"""Independent browser check of the real mock-provider finalization path."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.e4.test_ui_connect import _server


pytestmark = pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="Explicit local browser test only")


def test_single_action_final_text_and_invalidation(tmp_path):
    from playwright.sync_api import sync_playwright
    from tests.e4.ui_shots import stop_server

    proc, base = _server(tmp_path)
    requests = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(accept_downloads=True, locale="ko-KR")
            page = context.new_page()
            page.on("request", lambda r: requests.append(r) if urlparse(r.url).path == "/premortem/finalize" else None)
            page.goto(base, wait_until="networkidle")
            page.locator("#sampleGallery").evaluate("node => node.open = true")
            page.click("[data-sample='example-battery']")
            page.wait_for_function("document.getElementById('ta').value.length > 300")
            page.click("#btnStart")
            page.wait_for_function("document.body.dataset.view === 'report' && document.body.dataset.ready === '1'", timeout=90_000)
            assert page.evaluate("window.NeumannUI.D()._status.source") == "pipeline"
            with page.expect_response(lambda r: urlparse(r.url).path == "/premortem/revise" and r.request.method == "POST", timeout=90_000) as revision:
                page.locator("#s-cards .rc [data-rv]").first.click()
            assert revision.value.status == 200
            page.wait_for_selector("#rv-1 .rvdiff", timeout=90_000)
            edits = page.locator("#rv-1 .rdec[data-d='edit']")
            assert edits.count() > 0
            edits.first.click()
            original = "연구자 확정 전 직접 수정: 자료 분할과 중복 제거를 사전에 기록한다."
            page.locator("#rv-1 textarea.rvedit").first.fill(original)
            page.locator("#rvTitle").click()
            with page.expect_response(lambda r: urlparse(r.url).path == "/premortem/revise/assemble" and r.request.method == "POST", timeout=90_000) as assembled:
                page.click("#rvOpen")
            assert assembled.value.status == 200
            page.wait_for_function("window.NeumannRevise.state().asm && window.NeumannRevise.state().asm.source === 'server'", timeout=90_000)
            with page.expect_response(lambda r: urlparse(r.url).path == "/premortem/finalize" and r.request.method == "POST", timeout=90_000) as finalized:
                page.click("#rvFinalize")
            assert finalized.value.status == 200, finalized.value.text()[:300]
            body = finalized.value.json()
            assert body["origin"] == "server_signed"
            assert body["finalization_sig"]
            assert body["final_text"] == body["finalization"]["final_text"]
            assert body["finalization"]["status"]
            page.wait_for_selector("#rvFinalization pre")
            assert page.locator("#rvFinalization pre").first.inner_text() == body["final_text"]
            assert len(requests) == 1
            with page.expect_download() as download:
                page.click("#rvVBar [data-rvdl]")
            md = Path(download.value.path()).read_text(encoding="utf-8")
            assert download.value.suggested_filename == "neumann_final_plan.md"
            assert body["final_text"] in md
            assert "변경 목록" in md and "잔여 쟁점" in md
            # A user change makes the prior finalization stale immediately.
            page.locator("#rvPolish").check()
            assert page.evaluate("window.NeumannRevise.state().finalization === null")
            assert page.locator("#rvFinalization").count() == 0
            assert len(requests) == 1
            context.set_offline(True)
            page.click("#rvFinalize")
            page.wait_for_function("window.NeumannRevise.state().finalBusy === false")
            assert page.evaluate("window.NeumannRevise.state().finalization === null")
            assert "수정 확정 실패" in page.inner_text("#rvVBar")
            print({"final_status": body["finalization"]["status"], "final_chars": len(body["final_text"]),
                   "corrections": len(body["finalization"].get("corrections", [])),
                   "issues": len(body["finalization"].get("issues", [])),
                   "single_click_requests": 1, "offline_failure_displayed": True})
            context.close()
            browser.close()
    finally:
        stop_server(proc, int(urlparse(base).port))
