"""계획서 업로드 파서(E4-L1a). `POST /upload/plan`.

- 받는 형식: txt·md(인코딩 추정 UTF-8 → CP949), pdf(pypdf), docx(python-docx).
  확장자와 매직바이트를 함께 본다. 내용이 PDF·DOCX로 확인되면 확장자가 달라도 내용 기준으로 읽고 경고를 남긴다.
- HWP·HWPX는 415로 거부하고 "HWP는 PDF나 DOCX로 저장해 올려 주세요"라고 안내한다.
- 10MB(10 × 1024 × 1024바이트) 초과는 413.
- **디스크에 쓰지 않는다.** Starlette의 기본 multipart 처리(`UploadFile`)는 1MB가 넘으면 임시 파일로
  내려 쓰므로 쓰지 않고, 요청 본문을 스트림으로 읽어 메모리에서만 파싱한다. 로그에도 본문·파일명을 남기지 않는다.

main.py 연결(PM): `from neumann.api.upload import router as upload_router; app.include_router(upload_router)`.
파이프라인에서 쓸 때: `parse_plan_upload(filename, data) -> str` (거부는 `UploadRejected` 예외, `.status_code`·`.message`).
"""

from __future__ import annotations

import codecs
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.concurrency import run_in_threadpool

from neumann.models import normalize_text

PlanKind = Literal["txt", "md", "pdf", "docx"]

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
"""업로드 파일 상한(10MB). 넘으면 413."""
MULTIPART_OVERHEAD_BYTES = 64 * 1024
"""multipart 경계·헤더·작은 필드 몫. 요청 본문 전체 상한 = 파일 상한 + 이 값."""
MAX_PDF_PAGES = 300
"""이보다 긴 PDF는 앞쪽만 읽고 경고를 남긴다(연구계획서는 보통 수십 쪽)."""
MAX_DOCX_UNCOMPRESSED = 100 * 1024 * 1024
"""DOCX(zip) 압축 해제 합계 상한. zip 폭탄 방지."""
MAX_REPLACEMENT_RATIO = 0.05
"""UTF-8·CP949 둘 다 실패했을 때, 깨진 글자 비율이 이보다 크면 텍스트 파일로 보지 않는다."""

HWP_MESSAGE = "HWP는 PDF나 DOCX로 저장해 올려 주세요"
TOO_LARGE_MESSAGE = "파일이 10MB를 넘습니다. 10MB 이하로 줄여 올려 주세요"
UNSUPPORTED_MESSAGE = "지원하지 않는 형식입니다. txt·md·pdf·docx만 올릴 수 있습니다"
LEGACY_OFFICE_MESSAGE = "구형 Office 문서(.doc 등)는 지원하지 않습니다. DOCX나 PDF로 저장해 올려 주세요"

HWP_EXTS = frozenset({".hwp", ".hwpx", ".hwt", ".hml"})
EXT_KIND: dict[str, PlanKind] = {".txt": "txt", ".md": "md", ".markdown": "md", ".pdf": "pdf", ".docx": "docx"}

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
HWP_SIGNATURE = b"HWP Document File"
HWP_SUMMARY_UTF16 = "HwpSummaryInformation".encode("utf-16-le")
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06")


class UploadRejected(Exception):
    """업로드를 받지 않는 이유. `status_code`는 HTTP 상태(413·415·422·400), `message`는 사용자 안내 문구."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class PlanExtract:
    """추출 결과. `text`는 LF·NFC 정규화를 거친 본문이다(개인정보 가림은 `PlanDocument.from_text`가 한다)."""

    filename: str
    kind: PlanKind
    text: str
    size_bytes: int
    pages: int | None = None
    encoding: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def lines(self) -> int:
        """`PlanDocument.from_text`와 같은 규칙(`split("\\n")`)으로 센 줄 수."""
        return len(self.text.split("\n")) if self.text else 0


# ── 형식 판별 ───────────────────────────────────────────────────────────────


def _safe_filename(filename: str) -> str:
    """경로 성분을 떼고 이름만 남긴다(`C:\\fakepath\\a.pdf` → `a.pdf`)."""
    name = PureWindowsPath(PurePosixPath(filename or "").name).name
    return name.strip()[:255]


def _looks_like_hwp(data: bytes) -> bool:
    if data.startswith(HWP_SIGNATURE):  # HWP 3.x
        return True
    if data.startswith(OLE_MAGIC):  # HWP 5.x는 OLE 복합 문서다
        return HWP_SIGNATURE in data or HWP_SUMMARY_UTF16 in data
    return False


def _sniff_zip(data: bytes) -> Literal["docx", "hwpx", "zip", "binary"]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            names = {i.filename for i in infos}
            mimetype = next((i for i in infos if i.filename == "mimetype"), None)
            if mimetype is not None and mimetype.file_size <= 256:
                if zf.read(mimetype).strip().lower().startswith(b"application/hwp"):
                    return "hwpx"
            if any(n.startswith("Contents/section") or n == "Contents/content.hpf" for n in names):
                return "hwpx"
            if "word/document.xml" in names:
                return "docx"
            return "zip"
    except Exception:  # 손상 zip, 암호 zip(RuntimeError), 미지원 압축(NotImplementedError) 등
        return "binary"


def _sniff(data: bytes, ext_kind: str | None) -> Literal["pdf", "docx", "hwpx", "zip", "ole", "binary", "text"]:
    # PDF 머리는 보통 0바이트 위치다. 규격상 앞 1024바이트 안이면 되지만, 그 경우는 확장자도 .pdf일 때만 믿는다
    # (본문에 "%PDF-"라는 글자가 든 txt·md를 PDF로 오인하지 않게).
    pdf_at = data[:1024].find(b"%PDF-")
    if pdf_at == 0 or (pdf_at > 0 and ext_kind == "pdf"):
        return "pdf"
    if data.startswith(ZIP_MAGICS):
        return _sniff_zip(data)
    if data.startswith(OLE_MAGIC):
        return "ole"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "text"
    if b"\x00" in data[:8192]:
        return "binary"
    return "text"


def _detect_kind(filename: str, data: bytes) -> tuple[PlanKind, list[str]]:
    ext = PurePosixPath(filename.lower()).suffix
    if ext in HWP_EXTS or _looks_like_hwp(data):
        raise UploadRejected(415, HWP_MESSAGE)
    ext_kind = EXT_KIND.get(ext)
    magic = _sniff(data, ext_kind)
    if magic == "hwpx":
        raise UploadRejected(415, HWP_MESSAGE)
    if magic in ("pdf", "docx"):
        warnings: list[str] = []
        if ext_kind != magic:
            shown = ext or "없음"
            warnings.append(f"확장자({shown})와 내용이 달라 내용 기준({magic.upper()})으로 읽었습니다")
        return magic, warnings  # type: ignore[return-value]
    if magic == "ole":
        raise UploadRejected(415, LEGACY_OFFICE_MESSAGE)
    if ext_kind in ("pdf", "docx"):
        raise UploadRejected(422, f"{ext_kind.upper()} 파일이 아니거나 손상되었습니다. 다시 저장해 올려 주세요")
    if magic == "text" and ext_kind in ("txt", "md"):
        return ext_kind, []
    raise UploadRejected(415, UNSUPPORTED_MESSAGE)


# ── 형식별 추출 ─────────────────────────────────────────────────────────────


def _decode_text(data: bytes) -> tuple[str, str, list[str]]:
    """(본문, 인코딩, 경고). BOM → UTF-8 → CP949 → UTF-8(깨진 글자 치환) 순서."""
    if data.startswith(codecs.BOM_UTF8):
        try:
            return data.decode("utf-8-sig"), "utf-8-sig", []
        except UnicodeDecodeError:
            pass
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16"), "utf-16", []
        except UnicodeDecodeError as exc:
            raise UploadRejected(422, "UTF-16 텍스트를 읽을 수 없습니다. UTF-8로 저장해 올려 주세요") from exc
    else:
        try:
            return data.decode("utf-8"), "utf-8", []
        except UnicodeDecodeError:
            pass
        try:
            text = data.decode("cp949")
            return text, "cp949", ["UTF-8이 아니어서 CP949(EUC-KR)로 읽었습니다. 글자가 깨졌다면 UTF-8로 저장해 올려 주세요"]
        except UnicodeDecodeError:
            pass
    text = data.decode("utf-8", errors="replace").removeprefix("\ufeff")
    bad = text.count("\ufffd")
    if not text or bad / len(text) > MAX_REPLACEMENT_RATIO:
        raise UploadRejected(422, "텍스트 인코딩을 알 수 없습니다. UTF-8로 저장해 올려 주세요")
    return text, "utf-8", [f"UTF-8로 읽지 못한 글자 {bad}곳을 �로 바꿨습니다"]


def _extract_pdf(data: bytes) -> tuple[str, int, list[str]]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                opened = int(reader.decrypt(""))  # PasswordType: 0 = NOT_DECRYPTED
            except Exception:  # 암호 알고리즘 미지원(cryptography 없음) 등
                opened = 0
            if opened == 0:
                raise UploadRejected(422, "암호가 걸린 PDF는 읽을 수 없습니다. 암호를 풀고 다시 올려 주세요")
        n_pages = len(reader.pages)
    except UploadRejected:
        raise
    except Exception as exc:  # pypdf는 손상 파일에서 여러 종류의 예외를 낸다
        raise UploadRejected(422, "PDF를 읽을 수 없습니다(손상된 파일일 수 있습니다)") from exc

    warnings: list[str] = []
    texts: list[str] = []
    empty: list[int] = []
    failed: list[int] = []
    for i in range(min(n_pages, MAX_PDF_PAGES)):
        try:
            page_text = reader.pages[i].extract_text() or ""
        except Exception:
            failed.append(i + 1)
            continue
        if page_text.strip():
            texts.append(page_text.strip("\r\n"))  # 쪽 경계에 빈 줄을 끼우지 않는다(문단이 쪽을 넘어가도 이어지게)
        else:
            empty.append(i + 1)
    if n_pages > MAX_PDF_PAGES:
        warnings.append(f"{n_pages}쪽 중 앞 {MAX_PDF_PAGES}쪽만 읽었습니다")
    if failed:
        warnings.append(f"텍스트 추출에 실패한 쪽: {_pages(failed)}")
    if empty:
        warnings.append(f"텍스트가 없는 쪽: {_pages(empty)} (스캔 이미지일 수 있습니다. 문자 인식(OCR)은 하지 않습니다)")
    return "\n".join(texts), n_pages, warnings


def _pages(numbers: list[int], limit: int = 20) -> str:
    shown = ", ".join(str(n) for n in numbers[:limit])
    return shown + (f" 외 {len(numbers) - limit}쪽" if len(numbers) > limit else "")


def _w(tag: str) -> str:
    return "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}" + tag


_W_P, _W_TBL, _W_TR, _W_TC = _w("p"), _w("tbl"), _w("tr"), _w("tc")
_W_SDT, _W_SDT_CONTENT, _W_CUSTOM_XML = _w("sdt"), _w("sdtContent"), _w("customXml")


def _children(el):  # noqa: ANN001, ANN202 - lxml 요소
    """자식 요소. 내용 컨트롤(`w:sdt`)·`w:customXml` 포장은 벗겨서 안쪽 요소를 돌려준다."""
    for child in el.iterchildren():
        if child.tag == _W_SDT:
            content = child.find(_W_SDT_CONTENT)
            if content is not None:
                yield from _children(content)
        elif child.tag == _W_CUSTOM_XML:
            yield from _children(child)
        else:
            yield child


def _docx_lines(el, doc):  # noqa: ANN001, ANN202
    """본문 순서대로 줄을 낸다. 문단은 한 줄, 표는 행마다 한 줄(셀은 ` | `로 잇는다)."""
    from docx.text.paragraph import Paragraph

    for child in _children(el):
        if child.tag == _W_P:
            yield Paragraph(child, doc).text
        elif child.tag == _W_TBL:
            for tr in (c for c in _children(child) if c.tag == _W_TR):
                cells = []
                # 실제 셀(w:tc)만 돈다: 가로 병합은 셀 하나, 세로 병합 연속 셀은 비어 있어 빠진다
                for tc in (c for c in _children(tr) if c.tag == _W_TC):
                    cell = " ".join(s.strip() for s in _docx_lines(tc, doc) if s.strip())
                    if cell:
                        cells.append(cell.replace("\n", " "))
                if cells:
                    yield " | ".join(cells)


def _extract_docx(data: bytes) -> tuple[str, list[str]]:
    from docx import Document

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if sum(i.file_size for i in zf.infolist()) > MAX_DOCX_UNCOMPRESSED:
                raise UploadRejected(422, "DOCX 압축을 푼 크기가 너무 큽니다")
        doc = Document(io.BytesIO(data))
        lines = list(_docx_lines(doc.element.body, doc))
    except UploadRejected:
        raise
    except Exception as exc:
        raise UploadRejected(422, "DOCX를 읽을 수 없습니다(손상된 파일일 수 있습니다)") from exc
    return "\n".join(lines), []


# ── 정리·진입점 ─────────────────────────────────────────────────────────────

_CONTROL_TO_NEWLINE = str.maketrans({"\x0b": "\n", "\x0c": "\n", "\u2028": "\n", "\u2029": "\n"})
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # \uc720\ub2c8\ucf54\ub4dc Cc \uc911 \ud0ed(\x09)\u00b7\uc904\ubc14\uafc8(\x0a) \uc81c\uc678


def _clean(text: str, *, collapse_blank: bool) -> str:
    """LF·NFC 정규화, 제어문자 제거(탭·줄바꿈 제외), 줄 끝 공백 제거, 앞뒤 빈 줄 제거.

    pdf·docx는 연속 빈 줄을 하나로 줄인다. txt·md는 사용자가 쓴 줄 구조를 그대로 둔다.
    """
    text = normalize_text(text).translate(_CONTROL_TO_NEWLINE)
    text = _CONTROL_RE.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    if collapse_blank:
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n")


def extract_plan(filename: str, data: bytes) -> PlanExtract:
    """업로드 바이트에서 계획서 본문과 메타(쪽수·인코딩·경고)를 뽑는다. 받지 않으면 `UploadRejected`."""
    name = _safe_filename(filename)
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(413, TOO_LARGE_MESSAGE)
    if not data:
        raise UploadRejected(422, "빈 파일입니다")
    kind, warnings = _detect_kind(name, data)
    pages: int | None = None
    encoding: str | None = None
    if kind == "pdf":
        raw, pages, more = _extract_pdf(data)
    elif kind == "docx":
        raw, more = _extract_docx(data)
    else:
        raw, encoding, more = _decode_text(data)
    warnings.extend(more)
    text = _clean(raw, collapse_blank=kind in ("pdf", "docx"))
    if not text.strip():
        hint = " 스캔한 PDF라면 텍스트가 들어 있는 PDF나 DOCX로 올려 주세요" if kind == "pdf" else ""
        raise UploadRejected(422, "파일에서 텍스트를 찾지 못했습니다." + hint)
    return PlanExtract(
        filename=name,
        kind=kind,
        text=text,
        size_bytes=len(data),
        pages=pages,
        encoding=encoding,
        warnings=tuple(warnings),
    )


def parse_plan_upload(filename: str, data: bytes) -> str:
    """업로드 파일 → 계획서 본문(LF·NFC). 크기 초과·HWP·미지원·손상이면 `UploadRejected`."""
    return extract_plan(filename, data).text


# ── HTTP ───────────────────────────────────────────────────────────────────


class PlanUploadResponse(BaseModel):
    filename: str
    kind: PlanKind
    size_bytes: int = Field(ge=1)
    pages: int | None = Field(default=None, description="PDF 쪽수. 다른 형식은 null")
    encoding: str | None = Field(default=None, description="txt·md를 읽은 인코딩. 다른 형식은 null")
    text: str
    lines: int = Field(ge=1, description="줄 수(PlanDocument 줄 번호와 같은 규칙)")
    chars: int = Field(ge=1)
    warnings: list[str] = Field(default_factory=list, description="추출 경고(인코딩 추정, 빈 쪽, 확장자 불일치 등)")


class _FilePartCollector:
    """python-multipart 콜백. 첫 번째 파일 파트만 메모리(bytearray)에 모은다. 다른 필드는 버린다."""

    def __init__(self) -> None:
        self.filename: str | None = None
        self.data = bytearray()
        self.files = 0
        self._header_name = b""
        self._header_value = b""
        self._disposition = b""
        self._collecting = False

    def callbacks(self) -> dict:
        return {
            "on_part_begin": self.on_part_begin,
            "on_part_data": self.on_part_data,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
        }

    def on_part_begin(self) -> None:
        self._disposition = b""
        self._collecting = False

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def on_header_end(self) -> None:
        if self._header_name.strip().lower() == b"content-disposition":
            self._disposition = self._header_value
        self._header_name = b""
        self._header_value = b""

    def on_headers_finished(self) -> None:
        _, options = parse_options_header(self._disposition)
        if b"filename" not in options:
            return
        self.files += 1
        if self.files > 1:
            raise UploadRejected(400, "한 번에 파일 하나만 올려 주세요")
        raw = options[b"filename"]
        try:
            self.filename = raw.decode("utf-8")
        except UnicodeDecodeError:
            self.filename = raw.decode("latin-1")
        self._collecting = True

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if not self._collecting:
            return
        if len(self.data) + (end - start) > MAX_UPLOAD_BYTES:
            raise UploadRejected(413, TOO_LARGE_MESSAGE)
        self.data += data[start:end]


async def _read_file_part(request: Request) -> tuple[str, bytes]:
    """multipart/form-data 요청에서 파일 하나를 메모리로 읽는다. 임시 파일을 만들지 않는다."""
    ctype, params = parse_options_header(request.headers.get("content-type"))
    if ctype.strip().lower() != b"multipart/form-data":
        raise UploadRejected(415, "multipart/form-data 형식으로 file 필드에 계획서 파일을 담아 보내 주세요")
    boundary = params.get(b"boundary")
    if not boundary:
        raise UploadRejected(400, "multipart 경계(boundary)가 없습니다")
    limit = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise UploadRejected(413, TOO_LARGE_MESSAGE)

    collector = _FilePartCollector()
    parser = MultipartParser(boundary, collector.callbacks())
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > limit:
                raise UploadRejected(413, TOO_LARGE_MESSAGE)
            parser.write(chunk)
        parser.finalize()
    except FormParserError as exc:
        raise UploadRejected(400, "multipart 본문을 해석할 수 없습니다") from exc
    if collector.filename is None:
        raise UploadRejected(422, "file 필드에 계획서 파일이 없습니다")
    return collector.filename, bytes(collector.data)


router = APIRouter(tags=["upload"])

_ERROR_RESPONSES = {
    400: {"description": "multipart 형식 오류, 파일 여러 개"},
    413: {"description": TOO_LARGE_MESSAGE},
    415: {"description": f"HWP·HWPX(\"{HWP_MESSAGE}\"), 그 밖의 미지원 형식"},
    422: {"description": "빈 파일, 손상·암호 PDF, 텍스트 없음"},
}


@router.post(
    "/upload/plan",
    response_model=PlanUploadResponse,
    summary="계획서 파일(txt·md·pdf·docx, 10MB 이하)에서 텍스트 추출. 디스크에 저장하지 않는다",
    responses=_ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def upload_plan(request: Request) -> PlanUploadResponse:
    try:
        filename, data = await _read_file_part(request)
        result = await run_in_threadpool(extract_plan, filename, data)
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    return PlanUploadResponse(
        filename=result.filename,
        kind=result.kind,
        size_bytes=result.size_bytes,
        pages=result.pages,
        encoding=result.encoding,
        text=result.text,
        lines=result.lines,
        chars=len(result.text),
        warnings=list(result.warnings),
    )


__all__ = [
    "HWP_MESSAGE",
    "MAX_UPLOAD_BYTES",
    "PlanExtract",
    "PlanUploadResponse",
    "UploadRejected",
    "extract_plan",
    "parse_plan_upload",
    "router",
]
