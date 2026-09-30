"""위험 묶음(risk set) 형식: 두 시스템(Neumann·일반 LLM)이 같은 모양으로 위험 3개를 낸다(04_평가_명세 §0.2).

한 줄 = (시스템, 판정 대상 논문 work_id, 조건) 하나:
    {"format": "neumann-riskset-v1", "system": "neumann"|"baseline_llm"|"mock",
     "condition": "real"|"shuffle", "work_id": <심사평으로 판정할 논문>, "plan_work_id": <계획서를 만든 논문>,
     "plan_id": <계획서 sha256>, "status": "ok"|"degraded"|"error", "generator": "astra"|"rule"|"mock",
     "model": <실제 호출 모델 id>, "risks": [{"rank": 1, "title": str, "body": str, "evidence_ok": bool, ...}], ...}

사전 고정(2026-09-30):
- 위험은 정확히 3개. 모자라면 빈 자리는 판정하지 않고 적중 아님으로 센다(분모 3 유지). 넘치면 앞 3개.
- 판정자에게 보이는 글 = `제목 — 설명`. 설명은 2문장 이내(넘으면 앞 2문장으로 자르고 `trimmed=true`).
- 블라인드: 두 시스템 모두 같은 정리 함수(`blind_text`)를 거친다. 링크, 근거·발췌 id, 논문 id, 위험 코드(R2, R3.1),
  계획서 줄 번호 표기(L12), 대괄호 인용 번호, 카드 번호, 규칙 경로 표기를 지운다.
- 근거율: Neumann 카드는 근거 발췌가 전부 결과 안에 있고 원문 대조(`Excerpt.verify_against`)를 통과해야 `evidence_ok`.
  원문을 못 찾으면 통과로 치지 않는다. 일반 LLM은 원문 근거가 없어 항상 false.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

FORMAT = "neumann-riskset-v1"
K = 3
MAX_SENTENCES = 2
SYSTEMS = ("neumann", "baseline_llm", "mock")
CONDITIONS = ("real", "shuffle")
SEP = " — "

# ── 문장 세기 ────────────────────────────────────────────────────────────

_ABBREV = re.compile(r"\b(?:e\.g|i\.e|et al|etc|vs|cf|Fig|Figs|Eq|Eqs|Sec|No|approx|resp)\.", re.I)
_DECIMAL = re.compile(r"(?<=\d)\.(?=\d)")
_SENT_END = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)(?=\S)")
_PLACEHOLDER = "․"  # one dot leader: 약어·소수점의 점을 잠시 바꿔 문장 끝으로 안 보이게


def _protect(text: str) -> str:
    text = _ABBREV.sub(lambda m: m.group(0)[:-1] + _PLACEHOLDER, text)
    return _DECIMAL.sub(_PLACEHOLDER, text)


def split_sentences(text: str) -> list[str]:
    prot = _protect(" ".join((text or "").split()))
    return [s.replace(_PLACEHOLDER, ".").strip() for s in _SENT_END.split(prot) if s and s.strip()]


def count_sentences(text: str) -> int:
    return len(split_sentences(text))


def trim_sentences(text: str, max_n: int = MAX_SENTENCES) -> tuple[str, bool]:
    sents = split_sentences(text)
    if len(sents) <= max_n:
        return " ".join(sents), False
    return " ".join(sents[:max_n]), True


# ── 블라인드 정리 ────────────────────────────────────────────────────────

BLIND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("url", re.compile(r"https?://\S+|\bwww\.\S+", re.I)),
    ("excerpt_id", re.compile(r"\[?\bex_[0-9a-f]{6,}\b\]?", re.I)),
    ("card_id", re.compile(r"\[?\b(?:card|카드)[_\s#-]*\d+\b\]?", re.I)),
    ("work_id", re.compile(r"\b[a-z][a-z0-9_]*:[A-Za-z0-9_\-]{6,}\b")),
    ("rule_tag", re.compile(r"\((?:규칙|rule)[^)]*\)", re.I)),
    ("plan_line_paren", re.compile(r"\(\s*(?:계획서\s*)?L\d+(?:\s*[-–~,]\s*L?\d+)*\s*\)")),
    ("plan_line_ko", re.compile(r"(?:계획서\s*)?\bL\d+(?:\s*[-–~]\s*L?\d+)?(?=[가-힣,.)])")),
    ("risk_code", re.compile(r"\(?\bR\d(?:\.\d+)?\b\)?(?:\s*[:：·]\s*)?")),
    ("bracket_cite", re.compile(r"\[\s*(?:\d+|근거\s*\d*|evidence\s*\d*)(?:\s*[,–-]\s*\d+)*\s*\]", re.I)),
]
_EMPTY_PARENS = re.compile(r"\(\s*[,;·]?\s*\)")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")


def blind_text(text: str) -> str:
    """시스템 흔적(링크·id·코드·줄 번호·인용 번호)을 지운다. 두 시스템에 똑같이 적용한다."""
    t = text or ""
    for _, pat in BLIND_PATTERNS:
        t = pat.sub(" ", t)
    t = _EMPTY_PARENS.sub(" ", t)
    t = " ".join(t.split())
    t = _SPACE_BEFORE_PUNCT.sub(r"\1", t)
    return t.strip(" ,;·-—")


def blind_residue(text: str) -> list[str]:
    """정리한 뒤에도 남은 흔적 종류(블라인드 검사용)."""
    return [name for name, pat in BLIND_PATTERNS if pat.search(text or "")]


# ── 위험 항목 ────────────────────────────────────────────────────────────


def make_risk(rank: int, title: str, body: str, *, evidence_ok: bool = False, n_evidence: int = 0,
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    title_b = blind_text(title)
    body_b = blind_text(body)
    body_t, trimmed = trim_sentences(body_b)
    return {
        "rank": rank,
        "title": title_b,
        "body": body_t,
        "text": f"{title_b}{SEP}{body_t}" if body_t else title_b,
        "sentences": count_sentences(body_t),
        "trimmed": trimmed,
        "evidence_ok": bool(evidence_ok),
        "n_evidence": int(n_evidence),
        **(extra or {}),
    }


def make_riskset(*, system: str, condition: str, work_id: str, plan_work_id: str, plan_id: str,
                 risks: list[dict[str, Any]], status: str, generator: str, model: str | None,
                 notes: list[str] | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    if system not in SYSTEMS:
        raise ValueError(f"알 수 없는 시스템 {system!r}")
    if condition not in CONDITIONS:
        raise ValueError(f"알 수 없는 조건 {condition!r}")
    return {
        "format": FORMAT,
        "system": system,
        "condition": condition,
        "work_id": work_id,
        "plan_work_id": plan_work_id,
        "plan_id": plan_id,
        "status": status,
        "generator": generator,
        "model": model,
        "n_risks": len(risks[:K]),
        "risks": risks[:K],
        "notes": list(notes or []),
        **(meta or {}),
    }


def validate_riskset(rs: dict[str, Any]) -> list[str]:
    """형식 문제 목록(빈 목록이면 통과). 위험 3개 미만은 문제로 적되 판정은 가능(빈 자리 = 적중 아님)."""
    p: list[str] = []
    if rs.get("format") != FORMAT:
        p.append("format")
    if rs.get("system") not in SYSTEMS:
        p.append("system")
    if rs.get("condition") not in CONDITIONS:
        p.append("condition")
    risks = rs.get("risks") or []
    if len(risks) != K:
        p.append(f"risks={len(risks)}(정확히 {K}개여야 한다)")
    for r in risks:
        if not str(r.get("text", "")).strip():
            p.append(f"rank {r.get('rank')}: 빈 위험")
        if count_sentences(r.get("body", "")) > MAX_SENTENCES:
            p.append(f"rank {r.get('rank')}: 설명 {MAX_SENTENCES}문장 초과")
        if blind_residue(r.get("text", "")):
            p.append(f"rank {r.get('rank')}: 블라인드 흔적 {blind_residue(r.get('text', ''))}")
    return p


# ── Neumann 결과 → 위험 묶음 ──────────────────────────────────────────────


def card_evidence_ok(card: Any, excerpts: dict[str, Any], source_text_for: Callable[[Any], str | None]) -> tuple[bool, int]:
    """카드의 근거가 전부 결과 안에 있고 원문 대조를 통과하는가. (통과 여부, 근거 수)."""
    ids = list(getattr(card, "evidence", None) or [])
    if not ids:
        return False, 0
    for eid in ids:
        ex = excerpts.get(eid)
        if ex is None:
            return False, len(ids)
        src = source_text_for(ex)
        if src is None or not ex.verify_against(src):
            return False, len(ids)
    return True, len(ids)


def riskset_from_premortem(result: Any, *, condition: str, work_id: str, plan_work_id: str, plan_id: str,
                           source_text_for: Callable[[Any], str | None]) -> dict[str, Any]:
    """PremortemResult(계약 모델) → 위험 묶음. 카드는 점수(total) 내림차순, 같으면 원래 순서로 앞 3장."""
    cards = list(result.risk_cards)
    order = sorted(range(len(cards)), key=lambda i: (-float(cards[i].score.total), i))
    excerpts = {e.excerpt_id: e for e in result.evidence}
    risks = []
    gens = set()
    for rank, i in enumerate(order[:K], 1):
        c = cards[i]
        ok, n_ev = card_evidence_ok(c, excerpts, source_text_for)
        gens.add(str(c.generator))
        risks.append(make_risk(rank, c.title, c.why_applies.text, evidence_ok=ok, n_evidence=n_ev,
                               extra={"generator": str(c.generator)}))
    notes = []
    if len(risks) < K:
        notes.append(f"카드 {len(risks)}장(빈 자리 {K - len(risks)}개는 적중 아님으로 센다)")
    generator = "astra" if gens == {"astra"} else ("rule" if gens == {"rule"} else ("mixed:" + ",".join(sorted(gens)) if gens else "none"))
    return make_riskset(system="neumann", condition=condition, work_id=work_id, plan_work_id=plan_work_id,
                        plan_id=plan_id, risks=risks, status=str(result.status), generator=generator,
                        model=next((c.model for c in cards if getattr(c, "model", None)), None), notes=notes)


__all__ = [
    "CONDITIONS",
    "FORMAT",
    "K",
    "MAX_SENTENCES",
    "SYSTEMS",
    "blind_residue",
    "blind_text",
    "card_evidence_ok",
    "count_sentences",
    "make_risk",
    "make_riskset",
    "riskset_from_premortem",
    "split_sentences",
    "trim_sentences",
    "validate_riskset",
]
