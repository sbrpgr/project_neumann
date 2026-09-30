"""공개 라이브 서버 안정성 층(E4-L2c): 동시 상한·대기열·IP 속도 제한·입력 상한·결과 캐시·예열·오류 문구·로그 위생.

main.py에는 PM이 붙인다(이 모듈은 main.py를 import 하지 않는다).

    from neumann.api import serving
    serving.install(app)                       # 미들웨어 + GET /queue/status + 로그 필터 + (설정 시) 시작 예열
    ...
    return serving.wrap_pipeline(fn), "connected", ""   # _load_pipeline 안: 캐시·대기열·시간 상한을 씌운다
    # _run_pipeline 의 `async with _semaphore():` 는 지운다(동시 상한은 여기 Gate가 한다)

구성
- ``Gate``: 동시 분석 상한(기본 2) + FIFO 대기열(기본 20). 대기 순번·예상 대기 시간. 넘치면 503 + 사용자 문구.
- ``RateLimiter``: IP별 슬라이딩 창(기본 분당 6건). 넘치면 429 + Retry-After + 사용자 문구. 캐시 적중은 세지 않는다.
- 입력 상한: plan_text 50,000자(바이트 상한도 함께). 넘치면 413 + 사용자 문구. 요청 시간 상한(기본 300초) → 504.
- ``ResultCache``: plan_id(= 정규화·가림 뒤 본문 sha256, PlanDocument.plan_id와 같다) → 결과.
  메모리 LRU + 공유 ``<data_dir>/cache/results/<plan_id>.json``. 저장본에는 계획서 본문(줄 텍스트)을 넣지 않고,
  적중 때 요청 본문으로 줄을 다시 붙인다. status가 ``ok``인 결과만 저장한다(강등 결과는 다시 돌린다).
- 같은 plan_id가 이미 돌고 있으면 새로 돌리지 않고 그 결과를 같이 받는다(single-flight).
- 시간 상한을 넘겨도 분석은 끝까지 돌고(슬롯도 그때 반납) 결과가 캐시에 들어간다 → 다시 누르면 즉시 응답.
- 오류 응답: 스택 트레이스·예외 메시지·파일 경로·키를 지우고 사용자 문구 + 요청 번호(ticket)로 바꾼다.
  예외 "종류" 이름(예: RuntimeError)만 남긴다(실패를 숨기지 않기 위해).
- 로그: 요청마다 한 줄(ticket, IP 해시, plan_id 앞 12자, 글자 수, 상태, 캐시, 대기·총 시간). 본문·키·트레이스 없음.
  ``RedactingFilter``가 키 모양 문자열·실제 키 값을 가리고 트레이스(exc_info)를 예외 종류 한 줄로 줄인다.

설정(환경변수, 모두 선택). ``NEUMANN_PUBLIC=1``(scripts/serve.py 기본)이면 공개 프로필: 속도 제한·결과 캐시·예열이
기본으로 켜진다. 없으면(테스트·개발) 이 셋은 꺼져 있고, 동시 상한·대기열·입력/시간 상한·오류 문구·로그 위생만 켜진다.

    NEUMANN_MAX_CONCURRENT=2  NEUMANN_QUEUE_MAX=20  NEUMANN_RATE_PER_MIN=6(공개)/0  NEUMANN_MAX_PLAN_CHARS=50000
    NEUMANN_REQUEST_TIMEOUT_S=300  NEUMANN_AVG_RUN_S=60  NEUMANN_RESULT_CACHE=1(공개)/0
    NEUMANN_RESULT_CACHE_DIR=<data_dir>/cache/results  NEUMANN_CACHE_MEM_ITEMS=64
    NEUMANN_TRUST_PROXY=loopback|always|never  NEUMANN_WARMUP=1(공개)/0  NEUMANN_WARMUP_PLANS=a.md;b.md

프로세스 하나(uvicorn worker 1개)를 전제로 한다. 대기열·속도 제한 상태는 프로세스 메모리에 있다.
"""

from __future__ import annotations

import asyncio
import contextvars
import copy
import hashlib
import heapq
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

from fastapi import APIRouter, Request

log = logging.getLogger("neumann.serving")

REPO_ROOT = Path(__file__).resolve().parents[3]
PROTECTED_PATHS = frozenset({"/premortem", "/premortem/view"})
TICKET_HEADER = "x-neumann-ticket"
_TICKET_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")
_PLAN_ID_RE = re.compile(r"^[0-9a-f]{64}$")

# ───────────────────────── 사용자 문구 ─────────────────────────

MESSAGES = {
    "busy": "지금 분석 요청이 많아 대기열이 가득 찼습니다. 약 {retry}초 뒤에 다시 시도해 주세요.",
    "rate": "요청이 너무 잦습니다. {retry}초 뒤에 다시 시도해 주세요(분당 {limit}건).",
    "too_large": "계획서가 너무 깁니다. {limit:,}자 이하로 줄여서 다시 올려 주세요(현재 {chars:,}자).",
    "too_large_bytes": "요청이 너무 큽니다. 계획서는 {limit:,}자 이하로 올려 주세요.",
    "timeout": ("분석이 {limit}초 안에 끝나지 않았습니다. 분석은 계속 진행 중이니 잠시 뒤 같은 계획서로 다시 요청하면 "
                "끝난 결과를 바로 받을 수 있습니다(요청 번호 {ticket})."),
    "invalid": "요청 형식이 올바르지 않습니다. 계획서 본문(plan_text)을 비우지 말고 다시 보내 주세요.",
    "internal": "분석 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요. 계속되면 요청 번호 {ticket}를 알려 주세요.",
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


@dataclass(frozen=True)
class ServingConfig:
    max_concurrent: int = 2
    queue_max: int = 20
    rate_per_min: int = 0
    rate_window_s: float = 60.0
    max_plan_chars: int = 50_000
    request_timeout_s: float = 300.0
    avg_run_s: float = 60.0
    cache_enabled: bool = False
    cache_dir: Path | None = None
    cache_mem_items: int = 64
    cache_statuses: tuple[str, ...] = ("ok",)
    cache_variant: str = "default"
    trust_proxy: str = "loopback"
    warmup: bool = False
    warmup_plans: tuple[Path, ...] = ()
    public: bool = False

    @classmethod
    def from_env(cls) -> ServingConfig:
        public = _env_bool("NEUMANN_PUBLIC", False)
        cache_enabled = _env_bool("NEUMANN_RESULT_CACHE", public)
        cache_dir = _env("NEUMANN_RESULT_CACHE_DIR")
        plans = _env("NEUMANN_WARMUP_PLANS")
        if plans:
            warm = tuple(Path(p) for p in plans.split(";") if p.strip())
        else:
            warm = tuple(sorted((REPO_ROOT / "tests" / "fixtures" / "plans").glob("plan*.md")))
        trust = (_env("NEUMANN_TRUST_PROXY") or "loopback").lower()
        return cls(
            max_concurrent=int(_env_num("NEUMANN_MAX_CONCURRENT", 2, 1, 64)),
            queue_max=int(_env_num("NEUMANN_QUEUE_MAX", 20, 0, 10_000)),
            rate_per_min=int(_env_num("NEUMANN_RATE_PER_MIN", 6 if public else 0, 0, 100_000)),
            max_plan_chars=int(_env_num("NEUMANN_MAX_PLAN_CHARS", 50_000, 1, 10_000_000)),
            request_timeout_s=_env_num("NEUMANN_REQUEST_TIMEOUT_S", 300.0, 0.05, 86_400),
            avg_run_s=_env_num("NEUMANN_AVG_RUN_S", 60.0, 0.1, 86_400),
            cache_enabled=cache_enabled,
            cache_dir=Path(cache_dir) if cache_dir else (_default_data_dir() / "cache" / "results"),
            cache_mem_items=int(_env_num("NEUMANN_CACHE_MEM_ITEMS", 64, 0, 100_000)),
            cache_variant=_default_variant(),
            trust_proxy=trust if trust in {"loopback", "always", "never"} else "loopback",
            warmup=_env_bool("NEUMANN_WARMUP", public),
            warmup_plans=warm,
            public=public,
        )

    def public_view(self) -> dict[str, Any]:
        return {
            "max_concurrent": self.max_concurrent, "queue_max": self.queue_max, "rate_per_min": self.rate_per_min,
            "max_plan_chars": self.max_plan_chars, "request_timeout_s": self.request_timeout_s,
            "cache": self.cache_enabled, "public": self.public,
        }


# ───────────────────────── 비밀값·내부 정보 가리기 ─────────────────────────

# 키 모양(verify.py와 같은 종류). 이 파일이 검사에 걸리지 않게 쪼개 쓴다.
_SECRET_RES = [
    re.compile(r"\bs" r"k-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh" r"[pousr]_[A-Za-z0-9]{20,}|github" r"_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bh" r"f_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAK" r"IA[0-9A-Z]{16}\b"),
    re.compile(r"\bAI" r"za[0-9A-Za-z_\-]{30,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
]
_SECRET_ENV = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HF_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "NEUMANN_PSEUDONYM_SALT")
REDACTED = "[가림]"


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


_TRACE_RE = re.compile(r"Traceback \(most recent call last\)|File \"[^\"]+\", line \d+")
_INTERNAL_RE = re.compile(
    r"Traceback|File \"|\.py\b|[A-Za-z]:\\|/(?:home|usr|Users|tmp|var|opt)/|\b[A-Z]\w*(?:Error|Exception|Timeout|Exit)\b"
    r"|import 실패|모듈 없음|실행 실패"
)
_EXC_NAME_RE = re.compile(r"\b([A-Z]\w*(?:Error|Exception|Timeout|Exit))\b")


def _exc_kind(text: str) -> str | None:
    m = _EXC_NAME_RE.search(text)
    return m.group(1) if m else None


def _sanitize_error_str(s: str, msg: str) -> str:
    if not _INTERNAL_RE.search(s):
        return scrub_secrets(s)
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


def _scrub_ok_str(s: str) -> str:
    s = scrub_secrets(s)
    if _TRACE_RE.search(s):
        kind = _exc_kind(s)
        return f"(내부 추적 정보 생략{': ' + kind if kind else ''})"
    return s


class RedactingFilter(logging.Filter):
    """로그 레코드에서 키 모양 문자열·실제 키 값을 가리고, 트레이스를 예외 종류 한 줄로 줄인다."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(record.msg)
        clean = scrub_secrets(msg)
        if record.exc_info:
            exc = record.exc_info[1]
            clean += f" [트레이스 생략: {type(exc).__name__ if exc else '?'}]"
            record.exc_info = None
            record.exc_text = None
        if record.stack_info:
            record.stack_info = None
        if clean != msg or record.args:
            record.msg, record.args = clean, None
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


def _ip_tag(ip: str) -> str:
    """로그용 IP 표시: 원래 값 대신 해시 앞 10자(같은 IP끼리 묶어 볼 수만 있다)."""
    return "ip_" + hashlib.sha256(("neumann-ip:" + ip).encode("utf-8")).hexdigest()[:10]


# ───────────────────────── plan_id ─────────────────────────


def plan_key(plan_text: str) -> str:
    """PlanDocument.from_text와 같은 plan_id(정규화 → 이메일·ORCID 가림 → sha256)."""
    try:
        from neumann.models import normalize_text, redact_pii

        body = redact_pii(normalize_text(plan_text))
    except Exception:  # noqa: BLE001 - models가 없거나 실패하면 줄바꿈만 맞춘다
        body = plan_text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ───────────────────────── 요청 문맥 ─────────────────────────


@dataclass
class RequestCtx:
    ticket: str
    ip: str = "internal"
    path: str = ""
    started: float = field(default_factory=time.monotonic)
    plan_id: str = ""
    chars: int = 0
    cache: str = "miss"           # miss | hit | off
    queue: str = "none"           # none | queued | joined
    reservation: Ticket | None = None
    position_at_arrival: int = 0
    waited_s: float = 0.0
    run_s: float = 0.0
    error_kind: str | None = None  # timeout | internal | None


_CTX: contextvars.ContextVar[RequestCtx | None] = contextvars.ContextVar("neumann_serving_ctx", default=None)


def current_request() -> RequestCtx | None:
    return _CTX.get()


# ───────────────────────── 속도 제한 ─────────────────────────


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


class Gate:
    """동시 실행 상한 + FIFO 대기열. 이벤트 루프 하나에서만 쓴다."""

    def __init__(self, max_active: int, max_waiting: int, avg_run_s: float) -> None:
        self.max_active, self.max_waiting = max_active, max_waiting
        self.avg_run_s = avg_run_s
        self._waiting: OrderedDict[str, Ticket] = OrderedDict()
        self._running: dict[str, Ticket] = {}
        self._recent: OrderedDict[str, Ticket] = OrderedDict()
        self.completed = 0

    # 입장 ------------------------------------------------------------
    def reserve(self, ticket_id: str, plan_id: str = "", *, force: bool = False) -> Ticket:
        """대기열에 자리를 잡는다. 꽉 찼으면 QueueFull(force면 무시: 예열 등 내부 작업)."""
        if not force and len(self._running) + len(self._waiting) >= self.max_active + self.max_waiting:
            raise QueueFull(self.eta(len(self._waiting) + 1))
        if ticket_id in self._waiting or ticket_id in self._running:
            ticket_id = f"{ticket_id}-{uuid.uuid4().hex[:6]}"
        t = Ticket(id=ticket_id, plan_id=plan_id)
        self._waiting[t.id] = t
        return t

    async def acquire(self, t: Ticket) -> None:
        """차례가 올 때까지 기다린다. 취소되면 자리를 비운다."""
        self._dispatch()
        if t.state == "running":
            return
        t.event = t.event or asyncio.Event()
        try:
            await t.event.wait()
        except BaseException:
            if t.state == "running":
                self.release(t)
            else:
                self.cancel(t)
            raise

    def release(self, t: Ticket, run_s: float | None = None) -> None:
        if self._running.pop(t.id, None) is not None:
            t.state, t.end_at = "done", time.monotonic()
            self.completed += 1
            if run_s is not None and run_s > 0:
                self.avg_run_s = 0.7 * self.avg_run_s + 0.3 * run_s
            self._remember(t)
        self._dispatch()

    def cancel(self, t: Ticket) -> None:
        if self._waiting.pop(t.id, None) is not None:
            t.state = "cancelled"
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
                    "eta_s": self.eta(pos), "waited_s": round(now - t.enq_at, 1)}
        if ticket_id in self._running:
            t = self._running[ticket_id]
            el = now - (t.start_at or now)
            return {"id": ticket_id, "state": "running", "position": 0, "ahead": 0,
                    "eta_s": round(max(self.avg_run_s - el, 1.0), 1), "running_s": round(el, 1)}
        if ticket_id in self._recent:
            return {"id": ticket_id, "state": self._recent[ticket_id].state, "position": 0, "ahead": 0, "eta_s": 0.0}
        return {"id": ticket_id, "state": "unknown", "position": 0, "ahead": 0, "eta_s": None}


# ───────────────────────── 결과 캐시 ─────────────────────────


def _strip_plan_body(result: dict[str, Any]) -> dict[str, Any]:
    """영속 저장본: plan.lines 텍스트를 빼고(PremortemResult.dump_persisted와 같은 규칙) plan_stats.lines의 글도 뺀다."""
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
    """plan_id → 결과. 메모리 LRU + 디스크(JSON 한 건 한 파일). 본문은 저장하지 않는다."""

    def __init__(self, directory: Path | None, *, enabled: bool, mem_items: int = 64, variant: str = "default",
                 statuses: tuple[str, ...] = ("ok",)) -> None:
        self.dir, self.enabled, self.mem_items = directory, enabled, mem_items
        self.variant, self.statuses = variant, statuses
        self._mem: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.hits = self.misses = self.stores = 0

    def _path(self, plan_id: str) -> Path | None:
        if self.dir is None or not _PLAN_ID_RE.match(plan_id):
            return None
        return self.dir / f"{plan_id}.json"

    def get(self, plan_id: str) -> dict[str, Any] | None:
        if not self.enabled or not plan_id:
            return None
        entry = self._mem.get(plan_id)
        if entry is not None:
            self._mem.move_to_end(plan_id)
            return entry
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
            except OSError as exc:
                log.warning("결과 캐시 쓰기 실패 plan_id=%s (%s)", plan_id[:12], type(exc).__name__)
        return True

    def _remember(self, plan_id: str, entry: dict[str, Any]) -> None:
        if self.mem_items <= 0:
            return
        self._mem[plan_id] = entry
        self._mem.move_to_end(plan_id)
        while len(self._mem) > self.mem_items:
            self._mem.popitem(last=False)

    @staticmethod
    def restore(entry: dict[str, Any], plan_text: str) -> dict[str, Any]:
        return _restore_plan_body(copy.deepcopy(entry["result"]), plan_text)


# ───────────────────────── 서빙 상태 ─────────────────────────


class AnalysisTimeout(Exception):
    """요청 시간 상한 초과(분석 자체는 계속 돈다)."""


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
        self.gate = Gate(c.max_concurrent, c.queue_max, c.avg_run_s)
        self.limiter = RateLimiter(c.rate_per_min, c.rate_window_s)
        self.cache = ResultCache(c.cache_dir, enabled=c.cache_enabled, mem_items=c.cache_mem_items,
                                 variant=c.cache_variant, statuses=c.cache_statuses)
        self.inflight: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.counters = {"requests": 0, "cache_hits": 0, "joined": 0, "busy_503": 0, "rate_429": 0, "too_large_413": 0,
                         "timeout_504": 0, "error_5xx": 0}
        self.warmup_state: dict[str, Any] = {"state": "off" if not c.warmup else "pending", "plans": 0, "cached": 0,
                                             "failed": 0}
        self._warm_task: asyncio.Task[Any] | None = None

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

    async def run(self, fn: Callable[..., Any], plan_text: str, **kwargs: Any) -> dict[str, Any]:
        ctx = current_request() or RequestCtx(ticket="int_" + uuid.uuid4().hex[:12])
        pid = ctx.plan_id or plan_key(plan_text)
        ctx.plan_id, ctx.chars = pid, len(plan_text)
        entry = self.cache.get(pid)
        if entry is not None:
            self._drop_reservation(ctx)
            ctx.cache = "hit"
            self.cache.hits += 1
            self.counters["cache_hits"] += 1
            return self.cache.restore(entry, plan_text)
        ctx.cache = "miss" if self.cache.enabled else "off"
        self.cache.misses += 1
        job = self.inflight.get(pid)
        if job is None:
            t = ctx.reservation or self.gate.reserve(ctx.ticket, pid, force=True)
            ctx.reservation = None
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
        remaining = self.config.request_timeout_s - (time.monotonic() - ctx.started)
        try:
            result = await asyncio.wait_for(asyncio.shield(job), timeout=max(remaining, 0.01))
        except asyncio.TimeoutError:
            ctx.error_kind = "timeout"
            raise AnalysisTimeout("request time limit") from None
        return copy.deepcopy(result)

    def _drop_reservation(self, ctx: RequestCtx) -> None:
        if ctx.reservation is not None:
            self.gate.cancel(ctx.reservation)
            ctx.reservation = None

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
            "active": g.active, "waiting": g.waiting, "max_active": g.max_active, "max_waiting": g.max_waiting,
            "avg_run_s": round(g.avg_run_s, 1), "eta_new_s": g.eta(g.waiting + 1) if g.active >= g.max_active else 0.0,
            "accepting": g.active + g.waiting < g.max_active + g.max_waiting,
            "limits": self.config.public_view(),
            "counters": dict(self.counters, completed=g.completed),
            "cache": {"enabled": self.cache.enabled, "memory_items": len(self.cache._mem), "hits": self.cache.hits,
                      "stores": self.cache.stores},
            "warmup": dict(self.warmup_state),
        }
        if ticket:
            out["ticket"] = g.ticket_status(ticket) if _TICKET_RE.match(ticket) else {"id": "", "state": "unknown"}
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
            t0 = time.monotonic()
            token = _CTX.set(RequestCtx(ticket="warm_" + pid[:12], path="warmup"))
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


def client_ip(scope: dict[str, Any], trust: str) -> str:
    """실제 클라이언트 IP. 터널(cloudflared·ngrok)은 로컬(127.0.0.1)에서 들어오므로 그때만 프록시 헤더를 믿는다.

    CF-Connecting-IP가 있으면 그것, 없으면 X-Forwarded-For의 마지막 값(터널이 붙인 값, 앞쪽은 위조 가능).
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
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
    cf = headers.get("cf-connecting-ip", "").strip()
    if cf:
        return cf[:64]
    xff = [p.strip() for p in headers.get("x-forwarded-for", "").split(",") if p.strip()]
    return xff[-1][:64] if xff else peer


def _header(scope: dict[str, Any], name: str) -> str | None:
    key = name.lower().encode("latin-1")
    for k, v in scope.get("headers") or []:
        if k.lower() == key:
            return v.decode("latin-1")
    return None


class ServingMiddleware:
    """분석 요청(POST /premortem, /premortem/view)에 입력·속도·대기열 상한과 오류 문구·로그 위생을 씌운다."""

    def __init__(self, app: Any, serving: Serving | None = None) -> None:
        self.app = app
        self.serving = serving or get_serving()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") != "POST" or scope.get("path") not in PROTECTED_PATHS:
            await self.app(scope, receive, send)
            return
        await self._handle(scope, receive, send)

    async def _handle(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        srv, cfg = self.serving, self.serving.config
        raw_ticket = _header(scope, TICKET_HEADER) or ""
        ticket = raw_ticket if _TICKET_RE.match(raw_ticket) else uuid.uuid4().hex[:16]
        ctx = RequestCtx(ticket=ticket, ip=client_ip(scope, cfg.trust_proxy), path=scope.get("path", ""))
        srv.counters["requests"] += 1
        max_bytes = cfg.max_plan_chars * 6 + 65_536

        async def reply(code: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
            await self._send_json(send, code, payload, ctx, headers)
            self._log(ctx, code)

        # 1) 바이트 상한(Content-Length 먼저, 그다음 실제로 읽은 양)
        clen = _header(scope, "content-length")
        if clen and clen.isdigit() and int(clen) > max_bytes:
            srv.counters["too_large_413"] += 1
            await reply(413, self._err("too_large", user_message("too_large_bytes", limit=cfg.max_plan_chars), ctx))
            return
        chunks, size = [], 0
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            body = msg.get("body", b"")
            size += len(body)
            if size > max_bytes:
                srv.counters["too_large_413"] += 1
                await reply(413, self._err("too_large", user_message("too_large_bytes", limit=cfg.max_plan_chars), ctx))
                return
            chunks.append(body)
            if not msg.get("more_body"):
                break
        body = b"".join(chunks)

        # 2) 글자 수 상한, plan_id
        plan_text: str | None = None
        try:
            payload = json.loads(body.decode("utf-8")) if body else None
            if isinstance(payload, dict) and isinstance(payload.get("plan_text"), str):
                plan_text = payload["plan_text"]
        except (ValueError, UnicodeDecodeError):
            plan_text = None
        if plan_text is not None:
            ctx.chars = len(plan_text)
            if ctx.chars > cfg.max_plan_chars:
                srv.counters["too_large_413"] += 1
                await reply(413, self._err("too_large", user_message("too_large", limit=cfg.max_plan_chars,
                                                                      chars=ctx.chars), ctx))
                return
            if plan_text.strip():
                ctx.plan_id = plan_key(plan_text)

        # 3) 캐시 적중·진행 중이면 속도 제한·대기열을 건너뛴다
        if ctx.plan_id:
            cached = srv.cache.has(ctx.plan_id)
            joining = ctx.plan_id in srv.inflight
            if not cached:
                ok, retry = srv.limiter.hit(ctx.ip)
                if not ok:
                    srv.counters["rate_429"] += 1
                    retry_s = max(int(math.ceil(retry)), 1)
                    await reply(429, self._err("rate_limited", user_message("rate", retry=retry_s,
                                                                             limit=cfg.rate_per_min), ctx,
                                               retry_after_s=retry_s), {"retry-after": str(retry_s)})
                    return
            if not cached and not joining:
                try:
                    ctx.reservation = srv.gate.reserve(ticket, ctx.plan_id)
                    ctx.position_at_arrival = srv.gate.position(ctx.reservation.id)
                except QueueFull as exc:
                    srv.counters["busy_503"] += 1
                    retry_s = max(int(math.ceil(min(exc.retry_after_s, 600))), 5)
                    err = self._err("busy", user_message("busy", retry=retry_s), ctx, retry_after_s=retry_s)
                    err["queue"] = {k: v for k, v in srv.queue_status().items() if k in
                                    {"active", "waiting", "max_active", "max_waiting", "eta_new_s"}}
                    await reply(503, err, {"retry-after": str(retry_s)})
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
                start.update(message)
            elif message["type"] == "http.response.body":
                out_chunks.append(message.get("body", b""))

        token = _CTX.set(ctx)
        try:
            await self.app(scope, replay, capture)
        except Exception as exc:  # noqa: BLE001 - 어떤 예외도 사용자 문구로
            ctx.error_kind = ctx.error_kind or "internal"
            log.warning("처리 중 예외 ticket=%s kind=%s", ticket, type(exc).__name__)
            start.clear()
            out_chunks = []
        finally:
            _CTX.reset(token)
            srv._drop_reservation(ctx)

        if not start:
            srv.counters["error_5xx"] += 1
            code = 504 if ctx.error_kind == "timeout" else 500
            kind = "timeout" if code == 504 else "internal"
            msg = (user_message("timeout", limit=int(cfg.request_timeout_s), ticket=ticket) if code == 504
                   else user_message("internal", ticket=ticket))
            await reply(code, self._err(kind, msg, ctx))
            return
        await self._finish(send, start, b"".join(out_chunks), ctx)

    # 응답 다듬기 -------------------------------------------------------
    def _err(self, code: str, message: str, ctx: RequestCtx, **extra: Any) -> dict[str, Any]:
        return {"status": "error", "error_code": code, "message": message, "ticket": ctx.ticket, **extra}

    def _serving_info(self, ctx: RequestCtx) -> dict[str, Any]:
        return {"ticket": ctx.ticket, "cache": ctx.cache, "queue": ctx.queue,
                "position_at_arrival": ctx.position_at_arrival, "waited_s": round(ctx.waited_s, 1),
                "run_s": round(ctx.run_s, 1), "total_s": round(time.monotonic() - ctx.started, 2)}

    async def _finish(self, send: Any, start: dict[str, Any], body: bytes, ctx: RequestCtx) -> None:
        srv, cfg = self.serving, self.serving.config
        code = int(start.get("status", 500))
        headers = [(k, v) for k, v in start.get("headers", []) if k.lower() not in {b"content-length"}]
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
            if code == 504:
                msg = user_message("timeout", limit=int(cfg.request_timeout_s), ticket=ctx.ticket)
                kind = "timeout"
            elif code == 422:
                msg, kind = user_message("invalid"), "invalid_request"
            else:
                msg, kind = user_message("internal", ticket=ctx.ticket), "internal"
            if code == 422 or not isinstance(data, dict):
                data = self._err(kind, msg, ctx)  # 422 detail은 입력(본문)을 되돌려 보내므로 통째로 바꾼다
            else:
                data = _walk_strings(data, lambda s: _sanitize_error_str(s, msg))
                data.update({"message": msg, "error_code": kind, "ticket": ctx.ticket})
        elif isinstance(data, (dict, list)):
            data = _walk_strings(data, _scrub_ok_str)
        if isinstance(data, dict) and isinstance(data.get("_status"), dict):
            data["_status"]["serving"] = self._serving_info(ctx)
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        elif code >= 400:
            body = json.dumps(self._err("internal", user_message("internal", ticket=ctx.ticket), ctx),
                              ensure_ascii=False).encode("utf-8")
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
        log.info("req ticket=%s %s path=%s plan_id=%s chars=%d status=%d cache=%s queue=%s pos=%d waited_s=%.1f "
                 "run_s=%.1f total_s=%.2f", ctx.ticket, _ip_tag(ctx.ip), ctx.path, ctx.plan_id[:12] or "-", ctx.chars,
                 code, ctx.cache, ctx.queue, ctx.position_at_arrival, ctx.waited_s, ctx.run_s,
                 time.monotonic() - ctx.started)


# ───────────────────────── 라우터·설치 ─────────────────────────

router = APIRouter()


@router.get("/queue/status")
def queue_status(request: Request, ticket: str | None = None) -> dict[str, Any]:
    """대기열 상태. ``ticket``(요청 헤더 X-Neumann-Ticket에 보낸 값)을 주면 그 요청의 대기 순번·예상 시간."""
    srv = getattr(request.app.state, "serving", None) or get_serving()
    return srv.queue_status(ticket)


def install(app: Any, serving: Serving | None = None, *, pipeline: Callable[..., Any] | None = None) -> Serving:
    """앱에 서빙 층을 붙인다: 미들웨어, GET /queue/status, 로그 필터, (설정 시) 시작 예열."""
    srv = serving or get_serving()
    app.state.serving = srv
    app.add_middleware(ServingMiddleware, serving=srv)
    app.include_router(router)
    install_log_filter()

    async def _on_startup() -> None:
        install_log_filter()  # uvicorn이 핸들러를 다시 만든 뒤에도 붙게
        srv.start_warmup(pipeline)

    app.router.on_startup.append(_on_startup)
    return srv


__all__ = [
    "MESSAGES", "AnalysisTimeout", "Gate", "QueueFull", "RateLimiter", "RedactingFilter", "RequestCtx", "ResultCache",
    "Serving", "ServingConfig", "ServingMiddleware", "client_ip", "current_request", "get_serving", "install",
    "install_log_filter", "plan_key", "router", "scrub_secrets", "user_message", "wrap_pipeline",
]
