"""SEC-3: 실제 OpenAI 호출은 NEUMANN_LIVE_LLM_OK가 있을 때만 열린다.

사용자 환경변수에 NEUMANN_LLM_PROVIDER=openai가 남아 있어도(20:0x 사고) 에이전트 프로세스가
실제 호출을 하지 못하게 한다. 키는 가짜 문자열만 쓰고, 실제 네트워크 호출은 없다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from neumann.config import Settings, get_settings, live_llm_allowed
from neumann.llm import OpenAIProvider, make_llm

FAKE_KEY = "fake-test-key-not-real-000"  # 실제 키 아님


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _openai_settings() -> SimpleNamespace:
    return SimpleNamespace(llm_provider="openai", llm_model="gpt-6.1-sol", openai_api_key=FAKE_KEY, llm_timeout_s=5.0)


def test_conftest_closes_flag_by_default():
    assert live_llm_allowed() is False


@pytest.mark.parametrize("val,expected", [("1", True), ("true", True), ("ON", True), ("0", False), ("no", False), ("", False)])
def test_flag_values(monkeypatch, val, expected, tmp_path):
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", val)
    if val == "":
        # 빈 값은 없는 것 → 설정(.env)으로 넘어간다. 저장소 .env의 영향을 받지 않게 빈 .env를 쓰는 설정으로 확인
        assert Settings(_env_file=tmp_path / "none.env").live_llm_ok is False
    else:
        assert live_llm_allowed() is expected


def test_env_provider_openai_without_flag_is_forced_to_mock(monkeypatch):
    """사고 재현: 환경변수 provider=openai·키 있음·플래그 없음 → mock."""
    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    assert get_settings().llm_provider == "openai"  # 설정은 요청값을 그대로 보여 준다
    llm = make_llm(get_settings())
    assert llm.name == "mock"
    assert make_llm(None).name == "mock"


def test_explicit_provider_argument_is_also_guarded(monkeypatch):
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    assert make_llm(_openai_settings(), provider="openai").name == "mock"


def test_flag_opens_openai(monkeypatch):
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "1")
    llm = make_llm(_openai_settings(), provider="openai")
    assert llm.name == "openai" and llm.model == "gpt-6.1-sol"


def test_direct_provider_construction_does_not_build_client_without_flag(monkeypatch):
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    p = OpenAIProvider(api_key=FAKE_KEY, model="gpt-6.1-sol")
    assert p._client is None
    from neumann.llm import LLMCall

    res = p.complete_json(LLMCall(task="t", instructions="i", payload={"x": 1}, schema_name="s",
                                  schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False}))
    assert not res.ok and res.error == "config_error" and "NEUMANN_LIVE_LLM_OK" in res.detail


def test_injected_client_still_works_without_flag(monkeypatch):
    """테스트용 가짜 클라이언트 주입 경로는 막지 않는다(실제 네트워크가 아니다)."""
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    p = OpenAIProvider(api_key=None, model="gpt-6.1-sol", client=object())
    assert p._config_error is None


def test_baseline_llm_refuses_real_client_without_flag(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        monkeypatch.syspath_prepend(str(root))
    from eval.baseline_llm import OpenAIBaseline

    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    with pytest.raises(RuntimeError, match="NEUMANN_LIVE_LLM_OK"):
        OpenAIBaseline()._get_client()


def test_health_reports_guard(monkeypatch):
    from fastapi.testclient import TestClient

    from neumann.api.main import app

    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    body = TestClient(app).get("/health").json()
    assert body["llm"] == {"provider_requested": "openai", "live_llm_ok": False, "effective": "mock", "model": ""}
    assert FAKE_KEY not in str(body)
