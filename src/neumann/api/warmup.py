"""서버 검색 예열. 제품 파이프라인·LLM·결과 캐시는 사용하지 않는다."""

from __future__ import annotations

from typing import Any

DUMMY_QUERY = "research methodology evaluation reproducibility"


def warm_search() -> dict[str, Any]:
    # 실제 요청과 같은 프로세스 공용 캐시를 채운다. 원본·색인에는 쓰지 않는다.
    from neumann.index.embed import get_embedder
    from neumann.index.search import last_search_status, search
    from neumann.index.store import get_store

    store = get_store()  # BM25·dense 색인 로드
    if not store.work_order:
        raise RuntimeError("empty index")
    get_embedder()  # bge-m3 로드; 실패를 어휘 검색 성공으로 숨기지 않는다
    search([DUMMY_QUERY], k=1, store=store)  # 첫 encode·BM25·순위 융합까지 실행
    status = last_search_status()
    if status.get("backend") != "hybrid" or status.get("degraded"):
        raise RuntimeError("hybrid search unavailable")
    return {"backend": "hybrid", "n_works": len(store.work_order)}
