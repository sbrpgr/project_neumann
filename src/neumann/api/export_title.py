"""사용자가 정하는 내보내기 제목(서명 대상 아님)과 안전한 다운로드 이름."""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from neumann.models import redact_pii

DEFAULT_TITLE = "수정된 연구계획서"
HISTORY_SUFFIX = " — 수정 이력과 근거"
MAX_TITLE_CHARS = 200
MAX_FILENAME_TITLE_CHARS = 60


def display_title(value: Any) -> str:
    if not isinstance(value, str):
        return DEFAULT_TITLE
    # Keep a single display line, mask personal information, remove controls/bidi.
    value = " ".join(redact_pii(value).split())
    value = "".join(c for c in value if not unicodedata.category(c).startswith("C"))
    return value[:MAX_TITLE_CHARS].strip() or DEFAULT_TITLE


def plan_title(plan: Mapping[str, Any] | None, override: str | None = None) -> str:
    if override is not None:
        return display_title(override)
    if isinstance(plan, Mapping):
        if isinstance(plan.get("title"), str):
            return display_title(plan["title"])
        # Compatibility with already issued assemblies: title used to exist only here.
        md = plan.get("markdown")
        history = md.get("history") if isinstance(md, Mapping) else None
        if isinstance(history, str):
            head = history.split("\n", 1)[0]
            if head.startswith("# ") and head.endswith(HISTORY_SUFFIX):
                return display_title(html.unescape(head[2:-len(HISTORY_SUFFIX)]))
    return DEFAULT_TITLE


def markdown_title(value: str) -> str:
    return html.escape(display_title(value), quote=False)


def filename_title(value: str) -> str:
    # A whitelist excludes separators, controls, Windows punctuation and dot paths.
    safe = "".join(c for c in display_title(value) if c.isalnum() or c in " _-")
    return "_".join(safe.split())[:MAX_FILENAME_TITLE_CHARS].strip("_-") or "plan"


def content_disposition(prefix: str, ident: str, title: str, extension: str) -> str:
    short = re.sub(r"[^0-9A-Za-z_-]", "", ident)[:12] or "plan"
    fallback = f"{prefix}_{short}.{extension}"
    filename = f"{prefix}_{filename_title(title)}_{short}.{extension}"
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}'
