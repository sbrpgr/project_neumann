"""SEC-5 A: last_search_status()는 호출 스레드 자신의 마지막 검색 상태다.

동시 요청 두 개가 search()를 겹쳐 돌려도 각자 자기 판정·강등·질의를 읽는다. 겹침은 Barrier로 강제한다
(두 스레드가 모두 검색 중간(BM25 점수 계산)에 들어온 뒤에야 진행). 검색한 적 없는 스레드는 공용 값으로 돌아간다.
"""

from __future__ import annotations

import threading
from typing import Any

from neumann.index import search as search_mod
from neumann.index.store import IndexStore

Q_RELATED = ["ionic conductivity electrolyte graph neural network", "brain tumor segmentation MRI"]
Q_UNRELATED = ["sourdough bread baking recipe"]
FLOOR = 0.3


class _BarrierBM25:
    """BM25 색인 대리자: 첫 scores() 호출에서 Barrier를 기다린다(두 검색이 모두 진행 중일 때만 풀린다)."""

    def __init__(self, inner: Any, barrier: threading.Barrier) -> None:
        self._inner = inner
        self._barrier = barrier
        self._waited = False

    def scores(self, query: str):
        if not self._waited:
            self._waited = True
            self._barrier.wait()
        return self._inner.scores(query)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _run_threads(targets: dict[str, Any], timeout: float = 20.0) -> dict[str, Any]:
    out: dict[str, Any] = {}
    errors: list[BaseException] = []

    def wrap(name, fn):
        def run():
            try:
                out[name] = fn()
            except BaseException as exc:  # noqa: BLE001 — 스레드 예외를 본 스레드로 넘긴다
                errors.append(exc)

        return run

    threads = [threading.Thread(target=wrap(n, f), name=f"sec5-{n}") for n, f in targets.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
    assert not any(t.is_alive() for t in threads), "스레드가 끝나지 않았다(교착)"
    if errors:
        raise errors[0]
    return out


def test_concurrent_searches_each_read_own_status(corpus, fake_embedder):
    works, reviews = corpus
    st_hybrid = IndexStore.from_corpus(works, reviews, embedder=fake_embedder)
    st_lexical = IndexStore.from_corpus(works, reviews, embedder=None)  # 임베딩 없음 → 강등

    # 기준: 겹치지 않게 차례로 돌린 결과(결과가 동시 실행으로 바뀌지 않았는지 비교)
    search_mod.set_query_embedder(fake_embedder)
    try:
        ref_a = search_mod.search(Q_RELATED, k=3, store=st_hybrid, score_floor=FLOOR)
        ref_b = search_mod.search(Q_UNRELATED, k=3, store=st_lexical, score_floor=FLOOR)

        mid = threading.Barrier(2, timeout=10)  # 두 검색이 모두 중간에 들어와야 풀린다
        after = threading.Barrier(2, timeout=10)  # 두 검색이 모두 끝난 뒤에 상태를 읽는다
        st_hybrid.bm25 = _BarrierBM25(st_hybrid.bm25, mid)
        st_lexical.bm25 = _BarrierBM25(st_lexical.bm25, mid)

        def job(queries, store):
            def run():
                hits = search_mod.search(queries, k=3, store=store, score_floor=FLOOR)
                after.wait()
                return hits, search_mod.last_search_status()

            return run

        out = _run_threads({"a": job(Q_RELATED, st_hybrid), "b": job(Q_UNRELATED, st_lexical)})
        # 검색한 적 없는 새 스레드: 공용 값(둘 중 나중에 끝난 쪽)
        glob = _run_threads({"c": search_mod.last_search_status})["c"]
    finally:
        search_mod.set_query_embedder(None)

    (hits_a, st_a), (hits_b, st_b) = out["a"], out["b"]
    assert hits_a == ref_a and hits_b == ref_b  # 검색 결과·점수는 그대로

    assert st_a["backend"] == "hybrid" and st_a["degraded"] is False
    assert st_a["n_queries"] == 2 and [p["query"] for p in st_a["per_query"]] == Q_RELATED
    assert st_a["relevance"]["verdict"] == "related"

    assert st_b["backend"] == "lexical_only" and st_b["degraded"] is True
    assert st_b["n_queries"] == 1 and [p["query"] for p in st_b["per_query"]] == Q_UNRELATED
    assert st_b["relevance"]["verdict"] == "unrelated"

    # 공용 값은 둘 중 하나뿐이다 → 공용 값만 읽었다면 둘 중 한 스레드는 남의 상태를 읽었을 것
    assert glob in (st_a, st_b)
    assert (st_a != glob) or (st_b != glob)


def test_thread_without_search_falls_back_to_global(mem_store):
    """mcp_server 호환: 검색한 적 없는 스레드는 프로세스 공용(마지막 호출) 값을 읽는다."""
    out = _run_threads({"s": lambda: (search_mod.search(Q_UNRELATED, k=2), search_mod.last_search_status())})
    _hits, own = out["s"]
    fresh = _run_threads({"r": search_mod.last_search_status})["r"]
    assert fresh == own and [p["query"] for p in fresh["per_query"]] == Q_UNRELATED


def test_thread_status_survives_later_search_elsewhere(mem_store):
    """한 스레드가 검색한 뒤 다른 스레드가 검색해도, 앞 스레드는 여전히 자기 상태를 읽는다(차례 강제)."""
    first_done = threading.Event()
    second_done = threading.Event()

    def first():
        search_mod.search(Q_RELATED, k=2)
        first_done.set()
        assert second_done.wait(10)
        return search_mod.last_search_status()

    def second():
        assert first_done.wait(10)
        search_mod.search(Q_UNRELATED, k=2, exclude_work_ids={"fake:bat-1"})
        second_done.set()
        return search_mod.last_search_status()

    out = _run_threads({"first": first, "second": second})
    assert [p["query"] for p in out["first"]["per_query"]] == Q_RELATED and out["first"]["n_excluded"] == 0
    assert [p["query"] for p in out["second"]["per_query"]] == Q_UNRELATED and out["second"]["n_excluded"] == 1
    # 공용 값은 나중 스레드 것 → 앞 스레드는 공용 값이 아니라 자기 값을 읽었다
    assert search_mod._STATUS["per_query"][0]["query"] == Q_UNRELATED[0]


class _BrokenBM25:
    """검색 한가운데(BM25 점수 계산)에서 예외를 내는 대리자."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def scores(self, query: str):
        raise RuntimeError("검색 중간 실패(시험)")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def test_failed_search_in_reused_thread_does_not_leave_stale_status(mem_store, corpus, fake_embedder):
    """스레드 풀 스레드 하나를 다시 쓴다: 요청 1 검색 성공 → 요청 2 검색이 상태를 남기기 전에 예외 →
    요청 2의 last_search_status()는 요청 1의 상태가 아니라 미완료 표지다(입력 검사 예외·검색 중간 예외 둘 다)."""
    from concurrent.futures import ThreadPoolExecutor

    works, reviews = corpus
    broken = IndexStore.from_corpus(works, reviews, embedder=fake_embedder)
    broken.bm25 = _BrokenBM25(broken.bm25)

    def ok_request():
        hits = search_mod.search(Q_RELATED, k=2)
        return threading.get_ident(), hits, search_mod.last_search_status()

    def failing_request(kind: str):
        try:
            if kind == "argument":
                search_mod.search(Q_UNRELATED, k=2, fusion="bogus")  # 입력 검사에서 ValueError
            else:
                search_mod.search(Q_UNRELATED, k=2, store=broken)  # 점수 계산 중 RuntimeError
        except (ValueError, RuntimeError) as exc:
            return threading.get_ident(), type(exc).__name__, search_mod.last_search_status()
        raise AssertionError("예외가 나야 한다")

    with ThreadPoolExecutor(max_workers=1) as pool:  # 같은 작업 스레드를 차례로 다시 쓴다
        t1, hits1, st1 = pool.submit(ok_request).result(timeout=20)
        t2, err2, st2 = pool.submit(failing_request, "argument").result(timeout=20)
        t3, hits3, st3 = pool.submit(ok_request).result(timeout=20)
        t4, err4, st4 = pool.submit(failing_request, "mid_search").result(timeout=20)
    assert t1 == t2 == t3 == t4  # 정말 같은 스레드
    assert hits1 and [p["query"] for p in st1["per_query"]] == Q_RELATED and "incomplete" not in st1
    assert err2 == "ValueError" and err4 == "RuntimeError"
    for stale in (st2, st4):
        assert stale != st1 and stale != st3  # 앞 요청 상태가 남지 않는다
        assert stale["incomplete"] is True and stale["backend"] == "unknown"
        assert "per_query" not in stale and "relevance" not in stale and "degraded" not in stale
    assert hits3 == hits1 and st3.get("incomplete") is None  # 다시 성공하면 정상 상태
    # 공용 값은 마지막으로 끝난(성공한) 호출 그대로: 검색한 적 없는 스레드에는 이전 동작 유지
    assert [p["query"] for p in search_mod._STATUS["per_query"]] == Q_RELATED


def test_backend_status_per_request_thread(mem_store):
    """파이프라인 경로(IndexBackend.search → .status())가 동시 요청 사이에 섞이지 않는다."""
    from neumann.analyze.backend import IndexBackend

    after = threading.Barrier(2, timeout=10)

    def request(queries):
        def run():
            be = IndexBackend()
            be.search(queries, k=2)
            after.wait()  # 두 요청의 검색이 모두 끝난 뒤 상태를 읽는다(공용 값이면 한쪽이 틀린다)
            return be.status()

        return run

    out = _run_threads({"a": request(Q_RELATED), "b": request(Q_UNRELATED)})
    assert [p["query"] for p in out["a"]["per_query"]] == Q_RELATED
    assert [p["query"] for p in out["b"]["per_query"]] == Q_UNRELATED
