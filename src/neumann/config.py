"""설정 로더. 우선순위: 생성자 인자 > 환경변수 > 저장소 루트 `.env` > 기본값.

- `.env`가 없으면 무시한다. `load_dotenv(override=True)`는 쓰지 않는다(빈 값이 실제 키를 가리지 않게).
- 빈 값(`OPENAI_API_KEY=`)은 없는 것으로 본다(`env_ignore_empty`).
- 비밀값(`openai_api_key`, `pseudonym_salt`)은 SecretStr: repr·로그에 값이 나오지 않는다.
  값이 필요하면 `.get_secret_value()`를 그 자리에서만 부른다. 설정 객체 전체를 로그에 찍지 않는다.
- 실제 OpenAI 호출은 프로세스 환경변수 `NEUMANN_LIVE_LLM_OK=1`일 때만 열린다(`live_llm_allowed`). provider가
  openai여도 이 값이 없으면 `llm.make_llm`이 mock으로 강등한다. `.env`의 같은 키는 읽지 않는다(main 체크아웃에서
  도는 에이전트가 물려받지 않게). 실서비스 서버 기동 명령에만 준다(SEC-3, 대표 상시 규칙).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
LIVE_LLM_FLAG = "NEUMANN_LIVE_LLM_OK"
_TRUE = frozenset({"1", "true", "yes", "on"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
        validate_by_name=True,
        validate_by_alias=True,
    )

    # 비밀값
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    pseudonym_salt: SecretStr | None = Field(default=None, validation_alias="NEUMANN_PSEUDONYM_SALT")

    # 제품 LLM
    # 기본은 mock(대표 상시 규칙: 실제 OpenAI 호출은 실제 서비스와 승인된 확인 테스트에만). 실서비스는 main 체크아웃 .env에서 openai로 켠다
    llm_provider: Literal["openai", "mock"] = Field(default="mock", validation_alias="NEUMANN_LLM_PROVIDER")
    llm_model: str = Field(default="gpt-6.1-sol", validation_alias="NEUMANN_LLM_MODEL")
    llm_timeout_s: float = Field(default=60.0, gt=0, validation_alias="NEUMANN_LLM_TIMEOUT_S")

    # 임베딩·데이터 경로
    embed_model: str | None = Field(default=None, validation_alias="NEUMANN_EMBED_MODEL")
    raw_dir: Path | None = Field(default=None, validation_alias="NEUMANN_RAW_DIR")
    data_dir: Path = Field(default=REPO_ROOT / "data", validation_alias="NEUMANN_DATA_DIR")

    # 서버
    api_host: str = Field(default="127.0.0.1", validation_alias="NEUMANN_API_HOST")
    api_port: int = Field(default=8000, ge=1, le=65535, validation_alias="NEUMANN_API_PORT")

    # 테스트: 실제 API를 부르는 테스트는 이 값이 참일 때만 돈다
    live_tests: bool = Field(default=False, validation_alias="NEUMANN_LIVE_TESTS")

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스 공용 설정(캐시). 테스트에서 바꿨으면 `get_settings.cache_clear()`."""
    return Settings()


def live_llm_allowed() -> bool:
    """실제 OpenAI 호출을 해도 되는가. 프로세스 환경변수 `NEUMANN_LIVE_LLM_OK`만 본다(`.env`는 보지 않는다).

    요청마다 다시 읽는다(설정 캐시와 무관). 1·true·yes·on만 참이고 나머지는 모두 닫힌 쪽이다."""
    return os.environ.get(LIVE_LLM_FLAG, "").strip().lower() in _TRUE


__all__ = ["ENV_FILE", "LIVE_LLM_FLAG", "REPO_ROOT", "Settings", "get_settings", "live_llm_allowed"]
