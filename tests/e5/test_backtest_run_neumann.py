"""Neumann 위험 묶음 실행기: 조건별 제외 목록 전달(셔플 = i ∪ j), 근거율, 자동 누출 검사."""

from __future__ import annotations

import pytest

from eval import backtest_run_neumann as rn
from eval.judge_envelope import build_envelopes
from tests.fixtures.loader import load_fixtures


class View:
    def __init__(self, fx):
        self.fx = fx

    def reviews_for(self, wid):
        return [r for r in self.fx.reviews if r.work_id == wid]


def _setup():
    fx = load_fixtures()
    res = fx.premortem_result
    sample = {"items": [{"work_id": "t:I"}, {"work_id": "t:J"}],
              "shuffle_pairs": [{"work_id": "t:I", "plan_work_id": "t:J"}, {"work_id": "t:J", "plan_work_id": "t:I"}]}
    plans = {"t:I": {"plan_text": "plan I", "plan_id": "i" * 64}, "t:J": {"plan_text": "plan J", "plan_id": "j" * 64}}
    excl = {"targets": [{"work_id": "t:I", "exclude_work_ids": ["idx:I"]}, {"work_id": "t:J", "exclude_work_ids": ["idx:J"]}]}
    calls = []

    def fake(plan_text, *, exclude_work_ids, session_id):
        calls.append((plan_text, set(exclude_work_ids)))
        return res

    lookup = fx.source_text
    return fx, sample, plans, excl, fake, lookup, calls


def test_conditions_pass_union_exclusion_and_no_leak():
    fx, sample, plans, excl, fake, lookup, calls = _setup()
    rows = rn.run(sample, plans, excl, View(fx), fake, lookup)
    assert len(rows) == 4
    assert calls[0] == ("plan I", {"idx:I"})  # 진짜: i만
    assert calls[1] == ("plan J", {"idx:I", "idx:J"})  # 셔플: 계획서 j, 제외 i ∪ j
    shuf = rows[1]
    assert shuf["condition"] == "shuffle" and shuf["work_id"] == "t:I" and shuf["plan_work_id"] == "t:J"
    assert all(r["leak_check"]["leaks"] == 0 for r in rows)
    assert all(x["evidence_ok"] for x in rows[0]["risks"])


def test_leak_detected_when_evidence_from_target_paper():
    fx, sample, plans, excl, fake, lookup, _ = _setup()
    res = fx.premortem_result
    # 판정 논문 i의 심사평 = 근거로 쓰인 fixture 심사평이라고 두면(누출), 검사기가 잡아야 한다
    ev_review_ids = {e.source_id for e in res.evidence if e.source_kind == "review"}
    leaked_work = next(r.work_id for r in fx.reviews if r.review_id in ev_review_ids)

    class LeakyView(View):
        def reviews_for(self, wid):
            return [r for r in self.fx.reviews if r.work_id == leaked_work]

    excl["targets"][0]["exclude_work_ids"] = [leaked_work, *[s.work_id for s in res.similar_works]]
    rows = rn.run(sample, plans, excl, LeakyView(fx), fake, lookup, conditions=("real",), limit=1)
    lc = rows[0]["leak_check"]
    assert lc["leaks"] > 0 and lc["evidence_quotes_in_target_reviews"] > 0 and lc["similar_in_exclude"]


def test_empty_exclusion_aborts():
    fx, sample, plans, excl, fake, lookup, _ = _setup()
    excl["targets"][0]["exclude_work_ids"] = []
    with pytest.raises(ValueError, match="누출"):
        rn.run(sample, plans, excl, View(fx), fake, lookup)


def test_duplicate_risksets_rejected():
    fx, sample, plans, excl, fake, lookup, _ = _setup()
    rows = rn.run(sample, plans, excl, View(fx), fake, lookup, conditions=("real",))
    with pytest.raises(ValueError, match="중복"):
        build_envelopes(sample, plans, {"t:I": ["r"], "t:J": ["r"]}, rows + rows[:1])


def test_mock_never_writes_default_runs_or_names(tmp_path):
    base = tmp_path / "eval"
    # mock: 기본 이름에 .mock, 실행 결과는 기본 neumann_runs가 아니다(실제 실행 결과를 덮지 않는다)
    out, runs = rn.output_paths("mock", limit=5, out=None, runs_dir=None, base=base)
    assert out == base / "riskset_neumann.first5.mock.jsonl" and runs == base / "neumann_runs.mock"
    out, runs = rn.output_paths("mock", limit=5, out=tmp_path / "s" / "n.jsonl", runs_dir=None, base=base)
    assert runs == tmp_path / "s" / "neumann_runs.mock" and runs != base / "neumann_runs"
    # 실제 provider의 기본값은 그대로
    out, runs = rn.output_paths("openai", limit=None, out=None, runs_dir=None, base=base)
    assert out == base / "riskset_neumann.jsonl" and runs == base / "neumann_runs"
    assert rn.output_paths("openai", limit=5, out=None, runs_dir=tmp_path / "r", base=base)[1] == tmp_path / "r"
    assert rn.effective_provider("openai") == "openai"
