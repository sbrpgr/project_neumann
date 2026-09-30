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


MP = {"content-type": "multipart/form-data; boundary=XyZ"}


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
            t1 = asyncio.create_task(c.post("/upload/plan", content=b"a" * 100, headers=MP))
            await wait_until(lambda: srv.aux_gate.active == 1)
            t2 = asyncio.create_task(c.post("/upload/plan", content=b"b" * 100, headers=MP))
            await wait_until(lambda: srv.aux_gate.waiting == 1)
            r3 = await c.post("/upload/plan", content=b"c" * 100, headers=MP)
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
            r = await c.post("/upload/plan", content=b"x" * 10, headers={**MP, "X-Neumann-Ticket": "tk_up_timeout"})
            assert r.status_code == 504
            body = r.json()
            assert body["error_code"] == "timeout" and body["request_id"] == "tk_up_timeout"
            assert "0초 안에 끝나지 않았습니다" in body["message"]
            assert srv.aux_gate.active == 1  # 처리는 아직 돈다 → 슬롯을 쥐고 있다(과부하 누적 방지)
            await wait_until(lambda: srv.aux_gate.active == 0)
            assert slow.done == 1

    asyncio.run(go())


def test_upload_rate_limit_is_separate_bucket(tmp_path):
    slow = Slow(hold=0.0)
    srv, app = side_app(tmp_path, slow, upload_rate_per_min=2, aux_rate_per_min=100)

    async def go() -> None:
        async with raw_client(app) as c:
            h = {**MP, "CF-Connecting-IP": "203.0.113.50"}
            assert (await c.post("/upload/plan", content=b"1", headers=h)).status_code == 200
            assert (await c.post("/upload/plan", content=b"2", headers=h)).status_code == 200
            r = await c.post("/upload/plan", content=b"3", headers=h)
            assert r.status_code == 429 and "분당 2건" in r.json()["message"]
            other = {**MP, "CF-Connecting-IP": "203.0.113.51"}
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
            r = await c.post("/upload/plan", content=b"z" * 2000, headers=MP)  # Content-Length로 거절
            assert r.status_code == 413 and r.json()["error_code"] == "too_large"
            r = await c.post("/upload/plan", content=chunks([b"z" * 256] * 8), headers=MP)  # CL 없음 → 누적으로 거절
            assert r.status_code == 413 and "content-length" not in {k.lower() for k in r.request.headers}
            assert slow.calls == 0
            # 분석 경로: 바이트 상한(=글자 상한*6+64KB)을 스트리밍으로 넘기면 JSON을 파싱하기 전에 413
            limit = srv.config.analysis_body_bytes
            big = [b'{"plan_text": "', *([b"x" * 4096] * (limit // 4096 + 2)), b'"}']
            r = await c.post("/premortem", content=chunks(big), headers={"content-type": "application/json"})
            assert r.status_code == 413 and BODY_MARK not in r.text and "xxxx" not in r.text
            assert srv.counters["too_large_413"] == 3

    asyncio.run(go())


def test_package_plan_text_only_is_422_without_touching_analysis_gate_or_budget(tmp_path):
    """FAIL 대응 3: 실제 내보내기 라우터에 plan_text만 보내면 422. 분석 슬롯·예산·분석 속도 제한을 쓰지 않는다."""
    from neumann.api.export import router as export_router

    srv = serving.Serving(serving.ServingConfig(max_concurrent=1, queue_max=0, rate_per_min=1, daily_budget=1,
                                                budget_file=tmp_path / "b.json", cache_enabled=False))
    app = FastAPI()
    app.include_router(export_router)
    serving.install(app, srv)

    async def go() -> None:
        async with raw_client(app) as c:
            for i in range(3):
                r = await c.post("/premortem/package", json={"plan_text": plan(f"pkg{i}")})
                assert r.status_code == 422 and "분석 결과가 필요합니다" in r.text
                assert BODY_MARK not in r.text
            assert srv.budget.used == 0 and srv.gate.completed == 0 and srv.gate.active == 0
            assert srv.aux_gate.completed == 3  # 보조 관문만 지났다
            assert srv.counters["rate_429"] == 0  # 분석 속도 제한(분당 1)도 쓰지 않았다

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
    assert st["accepting"] is False
    assert "budget" not in st and "daily_budget" not in st["limits"]  # 예산 수치는 공개하지 않는다


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
            assert set(body) == {"status", "error_code", "message", "detail", "request_id", "ticket"}
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


# ───────────────────────── FAIL 대응 1: 본문 인코딩으로 관문 우회 ─────────────────────────

def _encodings(obj: dict[str, Any]) -> dict[str, bytes]:
    text = json.dumps(obj, ensure_ascii=False)
    return {
        "utf8-bom": ("\ufeff" + text).encode("utf-8"),
        "utf16": text.encode("utf-16"),
        "utf16-le": text.encode("utf-16-le"),
        "utf32": text.encode("utf-32"),
    }


JSON_H = {"content-type": "application/json"}


def test_encoded_bodies_are_parsed_like_the_app_and_cannot_bypass_admission(tmp_path, monkeypatch):
    """BOM·UTF-16·UTF-32 본문도 미들웨어가 앱과 같이 읽어 차단·예산·속도 제한·대기열·글자 상한을 그대로 건다."""
    calls = []

    def quick(plan_text: str) -> dict[str, Any]:
        calls.append(1)
        return fake_result(plan_text)

    flag = tmp_path / "block.flag"
    srv, app = make(tmp_path, monkeypatch, quick, block_file=flag, max_plan_chars=2000)

    async def go() -> None:
        async with client(app) as c:
            # 인코딩만 바꾼 정상 요청은 정상 처리(파서가 앱과 같다)
            for name, raw in _encodings({"plan_text": plan("enc-ok")}).items():
                r = await c.post("/premortem/view", content=raw, headers=JSON_H)
                assert r.status_code == 200, name
            n = len(calls)
            # 차단 스위치
            flag.write_text("", encoding="utf-8")
            for name, raw in _encodings({"plan_text": plan("enc-block")}).items():
                r = await c.post("/premortem/view", content=raw, headers=JSON_H)
                assert r.status_code == 503 and r.json()["error_code"] == "blocked", name
            flag.unlink()
            # 글자 상한
            for name, raw in _encodings({"plan_text": plan("enc-long", "가" * 3000)}).items():
                r = await c.post("/premortem", content=raw, headers=JSON_H)
                assert r.status_code == 413 and r.json()["error_code"] == "too_large", name
            assert len(calls) == n  # 거절된 요청은 파이프라인을 한 번도 부르지 않았다

    asyncio.run(go())


def test_encoded_bodies_hit_budget_rate_and_queue_limits(tmp_path, monkeypatch):
    fake = Blocking()
    srv, app = make(tmp_path, monkeypatch, fake, max_concurrent=1, queue_max=1, rate_per_min=3, daily_budget=3,
                    budget_file=tmp_path / "b.json")

    async def go() -> None:
        async with client(app) as c:
            enc = lambda i, name: _encodings({"plan_text": plan(f"q{i}")})[name]  # noqa: E731
            h1 = {**JSON_H, "CF-Connecting-IP": "198.51.100.1"}
            t1 = asyncio.create_task(c.post("/premortem", content=enc(1, "utf8-bom"), headers=h1))
            await wait_until(lambda: srv.gate.active == 1)
            t2 = asyncio.create_task(c.post("/premortem", content=enc(2, "utf16"),
                                            headers={**JSON_H, "CF-Connecting-IP": "198.51.100.2"}))
            await wait_until(lambda: srv.gate.waiting == 1)
            r = await c.post("/premortem", content=enc(3, "utf32"), headers={**JSON_H, "CF-Connecting-IP": "198.51.100.3"})
            assert r.status_code == 503 and r.json()["error_code"] == "busy"  # 대기열 상한
            fake.release.set()
            assert [x.status_code for x in await asyncio.gather(t1, t2)] == [200, 200]
            # 속도 제한: 같은 IP에서 BOM으로 계속(분당 3, 이미 1건 사용)
            codes = []
            for i in range(4, 7):
                codes.append((await c.post("/premortem", content=enc(i, "utf8-bom"), headers=h1)).status_code)
            assert codes[-1] == 429
            # 예산 3건(2건 + 속도 제한 전 1건)을 다 쓰면 인코딩과 무관하게 503
            assert srv.budget.used == 3
            r = await c.post("/premortem", content=enc(9, "utf16-le"), headers={**JSON_H, "CF-Connecting-IP": "203.0.113.9"})
            assert r.status_code == 503 and r.json()["error_code"] == "budget_exhausted"
            assert srv.budget.used == 3

    asyncio.run(go())


def test_unreadable_or_invalid_analysis_body_is_rejected_before_the_app(tmp_path, monkeypatch):
    """분석 경로는 plan_text를 문자열로 못 읽으면 앱에 넘기지 않고 422(fail-closed). 깊은 중첩도 500이 아니다."""
    calls = []
    srv, app = make(tmp_path, monkeypatch, lambda t: calls.append(1) or fake_result(t))
    bad = [
        b"\xff\xfe\x00garbage",                      # 깨진 UTF-16
        b"{not json",                                  # 잘못된 JSON
        b"[" * 100_000 + b"]" * 100_000,               # 깊은 중첩(RecursionError)
        json.dumps({"plan_text": 123}).encode(),       # 문자열 아님
        json.dumps({"text": plan("x")}).encode(),      # 키 없음
        json.dumps([plan("x")]).encode(),              # dict 아님
        json.dumps({"plan_text": "   "}).encode(),     # 빈 본문
        b"",
    ]

    async def go() -> None:
        async with client(app) as c:
            for raw in bad:
                r = await c.post("/premortem/view", content=raw, headers=JSON_H)
                assert r.status_code == 422 and r.json()["error_code"] == "invalid_request", raw[:20]
                assert_clean(r.text)
            assert calls == [] and srv.gate.completed == 0 and srv.budget.used == 0
            # 짝 없는 서로게이트(\ud800)도 500 없이 처리한다
            r = await c.post("/premortem", content=b'{"plan_text": "abc \\ud800 def"}', headers=JSON_H)
            assert r.status_code in (200, 422)

    asyncio.run(go())


def test_run_rechecks_admission_when_middleware_did_not_reserve(tmp_path):
    """두 번째 방어선: 미들웨어 예약 없이 Serving.run()에 들어온 실행도 차단·예산·대기열을 검사한다. force는 예열만."""
    flag = tmp_path / "block.flag"
    srv = serving.Serving(serving.ServingConfig(max_concurrent=1, queue_max=0, daily_budget=1,
                                                budget_file=tmp_path / "b.json", block_file=flag))
    calls = []

    def quick(plan_text: str) -> dict[str, Any]:
        calls.append(1)
        return fake_result(plan_text)

    async def go() -> None:
        flag.write_text("", encoding="utf-8")
        with pytest.raises(serving.AdmissionRefused):
            await srv.run(quick, plan("r1"))  # 문맥 없음 = 외부 실행 → 검사
        flag.unlink()
        await srv.run(quick, plan("r2"))
        with pytest.raises(serving.AdmissionRefused):
            await srv.run(quick, plan("r3"))  # 예산 1건 소진
        assert len(calls) == 1 and srv.budget.used == 1
        token = serving._CTX.set(serving.RequestCtx(ticket="warm_test01", path="warmup", internal=True))
        try:
            await srv.run(quick, plan("r4"))  # 예열은 force로 들어간다(운영자가 켠 내부 작업)
        finally:
            serving._CTX.reset(token)
        assert len(calls) == 2

    asyncio.run(go())


# ───────────────────────── FAIL 대응 2: IPv6 /64, 공개 프로필 XFF 무시 ─────────────────────────


def test_ipv6_addresses_in_same_64_share_one_rate_limit(tmp_path, monkeypatch):
    assert serving.ip_key("2001:db8:1:2:aaaa::1") == serving.ip_key("2001:db8:1:2:ffff:1:2:3") == "2001:db8:1:2::/64"
    assert serving.ip_key("2001:db8:1:3::1") != serving.ip_key("2001:db8:1:2::1")
    assert serving.ip_key("::ffff:198.51.100.7") == "198.51.100.7" and serving.ip_key("198.51.100.7") == "198.51.100.7"
    srv, app = make(tmp_path, monkeypatch, lambda t: fake_result(t), rate_per_min=3)

    async def go() -> list[int]:
        async with client(app) as c:
            return [(await c.post("/premortem", json={"plan_text": plan(f"v6-{i}")},
                                  headers={"CF-Connecting-IP": f"2001:db8:1:2::{i + 1:x}"})).status_code
                    for i in range(5)]

    assert asyncio.run(go()) == [200, 200, 200, 429, 429]


def test_public_profile_ignores_x_forwarded_for(tmp_path, monkeypatch):
    srv, app = make(tmp_path, monkeypatch, lambda t: fake_result(t), rate_per_min=2, trust_xff=False)

    async def go() -> list[int]:
        async with client(app) as c:
            return [(await c.post("/premortem", json={"plan_text": plan(f"xff-{i}")},
                                  headers={"X-Forwarded-For": f"203.0.113.{i + 1}"})).status_code for i in range(4)]

    assert asyncio.run(go()) == [200, 200, 429, 429]  # XFF를 바꿔도 한 통(루프백)으로 센다
    scope = {"client": ("127.0.0.1", 1), "headers": [(b"x-forwarded-for", b"1.2.3.4"), (b"cf-connecting-ip", b"9.9.9.9")]}
    assert serving.client_ip(scope, "loopback", use_xff=False) == "9.9.9.9"
    scope["headers"] = [(b"x-forwarded-for", b"1.2.3.4")]
    assert serving.client_ip(scope, "loopback", use_xff=False) == "127.0.0.1"


def test_queue_status_public_hides_budget_and_counters(tmp_path):
    srv = serving.Serving(serving.ServingConfig(public=True, daily_budget=5, budget_file=tmp_path / "b.json"))
    st = srv.queue_status("tk_pub_status")
    assert "budget" not in st and "counters" not in st and "cache" not in st and "daily_budget" not in st["limits"]
    assert {"active", "waiting", "accepting", "ticket"} <= set(st)


def test_ip_tag_is_salted_hmac_and_hides_env_salt(monkeypatch):
    monkeypatch.setattr(serving, "_IP_SALT", None)
    monkeypatch.setenv("NEUMANN_PSEUDONYM_SALT", "salt-value-for-tests-only")
    a = serving._ip_tag("198.51.100.7")
    import hashlib

    unsalted = "ip_" + hashlib.sha256(("neumann-ip:" + "198.51.100.7").encode()).hexdigest()[:10]
    assert a != unsalted and a == serving._ip_tag("198.51.100.7") and len(a) == 13
    assert serving._ip_tag("2001:db8::1") == serving._ip_tag("2001:db8::2")  # /64 묶음
    monkeypatch.setattr(serving, "_IP_SALT", None)
    monkeypatch.delenv("NEUMANN_PSEUDONYM_SALT")
    assert serving._ip_tag("198.51.100.7") != a  # 솔트가 없으면 프로세스마다 무작위


def test_serve_public_preflight_refuses_do_not_serve_index(monkeypatch, tmp_path):
    """SEC-2r: 서비스 금지 표시(DO_NOT_SERVE.txt)가 있는 색인으로는 공개 기동을 거부한다."""
    from neumann.config import Settings

    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key-for-tests")
    bad, good = tmp_path / "index_elife", tmp_path / "index"
    bad.mkdir()
    good.mkdir()
    (bad / "DO_NOT_SERVE.txt").write_text("DO NOT SERVE", encoding="utf-8")
    monkeypatch.setenv("NEUMANN_INDEX_DIR", str(bad))
    ok, why = serve_script.preflight_public(Settings(_env_file=None))
    assert not ok and "DO_NOT_SERVE" in why and "not-a-real" not in why
    monkeypatch.setenv("NEUMANN_INDEX_DIR", str(good))
    ok, why = serve_script.preflight_public(Settings(_env_file=None))
    assert ok, why
    monkeypatch.delenv("NEUMANN_INDEX_DIR")  # 지정이 없으면 <data_dir>/index를 본다
    monkeypatch.setenv("NEUMANN_DATA_DIR", str(tmp_path))
    (good / "DO_NOT_SERVE.txt").write_text("x", encoding="utf-8")
    ok, why = serve_script.preflight_public(Settings(_env_file=None))
    assert not ok and "DO_NOT_SERVE" in why


def test_serve_public_preflight_checks_effective_index_dir(monkeypatch, tmp_path):
    """.env에만 적힌 NEUMANN_INDEX_DIR처럼 서버가 실제로 읽는 경로(index.settings)에 DO_NOT_SERVE가 있어도 거부한다."""
    from types import SimpleNamespace

    import neumann.index.settings as idx_settings
    from neumann.config import Settings

    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key-for-tests")
    good, bad = tmp_path / "index", tmp_path / "index_elife_epmc"
    good.mkdir()
    bad.mkdir()
    (bad / "DO_NOT_SERVE.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv("NEUMANN_INDEX_DIR", str(good))  # 환경변수 쪽은 정상

    fake = SimpleNamespace(resolved_index_dir=lambda: bad)  # 실효 경로(.env 등)는 금지 색인
    fake_get = lambda: fake  # noqa: E731
    fake_get.cache_clear = lambda: None
    monkeypatch.setattr(idx_settings, "get_index_settings", fake_get)
    ok, why = serve_script.preflight_public(Settings(_env_file=None))
    assert not ok and "DO_NOT_SERVE" in why

    def boom():
        raise RuntimeError("x")

    boom.cache_clear = lambda: None
    monkeypatch.setattr(idx_settings, "get_index_settings", boom)
    ok, why = serve_script.preflight_public(Settings(_env_file=None))
    assert not ok and "색인 경로" in why  # 경로를 못 구하면 닫힌 쪽


def test_serve_public_preflight_refuses_whitespace_key(monkeypatch):
    from neumann.config import Settings

    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "      ")
    ok, why = serve_script.preflight_public(Settings(_env_file=None))
    assert not ok and "OPENAI_API_KEY" in why


# ───────────────────────── 재작업 2: 업로드(E4-L1a 실제 라우터) ─────────────────────────

UPLOAD_LIMIT = 10 * 1024 * 1024 + 64 * 1024  # upload.py: 파일 10MB + multipart 64KB


def _multipart(data: bytes, filename: str = "plan.md", boundary: str = "XyZ") -> bytes:
    return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: text/markdown\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()


def upload_app(tmp_path: Path, **cfg: Any) -> tuple[serving.Serving, FastAPI]:
    from neumann.api.upload import router as upload_router

    base: dict[str, Any] = dict(cache_enabled=False, aux_concurrent=2, aux_queue_max=10)
    base.update(cfg)
    srv = serving.Serving(serving.ServingConfig(**base))
    app = FastAPI()
    app.include_router(upload_router)
    serving.install(app, srv)
    return srv, app


def test_upload_body_cap_is_upload_only_10mb_by_length_chunked_and_lying_length(tmp_path):
    """업로드에만 10MB(+multipart 64KB) 상한: Content-Length·chunked·거짓 Content-Length 모두 앱에 닿기 전 413."""
    srv, app = upload_app(tmp_path)
    assert srv.config.body_limit("upload") == UPLOAD_LIMIT != srv.config.body_limit("analysis")
    small = _multipart("# 연구 목표\n본문\n".encode("utf-8"))

    async def chunks(n_bytes: int):
        step = 1024 * 1024
        for _ in range(0, n_bytes, step):
            yield b"z" * step

    async def go() -> None:
        async with raw_client(app) as c:
            ok = await c.post("/upload/plan", content=small, headers=MP)
            assert ok.status_code == 200 and ok.json()["kind"] == "md"
            r = await c.post("/upload/plan", content=b"z" * (UPLOAD_LIMIT + 1), headers=MP)
            assert r.status_code == 413 and r.json()["error_code"] == "too_large"
            r = await c.post("/upload/plan", content=chunks(UPLOAD_LIMIT + 1024 * 1024), headers=MP)
            assert r.status_code == 413 and r.json()["error_code"] == "too_large"
            assert srv.counters["too_large_413"] == 2

    asyncio.run(go())

    # 거짓 Content-Length(작다고 적고 11MB를 보냄): ASGI로 직접 흘려 넣어 본다
    sent: list[dict[str, Any]] = []
    body_chunks = [b"z" * (1024 * 1024)] * 11
    it = iter(body_chunks)

    async def receive() -> dict[str, Any]:
        try:
            return {"type": "http.request", "body": next(it), "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    scope = {"type": "http", "method": "POST", "path": "/upload/plan", "headers": [
        (b"content-type", b"multipart/form-data; boundary=XyZ"), (b"content-length", b"100")],
        "client": ("127.0.0.1", 1), "query_string": b"", "http_version": "1.1", "scheme": "http",
        "server": ("t", 80), "root_path": "", "raw_path": b"/upload/plan"}
    mw = serving.ServingMiddleware(lambda *a: None, srv)  # 앱에 닿으면 TypeError → 닿지 않아야 한다
    asyncio.run(mw(scope, receive, send))
    assert sent[0]["status"] == 413 and b"too_large" in sent[1]["body"]


def test_upload_fail_closed_on_content_type_and_encoding(tmp_path):
    """업로드도 앱과 같은 파서로 먼저 본다: multipart가 아니거나(BOM·UTF-16 JSON 포함) 경계가 없으면 본문을 읽지 않고 거절.
    multipart 본문을 BOM·UTF-16으로 바꿔도 속도 제한·동시 상한·바이트 상한은 그대로 걸린다(본문 해석과 무관)."""
    srv, app = upload_app(tmp_path, upload_rate_per_min=3)
    bom_json = (chr(0xFEFF) + json.dumps({"plan_text": plan("u")})).encode("utf-8")
    cases = [
        ({"content-type": "application/json"}, bom_json, 415),
        ({"content-type": "application/json; charset=utf-16"}, json.dumps({"a": 1}).encode("utf-16"), 415),
        ({"content-type": "text/plain"}, b"hello", 415),
        ({}, b"hello", 415),
        ({"content-type": chr(0xFEFF) + "multipart/form-data; boundary=XyZ"}, _multipart(b"x"), 415),
        ({"content-type": "multipart/form-data"}, _multipart(b"x"), 400),
    ]

    async def go() -> None:
        async with raw_client(app) as c:
            for headers, body, code in cases:
                hdrs = {k: v.encode("utf-8") for k, v in headers.items()}  # BOM이 든 헤더도 바이트 그대로
                r = await c.post("/upload/plan", content=body, headers=hdrs)
                assert r.status_code == code, (headers, r.status_code)
                assert r.json()["detail"] in (serving.MESSAGES["upload_type"], serving.MESSAGES["upload_boundary"])
                assert BODY_MARK not in r.text
            assert srv.aux_gate.completed == 0  # 앱까지 간 요청이 없다
            # 인코딩을 바꾼 multipart 본문도 같은 IP 속도 제한(분당 3)에 걸린다
            h = {**MP, "CF-Connecting-IP": "198.51.100.77"}
            bodies = [_multipart(chr(0xFEFF).encode("utf-8") + b"# a"), _multipart("# b".encode("utf-16")),
                      _multipart("# c".encode("utf-32")), _multipart(b"# d")]
            codes = [(await c.post("/upload/plan", content=b, headers=h)).status_code for b in bodies]
            assert codes[3] == 429 and 429 not in codes[:3]

    asyncio.run(go())


def test_upload_per_ip_concurrency_so_slow_files_cannot_hold_every_slot(tmp_path):
    """느린 파일 2건이 한 IP에서 슬롯을 모두 잡는 문제: IP(/64)별 동시 업로드 1건. 다른 IP는 계속 올린다."""
    slow = Slow()
    srv, app = side_app(tmp_path, slow, aux_concurrent=2, aux_queue_max=4, upload_per_ip=1, upload_rate_per_min=100)

    async def go() -> None:
        async with raw_client(app) as c:
            a = {**MP, "CF-Connecting-IP": "2001:db8:5:6::1"}
            t1 = asyncio.create_task(c.post("/upload/plan", content=b"slow-pdf-1", headers=a))
            await wait_until(lambda: srv.aux_gate.active == 1)
            same = {**MP, "CF-Connecting-IP": "2001:db8:5:6::99"}  # 같은 /64
            r = await c.post("/upload/plan", content=b"slow-pdf-2", headers=same)
            assert r.status_code == 429 and r.json()["error_code"] == "busy_ip"
            assert srv.aux_gate.active == 1  # 두 번째 슬롯은 비어 있다
            t2 = asyncio.create_task(c.post("/upload/plan", content=b"other", headers={**MP, "CF-Connecting-IP": "203.0.113.8"}))
            await wait_until(lambda: srv.aux_gate.active == 2)
            slow.release.set()
            assert [x.status_code for x in await asyncio.gather(t1, t2)] == [200, 200]
            assert srv.upload_active == {}  # 끝나면 반납
            assert (await c.post("/upload/plan", content=b"again", headers=same)).status_code == 200

    asyncio.run(go())


def test_upload_timeout_releases_per_ip_count_only_when_work_ends(tmp_path):
    slow = Slow(hold=0.5)
    srv, app = side_app(tmp_path, slow, aux_timeout_s=0.1, upload_per_ip=1)

    async def go() -> None:
        async with raw_client(app) as c:
            h = {**MP, "CF-Connecting-IP": "198.51.100.40"}
            r = await c.post("/upload/plan", content=b"x", headers=h)
            assert r.status_code == 504
            assert srv.upload_active == {serving.ip_key("198.51.100.40"): 1}  # 처리는 아직 돈다
            r2 = await c.post("/upload/plan", content=b"y", headers=h)
            assert r2.status_code == 429 and r2.json()["error_code"] == "busy_ip"
            await wait_until(lambda: srv.upload_active == {})

    asyncio.run(go())


def test_upload_defaults_public_profile(monkeypatch):
    for k in ("NEUMANN_UPLOAD_RATE_PER_MIN", "NEUMANN_UPLOAD_PER_IP", "NEUMANN_MAX_UPLOAD_BYTES"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NEUMANN_PUBLIC", "1")
    c = serving.ServingConfig.from_env()
    assert (c.upload_rate_per_min, c.upload_per_ip, c.max_upload_bytes) == (10, 1, UPLOAD_LIMIT)
    monkeypatch.delenv("NEUMANN_PUBLIC")
    c = serving.ServingConfig.from_env()
    assert (c.upload_rate_per_min, c.upload_per_ip) == (0, 0)
