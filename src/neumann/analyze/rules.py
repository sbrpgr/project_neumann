"""비상 규칙 경로(최소). astra 호출이 실패하거나 시간 상한을 넘은 단계만 이것으로 대신한다.

다듬지 않는다(계획서 §3 L0). 여기서 만든 결과는 항상 generator="rule"로 표기한다.
- 검색어: 계획서의 영문 기술어 + 목표 줄
- 지적 태깅: E2의 `neumann.index.taxonomy` 태거를 먼저 쓰고, 없으면 아래 최소 키워드 사전
- 계획서 줄: 유형별 키워드가 나오는 줄
- 연구계획서 여부: 연구 어휘 개수
"""

from __future__ import annotations

import re
from collections.abc import Callable

from neumann.models import Excerpt, PlanDocument, RiskCode

# ── 검색어 ────────────────────────────────────────────────────────────────

_EN_STOP = {
    "the", "and", "for", "with", "into", "from", "this", "that", "are", "was", "were", "will", "not", "due",
    "we", "our", "no", "is", "be", "to", "of", "in", "on", "an", "a", "as", "by", "at", "or", "do", "does",
    "sets", "set", "report", "planned", "released", "agreement", "study",
}
_EN_PHRASE = re.compile(r"[A-Za-z][A-Za-z0-9\-]*(?:\s+[A-Za-z0-9][A-Za-z0-9\-]*)*")


def english_terms(text: str) -> list[str]:
    """계획서에 섞인 영문 구절(기술어). 순서 보존, 중복 제거."""
    seen: dict[str, None] = {}
    for m in _EN_PHRASE.finditer(text):
        words = [w for w in m.group(0).split() if w.lower() not in _EN_STOP and len(w) > 1]
        phrase = " ".join(words).strip()
        if len(phrase) >= 2 and phrase.lower() not in (k.lower() for k in seen):
            seen[phrase] = None
    return list(seen)


def fallback_queries(plan: PlanDocument, max_queries: int = 6) -> list[str]:
    """영문 기술어를 묶은 검색어 + 목표 줄(원문, 다국어 임베딩용)."""
    terms = english_terms(plan.text)
    queries: list[str] = []
    chunk: list[str] = []
    for term in terms:
        chunk.append(term)
        if sum(len(t) for t in chunk) > 60:
            queries.append(" ".join(chunk))
            chunk = []
    if chunk:
        queries.append(" ".join(chunk))
    goal = _first_content_line(plan)
    if goal:
        queries.append(goal)
    return queries[:max_queries] or [plan.text[:300]]


def _first_content_line(plan: PlanDocument) -> str | None:
    for ln in plan.lines:
        t = ln.text.strip()
        if t and not t.startswith("#") and len(t) > 15:
            return t[:300]
    return None


def fallback_axes(plan: PlanDocument) -> dict[str, str]:
    """제목(## 방법/데이터/평가, Method/Data/Evaluation) 아래 줄을 축으로 모은다."""
    heads = {
        "method": re.compile(r"(방법|method|approach|model)", re.I),
        "data": re.compile(r"(데이터|data|dataset)", re.I),
        "evaluation": re.compile(r"(평가|evaluation|experiment|validation)", re.I),
    }
    axes: dict[str, list[str]] = {k: [] for k in heads}
    current: str | None = None
    for ln in plan.lines:
        t = ln.text.strip()
        if t.startswith("#"):
            current = next((k for k, p in heads.items() if p.search(t)), None)
            continue
        if current and t:
            axes[current].append(t)
    return {k: " ".join(v)[:500] for k, v in axes.items() if v}


# ── 연구계획서 여부 ────────────────────────────────────────────────────────

_RESEARCH_WORDS = re.compile(
    r"(연구|실험|데이터|모델|평가|분석|검증|가설|학습|측정|방법론|대리모델|분류기|"
    r"\b(?:research|experiment\w*|dataset|data|model\w*|evaluat\w*|baseline\w*|hypothes\w+|"
    r"train\w*|test|validation|accuracy|method\w*|analysis|benchmark\w*)\b)",
    re.I,
)


def research_signal(plan: PlanDocument) -> int:
    return len(_RESEARCH_WORDS.findall(plan.text))


def looks_like_research(plan: PlanDocument, min_hits: int = 4) -> bool:
    return research_signal(plan) >= min_hits


# ── 지적 태깅(최소 키워드 사전, E2 태거가 없을 때만) ─────────────────────────

_CUES: dict[RiskCode, list[str]] = {
    RiskCode.R1: [
        r"\bnot (?:well )?(?:justified|supported|convincing)\b", r"\boverclaim\w*|\boverstat\w*",
        r"\bdo(?:es)? not (?:support|demonstrate|show|establish)\b", r"\bnot sufficient evidence\b",
        r"\bunjustified\b", r"\bnot convinced\b",
    ],
    RiskCode.R2: [
        r"\bbaselines?\b", r"\bablation", r"\berror bars?\b", r"\bstandard deviations?\b",
        r"\bconfidence intervals?\b", r"\b(?:single|multiple|several|different|random) (?:seeds?|runs?)\b",
        r"\bstatistical(?:ly)? (?:significan\w+|test\w*)", r"\bvariance\b", r"\bfair comparison\b",
        r"\b(?:more|additional|further) (?:experiments?|evaluations?|ablations?)\b",
    ],
    RiskCode.R3: [
        r"\bleak(?:age|ed|ing|s)?\b", r"\bcontaminat\w+", r"\brandom(?:ly)? split\b", r"\bscaffold split\b",
        r"\bnear[- ]duplicates?\b", r"\bduplicates?\b[^.]{0,60}\b(?:train|test)", r"\boverlap\w*\b[^.]{0,40}\b(?:train|test)",
    ],
    RiskCode.R4: [
        r"\blabel noise\b", r"\bnoisy labels?\b", r"\bdata quality\b", r"\bsample size\b", r"\bimbalance\w*\b",
        r"\bmeasurement conditions?\b", r"\bheterogene\w+\b", r"\bprovenance\b", r"\bmissing values?\b",
        r"\bunrepresentative\b|\bnot representative\b",
    ],
    RiskCode.R5: [
        r"\b(?:code|data|dataset|weights)\b[^.]{0,40}\b(?:not (?:available|released|provided|shared)|unavailable)\b",
        r"\breproduc\w+\b", r"\bhyper-?parameters?\b[^.]{0,40}\b(?:not|missing|unclear)", r"\bimplementation details\b",
        r"\brelease the code\b",
    ],
    RiskCode.R6: [
        r"\bnovelty\b", r"\bincremental\b", r"\bprior work\b", r"\brelated work\b", r"\bnot new\b", r"\balready (?:proposed|known)\b",
    ],
    RiskCode.R7: [
        r"\bgenerali[sz]\w+\b", r"\bout[- ]of[- ]distribution\b", r"\bexternal (?:validation|test\w*|datasets?)\b",
        r"\bother (?:datasets?|domains?|sites?|hospitals?|chemistr\w+)\b", r"\bunseen\b",
    ],
    RiskCode.R8: [
        r"\bexperimental(?:ly)? (?:validat\w+|verif\w+)\b", r"\bwet[- ]lab\b", r"\bsynthesi[sz]ed\b",
        r"\bphysical(?:ly)? (?:plausib\w+|constraints?|meaningful)\b", r"\bclinical (?:validation|study|trial|relevance)\b",
        r"\bdomain experts?\b", r"\bradiologists?\b",
    ],
    RiskCode.R0: [r"\btypos?\b", r"\bhard to (?:follow|read)\b", r"\bwriting\b", r"\bnotation\b", r"\bpresentation\b"],
}
_NEGATIVE = [
    r"\b(?:strong|extensive|comprehensive|solid|thorough) (?:baselines?|experiments?|evaluation|ablations?)\b",
    r"\bwell[- ]written\b", r"\bleaky ?relu\b", r"\b(?:gradient|memory|privacy) leak\w*\b",
]
_COMPILED = {code: [re.compile(p, re.I) for p in pats] for code, pats in _CUES.items()}
_NEG_COMPILED = [re.compile(p, re.I) for p in _NEGATIVE]


def keyword_tags(text: str) -> list[tuple[RiskCode, float]]:
    """문장 → (유형, 신뢰도) 목록. 긍정 표현이 있으면 비운다."""
    if any(p.search(text) for p in _NEG_COMPILED):
        return []
    out: list[tuple[RiskCode, float]] = []
    for code, pats in _COMPILED.items():
        hits = sum(1 for p in pats if p.search(text))
        if hits:
            out.append((code, min(0.4 + 0.1 * hits, 0.6)))
    return out


RuleTag = tuple[Excerpt, RiskCode, str, float]  # (발췌, 유형, 극성, 신뢰도)
RuleTagger = Callable[[list[Excerpt]], list[RuleTag]]


def make_rule_tagger() -> tuple[RuleTagger, str]:
    """비상 경로 태거. E2 `neumann.index.taxonomy.tag_excerpts`(절 제목 기반 극성 포함)가 있으면 그것을,
    없으면 최소 키워드 사전을 쓴다. (태거, impl 이름)."""
    try:
        from neumann.index import taxonomy as e2_tax  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        e2_tax = None
    fn = getattr(e2_tax, "tag_excerpts", None) if e2_tax is not None else None
    if callable(fn):
        return _wrap_e2(fn), "neumann.index.taxonomy:tag_excerpts"
    return keyword_tagger, "neumann.analyze.rules:keyword_tags"


def keyword_tagger(excerpts: list[Excerpt]) -> list[RuleTag]:
    return [(ex, code, "negative", conf) for ex in excerpts for code, conf in keyword_tags(ex.text)]


def _wrap_e2(fn: Callable) -> RuleTagger:
    def tagger(excerpts: list[Excerpt]) -> list[RuleTag]:
        by_id = {ex.excerpt_id: ex for ex in excerpts}
        try:
            tags = fn(excerpts)
        except Exception:  # noqa: BLE001 — E2 태거가 깨져도 비상 경로는 돈다
            return keyword_tagger(excerpts)
        out: list[RuleTag] = []
        for t in tags or []:
            ex = by_id.get(getattr(t, "excerpt_id", None))
            code = getattr(t, "risk_code", None)
            if ex is None or code is None:
                continue
            try:
                rc = RiskCode(str(getattr(code, "value", code)).split(".")[0])
            except ValueError:
                continue
            pol = getattr(t, "polarity", "negative")
            conf = float(getattr(t, "confidence", 0.5) or 0.5)
            out.append((ex, rc, pol if pol in ("negative", "positive", "neutral") else "negative", max(0.0, min(1.0, conf))))
        return out

    return tagger


# ── 계획서 줄(규칙 카드용) ──────────────────────────────────────────────────

_PLAN_CUES: dict[RiskCode, str] = {
    RiskCode.R1: r"(기대|달성|주장|claim|outperform|더 높은|우수)",
    RiskCode.R2: r"(baseline|기준선|비교|ablation|error bar|seed|시드|유의성|R2|MAE|AUC|정확도|지표|metric)",
    RiskCode.R3: r"(split|분할|중복|duplicate|leak|누출|holdout|test set|테스트셋)",
    RiskCode.R4: r"(데이터|수집|문헌|label|라벨|측정|dataset|샘플|피험자)",
    RiskCode.R5: r"(code|코드|공개|release|재현|가중치|weights)",
    RiskCode.R6: r"(기존|선행|prior|novel|신규)",
    RiskCode.R7: r"(일반화|외부|external|holdout|다른|확장|generali)",
    RiskCode.R8: r"(실험 합성|합성|실증|임상|clinical|물리|검증|synthesis)",
}


def plan_lines_for(code: RiskCode, plan: PlanDocument, limit: int = 3) -> list[int]:
    pat = _PLAN_CUES.get(code)
    if not pat:
        return []
    rx = re.compile(pat, re.I)
    return [ln.no for ln in plan.lines if not ln.text.lstrip().startswith("#") and rx.search(ln.text)][:limit]
