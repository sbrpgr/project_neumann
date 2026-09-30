"""봉투 블라인드: 설명 앞머리 조사(“제목 — 은 …”)는 두 시스템 모두에서 지우고, 남으면 위반으로 잡는다."""

from __future__ import annotations

from eval.judge_envelope import LEADING_PARTICLE, blind_violations, normalize_risk_text


def test_normalize_strips_leading_particle_only_after_separator():
    assert normalize_risk_text("비교 설계 부재 — 은 학습 시간과 메모리") == "비교 설계 부재 — 학습 시간과 메모리"
    assert normalize_risk_text("근거 부족 — 는 기존 연구가") == "근거 부족 — 기존 연구가"
    assert normalize_risk_text("근거 부족 — 기존 연구가") == "근거 부족 — 기존 연구가"  # 조사 없음 → 그대로
    assert normalize_risk_text("은행 데이터 편향 — 은행 거래 기록") == "은행 데이터 편향 — 은행 거래 기록"  # 낱말 앞부분은 안 지움
    assert normalize_risk_text("제목만") == "제목만"


def test_blind_violation_flags_leading_particle():
    env = {
        "format": "x", "envelope_id": "env_0123456789ab", "task": "t", "rubric": {}, "plan": "p", "reviews": [],
        "risks": [{"risk_id": "k01", "text": "제목 — 은 기존 연구가"}],
        "answer_template": {},
    }
    assert any("앞머리 조사" in v for v in blind_violations(env))
    env["risks"][0]["text"] = normalize_risk_text(env["risks"][0]["text"])
    assert not any("앞머리 조사" in v for v in blind_violations(env))


def test_pattern_needs_trailing_space():
    assert LEADING_PARTICLE.match("은 기존")
    assert not LEADING_PARTICLE.match("은행 거래")
