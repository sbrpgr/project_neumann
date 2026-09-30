"""citation_lookup 도구와 근거 조회(FIN-TOOLS): MCP 서버(`neumann.api.mcp_server`)의 읽기 전용 백엔드를 그대로 쓴다.

- 인용 확인(`run`, 등록 도구 citation_lookup): DOI → 철회·정정·우려표명 기록(Retraction Watch), 제목 → 심사 코퍼스 검색.
  철회·우려표명이면 fail, 코퍼스에서 제목(과 DOI)이 맞고 철회 기록이 없으면 pass, 그 밖(코퍼스 밖·자료 없음)은 unchecked.
  "기록 없음"은 문제가 없다는 보증이 아니므로 그것만으로 pass를 주지 않는다.
- 근거 조회(`search_prior_work`·`review_records`): 엔진이 선행연구 주장·심사평을 붙일 때 쓰는 보조 함수(판정 없음).

오프라인·읽기 전용이다(색인·데이터 파일만 읽는다). 도구는 환경변수·.env를 읽지 않는다: 엔진이 `configure(data_dir)` 또는
`set_backend(backend)`로 백엔드를 정하고, 정하지 않았으면 unchecked(backend_not_configured)다. 검색어는 300자 이하만 보낸다
(계획서 본문 금지 — MCP 서버 규칙). 백엔드 호출은 스레드에서 시간 상한(기본 10초)으로 기다린다.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Callable

VERSION = "fin-tools.citation_lookup@1"
MAX_TITLE = 300
DEFAULT_TIMEOUT_S = 10.0
BAD_KINDS = {"retraction", "partial_retraction", "expression_of_concern", "removal", "withdrawal"}

_LOCK = threading.Lock()
_BACKEND: Any = None
_TIMEOUT_S = DEFAULT_TIMEOUT_S


def set_backend(backend: Any, *, timeout_s: float | None = None) -> None:
    """조회 백엔드(`mcp_server.Backend`)를 정한다. 테스트·엔진이 이미 만든 백엔드를 넘긴다. None이면 기본으로 되돌린다."""
    global _BACKEND, _TIMEOUT_S
    with _LOCK:
        _BACKEND = backend
        if timeout_s is not None:
            _TIMEOUT_S = float(timeout_s)


class BackendNotConfigured(RuntimeError):
    """조회 백엔드를 정하지 않았다. 도구는 환경변수·설정 파일을 스스로 읽지 않는다(엔진이 경로를 넘긴다)."""


def configure(data_dir: str | Path, index_dir: str | Path | None = None, *, timeout_s: float | None = None) -> Any:
    """명시한 데이터 폴더로 기본 백엔드(`mcp_server.build_default_backend`)를 만든다. 색인 폴더 기본은 ``{data}/index``.

    경로를 모두 인자로 넘기므로 NEUMANN_DATA_DIR·NEUMANN_INDEX_DIR·.env를 읽지 않는다.
    """
    from neumann.api.mcp_server import build_default_backend

    data = Path(data_dir)
    backend = build_default_backend(data, Path(index_dir) if index_dir is not None else data / "index")
    set_backend(backend, timeout_s=timeout_s)
    return backend


def get_backend() -> Any:
    with _LOCK:
        if _BACKEND is None:
            raise BackendNotConfigured("backend_not_configured")
        return _BACKEND


def _bounded(fn: Callable[[], Any], timeout_s: float) -> Any:
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — 호출자에게 종류만 넘긴다
            box["error"] = exc

    worker = threading.Thread(target=target, name="fin-tools-evidence", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise TimeoutError("evidence_lookup_timeout")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _norm_title(text: str) -> str:
    return " ".join(re.findall(r"[0-9a-z가-힣]+", text.casefold()))


def _title_match(a: str, b: str) -> str | None:
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return None
    if na == nb:
        return "exact"
    ta, tb = set(na.split()), set(nb.split())
    return "near" if len(ta & tb) / len(ta | tb) >= 0.9 else None


def _lookup(args: dict[str, Any], be: Any) -> dict[str, Any]:
    from neumann.api.mcp_server import DataUnavailable, run_search

    doi_raw, title, year = args.get("doi"), args.get("title"), args.get("year")
    out: dict[str, Any] = {"found": None, "retracted": None, "post_status": [], "notes": []}
    doi = None
    if doi_raw is not None:
        doi = be.normalize_doi(doi_raw)
        if doi is None:
            return {"verdict": "unchecked", "reason": "invalid_doi"}
        out["doi"] = doi
        try:
            records = be.get_post_status(doi)
        except (FileNotFoundError, DataUnavailable):
            out["notes"].append("retraction_data_unavailable")
            records = None
        if records is not None:
            kinds = sorted({r.kind.value for r in records})
            out["post_status"] = [{"kind": r.kind.value, "notice_url": r.url, "source_url": r.provenance.source_url,
                                   "snapshot": r.provenance.api_version} for r in records[:10]]
            out["retracted"] = bool(set(kinds) & BAD_KINDS)
            if not records:
                out["notes"].append("no_record_is_not_a_guarantee")
    match = None
    if title is not None:
        query = title.strip()[:MAX_TITLE]
        try:
            result = run_search(be, query, 5)
        except Exception:  # noqa: BLE001 — 색인 없음·검색어 거부는 코퍼스 확인 불가
            out["notes"].append("corpus_unavailable")
            result = None
        if result is not None:
            out["search_backend"] = result.backend
            out["search_degraded"] = result.degraded
            for hit in result.hits:
                how = _title_match(title, hit.title)
                if how and (year is None or hit.year in (None, year)):
                    match = {"work_id": hit.work_id, "title": hit.title, "url": hit.url, "doi": hit.doi,
                             "year": hit.year, "match": how}
                    break
            out["found"] = match is not None
            if match:
                out["match"] = match
                if doi and match.get("doi") and be.normalize_doi(match["doi"]) != doi:
                    out["notes"].append("doi_title_mismatch")
    if out["retracted"]:
        out.update(verdict="fail", reason="retracted_or_concern")
    elif "doi_title_mismatch" in out["notes"]:
        out.update(verdict="fail", reason="doi_title_mismatch")
    elif match and out["retracted"] is False:
        out["verdict"] = "pass"
    elif match and doi is None:
        out.update(verdict="pass", reason="found_in_corpus_no_doi")
    else:
        out.update(verdict="unchecked", reason="not_verifiable_in_corpus")
    out["engine"] = "mcp_backend"
    return out


def run(args: dict[str, Any]) -> dict[str, Any]:
    if type(args) is not dict or not set(args) <= {"doi", "title", "year"}:
        return {"verdict": "unchecked", "reason": "invalid_args"}
    doi, title, year = args.get("doi"), args.get("title"), args.get("year")
    if doi is None and title is None:
        return {"verdict": "unchecked", "reason": "invalid_args"}
    if (doi is not None and (type(doi) is not str or not 0 < len(doi) <= 300)) or (
        title is not None and (type(title) is not str or not 0 < len(title.strip()) <= MAX_TITLE)
    ) or (year is not None and (type(year) is not int or not 1800 <= year <= 2100)):
        return {"verdict": "unchecked", "reason": "invalid_args"}
    try:
        be = get_backend()
    except BackendNotConfigured:
        return {"verdict": "unchecked", "reason": "backend_not_configured"}
    return _bounded(lambda: _lookup(args, be), _TIMEOUT_S)


def search_prior_work(query: str, k: int = 5) -> dict[str, Any]:
    """선행연구 검색(판정 없음). 결과: hits(work_id·제목·URL·점수)와 검색 백엔드·강등 여부. 실패는 {"error": 코드}."""
    if type(query) is not str or not 0 < len(query.strip()) <= MAX_TITLE or type(k) is not int or not 1 <= k <= 10:
        return {"error": "invalid_args"}
    try:
        from neumann.api.mcp_server import run_search

        be = get_backend()
        result = _bounded(lambda: run_search(be, query.strip(), k), _TIMEOUT_S)
    except BackendNotConfigured:
        return {"error": "backend_not_configured"}
    except TimeoutError:
        return {"error": "timeout"}
    except Exception:  # noqa: BLE001
        return {"error": "lookup_failed"}
    return result.model_dump(mode="json")


def review_records(work_id: str) -> dict[str, Any]:
    """논문 한 편의 심사평·저자 답변·결정(신원 없음, 원문 앞부분 글자 그대로). 실패는 {"error": 코드}."""
    if type(work_id) is not str or not 0 < len(work_id) <= 200:
        return {"error": "invalid_args"}
    try:
        from neumann.api.mcp_server import run_review_records

        be = get_backend()
        if _bounded(lambda: be.get_work(work_id.strip()), _TIMEOUT_S) is None:
            return {"error": "not_found"}
        result = _bounded(lambda: run_review_records(be, work_id), _TIMEOUT_S)
    except BackendNotConfigured:
        return {"error": "backend_not_configured"}
    except TimeoutError:
        return {"error": "timeout"}
    except Exception:  # noqa: BLE001
        return {"error": "lookup_failed"}
    return result.model_dump(mode="json")


ARGS_SCHEMA = {
    "type": "object",
    "properties": {
        "doi": {"type": "string", "maxLength": 300},
        "title": {"type": "string", "maxLength": MAX_TITLE},
        "year": {"type": "integer", "minimum": 1800, "maximum": 2100},
    },
    "additionalProperties": False,
}
