"""판정 봉투: 모델 중립 JSON, 블라인드(시스템 흔적 없음), 섞인 순서, 짝 표 분리, 사람 판정 꾸러미."""

from __future__ import annotations

import json

import pytest

from eval import judge_envelope as je
from eval.backtest_riskset import make_risk, make_riskset

WORKS = ["researcharcade_hf:AAA111", "researcharcade_hf:BBB222"]
TAG = {("neumann", "real"): "Nr", ("neumann", "shuffle"): "Ns", ("baseline_llm", "real"): "Br", ("baseline_llm", "shuffle"): "Bs"}


def _risksets():
    rows = []
    for i, w in enumerate(WORKS):
        partner = WORKS[1 - i]
        for system in ("neumann", "baseline_llm"):
            for cond, pw in (("real", w), ("shuffle", partner)):
                risks = [
                    make_risk(k, f"{TAG[system, cond]}-{w[-3:]}-{k} 위험 (R2) [ex_0123456789abcdef]" if system == "neumann" else f"위험 {TAG[system, cond]} {w[-3:]} {k}",
                              "설명 한 문장이다. https://openreview.net/forum?id=x 두 번째 문장이다.",
                              evidence_ok=(system == "neumann"))
                    for k in (1, 2, 3)
                ]
                rows.append(make_riskset(system=system, condition=cond, work_id=w, plan_work_id=pw, plan_id="p" * 64,
                                         risks=risks, status="ok", generator="astra", model="gpt-6-astra"))
    return rows


def _fix_system_words(rows):
    return rows


def _with_system_name(rows):
    rows[0]["risks"][0]["text"] += " (Neumann 결과)"
    return rows


def _inputs():
    sample = {"items": [{"work_id": w} for w in WORKS]}
    plans = {w: {"plan_text": f"plan of {w[-3:]}"} for w in WORKS}
    reviews = {w: [f"review one of {w[-3:]}", f"review two of {w[-3:]}"] for w in WORKS}
    return sample, plans, reviews


def test_build_envelopes_blind_shuffled_and_keyed():
    sample, plans, reviews = _inputs()
    envs, key = je.build_envelopes(sample, plans, reviews, _fix_system_words(_risksets()))
    assert len(envs) == 2
    for env in envs:
        assert je.blind_violations(env) == []
        assert len(env["risks"]) == 12  # 2 시스템 × 2 조건 × 3
        assert [r["risk_id"] for r in env["risks"]] == [f"k{i:02d}" for i in range(1, 13)]
        dump = json.dumps({k: v for k, v in env.items() if k not in ("plan", "reviews")}, ensure_ascii=False).lower()
        for bad in ("neumann", "baseline", "astra", "gpt", "shuffle", "condition", "system", "evidence", "researcharcade", "http", "ex_0123"):
            assert bad not in dump, bad
        assert set(env) == {"format", "envelope_id", "task", "rubric", "plan", "reviews", "risks", "answer_template"}
        assert env["envelope_id"].startswith("env_") and env["format"] == je.ENVELOPE_FORMAT
        meta = key["envelopes"][env["envelope_id"]]
        assert sorted(meta["risks"]) == [r["risk_id"] for r in env["risks"]]
        systems = [meta["risks"][r["risk_id"]]["system"] for r in env["risks"]]
        assert systems != sorted(systems)  # 시스템별로 몰려 있지 않다(섞였다)
        assert env["reviews"][0] == {"review_no": 1, "text": reviews[meta["work_id"]][0]}
        assert env["plan"] == plans[meta["work_id"]]["plan_text"]  # 셔플 위험도 계획서 i의 봉투에 들어간다
    envs2, key2 = je.build_envelopes(sample, plans, reviews, _fix_system_words(_risksets()))
    assert envs2 == envs and key2 == key  # 시드 고정


def test_blind_violations_really_detect():
    sample, plans, reviews = _inputs()
    with pytest.raises(ValueError, match="블라인드"):
        je.build_envelopes(sample, plans, reviews, _with_system_name(_risksets()))  # 위험 글에 시스템 이름
    envs, _ = je.build_envelopes(sample, plans, reviews, _fix_system_words(_risksets()))
    env = json.loads(json.dumps(envs[0]))
    env["risks"][0]["system"] = "neumann"
    assert je.blind_violations(env)
    env = json.loads(json.dumps(envs[0]))
    env["risks"][1]["text"] += " 카드 3 R2.1"
    assert je.blind_violations(env)
    env = json.loads(json.dumps(envs[0]))
    env["condition"] = "shuffle"
    assert je.blind_violations(env)
    env = json.loads(json.dumps(envs[0]))
    env["envelope_id"] = "env_neumann_real"
    assert je.blind_violations(env)


def test_save_key_outside_envelope_dir(tmp_path):
    sample, plans, reviews = _inputs()
    envs, key = je.build_envelopes(sample, plans, reviews, _fix_system_words(_risksets()))
    with pytest.raises(ValueError):
        je.save_envelopes(envs, key, tmp_path / "env", tmp_path / "env" / "pairing.json")
    man = je.save_envelopes(envs, key, tmp_path / "env", tmp_path / "key" / "pairing.json")
    assert man["n"] == 2 and man["n_risks"] == 24
    assert "system" not in (tmp_path / "env" / "manifest.json").read_text(encoding="utf-8")
    assert (tmp_path / "key" / "pairing.json").is_file()


def test_human_packet_only_real_and_answer_sheet(tmp_path):
    sample, plans, reviews = _inputs()
    envs, key = je.build_envelopes(sample, plans, reviews, _fix_system_words(_risksets()))
    h = je.human_envelope(envs[0], key)
    meta = key["envelopes"][envs[0]["envelope_id"]]["risks"]
    assert len(h["risks"]) == 6 and all(meta[r["risk_id"]]["condition"] == "real" for r in h["risks"])
    assert je.blind_violations(h) == []
    md = je.render_markdown(h)
    assert h["envelope_id"] in md and "neumann" not in md.lower()
    sheet = je.human_answer_sheet([h])
    p = tmp_path / "a.csv"
    p.write_text(sheet.replace(",,,", ",A,1,이유").replace(f"{h['envelope_id']},k", f"{h['envelope_id']},k"), encoding="utf-8")
    ans = je.read_human_answers(p)
    assert len(ans) == 6 and set(ans.values()) == {"A"}
    p.write_text(sheet, encoding="utf-8")
    with pytest.raises(ValueError):
        je.read_human_answers(p)  # 빈 등급은 오류
