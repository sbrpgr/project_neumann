"""FIX-AUTOFIX: code-owned numeric evidence and discarded model placeholders.

Captured-response tests use the saved input/checks, with explicitly reconstructed
corrections: the live response deliberately erased rejected replacement prose.
No live provider, socket connection, dotenv, or secret-value assertion is needed.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import socket

import pytest

from neumann.analyze import finalize as engine
from neumann.analyze.revise import PLACEHOLDER_RE
from neumann.llm import MockProvider


def scripted(assessment, edits):
    return MockProvider(scripted={
        engine.ASSESSMENT_TASK: [copy.deepcopy(assessment)],
        engine.CORRECTION_TASK: [{"edits": copy.deepcopy(edits)}],
    })


def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline regression must not connect to a socket")
    monkeypatch.setattr(socket.socket, "connect", denied)


def numeric_case(replacement, *, linked=False):
    text = "GPU 8장 × 72시간 = 500 GPU시간을 쓴다."
    issue = {"issue_id": "i", "kind": "physical", "plan_lines": [1],
             "message": "계산 확인", "check_ids": ["code:unit_derive-1-1"] if linked else []}
    return text, {"issues": [issue], "checks": []}, [{
        "line": 1, "current_text": text, "replacement": replacement, "issue_ids": ["i"]}]


@pytest.mark.parametrize("linked", [False, True])
def test_exact_code_computed_result_can_correct_body_with_or_without_model_check_id(monkeypatch, linked):
    deny_network(monkeypatch)
    text, assessment, edits = numeric_case("GPU 8장 × 72시간 = 576 GPU시간을 쓴다.", linked=linked)
    out = engine.finalize_plan(text, provider=scripted(assessment, edits))
    assert out["corrections"][0]["applied"]
    assert out["final_text"] == edits[0]["replacement"]
    assert out["tool_checks_before"][0]["details"]["computed"] == 576
    assert out["tool_checks_after"][0]["status"] == "passed"


@pytest.mark.parametrize("suffix", [
    " [확인 필요: 신약 임상 결과가 우수함]",
    " [확인 필요 항목 합계]",
    " 999를 쓴다.",
])
def test_rejected_numeric_proposal_uses_only_original_line_and_code_warning(monkeypatch, suffix):
    deny_network(monkeypatch)
    text, assessment, edits = numeric_case("GPU 8장 × 72시간 = 500 GPU시간을 쓴다." + suffix)
    out = engine.finalize_plan(text, provider=scripted(assessment, edits))
    assert out["corrections"][0]["applied"]
    assert out["final_text"] == text + " [확인 필요: 계산 불일치 — 계산값 576GPU시간, 표기 500GPU시간]"
    assert not engine._placeholder_problem(out["final_text"], engine._grounded_words(text))
    assert suffix not in json.dumps(out, ensure_ascii=False)
    assert out["status"] == "partial"
    assert out["tool_checks_after"][0]["status"] == "failed"
    assert any("코드가 생성" in notice for notice in out["notices"])


def test_unsafe_proposal_is_still_rejected_even_for_a_numeric_failure(monkeypatch):
    deny_network(monkeypatch)
    text, assessment, edits = numeric_case("GPU 8장 × 72시간 = 576 GPU시간을 쓴다. <script>x</script>")
    out = engine.finalize_plan(text, provider=scripted(assessment, edits))
    assert out["corrections"][0]["reason"] == "unsafe_markup"
    assert out["final_text"] == text


def test_valid_placeholder_for_an_unlinked_issue_still_shows_the_code_computation(monkeypatch):
    deny_network(monkeypatch)
    text, assessment, edits = numeric_case(
        "GPU 8장 × 72시간 = 500 GPU시간을 쓴다. [확인 필요: 계산값 576]")
    out = engine.finalize_plan(text, provider=scripted(assessment, edits))
    assert out["corrections"][0]["applied"]
    assert "계산값 576GPU시간, 표기 500GPU시간" in out["final_text"]
    assert "SEMANTIC_REVIEW" not in out["final_text"]
    assert any("코드가 생성" in notice for notice in out["notices"])


def test_unchecked_or_out_of_scope_results_do_not_authorize_numeric_body():
    lines = ["GPU 8장 × 72시간 = 500 GPU시간을 쓴다.", "별도 방법을 검토한다."]
    checks, rows = engine._run_code_checks("\n".join(lines), None)
    by_id = {c["check_id"]: c for c in checks}
    row_map = {r["check_id"]: r for r in rows}
    assert engine._numeric_failure(1, {1}, by_id, row_map, lines)
    assert not engine._numeric_failure(2, {2}, by_id, row_map, lines)
    assert not engine._numeric_failure(1, {2}, by_id, row_map, lines)
    rows[0]["status"] = "unchecked"
    assert not engine._numeric_failure(1, {1}, by_id, row_map, lines)


def test_split_sum_has_no_output_anchor_and_cannot_authorize_new_allocations():
    lines = ["학습/검증/테스트 분할은 80/10/20이다."]
    checks, rows = engine._run_code_checks(lines[0], None)
    assert rows[0]["status"] == "failed"
    assert not engine._numeric_failure(1, {1}, {c["check_id"]: c for c in checks},
                                       {r["check_id"]: r for r in rows}, lines)


def test_string_computed_template_uses_no_metadata_or_stated_input_as_permission():
    row = {"status": "failed", "details": {"code_selected": True, "computed": "0.3",
           "expected": 99, "total": 88, "converted": 77, "elapsed_ms": 66}}
    assert engine._computed_numbers({}, row) == {"0.3"}
    template = engine._placeholder_template(["i"], {"i": {"plan_lines": [1], "check_ids": ["code:c"]}},
        {"code:c": {"kind": "constraint", "plan_lines": [1]}}, {"code:c": row})
    assert "계산값 0.3" in template
    assert all(value not in template for value in ("99", "88", "77", "66"))
    assert PLACEHOLDER_RE.fullmatch(template)


def captured_case(path: Path, *, exact=False):
    saved = json.loads(path.read_text(encoding="utf-8"))["finalization"]
    text = saved["input_text"]
    # Tool evidence preserved each actual model check, including anchored params.
    checks = [r["evidence"]["input"]["check"] for r in saved["tool_checks_before"]
              if not r["check_id"].startswith("code:")]
    for check in checks:
        for source in check["params"]["sources"]:
            source.pop("quote", None)  # code attached these after the model schema gate
    links = {"I2": ["C1"], "I3": ["C2"], "I4": ["C3"]}
    issues = [{k: i[k] for k in ("issue_id", "kind", "plan_lines", "message")} |
              {"check_ids": links.get(i["issue_id"], [])}
              for i in saved["issues"] if not i["issue_id"].startswith("tool:")]
    lines = text.splitlines()
    if exact:
        proposed = {
            14: (lines[13].replace("10시간", "27.7777777778시간"), "I1"),
            15: (lines[14].replace("500", "576"), "I2"),
            36: (lines[35].replace("12개월", "10개월"), "I3"),
            44: (lines[43].replace("6억 원", "500000000 원"), "I4"),
        }
    else:
        # Reconstruct the observed 4/3/1 rejection classes, never claim these
        # invented regression proposals were the erased live model response.
        proposed = {
            11: (lines[10], "I7"),
            14: (lines[13].replace("10시간", "27.7777777778시간"), "I1"),
            15: (lines[14].replace("500", "576"), "I2"),
            21: (lines[20].replace("1.", "2."), "I6"),
            23: (lines[22].replace("6.", "5."), "I10"),
            27: (lines[26].replace("[확인 필요:", "[확인 필요"), "I8"),
            36: (lines[35] + " [확인 필요: 단계별 소요기간 검토]", "I3"),
            44: (lines[43] + " [확인 필요: 지출액 검토]", "I4"),
        }
    edits = [{"line": no, "current_text": lines[no - 1], "replacement": after, "issue_ids": [iid]}
             for no, (after, iid) in proposed.items()]
    return saved, text, {"issues": issues, "checks": checks}, edits


CAPTURE = Path(__file__).resolve().parents[3] / "final-live/data/final_test/final_live3c/finalize.json"


@pytest.mark.skipif(not CAPTURE.is_file(), reason="Saved live artifact is local and must not be committed")
@pytest.mark.parametrize("exact", [False, True], ids=["reconstructed-eight", "exact-tool-values"])
def test_saved_seeded_input_applies_four_sum_and_unit_corrections_offline(monkeypatch, exact):
    deny_network(monkeypatch)
    saved, text, assessment, edits = captured_case(CAPTURE, exact=exact)
    out = engine.finalize_plan(text, provider=scripted(assessment, edits))
    assert sum(c["applied"] for c in saved["corrections"]) == 0
    assert {c["line"] for c in out["corrections"] if c["applied"]} == {14, 15, 36, 44}
    rows = {r["check_id"]: r for r in out["tool_checks_after"]}
    for cid in ("code:unit_derive-14-2", "code:unit_derive-15-1", "code:schedule_sum-33-1", "code:table_sum-41-1"):
        expected = "passed" if exact or "unit_derive" in cid else (
            "unchecked" if "schedule_sum" in cid else "failed")
        assert rows[cid]["status"] == expected
    assert out["status"] == "partial"  # structural/semantic issues remain visible
