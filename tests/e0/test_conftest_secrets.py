"""기본 테스트 실행에서는 실제 키가 보이지 않는다(환경변수·저장소 .env 모두)."""

from __future__ import annotations

import os

from neumann.config import Settings


def test_no_openai_key_in_process_env():
    assert "OPENAI_API_KEY" not in os.environ


def test_settings_do_not_read_repo_dotenv():
    assert Settings.model_config.get("env_file") is None
    assert Settings().openai_api_key is None
