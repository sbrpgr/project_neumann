"""E4-L2d 재작업 검사: BOM 본문·글자 상한(작업 핸들러 직접), 작업 저장소 고갈 방지(IP별 보관 상한·IP별 속도 제한·
다른 IP 결과를 밀어내지 않음), 긴 토큰 422(이벤트 루프 멈춤 없음, 정상 계획서는 통과), 폴링 속도 제한, 접근 로그의
job_id 가리기, 다중 사용자(서로 다른 IP 10개: 4건 실행·6건 대기·전부 결과), 동기 경로의 작은 대기열.

실제 파이프라인·bge-m3·OpenAI를 부르지 않는다(가짜 파이프라인).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from neumann.api import jobs, serving
from neumann.api import main as api_main
from scripts.serve_fake_app import fake_result, integrate
from tests.e4.test_jobs import BODY_MARK, Gated, client, plan, poll_done, slow, wait_until

ROOT = Path(__file__).resolve().parents[2]
JSON_H = {"content-type": "application/json"}


def make(tmp_path: Path, monkeypatch: Any, fn: Any, jcfg: jobs.JobsConfig, **cfg: Any) -> tuple[Any, Any, Any]:
    base: dict[str, Any] = dict(max_concurrent=2, queue_max=30, rate_per_min=0, cache_enabled=False,
                                cache_dir=tmp_path / "results", request_timeout_s=30.0, avg_run_s=1.0,
                                block_file=tmp_path / "block.flag")
    base.update(cfg)
    srv = serving.Serving(serving.ServingConfig(**base))
    app = integrate(srv, fn, monkeypatch.setattr)
    store = jobs.install(app, load_pipeline=lambda: api_main._load_pipeline(), sample_result=api_main._sample_result,
                         config=jcfg)
    return srv, app, store


def ip(n: int) -> dict[str, str]:
    """다른 사용자 흉내: 로컬 peer(터널)에서 온 CF-Connecting-IP는 믿는다."""
    return {"CF-Connecting-IP": f"198.51.100.{n}"}


def encodings(obj: dict[str, Any]) -> dict[str, bytes]:
    raw = json.dumps(obj, ensure_ascii=False)
    return {"utf8-bom": b"\xef\xbb\xbf" + raw.encode("utf-8"), "utf16": raw.encode("utf-16"),
            "utf16-le": raw.encode("utf-16-le"), "utf32": raw.encode("utf-32")}


# ───────────────────────── 1. BOM·글자 상한 ─────────────────────────


def test_bom_and_utf16_bodies_hit_gates_on_jobs_and_view(tmp_path, monkeypatch):
    fn = slow(0.02)
    srv, app, store = make(tmp_path, monkeypatch, fn, jobs.JobsConfig(per_ip=0, rate_per_min=0, poll_per_min=0),
                           max_plan_chars=2000)

    async def go() -> None:
        async with client(app) as c:
            for name, raw in encodings({"plan_text": plan("bom-ok")}).items():  # 정상: 앱과 같이 읽는다
                r = await c.post("/premortem/jobs", content=raw, headers=JSON_H)
                assert r.status_code == 202, name
                assert (await poll_done(c, r.json()["job_id"]))["status"] == "done"
                v = await c.post("/premortem/view", content=raw, headers=JSON_H)
                assert v.status_code == 200, name
            n_jobs, n_calls = len(store), fn.calls["n"]
            srv.config.block_file.write_text("1", encoding="utf-8")   # 차단 스위치
            for name, raw in encodings({"plan_text": plan("bom-block")}).items():
                for path in ("/premortem/jobs", "/premortem/view"):
                    r = await c.post(path, content=raw, headers=JSON_H)
                    assert r.status_code == 503 and r.json()["error_code"] == "blocked", (name, path)
            srv.config.block_file.unlink()
            for name, raw in encodings({"plan_text": plan("bom-long", "가 " * 1500)}).items():  # 글자 상한
                for path in ("/premortem/jobs", "/premortem/view"):
                    r = await c.post(path, content=raw, headers=JSON_H)
                    assert r.status_code == 413 and r.json()["error_code"] == "too_large", (name, path)
            assert len(store) == n_jobs and fn.calls["n"] == n_calls   # 거절된 요청은 작업·분석을 만들지 않았다

    asyncio.run(go())


def test_create_job_checks_char_limit_itself(tmp_path, monkeypatch):
    """미들웨어가 어떤 이유로 글자 수를 못 봤어도 작업 핸들러가 직접 413으로 거절한다(12만 자가 202였던 결함)."""
    srv, app, store = make(tmp_path, monkeypatch, slow(0.02), jobs.JobsConfig(per_ip=0, rate_per_min=0))
    ctx = serving.RequestCtx(ticket="tk_direct", plan_id="p" * 64, chars=120_000)
    r = store.submit(jobs.JobRequest(plan_text="가나 " * 40_000), ctx)
    assert r.status_code == 413 and json.loads(r.body)["error_code"] == "too_large" and len(store) == 0
    r = store.submit(jobs.JobRequest(plan_text="x" * (srv.config.max_token_chars + 1)), ctx)
    assert r.status_code == 422 and json.loads(r.body)["error_code"] == "long_token" and len(store) == 0


# ───────────────────────── 2. 저장소 고갈 방지 ─────────────────────────


def test_join_flood_from_one_ip_cannot_fill_store_or_block_others(tmp_path, monkeypatch):
    fake = Gated()
    srv, app, store = make(tmp_path, monkeypatch, fake, jobs.JobsConfig(per_ip=3, rate_per_min=6, max_jobs=200))

    async def go() -> None:
        async with client(app) as c:
            codes: dict[int, int] = {}
            t0 = time.monotonic()
            for _ in range(230):   # 같은 계획서(합류)를 한 IP에서 230번
                r = await c.post("/premortem/jobs", json={"plan_text": plan("flood")}, headers=ip(66))
                codes[r.status_code] = codes.get(r.status_code, 0) + 1
            # 합류 작업은 IP별 보관 수에서 빠지고(재작업 3) IP별 작업 POST 속도 제한(분당 6)이 막는다
            assert codes.get(202) == 6 and codes.get(429) == 224, codes
            assert len(store) == 6 and fake.calls == 1                   # 분석은 1회(합류)
            assert sum(1 for j in store._jobs.values() if j.shared) == 5
            assert time.monotonic() - t0 < 10
            r = await c.post("/premortem/jobs", json={"plan_text": plan("victim")}, headers=ip(7))
            assert r.status_code == 202                                  # 다른 IP의 새 분석은 받는다
            fake.release_all()
            assert (await poll_done(c, r.json()["job_id"]))["status"] == "done"
            assert store.counters["per_ip_429"] == 0 and store.counters["rate_429"] >= 1   # 합류는 속도 제한이 막는다

    asyncio.run(go())


def test_cached_flood_does_not_evict_other_ip_results(tmp_path, monkeypatch):
    srv, app, store = make(tmp_path, monkeypatch, slow(0.02), jobs.JobsConfig(per_ip=3, rate_per_min=6, max_jobs=10),
                           cache_enabled=True)

    async def go() -> None:
        async with client(app) as c:
            victim = (await c.post("/premortem/jobs", json={"plan_text": plan("mine")}, headers=ip(8))).json()["job_id"]
            assert (await poll_done(c, victim))["status"] == "done"
            first = await c.post("/premortem/jobs", json={"plan_text": plan("hot")}, headers=ip(99))
            await poll_done(c, first.json()["job_id"])                    # 이제 캐시에 있다
            codes: dict[int, int] = {}
            for _ in range(300):
                r = await c.post("/premortem/jobs", json={"plan_text": plan("hot")}, headers=ip(99))
                codes[r.status_code] = codes.get(r.status_code, 0) + 1
            assert codes.get(202, 0) <= 5 and codes.get(429, 0) >= 295, codes   # 캐시 적중 POST도 IP별 분당 6건
            g = await c.get(f"/premortem/jobs/{victim}", headers=ip(8))
            assert g.status_code == 200 and g.json()["status"] == "done"     # 남의 완료 결과는 그대로
            mine = [j for j in store._jobs.values() if j.ipk == "198.51.100.99"]
            assert len(mine) <= 6 and all(store.ttl_for(j) == 60 for j in mine if j.shared)

    asyncio.run(go())


def test_full_store_refuses_requester_and_keeps_other_ips_results(tmp_path, monkeypatch):
    srv, app, store = make(tmp_path, monkeypatch, slow(0.01), jobs.JobsConfig(per_ip=0, rate_per_min=0, max_jobs=4))

    async def go() -> None:
        async with client(app) as c:
            ids = {}
            for who, n in (("a", 1), ("a", 1), ("b", 2), ("b", 2)):
                r = await c.post("/premortem/jobs", json={"plan_text": plan(f"{who}{len(ids)}")}, headers=ip(n))
                ids[r.json()["job_id"]] = who
                await poll_done(c, r.json()["job_id"])
            r = await c.post("/premortem/jobs", json={"plan_text": plan("c")}, headers=ip(3))
            assert r.status_code == 503 and r.json()["error_code"] == "busy"          # 요청한 쪽(C)을 거절
            assert "보관 중인 분석 작업이 많습니다" in r.json()["message"]
            for jid in ids:
                assert (await c.get(f"/premortem/jobs/{jid}")).status_code == 200      # A·B 결과는 그대로
            r = await c.post("/premortem/jobs", json={"plan_text": plan("a-new")}, headers=ip(1))
            assert r.status_code == 202                                              # A는 자기 끝난 작업을 밀어낸다
            alive = [jid for jid in ids if (await c.get(f"/premortem/jobs/{jid}")).status_code == 200]
            assert sorted(ids[j] for j in alive) == ["a", "b", "b"]

    asyncio.run(go())


# ───────────────────────── 3. 긴 토큰 ─────────────────────────


def test_long_single_token_is_422_at_once_and_health_stays_fast(tmp_path, monkeypatch):
    fn = slow(0.02)
    srv, app, store = make(tmp_path, monkeypatch, fn, jobs.JobsConfig(per_ip=0, rate_per_min=0),
                           max_plan_chars=300_000)

    async def go() -> None:
        async with client(app) as c:
            token = "a" * 200_000   # '@' 없는 20만 자 한 토큰(이메일 정규식 O(n²)이면 수십 초)
            health_ms: list[float] = []
            assert (await c.get("/health")).status_code == 200   # 첫 호출의 모듈 import 시간은 빼고 잰다

            async def health_loop() -> None:
                for _ in range(10):
                    t = time.monotonic()
                    assert (await c.get("/health")).status_code == 200
                    health_ms.append((time.monotonic() - t) * 1000)
                    await asyncio.sleep(0.01)

            async def attack(path: str) -> httpx.Response:
                t = time.monotonic()
                r = await c.post(path, json={"plan_text": f"# 계획서\n{token}\n"})
                assert time.monotonic() - t < 1.0, path
                return r

            rs = await asyncio.gather(attack("/premortem/jobs"), attack("/premortem/view"), attack("/premortem"),
                                      health_loop())
            for r in rs[:3]:
                assert r.status_code == 422 and r.json()["error_code"] == "long_token"
                assert "띄어쓰기 없이" in r.json()["message"] and "a" * 100 not in r.text
            assert max(health_ms) < 500, health_ms
            assert len(store) == 0 and fn.calls["n"] == 0

    asyncio.run(go())


def test_normal_plans_templates_and_long_urls_pass_token_check(tmp_path, monkeypatch):
    fn = slow(0.01)
    srv, app, store = make(tmp_path, monkeypatch, fn, jobs.JobsConfig(per_ip=0, rate_per_min=0))
    texts = {p.name: p.read_text(encoding="utf-8") for p in sorted((ROOT / "tests/fixtures/plans").glob("plan*.md"))}
    texts |= {p.name: p.read_text(encoding="utf-8") for p in sorted((ROOT / "src/neumann/api/templates").glob("*.md"))}
    assert len(texts) == 8   # 정상 예시 3건 + 템플릿 5종
    for n in (2_000, 5_000, 10_000):   # 2천~1만 자 URL 한 줄
        url = "https://example.org/data?" + "&".join(f"k{i}=v{i}" for i in range(n))[: n - 25]
        texts[f"url{n}"] = f"{plan('url')}\n데이터 위치: {url}\n"
        assert serving.longest_token(texts[f"url{n}"]) >= n - 5
    texts["base64"] = plan("b64") + "\n그림: data:image/png;base64," + "QUJD" * 4000 + "\n"   # 1.6만 자 한 줄

    async def go() -> None:
        async with client(app) as c:
            for name, text in texts.items():
                assert serving.longest_token(text) <= srv.config.max_token_chars, name
                r = await c.post("/premortem/jobs", json={"plan_text": text})
                assert r.status_code == 202, (name, r.text[:200])
                assert (await poll_done(c, r.json()["job_id"]))["status"] == "done", name

    asyncio.run(go())
    assert serving.ServingConfig().max_token_chars == 20_000


# ───────────────────────── 4. 폴링 속도 제한·접근 로그 ─────────────────────────


def test_poll_rate_limit_per_ip(tmp_path, monkeypatch):
    srv, app, store = make(tmp_path, monkeypatch, slow(0.01), jobs.JobsConfig(per_ip=0, rate_per_min=0, poll_per_min=5))

    async def go() -> None:
        async with client(app) as c:
            jid = (await c.post("/premortem/jobs", json={"plan_text": plan("poll")})).json()["job_id"]
            codes = [(await c.get(f"/premortem/jobs/{jid}", headers=ip(5))).status_code for _ in range(7)]
            assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
            r = await c.get(f"/premortem/jobs/{jid}", headers=ip(5))
            assert r.json()["error_code"] == "rate_limited" and "retry-after" in r.headers and "result" not in r.json()
            assert (await c.get(f"/premortem/jobs/{jid}", headers=ip(6))).status_code == 200   # 다른 IP는 따로

    asyncio.run(go())


def test_access_log_masks_job_id():
    jid = "AbCdEf" + "x" * 26
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:5000", "GET", f"/premortem/jobs/{jid}", "1.1", 200), None)
    serving.RedactingFilter().filter(rec)
    msg = rec.getMessage()
    assert jid not in msg and "/premortem/jobs/AbCdEf…" in msg
    assert isinstance(rec.args, tuple) and len(rec.args) == 5   # 접근 로그 인자 구조 유지
    assert serving.mask_job_paths("POST /premortem/jobs HTTP/1.1") == "POST /premortem/jobs HTTP/1.1"


# ───────────────────────── 5. 다중 사용자 ─────────────────────────


def test_ten_users_four_run_six_wait_all_get_results_and_no_ip_monopoly(tmp_path, monkeypatch):
    fake = Gated()
    srv, app, store = make(tmp_path, monkeypatch, fake, jobs.JobsConfig(per_ip=3, rate_per_min=6, poll_per_min=600),
                           max_concurrent=4, queue_max=30, sync_queue_max=4, rate_per_min=6, avg_run_s=60.0)

    async def go() -> None:
        async with client(app) as c:
            rs = await asyncio.gather(*(c.post("/premortem/jobs", json={"plan_text": plan(f"u{i}")}, headers=ip(10 + i))
                                        for i in range(10)))
            assert [r.status_code for r in rs] == [202] * 10
            await wait_until(lambda: fake.calls == 4)
            assert (srv.gate.active, srv.gate.waiting) == (4, 6)
            st = [(await c.get(f"/premortem/jobs/{r.json()['job_id']}", headers=ip(10 + i))).json()
                  for i, r in enumerate(rs)]
            assert sorted(s["status"] for s in st) == ["queued"] * 6 + ["running"] * 4
            q = sorted((s["position"], s["eta_s"]) for s in st if s["status"] == "queued")
            assert [p for p, _ in q] == [1, 2, 3, 4, 5, 6]
            # 예상 시간이 동시 수를 반영: 앞 4명은 첫 슬롯이 빌 때(약 60초), 5·6번째는 두 바퀴(약 120초)
            assert all(50 <= e <= 61 for _, e in q[:4]) and all(110 <= e <= 121 for _, e in q[4:]), q
            assert all(s["message"].startswith(f"대기 {s['position']}번째 · 약 ") for s in st if s["status"] == "queued")
            # 한 IP가 독점하지 못한다: 같은 IP에서 10건 → 보관 3건까지(이미 1건) 받고 나머지 429
            mono = [await c.post("/premortem/jobs", json={"plan_text": plan(f"m{i}")}, headers=ip(10)) for i in range(10)]
            assert [r.status_code for r in mono].count(202) == 2 and all(r.status_code == 429 for r in mono[2:])
            # 동기 경로는 대기 4 이상이면 바로 503(응답 하나가 터널 상한을 넘지 않게), 작업 경로는 계속 받는다
            v = await c.post("/premortem/view", json={"plan_text": plan("sync")}, headers=ip(40))
            assert v.status_code == 503 and v.json()["error_code"] == "busy"
            j = await c.post("/premortem/jobs", json={"plan_text": plan("late")}, headers=ip(41))
            assert j.status_code == 202 and j.json()["position"] == 9
            fake.release_all()
            ids = [r.json()["job_id"] for r in rs] + [j.json()["job_id"]] + [r.json()["job_id"] for r in mono[:2]]
            done = [await poll_done(c, x) for x in ids]
            assert [d["status"] for d in done] == ["done"] * len(ids)
            assert all(d["result"]["cards"] for d in done)

    asyncio.run(go())


# ───────────────────────── 재작업 2(E4-L2c 재검증 대응) ─────────────────────────


def test_upload_4xx_body_is_the_apps_own_shape(tmp_path, monkeypatch):
    """서빙 층을 붙여도 업로드 4xx 본문은 앱 모양 그대로(요청 번호는 헤더). E4-L1f 화면 계약({"detail": 문구})."""
    from neumann.api.upload import HWP_MESSAGE
    from tests.e4.test_upload import HWP5_BYTES

    srv, app, store = make(tmp_path, monkeypatch, slow(0.01), jobs.JobsConfig(per_ip=0, rate_per_min=0))

    async def go() -> None:
        async with client(app) as c:
            r = await c.post("/upload/plan", files={"file": ("계획서.hwp", HWP5_BYTES)})
            assert r.status_code == 415 and r.json() == {"detail": HWP_MESSAGE}
            assert r.headers.get("x-neumann-ticket")
            j = await c.post("/premortem/jobs", json={"plan_text": " "})
            assert j.status_code == 422 and "request_id" in j.json()   # 분석 경로 4xx는 요청 번호를 본문에도

    asyncio.run(go())


def test_preparse_rate_limit_runs_before_body_parse_and_hash(tmp_path, monkeypatch):
    calls = {"n": 0}
    real = serving.plan_key

    def counting(text: str) -> str:
        calls["n"] += 1
        return real(text)

    monkeypatch.setattr(serving, "plan_key", counting)
    srv, app, store = make(tmp_path, monkeypatch, slow(0.01), jobs.JobsConfig(per_ip=0, rate_per_min=0),
                           preparse_per_min=3)

    async def go() -> None:
        async with client(app) as c:
            codes = [(await c.post("/premortem/jobs", json={"plan_text": plan(f"pp{i}")}, headers=ip(77))).status_code
                     for i in range(3)]
            assert codes == [202, 202, 202] and calls["n"] == 3
            r = await c.post("/premortem/view", content=b"{not json" + b"a" * 40_000, headers={**JSON_H, **ip(77)})
            assert r.status_code == 429 and r.json()["error_code"] == "rate_limited" and calls["n"] == 3
            assert (await c.post("/premortem/jobs", json={"plan_text": plan("other")}, headers=ip(78))).status_code == 202

    asyncio.run(go())
    assert serving.ServingConfig().preparse_per_min == 0   # 개발 기본은 끔, 공개 60(from_env)


def test_serve_py_survives_cp949_redirected_stdout(tmp_path):
    """한국어 Windows에서 출력을 파일로 돌려도 첫 로그 줄('—')에서 죽지 않는다(serve.py --public --dry-run)."""
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONIOENCODING", "PYTHONUTF8"}}
    env.update(NEUMANN_LLM_PROVIDER="mock", PYTHONUTF8="0", PYTHONIOENCODING="cp949")
    out = tmp_path / "serve_out.txt"
    with out.open("wb") as fh:
        rc = subprocess.run([sys.executable, str(ROOT / "scripts" / "serve.py"), "--public", "--dry-run"],
                            stdout=fh, stderr=subprocess.STDOUT, env=env, cwd=ROOT, timeout=60).returncode
    text = out.read_bytes().decode("utf-8", errors="replace")
    assert rc == 2, text   # mock provider → 공개 기동 거부(정상 종료 코드 2), UnicodeEncodeError(1) 아님
    assert "UnicodeEncodeError" not in text and "provider" in text


# ───────────────────────── 재작업 3(재검증 권장 2·4) ─────────────────────────


def test_shared_jobs_short_ttl_and_not_counted_per_ip(tmp_path, monkeypatch):
    """같은 공인 IP(행사장 와이파이) 5명이 같은 예시를 동시에 눌러도 모두 받는다(합류는 비용 0).
    합류·캐시 작업은 60초만 보관, 새 분석 작업은 15분."""
    fake = Gated()
    srv, app, store = make(tmp_path, monkeypatch, fake, jobs.JobsConfig(per_ip=3, rate_per_min=30, max_jobs=500))
    now = {"t": 5000.0}
    store.clock = lambda: now["t"]
    assert (jobs.JobsConfig().max_jobs, jobs.JobsConfig().shared_ttl_s) == (500, 60.0)

    async def go() -> None:
        async with client(app) as c:
            rs = await asyncio.gather(*(c.post("/premortem/jobs", json={"plan_text": plan("demo")}, headers=ip(50))
                                        for _ in range(5)))
            assert [r.status_code for r in rs] == [202] * 5 and fake.calls <= 1
            # 새 분석은 IP별 3건: 합류 4건이 있어도 새 분석 2건 더(첫 건 포함 3건)
            extra = [await c.post("/premortem/jobs", json={"plan_text": plan(f"new{i}")}, headers=ip(50))
                     for i in range(3)]
            assert [r.status_code for r in extra] == [202, 202, 429]
            fake.release_all()
            ids = [r.json()["job_id"] for r in rs + extra[:2]]
            done = [await poll_done(c, x) for x in ids]
            shared = [j for j in store._jobs.values() if j.shared]
            assert len(shared) == 4 and all(d["status"] == "done" for d in done)
            assert sorted(d["expires_in_s"] for d in done) == [60.0] * 4 + [900.0] * 3
            now["t"] += 61
            alive = [(await c.get(f"/premortem/jobs/{x}", headers=ip(50))).status_code for x in ids]
            assert alive.count(404) == 4 and alive.count(200) == 3   # 합류 작업만 사라졌다

    asyncio.run(go())


def test_full_store_shows_accepting_false_in_queue_status(tmp_path, monkeypatch):
    srv, app, store = make(tmp_path, monkeypatch, slow(0.01), jobs.JobsConfig(per_ip=0, rate_per_min=0, max_jobs=2,
                                                                              ttl_s=30))
    now = {"t": 100.0}
    store.clock = lambda: now["t"]

    async def go() -> None:
        async with client(app) as c:
            assert (await c.get("/queue/status")).json()["accepting"] is True
            for i in range(2):
                await poll_done(c, (await c.post("/premortem/jobs", json={"plan_text": plan(f"f{i}")},
                                                 headers=ip(60 + i))).json()["job_id"])
            assert (await c.get("/queue/status")).json()["accepting"] is False   # 저장소 가득
            r = await c.post("/premortem/jobs", json={"plan_text": plan("f9")}, headers=ip(69))
            assert r.status_code == 503
            now["t"] += 31
            assert (await c.get("/queue/status")).json()["accepting"] is True    # TTL 지나 비었다

    asyncio.run(go())


def test_access_log_masks_query_and_path_variants_idempotently():
    jid = "Zx9_-Q" + "k" * 26
    paths = [f"/premortem/jobs/{jid}?x=1", f"/PREMORTEM/JOBS/{jid}", f"/premortem//jobs//{jid}",
             f"/premortem/jobs%2F{jid}", f"/queue/status?ticket={jid}", f"/premortem/jobs?job={jid}",
             f"/x?a=1&job_id={jid}", f"/anything/{jid}/more"]
    f = serving.RedactingFilter()
    for path in paths:
        rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                ("127.0.0.1:5000", "GET", path, "1.1", 200), None)
        f.filter(rec)
        f.filter(rec)   # 로거와 핸들러에 두 번 걸려도 같은 결과
        msg = rec.getMessage()
        assert jid not in msg and jid[6:] not in msg, msg
        assert "Zx9_-Q…" in msg and "……" not in msg, msg
    # 앱 로그(접근 로그 아님)도 경로·쿼리 모양은 가린다
    assert jid not in serving.mask_job_paths(f"GET /Premortem/Jobs/{jid}")
    assert serving.mask_job_paths("plan_id=3d35460def76 chars=669") == "plan_id=3d35460def76 chars=669"


def test_on_stage_running_and_end_reports_with_parallel_stages(tmp_path, monkeypatch):
    """E3-L1y 모양의 on_stage(name, state, seconds): 시작("running")만 현재 단계가 되고, 끝 보고는 완료 목록에만.
    병렬 구간(예상 심사평 ∥ 체크리스트→2차 검증)에서 끝난 단계가 현재 단계로 남지 않는다."""
    import threading

    steps = [("fitness", "running", 0.0), ("fitness", "ok", 0.4), ("expected_review", "running", 0.0),
             ("checklist", "running", 0.0), ("checklist", "ok", 1.2), ("semantic_validate", "running", 0.0),
             ("semantic_validate", "ok", 0.8), ("expected_review", "degraded", 2.5)]
    go_next = [threading.Event() for _ in steps]
    hold = threading.Event()   # 마지막 보고 뒤 결과를 내기 전에 멈춰 둔다(끝난 뒤 상태를 재려고)
    reached = {"i": -1}

    def run_premortem(plan_text: str, on_stage: Any = None) -> dict[str, Any]:
        for i, (name, state, secs) in enumerate(steps):
            go_next[i].wait(10)
            on_stage(name, state, secs)
            reached["i"] = i
        hold.wait(10)
        return fake_result(plan_text)

    srv, app, store = make(tmp_path, monkeypatch, run_premortem, jobs.JobsConfig(per_ip=0, rate_per_min=0))
    expect_current = ["fitness", "running", "expected_review", "checklist", "expected_review", "semantic_validate",
                      "expected_review", "running"]

    async def go() -> None:
        async with client(app) as c:
            jid = (await c.post("/premortem/jobs", json={"plan_text": plan("stages")})).json()["job_id"]
            seen = []
            for i in range(len(steps)):
                go_next[i].set()
                await wait_until(lambda i=i: reached["i"] >= i)
                j = (await c.get(f"/premortem/jobs/{jid}")).json()
                seen.append(j["stage"])
                if j["stage"] in jobs.STAGE_LABELS and j["stage"] not in ("running",):
                    assert j["stage_label"] == jobs.STAGE_LABELS[j["stage"]] and j["stage_label"] in j["message"]
            assert seen == expect_current, seen
            last = (await c.get(f"/premortem/jobs/{jid}")).json()
            assert last["status"] == "running" and last["message"].startswith("분석 중 · 약 ")
            assert [(d["stage"], d["status"]) for d in last["stages_done"]] == [
                ("fitness", "ok"), ("checklist", "ok"), ("semantic_validate", "ok"), ("expected_review", "degraded")]
            assert last["stages_done"][1]["label"] == "체크리스트" and last["stages_done"][1]["elapsed_s"] == 1.2
            hold.set()
            assert (await poll_done(c, jid))["status"] == "done"
            assert {"fitness": "적합성 판정", "expected_review": "예상 심사평", "checklist": "체크리스트",
                    "semantic_validate": "2차 검증"}.items() <= jobs.STAGE_LABELS.items()

    asyncio.run(go())


# ───────────────────────── 재작업 4: 퍼센트 인코딩된 job_id(접근 로그) ─────────────────────────


def _enc(s: str, which: Any) -> str:
    return "".join(f"%{ord(c):02X}" if which(i) else c for i, c in enumerate(s))


def _exposed(text: str, jid: str) -> bool:
    """원래 id·푼(unquote) id 어느 쪽이든 12자 이상 조각이 보이면 누출."""
    import urllib.parse as up

    views = (text, up.unquote(text), up.unquote(up.unquote(text)))
    return any(jid[s:s + 12] in v for v in views for s in range(len(jid) - 11))


class _AccessLogCapture:
    """실제 uvicorn 접근 로그 경로: uvicorn.access 로거 + uvicorn AccessFormatter + 서빙 층 로그 필터(로거·핸들러 둘 다)."""

    def __enter__(self) -> _AccessLogCapture:
        import io

        from uvicorn.logging import AccessFormatter

        self.buf = io.StringIO()
        self.lg = logging.getLogger("uvicorn.access")
        self.saved = (self.lg.level, self.lg.propagate, list(self.lg.handlers), list(self.lg.filters))
        self.h = logging.StreamHandler(self.buf)
        self.h.setFormatter(AccessFormatter('%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                                            use_colors=False))
        self.lg.handlers = [self.h]
        self.lg.setLevel(logging.INFO)
        self.lg.propagate = False
        serving.install_log_filter()   # 로거와 핸들러에 모두 붙는다(두 번 걸림)
        return self

    def log(self, full_path: str) -> str:
        start = len(self.buf.getvalue())
        # uvicorn h11/httptools 프로토콜이 부르는 것과 같은 모양
        self.lg.info('%s - "%s %s HTTP/%s" %d', "198.51.100.7:50000", "GET", full_path, "1.1", 200)
        return self.buf.getvalue()[start:]

    def __exit__(self, *exc: Any) -> None:
        level, prop, handlers, filters = self.saved
        self.lg.handlers, self.lg.filters = handlers, filters
        self.lg.setLevel(level)
        self.lg.propagate = prop


def test_access_log_masks_percent_encoded_job_ids_through_uvicorn_formatter():
    import secrets

    with _AccessLogCapture() as cap:
        for _ in range(5):
            jid = secrets.token_urlsafe(24)
            cases = {
                "q-job-first": f"/health?job={_enc(jid, lambda i: i == 0)}",
                "q-job-mid": f"/health?job={_enc(jid, lambda i: i in (0, 15))}",
                "q-job-all": f"/health?job={_enc(jid, lambda i: True)}",
                "q-x-plain": f"/health?x={jid}",
                "q-x-%2D": f"/health?x={jid[:10]}%2D{jid[11:]}",
                "q-x-all": f"/health?x={_enc(jid, lambda i: True)}",
                "q-other-key-one": f"/templates?next={_enc(jid, lambda i: i == 20)}",
                "q-encoded-key": f"/x?%6Aob={_enc(jid, lambda i: i % 3 == 0)}",
                "q-path-in-query": f"/x?next=%2Fpremortem%2Fjobs%2F{_enc(jid, lambda i: i == 1)}",
                "path": f"/premortem/jobs/{jid}",
                "path-%2F": f"/premortem%2Fjobs%2F{jid}",
                "path-then-query": f"/premortem/jobs/{jid}?job={_enc(jid, lambda i: i < 3)}",
            }
            for name, path in cases.items():
                line = cap.log(path)
                assert '"GET ' in line and "HTTP/1.1" in line and "200" in line, line   # 접근 로그 형식 그대로
                assert not _exposed(line, jid), (name, line)
                assert "…" in line, (name, line)
        # 정상 경로는 그대로(요청 번호·템플릿 이름 등 짧은 토큰)
        assert "/templates/physics_pde_climate" in cap.log("/templates/physics_pde_climate")
        assert "ticket=cb07f6ed523e4785" not in cap.log("/queue/status?ticket=cb07f6ed523e4785")   # 쿼리 ticket은 가림


def test_access_log_mask_fuzz_300_no_leak_and_idempotent():
    import random
    import secrets

    rnd = random.Random(20260930)
    shapes = ["/x?job={}", "/x?x={}", "/premortem/jobs?job_id={}", "/premortem/jobs/{}", "/x?a=1&ticket={}", "/x/{}",
              "/x?next={}", "/x?a=%41&b={}&c=1", "/premortem%2Fjobs%2F{}", "/x?q=%22{}%22"]
    leaks = []
    with _AccessLogCapture() as cap:
        for n in range(300):
            jid = secrets.token_urlsafe(24)
            pr = rnd.choice((0.0, 0.03, 0.1, 0.3, 0.6, 1.0))
            path = rnd.choice(shapes).format(_enc(jid, lambda i: rnd.random() < pr))
            line = cap.log(path)
            if _exposed(line, jid):
                leaks.append((path, line))
            once = serving.mask_job_paths(path, access=True)
            assert serving.mask_job_paths(once, access=True) == once   # 두 번 걸어도 같다
    assert leaks == [], leaks[:3]
