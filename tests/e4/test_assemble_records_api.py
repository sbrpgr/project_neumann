"""Saved LIVE-SMOKE-3 record reuse reaches HTTP assembly and all export formats."""

from __future__ import annotations

import io

import pytest

from neumann.analyze.assemble import validate_revised_plan
from tests.e3.test_assemble_records import decisions_of, saved_bundle
from tests.e4.test_revise_api import client, make, run, signing_contract


@pytest.mark.parametrize("format", ["json", "md", "docx"])
@pytest.mark.parametrize("reverse", [False, True])
def test_all_adopt_saved_records_http_200_and_exports(tmp_path, monkeypatch, signing_contract, saved_bundle, format, reverse):
    srv, app = make(tmp_path, monkeypatch)
    revision, result = saved_bundle["revision"], saved_bundle["result"]
    decisions = decisions_of(saved_bundle)
    if reverse:
        decisions.reverse()
    body = {"plan_text": saved_bundle["plan_text"], "revision": revision, "result": result,
            "result_sig": signing_contract.sign_result(result),
            "revision_sig": signing_contract.sign_payload("revision", revision),
            "decisions": decisions, "polish": False, "format": format}

    async def go():
        async with client(app) as c:
            response = await c.post("/premortem/revise/assemble", json=body)
        assert response.status_code == 200, response.text
        if format == "json":
            output = response.json()
            assert validate_revised_plan(output) == []
            assert output["stats"]["applied"] == 2 and output["stats"]["conflicts"] == 0
            assert output["origin"] == "server_signed" and output["revised_plan_sig"]
            assert signing_contract.verify_payload("revised-plan", {k: v for k, v in output.items() if k != "revised_plan_sig"},
                                                   output["revised_plan_sig"])
        elif format == "md":
            assert "ex_2fc1f7e58d84a04a" in response.text
            assert "The comparison may be unfair" in response.text
        else:
            from docx import Document

            document = Document(io.BytesIO(response.content))
            text = "\n".join(p.text for p in document.paragraphs)
            assert "The comparison may be unfair" in text
            assert "ex_2fc1f7e58d84a04a" in text
    run(go())
    assert srv.gate.active == srv.gate.waiting == 0


@pytest.mark.parametrize("kind", ["original", "record"])
@pytest.mark.parametrize("reverse", [False, True])
def test_other_card_links_still_http_422_without_budget_use(tmp_path, monkeypatch, saved_bundle, kind, reverse):
    srv, app = make(tmp_path, monkeypatch)
    own, other = saved_bundle["revision"]["revisions"]
    if kind == "original":
        foreign = saved_bundle["result"]["risk_cards"][1]["evidence"][0]
        own["evidence_pool"].append(foreign)
    else:
        foreign = other["evidence_pool"][-1]
    own["edits"][1]["rationale"]["excerpt_ids"] = [foreign]
    decisions = decisions_of(saved_bundle)
    if reverse:
        decisions.reverse()

    async def go():
        async with client(app) as c:
            response = await c.post("/premortem/revise/assemble", json={
                "plan_text": saved_bundle["plan_text"], "revision": saved_bundle["revision"],
                "result": saved_bundle["result"], "decisions": decisions, "polish": False})
        assert response.status_code == 422
        assert response.json()["error_code"] == "invalid_revision_proposal"
    run(go())
    assert srv.gate.active == srv.gate.waiting == srv.budget.used == 0
