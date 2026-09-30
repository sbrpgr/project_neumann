from __future__ import annotations

import json

from neumann.index.bm25 import BM25Index, tokenize
from neumann.index.sentences import excerpts_for_reviews
from neumann.index.taxonomy import classify, polarity_of, tag_counts, tag_excerpts, tag_text
from neumann.models import Generator, RiskCode

DOCS = {
    "a": "graph neural network ionic conductivity electrolyte battery",
    "b": "tumor segmentation magnetic resonance images uncertainty",
    "c": "protein backbone diffusion generation designability",
    "d": "graph network molecular property prediction equivariant",
}


def idx() -> BM25Index:
    return BM25Index.build(list(DOCS), list(DOCS.values()))


def test_tokenize_stopwords_and_plural():
    assert tokenize("The Networks are predicting properties of molecules") == ["network", "predicting", "property", "molecule"]
    assert "배터리" in tokenize("배터리 전해액 GNN")


def test_bm25_ranking_and_unit_range():
    s = idx().scores("ionic conductivity of battery electrolytes")
    assert max(range(4), key=lambda i: s[i]) == 0
    assert all(0.0 <= x <= 1.0 for x in s)
    assert s[1] == s[2] == 0.0


def test_bm25_korean_query_is_lexically_blind():
    s = idx().scores("배터리 전해액 이온전도도 예측")
    assert s == [0.0, 0.0, 0.0, 0.0]


def test_bm25_unrelated_query_scores_low():
    # 질의 최댓값 정규화가 아니므로 무관한 질의의 1등이 1.0이 되지 않는다
    s = idx().scores("simmer the onion soup with graph paper and salt for twenty minutes")
    assert max(s) < 0.3


def test_bm25_json_roundtrip():
    a = idx()
    b = BM25Index.from_json(json.loads(json.dumps(a.to_json())))
    q = "graph network property"
    assert a.scores(q) == b.scores(q)


def test_rule_tagger_known_sentences():
    assert RiskCode.R3 in tag_text("The random split likely leaks near-duplicate formulations between train and test.")
    assert RiskCode.R2 in tag_text("Only a single seed is reported, so error bars are missing.")
    assert RiskCode.R5 in tag_text("The code is not available, which hurts reproducibility.")
    assert RiskCode.R6 in tag_text("Novelty is limited: this was already proposed in prior work.")
    assert RiskCode.R8 in tag_text("Is the model physically plausible? No wet-lab validation is given.")
    assert RiskCode.R0 in tag_text("The writing is hard to follow in Section 3.")
    assert tag_text("We thank the authors for the response.") == []


def test_rule_tagger_rejection_cues():
    assert RiskCode.R3 not in tag_text("The model uses a leaky ReLU activation.")
    assert RiskCode.R3 not in tag_text("I have concerns about gradient leakage in federated settings.")
    assert RiskCode.R7 not in tag_text("The generalization error bound is standard.")


def test_rule_tagger_never_emits_r9():
    t = "The results look suspicious and the authors may have manipulated the figures; this could lead to retraction."
    assert RiskCode.R9 not in tag_text(t)


def test_tags_are_rule_generated_and_not_constant(corpus):
    _, reviews = corpus
    exs = excerpts_for_reviews(reviews)
    tags = tag_excerpts(exs)
    assert tags, "태그가 하나도 없다"
    assert all(t.generator == Generator.rule for t in tags)
    assert len(tag_counts(tags)) >= 2  # 상수 출력 금지(F6)
    ids = {ex.excerpt_id for ex in exs}
    assert all(t.excerpt_id in ids for t in tags)
    assert len({t.polarity for t in tags}) >= 2  # 극성도 상수가 아니다


def test_polarity_follows_sections():
    assert polarity_of("The ablation study is thorough.", "strengths") == "positive"
    assert polarity_of("The ablation study is missing.", "weaknesses") == "negative"
    assert polarity_of("The baselines are missing and results are unclear.") == "negative"
    assert polarity_of("The experiments are convincing and thorough.") == "positive"


def test_classify_scores_sorted():
    hits = classify("Error bars are missing and the ablation study is incomplete; the baselines are outdated.")
    assert hits and hits[0].risk_code == RiskCode.R2
    assert [h.score for h in hits] == sorted([h.score for h in hits], reverse=True)
