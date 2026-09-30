"""공개 라이브 서버 안정성 층(E4-L2c + SEC-1 대응).

동시 상한·대기열·IP 속도 제한·일일 예산·차단 스위치·입력(바이트·글자) 상한·요청 시간 상한·결과 캐시·예열·
사용자 오류 문구·전역 예외 처리·로그 위생. main.py에는 PM이 붙인다(이 모듈은 main.py를 import 하지 않는다).

    from neumann.api import serving
    serving.install(app)                                  # 미들웨어·예외 처리기·GET /queue/status·로그 필터·예열
    ...
    return serving.wrap_pipeline(fn), "connected", ""     # _load_pipeline 안: 캐시·대기열·시간 상한을 씌운다
    # _run_pipeline 의 `async with _semaphore():` 는 지운다(동시 상한은 여기 Gate가 한다)

보호 경로(설정 ``NEUMANN_PROTECTED_PATHS``)와 종류
- ``analysis``(/premortem, /premortem/view): 파이프라인 감싸개(wrap_pipeline)가 분석 관문에서 슬롯을 잡는다.
  캐시 적중·같은 계획서 합류는 관문·속도 제한·예산을 거치지 않는다.
- ``export``(/premortem/package), ``upload``(/upload/plan), ``gated``(그 밖에 설정한 경로): 미들웨어가 보조 관문
  (동시 상한·대기열·시간 상한)과 보조 속도 제한을 씌운다. export 본문에 ``plan_text``만 있고 ``result``가 없으면
  (옛 파이프라인 실행 경로) 분석과 같은 관문·예산·차단 스위치로 묶는다.

관문 순서(새 분석): 바이트 상한(Content-Length → 스트리밍 누적, 파싱 전 413) → 글자 상한(413) → 캐시·합류면 통과 →
차단 스위치(503) → IP 속도 제한(429) → 일일 예산(503) → 대기열(가득이면 503) → 실행(시간 상한 넘으면 504).

결과 캐시(S-06): 사용자 입력 결과는 **메모리에만**(TTL·개수 상한) 두고 디스크에 쓰지 않는다. 디스크
(``<data_dir>/cache/results/<plan_id>.json``)는 공개 입력(데모 계획서·템플릿의 plan_id 허용 목록)만 쓴다. 메모리·디스크
모두 계획서 줄 텍스트를 뺀 저장본이고, 적중 때 요청 본문으로 줄을 다시 붙인다. status가 ``ok``인 결과만 저장한다.

설정(환경변수, 모두 선택). ``NEUMANN_PUBLIC=1``(scripts/serve.py --public)이면 공개 프로필: 속도 제한·결과 캐시·
예열·일일 예산·/docs 숨김이 기본으로 켜진다. 없으면(테스트·개발) 이것들은 꺼지고 관문·상한·오류 문구·로그 위생만 켜진다.
키 목록은 ``ServingConfig.from_env``와 보고서 docs/reports/E4-L2c.md에 있다.

프로세스 하나(uvicorn worker 1개)를 전제로 한다. 대기열·속도 제한 상태는 프로세스 메모리에 있다(예산은 파일에도 남김).

SEC-7 보강: 모든 응답에 보안 헤더(nosniff·frame-ancestors 'none'·X-Frame-Options DENY·no-referrer), 요청 대상 8KB 상한(414),
보호 경로 밖 요청(GET 등)의 IP별 분당 상한(공개 600), CF-Connecting-IP 값 검증, IPv6 /56 묶음, IP별 대기열 몫(대기 칸의 1/3,
남은 자리는 처음 오는 사용자 몫), 계획서 줄 수 상한(5,000줄, 422), 로그에서 살아 있는 job_id 정확 일치 가림·긴 인자 자르기·
설정 이름 허용 목록.
"""

from __future__ import annotations

import asyncio
import contextvars
import copy
import hashlib
import heapq
import hmac
import importlib
import inspect
import ipaddress
import json
import logging
import math
import os
import re
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neumann.api.plan_limits import PlanLimitError, check_payload_plan

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("neumann.serving")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROTECTED = {
    "/premortem": "analysis",
    "/premortem/view": "analysis",
    "/premortem/package": "export",
    "/upload/plan": "upload",
}
KINDS = {"analysis", "export", "upload", "gated"}
DOC_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})
TICKET_HEADER = "x-neumann-ticket"
JOB_POLL_PREFIX = "/premortem/jobs/"  # 작업 폴링 GET(jobs.py가 따로 IP별 상한을 건다)
JOB_POLL_PATH_RE = re.compile(re.escape(JOB_POLL_PREFIX) + r"[^/]+")  # jobs의 /{job_id} 한 구간만
_TICKET_RE = re.compile(r"^[A-Za-z0-9_\-]{6,64}$")
_PLAN_ID_RE = re.compile(r"^[0-9a-f]{64}$")

# ───────────────────────── 사용자 문구 ─────────────────────────

MESSAGES = {
    "busy": "지금 분석 요청이 많아 대기열이 가득 찼습니다. 약 {retry}초 뒤에 다시 시도해 주세요.",
    "busy_aux": "지금 처리 중인 요청이 많습니다. 약 {retry}초 뒤에 다시 시도해 주세요.",
    "rate": "요청이 너무 잦습니다. {retry}초 뒤에 다시 시도해 주세요(분당 {limit}건).",
    "budget": ("오늘 준비한 분석 한도({limit}건)를 모두 썼습니다. 이미 분석된 계획서와 예시 결과는 계속 볼 수 있습니다. "
               "내일 다시 시도해 주세요."),
    "blocked": "지금은 새 분석을 잠시 멈췄습니다. 이미 분석된 계획서와 예시 결과는 계속 볼 수 있습니다.",
    "too_large": "계획서가 너무 깁니다. {limit:,}자 이하로 줄여서 다시 올려 주세요(현재 {chars:,}자).",
    "too_large_bytes": "요청이 너무 큽니다({limit_mb}MB 이하만 받습니다). 계획서는 {chars:,}자 이하로 올려 주세요.",
    "timeout": ("분석이 {limit}초 안에 끝나지 않았습니다. 분석은 계속 진행 중이니 잠시 뒤 같은 계획서로 다시 요청하면 "
                "끝난 결과를 바로 받을 수 있습니다(요청 번호 {ticket})."),
    "timeout_aux": "처리가 {limit}초 안에 끝나지 않았습니다. 잠시 뒤 다시 시도해 주세요(요청 번호 {ticket}).",
    "invalid": "요청 형식이 올바르지 않습니다. 보낸 내용을 확인하고 다시 시도해 주세요.",
    "long_token": ("계획서에 띄어쓰기 없이 {limit:,}자가 넘게 이어진 부분이 있습니다(가장 긴 부분 {longest:,}자). "
                   "긴 링크·인코딩된 데이터·표 서식을 줄여서 다시 올려 주세요."),
    # SEC-7
    "too_many_lines": "줄이 너무 많습니다(최대 {limit:,}줄). 문단으로 합쳐 주세요.",
    "queue_ip": ("이 주소에서 요청한 분석 {n}건이 이미 대기열에 있습니다. 다른 분의 자리를 남겨 두려고 더 받지 않습니다. "
                 "앞 분석이 끝난 뒤 다시 시도해 주세요."),
    "uri_too_long": "요청 주소가 너무 깁니다({limit:,}바이트 이하만 받습니다).",
    "internal": "처리 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요. 계속되면 요청 번호 {ticket}를 알려 주세요.",
    "not_found": "없는 주소입니다.",
    # 업로드(E4-L1a upload.py와 같은 문구: 화면이 같은 안내를 보게)
    "upload_type": "multipart/form-data 형식으로 file 필드에 계획서 파일을 담아 보내 주세요",
    "upload_boundary": "multipart 경계(boundary)가 없습니다",
    "busy_ip": "이 주소에서 올린 파일을 아직 처리하고 있습니다. 끝난 뒤 다시 올려 주세요.",
}


def user_message(kind: str, **kw: Any) -> str:
    return MESSAGES[kind].format(**kw)


# ───────────────────────── 설정 ─────────────────────────


def _env(name: str) -> str | None:
    v = os.getenv(name)
    return v.strip() if v and v.strip() else None


def _env_bool(name: str, default: bool) -> bool:
    v = _env(name)
    return default if v is None else v.lower() in {"1", "true", "yes", "on"}


def _env_num(name: str, default: float, lo: float, hi: float) -> float:
    v = _env(name)
    if v is None:
        return default
    try:
        x = float(v)
    except ValueError:
        log.warning("설정 %s 값이 숫자가 아니어서 기본값 %s를 쓴다", name, default)
        return default
    return min(max(x, lo), hi)


def _default_data_dir() -> Path:
    try:
        from neumann.config import get_settings

        return Path(get_settings().data_dir)
    except Exception:  # noqa: BLE001 - 설정 실패해도 서버는 뜬다
        return Path(_env("NEUMANN_DATA_DIR") or REPO_ROOT / "data")


def _default_variant() -> str:
    """캐시 구분자: provider·모델·버전이 다르면 다른 결과다."""
    try:
        import neumann
        from neumann.config import get_settings

        s = get_settings()
        return f"{s.llm_provider}:{s.llm_model}:{neumann.__version__}"
    except Exception:  # noqa: BLE001
        return "unknown"


def _parse_protected(raw: str | None) -> dict[str, str]:
    """``/a=analysis;/b=upload;/c`` → {경로: 종류}. 종류를 안 적으면 gated."""
    if not raw:
        return dict(DEFAULT_PROTECTED)
    out: dict[str, str] = {}
    for part in re.split(r"[;,]", raw):
        part = part.strip()
        if not part.startswith("/"):
            continue
        path, _, kind = part.partition("=")
        kind = kind.strip().lower() or DEFAULT_PROTECTED.get(path.strip(), "gated")
        out[path.strip().rstrip("/") or "/"] = kind if kind in KINDS else "gated"
    return out or dict(DEFAULT_PROTECTED)


DEMO_PLAN_GLOB = ("tests/fixtures/plans", "plan*.md")  # 데모 계획서 3건(E6 사전 계산본과 같은 입력)


@dataclass(frozen=True)
class ServingConfig:
    max_concurrent: int = 2
    queue_max: int = 20
    sync_queue_max: int = 0             # 동기 경로(/premortem, /view) 입장 때 대기 수 상한(0이면 queue_max). 작업 경로는 queue_max
    rate_per_min: int = 0
    preparse_per_min: int = 0           # 본문을 읽기 전 IP(/64)별 분석 경로 POST 상한(아주 넉넉히, 공개 60, 0이면 끔)
    rate_window_s: float = 60.0
    max_plan_chars: int = 50_000
    max_token_chars: int = 20_000       # 공백 없이 이어진 토큰 하나의 글자 상한(E4-L2d 재작업: 정규식 O(n²) 방어 겹)
    max_plan_lines: int = 5_000         # 계획서 줄 수 상한(SEC-7: 짧은 줄 수만 개로 요청당 CPU를 키우는 입력). 넘으면 422
    max_request_line: int = 8192        # 요청 대상(경로+쿼리) 바이트 상한(SEC-7). 넘으면 414. 0이면 끔
    get_rate_per_min: int = 0           # 보호 POST·작업 폴링 밖 요청(GET 등)의 IP별 분당 상한(SEC-7, 공개 600, 0이면 끔)
    queue_per_ip: int = 0               # 분석 관문(실행+대기)에서 IP 묶음 하나가 잡을 수 있는 자리 수(SEC-7, 공개 대기 칸의 1/3)
    queue_reserve: int = 0              # 이미 자리를 가진 IP는 남은 자리가 이만큼 이하면 더 못 잡는다(처음 오는 사용자 몫)
    max_body_bytes: int = 0             # 0이면 max_plan_chars*6 + 64KB
    max_export_bytes: int = 4 * 1024 * 1024
    max_upload_bytes: int = 10 * 1024 * 1024 + 65_536
    request_timeout_s: float = 300.0
    avg_run_s: float = 60.0
    aux_concurrent: int = 2
    aux_queue_max: int = 10
    aux_timeout_s: float = 60.0
    aux_rate_per_min: int = 0
    upload_rate_per_min: int = 0        # 업로드 전용 IP(/64)별 분당 상한(공개 10)
    upload_per_ip: int = 0              # 업로드 IP(/64)별 동시 처리 상한(공개 1). 0이면 끔
    daily_budget: int = 0               # 0이면 끔
    budget_file: Path | None = None
    block_new: bool = False
    block_file: Path | None = None
    cache_enabled: bool = False
    cache_dir: Path | None = None       # 디스크: 허용 목록(공개 입력)만
    cache_mem_items: int = 64
    cache_ttl_s: float = 6 * 3600.0
    cache_statuses: tuple[str, ...] = ("ok",)
    cache_variant: str = "default"
    disk_allow: frozenset[str] = frozenset()
    trust_proxy: str = "loopback"       # loopback | always | never
    xff_pick: str = "first"             # first | last
    trust_xff: bool = True              # 공개 프로필 기본 False: X-Forwarded-For는 위조할 수 있다
    hide_docs: bool = False
    protected: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PROTECTED))
    warmup: bool = False
    warmup_plans: tuple[Path, ...] = ()
    public: bool = False

    @property
    def analysis_body_bytes(self) -> int:
        return self.max_body_bytes or self.max_plan_chars * 6 + 65_536

    def body_limit(self, kind: str) -> int:
        return {"analysis": self.analysis_body_bytes, "upload": self.max_upload_bytes}.get(kind, self.max_export_bytes)

    @classmethod
    def from_env(cls) -> ServingConfig:
        public = _env_bool("NEUMANN_PUBLIC", False)
        data_dir = _default_data_dir()
        cache_dir = _env("NEUMANN_RESULT_CACHE_DIR")
        plans = _env("NEUMANN_WARMUP_PLANS")
        if plans:
            warm = tuple(Path(p) for p in plans.split(";") if p.strip())
        else:
            warm = tuple(sorted((REPO_ROOT / DEMO_PLAN_GLOB[0]).glob(DEMO_PLAN_GLOB[1])))
        # 디스크 허용 목록: 데모 계획서 3건(공개 입력)만 + 운영자가 명시한 sha256. 사용자 입력은 절대 디스크에 안 쓴다.
        allow = set(public_plan_ids(sorted((REPO_ROOT / DEMO_PLAN_GLOB[0]).glob(DEMO_PLAN_GLOB[1]))))
        allow |= {x.strip() for x in (_env("NEUMANN_DISK_CACHE_ALLOW") or "").split(";") if _PLAN_ID_RE.match(x.strip())}
        trust = (_env("NEUMANN_TRUST_PROXY") or "loopback").lower()
        block_file = _env("NEUMANN_BLOCK_FILE")
        budget_file = _env("NEUMANN_BUDGET_FILE")
        queue_max = int(_env_num("NEUMANN_QUEUE_MAX", 30 if public else 20, 0, 10_000))
        share = max(math.ceil(queue_max / 3), 1) if public else 0  # SEC-7: IP 하나는 대기 칸의 1/3까지
        return cls(
            # 공개 기본값(다중 사용자, E4-L2d 대표 지시): 동시 4·대기 30(작업 방식), 동기 경로는 대기 4까지만
            max_concurrent=int(_env_num("NEUMANN_MAX_CONCURRENT", 4 if public else 2, 1, 64)),
            queue_max=queue_max,
            queue_per_ip=int(_env_num("NEUMANN_QUEUE_PER_IP", share, 0, 10_000)),
            queue_reserve=int(_env_num("NEUMANN_QUEUE_RESERVE", share, 0, 10_000)),
            max_plan_lines=int(_env_num("NEUMANN_MAX_PLAN_LINES", 5_000, 10, 10_000_000)),
            max_request_line=int(_env_num("NEUMANN_MAX_REQUEST_LINE", 8192, 0, 1 << 20)),
            get_rate_per_min=int(_env_num("NEUMANN_GET_RATE_PER_MIN", 600 if public else 0, 0, 1_000_000)),
            sync_queue_max=int(_env_num("NEUMANN_SYNC_QUEUE_MAX", 4 if public else 0, 0, 10_000)),
            rate_per_min=int(_env_num("NEUMANN_RATE_PER_MIN", 6 if public else 0, 0, 100_000)),
            preparse_per_min=int(_env_num("NEUMANN_PREPARSE_PER_MIN", 60 if public else 0, 0, 1_000_000)),
            max_plan_chars=int(_env_num("NEUMANN_MAX_PLAN_CHARS", 50_000, 1, 10_000_000)),
            max_token_chars=int(_env_num("NEUMANN_MAX_TOKEN_CHARS", 20_000, 64, 10_000_000)),
            max_body_bytes=int(_env_num("NEUMANN_MAX_BODY_BYTES", 0, 0, 1 << 31)),
            max_export_bytes=int(_env_num("NEUMANN_MAX_EXPORT_BYTES", 4 * 1024 * 1024, 1024, 1 << 31)),
            max_upload_bytes=int(_env_num("NEUMANN_MAX_UPLOAD_BYTES", 10 * 1024 * 1024 + 65_536, 1024, 1 << 31)),
            request_timeout_s=_env_num("NEUMANN_REQUEST_TIMEOUT_S", 90.0 if public else 300.0, 0.05, 86_400),
            avg_run_s=_env_num("NEUMANN_AVG_RUN_S", 60.0, 0.1, 86_400),
            aux_concurrent=int(_env_num("NEUMANN_AUX_CONCURRENT", 2, 1, 64)),
            aux_queue_max=int(_env_num("NEUMANN_AUX_QUEUE_MAX", 10, 0, 10_000)),
            aux_timeout_s=_env_num("NEUMANN_AUX_TIMEOUT_S", 60.0, 0.05, 86_400),
            aux_rate_per_min=int(_env_num("NEUMANN_AUX_RATE_PER_MIN", 30 if public else 0, 0, 100_000)),
            upload_rate_per_min=int(_env_num("NEUMANN_UPLOAD_RATE_PER_MIN", 10 if public else 0, 0, 100_000)),
            upload_per_ip=int(_env_num("NEUMANN_UPLOAD_PER_IP", 1 if public else 0, 0, 1000)),
            daily_budget=int(_env_num("NEUMANN_DAILY_BUDGET", 0, 0, 10_000_000)),  # 대표 결정: 기본 끔
            budget_file=Path(budget_file) if budget_file else data_dir / "cache" / "serving_budget.json",
            block_new=_env_bool("NEUMANN_BLOCK_NEW", False),
            block_file=Path(block_file) if block_file else data_dir / "serving_block.flag",
            cache_enabled=_env_bool("NEUMANN_RESULT_CACHE", public),
            cache_dir=Path(cache_dir) if cache_dir else data_dir / "cache" / "results",
            cache_mem_items=int(_env_num("NEUMANN_CACHE_MEM_ITEMS", 64, 0, 100_000)),
            cache_ttl_s=_env_num("NEUMANN_CACHE_TTL_S", 6 * 3600.0, 1, 30 * 86_400),
            cache_variant=_default_variant(),
            disk_allow=frozenset(allow),
            trust_proxy=trust if trust in {"loopback", "always", "never"} else "loopback",
            xff_pick="last" if (_env("NEUMANN_XFF_PICK") or "").lower() == "last" else "first",
            trust_xff=_env_bool("NEUMANN_TRUST_XFF", not public),  # 공개: CF-Connecting-IP만 믿는다
            hide_docs=_env_bool("NEUMANN_HIDE_DOCS", public),
            protected=_parse_protected(_env("NEUMANN_PROTECTED_PATHS")),
            warmup=_env_bool("NEUMANN_WARMUP", public),
            warmup_plans=warm,
            public=public,
        )

    def public_view(self) -> dict[str, Any]:
        return {
            "max_concurrent": self.max_concurrent, "queue_max": self.queue_max, "sync_queue_max": self.sync_queue_max, "rate_per_min": self.rate_per_min,
            "max_plan_chars": self.max_plan_chars, "max_plan_lines": self.max_plan_lines,
            "request_timeout_s": self.request_timeout_s,
            "cache": self.cache_enabled, "public": self.public,
        }


# ───────────────────────── 비밀값·내부 정보 가리기 ─────────────────────────

# 키 모양(verify.py와 같은 종류). 이 파일이 검사에 걸리지 않게 쪼개 쓴다.
_SECRET_RES = [
    re.compile(r"\bs" r"k-[A-Za-z0-9_\-*.]{12,}"),
    re.compile(r"\bgh" r"[pousr]_[A-Za-z0-9]{20,}|github" r"_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bh" r"f_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAK" r"IA[0-9A-Z]{16}\b"),
    re.compile(r"\bAI" r"za[0-9A-Za-z_\-]{30,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
]
_SECRET_ENV = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HF_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "NEUMANN_PSEUDONYM_SALT")
REDACTED = "[가림]"
# 절대 경로(Windows 드라이브·UNC·유닉스 홈 등)와 상류 API 오류 문구
_PATH_RE = re.compile(r"(?:\b[A-Za-z]:[\\/]|\\\\)[^\s\"'<>|,;)]*|/(?:home|Users|usr|tmp|var|opt|mnt|root|srv|etc)/[^\s\"'<>|,;)]*")
_API_MSG_RE = re.compile(r"(HTTP \d{3})\b[^)\n]*|Incorrect API key provided[^)\n]*|You can find your API key[^)\n]*")


def _env_secret_values() -> list[str]:
    vals = []
    for name in _SECRET_ENV:
        v = os.getenv(name)
        if v and len(v.strip()) >= 8:
            vals.append(v.strip())
    return vals


def scrub_secrets(text: str) -> str:
    for val in _env_secret_values():
        if val in text:
            text = text.replace(val, REDACTED)
    for rx in _SECRET_RES:
        text = rx.sub(REDACTED, text)
    return text


def scrub_public(text: str) -> str:
    """공개 응답용: 키·절대 경로·상류 API 오류 문구를 가린다(분류는 남긴다: 'HTTP 401')."""
    text = scrub_secrets(text)
    text = _PATH_RE.sub("[경로]", text)
    return _API_MSG_RE.sub(lambda m: m.group(1) or "[API 오류 문구 생략]", text)


_TRACE_RE = re.compile(r"Traceback \(most recent call last\)|File \"[^\"]+\", line \d+")
_INTERNAL_RE = re.compile(
    r"Traceback|File \"|\.py\b|[A-Za-z]:[\\/]|/(?:home|usr|Users|tmp|var|opt)/|\b[A-Z]\w*(?:Error|Exception|Timeout|Exit)\b"
    r"|import 실패|모듈 없음|실행 실패|HTTP \d{3}"
)
_EXC_NAME_RE = re.compile(r"\b([A-Z]\w*(?:Error|Exception|Timeout|Exit))\b")


def _exc_kind(text: str) -> str | None:
    m = _EXC_NAME_RE.search(text)
    return m.group(1) if m else None


def _sanitize_error_str(s: str, msg: str) -> str:
    if not _INTERNAL_RE.search(s):
        return scrub_public(s)
    kind = _exc_kind(s)
    return f"{msg} (오류 종류: {kind})" if kind else msg


def _walk_strings(obj: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_walk_strings(x, fn) for x in obj]
    if isinstance(obj, dict):
        return {k: _walk_strings(v, fn) for k, v in obj.items()}
    return obj


# 정상 응답에서 가리는 곳: 진단 문구 필드만. 근거 인용·계획서 줄은 글자 그대로 둔다(인용은 원문과 같아야 한다).
DIAG_KEYS = frozenset({"notices", "reason", "detail", "error", "errors", "message", "log", "warnings", "stages_not_ok",
                       "contract_errors", "section_errors", "empty_reason", "note"})


def _walk_diag(obj: Any, fn: Callable[[str], str], under: bool = False) -> Any:
    if isinstance(obj, str):
        return fn(obj) if under else obj
    if isinstance(obj, list):
        return [_walk_diag(x, fn, under) for x in obj]
    if isinstance(obj, dict):
        return {k: _walk_diag(v, fn, under or k in DIAG_KEYS) for k, v in obj.items()}
    return obj


def _scrub_ok_str(s: str) -> str:
    if _TRACE_RE.search(s):
        kind = _exc_kind(s)
        return f"(내부 추적 정보 생략{': ' + kind if kind else ''})"
    return scrub_public(s)


def longest_token(text: str) -> int:
    """공백 없이 이어진 가장 긴 토큰의 글자 수. str.split(C 구현, 선형)만 쓴다(정규식 역추적 없음)."""
    return max((len(t) for t in text.split()), default=0)


def count_lines(text: str) -> int:
    """``PlanDocument.from_text``와 같은 규칙(CRLF·CR → LF 뒤 ``split("\\n")``)의 줄 수. str.count만 쓴다(선형)."""
    return text.count("\n") + text.count("\r") - text.count("\r\n") + 1


# 로그의 job_id 가리기(재작업 3·4). job_id는 결과 열람 자격(URL-safe 32자)이다.
# - 퍼센트 인코딩 인식(재작업 4): uvicorn 접근 로그는 쿼리를 날것으로 적으므로 ``%45``처럼 인코딩한 글자도 토큰의
#   일부로 읽는다. [URL-safe 글자 | %XX]가 이어진 구간을 풀어(decoded) 보고, 푼 글자가 URL-safe로 N자 이상 이어지면
#   그 부분을 "푼 앞 6자 + …"로 바꾼다(접근 로그 20자, 앱 로그 26자: 요청 번호·예외 이름은 남긴다).
# - 경로(/premortem/jobs/…, 대소문자·겹 슬래시·%2F)와 쿼리(?job=·?job_id=·?id=·?ticket=)는 길이와 무관하게 가린다.
# - 결과는 두 번 걸어도 같다("…"는 토큰 글자가 아니다).
_URLSAFE_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
_ENC_RUN_RE = re.compile(r"(?:[A-Za-z0-9_\-]|%[0-9A-Fa-f]{2})+")
_ENC_UNIT_RE = re.compile(r"[A-Za-z0-9_\-]|%[0-9A-Fa-f]{2}")
_JOB_PATH_RE = re.compile(r"(?i)(/premortem/+jobs(?:/|%2F)+)((?:[A-Za-z0-9_\-]|%[0-9A-Fa-f]{2})+)…?")
_JOB_QUERY_RE = re.compile(r"(?i)([?&;](?:job|job_id|jobid|id|ticket)=)((?:[A-Za-z0-9_\-]|%[0-9A-Fa-f]{2})+)…?")
ACCESS_TOKEN_MIN = 20
APP_TOKEN_MIN = 26
# 길이 기준 가림의 허용 목록(SEC-7): 설정 이름(``NEUMANN_`` + 대문자·숫자·밑줄)은 26자가 넘어도 그대로 둔다
# ("설정 NEUMANN_UPLOAD_RATE_PER_MIN 값이…" 경고를 읽을 수 있게). job_id는 서버가 만든 대소문자 섞인 무작위 32자라
# 이 모양이 될 수 없고, 살아 있는 job_id는 아래 정확 일치 가림이 따로 가린다.
LOG_ALLOW_RE = re.compile(r"NEUMANN_[A-Z0-9_]{1,80}")


def _decode_units(run: str) -> list[tuple[str, str]]:
    """토큰 구간 → [(날것 단위, 푼 글자)]. ``%XX``는 한 바이트를 글자 하나로 푼다(URL-safe 판정용)."""
    return [(u, chr(int(u[1:], 16)) if u[0] == "%" else u) for u in _ENC_UNIT_RE.findall(run)]


def _head6(raw: str) -> str:
    """토큰(인코딩 포함)을 풀어 앞에서부터 URL-safe 글자 최대 6자 + "…"(두 번 걸어도 같게 구분 글자에서 멈춘다)."""
    head: list[str] = []
    for _, c in _decode_units(raw):
        if c not in _URLSAFE_CHARS or len(head) == 6:
            break
        head.append(c)
    return "".join(head) + "…"


def _mask_run(run: str, min_len: int) -> str:
    """토큰 구간 하나: 푼 글자가 URL-safe로 min_len자 이상 이어지는 부분을 앞 6자 + "…"로."""
    out: list[str] = []
    raw: list[str] = []
    dec: list[str] = []

    def flush() -> None:
        hide = len(dec) >= min_len and not LOG_ALLOW_RE.fullmatch("".join(dec))  # 설정 이름은 허용 목록(SEC-7)
        out.append("".join(dec[:6]) + "…" if hide else "".join(raw))
        raw.clear()
        dec.clear()

    for u, c in _decode_units(run):
        if c in _URLSAFE_CHARS:
            raw.append(u)
            dec.append(c)
        else:  # 인코딩된 구분 글자(%2F 등)는 그대로 두고 앞뒤를 따로 본다
            flush()
            out.append(u)
    flush()
    return "".join(out)


def mask_job_paths(text: str, *, access: bool = False) -> str:
    """로그용: job_id(결과 열람 자격)를 앞 6자만 남긴다(퍼센트 인코딩을 풀어서 판정, 두 번 걸어도 같다)."""
    if "jobs" in text.lower():
        text = _JOB_PATH_RE.sub(lambda m: m.group(1) + _head6(m.group(2)), text)
    if "=" in text:
        text = _JOB_QUERY_RE.sub(lambda m: m.group(1) + _head6(m.group(2)), text)
    n = ACCESS_TOKEN_MIN if access else APP_TOKEN_MIN
    return _ENC_RUN_RE.sub(lambda m: _mask_run(m.group(0), n) if len(m.group(0)) >= n else m.group(0), text)


# 살아 있는 job_id 정확 일치 가림(SEC-7, E4-L2d 재검증 권고 ①). 길이 기준 가림은 구분 글자(``+``·``/``·잘못된 ``%zz``·
# 이중 인코딩 ``%2541``)로 쪼갠 id를 못 잡는다. 작업 저장소가 아는 id를 등록해 두고, 로그 글을 "퍼센트 인코딩을 세 겹까지
# 풀고 URL-safe가 아닌 글자를 모두 뺀 뼈대"로 바꿔 그 안에서 id를 정확히 찾는다. 찾으면 원문에서 그 id가 걸친 구간 전체를
# "id 앞 6자 + …"로 바꾼다. 뼈대 만들기와 창 검사는 글 길이에 선형이다(창 하나는 집합 조회 한 번).
_LIVE_SECRETS: set[str] = set()
_LIVE_LENS: dict[int, int] = {}
LOG_ARG_MAX = 2048        # 로그 인자 문자열 상한(넘으면 앞부분만 두고 끝의 잘린 토큰은 뺀다): 긴 쿼리로 필터 시간 키우기 방어
_CLIP_TOKEN_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.*%+~")
_HEX_CHARS = frozenset("0123456789abcdefABCDEF")


def register_log_secret(token: str) -> None:
    """로그에서 정확 일치로도 가릴 값(살아 있는 job_id)을 등록한다. 이벤트 루프에서 부른다."""
    if isinstance(token, str) and len(token) >= 16 and token not in _LIVE_SECRETS:
        _LIVE_SECRETS.add(token)
        _LIVE_LENS[len(token)] = _LIVE_LENS.get(len(token), 0) + 1


def forget_log_secret(token: str) -> None:
    """등록한 값을 뺀다(작업이 만료·삭제될 때)."""
    if token in _LIVE_SECRETS:
        _LIVE_SECRETS.discard(token)
        n = _LIVE_LENS.get(len(token), 0) - 1
        if n > 0:
            _LIVE_LENS[len(token)] = n
        else:
            _LIVE_LENS.pop(len(token), None)


def _skeletons(text: str) -> list[tuple[str, list[int], list[int]]]:
    """로그 글 → [(뼈대, 뼈대 글자별 원문 시작, 원문 끝)]. 뼈대는 퍼센트 인코딩을 세 겹까지 푼 뒤 URL-safe 글자만 남긴 것.

    풀고 남은 ``%``(잘못된 인코딩 ``%zz`` 등)가 있으면, 그 ``%``와 뒤 영숫자 두 개까지 뺀 뼈대를 하나 더 만든다.
    """
    units = [(c, i, i + 1) for i, c in enumerate(text)]
    for _ in range(3):
        if "%" not in text:
            break
        out: list[tuple[str, int, int]] = []
        j, n, changed = 0, len(units), False
        while j < n:
            c = units[j][0]
            if c == "%" and j + 2 < n and units[j + 1][0] in _HEX_CHARS and units[j + 2][0] in _HEX_CHARS:
                out.append((chr(int(units[j + 1][0] + units[j + 2][0], 16)), units[j][1], units[j + 2][2]))
                j += 3
                changed = True
            else:
                out.append(units[j])
                j += 1
        units = out
        if not changed or not any(u[0] == "%" for u in units):
            break
    variants = [False]
    if any(u[0] == "%" for u in units):
        variants.append(True)
    res = []
    for drop_after_pct in variants:
        chars: list[str] = []
        starts: list[int] = []
        ends: list[int] = []
        skip = 0
        for c, s, e in units:
            if skip and c.isascii() and c.isalnum():
                skip -= 1
                continue
            skip = 0
            if c == "%" and drop_after_pct:
                skip = 2
            elif c in _URLSAFE_CHARS:
                chars.append(c)
                starts.append(s)
                ends.append(e)
        res.append(("".join(chars), starts, ends))
    return res


def mask_live_secrets(text: str) -> str:
    """등록된 살아 있는 job_id를 원문·퍼센트 인코딩(세 겹까지)·구분 글자로 쪼갠 모양 모두에서 가린다(선형)."""
    if not _LIVE_SECRETS or len(text) < min(_LIVE_LENS, default=10**9):
        return text
    lens = tuple(_LIVE_LENS)
    spans: list[tuple[int, int, str]] = []
    for sk, starts, ends in _skeletons(text):
        for ln in lens:
            for i in range(len(sk) - ln + 1):
                tok = sk[i:i + ln]
                if tok in _LIVE_SECRETS:
                    spans.append((starts[i], ends[i + ln - 1], tok))
    if not spans:
        return text
    spans.sort()
    out: list[str] = []
    pos = 0
    for s, e, tok in spans:
        if s < pos:  # 겹치는 구간은 앞 것에 합친다
            continue
        out.append(text[pos:s])
        out.append(tok[:6] + "…")
        pos = e
    out.append(text[pos:])
    return "".join(out)


def _clip(text: str, limit: int = LOG_ARG_MAX) -> str:
    """긴 로그 인자는 앞 ``limit``자만 둔다. 잘린 자리의 토큰 조각(자격·키의 일부일 수 있다)은 통째로 뺀다."""
    if len(text) <= limit:
        return text
    i = limit
    while i and text[i - 1] in _CLIP_TOKEN_CHARS:
        i -= 1
    return f"{text[:i]}…(+{len(text) - i}자 생략)"


def _scrub_log(text: str, access: bool = False) -> str:
    return mask_job_paths(mask_live_secrets(scrub_secrets(_clip(text))), access=access)


def scrub_ok_payload(data: Any) -> Any:
    """정상 분석 응답의 진단 필드에서 키·절대 경로·상류 API 문구·트레이스를 가린다(미들웨어와 같은 규칙)."""
    return _walk_diag(data, _scrub_ok_str)


class RedactingFilter(logging.Filter):
    """로그 레코드에서 키 모양 문자열·실제 키 값을 가리고, 트레이스를 예외 종류 한 줄로 줄인다.

    인자 구조(uvicorn 접근 로그 포매터가 풀어 쓰는 튜플)는 유지한다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            acc = record.name == "uvicorn.access"
            if isinstance(record.msg, str):
                record.msg = _scrub_log(record.msg if record.args else _clip(record.msg, 4 * LOG_ARG_MAX), acc)
            if isinstance(record.args, tuple):  # 인자는 길이를 먼저 자른다(SEC-7: 긴 쿼리 한 줄로 필터 시간 키우기 방어)
                record.args = tuple(_scrub_log(_clip(a), acc) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: _scrub_log(_clip(v), acc) if isinstance(v, str) else v for k, v in record.args.items()}
            if record.exc_info:
                exc = record.exc_info[1]
                note = f" [트레이스 생략: {type(exc).__name__ if exc else '?'}]"
                record.exc_info = None
                record.exc_text = None
                if isinstance(record.msg, str):
                    record.msg = record.msg + note
            record.stack_info = None
            if not acc:  # 인자를 합쳐야 드러나는 키(접근 로그는 인자 구조를 지키고 인자별로 이미 가렸다)
                msg = record.getMessage()
                clean = _scrub_log(_clip(msg, 4 * LOG_ARG_MAX), acc)
                if clean != msg:
                    record.msg, record.args = clean, None
        except Exception:  # noqa: BLE001 - 로그 필터가 로그를 막지 않게
            pass
        return True


_FILTER = RedactingFilter()
_LOGGER_NAMES = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "neumann", "neumann.api", "neumann.serving",
                 "asyncio", "fastapi")


def install_log_filter() -> None:
    """이미 있는 핸들러와 주요 로거에 RedactingFilter를 붙인다(여러 번 불러도 한 번만 붙는다)."""
    for name in _LOGGER_NAMES:
        lg = logging.getLogger(name)
        if _FILTER not in lg.filters:
            lg.addFilter(_FILTER)
        for h in lg.handlers:
            if _FILTER not in h.filters:
                h.addFilter(_FILTER)


def ensure_log_handler() -> None:
    """uvicorn 기본 설정은 neumann.* INFO 로그를 어디에도 내보내지 않는다. 핸들러가 없으면 하나 붙인다(필터 포함)."""
    lg = logging.getLogger("neumann")
    if lg.handlers or logging.getLogger().handlers:
        return
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    h.addFilter(_FILTER)
    lg.addHandler(h)
    if lg.level == logging.NOTSET:
        lg.setLevel(logging.INFO)


IPV6_GROUP_PREFIX = 56  # SEC-7: /64 → /56(가정 가입자 하나가 흔히 /56을 받는다. 근거는 docs/reports/SEC-7.md)


def ip_key(ip: str) -> str:
    """속도 제한·로그용 IP 묶음. IPv6는 /56(가입자 하나가 /56~/48을 받으면 /64마다 새 통이 생기던 문제),
    IPv4-매핑은 IPv4로."""
    try:
        addr = ipaddress.ip_address(ip.strip().strip("[]").split("%")[0])
    except ValueError:
        return ip
    if addr.version == 6:
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/{IPV6_GROUP_PREFIX}", strict=False))
    return str(addr)


_IP_SALT: bytes | None = None


def _ip_salt() -> bytes:
    """로그 IP 해시용 솔트: NEUMANN_PSEUDONYM_SALT(있으면, 값은 어디에도 쓰지 않는다) 또는 프로세스마다 무작위."""
    global _IP_SALT
    if _IP_SALT is None:
        env = os.getenv("NEUMANN_PSEUDONYM_SALT")
        _IP_SALT = env.encode("utf-8") if env and env.strip() else os.urandom(16)
    return _IP_SALT


def _ip_tag(ip: str) -> str:
    """로그용 IP 표시: 솔트를 섞은 HMAC 앞 10자(같은 IP끼리 묶어 볼 수만 있고, 전수 대입으로 되돌릴 수 없다)."""
    return "ip_" + hmac.new(_ip_salt(), ip_key(ip).encode("utf-8"), hashlib.sha256).hexdigest()[:10]


# ───────────────────────── plan_id ─────────────────────────


def plan_key(plan_text: str) -> str:
    """PlanDocument.from_text와 같은 plan_id(정규화 → 이메일·ORCID 가림 → sha256)."""
    try:
        from neumann.models import normalize_text, redact_pii

        body = redact_pii(normalize_text(plan_text))
    except Exception:  # noqa: BLE001 - models가 없거나 실패하면 줄바꿈만 맞춘다
        body = plan_text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(body.encode("utf-8", "surrogatepass")).hexdigest()


def public_plan_ids(paths: Any) -> list[str]:
    """공개 입력(데모·템플릿 파일)의 plan_id. 디스크 캐시 허용 목록."""
    out = []
    for p in paths:
        try:
            out.append(plan_key(Path(p).read_text(encoding="utf-8")))
        except OSError:
            continue
    return out


# ───────────────────────── 요청 문맥 ─────────────────────────


@dataclass
class RequestCtx:
    ticket: str
    ip: str = "internal"
    path: str = ""
    kind: str = "analysis"
    mode: str = "analysis"        # analysis | aux
    started: float = field(default_factory=time.monotonic)
    plan_id: str = ""
    chars: int = 0
    cache: str = "miss"           # miss | hit | off
    queue: str = "none"           # none | queued | joined
    reservation: Ticket | None = None
    budget_spent: bool = False
    position_at_arrival: int = 0
    waited_s: float = 0.0
    run_s: float = 0.0
    error_kind: str | None = None  # timeout | internal | refused | None
    internal: bool = False         # 예열 등 서버 내부 실행(입장 검사 대신 force 예약)
    refusal: tuple[int, str, str, int] | None = None  # run()이 거절했을 때 (HTTP 코드, error_code, 문구, retry 초)
    upload_key: str | None = None  # 업로드 IP별 동시 처리 수를 센 키(반납 전까지)
    task_started: bool = False     # 보조 관문에서 하위 앱 작업을 시작했는가


_CTX: contextvars.ContextVar[RequestCtx | None] = contextvars.ContextVar("neumann_serving_ctx", default=None)


def current_request() -> RequestCtx | None:
    return _CTX.get()


# ───────────────────────── 속도 제한·예산 ─────────────────────────


class RateLimiter:
    """IP별 슬라이딩 창. limit<=0이면 끈다."""

    def __init__(self, limit: int, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> tuple[bool, float]:
        """(허용?, 다시 시도까지 초). 허용이면 1건을 센다."""
        if self.limit <= 0:
            return True, 0.0
        now = self.clock()
        dq = self._hits.setdefault(key, deque())
        while dq and now - dq[0] >= self.window_s:
            dq.popleft()
        if len(dq) >= self.limit:
            return False, max(self.window_s - (now - dq[0]), 0.0)
        dq.append(now)
        if len(self._hits) > 10_000:
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window_s}
        return True, 0.0


class DailyBudget:
    """전역 일일 새 분석 건수 상한. 날짜(서버 현지)가 바뀌면 0부터. 재시작해도 이어지게 파일에 남긴다."""

    def __init__(self, limit: int, path: Path | None, today: Callable[[], str] | None = None) -> None:
        self.limit, self.path = limit, path
        self.today = today or (lambda: time.strftime("%Y-%m-%d"))
        self.day, self.used = self.today(), 0
        if path is not None and path.is_file():
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                if d.get("day") == self.day:
                    self.used = int(d.get("used", 0))
            except (OSError, ValueError, TypeError):
                log.warning("예산 파일을 읽지 못해 0부터 센다")

    def _roll(self) -> None:
        t = self.today()
        if t != self.day:
            self.day, self.used = t, 0

    def exhausted(self) -> bool:
        if self.limit <= 0:
            return False
        self._roll()
        return self.used >= self.limit

    def spend(self, n: int = 1) -> None:
        self._roll()
        self.used = max(self.used + n, 0)
        self._save()

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
            tmp.write_text(json.dumps({"day": self.day, "used": self.used}), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("예산 파일 쓰기 실패 (%s)", type(exc).__name__)

    def status(self) -> dict[str, Any]:
        self._roll()
        return {"limit": self.limit, "used": self.used, "day": self.day,
                "remaining": max(self.limit - self.used, 0) if self.limit > 0 else None}


# ───────────────────────── 동시 상한·대기열 ─────────────────────────


class QueueFull(Exception):
    def __init__(self, retry_after_s: float) -> None:
        super().__init__("queue full")
        self.retry_after_s = retry_after_s


@dataclass
class Ticket:
    id: str
    plan_id: str = ""
    state: str = "waiting"        # waiting | running | done | cancelled
    enq_at: float = field(default_factory=time.monotonic)
    start_at: float | None = None
    end_at: float | None = None
    event: asyncio.Event | None = None
    owner: str = ""               # IP 묶음 키(SEC-7: IP별 자리 수 상한). 빈 값이면 세지 않는다(예열 등 내부)


class Gate:
    """동시 실행 상한 + FIFO 대기열(대기 수 상한). 이벤트 루프 하나에서만 쓴다."""

    def __init__(self, max_active: int, max_waiting: int, avg_run_s: float, name: str = "analysis") -> None:
        self.max_active, self.max_waiting, self.name = max_active, max_waiting, name
        self.avg_run_s = avg_run_s
        self._waiting: OrderedDict[str, Ticket] = OrderedDict()
        self._running: dict[str, Ticket] = {}
        self._recent: OrderedDict[str, Ticket] = OrderedDict()
        self.completed = 0
        self._owners: dict[str, int] = {}  # IP 묶음별 잡은 자리(실행+대기) 수(SEC-7)

    # 입장 ------------------------------------------------------------
    def reserve(self, ticket_id: str, plan_id: str = "", *, force: bool = False, owner: str = "") -> Ticket:
        """대기열에 자리를 잡는다. 빈 슬롯이면 바로 running. 꽉 찼으면 QueueFull(force면 무시: 예열 등 내부 작업)."""
        if not force and len(self._running) + len(self._waiting) >= self.max_active + self.max_waiting:
            raise QueueFull(self.eta(len(self._waiting) + 1))
        if ticket_id in self._waiting or ticket_id in self._running:
            ticket_id = f"{ticket_id}-{uuid.uuid4().hex[:6]}"
        t = Ticket(id=ticket_id, plan_id=plan_id, owner=owner)
        if owner:
            self._owners[owner] = self._owners.get(owner, 0) + 1
        self._waiting[t.id] = t
        self._dispatch()
        return t

    def held(self, owner: str) -> int:
        """그 IP 묶음이 지금 잡고 있는 자리(실행+대기) 수."""
        return self._owners.get(owner, 0)

    def share_refusal(self, owner: str, per_owner: int, reserve: int) -> int | None:
        """IP별 몫 검사(SEC-7, M-1). 거절이면 그 IP가 잡은 자리 수, 받으면 None.

        - 한 IP 묶음은 자리를 ``per_owner``개까지만 잡는다.
        - 이미 자리를 가진 IP는 남은 자리가 ``reserve``개 이하로 줄면 더 못 잡는다(처음 오는 사용자 몫).
          IP 몇 개로 대기열을 채워 다른 사용자를 밀어내지 못하게 한다. 처음 오는 IP(잡은 자리 0)는 이 검사를 받지 않는다.
        """
        n = self.held(owner) if owner else 0
        if n <= 0:
            return None
        if per_owner > 0 and n >= per_owner:
            return n
        free = self.max_active + self.max_waiting - len(self._running) - len(self._waiting)
        if reserve > 0 and free <= reserve:
            return n
        return None

    def _release_owner(self, t: Ticket) -> None:
        if t.owner:
            n = self._owners.get(t.owner, 0) - 1
            if n > 0:
                self._owners[t.owner] = n
            else:
                self._owners.pop(t.owner, None)

    def has_plan(self, plan_id: str) -> bool:
        return any(t.plan_id == plan_id for t in (*self._waiting.values(), *self._running.values()))

    def ticket_for_plan(self, plan_id: str) -> Ticket | None:
        """그 계획서의 실행 중 자리(없으면 대기 중 자리). 작업(jobs) 상태 조회용(E4-L2d)."""
        for t in self._running.values():
            if t.plan_id == plan_id:
                return t
        for t in self._waiting.values():
            if t.plan_id == plan_id:
                return t
        return None

    async def acquire(self, t: Ticket) -> None:
        """차례가 올 때까지 기다린다. 취소되면 자리를 비운다."""
        self._dispatch()
        if t.state == "running":
            return
        t.event = t.event or asyncio.Event()
        try:
            await t.event.wait()
        except BaseException:
            self.cancel(t)
            raise

    def release(self, t: Ticket, run_s: float | None = None) -> None:
        if self._running.pop(t.id, None) is not None:
            t.state, t.end_at = "done", time.monotonic()
            self._release_owner(t)
            self.completed += 1
            if run_s is not None and run_s > 0:
                self.avg_run_s = 0.7 * self.avg_run_s + 0.3 * run_s
            self._remember(t)
        self._dispatch()

    def cancel(self, t: Ticket) -> None:
        """쓰지 않은 자리를 돌려준다(대기 중이든, 잡아 둔 슬롯이든)."""
        if self._waiting.pop(t.id, None) is not None or self._running.pop(t.id, None) is not None:
            t.state = "cancelled"
            self._release_owner(t)
            self._remember(t)
        self._dispatch()

    def _remember(self, t: Ticket) -> None:
        self._recent[t.id] = t
        while len(self._recent) > 500:
            self._recent.popitem(last=False)

    def _dispatch(self) -> None:
        while self._waiting and len(self._running) < self.max_active:
            _, t = self._waiting.popitem(last=False)
            t.state, t.start_at = "running", time.monotonic()
            self._running[t.id] = t
            if t.event is not None:
                t.event.set()

    # 상태 ------------------------------------------------------------
    @property
    def active(self) -> int:
        return len(self._running)

    @property
    def waiting(self) -> int:
        return len(self._waiting)

    def knows(self, ticket_id: str) -> bool:
        return ticket_id in self._waiting or ticket_id in self._running or ticket_id in self._recent

    def position(self, ticket_id: str) -> int:
        """대기 순번(1부터). 대기 중이 아니면 0."""
        for i, tid in enumerate(self._waiting, start=1):
            if tid == ticket_id:
                return i
        return 0

    def eta(self, position: int) -> float:
        """대기 순번 position(1부터)의 예상 대기 시간(초). 슬롯이 비는 순서를 흉내 낸다."""
        if position <= 0:
            return 0.0
        now = time.monotonic()
        slots = [max(self.avg_run_s - (now - (r.start_at or now)), 1.0) for r in self._running.values()]
        slots += [0.0] * max(self.max_active - len(slots), 0)
        heapq.heapify(slots)
        t = 0.0
        for _ in range(position):
            t = heapq.heappop(slots)
            heapq.heappush(slots, t + self.avg_run_s)
        return round(t, 1)

    def ticket_status(self, ticket_id: str) -> dict[str, Any]:
        now = time.monotonic()
        if ticket_id in self._waiting:
            pos = self.position(ticket_id)
            t = self._waiting[ticket_id]
            return {"id": ticket_id, "state": "waiting", "position": pos, "ahead": pos - 1,
                    "eta_s": self.eta(pos), "waited_s": round(now - t.enq_at, 1), "gate": self.name}
        if ticket_id in self._running:
            t = self._running[ticket_id]
            el = now - (t.start_at or now)
            return {"id": ticket_id, "state": "running", "position": 0, "ahead": 0,
                    "eta_s": round(max(self.avg_run_s - el, 1.0), 1), "running_s": round(el, 1), "gate": self.name}
        if ticket_id in self._recent:
            return {"id": ticket_id, "state": self._recent[ticket_id].state, "position": 0, "ahead": 0, "eta_s": 0.0,
                    "gate": self.name}
        return {"id": ticket_id, "state": "unknown", "position": 0, "ahead": 0, "eta_s": None}

    def summary(self) -> dict[str, Any]:
        return {"active": self.active, "waiting": self.waiting, "max_active": self.max_active,
                "max_waiting": self.max_waiting}


# ───────────────────────── 결과 캐시 ─────────────────────────


def _strip_plan_body(result: dict[str, Any]) -> dict[str, Any]:
    """저장본: plan.lines 텍스트를 빼고(PremortemResult.dump_persisted와 같은 규칙) plan_stats.lines의 글도 뺀다."""
    data = copy.deepcopy(result)
    plan = data.get("plan")
    if isinstance(plan, dict):
        lines = plan.get("lines")
        data["plan"] = {"plan_id": plan.get("plan_id"), "session_id": plan.get("session_id"),
                        "n_lines": len(lines) if isinstance(lines, list) else plan.get("n_lines")}
    ps = data.get("plan_stats")
    if isinstance(ps, dict) and isinstance(ps.get("lines"), list):
        ps["lines"] = [{k: v for k, v in ln.items() if k not in {"t", "text"}} if isinstance(ln, dict) else None
                       for ln in ps["lines"]]
    return data


def _restore_plan_body(data: dict[str, Any], plan_text: str) -> dict[str, Any]:
    """캐시 저장본 + 요청 본문 → 줄 텍스트를 다시 붙인 결과."""
    plan = data.get("plan")
    session_id = (plan.get("session_id") if isinstance(plan, dict) else None) or data.get("session_id") or "cache"
    try:
        from neumann.models import PlanDocument

        doc = PlanDocument.from_text(plan_text, str(session_id))
    except Exception:  # noqa: BLE001 - models가 없으면 줄 텍스트 없이 돌려준다
        return data
    if doc.plan_id != data.get("plan_id") and isinstance(plan, dict) and plan.get("plan_id") != doc.plan_id:
        return data
    if isinstance(plan, dict):
        data["plan"] = doc.model_dump(mode="json")
    texts = [ln.text for ln in doc.lines]
    ps = data.get("plan_stats")
    if isinstance(ps, dict) and isinstance(ps.get("lines"), list):
        out = []
        for i, ln in enumerate(ps["lines"], start=1):
            if isinstance(ln, dict):
                n = ln.get("n") or ln.get("no") or i
                ln = {**ln, "t": texts[n - 1] if isinstance(n, int) and 0 < n <= len(texts) else ""}
            out.append(ln)
        ps["lines"] = out
    return data


class ResultCache:
    """plan_id → 결과(줄 텍스트 뺀 저장본).

    - 메모리: TTL·개수 상한(LRU). 사용자 입력은 여기에만 있다.
    - 디스크: ``disk_allow``(공개 입력 plan_id)만 쓴다·읽는다. 사용자 입력은 파일로 남지 않는다.
    """

    def __init__(self, directory: Path | None, *, enabled: bool, mem_items: int = 64, variant: str = "default",
                 statuses: tuple[str, ...] = ("ok",), ttl_s: float = 6 * 3600.0,
                 disk_allow: frozenset[str] | set[str] = frozenset(),
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.dir, self.enabled, self.mem_items = directory, enabled, mem_items
        self.variant, self.statuses, self.ttl_s = variant, statuses, ttl_s
        self.disk_allow = frozenset(disk_allow)
        self.clock = clock
        self._mem: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self.hits = self.misses = self.stores = self.disk_stores = 0

    def _path(self, plan_id: str) -> Path | None:
        if self.dir is None or not _PLAN_ID_RE.match(plan_id) or plan_id not in self.disk_allow:
            return None
        return self.dir / f"{plan_id}.json"

    def get(self, plan_id: str) -> dict[str, Any] | None:
        if not self.enabled or not plan_id:
            return None
        item = self._mem.get(plan_id)
        if item is not None:
            if self.clock() - item[0] <= self.ttl_s:
                self._mem.move_to_end(plan_id)
                return item[1]
            del self._mem[plan_id]
        path = self._path(plan_id)
        if path is None or not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("결과 캐시 읽기 실패 plan_id=%s (%s)", plan_id[:12], type(exc).__name__)
            return None
        if not isinstance(entry, dict) or entry.get("variant") != self.variant or not isinstance(entry.get("result"), dict):
            return None
        self._remember(plan_id, entry)
        return entry

    def has(self, plan_id: str) -> bool:
        return self.get(plan_id) is not None

    def put(self, plan_id: str, result: dict[str, Any]) -> bool:
        if not self.enabled or not plan_id:
            return False
        if result.get("sample") or result.get("status") not in self.statuses:
            return False
        entry = {"variant": self.variant, "plan_id": plan_id,
                 "cached_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "result": _strip_plan_body(result)}
        self._remember(plan_id, entry)
        self.stores += 1
        path = self._path(plan_id)
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
                tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, path)
                self.disk_stores += 1
            except OSError as exc:
                log.warning("결과 캐시 쓰기 실패 plan_id=%s (%s)", plan_id[:12], type(exc).__name__)
        return True

    def _remember(self, plan_id: str, entry: dict[str, Any]) -> None:
        if self.mem_items <= 0:
            return
        self._mem[plan_id] = (self.clock(), entry)
        self._mem.move_to_end(plan_id)
        while len(self._mem) > self.mem_items:
            self._mem.popitem(last=False)

    @property
    def memory_items(self) -> int:
        return len(self._mem)

    @staticmethod
    def restore(entry: dict[str, Any], plan_text: str) -> dict[str, Any]:
        return _restore_plan_body(copy.deepcopy(entry["result"]), plan_text)


# ───────────────────────── 서빙 상태 ─────────────────────────


class AnalysisTimeout(Exception):
    """요청 시간 상한 초과(분석 자체는 계속 돈다)."""


class AdmissionRefused(Exception):
    """새 분석 입장 거절(차단·속도 제한·예산·대기열). 미들웨어가 ctx.refusal로 사용자 문구 응답을 만든다."""


def _to_jsonable(result: Any) -> dict[str, Any]:
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        result = dump(mode="json")
    from fastapi.encoders import jsonable_encoder

    out = jsonable_encoder(result)
    if not isinstance(out, dict):
        raise TypeError("pipeline result is not a dict")
    return out


def _default_pipeline() -> Callable[..., Any] | None:
    try:
        fn = getattr(importlib.import_module("neumann.pipeline"), "run_premortem", None)
    except Exception as exc:  # noqa: BLE001
        log.warning("예열: 파이프라인 import 실패 (%s)", type(exc).__name__)
        return None
    return fn if callable(fn) else None


class Serving:
    def __init__(self, config: ServingConfig | None = None) -> None:
        self.config = config or ServingConfig.from_env()
        c = self.config
        self.gate = Gate(c.max_concurrent, c.queue_max, c.avg_run_s, "analysis")
        self.aux_gate = Gate(c.aux_concurrent, c.aux_queue_max, min(c.aux_timeout_s, 10.0), "aux")
        self.limiter = RateLimiter(c.rate_per_min, c.rate_window_s)
        self.preparse_limiter = RateLimiter(c.preparse_per_min, c.rate_window_s)  # 본문 파싱·해시 전 값싼 검사
        self.aux_limiter = RateLimiter(c.aux_rate_per_min, c.rate_window_s)
        self.upload_limiter = RateLimiter(c.upload_rate_per_min, c.rate_window_s)
        self.get_limiter = RateLimiter(c.get_rate_per_min, c.rate_window_s)  # SEC-7: 보호 POST·작업 폴링 밖 요청
        self.upload_active: dict[str, int] = {}  # IP 묶음별 처리 중인 업로드 수
        self.budget = DailyBudget(c.daily_budget, c.budget_file if c.daily_budget > 0 else None)
        self.cache = ResultCache(c.cache_dir, enabled=c.cache_enabled, mem_items=c.cache_mem_items,
                                 variant=c.cache_variant, statuses=c.cache_statuses, ttl_s=c.cache_ttl_s,
                                 disk_allow=c.disk_allow)
        self.inflight: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.counters = {"requests": 0, "cache_hits": 0, "joined": 0, "busy_503": 0, "rate_429": 0, "too_large_413": 0,
                         "budget_503": 0, "blocked_503": 0, "timeout_504": 0, "error_5xx": 0}
        self.warmup_state: dict[str, Any] = {"state": "off" if not c.warmup else "pending", "plans": 0, "cached": 0,
                                             "failed": 0}
        self._warm_task: asyncio.Task[Any] | None = None
        # 코드가 등록하는 보호 경로(E4-L2d: POST /premortem/jobs). 설정(NEUMANN_PROTECTED_PATHS)보다 우선한다.
        self.extra_protected: dict[str, str] = {}
        self.async_paths: set[str] = set()  # 응답을 기다리지 않는 경로(작업 방식): 대기열 전체(queue_max)를 쓴다
        self.accept_checks: list[Callable[[], bool]] = []  # 새 분석을 받을 수 있나(작업 저장소 가득 등, /queue/status)

    def protect(self, path: str, kind: str = "analysis", *, async_: bool = False) -> None:
        """경로를 보호 경로로 등록한다. 설정으로 빼거나 다른 종류로 바꿀 수 없다(우회 경로 방지)."""
        key = path.rstrip("/") or "/"
        self.extra_protected[key] = kind if kind in KINDS else "gated"
        if async_:
            self.async_paths.add(key)

    def sync_wait_full(self, ctx: RequestCtx) -> bool:
        """동기 경로 요청인데 대기가 동기 상한 이상이면 True(응답 하나가 터널 시간 상한을 넘지 않게)."""
        lim = self.config.sync_queue_max
        return lim > 0 and (ctx.path.rstrip("/") or "/") not in self.async_paths and self.gate.waiting >= lim

    def kind_for(self, path: str) -> str | None:
        key = path.rstrip("/") or "/"
        return self.extra_protected.get(key) or self.config.protected.get(key)

    def admit_new(self, ctx: RequestCtx) -> tuple[int, str, str, int] | None:
        """새 분석 입장 검사: 차단 스위치 → IP 묶음 속도 제한 → 일일 예산 → IP별 대기열 몫(SEC-7) → 대기열.

        입장이면 None(대기열 자리를 잡고 예산 1건을 뗀다. 쓰지 않으면 _drop_reservation이 돌려준다).
        거절이면 (HTTP 코드, error_code, 사용자 문구, retry 초).
        """
        cfg = self.config
        if self.blocked():
            self.counters["blocked_503"] += 1
            return 503, "blocked", user_message("blocked"), 600
        ok, retry = self.limiter.hit(ip_key(ctx.ip))
        if not ok:
            self.counters["rate_429"] += 1
            r = max(int(math.ceil(retry)), 1)
            return 429, "rate_limited", user_message("rate", retry=r, limit=cfg.rate_per_min), r
        if self.budget.exhausted():
            self.counters["budget_503"] += 1
            return 503, "budget_exhausted", user_message("budget", limit=cfg.daily_budget), 3600
        if self.sync_wait_full(ctx):
            self.counters["busy_503"] += 1
            r = max(int(math.ceil(min(self.gate.eta(self.gate.waiting + 1), 600))), 5)
            return 503, "busy", user_message("busy", retry=r), r
        owner = ip_key(ctx.ip)
        held = self.gate.share_refusal(owner, cfg.queue_per_ip, cfg.queue_reserve)  # SEC-7: IP별 대기열 몫
        if held is not None:
            self.counters["rate_429"] += 1
            return 429, "busy_ip", user_message("queue_ip", n=held), 30
        try:
            ctx.reservation = self.gate.reserve(ctx.ticket, ctx.plan_id, owner=owner)
        except QueueFull as exc:
            self.counters["busy_503"] += 1
            r = max(int(math.ceil(min(exc.retry_after_s, 600))), 5)
            return 503, "busy", user_message("busy", retry=r), r
        ctx.position_at_arrival = self.gate.position(ctx.reservation.id)
        self.budget.spend()
        ctx.budget_spent = True
        return None

    def release_upload(self, ctx: RequestCtx) -> None:
        """업로드 IP별 동시 처리 수를 돌려준다(여러 번 불러도 한 번만)."""
        key, ctx.upload_key = ctx.upload_key, None
        if key is not None:
            n = self.upload_active.get(key, 0) - 1
            if n > 0:
                self.upload_active[key] = n
            else:
                self.upload_active.pop(key, None)

    def blocked(self) -> bool:
        """차단 스위치: 환경변수(NEUMANN_BLOCK_NEW) 또는 파일 플래그가 있으면 새 분석을 받지 않는다."""
        c = self.config
        return c.block_new or bool(c.block_file is not None and c.block_file.exists())

    # 파이프라인 감싸기 -----------------------------------------------------
    def wrap_pipeline(self, fn: Callable[..., Any]) -> Callable[..., Awaitable[dict[str, Any]]]:
        raw = getattr(fn, "__wrapped_pipeline__", fn)
        try:
            takes_filename = "filename" in inspect.signature(raw).parameters
        except (TypeError, ValueError):
            takes_filename = False

        async def serving_pipeline(plan_text: str, filename: str | None = None) -> dict[str, Any]:
            kwargs = {"filename": filename} if takes_filename else {}
            return await self.run(raw, plan_text, **kwargs)

        serving_pipeline.__wrapped_pipeline__ = raw  # type: ignore[attr-defined]
        return serving_pipeline

    async def run(self, fn: Callable[..., Any], plan_text: str, *, timeout_s: float | None = None,
                  **kwargs: Any) -> dict[str, Any]:
        """캐시 → 같은 계획서 합류 → 대기열·실행. ``timeout_s``를 주면 요청 시간 상한 대신 그 값(작업 방식)."""
        ctx = current_request() or RequestCtx(ticket="int_" + uuid.uuid4().hex[:12])
        pid = ctx.plan_id or plan_key(plan_text)
        ctx.plan_id, ctx.chars = pid, len(plan_text)
        entry = self.cache.get(pid)
        if entry is not None:
            self._drop_reservation(ctx)
            ctx.cache = "hit"
            self.cache.hits += 1
            self.counters["cache_hits"] += 1
            return await asyncio.to_thread(self.cache.restore, entry, plan_text)
        ctx.cache = "miss" if self.cache.enabled else "off"
        self.cache.misses += 1
        job = self.inflight.get(pid)
        if job is None:
            if ctx.reservation is None:
                # 미들웨어가 자리를 잡지 않은 실행: 두 번째 방어선. 예열(internal)만 검사 없이 force로 들어간다.
                if ctx.internal:
                    ctx.reservation = self.gate.reserve(ctx.ticket, pid, force=True)
                    self.budget.spend()
                else:
                    refusal = self.admit_new(ctx)
                    if refusal is not None:
                        ctx.refusal, ctx.error_kind = refusal, "refused"
                        raise AdmissionRefused(refusal[1])
            t = ctx.reservation
            assert t is not None
            ctx.reservation, ctx.budget_spent = None, False
            t.plan_id = pid
            ctx.position_at_arrival = ctx.position_at_arrival or self.gate.position(t.id)
            job = asyncio.ensure_future(self._job(fn, plan_text, kwargs, t, pid, ctx))
            self.inflight[pid] = job
            job.add_done_callback(lambda j, pid=pid: self._job_done(pid, j))
            ctx.queue = "queued"
        else:
            self._drop_reservation(ctx)
            ctx.queue = "joined"
            self.counters["joined"] += 1
        limit = self.config.request_timeout_s if timeout_s is None else timeout_s
        remaining = limit - (time.monotonic() - ctx.started)
        try:
            result = await asyncio.wait_for(asyncio.shield(job), timeout=max(remaining, 0.01))
        except asyncio.TimeoutError:
            ctx.error_kind = "timeout"
            raise AnalysisTimeout("request time limit") from None
        return copy.deepcopy(result)

    def _drop_reservation(self, ctx: RequestCtx) -> None:
        """쓰지 않은 자리와 미리 뗀 예산을 돌려준다."""
        if ctx.reservation is not None:
            (self.aux_gate if ctx.mode == "aux" else self.gate).cancel(ctx.reservation)
            ctx.reservation = None
        if ctx.budget_spent:
            self.budget.spend(-1)
            ctx.budget_spent = False

    async def _job(self, fn: Callable[..., Any], plan_text: str, kwargs: dict[str, Any], t: Ticket, pid: str,
                   ctx: RequestCtx) -> dict[str, Any]:
        await self.gate.acquire(t)
        t0 = time.monotonic()
        ctx.waited_s = round(t0 - t.enq_at, 3)
        ok = False
        try:
            if inspect.iscoroutinefunction(fn):
                res = await fn(plan_text, **kwargs)
            else:
                res = await asyncio.to_thread(fn, plan_text, **kwargs)
            data = _to_jsonable(res)
            ok = True
        finally:
            run_s = time.monotonic() - t0
            ctx.run_s = round(run_s, 3)
            self.gate.release(t, run_s if ok else None)
        self.cache.put(pid, data)
        return data

    def _job_done(self, pid: str, job: asyncio.Future[Any]) -> None:
        if self.inflight.get(pid) is job:
            self.inflight.pop(pid, None)
        if not job.cancelled() and job.exception() is not None:  # 받아 가는 쪽이 없어도 경고 로그(트레이스)가 안 나게
            log.info("분석 실패 plan_id=%s kind=%s", pid[:12], type(job.exception()).__name__)

    # 상태 ------------------------------------------------------------
    def queue_status(self, ticket: str | None = None) -> dict[str, Any]:
        g = self.gate
        out: dict[str, Any] = {
            **g.summary(),
            "avg_run_s": round(g.avg_run_s, 1), "eta_new_s": g.eta(g.waiting + 1) if g.active >= g.max_active else 0.0,
            "accepting": g.active + g.waiting < g.max_active + g.max_waiting and not self.blocked()
            and not self.budget.exhausted() and all(check() for check in self.accept_checks),
            "blocked": self.blocked(),
            "aux": self.aux_gate.summary(),
            "limits": self.config.public_view(),
        }
        if not self.config.public:  # 공개 프로필은 운영 수치(카운터·캐시·예열)를 내보내지 않는다. 예산 수치는 항상 뺀다
            out.update({
                "counters": dict(self.counters, completed=g.completed),
                "cache": {"enabled": self.cache.enabled, "memory_items": self.cache.memory_items,
                          "hits": self.cache.hits, "stores": self.cache.stores},
                "warmup": dict(self.warmup_state),
            })
        if ticket:
            if not _TICKET_RE.match(ticket):
                out["ticket"] = {"id": "", "state": "unknown"}
            else:
                gate = self.aux_gate if self.aux_gate.knows(ticket) and not g.knows(ticket) else g
                out["ticket"] = gate.ticket_status(ticket)
        return out

    # 예열 ------------------------------------------------------------
    async def warmup(self, pipeline: Callable[..., Any] | None = None) -> dict[str, Any]:
        """색인·모델 로드(파이프라인 모듈의 warmup 훅이 있으면) + 데모 계획서 결과를 캐시에 채운다."""
        ws = self.warmup_state
        ws.update(state="running", plans=len(self.config.warmup_plans), cached=0, failed=0)
        fn = pipeline or _default_pipeline()
        if fn is None:
            ws.update(state="skipped", reason="pipeline unavailable")
            log.info("예열 건너뜀: 파이프라인 없음")
            return dict(ws)
        fn = getattr(fn, "__wrapped_pipeline__", fn)
        try:
            hook = getattr(importlib.import_module(fn.__module__), "warmup", None)
        except Exception:  # noqa: BLE001
            hook = None
        if callable(hook):
            t0 = time.monotonic()
            try:
                await (hook() if inspect.iscoroutinefunction(hook) else asyncio.to_thread(hook))
                log.info("예열: 모델·색인 로드 %.1fs", time.monotonic() - t0)
            except Exception as exc:  # noqa: BLE001
                log.warning("예열: warmup 훅 실패 (%s)", type(exc).__name__)
        for path in self.config.warmup_plans:
            try:
                text = Path(path).read_text(encoding="utf-8")
            except OSError as exc:
                ws["failed"] += 1
                log.warning("예열: 계획서 읽기 실패 %s (%s)", Path(path).name, type(exc).__name__)
                continue
            pid = plan_key(text)
            if self.cache.has(pid):
                ws["cached"] += 1
                continue
            if self.blocked() or self.budget.exhausted():
                ws["failed"] += 1
                log.info("예열: 차단 스위치·예산 때문에 plan_id=%s 건너뜀", pid[:12])
                continue
            t0 = time.monotonic()
            token = _CTX.set(RequestCtx(ticket="warm_" + pid[:12], path="warmup", internal=True))
            try:
                await self.run(fn, text)
                ws["cached"] += int(self.cache.has(pid))
                log.info("예열: plan_id=%s chars=%d %.1fs cache=%s", pid[:12], len(text), time.monotonic() - t0,
                         "stored" if self.cache.has(pid) else "not-stored")
            except Exception as exc:  # noqa: BLE001
                ws["failed"] += 1
                log.warning("예열: plan_id=%s 실패 (%s)", pid[:12], type(exc).__name__)
            finally:
                _CTX.reset(token)
        ws["state"] = "done"
        return dict(ws)

    def start_warmup(self, pipeline: Callable[..., Any] | None = None) -> None:
        """서버 시작 때 배경으로 예열한다(요청은 바로 받는다)."""
        if self.config.warmup and self._warm_task is None:
            self._warm_task = asyncio.ensure_future(self.warmup(pipeline))


_DEFAULT: Serving | None = None


def get_serving() -> Serving:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Serving()
    return _DEFAULT


def wrap_pipeline(fn: Callable[..., Any]) -> Callable[..., Awaitable[dict[str, Any]]]:
    """기본 Serving으로 파이프라인을 감싼다(main._load_pipeline에서 쓴다)."""
    return get_serving().wrap_pipeline(fn)


# ───────────────────────── 미들웨어 ─────────────────────────


def client_ip(scope: dict[str, Any], trust: str, pick: str = "first", use_xff: bool = True) -> str:
    """실제 클라이언트 IP. 터널(cloudflared)은 로컬(127.0.0.1)에서 들어오므로 그때만 프록시 헤더를 믿는다(trust=loopback).

    CF-Connecting-IP → 없으면 X-Forwarded-For(use_xff일 때만. 기본 첫 값, NEUMANN_XFF_PICK=last면 마지막 값)
    → 없으면 client.host. 공개 프로필은 use_xff=False(XFF는 클라이언트가 위조할 수 있다).
    trust=never면 헤더를 보지 않고, always면 peer와 무관하게 헤더를 믿는다.
    """
    peer = (scope.get("client") or ("unknown", 0))[0] or "unknown"
    if trust == "never":
        return peer
    if trust == "loopback":
        try:
            if not ipaddress.ip_address(peer).is_loopback:
                return peer
        except ValueError:
            if peer not in {"testclient", "localhost"}:
                return peer
    cf = (_header(scope, "cf-connecting-ip") or "").strip()
    if cf:
        # SEC-7: 올바른 IPv4/IPv6 하나만 믿는다. 쉼표 목록·이상한 값이면 peer로 보고 경고(값은 로그에 안 적는다)
        return cf if _valid_ip(cf) else _bad_ip_header("CF-Connecting-IP", peer)
    xff = [p.strip() for p in (_header(scope, "x-forwarded-for") or "").split(",") if p.strip()] if use_xff else []
    if xff:
        v = xff[-1] if pick == "last" else xff[0]
        return v if _valid_ip(v) else _bad_ip_header("X-Forwarded-For", peer)
    return peer


def _valid_ip(value: str) -> bool:
    """IPv4·IPv6 주소 하나인가(쉼표 목록·포트·대괄호·공백·범위 표기는 거절). IPv6 zone(%eth0)도 거절한다."""
    if not value or len(value) > 45 or "%" in value:
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


_BAD_IP_WARN = {"n": 0, "t": 0.0}


def _bad_ip_header(name: str, peer: str) -> str:
    """이상한 IP 헤더: peer 주소로 처리한다. 경고는 60초에 한 번(그 사이 건수를 붙여), 헤더 값은 적지 않는다."""
    _BAD_IP_WARN["n"] += 1
    now = time.monotonic()
    if now - _BAD_IP_WARN["t"] >= 60.0:
        log.warning("%s 값이 IP 주소 하나가 아니어서 연결 주소로 처리한다(최근 %d건)", name, _BAD_IP_WARN["n"])
        _BAD_IP_WARN.update(n=0, t=now)
    return peer


def _header(scope: dict[str, Any], name: str) -> str | None:
    key = name.lower().encode("latin-1")
    for k, v in scope.get("headers") or []:
        if k.lower() == key:
            return v.decode("latin-1")
    return None


_APP_BUSY_CODES = frozenset({"busy", "unavailable"})  # 앱이 503으로 돌려주는 사용자 안내(E4-L2d 작업 API)


def _err(code: str, message: str, ticket: str, **extra: Any) -> dict[str, Any]:
    """오류 본문. ``detail``은 FastAPI 기본 오류 모양을 읽는 화면(업로드 등)을 위해 같은 문구를 한 번 더 싣는다."""
    return {"status": "error", "error_code": code, "message": message, "detail": message, "request_id": ticket,
            "ticket": ticket, **extra}


def _upload_type_refusal(content_type: str | None) -> tuple[int, str] | None:
    """업로드 Content-Type 검사. 앱(upload.py)과 같은 python-multipart 파서를 쓴다. 거절이면 (코드, 문구)."""
    try:
        from python_multipart.multipart import parse_options_header

        ctype, params = parse_options_header(content_type)
        ok_type = ctype.strip().lower() == b"multipart/form-data"
        boundary = params.get(b"boundary")
    except Exception:  # noqa: BLE001 - 파서가 못 읽으면 거절(fail-closed)
        return 415, user_message("upload_type")
    if not ok_type:
        return 415, user_message("upload_type")
    if not boundary:
        return 400, user_message("upload_boundary")
    return None


def _is_validation_body(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("detail"), list) and all(
        isinstance(d, dict) and "loc" in d for d in data["detail"])


def _validation_fields(data: dict[str, Any]) -> list[dict[str, Any]]:
    """422 detail에서 입력(input)·ctx를 빼고 위치·종류만 남긴다(입력을 되돌려 보내지 않는다)."""
    out = []
    for d in data.get("detail", [])[:20]:
        loc = [x if isinstance(x, (int, str)) else str(x) for x in d.get("loc", [])][:6]
        out.append({"loc": loc, "type": str(d.get("type", ""))[:60], "msg": scrub_public(str(d.get("msg", ""))[:200])})
    return out


class ServingMiddleware:
    """보호 경로에 바이트·글자 상한, 차단 스위치, 속도 제한, 일일 예산, 대기열, 시간 상한, 오류 문구, 로그를 씌운다."""

    def __init__(self, app: Any, serving: Serving | None = None) -> None:
        self.app = app
        self.serving = serving or get_serving()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        cfg = self.serving.config
        early = self._precheck(scope, path)  # SEC-7: 요청 대상 길이(414)·보호 경로 밖 요청의 IP별 속도 제한(429)
        if early is not None:
            await self._send_early(send, *early)
            return
        if cfg.hide_docs and path in DOC_PATHS:
            body = json.dumps({"detail": user_message("not_found")}, ensure_ascii=False).encode("utf-8")
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode("latin-1"))]})
            await send({"type": "http.response.body", "body": body})
            return
        kind = self.serving.kind_for(path)
        if scope.get("method") != "POST" or kind is None:
            await self.app(scope, receive, send)
            return
        await self._handle(scope, receive, send, kind)

    def _precheck(self, scope: dict[str, Any], path: str) -> tuple[int, dict[str, Any], dict[str, str]] | None:
        """본문·앱을 부르기 전 값싼 검사(SEC-7).

        - 요청 대상(경로+쿼리)이 ``max_request_line`` 바이트를 넘으면 414(긴 쿼리 반복으로 로그 필터·라우팅 시간 키우기 방어).
        - 보호 POST(자기 관문이 있음)와 작업 폴링 GET(jobs의 폴링 상한)을 뺀 모든 요청(/health·정적 파일·/templates 등)에
          IP 묶음별 넉넉한 분당 상한(``get_rate_per_min``, 공개 600).
        """
        srv, cfg = self.serving, self.serving.config
        raw = scope.get("raw_path") or path.encode("utf-8", "surrogateescape")
        query = scope.get("query_string") or b""
        size = len(raw) + (1 + len(query) if query else 0)
        if cfg.max_request_line > 0 and size > cfg.max_request_line:
            rid = uuid.uuid4().hex[:16]
            return 414, _err("uri_too_long", user_message("uri_too_long", limit=cfg.max_request_line), rid), {
                "x-neumann-ticket": rid}
        method = scope.get("method", "GET")
        if cfg.get_rate_per_min <= 0 or (method == "POST" and srv.kind_for(path) is not None):
            return None
        if method == "GET" and JOB_POLL_PATH_RE.fullmatch(path):
            return None
        ok, retry = srv.get_limiter.hit(ip_key(client_ip(scope, cfg.trust_proxy, cfg.xff_pick, cfg.trust_xff)))
        if ok:
            return None
        srv.counters["rate_429"] += 1
        retry_s = max(int(math.ceil(retry)), 1)
        rid = uuid.uuid4().hex[:16]
        return 429, _err("rate_limited", user_message("rate", retry=retry_s, limit=cfg.get_rate_per_min), rid,
                         retry_after_s=retry_s), {"retry-after": str(retry_s), "x-neumann-ticket": rid}

    @staticmethod
    async def _send_early(send: Any, code: int, payload: dict[str, Any], headers: dict[str, str]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hs = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("latin-1")),
              (b"cache-control", b"no-store")]
        hs += [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
        await send({"type": "http.response.start", "status": code, "headers": hs})
        await send({"type": "http.response.body", "body": body})

    async def _handle(self, scope: dict[str, Any], receive: Any, send: Any, kind: str) -> None:
        srv, cfg = self.serving, self.serving.config
        raw_ticket = _header(scope, TICKET_HEADER) or ""
        ticket = raw_ticket if _TICKET_RE.match(raw_ticket) else uuid.uuid4().hex[:16]
        ctx = RequestCtx(ticket=ticket, ip=client_ip(scope, cfg.trust_proxy, cfg.xff_pick, cfg.trust_xff),
                         path=scope.get("path", ""), kind=kind)
        srv.counters["requests"] += 1
        limit = cfg.body_limit(kind)

        async def reply(code: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
            await self._send_json(send, code, payload, ctx, headers)
            self._log(ctx, code)

        def too_big() -> dict[str, Any]:
            srv.counters["too_large_413"] += 1
            return _err("too_large", user_message("too_large_bytes", limit_mb=round(limit / 1048576, 1),
                                                   chars=cfg.max_plan_chars), ticket)

        # 0) 업로드: 앱(upload.py)과 같은 파서로 Content-Type을 먼저 본다. multipart가 아니거나 경계가 없으면
        #    본문을 읽지 않고 앱과 같은 문구로 거절한다(fail-closed). 입장 검사는 본문 해석과 무관하게 모두 적용된다.
        if kind == "upload":
            refusal = _upload_type_refusal(_header(scope, "content-type"))
            if refusal is not None:
                await reply(refusal[0], _err("invalid_request", refusal[1], ticket))
                return

        # 0') 분석 경로: 본문을 읽고 해시(plan_key, 정규식)하기 전에 IP별 아주 넉넉한 사전 속도 검사(E4-L2d 재작업 2)
        if kind == "analysis":
            ok, retry = srv.preparse_limiter.hit(ip_key(ctx.ip))
            if not ok:
                await reply(*self._rate_reply(ctx, retry, cfg.preparse_per_min))
                return

        # 1) 바이트 상한: Content-Length 먼저, 그다음 스트리밍 누적(파싱 전)
        clen = _header(scope, "content-length")
        if clen and clen.strip().isdigit() and int(clen) > limit:
            await reply(413, too_big())
            return
        chunks, size = [], 0
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            chunk = msg.get("body", b"")
            size += len(chunk)
            if size > limit:
                await reply(413, too_big())
                return
            chunks.append(chunk)
            if not msg.get("more_body"):
                break
        body = b"".join(chunks)

        # 2) 종류 결정, 글자 수 상한, plan_id
        #    앱(FastAPI·Starlette)과 같은 파서로 읽는다: json.loads(bytes)는 BOM·UTF-16·UTF-32를 스스로 판별한다.
        #    분석 경로는 plan_text를 문자열로 못 읽으면 앱에 넘기지 않고 거절한다(fail-closed: 파서 차이로 관문 우회 금지).
        ctx.mode = "analysis" if kind == "analysis" else "aux"
        if kind == "export":
            from neumann.api.export import package_limit_refusal

            try:
                payload = json.loads(body) if body else None
            except (ValueError, UnicodeError, RecursionError, TypeError):
                payload = None  # 스키마 오류는 라우트가 처리한다.
            if isinstance(payload, dict):
                refusal = package_limit_refusal(payload, max_plan_lines=cfg.max_plan_lines,
                                                max_plan_chars=cfg.max_plan_chars)
                if refusal:
                    status, code, message = refusal
                    await reply(status, _err(code, message, ticket))
                    return
        if ctx.mode == "analysis":
            plan_text: str | None = None
            payload = None
            try:
                payload = json.loads(body) if body else None
                if isinstance(payload, dict) and isinstance(payload.get("plan_text"), str):
                    plan_text = payload["plan_text"]
                    ctx.chars = len(plan_text)
            except (ValueError, UnicodeError, RecursionError, TypeError):
                plan_text = None
            if plan_text is not None and ctx.chars > cfg.max_plan_chars:
                srv.counters["too_large_413"] += 1
                await reply(413, _err("too_large", user_message("too_large", limit=cfg.max_plan_chars, chars=ctx.chars),
                                      ticket))
                return
            try:
                check_payload_plan(payload, max_lines=cfg.max_plan_lines)
            except PlanLimitError as exc:
                await reply(exc.status_code, _err(exc.detail["error_code"], exc.message, ticket))
                return
            # 공백 없는 긴 토큰은 plan_key(이메일 정규식이 O(n²))·파이프라인을 부르기 전에 거절한다(E4-L2d 재작업).
            # 검사는 str.split(선형)뿐이고, plan_key(해시·정규식)는 이벤트 루프 밖(스레드)에서 계산한다.
            longest = longest_token(plan_text) if plan_text is not None else 0
            if longest > cfg.max_token_chars:
                await reply(422, _err("long_token", user_message("long_token", limit=cfg.max_token_chars,
                                                                 longest=longest), ticket))
                return
            # 줄 수 상한(SEC-7): 짧은 줄 수만 개는 글자 상한 안에서도 요청당 CPU(줄 모델·화면 조립·복사)를 크게 키운다
            if plan_text is not None and count_lines(plan_text) > cfg.max_plan_lines:
                await reply(422, _err("too_many_lines", user_message("too_many_lines", limit=cfg.max_plan_lines), ticket))
                return
            if plan_text is not None and plan_text.strip():
                ctx.plan_id = await asyncio.to_thread(plan_key, plan_text)
            if not ctx.plan_id:
                await reply(422, _err("invalid_request", user_message("invalid"), ticket))
                return

        # 3) 입장 관문
        if ctx.mode == "aux":
            key = ip_key(ctx.ip)
            if kind == "upload" and cfg.upload_per_ip > 0 and srv.upload_active.get(key, 0) >= cfg.upload_per_ip:
                srv.counters["rate_429"] += 1  # 한 IP가 느린 파일로 슬롯을 모두 잡지 못하게
                await reply(429, _err("busy_ip", user_message("busy_ip"), ticket, retry_after_s=10), {"retry-after": "10"})
                return
            limiter, lim = ((srv.upload_limiter, cfg.upload_rate_per_min) if kind == "upload"
                            else (srv.aux_limiter, cfg.aux_rate_per_min))
            ok, retry = limiter.hit(key)
            if not ok:
                await reply(*self._rate_reply(ctx, retry, lim))
                return
            try:
                ctx.reservation = srv.aux_gate.reserve(ticket)
                ctx.position_at_arrival = srv.aux_gate.position(ctx.reservation.id)
                if kind == "upload" and cfg.upload_per_ip > 0:
                    srv.upload_active[key] = srv.upload_active.get(key, 0) + 1
                    ctx.upload_key = key
            except QueueFull as exc:
                srv.counters["busy_503"] += 1
                retry_s = max(int(math.ceil(min(exc.retry_after_s, 600))), 5)
                await reply(503, _err("busy", user_message("busy_aux", retry=retry_s), ticket, retry_after_s=retry_s),
                            {"retry-after": str(retry_s)})
                return
        else:
            cached = srv.cache.has(ctx.plan_id)
            joining = ctx.plan_id in srv.inflight or srv.gate.has_plan(ctx.plan_id)
            if not cached and not joining:
                refusal = srv.admit_new(ctx)
                if refusal is not None:
                    await reply(*self._refusal_reply(ctx, refusal))
                    return

        # 4) 본문을 다시 흘려보내고 응답을 모은다
        sent = False

        async def replay() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        start: dict[str, Any] = {}
        out_chunks: list[bytes] = []

        async def capture(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                start.clear()
                start.update(message)
            elif message["type"] == "http.response.body":
                out_chunks.append(message.get("body", b""))

        token = _CTX.set(ctx)
        try:
            if ctx.mode == "analysis":
                await self.app(scope, replay, capture)
            else:
                await self._gated_call(scope, replay, capture, ctx, srv.aux_gate, cfg.aux_timeout_s)
        except Exception as exc:  # noqa: BLE001 - 어떤 예외도 사용자 문구로
            ctx.error_kind = ctx.error_kind or "internal"
            log.warning("처리 중 예외 ticket=%s kind=%s", ticket, type(exc).__name__)
            start.clear()
        finally:
            _CTX.reset(token)
            srv._drop_reservation(ctx)
            if not ctx.task_started:
                srv.release_upload(ctx)  # 하위 작업을 시작했으면 그 작업이 끝날 때 반납한다

        if ctx.refusal is not None:  # run()의 두 번째 입장 검사가 거절
            await reply(*self._refusal_reply(ctx, ctx.refusal))
            return
        if not start or ctx.error_kind == "timeout" and ctx.mode != "analysis":
            code = 504 if ctx.error_kind == "timeout" else 500
            srv.counters["timeout_504" if code == 504 else "error_5xx"] += 1
            await reply(code, _err("timeout" if code == 504 else "internal", self._error_message(code, ctx), ticket))
            return
        await self._finish(send, start, b"".join(out_chunks), ctx)

    def _rate_reply(self, ctx: RequestCtx, retry: float, limit: int) -> tuple[int, dict[str, Any], dict[str, str]]:
        self.serving.counters["rate_429"] += 1
        retry_s = max(int(math.ceil(retry)), 1)
        return (429, _err("rate_limited", user_message("rate", retry=retry_s, limit=limit), ctx.ticket,
                          retry_after_s=retry_s), {"retry-after": str(retry_s)})

    def _refusal_reply(self, ctx: RequestCtx, refusal: tuple[int, str, str, int]
                       ) -> tuple[int, dict[str, Any], dict[str, str]]:
        code, error_code, message, retry_s = refusal
        err = _err(error_code, message, ctx.ticket, retry_after_s=retry_s)
        if error_code == "busy":
            err["queue"] = self.serving.gate.summary()
        return code, err, {"retry-after": str(retry_s)}

    async def _gated_call(self, scope: dict[str, Any], replay: Any, capture: Any, ctx: RequestCtx, gate: Gate,
                          timeout: float) -> None:
        """미들웨어가 슬롯을 잡고 하위 앱을 부른다. 시간 상한을 넘기면 504로 답하되, 슬롯은 하위 작업이 끝날 때 반납."""
        t = ctx.reservation
        assert t is not None
        remaining = timeout - (time.monotonic() - ctx.started)
        try:
            await asyncio.wait_for(gate.acquire(t), timeout=max(remaining, 0.01))
        except asyncio.TimeoutError:
            ctx.error_kind = "timeout"
            return  # finally에서 자리 반납
        ctx.reservation, ctx.budget_spent = None, False
        t0 = time.monotonic()
        ctx.waited_s = round(t0 - t.enq_at, 3)
        task = asyncio.ensure_future(self.app(scope, replay, capture))
        ctx.task_started = True

        def _done(job: asyncio.Future[Any]) -> None:
            ctx.run_s = round(time.monotonic() - t0, 3)
            gate.release(t, ctx.run_s)
            self.serving.release_upload(ctx)
            if not job.cancelled() and job.exception() is not None:
                log.info("하위 처리 실패 ticket=%s kind=%s", ctx.ticket, type(job.exception()).__name__)

        task.add_done_callback(_done)
        remaining = timeout - (time.monotonic() - ctx.started)
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=max(remaining, 0.01))
        except asyncio.TimeoutError:
            ctx.error_kind = "timeout"

    # 응답 다듬기 -------------------------------------------------------
    def _error_message(self, code: int, ctx: RequestCtx) -> str:
        cfg = self.serving.config
        if code == 504:
            if ctx.mode == "aux":
                return user_message("timeout_aux", limit=int(cfg.aux_timeout_s), ticket=ctx.ticket)
            return user_message("timeout", limit=int(cfg.request_timeout_s), ticket=ctx.ticket)
        if code in (400, 422):
            return user_message("invalid")
        return user_message("internal", ticket=ctx.ticket)

    def _serving_info(self, ctx: RequestCtx) -> dict[str, Any]:
        return {"ticket": ctx.ticket, "cache": ctx.cache, "queue": ctx.queue,
                "position_at_arrival": ctx.position_at_arrival, "waited_s": round(ctx.waited_s, 1),
                "run_s": round(ctx.run_s, 1), "total_s": round(time.monotonic() - ctx.started, 2)}

    async def _finish(self, send: Any, start: dict[str, Any], body: bytes, ctx: RequestCtx) -> None:
        srv = self.serving
        code = int(start.get("status", 500))
        headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
        ctype = next((v.decode("latin-1") for k, v in headers if k.lower() == b"content-type"), "")
        data: Any = None
        if "json" in ctype:
            try:
                data = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                data = None
        if ctx.error_kind == "timeout" and code >= 500:
            code = 504
        if code >= 400:
            if code >= 500:
                srv.counters["timeout_504" if code == 504 else "error_5xx"] += 1
            msg = self._error_message(code, ctx)
            kind = {504: "timeout", 422: "invalid_request", 400: "invalid_request"}.get(
                code, "internal" if code >= 500 else "rejected")
            if _is_validation_body(data):
                data = _err("invalid_request", msg, ctx.ticket, fields=_validation_fields(data))
            elif not isinstance(data, dict):
                data = _err(kind, msg if code >= 500 or data is None else scrub_public(str(data))[:300], ctx.ticket)
            elif code == 503 and data.get("status") == "error" and data.get("error_code") in _APP_BUSY_CODES:
                data = _walk_strings(data, scrub_public)  # 앱이 만든 "잠시 뒤 다시" 안내(작업 보관 상한 등)는 문구를 둔다
                data.setdefault("request_id", ctx.ticket)
            elif code >= 500:
                data = _walk_strings(data, lambda s: _sanitize_error_str(s, msg))
                data.update({"message": msg, "error_code": kind, "request_id": ctx.ticket, "ticket": ctx.ticket})
            else:  # 4xx: 하위 앱의 사용자 문구(예: 업로드 형식 안내)는 두고 내부 정보만 지운다
                data = _walk_strings(data, lambda s: _sanitize_error_str(s, msg))
                if ctx.kind != "upload":  # 업로드 4xx는 앱 본문 모양 그대로(요청 번호는 X-Neumann-Ticket 헤더로 나간다)
                    data.setdefault("request_id", ctx.ticket)
        elif isinstance(data, (dict, list)) and ctx.mode == "analysis":
            data = _walk_diag(data, _scrub_ok_str)
        if isinstance(data, dict) and isinstance(data.get("_status"), dict):
            data["_status"]["serving"] = self._serving_info(ctx)
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            if code >= 400 or "json" not in ctype:
                headers = [(k, v) for k, v in headers if k.lower() != b"content-type"]
                headers.append((b"content-type", b"application/json"))
        headers += self._extra_headers(ctx)
        headers.append((b"content-length", str(len(body)).encode("latin-1")))
        await send({"type": "http.response.start", "status": code, "headers": headers})
        await send({"type": "http.response.body", "body": body})
        self._log(ctx, code)

    def _extra_headers(self, ctx: RequestCtx) -> list[tuple[bytes, bytes]]:
        return [(b"x-neumann-ticket", ctx.ticket.encode("latin-1")), (b"x-neumann-cache", ctx.cache.encode("latin-1")),
                (b"x-neumann-queue-waited-s", f"{ctx.waited_s:.1f}".encode("latin-1")),
                (b"x-neumann-queue-position", str(ctx.position_at_arrival).encode("latin-1"))]

    async def _send_json(self, send: Any, code: int, payload: dict[str, Any], ctx: RequestCtx,
                         headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hs = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("latin-1"))]
        hs += [(k.encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()]
        hs += self._extra_headers(ctx)
        await send({"type": "http.response.start", "status": code, "headers": hs})
        await send({"type": "http.response.body", "body": body})

    def _log(self, ctx: RequestCtx, code: int) -> None:
        log.info("req ticket=%s %s path=%s mode=%s plan_id=%s chars=%d status=%d cache=%s queue=%s pos=%d "
                 "waited_s=%.1f run_s=%.1f total_s=%.2f", ctx.ticket, _ip_tag(ctx.ip), ctx.path, ctx.mode,
                 ctx.plan_id[:12] or "-", ctx.chars, code, ctx.cache, ctx.queue, ctx.position_at_arrival,
                 ctx.waited_s, ctx.run_s, time.monotonic() - ctx.started)


# ───────────────────────── 보안 헤더(SEC-7) ─────────────────────────

# 모든 응답에 붙인다. CSP는 frame-ancestors만(화면 index.html의 인라인 스크립트·스타일을 막지 않게 스크립트 정책은 넣지 않는다).
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)


class SecurityHeadersMiddleware:
    """응답 시작 메시지에 보안 헤더를 붙인다(앱이 이미 같은 이름을 붙였으면 그대로 둔다). 가장 바깥에 둔다."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                have = {bytes(k).lower() for k, _ in headers}
                headers += [(k, v) for k, v in SECURITY_HEADERS if k not in have]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ───────────────────────── 전역 예외 처리기(S-04) ─────────────────────────


def _request_id(request: Request) -> str:
    ctx = current_request()
    if ctx is not None:
        return ctx.ticket
    rid = request.headers.get(TICKET_HEADER) or request.headers.get("x-request-id") or ""
    return rid if _TICKET_RE.match(rid) else uuid.uuid4().hex[:16]


async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """모든 경로의 처리 안 된 예외: 분류 문자열과 요청 id만(예외 메시지·경로·상류 API 문구 없음)."""
    rid = _request_id(request)
    log.warning("처리 안 된 예외 request_id=%s path=%s kind=%s", rid, request.url.path, type(exc).__name__)
    # 이 응답은 가장 바깥(ServerErrorMiddleware)에서 나가 보안 헤더 미들웨어를 거치지 않으므로 직접 붙인다(SEC-7)
    return JSONResponse(_err("internal", user_message("internal", ticket=rid), rid), status_code=500,
                        headers={"x-neumann-ticket": rid, **{k.decode(): v.decode() for k, v in SECURITY_HEADERS}})


async def _validation_exception(request: Request, exc: Exception) -> JSONResponse:
    """422: 입력을 되돌려 보내지 않는다(FastAPI 기본은 input을 통째로 싣는다). detail은 위치·종류·문구만."""
    rid = _request_id(request)
    errors = exc.errors() if hasattr(exc, "errors") else []
    detail = _validation_fields({"detail": [e for e in errors if isinstance(e, dict)]})
    body = _err("invalid_request", user_message("invalid"), rid, fields=detail)
    body["detail"] = detail
    return JSONResponse(body, status_code=422, headers={"x-neumann-ticket": rid})


def install_exception_handlers(app: Any) -> None:
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, _validation_exception)
    app.add_exception_handler(Exception, _unhandled_exception)


# ───────────────────────── 라우터·설치 ─────────────────────────

router = APIRouter()


@router.get("/queue/status")
def queue_status(request: Request, ticket: str | None = None) -> dict[str, Any]:
    """대기열 상태. ``ticket``(요청 헤더 X-Neumann-Ticket에 보낸 값)을 주면 그 요청의 대기 순번·예상 시간."""
    srv = getattr(request.app.state, "serving", None) or get_serving()
    return srv.queue_status(ticket)


def install(app: Any, serving: Serving | None = None, *, pipeline: Callable[..., Any] | None = None,
            exception_handlers: bool = True) -> Serving:
    """앱에 서빙 층을 붙인다: 미들웨어, 전역 예외 처리기, GET /queue/status, 로그 필터, (설정 시) 시작 예열."""
    srv = serving or get_serving()
    app.state.serving = srv
    app.add_middleware(ServingMiddleware, serving=srv)
    app.add_middleware(SecurityHeadersMiddleware)  # 나중에 붙인 것이 바깥: 서빙 층이 직접 보낸 응답에도 붙는다(SEC-7)
    if exception_handlers:
        install_exception_handlers(app)
    app.include_router(router)
    install_log_filter()

    async def _on_startup() -> None:
        ensure_log_handler()
        install_log_filter()  # uvicorn이 핸들러를 다시 만든 뒤에도 붙게
        srv.start_warmup(pipeline)

    app.router.on_startup.append(_on_startup)
    return srv


__all__ = [
    "MESSAGES", "AdmissionRefused", "AnalysisTimeout", "DailyBudget", "Gate", "QueueFull", "RateLimiter", "RedactingFilter", "RequestCtx",
    "ResultCache", "Serving", "ServingConfig", "ServingMiddleware", "client_ip", "current_request",
    "ensure_log_handler", "get_serving", "install", "ip_key", "install_exception_handlers", "install_log_filter",
    "longest_token", "mask_job_paths", "plan_key", "public_plan_ids", "router", "scrub_ok_payload", "scrub_public", "scrub_secrets", "user_message",
    "wrap_pipeline",
    # SEC-7
    "SECURITY_HEADERS", "SecurityHeadersMiddleware", "count_lines", "forget_log_secret", "mask_live_secrets",
    "register_log_secret",
]
