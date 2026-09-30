"""bge-m3 임베딩(로컬 모델, 오프라인). GPU가 있으면 cuda + fp16, 없으면 cpu.

- 모델 경로는 `NEUMANN_EMBED_MODEL`(공용 설정). 네트워크로 받지 않는다(HF_HUB_OFFLINE 권장).
- 벡터는 L2 정규화한 float32다(코사인 = 내적).
- 프로세스당 한 번만 읽는다(`get_embedder()` 캐시). 서버가 켜질 때 한 번 로드된다.
- 테스트는 `Embedder` 프로토콜을 만족하는 가짜를 주입한다(모델을 읽지 않는다).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from neumann.config import get_settings
from neumann.index.settings import get_index_settings

log = logging.getLogger(__name__)


@runtime_checkable
class Embedder(Protocol):
    model_id: str
    dim: int
    device: str

    def encode(self, texts: list[str]) -> np.ndarray:
        """텍스트 목록 → (n, dim) float32, 행마다 L2 정규화."""
        ...


class EmbedderUnavailable(RuntimeError):
    """임베딩 모델을 읽을 수 없다(경로 없음·패키지 오류 등). 호출부는 어휘 검색으로 강등하고 표시한다."""


def pick_device(pref: str = "auto") -> str:
    if pref == "cpu":
        return "cpu"
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:  # pragma: no cover - torch 없는 환경
        pass
    if pref == "cuda":
        log.warning("NEUMANN_EMBED_DEVICE=cuda인데 CUDA를 쓸 수 없다. cpu로 돈다")
    return "cpu"


class BgeM3Embedder:
    """sentence-transformers로 bge-m3 dense 벡터(1024차원)."""

    def __init__(self, model_path: str | Path, *, device: str = "auto", batch_size: int = 16, max_seq: int = 512):
        path = Path(model_path)
        if not path.exists():
            raise EmbedderUnavailable(f"임베딩 모델 경로가 없다: {path}")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        t0 = time.perf_counter()
        try:
            import torch
            from sentence_transformers import SentenceTransformer

            self.device = pick_device(device)
            kwargs = {"torch_dtype": torch.float16} if self.device == "cuda" else {}
            self._model = SentenceTransformer(str(path), device=self.device, model_kwargs=kwargs)
        except Exception as exc:  # 모델 파일 손상·패키지 문제
            raise EmbedderUnavailable(f"임베딩 모델 로드 실패: {type(exc).__name__}: {exc}") from exc
        self._model.max_seq_length = max_seq
        self.batch_size = batch_size
        self.max_seq = max_seq
        self.model_id = path.name
        self.model_path = str(path)
        get_dim = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self.dim = int(get_dim())
        self.load_seconds = time.perf_counter() - t0
        self._lock = threading.Lock()

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        with self._lock:  # 한 GPU 모델을 여러 스레드가 동시에 부르지 않게
            vecs = self._model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        return np.asarray(vecs, dtype=np.float32)


_CACHE: dict[tuple[str, str], Embedder] = {}
_CACHE_LOCK = threading.Lock()


def get_embedder(model_path: str | Path | None = None) -> Embedder:
    """프로세스 공용 bge-m3(캐시). 모델이 없으면 EmbedderUnavailable."""
    ist = get_index_settings()
    path = model_path or get_settings().embed_model
    if not path:
        raise EmbedderUnavailable("NEUMANN_EMBED_MODEL이 설정되지 않았다")
    key = (str(path), ist.embed_device)
    with _CACHE_LOCK:
        emb = _CACHE.get(key)
        if emb is None:
            emb = BgeM3Embedder(path, device=ist.embed_device, batch_size=ist.embed_batch, max_seq=ist.embed_max_seq)
            _CACHE[key] = emb
        return emb


def clear_embedder_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = ["BgeM3Embedder", "Embedder", "EmbedderUnavailable", "clear_embedder_cache", "get_embedder", "pick_device"]
