"""Curated demonstration samples. Reads local files only; never runs analysis."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from jsonschema import Draft7Validator

from neumann.api.precomputed import PrecomputedError, load_precomputed, mark_result
from neumann.api.sample_curation import OFFLINE_LABEL, generation_of
from neumann.api.view import build_ui_view
from neumann.models import PlanDocument

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(__file__).resolve().parent / "templates"
REGISTRY_PATH = DATA_DIR / "samples.json"
SCHEMA_PATH = DATA_DIR / "samples.schema.json"
DOCUMENT_DIR = REPO_ROOT / "src/neumann/webui/samples"
TEXT_DIRS = (DATA_DIR / "examples", DATA_DIR / "samples", REPO_ROOT / "tests/fixtures/plans")
PRECOMPUTED_LABEL = "사전 계산본 · 라이브 분석 아님"
router = APIRouter(tags=["samples"])


class RegistryError(RuntimeError):
    """Invalid local registry. Details never include file contents."""


def text_path(item: dict[str, Any]) -> Path | None:
    value = item.get("path")
    if not value:
        return None
    path = (REPO_ROOT / value).resolve()
    if path.parent not in {p.resolve() for p in TEXT_DIRS} or not path.is_file():
        raise RegistryError("본문 파일 경로가 허용 범위를 벗어나거나 파일이 없습니다")
    return path


def document_path(item: dict[str, Any], fmt: str) -> Path | None:
    name = item.get("documents", {}).get(fmt)
    if not name:
        return None
    path = (DOCUMENT_DIR / name).resolve()
    if path.parent != DOCUMENT_DIR.resolve() or path.suffix != "." + fmt:
        raise RegistryError("문서 파일 경로가 허용 범위를 벗어납니다")
    return path if path.is_file() else None


def registry_errors(registry: dict[str, Any]) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = ["샘플 스키마 위반: " + "/".join(map(str, e.absolute_path))
              for e in Draft7Validator(schema).iter_errors(registry)]
    if errors:
        return errors
    fields = {f["id"]: f for f in registry["fields"]}
    for key, values in (("sample", [s["id"] for s in registry["samples"]]),
                        ("field", [f["id"] for f in registry["fields"]])):
        if len(values) != len(set(values)):
            errors.append(key + " id 중복")
    if any(f["domain"] not in registry["domains"] for f in fields.values()):
        errors.append("분야의 domain 참조 오류")
    for item in registry["samples"]:
        if item["field"] not in fields or item["domain"] not in registry["domains"]:
            errors.append(item["id"] + ": 분야 참조 오류")
        if item["kind"] == "case" and (item.get("path") or item.get("documents")):
            errors.append(item["id"] + ": 사례에는 본문·문서 경로를 둘 수 없습니다")
        try:
            path = text_path(item)
            if item["public_ok"] and item["kind"] != "case" and path is None:
                errors.append(item["id"] + ": 공개 본문 파일 없음")
            for fmt in item.get("documents", {}):
                document_path(item, fmt)  # Missing pending artifacts are unavailable, not a broken registry.
            if path and item.get("plan_id"):
                plan_id = PlanDocument.from_text(path.read_text(encoding="utf-8"), session_id="samples").plan_id
                if plan_id != item["plan_id"]:
                    errors.append(item["id"] + ": plan_id 불일치")
        except (RegistryError, ValueError, OSError):
            errors.append(item["id"] + ": 파일 참조 오류")
    return errors


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        errors = registry_errors(registry)
    except (OSError, ValueError):
        raise RegistryError("샘플 레지스트리를 읽을 수 없습니다") from None
    if errors:
        raise RegistryError("; ".join(errors))
    return registry


def sample_plan_id(item: dict[str, Any]) -> str | None:
    path = text_path(item) if item["public_ok"] and item["kind"] != "case" else None
    if path:
        return PlanDocument.from_text(path.read_text(encoding="utf-8"), session_id="samples").plan_id
    return item.get("plan_id")


def precomputed_hit(item: dict[str, Any]):
    # No body, quotations or analysis are exposed for private/candidate/retired/case items.
    if not item["public_ok"] or item["status"] != "featured" or item["kind"] != "plan":
        return None
    plan_id = sample_plan_id(item)
    if not plan_id:
        return None
    try:
        hit = load_precomputed(plan_id)
    except PrecomputedError:
        return None
    if hit.entry.get("source") == "fixture" or hit.manifest.get("source") == "fixture":
        return None
    generation = generation_of(hit.result.model_dump(mode="json", by_alias=True), source=hit.entry.get("source"))
    if generation in ("mock", "rule", "unknown"):
        return None
    return hit


def public_item(item: dict[str, Any]) -> dict[str, Any]:
    # An allowlist prevents future internal curation fields leaking into the gallery.
    keys = ("id", "kind", "title", "summary", "domain", "field", "language", "license", "public_ok", "expect_gate")
    out = {k: item[k] for k in keys}
    origin = item.get("origin", {})
    out["origin"] = {k: origin.get(k) for k in ("url", "arxiv")}
    public_body = item["public_ok"] and item["kind"] != "case"
    path = text_path(item) if public_body else None
    text = path.read_text(encoding="utf-8") if path else ""
    out.update(chars=len(text) if path else None, lines=len(text.splitlines()) if path else None,
               body_available=bool(path), documents={})
    if public_body:
        out["documents"] = {fmt: {"url": f"/templates/samples/{item['id']}/document/{fmt}", "filename": p.name}
                            for fmt in item.get("documents", {}) if (p := document_path(item, fmt))}
    hit = precomputed_hit(item)
    out["precomputed"] = {"available": hit is not None, "label": PRECOMPUTED_LABEL if hit else None}
    if hit:
        generation = generation_of(hit.result.model_dump(mode="json", by_alias=True), source=hit.entry.get("source"))
        out["precomputed"].update(url=f"/templates/samples/{item['id']}/view", generated_at=hit.entry.get("generated_at"),
                                  generation=generation)
        if generation == OFFLINE_LABEL:
            out["precomputed"]["label"] += " · " + OFFLINE_LABEL
    return out


def find_sample(sample_id: str) -> dict[str, Any]:
    for item in load_registry()["samples"]:
        if item["id"] == sample_id and item["status"] == "featured" and item["public_ok"]:
            return item
    raise HTTPException(404, "샘플 없음")


def require_body(item: dict[str, Any]) -> None:
    if not item["public_ok"] or item["kind"] == "case":
        raise HTTPException(404, "공개 본문 없음")


def registry_failure(exc: RegistryError) -> JSONResponse:
    return JSONResponse({"status": "error", "reason": str(exc)}, status_code=500,
                        headers={"Cache-Control": "no-store"})


@router.get("/templates/samples")
def samples_index():
    try:
        registry = load_registry()
        return JSONResponse({**{k: registry[k] for k in ("version", "label", "notice", "domains")},
                             "fields": [{k: f[k] for k in ("id", "name", "domain")} for f in registry["fields"]],
                             "samples": [public_item(s) for s in registry["samples"]
                                         if s["status"] == "featured" and s["public_ok"]]},
                            headers={"Cache-Control": "no-store"})
    except RegistryError as exc:
        return registry_failure(exc)


@router.get("/templates/samples/{sample_id}")
def samples_body(sample_id: str):
    try:
        item = find_sample(sample_id)
        require_body(item)
        path = text_path(item)
        if path is None:
            raise HTTPException(404, "공개 본문 없음")
        return JSONResponse({**public_item(item), "text": path.read_text(encoding="utf-8"), "filename": path.name},
                            headers={"Cache-Control": "no-store"})
    except RegistryError as exc:
        return registry_failure(exc)


@router.get("/templates/samples/{sample_id}/document/{fmt}")
def samples_document(sample_id: str, fmt: str):
    try:
        item = find_sample(sample_id)
        require_body(item)
        if fmt not in ("pdf", "docx", "hwpx"):
            raise HTTPException(404, "문서 형식 없음")
        path = document_path(item, fmt)
        if path is None:
            raise HTTPException(404, "문서 파일 없음")
        mime = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "hwpx": "application/vnd.hancom.hwpx"}[fmt]
        return FileResponse(path, media_type=mime, filename=path.name, headers={"Cache-Control": "no-store"})
    except RegistryError as exc:
        return registry_failure(exc)


@router.get("/templates/samples/{sample_id}/view")
def samples_view(sample_id: str):
    try:
        item = find_sample(sample_id)
        require_body(item)
        hit = precomputed_hit(item)
        if hit is None:
            raise HTTPException(404, "사용 가능한 사전 계산본 없음")
        result = mark_result(hit)
        generation = generation_of(result, source=hit.entry.get("source"))
        notices = [PRECOMPUTED_LABEL]
        if generation == OFFLINE_LABEL:
            notices.append(OFFLINE_LABEL)
        view = build_ui_view(result, records=None, extra_notices=notices)
        labels = [PRECOMPUTED_LABEL]
        if generation == OFFLINE_LABEL:
            labels.append(OFFLINE_LABEL)
        if view["_status"].get("label"):
            labels.append(view["_status"]["label"])  # Keep degradation and UI contract error labels visible.
        view["_status"]["label"] = " · ".join(labels)
        return JSONResponse(view, headers={"X-Neumann-Precomputed": "1", "Cache-Control": "no-store"})
    except RegistryError as exc:
        return registry_failure(exc)
