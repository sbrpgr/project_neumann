"""E4-L2h HWPX 업로드 테스트: 추출·순서·표·각주, 격리 작업자, 적대 입력, 무작위 퍼징.

HWPX 견본은 테스트 안에서 zipfile로 만든다(파일 커밋 없음). 구조는 한글이 저장한 실제 HWPX와 같게 둔다:
`mimetype`(무압축, 맨 앞) · `Contents/content.hpf`(OPF manifest + spine) · `Contents/section*.xml`(OWPML 2011)
· `META-INF/manifest.xml` · `Preview/PrvText.txt`(UTF-8).

    python tests/e4/test_upload_hwpx.py --fuzz 2000     # 퍼징 통계만 따로(보고서용)
"""

from __future__ import annotations

import io
import json
import random
import sys
import time
import zipfile
from xml.sax.saxutils import escape

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neumann.api.hwpx as hwpx
import neumann.api.upload as upload
from neumann.api.upload import (
    MAX_ZIP_UNCOMPRESSED,
    UploadRejected,
    extract_plan,
    extract_plan_isolated,
    router,
)

HS = "http://www.hancom.co.kr/hwpml/2011/section"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
EMPTY_MANIFEST = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
    b'<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
)
ONE_SECOND = 1.0


# ── 견본 생성 ───────────────────────────────────────────────────────────────


def t(text: str) -> str:
    """`hp:t` 한 개. 탭은 `hp:tab`, 줄바꿈은 `hp:lineBreak`(한글이 저장하는 모양)."""
    out = []
    for i, line in enumerate(text.split("\n")):
        if i:
            out.append("<hp:lineBreak/>")
        out.append("<hp:tab/>".join(escape(part) for part in line.split("\t")))
    return "<hp:t>" + "".join(out) + "</hp:t>"


def p(text: str = "", *extra_runs: str) -> str:
    """문단 한 개: 글자 run + 덧붙일 run(표·각주 등) + linesegarray(읽지 않는 요소)."""
    return (
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="0">{t(text)}</hp:run>' + "".join(extra_runs)
        + '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0"/></hp:linesegarray></hp:p>'
    )


def cell(content: str | list[str], col: int, row: int) -> str:
    paras = content if isinstance(content, list) else [content]
    body = "".join(x if x.startswith("<hp:p") else p(x) for x in paras)
    return (
        '<hp:tc name="" header="0" borderFillIDRef="1">'
        f'<hp:subList id="" textDirection="HORIZONTAL">{body}</hp:subList>'
        f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        '<hp:cellSz width="100" height="100"/></hp:tc>'
    )


def tbl(rows: list[list[str | list[str]]]) -> str:
    """표 run. 행마다 셀 목록(병합으로 빠진 칸은 목록에서 빼면 된다 — HWPX도 그렇게 저장한다)."""
    trs = "".join("<hp:tr>" + "".join(cell(c, ci, ri) for ci, c in enumerate(r)) + "</hp:tr>" for ri, r in enumerate(rows))
    return (
        f'<hp:run charPrIDRef="0"><hp:tbl id="1" rowCnt="{len(rows)}" colCnt="3">'
        f'<hp:sz width="100" height="100"/><hp:pos treatAsChar="1"/>{trs}</hp:tbl><hp:t/></hp:run>'
    )


def ctrl(kind: str, text: str) -> str:
    """각주(footNote)·미주(endNote)·머리말(header)·꼬리말(footer)·숨은 설명(hiddenComment) run."""
    return f'<hp:run charPrIDRef="0"><hp:ctrl><hp:{kind} id="1"><hp:subList>{p(text)}</hp:subList></hp:{kind}></hp:ctrl></hp:run>'


def textbox(text: str) -> str:
    return (
        '<hp:run charPrIDRef="0"><hp:rect id="1"><hp:shapeComment>사각형입니다.</hp:shapeComment>'
        f'<hp:drawText><hp:subList>{p(text)}</hp:subList></hp:drawText></hp:rect></hp:run>'
    )


def section(*paras: str) -> str:
    first = (
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:secPr id="" textDirection="HORIZONTAL"><hp:pagePr width="59528" height="84188"/></hp:secPr>'
        '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" colCount="1"/></hp:ctrl></hp:run></hp:p>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{first}{"".join(paras)}</hs:sec>'
    )


def content_hpf(n_sections: int, spine: list[int] | None = None) -> bytes:
    order = list(range(n_sections)) if spine is None else spine
    items = '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>' + "".join(
        f'<opf:item id="section{i}" href="Contents/section{i}.xml" media-type="application/xml"/>' for i in range(n_sections)
    )
    refs = '<opf:itemref idref="header" linear="yes"/>' + "".join(f'<opf:itemref idref="section{i}" linear="yes"/>' for i in order)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version="" unique-identifier="" id="">'
        f"<opf:metadata><opf:title/><opf:language>ko</opf:language></opf:metadata>"
        f"<opf:manifest>{items}</opf:manifest><opf:spine>{refs}</opf:spine></opf:package>"
    ).encode("utf-8")


def make_hwpx(
    sections: list[str | bytes],
    *,
    spine: list[int] | None = None,
    hpf: bytes | None = None,
    prvtext: str | None = "미리보기 첫 줄\r\n미리보기 둘째 줄",
    manifest: bytes = EMPTY_MANIFEST,
    extra: dict[str, bytes] | None = None,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    """최소 HWPX. `hpf=b""`면 content.hpf를 넣지 않는다(번호순으로 읽어야 한다)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), b"application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("version.xml", b'<?xml version="1.0" encoding="UTF-8"?><hv:HCFVersion xmlns:hv="x" major="5"/>')
        zf.writestr("Contents/header.xml", b'<?xml version="1.0" encoding="UTF-8"?><hh:head xmlns:hh="x"/>')
        for i, sec in enumerate(sections):
            zf.writestr(f"Contents/section{i}.xml", sec.encode("utf-8") if isinstance(sec, str) else sec)
        if hpf != b"":
            zf.writestr("Contents/content.hpf", hpf if hpf is not None else content_hpf(len(sections), spine))
        zf.writestr("META-INF/container.xml", b'<?xml version="1.0"?><ocf:container xmlns:ocf="x"/>')
        zf.writestr("META-INF/manifest.xml", manifest)
        if prvtext is not None:
            zf.writestr("Preview/PrvText.txt", prvtext.encode("utf-8"))
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


PLAN_LINES = [
    "연구계획서 — 전해액 이온전도도 예측 대리모델",
    "1. 목표: GNN으로 이온전도도(mS/cm)를 예측한다.",
    "2. 데이터: 문헌 12,000건, 자체 실험 300건",
    "3. 평가: 5겹 교차검증, MAE·R² 보고",
]


def plan_hwpx(lines: list[str] = PLAN_LINES) -> bytes:
    return make_hwpx([section(*(p(x) for x in lines))])


def rich_section() -> str:
    """제목·탭·줄바꿈·표(가로 병합·셀 안 두 문단·중첩 표)·각주·글상자·머리말(읽지 않음)·숨은 설명(읽지 않음)."""
    nested = p("", tbl([["안쪽 A", "안쪽 B"]]))
    return section(
        p(PLAN_LINES[0], ctrl("header", "머리말은 읽지 않는다")),
        p("1. 목표:\tGNN으로 예측\n(줄바꿈 뒤)"),
        p("", tbl([["구분", "규모", "출처"], ["데이터", "12,000건", "문헌"], ["300건 자체 실험"], [["셀 첫 문단", "셀 둘째 문단"], nested]])),
        p("2. 방법 본문", ctrl("footNote", "각주: 출처 표기"), ctrl("hiddenComment", "숨은 설명은 읽지 않는다")),
        p("3. 평가", textbox("글상자 안 글")),
        p("A&B <태그 아님> \"따옴표\""),
    )


RICH_EXPECTED = [
    PLAN_LINES[0],
    "1. 목표:\tGNN으로 예측",
    "(줄바꿈 뒤)",
    "구분 | 규모 | 출처",
    "데이터 | 12,000건 | 문헌",
    "300건 자체 실험",
    "셀 첫 문단 셀 둘째 문단 | 안쪽 A | 안쪽 B",
    "2. 방법 본문",
    "각주: 출처 표기",
    "3. 평가",
    "글상자 안 글",
    "A&B <태그 아님> \"따옴표\"",
]


def reject(filename: str, data: bytes) -> UploadRejected:
    with pytest.raises(UploadRejected) as info:
        extract_plan(filename, data)
    return info.value


def timed_reject(filename: str, data: bytes) -> tuple[UploadRejected, float]:
    start = time.perf_counter()
    err = reject(filename, data)
    return err, time.perf_counter() - start


def rezip(data: bytes, change: dict[str, bytes | None], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    """기존 zip의 항목을 바꾸거나(None이면 뺀다) 더한다."""
    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as out:
        for info in src.infolist():
            if info.filename in change:
                continue
            out.writestr(info, src.read(info))
        for name, blob in change.items():
            if blob is not None:
                out.writestr(name, blob)
    return buf.getvalue()


# ── 추출 ────────────────────────────────────────────────────────────────────


def test_hwpx_paragraphs_tables_notes_in_order():
    result = extract_plan("계획서.hwpx", make_hwpx([rich_section()]))
    assert result.kind == "hwpx"
    assert result.pages is None and result.encoding is None
    assert result.text.split("\n") == RICH_EXPECTED
    assert result.warnings == ()
    assert result.paragraphs == len(RICH_EXPECTED)
    assert result.chars_no_space == len("".join(result.text.split()))
    for hidden in ("머리말", "숨은 설명", "사각형입니다"):  # 머리말·숨은 설명·개체 설명은 읽지 않는다
        assert hidden not in result.text


def test_hwpx_plan_round_trip_matches_docx_rules():
    result = extract_plan("plan.hwpx", plan_hwpx())
    assert result.text.split("\n") == PLAN_LINES
    assert result.lines == len(PLAN_LINES) and result.paragraphs == len(PLAN_LINES)


def test_hwpx_section_order_follows_spine_then_number():
    def body(result) -> list[str]:  # 구역 첫 문단(secPr만 든 빈 문단)이 구역 사이에 빈 줄을 하나씩 만든다
        return [line for line in result.text.split("\n") if line]

    secs = [section(p("구역0")), section(p("구역1")), section(p("구역2"))]
    by_spine = extract_plan("a.hwpx", make_hwpx(secs, spine=[2, 0, 1]))
    assert body(by_spine) == ["구역2", "구역0", "구역1"]
    assert by_spine.text == "구역2\n\n구역0\n\n구역1"
    # content.hpf가 없으면 파일 이름 번호순(문자열 순이 아니라 2 < 10)
    many = [section(p(f"구역{i}")) for i in range(11)]
    assert body(extract_plan("b.hwpx", make_hwpx(many, hpf=b""))) == [f"구역{i}" for i in range(11)]
    # spine이 가리키는 곳이 없거나 이상한 경로면 무시하고 번호순
    odd = content_hpf(0).replace(b"</opf:manifest>", b'<opf:item id="s" href="../../etc/passwd"/></opf:manifest>')
    odd = odd.replace(b"</opf:spine>", b'<opf:itemref idref="s"/></opf:spine>')
    assert body(extract_plan("c.hwpx", make_hwpx(secs[:2], hpf=odd))) == ["구역0", "구역1"]


def test_hwpx_prvtext_fallback_and_partial_warning():
    broken = b"<hs:sec><hp:p>"  # 닫히지 않은 XML
    only_bad = extract_plan("a.hwpx", make_hwpx([broken]))
    assert only_bad.text == "미리보기 첫 줄\n미리보기 둘째 줄"
    assert only_bad.warnings == (hwpx.PRVTEXT_WARNING,)
    partial = extract_plan("b.hwpx", make_hwpx([section(p("살아남은 본문")), broken]))
    assert partial.text == "살아남은 본문"
    assert any("구역(section) 1개" in w for w in partial.warnings)
    err = reject("c.hwpx", make_hwpx([broken], prvtext=None))
    assert err.status_code == 422 and err.message == hwpx.HWPX_CORRUPT_MESSAGE


def test_hwpx_encrypted_rejected():
    manifest = (
        b'<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
        b'<odf:file-entry odf:full-path="Contents/section0.xml"><odf:encryption-data/></odf:file-entry></odf:manifest>'
    )
    err = reject("locked.hwpx", make_hwpx([section(p("본문"))], manifest=manifest))
    assert (err.status_code, err.message) == (422, hwpx.HWPX_ENCRYPTED_MESSAGE)
    assert "암호가 걸린 문서는 처리할 수 없습니다" in err.message
    # zip 항목 암호 플래그(zipfile은 쓸 때 플래그를 지우므로 중앙 디렉터리 바이트를 직접 고친다)
    zipped = with_encrypted_flag(plan_hwpx(), "Contents/section0.xml")
    assert zipfile.ZipFile(io.BytesIO(zipped)).getinfo("Contents/section0.xml").flag_bits & 0x1
    assert reject("zipcrypt.hwpx", zipped).message == hwpx.HWPX_ENCRYPTED_MESSAGE


def with_encrypted_flag(data: bytes, name: str) -> bytes:
    out = bytearray(data)
    pos = out.find(b"PK\x01\x02")
    while pos >= 0:
        n_len = int.from_bytes(out[pos + 28 : pos + 30], "little")
        if out[pos + 46 : pos + 46 + n_len] == name.encode():
            out[pos + 8] |= 0x1
        pos = out.find(b"PK\x01\x02", pos + 4)
    return bytes(out)


def test_hwpx_content_wins_over_extension():
    from tests.e4.test_upload import make_docx, make_pdf

    as_docx = extract_plan("plan.docx", plan_hwpx())
    assert as_docx.kind == "hwpx" and any("확장자(.docx)" in w and "HWPX" in w for w in as_docx.warnings)
    docx_as_hwpx = extract_plan("plan.hwpx", make_docx())
    assert docx_as_hwpx.kind == "docx" and any("확장자(.hwpx)" in w for w in docx_as_hwpx.warnings)
    pdf_as_hwpx = extract_plan("plan.hwpx", make_pdf([PLAN_LINES]))
    assert pdf_as_hwpx.kind == "pdf" and pdf_as_hwpx.text.split("\n") == PLAN_LINES


def test_hwpx_broken_chars_ratio():
    bad = extract_plan("a.hwpx", make_hwpx([section(p("정상 본문 " * 30 + "\ufffd"))]))
    assert any("�" in w for w in bad.warnings)
    err = reject("b.hwpx", make_hwpx([section(p("깨짐\ufffd\ufffd\ufffd"))]))
    assert (err.status_code, err.message) == (422, upload.BROKEN_CHARS_MESSAGE)


def test_hwpx_char_limit_and_deadline():
    long_lines = [f"{i:05d} 연구 방법 {i * 7919 % 100003} 데이터 설명 문장입니다" for i in range(2_000)]
    assert reject("long.hwpx", make_hwpx([section(*(p(x) for x in long_lines))])).message == upload.TOO_MANY_CHARS_MESSAGE
    with pytest.raises(UploadRejected) as info:
        extract_plan("p.hwpx", plan_hwpx(), deadline_s=-1)
    assert (info.value.status_code, info.value.message) == (413, upload.TIMEOUT_MESSAGE)


# ── 격리 작업자(HTTP 경로) ─────────────────────────────────────────────────────


def test_isolated_hwpx_runs_in_worker(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("부모 프로세스에서 추출하면 안 된다")

    monkeypatch.setattr(upload, "_extract_hwpx", broken)
    result = extract_plan_isolated("p.hwpx", plan_hwpx())
    assert result.kind == "hwpx" and result.text.split("\n") == PLAN_LINES
    with pytest.raises(RuntimeError):
        extract_plan("p.hwpx", plan_hwpx())  # 대조: 같은 프로세스 경로는 막힌 함수를 쓴다


def test_isolated_hwpx_timeout_and_rejections():
    start = time.perf_counter()
    with pytest.raises(UploadRejected) as info:
        extract_plan_isolated("p.hwpx", plan_hwpx(), timeout_s=0.05)
    assert (info.value.status_code, info.value.message) == (413, upload.TIMEOUT_MESSAGE)
    assert time.perf_counter() - start < 5.0
    err = pytest.raises(UploadRejected, extract_plan_isolated, "x.hwpx", xxe_hwpx()).value  # 작업자 안 거부도 그대로
    assert (err.status_code, err.message) == (422, hwpx.HWPX_DTD_MESSAGE)
    assert pytest.raises(UploadRejected, extract_plan_isolated, "b.hwpx", section_bomb()).value.status_code == 413  # 부모에서


# ── HTTP ────────────────────────────────────────────────────────────────────


def test_api_hwpx_200_with_counts():
    client = TestClient(_app())
    res = client.post("/upload/plan", files={"file": ("계획서.hwpx", make_hwpx([rich_section()]), "application/hwp+zip")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["kind"] == "hwpx" and body["pages"] is None
    assert body["text"].split("\n") == RICH_EXPECTED
    assert body["lines"] == body["paragraphs"] == len(RICH_EXPECTED)
    assert body["chars"] == len(body["text"]) and body["chars_no_space"] == len("".join(body["text"].split()))
    locked = client.post("/upload/plan", files={"file": ("x.hwpx", xxe_hwpx())})
    assert locked.status_code == 422 and locked.json() == {"detail": hwpx.HWPX_DTD_MESSAGE}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


# ── 적대 입력 ────────────────────────────────────────────────────────────────


def xxe_hwpx(target: str = "file:///C:/Windows/win.ini") -> bytes:
    sec = (
        f'<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE hs:sec [<!ENTITY xxe SYSTEM "{target}">]>'
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}"><hp:p><hp:run><hp:t>&xxe;</hp:t></hp:run></hp:p></hs:sec>'
    )
    return make_hwpx([sec])


def laughs_hwpx() -> bytes:
    ents = '<!ENTITY lol "lol">' + "".join(f'<!ENTITY lol{i} "{("&lol" + (str(i - 1) if i > 1 else "") + ";") * 10}">' for i in range(1, 10))
    sec = f'<?xml version="1.0"?><!DOCTYPE lolz [{ents}]><hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}"><hp:p><hp:run><hp:t>&lol9;</hp:t></hp:run></hp:p></hs:sec>'
    return make_hwpx([sec])


def section_bomb(extra: int = MAX_ZIP_UNCOMPRESSED + 5 * 1024 * 1024) -> bytes:
    """본문 구역 압축 폭탄: 같은 문단을 되풀이해 압축 해제 크기만 키운다."""
    para = p("반복 문단 반복 문단")
    return make_hwpx([section(para * (extra // len(para.encode("utf-8"))))])


def deep_xml(depth: int) -> str:
    return section(p("앞 문단"), "<hp:x>" * depth + "</hp:x>" * depth)


def nested_tables(depth: int) -> str:
    inner = p("가장 안쪽 글")
    for i in range(depth):
        inner = p(f"층{i}", tbl([[[inner]]]))
    return section(p("시작"), inner)


def test_adversarial_zip_limits_fast():
    cases = {
        "section-bomb": (section_bomb(), 413, upload.ZIP_BOMB_MESSAGE),  # 압축 해제 25MB
        "section-ratio": (section_bomb(5 * 1024 * 1024), 413, upload.ZIP_BOMB_MESSAGE),  # 5MB, 압축비 100배 초과
        "many-entries": (make_hwpx([section(p("x"))], extra={f"BinData/i{n}.bmp": b"" for n in range(1001)}), 413,
                         upload.ZIP_BOMB_MESSAGE),
        "many-sections": (make_hwpx([section(p("x"))] * (hwpx.MAX_SECTIONS + 1)), 413, hwpx.HWPX_TOO_COMPLEX_MESSAGE),
    }
    for name, (data, status, message) in cases.items():
        assert len(data) < upload.MAX_UPLOAD_BYTES, name
        err, took = timed_reject(f"{name}.hwpx", data)
        assert (err.status_code, err.message) == (status, message), name
        assert took < ONE_SECOND, (name, took)


def test_bindata_images_are_not_inflated_so_not_counted():
    """한글이 BMP로 넣은 큰 그림(압축비 높음)은 풀지 않으므로 합계 상한에 세지 않는다(실제 5.8MB HWPX 오탐 방지)."""
    big_bmp = b"BM" + b"\x00" * (30 * 1024 * 1024)  # 압축 해제 30MB, 압축비 1,000배 넘음
    data = make_hwpx([section(p("그림이 든 계획서 본문"))], extra={"BinData/image1.bmp": big_bmp})
    start = time.perf_counter()
    result = extract_plan("그림.hwpx", data)
    assert result.text == "그림이 든 계획서 본문"
    assert time.perf_counter() - start < ONE_SECOND
    # 같은 그림을 DOCX에 넣으면 python-docx가 모든 부분을 읽으므로 지금처럼 막는다(대조)
    from tests.e4.test_upload import make_docx

    docx = rezip(make_docx(), {"word/media/image1.bmp": big_bmp})
    assert reject("그림.docx", docx).message == upload.ZIP_BOMB_MESSAGE


def test_adversarial_xml_dtd_entities_rejected():
    marker = "[fontsXX]"  # win.ini 첫 줄 흉내 — 응답·오류에 파일 내용이 나오면 안 된다
    for name, data in {
        "xxe": xxe_hwpx(),
        "xxe-http": xxe_hwpx("http://127.0.0.1:9/secret"),
        "laughs": laughs_hwpx(),
        "dtd-utf16": make_hwpx([
            ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a []>'
             f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}"/>').encode("utf-16")
        ]),
        "dtd-in-hpf": make_hwpx([section(p("본문"))], hpf=b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>'),
    }.items():
        err, took = timed_reject(f"{name}.hwpx", data)
        assert (err.status_code, err.message) == (422, hwpx.HWPX_DTD_MESSAGE), name
        assert marker not in err.message and took < ONE_SECOND, (name, took)


def test_adversarial_parser_is_safe_even_without_byte_check(monkeypatch, tmp_path):
    """바이트 검사를 꺼도(DTD 표시를 숨긴 인코딩 가정) 파서가 외부 엔티티를 읽지 않고 DTD가 있는 문서를 거부하며,
    엔티티 폭탄은 libxml2의 증폭 상한에 걸려 그 구역을 못 읽은 것으로 끝난다(미리보기 없으면 422)."""
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET-FILE-CONTENT", encoding="utf-8")
    monkeypatch.setattr(hwpx, "_DTD_MARKERS", ())
    err = reject("x.hwpx", xxe_hwpx(secret.as_uri()))
    assert (err.status_code, err.message) == (422, hwpx.HWPX_DTD_MESSAGE)
    assert "SECRET" not in err.message
    laughs = rezip(laughs_hwpx(), {"Preview/PrvText.txt": None})
    err, took = timed_reject("l.hwpx", laughs)
    assert (err.status_code, err.message) == (422, hwpx.HWPX_CORRUPT_MESSAGE) and took < ONE_SECOND


def test_adversarial_structure_cases_fast():
    good = plan_hwpx()
    cases = {
        "truncated-half": good[: len(good) // 2],
        "truncated-tail": good[:-10],
        "not-xml": make_hwpx([b"\x00\x01binary\xff" * 50], prvtext=None),
        "empty-section": make_hwpx([b""], prvtext=None),
        "undefined-entity": make_hwpx([section(p("x")).replace("<hp:t>x</hp:t>", "<hp:t>&nope;</hp:t>")], prvtext=None),
        "wrong-encoding-decl": make_hwpx([section(p("본문")).replace("UTF-8", "UTF-16")], prvtext=None),
        "deep-xml-300": make_hwpx([deep_xml(300)], prvtext=None),  # libxml2 깊이 상한(256) → 구역 실패
        "random-bytes": bytes(random.Random(7).getrandbits(8) for _ in range(4000)),
        "zip-magic-garbage": b"PK\x03\x04" + bytes(random.Random(8).getrandbits(8) for _ in range(4000)),
        "plain-zip": rezip(good, {"mimetype": None, "Contents/content.hpf": None, "Contents/section0.xml": None}),
    }
    for name, data in cases.items():
        err, took = timed_reject(f"{name}.hwpx", data)
        assert 400 <= err.status_code < 500, name
        assert took < ONE_SECOND, (name, took)
        assert "Traceback" not in err.message and "Error" not in err.message, name


def test_adversarial_nesting_and_element_cap(monkeypatch):
    deep = extract_plan("n.hwpx", make_hwpx([nested_tables(40)]))  # XML 깊이 256 안, 표 중첩 32단계 넘음
    # 바깥 표 셀 하나에 안쪽 문단·표가 공백으로 이어지고, 깊이 상한 밖(가장 안쪽 글 포함)은 건너뛴다
    assert deep.text.startswith("시작\n층39\n층38 층37 층36") and "가장 안쪽 글" not in deep.text
    assert hwpx.DEEP_WARNING in deep.warnings
    shallow = extract_plan("s.hwpx", make_hwpx([nested_tables(3)]))
    assert hwpx.DEEP_WARNING not in shallow.warnings and "가장 안쪽 글" in shallow.text
    monkeypatch.setattr(hwpx, "XML_MAX_ELEMENTS", 5_000)  # 상한 동작만 작게 확인(실제 50만 개는 보고서에 측정)
    many = make_hwpx([section(*(p(f"문단 {i}") for i in range(2_000)))])
    err, took = timed_reject("many.hwpx", many)
    assert (err.status_code, err.message) == (413, hwpx.HWPX_TOO_COMPLEX_MESSAGE) and took < ONE_SECOND


# ── 무작위 퍼징 ──────────────────────────────────────────────────────────────


def _seed_docs() -> list[bytes]:
    return [
        make_hwpx([rich_section()]),
        plan_hwpx(),
        make_hwpx([section(p("구역0")), section(p("구역1", tbl([["a", "b"], ["c"]])))], spine=[1, 0]),
        make_hwpx([rich_section()], compression=zipfile.ZIP_STORED),
    ]


def _mutate(rng: random.Random, seeds: list[bytes]) -> tuple[str, bytes]:
    base = rng.choice(seeds)
    op = rng.randrange(8)
    data = bytearray(base)
    if op == 0:  # 바이트 뒤집기
        for _ in range(rng.randint(1, 30)):
            data[rng.randrange(len(data))] = rng.getrandbits(8)
        return "flip", bytes(data)
    if op == 1:  # 자르기
        return "truncate", bytes(data[: rng.randrange(len(data))])
    if op == 2:  # 끼워 넣기·지우기
        pos = rng.randrange(len(data))
        if rng.random() < 0.5:
            return "insert", bytes(data[:pos] + bytes(rng.getrandbits(8) for _ in range(rng.randint(1, 64))) + data[pos:])
        return "delete", bytes(data[:pos] + data[pos + rng.randint(1, 64):])
    src = zipfile.ZipFile(io.BytesIO(base))
    name = rng.choice([i.filename for i in src.infolist()])
    blob = bytearray(src.read(name))
    if op == 3 and blob:  # 항목 XML 안 바이트 뒤집기(압축은 정상)
        for _ in range(rng.randint(1, 10)):
            blob[rng.randrange(len(blob))] = rng.getrandbits(8)
        return f"xmlflip:{name}", rezip(base, {name: bytes(blob)})
    if op == 4:  # 항목 XML에서 태그 조각 잘라 내기(구조 깨짐)
        cut = rng.randrange(len(blob) + 1)
        return f"xmlcut:{name}", rezip(base, {name: bytes(blob[:cut]) + bytes(blob[cut + rng.randint(1, 200):])})
    if op == 5:  # 항목 빼기
        return f"drop:{name}", rezip(base, {name: None})
    if op == 6:  # 이상한 항목 이름·경로 더하기
        odd = rng.choice(["../../evil.xml", "/abs/section0.xml", "Contents/section9999999.xml", "Contents/SECTION1.XML", "C:\\x.xml"])
        return f"oddname:{odd}", rezip(base, {odd: section(p("이상한 경로")).encode("utf-8")})
    return "random", b"PK\x03\x04" + bytes(rng.getrandbits(8) for _ in range(rng.randint(0, 3000)))


def run_fuzz(n: int, seed: int = 20260930) -> dict:
    """퍼징 n건. 결과별 건수·최대 시간. 예외(UploadRejected가 아닌 것)나 5xx가 하나라도 나오면 `unexpected`에 담는다."""
    rng = random.Random(seed)
    seeds = _seed_docs()
    stats: dict = {"n": n, "outcomes": {}, "max_s": 0.0, "slowest": None, "unexpected": [], "unguarded": []}
    for i in range(n):
        op, data = _mutate(rng, seeds)
        start = time.perf_counter()
        try:
            res = extract_plan(f"f{i}.hwpx", data)
            outcome = f"200 {res.kind}"
        except UploadRejected as exc:
            outcome = str(exc.status_code)
            if not 400 <= exc.status_code < 500:
                stats["unexpected"].append((i, op, outcome))
        except Exception as exc:  # noqa: BLE001 - 퍼징이 찾으려는 것
            outcome = "EXC"
            stats["unexpected"].append((i, op, type(exc).__name__))
        took = time.perf_counter() - start
        if took > stats["max_s"]:
            stats["max_s"], stats["slowest"] = took, (i, op, outcome)
        stats["outcomes"][outcome] = stats["outcomes"].get(outcome, 0) + 1
        # 방어선(catch-all) 없이도 UploadRejected로만 끝나는지: 추출기 본체를 직접 부른다
        try:
            hwpx._extract(data, upload._Budget(20.0))
        except UploadRejected:
            pass
        except Exception as exc:  # noqa: BLE001
            stats["unguarded"].append((i, op, type(exc).__name__))
    stats["max_s"] = round(stats["max_s"], 3)
    return stats


def test_fuzz_hwpx_300_cases_all_4xx_or_ok_under_1s():
    stats = run_fuzz(300)
    assert stats["unexpected"] == [], stats
    assert stats["unguarded"] == [], stats
    assert stats["max_s"] < ONE_SECOND, stats
    assert sum(v for k, v in stats["outcomes"].items() if k.startswith("4")) >= 100, stats  # 실제로 깨진 입력이 많이 들어갔다


def test_fuzz_through_isolated_worker():
    """퍼징 입력 몇 건을 격리 작업자 경로로도 보낸다: 4xx 또는 200, 작업자 실패(고정 문구)도 422로."""
    rng = random.Random(99)
    seeds = _seed_docs()
    for i in range(4):
        _, data = _mutate(rng, seeds)
        try:
            res = extract_plan_isolated(f"w{i}.hwpx", data)
            assert res.text
        except UploadRejected as exc:
            assert 400 <= exc.status_code < 500


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    n = int(sys.argv[sys.argv.index("--fuzz") + 1]) if "--fuzz" in sys.argv else 300
    print(json.dumps(run_fuzz(n), ensure_ascii=False, indent=1))
    sys.exit(0)
