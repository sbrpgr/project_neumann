"""Selected examples must remain usable without providers or private datasets."""

import hashlib
import json
import re
import socket
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import samples
from neumann.api import upload
from neumann.api.upload import UploadRejected, _clean, extract_plan
from neumann.models import PlanDocument

ROOT = Path(__file__).resolve().parents[2]
SELECTED = [s for s in samples.load_registry()["samples"] if s["status"] == "featured"]


def compact(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def test_three_domains_and_recorded_selection_evidence():
    recorded = json.loads((samples.DATA_DIR / "samples/selection.json").read_text(encoding="utf-8"))
    measured = {m["id"]: m for m in recorded["samples"]}
    assert len(SELECTED) == 3
    assert {s["domain"] for s in SELECTED} == set(samples.load_registry()["domains"])
    assert set(measured) == {s["id"] for s in SELECTED}
    for item in SELECTED:
        text = samples.text_path(item).read_text(encoding="utf-8")
        measurement = measured[item["id"]]
        assert len(text) >= 600
        assert PlanDocument.from_text(text, session_id="sample").plan_id == item["plan_id"]
        assert hashlib.sha256(text.encode()).hexdigest() == measurement["plan_sha256"]
        assert measurement["result_sha256"] == item["curation"]["result_sha256"]
        assert 4 <= measurement["cards"] <= 8
        assert measurement["quotes_verified"] == measurement["quotes_total"] > 0
        assert measurement["linkage_rate"] == 1
        assert measurement["semantic"]["cards_mismatch"] == 0
        # Historical failures must remain visible in the internal selection proof.
        assert len(measurement["past_e2e_failures"]) == item["curation"]["breakdown"]["e2e_failures"]
        assert item["curation"]["checked_by_human"] is False
        assert item["curation"]["score"] is None
        assert item["summary"].endswith("연구계획입니다.")
        assert not any(word in item["summary"] for word in ("약점", "누출", "오차 막대", "분할", "미반영", "없음"))


@pytest.mark.parametrize("item", SELECTED, ids=lambda s: s["id"])
@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_documents_recover_all_original_characters(item, fmt):
    expected = samples.text_path(item).read_text(encoding="utf-8")
    path = samples.document_path(item, fmt)
    assert path is not None and path.parent == samples.DATA_DIR / "samples/docs"
    result = extract_plan(path.name, path.read_bytes())
    assert result.kind == fmt and not result.warnings
    assert compact(result.text) == compact(expected)
    if fmt == "docx":
        assert result.text == _clean(expected, collapse_blank=True)
    else:
        assert result.pages == 1


@pytest.mark.parametrize("item", SELECTED, ids=lambda s: s["id"])
def test_hwpx_package_preserves_body_and_current_unsupported_response(item):
    path = samples.document_path(item, "hwpx")
    expected = samples.text_path(item).read_text(encoding="utf-8")
    with zipfile.ZipFile(path) as archive:
        assert archive.infolist()[0].filename == "mimetype"
        assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/hwp+zip"
        section = ET.fromstring(archive.read("Contents/section0.xml"))
        body = "\n".join(t.text or "" for t in section.iter(
            "{http://www.hancom.co.kr/hwpml/2011/paragraph}t"))
        assert body == expected.rstrip("\n")
        assert archive.read("Preview/PrvText.txt").decode("utf-8") == expected
        for name in archive.namelist():
            if name.endswith((".xml", ".hpf")):
                ET.fromstring(archive.read(name))
    try:
        result = extract_plan(path.name, path.read_bytes())
    except UploadRejected as exc:
        assert exc.status_code == 415  # HWPX-UPLOAD owns parser support.
    else:
        # The same regression remains useful after HWPX-UPLOAD is merged.
        assert compact(result.text) == compact(expected)


def test_sample_downloads_and_public_api_are_local_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("sample loading must not open a network connection")

    app = FastAPI()
    app.include_router(samples.router)
    with TestClient(app) as client:
        # Windows creates a local socket pair when the event loop starts.
        # Guard application requests after that setup, as in test_samples.py.
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        response = client.get("/templates/samples")
        assert response.status_code == 200
        for item in response.json()["samples"]:
            assert item["kind"] == "plan" and set(item["documents"]) == {"pdf", "docx", "hwpx"}
            assert "curation" not in item and "intended_weaknesses" not in item
            for fmt, link in item["documents"].items():
                download = client.get(link["url"])
                assert download.status_code == 200
                path = samples.document_path(samples.find_sample(item["id"]), fmt)
                assert download.content == path.read_bytes()
        for sample_id in ("reject-too-short", "reject-off-scope"):
            assert client.get("/templates/samples/" + sample_id).status_code == 404


@pytest.mark.parametrize("item", SELECTED, ids=lambda s: s["id"])
@pytest.mark.parametrize("fmt", ["pdf", "docx", "hwpx"])
def test_downloaded_document_can_be_submitted_to_upload_endpoint(item, fmt):
    app = FastAPI()
    app.include_router(upload.router)
    path = samples.document_path(item, fmt)
    with TestClient(app) as client:
        response = client.post("/upload/plan", files={"file": (path.name, path.read_bytes())})
    if fmt == "hwpx" and response.status_code == 415:
        assert response.json().get("detail")
    else:
        assert response.status_code == 200
        expected = samples.text_path(item).read_text(encoding="utf-8")
        assert compact(response.json()["text"]) == compact(expected)
        assert response.json()["warnings"] == []
