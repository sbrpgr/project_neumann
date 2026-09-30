"""FIN-ENGINE ↔ FIN-TOOLS 도구 인터페이스(공유 계약). 실제 계산은 ``neumann.analyze.final_tools``(Z3·Pint·NetworkX)가 한다.

    from neumann.finalize.tools import ToolCall, ToolResult, run_tool, tool_for

    call   = ToolCall(name="z3", args={"plan_text": text, "check": check})   # check = final_tools 검사 1건(원문 발췌 앵커)
    result = run_tool(call)                                                # → ToolResult(ok, output, evidence)
    result.verdict                                                         # "pass" | "fail" | "unchecked"

원칙(대표 원칙·AGENTS.md)
- **도구 선택은 코드가 한다.** 점검 유형(check kind) → 도구 이름은 `TOOL_FOR_CHECK` 표 하나로 고정한다(constraint→z3,
  units→pint, dependency→networkx). LLM은 "어느 줄의 어떤 종류의 조건을 검사하라"(줄 번호·값)만 가리키고 도구 이름·인용문을
  정하지 않는다. 인용문은 코드가 원문 줄에서 붙인다(`finalize._bind_sources`).
- **수치·단위·합계 판정은 도구 결과로만 한다.** `ToolResult.ok=False`는 "검사하지 못함(unchecked)"이지 통과가 아니다. 도구가
  없거나(ImportError) 인자가 어긋나거나 시간·취소가 걸리면 `unchecked`로 남고, 엔진은 그 항목을 판단 보류로 둔다.
- **근거 정직성.** `ToolResult.evidence`는 {tool, version, input, output, verdict, reason, elapsed_ms}다. 예외 원문·경로·
  비밀값은 evidence에 넣지 않는다(종류만). 모델이 만든 코드는 어떤 도구도 실행하지 않는다.

도구 이름과 인자(모두 `args = {"plan_text": str, "check": dict}`; check 형식은 `docs/reports/FINAL-TOOLS.md`)
| name | kind | 검사 | output |
|---|---|---|---|
| z3       | constraint | 원문에 명시된 합/곱 제약(≤·≥·=) | final_tools 결과 행(status·message·details) + verdict |
| pint     | units      | 명시 단위의 차원 호환·변환 | 〃 |
| networkx | dependency | 명시된 필수 선행 관계의 순환 | 〃 |

FIN-TOOLS는 같은 이름으로 `ToolSpec`을 등록(replace=True)해 구현을 바꿀 수 있다. 등록이 없으면 `final_tools` 어댑터가 쓰인다.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

INTERFACE_VERSION = "finalize-tools@v2"
VERDICTS = ("pass", "fail", "unchecked")

# 점검 유형 → 도구 이름. 코드가 정한다(LLM이 고르지 않는다). 유형을 더할 때는 여기만 늘린다(계약 추가만).
TOOL_FOR_CHECK: dict[str, str] = {"constraint": "z3", "units": "pint", "dependency": "networkx"}
CHECK_KINDS: tuple[str, ...] = tuple(TOOL_FOR_CHECK)
TOOL_NAMES: tuple[str, ...] = tuple(dict.fromkeys(TOOL_FOR_CHECK.values()))
_STATUS_VERDICT = {"passed": "pass", "pass": "pass", "ok": "pass", "failed": "fail", "fail": "fail"}


def tool_for(check_kind: str) -> str:
    """점검 유형의 도구 이름. 모르는 유형은 ValueError(추정하지 않는다)."""
    try:
        return TOOL_FOR_CHECK[check_kind]
    except KeyError:
        raise ValueError(f"unknown check kind: {check_kind!r}") from None


@dataclass(frozen=True)
class ToolCall:
    """도구 호출 1건. ``args``는 JSON 직렬화 가능한 dict이며 도구가 스스로 검증한다."""

    name: str
    args: Mapping[str, Any] = field(default_factory=dict)
    check_id: str | None = None  # 엔진의 점검 항목 id(감사 연결용)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "args": dict(self.args), "check_id": self.check_id}


@dataclass
class ToolResult:
    """도구 결과. ``ok``는 "도구가 끝까지 돌아 판정을 냈다"이지 통과가 아니다. 통과 여부는 ``verdict``."""

    ok: bool
    output: dict[str, Any]
    evidence: dict[str, Any]
    error: str | None = None  # 짧은 분류(invalid_args · tool_unavailable · timeout · cancelled · tool_error · unchecked)

    @property
    def verdict(self) -> str:
        v = self.output.get("verdict") if isinstance(self.output, Mapping) else None
        return v if self.ok and v in VERDICTS else "unchecked"

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "verdict": self.verdict, "output": dict(self.output), "evidence": dict(self.evidence),
                "error": self.error}


ToolFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    """도구 등록 단위. ``run(args) -> output``(verdict 포함). ``args_schema``는 JSON Schema(없으면 검사 생략)."""

    name: str
    description: str
    run: ToolFn
    version: str = "0"
    args_schema: Mapping[str, Any] | None = None
    timeout_s: float = 5.0


class ToolRegistry:
    """이름 → ToolSpec. 실행은 항상 이 층을 거쳐 evidence를 남긴다."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._lock = threading.Lock()

    def register(self, spec: ToolSpec, *, replace: bool = False) -> None:
        if spec.name not in TOOL_NAMES:
            raise ValueError(f"unknown tool name: {spec.name!r} (allowed: {TOOL_NAMES})")
        with self._lock:
            if spec.name in self._specs and not replace:
                raise ValueError(f"tool already registered: {spec.name!r}")
            self._specs[spec.name] = spec

    def unregister(self, name: str) -> None:
        with self._lock:
            self._specs.pop(name, None)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return sorted(self._specs)

    def run(self, call: ToolCall, *, cancel_event: threading.Event | None = None) -> ToolResult:
        """도구를 돌리고 evidence를 붙인다. 어떤 실패도 예외 대신 ok=False(unchecked)로 돌아온다."""
        t0 = time.perf_counter()
        spec = self.get(call.name)
        base = {"tool": call.name, "version": spec.version if spec else None, "interface": INTERFACE_VERSION,
                "input": _jsonable(dict(call.args)) if isinstance(call.args, Mapping) else None, "check_id": call.check_id}

        def fail(reason: str, error: str) -> ToolResult:
            ev = {**base, "output": {}, "verdict": "unchecked", "reason": reason,
                  "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2)}
            return ToolResult(ok=False, output={"verdict": "unchecked", "reason": reason}, evidence=ev, error=error)

        if call.name not in TOOL_NAMES:
            return fail("unknown_tool", "invalid_args")
        if spec is None:
            return fail("tool_not_registered", "tool_unavailable")
        if cancel_event is not None and cancel_event.is_set():
            return fail("cancelled", "cancelled")
        if not isinstance(call.args, Mapping):
            return fail("args_not_mapping", "invalid_args")
        if spec.args_schema is not None:
            problem = _schema_problem(spec.args_schema, dict(call.args))
            if problem:
                return fail(f"invalid_args: {problem}", "invalid_args")
        try:
            output = spec.run(dict(call.args))
        except ImportError:
            return fail("tool_unavailable", "tool_unavailable")
        except TimeoutError:
            return fail("timeout", "timeout")
        except Exception as exc:  # noqa: BLE001 — 예외 원문(입력·경로가 섞일 수 있다)은 남기지 않는다
            log.warning("tool %s failed kind=%s", call.name, type(exc).__name__)
            return fail(f"tool_error: {type(exc).__name__}", "tool_error")
        if not isinstance(output, Mapping) or output.get("verdict") not in VERDICTS:
            return fail("invalid_output", "tool_error")
        output = _jsonable(dict(output))
        ok = output["verdict"] in ("pass", "fail")
        ev = {**base, "output": output, "verdict": output["verdict"], "reason": output.get("reason"),
              "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2)}
        return ToolResult(ok=ok, output=output, evidence=ev, error=None if ok else "unchecked")


def _schema_problem(schema: Mapping[str, Any], args: dict[str, Any]) -> str:
    try:
        import jsonschema
    except ImportError:
        return ""
    errors = sorted(jsonschema.Draft202012Validator(dict(schema)).iter_errors(args), key=lambda e: list(e.absolute_path))
    if not errors:
        return ""
    first = errors[0]
    path = "/".join(str(p) for p in first.absolute_path) or "(root)"
    return f"{path} ({first.validator})"  # 값은 싣지 않는다(입력 되돌림 방지)


def _jsonable(value: Any) -> Any:
    """evidence에 들어가는 값을 JSON 기본형으로 고정한다(Decimal·set·tuple 등)."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)[:500]


# ── final_tools 어댑터(기본 구현) ────────────────────────────────────────

_ARGS_SCHEMA = {"type": "object", "required": ["plan_text", "check"], "additionalProperties": False,
                "properties": {"plan_text": {"type": "string", "maxLength": 200_000}, "check": {"type": "object"}}}


def _adapter(tool: str, kind: str) -> ToolFn:
    def run(args: dict[str, Any]) -> dict[str, Any]:
        from neumann.analyze.final_tools import run_tool_checks  # ImportError → tool_unavailable

        check = dict(args["check"])
        if check.get("kind") not in (None, kind):
            return {"verdict": "unchecked", "reason": "kind_mismatch", "tool": tool}
        check["kind"] = kind
        rows = run_tool_checks(args["plan_text"], [check])
        row = rows[0] if rows else {"status": "unchecked", "message": "no_result", "details": {}, "plan_lines": []}
        return {"verdict": _STATUS_VERDICT.get(str(row.get("status")), "unchecked"), "reason": row.get("message"),
                "tool": row.get("tool", tool), "status": row.get("status"), "details": row.get("details", {}),
                "plan_lines": row.get("plan_lines", [])}
    return run


ADAPTERS: tuple[ToolSpec, ...] = tuple(
    ToolSpec(tool, f"final_tools {kind} 검사 어댑터", _adapter(tool, kind), "final_tools@v1", _ARGS_SCHEMA)
    for kind, tool in TOOL_FOR_CHECK.items()
)

registry = ToolRegistry()


def ensure_adapters(reg: ToolRegistry | None = None) -> list[str]:
    """등록되지 않은 이름에 final_tools 어댑터를 붙인다(FIN-TOOLS 구현이 먼저 있으면 유지). 반환: 이번에 붙인 이름."""
    reg = reg or registry
    added = []
    for spec in ADAPTERS:
        if reg.get(spec.name) is None:
            reg.register(spec)
            added.append(spec.name)
    return added


def register(spec: ToolSpec, *, replace: bool = False) -> None:
    registry.register(spec, replace=replace)


def run_tool(call: ToolCall, *, cancel_event: threading.Event | None = None,
             reg: ToolRegistry | None = None) -> ToolResult:
    """기본 레지스트리로 도구 1건 실행. 등록된 구현이 없으면 final_tools 어댑터를 쓴다."""
    reg = reg or registry
    ensure_adapters(reg)
    return reg.run(call, cancel_event=cancel_event)


def run_check(plan_text: str, check: Mapping[str, Any], *, cancel_event: threading.Event | None = None,
              reg: ToolRegistry | None = None) -> ToolResult:
    """검사 1건(final_tools 형식)을 코드가 정한 도구로 돌린다. 모르는 kind는 unchecked."""
    kind = check.get("kind") if isinstance(check, Mapping) else None
    check_id = check.get("check_id") if isinstance(check, Mapping) else None
    try:
        name = tool_for(str(kind))
    except ValueError:
        ev = {"tool": None, "version": None, "interface": INTERFACE_VERSION, "input": {"check": _jsonable(dict(check))},
              "check_id": check_id, "output": {}, "verdict": "unchecked", "reason": "unknown_check_kind", "elapsed_ms": 0.0}
        return ToolResult(ok=False, output={"verdict": "unchecked", "reason": "unknown_check_kind"}, evidence=ev, error="invalid_args")
    return run_tool(ToolCall(name, {"plan_text": plan_text, "check": dict(check)}, check_id=check_id), cancel_event=cancel_event, reg=reg)


__all__ = [
    "ADAPTERS",
    "CHECK_KINDS",
    "INTERFACE_VERSION",
    "TOOL_FOR_CHECK",
    "TOOL_NAMES",
    "VERDICTS",
    "ToolCall",
    "ToolFn",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "ensure_adapters",
    "register",
    "registry",
    "run_check",
    "run_tool",
    "tool_for",
]
