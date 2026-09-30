"""E4 화면 검증: 서버를 띄우고 Playwright(1440×900)로 입력 → 리포트를 찍는다.

    python tests/e4/ui_shots.py [--plan PATH] [--port 8000] [--out docs/reports] [--prefix E4-L0]

- uvicorn을 하위 프로세스로 띄우고, 끝나면(실패해도) 반드시 종료한다.
- 렌더 완료 DOM 조건을 기다린 뒤 찍는다:
  입력 = ``body[data-view=input][data-ready="1"]`` + 헤더 상태 갱신 + ``document.fonts.ready``
  리포트 = ``body[data-view=report][data-ready="1"]`` + (``#s-cards .rc`` 또는 ``#noCards``) + ``document.fonts.ready``
- 콘솔 오류·페이지 오류·실패한 요청·외부 도메인 요청을 기록한다. 하나라도 있으면 exit 1.
- pytest가 모으지 않는다(파일 이름이 test_로 시작하지 않음). verify와 별개로 수동 실행한다.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from neumann.api.view import build_ui_view  # noqa: E402

KIT_PLAN = Path("C:/Users/User/Desktop/노이만_본선자료/기획서/부록/데모입력/plan.md")
FIXTURE_PLAN = ROOT / "tests" / "fixtures" / "plans" / "plan.md"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
FONTS = ['16px "Mr Dafoe"', '16px Pretendard', '16px Jost', '16px "IBM Plex Mono"', '16px "Instrument Serif"']


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def start_server(port: int) -> subprocess.Popen:
    if not port_free(port):
        raise SystemExit(f"포트 {port}가 이미 쓰이고 있다. 다른 서버를 끄거나 --port를 바꿔라")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT)])
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "neumann.api.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        cwd=ROOT, env=env)
    deadline = time.time() + 40
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"서버가 바로 종료됨(exit {proc.returncode})")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    stop_server(proc)
    raise SystemExit("서버가 40초 안에 /health 200을 내지 않았다")


def stop_server(proc: subprocess.Popen, port: int | None = None) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    if port is not None:  # 소켓이 닫힐 때까지 잠깐 기다린다(Windows는 종료 직후 몇백 ms 남는다)
        deadline = time.time() + 10
        while time.time() < deadline and not port_free(port):
            time.sleep(0.2)


def shoot(base: str, plan_text: str, out: Path, prefix: str) -> dict:
    from playwright.sync_api import sync_playwright

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed: list[str] = []
    requests: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="ko-KR")
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}"))

        # 1 입력
        page.goto(base + "/", wait_until="networkidle")
        page.wait_for_selector('body[data-view="input"][data-ready="1"]')
        page.wait_for_function("document.getElementById('hdrState').textContent !== '서버 확인 중'")
        page.fill("#ta", plan_text)
        page.evaluate("document.fonts.ready.then(() => true)")
        fonts_input = page.evaluate(f"{json.dumps(FONTS)}.map(f => document.fonts.check(f))")
        page.screenshot(path=str(out / f"{prefix}_input.png"))

        # 2 실행 → 3 리포트
        t0 = time.time()
        page.click("#btnStart")
        page.wait_for_function(
            "document.body.dataset.view === 'report' && document.body.dataset.ready === '1' && "
            "!!(document.querySelector('#s-cards .rc') || document.querySelector('#noCards'))",
            timeout=180_000)
        elapsed = time.time() - t0
        page.evaluate("document.fonts.ready.then(() => true)")
        page.wait_for_load_state("networkidle")
        fonts_report = page.evaluate(f"{json.dumps(FONTS)}.map(f => document.fonts.check(f))")
        loaded_faces = page.evaluate(
            "Array.from(document.fonts).filter(f => f.status === 'loaded').map(f => f.family + ' ' + f.weight + ' ' + f.style)")
        page.screenshot(path=str(out / f"{prefix}_report.png"))

        dom = page.evaluate("""() => {
          const q = s => document.querySelectorAll(s).length;
          const cards = Array.from(document.querySelectorAll('#s-cards .rc'));
          return {
            status_notice: (document.getElementById('statusNotice') || {}).innerText || '',
            header_state: document.getElementById('hdrState').innerText,
            title: (document.getElementById('repTitle') || {}).innerText || '',
            works_rows: q('#s-map tbody tr:not(.tf)'),
            cards: cards.length,
            cards_with_quote_and_link: cards.filter(c => c.querySelector('.ev .q') && c.querySelector('.ev a.src[href^="http"]')).length,
            quotes: q('#s-cards .ev .q'),
            sections: Array.from(document.querySelectorAll('.doc section')).map(s => s.id),
            no_cards: !!document.getElementById('noCards'),
          };
        }""")

        # 카드 영역 + 근거 패널(인용문 클릭)
        if dom["cards"]:
            page.evaluate("document.getElementById('s-cards').scrollIntoView({block: 'start'})")
            page.click("#s-cards .ev .q >> nth=0")
            page.wait_for_selector("#pbody .pq")
            page.wait_for_timeout(300)
            page.screenshot(path=str(out / f"{prefix}_cards.png"))

        # '새 분석' 뒤 입력칸이 비는지(계획서 §4 E4 함정)
        page.click("#btnNew")
        page.wait_for_selector('body[data-view="input"][data-ready="1"]')
        new_analysis_textarea = page.input_value("#ta")

        # 실패·0장 화면: 응답을 가로채 오류 뷰와 0장 뷰를 넣는다(서버·파이프라인은 그대로).
        # 500 응답은 브라우저가 "Failed to load resource" 콘솔 오류를 남기므로 본 흐름과 따로 센다.
        main_console_errors = list(console_errors)
        extra = {}
        for name, code, body, sel in (
            ("error", 500, build_ui_view(None, pipeline_state="connected", error="파이프라인 실행 실패: TimeoutError"),
             "#jobErr"),
            ("zero_cards", 200, build_ui_view({"status": "ok", "plan_stats": {"lines": [{"n": 1, "t": "김치찌개 조리법"}]},
                                               "empty_reason": "무관한 입력: 연구계획서가 아니다"}), "#noCards"),
        ):
            page.route("**/premortem/view", lambda route, _req, c=code, b=body: route.fulfill(
                status=c, content_type="application/json", body=json.dumps(b, ensure_ascii=False)))
            page.fill("#ta", "김치찌개 조리법")
            page.click("#btnStart")
            page.wait_for_selector(sel, timeout=20_000)
            extra[name] = page.inner_text(sel)
            page.unroute("**/premortem/view")
            page.goto(base + "/", wait_until="networkidle")
            page.wait_for_selector('body[data-view="input"][data-ready="1"]')
        browser.close()

    external = []
    for u in requests:
        pu = urlparse(u)
        if pu.scheme in {"data", "blob", "about"}:
            continue
        if pu.hostname not in LOCAL_HOSTS:
            external.append(u)
    return {
        "analysis_wait_s": round(elapsed, 2),
        "console_errors": main_console_errors,
        "console_errors_in_failure_scenarios": console_errors[len(main_console_errors):],
        "page_errors": page_errors,
        "failed_requests": failed,
        "requests_total": len(requests),
        "requests": sorted({urlparse(u).path for u in requests}),
        "external_requests": external,
        "fonts_check_input": dict(zip(FONTS, fonts_input)),
        "fonts_check_report": dict(zip(FONTS, fonts_report)),
        "fonts_loaded": sorted(set(loaded_faces)),
        "dom": dom,
        "new_analysis_textarea_empty": new_analysis_textarea == "",
        "error_screen": extra.get("error", ""),
        "zero_card_screen": extra.get("zero_cards", ""),
    }


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path, default=FIXTURE_PLAN if FIXTURE_PLAN.is_file() else KIT_PLAN)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "reports")
    ap.add_argument("--prefix", default="E4-L0")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    plan_text = args.plan.read_text(encoding="utf-8")

    proc = start_server(args.port)
    try:
        report = shoot(f"http://127.0.0.1:{args.port}", plan_text, args.out, args.prefix)
    finally:
        stop_server(proc, args.port)
    report["plan"] = args.plan.name
    report["server_stopped"] = proc.poll() is not None
    report["port_free_after"] = port_free(args.port)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    bad = (report["console_errors"] or report["page_errors"] or report["failed_requests"]
           or report["external_requests"] or not all(report["fonts_check_report"].values())
           or not (report["dom"]["cards"] or report["dom"]["no_cards"])
           or not report["new_analysis_textarea_empty"]
           or "TimeoutError" not in report["error_screen"] or "무관한 입력" not in report["zero_card_screen"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
