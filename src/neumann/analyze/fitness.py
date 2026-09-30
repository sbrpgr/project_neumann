"""입력 적합성 판정 (E3-L1c).

계획서가 분석할 수 있는 연구계획서인지 판정한다: 연구 요소(질문·방법·데이터·평가), 분야, 언어, 판정 사유.

- **주력은 astra.** `llm_call(schema, instructions, input, *, effort) -> dict | None`을 주입받는다(E3-L1a와 같은 방식).
  모델은 판정·요소별 계획서 **줄 번호**·분야·사유만 돌려준다. 코드가 스키마와 줄 번호를 다시 검사한다.
- **비상 경로는 규칙.** llm_call이 None을 돌려주거나 예외·스키마 위반이면 키워드·길이 규칙으로 판정하고
  `generator="rule"`, `status="degraded"`로 표기한다(규칙 결과를 LLM 결과라고 쓰지 않는다).
- **과잉 거절 방지(설계 원칙):** 판정은 세 갈래다. `fit`(분석), `unfit`(분석하지 않음 + 사유),
  `uncertain`(거절하지 않고 분석을 진행하되 빠진 요소와 보완 질문을 알린다). 모델이 "연구 아님"이라 해도 규칙 신호가
  강하면 `uncertain`으로 내린다. 판정 신호를 하나에 걸지 않는다(모델 판정 + 근거 줄 + 규칙 신호).
- 모델에 보내는 본문은 개인정보를 다시 가린다(`pii.mask_pii`). 모델이 쓴 사유·분야도 가린다.
- 언어(ko·en·mixed)는 코드가 글자 수로 잰다(결정적이고 호출이 필요 없다).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import jsonschema

from neumann.analyze.pii import mask_pii, mask_pii_counts
from neumann.models import Generator, PlanDocument, StageStatus

LLMCallable = Callable[..., dict[str, Any] | None]

DEFAULT_EFFORT = "low"
MIN_CHARS = 40  # 공백을 뺀 글자 수가 이보다 적으면 판정할 거리가 없다(호출하지 않는다)
MAX_INPUT_CHARS = 12000  # 모델에 보내는 본문 상한
MAX_REASON_CHARS = 500
MAX_FIELD_CHARS = 60

ELEMENTS: tuple[str, ...] = ("research_question", "method", "data", "evaluation")
ELEMENT_KO: dict[str, str] = {
    "research_question": "연구 질문·목표",
    "method": "방법",
    "data": "데이터",
    "evaluation": "평가",
}
# 빠진 요소를 보완하라는 질문(규칙 문구, LLM 생성 아님)
FOLLOWUP_KO: dict[str, str] = {
    "research_question": "이 연구로 답하려는 질문이나 목표는 무엇인가요?",
    "method": "어떤 방법(모델·실험 설계·분석 절차)을 쓸 계획인가요?",
    "data": "어떤 데이터를 어디서, 얼마나 모을 계획인가요?",
    "evaluation": "결과를 어떤 지표와 비교 대상(기준선)으로 평가하나요?",
}
VERDICT_LABEL_KO: dict[str, str] = {"fit": "연구계획서", "unfit": "분석하지 않음", "uncertain": "판정 보류(분석 진행)"}

# ── astra 호출 계약 ───────────────────────────────────────────────────────

_ELEMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["present", "plan_lines"],
    "properties": {
        "present": {"type": "boolean"},
        "plan_lines": {"type": "array", "items": {"type": "integer"}},
    },
}

FITNESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "elements", "field", "reason"],
    "properties": {
        "verdict": {"type": "string", "enum": ["research_plan", "not_research_plan", "uncertain"]},
        "elements": {
            "type": "object",
            "additionalProperties": False,
            "required": list(ELEMENTS),
            "properties": {e: _ELEMENT_SCHEMA for e in ELEMENTS},
        },
        "field": {"type": "string"},
        "reason": {"type": "string"},
    },
}

INSTRUCTIONS = """You screen inputs for a research-risk analysis tool. A user pasted a text that should be a research plan
(a proposal, a study design, or a research abstract), usually in Korean, sometimes mixed with English.
Decide whether it is a research plan that can be analyzed. The input is JSON; its "plan" field lists the non-empty
lines as "<line number>: <text>" (empty lines omitted, "truncated_after_line" is set if the text was cut).

Return JSON that matches the schema:
- verdict:
  - "research_plan": the text describes a research study: at least some of research question/goal, method, data,
    evaluation. Proposals, study designs, research abstracts, and short but real research ideas all count.
    Do not reject a research text just because some parts are missing or it is written informally.
  - "not_research_plan": the text is not research at all (e.g. recipe, story, diary, advertisement, travel plan,
    shopping list, chat message, song lyrics, code or logs without any research framing).
  - "uncertain": research-related but too thin or ambiguous to tell.
- elements: for each of research_question (question, goal, hypothesis), method (model, experiment design, analysis),
  data (datasets, samples, participants, collection), evaluation (metrics, baselines, validation, statistics):
  present=true only if the text actually states it; plan_lines = the line numbers from the input that state it
  (empty list when absent). Use only line numbers that appear in the input. Never invent line numbers.
- field: a short label of the research field in Korean (e.g. "재료과학·배터리 전해액"). Empty string if not research.
- reason: one or two sentences in Korean explaining the verdict. Refer to line numbers instead of quoting the text.
  Do not copy personal information (names, phone numbers, emails) into the reason.
"""

# ── 규칙 신호 (비상 판정·교차 확인) ─────────────────────────────────────


def _en(*words: str) -> re.Pattern[str]:
    return re.compile(r"(?i)\b(?:" + "|".join(words) + r")\b")


_LEXICON: dict[str, tuple[tuple[str, ...], re.Pattern[str]]] = {
    "research_question": (
        ("연구 목표", "연구목표", "연구 목적", "연구목적", "목표", "목적", "연구 질문", "연구질문", "가설", "연구 문제",
         "규명", "밝히", "하고자 한다", "하고자 함", "제안한다", "제안하"),
        _en(r"aims?", r"objectives?", r"goals?", r"hypothes\w*", r"research questions?", r"propos\w*",
            r"this (?:study|work|paper|project)", r"purpose", r"investigat\w*"),
    ),
    "method": (
        ("방법", "모델", "알고리즘", "학습", "기법", "실험", "분석", "설계", "신경망", "분류기", "회귀", "시뮬레이션",
         "인코더", "추정", "측정"),
        _en(r"methods?", r"methodology", r"models?", r"algorithms?", r"train\w*", r"approach\w*", r"architectures?",
            r"networks?", r"framework", r"pipeline", r"simulat\w*", r"regression", r"classifiers?", r"experiments?",
            r"fine-?tun\w*", r"transformers?", r"gnn", r"cnn", r"estimat\w*"),
    ),
    "data": (
        ("데이터", "자료", "표본", "샘플", "피험자", "참가자", "참여자", "코호트", "수집", "말뭉치", "코퍼스", "영상",
         "관측"),
        _en(r"data", r"datasets?", r"samples?", r"cohorts?", r"participants?", r"subjects?", r"corpus", r"corpora",
            r"collect\w*", r"records?", r"images?", r"annotat\w*"),
    ),
    "evaluation": (
        ("평가", "성능", "정확도", "지표", "비교", "통계", "유의", "교차검증", "교차 검증", "테스트셋", "테스트 셋",
         "검증", "기준선", "재현율", "정밀도", "민감도", "특이도", "오차"),
        _en(r"evaluat\w*", r"accuracy", r"metrics?", r"baselines?", r"test(?:ing)? sets?", r"validat\w*", r"f1",
            r"auc", r"roc(?:-auc)?", r"mae", r"rmse", r"r2", r"precision", r"recall", r"significan\w*",
            r"ablations?", r"holdout", r"cross-?validation", r"benchmarks?", r"error bars?"),
    ),
}

# 연구와 무관한 글의 장르 표지(조리법·여행·쇼핑·가사·일기)
_OFFTOPIC_KO: tuple[str, ...] = (
    "재료", "만드는 법", "만드는법", "레시피", "큰술", "작은술", "꼬집", "인분", "볶", "끓여", "끓인", "굽는", "간을 맞", "팬에",
    "불에서", "조리", "요리", "양념", "덮밥", "오븐", "냉장고", "썰어", "여행", "숙소", "관광", "맛집", "쇼핑", "할인",
    "구매", "주문", "배송", "후렴", "일기",
)
_OFFTOPIC_EN = _en(
    r"recipes?", r"ingredients?", r"tablespoons?", r"teaspoons?", r"tbsp", r"tsp", r"preheat\w*", r"bak(?:e|ed|ing)",
    r"simmer\w*", r"servings?", r"chopped", r"minced", r"saut[eé]\w*", r"itinerary", r"hotel", r"sightseeing",
    r"discount", r"lyrics", r"chorus", r"diary",
)

# 신경과학 표지(E3-L1x). 인공 신경망(neural network, 신경망·심층신경망·신경회로망)과 신경 연산자(neural operator)는
# AI 방법이지 신경과학이 아니다. 영어는 neur\w*가 아니라 neuro\w*(neuron·neuronal·neuroscience·neuroimaging)만 잡는다.
# 한국어는 "신경" 단독 대신 신경과학 복합어만 잡고, "뇌우"(기상)와 "~인지"(어미)는 빼려고 정규식으로 둔다.
_NEURO_KO = re.compile(
    r"신경\s?(?:과학|세포|생리|영상|활동|신호|질환)|신경\s?회로(?!망)|신경계|뉴런|뇌(?!우)"
    r"|인지\s?(?:과학|과제|기능|능력|부하|저하|장애|심리)"
)
_NEURO_EN = _en(r"neuro\w*", r"fmri", r"eeg", r"brains?", r"cognit\w*")

_FIELDS: tuple[tuple[str, tuple[str, ...] | re.Pattern[str], re.Pattern[str]], ...] = (
    ("재료·화학", ("전해액", "배터리", "전지", "분자", "소재", "촉매", "화합물", "고분자"),
     _en(r"electrolyt\w*", r"batter(?:y|ies)", r"molecul\w*", r"materials?", r"catalys\w*", r"polymers?", r"chemi\w*")),
    ("신경과학·뇌영상", _NEURO_KO, _NEURO_EN),
    ("의료·의료영상", ("의료", "임상", "환자", "진단", "폐렴", "X선", "병변"),
     _en(r"clinic\w*", r"patients?", r"diagnos\w*", r"x-?ray", r"radiolog\w*", r"medical", r"patholog\w*")),
    ("자연어처리", ("자연어", "언어모델", "언어 모델", "텍스트", "말뭉치"),
     _en(r"nlp", r"language models?", r"llms?", r"corpus", r"translation")),
    ("컴퓨터비전", ("이미지", "객체 탐지", "영상 분할"), _en(r"images?", r"vision", r"object detection", r"segmentation")),
    ("생명과학·생물정보", ("유전체", "단백질", "세포", "유전자"),
     _en(r"genom\w*", r"proteins?", r"cells?", r"genes?", r"rna", r"dna")),
    ("기후·지구과학", ("기후", "기상", "강수", "해양", "대기"),
     _en(r"climate", r"weather", r"precipitation", r"ocean\w*", r"atmospher\w*")),
    ("물리·공학", ("물리", "역학", "유체", "플라즈마"), _en(r"physic\w*", r"fluids?", r"plasma", r"quantum")),
)


def _line_hits(text: str, ko: tuple[str, ...] | re.Pattern[str], en: re.Pattern[str]) -> list[str]:
    """한 줄에서 찾은 표지. 한국어 `ko`는 부분 문자열 목록이거나(대부분) 제외 조건이 필요한 정규식이다."""
    terms = [m.group(0) for m in ko.finditer(text)] if isinstance(ko, re.Pattern) else [w for w in ko if w in text]
    terms += [m.group(0).lower() for m in en.finditer(text)]
    return terms


def detect_language(text: str) -> dict[str, Any]:
    """한글 음절·자모 수와 로마자 수로 언어를 잰다. 한글 1자는 로마자 약 2자로 본다."""
    hangul = sum(1 for ch in text if "가" <= ch <= "힣" or "ㄱ" <= ch <= "ㆎ")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if hangul + latin < 10:
        lang = "unknown"
        share = 0.0
    else:
        share = 2 * hangul / (2 * hangul + latin)
        lang = "ko" if share >= 0.6 else "en" if share <= 0.25 else "mixed"
    return {"language": lang, "hangul_share": round(share, 3), "hangul_chars": hangul, "latin_chars": latin}


def rule_fitness(plan: PlanDocument) -> dict[str, Any]:
    """키워드·길이 규칙 판정. 비상 경로이자 모델 판정의 교차 확인 신호다."""
    elements: dict[str, list[int]] = {e: [] for e in ELEMENTS}
    offtopic_lines: list[int] = []
    offtopic_terms: set[str] = set()
    field_scores: dict[str, int] = {}
    for ln in plan.lines:
        if not ln.text.strip():
            continue
        for e, (ko, en) in _LEXICON.items():
            if _line_hits(ln.text, ko, en):
                elements[e].append(ln.no)
        off = _line_hits(ln.text, _OFFTOPIC_KO, _OFFTOPIC_EN)
        if off:
            offtopic_lines.append(ln.no)
            offtopic_terms.update(off)
        for name, ko, en in _FIELDS:
            if _line_hits(ln.text, ko, en):
                field_scores[name] = field_scores.get(name, 0) + 1
    n_chars = sum(1 for ch in plan.text if not ch.isspace())
    n_elem = sum(1 for e in ELEMENTS if elements[e])
    research_hits = sum(len(v) for v in elements.values())
    offtopic_hits = len(offtopic_lines)

    if n_chars < MIN_CHARS:
        verdict, precheck = "unfit", "too_short"
        reason = f"본문이 너무 짧다(공백 제외 {n_chars}자, 최소 {MIN_CHARS}자). 연구 질문·방법·데이터·평가를 적어 달라."
    elif n_elem >= 3 and offtopic_hits <= research_hits:
        verdict, precheck = "fit", None
        reason = f"연구 요소 {n_elem}/4개의 표지가 보인다(규칙 판정)."
    elif n_elem <= 1 and (offtopic_hits >= 2 or research_hits == 0):
        verdict, precheck = "unfit", None
        why = f"연구와 무관한 글의 표지 {offtopic_hits}줄" if offtopic_hits else "연구 담화 표지 없음"
        reason = f"연구 요소 표지가 {n_elem}/4개뿐이고 {why}: 연구계획서로 보기 어렵다(규칙 판정)."
    else:
        verdict, precheck = "uncertain", None
        reason = f"연구 요소 표지 {n_elem}/4개, 무관 표지 {offtopic_hits}줄: 규칙으로는 판단하기 어렵다(규칙 판정)."

    field = max(field_scores, key=lambda k: field_scores[k]) if field_scores else None
    return {
        "verdict": verdict,
        "precheck": precheck,
        "reason": reason,
        "elements": {e: {"present": bool(elements[e]), "plan_lines": elements[e]} for e in ELEMENTS},
        "n_elements": n_elem,
        "research_hits": research_hits,
        "offtopic_hits": offtopic_hits,
        "offtopic_terms": sorted(offtopic_terms),
        "n_chars": n_chars,
        "field": field,
    }


# ── 모델 입력·출력 검사 ───────────────────────────────────────────────────


def build_llm_input(plan: PlanDocument, max_chars: int = MAX_INPUT_CHARS) -> tuple[str, dict[str, Any]]:
    """빈 줄을 뺀 `번호: 본문` 목록. 개인정보를 다시 가리고, 상한을 넘으면 뒤를 자른다."""
    out: list[str] = []
    used = 0
    masked: dict[str, int] = {}
    last_no = 0
    truncated = False
    for ln in plan.lines:
        if not ln.text.strip():
            continue
        text, counts = mask_pii_counts(ln.text)
        for k, v in counts.items():
            masked[k] = masked.get(k, 0) + v
        row = f"{ln.no}: {text}"
        if used + len(row) + 1 > max_chars and out:
            truncated = True
            break
        out.append(row)
        used += len(row) + 1
        last_no = ln.no
    # JSON 문자열로 준다: provider 어댑터(review.provider_llm_call)가 input을 JSON payload로 읽는다
    payload = {
        "n_lines": len(plan.lines),
        "empty_lines_omitted": True,
        "truncated_after_line": last_no if truncated else None,
        "plan": "\n".join(out),
    }
    meta = {"truncated": truncated, "last_line_sent": last_no, "pii_masked": masked}
    return json.dumps(payload, ensure_ascii=False), meta


def parse_llm_output(raw: Any, plan: PlanDocument) -> tuple[dict[str, Any] | None, str | None, int]:
    """모델 출력 → (정리된 값, 실패 사유, 버린 줄 번호 수). 스키마를 로컬에서 다시 검사한다."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, f"json_invalid: {exc.msg}", 0
    if not isinstance(raw, dict):
        return None, f"schema_invalid: 최상위가 객체가 아니다({type(raw).__name__})", 0
    errors = sorted(jsonschema.Draft202012Validator(FITNESS_SCHEMA).iter_errors(raw), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.absolute_path) or "(root)"
        return None, f"schema_invalid: {len(errors)}건, 첫 오류 {path}: {first.message[:120]}", 0

    valid_lines = {ln.no for ln in plan.lines if ln.text.strip()}
    dropped = 0
    elements: dict[str, dict[str, Any]] = {}
    for e in ELEMENTS:
        item = raw["elements"][e]
        lines = sorted({n for n in item["plan_lines"] if n in valid_lines})
        dropped += len(item["plan_lines"]) - len([n for n in item["plan_lines"] if n in valid_lines])
        # 근거 줄이 없는 "있음"은 인정하지 않는다
        elements[e] = {"present": bool(item["present"] and lines), "plan_lines": lines if item["present"] else []}
    reason = mask_pii(raw["reason"].strip())[:MAX_REASON_CHARS]
    field = mask_pii(raw["field"].strip())[:MAX_FIELD_CHARS] or None
    if not reason:
        return None, "semantic_invalid: 판정 사유가 비었다", dropped
    return {"verdict": raw["verdict"], "elements": elements, "field": field, "reason": reason}, None, dropped


# ── 판정 ──────────────────────────────────────────────────────────────────


def _followups(missing: list[str]) -> list[dict[str, str]]:
    return [{"element": e, "question": FOLLOWUP_KO[e]} for e in missing]


def _notice(verdict: str, reason: str, missing: list[str]) -> str | None:
    if verdict == "unfit":
        return f"분석하지 않음: {reason}"
    if verdict == "uncertain":
        miss = ", ".join(ELEMENT_KO[e] for e in missing) or "없음"
        return f"연구계획서인지 확실하지 않아 분석은 진행하지만 결과가 부정확할 수 있다. 확인되지 않은 요소: {miss}. {reason}"
    return None


def _result(
    *,
    verdict: str,
    reason: str,
    elements: dict[str, dict[str, Any]],
    field: str | None,
    generator: str,
    model: str | None,
    status: str,
    decided_by: str,
    degraded_reason: str | None,
    model_verdict: str | None,
    rule: dict[str, Any],
    language: dict[str, Any],
    checks: dict[str, Any],
    t0: float,
) -> dict[str, Any]:
    missing = [e for e in ELEMENTS if not elements[e]["present"]]
    return {
        "verdict": verdict,
        "analyze": verdict != "unfit",
        "is_research_plan": {"fit": True, "unfit": False}.get(verdict),
        "label_ko": VERDICT_LABEL_KO[verdict],
        "reason": reason,
        "notice": _notice(verdict, reason, missing),
        "field": field,
        "language": language["language"],
        "elements": elements,
        "missing": missing,
        "followup_questions": _followups(missing) if verdict == "uncertain" else [],
        "generator": generator,
        "model": model,
        "status": status,
        "decided_by": decided_by,
        "degraded_reason": degraded_reason,
        "model_verdict": model_verdict,
        "rule": rule,
        "language_detail": language,
        "checks": checks,
        "elapsed_s": round(time.perf_counter() - t0, 3),
    }


def _rule_result(rule: dict[str, Any], language: dict[str, Any], checks: dict[str, Any], t0: float, *,
                 status: str, decided_by: str, degraded_reason: str | None) -> dict[str, Any]:
    return _result(
        verdict=rule["verdict"], reason=rule["reason"], elements=rule["elements"], field=rule["field"],
        generator=Generator.rule.value, model=None, status=status, decided_by=decided_by,
        degraded_reason=degraded_reason, model_verdict=None, rule=rule, language=language, checks=checks, t0=t0,
    )


def resolve_generator(llm_call: Any, explicit: Generator | str | None) -> str:
    """생성 주체 표기: (1) `generator=` 인자 (2) `llm_call.generator` 속성. 둘 다 없거나 값이 틀리면 ValueError.

    설정(provider)이나 기본값에서 추정하지 않는다: 무엇이 호출됐는지 모르는 callable을 astra로 적지 않는다
    (E3-L1a `review._resolve_generator`와 같은 규칙).
    """
    if explicit is not None:
        try:
            return Generator(explicit).value
        except ValueError:
            raise ValueError(f"generator 인자 값이 틀렸다: {explicit!r} (허용 {[g.value for g in Generator]})") from None
    attr = getattr(llm_call, "generator", None)
    if attr is None:
        raise ValueError(
            "llm_call의 생성 주체를 알 수 없다: generator= 인자를 주거나 llm_call에 generator 속성"
            "(astra|mock|rule)을 달아라. provider는 review.provider_llm_call()로 감싸면 속성이 달린다"
        )
    try:
        return Generator(attr).value
    except ValueError:
        raise ValueError(f"llm_call.generator 값이 틀렸다: {attr!r}") from None


def _resolve_model(llm_call: Any, explicit: str | None) -> str | None:
    """모델 id: 인자 > `llm_call.model` 속성 > None(추정하지 않는다)."""
    if explicit is not None:
        return explicit
    attr = getattr(llm_call, "model", None)
    return str(attr) if attr else None


def assess_fitness(
    plan: PlanDocument,
    llm_call: LLMCallable | None,
    *,
    generator: Generator | str | None = None,
    model: str | None = None,
    effort: str = DEFAULT_EFFORT,
    max_chars: int = MAX_INPUT_CHARS,
) -> dict[str, Any]:
    """계획서 적합성 판정. astra(`llm_call`) 판정이 주력이고, 실패하면 규칙 판정으로 강등한다.

    `llm_call(schema, instructions, input, *, effort) -> dict | None`. None·예외·스키마 위반은 모두 비상 경로로 간다.
    생성 주체는 `generator=` 인자나 `llm_call.generator` 속성에서만 읽는다. 둘 다 없으면 **호출 전에** ValueError
    (기본값·설정으로 추정하지 않는다). 모델 id는 `model=` 인자나 `llm_call.model` 속성, 없으면 None.
    반환: verdict(fit·unfit·uncertain), analyze(분석 여부), reason, notice(화면 문구), field, language,
    elements(요소별 present·plan_lines), missing, followup_questions, generator, model, status(ok·degraded),
    decided_by(llm·rule_fallback·precheck), degraded_reason, model_verdict, rule(규칙 신호), checks, elapsed_s.
    """
    t0 = time.perf_counter()
    pre_gen = resolve_generator(llm_call, generator) if llm_call is not None else None  # 호출 전 거부
    rule = rule_fitness(plan)
    language = detect_language(plan.text)
    checks: dict[str, Any] = {"dropped_lines": 0, "overrides": []}

    if rule["precheck"] == "too_short":  # 판정할 거리가 없다: 호출하지 않는다(강등 아님)
        return _rule_result(rule, language, checks, t0, status="ok", decided_by="precheck", degraded_reason=None)
    if llm_call is None:
        return _rule_result(rule, language, checks, t0, status="degraded", decided_by="rule_fallback",
                            degraded_reason="llm_unavailable: llm_call 없음")

    llm_input, meta = build_llm_input(plan, max_chars)
    checks.update(meta)
    try:
        raw = llm_call(FITNESS_SCHEMA, INSTRUCTIONS, llm_input, effort=effort)
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 비상 경로로 넘긴다
        return _rule_result(rule, language, checks, t0, status="degraded", decided_by="rule_fallback",
                            degraded_reason=f"llm_exception: {type(exc).__name__}")
    if raw is None:
        why = getattr(llm_call, "last_error", None)  # provider 어댑터가 남긴 실패 사유(비밀값 없음)
        return _rule_result(rule, language, checks, t0, status="degraded", decided_by="rule_fallback",
                            degraded_reason="llm_unavailable: " + (str(why) if why else "호출 실패 또는 시간 초과"))
    parsed, problem, dropped = parse_llm_output(raw, plan)
    checks["dropped_lines"] = dropped
    if parsed is None:
        return _rule_result(rule, language, checks, t0, status="degraded", decided_by="rule_fallback",
                            degraded_reason=problem)

    model_verdict = parsed["verdict"]
    n_present = sum(1 for e in ELEMENTS if parsed["elements"][e]["present"])
    reason = parsed["reason"]
    if model_verdict == "research_plan":
        if n_present >= 2 or rule["verdict"] == "fit":
            verdict = "fit"
        else:
            verdict = "uncertain"
            checks["overrides"].append(f"모델은 연구계획서로 봤지만 근거 줄이 있는 요소가 {n_present}/4개뿐이다")
    elif model_verdict == "not_research_plan":
        if rule["verdict"] == "fit":
            verdict = "uncertain"  # 과잉 거절 방지(ID-97): 규칙 신호가 강하면 거절하지 않는다
            checks["overrides"].append(
                f"모델은 연구계획서가 아니라고 봤지만 규칙 신호(연구 요소 {rule['n_elements']}/4)가 강해 거절하지 않는다"
            )
        else:
            verdict = "unfit"
    else:
        verdict = "uncertain"
    try:  # 호출 뒤 다시 읽는다: 어댑터는 실제 provider 결과로 generator·model 속성을 갱신한다
        gen = resolve_generator(llm_call, generator)
    except ValueError:
        gen = pre_gen
    assert gen is not None
    return _result(
        verdict=verdict, reason=reason, elements=parsed["elements"], field=parsed["field"] or rule["field"],
        generator=gen, model=_resolve_model(llm_call, model), status="ok", decided_by="llm", degraded_reason=None,
        model_verdict=model_verdict, rule=rule, language=language, checks=checks, t0=t0,
    )


def fitness_stage(result: dict[str, Any]) -> StageStatus:
    """판정 결과 → 파이프라인 단계 기록(`PremortemResult.stages`에 넣는다). 강등이면 degraded로 남긴다."""
    impl = {
        "llm": "neumann.analyze.fitness:assess_fitness",
        "rule_fallback": "fallback:rule_fitness",
        "precheck": "neumann.analyze.fitness:rule_fitness(precheck)",
    }[result["decided_by"]]
    detail = f"{result['verdict']} by {result['generator']}"
    if result["degraded_reason"]:
        detail += f" — {result['degraded_reason']}"
    if result["checks"].get("overrides"):  # 규칙 신호가 모델 판정을 바꿨으면 단계 기록에도 남긴다
        detail += f" (model {result['model_verdict']} → {result['verdict']}: 규칙 신호로 조정)"
    return StageStatus(
        stage="fitness",
        state="degraded" if result["status"] == "degraded" else "ok",
        detail=detail,
        phase="input",
        impl=impl,
        elapsed_s=float(result["elapsed_s"]),
        counts={
            "elements_present": sum(1 for e in ELEMENTS if result["elements"][e]["present"]),
            "dropped_lines": int(result["checks"].get("dropped_lines", 0)),
            "overrides": len(result["checks"].get("overrides", [])),
        },
    )


__all__ = [
    "DEFAULT_EFFORT",
    "ELEMENTS",
    "FITNESS_SCHEMA",
    "INSTRUCTIONS",
    "assess_fitness",
    "build_llm_input",
    "detect_language",
    "fitness_stage",
    "resolve_generator",
    "parse_llm_output",
    "rule_fitness",
]
