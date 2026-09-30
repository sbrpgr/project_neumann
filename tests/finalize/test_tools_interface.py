"""도구 인터페이스 계약(FIN-ENGINE ↔ FIN-TOOLS): ToolCall → ToolResult, 코드가 정한 유형→도구 표, 실패는 통과가 아니다."""

from __future__ import annotations

import threading

import pytest

from neumann.finalize import tools as T


def spec(name="arithmetic_sum", fn=None, schema=None):
    return T.ToolSpec(name=name, description="stub", version="t", args_schema=schema,
                      run=fn or (lambda a: {"verdict": "fail" if sum(a["items"]) != a["total"] else "pass",
                                            "computed": sum(a["items"]), "stated": a["total"]}))


def test_code_fixed_tool_map_covers_every_check_kind_and_rejects_unknown():
    assert set(T.TOOL_FOR_CHECK) == set(T.CHECK_KINDS)
    assert {T.tool_for(k) for k in T.CHECK_KINDS} <= set(T.TOOL_NAMES)
    assert T.tool_for("sum") == "arithmetic_sum" and T.tool_for("unit") == "unit_dimension"
    with pytest.raises(ValueError):
        T.tool_for("llm_choice")


def test_result_carries_evidence_with_tool_input_output():
    reg = T.ToolRegistry()
    reg.register(spec())
    res = reg.run(T.ToolCall("arithmetic_sum", {"items": [70, 20, 20], "total": 100}, check_id="c1"))
    assert res.ok and res.verdict == "fail" and res.output["computed"] == 110
    ev = res.evidence
    assert ev["tool"] == "arithmetic_sum" and ev["check_id"] == "c1" and ev["input"]["total"] == 100
    assert ev["output"]["computed"] == 110 and ev["verdict"] == "fail" and ev["elapsed_ms"] >= 0
    assert res.as_dict()["verdict"] == "fail"


def test_failures_are_unchecked_never_pass_and_never_leak_exception_text():
    reg = T.ToolRegistry()
    assert reg.run(T.ToolCall("calculator", {})).verdict == "unchecked"          # not registered
    assert reg.run(T.ToolCall("calculator", {})).error == "tool_unavailable"
    assert reg.run(T.ToolCall("not_a_tool", {})).error == "invalid_args"          # unknown name
    reg.register(spec("calculator", fn=lambda a: (_ for _ in ()).throw(RuntimeError("secret /path/key=abc"))))
    res = reg.run(T.ToolCall("calculator", {"expression": "1+1"}))
    assert not res.ok and res.verdict == "unchecked" and res.error == "tool_error"
    assert "secret" not in str(res.as_dict()) and "/path" not in str(res.as_dict())
    reg.register(spec("unit_dimension", fn=lambda a: {"no_verdict": True}))
    assert reg.run(T.ToolCall("unit_dimension", {})).verdict == "unchecked"       # malformed output
    reg.register(spec("structure", fn=lambda a: (_ for _ in ()).throw(ImportError("pint"))))
    assert reg.run(T.ToolCall("structure", {})).error == "tool_unavailable"


def test_schema_validation_and_cancel_are_unchecked():
    reg = T.ToolRegistry()
    schema = {"type": "object", "required": ["items", "total"], "properties": {
        "items": {"type": "array", "items": {"type": "number"}}, "total": {"type": "number"}}, "additionalProperties": False}
    reg.register(spec(schema=schema))
    bad = reg.run(T.ToolCall("arithmetic_sum", {"items": "SECRET_VALUE", "total": 1}))
    assert bad.error == "invalid_args" and "SECRET_VALUE" not in bad.evidence["reason"]
    ev = threading.Event()
    ev.set()
    assert reg.run(T.ToolCall("arithmetic_sum", {"items": [1], "total": 1}), cancel_event=ev).error == "cancelled"


def test_registry_refuses_unknown_tool_names_and_duplicate_registration():
    reg = T.ToolRegistry()
    with pytest.raises(ValueError):
        reg.register(spec("free_form_python"))
    reg.register(spec())
    with pytest.raises(ValueError):
        reg.register(spec())
    reg.register(spec(), replace=True)
    assert reg.names() == ["arithmetic_sum"]
