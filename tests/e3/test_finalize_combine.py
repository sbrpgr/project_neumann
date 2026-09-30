"""FIN-COMBINE: code-owned placeholders and actual computed evidence (mock only)."""
from neumann.analyze.finalize import finalize_plan
from neumann.analyze.revise import PLACEHOLDER_RE
from tests.e3.test_finalize_gate import CHECK, ISSUE, PLAN, edit, provider


def test_placeholder_is_closed_template_not_model_prose():
    proposals = ["합계 최대 6이다. [확인 필요: 항목 합계 상한 대조]",
                 "합계 최대 6이다. [확인 필요: 연구자 결정 절차 추가]"]
    outputs = [finalize_plan(PLAN, provider=provider([edit(p)])) for p in proposals]
    for out in outputs:
        assert out["corrections"][0]["applied"]
        assert out["status"] == "partial"
        assert "[확인 필요: NUMERIC_CONSTRAINT; 줄 1, 2, 3; 계산값 7]" in out["final_text"]
        assert out["tool_checks_before"][0]["details"]["computed"] == 7
    assert outputs[0]["final_text"] == outputs[1]["final_text"]


def test_semantic_placeholder_uses_issue_lines_and_fixed_reason():
    out = finalize_plan(PLAN, provider=provider([edit("합계 최대 6이다. [확인 필요: 연구자 결정]")],
                        issue={**ISSUE, "check_ids": []}, checks=()))
    assert out["corrections"][0]["applied"]
    assert out["final_text"].splitlines()[2].endswith("[확인 필요: SEMANTIC_REVIEW; 줄 3]")


def test_unchecked_tool_cannot_supply_a_computed_number():
    duplicate = {**CHECK, "params": {**CHECK["params"], "terms": [CHECK["params"]["terms"][0]] * 2}}
    out = finalize_plan(PLAN, provider=provider([edit("합계 최대 6이다. [확인 필요: 항목 합계]")], checks=(duplicate,)))
    assert out["tool_checks_before"][0]["status"] == "unchecked"
    assert out["corrections"][0]["applied"]
    assert "[확인 필요: TOOL_UNCHECKED; 줄 1, 2, 3]" in out["final_text"]
    assert "계산값" not in out["final_text"]


def test_many_anchors_generate_bounded_placeholders_without_losing_lines():
    from neumann.analyze.finalize import _placeholder_template
    anchors = list(range(101, 901, 25))
    text = _placeholder_template(["i"], {"i": {"plan_lines": anchors, "check_ids": []}}, {}, {})
    bodies = PLACEHOLDER_RE.findall(text)
    assert bodies and PLACEHOLDER_RE.sub("", text).strip() == ""
    for anchor in anchors:
        assert str(anchor) in text
    assert all("SEMANTIC_REVIEW; 줄 " in body for body in bodies)


def test_repeated_placeholders_cannot_expand_beyond_the_edit_limit():
    plan = "\n".join(["방법을 검토한다."] * 30 + ["합계 최대 6이다."])
    issue = {**ISSUE, "plan_lines": list(range(1, 32)), "check_ids": []}
    proposal = "합계 최대 6이다. " + "[확인 필요: 확인] " * 100
    out = finalize_plan(plan, provider=provider([edit(proposal, line=31)], issue=issue, checks=()))
    assert out["corrections"][0]["reason"] == "invalid_line"
    assert out["final_text"] == out["input_text"]
