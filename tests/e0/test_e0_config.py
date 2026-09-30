"""설정 로더: 환경변수 > .env, 빈 값 무시, SecretStr 가림. 키는 가짜 문자열만 쓴다."""

from __future__ import annotations

from pathlib import Path

import pytest

from neumann.config import Settings, get_settings

FAKE_KEY = "fake-test-key-not-real-000"  # 실제 키 아님
FAKE_SALT = "fake-test-salt-000"

KEYS = [
    "OPENAI_API_KEY",
    "NEUMANN_PSEUDONYM_SALT",
    "NEUMANN_LLM_PROVIDER",
    "NEUMANN_LLM_MODEL",
    "NEUMANN_LLM_TIMEOUT_S",
    "NEUMANN_EMBED_MODEL",
    "NEUMANN_RAW_DIR",
    "NEUMANN_DATA_DIR",
    "NEUMANN_API_HOST",
    "NEUMANN_API_PORT",
    "NEUMANN_LIVE_TESTS",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def write_env(tmp_path: Path, body: str) -> Path:
    p = tmp_path / ".env"
    p.write_text(body, encoding="utf-8")
    return p


def test_env_var_beats_empty_dotenv_value(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    env_file = write_env(tmp_path, "OPENAI_API_KEY=\nNEUMANN_LLM_PROVIDER=openai\n")
    clean_env.setenv("OPENAI_API_KEY", FAKE_KEY)
    s = Settings(_env_file=env_file)
    assert s.openai_api_key is not None
    assert s.openai_api_key.get_secret_value() == FAKE_KEY
    assert s.has_openai_key


def test_env_var_beats_nonempty_dotenv_value(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    env_file = write_env(tmp_path, "OPENAI_API_KEY=fake-dotenv-value\nNEUMANN_LLM_MODEL=from-dotenv\n")
    clean_env.setenv("OPENAI_API_KEY", FAKE_KEY)
    clean_env.setenv("NEUMANN_LLM_MODEL", "from-env")
    s = Settings(_env_file=env_file)
    assert s.openai_api_key.get_secret_value() == FAKE_KEY
    assert s.llm_model == "from-env"


def test_dotenv_used_when_env_missing_and_empty_means_none(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    env_file = write_env(tmp_path, "OPENAI_API_KEY=\nNEUMANN_LLM_PROVIDER=mock\nNEUMANN_API_PORT=9001\n")
    s = Settings(_env_file=env_file)
    assert s.openai_api_key is None and not s.has_openai_key
    assert s.llm_provider == "mock"
    assert s.api_port == 9001


def test_missing_dotenv_is_ignored_and_defaults(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=tmp_path / "nope.env")
    assert s.llm_provider == "openai"
    assert s.llm_model == "gpt-6-astra"
    assert s.llm_timeout_s == 60.0
    assert s.api_host == "127.0.0.1" and s.api_port == 8000
    assert s.live_tests is False


def test_invalid_provider_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("NEUMANN_LLM_PROVIDER", "local")
    with pytest.raises(Exception):
        Settings(_env_file=None)


def test_secretstr_repr_hides_values(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPENAI_API_KEY", FAKE_KEY)
    clean_env.setenv("NEUMANN_PSEUDONYM_SALT", FAKE_SALT)
    s = Settings(_env_file=None)
    for text in (repr(s), str(s), repr(s.openai_api_key), str(s.pseudonym_salt), s.model_dump_json()):
        assert FAKE_KEY not in text
        assert FAKE_SALT not in text
    assert s.pseudonym_salt.get_secret_value() == FAKE_SALT


def test_paths_from_env(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("NEUMANN_DATA_DIR", str(tmp_path / "data"))
    clean_env.setenv("NEUMANN_RAW_DIR", str(tmp_path / "raw"))
    s = Settings(_env_file=None)
    assert s.data_dir == tmp_path / "data"
    assert s.raw_dir == tmp_path / "raw"


def test_get_settings_is_cached(clean_env: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()
