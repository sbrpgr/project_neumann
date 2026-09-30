"""E3-L1e 근거 게이트 — 화면(view)·내보내기: 근거 없는 항목은 나가지 않고, 제외 수가 view 필드로 보인다."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from neumann.analyze import gate as g
from neumann.analyze.checklist import attach_checklist
from neumann.analyze.review import attach_expected_review
from tests.e3.test_checklist import LEAK, SEED, FakeLLM, _good
from tests.e3.test_evidence_gate_l1e import _card_ev, _ReviewCall, _aliases, _respond, _result, _s

view_mod = pytest.importorskip("neumann.api.view")


# ── 화면(view): 체크리스트 ──────────────────────────────────────────────


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


@pytest.mark.parametrize(
    "bad",
    [
        {"evidence": "other_card"},  # 다른 카드의 근거
        {"evidence": "mixed"},  # 자기 근거 + 다른 카드 근거(하나라도 밖이면 제외)
        {"card_id": "card-ghost"},  # 화면에 없는 카드 연결
        {"card_id": None},  # 카드 연결 없음
        {"evidence": ["ex_forged00000000"]},  # 없는 id
    ],
    ids=["other_card", "mixed", "ghost_card", "no_card", "unknown_id"],
)
def test_view_gate_is_the_same_check_as_generation(bad: dict[str, Any]) -> None:
    """화면 게이트도 생성 직후·2차 검증과 같은 검사: 근거가 전부 **그 카드의** 근거여야 하고 카드가 있어야 한다."""
    res = _result()
    assert res.plan is not None
    out = attach_checklist(res, res.plan, FakeLLM(_good))
    leak_item = next(it for it in out.checklist if it["card_id"] == LEAK)
    item = {**leak_item, "item_id": "X1", "action": "끼어든 행동"}
    if bad.get("evidence") == "other_card":
        item["evidence"] = _card_ev(res, SEED)[:1]
    elif bad.get("evidence") == "mixed":
        item["evidence"] = [*_card_ev(res, LEAK)[:1], *_card_ev(res, SEED)[:1]]
    elif "evidence" in bad:
        item["evidence"] = bad["evidence"]
    if "card_id" in bad:
        item["card_id"] = bad["card_id"]
    v = view_mod.build_ui_view(out.model_copy(update={"checklist": [*out.checklist, item]}), records=None)
    assert "X1" not in [r["id"] for r in v["checklist"]] and len(v["checklist"]) == 4
    assert v["checklist_audit"]["by_stage"]["view"] == 1 and v["checklist_audit"]["note"] == "근거 없는 항목 1개 제외"
    for r in v["checklist"]:  # 남은 항목의 근거 번호는 전부 그 카드의 근거 번호다
        card = v["cards"][r["card"] - 1]
        assert r["ev"] and set(r["ev"]) <= set(card["ev"])


def test_view_all_items_excluded_keeps_section_with_message() -> None:
    res = _result()
    assert res.plan is not None
    out = attach_checklist(res, res.plan, FakeLLM(_good))
    stripped = out.model_copy(update={"checklist": [{**it, "evidence": []} for it in out.checklist]})
    v = view_mod.build_ui_view(stripped, records=None)
    assert v["checklist"] == [] and view_mod.validate_ui_view(v) == []
    ca = v["checklist_audit"]
    assert ca["shown"] == 0 and ca["excluded"] == 4 and ca["note"] == "근거 있는 항목이 없어 모두 제외했습니다(4개)"


def test_view_normal_checklist_has_zero_excluded_and_no_note() -> None:
    res = _result()
    assert res.plan is not None
    v = view_mod.build_ui_view(attach_checklist(res, res.plan, FakeLLM(_good)), records=None)
    assert v["checklist_audit"]["excluded"] == 0 and v["checklist_audit"]["note"] == ""
    assert len(v["checklist"]) == 4


# ── 화면(view): 예상 심사평 ─────────────────────────────────────────────


def _review_with_drops(input_text: str) -> dict:
    """정상 1 + 근거 빈 문장 1 + 형식 오류 1 + 없는 수치 1(근거 문제 아님)."""
    code, ev = _aliases(input_text)
    c_leak = next(k for k, v in code.items() if v == "R3")
    return {"strength": [], "request": [], "weakness": [
        _s("무작위 분할은 누출 위험이 있다 (16행).", ev[c_leak][:1], [c_leak], [16]),
        _s("근거 없는 문장.", [], []),
        {"text": "근거 형식이 틀린 문장.", "excerpt_ids": "E1", "card_ids": [], "plan_lines": []},
        _s("이 설계로는 R² 0.95 이상을 달성하기 어렵다.", ev[c_leak][:1], [c_leak]),
    ]}


def test_view_review_audit_counts_only_no_evidence_reasons() -> None:
    """화면 제외 수 k = 삭제 목록 중 근거 계열 사유의 수(형식 오류 포함, 없는 수치 등은 따로)."""
    res = _result()
    v = view_mod.build_ui_view(attach_expected_review(res, _ReviewCall(_review_with_drops)), records=None)
    assert view_mod.validate_ui_view(v) == []
    audit = v["review"]["audit"]
    codes = audit["no_evidence_reasons"]
    assert set(codes) == {*g.NO_EVIDENCE_FAMILY, "no_evidence_in_view"}  # 생성 게이트와 같은 계열 + 화면에서 뺀 것
    ne = [d for d in audit["dropped"] if d[0] in codes]
    other = [d for d in audit["dropped"] if d[0] not in codes]
    assert audit["no_evidence"] == len(ne) == 2 and audit["note"] == "근거 없는 항목 2개 제외"
    assert [d[0] for d in other] == [g.FABRICATED_NUMBER]
    assert all(s["c"] for s in v["review"]["weakness"])


# ── 내보내기(neumann_report.md) ─────────────────────────────────────────


def test_export_report_carries_reason_codes_not_dropped_sentences() -> None:
    export = pytest.importorskip("neumann.api.export")
    res = attach_expected_review(_result(), _ReviewCall(_review_with_drops))
    assert res.expected_review["audit"]["dropped"]  # 결과 JSON 원본에는 감사 기록이 그대로 있다
    report = export.build_package_files(res)["neumann_report.md"].decode("utf-8")
    for text in ("근거 없는 문장.", "근거 형식이 틀린 문장.", "R² 0.95"):
        assert text not in report  # 뺀 문장 원문은 라벨 없이 문서에 나가지 않는다
    assert '"dropped_reasons"' in report and g.MISSING_CITATION in report and g.FABRICATED_NUMBER in report
    assert "무작위 분할은 누출 위험이 있다" in report  # 통과 문장은 그대로


# ── 브라우저(선택): NEUMANN_UI_TESTS=1일 때만 ──────────────────────────


def _mock_view(*, strip_checklist: bool = False) -> dict:
    """fixture + 가짜 응답(mock 표기). 심사평: 근거 빈 문장 1 + 형식 오류 1 + 없는 수치 1이 빠진다.
    체크리스트: 근거 빈 행동 1개가 빠진다. strip_checklist면 남은 항목도 근거를 지워 화면에서 전부 빠진다."""
    res = _result()
    call = _ReviewCall(_review_with_drops)
    call.generator, call.model = "mock", "mock-l1e"
    res = attach_expected_review(res, call)
    assert res.plan is not None
    res = attach_checklist(res, res.plan, FakeLLM(_respond([])), generator="mock", model="mock-l1e")
    if strip_checklist:
        res = res.model_copy(update={"checklist": [{**it, "evidence": []} for it in res.checklist]})
    return view_mod.build_ui_view(res, filename="plan.md", sample=True, pipeline_state="unavailable", records=None)


_DOM_JS = """() => {
  const fold = (id) => { const d = document.getElementById(id); if (!d) return null;
    const rows = Array.from(d.querySelectorAll(':scope > div'));
    return {open: d.open, summary: d.querySelector('summary').innerText,
            rows: rows.length, labeled: rows.filter(r => r.textContent.includes('제외됨')).length,
            struck_visible: rows.some(r => r.querySelector('s') && r.querySelector('s').checkVisibility())}; };
  const chk = document.getElementById('s-check');
  return {
    ck: (document.getElementById('ckExcluded') || {}).innerText || '',
    rev: (document.getElementById('revExcluded') || {}).innerText || '',
    rows: Array.from(document.querySelectorAll('#s-check .ck:not(.head)')).map(r => r.querySelectorAll('.cite').length),
    has_check: !!chk,
    text: (chk ? chk.innerText : '') + document.getElementById('s-review').innerText,
    ne: fold('revDropped'), other: fold('revDroppedOther'),
  };
}"""


def _route_jobs(page: Any, view: dict) -> list[str]:
    """`**/premortem/jobs**`를 가로채 작업 API를 흉내 낸다: POST → queued, GET 1번째 → running, 2번째 → done(view)."""
    seen: list[str] = []
    body = json.dumps(view, ensure_ascii=False)

    def handle(route: Any, req: Any) -> None:
        seen.append(f"{req.method} {req.url.split('/premortem/')[-1]}")
        gets = sum(1 for s in seen if s.startswith("GET"))
        if req.method == "POST":
            data = {"job_id": "job_l1e", "status": "queued", "position": 0, "eta_s": 1, "poll_after_s": 1}
            route.fulfill(status=202, content_type="application/json", body=json.dumps(data))
        elif gets <= 1:
            data = {"job_id": "job_l1e", "status": "running", "stage": "checklist", "stage_label": "체크리스트", "poll_after_s": 1}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data, ensure_ascii=False))
        else:
            route.fulfill(status=200, content_type="application/json",
                          body='{"job_id":"job_l1e","status":"done","result":' + body + "}")

    page.route("**/premortem/jobs**", handle)
    return seen


@pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="NEUMANN_UI_TESTS=1일 때만(브라우저·서버 필요)")
def test_excluded_lists_render_in_browser(tmp_path) -> None:
    """실제 index.html(작업 API 흐름 queued → running → done을 가로채 모의)에서:
    - 제외 문구 "근거 없는 항목 k개 제외"가 체크리스트·심사평 절에 보이고, 심사평 목록 제목의 k와 같다.
    - 삭제 문장 목록은 둘(근거 없음 · 그 밖의 검증 사유), 모두 기본 접힘, 항목마다 "제외됨".
    - 체크리스트가 전부 제외되면 절을 숨기지 않고 "근거 있는 항목이 없어 모두 제외했습니다(k개)".
    서버는 mock provider·키 없이 하위 프로세스(기본 8164, 8010 금지). 콘솔 오류 0.
    """
    from playwright.sync_api import sync_playwright

    from tests.e4.ui_shots import port_free, start_server, stop_server
    from tests.fixtures.loader import plan_text

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
    results: dict[str, Any] = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for name, view in (("main", _mock_view()), ("all_excluded", _mock_view(strip_checklist=True))):
                page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="ko-KR")
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                page.wait_for_selector('body[data-view="input"][data-ready="1"]')
                seen = _route_jobs(page, view)
                page.fill("#ta", plan_text())
                page.click("#btnStart")
                page.wait_for_function("document.body.dataset.view === 'report' && document.body.dataset.ready === '1'",
                                       timeout=120_000)
                results[name] = {**page.evaluate(_DOM_JS), "jobs": seen}
                if name == "main":
                    for sec, shot in (("s-check", "check"), ("s-review", "review")):
                        page.evaluate(f"document.getElementById('{sec}').scrollIntoView({{block: 'start'}})")
                        page.wait_for_timeout(200)
                        page.screenshot(path=str(out / f"E3-L1e_{shot}.png"))
                else:
                    page.evaluate("document.getElementById('s-check').scrollIntoView({block: 'start'})")
                    page.wait_for_timeout(200)
                    page.screenshot(path=str(out / "E3-L1e_check_all_excluded.png"))
                page.close()
            browser.close()
    finally:
        stop_server(proc, port)

    assert errors == []
    m = results["main"]
    assert m["jobs"][0].startswith("POST") and any(s.startswith("GET jobs/job_l1e") for s in m["jobs"])  # 작업 API 흐름
    assert m["ck"].startswith("근거 없는 항목 1개 제외")
    assert m["rows"] and all(n >= 1 for n in m["rows"])  # 화면 항목은 전부 근거 번호가 있다
    assert "분할 단위를 계획서 16행에 적는다." not in m["text"]  # 폐기된 행동 문구는 화면에 없다
    ne, other = m["ne"], m["other"]
    assert ne and other and ne["open"] is False and other["open"] is False  # 둘 다 기본 접힘
    assert ne["summary"] == "근거가 없어 제외한 문장(분석 결과 아님) · 2"
    assert other["summary"] == "검증에서 제외한 문장(분석 결과 아님) · 1"
    assert m["rev"].startswith("근거 없는 항목 2개 제외")  # 제외 문구 k = 목록 제목 k
    assert ne["labeled"] == ne["rows"] == 2 and other["labeled"] == other["rows"] == 1  # 항목마다 "제외됨"
    assert not ne["struck_visible"] and not other["struck_visible"]
    assert "근거 없는 문장." not in m["text"] and "근거 형식이 틀린 문장." not in m["text"]  # 접힌 상태에서 안 보임

    a = results["all_excluded"]
    assert a["has_check"] and a["rows"] == []  # 절은 남고 행은 없다
    assert a["ck"].startswith("근거 있는 항목이 없어 모두 제외했습니다(")
