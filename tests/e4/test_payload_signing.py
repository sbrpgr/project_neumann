"""Regression checks for revision provenance and signature domain separation."""

import hashlib
import hmac
import json
import math
from pathlib import Path

import pytest

from neumann.api import signing
from neumann.api.signing import sign_payload, sign_result, verify_payload, verify_result


def test_revision_signature_preserves_browser_json_roundtrip():
    payload = {"plan_id": "plan", "edit": {"text": "근거에 따른 수정", "line": 1.0}}
    sig = sign_payload("revision", payload)
    assert verify_payload("revision", {"edit": {"line": 1, "text": "근거에 따른 수정"}, "plan_id": "plan"}, sig)


def test_signature_rejects_tampering_and_domain_substitution():
    payload = {"proposed_text": "원문", "plan_id": "plan"}
    sig = sign_payload("revision", payload)
    assert not verify_payload("revision", {**payload, "proposed_text": "위조"}, sig)
    assert not verify_payload("revised-plan", payload, sig)
    assert not verify_payload("result", payload, sig)
    assert not verify_result(payload, sig)


@pytest.mark.parametrize("sig", [None, 12, "v1." + "가" * 64, "v1." + "F" * 64, "v2." + "0" * 64])
def test_malformed_signature_never_raises(sig):
    assert not verify_payload("revision", {"text": "내용"}, sig)


@pytest.mark.parametrize("kind", ["result", "", "../revision", "REVISION", "수정"])
def test_reserved_or_invalid_domain_cannot_be_signed(kind):
    with pytest.raises(ValueError):
        sign_payload(kind, {"text": "내용"})


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, object()])
def test_invalid_payload_is_not_authenticated(bad):
    sig = sign_payload("revision", {"text": "내용"})
    assert not verify_payload("revision", {"value": bad}, sig)


def test_non_mapping_payload_is_not_authenticated():
    sig = sign_payload("revision", {"text": "내용"})
    assert not verify_payload("revision", ["내용"], sig)


@pytest.mark.parametrize("payload", [{1: "내용"}, {"edit": {1: "내용"}}, {"edits": [{1: "내용"}]}])
def test_non_string_keys_cannot_alias_json_keys(payload):
    # JSON keys are strings. Coercion must not authenticate a different Python mapping.
    normal = json.loads(json.dumps(payload, ensure_ascii=False))
    sig = sign_payload("revision", normal)
    assert not verify_payload("revision", payload, sig)
    with pytest.raises(TypeError):
        sign_payload("revision", payload)


def test_valid_result_and_generic_payload_signatures_are_separate():
    payload = json.loads((Path(__file__).parents[1] / "fixtures" / "premortem_result.json").read_text(encoding="utf-8"))
    result_sig = sign_result(payload)
    revision_sig = sign_payload("revision", payload)
    assert verify_result(payload, result_sig)
    assert verify_payload("revision", payload, revision_sig)
    assert result_sig != revision_sig
    assert not verify_result(payload, revision_sig)
    assert not verify_payload("revision", payload, result_sig)


def test_payload_signature_uses_versioned_domain_and_shared_key(monkeypatch):
    test_key = b"unit-test-generic-signing-key"
    monkeypatch.setattr(signing, "_KEY", test_key)
    payload = {"text": "근거", "line": 1.0}
    body = 'neumann-revision-v1\n{"line":1,"text":"근거"}'.encode("utf-8")
    assert sign_payload("revision", payload) == "v1." + hmac.new(test_key, body, hashlib.sha256).hexdigest()


def test_generic_signature_key_rotation_invalidates_old_payload(monkeypatch):
    payload = {"edit": {"text": "내용"}}
    monkeypatch.setattr(signing, "_KEY", b"unit-test-first-signing-key")
    sig = sign_payload("revision", payload)
    monkeypatch.setattr(signing, "_KEY", b"unit-test-second-signing-key")
    assert not verify_payload("revision", payload, sig)
    assert verify_payload("revision", payload, sign_payload("revision", payload))


@pytest.mark.parametrize("value, changed", [(1.25, 1.26), (True, 1), (None, ""), ([1, 2], [2, 1])])
def test_payload_values_are_not_erased_by_canonicalisation(value, changed):
    sig = sign_payload("revision", {"value": value})
    assert not verify_payload("revision", {"value": changed}, sig)


def test_cyclic_payload_fails_closed():
    payload = {}
    payload["self"] = payload
    sig = sign_payload("revision", {"text": "내용"})
    assert not verify_payload("revision", payload, sig)
