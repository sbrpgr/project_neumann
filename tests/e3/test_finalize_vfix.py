"""V-finalization(e630d23) 재현의 회귀 테스트: F1 중복 검사 id, F3 짧은 주장·부정 변경, F4 수정 후 재검사, R8 엔진 상한.

실제 Z3·NetworkX를 쓴다(mock LLM, 실제 API 없음)."""

from __future__ import annotations

from neumann.analyze.finalize import ASSESSMENT_TASK, CORRECTION_TASK, MAX_PLAN_CHARS, finalize_plan
from neumann.llm import MockProvider


def provider(edits=(), issues=None, checks=()):
    return MockProvider(scripted={ASSESSMENT_TASK: [{"issues": list(issues or []), "checks": list(checks)}],
                                  CORRECTION_TASK: [{"edits": list(edits)}]})


def constraint(check_id, limit_line, limit):
    return {"check_id": check_id, "kind": "constraint", "plan_lines": [1, 2, limit_line], "params": {
        "sources": [{"line": 1}, {"line": 2}, {"line": limit_line}], "operation": "sum",
        "terms": [{"source": 0, "value": 3}, {"source": 1, "value": 4}], "comparator": "le", "limit": {"source": 2, "value": limit}}}


def test_f1_duplicate_check_ids_are_refused_not_overwritten():
    plan = "총 3\n항목 4\n최대 6\n최대 10"
    checks = [constraint("budget", 3, 6), constraint("budget", 4, 10)]  # 첫 검사는 실패, 둘째는 통과
    issue = {"issue_id": "i1", "kind": "logical", "plan_lines": [3], "message": "합계 대조", "check_ids": ["budget"]}
    p = provider(issues=[issue], checks=checks)
    out = finalize_plan(plan, provider=p)
    assert out["status"] == "incomplete" and any("중복" in n for n in out["notices"])
    assert out["counters"]["correction_calls"] == 0 and out["tool_checks_before"] == []
    ok = finalize_plan(plan, provider=provider(issues=[issue], checks=[constraint("budget", 3, 6), constraint("budget2", 4, 10)]))
    assert [r["status"] for r in ok["tool_checks_before"]] == ["failed", "passed"]
    assert ok["issues"][0]["status"] == "unresolved" and ok["status"] == "partial"


def test_f3_short_korean_claims_and_negations_are_rejected():
    issue = {"issue_id": "i1", "kind": "logical", "plan_lines": [1], "message": "방법 서술", "check_ids": []}
    for after, reason in [("치료 효과 입증", "unsupported_content"), ("효과 입증", "unsupported_content"),
                          ("방법을 안 검토한다.", "negation_change"), ("방법을 검토하지 않는다.", "negation_change"),
                          ("방법을 검토한다. 결과 없음", "negation_change"), ("Do not review the method.", "negation_change"),
                          ("Review the method thoroughly.", "unsupported_content")]:
        edit = {"line": 1, "current_text": "방법을 검토한다.", "replacement": after, "issue_ids": ["i1"]}
        out = finalize_plan("방법을 검토한다.", provider=provider([edit], [issue]))
        assert out["corrections"][0]["reason"] == reason, (after, out["corrections"][0]["reason"])
        assert out["final_text"] == out["input_text"]
    ok = finalize_plan("방법을 검토한다.", provider=provider([{"line": 1, "current_text": "방법을 검토한다.",
                       "replacement": "방법을 명확히 검토한다.", "issue_ids": ["i1"]}], [issue]))
    assert ok["corrections"][0]["applied"]


def dependency_check():
    return {"check_id": "dep", "kind": "dependency", "plan_lines": [1, 2], "params": {
        "sources": [{"line": 1}, {"line": 2}],
        "nodes": [{"id": "collect", "source": 0, "phrase": "수집"}, {"id": "analyze", "source": 0, "phrase": "분석"}],
        "edges": [{"from": "collect", "to": "analyze", "source": 0, "phrase": "수집 완료 후 분석 시작"},
                  {"from": "analyze", "to": "collect", "source": 1, "phrase": "분석 완료 후 수집 시작"}]}}


def test_f4_structural_fix_is_rechecked_against_the_corrected_text():
    plan = "수집 완료 후 분석 시작\n분석 완료 후 수집 시작"
    issue = {"issue_id": "i1", "kind": "structural", "plan_lines": [1, 2], "message": "선행 순환", "check_ids": ["dep"]}
    edit = {"line": 2, "current_text": "분석 완료 후 수집 시작", "replacement": "수집 완료 후 분석 시작", "issue_ids": ["i1"]}
    out = finalize_plan(plan, provider=provider([edit], [issue], [dependency_check()]))
    before, after = out["tool_checks_before"][0], out["tool_checks_after"][0]
    assert before["tool"] == "networkx" and before["status"] == "failed"
    assert after["status"] == "passed" and after["details"]["rebound_to_corrected_lines"] == [2]
    assert out["issues"][0]["status"] == "resolved" and out["status"] == "completed"
    assert out["counters"] == {"assessment_calls": 1, "correction_calls": 1, "correction_batches": 1, "recheck_runs": 1}


def test_f4_vanished_number_after_correction_is_unchecked_not_passed():
    plan = "총 3\n항목 4\n최대 6"
    issue = {"issue_id": "i1", "kind": "logical", "plan_lines": [1, 2, 3], "message": "합계", "check_ids": ["budget"]}
    edit = {"line": 3, "current_text": "최대 6", "replacement": "항목 최대", "issue_ids": ["i1"]}  # 상한 수치를 지운 수정
    out = finalize_plan(plan, provider=provider([edit], [issue], [constraint("budget", 3, 6)]))
    assert out["corrections"][0]["applied"]
    assert out["tool_checks_after"][0]["status"] == "unchecked" and out["issues"][0]["status"] == "unchecked"
    assert out["issues"][0]["unchecked_reason"] == "ambiguous_or_ungrounded_number"


def test_placeholders_left_in_the_draft_keep_status_partial():
    plan = "수집 완료 후 분석 시작\n분석 완료 후 수집 시작"
    issue = {"issue_id": "i1", "kind": "structural", "plan_lines": [1, 2], "message": "선행 순환", "check_ids": ["dep"]}
    edit = {"line": 2, "current_text": "분석 완료 후 수집 시작", "replacement": "수집 완료 후 분석 시작 [확인 필요: 순서]", "issue_ids": ["i1"]}
    out = finalize_plan(plan, provider=provider([edit], [issue], [dependency_check()]))
    assert out["issues"][0]["status"] == "resolved" and out["status"] == "partial"


def test_r8_engine_cap_stops_before_any_model_call():
    p = provider()
    out = finalize_plan("x" * (MAX_PLAN_CHARS + 1), provider=p)
    assert out["status"] == "incomplete" and p.calls == [] and out["counters"]["assessment_calls"] == 0
