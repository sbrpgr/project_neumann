"""FIN-ENGINE ↔ FIN-TOOLS 도구 인터페이스(공유 계약). 먼저 커밋하는 파일이다.

    from neumann.finalize.tools import ToolCall, ToolResult, ToolSpec, registry, run_tool, tool_for

    call   = ToolCall(name="arithmetic_sum", args={"items": [3, 4, 3], "total": 12})
    result = run_tool(call)                      # → ToolResult(ok, output, evidence)
    result.verdict                               # "pass" | "fail" | "unchecked"

원칙(대표 원칙·AGENTS.md)
- **도구 선택은 코드가 한다.** 점검 유형(check kind) → 도구 이름은 `TOOL_FOR_CHECK` 표 하나로 고정한다. LLM은 "어느 줄의 어떤
  종류의 주장을 검사하라"고 가리킬 뿐 도구 이름·인자를 정하지 않는다. 인자는 코드가 계획서 원문에서 추출해 만든다.
- **수치·단위·합계 판정은 도구 결과로만 한다.** `ToolResult.ok=False`는 "검사하지 못함(unchecked)"이지 통과가 아니다. 도구가
  없거나(ImportError) 인자가 어긋나거나 시간·취소가 걸리면 `unchecked`로 남고, 엔진은 그 항목을 `[확인 필요]`로 둔다.
- **근거 정직성.** `ToolResult.evidence`는 {tool, version, input, output, verdict, elapsed_ms, reason}이다. 엔진은 이것을 문제·
  변경 이력에 그대로 붙인다(도구 이름·입력·출력). 예외 원문·경로·비밀값은 evidence에 넣지 않는다(종류만).
- 도구는 모델이 만든 코드를 실행하지 않는다(`restricted_exec`도 코드 검사·승인 경계를 통과한 명령 규격만 받고, 기본은 꺼짐).

도구 이름과 인자 규격(FIN-TOOLS가 구현, 이 모듈의 `builtin`이 최소 참조 구현을 등록한다)
| name | args | output(verdict 포함) |
|---|---|---|
| calculator     | {"expression": "4*12", "expected": 40, "tolerance": 1e-6} | {"value": 48, "expected": 40, "verdict": "fail"} |
| unit_dimension | {"left": {"value": 10, "unit": "mS"}, "right": {"value": 1, "unit": "S/cm"}, "operation": "compare"} 또는 {"quantity": {...}, "expected_dimension": "S/cm"} | {"compatible": false, "left_dimension": "...", "verdict": "fail"} |
| arithmetic_sum | {"items": [70, 20, 20], "total": 100, "tolerance": 1e-9} | {"computed": 110, "stated": 100, "verdict": "fail"} |
| structure      | {"lines": [...], "required_sections": [...], "references": [{"line": 7, "ref": "§7"}]} | {"missing": [...], "order_ok": true, "broken_references": [...], "verdict": ...} |
| citation_lookup| {"doi": "10.../x", "title": "...", "year": 2024} | {"found": true, "retracted": false, "post_status": [...], "verdict": "pass"} |
| restricted_exec| {"language": "python", "code": "...", "timeout_s": 5, "inputs": {}} | {"verdict": "unchecked", "reason": "exec_disabled"} (기본) |

verdict 의미: pass = 도구가 주장을 확인함, fail = 도구가 주장과 어긋남을 확인함, unchecked = 판단 불가(통과 아님).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

INTERFACE_VERSION = "finalize-tools@v1"
VERDICTS = ("pass", "fail", "unchecked")

# 점검 유형 → 도구 이름. 코드가 정한다(LLM이 고르지 않는다). 유형을 더할 때는 여기와 CHECK_KINDS만 늘린다(계약 추가만).
TOOL_FOR_CHECK: dict[str, str] = {
    "arithmetic": "calculator",      # 명시된 산식(A × B = C)의 검산
    "sum": "arithmetic_sum",         # 항목 합계(일정·예산·분할 비율)
    "unit": "unit_dimension",        # 단위·차원 일관성
    "structure": "structure",        # 필수 절·순서
    "reference": "structure",        # 절·표·그림 참조
    "citation": "citation_lookup",   # 선행연구·인용 ↔ 코퍼스·철회 데이터
    "exec": "restricted_exec",       # 제한 실행(기본 꺼짐)
}
CHECK_KINDS: tuple[str, ...] = tuple(TOOL_FOR_CHECK)
TOOL_NAMES: tuple[str, ...] = tuple(dict.fromkeys(TOOL_FOR_CHECK.values()))


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
    error: str | None = None  # 짧은 분류(invalid_args · tool_unavailable · timeout · cancelled · tool_error)

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
                "input": _jsonable(dict(call.args)), "check_id": call.check_id}

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


registry = ToolRegistry()


def register(spec: ToolSpec, *, replace: bool = False) -> None:
    registry.register(spec, replace=replace)


def run_tool(call: ToolCall, *, cancel_event: threading.Event | None = None,
             reg: ToolRegistry | None = None) -> ToolResult:
    """기본 레지스트리로 도구 1건 실행. 참조 구현이 아직 없으면 `builtin`을 먼저 붙인다."""
    reg = reg or registry
    if reg is registry and not registry.names():
        ensure_builtin()
    return reg.run(call, cancel_event=cancel_event)


def ensure_builtin() -> None:
    """최소 참조 구현(`neumann.finalize.tools.builtin`)을 기본 레지스트리에 등록한다(이미 있으면 유지)."""
    try:
        from neumann.finalize.tools import builtin
    except ImportError:
        return
    builtin.register_all(registry)


__all__ = [
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
    "ensure_builtin",
    "register",
    "registry",
    "run_tool",
    "tool_for",
]
