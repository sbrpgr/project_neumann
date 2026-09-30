"""지표 정의(손 계산), 부트스트랩 결정성, 사람 대 AI 일치·κ(분산 없으면 undefined)."""

from __future__ import annotations

import pytest

from eval import backtest_metrics as bm


def test_per_plan_scores_missing_slot_not_a():
    assert bm.precision_at_3(["A", "B", "C"]) == pytest.approx(1 / 3)
    assert bm.precision_at_3(["A", "A", None]) == pytest.approx(2 / 3)  # 빈 자리도 분모에 든다
    assert bm.hit_at_3(["B", None, "C"]) == 0.0 and bm.hit_at_3(["C", "C", "A"]) == 1.0
    assert bm.fp_rate(["C", None, "C"]) == pytest.approx(2 / 3)


def test_bootstrap_deterministic_and_brackets_mean():
    xs = [0, 1 / 3, 2 / 3, 1, 1 / 3, 0, 1, 2 / 3]
    ci1 = bm.bootstrap_ci(xs, lambda v: sum(v) / len(v))
    ci2 = bm.bootstrap_ci(xs, lambda v: sum(v) / len(v))
    assert ci1 == ci2
    mean = sum(xs) / len(xs)
    assert ci1[0] < mean < ci1[1]
    assert bm.bootstrap_ci([], lambda v: 0.0) is None
    assert bm.bootstrap_ci([0.5] * 5, lambda v: sum(v) / len(v)) == (0.5, 0.5)


def _g(system, cond, wid, grades, n=3, ev=None):
    return {"system": system, "condition": cond, "work_id": wid, "grades": grades, "n_risks": n,
            "evidence_ok": ev or [False] * 3, "judged": True}


def test_specificity_not_measured_without_shuffle_and_failed_run_counts_zero():
    graded = [_g("neumann", "real", "w1", ["A", "B", "B"]), _g("neumann", "real", "w2", [None, None, None], n=0)]
    m = bm.compute_metrics(graded, n_boot=100)
    ne = m["systems"]["neumann"]
    assert ne["specificity"]["measured"] is False and ne["shuffle"]["measured"] is False
    assert ne["real"]["n"] == 2 and ne["real"]["failed_runs"] == 1
    assert ne["real"]["precision_at_3"]["value"] == pytest.approx(1 / 6, abs=1e-4)  # 실패 논문도 0으로 센다
    assert m["summary"]["neumann"]["specificity"] == "측정 못 함"
    assert m["comparison"] == {}  # 일반 LLM이 없으면 비교하지 않는다


def test_cohen_kappa_hand_computed():
    # 2x2: A/A 20, A/notA 5, notA/A 10, notA/notA 15 (n=50) → po .7, pa .5, pb .6, pe .5 → κ .4
    pairs = [("A", "A")] * 20 + [("A", "notA")] * 5 + [("notA", "A")] * 10 + [("notA", "notA")] * 15
    assert bm.cohen_kappa(pairs, ("A", "notA")) == pytest.approx(0.4)
    assert bm.cohen_kappa([("A", "A")] * 5, ("A", "notA")) is None  # 분산 없음 → undefined


def test_human_agreement_table():
    human = {("e1", "k01"): "A", ("e1", "k02"): "B", ("e1", "k03"): "C", ("e2", "k01"): "A", ("e2", "k09"): "B"}
    ai = {("e1", "k01"): "A", ("e1", "k02"): "C", ("e1", "k03"): "C", ("e2", "k01"): "B", ("e3", "k01"): "A"}
    res = bm.human_agreement(human, ai)
    assert res["n"] == 4 and res["only_human"] == 1 and res["only_ai"] == 1
    assert res["exact_agreement_3class"] == 0.5
    assert res["binary_A_agreement"] == 0.75  # A/A, notA/notA, notA/notA, A/notA
    assert res["prevalence_A_human"] == 0.5 and res["prevalence_A_ai"] == 0.25
    assert res["kappa_binary_A"] == pytest.approx(0.5)  # po .75, pe .5 → .5
    assert res["confusion_human_to_ai"]["B->C"] == 1
