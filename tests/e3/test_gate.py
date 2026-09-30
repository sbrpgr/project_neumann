"""근거 게이트(E3-L1a) 단위 테스트. fixture 결과(tests/fixtures/premortem_result.json)에 대고 문장을 검사한다."""

from __future__ import annotations

import pytest

from neumann.analyze import gate as g
from neumann.analyze.gate import Draft, extract_numbers, find_quotes, gate_sentences, verify_expected_review
from tests.fixtures.loader import load_fixtures

LEAK = "card-fx-leak"
SEED = "card-fx-seed"
EX_SPLIT = "ex_c5986bb2facc61b2"  # "The paper reports a random 80/10/10 split of the molecules."
EX_LEAK = "ex_110f92f3599151f1"  # "Random splits are known to leak near-duplicate scaffolds ..."
EX_BARS = "ex_4b76d98627bb3f0c"  # "Without error bars across seeds it is impossible to tell whether the 3% improvement is real."


@pytest.fixture(scope="module")
def fx():
    return load_fixtures()


@pytest.fixture(scope="module")
def result(fx):
    return fx.premortem_result


def one(result, **kw):
    base = {"section": "weakness", "excerpt_ids": [EX_LEAK], "card_ids": [LEAK], "plan_lines": [16, 17]}
    base.update(kw)
    return gate_sentences([base], result)


def reason_of(report):
    assert len(report.dropped) == 1, report.passed
    return report.dropped[0].reason


# ── 통과 ─────────────────────────────────────────────────────────────────


def test_grounded_sentence_passes(result):
    rep = one(result, text="무작위 분할은 유사 조성 중복을 통해 시험 성능을 과대평가할 수 있다 (16–17행).")
    assert not rep.dropped
    s = rep.passed[0]
    assert s["c"] == [EX_LEAK] and s["cards"] == [LEAK] and s["plan_lines"] == [16, 17]
    assert s["quotes"] == []


def test_cards_are_derived_from_cited_excerpts(result):
    rep = one(result, text="무작위 분할은 누출 위험이 있다.", card_ids=[])
    assert rep.passed[0]["cards"] == [LEAK]


# ── 근거 없는 문장 · 없는 id ─────────────────────────────────────────────


def test_sentence_without_evidence_is_dropped(result):
    rep = one(result, text="대부분의 전해질 연구가 이 문제를 겪는다.", excerpt_ids=[], card_ids=[])
    assert reason_of(rep) == g.MISSING_CITATION


def test_card_only_citation_is_not_enough(result):
    rep = one(result, text="분할 방식이 문제다.", excerpt_ids=[], card_ids=[LEAK])
    assert reason_of(rep) == g.MISSING_CITATION


def test_unknown_excerpt_id_is_dropped(result):
    rep = one(result, text="분할 방식이 문제다.", excerpt_ids=[EX_LEAK, "ex_0000000000000000"])
    assert reason_of(rep) == g.UNKNOWN_EXCERPT


def test_unknown_card_id_is_dropped(result):
    rep = one(result, text="분할 방식이 문제다.", card_ids=["card-does-not-exist"])
    assert reason_of(rep) == g.UNKNOWN_CARD


def test_excerpt_from_other_card_is_dropped(result):
    rep = one(result, text="분할 방식이 문제다.", excerpt_ids=[EX_BARS], card_ids=[LEAK])
    assert reason_of(rep) == g.EXCERPT_CARD_MISMATCH


def test_excerpt_outside_every_card_is_dropped_without_card_ids(result):
    """E3-L1e: 카드를 달지 않아도 인용한 발췌는 어느 위험카드의 근거여야 한다(카드에서 빠진 발췌는 근거가 아니다)."""
    orphan = result.evidence[0].model_copy(update={"excerpt_id": "ex_orphan000000000"})
    res = result.model_copy(update={"evidence": [*result.evidence, orphan]})
    rep = gate_sentences(
        [{"section": "weakness", "text": "분할 방식이 문제다.", "excerpt_ids": ["ex_orphan000000000"], "card_ids": []}],
        res,
    )
    assert reason_of(rep) == g.EXCERPT_CARD_MISMATCH and "어느 위험카드" in rep.dropped[0].detail


def test_evidence_link_problem_is_the_shared_check(result):
    """심사평 문장·체크리스트 항목·2차 검증이 같이 쓰는 근거 연결 검사."""
    idx = g.EvidenceIndex(result)
    assert g.evidence_link_problem([EX_LEAK], [LEAK], idx) == (None, "")
    assert g.evidence_link_problem([], [LEAK], idx)[0] == g.MISSING_CITATION
    assert g.evidence_link_problem(["ex_none"], [LEAK], idx)[0] == g.UNKNOWN_EXCERPT
    assert g.evidence_link_problem([None], [LEAK], idx)[0] == g.UNKNOWN_EXCERPT  # 형식 오류도 없는 id
    assert g.evidence_link_problem([EX_BARS], [LEAK], idx)[0] == g.EXCERPT_CARD_MISMATCH  # 다른 카드의 근거
    assert g.evidence_link_problem([EX_LEAK], ["card-x"], idx)[0] == g.UNKNOWN_CARD
    assert g.evidence_link_problem([EX_BARS], [], idx) == (None, "")  # 카드 없으면 어느 카드의 근거면 된다
    assert set(g.NO_EVIDENCE_REASONS) == {g.MISSING_CITATION, g.UNKNOWN_EXCERPT, g.UNKNOWN_CARD, g.EXCERPT_CARD_MISMATCH}


def test_unknown_plan_line_is_dropped(result):
    rep = one(result, text="분할 방식이 문제다.", plan_lines=[16, 999])
    assert reason_of(rep) == g.UNKNOWN_PLAN_LINE


# ── 따옴표 인용 대조 ─────────────────────────────────────────────────────


def test_exact_quote_passes_and_points_to_source_offsets(fx, result):
    ex = fx.excerpt(EX_LEAK)
    rep = one(result, text=f"심사평은 “{ex.text}” 라고 지적했다.")
    assert not rep.dropped
    (q,) = rep.passed[0]["quotes"]
    assert q["excerpt_id"] == EX_LEAK and q["text"] == ex.text
    src = fx.source_text(ex)
    assert src[q["start"] : q["end"]] == q["text"]


def test_long_substring_quote_passes(fx, result):
    ex = fx.excerpt(EX_LEAK)
    part = "leak near-duplicate scaffolds between train and test"
    assert part in ex.text and len(part) >= g.MIN_QUOTE_LEN
    rep = one(result, text=f'리뷰어는 "{part}"를 우려했다.')
    assert not rep.dropped
    q = rep.passed[0]["quotes"][0]
    assert fx.source_text(ex)[q["start"] : q["end"]] == part


def test_short_partial_quote_is_dropped(result):
    rep = one(result, text='리뷰어는 "near-duplicate"를 우려했다.')  # 부분 문자열이지만 20자 미만
    assert reason_of(rep) == g.QUOTE_MISMATCH


def test_altered_quote_is_dropped(result):
    rep = one(result, text='리뷰어는 "Random splits are known to leak near-identical scaffolds"라고 썼다.')
    assert reason_of(rep) == g.QUOTE_MISMATCH


def test_quote_from_uncited_excerpt_is_dropped(fx, result):
    other = fx.excerpt(EX_SPLIT).text  # 같은 카드의 다른 근거지만 이 문장이 인용하지 않았다
    rep = one(result, text=f"“{other}”", excerpt_ids=[EX_LEAK])
    assert reason_of(rep) == g.QUOTE_MISMATCH


def test_paraphrase_in_korean_quotes_is_dropped(result):
    rep = one(result, text="이 설계는 '비교 대상 부족' 지적에 그대로 노출된다.")
    assert reason_of(rep) == g.QUOTE_MISMATCH


@pytest.mark.parametrize("pair", [("《", "》"), ("＂", "＂")])
def test_double_angle_and_fullwidth_quotes_are_checked(result, pair):
    o, c = pair
    rep = one(result, text=f"리뷰어는 {o}random splits always leak everything{c}이라고 했다.")
    assert reason_of(rep) == g.QUOTE_MISMATCH


def test_unbalanced_quote_is_dropped(result):
    rep = one(result, text='리뷰어는 "Random splits are known to leak 라고 썼다.')
    assert reason_of(rep) == g.QUOTE_MISMATCH


def test_quote_of_cited_plan_line_passes(fx, result):
    line16 = result.plan.line(16)
    rep = one(result, text=f"계획서는 “{line16}”라고 적었다.")
    assert not rep.dropped
    q = rep.passed[0]["quotes"][0]
    assert q["plan_line"] == 16 and line16[q["start"] : q["end"]] == q["text"]


def test_apostrophes_are_not_quotes():
    spans, problems = find_quotes("The model's results and the reviewers' concerns, authors’ reply")
    assert spans == [] and problems == []


# ── 숫자 ─────────────────────────────────────────────────────────────────


def test_fabricated_number_is_dropped(result):
    rep = one(result, text="이 설계로는 R² 0.9 이상을 달성하기 어렵다.")
    assert reason_of(rep) == g.FABRICATED_NUMBER


def test_numbers_from_plan_evidence_and_counts_pass(result):
    texts = [
        "약 12,000건의 데이터를 80/10/10으로 무작위 분할한다 (16–17행).",  # 계획서 수치 + 인용 줄 번호
        "유사 연구 2편의 심사에서 같은 지적이 나왔다.",  # 카드 works 수
        "유사 연구 3편을 검토했다.",  # 결과의 유사 연구 수
    ]
    rep = gate_sentences(
        [{"section": "weakness", "text": t, "excerpt_ids": [EX_LEAK], "card_ids": [LEAK], "plan_lines": [16, 17]} for t in texts],
        result,
    )
    assert not rep.dropped, [d.as_dict() for d in rep.dropped]


def test_number_inside_verified_quote_is_allowed(fx, result):
    ex = fx.excerpt(EX_BARS)
    rep = gate_sentences(
        [{"section": "weakness", "text": f"“{ex.text}”", "excerpt_ids": [EX_BARS], "card_ids": [SEED], "plan_lines": []}],
        result,
    )
    assert not rep.dropped


@pytest.mark.parametrize(
    "text",
    [
        "이 설계는 성능을 5% 개선하는 데 그칠 것이다.",  # 5는 계획서 제목 줄(## 5. 기대 성과)에만 있다
        "기준 모델보다 3배 느릴 수 있다.",  # 3은 유사 연구 수(집계값)지만 개수 단위가 아니다
        "1단계부터 누출 위험이 있다.",  # 1은 제목 줄 번호뿐
        "유사 연구 7편에서 같은 지적이 나왔다.",  # 7은 어떤 집계값도 아니다
    ],
)
def test_header_numbers_and_unitless_counts_are_not_facts(result, text):
    rep = one(result, text=text, plan_lines=[])
    assert reason_of(rep) == g.FABRICATED_NUMBER


def test_counts_need_a_count_unit(result):
    rep = gate_sentences(
        [
            {"section": "weakness", "text": t, "excerpt_ids": [EX_LEAK], "card_ids": [LEAK], "plan_lines": []}
            for t in ("유사 연구 3편에서 같은 지적이 나왔다.", "근거 4건이 같은 문제를 가리킨다.", "카드 2장이 이 위험을 다룬다.")
        ],
        result,
    )
    assert not rep.dropped, [d.as_dict() for d in rep.dropped]


def test_plan_fact_numbers_skip_headers_and_enumeration():
    from neumann.models import PlanDocument

    plan = PlanDocument.from_text("# 3. 제목\n1. 데이터 250건을 쓴다\n(2) 시드 5개\n- 7 fold\n## 9 결론\n  4) 기준 0.8", "s")
    assert g.plan_fact_numbers(plan) == {"250", "5", "7", "0.8"}


def test_extract_numbers_ignores_names_and_handles_thousands():
    assert extract_numbers("R2 bge-m3 GPT-4 12,000 0.90 16,17 3%") == ["4", "12000", "0.9", "16", "17", "3"]


# ── 기타 ─────────────────────────────────────────────────────────────────


def test_pii_sentence_is_dropped_and_redacted_in_log(result):
    rep = one(result, text="문의는 someone@example.com 으로.")
    assert reason_of(rep) == g.PII
    assert "someone@example.com" not in rep.dropped[0].text


def test_malformed_items_are_dropped(result):
    rep = gate_sentences(
        [
            {"section": "weakness", "text": 3, "excerpt_ids": [EX_LEAK]},
            {"section": "nope", "text": "x", "excerpt_ids": [EX_LEAK]},
            {"section": "request", "text": "x", "excerpt_ids": "ex"},
            "just a string",
            {"section": "weakness", "text": "   ", "excerpt_ids": [EX_LEAK]},
        ],
        result,
    )
    assert rep.passed == []
    assert [d.reason for d in rep.dropped] == [g.MALFORMED] * 4 + [g.EMPTY_TEXT]


def test_duplicate_is_dropped_only_once(result):
    d = {"section": "weakness", "text": "분할 방식이 문제다.", "excerpt_ids": [EX_LEAK], "card_ids": [], "plan_lines": []}
    rep = gate_sentences([d, dict(d)], result)
    assert len(rep.passed) == 1 and [x.reason for x in rep.dropped] == [g.DUPLICATE]


def test_only_failing_sentences_are_removed_and_audit_counts(result):
    good = Draft("weakness", "무작위 분할은 누출 위험이 있다.", (EX_LEAK,), (LEAK,), (16,))
    bad = Draft("weakness", "대부분의 연구가 이 문제를 겪는다.")
    same_text_other_section = Draft("request", good.text, (EX_LEAK,))
    rep = gate_sentences([good, bad, same_text_other_section], result)
    audit = rep.audit()
    assert audit["gen"] == 3 and audit["pass"] == 2 and audit["drop"] == 1
    assert audit["no_evidence"] == 1  # E3-L1e: 근거 연결 실패로 뺀 수
    assert set(g.NO_EVIDENCE_FAMILY) == {*g.NO_EVIDENCE_REASONS, g.MALFORMED}  # 형식 오류도 같은 계열로 센다
    assert g.count_no_evidence([{"reason": g.MALFORMED}, {"reason": g.FABRICATED_NUMBER}, {"reason": g.DUPLICATE}]) == 1
    assert audit["gen"] == audit["pass"] + audit["drop"]
    assert audit["dropped"] == [[g.MISSING_CITATION, "대부분의 연구가 이 문제를 겪는다."]]
    assert audit["linked_rate"] == 1.0 and audit["gate"] == g.GATE_VERSION


def test_verify_expected_review_rechecks_assembled_dict(result):
    review = {
        "weakness": [{"t": "무작위 분할은 누출 위험이 있다.", "c": [EX_LEAK], "cards": [LEAK], "plan_lines": [16]}],
        "request": [{"t": "분할을 바꿀 것.", "c": ["ex_forged00000000"], "cards": [LEAK], "plan_lines": []}],
        "strength": [],
    }
    rep = verify_expected_review(review, result)
    assert len(rep.passed) == 1 and [d.reason for d in rep.dropped] == [g.UNKNOWN_EXCERPT]
