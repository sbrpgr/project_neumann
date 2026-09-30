"""unit_dimension(Pint): 차원 호환·변환·규모. 정상·경계·적대·시간."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from neumann.finalize.tools import ToolCall, ToolRegistry
from neumann.finalize.tools import dimension
from neumann.finalize.tools.fin_tools import register_all


def q(value, unit):
    return {"value": value, "unit": unit}


# (args, verdict, 추가 기대) — 변이 검사도 이 표를 쓴다.
CASES = [
    ({"left": q(3, "m"), "right": q(4, "cm"), "operation": "add"}, "pass", {"compatible": True}),
    ({"left": q(3, "m"), "right": q(4, "s"), "operation": "add"}, "fail", {"reason": "incompatible_dimensions"}),
    ({"left": q(10, "mS"), "right": q(1, "S/cm"), "operation": "compare"}, "fail", {"compatible": False}),
    ({"left": q(10, "mS/cm"), "right": q(1, "S/cm"), "operation": "compare"}, "pass", {"ratio": 0.01}),
    ({"left": q(3, "개월"), "right": q(2, "주"), "operation": "add"}, "pass", {}),
    ({"left": q(3, "개월"), "right": q(3, "억원"), "operation": "add"}, "fail", {}),
    ({"left": q(1, "GB"), "right": q(8, "Gb"), "operation": "equal"}, "pass", {}),           # Gb = 기가비트(gilbert 아님)
    ({"left": q(1, "GiB"), "right": q("1.000", "GB"), "operation": "equal"}, "fail", {}),  # 1.0737 GB
    ({"left": q(1, "GB"), "right": q(3, "%"), "operation": "add"}, "fail", {}),                # 정보량 ≠ 무차원
    ({"left": q(3, "TFLOPS"), "right": q(3, "TFLOPs"), "operation": "add"}, "fail", {}),       # 속도 ≠ 양
    ({"left": q(100, "samples"), "right": q(100, "tokens"), "operation": "add"}, "fail", {}),
    ({"left": q(120, "GB"), "right": q(80, "GB"), "relation": "le"}, "fail", {"reason": "relation_violated"}),
    ({"left": q(60, "GB"), "right": q(80, "GB"), "relation": "le"}, "pass", {}),
    ({"left": q(25, "°C"), "right": q(300, "K"), "relation": "lt"}, "pass", {}),               # 298.15 K < 300 K
    ({"left": q(1, "day"), "right": q(24, "h"), "operation": "equal"}, "pass", {}),
    ({"left": q(1, "day"), "right": q(25, "h"), "operation": "equal"}, "fail", {"reason": "values_differ"}),
    ({"left": q(1, "km"), "right": q(1, "m"), "operation": "compare"}, "pass", {"orders_of_magnitude": 3}),
    ({"quantity": q(10, "mS/cm"), "expected_dimension": "S/m"}, "pass", {}),
    ({"quantity": q(10, "mS"), "expected_dimension": "S/cm"}, "fail", {}),
    ({"operation": "derive", "factors": [dict(q("1e8", "sample"), power=1), dict(q(1000, "sample/s"), power=-1)],
      "expected": q("27.8", "h")}, "pass", {}),
    ({"operation": "derive", "factors": [dict(q("1e8", "sample"), power=1), dict(q(1000, "sample/s"), power=-1)],
      "expected": q(10, "h")}, "fail", {"reason": "magnitude_differs"}),
    ({"operation": "derive", "factors": [dict(q(8, "gpu"), power=1), dict(q(72, "h"), power=1)],
      "expected": q(576, "gpu * hour")}, "pass", {}),
    ({"operation": "derive", "factors": [dict(q(8, "gpu"), power=1), dict(q(72, "h"), power=1)],
      "expected": q(576, "hour")}, "fail", {"reason": "incompatible_dimensions"}),
    ({"operation": "derive", "factors": [dict(q(3, "PFLOPS"), power=1), dict(q(1, "day"), power=1)],
      "expected": q(3, "PF-day")}, "pass", {}),
    ({"operation": "derive", "factors": [dict(q("1e8", "(count) / second"), power=1)], "expected": q("1e8", "Hz")},
     "pass", {}),
]
BAD_UNITS = ["__import__('os')", "m^999", "m**9", "a" * 65, "1e308*1e308*m", "m;s", "definitely_not_a_unit",
             "개수불명", "m[0]", "lambda: 0", "{m}", ""]


@pytest.mark.parametrize("args,verdict,extra", CASES)
def test_pint_dimensions_conversion_and_magnitude(args, verdict, extra):
    out = dimension.run(args)
    assert out["verdict"] == verdict, out
    assert out["engine"] == "pint"
    for k, v in extra.items():
        assert out[k] == v, (k, out)


def test_stated_precision_tolerance():
    derive = {"operation": "derive", "factors": [dict(q("1e8", "sample"), power=1), dict(q(1000, "sample/s"), power=-1)]}
    assert dimension.run({**derive, "expected": q(28, "h")})["verdict"] == "pass"       # ±0.5
    assert dimension.run({**derive, "expected": q("28.0", "h")})["verdict"] == "fail"   # ±0.05
    assert dimension.run({**derive, "expected": q(28, "h"), "tolerance": 0})["verdict"] == "fail"


@pytest.mark.parametrize("unit", BAD_UNITS)
def test_unit_grammar_attacks_are_unchecked(unit):
    out = dimension.run({"left": q(1, unit), "right": q(1, "m"), "operation": "add"})
    assert out["verdict"] == "unchecked" and out["reason"] in {"invalid_unit", "unknown_unit", "not_computable"}


@pytest.mark.parametrize("args", [
    {"left": q(True, "m"), "right": q(1, "m")},
    {"left": q(float("nan"), "m"), "right": q(1, "m")},
    {"left": q("10**9", "m"), "right": q(1, "m")},
    {"left": q(1, "m"), "right": q(1, "m"), "operation": "multiply"},
    {"left": q(1, "m"), "right": q(1, "m"), "relation": "approx"},
    {"left": {"value": 1, "unit": "m", "code": "x"}, "right": q(1, "m")},
    {"operation": "derive", "factors": [], "expected": q(1, "m")},
    {"operation": "derive", "factors": [dict(q(1, "m"), power=9)], "expected": q(1, "m")},
    {"operation": "derive", "factors": [dict(q(1, "m"), power=1)] * 9, "expected": q(1, "m")},
    {"left": q(1, "m"), "right": q(1, "m"), "operation": "equal", "tolerance": 5},
    [], "m",
])
def test_invalid_args_are_unchecked(args):
    assert dimension.run(args)["verdict"] == "unchecked"


def test_pint_unavailable_is_tool_unavailable_not_pass():
    reg = ToolRegistry()
    register_all(reg)
    with patch.object(dimension, "registry", side_effect=ImportError("pint")):
        res = reg.run(ToolCall("unit_dimension", {"left": q(1, "m"), "right": q(1, "m")}))
    assert res.verdict == "unchecked" and res.error == "tool_unavailable"


def test_registry_evidence_and_time():
    reg = ToolRegistry()
    register_all(reg)
    t0 = time.perf_counter()
    for _ in range(50):
        res = reg.run(ToolCall("unit_dimension", {"left": q(3, "m"), "right": q(4, "s"), "operation": "add"}))
    assert time.perf_counter() - t0 < 5.0
    assert res.ok and res.verdict == "fail" and res.evidence["output"]["left_dimension"] == "[length]"
