"""E3-L1s: 짧은 입력 두 단계(300자 미만 → 거절, 600자 미만·요소 2개 이하 → 경고 후 끝까지 분석), 카드 0장 금지,
범위 밖 거절 유지.

실제 API 없음. "live_like"는 백테스트 n=5(gpt-6.1-sol) 실행 파일에 남은 판정을 그대로 흉내 낸 mock이다:
적합성 uncertain(요소 0개) + 검색어 단계 is_research_plan=False·검색어 [] → 고치기 전에는 추출 전에 멈춰 카드 0장.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import jsonschema
import pytest

import neumann.pipeline as pl
from neumann.analyze import cards as cards_mod
from neumann.analyze import fitness as fit_mod
from neumann.analyze.backend import FixtureBackend, Hit
from neumann.analyze.fitness import (
    ELEMENTS,
    assess_fitness,
    TOO_SHORT_MESSAGE,
    input_length,
    input_quality,
    refine_input_quality,
    rule_fitness,
    sentence_units,
)
from neumann.analyze.mock_responders import default_responders
from neumann.api.view import build_ui_view, validate_ui_view
from neumann.llm import MockProvider
from neumann.models import PlanDocument
from neumann.pipeline import run_premortem
from tests.e3.corpus import RECIPE, build, build_backend
from tests.e3.short_inputs import KO_UNDER_300, LONG_SINGLE, OFFTOPIC, REJECT, UNDER_300, WARN
from tests.fixtures.loader import DEMO_PLANS, NEGATIVE_PLAN, plan_text

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "contracts" / "premortem_response.schema.json").read_text(encoding="utf-8"))
WARN_TEXT = "입력이 짧아 결과 신뢰도가 낮습니다 — 연구 질문·방법·데이터·평가를 더 적어 주세요"

# 가짜 코퍼스(배터리·의료영상) 분야의 경고 단계 입력(300~600자): 백테스트 SFCH처럼 연구 배경만(목표·방법 문장 없음)
SHORT_BAT = ("Graph neural network surrogates are increasingly used to screen lithium battery electrolytes for high "
             "ionic conductivity. Most models are trained on literature data of electrolyte formulations, which mixes "
             "measurements taken at different temperatures and salt concentrations. How reliable these surrogates are "
             "for new electrolyte chemistries remains poorly understood.")
SHORT_IMG = ("Convolutional neural networks can detect pneumonia in chest X-ray images and are often compared with "
             "radiologists. Most studies train and test on images from a single hospital. Their performance on "
             "external hospital data, other scanners, and noisy labels mined from reports remains poorly understood.")
WARN_ALL = WARN + [(i, t) for i, exp, t in LONG_SINGLE if exp == "warn"]
REJECT_ALL = REJECT + UNDER_300 + KO_UNDER_300 + [(i, t) for i, exp, t in LONG_SINGLE if exp == "reject"]
OFF_ALL = [*OFFTOPIC, ("RECIPE", RECIPE), ("negative_recipe.md", plan_text(NEGATIVE_PLAN))]
OFF_UNDER = [(i, t) for i, t in OFF_ALL if input_length(t) < 300]
OFF_OVER = [(i, t) for i, t in OFF_ALL if input_length(t) >= 300]


def _plan(text: str) -> PlanDocument:
    return PlanDocument.from_text(text, "sess-test")


class FakeLLM:
    generator = "mock"
    model = "mock-fitness"

    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.calls: list[str] = []

    def __call__(self, schema: dict, instructions: str, input: str, *, effort: str) -> Any:  # noqa: A002
        self.calls.append(input)
        return self.reply


def _reply(verdict: str, lines: dict[str, list[int]] | None = None) -> dict:
    lines = lines or {}
    return {"verdict": verdict, "elements": {e: {"present": bool(lines.get(e)), "plan_lines": lines.get(e, [])}
                                             for e in ELEMENTS}, "field": "", "reason": "사유"}


def live_like(**override: Any) -> MockProvider:
    """백테스트 실행 파일의 sol 판정을 흉내 낸 mock: 적합성 uncertain(요소 0) + 검색어 단계 '계획서 아님'·검색어 []."""
    r = default_responders()
    r["fitness"] = lambda call: {**_reply("uncertain"), "reason": "1번 줄은 연구 배경만 설명한다."}
    r["query_axes"] = lambda call: {
        "is_research_plan": False, "suitability_reason": "배경 설명일 뿐 연구 목표가 없다.", "suitability_lines": [1],
        "domain": "", "queries": [], "axes": {"method": "", "data": "", "evaluation": ""},
    }
    r.update(override)
    return MockProvider(r)


class StrongBackend(FixtureBackend):
    """bge-m3 하이브리드 척도를 흉내 낸 가짜 코퍼스 검색: 낱말이 겹치는 논문의 관련도를 0.55~0.75로 옮긴다
    (실측: 경고 단계 입력 24건의 상위 관련도 0.541~0.873)."""

    def search(self, queries, k=10, exclude_work_ids=None, *, score_floor=None):  # noqa: ANN001
        hits = super().search(queries, k=k, exclude_work_ids=exclude_work_ids)
        return [Hit(h.work_id, score=round(0.55 + 0.2 * h.score, 4), dense=round(0.55 + 0.2 * h.score, 4),
                    lexical=h.lexical, matched_query=h.matched_query) for h in hits]


class FloorBackend(FixtureBackend):
    """모든 논문이 점수 하한 아래인 코퍼스(하한을 넘은 논문 0편). score_floor=0.0을 주면 상위 k편을 준다."""

    def search(self, queries, k=10, exclude_work_ids=None, *, score_floor=None):  # noqa: ANN001
        if score_floor is None:
            return []
        return super().search(queries, k=k, exclude_work_ids=exclude_work_ids, score_floor=score_floor)


class EverythingBackend(FixtureBackend):
    """질의와 상관없이 가짜 코퍼스 8편을 모두 관련도 0.7로 돌려준다(검색 근거만으로는 막을 수 없는 최악의 경우)."""

    def search(self, queries, k=10, exclude_work_ids=None, *, score_floor=None):  # noqa: ANN001
        return [Hit(w, score=0.7, dense=0.7, lexical=0.0, matched_query=queries[0] if queries else "")
                for w in sorted(self.works)][:k]


def _strong() -> StrongBackend:
    return StrongBackend(*build())


def _run(text: str, llm: MockProvider, backend: Any = None) -> Any:
    return run_premortem(text, llm=llm, backend=backend if backend is not None else _strong(), cache_dir=None)


def _st(result: Any, name: str) -> Any:
    return next(s for s in result.stages if s.stage == name)


def _view(result: Any) -> dict:
    view = build_ui_view(result, records=None)
    assert validate_ui_view(view) == [] and view["_status"]["contract_ok"] is True
    return view


# ── 1. 단계 기준표(보정 세트) ─────────────────────────────────────────────


def test_calibration_set_sizes() -> None:
    """보정 세트: 경고 15(한국어 6·영어 8·긴 한 문장 1), 거절 43, 범위 밖 6(300자 이상 1)."""
    assert len(WARN_ALL) >= 15 and len(REJECT_ALL) >= 40 and OFF_OVER and OFF_UNDER
    assert all(300 <= input_length(t) < 600 for _, t in WARN_ALL)
    assert all(input_length(t) < 300 for _, t in UNDER_300 + KO_UNDER_300)


@pytest.mark.parametrize(("iid", "text"), WARN_ALL, ids=[i for i, _ in WARN_ALL])
def test_short_but_clear_inputs_are_warn(iid: str, text: str) -> None:
    iq = rule_fitness(_plan(text))["input_quality"]
    assert iq["level"] == "warn", (iid, iq["reasons"], iq["metrics"])
    assert iq["status"] == "warn_short_input" and iq["message"].startswith(WARN_TEXT)


@pytest.mark.parametrize(("iid", "text"), REJECT_ALL, ids=[i for i, _ in REJECT_ALL])
def test_thin_inputs_are_rejected_without_llm_call(iid: str, text: str) -> None:
    fake = FakeLLM(_reply("research_plan", {e: [1] for e in ELEMENTS}))
    r = assess_fitness(_plan(text), fake)
    assert fake.calls == []  # LLM 호출 0
    assert r["verdict"] == "unfit" and r["analyze"] is False and r["decided_by"] == "precheck"
    iq = r["input_quality"]
    assert iq["level"] == "reject" and iq["status"] == "rejected_thin_input", (iid, iq["metrics"])
    assert "연구 질문·방법·데이터·평가를 적어 주세요" in r["notice"] and r["notice"] == iq["message"]
    assert r["rule"]["precheck"] in ("too_short", "too_thin")
    if input_length(text) < 300:
        assert r["rule"]["precheck"] == "too_short" and r["notice"] == TOO_SHORT_MESSAGE


@pytest.mark.parametrize(("iid", "text"), OFF_UNDER, ids=[i for i, _ in OFF_UNDER])
def test_offtopic_under_300_rejected_by_length_without_call(iid: str, text: str) -> None:
    fake = FakeLLM(_reply("research_plan", {e: [1] for e in ELEMENTS}))
    r = assess_fitness(_plan(text), fake)
    assert fake.calls == [] and r["verdict"] == "unfit" and r["notice"] == TOO_SHORT_MESSAGE


@pytest.mark.parametrize(("iid", "text"), OFF_OVER, ids=[i for i, _ in OFF_OVER])
def test_offtopic_over_300_still_rejected_by_fitness(iid: str, text: str) -> None:
    """300자 이상 범위 밖 글은 지금처럼 적합성 판정이 거절한다(무관 표지가 있으면 분량 단계는 거절하지 않고 넘긴다)."""
    plan = _plan(text)
    rule = rule_fitness(plan)
    assert rule["verdict"] == "unfit" and rule["offtopic_hits"] >= 1 and rule["input_quality"]["level"] != "reject"
    r = assess_fitness(plan, FakeLLM(_reply("not_research_plan")))
    assert r["verdict"] == "unfit" and r["analyze"] is False and r["decided_by"] == "llm"
    assert r["checks"]["overrides"] == []  # 짧은 입력 과잉 거절 방지가 범위 밖 글을 살리지 않는다


@pytest.mark.parametrize("name", DEMO_PLANS)
def test_demo_plans_are_ok_tier(name: str) -> None:
    iq = rule_fitness(_plan(plan_text(name)))["input_quality"]
    assert iq["level"] == "ok" and iq["message"] is None and iq["reasons"] == []


def test_300_char_rule_counts_raw_stripped_length() -> None:
    """거절 = 앞뒤 공백을 뺀 원문 300자 미만(공백 포함, 한글 가중치 없음). 옛 40자 사전검사를 합쳤다. 화면 문구는 지시 그대로."""
    assert fit_mod.MIN_CHARS == 300 and fit_mod.WARN_CHARS == 600
    assert TOO_SHORT_MESSAGE == "입력이 300자 미만이라 연구계획서로 분석하지 않습니다. 연구 질문·방법·데이터·평가를 적어 주세요."
    base = dict(WARN)["V09"]  # 영어 429자, 경고
    cut = base[:299]
    assert input_quality(_plan("   " + cut + "\n\n  "))["reasons"][0]["code"] == "too_short"  # 앞뒤 공백은 세지 않는다
    assert input_quality(_plan(cut))["message"] == TOO_SHORT_MESSAGE
    assert input_quality(_plan(base[:300].rstrip() + "x" * (300 - len(base[:300].rstrip()))))["level"] == "warn"
    assert input_quality(_plan("안녕하세요"))["reasons"][0]["code"] == "too_short"


def test_korean_needs_about_seven_sentences_to_pass_300() -> None:
    """한국어는 같은 내용이 짧다: 4~5문장 계획(K01~K08, 요소 2~4개)은 177~236자라 거절, 7문장(V01·V04~V06)은 경고."""
    for iid, text in KO_UNDER_300:
        iq = input_quality(_plan(text))
        assert iq["level"] == "reject" and 4 <= iq["metrics"]["n_sentences"] <= 5, iid
    assert input_quality(_plan(dict(KO_UNDER_300)["K08"]))["metrics"]["n_elements"] == 4
    for iid in ("V01", "V04", "V05", "V06"):
        iq = input_quality(_plan(dict(WARN)[iid]))
        assert iq["level"] == "warn" and iq["metrics"]["n_sentences"] >= 7, iid


def test_single_sentence_rules_recalibrated_above_300() -> None:
    """300자 이상 한 문장: 지시어로 시작하거나 요소 3개 미만이면 거절, 요소 3개 이상이면 경고(한 문장 규칙만으로 거절되는 것은 S02)."""
    got = {i: input_quality(_plan(t)) for i, _exp, t in LONG_SINGLE}
    assert all(input_length(t) >= 300 for _i, _e, t in LONG_SINGLE)
    assert got["S01"]["level"] == "warn" and got["S01"]["metrics"]["n_sentences"] == 1
    assert [r["code"] for r in got["S02"]["reasons"]] == ["single_sentence"]
    assert [r["code"] for r in got["S03"]["reasons"]] == ["demonstrative_sentence"]
    assert got["S03"]["message"].startswith("입력을 연구계획서로 분석하지 않습니다(")


# ── 2. 적합성 판정과 분량 단계 ──────────────────────────────────────────────


def test_model_rejection_of_short_on_topic_input_is_softened() -> None:
    """짧지만 분야·방법 표지가 있고 무관 표지가 없으면 모델의 '연구 아님'을 보류로 낮춘다(분석 진행)."""
    for iid in ("V02", "V03", "V09", "V11", "V16"):
        r = assess_fitness(_plan(dict(WARN)[iid]), FakeLLM(_reply("not_research_plan")))
        assert r["verdict"] == "uncertain" and r["analyze"] is True, iid
        assert any("짧은 입력" in o for o in r["checks"]["overrides"])
        assert r["input_quality"]["level"] == "warn"


def test_fitness_uncertain_or_few_llm_elements_adds_warning_to_long_plan() -> None:
    plan = _plan(plan_text("plan.md"))
    all_lines = {e: rule_fitness(plan)["elements"][e]["plan_lines"] for e in ELEMENTS}
    ok = assess_fitness(plan, FakeLLM(_reply("research_plan", all_lines)))
    assert ok["input_quality"]["level"] == "ok"
    unc = assess_fitness(plan, FakeLLM(_reply("uncertain", all_lines)))
    assert unc["input_quality"]["level"] == "warn"
    assert [x["code"] for x in unc["input_quality"]["reasons"]] == ["fitness_uncertain"]
    few = assess_fitness(plan, FakeLLM(_reply("research_plan", {"method": all_lines["method"], "data": all_lines["data"]})))
    assert "few_elements_llm" in [x["code"] for x in few["input_quality"]["reasons"]]
    assert few["input_quality"]["missing"] == ["research_question", "evaluation"]
    # 거절 단계는 판정 뒤에도 바뀌지 않는다
    rej = input_quality(_plan("PINN 연구"))  # 거절 단계
    assert refine_input_quality(rej, unc)["level"] == "reject"


# ── 3. 파이프라인: 경고 단계는 끝까지, 카드 0장 없음 ─────────────────────────


@pytest.mark.parametrize("text", [SHORT_BAT, SHORT_IMG])
def test_live_like_short_input_now_gets_cards(text: str) -> None:
    """백테스트 0장 원인(적합성 보류 + 검색어 단계 '계획서 아님')을 재현: 이제 유사 연구 근거로 진행해 카드 ≥1."""
    llm = live_like()
    r = _run(text, llm)
    assert len(r.risk_cards) >= 1, r.risk_synthesis.get("no_card_reason")
    assert r.plan_checks["input_quality"]["level"] == "warn"
    assert r.manifest["input_quality"] == {"level": "warn", "status": "warn_short_input"}
    gate = r.plan_checks["research_gate"]
    assert gate["passed"] is True and gate["status"] == "proceeded_on_similar_work_evidence"
    assert gate["note"] == "적합성 보류였으나 유사 연구 근거로 진행"
    assert gate["top_relevance"] >= pl.RESEARCH_GATE_MIN_TOP and gate["n_strong_works"] >= pl.RESEARCH_GATE_MIN_WORKS
    assert r.plan_checks["suitability"]["thin_input"] is True
    assert any(n.startswith("적합성 보류였으나 유사 연구 근거로 진행") for n in r.notices)
    assert any(n.startswith(WARN_TEXT) for n in r.notices)
    # 검색어 규칙 대체를 숨기지 않는다
    assert r.plan_checks["search"]["queries_source"] == "rule" and "규칙 대체" in _st(r, "search").detail
    tasks = [c.task for c in llm.calls]
    assert "extract_issues" in tasks and "synthesize_cards" in tasks
    # 카드 근거는 원문 대조를 통과했다
    assert _st(r, "verify_evidence").state == "ok"
    jsonschema.validate(r.model_dump(mode="json"), CONTRACT)


def test_short_input_view_shows_warning_and_search_marks() -> None:
    r = _run(SHORT_BAT, live_like())
    st = _view(r)["_status"]
    assert st["input_quality"]["level"] == "warn" and st["input_quality"]["label"] == "입력이 짧아 결과 신뢰도 낮음"
    assert st["notices"][0].startswith(WARN_TEXT)  # 안내 문구가 맨 앞
    assert st["label"].startswith("입력이 짧아 결과 신뢰도 낮음")  # 화면 공지 상자는 라벨이 있을 때 뜬다
    assert "검색어 규칙 대체" in st["label"] and "적합성 보류였으나 유사 연구 근거로 진행" in st["label"]
    assert st["search"]["queries_source"] == "rule" and st["search"]["research_gate"] == "proceeded_on_similar_work_evidence"
    assert set(st["input_quality"]["missing"]) <= set(ELEMENTS) and st["input_quality"]["followups"]


def test_weak_search_still_stops_uncertain_non_plan() -> None:
    """유사 연구 근거가 약하면(가짜 코퍼스 원래 척도: 0.50 이상 1편) 적합성 보류 + '계획서 아님'에서 멈춘다."""
    r = _run(SHORT_BAT, live_like(), backend=build_backend())
    assert r.risk_cards == []
    gate = r.plan_checks["research_gate"]
    assert gate["passed"] is False and gate["failed_checks"] == ["search_strong"]
    reason = r.risk_synthesis["no_card_reason"]
    assert "적합성 판정 보류" in reason and "진행 조건 미충족(search_strong)" in reason
    assert _st(r, "extract_issues").state == "skipped"


@pytest.mark.parametrize(("iid", "text"), OFF_OVER, ids=[i for i, _ in OFF_OVER])
def test_offtopic_stopped_even_if_llm_says_uncertain(iid: str, text: str) -> None:
    """LLM이 범위 밖 글을 '판정 보류'라고 해도 멈춘다: 검색 근거가 약하면 검색에서, 검색이 모두 강하게 맞는
    최악의 경우에도 규칙 신호(무관한 글)로 진행 조건에서 멈춘다."""
    for backend in (_strong(), EverythingBackend(*build())):
        llm = live_like()
        r = _run(text, llm, backend=backend)
        assert r.risk_cards == [] and r.checklist == []
        assert "extract_issues" not in [c.task for c in llm.calls]
        gate = r.plan_checks.get("research_gate")
        if isinstance(backend, EverythingBackend):
            assert gate is not None and gate["passed"] is False and "rule_on_topic" in gate["failed_checks"]
            assert "진행 조건 미충족" in r.risk_synthesis["no_card_reason"]
        else:
            assert gate is None or gate["passed"] is False


@pytest.mark.parametrize(("iid", "text"), OFF_UNDER + OFF_OVER, ids=[i for i, _ in OFF_UNDER + OFF_OVER])
def test_offtopic_regression_default_mock(iid: str, text: str) -> None:
    llm = MockProvider(default_responders())
    r = _run(text, llm, backend=build_backend())
    assert r.risk_cards == [] and r.similar_works == []
    if input_length(text) < 300:  # 길이로 거절(호출 0)
        assert llm.calls == [] and r.risk_synthesis["no_card_reason"].startswith(TOO_SHORT_MESSAGE)
    else:  # 지금처럼 적합성 판정이 거절(호출 1)
        assert r.risk_synthesis["no_card_reason"].startswith("입력이 연구계획서가 아니다(")
        assert [c.task for c in llm.calls] == ["fitness"]


REJECT_PIPE = [REJECT[0], UNDER_300[0], KO_UNDER_300[7], *[(i, t) for i, e, t in LONG_SINGLE if e == "reject"]]


@pytest.mark.parametrize(("iid", "text"), REJECT_PIPE, ids=[i for i, _ in REJECT_PIPE])
def test_reject_tier_pipeline_makes_no_llm_call(iid: str, text: str) -> None:
    llm = live_like()
    r = _run(text, llm)
    assert llm.calls == []  # 적합성·검색어·추출·합성·v1 모두 부르지 않았다
    assert r.risk_cards == [] and r.similar_works == []
    assert r.plan_checks["input_quality"]["level"] == "reject"
    assert r.manifest["input_quality"]["status"] == "rejected_thin_input"
    msg = r.plan_checks["input_quality"]["message"]
    assert r.risk_synthesis["no_card_reason"] == f"{msg} (규칙 판정, LLM 호출 없음; 검색 안 함)"
    assert "연구 질문·방법·데이터·평가를 적어 주세요" in msg and msg in r.notices
    if input_length(text) < 300:
        assert msg == TOO_SHORT_MESSAGE
    st = _view(r)["_status"]
    assert st["input_quality"]["level"] == "reject" and st["label"].startswith("입력이 짧아 분석하지 않음")
    assert st["notices"][0] == msg and st["empty_reason"].startswith(msg)


def test_low_similarity_fallback_for_short_input() -> None:
    """경고 단계 입력이 점수 하한을 넘은 논문 0편이면 하한 없이 상위 k편을 '낮은 유사도'로 쓴다(표시)."""
    llm = live_like(fitness=lambda call: _reply("research_plan", {"method": [1], "data": [1]}))  # 적합(fit)
    r = _run(SHORT_BAT, llm, backend=FloorBackend(*build()))
    assert r.plan_checks["search"]["low_similarity"] is True and _st(r, "search").counts["low_similarity"] == 1
    assert r.similar_works and any("낮은 유사도" in n for n in r.notices)
    assert r.risk_cards  # 카드 0장으로 끝나지 않는다
    assert "낮은 유사도" in _view(r)["_status"]["label"]


def test_low_similarity_fallback_not_for_ok_tier_plans() -> None:
    r = _run(plan_text("plan.md"), MockProvider(default_responders()), backend=FloorBackend(*build()))
    assert r.risk_cards == [] and r.plan_checks["search"]["low_similarity"] is False
    assert r.risk_synthesis["no_card_reason"] == "유사 연구 검색 결과가 0건이다"


def test_field_level_cards_when_synthesis_returns_none() -> None:
    """짧은 입력에서 카드 합성이 0장이면 분야 수준 카드(규칙 합성)로 대신한다. LLM 결과라고 쓰지 않는다."""
    llm = live_like(synthesize_cards=lambda call: {"cards": [], "no_card_reason": "계획서 줄에 맞는 지적이 없다"})
    r = _run(SHORT_BAT, llm)
    assert 1 <= len(r.risk_cards) <= cards_mod.FIELD_MAX_CARDS
    for c in r.risk_cards:
        assert c.generator.value == "rule" and c.title.startswith("분야 공통 위험:")
        assert c.why_applies.plan_lines == [] and "규칙 합성" in c.why_applies.text
        assert len(c.evidence) >= cards_mod.MIN_EVIDENCE and len(c.works) >= cards_mod.MIN_WORKS
    st = _st(r, "synthesize_cards")
    assert st.state == "degraded" and st.impl == "fallback:cards.field_level_cards"
    assert r.status == "degraded" and _st(r, "verify_evidence").state == "ok"
    fl = r.risk_synthesis["field_level"]
    assert fl["used"] is True and fl["first_no_card_reason"].startswith("mock 판단: 계획서 줄에 맞는")
    assert any("분야 수준 카드" in n and "LLM 생성 아님" in n for n in r.notices)
    # 근거는 원문 구간 그대로(인용 문자열을 만들지 않는다)
    reviews = {rv.review_id: rv.text for rv in build()[1]}
    for ex in r.evidence:
        assert ex.verify_against(reviews[ex.source_id])
    view = _view(r)
    assert view["cards"] and view["_status"]["generators"] == {"rule": len(view["cards"])}


def test_no_field_level_cards_for_ok_tier_plans() -> None:
    llm = MockProvider({**default_responders(),
                        "synthesize_cards": lambda call: {"cards": [], "no_card_reason": "해당 없음"}})
    r = run_premortem(plan_text("plan.md"), llm=llm, backend=build_backend(), cache_dir=None)
    assert r.plan_checks["input_quality"]["level"] == "ok"
    assert r.risk_cards == [] and "field_level" not in r.risk_synthesis


def test_short_input_note_only_for_warn_tier() -> None:
    llm = live_like()
    _run(SHORT_BAT, llm)
    synth = [c for c in llm.calls if c.task == "synthesize_cards"]
    assert synth and cards_mod.SHORT_INPUT_NOTE in synth[0].instructions
    ok = MockProvider(default_responders())
    run_premortem(plan_text("plan.md"), llm=ok, backend=build_backend(), cache_dir=None)
    synth_ok = [c for c in ok.calls if c.task == "synthesize_cards"]
    assert synth_ok and cards_mod.SHORT_INPUT_NOTE not in synth_ok[0].instructions


def test_missing_fitness_module_keeps_old_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """적합성 모듈이 없으면 분량 단계도 없다: 검색어 단계 판정만으로 멈춘다(E3-L0 그대로)."""
    monkeypatch.setattr(pl, "_load_fitness", lambda: None)
    r = _run(SHORT_BAT, live_like())
    assert r.risk_cards == [] and "연구계획서가 아니다" in r.risk_synthesis["no_card_reason"]
    assert "input_quality" not in r.plan_checks and r.manifest["input_quality"]["level"] == "unknown"


# ── 4. 새 정규식: 적대 입력 0.2초 미만 ─────────────────────────────────────


ADVERSARIAL = [
    "." * 200_000,
    ". " * 100_000,
    "a." * 100_000,
    "\n" * 200_000,
    "!?" * 100_000 + "x",
    "this " * 40_000,
    "이는" * 100_000,
    "이 " * 100_000,
    ("가" * 50 + ". ") * 4_000,
]


@pytest.mark.parametrize("text", ADVERSARIAL, ids=[f"adv{i}" for i in range(len(ADVERSARIAL))])
def test_new_regexes_are_fast_on_adversarial_input(text: str) -> None:
    t0 = time.perf_counter()
    sentence_units(text)
    fit_mod._UNIT_SPLIT.split(text)
    fit_mod._DEMONSTRATIVE.match(text[:40])
    fit_mod._DEMONSTRATIVE.match(text)  # 앞 40자로 자르지 않아도 앞에 고정돼 있어 빠르다
    input_length(text)
    assert time.perf_counter() - t0 < 0.2


def test_demonstrative_pattern_is_anchored() -> None:
    assert fit_mod._DEMONSTRATIVE.match("This is important")
    assert fit_mod._DEMONSTRATIVE.match("이는 중요하다")
    assert not fit_mod._DEMONSTRATIVE.match("Thesis work on PDEs")  # 낱말 경계
    assert not fit_mod._DEMONSTRATIVE.match("We study this problem")  # 문장 앞에만
    assert re.compile(fit_mod._UNIT_SPLIT.pattern).split("A b c. D e f\nG") == ["A b c.", "D e f", "G"]
