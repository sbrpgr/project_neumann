"""E3-L1b 2차 의미검증: 가짜 llm_call로 검사한다(실제 API 없음).

완료 기준 1: 카드 기각(틀림) 시 행동 유지 · 없는 줄 번호 참조 · 실패 시 표기.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from neumann.analyze.checklist import attach_checklist
from neumann.analyze.validate import (
    VERDICTS,
    apply_validation,
    attach_validation,
    card_verdicts,
    validate_cards,
    validation_schema,
)
from neumann.models import PremortemResult, WhyApplies
from tests.e3.test_checklist import LEAK, SEED, FakeLLM, _good, _strict_problems
from tests.fixtures.loader import load_fixtures

ROOT = Path(__file__).resolve().parents[2]


def _base() -> tuple[PremortemResult, Any]:
    res = load_fixtures().premortem_result
    assert res.plan is not None
    return attach_checklist(res, res.plan, FakeLLM(_good)), res.plan


def _judge(card_verdicts_: dict[str, str], action_verdict: str | dict[str, str] = "match"):
    """카드별 판정과 행동 판정을 돌려주는 가짜 검증자."""

    def respond(payload: dict) -> dict:
        out = []
        for c in payload["cards"]:
            acts = []
            for a in c["actions"]:
                v = action_verdict if isinstance(action_verdict, str) else action_verdict.get(a["item_id"], "match")
                acts.append({"item_id": a["item_id"], "verdict": v, "reason": "연결된 줄에 적용된다."})
            out.append({"card_id": c["card_id"], "verdict": card_verdicts_[c["card_id"]],
                        "reason": "인용 줄과 비교한 판정이다.", "actions": acts})
        return {"cards": out}

    return respond


def test_mismatch_card_is_demoted_but_not_deleted_and_its_actions_stay() -> None:
    res, plan = _base()
    n_items = len(res.checklist)
    out = attach_validation(res, plan, FakeLLM(_judge({LEAK: "mismatch", SEED: "match"})))

    # 카드는 지우지 않는다
    assert [c.card_id for c in out.risk_cards] == [LEAK, SEED]
    report = out.verification["semantic"]
    assert report["demoted_cards"] == [LEAK] and report["status"] == "ok"
    assert card_verdicts(out) == {LEAK: "mismatch", SEED: "match"}
    leak_row = next(r for r in report["cards"] if r["card_id"] == LEAK)
    assert leak_row["verdict_ko"] == "틀림" and leak_row["demoted"] and leak_row["judge"] == "astra"

    # 카드가 틀림이어도 타당한 행동은 남는다(강등되지 않음)
    assert len(out.checklist) == n_items
    leak_items = [it for it in out.checklist if it["card_id"] == LEAK]
    assert leak_items and all(it["card_verdict"] == "mismatch" for it in leak_items)
    assert all(it["validation"]["verdict"] == "match" and not it["validation"]["demoted"] for it in leak_items)
    assert all(it["action"] for it in leak_items)
    assert any("틀림" in n and LEAK in n for n in out.notices)
    stage = next(s for s in out.stages if s.stage == "semantic_validate")
    assert stage.state == "ok" and stage.counts["cards_mismatch"] == 1 and stage.counts["actions_match"] == n_items


def test_mismatch_action_is_flagged_not_deleted_independent_of_card() -> None:
    res, plan = _base()
    out = attach_validation(res, plan, FakeLLM(_judge({LEAK: "match", SEED: "match"}, {"C1": "mismatch"})))
    c1 = next(it for it in out.checklist if it["item_id"] == "C1")
    assert c1["card_verdict"] == "match" and c1["validation"]["verdict"] == "mismatch" and c1["validation"]["demoted"]
    assert out.verification["semantic"]["demoted_actions"] == ["C1"]
    assert out.verification["semantic"]["demoted_cards"] == []
    assert len(out.checklist) == len(res.checklist)


def test_failure_leaves_cards_unverified_and_degrades() -> None:
    res, plan = _base()
    for llm in (FakeLLM(None), FakeLLM(raise_exc=RuntimeError("boom")), None):
        out = attach_validation(res, plan, llm)
        report = out.verification["semantic"]
        assert {r["verdict"] for r in report["cards"]} == {"unverified"}
        assert {r["verdict"] for r in report["actions"]} == {"unverified"}
        assert report["demoted_cards"] == [] and report["status"] == "degraded"
        assert all(r["judge"] == "none" for r in report["cards"])  # 규칙이 의미 판정을 흉내 내지 않는다
        stage = next(s for s in out.stages if s.stage == "semantic_validate")
        assert stage.state == "degraded" and out.status == "degraded"
        assert any("미검증" in n for n in out.notices)
        assert len(out.checklist) == len(res.checklist)  # 검증 실패로 행동을 잃지 않는다


def test_card_citing_nonexistent_lines_is_capped_at_weak() -> None:
    res, plan = _base()
    leak = next(c for c in res.risk_cards if c.card_id == LEAK)
    bad = leak.model_copy(update={"why_applies": WhyApplies(text=leak.why_applies.text, plan_lines=[99, 2])})
    res = res.model_copy(update={"risk_cards": [bad, *[c for c in res.risk_cards if c.card_id != LEAK]]})

    llm = FakeLLM(_judge({LEAK: "match", SEED: "match"}))
    report = validate_cards(res, plan, llm)
    row = next(r for r in report["cards"] if r["card_id"] == LEAK)
    assert row["verdict"] == "weak" and row["judge"] == "rule"
    assert row["cited_lines"] == [] and row["dropped_lines"] == [99, 2]  # 99 범위 밖, 2 빈 줄
    sent = next(c for c in llm.calls[0]["payload"]["cards"] if c["card_id"] == LEAK)
    assert sent["cited_lines"] == []  # 없는 줄은 모델에 보내지 않는다

    # 모델이 mismatch라 하면 그대로(상한은 weak이지 하한이 아니다)
    report = validate_cards(res, plan, FakeLLM(_judge({LEAK: "mismatch", SEED: "match"})))
    assert next(r for r in report["cards"] if r["card_id"] == LEAK)["verdict"] == "mismatch"

    # 호출이 실패해도 구조 사실(인용 줄 없음)은 규칙으로 표기
    report = validate_cards(res, plan, FakeLLM(None))
    row = next(r for r in report["cards"] if r["card_id"] == LEAK)
    assert row["verdict"] == "weak" and row["judge"] == "rule"
    assert next(r for r in report["cards"] if r["card_id"] == SEED)["verdict"] == "unverified"


def test_payload_sends_cited_line_text_and_actions() -> None:
    res, plan = _base()
    llm = FakeLLM(_judge({LEAK: "match", SEED: "match"}))
    validate_cards(res, plan, llm, effort="high")
    call = llm.calls[0]
    assert call["effort"] == "high"
    leak = next(c for c in call["payload"]["cards"] if c["card_id"] == LEAK)
    assert leak["cited_lines"] == [{"no": 16, "text": plan.line(16)}, {"no": 17, "text": plan.line(17)}]
    assert [a["item_id"] for a in leak["actions"]] == [it["item_id"] for it in res.checklist if it["card_id"] == LEAK]
    assert _strict_problems(call["schema"]) == []
    jsonschema.validate(_judge({LEAK: "match", SEED: "match"})(call["payload"]), call["schema"])


def test_unknown_ids_and_invalid_verdicts_are_ignored() -> None:
    res, plan = _base()
    seed_item = next(it["item_id"] for it in res.checklist if it["card_id"] == SEED)

    def respond(payload: dict) -> dict:
        return {"cards": [
            {"card_id": "card-ghost", "verdict": "mismatch", "reason": "", "actions": []},
            # LEAK 아래에 SEED의 행동 id를 넣었다 → 무시(그 행동은 미검증)
            {"card_id": LEAK, "verdict": "match", "reason": "맞다.",
             "actions": [{"item_id": seed_item, "verdict": "mismatch", "reason": ""}]},
            {"card_id": SEED, "verdict": "totally", "reason": "", "actions": []},
        ]}

    report = validate_cards(res, plan, FakeLLM(respond))
    assert {r["card_id"] for r in report["cards"]} == {LEAK, SEED}
    assert next(r for r in report["cards"] if r["card_id"] == SEED)["verdict"] == "unverified"
    assert next(r for r in report["actions"] if r["item_id"] == seed_item)["verdict"] == "unverified"
    assert report["demoted_cards"] == [] and report["status"] == "degraded"


def test_zero_cards_skipped_and_contract_kept() -> None:
    res, plan = _base()
    empty = res.model_copy(update={"risk_cards": [], "checklist": []})
    llm = FakeLLM(_judge({}))
    out = attach_validation(empty, plan, llm)
    assert llm.calls == [] and out.verification["semantic"]["status"] == "skipped"

    full = attach_validation(res, plan, FakeLLM(_judge({LEAK: "weak", SEED: "match"})))
    schema = json.loads((ROOT / "contracts" / "premortem_response.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(full.model_dump(mode="json"), schema)
    PremortemResult.model_validate(full.model_dump(mode="json"))


def test_apply_is_pure_and_schema_enum() -> None:
    res, plan = _base()
    report = validate_cards(res, plan, FakeLLM(_judge({LEAK: "mismatch", SEED: "match"})))
    before = json.dumps(res.checklist, ensure_ascii=False, sort_keys=True)
    apply_validation(res, report)
    assert json.dumps(res.checklist, ensure_ascii=False, sort_keys=True) == before  # 원본을 바꾸지 않는다
    schema = validation_schema(["a", "b"], ["C1"])
    card = schema["properties"]["cards"]["items"]["properties"]
    assert card["verdict"]["enum"] == list(VERDICTS) and card["card_id"]["enum"] == ["a", "b"]
    assert _strict_problems(schema) == []
