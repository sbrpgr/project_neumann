"""E3-L1b 체크리스트: 가짜 llm_call로 검사한다(실제 API 없음).

완료 기준 1: 없는 줄 번호 참조 제거 · 실패 시 규칙 표기. (카드 기각 시 행동 유지는 test_validate_semantic.py)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from neumann.analyze.checklist import (
    DECISION_STATES,
    RULE_ACTIONS,
    attach_checklist,
    build_checklist,
    checklist_schema,
    decision_entries,
    decision_log,
    record_decision,
)
from neumann.models import PremortemResult, RiskCode
from tests.fixtures.loader import load_fixtures

ROOT = Path(__file__).resolve().parents[2]
LEAK, SEED = "card-fx-leak", "card-fx-seed"


class FakeLLM:
    """주입용 가짜 llm_call. respond(payload) → dict | None, 또는 raise_exc를 던진다."""

    # 생성 주체는 추정하지 않는다(SEC-1 S-05b): 이 가짜는 astra 응답을 흉내 낸다고 속성으로 명시한다.
    generator = "astra"
    model = "gpt-6-astra"

    def __init__(self, respond: Any = None, *, raise_exc: Exception | None = None) -> None:
        self.respond = respond
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    def __call__(self, schema: dict, instructions: str, input: str, *, effort: str) -> dict | None:
        payload = json.loads(input)
        self.calls.append({"schema": schema, "instructions": instructions, "payload": payload, "effort": effort})
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.respond(payload) if callable(self.respond) else self.respond


def _result() -> PremortemResult:
    return load_fixtures().premortem_result


def _plan():
    res = _result()
    assert res.plan is not None
    return res.plan


def _good(payload: dict) -> dict:
    """카드마다 유효한 행동 2개(카드 자기 근거·실재 줄)."""
    out = []
    for c in payload["cards"]:
        ev = [e["excerpt_id"] for e in c["evidence"]]
        lines = c["why_plan_lines"]
        out.append(
            {
                "card_id": c["card_id"],
                "actions": [
                    {"action": f"{c['card_id']} 첫 행동을 계획서에 적는다.", "verify": "계획서에 적혀 있다.",
                     "plan_lines": lines, "evidence_ids": ev[:2]},
                    {"action": f"{c['card_id']} 두 번째 행동을 실험 전에 한다.", "verify": "",
                     "plan_lines": lines[:1], "evidence_ids": []},
                ],
            }
        )
    return {"cards": out}


def _strict_problems(schema: dict, path: str = "$") -> list[str]:
    """OpenAI strict 모드 요건: 객체는 additionalProperties=false, 속성 전부 required."""
    probs: list[str] = []
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            probs.append(f"{path}: additionalProperties")
        if sorted(schema.get("required", [])) != sorted(props):
            probs.append(f"{path}: required")
        for k, v in props.items():
            probs += _strict_problems(v, f"{path}.{k}")
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        probs += _strict_problems(schema["items"], f"{path}[]")
    return probs


# ── LLM 경로 ─────────────────────────────────────────────────────────────


def test_llm_path_links_actions_to_plan_lines_and_card_evidence() -> None:
    res, plan = _result(), _plan()
    llm = FakeLLM(_good)
    items = build_checklist(res, plan, llm)

    assert len(llm.calls) == 1  # 카드 2장 → 한 묶음
    assert [it["item_id"] for it in items] == ["C1", "C2", "C3", "C4"]
    assert {it["card_id"] for it in items} == {LEAK, SEED}
    for it in items:
        assert it["generator"] == "astra" and it["model"] == "gpt-6-astra" and it["fallback_reason"] is None
        assert it["plan_lines"] and all(plan.line(n).strip() for n in it["plan_lines"])
        card = next(c for c in res.risk_cards if c.card_id == it["card_id"])
        assert set(it["evidence"]) <= set(card.evidence)
        assert it["decision"] is None and it["decision_log"] == []
        assert "quote" not in json.dumps(it)  # 인용문 필드 없음
    assert items[0]["plan_lines"] == [16, 17] and items[0]["plan_lines_source"] == "llm"


def test_payload_and_schema_carry_ids_not_quotes() -> None:
    res, plan = _result(), _plan()
    llm = FakeLLM(_good)
    build_checklist(res, plan, llm, effort="high")
    call = llm.calls[0]
    assert call["effort"] == "high"
    assert [c["card_id"] for c in call["payload"]["cards"]] == [LEAK, SEED]
    assert all(pl["text"].strip() for pl in call["payload"]["plan_lines"])  # 빈 줄은 보내지 않는다
    assert {pl["no"] for pl in call["payload"]["plan_lines"]} >= {16, 17, 22}
    schema = call["schema"]
    assert _strict_problems(schema) == []
    action_props = schema["properties"]["cards"]["items"]["properties"]["actions"]["items"]["properties"]
    assert set(action_props) == {"action", "verify", "plan_lines", "evidence_ids"}
    assert schema["properties"]["cards"]["items"]["properties"]["card_id"]["enum"] == [LEAK, SEED]
    jsonschema.validate(_good(call["payload"]), schema)


def test_nonexistent_plan_lines_are_removed_and_recorded() -> None:
    res, plan = _result(), _plan()
    n = len(plan.lines)

    def respond(payload: dict) -> dict:
        return {
            "cards": [
                {"card_id": LEAK, "actions": [
                    # 16만 실재. 99·n+1(범위 밖), 0·-3(1 미만), 2(빈 줄), "17"(정수 아님), true(불리언) 제거
                    {"action": "그룹 분할 규칙을 문서로 고정한다.", "verify": "문서가 있다.",
                     "plan_lines": [16, 99, n + 1, 0, -3, 2, "17", True, 16], "evidence_ids": []},
                    # 줄이 전부 없는 줄 → 카드가 인용한 줄(16, 17)로 잇고 표시
                    {"action": "근사중복 제거 기준을 정한다.", "verify": "", "plan_lines": [500], "evidence_ids": []},
                ]},
                {"card_id": SEED, "actions": [
                    {"action": "시드 반복 횟수를 정한다.", "verify": "", "plan_lines": [22], "evidence_ids": []},
                ]},
            ]
        }

    stats: dict = {}
    items = build_checklist(res, plan, FakeLLM(respond), stats=stats)
    first, second = items[0], items[1]
    assert first["plan_lines"] == [16]
    assert first["dropped"]["plan_lines"] == [99, n + 1, 0, -3, 2, "17", True]
    assert second["plan_lines"] == [16, 17] and second["plan_lines_source"] == "card"
    assert second["dropped"]["plan_lines"] == [500]
    assert stats["plan_lines_dropped"] == 8
    valid = {ln.no for ln in plan.lines if ln.text.strip()}
    assert all(set(it["plan_lines"]) <= valid for it in items)
    assert all(it["generator"] == "astra" for it in items)


def test_foreign_evidence_unknown_card_and_missing_card() -> None:
    res, plan = _result(), _plan()
    seed_ev = next(c for c in res.risk_cards if c.card_id == SEED).evidence

    def respond(payload: dict) -> dict:
        return {
            "cards": [
                {"card_id": "card-does-not-exist", "actions": [
                    {"action": "없는 카드의 행동이다.", "verify": "", "plan_lines": [16], "evidence_ids": []}]},
                {"card_id": LEAK, "actions": [
                    {"action": "분할 규칙을 문서로 고정한다.", "verify": "", "plan_lines": [16],
                     "evidence_ids": [seed_ev[0], "ex_made_up", "ex_c5986bb2facc61b2"]}]},
                # SEED 카드는 응답에서 빠졌다 → 그 카드만 규칙 경로
            ]
        }

    stats: dict = {}
    items = build_checklist(res, plan, FakeLLM(respond), stats=stats)
    assert all(it["card_id"] in (LEAK, SEED) for it in items)
    leak = [it for it in items if it["card_id"] == LEAK]
    assert len(leak) == 1 and leak[0]["evidence"] == ["ex_c5986bb2facc61b2"]
    assert leak[0]["dropped"]["evidence"] == [seed_ev[0], "ex_made_up"]
    seed = [it for it in items if it["card_id"] == SEED]
    assert seed and all(it["generator"] == "rule" and it["fallback_reason"] == "llm_missing_card" for it in seed)
    assert stats["cards_rule"] == 1 and stats["evidence_dropped"] == 2


def test_actions_capped_at_three_deduped_and_length_checked() -> None:
    res, plan = _result(), _plan()

    def respond(payload: dict) -> dict:
        acts = [
            {"action": "짧다", "verify": "", "plan_lines": [16], "evidence_ids": []},  # 5자 미만
            {"action": "가" * 400, "verify": "", "plan_lines": [16], "evidence_ids": []},  # 너무 김
            {"action": "행동 하나를 한다.", "verify": "", "plan_lines": [16], "evidence_ids": []},
            {"action": "행동  하나를 한다!", "verify": "", "plan_lines": [17], "evidence_ids": []},  # 중복
            {"action": "행동 둘을 한다.", "verify": "", "plan_lines": [16], "evidence_ids": []},
            {"action": "행동 셋을 한다.", "verify": "", "plan_lines": [16], "evidence_ids": []},
            {"action": "행동 넷을 한다.", "verify": "", "plan_lines": [16], "evidence_ids": []},
        ]
        return {"cards": [{"card_id": c["card_id"], "actions": acts} for c in payload["cards"]]}

    items = build_checklist(res, plan, FakeLLM(respond))
    leak = [it["action"] for it in items if it["card_id"] == LEAK]
    assert leak == ["행동 하나를 한다.", "행동 둘을 한다.", "행동 셋을 한다."]


# ── 비상 규칙 경로 ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("llm", "reason"),
    [
        (FakeLLM(None), "llm_failed"),
        (FakeLLM(raise_exc=TimeoutError("slow")), "llm_exception:TimeoutError"),
        (FakeLLM({"cards": "not-a-list"}), "llm_invalid_response"),
        (FakeLLM(["not", "a", "dict"]), "llm_invalid_response"),
        (None, "llm_unavailable"),
    ],
)
def test_failure_falls_back_to_rule_and_marks_generator(llm: Any, reason: str) -> None:
    res, plan = _result(), _plan()
    items = build_checklist(res, plan, llm)
    assert items, "실패해도 카드마다 규칙 행동이 나와야 한다"
    assert all(it["generator"] == "rule" and it["model"] is None and it["fallback_reason"] == reason for it in items)
    leak = [it for it in items if it["card_id"] == LEAK]
    assert [it["action"] for it in leak] == list(RULE_ACTIONS[RiskCode.R3])
    assert all(it["plan_lines"] == [16, 17] for it in leak)  # 카드가 인용한 줄에 연결
    seed = [it for it in items if it["card_id"] == SEED]
    assert [it["action"] for it in seed] == list(RULE_ACTIONS[RiskCode.R2])


def test_all_actions_invalid_falls_back_for_that_card_only() -> None:
    res, plan = _result(), _plan()

    def respond(payload: dict) -> dict:
        return {"cards": [
            {"card_id": LEAK, "actions": [{"action": 3, "verify": "", "plan_lines": [], "evidence_ids": []}]},
            {"card_id": SEED, "actions": [{"action": "시드 반복을 정한다.", "verify": "", "plan_lines": [22],
                                           "evidence_ids": []}]},
        ]}

    items = build_checklist(res, plan, FakeLLM(respond))
    assert {it["generator"] for it in items if it["card_id"] == LEAK} == {"rule"}
    assert {it["fallback_reason"] for it in items if it["card_id"] == LEAK} == {"llm_no_valid_action"}
    assert {it["generator"] for it in items if it["card_id"] == SEED} == {"astra"}


def test_rule_actions_exist_for_every_risk_code() -> None:
    assert set(RULE_ACTIONS) == set(RiskCode)
    assert all(1 <= len(v) <= 3 and all(len(t) >= 10 for t in v) for v in RULE_ACTIONS.values())


def test_generator_label_follows_injection() -> None:
    res, plan = _result(), _plan()
    items = build_checklist(res, plan, FakeLLM(_good), generator="mock", model="mock-deterministic-v1")
    assert {it["generator"] for it in items} == {"mock"} and {it["model"] for it in items} == {"mock-deterministic-v1"}

    llm = FakeLLM(_good)
    llm.generator, llm.model = "mock", "m1"  # llm_call 속성으로도 받는다
    assert {it["generator"] for it in build_checklist(res, plan, llm)} == {"mock"}


def test_generator_is_never_guessed() -> None:
    """SEC-1 S-05b: 생성 주체가 인자에도 llm_call 속성에도 없으면 astra로 추정하지 않고 ValueError."""
    import pytest

    from neumann.analyze.checklist import llm_label
    from neumann.analyze.validate import validate_cards

    res, plan = _result(), _plan()

    def bare(schema, instructions, input, *, effort):  # 속성 없는 llm_call
        return _good(json.loads(input))

    with pytest.raises(ValueError):
        build_checklist(res, plan, bare)
    with pytest.raises(ValueError):
        validate_cards(res, plan, bare)
    with pytest.raises(ValueError):
        llm_label(bare, "gpt-6-astra", None)  # 모델명은 생성 주체 값이 아니다
    # llm_call이 없으면 LLM 결과가 없다: 추정 없이 "none", 항목은 전부 규칙
    assert llm_label(None, None, None) == ("none", None)
    assert {it["generator"] for it in build_checklist(res, plan, None)} == {"rule"}
    # 명시하면 그대로(모델 기본값도 채우지 않는다)
    assert llm_label(bare, "astra", None) == ("astra", None)


# ── 결과·단계·결정 로그 ──────────────────────────────────────────────────


def _contract() -> dict:
    return json.loads((ROOT / "contracts" / "premortem_response.schema.json").read_text(encoding="utf-8"))


def test_attach_checklist_records_stage_and_keeps_contract() -> None:
    res, plan = _result(), _plan()
    ok = attach_checklist(res, plan, FakeLLM(_good))
    stage = next(s for s in ok.stages if s.stage == "checklist")
    assert stage.state == "ok" and stage.counts["items_llm"] == 4 and stage.counts["items_rule"] == 0
    assert ok.status == "ok" and len(ok.checklist) == 4
    jsonschema.validate(ok.model_dump(mode="json"), _contract())
    PremortemResult.model_validate(ok.model_dump(mode="json"))

    bad = attach_checklist(res, plan, FakeLLM(None))
    stage = next(s for s in bad.stages if s.stage == "checklist")
    assert stage.state == "degraded" and "llm_failed" in (stage.detail or "")
    assert stage.impl == "fallback:rule_actions" and stage.counts["cards_rule"] == 2
    assert bad.status == "degraded"  # 강등을 ok로 숨기지 않는다
    jsonschema.validate(bad.model_dump(mode="json"), _contract())


def test_zero_cards_gives_empty_checklist_and_skipped_stage() -> None:
    res, plan = _result(), _plan()
    empty = res.model_copy(update={"risk_cards": []})
    llm = FakeLLM(_good)
    out = attach_checklist(empty, plan, llm)
    assert out.checklist == [] and llm.calls == []
    assert next(s for s in out.stages if s.stage == "checklist").state == "skipped"


def test_decision_log_records_adopt_defer_reject() -> None:
    res, plan = _result(), _plan()
    items = build_checklist(res, plan, FakeLLM(_good))
    assert DECISION_STATES == ("채택", "보류", "기각")
    record_decision(items, "C1", "채택", note="바로 반영")
    record_decision(items, "C2", "보류")
    record_decision(items, "C2", "기각", note="범위 밖")
    assert items[0]["decision"] == "채택" and items[0]["decided_at"]
    assert items[1]["decision"] == "기각" and [e["decision"] for e in items[1]["decision_log"]] == ["보류", "기각"]
    with pytest.raises(ValueError):
        record_decision(items, "C3", "accept")
    with pytest.raises(KeyError):
        record_decision(items, "C99", "채택")
    log = decision_log(items)
    assert [row["decision"] for row in log] == ["채택", "기각", None, None]
    assert log[0]["action"] == items[0]["action"] and log[0]["plan_lines"] == items[0]["plan_lines"]
    json.dumps(log, ensure_ascii=False)  # 내보내기 가능


def test_items_render_in_ui_view_checklist() -> None:
    """E4 화면 계약(목업 checklist: id·t·r·s·m)으로 그대로 옮겨지는지."""
    view_mod = pytest.importorskip("neumann.api.view")
    res, plan = _result(), _plan()
    out = attach_checklist(res, plan, FakeLLM(_good))
    record_decision(out.checklist, "C1", "기각", note="과제 범위 밖")
    rows = view_mod.build_ui_view(out)["checklist"]
    assert [r["id"] for r in rows] == [it["item_id"] for it in out.checklist]
    assert [r["t"] for r in rows] == [it["action"] for it in out.checklist]
    assert rows[0]["r"] == "R3" and rows[0]["s"] == "기각" and rows[0]["m"] == "과제 범위 밖"


def test_decision_entries_feed_export_package() -> None:
    """E4 내보내기(DecisionEntry·decision_log.json)가 체크리스트 결정을 그대로 받는지."""
    export = pytest.importorskip("neumann.api.export")
    res, plan = _result(), _plan()
    out = attach_checklist(res, plan, FakeLLM(_good))
    record_decision(out.checklist, "C1", "채택", note="바로 반영")
    record_decision(out.checklist, "C3", "보류")
    entries = decision_entries(out.checklist)
    assert [e["item_id"] for e in entries] == ["C1", "C3"]
    parsed = [export.DecisionEntry.model_validate(e) for e in entries]
    assert [p.decision for p in parsed] == ["adopt", "hold"] and parsed[1].note is None
    files = export.build_package_files(out, decisions=entries)
    log = json.loads(files["decision_log.json"])
    assert [d["item_id"] for d in log["decisions"]] == ["C1", "C3"]


def test_schema_without_excerpts_still_strict() -> None:
    schema = checklist_schema(["a"], [])
    assert _strict_problems(schema) == []
    ev = schema["properties"]["cards"]["items"]["properties"]["actions"]["items"]["properties"]["evidence_ids"]
    assert "enum" not in ev["items"]
