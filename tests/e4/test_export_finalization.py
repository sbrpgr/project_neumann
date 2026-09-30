"""PKG-FINAL: optional inspection ZIP, authenticated chain and F-8 regressions.

Only local fixtures, mock assembly and process-local signatures are used.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import export, finalize, serving, signing
from neumann.models import sha256_text
from tests.e4.test_export_pairing import chain  # shared mock signed chain fixture


def sign(envelope):
    envelope["finalization_sig"] = signing.sign_payload(
        "finalization", {k: v for k, v in envelope.items() if k != "finalization_sig"})


@pytest.fixture
def payload(chain):
    p = chain.payload()
    text = p["revised_plan"]["revised_text"]
    before = text.split("\n")
    after = list(before)
    after[0] = before[0] + " [확인 필요]"
    output = "\n".join(after)
    check = {"check_id": "physical-1", "kind": "units", "tool": "units",
             "status": "failed", "plan_lines": [1], "message": "단위 확인 필요", "details": {}}
    inspection = {"version": "finalization@v1", "status": "partial",
        "input_plan_id": sha256_text(text), "output_plan_id": sha256_text(output),
        "input_text": text, "final_text": output,
        "issues": [{"issue_id": "i1", "kind": "physical", "status": "unresolved", "message": "단위 확인 필요"}],
        "tool_checks_before": [check], "tool_checks_after": [{**check, "status": "unchecked"}],
        "corrections": [{"line": 1, "before": before[0], "after": after[0], "applied": True, "reason": "applied"}],
        "counters": {"assessment_calls": 1, "correction_calls": 1, "correction_batches": 1, "recheck_runs": 1},
        "generator": "mock", "model": "mock", "notices": ["mock 테스트 결과"]}
    envelope = {"version": "finalization@v1", "assembled": copy.deepcopy(p["revised_plan"]),
        "finalization": inspection, "final_text": output, "origin": "server_signed",
        "text_source": "server_assembled", "provenance": {"researcher_text": False}}
    sign(envelope)
    p.update(finalization=envelope, finalization_sig=envelope["finalization_sig"], final_text=output)
    return p


def test_signed_inspection_zip_contents_and_summary(chain, payload):
    sent = chain.send(payload)
    assert sent.status == 200, sent.detail
    final = json.loads(sent.files["finalization.json"])
    assert final["origin"] == "server_signed"
    assert final["finalization"] == payload["finalization"]["finalization"]
    assert payload["final_text"] in sent.files["final_draft.md"].decode()
    assert "모의(mock)" in sent.files["final_draft.md"].decode()
    assert sent.headers["x-neumann-finalization-origin"] == "server_signed"
    assert all(text in sent.readme for text in ("## 최종 점검", "자동 수정 목록", "도구별 결과", "미해결 항목",
                                                "physical-1", "unresolved", "failed", "unchecked", "mock 테스트 결과"))
    assert "finalization_sig" not in final
    for exported in (sent.readme, sent.files["final_draft.md"].decode()):
        assert "모델: mock" in exported and "최종 점검 완료: 아니오" in exported
    entries = {x["path"]: x for x in sent.manifest["files"]}
    for name in ("final_draft.md", "finalization.json"):
        assert entries[name]["origin"] == "server_signed"
        assert entries[name]["sha256"] == hashlib.sha256(sent.files[name]).hexdigest()
        assert entries[name]["bytes"] == len(sent.files[name])


def test_actual_finalize_response_can_be_exported(chain):
    # Exercises the issuer's real envelope/signature layout, using mock only.
    from tests.fixtures.loader import plan_text
    p = chain.payload()
    req = finalize.FinalizeRequest(result=p["result"], result_sig=p["result_sig"],
        plan_text=plan_text(), revision=p["revision"], decisions=p["revision_decisions"],
        submission_id="pkg_final_actual", polish=False)
    out = finalize.run_finalization(req, threading.Event())
    p.update(finalization=out, revised_plan=out["assembled"])
    sent = chain.send(p)
    assert sent.status == 200, sent.detail
    assert sent.headers["x-neumann-finalization-origin"] == "server_signed"
    assert out["finalization"]["status"] in sent.readme


@pytest.mark.parametrize("status,completed", [("completed", "예"), ("partial", "아니오"), ("incomplete", "아니오")])
def test_completion_and_model_come_from_inspection(chain, payload, status, completed):
    envelope = payload["finalization"]
    envelope["finalization"].update(status=status, model="mock-deterministic-v1")
    sign(envelope)
    payload["finalization_sig"] = envelope["finalization_sig"]
    sent = chain.send(payload)
    assert sent.status == 200, sent.detail
    for exported in (sent.readme, sent.files["final_draft.md"].decode()):
        assert f"최종 점검 완료: {completed}" in exported
        assert "모의(mock)" in exported and "모델: mock-deterministic-v1" in exported
        assert "mock 테스트 결과" in exported


@pytest.mark.parametrize("mode", ["missing", "tampered", "other_domain", "result_unsigned", "assembly_unsigned"])
def test_unverified_signature_chain_is_explicit(chain, payload, mode):
    envelope = payload["finalization"]
    payload.pop("finalization_sig")
    if mode == "missing":
        envelope.pop("finalization_sig")
    elif mode == "tampered":
        envelope["finalization"]["notices"].append("tampered")
    elif mode == "other_domain":
        envelope["finalization_sig"] = signing.sign_payload("revision", {k: v for k, v in envelope.items() if k != "finalization_sig"})
    elif mode == "result_unsigned":
        payload.pop("result_sig")
    else:
        payload["revised_plan"]["revised_plan_sig"] = None
        envelope["assembled"]["revised_plan_sig"] = None
        sign(envelope)
    sent = chain.send(payload)
    assert sent.status == 200, sent.detail
    assert sent.headers["x-neumann-finalization-origin"] == "client_submitted_unverified"
    assert json.loads(sent.files["finalization.json"])["origin"] == "client_submitted_unverified"
    assert "client_submitted_unverified" in sent.files["final_draft.md"].decode()
    assert sent.manifest["finalization"]["origin"] == "client_submitted_unverified"
    assert "모의(mock)" in sent.readme and "모델: mock" in sent.readme
    assert "요청자 표기이며 서버 확인 안 됨" in sent.readme


@pytest.mark.parametrize("mode", ["output_alias", "hash", "correction_anchor", "correction_missing", "input_assembly",
                                   "assembly", "decisions", "session", "signature_alias", "malformed", "cross_envelope"])
def test_conflicts_are_422_even_when_signed(chain, payload, mode):
    envelope = payload["finalization"]
    final = envelope["finalization"]
    if mode == "output_alias":
        payload["final_text"] += "other"
    elif mode == "hash":
        final["output_plan_id"] = "0" * 64
    elif mode == "correction_anchor":
        final["corrections"][0]["before"] = "other"
    elif mode == "correction_missing":
        final["corrections"] = []
    elif mode == "input_assembly":
        final["input_text"] += "other"
        final["input_plan_id"] = sha256_text(final["input_text"])
        final["final_text"] += "other"
        final["output_plan_id"] = sha256_text(final["final_text"])
        envelope["final_text"] = payload["final_text"] = final["final_text"]
    elif mode == "assembly":
        payload["revised_plan"]["origin"] = "client_submitted_unverified"
    elif mode == "decisions":
        payload["revision_decisions"][0]["decision"] = "reject"
    elif mode == "session":
        payload["result"]["session_id"] = "other-session"
        payload["result_sig"] = signing.sign_result(payload["result"])
    elif mode == "signature_alias":
        payload["finalization_sig"] = "v1." + "0" * 64
    elif mode == "malformed":
        final["tool_checks_before"] = [{}]
    else:
        envelope["assembled"]["plan_id"] = "0" * 64
    if mode != "signature_alias":
        sign(envelope)
        payload["finalization_sig"] = envelope["finalization_sig"]
    assert chain.send(payload).status == 422


@pytest.mark.parametrize("same_text", [False, True])
def test_researcher_confirmed_text_never_server_signed(chain, payload, same_text):
    envelope = payload["finalization"]
    final = envelope["finalization"]
    envelope["text_source"] = "researcher_confirmed"
    envelope["provenance"]["researcher_text"] = True
    if not same_text:
        text = "연구자가 확정한 초안"
        final.update(input_text=text, final_text=text, input_plan_id=sha256_text(text),
                     output_plan_id=sha256_text(text), corrections=[])
        envelope["final_text"] = payload["final_text"] = text
    sign(envelope)  # Even a valid accidental/old signature cannot authenticate F-8 input.
    payload["finalization_sig"] = envelope["finalization_sig"]
    sent = chain.send(payload)
    assert sent.status == 200, sent.detail
    assert sent.headers["x-neumann-finalization-origin"] == "client_submitted_unverified"
    assert "F-8" in sent.readme


def test_envelope_assembly_can_supply_optional_revised_plan(chain, payload):
    payload.pop("revised_plan")
    payload.pop("finalization_sig")
    payload.pop("final_text")
    sent = chain.send(payload)
    assert sent.status == 200, sent.detail
    assert "revised_plan.md" in sent.files
    assert sent.headers["x-neumann-finalization-origin"] == "server_signed"


def test_inner_inspection_without_signed_envelope_is_unverified(chain, payload):
    payload["finalization"] = payload["finalization"]["finalization"]
    payload.pop("finalization_sig")
    sent = chain.send(payload)
    assert sent.status == 200, sent.detail
    assert sent.headers["x-neumann-finalization-origin"] == "client_submitted_unverified"


@pytest.mark.parametrize("field,value", [("final_text", "draft"), ("finalization_sig", "v1." + "0" * 64)])
def test_orphan_fields_refused(chain, field, value):
    p = chain.payload()
    p[field] = value
    assert chain.send(p).status == 422


def test_optional_export_is_deterministic(chain, payload):
    result = payload.pop("result")
    when = datetime(2026, 10, 1, tzinfo=UTC)
    assert export.build_package(result, created_at=when, **payload) == export.build_package(result, created_at=when, **payload)


def test_readme_escapes_markup_and_masks_pii(chain, payload):
    envelope = payload["finalization"]
    envelope["finalization"]["issues"][0]["message"] = '<script>alert(1)</script> mail@example.org'
    envelope["finalization"]["issues"][0]["reviewer_name"] = "private-reviewer"
    sign(envelope)
    payload["finalization_sig"] = envelope["finalization_sig"]
    sent = chain.send(payload)
    assert sent.status == 200, sent.detail
    assert "<script>" not in sent.readme and "&lt;script&gt;" in sent.readme
    assert "mail@example.org" not in sent.readme
    assert "mail@example.org" not in sent.files["finalization.json"].decode()
    assert "reviewer_name" not in sent.files["finalization.json"].decode()
    assert "private-reviewer" not in sent.files["finalization.json"].decode()


def test_four_mib_cap_includes_finalization_before_render(tmp_path, payload, monkeypatch):
    app = FastAPI()
    app.include_router(export.router)
    srv = serving.Serving(serving.ServingConfig(cache_enabled=False, budget_file=tmp_path / "budget.json"))
    serving.install(app, srv)
    calls = []
    monkeypatch.setattr(export, "build_package", lambda *a, **kw: calls.append(1))
    payload["finalization"]["finalization"]["notices"] = ["x" * (4 * 1024 * 1024)]
    with TestClient(app) as client:
        response = client.post("/premortem/package", json=payload)
    assert response.status_code == 413 and not calls
