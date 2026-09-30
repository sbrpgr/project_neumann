"""E4-L1c 화면 확인: 근거 열람 패널 · 평가이력 지도 · 예상 심사평 · 체크리스트 (Playwright 1440×900).

    NEUMANN_UI_SHOTS=1 python -m pytest tests/e4/test_view_shots.py -s      # pytest로
    python tests/e4/test_view_shots.py [--port 8132] [--out docs/reports]  # 직접

- 기본 pytest에서는 건너뛴다(브라우저·서버가 필요). ``NEUMANN_UI_SHOTS=1``일 때만 돈다.
- 서버(uvicorn)는 하위 프로세스로 띄우고 끝나면 반드시 끈다. 포트 기본 8132(8010 금지).
- 화면 데이터: 공용 fixture 결과(가짜) + E3 규칙 경로로 만든 예상 심사평·체크리스트(LLM 호출 없음) +
  fixture 기록(works·reviews·decisions)으로 채운 결정. ``sample=True``라 화면에 샘플 표시가 남는다.
  이 뷰는 ``/premortem/view`` 응답을 가로채 넣는다(서버의 기본 샘플 흐름도 따로 한 번 찍는다).
- XSS: 인용·제목·심사평 문장에 태그를 넣은 뷰를 그려 요소가 만들어지지 않는지 확인한다.
- 콘솔 오류·페이지 오류·실패 요청·외부 도메인 요청이 하나라도 있으면 실패.
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

DEFAULT_PORT = 8132
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
REPORT_READY = ("document.body.dataset.view === 'report' && document.body.dataset.ready === '1' && "
                "!!(document.querySelector('#s-cards .rc') || document.querySelector('#noCards'))")


def rich_view() -> dict:
    """fixture 결과 + 규칙 경로 예상 심사평·체크리스트 + fixture 기록 → ui_view(샘플 표시 유지)."""
    from neumann.analyze.checklist import attach_checklist
    from neumann.analyze.review import attach_expected_review
    from neumann.api.view import RecordLookup, build_ui_view
    from tests.fixtures.loader import load_fixtures

    fx = load_fixtures()
    res = attach_expected_review(fx.premortem_result, None)
    res = attach_checklist(res, fx.premortem_result.plan, None)
    lk = RecordLookup.from_records(fx.works, fx.reviews, fx.decisions, source="fixture_records")
    return build_ui_view(res, filename="plan.md", sample=True, pipeline_state="unavailable", records=lk)


def xss_view() -> dict:
    from neumann.api.view import build_ui_view

    bad = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>'
    res = {
        "status": "ok",
        "plan_stats": {"lines": [{"n": 1, "t": "제목 " + bad, "h": "title"}, {"n": 2, "t": "split " + bad}]},
        "similar_works": [{"work_id": "W1", "title": "T " + bad, "decision": "Reject " + bad,
                           "url": "javascript:alert(1)"}],
        "evidence": [{"excerpt_id": "e1", "work_id": "W1", "text": "quote " + bad, "source_url": "javascript:alert(2)",
                      "start": 0, "end": 5}],
        "risk_cards": [{"card_id": "c1", "risk_code": "R3", "title": "제목 " + bad, "plan_lines": [2],
                        "why_applies": {"text": "why " + bad, "plan_lines": [2]}, "evidence": ["e1"],
                        "works": ["W1"], "generator": "astra", "score": {"total": 0.5}}],
        "expected_review": {"generator": "astra " + bad, "status": "ok",
                            "weakness": [{"t": "문장 " + bad, "c": ["e1"], "plan_lines": [2]}]},
        "checklist": [{"item_id": "C1", "action": "행동 " + bad, "risk_code": "R3", "plan_lines": [2],
                       "evidence": ["e1"], "card_id": "c1", "generator": "rule", "verify": "v " + bad}],
    }
    return build_ui_view(res, records=None)


def shoot(base: str, out: Path, prefix: str = "E4-L1c") -> dict:
    from playwright.sync_api import sync_playwright

    from tests.fixtures.loader import plan_text

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed: list[str] = []
    requests: list[str] = []
    rich = rich_view()
    shots: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="ko-KR")
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}"))

        def run_report(view: dict | None) -> None:
            page.goto(base + "/", wait_until="networkidle")
            page.wait_for_selector('body[data-view="input"][data-ready="1"]')
            if view is not None:
                body = json.dumps(view, ensure_ascii=False)
                page.route("**/premortem/view", lambda route, _req: route.fulfill(
                    status=200, content_type="application/json", body=body))
            page.fill("#ta", plan_text())
            page.click("#btnStart")
            page.wait_for_function(REPORT_READY, timeout=60_000)
            page.evaluate("document.fonts.ready.then(() => true)")
            page.wait_for_load_state("networkidle")
            if view is not None:
                page.unroute("**/premortem/view")

        def snap(name: str) -> None:
            page.wait_for_timeout(250)
            path = out / f"{prefix}_{name}.png"
            page.screenshot(path=str(path))
            shots.append(path.name)

        # 1) 서버 기본 흐름(샘플 응답 그대로)
        run_report(None)
        server_dom = page.evaluate("""() => ({
          notice: (document.getElementById('statusNotice') || {}).innerText || '',
          map_rows: document.querySelectorAll('#s-map tbody tr:not(.tf)').length,
          dist: !!document.getElementById('mapDist'),
        })""")
        snap("server_sample")

        # 2) 풍부한 뷰: 평가이력 지도
        run_report(rich)
        page.evaluate("document.getElementById('s-map').scrollIntoView({block: 'start'})")
        snap("map")
        map_dom = page.evaluate("""() => ({
          dist_legend: (document.querySelector('#mapDist .distl') || {}).innerText || '',
          dist_segments: document.querySelectorAll('#mapDist .dist span').length,
          rows: Array.from(document.querySelectorAll('#s-map tbody tr:not(.tf)')).map(tr => tr.innerText.replace(/\\s+/g, ' ').trim()),
          row_cites: document.querySelectorAll('#s-map td.evs .cite').length,
        })""")

        # 3) 근거 열람: 카드의 첫 인용문 클릭
        page.evaluate("document.getElementById('s-cards').scrollIntoView({block: 'start'})")
        page.click("#s-cards .ev .q >> nth=0")
        page.wait_for_selector("#pbody #evQuote")
        snap("evidence")
        ev_dom = page.evaluate("""() => {
          const k = document.querySelector('#evHead .cite').innerText.replace('#', '');
          return {
            k,
            quote: document.getElementById('evQuote').textContent,
            warn: (document.getElementById('panelWarn') || {}).innerText || '',
            head: document.getElementById('evHead').innerText,
            link: (document.getElementById('evLink') || {}).href || '',
            lines: Array.from(document.querySelectorAll('#evLines .pline')).map(x => x.innerText.replace(/\\s+/g, ' ').trim()),
            strip_sel: Array.from(document.querySelectorAll('.strip .c.sel')).map(c => +c.dataset.line),
            panel_text: document.getElementById('pbody').innerText,
          };
        }""")
        # 다음 근거로 이동 → 계획서 탭(선택 근거 줄 강조)
        page.click("#evHead .nav button >> nth=1")
        page.wait_for_function("document.querySelector('#evHead .cite').innerText !== '#1'")
        next_k = page.inner_text("#evHead .cite")
        page.click('.ptabs button[data-ptab="plan"]')
        page.wait_for_selector("#pbody .doclines")
        plan_sel = page.evaluate("Array.from(document.querySelectorAll('#pbody .doclines .l.sel')).map(x => x.textContent)")
        snap("evidence_plan")

        # 4) 예상 심사평 · 체크리스트
        page.evaluate("document.getElementById('s-review').scrollIntoView({block: 'start'})")
        snap("review")
        rev_dom = page.evaluate("""() => ({
          gen: (document.getElementById('revGen') || {}).innerText || '',
          sentences: document.querySelectorAll('#s-review .rev .g p').length,
          cites: document.querySelectorAll('#s-review .rev .cite').length,
          check_rows: document.querySelectorAll('#s-check .ck:not(.head)').length,
          check_sub: (document.querySelector('#s-check .ck .sub') || {}).innerText || '',
          trace_records: (document.getElementById('traceRecords') || {}).innerText || '',
        })""")
        page.evaluate("document.getElementById('s-check').scrollIntoView({block: 'start'})")
        snap("check")

        # 5) XSS: 태그가 든 뷰
        run_report(xss_view())
        page.click("#s-cards .ev .q >> nth=0")
        page.wait_for_selector("#pbody #evQuote")
        xss = page.evaluate("""() => ({
          flag: window.__xss === undefined ? null : window.__xss,
          injected: document.querySelectorAll('#app img, #app script, #pbody img, #pbody script').length,
          js_links: Array.from(document.querySelectorAll('a[href]')).filter(a => a.href.startsWith('javascript:')).length,
          quote: document.getElementById('evQuote').textContent,
        })""")
        browser.close()

    external = [u for u in requests if urlparse(u).scheme not in {"data", "blob", "about"}
                and urlparse(u).hostname not in LOCAL_HOSTS]
    return {
        "shots": shots,
        "console_errors": console_errors,
        "page_errors": page_errors,
        "failed_requests": failed,
        "external_requests": external,
        "requests_total": len(requests),
        "server_sample": server_dom,
        "map": map_dom,
        "evidence": ev_dom,
        "evidence_next": next_k,
        "plan_sel": plan_sel,
        "review": rev_dom,
        "xss": xss,
        "rich_ev1_quote": rich["ev"]["1"]["q"],
    }


def check(r: dict) -> list[str]:
    """완료 기준 판정. 빈 목록이면 통과."""
    bad = []
    for key in ("console_errors", "page_errors", "failed_requests", "external_requests"):
        if r[key]:
            bad.append(f"{key}: {r[key][:3]}")
    if "샘플" not in r["server_sample"]["notice"]:
        bad.append("서버 샘플 응답에 샘플 표시 없음")
    ev = r["evidence"]
    if ev["quote"] != r["rich_ev1_quote"]:
        bad.append("패널 인용이 결과 원문과 다름")
    if "샘플" not in ev["warn"]:
        bad.append("근거 패널에 샘플 표시 없음")
    if not ev["lines"] or not ev["strip_sel"]:
        bad.append("연결된 계획서 줄 강조 없음")
    if "거절" not in ev["panel_text"]:
        bad.append("근거 패널에 논문 결정 없음")
    if not ev["link"].startswith("https://"):
        bad.append("원문 링크 없음")
    if not r["plan_sel"]:
        bad.append("계획서 탭 강조 없음")
    if r["map"]["dist_segments"] < 2 or "거절" not in r["map"]["dist_legend"]:
        bad.append("결정 분포 없음")
    rv = r["review"]
    if "규칙" not in rv["gen"] or not rv["sentences"] or not rv["cites"]:
        bad.append(f"예상 심사평 생성 방식·문장 표시 이상: {rv['gen']!r}")
    if not rv["check_rows"] or "규칙" not in rv["check_sub"]:
        bad.append("체크리스트 표시 이상")
    x = r["xss"]
    if x["flag"] is not None or x["injected"] or x["js_links"] or "<img" not in x["quote"]:
        bad.append(f"XSS 방어 실패: {x}")
    return bad


def _run(port: int, out: Path) -> dict:
    from tests.e4.ui_shots import start_server, stop_server

    out.mkdir(parents=True, exist_ok=True)
    proc = start_server(port)
    try:
        return shoot(f"http://127.0.0.1:{port}", out)
    finally:
        stop_server(proc, port)


@pytest.mark.skipif(os.environ.get("NEUMANN_UI_SHOTS") != "1", reason="NEUMANN_UI_SHOTS=1일 때만(브라우저·서버 필요)")
def test_view_shots(tmp_path):
    out = Path(os.environ.get("NEUMANN_UI_SHOTS_OUT") or tmp_path)
    r = _run(int(os.environ.get("NEUMANN_UI_SHOTS_PORT", DEFAULT_PORT)), out)
    assert check(r) == []


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "reports")
    args = ap.parse_args()
    if args.port == 8010:
        raise SystemExit("8010은 점검 서버 포트다. 다른 포트를 써라")
    r = _run(args.port, args.out)
    bad = check(r)
    r["problems"] = bad
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
