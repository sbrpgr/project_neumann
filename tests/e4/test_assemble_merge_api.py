"""All 24 saved edits retain signatures and B1 coupling through package export."""
from __future__ import annotations

import copy
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.analyze import assemble as asm
from neumann.api import export, revise, signing
from tests.e3.test_assemble_merge import live24  # noqa: F401


def assembled_payload(bundle, polish=False):
    result, revision = bundle["result"], copy.deepcopy(bundle["revision"])
    revision["revision_sig"] = signing.sign_payload("revision", revision)
    decisions = [{"edit_id": eid, "decision": "adopt"} for eid in asm.collect_edits(revision)]
    result_sig = signing.sign_result(result)
    out = revise.run_assembly(revise.AssembleRequest(plan_text=bundle["plan_text"], revision=revision,
                             result=result, result_sig=result_sig, decisions=decisions, polish=polish), provider="mock")
    assert out["origin"] == "server_signed"
    assert out["stats"]["applied"] == 24
    assert signing.verify_payload("revised-plan", {k: v for k, v in out.items() if k != "revised_plan_sig"}, out["revised_plan_sig"])
    return {"result": result, "result_sig": result_sig, "revision": revision,
            "revision_decisions": decisions, "revised_plan": out}


@pytest.mark.parametrize("polish", [False, True])
def test_all24_signed_package_preserves_every_edit_and_source(live24, polish):
    payload = assembled_payload(live24, polish)
    app = FastAPI()
    app.include_router(export.router)
    with TestClient(app) as client:
        response = client.post("/premortem/package", json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["x-neumann-assembly-origin"] == "server_signed"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        draft = archive.read("revised_plan.md").decode("utf-8")
    for change in payload["revised_plan"]["changes"]:
        assert change["new_text"] in draft
        assert change["edit_id"] in draft
        for excerpt in change["excerpt_ids"]:
            assert excerpt in draft


def test_new_status_and_line_contributors_are_in_signature_scope(live24):
    payload = assembled_payload(live24)
    out = payload["revised_plan"]
    out["edit_statuses"][0]["status"] = "not_applied"
    assert not signing.verify_payload("revised-plan", {k: v for k, v in out.items() if k != "revised_plan_sig"}, out["revised_plan_sig"])


def test_disjoint_merged_edits_keep_b1_pairing_and_all_footnotes(live24):
    revision = copy.deepcopy(live24["revision"])
    card = revision["revisions"][0]
    base = card["edits"][0]
    current = base["current_text"]
    # Independent insertions at the two ends of the same original line.
    items = [{**base, "edit_id": base["edit_id"] + "a", "proposed_text": "제안: " + current},
             {**base, "edit_id": base["edit_id"] + "b", "proposed_text": current + " [확인 필요: 절차]"}]
    card["edits"] = items
    for other in revision["revisions"][1:]:
        other["edits"] = []
    revision["revision_sig"] = signing.sign_payload("revision", revision)
    decisions = [{"edit_id": item["edit_id"], "decision": "adopt"} for item in items]
    result_sig = signing.sign_result(live24["result"])
    assembled = revise.run_assembly(revise.AssembleRequest(plan_text=live24["plan_text"], revision=revision,
                                   result=live24["result"], result_sig=result_sig, decisions=decisions), provider="mock")
    assert assembled["stats"]["merged"] == 2
    assert any(ln["text"] == "제안: " + current + " [확인 필요: 절차]" for ln in assembled["lines"])
    app = FastAPI()
    app.include_router(export.router)
    with TestClient(app) as client:
        response = client.post("/premortem/package", json={"result": live24["result"], "result_sig": result_sig,
                               "revision": revision, "revision_decisions": decisions, "revised_plan": assembled})
    assert response.status_code == 200, response.text
    assert response.headers["x-neumann-assembly-origin"] == "server_signed"


@pytest.mark.parametrize("tamper", ["session", "proposal", "reason", "decision", "quote"])
def test_all24_pairing_rejects_individually_signed_mismatches(live24, tamper):
    payload = assembled_payload(live24)
    revision = payload["revision"]
    if tamper == "session":
        payload["result"]["session_id"] = "other-analysis"
        payload["result_sig"] = signing.sign_result(payload["result"])
    elif tamper in ("proposal", "reason"):
        edit = revision["revisions"][0]["edits"][0]
        if tamper == "proposal":
            edit["proposed_text"] += " 다른 문안."
        else:
            edit["rationale"]["text"] += " 다른 이유."
        revision["revision_sig"] = signing.sign_payload("revision", {k: v for k, v in revision.items() if k != "revision_sig"})
    elif tamper == "decision":
        payload["revision_decisions"][0]["decision"] = "reject"
    else:
        import hashlib
        used = {x for c in payload["revised_plan"]["changes"] for x in c["excerpt_ids"]}
        excerpt = next(e for e in payload["result"]["evidence"] if e["excerpt_id"] in used)
        excerpt["text"] = "x" * len(excerpt["text"])
        excerpt["text_sha256"] = hashlib.sha256(excerpt["text"].encode()).hexdigest()
        payload["result_sig"] = signing.sign_result(payload["result"])
    app = FastAPI()
    app.include_router(export.router)
    with TestClient(app) as client:
        response = client.post("/premortem/package", json=payload)
    assert response.status_code == 422
