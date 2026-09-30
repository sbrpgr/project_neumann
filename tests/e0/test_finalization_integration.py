"""Real HTTP -> real assembly -> real final engine -> installed tool checks.

Only the research records and semantic model are explicit mock fixtures.
"""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from neumann.api import finalize
from tests.e4.test_finalize_api import setup
from tests.e4.test_revise_api import PLAN, _bundle, _decisions, client, result_json, run


def test_real_finalization_response_contract_tools_and_duplicate(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch)
    manuscript = "합계 항목은 3이다.\n추가 항목은 4이다.\n합계 최대 6이다."
    checks = [{"check_id": "resource", "kind": "constraint", "plan_lines": [1, 2, 3], "params": {
        "sources": [{"line": 1, "quote": "합계 항목은 3이다."},
                    {"line": 2, "quote": "추가 항목은 4이다."},
                    {"line": 3, "quote": "합계 최대 6이다."}],
        "operation": "sum", "terms": [{"source": 0, "value": 3}, {"source": 1, "value": 4}],
        "comparator": "le", "limit": {"source": 2, "value": 6}}}]
    schema = json.loads((Path(__file__).resolve().parents[2] / "contracts/finalization.schema.json").read_text(encoding="utf-8"))

    async def go():
        async with client(app) as c:
            revision = await _bundle(c)
            body = {"plan_text": PLAN, "revision": revision, "result": result_json(), "decisions": _decisions(revision)}
            assembled = await c.post("/premortem/revise/assemble", json=body)
            assert assembled.status_code == 200
            request = {**body, "submission_id": "real_finalization_contract", "confirmed_text": manuscript,
                       "confirmed_base_id": assembled.json()["revised_plan_id"], "checks": checks}
            response = await c.post(finalize.FINALIZE_PATH, json=request)
            assert response.status_code == 200, response.text
            out = response.json()
            Draft202012Validator(schema).validate(out)
            report = out["finalization"]
            assert report["generator"] == "mock" and report["status"] == "partial"
            assert report["tool_checks_before"][0]["tool"] == "z3"
            assert report["tool_checks_before"][0]["status"] == "failed"
            assert report["final_text"] == manuscript and out["final_text"] == manuscript
            assert report["counters"] == {"assessment_calls": 1, "correction_calls": 1,
                                           "correction_batches": 0, "recheck_runs": 0}
            again = await c.post(finalize.FINALIZE_PATH, json=request)
            assert again.status_code == 200 and again.json() == out
    run(go())
    assert srv.gate.active == srv.gate.waiting == 0


def test_response_schema_cannot_claim_unknown_tool_pass():
    schema = json.loads((Path(__file__).resolve().parents[2] / "contracts/finalization.schema.json").read_text(encoding="utf-8"))
    tool_schema = {"$schema": schema["$schema"], **schema["$defs"]["toolResult"]}
    valid = {"check_id": "bad", "kind": "unknown", "tool": "none", "status": "unchecked",
             "plan_lines": [], "message": "invalid_parameters", "details": {}}
    validator = Draft202012Validator(tool_schema)
    assert validator.is_valid(valid)
    assert not validator.is_valid({**valid, "status": "passed"})
