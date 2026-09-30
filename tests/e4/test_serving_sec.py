"""E4-L2c SEC-1 대응 검사: 보호 경로(업로드·내보내기) 관문, 일일 예산, 차단 스위치, 스트리밍 바이트 상한,
전역 예외 처리기, 공개 응답의 경로·상류 API 문구 가림, /docs 숨김, 로그 필터, serve.py 공개 모드 사전 점검.

실제 파이프라인·OpenAI를 부르지 않는다. 느린 처리는 threading.Event로 멈추는 가짜 함수다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import Body, FastAPI, Request
from pydantic import BaseModel

from neumann.api import serving
from scripts import serve as serve_script
from scripts.serve_fake_app import fake_result
from tests.e4.test_serving import BODY_MARK, FAKE_KEY, Blocking, assert_clean, client, make, plan, wait_until


class Slow:
    """event가 풀릴 때까지(또는 hold초) 멈추는 가짜 처리. 동시 실행 수 최댓값을 잰다."""

    def __init__(self, hold: float | None = None) -> None:
        self.release = threading.Event()
        self.hold = hold
        self.lock = threading.Lock()
        self.now = self.peak = self.calls = self.done = 0

    def __call__(self) -> None:
        with self.lock:
            self.calls += 1
            self.now += 1
            self.peak = max(self.peak, self.now)
        try:
            if self.hold is not None:
                time.sleep(self.hold)
            else:
                self.release.wait(10)
        finally:
            with self.lock:
                self.now -= 1
                self.done += 1


class Echo(BaseModel):
    n: int


def side_app(tmp_path: Path, slow: Slow, **cfg: Any) -> tuple[serving.Serving, FastAPI]:
    """업로드·내보내기 모양의 가짜 라우트 + 서빙 층."""
    base: dict[str, Any] = dict(max_concurrent=1, queue_max=1, aux_concurrent=1, aux_queue_max=1, aux_timeout_s=5.0,
                                request_timeout_s=5.0, cache_enabled=False, cache_dir=tmp_path / "results")
    base.update(cfg)
    srv = serving.Serving(serving.ServingConfig(**base))
    app = FastAPI()

    @app.post("/upload/plan")
    async def upload(request: Request) -> dict[str, Any]:
        body = await request.body()
        await asyncio.to_thread(slow)
        return {"ok": True, "bytes": len(body)}

    @app.post("/premortem/package")
    async def package(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if payload.get("result") is None:  # 옛 경로 흉내: plan_text만 오면 파이프라인을 돈다
            await asyncio.to_thread(slow)
            return {"ran": "pipeline"}
        return {"ran": "zip"}

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(rf"C:\Users\bob\neumann\index\manifest.json {FAKE_KEY} secret-internal-detail")

    @app.post("/echo")
    def echo(body: Echo) -> dict[str, int]:
        return {"n": body.n}

    serving.install(app, srv)
    return srv, app


def raw_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000),
                                                          raise_app_exceptions=False),
                             base_url="http://t", timeout=30)


# ───────────────────────── S-02·S-03: 업로드·내보내기 관문 ─────────────────────────


def test_upload_path_has_concurrency_cap_queue_limit_and_503(tmp_path):
    slow = Slow()
    srv, app = side_app(tmp_path, slow, aux_concurrent=1, aux_queue_max=1)

    async def go() -> None:
        async with raw_client(app) as c:
            t1 = asyncio.create_task(c.post("/upload/plan", content=b"a" * 100))
            await wait_until(lambda: srv.aux_gate.active == 1)
            t2 = asyncio.create_task(c.post("/upload/plan", content=b"b" * 100))
            await wait_until(lambda: srv.aux_gate.waiting == 1)
            r3 = await c.post("/upload/plan", content=b"c" * 100)
            assert r3.status_code == 503 and r3.json()["error_code"] == "busy"
            assert r3.json()["message"].startswith("지금 처리 중인 요청이 많습니다")
            assert slow.peak == 1
            slow.release.set()
            r1, r2 = await asyncio.gather(t1, t2)
            assert (r1.status_code, r2.status_code) == (200, 200) and slow.peak == 1
            # 분석 관문과 따로 센다(업로드가 분석 슬롯을 먹지 않는다)
            assert srv.gate.active == 0 and srv.aux_gate.completed == 2

    asyncio.run(go())


def test_upload_time_limit_504_keeps_slot_until_work_ends(tmp_path):
    slow = Slow(hold=0.6)
    srv, app = side_app(tmp_path, slow, aux_timeout_s=0.2)

    async def go() -> None:
        async with raw_client(app) as c:
            r = await c.post("/upload/plan", content=b"x" * 10, headers={"X-Neumann-Ticket": "tk_up_timeout"})
            assert r.status_code == 504
            body = r.json()
            assert body["error_code"] == "timeout" and body["request_id"] == "tk_up_timeout"
            assert "0초 안에 끝나지 않았습니다" in body["message"]
            assert srv.aux_gate.active == 1  # 처리는 아직 돈다 → 슬롯을 쥐고 있다(과부하 누적 방지)
            await wait_until(lambda: srv.aux_gate.active == 0, timeout=3)
            assert slow.done == 1

    asyncio.run(go())


def test_upload_rate_limit_is_separate_bucket(tmp_path):
    slow = Slow(hold=0.0)
    srv, app = side_app(tmp_path, slow, aux_rate_per_min=2)

    async def go() -> None:
        async with raw_client(app) as c:
            h = {"CF-Connecting-IP": "203.0.113.50"}
            assert (await c.post("/upload/plan", content=b"1", headers=h)).status_code == 200
            assert (await c.post("/upload/plan", content=b"2", headers=h)).status_code == 200
            r = await c.post("/upload/plan", content=b"3", headers=h)
            assert r.status_code == 429 and "분당 2건" in r.json()["message"]
            other = {"CF-Connecting-IP": "203.0.113.51"}
            assert (await c.post("/upload/plan", content=b"4", headers=other)).status_code == 200

    asyncio.run(go())


def test_body_byte_cap_by_content_length_and_streaming_before_parse(tmp_path):
    slow = Slow(hold=0.0)
    srv, app = side_app(tmp_path, slow, max_upload_bytes=1000, max_plan_chars=100)

    async def chunks(parts: list[bytes]):
        for part in parts:
            yield part

    async def go() -> None:
        async with raw_client(app) as c:
            r = await c.post("/upload/plan", content=b"z" * 2000)  # Content-Length로 거절
            assert r.status_code == 413 and r.json()["error_code"] == "too_large"
            r = await c.post("/upload/plan", content=chunks([b"z" * 256] * 8))  # Content-Length 없음 → 누적으로 거절
            assert r.status_code == 413 and "content-length" not in {k.lower() for k in r.request.headers}
            assert slow.calls == 0
            # 분석 경로: 바이트 상한(=글자 상한*6+64KB)을 스트리밍으로 넘기면 JSON을 파싱하기 전에 413
            limit = srv.config.analysis_body_bytes
            big = [b'{"plan_text": "', *([b"x" * 4096] * (limit // 4096 + 2)), b'"}']
            r = await c.post("/premortem", content=chunks(big), headers={"content-type": "application/json"})
            assert r.status_code == 413 and BODY_MARK not in r.text and "xxxx" not in r.text
            assert srv.counters["too_large_413"] == 3

    asyncio.run(go())


def test_legacy_package_plan_text_uses_analysis_gate_budget_and_block(tmp_path):
    """옛 내보내기(plan_text만 → 파이프라인)는 분석과 같은 관문·예산·차단 스위치로 묶인다. result 내보내기는 영향 없음."""
    slow = Slow()
    block = tmp_path / "block.flag"
    srv, app = side_app(tmp_path, slow, max_concurrent=1, queue_max=0, daily_budget=5,
                        budget_file=tmp_path / "budget.json", block_file=block)

    async def go() -> None:
        async with raw_client(app) as c:
            t1 = asyncio.create_task(c.post("/premortem/package", json={"plan_text": plan("pkg1")}))
            await wait_until(lambda: srv.gate.active == 1)  # 분석 관문 슬롯을 잡았다
            r2 = await c.post("/premortem/package", json={"plan_text": plan("pkg2")})
            assert r2.status_code == 503 and r2.json()["error_code"] == "busy"
            ok = await c.post("/premortem/package", json={"result": {"plan_id": "x"}})  # 결과 내보내기는 보조 관문
            assert ok.status_code == 200 and ok.json() == {"ran": "zip"}
            slow.release.set()
            assert (await t1).status_code == 200
            assert srv.budget.used == 1  # 거절된 요청은 예산을 쓰지 않는다
            block.write_text("stop", encoding="utf-8")
            r = await c.post("/premortem/package", json={"plan_text": plan("pkg3")})
            assert r.status_code == 503 and r.json()["error_code"] == "blocked"
            assert (await c.post("/premortem/package", json={"result": {"a": 1}})).status_code == 200

    asyncio.run(go())


def test_protected_paths_are_configurable(monkeypatch):
    monkeypatch.setenv("NEUMANN_PROTECTED_PATHS", "/premortem=analysis;/x/y;/z=bogus;/upload/plan")
    c = serving.ServingConfig.from_env()
    assert c.protected == {"/premortem": "analysis", "/x/y": "gated", "/z": "gated", "/upload/plan": "upload"}
    assert c.body_limit("upload") == c.max_upload_bytes and c.body_limit("gated") == c.max_export_bytes


# ───────────────────────── S-01: 일일 예산·차단 스위치 ─────────────────────────


def test_daily_budget_503_cache_still_served_and_persists(tmp_path, monkeypatch):
    calls = []

    def quick(plan_text: str) -> dict[str, Any]:
        calls.append(1)
        return fake_result(plan_text)

    bfile = tmp_path / "budget.json"
    srv, app = make(tmp_path, monkeypatch, quick, cache_enabled=True, daily_budget=2, budget_file=bfile)

    async def go(app: Any, *texts: str) -> list[httpx.Response]:
        async with client(app) as c:
            return [await c.post("/premortem/view", json={"plan_text": t}) for t in texts]

    r1, r2, r3, r4 = asyncio.run(go(app, plan(1), plan(2), plan(3), plan(1)))
    assert [r.status_code for r in (r1, r2, r3, r4)] == [200, 200, 503, 200]
    assert r3.json()["error_code"] == "budget_exhausted" and "분석 한도(2건)" in r3.json()["message"]
    assert r4.headers["x-neumann-cache"] == "hit"  # 한도가 끝나도 이미 분석된 계획서는 계속
    assert len(calls) == 2 and json.loads(bfile.read_text(encoding="utf-8"))["used"] == 2
    assert_clean(r3.text)
    # 재시작해도(새 Serving) 오늘 쓴 양은 이어진다
    srv2, app2 = make(tmp_path, monkeypatch, quick, cache_enabled=True, daily_budget=2, budget_file=bfile)
    (r5,) = asyncio.run(go(app2, plan(4)))
    assert r5.status_code == 503 and len(calls) == 2
    st = asyncio.run(_status(app2))
    assert st["budget"]["remaining"] == 0 and st["accepting"] is False


async def _status(app: Any) -> dict[str, Any]:
    async with client(app) as c:
        return (await c.get("/queue/status")).json()


def test_budget_day_rollover_and_join_does_not_spend(tmp_path, monkeypatch):
    day = ["2026-09-30"]
    b = serving.DailyBudget(1, tmp_path / "b.json", today=lambda: day[0])
    b.spend()
    assert b.exhausted()
    day[0] = "2026-10-01"
    assert not b.exhausted() and b.status()["used"] == 0

    fake = Blocking()
    srv, app = make(tmp_path, monkeypatch, fake, max_concurrent=1, queue_max=0, daily_budget=1,
                    budget_file=tmp_path / "b2.json")

    async def go() -> None:
        async with client(app) as c:
            t1 = asyncio.create_task(c.post("/premortem", json={"plan_text": plan("join")}))
            await wait_until(lambda: fake.calls == 1)
            t2 = asyncio.create_task(c.post("/premortem", json={"plan_text": plan("join")}))
            await wait_until(lambda: srv.counters["joined"] == 1)
            fake.release.set()
            assert [r.status_code for r in await asyncio.gather(t1, t2)] == [200, 200]
            assert srv.budget.used == 1

    asyncio.run(go())


def test_block_switch_by_file_and_env_keeps_cache(tmp_path, monkeypatch):
    flag = tmp_path / "serving_block.flag"
    srv, app = make(tmp_path, monkeypatch, lambda t: fake_result(t), cache_enabled=True, block_file=flag)

    async def go(app: Any) -> None:
        async with client(app) as c:
            assert (await c.post("/premortem/view", json={"plan_text": plan("b1")})).status_code == 200
            flag.write_text("", encoding="utf-8")  # 즉시 차단(재시작 불필요)
            r = await c.post("/premortem/view", json={"plan_text": plan("b2")})
            assert r.status_code == 503 and r.json()["error_code"] == "blocked"
            assert r.json()["message"].startswith("지금은 새 분석을 잠시 멈췄습니다")
            cached = await c.post("/premortem/view", json={"plan_text": plan("b1")})
            assert cached.status_code == 200 and cached.headers["x-neumann-cache"] == "hit"
            assert (await c.get("/queue/status")).json()["blocked"] is True
            flag.unlink()
            assert (await c.post("/premortem/view", json={"plan_text": plan("b2")})).status_code == 200

    asyncio.run(go(app))
    srv2, app2 = make(tmp_path, monkeypatch, lambda t: fake_result(t), block_new=True)

    async def go2() -> None:
        async with client(app2) as c:
            assert (await c.post("/premortem", json={"plan_text": plan("b3")})).json()["error_code"] == "blocked"

    asyncio.run(go2())


# ───────────────────────── S-04: 예외·오류 문구 ─────────────────────────


def test_global_exception_handler_returns_only_code_and_request_id(tmp_path):
    srv, app = side_app(tmp_path, Slow(hold=0.0))

    async def go() -> None:
        async with raw_client(app) as c:
            r = await c.get("/boom", headers={"X-Request-Id": "req_abc_123"})
            assert r.status_code == 500
            body = r.json()
            assert body["error_code"] == "internal" and body["request_id"] == "req_abc_123"
            assert set(body) == {"status", "error_code", "message", "request_id", "ticket"}
            for bad in ("C:\\", "Users", "manifest.json", "RuntimeError", "secret-internal-detail", FAKE_KEY[:6]):
                assert bad not in r.text, bad
            # 422: 입력을 되돌려 보내지 않는다(FastAPI 기본은 input을 통째로 싣는다)
            r = await c.post("/echo", json={"n": BODY_MARK * 50})
            assert r.status_code == 422 and r.json()["error_code"] == "invalid_request"
            assert BODY_MARK not in r.text and r.json()["detail"][0]["loc"] == ["body", "n"]

    asyncio.run(go())


def test_ok_response_hides_paths_and_upstream_api_text_but_keeps_quotes(tmp_path, monkeypatch):
    quote = r"We used C:\data\split.csv and HTTP 404 pages (quoted)."

    def degraded(plan_text: str) -> dict[str, Any]:
        data = fake_result(plan_text)
        data["notices"] = [
            r"IndexNotBuilt: 색인이 없다: C:\Users\bob\neumann\data\index\manifest.json (python scripts/build_index.py)",
            "비상 규칙 경로: openai:gpt-6-astra api_error (HTTP 401 Incorrect API key provided: "
            + "s" + "k-proj-ab" + "*" * 20 + "wxyz. You can find your API key at https://platform.example/keys.)",
            "/home/runner/secret/cache.sqlite 열기 실패",
        ]
        data["evidence"][0]["text"] = quote  # 근거 인용은 글자 그대로여야 한다
        return data

    srv, app = make(tmp_path, monkeypatch, degraded)

    async def go() -> httpx.Response:
        async with client(app) as c:
            return await c.post("/premortem", json={"plan_text": plan("diag")})

    r = asyncio.run(go())
    assert r.status_code == 200
    notices = r.json()["notices"]
    joined = " ".join(notices)
    for bad in ("C:\\Users", "bob", "Incorrect API key", "You can find", "k-proj-ab", "/home/runner"):
        assert bad not in joined, bad
    assert "IndexNotBuilt" in joined and "HTTP 401" in joined and "[경로]" in joined  # 분류는 남긴다
    assert r.json()["evidence"][0]["text"] == quote


def test_docs_hidden_in_public_mode(tmp_path):
    for hide, code in ((True, 404), (False, 200)):
        srv, app = side_app(tmp_path, Slow(hold=0.0), hide_docs=hide)

        async def go() -> list[int]:
            async with raw_client(app) as c:
                return [(await c.get(p)).status_code for p in ("/docs", "/openapi.json", "/redoc")]

        assert asyncio.run(go()) == [code] * 3


def test_log_filter_keeps_uvicorn_access_args_and_scrubs_them():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:5000", "GET", f"/queue/status?ticket={FAKE_KEY}", "1.1", 200), None)
    serving.RedactingFilter().filter(rec)
    assert isinstance(rec.args, tuple) and len(rec.args) == 5  # 접근 로그 포매터가 풀어 쓰는 모양 유지
    msg = rec.getMessage()
    assert FAKE_KEY not in msg and serving.REDACTED in msg and msg.endswith("200")


# ───────────────────────── S-05: 공개 모드 사전 점검 ─────────────────────────


def test_serve_public_preflight_refuses_mock_or_missing_key(monkeypatch):
    from neumann.config import Settings

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "mock")
    ok, why = serve_script.preflight_public(Settings(_env_file=None))
    assert not ok and "provider=openai" in why
    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    ok, why = serve_script.preflight_public(Settings(_env_file=None))
    assert not ok and "OPENAI_API_KEY가 없다" in why
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key-for-tests")
    ok, why = serve_script.preflight_public(Settings(_env_file=None))
    assert ok and "key=있음" in why and "not-a-real" not in why  # 값은 쓰지 않는다


def test_serve_public_dry_run_exit_code(monkeypatch, tmp_path, capsys):
    from neumann.config import get_settings

    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "mock")  # 환경변수가 .env보다 먼저다
    try:
        rc = serve_script.main(["--public", "--dry-run", "--log-file", str(tmp_path / "serve.log")])
    finally:
        get_settings.cache_clear()
    assert rc == 2
    assert "공개 모드 사전 점검: 거부" in (tmp_path / "serve.log").read_text(encoding="utf-8")
    assert serve_script.main(["--dry-run", "--log-file", str(tmp_path / "serve2.log")]) == 0  # 공개 아님: 점검 없음
