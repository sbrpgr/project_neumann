"""E4-L2f 검증 보완: 결과 출처 서명(F1)·서식 안전(F4)·내보내기 413 문구(F6)·자유형 칸 화이트리스트(F2).

    NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4/test_export_ui_sign.py -q

- F1: 화면 응답(``build_ui_view``)이 원결과에 서버 서명(HMAC)을 붙이고 ``/premortem/package``가 확인한다.
  정상 서명 → ``server_signed``, 변조·서명 없음·형식 오류·재기동(키 새로 생성) → ``client_submitted_unverified``
  (README 첫 줄 경고, "제품 LLM이 만든"·"오프셋으로 잘라" 문구 없음). 키 값·키 설정 여부는 응답·ZIP·로그·/health에 없다.
- 브라우저 JSON 왕복(정수로 떨어지는 실수 1.0 → 1)과 jobs 응답의 진단 문구 가림(``scrub_ok_payload``)을 거쳐도 서명이 맞다.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from neumann.api import signing  # noqa: E402
from neumann.api.export import UNVERIFIED_WARNING, router  # noqa: E402
from neumann.api.view import build_ui_view  # noqa: E402

TEST_KEY = "unit-test-hmac-key-must-never-leak-7f3a9c"
SERVER_WORDING = ("제품 LLM", "오프셋으로 잘라", "원문[start:end]를 잘라 옮긴 값")


@pytest.fixture(autouse=True)
def _restore_key():
    yield
    signing.reset_key()  # 테스트가 바꾼 키를 프로세스 환경 기준으로 되돌린다


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _fixture() -> dict[str, Any]:
    return json.loads((ROOT / "tests" / "fixtures" / "premortem_result.json").read_text(encoding="utf-8"))


def _signed_view(res: dict[str, Any] | None = None) -> dict[str, Any]:
    view = build_ui_view(res or _fixture(), records=None)
    assert view["result"] is not None and view["result_sig"], view["_status"]["export"]
    return view


def _browser_roundtrip(obj: Any) -> Any:
    """브라우저 JSON.parse/stringify 왕복 흉내: 정수로 떨어지는 실수는 정수가 된다."""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _browser_roundtrip(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_browser_roundtrip(v) for v in obj]
    return obj


def _package(client: TestClient, result: dict[str, Any], sig: str | None, **extra: Any):
    body: dict[str, Any] = {"result": result, **extra}
    if sig is not None:
        body["result_sig"] = sig
    resp = client.post("/premortem/package", json=body)
    assert resp.status_code == 200, resp.text
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        files = {n: zf.read(n) for n in zf.namelist()}
    return resp, files


def _assert_unverified(resp, files) -> None:
    assert resp.headers["x-neumann-result-origin"] == "client_submitted_unverified"
    assert json.loads(files["manifest.json"])["result_origin"] == "client_submitted_unverified"
    assert json.loads(files["evidence_pack.json"])["result_origin"] == "client_submitted_unverified"
    for name in ("README.md", "neumann_report.md", "ai_context.md"):
        doc = files[name].decode("utf-8")
        assert doc.splitlines()[0] == UNVERIFIED_WARNING, name  # 첫 줄 경고
        for phrase in SERVER_WORDING:
            assert phrase not in doc, (name, phrase)
    assert "서버 서명이 없는 결과" in json.loads(files["evidence_pack.json"])["reverification"]["note"]


# ── F1 서명 ───────────────────────────────────────────────────────────────


def test_signed_result_packages_as_server_signed(client: TestClient) -> None:
    view = _signed_view()
    resp, files = _package(client, _browser_roundtrip(json.loads(json.dumps(view["result"]))), view["result_sig"])
    assert resp.headers["x-neumann-result-origin"] == "server_signed"
    manifest = json.loads(files["manifest.json"])
    assert manifest["result_origin"] == "server_signed"
    readme = files["README.md"].decode("utf-8")
    assert readme.startswith("# Neumann 내보내기 패키지") and UNVERIFIED_WARNING not in readme
    assert "`server_signed`" in readme
    assert "오프셋으로 잘라" in files["neumann_report.md"].decode("utf-8")  # 서버 결과는 서버 문구 그대로


def test_integral_float_roundtrip_keeps_signature() -> None:
    res = _fixture()
    res["risk_cards"][0]["score"]["similarity"] = 1.0  # 브라우저에서 1이 되는 값
    view = _signed_view(res)
    assert view["result"]["risk_cards"][0]["score"]["similarity"] == 1.0
    assert signing.verify_result(_browser_roundtrip(view["result"]), view["result_sig"])


@pytest.mark.parametrize("tamper", ["generator_astra", "why_text", "card_title", "score", "session_id"])
def test_tampered_result_is_unverified(client: TestClient, tamper: str) -> None:
    view = _signed_view()
    res = json.loads(json.dumps(view["result"]))
    if tamper == "generator_astra":  # 가짜 카드에 astra를 넣어 "제품 LLM이 만든 카드"로 보이게 하려는 시도
        for card in res["risk_cards"]:
            card["generator"] = "astra"
            card["model"] = "gpt-6.1-sol"
    elif tamper == "why_text":
        res["risk_cards"][0]["why_applies"]["text"] += " (덧붙임)"
    elif tamper == "card_title":
        res["risk_cards"][0]["title"] = "지어낸 위험"
    elif tamper == "score":
        res["risk_cards"][0]["score"]["severity"] = 0.99
    else:
        res["session_id"] = "forged-session"
    # 인용 문구·plan_id를 바꾸면 계약 검증(text_sha256·plan.plan_id 대조)이 먼저 422로 막는다(아래 테스트)
    resp, files = _package(client, res, view["result_sig"])
    _assert_unverified(resp, files)
    if tamper == "generator_astra":  # DISP-1 병합 뒤: 표기만 옮기고(모델명 없음) 사람용 문서에 astra 글자 없음
        readme = files["README.md"].decode("utf-8")
        assert "LLM(결과에 적힌 표기, 미확인)" in readme
        assert "gpt-6.1-sol" not in readme and "제품 LLM" not in readme
        _assert_no_astra(files)


def _human_lines(doc: str) -> str:
    """사람이 보는 문장만: 코드 블록(```json … ```, 결과 값 그대로)과 DISP-1 JSON 설명 줄은 뺀다."""
    from neumann.api.export import JSON_GENERATOR_NOTE

    out, fence = [], False
    for ln in doc.splitlines():
        if ln.startswith("```"):
            fence = not fence
            continue
        if not fence and JSON_GENERATOR_NOTE not in ln:
            out.append(ln)
    return chr(10).join(out)


def _assert_no_astra(files: dict[str, bytes]) -> None:
    for name in ("README.md", "neumann_report.md", "plan_annotated.md", "ai_context.md"):
        assert "astra" not in _human_lines(files[name].decode("utf-8")).lower(), name


def test_signed_llm_cards_show_model_and_no_astra(client: TestClient) -> None:
    res = _fixture()
    for card in res["risk_cards"]:
        card["generator"], card["model"] = "astra", "gpt-6.1-sol"
    view = _signed_view(res)
    resp, files = _package(client, view["result"], view["result_sig"])
    assert resp.headers["x-neumann-result-origin"] == "server_signed"
    readme = files["README.md"].decode("utf-8")
    assert "LLM (gpt-6.1-sol)" in readme and "제품 LLM" in readme  # 서명 확인된 결과는 DISP-1 이름 + 서버 설명
    _assert_no_astra(files)


def test_contract_rejects_quote_or_plan_id_tamper(client: TestClient) -> None:
    view = _signed_view()
    res = json.loads(json.dumps(view["result"]))
    res["evidence"][0]["text"] += " (덧붙임)"
    assert client.post("/premortem/package", json={"result": res, "result_sig": view["result_sig"]}).status_code == 422
    res = json.loads(json.dumps(view["result"]))
    res["plan_id"] = "0" * 64
    assert client.post("/premortem/package", json={"result": res, "result_sig": view["result_sig"]}).status_code == 422


@pytest.mark.parametrize("sig", [None, "", "v1.", "v1." + "0" * 64, "v2." + "a" * 64, "not-a-signature"])
def test_missing_or_malformed_signature_is_unverified(client: TestClient, sig: str | None) -> None:
    view = _signed_view()
    resp, files = _package(client, view["result"], sig)
    _assert_unverified(resp, files)


def test_restart_with_random_key_invalidates_old_signature(client: TestClient, monkeypatch) -> None:
    monkeypatch.delenv(signing.KEY_ENV, raising=False)
    signing.reset_key()
    view = _signed_view()
    assert signing.verify_result(view["result"], view["result_sig"])
    signing.reset_key()  # 재기동: 키가 없으니 새 무작위 키
    assert not signing.verify_result(view["result"], view["result_sig"])
    _assert_unverified(*_package(client, view["result"], view["result_sig"]))


def test_restart_with_configured_key_keeps_signature(monkeypatch) -> None:
    monkeypatch.setenv(signing.KEY_ENV, TEST_KEY)
    signing.reset_key()
    view = _signed_view()
    signing.reset_key()  # 재기동: 같은 환경변수 키
    assert signing.verify_result(view["result"], view["result_sig"])
    monkeypatch.setenv(signing.KEY_ENV, TEST_KEY + "-rotated")
    signing.reset_key()  # 키를 바꾸면 옛 서명은 무효
    assert not signing.verify_result(view["result"], view["result_sig"])


def test_key_never_leaks_to_view_zip_logs_or_health(client: TestClient, monkeypatch, caplog) -> None:
    monkeypatch.setenv(signing.KEY_ENV, TEST_KEY)
    signing.reset_key()
    caplog.set_level(logging.DEBUG)
    view = _signed_view()
    blob = json.dumps(view, ensure_ascii=False)
    assert TEST_KEY not in blob and signing.KEY_ENV not in blob
    resp, files = _package(client, view["result"], view["result_sig"])
    tampered = dict(view["result"], session_id="forged-session")
    resp2, files2 = _package(client, tampered, view["result_sig"])
    for payload in (resp.content, resp2.content, *files.values(), *files2.values(),
                    json.dumps(dict(resp.headers)).encode(), json.dumps(dict(resp2.headers)).encode()):
        assert TEST_KEY.encode() not in payload
    assert TEST_KEY not in caplog.text

    from neumann.api.main import app

    health = TestClient(app).get("/health")
    assert health.status_code == 200
    text = health.text
    assert TEST_KEY not in text and signing.KEY_ENV not in text and "hmac" not in text.lower()


def test_jobs_scrub_does_not_break_signature() -> None:
    """jobs 응답은 뷰 전체에 scrub_ok_payload를 한 번 더 건다 — 서명한 원결과가 바뀌지 않아야 한다."""
    from neumann.api.serving import scrub_ok_payload

    res = _fixture()
    res["notices"] = list(res.get("notices", [])) + [r"색인 읽기 실패 C:\Users\someone\data\index\works.jsonl"]
    view = _signed_view(res)
    assert "someone" not in json.dumps(view["result"], ensure_ascii=False)  # 서명 전에 같은 규칙으로 가림
    again = scrub_ok_payload(view)
    assert again["result"] == view["result"]
    assert signing.verify_result(again["result"], again["result_sig"])


def test_sample_and_error_views_have_no_signature() -> None:
    assert build_ui_view(_fixture(), sample=True, pipeline_state="unavailable")["result_sig"] is None
    assert build_ui_view(None, pipeline_state="error", error="파이프라인 실행 실패: X")["result_sig"] is None


# ── F2 자유형 칸 화이트리스트 ───────────────────────────────────────────────


def test_free_form_manifest_and_checklist_keys_are_whitelisted() -> None:
    res = _fixture()
    res["manifest"] = {"pipeline_version": "p1", "llm_model": "gpt-6.1-sol", "debug_path": "C:/secret/x",
                       "raw_prompt": "system: ..."}
    res["checklist"] = [{"item_id": "C1", "action": "표본 크기 근거를 적는다", "decision": None, "note": "",
                         "internal_trace": "stack ..."}]
    view = build_ui_view(res, records=None)
    raw = view["result"]
    assert raw["manifest"] == {"pipeline_version": "p1", "llm_model": "gpt-6.1-sol"}
    assert set(raw["checklist"][0]) == {"item_id", "action", "decision", "note"}
    assert view["_status"]["export"]["dropped_keys"] == [
        "checklist[].internal_trace", "manifest.debug_path", "manifest.raw_prompt"]
    blob = json.dumps(view, ensure_ascii=False)
    assert "C:/secret/x" not in blob and "internal_trace" not in json.dumps(raw)
    assert signing.verify_result(raw, view["result_sig"])


# ── F4 서식 안전 ──────────────────────────────────────────────────────────


def test_csv_formula_and_markdown_html_are_neutralised(client: TestClient) -> None:
    res = _fixture()
    res["similar_works"][0]["title"] = '=HYPERLINK("http://evil.example","x")'
    res["similar_works"][0]["venue"] = "@SUM(A1)"
    res["risk_cards"][0]["title"] = "<script>alert(1)</script> 표본 & 대조군"
    res["risk_cards"][0]["card_id"] = res["risk_cards"][0]["card_id"]  # id는 그대로(참조 무결성)
    quote_id = res["risk_cards"][0]["evidence"][0]
    ex = next(e for e in res["evidence"] if e["excerpt_id"] == quote_id)
    view = _signed_view(res)
    resp, files = _package(client, view["result"], view["result_sig"])
    rows = list(csv.reader(io.StringIO(files["similar_works.csv"].decode("utf-8-sig"))))
    head = rows[0]
    first = dict(zip(head, rows[1], strict=False))
    assert first["title"].startswith("'=HYPERLINK") and first["venue"] == "'@SUM(A1)"
    for name in ("README.md", "neumann_report.md", "plan_annotated.md", "ai_context.md"):
        doc = files[name].decode("utf-8")
        assert "<script>" not in doc, name
    report = files["neumann_report.md"].decode("utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt; 표본 &amp; 대조군" in report
    # 글자 그대로의 인용은 evidence_pack.json에 남는다
    pack = json.loads(files["evidence_pack.json"])
    assert any(e["text"] == ex["text"] for c in pack["cards"] for e in c["evidence"])


def test_ai_context_quote_json_escapes_html_but_decodes_verbatim() -> None:
    from neumann.api.export import build_package_files

    res = _fixture()
    ex_id = res["risk_cards"][0]["evidence"][0]
    ex = next(e for e in res["evidence"] if e["excerpt_id"] == ex_id)
    files = build_package_files(res)
    ctx = files["ai_context.md"].decode("utf-8")
    line = next(ln for ln in ctx.splitlines() if ln.strip().startswith(f"- [{ex_id}] "))
    quoted = line.split(f"- [{ex_id}] ", 1)[1].rsplit(" (", 1)[0]
    assert json.loads(quoted) == ex["text"]


# ── F6 내보내기 413 문구 ─────────────────────────────────────────────────


def test_export_413_message_is_specific() -> None:
    from neumann.api.main import app

    too_big = b'{"result": {"x": "' + b"a" * (4 * 1024 * 1024 + 10) + b'"}}'
    resp = TestClient(app).post("/premortem/package", content=too_big, headers={"Content-Type": "application/json"})
    assert resp.status_code == 413
    assert resp.json()["message"] == "내보낼 결과가 너무 큽니다(최대 4MB)."


# ── 서명 재검증 R1~R4·M10 ─────────────────────────────────────────────────


@pytest.mark.parametrize("sig", [
    "v1." + "é" * 64,                     # 비ASCII(예전에는 compare_digest TypeError → 500)
    "v1." + "０" * 64,                     # 전각 숫자
    "v1." + "A" * 64,                      # 대문자 hex
    "v1." + "0" * 63 + " ",                # 공백
    "v1." + "0" * 64 + "\n",               # 줄바꿈 꼬리
    "ｖ1." + "0" * 64,                     # 전각 접두
    "v1." + "0" * 65,                      # 길이
])
def test_r1_malformed_signature_is_unverified_not_500(client: TestClient, sig: str) -> None:
    view = _signed_view()
    assert signing.verify_result(view["result"], sig) is False
    resp, files = _package(client, view["result"], sig)  # 200 + unverified(500 아님)
    _assert_unverified(resp, files)


def test_r2_short_key_falls_back_to_random_with_warning(monkeypatch, caplog) -> None:
    short = "short-key-15byt"
    assert len(short.encode()) == 15
    monkeypatch.setenv(signing.KEY_ENV, short)
    caplog.set_level(logging.WARNING, logger="neumann.api.signing")
    signing.reset_key()
    assert any("무작위 키" in r.getMessage() for r in caplog.records)
    assert short not in caplog.text
    view = _signed_view()
    signing.reset_key()  # 같은 짧은 키로 재기동해도 무작위 키라 옛 서명 무효(짧은 키는 쓰지 않았다는 증거)
    assert not signing.verify_result(view["result"], view["result_sig"])
    monkeypatch.setenv(signing.KEY_ENV, "x" * 16)  # 16바이트면 쓴다
    caplog.clear()
    signing.reset_key()
    assert not caplog.records
    view = _signed_view()
    signing.reset_key()
    assert signing.verify_result(view["result"], view["result_sig"])


def test_r3_other_free_form_fields_are_whitelisted() -> None:
    res = _fixture()
    res["expected_review"] = {"generator": "rule", "strength": [], "weakness": [], "request": [],
                              "debug_prompt": "system: …", "raw_response": {"x": 1}}
    res["verification"] = {"quotes_total": 3, "quotes_verified": 3, "internal_path": "C:/x"}
    res["risk_synthesis"] = {"pool_size": 4, "trace": "..."}
    res["plan_checks"] = {"fitness": {"verdict": "fit"}, "llm_raw": "..."}
    res["research_questions"] = {"q1": "…"}
    res["post_status"] = [{"post_status_id": "ps1", "kind": "retraction", "work_id": "w1", "secret": 1}]
    view = build_ui_view(res, records=None)
    raw = view["result"]
    assert set(raw["expected_review"]) == {"generator", "strength", "weakness", "request"}
    assert raw["verification"] == {"quotes_total": 3, "quotes_verified": 3}
    assert raw["risk_synthesis"] == {"pool_size": 4}
    assert raw["plan_checks"] == {"fitness": {"verdict": "fit"}}
    assert raw["research_questions"] == {}
    assert raw["post_status"] == [{"post_status_id": "ps1", "kind": "retraction", "work_id": "w1"}]
    assert view["_status"]["export"]["dropped_keys"] == [
        "expected_review.debug_prompt", "expected_review.raw_response", "plan_checks.llm_raw",
        "post_status[].secret", "research_questions.q1", "risk_synthesis.trace", "verification.internal_path"]
    assert signing.verify_result(raw, view["result_sig"])


def _real_results() -> list[Path]:
    data = Path(os.environ.get("NEUMANN_DATA_DIR") or ROOT.parents[2] / "data")
    return sorted(p for p in [*(data / "precomputed").glob("*.json"), *(data / "eval" / "neumann_runs").glob("*.json")]
                  if p.name != "manifest.json")


def test_r3_real_results_lose_no_keys_and_package_unchanged() -> None:
    """실제 결과(사전 계산본·백테스트 실행)는 화이트리스트로 빠지는 키가 없고, 패키지 출력(생성 시각 고정)이 같다."""
    from datetime import UTC, datetime

    from neumann.api.export import build_package_files
    from neumann.api.view import export_result
    from neumann.models import PremortemResult

    paths = _real_results()
    if not paths:
        pytest.skip("공유 데이터 폴더에 실제 결과가 없다")
    when = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    checked = 0
    for path in paths:
        try:
            orig = PremortemResult.model_validate(json.loads(path.read_text(encoding="utf-8"))).model_dump(mode="json")
        except Exception:  # noqa: BLE001 - 결과 모양이 아닌 파일은 건너뛴다
            continue
        raw, reason, dropped = export_result(orig)
        assert raw is not None, (path.name, reason)
        assert dropped == [], (path.name, dropped)
        assert build_package_files(raw, created_at=when) == build_package_files(orig, created_at=when), path.name
        checked += 1
    assert checked >= 3, checked


def test_r4_markdown_link_image_and_stage_names_are_neutralised(client: TestClient) -> None:
    res = _fixture()
    img = "![x](https://evil.example/pixel.png)"
    res["risk_cards"][0]["title"] = "제목 " + img + " [링크](https://evil.example) " + BS + "[이미 이스케이프]"
    res["notices"] = [f"알림 {img}"]
    res["stages"] = [{"stage": f"search{img}<b>", "state": "degraded", "detail": f"사유 {img}", "phase": "EVIDENCE",
                      "impl": "x"}]
    res["status"] = "degraded"
    view = _signed_view(res)
    resp, files = _package(client, view["result"], view["result_sig"])
    for name in ("README.md", "neumann_report.md", "ai_context.md", "plan_annotated.md"):
        doc = files[name].decode("utf-8")
        assert not _live_link_syntax(doc), (name, _live_link_syntax(doc))  # 이미지·링크 문법이 살아 있지 않다
        assert "<b>" not in doc, name
    ctx = files["ai_context.md"].decode("utf-8")
    escaped_img = "!" + BS + "[x" + BS + "](https://evil.example/pixel.png)"
    assert f"정상이 아닌 단계: search{escaped_img}&lt;b&gt;: degraded" in ctx
    report = files["neumann_report.md"].decode("utf-8")
    assert BS * 3 + "[이미 이스케이프" + BS + "]" in report  # 원래 백슬래시도 글자로 남는다(두 배 + 괄호 앞 하나)


BS = chr(92)  # 백슬래시(소스에 이스케이프를 섞지 않으려고)


def _escaped(doc: str, i: int) -> bool:
    """doc[i] 앞에 백슬래시가 홀수 개면 이스케이프된 글자다."""
    n = 0
    while i - 1 - n >= 0 and doc[i - 1 - n] == BS:
        n += 1
    return n % 2 == 1


def _live_link_syntax(doc: str) -> list[str]:
    """이스케이프되지 않은 이미지 시작(![)이나 링크 닫기(](): 렌더러가 링크·이미지로 읽을 자리."""
    bad = []
    for i, ch in enumerate(doc):
        if ch == "[" and not _escaped(doc, i) and i > 0 and doc[i - 1] == "!":
            bad.append(doc[max(0, i - 10):i + 20])
        if ch == "]" and doc[i + 1:i + 2] == "(" and not _escaped(doc, i):
            bad.append(doc[max(0, i - 10):i + 20])
    return bad


def test_m10_int_float_normalisation_in_free_form_fields() -> None:
    """정수로 떨어지는 실수 정규화(M10): 자유형 칸은 모델이 형을 바꾸지 않으므로 여기서 잡힌다."""
    res = _fixture()
    res["manifest"] = {"total_s": 12.0, "timings_s": {"search": 3.0, "extract_issues": 1.25}}
    view = _signed_view(res)
    assert view["result"]["manifest"]["total_s"] == 12.0 and isinstance(view["result"]["manifest"]["total_s"], float)
    back = _browser_roundtrip(view["result"])
    assert isinstance(back["manifest"]["total_s"], int)  # 브라우저 왕복 뒤 12
    assert signing.canonical_bytes(back) == signing.canonical_bytes(view["result"])
    assert signing.verify_result(back, view["result_sig"])
    changed = json.loads(json.dumps(back))
    changed["manifest"]["timings_s"]["extract_issues"] = 1.26  # 정수가 아닌 값은 그대로 구별
    assert not signing.verify_result(changed, view["result_sig"])
    big = json.loads(json.dumps(view["result"]))
    big["manifest"]["total_s"] = float(2**53)  # 2^53 이상은 정수로 바꾸지 않는다(브라우저 정밀도 밖)
    assert b"9007199254740992.0" in signing.canonical_bytes(big)
