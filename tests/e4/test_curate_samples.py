"""Test synthetic variants of the shared fake fixture, never actual API results."""

from __future__ import annotations

import copy
import json
import socket
from pathlib import Path

import pytest

from neumann.api import samples as S
from neumann.api.sample_curation import OFFLINE_LABEL, generation_of, score_result
from scripts import curate_samples as C

ROOT = Path(__file__).resolve().parents[2]


def registry():
    return json.loads(S.REGISTRY_PATH.read_text(encoding="utf-8"))


def fixture_result():
    return json.loads((ROOT / "tests/fixtures/premortem_result.json").read_text(encoding="utf-8"))


def eligible_variant():
    """A test-only recorded-provenance variant for measuring eligibility branches."""
    result = fixture_result()
    result["notices"] = []
    result["stages"] = [{"name": "cards", "status": "ok", "impl": "synthetic-test"}]
    result["manifest"] = {"llm_provider": "openai", "llm_model": "gpt-6.1-sol"}
    cards = result["risk_cards"]
    for card in cards:
        card["generator"] = "astra"
        card["model"] = "gpt-6.1-sol"
    for index in range(2):
        card = copy.deepcopy(cards[index])
        card["card_id"] = "synthetic-test-card-" + str(index)
        cards.append(card)
    result["expected_review"] = {"generator": "astra", "strength": [], "request": [],
                                  "weakness": [{"t": "Test sentence", "c": cards[0]["evidence"][:1],
                                                "cards": [cards[0]["card_id"]]}]}
    result["checklist"] = [{"card_id": c["card_id"], "generator": "astra", "evidence": c["evidence"][:1],
                            "action": "Test action"} for c in cards]
    result["domain"] = registry()["samples"][0]["domain"]
    result["plan_checks"] = {"fitness": {"analyze": True, "verdict": "fit", "field": "battery", "generator": "astra"}}
    result["verification"] = {"linkage_rate": 1.0, "checklist_evidence": {"dropped": 0}}
    return result


def score(result):
    r = registry()
    return score_result(result, r["samples"][0], r["fields"][0])


def test_fixture_scores_as_mock_never_eligible():
    measured = score(fixture_result())
    assert measured["generation"] == "mock" and not measured["eligible"]
    assert 0 <= measured["score"] < 100
    assert "선별 불가" in measured["reason"]


def test_unsupported_review_sentence_is_not_exported():
    result = eligible_variant()
    result["expected_review"]["weakness"][0].update(t="Unsupported assertion", c=[])
    assert score(result)["review_first_line"] == ""


def test_complete_measurements_and_absent_revision_denominator():
    measured = score(eligible_variant())
    assert measured["eligible"] and measured["score"] == 100
    assert sum(measured["breakdown"].values()) == 95
    assert "revision_evidence" not in measured["breakdown"]
    assert measured["generation"] == "라이브 gpt-6.1-sol"
    assert any(w["card_ids"] for w in measured["weakness_matches"])


@pytest.mark.parametrize("mutate,check", [
    (lambda r: r["plan_checks"]["fitness"].update(analyze=False), "gate"),
    (lambda r: r["plan_checks"]["fitness"].update(verdict="unfit"), "gate"),
    (lambda r: r["plan_checks"].update(input_quality={"analyze": False}), "gate"),
    (lambda r: r.update(status="degraded"), "no_degradation"),
    (lambda r: r["stages"][0].update(status="error"), "no_degradation"),
    (lambda r: r["risk_cards"][0].update(generator="rule"), "no_degradation"),
    (lambda r: r.update(risk_cards=r["risk_cards"][:2]), "card_count"),
    (lambda r: r["risk_cards"][0].update(evidence=[]), "evidence_linkage"),
    (lambda r: r["verification"].update(linkage_rate=0.9), "evidence_linkage"),
    (lambda r: r["expected_review"]["weakness"][0].update(c=[]), "review_evidence"),
    (lambda r: r["expected_review"]["weakness"][0].update(c=["unknown"]), "review_evidence"),
    (lambda r: r["expected_review"]["weakness"][0].update(cards=["unknown"]), "review_evidence"),
    (lambda r: r.update(expected_review={}), "review_evidence"),
    (lambda r: r["checklist"][0].update(evidence=[]), "checklist_evidence"),
    (lambda r: r["checklist"][0].update(evidence=["unknown"]), "checklist_evidence"),
    (lambda r: r["checklist"][0].update(card_id="unknown"), "checklist_evidence"),
    (lambda r: r["verification"]["checklist_evidence"].update(dropped=1), "checklist_evidence"),
    (lambda r: r["verification"].pop("checklist_evidence"), "checklist_evidence"),
    (lambda r: r.update(domain="travel", plan_checks={"fitness": {"analyze": True, "field": "travel"}}), "domain"),
    (lambda r: r["plan_checks"].update(revision_advice={"items": [{"evidence": []}]}), "revision_evidence"),
])
def test_each_failed_measurement_lowers_score_and_blocks_selection(mutate, check):
    result = eligible_variant()
    mutate(result)
    measured = score(result)
    assert not measured["checks"][check]
    assert measured["score"] < 100 and not measured["eligible"]


def test_checklist_cannot_cite_another_cards_evidence():
    result = eligible_variant()
    result["checklist"][0]["evidence"] = result["risk_cards"][1]["evidence"][:1]
    assert score(result)["checks"]["checklist_evidence"] is False


@pytest.mark.parametrize("change,expected", [
    (lambda r: r["manifest"].update(llm_provider="mock"), "mock"),
    (lambda r: r["risk_cards"][0].update(generator="mock"), "mock"),
    (lambda r: r["stages"][0].update(impl="fixture"), "mock"),
    (lambda r: r["notices"].append("[FAKE] test fixture"), "mock"),
    (lambda r: r.update(manifest={}), "unknown"),
    (lambda r: r["manifest"].update(llm_model=None), "unknown"),
    (lambda r: r.update(manifest={"llm_provider": "rule"}), "rule"),
    (lambda r: r.update(manifest={"generation": OFFLINE_LABEL}), OFFLINE_LABEL),
])
def test_generation_is_recorded_not_assumed(change, expected):
    result = eligible_variant()
    change(result)
    measured = score(result)
    assert measured["generation"] == expected
    assert measured["eligible"] == (expected == OFFLINE_LABEL)


def test_mock_provenance_takes_priority_over_offline_label():
    result = fixture_result()
    result["manifest"] = {"generation": OFFLINE_LABEL}
    assert generation_of(result) == "mock"


def saved_rows(tmp_path, result=None, name="result.json"):
    path = tmp_path / name
    C.write_json(path, result or eligible_variant())
    return C.read_results([path])


def test_matching_prefers_plan_id_and_rejects_ambiguity(tmp_path):
    rows = saved_rows(tmp_path, name="not-the-result-hint.json")
    item = registry()["samples"][0]
    assert C.match_result(item, rows) is rows[0]
    with pytest.raises(ValueError, match="둘 이상"):
        C.match_result(item, rows + rows)
    rows[0]["result"]["plan_id"] = "0" * 64
    rows[0]["path"] = Path("plan.result.json")
    assert C.match_result(item, rows) is None  # A filename hint cannot override a known plan hash.


def test_case_hint_used_only_when_no_plan_id_and_never_public(tmp_path):
    rows = saved_rows(tmp_path, name="matching-case.json")
    item = registry()["samples"][5]
    item["source_test"]["result_hint"] = "matching-*.json"
    assert C.match_result(item, rows) is rows[0]
    assert item["public_ok"] is False and item["path"] is None


def test_apply_only_changes_curation(tmp_path):
    before = registry()
    ranked = C.curate(before, saved_rows(tmp_path))
    updated = C.apply_scores(before, ranked, "2026-09-30T15:00:00+00:00")
    assert S.registry_errors(updated) == []
    for old, new in zip(before["samples"], updated["samples"]):
        assert {k: v for k, v in old.items() if k != "curation"} == {k: v for k, v in new.items() if k != "curation"}
    assert updated["samples"][0]["curation"]["score"] == 100
    assert updated["samples"][0]["curation"]["checked_by_human"] is False


def test_feature_requires_human_public_approval_and_verified_result(tmp_path):
    r = registry()
    rows = saved_rows(tmp_path)
    r = C.apply_scores(r, C.curate(r, rows), "now")
    r["samples"][0]["status"] = "candidate"
    with pytest.raises(ValueError, match="사람 확인"):
        C.feature(r, "example-battery", confirmed=False)
    featured = C.feature(r, "example-battery", confirmed=True)
    assert featured["samples"][0]["status"] == "featured"
    assert featured["samples"][0]["curation"]["checked_by_human"] is True
    r["samples"][0]["public_ok"] = False
    with pytest.raises(ValueError, match="공개 승인"):
        C.feature(r, "example-battery", confirmed=True)


def test_feature_blocks_mock_even_when_score_forged(tmp_path):
    r = registry()
    rows = saved_rows(tmp_path, fixture_result())
    r = C.apply_scores(r, C.curate(r, rows), "now")
    r["samples"][0]["curation"].update(score=100, generation="라이브 gpt-6.1-sol")
    with pytest.raises(ValueError, match="선별 조건"):
        C.feature(r, "example-battery", confirmed=True)


def test_feature_rechecks_hash_not_just_saved_score(tmp_path):
    r = registry()
    rows = saved_rows(tmp_path)
    r = C.apply_scores(r, C.curate(r, rows), "now")
    result = eligible_variant()
    result["notices"].append("changed")
    C.write_json(rows[0]["path"], result)
    with pytest.raises(ValueError, match="바뀌었습니다"):
        C.feature(r, "example-battery", confirmed=True)


def test_changed_result_invalidates_human_confirmation(tmp_path):
    r = registry()
    rows = saved_rows(tmp_path)
    r = C.apply_scores(r, C.curate(r, rows), "now")
    r = C.feature(r, "example-battery", confirmed=True)
    unchanged = C.apply_scores(r, C.curate(r, rows), "later")
    assert unchanged["samples"][0]["curation"]["checked_by_human"] is True
    rows[0]["sha256"] = "0" * 64
    changed = C.apply_scores(r, C.curate(r, rows), "later")
    assert changed["samples"][0]["curation"]["checked_by_human"] is False


def test_cli_score_read_only_and_html_escaped(tmp_path, capsys):
    regpath = tmp_path / "registry.json"
    C.write_json(regpath, registry())
    before = regpath.read_bytes()
    result = eligible_variant()
    result["expected_review"]["weakness"][0]["t"] = '<script>alert("test")</script>'
    rows = saved_rows(tmp_path, result)
    output = tmp_path / "report"
    assert C.main(["--registry", str(regpath), "score", str(rows[0]["path"]), "--output", str(output)]) == 0
    assert regpath.read_bytes() == before
    assert "100.0" in capsys.readouterr().out
    summary = (output / "summary.html").read_text(encoding="utf-8")
    assert "<script>" not in summary and "&lt;script&gt;" in summary
    assert (output / "curation.json").is_file() and (output / "curation.md").is_file()


def test_cli_score_never_opens_network_sockets(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Curation must not connect to a network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    rows = saved_rows(tmp_path, fixture_result())
    regpath = tmp_path / "registry.json"
    C.write_json(regpath, registry())
    assert C.main(["--registry", str(regpath), "score", str(rows[0]["path"]), "--output", str(tmp_path / "out")]) == 0


def test_cli_apply_and_feature_offline_preserves_generation(tmp_path):
    result = eligible_variant()
    result["manifest"] = {"generation": OFFLINE_LABEL}
    rows = saved_rows(tmp_path, result)
    r = registry()
    r["samples"][0]["status"] = "candidate"
    regpath = tmp_path / "registry.json"
    C.write_json(regpath, r)
    prefix = ["--registry", str(regpath)]
    assert C.main(prefix + ["score", str(rows[0]["path"]), "--output", str(tmp_path / "out"), "--apply"]) == 0
    updated = json.loads(regpath.read_text(encoding="utf-8"))
    assert updated["samples"][0]["status"] == "candidate"
    assert updated["samples"][0]["curation"]["generation"] == OFFLINE_LABEL
    assert C.main(prefix + ["feature", "example-battery"]) == 1
    assert C.main(prefix + ["feature", "example-battery", "--confirm-human"]) == 0


def test_suggestions_stay_private_and_omit_result_text(tmp_path):
    result = eligible_variant()
    result["plan"] = None
    result["plan_id"] = "0" * 64
    rows = saved_rows(tmp_path, result)
    regpath = tmp_path / "registry.json"
    C.write_json(regpath, registry())
    assert C.main(["--registry", str(regpath), "suggest", str(rows[0]["path"]), "--output", str(tmp_path / "out")]) == 0
    proposals = json.loads((tmp_path / "out/suggestions.json").read_text(encoding="utf-8"))
    assert len(proposals) == 1 and proposals[0]["public_ok"] is False
    assert proposals[0]["status"] == "candidate"
    assert "evidence" not in proposals[0] and "plan" not in proposals[0]


def test_invalid_result_contract_returns_nonzero_without_echoing_body(tmp_path, capsys):
    regpath = tmp_path / "registry.json"
    C.write_json(regpath, registry())
    result = tmp_path / "invalid.json"
    C.write_json(result, {"session_id": "DO_NOT_ECHO_BODY", "plan_id": None})
    assert C.main(["--registry", str(regpath), "score", str(result), "--output", str(tmp_path / "out")]) == 1
    assert "DO_NOT_ECHO_BODY" not in capsys.readouterr().out


def test_nonjson_inputs_are_rejected_before_opening(tmp_path):
    # The file is deliberately absent: extension rejection must precede any read.
    with pytest.raises(ValueError, match="JSON 파일만"):
        C.read_results([tmp_path / ".env"])
    with pytest.raises(ValueError, match="JSON 파일만"):
        C.read_registry(tmp_path / ".env")


def test_empty_results_folder_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="파일 없음"):
        C.read_results([tmp_path])


def test_result_folder_prefers_result_json_over_metadata(tmp_path):
    C.write_json(tmp_path / "plan.result.json", eligible_variant())
    C.write_json(tmp_path / "metadata.json", {"test": "not a result"})
    rows = C.read_results([tmp_path])
    assert len(rows) == 1 and rows[0]["path"].name == "plan.result.json"


def test_no_sample_match_is_an_error_not_empty_success(tmp_path, capsys):
    result = eligible_variant()
    result.update(plan=None, plan_id="0" * 64)
    rows = saved_rows(tmp_path, result)
    regpath = tmp_path / "registry.json"
    C.write_json(regpath, registry())
    assert C.main(["--registry", str(regpath), "score", str(rows[0]["path"]), "--output", str(tmp_path / "out")]) == 1
    assert "일치하는 결과 없음" in capsys.readouterr().out
