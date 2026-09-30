"""Real HTTP gates/assembly, mock finalizer, no live API calls."""
import asyncio
import time

from fastapi import FastAPI
from neumann.api import finalize, serving, signing
from tests.e4.test_revise_api import PLAN, _bundle, _decisions, client, make, result_json, run
from neumann.analyze import revise as revise_mod
from tests.e3.revise_fixtures import make_store


def setup(tmp_path, monkeypatch, **cfg):
    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "mock")
    monkeypatch.setattr(revise_mod, "default_record_store", lambda: make_store())
    srv, app = make(tmp_path, monkeypatch, **cfg)
    assert finalize.install(app)
    return srv, app


def engine(calls, delay=0):
    def execute(text, **kw):
        calls.append(text)
        if delay:
            time.sleep(delay)
        return {"version": "finalization@v1", "status": "ok", "final_text": text,
                "issues": [], "corrections": [], "tool_checks_before": [], "tool_checks_after": [], "notices": []}
    return execute


def test_http_idempotency_concurrency_provenance_and_conflict(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(finalize, "finalize_plan", engine(calls, .1))
    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            body = {"plan_text": PLAN, "revision": bundle, "result": result_json(),
                    "decisions": _decisions(bundle), "submission_id": "submission_test_1", "polish": True}
            responses = await asyncio.gather(c.post(finalize.FINALIZE_PATH, json=body), c.post(finalize.FINALIZE_PATH, json=body))
            assert [r.status_code for r in responses] == [200, 200]
            out = responses[0].json()
            assert responses[1].json() == out and len(calls) == 1
            assert out["origin"] == "client_submitted_unverified" and out["finalization_sig"] is None
            assert out["assembled"]["polish"]["applied"] is False
            assert out["final_text"] == calls[0] and out["final_text"] != PLAN
            again = await c.post(finalize.FINALIZE_PATH, json=body)
            assert again.json() == out and len(calls) == 1
            conflict = await c.post(finalize.FINALIZE_PATH, json={**body, "title": "different"})
            assert conflict.status_code == 409
            invalid = await c.post(finalize.FINALIZE_PATH, json={**body, "checks": [{}] * 17})
            assert invalid.status_code == 422
    run(go())
    assert srv.gate.active == srv.gate.waiting == 0


def test_http_signed_output_and_confirmed_binding(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(finalize, "finalize_plan", engine(calls))
    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            result = result_json()
            bundle["revision_sig"] = signing.sign_payload("revision", {k:v for k,v in bundle.items() if k != "revision_sig"})
            body = {"plan_text": PLAN, "revision": bundle, "result": result,
                    "result_sig": signing.sign_result(result), "decisions": _decisions(bundle), "submission_id": "signed_request_1"}
            response = await c.post(finalize.FINALIZE_PATH, json=body)
            assert response.status_code == 200, response.text
            out = response.json()
            assert out["origin"] == "server_signed"
            assert signing.verify_payload("finalization", {k:v for k,v in out.items() if k != "finalization_sig"}, out["finalization_sig"])
            confirmed = {**body, "submission_id": "confirmed_request", "confirmed_text": "연구자가 직접 수정한 계획서 문안.", "confirmed_base_id": out["assembled"]["revised_plan_id"]}
            good = await c.post(finalize.FINALIZE_PATH, json=confirmed)
            assert good.status_code == 200 and calls[-1] == confirmed["confirmed_text"]
            assert "새 내용의 출처" in good.json()["finalization"]["notices"][-1]
            for change in [{"confirmed_base_id": "wrong"}, {"confirmed_text": "<script>alert(1)</script>"}, {"confirmed_text": "contact a@example.com"}]:
                bad = await c.post(finalize.FINALIZE_PATH, json={**confirmed, **change})
                assert bad.status_code == 422
    run(go())
    assert srv.gate.active == 0


def test_http_protected_even_custom_config_and_preflight_refunds(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch, protected={})
    calls = []
    monkeypatch.setattr(finalize, "finalize_plan", engine(calls))
    assert srv.kind_for(finalize.FINALIZE_PATH) == "analysis"
    async def go():
        async with client(app) as c:
            invalid = await c.post(finalize.FINALIZE_PATH, json={"plan_text": PLAN})
            assert invalid.status_code == 422
            assert srv.budget.used == srv.gate.active == srv.gate.waiting == 0
            srv.config.block_file.write_text("1")
            blocked = await c.post(finalize.FINALIZE_PATH, json={"plan_text": PLAN})
            assert blocked.status_code == 503 and blocked.json()["error_code"] == "blocked"
    run(go())
    app2 = FastAPI()
    app2.include_router(finalize.router)
    async def ungated():
        async with client(app2) as c:
            assert (await c.post(finalize.FINALIZE_PATH, json={"plan_text": PLAN})).status_code == 503
    run(ungated())
    assert not calls


def test_http_timeout_is_explicit_and_replay_does_not_repeat(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(finalize, "finalize_plan", engine(calls, .2))
    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            # The 50 ms limit applies to the finalization request only; building the bundle above must not race it.
            monkeypatch.setenv("NEUMANN_REVISE_TIMEOUT_S", "0.05")
            body = {"plan_text": PLAN, "revision": bundle, "submission_id": "timeout_request"}
            response = await c.post(finalize.FINALIZE_PATH, json=body)
            assert response.status_code == 504 and response.json()["error_code"] == "timeout"
            again = await c.post(finalize.FINALIZE_PATH, json=body)
            assert again.status_code == 504 and len(calls) == 1
    run(go())


def test_cache_bound_pending_and_payload_conflict():
    cache = finalize._Cache()
    for i in range(64):
        assert cache.claim(str(i), "digest")[1] == "leader"
    assert cache.claim("overflow", "digest")[1] == "full"
    entry, kind = cache.claim("0", "digest")
    assert kind == "duplicate"
    assert cache.claim("0", "changed")[1] == "conflict"
    cache.finish(entry, {"ok": True}, 200)
    assert cache.claim("replacement", "digest")[1] == "leader"
    assert len(cache.entries) == 64


def test_http_engine_failure_cached_without_success_replacement(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch)
    calls = []
    def failure(*args, **kw):
        calls.append(1)
        raise RuntimeError("private diagnostics")
    monkeypatch.setattr(finalize, "finalize_plan", failure)
    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            body = {"plan_text": PLAN, "revision": bundle, "submission_id": "failure_request"}
            first = await c.post(finalize.FINALIZE_PATH, json=body)
            assert first.status_code == 500 and "private diagnostics" not in first.text
            second = await c.post(finalize.FINALIZE_PATH, json=body)
            assert second.status_code == 500 and second.json()["error_code"] == first.json()["error_code"] and len(calls) == 1
    run(go())
    assert srv.gate.active == srv.gate.waiting == 0


def test_http_rate_limit_and_byte_limit(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch, rate_per_min=1, max_plan_chars=len(PLAN) + 5)
    calls = []
    monkeypatch.setattr(finalize, "finalize_plan", engine(calls))
    async def go():
        async with client(app) as c:
            # Even invalid requests pass admission and cannot bypass IP rate limits.
            assert (await c.post(finalize.FINALIZE_PATH, json={"plan_text": PLAN})).status_code == 422
            limited = await c.post(finalize.FINALIZE_PATH, json={"plan_text": PLAN})
            assert limited.status_code == 429
        async with client(app, ip="10.0.0.9") as c:
            large = await c.post(finalize.FINALIZE_PATH, json={"plan_text": PLAN + "x" * 100})
            assert large.status_code == 413
    run(go())
    assert calls == [] and srv.gate.active == srv.gate.waiting == srv.budget.used == 0
