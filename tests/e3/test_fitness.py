"""E3-L1c: 입력 적합성 판정 테스트(가짜 llm_call, 실제 API 없음)."""

from __future__ import annotations

import re
from typing import Any

import pytest

from neumann.analyze.fitness import (
    ELEMENTS,
    FITNESS_SCHEMA,
    assess_fitness,
    build_llm_input,
    detect_language,
    fitness_stage,
    rule_fitness,
)
from neumann.models import PlanDocument
from tests.fixtures.loader import DEMO_PLANS, NEGATIVE_PLAN, plan_text

SECTION_ELEMENT = {"1": "research_question", "2": "method", "3": "data", "4": "evaluation"}


def _plan(name_or_text: str) -> PlanDocument:
    text = plan_text(name_or_text) if name_or_text.endswith(".md") else name_or_text
    return PlanDocument.from_text(text, "sess-test")


def _section_lines(plan: PlanDocument) -> dict[str, list[int]]:
    """데모 계획서의 `## N.` 절 아래 줄을 요소별로 모은다(가짜 모델이 돌려줄 줄 번호)."""
    out: dict[str, list[int]] = {e: [] for e in ELEMENTS}
    current = None
    for ln in plan.lines:
        m = re.match(r"^##\s*(\d)\.", ln.text)
        if m:
            current = SECTION_ELEMENT.get(m.group(1))
            continue
        if current and ln.text.strip():
            out[current].append(ln.no)
    return out


def _response(verdict: str, lines: dict[str, list[int]] | None = None, *, field: str = "", reason: str = "사유") -> dict:
    lines = lines or {}
    return {
        "verdict": verdict,
        "elements": {e: {"present": bool(lines.get(e)), "plan_lines": lines.get(e, [])} for e in ELEMENTS},
        "field": field,
        "reason": reason,
    }


class FakeLLM:
    """llm_call 대역. 호출 인자를 기록하고 정해 둔 값을 돌려준다(callable이면 plan 입력으로 계산)."""

    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def __call__(self, schema: dict, instructions: str, input: str, *, effort: str) -> Any:  # noqa: A002
        self.calls.append({"schema": schema, "instructions": instructions, "input": input, "effort": effort})
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply(input) if callable(self.reply) else self.reply


# ── 완료 기준 1: 조리법 → 부적합, 데모 3건 → 적합 ─────────────────────────


@pytest.mark.parametrize("name", DEMO_PLANS)
def test_demo_plans_fit_via_llm(name: str) -> None:
    plan = _plan(name)
    fake = FakeLLM(_response("research_plan", _section_lines(plan), field="테스트 분야", reason="연구 요소가 모두 있다."))
    r = assess_fitness(plan, fake)
    assert r["verdict"] == "fit"
    assert r["analyze"] is True and r["is_research_plan"] is True
    assert r["generator"] == "astra" and r["model"] == "gpt-6-astra"
    assert r["status"] == "ok" and r["decided_by"] == "llm"
    assert r["missing"] == [] and r["notice"] is None
    assert r["field"] == "테스트 분야"
    assert r["language"] == "ko"
    assert len(fake.calls) == 1 and fake.calls[0]["schema"] is FITNESS_SCHEMA


def test_recipe_unfit_via_llm() -> None:
    plan = _plan(NEGATIVE_PLAN)
    fake = FakeLLM(_response("not_research_plan", reason="조리법이며 연구 질문·데이터·평가가 없다."))
    r = assess_fitness(plan, fake)
    assert r["verdict"] == "unfit"
    assert r["analyze"] is False and r["is_research_plan"] is False
    assert r["label_ko"] == "분석하지 않음"
    assert r["notice"] == "분석하지 않음: 조리법이며 연구 질문·데이터·평가가 없다."
    assert r["generator"] == "astra" and r["status"] == "ok"
    assert r["model_verdict"] == "not_research_plan"


@pytest.mark.parametrize("name", DEMO_PLANS)
def test_demo_plans_fit_via_rule_fallback(name: str) -> None:
    r = assess_fitness(_plan(name), FakeLLM(None))
    assert r["verdict"] == "fit" and r["analyze"] is True
    assert r["generator"] == "rule" and r["model"] is None
    assert r["status"] == "degraded" and r["decided_by"] == "rule_fallback"
    assert r["degraded_reason"].startswith("llm_unavailable")
    assert all(r["elements"][e]["present"] for e in ELEMENTS)
    assert r["field"] is not None


def test_recipe_unfit_via_rule_fallback() -> None:
    r = assess_fitness(_plan(NEGATIVE_PLAN), FakeLLM(None))
    assert r["verdict"] == "unfit" and r["analyze"] is False
    assert r["generator"] == "rule" and r["status"] == "degraded"
    assert r["notice"].startswith("분석하지 않음:")
    assert r["rule"]["offtopic_hits"] >= 2 and r["rule"]["n_elements"] <= 1


def test_demo_fields_differ_by_rule() -> None:
    fields = {name: rule_fitness(_plan(name))["field"] for name in DEMO_PLANS}
    assert fields == {
        "plan.md": "재료·화학",
        "plan_elife_neuro.md": "신경과학·뇌영상",
        "plan_medimaging.md": "의료·의료영상",
    }


# ── 비상 경로: 예외·스키마 위반·깨진 JSON ─────────────────────────────────


def test_exception_falls_back_to_rule() -> None:
    r = assess_fitness(_plan("plan.md"), FakeLLM(TimeoutError("slow")))
    assert r["generator"] == "rule" and r["status"] == "degraded"
    assert r["degraded_reason"] == "llm_exception: TimeoutError"
    assert r["verdict"] == "fit"


@pytest.mark.parametrize(
    "bad",
    [
        {"verdict": "research_plan"},  # 필수 키 없음
        {**_response("maybe"), "verdict": "maybe"},  # enum 밖
        {**_response("research_plan"), "extra": 1},  # 추가 키
        ["not", "an", "object"],
    ],
)
def test_schema_violation_falls_back(bad: Any) -> None:
    r = assess_fitness(_plan("plan.md"), FakeLLM(bad))
    assert r["status"] == "degraded" and r["generator"] == "rule"
    assert r["degraded_reason"].startswith("schema_invalid")


def test_json_string_is_accepted_and_broken_json_falls_back() -> None:
    import json

    plan = _plan("plan.md")
    good = assess_fitness(plan, FakeLLM(json.dumps(_response("research_plan", _section_lines(plan)))))
    assert good["decided_by"] == "llm" and good["verdict"] == "fit"
    broken = assess_fitness(plan, FakeLLM('{"verdict": "research_plan",'))
    assert broken["status"] == "degraded" and broken["degraded_reason"].startswith("json_invalid")


def test_empty_reason_falls_back() -> None:
    plan = _plan("plan.md")
    r = assess_fitness(plan, FakeLLM(_response("research_plan", _section_lines(plan), reason="   ")))
    assert r["status"] == "degraded" and r["degraded_reason"].startswith("semantic_invalid")


def test_no_llm_call_is_degraded_rule() -> None:
    r = assess_fitness(_plan("plan.md"), None)
    assert r["generator"] == "rule" and r["status"] == "degraded"


# ── 줄 번호 검사·과잉 거절 방지 ───────────────────────────────────────────


def test_invalid_line_numbers_dropped_and_counted() -> None:
    plan = _plan("plan.md")
    lines = _section_lines(plan)
    lines["data"] = [999, -1, 2]  # 범위 밖·음수·빈 줄(2번은 빈 줄)
    r = assess_fitness(plan, FakeLLM(_response("research_plan", lines)))
    assert r["checks"]["dropped_lines"] == 3
    assert r["elements"]["data"] == {"present": False, "plan_lines": []}
    assert r["missing"] == ["data"]
    assert r["verdict"] == "fit"  # 나머지 세 요소는 근거 줄이 있다


def test_model_rejection_of_real_plan_is_softened() -> None:
    """모델이 진짜 계획서를 '연구 아님'이라 해도 규칙 신호가 강하면 거절하지 않는다(ID-97)."""
    r = assess_fitness(_plan("plan_elife_neuro.md"), FakeLLM(_response("not_research_plan")))
    assert r["verdict"] == "uncertain" and r["analyze"] is True
    assert r["checks"]["overrides"] and "거절하지 않는다" in r["checks"]["overrides"][0]
    assert r["notice"].startswith("연구계획서인지 확실하지 않아")
    assert len(r["followup_questions"]) == 4  # 모델이 요소를 하나도 안 짚었으니 전부 보완 질문


def test_thin_idea_is_uncertain_with_followups() -> None:
    text = "그래프 신경망으로 전해액 이온전도도를 예측해 보려는 아이디어를 구상 중이다.\n아직 세부 계획은 정하지 않았다."
    plan = _plan(text)
    rule = rule_fitness(plan)
    assert rule["verdict"] == "uncertain"
    r = assess_fitness(plan, FakeLLM(_response("research_plan", {"research_question": [1]})))
    assert r["verdict"] == "uncertain" and r["analyze"] is True
    assert r["missing"] == ["method", "data", "evaluation"]
    assert [q["element"] for q in r["followup_questions"]] == ["method", "data", "evaluation"]
    assert r["checks"]["overrides"]


def test_model_uncertain_is_uncertain() -> None:
    plan = _plan("plan.md")
    r = assess_fitness(plan, FakeLLM(_response("uncertain", _section_lines(plan))))
    assert r["verdict"] == "uncertain" and r["analyze"] is True


def test_english_abstract_fit_by_rule_and_language() -> None:
    text = (
        "We propose a transformer model that predicts protein stability from sequence.\n"
        "We train it on 50,000 variants collected from public datasets.\n"
        "We evaluate Spearman correlation and RMSE against three published baselines with 5-fold cross-validation."
    )
    plan = _plan(text)
    assert rule_fitness(plan)["verdict"] == "fit"
    assert detect_language(plan.text)["language"] == "en"
    r = assess_fitness(plan, FakeLLM(None))
    assert r["verdict"] == "fit" and r["language"] == "en"


def test_english_recipe_unfit_by_rule() -> None:
    text = (
        "Easy banana bread recipe\n"
        "Ingredients: 3 ripe bananas, 2 tablespoons butter, 1 teaspoon baking soda, 1 cup sugar.\n"
        "Preheat the oven to 175C. Mash the bananas, mix in the butter, and bake for 60 minutes.\n"
        "Makes 8 servings."
    )
    r = assess_fitness(_plan(text), FakeLLM(None))
    assert r["verdict"] == "unfit" and r["analyze"] is False


def test_too_short_is_precheck_without_call() -> None:
    fake = FakeLLM(_response("research_plan"))
    r = assess_fitness(_plan("안녕하세요"), fake)
    assert r["verdict"] == "unfit" and r["decided_by"] == "precheck"
    assert r["generator"] == "rule" and r["status"] == "ok"
    assert fake.calls == []


# ── 모델 입력·출력의 개인정보, 정직 표기 ─────────────────────────────────


def test_llm_input_is_masked_and_numbered() -> None:
    raw = plan_text("plan.md") + "\n책임자 연락처 010-1234-5678, pi@lab.ac.kr"
    plan = PlanDocument.from_text(raw, "s")  # models 기본 마스킹은 이메일만 가린다
    assert "010-1234-5678" in plan.text
    fake = FakeLLM(_response("research_plan", _section_lines(plan)))
    r = assess_fitness(plan, fake, effort="medium")
    sent = fake.calls[0]["input"]
    assert "010-1234-5678" not in sent and "[PHONE]" in sent
    assert "5: 리튬이온 배터리" in sent  # 줄 번호: 본문
    assert "\n2: " not in sent  # 빈 줄은 뺀다
    assert fake.calls[0]["effort"] == "medium"
    assert r["checks"]["pii_masked"] == {"phone": 1}


def test_llm_reason_and_field_are_masked() -> None:
    plan = _plan("plan.md")
    reply = _response("research_plan", _section_lines(plan), field="배터리 x@y.com", reason="문의 010-1234-5678. 연구계획서다.")
    r = assess_fitness(plan, FakeLLM(reply))
    assert r["reason"] == "문의 [PHONE]. 연구계획서다."
    assert r["field"] == "배터리 [EMAIL]"


def test_build_llm_input_truncates() -> None:
    plan = _plan("plan.md")
    text, meta = build_llm_input(plan, max_chars=200)
    assert meta["truncated"] is True and len(text) < 400
    assert f"truncated after line {meta['last_line_sent']}" in text


def test_generator_label_is_honest() -> None:
    plan = _plan("plan.md")
    r = assess_fitness(plan, FakeLLM(_response("research_plan", _section_lines(plan))), generator="mock", model="mock-v1")
    assert r["generator"] == "mock" and r["model"] == "mock-v1"
    with pytest.raises(ValueError):
        assess_fitness(plan, FakeLLM(None), generator="gpt")


def _strict_problems(schema: dict, path: str = "$") -> list[str]:
    problems = []
    if schema.get("type") == "object":
        if schema.get("additionalProperties") is not False:
            problems.append(f"{path}: additionalProperties")
        if sorted(schema.get("required", [])) != sorted(schema.get("properties", {})):
            problems.append(f"{path}: required")
        for k, sub in schema.get("properties", {}).items():
            problems += _strict_problems(sub, f"{path}.{k}")
    if schema.get("type") == "array":
        problems += _strict_problems(schema["items"], f"{path}[]")
    return problems


def test_schema_is_openai_strict_compatible() -> None:
    assert _strict_problems(FITNESS_SCHEMA) == []


def test_fitness_stage_records_degradation() -> None:
    plan = _plan("plan.md")
    ok = fitness_stage(assess_fitness(plan, FakeLLM(_response("research_plan", _section_lines(plan)))))
    assert ok.state == "ok" and ok.stage == "fitness" and ok.impl == "neumann.analyze.fitness:assess_fitness"
    assert ok.counts["elements_present"] == 4
    bad = fitness_stage(assess_fitness(plan, FakeLLM(None)))
    assert bad.state == "degraded" and bad.impl == "fallback:rule_fitness"
    assert "llm_unavailable" in bad.detail
    dumped = bad.model_dump(mode="json")
    assert dumped["name"] == "fitness" and dumped["status"] == "degraded"
