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


def test_source_reference_sentence_removed_for_any_system():
    raw = ("비교 설계 부재 — 두 모델을 제안하지만 비교를 명시하지 않는다. "
           "유사 연구의 리뷰어들은 계산 효율 비교가 없으면 판단하기 어렵다고 지적했다.")
    assert normalize_risk_text(raw) == "비교 설계 부재 — 두 모델을 제안하지만 비교를 명시하지 않는다."
    raw2 = "차별성 — 무엇이 다른지 설명하지 않는다. 유사 연구에서는 결합만으로는 독창성이 약하다는 지적이 있었다."
    assert normalize_risk_text(raw2) == "차별성 — 무엇이 다른지 설명하지 않는다."
    raw3 = "공백 근거 — 문헌 범위를 명시하지 않는다. 유사 논문의 리뷰어들은 누락을 지적했으므로, 확인할 필요가 있다."
    assert normalize_risk_text(raw3) == "공백 근거 — 문헌 범위를 명시하지 않는다."
    plain = "범위 불명확 — 응용 분야와 잡음 모델이 무엇인지 알 수 없다."
    assert normalize_risk_text(plain) == plain  # 출처 문장이 없으면 그대로(기준선 모양)


def test_forbidden_catches_reviewer_reference():
    from eval.judge_envelope import RISK_FORBIDDEN

    for t in ("유사 연구의 리뷰어들은 지적했다", "유사 연구에서는 검토 쟁점이었다", "유사 논문의 심사평", "유사 연구들의 지적"):
        assert RISK_FORBIDDEN.search(t), t
    assert not RISK_FORBIDDEN.search("유사한 방법과 비교가 없다")
