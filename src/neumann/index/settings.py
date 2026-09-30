"""색인·검색 설정(E2 전용). 공용 `neumann.config`에 없는 키만 여기서 환경변수로 받는다.

우선순위는 공용 설정과 같다: 환경변수 > 저장소 루트 `.env` > 기본값. 비밀값은 없다.

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| NEUMANN_INDEX_DIR | `{NEUMANN_DATA_DIR}/index` | 색인 폴더 |
| NEUMANN_EMBED_DEVICE | auto | auto(cuda 있으면 cuda) · cuda · cpu |
| NEUMANN_EMBED_BATCH | 16 | 임베딩 배치(VRAM 6GB·fp16·최대 512토큰 기준) |
| NEUMANN_EMBED_MAX_SEQ | 512 | 임베딩 최대 토큰 수(제목+초록은 대개 400 안쪽) |
| NEUMANN_SEARCH_ALPHA | 0.6 | 결합 점수에서 임베딩 비중(나머지는 BM25) |
| NEUMANN_SEARCH_SCORE_FLOOR | 0.0 | 점수 하한. 보정은 L1 |
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from neumann.config import ENV_FILE, get_settings


class IndexSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
        validate_by_name=True,
        validate_by_alias=True,
    )

    index_dir: Path | None = Field(default=None, validation_alias="NEUMANN_INDEX_DIR")
    embed_device: Literal["auto", "cuda", "cpu"] = Field(default="auto", validation_alias="NEUMANN_EMBED_DEVICE")
    embed_batch: int = Field(default=16, ge=1, le=512, validation_alias="NEUMANN_EMBED_BATCH")
    embed_max_seq: int = Field(default=512, ge=16, le=8192, validation_alias="NEUMANN_EMBED_MAX_SEQ")
    search_alpha: float = Field(default=0.6, ge=0.0, le=1.0, validation_alias="NEUMANN_SEARCH_ALPHA")
    search_score_floor: float = Field(default=0.0, ge=0.0, le=1.0, validation_alias="NEUMANN_SEARCH_SCORE_FLOOR")

    def resolved_index_dir(self) -> Path:
        return self.index_dir or (get_settings().data_dir / "index")


@lru_cache(maxsize=1)
def get_index_settings() -> IndexSettings:
    """캐시. 테스트에서 바꿨으면 `get_index_settings.cache_clear()`."""
    return IndexSettings()


__all__ = ["IndexSettings", "get_index_settings"]
