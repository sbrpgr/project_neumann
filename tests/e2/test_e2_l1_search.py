"""E2-L1 검색 보정: 질의 결합(RRF·상위 할당), 축별 가중치, 점수 하한·관련 없음 판정, 한국어 적응 alpha.

가짜 코퍼스·가짜 임베더로 돈다(모델을 읽지 않는다). 실측 수치는 scripts/build_index_calibrate.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from neumann.index import search as search_mod
from neumann.index.queries import normalize_axis, plan_axis_queries
from neumann.index.search import (
    FLOOR_CALIBRATION,
    default_floor,
    last_search_status,
    lexical_coverage,
    search,
)
from neumann.index.settings import IndexSettings
from neumann.index.store import IndexStore
from neumann.models import Provenance, Work, sha256_text

PLAN = Path(__file__).resolve().parents[1] / "fixtures/plans/plan.md"


def _work(wid: str, title: str, abstract: str) -> Work:
    url = f"https://example.org/fake-venue/forum?id={wid}"
    pv = Provenance(source="fixture", source_url=url, accessed_at=datetime(2026, 9, 30, 9, 0, tzinfo=UTC),
                    content_sha256=sha256_text(title + abstract))
    return Work(work_id=f"fake:{wid}", title=title, abstract=abstract, url=url, provenance=pv)


@pytest.fixture
def mono_store(fake_embedder):
    """단백질 논문 8편(질의 A와 낱말이 똑같다) + 배터리 논문 3편(질의 B와 일부만 겹친다)."""
    works = [
        _work(f"pro{i}", f"Protein language model study {i}", "protein language model protein language model "
              f"pretraining on protein sequences, variant {i}.")
        for i in range(8)
    ] + [
        _work(f"bat{i}", f"Electrolyte screening {i}", f"battery electrolyte conductivity measurements, cell {i}.")
        for i in range(3)
    ]
    st = IndexStore.from_corpus(works, [], embedder=fake_embedder)
    search_mod.set_query_embedder(fake_embedder)
    yield st
    search_mod.set_query_embedder(None)


QA = "protein language model"
FL = 0.1  # 실제처럼 하한을 둔다(하한 0이면 관련도 0.05짜리 쌍도 순위 융합에 표를 던진다)
QB = "battery electrolyte conductivity prediction with a surrogate and ablation study"


def _n_bat(hits) -> int:
    return sum(h.work_id.startswith("fake:bat") for h in hits)


def test_max_fusion_lets_one_query_monopolize(mono_store):
    """전제 확인: L0 최댓값 결합은 절대 점수가 높은 질의가 상위 k를 다 가져간다(E2-L0 검증 관찰 D)."""
    hits = search([QA, QB], k=6, store=mono_store, fusion="max", per_query_min=0, score_floor=FL)
    assert len(hits) == 6 and _n_bat(hits) == 0
    assert all(h.matched_query == QA for h in hits)


def test_rrf_interleaves_queries(mono_store):
    hits = search([QA, QB], k=6, store=mono_store, fusion="rrf", per_query_min=0, score_floor=FL)
    assert _n_bat(hits) == 3  # 순위 융합: 질의마다 1위, 2위 … 가 번갈아 온다
    assert {h.matched_query for h in hits} == {QA, QB}
    assert [h.fused for h in hits] == sorted([h.fused for h in hits], reverse=True)
    st = last_search_status()
    assert st["fusion"] == "rrf" and st["rrf_k"] == 60.0
    assert {q["query"]: q["n_best_match"] for q in st["per_query"]} == {QA: 3, QB: 3}
    assert {q["query"]: q["n_ranked_in_results"] for q in st["per_query"]} == {QA: 3, QB: 3}


def test_per_query_min_reserves_slots_even_with_max(mono_store):
    hits = search([QA, QB], k=6, store=mono_store, fusion="max", per_query_min=1, score_floor=FL)
    assert _n_bat(hits) == 1  # QB의 1위가 할당 몫으로 들어온다
    hits2 = search([QA, QB], k=8, store=mono_store, fusion="max", per_query_min=2, score_floor=FL)  # k=8 → 몫 4
    assert _n_bat(hits2) == 2
    # 할당 몫은 k의 절반까지: 질의 2개 × 5편이어도 k=4면 2편만 할당(가중치 같으면 앞 질의부터 번갈아)
    hits3 = search([QA, QB], k=4, store=mono_store, fusion="max", per_query_min=5, score_floor=FL)
    assert _n_bat(hits3) == 1 and len(hits3) == 4  # 몫 2 = 질의마다 1편


def test_axis_weights_zero_weight_axis_does_not_pull(mono_store):
    kw = {"store": mono_store, "fusion": "rrf", "per_query_min": 1, "k": 6, "score_floor": FL}
    hits = search([QA, QB], axes=["method", "evaluation"], axis_weights={"evaluation": 0.0}, **kw)
    assert _n_bat(hits) == 0  # 가중치 0인 축은 순위에도 할당에도 기여하지 않는다
    hits = search([QA, QB], axes=["method", "evaluation"], axis_weights={"evaluation": 1.0}, **kw)
    assert _n_bat(hits) == 3
    for h in hits:
        assert set(h.axis_scores) <= {"method", "evaluation"} and h.axis_scores
        assert h.score == pytest.approx(max(h.axis_scores.values()), abs=1e-6)
    st = last_search_status()
    assert [q["axis"] for q in st["per_query"]] == ["method", "evaluation"]


def test_axis_argument_validation(mono_store):
    with pytest.raises(ValueError):
        search([QA, QB], axes=["method"], store=mono_store)
    with pytest.raises(ValueError):
        search([QA], store=mono_store, fusion="sum")
    hits = search([QA], axes=["방법론?"], store=mono_store, k=2)
    assert hits and last_search_status()["unknown_axes"] == ["방법론?"]
    assert search([QA], store=mono_store, k=3)[0].axis_scores == {}  # axes 없으면 비움


def test_axis_aliases():
    assert normalize_axis("Methods") == "method" and normalize_axis("데이터") == "data"
    assert normalize_axis("eval") == "evaluation" and normalize_axis(None) == "topic"
    assert normalize_axis("nonsense") is None


def test_floor_calibration_is_model_specific(mem_store):
    assert default_floor("bge-m3") == (FLOOR_CALIBRATION["bge-m3"]["floor"], "calibrated:bge-m3")
    assert default_floor("fake-embedder") == (0.0, "uncalibrated:fake-embedder")
    hits = search(["graph network molecular property"], k=10)
    st = last_search_status()
    assert len(hits) == 4 and st["score_floor"] == 0.0 and st["relevance"]["verdict"] == "unknown"


def test_calibrated_floor_rejects_unrelated_with_reason(mem_store, monkeypatch):
    monkeypatch.setitem(FLOOR_CALIBRATION, "fake-embedder", {"floor": 0.5, "basis": "테스트 보정"})
    hits = search(["tomato egg stir fry recipe with sugar"], k=10)
    st = last_search_status()
    assert hits == []
    rel = st["relevance"]
    assert rel["verdict"] == "unrelated" and rel["floor"] == 0.5 and rel["basis"] == "테스트 보정"
    assert rel["top_relevance"] < 0.5 and rel["margin"] < 0 and rel["n_above_floor"] == 0
    assert st["floor_source"] == "calibrated:fake-embedder" and st["floor_on"] == "max(dense, score)"
    hits = search(["graph neural network for ionic conductivity of electrolytes"], k=10)
    assert hits and last_search_status()["relevance"]["verdict"] == "related"
    assert all(max(h.dense, h.score) >= 0.5 for h in hits)


def test_floor_gate_is_max_of_dense_and_score(mem_store):
    """BM25는 근거를 더할 수만 있다: 결합 점수가 하한 밑이어도 dense가 넘으면 남는다."""
    q = ["종양 분할"]  # 어휘 0, adaptive를 끄면 score = 0.6·dense < dense
    base = search(q, k=10, score_floor=0.0, adaptive_alpha=False)
    h = next(x for x in base if x.dense > x.score + 0.02)
    fl = (h.dense + h.score) / 2
    kept = {x.work_id for x in search(q, k=10, score_floor=fl, adaptive_alpha=False)}
    assert h.work_id in kept
    assert all(max(x.dense, x.score) >= fl for x in base if x.work_id in kept)
    assert all(x.work_id not in kept for x in base if max(x.dense, x.score) < fl)


def test_adaptive_alpha_korean_query_scores_as_dense(mem_store):
    ko = ["배터리 전해액 이온전도도 예측 그래프 신경망"]
    h = search(ko, k=1)[0]
    assert h.lexical == 0.0 and h.score == pytest.approx(h.dense, abs=1e-6)
    assert last_search_status()["per_query"][0]["alpha_eff"] == pytest.approx(1.0)
    h_off = search(ko, k=1, adaptive_alpha=False)[0]
    assert h_off.score == pytest.approx(0.6 * h_off.dense, abs=1e-6)  # L0 방식: 한국어는 0.6배로 깎였다
    en = search(["graph neural network for ionic conductivity of electrolytes"], k=2)
    for x in en:  # 영어(어휘 적용률 1)는 L0와 같은 식
        assert x.score == pytest.approx(0.6 * x.dense + 0.4 * x.lexical, abs=1e-5)


def test_lexical_coverage(mem_store):
    bm = mem_store.bm25
    assert lexical_coverage(bm, "배터리 전해액 이온전도도") == 0.0
    assert lexical_coverage(bm, "ionic conductivity electrolyte") == pytest.approx(1.0)
    mixed = lexical_coverage(bm, "전해액 ionic conductivity 예측")
    assert 0.0 < mixed < 1.0
    assert lexical_coverage(bm, "") == 0.0


def test_legacy_settings_reproduce_l0_max_formula(mem_store):
    qs = ["brain tumor segmentation MRI", "protein backbone diffusion"]
    hits = search(qs, k=4, fusion="max", adaptive_alpha=False, score_floor=0.0, per_query_min=0)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)  # L0: 최댓값 점수 내림차순
    for h in hits:
        per_q = [search([q], k=4, adaptive_alpha=False, score_floor=0.0) for q in qs]
        best = max(x.score for hs in per_q for x in hs if x.work_id == h.work_id)
        assert h.score == pytest.approx(best, abs=1e-6)


def test_unmatched_excludes_reported(mem_store):
    hits = search(["ionic conductivity electrolyte"], k=4, exclude_work_ids={"bat-1", "fake:mol-2"})
    st = last_search_status()
    assert "fake:bat-1" in {h.work_id for h in hits}  # 접두어 없는 id는 제외되지 않는다(완전 일치)
    assert "fake:mol-2" not in {h.work_id for h in hits}
    assert st["n_excluded"] == 1 and st["n_unmatched_excludes"] == 1 and st["unmatched_excludes"] == ["bat-1"]


def test_search_positional_signature_unchanged(mem_store):
    """E3·E5·MCP 호출 모양: search(queries, k, exclude_work_ids) 위치 인자 그대로."""
    hits = search(["graph network molecular property"], 2, {"fake:mol-2"})
    assert len(hits) == 2 and all(h.work_id != "fake:mol-2" for h in hits)
    d = hits[0].model_dump()
    assert {"work_id", "score", "dense", "lexical", "matched_query"} <= set(d)


def test_plan_axis_queries_from_fixture():
    text = PLAN.read_text(encoding="utf-8")
    qs = plan_axis_queries(text)
    assert qs == plan_axis_queries(text)  # 결정적
    axes = [a for _, a in qs]
    assert axes == ["topic", "topic", "method", "data", "evaluation"]
    assert qs[0][0] == text.strip()
    assert qs[1][0].startswith("연구계획서 (예시)") and "리튬이온" in qs[1][0]
    assert "GNN" in qs[2][0] and "12,000" in qs[3][0] and "R2" in qs[4][0]
    assert all("기대 성과" not in q for q, _ in qs[1:])  # 축이 아닌 절은 버린다
    assert plan_axis_queries("제목 없는 짧은 글입니다") == [("제목 없는 짧은 글입니다", "topic")]
    assert plan_axis_queries("") == []


def test_axis_weight_setting_parse():
    s = IndexSettings(NEUMANN_SEARCH_AXIS_WEIGHTS="method=2, evaluation=0.25")
    assert s.axis_weights() == {"topic": 1.0, "method": 2.0, "data": 1.0, "evaluation": 0.25}
    assert IndexSettings().axis_weights()["evaluation"] == 0.5
    with pytest.raises(ValueError):
        IndexSettings(NEUMANN_SEARCH_AXIS_WEIGHTS="method:2").axis_weights()
    assert IndexSettings().search_fusion == "rrf" and IndexSettings().search_score_floor is None


def test_degraded_lexical_only_has_no_default_floor(corpus):
    works, reviews = corpus
    st = IndexStore.from_corpus(works, reviews, embedder=None)
    hits = search(["ionic conductivity electrolyte", "protein backbone"], k=4, store=st)
    status = last_search_status()
    assert hits and status["degraded"] is True and status["score_floor"] == 0.0
    assert status["floor_source"] == "lexical_only:uncalibrated" and status["relevance"]["verdict"] == "unknown"
