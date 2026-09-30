"""실제 화면의 다운로드 함수: Playwright headless + 81xx 로컬 mock 서버만 사용."""

from __future__ import annotations

import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from neumann.api.export_title import content_disposition


@pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="Playwright headless 검증은 명시 실행")
def test_browser_preserves_title_in_download_names(tmp_path):
    from playwright.sync_api import sync_playwright

    source = Path("src/neumann/webui/index.html").read_text(encoding="utf-8")
    names = ("expFileName", "fileNameOf", "revisedName", "downloadMd")
    functions = []
    for name in names:
        match = re.search(r"^  function " + name + r"\([^\n]+$", source, re.MULTILINE)
        assert match, name
        functions.append(match.group(0))
    script = "\n".join(functions)
    # The ZIP action spans multiple lines; include the actual product function.
    start = source.index("  function doExport() {")
    end = source.index("\n  document.addEventListener", start)
    script += "\n" + source[start:end]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<!doctype html><title>EXPORT-TITLE mock</title>")

        def log_message(self, *args):
            pass

    server = None
    for port in range(8100, 8200):
        if port == 8171:
            continue
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    assert server is not None, "사용 가능한 81xx 포트가 없다"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(accept_downloads=True)
                page.goto(f"http://127.0.0.1:{server.server_port}")
                page.add_script_tag(content=script)
                title = "이온전도도 연구 A/B\\C? 2026"
                for fmt in ("zip", "docx"):
                    prefix = "neumann_package" if fmt == "zip" else "neumann_revised_plan"
                    header = content_disposition(prefix, "abc123", title, fmt)
                    js = "h => expFileName(h)" if fmt == "zip" else "h => fileNameOf(h, 'fallback.docx')"
                    actual = page.evaluate(js, header)
                    assert "이온전도도_연구_ABC_2026" in actual
                    assert actual.endswith("." + fmt)
                assert page.evaluate("() => expFileName(\"filename*=UTF-8''bad%ZZ.zip\")") == "neumann_package.zip"
                assert page.evaluate("() => fileNameOf(\"filename*=UTF-8''../bad.docx\", 'safe.docx')") == "safe.docx"
                page.evaluate("""() => {
                    window.D = {plan: {title: '독립 ZIP 제목'}, result_sig: null};
                    window.EXP = {d: D}; window.NeumannRevise = null;
                    window.expState = () => ({}); window.expBlock = () => '';
                    window.expPaint = () => {}; window.expMsg = () => {};
                    window.expInline = () => ({}); window.expDecisions = () => [];
                    window.expSave = () => {}; window.upSize = () => 'mock';
                    window.fetch = (url, opts) => {
                        window.exportBody = JSON.parse(opts.body);
                        return Promise.resolve(new Response(new Blob(['mock ZIP']),
                            {headers: {'Content-Disposition': 'filename=mock.zip'}}));
                    };
                    doExport();
                }""")
                assert page.evaluate("() => exportBody.title") == "독립 ZIP 제목"
                page.evaluate("""() => {
                    window.state = () => ({});
                    window.currentAsm = () => ({source: 'server', rid: 'abc123',
                        raw: {title: '이온전도도 연구 A/B\\\\C? 2026'}, counts: {adopted: 1}});
                    window.mdText = () => '# 이온전도도 연구 A/B\\\\C? 2026\\n본문';
                    window.U = {toast: () => {}};
                    window.saveBlob = (blob, name) => {
                        const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
                        a.download = name; document.body.append(a); a.click(); a.remove();
                    };
                }""")
                with page.expect_download() as downloaded:
                    page.evaluate("() => downloadMd()")
                download = downloaded.value
                assert download.suggested_filename == "neumann_revised_plan_이온전도도_연구_ABC_2026_abc123.md"
                target = tmp_path / "download.md"
                download.save_as(target)
                assert "이온전도도 연구" in target.read_text(encoding="utf-8")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
