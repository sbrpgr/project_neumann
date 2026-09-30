"""FIX-B3: bind cache records to the identity sent to a synthetic SDK."""

import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from eval import baseline_llm as bl
from neumann import config

PLAN = {"work_id": "synthetic", "plan_id": "c" * 64, "plan_text": "Synthetic plan"}
PROMPT = ("instructions", "independent-effort-v1")


@pytest.fixture(autouse=True)
def synthetic_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real SDK/settings access is forbidden")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=forbidden))
    monkeypatch.setattr(config, "get_settings", forbidden)
    monkeypatch.setattr(bl, "_require_live_call", lambda: None)


def expected_key(effort):
    raw = f"openai|{bl.DEFAULT_MODEL}|{effort}|{PROMPT[1]}|{PLAN['plan_id']}"
    return hashlib.sha256(raw.encode()).hexdigest()


def synthetic_provider(on_call=None, description="One sentence.", effort="medium"):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if on_call:
            on_call()
        return SimpleNamespace(
            status="completed", model=kwargs["model"], usage=None,
            output_text=json.dumps({"risks": [
                {"title": f"Risk {i}", "description": description} for i in range(3)
            ]}),
        )

    provider = bl.OpenAIBaseline(
        model=bl.DEFAULT_MODEL, effort=effort,
        client=SimpleNamespace(responses=SimpleNamespace(create=create)),
    )
    return provider, calls


@pytest.mark.parametrize("initial,sent", [("medium", "high"), ("high", "low")])
def test_effort_changes_during_client_acquisition(monkeypatch, tmp_path, initial, sent):
    provider, calls = synthetic_provider(effort=initial)

    def acquire():
        provider.effort = sent
        return provider._client

    monkeypatch.setattr(provider, "_get_client", acquire)
    first = bl.generate_cached(PLAN, provider, tmp_path, PROMPT)
    assert calls[0]["reasoning"]["effort"] == sent
    assert first["effort"] == sent
    assert first["key"] == expected_key(sent)
    assert first["attempts"][0]["effort"] == sent
    assert first["attempts"][0]["provider"] == "openai"
    assert [p.name for p in tmp_path.glob("*.json")] == [f"{expected_key(sent)}.json"]
    stored = json.loads((tmp_path / f"{expected_key(sent)}.json").read_text(encoding="utf-8"))
    assert stored["effort"] == sent and stored["key"] == first["key"]
    second = bl.generate_cached(PLAN, provider, tmp_path, PROMPT)
    assert second["cache_hit"] is True and len(calls) == 1
    assert second["key"] == first["key"]


def test_effort_changes_after_sdk_call_keeps_sent_snapshot(tmp_path):
    provider, calls = synthetic_provider(on_call=lambda: setattr(provider, "effort", "high"))
    first = bl.generate_cached(PLAN, provider, tmp_path, PROMPT)
    assert calls[0]["reasoning"]["effort"] == "medium"
    assert first["effort"] == "medium" and first["key"] == expected_key("medium")
    assert first["attempts"][0]["effort"] == "medium"
    second = bl.generate_cached(PLAN, provider, tmp_path, PROMPT)
    assert second["cache_hit"] is False and len(calls) == 2
    assert second["effort"] == "high" and second["key"] == expected_key("high")
    third = bl.generate_cached(PLAN, provider, tmp_path, PROMPT)
    assert third["cache_hit"] is True and len(calls) == 2


@pytest.mark.parametrize("field,value,reason,note", [
    ("effort", "high", "effective_identity_changed", "effort"),
    ("name", "other-synthetic", "effective_identity_changed", "provider"),
    ("model", "gpt-6.1-sol-preview", "effective_model_changed", "모델"),
])
def test_mixed_identity_retry_is_failed_and_not_cached(tmp_path, field, value, reason, note):
    provider, calls = synthetic_provider(
        on_call=lambda: setattr(provider, field, value), description="One. Two. Three.",
    )
    entry = bl.generate_cached(PLAN, provider, tmp_path, PROMPT)
    assert len(calls) == 2
    if field == "effort":
        assert [c["reasoning"]["effort"] for c in calls] == ["medium", "high"]
        assert [a["effort"] for a in entry["attempts"]] == ["medium", "high"]
    else:
        recorded = "provider" if field == "name" else "model_requested"
        assert entry["attempts"][0][recorded] != entry["attempts"][1][recorded] == value
    assert entry["ok"] is False and entry["output"] is None
    assert entry["cache_skipped"] == reason
    assert list(tmp_path.iterdir()) == []
    row = bl.riskset_from_entry(entry, condition="real", work_id=PLAN["work_id"])
    assert row["status"] == "error" and row["n_risks"] == 0
    assert any(note in text for text in row["notes"])


def test_same_effort_retry_uses_sent_key(monkeypatch, tmp_path):
    provider, calls = synthetic_provider(description="One. Two. Three.")

    def acquire():
        provider.effort = "high"
        return provider._client

    monkeypatch.setattr(provider, "_get_client", acquire)
    entry = bl.generate_cached(PLAN, provider, tmp_path, PROMPT)
    assert entry["ok"] is True and len(calls) == 2
    assert entry["effort"] == "high" and entry["key"] == expected_key("high")
    assert [a["effort"] for a in entry["attempts"]] == ["high", "high"]
    assert bl.generate_cached(PLAN, provider, tmp_path, PROMPT)["cache_hit"] is True
    assert len(calls) == 2


@pytest.mark.parametrize("field,value,reason", [
    ("effort", "high", "attempt_effort_mismatch"),
    ("provider", "mock", "attempt_provider_mismatch"),
])
def test_cache_with_mismatched_attempt_identity_is_regenerated(tmp_path, field, value, reason):
    provider, calls = synthetic_provider()
    first = bl.generate_cached(PLAN, provider, tmp_path, PROMPT)
    path = tmp_path / f"{first['key']}.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["attempts"][0][field] = value
    path.write_text(json.dumps(stored), encoding="utf-8")
    second = bl.generate_cached(PLAN, provider, tmp_path, PROMPT)
    assert second["cache_hit"] is False and len(calls) == 2
    assert second["stale_cache"] == reason
