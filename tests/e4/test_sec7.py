"""SEC-7 공개 보강 회귀. ASGI·합성 PDF만 사용하며 서버·제품 LLM을 호출하지 않는다."""

from __future__ import annotations

import asyncio
import copy
import io
import json
import logging
import subprocess
import sys
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import export, main, serving, upload
from neumann.models import PremortemResult
from scripts.serve_fake_app import fake_result
from tests.e4.test_export import fixture_result
from tests.e4.test_jobs import cfg_nolimit, make as make_jobs
from tests.e4.test_serving import client
from tests.e4.test_upload import KOREAN_LINES, make_pdf


def package_app(**limits):
    app = FastAPI()
    app.include_router(export.router)
    srv = serving.Serving(serving.ServingConfig(**limits))
    serving.install(app, srv)
    return app, srv


@pytest.mark.parametrize("protected", [False, True])
@pytest.mark.parametrize("case", ["cards", "card_lines", "decisions", "plan_lines", "plan_text", "embedded_lines", "chars"])
def test_package_rejects_before_model_validation_or_zip(monkeypatch, case, protected):
    payload = {"result": fixture_result().model_dump(mode="json")}
    if case == "cards":
        payload["result"]["risk_cards"] *= 51
    elif case == "card_lines":
        payload["result"]["risk_cards"][0]["why_applies"]["plan_lines"] = [1] * 201
    elif case == "decisions":
        payload["decisions"] = [{}] * 1001
    elif case == "plan_lines":
        payload["result"]["plan"]["lines"] = [{}] * 5001
    elif case == "plan_text":
        payload["plan_text"] = "x\r\n" * 5001
    elif case == "embedded_lines":
        payload["result"]["plan"]["lines"] = [{"no": 1, "text": "x\n" * 5001}]
    else:
        payload["result"]["plan"]["lines"] = [{"no": 1, "text": "x" * 50001}]

    def forbidden(*args, **kwargs):
        pytest.fail("oversized package reached expensive validation/build")

    monkeypatch.setattr(PremortemResult, "model_validate", forbidden)
    monkeypatch.setattr(export.PackageRequest, "model_validate", forbidden)
    monkeypatch.setattr(export, "build_package", forbidden)
    if protected:
        app, srv = package_app()
        # 조기 제한은 aux 입장보다 앞이다.
        monkeypatch.setattr(srv.aux_gate, "reserve", forbidden)
    else:
        app = FastAPI()
        app.include_router(export.router)
    resp = TestClient(app).post("/premortem/package", json=payload)
    assert resp.status_code == (413 if case == "chars" else 422)
    assert "[FAKE]" not in resp.text


def test_package_limits_bare_results_and_custom_serving_limits():
    result = fixture_result().model_dump(mode="json")
    result["risk_cards"] *= 51
    assert TestClient(package_app()[0]).post("/premortem/package", json=result).status_code == 422
    app, _ = package_app(max_plan_lines=20)
    assert TestClient(app).post("/premortem/package", json={"result": fixture_result().model_dump(mode="json")}).status_code == 422


def test_package_limit_boundaries_and_normal_zip():
    assert export.package_limit_refusal({"result": {"risk_cards": [{"why_applies": {"plan_lines": [1] * 200}}] * 100},
                                        "decisions": [{}] * 1000, "plan_text": "x\n" * 4999 + "x"}) is None
    assert export.package_limit_refusal({"plan_text": "x" * 50000}) is None
    assert TestClient(package_app()[0]).post("/premortem/package", json={"result": fixture_result().model_dump(mode="json")}).status_code == 200


def test_plan_annotations_deduplicate_with_stable_card_order():
    result = fixture_result()
    cards = []
    for i in range(100):
        card = result.risk_cards[0].model_copy(deep=True)
        card.card_id = f"test-card-{i}"
        card.why_applies.plan_lines = [1, 1, 2, 1]
        cards.append(card)
    result = result.model_copy(update={"risk_cards": cards})
    doc = export._plan_annotated(export._make_ctx(result, None, None)).decode()
    line = next(ln for ln in doc.splitlines() if "[C1,C2," in ln and " | " in ln)
    assert "[" + ",".join(f"C{i}" for i in range(1, 101)) + "]" in line
    assert line.count("C1,") == 1


@pytest.mark.parametrize("path", ["/", "/health", "/queue/status", "/missing", "/docs", "/boom"])
def test_security_headers_on_success_and_error(path):
    app, _ = package_app(hide_docs=True)
    app.add_api_route("/", lambda: {"status": "ok"})
    app.add_api_route("/health", lambda: {"status": "ok"})

    @app.get("/boom")
    def boom():
        raise RuntimeError("synthetic failure")

    resp = TestClient(app, raise_server_exceptions=False).get(path)
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["referrer-policy"] == "no-referrer"
    if path == "/boom":
        assert resp.status_code == 500
    elif path in {"/", "/health", "/queue/status"}:
        assert resp.status_code == 200
    else:
        assert resp.status_code == 404


def test_security_headers_on_protected_post_and_static_font(tmp_path, monkeypatch):
    srv, app, store = make_jobs(tmp_path, monkeypatch, fake_result, jobs_cfg=cfg_nolimit())

    async def go():
        async with client(app) as c:
            responses = [await c.post("/premortem/view", json={"plan_text": "normal research plan"}),
                         await c.post("/premortem/view", json={"plan_text": "x " * 25001}),
                         await c.post("/premortem/jobs", json={"plan_text": "another normal research plan"})]
            assert [r.status_code for r in responses] == [200, 413, 202]
            fonts = main.WEBUI_DIR / "fonts"
            font = next(fonts.rglob("*.woff2"))
            responses.append(await c.get("/fonts/" + font.relative_to(fonts).as_posix()))
            assert responses[-1].status_code == 200
            for resp in responses:
                for key, value in serving.SECURITY_HEADERS:
                    assert resp.headers[key.decode()] == value.decode()
            await asyncio.gather(*(j.task for j in store._jobs.values() if j.task is not None))
    asyncio.run(go())


def test_public_health_is_small_and_local_health_keeps_diagnostics(monkeypatch):
    monkeypatch.setattr(main, "_load_pipeline", lambda: (None, "unavailable", "private-path"))
    monkeypatch.setattr(main, "_llm_state", lambda: {"effective": "mock", "model": "", "live_llm_ok": False,
                                                  "key_present": True, "provider_requested": "openai", "astra_allowed": False})
    monkeypatch.setattr(main, "_import_state", lambda name: ("ok", ""))
    for public in (True, False):
        app, _ = package_app(public=public)
        app.add_api_route("/health", main.health)
        resp = TestClient(app).get("/health")
        body = resp.json()
        if public:
            assert set(body) == {"status", "version", "commit", "pipeline", "llm", "accepting"}
            assert set(body["llm"]) == {"effective", "model", "live_llm_ok"}
            assert "private-path" not in resp.text and "key_present" not in resp.text
        else:
            assert {"stages", "routers", "started_at"} <= body.keys()
            assert body["llm"]["key_present"] is True


@pytest.mark.parametrize("value", ["a, b", "garbage<script>", "999.1.1.1", "", "2001:db8::1%eth0"])
def test_invalid_cf_header_uses_peer_and_does_not_log_value(value, caplog, monkeypatch):
    monkeypatch.setattr(serving, "_BAD_IP_WARN", {"n": 0, "t": 0.0})
    scope = {"client": ("127.0.0.1", 1234), "headers": [(b"cf-connecting-ip", value.encode())]}
    with caplog.at_level(logging.WARNING):
        assert serving.client_ip(scope, "loopback") == "127.0.0.1"
    if value:
        assert value not in caplog.text


def test_valid_cf_header_and_ipv6_56_group():
    scope = {"client": ("127.0.0.1", 1234), "headers": [(b"cf-connecting-ip", b"2001:db8:1:10::1")]}
    assert serving.client_ip(scope, "loopback") == "2001:db8:1:10::1"
    assert serving.ip_key("2001:db8:1:10::1") == serving.ip_key("2001:db8:1:20::2")
    assert serving.ip_key("2001:db8:1:10::1") != serving.ip_key("2001:db8:1:100::2")
    assert serving.client_ip(scope, "never") == "127.0.0.1"


def test_queue_shares_leave_room_for_five_new_users_and_release_owners():
    gate = serving.Gate(6, 30, 60)
    held = []
    for owner in range(4):
        for n in range(10):
            if gate.share_refusal(str(owner), 10, 10) is None:
                held.append(gate.reserve(f"attack-{owner}-{n}", owner=str(owner)))
    assert len(held) == 27
    for owner in range(5):
        assert gate.share_refusal(f"new-{owner}", 10, 10) is None
        held.append(gate.reserve(f"new-{owner}", owner=f"new-{owner}"))
    assert gate.active + gate.waiting == 32
    for ticket in held:
        gate.cancel(ticket)
    assert gate._owners == {} and gate.active + gate.waiting == 0


def test_queue_share_is_enforced_on_job_admission(tmp_path, monkeypatch):
    srv, app, store = make_jobs(tmp_path, monkeypatch, fake_result, jobs_cfg=cfg_nolimit(), public=True,
                                 queue_per_ip=1, queue_reserve=1)
    ticket = srv.gate.reserve("held", owner=serving.ip_key("192.0.2.1"))

    async def go():
        async with client(app, "192.0.2.1") as c:
            resp = await c.post("/premortem/jobs", json={"plan_text": "research plan"})
            assert resp.status_code == 429 and resp.json()["error_code"] == "busy_ip"
        assert len(store) == 0
    try:
        asyncio.run(go())
    finally:
        srv.gate.cancel(ticket)


@pytest.mark.parametrize("path", ["/premortem", "/premortem/view", "/premortem/jobs"])
@pytest.mark.parametrize("sep", ["\n", "\r", "\r\n"])
def test_line_limits_before_pipeline_and_job_creation(path, sep, tmp_path, monkeypatch):
    calls = []
    srv, app, store = make_jobs(tmp_path, monkeypatch, lambda text: calls.append(text), jobs_cfg=cfg_nolimit())

    async def go():
        async with client(app) as c:
            resp = await c.post(path, json={"plan_text": sep.join(["x"] * 5001)})
            assert resp.status_code == 422 and resp.json()["error_code"] == "too_many_lines"
    asyncio.run(go())
    assert not calls and len(store) == 0
    assert srv.gate.active + srv.gate.waiting == 0


def test_upload_line_limits_after_cleanup():
    for sep in ("\n", "\r", "\r\n", "\u2028"):
        err = pytest.raises(upload.UploadRejected, upload.extract_plan, "plan.txt", sep.join(["x"] * 5001).encode()).value
        assert err.status_code == 422 and err.message == upload.TOO_MANY_LINES_MESSAGE
    assert upload.extract_plan("plan.txt", b"x\n" * 4999 + b"x").lines == 5000


@pytest.mark.parametrize("path", ["/health", "/missing"])
def test_get_rate_and_request_target_caps_are_early_and_ip_scoped(path):
    app, _ = package_app(get_rate_per_min=2, max_request_line=64)
    app.add_api_route("/health", lambda: {"status": "ok"})

    async def go():
        async with client(app, "192.0.2.1") as c:
            assert (await c.get(path + "?q=" + "x" * 64)).status_code == 414
            expected = 200 if path == "/health" else 404
            assert (await c.get(path)).status_code == expected
            assert (await c.get(path)).status_code == expected
            assert (await c.get(path)).status_code == 429
        async with client(app, "192.0.2.2") as c:
            assert (await c.get(path)).status_code == expected
    asyncio.run(go())


@pytest.mark.parametrize("variant", ["raw", "pct", "double", "triple", "+", "/", ".~", "%zz", "%25zz"])
def test_live_job_ids_are_masked_in_both_log_filters(variant):
    token = "TestJob_" + "aB7_" * 6
    encoded = "".join(f"%{ord(c):02X}" for c in token)
    shapes = {"raw": token, "pct": encoded, "double": quote(encoded), "triple": quote(quote(encoded))}
    value = shapes.get(variant, variant.join(token))
    serving.register_log_secret(token)
    try:
        assert serving.mask_live_secrets(value) == token[:6] + "…"
        for name in ("uvicorn.access", "neumann.test"):
            rec = logging.LogRecord(name, logging.INFO, __file__, 1, "value=%s", (value,), None)
            serving.RedactingFilter().filter(rec)
            assert value not in rec.getMessage()
    finally:
        serving.forget_log_secret(token)
    assert serving.mask_live_secrets(token) == token


def test_setting_name_is_not_masked_and_long_log_arguments_are_clipped():
    value = "NEUMANN_UPLOAD_RATE_PER_MIN"
    assert value in serving.mask_job_paths(f"설정 {value} 값이 잘못되었습니다")
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "%s", ("x" * 64000,), None)
    serving.RedactingFilter().filter(rec)
    assert len(rec.getMessage()) < 2100


def pdf_with_streams(contents):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    writer = PdfWriter()
    normal = PdfReader(io.BytesIO(make_pdf([["normal research plan"]])))
    for content in contents:
        page = copy.deepcopy(normal.pages[0])
        if content is not None:
            stream = DecodedStreamObject()
            stream.set_data(content)
            page[NameObject("/Contents")] = stream.flate_encode()
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_normal_12_page_pdf_isolated_and_oversized_page_warning():
    result = upload.extract_plan_isolated("normal.pdf", make_pdf([KOREAN_LINES] * 12))
    assert result.pages == 12 and "GNN" in result.text and not result.warnings
    heavy = b"%" + b"x" * upload.MAX_PDF_PAGE_STREAM
    result = upload.extract_plan_isolated("heavy.pdf", pdf_with_streams([None, heavy]))
    assert result.pages == 2 and result.text == "normal research plan"
    assert any("읽지 않은 쪽: 2" in w for w in result.warnings)


def test_pdf_decode_bomb_is_skipped_with_warning():
    data = pdf_with_streams([None, b"%" + b"x" * upload.MAX_PDF_STREAM_DECODE])
    result = upload.extract_plan_isolated("decode.pdf", data)
    assert len(data) < 20000
    assert result.text == "normal research plan" and any("읽지 않은 쪽: 2" in w for w in result.warnings)


def test_pdf_total_stream_budget_rejects_before_text_parsing():
    content = b"%" + b"x" * 899998 + b"\n"
    err = pytest.raises(upload.UploadRejected, upload.extract_plan_isolated, "total.pdf", pdf_with_streams([content] * 6)).value
    assert err.status_code == 413 and err.message == upload.PDF_COMPLEX_MESSAGE


def test_pdf_page_character_budget_and_empty_heavy_document():
    err = pytest.raises(upload.UploadRejected, upload.extract_plan_isolated, "text.pdf", make_pdf([["x" * 20001]])).value
    assert err.status_code == 413 and err.message == upload.PAGE_CHARS_MESSAGE
    err = pytest.raises(upload.UploadRejected, upload.extract_plan_isolated, "heavy.pdf",
                        pdf_with_streams([b"%" + b"x" * upload.MAX_PDF_PAGE_STREAM])).value
    assert err.status_code == 422 and "텍스트를 찾지 못했습니다" in err.message


@pytest.mark.parametrize("deferred", [False, True])
def test_pdf_refuses_when_stream_limits_are_unavailable(monkeypatch, deferred):
    from contextlib import contextmanager

    import pypdf

    def unavailable(**kwargs):
        raise TypeError("unsupported configuration")

    @contextmanager
    def unavailable_on_entry(**kwargs):
        unavailable(**kwargs)
        yield  # 실제 contextmanager처럼 __enter__ 시점에 실패한다.

    monkeypatch.setattr(pypdf, "apply_configuration", unavailable_on_entry if deferred else unavailable)
    err = pytest.raises(upload.UploadRejected, upload.extract_plan, "plan.pdf", make_pdf([KOREAN_LINES])).value
    assert err.status_code == 503 and "안전 제한" in err.message


def test_worker_memory_limit_is_active_and_denies_allocation():
    # 자기 작업자만 한 번 실행. 128MB 제한에서 160MB 할당이 실패하는지를 직접 잰다.
    code = ("import sys; sys.path.insert(0, 'src'); from neumann.api.upload import _limit_worker_memory; "
            "print('limited=' + str(_limit_worker_memory(128)), flush=True)\n"
            "try:\n x = bytearray(160 * 1024 * 1024); print('allocation_allowed')\n"
            "except MemoryError:\n print('allocation_denied')")
    proc = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert "limited=True" in proc.stdout and "allocation_denied" in proc.stdout


def test_worker_refuses_when_memory_limit_cannot_be_installed(monkeypatch):
    # 추출 전에 실패하는지를 확인. 감사 훅은 이 테스트 프로세스에 설치하지 않는다.
    monkeypatch.setattr(upload, "_deny_disk_writes", lambda: None)
    monkeypatch.setattr(upload, "_limit_worker_memory", lambda n: False)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"filename":"x.pdf","memory_mb":512}\n')))
    output = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(output))
    upload._worker_main()
    result = json.loads(output.getvalue())
    assert result["status"] == 503 and result["message"] == upload.MEMORY_LIMIT_MESSAGE
