"""Neumann API (FastAPI).

    python -m uvicorn neumann.api.main:app --host 127.0.0.1 --port 8000

라우트(L0)
- ``GET /``                  화면(webui/index.html)
- ``GET /fonts/...``         로컬 폰트(CDN 없음)
- ``GET /health``            서버 상태 + 단계별 모듈 import 가능 여부(정직하게). 공개 모드는 축약(SEC-7, ``_public_health``)
- ``POST /premortem``        {"plan_text": str, "filename"?: str} → 분석 결과 JSON(PremortemResult 모양)
- ``POST /premortem/view``   같은 입력 → 화면 데이터 계약(ui_view) JSON + ``_status``

분석은 E3의 ``neumann.pipeline.run_premortem``을 요청 때마다 지연 import 한다. 모듈이 아직 없으면
공용 fixture(``tests/fixtures/premortem_result.json``, 가짜 데이터)로 만든 샘플을 돌려주되,
응답(``sample``·``status``·``notices``·``_status.label``)과 화면에
"분석 파이프라인 미연결(샘플 데이터)"을 표시한다. 모듈은 있는데 import나 실행이 실패하면 샘플로 숨기지 않고
500과 오류 상태를 돌려준다.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import neumann
from neumann.api.plan_limits import PlanLimitError, check_plan_text
from neumann.api.view import SAMPLE_LABEL, build_ui_view

log = logging.getLogger("neumann.api")

WEBUI_DIR = Path(__file__).resolve().parent.parent / "webui"
REPO_ROOT = Path(__file__).resolve().parents[3]
# 파이프라인 미연결 때 쓰는 샘플: E0b 공용 fixture(plan.md 기준 PremortemResult 1건, 내용은 전부 [FAKE])
SAMPLE_PATH = REPO_ROOT / "tests" / "fixtures" / "premortem_result.json"
PIPELINE_MODULE = "neumann.pipeline"
PIPELINE_FUNC = "run_premortem"
MAX_PLAN_CHARS = 200_000
MAX_CONCURRENT = 2

# /health가 보고하는 단계별 구현 모듈(계획서 §4.0 골격). import가 되면 available.
STAGE_MODULES: dict[str, list[str]] = {
    "pipeline": [PIPELINE_MODULE],
    # 실제 모듈 이름(E2·E3 병합 뒤 기준)
    "INPUT": ["neumann.analyze.queries"],
    "EVIDENCE": ["neumann.index.search", "neumann.index.store", "neumann.analyze.extract"],
    "RISK": ["neumann.analyze.cards"],
    "REVIEW": ["neumann.analyze.review", "neumann.analyze.gate"],
    "ACTION": ["neumann.analyze.checklist", "neumann.analyze.validate"],
    "TRACE": ["neumann.api.export"],
    "llm": ["neumann.llm"],
    "models": ["neumann.models"],
    "config": ["neumann.config"],
}

_FONT_DEVICE_NAMES = frozenset({"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)
})


def _safe_font_path(path: str) -> bool:
    """Reject Windows-invalid names before stat; StaticFiles still checks containment."""
    if any(ord(char) < 32 or char in '<>:"\\|?*' for char in path):
        return False
    for part in path.split("/"):
        if not part:
            continue
        if part in {".", ".."} or part.endswith((" ", ".")) or len(part) > 255:
            return False
        if sum(2 if ord(char) > 0xFFFF else 1 for char in part) > 255:
            return False
        stem = part.split(".", 1)[0].upper()
        if stem in _FONT_DEVICE_NAMES:
            return False
    return True


class _FontFiles(StaticFiles):
    async def __call__(self, scope, receive, send) -> None:
        # Check the original decoded path: Windows normpath turns valid forward
        # separators into backslashes, and could hide unsafe dot segments.
        if not _safe_font_path(scope.get("path", "")):
            await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except (OSError, ValueError):
            # Filesystem-specific invalid names fail closed, without a path/error leak.
            return JSONResponse({"detail": "Not Found"}, status_code=404)


app = FastAPI(title="Neumann", version=neumann.__version__, description="Research pre-mortem API")
app.mount("/fonts", _FontFiles(directory=WEBUI_DIR / "fonts"), name="fonts")

from neumann.api import serving  # noqa: E402  E4-L2c 서빙 층(동시 상한·대기열·속도 제한·예산·캐시·오류 문구·로그 위생)

serving.install(app)

# 선택 라우터(PM 연결). 모듈이 아직 없으면 건너뛰고, 상태는 /health의 routers에 드러난다.
OPTIONAL_ROUTERS: tuple[str, ...] = (
    "neumann.api.export",
    "neumann.api.upload",
    "neumann.api.precomputed",
    "neumann.api.samples",
    "neumann.api.templates",
    "neumann.api.meta",
)
ROUTER_STATE: dict[str, str] = {}
for _mod_name in OPTIONAL_ROUTERS:
    try:
        app.include_router(importlib.import_module(_mod_name).router)
        ROUTER_STATE[_mod_name] = "ok"
    except ModuleNotFoundError as _exc:
        ROUTER_STATE[_mod_name] = "missing" if _exc.name == _mod_name else f"error: 의존 모듈 없음({_exc.name})"
    except Exception as _exc:  # 라우터 하나가 깨져도 서버는 뜨게 하고, 상태로 드러낸다
        ROUTER_STATE[_mod_name] = f"error: {type(_exc).__name__}"

def _server_commit() -> str:
    """서버가 뜬 코드 커밋(짧은 해시). 환경변수 NEUMANN_BUILD_COMMIT가 있으면 그 값, 없으면 git, 실패하면 unknown."""
    import os
    import subprocess

    env = os.environ.get("NEUMANN_BUILD_COMMIT", "").strip()
    if env:
        return env[:40]
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


SERVER_COMMIT = _server_commit()
SERVER_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

_sem: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(MAX_CONCURRENT)
    return _sem


class PremortemRequest(BaseModel):
    plan_text: str = Field(..., max_length=MAX_PLAN_CHARS, description="계획서 원문(붙여넣기)")
    filename: str | None = Field(default=None, max_length=255)

    @field_validator("plan_text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("plan_text가 비어 있다")
        return v


# ───────────────────────── 파이프라인 연결 ─────────────────────────


def _import_state(module: str) -> tuple[str, str]:
    """(상태, 사유). 상태: ok | missing | error. 사유에는 예외 종류와 모듈 이름만 넣는다."""
    try:
        importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == module or module.startswith(exc.name + ".")):
            return "missing", "모듈 없음"
        return "error", f"import 실패: {type(exc).__name__}({exc.name})"
    except Exception as exc:  # noqa: BLE001 - 어떤 import 실패든 상태로 보고한다
        return "error", f"import 실패: {type(exc).__name__}"
    return "ok", ""


def _load_pipeline() -> tuple[Callable[..., Any] | None, str, str]:
    """(run_premortem, 상태, 사유). 상태: connected | unavailable | error."""
    state, reason = _import_state(PIPELINE_MODULE)
    if state == "missing":
        return None, "unavailable", f"{PIPELINE_MODULE} 모듈 없음"
    if state == "error":
        return None, "error", f"{PIPELINE_MODULE} {reason}"
    fn = getattr(importlib.import_module(PIPELINE_MODULE), PIPELINE_FUNC, None)
    if not callable(fn):
        return None, "unavailable", f"{PIPELINE_MODULE}.{PIPELINE_FUNC} 없음"
    return serving.wrap_pipeline(fn), "connected", ""


def _to_jsonable(result: Any) -> dict[str, Any]:
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        result = dump(mode="json")
    out = jsonable_encoder(result)
    if not isinstance(out, dict):
        raise TypeError(f"{PIPELINE_FUNC} 반환형이 dict가 아니다: {type(result).__name__}")
    return out


async def _run_pipeline(fn: Callable[..., Any], req: PremortemRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    try:
        if "filename" in inspect.signature(fn).parameters:
            kwargs["filename"] = req.filename
    except (TypeError, ValueError):
        pass
    if inspect.iscoroutinefunction(fn):
        result = await fn(req.plan_text, **kwargs)
    else:
        result = await run_in_threadpool(fn, req.plan_text, **kwargs)
    return _to_jsonable(result)


def _failure_reason(exc: BaseException) -> str:
    """사람이 읽는 실패 사유. 예외 메시지는 쓰지 않는다(요청 헤더·키가 섞일 수 있다)."""
    tb = traceback.extract_tb(exc.__traceback__)
    where = f" @ {Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else ""
    return f"파이프라인 실행 실패: {type(exc).__name__}{where}"


def _sample_result(reason: str) -> dict[str, Any]:
    """공용 fixture 결과를 계약 모델로 검증한 뒤, 샘플임을 드러내는 표시를 붙인다."""
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    try:
        from neumann.models import PremortemResult
    except ImportError:  # models가 없으면 JSON 그대로(계약 스키마 검사는 테스트가 한다)
        pass
    else:
        data = PremortemResult.model_validate(data).model_dump(mode="json")
    data.update({
        "status": "degraded",
        "sample": True,
        "session_id": "sess_" + uuid.uuid4().hex[:12],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stages": [{
            "name": PIPELINE_FUNC, "phase": "PIPELINE", "status": "unavailable",
            "reason": f"{reason} — 샘플 데이터", "impl": "fallback:sample", "degraded": True,
            "elapsed_s": 0.0, "counts": {}, "details": {},
        }],
        "notices": [f"{SAMPLE_LABEL}: 입력한 계획서는 분석되지 않았다. 아래 값은 공용 fixture(가짜 데이터)다.",
                    *data.get("notices", [])],
    })
    return data


def _input_info(req: PremortemRequest) -> dict[str, Any]:
    return {
        "chars": len(req.plan_text),
        "lines": sum(1 for line in req.plan_text.splitlines() if line.strip()),
        "filename": req.filename or "",
    }


# ───────────────────────── 라우트 ─────────────────────────


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEBUI_DIR / "index.html", media_type="text/html", headers={"Cache-Control": "no-store"})


# WAIT-UX: 인터랙티브 대기 화면 모듈(webui/wait.js·wait.css). index.html이 상대 경로로 읽는다. 외부 CDN 없음. (출처: task/WAIT-UX 06916ab)
@app.get("/wait.js", include_in_schema=False)
def wait_js() -> FileResponse:
    return FileResponse(WEBUI_DIR / "wait.js", media_type="text/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


@app.get("/wait.css", include_in_schema=False)
def wait_css() -> FileResponse:
    return FileResponse(WEBUI_DIR / "wait.css", media_type="text/css; charset=utf-8", headers={"Cache-Control": "no-store"})


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    srv = getattr(request.app.state, "serving", None)
    if srv is not None and srv.config.public:
        return _public_health(srv)
    stages: dict[str, Any] = {}
    cache: dict[str, tuple[str, str]] = {}
    for stage, modules in STAGE_MODULES.items():
        mods = {}
        for m in modules:
            cache.setdefault(m, _import_state(m))
            state, reason = cache[m]
            mods[m] = state if not reason else f"{state}: {reason}"
        stages[stage] = {"available": all(cache[m][0] == "ok" for m in modules), "modules": mods}
    _fn, state, reason = _load_pipeline()
    return {
        "status": "ok",
        "version": neumann.__version__,
        "commit": SERVER_COMMIT,
        "started_at": SERVER_STARTED_AT,
        "pipeline": {"state": state, "reason": reason, "mode": "pipeline" if state == "connected" else (
            "sample" if state == "unavailable" else "error"), "label": SAMPLE_LABEL if state == "unavailable" else ""},
        "stages": stages,
        "routers": dict(ROUTER_STATE),
        "llm": _llm_state(),
    }


def _public_health(srv: Any) -> dict[str, Any]:
    """공개 모드(SEC-7) /health: 운영·화면에 필요한 값만. 모듈별 import 상태·라우터·키 존재 여부·실패 사유·기동 시각은 뺀다.

    남기는 값: status·version·commit, pipeline.state/mode/label(화면 머리 표시·녹화 판정·터널 점검),
    llm.effective/model/live_llm_ok(OPS-tun 점검), accepting(새 분석을 받는지).
    """
    _fn, state, _reason = _load_pipeline()
    llm = _llm_state()
    try:
        accepting = bool(srv.queue_status().get("accepting"))
    except Exception:  # noqa: BLE001 - 상태 확인이 /health를 깨지 않게
        accepting = False
    return {
        "status": "ok",
        "version": neumann.__version__,
        "commit": SERVER_COMMIT,
        "pipeline": {"state": state, "mode": "pipeline" if state == "connected" else (
            "sample" if state == "unavailable" else "error"), "label": SAMPLE_LABEL if state == "unavailable" else ""},
        "llm": {k: llm.get(k) for k in ("effective", "model", "live_llm_ok")},
        "accepting": accepting,
    }


def _llm_state() -> dict[str, Any]:
    """실제 호출이 열려 있는지(SEC-3). 키 값·설정 전체는 싣지 않는다."""
    try:
        from neumann.config import astra_allowed, get_settings, guard_model, live_llm_allowed

        s = get_settings()
        allowed = live_llm_allowed()
        requested = s.llm_provider
        key_present = s.has_openai_key
        live = requested == "openai" and allowed
        return {
            "provider_requested": requested,
            "live_llm_ok": allowed,
            "key_present": key_present,
            # openai_no_key: 호출마다 config_error → 비상 규칙 경로로 강등된다
            "effective": ("openai" if key_present else "openai_no_key") if live else "mock",
            "model": guard_model(s.llm_model, log=False) if live else "",
            "astra_allowed": astra_allowed(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__}


@app.post("/premortem")
async def premortem(req: PremortemRequest) -> JSONResponse:
    try:
        check_plan_text(req.plan_text)
    except PlanLimitError as exc:
        return JSONResponse(exc.detail, status_code=exc.status_code)
    fn, state, reason = _load_pipeline()
    if fn is None and state == "unavailable":
        return JSONResponse(_sample_result(reason))
    if fn is None:
        return JSONResponse({"status": "error", "pipeline": state, "reason": reason}, status_code=500)
    try:
        result = await _run_pipeline(fn, req)
    except Exception as exc:  # noqa: BLE001
        why = _failure_reason(exc)
        log.error(why)
        return JSONResponse({"status": "error", "pipeline": state, "reason": why}, status_code=500)
    return JSONResponse(result)


@app.post("/premortem/view")
async def premortem_view(req: PremortemRequest) -> JSONResponse:
    try:
        check_plan_text(req.plan_text)
    except PlanLimitError as exc:
        return JSONResponse(exc.detail, status_code=exc.status_code)
    t0 = time.perf_counter()
    info = _input_info(req)
    fn, state, reason = _load_pipeline()
    code = 200
    if fn is None and state == "unavailable":
        view = build_ui_view(_sample_result(reason), sample=True, pipeline_state=state, input_info=info)
    elif fn is None:
        view, code = build_ui_view(None, pipeline_state=state, error=reason, input_info=info), 500
    else:
        try:
            result = await _run_pipeline(fn, req)
        except Exception as exc:  # noqa: BLE001
            why = _failure_reason(exc)
            log.error(why)
            view, code = build_ui_view(None, pipeline_state=state, error=why, input_info=info), 500
        else:
            view = build_ui_view(result, filename=req.filename, pipeline_state=state, input_info=info)
    view["_status"]["server_elapsed_s"] = round(time.perf_counter() - t0, 3)
    return JSONResponse(view, status_code=code)


# ───────────────────────── 작업 방식(E4-L2d) ─────────────────────────
# POST /premortem/jobs → 곧바로 job_id, GET /premortem/jobs/{id} → 상태·진행 단계·결과(메모리, TTL 뒤 폐기).
# 터널(Cloudflare)의 응답 시간 상한(약 100초)을 넘지 않게 긴 분석을 작업으로 돌린다. 관문은 serving과 같다.
from neumann.api import jobs  # noqa: E402

jobs.install(app, load_pipeline=lambda: _load_pipeline(), sample_result=lambda reason: _sample_result(reason))

# ───────────────────────── 수정 권고(E3-L2r) ─────────────────────────
# POST /premortem/revise(카드별 해석·대응·수정안) · POST /premortem/revise/assemble(통합본·md·docx). 관문은 serving과 같다.
from neumann.api import revise as revise_api  # noqa: E402

revise_api.install(app)
from neumann.api import finalize as finalize_api  # noqa: E402

finalize_api.install(app)
