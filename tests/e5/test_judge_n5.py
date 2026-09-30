"""n=5 진짜 조건만(21:0x 결정) 판정 경로: 앞 5편 선택, 셔플 없는 봉투·지표, 위험 0개·degraded 행, 폴더 분리·보호, 예행 도구."""

from __future__ import annotations

import csv
import json

import pytest

from eval import judge_run as jr
from eval.backtest_common import canonical_sha256
from eval.backtest_metrics import bootstrap_ci, compute_metrics
from eval.backtest_riskset import make_risk, make_riskset
from eval.judge_envelope import ANSWER_FORMAT, blind_violations, read_human_answers
from eval.judge_summary import render_results_md

WORKS = [f"ns:P{i}" for i in range(6)]
FIRST5 = WORKS[:5]
N_RISKS = {"ns:P0": 0, "ns:P1": 3, "ns:P2": 2, "ns:P3": 3, "ns:P4": 3}  # Neumann: P0 카드 0장, P2 2장


def _sample():
    return {"items": [{"work_id": w} for w in WORKS], "reduced_n": 3, "list_sha256": canonical_sha256(WORKS),
            "human_sample": [WORKS[5]]}


def _rows(*, with_shuffle=True, with_extra_work=True):
    rows = []
    for w in FIRST5:
        n = N_RISKS[w]
        risks = [make_risk(k, f"위험 가 {WORKS.index(w)}-{k}", "설명이다.", evidence_ok=k <= 2) for k in range(1, n + 1)]
        rows.append(make_riskset(system="neumann", condition="real", work_id=w, plan_work_id=w, plan_id="p" * 64, risks=risks,
                                 status="degraded" if w == "ns:P1" else "ok", generator="rule" if w == "ns:P1" else ("none" if n == 0 else "astra"),
                                 model=None if n == 0 else "gpt-6.1-sol"))
    for w in WORKS if with_extra_work else FIRST5:
        conds = ("real", "shuffle") if with_shuffle else ("real",)
        for c in conds:
            risks = [make_risk(k, f"위험 나 {WORKS.index(w)}-{c[0]}-{k}", "설명이다.") for k in (1, 2, 3)]
            rows.append(make_riskset(system="baseline_llm", condition=c, work_id=w, plan_work_id=w, plan_id="q" * 64,
                                     risks=risks, status="ok", generator="astra", model="gpt-6.1-sol"))
    return rows


def _inputs():
    plans = {w: {"plan_text": f"plan {w}", "plan_id": "p" * 64} for w in WORKS}
    reviews = {w: [f"review 1 {w}", f"review 2 {w}"] for w in WORKS}
    return _sample(), plans, reviews


def _build(tmp_path, rows=None, **kw):
    sample, plans, reviews = _inputs()
    P = jr.paths(tmp_path, "judge_n5")
    work_ids = jr.resolve_work_ids("first5", sample)
    kw = {"work_ids": work_ids, "work_ids_spec": "first5", "conditions": ("real",)} | kw
    res = jr.build_package(sample, plans, reviews, rows if rows is not None else _rows(), P, **kw)
    return P, res


def _truth(m, work_id):
    """기대값 계산용: Neumann 1순위 A·나머지 B, 기준선 1순위 A(P0·P2·P4만)·2순위 B·3순위 C."""
    if m["system"] == "neumann":
        return "A" if m["rank"] == 1 else "B"
    if m["rank"] == 1:
        return "A" if work_id in ("ns:P0", "ns:P2", "ns:P4") else "B"
    return "B" if m["rank"] == 2 else "C"


def _answers(P, envs, key):
    for j in jr.JUDGES:
        for e, env in envs.items():
            meta = key["envelopes"][e]
            judg = []
            for r in env["risks"]:
                g = _truth(meta["risks"][r["risk_id"]], meta["work_id"])
                if j == "J3":
                    g = {"A": "B", "B": "C", "C": "A"}[g]
                judg.append({"risk_id": r["risk_id"], "grade": g, "review_no": 1 if g == "A" else None, "reason": "이유"})
            p = P["answers"] / j / f"{e}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"format": ANSWER_FORMAT, "envelope_id": e, "judge_id": j,
                                     "judge_model": "claude-sonnet-test", "judgments": judg}, ensure_ascii=False), encoding="utf-8")


# ── 논문 선택·폴더 ────────────────────────────────────────────────────────


def test_resolve_work_ids_first5_and_registration_check():
    s = _sample()
    assert jr.resolve_work_ids("first5", s) == FIRST5
    assert jr.resolve_work_ids("reduced", s) == WORKS[:3]
    assert jr.resolve_work_ids(None, s) is None and jr.resolve_work_ids("all", s) is None
    assert jr.resolve_work_ids("ns:P4,ns:P1", s) == ["ns:P4", "ns:P1"]
    for bad in ("first0", "first7", "ns:X", "ns:P1,ns:P1"):
        with pytest.raises(ValueError):
            jr.resolve_work_ids(bad, s)
    moved = dict(s, items=list(reversed(s["items"])))  # 순서가 바뀐 표본 → '앞 5편'의 뜻이 달라진다
    with pytest.raises(ValueError, match="list_sha256"):
        jr.resolve_work_ids("first5", moved)


def test_paths_default_compatible_and_n5_separate(tmp_path):
    d = jr.paths(tmp_path)
    assert d["judge"] == tmp_path / "judge" and d["key"] == tmp_path / "judge_key" / "pairing.json"
    assert d["results"] == tmp_path / "judge_results.json"  # 옛 경로 그대로
    n5 = jr.paths(tmp_path, "judge_n5")
    assert n5["judge"] == tmp_path / "judge_n5" and n5["key"] == tmp_path / "judge_n5_key" / "pairing.json"
    assert n5["results"] == tmp_path / "judge_n5_results.json" and n5["results_md"] == tmp_path / "judge_n5_results.md"
    assert n5["judge"] not in n5["key"].parents  # 짝 표는 판정 폴더 밖
    other = tmp_path / "x" / "j5"
    assert jr.paths(tmp_path, str(other))["judge"] == other  # 경로면 그대로


# ── 봉투 만들기(진짜 조건만) ──────────────────────────────────────────────


def test_build_real_only_first5_blind_and_human_packet(tmp_path):
    P, res = _build(tmp_path)
    assert res["work_ids"] == FIRST5 and res["conditions"] == ["real"] and res["controls"]["shuffle"] is False
    assert "셔플 대조 없음" in res["controls"]["note"]
    assert res["dropped_rows"] == {"condition": 6, "work": 1}  # 기준선 셔플 6행, 선택 밖 P5 진짜 1행
    assert res["envelopes"] == 5 and res["risks"] == 11 + 15
    assert res["by_system"]["neumann/real"]["zero_risk_rows"] == 1
    assert res["by_system"]["neumann/real"]["status"] == {"ok": 4, "degraded": 1}
    envs = jr.load_envelopes(tmp_path, "judge_n5")
    key = json.loads(P["key"].read_text(encoding="utf-8"))
    assert key["work_ids"] == FIRST5 and key["conditions"] == ["real"] and key["controls"]["shuffle"] is False
    assert {m["condition"] for e in key["envelopes"].values() for m in e["risks"].values()} == {"real"}
    assert sorted(e["work_id"] for e in key["envelopes"].values()) == FIRST5
    grouped = []
    for env in envs.values():
        assert blind_violations(env) == []
        dump = json.dumps({k: v for k, v in env.items() if k not in ("plan", "reviews")}, ensure_ascii=False).lower()
        for bad in ("neumann", "baseline", "shuffle", "condition", "system", "ns:p", "degraded", "rule"):
            assert bad not in dump, bad
        systems = [key["envelopes"][env["envelope_id"]]["risks"][r["risk_id"]]["system"] for r in env["risks"]]
        if len(set(systems)) > 1:
            grouped.append(systems in (sorted(systems), sorted(systems, reverse=True)))
    assert grouped and not all(grouped)  # 시스템별로 몰려 있지 않다(시드 고정 섞기)
    # 시드 고정: 같은 입력이면 같은 봉투
    P2, _ = _build(tmp_path / "again")
    assert json.loads((P2["envelopes"] / "manifest.json").read_text(encoding="utf-8"))["envelopes"] == \
        json.loads((P["envelopes"] / "manifest.json").read_text(encoding="utf-8"))["envelopes"]
    # 사람 꾸러미 = 앞 5편 전부(사전 고정 human_sample P5가 아니라)
    hfiles = sorted(p.stem for p in P["human"].glob("env_*.json"))
    assert hfiles == sorted(envs) and len(hfiles) == 5
    with (P["human"] / "answers_template.csv").open(encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 26
    readme = (P["human"] / "README.md").read_text(encoding="utf-8").lower()
    for bad in ("neumann", "baseline", "기준선", "셔플"):
        assert bad not in readme
    assert "system" not in (P["envelopes"] / "manifest.json").read_text(encoding="utf-8")


def test_missing_rows_fail_unless_allowed(tmp_path):
    rows = [r for r in _rows() if not (r["system"] == "neumann" and r["work_id"] == "ns:P3")]
    with pytest.raises(ValueError, match="neumann/real/ns:P3"):
        _build(tmp_path, rows)
    P, res = _build(tmp_path, rows, allow_missing=True)
    assert res["missing_risksets"] == ["neumann/real/ns:P3"] and res["envelopes"] == 5


def test_guard_existing_folder(tmp_path):
    P, _ = _build(tmp_path)
    _build(tmp_path)  # 같은 입력, 답 없음 → 다시 만들어도 된다
    with pytest.raises(FileExistsError, match="다른 입력"):
        _build(tmp_path, _rows(with_extra_work=False), riskset_sha256={"x": "y"})  # 다른 입력으로 덮기
    envs = jr.load_envelopes(tmp_path, "judge_n5")
    key = json.loads(P["key"].read_text(encoding="utf-8"))
    _answers(P, envs, key)
    with pytest.raises(FileExistsError, match="판정 답이 이미"):
        _build(tmp_path)
    _build(tmp_path, force=True)


def test_empty_work_gets_no_envelope_and_counts_zero(tmp_path):
    rows = [r for r in _rows(with_shuffle=False, with_extra_work=False) if not (r["system"] == "baseline_llm" and r["work_id"] == "ns:P0")]
    rows.append(make_riskset(system="baseline_llm", condition="real", work_id="ns:P0", plan_work_id="ns:P0", plan_id="q" * 64,
                             risks=[], status="error", generator="astra", model="gpt-6.1-sol"))
    P, res = _build(tmp_path, rows)
    assert res["envelopes"] == 4 and res["empty_works"] == ["ns:P0"]  # P0은 두 시스템 모두 위험 0개
    envs = jr.load_envelopes(tmp_path, "judge_n5")
    key = json.loads(P["key"].read_text(encoding="utf-8"))
    _answers(P, envs, key)
    good, report = jr.load_answers(envs, P)
    assert report["complete"]
    agg = jr.aggregate(envs, key, good)
    g = {(x["system"], x["work_id"]): x for x in agg["graded"]}
    assert g[("neumann", "ns:P0")]["judged"] and g[("baseline_llm", "ns:P0")]["judged"]
    m = compute_metrics(agg["graded"], work_ids=FIRST5, n_boot=200)
    assert m["systems"]["baseline_llm"]["real"]["n"] == 5 and m["systems"]["baseline_llm"]["real"]["failed_runs"] == 1
    assert m["systems"]["baseline_llm"]["real"]["status_counts"] == {"error": 1, "ok": 4}


# ── 답 → 다수결 → 지표(셔플 없음) ─────────────────────────────────────────


def test_end_to_end_real_only_metrics(tmp_path):
    P, _ = _build(tmp_path)
    envs = jr.load_envelopes(tmp_path, "judge_n5")
    key = json.loads(P["key"].read_text(encoding="utf-8"))
    _answers(P, envs, key)
    good, report = jr.load_answers(envs, P)
    assert report["complete"] and report["valid"] == 15
    agg = jr.aggregate(envs, key, good)
    m = compute_metrics(agg["graded"], work_ids=key["work_ids"], n_boot=300)
    ne, bl = m["systems"]["neumann"], m["systems"]["baseline_llm"]
    # 셔플 대조 없음: 측정 안 함으로 적고 0으로 채우지 않는다
    assert ne["shuffle"] == {"n": 0, "measured": False} and ne["specificity"]["measured"] is False
    assert m["summary"]["neumann"]["specificity"] == "측정 못 함"
    assert m["controls"]["shuffle"] is False and "셔플 대조 없음" in m["controls"]["note"]
    # Neumann(손 계산): P0 위험 0개 = 적중 0, P1~P4 A 1개씩 → p@3 = (4/3)/5, hit 4/5
    r = ne["real"]
    assert r["n"] == 5 and r["failed_runs"] == 1 and r["missing_slots"] == 4
    assert r["precision_at_3"]["value"] == pytest.approx(4 / 15, abs=1e-4) and r["hit_at_3"]["value"] == 0.8
    assert r["risk_grades"]["counts"] == {"A": 4, "B": 7, "C": 0} and r["risk_grades"]["n"] == 11
    assert r["status_counts"] == {"ok": 4, "degraded": 1}  # degraded도 빼지 않고 적는다
    assert r["evidence_rate"]["value"] == pytest.approx(8 / 11, abs=1e-4)
    assert r["vote_patterns"] == {"unanimous": 0, "split_2_1": 11, "all_differ": 0}
    b = bl["real"]
    assert b["precision_at_3"]["value"] == pytest.approx(0.2, abs=1e-4) and b["hit_at_3"]["value"] == 0.6
    assert b["fp_rate"]["value"] == pytest.approx(1 / 3, abs=1e-4) and b["risk_grades"]["counts"] == {"A": 3, "B": 7, "C": 5}
    c = m["comparison"]
    assert c["precision_at_3_diff_neumann_minus_baseline_llm"]["value"] == pytest.approx(1 / 15, abs=1e-4)
    assert c["precision_at_3_diff_neumann_minus_baseline_llm"]["n"] == 5
    assert c["hit_at_3_discordant"] == {"neumann_only": 2, "baseline_only": 1, "n": 5}
    sens = c["sensitivity_status_ok_only"]
    assert sens["excluded_work_ids"] == ["ns:P1"] and sens["n"] == 4 and sens["precision_at_3_diff"]["value"] == 0.0
    # 발표 표
    out = {"validation": {"valid": 15, "expected": 15, "complete": True, "missing": []}, "judge_agreement": agg["judge_pairwise_agreement"],
           "judge_models": ["claude-sonnet-test"], "run": {k: key.get(k) for k in ("work_ids", "work_ids_spec", "conditions", "empty_works")},
           "metrics": m}
    md = render_results_md(out)
    for frag in ("셔플 대조 없음", "논문 5편", "first5", "4/11 (36%)", "3/15 (20%)", "degraded 1 · ok 4 · 위험 0개 1편",
                 "Neumann만 적중 2편 · 일반 LLM만 적중 1편", "+0.067", "뺀 논문 1편", "| Neumann | 0 | 11 | 0 |"):
        assert frag in md, frag
    assert "[예행]" not in md  # 실제 판정 모델이면 예행 표시가 없다


def test_human_answers_metrics_and_agreement(tmp_path):
    P, _ = _build(tmp_path)
    envs = jr.load_envelopes(tmp_path, "judge_n5")
    key = json.loads(P["key"].read_text(encoding="utf-8"))
    sheet = (P["human"] / "answers_template.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(sheet.splitlines()))
    first_env = sorted(envs)[0]
    with (P["human"] / "answers.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["envelope_id", "risk_id", "grade", "review_no", "reason"])
        w.writeheader()
        for r in rows:
            if r["envelope_id"] == first_env and r["risk_id"] == "k01":
                continue  # 한 봉투는 다 채우지 않았다 → 사람 지표에서 뺀다
            w.writerow({**r, "grade": "A", "review_no": "1", "reason": "사람"})
    human = read_human_answers(P["human"] / "answers.csv")
    hg, incomplete = jr.human_graded(envs, key, human)
    assert incomplete == [first_env]
    m = compute_metrics(hg, work_ids=key["work_ids"], n_boot=100)
    skipped_work = key["envelopes"][first_env]["work_id"]
    assert m["systems"]["baseline_llm"]["real"]["n"] == 4
    assert skipped_work not in {g["work_id"] for g in hg if g["judged"]}


def test_bootstrap_ci_all_undefined_is_none():
    # 모든 논문이 위험 0개면 근거율 분모가 늘 0 → 구간 없음(예전에는 빈 목록 예외로 aggregate가 죽었다)
    assert bootstrap_ci([(0, 0), (0, 0)], lambda us: None if not sum(u[1] for u in us) else 1.0, n_boot=50) is None


def test_leaky_riskset_is_not_judged(tmp_path):
    rows = _rows()
    rows[2]["leak_check"] = {"leaks": 1}
    with pytest.raises(ValueError, match="누출"):
        _build(tmp_path, rows)
    assert not (tmp_path / "judge_n5").exists()  # 아무것도 쓰지 않았다


def test_briefs_for_n5_one_per_judge(tmp_path):
    P, _ = _build(tmp_path)
    envs = jr.load_envelopes(tmp_path, "judge_n5")
    briefs = jr.claude_briefs(list(envs), P, batch_size=10)
    assert set(briefs) == {"J1_b1.md", "J2_b1.md", "J3_b1.md"}
    for j in jr.JUDGES:
        text = briefs[f"{j}_b1.md"].replace("\\", "/")
        assert all(f"envelopes/{e}.json" in text for e in envs)
        assert f"judge_n5/answers/{j}/" in text and "judge_n5_key" in text and "pairing.json" not in text
        for other in set(jr.JUDGES) - {j}:
            assert f"answers/{other}/" not in text
        for bad in ("neumann", "baseline", "astra", "셔플"):
            assert bad not in text.lower()
