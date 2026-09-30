"""시연용 scripted mock(finalize_demo): 심은 논리·물리·구조 오류를 실제 도구(Z3·Pint·NetworkX)로 확인하고 그 자리에서 고친다.

대본은 NEUMANN_DEMO_SCRIPT=1일 때만 켜지고(운영 기본 꺼짐), mock 라벨은 유지되며, 다른 계획서에는 기존 정직한 기본 mock이 나온다."""

from __future__ import annotations

import pytest

from neumann.analyze.finalize import finalize_plan
from neumann.analyze.finalize_demo import DEMO_PLAN
from neumann.analyze.revise import PLACEHOLDER_RE


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("NEUMANN_DEMO_SCRIPT", "1")


def test_demo_script_is_off_by_default(monkeypatch):
    monkeypatch.delenv("NEUMANN_DEMO_SCRIPT", raising=False)
    out = finalize_plan(DEMO_PLAN, provider="mock")
    assert out["corrections"] == [] and out["issues"][0]["issue_id"] == "mock-semantic"
    assert out["code_selected_checks"] > 0
    assert all(r["details"]["code_selected"] for r in out["tool_checks_before"])


def test_demo_plan_is_found_fixed_in_place_and_tool_grounded(demo_on):
    out = finalize_plan(DEMO_PLAN, provider="mock")
    assert out["generator"] == "mock" and any("mock" in n for n in out["notices"])
    assert {k: out["counters"][k] for k in ("assessment_calls", "correction_calls", "correction_batches", "recheck_runs")} == {
        "assessment_calls": 1, "correction_calls": 1, "correction_batches": 1, "recheck_runs": 1}
    tools = {r["check_id"]: r for r in out["tool_checks_before"]}
    assert {(r["tool"], r["status"]) for r in tools.values() if not r["check_id"].startswith("code:")} == {
        ("z3", "failed"), ("pint", "failed"), ("networkx", "failed")}
    issues = {i["issue_id"]: i for i in out["issues"]}
    assert issues["demo-budget"]["kind"] == "physical" and issues["demo-units"]["kind"] == "physical"
    assert issues["demo-order"]["kind"] == "structural" and issues["demo-contra"]["kind"] == "logical"
    applied = {c["line"]: c for c in out["corrections"] if c["applied"]}
    assert len(applied) == 4 and all(not c["applied"] or c["reason"] == "applied" for c in out["corrections"])
    final = out["final_text"].split("\n")
    assert all("[확인 필요:" in final[n - 1] for n in applied)
    budget_line = final[issues["demo-budget"]["plan_lines"][0] - 1]
    assert "최대 4000만원이다." in budget_line  # 원문 수치는 그대로
    computed = tools["demo-budget"].get("details", {}).get("computed")
    body = "".join(PLACEHOLDER_RE.findall(budget_line))
    assert ("4200" in body) == (computed == 4200)  # 계산값은 도구 details.computed가 있을 때만, 자리표시 안에만
    assert "4200" not in PLACEHOLDER_RE.sub("", budget_line)
    assert issues["demo-contra"]["status"] == "unchecked" and issues["demo-contra"]["unchecked_reason"] == "no_tool_check"
    assert all(issues[k]["status"] == "unresolved" for k in ("demo-budget", "demo-units", "demo-order"))
    assert {r["check_id"] for r in out["tool_checks_after"] if not r["check_id"].startswith("code:")} == {
        "demo-budget", "demo-units", "demo-order"}
    assert out["status"] == "partial" and out["output_plan_id"] != out["input_plan_id"]
    unchanged = [a for a, b in zip(out["input_text"].split("\n"), final, strict=True) if a == b]
    assert len(unchanged) == len(final) - 4


def test_other_plans_get_the_honest_default_mock(demo_on):
    out = finalize_plan("방법을 검토한다.\n목적을 유지한다.", provider="mock")
    assert out["corrections"] == [] and out["tool_checks_before"] == []
    assert out["issues"][0]["issue_id"] == "mock-semantic" and out["issues"][0]["unchecked_reason"] == "no_tool_check"


def test_demo_script_anchors_follow_the_payload_not_fixed_line_numbers(demo_on):
    out = finalize_plan("머리말 줄\n\n" + DEMO_PLAN, provider="mock")
    lines = out["final_text"].split("\n")
    budget = next(i for i in out["issues"] if i["issue_id"] == "demo-budget")
    assert "4000만원이다" in lines[budget["plan_lines"][0] - 1]
    assert sum(c["applied"] for c in out["corrections"]) == 4


def test_demo_plan_with_a_flaw_removed_only_reports_the_remaining_ones(demo_on):
    fixed = DEMO_PLAN.replace("모델 학습 후 데이터 정제 기준을 확정한다.", "정제 기준은 별도 문서를 따른다.")
    out = finalize_plan(fixed, provider="mock")
    ids = {i["issue_id"] for i in out["issues"]}
    assert "demo-order" not in ids and {"demo-budget", "demo-units", "demo-contra"} <= ids
    assert {r["tool"] for r in out["tool_checks_before"] if not r["check_id"].startswith("code:")} == {"z3", "pint"}
