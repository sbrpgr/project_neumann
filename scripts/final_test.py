"""Sequential final-flow runner. No .env loading, keys, or raw response logging.

Mock: python scripts/final_test.py --url http://127.0.0.1:8156 --mock
Live: requires explicit operator approval AND the process-only live permission.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import uuid
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "src/neumann/api/templates/samples.json"
DEFAULT_SAMPLES = ["example-battery", "example-binding", "example-operator"]
STATES = {"ok", "done", "degraded", "error", "queued", "running", "completed",
          "partial", "incomplete", "passed", "failed", "unchecked", "skipped", "unavailable", "mock", "astra", "rule"}


class Failure(Exception):
    def __init__(self, code: str, http_status: int | None = None):
        self.code, self.http_status = code, http_status


def state(value):
    return value if isinstance(value, str) and value in STATES else "unknown"


def authorize(url: str, mock: bool, approval: bool, live_allowed: bool) -> str:
    """Pure guard: approval must precede even the first network request."""
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        raise Failure("invalid_url") from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise Failure("invalid_url")
    if port in {8099, 8171}:
        raise Failure("forbidden_port")
    if mock:
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or not port or not 8100 <= port <= 8199:
            raise Failure("mock_requires_local_81xx")
        return "mock"
    if not approval or not live_allowed:
        raise Failure("live_requires_approval_and_process_flag")
    return "live"


def samples(names):
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["samples"]
    allowed = {s["id"]: s for s in catalog if s.get("public_ok")}
    selected = []
    for name in names:
        item = allowed.get(name)
        if item is None:
            item = next((s for s in allowed.values() if name == s["path"] or name == Path(s["path"]).name), None)
        if item is None:
            raise Failure("unknown_or_nonpublic_sample")
        path = (ROOT / item["path"]).resolve()
        if not path.is_relative_to(ROOT):
            raise Failure("sample_outside_repository")
        selected.append((item["id"], path))
    if not 2 <= len(selected) <= 3 or len({s[0] for s in selected}) != len(selected):
        raise Failure("select_two_or_three_distinct_samples")
    return selected


@contextmanager
def single_run(root):
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".runner.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise Failure("another_runner_active") from None
    os.close(fd)
    try:
        yield
    finally:
        lock.unlink()


def json_request(client, method, path, payload=None):
    response = client.request(method, path, json=payload)
    if not 200 <= response.status_code < 300:
        # Never copy arbitrary server errors, headers, body, or URL into logs.
        raise Failure("http_error", response.status_code)
    try:
        body = response.json()
    except ValueError:
        raise Failure("invalid_json", response.status_code) from None
    if not isinstance(body, dict):
        raise Failure("invalid_response_shape", response.status_code)
    return body


def record_stage(case, name, operation):
    row = {"stage": name, "status": "running"}
    case["stages"].append(row)
    start = time.monotonic()
    try:
        result = operation(row)
        row["status"] = "passed"
        return result
    except KeyboardInterrupt:
        row["status"] = "failed"
        row["error_code"] = "interrupted"
        case["failed_stage"] = name
        raise
    except Exception as exc:
        row["status"] = "failed"
        row["error_code"] = exc.code if isinstance(exc, Failure) else "unexpected_error"
        if isinstance(exc, Failure) and exc.http_status is not None:
            row["http_status"] = exc.http_status
        case["failed_stage"] = name
        raise
    finally:
        row["elapsed_s"] = round(time.monotonic() - start, 3)


def tool_summary(report):
    rows = []
    for phase in ("before", "after"):
        for check in report.get("tool_checks_" + phase, []):
            rows.append({"phase": phase, "tool": check.get("tool") if check.get("tool") in {"z3", "pint", "networkx", "none"} else "unknown",
                         "status": state(check.get("status")),
                         "line_count": len(check.get("plan_lines", []))})
    return {"checks": rows, "coverage": {tool: sum(r["tool"] == tool for r in rows)
                                         for tool in ("z3", "pint", "networkx")}}


def probe_checks(text):
    """Explicit synthetic appendix for tool smoke checks; never scientific evidence."""
    marker = "## FINAL-TEST synthetic tool probes"
    lines = text.splitlines()
    try:
        start = lines.index(marker)
    except ValueError:
        raise Failure("tool_probe_appendix_missing") from None
    expected = ["총 3", "항목 4", "최대 10", "합산 3 m", "4 cm", "수집 완료 후 분석 시작"]
    if lines[start + 1:start + 7] != expected:
        raise Failure("tool_probe_appendix_changed")
    def sources(indices):
        return [{"line": start + i + 2, "quote": expected[i]} for i in indices]
    return [
        {"check_id": "final_test_sum", "kind": "constraint", "plan_lines": [s["line"] for s in sources([0, 1, 2])],
         "params": {"sources": sources([0, 1, 2]), "operation": "sum", "terms": [{"source": 0, "value": 3}, {"source": 1, "value": 4}], "comparator": "le", "limit": {"source": 2, "value": 10}}},
        {"check_id": "final_test_units", "kind": "units", "plan_lines": [s["line"] for s in sources([3, 4])],
         "params": {"sources": sources([3, 4]), "operation": "addition", "left": {"source": 0, "value": 3, "unit": "m"}, "right": {"source": 1, "value": 4, "unit": "cm"}}},
        {"check_id": "final_test_dag", "kind": "dependency", "plan_lines": [sources([5])[0]["line"]],
         "params": {"sources": sources([5]), "nodes": [{"id": "a", "source": 0, "phrase": "수집"}, {"id": "b", "source": 0, "phrase": "분석"}], "edges": [{"from": "a", "to": "b", "source": 0, "phrase": expected[5]}]}}
    ]


PROBE_APPENDIX = "\n\n## FINAL-TEST synthetic tool probes\n총 3\n항목 4\n최대 10\n합산 3 m\n4 cm\n수집 완료 후 분석 시작\n"


def run_case(client, sample, directory, finalize_path, args):
    case = {"sample": sample[0], "status": "failed", "stages": []}
    try:
        def input_stage(row):
            text = sample[1].read_text(encoding="utf-8")
            row["input_chars"] = len(text)
            return text
        text = record_stage(case, "input", input_stage)
        job = record_stage(case, "analysis_submit", lambda row: json_request(client, "POST", "/premortem/jobs", {"plan_text": text, "filename": sample[1].name, "format": "view"}))
        def poll(row):
            job_id = job.get("job_id")
            if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", job_id):
                raise Failure("invalid_job_id")
            deadline = time.monotonic() + args.job_timeout
            row["polls"] = 0
            while time.monotonic() < deadline:
                current = json_request(client, "GET", "/premortem/jobs/" + job_id)
                row["polls"] += 1
                row["job_status"] = state(current.get("status"))
                if current.get("status") == "error":
                    raise Failure("analysis_job_failed")
                if current.get("status") == "done":
                    view = current.get("result")
                    if not isinstance(view, dict) or not isinstance(view.get("result"), dict):
                        raise Failure("analysis_result_missing")
                    return view
                time.sleep(min(max(args.poll_interval, float(current.get("poll_after_s", 1.5))), max(deadline - time.monotonic(), 0)))
            raise Failure("analysis_poll_timeout")
        view = record_stage(case, "analysis_poll", poll)
        result = view["result"]
        case["analysis_status"] = state(result.get("status"))
        cards = result.get("risk_cards", [])
        case["card_count"] = len(cards)
        case["generators"] = sorted({state(c.get("generator")) for c in cards})
        case["analysis_stages"] = [{"stage": s.get("stage") if s.get("stage") in {"plan_normalize", "fitness", "query_axes", "search", "extract_issues", "synthesize_cards", "verify_evidence", "expected_review", "checklist", "semantic_validate"} else "unknown", "status": state(s.get("state")), "elapsed_s": s.get("elapsed_s", 0)} for s in result.get("stages", [])]
        def adopt(row):
            if not cards:
                raise Failure("no_cards_to_adopt")
            row["adopted_cards"] = len(cards)
            return [c["card_id"] for c in cards]
        ids = record_stage(case, "adopt_all_cards", adopt)
        base = {"plan_text": text, "result": result, "result_sig": view.get("result_sig")}
        revision = record_stage(case, "revise", lambda row: json_request(client, "POST", "/premortem/revise", {**base, "card_ids": ids}))
        edits = [e for r in revision.get("revisions", []) for e in r.get("edits", [])]
        case["revision_count"], case["edit_count"] = len(revision.get("revisions", [])), len(edits)
        def adopt_edits(row):
            if not edits:
                raise Failure("no_edits_to_adopt")
            row["adopted_edits"] = len(edits)
            return [{"edit_id": e["edit_id"], "decision": "채택"} for e in edits]
        decisions = record_stage(case, "adopt_all_edits", adopt_edits)
        assembly_body = {**base, "revision": revision, "revision_sig": revision.get("revision_sig"), "decisions": decisions, "polish": False, "format": "json"}
        assembled = record_stage(case, "assemble", lambda row: json_request(client, "POST", "/premortem/revise/assemble", assembly_body))
        case["assembly_stats"] = {k: v for k, v in assembled.get("stats", {}).items() if k in {"applied", "conflicts", "adopted", "rejected", "modified"} and isinstance(v, int)}
        def prepare_final(row):
            confirmed = assembled["revised_text"]
            if args.tool_probes:
                confirmed += PROBE_APPENDIX
            body = {**assembly_body, "submission_id": "final_test_" + uuid.uuid4().hex,
                    "confirmed_text": confirmed, "confirmed_base_id": assembled["revised_plan_id"]}
            if args.tool_probes:
                body["checks"] = probe_checks(confirmed)
            row["synthetic_appendix"] = bool(args.tool_probes)
            return body
        final_body = record_stage(case, "confirm_revision", prepare_final)
        final = record_stage(case, "finalize", lambda row: json_request(client, "POST", finalize_path, final_body))
        def complete(row):
            report = final.get("finalization", {})
            draft = final.get("final_text")
            if not isinstance(draft, str) or not draft.strip():
                raise Failure("empty_final_draft")
            case["final_status"] = state(report.get("status"))
            case["final_generator"] = state(report.get("generator"))
            case["final_draft_chars"] = len(draft)
            case["correction_count"] = len(report.get("corrections", []))
            case["applied_corrections"] = sum(bool(c.get("applied")) for c in report.get("corrections", []))
            case["tools"] = tool_summary(report)
            case["counters"] = {k: v for k, v in report.get("counters", {}).items() if k in {"assessment_calls", "correction_calls", "correction_batches", "recheck_runs"} and isinstance(v, int)}
            if report.get("status") not in {"completed", "partial"}:
                raise Failure("finalization_incomplete")
            if args.tool_probes and any(not any(r["tool"] == tool and r["status"] == "passed" for r in case["tools"]["checks"]) for tool in ("z3", "pint", "networkx")):
                raise Failure("tool_probe_not_passed")
            return draft
        draft = record_stage(case, "complete", complete)
        def export(row):
            response = client.post("/premortem/package", json={**base, "revision": revision,
                "revision_sig": revision.get("revision_sig"), "revision_decisions": decisions,
                "revised_plan": final["assembled"], "decisions": [{"card_id": i, "decision": "채택"} for i in ids]})
            if response.status_code != 200:
                raise Failure("http_error", response.status_code)
            try:
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    if archive.testzip() is not None or not {"manifest.json", "revision.json", "revised_plan.md"}.issubset(archive.namelist()):
                        raise Failure("incomplete_export_zip")
                    members = {name: archive.read(name) for name in archive.namelist()}
            except zipfile.BadZipFile:
                raise Failure("invalid_export_zip") from None
            # Current package API exports assembly. Add the actual final draft as
            # an explicitly runner-added artifact, without changing server files.
            members["final_draft.md"] = draft.encode("utf-8")
            members["final_test_validation.json"] = json.dumps({"origin": "final_test_runner_added",
                "notice": "Tool probes are synthetic smoke checks, not validation of the research.",
                "final_status": case["final_status"], "tools": case["tools"], "counters": case["counters"]}, ensure_ascii=False, indent=2).encode("utf-8")
            target = directory / (sample[0] + ".zip")
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, data in members.items():
                    archive.writestr(name, data)
            row.update(zip_files=len(members), zip_bytes=target.stat().st_size, zip_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        record_stage(case, "export_zip", export)
        case["status"] = "passed"
    except KeyboardInterrupt:
        case["error_code"] = "interrupted"
    except Exception as exc:
        case.setdefault("failed_stage", (case["stages"][-1]["stage"] + "_response_validation") if case["stages"] else "input")
        case["error_code"] = exc.code if isinstance(exc, Failure) else "unexpected_error"
    return case


def save_summary(directory, summary):
    (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# FINAL-TEST", "", f"Status: {summary['status']}; mode: {summary['mode']}; concurrency: 1.",
             "Mock/partial/degraded statuses describe product output; passed describes the runner flow.",
             f"Synthetic tool probes: {summary['tool_probes']}.", "",
             "| Sample | Flow | Cards | Edits | Applied edits | Conflicts | Corrections | Final status | Draft chars | Failed stage |",
             "|---|---|---:|---:|---:|---:|---:|---|---:|---|"]
    for case in summary["cases"]:
        stats = case.get("assembly_stats", {})
        lines.append(f"| {case['sample']} | {case['status']} | {case.get('card_count', 0)} | {case.get('edit_count', 0)} | {stats.get('applied', 0)} | {stats.get('conflicts', 0)} | {case.get('applied_corrections', 0)} | {case.get('final_status', 'unknown')} | {case.get('final_draft_chars', 0)} | {case.get('failed_stage', '')} |")
    if summary.get("error_code"):
        lines += ["", "Preflight failure: " + summary["error_code"]]
    for case in summary["cases"]:
        lines += ["", "## " + case["sample"], "", "| Stage | Status | Seconds |", "|---|---|---:|"]
        lines += [f"| {r['stage']} | {r['status']} | {r['elapsed_s']} |" for r in case["stages"]]
        lines += ["", "Tools: " + json.dumps(case.get("tools", {}), ensure_ascii=False)]
    (directory / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8020")
    parser.add_argument("--samples", nargs="+", default=DEFAULT_SAMPLES)
    parser.add_argument("--mock", action="store_true", help="Only local 81xx; verify health reports mock before analysis")
    parser.add_argument("--i-have-approval", action="store_true")
    parser.add_argument("--tool-probes", action="store_true", help="Append synthetic checks at manuscript confirmation (mock only)")
    parser.add_argument("--request-timeout", type=float, default=180)
    parser.add_argument("--job-timeout", type=float, default=900)
    parser.add_argument("--poll-interval", type=float, default=1.5)
    args = parser.parse_args(argv)
    try:
        mode = authorize(args.url, args.mock, args.i_have_approval, os.environ.get("NEUMANN_LIVE_LLM_OK") == "1")
        if args.tool_probes and mode != "mock":
            raise Failure("synthetic_probes_mock_only")
        if min(args.request_timeout, args.job_timeout, args.poll_interval) <= 0:
            raise Failure("timeouts_must_be_positive")
        selected = samples(args.samples)
    except (Failure, ValueError) as exc:
        print("FINAL-TEST refused: " + (exc.code if isinstance(exc, Failure) else "invalid_arguments"))
        return 2
    root = ROOT / "data/final_test"
    try:
        with single_run(root):
            directory = root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
            directory.mkdir()
            summary = {"status": "failed", "mode": mode, "tool_probes": args.tool_probes, "concurrency": 1, "cases": []}
            start = time.monotonic()
            try:
                with httpx.Client(base_url=args.url.rstrip("/"), timeout=args.request_timeout, trust_env=False, follow_redirects=False) as client:
                    health = json_request(client, "GET", "/health")
                    effective = health.get("llm", {}).get("effective")
                    if mode == "mock" and effective != "mock":
                        raise Failure("target_is_not_mock")
                    if mode == "live" and effective != "openai":
                        raise Failure("target_is_not_live_openai")
                    queue = json_request(client, "GET", "/queue/status")
                    if queue.get("max_concurrent", queue.get("limits", {}).get("max_concurrent")) != 1:
                        raise Failure("server_max_concurrent_must_be_one")
                    paths = json_request(client, "GET", "/openapi.json").get("paths", {})
                    finalize_path = next((p for p in ("/premortem/finalize", "/premortem/revise/finalize") if "post" in paths.get(p, {})), None)
                    if finalize_path is None:
                        raise Failure("finalize_endpoint_missing")
                    summary["finalize_endpoint"] = finalize_path
                    for sample in selected:
                        summary["cases"].append(run_case(client, sample, directory, finalize_path, args))
                        save_summary(directory, summary)
                        if summary["cases"][-1]["status"] != "passed":
                            break
                    summary["status"] = "passed" if len(summary["cases"]) == len(selected) and all(c["status"] == "passed" for c in summary["cases"]) else "failed"
            except KeyboardInterrupt:
                summary["failed_stage"] = "preflight"
                summary["error_code"] = "interrupted"
            except Exception as exc:
                summary["failed_stage"] = "preflight"
                summary["error_code"] = exc.code if isinstance(exc, Failure) else "connection_or_response_error"
            finally:
                summary["elapsed_s"] = round(time.monotonic() - start, 3)
                save_summary(directory, summary)
            print(f"FINAL-TEST {summary['status']}: {len(summary['cases'])}/{len(selected)} cases; data/final_test/{directory.name}/summary.json")
            return 0 if summary["status"] == "passed" else 1
    except Failure as exc:
        print("FINAL-TEST refused: " + exc.code)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
