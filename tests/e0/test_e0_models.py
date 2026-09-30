"""E0b 계약 불변식 테스트: 신원 필드 금지, Excerpt 오프셋, 근거 없는 카드 거부, provenance 필수."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from neumann.models import (
    Decision,
    Excerpt,
    Generator,
    NeumannModel,
    PlanDocument,
    PostStatus,
    PremortemResult,
    Provenance,
    ReviewEvent,
    RiskCard,
    RiskCode,
    RiskScore,
    RiskTag,
    StageStatus,
    WhyApplies,
    Work,
    make_reviewer_pseudonym,
    redact_pii,
    sha256_text,
)

ROOT = Path(__file__).resolve().parents[2]
SRC_TEXT = "The baselines are weak. Only a single seed is reported, so the gains may be noise."


def prov(**kw) -> Provenance:
    base = dict(
        source="fixture",
        source_url="https://example.org/forum?id=FAKE01&noteId=r1",
        accessed_at=datetime(2026, 9, 30, 9, 0, tzinfo=UTC),
        content_sha256=sha256_text(SRC_TEXT),
    )
    base.update(kw)
    return Provenance(**base)


def excerpt(start: int = 0, end: int = 23) -> Excerpt:
    return Excerpt.from_source(
        SRC_TEXT, start, end, source_kind="review", source_id="rev1", source_url="https://example.org/r1"
    )


def card(**kw) -> RiskCard:
    base = dict(
        card_id="card_1",
        risk_code="R2",
        title="Weak baselines",
        why_applies=WhyApplies(text="Plan compares against one baseline", plan_lines=[3]),
        evidence=[excerpt().excerpt_id],
        score=RiskScore(similarity=0.8, frequency=0.5, severity=0.6, confidence=0.9, total=0.68),
        generator=Generator.mock,
    )
    base.update(kw)
    return RiskCard(**base)


# ── 불변식 2: 신원 필드 금지 ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "field", ["reviewer_name", "email", "reviewer_id", "author", "orcid", "Affiliation", "signature_raw"]
)
def test_identity_field_raises_typeerror_at_class_definition(field: str) -> None:
    with pytest.raises(TypeError, match="신원 필드 금지"):
        type("Bad", (NeumannModel,), {"__annotations__": {field: str}})


def test_identity_alias_also_blocked() -> None:
    from pydantic import Field

    with pytest.raises(TypeError):

        class Sneaky(NeumannModel):
            note: str = Field(alias="reviewer_email")


def test_identity_exemption_is_explicit_only() -> None:
    class Ok(NeumannModel):
        __identity_exempt_fields__ = frozenset({"display_name"})
        display_name: str

    assert Ok(display_name="stage label").display_name == "stage label"


def test_extra_identity_key_rejected_at_runtime() -> None:
    with pytest.raises(ValidationError):
        ReviewEvent(review_id="r", work_id="w", text="ok", provenance=prov(), reviewer_name="X")


def test_reviewer_pseudonym_pattern_only() -> None:
    good = make_reviewer_pseudonym("Reviewer_e1KG", scope="forum:FAKE01", salt="test-salt")
    assert good.startswith("rvw_") and len(good) == 20
    ReviewEvent(review_id="r", work_id="w", text="ok", provenance=prov(), reviewer_pseudonym=good)
    with pytest.raises(ValidationError):
        ReviewEvent(
            review_id="r", work_id="w", text="ok", provenance=prov(), reviewer_pseudonym="ICLR.cc/2024/Reviewer_e1KG"
        )
    other_scope = make_reviewer_pseudonym("Reviewer_e1KG", scope="forum:FAKE02", salt="test-salt")
    assert other_scope != good
    with pytest.raises(ValueError):
        make_reviewer_pseudonym("x", scope="s", salt="")


def test_review_text_with_pii_rejected_and_redact_helper() -> None:
    dirty = "Contact me at jane.doe@example.com, ORCID 0000-0002-1825-0097. vIoU@0.3 is fine."
    with pytest.raises(ValidationError):
        ReviewEvent(review_id="r", work_id="w", text=dirty, provenance=prov())
    clean = redact_pii(dirty)
    assert "@example.com" not in clean and "0000-0002" not in clean and "vIoU@0.3" in clean
    ReviewEvent(review_id="r", work_id="w", text=clean, provenance=prov())


# ── 불변식 1: provenance 필수 ────────────────────────────────────────────


def test_work_without_provenance_rejected() -> None:
    with pytest.raises(ValidationError, match="provenance"):
        Work(work_id="fixture:W1", title="T", url="https://example.org/w1")


@pytest.mark.parametrize("cls,kw", [
    (ReviewEvent, dict(review_id="r", work_id="w", text="t")),
    (Decision, dict(decision_id="d", work_id="w", outcome="reject", outcome_raw="Reject")),
    (PostStatus, dict(post_status_id="p", kind="retraction", work_id="w")),
])
def test_other_sourced_records_require_provenance(cls, kw) -> None:
    with pytest.raises(ValidationError):
        cls(**kw)
    cls(**kw, provenance=prov())


def test_provenance_rules() -> None:
    url = "https://openreview.net/forum?id=AbC&noteId=XyZ"
    assert prov(source_url=url).source_url == url  # 글자 그대로
    with pytest.raises(ValidationError):
        prov(source_url="ftp://example.org/x")
    with pytest.raises(ValidationError):
        prov(accessed_at=datetime(2026, 9, 30, 9, 0))  # naive
    with pytest.raises(ValidationError):
        prov(accessed_at=datetime.now(UTC) + timedelta(days=2))
    with pytest.raises(ValidationError):
        prov(content_sha256="abc")
    with pytest.raises(ValidationError):
        prov(source="reviewcritique")


def test_post_status_needs_target() -> None:
    with pytest.raises(ValidationError):
        PostStatus(post_status_id="p", kind="retraction", provenance=prov())
    PostStatus(post_status_id="p", kind="retraction", target_doi="10.1234/fake.1", provenance=prov())


# ── Excerpt 오프셋 ───────────────────────────────────────────────────────


def test_excerpt_from_source_slices_original_including_offset_zero() -> None:
    ex = excerpt(0, 23)
    assert ex.start == 0
    assert ex.text == SRC_TEXT[0:23] == "The baselines are weak."
    assert ex.text_sha256 == sha256_text(ex.text)
    assert ex.verify_against(SRC_TEXT)


def test_excerpt_middle_and_end_offsets() -> None:
    start = SRC_TEXT.index("Only")
    ex = excerpt(start, len(SRC_TEXT))
    assert ex.text == SRC_TEXT[start:]
    assert ex.verify_against(SRC_TEXT)


def test_excerpt_tampered_text_rejected() -> None:
    ex = excerpt(0, 23)
    data = ex.model_dump()
    data["text"] = "The baselines are good."  # 같은 길이, 다른 글자
    with pytest.raises(ValidationError):
        Excerpt(**data)  # sha 불일치
    data["text_sha256"] = sha256_text(data["text"])
    forged = Excerpt(**data)  # 자기 모순은 없지만
    assert not forged.verify_against(SRC_TEXT)  # 원문 대조에서 걸린다


def test_excerpt_constructor_invariants() -> None:
    with pytest.raises(ValueError):
        Excerpt.from_source(SRC_TEXT, 10, 5, source_kind="review", source_id="r", source_url="https://e.org")
    with pytest.raises(ValueError):
        Excerpt.from_source(SRC_TEXT, 0, len(SRC_TEXT) + 1, source_kind="review", source_id="r", source_url="https://e.org")
    with pytest.raises(ValueError):
        Excerpt.from_source("a    b", 1, 5, source_kind="review", source_id="r", source_url="https://e.org")  # 공백뿐
    data = excerpt().model_dump()
    data["end"] = data["end"] + 1  # len(text) != end-start
    with pytest.raises(ValidationError):
        Excerpt(**data)


def test_excerpt_detects_changed_source() -> None:
    ex = excerpt(0, 23)
    assert not ex.verify_against(SRC_TEXT + " edited")
    assert not ex.verify_against("short")


# ── 불변식 3: 근거 없는 카드 거부 ────────────────────────────────────────


def test_riskcard_without_evidence_rejected() -> None:
    with pytest.raises(ValidationError):
        card(evidence=[])
    with pytest.raises(ValidationError):
        card(evidence=[" "])
    c = card()
    assert c.risk_code is RiskCode.R2 and c.evidence


def test_subcode_must_belong_to_code() -> None:
    card(subcode="R2.3")
    with pytest.raises(ValidationError):
        card(subcode="R5.1")
    with pytest.raises(ValidationError):
        RiskTag(excerpt_id="e", risk_code="R3", subcode="R1.2", generator="rule")


def test_risk_code_names_and_generator() -> None:
    assert [c.value for c in RiskCode] == [f"R{i}" for i in range(10)]
    assert RiskCode.R0.slug == "presentation_clarity"
    assert RiskCode.R3.slug == "data_leakage"
    assert {g.value for g in Generator} == {"astra", "rule", "mock"}
    with pytest.raises(ValidationError):
        card(generator="gpt")


def test_score_bounds() -> None:
    with pytest.raises(ValidationError):
        RiskScore(similarity=1.2, frequency=0, severity=0, confidence=0, total=0)


# ── PlanDocument ─────────────────────────────────────────────────────────


def test_plan_document_lines_and_no_body_in_persisted_dump() -> None:
    text = "# Plan\r\nWe train a GNN.\r\nContact: pi@example.com\n"
    plan = PlanDocument.from_text(text, session_id="s1")
    assert [ln.no for ln in plan.lines][:3] == [1, 2, 3]
    assert plan.line(2) == "We train a GNN."
    assert "@example.com" not in plan.text
    assert plan.plan_id == sha256_text(plan.text)
    persisted = json.dumps(plan.dump_persisted())
    assert "GNN" not in persisted and plan.plan_id in persisted
    with pytest.raises(ValidationError):
        PlanDocument(plan_id="0" * 64, session_id="s1", lines=plan.lines)


# ── StageStatus / PremortemResult ↔ 계약 스키마 ──────────────────────────


def _schema() -> dict:
    return json.loads((ROOT / "contracts" / "premortem_response.schema.json").read_text(encoding="utf-8"))


def test_premortem_result_dump_matches_contract_schema() -> None:
    plan = PlanDocument.from_text("line one\nline two\nline three", session_id="s1")
    ex = excerpt()
    res = PremortemResult(
        session_id="s1",
        plan_id=plan.plan_id,
        plan=plan,
        evidence=[ex],
        risk_cards=[card()],
        stages=[StageStatus(stage="retrieve", state="ok"), StageStatus(stage="extract", state="degraded", detail="timeout")],
    )
    assert res.status == "degraded"  # 강등을 ok로 숨기지 않는다
    dumped = res.model_dump(mode="json")
    jsonschema.validate(dumped, _schema())
    assert dumped["stages"][1] == {**dumped["stages"][1], "name": "extract", "status": "degraded", "reason": "timeout"}
    again = PremortemResult.model_validate(dumped)
    assert again.stages[1].state == "degraded" and again.risk_cards[0].card_id == "card_1"
    persisted = res.dump_persisted()
    jsonschema.validate(persisted, _schema())
    assert "line two" not in json.dumps(persisted)


def test_premortem_result_minimal_is_valid() -> None:
    res = PremortemResult(session_id="s", plan_id="p")
    jsonschema.validate(res.model_dump(mode="json"), _schema())
    assert res.status == "ok"


def test_premortem_result_rejects_dangling_card_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        PremortemResult(session_id="s", plan_id="p", risk_cards=[card()], evidence=[])
