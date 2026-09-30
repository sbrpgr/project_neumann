"""E6-L3c 편집본 계획(순수 함수) 테스트. ffmpeg 없이 돈다."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("record_demo_edit", ROOT / "scripts" / "record_demo_edit.py")
ed = importlib.util.module_from_spec(_spec)
sys.modules["record_demo_edit"] = ed
_spec.loader.exec_module(ed)


def _meta(steps, click=7.8, report=39.8, dur=69.2):
    return {"duration_s": dur, "wall_s": dur, "steps": steps, "observed": {"analysis_t_click": click, "analysis_t_report": report}}


OK_STEPS = [{"id": "analyze", "t_start": 6.6, "status": "ok"}, {"id": "evidence", "t_start": 52.75, "status": "ok"}]


def test_only_analysis_wait_is_accelerated():
    p = ed.plan_edit(_meta(OK_STEPS), 4)
    assert p["segments"] == [(0.0, 7.8, 1.0), (7.8, 39.8, 4), (39.8, 69.2, 1.0)]
    assert p["end"] == 69.2 and p["cut_reason"] == "전체"
    assert p["expected_s"] == pytest.approx(7.8 + 32 / 4 + (69.2 - 39.8))
    assert p["caption"] == "분석 중(가속 ×4 · 실제 대기 32.0초)"


def test_failed_step_cut_before_its_caption():
    steps = [{"id": "analyze", "t_start": 6.6, "status": "ok"}, {"id": "evidence", "t_start": 52.75, "status": "failed"}]
    p = ed.plan_edit(_meta(steps), 4)
    assert p["end"] == pytest.approx(52.75 - ed.FAIL_MARGIN_S)
    assert p["segments"][-1] == (39.8, pytest.approx(52.35), 1.0)
    assert "evidence" in p["cut_reason"]


@pytest.mark.parametrize(
    "meta",
    [
        _meta(OK_STEPS, click=None),
        _meta(OK_STEPS, click=40, report=39.8),
        _meta([{"id": "report", "t_start": 39.0, "status": "failed"}]),  # 리포트 전에 실패 → 편집할 것 없음
    ],
)
def test_bad_meta_rejected(meta):
    with pytest.raises(ValueError):
        ed.plan_edit(meta, 4)


def test_filter_graph_draws_caption_only_on_fast_segment():
    g = ed.filter_graph(ed.plan_edit(_meta(OK_STEPS), 4), "font.ttf", "accel.txt")
    chains = g.split(";")
    assert len(chains) == 4 and chains[-1].startswith("[s0][s1][s2]concat=n=3")
    assert "drawtext" not in chains[0] and "drawtext" not in chains[2]
    assert "setpts=(PTS-STARTPTS)/4,drawtext=fontfile=font.ttf:textfile=accel.txt" in chains[1]
    assert "trim=start=7.800:end=39.800" in chains[1]
