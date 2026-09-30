"""astra ③ 카드 합성: 근거 없는 카드 거부, 조립 불변식, 점수는 코드가 계산."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from neumann.analyze import cards
from neumann.analyze.cards import CardDraft, finalize, guard_why, synthesize_cards
from neumann.analyze.extract import Issue
from neumann.llm import LLMCall, MockProvider
from neumann.models import Excerpt, PlanDocument, RiskCard, RiskCode, RiskScore, WhyApplies

PLAN = PlanDocument.from_text(
    "# 계획\n문헌 데이터 12,000건을 수집한다.\nWe randomly split the dataset into 80/10/10 sets.\n"
    "We do not report error bars.\nCode will not be released.",
    "s1",
)


def _issue(work: str, i: int, code: RiskCode = RiskCode.R2, conf: float = 0.8) -> Issue:
    text = f"Reviewer sentence {i} about {code.value} in {work}."
    ex = Excerpt.from_source(text, 0, len(text), source_kind="review", source_id=f"{work}:r1:{i}",
                             source_url=f"https://example.org/{work}")
    return Issue(excerpt=ex, work_id=work, risk_code=code, polarity="negative", confidence=conf,
                 rel_start=0, rel_end=len(text), generator="astra", model="m")


ISSUES = [_issue(w, i, c) for w in ("w1", "w2", "w3") for i, c in enumerate([RiskCode.R2, RiskCode.R3, RiskCode.R5, RiskCode.R0])]
SIM = {"w1": 0.9, "w2": 0.6, "w3": 0.3}


def _pool_ids():
    """synthesize_cards가 모델에 보내는 별칭 → Issue (build_pool과 같은 순서)."""
    return {f"E{i + 1}": iss for i, iss in enumerate(cards.build_pool(ISSUES))}


def _alias(work: str, code: RiskCode) -> str:
    return next(a for a, iss in _pool_ids().items() if iss.work_id == work and iss.risk_code == code)


def _run(response) -> cards.SynthesisResult:
    llm = MockProvider(scripted={"synthesize_cards": [response]})
    return synthesize_cards(PLAN, ISSUES, {"w1": "T1"}, SIM, 3, llm)


def _card(code="R2", ev=None, lines=(3, 4), why="L4에서 오차 막대를 보고하지 않는다.", title="오차 막대 부재"):
    ev = ev if ev is not None else [_alias(w, RiskCode(code)) for w in ("w1", "w2", "w3")]
    return {"risk_code": code, "title": title, "why_applies": why, "plan_lines": list(lines), "evidence_ids": ev}


def test_pool_excludes_r0_and_positive():
    pool = cards.build_pool(ISSUES)
    assert pool and all(i.risk_code not in (RiskCode.R0, RiskCode.R9) for i in pool)


def test_valid_card_gets_code_attached_evidence_and_score():
    res = _run({"cards": [_card()], "no_card_reason": None})
    assert len(res.cards) == 1 and res.generator == "mock"
    card = res.cards[0]
    assert card.generator.value == "mock" and card.risk_code is RiskCode.R2
    assert card.why_applies.plan_lines == [3, 4]
    assert set(card.works) == {"w1", "w2", "w3"}
    # 근거는 코드가 붙인 원문 Excerpt
    assert set(card.evidence) == set(res.evidence) and len(card.evidence) == 3
    for x in card.evidence:
        assert res.evidence[x].text.startswith("Reviewer sentence")
    s = card.score
    assert s.severity == 0.8  # R2 = S4
    assert abs(s.total - s.similarity * s.frequency * s.severity * s.confidence) < 1e-3
    assert abs(s.similarity - 0.6) < 1e-6 and s.frequency == 1.0


def test_card_with_fewer_than_three_evidence_is_rejected():
    res = _run({"cards": [_card(ev=[_alias("w1", RiskCode.R2), _alias("w2", RiskCode.R2)])], "no_card_reason": None})
    assert res.cards == [] and res.drops["card_evidence_lt3"] == 1
    assert "조립 불변식" in res.no_card_reason


def test_card_from_single_paper_is_rejected():
    ids = [_alias("w1", c) for c in (RiskCode.R2, RiskCode.R3, RiskCode.R5)]
    res = _run({"cards": [_card(ev=ids)], "no_card_reason": None})
    assert res.cards == [] and res.drops["card_works_lt2"] == 1


def test_unknown_evidence_id_fails_schema_and_falls_back_to_rule_cards():
    """모델이 풀에 없는 근거 id를 내면 스키마 재검증에서 걸리고, 그 단계는 비상 규칙 카드로 대신한다."""
    res = _run({"cards": [_card(ev=["E999", "E1", "E2"])], "no_card_reason": None})
    assert res.fallback_reason and "schema_invalid" in res.fallback_reason
    assert res.generator == "rule" and res.cards
    assert all(c.generator.value == "rule" for c in res.cards)


def test_plan_lines_out_of_range_dropped_and_card_without_lines_rejected():
    res = _run({"cards": [_card(lines=(3, 99)), _card(code="R3", lines=(0, 42))], "no_card_reason": None})
    assert len(res.cards) == 1 and res.cards[0].why_applies.plan_lines == [3]
    assert res.drops["plan_line_out_of_range"] == 3 and res.drops["card_no_plan_lines"] == 1


def test_unsupported_number_sentence_is_removed_not_card():
    why = "L3에서 무작위 분할을 쓴다. 이 방식은 성능을 37% 부풀린다."
    res = _run({"cards": [_card(why=why)], "no_card_reason": None})
    assert len(res.cards) == 1
    assert res.cards[0].why_applies.text == "L3에서 무작위 분할을 쓴다."
    assert res.drops["why_sentence_unsupported_number"] == 1


def test_guard_why_allows_plan_numbers_and_line_refs():
    text, dropped = guard_why("L2, L3: 12,000건을 80/10/10으로 나눈다.", PLAN.text)
    assert dropped == 0 and text


def test_no_card_reason_from_model():
    res = _run({"cards": [], "no_card_reason": "계획서와 맞는 지적이 없다"})
    assert res.cards == [] and "계획서와 맞는 지적이 없다" in res.no_card_reason


def test_max_eight_cards_and_r0_never_a_card():
    many = [_issue(f"w{j}", i, RiskCode.R2) for j in range(10) for i in range(3)]
    drafts = [CardDraft(RiskCode.R2, f"t{j}", "x", [2], many[j * 3 : j * 3 + 3] + many[(j * 3 + 3) % 30 : (j * 3 + 3) % 30 + 1], "astra")
              for j in range(10)]
    drafts.append(CardDraft(RiskCode.R0, "r0", "x", [2], many[:4], "astra"))
    from collections import Counter

    drops: Counter = Counter()
    out, evidence, _ = finalize(drafts, PLAN, {f"w{j}": 0.5 for j in range(10)}, many, 10, drops)
    assert len(out) == cards.MAX_CARDS
    assert drops["card_code_not_allowed"] == 1 and drops["card_over_max"] == 2
    assert all(c.risk_code is not RiskCode.R0 for c in out)
    assert all(x in evidence for c in out for x in c.evidence)


def test_rule_cards_are_labelled_rule():
    res = cards.rule_cards(PLAN, ISSUES, SIM, 3)
    assert res.generator == "rule" and res.cards
    for c in res.cards:
        assert c.generator.value == "rule" and "규칙" in c.why_applies.text
        assert len(c.evidence) >= 3 and len(set(c.works)) >= 2


def test_empty_pool_gives_reason_without_llm_call():
    llm = MockProvider()
    res = synthesize_cards(PLAN, [ISSUES[3]], {}, SIM, 3, llm)  # R0 하나뿐
    assert res.cards == [] and res.no_card_reason and llm.calls == []


def test_model_rejects_card_without_evidence():
    with pytest.raises(ValidationError):
        RiskCard(
            card_id="c", risk_code=RiskCode.R2, title="t", why_applies=WhyApplies(text="x", plan_lines=[1]), evidence=[],
            score=RiskScore(similarity=0, frequency=0, severity=0, confidence=0, total=0), generator="astra",
        )


def test_prompt_payload_has_no_quote_field_request():
    """카드 스키마에 인용문 칸이 없다: 모델은 id·줄 번호·제목·이유만 돌려준다."""
    props = cards.build_schema(["E1"])["properties"]["cards"]["items"]["properties"]
    assert set(props) == {"risk_code", "title", "why_applies", "plan_lines", "evidence_ids"}
    captured: list[LLMCall] = []
    llm = MockProvider({"synthesize_cards": lambda c: captured.append(c) or {"cards": [], "no_card_reason": "x"}})
    synthesize_cards(PLAN, ISSUES, {}, SIM, 3, llm)
    assert captured and {"plan", "papers", "pool"} <= set(captured[0].payload)
