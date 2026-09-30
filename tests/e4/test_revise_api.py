"""E3-L2r API 검사: POST /premortem/revise · /premortem/revise/assemble이 서빙 관문(차단·속도 제한·상한·대기열·시간 상한)을
그대로 거치고, 계약 JSON·md·docx를 돌려주며, 관문 없는 요청은 받지 않는다. 실제 파이프라인·OpenAI 없음(mock provider)."""

from __future__ import annotations

import asyncio
import io
import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from neumann.analyze import revise as revise_mod
from neumann.analyze.revise import validate_revision
from neumann.api import revise as revise_api
from neumann.api import serving
from scripts.serve_fake_app import fake_result, integrate
from tests.e3.revise_fixtures import make_store
from tests.fixtures.loader import load_fixtures, plan_text

PLAN = plan_text("plan.md")


@pytest.fixture(autouse=True)
def _records(monkeypatch):
    monkeypatch.setattr(revise_mod, "default_record_store", lambda: make_store())
    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "mock")
    monkeypatch.delenv("NEUMANN_REVISE_TIMEOUT_S", raising=False)


def make(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **cfg: Any) -> tuple[serving.Serving, Any]:
    base: dict[str, Any] = dict(max_concurrent=2, queue_max=4, rate_per_min=0, cache_enabled=False,
                                cache_dir=tmp_path / "results", request_timeout_s=30.0, avg_run_s=0.1,
                                block_file=tmp_path / "serving_block.flag")
    base.update(cfg)
    srv = serving.Serving(serving.ServingConfig(**base))
    app = integrate(srv, lambda plan_text: fake_result(plan_text), monkeypatch.setattr)
    assert revise_api.install(app, srv=srv)
    return srv, app


def client(app: Any, ip: str = "127.0.0.1") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(ip, 5000)), base_url="http://t", timeout=30)


def result_json() -> dict[str, Any]:
    return load_fixtures().premortem_result.model_dump(mode="json")


def run(coro):
    return asyncio.run(coro)


# ── /premortem/revise ─────────────────────────────────────────────────────


def test_revise_happy_path_contract_and_gate_release(tmp_path, monkeypatch):
    srv, app = make(tmp_path, monkeypatch)

    async def go() -> None:
        async with client(app) as c:
            r = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
            assert r.status_code == 200, r.text
            body = r.json()
            assert validate_revision(body) == []
            assert body["generator"] == "mock" and len(body["revisions"]) == 2 and body["cost"]["llm_calls"] == 2
            assert "revision_sig" in body  # 서명 모듈(E4-L2f)이 없으면 null
            assert r.headers["x-neumann-ticket"] and r.headers["cache-control"] == "no-store"
            assert "Traceback" not in r.text and "C:\\\\" not in r.text
            one = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN, "card_ids": ["card-fx-leak"]})
            assert one.status_code == 200 and [x["card_id"] for x in one.json()["revisions"]] == ["card-fx-leak"]
            assert one.json()["cards_requested"] == ["card-fx-leak"]
    run(go())
    assert srv.gate.active == 0 and srv.gate.waiting == 0
    assert srv.counters["requests"] == 2


def test_revise_rejects_mismatched_plan_and_invalid_result(tmp_path, monkeypatch):
    srv, app = make(tmp_path, monkeypatch)

    async def go() -> None:
        async with client(app) as c:
            r = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN + "\n바뀐 줄"})
            assert r.status_code == 422 and r.json()["error_code"] == "plan_mismatch"
            assert srv.gate.active == srv.gate.waiting == srv.budget.used == 0
            r = await c.post("/premortem/revise", json={"result": {"session_id": "x", "plan_id": "y", "bogus": "SECRET_VALUE_9f3"},
                                                        "plan_text": PLAN})
            assert r.status_code == 422 and r.json()["error_code"] == "invalid_request"
            assert "SECRET_VALUE_9f3" not in r.text  # 입력 값을 되돌려 보내지 않는다(위치·종류만)
            assert srv.gate.active == srv.gate.waiting == srv.budget.used == 0
            r = await c.post("/premortem/revise", json={"plan_text": PLAN})
            assert r.status_code == 422
            assert srv.gate.active == srv.gate.waiting == srv.budget.used == 0
    run(go())


def test_revise_goes_through_block_switch_rate_limit_and_size_cap(tmp_path, monkeypatch):
    srv, app = make(tmp_path, monkeypatch, rate_per_min=1, max_plan_chars=len(PLAN) + 10)

    async def go() -> None:
        async with client(app) as c:
            ok = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
            assert ok.status_code == 200
            limited = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
            assert limited.status_code == 429 and limited.json()["error_code"] == "rate_limited" and limited.headers["retry-after"]
        async with client(app, ip="10.0.0.7") as c:
            big = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN + "x" * 100})
            assert big.status_code == 413 and big.json()["error_code"] == "too_large"
            (tmp_path / "serving_block.flag").write_text("1")
            blocked = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
            assert blocked.status_code == 503 and blocked.json()["error_code"] == "blocked"
    run(go())
    assert srv.counters["rate_429"] >= 1 and srv.counters["too_large_413"] >= 1 and srv.counters["blocked_503"] >= 1


def test_revise_second_line_admission_when_middleware_skipped_reservation(tmp_path, monkeypatch):
    """같은 계획서 분석이 캐시에 있으면 미들웨어는 자리를 잡지 않는다. 그래도 핸들러가 입장 검사를 다시 거친다(차단 → 503)."""
    srv, app = make(tmp_path, monkeypatch, cache_enabled=True)
    pid = serving.plan_key(PLAN)
    srv.cache.put(pid, {**fake_result(PLAN), "plan_id": pid, "status": "ok"})
    assert srv.cache.has(pid)

    async def go() -> None:
        async with client(app) as c:
            ok = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
            assert ok.status_code == 200
            (tmp_path / "serving_block.flag").write_text("1")
            blocked = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
            assert blocked.status_code == 503 and blocked.json()["error_code"] == "blocked"
    run(go())
    assert srv.gate.active == 0


def test_revise_not_gated_is_refused(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(revise_api.router)  # 서빙 층 없이 붙인 경우(관문 없는 경로) → 받지 않는다

    async def go() -> None:
        async with client(app) as c:
            r = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
            assert r.status_code == 503 and r.json()["error_code"] == "unavailable"
    run(go())
    assert revise_api.install(app) is False  # serving.install이 없으면 붙이지 않는다


def test_revise_timeout_is_user_message(tmp_path, monkeypatch):
    srv, app = make(tmp_path, monkeypatch)
    monkeypatch.setenv("NEUMANN_REVISE_TIMEOUT_S", "0.3")

    def slow(req, **kw):
        time.sleep(1.0)
        return {}

    monkeypatch.setattr(revise_api, "run_revision", slow)

    async def go() -> None:
        async with client(app) as c:
            r = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
            assert r.status_code == 504 and r.json()["error_code"] == "timeout"
            assert "0초" in r.json()["message"] and "Traceback" not in r.text
    run(go())
    assert srv.gate.active == 0


def many_cards(count: int) -> dict[str, Any]:
    import copy

    out = result_json()
    source = out["risk_cards"][0]
    out["risk_cards"] = [{**copy.deepcopy(source), "card_id": f"card-limit-{i}"} for i in range(count)]
    return out


@pytest.mark.parametrize("explicit", [False, True])
def test_revise_card_amplification_refused_and_refunded(tmp_path, monkeypatch, explicit):
    srv, app = make(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(revise_api, "run_revision", lambda *a, **k: calls.append(1))
    result = many_cards(9)
    body = {"result": result, "plan_text": PLAN}
    if explicit:
        body["card_ids"] = [r["card_id"] for r in result["risk_cards"]]

    async def go():
        async with client(app) as c:
            response = await c.post("/premortem/revise", json=body)
            assert response.status_code == 422
            assert srv.gate.active == srv.gate.waiting == srv.budget.used == 0
            assert calls == []
    run(go())


def test_timeout_cancels_queued_cards_and_holds_slot_until_threads_finish(tmp_path, monkeypatch):
    from tests.e3.revise_fixtures import FakeCall

    srv, app = make(tmp_path, monkeypatch, max_concurrent=1)
    monkeypatch.setenv("NEUMANN_REVISE_TIMEOUT_S", "0.2")
    release = threading.Event()
    started = []

    def respond(schema, text):
        started.append(1)
        assert release.wait(3), "test must release its workers"
        return {"interpretation": [], "precedents": [], "edits": [], "questions": []}

    def call_for(*args):
        return FakeCall(respond, generator="mock"), {"effort": "medium"}, None

    monkeypatch.setattr(revise_mod, "_llm_call_for", call_for)

    async def go():
        try:
            async with client(app) as c:
                response = await c.post("/premortem/revise", json={"result": many_cards(8), "plan_text": PLAN})
                assert response.status_code == 504
                assert 1 <= len(started) <= 4
                count = len(started)
                assert srv.gate.active == 1 and srv.gate.waiting == 0
                release.set()
                for _ in range(100):
                    if srv.gate.active == 0:
                        break
                    await asyncio.sleep(0.01)
                assert srv.gate.active == srv.gate.waiting == 0
                assert len(started) == count  # 취소된 대기 카드는 호출하지 않는다.
        finally:
            release.set()
    run(go())


def test_queue_timeout_refunds_unstarted_work(tmp_path, monkeypatch):
    srv, app = make(tmp_path, monkeypatch, max_concurrent=1)
    monkeypatch.setenv("NEUMANN_REVISE_TIMEOUT_S", "0.05")

    async def go():
        occupied = srv.gate.reserve("test-occupancy", "unrelated-plan")
        try:
            async with client(app) as c:
                response = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
                assert response.status_code == 504
                assert srv.gate.active == 1 and srv.gate.waiting == srv.budget.used == 0
        finally:
            srv.gate.cancel(occupied)
    run(go())


def test_revise_internal_error_is_user_message(tmp_path, monkeypatch):
    _srv, app = make(tmp_path, monkeypatch)

    def boom(req, **kw):
        raise RuntimeError("C:\\Users\\someone\\secret\\revise_internal.py")

    monkeypatch.setattr(revise_api, "run_revision", boom)

    async def go() -> None:
        async with client(app) as c:
            r = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
            assert r.status_code == 500 and r.json()["error_code"] == "internal"
            assert "someone" not in r.text and "RuntimeError" not in r.text
    run(go())


# ── /premortem/revise/assemble ───────────────────────────────────────────


async def _bundle(c: httpx.AsyncClient) -> dict[str, Any]:
    r = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
    assert r.status_code == 200
    return r.json()


def _decisions(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    edits = [e for rev in bundle["revisions"] for e in rev["edits"]]
    return [{"edit_id": edits[0]["edit_id"], "decision": "채택"},
            {"edit_id": edits[1]["edit_id"], "decision": "수정", "revised_text": "조성 그룹 단위 분할로 바꾸고 중복은 분할 전에 제거한다."}]


def test_assemble_json_md_docx_and_polish(tmp_path, monkeypatch):
    from docx import Document

    from neumann.analyze.assemble import validate_revised_plan

    _srv, app = make(tmp_path, monkeypatch)

    async def go() -> None:
        async with client(app) as c:
            bundle = await _bundle(c)
            body = {"plan_text": PLAN, "revision": bundle, "decisions": _decisions(bundle), "result": result_json()}
            r = await c.post("/premortem/revise/assemble", json=body)
            assert r.status_code == 200, r.text
            out = r.json()
            assert validate_revised_plan(out) == []
            assert out["stats"]["applied"] == 2 and out["polish"] == {**out["polish"], "requested": False, "applied": False}
            assert set(out["markdown"]) == {"clean", "footnoted", "history"} and out["label"].startswith("Neumann 수정 제안")
            assert out["docx_available"] is True and "revised_plan_sig" in out
            assert out["markdown"]["clean"] == out["revised_text"]
            md = await c.post("/premortem/revise/assemble", json={**body, "format": "md"})
            assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
            assert "[^1]" in md.text and "## 수정 이력" in md.text
            dx = await c.post("/premortem/revise/assemble", json={**body, "format": "docx", "title": "수정본 시험"})
            assert dx.status_code == 200 and dx.headers["content-type"] == revise_api.DOCX_MEDIA
            assert dx.content[:2] == b"PK" and dx.headers["x-neumann-changes"] == "2"
            doc = Document(io.BytesIO(dx.content))
            assert doc.paragraphs[0].text == "수정본 시험" and doc.tables
            pol = await c.post("/premortem/revise/assemble", json={**body, "polish": True})
            assert pol.status_code == 200 and pol.json()["polish"]["applied"] is True and pol.json()["polish"]["generator"] == "mock"
    run(go())


def test_assemble_rejects_bad_revision_and_mismatch(tmp_path, monkeypatch):
    srv, app = make(tmp_path, monkeypatch)

    async def go() -> None:
        async with client(app) as c:
            bundle = await _bundle(c)
            baseline = srv.budget.used
            r = await c.post("/premortem/revise/assemble", json={"plan_text": PLAN, "revision": {"version": "x"}, "decisions": []})
            assert r.status_code == 422 and r.json()["error_code"] == "invalid_request"
            assert srv.gate.active == srv.gate.waiting == 0 and srv.budget.used == baseline
            r = await c.post("/premortem/revise/assemble", json={"plan_text": PLAN + "\n다른 계획서", "revision": bundle, "decisions": []})
            assert r.status_code == 422 and r.json()["error_code"] == "plan_mismatch"
            assert srv.gate.active == srv.gate.waiting == 0 and srv.budget.used == baseline
            other = {**result_json(), "plan_id": "0" * 64, "plan": None}
            r = await c.post("/premortem/revise/assemble", json={"plan_text": PLAN, "revision": bundle, "decisions": [], "result": other})
            assert r.status_code == 422 and r.json()["error_code"] == "plan_mismatch"
            assert srv.gate.active == srv.gate.waiting == 0 and srv.budget.used == baseline
            r = await c.post("/premortem/revise/assemble", json={"plan_text": PLAN, "revision": bundle, "result": {}})
            assert r.status_code == 422
            assert srv.gate.active == srv.gate.waiting == 0 and srv.budget.used == baseline
            r = await c.post("/premortem/revise/assemble", json={"plan_text": PLAN, "revision": bundle, "decisions": [], "format": "pdf"})
            assert r.status_code == 422
            assert srv.gate.active == srv.gate.waiting == 0 and srv.budget.used == baseline
    run(go())


def test_assemble_conflict_listed_via_api(tmp_path, monkeypatch):
    _srv, app = make(tmp_path, monkeypatch)

    async def go() -> None:
        async with client(app) as c:
            bundle = await _bundle(c)
            e0 = bundle["revisions"][0]["edits"][0]
            bundle["revisions"][0]["edits"].append({**e0, "edit_id": e0["edit_id"] + "b", "proposed_text": "다른 안"})
            decisions = [{"edit_id": e0["edit_id"], "decision": "adopt"}, {"edit_id": e0["edit_id"] + "b", "decision": "adopt"}]
            r = await c.post("/premortem/revise/assemble", json={"plan_text": PLAN, "revision": bundle, "decisions": decisions, "result": result_json()})
            assert r.status_code == 200
            out = r.json()
            assert out["stats"]["conflicts"] == 1 and out["conflicts"][0]["kind"] == "same_line" and out["stats"]["applied"] == 0
    run(go())


def test_main_app_registers_revise_paths_as_protected():
    from neumann.api import main as api_main

    srv = api_main.app.state.serving
    assert srv.kind_for("/premortem/revise") == "analysis" and srv.kind_for("/premortem/revise/assemble") == "analysis"
    paths = set(api_main.app.openapi()["paths"])
    assert {"/premortem/revise", "/premortem/revise/assemble"} <= paths


def test_plan_id_of_matches_pipeline_normalization():
    fx = load_fixtures()
    assert revise_api.plan_id_of(PLAN) == fx.premortem_result.plan_id
    assert revise_api.plan_id_of(PLAN + "\n연락처 010-1234-5678") != revise_api.plan_id_of(PLAN)
    assert json.dumps(revise_api.sign_payload("revision", {"a": 1.0}) or None) in ("null", json.dumps(revise_api.sign_payload("revision", {"a": 1})))


@pytest.fixture
def signing_contract(monkeypatch):
    """병합 전에는 공개 함수 계약 double, 병합 뒤에는 E4-L2f 실제 모듈을 검사한다."""
    try:
        from neumann.api import signing
        if hasattr(signing, "sign_payload"):
            return signing
    except ImportError:
        pass
    import hashlib
    import sys
    import types
    import neumann.api

    signing = types.ModuleType("neumann.api.signing")

    def payload(kind, data):
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        return "contract-test-" + hashlib.sha256((kind + json.dumps(data, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()

    signing.sign_payload = payload
    signing.verify_payload = lambda kind, data, sig: isinstance(sig, str) and sig == payload(kind, data)
    signing.sign_result = lambda data: payload("result", data)
    signing.verify_result = lambda data, sig: data is not None and isinstance(sig, str) and sig == payload("result", data)
    monkeypatch.setitem(sys.modules, "neumann.api.signing", signing)
    monkeypatch.setattr(neumann.api, "signing", signing, raising=False)
    return signing


def test_unsigned_result_never_receives_revision_server_signature(tmp_path, monkeypatch, signing_contract):
    srv, app = make(tmp_path, monkeypatch)

    async def go():
        async with client(app) as c:
            for sig in (None, "v1." + "0" * 64, "서명위조"):
                response = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN, "result_sig": sig})
                assert response.status_code == 200
                assert response.json()["revision_sig"] is None
                assert response.json()["origin"] == "client_submitted_unverified"
    run(go())


@pytest.mark.parametrize("tamper", ["none", "result", "revision", "result_sig", "revision_sig", "missing_result"])
def test_assembly_signing_requires_result_and_revision_authenticity(tmp_path, monkeypatch, signing_contract, tamper):
    import copy

    srv, app = make(tmp_path, monkeypatch)
    result = result_json()
    result_sig = signing_contract.sign_result(result)

    async def go():
        async with client(app) as c:
            response = await c.post("/premortem/revise", json={"result": result, "plan_text": PLAN, "result_sig": result_sig})
            assert response.status_code == 200, response.text
            bundle = response.json()
            assert bundle["revision_sig"] and bundle["origin"] == "server_signed"
            body = {"result": copy.deepcopy(result), "result_sig": result_sig, "plan_text": PLAN,
                    "revision": bundle, "decisions": []}
            if tamper == "result":
                body["result"]["session_id"] += "-forged"
            elif tamper == "revision":
                bundle["model"] = "gpt-forged"
                bundle["generator"] = "astra"
            elif tamper == "result_sig":
                body["result_sig"] = "비ASCII서명"
            elif tamper == "revision_sig":
                body["revision_sig"] = "비ASCII서명"
            elif tamper == "missing_result":
                body.pop("result")
            response = await c.post("/premortem/revise/assemble", json=body)
            assert response.status_code == 200, response.text
            out = response.json()
            if tamper == "none":
                assert out["origin"] == "server_signed" and out["revised_plan_sig"]
                assert revise_api.verify_payload("revised-plan", {k: v for k, v in out.items() if k != "revised_plan_sig"}, out["revised_plan_sig"])
            else:
                assert out["origin"] == "client_submitted_unverified" and out["revised_plan_sig"] is None
                assert "client_submitted_unverified" in out["label"] and "gpt-forged" not in out["label"]
    run(go())


@pytest.mark.parametrize("case", ["number", "pii", "placeholder", "unknown_evidence", "other_card_evidence", "institution", "handle", "markup", "written_number", "placeholder_number"])
def test_assembly_regates_returned_proposals_and_refunds(tmp_path, monkeypatch, case):
    srv, app = make(tmp_path, monkeypatch)

    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            baseline = srv.budget.used
            edit = bundle["revisions"][0]["edits"][0]
            if case == "number":
                edit["proposed_text"] = "정확도 99%를 이미 달성했다."
            elif case == "pii":
                edit["proposed_text"] = "연락 forged@example.org로 협의한다."
            elif case == "placeholder":
                edit["proposed_text"] = "[확인 필요: 닫히지 않은 자리표시"
            elif case == "institution":
                edit["proposed_text"] = "서울대병원과 공동 수행한다."
            elif case == "handle":
                edit["proposed_text"] = "Reviewer XYZq의 지적을 반영한다."
            elif case == "markup":
                edit["proposed_text"] = "<img src=x onerror=alert()>"
            elif case == "written_number":
                edit["proposed_text"] = "오천만 원을 이미 확보했다."
            elif case == "placeholder_number":
                edit["proposed_text"] = "[확인 필요: 표본 3000건 규모]"
            else:
                edit["rationale"]["excerpt_ids"] = ["unknown-excerpt" if case == "unknown_evidence" else result_json()["risk_cards"][1]["evidence"][0]]
            response = await c.post("/premortem/revise/assemble", json={"plan_text": PLAN, "revision": bundle, "result": result_json(),
                                                                      "decisions": [{"edit_id": edit["edit_id"], "decision": "adopt"}]})
            assert response.status_code == 422 and response.json()["error_code"] == "invalid_revision_proposal"
            assert srv.gate.active == srv.gate.waiting == 0 and srv.budget.used == baseline
    run(go())


def test_invalid_result_burst_does_not_starve_other_ip(tmp_path, monkeypatch):
    srv, app = make(tmp_path, monkeypatch, max_concurrent=4, queue_max=30, sync_queue_max=4,
                    rate_per_min=6, daily_budget=100)

    async def go():
        async with client(app, ip="10.0.0.1") as c:
            for _ in range(6):
                response = await c.post("/premortem/revise", json={"result": {}, "plan_text": PLAN})
                assert response.status_code == 422
                assert srv.gate.active == srv.gate.waiting == srv.budget.used == 0
        async with client(app, ip="10.0.0.2") as c:
            analysis = await c.post("/premortem", json={"plan_text": PLAN})
            assert analysis.status_code == 200
            revision = await c.post("/premortem/revise", json={"result": result_json(), "plan_text": PLAN})
            assert revision.status_code == 200
            assert srv.gate.active == srv.gate.waiting == 0
    run(go())


def test_modify_control_character_exports_docx_without_server_error(tmp_path, monkeypatch):
    from docx import Document

    srv, app = make(tmp_path, monkeypatch)

    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            edit = bundle["revisions"][0]["edits"][0]
            response = await c.post("/premortem/revise/assemble", json={"plan_text": PLAN, "revision": bundle,
                                                                      "decisions": [{"edit_id": edit["edit_id"], "decision": "modify", "revised_text": "직접\x00 수정 문안"}],
                                                                      "format": "docx"})
            assert response.status_code == 200
            doc = Document(io.BytesIO(response.content))
            assert "직접 수정 문안" in "\n".join(p.text for p in doc.paragraphs)
    run(go())
