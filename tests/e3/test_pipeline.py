"""run_premortem 종단(mock·fixture): 인용 원문 대조, 강등 기록, 카드 0장 사유, 분야별로 다른 결과, 계약 통과."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from neumann.analyze.backend import FixtureBackend
from neumann.llm import MockProvider
from neumann.analyze.mock_responders import default_responders
from neumann.models import ReviewEvent
from neumann.pipeline import FITNESS_MISSING, MOCK_NOTICE, mask_extra_pii, run_premortem, safe_text
from tests.e3.corpus import PLAN_BATTERY, PLAN_IMAGING, RECIPE, build, build_backend

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "premortem_response.schema.json").read_text(encoding="utf-8")
)
# E3-L1w: 적합성(fitness)과 v1 단계(예상 심사평·체크리스트·2차 검증)가 붙었다.
STAGES = ["plan_normalize", "fitness", "query_axes", "search", "extract_issues", "synthesize_cards", "verify_evidence",
          "expected_review", "checklist", "semantic_validate"]


def _ok(stage) -> bool:
    """정상 단계. 적합성 모듈(E3-L1c)이 아직 없으면 fitness만 skipped로 남는 것을 허용한다."""
    return stage.state == "ok" or (stage.stage == "fitness" and stage.state == "skipped" and stage.detail == FITNESS_MISSING)


def _run(plan: str, *, provider: str = "mock", backend=None, llm=None, k: int = 10):
    return run_premortem(plan, provider=provider, llm=llm, backend=backend or build_backend(), cache_dir=None, k=k)


def _assert_all_quotes_verify(result, backend: FixtureBackend):
    reviews = {r.review_id: r.text for rs in backend.reviews.values() for r in rs}
    ev = {e.excerpt_id: e for e in result.evidence}
    assert ev, "근거가 없다"
    for card in result.risk_cards:
        assert len(card.evidence) >= 3 and len(set(card.works)) >= 2
        for x in card.evidence:
            e = ev[x]
            src = reviews[e.source_id]
            assert src[e.start : e.end] == e.text  # 글자 단위 원문 대조
            assert e.verify_against(src)
            assert e.source_url.startswith("https://")


def _state(result, name):
    return next(s for s in result.stages if s.stage == name)


def test_mock_end_to_end_cards_and_contract():
    be = build_backend()
    r = _run(PLAN_BATTERY, backend=be)
    # mock 결과는 단계가 모두 ok여도 status를 ok로 두지 않는다(SEC-1 S-05)
    assert r.status == "degraded" and MOCK_NOTICE in r.notices
    assert [s.stage for s in r.stages] == STAGES
    assert all(_ok(s) for s in r.stages)
    assert len(r.risk_cards) >= 1
    assert all(c.generator.value == "mock" for c in r.risk_cards)  # mock 결과를 astra라고 쓰지 않는다
    _assert_all_quotes_verify(r, be)
    assert r.verification["linkage_rate"] == 1.0
    assert r.verification["findings_total"] >= r.verification["findings_kept"] > 0
    assert "findings_dropped" in r.verification and "findings_drop_reasons" in r.verification
    assert set(r.manifest["timings_s"]) == set(STAGES)
    jsonschema.validate(r.model_dump(mode="json"), CONTRACT)


def test_e5_linkage_checker_passes_and_reads_drop_rate():
    """E5-L0 근거 연결 검사기(eval.linkage)로 결과를 다시 잰다: 연결률 1.0, 폐기율을 verification에서 읽는다."""
    from eval.linkage import check_result

    be = build_backend()
    r = _run(PLAN_BATTERY, backend=be)
    reviews = {rv.review_id: rv.text for rs in be.reviews.values() for rv in rs}
    rep = check_result(r, reviews)
    assert rep.passed and rep.linkage_rate == 1.0 and rep.card_pass_rate == 1.0
    assert rep.drop.available and rep.drop.source == "verification"
    assert rep.drop.findings_total == r.verification["findings_total"]
    # JSON으로 오간 결과도 같다
    assert check_result(r.model_dump(mode="json"), reviews).passed


def test_provider_off_gives_rule_cards_and_marks_degradation():
    be = build_backend()
    r = _run(PLAN_BATTERY, provider="off", backend=be)
    assert r.status == "degraded"
    for name in ("query_axes", "extract_issues", "synthesize_cards"):
        st = _state(r, name)
        assert st.state == "degraded" and "비상 규칙 경로" in st.detail and "disabled" in st.detail
    assert r.risk_cards and all(c.generator.value == "rule" for c in r.risk_cards)
    _assert_all_quotes_verify(r, be)
    assert any("degraded" in n for n in r.notices)
    assert r.risk_synthesis["generator"] == "rule"
    jsonschema.validate(r.model_dump(mode="json"), CONTRACT)


def test_forced_failure_only_in_extraction_is_recorded_per_stage():
    be = build_backend()
    llm = MockProvider(default_responders(), fail={"extract_issues": "timeout"})
    r = _run(PLAN_BATTERY, llm=llm, backend=be)
    assert _state(r, "query_axes").state == "ok"
    assert _state(r, "extract_issues").state == "degraded"
    assert _state(r, "synthesize_cards").state == "ok"
    assert r.status == "degraded"
    assert r.risk_cards and all(c.generator.value == "mock" for c in r.risk_cards)
    # 근거 태그는 규칙에서 왔다고 정직하게 남는다
    assert r.risk_synthesis["tags"] and all(t["generator"] == "rule" for t in r.risk_synthesis["tags"])


def test_recipe_gives_zero_cards_with_reason():
    r = _run(RECIPE)
    assert r.risk_cards == []
    reason = r.risk_synthesis["no_card_reason"]
    assert "연구계획서가 아니다" in reason and "mock 판단" in reason
    assert any("위험카드 0장" in n for n in r.notices)
    assert _state(r, "extract_issues").state == "skipped"
    assert r.plan_checks["suitability"]["is_research_plan"] is False
    jsonschema.validate(r.model_dump(mode="json"), CONTRACT)


def test_recipe_zero_cards_on_emergency_path_too():
    r = _run(RECIPE, provider="off")
    assert r.risk_cards == [] and "규칙" in r.risk_synthesis["no_card_reason"]


def test_two_domains_give_different_similar_works_and_cards():
    be = build_backend()
    a = _run(PLAN_BATTERY, backend=be, k=3)
    b = _run(PLAN_IMAGING, backend=be, k=3)
    wa = [w.work_id for w in a.similar_works]
    wb = [w.work_id for w in b.similar_works]
    assert wa and wb and set(wa) != set(wb)
    # 가장 비슷한 논문과 과반이 각자 자기 분야다(A: 소재·화학, B: 의료영상)
    assert wa[0].startswith("fixture:A") and wb[0].startswith("fixture:B")
    assert sum(w.startswith("fixture:A") for w in wa) > len(wa) / 2
    assert sum(w.startswith("fixture:B") for w in wb) > len(wb) / 2
    ea = {x for c in a.risk_cards for x in c.evidence}
    eb = {x for c in b.risk_cards for x in c.evidence}
    assert a.risk_cards and b.risk_cards and ea != eb
    ta = [(c.risk_code, tuple(c.why_applies.plan_lines)) for c in a.risk_cards]
    tb = [(c.risk_code, tuple(c.why_applies.plan_lines)) for c in b.risk_cards]
    assert ta != tb


def test_tampered_source_evidence_is_removed():
    """원문이 인용과 다르면(조작) 그 근거는 빠지고, 카드 불변식이 깨지면 카드도 빠진다. 강등으로 남긴다."""
    works, reviews = build()
    target = "fixture:A1:r1"
    tampered = [
        r.model_copy(update={"text": r.text.replace("random split", "random  split")}) if r.review_id == target else r
        for r in reviews
    ]

    class TamperBackend(FixtureBackend):
        def get_reviews(self, work_id):
            return [r for r in tampered if r.work_id == work_id]

    be = TamperBackend(works, reviews)  # 발췌는 원래 원문에서, 대조는 조작된 원문으로
    r = _run(PLAN_BATTERY, backend=be)
    st = _state(r, "verify_evidence")
    assert st.state == "degraded" and st.counts["quotes_verified"] < st.counts["quotes_total"]
    assert all(e.source_id != target or "random split" not in e.text for e in r.evidence)
    good = {rv.review_id: rv.text for rv in tampered}
    for e in r.evidence:
        assert e.verify_against(good[e.source_id])


def test_search_failure_does_not_crash():
    class Broken(FixtureBackend):
        def search(self, *a, **kw):
            raise RuntimeError("index corrupted")

    works, reviews = build()
    r = _run(PLAN_BATTERY, backend=Broken(works, reviews))
    assert r.risk_cards == [] and r.status == "degraded"
    st = _state(r, "search")
    assert st.state == "error" and "RuntimeError" in st.detail
    assert "index corrupted" not in st.detail  # 예외 원문은 응답에 싣지 않는다(SEC-1 S-04)
    assert r.risk_synthesis["no_card_reason"]


def test_provider_that_raises_does_not_crash():
    class Exploding:
        name, model = "openai", "gpt-6-astra"

        def complete_json(self, call):
            raise RuntimeError("provider bug")

    r = _run(PLAN_BATTERY, llm=Exploding())
    assert r.risk_cards == [] and r.status == "degraded"
    assert _state(r, "query_axes").state == "error"
    assert "검색어" in r.risk_synthesis["no_card_reason"]


def test_missing_index_backend_gives_reason(monkeypatch):
    import neumann.analyze.backend as bm

    def boom(*a, **kw):
        raise FileNotFoundError("data/index 없음")

    monkeypatch.setattr(bm, "make_backend", boom)
    r = run_premortem(PLAN_BATTERY, provider="mock", cache_dir=None)
    assert r.risk_cards == [] and "색인" in r.risk_synthesis["no_card_reason"]
    assert _state(r, "search").state == "skipped"


def test_empty_input():
    r = _run("   \n  ")
    assert r.risk_cards == [] and r.status == "degraded"
    assert "비어" in r.risk_synthesis["no_card_reason"]


def test_no_reviews_gives_reason():
    works, _ = build()
    r = _run(PLAN_BATTERY, backend=FixtureBackend(works, []))
    assert r.risk_cards == [] and "심사평" in r.risk_synthesis["no_card_reason"]


def test_pii_is_masked_in_plan():
    text = PLAN_BATTERY + "\n연락처: kim.researcher@example.ac.kr, 010-1234-5678\n"
    r = _run(text)
    joined = r.plan.text
    assert "example.ac.kr" not in joined and "010-1234-5678" not in joined
    assert "[EMAIL]" in joined and "[PHONE]" in joined
    assert mask_extra_pii("80/10/10 split, 12,000건")[1] == 0


def test_llm_never_writes_quotes():
    """모델 응답에 인용 문자열을 넣을 칸이 없고, 카드 근거 텍스트는 원문에서 잘린 것뿐이다."""
    captured = []
    responders = default_responders()
    orig = responders["synthesize_cards"]
    responders["synthesize_cards"] = lambda c: captured.append(c) or orig(c)
    be = build_backend()
    r = _run(PLAN_BATTERY, llm=MockProvider(responders), backend=be)
    assert captured and r.risk_cards
    all_review_text = " ".join(rv.text for rs in be.reviews.values() for rv in rs)
    for e in r.evidence:
        assert e.text in all_review_text


@pytest.mark.parametrize("plan", [PLAN_BATTERY, PLAN_IMAGING])
def test_result_status_reflects_stages(plan):
    r = _run(plan)
    bad = [s for s in r.stages if s.state in ("degraded", "error")]
    mock = any(c.generator.value == "mock" for c in r.risk_cards) or r.manifest["llm_provider"] == "mock"
    assert (r.status == "degraded") == (bool(bad) or mock)


def test_shared_fixtures_demo_plan_and_negative_control():
    """공용 fixture(tests/fixtures)와 기획 키트 원본 데모 계획서로 한 쌍 검사: 계획서는 카드, 조리법은 0장+사유."""
    from tests.fixtures.loader import NEGATIVE_PLAN, load_fixtures, plan_text

    fx = load_fixtures()
    be = FixtureBackend(fx.works, fx.reviews)
    pos = run_premortem(plan_text("plan.md"), provider="mock", backend=be, cache_dir=None)
    neg = run_premortem(plan_text(NEGATIVE_PLAN), provider="mock", backend=be, cache_dir=None)
    assert len(pos.risk_cards) >= 1
    _assert_all_quotes_verify(pos, be)
    assert neg.risk_cards == [] and "연구계획서가 아니다" in neg.risk_synthesis["no_card_reason"]


def test_reviewevent_fixture_has_no_identity_fields():
    assert "reviewer_pseudonym" in ReviewEvent.model_fields
    assert not any(k in ReviewEvent.model_fields for k in ("reviewer_id", "reviewer_name", "author"))
