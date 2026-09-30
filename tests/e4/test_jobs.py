"""E4-L2d 비동기 작업 API 검사: POST가 곧바로 job_id, 폴링하면 순번이 줄고 결과가 온다, 관문 우회 불가
(차단 스위치·예산·속도 제한·본문 상한·대기열 상한), 오류는 사용자 문구만, TTL 폐기, job_id 추측 불가, 동기 경로 호환.

실제 파이프라인·bge-m3·OpenAI를 부르지 않는다. 가짜 파이프라인을 main.py 라우트 + 서빙 층(PM 통합 모양,
scripts/serve_fake_app.integrate) + 작업 API에 붙여 잰다. "1건 60초"는 시간 배율(SCALE)로 줄인다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from neumann.api import jobs, serving
from neumann.api import main as api_main
from scripts.serve_fake_app import fake_result, integrate

SCALE = 0.02                 # 실제 60초 분석 → 1.2초
RUN_S = 60 * SCALE
PLAN = """# 연구계획서 — 작업 API 시험
## 방법
We randomly split the dataset into 80/10/10 train/validation/test sets.
"""
BODY_MARK = "JOBBODY_MARKER_51c2"
FAKE_KEY = "s" + "k-proj-" + "Jb" * 14   # 보안 검사에 걸리지 않게 실행 중에 만든다
SECRET_PATH = "C:\\Users\\someone\\secret\\pipeline_internal.py"


def plan(i: int | str, extra: str = "") -> str:
    return f"{PLAN}\n실험 {i}: {BODY_MARK} {extra}\n"


def make(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fn: Any, *, jobs_cfg: jobs.JobsConfig | None = None,
         load_pipeline: Any = None, **cfg: Any) -> tuple[serving.Serving, Any, jobs.JobStore]:
    base: dict[str, Any] = dict(max_concurrent=2, queue_max=10, rate_per_min=0, cache_enabled=False,
                                cache_dir=tmp_path / "results", request_timeout_s=30.0, avg_run_s=RUN_S,
                                block_file=tmp_path / "serving_block.flag")
    base.update(cfg)
    srv = serving.Serving(serving.ServingConfig(**base))
    app = integrate(srv, fn, monkeypatch.setattr)
    store = jobs.install(app, load_pipeline=load_pipeline or (lambda: api_main._load_pipeline()),
                         sample_result=api_main._sample_result, config=jobs_cfg or cfg_nolimit())
    assert store is not None
    return srv, app, store


def cfg_nolimit(**kw: Any) -> jobs.JobsConfig:
    """IP별 상한·속도 제한을 끈 작업 설정(이 파일은 흐름·관문을 잰다. IP별 상한은 test_jobs_limits.py)."""
    base: dict[str, Any] = dict(ttl_s=60, poll_s=1, per_ip=0, rate_per_min=0, poll_per_min=0)
    base.update(kw)
    return jobs.JobsConfig(**base)


def client(app: Any, ip: str = "127.0.0.1") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(ip, 5000)), base_url="http://t",
                             timeout=30)


class Gated:
    """호출마다 풀어 줄 때까지 멈추는 가짜 파이프라인(스레드). 부른 순서대로 release(i)로 푼다."""

    def __init__(self, stage: str | None = None) -> None:
        self.lock = threading.Lock()
        self.events: list[threading.Event] = []
        self.calls = 0
        self.stage = stage
        self.opened = False

    def __call__(self, plan_text: str) -> dict[str, Any]:
        ev = threading.Event()
        with self.lock:
            self.calls += 1
            self.events.append(ev)
        if self.stage:
            jobs.report_stage(self.stage)
        if not self.opened:
            ev.wait(10)
        return fake_result(plan_text)

    def release(self, i: int) -> None:
        self.events[i].set()

    def release_all(self) -> None:
        """지금 멈춘 것과 앞으로 부를 것 모두 풀어 둔다."""
        self.opened = True
        for e in list(self.events):
            e.set()


def slow(run_s: float = RUN_S) -> Any:
    calls = {"n": 0}

    def run_premortem(plan_text: str) -> dict[str, Any]:
        calls["n"] += 1
        for name in ("plan_normalize", "query_axes", "search", "extract_issues", "synthesize_cards", "verify_evidence"):
            jobs.report_stage(name)
            time.sleep(run_s / 6)
        return fake_result(plan_text)

    run_premortem.calls = calls  # type: ignore[attr-defined]
    return run_premortem


async def wait_until(pred: Any, timeout: float = 20.0) -> None:
    t0 = time.monotonic()
    while not pred():
        if time.monotonic() - t0 > timeout:
            raise AssertionError("조건이 시간 안에 참이 되지 않았다")
        await asyncio.sleep(0.02)


async def submit(c: httpx.AsyncClient, text: str, **extra: Any) -> httpx.Response:
    # 교착 감시 한도. 즉시 반환의 기능 기준은 아래 Gated 시험이 검사한다.
    return await asyncio.wait_for(c.post("/premortem/jobs", json={"plan_text": text, **extra}), timeout=20)


async def poll_done(c: httpx.AsyncClient, job_id: str, timeout: float = 10.0) -> dict[str, Any]:
    t0 = time.monotonic()
    while True:
        r = await c.get(f"/premortem/jobs/{job_id}")
        assert r.status_code == 200, r.text
        j = r.json()
        if j["status"] in ("done", "error"):
            return j
        if time.monotonic() - t0 > timeout:
            raise AssertionError(f"작업이 끝나지 않았다: {j}")
        await asyncio.sleep(0.05)


def assert_clean(text: str) -> None:
    for bad in ("Traceback", 'File "', ".py:", ".py\"", BODY_MARK, FAKE_KEY, "secret-internal-detail", "someone",
                "pipeline_internal"):
        assert bad not in text, bad


# ───────────────────────── 기본 흐름 ─────────────────────────


def test_post_returns_immediately_then_result_arrives(tmp_path, monkeypatch):
    fn = Gated(stage="search")
    srv, app, store = make(tmp_path, monkeypatch, fn)

    async def go() -> None:
        async with client(app) as c:
            r = await submit(c, plan(1), filename="plan1.md")
            assert r.status_code == 202
            b = r.json()
            assert set(b) >= {"job_id", "status", "position", "eta_s", "poll_after_s", "message", "ticket"}
            assert b["status"] == "queued" and b["position"] == 0 and 1 <= b["poll_after_s"] <= 2
            assert r.headers["cache-control"] == "no-store"
            try:
                await wait_until(lambda: fn.calls == 1)
                j = (await c.get(f"/premortem/jobs/{b['job_id']}")).json()
                assert {"status", "position", "stage", "elapsed_s", "message"} <= set(j)
                assert (j["status"], j["stage"]) == ("running", "search")
                assert not fn.events[0].is_set(), "해제하기 전에 분석이 완료됐다"
            finally:
                fn.release_all()
            j = await poll_done(c, b["job_id"])
            view = j["result"]
            assert view["cards"] and view["plan"]["lines"]            # 화면 모양(ui_view) 그대로
            assert BODY_MARK in json.dumps(view["plan"], ensure_ascii=False)  # 결과에는 계획서 줄이 있다(메모리만)
            assert view["_status"]["serving"]["mode"] == "job"
            assert view["_status"]["source"] == "pipeline"
            assert j["message"] == jobs.MESSAGES["done"] and j["expires_in_s"] > 0
            assert fn.calls == 1
            assert srv.gate.active == 0 and srv.gate.waiting == 0

    asyncio.run(go())


def test_result_format_option_and_sync_endpoints_still_work(tmp_path, monkeypatch):
    srv, app, store = make(tmp_path, monkeypatch, slow(0.06))

    async def go() -> None:
        async with client(app) as c:
            r = await submit(c, plan("raw"), format="result")
            j = await poll_done(c, r.json()["job_id"])
            assert j["status"] == "done"
            res = j["result"]
            assert res["plan_id"] == serving.plan_key(plan("raw")) and "cards" not in res   # PremortemResult 모양
            v = await c.post("/premortem/view", json={"plan_text": plan("sync")})        # 동기 경로 그대로
            assert v.status_code == 200 and v.json()["cards"]
            p = await c.post("/premortem", json={"plan_text": plan("sync2")})
            assert p.status_code == 200 and p.json()["plan_id"] == serving.plan_key(plan("sync2"))
            bad = await c.post("/premortem/jobs", json={"plan_text": "   "})
            assert bad.status_code == 422 and len(store) == 1

    asyncio.run(go())


def test_queue_position_decreases_while_polling(tmp_path, monkeypatch):
    fake = Gated()
    srv, app, store = make(tmp_path, monkeypatch, fake, max_concurrent=1, queue_max=10)

    async def go() -> None:
        async with client(app) as c:
            ids = []
            for i in range(4):
                r = await submit(c, plan(i))
                assert r.status_code == 202
                ids.append(r.json()["job_id"])
            assert [(await c.get(f"/premortem/jobs/{x}")).json()["position"] for x in ids[1:]] == [1, 2, 3]
            last = ids[3]
            history = []
            for k in range(4):
                await wait_until(lambda k=k: fake.calls == k + 1)
                j = (await c.get(f"/premortem/jobs/{last}")).json()
                history.append((j["status"], j["position"]))
                if j["status"] == "queued":
                    assert j["message"].startswith(f"대기 {j['position']}번째 · 약 ")
                    assert j["eta_s"] > 0
                fake.release(k)
            assert history == [("queued", 3), ("queued", 2), ("queued", 1), ("running", 0)]
            done = [await poll_done(c, x) for x in ids]
            assert [d["status"] for d in done] == ["done"] * 4
            assert fake.calls == 4

    asyncio.run(go())


def test_stage_from_on_stage_kwarg_and_same_plan_runs_once(tmp_path, monkeypatch):
    release = threading.Event()
    calls = {"n": 0}

    def run_premortem(plan_text: str, on_stage: Any = None) -> dict[str, Any]:
        calls["n"] += 1
        on_stage("extract_issues")
        release.wait(10)
        return fake_result(plan_text)

    srv, app, store = make(tmp_path, monkeypatch, run_premortem)

    async def go() -> None:
        async with client(app) as c:
            a = (await submit(c, plan("same"))).json()["job_id"]
            b = (await submit(c, plan("same"))).json()["job_id"]
            await wait_until(lambda: calls["n"] == 1)
            await asyncio.sleep(0.05)
            ja = (await c.get(f"/premortem/jobs/{a}")).json()
            jb = (await c.get(f"/premortem/jobs/{b}")).json()
            for j in (ja, jb):
                assert j["status"] == "running" and j["stage"] == "extract_issues" and j["stage_label"] == "지적 추출"
                assert "지적 추출" in j["message"]
            release.set()
            ra, rb = await poll_done(c, a), await poll_done(c, b)
            assert ra["status"] == rb["status"] == "done" and calls["n"] == 1   # 같은 계획서는 한 번만 돈다
            assert a != b

    asyncio.run(go())


# ───────────────────────── 관문 우회 불가 ─────────────────────────


def test_gates_apply_to_jobs_block_budget_rate_body(tmp_path, monkeypatch):
    srv, app, store = make(tmp_path, monkeypatch, slow(0.02), daily_budget=2, rate_per_min=3, max_plan_chars=2000,
                           budget_file=tmp_path / "budget.json")

    async def go() -> None:
        async with client(app, "203.0.113.7") as c:
            # 차단 스위치(파일) → 503, 작업이 만들어지지 않는다
            srv.config.block_file.write_text("1", encoding="utf-8")
            r = await c.post("/premortem/jobs", json={"plan_text": plan("blk")})
            assert r.status_code == 503 and r.json()["error_code"] == "blocked" and "job_id" not in r.json()
            srv.config.block_file.unlink()
            # 본문 바이트 상한(Content-Length) → 413, 글자 상한 → 413
            big = json.dumps({"plan_text": "x" * (srv.config.analysis_body_bytes + 10)})
            r = await c.post("/premortem/jobs", content=big, headers={"content-type": "application/json"})
            assert r.status_code == 413 and r.json()["error_code"] == "too_large"
            r = await c.post("/premortem/jobs", json={"plan_text": plan("long", "가" * 3000)})
            assert r.status_code == 413 and r.json()["error_code"] == "too_large" and BODY_MARK not in r.text
            assert len(store) == 0 and srv.budget.used == 0
            # 예산 2건: 두 건은 받고 세 번째는 503(오늘 한도)
            ids = [(await submit(c, plan(f"b{i}"))).json()["job_id"] for i in range(2)]
            r = await c.post("/premortem/jobs", json={"plan_text": plan("b2")})
            assert r.status_code == 503 and r.json()["error_code"] == "budget_exhausted"
            assert r.json()["message"].startswith("오늘 준비한 분석 한도(2건)")
            for x in ids:
                assert (await poll_done(c, x))["status"] == "done"
            assert srv.budget.used == 2
        async with client(app, "198.51.100.9") as c2:
            # 속도 제한(분당 3건, 다른 IP): 예산은 넉넉히 늘리고 잰다
            srv.budget.limit = 100
            codes = [(await c2.post("/premortem/jobs", json={"plan_text": plan(f"r{i}")})).status_code
                     for i in range(4)]
            assert codes == [202, 202, 202, 429]
            r = await c2.post("/premortem/jobs", json={"plan_text": plan("r9")})
            assert r.json()["error_code"] == "rate_limited" and "분당 3건" in r.json()["message"]
            assert "retry-after" in r.headers

    asyncio.run(go())


def test_queue_full_and_block_env_refuse_jobs(tmp_path, monkeypatch):
    fake = Gated()
    srv, app, store = make(tmp_path, monkeypatch, fake, max_concurrent=1, queue_max=1)

    async def go() -> None:
        async with client(app) as c:
            a = (await submit(c, plan("q1"))).json()["job_id"]
            b = (await submit(c, plan("q2"))).json()["job_id"]
            r = await c.post("/premortem/jobs", json={"plan_text": plan("q3")})
            assert r.status_code == 503 and r.json()["error_code"] == "busy"
            assert r.json()["message"].startswith("지금 분석 요청이 많아 대기열이 가득 찼습니다")
            assert len(store) == 2 and srv.gate.active + srv.gate.waiting == 2
            fake.release_all()
            for x in (a, b):
                await poll_done(c, x)
            assert fake.calls == 2

    asyncio.run(go())
    srv2, app2, store2 = make(tmp_path, monkeypatch, fake, block_new=True)

    async def go2() -> None:
        async with client(app2) as c:
            r = await c.post("/premortem/jobs", json={"plan_text": plan("env")})
            assert r.status_code == 503 and r.json()["error_code"] == "blocked" and len(store2) == 0

    asyncio.run(go2())


def test_jobs_path_is_gated_even_if_config_omits_it(tmp_path, monkeypatch):
    fn = slow(0.02)
    srv, app, store = make(tmp_path, monkeypatch, fn, protected={"/premortem": "analysis"}, block_new=True)
    assert srv.kind_for("/premortem/jobs") == "analysis"

    async def go() -> None:
        async with client(app) as c:
            r = await c.post("/premortem/jobs", json={"plan_text": plan("cfg")})
            assert r.status_code == 503 and r.json()["error_code"] == "blocked"
            assert fn.calls["n"] == 0 and len(store) == 0

    asyncio.run(go())


def test_jobs_without_serving_middleware_is_refused(tmp_path, monkeypatch):
    """서빙 미들웨어 없이 라우터만 붙은 앱: 관문을 거치지 않은 요청은 받지 않는다(503), 파이프라인 안 부름."""
    from fastapi import FastAPI

    fn = slow(0.02)
    srv = serving.Serving(serving.ServingConfig(cache_enabled=False))
    bare = FastAPI()
    assert jobs.install(bare, load_pipeline=lambda: (fn, "connected", "")) is None   # 서빙 층 없으면 안 붙는다
    store = jobs.install(bare, load_pipeline=lambda: (fn, "connected", ""), srv=srv)   # 억지로 붙여도
    assert store is not None

    async def go() -> None:
        async with client(bare) as c:
            r = await c.post("/premortem/jobs", json={"plan_text": plan("bare")})
            assert r.status_code == 503 and r.json()["error_code"] == "unavailable"
            assert fn.calls["n"] == 0 and len(store) == 0

    asyncio.run(go())


def test_readmission_when_join_or_cache_vanished(tmp_path, monkeypatch):
    """입장 때 자리 없이(캐시·합류) 들어온 작업이 시작할 때 캐시·진행 중 분석이 없으면 관문을 다시 거친다."""
    fn = slow(0.02)
    srv, app, store = make(tmp_path, monkeypatch, fn, block_new=True)
    ctx = serving.RequestCtx(ticket="tk_readmit", plan_id=serving.plan_key(plan("ra")), chars=10)
    job = jobs.Job(id="x" * 32, ctx=ctx, fmt="view", filename=None, lines=3)
    asyncio.run(store._run(job, plan("ra")))
    assert job.state == "error" and job.error_code == "blocked" and fn.calls["n"] == 0
    srv2, app2, store2 = make(tmp_path, monkeypatch, fn, max_concurrent=1, queue_max=0)
    srv2.gate.reserve("someone_else", "p" * 64)   # 슬롯 1개를 다른 분석이 쓰는 중, 대기 자리 0
    ctx2 = serving.RequestCtx(ticket="tk_readmit2", plan_id=serving.plan_key(plan("rb")), chars=10)
    job2 = jobs.Job(id="y" * 32, ctx=ctx2, fmt="view", filename=None, lines=3)
    asyncio.run(store2._run(job2, plan("rb")))
    assert job2.state == "error" and job2.error_code == "busy" and fn.calls["n"] == 0


def test_store_full_503_returns_slot_and_budget(tmp_path, monkeypatch):
    fake = Gated()
    srv, app, store = make(tmp_path, monkeypatch, fake, daily_budget=10, budget_file=tmp_path / "b.json",
                           jobs_cfg=cfg_nolimit(max_jobs=2))

    async def go() -> None:
        async with client(app) as c:
            ids = [(await submit(c, plan(f"f{i}"))).json()["job_id"] for i in range(2)]
            before = (srv.gate.active, srv.gate.waiting, srv.budget.used)
            r = await c.post("/premortem/jobs", json={"plan_text": plan("f2")})
            assert r.status_code == 503 and r.json()["error_code"] == "busy"
            assert "보관 중인 분석 작업이 많습니다" in r.json()["message"]
            assert (srv.gate.active, srv.gate.waiting, srv.budget.used) == before   # 자리·예산을 돌려받았다
            fake.release_all()
            for x in ids:
                await poll_done(c, x)
            r = await submit(c, plan("f3"))            # 끝난 작업은 밀려나고 새 작업을 받는다
            assert r.status_code == 202 and len(store) == 2

    asyncio.run(go())


# ───────────────────────── 오류 문구·시간 상한 ─────────────────────────


def test_error_is_user_message_only(tmp_path, monkeypatch, caplog):
    def boom(plan_text: str) -> dict[str, Any]:
        raise RuntimeError(f"secret-internal-detail {SECRET_PATH} {FAKE_KEY} {plan_text}")

    srv, app, store = make(tmp_path, monkeypatch, boom)
    caplog.set_level(logging.INFO)

    async def go() -> None:
        async with client(app) as c:
            r = await submit(c, plan("err"))
            j = await poll_done(c, r.json()["job_id"])
            assert j["status"] == "error" and j["error_code"] == "internal" and "result" not in j
            assert j["message"].startswith("처리 중 문제가 생겼습니다") and j["ticket"] in j["message"]
            assert_clean(json.dumps(j, ensure_ascii=False))
            assert srv.gate.active == 0 and srv.gate.waiting == 0

    asyncio.run(go())
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "kind=RuntimeError" in logs
    for bad in (BODY_MARK, FAKE_KEY, "secret-internal-detail", "Traceback"):
        assert bad not in logs, bad


def test_timeout_is_user_message_then_cache_serves(tmp_path, monkeypatch):
    fn = slow(0.6)
    srv, app, store = make(tmp_path, monkeypatch, fn, cache_enabled=True,
                           jobs_cfg=cfg_nolimit(timeout_s=0.2))

    async def go() -> None:
        async with client(app) as c:
            r = await submit(c, plan("slow"))
            j = await poll_done(c, r.json()["job_id"])
            assert j["status"] == "error" and j["error_code"] == "timeout"
            assert j["message"].startswith("분석이 0초 안에 끝나지 않았습니다") or "끝나지 않았습니다" in j["message"]
            await wait_until(lambda: srv.cache.has(serving.plan_key(plan("slow"))), 5)
            r2 = await submit(c, plan("slow"))
            j2 = await poll_done(c, r2.json()["job_id"])
            assert j2["status"] == "done" and j2["result"]["_status"]["serving"]["cache"] == "hit"
            assert fn.calls["n"] == 1

    asyncio.run(go())


def test_pipeline_unavailable_gives_marked_sample(tmp_path, monkeypatch):
    srv, app, store = make(tmp_path, monkeypatch, slow(0.02),
                           load_pipeline=lambda: (None, "unavailable", "neumann.pipeline 모듈 없음"))

    async def go() -> None:
        async with client(app) as c:
            j = await poll_done(c, (await submit(c, plan("smp"))).json()["job_id"])
            assert j["status"] == "done" and j["result"]["_status"]["source"] == "sample"
            assert srv.gate.active == 0 and srv.gate.waiting == 0

    asyncio.run(go())


# ───────────────────────── 보관(TTL)·job_id ─────────────────────────


def test_results_are_discarded_after_ttl(tmp_path, monkeypatch):
    srv, app, store = make(tmp_path, monkeypatch, slow(0.02), jobs_cfg=cfg_nolimit(ttl_s=30))
    now = {"t": 1000.0}
    store.clock = lambda: now["t"]

    async def go() -> None:
        async with client(app) as c:
            jid = (await submit(c, plan("ttl"))).json()["job_id"]
            j = await poll_done(c, jid)
            assert j["status"] == "done" and j["expires_in_s"] == 30
            now["t"] += 29
            assert (await c.get(f"/premortem/jobs/{jid}")).status_code == 200
            now["t"] += 2
            g = await c.get(f"/premortem/jobs/{jid}")
            assert g.status_code == 404 and g.json()["error_code"] == "job_not_found"
            assert "보관 시간" in g.json()["message"] and BODY_MARK not in g.text
            assert len(store) == 0 and store.counters["expired"] == 1   # 결과(계획서 줄 포함)가 메모리에서 사라졌다

    asyncio.run(go())


def test_job_ids_are_unguessable_and_not_derived(tmp_path, monkeypatch):
    srv, app, store = make(tmp_path, monkeypatch, slow(0.01))

    async def go() -> None:
        async with client(app) as c:
            ids = []
            for i in range(30):
                r = await c.post("/premortem/jobs", json={"plan_text": plan(i % 3)},
                                 headers={"X-Neumann-Ticket": f"tk_same_{i:02d}"})
                assert r.status_code == 202
                ids.append(r.json()["job_id"])
            assert len(set(ids)) == 30
            assert all(re.fullmatch(r"[A-Za-z0-9_\-]{32}", x) for x in ids)
            pid = serving.plan_key(plan(0))
            assert not any(x in pid or pid[:12] in x or "tk_same" in x for x in ids)   # 계획서·요청 번호와 무관
            # 다른 사람 job_id를 짐작해 보기: 한 글자 바꾼 것, 임의의 것, 모양이 틀린 것 → 모두 같은 404
            victim = ids[0]
            flip = victim[:-1] + ("A" if victim[-1] != "A" else "B")
            for guess in (flip, "a" * 32, victim[:16], victim + "x", "tk_same_00", "%2e%2e"):
                g = await c.get(f"/premortem/jobs/{guess}")
                assert g.status_code == 404 and g.json()["error_code"] == "job_not_found"
                assert "result" not in g.json()
            await poll_done(c, victim)

    asyncio.run(go())
