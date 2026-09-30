"""E1-L3 실제 산출물 검사(공유 데이터 폴더에 `processed_l3`가 있고 E1-L0 모듈이 있을 때만 돈다)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("neumann.sources.researcharcade", reason="E1-L0(researcharcade)가 아직 병합되지 않았다")

from neumann.sources import corpus_l3 as l3  # noqa: E402

# HF ulab-ai/ResearchArcade-openreview-reviews @179a536…의 LFS sha256(2026-09-30 받음, tree API와 대조)
HF_SHA256 = {
    0: "23dba878e79de4704b2b1f1df5e7c0130c8b955871d735492e218761dfafe659",
    1: "ad84f8c50912d4a15ee6786c727adc2a33a406caea9cf657c4d577eaf7a284fc",
    2: "af626e352ccf008ea319a9d83d3927cc2d0bea4e80674edde870770d62dbedcf",
    3: "bb0fcf3f00583d238ff7aa686f28375dd85b3a1a3b0c5142e23a644c7d014f6d",
    4: "4cd338c9f1522593ad3b03adcf4a5a1af28c8b0358f4436559d6b426512ffbd2",
    5: "9095d8801e48e34ee192821e4e3286ffc34f3fda46fffb486b6e3ff5676239ed",
}


def _l3_dir() -> Path | None:
    cands = [Path(os.environ["NEUMANN_DATA_DIR"])] if os.getenv("NEUMANN_DATA_DIR") else []
    try:
        from neumann.config import get_settings

        cands.append(get_settings().data_dir)
    except Exception:
        pass
    for c in cands:
        try:
            return l3.resolve_l3_dir(c)
        except FileNotFoundError:
            continue
    return None


L3_DIR = _l3_dir()
pytestmark = pytest.mark.skipif(L3_DIR is None, reason="공유 데이터 폴더에 processed_l3가 없다")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((L3_DIR / "corpus_manifest.json").read_text(encoding="utf-8"))


def test_audit_all_records() -> None:
    rep = l3.audit_l3(L3_DIR)
    assert rep["violations"] == 0
    assert rep["works"] >= l3.MIN_TOTAL_WORKS
    assert rep["source_url_ratio"] == 1.0
    assert rep["by_group"]["ai4science"] >= 1000 and rep["by_group"]["general_ml"] >= 1


def test_all_six_shards_and_hashes(manifest: dict) -> None:
    shards = {i["shard"]: i for i in manifest["inputs"] if "shard" in i}
    assert sorted(shards) == list(range(l3.N_SHARDS))
    for i, info in shards.items():
        assert info["sha256"] == HF_SHA256[i] and info["manifest_sha256_match"] is True
        assert info["origin"] == ("kit" if i in l3.KIT_SHARDS else "l3")
        assert info["url"] and info["retrieved_at_utc"]
    for name, info in manifest["outputs"].items():
        assert hashlib.sha256((L3_DIR / name).read_bytes()).hexdigest() == info["sha256"]


def test_coverage_improves_with_all_shards(manifest: dict) -> None:
    cov = manifest["coverage"]
    assert cov["before"]["shards"] == [0, 1] and cov["after"]["shards"] == [0, 1, 2, 3, 4, 5]
    for key in ("population", "ai4science", "general_ml_population"):
        assert cov["after"][key]["with_official_review"] >= cov["before"][key]["with_official_review"]
    assert cov["after"]["population"]["ratio"] > cov["before"]["population"]["ratio"]
    assert cov["after"]["ai4science"]["ratio"] > cov["before"]["ai4science"]["ratio"]
