"""색인·검색 설정(E2 전용). 공용 `neumann.config`에 없는 키만 여기서 환경변수로 받는다.

우선순위는 공용 설정과 같다: 환경변수 > 저장소 루트 `.env` > 기본값. 비밀값은 없다.

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| NEUMANN_INDEX_DIR | `{NEUMANN_DATA_DIR}/index` | 색인 폴더 |
| NEUMANN_EMBED_DEVICE | auto | auto(cuda 있으면 cuda) · cuda · cpu |
| NEUMANN_EMBED_BATCH | 16 | 임베딩 배치(VRAM 6GB·fp16·최대 512토큰 기준) |
| NEUMANN_EMBED_MAX_SEQ | 512 | 임베딩 최대 토큰 수(제목+초록은 대개 400 안쪽) |
| NEUMANN_SEARCH_ALPHA | 0.6 | 결합 점수에서 임베딩 비중(나머지는 BM25) |
| NEUMANN_SEARCH_SCORE_FLOOR | (비움) | 점수 하한. 비우면 임베딩 모델별 실측 보정값(`search.FLOOR_CALIBRATION`, bge-m3 0.45), 보정값 없는 모델·어휘만 검색은 0 |
| NEUMANN_SEARCH_FUSION | rrf | 여러 질의 결합: rrf(질의별 순위 융합) · max(L0: 질의 중 최댓값) |
| NEUMANN_SEARCH_RRF_K | 60 | RRF 상수 k: 기여 = 축 가중치 / (k + 순위) |
| NEUMANN_SEARCH_PER_QUERY_MIN | 1 | 질의별 상위 할당: 질의마다 하한을 넘은 상위 n편을 결과에 먼저 넣는다(0이면 끔) |
| NEUMANN_SEARCH_AXIS_WEIGHTS | topic=1,method=1,data=1,evaluation=0.5 | 축별 가중치(`axes`로 축별 질의가 올 때) |
| NEUMANN_SEARCH_ADAPTIVE_ALPHA | true | 질의 낱말 중 색인 어휘에 있는 비율(idf 가중)만큼만 BM25에 비중을 준다(한국어 질의 = 임베딩만) |
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
    search_score_floor: float | None = Field(default=None, ge=0.0, le=1.0, validation_alias="NEUMANN_SEARCH_SCORE_FLOOR")
    search_fusion: Literal["rrf", "max"] = Field(default="rrf", validation_alias="NEUMANN_SEARCH_FUSION")
    search_rrf_k: float = Field(default=60.0, gt=0.0, le=10000.0, validation_alias="NEUMANN_SEARCH_RRF_K")
    search_per_query_min: int = Field(default=1, ge=0, le=100, validation_alias="NEUMANN_SEARCH_PER_QUERY_MIN")
    search_axis_weights: str = Field(
        default="topic=1,method=1,data=1,evaluation=0.5", validation_alias="NEUMANN_SEARCH_AXIS_WEIGHTS"
    )
    search_adaptive_alpha: bool = Field(default=True, validation_alias="NEUMANN_SEARCH_ADAPTIVE_ALPHA")

    def axis_weights(self) -> dict[str, float]:
        """`topic=1,method=1,data=1,evaluation=0.5` → dict. 빠진 축은 1.0. 형식이 틀리면 ValueError."""
        out = {"topic": 1.0, "method": 1.0, "data": 1.0, "evaluation": 1.0}
        for part in (self.search_axis_weights or "").split(","):
            if not part.strip():
                continue
            name, sep, val = part.partition("=")
            if not sep:
                raise ValueError(f"NEUMANN_SEARCH_AXIS_WEIGHTS 형식 오류: {part!r} (축=가중치)")
            w = float(val)
            if not 0.0 <= w <= 10.0:
                raise ValueError(f"축 가중치는 0~10: {part!r}")
            out[name.strip().lower()] = w
        return out

    def resolved_index_dir(self) -> Path:
        return self.index_dir or (get_settings().data_dir / "index")


@lru_cache(maxsize=1)
def get_index_settings() -> IndexSettings:
    """캐시. 테스트에서 바꿨으면 `get_index_settings.cache_clear()`."""
    return IndexSettings()


__all__ = ["IndexSettings", "get_index_settings"]
