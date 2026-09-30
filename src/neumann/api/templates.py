"""AI for Science 템플릿 카탈로그 API (E4-L1b, 예시·템플릿 AI for Science 재정렬 E4-L1e).

붙이는 법(PM, ``main.py``)::

    from neumann.api.templates import router as templates_router
    app.include_router(templates_router)

라우트
- ``GET /templates``       카탈로그: 범위 안내(``scope``), 템플릿 목록, 예시 계획서 목록
- ``GET /templates/{id}``  템플릿이면 계획서 골격 본문, 예시면 예시 계획서 원문
  (``api/templates/examples/`` 또는 데모 계획서 ``tests/fixtures/plans/``)

데이터는 ``api/templates/``(이 모듈과 같은 이름의 폴더, ``__init__.py`` 없음)에 있다.
``catalog.json``이 목록이고 ``catalog.schema.json``(JSON Schema Draft-07)이 그 모양이다.
카탈로그는 처음 읽을 때 스키마·참조(파일 존재, 예시의 template_id, id 중복, 골격의 필수 칸)를 검사한다.
검사에 실패하면 목록을 숨기지 않고 500과 사유를 돌려준다.

id는 카탈로그 사전에서만 찾는다. 요청 문자열로 파일 경로를 만들지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Path as PathParam
from fastapi.responses import JSONResponse

DATA_DIR = Path(__file__).resolve().parent / "templates"
CATALOG_PATH = DATA_DIR / "catalog.json"
SCHEMA_PATH = DATA_DIR / "catalog.schema.json"
REPO_ROOT = Path(__file__).resolve().parents[3]
# 예시 계획서가 있어도 되는 폴더(경로는 카탈로그의 저장소 기준 상대 경로, 스키마 패턴과 같은 두 곳)
EXAMPLE_DIRS = (DATA_DIR / "examples", REPO_ROOT / "tests" / "fixtures" / "plans")
ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
# 2단 제목 줄 `## …`: 줄 시작에서만 맞추고 `[^\n]*`가 줄 끝까지 한 번에 가므로 입력 길이에 선형이다.
# 번호(`1.`)와 앞뒤 공백은 정규식이 아니라 sections()에서 문자열로 벗긴다(SEC-6).
# 옛 `^##\s+(?:\d+\.\s*)?(.+?)\s*$`(re.M)는 `(.+?)\s*$`가 겹쳐 "## a" + 공백 N개 + "." 에서 제곱 시간이었고,
# `\s+`가 줄바꿈을 넘어 `##`만 있는 줄 다음 줄을 칸 이름으로 삼았다.
HEADING = re.compile(r"^##[^\S\n]([^\n]*)$", re.M)
_SECTION_NUMBER = re.compile(r"\d+\.")

router = APIRouter(tags=["templates"])


class CatalogError(RuntimeError):
    """카탈로그 파일이 스키마나 참조 규칙을 어겼다."""


def sections(text: str) -> list[str]:
    """``## 1. 연구 목표`` 같은 2단 제목에서 칸 이름만 뽑는다(번호 제거). 이름이 빈 제목 줄은 건너뛴다."""
    out: list[str] = []
    for m in HEADING.finditer(text):
        name = m.group(1).strip()
        num = _SECTION_NUMBER.match(name)
        if num and name[num.end() :].strip():  # 번호 뒤에 이름이 있을 때만 번호를 뗀다(옛 규칙: `## 1.`은 `1.`)
            name = name[num.end() :].lstrip()
        if name:
            out.append(name)
    return out


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def catalog_errors(catalog: dict[str, Any]) -> list[str]:
    """스키마 위반 + 참조 오류 목록(빈 목록이면 통과)."""
    from jsonschema import Draft7Validator

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errs = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
            for e in Draft7Validator(schema).iter_errors(catalog)]
    if errs:
        return errs
    required = catalog["required_sections"]
    domains = set(catalog["scope"]["domains"])
    ids: list[str] = [t["id"] for t in catalog["templates"]] + [e["id"] for e in catalog["examples"]]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errs.append(f"id 중복: {dup}")
    tpl_ids = {t["id"] for t in catalog["templates"]}
    for t in catalog["templates"]:
        path = DATA_DIR / t["file"]
        if not path.is_file():
            errs.append(f"{t['id']}: 골격 파일 없음 {t['file']}")
            continue
        missing = [s for s in required if s not in sections(_read(path))]
        if missing:
            errs.append(f"{t['id']}: 골격에 필수 칸 없음 {missing}")
        if t["domain"] not in domains:
            errs.append(f"{t['id']}: 범위 밖 분야 {t['domain']}")
    for e in catalog["examples"]:
        if e["template_id"] not in tpl_ids:
            errs.append(f"{e['id']}: 없는 템플릿 {e['template_id']}")
        path = (REPO_ROOT / e["path"]).resolve()
        if path.parent not in {d.resolve() for d in EXAMPLE_DIRS} or not path.is_file():
            errs.append(f"{e['id']}: 예시 파일 없음 {e['path']}")
        if e["domain"] not in domains:
            errs.append(f"{e['id']}: 범위 밖 분야 {e['domain']}")
    return errs


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """검사를 통과한 카탈로그. 실패하면 CatalogError."""
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"catalog.json 읽기 실패: {type(exc).__name__}") from exc
    errs = catalog_errors(catalog)
    if errs:
        raise CatalogError("; ".join(errs))
    return catalog


def _template_item(t: dict[str, Any]) -> dict[str, Any]:
    return {"id": t["id"], "kind": "template", "name": t["name"], "domain": t["domain"], "summary": t["summary"],
            "sections": sections(_read(DATA_DIR / t["file"]))}


def _example_item(e: dict[str, Any]) -> dict[str, Any]:
    text = _read(REPO_ROOT / e["path"])
    return {"id": e["id"], "kind": "example", "name": e["name"], "domain": e["domain"],
            "template_id": e["template_id"], "filename": Path(e["path"]).name, "title": _title(text)}


def list_templates() -> dict[str, Any]:
    c = load_catalog()
    return {
        "version": c["version"],
        "scope": c["scope"],
        "required_sections": c["required_sections"],
        "templates": [_template_item(t) for t in c["templates"]],
        "examples": [_example_item(e) for e in c["examples"]],
    }


def get_template(item_id: str) -> dict[str, Any] | None:
    """템플릿 골격 또는 예시 원문. 없으면 None."""
    c = load_catalog()
    for t in c["templates"]:
        if t["id"] == item_id:
            text = _read(DATA_DIR / t["file"])
            return {**_template_item(t), "text": text, "filename": None, "source": f"templates/{t['file']}",
                    "chars": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    for e in c["examples"]:
        if e["id"] == item_id:
            text = _read(REPO_ROOT / e["path"])
            return {**_example_item(e), "text": text, "source": e["path"], "sections": sections(text),
                    "chars": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    return None


def _catalog_failure(exc: CatalogError) -> JSONResponse:
    return JSONResponse({"status": "error", "reason": f"템플릿 카탈로그 오류: {exc}"}, status_code=500)


@router.get("/templates")
def templates_index() -> JSONResponse:
    try:
        return JSONResponse(list_templates())
    except CatalogError as exc:
        return _catalog_failure(exc)


@router.get("/templates/{item_id}")
def templates_item(item_id: str = PathParam(..., max_length=64, pattern=ID_PATTERN)) -> JSONResponse:
    try:
        item = get_template(item_id)
    except CatalogError as exc:
        return _catalog_failure(exc)
    if item is None:
        return JSONResponse({"detail": f"템플릿 없음: {item_id}"}, status_code=404)
    return JSONResponse(item)
