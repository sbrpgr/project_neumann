"""예상 심사평 (E3-L1a, 계획서 §2 REVIEW · §3 L1). 경로 하나: astra 생성 → 근거 게이트.

- `generate_expected_review(result, llm_call)`: 위험카드와 근거(Excerpt)로 예상 심사평(강점·약점·요청·감사)을 만든다.
  `llm_call(schema, instructions, input, *, effort) -> dict | None`을 **주입**받는다. 실패·시간 초과면 None.
- 모델은 문장마다 근거 **카드 id·excerpt id**(입력 안 별칭 C1·E1)와 계획서 줄 번호만 단다. 인용 문자열은 쓰지 않는다.
  코드가 별칭을 실제 id로 풀고, `gate.gate_sentences`가 문장마다 검사해 실패한 문장만 버린다.
- llm_call이 없거나 None을 돌려주거나 형식이 틀리거나 전부 게이트에서 떨어지면: 규칙 합성(카드 제목·근거 원문
  축자 인용으로 문장 조립)으로 대신하고 `generator="rule"`, `status="degraded"`, 사유를 남긴다.
- 위험카드가 없으면 호출하지 않고 `status="skipped"`와 사유를 남긴다.

반환 dict(= `PremortemResult.expected_review`)는 목업 `review` 구조(`contracts/ui_view.schema.json`의 review)를 따른다:
`strength`·`weakness`·`request`는 문장 목록 `{"t", "c"(excerpt id 목록), "cards", "plan_lines", "quotes"}`,
`audit`는 `{"gen", "pass", "drop", "dropped"([사유, 문장] 쌍), "reasons", "gate", "linked_rate"}`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from neumann.analyze.gate import (
    GATE_VERSION,
    SECTIONS,
    Draft,
    Drop,
    EvidenceIndex,
    GateReport,
    gate_sentences,
)
from neumann.models import Excerpt, Generator, PremortemResult, RiskCard, RiskCode, StageStatus

REVIEW_VERSION = "expected_review@v1"
TASK = "expected_review"
DEFAULT_EFFORT = "medium"
MAX_CARDS = 8
MAX_EVIDENCE_PER_CARD = 4
MAX_SENTENCES_PER_SECTION = 4
MAX_EXCERPT_CHARS = 800
MAX_PLAN_CHARS = 12000
RULE_QUOTE_MAX = 240

LLMCallFn = Callable[..., dict[str, Any] | None]

REVIEW_INSTRUCTIONS = """\
You write the expected peer review that a research plan is likely to receive, before the research starts.

Input (JSON): the plan as numbered lines, and risk cards. Each card (id C1, C2, ...) has a risk type, a title,
why it applies to this plan (with plan line numbers), and evidence: sentences from real peer reviews of similar
published work (id E1, E2, ...).

Write in Korean, in the voice of a reviewer, three sections:
- strength: what the plan already does well or already guards against. Only when a plan line and the evidence
  support it. May be empty.
- weakness: concrete risks this plan is exposed to, one sentence per risk, most serious first.
- request: concrete changes a reviewer would ask for before the work starts.

Hard rules. Sentences that break them are deleted automatically:
1. Every sentence lists in excerpt_ids 1-4 evidence ids that directly support it, and in card_ids the card(s)
   those evidence ids belong to. Use only ids from the input.
2. Never quote or copy evidence text, and do not use quotation marks of any kind. The system attaches the
   original quotations itself.
3. Use a number only if the same number appears in the plan or in the cited evidence. Do not invent sample sizes,
   percentages, thresholds or counts.
4. Put the plan lines a sentence is about in plan_lines. You may mention them in the text like (16-17행), only for
   lines listed in plan_lines.
5. State only what the plan says. Do not attribute to this plan datasets, targets or methods that appear only in
   the evidence about other papers.
6. Do not write ids in the text. At most 4 sentences per section, each under 200 characters.
"""

# 규칙 합성용 요청 문구(위험 유형별). 숫자·따옴표를 넣지 않는다(근거 없는 수치·인용 금지).
RULE_REQUESTS: dict[RiskCode, str] = {
    RiskCode.R1: "핵심 주장마다 이를 뒷받침할 실험·분석을 계획서에 짝지어 둘 것",
    RiskCode.R2: "비교 대상(baseline)과 반복 실험·오차 보고 방식을 착수 전에 명시할 것",
    RiskCode.R3: "학습·검증·평가 데이터의 분할 단위와 중복·누출 제거 절차를 계획서에 명시할 것",
    RiskCode.R4: "데이터 출처와 품질 점검 절차, 대표성의 한계를 계획서에 적을 것",
    RiskCode.R5: "코드·데이터·하이퍼파라미터의 공개 범위와 재현 절차를 정해 둘 것",
    RiskCode.R6: "가장 가까운 선행연구와의 차이를 비교 실험이나 표로 제시할 것",
    RiskCode.R7: "분포 밖 데이터나 다른 조건에서의 일반화 평가를 계획에 넣을 것",
    RiskCode.R8: "실험 검증이나 물리적 타당성 점검 같은 도메인 실증 계획을 추가할 것",
    RiskCode.R9: "연구윤리·데이터 이용 조건과 사후 정정 위험 점검 절차를 명시할 것",
}

_QUOTE_CHARS = "\"'“”‘’「」『』《》«»＂"
# 규칙 문장에 카드 제목을 넣을 때 인용으로 오인될 따옴표를 뺀다(제목은 인용이 아니다)
_TITLE_STRIP = str.maketrans("", "", "\"“”「」『』《》«»＂")


# ── 입력 조립 ─────────────────────────────────────────────────────────────


@dataclass
class ReviewPrompt:
    payload: dict[str, Any]
    card_alias: dict[str, str]  # C1 → card_id
    excerpt_alias: dict[str, str]  # E1 → excerpt_id
    n_plan_lines: int

    @property
    def input_text(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))


def usable_cards(result: PremortemResult) -> list[tuple[RiskCard, list[Excerpt]]]:
    """심사평에 쓸 카드(R0 제외, 근거가 결과 안에 있는 것)와 그 근거. 점수 높은 순, 최대 MAX_CARDS."""
    by_id = {ex.excerpt_id: ex for ex in result.evidence}
    out: list[tuple[RiskCard, list[Excerpt]]] = []
    for card in sorted(result.risk_cards, key=lambda c: -c.score.total):
        if card.risk_code == RiskCode.R0:
            continue
        exs = [by_id[x] for x in dict.fromkeys(card.evidence) if x in by_id][:MAX_EVIDENCE_PER_CARD]
        if exs:
            out.append((card, exs))
    return out[:MAX_CARDS]


def build_review_prompt(result: PremortemResult) -> ReviewPrompt:
    """모델 입력: 계획서 줄(빈 줄 제외) + 카드별 근거. id는 별칭(C1·E1)으로 바꿔 보낸다."""
    card_alias: dict[str, str] = {}
    excerpt_alias: dict[str, str] = {}
    rev_ex: dict[str, str] = {}
    cards_payload: list[dict[str, Any]] = []
    for card, exs in usable_cards(result):
        ca = f"C{len(card_alias) + 1}"
        card_alias[ca] = card.card_id
        ev: list[dict[str, Any]] = []
        for ex in exs:
            if ex.excerpt_id not in rev_ex:
                ea = f"E{len(excerpt_alias) + 1}"
                excerpt_alias[ea] = ex.excerpt_id
                rev_ex[ex.excerpt_id] = ea
            ev.append({"id": rev_ex[ex.excerpt_id], "kind": ex.source_kind, "text": ex.text[:MAX_EXCERPT_CHARS]})
        cards_payload.append(
            {
                "id": ca,
                "risk_code": card.risk_code.value,
                "risk_type": card.risk_code.title_en,
                "title": card.title,
                "why_applies": card.why_applies.text,
                "plan_lines": card.why_applies.plan_lines,
                "n_similar_works": len(card.works),
                "evidence": ev,
            }
        )
    plan_lines: list[dict[str, Any]] = []
    budget = MAX_PLAN_CHARS
    truncated = False
    n_lines = len(result.plan.lines) if result.plan else 0
    if result.plan:
        for ln in result.plan.lines:
            if not ln.text.strip():
                continue
            if budget - len(ln.text) < 0:
                truncated = True
                break
            budget -= len(ln.text)
            plan_lines.append({"no": ln.no, "text": ln.text})
    payload = {
        "plan": {"lines": plan_lines, "truncated": truncated},
        "similar_works": len(result.similar_works),
        "cards": cards_payload,
    }
    return ReviewPrompt(payload, card_alias, excerpt_alias, n_lines)


def build_review_schema(prompt: ReviewPrompt) -> dict[str, Any]:
    """출력 스키마(OpenAI strict 호환: 모든 객체 additionalProperties=false, 모든 속성 required). 인용문 필드 없음."""
    line_item: dict[str, Any] = {"type": "integer", "minimum": 1}
    if prompt.n_plan_lines:
        line_item["maximum"] = prompt.n_plan_lines
    sentence = {
        "type": "object",
        "additionalProperties": False,
        "required": ["text", "card_ids", "excerpt_ids", "plan_lines"],
        "properties": {
            "text": {"type": "string"},
            "card_ids": {"type": "array", "items": {"type": "string", "enum": list(prompt.card_alias)}, "maxItems": 4},
            "excerpt_ids": {
                "type": "array",
                "items": {"type": "string", "enum": list(prompt.excerpt_alias)},
                "minItems": 1,
                "maxItems": 4,
            },
            "plan_lines": {"type": "array", "items": line_item, "maxItems": 6 if prompt.n_plan_lines else 0},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(SECTIONS),
        "properties": {s: {"type": "array", "items": sentence, "maxItems": MAX_SENTENCES_PER_SECTION} for s in SECTIONS},
    }


def parse_llm_review(data: Any, prompt: ReviewPrompt) -> list[dict[str, Any]] | None:
    """모델 출력 → 게이트 입력. 최상위 형식이 틀리면 None. 별칭은 실제 id로 풀고, 모르는 값은 그대로 둬 게이트가 버린다."""
    if not isinstance(data, Mapping) or any(not isinstance(data.get(s), list) for s in SECTIONS):
        return None
    out: list[dict[str, Any]] = []
    for section in SECTIONS:
        for item in data[section]:
            if not isinstance(item, Mapping):
                out.append({"section": section, "text": item})
                continue
            d = dict(item)
            d["section"] = section
            for key, alias in (("excerpt_ids", prompt.excerpt_alias), ("card_ids", prompt.card_alias)):
                seq = d.get(key, [])
                if isinstance(seq, list):
                    d[key] = [alias.get(x, x) if isinstance(x, str) else x for x in seq]
            d.setdefault("card_ids", [])
            d.setdefault("plan_lines", [])
            out.append(d)
    return out


# ── 규칙 합성(비상 경로) ──────────────────────────────────────────────────


def _rule_quote(text: str) -> str | None:
    """근거 원문을 그대로 인용할 조각. 따옴표·줄바꿈이 섞였거나 너무 짧으면 인용하지 않는다."""
    if any(ch in text for ch in _QUOTE_CHARS):
        return None
    piece = max((p.strip() for p in text.split("\n")), key=len, default="")
    if len(piece) > RULE_QUOTE_MAX:
        cut = piece[:RULE_QUOTE_MAX]
        cut = cut[: cut.rfind(" ")] if " " in cut[RULE_QUOTE_MAX // 2 :] else cut
        piece = cut.rstrip()
    if piece == text or len(piece) >= 20:
        return piece
    return None


def _line_ref(lines: list[int]) -> str:
    if not lines:
        return ""
    lines = sorted(set(lines))
    if len(lines) > 1 and lines == list(range(lines[0], lines[-1] + 1)):
        return f" (계획서 {lines[0]}–{lines[-1]}행)"
    return " (계획서 " + ", ".join(str(n) for n in lines) + "행)"


def rule_review_drafts(result: PremortemResult) -> list[dict[str, Any]]:
    """카드 제목·근거로 문장을 조립한다. 약점: 카드마다 한 문장(근거 원문 축자 인용), 요청: 위험 유형별 문구.
    강점은 규칙으로 판단할 수 없으므로 만들지 않는다."""
    n_lines = len(result.plan.lines) if result.plan else 0
    drafts: list[dict[str, Any]] = []
    picked = usable_cards(result)[:MAX_SENTENCES_PER_SECTION]
    for card, exs in picked:
        lines = [n for n in card.why_applies.plan_lines if 1 <= n <= n_lines]
        cite = [ex.excerpt_id for ex in exs[:3]]
        quote = next(((ex, q) for ex in exs if (q := _rule_quote(ex.text))), None)
        title = card.title.translate(_TITLE_STRIP).strip().rstrip(".")
        head = f"{card.risk_code.title_ko} 위험: {title}{_line_ref(lines)}."
        freq = (f" 유사 연구 {len(card.works)}편의 심사에서 같은 유형의 지적이 나왔다" if card.works
                else " 유사 연구 심사에서 같은 유형의 지적이 나왔다")
        if quote is not None:
            ex, q = quote
            if ex.excerpt_id not in cite:
                cite = [ex.excerpt_id, *cite[:2]]
            text = f"{head}{freq}(예: “{q}”)."
        else:
            text = f"{head}{freq}."
        drafts.append(
            {"section": "weakness", "text": text, "excerpt_ids": cite, "card_ids": [card.card_id], "plan_lines": lines}
        )
    for card, exs in picked:
        ask = RULE_REQUESTS.get(card.risk_code)
        if not ask:
            continue
        lines = [n for n in card.why_applies.plan_lines if 1 <= n <= n_lines]
        drafts.append(
            {
                "section": "request",
                "text": f"{ask}{_line_ref(lines)}.",
                "excerpt_ids": [ex.excerpt_id for ex in exs[:3]],
                "card_ids": [card.card_id],
                "plan_lines": lines,
            }
        )
    return drafts


# ── 조립 ─────────────────────────────────────────────────────────────────


_GENERATORS = frozenset(g.value for g in Generator)


def _resolve_generator(llm_call: Any, explicit: Generator | str | None) -> tuple[str, str]:
    """생성 주체 표기: (1) 명시 인자 (2) llm_call의 `generator` 속성. 둘 다 없거나 값이 틀리면 ValueError.

    설정(provider)에서 추정하지 않는다 — 무엇이 호출됐는지 모르는 callable을 astra로 적지 않기 위해서다.
    """
    if explicit is not None:
        if explicit not in _GENERATORS:
            raise ValueError(f"generator 인자 값이 틀렸다: {explicit!r} (허용 {sorted(_GENERATORS)})")
        return Generator(explicit).value, "param"
    attr = getattr(llm_call, "generator", None)
    if attr is None:
        raise ValueError(
            "llm_call의 생성 주체를 알 수 없다: generator= 인자를 주거나 llm_call에 generator 속성"
            "(astra|mock|rule)을 달아라. provider는 provider_llm_call()로 감싸면 속성이 달린다"
        )
    if attr not in _GENERATORS:
        raise ValueError(f"llm_call.generator 값이 틀렸다: {attr!r} (허용 {sorted(_GENERATORS)})")
    return Generator(attr).value, "llm_call"


def _resolve_model(llm_call: Any, explicit: str | None) -> str | None:
    """모델 id: 명시 인자 > llm_call의 `model` 속성 > None(추정하지 않는다)."""
    if explicit is not None:
        return explicit
    attr = getattr(llm_call, "model", None)
    return str(attr) if attr else None


def _assemble(
    *,
    report: GateReport | None,
    generator: str | None,
    model: str | None,
    status: str,
    reason: str | None,
    attempts: list[dict[str, Any]],
    extra_drops: list[Drop],
    t0: float,
    generator_source: str | None = None,
    effort: str | None = None,
) -> dict[str, Any]:
    sections = report.by_section() if report else {s: [] for s in SECTIONS}
    drops = [*extra_drops, *(report.dropped if report else [])]
    gen = sum(a.get("gen", 0) for a in attempts)
    n_pass = sum(len(v) for v in sections.values())
    linked = sum(1 for v in sections.values() for s in v if s["c"])
    reasons: dict[str, int] = {}
    for d in drops:
        reasons[d.reason] = reasons.get(d.reason, 0) + 1
    return {
        "version": REVIEW_VERSION,
        "generator": generator,
        "model": model,
        "generator_source": generator_source,
        "effort": effort,
        "status": status,
        "reason": reason,
        **sections,
        "audit": {
            "gen": gen,
            "pass": n_pass,
            "drop": len(drops),
            "dropped": [d.pair() for d in drops],
            "dropped_detail": [d.as_dict() for d in drops],
            "reasons": reasons,
            "gate": GATE_VERSION,
            "linked_rate": (linked / n_pass) if n_pass else None,
        },
        "attempts": attempts,
        "elapsed_s": round(time.perf_counter() - t0, 3),
    }


def generate_expected_review(
    result: PremortemResult,
    llm_call: LLMCallFn | None,
    *,
    effort: str = DEFAULT_EFFORT,
    generator: Generator | str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """예상 심사평을 만든다. 실행 중 실패로는 죽지 않는다(llm_call 예외도 실패로 받아 규칙 합성으로 간다).

    - llm_call(schema, instructions, input, *, effort) -> dict | None. None이면 실패.
    - generator: 정직 표기용. 명시 인자 또는 llm_call의 `generator` 속성에서만 정한다. llm_call을 줬는데 둘 다
      없으면 **호출 전에** ValueError(사용 오류)로 거부한다. 호출 뒤 속성이 실제 provider 결과로 바뀌면(ProviderLLMCall)
      그 값을 쓴다(인자가 있으면 인자가 이긴다).
    - model: 명시 인자 > llm_call의 `model` 속성 > None.
    """
    t0 = time.perf_counter()
    pre_label = _resolve_generator(llm_call, generator) if llm_call is not None else None  # 호출 전 거부(추정 금지)
    if not usable_cards(result):
        why = "위험카드가 없어 예상 심사평을 만들지 않았다" if not result.risk_cards else "근거가 연결된 위험카드가 없다"
        return _assemble(report=None, generator=None, model=None, status="skipped", reason=why,
                         attempts=[], extra_drops=[], t0=t0)

    index = EvidenceIndex(result)
    attempts: list[dict[str, Any]] = []
    carried: list[Drop] = []
    llm_label: tuple[str, str] | None = None
    if llm_call is None:
        fallback = "llm_call_not_provided: LLM 호출이 주입되지 않았다"
    else:
        prompt = build_review_prompt(result)
        schema = build_review_schema(prompt)
        t_call = time.perf_counter()
        try:
            data = llm_call(schema, REVIEW_INSTRUCTIONS, prompt.input_text, effort=effort)
            error = None
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 규칙 합성으로 넘긴다
            data, error = None, f"llm_call_exception: {type(exc).__name__}"
        latency = round(time.perf_counter() - t_call, 3)
        try:  # 호출 뒤 다시 읽는다: 어댑터는 실제 provider 결과로 속성을 갱신한다
            llm_label = _resolve_generator(llm_call, generator)
        except ValueError:
            llm_label = pre_label
        assert llm_label is not None
        llm_model = _resolve_model(llm_call, model)
        attempt: dict[str, Any] = {"generator": llm_label[0], "model": llm_model, "latency_s": latency, "gen": 0}
        if data is None:
            detail = getattr(llm_call, "last_error", None)
            fallback = error or ("llm_call_failed" + (f": {detail}" if detail else ": None 반환(실패·시간 초과)"))
            attempt["outcome"] = "failed"
        else:
            drafts = parse_llm_review(data, prompt)
            if drafts is None:
                fallback = "llm_output_schema_invalid: 강점·약점·요청 목록이 없다"
                attempt["outcome"] = "schema_invalid"
            else:
                report = gate_sentences(drafts, result, generator=llm_label[0], index=index)
                attempt.update(gen=report.generated, passed=len(report.passed), dropped=len(report.dropped))
                if report.passed:
                    attempt["outcome"] = "ok"
                    attempts.append(attempt)
                    return _assemble(report=report, generator=llm_label[0], model=llm_model, status="ok",
                                     reason=None, attempts=attempts, extra_drops=[], t0=t0,
                                     generator_source=llm_label[1], effort=effort)
                attempt["outcome"] = "all_dropped" if report.generated else "empty"
                fallback = ("llm_all_sentences_dropped: 모델 문장이 전부 근거 게이트에서 떨어졌다"
                            if report.generated else "llm_empty_output: 모델이 문장을 내지 않았다")
                carried = report.dropped
        attempts.append(attempt)

    rule_report = gate_sentences(rule_review_drafts(result), result, generator=Generator.rule.value, index=index)
    attempts.append({"generator": Generator.rule.value, "model": None, "outcome": "ok" if rule_report.passed else "all_dropped",
                     "gen": rule_report.generated, "passed": len(rule_report.passed), "dropped": len(rule_report.dropped)})
    return _assemble(report=rule_report, generator=Generator.rule.value, model=None, status="degraded",
                     reason=fallback, attempts=attempts, extra_drops=carried, t0=t0,
                     generator_source="fallback", effort=None)


def expected_review_stage(review: Mapping[str, Any]) -> StageStatus:
    """파이프라인 단계 기록. 규칙 합성이면 degraded, 카드가 없으면 skipped."""
    status = review.get("status", "error")
    state = {"ok": "ok", "degraded": "degraded", "skipped": "skipped"}.get(status, "error")
    gen = review.get("generator")
    audit = review.get("audit", {})
    if state == "ok":
        detail = f"{gen}:{review.get('model') or '-'} 통과 {audit.get('pass', 0)}/{audit.get('gen', 0)}"
    else:
        detail = review.get("reason") or status
    return StageStatus(
        stage=TASK,
        state=state,
        detail=detail,
        phase="analyze",
        impl="fallback:rule" if gen == Generator.rule.value else "neumann.analyze.review:generate_expected_review",
        elapsed_s=float(review.get("elapsed_s", 0.0)),
        counts={k: int(audit.get(k, 0)) for k in ("gen", "pass", "drop")},
    )


def attach_expected_review(
    result: PremortemResult,
    llm_call: LLMCallFn | None,
    **kwargs: Any,
) -> PremortemResult:
    """결과에 예상 심사평과 단계 기록을 붙인 새 결과. 규칙 합성이면 결과 status도 degraded가 된다."""
    review = generate_expected_review(result, llm_call, **kwargs)
    data = result.model_dump()
    data["expected_review"] = review
    data["stages"] = [*data["stages"], expected_review_stage(review).model_dump()]
    return PremortemResult.model_validate(data)


# ── E3-L0 llm.py provider 어댑터 ─────────────────────────────────────────


# provider 이름 → 생성 주체 (E3-L0 llm.generator_for와 같은 대응. 모르는 이름은 추정하지 않는다)
_PROVIDER_GENERATOR: dict[str, str] = {
    "openai": Generator.astra.value,
    "mock": Generator.mock.value,
    "off": Generator.rule.value,
    "none": Generator.rule.value,
    "disabled": Generator.rule.value,
}


@dataclass(frozen=True)
class _CallSpec:
    """neumann.llm.LLMCall이 없을 때 쓰는 같은 모양의 호출 명세(덕 타이핑)."""

    task: str
    instructions: str
    payload: dict[str, Any]
    schema: dict[str, Any]
    schema_name: str
    effort: str | None = None
    timeout_s: float | None = None
    max_output_tokens: int | None = None

    def input_text(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))


class ProviderLLMCall:
    """`provider.complete_json(LLMCall) -> LLMResult`(E3-L0 llm.py)를 이 모듈의 llm_call 모양으로 감싼다.

    `generator` 속성은 **만들 때 반드시 정해진다**: 인자 → provider 이름(openai→astra, mock→mock, off→rule).
    이름을 모르면 ValueError(추정 금지). 호출 뒤에는 `generator`·`model`·`last_error`·`last_result`를
    실제 provider 결과(LLMResult.generator·model)로 갱신한다.
    """

    def __init__(
        self,
        provider: Any,
        *,
        task: str = TASK,
        timeout_s: float | None = None,
        max_output_tokens: int | None = None,
        generator: Generator | str | None = None,
    ) -> None:
        self.provider = provider
        self.task = task
        self.timeout_s = timeout_s
        self.max_output_tokens = max_output_tokens
        if generator is None:
            name = str(getattr(provider, "name", "") or "").lower()
            generator = _PROVIDER_GENERATOR.get(name)
            if generator is None:
                raise ValueError(f"provider {name or type(provider).__name__!r}의 생성 주체를 알 수 없다: generator= 인자를 줘라")
        if generator not in _GENERATORS:
            raise ValueError(f"generator 값이 틀렸다: {generator!r}")
        self.generator: str = Generator(generator).value
        self.model: str | None = getattr(provider, "model", None)
        self.last_error: str | None = None
        self.last_result: Any = None

    def __call__(self, schema: dict[str, Any], instructions: str, input: str, *, effort: str) -> dict[str, Any] | None:  # noqa: A002
        try:
            from neumann.llm import LLMCall as call_cls  # type: ignore[import-not-found]
        except ImportError:
            call_cls = _CallSpec
        payload = json.loads(input) if isinstance(input, str) else dict(input)
        call = call_cls(task=self.task, instructions=instructions, payload=payload, schema=schema,
                        schema_name=self.task, effort=effort, timeout_s=self.timeout_s,
                        max_output_tokens=self.max_output_tokens)
        res = self.provider.complete_json(call)
        self.last_result = res
        self.model = getattr(res, "model", None) or self.model
        gen = getattr(res, "generator", None)
        if gen in _GENERATORS:  # 실제 결과의 표기로 갱신. 모르는 값이면 만들 때 정한 값을 유지한다
            self.generator = Generator(gen).value
        if getattr(res, "ok", False) and isinstance(getattr(res, "data", None), dict):
            self.last_error = None
            return res.data
        reason = getattr(res, "reason", None)
        self.last_error = reason() if callable(reason) else str(getattr(res, "error", "failed"))
        return None


def provider_llm_call(provider: Any, **kwargs: Any) -> ProviderLLMCall:
    """파이프라인 연결용: `generate_expected_review(result, provider_llm_call(make_llm(settings)))`."""
    return ProviderLLMCall(provider, **kwargs)


__all__ = [
    "DEFAULT_EFFORT",
    "LLMCallFn",
    "ProviderLLMCall",
    "REVIEW_INSTRUCTIONS",
    "REVIEW_VERSION",
    "RULE_REQUESTS",
    "ReviewPrompt",
    "attach_expected_review",
    "build_review_prompt",
    "build_review_schema",
    "expected_review_stage",
    "generate_expected_review",
    "parse_llm_review",
    "provider_llm_call",
    "rule_review_drafts",
    "usable_cards",
]
