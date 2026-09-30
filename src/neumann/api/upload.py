"""계획서 업로드 파서(E4-L1a). `POST /upload/plan`.

- 받는 형식: txt·md(인코딩 추정 UTF-8 → CP949), pdf(pypdf), docx(python-docx).
  확장자와 매직바이트를 함께 본다. 내용이 PDF·DOCX로 확인되면 확장자가 달라도 내용 기준으로 읽고 경고를 남긴다.
- HWP·HWPX는 415로 거부하고 "HWP는 PDF나 DOCX로 저장해 올려 주세요"라고 안내한다.
- **상한(SEC-1 S-03, 업로드 증폭 차단). 넘으면 413, 붐비면 503.**
  파일 10MB(10 × 1024 × 1024바이트) · 추출 글자 50,000자 · 줄 5,000줄(422, SEC-7) · PDF 200쪽 ·
  DOCX 압축 해제 합계 20MB·항목 1,000개·압축비 100배(1MB 넘는 항목) · 처리 시간 10초(SEC-7, 옛 20초) · 동시 처리 2건.
  HTTP 경로의 pdf·docx 추출은 **별도 프로세스**에서 돌리고 시간이 넘으면 강제 종료한다(pypdf·python-docx가
  한 쪽·한 문서 안에서 오래 걸려도 서버 CPU를 붙잡지 못하게). 그 프로세스에는 비밀값 환경변수를 넘기지 않고,
  감사 훅으로 디스크 쓰기를 막는다. 추출 루프 안에서도 시간·글자 예산을 확인해 일찍 멈춘다.
- **PDF 폭탄(SEC-7).** 작업자 프로세스 메모리(커밋) 상한 512MB(Windows 작업 개체·POSIX RLIMIT_AS, 자식 프로세스 금지),
  스트림 하나 해제 크기 8MB, 쪽 내용 스트림 1MB(넘는 쪽은 읽지 않고 경고), 문서 전체 쪽 내용 5MB(넘으면 413),
  쪽당 글자 20,000자(413). pypdf는 내용 스트림 1MB를 해석하는 데 수 초가 걸려 이 상한들이 처리 시간 상한과 짝을 이룬다.
- **디스크에 쓰지 않는다.** Starlette의 기본 multipart 처리(`UploadFile`)는 1MB가 넘으면 임시 파일로
  내려 쓰므로 쓰지 않고, 요청 본문을 스트림으로 읽어 메모리에서만 파싱한다. 로그에도 본문·파일명을 남기지 않는다.

main.py 연결(PM): `from neumann.api.upload import router as upload_router; app.include_router(upload_router)`.
파이프라인에서 쓸 때: `parse_plan_upload(filename, data) -> str` (거부는 `UploadRejected` 예외, `.status_code`·`.message`).
같은 프로세스에서 돌며 상한·시간 예산은 같다. 신뢰할 수 없는 입력을 강제 종료까지 보장하려면 `extract_plan_isolated`.
"""

from __future__ import annotations

import codecs
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import zipfile
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.concurrency import run_in_threadpool

from neumann.models import normalize_text
from neumann.api.plan_limits import PlanLimitError, prepare_upload_text

PlanKind = Literal["txt", "md", "pdf", "docx"]

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
"""업로드 파일 상한(10MB). 넘으면 413."""
MULTIPART_OVERHEAD_BYTES = 64 * 1024
"""multipart 경계·헤더·작은 필드 몫. 요청 본문 전체 상한 = 파일 상한 + 이 값."""
MAX_PLAN_CHARS = 50_000
"""추출 본문 글자 수 상한(정리 뒤). 넘으면 413. 분석 입력 상한(E4-L2c 50,000자)과 같게 둔다."""
RAW_CHAR_ABORT = 4 * MAX_PLAN_CHARS
"""추출 중 누적 글자(정리 전)가 이 값을 넘으면 끝까지 읽지 않고 413. 공백·빈 줄 몫으로 4배 여유를 둔다."""
MAX_PDF_PAGES = 200
"""PDF 쪽수 상한. 넘으면 413(연구계획서는 보통 수십 쪽)."""
MAX_ZIP_UNCOMPRESSED = 20 * 1024 * 1024
"""zip(DOCX·HWPX 판별 포함) 압축 해제 합계 상한. zip 폭탄 방지."""
MAX_ZIP_ENTRIES = 1000
"""zip 항목 수 상한."""
MAX_ZIP_RATIO = 100
"""1MB가 넘는 항목의 압축비 상한(보통 DOCX XML은 10~30배)."""
def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        return min(max(float(os.environ.get(name, "") or default), lo), hi)
    except ValueError:
        return default


EXTRACT_TIMEOUT_S = _env_float("NEUMANN_UPLOAD_TIMEOUT_S", 10.0, 2.0, 120.0)
"""추출 처리 시간 상한(초, SEC-7에서 20 → 10). 넘으면 413. 격리 프로세스는 이 시간이 지나면 강제 종료한다."""
EXTRACT_MEMORY_MB = int(_env_float("NEUMANN_UPLOAD_MEMORY_MB", 512, 128, 8192))
"""격리 작업자 프로세스의 메모리(커밋) 상한(MB, SEC-7). 넘으면 MemoryError → 413."""
MAX_PLAN_LINES = 5_000
"""추출 본문 줄 수 상한(SEC-7, 분석 입력 상한과 같다). 넘으면 422."""
MAX_PDF_PAGE_CHARS = 20_000
"""PDF 한 쪽에서 나온 글자 상한(SEC-7). 넘으면 쪽 안에서 바로 멈추고 413."""
MAX_PDF_PAGE_STREAM = 1_000_000
"""PDF 한 쪽 내용 스트림(푼 크기) 상한(SEC-7). 넘는 쪽은 해석하지 않고 경고로 알린다(pypdf 해석이 1MB에 수 초)."""
MAX_PDF_CONTENT_TOTAL = 5_000_000
"""PDF 전체 쪽 내용 스트림 합계 상한(SEC-7). 넘으면 413(처리 시간 상한 안에 해석할 수 없는 양)."""
MAX_PDF_STREAM_DECODE = 8_000_000
"""pypdf가 스트림 하나를 풀 때의 크기 상한(SEC-7, 기본 75MB). 정상 PDF 실측 최대 약 0.4MB."""
MAX_CONCURRENT_EXTRACTIONS = 2
"""HTTP 경로의 동시 추출 수. 자리가 없으면 `EXTRACT_QUEUE_WAIT_S`만큼 기다리고 503."""
EXTRACT_QUEUE_WAIT_S = 5.0
MAX_REPLACEMENT_RATIO = 0.05
"""UTF-8·CP949 둘 다 실패했을 때, 깨진 글자 비율이 이보다 크면 텍스트 파일로 보지 않는다."""

HWP_MESSAGE = "HWP는 PDF나 DOCX로 저장해 올려 주세요"
TOO_LARGE_MESSAGE = "파일이 10MB를 넘습니다. 10MB 이하로 줄여 올려 주세요"
TOO_MANY_CHARS_MESSAGE = "계획서 글자 수가 상한(50,000자)을 넘습니다. 계획서 본문만 남겨 올려 주세요"
TOO_MANY_PAGES_MESSAGE = "PDF가 200쪽을 넘습니다. 계획서 부분만 PDF로 저장해 올려 주세요"
ZIP_BOMB_MESSAGE = "압축을 푼 크기가 상한(20MB)을 넘거나 비정상적으로 큽니다. 계획서 본문만 담아 다시 저장해 올려 주세요"
TIMEOUT_MESSAGE = f"파일 처리 시간이 상한({EXTRACT_TIMEOUT_S:g}초)을 넘었습니다. 쪽수를 줄이거나 다시 저장해 올려 주세요"
TOO_MANY_LINES_MESSAGE = f"줄이 너무 많습니다(최대 {MAX_PLAN_LINES:,}줄). 문단으로 합쳐 주세요."
PAGE_CHARS_MESSAGE = (f"PDF 한 쪽에서 나온 글자가 너무 많습니다(쪽당 최대 {MAX_PDF_PAGE_CHARS:,}자). "
                      "계획서 부분만 PDF로 저장해 올려 주세요")
PDF_COMPLEX_MESSAGE = ("PDF 내용(그림·도형 명령)이 너무 많아 처리 시간 안에 읽을 수 없습니다. "
                       "계획서 본문 부분만 PDF로 저장하거나 DOCX로 올려 주세요")
MEMORY_MESSAGE = "파일을 읽는 데 메모리가 너무 많이 듭니다. 쪽수를 줄이거나 다시 저장해 올려 주세요"
MEMORY_LIMIT_MESSAGE = "파일 처리의 메모리 제한을 준비하지 못했습니다. 잠시 뒤 다시 올려 주세요"
BUSY_MESSAGE = "업로드 처리 중인 요청이 많습니다. 잠시 뒤 다시 올려 주세요"
WORKER_FAILED_MESSAGE = "파일을 처리하지 못했습니다(손상된 파일일 수 있습니다)"
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


class _Budget:
    """추출 루프 안의 시간·글자 예산. 넘으면 바로 413으로 멈춘다(끝까지 읽지 않는다)."""

    def __init__(self, deadline_s: float | None) -> None:
        self.end = None if deadline_s is None else time.monotonic() + deadline_s
        self.chars = 0

    def spend(self, n_chars: int = 0) -> None:
        if self.end is not None and time.monotonic() > self.end:
            raise UploadRejected(413, TIMEOUT_MESSAGE)
        self.chars += n_chars
        if self.chars > RAW_CHAR_ABORT:
            raise UploadRejected(413, TOO_MANY_CHARS_MESSAGE)


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


def _check_zip_limits(infos: list[zipfile.ZipInfo]) -> None:
    """zip 폭탄 차단. 선언된 크기로 본다(zipfile은 선언 크기보다 더 풀지 않고, 어긋나면 CRC 오류를 낸다)."""
    if len(infos) > MAX_ZIP_ENTRIES:
        raise UploadRejected(413, ZIP_BOMB_MESSAGE)
    if sum(i.file_size for i in infos) > MAX_ZIP_UNCOMPRESSED:
        raise UploadRejected(413, ZIP_BOMB_MESSAGE)
    for i in infos:
        if i.file_size > 1024 * 1024 and i.file_size > MAX_ZIP_RATIO * max(i.compress_size, 1):
            raise UploadRejected(413, ZIP_BOMB_MESSAGE)


def _sniff_zip(data: bytes) -> Literal["docx", "hwpx", "zip", "binary"]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception:  # 손상 zip
        return "binary"
    with zf:
        infos = zf.infolist()
        _check_zip_limits(infos)  # 형식을 가리기 전에 막는다(UploadRejected는 그대로 올라간다)
        try:
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
        except Exception:  # 암호 zip(RuntimeError), 미지원 압축(NotImplementedError) 등
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


@contextmanager
def _pdf_limits():  # noqa: ANN202 - pypdf 설정 문맥
    """pypdf 스트림 해제 크기 상한(SEC-7). 제한 API가 없으면 보호 없이 PDF를 읽지 않는다."""
    with ExitStack() as stack:
        try:
            from pypdf import apply_configuration

            n = MAX_PDF_STREAM_DECODE
            # contextmanager는 진입할 때 설정을 검증한다. 생성·진입 실패를 모두 추출 전에 처리한다.
            stack.enter_context(apply_configuration(zlib_maximum_output_length=n, lzw_maximum_output_length=n,
                                                    run_length_maximum_output_length=n,
                                                    array_based_stream_maximum_output_length=n))
        except (ImportError, TypeError, ValueError):
            raise UploadRejected(503, "PDF 안전 제한을 준비하지 못했습니다. DOCX나 텍스트로 올려 주세요") from None
        yield


def _content_parts(page):  # noqa: ANN001, ANN202 - pypdf 객체
    obj = page.get("/Contents")
    if obj is None:
        return []
    obj = obj.get_object()
    return [p.get_object() for p in obj] if isinstance(obj, list) else [obj]


def _page_content_size(page) -> int:  # noqa: ANN001
    """쪽 내용 스트림의 푼 크기 합(해석 전에 잰다. 스트림 하나가 해제 상한을 넘으면 pypdf가 LimitReachedError)."""
    return sum(len(p.get_data()) for p in _content_parts(page) if hasattr(p, "get_data"))


def _drop_decoded(page) -> None:  # noqa: ANN001
    """읽지 않기로 한 쪽의 푼 스트림 캐시를 버린다(pypdf가 스트림 객체에 붙여 두는 사본, 최선 노력)."""
    try:
        for p in _content_parts(page):
            if getattr(p, "decoded_self", None) is not None:
                p.decoded_self = None
    except Exception:  # noqa: BLE001
        pass


def _page_text(page, budget: _Budget) -> str:  # noqa: ANN001
    """쪽 하나의 텍스트. 연산자 256개마다 시간 예산을 보고, 쪽 글자가 상한을 넘으면 쪽 안에서 바로 멈춘다(SEC-7)."""
    seen = {"chars": 0, "ops": 0}

    def on_text(text, *_):  # noqa: ANN001, ANN002, ANN202
        seen["chars"] += len(text or "")
        if seen["chars"] > MAX_PDF_PAGE_CHARS:
            raise UploadRejected(413, PAGE_CHARS_MESSAGE)

    def on_op(*_):  # noqa: ANN002, ANN202
        seen["ops"] += 1
        if not seen["ops"] & 255:
            budget.spend()

    text = page.extract_text(visitor_text=on_text, visitor_operand_before=on_op) or ""
    if len(text) > MAX_PDF_PAGE_CHARS:  # 방문자가 못 본 글자(양식 등)까지
        raise UploadRejected(413, PAGE_CHARS_MESSAGE)
    return text


def _extract_pdf(data: bytes, budget: _Budget) -> tuple[str, int, list[str]]:
    with _pdf_limits():
        return _extract_pdf_limited(data, budget)


def _extract_pdf_limited(data: bytes, budget: _Budget) -> tuple[str, int, list[str]]:
    from pypdf import PdfReader

    try:
        from pypdf.errors import LimitReachedError

        limit_errors: tuple[type[BaseException], ...] = (LimitReachedError,)
    except ImportError:  # 옛 pypdf
        limit_errors = ()

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
    except MemoryError:
        raise UploadRejected(413, MEMORY_MESSAGE) from None
    except Exception as exc:  # pypdf는 손상 파일에서 여러 종류의 예외를 낸다
        raise UploadRejected(422, "PDF를 읽을 수 없습니다(손상된 파일일 수 있습니다)") from exc
    if n_pages > MAX_PDF_PAGES:
        raise UploadRejected(413, TOO_MANY_PAGES_MESSAGE)

    warnings: list[str] = []
    texts: list[str] = []
    empty: list[int] = []
    failed: list[int] = []
    heavy: list[int] = []  # 내용 스트림이 쪽 상한을 넘어 해석하지 않은 쪽(SEC-7)
    content_total = 0
    for i in range(n_pages):
        budget.spend()
        page = None
        try:
            page = reader.pages[i]
            size = _page_content_size(page)  # 해석(느림) 전에 푼 크기만 잰다(빠름)
        except MemoryError:
            raise UploadRejected(413, MEMORY_MESSAGE) from None
        except limit_errors:
            heavy.append(i + 1)
            if page is not None:
                _drop_decoded(page)
            continue
        except Exception:
            failed.append(i + 1)
            continue
        if size > MAX_PDF_PAGE_STREAM:
            heavy.append(i + 1)
            _drop_decoded(page)
            continue
        content_total += size
        if content_total > MAX_PDF_CONTENT_TOTAL:
            raise UploadRejected(413, PDF_COMPLEX_MESSAGE)
        try:
            page_text = _page_text(page, budget)
        except UploadRejected:
            raise
        except MemoryError:
            raise UploadRejected(413, MEMORY_MESSAGE) from None
        except Exception:
            failed.append(i + 1)
            continue
        budget.spend(len(page_text))
        if page_text.strip():
            texts.append(page_text.strip("\r\n"))  # 쪽 경계에 빈 줄을 끼우지 않는다(문단이 쪽을 넘어가도 이어지게)
        else:
            empty.append(i + 1)
    if failed:
        warnings.append(f"텍스트 추출에 실패한 쪽: {_pages(failed)}")
    if heavy:
        warnings.append(f"그림·도형 명령이 너무 많아 읽지 않은 쪽: {_pages(heavy)} (쪽 내용 {MAX_PDF_PAGE_STREAM // 1_000_000}MB 상한)")
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


def _extract_docx(data: bytes, budget: _Budget) -> tuple[str, list[str]]:
    from docx import Document

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            _check_zip_limits(zf.infolist())  # _sniff_zip에서도 보지만, 이 함수만 불려도 막히게 한 번 더
        doc = Document(io.BytesIO(data))
        budget.spend()
        lines = []
        for line in _docx_lines(doc.element.body, doc):
            budget.spend(len(line) + 1)
            lines.append(line)
    except UploadRejected:
        raise
    except MemoryError:
        raise UploadRejected(413, MEMORY_MESSAGE) from None
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
    try:
        text = prepare_upload_text(text, collapse_blank=collapse_blank)
    except PlanLimitError as exc:
        raise UploadRejected(exc.status_code, exc.message) from None
    text = normalize_text(text).translate(_CONTROL_TO_NEWLINE)
    text = _CONTROL_RE.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    if collapse_blank:
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n")


def extract_plan(filename: str, data: bytes, *, deadline_s: float | None = EXTRACT_TIMEOUT_S) -> PlanExtract:
    """업로드 바이트에서 계획서 본문과 메타(쪽수·인코딩·경고)를 뽑는다. 받지 않으면 `UploadRejected`.

    같은 프로세스에서 돈다. `deadline_s`는 추출 루프(쪽·문단) 사이에서 확인하는 협조적 시간 예산이다.
    """
    budget = _Budget(deadline_s)
    name = _safe_filename(filename)
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(413, TOO_LARGE_MESSAGE)
    if not data:
        raise UploadRejected(422, "빈 파일입니다")
    kind, warnings = _detect_kind(name, data)
    pages: int | None = None
    encoding: str | None = None
    if kind == "pdf":
        raw, pages, more = _extract_pdf(data, budget)
    elif kind == "docx":
        raw, more = _extract_docx(data, budget)
    else:
        raw, encoding, more = _decode_text(data)  # 10MB 디코딩·정리는 1초 안쪽이라 글자 상한은 정리 뒤 한 번만 본다
        budget.spend()
    warnings.extend(more)
    if raw.count("\n") + raw.count("\r") > 20 * MAX_PLAN_LINES:  # 정리(줄 목록) 전에 값싸게: 줄바꿈 수백만 개 txt의 메모리
        raise UploadRejected(422, TOO_MANY_LINES_MESSAGE)
    text = _clean(raw, collapse_blank=kind in ("pdf", "docx"))
    if not text.strip():
        hint = " 스캔한 PDF라면 텍스트가 들어 있는 PDF나 DOCX로 올려 주세요" if kind == "pdf" else ""
        raise UploadRejected(422, "파일에서 텍스트를 찾지 못했습니다." + hint)
    if len(text) > MAX_PLAN_CHARS:
        raise UploadRejected(413, TOO_MANY_CHARS_MESSAGE)
    if text.count("\n") + 1 > MAX_PLAN_LINES:  # SEC-7: 분석 입구와 같은 줄 수 상한
        raise UploadRejected(422, TOO_MANY_LINES_MESSAGE)
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


# ── 격리 실행(HTTP 경로): 동시 상한 + 별도 프로세스 + 강제 종료 ─────────────────

_SRC_DIR = Path(__file__).resolve().parents[2]
_SECRET_ENV = re.compile(r"(?i)(KEY|SECRET|TOKEN|SALT|PASSWORD|PASSWD|CREDENTIAL)")
_EXTRACT_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_EXTRACTIONS)


def _worker_command() -> list[str]:
    """추출 작업자 실행 명령. `-I`(환경변수·사용자 site·현재 폴더 무시), `-B`(바이트코드 파일 안 씀)."""
    code = f"import sys; sys.path.insert(0, {str(_SRC_DIR)!r}); from neumann.api.upload import _worker_main; _worker_main()"
    return [sys.executable, "-I", "-B", "-c", code]


def _worker_env() -> dict[str, str]:
    """작업자 환경변수. 이름에 KEY·SECRET·TOKEN 등이 든 값(API 키 포함)은 넘기지 않는다."""
    return {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}


def _deny_disk_writes() -> None:
    """이 프로세스에서 쓰기 모드 파일 열기를 막는다(감사 훅은 한 번 걸면 풀 수 없다). 추출 작업자 전용."""
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def hook(event: str, args: tuple) -> None:
        if event != "open":
            return
        path, mode, flags = args
        if path is None or isinstance(path, int):  # 이미 열린 표준 입출력 등
            return
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & write_flags):
            raise PermissionError("업로드 추출 작업자는 디스크에 쓰지 않는다")

    sys.addaudithook(hook)


def _limit_worker_memory(max_mb: int) -> bool:
    """이 프로세스의 메모리(커밋) 상한을 건다(SEC-7). 걸었으면 True. 추출 작업자 전용.

    Windows: 새 작업 개체(Job Object)에 자기 자신을 넣고 프로세스 메모리 상한 + 프로세스 수 1(자식 금지).
    POSIX: RLIMIT_AS. 넘으면 파이썬은 MemoryError를 낸다(작업자는 413으로 답한다).
    """
    limit = int(max_mb) * 1024 * 1024
    if os.name != "nt":
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            return True
        except (ImportError, ValueError, OSError):
            return False
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = 0x100 | 0x8  # JOB_OBJECT_LIMIT_PROCESS_MEMORY | ACTIVE_PROCESS
    info.BasicLimitInformation.ActiveProcessLimit = 1
    info.ProcessMemoryLimit = limit
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # ExtendedLimitInformation
        k32.CloseHandle(job)
        return False
    if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
        k32.CloseHandle(job)
        return False
    return True  # 작업 개체 핸들은 프로세스가 끝날 때 닫힌다.


def _worker_main() -> None:
    """작업자 진입점. 표준 입력: JSON 머리 한 줄 + 파일 바이트. 표준 출력: JSON 결과 하나."""
    _deny_disk_writes()
    try:
        header = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
        if not _limit_worker_memory(int(header.get("memory_mb", EXTRACT_MEMORY_MB))):
            raise UploadRejected(503, MEMORY_LIMIT_MESSAGE)
        data = sys.stdin.buffer.read(MAX_UPLOAD_BYTES + 1)
        result = extract_plan(header["filename"], data, deadline_s=header.get("deadline_s"))
        out: dict = {"ok": True, "result": asdict(result)}
    except UploadRejected as exc:
        out = {"ok": False, "status": exc.status_code, "message": exc.message}
    except MemoryError:
        out = {"ok": False, "status": 413, "message": MEMORY_MESSAGE}
    except Exception:  # 내부 예외 문구는 내보내지 않는다(SEC-1 S-04)
        out = {"ok": False, "status": 422, "message": WORKER_FAILED_MESSAGE}
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()


def _run_worker(filename: str, data: bytes, timeout_s: float) -> PlanExtract:
    header = json.dumps({"filename": filename, "deadline_s": timeout_s,
                         "memory_mb": EXTRACT_MEMORY_MB}).encode("utf-8") + b"\n"
    try:
        proc = subprocess.run(
            _worker_command(),
            input=header + data,
            capture_output=True,
            timeout=timeout_s,
            env=_worker_env(),
            cwd=str(_SRC_DIR),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:  # subprocess.run이 작업자를 강제 종료한 뒤다
        raise UploadRejected(413, TIMEOUT_MESSAGE) from None
    try:
        out = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise UploadRejected(422, WORKER_FAILED_MESSAGE) from None
    if not out.get("ok"):
        raise UploadRejected(int(out.get("status", 422)), str(out.get("message", WORKER_FAILED_MESSAGE)))
    fields = out["result"]
    fields["warnings"] = tuple(fields.get("warnings", ()))
    return PlanExtract(**fields)


def extract_plan_isolated(filename: str, data: bytes, *, timeout_s: float = EXTRACT_TIMEOUT_S) -> PlanExtract:
    """HTTP 경로용 `extract_plan`. 동시 처리 상한(자리 없으면 503), pdf·docx는 별도 프로세스에서 돌려
    `timeout_s`가 지나면 강제 종료(413). 형식 판별·zip 상한·HWP 거부는 가벼워서 프로세스를 띄우기 전에 한다."""
    if not _EXTRACT_SLOTS.acquire(timeout=EXTRACT_QUEUE_WAIT_S):
        raise UploadRejected(503, BUSY_MESSAGE)
    try:
        name = _safe_filename(filename)
        if not data or len(data) > MAX_UPLOAD_BYTES:
            return extract_plan(name, data, deadline_s=timeout_s)  # 빈 파일 422·크기 413
        kind, _ = _detect_kind(name, data)
        if kind in ("pdf", "docx"):
            return _run_worker(name, data, timeout_s)
        return extract_plan(name, data, deadline_s=timeout_s)  # txt·md: 디코딩뿐이라 같은 프로세스
    finally:
        _EXTRACT_SLOTS.release()


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
    received = 0
    try:
        # 경계가 너무 길면(python-multipart 상한 256자) 생성자가 FormParserError를 낸다 → 아래에서 400
        parser = MultipartParser(boundary, collector.callbacks())
        async for chunk in request.stream():
            received += len(chunk)
            if received > limit:
                raise UploadRejected(413, TOO_LARGE_MESSAGE)
            parser.write(chunk)
        parser.finalize()
    except (FormParserError, ValueError) as exc:
        raise UploadRejected(400, "multipart 본문을 해석할 수 없습니다") from exc
    if collector.filename is None:
        raise UploadRejected(422, "file 필드에 계획서 파일이 없습니다")
    return collector.filename, bytes(collector.data)


router = APIRouter(tags=["upload"])

_ERROR_RESPONSES = {
    400: {"description": "multipart 형식 오류, 파일 여러 개"},
    413: {"description": "상한 초과: 파일 10MB, 글자 50,000자, PDF 200쪽, 압축 해제 20MB, 처리 시간 10초(SEC-7), 줄 5,000줄(422)"},
    415: {"description": f"HWP·HWPX(\"{HWP_MESSAGE}\"), 그 밖의 미지원 형식"},
    422: {"description": "빈 파일, 손상·암호 PDF, 텍스트 없음"},
    503: {"description": BUSY_MESSAGE},
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
        result = await run_in_threadpool(extract_plan_isolated, filename, data)
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
    "EXTRACT_TIMEOUT_S",
    "HWP_MESSAGE",
    "MAX_PDF_PAGES",
    "MAX_PLAN_CHARS",
    "MAX_UPLOAD_BYTES",
    "MAX_ZIP_UNCOMPRESSED",
    "PlanExtract",
    "PlanUploadResponse",
    "UploadRejected",
    "extract_plan",
    "extract_plan_isolated",
    "parse_plan_upload",
    "router",
]
