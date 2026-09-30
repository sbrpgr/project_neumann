"""위험 묶음: 블라인드 정리, 문장 세기·자르기, Neumann 결과 → 위험 3개와 근거율."""

from __future__ import annotations

from eval import backtest_riskset as br
from tests.fixtures.loader import load_fixtures


def test_blind_text_strips_system_traces():
    raw = ("데이터 누출 위험 (R3.2) — 계획서 L12에서 무작위 분할만 적었다(L16–L17). 유사 논문 심사평 [ex_c5986bb2facc61b2] "
           "https://openreview.net/forum?id=abc 참고, 카드 2, researcharcade_hf:tj40W2HAKN (규칙: 심사평 4편 반복 지적)")
    out = br.blind_text(raw)
    for bad in ("R3", "L12", "L16", "ex_", "http", "카드 2", "researcharcade_hf", "규칙"):
        assert bad not in out, bad
    assert "데이터 누출 위험" in out and "무작위 분할만 적었다" in out
    assert br.blind_residue(out) == []
    assert br.blind_residue(raw)  # 검사기가 실제로 잡는다


def test_blind_text_keeps_ordinary_terms():
    s = "L2 정규화 계수 선택 근거가 없다. baseline 비교가 Transformer 하나뿐이다."
    assert br.blind_text(s) == s


def test_sentence_count_and_trim():
    assert br.count_sentences("비교 기준이 없다. 평가 지표도 정하지 않았다.") == 2
    assert br.count_sentences("e.g. 3.5배 느린 모델, i.e. GNN 기반 방법을 쓴다. 두 번째 문장이다.") == 2
    t, trimmed = br.trim_sentences("하나다. 둘이다. 셋이다.")
    assert t == "하나다. 둘이다." and trimmed is True
    assert br.trim_sentences("하나다.")[1] is False


def test_make_risk_and_validate():
    r = br.make_risk(1, "재현성 정보 부족 (R5)", "분할 절차가 없다. 시드도 없다. 코드도 없다.")
    assert r["title"] == "재현성 정보 부족" and r["trimmed"] and r["sentences"] == 2
    assert r["text"] == "재현성 정보 부족 — 분할 절차가 없다. 시드도 없다."
    rs = br.make_riskset(system="baseline_llm", condition="real", work_id="w", plan_work_id="w", plan_id="p",
                         risks=[r], status="ok", generator="astra", model="gpt-6-astra")
    probs = br.validate_riskset(rs)
    assert any("정확히 3" in p for p in probs)
    rs["risks"] = [r, br.make_risk(2, "a", "b."), br.make_risk(3, "c", "d.")]
    assert br.validate_riskset(rs) == []
    rs["risks"][1]["text"] = "Neumann 카드 3 https://x.org"
    assert br.validate_riskset(rs)


def test_riskset_from_premortem_evidence_rate():
    fx = load_fixtures()
    res = fx.premortem_result
    rs = br.riskset_from_premortem(res, condition="real", work_id="w", plan_work_id="w", plan_id="p", source_text_for=fx.source_text)
    assert rs["system"] == "neumann" and rs["n_risks"] == min(3, len(res.risk_cards))
    totals = sorted((c.score.total for c in res.risk_cards), reverse=True)[:3]
    assert [r["rank"] for r in rs["risks"]] == list(range(1, len(totals) + 1))
    assert all(r["evidence_ok"] for r in rs["risks"])  # fixture 근거는 원문 대조 통과
    assert all("R" + str(i) not in r["text"] for r in rs["risks"] for i in range(10))
    # 원문이 바뀌었거나 찾을 수 없으면 근거로 치지 않는다
    rs2 = br.riskset_from_premortem(res, condition="real", work_id="w", plan_work_id="w", plan_id="p",
                                    source_text_for=lambda ex: fx.source_text(ex).replace("a", "@"))
    assert not any(r["evidence_ok"] for r in rs2["risks"])
    rs3 = br.riskset_from_premortem(res, condition="real", work_id="w", plan_work_id="w", plan_id="p", source_text_for=lambda ex: None)
    assert not any(r["evidence_ok"] for r in rs3["risks"])
