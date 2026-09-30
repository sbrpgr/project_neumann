from __future__ import annotations

import pytest

from neumann.index import search as search_mod
from neumann.index import store as store_mod
from neumann.index.search import SearchHit, last_search_status, search
from neumann.index.store import IndexNotBuilt, IndexStore, get_excerpts, get_reviews, get_work


def test_store_api(mem_store, corpus):
    works, reviews = corpus
    w = get_work("fake:bat-1")
    assert w.title.startswith("Graph neural network")
    revs = get_reviews("fake:bat-1")
    assert [r.review_id for r in revs] == ["rev-bat-1-0", "rev-bat-1-1"]
    exs = get_excerpts("fake:bat-1")
    assert len(exs) >= 8
    by_id = {r.review_id: r for r in reviews}
    for ex in exs:
        assert ex.verify_against(by_id[ex.source_id].text)
    # 번호 순서: 심사평 순서 → 원문 위치
    keys = [(ex.source_id, ex.start) for ex in exs]
    assert keys == sorted(keys)
    assert get_excerpts("fake:pro-4") == []  # 심사평 없는 논문
    assert get_reviews("nope") == []
    with pytest.raises(KeyError):
        get_work("nope")
    ex0 = exs[0]
    assert store_mod.get_excerpt(ex0.excerpt_id) == ex0
    assert store_mod.get_excerpt("ex_0000") is None
    assert mem_store.verify_offsets()["failed"] == 0


def test_rule_tags_available(mem_store):
    tags = store_mod.get_rule_tags("fake:bat-1")
    ids = {ex.excerpt_id for ex in get_excerpts("fake:bat-1")}
    assert tags and all(t.excerpt_id in ids for t in tags)


def test_save_load_roundtrip(tmp_path, corpus, fake_embedder):
    works, reviews = corpus
    st = IndexStore.from_corpus(works, reviews, embedder=fake_embedder)
    manifest = st.save(tmp_path, {"note": "test"})
    assert manifest["index_bytes"] > 0 and (tmp_path / "manifest.json").is_file()
    again = IndexStore.load(tmp_path)
    assert again.work_order == st.work_order
    for wid in st.work_order:
        assert again.get_excerpts(wid) == st.get_excerpts(wid)
        assert again.get_rule_tags(wid) == st.get_rule_tags(wid)
        assert again.get_work(wid) == st.get_work(wid)
    assert again.verify_offsets() == {"checked": st.n_excerpts(), "passed": st.n_excerpts(), "failed": 0}
    assert again.embeddings.shape == st.embeddings.shape
    q = ["ionic conductivity electrolyte"]
    search_mod.set_query_embedder(fake_embedder)
    try:
        a = search(q, store=st)
        b = search(q, store=again)
    finally:
        search_mod.set_query_embedder(None)
    assert [h.work_id for h in a] == [h.work_id for h in b]


def test_tampered_disk_excerpt_fails_verification(tmp_path, corpus):
    works, reviews = corpus
    IndexStore.from_corpus(works, reviews).save(tmp_path)
    p = tmp_path / "excerpts.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines()
    import json

    row = json.loads(lines[1])
    row["start"] += 1  # 오프셋만 한 칸 밀린 조작
    row["end"] += 1
    lines[1] = json.dumps(row, ensure_ascii=False)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = IndexStore.load(tmp_path).verify_offsets()
    assert res["failed"] == 1


def test_missing_index_raises(tmp_path):
    with pytest.raises(IndexNotBuilt):
        IndexStore.load(tmp_path / "none")


def test_search_hybrid_contract(mem_store):
    hits = search(["graph neural network for ionic conductivity of electrolytes"], k=3)
    assert 1 <= len(hits) <= 3
    assert all(isinstance(h, SearchHit) for h in hits)
    assert hits[0].work_id == "fake:bat-1"
    for h in hits:
        assert 0.0 <= h.score <= 1.0 and 0.0 <= h.dense <= 1.0 and 0.0 <= h.lexical <= 1.0
        assert h.matched_query == "graph neural network for ionic conductivity of electrolytes"
        assert h.score == pytest.approx(0.6 * h.dense + 0.4 * h.lexical, abs=1e-5)
    assert [h.score for h in hits] == sorted([h.score for h in hits], reverse=True)
    st = last_search_status()
    assert st["backend"] == "hybrid" and st["degraded"] is False


def test_search_multi_query_matched_query(mem_store):
    qs = ["brain tumor segmentation MRI", "protein backbone diffusion"]
    hits = {h.work_id: h for h in search(qs, k=4)}
    assert hits["fake:med-3"].matched_query == qs[0]
    assert hits["fake:pro-4"].matched_query == qs[1]


def test_search_korean_query_uses_dense(mem_store):
    hits = search(["배터리 전해액 이온전도도 예측 그래프 신경망"], k=2)
    assert hits[0].work_id == "fake:bat-1"
    assert hits[0].lexical == 0.0 and hits[0].dense > 0.0


def test_search_exclude_floor_k_and_determinism(mem_store):
    q = ["graph network molecular property"]
    all_hits = search(q, k=10)
    assert len(all_hits) == 4  # 하한 0.0 기본: 다 나온다
    ex = search(q, k=10, exclude_work_ids={all_hits[0].work_id})
    assert all_hits[0].work_id not in {h.work_id for h in ex} and len(ex) == 3
    assert last_search_status()["n_excluded"] == 1
    hi = search(q, k=10, score_floor=0.99)
    assert hi == []
    assert search(q, k=10) == all_hits  # 결정적
    assert search([], k=5) == [] and search(["  "], k=5) == [] and search(q, k=0) == []


def test_search_degrades_to_lexical_and_says_so(corpus):
    works, reviews = corpus
    st = IndexStore.from_corpus(works, reviews, embedder=None)  # 임베딩 없는 색인
    hits = search(["ionic conductivity electrolyte"], k=2, store=st)
    assert hits and hits[0].work_id == "fake:bat-1"
    assert all(h.dense == 0.0 for h in hits)
    status = last_search_status()
    assert status["backend"] == "lexical_only" and status["degraded"] is True and status["reason"]


def test_search_dim_mismatch_degrades(mem_store):
    class Other:
        model_id = "fake-embedder"
        dim = 8
        device = "cpu"

        def encode(self, texts):  # pragma: no cover - 불리면 안 된다
            raise AssertionError

    search_mod.set_query_embedder(Other())
    hits = search(["ionic conductivity"], k=1)
    assert hits and last_search_status()["degraded"] is True
