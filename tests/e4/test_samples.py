"""Local-only API tests, with the proposed main router ordering."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft7Validator

from neumann.api import precomputed as P, samples as S, templates as T
from neumann.models import PlanDocument

ROOT = Path(__file__).resolve().parents[2]


def registry():
    return json.loads(S.REGISTRY_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def client(monkeypatch):
    loader = S.load_registry
    loader.cache_clear()
    def unavailable(*args, **kwargs):
        raise P.PrecomputedError("not_found", "테스트 사전 계산본 없음")
    monkeypatch.setattr(S, "load_precomputed", unavailable)
    app = FastAPI()
    app.include_router(S.router)  # Exactly the main.py patch's order.
    app.include_router(T.router)
    with TestClient(app) as client:
        yield client
    loader.cache_clear()


def test_samples_schema_and_registry():
    schema = json.loads(S.SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    assert S.registry_errors(registry()) == []
    assert len(registry()["samples"]) == 17
    assert sum(s["status"] == "candidate" and not s["public_ok"] for s in registry()["samples"]) == 12


@pytest.mark.parametrize("mutate", [
    lambda r: r["samples"][0].update(path="../../.env"),
    lambda r: r["samples"][0].update(documents={"pdf": "../private.pdf"}),
    lambda r: r["samples"][0].update(plan_id="0" * 64),
    lambda r: r["samples"][0].update(field="missing"),
    lambda r: r["samples"][0].update(id=r["samples"][1]["id"]),
    lambda r: r["fields"][0].update(id=r["fields"][1]["id"]),
    lambda r: r["fields"][0].update(domain="missing"),
    lambda r: r["samples"][5].update(path=r["samples"][0]["path"]),
    lambda r: r["samples"][0].pop("public_ok"),
    lambda r: r["samples"][0].update(path=None),
])
def test_registry_rejects_bad_references(mutate):
    r = registry()
    mutate(r)
    assert S.registry_errors(r)


def test_samples_route_precedes_generic_template_and_hides_curation(client):
    response = client.get("/templates/samples")
    assert response.status_code == 200
    data = response.json()
    assert len(data["samples"]) == 5
    assert all(s["public_ok"] and s["precomputed"]["available"] is False for s in data["samples"])
    assert all(not s["documents"] for s in data["samples"])  # Pending files are not offered.
    blob = json.dumps(data)
    for internal in ("curation", "intended_weaknesses", "result_file", "result_hint", "keywords", "path"):
        assert '"' + internal + '"' not in blob
    assert client.get("/templates/materials-gnn").status_code == 200


@pytest.mark.parametrize("index", range(5))
def test_public_body_verbatim(client, index):
    item = registry()["samples"][index]
    response = client.get("/templates/samples/" + item["id"])
    assert response.status_code == 200
    assert response.json()["text"] == (ROOT / item["path"]).read_text(encoding="utf-8")
    assert response.json()["chars"] == len(response.json()["text"])


@pytest.mark.parametrize("index", range(5))
def test_original_sample_gate_expectations_without_llm(index):
    from neumann.analyze.fitness import rule_fitness

    item = registry()["samples"][index]
    text = (ROOT / item["path"]).read_text(encoding="utf-8")
    plan = PlanDocument.from_text(text, session_id="sample-gate-test")
    verdict = "reject" if len(plan.text) < 300 else ("ok" if rule_fitness(plan)["verdict"] == "fit" else "reject")
    assert verdict == item["expect_gate"]
    if item["id"] == "reject-off-scope":
        assert rule_fitness(plan)["verdict"] == "unfit"


@pytest.mark.parametrize("status,public", [("featured", False), ("candidate", False), ("candidate", True), ("retired", True)])
def test_nonpublic_and_unselected_never_exposed(client, monkeypatch, status, public):
    r = registry()
    item = r["samples"][0]
    item.update(status=status, public_ok=public)
    monkeypatch.setattr(S, "load_registry", lambda: r)
    assert item["id"] not in {s["id"] for s in client.get("/templates/samples").json()["samples"]}
    for suffix in ("", "/view", "/document/pdf", "/document/docx", "/document/hwpx"):
        assert client.get("/templates/samples/" + item["id"] + suffix).status_code == 404


@pytest.mark.parametrize("bad", ["no-such-sample", "..%2f..%2f.env", "%2e%2e", "a" * 256, "example-battery/document/..%2fprivate.pdf"])
def test_request_path_attacks(client, bad):
    assert client.get("/templates/samples/" + bad).status_code == 404


def test_document_only_registry_filename_and_existing_file(client, monkeypatch, tmp_path):
    r = registry()
    item = r["samples"][0]
    item["documents"] = {"pdf": "allowed.pdf"}
    monkeypatch.setattr(S, "load_registry", lambda: r)
    monkeypatch.setattr(S, "DOCUMENT_DIR", tmp_path)
    assert client.get("/templates/samples/example-battery/document/pdf").status_code == 404
    content = b"%PDF-test-only"
    (tmp_path / "allowed.pdf").write_bytes(content)
    response = client.get("/templates/samples/example-battery/document/pdf")
    assert response.status_code == 200 and response.content == content
    assert response.headers["content-type"] == "application/pdf"
    assert "allowed.pdf" in response.headers["content-disposition"]
    assert client.get("/templates/samples/example-battery/document/zip").status_code == 404
    item["documents"]["pdf"] = "../outside.pdf"
    assert client.get("/templates/samples/example-battery/document/pdf").status_code == 500


@pytest.mark.parametrize("fmt", ["pdf", "docx", "hwpx"])
def test_symlink_document_cannot_escape(tmp_path, monkeypatch, fmt):
    outside = tmp_path / ("outside." + fmt)
    outside.write_bytes(b"private")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    link = allowed / ("safe." + fmt)
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    monkeypatch.setattr(S, "DOCUMENT_DIR", allowed)
    with pytest.raises(S.RegistryError):
        S.document_path({"documents": {fmt: link.name}}, fmt)


def precomputed_disk(tmp_path, source="pipeline", *, mock=False, offline=False):
    result = json.loads((ROOT / "tests/fixtures/premortem_result.json").read_text(encoding="utf-8"))
    if not mock:
        for card in result["risk_cards"]:
            card["generator"] = "astra"
            card["model"] = "gpt-6.1-sol"
        result["stages"] = [{"name": "cards", "status": "ok", "impl": "pipeline"}]
        result["notices"] = []
        result["manifest"] = {"llm_provider": "openai", "llm_model": "gpt-6.1-sol"}
        if offline:
            result["manifest"] = {"generation": S.OFFLINE_LABEL}
    raw = P.encode_json(result)
    plan_id = result["plan_id"]
    (tmp_path / (plan_id + ".json")).write_bytes(raw)
    entry = {"plan_id": plan_id, "file": plan_id + ".json", "source": source,
             "sha256": P.sha256_bytes(raw), "generated_at": result["generated_at"]}
    (tmp_path / "manifest.json").write_bytes(P.encode_json({"kind": P.MANIFEST_KIND, "entries": [entry]}))
    return plan_id


@pytest.mark.parametrize("source,mock", [("fixture", False), ("pipeline", True)])
def test_fixture_and_mock_never_get_instant_badge_or_view(client, monkeypatch, tmp_path, source, mock):
    precomputed_disk(tmp_path, source, mock=mock)
    monkeypatch.setattr(S, "load_precomputed", lambda key: P.load_precomputed(key, tmp_path))
    data = client.get("/templates/samples").json()
    assert data["samples"][0]["precomputed"]["available"] is False
    assert client.get("/templates/samples/example-battery/view").status_code == 404


@pytest.mark.parametrize("offline", [False, True])
def test_valid_precomputed_view_marked_and_contract_checked(client, monkeypatch, tmp_path, offline):
    precomputed_disk(tmp_path, offline=offline)
    monkeypatch.setattr(S, "load_precomputed", lambda key: P.load_precomputed(key, tmp_path))
    item = client.get("/templates/samples").json()["samples"][0]
    assert item["precomputed"]["available"] is True
    assert (item["precomputed"]["generation"] == S.OFFLINE_LABEL) == offline
    response = client.get(item["precomputed"]["url"])
    assert response.status_code == 200 and response.headers["X-Neumann-Precomputed"] == "1"
    view = response.json()
    assert S.PRECOMPUTED_LABEL in view["_status"]["label"]
    assert (S.OFFLINE_LABEL in view["_status"]["label"]) == offline
    schema = json.loads((ROOT / "contracts/ui_view.schema.json").read_text(encoding="utf-8"))
    base = {k: v for k, v in view.items() if not k.startswith("_")}
    assert not list(Draft7Validator(schema).iter_errors(base))


def test_precomputed_label_preserves_degradation(client, monkeypatch, tmp_path):
    plan_id = precomputed_disk(tmp_path)
    file = tmp_path / (plan_id + ".json")
    data = json.loads(file.read_bytes())
    data["status"] = "degraded"
    raw = P.encode_json(data)
    file.write_bytes(raw)
    manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    manifest["entries"][0]["sha256"] = P.sha256_bytes(raw)
    (tmp_path / "manifest.json").write_bytes(P.encode_json(manifest))
    monkeypatch.setattr(S, "load_precomputed", lambda key: P.load_precomputed(key, tmp_path))
    view = client.get("/templates/samples/example-battery/view").json()
    assert view["_status"]["degraded"] is True
    assert "일부 단계 강등" in view["_status"]["label"] and S.PRECOMPUTED_LABEL in view["_status"]["label"]


def test_tampered_precomputed_unavailable(client, monkeypatch, tmp_path):
    plan_id = precomputed_disk(tmp_path)
    (tmp_path / (plan_id + ".json")).write_bytes(b"tampered")
    monkeypatch.setattr(S, "load_precomputed", lambda key: P.load_precomputed(key, tmp_path))
    assert client.get("/templates/samples").json()["samples"][0]["precomputed"]["available"] is False
    assert client.get("/templates/samples/example-battery/view").status_code == 404


def test_registry_failure_is_visible(client, monkeypatch):
    def broken():
        raise S.RegistryError("시험용 레지스트리 오류")
    monkeypatch.setattr(S, "load_registry", broken)
    for route in ("", "/example-battery", "/example-battery/view", "/example-battery/document/pdf"):
        response = client.get("/templates/samples" + route)
        assert response.status_code == 500 and response.json()["status"] == "error"


def test_api_local_reads_do_not_open_network_sockets(client, monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Sample routes must not connect to a network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    precomputed_disk(tmp_path)
    monkeypatch.setattr(S, "load_precomputed", lambda key: P.load_precomputed(key, tmp_path))
    assert client.get("/templates/samples").status_code == 200
    assert client.get("/templates/samples/example-battery").status_code == 200
    assert client.get("/templates/samples/example-battery/view").status_code == 200


def test_unknown_candidate_cases_not_served(client):
    for item in registry()["samples"][5:]:
        for suffix in ("", "/view", "/document/pdf"):
            assert client.get("/templates/samples/" + item["id"] + suffix).status_code == 404


def test_patch_order_matches_test_app():
    patch = (ROOT / "docs/reports/E4-L1g_main.patch").read_text(encoding="utf-8")
    assert patch.index('+    "neumann.api.samples"') < patch.index('     "neumann.api.templates"')
    # New code is read-only and must not import the analysis execution path.
    source = (ROOT / "src/neumann/api/samples.py").read_text(encoding="utf-8")
    assert "run_premortem" not in source and "neumann.llm" not in source
