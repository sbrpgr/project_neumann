"""E-8 통합: FIN-TOOLS `register_all()`을 실제 FIN-ENGINE 레지스트리(TOOL_NAMES = z3·pint·networkx)에 붙인다.

- 등록이 ValueError 없이 되고, 엔진 형식(final_tools check) 호출은 엔진 어댑터로 그대로 간다.
- FIN-TOOLS 형식 호출은 같은 엔진 이름으로 FIN-TOOLS 구현이 받는다(별칭).
- 엔진의 `ensure_adapters`가 FIN-TOOLS 구현을 덮어쓰지 않는다.
"""

from __future__ import annotations

import pytest

from neumann.finalize import tools as engine
from neumann.finalize.tools import ToolCall, ToolRegistry
from neumann.finalize.tools.extract import extract_checks, run_checks
from neumann.finalize.tools.fin_tools import register_all, run_call
from tests.finalize.fin_tools_plans import SEEDED


def _constraint(limit: int):
    plan = f"총 3\n항목 4\n최대 {limit}"
    sources = [{"line": i + 1, "quote": line} for i, line in enumerate(plan.splitlines())]
    return plan, {"check_id": "c", "kind": "constraint", "plan_lines": [1, 2, 3], "params": {
        "sources": sources, "operation": "sum", "terms": [{"source": 0, "value": 3}, {"source": 1, "value": 4}],
        "comparator": "le", "limit": {"source": 2, "value": limit}}}


@pytest.fixture()
def shared_registry():
    """엔진 공용 레지스트리에 실제로 붙이고, 끝나면 엔진 기본(어댑터)으로 되돌린다."""
    yield engine.registry
    for name in engine.TOOL_NAMES:
        engine.registry.unregister(name)
    engine.ensure_adapters()


def test_register_all_attaches_to_real_engine_registry_without_valueerror(shared_registry):
    engine.ensure_adapters()                       # 엔진이 먼저 어댑터를 붙인 상태에서
    names = register_all()                         # FIN-TOOLS가 같은 이름으로 교체
    assert set(names) == {"z3", "pint", "networkx", "citation_lookup"}
    assert register_all() == []                    # 같은 판이면 다시 붙이지 않는다
    assert engine.ensure_adapters() == []          # 엔진 어댑터가 FIN-TOOLS 구현을 덮어쓰지 않는다
    for name in ("z3", "pint", "networkx"):
        assert "+final_tools@v1" in shared_registry.get(name).version


@pytest.mark.parametrize("limit,verdict", [(10, "pass"), (6, "fail")])
def test_engine_format_calls_still_reach_final_tools_adapter(shared_registry, limit, verdict):
    register_all()
    plan, check = _constraint(limit)
    res = engine.run_check(plan, check)
    assert res.verdict == verdict and res.output["status"] in ("passed", "failed") and res.evidence["tool"] == "z3"


def test_fin_tools_format_calls_use_engine_names(shared_registry):
    register_all()
    s = engine.run_tool(ToolCall("z3", {"items": [3, 4, 3], "total": 12}))
    u = engine.run_tool(ToolCall("pint", {"left": {"value": 3, "unit": "m"}, "right": {"value": 4, "unit": "s"}, "operation": "add"}))
    n = engine.run_tool(ToolCall("networkx", {"lines": ["## 1. 배경", "§3 참조", "## 2. 방법"], "checks": ["references"]}))
    assert (s.verdict, u.verdict, n.verdict) == ("fail", "fail", "fail")
    assert s.output["engine"] == "fraction+z3" and u.output["engine"] == "pint" and n.output["engine"] == "networkx"
    assert run_call(ToolCall("arithmetic_sum", {"items": [1], "total": 1})).evidence["tool"] == "z3"  # 옛 이름 별칭
    assert run_call(ToolCall("calculator", {"expression": "1+1"})).error == "tool_unavailable"      # 만들지 않은 도구


def test_extracted_checks_run_through_a_fresh_engine_registry():
    reg = ToolRegistry()
    results = run_checks(extract_checks(SEEDED), reg=reg)
    assert sorted(reg.names()) == ["citation_lookup", "networkx", "pint", "z3"]
    assert {r["result"]["evidence"]["tool"] for r in results} >= {"z3", "pint", "networkx"}
    assert all(r["result"]["verdict"] == "fail" for r in results if r["check"]["label"] != "citation")
