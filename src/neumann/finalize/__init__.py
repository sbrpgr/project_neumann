"""최종 점검·수정 엔진(FIN-ENGINE). 연구자가 확정한 문안을 한 번 점검해 오류를 그 자리에서 고친 최종 초안을 낸다.

    from neumann.finalize import finalize
    out = finalize(plan_confirmed, result, revision, decisions)   # 점검 1회 · 수정 1묶음 · 재검사 ≤1회 · 반복 0회

하위 모듈
- ``tools``   FIN-TOOLS와 공유하는 도구 인터페이스(ToolCall → ToolResult)와 코드가 정한 점검 유형→도구 표
- ``checks``  계획서에서 사실(절·수치·단위·합계·참조·인용)을 뽑고 코드가 정한 도구로 검사한다
- ``engine``  점검(논리·물리·구조·근거) → 확실한 수정 반영 → 재검사 → 최종 초안·변경 이력·목록·도구 기록
- ``render``  최종 초안 Markdown/DOCX와 변경 이력
- ``mock``    mock provider 응답기(final_review · final_fix)
"""

from __future__ import annotations

from neumann.finalize.tools import TOOL_FOR_CHECK, ToolCall, ToolResult, ToolSpec, registry, run_tool, tool_for

__all__ = ["TOOL_FOR_CHECK", "ToolCall", "ToolResult", "ToolSpec", "finalize", "registry", "run_tool", "tool_for"]


def finalize(*args, **kwargs):  # noqa: ANN001, ANN201 — 엔진 지연 import(도구 인터페이스만 쓰는 곳이 엔진 의존성을 끌지 않게)
    from neumann.finalize.engine import finalize as _finalize

    return _finalize(*args, **kwargs)
