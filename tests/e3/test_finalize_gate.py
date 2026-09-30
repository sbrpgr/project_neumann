"""FIN-ENGINE 교정 게이트의 적대 검사.

근거 범위는 issue의 plan_lines와 도구 검사 sources(발췌)까지 넓혔다("원문 안의 사실로 원문을 고친다"). 그래도
새 수치·기관·달성 주장·범위 밖 줄의 사실은 계속 거절되고, 도구 계산값은 [확인 필요: …] 안에서만 쓸 수 있어야 한다.
실제 Z3 검사를 쓴다(mock LLM, 실제 API 없음)."""

from __future__ import annotations

import json
import sys

from neumann.analyze.finalize import ASSESSMENT_TASK, CORRECTION_TASK, finalize_plan
from neumann.llm import MockProvider

PLAN = "합계 항목은 3이다.\n추가 항목은 4이다.\n합계 최대 6이다.\n관련 없는 줄에 서울대학교와 99가 있다."
CHECK = {"check_id": "c1", "kind": "constraint", "plan_lines": [1, 2, 3], "params": {
    "sources": [{"line": 1}, {"line": 2}, {"line": 3}], "operation": "sum",
    "terms": [{"source": 0, "value": 3}, {"source": 1, "value": 4}], "comparator": "le", "limit": {"source": 2, "value": 6}}}
ISSUE = {"issue_id": "i1", "kind": "logical", "plan_lines": [3], "message": "합계 상한과 항목 합의 대조가 필요하다.", "check_ids": ["c1"]}


def provider(edits, issue=ISSUE, checks=(CHECK,)):
    return MockProvider(scripted={ASSESSMENT_TASK: [{"issues": [issue], "checks": list(checks)}],
                                  CORRECTION_TASK: [{"edits": edits}]})


def edit(after, line=3, before="합계 최대 6이다.", issue="i1"):
    return {"line": line, "current_text": before, "replacement": after, "issue_ids": [issue]}


def run(after, **kw):
    return finalize_plan(PLAN, provider=provider([edit(after, **kw)]))


def test_real_z3_check_fails_for_planted_sum_and_unchanged_line_is_no_change():
    out = run("합계 최대 6이다.")
    row = out["tool_checks_before"][0]
    assert row["tool"] == "z3" and row["status"] == "failed"
    assert out["corrections"][0]["reason"] == "no_change" and out["issues"][0]["status"] == "unresolved"


def test_words_and_numbers_from_other_issue_lines_and_tool_sources_are_now_allowed():
    out = run("합계 최대 6이다. 추가 항목은 4이다.")  # 낱말 '항목은'과 수치 4는 줄 2(도구 source)에서 온다
    assert out["corrections"][0]["applied"] and out["corrections"][0]["reason"] == "applied"
    assert out["final_text"].split("\n")[2] == "합계 최대 6이다. 추가 항목은 4이다."
    assert out["counters"]["correction_batches"] == 1 and out["counters"]["recheck_runs"] == 1
    assert out["tool_checks_after"][0]["check_id"] == "c1"  # 고친 줄의 검사만 1회 재검사


def _with_computed(monkeypatch, value):
    """도구 결과 details.computed를 흉내 낸다(실제 Z3 판정은 그대로). 엔진은 이 값 말고는 어떤 계산도 하지 않는다."""
    from neumann.analyze import final_tools
    real = final_tools.run_tool_checks

    def run(text, checks, event=None):
        rows = real(text, checks, event)
        for row in rows:
            if row["status"] in ("passed", "failed"):
                row["details"] = {**row.get("details", {}), "computed": value}
        return rows
    monkeypatch.setattr(final_tools, "run_tool_checks", run)


def test_tool_computed_value_only_inside_placeholder(monkeypatch):
    engine_only = run("합계 최대 6이다. [확인 필요: 항목 합계 7 상한 6 초과]")
    assert engine_only["corrections"][0]["reason"] == "unsupported_number"  # 엔진은 3+4를 스스로 계산하지 않는다(E-1)
    _with_computed(monkeypatch, 7)
    ok = run("합계 최대 6이다. [확인 필요: 항목 합계 7 상한 6 초과]")
    assert ok["corrections"][0]["applied"], ok["corrections"][0]["reason"]
    assert ok["issues"][0]["status"] == "unresolved"  # 자리표시는 표시일 뿐, 도구 재검사는 여전히 실패
    bad = run("합계 최대 7이다.")  # 계산값을 본문 사실로 단정 → 거절
    assert bad["corrections"][0]["reason"] == "unsupported_number" and bad["final_text"] == bad["input_text"]
    other = run("합계 최대 6이다. [확인 필요: 항목 합계 8 상한 6 초과]")  # 도구가 내지 않은 수치
    assert other["corrections"][0]["reason"] == "unsupported_number"


def test_placeholder_body_is_not_a_free_text_channel():
    cases = [("합계 최대 6이다. [확인 필요: https://evil.example/x]", "placeholder_unsafe"),
             ("합계 최대 6이다. [확인 필요: www.example.com 참조]", "placeholder_unsafe"),
             ("합계 최대 6이다. [확인 필요: 문의 admin@example.com]", "pii_or_identity"),  # 이메일은 개인정보 게이트가 먼저 잡는다
             ("합계 최대 6이다. [확인 필요: 계정 @admin 확인]", "placeholder_unsafe"),
             ("합계 최대 6이다. [확인 필요: 링크](x)", "placeholder_unsafe"),
             ("합계 최대 6이다. [확인 필요: 신약 임상 결과가 우수함]", "placeholder_vocabulary"),
             ("합계 최대 6이다. [확인 필요 항목 합계]", "placeholder_malformed")]
    for after, reason in cases:
        out = run(after)
        assert out["corrections"][0]["reason"] == reason, (after, out["corrections"][0]["reason"])
        assert out["final_text"] == out["input_text"]
    ok = run("합계 최대 6이다. [확인 필요: 항목 합계 상한 대조 — 연구자 확인]")  # 고정 사유 어휘 + 범위 낱말만
    assert ok["corrections"][0]["applied"]


def test_fabrication_is_still_rejected_and_never_serialized():
    cases = [
        ("합계 최대 6이다. 표본 500명을 더한다.", "unsupported_number"),          # 새 수치
        ("합계 최대 6이다. [확인 필요: 표본 500명]", "unsupported_number"),        # 자리표시 안이라도 원문·도구에 없는 수치
        ("합계 최대 6이다. 서울대학교와 협력한다.", "unsupported_fact"),          # 범위 밖 줄(4)의 기관명
        ("합계 최대 6이다. 99를 쓴다.", "unsupported_number"),                    # 범위 밖 줄(4)의 수치
        ("합계 최대 6이다. 이미 검증했다.", "unsupported_fact"),                  # 달성 주장
        ("합계 최대 6이다. 새로운 실험 장비를 도입한다.", "unsupported_content"),  # 범위에 없는 낱말
        ("합계 최대 6이다. a@example.com", "pii_or_identity"),
        ("합계 최대 6이다. <b>강조</b>", "unsafe_markup"),
    ]
    for after, reason in cases:
        out = run(after)
        assert out["corrections"][0]["reason"] == reason, (after, out["corrections"][0]["reason"])
        assert out["final_text"] == out["input_text"]
        assert after not in json.dumps(out, ensure_ascii=False)


def test_edit_outside_the_issue_scope_is_rejected():
    out = run("관련 없는 줄에 서울대학교와 99가 있다. 그리고", line=4, before="관련 없는 줄에 서울대학교와 99가 있다.")
    assert out["corrections"][0]["reason"] == "line_outside_issue" and out["final_text"] == out["input_text"]


def test_tool_numbers_are_not_available_when_the_check_did_not_run(monkeypatch):
    monkeypatch.setitem(sys.modules, "neumann.analyze.final_tools", None)
    out = run("합계 최대 6이다. [확인 필요: 항목 합 7이 상한 6을 넘음]")
    assert out["tool_checks_before"][0]["status"] == "unchecked"
    assert out["corrections"][0]["reason"] == "unsupported_number"  # 검사가 안 돌면 7은 근거 없는 수치다


def test_unchecked_reason_separates_hold_from_tool_failure(monkeypatch):
    p = provider([], issue={**ISSUE, "check_ids": []}, checks=())
    out = finalize_plan(PLAN, provider=p)
    assert out["issues"][0]["status"] == "unchecked" and out["issues"][0]["unchecked_reason"] == "no_tool_check"
    monkeypatch.setitem(sys.modules, "neumann.analyze.final_tools", None)
    out = finalize_plan(PLAN, provider=provider([]))
    assert out["issues"][0]["status"] == "unchecked" and out["issues"][0]["unchecked_reason"] == "도구 실행 불가"
    p = MockProvider(fail={ASSESSMENT_TASK: "timeout"})
    assert finalize_plan(PLAN, provider=p)["status"] == "incomplete"
