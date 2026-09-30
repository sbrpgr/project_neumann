"""arithmetic_sum 도구(FIN-TOOLS): 항목 합계 ↔ 적힌 총계(일정 개월·예산·분할 비율·표 합계).

정확한 유리수(Fraction) 산술로 계산하고, Z3가 있으면 같은 관계를 Z3 실수 산술로 한 번 더 확인한다(Codex FINAL-TOOLS와
같은 z3.RealVal 방식). 두 결과가 어긋나면 판정하지 않는다(unchecked). 부동소수 오차(0.1+0.2≠0.3)가 없다.

args ``{"items": [수…], "total": 수, "relation"?: "eq"|"le"|"ge", "tolerance"?: 절대오차(기본 0), "unit"?: 문자열,
"labels"?: [문자열…]}`` → output ``{"computed", "stated", "difference", "relation", "verdict", …}``.
수는 JSON 수 또는 수 문자열("12,000", "0.1"). 항목 1~64개, 절댓값 1e30 이하.
"""

from __future__ import annotations

import importlib
import math
from fractions import Fraction
from typing import Any

from neumann.analyze.final_tools import Z3_LOCK
from neumann.finalize.tools.quantities import parse_decimal

VERSION = "fin-tools.arithmetic_sum@1"
MAX_ITEMS = 64
MAX_ABS = Fraction(10) ** 30
RELATIONS = ("eq", "le", "ge")


class Unchecked(Exception):
    pass


def to_fraction(raw: Any) -> Fraction:
    if isinstance(raw, bool):
        raise Unchecked("invalid_number")
    if isinstance(raw, int):
        value = Fraction(raw)
    elif isinstance(raw, float):
        if not math.isfinite(raw):
            raise Unchecked("invalid_number")
        value = Fraction(repr(raw))  # 적힌 십진 표기 그대로(0.1 → 1/10)
    elif isinstance(raw, str):
        parsed = parse_decimal(raw)
        if parsed is None:
            raise Unchecked("invalid_number")
        value = parsed
    else:
        raise Unchecked("invalid_number")
    if abs(value) > MAX_ABS:
        raise Unchecked("number_out_of_range")
    return value


def plain(value: Fraction) -> int | float:
    return value.numerator if value.denominator == 1 else float(value)


def exact_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    d = value.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    if d == 1:  # 유한소수
        digits = 0
        while (value * 10**digits).denominator != 1:
            digits += 1
        return _fixed(value, digits)
    return f"{float(value):.12g}"


def _fixed(value: Fraction, digits: int) -> str:
    scaled = value * 10**digits
    sign = "-" if scaled < 0 else ""
    n = abs(scaled.numerator)
    whole, frac = divmod(n, 10**digits)
    return f"{sign}{whole}.{str(frac).rjust(digits, '0')}"


def _holds(relation: str, computed: Fraction, stated: Fraction, tol: Fraction) -> bool:
    if relation == "eq":
        return abs(computed - stated) <= tol
    if relation == "le":
        return computed <= stated + tol
    return computed >= stated - tol


def _z3_holds(relation: str, items: list[Fraction], stated: Fraction, tol: Fraction) -> bool | None:
    """Z3 교차 확인. 모듈이 없으면 None(분수 산술만으로 판정)."""
    try:
        z3 = importlib.import_module("z3")
    except ImportError:
        return None

    with Z3_LOCK:  # Z3 전역 컨텍스트는 스레드 안전하지 않다(VER-FIN C-1): 공용 잠금 + 호출마다 새 Context
        ctx = z3.Context()
        reals = [z3.RealVal(f"{x.numerator}/{x.denominator}", ctx) for x in items]
        total = z3.Sum(reals) if len(reals) > 1 else reals[0]
        rhs = z3.RealVal(f"{stated.numerator}/{stated.denominator}", ctx)
        t = z3.RealVal(f"{tol.numerator}/{tol.denominator}", ctx)
        if relation == "eq":
            relation_expr = z3.And(total - rhs <= t, rhs - total <= t)
        elif relation == "le":
            relation_expr = total <= rhs + t
        else:
            relation_expr = total >= rhs - t
        solver = z3.Solver(ctx=ctx)
        solver.set(timeout=200)
        solver.add(relation_expr)
        answer = solver.check()
        del solver, relation_expr, total, rhs, t, reals  # 잠금 안에서 Z3 참조와 컨텍스트를 모두 놓는다
        del ctx
    if answer == z3.unknown:
        raise Unchecked("solver_unknown")
    return answer == z3.sat


def run(args: dict[str, Any]) -> dict[str, Any]:
    if type(args) is not dict:
        return {"verdict": "unchecked", "reason": "invalid_args"}
    try:
        items_raw = args.get("items")
        if type(items_raw) is not list or not 1 <= len(items_raw) <= MAX_ITEMS:
            raise Unchecked("invalid_items")
        items = [to_fraction(x) for x in items_raw]
        stated = to_fraction(args.get("total"))
        relation = args.get("relation", "eq")
        if relation not in RELATIONS:
            raise Unchecked("invalid_relation")
        tol = to_fraction(args.get("tolerance", 0))
        if tol < 0:
            raise Unchecked("invalid_tolerance")
        computed = sum(items, Fraction(0))
        holds = _holds(relation, computed, stated, tol)
        z3_holds = _z3_holds(relation, items, stated, tol)
        if z3_holds is not None and z3_holds != holds:
            raise Unchecked("engine_disagreement")
    except Unchecked as exc:
        return {"verdict": "unchecked", "reason": str(exc)}
    out: dict[str, Any] = {
        "computed": plain(computed), "stated": plain(stated), "difference": plain(computed - stated),
        "computed_exact": exact_text(computed), "stated_exact": exact_text(stated),
        "relation": relation, "tolerance": plain(tol), "n_items": len(items),
        "engine": "fraction+z3" if z3_holds is not None else "fraction",
        "verdict": "pass" if holds else "fail",
    }
    if not holds:
        out["reason"] = {"eq": "sum_mismatch", "le": "sum_exceeds_total", "ge": "sum_below_total"}[relation]
    unit = args.get("unit")
    if type(unit) is str and len(unit) <= 32:
        out["unit"] = unit
    labels = args.get("labels")
    if type(labels) is list and len(labels) == len(items) and all(type(x) is str for x in labels):
        out["labels"] = [x[:80] for x in labels]
    return out


ARGS_SCHEMA = {
    "type": "object",
    "required": ["items", "total"],
    "properties": {
        "items": {"type": "array", "minItems": 1, "maxItems": MAX_ITEMS, "items": {"type": ["number", "string"]}},
        "total": {"type": ["number", "string"]},
        "relation": {"enum": list(RELATIONS)},
        "tolerance": {"type": ["number", "string"]},
        "unit": {"type": "string", "maxLength": 32},
        "labels": {"type": "array", "maxItems": MAX_ITEMS, "items": {"type": "string", "maxLength": 200}},
    },
    "additionalProperties": False,
}
