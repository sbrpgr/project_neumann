"""FIN-COMBINE v3 open registry with FIN-TOOLS canonical names and citation."""
from neumann.finalize import tools as engine
from neumann.finalize.tools.fin_tools import register_all, run_call


def test_citation_is_registered_and_uses_the_shared_evidence_boundary():
    reg = engine.ToolRegistry()
    assert set(register_all(reg)) == {"z3", "pint", "networkx", "citation_lookup"}
    result = engine.run_tool(engine.ToolCall("citation_lookup", {"title": "Unknown fixture title"}), reg=reg)
    assert result.evidence["tool"] == "citation_lookup"
    assert result.evidence["interface"] == "finalize-tools@v3"
    assert result.verdict == "unchecked"
    assert reg.get("citation_lookup").timeout_s > 0


def test_auto_registration_preserves_custom_implementations():
    reg = engine.ToolRegistry()
    custom = engine.ToolSpec("z3", "custom", lambda args: {"verdict": "pass", "custom": True}, "custom-v1")
    reg.register(custom)
    engine.ensure_builtin(reg)
    assert reg.get("z3") is custom
    assert engine.run_tool(engine.ToolCall("z3", {}), reg=reg).output["custom"] is True


def test_registered_extension_is_not_restricted_to_known_names():
    reg = engine.ToolRegistry()
    reg.register(engine.ToolSpec("custom_checker", "custom", lambda args: {"verdict": "pass"}, "v1"))
    assert run_call(engine.ToolCall("custom_checker", {}), reg=reg).verdict == "pass"
    assert run_call(engine.ToolCall("unknown_checker", {}), reg=reg).error == "tool_unavailable"
