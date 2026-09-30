"""질의 축(axis) 이름 정리와 계획서 → 축별 질의 나누기(모델·LLM 없이, 제목 규칙만).

축은 계획서 §4 E2 L1의 방법·데이터·평가 세 개와, 계획서 전체·목표를 뜻하는 `topic`이다.
`search(queries, axes=[...])`의 `axes`에 이 이름(또는 아래 별칭)을 준다. 없는 축은 `topic`이다.
"""

from __future__ import annotations

import re

AXES: tuple[str, ...] = ("topic", "method", "data", "evaluation")

_ALIASES: dict[str, str] = {
    "": "topic",
    "topic": "topic",
    "general": "topic",
    "plan": "topic",
    "goal": "topic",
    "objective": "topic",
    "주제": "topic",
    "목표": "topic",
    "method": "method",
    "methods": "method",
    "approach": "method",
    "model": "method",
    "방법": "method",
    "data": "data",
    "dataset": "data",
    "datasets": "data",
    "데이터": "data",
    "evaluation": "evaluation",
    "eval": "evaluation",
    "metrics": "evaluation",
    "experiment": "evaluation",
    "experiments": "evaluation",
    "평가": "evaluation",
}


def normalize_axis(axis: str | None) -> str | None:
    """별칭 → 표준 축 이름. 모르는 이름이면 None(호출부가 가중치 1.0으로 두고 상태에 적는다)."""
    key = (axis or "").strip().lower()
    return _ALIASES.get(key)


# 계획서 절 제목 → 축. 앞에서부터 처음 맞는 것
_HEADING_AXIS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"데이터|자료|data|dataset", re.I), "data"),
    (re.compile(r"평가|검증|실험|evaluat|experiment|metric|validation", re.I), "evaluation"),
    (re.compile(r"방법|방법론|모델|접근|method|approach|model", re.I), "method"),
    (re.compile(r"목표|목적|개요|배경|요약|objective|goal|aim|overview|summary|background", re.I), "topic"),
]
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.M)


def plan_axis_queries(text: str, *, include_full: bool = True, min_chars: int = 8) -> list[tuple[str, str]]:
    """마크다운 계획서 → [(질의, 축)]. 절 제목으로 방법·데이터·평가·목표 절을 골라 본문을 축 질의로 쓴다.

    - `include_full`이면 맨 앞에 전문을 `topic` 질의로 넣는다(분야 신호).
    - 맨 위 `#` 제목 줄(문서 제목)은 목표 절과 합쳐 `topic`으로 쓴다.
    - 축에 해당하지 않는 절(기대 성과 등)은 버린다. 제목이 하나도 없으면 전문 한 개만 돌려준다.
    결정적이다(같은 입력 → 같은 출력).
    """
    text = text or ""
    out: list[tuple[str, str]] = []
    if include_full and text.strip():
        out.append((text.strip(), "topic"))
    heads = list(_HEADING.finditer(text))
    if not heads:
        return out
    title = heads[0].group(1).strip() if heads[0].group(0).lstrip().startswith("# ") else ""
    buckets: dict[str, list[str]] = {}
    for i, m in enumerate(heads):
        body = text[m.end() : heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        axis = next((ax for pat, ax in _HEADING_AXIS if pat.search(m.group(1))), None)
        if axis and body:
            buckets.setdefault(axis, []).append(body)
    if title:
        buckets.setdefault("topic", []).insert(0, title)
    for axis in AXES:
        q = "\n".join(buckets.get(axis, [])).strip()
        if len(q) >= min_chars and (q, axis) not in out:
            out.append((q, axis))
    return out


__all__ = ["AXES", "normalize_axis", "plan_axis_queries"]
