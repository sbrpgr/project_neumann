"""FIX-REVISE-504: route deadlines, request slots and signed parallel revision."""

import asyncio
import threading
import time

from neumann.analyze import revise
from neumann.analyze.mock_responders import default_responders
from neumann.api import finalize, serving, signing
from neumann.api import revise as api
from neumann.llm import MockProvider
from scripts.serve_fake_app import fake_result, integrate
from tests.e3.revise_fixtures import make_store
from tests.e3.test_revise_parallel import seven_cards
from tests.e4.test_revise_api import PLAN, client
from tests.e4.test_serving import wait_until


def test_parallel_cards_share_one_slot_and_preserve_signed_finalization(tmp_path, monkeypatch):
    monkeypatch.delenv("NEUMANN_REVISE_TIMEOUT_S", raising=False)
    monkeypatch.setattr(revise, "default_record_store", make_store)
    config = serving.ServingConfig(max_concurrent=1, queue_max=4, request_timeout_s=.5,
                                   cache_enabled=False, block_file=tmp_path / "blocked")
    srv = serving.Serving(config)
    analysis_calls = []

    def pipeline(text):
        analysis_calls.append(srv.gate.active)
        return fake_result(text)

    app = integrate(srv, pipeline, monkeypatch.setattr)
    assert api.install(app, srv=srv) and finalize.install(app)
    release = threading.Event()
    active = peak = 0
    lock = threading.Lock()
    observed_slots = []

    class BlockingMock(MockProvider):
        def complete_json(self, call):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                observed_slots.append(srv.gate.active)
            try:
                assert release.wait(5), "test must release card workers"
                return super().complete_json(call)
            finally:
                with lock:
                    active -= 1

    mock = BlockingMock(default_responders())
    monkeypatch.setattr(revise, "make_llm", lambda *a: mock)
    limits = []
    original = api._Gate.run

    async def record_limit(gate, fn, timeout_s):
        limits.append((gate.path, timeout_s))
        return await original(gate, fn, timeout_s)

    monkeypatch.setattr(api._Gate, "run", record_limit)

    def final_engine(text, **kw):
        time.sleep(.6)  # Longer than the unchanged serving request default.
        return {"version": "finalization@v1", "status": "ok", "final_text": text,
                "issues": [], "corrections": [], "tool_checks_before": [], "tool_checks_after": [], "notices": []}

    monkeypatch.setattr(finalize, "finalize_plan", final_engine)
    result = seven_cards().model_dump(mode="json")
    result_sig = signing.sign_result(result)

    async def go():
        try:
            async with client(app) as c:
                revision_task = asyncio.create_task(c.post(api.REVISE_PATH,
                    json={"result": result, "result_sig": result_sig, "plan_text": PLAN}))
                await wait_until(lambda: len(observed_slots) == 4, timeout=3)
                assert srv.gate.active == 1 and srv.gate.waiting == 0
                analysis_task = asyncio.create_task(c.post("/premortem/view", json={"plan_text": PLAN + "\n別の計画"}))
                await wait_until(lambda: srv.gate.waiting == 1, timeout=3)
                assert analysis_calls == []  # The request slot still excludes another analysis.
                release.set()
                response, analysis = await asyncio.gather(revision_task, analysis_task)
                assert response.status_code == analysis.status_code == 200
                bundle = response.json()
                assert api.revision_verified(bundle)
                assert bundle["origin"] == "server_signed"
                assert bundle["cost"]["llm_calls"] == len(bundle["revisions"]) == 7
                assert [r["card_id"] for r in bundle["revisions"]] == [c["card_id"] for c in result["risk_cards"]]
                final = await c.post(finalize.FINALIZE_PATH, json={"plan_text": PLAN, "result": result,
                    "result_sig": result_sig, "revision": bundle, "decisions": [], "submission_id": "parallel_final"})
                assert final.status_code == 200, final.text
                out = final.json()
                assert out["origin"] == "server_signed" and out["provenance"]["coupled"]
                assert signing.verify_payload("finalization",
                    {k: v for k, v in out.items() if k != "finalization_sig"}, out["finalization_sig"])
                assert srv.gate.active == srv.gate.waiting == 0
        finally:
            release.set()

    asyncio.run(go())
    assert peak == 4 and active == 0 and observed_slots == [1] * 7
    assert analysis_calls == [1]
    assert limits == [(api.REVISE_PATH, 240), (finalize.FINALIZE_PATH, 240)]
    assert config.request_timeout_s == .5
    assert api._timeout_s(api.DEFAULT_ASSEMBLE_TIMEOUT_S) == 90
    assert serving.ServingConfig().request_timeout_s == 300

