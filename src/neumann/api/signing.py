"""분석 결과 서버 서명(E4-L2f F1). 서버가 만든 결과인지 내보내기 때 확인한다.

    from neumann.api.signing import sign_result, verify_result
    sig = sign_result(result_json)          # 화면 응답(view·jobs)에 실어 보낸다
    ok = verify_result(result_json, sig)    # /premortem/package가 되돌려 받은 결과를 확인한다

- 서명: HMAC-SHA256(키, "neumann-result-v1\\n" + 정규화 JSON). 문자열 형식은 ``v1.<64 hex>``.
- 정규화: ``PremortemResult``로 검증한 뒤 JSON으로 되돌리고(계약 필드만), 정수로 떨어지는 실수는 정수로 바꾸고(브라우저
  JSON 왕복에서 ``1.0``이 ``1``이 된다), 키를 정렬한 압축 JSON(UTF-8). 같은 값이면 서명이 같다.
- 키: 프로세스 환경변수 ``NEUMANN_RESULT_HMAC_KEY``. 없으면 모듈을 처음 읽을 때(서버 기동) 무작위 32바이트를 만든다.
  그러면 재기동 뒤에는 옛 서명이 모두 무효가 된다(내보내기는 "client_submitted_unverified"로 정직하게 표시).
- 키 값과 키 설정 여부는 로그·응답·/health 어디에도 내보내지 않는다. 이 모듈은 로그를 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
from collections.abc import Mapping
from typing import Any

KEY_ENV = "NEUMANN_RESULT_HMAC_KEY"
SIG_VERSION = "v1"
_DOMAIN = b"neumann-result-v1\n"


def _load_key() -> bytes:
    raw = os.environ.get(KEY_ENV, "")
    return raw.encode("utf-8") if raw.strip() else secrets.token_bytes(32)


_KEY: bytes = _load_key()


def reset_key() -> None:
    """키를 다시 읽는다(없으면 새 무작위 키). 서버 재기동과 같은 효과 — 테스트용."""
    global _KEY
    _KEY = _load_key()


def _norm(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("NaN·무한대는 서명하지 않는다")
        return int(v) if v.is_integer() and abs(v) < 2**53 else v
    if isinstance(v, Mapping):
        return {str(k): _norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
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
    if not isinstance(sig, str) or not sig.startswith(SIG_VERSION + "."):
        return False
    mac = sig[len(SIG_VERSION) + 1:]
    if len(mac) != 64:
        return False
    try:
        expected = _mac(canonical_bytes(result))
    except Exception:  # noqa: BLE001 - 계약 위반·정규화 실패는 "확인 안 됨"
        return False
    return hmac.compare_digest(expected, mac)


__all__ = ["KEY_ENV", "canonical_bytes", "reset_key", "sign_result", "verify_result"]
