"""E4-L2d 완료 기준 시험: 가짜 느린 파이프라인(1건 60초)으로 서버를 띄워 작업 API를 잰다.

    python tests/e4/test_jobs_live.py load --port 8136 --out docs/reports/E4-L2d_loadtest.txt   # 동시 5건
    python tests/e4/test_jobs_live.py ui --port 8137 --out docs/reports                         # 화면 1건(Playwright)

- 서버는 ``scripts/serve.py --app tests.e4.test_jobs_live:app``로 띄우고, 끝나면(실패해도) 끈다. 8010은 쓰지 않는다.
- 앱 = main.py 라우트 + 서빙 층(PM 통합 모양, scripts/serve_fake_app.integrate) + 작업 API + 가짜 파이프라인.
  가짜 파이프라인은 실제 분석(bge-m3·OpenAI)을 부르지 않고 6단계를 ``jobs.report_stage``로 알리며 잔다
  (``NEUMANN_FAKE_RUN_S``초, 기본 60). 결과는 공용 fixture(가짜 데이터)에 요청 계획서의 줄을 붙인 것이다.
- pytest는 같은 시나리오(동시 5건, 동시 상한 2)를 시간 배율(60초 → 1.2초)로 줄여 프로세스 안에서 돈다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
if __name__ == "__main__":
    sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from neumann.api import jobs, serving  # noqa: E402

STAGES = ("plan_normalize", "query_axes", "search", "extract_issues", "synthesize_cards", "verify_evidence")
PLAN_FILE = ROOT / "tests" / "fixtures" / "plans" / "plan.md"
OUT: list[str] = []
T0 = time.monotonic()


def plan_text(tag: str) -> str:
    return PLAN_FILE.read_text(encoding="utf-8") + f"\n\n(작업 API 시험 계획서 변형 {tag})\n"


def staged_pipeline(run_s: float) -> Any:
    """6단계를 알리며 run_s초 자는 가짜 파이프라인(스레드에서 돈다)."""
    from scripts.serve_fake_app import fake_result

    def run_premortem(plan_text: str) -> dict[str, Any]:
        for name in STAGES:
            jobs.report_stage(name)
            time.sleep(run_s / len(STAGES))
        return fake_result(plan_text)

    return run_premortem


def build_app(srv: serving.Serving | None = None, run_s: float | None = None, setattr_: Any = setattr,
              config: jobs.JobsConfig | None = None) -> Any:
    from neumann.api import main as api_main
    from scripts.serve_fake_app import integrate

    srv = srv or serving.Serving()
    run_s = float(os.getenv("NEUMANN_FAKE_RUN_S", "60")) if run_s is None else run_s
    app = integrate(srv, staged_pipeline(run_s), setattr_)
    jobs.install(app, load_pipeline=lambda: api_main._load_pipeline(), sample_result=api_main._sample_result,
                 config=config)
    return app


_APP: Any = None


def __getattr__(name: str) -> Any:
    """``app``은 uvicorn이 가져갈 때 만든다(pytest가 이 모듈을 모아도 main을 패치하지 않게)."""
    global _APP
    if name == "app":
        if _APP is None:
            _APP = build_app()
        return _APP
    raise AttributeError(name)


# ───────────────────────── pytest: 같은 시나리오를 시간 배율로 ─────────────────────────


def test_five_concurrent_jobs_scaled(monkeypatch, tmp_path):
    """동시 5건(동시 상한 2): 모든 HTTP 응답이 짧고(프로세스 안 1초 미만), 5건 모두 결과를 받는다.

    실제 60초 → 1.2초(배율 0.02). 동기 방식이었다면 마지막 건의 응답 하나가 분석 3회 분량(약 3.6초 = 실제 180초)을 기다린다.
    """
    run_s = 60 * 0.02
    srv = serving.Serving(serving.ServingConfig(max_concurrent=2, queue_max=20, rate_per_min=6, cache_enabled=False,
                                                avg_run_s=run_s, block_file=tmp_path / "block.flag"))
    app = build_app(srv, run_s, monkeypatch.setattr, jobs.JobsConfig(poll_s=1))

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=30) as c:
            longest = 0.0

            async def timed(coro: Any) -> httpx.Response:
                nonlocal longest
                t = time.monotonic()
                r = await coro
                longest = max(longest, time.monotonic() - t)
                return r

            t_start = time.monotonic()
            posts = await asyncio.gather(*(timed(c.post("/premortem/jobs", json={"plan_text": plan_text(f"S{i}")}))
                                           for i in range(5)))
            assert [r.status_code for r in posts] == [202] * 5
            assert sorted(r.json()["position"] for r in posts) == [0, 0, 1, 2, 3]
            pending = {r.json()["job_id"]: None for r in posts}
            done: dict[str, float] = {}
            positions: dict[str, list[int]] = {k: [] for k in pending}
            while len(done) < 5:
                await asyncio.sleep(0.1)
                for jid in [k for k in pending if k not in done]:
                    j = (await timed(c.get(f"/premortem/jobs/{jid}"))).json()
                    if j["status"] == "queued":
                        positions[jid].append(j["position"])
                    if j["status"] == "done":
                        assert j["result"]["cards"] and j["result"]["plan"]["lines"]
                        done[jid] = time.monotonic() - t_start
                    assert j["status"] != "error", j
                assert time.monotonic() - t_start < 30
            assert longest < 1.0, longest
            for seq in positions.values():
                assert seq == sorted(seq, reverse=True)       # 순번은 줄기만 한다
            assert max(done.values()) >= 2.5 * run_s           # 분석 3회 분량을 기다린 건이 있다(응답은 짧았다)

    asyncio.run(go())


# ───────────────────────── 실제 서버 시험 ─────────────────────────


def say(msg: str = "") -> None:
    line = f"[+{time.monotonic() - T0:7.2f}s] {msg}"
    OUT.append(line)
    print(line, flush=True)


def wait_health(base: str, timeout: float = 90) -> float:
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        try:
            if httpx.get(base + "/health", timeout=3).status_code == 200:
                return time.monotonic() - t
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise SystemExit("서버가 뜨지 않았다")


class Server:
    """serve.py(감시 스크립트)로 가짜 앱을 띄우고 끝나면 끈다."""

    def __init__(self, port: int, run_s: float, **env_extra: str) -> None:
        if port == 8010:
            raise SystemExit("8010은 대표 점검 서버 포트라 쓰지 않는다")
        self.port, self.base = port, f"http://127.0.0.1:{port}"
        self.tmp = Path(tempfile.mkdtemp(prefix="neumann_e4l2d_"))
        self.env = dict(os.environ, PYTHONIOENCODING="utf-8", NEUMANN_WARMUP="0", NEUMANN_FAKE_RUN_S=str(run_s),
                        NEUMANN_AVG_RUN_S=str(run_s), NEUMANN_MAX_CONCURRENT="2", NEUMANN_QUEUE_MAX="20",
                        NEUMANN_RATE_PER_MIN="6", NEUMANN_DAILY_BUDGET="100", NEUMANN_RESULT_CACHE="0",
                        NEUMANN_BUDGET_FILE=str(self.tmp / "budget.json"),
                        NEUMANN_BLOCK_FILE=str(self.tmp / "block.flag"))
        self.env.update(env_extra)
        self.env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT)])
        self.stdout = self.tmp / "server_stdout.log"
        self.proc: subprocess.Popen[bytes] | None = None

    @property
    def block_file(self) -> Path:
        return Path(self.env["NEUMANN_BLOCK_FILE"])

    def __enter__(self) -> Server:
        cmd = [sys.executable, str(ROOT / "scripts" / "serve.py"), "--app", "tests.e4.test_jobs_live:app",
               "--port", str(self.port), "--interval", "2", "--startup-grace", "60",
               "--log-file", str(self.tmp / "serve.log")]
        with self.stdout.open("wb") as so:
            self.proc = subprocess.Popen(cmd, cwd=ROOT, env=self.env, stdout=so, stderr=subprocess.STDOUT,
                                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        say(f"health 정상까지 {wait_health(self.base):.1f}s (serve.py --app tests.e4.test_jobs_live:app "
            f"--port {self.port})")
        return self

    def __exit__(self, *exc: Any) -> None:
        assert self.proc is not None
        self.proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        time.sleep(0.5)
        try:
            httpx.get(self.base + "/health", timeout=2)
            say("경고: 서버가 아직 떠 있다")
        except httpx.HTTPError:
            say(f"서버 종료 확인(포트 {self.port} 닫힘)")

    def log_lines(self) -> list[str]:
        return self.stdout.read_text(encoding="utf-8", errors="replace").splitlines()

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


async def load_scenario(base: str, n: int, run_s: float) -> bool:
    timings: list[tuple[str, float, int]] = []

    async with httpx.AsyncClient(base_url=base, timeout=100) as c:
        async def req(kind: str, coro: Any) -> httpx.Response:
            t = time.monotonic()
            r = await coro
            timings.append((kind, time.monotonic() - t, r.status_code))
            return r

        say(f"== 동시 {n}건을 POST /premortem/jobs로(서로 다른 계획서, 가짜 분석 1건 {run_s:.0f}s, 동시 상한 2)")
        t_start = time.monotonic()
        posts = await asyncio.gather(*(req("POST", c.post("/premortem/jobs", json={"plan_text": plan_text(f"L{i}")}))
                                       for i in range(n)))
        jobs_: dict[str, dict[str, Any]] = {}
        for i, r in enumerate(posts):
            b = r.json()
            say(f"  POST L{i}: code={r.status_code} {timings[i][1]:.3f}s job_id={b.get('job_id', '')[:6]}… "
                f"status={b.get('status')} position={b.get('position')} eta_s={b.get('eta_s')} "
                f"message=\"{b.get('message')}\"")
            if r.status_code == 202:
                jobs_[b["job_id"]] = {"tag": f"L{i}", "last": None, "done_at": None}
        last_q = 0.0
        while any(v["done_at"] is None for v in jobs_.values()):
            await asyncio.sleep(1.5)
            live = [k for k, v in jobs_.items() if v["done_at"] is None]
            rs = await asyncio.gather(*(req("GET", c.get(f"/premortem/jobs/{k}")) for k in live))
            for k, r in zip(live, rs):
                j, v = r.json(), jobs_[k]
                key = (j.get("status"), j.get("position"), j.get("stage"))
                if key != v["last"]:
                    v["last"] = key
                    say(f"  {v['tag']}: {j.get('status'):7s} pos={j.get('position')} stage={j.get('stage')} "
                        f"eta_s={j.get('eta_s')} elapsed_s={j.get('elapsed_s')} message=\"{j.get('message')}\"")
                if j.get("status") in ("done", "error"):
                    v["done_at"] = time.monotonic() - t_start
                    res = j.get("result") or {}
                    v["ok"] = (j["status"] == "done" and bool(res.get("cards")) and bool(res.get("plan", {}).get("lines"))
                               and res.get("_status", {}).get("serving", {}).get("mode") == "job")
                    sv = res.get("_status", {}).get("serving", {})
                    say(f"  {v['tag']}: 결과 받음 status={j['status']} 카드 {len(res.get('cards') or [])}장 "
                        f"계획서 줄 {len((res.get('plan') or {}).get('lines') or [])}줄 대기 {sv.get('waited_s')}s "
                        f"실행 {sv.get('run_s')}s 작업 등록→결과 {v['done_at']:.1f}s")
            if time.monotonic() - last_q > 20:
                last_q = time.monotonic()
                q = (await req("GET", c.get("/queue/status"))).json()
                say(f"  queue active={q['active']} waiting={q['waiting']} avg_run_s={q['avg_run_s']}")
            if time.monotonic() - t_start > 20 * run_s + 60:
                say("시간 초과로 멈춤")
                break
    longest = max(timings, key=lambda x: x[1])
    by_kind = {k: [t for kk, t, _ in timings if kk == k] for k in ("POST", "GET")}
    say(f"== HTTP 응답 {len(timings)}건(POST {len(by_kind['POST'])}, GET {len(by_kind['GET'])}): "
        f"가장 긴 응답 {longest[1]:.3f}s ({longest[0]} code={longest[2]}), POST 최장 {max(by_kind['POST']):.3f}s, "
        f"GET 최장 {max(by_kind['GET']):.3f}s, 100초 이상 {sum(1 for _, t, _ in timings if t >= 100)}건")
    codes: dict[str, int] = {}
    for _, _, code in timings:
        codes[str(code)] = codes.get(str(code), 0) + 1
    say(f"   응답 코드: {json.dumps(codes)}")
    ends = sorted(v["done_at"] or 0 for v in jobs_.values())
    say(f"== 결과 받은 작업 {sum(1 for v in jobs_.values() if v.get('ok'))}/{n}건, 등록→결과 시간 "
        f"{', '.join(f'{x:.1f}s' for x in ends)}")
    say(f"   (동기 방식이었다면 마지막 건은 HTTP 응답 하나가 {ends[-1]:.0f}s 걸려 Cloudflare 약 100초 상한에 끊긴다)")
    ok = (len(jobs_) == n and all(v.get("ok") for v in jobs_.values()) and longest[1] < 100
          and all(code in (200, 202) for _, _, code in timings))
    return ok


def cmd_load(a: argparse.Namespace) -> int:
    say(f"E4-L2d 동시 {a.jobs}건 시험 시작 (포트 {a.port}, 가짜 분석 1건 {a.run_s:.0f}s)")
    srv = Server(a.port, a.run_s)
    ok = False
    try:
        with srv:
            ok = asyncio.run(load_scenario(srv.base, a.jobs, a.run_s))
        say(f"판정: {'PASS' if ok else 'FAIL'}")
        lines = srv.log_lines()
        say("-- 서버 로그(neumann.jobs 작업 완료 줄)")
        for line in [ln for ln in lines if "neumann.jobs" in ln]:
            OUT.append("   " + line)
            print("   " + line)
        reqs = [ln for ln in lines if "neumann.serving" in ln and "path=/premortem/jobs" in ln]
        say(f"-- 서버 로그(neumann.serving, POST /premortem/jobs {len(reqs)}줄)")
        for line in reqs:
            OUT.append("   " + line)
            print("   " + line)
        leaks = [ln for ln in lines if "작업 API 시험 계획서 변형" in ln or "Traceback" in ln]
        say(f"서버 로그 {len(lines)}줄 중 계획서 본문·트레이스가 든 줄: {len(leaks)}")
    finally:
        if a.out:
            Path(a.out).write_text("\n".join(OUT) + "\n", encoding="utf-8")
        srv.cleanup()
    return 0 if ok else 1


# ───────────────────────── 화면(Playwright) ─────────────────────────


def cmd_ui(a: argparse.Namespace) -> int:
    from playwright.sync_api import sync_playwright

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    say(f"E4-L2d 화면 시험 시작 (포트 {a.port}, 가짜 분석 1건 {a.run_s:.0f}s, 동시 상한 1)")
    srv = Server(a.port, a.run_s, NEUMANN_MAX_CONCURRENT="1")
    problems: list[str] = []
    ok = False
    try:
        with srv, sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
            page.on("requestfailed", lambda r: problems.append(f"requestfailed: {r.url}"))
            # 앞선 작업 1건이 슬롯을 쓰는 중 → 화면의 작업은 "대기 1번째"
            r = httpx.post(srv.base + "/premortem/jobs", json={"plan_text": plan_text("UI-blocker")}, timeout=10)
            say(f"앞선 작업(API): code={r.status_code} status={r.json().get('status')} position={r.json().get('position')}")
            page.goto(srv.base + "/", wait_until="networkidle")
            page.wait_for_selector('body[data-view=input][data-ready="1"]')
            page.fill("#ta", plan_text("UI"))
            page.click("#btnStart")
            page.wait_for_function("() => (document.getElementById('jobWait')||{}).textContent?.startsWith('대기 1번째')",
                                   timeout=15000)
            page.evaluate("document.fonts.ready")
            wait_txt = page.text_content("#jobWait")
            page.screenshot(path=str(out / "E4-L2d_1_queued.png"))
            say(f"화면 대기 표시: \"{wait_txt}\" · 상태 {page.text_content('#jobState')} → E4-L2d_1_queued.png")
            page.wait_for_function("() => (document.getElementById('jobState')||{}).textContent === 'running' && "
                                   "document.querySelectorAll('.tl .tn.run').length === 1 && "
                                   "document.querySelectorAll('.tl .tn.done').length >= 3",
                                   timeout=int(a.run_s * 3000))
            run_txt = page.text_content("#jobWait")
            stage_txt = page.text_content(".tl .tn.run .msg")
            page.screenshot(path=str(out / "E4-L2d_2_running.png"))
            say(f"화면 진행 표시: \"{run_txt}\" · 현재 단계 \"{stage_txt}\" → E4-L2d_2_running.png")
            page.wait_for_selector('body[data-view=report][data-ready="1"]', timeout=int(a.run_s * 3000))
            page.wait_for_selector("#s-cards .rc, #noCards")
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(out / "E4-L2d_3_report.png"))
            n_cards = page.locator("#s-cards .rc").count()
            say(f"결과 렌더: 리포트 화면, 위험카드 {n_cards}장 → E4-L2d_3_report.png")
            main_problems = list(problems)
            say(f"정상 흐름(입력→대기→진행→결과) 콘솔 오류·페이지 오류·실패한 요청: {len(main_problems)}건 "
                f"{main_problems[:5]}")
            # 차단 스위치: 서버 사용자 문구가 오류 상자에 textContent로 들어간다
            srv.block_file.write_text("1", encoding="utf-8")
            page.click("#btnNew")
            page.wait_for_selector('body[data-view=input][data-ready="1"]')
            page.fill("#ta", plan_text("UI-blocked"))
            page.click("#btnStart")
            page.wait_for_selector("#jobErr", timeout=10000)
            err_label, err_msg = page.text_content("#jobErrLabel"), page.text_content("#jobErrMsg")
            page.screenshot(path=str(out / "E4-L2d_4_blocked.png"))
            say(f"차단 스위치 문구: [{err_label}] \"{err_msg}\" → E4-L2d_4_blocked.png")
            srv.block_file.unlink()
            # 작업 API가 없는 서버(404) 흉내 → 기존 POST /premortem/view로 폴백
            page.route("**/premortem/jobs", lambda route: route.fulfill(status=404, content_type="application/json",
                                                                         body='{"detail":"Not Found"}'))
            seen: list[str] = []
            page.on("request", lambda rq: seen.append(rq.url.rsplit("/", 2)[-2] + "/" + rq.url.rsplit("/", 1)[-1])
                    if "premortem" in rq.url else None)
            page.click("#btnRetry")
            page.wait_for_selector('body[data-view=report][data-ready="1"]', timeout=int(a.run_s * 3000))
            say(f"작업 API 404 → 폴백 요청: {seen} → 리포트 렌더 {page.locator('#s-cards .rc').count()}장")
            browser.close()
            # 일부러 낸 503(차단)·404(폴백)는 브라우저가 "Failed to load resource"로 적는다. 그 밖의 오류는 없어야 한다.
            extra = [x for x in problems[len(main_problems):]
                     if not re.search(r"Failed to load resource: the server responded with a status of (503|404)", x)]
            say(f"차단·폴백 단계 콘솔 기록 {len(problems) - len(main_problems)}건(503·404 자원 로드 알림), "
                f"그 밖의 오류 {len(extra)}건 {extra[:5]}")
            ok = (wait_txt or "").startswith("대기 1번째 · 약 ") and n_cards > 0 and "premortem/view" in seen \
                and "새 분석을 잠시 멈췄습니다" in (err_msg or "") and not main_problems and not extra
        say(f"판정: {'PASS' if ok else 'FAIL'}")
    finally:
        if a.log:
            Path(a.log).write_text("\n".join(OUT) + "\n", encoding="utf-8")
        srv.cleanup()
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    lo = sub.add_parser("load")
    lo.add_argument("--port", type=int, default=8136)
    lo.add_argument("--run-s", type=float, default=60.0)
    lo.add_argument("--jobs", type=int, default=5)
    lo.add_argument("--out", default=None)
    ui = sub.add_parser("ui")
    ui.add_argument("--port", type=int, default=8137)
    ui.add_argument("--run-s", type=float, default=12.0)
    ui.add_argument("--out", default=str(ROOT / "docs" / "reports"))
    ui.add_argument("--log", default=None)
    a = ap.parse_args(argv)
    return cmd_load(a) if a.cmd == "load" else cmd_ui(a)


if __name__ == "__main__":
    sys.exit(main())
