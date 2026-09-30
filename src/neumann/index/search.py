"""하이브리드 검색: bge-m3 임베딩(다국어) + BM25(영어 어휘), 여러 질의는 순위 융합.

`search(queries, k=10, exclude_work_ids=None) -> list[SearchHit]` (L0 호출 모양 그대로, 나머지는 키워드 인자)

질의 하나의 점수
- 논문별 `dense`(코사인, 0 미만은 0) · `lexical`(BM25 정규화, 0~1).
- `score = a·dense + (1−a)·lexical`. `a`는 기본 alpha(0.6)에서 **어휘 적용률**만큼만 BM25에 비중을 준다:
  `a = 1 − (1 − alpha)·coverage`, coverage = 질의 낱말 중 색인 어휘에 있는 것의 idf 비율(`lexical_coverage`).
  영어 질의(coverage≈1)는 L0와 같고, 한국어만 질의(coverage=0)는 `score = dense`다 — BM25가 볼 수 없는
  낱말 때문에 점수가 깎이지 않아 언어가 달라도 같은 하한을 쓸 수 있다(E2-L1). 끄려면 `adaptive_alpha=False`.

여러 질의 결합(`fusion`)
- `rrf`(기본): 질의마다 하한을 넘은 논문에 순위를 매기고 `Σ 축가중치 / (rrf_k + 순위)`로 정렬한다.
  한 질의의 절대 점수가 높아도 상위 10편을 독점하지 못한다.
- `max`: L0 방식(질의 중 가중 최댓값).
- `per_query_min=n`: 질의마다 상위 n편을 결과에 먼저 넣는다(질의별 상위 할당, 가중치 큰 질의부터 번갈아).
  할당 몫은 k의 절반까지(나머지 절반은 결합 순서 = 여러 질의가 함께 가리키는 논문).
- `axes`: 질의와 같은 길이의 축 이름 목록(topic·method·data·evaluation, `neumann.index.queries`).
  축 가중치(`NEUMANN_SEARCH_AXIS_WEIGHTS`)가 결합 기여에 곱해진다. 결과의 `axis_scores`에 축별 최고 점수.
- 결과의 `score`·`dense`·`lexical`·`matched_query`는 언제나 "그 논문에서 점수가 가장 높았던 질의" 값이다
  (절대 척도, 하한과 같은 척도). 결과 순서는 결합 순서(`fused`)라서 여러 질의일 때 `score`가 내림차순이 아닐 수 있다.

점수 하한과 "관련 없음"
- 하한은 (질의, 논문) 쌍마다 `관련도 = max(dense, score)`에 건다: 하한 미만인 쌍은 그 질의의 순위에 들어가지 않는다.
  BM25는 근거를 더할 수는 있어도 임베딩이 찾은 것을 깎지 못한다(영어 축 질의에서 표적 논문이 1·2위인데
  결합 점수가 0.40~0.42라 잘리던 문제, E2-L1 보고서). 순위 자체는 `score`로 매긴다.
- 기본 하한은 임베딩 모델별 실측 보정값(`FLOOR_CALIBRATION`, E2-L1 `scripts/build_index_calibrate.py`).
  보정값이 없는 모델·어휘만 검색(강등)은 0이다(점수 척도가 달라서. 계획서 §4 E2 함정 "하한은 백엔드마다 다르다").
  `NEUMANN_SEARCH_SCORE_FLOOR`·`score_floor=`를 주면 그 값을 쓴다.
- 하한을 넘은 논문이 하나도 없으면 빈 목록이고 `last_search_status()["relevance"]["verdict"] == "unrelated"`,
  근거(하한, 출처, 1위 점수, 보정 실측 요약)도 같이 남는다.
- **적용 범위(E2-L1 검증 5b·5c)**: 하한 0.45는 27건(관련 18·무관 9) 세트에서 잰 값이다. `verdict="related"`는
  주제가 맞다는 증거가 아니다. 짧은 한국어 일상 질의(예: "시험 공부법" 1위 0.550, 24개 중 12개 통과),
  학술체 무관 영어 글, 일반 학술어 질의는 통과할 수 있다. 1차 판정은 astra의 `is_research`다.
- 하한은 `max(dense, score)`에 걸리므로 `score`가 0.45 미만인 결과도 나올 수 있다(dense가 0.45 이상일 때).
- 여러 질의일 때 결과(따라서 이를 옮긴 `similar_works`)는 결합 순서라 유사도(`score`) 내림차순이 아니다.

기타
- `exclude_work_ids`: 백테스트 누출 제거(E5-L2). work_id 완전 일치. 색인에 없는 id는 상태의 `unmatched_excludes`.
- 임베딩 모델을 못 읽으면 어휘 검색만 하고 `last_search_status()`에 강등(degraded)을 남긴다.
  이때 점수는 `(1−alpha)·lexical`(L0와 같은 척도)이고 기본 하한은 0이다.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from pydantic import Field

from neumann.index.bm25 import BM25Index, tokenize
from neumann.index.embed import Embedder, EmbedderUnavailable, get_embedder
from neumann.index.queries import normalize_axis
from neumann.index.settings import get_index_settings
from neumann.index.store import IndexStore, get_store
from neumann.models import NeumannModel

log = logging.getLogger(__name__)

# 임베딩 모델별 점수 하한 실측 보정(E2-L1). 값과 근거는 docs/reports/E2-L1.md 표.
FLOOR_CALIBRATION: dict[str, dict[str, Any]] = {
    "bge-m3": {
        "floor": 0.45,
        "basis": "E2-L1 실측(색인 1,128편, 관련도 max(dense, score)의 1위): 무관한 글 9건 최대 0.422(영어 빵 굽기), "
        "관련 질의 18건 중 17건은 10위까지 0.469 이상, 1건(한국어 제목 '의료영상 분류 심층신경망' 0.427, 코퍼스에 "
        "의료영상 논문 없음)은 관련 없음 판정. 하한 0.43~0.46 구간에서 무관 0/9·관련 17/18 10편 유지. "
        "계획서 §3 L1 참고값 bge-m3 0.45. 적용 범위: 이 27건 세트에서 잰 값이고 verdict=related는 주제 관련성의 "
        "증거가 아니다. 짧은 한국어 일상 질의(예: '시험 공부법' 1위 0.550)와 학술체 무관 글은 통과할 수 있다"
        "(E2-L1 검증 5b·5c). 1차 판정은 astra is_research",
    },
}


class SearchHit(NeumannModel):
    """검색 결과 한 편. 점수는 모두 0~1."""

    work_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0, description="가장 잘 맞은 질의의 결합 점수 a·dense + (1−a)·lexical")
    dense: float = Field(ge=0.0, le=1.0, description="bge-m3 코사인(음수는 0)")
    lexical: float = Field(ge=0.0, le=1.0, description="BM25 정규화 점수")
    matched_query: str = Field(description="이 논문에서 결합 점수가 가장 높았던 질의")
    fused: float | None = Field(default=None, ge=0.0, description="정렬 키(rrf: 가중 순위 합, max: 가중 최댓값)")
    axis_scores: dict[str, float] = Field(default_factory=dict, description="축별 최고 결합 점수(axes를 줬을 때)")


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
    """마지막 search() 호출의 백엔드·강등·하한·관련성 판정·질의별 요약·소요 시간. 파이프라인이 StageStatus에 옮겨 적는다."""
    with _STATUS_LOCK:
        return dict(_STATUS)


def lexical_coverage(bm25: BM25Index, query: str) -> float:
    """질의 낱말(중복 제거) 중 색인 어휘에 있는 것의 idf 비율(0~1). 한국어만 질의는 0, 영어는 대개 1 근처."""
    toks = set(tokenize(query))
    total = sum(bm25.idf(t) for t in toks)
    if total <= 0:
        return 0.0
    seen = sum(bm25.idf(t) for t in toks if t in bm25.postings)
    return float(min(1.0, max(0.0, seen / total)))


def default_floor(model_id: str | None) -> tuple[float, str]:
    """(하한, 출처). 보정값이 없는 모델이면 0."""
    cal = FLOOR_CALIBRATION.get(model_id or "")
    if cal:
        return float(cal["floor"]), f"calibrated:{model_id}"
    return 0.0, f"uncalibrated:{model_id or 'none'}"


def _clean_queries(
    queries: Sequence[str], axes: Sequence[str | None] | None
) -> tuple[list[str], list[str | None], list[str]]:
    """앞뒤 공백 제거, 빈 질의 제거, 같은 질의는 처음 것만(축도 처음 것). (질의, 축, 모르는 축 이름)."""
    if axes is not None and len(axes) != len(queries):
        raise ValueError(f"axes 길이 {len(axes)} != queries 길이 {len(queries)}")
    qs: list[str] = []
    q_axes: list[str | None] = []
    unknown: list[str] = []
    for i, q in enumerate(queries):
        qq = (q or "").strip()
        if not qq or qq in qs:
            continue
        raw = None if axes is None else axes[i]
        ax = normalize_axis(raw) if raw is not None else None
        if raw is not None and ax is None:
            unknown.append(str(raw))
            ax = str(raw).strip().lower() or None
        qs.append(qq)
        q_axes.append(ax)
    return qs, q_axes, unknown


def search(
    queries: list[str],
    k: int = 10,
    exclude_work_ids: set[str] | None = None,
    *,
    store: IndexStore | None = None,
    alpha: float | None = None,
    score_floor: float | None = None,
    fusion: str | None = None,
    rrf_k: float | None = None,
    per_query_min: int | None = None,
    axes: Sequence[str | None] | None = None,
    axis_weights: Mapping[str, float] | None = None,
    adaptive_alpha: bool | None = None,
) -> list[SearchHit]:
    """질의 목록 → 상위 k편(결합 순서, 같으면 점수·work_id 순). 결과는 결정적이다. 추가 인자는 모듈 설명."""
    t0 = time.perf_counter()
    ist = get_index_settings()
    alpha = ist.search_alpha if alpha is None else float(alpha)
    fusion = (fusion or ist.search_fusion).lower()
    if fusion not in ("rrf", "max"):
        raise ValueError(f"fusion은 rrf 또는 max: {fusion!r}")
    rrf_k = ist.search_rrf_k if rrf_k is None else float(rrf_k)
    quota = ist.search_per_query_min if per_query_min is None else max(0, int(per_query_min))
    adaptive = ist.search_adaptive_alpha if adaptive_alpha is None else bool(adaptive_alpha)
    weights_by_axis = dict(ist.axis_weights())
    if axis_weights:
        weights_by_axis.update({str(a).lower(): float(w) for a, w in axis_weights.items()})
    qs, q_axes, unknown_axes = _clean_queries(queries, axes)
    q_w = np.array([weights_by_axis.get(a or "topic", 1.0) for a in q_axes], dtype=np.float64)

    store = store or get_store()
    n = len(store.work_order)
    status: dict[str, Any] = {"n_queries": len(qs), "n_works": n, "alpha": alpha, "fusion": fusion}
    if not qs or n == 0 or k <= 0:
        status.update(backend="none", degraded=False, reason="빈 질의 또는 빈 색인", elapsed_s=0.0,
                      relevance={"verdict": "unknown", "reason": "빈 질의 또는 빈 색인"})
        _set_status(status)
        return []

    lex = np.array([store.bm25.scores(q) for q in qs], dtype=np.float32)  # (Q, N)
    cov = np.array([lexical_coverage(store.bm25, q) for q in qs], dtype=np.float32)
    embedder, reason = _query_embedder(store)
    if embedder is not None:
        qv = np.asarray(embedder.encode(qs), dtype=np.float32)  # (Q, D)
        dense = np.clip(qv @ store.embeddings.T, 0.0, 1.0)  # type: ignore[union-attr]
        a_eff = (1.0 - (1.0 - alpha) * cov) if adaptive else np.full(len(qs), alpha, dtype=np.float32)
        model_id = getattr(embedder, "model_id", None)
        status.update(backend="hybrid", degraded=False, dense_model=model_id, device=getattr(embedder, "device", None))
    else:
        dense = np.zeros_like(lex)
        a_eff = np.full(len(qs), alpha, dtype=np.float32)  # 어휘만: L0와 같은 척도 (1−alpha)·lexical
        model_id = None
        status.update(backend="lexical_only", degraded=True, reason=reason)
        log.warning("검색 강등(어휘만): %s", reason)

    if score_floor is not None:
        floor, floor_source = float(score_floor), "argument"
    elif ist.search_score_floor is not None:
        floor, floor_source = float(ist.search_score_floor), "setting:NEUMANN_SEARCH_SCORE_FLOOR"
    elif embedder is None:
        floor, floor_source = 0.0, "lexical_only:uncalibrated"
    else:
        floor, floor_source = default_floor(model_id)

    a_col = a_eff.astype(np.float32)[:, None]
    combined = a_col * dense + (1.0 - a_col) * lex  # (Q, N)

    excluded = set(exclude_work_ids or ())
    unmatched = sorted(excluded - set(store.work_order)) if excluded else []
    col_ok = np.array([wid not in excluded for wid in store.work_order], dtype=bool)
    relevance = np.maximum(dense, combined)  # 하한을 거는 값: BM25는 더할 수만 있다
    ok = (relevance >= floor) & col_ok[None, :]  # (Q, N) 하한을 넘은 (질의, 논문) 쌍

    # 질의별 순위: 하한을 넘고 관련도가 0보다 큰 논문만, 점수 내림차순, 같으면 work_id 순
    # (하한 0일 때 관련도 0인 쌍은 결과에는 남지만 순위 융합·할당에는 기여하지 않는다)
    wid_rank = np.empty(n, dtype=np.int64)
    wid_rank[np.array(sorted(range(n), key=lambda i: store.work_order[i]), dtype=np.int64)] = np.arange(n)
    per_q_order: list[np.ndarray] = []
    for qi in range(len(qs)):
        idx = np.flatnonzero(ok[qi] & (relevance[qi] > 0.0))
        per_q_order.append(idx[np.lexsort((wid_rank[idx], -combined[qi, idx]))])

    masked = np.where(ok, combined, -1.0)
    best_q = np.argmax(masked, axis=0)  # 같은 점수면 앞 질의
    best = masked[best_q, np.arange(n)]
    alive = best >= 0.0
    if fusion == "rrf":
        fused = np.zeros(n, dtype=np.float64)
        for qi, idx in enumerate(per_q_order):
            fused[idx] += q_w[qi] / (rrf_k + np.arange(1, len(idx) + 1, dtype=np.float64))
    else:
        fused = np.max(np.where(ok, combined * q_w[:, None], -1.0), axis=0).astype(np.float64)
    fused = np.where(alive, fused, -1.0)

    order_all = [int(i) for i in np.lexsort((wid_rank, -best, -fused)) if alive[i]]
    chosen = _select(order_all, per_q_order, q_w, k, quota)

    hits: list[SearchHit] = []
    for i in chosen:
        qi = int(best_q[i])
        ax_scores: dict[str, float] = {}
        if axes is not None:
            for qj, ax in enumerate(q_axes):
                if ok[qj, i]:
                    name = ax or "topic"
                    ax_scores[name] = max(ax_scores.get(name, 0.0), _unit(float(combined[qj, i])))
        hits.append(
            SearchHit(
                work_id=store.work_order[i],
                score=_unit(float(combined[qi, i])),
                dense=_unit(float(dense[qi, i])),
                lexical=_unit(float(lex[qi, i])),
                matched_query=qs[qi],
                fused=round(max(0.0, float(fused[i])), 8),
                axis_scores=ax_scores,
            )
        )

    top_any = float(np.max(np.where(col_ok[None, :], relevance, 0.0)))
    n_above = int(alive.sum())
    verdict = ("related" if n_above > 0 else "unrelated") if floor > 0.0 else "unknown"
    cal = FLOOR_CALIBRATION.get(model_id or "") if floor_source.startswith("calibrated") else None
    status.update(
        score_floor=floor,
        floor_source=floor_source,
        floor_on="max(dense, score)",
        rrf_k=rrf_k if fusion == "rrf" else None,
        per_query_min=quota,
        adaptive_alpha=adaptive,
        relevance={
            "verdict": verdict,
            "top_relevance": round(top_any, 6),
            "floor": floor,
            "margin": round(top_any - floor, 6),
            "n_above_floor": n_above,
            "floor_source": floor_source,
            "basis": cal["basis"] if cal else ("하한 0: 판정하지 않음" if floor <= 0 else "지정값"),
        },
        per_query=[
            {
                "query": q[:80],
                "axis": q_axes[qi],
                "weight": float(q_w[qi]),
                "coverage": round(float(cov[qi]), 4),
                "alpha_eff": round(float(a_eff[qi]), 4),
                "top_score": round(float(np.max(np.where(col_ok, combined[qi], 0.0))), 6),
                "top_relevance": round(float(np.max(np.where(col_ok, relevance[qi], 0.0))), 6),
                "n_above_floor": len(per_q_order[qi]),
                "n_best_match": sum(1 for h in hits if h.matched_query == q),  # 결과 중 이 질의 점수가 가장 높은 편수
                "n_ranked_in_results": int(np.count_nonzero(ok[qi, chosen] & (relevance[qi, chosen] > 0.0)))
                if chosen
                else 0,  # 결과 중 이 질의가 순위를 매긴(하한 통과) 편수 = 결합에 기여한 편수
            }
            for qi, q in enumerate(qs)
        ],
        n_hits=len(hits),
        n_excluded=int((~col_ok).sum()),
        unmatched_excludes=unmatched[:20],
        n_unmatched_excludes=len(unmatched),
        elapsed_s=round(time.perf_counter() - t0, 4),
        top_score=hits[0].score if hits else None,
    )
    if unknown_axes:
        status["unknown_axes"] = sorted(set(unknown_axes))
    _set_status(status)
    return hits


def _select(order_all: list[int], per_q_order: list[np.ndarray], q_w: np.ndarray, k: int, quota: int) -> list[int]:
    """질의별 상위 할당(quota편씩, 가중치 큰 질의부터 번갈아, k의 절반까지) → 나머지는 결합 순서. 결합 순서로 정렬."""
    chosen: list[int] = []
    seen: set[int] = set()
    if quota > 0 and len(per_q_order) > 1:
        reserve = max(1, (k + 1) // 2)  # 할당 몫은 k의 절반까지
        prio = sorted(range(len(per_q_order)), key=lambda qi: (-q_w[qi], qi))
        cursors = [0] * len(per_q_order)
        for _ in range(quota):
            for qi in prio:
                if len(chosen) >= reserve or q_w[qi] <= 0:
                    continue
                order = per_q_order[qi]
                while cursors[qi] < len(order) and int(order[cursors[qi]]) in seen:
                    cursors[qi] += 1
                if cursors[qi] < len(order):
                    i = int(order[cursors[qi]])
                    chosen.append(i)
                    seen.add(i)
    for i in order_all:
        if len(chosen) >= k:
            break
        if i not in seen:
            chosen.append(i)
            seen.add(i)
    pos = {i: p for p, i in enumerate(order_all)}
    chosen.sort(key=lambda i: pos[i])
    return chosen


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


__all__ = [
    "FLOOR_CALIBRATION",
    "SearchHit",
    "default_floor",
    "last_search_status",
    "lexical_coverage",
    "search",
    "set_query_embedder",
    "tokenize",
    "warmup",
]
