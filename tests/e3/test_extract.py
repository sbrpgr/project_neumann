"""astra ② 지적 추출: 인용은 코드가 원문을 잘라 만들고, 범위 밖·빈 구간·enum 밖은 버린다."""

from __future__ import annotations

import threading

from neumann.analyze import extract
from neumann.analyze.backend import split_sentences
from neumann.analyze.extract import extract_issues, validate_issues
from neumann.analyze.rules import keyword_tagger
from neumann.llm import LLMCall, LLMResult, MockProvider
from neumann.models import Excerpt, RiskCode

REVIEW = (
    "The random split leaks near-duplicate molecules into the test set. "
    "The paper is well written. "
    "Baselines are weak and no error bars are reported."
)
URL = "https://example.org/fixture/review1"


def _excerpts() -> list[Excerpt]:
    spans = split_sentences(REVIEW)
    assert len(spans) == 3
    return [Excerpt.from_source(REVIEW, s, e, source_kind="review", source_id="rv1", source_url=URL) for s, e in spans]


def _issue(ex_id, start=None, end=None, code="R2", pol="negative", conf=0.9):
    return {"excerpt_id": ex_id, "start": start, "end": end, "risk_code": code, "polarity": pol, "confidence": conf}


def test_fixture_excerpts_are_source_slices():
    for ex in _excerpts():
        assert REVIEW[ex.start : ex.end] == ex.text and ex.verify_against(REVIEW)


def test_whole_sentence_issue_quotes_original_text():
    exs = _excerpts()
    by_id = {e.excerpt_id: e for e in exs}
    kept, drops, _ = validate_issues([_issue(exs[0].excerpt_id, code="R3")], by_id, "w1", generator="astra", model="m")
    assert not drops and len(kept) == 1
    iss = kept[0]
    assert iss.quote == exs[0].text and iss.whole_sentence
    ev = iss.evidence_excerpt()
    assert ev.excerpt_id == exs[0].excerpt_id and ev.verify_against(REVIEW)


def test_sub_span_offset_zero_is_kept_and_verifies_against_source():
    """오프셋 0은 정상값이다(falsy 검사 금지). 하위 구간 인용은 원문 절대 오프셋으로 대조된다."""
    exs = _excerpts()
    by_id = {e.excerpt_id: e for e in exs}
    third = exs[2]
    # "Baselines are weak" = 0..18, 뒤쪽 구간은 "no"의 가운데 글자에서 시작 → 단어 경계로 넓힘
    mid = third.text.index("o error")
    stop = third.text.index(".")
    kept, drops, snapped = validate_issues(
        [_issue(third.excerpt_id, 0, 18), _issue(third.excerpt_id, mid, stop)], by_id, "w1", generator="astra", model="m"
    )
    assert not drops and len(kept) == 2 and snapped == 1
    assert kept[0].rel_start == 0 and kept[0].quote == "Baselines are weak"
    assert kept[1].quote == "no error bars are reported"
    for iss in kept:
        ev = iss.evidence_excerpt()
        assert REVIEW[ev.start : ev.end] == ev.text == iss.quote
        assert ev.verify_against(REVIEW)
        assert ev.excerpt_id != third.excerpt_id


def test_invalid_issues_are_dropped_with_reasons():
    exs = _excerpts()
    by_id = {e.excerpt_id: e for e in exs}
    eid = exs[0].excerpt_id
    n = len(exs[0].text)
    raw = [
        _issue(eid, 0, n + 5),  # 범위 밖
        _issue(eid, 10, 10),  # start == end → 범위 오류
        _issue(eid, -1, 5),  # 음수
        _issue(eid, 10, 11),  # 공백 한 칸 → 빈 구간
        _issue(eid, 5, None),  # 한쪽만
        _issue(eid, code="R10"),  # enum 밖
        _issue(eid, code="R9"),  # 심사평에서 R9 금지
        _issue(eid, pol="angry"),  # 극성 enum 밖
        _issue(eid, conf=1.5),  # 신뢰도 범위 밖
        _issue("ex_nope"),  # 모르는 id
        _issue(eid, code="R3"),
        _issue(eid, code="R3"),  # 중복
    ]
    kept, drops, _ = validate_issues(raw, by_id, "w1", generator="astra", model="m")
    assert len(kept) == 1 and kept[0].risk_code is RiskCode.R3
    assert drops == {
        "out_of_range": 3, "empty_span": 1, "half_span": 1, "bad_enum_risk_code": 1, "r9_from_review": 1,
        "bad_enum_polarity": 1, "bad_confidence": 1, "unknown_excerpt_id": 1, "duplicate": 1,
    }


def test_extract_uses_aliases_and_counts_drop_rate():
    exs = _excerpts()

    def responder(call: LLMCall):
        ids = [s["id"] for s in call.payload["sentences"]]
        assert ids == ["s1", "s2", "s3"]  # 호출 안에서는 짧은 별칭
        return {"issues": [_issue("s1", code="R3"), _issue("s3", 0, 999), _issue("s3")]}

    llm = MockProvider({"extract_issues": responder})
    res = extract_issues([("w1", "T", exs)], llm, tagger=keyword_tagger, cache_dir=None)
    assert [i.excerpt.excerpt_id for i in res.issues] == [exs[0].excerpt_id, exs[2].excerpt_id]
    assert all(i.generator == "mock" for i in res.issues)
    assert res.n_raw == 3 and res.drops == {"out_of_range": 1}
    assert abs(res.drop_rate() - 1 / 3) < 1e-9
    assert res.counts()["findings_kept"] == 2


def test_llm_failure_falls_back_to_rule_tags_per_batch():
    exs = _excerpts()
    llm = MockProvider(fail={"extract_issues": "timeout"})
    res = extract_issues([("w1", "T", exs), ("w2", "T2", exs)], llm, tagger=keyword_tagger, cache_dir=None)
    assert len(res.fallback_batches) == 2
    assert res.issues and all(i.generator == "rule" for i in res.issues)
    assert {i.risk_code for i in res.issues} >= {RiskCode.R2, RiskCode.R3}
    assert "timeout" in res.fallback_batches[0].fallback_reason


def test_batches_and_partial_failure():
    exs = _excerpts()
    calls = {"n": 0}

    def responder(call: LLMCall):
        calls["n"] += 1
        return {"issues": [_issue(s["id"]) for s in call.payload["sentences"]]}

    llm = MockProvider({"extract_issues": responder}, scripted={"extract_issues": ["{broken"]})
    res = extract_issues([("w1", "T", exs)], llm, tagger=keyword_tagger, cache_dir=None, batch_size=2, parallel=1)
    assert len(res.batches) == 2
    assert len(res.fallback_batches) == 1 and "json_invalid" in res.fallback_batches[0].fallback_reason
    assert calls["n"] == 1


def test_stage_deadline_falls_back():
    exs = _excerpts()
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()

    class Slow:
        name, model = "mock", "slow"

        def complete_json(self, call):
            entered.set()
            try:
                assert release.wait(20), "시험이 지연 호출을 해제하지 않았다"
                return LLMResult(ok=True, data={"issues": []}, provider="mock", model="slow", task=call.task)
            finally:
                returned.set()

    try:
        res = extract_issues([("w1", "T", exs)], Slow(), tagger=keyword_tagger, cache_dir=None, stage_timeout_s=0.2)
        assert entered.is_set(), "추출 호출 자체가 시작되지 않았다"
        assert not returned.is_set(), "상한 뒤에도 미완료 호출을 기다렸다"
    finally:
        release.set()
        assert returned.wait(20), "시험의 지연 호출이 정리되지 않았다"
    assert len(res.fallback_batches) == 1 and "상한" in res.fallback_batches[0].fallback_reason


def test_cache_by_review_hash(tmp_path):
    exs = _excerpts()

    class FakeOpenAI(MockProvider):
        name = "openai"

    llm = FakeOpenAI({"extract_issues": lambda c: {"issues": [_issue("s1", code="R3")]}}, model="gpt-6-astra")
    r1 = extract_issues([("w1", "T", exs)], llm, tagger=keyword_tagger, cache_dir=tmp_path)
    assert len(llm.calls) == 1 and not r1.batches[0].cached
    assert len(list(tmp_path.glob("*.json"))) == 1
    r2 = extract_issues([("w1", "T", exs)], llm, tagger=keyword_tagger, cache_dir=tmp_path)
    assert len(llm.calls) == 1 and r2.batches[0].cached
    assert [i.quote for i in r2.issues] == [i.quote for i in r1.issues]
    assert r2.issues[0].generator == "astra"
    # 문장이 바뀌면 키가 바뀐다
    other = [Excerpt.from_source("Totally different.", 0, 18, source_kind="review", source_id="rv2", source_url=URL)]
    assert extract.cache_key("gpt-6-astra", "low", other) != extract.cache_key("gpt-6-astra", "low", exs)
