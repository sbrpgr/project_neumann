"""FIN-UI 목업(?mock=final) 최종 형태 흐름 Playwright 검사: ① 입력(샘플 갤러리·300자 안내·PDF/DOCX/HWPX) → ② 가짜 분석 진행 → 위험카드 →
③ 재탄생(V) → ④ "수정 확정·검증" 한 번 → ⑤ 점검 진행(단계·도구 호출 로그 실시간) → ⑥ 최종 초안(교정 표시·도구 근거 배지·해결/미해결/확인 필요·.md)
→ ⑦ 전후 비교 → 배지→기록 점프 · 키보드(Tab·Enter) · 결정 변경 시 무효화 → 390·768·1440 가로 넘침 0 · 콘솔/페이지 오류 0 · 서버 API·외부 요청 0.

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
REPORT_READY = "document.body.dataset.view === 'report' && document.body.dataset.ready === '1' && !!document.querySelector('#s-cards .rc')"
REVISE_READY = "document.body.dataset.view === 'revise' && document.body.dataset.ready === '1'"
FINAL_DONE = "document.body.dataset.view === 'final' && document.getElementById('finState') && document.getElementById('finState').textContent === 'complete'"

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

        def snap(name: str, full: bool = False, page=None) -> None:
            p = out / f"{prefix}_{name}.png"
            (page or pg).screenshot(path=str(p), full_page=full)
            r["shots"].append(p.name)

        # ① 입력: 목업은 입력 화면에서 시작. 샘플 갤러리·300자 안내·업로드 안내(PDF·DOCX·HWPX)
        pg.goto(base + "/?mock=final", wait_until="networkidle")
        pg.wait_for_function(INPUT_READY)
        pg.wait_for_selector("#finSamples")
        r["input"] = pg.evaluate("() => ({view: document.body.dataset.view, bar: document.getElementById('rvMockBar').innerText, samples: document.querySelectorAll('#finSamples .smp').length, guide: document.getElementById('finGuide').innerText, ta: document.getElementById('ta').value.length, jumps: document.querySelectorAll('[data-mockat]').length})")
        snap("1440_1_input", full=True)
        pg.click("[data-mode='file']")
        pg.wait_for_selector("#drop")
        r["upload"] = pg.evaluate("() => ({drop: document.getElementById('drop').innerText, accept: document.getElementById('fileIn').accept})")
        pg.click("[data-mode='text']")
        pg.wait_for_selector("#ta")
        pg.fill("#ta", "짧은 입력")
        r["guide_short"] = pg.inner_text("#finGuide")
        pg.click("[data-finsample='battery']")
        pg.wait_for_function("document.getElementById('ta') && document.getElementById('ta').value.length > 1000")
        r["sample_loaded"] = pg.evaluate("document.getElementById('ta').value.length")
        # ② 가짜 분석 진행(서버 호출 없음) → 리포트
        pg.click("#btnStart")
        pg.wait_for_function("document.body.dataset.view === 'job'")
        pg.wait_for_function("document.querySelectorAll('.tn.run, .tn.done').length >= 2", timeout=10_000)
        r["job"] = pg.evaluate("() => ({state: document.getElementById('jobState').innerText, nodes: document.querySelectorAll('.tn').length, wait: (document.getElementById('jobWait') || {}).innerText || ''})")
        snap("1440_2_job")
        pg.wait_for_function(REPORT_READY, timeout=30_000)
        pg.wait_for_selector("#s-cards .rc [data-rv]")
        r["report"] = pg.evaluate("() => ({cards: document.querySelectorAll('#s-cards .rc').length, status1: document.querySelector('#s-cards .rc[data-card=\"1\"] .rvst').innerText, steps: document.getElementById('steps').innerText.replace(/\\n/g, ' '), plan_lines: window.NeumannUI.D().plan.lines.length})")
        snap("1440_2_report", full=True)
        # ③ 재탄생(V)
        pg.click("#stpRevise")
        pg.wait_for_function(REVISE_READY)
        pg.wait_for_selector("#rvFinalize")
        r["revise"] = pg.evaluate("() => ({sections: document.querySelectorAll('.rvsec').length, sum: document.getElementById('rvSum').innerText, fin_disabled: document.getElementById('rvFinalize').disabled, vi_disabled: document.getElementById('stpFinal').disabled})")
        snap("1440_3_revise", full=True)
        pg.click("#rvOpen")
        pg.wait_for_selector("#rvViewer.on")
        r["viewer"] = {"fin_btn": pg.locator("#rvFinalize2").count(), "conflict": pg.locator("#rvConfBanner").count()}
        snap("1440_3_viewer")
        # ④ 한 번의 버튼(뷰어 바) → ⑤ 진행 화면
        pg.click("#rvFinalize2")
        pg.wait_for_function("document.body.dataset.view === 'final' && document.body.dataset.ready === '1'")
        r["final_focus"] = pg.evaluate("document.activeElement && document.activeElement.id")
        pg.wait_for_function("document.querySelectorAll('#finLog .row').length >= 6", timeout=15_000)
        r["run_mid"] = pg.evaluate("() => ({rows: document.querySelectorAll('#finLog .row').length, state: document.getElementById('finState').innerText, running: document.querySelectorAll('#finStages .tn.run').length, done: document.querySelectorAll('#finStages .tn.done').length, live: document.getElementById('finLog').getAttribute('aria-live'), role: document.getElementById('finLog').getAttribute('role'), row1: document.querySelector('#finLog .row').innerText})")
        snap("1440_5_running")
        # ⑥ 최종 초안
        pg.wait_for_function(FINAL_DONE, timeout=30_000)
        pg.wait_for_selector("#fin-draft")
        r["done"] = pg.evaluate("""() => { const st = window.NeumannFinal.state(); return {rows: document.querySelectorAll('#finLog .row').length, sum: document.getElementById('finSum').innerText.replace(/\\n/g, ' '),
          fix_paras: document.querySelectorAll('#finPaper p.fix').length, fixboxes: document.querySelectorAll('#finPaper .finfix').length, badges: document.querySelectorAll('#finPaper .fintool').length,
          issues: document.querySelectorAll('#fin-draft .fin-issue').length, chips: document.querySelectorAll('#finPaper .rvph').length, corrections: document.querySelectorAll('#fin-draft .fincorr .finfix').length,
          rejected: document.querySelectorAll('#fin-draft .fincorr .finfix.rej').length, steps: document.getElementById('steps').innerText.replace(/\\n/g, ' '), focus: document.activeElement && document.activeElement.id,
          counts: st.res.counts, status: st.res.status, final_has_ph: st.res.final_text.includes('[확인 필요: 항목 합'), input_has_orig: st.res.input_text.includes('총 예산은 1억 2,000만원이다'),
          log_hidden: document.getElementById('finLog').hidden, tools: Array.from(new Set(st.log.map(x => x.tool))).sort()}; }""")
        pg.evaluate("window.scrollTo(0, 0)")
        snap("1440_6_final_top")
        pg.evaluate("document.getElementById('fin-draft').scrollIntoView()")
        pg.wait_for_timeout(250)
        snap("1440_6_draft")
        pg.click("[data-finview='clean']")
        r["clean"] = pg.evaluate("() => ({clean: document.getElementById('finPaper').classList.contains('clean'), pressed: document.querySelector('[data-finview=\"clean\"]').getAttribute('aria-pressed'), fixbox_visible: getComputedStyle(document.querySelector('#finPaper .finfix')).display})")
        pg.click("[data-finview='marks']")
        # ⑦ 전후 비교
        pg.evaluate("document.getElementById('fin-compare').scrollIntoView()")
        pg.wait_for_timeout(250)
        r["compare"] = pg.evaluate("() => ({tiles: document.querySelectorAll('#finCmp .k').length, text: document.getElementById('finCmp').innerText.replace(/\\n/g, ' '), rows: document.querySelectorAll('#fin-compare .fintbl tbody tr').length})")
        snap("1440_7_compare")
        snap("1440_final_full", full=True)
        # 도구 근거 배지 → 점검 기록 점프(접힌 기록 펼침·강조·초점)
        pg.click("#finPaper .finfix [data-fincheck] >> nth=0")
        pg.wait_for_timeout(400)
        r["jump"] = pg.evaluate("() => ({hl: document.querySelectorAll('#finLog .row.hl').length, open: !document.getElementById('finLog').hidden, focus_in_log: !!(document.activeElement && document.activeElement.closest('#finLog')), expanded: document.getElementById('finLogToggle').getAttribute('aria-expanded')})")
        # 키보드: 교정 문단 Tab 초점 → Enter → 기록 점프
        pg.focus("#finPaper p.fix >> nth=1")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(300)
        r["kbd"] = pg.evaluate("() => ({hl_text: (document.querySelector('#finLog .row.hl') || {}).innerText || '', tabindex: document.querySelector('#finPaper p.fix').tabIndex})")
        # .md 내려받기
        with pg.expect_download() as dl:
            pg.click("#finMd")
        md_text = Path(dl.value.path()).read_text(encoding="utf-8")
        r["md"] = {"name": dl.value.suggested_filename, "has_fix": "[확인 필요: 항목 합" in md_text, "has_summary": "## 최종 점검 요약" in md_text, "has_corr": "## 교정 목록" in md_text, "has_log": "## 도구 호출 기록" in md_text, "rejected_absent": "결과는 논문으로 발표한다" not in md_text.split("## 교정 목록")[0], "lines": len(md_text.splitlines())}
        pg.click("#finDocx")
        pg.wait_for_timeout(200)
        r["docx_msg"] = pg.inner_text("#toast")
        # 무효화: 수정 권고로 돌아가 결정을 바꾸면 VI 결과는 사라진다
        pg.click("#finBack")
        pg.wait_for_function(REVISE_READY)
        pg.click("#rv-1 .rdec[data-d='reject'] >> nth=0")
        pg.wait_for_timeout(200)
        r["invalidate"] = pg.evaluate("() => ({status: window.NeumannFinal.state().status, vi: document.getElementById('stpFinal').innerText, vi_disabled: document.getElementById('stpFinal').disabled})")
        # 다시 확정(요약 버튼) → 390에서 진행·초안 → 768 → 1440 넘침 0
        pg.set_viewport_size({"width": 390, "height": 844})
        pg.click("#rvFinalize")
        pg.wait_for_function(FINAL_DONE, timeout=30_000)
        pg.wait_for_timeout(300)
        narrow = {"final_390": no_hscroll(pg)}
        pg.evaluate("window.scrollTo(0, 0)")
        snap("390_5_run")
        pg.evaluate("document.getElementById('fin-draft').scrollIntoView()")
        pg.wait_for_timeout(200)
        snap("390_6_draft")
        pg.set_viewport_size({"width": 768, "height": 1024})
        pg.wait_for_timeout(300)
        narrow["final_768"] = no_hscroll(pg)
        snap("768_6_draft")
        for at in ("input", "report", "revise"):
            pg.goto(base + "/?mock=final&at=" + at, wait_until="networkidle")
            pg.wait_for_timeout(600)
            narrow[at + "_768"] = no_hscroll(pg)
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.wait_for_timeout(300)
            narrow[at + "_390"] = no_hscroll(pg)
            if at == "input":
                snap("390_1_input")
            pg.set_viewport_size({"width": 768, "height": 1024})
        r["narrow"] = narrow
        # 단계 바로가기 ?at=final: 자동으로 ④~⑦까지
        pg.set_viewport_size({"width": 1440, "height": 900})
        pg.goto(base + "/?mock=final&at=final", wait_until="networkidle")
        pg.wait_for_function(FINAL_DONE, timeout=30_000)
        r["jump_final"] = pg.evaluate("document.querySelectorAll('#finLog .row').length")
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
    if i["view"] != "input" or i["samples"] != 3 or "300자" not in i["guide"] or "목업" not in i["bar"] or "가짜 데이터" not in i["bar"] or i["jumps"] < 5 or i["ta"] < 1000:
        bad.append(f"① 입력 화면 이상: {i}")
    if "HWPX" not in r["upload"]["drop"] or ".hwpx" not in r["upload"]["accept"] or "300자 이상" not in r["guide_short"] or r["sample_loaded"] < 1000:
        bad.append(f"① 업로드·안내·샘플 이상: {r['upload']} {r['guide_short']!r} {r['sample_loaded']}")
    if r["job"]["nodes"] < 2 or "목업" not in r["job"]["wait"]:
        bad.append(f"② 진행 화면 이상: {r['job']}")
    if r["report"]["cards"] != 2 or "완료" not in r["report"]["status1"] or "최종 초안" not in r["report"]["steps"] or r["report"]["plan_lines"] < 30:
        bad.append(f"② 리포트 이상: {r['report']}")
    v = r["revise"]
    if v["sections"] != 2 or v["fin_disabled"] or v["vi_disabled"] or "수정 확정·검증" not in v["sum"] or "확인 필요" not in v["sum"]:
        bad.append(f"③·④ 수정 권고 화면 이상: {v}")
    if r["viewer"]["fin_btn"] != 1 or r["viewer"]["conflict"] != 1:
        bad.append(f"③ 뷰어 이상: {r['viewer']}")
    m = r["run_mid"]
    if m["state"] != "running" or m["rows"] < 6 or m["running"] != 1 or m["done"] < 1 or m["live"] != "polite" or m["role"] != "log" or "입력" not in m["row1"] or "결과" not in m["row1"]:
        bad.append(f"⑤ 진행·로그 이상: {m}")
    if r["final_focus"] != "finTitle":
        bad.append(f"⑤ 진입 초점 이상: {r['final_focus']!r}")
    d = r["done"]
    c = d["counts"]
    if d["rows"] < 15 or d["fix_paras"] != c["applied"] or d["fixboxes"] != c["applied"] or d["badges"] < c["applied"] or d["issues"] < 6 or d["corrections"] != c["applied"] + c["rejected"] or d["rejected"] != c["rejected"] or d["rejected"] < 1:
        bad.append(f"⑥ 최종 초안 구성 이상: {d}")
    if not d["final_has_ph"] or not d["input_has_orig"] or d["status"] != "partial" or c["resolved"] < 1 or c["unresolved"] < 1 or c["confirm"] < 3 or not d["log_hidden"] or d["focus"] != "finDraftTitle":
        bad.append(f"⑥ 결과 모델 이상: status={d['status']} counts={c} focus={d['focus']} log_hidden={d['log_hidden']}")
    if not {"calc", "z3", "pint", "networkx", "records", "sandbox"} <= set(d["tools"]):
        bad.append(f"⑤ 도구 종류 부족: {d['tools']}")
    if not r["clean"]["clean"] or r["clean"]["pressed"] != "true" or r["clean"]["fixbox_visible"] != "none":
        bad.append(f"⑥ 깨끗한 원고 보기 이상: {r['clean']}")
    cp = r["compare"]
    if cp["tiles"] != 5 or cp["rows"] < 5 or "위험 해소" not in cp["text"] or "오류 수정" not in cp["text"] or "수정" not in cp["text"]:
        bad.append(f"⑦ 전후 비교 이상: {cp}")
    j = r["jump"]
    if j["hl"] != 1 or not j["open"] or not j["focus_in_log"] or j["expanded"] != "true":
        bad.append(f"배지→기록 점프 이상: {j}")
    if not r["kbd"]["hl_text"] or r["kbd"]["tabindex"] != 0:
        bad.append(f"키보드 접근 이상: {r['kbd']}")
    md = r["md"]
    if not md["name"].endswith("_final.md") or not all(md[k] for k in ("has_fix", "has_summary", "has_corr", "has_log", "rejected_absent")):
        bad.append(f".md 이상: {md}")
    if "docx" not in r["docx_msg"].lower() and ".docx" not in r["docx_msg"]:
        bad.append(f".docx 안내 이상: {r['docx_msg']!r}")
    if r["invalidate"]["status"] != "idle" or r["invalidate"]["vi_disabled"]:
        bad.append(f"무효화 이상: {r['invalidate']}")
    for k, v2 in r["narrow"].items():
        if v2["sw"] > v2["iw"]:
            bad.append(f"{k} 가로 스크롤: {v2}")
    if r["jump_final"] < 15:
        bad.append(f"?at=final 바로가기 이상: {r['jump_final']}")
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
    for k in ("input", "job", "report", "revise", "run_mid", "done", "compare", "jump", "kbd", "md", "invalidate", "narrow"):
        print(f"  {k}: {json.dumps(r[k], ensure_ascii=False)[:400]}")
    print("  console_errors", r["console_errors"], "· page_errors", r["page_errors"], "· api", r["api_requests"], "· external", r["external_requests"], "· requests", r["requests_total"])
    print("  shots", r["shots"])
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
