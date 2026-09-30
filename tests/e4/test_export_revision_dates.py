"""Narrow core regression: local revision trust and deterministic date rejection."""

import copy
import io
import json
import zipfile
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import export, export_revision
from neumann.analyze import assemble
from neumann.api.signing import sign_payload, sign_result
from neumann.models import PremortemResult
from tests.e4.test_export_revision import bundle
from tests.fixtures.loader import load_fixtures, plan_text


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(export.router)
    return TestClient(app, raise_server_exceptions=False)


def package(client, result, **extras):
    data = result.model_dump(mode="json")
    return client.post("/premortem/package", json={"result": data, "result_sig": sign_result(data), **extras})


def members(response):
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.parametrize("mode", ["unsigned", "signed", "changed_model", "missing_result_sig"])
def test_revision_summary_qualifies_its_own_origin_and_preserves_json(client, bundle, mode):
    result = load_fixtures().premortem_result
    revision = copy.deepcopy(bundle)
    revision.update(generator="astra", model="FORGED_MODEL_SENTINEL", origin="server_signed")
    revision_sig = sign_payload("revision", revision) if mode != "unsigned" else None
    if mode == "changed_model":
        revision["model"] = "TAMPERED_MODEL_SENTINEL"
    data = result.model_dump(mode="json")
    response = client.post("/premortem/package", json={
        "result": data, "result_sig": None if mode == "missing_result_sig" else sign_result(data),
        "revision": revision, "revision_sig": revision_sig,
    })
    files = members(response)
    origin = "server_signed" if mode == "signed" else "client_submitted_unverified"
    rendered_revision = json.loads(files["revision.json"])
    assert rendered_revision["origin"] == origin
    assert rendered_revision["revision"] == revision  # JSON source is kept, not relabelled as a different generator.
    summary = next(line for line in files["README.md"].decode().splitlines() if line.startswith("- 수정 권고(`"))
    assert f"수정 권고 출처: {origin}" in summary
    if mode == "signed":
        assert "생성 astra(FORGED_MODEL_SENTINEL)" in summary
    else:
        assert "MODEL_SENTINEL" not in summary
        assert "생성 표기 미확인" in summary
    if mode != "missing_result_sig":
        assert response.headers["x-neumann-result-origin"] == "server_signed"
    assert len(files) == 10


BAD_DATES = ["2200-01-01T00:00:00Z", "9999-12-31T23:59:59-10:00", "0001-01-01T00:00:00+10:00"]


@pytest.mark.parametrize("timestamp", BAD_DATES)
@pytest.mark.parametrize("signed", [True, False])
def test_latest_three_date_counterexamples_return_422(client, timestamp, signed):
    data = load_fixtures().premortem_result.model_dump(mode="json")
    data["generated_at"] = timestamp
    result = PremortemResult.model_validate(data)
    payload = {"result": result.model_dump(mode="json")}
    if signed:
        payload["result_sig"] = sign_result(result)
    response = client.post("/premortem/package", json=payload)
    assert response.status_code == 422, (response.status_code, response.headers.get("content-type"))
    assert "날짜" in response.json()["detail"]
    assert "x-neumann-result-origin" not in response.headers
    with pytest.raises(ValueError, match="날짜"):
        export.build_package(result)


@pytest.mark.parametrize("timestamp, expected", [
    ("1980-01-01T00:00:00Z", (1980, 1, 1, 0, 0, 0)),
    ("2020-02-29T12:34:56Z", (2020, 2, 29, 12, 34, 56)),
    ("2107-12-31T23:59:58Z", (2107, 12, 31, 23, 59, 58)),
    ("2108-01-01T00:59:58+01:00", (2107, 12, 31, 23, 59, 58)),
])
def test_signed_zip_date_boundaries_and_history_are_exact(client, timestamp, expected):
    data = load_fixtures().premortem_result.model_dump(mode="json")
    data["generated_at"] = timestamp
    result = PremortemResult.model_validate(data)
    response = package(client, result)
    files = members(response)
    assert list(files) == list(export.FILE_NAMES)
    assert response.headers["x-neumann-result-origin"] == "server_signed"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert all(info.date_time == expected for info in archive.infolist())
    assert json.loads(files["manifest.json"])["result"]["generated_at"] == result.generated_at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def test_no_clamping_of_unsupported_zip_year(client):
    result = load_fixtures().premortem_result.model_copy(update={"generated_at": datetime(1979, 12, 31, tzinfo=UTC)})
    assert package(client, result).status_code == 422


def test_created_at_overflow_is_a_value_error():
    result = load_fixtures().premortem_result
    bad = datetime.fromisoformat("9999-12-31T23:59:59-10:00")
    with pytest.raises(ValueError, match="날짜"):
        export.build_package_files(result, created_at=bad)


@pytest.mark.parametrize("mode", ["signed", "bad_revision_sig", "bad_assembly_sig"])
def test_assembly_summary_has_independent_signature_binding(client, bundle, mode):
    result = load_fixtures().premortem_result
    revision = {**copy.deepcopy(bundle), "origin": "server_signed"}
    revision_sig = sign_payload("revision", revision)
    revised = assemble.assemble_revised_plan(plan_text("plan.md"), revision, [])
    revised["origin"] = "server_signed"
    revised["revised_plan_sig"] = sign_payload("revised-plan", revised)
    if mode == "bad_revision_sig":
        revision_sig = "v1." + "0" * 64
    elif mode == "bad_assembly_sig":
        revised["revised_plan_sig"] = "v1." + "0" * 64
    files = members(package(client, result, revision=revision, revision_sig=revision_sig, revised_plan=revised))
    line = next(line for line in files["README.md"].decode().splitlines() if line.startswith("- 통합본(`"))
    origin = "server_signed" if mode == "signed" else "client_submitted_unverified"
    assert f"통합본 출처: {origin}" in line
    assert len(files) == 11
    markdown = files["revised_plan.md"].decode()
    assert ("client_submitted_unverified" in markdown) is (mode != "signed")
