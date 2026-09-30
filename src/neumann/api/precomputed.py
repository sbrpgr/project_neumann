"""사전 계산본(데모 오프라인 폴백) 조회 라우터.

    from neumann.api.precomputed import router as precomputed_router
    app.include_router(precomputed_router)
    # GET /premortem/precomputed             목록(항목마다 무결성 검사 결과)
    # GET /premortem/precomputed/{plan_id}   단건(plan_id 64hex 또는 데모 이름 예: plan_elife_neuro)

데이터: 공유 데이터 폴더 `<NEUMANN_DATA_DIR>/precomputed/` — `scripts/precompute_demo.py`가 만든다.
  manifest.json      항목별 plan_id·데모 이름·파일 이름·sha256·생성 시각·생성 방식별 카드 수·소요 시간
  <plan_id>.json     PremortemResult JSON

규칙
- 무결성: 파일 바이트의 sha256이 매니페스트와 다르면 404(변조 감지). 결과 안의 plan_id가 매니페스트와 달라도 404.
- 경로: 파일 이름은 요청 값이 아니라 매니페스트에서만 가져오고, 이름 형식과 폴더 안인지 확인한다(경로 조작 차단).
- 표시: 단건 응답의 `notices` 맨 앞, `manifest.precomputed`, 응답 헤더에 "사전 계산본(생성 시각)"을 넣는다.
  실시간 분석 결과처럼 보이게 내지 않는다. fixture로 대체된 사전 계산본이면 그것도 적는다.
- 오프라인: 디스크만 읽는다. 파이프라인·LLM·임베딩 모듈을 import하지 않는다(외부 호출 0).

main.py 연결(PM): 위 두 줄. 실시간 분석이 실패했을 때 같은 계획서의 사전 계산본을 찾으려면
`lookup_by_text(plan_text)`(없으면 None) → `mark_result(hit)`로 표시가 붙은 결과 dict를 얻는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from neumann.config import get_settings
from neumann.models import PlanDocument, PremortemResult

MANIFEST_NAME = "manifest.json"
MANIFEST_KIND = "neumann.precomputed"
MANIFEST_VERSION = 1
PRECOMPUTED_SUBDIR = "precomputed"
LABEL = "사전 계산본"
RESULT_FILE_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_\-]{0,127}\.json$")
KST = timezone(timedelta(hours=9), "KST")  # 데모 청중 기준 표시 시각(zoneinfo 없이 고정 오프셋)

HEADER_FLAG = "X-Neumann-Precomputed"
HEADER_GENERATED_AT = "X-Neumann-Precomputed-Generated-At"
HEADER_SHA256 = "X-Neumann-Precomputed-Sha256"


# ── 공용 헬퍼(scripts/precompute_demo.py도 쓴다) ──────────────────────────


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode_json(data: Any) -> bytes:
    """저장 형식: UTF-8, 한글 그대로, 들여쓰기 2, 끝 줄바꿈. sha256은 이 바이트로 잰다."""
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str) and value:
        try:
            ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def precomputed_label(generated_at: Any) -> str:
    """"사전 계산본(2026-09-30 21:03 KST)". 시각을 읽을 수 없으면 "생성 시각 미상"."""
    ts = parse_time(generated_at)
    when = ts.astimezone(KST).strftime("%Y-%m-%d %H:%M KST") if ts else "생성 시각 미상"
    return f"{LABEL}({when})"


def precomputed_dir() -> Path:
    """사전 계산본 폴더: `<NEUMANN_DATA_DIR>/precomputed`. FastAPI 의존성(테스트에서 바꿔 끼운다)."""
    return Path(get_settings().data_dir) / PRECOMPUTED_SUBDIR


# ── 읽기 ──────────────────────────────────────────────────────────────────


class PrecomputedError(Exception):
    """사전 계산본을 낼 수 없다. code: no_manifest · bad_manifest · not_found · bad_name · missing_file · tampered · invalid"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PrecomputedHit:
    result: PremortemResult
    entry: dict[str, Any]
    manifest: dict[str, Any]

    @property
    def label(self) -> str:
        return precomputed_label(self.entry.get("generated_at"))


def read_manifest(directory: Path) -> dict[str, Any]:
    path = directory / MANIFEST_NAME
    if not path.is_file():
        raise PrecomputedError("no_manifest", "사전 계산본이 없다(scripts/precompute_demo.py를 먼저 실행한다)")
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrecomputedError("bad_manifest", f"매니페스트를 읽을 수 없다({type(exc).__name__})") from None
    if not isinstance(data, dict) or data.get("kind") != MANIFEST_KIND or not isinstance(data.get("entries"), list):
        raise PrecomputedError("bad_manifest", "매니페스트 형식이 아니다")
    return data


def _entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in manifest.get("entries", []) if isinstance(e, dict)]


def find_entry(manifest: dict[str, Any], key: str) -> dict[str, Any]:
    """plan_id가 먼저, 없으면 데모 이름(`demo`)으로 찾는다."""
    entries = _entries(manifest)
    for field in ("plan_id", "demo"):
        for entry in entries:
            if isinstance(entry.get(field), str) and entry[field] == key:
                return entry
    raise PrecomputedError("not_found", "해당 계획서의 사전 계산본이 없다")


def entry_path(directory: Path, entry: dict[str, Any]) -> Path:
    """매니페스트의 파일 이름을 검사해 경로를 만든다. 형식이 틀리거나 폴더 밖이면 bad_name."""
    name = entry.get("file")
    if not isinstance(name, str) or not RESULT_FILE_RE.match(name) or name == MANIFEST_NAME:
        raise PrecomputedError("bad_name", "매니페스트의 파일 이름이 허용 형식이 아니다")
    base = directory.resolve()
    path = (base / name).resolve()
    if path.parent != base:
        raise PrecomputedError("bad_name", "매니페스트의 파일이 사전 계산본 폴더 밖을 가리킨다")
    return path


def _read_verified(directory: Path, entry: dict[str, Any]) -> bytes:
    path = entry_path(directory, entry)
    try:
        data = path.read_bytes()
    except OSError:
        raise PrecomputedError("missing_file", "사전 계산본 파일이 없다") from None
    expected = entry.get("sha256")
    if not isinstance(expected, str) or sha256_bytes(data) != expected.lower():
        raise PrecomputedError("tampered", "사전 계산본이 변조됐다(sha256이 매니페스트와 다르다)")
    return data


def integrity(directory: Path, entry: dict[str, Any]) -> str:
    """목록용: ok · mismatch(변조) · missing · bad_name."""
    try:
        _read_verified(directory, entry)
    except PrecomputedError as exc:
        return {"tampered": "mismatch", "missing_file": "missing"}.get(exc.code, exc.code)
    return "ok"


def load_precomputed(key: str, directory: Path | None = None) -> PrecomputedHit:
    """사전 계산본 한 건을 무결성 검사 뒤 PremortemResult로 읽는다. 실패하면 PrecomputedError."""
    directory = precomputed_dir() if directory is None else directory
    manifest = read_manifest(directory)
    entry = find_entry(manifest, key)
    data = _read_verified(directory, entry)
    try:
        result = PremortemResult.model_validate(json.loads(data.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise PrecomputedError("invalid", f"사전 계산본이 결과 계약을 통과하지 못한다({type(exc).__name__})") from None
    if result.plan_id != entry.get("plan_id"):
        raise PrecomputedError("tampered", "사전 계산본의 plan_id가 매니페스트와 다르다")
    return PrecomputedHit(result=result, entry=entry, manifest=manifest)


def lookup_by_text(plan_text: str, directory: Path | None = None) -> PrecomputedHit | None:
    """계획서 본문(정규화·마스킹 뒤 sha256 = plan_id)으로 사전 계산본을 찾는다. 없거나 못 쓰면 None."""
    try:
        plan_id = PlanDocument.from_text(plan_text, session_id="precomputed-lookup").plan_id
        return load_precomputed(plan_id, directory)
    except (PrecomputedError, ValueError):
        return None


def _source_note(entry: dict[str, Any]) -> str:
    if entry.get("source") == "fixture":
        return " · 분석 파이프라인 미연결로 fixture 결과로 대체된 사전 계산본"
    return ""


def mark_result(hit: PrecomputedHit) -> dict[str, Any]:
    """결과 JSON에 사전 계산본 표시를 붙인다(PremortemResult 계약은 그대로 통과한다)."""
    data = hit.result.model_dump(mode="json")
    entry = hit.entry
    notice = f"{hit.label} — 실시간 분석이 아니라 미리 계산해 둔 결과다{_source_note(entry)}"
    data["notices"] = [notice, *data.get("notices", [])]
    data["manifest"] = {
        **data.get("manifest", {}),
        "precomputed": {
            "label": hit.label,
            "generated_at": entry.get("generated_at"),
            "source": entry.get("source"),
            "impl": entry.get("impl"),
            "demo": entry.get("demo"),
            "models": entry.get("models", []),
            "file": entry.get("file"),
            "sha256": entry.get("sha256"),
            "integrity": "ok",
            "manifest_generated_at": hit.manifest.get("generated_at"),
        },
    }
    return data


def list_items(directory: Path) -> dict[str, Any]:
    """목록 응답 본문. 매니페스트가 없거나 깨져도 예외 없이 available=false와 사유를 돌려준다."""
    try:
        manifest = read_manifest(directory)
    except PrecomputedError as exc:
        return {"label": LABEL, "available": False, "reason": exc.message, "code": exc.code, "items": []}
    items = []
    for entry in _entries(manifest):
        state = integrity(directory, entry)
        items.append(
            {
                "plan_id": entry.get("plan_id"),
                "demo": entry.get("demo"),
                "title": entry.get("title"),
                "label": precomputed_label(entry.get("generated_at")),
                "generated_at": entry.get("generated_at"),
                "source": entry.get("source"),
                "impl": entry.get("impl"),
                "status": entry.get("status"),
                "cards_total": entry.get("cards_total"),
                "cards_by_generator": entry.get("cards_by_generator", {}),
                "models": entry.get("models", []),
                "warnings": entry.get("warnings", []),
                "elapsed_s": entry.get("elapsed_s"),
                "sha256": entry.get("sha256"),
                "integrity": state,
                "available": state == "ok",
                "url": f"/premortem/precomputed/{entry.get('plan_id')}",
            }
        )
    return {
        "label": LABEL,
        "available": any(it["available"] for it in items),
        "reason": None if items else "매니페스트에 항목이 없다",
        "generated_at": manifest.get("generated_at"),
        "source": manifest.get("source"),
        "pipeline": manifest.get("pipeline"),
        "llm": manifest.get("llm"),
        "items": items,
    }


# ── 라우터 ────────────────────────────────────────────────────────────────

router = APIRouter(tags=["precomputed"])


@router.get("/premortem/precomputed")
def list_precomputed(directory: Path = Depends(precomputed_dir)) -> JSONResponse:
    return JSONResponse(list_items(directory), headers={HEADER_FLAG: "1", "Cache-Control": "no-store"})


@router.get("/premortem/precomputed/{plan_id}")
def get_precomputed(plan_id: str, directory: Path = Depends(precomputed_dir)) -> JSONResponse:
    try:
        hit = load_precomputed(plan_id, directory)
    except PrecomputedError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": exc.message}) from None
    headers = {
        HEADER_FLAG: "1",
        HEADER_GENERATED_AT: str(hit.entry.get("generated_at", "")),
        HEADER_SHA256: str(hit.entry.get("sha256", "")),
        "Cache-Control": "no-store",
    }
    return JSONResponse(mark_result(hit), headers=headers)


__all__ = [
    "HEADER_FLAG",
    "HEADER_GENERATED_AT",
    "HEADER_SHA256",
    "LABEL",
    "MANIFEST_KIND",
    "MANIFEST_NAME",
    "MANIFEST_VERSION",
    "PRECOMPUTED_SUBDIR",
    "RESULT_FILE_RE",
    "PrecomputedError",
    "PrecomputedHit",
    "encode_json",
    "entry_path",
    "find_entry",
    "integrity",
    "list_items",
    "load_precomputed",
    "lookup_by_text",
    "mark_result",
    "parse_time",
    "precomputed_dir",
    "precomputed_label",
    "read_manifest",
    "router",
    "sha256_bytes",
]
