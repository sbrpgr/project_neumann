"""E3-L1e 근거 게이트: 근거 없는 체크리스트 항목·심사평 문장은 내보내지 않는다(가짜 llm_call, 실제 API 없음).

배경: v1 라이브 E2E(E5-L1e2e)에서 체크리스트 항목 1개씩이 근거 번호 없이 화면에 나왔다. 모델이 가끔
`evidence_ids`를 비우거나 풀 밖 id만 돌려준다. 기본 처리 = **폐기 + 폐기 수 표기**(승계·재요청 없음).

경우: 근거 빈 항목 · 없는 id · 다른 카드의 id · 전부 비었을 때 · 정상 — 체크리스트 생성, 2차 검증, 예상 심사평, 화면.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from neumann.analyze import gate as g
from neumann.analyze.checklist import (
    CHECKLIST_INSTRUCTIONS,
    EVIDENCE_GATE,
    attach_checklist,
    build_checklist,
    gate_checklist_items,
)
from neumann.analyze.review import attach_expected_review, generate_expected_review
from neumann.analyze.validate import attach_validation, validate_cards
from neumann.models import PremortemResult
from tests.e3.test_checklist import LEAK, SEED, FakeLLM, _ev, _good
from tests.fixtures.loader import load_fixtures

FORGED = "ex_made_up_000000"


def _result() -> PremortemResult:
    return load_fixtures().premortem_result.model_copy(deep=True)


def _card_ev(res: PremortemResult, card_id: str) -> list[str]:
    return list(next(c for c in res.risk_cards if c.card_id == card_id).evidence)


def _assert_all_grounded(res: PremortemResult, items: list[dict[str, Any]]) -> None:
    """불변식: 모든 항목이 근거 1개 이상이고, 전부 결과 evidence 안이며, 전부 연결 카드의 근거 안이다."""
    known = {e.excerpt_id for e in res.evidence}
    for it in items:
        pool = set(_card_ev(res, it["card_id"]))
        assert it["evidence"], it
        assert set(it["evidence"]) <= known and set(it["evidence"]) <= pool, it


def _respond(leak_ids: Any, seed_ids: Any = "good"):
    """LEAK 카드 행동 2개(첫째 근거는 leak_ids, 둘째는 정상) + SEED 카드 행동 1개."""

    def respond(payload: dict) -> dict:
        leak, seed = _ev(payload, LEAK), _ev(payload, SEED)
        first = leak_ids(payload) if callable(leak_ids) else leak_ids
        seed_first = seed[:1] if seed_ids == "good" else seed_ids
        return {"cards": [
            {"card_id": LEAK, "actions": [
                {"action": "분할 단위를 계획서 16행에 적는다.", "verify": "", "plan_lines": [16], "evidence_ids": first},
                {"action": "중복 제거 기준을 착수 전에 정한다.", "verify": "", "plan_lines": [17], "evidence_ids": leak[1:2]},
            ]},
            {"card_id": SEED, "actions": [
                {"action": "시드 반복 횟수를 22행에 적는다.", "verify": "", "plan_lines": [22], "evidence_ids": seed_first},
            ]},
        ]}

    return respond


# ── 체크리스트 생성 직후 게이트 ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("leak_ids", "reason"),
    [
        ([], g.MISSING_CITATION),  # 근거 빈 항목
        ([FORGED], g.UNKNOWN_EXCERPT),  # 없는 id
        (lambda p: _ev(p, SEED)[:1], g.EXCERPT_CARD_MISMATCH),  # 다른 카드의 id
        (lambda p: [FORGED, *_ev(p, SEED)[:1]], g.UNKNOWN_EXCERPT),  # 없는 id + 다른 카드 id
    ],
    ids=["empty", "unknown_id", "other_card_id", "unknown_and_other"],
)
def test_ungrounded_action_is_dropped_and_counted(leak_ids: Any, reason: str) -> None:
    res = _result()
    assert res.plan is not None
    out = attach_checklist(res, res.plan, FakeLLM(_respond(leak_ids)))

    # 폐기: 그 행동만 빠지고 나머지는 LLM 항목 그대로(규칙 대체 없음), 번호는 빈틈 없이
    actions = [it["action"] for it in out.checklist]
    assert "분할 단위를 계획서 16행에 적는다." not in actions
    assert actions == ["중복 제거 기준을 착수 전에 정한다.", "시드 반복 횟수를 22행에 적는다."]
    assert [it["item_id"] for it in out.checklist] == ["C1", "C2"]
    assert {it["generator"] for it in out.checklist} == {"astra"}
    _assert_all_grounded(out, out.checklist)
    # 승계 없음: 남은 항목의 근거는 모델이 댄 그대로다(카드 근거로 채우지 않는다)
    assert out.checklist[0]["evidence"] == _card_ev(res, LEAK)[1:2]
    assert not any("inherit" in json.dumps(it) for it in out.checklist)

    # 폐기 수를 status(단계 기록)와 결과 검증 기록에 남긴다. 게이트 폐기는 강등이 아니다(심사평 게이트와 같게)
    stage = next(s for s in out.stages if s.stage == "checklist")
    assert stage.state == "ok" and out.status == "ok"
    assert stage.counts["items_dropped_no_evidence"] == 1
    assert "근거 없는 항목 1개 제외" in (stage.detail or "")
    audit = out.verification["checklist_evidence"]
    assert audit["gate"] == EVIDENCE_GATE and audit["policy"] == "drop"
    assert audit["dropped"] == 1 and audit["reasons"] == {reason: 1} and audit["items"] == 2
    (rec,) = audit["dropped_detail"]
    assert rec["card_id"] == LEAK and rec["reason"] == reason and rec["where"] == "checklist"
    assert rec["action"] == "분할 단위를 계획서 16행에 적는다."


def test_all_actions_ungrounded_fall_back_to_labeled_rule_per_card() -> None:
    """전부 비었을 때: LLM 행동은 모두 폐기, 카드마다 규칙 경로(표기됨). 항목은 여전히 전부 근거가 있다."""
    res = _result()
    assert res.plan is not None

    def respond(payload: dict) -> dict:
        return {"cards": [{"card_id": c["card_id"], "actions": [
            {"action": f"{c['card_id']} 행동 하나를 한다.", "verify": "", "plan_lines": [16], "evidence_ids": []},
            {"action": f"{c['card_id']} 행동 둘을 한다.", "verify": "", "plan_lines": [16], "evidence_ids": []},
        ]} for c in payload["cards"]]}

    stats: dict[str, Any] = {}
    items = build_checklist(res, res.plan, FakeLLM(respond), stats=stats)
    assert stats["items_dropped_no_evidence"] == 4
    assert items and {it["generator"] for it in items} == {"rule"}
    assert {it["fallback_reason"] for it in items} == {"llm_no_grounded_action"}
    assert not any("행동 하나를 한다" in it["action"] or "행동 둘을 한다" in it["action"] for it in items)
    _assert_all_grounded(res, items)

    out = attach_checklist(res, res.plan, FakeLLM(respond))
    stage = next(s for s in out.stages if s.stage == "checklist")
    assert stage.state == "degraded" and out.status == "degraded"  # 규칙 대체는 강등(기존 규칙)
    assert "llm_no_grounded_action" in (stage.detail or "") and "근거 없는 항목 4개 제외" in (stage.detail or "")
    assert out.verification["checklist_evidence"]["dropped"] == 4


def test_only_the_card_with_all_ungrounded_actions_falls_back() -> None:
    res = _result()
    assert res.plan is not None

    def respond(payload: dict) -> dict:
        data = _good(payload)
        for c in data["cards"]:
            if c["card_id"] == LEAK:
                for a in c["actions"]:
                    a["evidence_ids"] = []
        return data

    items = build_checklist(res, res.plan, FakeLLM(respond))
    assert {it["generator"] for it in items if it["card_id"] == LEAK} == {"rule"}
    assert {it["generator"] for it in items if it["card_id"] == SEED} == {"astra"}
    _assert_all_grounded(res, items)


def test_normal_checklist_drops_nothing() -> None:
    res = _result()
    assert res.plan is not None
    out = attach_checklist(res, res.plan, FakeLLM(_good))
    stage = next(s for s in out.stages if s.stage == "checklist")
    assert stage.state == "ok" and stage.detail is None and stage.counts["items_dropped_no_evidence"] == 0
    assert out.verification["checklist_evidence"]["dropped"] == 0 and len(out.checklist) == 4
    _assert_all_grounded(out, out.checklist)


def test_gate_function_rejects_every_ungrounded_shape() -> None:
    """같은 검사를 직접: 빈 근거·근거 키 없음·없는 id·다른 카드 id·없는 카드·객체 아님은 폐기, 정상은 통과."""
    res = _result()
    leak_ev, seed_ev = _card_ev(res, LEAK), _card_ev(res, SEED)
    items = [
        {"item_id": "A", "card_id": LEAK, "action": "a", "evidence": []},
        {"item_id": "B", "card_id": LEAK, "action": "b"},
        {"item_id": "C", "card_id": LEAK, "action": "c", "evidence": [FORGED]},
        {"item_id": "D", "card_id": LEAK, "action": "d", "evidence": [seed_ev[0]]},
        {"item_id": "E", "card_id": "card-ghost", "action": "e", "evidence": [leak_ev[0]]},
        {"item_id": "F", "card_id": LEAK, "action": "f", "evidence": [leak_ev[0], seed_ev[0]]},
        "not-a-dict",
        {"item_id": "OK", "card_id": LEAK, "action": "ok", "evidence": [leak_ev[0]]},
    ]
    kept, drops = gate_checklist_items(items, res)
    assert [it["item_id"] for it in kept] == ["OK"]
    assert [(d.get("item_id"), d["reason"]) for d in drops] == [
        ("A", g.MISSING_CITATION), ("B", g.MISSING_CITATION), ("C", g.UNKNOWN_EXCERPT),
        ("D", g.EXCERPT_CARD_MISMATCH), ("E", g.UNKNOWN_CARD), ("F", g.EXCERPT_CARD_MISMATCH),
        (None, g.MALFORMED),  # 객체가 아닌 항목: 근거를 읽을 수 없다
    ]


def test_prompt_asks_for_at_least_one_evidence_id() -> None:
    assert "excerpt_id 1~3개" in CHECKLIST_INSTRUCTIONS and "0~3" not in CHECKLIST_INSTRUCTIONS
    assert "근거 id가 없는 행동은 버려진다" in CHECKLIST_INSTRUCTIONS


@pytest.mark.parametrize("seed", range(6))
def test_invariant_holds_for_mixed_bad_responses(seed: int) -> None:
    """정상·빈 근거·없는 id·다른 카드 id를 섞은 응답에서도 나오는 항목은 전부 근거가 있다."""
    res = _result()
    assert res.plan is not None
    shapes = [lambda me, other: me[:1], lambda me, other: [], lambda me, other: [FORGED],
              lambda me, other: other[:1], lambda me, other: [FORGED, *me[:1]]]

    def respond(payload: dict) -> dict:
        out = []
        for ci, c in enumerate(payload["cards"]):
            me = _ev(payload, c["card_id"])
            other = _ev(payload, SEED if c["card_id"] == LEAK else LEAK)
            acts = [{"action": f"{c['card_id']} 행동 {k}번을 한다.", "verify": "", "plan_lines": [16],
                     "evidence_ids": shapes[(seed + ci + k) % len(shapes)](me, other)} for k in range(3)]
            out.append({"card_id": c["card_id"], "actions": acts})
        return {"cards": out}

    out = attach_checklist(res, res.plan, FakeLLM(respond))
    _assert_all_grounded(out, out.checklist)
    audit = out.verification["checklist_evidence"]
    stage = next(s for s in out.stages if s.stage == "checklist")
    assert stage.counts["items_dropped_no_evidence"] == audit["dropped"] == len(audit["dropped_detail"])


# ── 2차 검증 게이트 ─────────────────────────────────────────────────────


def _judge_all_match(payload: dict) -> dict:
    return {"cards": [{"card_id": c["card_id"], "verdict": "match", "reason": "맞다.",
                       "actions": [{"item_id": a["item_id"], "verdict": "match", "reason": "맞다."} for a in c["actions"]]}
                      for c in payload["cards"]]}


def test_second_validation_catches_items_that_bypassed_the_checklist_gate() -> None:
    """생성 직후 게이트를 우회해 들어온 근거 없는 항목(빈 근거·없는 id·다른 카드 id)을 2차 검증이 잡아 뺀다."""
    res = _result()
    assert res.plan is not None
    base = attach_checklist(res, res.plan, FakeLLM(_good))
    good_ids = [it["item_id"] for it in base.checklist]
    seed_ev = _card_ev(res, SEED)
    forged = [
        {**base.checklist[0], "item_id": "X1", "action": "근거 없는 행동", "evidence": []},
        {**base.checklist[0], "item_id": "X2", "action": "없는 id 행동", "evidence": [FORGED]},
        {**base.checklist[0], "item_id": "X3", "action": "다른 카드 근거 행동", "evidence": [seed_ev[0]]},
    ]
    tampered = base.model_copy(update={"checklist": [*base.checklist, *forged]})

    llm = FakeLLM(_judge_all_match)
    out = attach_validation(tampered, res.plan, llm)
    sent = {a["item_id"] for call in llm.calls for c in call["payload"]["cards"] for a in c["actions"]}
    assert sent == set(good_ids)  # 근거 없는 항목은 모델에 보내지 않는다
    assert [it["item_id"] for it in out.checklist] == good_ids  # 내보내지 않는다
    _assert_all_grounded(out, out.checklist)
    report = out.verification["semantic"]
    assert report["counts"]["actions_no_evidence"] == 3 and report["dropped_actions"] == ["X1", "X2", "X3"]
    assert report["evidence_gate"]["reasons"] == {g.MISSING_CITATION: 1, g.UNKNOWN_EXCERPT: 1, g.EXCERPT_CARD_MISMATCH: 1}
    assert report["status"] == "degraded" and "근거 없는 체크리스트 항목 3개 제외" in report["reason"]
    stage = next(s for s in out.stages if s.stage == "semantic_validate")
    assert stage.state == "degraded" and stage.counts["actions_no_evidence"] == 3 and out.status == "degraded"
    assert any("근거 없는 체크리스트 항목 3개 제외" in n for n in out.notices)
    assert not any("미검증" in n for n in out.notices)  # 게이트 폐기를 미검증이라고 쓰지 않는다


def test_second_validation_passes_normal_checklist_unchanged() -> None:
    res = _result()
    assert res.plan is not None
    base = attach_checklist(res, res.plan, FakeLLM(_good))
    out = attach_validation(base, res.plan, FakeLLM(_judge_all_match))
    report = out.verification["semantic"]
    assert report["status"] == "ok" and report["counts"]["actions_no_evidence"] == 0 and report["dropped_actions"] == []
    assert [it["item_id"] for it in out.checklist] == [it["item_id"] for it in base.checklist]


def test_apply_validation_regates_checklist_it_is_given() -> None:
    """보고서를 만든 뒤 체크리스트가 바뀌어도(근거 없는 항목이 끼어도) 붙일 때 같은 검사로 뺀다."""
    res = _result()
    assert res.plan is not None
    base = attach_checklist(res, res.plan, FakeLLM(_good))
    report = validate_cards(base, res.plan, FakeLLM(_judge_all_match))
    assert report["counts"]["actions_no_evidence"] == 0
    tampered = base.model_copy(update={"checklist": [*base.checklist,
                                                     {**base.checklist[0], "item_id": "X9", "evidence": []}]})
    from neumann.analyze.validate import apply_validation

    out = apply_validation(tampered, report)
    assert "X9" not in [it["item_id"] for it in out.checklist]
    assert out.verification["semantic"]["counts"]["actions_no_evidence"] == 1
    assert out.verification["semantic"]["status"] == "degraded"


# ── 예상 심사평 게이트 ──────────────────────────────────────────────────


def _aliases(input_text: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    payload = json.loads(input_text)
    return ({c["id"]: c["risk_code"] for c in payload["cards"]}, {c["id"]: [e["id"] for e in c["evidence"]] for c in payload["cards"]})


def _s(text: str, ex: list[str], cards: list[str], lines: list[int] = ()) -> dict:  # type: ignore[assignment]
    return {"text": text, "excerpt_ids": list(ex), "card_ids": list(cards), "plan_lines": list(lines)}


class _ReviewCall:
    generator = "astra"
    model = "gpt-6-astra"

    def __init__(self, fn: Any) -> None:
        self.fn = fn

    def __call__(self, schema, instructions, input, *, effort):  # noqa: A002
        return self.fn(input)


def test_review_sentences_without_evidence_never_reach_output() -> None:
    res = _result()

    def respond(input_text: str) -> dict:
        code, ev = _aliases(input_text)
        c_leak = next(k for k, v in code.items() if v == "R3")
        c_seed = next(k for k, v in code.items() if v == "R2")
        return {
            "strength": [],
            "weakness": [
                _s("무작위 분할은 시험 성능을 과대평가할 수 있다 (16–17행).", ev[c_leak][:1], [c_leak], [16, 17]),  # 정상
                _s("근거 없이 쓴 약점 문장이다.", [], [c_leak]),  # 근거 빈 문장
                _s("없는 근거를 단 약점 문장이다.", ["E99"], [c_leak]),  # 없는 id
                _s("다른 카드의 근거를 단 약점 문장이다.", ev[c_seed][:1], [c_leak]),  # 다른 카드의 id
            ],
            "request": [],
        }

    out = attach_expected_review(res, _ReviewCall(respond))
    er = out.expected_review
    assert er["status"] == "ok" and er["generator"] == "astra"
    assert [x["t"] for x in er["weakness"]] == ["무작위 분할은 시험 성능을 과대평가할 수 있다 (16–17행)."]
    assert er["audit"]["no_evidence"] == 3 and er["audit"]["drop"] == 3
    assert er["audit"]["reasons"] == {g.MISSING_CITATION: 1, g.UNKNOWN_EXCERPT: 1, g.EXCERPT_CARD_MISMATCH: 1}
    stage = next(s for s in out.stages if s.stage == "expected_review")
    assert stage.counts["no_evidence"] == 3 and "근거 없는 문장 3개 제외" in (stage.detail or "")
    assert not g.verify_expected_review(er, out).dropped  # 나간 문장을 다시 검사해도 전부 통과


def test_review_all_ungrounded_falls_back_to_rule_and_every_sentence_is_grounded() -> None:
    res = _result()

    def respond(input_text: str) -> dict:
        return {"strength": [], "weakness": [_s("근거 없는 문장 하나.", [], []), _s("근거 없는 문장 둘.", ["E77"], [])],
                "request": [_s("근거 없는 요청.", [], [])]}

    er = generate_expected_review(res, _ReviewCall(respond))
    assert er["generator"] == "rule" and er["status"] == "degraded"
    assert er["audit"]["no_evidence"] == 3  # 모델 문장 폐기 수가 규칙 대체 뒤에도 남는다
    idx = g.EvidenceIndex(res)
    for sec in ("strength", "weakness", "request"):
        for sent in er[sec]:
            assert g.evidence_link_problem(sent["c"], sent["cards"], idx) == (None, "")
    assert not any("근거 없는" in s["t"] for sec in ("weakness", "request") for s in er[sec])


# ── 체크리스트 마지막 게이트(M1b) ────────────────────────────────────────


def test_final_gate_drops_ungrounded_rule_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """규칙 경로 항목도 마지막 게이트를 지난다: 규칙 문구가 근거 없이·다른 카드 근거로 나오면 버린다(번호는 거른 뒤)."""
    from neumann.analyze import checklist as ck

    res = _result()
    assert res.plan is not None
    real = ck.rule_actions

    def bad_rule_actions(card, valid_lines):
        good = real(card, valid_lines)[:1]
        other = SEED if card.card_id == LEAK else LEAK
        return [
            *good,
            {**good[0], "action": f"{card.card_id} 근거 없는 규칙 문구", "evidence": []},
            {**good[0], "action": f"{card.card_id} 다른 카드 근거 규칙 문구", "evidence": _card_ev(res, other)[:1]},
        ]

    monkeypatch.setattr(ck, "rule_actions", bad_rule_actions)
    stats: dict[str, Any] = {}
    items = ck.build_checklist(res, res.plan, None, stats=stats)  # llm 없음 → 전부 규칙 경로
    assert [it["item_id"] for it in items] == ["C1", "C2"]  # 카드마다 좋은 규칙 항목 1개만, 번호 빈틈 없음
    assert not any("규칙 문구" in it["action"] for it in items)
    _assert_all_grounded(res, items)
    assert stats["items_dropped_no_evidence"] == 4
    finals = [d for d in stats["evidence_drops"] if d["where"] == "checklist_final"]
    assert sorted(d["reason"] for d in finals) == sorted([g.MISSING_CITATION, g.EXCERPT_CARD_MISMATCH] * 2)


def test_final_gate_catches_a_regression_in_action_cleaning(monkeypatch: pytest.MonkeyPatch) -> None:
    """첫 게이트(_clean_actions)가 고장 나 근거 없는 행동을 흘려도 마지막 게이트가 잡는다."""
    from neumann.analyze import checklist as ck

    res = _result()
    assert res.plan is not None
    real = ck._clean_actions

    def leaky(raw_actions, card, valid_lines, index):
        kept, stats, drops = real(raw_actions, card, valid_lines, index)
        leak = {**kept[0], "action": f"{card.card_id} 새어 나온 행동", "evidence": []} if kept else None
        return ([*kept, leak] if leak else kept), stats, drops

    monkeypatch.setattr(ck, "_clean_actions", leaky)
    out = ck.attach_checklist(res, res.plan, FakeLLM(_good))
    assert not any("새어 나온 행동" in it["action"] for it in out.checklist)
    assert [it["item_id"] for it in out.checklist] == ["C1", "C2", "C3", "C4"]
    _assert_all_grounded(out, out.checklist)
    audit = out.verification["checklist_evidence"]
    assert audit["dropped"] == 2 and {d["where"] for d in audit["dropped_detail"]} == {"checklist_final"}
    stage = next(s for s in out.stages if s.stage == "checklist")
    assert stage.counts["items_dropped_no_evidence"] == 2 and "근거 없는 항목 2개 제외" in (stage.detail or "")


def test_review_malformed_citation_counts_as_no_evidence() -> None:
    """심사평에서 근거 id를 읽을 수 없는 문장(형식 오류)도 '근거 없는 항목'으로 센다(화면 수와 일관)."""
    res = _result()

    def respond(input_text: str) -> dict:
        code, ev = _aliases(input_text)
        c_leak = next(k for k, v in code.items() if v == "R3")
        return {"strength": [], "request": [], "weakness": [
            _s("무작위 분할은 누출 위험이 있다 (16행).", ev[c_leak][:1], [c_leak], [16]),
            {"text": "근거 형식이 틀린 문장.", "excerpt_ids": "E1", "card_ids": [], "plan_lines": []},  # 목록이 아님
            _s("이 설계로는 R² 0.95 이상을 달성하기 어렵다.", ev[c_leak][:1], [c_leak]),  # 없는 수치(근거 문제 아님)
        ]}

    er = generate_expected_review(res, _ReviewCall(respond))
    assert er["audit"]["reasons"] == {g.MALFORMED: 1, g.FABRICATED_NUMBER: 1}
    assert er["audit"]["no_evidence"] == 1 and er["audit"]["drop"] == 2
