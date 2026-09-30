"""수정 권고 API(E3-L2r): 분석 결과 뒤에 붙는 뒷단 두 개.

    POST /premortem/revise           {"result": <PremortemResult JSON>, "plan_text": "...", "card_ids": ["card_…"] | null}
                                     → 200 contracts/revision.schema.json (카드별 해석·대응·수정안·질문·게이트·비용)
    POST /premortem/revise/assemble  {"plan_text": "...", "revision": <위 응답>, "decisions": [{"edit_id", "decision":
                                      "채택|수정|기각", "revised_text"?, "note"?}], "result"?: <PremortemResult>,
                                      "polish": false, "format": "json"|"md"|"docx", "title"?: "…"}
                                     → 200 contracts/revised_plan.schema.json(+ markdown 3판) · text/markdown · .docx

관문(E4-L2c·E4-L2d와 같은 서빙 층, 우회 경로 없음)
- 두 경로는 서빙 층의 **분석(analysis) 보호 경로로 코드가 등록**한다(설정으로 뺄 수 없다): 바이트·글자 상한(413), 긴 토큰(422),
  차단 스위치(503), IP 속도 제한(429), 일일 예산(503), 동시 상한·대기열(503). 미들웨어가 자리를 잡지 않은 요청(같은 계획서의
  분석이 캐시·진행 중이라 통과한 경우)은 핸들러가 같은 입장 검사(`Serving.admit_new`)를 다시 거친다.
- 실행은 분석 관문의 자리(`Gate.acquire`)를 얻은 뒤 스레드에서 돈다. 동기 상한 `NEUMANN_REVISE_TIMEOUT_S`(기본 90초, 터널
  응답 상한 아래). 넘으면 504 사용자 문구. 미들웨어를 거치지 않은 요청은 503으로 받지 않는다.
- 작업(jobs) 방식 연결: `run_revision(payload)`·`run_assembly(payload)`는 순수 동기 함수라 E4-L2d `JobStore`에 작업 종류를
  하나 더 두면 그대로 감쌀 수 있다(이번 과제는 동기 경로만).

정직성
- `plan_text`의 plan_id(같은 정규화·가림)가 `result.plan_id`와 다르면 422(다른 계획서의 결과에 수정안을 붙이지 않는다).
- 서버 서명: `neumann.api.signing`(E4-L2f)이 있으면 응답에 `revision_sig`·`revised_plan_sig`(같은 HMAC 키, 도메인만 다름)를
  싣는다. 없으면 null. 내보내기(export)는 서명이 확인되면 server_signed, 아니면 client_submitted_unverified로 적는다.
- 응답 본문은 계약 JSON뿐이다(예외 문구·경로·키 없음). 리뷰어 신원 정보는 없다.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from neumann.api import serving

log = logging.getLogger("neumann.revise")

REVISE_PATH = "/premortem/revise"
ASSEMBLE_PATH = "/premortem/revise/assemble"
MAX_PLAN_CHARS = 200_000
MAX_CARD_IDS = 8
MAX_DECISIONS = 200
DEFAULT_TIMEOUT_S = 90.0
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

MESSAGES = {
    "not_gated": "지금은 수정 권고를 받을 수 없습니다. 잠시 뒤 다시 시도해 주세요.",
    "plan_mismatch": "보낸 계획서 본문이 분석 결과의 계획서와 다릅니다. 분석에 쓴 계획서를 그대로 보내 주세요.",
    "result_invalid": "분석 결과(result)가 계약(PremortemResult)과 맞지 않습니다.",
    "revision_invalid": "수정 권고(revision)가 계약(revision.schema.json)과 맞지 않습니다.",
    "timeout": "수정 권고가 {limit}초 안에 끝나지 않았습니다. 잠시 뒤 다시 시도해 주세요(요청 번호 {ticket}).",
    "internal": "처리 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요. 계속되면 요청 번호 {ticket}를 알려 주세요.",
    "busy": "지금 분석 요청이 많아 대기열이 가득 찼습니다. 약 {retry}초 뒤에 다시 시도해 주세요.",
}


# ───────────────────────── 요청 모양 ─────────────────────────


class ReviseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: dict[str, Any] = Field(..., description="분석 결과 JSON(POST /premortem 응답 또는 화면 응답의 result)")
    result_sig: str | None = Field(default=None, max_length=200)
    plan_text: str = Field(..., max_length=MAX_PLAN_CHARS, description="분석에 쓴 계획서 원문(결과의 plan_id와 같아야 한다)")
    card_ids: list[str] | None = Field(default=None, max_length=MAX_CARD_IDS, description="카드 id 목록. 없으면 결과의 모든 카드")

    @field_validator("plan_text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("plan_text가 비어 있다")
        return v

    @field_validator("card_ids")
    @classmethod
    def _ids(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out = [x.strip() for x in v if isinstance(x, str) and x.strip() and len(x) <= 80]
        return out or None


class AssembleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_text: str = Field(..., max_length=MAX_PLAN_CHARS)
    revision: dict[str, Any] = Field(..., description="POST /premortem/revise 응답")
    decisions: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_DECISIONS)
    result: dict[str, Any] | None = Field(default=None, description="분석 결과(있으면 각주에 카드 근거 인용을 붙인다)")
    result_sig: str | None = Field(default=None, max_length=200)
    revision_sig: str | None = Field(default=None, max_length=200)
    polish: bool = Field(default=False, description="문장 다듬기(LLM 1회). 기본 끔")
    format: Literal["json", "md", "docx"] = "json"
    title: str | None = Field(default=None, max_length=200)

    @field_validator("plan_text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("plan_text가 비어 있다")
        return v


# ───────────────────────── 서명(E4-L2f signing이 있을 때만) ─────────────────────────


def sign_payload(kind: str, data: Mapping[str, Any]) -> str | None:
    """E4-L2f 공개 헬퍼로만 서명한다. 모듈·헬퍼가 없으면 서명하지 않는다."""
    try:
        from neumann.api import signing
    except ImportError:
        return None
    sign = getattr(signing, "sign_payload", None)
    if not callable(sign):
        return None
    return sign(kind, data)


def verify_payload(kind: str, data: Mapping[str, Any], sig: Any) -> bool:
    try:
        from neumann.api import signing
    except ImportError:
        return False
    verify = getattr(signing, "verify_payload", None)
    return bool(callable(verify) and verify(kind, data, sig))


def verify_result(result: Any, sig: Any) -> bool:
    if result is None:
        return False
    try:
        from neumann.api.signing import verify_result as verify
    except ImportError:
        return False
    return verify(result, sig)


def revision_verified(revision: Mapping[str, Any], sig: Any = None) -> bool:
    body = {k: v for k, v in revision.items() if k != "revision_sig"}
    return verify_payload("revision", body, sig if sig is not None else revision.get("revision_sig"))


def assembly_verified(req: AssembleRequest) -> bool:
    return verify_result(req.result, req.result_sig) and revision_verified(req.revision, req.revision_sig)


# ───────────────────────── 실행(동기, 작업 방식으로 감쌀 수 있게) ─────────────────────────


def plan_id_of(plan_text: str) -> str:
    """파이프라인과 같은 정규화·가림(이메일·ORCID·전화·주민번호) 뒤의 sha256."""
    from neumann.models import PlanDocument
    from neumann.pipeline import mask_extra_pii

    masked, _ = mask_extra_pii(plan_text)
    return PlanDocument.from_text(masked, "revise").plan_id


def run_revision(req: ReviseRequest, *, provider: str | None = None,
                 cancel_event: threading.Event | None = None) -> dict[str, Any]:
    """카드별 수정 권고(순수 동기). API·작업 방식 공용."""
    from neumann.analyze.revise import revise_result

    out = revise_result(req.result, card_ids=req.card_ids, plan_text=req.plan_text, provider=provider, cancel_event=cancel_event)
    verified = verify_result(req.result, req.result_sig)
    out["origin"] = "server_signed" if verified else "client_submitted_unverified"
    if not verified:
        out["notices"].append("입력 분석 결과의 서버 서명을 확인하지 못했다. 근거 원문·출처는 미확인이다.")
    out = serving.scrub_ok_payload(out)
    out["revision_sig"] = sign_payload("revision", out) if verified else None
    return out


def run_assembly(req: AssembleRequest, *, provider: str | None = None, timeout_s: float | None = None,
                 cancel_event: threading.Event | None = None) -> dict[str, Any]:
    """통합(+선택 다듬기) + 마크다운 3판(순수 동기)."""
    from neumann.analyze import assemble as asm
    from neumann.analyze.review import provider_llm_call
    from neumann.llm import make_llm, provider_generator, task_options
    from neumann.analyze.revise import check_cancelled

    check_cancelled(cancel_event)
    out = asm.assemble_revised_plan(req.plan_text, req.revision, req.decisions, result=req.result, regate=True)
    verified = assembly_verified(req)
    out["origin"] = "server_signed" if verified else "client_submitted_unverified"
    if not verified:
        out["notices"].append("입력 결과·수정 권고의 서버 서명을 확인하지 못했다. 생성자·모델 표기와 근거 출처는 미확인이다.")
    generator: str | None = None
    model: str | None = None
    if req.polish:
        check_cancelled(cancel_event)
        llm = make_llm(None, provider)
        opts = task_options(asm.POLISH_TASK, None)
        try:
            gen = provider_generator(llm)
            call = provider_llm_call(llm, task=asm.POLISH_TASK, timeout_s=min(opts["timeout_s"], timeout_s or opts["timeout_s"]),
                                     generator=gen)
        except ValueError:
            call = None
        out = asm.polish_revised_plan(out, call, effort=opts["effort"])
        if out["polish"].get("applied"):
            generator, model = out["polish"].get("generator"), out["polish"].get("model")
    rev_model = req.revision.get("model") if isinstance(req.revision, Mapping) else None
    check_cancelled(cancel_event)
    rev_gen = req.revision.get("generator") if isinstance(req.revision, Mapping) else None
    ev = asm.evidence_lookup(req.result, req.revision)
    label_model = model or (rev_model if verified and isinstance(rev_model, str) else None)
    label_gen = generator or (rev_gen if verified and isinstance(rev_gen, str) else "client_submitted_unverified")
    out["markdown"] = asm.render_markdown(out, ev, model=label_model, generator=label_gen, title=req.title or "수정된 연구계획서")
    out["label"] = asm._label_line(label_model, out["generated_at"], label_gen)
    out["docx_available"] = True
    out = serving.scrub_ok_payload(out)
    out["revised_plan_sig"] = sign_payload("revised-plan", {k: v for k, v in out.items() if k != "revised_plan_sig"}) if verified else None
    return out


def build_docx_bytes(req: AssembleRequest, assembled: Mapping[str, Any]) -> bytes:
    from neumann.analyze import assemble as asm

    ev = asm.evidence_lookup(req.result, req.revision)
    pol = assembled.get("polish", {}) if isinstance(assembled.get("polish"), Mapping) else {}
    verified = assembly_verified(req)
    rev_model = req.revision.get("model") if isinstance(req.revision, Mapping) else None
    rev_gen = req.revision.get("generator") if isinstance(req.revision, Mapping) else None
    return asm.build_docx(assembled, ev, model=(pol.get("model") if pol.get("applied") else None) or (rev_model if verified and isinstance(rev_model, str) else None),
                          generator=(pol.get("generator") if pol.get("applied") else None) or (rev_gen if verified and isinstance(rev_gen, str) else "client_submitted_unverified"),
                          title=req.title or "수정된 연구계획서")


# ───────────────────────── 라우터 ─────────────────────────

router = APIRouter()


def _timeout_s() -> float:
    return serving._env_num("NEUMANN_REVISE_TIMEOUT_S", DEFAULT_TIMEOUT_S, 0.05, 3600)


def _json(payload: dict[str, Any], code: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(payload, status_code=code, headers={"Cache-Control": "no-store", **(headers or {})})


def _errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors(include_input=False, include_url=False)]


class _Gate:
    """핸들러가 서빙 층의 분석 관문을 그대로 거치게 한다(입장 검사 → 자리 얻기 → 실행 → 반납)."""

    def __init__(self, request: Request, path: str) -> None:
        self.srv: serving.Serving | None = getattr(request.app.state, "serving", None)
        self.ctx = serving.current_request()
        self.path = path
        self.ticket: serving.Ticket | None = None

    def refusal_response(self) -> JSONResponse | None:
        srv, ctx = self.srv, self.ctx
        if (srv is None or ctx is None or ctx.mode != "analysis" or srv.kind_for(ctx.path) != "analysis"
                or (ctx.path.rstrip("/") or "/") != self.path):
            rid = ctx.ticket if ctx is not None else "no-ticket"
            log.warning("관문을 거치지 않은 수정 권고 요청 거절 request_id=%s", rid)
            return _json(serving._err("unavailable", MESSAGES["not_gated"], rid), 503)
        if ctx.reservation is None and not ctx.internal:
            refusal = srv.admit_new(ctx)  # 캐시·합류로 통과한 요청: 두 번째 입장 검사(차단·속도 제한·예산·대기열)
            if refusal is not None:
                code, error_code, message, retry = refusal
                ctx.refusal, ctx.error_kind = refusal, "refused"  # 미들웨어가 같은 거절 응답(_refusal_reply)으로 바꿔 보낸다
                err = serving._err(error_code, message, ctx.ticket, retry_after_s=retry)
                return _json(err, code, {"Retry-After": str(retry)})
        # 검증을 마치기 전에는 미들웨어가 예약·예산을 소유한다.
        # 모든 422 조기 반환은 _drop_reservation으로 자동 취소·환불된다.
        self.ticket = ctx.reservation
        if self.ticket is not None:
            self.ticket.plan_id = f"revise:{ctx.plan_id[:12]}"  # 작업(jobs) 상태 조회가 분석 자리로 오인하지 않게
        return None

    async def run(self, fn: Callable[[threading.Event], Any], timeout_s: float) -> Any:
        assert self.srv is not None and self.ctx is not None
        t = self.ticket
        gate = self.srv.gate
        started = time.monotonic()
        if t is not None:
            try:
                await asyncio.wait_for(gate.acquire(t), timeout=timeout_s)
            except asyncio.TimeoutError:
                self.srv._drop_reservation(self.ctx)
                raise serving.AnalysisTimeout("queue wait") from None
        self.ctx.reservation, self.ctx.budget_spent = None, False
        cancel_event = threading.Event()
        worker = asyncio.create_task(asyncio.to_thread(fn, cancel_event))

        def finished(task: asyncio.Task[Any]) -> None:
            if t is not None:
                gate.release(t, None)  # 스레드가 끝날 때까지 자리를 유지한다.
            if not task.cancelled():
                task.exception()  # 504 뒤 협력 취소 예외를 회수한다.

        worker.add_done_callback(finished)
        try:
            remaining = max(timeout_s - (time.monotonic() - started), 0.01)
            return await asyncio.wait_for(asyncio.shield(worker), timeout=remaining)
        except asyncio.TimeoutError:
            cancel_event.set()
            raise serving.AnalysisTimeout("revise time limit") from None
        except BaseException:
            cancel_event.set()
            raise


def _timeout_response(ctx: serving.RequestCtx | None, limit: float) -> JSONResponse:
    ticket = ctx.ticket if ctx is not None else "-"
    if ctx is not None:
        ctx.error_kind = "timeout"
    return _json(serving._err("timeout", MESSAGES["timeout"].format(limit=int(limit), ticket=ticket), ticket), 504)


def _internal_response(ctx: serving.RequestCtx | None, exc: BaseException) -> JSONResponse:
    ticket = ctx.ticket if ctx is not None else "-"
    log.warning("수정 권고 실패 ticket=%s kind=%s", ticket, type(exc).__name__)
    return _json(serving._err("internal", MESSAGES["internal"].format(ticket=ticket), ticket), 500)


@router.post(REVISE_PATH)
async def premortem_revise(request: Request) -> Response:
    """카드별 수정 권고. 본문: result(분석 결과) + plan_text + card_ids(선택)."""
    gate = _Gate(request, REVISE_PATH)
    refused = gate.refusal_response()
    if refused is not None:
        return refused
    ctx = gate.ctx
    ticket = ctx.ticket if ctx is not None else "-"
    try:
        req = ReviseRequest.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        fields = _errors(exc) if isinstance(exc, ValidationError) else []
        return _json(serving._err("invalid_request", serving.user_message("invalid"), ticket, fields=fields), 422)
    try:
        from neumann.models import PremortemResult

        result = PremortemResult.model_validate(req.result)
    except ValidationError as exc:
        return _json(serving._err("invalid_request", MESSAGES["result_invalid"], ticket, fields=_errors(exc)[:20]), 422)
    if plan_id_of(req.plan_text) != result.plan_id:
        return _json(serving._err("plan_mismatch", MESSAGES["plan_mismatch"], ticket), 422)
    from neumann.analyze.revise import select_cards

    try:
        select_cards(result, req.card_ids)
    except ValueError:
        return _json(serving._err("too_many_cards", "수정 권고는 요청당 최대 8개 카드만 가능합니다. 카드 id를 선택해 주세요.", ticket), 422)
    limit = _timeout_s()
    try:
        out = await gate.run(lambda cancelled: run_revision(req, cancel_event=cancelled), limit)
    except serving.AnalysisTimeout:
        return _timeout_response(ctx, limit)
    except Exception as exc:  # noqa: BLE001
        return _internal_response(ctx, exc)
    return _json(serving.scrub_ok_payload(out))


@router.post(ASSEMBLE_PATH)
async def premortem_revise_assemble(request: Request) -> Response:
    """통합본(수정된 계획서 한 부). format=json(계약+마크다운 3판) · md(각주 판+이력) · docx."""
    gate = _Gate(request, ASSEMBLE_PATH)
    refused = gate.refusal_response()
    if refused is not None:
        return refused
    ctx = gate.ctx
    ticket = ctx.ticket if ctx is not None else "-"
    try:
        req = AssembleRequest.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        fields = _errors(exc) if isinstance(exc, ValidationError) else []
        return _json(serving._err("invalid_request", serving.user_message("invalid"), ticket, fields=fields), 422)
    from neumann.analyze.revise import validate_revision

    if validate_revision(req.revision):
        return _json(serving._err("invalid_request", MESSAGES["revision_invalid"], ticket), 422)
    rev_pid = req.revision.get("plan_id")
    if isinstance(rev_pid, str) and rev_pid and plan_id_of(req.plan_text) != rev_pid:
        return _json(serving._err("plan_mismatch", MESSAGES["plan_mismatch"], ticket), 422)
    if req.result is not None:
        try:
            from neumann.models import PremortemResult

            res = PremortemResult.model_validate(req.result)
        except ValidationError as exc:
            return _json(serving._err("invalid_request", MESSAGES["result_invalid"], ticket, fields=_errors(exc)[:20]), 422)
        if res.plan_id != rev_pid:
            return _json(serving._err("plan_mismatch", MESSAGES["plan_mismatch"], ticket), 422)
    try:
        from neumann.analyze import assemble as asm

        # 실행·예산 소비 전에 검사한다. worker도 같은 경계를 다시 확인한다.
        asm.assemble_revised_plan(req.plan_text, req.revision, req.decisions, result=req.result, regate=True)
    except ValueError:
        return _json(serving._err("invalid_revision_proposal", "수정 제안의 근거·수치·개인정보 검사를 통과하지 못했습니다.", ticket), 422)
    limit = _timeout_s()

    def assemble_output(cancelled: threading.Event) -> tuple[dict[str, Any], bytes | None]:
        from neumann.analyze.revise import check_cancelled

        out = run_assembly(req, timeout_s=limit, cancel_event=cancelled)
        check_cancelled(cancelled)
        data = build_docx_bytes(req, out) if req.format == "docx" else None
        return out, data

    try:
        out, data = await gate.run(assemble_output, limit)
    except serving.AnalysisTimeout:
        return _timeout_response(ctx, limit)
    except ValueError:
        return _json(serving._err("invalid_revision_proposal", "수정 제안의 근거·수치·개인정보 검사를 통과하지 못했습니다.", ticket), 422)
    except Exception as exc:  # noqa: BLE001
        return _internal_response(ctx, exc)
    short = re.sub(r"[^0-9A-Za-z_-]", "", str(out.get("revised_plan_id", "")))[:12] or "plan"
    if req.format == "docx":
        return Response(content=data, media_type=DOCX_MEDIA, headers={
            "Content-Disposition": f'attachment; filename="neumann_revised_plan_{short}.docx"', "Cache-Control": "no-store",
            "X-Neumann-Changes": str(out["stats"]["applied"]), "X-Neumann-Conflicts": str(out["stats"]["conflicts"])})
    if req.format == "md":
        md = out["markdown"]["footnoted"] + "\n\n" + out["markdown"]["history"]
        return Response(content=md, media_type="text/markdown; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="neumann_revised_plan_{short}.md"', "Cache-Control": "no-store"})
    return _json(serving.scrub_ok_payload(out))


def install(app: Any, *, srv: serving.Serving | None = None) -> bool:
    """앱에 수정 권고 API를 붙인다. 서빙 층(serving.install)이 먼저 있어야 한다(없으면 붙이지 않고 경고: 관문 없는 경로 금지)."""
    srv = srv or getattr(app.state, "serving", None)
    if srv is None:
        log.warning("수정 권고 API를 붙이지 않음: 서빙 층(serving.install)이 없다")
        return False
    srv.protect(REVISE_PATH, "analysis")
    srv.protect(ASSEMBLE_PATH, "analysis")
    app.include_router(router)
    return True


__all__ = ["ASSEMBLE_PATH", "REVISE_PATH", "AssembleRequest", "ReviseRequest", "build_docx_bytes", "install", "plan_id_of",
           "router", "run_assembly", "run_revision", "sign_payload", "verify_payload"]
