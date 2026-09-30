"""LIVE-SMOKE-3 regression, reduced from saved public OpenReview excerpts.

The fixture keeps two proposals from one card citing the same additional record,
plus another card's evidence and record. Source spans/text/hashes are unchanged;
the proposal rationale lists are projected to the shared record. No live LLM.
"""

from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path

import pytest

from neumann.analyze import assemble as asm
from neumann.analyze.gate import EvidenceIndex
from neumann.analyze.revise import contains_identity, validate_revision
from neumann.models import Excerpt, PremortemResult, contains_pii


@pytest.fixture
def saved_bundle():
    return json.loads(Path(__file__).with_name("assemble_live_smoke3.json").read_text(encoding="utf-8"))


def decisions_of(bundle):
    return [{"edit_id": e["edit_id"], "decision": "adopt"}
            for r in bundle["revision"]["revisions"] for e in r["edits"]]


def assemble(bundle, decisions):
    return asm.assemble_revised_plan(bundle["plan_text"], bundle["revision"], decisions,
                                     result=bundle["result"], regate=True)


def stable_output(output):
    return {k: v for k, v in output.items() if k != "generated_at"}


def test_saved_public_excerpts_and_contracts_are_valid(saved_bundle):
    result, revision = saved_bundle["result"], saved_bundle["revision"]
    PremortemResult.model_validate(result)
    assert validate_revision(revision) == []
    for raw in result["evidence"] + revision["records"]:
        excerpt = Excerpt.model_validate({k: v for k, v in raw.items() if k in Excerpt.model_fields})
        assert excerpt.source_url.startswith("https://openreview.net/forum?")
        assert not contains_pii(excerpt.text) and not contains_identity(excerpt.text)
    assert "revision_sig" not in revision


def test_all_adopt_reuses_same_card_record_without_mutating_input(saved_bundle):
    before = copy.deepcopy(saved_bundle)
    output = assemble(saved_bundle, decisions_of(saved_bundle))
    assert asm.validate_revised_plan(output) == []
    assert output["stats"]["applied"] == output["stats"]["adopted"] == 2
    assert output["stats"]["conflicts"] == output["stats"]["skipped"] == 0
    assert saved_bundle == before


def test_adoption_and_revision_order_produce_identical_output(saved_bundle):
    decisions = decisions_of(saved_bundle)
    singles = [assemble(saved_bundle, [decision]) for decision in decisions]
    assert all(out["stats"]["applied"] == 1 for out in singles)
    expected = stable_output(assemble(saved_bundle, decisions))
    for order in itertools.permutations(decisions):
        for reverse_revisions in (False, True):
            bundle = copy.deepcopy(saved_bundle)
            if reverse_revisions:
                bundle["revision"]["revisions"].reverse()
                for revision in bundle["revision"]["revisions"]:
                    revision["edits"].reverse()
                bundle["revision"]["records"].reverse()
            assert stable_output(assemble(bundle, order)) == expected


def test_number_gate_uses_proposal_local_index(saved_bundle, monkeypatch):
    indexes = []

    class TrackedIndex(EvidenceIndex):
        def __init__(self, result):
            super().__init__(result)
            indexes.append((self, dict(self.excerpts)))

    monkeypatch.setattr("neumann.analyze.gate.EvidenceIndex", TrackedIndex)
    assemble(saved_bundle, decisions_of(saved_bundle))
    assert indexes
    assert all(index.excerpts == original for index, original in indexes)


@pytest.mark.parametrize("reverse", [False, True])
def test_additional_record_numbers_are_checked_per_proposal(saved_bundle, reverse):
    own = saved_bundle["revision"]["revisions"][0]
    own["edits"][1]["proposed_text"] += " 해상도 0.25 조건을 비교한다."
    decisions = decisions_of(saved_bundle)
    if reverse:
        decisions.reverse()
    assert assemble(saved_bundle, decisions)["stats"]["applied"] == 2
    own["edits"][1]["proposed_text"] += " 표본 987654건을 확보했다."
    with pytest.raises(ValueError, match="unsupported numbers"):
        assemble(saved_bundle, decisions)


def test_additional_record_must_pass_excerpt_hash_validation(saved_bundle):
    own_id = saved_bundle["revision"]["revisions"][0]["edits"][0]["rationale"]["excerpt_ids"][0]
    record = next(r for r in saved_bundle["revision"]["records"] if r["excerpt_id"] == own_id)
    record["text_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="text_sha256"):
        assemble(saved_bundle, decisions_of(saved_bundle))


@pytest.mark.parametrize("kind", ["original", "record", "missing_record"])
@pytest.mark.parametrize("reverse", [False, True])
def test_foreign_and_missing_record_links_stay_rejected(saved_bundle, kind, reverse):
    revision = saved_bundle["revision"]
    own, other = revision["revisions"]
    own_record = own["edits"][0]["rationale"]["excerpt_ids"][0]
    if kind == "original":
        foreign = saved_bundle["result"]["risk_cards"][1]["evidence"][0]
        # Even a claimed pool cannot turn another card's original evidence into ours.
        own["evidence_pool"].append(foreign)
    elif kind == "record":
        foreign = next(x for x in other["evidence_pool"] if x not in own["evidence_pool"]
                       and any(rec["excerpt_id"] == x for rec in revision["records"]))
    else:
        foreign = own_record
        revision["records"] = [rec for rec in revision["records"] if rec["excerpt_id"] != foreign]
    own["edits"][1]["rationale"]["excerpt_ids"] = [foreign]
    decisions = decisions_of(saved_bundle)
    if reverse:
        decisions.reverse()
    with pytest.raises(ValueError, match="another card|verified evidence links"):
        assemble(saved_bundle, decisions)
