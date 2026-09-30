"""E4-L2c 서빙 층 검사: 동시 상한·대기 순번, 대기열 초과 503, IP 속도 제한, 입력 상한, 결과 캐시(메모리·디스크),
같은 계획서 합류, 시간 상한, 오류 문구에 내부 정보 없음, 로그에 본문·키 없음.

실제 파이프라인·bge-m3·OpenAI를 부르지 않는다. 가짜 파이프라인(이벤트로 멈추는 것, 짧게 자는 것)을
main.py 라우트에 PM 통합 모양으로 붙여(scripts/serve_fake_app.integrate) 잰다.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from neumann.api import serving
from scripts.serve_fake_app import fake_result, integrate

PLAN = """# 연구계획서 — 서빙 시험
## 방법
We randomly split the dataset into 80/10/10 train/validation/test sets.
"""
# 로그·응답에 나오면 안 되는 본문 표지. 키 모양 문자열은 이 파일이 보안 검사에 걸리지 않게 실행 중에 만든다.
BODY_MARK = "PLANBODY_MARKER_7f3a"
FAKE_KEY = "s" + "k-proj-" + "Zq" * 14


def plan(i: int | str, extra: str = "") -> str:
    return f"{PLAN}\n실험 {i}: {BODY_MARK} {extra}\n"


def make(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fn: Any, **cfg: Any) -> tuple[serving.Serving, Any]:
    base: dict[str, Any] = dict(max_concurrent=2, queue_max=10, rate_per_min=0, cache_enabled=False,
                                cache_dir=tmp_path / "results", request_timeout_s=30.0, avg_run_s=1.0)
    base.update(cfg)
    srv = serving.Serving(serving.ServingConfig(**base))
    app = integrate(srv, fn, monkeypatch.setattr)
    return srv, app


def client(app: Any, ip: str = "127.0.0.1") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(ip, 5000)), base_url="http://t",
                             timeout=30)


class Blocking:
    """event가 풀릴 때까지 멈추는 가짜 파이프라인(스레드에서 돈다). 동시 실행 수 최댓값을 잰다."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.now = self.peak = self.calls = 0

    def __call__(self, plan_text: str) -> dict[str, Any]:
        with self.lock:
            self.calls += 1
            self.now += 1
            self.peak = max(self.peak, self.now)
        try:
            self.release.wait(10)
            return fake_result(plan_text)
        finally:
            with self.lock:
                self.now -= 1


async def wait_until(pred: Any, timeout: float = 20.0) -> None:
    """기능 단언은 pred로 검사한다. timeout은 스케줄링 여유를 둔 교착 감시 한도다."""
    t0 = time.monotonic()
    while not pred():
        if time.monotonic() - t0 > timeout:
            raise AssertionError("조건이 시간 안에 참이 되지 않았다")
        await asyncio.sleep(0.02)


def assert_clean(text: str, *, response: bool = True) -> None:
    """응답·로그에 내부 정보가 없어야 한다. 응답은 파일 위치(.py:줄)도 없어야 한다."""
    bad = ["Traceback", 'File "', BODY_MARK, FAKE_KEY, "secret-internal-detail"]
    if response:
        bad += [".py:", ".py\""]
    for b in bad:
        assert b not in text, b


# ───────────────────────── 동시 상한·대기열 ─────────────────────────


def test_concurrency_cap_and_queue_positions(tmp_path, monkeypatch):
    fake = Blocking()
    srv, app = make(tmp_path, monkeypatch, fake, max_concurrent=2, queue_max=10)

    async def go() -> None:
        async with client(app) as c:
            tickets = [f"tk_conc_{i:02d}" for i in range(6)]
            tasks = []
            for i, t in enumerate(tickets):
                tasks.append(asyncio.create_task(
                    c.post("/premortem/view", json={"plan_text": plan(i)}, headers={"X-Neumann-Ticket": t})))
                await wait_until(lambda n=i + 1: srv.gate.active + srv.gate.waiting == n)
            st = (await c.get("/queue/status")).json()
            assert (st["active"], st["waiting"]) == (2, 4)
            per = {t: (await c.get("/queue/status", params={"ticket": t})).json()["ticket"] for t in tickets}
            assert [per[t]["state"] for t in tickets[:2]] == ["running", "running"]
            assert [per[t]["position"] for t in tickets[2:]] == [1, 2, 3, 4]  # 도착 순서대로
            assert all(per[t]["eta_s"] > 0 for t in tickets[2:])
            assert per[tickets[5]]["eta_s"] >= per[tickets[2]]["eta_s"]
            assert fake.peak == 2
            fake.release.set()
            rs = await asyncio.gather(*tasks)
            assert [r.status_code for r in rs] == [200] * 6
            assert fake.peak == 2 and fake.calls == 6
            pos = [r.json()["_status"]["serving"]["position_at_arrival"] for r in rs]
            assert pos == [0, 0, 1, 2, 3, 4]
            assert [r.headers["x-neumann-ticket"] for r in rs] == tickets
            done = (await c.get("/queue/status", params={"ticket": tickets[3]})).json()
            assert done["ticket"]["state"] == "done" and done["active"] == 0 and done["waiting"] == 0

    asyncio.run(go())


def test_queue_full_returns_503_with_user_message(tmp_path, monkeypatch):
    fake = Blocking()
    srv, app = make(tmp_path, monkeypatch, fake, max_concurrent=1, queue_max=1)

    async def go() -> None:
        async with client(app) as c:
            t1 = asyncio.create_task(c.post("/premortem", json={"plan_text": plan(1)}))
            await wait_until(lambda: srv.gate.active == 1)
            t2 = asyncio.create_task(c.post("/premortem", json={"plan_text": plan(2)}))
            await wait_until(lambda: srv.gate.waiting == 1)
            r3 = await c.post("/premortem/view", json={"plan_text": plan(3)})
            assert r3.status_code == 503
            body = r3.json()
            assert body["error_code"] == "busy"
            assert body["message"].startswith("지금 분석 요청이 많아 대기열이 가득 찼습니다")
            assert int(r3.headers["retry-after"]) >= 5
            assert body["queue"]["active"] == 1 and body["queue"]["waiting"] == 1
            assert_clean(r3.text)
            fake.release.set()
            r1, r2 = await asyncio.gather(t1, t2)
            assert (r1.status_code, r2.status_code) == (200, 200)
            assert srv.counters["busy_503"] == 1
            # 자리가 비면 다시 받는다
            assert (await c.post("/premortem", json={"plan_text": plan(4)})).status_code == 200

    asyncio.run(go())


def test_same_plan_in_flight_runs_once(tmp_path, monkeypatch):
    fake = Blocking()
    srv, app = make(tmp_path, monkeypatch, fake, max_concurrent=1, queue_max=0)

    async def go() -> None:
        async with client(app) as c:
            tasks = [asyncio.create_task(c.post("/premortem", json={"plan_text": plan("same")}))]
            await wait_until(lambda: fake.calls == 1)
            tasks += [asyncio.create_task(c.post("/premortem", json={"plan_text": plan("same")})) for _ in range(2)]
            await wait_until(lambda: srv.counters["joined"] == 2)
            fake.release.set()
            rs = await asyncio.gather(*tasks)
            # 대기열이 0이어도 같은 계획서는 진행 중인 분석에 합류하므로 503이 아니다
            assert [r.status_code for r in rs] == [200, 200, 200]
            assert fake.calls == 1 and srv.counters["joined"] == 2
            assert len({r.json()["plan_id"] for r in rs}) == 1

    asyncio.run(go())


# ───────────────────────── 속도 제한 ─────────────────────────


def test_rate_limit_per_ip_with_user_message(tmp_path, monkeypatch):
    calls = []

    def quick(plan_text: str) -> dict[str, Any]:
        calls.append(1)
        return fake_result(plan_text)

    srv, app = make(tmp_path, monkeypatch, quick, rate_per_min=2, cache_enabled=True)

    async def go() -> None:
        async with client(app) as c:
            a = {"X-Forwarded-For": "203.0.113.7"}
            assert (await c.post("/premortem", json={"plan_text": plan(1)}, headers=a)).status_code == 200
            assert (await c.post("/premortem", json={"plan_text": plan(2)}, headers=a)).status_code == 200
            r = await c.post("/premortem/view", json={"plan_text": plan(3)}, headers=a)
            assert r.status_code == 429
            body = r.json()
            assert body["error_code"] == "rate_limited" and body["message"].startswith("요청이 너무 잦습니다")
            assert "분당 2건" in body["message"]
            assert 1 <= int(r.headers["retry-after"]) <= 60
            assert_clean(r.text)
            # 다른 IP는 따로 센다(터널 뒤: 로컬 peer + X-Forwarded-For 마지막 값)
            b = {"X-Forwarded-For": "198.51.100.1, 203.0.113.99"}
            assert (await c.post("/premortem", json={"plan_text": plan(3)}, headers=b)).status_code == 200
            # 캐시 적중은 세지 않는다
            assert (await c.post("/premortem", json={"plan_text": plan(1)}, headers=a)).status_code == 200
            assert len(calls) == 3 and srv.counters["rate_429"] == 1

    asyncio.run(go())


def test_proxy_headers_trusted_only_from_loopback():
    scope = {"client": ("198.51.100.5", 1), "headers": [(b"x-forwarded-for", b"1.2.3.4, 10.0.0.9")]}
    assert serving.client_ip(scope, "loopback") == "198.51.100.5"  # 외부 peer가 보낸 XFF는 믿지 않는다
    assert serving.client_ip(scope, "always") == "1.2.3.4"  # 신뢰를 켜면 peer와 무관
    scope["client"] = ("127.0.0.1", 1)  # 터널(cloudflared)은 로컬에서 들어온다
    assert serving.client_ip(scope, "loopback") == "1.2.3.4"  # XFF 첫 값(기본)
    assert serving.client_ip(scope, "loopback", "last") == "10.0.0.9"
    scope["headers"].append((b"cf-connecting-ip", b"9.9.9.9"))
    assert serving.client_ip(scope, "loopback") == "9.9.9.9"  # CF-Connecting-IP가 먼저
    assert serving.client_ip(scope, "never") == "127.0.0.1"  # 신뢰를 끄면 client.host
    lim = serving.RateLimiter(2, 60, clock=lambda: 100.0)
    assert lim.hit("x")[0] and lim.hit("x")[0]
    ok, retry = lim.hit("x")
    assert not ok and retry == 60.0


# ───────────────────────── 입력 상한 ─────────────────────────


def test_input_size_limit_413(tmp_path, monkeypatch):
    calls = []
    srv, app = make(tmp_path, monkeypatch, lambda t: calls.append(1) or fake_result(t), max_plan_chars=200)

    async def go() -> None:
        async with client(app) as c:
            long = plan(1, "가" * 300)
            r = await c.post("/premortem/view", json={"plan_text": long})
            assert r.status_code == 413
            body = r.json()
            assert body["error_code"] == "too_large" and "200자 이하" in body["message"]
            assert f"현재 {len(long):,}자" in body["message"]
            assert_clean(r.text)
            # 바이트 상한: Content-Length만 보고 본문을 읽기 전에 거절
            big = json.dumps({"plan_text": "x" * 200_000}).encode()
            r2 = await c.post("/premortem", content=big, headers={"content-type": "application/json"})
            assert r2.status_code == 413 and r2.json()["error_code"] == "too_large"
            assert calls == []
            assert (await c.post("/premortem", json={"plan_text": plan(2)})).status_code == 200

    asyncio.run(go())


# ───────────────────────── 결과 캐시 ─────────────────────────


def test_user_input_is_cached_in_memory_only_never_on_disk(tmp_path, monkeypatch):
    """S-06: 사용자 입력 결과는 메모리 캐시만. 디스크(공유 data/cache/results)에는 파일도 본문 조각도 남지 않는다."""
    calls = []

    def quick(plan_text: str) -> dict[str, Any]:
        calls.append(1)
        return fake_result(plan_text)

    srv, app = make(tmp_path, monkeypatch, quick, cache_enabled=True)
    text = plan("cache")

    async def go(app: Any) -> list[httpx.Response]:
        async with client(app) as c:
            return [await c.post("/premortem/view", json={"plan_text": text}),
                    await c.post("/premortem", json={"plan_text": text})]

    r1, r2 = asyncio.run(go(app))
    assert (r1.status_code, r2.status_code) == (200, 200)
    assert r1.headers["x-neumann-cache"] == "miss" and r2.headers["x-neumann-cache"] == "hit"
    assert len(calls) == 1
    pid = serving.plan_key(text)
    assert r2.json()["plan_id"] == pid
    # 적중 결과에도 계획서 줄이 다시 붙는다(요청 본문으로 복원)
    assert any(BODY_MARK in ln["text"] for ln in r2.json()["plan"]["lines"])
    # 메모리 저장본에도 줄 텍스트는 없다
    assert BODY_MARK not in json.dumps(srv.cache.get(pid), ensure_ascii=False)
    # 디스크: 파일이 하나도 없고, tmp 전체 어디에도 본문 조각이 없다
    assert not (tmp_path / "results").exists() or list((tmp_path / "results").iterdir()) == []
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert BODY_MARK.encode() not in f.read_bytes(), f
    assert srv.cache.disk_stores == 0
    # 새 프로세스를 흉내(메모리 비어 있음) → 디스크에 없으므로 다시 돌린다
    srv2, app2 = make(tmp_path, monkeypatch, quick, cache_enabled=True)
    r3, _ = asyncio.run(go(app2))
    assert r3.headers["x-neumann-cache"] == "miss" and len(calls) == 2


def test_public_demo_input_goes_to_disk_without_plan_body(tmp_path, monkeypatch):
    """디스크 캐시는 허용 목록(데모·템플릿 plan_id)만. 저장본에는 줄 텍스트가 없고, 재시작 뒤에도 적중한다."""
    calls = []

    def quick(plan_text: str) -> dict[str, Any]:
        calls.append(1)
        return fake_result(plan_text)

    demo = plan("public-demo")
    allow = frozenset({serving.plan_key(demo)})
    srv, app = make(tmp_path, monkeypatch, quick, cache_enabled=True, disk_allow=allow)

    async def go(app: Any) -> httpx.Response:
        async with client(app) as c:
            return await c.post("/premortem/view", json={"plan_text": demo})

    assert asyncio.run(go(app)).headers["x-neumann-cache"] == "miss"
    pid = serving.plan_key(demo)
    f = tmp_path / "results" / f"{pid}.json"
    assert f.is_file() and srv.cache.disk_stores == 1
    stored = f.read_text(encoding="utf-8")
    assert BODY_MARK not in stored
    assert json.loads(stored)["result"]["plan"]["n_lines"] >= 3
    srv2, app2 = make(tmp_path, monkeypatch, quick, cache_enabled=True, disk_allow=allow)
    r = asyncio.run(go(app2))
    assert r.status_code == 200 and r.headers["x-neumann-cache"] == "hit" and len(calls) == 1
    assert r.json()["_status"]["serving"]["cache"] == "hit"
    assert any(BODY_MARK in ln["t"] for ln in r.json()["plan"]["lines"])


def test_disk_allowlist_is_exactly_three_demo_plans(monkeypatch):
    monkeypatch.delenv("NEUMANN_WARMUP_PLANS", raising=False)
    monkeypatch.delenv("NEUMANN_DISK_CACHE_ALLOW", raising=False)
    root = Path(serving.__file__).resolve().parents[3]
    demos = sorted((root / "tests" / "fixtures" / "plans").glob("plan*.md"))
    assert [p.name for p in demos] == ["plan.md", "plan_elife_neuro.md", "plan_medimaging.md"]
    c = serving.ServingConfig.from_env()
    assert set(c.warmup_plans) == set(demos)
    assert c.disk_allow == {serving.plan_key(p.read_text(encoding="utf-8")) for p in demos}
    assert len(c.disk_allow) == 3
    templates = sorted((root / "src" / "neumann" / "api" / "templates").glob("*.md"))
    assert templates and not {serving.plan_key(p.read_text(encoding="utf-8")) for p in templates} & c.disk_allow
    assert serving.plan_key(plan("user")) not in c.disk_allow


def test_public_profile_user_input_leaves_no_file_in_data_cache_results(tmp_path, monkeypatch):
    """화면 고지 "이 서버는 계획서 본문을 파일로 저장하지 않습니다"의 근거: 공개 프로필 기본 설정 그대로
    사용자 입력을 분석해도 <data_dir>/cache/results/에 새 파일이 0개다. 데모 계획서만 파일로 남는다."""
    from neumann.config import get_settings

    for k in ("NEUMANN_RESULT_CACHE_DIR", "NEUMANN_RESULT_CACHE", "NEUMANN_DISK_CACHE_ALLOW", "NEUMANN_BUDGET_FILE",
              "NEUMANN_BLOCK_FILE", "NEUMANN_WARMUP_PLANS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NEUMANN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEUMANN_PUBLIC", "1")
    get_settings.cache_clear()
    try:
        cfg = serving.ServingConfig.from_env()
    finally:
        get_settings.cache_clear()
    results = tmp_path / "cache" / "results"
    assert cfg.cache_enabled and cfg.cache_dir == results
    srv, app = make(tmp_path, monkeypatch, lambda t: fake_result(t), **{
        k: getattr(cfg, k) for k in ("cache_enabled", "cache_dir", "disk_allow", "cache_ttl_s", "cache_mem_items")})
    demo = (Path(serving.__file__).resolve().parents[3] / "tests" / "fixtures" / "plans" / "plan.md").read_text(
        encoding="utf-8")

    async def go() -> None:
        async with client(app) as c:
            for i in range(3):
                assert (await c.post("/premortem/view", json={"plan_text": plan(f"user{i}")})).status_code == 200
            assert not results.exists() or list(results.iterdir()) == []  # 사용자 입력 3건 → 새 파일 0개
            assert (await c.post("/premortem/view", json={"plan_text": demo})).status_code == 200

    asyncio.run(go())
    files = list(results.iterdir())
    assert [f.name for f in files] == [f"{serving.plan_key(demo)}.json"]  # 데모만
    assert BODY_MARK not in files[0].read_text(encoding="utf-8")


def test_memory_cache_ttl_and_size_cap():
    now = [0.0]
    c = serving.ResultCache(None, enabled=True, mem_items=2, ttl_s=10, clock=lambda: now[0])
    for ch in "abc":
        assert c.put(ch * 64, {"status": "ok", "plan_id": ch * 64})
    assert c.get("a" * 64) is None and c.memory_items == 2  # 개수 상한(LRU)
    now[0] = 11.0
    assert c.get("b" * 64) is None and c.get("c" * 64) is None  # TTL 지남


def test_cache_skips_degraded_and_other_variant(tmp_path):
    allow = {"c" * 64}
    c = serving.ResultCache(tmp_path, enabled=True, variant="openai:gpt-6-astra:1", disk_allow=allow)
    assert not c.put("a" * 64, {"status": "degraded", "plan_id": "a" * 64})
    assert not c.put("b" * 64, {"status": "ok", "sample": True})
    assert c.put("c" * 64, {"status": "ok", "plan_id": "c" * 64})
    other = serving.ResultCache(tmp_path, enabled=True, variant="mock:gpt-6-astra:1", disk_allow=allow)
    assert other.get("c" * 64) is None and c.get("c" * 64) is not None
    assert not serving.ResultCache(tmp_path, enabled=False).put("d" * 64, {"status": "ok"})


def test_warmup_fills_cache_from_demo_plans(tmp_path):
    p1, p2 = tmp_path / "demo1.md", tmp_path / "demo2.md"
    p1.write_text(plan("demo1"), encoding="utf-8")
    p2.write_text(plan("demo2"), encoding="utf-8")
    calls = []

    def quick(plan_text: str) -> dict[str, Any]:
        calls.append(1)
        return fake_result(plan_text)

    cfg = serving.ServingConfig(cache_enabled=True, cache_dir=tmp_path / "results", warmup=True,
                                warmup_plans=(p1, p2, tmp_path / "missing.md"),
                                disk_allow=frozenset(serving.public_plan_ids([p1, p2])))
    srv = serving.Serving(cfg)
    ws = asyncio.run(srv.warmup(quick))
    assert ws["state"] == "done" and ws["cached"] == 2 and ws["failed"] == 1 and len(calls) == 2
    assert srv.cache.has(serving.plan_key(plan("demo1")))
    ws2 = asyncio.run(serving.Serving(cfg).warmup(quick))  # 디스크 캐시가 있으면 다시 안 돌린다
    assert ws2["cached"] == 2 and len(calls) == 2


# ───────────────────────── 시간 상한·오류 문구 ─────────────────────────


def test_timeout_504_then_cached_result(tmp_path, monkeypatch):
    def slow(plan_text: str) -> dict[str, Any]:
        time.sleep(0.6)
        return fake_result(plan_text)

    srv, app = make(tmp_path, monkeypatch, slow, request_timeout_s=0.2, cache_enabled=True)

    async def go() -> None:
        async with client(app) as c:
            r = await c.post("/premortem/view", json={"plan_text": plan("slow")})
            assert r.status_code == 504
            body = r.json()
            assert body["error_code"] == "timeout"
            assert body["message"].startswith("분석이 0초 안에") or "안에 끝나지 않았습니다" in body["message"]
            assert body["_status"]["label"] == "분석 실패"  # 화면 모양(ui_view)은 유지
            assert_clean(r.text)
            await wait_until(lambda: srv.gate.active == 0)  # 분석은 끝까지 돌고 슬롯을 반납
            r2 = await c.post("/premortem/view", json={"plan_text": plan("slow")})
            assert r2.status_code == 200 and r2.headers["x-neumann-cache"] == "hit"
            assert srv.counters["timeout_504"] == 1

    asyncio.run(go())


def test_pipeline_error_is_user_message_without_internals(tmp_path, monkeypatch):
    def boom(plan_text: str) -> dict[str, Any]:
        raise RuntimeError(f"secret-internal-detail {FAKE_KEY} C:\\x\\y.py {plan_text}")

    srv, app = make(tmp_path, monkeypatch, boom)

    async def go() -> None:
        async with client(app) as c:
            for path in ("/premortem", "/premortem/view"):
                r = await c.post(path, json={"plan_text": plan("err")}, headers={"X-Neumann-Ticket": "tk_err_0001"})
                assert r.status_code == 500
                body = r.json()
                assert body["error_code"] == "internal" and body["ticket"] == "tk_err_0001"
                assert body["message"].startswith("처리 중 문제가 생겼습니다") and "tk_err_0001" in body["message"]
                assert "@ " not in r.text  # main의 "RuntimeError @ 파일:줄" 위치가 지워졌다
                assert_clean(r.text)
            view = r.json()
            assert view["_status"]["label"] == "분석 실패"
            assert "오류 종류: RuntimeError" in view["_status"]["notices"][0]  # 실패 종류는 숨기지 않는다
            # 422: FastAPI 기본 응답은 입력을 되돌려 보내므로 사용자 문구로 통째로 바꾼다
            r = await c.post("/premortem/view", json={"plan_text": "   \n", "filename": BODY_MARK})
            assert r.status_code == 422 and r.json()["error_code"] == "invalid_request"
            assert_clean(r.text)

    asyncio.run(go())


def test_unexpected_exception_in_app_becomes_500_message(tmp_path, monkeypatch):
    srv, app = make(tmp_path, monkeypatch, lambda t: fake_result(t))
    from neumann.api import main as api_main

    def explode(*a: Any, **k: Any) -> Any:
        raise ValueError(f"secret-internal-detail {FAKE_KEY}")

    monkeypatch.setattr(api_main, "_input_info", explode)  # main이 잡지 않는 곳에서 터뜨린다

    async def go() -> None:
        async with client(app) as c:
            r = await c.post("/premortem/view", json={"plan_text": plan("x")})
            assert r.status_code == 500 and r.json()["error_code"] == "internal"
            assert_clean(r.text)

    asyncio.run(go())


# ───────────────────────── 로그 위생 ─────────────────────────


def test_logs_have_plan_id_and_length_but_no_body_key_or_traceback(tmp_path, monkeypatch):
    def boom(plan_text: str) -> dict[str, Any]:
        raise RuntimeError(f"secret-internal-detail {FAKE_KEY}")

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        srv, app = make(tmp_path, monkeypatch, boom)  # install()이 로그 필터를 붙인다

        async def go() -> None:
            async with client(app) as c:
                await c.post("/premortem/view", json={"plan_text": plan("log")})
                await c.post("/premortem", json={"plan_text": plan("log2", "가" * 10)})

        asyncio.run(go())
        # 코드 어딘가가 키·트레이스를 로그에 흘려도 필터가 막는다
        logging.getLogger("neumann.api").error("leak %s", FAKE_KEY)
        try:
            raise KeyError("secret-internal-detail")
        except KeyError:
            logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    out = buf.getvalue()
    pid = serving.plan_key(plan("log"))
    assert f"plan_id={pid[:12]}" in out and f"chars={len(plan('log'))}" in out
    assert "req ticket=" in out and "status=500" in out
    assert "[트레이스 생략: KeyError]" in out
    assert serving.REDACTED in out
    assert_clean(out, response=False)
    assert "203.0.113" not in out and "127.0.0.1" not in out  # IP는 해시로만


def test_redacting_filter_hides_real_env_secret(monkeypatch):
    real_like = "Zz9" * 12
    monkeypatch.setenv("OPENAI_API_KEY", real_like)
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "value=%s", (real_like,), None)
    serving.RedactingFilter().filter(rec)
    assert real_like not in rec.getMessage() and serving.REDACTED in rec.getMessage()
    assert real_like not in serving.scrub_secrets(f"a {real_like} b")


def test_config_defaults_and_public_profile(monkeypatch):
    for k in ("NEUMANN_PUBLIC", "NEUMANN_RATE_PER_MIN", "NEUMANN_RESULT_CACHE", "NEUMANN_WARMUP",
              "NEUMANN_MAX_CONCURRENT", "NEUMANN_QUEUE_MAX", "NEUMANN_MAX_PLAN_CHARS", "NEUMANN_DAILY_BUDGET",
              "NEUMANN_HIDE_DOCS", "NEUMANN_AUX_RATE_PER_MIN", "NEUMANN_PROTECTED_PATHS", "NEUMANN_REQUEST_TIMEOUT_S",
              "NEUMANN_TRUST_XFF"):
        monkeypatch.delenv(k, raising=False)
    c = serving.ServingConfig.from_env()
    assert (c.max_concurrent, c.queue_max, c.max_plan_chars) == (2, 20, 50_000)
    assert (c.rate_per_min, c.cache_enabled, c.warmup) == (0, False, False)  # 테스트·개발: 꺼짐
    assert c.daily_budget == 0 and not c.hide_docs and c.trust_xff
    assert (c.request_timeout_s, c.queue_max) == (300.0, 20)
    assert c.protected == {"/premortem": "analysis", "/premortem/view": "analysis",
                           "/premortem/package": "export", "/upload/plan": "upload"}
    assert c.cache_dir is not None and c.cache_dir.parts[-2:] == ("cache", "results")
    monkeypatch.setenv("NEUMANN_PUBLIC", "1")
    c = serving.ServingConfig.from_env()
    assert (c.rate_per_min, c.cache_enabled, c.warmup) == (6, True, True)
    assert c.hide_docs and c.aux_rate_per_min == 30
    # FAIL 대응 4: 공개 기본값 — 시간 상한 90초(Cloudflare 약 100초보다 먼저), 일일 예산 끔(대표 결정)
    # E4-L2d(대표 지시 "여러 명이 동시에"): 동시 4·대기 30(작업 방식), 동기 경로는 대기 4까지만
    assert (c.request_timeout_s, c.queue_max, c.sync_queue_max, c.daily_budget) == (90.0, 30, 4, 0)
    assert c.max_concurrent == 4
    assert c.trust_xff is False  # 공개: X-Forwarded-For 무시, CF-Connecting-IP만
    monkeypatch.setenv("NEUMANN_RATE_PER_MIN", "10")
    monkeypatch.setenv("NEUMANN_MAX_CONCURRENT", "abc")
    c = serving.ServingConfig.from_env()
    assert c.rate_per_min == 10 and c.max_concurrent == 4  # 숫자가 아니면 공개 기본값
