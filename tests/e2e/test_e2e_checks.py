"""E5-L0e2e 판정 함수 검사(기본 pytest, 서버·브라우저·API 없음).

라이브 E2E가 "샘플 모드면 파이프라인 미연결로 실패"·"카드·인용·링크·강등 표시"·"근거 연결률 1.0"을
실제로 잡아내는지, 공용 fixture와 실제 화면 조립기(build_ui_view)·실제 /health로 확인한다.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e_checks as C  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FX_RESULT = ROOT / "tests" / "fixtures" / "premortem_result.json"


@pytest.fixture(scope="module")
def result() -> dict:
    return json.loads(FX_RESULT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def build_ui_view():
    view = pytest.importorskip("neumann.api.view")
    return view.build_ui_view


def _dom(v: dict, **over) -> dict:
    """응답 view로 브라우저가 그렸을 화면 상태를 흉내 낸다(카드마다 인용·원문 링크)."""
    view = v
    cards = []
    for cd in view.get("cards") or []:
        evs = [{"quote_len": len(view["ev"][str(k)]["q"]), "href": view["ev"][str(k)]["u"] or "",
                "no_link_tag": not view["ev"][str(k)]["u"]} for k in cd["ev"]]
        cards.append({"rank": str(cd["rank"]), "gen_class": f"gen {cd['gen']}", "gen_text": cd.get("genl") or C.GEN_LABEL.get(cd["gen"], ""),
                      "ev": evs})
    st = view.get("_status") or {}
    notice = None
    if st.get("label"):
        notice = st["label"] + " " + " ".join(f"{s['phase']} · {s['name']} · {s['status']} · {s['reason']}"
                                              for s in st.get("stages_not_ok") or [] if st.get("source") != "sample")
    dom = {"view": "report", "ready": "1", "cards": cards, "no_cards": None if cards else "위험카드 0장" + (st.get("empty_reason") or ""),
           "notice": notice, "hdr_class": "pill st-ok", "hdr_text": "분석 파이프라인 연결 · v0.0.1",
           "trace": "Stages " + " ".join(f"{p['k']} {p['m']}" for p in view.get("pipeline") or []),
           "job_state": None, "job_err": None}
    dom.update(over)
    return dom


# ───────────────────────── 샘플 모드 = 실패 ─────────────────────────


def test_health_sample_mode_is_failure_on_this_branch() -> None:
    """이 브랜치 서버(파이프라인 모듈 없음)의 실제 /health는 샘플 모드 실패로 판정된다."""
    tc = pytest.importorskip("fastapi.testclient")
    from neumann.api.main import app

    health = tc.TestClient(app).get("/health").json()
    fails = C.check_health(health)
    if health["pipeline"]["state"] == "connected":
        assert fails == []
    else:
        assert fails and fails[0].startswith(C.SAMPLE_FAIL), fails


def test_health_connected_passes_and_error_fails() -> None:
    assert C.check_health({"pipeline": {"state": "connected", "reason": "", "mode": "pipeline"}}) == []
    err = C.check_health({"pipeline": {"state": "error", "reason": "neumann.pipeline import 실패", "mode": "error"}})
    assert err and not err[0].startswith(C.SAMPLE_FAIL) and "오류" in err[0]
    assert C.check_health(None) == ["서버 /health 응답 없음"]


def test_sample_view_and_result_are_reported_as_sample(result, build_ui_view) -> None:
    """서버가 샘플로 물러난 응답은 화면 데이터·결과 JSON·헤더 어디서든 SAMPLE_FAIL로 잡힌다."""
    tc = pytest.importorskip("fastapi.testclient")
    from neumann.api.main import app

    client = tc.TestClient(app)
    plan = (ROOT / "tests" / "fixtures" / "plans" / "plan.md").read_text(encoding="utf-8")
    health = client.get("/health").json()
    if health["pipeline"]["state"] == "connected":
        pytest.skip("이 브랜치에는 파이프라인이 연결돼 있다(샘플 모드 재현 불가)")
    view = client.post("/premortem/view", json={"plan_text": plan}).json()
    res = client.post("/premortem", json={"plan_text": plan}).json()
    v_fail, r_fail = C.check_view_status(view, 200), C.check_result_json(res, 200)
    assert v_fail and v_fail[0].startswith(C.SAMPLE_FAIL), v_fail
    assert r_fail and r_fail[0].startswith(C.SAMPLE_FAIL), r_fail
    h_fail = C.check_header({"hdr_class": "pill st-sample", "hdr_text": C.SAMPLE_LABEL})
    assert h_fail and h_fail[0].startswith(C.SAMPLE_FAIL)
    # 샘플에도 카드가 있다 — 카드 수 검사만으로는 샘플을 못 잡는다는 것을 확인(그래서 상태 검사가 따로 있다)
    assert C.check_cards(_dom(view), view) == []


def test_connected_view_has_no_sample_failure(result, build_ui_view) -> None:
    view = build_ui_view(result, pipeline_state="connected")
    assert view["_status"]["source"] == "pipeline"
    assert C.check_view_status(view, 200) == []
    assert C.check_result_json(result, 200) == []
    dom = _dom(view)
    assert C.check_header(dom) == []
    assert C.check_cards(dom, view) == []
    assert C.check_generators(dom, view) == []
    assert C.check_degradation(dom, view) == []


# ───────────────────────── 카드 · 인용 · 링크 · 생성 방식 · 강등 ─────────────────────────


def test_cards_missing_quote_link_or_zero_fail(result, build_ui_view) -> None:
    view = build_ui_view(result, pipeline_state="connected")
    dom = _dom(view)
    assert dom["cards"], "fixture에 카드가 있어야 한다"

    no_link = copy.deepcopy(dom)
    no_link["cards"][0]["ev"][0]["href"] = ""
    assert any("원문 링크" in f for f in C.check_cards(no_link, view))

    bad_link = copy.deepcopy(dom)
    bad_link["cards"][0]["ev"][0]["href"] = "javascript:alert(1)"
    assert any("원문 링크" in f for f in C.check_cards(bad_link, view))

    no_quote = copy.deepcopy(dom)
    for e in no_quote["cards"][0]["ev"]:
        e["quote_len"] = 0
    assert any("인용문" in f for f in C.check_cards(no_quote, view))

    zero = _dom(view, cards=[], no_cards="위험카드 0장 사유")
    assert any("0장" in f for f in C.check_cards(zero, None))

    stuck = _dom(view, view="job", job_state="failed", job_err="분석 실패 HTTP 500")
    assert any("리포트 화면에 도달하지 못했다" in f for f in C.check_cards(stuck, view))


def test_rule_card_shown_as_astra_fails(result, build_ui_view) -> None:
    res = copy.deepcopy(result)
    for c in res["risk_cards"]:
        c["generator"] = "rule"
    view = build_ui_view(res, pipeline_state="connected")
    dom = _dom(view)
    assert C.check_generators(dom, view) == []
    lie = copy.deepcopy(dom)
    lie["cards"][0]["gen_text"] = C.GEN_LABEL["astra"]
    assert any("generator=rule" in f for f in C.check_generators(lie, view))


def test_degraded_stage_must_be_displayed(result, build_ui_view) -> None:
    res = copy.deepcopy(result)
    res["stages"][0].update({"status": "degraded", "reason": "astra 시간 초과 → 규칙", "degraded": True})
    res["status"] = "degraded"
    view = build_ui_view(res, pipeline_state="connected")
    assert view["_status"]["stages_not_ok"], "강등 단계가 _status에 올라와야 한다"
    dom = _dom(view)
    assert C.check_degradation(dom, view) == []
    hidden = _dom(view, notice=view["_status"]["label"])  # 라벨만 있고 단계는 숨김
    assert any("강등 단계가 화면에 없다" in f for f in C.check_degradation(hidden, view))
    no_trace = _dom(view, trace="Stages")
    assert any("추적 섹션" in f for f in C.check_degradation(no_trace, view))


# ───────────────────────── 범위 밖 입력 ─────────────────────────


def test_negative_checks() -> None:
    ok_view = {"_status": {"empty_reason": "계획서가 연구 계획이 아니다(범위 밖)", "notices": []}}
    ok_dom = {"view": "report", "cards": [], "no_cards": "위험카드 0장계획서가 연구 계획이 아니다(범위 밖)"}
    assert C.check_negative(ok_dom, ok_view, 200) == []
    assert C.check_negative({**ok_dom, "cards": [{"rank": "1"}]}, ok_view, 200)
    no_reason = {"_status": {"empty_reason": "위험카드 0장 — 결과에 사유가 없다"}}
    assert C.check_negative({**ok_dom, "no_cards": "위험카드 0장위험카드 0장 — 결과에 사유가 없다"}, no_reason, 200)
    # 4xx 부적합 판정 + 사유는 통과, 500은 실패
    rej = {"_status": {"notices": ["연구계획서가 아니다"]}}
    assert C.check_negative({"view": "job", "job_err": "분석 실패 연구계획서가 아니다"}, rej, 422) == []
    assert C.check_negative({"view": "job", "job_err": "분석 실패"}, {"_status": {"notices": ["파이프라인 실행 실패"]}}, 500)


def _zero_card_result(result: dict, notices: list[str], stages: list[dict] | None = None, status: str = "ok") -> dict:
    """integ/v0 파이프라인 모양의 카드 0장 결과: 사유는 notices("위험카드 0장: …")와 risk_synthesis에 있다."""
    res = copy.deepcopy(result)
    res.update({"risk_cards": [], "evidence": [], "status": status, "notices": notices, "expected_review": {},
                "checklist": [], "stages": stages if stages is not None else [
                    {"name": "query_axes", "phase": "INPUT", "status": "ok", "reason": None, "elapsed_s": 1.2}]})
    reason = notices[0].split(":", 1)[1].strip() if notices and ":" in notices[0] else None
    res["risk_synthesis"] = {"no_card_reason": reason}
    return res


def test_negative_reason_from_pipeline_notices(result, build_ui_view) -> None:
    """카드 0장 사유가 notices에만 있을 때(view.py가 empty_reason으로 올리지 않음): 화면에 보이면 통과."""
    why = "위험카드 0장: 입력이 연구계획서가 아니다(astra 판단: 요리 메모); 연구성 0.02"
    view = build_ui_view(_zero_card_result(result, [why]), pipeline_state="connected")
    why = why.replace("astra 판단", "LLM 판단")  # 화면 문구는 계약 이름 astra를 LLM으로 보인다(DISP-1)
    st = view["_status"]
    assert st["empty_reason"] in C.DEFAULT_EMPTY_REASONS, st["empty_reason"]  # 오탐이 나던 모양 재현
    assert C.zero_card_reasons(view) == [why]
    shown = _dom(view, notice="일부 단계 강등 " + why)  # 상단 안내에 notices가 보인 화면
    assert C.check_negative(shown, view, 200) == []
    # 응답에는 사유가 있지만 화면 어디에도 없으면 실패(화면 결함을 사유 없음과 구분해 보고)
    hidden = C.check_negative(_dom(view, notice=None), view, 200)
    assert hidden and "화면(#noCards·#statusNotice)에 없다" in hidden[0], hidden


def test_negative_reason_missing_everywhere_still_fails(result, build_ui_view) -> None:
    """조작 입력: 사유가 자리표시뿐이거나 없거나, 분석 오류면 실패."""
    for notices in (["위험카드 0장: 카드 0장(사유 미상)"], [], ["위험카드 0장:"], ["[search] degraded: 색인 느림"]):
        view = build_ui_view(_zero_card_result(result, notices), pipeline_state="connected")
        dom = _dom(view, notice=" ".join(notices) or None)
        fails = C.check_negative(dom, view, 200)
        assert fails and "사유가 없다" in fails[0], (notices, fails)
    err = build_ui_view(_zero_card_result(result, ["위험카드 0장: 결과 조립 실패"], status="error"),
                        pipeline_state="connected")
    fails = C.check_negative(_dom(err), err, 200)
    assert fails and "분석 오류" in fails[0], fails


def test_negative_reason_from_skipped_card_stage(result, build_ui_view) -> None:
    """integ/v0 실제 흐름: 카드 합성 단계가 사유와 함께 건너뛰어지면 view가 그 사유를 empty_reason(#noCards)으로 올린다."""
    reason = "입력이 연구계획서가 아니다(astra 판단: 요리 메모)"
    stages = [{"name": "query_axes", "phase": "INPUT", "status": "ok", "reason": None},
              {"name": "search", "phase": "EVIDENCE", "status": "skipped", "reason": reason},
              {"name": "synthesize_cards", "phase": "RISK", "status": "skipped", "reason": reason},
              {"name": "verify_evidence", "phase": "REVIEW", "status": "skipped", "reason": "카드 없음"}]
    view = build_ui_view(_zero_card_result(result, [f"위험카드 0장: {reason}"], stages), pipeline_state="connected")
    reason = reason.replace("astra 판단", "LLM 판단")  # 화면 문구는 계약 이름 astra를 LLM으로 보인다(DISP-1)
    assert view["_status"]["empty_reason"] == reason
    dom = _dom(view)  # label이 없어 상단 안내는 없다 → #noCards에 사유
    assert dom["notice"] is None and reason in dom["no_cards"]
    assert C.check_negative(dom, view, 200) == []
    # 건너뛴 단계는 강등이 아니므로 상단 안내가 없어도 강등 검사 통과(추적 섹션에는 단계가 있어야 한다)
    assert C.check_degradation(dom, view) == []
    assert any("추적 섹션" in f for f in C.check_degradation(_dom(view, trace="Stages"), view))


def test_error_stage_must_be_displayed(result, build_ui_view) -> None:
    res = copy.deepcopy(result)
    res["stages"].append({"name": "expected_review", "phase": "REVIEW", "status": "error", "reason": "TimeoutError"})
    res["status"] = "degraded"
    view = build_ui_view(res, pipeline_state="connected")
    assert C.check_degradation(_dom(view), view) == []
    hidden = C.check_degradation(_dom(view, notice=view["_status"]["label"]), view)
    assert any("REVIEW · expected_review · error" in f for f in hidden), hidden


# ───────────────────────── 브라우저 위생 ─────────────────────────


def test_external_request_detection() -> None:
    base = "http://127.0.0.1:8123/"
    assert not C.is_external("http://127.0.0.1:8123/premortem/view", base)
    assert not C.is_external("http://localhost:8123/fonts/Jost/x.ttf", base)
    assert not C.is_external("data:image/png;base64,AAAA", base)
    assert C.is_external("https://fonts.googleapis.com/css2?family=Jost", base)
    assert C.is_external("https://api.openai.com/v1/responses", base)
    assert C.check_browser([], [], [], []) == []
    fails = C.check_browser(["Uncaught TypeError"], [], ["https://cdn.example.com/x.js"], [])
    assert len(fails) == 2 and fails[0].startswith("콘솔 오류 1건")


# ───────────────────────── 근거 연결 ─────────────────────────


def test_linkage_passes_on_fixture_and_fails_when_tampered(result) -> None:
    loader = pytest.importorskip("tests.fixtures.loader")
    pytest.importorskip("eval.linkage")
    fx = loader.load_fixtures()
    sources = {r.review_id: r.text for r in fx.reviews}
    sources.update({d.decision_id: d.text for d in fx.decisions if d.text is not None})
    fails, info = C.check_linkage(result, sources)
    assert fails == [] and info["linkage_rate"] == 1.0, (fails, info)

    bad = copy.deepcopy(result)
    ex = bad["evidence"][0]
    ex["text"] = ex["text"][:-1] + ("X" if ex["text"][-1] != "X" else "Y")
    fails, info = C.check_linkage(bad, sources)
    assert fails and info["linkage_rate"] < 1.0

    fails, info = C.check_linkage(result, {})  # 원문 조회가 비면 연결률 0
    assert fails and info["linkage_rate"] == 0.0


def test_stage_timings(result, build_ui_view) -> None:
    res = copy.deepcopy(result)
    for i, s in enumerate(res["stages"]):
        s["elapsed_s"] = 1.5 + i
    view = build_ui_view(res, pipeline_state="connected")
    view["_status"]["server_elapsed_s"] = 9.9
    t = C.stage_timings(view, res)
    assert t["view_server_elapsed_s"] == 9.9
    assert sum(t["view_phase_s"].values()) == pytest.approx(sum(1.5 + i for i in range(len(res["stages"]))))
    assert len(t["result_stage_s"]) == len(res["stages"])
