"""E2 테스트 공용: 작은 가짜 코퍼스와 결정적 가짜 임베더(모델을 읽지 않는다).

내용은 전부 가짜다(분명히 가짜인 URL·id). 실제 bge-m3 검사는 test_e2_model_live.py(환경변수로 켬).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

import numpy as np
import pytest

from neumann.index import search as search_mod
from neumann.index import store as store_mod
from neumann.models import Provenance, ReviewEvent, Work, sha256_text

ACCESSED = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)


def prov(url: str, text: str) -> Provenance:
    return Provenance(source="fixture", source_url=url, accessed_at=ACCESSED, content_sha256=sha256_text(text))


WORKS = [
    (
        "fake:bat-1",
        "Graph neural network surrogate for ionic conductivity of liquid electrolytes",
        "We train a message passing graph neural network on molecular graphs of solvents and lithium salts to "
        "predict ionic conductivity of battery electrolytes, and screen candidate formulations.",
    ),
    (
        "fake:mol-2",
        "Equivariant message passing for molecular property prediction",
        "An E(3)-equivariant graph network predicts quantum chemical properties of small molecules on QM9 "
        "with scaffold split evaluation.",
    ),
    (
        "fake:med-3",
        "Uncertainty-aware segmentation of tumors in MRI",
        "We propose a U-Net variant with Monte Carlo dropout for brain tumor segmentation in magnetic resonance "
        "images and evaluate calibration across hospitals.",
    ),
    (
        "fake:pro-4",
        "Diffusion models for protein backbone generation",
        "A denoising diffusion model generates protein backbones; designability is assessed with structure "
        "prediction and in silico folding.",
    ),
]

REVIEWS = {
    "fake:bat-1": [
        "Summary:\nThe paper predicts ionic conductivity with a GNN.\n\nStrengths:\n- The paper is well written and easy to follow.\n"
        "\nWeaknesses:\n1. The random split likely leaks near-duplicate electrolyte formulations between train and test. "
        "2. Only a single seed is reported, so error bars are missing.3. The baselines are outdated; please compare "
        "with recent models, e.g. Smith et al. (2023).",
        "The claims about screening are not supported by any wet-lab validation. Is the model physically plausible "
        "outside the training temperature range? The code is not available, which hurts reproducibility.",
    ],
    "fake:mol-2": [
        "Novelty is limited: equivariant message passing was already proposed in prior work. The ablation study "
        "is thorough. However, results on only QM9 do not show generalization to larger molecules.",
    ],
    "fake:med-3": [
        "The dataset is small (48 patients) and data collection differs across sites. How was the data annotated? "
        "The writing is hard to follow in Section 3.",
    ],
}


def make_corpus() -> tuple[list[Work], list[ReviewEvent]]:
    works = [
        Work(
            work_id=wid,
            title=title,
            abstract=abstract,
            url=f"https://example.org/fake-venue/forum?id={wid.split(':')[1]}",
            provenance=prov(f"https://example.org/fake-venue/forum?id={wid.split(':')[1]}", title + abstract),
        )
        for wid, title, abstract in WORKS
    ]
    reviews: list[ReviewEvent] = []
    for wid, texts in REVIEWS.items():
        native = wid.split(":")[1]
        for i, text in enumerate(texts):
            rid = f"rev-{native}-{i}"
            url = f"https://example.org/fake-venue/forum?id={native}&noteId={rid}"
            reviews.append(
                ReviewEvent(
                    review_id=rid,
                    work_id=wid,
                    text=text,
                    url=url,
                    created=datetime(2024, 11, 1 + i, tzinfo=UTC),
                    provenance=prov(url, text),
                )
            )
    return works, reviews


# 한국어 → 영어 작은 사전: 가짜 임베더가 "다국어"처럼 굴게 한다(배관 검사용. 실제 다국어는 bge-m3 라이브 테스트)
KO_EN = {
    "배터리": "battery",
    "전해액": "electrolyte",
    "이온전도도": "ionic conductivity",
    "그래프": "graph",
    "신경망": "neural network",
    "분자": "molecular",
    "종양": "tumor",
    "분할": "segmentation",
    "단백질": "protein",
}


class FakeEmbedder:
    """해시 낱말 주머니 → 256차원 정규화 벡터. 결정적."""

    model_id = "fake-embedder"
    dim = 256
    device = "cpu"

    def __init__(self) -> None:
        self.calls = 0

    def _vec(self, text: str) -> np.ndarray:
        for ko, en in KO_EN.items():
            text = text.replace(ko, f" {en} ")
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in re.findall(r"[a-z]+", text.lower()):
            if len(tok) < 3:
                continue
            tok = tok.rstrip("s")
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)


@pytest.fixture
def corpus() -> tuple[list[Work], list[ReviewEvent]]:
    return make_corpus()


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def mem_store(corpus, fake_embedder):
    """가짜 임베더로 만든 메모리 색인을 공용 저장소로 주입한다. 끝나면 원상복구."""
    works, reviews = corpus
    st = store_mod.IndexStore.from_corpus(works, reviews, embedder=fake_embedder)
    store_mod.set_store(st)
    search_mod.set_query_embedder(fake_embedder)
    yield st
    store_mod.set_store(None)
    search_mod.set_query_embedder(None)
