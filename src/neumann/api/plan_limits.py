"""Cheap public-input guards; never normalize or redact input (PERF-pk).

The 200,000-character pre-NFC budget permits up to four input code points per
character of a 50,000-character public plan. It bounds Windows NFC expansion.
Uploads may discard ASCII end-of-line padding which their existing cleaner
already discards. Other input, including quote offsets, is returned unchanged.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import HTTPException

MAX_PRE_NFC_CHARS = 200_000
MAX_PLAN_LINES = 5_000
# Same decoded-raw allowance as the existing 10 MiB upload envelope. Since
# UTF-8 uses at most four bytes/code point, these caps also bound encoding size
# without allocating an encoded copy (800,000 B pre-NFC; 40 MiB upload raw).
MAX_RAW_UPLOAD_CHARS = 10 * 1024 * 1024
_BREAK = re.compile(r"\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]")
_UPLOAD_BREAK = re.compile(r"\r\n|[\r\n]")


class PlanLimitError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.message = message
        super().__init__(status_code, detail={"status": "error", "error_code": code, "message": message})


def check_line_budget(text: str, max_lines: int = MAX_PLAN_LINES) -> None:
    # Include the last empty line, as PlanDocument does. Also count splitlines'
    # Unicode separators, conservatively, before upload translates controls.
    lines = 1
    for _ in _BREAK.finditer(text):
        lines += 1
        if lines > max_lines:
            raise PlanLimitError(422, "too_many_lines",
                                 f"줄이 너무 많습니다(최대 {max_lines:,}줄). 문단으로 합쳐 주세요.")


def check_plan_text(text: str, *, max_lines: int = MAX_PLAN_LINES) -> str:
    if len(text) > MAX_PRE_NFC_CHARS:
        raise PlanLimitError(413, "plan_pre_nfc_too_large",
                             f"정규화 전 계획서가 너무 큽니다(최대 {MAX_PRE_NFC_CHARS:,}자). 계획서 본문만 남겨 주세요.")
    check_line_budget(text, max_lines)
    return text


def prepare_upload_text(text: str, *, collapse_blank: bool) -> str:
    # Bound list allocation first. This matches SEC-7's existing 20x raw-line
    # allowance and preserves PDF/DOCX blank-line collapse and horizontal padding.
    if len(text) > MAX_RAW_UPLOAD_CHARS:
        raise PlanLimitError(413, "plan_raw_too_large", "추출한 계획서 원문이 너무 큽니다. 본문만 남겨 주세요.")
    check_line_budget(text, 20 * MAX_PLAN_LINES)
    # Do not allocate a split list or an oversized content slice. Strip only the
    # ASCII padding already removed by upload._clean, keeping controls until NFC
    # (removing them first could change composition and citation offsets).
    rows: list[str] = []
    chars = 0
    start = 0
    for match in _UPLOAD_BREAK.finditer(text):
        end = match.start()
        while end > start and text[end - 1] in " \t":
            end -= 1
        chars += end - start + 1
        if chars > MAX_PRE_NFC_CHARS:
            raise PlanLimitError(413, "plan_pre_nfc_too_large", "정규화 전 계획서가 너무 큽니다. 본문만 남겨 주세요.")
        rows.append(text[start:end])
        start = match.end()
    end = len(text)
    while end > start and text[end - 1] in " \t":
        end -= 1
    chars += end - start
    if chars > MAX_PRE_NFC_CHARS:
        raise PlanLimitError(413, "plan_pre_nfc_too_large", "정규화 전 계획서가 너무 큽니다. 본문만 남겨 주세요.")
    rows.append(text[start:end])
    text = "\n".join(rows)
    if collapse_blank:
        text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip("\n")
    return check_plan_text(text)


def check_embedded_plan(lines: Sequence[Any], *, max_lines: int = MAX_PLAN_LINES) -> None:
    if len(lines) > max_lines:
        raise PlanLimitError(422, "too_many_lines",
                             f"줄이 너무 많습니다(최대 {max_lines:,}줄). 문단으로 합쳐 주세요.")
    chars = max(len(lines) - 1, 0)  # inserted LF separators, without an extra last LF
    physical_lines = len(lines)
    for line in lines:
        text = line.get("text") if isinstance(line, Mapping) else getattr(line, "text", None)
        if isinstance(text, str):
            check_plan_text(text, max_lines=max_lines)
            chars += len(text)
            if chars > MAX_PRE_NFC_CHARS:
                raise PlanLimitError(413, "plan_pre_nfc_too_large",
                                     "계획서 본문이 너무 큽니다. 계획서 부분만 남겨 주세요.")
            physical_lines += sum(1 for _ in _BREAK.finditer(text))
            if physical_lines > max_lines:
                raise PlanLimitError(422, "too_many_lines",
                                     f"줄이 너무 많습니다(최대 {max_lines:,}줄). 문단으로 합쳐 주세요.")


def check_payload_plan(payload: Any, *, max_lines: int = MAX_PLAN_LINES) -> None:
    """Gate raw JSON before nested Pydantic models; leave type errors to schemas."""
    if not isinstance(payload, Mapping):
        return
    text = payload.get("plan_text")
    if isinstance(text, str):
        check_plan_text(text, max_lines=max_lines)
    result = payload.get("result", payload)
    plan = result.get("plan") if isinstance(result, Mapping) else None
    lines = plan.get("lines") if isinstance(plan, Mapping) else None
    if isinstance(lines, list):
        check_embedded_plan(lines, max_lines=max_lines)
