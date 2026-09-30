"""WARMUP: synchronize on events, never on machine-speed assertions."""

import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from neumann.api import jobs, main, serving, warmup
from scripts.serve_fake_app import fake_result

PLAN = (main.REPO_ROOT / "tests/fixtures/plans/plan.md").read_text(encoding="utf-8")


def test_search_warms_shared_retrieval_only(monkeypatch):
    import importlib

    embed = importlib.import_module("neumann.index.embed")
    search = importlib.import_module("neumann.index.search")
    store = importlib.import_module("neumann.index.store")
    calls = []
    shared = SimpleNamespace(work_order=["work"])
    monkeypatch.setattr(store, "get_store", lambda: (calls.append("bm25") or shared))
    monkeypatch.setattr(embed, "get_embedder", lambda: calls.append("bge-m3"))

    def dummy_search(queries, k, store):
        assert queries == [warmup.DUMMY_QUERY] and k == 1 and store is shared
        calls.append("search")

    monkeypatch.setattr(search, "search", dummy_search)
    monkeypatch.setattr(search, "last_search_status", lambda: {"backend": "hybrid", "degraded": False})
    assert warmup.warm_search() == {"backend": "hybrid", "n_works": 1}
    assert calls == ["bm25", "bge-m3", "search"]
    monkeypatch.setattr(search, "last_search_status", lambda: {"backend": "lexical_only", "degraded": True})
    with pytest.raises(RuntimeError):
        warmup.warm_search()


def test_disabled_skips_work(monkeypatch):
    def forbidden():
        raise AssertionError("disabled warmup ran")

    monkeypatch.setattr(warmup, "warm_search", forbidden)
    srv = serving.Serving(serving.ServingConfig(warmup=False))

    async def go():
        srv.start_warmup()
        await srv.wait_warmup()
        assert await srv.warmup() == {"state": "done", "enabled": False, "elapsed_s": 0.0}
        assert srv._warm_task is None

    asyncio.run(go())


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("public", [False, True])
def test_startup_health_waiting_jobs_and_error_release(monkeypatch, fails, public):
    async def go():
        loop = asyncio.get_running_loop()
        entered, analyzed = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        calls = []

        def gated_warmup():
            calls.append("warmup")
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(20):
                raise RuntimeError("test release missing")
            if fails:
                raise RuntimeError("private-path-and-request-details")
            return {"backend": "hybrid", "n_works": 1}

        async def pipeline(text):
            assert release.is_set()
            calls.append("analysis")
            analyzed.set()
            return fake_result(text)

        monkeypatch.setattr(warmup, "warm_search", gated_warmup)
        srv = serving.Serving(serving.ServingConfig(warmup=True, public=public, rate_per_min=0,
                                                   cache_enabled=False))
        app = FastAPI()
        serving.install(app, srv)
        app.add_api_route("/health", main.health)
        wrapped = srv.wrap_pipeline(pipeline)
        monkeypatch.setattr(main, "_load_pipeline", lambda: (wrapped, "connected", ""))
        jobs.install(app, load_pipeline=main._load_pipeline,
                     config=jobs.JobsConfig(per_ip=0, rate_per_min=0, poll_per_min=0))
        assert srv.warmup_status()["state"] == "pending"
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        try:
            await asyncio.wait_for(entered.wait(), 20)
            srv.start_warmup()  # duplicate startup must not load twice
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
                health = (await c.get("/health")).json()["warmup"]
                assert health["state"] == "running" and health["elapsed_s"] >= 0
                response = await c.post(jobs.JOBS_PATH, json={"plan_text": PLAN, "format": "result"})
                assert response.status_code == 202
                jid = response.json()["job_id"]
                status = (await c.get(f"{jobs.JOBS_PATH}/{jid}")).json()
                assert status["status"] == "running" and status["stage"] == "warmup"
                assert status["stage_label"] == jobs.STAGE_LABELS["warmup"]
                assert status["eta_s"] is None and not analyzed.is_set()
                waiter = asyncio.create_task(srv.wait_warmup())
                await asyncio.sleep(0)
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
                assert srv.warming
                release.set()
                await srv.wait_warmup()
                await asyncio.wait_for(analyzed.wait(), 20)
                job = app.state.jobs.get(jid)
                await job.task
                assert app.state.jobs.status(job)["status"] == "done"
                final = (await c.get("/health")).json()["warmup"]
                assert final["state"] == ("error" if fails else "done")
                assert final["elapsed_s"] >= health["elapsed_s"]
                assert "private-path" not in str(final)
                assert calls == ["warmup", "analysis"]
        finally:
            release.set()
            await lifespan.__aexit__(None, None, None)

    asyncio.run(go())
