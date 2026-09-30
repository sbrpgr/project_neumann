"""Optional final inspection export, bound to the existing B1 composition.

`finalization` accepts the complete /premortem/finalize response. An inner
inspection object is also accepted, but cannot authenticate the signed envelope.
Researcher-confirmed text always remains client_submitted_unverified (F-8).
"""
from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from neumann.api import export_revision, signing
from neumann.api.view import display_generator
from neumann.models import IDENTITY_TOKENS, PremortemResult, redact_pii, sha256_text

FILE_ROLES = {
    "final_draft.md": "최종 수정 초안과 출처·점검 상태",
    "finalization.json": "최종 점검 원자료·자동 수정·도구 검사·미해결 항목과 출처",
}
UNVERIFIED = export_revision.UNVERIFIED
SIGNED = export_revision.SERVER_SIGNED


def _conflict(message: str) -> None:
    raise export_revision.PairingConflict("최종 점검 결합 불일치: " + message)


def _safe(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", redact_pii(value))
    if isinstance(value, Mapping):
        return {k: _safe(v) for k, v in value.items()
                if k not in {"finalization_sig", "revised_plan_sig"}
                and not any(token in str(k).lower() for token in IDENTITY_TOKENS)}
    if isinstance(value, list):
        return [_safe(v) for v in value]
    return value


def _md(value: Any) -> str:
    return html.escape(str(_safe(value)), quote=False).replace("\n", " ").replace("\r", " ")


@dataclass
class FinalComposition:
    envelope: dict[str, Any] | None = None
    origin: str | None = None
    qualifiers: list[str] = field(default_factory=list)

    def metadata(self) -> dict[str, Any] | None:
        if self.envelope is None:
            return None
        return {"origin": self.origin, "status": self.envelope["finalization"]["status"],
                "qualifiers": self.qualifiers, "researcher_text_signed": False}


def compose(result: PremortemResult, base: export_revision.Composition,
            finalization: Mapping[str, Any] | None, finalization_sig: str | None = None,
            final_text: str | None = None) -> FinalComposition:
    if finalization is None:
        if finalization_sig is not None or final_text is not None:
            _conflict("finalization 없이 서명 또는 최종 문안만 제출됨")
        return FinalComposition()
    import jsonschema
    from neumann.api.view import SCHEMA_PATH

    envelope = dict(finalization)
    full = "finalization" in envelope
    if not full:
        envelope = {"version": "finalization@v1", "assembled": base.revised_plan or {},
                    "finalization": dict(finalization), "final_text": finalization.get("final_text"),
                    "origin": UNVERIFIED, "finalization_sig": None}
    else:
        envelope.setdefault("finalization_sig", None)
    schema = json.loads((SCHEMA_PATH.parent / "finalization.schema.json").read_text(encoding="utf-8"))
    if not jsonschema.Draft202012Validator(schema).is_valid(envelope):
        raise ValueError("최종 점검이 계약(finalization.schema.json)과 맞지 않는다")
    final = envelope["finalization"]
    if envelope["final_text"] != final["final_text"] or (final_text is not None and final_text != final["final_text"]):
        _conflict("최종 문안이 점검 결과의 final_text와 다름")
    for prefix, text_key in (("input", "input_text"), ("output", "final_text")):
        if sha256_text(final[text_key]) != final[prefix + "_plan_id"]:
            _conflict(prefix + " 문안 해시가 점검 결과와 다름")

    # Every applied correction must describe the actual output; merely valid
    # signatures cannot make an unrelated draft part of this package.
    lines = final["input_text"].split("\n")
    updated, touched = list(lines), set()
    for correction in final["corrections"]:
        if correction.get("applied") is not True:
            continue
        no = correction.get("line")
        after = correction.get("after")
        if (type(no) is not int or not 1 <= no <= len(lines) or no in touched
                or correction.get("before") != lines[no - 1] or not isinstance(after, str)
                or "\n" in after or "\r" in after):
            _conflict("자동 수정의 줄·원문·수정 문안이 입력과 다름")
        updated[no - 1] = after
        touched.add(no)
    if "\n".join(updated) != final["final_text"]:
        _conflict("자동 수정 이력으로 최종 문안을 재현할 수 없음")

    assembled = envelope["assembled"]
    # Reuse all B1 checks against result/revision/decisions, even for unsigned input.
    linked = export_revision.compose(result, base.revision, base.decided, assembled,
                                     None, None) if assembled else export_revision.Composition()
    if base.revised_plan is not None and assembled != base.revised_plan:
        _conflict("첨부 조립본이 최종 점검 응답의 조립본과 다름")
    researcher = (envelope.get("text_source") == "researcher_confirmed"
                  or (isinstance(envelope.get("provenance"), Mapping)
                      and envelope["provenance"].get("researcher_text") is True))
    if assembled and not researcher and (final["input_text"] != assembled.get("revised_text")
                                         or final["input_plan_id"] != assembled.get("revised_plan_id")):
        _conflict("점검 입력이 첨부 조립본과 다름")
    embedded_sig = envelope.get("finalization_sig")
    if finalization_sig is not None and embedded_sig is not None and finalization_sig != embedded_sig:
        _conflict("별도 서명과 응답 서명이 다름")
    signature = finalization_sig if finalization_sig is not None else embedded_sig
    body = {k: v for k, v in envelope.items() if k != "finalization_sig"}
    verified = (full and not researcher and base.assembly_origin == SIGNED
                and not linked.qualifiers and envelope["origin"] == SIGNED
                and signing.verify_payload("finalization", body, signature))
    qualifiers = [] if verified else ["최종 점검 서버 서명·결합 확인 안 됨(client_submitted_unverified)."]
    if researcher:
        qualifiers.append("연구자 확정 문안은 서버 서명 대상이 아님(F-8).")
    return FinalComposition(envelope, SIGNED if verified else UNVERIFIED, qualifiers)


def render_files(comp: FinalComposition) -> dict[str, bytes]:
    if comp.envelope is None:
        return {}
    final = comp.envelope["finalization"]
    draft = (f"> 최종 수정 초안 · 상태: {final['status']} · 출처: {comp.origin}\n\n"
             + _generation(comp, final) + "\n\n"
             + html.escape(_safe(final["final_text"]), quote=False) + "\n\n"
             + "\n".join(comp.qualifiers + [_md(n) for n in final["notices"]]) + "\n")
    data = {"format": "neumann-package/1", **_safe(comp.envelope),
            "origin": comp.origin, "export_verification": comp.metadata()}
    return {"final_draft.md": draft.encode("utf-8"),
            "finalization.json": (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")}


def _generation(comp: FinalComposition, final: Mapping[str, Any]) -> str:
    if comp.origin != SIGNED:
        return "생성 방식·모델: 요청자 표기이며 서버 확인 안 됨."
    return "생성 방식: " + _md(display_generator(final["generator"], final["model"]))


def summary_of(comp: FinalComposition) -> list[str]:
    if comp.envelope is None:
        return []
    final = comp.envelope["finalization"]
    out = ["", "## 최종 점검", "", f"- 상태: {final['status']} · 출처: {comp.origin}",
           "- " + _generation(comp, final),
           "- 제한된 검사 범위이며 모든 오류의 부재를 보장하지 않습니다.", *comp.qualifiers,
           "", "### 자동 수정 목록", ""]
    for row in final["corrections"]:
        out.append(f"- {_md(row.get('line', '?'))}줄 · 적용: {_md(row.get('applied', False))} · "
                   f"{_md(row.get('before', ''))} → {_md(row.get('after', ''))} · 사유: {_md(row.get('reason', ''))}")
    if not final["corrections"]:
        out.append("- 자동 수정 없음")
    out += ["", "### 도구별 결과", ""]
    for key, label in (("tool_checks_before", "수정 전"), ("tool_checks_after", "재검사")):
        for row in final[key]:
            out.append(f"- {label} · {_md(row['tool'])} · {_md(row['check_id'])} · "
                       f"{row['status']} · {_md(row['message'])}")
    if not final["tool_checks_before"] and not final["tool_checks_after"]:
        out.append("- 기록된 도구 검사 없음(검사 통과를 뜻하지 않음)")
    out += ["", "### 미해결 항목", ""]
    residual = [r for r in final["issues"] if r.get("status") != "resolved"]
    for row in residual:
        out.append(f"- {_md(row.get('issue_id', '?'))} · {_md(row.get('status', 'unchecked'))} · {_md(row.get('message', ''))}")
    latest = {r["check_id"]: r for r in final["tool_checks_before"] + final["tool_checks_after"]}
    pending_tools = [r for r in latest.values() if r["status"] != "passed"]
    for row in pending_tools:
        out.append(f"- 도구 {_md(row['tool'])} · {_md(row['check_id'])} · {row['status']} · {_md(row['message'])}")
    if not residual and not pending_tools:
        out.append("- 기록된 미해결 항목 없음")
    out += [f"- {_md(notice)}" for notice in final["notices"]]
    return out
