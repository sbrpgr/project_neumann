"""Headless checks against this worktree's local mock server only."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="headless UI checks are opt-in")
SERVER = """
import sys
from neumann.config import Settings
Settings.model_config['env_file'] = None
from neumann.index.settings import IndexSettings
IndexSettings.model_config['env_file'] = None
import uvicorn
from neumann.api.main import app
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='critical', lifespan='off')
"""


@pytest.fixture(scope="module")
def local_server():
    port = None
    for candidate in range(8150, 8170):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            port = candidate
            break
    if port is None:
        pytest.fail("No free mock port in 8150..8169")
    env = dict(os.environ, NEUMANN_LLM_PROVIDER="mock", PYTHONPATH="src;.", PYTHONIOENCODING="utf-8")
    for name in ("OPENAI_API_KEY", "NEUMANN_PSEUDONYM_SALT", "NEUMANN_LIVE_LLM_OK", "NEUMANN_LIVE_TESTS"):
        env.pop(name, None)
    process = subprocess.Popen([sys.executable, "-c", SERVER, str(port)], cwd=ROOT, env=env)
    origin = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("mock server exited before startup")
            try:
                if httpx.get(origin + "/templates/samples", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            pytest.fail("mock server did not start")
        yield origin
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@pytest.mark.parametrize("width", [1440, 390])
def test_first_screen_selection_and_document_links(local_server, width):
    from playwright.sync_api import sync_playwright

    output = ROOT / "out/sample-build/ui"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": 960})
            external, errors, console_errors, failed_requests, requests = [], [], [], [], []
            def route_request(route):
                url = route.request.url
                requests.append(url)
                if url.startswith(local_server + "/"):
                    route.continue_()
                else:
                    external.append(url)
                    route.abort()
            page.route("**/*", route_request)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("requestfailed", lambda request: failed_requests.append(request.url))
            page.goto(local_server + "/", wait_until="networkidle")
            page.wait_for_selector('.sampleCard[data-sample-id="example-battery"]')
            assert page.locator("#sampleGallery").evaluate("e => e.open") is True
            assert page.locator(".sampleCard").count() == 3
            assert page.locator("#sampleField option").count() == 4
            cards = page.locator("#sampleGallery").inner_text()
            assert not any(word in cards for word in ("약점", "누출", "오차 막대", "사용 가능한 저장 결과 없음", "fixture"))
            assert page.locator('.sampleCard a[download]').count() == 9
            assert page.locator("#sendNote").evaluate("e => getComputedStyle(e).position") == "static"
            assert page.evaluate("document.getElementById('sendNote').getBoundingClientRect().top >= document.getElementById('btnStart').getBoundingClientRect().bottom")
            overflow = page.evaluate("Math.max(0, document.documentElement.scrollWidth - innerWidth)")
            assert overflow == 0
            page.screenshot(path=str(output / f"samples-{width}.png"), full_page=True)
            for sample_id in ("example-battery", "example-binding", "example-operator"):
                expected = httpx.get(local_server + "/templates/samples/" + sample_id).json()["text"]
                page.locator('[data-sample="' + sample_id + '"]').click()
                # Samples select paste mode and preserve the server input verbatim.
                page.wait_for_function("expected => document.getElementById('ta')?.value === expected", arg=expected)
                assert page.locator("#ta").input_value() == expected
                assert page.locator("#btnStart").is_enabled()
            page.locator("#sampleField").select_option("binding")
            assert page.locator(".sampleCard").count() == 1
            assert not external and not errors and not console_errors and not failed_requests
            assert not any("premortem" in request for request in requests)
            (output / f"checks-{width}.json").write_text(json.dumps({
                "width": width, "cards": 3, "downloads": 9, "overflow": overflow,
                "page_errors": errors, "external_requests": external, "analysis_requests": 0,
                "console_errors": console_errors, "failed_requests": failed_requests,
            }, indent=2), encoding="utf-8")
        finally:
            browser.close()
