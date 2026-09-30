"""E3-L1e 근거 게이트 — 화면(view): 근거 없는 항목은 화면에 나가지 않고, 제외 수가 view 필드로 보인다."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from neumann.analyze.checklist import attach_checklist
from neumann.analyze.review import attach_expected_review
from tests.e3.test_checklist import FakeLLM, _good
from tests.e3.test_evidence_gate_l1e import _ReviewCall, _aliases, _respond, _result, _s

view_mod = pytest.importorskip("neumann.api.view")


# ── 화면(view) ──────────────────────────────────────────────────────────


def test_view_shows_excluded_count_and_never_shows_ungrounded_items() -> None:
    res = _result()
    assert res.plan is not None
    out = attach_checklist(res, res.plan, FakeLLM(_respond([])))  # 생성 직후 게이트가 1개 폐기
    # 화면 앞 마지막 방어선: 게이트를 우회한 근거 없는 항목 1개를 억지로 넣는다
    sneaked = out.model_copy(update={"checklist": [*out.checklist,
                                                   {**out.checklist[0], "item_id": "C9", "action": "몰래 들어온 행동",
                                                    "evidence": []}]})
    v = view_mod.build_ui_view(sneaked, records=None)
    assert view_mod.validate_ui_view(v) == []
    assert [r["id"] for r in v["checklist"]] == ["C1", "C2"] and all(r["ev"] for r in v["checklist"])
    ca = v["checklist_audit"]
    assert ca["excluded"] == 2 and ca["by_stage"] == {"checklist": 1, "semantic_validate": 0, "view": 1}
    assert ca["note"] == "근거 없는 항목 2개 제외" and ca["shown"] == 2
    assert v["_status"]["dropped"]["checklist_items_without_evidence"] == 1


def test_view_normal_checklist_has_zero_excluded_and_no_note() -> None:
    res = _result()
    assert res.plan is not None
    v = view_mod.build_ui_view(attach_checklist(res, res.plan, FakeLLM(_good)), records=None)
    assert v["checklist_audit"]["excluded"] == 0 and v["checklist_audit"]["note"] == ""
    assert len(v["checklist"]) == 4


def test_view_review_audit_carries_excluded_note() -> None:
    res = _result()

    def respond(input_text: str) -> dict:
        code, ev = _aliases(input_text)
        c_leak = next(k for k, v in code.items() if v == "R3")
        return {"strength": [], "weakness": [_s("무작위 분할은 누출 위험이 있다 (16행).", ev[c_leak][:1], [c_leak], [16]),
                                             _s("근거 없는 문장.", [], [])], "request": []}

    v = view_mod.build_ui_view(attach_expected_review(res, _ReviewCall(respond)), records=None)
    assert view_mod.validate_ui_view(v) == []
    audit = v["review"]["audit"]
    assert audit["no_evidence"] == 1 and audit["note"] == "근거 없는 항목 1개 제외"
    assert all(s["c"] for s in v["review"]["weakness"])


# ── 브라우저(선택): NEUMANN_UI_TESTS=1일 때만 ──────────────────────────


@pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="NEUMANN_UI_TESTS=1일 때만(브라우저·서버 필요)")
def test_excluded_note_renders_in_browser(tmp_path) -> None:
    """실제 index.html에 가짜 뷰(mock 표기)를 먹여 '근거 없는 항목 k개 제외'가 체크리스트·심사평 절에 보이는지.

    서버는 mock provider·키 없이 하위 프로세스로 띄운다(기본 8164, 8010 금지). 스크린샷은
    NEUMANN_UI_SHOTS_OUT이 있으면 그 폴더에 E3-L1e_check.png·E3-L1e_review.png로 남긴다.
    """
    from playwright.sync_api import sync_playwright

    from tests.e4.ui_shots import port_free, start_server, stop_server
    from tests.fixtures.loader import plan_text

    view = _mock_view()
    port = int(os.getenv("NEUMANN_UI_TESTS_PORT", "8164"))
    assert port != 8010 and port_free(port), f"포트 {port}가 쓰이고 있다"
    out = Path(os.getenv("NEUMANN_UI_SHOTS_OUT") or tmp_path)
    saved = dict(os.environ)
    for k in ("OPENAI_API_KEY", "NEUMANN_LIVE_LLM_OK"):
        os.environ.pop(k, None)
    os.environ.update({"NEUMANN_LLM_PROVIDER": "mock", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    try:
        proc = start_server(port)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    errors: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="ko-KR")
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            page.wait_for_selector('body[data-view="input"][data-ready="1"]')
            body = json.dumps(view, ensure_ascii=False)
            page.route("**/premortem/view", lambda route, _req: route.fulfill(
                status=200, content_type="application/json", body=body))
            page.fill("#ta", plan_text())
            page.click("#btnStart")
            page.wait_for_function("document.body.dataset.view === 'report' && document.body.dataset.ready === '1'",
                                   timeout=120_000)
            dom = page.evaluate("""() => ({
              ck: (document.getElementById('ckExcluded') || {}).innerText || '',
              rev: (document.getElementById('revExcluded') || {}).innerText || '',
              rows: Array.from(document.querySelectorAll('#s-check .ck:not(.head)')).map(r => r.querySelectorAll('.cite').length),
              text: document.getElementById('s-check').innerText + document.getElementById('s-review').innerText,
              fold: (() => { const d = document.getElementById('revDropped'); return d ? {open: d.open,
                summary: d.querySelector('summary').innerText, struck_visible: !!d.querySelector('s') && d.querySelector('s').checkVisibility()} : null; })(),
            })""")
            for sec, name in (("s-check", "check"), ("s-review", "review")):
                page.evaluate(f"document.getElementById('{sec}').scrollIntoView({{block: 'start'}})")
                page.wait_for_timeout(200)
                page.screenshot(path=str(out / f"E3-L1e_{name}.png"))
            browser.close()
    finally:
        stop_server(proc, port)
    assert errors == []
    assert dom["ck"].startswith("근거 없는 항목 1개 제외") and dom["rev"].startswith("근거 없는 항목 1개 제외")
    assert dom["rows"] and all(n >= 1 for n in dom["rows"])  # 화면 항목은 전부 근거 번호가 있다
    assert "분할 단위를 계획서 16행에 적는다." not in dom["text"]  # 폐기된 행동 문구는 화면에 없다
    # PM 결정: 심사평 감사 카드의 제외 문장 목록은 기본 접힘, 제목 "근거가 없어 제외한 문장(분석 결과 아님)"
    fold = dom["fold"]
    assert fold is not None and fold["open"] is False and not fold["struck_visible"]
    assert fold["summary"].startswith("근거가 없어 제외한 문장(분석 결과 아님)")
    assert "근거 없이 쓴 약점 문장이다." not in dom["text"]  # 접힌 상태에서는 제외 문장이 보이지 않는다


def _mock_view() -> dict:
    """fixture + 가짜 응답(mock 표기): 심사평 근거 없는 문장 1개, 체크리스트 근거 빈 행동 1개가 게이트에서 빠진다."""
    res = _result()

    def review(input_text: str) -> dict:
        code, ev = _aliases(input_text)
        c_leak = next(k for k, v in code.items() if v == "R3")
        c_seed = next(k for k, v in code.items() if v == "R2")
        return {"strength": [],
                "weakness": [_s("무작위 분할은 시험 성능을 과대평가할 수 있다 (16–17행).", ev[c_leak][:1], [c_leak], [16, 17]),
                             _s("근거 없이 쓴 약점 문장이다.", [], [c_leak])],
                "request": [_s("여러 시드로 반복 학습하고 오차막대를 보고할 것 (22행).", ev[c_seed][:2], [c_seed], [22])]}

    call = _ReviewCall(review)
    call.generator, call.model = "mock", "mock-l1e"
    res = attach_expected_review(res, call)
    assert res.plan is not None
    res = attach_checklist(res, res.plan, FakeLLM(_respond([])), generator="mock", model="mock-l1e")
    return view_mod.build_ui_view(res, filename="plan.md", sample=True, pipeline_state="unavailable", records=None)
