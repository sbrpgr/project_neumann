"""근거 게이트 (E3-L1a). 예상 심사평 문장마다 근거를 검사하고, 실패한 문장만 버린다.

LLM이 아니다. 규칙 검사만 한다. 문장 하나가 통과하려면:

1. 근거 excerpt id가 1개 이상 있고, 모두 결과(`PremortemResult.evidence`) 안에 실제로 있다.
2. 카드 id를 달았다면 모두 결과(`risk_cards`) 안에 있고, 인용한 excerpt가 그 카드들의 근거에 속한다.
3. 계획서 줄 번호를 달았다면 계획서 범위 안이다.
4. 따옴표 인용이 있으면, 인용한 근거 원문(또는 인용한 계획서 줄)과 글자 그대로 같거나
   그 원문의 20자 이상 연속 부분문자열이다. 짝이 맞지 않는 따옴표도 실패다.
5. 숫자는 인용한 근거·계획서 본문(제목 줄·줄 앞 번호 매기기 제외)·인용 카드 문구·인용 줄 번호에 있는 것만 쓴다.
   결과 집계값(유사 연구 수·근거 수·카드 수)은 개수 단위(편·건·개·장·곳)가 바로 붙을 때만 허용한다
   (근거 없는 수치는 그 문장만 뺀다 — 계획서 §4 E3 불변식).
6. 개인정보(이메일·ORCID)가 없다. 빈 문장·형식 오류·중복이 아니다.

실패 문장은 `dropped`에 사유와 함께 남긴다(개인정보는 가린 뒤). 통과 문장에는 인용 위치(원문 오프셋)를 붙인다.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from neumann.models import PlanDocument, PremortemResult, contains_pii, redact_pii

GATE_VERSION = "grounding@v1"
MIN_QUOTE_LEN = 20
SECTIONS: tuple[str, ...] = ("strength", "weakness", "request")
MAX_TEXT_LEN = 600
MAX_DROPPED_TEXT = 300

# 폐기 사유 (목업 audit의 missing_citation·fabricated_number와 이름을 맞춘다)
MALFORMED = "malformed"
EMPTY_TEXT = "empty_text"
TOO_LONG = "too_long"
PII = "pii"
MISSING_CITATION = "missing_citation"
UNKNOWN_EXCERPT = "unknown_excerpt_id"
UNKNOWN_CARD = "unknown_card_id"
EXCERPT_CARD_MISMATCH = "excerpt_card_mismatch"
UNKNOWN_PLAN_LINE = "unknown_plan_line"
QUOTE_MISMATCH = "quote_mismatch"
FABRICATED_NUMBER = "fabricated_number"
DUPLICATE = "duplicate"

DROP_REASONS: tuple[str, ...] = (
    MALFORMED,
    EMPTY_TEXT,
    TOO_LONG,
    PII,
    MISSING_CITATION,
    UNKNOWN_EXCERPT,
    UNKNOWN_CARD,
    EXCERPT_CARD_MISMATCH,
    UNKNOWN_PLAN_LINE,
    QUOTE_MISMATCH,
    FABRICATED_NUMBER,
    DUPLICATE,
)


# ── 따옴표 인용 찾기 ──────────────────────────────────────────────────────

# (여는 문자, 닫는 문자). ASCII 작은따옴표는 영어 축약·소유격(model's, reviewers')과 헷갈리므로 따로 다룬다.
_PAIRS: tuple[tuple[str, str], ...] = (
    ('"', '"'),
    ("“", "”"),  # “ ”
    ("‘", "’"),  # ‘ ’
    ("「", "」"),  # 「 」
    ("『", "』"),  # 『 』
    ("《", "》"),  # 《 》
    ("«", "»"),  # « »
    ("＂", "＂"),  # ＂ ＂ (전각)
)
_PAIR_RES = [re.compile(re.escape(o) + r"([^" + re.escape(o + c) + r"]+)" + re.escape(c)) for o, c in _PAIRS]
# 여는 '는 앞이 글자·숫자가 아니고, 닫는 '는 뒤가 라틴 글자가 아닐 때만 인용으로 본다.
_SINGLE_RE = re.compile(r"(?<![A-Za-z0-9])'([^'\n]{1,400}?)'(?![A-Za-z])")


@dataclass(frozen=True)
class QuoteSpan:
    start: int  # 문장 안 위치(여는 따옴표 포함)
    end: int
    inner: str  # 따옴표 안 문자열(그대로)


def find_quotes(text: str) -> tuple[list[QuoteSpan], list[str]]:
    """문장 안 따옴표 인용 목록과 문제(짝이 안 맞는 따옴표) 목록."""
    spans: list[QuoteSpan] = []
    problems: list[str] = []
    for (o, c), rx in zip(_PAIRS, _PAIR_RES, strict=True):
        if o == c:
            if text.count(o) % 2:
                problems.append(f"짝이 맞지 않는 따옴표 {o}")
        elif c != "’" and text.count(o) != text.count(c):  # ’는 아포스트로피로도 쓰여 짝 검사에서 뺀다
            problems.append(f"짝이 맞지 않는 따옴표 {o}{c}")
        spans.extend(QuoteSpan(m.start(), m.end(), m.group(1)) for m in rx.finditer(text))
    spans.extend(QuoteSpan(m.start(), m.end(), m.group(1)) for m in _SINGLE_RE.finditer(text))
    # 다른 인용 안에 들어간 인용(예: "… 'x' …")은 바깥 것만 검사한다
    spans.sort(key=lambda s: (s.start, -s.end))
    outer: list[QuoteSpan] = []
    for s in spans:
        if any(o.start <= s.start and s.end <= o.end for o in outer):
            continue
        outer.append(s)
    return outer, problems


def _quote_candidates(inner: str) -> list[str]:
    """비교할 인용 문자열 후보: 그대로, 앞뒤 공백 제거, 끝 문장부호 제거. 글자를 새로 만들지는 않는다."""
    out = [inner]
    stripped = inner.strip()
    if stripped != inner:
        out.append(stripped)
    trimmed = stripped.rstrip(".,;:!?…")
    if trimmed and trimmed != stripped:
        out.append(trimmed)
    return [q for q in out if q]


def match_quote(inner: str, sources: Iterable[tuple[str, str]]) -> tuple[str, str, int] | None:
    """인용이 원문 중 하나와 글자 그대로 같거나 그 20자 이상 연속 부분문자열이면 (source_key, quote, 위치)."""
    sources = list(sources)
    for q in _quote_candidates(inner):
        for key, src in sources:
            if q == src:
                return key, q, 0
            if len(q) >= MIN_QUOTE_LEN:
                idx = src.find(q)
                if idx >= 0:
                    return key, q, idx
    return None


# ── 숫자 ─────────────────────────────────────────────────────────────────

_NUM_RE = re.compile(r"(?<![A-Za-z0-9_.])\d+(?:[.,]\d+)*")
_THOUSANDS_RE = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


def _norm_number(tok: str) -> list[str]:
    parts = [tok.replace(",", "")] if _THOUSANDS_RE.match(tok) else tok.split(",")
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        if p.count(".") == 1:
            try:
                d = Decimal(p).normalize()
                out.append(format(d, "f"))
                continue
            except InvalidOperation:
                pass
        elif "." not in p:
            out.append(str(int(p)))
            continue
        out.append(p)
    return out


def extract_numbers(text: str) -> list[str]:
    """문장 안 숫자(정규화). 영문자에 붙은 숫자(R2, bge-m3)는 이름의 일부로 보고 뺀다."""
    nums: list[str] = []
    for m in _NUM_RE.finditer(text):
        nums.extend(_norm_number(m.group(0)))
    return nums


# 계획서 줄 앞의 번호 매기기("1. ", "2) ", "(3) ", "2.1. ")는 사실 수치가 아니다
_ENUM_PREFIX_RE = re.compile(r"^\s*(?:\(?\d+(?:\.\d+)*[.)]\s+|[-*+]\s+)")
# 집계값(유사 연구 수·근거 수·카드 수)은 개수 단위가 바로 붙을 때만 허용한다("3편"은 되고 "3배"·"3%"는 안 된다)
_COUNT_UNIT_RE = re.compile(r"\s?(?:편|건|개|장|곳)")


def plan_fact_numbers(plan: PlanDocument | None) -> set[str]:
    """계획서에서 사실로 쓸 수 있는 숫자. 제목 줄(#로 시작)과 줄 앞 번호 매기기는 뺀다."""
    if plan is None:
        return set()
    out: set[str] = set()
    for ln in plan.lines:
        text = ln.text.lstrip()
        if not text or text.startswith("#"):
            continue
        out.update(extract_numbers(_ENUM_PREFIX_RE.sub("", text, count=1)))
    return out


# ── 입력 정리 ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Draft:
    """게이트에 넣을 문장 후보. id는 실제 id(별칭을 푼 뒤)."""

    section: str
    text: str
    excerpt_ids: tuple[str, ...] = ()
    card_ids: tuple[str, ...] = ()
    plan_lines: tuple[int, ...] = ()


@dataclass(frozen=True)
class Drop:
    section: str
    reason: str
    text: str  # 개인정보를 가리고 잘라 둔 문장
    detail: str = ""
    generator: str | None = None

    def pair(self) -> list[str]:
        return [self.reason, self.text]

    def as_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "reason": self.reason,
            "text": self.text,
            "detail": self.detail,
            "generator": self.generator,
        }


def _safe_text(text: Any) -> str:
    s = text if isinstance(text, str) else repr(text)
    s = redact_pii(s)
    return s if len(s) <= MAX_DROPPED_TEXT else s[: MAX_DROPPED_TEXT - 1] + "…"


def _coerce(item: Any) -> tuple[Draft | None, str]:
    """dict 또는 Draft → Draft. 형식이 틀리면 (None, 사유)."""
    if isinstance(item, Draft):
        return item, ""
    if not isinstance(item, Mapping):
        return None, f"문장이 객체가 아니다({type(item).__name__})"
    section = item.get("section")
    text = item.get("text", item.get("t"))
    ex = item.get("excerpt_ids", item.get("c", []))
    cards = item.get("card_ids", item.get("cards", []))
    lines = item.get("plan_lines", [])
    if section not in SECTIONS:
        return None, f"알 수 없는 절 {section!r}"
    if not isinstance(text, str):
        return None, "text가 문자열이 아니다"
    for name, seq, typ in (("excerpt_ids", ex, str), ("card_ids", cards, str), ("plan_lines", lines, int)):
        if not isinstance(seq, list | tuple) or any(not isinstance(x, typ) or isinstance(x, bool) for x in seq):
            return None, f"{name} 형식 오류"
    return Draft(section, text, tuple(ex), tuple(cards), tuple(lines)), ""


# ── 근거 색인 ─────────────────────────────────────────────────────────────


class EvidenceIndex:
    """결과 하나에서 게이트가 참조하는 것: 근거 원문, 카드, 계획서 줄, 집계값."""

    def __init__(self, result: PremortemResult) -> None:
        self.result = result
        self.excerpts = {ex.excerpt_id: ex for ex in result.evidence}
        self.cards = {c.card_id: c for c in result.risk_cards}
        self.card_of_excerpt: dict[str, set[str]] = {}
        for c in result.risk_cards:
            for x in c.evidence:
                self.card_of_excerpt.setdefault(x, set()).add(c.card_id)
        self.plan_lines: dict[int, str] = {ln.no: ln.text for ln in result.plan.lines} if result.plan else {}
        self.plan_numbers = plan_fact_numbers(result.plan)
        self.global_counts = {
            str(len(result.similar_works)),
            str(len(result.evidence)),
            str(len(result.risk_cards)),
        }

    def cited_cards(self, d: Draft) -> list[str]:
        """문장이 기대는 카드: 명시한 카드 + 인용 excerpt가 속한 카드."""
        ids = list(dict.fromkeys(d.card_ids))
        for x in d.excerpt_ids:
            for cid in sorted(self.card_of_excerpt.get(x, ())):
                if cid not in ids:
                    ids.append(cid)
        return ids

    def allowed_numbers(self, d: Draft) -> tuple[set[str], set[str]]:
        """(사실 숫자, 집계 숫자). 사실 숫자는 단위와 상관없이 허용, 집계 숫자는 개수 단위가 붙을 때만 허용."""
        facts = set(self.plan_numbers)
        counts = set(self.global_counts)
        for x in d.excerpt_ids:
            facts.update(extract_numbers(self.excerpts[x].text))
        for cid in self.cited_cards(d):
            card = self.cards[cid]
            facts.update(extract_numbers(card.title))
            facts.update(extract_numbers(card.why_applies.text))
            counts.update({str(len(card.evidence)), str(len(card.works))})
        facts.update(str(n) for n in d.plan_lines)
        return facts, counts


# ── 게이트 ────────────────────────────────────────────────────────────────


@dataclass
class GateReport:
    passed: list[dict[str, Any]] = field(default_factory=list)  # section 키를 가진 문장 dict
    dropped: list[Drop] = field(default_factory=list)
    generated: int = 0

    def by_section(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {s: [] for s in SECTIONS}
        for s in self.passed:
            out[s["section"]].append({k: v for k, v in s.items() if k != "section"})
        return out

    def reasons(self) -> dict[str, int]:
        return dict(Counter(d.reason for d in self.dropped))

    def audit(self) -> dict[str, Any]:
        n_pass = len(self.passed)
        linked = sum(1 for s in self.passed if s["c"])
        return {
            "gen": self.generated,
            "pass": n_pass,
            "drop": len(self.dropped),
            "dropped": [d.pair() for d in self.dropped],
            "reasons": self.reasons(),
            "gate": GATE_VERSION,
            "linked_rate": (linked / n_pass) if n_pass else None,
        }


def check_sentence(d: Draft, index: EvidenceIndex) -> tuple[str | None, str, list[dict[str, Any]]]:
    """문장 하나 검사 → (폐기 사유 또는 None, 설명, 인용 위치 목록)."""
    text = d.text
    if not text.strip():
        return EMPTY_TEXT, "빈 문장", []
    if len(text) > MAX_TEXT_LEN:
        return TOO_LONG, f"{len(text)}자 > {MAX_TEXT_LEN}", []
    if contains_pii(text):
        return PII, "이메일/ORCID", []
    if not d.excerpt_ids:
        return MISSING_CITATION, "근거 excerpt id가 없다", []
    missing = [x for x in d.excerpt_ids if x not in index.excerpts]
    if missing:
        return UNKNOWN_EXCERPT, f"결과에 없는 excerpt id {missing[:3]}", []
    missing = [c for c in d.card_ids if c not in index.cards]
    if missing:
        return UNKNOWN_CARD, f"결과에 없는 카드 id {missing[:3]}", []
    if d.card_ids:
        pool = {x for c in d.card_ids for x in index.cards[c].evidence}
        stray = [x for x in d.excerpt_ids if x not in pool]
        if stray:
            return EXCERPT_CARD_MISMATCH, f"인용 카드의 근거가 아니다 {stray[:3]}", []
    bad_lines = [n for n in d.plan_lines if n not in index.plan_lines]
    if bad_lines:
        return UNKNOWN_PLAN_LINE, f"계획서에 없는 줄 {bad_lines[:5]}", []

    spans, problems = find_quotes(text)
    if problems:
        return QUOTE_MISMATCH, problems[0], []
    sources = [(f"ex:{x}", index.excerpts[x].text) for x in dict.fromkeys(d.excerpt_ids)]
    sources += [(f"line:{n}", index.plan_lines[n]) for n in dict.fromkeys(d.plan_lines)]
    quotes: list[dict[str, Any]] = []
    for sp in spans:
        hit = match_quote(sp.inner, sources)
        if hit is None:
            return QUOTE_MISMATCH, f"인용이 근거 원문과 다르다: {_safe_text(sp.inner)[:80]}", []
        key, q, idx = hit
        kind, ref = key.split(":", 1)
        if kind == "ex":
            ex = index.excerpts[ref]
            quotes.append({"text": q, "excerpt_id": ref, "start": ex.start + idx, "end": ex.start + idx + len(q)})
        else:
            quotes.append({"text": q, "plan_line": int(ref), "start": idx, "end": idx + len(q)})

    # 숫자: 인용 구간 안의 숫자는 이미 원문 대조를 통과했으므로 그 밖의 숫자만 본다
    outside = text
    for sp in sorted(spans, key=lambda s: s.start, reverse=True):
        outside = outside[: sp.start] + " " + outside[sp.end :]
    facts, counts = index.allowed_numbers(d)
    unknown: list[str] = []
    for m in _NUM_RE.finditer(outside):
        for n in _norm_number(m.group(0)):
            if n in facts or (n in counts and _COUNT_UNIT_RE.match(outside, m.end())):
                continue
            unknown.append(n)
    if unknown:
        return FABRICATED_NUMBER, f"근거·계획서에 없는 수치 {unknown[:5]}", []
    return None, "", quotes


def gate_sentences(
    drafts: Iterable[Draft | Mapping[str, Any]],
    result: PremortemResult,
    *,
    generator: str | None = None,
    index: EvidenceIndex | None = None,
) -> GateReport:
    """문장 후보를 검사해 통과 문장과 폐기 기록을 돌려준다. 실패 문장만 버린다."""
    index = index or EvidenceIndex(result)
    report = GateReport()
    seen: set[tuple[str, str]] = set()
    for item in drafts:
        report.generated += 1
        d, why = _coerce(item)
        if d is None:
            raw = item.get("text", item.get("t", "")) if isinstance(item, Mapping) else item
            sec = item.get("section", "?") if isinstance(item, Mapping) else "?"
            report.dropped.append(Drop(str(sec), MALFORMED, _safe_text(raw), why, generator))
            continue
        reason, detail, quotes = check_sentence(d, index)
        if reason is None:
            key = (d.section, " ".join(d.text.split()))
            if key in seen:
                reason, detail = DUPLICATE, "같은 절에 같은 문장"
            else:
                seen.add(key)
        if reason is not None:
            report.dropped.append(Drop(d.section, reason, _safe_text(d.text), detail, generator))
            continue
        report.passed.append(
            {
                "section": d.section,
                "t": d.text,
                "c": list(dict.fromkeys(d.excerpt_ids)),
                "cards": index.cited_cards(d),
                "plan_lines": sorted(set(d.plan_lines)),
                "quotes": quotes,
            }
        )
    return report


def verify_expected_review(review: Mapping[str, Any], result: PremortemResult) -> GateReport:
    """조립된 예상 심사평(dict)을 결과에 대고 다시 검사한다(평가·API 재확인용)."""
    drafts: list[dict[str, Any]] = []
    for section in SECTIONS:
        for s in review.get(section, []) or []:
            if isinstance(s, Mapping):
                drafts.append({**s, "section": section})
            else:
                drafts.append({"section": section, "text": s})
    return gate_sentences(drafts, result)


__all__ = [
    "DROP_REASONS",
    "Draft",
    "Drop",
    "EvidenceIndex",
    "GATE_VERSION",
    "GateReport",
    "MIN_QUOTE_LEN",
    "SECTIONS",
    "check_sentence",
    "extract_numbers",
    "find_quotes",
    "gate_sentences",
    "match_quote",
    "plan_fact_numbers",
    "verify_expected_review",
]
