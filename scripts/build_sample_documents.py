"""Build upload examples locally, preserving the selected plan text.

No analysis or LLM imports. Requires python-docx and Playwright Chromium.
Run with the task's Python interpreter; outputs remain in this worktree.
"""

from __future__ import annotations

import html
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "src/neumann/api/templates"
OUTPUT = TEMPLATES / "samples/docs"
FONT_DIR = ROOT / "src/neumann/webui/fonts/Pretendard"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"


def docx_file(text: str, path: Path) -> None:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin = section.bottom_margin = Mm(18)
    section.left_margin = section.right_margin = Mm(20)
    for name, size in (("Normal", 10.5), ("Title", 15), ("Heading 2", 12)):
        style = doc.styles[name]
        style.font.name = "Pretendard"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "Pretendard")
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.line_spacing = 1.35
    # Keep punctuation and Markdown markers too: the upload must recover the input.
    for line in text.splitlines():
        p = doc.add_paragraph(line, "Title" if line.startswith("# ") else
                              "Heading 2" if line.startswith("## ") else "Normal")
        if not line:
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 0.3
        if line.startswith("#"):
            p.paragraph_format.keep_with_next = True
        # Word defaults sometimes attach decorative borders to Title styles.
        properties = p._p.get_or_add_pPr()
        for border in list(properties.findall(qn("w:pBdr"))):
            properties.remove(border)
    doc.core_properties.author = ""
    doc.core_properties.last_modified_by = ""
    doc.core_properties.title = text.splitlines()[0].removeprefix("# ")
    doc.core_properties.comments = ""
    doc.save(path)


def hwpx_file(text: str, path: Path) -> None:
    """OWPML text package, including an OPF spine and uncompressed mimetype."""
    declaration = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    page = ('<hp:secPr id="0" textDirection="HORIZONTAL" spaceColumns="1134" '
            'tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT">'
            '<hp:pagePr landscape="WIDELY" width="59528" height="84188" gutterType="LEFT_ONLY">'
            '<hp:margin header="0" footer="0" gutter="0" left="5669" right="5669" top="5102" bottom="5102"/>'
            '</hp:pagePr></hp:secPr>')
    paragraphs = []
    for i, line in enumerate(text.splitlines()):
        paragraphs.append(f'<hp:p id="{i}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
                          f'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
                          f'{page if i == 0 else ""}<hp:t>{escape(line)}</hp:t></hp:run></hp:p>')
    section = declaration + f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">' + ''.join(paragraphs) + '</hs:sec>'
    fonts = ''.join(f'<hh:fontface lang="{lang}" fontCnt="1"><hh:font id="0" face="Pretendard" '
                    'type="TTF" isEmbedded="0"/></hh:fontface>'
                    for lang in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER"))
    header = declaration + f'''<hh:head xmlns:hh="{HH}" version="1.4" secCnt="1">
<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>
<hh:refList><hh:fontfaces itemCnt="7">{fonts}</hh:fontfaces>
<hh:charProperties itemCnt="1"><hh:charPr id="0" height="1050" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0">
<hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
<hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
<hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
<hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
<hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
</hh:charPr></hh:charProperties>
<hh:paraProperties itemCnt="1"><hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1">
<hh:align horizontal="LEFT" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/>
<hh:margin><hh:intent value="0" unit="HWPUNIT"/><hh:left value="0" unit="HWPUNIT"/><hh:right value="0" unit="HWPUNIT"/><hh:prev value="0" unit="HWPUNIT"/><hh:next value="400" unit="HWPUNIT"/></hh:margin>
<hh:lineSpacing type="PERCENT" value="135" unit="HWPUNIT"/></hh:paraPr></hh:paraProperties>
<hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="Normal" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles>
</hh:refList></hh:head>'''
    package = declaration + '''<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version="1.0" unique-identifier="" id="">
<opf:metadata><opf:title>연구계획서</opf:title><opf:language>ko</opf:language></opf:metadata>
<opf:manifest><opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>
<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/></opf:manifest>
<opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/></opf:spine></opf:package>'''
    container = declaration + '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/></rootfiles></container>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("version.xml", declaration + '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" major="5" minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.4" application="Neumann" appVersion="1.0"/>')
        z.writestr("Contents/header.xml", header)
        z.writestr("Contents/section0.xml", section)
        z.writestr("Contents/content.hpf", package)
        z.writestr("META-INF/container.xml", container)
        z.writestr("META-INF/manifest.xml", declaration + '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/hwp+zip"/></manifest:manifest>')
        z.writestr("Preview/PrvText.txt", text)


def print_html(text: str) -> str:
    paragraphs = []
    for line in text.splitlines():
        css = "title" if line.startswith("# ") else "heading" if line.startswith("## ") else "body"
        paragraphs.append(f'<p class="{css}">{html.escape(line) if line else "&nbsp;"}</p>')
    return '''<!doctype html><html lang="ko"><meta charset="utf-8"><title>연구계획서</title>
<style>@font-face{font-family:Pretendard;src:url(/font/regular) format('woff2');font-weight:400}
@font-face{font-family:Pretendard;src:url(/font/bold) format('woff2');font-weight:700}
@page{size:A4;margin:18mm 20mm}body{font-family:Pretendard;margin:0;color:#000;font-size:10.5pt;line-height:1.35}
p{margin:0 0 4pt;white-space:pre-wrap;overflow-wrap:anywhere}.title{font-size:15pt;font-weight:700;break-after:avoid}
.heading{font-size:12pt;font-weight:700;break-after:avoid}</style><body>''' + ''.join(paragraphs) + '</body></html>'


def build() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    registry = json.loads((TEMPLATES / "samples.json").read_text(encoding="utf-8"))
    selected = [s for s in registry["samples"] if s["kind"] == "plan" and s["status"] == "featured"]
    pages = {}
    for item in selected:
        text = (ROOT / item["path"]).read_text(encoding="utf-8")
        docx_file(text, OUTPUT / item["documents"]["docx"])
        hwpx_file(text, OUTPUT / item["documents"]["hwpx"])
        pages['/' + item['id']] = print_html(text).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in pages:
                content, mime = pages[self.path], "text/html; charset=utf-8"
            elif self.path in ("/font/regular", "/font/bold"):
                weight = "Regular" if self.path.endswith("regular") else "Bold"
                content, mime = (FONT_DIR / f"Pretendard-{weight}.woff2").read_bytes(), "font/woff2"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_):
            pass

    server = None
    for port in range(8150, 8170):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("No available document build port in 8150..8169")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(
                    f"http://127.0.0.1:{server.server_port}/") else route.abort())
                for item in selected:
                    page.goto(f"http://127.0.0.1:{server.server_port}/{item['id']}")
                    page.evaluate("document.fonts.ready")
                    page.pdf(path=str(OUTPUT / item["documents"]["pdf"]), prefer_css_page_size=True)
                    print(item['id'], 'PDF DOCX HWPX created')
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


if __name__ == "__main__":
    build()
