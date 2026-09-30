"""비상 경로용 최소 규칙 태거: 심사평 문장 → R0~R8 태그 후보. `generator="rule"`.

주력은 astra 지적 추출(E3)이다. 이 태거는 API가 실패했을 때 카드가 나오는 데까지만 쓴다. 다듬지 않는다.
패턴은 `부록/설계/03_risk_taxonomy.md` §3의 탐지 큐·거부 큐를 줄여 새로 적은 것이다(영어).

- 문장마다 코드별 점수 = 탐지 큐 가중치 합 − 거부 큐 가중치 합. `min_score`(기본 2) 이상이면 태그.
- R9(연구윤리·사후 위험)는 심사평에서 추론하지 않는다(가드레일). 사후기록(E1-L2)에서만 온다.
- 극성: 심사평 절 제목(Strengths/Weaknesses …)을 따라가고, 절을 모르면 문장 단서로 정한다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from neumann.models import Excerpt, Generator, RiskCode, RiskTag

Pattern = tuple[int, str]

# (가중치, 정규식). 대소문자 무시.
DETECT: dict[RiskCode, list[Pattern]] = {
    RiskCode.R1: [
        (2, r"\b(?:claim|claims|claimed|conclusion|statement)s?\b[^.]{0,90}\b(?:not (?:correct|true|supported|justified|convincing)|too strong|overstat\w*|overclaim\w*|unsupported|not backed)"),
        (2, r"\b(?:not|hardly|insufficiently)\s+(?:convincing|compelling)\b"),
        (2, r"\b(?:proof|theorem|lemma|derivation|equation|proposition)\b[^.]{0,80}\b(?:incorrect|wrong|flaw\w*|not (?:valid|correct|rigorous)|error|gap|does not hold)"),
        (2, r"\bassumptions?\b[^.]{0,70}\b(?:too strong|unrealistic|not (?:verified|justified|checked|validated)|questionable|restrictive)"),
        (2, r"\b(?:does|do|did)\s+not\s+(?:support|demonstrate|show|prove|establish|justify)\b"),
        (2, r"\bnot\s+(?:well\s+)?justified\b"),
        (2, r"\bevidence\b[^.]{0,60}\b(?:weak|insufficient|not enough|lacking)"),
        (2, r"\b(?:I|we)\s+(?:am|are)\s+not\s+convinced\b"),
        (2, r"\bnot\s+sufficient\s+evidence\b"),
    ],
    RiskCode.R2: [
        (1, r"\bbaselines?\b"),
        (2, r"\bbaselines?\b[^.]{0,80}\b(?:weak|simple|old|outdated|missing|not (?:included|compared)|stronger|more recent)"),
        (2, r"\bablation(?:s|\s+stud(?:y|ies)|\s+experiments?)?\b"),
        (2, r"\b(?:error bars?|standard deviations?|confidence intervals?|95% CI)\b"),
        (2, r"\b(?:multiple|several|different|random)\s+seeds?\b|\bsingle\s+(?:seed|run)\b"),
        (2, r"\bvarian\w+\b[^.]{0,60}\b(?:not reported|missing|unclear|should|analysis)"),
        (2, r"\bstatistical(?:ly)?\s+(?:significan\w+|test\w*)|\bp-values?\b|\bsignificance test"),
        (2, r"\b(?:improvements?|gains?|differences?|margins?)\b[^.]{0,60}\b(?:marginal|negligible|within (?:the )?(?:noise|error|std)|not significant|too small)"),
        (2, r"\bhyper-?parameters?\b[^.]{0,90}\b(?:fair|same budget|equally|grid search|tuned|how (?:were|was)|chosen)"),
        (2, r"\b(?:metrics?|evaluation measures?)\b[^.]{0,70}\b(?:not (?:appropriate|suitable|standard|meaningful)|misleading|does not (?:capture|reflect))"),
        (2, r"\bfair\s+comparison\b"),
        (2, r"\b(?:more|additional|further)\s+(?:experiments?|evaluations?|datasets?|benchmarks?|ablations?)\b"),
        (2, r"\bexperiments?\b[^.]{0,60}\b(?:do|does|did)\s+not\s+(?:conclusively\s+)?(?:show|demonstrate|support|establish)"),
    ],
    RiskCode.R3: [
        (2, r"\b(?:data|information|label|test)\s+leak(?:age|s|ed|ing)?\b"),
        (2, r"\bleak(?:age|ed|ing)\b"),
        (2, r"\bcontaminat(?:ion|ed|es)\b"),
        (2, r"\b(?:train|training)[-/ ](?:and[- ])?(?:test|validation|val)\b[^.]{0,60}\b(?:split|overlap|leak|contaminat|same|shared)"),
        (2, r"\b(?:test|held[- ]?out)\s+(?:set|data|samples?)\b[^.]{0,70}\b(?:appear|occur|seen|during training)"),
        (2, r"\b(?:randomly\s+split|random\s+split|scaffold split|temporal split|cluster split|leave[- ]one[- ]cluster[- ]out|group k-?fold)\b"),
        (2, r"\b(?:duplicate|near[- ]duplicate|redundan\w+)\b[^.]{0,60}\b(?:train|test|dataset|samples?|structures?)"),
        (2, r"\bpre-?process\w*\b[^.]{0,60}\b(?:before|prior to|whole|entire|full)\s+(?:the\s+)?(?:split|dataset|data)"),
        (2, r"\bnormali[sz]\w+\b[^.]{0,50}\b(?:entire|whole|full)\s+dataset"),
    ],
    RiskCode.R4: [
        (2, r"\b(?:data|dataset)\s+(?:quality|collection|curation|provenance|acquisition)\b"),
        (2, r"\bhow (?:was|were) the (?:data|dataset)\b"),
        (2, r"\b(?:label|annotation|ground[- ]truth)\w*\b[^.]{0,70}\b(?:noise|noisy|quality|errors?|reliab\w+|inconsist\w+|inter-?annotator)"),
        (2, r"\b(?:small|limited|insufficient|tiny|few)\b[^.]{0,45}\b(?:dataset|data|sample size|number of (?:samples|examples|subjects|patients))"),
        (2, r"\b(?:sample size|statistical power|underpowered|power analysis)\b"),
        (2, r"\b(?:missing (?:values?|data)|imputat\w+)\b"),
        (2, r"\b(?:different|inconsistent|varying|heterogeneous)\s+(?:sources?|labs?|protocols?|conditions?|instruments?|sites?|batches?)\b"),
        (2, r"\b(?:publication bias|survivorship bias|selection bias)\b"),
        (2, r"\b(?:batch effects?|confound(?:er|ers|ing|ed)?)\b"),
        (2, r"\b(?:negative|positive|appropriate|proper)\s+controls?\b"),
    ],
    RiskCode.R5: [
        (2, r"\breproduc(?:e|ible|ibility|ing)\b|\breplicab\w+"),
        (2, r"\b(?:code|implementation|source code)\b[^.]{0,70}\b(?:not (?:available|released|provided|public)|will (?:be )?(?:released?|provided)|be (?:made )?(?:public|available)|open[- ]source)"),
        (2, r"\b(?:implementation|experimental|training)\s+details?\b[^.]{0,60}\b(?:missing|not (?:provided|given|reported)|unclear|lack\w*)"),
        (2, r"\b(?:hyper-?parameters?|learning rate|batch size|number of epochs)\b[^.]{0,60}\b(?:not (?:reported|specified|given|provided)|missing|unclear)"),
        (2, r"\b(?:training|inference|computational|runtime|memory|GPU)\b[^.]{0,45}\b(?:cost|budget|time|overhead|requirements?|hours?)\b[^.]{0,60}\b(?:not (?:reported|provided|discussed)|missing|unclear|should)"),
        (2, r"\b(?:dataset|data)\b[^.]{0,50}\b(?:not (?:available|released|shared)|cannot be (?:accessed|obtained))"),
        (2, r"\bopen[- ]?sourc\w+\b"),
        (2, r"\b(?:details?|information)\b[^.]{0,45}\b(?:are|is)\s+missing\b"),
    ],
    RiskCode.R6: [
        (2, r"\bnovelt(?:y|ies)\b"),
        (2, r"\bincremental\b"),
        (2, r"\b(?:contribution|novelty)s?\b[^.]{0,60}\b(?:limited|marginal|minor|narrow|unclear|not (?:clear|significant|enough))"),
        (2, r"\b(?:already|previously)\s+(?:known|proposed|shown|studied|explored)\b"),
        (2, r"\b(?:similar|close|identical)\s+to\b[^.]{0,60}\b(?:existing|prior|previous)\s+(?:work|method|approach)"),
        (2, r"\brelated work\b[^.]{0,70}\b(?:missing|incomplete|omit\w*|not (?:discussed|cited)|should (?:include|discuss|cite))"),
        (2, r"\b(?:missing|omitted|overlooked|not cited|fail(?:s|ed)? to cite)\b[^.]{0,70}\b(?:work|literature|papers?|references?|citations?)"),
        (2, r"\b(?:should|could|must)\s+(?:cite|compare (?:with|to)|discuss)\b"),
        (2, r"\bhow does\b[^.]{0,60}\bcompare (?:to|with)\b"),
    ],
    RiskCode.R7: [
        (1, r"\bgenerali[sz](?:e|es|ed|ation|ability|able)\b"),
        (2, r"\bgenerali[sz]\w*\b[^.]{0,60}\b(?:to (?:other|new|unseen|real|larger|different)|beyond|unclear|not (?:clear|shown|evaluated)|question)"),
        (2, r"\b(?:out[- ]of[- ]distribution|OOD|distribution shift|domain shift|covariate shift)\b"),
        (2, r"\bextrapolat\w+"),
        (2, r"\bapplicability domain\b|\bdomain of applicability\b"),
        (2, r"\blimitations?\b[^.]{0,70}\b(?:not (?:discussed|stated|addressed|acknowledged)|missing|should be (?:discussed|added))"),
        (2, r"\b(?:only|just)\s+(?:evaluated|tested|validated|demonstrated)\s+(?:on|in|for)\b"),
        (2, r"\b(?:real[- ]world|practical|deployment|clinical)\b[^.]{0,60}\b(?:setting|scenario|applicab\w+|unclear|not (?:clear|shown|evaluated))"),
        (2, r"\b(?:does|do)\s+not\s+(?:apply|hold|transfer|generali[sz]e)\b"),
        (1, r"\b(?:unseen|other|different)\s+(?:domains?|datasets?|distributions?|species|chemistries|materials)\b"),
    ],
    RiskCode.R8: [
        (2, r"\b(?:DFT|density functional|molecular dynamics|force ?field|first[- ]principles|ab initio)\b"),
        (2, r"\b(?:synthesizab\w+|synthetic accessibility|retrosynthe\w+)\b"),
        (2, r"\b(?:thermodynamic|phase)\s+stab\w+|\bformation energy\b|\benergy above (?:the )?hull\b|\bconvex hull\b"),
        (2, r"\b(?:wet[- ]?lab|in vitro|in vivo|bench(?:top)?\s+experiments?)\b"),
        (1, r"\bexperimental(?:ly)?\s+(?:valid\w+|verif\w+|confirm\w+)\b"),
        (2, r"\b(?:charge neutrality|valence|oxidation state|stoichiometr\w+|space group|crystal structure)\b"),
        (2, r"\b(?:physical(?:ly)?|chemical(?:ly)?)\s+(?:plausib\w+|realistic|meaningful|consistent|implausib\w+)\b"),
        (2, r"\b(?:ionic conductivity|electrochemical (?:stability )?window|viscosity|interfacial stab\w+|cycle life)\b"),
    ],
    RiskCode.R0: [
        (2, r"\b(?:typos?|grammar|grammatical|spelling)\b"),
        (2, r"\b(?:hard|difficult)\s+to\s+(?:read|follow|parse|understand)\b"),
        (2, r"\b(?:writing|presentation|notation|wording|phrasing)\b[^.]{0,50}\b(?:unclear|confusing|poor|improve|inconsistent)"),
        (2, r"\b(?:figure|fig\.|table|caption|axis|legend)\b[^.]{0,50}\b(?:unclear|confusing|missing label|hard to read|too small)"),
        (2, r"\b(?:section|paragraph|sentence)\b[^.]{0,40}\b(?:unclear|confusing|should be (?:moved|rewritten|shortened))"),
    ],
}

REJECT: dict[RiskCode, list[Pattern]] = {
    RiskCode.R1: [(2, r"\b(?:claims?|conclusions?)\b[^.]{0,40}\b(?:well[- ]supported|convincing|sound|solid)")],
    RiskCode.R2: [
        (2, r"\bablation\s+stud(?:y|ies)\s+(?:is|are)\s+(?:thorough|comprehensive|convincing|extensive)"),
        (2, r"\b(?:strong|extensive|comprehensive|solid)\s+(?:baselines?|experiments?|evaluation)\b"),
    ],
    RiskCode.R3: [(2, r"\b(?:gradient|memory|activation|privacy|parameter)\s+leak(?:age)?\b"), (2, r"\bleaky\s*ReLU\b")],
    RiskCode.R4: [(2, r"\bcontrol (?:variate|flow|theory|signal|policy)\b"), (2, r"\bNegative results do not necessarily mean\b")],
    RiskCode.R5: [(2, r"\bcode (?:is|was) (?:provided|available|released)\b(?![^.]{0,40}\bnot\b)")],
    RiskCode.R6: [
        (2, r"\b(?:novel|novelty)\b[^.]{0,40}\b(?:is clear|is significant|is high|and interesting|and important)"),
        (2, r"\bto (?:the )?best of my knowledge[^.]{0,40}\b(?:novel|new|first)\b"),
    ],
    RiskCode.R7: [
        (2, r"\bgenerali[sz]es? well\b|\bstrong generali[sz]ation\b"),
        (2, r"\bgenerali[sz]ation\s+(?:error|gap|bounds?|theory)\b"),
    ],
    RiskCode.R8: [
        (2, r"\b(?:image|speech|audio|video|text|data|program|code|scene|motion|view)\s+synthesis\b"),
        (2, r"\bDFT\s+(?:matrix|transform|coefficients?|basis)\b|\bFourier\s+transform\b"),
    ],
    RiskCode.R0: [
        (2, r"\bunclear\b[^.]{0,60}\b(?:how (?:the )?(?:model|method|algorithm) (?:is|was) (?:implement|train|initiali[sz])|hyper-?parameter|experimental setup)"),
    ],
}

_DETECT_RE = {c: [(w, re.compile(p, re.I)) for w, p in ps] for c, ps in DETECT.items()}
_REJECT_RE = {c: [(w, re.compile(p, re.I)) for w, p in ps] for c, ps in REJECT.items()}

# 심사평 절 제목 → 극성
_SECTION = re.compile(
    r"^\W{0,4}(strengths?|pros|weakness(?:es)?|cons|questions?|limitations?|concerns?|summary|"
    r"soundness|presentation|contribution|rating|confidence|flag for ethics review|details of ethics concerns)\b\W{0,4}:?",
    re.I,
)
_SECTION_POLARITY = {
    "strength": "positive", "strengths": "positive", "pros": "positive",
    "weakness": "negative", "weaknesses": "negative", "cons": "negative", "limitation": "negative",
    "limitations": "negative", "concern": "negative", "concerns": "negative",
    "question": "neutral", "questions": "neutral", "summary": "neutral",
}
_NEG_CUE = re.compile(
    r"\b(?:not|no|lack\w*|missing|unclear|weak\w*|limited|insufficient|concern\w*|however|should|fail\w*|"
    r"problem\w*|issue\w*|question\w*|doubt\w*|confus\w*|unfortunately|incorrect|wrong|outdated|only)\b|\?",
    re.I,
)
_POS_CUE = re.compile(
    r"\b(?:well[- ]written|clear|strong|convincing|novel|interesting|thorough|impressive|good|nice|"
    r"solid|comprehensive|extensive|important|significant contribution|easy to follow|appreciate)\b",
    re.I,
)

MIN_SCORE = 2


@dataclass(frozen=True)
class RuleHit:
    risk_code: RiskCode
    score: int


def classify(text: str, *, min_score: int = MIN_SCORE) -> list[RuleHit]:
    """문장 → 규칙 점수 min_score 이상인 코드(점수 내림차순, 같으면 코드 순)."""
    hits: list[RuleHit] = []
    for code, pats in _DETECT_RE.items():
        score = sum(w for w, rx in pats if rx.search(text))
        if not score:
            continue
        score -= sum(w for w, rx in _REJECT_RE.get(code, []) if rx.search(text))
        if score >= min_score:
            hits.append(RuleHit(code, score))
    hits.sort(key=lambda h: (-h.score, h.risk_code.value))
    return hits


def section_of(text: str) -> str | None:
    m = _SECTION.match(text)
    return m.group(1).lower() if m else None


def polarity_of(text: str, section: str | None = None) -> str:
    """절 제목이 알려 주면 그것을, 아니면 문장 단서(부정·긍정 어휘 수)로."""
    if section in _SECTION_POLARITY and _SECTION_POLARITY[section] != "neutral":
        return _SECTION_POLARITY[section]
    neg = len(_NEG_CUE.findall(text))
    pos = len(_POS_CUE.findall(text))
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral" if section in _SECTION_POLARITY else "negative"


def confidence_of(score: int, polarity: str) -> float:
    base = min(0.9, 0.4 + 0.1 * score)
    return round(base if polarity == "negative" else base * 0.5, 3)


def tag_excerpts(excerpts: Sequence[Excerpt], *, min_score: int = MIN_SCORE) -> list[RiskTag]:
    """한 심사평(또는 한 논문)의 Excerpt들(원문 순서) → RiskTag 목록. 절 제목을 따라가며 극성을 정한다.

    서로 다른 심사평이 섞여 있으면 source_id가 바뀔 때 절 상태를 초기화한다.
    """
    tags: list[RiskTag] = []
    section: str | None = None
    current_source: str | None = None
    for ex in excerpts:
        if ex.source_id != current_source:
            current_source, section = ex.source_id, None
        sec = section_of(ex.text)
        if sec is not None:
            section = sec
        hits = classify(ex.text, min_score=min_score)
        if not hits:
            continue
        pol = polarity_of(ex.text, section)
        for hit in hits:
            tags.append(
                RiskTag(
                    excerpt_id=ex.excerpt_id,
                    risk_code=hit.risk_code,
                    polarity=pol,  # type: ignore[arg-type]
                    confidence=confidence_of(hit.score, pol),
                    generator=Generator.rule,
                )
            )
    return tags


def tag_text(text: str, *, min_score: int = MIN_SCORE) -> list[RiskCode]:
    """문장 하나 → 코드 목록(편의 함수)."""
    return [h.risk_code for h in classify(text, min_score=min_score)]


def tag_counts(tags: Iterable[RiskTag]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in tags:
        out[t.risk_code.value] = out.get(t.risk_code.value, 0) + 1
    return dict(sorted(out.items()))


__all__ = [
    "DETECT",
    "MIN_SCORE",
    "REJECT",
    "RuleHit",
    "classify",
    "polarity_of",
    "section_of",
    "tag_counts",
    "tag_excerpts",
    "tag_text",
]
