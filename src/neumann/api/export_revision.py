"""내보내기 ZIP의 수정 권고 자리(E3-L2r). export.py는 이 모듈을 몇 줄로만 부른다(E4-L2f와 충돌 최소화).

ZIP 9파일은 그대로 두고, 요청에 수정 권고가 있을 때만 파일을 **덧붙인다**:
- `revision.json`: 카드별 수정 권고(계약 revision.schema.json 그대로) + 연구자 결정(채택·수정·기각) + 출처(origin)
- `revised_plan.md`: 통합본(각주 판 + 수정 이력·근거 부록). 요청의 revised_plan(계약 revised_plan.schema.json)이 있을 때

출처(origin): 서버 서명(`revision_sig`, E4-L2f signing이 있을 때만 만들어진다)이 확인되면 server_signed, 아니면
client_submitted_unverified. 결정의 edit_id는 수정 권고 안에 있어야 한다(없으면 ValueError → 422).
리뷰어 신원 필드는 없다(NeumannModel). 연구자 문안·메모는 이메일·ORCID를 가린다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from neumann.models import SCHEMA_VERSION, NeumannModel, PremortemResult, redact_pii

REVISION_FILE = "revision.json"
REVISED_PLAN_FILE = "revised_plan.md"
FILE_ROLES: dict[str, str] = {
    REVISION_FILE: "카드별 수정 권고(해석·채택 연구의 대응·수정안·질문·게이트 폐기 수·근거 발췌)와 연구자 결정(채택·수정·기각)",
    REVISED_PLAN_FILE: "통합된 수정 계획서: 각주 판(변경 문장 옆 근거)과 수정 이력·미해결 충돌·자리표시·근거 부록",
}
DECISION_LABELS: dict[str, str] = {"adopt": "채택", "modify": "수정", "reject": "기각"}
_ALIASES = {v: k for k, v in DECISION_LABELS.items()}


class RevisionDecision(NeumannModel):
    """수정안(edit) 하나에 대한 연구자 결정."""

    edit_id: str = Field(min_length=1)
    card_id: str | None = None
    decision: Literal["adopt", "modify", "reject"]
    revised_text: str | None = Field(default=None, max_length=2000, description="수정(modify) 때 연구자 문안. 이메일·ORCID는 가린다")
    note: str | None = Field(default=None, max_length=2000)
    decided_at: datetime | None = None

    @field_validator("decision", mode="before")
    @classmethod
    def _accept_korean(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return _ALIASES.get(v, v.lower())
        return v

    @field_validator("revised_text", "note")
    @classmethod
    def _mask(cls, v: str | None) -> str | None:
        return None if v is None else redact_pii(v)

    @field_validator("decided_at")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("timezone-aware datetime만 허용한다")
        return v


def edit_ids_of(revision: Mapping[str, Any]) -> dict[str, str]:
    """edit_id → card_id."""
    out: dict[str, str] = {}
    for rev in revision.get("revisions", []) or []:
        if isinstance(rev, Mapping):
            for e in rev.get("edits", []) or []:
                if isinstance(e, Mapping) and isinstance(e.get("edit_id"), str):
                    out[e["edit_id"]] = str(rev.get("card_id", ""))
    return out


def validate_decisions(revision: Mapping[str, Any], decisions: Sequence[Mapping[str, Any] | RevisionDecision] | None
                       ) -> list[RevisionDecision]:
    ids = edit_ids_of(revision)
    out: list[RevisionDecision] = []
    for raw in decisions or ():
        d = raw if isinstance(raw, RevisionDecision) else RevisionDecision.model_validate(raw)
        if d.edit_id not in ids:
            raise ValueError(f"수정 권고에 없는 edit_id {d.edit_id!r}")
        if d.card_id is None:
            d = d.model_copy(update={"card_id": ids[d.edit_id]})
        out.append(d)
    return out


def _origin(revision: Mapping[str, Any], sig: Any, result: Any = None, result_sig: Any = None) -> str:
    try:
        from neumann.api.revise import revision_verified, verify_result
    except ImportError:
        return "client_submitted_unverified"
    return "server_signed" if verify_result(result, result_sig) and revision_verified(revision, sig) else "client_submitted_unverified"


def _json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def extra_files(
    result: PremortemResult,
    revision: Mapping[str, Any] | None,
    decisions: Sequence[Mapping[str, Any] | RevisionDecision] | None,
    revised_plan: Mapping[str, Any] | None,
    revision_sig: Any = None,
    result_sig: Any = None,
) -> dict[str, bytes]:
    """덧붙일 파일 {이름: 바이트}. 계약 위반·plan_id 불일치·없는 edit_id는 ValueError."""
    files: dict[str, bytes] = {}
    if revision is None and revised_plan is None:
        if decisions:
            raise ValueError("revision 없이 revision_decisions만 왔다")
        return files
    if revision is not None:
        from neumann.analyze.revise import validate_revision

        errs = validate_revision(revision)
        if errs:
            raise ValueError("수정 권고가 계약(revision.schema.json)과 맞지 않는다: " + "; ".join(errs[:3]))
        if revision.get("plan_id") != result.plan_id:
            raise ValueError("수정 권고의 plan_id가 결과의 plan_id와 다르다")
        decided = validate_decisions(revision, decisions)
        sig = revision_sig if revision_sig is not None else revision.get("revision_sig")
        files[REVISION_FILE] = _json_bytes({
            "format": "neumann-package/1", "schema_version": SCHEMA_VERSION, "plan_id": result.plan_id,
            "origin": _origin(revision, sig, result, result_sig), "choices": DECISION_LABELS,
            "revision": {k: v for k, v in revision.items() if k != "revision_sig"},
            "decisions": [d.model_dump(mode="json") for d in decided],
        })
    elif decisions:
        raise ValueError("revision 없이 revision_decisions만 왔다")
    if revised_plan is not None:
        from neumann.analyze import assemble as asm

        errs = asm.validate_revised_plan(revised_plan)
        if errs:
            raise ValueError("통합본이 계약(revised_plan.schema.json)과 맞지 않는다: " + "; ".join(errs[:3]))
        if revised_plan.get("plan_id") != result.plan_id:
            raise ValueError("통합본의 plan_id가 결과의 plan_id와 다르다")
        from neumann.api.revise import verify_payload

        plan_body = {k: v for k, v in revised_plan.items() if k != "revised_plan_sig"}
        trusted = (revision is not None and _origin(revision, revision_sig if revision_sig is not None else revision.get("revision_sig"),
                                                   result, result_sig) == "server_signed"
                   and verify_payload("revised-plan", plan_body, revised_plan.get("revised_plan_sig")))
        rendered = asm.render_markdown(revised_plan, asm.evidence_lookup(result, revision),
                                      model=(revision or {}).get("model") if trusted else None,
                                      generator=(revision or {}).get("generator") if trusted else "client_submitted_unverified")
        text = rendered["footnoted"].rstrip("\n") + "\n\n" + rendered["history"]
        files[REVISED_PLAN_FILE] = text.encode("utf-8")
    return files


def summary_lines(revision: Mapping[str, Any] | None, decisions: Sequence[Any] | None,
                  revised_plan: Mapping[str, Any] | None) -> list[str]:
    """README·리포트용 한 줄들(없으면 빈 목록)."""
    out: list[str] = []
    if revision is not None:
        revs = revision.get("revisions", []) or []
        n_edits = sum(len(r.get("edits", []) or []) for r in revs if isinstance(r, Mapping))
        n_prec = sum(1 for r in revs if isinstance(r, Mapping) and (r.get("precedents") or {}).get("status") == "found")
        audit = revision.get("audit", {}) or {}
        out.append(f"- 수정 권고(`{REVISION_FILE}`): 카드 {len(revs)}장 · 수정안 {n_edits}건 · 채택 연구 대응 {n_prec}장 · "
                   f"근거 게이트 폐기 {audit.get('dropped', 0)}건 · 생성 {revision.get('generator')}"
                   + (f"({revision.get('model')})" if revision.get("model") else "") + f" · 결정 {len(decisions or ())}건")
    if revised_plan is not None:
        st = revised_plan.get("stats", {}) or {}
        pol = revised_plan.get("polish", {}) or {}
        out.append(f"- 통합본(`{REVISED_PLAN_FILE}`): 적용 {st.get('applied', 0)}건 · 충돌 {st.get('conflicts', 0)}건 · "
                   f"자리표시 {st.get('placeholders', 0)}곳 · 다듬기 {'적용' if pol.get('applied') else '미적용'}")
    return out


__all__ = ["DECISION_LABELS", "FILE_ROLES", "REVISED_PLAN_FILE", "REVISION_FILE", "RevisionDecision", "edit_ids_of",
           "extra_files", "summary_lines", "validate_decisions"]
