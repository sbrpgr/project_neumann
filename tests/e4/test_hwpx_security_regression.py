"""E4-L2h ZIP/XML 회귀: 메타데이터·숨은 요소도 같은 보안 한도를 지킨다."""

from __future__ import annotations

import codecs
import io
import unicodedata
import warnings
import zipfile

import pytest
from fastapi.testclient import TestClient

import neumann.api.hwpx as hwpx
import neumann.api.upload as upload
from neumann.models import PlanDocument, contains_pii
from tests.e4.test_upload_hwpx import (
    EMPTY_MANIFEST, HP, _app, content_hpf, make_hwpx, p, plan_hwpx, section,
)


def rejected(data: bytes, status: int, message: str) -> None:
    with pytest.raises(upload.UploadRejected) as exc:
        upload.extract_plan("plan.hwpx", data)
    assert (exc.value.status_code, exc.value.message) == (status, message)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32-le", "utf-32-be"])
@pytest.mark.parametrize("bom", [False, True])
def test_encrypted_manifest_encoding_cannot_fall_back_to_preview(encoding, bom):
    declared = "UTF-32" if encoding.startswith("utf-32") else encoding
    manifest = (
        f'<?xml version="1.0" encoding="{declared}"?>'
        '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
        '<odf:file-entry><odf:encryption-data/></odf:file-entry></odf:manifest>'
    ).encode(encoding)
    if bom and encoding.startswith("utf-32"):
        manifest = (codecs.BOM_UTF32_LE if encoding.endswith("le") else codecs.BOM_UTF32_BE) + manifest
    rejected(make_hwpx([section(p("본문"))], manifest=manifest), 422, hwpx.HWPX_ENCRYPTED_MESSAGE)


@pytest.mark.parametrize("encoding", ["utf-32-le", "utf-32-be"])
@pytest.mark.parametrize("bom", [False, True])
def test_valid_utf32_manifest_remains_supported(encoding, bom):
    manifest = '<?xml version="1.0" encoding="UTF-32"?><manifest/>'.encode(encoding)
    if bom:
        manifest = (codecs.BOM_UTF32_LE if encoding.endswith("le") else codecs.BOM_UTF32_BE) + manifest
    result = upload.extract_plan("plan.hwpx", make_hwpx([section(p("본문"))], manifest=manifest))
    assert result.text == "본문" and result.warnings == ()


@pytest.mark.parametrize("mimetype", [False, True])
def test_minimal_hwpx_for_document_sample_builder(mimetype):
    from tests.e4.test_upload import make_zip

    parts = {"Contents/section0.xml": section(p("첫 문단"), p("둘째 문단")).encode("utf-8")}
    if mimetype:
        parts["mimetype"] = b"application/hwp+zip"
    result = upload.extract_plan("sample.hwpx", make_zip(parts))
    assert result.kind == "hwpx" and result.text == "첫 문단\n둘째 문단"
    assert result.warnings == ()


@pytest.mark.parametrize("part", ["section", "hpf", "manifest"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32-le", "utf-32-be"])
def test_dtd_in_every_parsed_xml_part_is_rejected_even_with_preview(part, encoding):
    declared = "UTF-32" if encoding.startswith("utf-32") else encoding
    raw = (
        f'<?xml version="1.0" encoding="{declared}"?>'
        '<!DOCTYPE sec [<!ENTITY x SYSTEM "http://127.0.0.1:9/never-fetch">]>'
        f'<sec xmlns:hp="{HP}"><hp:p><hp:run><hp:t>&x;</hp:t></hp:run></hp:p></sec>'
    ).encode(encoding)
    kwargs = {"hpf": raw} if part == "hpf" else {"manifest": raw} if part == "manifest" else {}
    data = make_hwpx([raw if part == "section" else section(p("정상 본문"))], **kwargs)
    rejected(data, 422, hwpx.HWPX_DTD_MESSAGE)


@pytest.mark.parametrize("container", ["header", "hiddenComment", "secPr", "t"])
def test_element_limit_counts_skipped_and_inline_subtrees(monkeypatch, container):
    monkeypatch.setattr(hwpx, "XML_MAX_ELEMENTS", 80)
    hidden = f'<hp:{container}><hp:x>' + '<hp:x/>' * 100 + f'</hp:x></hp:{container}>'
    if container == "t":
        hidden = p("", f'<hp:run>{hidden}</hp:run>')
    data = make_hwpx([section(p("본문"), hidden)])
    rejected(data, 413, hwpx.HWPX_TOO_COMPLEX_MESSAGE)


@pytest.mark.parametrize("part", ["hpf", "manifest"])
def test_element_limit_counts_metadata(monkeypatch, part):
    monkeypatch.setattr(hwpx, "XML_MAX_ELEMENTS", 80)
    raw = b'<meta>' + b'<x/>' * 100 + b'</meta>'
    data = make_hwpx([section(p("본문"))], **{part: raw})
    rejected(data, 413, hwpx.HWPX_TOO_COMPLEX_MESSAGE)


def test_element_limit_is_cumulative_across_sections(monkeypatch):
    monkeypatch.setattr(hwpx, "XML_MAX_ELEMENTS", 80)
    hidden = '<hp:header>' + '<hp:x/>' * 45 + '</hp:header>'
    rejected(make_hwpx([section(p("첫째"), hidden), section(p("둘째"), hidden)]),
             413, hwpx.HWPX_TOO_COMPLEX_MESSAGE)


def test_small_hidden_subtree_remains_supported(monkeypatch):
    monkeypatch.setattr(hwpx, "XML_MAX_ELEMENTS", 80)
    hidden = '<hp:header>' + '<hp:x/>' * 10 + '</hp:header>'
    result = upload.extract_plan("plan.hwpx", make_hwpx([section(p("본문"), hidden)]))
    assert result.text == "본문" and result.warnings == ()


@pytest.mark.parametrize("manifest", [b'<manifest><encryption-data>', b'not XML'])
def test_unreadable_manifest_cannot_skip_security_checks(manifest):
    rejected(make_hwpx([section(p("본문"))], manifest=manifest), 422, hwpx.HWPX_CORRUPT_MESSAGE)


def test_oversized_manifest_cannot_skip_security_checks():
    manifest = b'<manifest>' + b' ' * hwpx.META_MAX_BYTES + b'<encryption-data/></manifest>'
    rejected(make_hwpx([section(p("본문"))], manifest=manifest, compression=zipfile.ZIP_STORED),
             413, hwpx.HWPX_TOO_COMPLEX_MESSAGE)


def test_case_variant_manifest_is_checked():
    data = make_hwpx([section(p("본문"))])
    from tests.e4.test_upload_hwpx import rezip

    data = rezip(data, {"META-INF/manifest.xml": None,
                        "META-INF/MANIFEST.XML": b'<!DOCTYPE x [<!ENTITY a "b">]><x/>'})
    rejected(data, 422, hwpx.HWPX_DTD_MESSAGE)


@pytest.mark.parametrize("name", ["Contents/section0.xml", "Contents/content.hpf", "META-INF/manifest.xml"])
def test_duplicate_parsed_zip_parts_are_rejected(name):
    raw = {"Contents/section0.xml": section(p("다른 본문")).encode(),
           "Contents/content.hpf": content_hpf(1), "META-INF/manifest.xml": EMPTY_MANIFEST}[name]
    buf = io.BytesIO(plan_hwpx())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(buf, "a") as zf:
            zf.writestr(name, raw)
    rejected(buf.getvalue(), 422, hwpx.HWPX_CORRUPT_MESSAGE)


def test_metadata_dtd_http_error_does_not_echo_filename_or_input():
    data = make_hwpx([section(p("본문"))], manifest=b'<!DOCTYPE x [<!ENTITY a "private-marker">]><x/>')
    with TestClient(_app()) as client:
        res = client.post("/upload/plan", files={"file": ("private-filename.hwpx", data)})
    assert res.status_code == 422
    assert res.json() == {"detail": hwpx.HWPX_DTD_MESSAGE}
    assert "private-marker" not in res.text and "private-filename" not in res.text


def test_hwpx_normalization_and_existing_plan_pii_boundary():
    body = unicodedata.normalize("NFD", "연구 목표") + "\r\n담당: researcher@example.org\r\nORCID 0000-0002-1825-0097"
    result = upload.extract_plan("plan.hwpx", make_hwpx([section(p(body)).replace("\r", "&#13;")]))
    assert result.text.startswith("연구 목표\n담당:") and "\r" not in result.text
    # 업로드는 추출만 한다. 기존 계약의 PlanDocument 생성 시 가림·행 번호를 검증한다.
    plan = PlanDocument.from_text(result.text, "hwpx-regression")
    assert not contains_pii(plan.text)
    assert "researcher@example.org" not in plan.text and "0000-0002-1825-0097" not in plan.text
    assert [line.no for line in plan.lines] == list(range(1, result.lines + 1))
    assert "text" not in plan.dump_persisted()
