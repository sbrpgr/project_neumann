"""도구 인터페이스 계약(FIN-ENGINE ↔ FIN-TOOLS): ToolCall → ToolResult, 코드가 정한 유형→도구 표, 실패는 통과가 아니다.

기본 구현은 analyze/final_tools(Z3·Pint·NetworkX) 어댑터이고, 실제 계산으로 검사한다."""

from __future__ import annotations

import sys
import threading

import pytest

from neumann.finalize import tools as T

PLAN = "합계 항목은 3이다.\n추가 항목은 4이다.\n합계 최대 6이다."
CHECK = {"check_id": "c1", "kind": "constraint", "plan_lines": [1, 2, 3], "params": {
    "sources": [{"line": 1, "quote": "합계 항목은 3이다."}, {"line": 2, "quote": "추가 항목은 4이다."}, {"line": 3, "quote": "합계 최대 6이다."}],
    "operation": "sum", "terms": [{"source": 0, "value": 3}, {"source": 1, "value": 4}], "comparator": "le", "limit": {"source": 2, "value": 6}}}


def spec(name="z3", fn=None, schema=None):
    return T.ToolSpec(name=name, description="stub", version="t", args_schema=schema,
                      run=fn or (lambda a: {"verdict": "fail", "stub": True}))


def test_code_fixed_tool_map_covers_every_check_kind_and_rejects_unknown():
    assert set(T.TOOL_FOR_CHECK) == set(T.CHECK_KINDS) == {"constraint", "units", "dependency"}
    assert {T.tool_for(k) for k in T.CHECK_KINDS} == set(T.TOOL_NAMES) == {"z3", "pint", "networkx"}
    with pytest.raises(ValueError):
        T.tool_for("llm_choice")


def test_real_z3_through_the_interface_carries_tool_input_output_evidence():
    res = T.run_check(PLAN, CHECK)
    assert res.ok and res.verdict == "fail" and res.output["status"] == "failed"
    ev = res.evidence
    assert ev["tool"] == "z3" and ev["check_id"] == "c1" and ev["input"]["check"]["params"]["limit"]["value"] == 6
    assert ev["output"]["details"]["operation"] == "sum" and ev["verdict"] == "fail" and ev["elapsed_ms"] >= 0
    ok = T.run_check(PLAN.replace("최대 6", "최대 9"), {**CHECK, "params": {**CHECK["params"], "limit": {"source": 2, "value": 9},
                     "sources": CHECK["params"]["sources"][:2] + [{"line": 3, "quote": "합계 최대 9이다."}]}})
    assert ok.verdict == "pass"
    assert T.run_check(PLAN, {**CHECK, "kind": "free_python"}).verdict == "unchecked"


def test_ungrounded_or_ambiguous_checks_are_unchecked_never_pass():
    forged = {**CHECK, "params": {**CHECK["params"], "terms": [{"source": 0, "value": 30}, {"source": 1, "value": 4}]}}
    res = T.run_check(PLAN, forged)
    assert not res.ok and res.verdict == "unchecked" and "ungrounded" in res.output["reason"]
    assert T.run_tool(T.ToolCall("pint", {"plan_text": PLAN, "check": CHECK})).output["reason"] == "kind_mismatch"


def test_failures_are_unchecked_and_never_leak_exception_text():
    reg = T.ToolRegistry()
    assert reg.run(T.ToolCall("z3", {})).error == "tool_unavailable"        # not registered
    assert reg.run(T.ToolCall("not_a_tool", {})).error == "invalid_args"    # unknown name
    reg.register(spec("z3", fn=lambda a: (_ for _ in ()).throw(RuntimeError("secret /path/key=abc"))))
    res = reg.run(T.ToolCall("z3", {"x": 1}))
    assert not res.ok and res.verdict == "unchecked" and res.error == "tool_error"
    assert "secret" not in str(res.as_dict()) and "/path" not in str(res.as_dict())
    reg.register(spec("pint", fn=lambda a: {"no_verdict": True}))
    assert reg.run(T.ToolCall("pint", {})).verdict == "unchecked"           # malformed output
    reg.register(spec("networkx", fn=lambda a: (_ for _ in ()).throw(ImportError("networkx"))))
    assert reg.run(T.ToolCall("networkx", {})).error == "tool_unavailable"
    ev = threading.Event()
    ev.set()
    assert reg.run(T.ToolCall("z3", {}), cancel_event=ev).error == "cancelled"


def test_schema_validation_hides_values_and_missing_tool_module_is_unavailable(monkeypatch):
    reg = T.ToolRegistry()
    T.ensure_adapters(reg)
    bad = reg.run(T.ToolCall("z3", {"plan_text": "SECRET_VALUE", "check": "not-a-dict"}))
    assert bad.error == "invalid_args" and "SECRET_VALUE" not in bad.evidence["reason"]
    monkeypatch.setitem(sys.modules, "neumann.analyze.final_tools", None)
    assert T.run_check(PLAN, CHECK, reg=reg).error == "tool_unavailable"


def test_registry_refuses_unknown_names_and_duplicates_but_allows_replacement_by_fin_tools():
    reg = T.ToolRegistry()
    with pytest.raises(ValueError):
        reg.register(spec("free_form_python"))
    reg.register(spec())
    with pytest.raises(ValueError):
        reg.register(spec())
    reg.register(spec(fn=lambda a: {"verdict": "pass", "replaced": True}), replace=True)
    assert reg.run(T.ToolCall("z3", {})).output["replaced"] is True
    assert set(T.ensure_adapters(reg)) == {"networkx", "pint"} and reg.names() == ["networkx", "pint", "z3"]
