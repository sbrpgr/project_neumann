"""Runner guards and failure reports. Never assert or print environment values."""
import argparse
import io
import json
import zipfile

import httpx
import pytest

from scripts import final_test as ft


@pytest.mark.parametrize("approval,allowed", [(False, False), (False, True), (True, False)])
def test_live_guard_requires_both(approval, allowed):
    with pytest.raises(ft.Failure) as error:
        ft.authorize("http://127.0.0.1:8020", False, approval, allowed)
    assert error.value.code == "live_requires_approval_and_process_flag"


def test_pure_live_guard_accepts_explicit_authorization():
    # A pure function test; does not enable a live process or send any request.
    assert ft.authorize("http://127.0.0.1:8020", False, True, True) == "live"


@pytest.mark.parametrize("url", ["http://127.0.0.1:8020", "http://example.org:8156",
    "http://127.0.0.1:8171", "http://127.0.0.1:8099", "http://user:password@localhost:8156",
    "http://localhost:8156/?auth=value", "http://localhost:8156/#value", "http://localhost:bad"])
def test_mock_guard_rejects_unsafe_target(url):
    with pytest.raises(ft.Failure):
        ft.authorize(url, True, False, False)


def test_unapproved_cli_makes_no_network_call(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("unapproved runner attempted network")
    monkeypatch.setattr(ft.httpx, "Client", forbidden)
    assert ft.main([]) == 2
    assert "live_requires_approval" in capsys.readouterr().out


def test_samples_are_public_catalog_entries():
    assert [s[0] for s in ft.samples(ft.DEFAULT_SAMPLES)] == ft.DEFAULT_SAMPLES
    assert len(ft.samples(["electrolyte_gnn.md", "protein_ligand_affinity.md"])) == 2  # SAMPLES 5158382: example-battery 파일명
    for names in (["../.env", "example-binding"], ["example-battery"], ["example-battery"] * 2):
        with pytest.raises(ft.Failure):
            ft.samples(names)


def test_only_one_runner_and_lock_released(tmp_path):
    with ft.single_run(tmp_path):
        with pytest.raises(ft.Failure) as error:
            with ft.single_run(tmp_path):
                pass
        assert error.value.code == "another_runner_active"
    with ft.single_run(tmp_path):
        pass
    assert not (tmp_path / ".runner.lock").exists()


def test_http_error_body_is_never_exposed():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(422, json={"detail": "private-body-marker"})), base_url="http://test") as client:
        with pytest.raises(ft.Failure) as error:
            ft.json_request(client, "POST", "/premortem/jobs", {})
    assert error.value.code == "http_error" and error.value.http_status == 422
    assert "private-body-marker" not in str(error.value)


def test_failed_stage_persisted_without_raw_error(tmp_path):
    case = {"sample": "example-battery", "status": "failed", "stages": []}
    def fail(row):
        raise RuntimeError("private-error-marker")
    with pytest.raises(RuntimeError):
        ft.record_stage(case, "finalize", fail)
    ft.save_summary(tmp_path, {"status": "failed", "mode": "mock", "tool_probes": False, "cases": [case]})
    data = json.loads((tmp_path / "summary.json").read_text())
    assert data["cases"][0]["failed_stage"] == "finalize"
    assert data["cases"][0]["stages"][0]["elapsed_s"] >= 0
    assert "private-error-marker" not in (tmp_path / "summary.json").read_text()


def test_synthetic_checks_use_exact_input_lines():
    from neumann.analyze.final_tools import run_tool_checks
    text = "An original public sample.\n" + ft.PROBE_APPENDIX
    rows = run_tool_checks(text, ft.probe_checks(text))
    assert {r["tool"] for r in rows} == {"z3", "pint", "networkx"}
    assert all(r["status"] == "passed" for r in rows)
    with pytest.raises(ft.Failure):
        ft.probe_checks(text.replace("총 3", "총 5"))


def test_tool_summary_preserves_failed_and_unchecked_without_messages():
    summary = ft.tool_summary({"tool_checks_before": [
        {"tool": "z3", "status": "failed", "message": "private-marker", "plan_lines": [1]},
        {"tool": "pint", "status": "unchecked", "plan_lines": []}]})
    assert [r["status"] for r in summary["checks"]] == ["failed", "unchecked"]
    assert summary["coverage"]["networkx"] == 0
    assert "private-marker" not in json.dumps(summary)


def fake_flow(monkeypatch, tmp_path, fail=None, variant=None):
    calls = []
    result = {"status": "degraded", "risk_cards": [{"card_id": "c1", "generator": "mock"}]}
    revision = {"revisions": [{"edits": [{"edit_id": "e1"}]}]}
    assembled = {"revised_text": "public final draft", "revised_plan_id": "p1", "stats": {"applied": 1}}
    final = {"assembled": assembled, "final_text": assembled["revised_text"], "finalization": {"status": "partial", "generator": "mock", "corrections": []}}
    if variant == "no_cards":
        result["risk_cards"] = []
    if variant == "no_edits":
        revision["revisions"] = []
    if variant == "empty_final":
        final["final_text"] = ""
    if variant == "incomplete":
        final["finalization"]["status"] = "incomplete"
    def handler(request):
        path = request.url.path
        calls.append(path)
        body = json.loads(request.content) if request.content else {}
        if path == fail:
            return httpx.Response(500, json={"detail": "private-response-marker"})
        if path == "/premortem/jobs":
            return httpx.Response(202, json={"job_id": "j" * 32})
        if path.startswith("/premortem/jobs/"):
            if variant == "job_error":
                return httpx.Response(200, json={"status": "error"})
            if variant == "job_timeout":
                return httpx.Response(200, json={"status": "running", "poll_after_s": 0.01})
            return httpx.Response(200, json={"status": "done", "result": {"result": result}})
        if path == "/premortem/revise":
            assert body["card_ids"] == ["c1"]
            return httpx.Response(200, json=revision)
        if path == "/premortem/revise/assemble":
            assert body["decisions"] == [{"edit_id": "e1", "decision": "채택"}]
            return httpx.Response(200, json=assembled)
        if path == "/premortem/revise/finalize":
            assert body["confirmed_text"] == assembled["revised_text"]
            return httpx.Response(200, json=final)
        if path == "/premortem/package":
            if variant == "invalid_zip":
                return httpx.Response(200, content=b"invalid ZIP")
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                for name in ("manifest.json", "revision.json", "revised_plan.md"):
                    archive.writestr(name, "public")
            return httpx.Response(200, content=buffer.getvalue())
        pytest.fail("unexpected request path")
    sample = tmp_path / "public.md"
    sample.write_text("public sample")
    args = argparse.Namespace(tool_probes=False, job_timeout=1, poll_interval=0.01)
    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        case = ft.run_case(client, ("public-sample", sample), tmp_path, "/premortem/revise/finalize", args)
    return calls, case


def test_full_sequence_adopts_all_and_exports_actual_final_draft(monkeypatch, tmp_path):
    calls, case = fake_flow(monkeypatch, tmp_path)
    assert case["status"] == "passed" and case["final_status"] == "partial"
    assert calls == ["/premortem/jobs", "/premortem/jobs/" + "j" * 32, "/premortem/revise",
                     "/premortem/revise/assemble", "/premortem/revise/finalize", "/premortem/package"]
    with zipfile.ZipFile(tmp_path / "public-sample.zip") as archive:
        assert archive.read("final_draft.md").decode() == "public final draft"


@pytest.mark.parametrize("path,stage", [("/premortem/jobs", "analysis_submit"), ("/premortem/revise", "revise"),
    ("/premortem/revise/assemble", "assemble"), ("/premortem/revise/finalize", "finalize"), ("/premortem/package", "export_zip")])
def test_each_http_failure_stops_at_correct_stage(monkeypatch, tmp_path, path, stage):
    calls, case = fake_flow(monkeypatch, tmp_path, fail=path)
    assert case["status"] == "failed" and case["failed_stage"] == stage
    assert calls[-1] == path
    assert "private-response-marker" not in json.dumps(case)


@pytest.mark.parametrize("variant,stage,code", [
    ("job_error", "analysis_poll", "analysis_job_failed"),
    ("job_timeout", "analysis_poll", "analysis_poll_timeout"),
    ("no_cards", "adopt_all_cards", "no_cards_to_adopt"),
    ("no_edits", "adopt_all_edits", "no_edits_to_adopt"),
    ("empty_final", "complete", "empty_final_draft"),
    ("incomplete", "complete", "finalization_incomplete"),
    ("invalid_zip", "export_zip", "invalid_export_zip")])
def test_semantic_failures_are_reported(monkeypatch, tmp_path, variant, stage, code):
    _, case = fake_flow(monkeypatch, tmp_path, variant=variant)
    assert case["status"] == "failed" and case["failed_stage"] == stage
    assert case["error_code"] == code


@pytest.mark.parametrize("effective,concurrency,code", [("openai", 1, "target_is_not_mock"),
    ("mock", 2, "server_max_concurrent_must_be_one")])
def test_preflight_blocks_mutations_and_saves_safe_report(monkeypatch, tmp_path, effective, concurrency, code):
    calls = []
    def handler(request):
        calls.append(request.method)
        if request.url.path == "/health":
            return httpx.Response(200, json={"llm": {"effective": effective}})
        if request.url.path == "/queue/status":
            return httpx.Response(200, json={"limits": {"max_concurrent": concurrency}})
        pytest.fail("preflight made unauthorized request")
    factory = httpx.Client
    monkeypatch.setattr(ft, "ROOT", tmp_path)
    monkeypatch.setattr(ft.httpx, "Client", lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs))
    assert ft.main(["--url", "http://127.0.0.1:8156", "--mock"]) == 1
    assert set(calls) == {"GET"}
    summaries = list(tmp_path.glob("data/final_test/*/summary.json"))
    assert len(summaries) == 1
    assert json.loads(summaries[0].read_text())["error_code"] == code
