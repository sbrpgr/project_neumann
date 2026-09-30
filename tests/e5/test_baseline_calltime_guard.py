"""Call-boundary guards measured with a synthetic SDK; no credentials or network."""

import json
import sys
from types import SimpleNamespace

import pytest

from eval import baseline_llm as bl
from neumann import config


class FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            status="completed", model=kwargs["model"], usage=None,
            output_text=json.dumps({"risks": [
                {"title": f"Risk {i}", "description": "Synthetic description."} for i in range(3)
            ]}),
        )


@pytest.fixture(autouse=True)
def synthetic_sdk_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real SDK/settings access is forbidden in this test")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=forbidden))
    monkeypatch.setattr(config, "get_settings", forbidden)
    # 환경 파싱까지 검사하되 프로세스 환경변수는 켜지 않는다. config만 보는 합성 매핑이다.
    monkeypatch.setattr(config, "os", SimpleNamespace(environ={}))


def provider(model=bl.DEFAULT_MODEL):
    responses = FakeResponses()
    return bl.OpenAIBaseline(model=model, client=SimpleNamespace(responses=responses)), responses


@pytest.mark.parametrize("flag", [None, "0", "false", "", "2"])
def test_injected_sdk_locked_with_zero_calls(monkeypatch, flag):
    if flag is None:
        monkeypatch.delitem(config.os.environ, config.LIVE_LLM_FLAG, raising=False)
    else:
        monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, flag)
    p, sdk = provider()
    result = p.generate("instructions", "synthetic plan")
    assert sdk.calls == []
    assert result.get("locked") is True and result["ok"] is False
    with pytest.raises(bl.LiveCallLocked):
        p._get_client()


@pytest.mark.parametrize("flag", ["1", "true", " yes ", "ON"])
def test_authorized_fake_sdk_preserved(monkeypatch, flag):
    monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, flag)
    p, sdk = provider()
    result = p.generate("instructions", "synthetic plan")
    assert result["ok"] and result["model_actual"] == bl.DEFAULT_MODEL
    assert len(sdk.calls) == 1
    assert sdk.calls[0]["input"] == "synthetic plan"
    assert sdk.calls[0]["instructions"] == "instructions"
    assert sdk.calls[0]["store"] is False


def test_permission_revoked_after_success_blocks_cached_sdk(monkeypatch):
    monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, "1")
    p, sdk = provider()
    assert p.generate("i", "plan")["ok"]
    monkeypatch.delitem(config.os.environ, config.LIVE_LLM_FLAG)
    result = p.generate("i", "plan")
    assert len(sdk.calls) == 1  # revoked call adds zero SDK calls
    assert result.get("locked") is True


def test_permission_revoked_after_authorized_client_acquisition(monkeypatch):
    monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, "1")
    p, sdk = provider()
    assert p._get_client() is p._client
    monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, "0")
    assert p.generate("i", "plan").get("locked") is True
    assert sdk.calls == []


def test_settings_permission_cannot_authorize_process(monkeypatch):
    monkeypatch.delitem(config.os.environ, config.LIVE_LLM_FLAG, raising=False)
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(live_llm_ok=True))
    p, sdk = provider()
    assert p.generate("i", "plan").get("locked") is True
    assert sdk.calls == []


def test_permission_revoked_during_client_acquisition(monkeypatch):
    monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, "1")
    p, sdk = provider()

    def acquire_and_revoke():
        monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, "0")
        return p._client

    monkeypatch.setattr(p, "_get_client", acquire_and_revoke)
    assert p.generate("i", "plan").get("locked") is True
    assert sdk.calls == []


@pytest.mark.parametrize("model", ["gpt-6-astra", "GPT-6-ASTRA-preview"])
def test_injected_astra_routes_to_sol(monkeypatch, model):
    monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, "1")
    p, sdk = provider(model)
    assert p.model == bl.DEFAULT_MODEL
    result = p.generate("i", "plan")
    assert result["ok"] and result["model_actual"] == bl.DEFAULT_MODEL
    assert len(sdk.calls) == 1 and sdk.calls[0]["model"] == bl.DEFAULT_MODEL


def test_current_astra_permission_rechecked(monkeypatch):
    monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, "1")
    monkeypatch.setitem(config.os.environ, config.ASTRA_FLAG, "1")
    p, sdk = provider("gpt-6-astra")
    assert p.generate("i", "plan")["ok"]
    assert sdk.calls[0]["model"] == "gpt-6-astra"
    monkeypatch.delitem(config.os.environ, config.ASTRA_FLAG)
    result = p.generate("i", "plan")
    assert result["ok"] and result["model_actual"] == bl.DEFAULT_MODEL
    assert len(sdk.calls) == 2 and sdk.calls[1]["model"] == bl.DEFAULT_MODEL


def test_live_guard_failure_is_closed(monkeypatch):
    monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, "1")
    p, sdk = provider()

    def broken_guard():
        raise RuntimeError("synthetic guard failure")

    monkeypatch.setattr(config, "live_llm_allowed", broken_guard)
    assert p.generate("i", "plan").get("locked") is True
    assert sdk.calls == []


def test_model_guard_failure_routes_astra_to_sol(monkeypatch):
    monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, "1")
    monkeypatch.setitem(config.os.environ, config.ASTRA_FLAG, "1")
    p, sdk = provider("gpt-6-astra")

    def broken_guard(model):
        raise RuntimeError("synthetic model guard failure")

    monkeypatch.setattr(config, "guard_model", broken_guard)
    result = p.generate("i", "plan")
    assert result["ok"] and result["model_actual"] == bl.DEFAULT_MODEL
    assert len(sdk.calls) == 1 and sdk.calls[0]["model"] == bl.DEFAULT_MODEL


def test_locked_cache_is_not_written_or_retried(monkeypatch, tmp_path):
    monkeypatch.setitem(config.os.environ, config.LIVE_LLM_FLAG, "0")
    p, sdk = provider()
    plan = {"work_id": "synthetic", "plan_id": "a" * 64, "plan_text": "synthetic plan"}
    entry = bl.generate_cached(plan, p, tmp_path, prompt=("i", "synthetic-v1"))
    assert entry.get("locked") is True and entry["ok"] is False
    assert len(entry["attempts"]) == 1 and sdk.calls == []
    assert list(tmp_path.iterdir()) == []
    row = bl.riskset_from_entry(entry, condition="real", work_id=plan["work_id"])
    assert row["generator"] == "none" and row["status"] == "error"


def test_ordinary_mock_requires_no_live_permission(monkeypatch):
    monkeypatch.delitem(config.os.environ, config.LIVE_LLM_FLAG, raising=False)
    p = bl.MockBaseline()
    result = p.generate("i", "synthetic plan")
    assert result["ok"] and p.calls == 1 and len(result["data"]["risks"]) == 3
