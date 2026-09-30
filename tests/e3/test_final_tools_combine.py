"""Numeric occurrence identity and homogeneous sum grounding, actual local Z3."""
import copy

import pytest

from neumann.analyze.final_tools import run_tool_checks
from tests.e3.test_final_tools import constraint


def row(plan, check):
    return run_tool_checks(plan, [check])[0]


def with_plan(plan):
    _, check = constraint()
    check["params"]["sources"] = [{"line": i + 1, "quote": line} for i, line in enumerate(plan.splitlines())]
    return check


def test_duplicate_terms_never_reach_solver():
    plan, check = constraint()
    check["params"]["terms"] = [check["params"]["terms"][0]] * 4
    out = row(plan, check)
    assert out["status"] == "unchecked" and out["message"] == "duplicate_numeric_fact"
    assert "computed" not in out["details"]


def test_duplicate_sources_cannot_alias_one_numeric_occurrence():
    plan, check = constraint()
    check["params"]["sources"].append(copy.deepcopy(check["params"]["sources"][0]))
    check["params"]["terms"][1] = {"source": 3, "value": 3}
    assert row(plan, check)["message"] == "duplicate_numeric_fact"


@pytest.mark.parametrize("plan", ["용량 합계 3\n온도 4\n용량 최대 10",
                                  "예산 합계 3만원\n기간 4개월\n예산 최대 10만원",
                                  "표본 합계 3개\n실험 4개\n표본 최대 10개",
                                  "알파 합계 3\n베타 4\n알파 최대 10",
                                  "용량 합계 3\n색상 4\n용량 최대 10"])
def test_mixed_concept_sums_are_unchecked(plan):
    out = row(plan, with_plan(plan))
    assert out["status"] == "unchecked"
    assert "computed" not in out["details"]


def test_cropped_quotes_cannot_hide_concepts():
    plan = "용량 합계 3\n온도 4\n용량 최대 10"
    check = with_plan(plan)
    check["params"]["sources"][1]["quote"] = "4"
    assert row(plan, check)["message"] == "mixed_quantity_concepts"


@pytest.mark.parametrize("limit,status", [(6, "failed"), (10, "passed")])
def test_computed_is_real_tool_output(limit, status):
    plan, check = constraint(limit)
    out = row(plan, check)
    assert out["status"] == status and out["details"]["computed"] == 7


def test_distinct_equal_values_are_not_duplicate_facts():
    plan = "장비 3만원\n재료 3만원\n예산 합계 최대 10만원"
    check = with_plan(plan)
    check["params"]["terms"][1]["value"] = 3
    out = row(plan, check)
    assert out["status"] == "passed" and out["details"]["computed"] == 6


def test_cropped_quote_cannot_turn_part_of_a_number_into_an_operand():
    plan, check = constraint()
    plan = plan.replace("총 3", "총 30")
    check["params"]["sources"][0]["quote"] = "3"
    assert row(plan, check)["message"] == "cropped_numeric_token"


def test_same_occurrence_cannot_be_both_term_and_limit():
    plan, check = constraint()
    check["params"]["terms"][1] = copy.deepcopy(check["params"]["limit"])
    assert row(plan, check)["message"] == "duplicate_numeric_fact"
