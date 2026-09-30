"""E4-L0 build_ui_view 검사: 계약 준수, 예외 없음, 근거 없는 카드·문장 차단, 생성 방식 표기."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from pydantic import BaseModel

from neumann.api.view import SAMPLE_LABEL, build_ui_view, validate_ui_view

ROOT = Path(__file__).resolve().parents[2]
UI_SCHEMA = json.loads((ROOT / "contracts" / "ui_view.schema.json").read_text(encoding="utf-8"))
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "premortem_result.json").read_text(encoding="utf-8"))


def errors(view: dict) -> list[str]:
    return [f"{list(e.absolute_path)}: {e.message}" for e in Draft7Validator(UI_SCHEMA).iter_errors(view)]


def small_result(**over) -> dict:
    res = {
        "status": "ok",
        "session_id": "sess_1",
        "plan_id": "sha256:abc",
        "generated_at": "2026-09-30T20:00:00+09:00",
        "plan_stats": {"lines": [
            {"n": 1, "t": "계획서 제목", "h": "title"},
            {"n": 2, "t": "We randomly split the data."},
            {"n": 3, "t": "No error bars."},
        ]},
        "similar_works": [
            {"work_id": "W1", "title": "Paper One: A Study", "decision": "Rejected_Submission", "rating": 4.5,
             "url": "https://openreview.net/forum?id=W1"},
            {"work_id": "W2", "title": "Paper Two", "decision": "ICLR 2025 Poster", "rating": 6,
             "url": "https://openreview.net/forum?id=W2"},
        ],
        "evidence": [
            {"excerpt_id": "e1", "work_id": "W1", "text": "The split seems random; leakage is likely.",
             "source_url": "https://openreview.net/forum?id=W1", "risk_code": "R3", "start": 10, "end": 52},
            {"excerpt_id": "e2", "work_id": "W2", "text": "No standard deviations are reported.",
             "source_url": "https://openreview.net/forum?id=W2", "risk_code": "R2"},
        ],
        "risk_cards": [
            {"card_id": "c1", "risk_code": "R3", "title": "무작위 분할 누출", "plan_lines": [2], "severity": 5,
             "score": {"similarity": 0.9, "frequency": 0.5, "severity": 1.0, "confidence": 0.8, "total": 0.81},
             "evidence": ["e1"], "works": ["W1"], "generator": "astra"},
            {"card_id": "c2", "risk_code": "R2", "title": "불확실성 미보고", "why_applies": {"plan_lines": [3], "text": "오차 없음"},
             "severity": "S4", "score": {"total": 0.6}, "evidence": ["e2"], "generator": "rule"},
        ],
        "stages": [
            {"name": "extract", "phase": "RISK", "status": "degraded", "reason": "timeout → rule", "elapsed_s": 1.2},
        ],
    }
    res.update(over)
    return res


@pytest.mark.parametrize("bad", [
    None, {}, [], "text", 42,
    {"risk_cards": "x", "similar_works": [1, None, {"title": 5}], "evidence": {"a": 1},
     "plan_stats": {"lines": ["a", {"n": "x"}, {"n": 0, "t": "zero"}, None]}},
    {"plan_stats": {"lines": [{"n": 1, "t": "a"}, {"n": 1, "t": "dup"}]},
     "risk_cards": [{"evidence": [{"excerpt_id": "z", "text": "q"}], "severity": "high", "score": "nan"}],
     "expected_review": {"strength": ["no cite"], "audit": {"dropped": [1, ["a"], {"reason": "r"}]}},
     "stages": [None, "x", {"elapsed_s": "bad"}], "checklist": [{"action": "do", "decision": "maybe"}]},
])
def test_never_raises_and_always_valid(bad):
    view = build_ui_view(bad)
    assert errors(view) == []
    assert validate_ui_view(view) == []
    assert "_status" in view


def test_premortem_result_fixture_maps_fully():
    """E0b 공용 fixture(PremortemResult 모델 모양)를 그대로 넣는다."""
    view = build_ui_view(FIXTURE, sample=True, pipeline_state="unavailable")
    assert errors(view) == []
    fx_cards, fx_ev = FIXTURE["risk_cards"], FIXTURE["evidence"]
    assert len(view["works"]) == len(FIXTURE["similar_works"])
    assert len(view["cards"]) == len(fx_cards)
    assert len(view["ev"]) == len({e for c in fx_cards for e in c["evidence"]})
    assert view["_status"]["label"] == SAMPLE_LABEL
    assert view["_status"]["source"] == "sample"
    assert view["_status"]["generators"] == {"mock": len(fx_cards)}
    # 인용은 결과의 text 그대로, 카드 순서대로 번호가 붙는다
    quotes = {e["excerpt_id"]: e["text"] for e in fx_ev}
    first = view["ev"][str(view["cards"][0]["ev"][0])]
    assert first["q"] == quotes[fx_cards[0]["evidence"][0]]
    assert first["eid"] == fx_cards[0]["evidence"][0]
    # 계획서: 빈 줄은 빠지고 번호는 원래 번호, 마크다운 제목은 h
    ns = [line["n"] for line in view["plan"]["lines"]]
    assert ns == [ln["no"] for ln in FIXTURE["plan"]["lines"] if ln["text"].strip()]
    assert view["plan"]["lines"][0]["h"] == "title"
    assert view["plan"]["title"] == FIXTURE["plan"]["lines"][0]["text"].lstrip("#").strip()
    # 카드가 가리키는 계획서 줄은 f(표시) 되어 있다
    flagged = {line["n"] for line in view["plan"]["lines"] if line.get("f")}
    assert flagged == {n for c in fx_cards for n in c["why_applies"]["plan_lines"]}
    # 원문 URL로 발췌 → 유사 연구 대조(Excerpt에는 work_id가 없다)
    mapped = [e for e in view["ev"].values() if "map" in e]
    assert mapped and all(view["works"][e["map"] - 1]["id"] == e["id"] for e in mapped)
    # 지도 칸 수 = fams 수, 결정 정보가 없으면 거절 수를 지어내지 않는다
    assert all(len(w["f"]) == len(view["fams"]) for w in view["works"])
    assert len(view["corpus"]) == len(view["fams"])
    assert all(w["d"] == "미정" for w in view["works"])
    assert all("결정 정보 없음" in c["freq"] for c in view["cards"])


def test_pydantic_premortem_result_object_is_accepted():
    from neumann.models import PremortemResult

    model = PremortemResult.model_validate(FIXTURE)
    assert build_ui_view(model)["cards"] == build_ui_view(FIXTURE)["cards"]


def test_small_result_mapping_and_generator_honesty():
    view = build_ui_view(small_result())
    assert errors(view) == []
    c1, c2 = view["cards"]
    assert c1["gen"] == "astra" and c2["gen"] == "rule"
    assert c1["sev"] == 5 and c2["sev"] == 4
    assert c1["score"] == "0.81"
    assert c1["lines"] == [2] and c2["lines"] == [3]
    assert c2["desc"] == "오차 없음"
    assert c1["comp"][0] == ["유사도", 0.9]
    assert view["works"][0]["d"] == "거절" and view["works"][1]["d"] == "Poster"
    assert view["works"][0]["s"] == "Paper One"
    assert c1["freq"] == "유사 2편 중 1편 지적 · 그중 1편 거절"
    ev1 = view["ev"][str(c1["ev"][0])]
    assert ev1["q"] == "The split seems random; leakage is likely."
    assert ev1["off"] == [10, 52]
    assert ev1["u"] == "https://openreview.net/forum?id=W1"
    assert ev1["map"] == 1 and "x" not in ev1
    st = view["_status"]
    assert st["generators"] == {"astra": 1, "rule": 1}
    assert st["degraded"] is True  # 규칙 카드 + 강등 단계
    assert st["stages_not_ok"][0]["status"] == "degraded"
    assert st["label"] == ""  # result.status == ok → 배지는 없고 카드·추적에 생성 방식이 보인다
    assert view["pipeline"][0]["log"][0][0] == "w"
    assert view["kpi"]["n_works"] == 2 and view["kpi"]["n_reject"] == 1 and view["kpi"]["n_accept"] == 1


def test_card_without_resolvable_evidence_is_dropped():
    res = small_result()
    res["risk_cards"].append({"card_id": "c3", "risk_code": "R5", "title": "근거 없음", "evidence": ["nope"],
                              "generator": "astra"})
    res["risk_cards"].append({"card_id": "c4", "risk_code": "R5", "title": "근거 빈 목록", "evidence": [],
                              "generator": "astra"})
    view = build_ui_view(res)
    assert [c["id"] for c in view["cards"]] == ["c1", "c2"]
    assert view["_status"]["dropped"]["cards_without_evidence"] == 2


def test_zero_cards_carries_reason():
    view = build_ui_view(small_result(risk_cards=[], empty_reason="무관한 입력: 연구계획서가 아니다"))
    assert view["cards"] == []
    assert view["_status"]["empty_reason"] == "무관한 입력: 연구계획서가 아니다"
    view2 = build_ui_view(small_result(risk_cards=[]))
    assert view2["_status"]["empty_reason"]  # 사유가 없더라도 빈 문자열로 두지 않는다


def test_review_sentence_without_evidence_is_not_shown():
    res = small_result(expected_review={
        "strength": [{"text": "근거 있는 문장", "evidence": ["e1"]}],
        "weakness": [{"text": "근거 없는 문장", "evidence": []}, {"text": "모르는 근거", "evidence": ["zzz"]}],
        "request": [],
        "audit": {"generated": 4, "passed": 3, "dropped": [{"reason": "fabricated_number", "text": "R² 0.9"}]},
    })
    view = build_ui_view(res)
    R = view["review"]
    assert [s["t"] for s in R["strength"]] == ["근거 있는 문장"]
    assert R["weakness"] == []
    assert R["audit"]["gen"] == 4 and R["audit"]["pass"] == 1 and R["audit"]["drop"] == 3
    reasons = [d[0] for d in R["audit"]["dropped"]]
    assert reasons.count("missing_citation") == 1 and reasons.count("unknown_excerpt_id") == 1
    assert "fabricated_number" in reasons
    assert view["_status"]["dropped"]["review_sentences_without_evidence"] == 2


def test_plan_lines_outside_plan_are_dropped():
    res = small_result()
    res["risk_cards"][0]["plan_lines"] = [2, 99, "x"]
    res["evidence"][0]["plan_line"] = 42
    view = build_ui_view(res)
    assert view["cards"][0]["lines"] == [2]
    assert view["ev"]["1"]["ln"] is None
    assert view["_status"]["dropped"]["card_plan_lines"] == 2


def test_reviewer_identity_is_never_passed_through():
    res = small_result()
    res["evidence"][0]["reviewer_pseudonym"] = "Reviewer_HW8X"
    res["evidence"][1]["reviewer_pseudonym"] = "rvw_0123456789abcdef"
    view = build_ui_view(res)
    assert view["ev"]["1"]["rv"] == ""
    assert view["ev"]["2"]["rv"] == "rvw_0123456789abcdef"


def test_pydantic_model_input_is_accepted():
    class Result(BaseModel):
        status: str = "ok"
        session_id: str = "sess_m"
        plan_id: str = "p"
        generated_at: str = "2026-09-30"
        plan_stats: dict = {"lines": [{"n": 1, "t": "x"}]}
        similar_works: list = []
        evidence: list = [{"excerpt_id": "e", "work_id": "W", "text": "quote", "source_url": "https://x.org"}]
        risk_cards: list = [{"risk_code": "R1", "evidence": ["e"], "generator": "mock"}]

    view = build_ui_view(Result())
    assert errors(view) == []
    assert view["session_id"] == "sess_m"
    assert view["cards"][0]["gen"] == "mock"
    assert view["ev"]["1"]["x"] is True  # 유사 연구 목록 밖의 논문


def test_error_view():
    view = build_ui_view(None, pipeline_state="error", error="파이프라인 실행 실패: TimeoutError")
    assert errors(view) == []
    st = view["_status"]
    assert st["result_status"] == "error" and st["label"] == "분석 실패"
    assert st["notices"][0] == "파이프라인 실행 실패: TimeoutError"
