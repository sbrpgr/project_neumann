"""드롭형 스크러빙: 수치·우월성·실증 문장을 통째로 지우고, 잔여 0 검사가 실제로 잡는지."""

from __future__ import annotations

import pytest

from eval import backtest_plans as bp

ABSTRACT = (
    "Predicting protein stability from sequence remains difficult. "
    "We propose a graph model that encodes residue contacts with an equivariant layer. "
    "Our method outperforms strong baselines on three datasets. "
    "It reaches 92.4% accuracy and is 3x faster. "
    "Extensive experiments on five benchmarks confirm the design. "
    "The model is trained with a contrastive objective over homologous families. "
    "Code is available at https://anonymous.4open.science/r/abc-123."
)


def test_drop_whole_sentences_not_masking():
    plan, dropped = bp.scrub_drop_only(ABSTRACT)
    assert plan == (
        "Predicting protein stability from sequence remains difficult. "
        "We propose a graph model that encodes residue contacts with an equivariant layer. "
        "The model is trained with a contrastive objective over homologous families."
    )
    assert len(dropped) == 4
    reasons = [d["hits"] for d in dropped]
    assert "CLAIM" in reasons[0]  # outperforms
    assert "NUM" in reasons[1]  # 92.4%, 3x
    assert "EVID" in reasons[2]  # extensive experiments / benchmarks
    assert reasons[3] == ["URL"]
    assert "[" not in plan and "outperform" not in plan.lower()


def test_masking_failure_examples_from_protocol_are_dropped():
    # 05_eval_protocol §1.3 마스킹 실패 사례의 원문 문장: 드롭형이면 문장째 사라진다
    s1 = "When applied on established real-world datasets, SYFLOW provides easily interpretable descriptions in a fraction of the times of state-of-the-art methods."
    s2 = "In evaluating on synthetic datasets, we also beat the competition in terms of precision/recall."
    plan, dropped = bp.scrub_drop_only(s1 + " " + s2)
    assert plan == "" and len(dropped) == 2


def test_residual_check_really_detects():
    # 검사기가 항상 0을 내지 않는지: 스크러빙 전 원문에는 잔여가 있어야 한다
    raw = bp.residual_hits(ABSTRACT)
    assert raw["NUM"] >= 2 and raw["CLAIM"] >= 1 and raw["EVID"] >= 1 and raw["URL"] == 1
    plan, _ = bp.scrub_drop_only(ABSTRACT)
    assert bp.residual_hits(plan) == {"NUM": 0, "CLAIM": 0, "EVID": 0, "URL": 0}


def test_make_plan_flags_short_and_raises_on_residual(monkeypatch):
    row = bp.make_plan("ns:X", ABSTRACT)
    assert row["residual_total"] == 0 and row["needs_manual_restore"] is True  # 400자 미만
    assert row["plan_id"] == bp.sha256_text(row["plan_text"]) and row["sentences_dropped"] == 4
    long_abs = " ".join(f"We describe component number {w} of the proposed pipeline in detail." for w in "abcdefghij")
    assert bp.make_plan("ns:Y", long_abs)["needs_manual_restore"] is False
    # 스크러버가 고장 나 문장을 남기면 2단 검사가 멈춘다
    monkeypatch.setattr(bp, "scrub_drop_only", lambda text: (text, []))
    with pytest.raises(bp.ResidualPatternError):
        bp.make_plan("ns:Z", ABSTRACT)


def test_regex_are_protocol_verbatim():
    # 사전 고정: 05_eval_protocol §4.2 정규식 원문(바뀌면 이 테스트가 깨진다)
    assert bp.NUM.pattern == r'\b\d+(?:\.\d+)?\s?%|\b\d+\.\d+\b|\b\d+(?:\.\d+)?\s?(?:x|×)\b|\bp\s?<\s?0?\.\d+'
    assert bp.CLAIM.pattern.startswith(r'\b(?:out[- ]?perform\w*|state[- ]of[- ]the[- ]art|SOTA|surpass\w*|superior\w*|')
    assert bp.CLAIM.pattern.endswith(r'validat\w*|verif\w*|confirm\w*|show[s]?\s+that|prove[sd]?)\b')
    assert bp.EVID.pattern.endswith(r'we\s+show|we\s+demonstrate|extensive\w*|comprehensive\s+(?:experiments|evaluation))\b')
    assert bp.SENT_SPLIT.pattern == r'(?<=[.!?])\s+'


def test_summarize_counts():
    rows = [bp.make_plan("a", ABSTRACT), bp.make_plan("b", "Only one neutral sentence here.")]
    s = bp.summarize(rows)
    assert s["n_plans"] == 2 and s["residual_total"] == 0 and s["under_400"] == 2
    assert s["drop_reasons_total"]["URL"] == 1
