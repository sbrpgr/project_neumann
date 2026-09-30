"""E4-L1c build_ui_view: 근거 열람 패널·평가이력 지도·예상 심사평·체크리스트 데이터.

- 결정·평점은 결과에 없으면 코퍼스 기록(RecordLookup)에서 원문 그대로, 결과 값이 우선
- 샘플(가짜 fixture)에는 실제 기록을 섞지 않는다
- 근거: 인용은 결과 text 그대로(오프셋 유지), 연결된 계획서 줄 전부·인용 카드 순위
- 예상 심사평·체크리스트(E3-L1a·b 실제 출력 모양) → 목업 형식 + 생성 방식 표기
"""

from __future__ import annotations

import json

import pytest

from neumann.api import view as view_mod
from neumann.api.view import RecordLookup, build_ui_view, decision_label, rating_value, validate_ui_view
from tests.fixtures.loader import load_fixtures


def result(**over) -> dict:
    res = {
        "status": "ok",
        "plan": {"lines": [{"no": 1, "text": "# 제목"}, {"no": 2, "text": "We randomly split the data."},
                           {"no": 3, "text": "No error bars."}, {"no": 4, "text": "Baselines: two."}]},
        "similar_works": [
            {"work_id": "W1", "title": "Paper One", "url": "https://openreview.net/forum?id=W1", "similarity": 0.8},
            {"work_id": "W2", "title": "Paper Two", "url": "https://openreview.net/forum?id=W2", "similarity": 0.7,
             "decision": "ICLR 2025 Oral", "rating": 8},
        ],
        "evidence": [
            {"excerpt_id": "e1", "source_kind": "review", "source_id": "R1", "start": 5, "end": 34,
             "text": "The split  is random; leaky.", "source_url": "https://openreview.net/forum?id=W1&noteId=R1"},
            {"excerpt_id": "e2", "source_kind": "review", "source_id": "R3", "start": 0, "end": 20,
             "text": "No seeds are given.", "source_url": "https://example.org/other"},
        ],
        "risk_cards": [
            {"card_id": "c1", "risk_code": "R3", "title": "누출", "why_applies": {"text": "무작위", "plan_lines": [2]},
             "evidence": ["e1"], "score": {"total": 0.8}, "generator": "astra"},
            {"card_id": "c2", "risk_code": "R2", "title": "오차", "why_applies": {"text": "오차 없음", "plan_lines": [3, 4]},
             "evidence": ["e2", "e1"], "score": {"total": 0.6}, "generator": "rule"},
        ],
        "stages": [{"name": "verify_evidence", "status": "ok", "phase": "REVIEW"}],
        "verification": {"quotes_total": 2, "quotes_verified": 2},
    }
    res.update(over)
    return res


def records() -> RecordLookup:
    return RecordLookup.from_records(
        works=[{"work_id": "W1", "title": "Paper One"}, {"work_id": "W9", "title": "Outside Paper", "venue": "ICLR 2024",
                                                         "url": "https://openreview.net/forum?id=W9"}],
        reviews=[
            {"review_id": "R1", "work_id": "W1", "rating": "3: reject, not good enough", "kind": "official_review"},
            {"review_id": "R2", "work_id": "W1", "rating": "6: marginally above", "kind": "official_review"},
            {"review_id": "R3", "work_id": "W9", "rating": "8", "kind": "official_review"},
            {"review_id": "M1", "work_id": "W1", "rating": None, "kind": "meta_review"},
        ],
        decisions=[
            {"decision_id": "D1", "work_id": "W1", "outcome": "reject", "outcome_raw": "Rejected_Submission"},
            {"decision_id": "D2", "work_id": "W2", "outcome": "accept_poster", "outcome_raw": "ICLR 2025 Poster"},
            {"decision_id": "D9", "work_id": "W9", "outcome": "accept_spotlight", "outcome_raw": "ICLR 2024 spotlight"},
        ],
        source="test_records",
    )


def test_decision_and_rating_helpers():
    assert decision_label("accept_oral") == "Oral"
    assert decision_label("major_revision") == "대폭 수정"
    assert decision_label("Minor Revision") == "소폭 수정"
    assert decision_label("Rejected_Submission") == "거절"
    assert rating_value("6: marginally above the acceptance threshold") == 6.0
    assert rating_value("5.5") == 5.5 and rating_value(7) == 7.0
    assert rating_value("") is None and rating_value("n/a") is None


def test_works_get_decision_and_ratings_from_records_but_result_wins():
    v = build_ui_view(result(), records=records())
    assert validate_ui_view(v) == []
    w1, w2 = v["works"]
    # W1: 결과에 결정·평점이 없다 → 기록(원문 문자열 보존)
    assert (w1["d"], w1["draw"], w1["dsrc"]) == ("거절", "Rejected_Submission", "test_records")
    assert w1["rs"] == [3.0, 6.0] and w1["r"] == "4.50"  # 공식 심사평만(메타리뷰 제외), 평균
    # W2: 결과 값이 기록보다 우선
    assert (w2["d"], w2["r"], w2["dsrc"]) == ("Oral", "8", "result")
    assert v["kpi"]["n_reject"] == 1 and v["kpi"]["n_accept"] == 1
    assert v["_status"]["records"] == {"source": "test_records",
                                       "filled": {"works_decision": 1, "works_rating": 1, "evidence_rating": 2,
                                                  "evidence_decision": 1}}


def test_without_records_nothing_is_invented():
    v = build_ui_view(result(), records=None)
    w1 = v["works"][0]
    assert w1["d"] == "미정" and w1["r"] == "–" and "rs" not in w1 and "dsrc" not in w1
    assert all(e["rt"] == "" for e in v["ev"].values())
    assert v["_status"]["records"] is None


def test_sample_never_mixes_real_records(monkeypatch):
    calls = []
    monkeypatch.setattr(view_mod, "default_records", lambda: calls.append(1) or records())
    v = build_ui_view(result(), sample=True)
    assert calls == [] and v["_status"]["records"] is None and v["works"][0]["d"] == "미정"
    assert v["_status"]["label"] == view_mod.SAMPLE_LABEL
    v2 = build_ui_view(result())  # 실제 결과면 기본(AUTO)으로 기록을 쓴다
    assert calls == [1] and v2["works"][0]["d"] == "거절"


def test_evidence_panel_fields_verbatim_lines_cards():
    res = result()
    v = build_ui_view(res, records=records())
    ev = {e["eid"]: e for e in v["ev"].values()}
    e1, e2 = ev["e1"], ev["e2"]
    # 인용은 결과 text 그대로(공백 두 칸까지), 오프셋·해시 없이도 오프셋은 그대로
    assert e1["q"] == res["evidence"][0]["text"] and e1["off"] == [5, 34]
    # 발췌 → 논문: source_id(review) → 기록의 work_id. 평점은 그 심사평의 원문 평점
    assert (e1["id"], e1["rt"], e1["rtraw"], e1["d"]) == ("W1", "3", "3: reject, not good enough", "거절")
    # 연결된 계획서 줄: 이 발췌를 인용한 카드(c1 → 2행, c2 → 3·4행) 전부, 카드 순위도
    assert e1["lns"] == [2, 3, 4] and e1["ln"] == 2 and e1["cards"] == [1, 2]
    # 유사 연구 밖 논문(확장 검색): 기록에서 제목·학회·결정을 가져오되 x 표시는 유지
    assert e2["x"] is True and e2["p"] == "Outside Paper" and e2["d"] == "Spotlight" and e2["rt"] == "8"
    assert e2["lns"] == [3, 4] and e2["cards"] == [2]
    assert e1["kind"] == "review"
    assert v["_status"]["verification"] == {"total": 2, "verified": 2, "stage": "ok"}


def test_map_flags_follow_card_works():
    v = build_ui_view(result(), records=records())
    w1 = v["works"][0]
    assert w1["f"] == [1, 1]  # R3·R2 카드 모두 W1 발췌를 인용
    assert v["works"][1]["f"] == [0, 0]


@pytest.fixture(scope="module")
def e3_result():
    """공용 fixture + E3-L1a·b 규칙 경로(LLM 없음)의 실제 출력."""
    from neumann.analyze.checklist import attach_checklist
    from neumann.analyze.review import attach_expected_review

    fx = load_fixtures()
    res = attach_expected_review(fx.premortem_result, None)
    return attach_checklist(res, fx.premortem_result.plan, None), fx


def test_e3_expected_review_maps_to_mockup_format_with_generator(e3_result):
    res, fx = e3_result
    v = build_ui_view(res, records=None)
    assert validate_ui_view(v) == []
    R = v["review"]
    er = res.expected_review
    assert (R["gen"], R["st"]) == ("rule", "degraded") and R["why"] == er["reason"]
    assert R["audit"]["gate"] == er["audit"]["gate"] and R["audit"]["gen"] == er["audit"]["gen"]
    n_sent = sum(len(er[k]) for k in ("strength", "weakness", "request"))
    assert sum(len(R[k]) for k in ("strength", "weakness", "request")) == n_sent > 0
    s0 = R["weakness"][0]
    assert s0["t"] == er["weakness"][0]["t"]  # 문장은 그대로
    ev_by_eid = {e["eid"]: int(k) for k, e in v["ev"].items()}
    assert s0["c"] == [ev_by_eid[x] for x in er["weakness"][0]["c"]]
    assert s0["ln"] == er["weakness"][0]["plan_lines"] and s0["cards"] == [1]


def test_e3_checklist_maps_to_mockup_format(e3_result):
    res, _ = e3_result
    v = build_ui_view(res, records=None)
    ck = v["checklist"]
    assert len(ck) == len(res.checklist) > 0
    for it, raw in zip(ck, res.checklist):
        assert {"id", "t", "r", "s", "m"} <= set(it)
        assert (it["id"], it["t"], it["r"]) == (raw["item_id"], raw["action"], raw["risk_code"])
        assert it["s"] == "보류" and it["set"] is False  # 결정 전: 기본값 보류, 결정했다고 쓰지 않는다
        assert it["gen"] == "rule" and it["why"] == raw["fallback_reason"]
        assert it["ln"] == raw["plan_lines"] and it["card"] in (1, 2) and it["ev"]
    decided = res.model_copy(update={"checklist": [{**res.checklist[0], "decision": "채택", "note": "메모"}]})
    it = build_ui_view(decided, records=None)["checklist"][0]
    assert (it["s"], it["set"], it["m"]) == ("채택", True, "메모")


def test_review_and_checklist_hidden_when_absent():
    v = build_ui_view(result(), records=None)
    R = v["review"]
    assert all(R[k] == [] for k in ("strength", "weakness", "request")) and R["audit"]["gen"] == 0
    assert "gen" not in R and v["checklist"] == []


def test_fixture_records_fill_decisions_for_fixture_result():
    fx = load_fixtures()
    lk = RecordLookup.from_records(fx.works, fx.reviews, fx.decisions, source="fixture_records")
    v = build_ui_view(fx.premortem_result, records=lk, sample=True)
    assert [w["d"] for w in v["works"]] == ["거절", "Poster", "대폭 수정"]
    assert v["_status"]["label"] == view_mod.SAMPLE_LABEL  # 샘플 표시는 그대로


def test_default_records_reads_shared_data_dir(tmp_path, monkeypatch):
    (tmp_path / "index").mkdir()
    (tmp_path / "processed").mkdir()
    (tmp_path / "index" / "works.jsonl").write_text(
        json.dumps({"work_id": "W1", "title": "Paper One", "url": "https://x.org/W1"}) + "\n", encoding="utf-8")
    (tmp_path / "index" / "reviews.jsonl").write_text(
        json.dumps({"review_id": "R1", "work_id": "W1", "rating": "5: marginally below", "kind": "official_review"})
        + "\n{broken\n", encoding="utf-8")
    (tmp_path / "processed" / "decisions.jsonl").write_text(
        json.dumps({"decision_id": "D1", "work_id": "W1", "outcome": "reject", "outcome_raw": "Rejected_Submission"})
        + "\n", encoding="utf-8")
    monkeypatch.setattr(view_mod, "_data_dir", lambda: tmp_path)
    monkeypatch.setitem(__import__("sys").modules, "neumann.index.store", None)  # 메모리 색인 없음 → 파일
    view_mod._load_records.cache_clear()
    lk = view_mod.default_records()
    assert lk is not None and lk.source == "corpus_records"
    assert lk.decisions["W1"] == ("거절", "Rejected_Submission") and lk.ratings["W1"] == [5.0]
    assert lk.work_of_source("R1") == "W1" and lk.work_of_source("D1") == "W1"
    monkeypatch.setattr(view_mod, "_data_dir", lambda: tmp_path / "missing")
    assert view_mod.default_records() is None


def test_outside_paper_venue_from_records():
    v = build_ui_view(result(), records=records())
    e2 = next(e for e in v["ev"].values() if e["eid"] == "e2")
    assert e2["v"] == "ICLR 2024 · 심사평"
