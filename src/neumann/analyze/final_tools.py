"""Bounded, source-grounded checks; tool results cover only supplied facts.

Sources use one-based plan line numbers; fact ``source`` indices are zero-based.
No tool interprets model-generated code. Missing tools and ambiguous facts are
unchecked, never successful verification of the whole research plan.
"""
from __future__ import annotations

import importlib
import math
import re
from decimal import Decimal

MAX_CHECKS = 16
MAX_FACTS = 32
SOLVER_TIMEOUT_MS = 200
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w.])")
_TOOLS = {"constraint": "z3", "units": "pint", "dependency": "networkx"}


class _Unchecked(Exception):
    pass


def _require(condition, reason="invalid_parameters"):
    if not condition:
        raise _Unchecked(reason)


def _keys(value, expected):
    _require(type(value) is dict and set(value) == set(expected))


def _string(value, limit=256):
    _require(type(value) is str and 0 < len(value) <= limit)
    return value


def _list(value, limit=MAX_FACTS):
    _require(type(value) is list and 0 < len(value) <= limit)
    return value


def _number(value):
    _require(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e9)
    return Decimal(str(value))


def _source(index, sources):
    _require(type(index) is int and 0 <= index < len(sources))
    return sources[index]["quote"]


def _fact(fact, sources, units=False):
    _keys(fact, ("source", "value", "unit") if units else ("source", "value"))
    quote = _source(fact["source"], sources)
    value = _number(fact["value"])
    matches = [m for m in _NUMBER.finditer(quote) if Decimal(m.group()) == value]
    _require(len(matches) == 1, "ambiguous_or_ungrounded_number")
    if units:
        unit = _string(fact["unit"], 48)
        _require(bool(re.fullmatch(r"[A-Za-zµ°]+(?:[*/][A-Za-zµ°]+|\^[1-3])*", unit)), "unsupported_unit")
        _require(bool(re.match(r"\s*" + re.escape(unit) + r"(?![A-Za-zµ°])", quote[matches[0].end():])), "ungrounded_unit")
    return value


def _constraint(params, sources):
    _keys(params, ("sources", "operation", "terms", "comparator", "limit"))
    operation = params["operation"]
    comparator = params["comparator"]
    _require(operation in ("sum", "product") and comparator in ("le", "ge", "eq"))
    terms = [_fact(t, sources) for t in _list(params["terms"])]
    limit = _fact(params["limit"], sources)
    quotes = " ".join(s["quote"] for s in sources)
    marker = r"합계|총|sum|total|합산" if operation == "sum" else r"곱|product|×|\*"
    _require(bool(re.search(marker, quotes, re.I)), "ungrounded_operation")
    markers = {"le": r"이하|최대|<=|≤|at most", "ge": r"이상|최소|>=|≥|at least", "eq": r"같다|equal|(?<![<>])="}
    _require(bool(re.search(markers[comparator], _source(params["limit"]["source"], sources), re.I)), "ungrounded_comparator")
    z3 = importlib.import_module("z3")
    values = [z3.RealVal(str(v)) for v in terms]
    expr = z3.Sum(values) if operation == "sum" else values[0]
    if operation == "product":
        for value in values[1:]:
            expr = expr * value
    rhs = z3.RealVal(str(limit))
    relation = {"le": lambda: expr <= rhs, "ge": lambda: expr >= rhs, "eq": lambda: expr == rhs}[comparator]()
    solver = z3.Solver()
    solver.set(timeout=SOLVER_TIMEOUT_MS)
    solver.add(relation)
    answer = solver.check()
    if answer == z3.unknown:
        raise _Unchecked("solver_timeout_or_unknown")
    return answer == z3.sat, {"operation": operation, "comparator": comparator, "scope": "anchored_numeric_relation"}


def _units(params, sources):
    _keys(params, ("sources", "operation", "left", "right"))
    _require(params["operation"] in ("addition", "equality"))
    left = _fact(params["left"], sources, units=True)
    right = _fact(params["right"], sources, units=True)
    marker = r"합산|합계|더하|sum|add|\+" if params["operation"] == "addition" else r"같다|equal|="
    _require(bool(re.search(marker, " ".join(s["quote"] for s in sources), re.I)), "ungrounded_operation")
    # This checks dimensions only, not numerical equality or experimental validity.
    pint = importlib.import_module("pint")
    registry = pint.UnitRegistry()
    a = registry.Quantity(float(left), registry.Unit(params["left"]["unit"]))
    b = registry.Quantity(float(right), registry.Unit(params["right"]["unit"]))
    compatible = a.dimensionality == b.dimensionality
    if compatible:
        b.to(a.units)  # Exercise actual unit conversion, not a string comparison.
        if params["operation"] == "addition":
            a + b
    return compatible, {"scope": "dimensional_compatibility_only", "operation": params["operation"]}


def _dependency(params, sources):
    _keys(params, ("sources", "nodes", "edges"))
    nodes = _list(params["nodes"])
    edges = _list(params["edges"])
    phrases = {}
    for node in nodes:
        _keys(node, ("id", "source", "phrase"))
        identifier = _string(node["id"], 64)
        phrase = _string(node["phrase"], 128)
        _require(identifier not in phrases and phrase in _source(node["source"], sources), "ungrounded_node")
        phrases[identifier] = phrase
    pairs = []
    for edge in edges:
        _keys(edge, ("from", "to", "source", "phrase"))
        start, end = edge["from"], edge["to"]
        _require(type(start) is str and type(end) is str and start in phrases and end in phrases)
        phrase = _string(edge["phrase"])
        _require(phrase in _source(edge["source"], sources), "ungrounded_edge")
        _require(not re.search(r"feedback|피드백|반복|iteration|optional|선택|않|아니|불필요|\bnot\b", _source(edge["source"], sources), re.I), "non_hard_dependency")
        forward = re.escape(phrases[start]) + r".*(?:후|before|선행|prerequisite for).*" + re.escape(phrases[end])
        reverse = re.escape(phrases[end]) + r".*requires.*" + re.escape(phrases[start])
        _require(bool(re.search(forward, phrase, re.I) or re.search(reverse, phrase, re.I)), "ambiguous_dependency_direction")
        pairs.append((start, end))
    nx = importlib.import_module("networkx")
    graph = nx.DiGraph()
    graph.add_nodes_from(phrases)
    graph.add_edges_from(pairs)
    acyclic = nx.is_directed_acyclic_graph(graph)
    return acyclic, {"nodes": len(nodes), "edges": len(edges), "scope": "explicit_hard_prerequisites"}


def run_tool_checks(plan_text: str, checks: list[dict], cancel_event=None) -> list[dict]:
    """Return bounded checks with sanitized errors and exact source grounding."""
    if type(checks) is not list:
        return []
    results = []
    valid_plan = type(plan_text) is str and len(plan_text) <= 200_000
    lines = plan_text.splitlines() if valid_plan else []
    for index, check in enumerate(checks[:MAX_CHECKS]):
        check = check if type(check) is dict else {}
        kind = check.get("kind")
        kind = kind if type(kind) is str and kind in _TOOLS else "unknown"
        identifier = check.get("check_id")
        identifier = identifier if type(identifier) is str and re.fullmatch(r"[\w-]{1,64}", identifier) else f"check-{index + 1}"
        result = {"check_id": identifier, "kind": kind, "tool": _TOOLS.get(kind, "none"), "status": "unchecked", "plan_lines": [], "message": "invalid_parameters", "details": {}}
        try:
            _require(len(checks) <= MAX_CHECKS, "check_limit_exceeded")
            _require(valid_plan, "plan_limit_exceeded")
            _require(cancel_event is None or not cancel_event.is_set(), "cancelled")
            _require(kind in _TOOLS)
            anchors = _list(check.get("plan_lines"))
            _require(all(type(n) is int and 1 <= n <= len(lines) for n in anchors))
            result["plan_lines"] = sorted(set(anchors))
            params = check.get("params")
            _require(type(params) is dict)
            sources = _list(params.get("sources"))
            for source in sources:
                _keys(source, ("line", "quote"))
                line = source["line"]
                quote = _string(source["quote"])
                _require(type(line) is int and line in anchors and quote in lines[line - 1], "source_mismatch")
                # A cropped quote must not erase a qualification on the source line.
                if kind == "dependency":
                    _require(not re.search(r"feedback|피드백|반복|iteration|optional|선택|않|아니|불필요|\bnot\b", lines[line - 1], re.I), "non_hard_dependency")
            passed, details = {"constraint": _constraint, "units": _units, "dependency": _dependency}[kind](params, sources)
            _require(cancel_event is None or not cancel_event.is_set(), "cancelled")
            result.update(status="passed" if passed else "failed", message="bounded_check_passed" if passed else "bounded_check_failed", details=details)
        except _Unchecked as error:
            result["message"] = str(error)
        except (ImportError, ModuleNotFoundError):
            result["message"] = "tool_unavailable"
        except Exception:
            result["message"] = "tool_error_or_unsupported_parameters"
        results.append(result)
    return results
