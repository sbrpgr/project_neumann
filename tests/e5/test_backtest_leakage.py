"""누출 회귀(옛 함정 B-10): 자기 논문 id를 주입하면 검색 결과에 자기 논문이 0건이어야 한다.

E2 검색(`neumann.index.search`)이 main에 없으면 fixture 검색(같은 인터페이스: 완전 일치 exclude)으로 검사한다.
E2가 들어오면 마지막 테스트가 실제 `search(..., exclude_work_ids=...)`로 같은 검사를 한다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import pytest

from eval import backtest_leakage as bl
from tests.fixtures.loader import load_fixtures


@dataclass
class Hit:
    work_id: str
    score: float


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def make_fixture_search(works: dict[str, str]):
    """E2 search와 같은 약속: exclude_work_ids는 **색인 work_id 문자열과 완전 일치**로 거른다."""

    def search(queries, k=10, exclude_work_ids=None):
        ex = exclude_work_ids or set()
        q = set().union(*(_tokens(x) for x in queries))
        scored = sorted(((len(q & _tokens(t)) / (len(q) or 1), w) for w, t in works.items()), key=lambda x: (-x[0], x[1]))
        return [Hit(w, s) for s, w in scored if w not in ex and s > 0][:k]

    return search


@pytest.fixture()
def index_env():
    fx = load_fixtures()
    # 색인은 접두어가 붙은 id를 쓴다(실데이터: researcharcade_hf:<native>)
    re_id = {w.work_id: "researcharcade_hf:" + w.work_id.split(":", 1)[1] for w in fx.works}
    works = [{"work_id": re_id[w.work_id], "title": w.title, "native_id": w.work_id.split(":", 1)[1], "url": w.url} for w in fx.works]
    reviews = [{"work_id": re_id[r.work_id], "text": r.text} for r in fx.reviews]
    catalog = bl.IndexCatalog.from_records(works, reviews, "fixture")
    texts = {re_id[w.work_id]: f"{w.title}\n{w.abstract or ''}" for w in fx.works}
    return fx, re_id, catalog, make_fixture_search(texts)


def test_normalize_work_id_prefix_namespace_url():
    k = bl.normalize_work_id
    assert k("researcharcade_hf:tj40W2HAKN") == k("tj40W2HAKN") == k("https://openreview.net/forum?id=tj40W2HAKN")
    assert k("openreview:tj40W2HAKN") == k("  tj40W2HAKN ")
    assert k("researcharcade_hf:AAA") != k("researcharcade_hf:BBB")
    assert bl.normalize_title("MV-CLAM: Multi-View  Molecular") == bl.normalize_title("mv clam multi view molecular")


def test_self_injection_zero_hits_and_naive_filter_fails(index_env):
    """자기 논문 id(접두어 없는 표기)를 주입: 정규화 제외는 0건, 옛 완전 일치 제외는 누출(B-10 재현)."""
    fx, re_id, catalog, search = index_env
    for w in fx.works:
        bare = w.work_id.split(":", 1)[1]  # 표본 쪽 표기: 접두어 없음
        keys = bl.target_keys(bare, title=w.title, review_texts=[r.text for r in fx.reviews if r.work_id == w.work_id])
        q = [f"{w.title} {w.abstract}"]
        before = [h.work_id for h in search(q, k=10)]
        assert re_id[w.work_id] in before[:1], "제외 없이는 자기 논문이 1위로 나와야 검사가 의미 있다"
        naive = [h.work_id for h in search(q, k=10, exclude_work_ids={bare})]
        assert len(bl.self_hits(naive, keys, catalog)) == 1, "완전 일치 제외는 접두어 차이로 작동하지 않는다(B-10)"
        excl = bl.resolve_exclusions([keys], catalog)[bare]["exclude_work_ids"]
        assert excl == [re_id[w.work_id]]
        after = [h.work_id for h in search(q, k=10, exclude_work_ids=set(excl))]
        assert bl.self_hits(after, keys, catalog) == []
        assert len(after) >= 1  # 다른 논문은 그대로 나온다(과잉 제거 아님)


def test_title_and_review_hash_catch_renamed_copies(index_env):
    """id가 전혀 다른 사본(다른 소스·재수집)도 제목 정규화나 심사평 해시로 잡는다."""
    fx, re_id, catalog, _ = index_env
    w = fx.works[0]
    revs = [r.text for r in fx.reviews if r.work_id == w.work_id]
    catalog.works["mirror:ZZZ1"] = {"title": w.title.upper() + " ", "native_id": "ZZZ1", "url": None}  # 제목만 같음
    catalog.works["mirror:ZZZ2"] = {"title": "Totally different", "native_id": "ZZZ2", "url": None}
    catalog.review_hashes["mirror:ZZZ2"] = {bl.review_hash("  " + revs[0].replace(" ", "  ") + "\n")}  # 공백만 다름
    keys = bl.target_keys(w.work_id, title=w.title, review_texts=revs)
    res = bl.resolve_exclusions([keys], catalog)[w.work_id]
    assert set(res["exclude_work_ids"]) == {re_id[w.work_id], "mirror:ZZZ1", "mirror:ZZZ2"}
    assert res["reasons"]["mirror:ZZZ1"] == ["title"] and res["reasons"]["mirror:ZZZ2"] == ["review"]
    assert set(res["reasons"][re_id[w.work_id]]) == {"id", "title", "review"}


def test_evidence_leak_check_detects_target_review_quote(index_env):
    fx, _, _, _ = index_env
    target = fx.works[0].work_id
    own = [r.text for r in fx.reviews if r.work_id == target]
    other = [r.text for r in fx.reviews if r.work_id != target]
    quote_own = own[0][:60]
    assert bl.evidence_leaks([quote_own], own) == [quote_own]
    assert bl.evidence_leaks([other[0][:60]], own) == []


def test_shuffle_exclusion_is_union(index_env):
    fx, re_id, catalog, _ = index_env
    sample = {"list_sha256": "x", "items": [{"work_id": w.work_id, "pos": i} for i, w in enumerate(fx.works[:2], 1)],
              "shuffle_pairs": [{"work_id": fx.works[0].work_id, "plan_work_id": fx.works[1].work_id}]}

    class View:
        works = {w.work_id: w for w in fx.works}

        def reviews_for(self, wid):
            return [r for r in fx.reviews if r.work_id == wid]

    ex = bl.build_exclusions(sample, View(), catalog)
    assert ex["summary"]["targets_found_in_index"] == 2
    assert ex["shuffle"][0]["exclude_work_ids"] == sorted({re_id[fx.works[0].work_id], re_id[fx.works[1].work_id]})


def test_stale_exclusions_detects_ids_not_in_index(index_env):
    """색인이 다시 만들어져 id가 바뀌면 완전 일치 필터가 조용히 무시한다 → 생성 전에 잡는다."""
    fx, re_id, catalog, _ = index_env
    good = re_id[fx.works[0].work_id]
    excl = {"targets": [{"work_id": "t1", "exclude_work_ids": [good]}], "shuffle": []}
    assert bl.stale_exclusions(excl, catalog) == []
    excl["targets"].append({"work_id": "t2", "exclude_work_ids": [fx.works[1].work_id.split(":", 1)[1]]})  # 접두어 없음
    excl["targets"].append({"work_id": "t3", "exclude_work_ids": []})
    stale = bl.stale_exclusions(excl, catalog)
    assert fx.works[1].work_id.split(":", 1)[1] in stale and any("t3" in s for s in stale)


def test_e2_search_self_injection_zero(index_env):
    """E2 검색이 있으면 실제 search()로 같은 회귀를 돈다(어휘 검색만, 임베딩 없음)."""
    search_mod = pytest.importorskip("neumann.index.search")
    store_mod = pytest.importorskip("neumann.index.store")
    fx, re_id, catalog, _ = index_env
    works = [w.model_copy(update={"work_id": re_id[w.work_id]}) for w in fx.works]
    reviews = [r.model_copy(update={"work_id": re_id[r.work_id]}) for r in fx.reviews]
    store = store_mod.IndexStore.from_corpus(works, reviews, embedder=None)
    for w in fx.works:
        bare = w.work_id.split(":", 1)[1]
        keys = bl.target_keys(bare, title=w.title, review_texts=[r.text for r in fx.reviews if r.work_id == w.work_id])
        excl = set(bl.resolve_exclusions([keys], catalog)[bare]["exclude_work_ids"])
        q = [f"{w.title} {w.abstract}"]
        before = search_mod.search(q, k=10, store=store)
        naive = search_mod.search(q, k=10, exclude_work_ids={bare}, store=store)
        after = search_mod.search(q, k=10, exclude_work_ids=excl, store=store)
        assert bl.self_hits([h.work_id for h in before], keys, catalog)
        # E2 search는 완전 일치라 접두어 없는 id는 조용히 무시된다(PM이 E2-L0 검증에서 확인한 함정)
        assert bl.self_hits([h.work_id for h in naive], keys, catalog)
        assert excl == {re_id[w.work_id]}  # 넘기는 값은 색인의 work_id 형식(researcharcade_hf:<id>)
        assert bl.self_hits([h.work_id for h in after], keys, catalog) == []


REAL = os.environ.get("NEUMANN_REAL_DATA_TESTS") == "1"


@pytest.mark.skipif(not REAL, reason="실색인 회귀는 NEUMANN_REAL_DATA_TESTS=1일 때만(공유 데이터 폴더 필요, 수 초~수십 초)")
def test_real_index_self_injection_zero():
    """실색인(data/index)에 표본 30편의 계획서를 넣어 자기 논문 top-10: 제외 전 > 0, 정규화 제외 후 0, 접두어 없는 id는 새어 나옴."""
    search_mod = pytest.importorskip("neumann.index.search")
    from eval.backtest_common import data_dir, eval_dir, read_json, read_jsonl

    sample = read_json(eval_dir() / "backtest_sample.json")
    plans = {r["work_id"]: r["plan_text"] for r in read_jsonl(eval_dir() / "backtest_plans.jsonl")}
    catalog = bl.IndexCatalog.load(data_dir() / "index")
    from eval.backtest_common import load_corpus_view

    excl = bl.build_exclusions(sample, load_corpus_view(), catalog)
    probe = bl.probe_search(sample, plans, excl, catalog, search_mod.search, k=10)
    assert probe["n"] == 30
    assert probe["self_hits_without_exclusion"] > 0
    assert probe["self_hits_naive_bare_id"] > 0
    assert probe["self_hits_with_exclusion"] == 0
    assert all(w.startswith("researcharcade_hf:") for t in excl["targets"] for w in t["exclude_work_ids"])
