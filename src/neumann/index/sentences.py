"""심사평 텍스트 → 문장 구간 → Excerpt.

astra 지적 추출(E3)이 쓰는 **문장 번호의 기준**이다. 같은 입력이면 항상 같은 구간·같은 id가 나온다.

- 오프셋은 저장된 `ReviewEvent.text`(정규화·신원 제거가 끝난 문자열) 기준이다. 여기서는 텍스트를 바꾸지 않는다.
- 구간은 앞뒤 공백과 앞머리 목록 기호(`-`, `*`, `1.`, `2)`, `(a)`)를 뺀 자리를 가리킨다. 문장 텍스트는
  언제나 `text[start:end]`다.
- ResearchArcade 심사평은 줄바꿈이 사라져 목록 번호가 앞 문장에 붙어 있다(`...below.2. Certain parts`).
  이 경우도 경계로 본다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from neumann.models import Excerpt, ReviewEvent

# 마침표 뒤에 와도 문장이 끝나지 않는 약어(소문자, 마침표 뺀 꼴)
ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "e.g", "i.e", "eg", "ie", "cf", "c.f", "vs", "al", "fig", "figs", "eq", "eqs", "eqn", "eqns",
        "sec", "secs", "tab", "tbl", "ref", "refs", "resp", "approx", "w.r.t", "wrt", "no", "nos",
        "vol", "pp", "p", "ch", "chap", "app", "appx", "thm", "lem", "def", "prop", "cor", "alg",
        "dr", "mr", "mrs", "ms", "prof", "st", "jr", "sr", "incl", "esp", "viz", "ca", "est",
        "i.i.d", "a.k.a", "u.s", "e.t.c",
    }
)

# 문장 끝 후보: 종결부호 + 닫는 따옴표·괄호
_TERMINAL = re.compile(r"[.!?]+[\"'”’)\]]*")
# 종결부호 뒤에 오면 경계로 보는 것
_AFTER_SPACE_START = re.compile(r"\s+[\"'“‘(\[]?[A-Z0-9]")  # 공백 + 대문자/숫자로 시작
_AFTER_GLUED_ENUM = re.compile(r"\(?\d{1,2}[.)]\s*[A-Za-z]")  # 'below.2. Certain', 'x.2)The'
_AFTER_BULLET = re.compile(r"\s*[-*•]\s")  # 'Table 2!- The'
# 문장 앞머리 목록 기호
_LEADING_MARKER = re.compile(
    r"(?:[-*•+>]+\s*|\(?\d{1,2}[.)](?!\d)\s*|\([a-zA-Z]\)\s*|\([ivxIVX]{1,4}\)\s*|[ivx]{1,4}\)\s*)+"
)
_WORD_BEFORE = re.compile(r"([A-Za-z][A-Za-z.]*)$")
_ENUM_ONLY = re.compile(r"\s*(?:[-*•]\s*)?\(?(?:\d{1,2}|[a-zA-Z]|[ivxIVX]{1,4})")
_HAS_WORD = re.compile(r"[^\W_]")  # 글자나 숫자가 하나라도 있어야 문장으로 본다

# 구분자 없이 너무 긴 문장은 ';'에서 한 번 더 나눈다(LLM에 넘기는 단위를 줄이려고)
LONG_SENTENCE_CHARS = 800


def _is_abbreviation(line: str, dot_pos: int) -> bool:
    """line[dot_pos]가 '.'이고 그 앞 낱말이 약어면 True."""
    m = _WORD_BEFORE.search(line, 0, dot_pos)
    if not m:
        return False
    word = m.group(1).lower().rstrip(".")
    if word in ABBREVIATIONS:
        return True
    # 이름 머리글자(J. Smith)나 한 글자 기호
    return len(word) == 1 and m.group(1)[0].isupper()


def _split_line(line: str) -> list[tuple[int, int]]:
    """줄 하나(줄바꿈 없음)를 문장 구간으로 나눈다. 구간은 line 기준 [s, e)."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _TERMINAL.finditer(line):
        end = m.end()
        if end >= len(line):
            break
        rest_pos = end
        boundary = False
        if _AFTER_SPACE_START.match(line, rest_pos) or _AFTER_BULLET.match(line, rest_pos):
            boundary = True
        elif _AFTER_GLUED_ENUM.match(line, rest_pos) and m.group(0)[0] == ".":
            # 'Section 4.2. The'는 제외: 마침표 앞이 글자·닫는 괄호·$여야 붙은 목록 번호로 본다
            prev = line[m.start() - 1] if m.start() > 0 else ""
            boundary = prev.isalpha() or prev in ")]$\"'"
        if not boundary:
            continue
        # 문장 앞머리 목록 번호('2.', '(3)')의 마침표는 경계가 아니다
        if _ENUM_ONLY.fullmatch(line, start, m.start()):
            continue
        if m.group(0)[0] == "." and len(m.group(0).rstrip("\"'”’)]")) == 1:
            if _is_abbreviation(line, m.start()):
                continue
        spans.append((start, end))
        start = end
    spans.append((start, len(line)))
    return spans


def _split_long(text: str, s: int, e: int) -> list[tuple[int, int]]:
    if e - s <= LONG_SENTENCE_CHARS:
        return [(s, e)]
    out: list[tuple[int, int]] = []
    cur = s
    for m in re.finditer(r";\s+", text[s:e]):
        cut = s + m.start() + 1
        if cut - cur >= 40:
            out.append((cur, cut))
            cur = cut
    out.append((cur, e))
    return out


def _trim(text: str, s: int, e: int) -> tuple[int, int]:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    m = _LEADING_MARKER.match(text, s, e)
    if m and m.end() > s:
        s = m.end()
        while s < e and text[s].isspace():
            s += 1
    return s, e


def split_sentences(text: str) -> list[tuple[int, int]]:
    """텍스트 → 문장 구간 [(start, end), ...]. `text[start:end]`가 문장이다. 결정적."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for line in text.split("\n"):
        line_start = pos
        pos += len(line) + 1
        if not line.strip():
            continue
        for ls, le in _split_line(line):
            for s, e in _split_long(text, line_start + ls, line_start + le):
                s, e = _trim(text, s, e)
                if e > s and _HAS_WORD.search(text, s, e):
                    spans.append((s, e))
    return spans


def review_source_url(review: ReviewEvent) -> str:
    """심사평 딥링크. 없으면 provenance의 원문 URL."""
    return review.url or review.provenance.source_url


def excerpts_for_text(
    text: str, *, source_kind: str, source_id: str, source_url: str
) -> list[Excerpt]:
    """원문 → 문장 Excerpt 목록(원문 순서). 모든 Excerpt는 원문을 잘라서 만든다."""
    return [
        Excerpt.from_source(text, s, e, source_kind=source_kind, source_id=source_id, source_url=source_url)  # type: ignore[arg-type]
        for s, e in split_sentences(text)
    ]


def excerpts_for_review(review: ReviewEvent) -> list[Excerpt]:
    return excerpts_for_text(
        review.text, source_kind="review", source_id=review.review_id, source_url=review_source_url(review)
    )


def review_sort_key(review: ReviewEvent) -> tuple:
    """논문 안에서 심사평 순서: 작성 시각(없으면 뒤) → review_id. 문장 번호가 이 순서를 따른다."""
    created = review.created.isoformat() if review.created else "~"
    return (created, review.review_id)


def excerpts_for_reviews(reviews: Iterable[ReviewEvent]) -> list[Excerpt]:
    """한 논문의 심사평들 → 번호 순서의 Excerpt 목록."""
    out: list[Excerpt] = []
    for review in sorted(reviews, key=review_sort_key):
        out.extend(excerpts_for_review(review))
    return out


__all__ = [
    "ABBREVIATIONS",
    "excerpts_for_review",
    "excerpts_for_reviews",
    "excerpts_for_text",
    "review_sort_key",
    "review_source_url",
    "split_sentences",
]
