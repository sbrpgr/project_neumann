"""전송 고지 Playwright 검사(1440×900): 실행 버튼 아래에 보이는지, 업로드 모드에서도 같은지.

    NEUMANN_UI_TESTS=1 python -m pytest tests/e4/test_notice_ui.py -q -s
    python tests/e4/test_notice_ui.py [--port 8131] [--out docs/reports]

- 기본 pytest(verify)에서는 건너뛴다(브라우저·서버 필요). ``NEUMANN_UI_TESTS=1``일 때만 돈다.
- 서버는 하위 프로세스(uvicorn ``neumann.api.main:app``, 기본 8131번)로 띄우고 끝나면(실패해도) 종료한다. 8010은 쓰지 않는다.
- 렌더 완료 DOM 조건(``data-ready``, 템플릿 목록, 헤더 상태, 폰트)을 기다린 뒤 잰다.
- 콘솔 오류·페이지 오류·실패 요청·외부 도메인 요청이 하나라도 있으면 실패.
- 스크린샷: ``docs/reports/E4-S06_notice.png``(직접 입력 첫 화면, 고지 접힘 = 한 줄 요약),
  ``docs/reports/E4-S06_notice_open.png``(같은 화면, 고지 펼침 = 전문 두 줄).
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

import pytest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "reports"
PREFIX = "E4-S06"
DEFAULT_PORT = 8131
FORBIDDEN_PORT = 8010
VW, VH = 1440, 900
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SEND_LINE = "입력한 계획서는 분석을 위해 OpenAI API로 전송됩니다. 개인정보·미공개 기밀은 넣지 마세요."
STORE_LINE = "이 서버는 계획서 본문을 파일로 저장하지 않습니다."
SUMMARY = "OpenAI API로 전송 · 개인정보·미공개 기밀 입력 금지 · 본문 파일 저장 없음"
NEAR_PX = 60  # 스크롤해 버튼이 보일 때, 고지 아래 끝 ~ 실행 버튼 위 끝 거리 상한
COLLAPSED_MAX_H = 44  # 접힌 고지(한 줄) 높이 상한. 입력칸을 가리는 폭을 줄이려는 것(첫 판 두 줄 64px)

pytestmark = pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="NEUMANN_UI_TESTS=1일 때만(브라우저·서버 필요)")


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def start_server(port: int) -> subprocess.Popen:
    import httpx

    if port == FORBIDDEN_PORT:
        raise SystemExit("8010은 대표 점검 서버 포트다. 다른 포트를 써라")
    if not _port_free(port):
        raise SystemExit(f"포트 {port}가 이미 쓰이고 있다")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]))
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "neumann.api.main:app", "--host", "127.0.0.1",
                             "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
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
    stop_server(proc, port)
    raise SystemExit("서버가 40초 안에 /health 200을 내지 않았다")


def stop_server(proc: subprocess.Popen, port: int) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    deadline = time.time() + 10
    while time.time() < deadline and not _port_free(port):
        time.sleep(0.2)


MEASURE = """() => {
  const n = document.getElementById('sendNote'), b = document.getElementById('btnStart');
  const r = n.getBoundingClientRect(), br = b.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const top = document.elementFromPoint(cx, cy);
  const cs = getComputedStyle(n);
  const sm = n.querySelector('summary'), su = n.querySelector('summary .sum');
  const ta = document.getElementById('ta'), tr = ta ? ta.getBoundingClientRect() : null;
  const lh = parseFloat(getComputedStyle(su).lineHeight);
  return {
    box: {x: r.left, y: r.top, w: r.width, h: r.height, bottom: r.bottom, right: r.right},
    btn: {y: br.top, bottom: br.bottom},
    in_card: !!n.closest('#inCard'),
    on_top: !!(top && n.contains(top)),
    open: n.open,
    text: n.innerText,
    label: n.getAttribute('aria-label'),
    summary_text: su.textContent,
    summary_lines: Math.round(su.getBoundingClientRect().height / lh),
    more_text: n.querySelector('summary .more').textContent,
    spans: Array.from(n.querySelectorAll('.snl')).map(s => s.textContent),
    spans_shown: Array.from(n.querySelectorAll('.snl')).map(s => s.checkVisibility()),
    has_markup_children: Array.from(n.children).map(c => c.tagName),
    textarea_covered_px: tr ? Math.max(0, Math.min(tr.bottom, window.innerHeight) - Math.max(r.top, tr.top)) : null,
    visible: cs.visibility !== 'hidden' && cs.display !== 'none' && r.width > 0 && r.height > 0,
    scrollY: window.scrollY,
    mode: document.querySelector('.seg button.on') && document.querySelector('.seg button.on').dataset.mode
  };
}"""


def click_summary(page) -> None:
    """사용자처럼 보이는 자리를 마우스로 누른다. page.click은 누르기 전에 scrollIntoView를 해서
    scroll-padding 영역 안의 sticky 고지를 보면 화면을 내려 버린다(사용자 동작과 다름)."""
    b = page.locator("#sendNote summary").bounding_box()
    page.mouse.click(b["x"] + 40, b["y"] + b["height"] / 2)


def _in_viewport(m: dict) -> bool:
    b = m["box"]
    return b["x"] >= 0 and b["y"] >= 0 and b["right"] <= VW and b["bottom"] <= VH


def shoot(base: str, out: Path) -> dict:
    from playwright.sync_api import sync_playwright

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed: list[str] = []
    requests: list[str] = []
    res: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=1, locale="ko-KR")
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}"))

        def ready() -> None:
            page.wait_for_selector('body[data-view="input"][data-ready="1"]')
            page.wait_for_function("document.querySelectorAll('#tplList .tp').length > 0 || !!document.getElementById('tplErr')")
            page.wait_for_function("document.getElementById('hdrState').textContent !== '서버 확인 중'")
            page.evaluate("document.fonts.ready.then(() => true)")
            page.wait_for_function("document.querySelectorAll('#sendNote .snl').length === 2")
            page.locator("#sendNote").scroll_into_view_if_needed()

        # 1 입력 단계의 실행 버튼 아래로 내려가 고지를 확인한다.
        page.goto(base + "/", wait_until="networkidle")
        ready()
        m = page.evaluate(MEASURE)
        res["text_first"] = m
        res["text_first_in_viewport"] = _in_viewport(m)
        res["text_first_button_in_viewport"] = m["btn"]["bottom"] <= VH
        page.screenshot(path=str(out / f"{PREFIX}_notice.png"))

        # 1b 펼치기: 전문 두 줄이 보인다. 다시 접는다.
        click_summary(page)
        page.wait_for_function("document.getElementById('sendNote').open === true && document.querySelector('#sendNote .more').textContent === '접기'")
        page.locator("#sendNote").scroll_into_view_if_needed()
        mo = page.evaluate(MEASURE)
        res["text_first_open"] = mo
        res["text_first_open_in_viewport"] = _in_viewport(mo)
        page.screenshot(path=str(out / f"{PREFIX}_notice_open.png"))
        click_summary(page)
        page.wait_for_function("document.getElementById('sendNote').open === false && document.querySelector('#sendNote .more').textContent === '자세히'")
        res["text_first_reclosed"] = page.evaluate(MEASURE)["open"] is False

        # 2 고지는 실행 버튼 아래에 놓이고 입력 내용과 겹치지 않는다.
        page.evaluate("document.getElementById('btnStart').scrollIntoView({block: 'end'})")
        page.locator("#sendNote").scroll_into_view_if_needed()
        page.wait_for_timeout(150)
        m2 = page.evaluate(MEASURE)
        res["text_scrolled"] = m2
        res["text_gap_to_button_px"] = round(m2["box"]["y"] - m2["btn"]["bottom"], 1)

        # 2b 긴 글 끝에서 타이핑(접힘)·붙여넣기(펼침): 캐럿이 있는 마지막 줄이 고지 위에 보인다(scroll-padding-bottom)
        caret_js = """() => {
          const n = document.getElementById('sendNote'), ta = document.getElementById('ta');
          const r = n.getBoundingClientRect(), tr = ta.getBoundingClientRect(), cs = getComputedStyle(ta);
          /* 마지막 줄(캐럿 줄) 아래 끝의 화면 좌표 = 입력칸 위 + 테두리 + (전체 높이 - 안쪽 스크롤) - 아래 안쪽 여백 */
          const lastLineBottom = tr.top + parseFloat(cs.borderTopWidth) + ta.scrollHeight - ta.scrollTop - parseFloat(cs.paddingBottom);
          /* 줄 상자(line-height)는 캐럿 글자보다 아래로 몇 px 길다 → 입력칸 안 보이는 끝을 넘는 것은 반 줄까지 허용 */
          const lh = parseFloat(cs.lineHeight), caretBottom = Math.min(lastLineBottom, tr.bottom);
          return {open: n.open, note_top: r.top, last_line_bottom: lastLineBottom, ta_bottom: tr.bottom, caret_bottom: caretBottom,
                  at_end: ta.selectionStart === ta.value.length,
                  caret_in_ta_view: lastLineBottom <= tr.bottom + lh / 2,
                  scroll_padding: getComputedStyle(document.documentElement).scrollPaddingBottom};
        }"""
        long_text = "# 긴 계획서 [FAKE]\n" + "\n".join(f"{i}번째 줄 [FAKE] 가짜 문장" for i in range(1, 121))
        caret = {}
        for label, want_open in (("typing_collapsed", False), ("paste_open", True)):
            page.evaluate("window.scrollTo(0, 0)")
            page.locator("#sendNote").scroll_into_view_if_needed()
            if page.evaluate("document.getElementById('sendNote').open") != want_open:
                click_summary(page)
                page.wait_for_function("o => document.getElementById('sendNote').open === o", arg=want_open)
            page.fill("#ta", long_text)
            page.evaluate("window.scrollTo(0, 0)")
            page.focus("#ta")
            page.keyboard.press("Control+End")
            if want_open:
                page.keyboard.insert_text("\n붙여넣은 마지막 줄 [FAKE]")
            else:
                page.keyboard.type("\n마지막 줄 입력")
            page.wait_for_timeout(200)
            caret[label] = page.evaluate(caret_js)
        res["caret"] = caret
        page.evaluate("window.scrollTo(0, 0)")
        page.locator("#sendNote").scroll_into_view_if_needed()
        if page.evaluate("document.getElementById('sendNote').open"):
            click_summary(page)
            page.wait_for_function("document.getElementById('sendNote').open === false")
        page.fill("#ta", "")

        # 3 파일 업로드 모드: 같은 고지와 실행 버튼 아래 위치.
        page.evaluate("window.scrollTo(0, 0)")
        page.click('.seg button[data-mode="file"]')
        page.wait_for_selector("#drop")
        ready()
        m3 = page.evaluate(MEASURE)
        res["file_first"] = m3
        res["file_first_in_viewport"] = _in_viewport(m3)
        res["file_gap_to_button_px"] = round(m3["box"]["y"] - m3["btn"]["bottom"], 1)

        # 4 업로드 파일 미리보기가 길어져도 아래로 내려가 고지를 볼 수 있다.
        page.set_input_files("#fileIn", files=[{"name": "plan.md", "mimeType": "text/markdown",
                                                "buffer": ("# 가짜 계획서\n" + "\n".join(f"{i}번째 줄 [FAKE]" for i in range(1, 60))).encode("utf-8")}])
        page.wait_for_selector(".file .fn")
        ready()
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(100)
        page.locator("#sendNote").scroll_into_view_if_needed()
        m4 = page.evaluate(MEASURE)
        res["file_loaded_first"] = m4
        res["file_loaded_first_in_viewport"] = _in_viewport(m4)
        browser.close()

    external = [u for u in requests if urlparse(u).scheme not in {"data", "blob", "about"}
                and urlparse(u).hostname not in LOCAL_HOSTS]
    res.update({
        "console_errors": console_errors,
        "page_errors": page_errors,
        "failed_requests": failed,
        "requests_total": len(requests),
        "request_paths": sorted({urlparse(u).path for u in requests}),
        "external_requests": external,
    })
    return res


def check(res: dict) -> list[str]:
    bad: list[str] = []
    for key in ("text_first", "text_first_open", "file_first", "file_loaded_first", "text_scrolled"):
        m = res[key]
        if m["spans"] != [SEND_LINE, STORE_LINE]:
            bad.append(f"{key}: 고지 문구 다름 {m['spans']}")
        if m["summary_text"] != SUMMARY or m["label"] != "외부 전송":
            bad.append(f"{key}: 요약·라벨 다름 {m['summary_text']!r} {m['label']!r}")
        if not m["in_card"]:
            bad.append(f"{key}: 입력 카드 밖")
        if not m["visible"] or not m["on_top"]:
            bad.append(f"{key}: 고지가 보이지 않거나 가려짐")
        if m["has_markup_children"] != ["SUMMARY", "SPAN", "SPAN"]:
            bad.append(f"{key}: 고지 구조 다름 {m['has_markup_children']}")
        if key != "text_first_open":  # 기본은 접힘: 한 줄 요약만, 높이 상한
            if m["open"] or any(m["spans_shown"]) or m["summary_lines"] != 1 or m["box"]["h"] > COLLAPSED_MAX_H:
                bad.append(f"{key}: 접힌 고지가 한 줄이 아님 open={m['open']} lines={m['summary_lines']} h={m['box']['h']}")
    mo = res["text_first_open"]
    if not mo["open"] or mo["spans_shown"] != [True, True] or mo["more_text"] != "접기":
        bad.append(f"펼치기: 전문이 안 보임 {mo['spans_shown']} {mo['more_text']}")
    if not res["text_first_reclosed"]:
        bad.append("다시 접기 실패")
    for label, c in res["caret"].items():
        if not (c["at_end"] and c["caret_in_ta_view"]):
            bad.append(f"{label}: 캐럿이 글 끝에 있지 않음 {c}")
        if c["caret_bottom"] > c["note_top"]:
            bad.append(f"{label}: 방금 친 줄이 고지 밑에 가려짐 {c}")
    if res["caret"]["paste_open"]["open"] is not True or res["caret"]["typing_collapsed"]["open"] is not False:
        bad.append("캐럿 검사의 접힘·펼침 상태가 다름")
    if res["text_first"]["mode"] != "text" or res["file_first"]["mode"] != "file":
        bad.append("모드 전환 확인 실패")
    for key in ("text_first_in_viewport", "text_first_open_in_viewport", "file_first_in_viewport",
                "file_loaded_first_in_viewport"):
        if not res[key]:
            bad.append(f"{key}: 첫 화면(1440×900) 밖")
    for key in ("text_first", "text_first_open", "file_first", "file_loaded_first"):
        if res[key]["box"]["y"] < res[key]["btn"]["bottom"]:
            bad.append(f"{key}: 고지가 실행 버튼 위에 겹침")
    if not (0 <= res["text_gap_to_button_px"] <= NEAR_PX):
        bad.append(f"직접 입력: 고지~실행 버튼 거리 {res['text_gap_to_button_px']}px > {NEAR_PX}")
    if not (0 <= res["file_gap_to_button_px"] <= NEAR_PX):
        bad.append(f"업로드: 고지~실행 버튼 거리 {res['file_gap_to_button_px']}px > {NEAR_PX}")
    for key in ("console_errors", "page_errors", "failed_requests", "external_requests"):
        if res[key]:
            bad.append(f"{key}: {res[key]}")
    return bad


def run(port: int, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    proc = start_server(port)
    try:
        return shoot(f"http://127.0.0.1:{port}", out)
    finally:
        stop_server(proc, port)


def test_notice_visible_first_screen() -> None:
    port = int(os.getenv("NEUMANN_UI_PORT", DEFAULT_PORT))
    res = run(port, OUT)
    bad = check(res)
    assert not bad, json.dumps({"bad": bad, "res": res}, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    r = run(a.port, a.out)
    problems = check(r)
    print(json.dumps({"ok": not problems, "bad": problems, **r}, ensure_ascii=False, indent=2))
    sys.exit(1 if problems else 0)
