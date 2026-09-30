import copy
import threading
from unittest.mock import patch

import pytest

from neumann.analyze import final_tools as ft


def constraint(limit=10, operation="sum"):
    plan = f"총 3\n항목 4\n최대 {limit}"
    return plan, {"check_id": "budget", "kind": "constraint", "plan_lines": [1, 2, 3], "params": {"sources": [{"line": i + 1, "quote": line} for i, line in enumerate(plan.splitlines())], "operation": operation, "terms": [{"source": 0, "value": 3}, {"source": 1, "value": 4}], "comparator": "le", "limit": {"source": 2, "value": limit}}}


def units(right="cm"):
    plan = f"합산 3 m\n4 {right}"
    return plan, {"check_id": "dimension", "kind": "units", "plan_lines": [1, 2], "params": {"sources": [{"line": 1, "quote": "합산 3 m"}, {"line": 2, "quote": f"4 {right}"}], "operation": "addition", "left": {"source": 0, "value": 3, "unit": "m"}, "right": {"source": 1, "value": 4, "unit": right}}}


def dependency(cyclic=False):
    text = "수집 완료 후 분석 시작\n분석 완료 후 수집 시작" if cyclic else "수집 완료 후 분석 시작"
    sources = [{"line": i + 1, "quote": line} for i, line in enumerate(text.splitlines())]
    edges = [{"from": "a", "to": "b", "source": 0, "phrase": sources[0]["quote"]}]
    if cyclic:
        edges.append({"from": "b", "to": "a", "source": 1, "phrase": sources[1]["quote"]})
    return text, {"check_id": "dag", "kind": "dependency", "plan_lines": list(range(1, len(sources) + 1)), "params": {"sources": sources, "nodes": [{"id": "a", "source": 0, "phrase": "수집"}, {"id": "b", "source": 0, "phrase": "분석"}], "edges": edges}}


def run(pair):
    return ft.run_tool_checks(pair[0], [pair[1]])[0]


@pytest.mark.parametrize("limit,status", [(10, "passed"), (6, "failed")])
def test_actual_z3_constraint(limit, status):
    result = run(constraint(limit))
    assert result["status"] == status
    assert result["tool"] == "z3"


def test_actual_z3_product():
    plan, check = constraint(10, "product")
    plan = plan.replace("총", "곱")
    check["params"]["sources"][0]["quote"] = "곱 3"
    assert run((plan, check))["status"] == "failed"


@pytest.mark.parametrize("unit,status", [("cm", "passed"), ("s", "failed"), ("unknownunit", "unchecked")])
def test_actual_pint_units(unit, status):
    assert run(units(unit))["status"] == status


@pytest.mark.parametrize("cyclic,status", [(False, "passed"), (True, "failed")])
def test_actual_networkx_dag(cyclic, status):
    assert run(dependency(cyclic))["status"] == status


def test_feedback_is_not_hard_prerequisite_failure():
    plan, check = dependency(True)
    plan += " 피드백"
    check["params"]["sources"][1]["quote"] += " 피드백"
    check["params"]["edges"][1]["phrase"] += " 피드백"
    result = run((plan, check))
    assert result["status"] == "unchecked"
    assert result["message"] == "non_hard_dependency"


def test_reversed_dependency_direction_is_unchecked():
    plan, check = dependency()
    check["params"]["edges"][0].update({"from": "b", "to": "a"})
    assert run((plan, check))["message"] == "ambiguous_dependency_direction"


def test_cropped_quote_cannot_hide_feedback_or_negation():
    plan, check = dependency()
    for qualifier in [" 피드백", " not required"]:
        assert run((plan + qualifier, check))["message"] == "non_hard_dependency"


@pytest.mark.parametrize("builder", [constraint, units, dependency])
def test_unavailable_never_passes(builder):
    with patch.object(ft.importlib, "import_module", side_effect=ImportError("sensitive payload")):
        result = run(builder())
    assert result["status"] == "unchecked"
    assert result["message"] == "tool_unavailable"
    assert "sensitive" not in str(result)


def test_source_is_exact_and_line_anchored():
    plan, check = constraint()
    check["params"]["sources"][0]["quote"] = "총 999"
    assert run((plan, check))["message"] == "source_mismatch"
    check["params"]["sources"][0] = {"line": 2, "quote": "총 3"}
    assert run((plan, check))["status"] == "unchecked"


@pytest.mark.parametrize("value", [30, True, float("inf"), 1e10, "__import__('os').system('x')"])
def test_numbers_cannot_be_fabricated_or_code(value):
    plan, check = constraint()
    check["params"]["terms"][0]["value"] = value
    assert run((plan, check))["status"] == "unchecked"


def test_duplicate_numeric_mentions_ambiguous():
    plan, check = constraint()
    plan = plan.replace("총 3", "총 3 또는 3")
    check["params"]["sources"][0]["quote"] = "총 3 또는 3"
    assert run((plan, check))["message"] == "ambiguous_or_ungrounded_number"


def test_extra_code_params_rejected_without_execution():
    plan, check = constraint()
    check["params"]["code"] = "raise RuntimeError('secret')"
    result = run((plan, check))
    assert result["message"] == "invalid_parameters"
    assert "secret" not in str(result)


def test_units_must_be_contiguous_and_bounded():
    plan, check = units()
    check["params"]["left"]["unit"] = "s"
    assert run((plan, check))["message"] == "ungrounded_unit"
    check["params"]["left"]["unit"] = "m**999999999"
    assert run((plan, check))["message"] == "unsupported_unit"


def test_unanchored_unit_operation_is_unchecked():
    plan, check = units()
    plan = plan.replace("합산", "참고")
    check["params"]["sources"][0]["quote"] = "참고 3 m"
    assert run((plan, check))["message"] == "ungrounded_operation"


def test_check_and_fact_limits():
    plan, check = constraint()
    results = ft.run_tool_checks(plan, [copy.deepcopy(check) for _ in range(17)])
    assert len(results) == 16
    assert all(r["message"] == "check_limit_exceeded" for r in results)
    check["params"]["terms"] *= 17
    assert run((plan, check))["status"] == "unchecked"


def test_cancelled_check_is_not_passed():
    event = threading.Event()
    event.set()
    plan, check = constraint()
    assert ft.run_tool_checks(plan, [check], event)[0]["message"] == "cancelled"


def test_z3_unknown_and_timeout_are_unchecked():
    import z3
    plan, check = constraint()
    with patch.object(z3, "Solver") as factory:
        factory.return_value.check.return_value = z3.unknown
        result = run((plan, check))
        factory.return_value.set.assert_called_once_with(timeout=200)
    assert result["message"] == "solver_timeout_or_unknown"


def test_malformed_input_is_sanitized():
    assert ft.run_tool_checks("x", {}) == []
    for check in [None, {}, {"kind": []}, {"kind": "constraint", "params": {}}]:
        assert ft.run_tool_checks("x", [check])[0]["status"] == "unchecked"


def test_no_relation_marker_does_not_assert_correctness():
    plan, check = constraint()
    plan = plan.replace("최대", "참고")
    check["params"]["sources"][2]["quote"] = "참고 10"
    assert run((plan, check))["message"] == "ungrounded_comparator"
