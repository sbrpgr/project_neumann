"""llm.py: JSON 스키마 요청 → 로컬 재검증 한 경로, 실패는 예외 대신 결과, 비밀값 비노출."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from neumann.analyze import cards, extract, queries
from neumann.llm import (
    DisabledProvider,
    LLMCall,
    MockProvider,
    OpenAIProvider,
    check_strict_schema,
    make_llm,
    task_options,
    validate_output,
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"n": {"type": "integer"}, "tag": {"type": "string", "enum": ["a", "b"]}},
    "required": ["n", "tag"],
}
FAKE_KEY = "fake-test-key"  # 실제 키 아님


def _call(**kw) -> LLMCall:
    return LLMCall(task=kw.pop("task", "t"), instructions="x", payload={"q": 1}, schema=SCHEMA, schema_name="s", **kw)


class _FakeResponses:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.kwargs: list[dict] = []

    def create(self, **kwargs):
        self.kwargs.append(kwargs)
        b = self.behaviour.pop(0) if isinstance(self.behaviour, list) else self.behaviour
        if isinstance(b, Exception):
            raise b
        return b


class _FakeClient:
    def __init__(self, behaviour):
        self.responses = _FakeResponses(behaviour)
        self.timeouts: list[float] = []

    def with_options(self, timeout):
        self.timeouts.append(timeout)
        return self


def _resp(text, status="completed"):
    return SimpleNamespace(
        output_text=text, status=status, incomplete_details=None,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15, output_tokens_details=None),
    )


def _req():
    return httpx.Request("POST", "https://api.openai.com/v1/responses")


# ── 로컬 재검증 ──────────────────────────────────────────────────────────


def test_validate_output_accepts_valid():
    data, err, _ = validate_output('{"n": 1, "tag": "a"}', SCHEMA)
    assert err is None and data == {"n": 1, "tag": "a"}


@pytest.mark.parametrize(
    "text, err",
    [
        ("", "empty_output"),
        ("{not json", "json_invalid"),
        ("[1,2]", "schema_invalid"),
        ('{"n": 1, "tag": "z"}', "schema_invalid"),  # enum 밖
        ('{"n": 1}', "schema_invalid"),  # 필수 누락
        ('{"n": 1, "tag": "a", "extra": 1}', "schema_invalid"),  # 추가 키 밀반입
    ],
)
def test_validate_output_rejects(text, err):
    data, e, detail = validate_output(text, SCHEMA)
    assert data is None and e == err and detail


def test_all_product_schemas_are_strict():
    """OpenAI strict 모드 요건(모든 객체 additionalProperties=false, 모든 속성 required)을 지킨다."""
    for schema in (queries.SCHEMA, extract.build_schema(["s1", "s2"]), cards.build_schema(["E1"])):
        assert check_strict_schema(schema) == []
    assert check_strict_schema({"type": "object", "properties": {"a": {"type": "string"}}, "required": []})


# ── OpenAI provider (가짜 클라이언트) ─────────────────────────────────────


def test_openai_success_sends_schema_effort_no_temperature():
    client = _FakeClient(_resp('{"n": 2, "tag": "b"}'))
    p = OpenAIProvider(api_key=None, model="gpt-6-astra", client=client)
    res = p.complete_json(_call(effort="low", timeout_s=12))
    assert res.ok and res.data == {"n": 2, "tag": "b"} and res.generator == "astra"
    kw = client.responses.kwargs[0]
    assert kw["model"] == "gpt-6-astra"
    assert kw["text"]["format"]["type"] == "json_schema" and kw["text"]["format"]["strict"] is True
    assert kw["reasoning"] == {"effort": "low"}
    assert "temperature" not in kw and "max_tokens" not in kw
    assert json.loads(kw["input"]) == {"q": 1}
    assert client.timeouts[0] <= 12
    assert res.usage["output_tokens"] == 5


def test_openai_schema_violation_is_failure_not_exception():
    p = OpenAIProvider(api_key=None, model="gpt-6-astra", client=_FakeClient(_resp('{"n": "x", "tag": "a"}')))
    res = p.complete_json(_call())
    assert not res.ok and res.error == "schema_invalid"


def test_openai_timeout_is_failure():
    p = OpenAIProvider(api_key=None, model="gpt-6-astra", client=_FakeClient(openai.APITimeoutError(request=_req())))
    res = p.complete_json(_call(timeout_s=3))
    assert not res.ok and res.error == "timeout" and "3s" in res.detail


def test_openai_http_error_is_failure_and_hides_key():
    err = openai.BadRequestError(
        "bad", response=httpx.Response(400, request=_req()), body={"error": {"message": "Unsupported parameter"}}
    )
    p = OpenAIProvider(api_key=None, model="gpt-6-astra", client=_FakeClient(err))
    res = p.complete_json(_call())
    assert not res.ok and res.error == "api_error" and "400" in res.detail
    assert FAKE_KEY not in res.reason()


def test_openai_retries_transient_once():
    transient = openai.InternalServerError("x", response=httpx.Response(500, request=_req()), body=None)
    client = _FakeClient([transient, _resp('{"n": 3, "tag": "a"}')])
    p = OpenAIProvider(api_key=None, model="gpt-6-astra", client=client)
    res = p.complete_json(_call(timeout_s=60))
    assert res.ok and res.attempts == 2


def test_openai_incomplete_is_failure():
    p = OpenAIProvider(api_key=None, model="gpt-6-astra", client=_FakeClient(_resp("", status="incomplete")))
    res = p.complete_json(_call())
    assert not res.ok and res.error == "incomplete"


def test_empty_model_is_loud_config_error():
    """모델명이 비면 조용히 꺼지지 않고 호출마다 config_error로 드러난다."""
    p = OpenAIProvider(api_key=FAKE_KEY, model="")
    res = p.complete_json(_call())
    assert not res.ok and res.error == "config_error" and "NEUMANN_LLM_MODEL" in res.detail


def test_missing_key_is_loud_config_error():
    p = OpenAIProvider(api_key="", model="gpt-6-astra")
    res = p.complete_json(_call())
    assert not res.ok and res.error == "config_error"


def test_provider_state_does_not_expose_key():
    """provider 속성·repr에 키 문자열이 평문으로 남지 않는다(키는 SDK 클라이언트 안에만)."""
    p = OpenAIProvider(api_key=FAKE_KEY, model="gpt-6-astra")
    assert FAKE_KEY not in repr(p)
    assert FAKE_KEY not in repr({k: v for k, v in vars(p).items()})


# ── mock · off · 설정 ────────────────────────────────────────────────────


def test_mock_scripted_fail_and_revalidation():
    m = MockProvider(
        {"t": lambda c: {"n": 1, "tag": "a"}},
        scripted={"t": ['{"n": 1, "tag": "q"}']},  # 첫 응답은 enum 밖 → 재검증에서 실패
        fail={"dead": "timeout"},
    )
    assert m.complete_json(_call()).error == "schema_invalid"
    ok = m.complete_json(_call())
    assert ok.ok and ok.generator == "mock"
    assert m.complete_json(_call(task="dead")).error == "timeout"
    assert m.complete_json(_call(task="unknown")).error == "config_error"


def test_disabled_provider():
    res = DisabledProvider().complete_json(_call())
    assert not res.ok and res.error == "disabled" and res.generator == "rule"


def test_make_llm_selects_provider(monkeypatch):
    assert make_llm(provider="off").name == "off"
    assert make_llm(provider="mock").name == "mock"
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "1")  # 실제 클라이언트는 키가 없어 만들지 않는다
    s = SimpleNamespace(llm_provider="openai", llm_model="gpt-6-astra", openai_api_key=None, llm_timeout_s=5.0)
    p = make_llm(s, provider="openai")
    assert p.name == "openai" and p.model == "gpt-6-astra"


def test_task_options_per_call_effort(monkeypatch):
    assert task_options("query_axes")["effort"] == "low"
    assert task_options("synthesize_cards")["effort"] == "medium"
    monkeypatch.setenv("NEUMANN_LLM_EFFORT_EXTRACT_ISSUES", "high")
    monkeypatch.setenv("NEUMANN_LLM_TIMEOUT_EXTRACT_ISSUES_S", "7")
    assert task_options("extract_issues") == {"effort": "high", "timeout_s": 7.0}
    monkeypatch.setenv("NEUMANN_LLM_EFFORT_QUERY_AXES", "bogus")
    assert task_options("query_axes")["effort"] == "low"
