"""E4-L3m 반응형 검사: 휴대폰 390×844 · 태블릿 768×1024 · 데스크톱 1440×900에서 입력 · 대기 · 리포트 화면.

    NEUMANN_UI_TESTS=1 python -m pytest tests/e4/test_responsive.py -q -s
    python tests/e4/test_responsive.py [--port 8150] [--out docs/reports] [--prefix E4-L3m]

- 기본 pytest(verify)에서는 건너뛴다(브라우저·서버 필요). ``NEUMANN_UI_TESTS=1``일 때만 돈다.
- 서버는 하위 프로세스(uvicorn, 기본 8150번)로 띄우고 끝나면(실패해도) 끈다. 8010·8020은 쓰지 않는다.
  서버에는 ``NEUMANN_LLM_PROVIDER=mock``을 주고 ``OPENAI_API_KEY``를 넘기지 않는다(실제 API 호출 없음).
- 리포트 데이터: ``/premortem/view`` 응답을 가로채 fixture 기반 풍부한 뷰(test_view_shots.rich_view: 지도·카드·
  예상 심사평·체크리스트가 모두 있는 샘플)를 넣는다. 대기 화면은 응답을 붙잡아 둔 채 잰다.
- 화면마다 잰다: 가로 넘침(``document.documentElement.scrollWidth <= innerWidth``), 화면 밖으로 나간 요소
  (가로 스크롤 상자 안은 제외), 좌우 여백(390·768은 16px), 글자가 상자를 넘치는 버튼·라벨, 형제 요소 겹침,
  근거 패널 여닫기(좁은 화면 = 서랍, 1440 = 오른쪽 상시 패널), 실행 버튼이 전송 고지에 가리지 않는지.
- 콘솔 오류·페이지 오류·실패 요청·외부 도메인 요청이 하나라도 있으면 실패.
- 스크린샷: ``{prefix}_{390,768,1440}_{input,report}.png``(전체 페이지), ``{prefix}_{390,768}_{job,panel}.png``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

PREFIX = "E4-L3m"
DEFAULT_PORT = 8150
FORBIDDEN_PORTS = {8010, 8020}
VIEWPORTS = [(390, 844), (768, 1024), (1440, 900)]
GUTTER = 16  # 390·768 좌우 여백(px)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
REPORT_READY = ("document.body.dataset.view === 'report' && document.body.dataset.ready === '1' && "
                "!!(document.querySelector('#s-cards .rc') || document.querySelector('#noCards'))")

pytestmark = pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="NEUMANN_UI_TESTS=1일 때만(브라우저·서버 필요)")

# 화면 하나를 잰다. 반환: 넘침·밖으로 나간 요소·글자 넘침·겹침·여백.
LAYOUT = r"""(arg) => {
  const vw = window.innerWidth, de = document.documentElement;
  const desc = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : '') + ' "' + (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 24) + '"';
  const shown = el => { const cs = getComputedStyle(el); if (cs.display === 'none' || cs.visibility === 'hidden') return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const scroller = el => { for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) { const ox = getComputedStyle(p).overflowX; if (ox === 'auto' || ox === 'scroll') return p; } return null; };
  const inPanel = el => !!el.closest('.panel');
  // 1) 화면 밖으로 나간 요소(가로 스크롤 상자 안은 사용자가 밀어 볼 수 있으니 제외, 서랍 패널은 따로 잰다)
  const offscreen = [];
  document.querySelectorAll('.top *, #app *, .foot *').forEach(el => {
    if (inPanel(el) || !shown(el)) return;
    const r = el.getBoundingClientRect();
    if ((r.right > vw + 0.5 || r.left < -0.5) && !scroller(el)) offscreen.push(desc(el) + ' [' + Math.round(r.left) + ',' + Math.round(r.right) + ']');
  });
  // 2) 글자가 상자를 넘치는 버튼·라벨(높이 고정 버튼이 두 줄로 접히거나, 가로로 삐져나감)
  const FIX = '.btn, .stp, .tp, .exl, .dec, .cite, .lref, .seg button, .ptabs button, .pill, .idx a, .tag, .strip .c, .evh .nav button, .sendnote summary, h1, h2, h3, .kpiline .v, .rc .score .v, .t3 .sc';
  const clipped = [];
  document.querySelectorAll(FIX).forEach(el => {
    if (!shown(el) || el.clientWidth === 0) return;
    // 세로는 글리프가 line-height 밖으로 몇 px 나오는 것을 봐준다(4px). 높이 고정 버튼이 두 줄로 접히면 걸린다
    if (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 4) clipped.push(desc(el) + ' ' + el.scrollWidth + '/' + el.clientWidth + 'x' + el.scrollHeight + '/' + el.clientHeight);
  });
  // 3) 형제 겹침: 플렉스·그리드 상자의 직계 자식끼리
  const BOXES = ['.top', '#steps', '.top .r', '.scope', '.seg', '#tplList', '#exList', '.tplmeta', '#inCard > div:last-child', '.sendnote summary', '.file', '.drop',
                 '.hero h1', '.tn', '.idx', '.idx > span', '.kpiline', '.t3', '.rc .hd', '.rc .hd .sub', '.kv', '.meters', '.ev', '.ev .m', '.acts .a', '.distl', '.strip',
                 '.rev .gh', '.audit', '.ck', '.ck .sub', '.trace', '.evh', '.pkv', '.pcard', '.same', '.pline', '.ptabs', '.corp'];
  const overlaps = [];
  const hit = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1;
  BOXES.forEach(sel => document.querySelectorAll(sel).forEach(box => {
    if (!shown(box)) return;
    const d = getComputedStyle(box).display;
    if (!/flex|grid/.test(d)) return;
    const kids = Array.from(box.children).filter(k => shown(k) && getComputedStyle(k).position !== 'absolute' && getComputedStyle(k).position !== 'fixed');
    for (let i = 0; i < kids.length; i++) for (let j = i + 1; j < kids.length; j++) {
      const a = kids[i].getBoundingClientRect(), b = kids[j].getBoundingClientRect();
      if (hit(a, b)) overlaps.push(sel + ': ' + desc(kids[i]) + ' × ' + desc(kids[j]));
    }
  }));
  // 4) 좌우 여백
  const wrap = document.querySelector('.wrap'), ws = getComputedStyle(wrap);
  const main = document.querySelector(arg.main);
  const mr = main ? main.getBoundingClientRect() : null;
  return {
    vw, scroll_w: de.scrollWidth, body_scroll_w: document.body.scrollWidth,
    overflow_x: de.scrollWidth > vw || document.body.scrollWidth > vw,
    offscreen: offscreen.slice(0, 20), offscreen_n: offscreen.length,
    clipped: clipped.slice(0, 20), clipped_n: clipped.length,
    overlaps: overlaps.slice(0, 20), overlaps_n: overlaps.length,
    wrap_pad: [parseFloat(ws.paddingLeft), parseFloat(ws.paddingRight)],
    main_lr: mr ? [Math.round(mr.left * 10) / 10, Math.round((vw - mr.right) * 10) / 10] : null,
    top_h: Math.round(document.querySelector('.top').getBoundingClientRect().height),
    doc_h: de.scrollHeight,
  };
}"""

PANEL = r"""() => {
  const vw = window.innerWidth, p = document.querySelector('.panel'), r = p.getBoundingClientRect();
  const cs = getComputedStyle(p), pb = document.getElementById('pbody');
  const vis = el => { if (!el) return false; const c = getComputedStyle(el); const b = el.getBoundingClientRect(); return c.display !== 'none' && c.visibility !== 'hidden' && b.width > 0 && b.height > 0; };
  const inView = r.left >= -0.5 && r.right <= vw + 0.5 && r.width > 0;
  return {
    position: cs.position, open_class: document.body.classList.contains('popen'),
    left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width), height: Math.round(r.height),
    in_view: inView, visibility: cs.visibility,
    pbody_overflow_x: pb ? pb.scrollWidth > pb.clientWidth + 1 : null,
    pclose_shown: vis(document.querySelector('.pclose')), pfab_shown: vis(document.querySelector('.pfab')),
    quote: (document.getElementById('evQuote') || {}).textContent || '',
  };
}"""

BTN_FREE = r"""() => {
  window.scrollTo(0, document.documentElement.scrollHeight);
  const b = document.getElementById('btnStart'), r = b.getBoundingClientRect();
  const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return {btn_on_top: !!(top && (top === b || b.contains(top))), btn_h: Math.round(r.height), btn_w: Math.round(r.width),
          note_h: Math.round(document.getElementById('sendNote').getBoundingClientRect().height)};
}"""


def _port_free(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def shoot(base: str, out: Path, prefix: str = PREFIX, html: Path | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    from tests.e4.test_view_shots import rich_view
    from tests.fixtures.loader import plan_text

    body = json.dumps(rich_view(), ensure_ascii=False)
    text = plan_text()
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed: list[str] = []
    requests: list[str] = []
    res: dict = {"shots": [], "vp": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        only = {int(x) for x in os.environ.get("NEUMANN_UI_VP", "").split(",") if x.strip()}
        for w, h in [v for v in VIEWPORTS if not only or v[0] in only]:
            narrow = w < 1181
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, locale="ko-KR")
            page = ctx.new_page()
            if html is not None:  # 전후 비교용: 첫 화면 문서만 다른 판(예: main의 index.html)으로 바꿔 끼운다
                page.route(base + "/", lambda route, _req: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html.read_text(encoding="utf-8")))
            page.on("console", lambda m: console_errors.append(f"{w}: {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: page_errors.append(f"{w}: {e}"))
            page.on("request", lambda r: requests.append(r.url))
            page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}"))
            r: dict = {}
            log = lambda msg: print(f"[{w}] {msg}", file=sys.stderr, flush=True)  # noqa: E731

            def snap(name: str, full: bool = False, tall: bool = False) -> None:
                page.wait_for_timeout(200)
                path = out / f"{prefix}_{w}_{name}.png"
                if tall:  # sticky 고지가 제자리에 보이게 창을 문서 높이로 늘려 찍고 되돌린다(가로 폭은 그대로)
                    page.set_viewport_size({"width": w, "height": page.evaluate("document.documentElement.scrollHeight")})
                    page.wait_for_timeout(200)
                    page.screenshot(path=str(path))
                    page.set_viewport_size({"width": w, "height": h})
                else:
                    page.screenshot(path=str(path), full_page=full)
                res["shots"].append(path.name)

            # 1 입력: 템플릿 목록·헤더 상태·폰트까지 그려진 뒤, 예시 하나를 불러온 상태
            page.goto(base + "/", wait_until="networkidle")
            page.wait_for_selector('body[data-view="input"][data-ready="1"]')
            page.wait_for_selector("#tplList .tp")
            page.wait_for_function("document.getElementById('hdrState').textContent !== '서버 확인 중'")
            page.evaluate("document.fonts.ready.then(() => true)")
            r["input_empty"] = page.evaluate(LAYOUT, {"main": "#inCard"})
            page.click("#exList .exl >> nth=0")
            page.wait_for_function("document.getElementById('ta') && document.getElementById('ta').value.length > 0 && !document.getElementById('btnStart').disabled")
            page.evaluate("window.scrollTo(0, 0)")
            r["input"] = page.evaluate(LAYOUT, {"main": "#inCard"})
            log("input")
            r["tpl_cols"] = page.evaluate("getComputedStyle(document.getElementById('tplList')).gridTemplateColumns.split(' ').length")
            snap("input", tall=True)
            r["run_btn"] = page.evaluate(BTN_FREE)
            page.evaluate("window.scrollTo(0, 0)")
            # 파일 업로드 모드도 넘침만 잰다
            page.click('.seg button[data-mode="file"]')
            page.wait_for_selector("#drop")
            r["input_file"] = page.evaluate(LAYOUT, {"main": "#inCard"})
            page.click('.seg button[data-mode="text"]')
            page.wait_for_selector("#ta")
            page.fill("#ta", text)

            # 2 대기: 응답을 붙잡아 둔 채 잰다
            held: list = []
            page.route("**/premortem/view", lambda route, _req: held.append(route))
            page.click("#btnStart")
            page.wait_for_selector('body[data-view="job"][data-ready="1"]')
            page.wait_for_function("document.querySelector('.tn.run') !== null")
            page.wait_for_timeout(150)
            r["job"] = page.evaluate(LAYOUT, {"main": "#app .col"})
            log("job")
            if narrow:
                snap("job")
            for _ in range(50):  # route 콜백은 Playwright 호출 사이에 돈다: 최대 5초 기다린다
                if held:
                    break
                page.wait_for_timeout(100)
            assert held, "/premortem/view 요청을 붙잡지 못했다"
            log(f"held {len(held)}")
            held[0].fulfill(status=200, content_type="application/json", body=body)
            log("fulfilled")
            page.wait_for_function(REPORT_READY, timeout=60_000)
            log("report ready")  # unroute는 하지 않는다(가끔 멈춘다). 이 페이지는 더 요청하지 않고 곧 닫는다
            page.evaluate("document.fonts.ready.then(() => true)")
            page.wait_for_load_state("networkidle")
            page.evaluate("window.scrollTo(0, 0)")

            # 3 리포트
            r["report"] = page.evaluate(LAYOUT, {"main": ".doc"})
            log("report")
            r["strip_cols"] = page.evaluate("getComputedStyle(document.querySelector('.strip')).gridTemplateColumns.split(' ').length")
            r["sections"] = page.evaluate("Array.from(document.querySelectorAll('.doc section')).filter(s => s.offsetParent).map(s => s.id)")
            snap("report", full=True)
            r["panel_closed"] = page.evaluate(PANEL)
            if narrow and page.locator(".pfab").count() and page.locator(".pclose").count():
                # 떠 있는 버튼으로 열고 닫기 → 근거 번호로 열기
                page.click(".pfab")
                page.wait_for_timeout(350)
                r["panel_fab"] = page.evaluate(PANEL)
                page.click(".pclose")
                page.wait_for_timeout(350)
                r["panel_after_close"] = page.evaluate(PANEL)
                page.evaluate("document.getElementById('s-cards').scrollIntoView({block: 'start'})")
                page.click("#s-cards .ev .cite >> nth=0")
                page.wait_for_selector("#pbody #evQuote")
                page.wait_for_timeout(350)
                r["panel_cite"] = page.evaluate(PANEL)
                r["panel_layout"] = page.evaluate(LAYOUT, {"main": ".panel"})
                snap("panel")
                page.click(".pclose")
                page.wait_for_timeout(350)
                r["panel_after_close2"] = page.evaluate(PANEL)
            else:
                page.click("#s-cards .ev .cite >> nth=0")
                page.wait_for_selector("#pbody #evQuote")
                r["panel_cite"] = page.evaluate(PANEL)
            res["vp"][str(w)] = r
            ctx.close()
        browser.close()
    res["console_errors"] = console_errors
    res["page_errors"] = page_errors
    res["failed_requests"] = failed
    res["external_requests"] = [u for u in requests if urlparse(u).scheme not in {"data", "blob", "about"}
                                and urlparse(u).hostname not in LOCAL_HOSTS]
    return res


def check(res: dict) -> list[str]:
    """완료 기준 판정. 빈 목록이면 통과."""
    bad = []
    for key in ("console_errors", "page_errors", "failed_requests", "external_requests"):
        if res[key]:
            bad.append(f"{key}: {res[key][:3]}")
    for w, r in res["vp"].items():
        narrow = int(w) < 1181
        for scr in ("input_empty", "input", "input_file", "job", "report") + (("panel_layout",) if narrow else ()):
            m = r.get(scr)
            if m is None:
                bad.append(f"{w} {scr}: 측정 없음")
                continue
            if m["overflow_x"]:
                bad.append(f"{w} {scr}: 가로 넘침 scrollWidth {m['scroll_w']}/{m['body_scroll_w']} > {m['vw']}")
            if m["offscreen_n"]:
                bad.append(f"{w} {scr}: 화면 밖 요소 {m['offscreen_n']}개 {m['offscreen'][:3]}")
            if m["clipped_n"]:
                bad.append(f"{w} {scr}: 글자 넘침 {m['clipped_n']}개 {m['clipped'][:3]}")
            if m["overlaps_n"]:
                bad.append(f"{w} {scr}: 겹침 {m['overlaps_n']}개 {m['overlaps'][:3]}")
            if int(w) <= 768 and scr != "panel_layout":
                if m["wrap_pad"] != [GUTTER, GUTTER]:
                    bad.append(f"{w} {scr}: 좌우 여백 {m['wrap_pad']} != {GUTTER}px")
                if m["main_lr"] and min(m["main_lr"]) < GUTTER - 0.5:
                    bad.append(f"{w} {scr}: 본문 상자 좌우 {m['main_lr']} < {GUTTER}px")
        rb = r["run_btn"]
        if not rb["btn_on_top"]:
            bad.append(f"{w}: 맨 아래로 내렸을 때 실행 버튼이 가려짐 {rb}")
        if "s-cards" not in r["sections"] or "s-check" not in r["sections"] or "s-review" not in r["sections"]:
            bad.append(f"{w}: 리포트 섹션 누락 {r['sections']}")
        pc = r["panel_cite"]
        if not pc["in_view"] or not pc["quote"]:
            bad.append(f"{w}: 근거 번호를 눌러도 패널이 화면 안에 안 열림 {pc}")
        if pc["pbody_overflow_x"]:
            bad.append(f"{w}: 근거 패널 안 가로 넘침")
        if narrow:
            if r["panel_closed"]["in_view"] and r["panel_closed"]["visibility"] != "hidden":
                bad.append(f"{w}: 닫힌 패널이 화면에 보임 {r['panel_closed']}")
            if not r["panel_closed"]["pfab_shown"]:
                bad.append(f"{w}: 패널 여는 버튼 없음")
            for k in ("panel_fab", "panel_cite"):
                v = r.get(k) or {}
                if not (v.get("open_class") and v.get("in_view") and v.get("pclose_shown")):
                    bad.append(f"{w}: {k} 패널 열림·닫기 버튼 이상 {v}")
            for k in ("panel_after_close", "panel_after_close2"):
                v = r.get(k)
                if not v or v["open_class"] or (v["in_view"] and v["visibility"] != "hidden"):
                    bad.append(f"{w}: {k} 닫기 버튼으로 안 닫힘 {v}")
            if r["tpl_cols"] > 3 and int(w) < 600:
                bad.append(f"{w}: 템플릿 선택기 {r['tpl_cols']}열(휴대폰에서 너무 좁음)")
            if int(w) < 600 and r["strip_cols"] > 10:
                bad.append(f"{w}: 줄 스트립 {r['strip_cols']}열(칸이 너무 좁음)")
        else:
            if r["panel_closed"]["position"] != "sticky" or r["panel_closed"]["pfab_shown"] or r["panel_closed"]["pclose_shown"]:
                bad.append(f"{w}: 데스크톱 상시 패널이 바뀜 {r['panel_closed']}")
            m = r["report"]
            if m["wrap_pad"] != [36, 36] or m["top_h"] != 60:
                bad.append(f"{w}: 데스크톱 여백·상단바 바뀜 pad {m['wrap_pad']} top {m['top_h']}")
    return bad


def _run(port: int, out: Path, prefix: str = PREFIX, html: Path | None = None) -> dict:
    from tests.e4.ui_shots import start_server, stop_server

    if port in FORBIDDEN_PORTS:
        raise SystemExit(f"{port}번은 쓰지 않는다(8010 점검 서버·8020)")
    if not _port_free(port):
        raise SystemExit(f"포트 {port}가 이미 쓰이고 있다")
    out.mkdir(parents=True, exist_ok=True)
    saved = dict(os.environ)
    os.environ.pop("OPENAI_API_KEY", None)  # 서버 하위 프로세스에 키를 넘기지 않는다
    os.environ.pop("NEUMANN_LIVE_LLM_OK", None)
    os.environ.update({"NEUMANN_LLM_PROVIDER": "mock", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    try:
        proc = start_server(port)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    try:
        return shoot(f"http://127.0.0.1:{port}", out, prefix, html)
    finally:
        stop_server(proc, port)


def test_responsive(tmp_path):
    out = Path(os.environ.get("NEUMANN_UI_SHOTS_OUT") or tmp_path)
    res = _run(int(os.environ.get("NEUMANN_UI_PORT", DEFAULT_PORT)), out)
    bad = check(res)
    assert bad == [], "\n".join(bad)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "reports")
    ap.add_argument("--prefix", default=PREFIX)
    ap.add_argument("--html", type=Path, default=None, help="첫 화면 문서를 이 파일로 바꿔 끼운다(전후 비교)")
    args = ap.parse_args()
    res = _run(args.port, args.out, args.prefix, args.html)
    bad = check(res)
    res["problems"] = bad
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
