"""Scoped offline build and headless browser checks; no product LLM or settings."""
from __future__ import annotations

import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import re
import socket
import threading
import zipfile
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("static_final_builder", ROOT / "scripts/build_static_final.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("static-final") / "neumann"
    samples = builder.build(out)
    return out, samples


@pytest.fixture(scope="module")
def server(site):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(QuietHandler, directory=str(site[0].parent))
    http = None
    for port in range(8100, 8200):
        if port == 8171:
            continue
        try:
            http = ThreadingHTTPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            continue
    assert http is not None, "No free permitted 81xx test port"
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{http.server_port}/neumann/"
    port = http.server_port
    http.shutdown()
    http.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive()
    probe = socket.socket()
    try:
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    finally:
        probe.close()


def test_build_records_real_failures_and_corrections(site):
    out, samples = site
    assert len(samples) == 3
    assert (out / ".nojekyll").is_file()
    assert (out / "FONT-LICENSE.txt").is_file()
    for sample in samples:
        assert len(sample["original"]) >= 600
        assert [r["passed"] for r in sample["before_checks"]] == [False] * 3
        assert [r["passed"] for r in sample["after_checks"]] == [True] * 3
        assert [r["tool"] for r in sample["after_checks"]] == ["Z3", "Pint", "NetworkX"]
        for edit in sample["edits"]:
            assert edit["before"] == "\n".join(sample["original"].splitlines()[n - 1] for n in edit["lines"])
            assert edit["origin"] == "Claude/Codex 오프라인"
    assert all(e["reference"] == "분야 수준 참고" for e in samples[2]["edits"])
    raw = (out / "index.html").read_text(encoding="utf-8")
    assert "@@" not in raw
    assert "connect-src 'none'" in raw
    assert "사전 계산 결과 · 실시간 분석 아님" in raw
    assert not re.search(r"\b(fetch|XMLHttpRequest|WebSocket|sendBeacon)\s*\(", raw)
    assert not re.search(r"https?://(?!schemas\.openxmlformats\.org)", raw)
    assert not re.search(r"sk-[A-Za-z0-9_-]{16,}|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|010[- ]\d{4}[- ]\d{4}", raw)


def test_corrupt_quote_is_rejected(monkeypatch):
    original = builder.rows

    def altered(name):
        values = original(name)
        if name == "excerpts.jsonl":
            values[0]["text"] = "changed"
        return values

    monkeypatch.setattr(builder, "rows", altered)
    with pytest.raises(ValueError, match="mismatch"):
        builder.load_evidence()


def test_build_has_no_socket_access_and_escapes_data(tmp_path, monkeypatch, site):
    def reject(*args, **kwargs):
        raise AssertionError("Build attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)
    out = tmp_path / "offline"
    builder.build(out)
    samples = json.loads(json.dumps(site[1]))
    samples[0]["intro"] = '</script><img src="https://invalid.example" onerror="alert(1)">'
    monkeypatch.setattr(builder, "make_samples", lambda: samples)
    builder.build(out)
    raw = (out / "index.html").read_text(encoding="utf-8")
    assert '</script><img src="https://invalid.example"' not in raw
    assert "\\u003c/script>" in raw


def test_mutated_execution_conditions_fail(site):
    conditions = list(site[1][0]["conditions"])
    for correction in site[1][0]["corrections"]:
        conditions[conditions.index(correction["before"])] = correction["after"]
    conditions[0] = "학습 배분 9601건"
    assert builder.measure(conditions)[0]["passed"] is False
    conditions[5] = "변환 전도도 0.2 S/m 와 같다"
    assert builder.measure(conditions)[1]["passed"] is False
    conditions[-1] = "학습 완료 후 전처리 시작"
    assert builder.measure(conditions)[2]["passed"] is False


def test_design_tokens_and_wait_contract():
    css = (builder.ASSETS / "style.css").read_text(encoding="utf-8")
    css += (builder.ASSETS / "wait.css").read_text(encoding="utf-8")
    outside_root = re.sub(r":root\{[^}]+\}", "", css)
    assert len(re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", outside_root)) == 0
    assert not re.search(r"font-size:\s*(?!var\()[0-9]", css)
    assert set(re.findall(r"font-family:([^;}]+)", css)) == {"Pretendard"}
    js = (builder.ASSETS / "wait.js").read_text(encoding="utf-8")
    assert "{create, update, done, fail}" in js
    assert "Math.max(progress" in js


def assert_layout(page):
    state = page.evaluate("""() => {
      const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
      const elements = [...document.querySelectorAll('main *,header *,nav *,footer')].filter(visible);
      return {overflow: document.documentElement.scrollWidth - innerWidth,
              sections: [...document.querySelectorAll('section[data-step]')].filter(visible).length,
              primary: [...document.querySelectorAll('button.primary')].filter(visible).length,
              sizes: [...new Set(elements.map(el=>getComputedStyle(el).fontSize))],
              fonts: [...new Set(elements.map(el=>getComputedStyle(el).fontFamily))],
              bodyDialogs: [...document.querySelectorAll('dialog')].every(el=>el.parentElement===document.body)};
    }""")
    assert state["overflow"] == 0, state
    assert state["sections"] == 1, state
    assert state["primary"] == 1, state
    assert set(state["sizes"]) <= {"14px", "16px", "20px", "28px"}, state
    assert state["fonts"] == ["Pretendard"], state
    assert state["bodyDialogs"]
    return state


def advance(page):
    page.locator("#start").click()
    page.locator("#show-cards").wait_for(state="visible")
    page.wait_for_function("() => !document.getElementById('show-cards').disabled")
    page.locator("#show-cards").click()


def screenshot(page, path):
    page.evaluate("() => window.scrollTo(0, 0)")
    page.screenshot(path=str(path), full_page=True, animations="disabled")


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_three_complete_flows_headless(server, site, width, height):
    from playwright.sync_api import sync_playwright

    shots = ROOT / "data/site_final/qa"
    shots.mkdir(parents=True, exist_ok=True)
    observations, requests, errors = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": width, "height": height}, locale="ko-KR", accept_downloads=True)
        page = context.new_page()
        page.on("request", lambda request: requests.append(request.url))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.goto(server, wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        context.set_offline(True)
        for index, sample in enumerate(site[1]):
            if index:
                page.locator("#reset").click()
            page.locator(f'[data-sample="{index}"]').click()
            assert page.locator("#plan-input").input_value() == sample["original"]
            observations.append(assert_layout(page))
            if index == 0:
                screenshot(page, shots / f"{width}-0-input.png")
            page.locator("#start").click()
            observations.append(assert_layout(page))
            if index == 0:
                screenshot(page, shots / f"{width}-1-analysis.png")
            page.wait_for_function("() => !document.getElementById('show-cards').disabled")
            page.locator("#show-cards").click()
            assert page.locator('#cards input:checked').count() == 2
            page.locator("#cards details").first.locator("summary").click()
            assert sample["edits"][0]["evidence"]["quote"] in page.locator("#cards").inner_text()
            observations.append(assert_layout(page))
            if index == 0:
                screenshot(page, shots / f"{width}-2-adoption.png")
            page.locator("#make-plan").click()
            assert page.locator("#revision .changed").count() == 2
            observations.append(assert_layout(page))
            if index == 0:
                screenshot(page, shots / f"{width}-3-revision.png")
            page.locator("#revision .change-number").first.click()
            assert page.locator("#change-dialog").is_visible()
            assert page.locator("#change-before").inner_text() == sample["edits"][0]["before"]
            page.locator("#close-dialog").click()
            page.locator("#finalize").click()
            page.wait_for_function("() => !document.getElementById('finish').disabled")
            assert page.locator("#checks .status.passed").count() == 3
            observations.append(assert_layout(page))
            if index == 0:
                screenshot(page, shots / f"{width}-4-checks.png")
            page.locator("#finish").click()
            assert page.locator("#final-document .changed").count() == 5
            observations.append(assert_layout(page))
            if index == 0:
                screenshot(page, shots / f"{width}-5-complete.png")
            for correction in sample["corrections"]:
                assert correction["after"] in page.locator("#final-document").inner_text()
                assert correction["before"] not in page.locator("#final-document").inner_text()
            with page.expect_download() as download:
                page.locator("#download-md").click()
            downloaded_md = Path(download.value.path()).read_text(encoding="utf-8")
            assert sample["title"] in downloaded_md
            assert "사전 계산 결과 · 실시간 분석 아님" in downloaded_md
            with page.expect_download() as download:
                page.locator("#download-docx").click()
            with zipfile.ZipFile(download.value.path()) as package:
                assert package.testzip() is None
                xml = ET.fromstring(package.read("word/document.xml"))
                texts = "\n".join(xml.itertext())
                for correction in sample["corrections"]:
                    assert correction["after"] in texts
            # Revisit a past stage and verify automatic correction undo is honest.
            page.locator("#steps button").nth(4).click()
            page.locator("#checks .text-button").first.click()
            assert page.locator("#checks .status.failed").count() == 1
            page.locator("#finish").click()
            assert sample["corrections"][0]["before"] in page.locator("#final-document").inner_text()
            assert "확인 필요 1건" in page.locator("#final-summary").inner_text()
            page.locator("#steps button").nth(4).click()
            page.locator("#checks .text-button").first.click()
            page.locator("#finish").click()
            assert "확인 필요 0건" in page.locator("#final-summary").inner_text()
        assert requests == [server], requests
        assert errors == [], errors
        (shots / f"{width}-measurements.json").write_text(json.dumps({"layouts": observations, "external_requests": 0, "requests": len(requests), "errors": errors, "samples_completed": 3}, indent=2), encoding="utf-8")
        browser.close()


def test_editing_and_input_guardrails(server, site):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(server, wait_until="networkidle")
        page.locator("#plan-input").fill("짧은 계획서")
        assert page.locator("#start").is_disabled()
        assert "300자 이상" in page.locator("#input-message").inner_text()
        page.locator("#plan-input").fill("레시피 계획")
        assert "범위 밖" in page.locator("#input-message").inner_text()
        page.locator("#plan-input").fill("연구 계획을 설명합니다. " * 35)
        assert page.locator("#start").is_disabled()
        assert "600자 미만" in page.locator("#input-message").inner_text()
        page.locator("#file-input").set_input_files({"name": "sample.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "buffer": b"not-read"})
        assert "새 파일을 읽거나 분석하지 않습니다" in page.locator("#input-message").inner_text()
        page.locator('[data-sample="0"]').click()
        advance(page)
        page.locator("#cards input").first.uncheck()
        assert "채택 1건" in page.locator("#make-plan").inner_text()
        page.locator("#make-plan").click()
        assert page.locator("#revision .changed").count() == 1
        original_split = site[1][0]["edits"][0]["before"].splitlines()[0]
        assert original_split in page.locator("#revision").inner_text()
        condition = page.locator('#revision [contenteditable="true"]').filter(has_text="시험 배분 2400건")
        condition.fill("시험 배분 99999건")
        page.locator("#finalize").click()
        page.wait_for_function("() => !document.getElementById('finish').disabled")
        assert page.locator("#checks .status.unchecked").count() == 1
        page.locator("#finish").click()
        assert "시험 배분 99999건" in page.locator("#final-document").inner_text()
        assert "확인 필요 2건" in page.locator("#final-summary").inner_text()
        # Navigation returns to top and past-stage editing invalidates completion.
        page.locator("#steps button").nth(3).click()
        assert page.evaluate("scrollY") == 0
        paragraph = page.locator('#revision [contenteditable="true"]').first
        paragraph.fill("직접 수정한 연구 목표입니다.")
        assert page.locator("#steps button").nth(5).is_disabled()
        page.locator("#finalize").click()
        page.wait_for_function("() => !document.getElementById('finish').disabled")
        assert page.locator("#checks .status.unchecked").count() == 1
        assert page.locator("#checks .status.passed").count() == 2
        # Untouched recorded conditions remain applicable after editing prose.
        page.locator("#finish").click()
        assert "직접 수정한 연구 목표입니다." in page.locator("#final-document").inner_text()
        page.locator("#reset").click()
        advance(page)
        for checkbox in page.locator("#cards input").all():
            checkbox.uncheck()
        assert "채택 0건" in page.locator("#make-plan").inner_text()
        page.locator("#make-plan").click()
        assert page.locator("#revision .changed").count() == 0
        page.locator("#finalize").click()
        page.wait_for_function("() => !document.getElementById('finish').disabled")
        assert page.locator("#checks .status.passed").count() == 3
        page.locator("#finish").click()
        assert "권고 반영 0건" in page.locator("#final-summary").inner_text()
        page.locator("#steps button").nth(3).click()
        paragraph = page.locator('#revision [contenteditable="true"]').first
        paragraph.fill("편집한 목표입니다. <script>실행하지 않습니다.</script>")
        assert page.locator("#revision script").count() == 0
        page.locator("#finalize").click()
        page.wait_for_function("() => !document.getElementById('finish').disabled")
        assert page.locator("#checks .status.passed").count() == 3
        assert page.locator("#checks .status.unchecked").count() == 0
        browser.close()


@pytest.mark.parametrize("width,zoom", [(375, 1), (1152, 1.25)])
def test_dialog_reduced_motion_and_stepper(server, width, zoom):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 900}, reduced_motion="reduce")
        page.goto(server, wait_until="networkidle")
        page.evaluate("zoom => document.body.style.zoom = zoom", zoom)
        advance(page)
        page.locator("#make-plan").click()
        assert_layout(page)
        assert page.locator(".stepper").evaluate("el => getComputedStyle(el).height") == "56px"
        page.locator("#revision .change-number").first.click()
        assert page.locator("#change-dialog").is_visible()
        assert page.locator("#close-dialog").is_visible()
        assert page.locator("#change-dialog").evaluate("el => el.parentElement === document.body")
        page.screenshot(path=str(ROOT / f"data/site_final/qa/{width}-dialog-{zoom}.png"), full_page=True, animations="disabled")
        page.keyboard.press("Escape")
        assert not page.locator("#change-dialog").is_visible()
        assert page.locator('section:not([hidden])').evaluate("el => getComputedStyle(el).animationName") == "none"
        browser.close()
