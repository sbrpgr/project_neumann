"""The real finalize HTTP path retains per-tool timeout evidence (mock only)."""
from dataclasses import replace
import threading

from neumann.analyze import final_tools
from neumann.finalize import tools
from tests.e4.test_finalize_api import setup
from tests.e4.test_revise_api import PLAN, _bundle, _decisions, client, result_json, run


def test_http_tool_timeout_remains_unchecked_and_replays_evidence(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch)
    registry = tools.ToolRegistry()
    tools.ensure_adapters(registry)
    z3 = next(s for s in tools.ADAPTERS if s.name == "z3")
    registry.register(replace(z3, timeout_s=.05), replace=True)
    monkeypatch.setattr(tools, "registry", registry)
    real = final_tools._constraint
    release, finished = threading.Event(), threading.Event()
    calls = []
    def delayed(*args):
        calls.append(1)
        try:
            release.wait(.3)
            return real(*args)
        finally:
            finished.set()
    monkeypatch.setattr(final_tools, "_constraint", delayed)
    text = "총 3\n항목 4\n최대 10"
    check = {"check_id": "budget", "kind": "constraint", "plan_lines": [1, 2, 3], "params": {
        "sources": [{"line": i + 1} for i in range(3)], "operation": "sum",
        "terms": [{"source": 0, "value": 3}, {"source": 1, "value": 4}],
        "comparator": "le", "limit": {"source": 2, "value": 10}}}
    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            body = {"plan_text": PLAN, "revision": bundle, "result": result_json(),
                    "decisions": _decisions(bundle)}
            assembled = await c.post("/premortem/revise/assemble", json=body)
            assert assembled.status_code == 200
            body.update(confirmed_text=text, confirmed_base_id=assembled.json()["revised_plan_id"],
                        checks=[check], submission_id="vcomb_tool_timeout")
            response = await c.post("/premortem/finalize", json=body)
            assert response.status_code == 200
            out = response.json()
            row = out["finalization"]["tool_checks_before"][0]
            assert row["status"] == "unchecked" and row["error"] == "timeout"
            assert row["details"] == {} and row["message"].startswith("timeout")
            assert row["evidence"]["verdict"] == "unchecked" and row["evidence"]["output"] == {}
            assert row["evidence"]["tool"] == "z3" and row["evidence"]["check_id"] == "budget"
            assert out["finalization"]["status"] == "partial" and out["final_text"] == text
            issue = next(i for i in out["finalization"]["issues"] if i["issue_id"] == "tool:budget")
            assert issue["status"] == "unchecked" and issue["unchecked_reason"].startswith("timeout")
            replay = await c.post("/premortem/finalize", json=body)
            assert replay.status_code == 200 and replay.json() == out
            assert len(calls) == 1
    try:
        run(go())
        assert srv.gate.active == srv.gate.waiting == 0
    finally:
        release.set()
        if calls:
            assert finished.wait(2)
