"""FIN-UI v2 목업(?mock=final) 단계 전환형 흐름 Playwright 검사: 입력(예시·업로드·한글 문구·개발자 문구 없음) → 분석(WAIT-UX 모듈 또는 타임라인)
→ 채택(기본 채택 토글·근거 칩→발췌·제안 미리보기·주 버튼 하나) → 수정 계획서(문서 한 장·여백 번호 팝오버·제자리 편집·되돌리기·주 버튼 하나)
→ 최종 점검(항목 켜짐·도구 배지·자동 수정 + 되돌리기) → 완성(문서 뷰·한 줄 통계·.md) → 스테퍼로 되돌아가기 → 390·768·1440 가로 넘침 0 · 콘솔/페이지 오류 0 · 서버 API·외부 요청 0.

    NEUMANN_UI_TESTS=1 NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4/test_fin_ui.py -q -s
    NEUMANN_LLM_PROVIDER=mock python tests/e4/test_fin_ui.py [--port 8174] [--out docs/reports]

- 기본 pytest(verify)에서는 건너뛴다(브라우저·서버 필요). ``NEUMANN_UI_TESTS=1``일 때만 돈다.
- 서버(uvicorn)는 하위 프로세스로 띄우고 끝나면 끈다. 포트 기본 8174(8010·8020·8099 금지, 8171·8172는 대표가 보는 목업 서버). 서버에 ``OPENAI_API_KEY``를 넘기지 않는다.
- 목업은 서버 API를 부르지 않는다: ``/premortem/`` · ``/upload`` 요청이 하나라도 있으면 실패. 외부 도메인 요청도 0이어야 한다.
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

PREFIX = "FIN-UI"
DEFAULT_PORT = 8174
FORBIDDEN_PORTS = {8010, 8020, 8099, 8171, 8172}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
INPUT_READY = "document.body.dataset.view === 'input' && document.body.dataset.ready === '1'"
DEV_WORDS = ("v0.0.1", "fixture", "/templates", "chars", "Pre-mortem 실행", "300자 기준 충족", "목업에는", "RESEARCH PRE-MORTEM")

pytestmark = pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="NEUMANN_UI_TESTS=1일 때만(브라우저·서버 필요)")


def no_hscroll(pg) -> dict:
    return pg.evaluate("() => ({sw: document.documentElement.scrollWidth, iw: document.documentElement.clientWidth})")


def shoot(base: str, out: Path, prefix: str = PREFIX) -> dict:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    r: dict = {"shots": [], "console_errors": [], "page_errors": [], "api_requests": [], "external_requests": [], "requests_total": 0}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="ko-KR", accept_downloads=True)
        pg = ctx.new_page()
        pg.on("console", lambda m: r["console_errors"].append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: r["page_errors"].append(str(e)))

        def on_request(q):
            r["requests_total"] += 1
            u = urlparse(q.url)
            if "/premortem/" in u.path or "/upload" in u.path:
                r["api_requests"].append(q.url)
            if u.scheme not in {"data", "blob", "about"} and u.hostname not in LOCAL_HOSTS:
                r["external_requests"].append(q.url)
        pg.on("request", on_request)

        def snap(name: str, full: bool = False) -> None:
            p = out / f"{prefix}_{name}.png"
            pg.screenshot(path=str(p), full_page=full)
            r["shots"].append(p.name)

        def body_text() -> str:
            return pg.evaluate("document.body.innerText")

        # 1) 입력
        pg.goto(base + "/?mock=final", wait_until="networkidle")
        pg.wait_for_function(INPUT_READY)
        pg.wait_for_selector("#finSamples")
        txt = body_text()
        r["input"] = {"view": pg.evaluate("document.body.dataset.view"), "stepper": pg.locator("#finStepper .fs").count(), "cur": pg.inner_text("#finStepper .fs.cur"),
                      "chip": pg.inner_text("#finMockChip"), "old_nav_visible": pg.evaluate("getComputedStyle(document.getElementById('steps')).display !== 'none'"),
                      "samples": pg.locator("#finSamples .smp").count(), "btn": pg.inner_text("#btnStart"), "cnt": pg.inner_text("#cnt"), "note": pg.inner_text("#finNote"),
                      "dev_words": [w for w in DEV_WORDS if w in txt], "quote_count": txt.count("Probabilistic Logics"), "mockbar": pg.locator("#rvMockBar").count()}
        snap("1440_1_input")
        pg.click("[data-mode='file']")
        pg.wait_for_selector("#drop")
        r["upload"] = {"drop": pg.inner_text("#drop"), "accept": pg.evaluate("document.getElementById('fileIn').accept")}
        pg.click("[data-mode='text']")
        pg.wait_for_selector("#ta")
        pg.fill("#ta", "짧은 입력")
        r["guide_short"] = pg.inner_text("#finGuide")
        pg.click("[data-finsample='battery']")
        pg.wait_for_function("document.getElementById('ta') && document.getElementById('ta').value.length > 1000")
        # 2) 분석(WAIT-UX 모듈이 있으면 #waitux, 없으면 타임라인)
        pg.click("#btnStart")
        pg.wait_for_function("document.body.dataset.view === 'job'")
        pg.wait_for_timeout(1400)
        r["job"] = {"waitux": pg.locator("#waitux").count(), "cur": pg.inner_text("#finStepper .fs.cur"), "wait": (pg.locator("#jobWait").inner_text() if pg.locator("#jobWait").count() else ""), "text_has_mock": "목업" in body_text() or "mock" in body_text()}
        snap("1440_2_job")
        # 3) 채택
        pg.wait_for_function("document.body.dataset.view === 'adopt' && document.body.dataset.ready === '1'", timeout=30_000)
        r["adopt"] = pg.evaluate("""() => ({cards: document.querySelectorAll('#faList .fa-card').length, on: document.querySelectorAll('[data-fatoggle]:checked').length,
            chips: document.querySelectorAll('.fa-chip').length, previews: document.querySelectorAll('.fa-prev').length, btn: document.getElementById('faNext').innerText,
            primary_buttons: document.querySelectorAll('#app .btn.dark').length, more_open: document.querySelector('.fa-more').open, focus: document.activeElement && document.activeElement.id,
            scroll: window.scrollY, cur: document.querySelector('#finStepper .fs.cur').innerText})""")
        snap("1440_3_adopt", full=True)
        pg.click(".fa-chip >> nth=0")
        r["chip"] = pg.evaluate("() => { const c = document.querySelector('.fa-chip'); const x = document.getElementById(c.getAttribute('aria-controls')); return {expanded: c.getAttribute('aria-expanded'), visible: !x.hidden, quote: x.innerText.slice(0, 60)}; }")
        pg.click("[data-fatoggle='2']")
        r["toggle_off"] = pg.evaluate("() => ({btn: document.getElementById('faNext').innerText, off: document.querySelectorAll('.fa-card.off').length})")
        pg.click("[data-fatoggle='2']")
        r["toggle_on"] = pg.inner_text("#faNext")
        # 4) 수정 계획서
        pg.click("#faNext")
        pg.wait_for_function("document.body.dataset.view === 'draft' && document.getElementById('fdDoc')", timeout=20_000)
        r["draft"] = pg.evaluate("""() => ({marks: document.querySelectorAll('.fd-mark').length, chg: document.querySelectorAll('.fd-p.chg').length, paras: document.querySelectorAll('#fdDoc .fd-p').length,
            status: document.getElementById('fdStatus').innerText, width: document.getElementById('fdDoc').getBoundingClientRect().width, primary: document.querySelectorAll('#app .btn.dark').length,
            btn: document.getElementById('fdNext').innerText, ph: document.querySelectorAll('#fdDoc mark.ph').length, conflicts: window.NeumannRevise.assembleLocal().conflicts.length, scroll: window.scrollY})""")
        snap("1440_4_draft", full=True)
        pg.click(".fd-mark >> nth=0")
        pg.wait_for_selector("#fdPop:not([hidden])")
        r["pop"] = pg.evaluate("() => ({text: document.getElementById('fdPop').innerText.slice(0, 200), has_orig: document.getElementById('fdPop').innerText.includes('원문'), has_ev: !!document.querySelector('#fdPop .ev'), focus_in: !!(document.activeElement && document.activeElement.closest('#fdPop'))})")
        snap("1440_4_popover")
        pg.keyboard.press("Escape")
        r["pop_closed"] = pg.evaluate("document.getElementById('fdPop').hidden")
        # 제자리 편집
        pg.click("#fdDoc .fd-p:not(.chg) p >> nth=1")
        pg.wait_for_selector("#fdDoc textarea.fd-ta")
        r["edit"] = {"editing": "편집 중" in pg.inner_text("#fdStatus"), "ta_h": pg.evaluate("document.querySelector('#fdDoc textarea.fd-ta').offsetHeight")}
        pg.fill("#fdDoc textarea.fd-ta", "연구자가 제자리에서 고친 문장이다.")
        pg.keyboard.press("Control+Enter")
        pg.wait_for_function("!document.querySelector('#fdDoc textarea.fd-ta')")
        r["after_edit"] = pg.evaluate("""() => ({has: document.getElementById('fdDoc').innerText.includes('연구자가 제자리에서 고친 문장이다.'), chg: document.querySelectorAll('.fd-p.chg').length, undo: document.getElementById('fdUndo').innerText, status: document.getElementById('fdStatus').innerText})""")
        pg.click("#fdUndo")
        pg.wait_for_timeout(200)
        r["undone"] = pg.evaluate("!document.getElementById('fdDoc').innerText.includes('연구자가 제자리에서 고친 문장이다.')")
        # 되돌리기(팝오버)
        pg.click(".fd-mark >> nth=0")
        pg.wait_for_selector("#fdPop:not([hidden])")
        marks_before = r["draft"]["marks"]
        pg.click("[data-fdrevert]")
        pg.wait_for_timeout(200)
        r["reverted"] = {"marks": pg.locator(".fd-mark").count(), "before": marks_before}
        pg.click("#fdUndo")
        pg.wait_for_timeout(200)
        r["revert_undone"] = pg.locator(".fd-mark").count()
        # 5) 최종 점검
        pg.click("#fdNext")
        pg.wait_for_function("document.body.dataset.view === 'check'")
        pg.wait_for_function("document.querySelectorAll('.fc-row.pass, .fc-row.fail').length >= 4", timeout=15_000)
        r["check_mid"] = pg.evaluate("() => ({rows: document.querySelectorAll('.fc-row').length, done: document.querySelectorAll('.fc-row.pass, .fc-row.fail').length, run: document.querySelectorAll('.fc-row.run').length, badges: document.getElementById('fcBadges').innerText, btn_disabled: document.getElementById('fcNext').disabled, scroll: window.scrollY})")
        snap("1440_5_check_running")
        pg.wait_for_function("document.getElementById('fcNext') && !document.getElementById('fcNext').disabled", timeout=30_000)
        r["check"] = pg.evaluate("""() => { const C = window.NeumannFinal.check(); return {rows: document.querySelectorAll('.fc-row').length, pass: document.querySelectorAll('.fc-row.pass').length, fail: document.querySelectorAll('.fc-row.fail').length, skip: document.querySelectorAll('.fc-row.skip').length,
            fixes: document.querySelectorAll('.fc-fix').length, applied: C.res.counts.applied, rejected: C.res.counts.rejected, badges: document.getElementById('fcBadges').innerText, undo_links: document.querySelectorAll('[data-fcundo]').length,
            title: document.getElementById('fcTitle').innerText, status: C.res.status, tools: Array.from(new Set(C.log.map(x => x.tool))).sort(), primary: document.querySelectorAll('#app .btn.dark').length, state: document.getElementById('fin-checkState').innerText}; }""")
        snap("1440_5_check", full=True)
        pg.click("[data-fcundo] >> nth=0")
        pg.wait_for_timeout(150)
        r["fix_undo"] = pg.evaluate("() => ({rev: document.querySelectorAll('.fc-fix.rev').length, applied: window.NeumannFinal.check().res.counts.applied, link: document.querySelector('[data-fcundo]').innerText})")
        pg.click("[data-fcundo] >> nth=0")
        pg.wait_for_timeout(150)
        r["fix_redo"] = pg.evaluate("window.NeumannFinal.check().res.counts.applied")
        pg.click(".fc-row >> nth=2")
        r["row_detail"] = pg.evaluate("() => { const row = document.querySelectorAll('.fc-row')[2]; return {expanded: row.getAttribute('aria-expanded'), detail: row.querySelector('.dt').innerText.slice(0, 80)}; }")
        # 6) 완성
        pg.click("#fcNext")
        pg.wait_for_function("document.body.dataset.view === 'done'")
        r["done"] = pg.evaluate("""() => ({stat: document.querySelector('.fz-stat').innerText, note: document.querySelector('.fz-note').innerText, paras: document.querySelectorAll('#fzDoc .fd-p').length, fixes: document.querySelectorAll('#fzDoc .fd-p.fix').length,
            ph: document.querySelectorAll('#fzDoc mark.ph').length, primary: document.querySelectorAll('#app .btn.dark').length, cur: document.querySelector('#finStepper .fs.cur').innerText, done_steps: document.querySelectorAll('#finStepper .fs.done').length, scroll: window.scrollY,
            has_fix_text: document.getElementById('fzDoc').innerText.includes('[확인 필요: 항목 합')})""")
        snap("1440_6_done", full=True)
        with pg.expect_download() as dl:
            pg.click("#fzMd")
        md_text = Path(dl.value.path()).read_text(encoding="utf-8")
        r["md"] = {"name": dl.value.suggested_filename, "has_fix": "[확인 필요: 항목 합" in md_text, "has_summary": "## 최종 점검 요약" in md_text, "has_fixes": "## 자동 수정" in md_text, "has_log": "## 도구 호출 기록" in md_text, "kst": "KST" in md_text, "lines": len(md_text.splitlines())}
        pg.click("#fzDocx")
        pg.wait_for_timeout(200)
        r["docx_msg"] = pg.inner_text("#toast")
        # 스테퍼로 되돌아가기(채택) → 결정 변경 → 최종 점검 무효화 → 다시 수정 계획서로
        pg.click("[data-finstep='adopt']")
        pg.wait_for_function("document.body.dataset.view === 'adopt'")
        r["back"] = {"scroll": pg.evaluate("window.scrollY"), "cur": pg.inner_text("#finStepper .fs.cur"), "on": pg.locator("[data-fatoggle]:checked").count()}
        pg.click("[data-fatoggle='2']")
        pg.wait_for_timeout(200)
        r["invalidated"] = pg.evaluate("window.NeumannFinal.check().status")
        # 390: 입력·채택·수정 계획서·점검·완성 넘침 0(?at= 바로가기)
        narrow = {}
        pg.set_viewport_size({"width": 390, "height": 844})
        for at in ("input", "adopt", "draft", "done"):
            pg.goto(base + "/?mock=final&at=" + at, wait_until="networkidle")
            if at == "done":
                pg.wait_for_function("document.body.dataset.view === 'done'", timeout=30_000)
            elif at != "input":
                pg.wait_for_function("document.body.dataset.view === '%s' && document.body.dataset.ready === '1'" % at, timeout=20_000)
            pg.wait_for_timeout(300)
            narrow[at + "_390"] = no_hscroll(pg)
            if at == "draft":
                snap("390_4_draft")
        pg.set_viewport_size({"width": 375, "height": 812})
        pg.goto(base + "/?mock=final", wait_until="networkidle")
        pg.wait_for_function(INPUT_READY)
        pg.wait_for_timeout(300)
        narrow["input_375"] = dict(no_hscroll(pg), top_h=pg.evaluate("document.querySelector('.top').offsetHeight"), btn_visible=pg.evaluate("(() => { const b = document.getElementById('btnStart'); b.scrollIntoView(); const r = b.getBoundingClientRect(); return r.width > 0 && r.top >= 0 && r.bottom <= window.innerHeight; })()"))
        pg.set_viewport_size({"width": 768, "height": 1024})
        for at in ("adopt", "draft"):
            pg.goto(base + "/?mock=final&at=" + at, wait_until="networkidle")
            pg.wait_for_function("document.body.dataset.view === '%s' && document.body.dataset.ready === '1'" % at, timeout=20_000)
            pg.wait_for_timeout(300)
            narrow[at + "_768"] = no_hscroll(pg)
        r["narrow"] = narrow
        # QA-2 Q2-2: 1152px(배율 125%)에서 기존 리포트 화면의 근거 서랍이 scrim 위에 있고 클릭된다
        pg.set_viewport_size({"width": 1152, "height": 800})
        pg.goto(base + "/?mock=final&at=adopt", wait_until="networkidle")
        pg.wait_for_function("document.body.dataset.view === 'adopt' && document.body.dataset.ready === '1'", timeout=20_000)
        pg.evaluate("window.NeumannUI.go(2)")
        pg.wait_for_function("document.body.dataset.view === 'report' && document.body.dataset.ready === '1'")
        pg.click("#s-cards .cite[data-ev] >> nth=0")
        pg.wait_for_timeout(400)
        r["drawer_1152"] = pg.evaluate("""() => { const p = document.querySelector('.panel'); const rp = p.getBoundingClientRect(); const x = rp.left + 40, y = rp.top + 60; const hit = document.elementFromPoint(x, y); return {open: document.body.classList.contains('popen'), visible: getComputedStyle(p).visibility, hit_in_panel: !!(hit && hit.closest('.panel')), left: Math.round(rp.left), width: Math.round(rp.width)}; }""")
        ctx.close()
        browser.close()
    return r


def check(r: dict) -> list[str]:
    """완료 기준 판정. 빈 목록이면 통과."""
    bad: list[str] = []
    if r["console_errors"] or r["page_errors"]:
        bad.append(f"콘솔/페이지 오류: {r['console_errors'][:3]} {r['page_errors'][:3]}")
    if r["api_requests"] or r["external_requests"]:
        bad.append(f"목업 서버 API·외부 요청: {r['api_requests'][:3]} {r['external_requests'][:3]}")
    i = r["input"]
    if i["view"] != "input" or i["stepper"] != 6 or "입력" not in i["cur"] or i["old_nav_visible"] or i["mockbar"] or i["samples"] != 3 or i["btn"] != "분석 시작" or not i["cnt"].endswith("자") or "mock" not in i["chip"] or "외부로 전송하지 않" not in i["note"]:
        bad.append(f"입력 화면 이상: {i}")
    if i["dev_words"] or i["quote_count"] != 1:
        bad.append(f"개발자 문구·중복 인용: {i['dev_words']} quote={i['quote_count']}")
    if "HWPX" not in r["upload"]["drop"] or ".hwpx" not in r["upload"]["accept"] or "300자 이상" not in r["guide_short"]:
        bad.append(f"업로드·안내 이상: {r['upload']} {r['guide_short']!r}")
    if "분석" not in r["job"]["cur"] or not r["job"]["text_has_mock"]:
        bad.append(f"분석 화면 이상: {r['job']}")
    a = r["adopt"]
    if a["cards"] != 2 or a["on"] != 2 or a["chips"] < 3 or a["previews"] != 2 or "채택 2건" not in a["btn"] or a["primary_buttons"] != 1 or a["more_open"] or a["scroll"] != 0 or "채택" not in a["cur"]:
        bad.append(f"채택 화면 이상: {a}")
    if r["chip"]["expanded"] != "true" or not r["chip"]["visible"] or "“" not in r["chip"]["quote"]:
        bad.append(f"근거 칩 이상: {r['chip']}")
    if "채택 1건" not in r["toggle_off"]["btn"] or r["toggle_off"]["off"] != 1 or "채택 2건" not in r["toggle_on"]:
        bad.append(f"채택 토글 이상: {r['toggle_off']} {r['toggle_on']}")
    d = r["draft"]
    if d["marks"] < 3 or d["marks"] != d["chg"] or d["paras"] < 20 or d["width"] > 780 or d["primary"] != 1 or "확정하고 최종 점검" != d["btn"] or d["conflicts"] != 0 or d["scroll"] != 0 or "바뀐 문장" not in d["status"]:
        bad.append(f"수정 계획서 화면 이상: {d}")
    if not r["pop"]["has_orig"] or not r["pop"]["has_ev"] or not r["pop"]["focus_in"] or not r["pop_closed"]:
        bad.append(f"팝오버 이상: {r['pop']} closed={r['pop_closed']}")
    if not r["edit"]["editing"] or r["edit"]["ta_h"] < 20 or not r["after_edit"]["has"] or r["after_edit"]["chg"] != d["chg"] + 1 or "(1)" not in r["after_edit"]["undo"] or not r["undone"]:
        bad.append(f"제자리 편집·되돌리기 이상: {r['edit']} {r['after_edit']} undone={r['undone']}")
    if r["reverted"]["marks"] != r["reverted"]["before"] - 1 or r["revert_undone"] != r["reverted"]["before"]:
        bad.append(f"팝오버 되돌리기 이상: {r['reverted']} {r['revert_undone']}")
    m = r["check_mid"]
    if m["rows"] < 10 or m["done"] < 4 or m["btn_disabled"] is not True or m["scroll"] != 0:
        bad.append(f"최종 점검 진행 이상: {m}")
    c = r["check"]
    if c["pass"] + c["fail"] + c["skip"] != c["rows"] or c["fixes"] != c["applied"] + c["rejected"] or c["applied"] < 5 or c["rejected"] < 1 or c["undo_links"] != c["applied"] or c["primary"] != 1 or "Z3" not in c["badges"] or "Pint" not in c["badges"] or "NetworkX" not in c["badges"] or c["status"] != "partial" or "완료" not in c["state"]:
        bad.append(f"최종 점검 결과 이상: {c}")
    if not {"calc", "z3", "pint", "networkx", "records", "sandbox"} <= set(c["tools"]):
        bad.append(f"도구 종류 부족: {c['tools']}")
    if r["fix_undo"]["rev"] != 1 or r["fix_undo"]["applied"] != c["applied"] - 1 or "다시 적용" not in r["fix_undo"]["link"] or r["fix_redo"] != c["applied"]:
        bad.append(f"자동 수정 되돌리기 이상: {r['fix_undo']} {r['fix_redo']}")
    if r["row_detail"]["expanded"] != "true" or "입력" not in r["row_detail"]["detail"]:
        bad.append(f"항목 상세 이상: {r['row_detail']}")
    z = r["done"]
    if "자동 수정" not in z["stat"] or z["fixes"] != c["applied"] or not z["has_fix_text"] or z["primary"] != 1 or "완성" not in z["cur"] or z["done_steps"] != 5 or z["scroll"] != 0 or "KST" not in z["note"]:
        bad.append(f"완성 화면 이상: {z}")
    md = r["md"]
    if not md["name"].endswith("_final.md") or not all(md[k] for k in ("has_fix", "has_summary", "has_fixes", "has_log", "kst")):
        bad.append(f".md 이상: {md}")
    if "docx" not in r["docx_msg"].lower():
        bad.append(f".docx 안내 이상: {r['docx_msg']!r}")
    if r["back"]["scroll"] != 0 or "채택" not in r["back"]["cur"] or r["back"]["on"] != 2 or r["invalidated"] != "idle":
        bad.append(f"되돌아가기·무효화 이상: {r['back']} {r['invalidated']}")
    for k, v2 in r["narrow"].items():
        if v2["sw"] > v2["iw"]:
            bad.append(f"{k} 가로 스크롤: {v2}")
    if r["narrow"]["input_375"]["top_h"] > 200 or not r["narrow"]["input_375"]["btn_visible"]:
        bad.append(f"375 헤더·실행 버튼 이상: {r['narrow']['input_375']}")
    dr = r["drawer_1152"]
    if not dr["open"] or dr["visible"] != "visible" or not dr["hit_in_panel"]:
        bad.append(f"1152 근거 서랍 이상(QA-2 Q2-2): {dr}")
    return bad


def _run(port: int, out: Path) -> dict:
    from tests.e4.ui_shots import start_server, stop_server

    if port in FORBIDDEN_PORTS:
        raise SystemExit(f"포트 {port}는 쓰지 않는다")
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("NEUMANN_LIVE_LLM_OK", None)
    os.environ["NEUMANN_LLM_PROVIDER"] = "mock"
    proc = start_server(port)
    try:
        return shoot(f"http://127.0.0.1:{port}", out)
    finally:
        stop_server(proc, port)


def test_fin_ui(tmp_path):
    r = _run(int(os.getenv("NEUMANN_UI_SHOTS_PORT", DEFAULT_PORT)), tmp_path / "shots")
    problems = check(r)
    print("problems", problems)
    assert not problems, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "reports")
    args = ap.parse_args()
    r = _run(args.port, args.out)
    problems = check(r)
    print("problems", problems)
    for k in ("input", "job", "adopt", "chip", "draft", "pop", "edit", "after_edit", "reverted", "check_mid", "check", "fix_undo", "row_detail", "done", "md", "back", "invalidated", "narrow", "drawer_1152"):
        print(f"  {k}: {json.dumps(r[k], ensure_ascii=False)[:420]}")
    print("  console_errors", r["console_errors"], "· page_errors", r["page_errors"], "· api", r["api_requests"], "· external", r["external_requests"], "· requests", r["requests_total"])
    print("  shots", r["shots"])
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
