"""Result HMAC provenance must not authenticate an unrelated supplemental plan."""

import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import export
from neumann.api.signing import sign_result
from neumann.models import PlanDocument
from tests.fixtures.loader import load_fixtures, plan_text


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(export.router)
    return TestClient(app)


def result():
    return load_fixtures().premortem_result.model_dump(mode="json")


def package(client, data, body=None, sig=None):
    payload = {"result": data, "result_sig": sig if sig is not None else sign_result(data)}
    if body is not None:
        payload["plan_text"] = body
    return client.post("/premortem/package", json=payload)


@pytest.mark.parametrize("body", ["different plan", plan_text("plan.md") + "\n바뀐 줄"], ids=["original-fail", "tampered-body"])
def test_original_fail_and_tampered_supplemental_body_are_rejected(client, body):
    data = result()
    data["plan"] = None
    response = package(client, data, body)
    assert response.status_code == 422
    assert "해시" in response.json()["detail"]
    assert "x-neumann-result-origin" not in response.headers
    assert "different plan" not in response.text


def files(response):
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == list(export.FILE_NAMES)
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.parametrize("mode, association, verified", [
    ("original", "signed_result_plan", True),
    ("hash", "hash_verified", True),
    ("missing", "missing", False),
    ("unsigned", "unverified", False),
])
def test_result_signature_and_plan_authority_are_distinct_across_package(client, mode, association, verified):
    data = result()
    body = None
    if mode in {"hash", "missing", "unsigned"}:
        data["plan"] = None
    if mode in {"hash", "unsigned"}:
        body = plan_text("plan.md")
    response = package(client, data, body, sig="invalid" if mode == "unsigned" else None)
    members = files(response)
    origin = "client_submitted_unverified" if mode == "unsigned" else "server_signed"
    assert response.headers["x-neumann-result-origin"] == origin
    assert response.headers["x-neumann-plan-association"] == association
    manifest = json.loads(members["manifest.json"])
    assert manifest["result_origin"] == origin
    assert manifest["plan_association"] == association
    assert manifest["plan_verified"] is verified
    # The manifest accounts for all nine members without changing card-list or CSV formats.
    assert {entry["path"] for entry in manifest["files"]} | {"manifest.json"} == set(export.FILE_NAMES)
    for entry in manifest["files"]:
        assert entry["plan_association"] == association
        assert entry["result_origin"] == origin
        assert entry["plan_verified"] is verified
    for name in ("evidence_pack.json", "decision_log.json"):
        metadata = json.loads(members[name])
        assert metadata["plan_association"] == association
        assert metadata["plan_verified"] is verified
    for name in ("README.md", "neumann_report.md", "ai_context.md", "plan_annotated.md"):
        text = members[name].decode("utf-8")
        assert f"계획서 연결 상태: `{association}`" in text
        assert "결과 서명은 결과 JSON에만 적용" in text
        if not verified:
            assert "계획서 본문을 서버 검증된 입력으로 보증하지 않는다" in text


def test_original_plan_takes_precedence_over_unrelated_supplement(client):
    response = package(client, result(), "different plan")
    members = files(response)
    assert response.headers["x-neumann-plan-association"] == "signed_result_plan"
    assert b"different plan" not in members["plan_annotated.md"]


def test_unverifiable_plan_id_cannot_authorise_supplemental_body(client):
    data = result()
    data.update(plan=None, plan_id="legacy-plan-id")
    assert package(client, data, "different plan").status_code == 422


def test_hash_checks_normalised_masked_body(client):
    body = "# 계획\r\n문의: researcher@example.org\r\n"
    plan = PlanDocument.from_text(body, "authority-test")
    data = result()
    data.update(plan=None, plan_id=plan.plan_id)
    members = files(package(client, data, body))
    assert json.loads(members["manifest.json"])["plan_association"] == "hash_verified"
    assert b"researcher@example.org" not in b"".join(members.values())


def test_changed_original_body_invalidates_existing_signature(client):
    data = result()
    sig = sign_result(data)
    changed = PlanDocument.from_text(data["plan"]["lines"][0]["text"] + "\n바뀐 본문", data["session_id"])
    data.update(plan=changed.model_dump(mode="json"), plan_id=changed.plan_id)
    response = package(client, data, sig=sig)
    assert response.headers["x-neumann-result-origin"] == "client_submitted_unverified"
    assert json.loads(files(response)["manifest.json"])["plan_verified"] is False


def test_signed_hash_matched_export_revise_assemble_connection(tmp_path, monkeypatch):
    import asyncio

    from neumann.analyze import revise as revise_module
    from neumann.api.signing import verify_payload
    from tests.e3.revise_fixtures import make_store
    from tests.e4.test_revise_api import client as async_client, make

    monkeypatch.setattr(revise_module, "default_record_store", lambda: make_store())
    _, app = make(tmp_path, monkeypatch)
    app.include_router(export.router)
    data = result()
    data["plan"] = None
    sig = sign_result(data)
    body = plan_text("plan.md")

    async def connected():
        async with async_client(app) as http:
            revision_response = await http.post("/premortem/revise", json={
                "result": data, "result_sig": sig, "plan_text": body,
            })
            assert revision_response.status_code == 200, revision_response.text
            revision = revision_response.json()
            assert revision["origin"] == "server_signed" and revision["revision_sig"]
            assembly_response = await http.post("/premortem/revise/assemble", json={
                "result": data, "result_sig": sig, "plan_text": body,
                "revision": revision, "decisions": [],
            })
            assert assembly_response.status_code == 200, assembly_response.text
            assembly = assembly_response.json()
            assert assembly["origin"] == "server_signed"
            assert verify_payload("revised-plan", {k: v for k, v in assembly.items() if k != "revised_plan_sig"},
                                  assembly["revised_plan_sig"])
            response = await http.post("/premortem/package", json={
                "result": data, "result_sig": sig, "plan_text": body,
                "revision": revision, "revision_sig": revision["revision_sig"], "revised_plan": assembly,
            })
            assert response.status_code == 200, response.text
            assert response.headers["x-neumann-result-origin"] == "server_signed"
            assert response.headers["x-neumann-plan-association"] == "hash_verified"
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                assert archive.namelist() == [*export.FILE_NAMES, "revision.json", "revised_plan.md"]
                assert json.loads(archive.read("revision.json"))["origin"] == "server_signed"
                rendered = archive.read("revised_plan.md").decode("utf-8")
                assert "client_submitted_unverified" not in rendered
                assert "mock" in rendered
                # Input plan authority must not pretend to authenticate a derived plan's body.
                entries = json.loads(archive.read("manifest.json"))["files"]
                assert all("plan_association" not in entry for entry in entries if entry["path"] not in export.FILE_NAMES)

    asyncio.run(connected())
