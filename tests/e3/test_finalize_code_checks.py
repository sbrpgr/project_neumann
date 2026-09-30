"""Production finalization must execute source-selected tools without model checks."""
from pathlib import Path
import threading

import pytest

from neumann.analyze import finalize as engine
from neumann.finalize.tools import citation, ToolRegistry, ToolSpec
from neumann.finalize.tools import extract as extractor
from neumann.finalize.tools import fin_tools
from neumann.llm import MockProvider

ROOT = Path(__file__).resolve().parents[2]


def empty_provider(edits=None):
    return MockProvider(scripted={
        engine.ASSESSMENT_TASK: [{"issues": [], "checks": []}],
        engine.CORRECTION_TASK: [{"edits": edits or []}],
    })


@pytest.mark.parametrize("name", ["electrolyte_gnn", "protein_ligand_affinity", "neural_operator_weather"])
def test_samples_execute_tools_with_empty_model_checks(name):
    text = (ROOT / "src/neumann/api/templates/samples" / (name + ".md")).read_text(encoding="utf-8")
    p = empty_provider()
    out = engine.finalize_plan(text, provider=p)
    assert p.calls[0].task == engine.ASSESSMENT_TASK
    assert out["code_selected_checks"] >= 2
    assert out["code_checks_label"] == f"코드 선택 검사 {out['code_selected_checks']}건"
    assert out["counters"]["tool_runs"]["z3"] > 0
    assert out["counters"]["tool_runs"]["networkx"] > 0
    for row in out["tool_checks_before"]:
        assert row["check_id"].startswith("code:")
        for anchor in row["details"]["anchors"]:
            assert out["input_text"].splitlines()[anchor["line"] - 1][anchor["start"]:anchor["end"]] == anchor["text"]
    failures = [r for r in out["tool_checks_before"] if r["status"] == "failed"]
    assert failures
    correction = p.calls[1].payload
    assert all(any(i["issue_id"] == "tool:" + r["check_id"] for i in correction["issues"]) for r in failures)
    assert out["status"] == "partial"


def test_mutation_removing_extraction_breaks_sample_requirement(monkeypatch):
    monkeypatch.setattr(engine, "extract_checks", lambda text: [])
    with pytest.raises(AssertionError):
        test_samples_execute_tools_with_empty_model_checks("electrolyte_gnn")


def test_units_and_local_citation_execute_without_network(monkeypatch, tmp_path):
    from tests.finalize.fin_tools_backend import build_backend, RETRACTED_DOI
    import socket
    def denied(*args, **kwargs):
        raise AssertionError("External network is forbidden")
    monkeypatch.setattr(socket.socket, "connect", denied)
    citation.set_backend(build_backend(tmp_path))
    try:
        out = engine.finalize_plan(f"10 mS + 1 S/cm\nDOI: {RETRACTED_DOI}", provider=empty_provider())
        assert out["counters"]["tool_runs"]["pint"] == 2
        assert out["counters"]["tool_runs"]["citation"] == 2
        assert {r["tool"] for r in out["tool_checks_before"]} == {"pint", "citation_lookup"}
        assert all(r["status"] == "failed" for r in out["tool_checks_before"])
    finally:
        citation.set_backend(None)


def test_reextracts_changed_claim_and_does_not_pass_a_disappearing_claim():
    text = "학습/검증/테스트 분할은 80/10/20이다."
    p = empty_provider()
    def correct(call):
        cid = call.payload["tool_checks"][0]["check_id"]
        return {"edits": [{"line": 1, "current_text": text,
                           "replacement": "학습/검증/테스트 분할은 80/10/10이다.", "issue_ids": ["tool:" + cid]}]}
    p.scripted[engine.CORRECTION_TASK] = [correct]
    out = engine.finalize_plan(text, provider=p)
    assert out["corrections"][0]["applied"]
    assert out["tool_checks_before"][0]["status"] == "failed"
    assert out["tool_checks_after"][0]["status"] == "passed"
    assert out["tool_checks_after"][0]["details"]["computed"] == 100
    assert out["issues"][0]["status"] == "resolved"
    p = empty_provider()
    def remove_claim(call):
        cid = call.payload["tool_checks"][0]["check_id"]
        return {"edits": [{"line": 1, "current_text": text,
                           "replacement": "학습/검증/테스트 분할은 [확인 필요: 분할 합계]",
                           "issue_ids": ["tool:" + cid]}]}
    p.scripted[engine.CORRECTION_TASK] = [remove_claim]
    out = engine.finalize_plan(text, provider=p)
    assert out["corrections"][0]["applied"]
    assert out["tool_checks_after"][0]["message"] == "claim_not_reextracted"
    assert out["issues"][0]["status"] == "unchecked"


def test_code_id_collision_keeps_both_rows():
    text = "학습/검증/테스트 분할은 80/10/20이다."
    cid = "code:" + extractor.extract_checks(text)[0].check_id
    out = engine.finalize_plan(text, provider=empty_provider(), checks=[{
        "check_id": cid, "kind": "constraint", "plan_lines": [1], "params": {}}])
    ids = [r["check_id"] for r in out["tool_checks_before"]]
    assert len(ids) == len(set(ids)) == 2
    assert {cid, "code:" + cid} == set(ids)


def test_model_failure_still_retains_code_tool_results():
    out = engine.finalize_plan("학습/검증/테스트 분할은 80/10/20이다.",
                               provider=MockProvider(fail={engine.ASSESSMENT_TASK: "timeout"}))
    assert out["status"] == "incomplete"
    assert out["counters"]["tool_runs"]["z3"] == 1
    assert out["issues"][0]["issue_id"].startswith("tool:code:")


def test_extracted_checks_use_existing_registry_timeout_and_cancellation(monkeypatch):
    gate = threading.Event()
    reg = ToolRegistry()
    reg.register(ToolSpec("z3", "slow local test", lambda _: gate.wait(2) or {"verdict": "pass"},
                          version="slow-test", timeout_s=0.02))
    monkeypatch.setattr(fin_tools, "register_all", lambda *args, **kwargs: [])
    checks = extractor.extract_checks("학습/검증/테스트 분할은 80/10/10이다.")
    try:
        row = extractor.run_checks(checks, reg=reg)[0]["result"]
        assert row["error"] == "timeout" and row["verdict"] == "unchecked"
        event = threading.Event()
        event.set()
        row = extractor.run_checks(checks, reg=reg, cancel_event=event)[0]["result"]
        assert row["error"] == "cancelled" and row["verdict"] == "unchecked"
    finally:
        gate.set()


def test_combined_rows_and_citation_fit_backward_compatible_export_contract():
    import json
    import jsonschema
    text = "\n".join(["학습/검증/테스트 분할은 80/10/10이다."] * 8
                     + ["10 mS + 1 S/cm"] * 8 + ["DOI: 10.9999/local-only"])
    out = engine.finalize_plan(text, provider=empty_provider())
    assert out["code_selected_checks"] > 16
    assert any(r["kind"] == "citation" for r in out["tool_checks_before"])
    assert len(out["tool_checks_before"]) > 16
    schema = json.loads((ROOT / "contracts/finalization.schema.json").read_text(encoding="utf-8"))
    envelope = {"version": engine.VERSION, "assembled": {}, "finalization": out,
                "final_text": out["final_text"], "origin": "client_submitted_unverified", "finalization_sig": None}
    jsonschema.validate(envelope, schema)
    # Optional additions leave an existing v1 result valid.
    old = engine.finalize_plan("본문", provider=empty_provider())
    old.pop("code_selected_checks")
    old.pop("code_checks_label")
    old["counters"].pop("tool_runs")
    old["counters"].pop("tool_attempts")
    envelope.update(finalization=old, final_text=old["final_text"])
    jsonschema.validate(envelope, schema)


def test_audit_metadata_does_not_authorize_new_correction_numbers():
    numbers = engine._computed_numbers({}, {"status": "failed", "details": {
        "code_selected": True, "computed": "0.3", "evidence": {"elapsed_ms": 987.123},
        "anchors": [{"start": 543, "end": 654}]}})
    assert "0.3" in numbers
    assert not ({"987.123", "543", "654"} & numbers)
