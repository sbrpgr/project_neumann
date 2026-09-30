"""판정 예행 도구: 합성 Neumann 위험 묶음, 가짜 판정 답(예행 폴더에만, 덮지 않음), 공유 data/eval 보호."""

from __future__ import annotations

import json

import pytest

from eval import judge_rehearsal as rh
from eval import judge_run as jr
from eval.backtest_metrics import compute_metrics
from eval.backtest_riskset import validate_riskset
from eval.judge_envelope import blind_violations
from tests.e5.test_judge_n5 import FIRST5, _build, _inputs, _rows


def test_synth_neumann_rows_are_valid_and_marked():
    _, plans, _ = _inputs()
    syn = rh.synth_neumann(FIRST5, plans, degraded=1)
    assert len(syn) == 5 and all(validate_riskset(r) == [] for r in syn)
    assert [r["status"] for r in syn] == ["ok"] * 4 + ["degraded"]
    assert {r["generator"] for r in syn} == {"synthetic"} and {r["model"] for r in syn} == {rh.SYNTH_MODEL}
    assert all("예행" in r["notes"][0] for r in syn)
    assert all([x["evidence_ok"] for x in r["risks"]] == [True, True, False] for r in syn)


def test_fake_answers_full_path_and_guards(tmp_path):
    _, plans, _ = _inputs()
    syn = rh.synth_neumann(FIRST5, plans, degraded=1)
    base = [r for r in _rows(with_shuffle=False, with_extra_work=False) if r["system"] == "baseline_llm"]
    for r in base:
        r["generator"] = "mock"
    P, _ = _build(tmp_path, syn + base)
    envs = jr.load_envelopes(tmp_path, "judge_n5")
    assert all(blind_violations(e) == [] for e in envs.values())
    key = json.loads(P["key"].read_text(encoding="utf-8"))
    assert rh.fake_answers(P, envs, key) == 15
    good, report = jr.load_answers(envs, P)
    assert report["complete"] and not report["invalid"]
    assert {a["judge_model"] for j in good.values() for a in j.values()} == {rh.FAKE_JUDGE_MODEL}
    with pytest.raises(FileExistsError):
        rh.fake_answers(P, envs, key)  # 덮지 않는다
    agg = jr.aggregate(envs, key, good)
    vp = compute_metrics(agg["graded"], n_boot=50)["systems"]["neumann"]["real"]["vote_patterns"]
    assert sum(vp.values()) == 15 and vp["split_2_1"] > 0  # 판정자끼리 다른 답이 섞여 있다
    # 실제 생성(astra·rule)이 든 판정 폴더에는 가짜 답을 쓰지 않는다
    P2, _ = _build(tmp_path / "real")
    key2 = json.loads(P2["key"].read_text(encoding="utf-8"))
    with pytest.raises(PermissionError):
        rh.fake_answers(P2, jr.load_envelopes(tmp_path / "real", "judge_n5"), key2)
    assert not P2["answers"].exists()


def test_synth_cli_refuses_shared_eval_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUMANN_DATA_DIR", str(tmp_path))
    (tmp_path / "eval").mkdir()
    assert rh.main(["synth-neumann", "--out", str(tmp_path / "eval" / "riskset_neumann.synthetic.jsonl")]) == 2
    assert not (tmp_path / "eval" / "riskset_neumann.synthetic.jsonl").exists()
