"""E3-L2r 내보내기 연동: ZIP에 수정 권고(revision.json)·통합본(revised_plan.md)이 덧붙고, 없으면 9파일 그대로.
결정의 edit_id는 권고 안에 있어야 하고(422), plan_id가 다르면 거절한다."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.analyze import assemble as asm
from neumann.analyze import revise
from neumann.api import export_revision
from neumann.api.export import FILE_NAMES, build_package, router
from neumann.llm import MockProvider
from tests.e3.revise_fixtures import make_store
from tests.fixtures.loader import load_fixtures, plan_text
from tests.e4.test_revise_api import signing_contract


@pytest.fixture(scope="module")
def bundle() -> dict[str, Any]:
    from neumann.analyze.mock_responders import default_responders

    return revise.revise_result(load_fixtures().premortem_result, store=make_store(), llm=MockProvider(default_responders()))


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        return {i.filename: zf.read(i) for i in zf.infolist()}


def edits(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for r in bundle["revisions"] for e in r["edits"]]


def test_zip_without_revision_is_still_nine_files():
    files = unzip(build_package(load_fixtures().premortem_result))
    assert list(files) == list(FILE_NAMES)
    assert json.loads(files["manifest.json"])["extra_files"] == []


def test_zip_with_revision_and_revised_plan_adds_two_files(bundle):
    result = load_fixtures().premortem_result
    e = edits(bundle)
    decisions = [{"edit_id": e[0]["edit_id"], "decision": "채택"},
                 {"edit_id": e[1]["edit_id"], "decision": "modify", "revised_text": "직접 쓴 문장 mail@example.org", "note": "메모"}]
    plan = asm.assemble_revised_plan(plan_text("plan.md"), bundle, decisions)
    files = unzip(build_package(result, revision=bundle, revision_decisions=decisions, revised_plan=plan))
    assert list(files) == [*FILE_NAMES, "revision.json", "revised_plan.md"]
    manifest = json.loads(files["manifest.json"])
    assert manifest["extra_files"] == ["revision.json", "revised_plan.md"]
    listed = {f["path"]: f for f in manifest["files"]}
    assert "revision.json" in listed and listed["revised_plan.md"]["bytes"] == len(files["revised_plan.md"])
    rev = json.loads(files["revision.json"])
    assert rev["origin"] == "client_submitted_unverified" and rev["revision"]["plan_id"] == result.plan_id
    assert [d["decision"] for d in rev["decisions"]] == ["adopt", "modify"]
    assert "[EMAIL]" in rev["decisions"][1]["revised_text"] and "@" not in rev["decisions"][1]["revised_text"]
    assert rev["decisions"][0]["card_id"] == "card-fx-leak"
    md = files["revised_plan.md"].decode("utf-8")
    assert "[^1]" in md and "## 수정 이력" in md and "Neumann 수정 제안" in md
    readme = files["README.md"].decode("utf-8")
    assert "revision.json" in readme and "수정 권고(E3-L2r)" in readme and "통합본" in readme


def test_unknown_edit_id_and_plan_mismatch_rejected(bundle):
    result = load_fixtures().premortem_result
    with pytest.raises(ValueError, match="edit_id"):
        build_package(result, revision=bundle, revision_decisions=[{"edit_id": "nope/e1", "decision": "adopt"}])
    other = {**bundle, "plan_id": "0" * 64}
    with pytest.raises(ValueError, match="plan_id"):
        build_package(result, revision=other)
    with pytest.raises(ValueError, match="계약"):
        build_package(result, revision={"version": "x"})
    with pytest.raises(ValueError):
        build_package(result, revision_decisions=[{"edit_id": "x", "decision": "adopt"}])


def test_identity_fields_are_impossible_on_decision():
    with pytest.raises(TypeError):
        type("Bad", (export_revision.RevisionDecision,), {"__annotations__": {"reviewer_name": str}})


def test_package_route_accepts_revision(bundle):
    app = FastAPI()
    app.include_router(router)
    result = load_fixtures().premortem_result.model_dump(mode="json")
    e = edits(bundle)
    with TestClient(app) as c:
        r = c.post("/premortem/package", json={"result": result, "revision": bundle,
                                               "revision_decisions": [{"edit_id": e[0]["edit_id"], "decision": "기각"}]})
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        files = unzip(r.content)
        assert "revision.json" in files and "revised_plan.md" not in files
        bad = c.post("/premortem/package", json={"result": result, "revision": bundle,
                                                 "revision_decisions": [{"edit_id": "x/e9", "decision": "adopt"}]})
        assert bad.status_code == 422


def test_revision_origin_requires_both_result_and_revision_signatures(bundle, signing_contract):
    from neumann.api import revise as api

    result = load_fixtures().premortem_result
    result_sig = signing_contract.sign_result(result)
    body = {**bundle, "origin": "server_signed"}
    sig = api.sign_payload("revision", body)
    revision = {**body, "revision_sig": sig}
    assert export_revision._origin(revision, sig, result, result_sig) == "server_signed"
    assert export_revision._origin(revision, sig, result) == "client_submitted_unverified"
    assert export_revision._origin(revision, "비ASCII", result, result_sig) == "client_submitted_unverified"
    changed = result.model_copy(update={"session_id": result.session_id + "-forged"})
    assert export_revision._origin(revision, sig, changed, result_sig) == "client_submitted_unverified"
    files = export_revision.extra_files(result, revision, [], None, sig, result_sig)
    assert json.loads(files["revision.json"])["origin"] == "server_signed"


def test_unverified_plan_markdown_and_generator_are_not_trusted(bundle):
    import copy

    result = load_fixtures().premortem_result
    forged = copy.deepcopy(bundle)
    forged["generator"] = "astra"
    forged["model"] = "gpt-forged"
    edit = edits(forged)[0]
    out = asm.assemble_revised_plan(plan_text("plan.md"), forged, [{"edit_id": edit["edit_id"], "decision": "adopt"}])
    out["markdown"] = {"footnoted": "FORGED LLM mail@example.org", "history": "FORGED HISTORY"}
    files = export_revision.extra_files(result, forged, [], out)
    md = files["revised_plan.md"].decode()
    assert "FORGED" not in md and "gpt-forged" not in md and "mail@example.org" not in md
    assert "client_submitted_unverified" in md


def test_pii_excerpt_is_withheld_from_markdown(bundle):
    import copy

    result = load_fixtures().premortem_result.model_dump(mode="json")
    result["evidence"][0]["text"] = "Private contact mail@example.org"
    forged = copy.deepcopy(bundle)
    edit = edits(forged)[0]
    edit["rationale"]["excerpt_ids"] = [result["evidence"][0]["excerpt_id"]]
    out = asm.assemble_revised_plan(plan_text("plan.md"), forged, [{"edit_id": edit["edit_id"], "decision": "adopt"}])
    markdown = asm.render_markdown(out, asm.evidence_lookup(result, forged), generator="client_submitted_unverified")
    assert "mail@example.org" not in json.dumps(markdown, ensure_ascii=False)
    assert "개인정보가 포함된 발췌는 표시하지 않음" in markdown["footnoted"]
