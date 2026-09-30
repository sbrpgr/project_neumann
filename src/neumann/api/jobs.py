"""비동기 작업 API(E4-L2d): 긴 분석을 작업(job)으로 바꿔 HTTP 응답을 짧게 끝낸다.

터널(Cloudflare)은 응답을 약 100초에서 끊는다(524). 분석 1건이 60~70초라 대기열에서 기다리면 넘는다. 그래서
``POST /premortem/jobs``는 수 초 안에 ``job_id``만 돌려주고, 화면은 ``GET /premortem/jobs/{job_id}``를 1~2초마다 본다.

    POST /premortem/jobs      {"plan_text", "filename"?, "format"?: "view"|"result"}
                              → 202 {job_id, status:"queued", position, eta_s, poll_after_s, message, ticket}
    GET  /premortem/jobs/{id} → {job_id, status: queued|running|done|error, position, eta_s, stage, stage_label,
                                 elapsed_s, message, result(done일 때: 화면 모양 ui_view 또는 PremortemResult),
                                 error_code(error일 때), poll_after_s, expires_in_s(끝난 뒤)}

관문은 serving의 것을 그대로 거친다(우회 경로 없음).
- ``POST /premortem/jobs``는 serving 미들웨어의 보호 경로(종류 analysis)로 **코드가 등록**한다(설정으로 뺄 수 없다).
  바이트 상한(413) → 글자 상한(413) → 캐시·합류면 통과 → 차단 스위치(503) → IP 속도 제한(429) → 일일 예산(503)
  → 대기열(가득이면 503)이 POST 때 적용되고, 잡은 자리와 뗀 예산은 작업으로 넘어간다.
- 미들웨어를 거치지 않은 요청(서빙 층 미설치 등)은 받지 않는다(503).
- 작업이 시작할 때 자리가 없고(입장 때 캐시·합류였는데 그새 사라짐) 캐시·진행 중 분석도 없으면 같은 관문을 다시 거친다.
- 실행은 ``Serving.run``(캐시 → 같은 계획서 합류 → 동시 상한·대기열)이 한다. 시간 상한은 작업용(``NEUMANN_JOB_TIMEOUT_S``).

작업 결과는 **메모리에만** 두고 끝난 뒤 TTL(``NEUMANN_JOB_TTL_S``)이 지나면 버린다. job_id는
``secrets.token_urlsafe(24)``(192비트)라 추측할 수 없다.

저장소 고갈 방지(재작업): 합류·캐시 적중 POST는 serving의 속도 제한·예산·대기열을 쓰지 않으므로 작업 API가 따로 막는다.
- IP(/64)별 POST 속도 제한(``NEUMANN_JOB_RATE_PER_MIN``, 모든 작업 POST에 적용)
- IP별 보관 작업 수 상한(``NEUMANN_JOB_PER_IP``): 넘으면 **그 IP의** 끝난 작업부터 밀어내고, 모두 진행 중이면 429
- 전체 상한(``NEUMANN_JOB_MAX``): 차면 **요청한 IP의** 끝난 작업만 밀어내고, 없으면 그 요청을 503으로 거절한다
  (다른 IP의 결과는 밀어내지 않는다)
- 폴링 GET도 IP별 넉넉한 속도 제한(``NEUMANN_JOB_POLL_PER_MIN``)
- 입구 검사: 글자 상한(413)과 공백 없는 긴 토큰(422)을 핸들러에서도 직접 본다(serving과 이중).
오류는 사용자 문구와 분류(error_code)만 싣는다(예외 메시지·경로·트레이스·키 없음).

진행 단계: 파이프라인이 ``on_stage`` 키워드를 받으면 콜백을 넘기고, 파이프라인 안(같은 요청 문맥)에서
``neumann.api.jobs.report_stage(name)``을 부르면 그 단계가 ``stage``로 보인다. 둘 다 없으면 queued/running만.

main.py 연결(PM): ``docs/reports/E4-L2d_main.patch`` — 파일 끝에서 ``jobs.install(app, load_pipeline=_load_pipeline,
sample_result=_sample_result)``. serving.install(E4-L2c 패치)이 먼저 붙어 있어야 한다.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from neumann.api import serving
from neumann.api.view import build_ui_view

log = logging.getLogger("neumann.jobs")

JOBS_PATH = "/premortem/jobs"
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{32}$")
MAX_PLAN_CHARS = 200_000  # main.PremortemRequest와 같다(실제 상한은 serving의 NEUMANN_MAX_PLAN_CHARS가 먼저 건다)

# 파이프라인 단계(neumann.pipeline 순서)와 화면 이름
STAGE_LABELS: dict[str, str] = {
    "queued": "대기", "running": "분석 중", "done": "완료", "error": "오류",
    "plan_normalize": "계획서 정리", "query_axes": "검색 질의 만들기", "search": "유사 연구 검색",
    "extract_issues": "지적 추출", "synthesize_cards": "위험카드 합성", "verify_evidence": "원문 대조",
    "assemble": "결과 정리",
    "fitness": "적합성 판정", "expected_review": "예상 심사평", "checklist": "체크리스트", "semantic_validate": "2차 검증",
}

MESSAGES = {
    "queued": "대기 {position}번째 · 약 {eta}초",
    "starting": "곧 분석을 시작합니다",
    "running": "분석 중 · {label} · 약 {eta}초 남음",
    "running_plain": "분석 중 · 약 {eta}초 남음",
    "done": "분석이 끝났습니다.",
    "not_found": ("작업을 찾을 수 없습니다. 결과 보관 시간({ttl_min}분)이 지났거나 주소가 잘못되었습니다. "
                  "다시 분석을 요청해 주세요."),
    "full": "지금 보관 중인 분석 작업이 많습니다. 약 {retry}초 뒤에 다시 시도해 주세요.",
    "unavailable": "지금은 분석 기능을 쓸 수 없습니다. 잠시 뒤 다시 시도해 주세요(요청 번호 {ticket}).",
    "not_gated": "지금은 작업 방식 분석을 받을 수 없습니다. 잠시 뒤 다시 시도해 주세요.",
    "per_ip": "이 주소에서 요청한 분석 {n}건이 아직 진행 중입니다. 끝난 뒤 다시 시도해 주세요.",
    "rate": "분석 요청이 너무 잦습니다. {retry}초 뒤에 다시 시도해 주세요(분당 {limit}건).",
    "poll_rate": "상태 확인이 너무 잦습니다. {retry}초 뒤에 다시 확인해 주세요.",
}


# ───────────────────────── 설정 ─────────────────────────


@dataclass(frozen=True)
class JobsConfig:
    ttl_s: float = 900.0        # 끝난 작업 결과 보관 시간
    max_jobs: int = 500         # 메모리에 두는 작업 수 상한(결과 약 150KB × 500 ≈ 75MB)
    shared_ttl_s: float = 60.0  # 합류·캐시 적중으로 만든 작업(분석 비용 0)의 보관 시간
    timeout_s: float = 900.0    # 작업 하나의 시간 상한(대기+실행). 넘으면 오류 문구(분석은 끝까지 돌고 캐시에 들어간다)
    poll_s: float = 1.5         # 화면에 권하는 폴링 간격
    per_ip: int = 3             # IP(/64)별 보관 작업 수 상한(0이면 끔)
    rate_per_min: int = 6       # IP별 작업 POST 수(합류·캐시 적중 포함, 0이면 끔). 개발 기본은 끔
    poll_per_min: int = 600     # IP별 폴링 GET 수(정상 사용은 작업 1건에 분당 약 40회, 0이면 끔)

    @classmethod
    def from_env(cls) -> JobsConfig:
        public = serving._env_bool("NEUMANN_PUBLIC", False)
        return cls(
            ttl_s=serving._env_num("NEUMANN_JOB_TTL_S", 900.0, 1.0, 7 * 86_400),
            max_jobs=int(serving._env_num("NEUMANN_JOB_MAX", 500, 1, 100_000)),
            shared_ttl_s=serving._env_num("NEUMANN_JOB_SHARED_TTL_S", 60.0, 1.0, 7 * 86_400),
            timeout_s=serving._env_num("NEUMANN_JOB_TIMEOUT_S", 900.0, 0.05, 86_400),
            poll_s=serving._env_num("NEUMANN_JOB_POLL_S", 1.5, 1.0, 2.0),
            per_ip=int(serving._env_num("NEUMANN_JOB_PER_IP", 3, 0, 10_000)),
            rate_per_min=int(serving._env_num("NEUMANN_JOB_RATE_PER_MIN", 6 if public else 0, 0, 100_000)),
            poll_per_min=int(serving._env_num("NEUMANN_JOB_POLL_PER_MIN", 600, 0, 1_000_000)),
        )


# ───────────────────────── 진행 단계 보고 ─────────────────────────

@dataclass
class _Progress:
    running: list[str] = field(default_factory=list)                   # 시작했고 아직 안 끝난 단계(시작 순)
    done: list[tuple[str, str, float | None]] = field(default_factory=list)  # 끝난 단계 (이름, 상태, 초)
    t: float = field(default_factory=time.monotonic)                   # 마지막 보고 시각


_PROGRESS: OrderedDict[str, _Progress] = OrderedDict()  # plan_id → 진행 기록
_PROGRESS_LOCK = threading.Lock()


def _set_progress(plan_id: str, stage: str, state: str = "running", seconds: Any = None, *_: Any, **__: Any) -> None:
    """단계 보고 한 건. ``state == "running"``이면 현재 단계로(시작), 그 밖이면 끝난 단계 목록에만 넣는다.

    병렬 구간(예상 심사평 ∥ 체크리스트→2차 검증)에서 끝난 단계가 "현재 단계"로 남지 않게, 현재 단계는
    아직 안 끝난 단계 중 가장 나중에 시작한 것이다.
    """
    if not plan_id or not isinstance(stage, str):
        return
    name = stage[:40]
    with _PROGRESS_LOCK:
        rec = _PROGRESS.get(plan_id) or _Progress()
        if state == "running":
            if name in rec.running:
                rec.running.remove(name)
            rec.running.append(name)
        else:
            if name in rec.running:
                rec.running.remove(name)
            secs = round(float(seconds), 3) if isinstance(seconds, (int, float)) else None
            rec.done.append((name, str(state)[:20], secs))
            del rec.done[:-50]
        rec.t = time.monotonic()
        _PROGRESS[plan_id] = rec
        _PROGRESS.move_to_end(plan_id)
        while len(_PROGRESS) > 256:
            _PROGRESS.popitem(last=False)


def _reset_progress(plan_id: str) -> None:
    with _PROGRESS_LOCK:
        _PROGRESS.pop(plan_id, None)


def report_stage(stage: str, state: str = "running", seconds: float | None = None) -> None:
    """파이프라인 안에서 부르면 지금 분석 중인 계획서의 진행 단계를 갱신한다(요청 문맥이 없으면 아무 일도 안 함).

    ``on_stage`` 콜백과 같은 뜻(시작은 state="running", 끝은 상태와 초). ``asyncio.to_thread``가 문맥을 복사하므로
    스레드에서 도는 동기 파이프라인에서도 부를 수 있다.
    """
    ctx = serving.current_request()
    if ctx is not None and ctx.plan_id:
        _set_progress(ctx.plan_id, stage, state, seconds)


def _progress(plan_id: str, since: float | None) -> tuple[str | None, list[tuple[str, str, float | None]]]:
    """(현재 단계, 끝난 단계들). 이번 실행(``since`` 이후)의 기록이 아니면 (None, [])."""
    with _PROGRESS_LOCK:
        rec = _PROGRESS.get(plan_id)
        if rec is None or (since is not None and rec.t < since):
            return None, []
        return (rec.running[-1] if rec.running else None), list(rec.done)


# ───────────────────────── 작업 ─────────────────────────


class JobRequest(BaseModel):
    plan_text: str = Field(..., max_length=MAX_PLAN_CHARS, description="계획서 원문")
    filename: str | None = Field(default=None, max_length=255)
    format: Literal["view", "result"] = Field(default="view", description="view: 화면 모양(ui_view), result: 분석 결과")

    @field_validator("plan_text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("plan_text가 비어 있다")
        return v


@dataclass
class Job:
    id: str
    ctx: serving.RequestCtx
    fmt: str
    filename: str | None
    lines: int
    ipk: str = ""                    # 요청한 IP(/64) 묶음 키
    shared: bool = False             # 합류·캐시 적중(새 분석 아님): 짧은 TTL, IP별 보관 수 계산에서 뺀다
    created: float = field(default_factory=time.monotonic)
    state: str = "queued"            # queued | done | error (대기·실행 구분은 대기열에서 읽는다)
    started: bool = False            # 작업 코루틴이 실행을 시작했나
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    message: str | None = None
    retry_after_s: int | None = None
    task: asyncio.Task[Any] | None = None

    @property
    def plan_id(self) -> str:
        return self.ctx.plan_id

    @property
    def finished(self) -> bool:
        return self.state in ("done", "error")


def _new_job_id() -> str:
    return secrets.token_urlsafe(24)  # 32자, 192비트


def _json(payload: dict[str, Any], code: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(payload, status_code=code, headers={"Cache-Control": "no-store", **(headers or {})})


class JobStore:
    """메모리 작업 저장소 + 실행. 이벤트 루프 하나에서 쓴다(uvicorn worker 1개 전제, serving과 같다)."""

    def __init__(self, srv: serving.Serving, config: JobsConfig | None = None, *,
                 load_pipeline: Callable[[], tuple[Callable[..., Any] | None, str, str]],
                 sample_result: Callable[[str], dict[str, Any]] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.srv, self.config = srv, config or JobsConfig.from_env()
        self.load_pipeline, self.sample_result, self.clock = load_pipeline, sample_result, clock
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self.limiter = serving.RateLimiter(self.config.rate_per_min, 60.0)
        self.poll_limiter = serving.RateLimiter(self.config.poll_per_min, 60.0)
        self.counters = {"created": 0, "done": 0, "error": 0, "expired": 0, "evicted": 0, "full_503": 0,
                         "per_ip_429": 0, "rate_429": 0, "poll_429": 0}

    # 보관 ------------------------------------------------------------
    def sweep(self) -> None:
        """TTL이 지난 끝난 작업을 버린다(결과·계획서 줄도 같이 사라진다)."""
        now = self.clock()
        for jid in [k for k, j in self._jobs.items()
                    if j.finished_at is not None and now - j.finished_at > self.ttl_for(j)]:
            del self._jobs[jid]
            serving.forget_log_secret(jid)
            self.counters["expired"] += 1

    def ttl_for(self, job: Job) -> float:
        return self.config.shared_ttl_s if job.shared else self.config.ttl_s

    def has_room(self) -> bool:
        """새 작업을 받을 자리가 있나(끝난 작업을 밀어내지 않고). /queue/status의 accepting에 쓴다."""
        self.sweep()
        return len(self._jobs) < self.config.max_jobs

    def _evict_own_finished(self, ipk: str, *, counted_only: bool = False) -> bool:
        """그 IP의 끝난 작업 중 가장 오래된 것 하나를 버린다. 다른 IP의 결과는 건드리지 않는다."""
        done = [(j.finished_at or 0.0, k) for k, j in self._jobs.items()
                if j.finished and j.ipk == ipk and not (counted_only and j.shared)]
        if not done:
            return False
        jid = min(done)[1]
        del self._jobs[jid]
        serving.forget_log_secret(jid)
        self.counters["evicted"] += 1
        return True

    def _make_room(self, ipk: str) -> str | None:
        """새 작업 자리. 없으면 거절 종류("per_ip" | "full"). 밀어내는 것은 요청한 IP의 끝난 작업뿐이다."""
        self.sweep()
        cap = self.config.per_ip
        while cap > 0 and sum(1 for j in self._jobs.values() if j.ipk == ipk and not j.shared) >= cap:
            if not self._evict_own_finished(ipk, counted_only=True):
                return "per_ip"
        while len(self._jobs) >= self.config.max_jobs:
            if not self._evict_own_finished(ipk):
                return "full"
        return None

    def get(self, job_id: str) -> Job | None:
        self.sweep()
        if not isinstance(job_id, str) or not _JOB_ID_RE.match(job_id):
            return None
        return self._jobs.get(job_id)

    def __len__(self) -> int:
        return len(self._jobs)

    # 접수 ------------------------------------------------------------
    def submit(self, req: JobRequest, ctx: serving.RequestCtx) -> JSONResponse:
        """미들웨어가 입장시킨 요청을 작업으로 바꾼다. 잡은 자리·뗀 예산은 작업 문맥으로 넘긴다.

        거절하면 자리·예산은 ctx에 남아 있으므로 미들웨어가 돌려준다.
        """
        cfg = self.srv.config
        text = req.plan_text
        if len(text) > cfg.max_plan_chars:  # serving과 이중: 파서 차이 등으로 미들웨어가 못 봤어도 여기서 막는다
            self.srv.counters["too_large_413"] += 1
            return _json(serving._err("too_large", serving.user_message("too_large", limit=cfg.max_plan_chars,
                                                                        chars=len(text)), ctx.ticket), 413)
        longest = serving.longest_token(text)
        if longest > cfg.max_token_chars:
            return _json(serving._err("long_token", serving.user_message("long_token", limit=cfg.max_token_chars,
                                                                         longest=longest), ctx.ticket), 422)
        if serving.count_lines(text) > cfg.max_plan_lines:  # SEC-7: serving과 이중
            return _json(serving._err("too_many_lines", serving.user_message("too_many_lines", limit=cfg.max_plan_lines),
                                      ctx.ticket), 422)
        ipk = serving.ip_key(ctx.ip)
        ok, retry_f = self.limiter.hit(ipk)
        if not ok:
            self.counters["rate_429"] += 1
            retry = max(int(retry_f) + 1, 1)
            return _json(serving._err("rate_limited", MESSAGES["rate"].format(retry=retry, limit=self.config.rate_per_min),
                                      ctx.ticket, retry_after_s=retry), 429, {"Retry-After": str(retry)})
        why = self._make_room(ipk)
        if why == "per_ip":
            self.counters["per_ip_429"] += 1
            return _json(serving._err("busy_ip", MESSAGES["per_ip"].format(n=self.config.per_ip), ctx.ticket,
                                      retry_after_s=30), 429, {"Retry-After": "30"})
        if why == "full":
            self.counters["full_503"] += 1
            retry = max(int(self.srv.gate.eta(self.srv.gate.waiting + 1)) or 30, 10)
            return _json(serving._err("busy", MESSAGES["full"].format(retry=retry), ctx.ticket, retry_after_s=retry),
                         503, {"Retry-After": str(retry)})
        job_ctx = serving.RequestCtx(ticket=ctx.ticket, ip=ctx.ip, path=JOBS_PATH, kind="analysis", mode="analysis",
                                     plan_id=ctx.plan_id or serving.plan_key(req.plan_text), chars=len(req.plan_text))
        job_ctx.reservation, ctx.reservation = ctx.reservation, None
        job_ctx.budget_spent, ctx.budget_spent = ctx.budget_spent, False
        job_ctx.position_at_arrival = ctx.position_at_arrival
        ctx.queue = "job"
        jid = _new_job_id()
        while jid in self._jobs:  # 사실상 일어나지 않는다
            jid = _new_job_id()
        job = Job(id=jid, ctx=job_ctx, fmt=req.format, filename=req.filename, ipk=ipk,
                  shared=job_ctx.reservation is None,  # 미들웨어가 자리를 안 잡음 = 캐시 적중·합류
                  lines=sum(1 for ln in req.plan_text.splitlines() if ln.strip()), created=self.clock())
        self._jobs[jid] = job
        serving.register_log_secret(jid)  # SEC-7: 로그에서 정확 일치로도 가린다(쪼갠·겹 인코딩 모양 포함)
        self.counters["created"] += 1
        job.task = asyncio.ensure_future(self._run(job, req.plan_text))
        st = self.status(job)
        body = {"job_id": jid, "status": "queued", "position": st["position"], "eta_s": st["eta_s"],
                "poll_after_s": self.config.poll_s, "message": st["message"], "ticket": ctx.ticket,
                "status_url": f"premortem/jobs/{jid}"}
        return _json(body, 202)

    # 실행 ------------------------------------------------------------
    def _kwargs(self, fn: Callable[..., Any], job: Job) -> dict[str, Any]:
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            return {}
        kw: dict[str, Any] = {}
        if "filename" in params:
            kw["filename"] = job.filename
        if "on_stage" in params:
            pid = job.plan_id
            kw["on_stage"] = lambda stage, state="running", seconds=None, *a, **k: _set_progress(pid, stage, state,
                                                                                            seconds)
        return kw

    async def _run(self, job: Job, plan_text: str) -> None:
        srv, ctx = self.srv, job.ctx
        token = serving._CTX.set(ctx)
        job.started = True
        try:
            fn, state, reason = self.load_pipeline()
            if fn is None:
                srv._drop_reservation(ctx)
                if state == "unavailable" and self.sample_result is not None:
                    # main.py와 같은 흐름: 파이프라인이 없으면 샘플(화면과 응답에 샘플이라고 표시된다)
                    self._finish_ok(job, self._present(job, self.sample_result(reason), state, sample=True))
                else:
                    log.warning("작업 파이프라인 없음 job=%s ticket=%s state=%s", job.id[:6], ctx.ticket, state)
                    self._finish_err(job, "unavailable", MESSAGES["unavailable"].format(ticket=ctx.ticket))
                return
            raw = getattr(fn, "__wrapped_pipeline__", fn)
            if job.plan_id not in srv.inflight:
                _reset_progress(job.plan_id)  # 새 실행(또는 캐시 적중): 이전 실행의 단계 기록을 지운다
            kwargs = self._kwargs(raw, job)
            # 입장 때 캐시·합류라 자리 없이 들어왔는데 그새 캐시·진행 중 분석이 사라졌으면 Serving.run이 관문을
            # 다시 거친다(차단·속도 제한·예산·대기열). 거절이면 AdmissionRefused + ctx.refusal.
            result = await srv.run(raw, plan_text, timeout_s=self.config.timeout_s, **kwargs)
            self._finish_ok(job, await asyncio.to_thread(self._present, job, result, state))
        except serving.AdmissionRefused:
            _code, error_code, message, retry = ctx.refusal or (503, "busy", serving.user_message("busy", retry=30), 30)
            self._finish_err(job, error_code, message, retry)
        except serving.AnalysisTimeout:
            srv.counters["timeout_504"] += 1
            self._finish_err(job, "timeout", serving.user_message("timeout", limit=int(self.config.timeout_s),
                                                                  ticket=ctx.ticket))
        except asyncio.CancelledError:
            self._finish_err(job, "internal", serving.user_message("internal", ticket=ctx.ticket))
            raise
        except Exception as exc:  # noqa: BLE001 - 어떤 예외도 사용자 문구로(종류만 로그)
            srv.counters["error_5xx"] += 1
            log.warning("작업 실패 job=%s ticket=%s kind=%s", job.id[:6], ctx.ticket, type(exc).__name__)
            self._finish_err(job, "internal", serving.user_message("internal", ticket=ctx.ticket))
        finally:
            srv._drop_reservation(ctx)
            serving._CTX.reset(token)
            log.info("job %s ticket=%s %s plan_id=%s chars=%d status=%s cache=%s queue=%s pos=%d waited_s=%.1f "
                     "run_s=%.1f total_s=%.1f", job.id[:6], ctx.ticket, serving._ip_tag(ctx.ip), ctx.plan_id[:12],
                     ctx.chars, job.state, ctx.cache, ctx.queue, ctx.position_at_arrival, ctx.waited_s, ctx.run_s,
                     self.clock() - job.created)

    def _present(self, job: Job, result: dict[str, Any], state: str, *, sample: bool = False) -> dict[str, Any]:
        ctx = job.ctx
        if job.fmt == "result":
            data = dict(result)
        else:
            info = {"chars": ctx.chars, "lines": job.lines, "filename": job.filename or ""}
            data = build_ui_view(result, filename=job.filename, sample=sample, pipeline_state=state, input_info=info)
        data = serving.scrub_ok_payload(data)
        if isinstance(data.get("_status"), dict):
            data["_status"]["server_elapsed_s"] = round(self.clock() - job.created, 3)
            data["_status"]["serving"] = {
                "ticket": ctx.ticket, "cache": ctx.cache, "queue": ctx.queue, "mode": "job",
                "position_at_arrival": ctx.position_at_arrival, "waited_s": round(ctx.waited_s, 1),
                "run_s": round(ctx.run_s, 1), "total_s": round(self.clock() - job.created, 2)}
        return data

    def _finish_ok(self, job: Job, data: dict[str, Any]) -> None:
        ctx = job.ctx
        job.shared = ctx.cache == "hit" or ctx.queue == "joined"  # 실제로 분석을 돌렸는지로 다시 정한다
        job.state, job.result, job.finished_at = "done", data, self.clock()
        job.message = MESSAGES["done"]
        self.counters["done"] += 1

    def _finish_err(self, job: Job, code: str, message: str, retry_after_s: Any = None) -> None:
        if job.finished:
            return
        job.state, job.error_code, job.finished_at = "error", code, self.clock()
        job.message = serving.scrub_public(message)
        job.retry_after_s = int(retry_after_s) if isinstance(retry_after_s, (int, float)) else None
        self.counters["error"] += 1

    # 상태 ------------------------------------------------------------
    def status(self, job: Job) -> dict[str, Any]:
        now = self.clock()
        out: dict[str, Any] = {"job_id": job.id, "ticket": job.ctx.ticket, "elapsed_s": round(now - job.created, 1),
                               "poll_after_s": self.config.poll_s, "position": 0, "eta_s": None}
        if job.finished:
            out.update(status=job.state, stage=job.state, stage_label=STAGE_LABELS[job.state], message=job.message,
                       expires_in_s=round(max(self.ttl_for(job) - (now - (job.finished_at or now)), 0.0), 1))
            if job.state == "done":
                out["result"] = job.result
                out["position"], out["eta_s"] = 0, 0.0
            else:
                out["error_code"] = job.error_code
                if job.retry_after_s is not None:
                    out["retry_after_s"] = job.retry_after_s
            return out
        gate = self.srv.gate
        t = gate.ticket_for_plan(job.plan_id)
        if t is not None and t.state == "waiting":
            pos = gate.position(t.id)
            eta = gate.eta(pos)
            out.update(status="queued", stage="queued", position=pos, eta_s=eta,
                       message=MESSAGES["queued"].format(position=pos, eta=int(round(eta))))
        elif t is not None or job.started:
            since = t.start_at if t is not None else None
            elapsed = now - since if since is not None else 0.0
            eta = round(max(gate.avg_run_s - elapsed, 1.0), 1)
            stage, done_stages = _progress(job.plan_id, since) if t is not None else (None, [])
            label = STAGE_LABELS.get(stage or "", stage) if stage else None
            if t is not None and not job.started:  # 자리는 났고 작업 코루틴이 곧 시작한다
                out.update(status="queued", stage="queued", position=0, eta_s=0.0, message=MESSAGES["starting"])
            else:
                out.update(status="running", stage=stage or "running", eta_s=eta,
                           message=(MESSAGES["running"].format(label=label, eta=int(round(eta))) if label
                                    else MESSAGES["running_plain"].format(eta=int(round(eta)))))
            if stage:
                out["stage_label"] = label
            if done_stages:
                out["stages_done"] = [{"stage": n, "label": STAGE_LABELS.get(n, n), "status": st, "elapsed_s": sec}
                                      for n, st, sec in done_stages]
        else:
            out.update(status="queued", stage="queued", position=0, eta_s=0.0, message=MESSAGES["starting"])
        out.setdefault("stage_label", STAGE_LABELS.get(out["stage"], out["stage"]))
        return out

    def summary(self) -> dict[str, Any]:
        self.sweep()
        live = sum(1 for j in self._jobs.values() if not j.finished)
        return {"jobs": len(self._jobs), "unfinished": live, "max_jobs": self.config.max_jobs,
                "ttl_s": self.config.ttl_s, "counters": dict(self.counters)}


# ───────────────────────── 라우터·설치 ─────────────────────────

router = APIRouter()


def _store(request: Request) -> JobStore | None:
    return getattr(request.app.state, "jobs", None)


@router.post(JOBS_PATH, status_code=202)
async def create_job(req: JobRequest, request: Request) -> JSONResponse:
    """분석 작업을 등록하고 바로 job_id를 돌려준다(관문은 serving 미들웨어가 이미 적용했다)."""
    store, ctx = _store(request), serving.current_request()
    if (store is None or ctx is None or ctx.mode != "analysis"
            or store.srv.kind_for(ctx.path) != "analysis" or (ctx.path.rstrip("/") or "/") != JOBS_PATH):
        # 서빙 층(관문)을 거치지 않은 요청: 관문 없는 경로가 되지 않게 받지 않는다
        rid = ctx.ticket if ctx is not None else secrets.token_hex(8)
        log.warning("관문을 거치지 않은 작업 요청 거절 request_id=%s", rid)
        return _json(serving._err("unavailable", MESSAGES["not_gated"], rid), 503)
    return store.submit(req, ctx)


@router.get(JOBS_PATH + "/{job_id}")
async def get_job(job_id: str, request: Request) -> JSONResponse:
    """작업 상태·결과. 모르는 id·보관 시간이 지난 id는 404(둘을 구분하지 않는다)."""
    store = _store(request)
    if store is not None:
        cfg = store.srv.config
        ip = serving.client_ip(request.scope, cfg.trust_proxy, cfg.xff_pick, cfg.trust_xff)
        ok, retry_f = store.poll_limiter.hit(serving.ip_key(ip))
        if not ok:
            store.counters["poll_429"] += 1
            retry = max(int(retry_f) + 1, 1)
            return _json({"status": "error", "error_code": "rate_limited", "retry_after_s": retry,
                          "message": MESSAGES["poll_rate"].format(retry=retry)}, 429, {"Retry-After": str(retry)})
    job = store.get(job_id) if store is not None else None
    if job is None:
        ttl_min = int((store.config.ttl_s if store else 900) // 60)
        return _json({"status": "error", "error_code": "job_not_found",
                      "message": MESSAGES["not_found"].format(ttl_min=ttl_min)}, 404)
    return _json(store.status(job))


def install(app: Any, *, load_pipeline: Callable[[], tuple[Callable[..., Any] | None, str, str]],
            sample_result: Callable[[str], dict[str, Any]] | None = None,
            srv: serving.Serving | None = None, config: JobsConfig | None = None) -> JobStore | None:
    """앱에 작업 API를 붙인다. serving.install(app)이 먼저 붙어 있어야 한다(없으면 붙이지 않고 경고).

    ``POST /premortem/jobs``를 서빙 층의 분석 보호 경로로 등록한다(설정으로 뺄 수 없다).
    """
    srv = srv or getattr(app.state, "serving", None)
    if srv is None:
        log.warning("작업 API를 붙이지 않음: 서빙 층(serving.install)이 없다(관문 없는 경로를 만들지 않는다)")
        return None
    srv.protect(JOBS_PATH, "analysis", async_=True)  # 작업 경로는 대기열 전체를 쓴다(동기 경로는 sync_queue_max)
    store = JobStore(srv, config, load_pipeline=load_pipeline, sample_result=sample_result)
    srv.accept_checks.append(store.has_room)  # 저장소가 차면 /queue/status accepting:false
    app.state.jobs = store
    app.include_router(router)
    return store


__all__ = ["JOBS_PATH", "Job", "JobRequest", "JobStore", "JobsConfig", "MESSAGES", "STAGE_LABELS", "install",
           "report_stage", "router"]
