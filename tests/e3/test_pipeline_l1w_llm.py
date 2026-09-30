"""E3-L1w: provider의 생성 주체 속성(추정 금지)과 v1 단계 호출 상한(llm.py)."""

from __future__ import annotations

import pytest

from neumann.analyze.mock_responders import default_responders
from neumann.llm import (
    PROVIDER_GENERATOR,
    TASK_DEFAULTS,
    DisabledProvider,
    MockProvider,
    OpenAIProvider,
    make_llm,
    provider_generator,
    task_options,
)

V1_TASKS = ("fitness", "expected_review", "checklist", "semantic_validate")


class AstraLike(MockProvider):
    """응답은 결정적이지만 이름은 openai(생성 주체 astra)인 시험용 provider."""

    name = "openai"


def test_provider_generator_attribute_follows_name_mapping():
    assert PROVIDER_GENERATOR == {"openai": "astra", "mock": "mock", "off": "rule"}
    astra = OpenAIProvider(api_key=None, model="gpt-6-astra", client=object())
    assert astra.generator == "astra" and provider_generator(astra) == "astra"
    assert MockProvider().generator == "mock" and provider_generator(MockProvider()) == "mock"
    assert DisabledProvider().generator == "rule" and provider_generator(DisabledProvider()) == "rule"
    # 이름만 openai인 시험용 하위 클래스는 LLMResult.generator(이름 기준)와 같게 astra
    assert AstraLike().generator == "astra"
    assert make_llm(None, "mock").generator == "mock"
    assert make_llm(None, "off").generator == "rule"


def test_provider_generator_refuses_to_guess():
    class Unknown:
        name, model = "boom", "x"

    class BadAttr:
        name, model, generator = "openai", "x", "gpt"

    with pytest.raises(ValueError, match="생성 주체"):
        provider_generator(Unknown())
    with pytest.raises(ValueError):
        provider_generator(BadAttr())

    class NamedOnly:  # 속성은 없지만 이름 대응이 있으면 그 대응을 쓴다
        name, model = "mock", "m"

    assert provider_generator(NamedOnly()) == "mock"


def test_v1_tasks_have_time_limits_and_efforts():
    for task in V1_TASKS:
        assert task in TASK_DEFAULTS
        opts = task_options(task)
        assert opts["timeout_s"] > 0 and opts["effort"] in ("low", "medium", "high")
    assert task_options("fitness") == {"effort": "low", "timeout_s": 30.0}
    assert task_options("checklist")["effort"] == "medium"


def test_v1_task_limits_can_be_overridden(monkeypatch):
    monkeypatch.setenv("NEUMANN_LLM_TIMEOUT_CHECKLIST_S", "12")
    monkeypatch.setenv("NEUMANN_LLM_EFFORT_EXPECTED_REVIEW", "low")
    assert task_options("checklist")["timeout_s"] == 12.0
    assert task_options("expected_review")["effort"] == "low"


def test_default_mock_responders_cover_v1_tasks():
    responders = default_responders()
    for task in (*V1_TASKS, "query_axes", "extract_issues", "synthesize_cards"):
        assert callable(responders[task])
