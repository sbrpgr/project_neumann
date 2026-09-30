"""예상 심사평(E3-L1a) 테스트. llm_call은 가짜 callable로 주입한다(실제 API 없음)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from neumann.analyze import gate as g
from neumann.analyze.gate import verify_expected_review
from neumann.analyze.review import (
    REVIEW_INSTRUCTIONS,
    ProviderLLMCall,
    attach_expected_review,
    build_review_prompt,
    expected_review_stage,
    generate_expected_review,
    rule_review_drafts,
)
from neumann.models import PremortemResult
from tests.fixtures.loader import load_fixtures

ROOT = Path(__file__).resolve().parents[2]
LEAK, SEED = "card-fx-leak", "card-fx-seed"
EX_LEAK = "ex_110f92f3599151f1"


@pytest.fixture(scope="module")
def fx():
    return load_fixtures()


@pytest.fixture()
def result(fx) -> PremortemResult:
    return fx.premortem_result.model_copy(deep=True)


class FakeCall:
    """가짜 llm_call. 받은 인자를 기록하고 정해진 응답(또는 함수 결과)을 돌려준다."""

    def __init__(self, response: Any = None, *, raises: Exception | None = None, generator: str | None = None) -> None:
        self.response = response
        self.raises = raises
        self.calls: list[dict[str, Any]] = []
        if generator:
            self.generator = generator

    def __call__(self, schema, instructions, input, *, effort):  # noqa: A002
        self.calls.append({"schema": schema, "instructions": instructions, "input": input, "effort": effort})
        if self.raises:
            raise self.raises
        return self.response(schema, input) if callable(self.response) else self.response


def aliases(input_text: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """입력 JSON에서 카드 별칭 → risk_code, 카드 별칭 → 근거 별칭 목록."""
    payload = json.loads(input_text)
    return (
        {c["id"]: c["risk_code"] for c in payload["cards"]},
        {c["id"]: [e["id"] for e in c["evidence"]] for c in payload["cards"]},
    )


def s(text, ex, cards=(), lines=()):
    return {"text": text, "excerpt_ids": list(ex), "card_ids": list(cards), "plan_lines": list(lines)}


def mixed_response(schema, input_text):
    """좋은 문장 + 근거 없는 문장 + 없는 id + 인용 불일치 + 없는 수치."""
    code, ev = aliases(input_text)
    c_leak = next(k for k, v in code.items() if v == "R3")
    c_seed = next(k for k, v in code.items() if v == "R2")
    return {
        "strength": [s("계획서는 평가 지표를 미리 정했다 (21행).", [ev[c_seed][0]], [c_seed], [21])],
        "weakness": [
            s("무작위 분할과 중복 미제거는 시험 성능을 과대평가할 수 있다 (16–17행).", ev[c_leak][:2], [c_leak], [16, 17]),
            s("대부분의 전해질 연구가 이 문제를 겪는다.", [], []),  # 근거 없음
            s("시드 하나로는 개선을 판단할 수 없다.", ["E99"], [c_seed]),  # 없는 id
            s('리뷰어는 "random splits always leak everything"이라고 했다.', ev[c_leak][:1], [c_leak]),  # 인용 불일치
            s("이 설계로는 R² 0.95 이상을 달성하기 어렵다.", ev[c_seed][:1], [c_seed]),  # 없는 수치
        ],
        "request": [s("여러 시드로 반복 학습하고 오차막대를 보고할 것 (22행).", ev[c_seed][:2], [c_seed], [22])],
    }


# ── LLM 경로 ─────────────────────────────────────────────────────────────


def test_llm_path_keeps_only_grounded_sentences(result):
    call = FakeCall(mixed_response)
    review = generate_expected_review(result, call, generator="astra", model="gpt-6-astra")
    assert len(call.calls) == 1
    assert review["generator"] == "astra" and review["model"] == "gpt-6-astra" and review["status"] == "ok"
    assert [x["t"] for x in review["weakness"]] == ["무작위 분할과 중복 미제거는 시험 성능을 과대평가할 수 있다 (16–17행)."]
    assert len(review["strength"]) == 1 and len(review["request"]) == 1
    audit = review["audit"]
    assert audit["gen"] == 7 and audit["pass"] == 3 and audit["drop"] == 4
    assert audit["reasons"] == {g.MISSING_CITATION: 1, g.UNKNOWN_EXCERPT: 1, g.QUOTE_MISMATCH: 1, g.FABRICATED_NUMBER: 1}
    assert all(len(p) == 2 for p in audit["dropped"])
    # 별칭(C1·E1)은 실제 id로 풀려 있다
    ids = {e.excerpt_id for e in result.evidence}
    for sec in ("strength", "weakness", "request"):
        for sent in review[sec]:
            assert sent["c"] and set(sent["c"]) <= ids
            assert set(sent["cards"]) <= {LEAK, SEED}
    # 다시 검사해도 전부 통과(근거 없는 문장 0)
    assert not verify_expected_review(review, result).dropped


def test_llm_receives_schema_instructions_input_and_effort(result):
    call = FakeCall(mixed_response)
    generate_expected_review(result, call, effort="high", generator="astra")
    (c,) = call.calls
    assert c["effort"] == "high" and c["instructions"] == REVIEW_INSTRUCTIONS
    payload = json.loads(c["input"])
    assert {card["risk_code"] for card in payload["cards"]} == {"R2", "R3"}
    assert all(e["text"] for card in payload["cards"] for e in card["evidence"])
    assert payload["plan"]["lines"][0]["no"] == 1
    schema = c["schema"]
    # OpenAI strict 호환: 모든 객체 additionalProperties=false, required = 모든 속성
    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert sorted(node["required"]) == sorted(node["properties"])
            for sub in node["properties"].values():
                walk(sub)
        if node.get("type") == "array":
            walk(node["items"])
    walk(schema)
    sent = schema["properties"]["weakness"]["items"]
    assert "quote" not in json.dumps(sent)  # 인용문 필드 없음
    assert set(sent["properties"]["excerpt_ids"]["items"]["enum"]) == set(build_review_prompt(result).excerpt_alias)
    # 모델이 real id를 그대로 돌려줘도 받아 준다(별칭 enum 밖이지만 결과 안에 있는 id)
    call2 = FakeCall({"strength": [], "weakness": [s("누출 위험.", [EX_LEAK], [LEAK])], "request": []})
    review = generate_expected_review(result, call2, generator="astra")
    assert review["weakness"][0]["c"] == [EX_LEAK]


def test_quotes_are_never_taken_from_model_but_verified(fx, result):
    ex = fx.excerpt(EX_LEAK)

    def resp(schema, input_text):
        code, ev = aliases(input_text)
        c = next(k for k, v in code.items() if v == "R3")
        e_alias = next(a for a in ev[c] if build_review_prompt(result).excerpt_alias[a] == EX_LEAK)
        return {"strength": [], "request": [],
                "weakness": [s(f"리뷰어는 “{ex.text}”라고 썼다.", [e_alias], [c])]}

    review = generate_expected_review(result, FakeCall(resp), generator="astra")
    (q,) = review["weakness"][0]["quotes"]
    assert fx.source_text(ex)[q["start"] : q["end"]] == q["text"] == ex.text


# ── 비상 경로(규칙 합성) ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("call", "reason_prefix"),
    [
        (None, "llm_call_not_provided"),
        (FakeCall(None), "llm_call_failed"),
        (FakeCall(raises=TimeoutError("slow")), "llm_call_exception: TimeoutError"),
        (FakeCall({"weakness": "not a list"}), "llm_output_schema_invalid"),
        (FakeCall({"strength": [], "weakness": [], "request": []}), "llm_empty_output"),
    ],
)
def test_failure_falls_back_to_rule_and_says_so(result, call, reason_prefix):
    review = generate_expected_review(result, call, generator="astra")
    assert review["generator"] == "rule" and review["model"] is None
    assert review["status"] == "degraded"
    assert review["reason"].startswith(reason_prefix)
    assert review["weakness"] and review["request"]
    assert review["strength"] == []  # 규칙은 강점을 지어내지 않는다
    assert review["audit"]["drop"] == 0
    assert review["attempts"][-1]["generator"] == "rule"
    assert not verify_expected_review(review, result).dropped


def test_all_llm_sentences_dropped_falls_back_and_keeps_audit(result):
    bad = {"strength": [], "request": [],
           "weakness": [s("근거 없는 말.", []), s("없는 근거.", ["E404"])]}
    review = generate_expected_review(result, FakeCall(bad), generator="astra")
    assert review["generator"] == "rule" and review["status"] == "degraded"
    assert review["reason"].startswith("llm_all_sentences_dropped")
    audit = review["audit"]
    assert audit["reasons"] == {g.MISSING_CITATION: 1, g.UNKNOWN_EXCERPT: 1}
    assert audit["gen"] == audit["pass"] + audit["drop"]
    assert [a["generator"] for a in review["attempts"]] == ["astra", "rule"]
    assert review["attempts"][0]["outcome"] == "all_dropped"


def test_rule_sentences_quote_evidence_verbatim(fx, result):
    drafts = rule_review_drafts(result)
    rep = g.gate_sentences(drafts, result)
    assert not rep.dropped
    weak = [x for x in rep.passed if x["section"] == "weakness"]
    assert {x["cards"][0] for x in weak} == {LEAK, SEED}
    for x in weak:
        assert x["quotes"], x["t"]
        for q in x["quotes"]:
            ex = fx.excerpt(q["excerpt_id"])
            assert fx.source_text(ex)[q["start"] : q["end"]] == q["text"]


def test_rule_skips_quote_when_evidence_has_quote_marks(result):
    ev = result.evidence[1]
    src = 'A reviewer wrote "leaks" here and it is long enough.'
    from neumann.models import Excerpt

    new = Excerpt.from_source(src, 0, len(src), source_kind="review", source_id="rev-q", source_url=ev.source_url)
    card = result.risk_cards[0].model_copy(update={"evidence": [new.excerpt_id]})
    res = result.model_copy(update={"evidence": [*result.evidence, new], "risk_cards": [card]})
    rep = g.gate_sentences(rule_review_drafts(res), res)
    assert not rep.dropped and all(x["quotes"] == [] for x in rep.passed)


# ── 생략 · 표기 · 연결 ───────────────────────────────────────────────────


def test_no_cards_skips_without_calling_llm(result):
    empty = result.model_copy(update={"risk_cards": []})
    call = FakeCall(mixed_response, generator="astra")
    review = generate_expected_review(empty, call)
    assert call.calls == []
    assert review["status"] == "skipped" and review["generator"] is None and review["reason"]
    assert expected_review_stage(review).state == "skipped"


# ── 생성 주체 표기: 인자 또는 callable 속성에서만. 설정에서 추정하지 않는다 ─────


@pytest.fixture()
def provider_openai(monkeypatch):
    """conftest의 mock 강제와 무관하게, 설정 provider가 openai(기본값)인 상태를 만든다."""
    from neumann.config import get_settings

    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    get_settings.cache_clear()
    assert get_settings().llm_provider == "openai"
    yield
    get_settings.cache_clear()  # monkeypatch가 환경을 되돌린 뒤 다시 읽히게


OK_RESPONSE = {"strength": [], "request": [], "weakness": [s("누출 위험.", [EX_LEAK], [LEAK])]}


def test_bare_callable_is_rejected_before_call_even_when_provider_is_openai(result, provider_openai):
    call = FakeCall(OK_RESPONSE)  # generator 속성 없음
    with pytest.raises(ValueError, match="생성 주체"):
        generate_expected_review(result, call)
    assert call.calls == []  # 호출 전에 거부
    with pytest.raises(ValueError):
        attach_expected_review(result, call)
    with pytest.raises(ValueError):  # 카드가 없어도 사용 오류는 똑같이 거부
        generate_expected_review(result.model_copy(update={"risk_cards": []}), call)
    assert call.calls == []


@pytest.mark.parametrize("label", ["mock", "astra", "rule"])
def test_callable_attribute_is_used_as_is(result, provider_openai, label):
    call = FakeCall(OK_RESPONSE, generator=label)
    review = generate_expected_review(result, call)
    assert review["generator"] == label and review["generator_source"] == "llm_call"
    assert review["model"] is None  # model 속성이 없으면 설정에서 채우지 않는다
    call.model = "some-model"
    assert generate_expected_review(result, call)["model"] == "some-model"


def test_explicit_argument_wins_and_bad_values_are_rejected(result, provider_openai):
    review = generate_expected_review(result, FakeCall(OK_RESPONSE, generator="mock"), generator="astra", model="m1")
    assert review["generator"] == "astra" and review["model"] == "m1" and review["generator_source"] == "param"
    for bad in (FakeCall(OK_RESPONSE, generator="gpt"),):
        with pytest.raises(ValueError):
            generate_expected_review(result, bad)
        assert bad.calls == []
    with pytest.raises(ValueError):
        generate_expected_review(result, FakeCall(OK_RESPONSE), generator="llm")


def test_no_llm_call_needs_no_label_and_is_rule(result, provider_openai):
    review = generate_expected_review(result, None)
    assert review["generator"] == "rule" and review["model"] is None and review["status"] == "degraded"


def test_review_matches_ui_contract_and_result_contract(result):
    ui = json.loads((ROOT / "contracts" / "ui_view.schema.json").read_text(encoding="utf-8"))
    review_schema = {"$schema": ui["$schema"], **ui["properties"]["review"], "definitions": ui["definitions"]}
    api = json.loads((ROOT / "contracts" / "premortem_response.schema.json").read_text(encoding="utf-8"))
    for call in (FakeCall(mixed_response, generator="astra"), None):
        review = generate_expected_review(result, call)
        jsonschema.validators.validator_for(review_schema)(review_schema).validate(review)
        attached = attach_expected_review(result, call)
        jsonschema.validators.validator_for(api)(api).validate(attached.model_dump(mode="json"))


def test_attach_records_stage_and_degrades_result_status(result):
    assert result.status == "ok"
    ok = attach_expected_review(result, FakeCall(mixed_response, generator="astra"))
    st = ok.stages[-1]
    assert st.stage == "expected_review" and st.state == "ok" and ok.status == "ok"
    assert st.counts == {"gen": 7, "pass": 3, "drop": 4, "no_evidence": 2}  # E3-L1e: 근거 없음·없는 id
    assert ok.expected_review["generator"] == "astra"
    bad = attach_expected_review(result, FakeCall(None, generator="astra"))
    assert bad.stages[-1].state == "degraded" and bad.stages[-1].impl == "fallback:rule"
    assert bad.status == "degraded" and bad.expected_review["generator"] == "rule"


# ── provider 어댑터(E3-L0 llm.py 모양) ───────────────────────────────────


class FakeLLMResult:
    def __init__(self, ok, data, generator, model, error=None):
        self.ok, self.data, self.generator, self.model, self.error = ok, data, generator, model, error

    def reason(self):
        return f"fake:{self.model} {self.error}"


class FakeProvider:
    model = "fake-model"

    def __init__(self, result, name="openai"):
        self.result = result
        self.name = name
        self.calls = []

    def complete_json(self, call):
        self.calls.append(call)
        return self.result


def test_provider_adapter_passes_call_and_labels_honestly(result):
    ok = {"strength": [], "request": [], "weakness": [s("누출 위험.", [EX_LEAK], [LEAK])]}
    prov = FakeProvider(FakeLLMResult(True, ok, "astra", "gpt-6-astra"))
    adapter = ProviderLLMCall(prov, timeout_s=30)
    assert adapter.generator == "astra"  # 호출 전에 이미 속성이 있다
    review = generate_expected_review(result, adapter)
    (call,) = prov.calls
    assert call.task == "expected_review" and call.effort == "medium" and call.timeout_s == 30
    assert call.schema["required"] == ["strength", "weakness", "request"]
    assert json.loads(call.input_text())["cards"]
    assert review["generator"] == "astra" and review["model"] == "gpt-6-astra" and review["status"] == "ok"

    prov_fail = FakeProvider(FakeLLMResult(False, None, "astra", "gpt-6-astra", error="timeout"))
    review = generate_expected_review(result, ProviderLLMCall(prov_fail))
    assert review["generator"] == "rule" and "timeout" in review["reason"]


def test_provider_adapter_label_comes_from_provider_not_settings(result, provider_openai):
    ok = {"strength": [], "request": [], "weakness": [s("누출 위험.", [EX_LEAK], [LEAK])]}
    assert ProviderLLMCall(FakeProvider(None, name="mock")).generator == "mock"
    assert ProviderLLMCall(FakeProvider(None, name="off")).generator == "rule"
    # 호출 결과가 다른 표기를 주면 실제 결과를 따른다
    review = generate_expected_review(result, ProviderLLMCall(FakeProvider(FakeLLMResult(True, ok, "mock", "m"), name="openai")))
    assert review["generator"] == "mock"
    # 모르는 provider 이름은 추정하지 않고 거부. 인자로 주면 받는다
    with pytest.raises(ValueError):
        ProviderLLMCall(FakeProvider(None, name="anthropic"))
    with pytest.raises(ValueError):
        ProviderLLMCall(object())
    assert ProviderLLMCall(FakeProvider(None, name="anthropic"), generator="mock").generator == "mock"


def test_real_llm_mock_provider_reaches_review_path(result):
    """E3-L0 llm.py가 main에 들어오면 실제 MockProvider로 이 경로가 호출되는지 확인한다(없으면 건너뜀)."""
    llm = pytest.importorskip("neumann.llm")

    def responder(call):
        payload = call.payload
        c = payload["cards"][0]
        return {"strength": [], "request": [],
                "weakness": [s("근거에 기댄 문장이다.", [c["evidence"][0]["id"]], [c["id"]])]}

    prov = llm.MockProvider({"expected_review": responder})
    review = generate_expected_review(result, ProviderLLMCall(prov))
    assert len(prov.calls) == 1 and prov.calls[0].task == "expected_review"
    assert review["generator"] == "mock" and review["status"] == "ok" and review["weakness"]
