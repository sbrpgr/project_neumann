"""origin/main 통합 후보: 경로 조작·실제 XML 상한·SEC-7 보존 회귀."""

import json
import os
from pathlib import Path
import socket
import threading
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from neumann.api import hwpx, upload
from tests.e4.test_upload_hwpx import _app, content_hpf, make_hwpx, p, section


@pytest.mark.parametrize("name", [
    "../../escape.xml", "/tmp/escape.xml", "C:\\temp\\escape.xml",
    "Contents/../section0.xml", "Contents\\evil.xml",
])
def test_path_manipulation_never_reads_or_extracts_untrusted_members(monkeypatch, tmp_path, name):
    target = tmp_path / "escape.xml"
    target.write_text("disk-marker", encoding="utf-8")
    data = make_hwpx([section(p("safe-body"))], extra={name: b"untrusted-body"})
    original_read = zipfile.ZipFile.read

    def guarded_read(self, member, *args, **kwargs):
        member_name = member.filename if isinstance(member, zipfile.ZipInfo) else member
        assert member_name in {"Contents/section0.xml", "Contents/content.hpf", "META-INF/manifest.xml"}
        return original_read(self, member, *args, **kwargs)

    def forbidden_extract(*args, **kwargs):
        pytest.fail("upload must never extract ZIP members to disk")

    monkeypatch.setattr(zipfile.ZipFile, "read", guarded_read)
    monkeypatch.setattr(zipfile.ZipFile, "extract", forbidden_extract)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", forbidden_extract)
    result = upload.extract_plan("../../plan.hwpx", data)
    assert result.filename == "plan.hwpx" and result.text == "safe-body"
    assert target.read_text(encoding="utf-8") == "disk-marker"


@pytest.mark.parametrize("href", ["../../escape.xml", "file:///tmp/escape.xml", "http://127.0.0.1:9/escape.xml"])
def test_manifest_spine_cannot_read_external_or_traversal_target(href):
    hpf = content_hpf(1).replace(b"Contents/section0.xml", href.encode())
    result = upload.extract_plan("plan.hwpx", make_hwpx([section(p("safe-body"))], hpf=hpf))
    assert result.text == "safe-body"


def test_actual_xml_element_cap_includes_hidden_nodes_and_rejects_before_preview():
    # ZIP_STORED keeps this below the byte limit without triggering the compression ratio guard.
    raw = b"<sec><header>" + b"<x/>" * hwpx.XML_MAX_ELEMENTS + b"</header></sec>"
    data = make_hwpx([raw], compression=zipfile.ZIP_STORED)
    with pytest.raises(upload.UploadRejected) as exc:
        upload.extract_plan("large.hwpx", data)
    assert (exc.value.status_code, exc.value.message) == (413, hwpx.HWPX_TOO_COMPLEX_MESSAGE)


def test_hwpx_inherits_main_line_limit():
    data = make_hwpx([section(*(p("x") for _ in range(upload.MAX_PLAN_LINES + 1)))], compression=zipfile.ZIP_STORED)
    with pytest.raises(upload.UploadRejected) as exc:
        upload.extract_plan("lines.hwpx", data)
    assert (exc.value.status_code, exc.value.message) == (422, upload.TOO_MANY_LINES_MESSAGE)


def test_http_rejects_giant_xml_bytes_before_worker(monkeypatch):
    data = make_hwpx([b"x" * (upload.MAX_ZIP_UNCOMPRESSED + 1)])
    monkeypatch.setattr(upload, "_run_worker", lambda *_: pytest.fail("must reject before worker"))
    with TestClient(_app()) as client:
        response = client.post("/upload/plan", files={"file": ("large.hwpx", data, "application/hwp+zip")})
    assert response.status_code == 413 and response.json() == {"detail": upload.ZIP_BOMB_MESSAGE}


@pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="headless browser opt-in")
def test_headless_upload_reaches_analysis_with_identical_text():
    """81xx mock 서버: 실제 업로드 경로 → 입력 반영 → 분석 요청 경계. 검색·LLM은 실행하지 않는다."""
    import uvicorn
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from playwright.sync_api import sync_playwright

    app = FastAPI()
    app.include_router(upload.router)

    @app.get("/health")
    def health():
        return {"version": "test", "pipeline": {"state": "unavailable", "label": "시험 모드"}}

    root = Path(__file__).resolve().parents[2]
    app.mount("/", StaticFiles(directory=root / "src/neumann/webui", html=True), name="webui")
    listener = socket.socket()
    for port in range(8180, 8200):
        try:
            listener.bind(("127.0.0.1", port))
            break
        except OSError:
            continue
    else:
        listener.close()
        pytest.fail("no free 81xx port")
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    out = root / "out/hwpx-upload"
    out.mkdir(parents=True, exist_ok=True)
    measurements = []
    try:
        assert server.started
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for width in (1440, 390):
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    errors = []
                    page.on("pageerror", lambda err: errors.append(str(err)))
                    page.route("**/premortem/jobs", lambda route: route.fulfill(
                        status=503, content_type="application/json",
                        body=json.dumps({"error_code": "blocked", "message": "시험 경계 확인"})))
                    page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                    page.click('[data-mode="file"]')
                    assert ".hwpx" in page.locator("#fileIn").get_attribute("accept")
                    data = make_hwpx([section(*(p("계획서 본문 " + str(i) + " 검증 가능한 연구 방법을 작성합니다.") for i in range(30)))])
                    with page.expect_response(lambda r: r.url.endswith("/upload/plan")) as received:
                        page.set_input_files("#fileIn", {"name": "plan.hwpx", "mimeType": "application/hwp+zip", "buffer": data})
                    response = received.value
                    assert response.status == 200
                    extracted = response.json()["text"]
                    page.wait_for_function("document.querySelector('.file .fn')?.textContent === 'plan.hwpx'")
                    assert "HWPX" in page.locator(".file .fm").inner_text()
                    page.screenshot(path=str(out / f"upload-{width}.png"), full_page=True)
                    overflow = page.evaluate("Math.max(0, document.documentElement.scrollWidth - innerWidth)")
                    with page.expect_request(lambda r: r.url.endswith("/premortem/jobs")) as sent:
                        page.click("#btnStart")
                    assert sent.value.post_data_json["plan_text"] == extracted
                    assert sent.value.post_data_json["filename"] == "plan.hwpx"
                    page.wait_for_selector("#jobErr")
                    page.screenshot(path=str(out / f"analysis-{width}.png"), full_page=True)
                    page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                    page.click('[data-mode="file"]')
                    page.set_input_files("#fileIn", {"name": "plan.hwp", "mimeType": "application/x-hwp", "buffer": b"HWP Document File"})
                    page.wait_for_selector("#inErr")
                    assert page.locator("#inErr").inner_text() == upload.HWP_MESSAGE
                    page.screenshot(path=str(out / f"hwp-rejection-{width}.png"), full_page=True)
                    assert errors == []
                    measurements.append({"width": width, "upload_status": 200, "analysis_text_identical": True,
                                         "hwp_rejected": True, "overflow_px": overflow, "page_errors": len(errors)})
                    page.close()
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive()
    (out / "measurements.json").write_text(json.dumps(measurements, indent=2), encoding="utf-8")
