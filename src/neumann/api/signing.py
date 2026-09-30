"""분석 결과 서버 서명(E4-L2f F1). 서버가 만든 결과인지 내보내기 때 확인한다.

    from neumann.api.signing import sign_result, verify_result
    sig = sign_result(result_json)          # 화면 응답(view·jobs)에 실어 보낸다
    ok = verify_result(result_json, sig)    # /premortem/package가 되돌려 받은 결과를 확인한다

- 서명: HMAC-SHA256(키, "neumann-result-v1\\n" + 정규화 JSON). 문자열 형식은 ``v1.<64 hex>``.
- 정규화: ``PremortemResult``로 검증한 뒤 JSON으로 되돌리고(계약 필드만), 정수로 떨어지는 실수는 정수로 바꾸고(브라우저
  JSON 왕복에서 ``1.0``이 ``1``이 된다), 키를 정렬한 압축 JSON(UTF-8). 같은 값이면 서명이 같다.
- 키: 프로세스 환경변수 ``NEUMANN_RESULT_HMAC_KEY``(32자 이상 무작위 권장). 없으면 모듈을 처음 읽을 때(서버 기동)
  무작위 32바이트를 만든다. 16바이트보다 짧으면 쓰지 않고 무작위 키로 바꾸며 경고 로그를 한 줄 남긴다(키 값·길이는 적지
  않는다). 무작위 키면 재기동 뒤 옛 서명이 모두 무효가 된다(내보내기는 "client_submitted_unverified"로 정직하게 표시).
- 키 값은 로그·응답·/health 어디에도 내보내지 않는다. 키 설정 여부도 응답·/health에 싣지 않는다.
- 확인(R1): 서명 문자열이 ASCII·접두 ``v1.``·소문자 hex 64자인지 먼저 보고, 비교는 bytes로 한다. 형식이 틀리면 False
  (예외 없음 — 비ASCII·전각 숫자도 500이 아니라 "확인 안 됨").
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
from collections.abc import Mapping
from typing import Any

KEY_ENV = "NEUMANN_RESULT_HMAC_KEY"
SIG_VERSION = "v1"
MIN_KEY_BYTES = 16
_DOMAIN = b"neumann-result-v1\n"
_SIG_RE = re.compile(r"v1\.[0-9a-f]{64}", re.ASCII)

log = logging.getLogger(__name__)


def _load_key() -> bytes:
    raw = os.environ.get(KEY_ENV, "")
    if not raw.strip():
        return secrets.token_bytes(32)
    key = raw.encode("utf-8")
    if len(key) < MIN_KEY_BYTES:
        log.warning("결과 서명 키 환경변수가 %d바이트보다 짧아 쓰지 않고 무작위 키를 쓴다(재기동하면 옛 서명 무효)",
                    MIN_KEY_BYTES)
        return secrets.token_bytes(32)
    return key


_KEY: bytes = _load_key()


def reset_key() -> None:
    """키를 다시 읽는다(없으면 새 무작위 키). 서버 재기동과 같은 효과 — 테스트용."""
    global _KEY
    _KEY = _load_key()


def _norm(v: Any, *, string_keys: bool = False) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("NaN·무한대는 서명하지 않는다")
        return int(v) if v.is_integer() and abs(v) < 2**53 else v
    if isinstance(v, Mapping):
        if string_keys and any(not isinstance(k, str) for k in v):
            raise TypeError("signed payload keys must be strings")
        return {str(k): _norm(x, string_keys=string_keys) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x, string_keys=string_keys) for x in v]
    raise TypeError(f"서명할 수 없는 값: {type(v).__name__}")


def canonical_bytes(result: Any) -> bytes:
    """계약(PremortemResult)으로 검증한 결과의 정규화 JSON 바이트. 계약을 어기면 ValidationError."""
    from neumann.models import PremortemResult

    model = result if isinstance(result, PremortemResult) else PremortemResult.model_validate(result)
    data = _norm(model.model_dump(mode="json"))
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _mac(body: bytes) -> str:
    return hmac.new(_KEY, _DOMAIN + body, hashlib.sha256).hexdigest()


def sign_result(result: Any) -> str:
    """``v1.<hex>``. 결과가 계약을 어기면 예외(호출하는 쪽이 서명을 싣지 않는다)."""
    return f"{SIG_VERSION}.{_mac(canonical_bytes(result))}"


def verify_result(result: Any, sig: Any) -> bool:
    """서명이 이 프로세스의 키로 이 결과에 대해 만든 것인지. 형식이 틀리거나 결과가 계약을 어기면 False."""
    if not isinstance(sig, str) or len(sig) != 67 or not sig.isascii() or not _SIG_RE.fullmatch(sig):
        return False
    try:
        expected = _mac(canonical_bytes(result))
    except Exception:  # noqa: BLE001 - 계약 위반·정규화 실패는 "확인 안 됨"
        return False
    return hmac.compare_digest(expected.encode("ascii"), sig[len(SIG_VERSION) + 1:].encode("ascii"))


def _payload_bytes(kind: str, data: Mapping[str, Any], *, legacy: bool = False) -> bytes:
    """Separate revision signatures from the validated result signature domain."""
    if not isinstance(kind, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", kind, re.ASCII) or kind == "result":
        raise ValueError("invalid payload signature kind")
    if not isinstance(data, Mapping):
        raise TypeError("signed payload must be a mapping")
    if kind == "revised-plan" and not legacy:
        from neumann.api.export_title import DEFAULT_TITLE, HISTORY_SUFFIX

        # Only the user title and its display heading are unsigned. All document
        # text, quotes and the rest of history remain covered by the signature.
        data = {k: v for k, v in data.items() if k != "title"}
        markdown = data.get("markdown")
        if isinstance(markdown, Mapping) and isinstance(markdown.get("history"), str):
            head, sep, tail = markdown["history"].partition("\n")
            if head.startswith("# ") and head.endswith(HISTORY_SUFFIX):
                data = {**data, "markdown": {**markdown, "history": f"# {DEFAULT_TITLE}{HISTORY_SUFFIX}{sep}{tail}"}}
    body = json.dumps(_norm(data, string_keys=True), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"neumann-{kind}-v1\n".encode("ascii") + body.encode("utf-8")


def sign_payload(kind: str, data: Mapping[str, Any]) -> str:
    """Sign validated server output with JSON string keys (including nested objects).

    ``kind`` is a lowercase ASCII domain, up to 32 characters, excluding ``result``.
    Shares the result key and v1 format, but signatures cannot cross domains.
    Callers must validate their schema and enforce provenance before signing.
    For ``revised-plan``, user ``title`` and the title part of the history heading
    are excluded; document content and evidence remain signed.
    """
    digest = hmac.new(_KEY, _payload_bytes(kind, data), hashlib.sha256).hexdigest()
    return f"{SIG_VERSION}.{digest}"


def verify_payload(kind: str, data: Any, sig: Any) -> bool:
    """Malformed input, domain substitution and altered payloads fail closed."""
    if not isinstance(sig, str) or len(sig) != 67 or not sig.isascii() or not _SIG_RE.fullmatch(sig):
        return False
    try:
        expected = sign_payload(kind, data)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False
    if hmac.compare_digest(expected.encode("ascii"), sig.encode("ascii")):
        return True
    # Existing v1 assemblies had no title metadata and signed the rendered heading.
    # Accept those exact old bytes; a changed legacy document still fails closed.
    if kind == "revised-plan" and isinstance(data, Mapping) and "title" not in data:
        try:
            old = hmac.new(_KEY, _payload_bytes(kind, data, legacy=True), hashlib.sha256).hexdigest()
        except (TypeError, ValueError, OverflowError, RecursionError):
            return False
        return hmac.compare_digest(f"{SIG_VERSION}.{old}".encode("ascii"), sig.encode("ascii"))
    return False


__all__ = ["KEY_ENV", "canonical_bytes", "reset_key", "sign_result", "verify_result", "sign_payload", "verify_payload"]
