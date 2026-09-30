import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import export
from neumann.api.signing import sign_result
from neumann.models import PlanDocument, PremortemResult
from tests.fixtures.loader import load_fixtures


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(export.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("audit", [1, [1], [], {}])
def test_audit_shape(client, audit):
    data = load_fixtures().premortem_result.model_dump(mode="json")
    data["expected_review"]["audit"] = audit
    # The public HMAC helper is only a synthetic fixture signer, not a public forgery claim.
    response = client.post("/premortem/package", json={"result": data, "result_sig": sign_result(data)})
    assert response.status_code == (200 if isinstance(audit, dict) else 422)
    if isinstance(audit, dict):
        assert response.headers["x-neumann-result-origin"] == "server_signed"


@pytest.mark.parametrize("kind, status", [("chars", 413), ("lines", 422), ("embedded_chars", 413), ("embedded_lines", 422)])
def test_raw_refusal_before_models_nfc_context(client, monkeypatch, kind, status):
    data = load_fixtures().premortem_result.model_dump(mode="json")
    payload = {"result": data}
    if kind.startswith("embedded"):
        data["plan"]["lines"] = ([{"no": 1, "text": "가" * 200_001}] if kind == "embedded_chars"
                                 else [{"no": i + 1, "text": "x"} for i in range(5001)])
    else:
        payload["plan_text"] = "가" * 200_001 if kind == "chars" else "x\n" * 5000
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("expensive path reached")

    monkeypatch.setattr(PremortemResult, "model_validate", forbidden)
    monkeypatch.setattr(PlanDocument, "from_text", forbidden)
    monkeypatch.setattr(export, "_make_ctx", forbidden)
    response = client.post("/premortem/package", json=payload)
    assert response.status_code == status
    assert calls == []
    with pytest.raises(Exception) as refusal:
        export.build_package_files(data, plan_text=payload.get("plan_text"))
    assert getattr(refusal.value, "status_code", None) == status
    assert calls == []


@pytest.mark.parametrize("body", ["  e\u0301  \r\n가\t ", "x" * 50_000, "x\n" * 4999 + "x"], ids=["padding", "public-char-boundary", "line-boundary"])
def test_valid_padding_boundaries_hash_and_content_preserved(client, monkeypatch, body):
    plan = PlanDocument.from_text(body, "raw-boundary")
    resolved = []
    original = export._resolve_plan

    def capture(result, plan_text):
        assert plan_text == body
        value = original(result, plan_text)
        resolved.append(value[0].lines)
        return value

    monkeypatch.setattr(export, "_resolve_plan", capture)
    data = load_fixtures().premortem_result.model_dump(mode="json")
    data.update(plan=None, plan_id=plan.plan_id)
    response = client.post("/premortem/package", json={"result": data, "result_sig": sign_result(data), "plan_text": body})
    assert response.status_code == 200
    assert response.headers["x-neumann-plan-association"] == "hash_verified"
    assert resolved and all(lines == plan.lines for lines in resolved)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 9
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["result"]["plan_id"] == plan.plan_id
        for line in plan.lines:
            # Existing Markdown rendering trims trailing whitespace; source/hash remain exact.
            assert line.text.rstrip() in archive.read("plan_annotated.md").decode()


def test_raw_guard_boundary_preserves_input():
    data = load_fixtures().premortem_result.model_dump(mode="json")
    body = "x" * 200_000
    before = json.dumps(data, ensure_ascii=False)
    export._guard_export_plan(data, body)
    assert json.dumps(data, ensure_ascii=False) == before
    assert len(body) == 200_000
