"""SEC-3: 실제 OpenAI 호출은 프로세스 환경변수 NEUMANN_LIVE_LLM_OK가 있을 때만 열린다.

사용자 환경변수에 NEUMANN_LLM_PROVIDER=openai가 남아 있어도(20:0x 사고) 에이전트 프로세스가
실제 호출을 하지 못하게 한다. 키는 가짜 문자열만 쓰고, 실제 네트워크 호출은 없다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from neumann.config import Settings, get_settings, live_llm_allowed
from neumann.llm import LLMCall, OpenAIProvider, make_llm

FAKE_KEY = "fake-test-key-not-real-000"  # 실제 키 아님
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _openai_settings() -> SimpleNamespace:
    return SimpleNamespace(llm_provider="openai", llm_model="gpt-6.1-sol", openai_api_key=FAKE_KEY, llm_timeout_s=5.0)


def _call() -> LLMCall:
    return LLMCall(task="t", instructions="i", payload={"x": 1}, schema_name="s",
                   schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False})


def test_conftest_closes_flag_by_default():
    assert live_llm_allowed() is False


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("ON", True), (" yes ", True),
    ("0", False), ("no", False), ("false", False), ("off", False), ("2", False), ("x", False), ("", False), (" ", False),
])
def test_flag_values(monkeypatch, val, expected):
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", val)
    assert live_llm_allowed() is expected


def test_unset_flag_is_closed(monkeypatch):
    monkeypatch.delenv("NEUMANN_LIVE_LLM_OK", raising=False)
    assert live_llm_allowed() is False


def test_dotenv_flag_is_ignored(monkeypatch, tmp_path):
    """`.env`에 1이 있어도 프로세스 환경변수가 없으면 닫힌다(main 체크아웃 에이전트가 물려받지 않게)."""
    env_file = tmp_path / ".env"
    env_file.write_text("NEUMANN_LIVE_LLM_OK=1\nNEUMANN_LLM_PROVIDER=openai\n", encoding="utf-8")
    monkeypatch.delenv("NEUMANN_LIVE_LLM_OK", raising=False)
    monkeypatch.delenv("NEUMANN_LLM_PROVIDER", raising=False)
    monkeypatch.setattr("neumann.config.get_settings", lambda: Settings(_env_file=env_file))
    assert Settings(_env_file=env_file).llm_provider == "openai"
    assert live_llm_allowed() is False
    assert make_llm(Settings(_env_file=env_file)).name == "mock"


def test_env_provider_openai_without_flag_is_forced_to_mock(monkeypatch):
    """사고 재현: 환경변수 provider=openai·키 있음·플래그 없음 → mock."""
    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    assert get_settings().llm_provider == "openai"  # 설정은 요청값을 그대로 보여 준다
    assert make_llm(get_settings()).name == "mock"
    assert make_llm(None).name == "mock"


def test_explicit_provider_argument_is_also_guarded(monkeypatch):
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    assert make_llm(_openai_settings(), provider="openai").name == "mock"


def test_flag_opens_openai(monkeypatch):
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # 키가 없으니 실제 클라이언트를 만들지 않는다
    llm = make_llm(SimpleNamespace(llm_provider="openai", llm_model="gpt-6.1-sol", openai_api_key=None, llm_timeout_s=5.0))
    assert llm.name == "openai" and llm.model == "gpt-6.1-sol" and llm._client is None


def test_direct_provider_construction_does_not_build_client_without_flag(monkeypatch):
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    p = OpenAIProvider(api_key=FAKE_KEY, model="gpt-6.1-sol")
    assert p._client is None
    res = p.complete_json(_call())
    assert not res.ok and res.error == "config_error" and "NEUMANN_LIVE_LLM_OK" in res.detail


def test_injected_client_still_works_without_flag(monkeypatch):
    """테스트용 가짜 클라이언트 주입 경로는 막지 않는다(실제 네트워크가 아니다)."""
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    p = OpenAIProvider(api_key=None, model="gpt-6.1-sol", client=object())
    assert p._config_error is None


def _eval_mod(monkeypatch, name):
    if str(ROOT) not in sys.path:
        monkeypatch.syspath_prepend(str(ROOT))
    return __import__(f"eval.{name}", fromlist=["_"])


def test_baseline_llm_locked_is_not_cached_and_not_astra(monkeypatch, tmp_path):
    bl = _eval_mod(monkeypatch, "baseline_llm")
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    with pytest.raises(bl.LiveCallLocked):
        bl.OpenAIBaseline()._get_client()
    plan = {"plan_id": "p" * 16, "work_id": "w1", "plan_text": "계획서"}
    entry = bl.generate_cached(plan, bl.OpenAIBaseline(), tmp_path, prompt=("지시", "v-test"))
    assert entry["locked"] is True and entry["ok"] is False
    assert list(tmp_path.iterdir()) == []  # 잠금 실패는 캐시에 쓰지 않는다
    rs = bl.riskset_from_entry(entry, condition="real", work_id="w1")
    assert rs["generator"] != "astra"
    assert "astra" not in json.dumps(rs["generator"])


def test_disapere_extract_refuses_astra_when_locked(monkeypatch):
    src = (ROOT / "eval" / "disapere_extract.py").read_text(encoding="utf-8")
    assert 'args.generator == "astra" and llm.name != "openai"' in src
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    assert make_llm(provider="openai").name != "openai"  # 이 조건이 참이 되어 SystemExit로 멈춘다


def test_precompute_manifest_records_actual_llm(monkeypatch):
    import importlib.util

    name = "precompute_demo_under_test"  # tests/e6/e6_support.py와 같은 이름(dataclass가 sys.modules를 본다)
    pd = sys.modules.get(name)
    if pd is None:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "precompute_demo.py")
        pd = importlib.util.module_from_spec(spec)
        sys.modules[name] = pd
        spec.loader.exec_module(pd)
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    s = pd.llm_settings()
    assert s is not None and s["live_llm_ok"] is False and "provider_requested" in s
    fake = SimpleNamespace(manifest={"llm_provider": "mock", "llm_model": "mock-deterministic-v1"})
    assert pd.llm_actual(fake) == {"provider": "mock", "model": "mock-deterministic-v1"}


def test_health_reports_guard_without_key_material(monkeypatch):
    from fastapi.testclient import TestClient

    from neumann.api.main import app

    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    get_settings.cache_clear()
    body = TestClient(app).get("/health").json()
    assert body["llm"] == {"provider_requested": "openai", "live_llm_ok": False, "key_present": True,
                           "effective": "mock", "model": "", "astra_allowed": False}
    assert FAKE_KEY not in json.dumps(body)

    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "1")
    get_settings.cache_clear()
    body = TestClient(app).get("/health").json()
    assert body["llm"]["effective"] == "openai" and body["llm"]["model"]
    assert FAKE_KEY not in json.dumps(body)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr("neumann.config.Settings.has_openai_key", property(lambda self: False))
    body = TestClient(app).get("/health").json()
    assert body["llm"]["effective"] == "openai_no_key"


# ── astra 금지(대표 지시 20:4x) ─────────────────────────────────────────


@pytest.mark.parametrize("model", ["gpt-6-astra", "GPT-6-Astra", "gpt-6.1-astra-preview"])
def test_make_llm_replaces_astra_with_sol(monkeypatch, model):
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "1")
    monkeypatch.delenv("NEUMANN_ALLOW_ASTRA", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm = make_llm(SimpleNamespace(llm_provider="openai", llm_model=model, openai_api_key=None, llm_timeout_s=5.0))
    assert llm.name == "openai" and llm.model == "gpt-6.1-sol"


def test_env_astra_model_is_replaced(monkeypatch):
    """사고 재현: 옛 프로세스 환경 NEUMANN_LLM_MODEL=gpt-6-astra."""
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "1")
    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    monkeypatch.setenv("NEUMANN_LLM_MODEL", "gpt-6-astra")
    monkeypatch.delenv("NEUMANN_ALLOW_ASTRA", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert make_llm(get_settings()).model == "gpt-6.1-sol"


def test_allow_astra_flag_keeps_model(monkeypatch):
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "1")
    monkeypatch.setenv("NEUMANN_ALLOW_ASTRA", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm = make_llm(SimpleNamespace(llm_provider="openai", llm_model="gpt-6-astra", openai_api_key=None, llm_timeout_s=5.0))
    assert llm.model == "gpt-6-astra"


def test_direct_provider_real_client_path_replaces_astra(monkeypatch):
    """실제 클라이언트를 만드는 경로(키 있음·플래그 1)에서 모델이 sol로 바뀐다. 클라이언트 생성만, 호출 없음."""
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "1")
    monkeypatch.delenv("NEUMANN_ALLOW_ASTRA", raising=False)
    p = OpenAIProvider(api_key=FAKE_KEY, model="gpt-6-astra")
    assert p.model == "gpt-6.1-sol"


def test_injected_client_keeps_model_name(monkeypatch):
    """가짜 클라이언트 주입(테스트 대역)은 모델 이름을 바꾸지 않는다(실제 호출이 아니다)."""
    monkeypatch.delenv("NEUMANN_ALLOW_ASTRA", raising=False)
    assert OpenAIProvider(api_key=None, model="gpt-6-astra", client=object()).model == "gpt-6-astra"


def test_baseline_replaces_astra(monkeypatch):
    bl = _eval_mod(monkeypatch, "baseline_llm")
    monkeypatch.delenv("NEUMANN_ALLOW_ASTRA", raising=False)
    monkeypatch.setenv("NEUMANN_LLM_MODEL", "gpt-6-astra")
    assert bl.OpenAIBaseline().model == "gpt-6.1-sol"
    assert bl.OpenAIBaseline(model="gpt-6-astra").model == "gpt-6.1-sol"
    assert bl.OpenAIBaseline(model="gpt-6-astra", client=object()).model == "gpt-6-astra"


def test_health_shows_effective_model_not_astra(monkeypatch):
    from fastapi.testclient import TestClient

    from neumann.api.main import app

    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    monkeypatch.setenv("NEUMANN_LLM_MODEL", "gpt-6-astra")
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "1")
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("NEUMANN_ALLOW_ASTRA", raising=False)
    get_settings.cache_clear()
    body = TestClient(app).get("/health").json()
    assert body["llm"]["model"] == "gpt-6.1-sol" and body["llm"]["astra_allowed"] is False
    assert FAKE_KEY not in json.dumps(body)
