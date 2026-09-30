"""정적 사이트 확인 (E6-L3a): ``data/site/``를 로컬 정적 서버(``python -m http.server``)에 올려 Playwright로 찍는다.

    python scripts/build_static_site_shots.py [--site DIR] [--out docs/reports] [--prefix E6-L3a] [--port N]

- GitHub Pages와 같은 하위 경로를 흉내 낸다: 임시 폴더에 ``project_neumann/``으로 복사하고
  ``http://127.0.0.1:<port>/project_neumann/``을 연다(상대 경로가 깨지면 여기서 드러난다).
- 1440×900, 렌더 완료 DOM 조건을 기다린 뒤 찍는다: 입력(데모 선택) → 데모 1 리포트 → 위험카드·근거 패널.
- 데모 3건을 모두 돌려 리포트에 "라이브 분석 아님" 표시가 나오는지, 데모 밖 입력이 거절되는지 잰다.
- 화면이 템플릿 선택기(GET templates, E4-L1b)를 쓰면: 목록이 정적 JSON으로 뜨는지, 골격을 고르면 본문이 바뀌고
  실행이 막히는지(분석 결과는 데모뿐), 예시를 고르면 데모와 맞아 실행이 열리는지 잰다.
- 콘솔 오류·페이지 오류·실패 요청(4xx/5xx 포함)·외부 도메인 요청을 기록한다. 하나라도 있으면 exit 1.
- 서버는 끝나면(실패해도) 종료하고 포트가 비었는지 확인한다. 8010(PM 점검 서버)·8000은 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
SUBPATH = "project_neumann"
RESERVED_PORTS = {8000, 8010}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
FONTS = ['16px "Mr Dafoe"', '16px Pretendard', '16px Jost', '16px "IBM Plex Mono"', '16px "Instrument Serif"']


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def pick_port() -> int:
    for _ in range(20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port not in RESERVED_PORTS and port_free(port):
            return port
    raise SystemExit("빈 포트를 찾지 못했다")


def start_server(root: Path, port: int) -> subprocess.Popen:
    if port in RESERVED_PORTS:
        raise SystemExit(f"포트 {port}는 쓰지 않는다(PM 점검 서버·API 서버)")
    if not port_free(port):
        raise SystemExit(f"포트 {port}가 이미 쓰이고 있다")
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                             "--directory", str(root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"정적 서버가 바로 종료됨(exit {proc.returncode})")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/{SUBPATH}/", timeout=2) as r:
                if r.status == 200:
                    return proc
        except OSError:
            pass
        time.sleep(0.2)
    stop_server(proc, port)
    raise SystemExit("정적 서버가 20초 안에 응답하지 않았다")


def stop_server(proc: subprocess.Popen, port: int) -> bool:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    deadline = time.time() + 10
    while time.time() < deadline and not port_free(port):
        time.sleep(0.2)
    return port_free(port)


WAIT_INPUT = ("document.body.dataset.view === 'input' && document.body.dataset.ready === '1' && "
              "!!document.getElementById('demoPicker') && document.getElementById('hdrState').textContent !== '서버 확인 중' && "
              "(!document.getElementById('tplArea') || !!document.getElementById('tplList') || !!document.getElementById('tplErr'))")
WAIT_REPORT = ("document.body.dataset.view === 'report' && document.body.dataset.ready === '1' && "
               "!!document.getElementById('statusNotice') && "
               "!!(document.querySelector('#s-cards .rc') || document.querySelector('#noCards'))")


def shoot(base: str, out: Path, prefix: str) -> dict:
    from playwright.sync_api import sync_playwright

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed: list[str] = []
    bad_status: list[str] = []
    requests: list[str] = []
    res: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="ko-KR")
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.on("requestfailed", lambda r: failed.append(f"{urlparse(r.url).path} {r.failure}"))
        page.on("response", lambda r: bad_status.append(f"{urlparse(r.url).path} {r.status}") if r.status >= 400 else None)

        # 1 입력(데모 선택)
        page.goto(base, wait_until="networkidle")
        page.wait_for_function(WAIT_INPUT)
        page.evaluate("document.fonts.ready.then(() => true)")
        res["input"] = page.evaluate("""() => {
            const ta = document.getElementById('ta');
            return {
              header_state: document.getElementById('hdrState').textContent,
              banner: (document.getElementById('staticBanner') || {}).textContent || '',
              demos: Array.from(document.querySelectorAll('#demoPicker .sdemo')).map(b => b.textContent),
              selected: Array.from(document.querySelectorAll('#demoPicker .sdemo.on')).map(b => b.dataset.demo),
              textarea_readonly: ta.readOnly, textarea_chars: ta.value.length,
              file_upload_visible: !!document.querySelector('#app [data-mode="file"]'),
              start_enabled: !document.getElementById('btnStart').disabled,
              title: document.title,
              template_selector: !!document.getElementById('tplArea'),
              templates: document.querySelectorAll('#tplList [data-tpl]').length,
              examples: document.querySelectorAll('#exList [data-ex]').length,
              template_error: (document.getElementById('tplErr') || {}).textContent || '',
            };
        }""")
        page.screenshot(path=str(out / f"{prefix}_input.png"))

        # 1-2 템플릿 선택기(있으면): 골격 → 실행 막힘, 예시 → 데모와 맞아 실행 열림, 데모 1로 되돌림
        if res["input"]["templates"]:
            state = """() => ({text: document.getElementById('ta').value.split('\\n')[0],
                              start_enabled: !document.getElementById('btnStart').disabled,
                              demo: document.body.getAttribute('data-static-demo'),
                              note_warn: document.getElementById('staticNote').classList.contains('warn'),
                              tpl_on: (document.querySelector('#tplList .tp.on') || {}).dataset?.tpl || '',
                              ex_on: (document.querySelector('#exList .exl.on') || {}).dataset?.ex || ''})"""
            tpl_id = page.get_attribute("#tplList [data-tpl]", "data-tpl")
            page.click(f'#tplList [data-tpl="{tpl_id}"]')
            page.wait_for_function(f"(document.querySelector('#tplList .tp.on') || {{}}).dataset?.tpl === '{tpl_id}' "
                                   "&& document.body.getAttribute('data-static-demo') === '-1'")
            res["template_pick"] = {"id": tpl_id, **page.evaluate(state)}
            ex_id = page.get_attribute("#exList [data-ex]", "data-ex")
            page.click(f'#exList [data-ex="{ex_id}"]')
            page.wait_for_function(f"(document.querySelector('#exList .exl.on') || {{}}).dataset?.ex === '{ex_id}' "
                                   "&& document.body.getAttribute('data-static-demo') !== '-1'")
            res["example_pick"] = {"id": ex_id, **page.evaluate(state)}
            page.click('#demoPicker .sdemo[data-demo="0"]')
            page.wait_for_function("document.body.getAttribute('data-static-demo') === '0'")

        # 2 데모 3건 → 리포트
        n = len(res["input"]["demos"])
        res["reports"] = []
        for i in range(n):
            if i > 0:
                page.click("#btnNew")
                page.wait_for_function(WAIT_INPUT)
            page.click(f'#demoPicker .sdemo[data-demo="{i}"]')
            page.click("#btnStart")
            page.wait_for_function(WAIT_REPORT, timeout=30_000)
            page.evaluate("document.fonts.ready.then(() => true)")
            page.wait_for_load_state("networkidle")
            dom = page.evaluate("""() => ({
                notice: document.getElementById('statusNotice').textContent,
                title: (document.getElementById('repTitle') || {}).textContent || '',
                cards: document.querySelectorAll('#s-cards .rc').length,
                works_rows: document.querySelectorAll('table.map tbody tr:not(.tf)').length,
                quotes: document.querySelectorAll('#s-cards .ev .q').length,
                header_state: document.getElementById('hdrState').textContent,
                trace: (document.querySelector('#s-trace .trace') || {}).textContent || '',
            })""")
            dom["demo"] = i
            dom["live_note_shown"] = "라이브 분석 아님" in dom["notice"]
            res["reports"].append(dom)
            if i == 0:
                res["fonts_report"] = page.evaluate(f"{json.dumps(FONTS)}.map(f => document.fonts.check(f))")
                page.screenshot(path=str(out / f"{prefix}_report.png"))
                # 3 위험카드 + 근거 패널
                page.evaluate("document.getElementById('s-cards').scrollIntoView({block: 'start'})")
                q = page.query_selector("#s-cards .ev .q")
                if q:
                    q.click()
                    page.wait_for_function("!!document.querySelector('#pbody .pq')")
                page.wait_for_timeout(300)
                page.screenshot(path=str(out / f"{prefix}_cards.png"))
                res["panel_quote"] = page.evaluate("(document.querySelector('#pbody .pq') || {}).textContent || ''")[:80]

        # 4 데모 밖 입력은 거절(정적 판은 분석하지 않는다)
        res["non_demo"] = page.evaluate("""async () => {
            const r = await fetch('premortem/view', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                     body: JSON.stringify({plan_text: '데모가 아닌 계획서'})});
            const j = await r.json();
            return {status: r.status, label: (j._status || {}).label || ''};
        }""")
        browser.close()

    # 데모 밖 입력의 404는 의도한 응답(가로채기가 만든 것이라 네트워크에 나가지 않는다)
    external = [u for u in requests if urlparse(u).hostname not in LOCAL_HOSTS and not u.startswith("data:")]
    res.update({
        "console_errors": console_errors, "page_errors": page_errors, "failed_requests": failed,
        "bad_status": bad_status, "external_requests": external,
        "requests": len(requests), "request_paths": sorted({urlparse(u).path for u in requests}),
    })
    return res


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", type=Path, default=None, help="정적 사이트 폴더(기본: <data>/site)")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "reports")
    ap.add_argument("--prefix", default="E6-L3a")
    ap.add_argument("--port", type=int, default=0, help="0이면 빈 포트(8000·8010 제외)")
    args = ap.parse_args()

    site = args.site
    if site is None:
        sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
        from neumann.config import get_settings

        site = Path(get_settings().data_dir) / "site"
    if not (site / "index.html").is_file():
        raise SystemExit("사이트 폴더에 index.html이 없다. 먼저 python scripts/build_static_site.py")
    args.out.mkdir(parents=True, exist_ok=True)

    stage = Path(tempfile.mkdtemp(prefix="neumann-pages-"))
    port = args.port or pick_port()
    proc = None
    result: dict = {}
    try:
        shutil.copytree(site, stage / SUBPATH)
        proc = start_server(stage, port)
        result = shoot(f"http://127.0.0.1:{port}/{SUBPATH}/", args.out, args.prefix)
    finally:
        stopped = stop_server(proc, port) if proc else True
        shutil.rmtree(stage, ignore_errors=True)
        result.update({"server": f"python -m http.server (127.0.0.1, 하위 경로 /{SUBPATH}/)",
                       "server_stopped": proc is None or proc.poll() is not None, "port_free_after": stopped})
    bad = (result.get("console_errors") or result.get("page_errors") or result.get("failed_requests")
           or result.get("bad_status") or result.get("external_requests"))
    reports = result.get("reports", [])
    inp = result.get("input", {})
    tpl_ok = True
    if inp.get("template_selector"):
        tp, ex = result.get("template_pick", {}), result.get("example_pick", {})
        tpl_ok = (inp.get("templates", 0) > 0 and not inp.get("template_error")
                  and tp.get("start_enabled") is False and tp.get("note_warn") is True
                  and ex.get("start_enabled") is True and ex.get("demo") not in (None, "-1"))
    result["templates_ok"] = tpl_ok
    print(json.dumps(result, ensure_ascii=False, indent=1))
    ok = (not bad and tpl_ok and len(reports) == 3 and all(r["live_note_shown"] for r in reports)
          and result.get("input", {}).get("textarea_readonly") and result.get("non_demo", {}).get("status") == 404)
    print("shots:", "통과" if ok else "실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
