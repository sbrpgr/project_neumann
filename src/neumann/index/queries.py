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
# 절 제목 줄(ATX): 들여쓰기 0~3칸 + `#` 1~6개 + (공백 + 나머지 줄) 또는 줄 끝. 줄 시작에서만 시도하고
# 되돌림은 {0,3}·{1,6}로 상한이 있으며 `[^\n]*`는 줄 끝까지 한 번에 가므로 입력 길이에 선형이다.
# 제목 끝의 공백·닫는 `#`은 정규식이 아니라 문자열 처리로 벗긴다.
# 옛 `^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$`(re.M)는 `(.+?)\s*#*\s*`가 겹쳐 세제곱 시간이었다
# ("# a" + 공백 4,000개 + "b"에 55초 이상, SEC-6). 공백은 옛 `\s`와 같은 유니코드 공백이되 줄바꿈만 빼서
# 제목이 다음 줄로 넘어가지 않는다.
_HEADING_LINE = re.compile(r"^[^\S\n]{0,3}#{1,6}(?:[^\S\n]([^\n]*))?$", re.M)


def _headings(text: str) -> list[tuple[int, int, str, str]]:
    """마크다운 제목 줄 → [(줄 시작, 줄 끝, 제목, 줄 전체)]. 줄 끝은 `\\n` 앞(또는 글 끝)이다.

    제목은 `#` 뒤 글자에서 앞뒤 공백을 벗기고, 끝의 `#`들과 그 앞 공백을 벗긴 것이다(옛 정규식과 같은 규칙:
    `C#`도 `C`가 된다). `#`만 있는 줄·`# `처럼 내용이 없는 줄은 제목이 빈 문자열인 제목 줄이다(CommonMark의 빈 제목).
    """
    out: list[tuple[int, int, str, str]] = []
    for m in _HEADING_LINE.finditer(text):
        rest = m.group(1)
        out.append((m.start(), m.end(), rest.strip().rstrip("#").rstrip() if rest else "", m.group(0)))
    return out


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
    heads = _headings(text)
    if not heads:
        return out
    title = heads[0][2] if heads[0][3].lstrip().startswith("# ") else ""
    buckets: dict[str, list[str]] = {}
    for i, (_, end, head, _) in enumerate(heads):
        axis = next((ax for pat, ax in _HEADING_AXIS if pat.search(head)), None) if head else None
        if not axis:
            continue
        body = text[end : heads[i + 1][0] if i + 1 < len(heads) else len(text)].strip()
        if body:
            buckets.setdefault(axis, []).append(body)
    if title:
        buckets.setdefault("topic", []).insert(0, title)
    for axis in AXES:
        q = "\n".join(buckets.get(axis, [])).strip()
        if len(q) >= min_chars and (q, axis) not in out:
            out.append((q, axis))
    return out


__all__ = ["AXES", "normalize_axis", "plan_axis_queries"]
