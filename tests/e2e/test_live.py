"""E5-L0e2e 라이브 E2E: 실제 서버(실데이터·실제 astra)를 브라우저(Playwright)로 끝까지 돈다.

    # PM: v0 통합 서버가 8010에 떠 있을 때
    NEUMANN_LIVE_TESTS=1 python -m pytest tests/e2e/test_live.py -v --e2e-base-url http://127.0.0.1:8010
    # 또는
    NEUMANN_LIVE_TESTS=1 python tests/e2e/test_live.py --base-url http://127.0.0.1:8010

`NEUMANN_LIVE_TESTS=1`이 아니면 전부 건너뛴다(기본 pytest·verify). 서버는 이 테스트가 띄우지 않는다.

계획서마다(데모 3건 `tests/fixtures/plans/plan*.md`)
1. 화면에 붙여넣기 → 실행 → ``POST /premortem/view`` 응답과 리포트 렌더를 기다린다(상한 ``--e2e-timeout``)
2. 파이프라인 연결: /health·응답 ``_status``·헤더 표시 — 샘플 모드면 "파이프라인 미연결(샘플 모드)"로 실패
3. 카드 1장 이상, 카드마다 인용과 http(s) 원문 링크, 생성 방식 표시, 강등 단계 표시
4. 같은 계획서로 ``POST /premortem``(PremortemResult)을 받아 ``eval.linkage.check_result`` +
   ``neumann.index.store.get_source_text``로 근거 연결률 1.0
5. 콘솔 오류 0 · 페이지 오류 0 · 외부 요청 0 · 실패한 요청 0, 스크린샷, 단계별·전체 시간 기록
범위 밖 입력(`negative_recipe.md`): 카드 0장 + 사유(또는 4xx 부적합 판정 + 사유).

실패는 계획서마다 모아 한 번에 보고한다(샘플 모드 사유가 맨 앞). 측정값은
``docs/reports/E5-L0e2e_<mode>_summary.json``과 터미널 요약에 남는다(mode = live | sample | error).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e_checks as C  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.getenv("NEUMANN_LIVE_TESTS") != "1",
    reason="라이브 E2E: NEUMANN_LIVE_TESTS=1일 때만 실행(실서버·실제 astra)",
)

ROOT = Path(__file__).resolve().parents[2]
PLANS_DIR = ROOT / "tests" / "fixtures" / "plans"
DEMO_PLANS = ["plan.md", "plan_elife_neuro.md", "plan_medimaging.md"]
NEGATIVE_PLAN = "negative_recipe.md"
VIEWPORT = {"width": 1440, "height": 900}
C_PREFIX = "E5-L0e2e"
CLIP_JS = ("(s) => { const r = document.querySelector(s).getBoundingClientRect(); "
           "return {x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: Math.min(r.height, 6000)}; }")
HEALTH_WAIT_JS = "() => { const h = document.getElementById('hdrState'); return h && h.textContent.trim() !== '서버 확인 중'; }"
DONE_WAIT_JS = ("() => (document.body.dataset.view === 'report' && document.body.dataset.ready === '1') "
                "|| !!document.getElementById('jobErr')")


# ───────────────────────── 세션 준비 ─────────────────────────


@pytest.fixture(scope="session")
def http():
    httpx = pytest.importorskip("httpx")
    with httpx.Client(timeout=30.0) as client:
        yield client


@pytest.fixture(scope="session")
def health(http, e2e_base_url: str, run_log: dict[str, Any]) -> dict[str, Any] | None:
    try:
        r = http.get(e2e_base_url + "health")
        data = r.json() if r.status_code == 200 else None
    except Exception as exc:  # noqa: BLE001
        run_log["health_error"] = f"{type(exc).__name__}"
        data = None
    p = (data or {}).get("pipeline") or {}
    run_log["mode"] = {"connected": "live", "unavailable": "sample"}.get(p.get("state"), "error")
    run_log["health"] = {"pipeline": p, "version": (data or {}).get("version"),
                         "stages": {k: v.get("available") for k, v in ((data or {}).get("stages") or {}).items()}}
    if data is None:
        pytest.fail(f"서버 {e2e_base_url} /health 응답 없음 — 서버를 먼저 띄운다", pytrace=False)
    return data


@pytest.fixture(scope="session")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            yield b
        finally:
            b.close()


@pytest.fixture(scope="session")
def source_lookup():
    """근거 원문 조회(E2 색인). 모듈이 없거나 색인이 없으면 (None, 사유)."""
    try:
        from neumann.index.store import get_source_text
    except Exception as exc:  # noqa: BLE001
        return None, f"neumann.index.store.get_source_text import 실패: {type(exc).__name__}"
    return get_source_text, ""


# ───────────────────────── 한 건 실행 ─────────────────────────


def _run_ui(browser, base_url: str, plan_name: str, timeout_s: float, out_dir: Path, mode: str) -> dict[str, Any]:
    """브라우저로 계획서 1건을 돌리고 재료(view·dom·시간·브라우저 기록)를 모은다."""
    text = (PLANS_DIR / plan_name).read_text(encoding="utf-8")
    stem = Path(plan_name).stem
    ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
    page = ctx.new_page()
    rec: dict[str, Any] = {"console_errors": [], "page_errors": [], "external": [], "failed": [], "shots": []}
    page.on("console", lambda m: rec["console_errors"].append(m.text[:300]) if m.type == "error" else None)
    page.on("pageerror", lambda e: rec["page_errors"].append(str(e)[:300]))
    page.on("request", lambda r: rec["external"].append(r.url[:200]) if C.is_external(r.url, base_url) else None)
    page.on("requestfailed", lambda r: rec["failed"].append(f"{r.method} {r.url[:160]} {r.failure}"))

    def shot(tag: str, full: bool = False, selector: str | None = None) -> None:
        path = out_dir / f"{C_PREFIX}_{mode}_{stem}_{tag}.png"
        try:
            if selector:  # 페이지 좌표로 잘라 찍는다(요소 스크린샷은 고정 헤더가 카드 위에 겹친다)
                box = page.evaluate(CLIP_JS, selector)
                page.screenshot(path=str(path), full_page=True, clip=box)
            else:
                page.screenshot(path=str(path), full_page=full)
            rec["shots"].append(path.name)
        except Exception as exc:  # noqa: BLE001 - 스크린샷 실패는 기록만(판정은 DOM으로)
            rec["shots"].append(f"{path.name}: 실패 {type(exc).__name__}")

    try:
        page.goto(base_url, wait_until="load")
        page.wait_for_selector('body[data-view="input"][data-ready="1"]', timeout=20_000)
        page.wait_for_function(HEALTH_WAIT_JS, timeout=20_000)
        page.fill("#ta", text)
        page.evaluate("() => document.fonts.ready")
        shot("input")
        t0 = time.perf_counter()
        with page.expect_response(lambda r: r.url.rstrip("/").endswith("/premortem/view") and r.request.method == "POST",
                                  timeout=timeout_s * 1000) as resp_info:
            page.click("#btnStart")
        resp = resp_info.value
        t_resp = time.perf_counter() - t0
        rec["http_status"] = resp.status
        try:
            rec["view"] = resp.json()
        except Exception:  # noqa: BLE001
            rec["view"] = None
        page.wait_for_function(DONE_WAIT_JS, timeout=30_000)
        t_done = time.perf_counter() - t0
        page.evaluate("() => document.fonts.ready")
        rec["dom"] = page.evaluate(C.DOM_PROBE_JS)
        rec["timings"] = {"ui_response_s": round(t_resp, 3), "ui_total_s": round(t_done, 3)}
        if rec["dom"].get("view") == "report":
            shot("report", full=True)
            shot("cards", selector="#s-cards")
        else:
            shot("job")
    except Exception as exc:  # noqa: BLE001 - 시간 초과 등도 실패 사유로 모은다
        rec["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}"
        rec.setdefault("dom", {})
        rec.setdefault("timings", {})
        shot("timeout")
    finally:
        ctx.close()
    return rec



def _post_premortem(http, base_url: str, plan_name: str, timeout_s: float) -> tuple[int | None, Any, float]:
    text = (PLANS_DIR / plan_name).read_text(encoding="utf-8")
    t0 = time.perf_counter()
    try:
        r = http.post(base_url + "premortem", json={"plan_text": text, "filename": plan_name}, timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001
        return None, {"reason": f"{type(exc).__name__}"}, time.perf_counter() - t0
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = None
    return r.status_code, body, time.perf_counter() - t0


def _report(run_log: dict[str, Any], plan_name: str, failures: list[str], entry: dict[str, Any]) -> None:
    # 샘플 모드 사유를 맨 앞으로(같은 사유가 여러 재료에서 나오면 한 번만 적지 않고 모두 남긴다: 어디서 드러났는지가 정보다)
    failures.sort(key=lambda f: 0 if f.startswith(C.SAMPLE_FAIL) else 1)
    entry["failures"] = failures
    run_log["plans"][plan_name] = entry
    if failures:
        pytest.fail(f"{plan_name}: {len(failures)}건 실패\n  - " + "\n  - ".join(failures), pytrace=False)


# ───────────────────────── 테스트 ─────────────────────────


def test_pipeline_connected(health) -> None:
    """서버가 실제 분석 파이프라인에 연결돼 있다(샘플 모드면 실패)."""
    failures = C.check_health(health)
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("plan_name", DEMO_PLANS)
def test_demo_plan(plan_name: str, browser, http, health, source_lookup, e2e_base_url: str, e2e_timeout_s: float,
                   e2e_out: Path, run_log: dict[str, Any]) -> None:
    mode = run_log.get("mode", "unknown")
    rec = _run_ui(browser, e2e_base_url, plan_name, e2e_timeout_s, e2e_out, mode)
    view, dom = rec.get("view"), rec.get("dom") or {}
    failures: list[str] = []
    if rec.get("error"):
        failures.append(f"화면 실행 실패(상한 {e2e_timeout_s}s): {rec['error']}")
    failures += C.check_health(health)
    failures += C.check_view_status(view, rec.get("http_status"))
    if dom:
        failures += C.check_header(dom)
        failures += C.check_cards(dom, view)
        failures += C.check_generators(dom, view)
        failures += C.check_degradation(dom, view)
    failures += C.check_browser(rec["console_errors"], rec["page_errors"], rec["external"], rec["failed"])

    status, result, api_s = _post_premortem(http, e2e_base_url, plan_name, e2e_timeout_s)
    result_fail = C.check_result_json(result if isinstance(result, dict) else None, status)
    failures += result_fail
    linkage: dict[str, Any] = {}
    lookup, why = source_lookup
    if any(f.startswith(C.SAMPLE_FAIL) for f in result_fail):
        linkage = {"summary": "검사 안 함: 샘플 결과(공용 fixture)는 근거 연결 검사 대상이 아니다"}
        failures.append(f"근거 연결률 미측정: {C.SAMPLE_FAIL}")
    elif lookup is None:
        linkage = {"summary": f"검사 안 함: {why}"}
        failures.append(f"근거 연결률 미측정: {why}")
    elif isinstance(result, dict) and status == 200:
        link_fail, linkage = C.check_linkage(result, lookup)
        failures += link_fail
        if not result.get("risk_cards"):
            failures.append("/premortem 결과 위험카드 0장(근거 연결 검사 대상 없음)")

    timings = {**rec.get("timings", {}), **C.stage_timings(view, result if isinstance(result, dict) else None),
               "api_premortem_s": round(api_s, 3)}
    entry = {
        "http_status": rec.get("http_status"), "api_status": status,
        "source": (view or {}).get("_status", {}).get("source") if isinstance(view, dict) else None,
        "result_status": (view or {}).get("_status", {}).get("result_status") if isinstance(view, dict) else None,
        "n_cards": len(dom.get("cards") or []), "generators": ((view or {}).get("_status") or {}).get("generators"),
        "stages_not_ok": ((view or {}).get("_status") or {}).get("stages_not_ok"),
        "timings": timings, "linkage": linkage, "shots": rec["shots"],
        "browser": {k: len(rec[k]) for k in ("console_errors", "page_errors", "external", "failed")},
    }
    _report(run_log, plan_name, failures, entry)


def test_negative_recipe(browser, health, e2e_base_url: str, e2e_timeout_s: float, e2e_out: Path,
                         run_log: dict[str, Any]) -> None:
    mode = run_log.get("mode", "unknown")
    rec = _run_ui(browser, e2e_base_url, NEGATIVE_PLAN, e2e_timeout_s, e2e_out, mode)
    view, dom = rec.get("view"), rec.get("dom") or {}
    failures: list[str] = []
    if rec.get("error"):
        failures.append(f"화면 실행 실패(상한 {e2e_timeout_s}s): {rec['error']}")
    failures += C.check_health(health)
    st = (view or {}).get("_status") or {} if isinstance(view, dict) else {}
    if st.get("source") == "sample":
        failures.append(f"{C.SAMPLE_FAIL}: /premortem/view _status.source=sample — 범위 밖 판정을 잴 수 없다")
    if dom:
        failures += C.check_header(dom)
        failures += C.check_negative(dom, view, rec.get("http_status"))
    failures += C.check_browser(rec["console_errors"], rec["page_errors"], rec["external"], rec["failed"])
    entry = {
        "http_status": rec.get("http_status"), "source": st.get("source"), "result_status": st.get("result_status"),
        "n_cards": len(dom.get("cards") or []), "empty_reason": st.get("empty_reason"),
        "timings": {**rec.get("timings", {}), **C.stage_timings(view)}, "shots": rec["shots"],
        "browser": {k: len(rec[k]) for k in ("console_errors", "page_errors", "external", "failed")},
    }
    _report(run_log, NEGATIVE_PLAN, failures, entry)


# ───────────────────────── 스크립트 실행 ─────────────────────────

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="E5-L0e2e 라이브 E2E(pytest 래퍼)")
    ap.add_argument("--base-url", default=os.getenv("NEUMANN_E2E_BASE_URL", "http://127.0.0.1:8010"))
    ap.add_argument("--timeout", default=None, help="계획서 1건 분석 대기 상한(초)")
    ap.add_argument("--out", default=None, help="스크린샷·요약 JSON 폴더(기본 docs/reports)")
    args, rest = ap.parse_known_args()
    os.environ["NEUMANN_LIVE_TESTS"] = "1"
    argv = [str(Path(__file__).resolve()), "-v", "-p", "no:cacheprovider", f"--e2e-base-url={args.base_url}"]
    if args.timeout:
        argv.append(f"--e2e-timeout={args.timeout}")
    if args.out:
        argv.append(f"--e2e-out={args.out}")
    sys.exit(pytest.main(argv + rest))
