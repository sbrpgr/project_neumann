"""FIN-TOOLS 등록: FIN-ENGINE 레지스트리(`neumann.finalize.tools`)에 도구 구현을 붙이고, 점검 유형 → 도구 표를 문서화한다.

    from neumann.finalize.tools.fin_tools import register_all
    register_all()                                  # 기본 레지스트리에 arithmetic_sum·unit_dimension·structure·citation_lookup
    from neumann.finalize.tools.extract import extract_checks, run_checks
    results = run_checks(extract_checks(plan_text))  # 규칙 추출 → 코드가 정한 도구 → ToolResult

calculator·restricted_exec는 FIN-TOOLS가 만들지 않는다(조정: 새 계산기·실행기 금지). 추출기는 단위 없는 산식을
calculator 호출로 내보낼 뿐이며, 등록된 구현이 없으면 레지스트리가 unchecked(tool_unavailable)로 돌려준다.
"""

from __future__ import annotations

from typing import Any

from neumann.finalize.tools import ToolRegistry, ToolSpec, registry
from neumann.finalize.tools import citation, dimension, structure, sums

# 점검 유형(TOOL_FOR_CHECK 키) → 도구 → 구현 모듈 · 추출 라벨. 도구 선택은 이 표와 TOOL_FOR_CHECK가 정한다(LLM 아님).
CHECK_TOOL_TABLE: tuple[dict[str, Any], ...] = (
    {"kind": "sum", "tool": "arithmetic_sum", "impl": "fin_tools.sums (Fraction + Z3 교차 확인)",
     "labels": ("split_sum", "schedule_sum", "schedule_span", "budget_sum", "table_sum", "expr_sum")},
    {"kind": "unit", "tool": "unit_dimension", "impl": "fin_tools.dimension (Pint)",
     "labels": ("unit_derive", "unit_add", "unit_compare")},
    {"kind": "structure", "tool": "structure", "impl": "fin_tools.structure (NetworkX)", "labels": ("sections",)},
    {"kind": "reference", "tool": "structure", "impl": "fin_tools.structure (NetworkX)", "labels": ("references",)},
    {"kind": "citation", "tool": "citation_lookup", "impl": "fin_tools.citation (MCP 백엔드: 코퍼스·Retraction Watch)",
     "labels": ("citation",)},
    {"kind": "arithmetic", "tool": "calculator", "impl": "FIN-ENGINE(미구현이면 unchecked)", "labels": ("arith_expr",)},
    {"kind": "exec", "tool": "restricted_exec", "impl": "FIN-ENGINE(기본 꺼짐)", "labels": ()},
)

SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(name="arithmetic_sum", description="항목 합계 ↔ 총계(정확한 유리수 + Z3 교차 확인)", run=sums.run,
             version=sums.VERSION, args_schema=sums.ARGS_SCHEMA, timeout_s=2.0),
    ToolSpec(name="unit_dimension", description="Pint 차원 호환·변환·규모(derive·compare)", run=dimension.run,
             version=dimension.VERSION, args_schema=dimension.ARGS_SCHEMA, timeout_s=5.0),
    ToolSpec(name="structure", description="필수 절·순서·번호·참조 그래프(NetworkX)", run=structure.run,
             version=structure.VERSION, args_schema=structure.ARGS_SCHEMA, timeout_s=5.0),
    ToolSpec(name="citation_lookup", description="인용 DOI 철회 조회·제목 코퍼스 확인(읽기 전용 MCP 백엔드)",
             run=citation.run, version=citation.VERSION, args_schema=citation.ARGS_SCHEMA, timeout_s=10.0),
)


def register_all(reg: ToolRegistry | None = None, *, replace: bool = True) -> list[str]:
    """FIN-TOOLS 구현을 레지스트리에 붙인다(기본: 공유 레지스트리, 참조 구현이 있으면 교체). 붙인 이름을 돌려준다."""
    target = reg or registry
    names = []
    for spec in SPECS:
        existing = target.get(spec.name)
        if existing is not None and (existing.version == spec.version or not replace):
            continue
        target.register(spec, replace=existing is not None)
        names.append(spec.name)
    return names


def warmup() -> dict[str, bool]:
    """느린 import(Pint 수 초·NetworkX 수 초)를 미리 한다. 서버 기동 때 한 번 부른다."""
    import importlib

    ok = {"pint": dimension.warmup()}
    for name in ("networkx", "z3"):
        try:
            importlib.import_module(name)
            ok[name] = True
        except ImportError:
            ok[name] = False
    return ok


__all__ = ["CHECK_TOOL_TABLE", "SPECS", "register_all", "warmup"]
