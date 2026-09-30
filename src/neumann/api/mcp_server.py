"""Neumann MCP 서버 (E4-L2b): 읽기 전용 도구 3종, stdio 전송.

외부 에이전트가 Neumann의 근거 데이터를 조회하는 창구다. 제품 경로는 아니다(계획서 §1.5 MCP 행, §3 L2).

도구
- `search_similar_works(query, k=10)`: 유사 연구 검색 → 논문 id·제목·원문 URL·점수(0~1)
- `get_review_records(work_id)`: 심사평·저자 답변·결정 요약과 원문 URL(신원 정보 없음)
- `get_post_status(doi)`: 철회·정정·우려표명 등 사후 상태와 공지 링크(Retraction Watch)

원칙
- 읽기 전용: 쓰기·삭제·외부 네트워크 호출이 없다. 도구 annotations에 readOnlyHint=True, openWorldHint=False.
- 계획서 본문은 받지 않는다: 검색어는 `MAX_QUERY_CHARS`(300자) 이하만. 넘으면 거부한다.
- 결과마다 출처 URL: 논문 랜딩·심사평 딥링크·공지 DOI 링크·데이터셋 URL(provenance).
- 신원 정보 없음: 리뷰어 가명(`reviewer_pseudonym`)도 내보내지 않는다. 출력 모델은 `NeumannModel`이라
  신원 토큰이 들어간 필드 이름은 클래스 정의 시점에 막힌다.
- 강등을 숨기지 않는다: 검색 백엔드(hybrid · lexical_only · 어댑터)와 강등 사유를 결과에 싣는다.
- 본문 발췌(`text_head`)는 원문 앞부분을 글자 그대로 자른 것이다(`원문[0:len(text_head)]`). 요약문을 새로 쓰지 않는다.
- stdout은 MCP 채널이다. 로그는 stderr로만 쓴다.

의존과 얇은 어댑터
- `neumann.index.search`·`neumann.index.store`(E2-L0)를 불러올 수 있으면 그대로 쓴다. 없으면 색인 폴더의
  `works.jsonl`·`reviews.jsonl`을 직접 읽고 토큰 겹침으로 찾는다(backend=`adapter_token_overlap`, degraded=True).
- `neumann.sources.retraction.get_post_status`(E1-L2)를 불러올 수 있으면 그대로 쓴다. 없으면
  `processed/retraction.jsonl`을 직접 읽는다(같은 DOI 정규화 규칙).
- 저자 답변·결정은 `processed/author_responses.jsonl`·`processed/decisions.jsonl`(E1-L0 산출물)을 논문별로 묶어 읽는다.

실행
    python -m neumann.api.mcp_server [--data-dir PATH] [--index-dir PATH] [--no-warmup] [--log-level LEVEL]

환경변수(기존 키만 쓴다): `NEUMANN_DATA_DIR`(공유 데이터 폴더), `NEUMANN_INDEX_DIR`(기본 `{data}/index`, E2),
`NEUMANN_EMBED_MODEL`(bge-m3 로컬 경로, E2). 비밀값은 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import unquote

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from neumann.models import AuthorResponse, Decision, NeumannModel, PostStatus, ReviewEvent, Work

log = logging.getLogger("neumann.mcp")

SERVER_NAME = "neumann"
SERVER_VERSION = "0.2.0"
MAX_QUERY_CHARS = 300
MAX_K = 50
DEFAULT_K = 10
HEAD_CHARS = 600

TOOL_NAMES = ("search_similar_works", "get_review_records", "get_post_status")

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

INSTRUCTIONS = (
    "Neumann 근거 데이터 조회(읽기 전용). 1) search_similar_works로 짧은 검색어(300자 이하, 계획서 본문 금지)를 "
    "넣어 유사 연구를 찾고 2) 그 work_id로 get_review_records를 불러 실제 심사평·저자 답변·결정을 보고 "
    "3) DOI가 있으면 get_post_status로 철회·정정 기록을 확인한다. 모든 결과에 출처 URL이 붙는다. "
    "Read-only evidence lookup: similar-work search, review records, post-publication status."
)


# ── 출력 모델(신원 필드 금지: NeumannModel) ──────────────────────────────


class WorkRef(NeumannModel):
    """논문 참조. url은 사람이 여는 랜딩 페이지, source_url은 레코드를 받은 원문(provenance)."""

    work_id: str
    title: str
    url: str = Field(description="논문 랜딩 페이지(원문 URL)")
    source_url: str = Field(description="레코드를 받은 원문 URL(provenance.source_url)")
    doi: str | None = None
    venue: str | None = None
    year: int | None = None


class SimilarWork(WorkRef):
    fields: list[str] = Field(default_factory=list, description="분야·키워드")
    score: float = Field(ge=0.0, le=1.0, description="결합 점수 0~1(보정 전)")
    dense: float = Field(ge=0.0, le=1.0, description="임베딩(bge-m3) 코사인, 강등이면 0")
    lexical: float = Field(ge=0.0, le=1.0, description="어휘(BM25 정규화 또는 토큰 겹침) 점수")
    matched_query: str


class SearchResult(NeumannModel):
    query: str
    k: int
    n_hits: int
    hits: list[SimilarWork]
    backend: str = Field(
        description="hybrid(bge-m3+BM25) · lexical_only(임베딩 강등) · adapter_token_overlap(E2 색인 모듈 없음, 비상)"
    )
    degraded: bool = Field(description="임베딩 없이 어휘로만 찾았으면 True")
    reason: str | None = Field(default=None, description="강등 사유")
    score_note: str = "점수는 0~1 상대값이다. 보정 전이므로 확률로 읽지 않는다."


class _TextHead(NeumannModel):
    url: str = Field(description="원문 딥링크(없으면 provenance.source_url)")
    source_url: str = Field(description="provenance.source_url")
    text_chars: int = Field(ge=0, description="원문 전체 글자 수")
    text_head: str = Field(description=f"원문 앞부분 글자 그대로(원문[0:len(text_head)]), 최대 {HEAD_CHARS}자")
    truncated: bool
    text_sha256: str | None = Field(default=None, description="원문 전체의 sha256")


class ReviewRecord(_TextHead):
    review_id: str
    kind: str
    round: int | None = None
    rating: str | None = Field(default=None, description="원문 그대로")
    confidence: str | None = Field(default=None, description="원문 그대로")
    created: str | None = None


class ResponseRecord(_TextHead):
    response_id: str
    review_id: str | None = Field(default=None, description="답변이 달린 심사평(전체 답변이면 None)")
    round: int | None = None


class DecisionRecord(_TextHead):
    decision_id: str
    outcome: str
    outcome_raw: str = Field(description="소스 원문 문자열 그대로")


class ReviewRecordsResult(NeumannModel):
    work: WorkRef
    decisions: list[DecisionRecord]
    reviews: list[ReviewRecord]
    responses: list[ResponseRecord] = Field(description="저자 답변")
    n_reviews: int
    n_responses: int
    n_decisions: int
    head_chars: int = HEAD_CHARS
    notes: list[str] = Field(default_factory=list, description="빠진 데이터·어댑터 사용 등 정직 표기")


class PostStatusRecord(NeumannModel):
    post_status_id: str
    kind: str = Field(description="retraction · correction · expression_of_concern · reinstatement 등")
    target_doi: str | None = None
    notice_doi: str | None = None
    notice_url: str | None = Field(default=None, description="공지 링크 https://doi.org/<공지 DOI>")
    reason_codes: list[str] = Field(default_factory=list, description="Retraction Watch 사유 원문 그대로")
    source_url: str = Field(description="데이터셋 원문 URL(provenance)")
    snapshot: str | None = Field(default=None, description="데이터 스냅샷(provenance.api_version)")
    accessed_at: str


class PostStatusResult(NeumannModel):
    query: str
    doi: str = Field(description="정규화한 원논문 DOI")
    status: Literal["found", "no_record"]
    n_records: int
    records: list[PostStatusRecord]
    citation: str | None = None
    dataset_url: str | None = None
    license: str | None = None
    snapshot: str | None = None
    backend: str
    note: str = (
        "원논문 DOI로만 찾는다(공지 DOI 아님). no_record는 이 데이터셋에 기록이 없다는 뜻이지 "
        "문제가 없다는 보증이 아니다."
    )


# ── 백엔드: 조회 함수 묶음(테스트는 fixture로 만든 것을 주입) ─────────────


class DataUnavailable(RuntimeError):
    """조회에 필요한 데이터 파일이 없다."""


@dataclass
class Backend:
    """도구가 쓰는 조회 함수. None을 돌려주는 조회는 "그 데이터 자체가 없다"는 뜻이다(빈 목록과 구별)."""

    search: Callable[[str, int], tuple[list[Any], dict[str, Any]]]  # 결과: work_id·score·dense·lexical·matched_query를 가진 객체
    get_work: Callable[[str], Work | None]
    get_reviews: Callable[[str], list[ReviewEvent]]
    get_responses: Callable[[str], list[AuthorResponse] | None]
    get_decisions: Callable[[str], list[Decision] | None]
    get_post_status: Callable[[str], list[PostStatus]]
    normalize_doi: Callable[[str], str | None]
    retraction_meta: Callable[[], dict[str, Any]]
    info: dict[str, str]
    warmup: Callable[[], dict[str, Any]] | None = None


# ── 공통 도우미 ───────────────────────────────────────────────────────────

_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_PCT_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_TOKEN_RE = re.compile(r"[0-9a-z가-힣]+")


def normalize_doi(value: str | None) -> str | None:
    """E1-L2와 같은 규칙: strip → 접두(https://doi.org/, http://dx.doi.org/, doi:) 제거 → %XX 해제 → 소문자 → 형식 검사."""
    if value is None:
        return None
    s = _DOI_PREFIX_RE.sub("", str(value).strip()).strip()
    if _PCT_RE.search(s):
        s = unquote(s)
    s = s.lower()
    return s if _DOI_RE.match(s) else None


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _iter_json_lines(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


class GroupedJsonl:
    """JSONL을 처음 쓸 때 한 번 읽어 키별 원시 행으로 묶는다. 돌려줄 때만 모델로 검증한다(적재가 빠르다)."""

    def __init__(self, path: Path, model: type[BaseModel], key: Callable[[dict[str, Any]], str | None]) -> None:
        self.path = Path(path)
        self.model = model
        self._key = key
        self._rows: dict[str, list[dict[str, Any]]] | None = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.path.is_file()

    def load(self) -> int:
        if self._rows is None:
            with self._lock:
                if self._rows is None:
                    rows: dict[str, list[dict[str, Any]]] = {}
                    if self.path.is_file():
                        for row in _iter_json_lines(self.path):
                            k = self._key(row)
                            if k:
                                rows.setdefault(k, []).append(row)
                    self._rows = rows
        return sum(len(v) for v in self._rows.values())

    def get(self, key: str) -> list[Any] | None:
        """키의 레코드들. 파일이 없으면 None(빈 목록과 구별)."""
        if not self.available:
            return None
        self.load()
        assert self._rows is not None
        return [self.model.model_validate(row) for row in self._rows.get(key, [])]


# ── 얇은 어댑터: E2 색인 모듈이 없을 때 ──────────────────────────────────


@dataclass(frozen=True)
class _Hit:
    work_id: str
    score: float
    dense: float
    lexical: float
    matched_query: str


class FileIndexAdapter:
    """E2-L0 `neumann.index`를 불러올 수 없을 때 쓰는 비상 어댑터.

    색인 폴더의 works.jsonl·reviews.jsonl(E2 디스크 형식, 모델 JSON 한 줄씩)을 읽는다. 검색은 제목+초록과
    검색어의 토큰 겹침 비율(겹친 고유 토큰 수 / 검색어 고유 토큰 수)이다. 임베딩이 없으므로 항상 강등으로 표시한다.
    """

    BACKEND = "adapter_token_overlap"

    def __init__(self, index_dir: Path, reason: str) -> None:
        self.index_dir = Path(index_dir)
        self.reason = reason
        self._lock = threading.Lock()
        self._works: dict[str, Work] | None = None
        self._reviews: dict[str, list[ReviewEvent]] = {}
        self._doc_tokens: dict[str, frozenset[str]] = {}

    def _load(self) -> dict[str, Work]:
        if self._works is None:
            with self._lock:
                if self._works is None:
                    path = self.index_dir / "works.jsonl"
                    if not path.is_file():
                        raise DataUnavailable(f"색인이 없다: {path} (python scripts/build_index.py)")
                    works = {}
                    for row in _iter_json_lines(path):
                        w = Work.model_validate(row)
                        works[w.work_id] = w
                    reviews: dict[str, list[ReviewEvent]] = {}
                    rpath = self.index_dir / "reviews.jsonl"
                    if rpath.is_file():
                        for row in _iter_json_lines(rpath):
                            r = ReviewEvent.model_validate(row)
                            reviews.setdefault(r.work_id, []).append(r)
                    self._doc_tokens = {
                        wid: frozenset(_tokens(f"{w.title}\n{w.abstract or ''}")) for wid, w in works.items()
                    }
                    self._reviews = reviews
                    self._works = works
        return self._works

    def search(self, query: str, k: int) -> tuple[list[_Hit], dict[str, Any]]:
        self._load()
        status = {"backend": self.BACKEND, "degraded": True, "reason": self.reason}
        q = frozenset(_tokens(query))
        if not q:
            return [], status
        scored = []
        for wid, toks in self._doc_tokens.items():
            s = len(q & toks) / len(q)
            if s > 0:
                scored.append((round(s, 6), wid))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [_Hit(wid, s, 0.0, s, query) for s, wid in scored[:k]], status

    def get_work(self, work_id: str) -> Work | None:
        return self._load().get(work_id)

    def get_reviews(self, work_id: str) -> list[ReviewEvent]:
        self._load()
        return list(self._reviews.get(work_id, []))

    def warmup(self) -> dict[str, Any]:
        return {"backend": self.BACKEND, "n_works": len(self._load())}


# ── 기본 백엔드(공유 데이터 폴더) ─────────────────────────────────────────


def resolve_dirs(data_dir: str | os.PathLike[str] | None = None, index_dir: str | os.PathLike[str] | None = None) -> tuple[Path, Path]:
    """(data_dir, index_dir). 우선순위: 인자 > 환경변수 > 공용 설정(neumann.config)."""
    if data_dir is None:
        env = os.getenv("NEUMANN_DATA_DIR")
        if env:
            data_dir = env
        else:
            from neumann.config import get_settings

            data_dir = get_settings().data_dir
    d = Path(data_dir)
    if index_dir is None:
        index_dir = os.getenv("NEUMANN_INDEX_DIR") or (d / "index")
    return d, Path(index_dir)


def build_default_backend(
    data_dir: str | os.PathLike[str] | None = None, index_dir: str | os.PathLike[str] | None = None
) -> Backend:
    """공유 데이터 폴더를 쓰는 백엔드. E2·E1 모듈이 있으면 그것을, 없으면 파일 어댑터를 쓴다(info에 기록)."""
    d, idx = resolve_dirs(data_dir, index_dir)
    processed = d / "processed"
    info: dict[str, str] = {"data_dir": str(d), "index_dir": str(idx)}
    search_lock = threading.Lock()

    # 검색·논문·심사평: E2-L0
    try:
        from neumann.index import search as e2_search
        from neumann.index import store as e2_store
    except ImportError as exc:
        adapter = FileIndexAdapter(idx, f"neumann.index를 불러올 수 없다({exc.name or exc}): 토큰 겹침 비상 검색, 임베딩 없음")
        info["index"] = f"adapter:{FileIndexAdapter.BACKEND}"
        search_fn = adapter.search
        get_work = adapter.get_work
        get_reviews = adapter.get_reviews
        index_warmup = adapter.warmup
    else:
        info["index"] = "neumann.index.search+store"
        # 이 서버가 받은 색인 폴더를 그대로 쓴다(프로세스 공용 캐시 대신 자기 저장소, 처음 쓸 때 한 번 읽음)
        holder: dict[str, Any] = {}

        def _store() -> Any:
            if "store" not in holder:
                with search_lock:
                    if "store" not in holder:
                        holder["store"] = e2_store.IndexStore.load(idx)
            return holder["store"]

        def search_fn(query: str, k: int) -> tuple[list[Any], dict[str, Any]]:
            st_ = _store()
            with search_lock:  # last_search_status()가 이 호출의 상태가 되게
                hits = e2_search.search([query], k=k, store=st_)
                st = e2_search.last_search_status()
            return hits, {"backend": st.get("backend", "unknown"), "degraded": bool(st.get("degraded")), "reason": st.get("reason")}

        def get_work(work_id: str) -> Work | None:
            try:
                return _store().get_work(work_id)
            except KeyError:
                return None

        def get_reviews(work_id: str) -> list[ReviewEvent]:
            return _store().get_reviews(work_id)

        def index_warmup() -> dict[str, Any]:
            t0 = time.perf_counter()
            st_ = _store()
            t1 = time.perf_counter()
            _hits, status = search_fn("warmup", 1)  # 질의 임베딩 모델을 올린다
            return {
                "index_load_s": round(t1 - t0, 2),
                "first_search_s": round(time.perf_counter() - t1, 2),
                "n_works": len(st_.work_ids()),
                "backend": status["backend"],
                "reason": status["reason"],
            }

    # 저자 답변·결정: E1-L0 산출물
    responses = GroupedJsonl(processed / "author_responses.jsonl", AuthorResponse, lambda r: r.get("work_id"))
    decisions = GroupedJsonl(processed / "decisions.jsonl", Decision, lambda r: r.get("work_id"))

    # 사후 상태: E1-L2
    manifest_path = processed / "retraction_manifest.json"
    try:
        from neumann.sources import retraction as e1_rw
    except ImportError:
        rw_file = GroupedJsonl(processed / "retraction.jsonl", PostStatus, lambda r: normalize_doi(r.get("target_doi")))
        info["post_status"] = "adapter:processed/retraction.jsonl"
        norm = normalize_doi

        def get_post_status(doi: str) -> list[PostStatus]:
            got = rw_file.get(normalize_doi(doi) or "")
            if got is None:
                raise DataUnavailable(f"사후상태 데이터가 없다: {rw_file.path}")
            return got

        def rw_warmup() -> int:
            return rw_file.load()
    else:
        info["post_status"] = "neumann.sources.retraction"
        norm = e1_rw.normalize_doi

        def get_post_status(doi: str) -> list[PostStatus]:
            return e1_rw.get_post_status(doi, data_dir=d)

        def rw_warmup() -> int:
            return e1_rw.load_index(d).n_records

    def retraction_meta() -> dict[str, Any]:
        if not manifest_path.is_file():
            return {}
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        return {
            "citation": m.get("citation"),
            "dataset_url": m.get("dataset_home") or m.get("dataset_url"),
            "license": m.get("license"),
            "snapshot": m.get("snapshot_generated"),
        }

    def warmup() -> dict[str, Any]:
        out: dict[str, Any] = {}
        t0 = time.perf_counter()
        try:
            out["index"] = index_warmup()
        except Exception as exc:  # 색인이 없어도 서버는 뜬다. 도구 호출 때 오류로 알린다
            out["index_error"] = f"{type(exc).__name__}: {exc}"
        try:
            out["post_status_records"] = rw_warmup()
        except Exception as exc:
            out["post_status_error"] = f"{type(exc).__name__}: {exc}"
        out["responses"] = responses.load()
        out["decisions"] = decisions.load()
        out["elapsed_s"] = round(time.perf_counter() - t0, 2)
        return out

    return Backend(
        search=search_fn,
        get_work=get_work,
        get_reviews=get_reviews,
        get_responses=responses.get,
        get_decisions=decisions.get,
        get_post_status=get_post_status,
        normalize_doi=norm,
        retraction_meta=retraction_meta,
        info=info,
        warmup=warmup,
    )


# ── 도구 본체 ─────────────────────────────────────────────────────────────


def _head(text: str | None) -> dict[str, Any]:
    text = text or ""
    head = text[:HEAD_CHARS]
    return {
        "text_chars": len(text),
        "text_head": head,
        "truncated": len(text) > len(head),
        "text_sha256": None if not text else _sha256(text),
    }


def _sha256(text: str) -> str:
    from neumann.models import sha256_text

    return sha256_text(text)


def _work_ref(w: Work) -> dict[str, Any]:
    return {
        "work_id": w.work_id,
        "title": w.title,
        "url": w.url,
        "source_url": w.provenance.source_url,
        "doi": w.doi,
        "venue": w.venue,
        "year": w.year,
    }


def run_search(be: Backend, query: str, k: int = DEFAULT_K) -> SearchResult:
    q = (query or "").strip()
    if not q:
        raise ToolError("검색어가 비었다. 짧은 검색어(주제·방법·데이터셋 이름)를 넣는다.")
    if len(q) > MAX_QUERY_CHARS:
        raise ToolError(
            f"검색어가 {len(q)}자다. 이 도구는 검색어만 받는다({MAX_QUERY_CHARS}자 이하). "
            "계획서 본문은 보내지 않는다 — 핵심 주제·방법을 짧게 줄여 다시 부른다."
        )
    if not 1 <= k <= MAX_K:
        raise ToolError(f"k는 1~{MAX_K}다(받은 값 {k}).")
    try:
        hits, status = be.search(q, k)
    except (FileNotFoundError, DataUnavailable) as exc:
        raise ToolError(f"검색 색인을 읽을 수 없다: {exc}") from exc
    out: list[SimilarWork] = []
    for h in hits:
        w = be.get_work(h.work_id)
        if w is None:  # 색인과 논문 목록이 어긋난 경우: 출처 없는 결과는 내보내지 않는다
            log.warning("검색 결과 %s가 논문 목록에 없어 뺐다", h.work_id)
            continue
        out.append(
            SimilarWork(
                **_work_ref(w),
                fields=list(w.fields),
                score=h.score,
                dense=h.dense,
                lexical=h.lexical,
                matched_query=h.matched_query,
            )
        )
    return SearchResult(
        query=q,
        k=k,
        n_hits=len(out),
        hits=out,
        backend=str(status.get("backend") or "unknown"),
        degraded=bool(status.get("degraded")),
        reason=status.get("reason"),
    )


def run_review_records(be: Backend, work_id: str) -> ReviewRecordsResult:
    wid = (work_id or "").strip()
    if not wid:
        raise ToolError("work_id가 비었다. search_similar_works 결과의 work_id를 넣는다.")
    try:
        work = be.get_work(wid)
    except (FileNotFoundError, DataUnavailable) as exc:
        raise ToolError(f"색인을 읽을 수 없다: {exc}") from exc
    if work is None:
        raise ToolError(f"work_id {wid!r}가 색인에 없다. search_similar_works 결과의 work_id를 그대로 쓴다.")
    notes: list[str] = []
    reviews = be.get_reviews(wid)
    responses = be.get_responses(wid)
    if responses is None:
        notes.append("저자 답변 데이터 파일이 없다(processed/author_responses.jsonl) — 답변 0건은 '없음'이 아니라 '모름'이다.")
        responses = []
    decisions = be.get_decisions(wid)
    if decisions is None:
        notes.append("결정 데이터 파일이 없다(processed/decisions.jsonl) — 결정 0건은 '없음'이 아니라 '모름'이다.")
        decisions = []
    if be.info.get("index", "").startswith("adapter:"):
        notes.append("색인 모듈(E2) 대신 파일 어댑터로 읽었다.")

    def _url(rec: Any) -> str:
        return rec.url or rec.provenance.source_url

    return ReviewRecordsResult(
        work=WorkRef(**_work_ref(work)),
        decisions=[
            DecisionRecord(
                decision_id=x.decision_id,
                outcome=x.outcome.value,
                outcome_raw=x.outcome_raw,
                url=_url(x),
                source_url=x.provenance.source_url,
                **_head(x.text),
            )
            for x in decisions
        ],
        reviews=[
            ReviewRecord(
                review_id=r.review_id,
                kind=r.kind.value,
                round=r.round,
                rating=r.rating,
                confidence=r.confidence,
                created=r.created.isoformat() if r.created else None,
                url=_url(r),
                source_url=r.provenance.source_url,
                **_head(r.text),
            )
            for r in reviews
        ],
        responses=[
            ResponseRecord(
                response_id=a.response_id,
                review_id=a.review_id,
                round=a.round,
                url=_url(a),
                source_url=a.provenance.source_url,
                **_head(a.text),
            )
            for a in responses
        ],
        n_reviews=len(reviews),
        n_responses=len(responses),
        n_decisions=len(decisions),
        notes=notes,
    )


def run_post_status(be: Backend, doi: str) -> PostStatusResult:
    raw = (doi or "").strip()
    norm = be.normalize_doi(raw)
    if norm is None:
        raise ToolError(f"DOI 형식이 아니다: {raw!r}. 예: 10.1234/abcd.5678 또는 https://doi.org/10.1234/abcd.5678")
    try:
        records = be.get_post_status(norm)
    except (FileNotFoundError, DataUnavailable) as exc:
        raise ToolError(f"사후상태 데이터를 읽을 수 없다: {exc}") from exc
    meta = be.retraction_meta()
    return PostStatusResult(
        query=raw,
        doi=norm,
        status="found" if records else "no_record",
        n_records=len(records),
        records=[
            PostStatusRecord(
                post_status_id=p.post_status_id,
                kind=p.kind.value,
                target_doi=p.target_doi,
                notice_doi=p.notice_doi,
                notice_url=p.url,
                reason_codes=list(p.reason_codes),
                source_url=p.provenance.source_url,
                snapshot=p.provenance.api_version,
                accessed_at=p.provenance.accessed_at.isoformat(),
            )
            for p in records
        ],
        citation=meta.get("citation"),
        dataset_url=meta.get("dataset_url"),
        license=meta.get("license"),
        snapshot=meta.get("snapshot"),
        backend=be.info.get("post_status", "unknown"),
    )


# ── 서버 ─────────────────────────────────────────────────────────────────


def create_server(backend: Backend | None = None, *, log_level: str = "WARNING") -> MCPServer:
    """도구 3종을 등록한 MCP 서버. backend를 주지 않으면 공유 데이터 폴더를 쓴다."""
    be = backend or build_default_backend()
    server = MCPServer(
        name=SERVER_NAME,
        title="Neumann evidence (read-only)",
        instructions=INSTRUCTIONS,
        version=SERVER_VERSION,
        log_level=log_level,  # type: ignore[arg-type]
    )

    @server.tool(title="유사 연구 검색 (similar works)", annotations=READ_ONLY)
    def search_similar_works(
        query: Annotated[str, Field(description=f"짧은 검색어(주제·방법·데이터셋). {MAX_QUERY_CHARS}자 이하. 계획서 본문 금지. 한국어 가능")],
        k: Annotated[int, Field(description=f"돌려줄 논문 수 1~{MAX_K}")] = DEFAULT_K,
    ) -> SearchResult:
        """심사 기록이 있는 코퍼스(ICLR 등 AI for Science 논문)에서 검색어와 비슷한 연구를 찾는다.

        결과: 논문 id(work_id)·제목·원문 URL(url, source_url)·점수(score 0~1, dense, lexical)와 검색 백엔드·강등 여부.
        Returns similar works with work_id, title, source URLs and 0-1 scores. Read-only.
        """
        return run_search(be, query, k)

    @server.tool(title="심사 기록 조회 (review records)", annotations=READ_ONLY)
    def get_review_records(
        work_id: Annotated[str, Field(description="search_similar_works가 돌려준 work_id")],
    ) -> ReviewRecordsResult:
        """논문 하나의 심사평·저자 답변·결정을 요약해 돌려준다. 신원 정보(리뷰어·저자)는 없다.

        레코드마다 원문 URL과 원문 앞부분(text_head, 글자 그대로 최대 600자)·전체 길이·해시가 붙는다.
        없는 work_id는 오류(is_error)로 알린다. Returns reviews, author responses and decisions with source URLs.
        """
        return run_review_records(be, work_id)

    @server.tool(title="사후 상태 조회 (post-publication status)", annotations=READ_ONLY)
    def get_post_status(
        doi: Annotated[str, Field(description="원논문 DOI. 10.xxxx/... 또는 https://doi.org/... 형식")],
    ) -> PostStatusResult:
        """원논문 DOI로 철회·정정·우려표명 등 사후 상태를 찾는다(Crossref Retraction Watch).

        레코드마다 공지 링크(notice_url)·사유 원문·데이터셋 URL이 붙는다. 기록이 없으면 status=no_record(빈 목록).
        Returns retraction/correction records and notice links for the original paper DOI.
        """
        return run_post_status(be, doi)

    return server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m neumann.api.mcp_server", description="Neumann MCP 서버(stdio, 읽기 전용)")
    ap.add_argument("--data-dir", help="공유 데이터 폴더(기본 NEUMANN_DATA_DIR)")
    ap.add_argument("--index-dir", help="색인 폴더(기본 NEUMANN_INDEX_DIR 또는 {data}/index)")
    ap.add_argument("--no-warmup", action="store_true", help="시작 때 색인·임베딩 모델을 미리 읽지 않는다")
    ap.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    args = ap.parse_args(argv)

    # 모델이 로컬에 있으므로 허브에 나가지 않는다(읽기 전용·외부 요청 없음)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    # E2 설정이 같은 폴더를 보게 환경변수로 넘긴다(인자 > 환경변수)
    if args.data_dir:
        os.environ["NEUMANN_DATA_DIR"] = args.data_dir
    if args.index_dir:
        os.environ["NEUMANN_INDEX_DIR"] = args.index_dir

    backend = build_default_backend(args.data_dir, args.index_dir)
    server = create_server(backend, log_level=args.log_level)
    log.info("backend %s", backend.info)
    if not args.no_warmup and backend.warmup is not None:
        warm = backend.warmup

        def _warm() -> None:
            try:
                log.info("warmup %s", warm())
            except Exception:  # 로그만. 도구 호출 때 다시 시도하고 오류를 돌려준다
                log.exception("warmup 실패")

        threading.Thread(target=_warm, name="neumann-mcp-warmup", daemon=True).start()
    server.run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
