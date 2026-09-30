from __future__ import annotations

import pytest

from neumann.index.sentences import excerpts_for_review, excerpts_for_reviews, split_sentences
from neumann.models import Excerpt


def texts(t: str) -> list[str]:
    return [t[s:e] for s, e in split_sentences(t)]


def test_basic_and_abbreviations():
    t = "The method in Fig. 3 of Smith et al. (2020) is unclear, e.g. the loss. Please add seeds. Why?"
    assert texts(t) == [
        "The method in Fig. 3 of Smith et al. (2020) is unclear, e.g. the loss.",
        "Please add seeds.",
        "Why?",
    ]


def test_glued_enumeration_researcharcade_style():
    # ResearchArcade 심사평은 줄바꿈이 사라져 목록 번호가 앞 문장에 붙는다
    t = "1. Details are missing below.2. Certain parts contain errors.3. The baselines seem outdated."
    assert texts(t) == ["Details are missing below.", "Certain parts contain errors.", "The baselines seem outdated."]


def test_inline_numbering_and_bullets_glued():
    t = "1) Prior work: misses works (4., 5., 6.). 2) Theory: unclear. Equalized?- Error bars are missing in Table 2!- Ablation lacks details."
    assert texts(t) == [
        "Prior work: misses works (4., 5., 6.).",
        "Theory: unclear.",
        "Equalized?",
        "Error bars are missing in Table 2!",
        "Ablation lacks details.",
    ]


def test_glued_sentences_without_newlines():
    # 실데이터(ResearchArcade)에서 본 모양: 줄바꿈이 사라진 문장·목록
    t = (
        "adding up the weight.The authors propose four changes to a transformer:- instead of atoms it uses rows"
        "- the initial features are distances- The output is pooled.W1. The first- and second-order terms use "
        "torch.Tensor ops.Q2: why?"
    )
    assert texts(t) == [
        "adding up the weight.",
        "The authors propose four changes to a transformer:",
        "instead of atoms it uses rows",
        "the initial features are distances",
        "The output is pooled.",
        "W1. The first- and second-order terms use torch.Tensor ops.",
        "Q2: why?",
    ]


def test_newlines_headings_and_markers():
    t = "Strengths:\n- Good writing.\n\nWeaknesses:\n* No code. Why?\n(a) missing seeds\n  \n"
    assert texts(t) == ["Strengths:", "Good writing.", "Weaknesses:", "No code.", "Why?", "missing seeds"]


def test_decimals_and_section_numbers_not_split():
    t = "Accuracy improves by 0.5 points on v1.2 of the benchmark. Next sentence."
    assert texts(t) == ["Accuracy improves by 0.5 points on v1.2 of the benchmark.", "Next sentence."]


def test_offsets_exact_and_trimmed():
    t = "  \n- First point.  Second point?\n\n3. Third point   "
    for s, e in split_sentences(t):
        seg = t[s:e]
        assert seg == seg.strip() and seg
        assert not seg.startswith(("-", "3."))
    assert texts(t) == ["First point.", "Second point?", "Third point"]


def test_empty_and_symbol_only():
    assert split_sentences("") == []
    assert split_sentences("\n\n  --- \n***\n") == []


def test_long_sentence_split_on_semicolon():
    part = "the model is evaluated on a narrow benchmark with a single configuration " * 6
    t = f"{part}; {part}; {part}."
    spans = split_sentences(t)
    assert len(spans) >= 2
    assert "".join(t[s:e] for s, e in spans).replace(" ", "") == t.replace(" ", "")


def test_excerpts_exact_and_stable(corpus):
    _, reviews = corpus
    r = reviews[0]
    a = excerpts_for_review(r)
    b = excerpts_for_review(r)
    assert [x.excerpt_id for x in a] == [x.excerpt_id for x in b]  # 같은 입력 → 같은 id
    assert len({x.excerpt_id for x in a}) == len(a)
    for ex in a:
        assert r.text[ex.start : ex.end] == ex.text
        assert ex.verify_against(r.text)
        assert ex.source_kind == "review" and ex.source_id == r.review_id
        assert ex.source_url == r.url
        assert ex.excerpt_id == Excerpt.make_id("review", r.review_id, ex.start, ex.end)


def test_excerpt_tampering_detected(corpus):
    _, reviews = corpus
    r = reviews[0]
    ex = excerpts_for_review(r)[3]
    assert not ex.verify_against(r.text.replace(ex.text, ex.text.upper()))
    with pytest.raises(ValueError):
        Excerpt(**{**ex.model_dump(), "text": ex.text[:-1] + "!"})


def test_order_by_review_then_offset(corpus):
    _, reviews = corpus
    bat = [r for r in reviews if r.work_id == "fake:bat-1"]
    exs = excerpts_for_reviews(list(reversed(bat)))
    ids = [ex.source_id for ex in exs]
    assert ids == sorted(ids, key=lambda i: (i != "rev-bat-1-0", i))  # 작성 시각 순서: -0 먼저
    starts = [ex.start for ex in exs if ex.source_id == "rev-bat-1-0"]
    assert starts == sorted(starts)
