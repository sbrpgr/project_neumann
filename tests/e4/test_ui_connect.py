"""Real local HTTP/browser connection, production app + mock provider + explicit fixture backend.

No browser route interception, fabricated results, or signing-module replacements.
Run only through out/codex/run_target_tests.py with NEUMANN_UI_TESTS=1.
"""
from __future__ import annotations

import io
import json
import os
import re
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="Explicit local browser test only")


def _server(tmp_path: Path):
    from tests.e3.corpus import build_backend

    backend = build_backend()
    corpus = tmp_path / "fixture-corpus.json"
    corpus.write_text(json.dumps({"works": [w.model_dump(mode="json", by_alias=True) for w in backend.works.values()],
                                 "reviews": [r.model_dump(mode="json", by_alias=True) for rs in backend.reviews.values() for r in rs]}), encoding="utf-8")
    for port in range(8140, 8170):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                break
            except OSError:
                continue
    else:
        raise AssertionError("No free 81xx test port")
    env = dict(os.environ)
    for key in ("OPENAI_API_KEY", "NEUMANN_PSEUDONYM_SALT", "NEUMANN_LIVE_LLM_OK", "NEUMANN_RESULT_HMAC_KEY"):
        env.pop(key, None)
    env.update(NEUMANN_LLM_PROVIDER="mock", NEUMANN_LIVE_TESTS="0", NEUMANN_EVIDENCE_BACKEND="fixture",
               NEUMANN_FIXTURE_CORPUS=str(corpus), NEUMANN_DATA_DIR=str(tmp_path / "data"),
               NEUMANN_RESULT_CACHE="0", NEUMANN_EXTRACT_CACHE="0", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]), PYTHONUTF8="1", OPENBLAS_NUM_THREADS="1")
    # A subprocess must disable dotenv independently of pytest's parent settings.
    server_code = """import sys
import neumann.config as config
config.Settings.model_config['env_file'] = None
import neumann.index.settings as index_config
index_config.IndexSettings.model_config['env_file'] = None
import uvicorn
uvicorn.run('neumann.api.main:app', host='127.0.0.1', port=int(sys.argv[1]), log_level='warning', access_log=False)
"""
    proc = subprocess.Popen([sys.executable, "-c", server_code, str(port)], cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            assert proc.poll() is None, "Own test server exited"
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    return proc, base
            except httpx.HTTPError:
                pass
            time.sleep(.2)
        raise AssertionError("Own test server did not become ready")
    except BaseException:
        proc.terminate()
        proc.wait(timeout=10)
        raise


def test_real_mock_http_and_browser(tmp_path):
    from docx import Document
    from playwright.sync_api import sync_playwright
    from tests.e4.ui_shots import stop_server

    out = Path(os.getenv("NEUMANN_UI_CONNECT_OUT") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    proc, base = _server(tmp_path)
    trace, page_errors, console_errors, failed_requests, external = [], [], [], [], []
    metrics = {}
    try:
        with httpx.Client(base_url=base, timeout=30) as client:
            catalog = client.get("/templates/samples")
            assert catalog.status_code == 200
            items = catalog.json()["samples"]
            assert len(items) == 5 and all(s["public_ok"] for s in items)
            assert all(not s["precomputed"]["available"] for s in items), "Mock/fixture results must never get stored-result badges"
            assert not any("curation" in s or "intended_weaknesses" in s or "path" in s for s in items)
            registry = json.loads((ROOT / "src/neumann/api/templates/samples.json").read_text(encoding="utf-8"))
            private = next(s for s in registry["samples"] if not s["public_ok"])
            assert client.get("/templates/samples/" + private["id"]).status_code == 404
            assert client.get("/templates/samples/example-battery/view").status_code == 404
            assert client.get("/templates").status_code == 200
            metrics["catalog"] = {"status": 200, "public_count": len(items), "private_status": 404, "fixture_badges": 0}

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True, locale="ko-KR")
            page = context.new_page()
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page.on("requestfailed", lambda request: failed_requests.append(request.failure))
            page.on("request", lambda req: external.append(req.url) if urlparse(req.url).hostname not in {None, "127.0.0.1", "localhost"} else None)
            def response_seen(response):
                path = urlparse(response.url).path
                if path.startswith("/premortem"):
                    trace.append({"method": response.request.method, "path": re.sub(r"/jobs/[^/]+", "/jobs/<id>", path), "status": response.status})
            page.on("response", response_seen)
            page.goto(base, wait_until="networkidle")
            page.wait_for_selector(".sampleCard", state="attached")
            page.locator("#sampleGallery").evaluate("node => node.open = true")
            assert page.locator(".sampleCard").count() == 5
            assert page.locator("[data-sample-view]").count() == 0
            page.select_option("#sampleField", "battery")
            assert page.locator(".sampleCard").count() == 1
            page.select_option("#sampleField", "")
            page.click("[data-sample='example-battery']")
            page.wait_for_function("document.getElementById('ta').value.length > 300")
            page.click("#btnStart")
            page.wait_for_function("document.body.dataset.view === 'report' && document.body.dataset.ready === '1'", timeout=90_000)
            view = page.evaluate("window.NeumannUI.D()")
            assert view.get("result") and view.get("result_sig"), "Actual production API must issue the result signature"
            assert view["_status"]["source"] == "pipeline" and view["_status"]["export"]["signed"]
            assert view["cards"], "Actual mock analysis returned no actionable cards"
            assert all(c["gen"] in {"mock", "rule"} for c in view["cards"])
            assert "모의(mock)" in page.inner_text("#s-cards"), "HMAC integrity must not hide mock generation"
            assert page.evaluate("window.NeumannRevise.config.dev === false && !window.NeumannRevise.mock")
            metrics["analysis"] = {"cards": len(view["cards"]), "source": view["_status"]["source"], "signed": True,
                                    "generation": sorted({c["gen"] for c in view["cards"]}), "backend": "explicit fixture", "OpenAI_calls": 0}
            page.screenshot(path=str(out / "UI-connect-report.png"), full_page=True)
            with page.expect_response(lambda r: urlparse(r.url).path == "/premortem/revise" and r.request.method == "POST") as response:
                page.locator("#s-cards .rc [data-rv]").first.click()
            revision_response = response.value
            assert revision_response.status == 200
            revision = revision_response.json()
            assert revision["origin"] == "server_signed" and revision.get("revision_sig")
            assert revision["generator"] in {"mock", "rule"}
            page.wait_for_selector("#rv-1 .rvdiff")
            assert "HMAC 무결성 확인됨" in page.inner_text("#rv-1 .rvh")
            edits = page.locator("#rv-1 .rdec[data-d='edit']")
            assert edits.count() > 0, "Real API produced no editable proposal"
            edits.first.click()
            edited_text = "연구자 직접 수정: 데이터 분할 기준과 중복 제거 절차를 착수 전에 문서화한다."
            page.locator("#rv-1 textarea.rvedit").first.fill(edited_text)
            page.locator("#rvTitle").click()
            page.wait_for_timeout(300)
            with page.expect_response(lambda r: urlparse(r.url).path == "/premortem/revise/assemble" and r.request.method == "POST") as assembled_response:
                page.click("#rvOpen")
            assembled = assembled_response.value
            assert assembled.status == 200
            plan = assembled.json()
            assert plan["origin"] == "server_signed" and plan.get("revised_plan_sig")
            assert edited_text in plan["revised_text"]
            assert any(c["revised_by"] == "researcher" for c in plan["changes"])
            page.wait_for_function("window.NeumannRevise.state().asm && window.NeumannRevise.state().asm.source === 'server'")
            assert edited_text in page.inner_text("#rvPaper")
            with page.expect_download() as downloaded:
                page.click("#rvVBar [data-rvdl]")
            markdown = Path(downloaded.value.path()).read_text(encoding="utf-8")
            assert edited_text in markdown and "HMAC 무결성 확인됨" in markdown
            with page.expect_response(lambda r: urlparse(r.url).path == "/premortem/revise/assemble" and r.request.method == "POST") as docx_response:
                with page.expect_download() as downloaded_docx:
                    page.click("#rvDocx")
            assert docx_response.value.status == 200
            data = Path(downloaded_docx.value.path()).read_bytes()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                assert "word/document.xml" in archive.namelist()
            document = Document(io.BytesIO(data))
            assert edited_text in "\n".join(p.text for p in document.paragraphs)
            metrics["revision"] = {"status": revision_response.status, "origin": revision["origin"], "generation": revision["generator"],
                                    "signed": True, "edits": len(revision["revisions"][0]["edits"])}
            metrics["assemble"] = {"status": 200, "origin": plan["origin"], "signed": True, "researcher_edit": True,
                                    "markdown_edit": True, "docx_edit": True, "docx_bytes": len(data)}
            page.emulate_media(media="print")
            assert page.locator("#rvPaper").bounding_box()["height"] > 0
            assert "생성: 모의(mock)" in page.inner_text("#rvPaper")
            page.screenshot(path=str(out / "UI-connect-print.png"), full_page=True)
            page.emulate_media(media="screen")
            for width in (390, 616, 768, 1440):
                page.set_viewport_size({"width": width, "height": 844})
                page.wait_for_timeout(80)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.keyboard.press("Escape")
            page.click("#rvBack")
            page.click("#stpExport")
            with page.expect_response(lambda r: urlparse(r.url).path == "/premortem/package" and r.request.method == "POST") as package_response:
                with page.expect_download() as package_download:
                    page.click("#btnExport")
            package = package_response.value
            assert package.status == 200
            assert package.headers.get("x-neumann-result-origin") == "server_signed"
            with zipfile.ZipFile(package_download.value.path()) as archive:
                assert "revision.json" in archive.namelist() and "revised_plan.md" in archive.namelist()
                assert edited_text in archive.read("revised_plan.md").decode("utf-8")
                assert json.loads(archive.read("manifest.json"))["result_origin"] == "server_signed"
                metrics["package"] = {"status": 200, "origin": "server_signed", "files": len(archive.namelist()), "researcher_edit": True}
            context.close()
            browser.close()
        with httpx.Client(base_url=base, timeout=30) as client:
            bad = client.post("/premortem/revise", json={"result": view["result"], "result_sig": "v1." + "0" * 64,
                              "plan_text": "\n".join(l["text"] for l in view["result"]["plan"]["lines"]), "card_ids": [view["cards"][0]["id"]]})
            assert bad.status_code == 200 and bad.json()["origin"] == "client_submitted_unverified" and bad.json().get("revision_sig") is None
            metrics["tampered_signature"] = {"status": 200, "origin": "client_submitted_unverified", "signed": False}
        assert not page_errors and not console_errors and not failed_requests and not external
        metrics.update(trace=trace, page_errors=page_errors, console_errors=console_errors, failed_requests=failed_requests,
                       external_requests=len(external), route_interceptions=0)
        (out / "UI-connect.metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(metrics, ensure_ascii=False))
    finally:
        stop_server(proc, int(urlparse(base).port))
