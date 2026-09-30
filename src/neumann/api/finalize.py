"""One gated, idempotent assembly and final validation action (process-local cache)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Request
from pydantic import Field, ValidationError

from neumann.api import revise, serving

FINALIZE_PATH = "/premortem/revise/finalize"
router = APIRouter()


class FinalizeRequest(revise.AssembleRequest):
    submission_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    checks: list[dict[str, Any]] | None = Field(default=None, max_length=16)
    confirmed_text: str | None = Field(default=None, min_length=1, max_length=revise.MAX_PLAN_CHARS)
    confirmed_base_id: str | None = Field(default=None, max_length=100)


@dataclass
class _Entry:
    digest: str
    created: float = field(default_factory=time.monotonic)
    done: threading.Event = field(default_factory=threading.Event)
    response: tuple[dict[str, Any], int] | None = None


class _Cache:
    """Bounded to 64 submissions for 10 minutes; pending entries cannot be evicted."""
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.entries: OrderedDict[str, _Entry] = OrderedDict()

    def claim(self, key: str, digest: str) -> tuple[_Entry | None, str]:
        with self.lock:
            now = time.monotonic()
            for old, entry in list(self.entries.items()):
                if entry.done.is_set() and now - entry.created > 600:
                    del self.entries[old]
            entry = self.entries.get(key)
            if entry is not None:
                return entry, "duplicate" if entry.digest == digest else "conflict"
            while len(self.entries) >= 64:
                old = next((k for k, v in self.entries.items() if v.done.is_set()), None)
                if old is None:
                    return None, "full"
                del self.entries[old]
            entry = _Entry(digest)
            self.entries[key] = entry
            return entry, "leader"

    def finish(self, entry: _Entry, body: dict[str, Any], code: int) -> None:
        with self.lock:
            entry.response = body, code
            entry.done.set()


def finalize_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from neumann.analyze.finalize import finalize_plan as engine
    return engine(*args, **kwargs)


def run_finalization(req: FinalizeRequest, cancelled: threading.Event) -> dict[str, Any]:
    assembly_req = revise.AssembleRequest.model_validate(req.model_dump(exclude={"submission_id", "checks", "confirmed_text", "confirmed_base_id"}))
    assembly_req.polish = False
    assembled = revise.run_assembly(assembly_req, cancel_event=cancelled)
    if req.confirmed_text is not None and req.confirmed_base_id != assembled["revised_plan_id"]:
        raise ValueError("confirmed manuscript assembly changed")
    text = req.confirmed_text if req.confirmed_text is not None else assembled["revised_text"]
    final = finalize_plan(text, result=req.result, checks=req.checks, cancel_event=cancelled)
    if req.confirmed_text is not None:
        final.setdefault("notices", []).append("연구자가 확정한 문안; 새 내용의 출처는 확인되지 않음")
    from neumann.analyze.revise import check_cancelled
    check_cancelled(cancelled)
    verified = revise.assembly_verified(assembly_req)
    out = serving.scrub_ok_payload({"version": "finalization@v1", "assembled": assembled,
        "finalization": final, "final_text": final["final_text"],
        "origin": "server_signed" if verified else "client_submitted_unverified"})
    out["finalization_sig"] = revise.sign_payload("finalization", out) if verified else None
    return out


@router.post(FINALIZE_PATH)
async def finalization(request: Request):
    gate = revise._Gate(request, FINALIZE_PATH)
    refused = gate.refusal_response()
    if refused is not None:
        return refused
    ticket = gate.ctx.ticket
    try:
        req = FinalizeRequest.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        return revise._json(serving._err("invalid_request", serving.user_message("invalid"), ticket,
            fields=revise._errors(exc) if isinstance(exc, ValidationError) else []), 422)
    from neumann.analyze.revise import validate_revision
    if validate_revision(req.revision):
        return revise._json(serving._err("invalid_request", revise.MESSAGES["revision_invalid"], ticket), 422)
    pid = req.revision.get("plan_id")
    if revise.plan_id_of(req.plan_text) != pid:
        return revise._json(serving._err("plan_mismatch", revise.MESSAGES["plan_mismatch"], ticket), 422)
    if req.result is not None:
        from neumann.models import PremortemResult
        try:
            result = PremortemResult.model_validate(req.result)
        except ValidationError as exc:
            return revise._json(serving._err("invalid_request", revise.MESSAGES["result_invalid"], ticket,
                fields=revise._errors(exc)[:20]), 422)
        if result.plan_id != pid:
            return revise._json(serving._err("plan_mismatch", revise.MESSAGES["plan_mismatch"], ticket), 422)
    try:
        from neumann.analyze.assemble import assemble_revised_plan
        preflight = assemble_revised_plan(req.plan_text, req.revision, req.decisions, result=req.result, regate=True)
        if req.confirmed_text is not None:
            from neumann.analyze.revise import CONTROL_RE, UNSAFE_MARKUP_RE, contains_identity
            from neumann.pipeline import mask_extra_pii
            from neumann.models import contains_pii
            masked, _ = mask_extra_pii(req.confirmed_text)
            if (req.confirmed_base_id != preflight["revised_plan_id"] or not req.confirmed_text.strip()
                    or contains_pii(req.confirmed_text) or contains_identity(req.confirmed_text)
                    or masked != req.confirmed_text or CONTROL_RE.search(req.confirmed_text)
                    or UNSAFE_MARKUP_RE.search(req.confirmed_text)):
                raise ValueError("invalid confirmed manuscript")
    except ValueError:
        return revise._json(serving._err("invalid_revision_proposal", "수정 제안의 검사를 통과하지 못했습니다.", ticket), 422)
    cache: _Cache = request.app.state.finalization_cache
    digest = hashlib.sha256(json.dumps(req.model_dump(), sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode()).hexdigest()
    entry, kind = cache.claim(req.submission_id, digest)
    if kind == "conflict":
        return revise._json(serving._err("submission_conflict", "같은 요청 번호에 다른 수정 내용이 있습니다.", ticket), 409)
    if kind == "full":
        return revise._json(serving._err("busy", "수정 확정 요청이 많습니다. 잠시 뒤 다시 시도해 주세요.", ticket), 503)
    limit = revise._timeout_s()
    if kind == "duplicate":
        # Refund this request's unused admission reservation before waiting for its leader.
        gate.srv._drop_reservation(gate.ctx)
        started = time.monotonic()
        while not entry.done.is_set():
            if time.monotonic() - started > limit:
                return revise._timeout_response(gate.ctx, limit)
            await asyncio.sleep(0.02)
        body, code = entry.response
        return revise._json(body, code)
    try:
        body = await gate.run(lambda cancelled: run_finalization(req, cancelled), limit)
        code = 200
    except serving.AnalysisTimeout:
        response = revise._timeout_response(gate.ctx, limit)
        body, code = json.loads(response.body), response.status_code
    except asyncio.CancelledError:
        cache.finish(entry, serving._err("cancelled", "수정 확정 요청이 취소되었습니다.", ticket), 503)
        raise
    except ValueError:
        body, code = serving._err("invalid_finalization", "수정 확정 입력 또는 검사 조건이 유효하지 않습니다.", ticket), 422
    except Exception as exc:
        response = revise._internal_response(gate.ctx, exc)
        body, code = json.loads(response.body), response.status_code
    cache.finish(entry, body, code)
    return revise._json(body, code)


def install(app: Any) -> bool:
    srv = getattr(app.state, "serving", None)
    if srv is None:
        return False
    srv.protect(FINALIZE_PATH, "analysis")
    app.state.finalization_cache = _Cache()
    app.include_router(router)
    return True
