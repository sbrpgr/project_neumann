"""공용 fixture가 계약(models)으로 읽히고, Excerpt가 원문 대조를 통과하는지."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

from neumann.models import PlanDocument, RiskCode, sha256_text
from tests.fixtures.loader import DEMO_PLANS, NEGATIVE_PLAN, PLANS_DIR, load_fixtures, plan_text

ROOT = Path(__file__).resolve().parents[2]
KIT_DEMO = Path("C:/Users/User/Desktop/노이만_본선자료/기획서/부록/데모입력")


def test_counts_and_two_fields() -> None:
    fx = load_fixtures()
    assert len(fx.works) == 6
    assert len(fx.reviews) == 12
    assert len(fx.risk_cards) == 2
    assert len(fx.decisions) >= 1
    fields = {w.fields[0] for w in fx.works}
    assert fields == {"molecular property prediction", "medical image segmentation"}
    assert all(w.title.startswith("[FAKE]") for w in fx.works)
    assert all("example.org" in w.url for w in fx.works)


def test_reviews_are_3_to_6_sentences_and_link_to_works() -> None:
    fx = load_fixtures()
    work_ids = {w.work_id for w in fx.works}
    for r in fx.reviews:
        n = sum(r.text.count(p) for p in (". ", "? ")) + 1
        assert 3 <= n <= 6, (r.review_id, n)
        assert r.work_id in work_ids
        assert r.provenance.content_sha256 == sha256_text(r.text)


def test_every_excerpt_matches_source_text() -> None:
    fx = load_fixtures()
    assert any(e.start == 0 for e in fx.excerpts)  # 오프셋 0 포함
    assert {e.source_kind for e in fx.excerpts} >= {"review", "decision"}
    for e in fx.excerpts:
        src = fx.source_text(e)
        assert e.verify_against(src), e.excerpt_id
        assert src[e.start : e.end] == e.text


def test_cards_reference_existing_excerpts_and_works() -> None:
    fx = load_fixtures()
    ex_ids = {e.excerpt_id for e in fx.excerpts}
    work_ids = {w.work_id for w in fx.works}
    for c in fx.risk_cards:
        assert c.evidence and set(c.evidence) <= ex_ids
        assert set(c.works) <= work_ids
        assert c.risk_code is not RiskCode.R0
    tag_ids = {t.excerpt_id for t in fx.risk_tags}
    assert tag_ids == ex_ids


def test_premortem_result_fixture_matches_contract_and_plan_lines() -> None:
    fx = load_fixtures()
    res = fx.premortem_result
    schema = json.loads((ROOT / "contracts" / "premortem_response.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(res.model_dump(mode="json"), schema)
    plan = PlanDocument.from_text(plan_text("plan.md"), session_id=res.session_id)
    assert res.plan_id == plan.plan_id
    for c in res.risk_cards:
        for no in c.why_applies.plan_lines:
            assert 1 <= no <= len(plan.lines)
        for x in c.evidence:
            ex = next(e for e in res.evidence if e.excerpt_id == x)
            assert ex.verify_against(fx.source_text(ex))
    assert "randomly split" in plan.line(16)
    assert "error bars" in plan.line(22)


def test_plans_present_and_demo_plans_identical_to_kit() -> None:
    for name in (*DEMO_PLANS, NEGATIVE_PLAN):
        text = plan_text(name)
        assert text.strip()
        PlanDocument.from_text(text, session_id="t")
    if KIT_DEMO.exists():  # 키트가 있는 머신에서만 원본 대조
        for name in DEMO_PLANS:
            a = hashlib.sha256((PLANS_DIR / name).read_bytes()).hexdigest()
            b = hashlib.sha256((KIT_DEMO / name).read_bytes()).hexdigest()
            assert a == b, name
    recipe = plan_text(NEGATIVE_PLAN)
    assert "토마토" in recipe and "연구" not in recipe
