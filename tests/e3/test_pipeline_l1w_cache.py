"""E3-L1w: 검색어 캐시(queries.make_queries). 같은 계획서(plan_id)는 astra 검색어를 다시 쓴다."""

from __future__ import annotations

import json

from neumann.analyze import queries as queries_mod
from neumann.analyze.mock_responders import default_responders
from neumann.llm import MockProvider
from neumann.models import PlanDocument
from tests.e3.corpus import PLAN_BATTERY, PLAN_IMAGING


class AstraLike(MockProvider):
    """응답은 결정적이지만 이름은 openai(생성 주체 astra)인 시험용 provider."""

    name = "openai"


def _astra(**kw) -> AstraLike:
    return AstraLike(default_responders(), model="gpt-6-astra", **kw)


def _n_calls(llm: MockProvider, task: str = "query_axes") -> int:
    return sum(1 for c in llm.calls if c.task == task)


def _plan(text: str, session: str = "s1") -> PlanDocument:
    return PlanDocument.from_text(text, session)


def test_astra_queries_are_stored_then_reused(tmp_path):
    llm = _astra()
    first = queries_mod.make_queries(_plan(PLAN_BATTERY), llm, cache_dir=tmp_path)
    assert first.generator == "astra" and first.queries
    assert first.cache["enabled"] and first.cache["stored"] and not first.cache["hit"]
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1 and files[0].stem.startswith(first.cache["key"])
    entry = json.loads(files[0].read_text(encoding="utf-8"))
    assert entry["provider"] == "openai" and entry["model"] == "gpt-6-astra" and entry["created_at"]
    assert entry["plan_id"] == _plan(PLAN_BATTERY).plan_id

    # 같은 계획서, 다른 세션: provider를 다시 부르지 않고 같은 검색어·축
    second = queries_mod.make_queries(_plan(PLAN_BATTERY, "s2"), llm, cache_dir=tmp_path)
    assert _n_calls(llm) == 1
    assert second.cache["hit"] and not second.cache["stored"] and second.cache["created_at"] == entry["created_at"]
    assert second.queries == first.queries and second.axes == first.axes and second.is_research == first.is_research
    assert second.generator == "astra" and second.model == "gpt-6-astra"  # 캐시여도 만든 주체를 그대로 표기
    assert any("캐시 적중" in n for n in second.notes)


def test_other_plan_or_model_misses(tmp_path):
    llm = _astra()
    queries_mod.make_queries(_plan(PLAN_BATTERY), llm, cache_dir=tmp_path)
    other = queries_mod.make_queries(_plan(PLAN_IMAGING), llm, cache_dir=tmp_path)
    assert not other.cache["hit"] and _n_calls(llm) == 2
    llm2 = AstraLike(default_responders(), model="gpt-6-other")
    again = queries_mod.make_queries(_plan(PLAN_BATTERY), llm2, cache_dir=tmp_path)
    assert not again.cache["hit"] and _n_calls(llm2) == 1
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_mock_and_rule_results_are_not_cached(tmp_path):
    mock = MockProvider(default_responders())
    qp = queries_mod.make_queries(_plan(PLAN_BATTERY), mock, cache_dir=tmp_path)
    assert qp.generator == "mock" and not qp.cache["enabled"] and not qp.cache["stored"]
    # astra 호출이 실패해 규칙 경로로 가면 저장하지 않는다 → 다음 실행에서 astra를 다시 시도한다
    failing = _astra(fail={"query_axes": "timeout"})
    fb = queries_mod.make_queries(_plan(PLAN_BATTERY), failing, cache_dir=tmp_path)
    assert fb.generator == "rule" and fb.fallback_reason and fb.cache["enabled"] and not fb.cache["stored"]
    assert list(tmp_path.glob("*.json")) == []
    ok = _astra()
    assert not queries_mod.make_queries(_plan(PLAN_BATTERY), ok, cache_dir=tmp_path).cache["hit"]
    assert _n_calls(ok) == 1


def test_broken_cache_entry_is_ignored_and_rewritten(tmp_path):
    llm = _astra()
    first = queries_mod.make_queries(_plan(PLAN_BATTERY), llm, cache_dir=tmp_path)
    path = next(tmp_path.glob("*.json"))
    path.write_text(json.dumps({"v": queries_mod.CACHE_VERSION, "data": {"queries": "not a list"}}), encoding="utf-8")
    again = queries_mod.make_queries(_plan(PLAN_BATTERY), llm, cache_dir=tmp_path)
    assert not again.cache["hit"] and again.cache["stored"] and _n_calls(llm) == 2
    assert again.queries == first.queries
    path.write_text("{깨진 JSON", encoding="utf-8")
    assert not queries_mod.make_queries(_plan(PLAN_BATTERY), llm, cache_dir=tmp_path).cache["hit"]


def test_no_cache_dir_means_no_cache(tmp_path):
    llm = _astra()
    a = queries_mod.make_queries(_plan(PLAN_BATTERY), llm)
    b = queries_mod.make_queries(_plan(PLAN_BATTERY), llm, cache_dir=None)
    assert not a.cache["enabled"] and not b.cache["enabled"] and _n_calls(llm) == 2


def test_cache_key_depends_on_plan_provider_model_effort():
    p = _plan(PLAN_BATTERY)
    k = queries_mod.cache_key(p, "openai", "gpt-6-astra", "low")
    assert k == queries_mod.cache_key(_plan(PLAN_BATTERY, "other-session"), "openai", "gpt-6-astra", "low")
    assert k != queries_mod.cache_key(_plan(PLAN_IMAGING), "openai", "gpt-6-astra", "low")
    assert k != queries_mod.cache_key(p, "openai", "gpt-6-astra", "medium")
    assert k != queries_mod.cache_key(p, "openai", "gpt-6-x", "low")
    assert k != queries_mod.cache_key(p, "mock", "gpt-6-astra", "low")
