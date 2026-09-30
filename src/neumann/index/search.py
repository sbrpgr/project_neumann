"""하이브리드 검색: bge-m3 임베딩(다국어) + BM25(영어 어휘) 단순 결합.

`search(queries, k=10, exclude_work_ids=None) -> list[SearchHit]`

- 질의마다 논문별로 `dense`(코사인, 0 미만은 0) · `lexical`(BM25 정규화, 0~1)을 구하고
  `score = alpha·dense + (1−alpha)·lexical` (alpha 기본 0.6). 논문 점수는 질의들 중 최댓값이고,
  그 질의가 `matched_query`다. 한국어 질의는 BM25에 거의 안 걸리므로 임베딩이 찾는다.
- `exclude_work_ids`: 백테스트 누출 제거(E5-L2).
- 점수 하한 `NEUMANN_SEARCH_SCORE_FLOOR`(기본 0.0). 보정은 L1.
- 임베딩 모델을 못 읽으면 어휘 검색만 하고 `last_search_status()`에 강등(degraded)을 남긴다.
  이때도 점수는 `(1−alpha)·lexical`로 같은 척도다(숨기지 않는다).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np
from pydantic import Field

from neumann.index.embed import Embedder, EmbedderUnavailable, get_embedder
from neumann.index.settings import get_index_settings
from neumann.index.store import IndexStore, get_store
from neumann.models import NeumannModel

log = logging.getLogger(__name__)


class SearchHit(NeumannModel):
    """검색 결과 한 편. 점수는 모두 0~1."""

    work_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0, description="결합 점수 alpha·dense + (1−alpha)·lexical")
    dense: float = Field(ge=0.0, le=1.0, description="bge-m3 코사인(음수는 0)")
    lexical: float = Field(ge=0.0, le=1.0, description="BM25 정규화 점수")
    matched_query: str = Field(description="이 논문에서 결합 점수가 가장 높았던 질의")


_QUERY_EMBEDDER: Embedder | None = None
_STATUS: dict[str, Any] = {}
_STATUS_LOCK = threading.Lock()


def set_query_embedder(embedder: Embedder | None) -> None:
    """질의 임베딩 모델 주입(테스트). None이면 기본(bge-m3, 지연 로드)으로 돌아간다."""
    global _QUERY_EMBEDDER
    _QUERY_EMBEDDER = embedder


def _query_embedder(store: IndexStore) -> tuple[Embedder | None, str | None]:
    """(embedder, 강등 사유)."""
    if store.embeddings is None:
        return None, "색인에 임베딩이 없다(어휘 검색만)"
    emb = _QUERY_EMBEDDER
    if emb is None:
        try:
            emb = get_embedder()
        except EmbedderUnavailable as exc:
            return None, str(exc)
    if int(emb.dim) != int(store.embeddings.shape[1]):
        return None, f"임베딩 차원 불일치: 모델 {emb.dim} != 색인 {store.embeddings.shape[1]}"
    want = store.manifest.get("dense_model")
    if want and getattr(emb, "model_id", None) and emb.model_id != want:
        return None, f"임베딩 모델 불일치: 모델 {emb.model_id} != 색인 {want}"
    return emb, None


def last_search_status() -> dict[str, Any]:
    """마지막 search() 호출의 백엔드·강등 여부·소요 시간. 파이프라인이 StageStatus에 옮겨 적는다."""
    with _STATUS_LOCK:
        return dict(_STATUS)


def search(
    queries: list[str],
    k: int = 10,
    exclude_work_ids: set[str] | None = None,
    *,
    store: IndexStore | None = None,
    alpha: float | None = None,
    score_floor: float | None = None,
) -> list[SearchHit]:
    """질의 목록 → 상위 k편(점수 내림차순, 같으면 work_id 순). 결과는 결정적이다."""
    t0 = time.perf_counter()
    ist = get_index_settings()
    alpha = ist.search_alpha if alpha is None else alpha
    floor = ist.search_score_floor if score_floor is None else score_floor
    qs = [q.strip() for q in dict.fromkeys(queries) if q and q.strip()]
    store = store or get_store()
    n = len(store.work_order)
    status: dict[str, Any] = {"n_queries": len(qs), "n_works": n, "alpha": alpha, "score_floor": floor}
    if not qs or n == 0 or k <= 0:
        status.update(backend="none", degraded=False, reason="빈 질의 또는 빈 색인", elapsed_s=0.0)
        _set_status(status)
        return []

    lex = np.array([store.bm25.scores(q) for q in qs], dtype=np.float32)  # (Q, N)
    embedder, reason = _query_embedder(store)
    if embedder is not None:
        qv = np.asarray(embedder.encode(qs), dtype=np.float32)  # (Q, D)
        dense = np.clip(qv @ store.embeddings.T, 0.0, 1.0)  # type: ignore[union-attr]
        status.update(backend="hybrid", degraded=False, dense_model=getattr(embedder, "model_id", None),
                      device=getattr(embedder, "device", None))
    else:
        dense = np.zeros_like(lex)
        status.update(backend="lexical_only", degraded=True, reason=reason)
        log.warning("검색 강등(어휘만): %s", reason)

    combined = alpha * dense + (1.0 - alpha) * lex  # (Q, N)
    best_q = np.argmax(combined, axis=0)  # 같은 점수면 앞 질의
    cols = np.arange(n)
    best = combined[best_q, cols]

    excluded = exclude_work_ids or set()
    order = sorted(range(n), key=lambda i: (-float(best[i]), store.work_order[i]))
    hits: list[SearchHit] = []
    n_excluded = 0
    for i in order:
        wid = store.work_order[i]
        if wid in excluded:
            n_excluded += 1
            continue
        score = float(best[i])
        if score < floor:
            break
        qi = int(best_q[i])
        hits.append(
            SearchHit(
                work_id=wid,
                score=_unit(score),
                dense=_unit(float(dense[qi, i])),
                lexical=_unit(float(lex[qi, i])),
                matched_query=qs[qi],
            )
        )
        if len(hits) >= k:
            break
    status.update(n_hits=len(hits), n_excluded=n_excluded, elapsed_s=round(time.perf_counter() - t0, 4),
                  top_score=hits[0].score if hits else None)
    _set_status(status)
    return hits


def _unit(x: float) -> float:
    return float(min(1.0, max(0.0, round(x, 6))))


def _set_status(status: dict[str, Any]) -> None:
    with _STATUS_LOCK:
        _STATUS.clear()
        _STATUS.update(status)


def warmup() -> dict[str, Any]:
    """서버 시작 때 부른다: 색인을 읽고 질의 임베딩 모델을 올린다. 소요 시간을 돌려준다."""
    t0 = time.perf_counter()
    store = get_store()
    t1 = time.perf_counter()
    emb, reason = _query_embedder(store)
    t2 = time.perf_counter()
    return {
        "index_load_s": round(t1 - t0, 3),
        "embedder_load_s": round(t2 - t1, 3),
        "dense": emb is not None,
        "device": getattr(emb, "device", None),
        "reason": reason,
        "n_works": len(store.work_order),
        "n_excerpts": store.n_excerpts(),
    }


__all__ = ["SearchHit", "last_search_status", "search", "set_query_embedder", "warmup"]
