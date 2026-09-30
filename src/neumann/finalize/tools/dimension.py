"""unit_dimension 도구(FIN-TOOLS): Pint로 차원 호환·변환·규모(비율·자릿수)를 검사한다.

새 단위 대수를 만들지 않는다. Codex FINAL-TOOLS가 쓰는 Pint를 그대로 쓰고, 과학 ML 단위만 정의를 더한다.
- 정보량은 Pint 기본(bit·byte 무차원, ``Gb``=gilbert) 대신 [information] 차원의 ``infobit``·``infobyte``로 둔다.
- 샘플·토큰·에폭·스텝·FLOP·파라미터·GPU·명·건·원(KRW)·달러(USD)는 각자 차원이다(서로 더하면 차원 오류).
- 단위 문자열은 짧은 문법(영문·숫자·``* / ( ) ^``, 지수 절댓값 4 이하, 64자 이하)만 받는다. Pint는 자체 파서로 읽는다(eval 없음).

args(FIN-ENGINE 계약 + 추가)
- ``{"left": Q, "right": Q, "operation": "compare"|"add"|"equal", "relation"?: le|lt|ge|gt|eq, "tolerance"?: 상대오차}``
- ``{"quantity": Q, "expected_dimension": "S/cm"}``
- ``{"operation": "derive", "factors": [Q+{"power": ±1..3}], "expected": Q, "tolerance"?: 상대오차}``  (규모 검사)
Q = ``{"value": 수 또는 수 문자열, "unit": 단위}``. 결과 verdict: pass · fail · unchecked(검사 못 함, 통과 아님).
"""

from __future__ import annotations

import importlib
import math
import re
import threading
from fractions import Fraction
from typing import Any

from neumann.finalize.tools.quantities import _ASCII_UNITS, _KO_UNITS, _WORD_UNITS, parse_decimal

VERSION = "fin-tools.unit_dimension@1"
MAX_FACTORS = 8
_UNIT_RE = re.compile(r"^[A-Za-z0-9µμΩÅ°℃%_\s*/().\-^가-힣]{1,64}$")
_EXP_RE = re.compile(r"(\^|\*\*)\s*\(?\s*(-?\d+)")
_TOKEN_RE = re.compile(r"[A-Za-zµμΩÅ°℃%가-힣_][A-Za-z0-9µμΩÅ°℃%가-힣_\-]*")
RELATIONS = {"le": lambda a, b: a <= b, "lt": lambda a, b: a < b, "ge": lambda a, b: a >= b,
             "gt": lambda a, b: a > b, "eq": lambda a, b: a == b}
DEFINITIONS = (
    "infobit = [information]",
    "infobyte = 8 * infobit",
    "sample = [sample] = example",
    "token = [token]",
    "epoch = [epoch]",
    "step = [step] = iteration",
    "FLOP = [flop]",
    "FLOPS = FLOP / second",
    "petaflop_day = 1e15 * FLOP / second * day",
    "parameter = [parameter] = param",
    "gpu = [gpu] = GPU",
    "person = [person]",
    "record = [record]",
    "KRW = [currency_KRW]",
    "USD = [currency_USD]",
    "quarter_year = 3 * month",
)

_LOCK = threading.Lock()
_UREG: Any = None


class Unchecked(Exception):
    """검사하지 못함. 인자는 고정 사유 코드(입력값을 담지 않는다)."""


def registry() -> Any:
    """과정당 Pint 레지스트리 1개(생성이 느리다: 이 PC에서 import 수 초 + 생성 약 2초). 없으면 ImportError."""
    global _UREG
    with _LOCK:
        if _UREG is None:
            pint = importlib.import_module("pint")
            ureg = pint.UnitRegistry()
            for line in DEFINITIONS:
                ureg.define(line)
            _UREG = ureg
    return _UREG


def warmup() -> bool:
    try:
        registry()
        return True
    except Exception:  # noqa: BLE001 — 준비 실패는 첫 검사에서 unchecked로 드러난다
        return False


def normalize_unit(unit: Any) -> str:
    """표면형(GB·개월·mS/cm·%)을 Pint 식으로. 모르는 영문 낱말은 Pint에 그대로 맡긴다(없으면 unknown_unit)."""
    if type(unit) is not str or not _UNIT_RE.fullmatch(unit.strip()):
        raise Unchecked("invalid_unit")
    text = unit.strip()
    for m in _EXP_RE.finditer(text):
        if abs(int(m.group(2))) > 4:
            raise Unchecked("invalid_unit")
    whole = _KO_UNITS.get(text) or _ASCII_UNITS.get(text) or _WORD_UNITS.get(text.lower())
    if whole:
        return whole[0]

    def swap(m: re.Match[str]) -> str:
        tok = m.group()
        hit = _KO_UNITS.get(tok) or _ASCII_UNITS.get(tok) or _WORD_UNITS.get(tok.lower())
        if hit:
            return f"({hit[0]})"
        if re.search(r"[가-힣]", tok):
            raise Unchecked("unknown_unit")
        return tok

    return _TOKEN_RE.sub(swap, text)


def _value(raw: Any) -> Fraction:
    if isinstance(raw, bool):
        raise Unchecked("invalid_value")
    if isinstance(raw, int):
        value = Fraction(raw)
    elif isinstance(raw, float):
        if not math.isfinite(raw):
            raise Unchecked("invalid_value")
        value = Fraction(repr(raw))
    elif isinstance(raw, str):
        parsed = parse_decimal(raw)
        if parsed is None:
            raise Unchecked("invalid_value")
        value = parsed
    else:
        raise Unchecked("invalid_value")
    if abs(value) > Fraction(10) ** 30:
        raise Unchecked("invalid_value")
    return value


def stated_tolerance(raw: Any) -> float:
    """기대값을 적은 자릿수의 반 칸(27.8 → 0.05, 14 → 0.5)을 상대오차로. 최소 1e-9."""
    text = raw if isinstance(raw, str) else repr(raw)
    text = text.replace(",", "").strip()
    if isinstance(raw, float) and raw.is_integer():
        text = str(int(raw))
    value = abs(float(_value(raw)))
    if "e" in text.lower() or value == 0:
        return 1e-9
    decimals = len(text.split(".", 1)[1]) if "." in text else 0
    half = 0.5 * 10 ** (-decimals)
    return max(half / value, 1e-9)


def _quantity(q: Any, ureg: Any) -> tuple[Any, str, Any]:
    if type(q) is not dict or not set(q) <= {"value", "unit", "power"} or "unit" not in q:
        raise Unchecked("invalid_args")
    expr = normalize_unit(q["unit"])
    try:
        unit = ureg.parse_units(expr) if "(" not in expr and not re.search(r"\d", expr) else None
        if unit is None:
            parsed = ureg.parse_expression(expr)
            magnitude = float(getattr(parsed, "magnitude", parsed))
            unit = parsed.units if hasattr(parsed, "units") else ureg.dimensionless
        else:
            magnitude = 1.0
    except Exception as exc:  # noqa: BLE001 — Pint 예외 원문은 싣지 않는다
        raise Unchecked("unknown_unit") from exc
    value = float(_value(q["value"])) * magnitude if "value" in q else magnitude
    return ureg.Quantity(value, unit), q["unit"], q.get("value")


def _dim(qty: Any) -> str:
    d = qty.dimensionality
    return str(d) if len(d) else "dimensionless"


def _num(x: float) -> float:
    return float(f"{x:.12g}")


def _magnitude(left: Any, right: Any) -> dict[str, Any]:
    converted = left.to(right.units).magnitude
    out: dict[str, Any] = {"left_in_right_unit": _num(converted)}
    if right.magnitude != 0:
        ratio = converted / right.magnitude
        out["ratio"] = _num(ratio)
        if ratio > 0:
            out["log10_ratio"] = _num(math.log10(ratio))
            out["orders_of_magnitude"] = round(math.log10(ratio))
    return out


def _pair(args: dict[str, Any], ureg: Any) -> dict[str, Any]:
    operation = args.get("operation", "compare")
    if operation not in ("compare", "add", "equal"):
        raise Unchecked("invalid_operation")
    left, lu, _ = _quantity(args.get("left"), ureg)
    right, ru, rv = _quantity(args.get("right"), ureg)
    relation = args.get("relation")
    if relation is not None and relation not in RELATIONS:
        raise Unchecked("invalid_relation")
    compatible = left.dimensionality == right.dimensionality
    out: dict[str, Any] = {"operation": operation, "compatible": compatible, "left_unit": lu, "right_unit": ru,
                           "left_dimension": _dim(left), "right_dimension": _dim(right)}
    if not compatible:
        out.update(verdict="fail", reason="incompatible_dimensions")
        return out
    out.update(_magnitude(left, right))
    a, b = out["left_in_right_unit"], _num(right.magnitude)
    if operation == "equal" or relation == "eq":
        tol = args.get("tolerance")
        tol = stated_tolerance(rv) if tol is None else float(tol)
        if not (0 <= tol <= 1):
            raise Unchecked("invalid_tolerance")
        close = math.isclose(a, b, rel_tol=tol, abs_tol=0.0)
        out.update(relation="eq", tolerance=tol, verdict="pass" if close else "fail",
                   reason=None if close else "values_differ")
        return out
    if relation:
        holds = RELATIONS[relation](a, b)
        out.update(relation=relation, verdict="pass" if holds else "fail", reason=None if holds else "relation_violated")
        return out
    out["verdict"] = "pass"  # 더하기·비교가 차원상 가능하다(값의 타당성은 범위 밖)
    return out


def _expected_dimension(args: dict[str, Any], ureg: Any) -> dict[str, Any]:
    qty, qu, _ = _quantity(args.get("quantity"), ureg)
    expected, eu, _ = _quantity({"unit": args.get("expected_dimension")}, ureg)
    same = qty.dimensionality == expected.dimensionality
    return {"operation": "expected_dimension", "compatible": same, "unit": qu, "expected_unit": eu,
            "dimension": _dim(qty), "expected_dimension": _dim(expected),
            "verdict": "pass" if same else "fail", "reason": None if same else "incompatible_dimensions"}


def _derive(args: dict[str, Any], ureg: Any) -> dict[str, Any]:
    factors = args.get("factors")
    if type(factors) is not list or not 1 <= len(factors) <= MAX_FACTORS:
        raise Unchecked("invalid_args")
    result = None
    for f in factors:
        qty, _, _ = _quantity(f, ureg)
        power = f.get("power", 1)
        if type(power) is not int or power == 0 or abs(power) > 3:
            raise Unchecked("invalid_args")
        term = qty ** power
        result = term if result is None else result * term
    expected, eu, ev = _quantity(args.get("expected"), ureg)
    out: dict[str, Any] = {"operation": "derive", "expected_unit": eu, "computed_dimension": _dim(result),
                           "expected_dimension": _dim(expected)}
    if result.dimensionality != expected.dimensionality:
        out.update(compatible=False, verdict="fail", reason="incompatible_dimensions")
        return out
    computed = result.to(expected.units).magnitude
    tol = args.get("tolerance")
    tol = stated_tolerance(ev) if tol is None else float(tol)
    if not (0 <= tol <= 1):
        raise Unchecked("invalid_tolerance")
    out.update(compatible=True, computed=_num(computed), expected=_num(expected.magnitude), tolerance=tol)
    out.update({k: v for k, v in _magnitude(result, expected).items() if k != "left_in_right_unit"})
    close = math.isclose(computed, expected.magnitude, rel_tol=tol, abs_tol=0.0)
    out.update(verdict="pass" if close else "fail", reason=None if close else "magnitude_differs")
    return out


def run(args: dict[str, Any]) -> dict[str, Any]:
    """ToolSpec.run. 인자 오류·모르는 단위는 unchecked(사유 코드), Pint가 없으면 ImportError(→ tool_unavailable)."""
    if type(args) is not dict:
        return {"verdict": "unchecked", "reason": "invalid_args"}
    ureg = registry()
    try:
        with _LOCK:
            if "quantity" in args:
                out = _expected_dimension(args, ureg)
            elif args.get("operation") == "derive":
                out = _derive(args, ureg)
            else:
                out = _pair(args, ureg)
    except Unchecked as exc:
        return {"verdict": "unchecked", "reason": str(exc)}
    except (OverflowError, ZeroDivisionError, ValueError, TypeError, ArithmeticError):
        return {"verdict": "unchecked", "reason": "not_computable"}
    out["engine"] = "pint"
    return {k: v for k, v in out.items() if v is not None}


ARGS_SCHEMA = {
    "type": "object",
    "properties": {
        "operation": {"enum": ["compare", "add", "equal", "derive"]},
        "relation": {"enum": list(RELATIONS)},
        "tolerance": {"type": "number", "minimum": 0, "maximum": 1},
        "left": {"type": "object"}, "right": {"type": "object"}, "quantity": {"type": "object"},
        "expected_dimension": {"type": "string", "maxLength": 64},
        "factors": {"type": "array", "maxItems": MAX_FACTORS, "items": {"type": "object"}},
        "expected": {"type": "object"},
    },
    "additionalProperties": False,
}
