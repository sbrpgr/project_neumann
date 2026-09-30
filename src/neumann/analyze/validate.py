"""2차 의미검증(GEN-2) — 카드의 "이 계획서에 해당하는 이유"가 인용한 계획서 줄과 실제로 맞는지 astra로 판정한다 (E3-L1b).

판정은 카드와 행동을 **따로** 한다.
- 카드: 해당 이유(why_applies.text) ↔ 인용한 계획서 줄. `match`(맞음) · `weak`(약함) · `mismatch`(틀림).
- 행동(체크리스트 항목): 연결된 계획서 줄에 실제로 적용되는 착수 전 행동인가. 같은 세 등급.
  카드가 틀림이어도 행동 판정은 카드 판정에 끌려가지 않는다. 틀림 카드의 행동도 지우지 않는다.

틀림은 **삭제하지 않고 강등 표시**한다: `result.verification["semantic"]`에 카드별 판정과 `demoted_cards`,
체크리스트 항목에는 `card_verdict`와 `validation`, `notices`에 한 줄, 단계 기록 `semantic_validate`.

규칙 층(코드): 카드가 인용한 줄이 하나도 없거나 전부 없는 줄이면 LLM 판정과 무관하게 `weak`가 상한이다
(인용 줄로 뒷받침할 수 없으므로 '맞음'일 수 없다). 이 부분은 `judge="rule"`로 표기한다.

실패(None·예외·모양 오류)면 그 묶음 카드·행동은 `unverified`(미검증)로 남기고 단계는 degraded다.
의미 판정을 규칙으로 흉내 내지 않는다.

근거 게이트(E3-L1e): 판정 전에 체크리스트 항목을 체크리스트 생성 직후와 **같은 검사**
(`checklist.gate_checklist_items` → `gate.evidence_link_problem`)로 다시 거른다. 근거가 없거나 연결 카드의
근거 밖을 가리키는 항목은 모델에 보내지 않고, `apply_validation`이 체크리스트에서 **뺀다**(틀림 강등과 달리
근거 없는 문장은 내보내지 않는다). 수는 `counts["actions_no_evidence"]`와 `evidence_gate`에 남고 단계는 degraded다
(정상 흐름이면 생성 직후 게이트가 이미 거르므로 0이다 — 0이 아니면 앞 단계를 우회한 항목이 있다는 뜻이다).
"""

from __future__ import annotations

import re
import time
from typing import Any

from neumann.analyze.checklist import (
    CARDS_PER_CALL,
    LLMCall,
    batched,
    call_llm,
    evidence_audit,
    evidence_payload,
    gate_checklist_items,
    llm_label,
    plan_lines_payload,
    run_batches,
    split_plan_lines,
    valid_plan_line_numbers,
    with_stage,
)
from neumann.models import PlanDocument, PremortemResult, RiskCard, RiskCode, StageStatus

VERDICTS: tuple[str, ...] = ("match", "weak", "mismatch")
UNVERIFIED = "unverified"
VERDICT_KO: dict[str, str] = {"match": "맞음", "weak": "약함", "mismatch": "틀림", UNVERIFIED: "미검증"}
_RANK = {"match": 0, "weak": 1, "mismatch": 2}
REASON_MAX_CHARS = 300
DEFAULT_EFFORT = "medium"
STAGE = "semantic_validate"
IMPL = "neumann.analyze.validate:validate_cards"

VALIDATE_INSTRUCTIONS = """너는 연구계획서 위험카드의 2차 검증자다.
입력 JSON에는 계획서 줄 목록(plan_lines)과 카드 목록(cards)이 있다. 카드마다
- why: 이 위험이 이 계획서에 해당하는 이유
- cited_lines: why가 근거로 인용한 계획서 줄(번호와 원문)
- evidence: 비슷한 연구의 실제 심사평 발췌(영어)
- actions: 그 카드에 딸린 착수 전 예방 행동(item_id, 문구, 연결된 계획서 줄)
이 있다.

1) 카드 판정(verdict) — 인용된 계획서 줄이 why의 내용을 실제로 뒷받침하는가:
- match: 인용된 줄이 why가 말하는 사실을 그대로 담고 있다.
- weak: 부분적으로만 맞거나, 줄이 간접적으로만 관련되거나, 인용된 줄이 없다.
- mismatch: 인용된 줄이 why와 다른 내용이거나 반대다. 또는 계획서가 이미 그 위험을 명시적으로 막고 있다.
계획서 전체를 읽고 판단하되, 판정의 근거는 인용된 줄이다.

2) 행동 판정(actions) — 카드 판정과 독립으로 매긴다:
- match: 연결된 계획서 줄에 실제로 적용되는 구체적인 착수 전 행동이다.
- weak: 막연하거나 일부만 관련된다.
- mismatch: 이 계획서와 무관하거나 계획서 내용과 모순된다.
카드가 mismatch여도 행동이 타당하면 match를 준다.

reason은 한국어 한 문장이다. 인용부호로 원문을 옮겨 적지 않는다.
입력의 모든 card_id와 item_id에 정확히 한 번씩 답한다."""


def validation_schema(card_ids: list[str], item_ids: list[str]) -> dict[str, Any]:
    """OpenAI strict 모드에 맞춘 스키마. 판정은 enum, 길이 상한은 코드가 검사한다."""
    item_id: dict[str, Any] = {"type": "string"}
    if item_ids:
        item_id["enum"] = list(item_ids)
    verdict = {"type": "string", "enum": list(VERDICTS)}
    action = {
        "type": "object",
        "additionalProperties": False,
        "required": ["item_id", "verdict", "reason"],
        "properties": {"item_id": item_id, "verdict": verdict, "reason": {"type": "string"}},
    }
    card = {
        "type": "object",
        "additionalProperties": False,
        "required": ["card_id", "verdict", "reason", "actions"],
        "properties": {
            "card_id": {"type": "string", "enum": list(card_ids)},
            "verdict": verdict,
            "reason": {"type": "string"},
            "actions": {"type": "array", "items": action},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["cards"],
        "properties": {"cards": {"type": "array", "items": card}},
    }


def _reason(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    return text if len(text) <= REASON_MAX_CHARS else text[: REASON_MAX_CHARS - 1] + "…"


def _card_entry(card_id: str, verdict: str, reason: str, judge: str, cited: list[int], dropped: list[Any]) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "verdict": verdict,
        "verdict_ko": VERDICT_KO[verdict],
        "reason": reason,
        "judge": judge,
        "cited_lines": cited,
        "dropped_lines": dropped,
        "demoted": verdict == "mismatch",
    }


def _action_entry(item: dict[str, Any], verdict: str, reason: str, judge: str) -> dict[str, Any]:
    return {
        "item_id": item["item_id"],
        "card_id": item["card_id"],
        "verdict": verdict,
        "verdict_ko": VERDICT_KO[verdict],
        "reason": reason,
        "judge": judge,
        "demoted": verdict == "mismatch",
    }


def validate_cards(
    result: PremortemResult,
    plan: PlanDocument,
    llm_call: LLMCall | None,
    *,
    checklist: list[dict[str, Any]] | None = None,
    effort: str = DEFAULT_EFFORT,
    generator: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """카드·행동 2차 의미검증 보고서를 만든다. 결과 객체는 바꾸지 않는다(`apply_validation`이 붙인다).

    checklist를 안 주면 `result.checklist`를 쓴다.
    """
    gen, mdl = llm_label(llm_call, generator, model)
    raw_items = list(result.checklist if checklist is None else checklist)
    # 근거 게이트: 근거 없는 항목은 판정하지 않고 빼낼 목록에 올린다(apply_validation이 뺀다)
    items, gate_drops = gate_checklist_items(raw_items, result, where="semantic_validate")
    cards = list(result.risk_cards)
    by_ex = {ex.excerpt_id: ex for ex in result.evidence}
    valid = valid_plan_line_numbers(plan)
    plan_payload = plan_lines_payload(plan)
    items_by_card: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        if isinstance(it, dict) and it.get("item_id") and it.get("card_id"):
            items_by_card.setdefault(it["card_id"], []).append(it)

    def lines_with_text(nums: list[Any]) -> list[dict[str, Any]]:
        kept, _ = split_plan_lines(nums, valid)
        return [{"no": n, "text": plan.line(n)} for n in kept]

    def payload_for(card: RiskCard) -> dict[str, Any]:
        code = RiskCode(card.risk_code)
        return {
            "card_id": card.card_id,
            "risk_code": code.value,
            "risk_name": f"{code.title_ko} ({code.title_en})",
            "title": card.title,
            "why": card.why_applies.text,
            "cited_lines": lines_with_text(card.why_applies.plan_lines),
            "evidence": evidence_payload(card, by_ex),
            "actions": [
                {"item_id": it["item_id"], "action": it.get("action", ""), "plan_lines": lines_with_text(it.get("plan_lines", []))}
                for it in items_by_card.get(card.card_id, [])
            ],
        }

    def run(batch: list[RiskCard]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        item_ids = [it["item_id"] for c in batch for it in items_by_card.get(c.card_id, [])]
        schema = validation_schema([c.card_id for c in batch], item_ids)
        payload = {"plan_lines": plan_payload, "cards": [payload_for(c) for c in batch]}
        data, fail = call_llm(llm_call, schema, VALIDATE_INSTRUCTIONS, payload, effort=effort)
        answers: dict[str, dict[str, Any]] = {}
        if data is not None:
            raw_cards = data.get("cards")
            if not isinstance(raw_cards, list):
                fail = "llm_invalid_response"
            else:
                for rc in raw_cards:
                    if isinstance(rc, dict) and isinstance(rc.get("card_id"), str) and rc["card_id"] not in answers:
                        answers[rc["card_id"]] = rc
        card_rows: list[dict[str, Any]] = []
        action_rows: list[dict[str, Any]] = []
        for card in batch:
            cited, dropped = split_plan_lines(card.why_applies.plan_lines, valid)
            no_lines = not cited
            rule_note = "해당 이유가 인용한 계획서 줄이 없다" + (f"(없는 줄 {dropped} 제거)" if dropped else "")
            ans = answers.get(card.card_id) if fail is None else None
            v = ans.get("verdict") if ans else None
            if v in VERDICTS:
                reason = _reason(ans.get("reason"))
                judge = gen
                if no_lines and _RANK[v] < _RANK["weak"]:
                    v, judge, reason = "weak", "rule", f"{rule_note} — 상한 약함(모델 판정 {VERDICT_KO[ans['verdict']]})"
                card_rows.append(_card_entry(card.card_id, v, reason, judge, cited, dropped))
            elif no_lines:
                card_rows.append(_card_entry(card.card_id, "weak", rule_note, "rule", cited, dropped))
            else:
                why = fail or ("llm_missing_card" if ans is None else "llm_invalid_verdict")
                card_rows.append(_card_entry(card.card_id, UNVERIFIED, why, "none", cited, dropped))
            # 행동: 이 카드에 딸린 항목만 받는다(다른 카드의 item_id는 무시)
            mine = {it["item_id"]: it for it in items_by_card.get(card.card_id, [])}
            got: dict[str, dict[str, Any]] = {}
            raw_actions = ans.get("actions") if ans else None
            for ra in raw_actions if isinstance(raw_actions, list) else []:
                if isinstance(ra, dict) and ra.get("item_id") in mine and ra["item_id"] not in got:
                    got[ra["item_id"]] = ra
            for item_id, it in mine.items():
                ra = got.get(item_id)
                if ra is not None and ra.get("verdict") in VERDICTS:
                    action_rows.append(_action_entry(it, ra["verdict"], _reason(ra.get("reason")), gen))
                else:
                    why = fail or ("llm_missing_action" if ra is None else "llm_invalid_verdict")
                    action_rows.append(_action_entry(it, UNVERIFIED, why, "none"))
        return card_rows, action_rows, fail

    outcomes = run_batches(run, batched(cards, CARDS_PER_CALL))
    card_rows = [r for c, _, _ in outcomes for r in c]
    action_rows = [r for _, a, _ in outcomes for r in a]
    fails = sorted({f for _, _, f in outcomes if f is not None})

    counts = {f"cards_{v}": sum(1 for r in card_rows if r["verdict"] == v) for v in (*VERDICTS, UNVERIFIED)}
    counts.update({f"actions_{v}": sum(1 for r in action_rows if r["verdict"] == v) for v in (*VERDICTS, UNVERIFIED)})
    counts["calls"] = len(outcomes) if llm_call is not None else 0
    counts["calls_failed"] = sum(1 for *_, f in outcomes if f is not None) if llm_call is not None else 0

    if not cards:
        status, reason = "skipped", "카드 0장 — 검증 대상 없음"
    elif fails:
        status, reason = "degraded", f"미검증 {counts['cards_unverified']}장: {', '.join(fails)}"
    elif counts["cards_unverified"] or counts["actions_unverified"]:
        status, reason = "degraded", "모델 응답에서 빠진 카드·행동이 있어 미검증으로 남김"
    else:
        status, reason = "ok", None

    # 설정 라벨은 요청 대상이다. 외피 출처는 최종 판정의 실제 judge로 정한다.
    # verification은 확장 가능한 dict 계약이므로 mixed는 카드 Generator enum을 바꾸지 않는다.
    judges: dict[str, int] = {}
    for row in [*card_rows, *action_rows]:
        judges[row["judge"]] = judges.get(row["judge"], 0) + 1
    generated = sum(judges.get(g, 0) for g in ("astra", "mock"))
    actual_gen = (gen if len(judges) == 1 else "mixed") if generated else "rule"

    report = {
        "method": "semantic_v1",
        "generator": actual_gen,
        "generators": judges,
        "model": mdl if generated else None,
        "effort": effort,
        "status": status,
        "reason": reason,
        "cards": card_rows,
        "actions": action_rows,
        "demoted_cards": [r["card_id"] for r in card_rows if r["demoted"]],
        "demoted_actions": [r["item_id"] for r in action_rows if r["demoted"]],
        "counts": counts,
    }
    return _with_gate(report, gate_drops, len(items))


def _with_gate(report: dict[str, Any], drops: list[dict[str, Any]], n_kept: int) -> dict[str, Any]:
    """보고서에 근거 게이트 기록을 넣은 사본. 폐기가 있으면 degraded와 사유 한 줄(skipped는 그대로)."""
    out = {**report, "counts": {**report["counts"], "actions_no_evidence": len(drops)}}
    out["evidence_gate"] = evidence_audit(drops, n_kept)
    out["dropped_actions"] = [d["item_id"] for d in drops if d.get("item_id")]
    if drops:
        note = f"근거 없는 체크리스트 항목 {len(drops)}개 제외(2차 검증 근거 게이트)"
        if out["status"] != "skipped":
            out["status"] = "degraded"
        out["reason"] = f"{out['reason']}; {note}" if out.get("reason") else note
    return out


def validation_stage(report: dict[str, Any], *, elapsed_s: float = 0.0) -> StageStatus:
    state = report["status"]
    impl = IMPL if report["counts"].get("calls", 0) else "fallback:unverified"
    return StageStatus(
        stage=STAGE, state=state, detail=report.get("reason"), phase="analyze", impl=impl,
        elapsed_s=round(elapsed_s, 3), counts={k: int(v) for k, v in report["counts"].items()},
    )


def apply_validation(result: PremortemResult, report: dict[str, Any], *, elapsed_s: float = 0.0) -> PremortemResult:
    """보고서를 결과에 붙인 사본. 카드·행동은 지우지 않고 판정과 강등 표시만 더한다.
    예외는 근거 게이트(E3-L1e)다: 근거가 없거나 연결 카드의 근거 밖을 가리키는 체크리스트 항목은 뺀다."""
    card_v = {r["card_id"]: r for r in report["cards"]}
    act_v = {r["item_id"]: r for r in report["actions"]}
    # 근거 게이트: 내보낼 체크리스트(result.checklist)를 같은 검사로 다시 거른다. 보고서와 수가 다르면
    # (보고서를 다른 체크리스트로 만들었으면) 이 결과 기준으로 보고서의 게이트 기록을 고쳐 쓴다.
    kept_items, drops = gate_checklist_items(result.checklist, result, where="semantic_validate")
    if len(drops) != int(report["counts"].get("actions_no_evidence", 0)):
        report = _with_gate(report, drops, len(kept_items))
    checklist = []
    for it in kept_items:
        it = dict(it)
        cv = card_v.get(it.get("card_id"))
        if cv is not None:
            it["card_verdict"] = cv["verdict"]
        av = act_v.get(it.get("item_id"))
        if av is not None:
            it["validation"] = {k: av[k] for k in ("verdict", "verdict_ko", "reason", "judge", "demoted")}
        checklist.append(it)
    notices = list(result.notices)
    n_gate = int(report["counts"].get("actions_no_evidence", 0))
    if n_gate:
        ids = ", ".join(str(x) for x in report.get("dropped_actions", [])) or "-"
        notices.append(f"2차 검증: 근거 없는 체크리스트 항목 {n_gate}개 제외(근거 번호 없음·연결 카드의 근거 밖): {ids}")
    if report["demoted_cards"]:
        notices.append(
            f"2차 의미검증: 카드 {len(report['demoted_cards'])}장이 '틀림'(인용한 계획서 줄과 해당 이유가 맞지 않음) — "
            f"삭제하지 않고 강등 표시: {', '.join(report['demoted_cards'])}"
        )
    gate_only = bool(n_gate) and str(report.get("reason") or "").startswith("근거 없는 체크리스트 항목")
    if report["status"] == "degraded" and not gate_only:  # 게이트 폐기만이면 위 한 줄로 충분하다
        notices.append(f"2차 의미검증 일부 미검증(강등): {report['reason']}")
    if report["generator"] in ("rule", "mixed") and report["status"] != "skipped":
        labels = {"astra": "LLM", "mock": "모의(mock)", "rule": "비상 규칙", "none": "미검증"}
        parts = " · ".join(f"{labels.get(g, g)} {n}건" for g, n in report.get("generators", {}).items())
        origin = "혼합" if report["generator"] == "mixed" else "비상 규칙"
        notices.append(f"2차 의미검증 출처: {origin}({parts}).")
    verification = {**result.verification, "semantic": report}
    stage = validation_stage(report, elapsed_s=elapsed_s)
    return with_stage(result, stage, checklist=checklist, notices=notices, verification=verification)


def attach_validation(
    result: PremortemResult,
    plan: PlanDocument,
    llm_call: LLMCall | None,
    **kwargs: Any,
) -> PremortemResult:
    """파이프라인 연결용: 검증 보고서를 만들어 붙인 사본(체크리스트를 먼저 붙인 뒤 부르면 행동도 판정한다)."""
    t0 = time.perf_counter()
    report = validate_cards(result, plan, llm_call, **kwargs)
    return apply_validation(result, report, elapsed_s=time.perf_counter() - t0)


def card_verdicts(result: PremortemResult) -> dict[str, str]:
    """card_id → 판정(match·weak·mismatch·unverified). 검증 전이면 빈 딕셔너리."""
    report = result.verification.get("semantic") or {}
    return {r["card_id"]: r["verdict"] for r in report.get("cards", [])}


__all__ = [
    "UNVERIFIED",
    "VALIDATE_INSTRUCTIONS",
    "VERDICTS",
    "VERDICT_KO",
    "apply_validation",
    "attach_validation",
    "card_verdicts",
    "validate_cards",
    "validation_schema",
    "validation_stage",
]
