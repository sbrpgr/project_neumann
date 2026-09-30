"""V-COMBINED E-1/E-4 reproductions: mock LLM, real bounded tool adapters."""
from dataclasses import replace
import threading
import time

import pytest

from neumann.analyze import final_tools, finalize
from neumann.finalize import tools
from tests.e3.test_finalize_gate import CHECK, PLAN, edit, provider


@pytest.mark.parametrize("status", ["passed", "failed"])
def test_computed_allowlist_excludes_params_and_numeric_metadata(status):
    check = {"params": {"terms": [{"value": 81}], "limit": {"value": 82},
                        "left": {"value": 83}, "right": {"value": 84}}}
    assert finalize._computed_numbers(check, {"status": status, "details": {"nodes": 99}}) == set()
    row = {"status": status, "details": {"computed": 7, "nodes": 99,
           "elapsed_ms": 123, "metadata": {"numbers": [88, 89]}}}
    assert finalize._computed_numbers(check, row) == {"7"}
    assert finalize._computed_numbers(check, {**row, "status": "unchecked"}) == set()


@pytest.mark.parametrize("value,expected", [
    (0, {"0"}), (-2.5, {"2.5"}), (7.0, {"7"}), (True, set()),
    (float("nan"), set()), (float("inf"), set()), ("99", set()),
    ({"nodes": 99}, set()), ([99], set()),
])
def test_only_explicit_finite_computed_scalars_are_numeric_evidence(value, expected):
    assert finalize._computed_numbers({}, {"status": "passed", "details": {"computed": value}}) == expected


def test_numeric_metadata_cannot_authorize_a_final_correction(monkeypatch):
    real = final_tools.run_tool_checks
    def metadata(text, checks, event=None):
        rows = real(text, checks, event)
        for row in rows:
            row["details"] = {**row["details"], "nodes": 99}
        return rows
    monkeypatch.setattr(final_tools, "run_tool_checks", metadata)
    out = finalize.finalize_plan(PLAN, provider=provider([
        edit("합계 최대 6이다. [확인 필요: 값 99]")]))
    assert out["tool_checks_before"][0]["details"]["nodes"] == 99
    assert out["corrections"][0]["reason"] == "unsupported_number"
    assert out["final_text"] == out["input_text"]
    allowed = finalize.finalize_plan(PLAN, provider=provider([
        edit("합계 최대 6이다. [확인 필요: 값 7]")]))
    assert allowed["corrections"][0]["applied"]
    assert "계산값 7" in allowed["final_text"]
    assert "99" not in allowed["final_text"].splitlines()[2]


@pytest.fixture
def short_registry(monkeypatch):
    reg = tools.ToolRegistry()
    tools.ensure_adapters(reg)
    for spec in tools.ADAPTERS:
        reg.register(replace(spec, timeout_s=.05), replace=True)
    monkeypatch.setattr(tools, "registry", reg)
    return reg


def assert_timeout(row):
    assert row["status"] == "unchecked"
    assert row["message"].startswith("timeout")
    assert row["details"] == {}
    assert row["evidence"]["verdict"] == "unchecked"
    assert row["evidence"]["output"] == {}
    assert row["evidence"]["reason"].startswith("timeout")
    assert row["error"] == "timeout"


@pytest.mark.parametrize("kind,tool,function", [
    ("constraint", "z3", "_constraint"), ("units", "pint", "_units"),
    ("dependency", "networkx", "_dependency"),
])
def test_finalize_uses_registry_timeout_for_every_tool(monkeypatch, short_registry, kind, tool, function):
    # Same 50ms wrapper / 300ms delay as timeout-flow. Event cleanup prevents
    # abandoned workers affecting later tests, even when the regression fails.
    release = threading.Event()
    finished = threading.Event()
    def delayed(*args):
        try:
            release.wait(.3)
            return True, {"computed": 7}
        finally:
            finished.set()
    monkeypatch.setattr(final_tools, function, delayed)
    check = {**CHECK, "kind": kind}
    try:
        started = time.perf_counter()
        out = finalize.finalize_plan(PLAN, provider="mock", checks=[check])
        elapsed = time.perf_counter() - started
        assert_timeout(out["tool_checks_before"][0])
        assert out["tool_checks_before"][0]["tool"] == tool
        assert out["tool_checks_before"][0]["evidence"]["check_id"] == CHECK["check_id"]
        assert out["tool_checks_before"][0]["plan_lines"] == [1, 2, 3]
        assert elapsed < .25
        issue = next(i for i in out["issues"] if i["issue_id"] == "tool:c1")
        assert issue["status"] == "unchecked" and issue["unchecked_reason"].startswith("timeout")
        assert out["status"] == "partial" and out["final_text"] == out["input_text"]
    finally:
        release.set()
        assert finished.wait(2)


def test_timeout_flow_interface_and_finalize_agree(monkeypatch, short_registry):
    real = final_tools._constraint
    finished = [threading.Event(), threading.Event()]
    calls = []
    def delayed(*args):
        index = len(calls)
        calls.append(index)
        try:
            time.sleep(.3)
            return real(*args)
        finally:
            finished[index].set()
    monkeypatch.setattr(final_tools, "_constraint", delayed)
    check = finalize._bind_sources([CHECK], PLAN.splitlines())[0]
    try:
        wrapped = tools.run_check(PLAN, check)
        assert wrapped.verdict == "unchecked" and wrapped.error == "timeout"
        out = finalize.finalize_plan(PLAN, provider="mock", checks=[check])
        assert_timeout(out["tool_checks_before"][0])
    finally:
        for event in finished[:len(calls)]:
            assert event.wait(2)


def test_targeted_recheck_also_uses_registry_timeout(monkeypatch, short_registry):
    real = final_tools._constraint
    release, finished = threading.Event(), threading.Event()
    calls = []
    def delayed_recheck(*args):
        calls.append(1)
        if len(calls) == 1:
            return real(*args)
        try:
            release.wait(.3)
            return real(*args)
        finally:
            finished.set()
    # Warm the real solver before applying the short deadline.
    check = finalize._bind_sources([CHECK], PLAN.splitlines())[0]
    assert final_tools.run_tool_checks(PLAN, [check])[0]["status"] == "failed"
    monkeypatch.setattr(final_tools, "_constraint", delayed_recheck)
    try:
        out = finalize.finalize_plan(PLAN, provider=provider([
            edit("합계 최대 6이다. [확인 필요: 항목 합계 7]")]))
        assert out["tool_checks_before"][0]["status"] == "failed"
        assert out["corrections"][0]["applied"] and out["counters"]["recheck_runs"] == 1
        assert_timeout(out["tool_checks_after"][0])
        assert out["issues"][0]["status"] == "unchecked"
        assert out["issues"][0]["unchecked_reason"].startswith("timeout")
    finally:
        release.set()
        if len(calls) > 1:
            assert finished.wait(2)
