"""arithmetic_sum: 정상·경계·적대·시간. 정확한 유리수 + Z3 교차 확인, 실패는 unchecked(통과 아님)."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from neumann.finalize.tools import ToolCall, ToolRegistry
from neumann.finalize.tools import sums
from neumann.finalize.tools.fin_tools import register_all

# (args, verdict, 추가 기대) — 변이 검사(test_fin_tools_mutation)도 이 표를 쓴다.
CASES = [
    ({"items": [3, 4, 3], "total": 10}, "pass", {"computed": 10}),
    ({"items": [3, 4, 3], "total": 12}, "fail", {"computed": 10, "difference": -2, "reason": "sum_mismatch"}),
    ({"items": [0.1, 0.2], "total": 0.3}, "pass", {"computed_exact": "0.3"}),          # 부동소수 오차 없음
    ({"items": ["0.1", "0.2"], "total": "0.30000000000000004"}, "fail", {}),
    ({"items": ["12,000", "3,000"], "total": "15,000"}, "pass", {"computed": 15000}),
    ({"items": [70, 20, 20], "total": 100}, "fail", {"computed": 110}),
    ({"items": [5, 6], "total": 10, "relation": "le"}, "fail", {"reason": "sum_exceeds_total"}),
    ({"items": [5, 5], "total": 10, "relation": "le"}, "pass", {}),
    ({"items": [4, 5], "total": 10, "relation": "ge"}, "fail", {"reason": "sum_below_total"}),
    ({"items": [99.9, 0.05], "total": 100, "tolerance": 0.05}, "pass", {}),
    ({"items": [99.9, 0.04], "total": 100, "tolerance": 0.05}, "fail", {}),
    ({"items": [1, 2], "total": 4, "tolerance": 1}, "pass", {}),
    ({"items": [-1, 1], "total": 0}, "pass", {}),
    ({"items": [10**29, 10**29], "total": 2 * 10**29}, "pass", {}),
]
BAD = [
    {"items": [True, 1], "total": 2},
    {"items": [float("inf")], "total": 1},
    {"items": [float("nan")], "total": 1},
    {"items": [10**31], "total": 1},
    {"items": ["__import__('os').system('x')"], "total": 1},
    {"items": ["1e999"], "total": 1},
    {"items": [], "total": 0},
    {"items": [1] * 65, "total": 65},
    {"items": [1], "total": None},
    {"items": [1], "total": 1, "relation": "ne"},
    {"items": [1], "total": 1, "tolerance": -1},
    {"items": "1,2,3", "total": 6},
    {"items": [[1]], "total": 1},
]


@pytest.mark.parametrize("args,verdict,extra", CASES)
def test_normal_and_boundary(args, verdict, extra):
    out = sums.run(args)
    assert out["verdict"] == verdict, out
    for k, v in extra.items():
        assert out[k] == v, (k, out)


@pytest.mark.parametrize("args", BAD)
def test_adversarial_inputs_are_unchecked_not_pass(args):
    out = sums.run(args)
    assert out["verdict"] == "unchecked" and out["reason"]
    assert "import" not in str(out)


def test_z3_cross_check_is_used_and_absence_falls_back_to_exact_fractions():
    assert sums.run({"items": [1, 2], "total": 3})["engine"] == "fraction+z3"
    real = sums.importlib.import_module

    def no_z3(name, *a, **k):
        if name == "z3":
            raise ImportError("z3")
        return real(name, *a, **k)

    with patch.object(sums.importlib, "import_module", side_effect=no_z3):
        out = sums.run({"items": [1, 2], "total": 4})
    assert out["engine"] == "fraction" and out["verdict"] == "fail"


def test_engine_disagreement_is_never_a_verdict():
    with patch.object(sums, "_z3_holds", return_value=False):
        out = sums.run({"items": [1, 2], "total": 3})
    assert out == {"verdict": "unchecked", "reason": "engine_disagreement"}


def test_registry_integration_schema_and_evidence():
    reg = ToolRegistry()
    assert "arithmetic_sum" in register_all(reg)
    res = reg.run(ToolCall("arithmetic_sum", {"items": [3, 4, 3], "total": 12, "unit": "month"}, check_id="s1"))
    assert res.ok and res.verdict == "fail" and res.evidence["tool"] == "arithmetic_sum"
    assert res.evidence["version"] == sums.VERSION and res.evidence["output"]["computed"] == 10
    bad = reg.run(ToolCall("arithmetic_sum", {"items": [1], "total": 1, "code": "SECRET"}))
    assert bad.verdict == "unchecked" and bad.error == "invalid_args" and "SECRET" not in str(bad.evidence["reason"])


def test_time_bound_worst_case():
    t0 = time.perf_counter()
    out = sums.run({"items": [f"{i}.123456789" for i in range(64)], "total": "1"})
    assert out["verdict"] == "fail" and time.perf_counter() - t0 < 2.0
