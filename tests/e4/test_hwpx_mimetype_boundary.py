"""격리 전 mimetype 판별: 작은 ZIP의 선언 크기 위조도 fail closed."""

import io
import struct
import zipfile
import zlib

import pytest
from fastapi.testclient import TestClient

from neumann.api import upload
from neumann.models import PlanDocument, contains_pii
from tests.e4.test_upload_hwpx import _app, make_hwpx, p, section


def forged_mimetype(*, forge_crc=False):
    body = b"application/hwp+zip" + b"x" * 65536
    data = bytearray(make_hwpx([section(p("첫째"), p("둘째"))], extra={"unused": b""}))
    # 기존 정상 문서는 그대로 두고 mimetype 내용만 64KiB로 바꾼다.
    from tests.e4.test_upload_hwpx import rezip

    data = bytearray(rezip(bytes(data), {"mimetype": body}))
    pos = data.find(b"PK\x01\x02")
    while pos >= 0:
        size = int.from_bytes(data[pos + 28:pos + 30], "little")
        if data[pos + 46:pos + 46 + size] == b"mimetype":
            struct.pack_into("<I", data, pos + 24, 1)
            if forge_crc:
                struct.pack_into("<I", data, pos + 16, zlib.crc32(body[:1]))
            return bytes(data)
        pos = data.find(b"PK\x01\x02", pos + 4)
    raise AssertionError("mimetype entry missing")


@pytest.mark.parametrize("forge_crc", [False, True])
def test_forged_mimetype_rejected_before_worker(monkeypatch, forge_crc):
    data = forged_mimetype(forge_crc=forge_crc)
    assert len(data) < 4096
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        info = zf.getinfo("mimetype")
        assert info.file_size == 1 and info.compress_size < 256
    monkeypatch.setattr(upload, "_run_worker", lambda *_: pytest.fail("worker must not start"))
    with pytest.raises(upload.UploadRejected) as exc:
        upload.extract_plan_isolated("p.hwpx", data)
    assert exc.value.status_code == 422


def test_forged_mimetype_http_422():
    with TestClient(_app()) as client:
        res = client.post("/upload/plan", files={"file": ("p.hwpx", forged_mimetype())})
    assert res.status_code == 422
    assert set(res.json()) == {"detail"}


def test_sniff_has_bounded_output_and_never_uses_zip_read_or_flush(monkeypatch):
    original = zlib.decompressobj
    calls = []

    class Decoder:
        def __init__(self, *args):
            self.inner = original(*args)

        def decompress(self, data, max_length):
            out = self.inner.decompress(data, max_length)
            calls.append((len(data), max_length, len(out)))
            return out

        def __getattr__(self, name):
            if name == "flush":
                pytest.fail("sniff must not flush unbounded decompression")
            return getattr(self.inner, name)

    data = forged_mimetype(forge_crc=True)
    monkeypatch.setattr(upload.zlib, "decompressobj", Decoder)
    monkeypatch.setattr(zipfile.ZipFile, "read", lambda *_: pytest.fail("sniff must not call ZipFile.read"))
    with pytest.raises(upload.UploadRejected) as exc:
        upload._sniff_zip(data)
    assert exc.value.status_code == 422
    assert len(calls) == 1 and calls[0][0] < 256
    assert calls[0][1:] == (257, 257)


@pytest.mark.parametrize("size", [256, 257])
def test_mimetype_size_boundary(size):
    from tests.e4.test_upload_hwpx import rezip

    mime = b"application/hwp+zip".ljust(size, b" ")
    data = rezip(make_hwpx([section(p("본문"))]), {"mimetype": mime})
    if size == 256:
        assert upload.extract_plan("p.hwpx", data).text == "본문"
    else:
        with pytest.raises(upload.UploadRejected) as exc:
            upload.extract_plan("p.hwpx", data)
        assert exc.value.status_code == 422


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_normal_mimetype_keeps_hwpx_md_identity(compression):
    from tests.e4.test_upload_hwpx import rezip

    data = rezip(make_hwpx([section(p("첫째"), p("담당 researcher@example.org"),
                                   p("ORCID 0000-0002-1825-0097"))]),
                 {"mimetype": b"application/hwp+zip"}, compression=compression)
    extracted = upload.extract_plan("p.hwpx", data)
    md = upload.extract_plan("p.md", extracted.text.encode())
    assert extracted.text == md.text and extracted.warnings == ()
    plan = PlanDocument.from_text(extracted.text, "identity")
    other = PlanDocument.from_text(md.text, "identity")
    assert plan.plan_id == other.plan_id and not contains_pii(plan.text)
    assert [line.no for line in plan.lines] == [1, 2, 3]


def test_mutation_restoring_swallowed_mimetype_error_is_detected(monkeypatch):
    safe = upload._zip_kind

    def unsafe(zf, infos):
        try:
            return safe(zf, infos)
        except upload.UploadRejected:
            return "hwpx"  # 기존 반례처럼 손상 정보를 삼키고 section으로 진행하는 변이

    monkeypatch.setattr(upload, "_zip_kind", unsafe)
    with pytest.raises(pytest.fail.Exception):
        test_forged_mimetype_rejected_before_worker(monkeypatch, False)
