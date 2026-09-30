"""예방 체크리스트(ACTION) — 카드마다 착수 전 예방 행동 1~3개를 계획서 줄 번호에 연결한다 (E3-L1b).

흐름
1. 위험카드를 3장씩 묶어 astra에 보낸다. `llm_call`은 주입받는다(E3-L1a와 같은 모양):
   `llm_call(schema: dict, instructions: str, input: str, *, effort: str) -> dict | None`
   입력은 카드 id·유형·제목·해당 이유(계획서 줄 번호)·근거 발췌(excerpt id + 원문)·계획서 전체 줄이다.
2. 모델은 카드마다 행동 문구·확인 조건·계획서 줄 번호·근거 excerpt id만 돌려준다. **인용문 필드는 없다.**
3. 코드가 다시 검사한다: 입력에 없는 card_id는 버리고, 없는 줄 번호(범위 밖·빈 줄)는 제거하고,
   그 카드의 근거 풀 밖 excerpt id는 제거한다. 문구 길이·중복을 보고, 행동은 카드당 최대 3개.
   제거한 참조는 항목의 `dropped`에 남긴다(조용히 버리지 않는다).
4. **근거 게이트(E3-L1e)**: 근거 id가 비었거나, 남은 근거가 하나도 없으면(없는 id·다른 카드의 id만 댔으면)
   그 행동은 **폐기**한다. 카드 근거를 대신 붙이지 않고(승계 없음) 다시 묻지도 않는다(재요청 없음).
   폐기 수·사유는 단계 기록 counts(`items_dropped_no_evidence`)와 `result.verification["checklist_evidence"]`에 남고,
   화면에는 "근거 없는 항목 k개 제외"로 나온다. 마지막에 규칙 항목까지 모든 항목을 같은 검사
   (`gate.evidence_link_problem`: 근거 1개 이상, 전부 결과 evidence 안, 전부 그 카드의 근거 안)로 한 번 더 거른다.
5. 호출 실패(None·예외·모양 오류)이거나, 카드가 응답에서 빠졌거나, 행동이 전부 무효(근거 없음 포함)면 **그 카드만**
   규칙 경로(카드 유형별 기본 행동 문구)로 대신하고 `generator="rule"`과 `fallback_reason`을 남긴다.
6. 항목마다 결정 로그 자리: `decision`(None → 채택·보류·기각)과 `decision_log`(이력).

카드(주장)와 행동(제안)은 따로 검증한다. 2차 의미검증(validate.py)이 카드를 '틀림'으로 강등해도
이 모듈이 만든 행동은 지우지 않는다.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from neumann.analyze.gate import MALFORMED, MISSING_CITATION, EvidenceIndex, evidence_link_problem
from neumann.models import Excerpt, PlanDocument, PremortemResult, RiskCard, RiskCode, StageStatus, redact_pii

log = logging.getLogger(__name__)

LLMCall = Callable[..., dict[str, Any] | None]

CARDS_PER_CALL = 3  # 옛 GEN-1 실측: 8장을 한 번에 넣으면 출력이 길어져 시간 상한을 넘겼다
MAX_PARALLEL_CALLS = 3
MAX_ACTIONS_PER_CARD = 3
MAX_EVIDENCE_PER_CARD = 4
EVIDENCE_CHARS = 600
ACTION_MIN_CHARS = 5
ACTION_MAX_CHARS = 300
VERIFY_MAX_CHARS = 300
DEFAULT_EFFORT = "medium"
IMPL = "neumann.analyze.checklist:build_checklist"
EVIDENCE_GATE = "checklist_evidence@v1"  # 근거 게이트 버전(E3-L1e)
DROPPED_TEXT_MAX = 300

DECISION_STATES: tuple[str, ...] = ("채택", "보류", "기각")

# 비상 규칙 경로: 카드 유형별 기본 행동 문구. 계획서 줄은 카드의 해당 이유 줄을 그대로 쓴다.
RULE_ACTIONS: dict[RiskCode, tuple[str, ...]] = {
    RiskCode.R0: (
        "제출 전에 저자가 아닌 동료 1인이 방법 절만 읽고 재구현 가능 여부를 판단하는 교차 읽기 일정을 잡는다.",
        "기호·용어 정의표를 원고 작성 시작 시점에 만들고 모든 수식과 그림이 그 표를 따르게 한다.",
    ),
    RiskCode.R1: (
        "핵심 주장마다 그 주장을 반증할 수 있는 실험을 짝지은 주장-근거 표를 만들고, 짝이 없는 주장은 문구를 약화한다.",
        "핵심 가정을 나열하고 가정마다 검증 실험이나 민감도 분석을 계획에 넣는다.",
    ),
    RiskCode.R2: (
        "비교 대상(최신 방법, 강한 단순 기준선, 제안법에서 핵심 요소를 뺀 버전)을 착수 전에 고정하고 계획서에 적는다.",
        "반복 실행 횟수와 보고 형식(평균·표준편차 또는 신뢰구간)을 착수 전에 정해 계획서에 명시한다.",
    ),
    RiskCode.R3: (
        "데이터를 만지기 전에 그룹 단위 분할 규칙을 문서로 고정하고, 그룹이 분할 경계를 넘지 않는지 코드로 검사한다.",
        "중복·근사중복 제거 기준을 착수 전에 정하고, 무작위 분할과 그룹 분할 성능을 함께 보고하기로 계획에 적는다.",
    ),
    RiskCode.R4: (
        "데이터 출처·수집 시점·라이선스·정답 부여 절차·결측률을 적는 데이터 카드를 착수 전에 만든다.",
        "포함·제외 기준을 데이터를 보기 전에 문서로 확정하고 제외 건수를 보고하기로 한다.",
    ),
    RiskCode.R5: (
        "착수 첫날 의존성 잠금 파일·난수 시드·데이터 버전 해시를 저장소에 남기고 결과마다 함께 기록한다.",
        "코드·데이터 공개 가능 범위를 착수 전에 확인하고, 공개가 어려우면 대체 공개물(설정 세부·합성 샘플 등)을 계획서에 적는다.",
    ),
    RiskCode.R6: (
        "가장 가까운 선행연구 목록을 만들고 각 연구와 무엇이 다른지 한 줄씩 적어 기여 문장을 확정한다.",
        "문헌 탐색을 착수 시점과 실험 종료 시점에 한 번씩 하도록 일정에 넣는다.",
    ),
    RiskCode.R7: (
        "결론이 성립하는 범위와 성립하지 않을 조건을 계획서에 먼저 한 문단씩 쓴다.",
        "학습 분포 밖 검증 데이터를 확보하는 일정을 잡거나, 확보가 어려우면 주장을 내삽 범위로 좁혀 적는다.",
    ),
    RiskCode.R8: (
        "예측 결과에 도메인 제약(물리·화학적 타당성) 검사 단계를 착수 전에 설계에 넣는다.",
        "상위 후보 일부를 실험이나 기존 실험 문헌과 대조하는 검증 고리를 일정에 넣고, 어려우면 주장을 계산 결과로 한정한다.",
    ),
    RiskCode.R9: (
        "인용·재현 대상 선행연구의 철회·정정 여부를 착수 전에 조회해 대상에서 제외한다.",
        "원자료 보관·변경 이력·승인 절차(윤리 승인, 데이터 사용 허가)를 데이터 수집 전에 확정해 계획서에 적는다.",
    ),
}

CHECKLIST_INSTRUCTIONS = """너는 연구계획서의 착수 전 점검을 돕는다.
입력 JSON에는 계획서 줄 목록(plan_lines: no, text)과 위험카드 목록(cards)이 있다.
위험카드는 비슷한 연구가 실제 심사에서 받은 지적에서 나왔다. evidence는 그 카드의 근거 심사평 발췌(excerpt_id와 영어 원문)다.

카드마다 연구자가 연구를 시작하기 전에 할 수 있는 예방 행동을 1~3개 쓴다.
- action: 한국어 한 문장, "~한다"로 끝나는 행동. 이 계획서의 해당 줄 내용을 구체적으로 고치거나 보강하는 행동이어야 한다. 어느 계획서에나 붙는 일반론은 쓰지 않는다.
- verify: 그 행동을 했는지 확인할 수 있는 완료 조건 한 문장(한국어).
- plan_lines: 이 행동이 고치거나 보강하는 계획서 줄 번호. 입력 plan_lines에 있는 번호만 쓴다. 1개 이상.
- evidence_ids: 이 행동의 근거가 된 그 카드의 excerpt_id 1~3개. 다른 카드의 id는 쓰지 않는다.
  그 카드의 근거로 뒷받침할 수 없는 행동은 쓰지 않는다(근거 id가 없는 행동은 버려진다).

규칙
- 인용문을 쓰지 않는다. 심사평 원문 문장을 옮겨 적지 않는다. 근거는 excerpt_id로만 가리킨다.
- 계획서와 근거 어디에도 없는 사실(수치, 데이터셋·모델·기관 이름)을 계획서에 있는 것처럼 쓰지 않는다.
  다른 논문에만 나오는 대상을 이 계획의 평가 대상으로 끌어오지 않는다.
- 입력의 모든 card_id에 대해 정확히 한 번씩 답한다."""


# ── 공용 도우미(validate.py도 쓴다) ──────────────────────────────────────


def valid_plan_line_numbers(plan: PlanDocument) -> set[int]:
    """참조할 수 있는 계획서 줄 번호: 범위 안이고 빈 줄이 아닌 줄."""
    return {ln.no for ln in plan.lines if ln.text.strip()}


def split_plan_lines(lines: Iterable[Any], valid: set[int]) -> tuple[list[int], list[Any]]:
    """줄 번호 목록 → (남길 번호(순서 유지·중복 제거), 제거한 값). 정수가 아니거나 없는 줄은 제거."""
    kept: list[int] = []
    dropped: list[Any] = []
    for n in lines:
        if isinstance(n, bool) or not isinstance(n, int) or n not in valid:
            dropped.append(n)
        elif n not in kept:
            kept.append(n)
    return kept, dropped


def plan_lines_payload(plan: PlanDocument) -> list[dict[str, Any]]:
    """모델 입력용 계획서 줄(빈 줄은 뺀다, 번호는 원래 번호)."""
    return [{"no": ln.no, "text": ln.text} for ln in plan.lines if ln.text.strip()]


def evidence_payload(card: RiskCard, by_id: dict[str, Excerpt]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for ex_id in card.evidence:
        ex = by_id.get(ex_id)
        if ex is None:
            continue
        out.append({"excerpt_id": ex_id, "text": ex.text[:EVIDENCE_CHARS]})
        if len(out) >= MAX_EVIDENCE_PER_CARD:
            break
    return out


def batched(items: Sequence[Any], size: int) -> list[list[Any]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def call_llm(
    llm_call: LLMCall | None, schema: dict[str, Any], instructions: str, payload: dict[str, Any], *, effort: str
) -> tuple[dict[str, Any] | None, str | None]:
    """주입된 llm_call을 부른다. (응답, 실패 사유). 예외는 삼키고 사유로 바꾼다(비상 경로로 가게)."""
    if llm_call is None:
        return None, "llm_unavailable"
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        data = llm_call(schema, instructions, text, effort=effort)
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 그 묶음만 비상 경로로
        log.warning("llm_call 예외: %s", type(exc).__name__)
        return None, f"llm_exception:{type(exc).__name__}"
    if data is None:
        return None, "llm_failed"
    if not isinstance(data, dict):
        return None, "llm_invalid_response"
    return data, None


GENERATOR_LABELS = frozenset({"astra", "mock", "rule"})  # models.Generator 값


def llm_label(llm_call: LLMCall | None, generator: str | None, model: str | None) -> tuple[str, str | None]:
    """LLM 결과의 정직 표기. 명시 인자 > llm_call의 속성(generator, model). **추정하지 않는다**(SEC-1 S-05b).

    - llm_call이 없으면 LLM 결과가 생길 수 없다 → ("none", None). 결과는 모두 규칙 경로로 표기된다.
    - llm_call이 있는데 생성 주체를 알 수 없으면 ValueError(astra 기본값 금지).
    """
    if llm_call is None and generator is None:
        return "none", None
    gen = generator or getattr(llm_call, "generator", None)
    if not gen:
        raise ValueError("생성 주체를 알 수 없다: generator 인자나 llm_call.generator 속성을 넘긴다(기본값 추정 금지)")
    gen = str(getattr(gen, "value", gen))
    if gen not in GENERATOR_LABELS:
        raise ValueError(f"알 수 없는 생성 주체 {gen!r} (허용: {sorted(GENERATOR_LABELS)})")
    mdl = model if model is not None else getattr(llm_call, "model", None)
    return gen, mdl


def run_batches(fn: Callable[[list[Any]], Any], batches: list[list[Any]]) -> list[Any]:
    if len(batches) <= 1:
        return [fn(b) for b in batches]
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_CALLS, len(batches))) as pool:
        return list(pool.map(fn, batches))


def with_stage(result: PremortemResult, stage: StageStatus, **updates: Any) -> PremortemResult:
    """결과에 단계 기록을 더한 사본. 강등 단계가 있으면 status도 degraded로(ok로 숨기지 않는다)."""
    stages = [s for s in result.stages if s.stage != stage.stage] + [stage]
    status = result.status
    if status == "ok" and stage.state in ("degraded", "error"):
        status = "degraded"
    return result.model_copy(update={**updates, "stages": stages, "status": status})


# ── 스키마·입력 ──────────────────────────────────────────────────────────


def checklist_schema(card_ids: list[str], excerpt_ids: list[str]) -> dict[str, Any]:
    """OpenAI strict 모드에 맞춘 스키마(모든 객체 additionalProperties=false, 모든 속성 required).
    길이·개수 상한은 스키마가 아니라 코드가 검사한다."""
    evidence_item: dict[str, Any] = {"type": "string"}
    if excerpt_ids:
        evidence_item["enum"] = sorted(set(excerpt_ids))
    action = {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "verify", "plan_lines", "evidence_ids"],
        "properties": {
            "action": {"type": "string"},
            "verify": {"type": "string"},
            "plan_lines": {"type": "array", "items": {"type": "integer"}},
            "evidence_ids": {"type": "array", "items": evidence_item},
        },
    }
    card = {
        "type": "object",
        "additionalProperties": False,
        "required": ["card_id", "actions"],
        "properties": {
            "card_id": {"type": "string", "enum": list(card_ids)},
            "actions": {"type": "array", "items": action},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["cards"],
        "properties": {"cards": {"type": "array", "items": card}},
    }


def _card_payload(card: RiskCard, by_id: dict[str, Excerpt]) -> dict[str, Any]:
    code = RiskCode(card.risk_code)
    return {
        "card_id": card.card_id,
        "risk_code": code.value,
        "risk_name": f"{code.title_ko} ({code.title_en})",
        "title": card.title,
        "why": card.why_applies.text,
        "why_plan_lines": list(card.why_applies.plan_lines),
        "evidence": evidence_payload(card, by_id),
    }


# ── 응답 검사 ────────────────────────────────────────────────────────────


def _clean_text(value: Any, max_chars: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) > max_chars:
        return None
    return text


def _norm_key(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text).lower()


def _drop_record(card_id: Any, reason: str, detail: str, action: Any, evidence: Any, *, where: str) -> dict[str, Any]:
    """근거 게이트 폐기 기록 한 줄. 문구는 개인정보를 가리고 자른다(화면 항목으로는 내보내지 않는다)."""
    text = redact_pii(action if isinstance(action, str) else repr(action))
    ids = evidence if isinstance(evidence, list) else []
    return {
        "card_id": card_id if isinstance(card_id, str) else None,
        "reason": reason,
        "detail": detail,
        "action": text if len(text) <= DROPPED_TEXT_MAX else text[: DROPPED_TEXT_MAX - 1] + "…",
        "evidence_ids": [str(x)[:80] for x in ids[:6]],
        "where": where,
    }


def gate_checklist_items(
    items: Iterable[Any], result: PremortemResult, *, index: EvidenceIndex | None = None, where: str = "checklist"
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """체크리스트 항목 근거 게이트(E3-L1e). (남길 항목, 폐기 기록).

    항목마다 `gate.evidence_link_problem(evidence, [card_id])`: 근거 1개 이상, 전부 결과 evidence 안,
    연결 카드가 결과에 있고 근거가 전부 그 카드의 근거 안. 하나라도 어기면 항목을 **폐기**한다(고쳐 붙이지 않는다).
    체크리스트 생성 직후(build_checklist)와 2차 검증(validate.py)이 같이 쓴다.
    """
    index = index or EvidenceIndex(result)
    kept: list[dict[str, Any]] = []
    drops: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            drops.append(_drop_record(None, MALFORMED, "항목이 객체가 아니다", it, [], where=where))
            continue
        ev = it.get("evidence", it.get("evidence_ids"))
        reason, detail = evidence_link_problem(ev if isinstance(ev, list) else [], [it.get("card_id")], index)
        if reason is None:
            kept.append(it)
        else:
            rec = _drop_record(it.get("card_id"), reason, detail, it.get("action", ""), ev, where=where)
            if it.get("item_id"):
                rec["item_id"] = it["item_id"]
            drops.append(rec)
    return kept, drops


def evidence_audit(drops: list[dict[str, Any]], n_items: int) -> dict[str, Any]:
    """`result.verification["checklist_evidence"]`에 남기는 근거 게이트 기록."""
    reasons: dict[str, int] = {}
    for d in drops:
        reasons[d["reason"]] = reasons.get(d["reason"], 0) + 1
    return {
        "gate": EVIDENCE_GATE,
        "policy": "drop",  # 폐기(승계·재요청 없음)
        "items": n_items,
        "dropped": len(drops),
        "reasons": reasons,
        "dropped_detail": drops,
    }


def _clean_actions(
    raw_actions: Any, card: RiskCard, valid_lines: set[int], index: EvidenceIndex
) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    """모델이 돌려준 한 카드의 행동들을 검사한다. (남길 행동, 폐기 통계, 근거 게이트 폐기 기록)."""
    stats = {"actions_dropped": 0, "plan_lines_dropped": 0, "evidence_dropped": 0, "items_dropped_no_evidence": 0}
    gate_drops: list[dict[str, Any]] = []
    if not isinstance(raw_actions, list):
        return [], stats, gate_drops
    pool = set(card.evidence)
    card_lines, _ = split_plan_lines(card.why_applies.plan_lines, valid_lines)
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, raw in enumerate(raw_actions):
        if len(kept) >= MAX_ACTIONS_PER_CARD:
            stats["actions_dropped"] += len(raw_actions) - idx  # 카드당 최대 3개
            break
        if not isinstance(raw, dict):
            stats["actions_dropped"] += 1
            continue
        action = _clean_text(raw.get("action"), ACTION_MAX_CHARS)
        if action is None or len(action) < ACTION_MIN_CHARS or _norm_key(action) in seen:
            stats["actions_dropped"] += 1
            continue
        verify = _clean_text(raw.get("verify"), VERIFY_MAX_CHARS) or ""
        raw_lines = raw.get("plan_lines") if isinstance(raw.get("plan_lines"), list) else []
        lines, bad_lines = split_plan_lines(raw_lines, valid_lines)
        raw_ev = raw.get("evidence_ids") if isinstance(raw.get("evidence_ids"), list) else []
        evidence: list[str] = []
        bad_ev: list[Any] = []
        for ex_id in raw_ev:
            if isinstance(ex_id, str) and ex_id in pool:
                if ex_id not in evidence:
                    evidence.append(ex_id)
            else:
                bad_ev.append(ex_id)
        stats["plan_lines_dropped"] += len(bad_lines)
        stats["evidence_dropped"] += len(bad_ev)
        if not evidence:
            # 근거 게이트(E3-L1e): 근거 id가 없거나 전부 풀 밖이면 행동을 버린다(카드 근거 승계·재요청 없음).
            reason, detail = evidence_link_problem(raw_ev, [card.card_id], index)
            if reason is None:  # 풀 밖 id는 위에서 걸렀으므로 오지 않는다. 와도 근거 없음으로 친다
                reason, detail = MISSING_CITATION, "남은 근거 excerpt id가 없다"
            stats["items_dropped_no_evidence"] += 1
            gate_drops.append(_drop_record(card.card_id, reason, detail, action, raw_ev, where="checklist"))
            continue
        source = "llm"
        if not lines:
            # 행동이 가리킨 줄이 전부 없는 줄이면, 카드가 인용한 줄로 잇는다(표시해 둔다).
            lines, source = (card_lines, "card") if card_lines else ([], "none")
        seen.add(_norm_key(action))
        kept.append(
            {
                "action": action,
                "verify": verify,
                "plan_lines": lines,
                "plan_lines_source": source,
                "evidence": evidence,
                "dropped": {"plan_lines": bad_lines, "evidence": bad_ev},
            }
        )
    return kept, stats, gate_drops


def rule_actions(card: RiskCard, valid_lines: set[int]) -> list[dict[str, Any]]:
    """비상 규칙 경로: 카드 유형별 기본 문구. 줄은 카드가 인용한 줄(있는 것만)."""
    lines, bad = split_plan_lines(card.why_applies.plan_lines, valid_lines)
    phrases = RULE_ACTIONS.get(RiskCode(card.risk_code), RULE_ACTIONS[RiskCode.R1])
    return [
        {
            "action": text,
            "verify": "",
            "plan_lines": list(lines),
            "plan_lines_source": "card" if lines else "none",
            "evidence": list(card.evidence[:MAX_ACTIONS_PER_CARD]),
            "dropped": {"plan_lines": list(bad), "evidence": []},
        }
        for text in phrases
    ]


# ── 본체 ─────────────────────────────────────────────────────────────────


def _new_item(
    card: RiskCard, act: dict[str, Any], *, generator: str, model: str | None, fallback_reason: str | None
) -> dict[str, Any]:
    return {
        "item_id": "",  # 마지막에 C1, C2 … 로 채운다
        "card_id": card.card_id,
        "risk_code": RiskCode(card.risk_code).value,
        "subcode": card.subcode,
        **act,
        "generator": generator,
        "model": model if generator != "rule" else None,
        "fallback_reason": fallback_reason,
        "card_verdict": None,  # validate.py가 채운다(맞음·약함·틀림·미검증)
        "validation": None,
        "decision": None,  # 채택 · 보류 · 기각
        "note": "",  # 결정 메모(화면 '메모' 칸)
        "decided_at": None,
        "decision_log": [],
    }


def build_checklist(
    result: PremortemResult,
    plan: PlanDocument,
    llm_call: LLMCall | None,
    *,
    effort: str = DEFAULT_EFFORT,
    generator: str | None = None,
    model: str | None = None,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """카드마다 예방 행동 1~3개. 반환 항목은 `PremortemResult.checklist`에 그대로 넣는다.

    - `llm_call`이 None이거나 실패하면 그 묶음의 카드는 규칙 문구(`generator="rule"`)로 대신한다.
    - `generator`·`model`: LLM 결과의 표기. 인자가 없으면 `llm_call.generator`·`.model` 속성을 쓴다.
      둘 다 없으면 ValueError(기본값으로 astra라고 쓰지 않는다). provider에서는 `llm.generator_for(name)`을 넘긴다.
    - `stats`: 넘기면 호출·폐기 통계를 채운다(단계 기록용). 근거 게이트 폐기 수는 `items_dropped_no_evidence`,
      폐기 기록은 `evidence_drops`.
    - 반환 항목은 모두 근거가 1개 이상이고 그 카드의 근거 안에 있다(근거 게이트, E3-L1e).
    """
    gen, mdl = llm_label(llm_call, generator, model)
    cards = list(result.risk_cards)
    by_id = {ex.excerpt_id: ex for ex in result.evidence}
    index = EvidenceIndex(result)
    valid_lines = valid_plan_line_numbers(plan)
    plan_payload = plan_lines_payload(plan)
    st: dict[str, Any] = {
        "cards": len(cards),
        "calls": 0,
        "calls_failed": 0,
        "actions_dropped": 0,
        "plan_lines_dropped": 0,
        "evidence_dropped": 0,
        "items_dropped_no_evidence": 0,
        "cards_rule": 0,
        "failures": [],
        "evidence_drops": [],
    }

    Row = tuple[RiskCard, list[dict[str, Any]], str | None, dict[str, int], list[dict[str, Any]]]

    def run(batch: list[RiskCard]) -> tuple[list[Row], str | None]:
        """묶음 하나 → (카드별 결과, 호출 실패 사유)."""
        payload = {"plan_lines": plan_payload, "cards": [_card_payload(c, by_id) for c in batch]}
        schema = checklist_schema([c.card_id for c in batch], [x for c in batch for x in c.evidence if x in by_id])
        data, fail = call_llm(llm_call, schema, CHECKLIST_INSTRUCTIONS, payload, effort=effort)
        answers: dict[str, Any] = {}
        if data is not None:
            raw_cards = data.get("cards")
            if not isinstance(raw_cards, list):
                fail = "llm_invalid_response"
            else:
                for rc in raw_cards:
                    if isinstance(rc, dict) and isinstance(rc.get("card_id"), str) and rc["card_id"] not in answers:
                        answers[rc["card_id"]] = rc.get("actions")
        rows: list[Row] = []
        for card in batch:
            if fail is not None:
                rows.append((card, [], fail, {}, []))
            elif card.card_id not in answers:  # 입력에 없는 card_id는 answers에 있어도 쓰이지 않는다
                rows.append((card, [], "llm_missing_card", {}, []))
            else:
                acts, s, drops = _clean_actions(answers[card.card_id], card, valid_lines, index)
                # 행동이 전부 빠졌는데 근거 없음 때문이면 사유를 따로 적는다(규칙 경로로 대신한 이유)
                why = None if acts else ("llm_no_grounded_action" if drops else "llm_no_valid_action")
                rows.append((card, acts, why, s, drops))
        return rows, fail

    batches = batched(cards, CARDS_PER_CALL)
    outcomes = run_batches(run, batches)
    st["calls"] = len(batches) if llm_call is not None else 0
    st["calls_failed"] = sum(1 for _, fail in outcomes if fail is not None and llm_call is not None)

    items: list[dict[str, Any]] = []
    for card, acts, reason, s, drops in (row for rows, _ in outcomes for row in rows):
        for k, v in s.items():
            st[k] += v
        st["evidence_drops"].extend(drops)
        if reason is None:
            items.extend(_new_item(card, a, generator=gen, model=mdl, fallback_reason=None) for a in acts)
            continue
        st["cards_rule"] += 1
        st["failures"].append({"card_id": card.card_id, "reason": reason})
        items.extend(
            _new_item(card, a, generator="rule", model=None, fallback_reason=reason)
            for a in rule_actions(card, valid_lines)
        )
    # 마지막 근거 게이트: 규칙 항목까지 모든 항목을 같은 검사로 거른다(번호는 거른 뒤에 매긴다)
    items, final_drops = gate_checklist_items(items, result, index=index, where="checklist_final")
    st["items_dropped_no_evidence"] += len(final_drops)
    st["evidence_drops"].extend(final_drops)
    for i, item in enumerate(items, start=1):
        item["item_id"] = f"C{i}"
    if stats is not None:
        stats.update(st)
    return items


def checklist_stage(items: list[dict[str, Any]], stats: dict[str, Any], *, elapsed_s: float = 0.0) -> StageStatus:
    """체크리스트 단계 기록. 규칙으로 대신한 카드가 있으면 degraded(사유 포함)."""
    n_cards = int(stats.get("cards", 0))
    counts = {
        "cards": n_cards,
        "items": len(items),
        "items_llm": sum(1 for it in items if it["generator"] != "rule"),
        "items_rule": sum(1 for it in items if it["generator"] == "rule"),
        "cards_rule": int(stats.get("cards_rule", 0)),
        "calls": int(stats.get("calls", 0)),
        "calls_failed": int(stats.get("calls_failed", 0)),
        "plan_lines_dropped": int(stats.get("plan_lines_dropped", 0)),
        "evidence_dropped": int(stats.get("evidence_dropped", 0)),
        "actions_dropped": int(stats.get("actions_dropped", 0)),
        "items_dropped_no_evidence": int(stats.get("items_dropped_no_evidence", 0)),
    }
    if n_cards == 0:
        state, detail, impl = "skipped", "카드 0장 — 체크리스트 없음", IMPL
    elif counts["cards_rule"] == 0:
        state, detail, impl = "ok", None, IMPL
    else:
        reasons = sorted({f["reason"] for f in stats.get("failures", [])})
        state = "degraded"
        detail = f"카드 {counts['cards_rule']}/{n_cards}장 규칙 문구로 대신함: {', '.join(reasons)}"
        impl = IMPL if counts["items_llm"] else "fallback:rule_actions"
    if counts["items_dropped_no_evidence"]:
        # 근거 게이트 폐기는 강등이 아니다(심사평 게이트와 같게 ok 유지). 수는 counts와 detail에 남긴다.
        note = f"근거 없는 항목 {counts['items_dropped_no_evidence']}개 제외"
        detail = f"{detail} · {note}" if detail else note
    return StageStatus(
        stage="checklist", state=state, detail=detail, phase="analyze", impl=impl,
        elapsed_s=round(elapsed_s, 3), counts=counts,
    )


def attach_checklist(
    result: PremortemResult,
    plan: PlanDocument,
    llm_call: LLMCall | None,
    **kwargs: Any,
) -> PremortemResult:
    """파이프라인 연결용: 체크리스트를 만들어 `result.checklist`에 넣고 `checklist` 단계를 기록한 사본."""
    t0 = time.perf_counter()
    stats: dict[str, Any] = {}
    items = build_checklist(result, plan, llm_call, stats=stats, **kwargs)
    stage = checklist_stage(items, stats, elapsed_s=time.perf_counter() - t0)
    verification = {**result.verification, "checklist_evidence": evidence_audit(stats.get("evidence_drops", []), len(items))}
    return with_stage(result, stage, checklist=items, verification=verification)


# ── 결정 로그 ────────────────────────────────────────────────────────────


def record_decision(
    items: list[dict[str, Any]],
    item_id: str,
    decision: str | None,
    *,
    note: str = "",
    at: datetime | None = None,
) -> dict[str, Any]:
    """항목 하나의 결정을 기록한다(채택·보류·기각, None이면 미결정으로 되돌림). 이력은 decision_log에 쌓인다."""
    if decision is not None and decision not in DECISION_STATES:
        raise ValueError(f"결정은 {DECISION_STATES} 중 하나다: {decision!r}")
    item = next((it for it in items if it.get("item_id") == item_id), None)
    if item is None:
        raise KeyError(f"체크리스트에 없는 항목: {item_id}")
    when = (at or datetime.now(UTC)).isoformat()
    item["decision"] = decision
    item["note"] = note
    item["decided_at"] = when if decision is not None else None
    item.setdefault("decision_log", []).append({"decision": decision, "note": note, "at": when})
    return item


def decision_log(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """내보내기(decision_log.json)용 평면 목록."""
    return [
        {
            "item_id": it["item_id"],
            "card_id": it["card_id"],
            "risk_code": it["risk_code"],
            "action": it["action"],
            "plan_lines": list(it["plan_lines"]),
            "generator": it["generator"],
            "decision": it.get("decision"),
            "note": it.get("note", ""),
            "decided_at": it.get("decided_at"),
            "history": list(it.get("decision_log", [])),
        }
        for it in items
    ]


def decision_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """결정이 기록된 항목만, 내보내기 API(`neumann.api.export.DecisionEntry`) 모양으로."""
    return [
        {
            "item_id": it["item_id"],
            "card_id": it["card_id"],
            "decision": it["decision"],
            "note": it.get("note") or None,
            "decided_at": it.get("decided_at"),
        }
        for it in items
        if it.get("decision") in DECISION_STATES
    ]


__all__ = [
    "CHECKLIST_INSTRUCTIONS",
    "DECISION_STATES",
    "EVIDENCE_GATE",
    "RULE_ACTIONS",
    "attach_checklist",
    "build_checklist",
    "checklist_schema",
    "checklist_stage",
    "decision_entries",
    "decision_log",
    "evidence_audit",
    "gate_checklist_items",
    "record_decision",
    "rule_actions",
]
