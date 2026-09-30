"""E3-L1c: 입력 적합성 판정 테스트(가짜 llm_call, 실제 API 없음)."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
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
    """llm_call 대역. 호출 인자를 기록하고 정해 둔 값을 돌려준다(callable이면 plan 입력으로 계산).

    생성 주체를 정직하게 밝히는 `generator`·`model` 속성을 단다(astra가 아니다).
    """

    generator = "mock"
    model = "mock-fitness"

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
    assert r["generator"] == "mock" and r["model"] == "mock-fitness"  # llm_call 속성에서 읽는다
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
    assert r["generator"] == "mock" and r["status"] == "ok"
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
    stage = fitness_stage(r)
    assert stage.counts["overrides"] == 1 and "not_research_plan → uncertain" in stage.detail


def test_thin_idea_is_uncertain_with_followups() -> None:
    short = "그래프 신경망으로 전해액 이온전도도를 예측해 보려는 아이디어를 구상 중이다.\n아직 세부 계획은 정하지 않았다."
    # E3-L1s(대표 지시): 300자 미만은 호출 없이 거절한다. 300자 이상인 얇은 아이디어로 판정 보류를 시험한다.
    fake = FakeLLM(_response("research_plan", {"research_question": [1]}))
    rej = assess_fitness(_plan(short), fake)
    assert rej["decided_by"] == "precheck" and rej["verdict"] == "unfit" and fake.calls == []
    text = short + (
        "\n배터리 전해액은 용매와 염의 조합이 많아서 하나씩 만들어 재 보는 데 시간이 오래 걸린다."
        "\n그래서 컴퓨터로 먼저 걸러 낼 수 있으면 좋겠다는 생각을 했다."
        "\n주변 연구실에서도 비슷한 이야기를 들었고, 관련 논문을 몇 편 읽어 보는 중이다."
        "\n다음 달 연구실 회의에서 이 아이디어를 공유하고 여러 사람의 의견을 들어 볼 생각이다."
        "\n의견이 모이면 무엇부터 할지 순서를 정하고, 필요한 도구와 일정도 함께 정리해 보겠다."
        "\n지도교수님과도 한 번 상의해서 이 주제가 학위 논문 주제로 괜찮은지 여쭤볼 예정이다."
    )
    assert len(text.strip()) >= 300
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
        "We evaluate Spearman correlation and RMSE against three published baselines with 5-fold cross-validation.\n"
        "Variants are grouped by protein so that no protein appears in both the training and the test folds."
    )  # E3-L1s: 300자 미만은 거절 단계라 한 줄을 더해 300자를 넘겼다
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
    payload = json.loads(sent)  # provider 어댑터가 JSON payload로 읽을 수 있어야 한다
    rows = payload["plan"].split("\n")
    assert "010-1234-5678" not in sent and "[PHONE]" in payload["plan"]
    assert f"5: {plan.line(5)}" in rows and plan.line(5).startswith("리튬이온 배터리")  # 줄 번호: 본문
    assert not any(row.startswith("2: ") for row in rows)  # 빈 줄은 뺀다
    assert payload["n_lines"] == len(plan.lines) and payload["truncated_after_line"] is None
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
    payload = json.loads(text)
    assert meta["truncated"] is True and len(payload["plan"]) <= 200
    assert payload["truncated_after_line"] == meta["last_line_sent"]


def test_generator_label_is_honest() -> None:
    plan = _plan("plan.md")
    r = assess_fitness(plan, FakeLLM(_response("research_plan", _section_lines(plan))), generator="astra", model="m-1")
    assert r["generator"] == "astra" and r["model"] == "m-1"  # 인자가 속성보다 우선
    with pytest.raises(ValueError):
        assess_fitness(plan, FakeLLM(None), generator="gpt")


def test_bare_callable_without_generator_is_rejected_before_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """생성 주체를 모르는 callable은 설정이 openai여도 astra로 추정하지 않고 호출 전에 거부한다."""
    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    plan = _plan("plan.md")
    calls: list[str] = []

    def bare(schema: dict, instructions: str, input: str, *, effort: str) -> dict:  # noqa: A002
        calls.append(input)
        return _response("research_plan", _section_lines(plan))

    with pytest.raises(ValueError, match="생성 주체"):
        assess_fitness(plan, bare)
    assert calls == []
    with pytest.raises(ValueError, match="생성 주체"):  # 짧은 입력(호출 안 하는 경로)도 같은 규칙
        assess_fitness(_plan("안녕하세요"), bare)
    bare.generator = "bogus"  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="llm_call.generator"):
        assess_fitness(plan, bare)
    assert calls == []
    r = assess_fitness(plan, None)  # 호출이 없으면 생성 주체도 필요 없다(규칙 경로)
    assert r["generator"] == "rule"


def test_generator_and_model_from_attributes() -> None:
    plan = _plan("plan.md")

    def call(schema: dict, instructions: str, input: str, *, effort: str) -> dict:  # noqa: A002
        return _response("research_plan", _section_lines(plan))

    call.generator = "astra"  # type: ignore[attr-defined]
    r = assess_fitness(plan, call)
    assert r["generator"] == "astra" and r["model"] is None  # 모델 id는 추정하지 않는다
    call.model = "gpt-6-astra"  # type: ignore[attr-defined]
    assert assess_fitness(plan, call)["model"] == "gpt-6-astra"


class _FakeProvider:
    """E3-L0 provider 모양(`name`, `model`, `complete_json(call) -> result`)의 대역."""

    def __init__(self, name: str, data: dict | None, error: str | None = None) -> None:
        self.name, self.model, self.data, self.error = name, f"{name}-model", data, error
        self.calls: list[Any] = []

    def complete_json(self, call: Any) -> Any:
        self.calls.append(call)
        gen = {"openai": "astra", "mock": "mock"}.get(self.name, "rule")
        return SimpleNamespace(ok=self.data is not None, data=self.data, model=self.model, generator=gen,
                               error=self.error, reason=lambda: f"{self.name}:{self.model} {self.error}")


def test_works_with_provider_llm_call_adapter() -> None:
    """main의 review.provider_llm_call로 감싼 provider를 그대로 넘길 수 있다(생성 주체는 provider 이름에서)."""
    from neumann.analyze.review import provider_llm_call

    plan = _plan("plan.md")
    prov = _FakeProvider("mock", _response("research_plan", _section_lines(plan)))
    r = assess_fitness(plan, provider_llm_call(prov, task="input_fitness"))
    assert r["decided_by"] == "llm" and r["verdict"] == "fit"
    assert r["generator"] == "mock" and r["model"] == "mock-model"
    call = prov.calls[0]
    assert call.task == "input_fitness" and call.schema is FITNESS_SCHEMA and "plan" in call.payload

    failing = _FakeProvider("openai", None, error="timeout")
    r2 = assess_fitness(plan, provider_llm_call(failing, task="input_fitness"))
    assert r2["status"] == "degraded" and r2["generator"] == "rule"
    assert "timeout" in r2["degraded_reason"]


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
