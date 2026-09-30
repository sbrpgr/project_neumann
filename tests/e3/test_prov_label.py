"""PROV-LABEL: 실제 공급자 없이 실패·부분 성공 출처와 화면 상태를 다시 잰다."""

import json
from pathlib import Path

import jsonschema
import pytest

from neumann.analyze import queries, validate
from neumann.analyze.mock_responders import default_responders
from neumann.api.view import build_ui_view, validate_ui_view
from neumann.llm import MockProvider
from neumann.models import PremortemResult, WhyApplies
from neumann.pipeline import run_premortem
from tests.e3.corpus import PLAN_BATTERY, build_backend
from tests.e3.test_validate_semantic import LEAK, SEED, _base, _judge

ROOT = Path(__file__).resolve().parents[2]
MODEL = "gpt-6.1-sol"


def _contract(result):
    raw = result.model_dump(mode="json")
    schema = json.loads((ROOT / "contracts/premortem_response.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(raw, schema)
    PremortemResult.model_validate(raw)
    view = build_ui_view(result, records=None)
    assert validate_ui_view(view) == []
    return view


@pytest.mark.parametrize("failed,source", [(True, "rule"), (False, "mock")])
def test_search_source_follows_real_query_generation(failed, source):
    llm = MockProvider(default_responders(), fail={"query_axes": "timeout"} if failed else {})
    result = run_premortem(PLAN_BATTERY, provider="mock", llm=llm, backend=build_backend(), cache_dir=None)
    assert result.plan_checks["queries"]["queries"]  # 실패해도 규칙이 채운다(LS-2)
    assert result.plan_checks["queries"]["generator"] == source
    assert result.plan_checks["search"]["queries_source"] == source
    status = _contract(result)["_status"]
    assert status["search"]["queries_source"] == source
    assert ("검색어 규칙 대체" in status["label"]) == failed
    assert status["generator_labels"] == {"mock": "모의(mock)"}


@pytest.mark.parametrize("generator,empty,source", [("astra", False, "llm"), ("astra", True, "rule")])
def test_search_source_for_llm_metadata_and_empty_queries(monkeypatch, generator, empty, source):
    original = queries.make_queries

    def query_plan(*args, **kwargs):
        qp = original(*args, **kwargs)
        qp.generator = generator  # 공급자 호출 없이 계약 메타데이터만 재현
        if empty:
            qp.queries = []
        return qp

    monkeypatch.setattr(queries, "make_queries", query_plan)
    result = run_premortem(PLAN_BATTERY, provider="mock", backend=build_backend(), cache_dir=None)
    assert result.plan_checks["search"]["queries_source"] == source
    assert _contract(result)["_status"]["search"]["queries_source"] == source


def _failure(kind):
    def callback(*args, **kwargs):
        if kind == "exception":
            raise RuntimeError("synthetic failure")
        return {"cards": []} if kind == "missing" else ([] if kind == "malformed" else None)
    return callback


@pytest.mark.parametrize("kind", ["none", "exception", "malformed", "missing"])
@pytest.mark.parametrize("generator", ["astra", "mock"])
def test_zero_success_reports_rule_with_no_model(kind, generator):
    result, plan = _base()
    card = result.risk_cards[0]
    bad = card.model_copy(update={"why_applies": WhyApplies(text=card.why_applies.text, plan_lines=[])})
    result = result.model_copy(update={"risk_cards": [bad, *result.risk_cards[1:]]})
    report = validate.validate_cards(result, plan, _failure(kind), generator=generator, model=MODEL)
    assert {r["judge"] for r in report["cards"]} == {"rule", "none"}
    assert report["generator"] == "rule" and report["model"] is None
    assert report["generators"] == {"rule": 1, "none": len(report["cards"]) + len(report["actions"]) - 1}
    assert report["status"] == "degraded"
    status = _contract(validate.apply_validation(result, report))["_status"]
    assert status["degraded"] is True
    assert any(s["name"] == "semantic_validate" for s in status["stages_not_ok"])
    assert any("2차 의미검증 출처: 비상 규칙" in n for n in status["notices"])


def _callback(respond):
    def callback(schema, instructions, input, *, effort):
        return respond(json.loads(input))
    return callback


@pytest.mark.parametrize("generator", ["astra", "mock"])
def test_partial_batch_success_reports_mixed(monkeypatch, generator):
    result, plan = _base()
    monkeypatch.setattr(validate, "CARDS_PER_CALL", 1)
    judge = _judge({LEAK: "match", SEED: "match"})
    callback = _callback(lambda payload: judge(payload) if payload["cards"][0]["card_id"] == LEAK else None)
    report = validate.validate_cards(result, plan, callback, generator=generator, model=MODEL)
    assert report["counts"]["calls"] == 2 and report["counts"]["calls_failed"] == 1
    assert report["generator"] == "mixed" and report["model"] == MODEL
    assert set(report["generators"]) == {generator, "none"}
    assert report["status"] == "degraded"
    view = _contract(validate.apply_validation(result, report))
    assert view["_status"]["degraded"] is True
    assert any("2차 의미검증 출처: 혼합" in n for n in view["_status"]["notices"])


@pytest.mark.parametrize("generator", ["astra", "mock"])
def test_complete_success_keeps_actual_generator(generator):
    result, plan = _base()
    callback = _callback(_judge({LEAK: "match", SEED: "match"}))
    report = validate.validate_cards(result, plan, callback, generator=generator, model=MODEL)
    assert report["generator"] == generator and report["model"] == MODEL
    assert report["generators"] == {generator: len(report["cards"]) + len(report["actions"])}
    assert report["status"] == "ok"
    _contract(validate.apply_validation(result, report))


def test_successful_actions_with_rule_capped_cards_are_mixed():
    result, plan = _base()
    cards = [c.model_copy(update={"why_applies": WhyApplies(text=c.why_applies.text, plan_lines=[])})
             for c in result.risk_cards]
    result = result.model_copy(update={"risk_cards": cards})
    report = validate.validate_cards(result, plan, _callback(_judge({LEAK: "match", SEED: "match"})),
                                     generator="astra", model=MODEL)
    assert {r["judge"] for r in report["cards"]} == {"rule"}
    assert {r["judge"] for r in report["actions"]} == {"astra"}
    assert report["generator"] == "mixed" and report["model"] == MODEL
    _contract(validate.apply_validation(result, report))


@pytest.mark.parametrize("empty", [True, False])
def test_absent_callback_or_zero_cards_never_claims_llm(empty):
    result, plan = _base()
    if empty:
        result = result.model_copy(update={"risk_cards": [], "checklist": []})
    report = validate.validate_cards(result, plan, None, generator="astra", model=MODEL)
    assert report["generator"] == "rule" and report["model"] is None
    assert report["status"] == ("skipped" if empty else "degraded")
    _contract(validate.apply_validation(result, report))
