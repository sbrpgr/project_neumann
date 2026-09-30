"""HWPX(한글 개방형 문서, OWPML) 본문 추출(E4-L2h). `upload.extract_plan`이 부른다.

HTTP 경로에서는 pdf·docx와 같은 **격리 작업자 프로세스(기본 10초·512MB 상한, 넘으면 강제 종료)** 안에서 돈다
(`upload.extract_plan_isolated`). 새 패키지 없이 표준 라이브러리 zipfile과 lxml만 쓴다.
옛 한글 바이너리(.hwp·.hwt)는 읽지 않는다(대표 지시, upload가 415로 안내한다).

- 구조: zip(`mimetype` = application/hwp+zip) 안의 `Contents/content.hpf`(OPF 목록)가 정한 순서(spine)로
  `Contents/section*.xml`을 읽는다. 목록이 없거나 깨졌으면 파일 이름의 번호순.
- 추출: 문단(`hp:p`)마다 한 줄. `hp:t` 안 `hp:tab`은 탭, `hp:lineBreak`는 줄바꿈, 묶음·고정폭 빈칸은 공백,
  `hp:hyphen`은 `-`. 표는 DOCX와 같게 행마다 한 줄(셀은 ` | `, 병합된 칸은 HWPX에 셀이 없어 되풀이하지 않는다).
  각주·미주·글상자·그림 캡션 문단은 그 문단 바로 뒤에. 머리말·꼬리말·숨은 설명·개체 설명은 읽지 않는다
  (DOCX도 머리글·바닥글은 읽지 않는다).
- 한도(적대 입력): zip은 DOCX와 같은 `upload._check_zip_limits`(항목 1,000개·압축 해제 합계 20MB·1MB 넘는 항목
  압축비 100배). XML은 lxml 안전 파서(엔티티 해석 끔·네트워크 끔·DTD 읽지 않음·huge_tree 끔 → libxml2 깊이 상한
  256), DTD·ENTITY 선언이 있으면 파싱하지 않고 422. 메타데이터·숨은 요소를 포함한 XML 요소 50만 개(넘으면 413),
  manifest 손상·중복 항목은 422, manifest 1MB 초과는 413. 표·글상자 중첩 32단계(넘는 부분은
  건너뛰고 경고), 구역 256개. 시간·글자 예산은 upload의 `_Budget`을 같이 쓴다.
- 암호 문서: zip 항목의 암호 플래그나 `META-INF/manifest.xml`의 암호화 정보(`encryption-data`)가 있으면 422
  "암호가 걸린 문서는 처리할 수 없습니다".
- 본문 구역을 하나도 못 읽으면 `Preview/PrvText.txt`(미리보기, 문서 앞부분 일부)로 물러나고 경고를 붙인다.
"""

from __future__ import annotations

import codecs
import io
import re
import zipfile
import zlib

from lxml import etree

from neumann.api.upload import UploadRejected, _Budget, _check_zip_limits, hwpx_parts

XML_MAX_ELEMENTS = 500_000
"""읽는 메타데이터·구역 XML의 모든 요소 합계 상한(숨은 요소 포함). 넘으면 413."""
MAX_NEST = 32
"""표·글상자·각주 중첩 깊이 상한. 넘는 부분은 건너뛰고 경고한다(재귀 깊이·중복 결합 비용 제한)."""
MAX_SECTIONS = 256
"""구역(section) 수 상한. 넘으면 413."""
META_MAX_BYTES = 1024 * 1024
"""content.hpf·manifest.xml 읽기 상한."""
PRVTEXT_MAX_BYTES = 64 * 1024
"""미리보기 텍스트 읽기 상한(보통 2~3KB)."""

HWPX_CORRUPT_MESSAGE = "HWPX를 읽을 수 없습니다(손상된 파일일 수 있습니다). 한글에서 다시 저장하거나 PDF로 저장해 올려 주세요"
HWPX_ENCRYPTED_MESSAGE = "암호가 걸린 문서는 처리할 수 없습니다. 한글에서 암호를 풀고 다시 저장해 올려 주세요"
HWPX_DTD_MESSAGE = "문서 XML에 허용하지 않는 선언(DTD·ENTITY)이 있어 읽지 않았습니다. 한글에서 다시 저장해 올려 주세요"
HWPX_TOO_COMPLEX_MESSAGE = "문서 구조가 비정상적으로 큽니다(구역·XML 요소 수 상한). 계획서 본문만 남겨 다시 저장해 올려 주세요"
PRVTEXT_WARNING = (
    "본문 구역을 읽지 못해 미리보기 텍스트(문서 앞부분 일부)만 가져왔습니다. "
    "전체를 분석하려면 한글에서 다시 저장하거나 PDF로 올려 주세요"
)
DEEP_WARNING = f"{MAX_NEST}단계보다 깊게 중첩된 표·글상자는 건너뛰었습니다"

_SECTION_RE = re.compile(r"Contents/section(\d{1,6})\.xml", re.IGNORECASE)
_ZIP_ERRORS = (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError, OSError, ValueError)
_DTD_MARKERS = tuple(
    m.encode(enc) for m in ("<!DOCTYPE", "<!ENTITY")
    for enc in ("ascii", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")
)

# 요소 이름(네임스페이스를 뗀 소문자). OWPML 2011·2016 네임스페이스를 가리지 않는다.
_PARA, _TEXT, _TABLE, _ROW, _CELL, _SUBLIST = "p", "t", "tbl", "tr", "tc", "sublist"
_SKIP = frozenset({"header", "footer", "hiddencomment", "shapecomment", "linesegarray", "secpr"})
_INLINE = {"tab": "\t", "linebreak": "\n", "nbspace": " ", "fwspace": " ", "hyphen": "-"}


class _Ctx:
    """구역 XML을 걷는 동안의 예산(요소 수·시간·글자)과 경고 표시."""

    __slots__ = ("budget", "elements", "walked", "deep")

    def __init__(self, budget: _Budget) -> None:
        self.budget = budget
        self.elements = 0
        self.walked = 0
        self.deep = False

    def tick(self) -> None:
        self.elements += 1
        if self.elements > XML_MAX_ELEMENTS:
            raise UploadRejected(413, HWPX_TOO_COMPLEX_MESSAGE)
        if not self.elements & 0x3FF:
            self.budget.spend()

    def step(self) -> None:
        """파싱에서 이미 센 트리를 걷는 동안에는 시간 예산만 검사한다."""
        self.walked += 1
        if not self.walked & 0x3FF:
            self.budget.spend()


def _local(tag: object) -> str | None:
    """`{ns}name` → `name`(소문자). 주석·처리 지시·엔티티 노드는 None."""
    return tag.rpartition("}")[2].lower() if isinstance(tag, str) else None


def _parse_xml(raw: bytes, ctx: _Ctx):  # noqa: ANN202 - lxml 요소 또는 None
    """안전 파서로 읽는다. 문법 오류면 None, DTD·ENTITY 선언이 있으면 파싱 전에 422."""
    if any(m in raw for m in _DTD_MARKERS):
        raise UploadRejected(422, HWPX_DTD_MESSAGE)
    # libxml2의 feed 파서는 UTF-32LE 자동 판별을 놓치는 경우가 있다.
    # BOM 또는 XML 첫 '<'의 바이트 순서만으로 endian을 지정한다.
    encoding = None
    if raw.startswith((codecs.BOM_UTF32_LE, b"<\x00\x00\x00")):
        encoding = "UTF-32LE"
    elif raw.startswith((codecs.BOM_UTF32_BE, b"\x00\x00\x00<")):
        encoding = "UTF-32BE"
    start_offset = 4 if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)) else 0
    parser = etree.XMLPullParser(
        events=("start",),
        encoding=encoding,
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )
    try:
        # 건너뛰는 머리말·숨은 설명·inline 하위 요소도 센다. 작은 청크마다 확인해
        # 전체 트리를 만들기 전에 요소 상한·시간 예산으로 중단한다.
        for start in range(start_offset, len(raw), 64 * 1024):
            ctx.budget.spend()
            parser.feed(raw[start : start + 64 * 1024])
            for _event, _element in parser.read_events():
                ctx.tick()
        root = parser.close()
    except (etree.LxmlError, ValueError):
        return None
    if root is None:
        return None
    info = root.getroottree().docinfo
    if info.doctype or info.internalDTD is not None:  # 위 바이트 검사를 피한 인코딩이어도 막는다
        raise UploadRejected(422, HWPX_DTD_MESSAGE)
    return root


# ── 본문 걷기 ────────────────────────────────────────────────────────────────


def _text(t, ctx: _Ctx) -> str:  # noqa: ANN001
    """`hp:t` 한 개의 글자. 자식 요소(탭·줄바꿈 등)는 기호로 바꾸고 꼬리 글자를 잇는다."""
    parts = [t.text or ""]
    for child in t:
        name = _local(child.tag)
        if name is not None:
            ctx.step()
            parts.append(_INLINE.get(name, ""))
        parts.append(child.tail or "")
    return "".join(parts)


def _blocks(container, out: list[str], ctx: _Ctx, depth: int) -> None:  # noqa: ANN001
    """container 아래 문단·표를 문서 순서대로 줄로 낸다. 다른 문단 안에 든 것은 그 문단이 처리한다."""
    if depth > MAX_NEST:
        ctx.deep = True
        return
    stack = [iter(container)]
    while stack:
        el = next(stack[-1], None)
        if el is None:
            stack.pop()
            continue
        name = _local(el.tag)
        if name is None:
            continue
        ctx.step()
        if name == _PARA:
            _paragraph(el, out, ctx, depth)
        elif name == _TABLE:
            _table(el, out, ctx, depth + 1)
        elif name not in _SKIP:
            stack.append(iter(el))


def _paragraph(p, out: list[str], ctx: _Ctx, depth: int) -> None:  # noqa: ANN001
    """문단 한 줄(`hp:t`만 모은다). 문단 안 표·하위 목록(각주·글상자 등)은 그 줄 뒤에 이어서 낸다."""
    parts: list[str] = []
    nested: list[tuple[str, object]] = []
    stack = [iter(p)]
    while stack:
        el = next(stack[-1], None)
        if el is None:
            stack.pop()
            continue
        name = _local(el.tag)
        if name is None:
            continue
        ctx.step()
        if name == _TEXT:
            parts.append(_text(el, ctx))
        elif name in (_TABLE, _SUBLIST, _PARA):
            nested.append((name, el))
        elif name not in _SKIP:
            stack.append(iter(el))
    line = "".join(parts)
    ctx.budget.spend(len(line) + 1)
    if line or not nested:  # 표만 싣는 빈 문단(한글은 표를 문단 안에 둔다)은 빈 줄을 만들지 않는다
        out.append(line)
    for name, el in nested:
        if name == _TABLE:
            _table(el, out, ctx, depth + 1)
        elif name == _PARA:
            if depth + 1 > MAX_NEST:
                ctx.deep = True
            else:
                _paragraph(el, out, ctx, depth + 1)
        else:
            _blocks(el, out, ctx, depth + 1)


def _table(tbl, out: list[str], ctx: _Ctx, depth: int) -> None:  # noqa: ANN001
    """표: 행(`hp:tr`)마다 한 줄, 셀(`hp:tc`) 글자는 ` | `로 잇는다. 셀 안 여러 문단·중첩 표는 공백으로 잇는다."""
    if depth > MAX_NEST:
        ctx.deep = True
        return
    for child in tbl:
        name = _local(child.tag)
        if name is None:
            continue
        ctx.step()
        if name == _ROW:
            cells = []
            for tc in child:
                if _local(tc.tag) != _CELL:
                    continue
                ctx.step()
                lines: list[str] = []
                _blocks(tc, lines, ctx, depth + 1)
                cell = " ".join(s for line in lines for s in (x.strip() for x in line.split("\n")) if s)
                if cell:
                    cells.append(cell)
            if cells:
                out.append(" | ".join(cells))
        elif name not in _SKIP:  # 표 캡션 등 표 안의 다른 문단
            _blocks(child, out, ctx, depth + 1)


# ── zip 꾸러미 ───────────────────────────────────────────────────────────────


def _reject_encrypted(zf: zipfile.ZipFile, infos: list[zipfile.ZipInfo], ctx: _Ctx) -> None:
    if any(i.flag_bits & 0x1 for i in infos):  # zip 항목 암호
        raise UploadRejected(422, HWPX_ENCRYPTED_MESSAGE)
    manifest = next((i for i in infos if i.filename.lower() == "meta-inf/manifest.xml"), None)
    if manifest is None:
        return
    if manifest.file_size > META_MAX_BYTES:
        raise UploadRejected(413, HWPX_TOO_COMPLEX_MESSAGE)
    try:
        raw = zf.read(manifest)
    except _ZIP_ERRORS as exc:
        raise UploadRejected(422, HWPX_CORRUPT_MESSAGE) from exc
    root = _parse_xml(raw, ctx)
    if root is None:
        raise UploadRejected(422, HWPX_CORRUPT_MESSAGE)
    if any(_local(el.tag) == "encryption-data" for el in root.iter()):
        # XML로 읽어 UTF-16·UTF-32 manifest도 같은 암호·DTD 검사를 거친다.
        raise UploadRejected(422, HWPX_ENCRYPTED_MESSAGE)


def _section_order(zf: zipfile.ZipFile, infos: list[zipfile.ZipInfo], ctx: _Ctx) -> list[zipfile.ZipInfo]:
    """content.hpf의 spine 순서. 목록이 없거나 구역을 하나도 못 찾으면 파일 이름 번호순."""
    by_name = {i.filename: i for i in infos}
    order: list[str] = []
    hpf = by_name.get("Contents/content.hpf")
    if hpf is not None and hpf.file_size <= META_MAX_BYTES:
        try:
            root = _parse_xml(zf.read(hpf), ctx)
        except _ZIP_ERRORS:
            root = None
        if root is not None:
            items: dict[str, str] = {}
            spine: list[str] = []
            for el in root.iter():
                name = _local(el.tag)
                if name == "item":
                    items.setdefault(el.get("id") or "", el.get("href") or "")
                elif name == "itemref":
                    spine.append(el.get("idref") or "")
            for idref in spine[:MAX_SECTIONS * 4]:
                href = items.get(idref, "").replace("\\", "/").lstrip("/")
                href = href[2:] if href.startswith("./") else href
                for cand in (href, "Contents/" + href):
                    if _SECTION_RE.fullmatch(cand) and cand in by_name and cand not in order:
                        order.append(cand)
                        break
    if not order:
        numbered = sorted((int(m.group(1)), i.filename) for i in infos if (m := _SECTION_RE.fullmatch(i.filename)))
        order = [name for _, name in numbered]
    return [by_name[n] for n in order]


def _prvtext(zf: zipfile.ZipFile, infos: list[zipfile.ZipInfo]) -> str:
    info = next((i for i in infos if i.filename.lower() == "preview/prvtext.txt"), None)
    if info is None:
        return ""
    try:
        with zf.open(info) as fh:
            raw = fh.read(PRVTEXT_MAX_BYTES)
    except _ZIP_ERRORS:
        return ""
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16", "replace")
    return raw.decode("utf-8", "replace").removeprefix("﻿")


def _extract(data: bytes, budget: _Budget) -> tuple[str, list[str]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except _ZIP_ERRORS as exc:
        raise UploadRejected(422, HWPX_CORRUPT_MESSAGE) from exc
    with zf:
        infos = zf.infolist()
        # upload._sniff_zip에서도 보지만, 이 함수만 불려도 막히게 한 번 더. 합계·압축비는 실제로 푸는 항목만
        _check_zip_limits(infos, hwpx_parts(infos))
        parts = hwpx_parts(infos)
        if len({i.filename.lower() for i in parts}) != len(parts):
            # 이름으로 읽는 메타데이터와 ZipInfo로 읽는 본문이 서로 다른 항목을
            # 고르지 않게, 실제로 읽는 항목의 중복 이름은 손상 파일로 거부한다.
            raise UploadRejected(422, HWPX_CORRUPT_MESSAGE)
        ctx = _Ctx(budget)
        _reject_encrypted(zf, infos, ctx)
        sections = _section_order(zf, infos, ctx)
        if len(sections) > MAX_SECTIONS:
            raise UploadRejected(413, HWPX_TOO_COMPLEX_MESSAGE)
        lines: list[str] = []
        failed = 0
        for info in sections:
            budget.spend()
            if info.flag_bits & 0x1:
                raise UploadRejected(422, HWPX_ENCRYPTED_MESSAGE)
            try:
                raw = zf.read(info)  # 선언 크기(합계 20MB 안)보다 더 풀지 않는다
            except _ZIP_ERRORS:
                failed += 1
                continue
            root = _parse_xml(raw, ctx)
            if root is None:
                failed += 1
                continue
            _blocks(root, lines, ctx, 0)
        text = "\n".join(lines)
        if not text.strip():
            preview = _prvtext(zf, infos)
            if preview.strip():
                return preview, [PRVTEXT_WARNING]
            if failed or not sections:
                raise UploadRejected(422, HWPX_CORRUPT_MESSAGE)
            return "", []
    warnings: list[str] = []
    if failed:
        warnings.append(f"읽지 못한 구역(section) {failed}개를 건너뛰었습니다(손상된 부분일 수 있습니다)")
    if ctx.deep:
        warnings.append(DEEP_WARNING)
    return text, warnings


def extract_hwpx(data: bytes, budget: _Budget) -> tuple[str, list[str]]:
    """HWPX 바이트 → (본문, 경고). 받지 않으면 `UploadRejected`(413 상한·422 손상·암호·DTD)."""
    try:
        return _extract(data, budget)
    except UploadRejected:
        raise
    except Exception as exc:  # 방어선: 위에서 못 잡은 예외도 손상 파일 422로(내부 문구는 내보내지 않는다)
        raise UploadRejected(422, HWPX_CORRUPT_MESSAGE) from exc


__all__ = [
    "HWPX_CORRUPT_MESSAGE",
    "HWPX_DTD_MESSAGE",
    "HWPX_ENCRYPTED_MESSAGE",
    "HWPX_TOO_COMPLEX_MESSAGE",
    "MAX_NEST",
    "PRVTEXT_WARNING",
    "XML_MAX_ELEMENTS",
    "extract_hwpx",
]
