"""표본 추출(층화·시드 고정·축소 표본·셔플 짝·사람 판정 표본)과 강한 층 판정."""

from __future__ import annotations

import random
from collections import Counter
from types import SimpleNamespace

import pytest

from eval import backtest_sample as bs


def _cands(n_rej: int = 120, n_acc: int = 80) -> list[dict]:
    rng = random.Random(1)
    fields = ["materials_chemistry_molecules", "protein_biology_drug", "physics_pde_climate"]
    out = []
    for i in range(n_rej + n_acc):
        out.append({
            "work_id": f"ns:W{i:04d}",
            "decision": "reject" if i < n_rej else "accept",
            "fields": sorted(set(rng.sample(fields, rng.choice([1, 1, 2])))),
        })
    return out


def test_largest_remainder_matches_population_ratio():
    assert bs.largest_remainder(30, {"reject": 486, "accept": 324}) == {"reject": 18, "accept": 12}
    q = bs.largest_remainder(30, {"reject": 601, "accept": 399})  # 18.03 / 11.97
    assert q == {"reject": 18, "accept": 12} and sum(q.values()) == 30
    with pytest.raises(ValueError):
        bs.largest_remainder(30, {"reject": 10, "accept": 5})


def test_draw_sample_stratified_deterministic_and_prefix_proportional():
    cands = _cands()
    items, quota = bs.draw_sample(cands, 30)
    assert quota == {"reject": 18, "accept": 12}
    assert len(items) == 30 and len({it["work_id"] for it in items}) == 30
    assert bs.strata_counts(items) == {"reject": 18, "accept": 12}
    assert bs.strata_counts(items[:15]) == {"reject": 9, "accept": 6}  # 축소 표본도 같은 비율
    again, _ = bs.draw_sample(list(reversed(cands)), 30)  # 입력 순서와 무관(work_id로 정렬 후 추출)
    assert [x["work_id"] for x in again] == [x["work_id"] for x in items]
    other, _ = bs.draw_sample(cands, 30, seed=7)
    assert [x["work_id"] for x in other] != [x["work_id"] for x in items]


def test_proportional_interleave_every_prefix_close_to_ratio():
    picks = {"reject": [f"r{i}" for i in range(18)], "accept": [f"a{i}" for i in range(12)]}
    order = bs.proportional_interleave(picks)
    for t in range(1, 31):
        r = sum(1 for x in order[:t] if x.startswith("r"))
        assert abs(r - 0.6 * t) < 1.0 + 1e-9


def test_shuffle_pairs_same_field_no_self_and_reduced_closed():
    items, _ = bs.draw_sample(_cands(), 30)
    pairs = bs.shuffle_pairs(items)
    head = {it["work_id"] for it in items[:15]}
    by = {it["work_id"]: it for it in items}
    assert len(pairs) == 30
    for pos, p in enumerate(pairs):
        assert p["work_id"] != p["plan_work_id"]
        if pos < 15:
            assert p["plan_work_id"] in head  # 15편으로 줄여도 짝이 표본 안에 있다
        if p["field_match"]:
            assert set(by[p["work_id"]]["fields"]) & set(by[p["plan_work_id"]]["fields"])
    assert bs.shuffle_pairs(items) == pairs  # 시드 고정


def test_human_sample_ten_from_reduced_head():
    items, _ = bs.draw_sample(_cands(), 30)
    hs = bs.human_sample(items)
    assert len(hs) == 10 and set(hs) <= {it["work_id"] for it in items[:15]}
    assert bs.human_sample(items) == hs


def _work(wid, title, abstract="An abstract."):
    return SimpleNamespace(work_id=wid, native_id=wid.split(":")[1], title=title, url=f"https://x/{wid}", venue="ICLR 2025",
                           abstract=abstract, fields=["protein_biology_drug"], provenance=SimpleNamespace(content_sha256="0" * 64))


def test_selection_strength_matches_e1_rule():
    assert bs.selection_strength("Protein folding with diffusion", {"protein_biology_drug": ["protein*"]}) == "title"
    assert bs.selection_strength("A generic graph model", {"protein_biology_drug": ["protein*", "drug*"]}) == "multi"
    assert bs.selection_strength("A generic graph model", {"protein_biology_drug": ["protein*"]}) == "single"
    # ogbn-proteins는 E1 규칙대로 지우고 본다 → 제목 적중이 아니다
    assert bs.selection_strength("Scaling GNNs on ogbn-proteins", {"protein_biology_drug": ["protein*"]}) == "single"


def test_candidates_eligibility_rules():
    rev = SimpleNamespace(review_id="r", text="t")
    works = {
        "ns:A1": _work("ns:A1", "Protein design"),  # 적격
        "ns:A2": _work("ns:A2", "Generic model"),  # 약한 층(키워드 1개, 제목 아님)
        "ns:A3": _work("ns:A3", "Protein thing"),  # 심사평 2건
        "ns:A4": _work("ns:A4", "Protein stuff"),  # 결정 unknown
        "ns:A5": _work("ns:A5", "Protein none", abstract=""),  # 초록 없음
    }
    sel = {w: {"keywords": {"protein_biology_drug": ["protein*"]}} for w in works}
    dec = lambda o: SimpleNamespace(outcome=SimpleNamespace(value=o))  # noqa: E731
    view = SimpleNamespace(
        works=works, selection=sel,
        decisions={"ns:A1": dec("reject"), "ns:A2": dec("reject"), "ns:A3": dec("accept_poster"), "ns:A4": dec("unknown"), "ns:A5": dec("reject")},
        reviews_for=lambda w: [rev] * (2 if w == "ns:A3" else 3),
    )
    cands, excluded = bs.candidates_from_corpus(view)
    assert [c["work_id"] for c in cands] == ["ns:A1"]
    assert cands[0]["selection_strength"] == "title" and cands[0]["decision"] == "reject"
    assert excluded == Counter({"weak_selection_single": 1, "official_reviews_lt_3": 1, "decision_not_binary": 1, "no_abstract": 1})


def test_save_sample_refuses_different_list(tmp_path):
    out = tmp_path / "s.json"
    bs.save_sample({"list_sha256": "aaa", "items": []}, out)
    bs.save_sample({"list_sha256": "aaa", "items": []}, out)  # 같은 목록이면 덮어써도 된다
    with pytest.raises(SystemExit):
        bs.save_sample({"list_sha256": "bbb", "items": []}, out)
    bs.save_sample({"list_sha256": "bbb", "items": []}, out, force=True)
