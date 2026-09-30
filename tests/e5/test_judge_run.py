"""판정 실행기 전 과정(mock 판정 답): 봉투 → 답 검증 → 다수결 → 짝 표 복원 → 지표. Claude 지시문·Codex 명령."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from eval import judge_run as jr
from eval.backtest_metrics import compute_metrics
from eval.backtest_riskset import make_risk, make_riskset
from eval.judge_envelope import ANSWER_FORMAT, build_envelopes, save_envelopes

WORKS = [f"ns:W{i}" for i in range(4)]
PAIR = {WORKS[i]: WORKS[(i + 1) % 4] for i in range(4)}


def _risksets():
    rows = []
    for w in WORKS:
        for system in ("neumann", "baseline_llm"):
            for cond in ("real", "shuffle"):
                pw = w if cond == "real" else PAIR[w]
                n = 2 if (system == "neumann" and w == "ns:W3" and cond == "real") else 3  # 카드 2장뿐인 경우
                risks = [make_risk(k, f"위험 {system[0]}{cond[0]} {w} {k}", "설명이다.", evidence_ok=(system == "neumann" and k != 2))
                         for k in range(1, n + 1)]
                rows.append(make_riskset(system=system, condition=cond, work_id=w, plan_work_id=pw, plan_id="p" * 64,
                                         risks=risks, status="ok", generator="mock", model="mock"))
    return rows


def _setup(tmp_path: Path):
    P = jr.paths(tmp_path)
    sample = {"items": [{"work_id": w} for w in WORKS]}
    plans = {w: {"plan_text": f"plan {w}"} for w in WORKS}
    reviews = {w: [f"review 1 {w}", f"review 2 {w}", f"review 3 {w}"] for w in WORKS}
    envs, key = build_envelopes(sample, plans, reviews, _risksets())
    save_envelopes(envs, key, P["envelopes"], P["key"])
    return P, {e["envelope_id"]: e for e in envs}, key


def _truth(meta: dict) -> str:
    """mock 판정 규칙(기대값 계산용): neumann 진짜 1순위 = A, neumann 진짜 나머지 = B,
    일반 LLM 진짜 1순위 = A(단 W0만), 나머지 진짜 = B, 셔플 = C, 단 neumann 셔플 W1 1순위 = A."""
    s, c, r, w = meta["system"], meta["condition"], meta["rank"], meta["work_id"]
    if c == "real":
        if s == "neumann":
            return "A" if r == 1 else "B"
        return "A" if (r == 1 and w == "ns:W0") else "B"
    return "A" if (s == "neumann" and w == "ns:W1" and r == 1) else "C"


def _write_mock_answers(P, envs, key, *, disagree=True):
    for j in jr.JUDGES:
        for e, env in envs.items():
            meta = key["envelopes"][e]
            judg = []
            for r in env["risks"]:
                m = dict(meta["risks"][r["risk_id"]], work_id=meta["work_id"])
                g = _truth(m)
                if disagree and j == "J3":
                    g = {"A": "B", "B": "C", "C": "A"}[g]  # J3는 늘 다르게: 다수결은 J1·J2
                judg.append({"risk_id": r["risk_id"], "grade": g, "review_no": 1 if g == "A" else None, "reason": "한 줄 이유"})
            ans = {"format": ANSWER_FORMAT, "envelope_id": e, "judge_id": j, "judge_model": "mock-judge", "judgments": judg}
            p = P["answers"] / j / f"{e}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(ans, ensure_ascii=False), encoding="utf-8")


def test_majority_rule():
    assert jr.majority(["A", "A", "B"]) == "A"
    assert jr.majority(["C", "B", "C"]) == "C"
    assert jr.majority(["A", "B", "C"]) == "B"  # 모두 다르면 B
    with pytest.raises(ValueError):
        jr.majority(["A", "A"])


def test_end_to_end_mock_answers_to_metrics(tmp_path):
    P, envs, key = _setup(tmp_path)
    _write_mock_answers(P, envs, key)
    good, report = jr.load_answers(envs, P)
    assert report["complete"] and report["valid"] == 12 and not report["invalid"]
    agg = jr.aggregate(envs, key, good)
    assert agg["incomplete_envelopes"] == []
    assert agg["judge_pairwise_agreement"]["J1-J2"] == 1.0 and agg["judge_pairwise_agreement"]["J1-J3"] == 0.0
    g = {(x["system"], x["condition"], x["work_id"]): x for x in agg["graded"]}
    assert g[("neumann", "real", "ns:W3")]["grades"] == ["A", "B", None]  # 빈 자리
    assert g[("baseline_llm", "real", "ns:W0")]["grades"] == ["A", "B", "B"]

    m = compute_metrics(agg["graded"], n_boot=200)
    ne, bl = m["systems"]["neumann"], m["systems"]["baseline_llm"]
    # 손 계산: neumann 진짜 = 논문마다 A 1개 → p@3 = 1/3, hit = 1, 오탐 0
    assert ne["real"]["precision_at_3"]["value"] == pytest.approx(1 / 3, abs=1e-4)
    assert ne["real"]["hit_at_3"]["value"] == 1.0 and ne["real"]["fp_rate"]["value"] == 0.0
    assert ne["real"]["missing_slots"] == 1 and ne["real"]["n"] == 4
    # 근거율: neumann 진짜 위험 11개 중 2순위(4개)만 근거 실패 → 7/11
    assert ne["real"]["evidence_rate"]["value"] == pytest.approx(7 / 11, abs=1e-4)
    assert bl["real"]["evidence_rate"]["value"] == 0.0
    # 일반 LLM 진짜: W0만 A 1개 → p@3 = (1/3)/4
    assert bl["real"]["precision_at_3"]["value"] == pytest.approx(1 / 12, abs=1e-4)
    assert bl["real"]["hit_at_3"]["value"] == 0.25
    # 셔플: neumann W1만 A 1개 → 1/12, 특이성 = 1/3 − 1/12 = 0.25 ; 일반 LLM 셔플 0 → 특이성 1/12
    assert ne["shuffle"]["precision_at_3"]["value"] == pytest.approx(1 / 12, abs=1e-4)
    assert ne["specificity"]["value"] == pytest.approx(0.25, abs=1e-4)
    assert bl["specificity"]["value"] == pytest.approx(1 / 12, abs=1e-4)
    assert ne["shuffle"]["fp_rate"]["value"] == pytest.approx((2 + 3 + 3 + 3) / 12, abs=1e-4)
    diff = m["comparison"]["precision_at_3_diff_neumann_minus_baseline_llm"]
    assert diff["value"] == pytest.approx(1 / 3 - 1 / 12, abs=1e-4) and diff["n"] == 4
    lo, hi = diff["ci95"]
    assert lo <= diff["value"] <= hi
    # 축소 표본(앞 2편)만
    m2 = compute_metrics(agg["graded"], work_ids=["ns:W0", "ns:W1"], n_boot=200)
    assert m2["systems"]["neumann"]["real"]["n"] == 2


def test_incomplete_and_invalid_answers_are_reported(tmp_path):
    P, envs, key = _setup(tmp_path)
    _write_mock_answers(P, envs, key)
    e0 = sorted(envs)[0]
    (P["answers"] / "J2" / f"{e0}.json").unlink()
    bad = json.loads((P["answers"] / "J1" / f"{sorted(envs)[1]}.json").read_text(encoding="utf-8"))
    bad["judgments"] = bad["judgments"][1:]  # 하나 누락
    bad["judgments"][0]["grade"] = "D"
    (P["answers"] / "J1" / f"{sorted(envs)[1]}.json").write_text(json.dumps(bad), encoding="utf-8")
    good, report = jr.load_answers(envs, P)
    assert not report["complete"] and report["missing"] == [f"J2/{e0}"]
    errs = report["invalid"][f"J1/{sorted(envs)[1]}"]
    assert any("누락" in x for x in errs) and any("등급" in x for x in errs)
    agg = jr.aggregate(envs, key, good)
    assert set(agg["incomplete_envelopes"]) == {sorted(envs)[0], sorted(envs)[1]}
    judged_works = {x["work_id"] for x in agg["graded"] if x["judged"]}
    assert len(judged_works) == 2  # 3명 답이 다 있는 봉투만 집계


def test_validate_answer_rules(tmp_path):
    P, envs, key = _setup(tmp_path)
    env = next(iter(envs.values()))
    ok = {"format": ANSWER_FORMAT, "envelope_id": env["envelope_id"], "judge_id": "J1", "judge_model": "claude-sonnet-5-5",
          "judgments": [{"risk_id": r["risk_id"], "grade": "B", "review_no": None, "reason": "이유"} for r in env["risks"]]}
    assert jr.validate_answer(ok, env, "J1") == ([], [])
    bad = json.loads(json.dumps(ok))
    bad["judge_model"] = "<실제 모델 id>"
    bad["judgments"][0]["reason"] = "두\n줄"
    bad["judgments"][1]["review_no"] = 9
    bad["judgments"].append(dict(bad["judgments"][2]))
    errs, _ = jr.validate_answer(bad, env, "J2")
    joined = " ".join(errs)
    for frag in ("judge_id", "judge_model", "한 줄", "review_no", "중복"):
        assert frag in joined, frag
    a_no_ref = json.loads(json.dumps(ok))
    a_no_ref["judgments"][0]["grade"] = "A"
    assert jr.validate_answer(a_no_ref, env, "J1")[1]  # A인데 심사평 번호 없음 → 경고


def test_claude_briefs_isolated(tmp_path):
    P, envs, key = _setup(tmp_path)
    briefs = jr.claude_briefs(list(envs), P, batch_size=3)
    assert set(briefs) == {"J1_b1.md", "J1_b2.md", "J2_b1.md", "J2_b2.md", "J3_b1.md", "J3_b2.md"}
    for j in jr.JUDGES:
        listed = [e for name, text in briefs.items() if name.startswith(j) for e in envs if f"envelopes/{e}.json" in text]
        assert sorted(listed) == sorted(envs)  # 판정자마다 모든 봉투를 한 번씩
        text = "".join(t for n, t in briefs.items() if n.startswith(j))
        assert f"answers/{j}/" in text.replace("\\", "/")
        for other in set(jr.JUDGES) - {j}:
            assert f"answers/{other}/" not in text.replace("\\", "/")
        assert "pairing.json" not in text  # 짝 표 경로를 알려 주지 않는다
        # 파일 경로 검사는 위에서 끝냈다. 내용 누출 검사에서 호스트 임시 디렉터리만 뺀다.
        text = text.replace("\\", "/").replace(tmp_path.as_posix(), "")
        for bad in ("neumann", "baseline", "astra"):
            assert bad not in text.lower()


def test_codex_dry_run_and_fake_execute(tmp_path):
    P, envs, key = _setup(tmp_path)
    jobs = jr.codex_jobs(envs, P, codex="codex.exe")
    assert len(jobs) == 12
    cmd = jobs[0]["cmd"]
    assert cmd[:2] == ["codex.exe", "exec"] and cmd[cmd.index("-m") + 1] == "gpt-6-sol"
    assert cmd[cmd.index("-s") + 1] == "read-only" and "--output-schema" in cmd and cmd[-1] == "-"
    assert "--ephemeral" in cmd and "--skip-git-repo-check" in cmd
    assert "gpt-6-astra" not in " ".join(cmd)
    called = []
    res = jr.run_codex(jobs, P, execute=False, runner=lambda *a, **k: called.append(a))
    assert called == [] and {r["status"] for r in res} == {"dry-run"}
    assert (P["codex_prompts"] / "answer_schema.json").is_file() and jobs[0]["prompt_path"].is_file()
    assert "neumann" not in jobs[0]["prompt"].lower()

    def fake_runner(cmd, input, **kw):  # noqa: A002 — subprocess.run 인자 이름
        out = Path(cmd[cmd.index("-o") + 1])
        env = json.loads(input.split("봉투:\n", 1)[1])
        judg = [{"risk_id": r["risk_id"], "grade": "C", "review_no": None, "reason": "무관"} for r in env["risks"]]
        out.write_text("```json\n" + json.dumps({"format": ANSWER_FORMAT, "envelope_id": env["envelope_id"],
                                                  "judge_id": "?", "judge_model": "", "judgments": judg}) + "\n```", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    res = jr.run_codex(jobs, P, execute=True, runner=fake_runner, workers=2)
    assert {r["status"] for r in res} == {"ok"}
    good, report = jr.load_answers(envs, P)
    assert report["complete"]
    assert all(a["judge_model"] == "gpt-6-sol" for j in good.values() for a in j.values())
    res2 = jr.run_codex(jobs, P, execute=True, runner=fake_runner)
    assert {r["status"] for r in res2} == {"skip(있음)"}  # 이미 답이 있으면 다시 돌리지 않는다


def test_extract_json():
    assert jr.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert jr.extract_json('설명\n{"a": 2}\n끝') == {"a": 2}
    assert jr.extract_json("없음") is None
