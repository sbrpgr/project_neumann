"""astra ③ 카드 합성 + 카드 조립 불변식 + 점수 + 비상 규칙 카드.

모델은 카드 제목, 이 계획서에 해당하는 이유(계획서 줄 번호), 근거 id 목록만 돌려준다.
코드가 id 존재를 검증하고, 근거 Excerpt(원문을 자른 인용)를 붙이고, 점수(유사도 × 빈도 × 심각도 × 신뢰도)를 계산한다.

조립 불변식: 카드당 근거 3건 이상·논문 2편 이상, 카드 최대 8장, R0(서술)·R9(사후 기록 전용)는 카드로 만들지 않는다.

짧은 입력(E3-L1s, 입력 단계 warn):
- astra 호출에 `SHORT_INPUT_NOTE`를 덧붙인다: 계획서가 짧으면 주제·방법 줄에 묶인 "빠진 안전장치" 카드를 허용한다.
- 그래도 카드가 0장이면 `field_level_cards`(규칙 합성, generator="rule")로 분야 수준 카드를 만든다. 유사 연구 2편 이상의
  심사평에서 반복된 위험 유형만, 근거는 원문 구간 그대로(인용을 쓰지 않는다), 계획서 줄에는 묶지 않는다(plan_lines=[]).
  파이프라인은 이 단계를 degraded로 남기고 결과·화면에 "규칙 합성"을 표시한다.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from neumann.analyze import rules
from neumann.analyze.extract import Issue
from neumann.analyze.risk_brief import CARD_CODES, SEVERITY_LEVEL, SEVERITY_UNIT, TAXONOMY_BRIEF
from neumann.llm import LLMCall, LLMProvider, LLMResult, task_options
from neumann.models import Excerpt, PlanDocument, RiskCard, RiskCode, RiskScore, WhyApplies

TASK = "synthesize_cards"
PROMPT_VERSION = "synthesize_cards.v3"
MAX_CARDS = 8
MIN_EVIDENCE = 3
MIN_WORKS = 2
MAX_EVIDENCE_PER_CARD = 6
MAX_POOL = 240
MAX_TITLE = 80
SCORE_FORMULA = "product_v1: similarity * frequency * severity * confidence"
SCORE_WEIGHTS = {"similarity": 1.0, "frequency": 1.0, "severity": 1.0, "confidence": 1.0}

INSTRUCTIONS = f"""\
You write pre-mortem risk cards for a research plan, using ONLY risks that reviewers actually raised on similar prior papers.

Input:
- plan: the research plan as numbered lines (often Korean).
- papers: similar prior papers (id, title, retrieval similarity to the plan), most similar first.
- pool: reviewer issues from those papers' peer reviews: id, paper id, risk code, and the reviewer's sentence.

Write up to 8 cards, most important first. Each card:
- risk_code: one risk type (R1 to R8, definitions below) that applies to THIS plan: the plan states the weakness, or it
  omits a safeguard that the plan's own design needs. Choose the code by the definitions for the plan's risk itself,
  even if some pool issues carry a different code (e.g. train/test overlap from a random split is R3, not R2).
  Point to the plan lines (plan_lines) that show it. Make no card you cannot tie to plan lines.
- evidence_ids: 3 to 6 ids from the pool showing that reviewers flagged the same kind of problem, from at least
  2 different papers. Use only ids that exist in the pool. Prefer issues whose risk code matches the card, papers that
  are closer to the plan's domain (higher similarity), and the most specific sentences.
- title: Korean, at most 40 characters, naming the concrete risk for this plan.
- why_applies: Korean, 1 or 2 sentences: what the plan says or lacks (cite lines like "L12") and why reviewers of similar
  work objected. Do not quote reviewer text. Do not state numbers that are not in the plan. Do not attribute to the plan
  any dataset, method, or entity that appears only in the reviews.
One card per distinct risk; no duplicates.
If no reviewer issue in the pool applies to this plan, return cards as [] and give no_card_reason (Korean, one sentence).
Otherwise no_card_reason is null.

{TAXONOMY_BRIEF}"""


SHORT_INPUT_NOTE = """
The plan is SHORT (only a few sentences), so most safeguards are simply not stated yet. For a short plan, a risk
applies when reviewers of 2 or more similar papers raised it AND the plan's topic or method (the lines that name them)
would need that safeguard; tie such a card to those lines and say in why_applies that the plan does not state it yet.
Write 1 to 3 such cards when the pool supports them; return [] only if no pool issue fits the plan's topic or method."""
SHORT_PROMPT_VARIANT = "short_input"
FIELD_MAX_CARDS = 3


def build_schema(ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "risk_code": {"type": "string", "enum": [c.value for c in CARD_CODES]},
                        "title": {"type": "string"},
                        "why_applies": {"type": "string"},
                        "plan_lines": {"type": "array", "items": {"type": "integer"}},
                        "evidence_ids": {"type": "array", "items": {"type": "string", "enum": ids}},
                    },
                    "required": ["risk_code", "title", "why_applies", "plan_lines", "evidence_ids"],
                },
            },
            "no_card_reason": {"type": ["string", "null"]},
        },
        "required": ["cards", "no_card_reason"],
    }


@dataclass
class CardDraft:
    """조립 중인 카드. 근거는 Issue(원문 구간)로 들고 있다가 RiskCard로 만든다."""

    risk_code: RiskCode
    title: str
    why_text: str
    plan_lines: list[int]
    evidence: list[Issue]
    generator: str
    model: str | None = None

    @property
    def work_ids(self) -> list[str]:
        return list(dict.fromkeys(i.work_id for i in self.evidence))


@dataclass
class SynthesisResult:
    cards: list[RiskCard]
    evidence: dict[str, Excerpt]  # excerpt_id → Excerpt (카드가 인용한 것만)
    tags: dict[str, Issue]  # excerpt_id → 그 근거를 만든 지적
    generator: str
    llm: LLMResult | None = None
    fallback_reason: str | None = None
    no_card_reason: str | None = None
    drops: Counter = field(default_factory=Counter)
    pool_size: int = 0
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        c = {"pool": self.pool_size, "cards": len(self.cards), "evidence": len(self.evidence)}
        for reason, n in sorted(self.drops.items()):
            c[f"drop_{reason}"] = n
        return c


# ── 풀(모델 입력) ─────────────────────────────────────────────────────────


def build_pool(issues: list[Issue], max_pool: int = MAX_POOL) -> list[Issue]:
    """카드 후보 지적: 부정 극성, 카드 유형만, 근거 구간 중복 제거. 넘치면 논문·유형을 돌아가며 신뢰도 순으로 고른다."""
    uniq: dict[tuple[str, str], Issue] = {}
    for iss in issues:
        if iss.polarity != "negative" or iss.risk_code not in CARD_CODES:
            continue
        key = (iss.evidence_excerpt().excerpt_id, iss.risk_code.value)
        if key not in uniq or iss.confidence > uniq[key].confidence:
            uniq[key] = iss
    cand = sorted(uniq.values(), key=lambda i: (-i.confidence, i.work_id, i.excerpt.start))
    if len(cand) <= max_pool:
        return cand
    groups: dict[tuple[str, str], list[Issue]] = defaultdict(list)
    for iss in cand:
        groups[(iss.work_id, iss.risk_code.value)].append(iss)
    picked: list[Issue] = []
    while len(picked) < max_pool and any(groups.values()):
        for key in sorted(groups):
            if groups[key] and len(picked) < max_pool:
                picked.append(groups[key].pop(0))
    return picked


# ── 점수 ─────────────────────────────────────────────────────────────────


def score_card(
    code: RiskCode, evidence: list[Issue], similarity: dict[str, float], code_work_freq: dict[RiskCode, int], n_works: int
) -> RiskScore:
    works = list(dict.fromkeys(i.work_id for i in evidence))
    sim = sum(max(0.0, min(1.0, similarity.get(w, 0.0))) for w in works) / max(1, len(works))
    freq = min(1.0, code_work_freq.get(code, 0) / max(1, n_works))
    sev = SEVERITY_UNIT[SEVERITY_LEVEL[code]]
    conf = sum(i.confidence for i in evidence) / max(1, len(evidence))
    total = sim * freq * sev * conf
    r = lambda x: round(max(0.0, min(1.0, x)), 4)  # noqa: E731
    return RiskScore(similarity=r(sim), frequency=r(freq), severity=r(sev), confidence=r(conf), total=r(total),
                     weights=dict(SCORE_WEIGHTS))


def code_work_frequency(issues: list[Issue]) -> dict[RiskCode, int]:
    """유형별로 부정 지적이 한 번이라도 나온 논문 수."""
    seen: dict[RiskCode, set[str]] = defaultdict(set)
    for i in issues:
        if i.polarity == "negative":
            seen[i.risk_code].add(i.work_id)
    return {k: len(v) for k, v in seen.items()}


# ── 문장 가드 ─────────────────────────────────────────────────────────────

_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_SENT = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s*")


def guard_why(text: str, allowed_text: str) -> tuple[str, int]:
    """근거(계획서·인용)에 없는 수치가 든 문장만 뺀다(카드 전체가 아니라 그 문장만). L12 같은 줄 표기는 허용."""
    kept: list[str] = []
    dropped = 0
    for sent in [s.strip() for s in _SENT.split(text) if s and s.strip()]:
        probe = re.sub(r"\bL\d+(?:\s*[-~,]\s*L?\d+)*", "", sent)
        nums = _NUM.findall(probe)
        if any(n not in allowed_text for n in nums):
            dropped += 1
            continue
        kept.append(sent)
    return " ".join(kept).strip(), dropped


# ── 조립 ─────────────────────────────────────────────────────────────────


def _card_id(plan_id: str, code: RiskCode, evidence_ids: list[str]) -> str:
    h = hashlib.sha256(f"{plan_id}\x00{code.value}\x00{','.join(sorted(evidence_ids))}".encode()).hexdigest()
    return f"card_{h[:12]}"


def finalize(
    drafts: list[CardDraft],
    plan: PlanDocument,
    similarity: dict[str, float],
    all_issues: list[Issue],
    n_works: int,
    drops: Counter,
) -> tuple[list[RiskCard], dict[str, Excerpt], dict[str, Issue]]:
    """불변식을 적용해 RiskCard를 만든다. 어긴 초안은 버리고 사유를 센다."""
    freq = code_work_frequency(all_issues)
    scored: list[tuple[float, RiskCard, list[Issue]]] = []
    seen_sets: set[frozenset[str]] = set()
    for d in drafts:
        if d.risk_code not in CARD_CODES:
            drops["card_code_not_allowed"] += 1
            continue
        ev = list({i.evidence_excerpt().excerpt_id: i for i in d.evidence}.values())[:MAX_EVIDENCE_PER_CARD]
        if len(ev) < MIN_EVIDENCE:
            drops["card_evidence_lt3"] += 1
            continue
        if len({i.work_id for i in ev}) < MIN_WORKS:
            drops["card_works_lt2"] += 1
            continue
        ids = [i.evidence_excerpt().excerpt_id for i in ev]
        if frozenset(ids) in seen_sets:
            drops["card_duplicate"] += 1
            continue
        seen_sets.add(frozenset(ids))
        score = score_card(d.risk_code, ev, similarity, freq, n_works)
        card = RiskCard(
            card_id=_card_id(plan.plan_id, d.risk_code, ids),
            risk_code=d.risk_code,
            title=d.title,
            why_applies=WhyApplies(text=d.why_text, plan_lines=d.plan_lines),
            evidence=ids,
            score=score,
            generator=d.generator,  # type: ignore[arg-type]
            works=list(dict.fromkeys(i.work_id for i in ev)),
            model=d.model,
        )
        scored.append((score.total, card, ev))
    scored.sort(key=lambda t: (-t[0], t[1].risk_code.value, t[1].card_id))
    if len(scored) > MAX_CARDS:
        drops["card_over_max"] += len(scored) - MAX_CARDS
        scored = scored[:MAX_CARDS]
    evidence: dict[str, Excerpt] = {}
    tags: dict[str, Issue] = {}
    for _, _card, ev in scored:
        for iss in ev:
            ex = iss.evidence_excerpt()
            evidence[ex.excerpt_id] = ex
            tags.setdefault(ex.excerpt_id, iss)
    return [c for _, c, _ in scored], evidence, tags


# ── astra 합성 ────────────────────────────────────────────────────────────


def synthesize_cards(
    plan: PlanDocument,
    issues: list[Issue],
    titles: dict[str, str],
    similarity: dict[str, float],
    n_works: int,
    llm: LLMProvider,
    settings: Any = None,
    *,
    short_input: bool = False,
) -> SynthesisResult:
    """astra로 카드를 합성한다. 호출이 실패하면 규칙 카드로 대신한다(fallback_reason 기록).

    short_input: 입력 단계 warn(E3-L1s)이면 지시문에 SHORT_INPUT_NOTE를 덧붙인다(notes에 변형 이름을 남긴다).
    """
    pool = build_pool(issues)
    if not pool:
        return SynthesisResult(cards=[], evidence={}, tags={}, generator="none", pool_size=0,
                               no_card_reason="유사 연구 심사평에서 카드로 만들 수 있는 부정 지적(R1~R8)이 없다")
    alias = {f"E{i + 1}": iss for i, iss in enumerate(pool)}
    ordered = sorted(dict.fromkeys(i.work_id for i in pool), key=lambda w: (-similarity.get(w, 0.0), w))
    paper_alias = {w: f"P{n + 1}" for n, w in enumerate(ordered)}
    opts = task_options(TASK, settings)
    call = LLMCall(
        task=TASK,
        instructions=INSTRUCTIONS + (SHORT_INPUT_NOTE if short_input else ""),
        payload={
            "plan": [f"{ln.no}: {ln.text}" for ln in plan.lines],
            "papers": [
                {"id": p, "title": titles.get(w, ""), "similarity": round(similarity.get(w, 0.0), 3)}
                for w, p in paper_alias.items()
            ],
            "pool": [
                {"id": a, "paper": paper_alias[i.work_id], "risk_code": i.risk_code.value, "text": i.quote[:500]}
                for a, i in alias.items()
            ],
        },
        schema=build_schema(list(alias)),
        schema_name="risk_cards",
        effort=opts["effort"],
        timeout_s=opts["timeout_s"],
        max_output_tokens=16000,
    )
    res = llm.complete_json(call)
    if not res.ok or res.data is None:
        out = rule_cards(plan, issues, similarity, n_works)
        out.llm = res
        out.fallback_reason = res.reason()
        return out
    drops: Counter = Counter()
    drafts: list[CardDraft] = []
    allowed_text = plan.text
    n_lines = len(plan.lines)
    for c in res.data.get("cards", []):
        try:
            code = RiskCode(c.get("risk_code"))
        except ValueError:
            drops["card_bad_code"] += 1
            continue
        ev: list[Issue] = []
        for eid in c.get("evidence_ids", []):
            if eid in alias:
                ev.append(alias[eid])
            else:
                drops["evidence_unknown_id"] += 1
        lines = sorted({n for n in c.get("plan_lines", []) if isinstance(n, int) and 1 <= n <= n_lines})
        if len(lines) != len(set(c.get("plan_lines", []))):
            drops["plan_line_out_of_range"] += len(set(c.get("plan_lines", []))) - len(lines)
        if not lines:
            drops["card_no_plan_lines"] += 1
            continue
        quotes = " ".join(i.quote for i in ev)
        why, n_bad = guard_why(str(c.get("why_applies", "")), allowed_text + " " + quotes)
        drops["why_sentence_unsupported_number"] += n_bad
        if not why:
            why = "계획서 " + ", ".join(f"L{n}" for n in lines) + " 줄이 이 위험 유형에 해당한다."
            drops["why_replaced"] += 1
        title = " ".join(str(c.get("title", "")).split())[:MAX_TITLE] or code.title_ko
        drafts.append(CardDraft(code, title, why, lines, ev, res.generator, res.model))
    drops = +drops
    cards, evidence, tags = finalize(drafts, plan, similarity, issues, n_works, drops)
    reason = res.data.get("no_card_reason")
    no_card = None
    if not cards:
        parts = []
        if reason:
            parts.append(f"{res.generator} 판단: {reason}")
        if drafts or res.data.get("cards"):
            parts.append(f"제안 카드 {len(res.data.get('cards', []))}장이 모두 조립 불변식에서 탈락: " +
                         ", ".join(f"{k} {v}" for k, v in sorted(drops.items()) if k.startswith("card_")))
        no_card = " / ".join(parts) or "카드 없음(사유 미제공)"
    return SynthesisResult(cards=cards, evidence=evidence, tags=tags, generator=res.generator, llm=res,
                           no_card_reason=no_card, drops=drops, pool_size=len(pool),
                           notes=[f"prompt_variant:{SHORT_PROMPT_VARIANT}"] if short_input else [])


# ── 비상 규칙 카드 ────────────────────────────────────────────────────────


def rule_cards(plan: PlanDocument, issues: list[Issue], similarity: dict[str, float], n_works: int) -> SynthesisResult:
    """태그 빈도 카드(비상 경로, 다듬지 않음). generator="rule"."""
    pool = build_pool(issues, max_pool=10_000)
    by_code: dict[RiskCode, list[Issue]] = defaultdict(list)
    for iss in pool:
        by_code[iss.risk_code].append(iss)
    drafts: list[CardDraft] = []
    for code, items in by_code.items():
        # 논문을 돌아가며 신뢰도 순으로 근거를 고른다.
        per_work: dict[str, list[Issue]] = defaultdict(list)
        for iss in sorted(items, key=lambda i: (-i.confidence, i.work_id, i.excerpt.start)):
            per_work[iss.work_id].append(iss)
        ev: list[Issue] = []
        order = sorted(per_work, key=lambda w: (-similarity.get(w, 0.0), w))  # 유사한 논문부터
        while len(ev) < 5 and any(per_work.values()):
            for w in order:
                if per_work[w] and len(ev) < 5:
                    ev.append(per_work[w].pop(0))
        n_w = len({i.work_id for i in items})
        lines = rules.plan_lines_for(code, plan)
        why = (f"비상 규칙 경로: 유사 연구 {n_w}편의 심사평에서 이 유형 지적이 {len(items)}건 나왔다. "
               + (f"계획서 {', '.join(f'L{n}' for n in lines)} 줄을 키워드로 연결했다." if lines else "계획서 줄은 연결하지 못했다."))
        drafts.append(CardDraft(code, f"{code.title_ko} (규칙: 심사평 {n_w}편 반복 지적)", why, lines, ev, "rule"))
    drops: Counter = Counter()
    cards, evidence, tags = finalize(drafts, plan, similarity, issues, n_works, drops)
    no_card = None if cards else "규칙 경로: 근거 3건·논문 2편 이상을 채운 위험 유형이 없다"
    return SynthesisResult(cards=cards, evidence=evidence, tags=tags, generator="rule", no_card_reason=no_card,
                           drops=+drops, pool_size=len(pool))


# ── 분야 수준 카드(E3-L1s, 짧은 입력에서 카드 0장일 때만) ─────────────────────


def field_level_cards(
    plan: PlanDocument, issues: list[Issue], similarity: dict[str, float], n_works: int,
    max_cards: int = FIELD_MAX_CARDS,
) -> SynthesisResult:
    """유사 연구 심사평에서 반복된 위험 유형 → 분야 수준 카드(규칙 합성, generator="rule").

    - 유형마다 부정 지적이 나온 논문 수·지적 수로 순위를 매겨 상위 max_cards개. 불변식(근거 3건·논문 2편)은 그대로.
    - 근거는 지적의 원문 구간(Issue.evidence_excerpt) 그대로다. 문장은 코드가 센 수치만 쓴다(LLM 문장 아님).
    - 계획서 줄에 묶지 않는다(plan_lines=[]): 짧은 입력이라 어느 줄의 문제인지 말할 근거가 없다.
    """
    pool = build_pool(issues, max_pool=10_000)
    by_code: dict[RiskCode, list[Issue]] = defaultdict(list)
    for iss in pool:
        by_code[iss.risk_code].append(iss)
    ranked = sorted(
        by_code.items(),
        key=lambda kv: (-len({i.work_id for i in kv[1]}), -len(kv[1]), kv[0].value),
    )
    drafts: list[CardDraft] = []
    for code, items in ranked:
        n_w = len({i.work_id for i in items})
        if n_w < MIN_WORKS or len(items) < MIN_EVIDENCE:
            continue
        per_work: dict[str, list[Issue]] = defaultdict(list)
        for iss in sorted(items, key=lambda i: (-i.confidence, i.work_id, i.excerpt.start)):
            per_work[iss.work_id].append(iss)
        ev: list[Issue] = []
        order = sorted(per_work, key=lambda w: (-similarity.get(w, 0.0), w))
        while len(ev) < 5 and any(per_work.values()):
            for w in order:
                if per_work[w] and len(ev) < 5:
                    ev.append(per_work[w].pop(0))
        why = (f"분야 수준 위험(규칙 합성): 입력이 짧아 계획서의 어느 줄에 해당하는지는 연결하지 못했다. "
               f"유사 연구 {n_w}편의 심사평에서 이 유형 지적이 {len(items)}건 나왔으니, 계획서에 이 부분을 어떻게 다룰지 적어 두는 것이 좋다.")
        drafts.append(CardDraft(code, f"분야 공통 위험: {code.title_ko} (유사 연구 {n_w}편)", why, [], ev, "rule"))
        if len(drafts) >= max_cards:
            break
    drops: Counter = Counter()
    cards, evidence, tags = finalize(drafts, plan, similarity, issues, n_works, drops)
    no_card = None if cards else "분야 수준 카드도 만들 수 없다: 근거 3건·논문 2편 이상을 채운 위험 유형이 없다"
    return SynthesisResult(cards=cards, evidence=evidence, tags=tags, generator="rule", no_card_reason=no_card,
                           drops=+drops, pool_size=len(pool), notes=["field_level"])
