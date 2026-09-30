"""Offline unit checks. Stub tool adapter tests engine orchestration, not tool validity."""
import sys
import json
import threading
import types

from neumann.analyze.finalize import (
    ASSESSMENT_TASK, CORRECTION_TASK, assessment_schema, correction_schema, finalize_plan,
)
from neumann.llm import MockProvider, check_strict_schema
from neumann.models import PlanDocument


def provider(edits=None, issues=None):
    return MockProvider(scripted={
        ASSESSMENT_TASK: [{"issues": issues if issues is not None else [{
            "issue_id": "i1", "kind": "logical", "plan_lines": [1],
            "message": "방법을 명확히 설명해야 합니다.", "check_ids": []}], "checks": []}],
        CORRECTION_TASK: [{"edits": edits or []}],
    })


def edit(after, before="방법을 검토한다.", **extra):
    return {"line": 1, "current_text": before, "replacement": after, "issue_ids": ["i1"], **extra}


def test_strict_schemas():
    assert not check_strict_schema(assessment_schema(3))
    assert not check_strict_schema(correction_schema(3))


def test_default_mock_is_honest_and_bounded():
    out = finalize_plan("방법을 검토한다.", provider="mock")
    assert out["status"] == "partial"
    assert out["generator"] == "mock"
    assert out["issues"][0]["status"] == "unchecked"
    assert {k: out["counters"][k] for k in ("assessment_calls", "correction_calls", "correction_batches", "recheck_runs")} == {
        "assessment_calls": 1, "correction_calls": 1, "correction_batches": 0, "recheck_runs": 0}
    assert out["counters"]["tool_runs"] == dict.fromkeys(("z3", "pint", "networkx", "citation"), 0)


def test_safe_edit_preserves_line_ids_and_semantic_residual():
    p = provider([edit("방법을 명확히 검토한다.")])
    out = finalize_plan("방법을 검토한다.\n목적을 유지한다.", provider=p)
    assert out["final_text"] == "방법을 명확히 검토한다.\n목적을 유지한다."
    assert out["output_plan_id"] == PlanDocument.from_text(out["final_text"], "test").plan_id
    assert out["issues"][0]["status"] == "unchecked"
    assert len(p.calls) == 2 and out["counters"]["correction_batches"] == 1


def test_numbers_entities_pii_markup_and_wrong_anchors_are_rejected():
    for after, reason in [("100명을 검토한다.", "unsupported_number"),
                          ("서울대학교에서 검토한다.", "unsupported_fact"),
                          ("치료 효과를 입증한다.", "unsupported_content"),
                          ("a@example.com에 연락한다.", "pii_or_identity"),
                          ("<script>검토</script>", "unsafe_markup")]:
        out = finalize_plan("방법을 검토한다.", provider=provider([edit(after)]))
        assert out["final_text"] == out["input_text"]
        assert out["corrections"][0]["reason"] == reason
        assert out["corrections"][0]["after"] == "[검사에서 제외된 수정안]"
        assert after not in json.dumps(out, ensure_ascii=False)
    out = finalize_plan("방법을 검토한다.", provider=provider([edit("검토한다.", before="다른 줄")]))
    assert out["corrections"][0]["reason"] == "anchor_mismatch"


def test_disabled_failure_and_malformed_schema_stop_calls():
    assert finalize_plan("본문", provider="off")["status"] == "incomplete"
    for failure in ("timeout", "api_error"):
        p = MockProvider(fail={ASSESSMENT_TASK: failure})
        out = finalize_plan("본문", provider=p)
        assert out["status"] == "incomplete" and len(p.calls) == 1
    p = MockProvider(scripted={ASSESSMENT_TASK: [{"issues": "bad", "checks": []}]})
    assert finalize_plan("본문", provider=p)["status"] == "incomplete"
    assert len(p.calls) == 1


def test_cancellation_before_and_after_assessment_stops():
    event = threading.Event()
    event.set()
    p = provider()
    out = finalize_plan("본문", provider=p, cancel_event=event)
    assert not p.calls and out["status"] == "incomplete"
    event.clear()
    def cancel(call):
        event.set()
        return {"issues": [], "checks": []}
    p = MockProvider(scripted={ASSESSMENT_TASK: [cancel]})
    out = finalize_plan("본문", provider=p, cancel_event=event)
    assert len(p.calls) == 1 and out["final_text"] == out["input_text"]


def test_targeted_recheck_once_with_stub_adapter(monkeypatch):
    calls = []
    def run(text, checks, event):
        calls.append((text, checks))
        return [{"check_id": c["check_id"], "kind": c["kind"], "tool": "stub",
                 "status": "fail" if len(calls) == 1 else "pass", "plan_lines": c["plan_lines"],
                 "message": "검사", "details": {}} for c in checks]
    monkeypatch.setitem(sys.modules, "neumann.analyze.final_tools", types.SimpleNamespace(run_tool_checks=run))
    checks = [{"check_id": "c1", "kind": "constraint", "plan_lines": [1], "params": {"sources": [{"line": 1}]}},
              {"check_id": "c2", "kind": "constraint", "plan_lines": [2], "params": {"sources": [{"line": 2}]}}]
    issues = [{"issue_id": "i1", "kind": "logical", "plan_lines": [1], "message": "검사", "check_ids": ["c1"]}]
    out = finalize_plan("방법을 검토한다.\n다른 줄", provider=provider([edit("방법을 명확히 검토한다.")], issues), checks=checks)
    assert len(calls) == 2 and len(calls[1][1]) == 1
    assert out["counters"]["recheck_runs"] == 1
    assert out["issues"][0]["status"] == "resolved"
    assert out["issues"][1]["status"] == "unresolved"
    assert out["status"] == "partial"


def test_check_limit_and_missing_tools_are_honest(monkeypatch):
    out = finalize_plan("본문", provider=provider(), checks=[{}] * 17)
    assert out["status"] == "incomplete" and out["counters"]["correction_calls"] == 0
    monkeypatch.setitem(sys.modules, "neumann.analyze.final_tools", None)
    out = finalize_plan("본문", provider=provider(), checks=[{"check_id": "x", "kind": "constraint", "plan_lines": [1]}])
    assert out["tool_checks_before"][0]["status"] == "unchecked"
    assert out["status"] == "partial"


def test_success_is_bounded_draft_with_notice():
    out = finalize_plan("본문", provider=provider(issues=[]))
    assert out["status"] == "completed"
    assert "보장하지" in out["notices"][0]


def test_provider_exception_is_sanitized():
    def broken(call):
        raise RuntimeError("sensitive request")
    out = finalize_plan("본문", llm_call=broken)
    assert out["status"] == "incomplete" and "sensitive" not in str(out)


def test_correction_failure_retains_original_and_no_recheck():
    p = provider()
    p.fail[CORRECTION_TASK] = "timeout"
    out = finalize_plan("방법을 검토한다.", provider=p)
    assert out["status"] == "incomplete"
    assert out["final_text"] == out["input_text"]
    assert out["counters"]["assessment_calls"] == 1
    assert out["counters"]["correction_calls"] == 1
    assert out["counters"]["recheck_runs"] == 0
    assert "check_ids" not in out["issues"][0]


def test_cancel_after_correction_discards_batch_and_stops():
    event = threading.Event()
    def cancelled_correction(call):
        event.set()
        return {"edits": [edit("방법을 명확히 검토한다.")]}
    p = provider()
    p.scripted[CORRECTION_TASK] = [cancelled_correction]
    out = finalize_plan("방법을 검토한다.", provider=p, cancel_event=event)
    assert out["status"] == "incomplete"
    assert len(p.calls) == 2
    assert out["final_text"] == out["input_text"]
    assert out["counters"]["correction_batches"] == 0
