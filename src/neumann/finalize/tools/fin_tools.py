"""FIN-TOOLS 등록: FIN-ENGINE 레지스트리(`neumann.finalize.tools`, 도구 이름 z3·pint·networkx)에 구현을 붙인다.

    from neumann.finalize.tools.fin_tools import register_all, run_call
    register_all()                                   # 엔진 이름(z3·pint·networkx)에 FIN-TOOLS 구현을 별칭으로 붙인다
    from neumann.finalize.tools.extract import extract_checks, run_checks
    results = run_checks(extract_checks(plan_text))  # 규칙 추출 → 코드가 정한 도구 → ToolResult

별칭(E-8): 엔진 레지스트리는 TOOL_NAMES(z3·pint·networkx) 밖의 이름을 거절한다. 그래서 FIN-TOOLS 도구는 같은 계산 엔진을
쓰는 엔진 이름으로 등록한다 — arithmetic_sum → z3(Fraction + Z3 교차 확인), unit_dimension → pint, structure → networkx.
등록된 도구는 인자 모양으로 나눈다: ``{"plan_text", "check"}``(엔진·final_tools 형식)은 엔진의 final_tools 어댑터에 그대로
넘기고, 그 밖(FIN-TOOLS 형식)은 FIN-TOOLS 구현이 받는다. 엔진 이름에 없는 citation_lookup은 `run_call`이 같은 ToolResult
모양(evidence 포함)으로 FIN-TOOLS 안에서 돌린다. calculator·restricted_exec는 만들지 않는다(조정) — 호출은 unchecked.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from neumann.finalize import tools as engine
from neumann.finalize.tools import ToolCall, ToolRegistry, ToolResult, ToolSpec, registry
from neumann.finalize.tools import citation, dimension, structure, sums

log = logging.getLogger(__name__)

# FIN-TOOLS 점검 유형 → 호출할 도구 이름(엔진 이름이 있으면 엔진 이름). 추출기가 쓴다. 도구 선택은 이 표가 정한다(LLM 아님).
FIN_TOOL_FOR_KIND: dict[str, str] = {
    "sum": "z3", "unit": "pint", "structure": "networkx", "reference": "networkx",
    "citation": "citation_lookup", "arithmetic": "calculator",
}
# FIN-TOOLS 옛 이름 → 엔진 이름(별칭)
ALIASES: dict[str, str] = {"arithmetic_sum": "z3", "unit_dimension": "pint", "structure": "networkx"}
_IMPL: dict[str, tuple[str, Callable[[dict], dict], str, dict]] = {
    "z3": ("arithmetic_sum", sums.run, sums.VERSION, sums.ARGS_SCHEMA),
    "pint": ("unit_dimension", dimension.run, dimension.VERSION, dimension.ARGS_SCHEMA),
    "networkx": ("structure", structure.run, structure.VERSION, structure.ARGS_SCHEMA),
}
_LOCAL: dict[str, tuple[Callable[[dict], dict], str, dict]] = {
    "citation_lookup": (citation.run, citation.VERSION, citation.ARGS_SCHEMA),
}

CHECK_TOOL_TABLE: tuple[dict[str, Any], ...] = (
    {"kind": "sum", "tool": "z3", "impl": "fin_tools.sums (Fraction + Z3 교차 확인, Z3_LOCK)",
     "labels": ("split_sum", "schedule_sum", "schedule_span", "budget_sum", "table_sum", "expr_sum")},
    {"kind": "unit", "tool": "pint", "impl": "fin_tools.dimension (Pint)", "labels": ("unit_derive", "unit_add", "unit_compare")},
    {"kind": "structure", "tool": "networkx", "impl": "fin_tools.structure (NetworkX)", "labels": ("sections",)},
    {"kind": "reference", "tool": "networkx", "impl": "fin_tools.structure (NetworkX)", "labels": ("references",)},
    {"kind": "citation", "tool": "citation_lookup", "impl": "fin_tools.citation (MCP 백엔드, FIN-TOOLS 안에서 실행)",
     "labels": ("citation",)},
    {"kind": "arithmetic", "tool": "calculator", "impl": "없음(unchecked)", "labels": ("arith_expr",)},
)


def _adapter(name: str) -> ToolSpec | None:
    return next((s for s in getattr(engine, "ADAPTERS", ()) if s.name == name), None)


def _dispatch(name: str, fin_run: Callable[[dict], dict]) -> Callable[[dict], dict]:
    adapter = _adapter(name)

    def run(args: dict[str, Any]) -> dict[str, Any]:
        if isinstance(args, dict) and "plan_text" in args and "check" in args:  # 엔진(final_tools) 형식
            if adapter is None:
                return {"verdict": "unchecked", "reason": "adapter_unavailable"}
            return adapter.run(args)
        return fin_run(args)

    return run


def specs() -> list[ToolSpec]:
    out = []
    for name, (fin_name, fin_run, version, schema) in _IMPL.items():
        if name not in engine.TOOL_NAMES:
            continue
        adapter = _adapter(name)
        any_of = [dict(schema)] + ([dict(adapter.args_schema)] if adapter and adapter.args_schema else [])
        out.append(ToolSpec(name=name, description=f"FIN-TOOLS {fin_name} + final_tools {name} 어댑터",
                            run=_dispatch(name, fin_run),
                            version=f"{version}+{adapter.version if adapter else 'no-adapter'}",
                            args_schema={"anyOf": any_of}, timeout_s=10.0))
    return out


def register_all(reg: ToolRegistry | None = None, *, replace: bool = True) -> list[str]:
    """엔진 레지스트리에 FIN-TOOLS 구현을 엔진 이름으로 붙인다(이미 같은 판이면 그대로). 붙인 이름을 돌려준다."""
    target = reg or registry
    names = []
    for spec in specs():
        existing = target.get(spec.name)
        if existing is not None and (existing.version == spec.version or not replace):
            continue
        target.register(spec, replace=existing is not None)
        names.append(spec.name)
    return names


def _local(name: str, call: ToolCall, cancel_event: Any) -> ToolResult:
    """엔진 이름 밖의 도구(citation_lookup)·없는 도구(calculator)를 엔진과 같은 ToolResult·evidence 모양으로."""
    t0 = time.perf_counter()
    entry = _LOCAL.get(name)
    base = {"tool": name, "version": entry[1] if entry else None, "interface": getattr(engine, "INTERFACE_VERSION", None),
            "input": engine._jsonable(dict(call.args)) if isinstance(call.args, dict) else None, "check_id": call.check_id}

    def done(output: dict[str, Any], error: str | None) -> ToolResult:
        ok = error is None and output.get("verdict") in ("pass", "fail")
        ev = {**base, "output": output, "verdict": output.get("verdict") if ok else "unchecked",
              "reason": output.get("reason"), "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2)}
        return ToolResult(ok=ok, output=output, evidence=ev, error=None if ok else (error or "unchecked"))

    if entry is None:
        return done({"verdict": "unchecked", "reason": "tool_not_registered"}, "tool_unavailable")
    if cancel_event is not None and cancel_event.is_set():
        return done({"verdict": "unchecked", "reason": "cancelled"}, "cancelled")
    fn, _version, schema = entry
    try:
        import jsonschema

        if not isinstance(call.args, dict) or any(True for _ in jsonschema.Draft202012Validator(schema).iter_errors(call.args)):
            return done({"verdict": "unchecked", "reason": "invalid_args"}, "invalid_args")
    except ImportError:
        pass
    try:
        output = fn(dict(call.args))
    except ImportError:
        return done({"verdict": "unchecked", "reason": "tool_unavailable"}, "tool_unavailable")
    except TimeoutError:
        return done({"verdict": "unchecked", "reason": "timeout"}, "timeout")
    except Exception as exc:  # noqa: BLE001 — 예외 원문은 남기지 않는다
        log.warning("tool %s failed kind=%s", name, type(exc).__name__)
        return done({"verdict": "unchecked", "reason": f"tool_error: {type(exc).__name__}"}, "tool_error")
    if not isinstance(output, dict) or output.get("verdict") not in ("pass", "fail", "unchecked"):
        return done({"verdict": "unchecked", "reason": "invalid_output"}, "tool_error")
    return done(engine._jsonable(output), None)


def run_call(call: ToolCall, *, reg: ToolRegistry | None = None, cancel_event: Any = None) -> ToolResult:
    """FIN-TOOLS 호출 1건: 옛 이름은 엔진 이름으로 바꿔 엔진 레지스트리로, 엔진 이름 밖은 FIN-TOOLS 안에서 돌린다."""
    name = ALIASES.get(call.name, call.name)
    if name in engine.TOOL_NAMES:
        target = reg or registry
        register_all(target)
        return target.run(ToolCall(name, call.args, check_id=call.check_id), cancel_event=cancel_event)
    return _local(name, call, cancel_event)


def warmup() -> dict[str, bool]:
    """느린 import(Pint 수 초·NetworkX 수 초)를 미리 한다. 서버 기동 때 한 번 부른다."""
    import importlib

    ok = {"pint": dimension.warmup()}
    for mod in ("networkx", "z3"):
        try:
            importlib.import_module(mod)
            ok[mod] = True
        except ImportError:
            ok[mod] = False
    return ok


__all__ = ["ALIASES", "CHECK_TOOL_TABLE", "FIN_TOOL_FOR_KIND", "register_all", "run_call", "specs", "warmup"]
