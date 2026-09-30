"""Macro-F1 채점기 테스트: 손 계산 예제, 완벽 1.0, 전부 오답 0.0, 빈 예측, 형식 오류."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import macro_f1 as mf

F = frozenset


def test_hand_computed_example():
    # 손 계산:
    #   R1: TP1 FP0 FN0 → F1 1
    #   R2: TP1 FP0 FN1 → P1 R.5 F1 2/3
    #   R6: TP0 FP1 FN1 → F1 0
    #   R3: FP1, support 0 → Macro 제외, Micro에는 FP로 들어감
    #   Macro = (1 + 2/3 + 0)/3 = 5/9 ; Micro: TP2 FP2 FN2 → 0.5
    gold = [F({"R1", "R2"}), F({"R2"}), F(), F({"R6"})]
    pred = [F({"R1"}), F({"R2", "R6"}), F({"R3"}), F()]
    res = mf.multilabel_scores(gold, pred)
    assert res["scored_classes"] == ["R1", "R2", "R6"]
    assert res["excluded_classes"] == ["R3", "R4", "R5", "R7", "R8", "R9"]
    assert res["per_class"]["R1"]["f1"] == pytest.approx(1.0)
    assert res["per_class"]["R2"]["precision"] == pytest.approx(1.0)
    assert res["per_class"]["R2"]["recall"] == pytest.approx(0.5)
    assert res["per_class"]["R2"]["f1"] == pytest.approx(2 / 3)
    assert res["per_class"]["R6"]["f1"] == 0.0
    assert res["per_class"]["R3"] == {
        "support": 0, "tp": 0, "fp": 1, "fn": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0, "scored": False,
    }
    assert res["macro_f1"] == pytest.approx(5 / 9)
    assert (res["TP"], res["FP"], res["FN"]) == (2, 2, 2)
    assert res["micro_f1"] == pytest.approx(0.5)
    assert res["n"] == 4


def test_perfect_prediction_is_one():
    gold = [F({"R1", "R2"}), F({"R5"}), F(), F({"R6", "R7"})]
    res = mf.multilabel_scores(gold, list(gold))
    assert res["macro_f1"] == 1.0 and res["micro_f1"] == 1.0
    ci = mf.bootstrap_ci(gold, list(gold), mf._macro, n=200)
    assert ci["low"] == 1.0 and ci["high"] == 1.0


def test_all_wrong_is_zero():
    gold = [F({"R1"}), F({"R2"}), F({"R5"})]
    pred = [F({"R2"}), F({"R1"}), F({"R6"})]
    res = mf.multilabel_scores(gold, pred)
    assert res["macro_f1"] == 0.0 and res["micro_f1"] == 0.0


def test_empty_predictions():
    gold = [F({"R1"}), F({"R2"}), F()]
    res = mf.multilabel_scores(gold, [F(), F(), F()])
    # 분모 0 → P=0, F1=0. 골드에 있는 R1·R2는 여전히 채점 대상
    assert res["scored_classes"] == ["R1", "R2"]
    assert res["macro_f1"] == 0.0 and res["micro_f1"] == 0.0
    assert res["per_class"]["R1"]["precision"] == 0.0


def test_no_risk_unit_counts_false_positives():
    # no_risk 단위를 버리지 않는다: 거기서 낸 R1은 FP
    gold = [F({"R1"}), F()]
    res = mf.multilabel_scores(gold, [F({"R1"}), F({"R1"})])
    assert res["per_class"]["R1"]["fp"] == 1
    assert res["per_class"]["R1"]["precision"] == 0.5


def test_gold_without_any_label_is_undefined_not_zero():
    res = mf.multilabel_scores([F(), F()], [F(), F({"R2"})])
    assert res["scored_classes"] == [] and res["macro_f1"] is None


def test_bootstrap_is_seeded_and_brackets_estimate():
    gold = [F({"R1", "R2"}), F({"R2"}), F(), F({"R6"}), F({"R1"}), F({"R2", "R6"})] * 5
    pred = [F({"R1"}), F({"R2", "R6"}), F({"R3"}), F(), F({"R1"}), F({"R2"})] * 5
    a = mf.bootstrap_ci(gold, pred, mf._macro, n=300, seed=7)
    b = mf.bootstrap_ci(gold, pred, mf._macro, n=300, seed=7)
    c = mf.bootstrap_ci(gold, pred, mf._macro, n=300, seed=8)
    assert a == b and a != c
    point = mf.multilabel_scores(gold, pred)["macro_f1"]
    assert a["low"] <= point <= a["high"] and a["low"] < a["high"]
    assert a["n_defined"] == 300


def _write(path: Path, rows) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_score_missing_extra_r0_and_generators(tmp_path):
    gold = mf.load_gold(_write(tmp_path / "g.jsonl", [
        {"review_id": "a", "risk_codes": ["R1", "R2"]},
        {"review_id": "b", "risk_codes": ["R2"]},
        {"review_id": "c", "risk_codes": []},
        {"review_id": "d", "risk_codes": ["R6"]},
    ]))
    preds = mf.load_predictions(_write(tmp_path / "p.jsonl", [
        {"review_id": "a", "risk_codes": ["R1", "R0"], "generator": "astra"},
        {"review_id": "b", "risk_codes": ["R2", "R6"], "generator": "rule", "status": "degraded"},
        {"review_id": "c", "risk_codes": ["R3"], "generator": "astra"},
        {"review_id": "zz", "risk_codes": ["R1"], "generator": "astra"},
    ]))
    res = mf.score(gold, preds, n_boot=100)
    # d는 예측이 없어 빈 집합으로 채점 → 손 계산 예제와 같다
    assert res["macro_f1"] == pytest.approx(5 / 9)
    assert res["micro_f1"] == pytest.approx(0.5)
    p = res["predictions"]
    assert p["missing"] == 1 and p["missing_ids"] == ["d"]
    assert p["extra_ignored"] == 1
    assert p["dropped_r0_labels"] == 1
    assert p["generator_counts"] == {"astra": 2, "rule": 1}
    assert res["excluded_classes"] == ["R3", "R4", "R5", "R7", "R8", "R9"]
    assert res["gold_no_risk_units"] == 1


@pytest.mark.parametrize(
    "row, msg",
    [
        ({"review_id": "a", "risk_codes": ["R10"], "generator": "astra"}, "허용되지 않는 코드"),
        ({"review_id": "a", "risk_codes": ["R2.3"], "generator": "astra"}, "허용되지 않는 코드"),
        ({"review_id": "a", "risk_codes": "R1", "generator": "astra"}, "문자열 목록"),
        ({"review_id": "a", "risk_codes": ["R1"], "generator": "gpt"}, "generator"),
        ({"review_id": "a", "generator": "astra"}, "risk_codes가 없다"),
        ({"risk_codes": ["R1"], "generator": "astra"}, "review_id"),
    ],
)
def test_prediction_format_errors(tmp_path, row, msg):
    with pytest.raises(mf.PredictionError, match=msg):
        mf.load_predictions(_write(tmp_path / "p.jsonl", [row]))


def test_duplicate_prediction_is_error(tmp_path):
    rows = [{"review_id": "a", "risk_codes": [], "generator": "mock"}] * 2
    with pytest.raises(mf.PredictionError, match="중복"):
        mf.load_predictions(_write(tmp_path / "p.jsonl", rows))


def test_gold_rejects_r0(tmp_path):
    with pytest.raises(mf.PredictionError, match="허용되지 않는 코드"):
        mf.load_gold(_write(tmp_path / "g.jsonl", [{"review_id": "a", "risk_codes": ["R0"]}]))


def test_cli_end_to_end(tmp_path, capsys):
    g = _write(tmp_path / "g.jsonl", [
        {"review_id": "a", "risk_codes": ["R1", "R2"]},
        {"review_id": "b", "risk_codes": ["R2"]},
        {"review_id": "c", "risk_codes": []},
        {"review_id": "d", "risk_codes": ["R6"]},
    ])
    p = _write(tmp_path / "p.jsonl", [
        {"review_id": "a", "risk_codes": ["R1"], "generator": "mock"},
        {"review_id": "b", "risk_codes": ["R2", "R6"], "generator": "mock"},
        {"review_id": "c", "risk_codes": ["R3"], "generator": "mock"},
        {"review_id": "d", "risk_codes": [], "generator": "mock"},
    ])
    out = tmp_path / "out" / "score.json"
    assert mf.main(["--pred", str(p), "--gold", str(g), "--out", str(out), "--n-boot", "50"]) == 0
    res = json.loads(out.read_text(encoding="utf-8"))
    assert res["macro_f1"] == round(5 / 9, 4) and res["micro_f1"] == 0.5
    assert res["n"] == 4 and res["excluded_classes"] == ["R3", "R4", "R5", "R7", "R8", "R9"]
    assert res["macro_f1_ci95"]["n_resamples"] == 50 and res["macro_f1_ci95"]["seed"] == mf.SEED
    assert len(res["gold_sha256"]) == 64 and len(res["pred_sha256"]) == 64
    assert res["reference_lines"]["human_upper_bound_consensus_gold"]["macro_f1"] == 0.725
    assert "Macro-F1 0.5556" in capsys.readouterr().out


def test_cli_bad_file_exit_code(tmp_path, capsys):
    g = _write(tmp_path / "g.jsonl", [{"review_id": "a", "risk_codes": ["R1"]}])
    p = _write(tmp_path / "p.jsonl", [{"review_id": "a", "risk_codes": ["X"], "generator": "mock"}])
    assert mf.main(["--pred", str(p), "--gold", str(g), "--out", str(tmp_path / "o.json")]) == 2
    assert "오류" in capsys.readouterr().err


def test_defaults_are_prefixed():
    # 사전 고정값(04_평가_명세 §0.4·§2.1): 2,000회, 시드 고정, 95%
    assert mf.N_BOOT == 2000 and mf.SEED == 20260930 and mf.ALPHA == 0.05
