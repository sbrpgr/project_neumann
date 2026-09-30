"""도구 인터페이스 계약(FIN-ENGINE ↔ FIN-TOOLS): ToolCall → ToolResult, 코드가 정한 유형→도구 표, 실패는 통과가 아니다.

레지스트리는 도구 이름을 목록에 묶지 않고(FIN-TOOLS의 arithmetic_sum·unit_dimension·structure·citation_lookup 등록 허용),
시간 상한을 실제로 강제한다. 기본 구현은 analyze/final_tools(Z3·Pint·NetworkX) 어댑터이고 실제 계산으로 검사한다."""

from __future__ import annotations

import sys
import threading
import time

import pytest

from neumann.finalize import tools as T

PLAN = "합계 항목은 3이다.\n추가 항목은 4이다.\n합계 최대 6이다."
CHECK = {"check_id": "c1", "kind": "constraint", "plan_lines": [1, 2, 3], "params": {
    "sources": [{"line": 1, "quote": "합계 항목은 3이다."}, {"line": 2, "quote": "추가 항목은 4이다."}, {"line": 3, "quote": "합계 최대 6이다."}],
    "operation": "sum", "terms": [{"source": 0, "value": 3}, {"source": 1, "value": 4}], "comparator": "le", "limit": {"source": 2, "value": 6}}}


def spec(name="z3", fn=None, schema=None, timeout_s=5.0):
    return T.ToolSpec(name=name, description="stub", version="t", args_schema=schema, timeout_s=timeout_s,
                      run=fn or (lambda a: {"verdict": "fail", "stub": True}))


def test_code_fixed_tool_map_covers_both_check_families_and_rejects_unknown():
    assert set(T.TOOL_FOR_CHECK) == set(T.CHECK_KINDS)
    assert {T.tool_for(k) for k in ("constraint", "units", "dependency")} == {"z3", "pint", "networkx"}
    assert T.tool_for("sum") == "arithmetic_sum" and T.tool_for("unit") == "unit_dimension" and T.tool_for("citation") == "citation_lookup"
    with pytest.raises(ValueError):
        T.tool_for("llm_choice")


def test_fin_tools_names_register_without_error_and_unknown_names_are_unavailable():
    reg = T.ToolRegistry()
    for name in ("arithmetic_sum", "unit_dimension", "structure", "citation_lookup", "calculator", "restricted_exec"):
        reg.register(spec(name, fn=lambda a: {"verdict": "pass"}))
    assert set(reg.names()) >= {"arithmetic_sum", "unit_dimension", "structure", "citation_lookup"}
    assert reg.run(T.ToolCall("arithmetic_sum", {"items": [1]})).verdict == "pass"
    assert reg.run(T.ToolCall("never_registered", {})).error == "tool_unavailable"
    assert reg.run(T.ToolCall("Bad Name!", {})).error == "invalid_args"
    with pytest.raises(ValueError):
        reg.register(spec("Bad Name!"))


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


def test_timeout_is_enforced_and_reported_as_unchecked():
    reg = T.ToolRegistry()
    reg.register(spec("z3", fn=lambda a: (time.sleep(0.6), {"verdict": "pass"})[1], timeout_s=0.05))
    t0 = time.perf_counter()
    res = reg.run(T.ToolCall("z3", {"x": 1}))
    assert time.perf_counter() - t0 < 0.5
    assert not res.ok and res.verdict == "unchecked" and res.error == "timeout" and res.evidence["reason"].startswith("timeout")


def test_failures_are_unchecked_and_never_leak_exception_text():
    reg = T.ToolRegistry()
    assert reg.run(T.ToolCall("z3", {})).error == "tool_unavailable"        # not registered
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


def test_registry_keeps_existing_registrations_and_allows_replacement_by_fin_tools():
    reg = T.ToolRegistry()
    reg.register(spec())
    with pytest.raises(ValueError):
        reg.register(spec())
    reg.register(spec(fn=lambda a: {"verdict": "pass", "replaced": True}), replace=True)
    assert reg.run(T.ToolCall("z3", {})).output["replaced"] is True
    assert set(T.ensure_adapters(reg)) == {"networkx", "pint"} and reg.names() == ["networkx", "pint", "z3"]
    assert T.ensure_adapters(reg) == [] and reg.run(T.ToolCall("z3", {})).output["replaced"] is True
