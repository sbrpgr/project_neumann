"""E1-L3 샤드 받기(가짜 HF 서버)와 일반 ML 표본 추출. E1-L0 모듈 없이 돈다."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from neumann.sources import corpus_l3 as l3

REV = "0123456789abcdef0123456789abcdef01234567"


def _fake_hf(blobs: dict[int, bytes], *, lie_about: int | None = None, calls: list[str] | None = None) -> httpx.Client:
    """HF tree API + resolve URL을 흉내 낸다. lie_about 샤드는 tree에 다른 sha256을 알려 준다."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        if url == f"{l3.HF_BASE}/api/datasets/{l3.HF_REVIEWS_REPO}/tree/{REV}/data":
            items = []
            for i, data in blobs.items():
                sha = hashlib.sha256(data if i != lie_about else b"something else").hexdigest()
                items.append({"type": "file", "path": l3.shard_repo_path(i), "size": len(data), "lfs": {"oid": sha, "size": len(data)}})
            return httpx.Response(200, json=items)
        for i, data in blobs.items():
            if url == l3.shard_url(i, REV):
                return httpx.Response(200, content=data)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


BLOBS = {0: b"kit shard zero", 1: b"kit shard one", 2: b"PAR1 shard two bytes" * 50, 3: b"PAR1 shard three" * 70}


def _kit(tmp_path: Path) -> Path:
    kit = tmp_path / "kit"
    kit.mkdir()
    files = [
        {"path": f"data/researcharcade/reviews/{l3.shard_name(0)}", "sha256": hashlib.sha256(BLOBS[0]).hexdigest()},
        {"path": f"data/researcharcade/reviews/{l3.shard_name(1)}", "sha256": "f" * 64},  # 다른 리비전인 척
    ]
    (kit / "manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    return kit


def test_names_and_pinned_urls() -> None:
    assert l3.shard_name(2) == "train-00002-of-00006.parquet"
    assert l3.shard_rel_path(5) == "reviews/train-00005-of-00006.parquet"
    assert l3.shard_url(3) == (
        "https://huggingface.co/datasets/ulab-ai/ResearchArcade-openreview-reviews/resolve/"
        f"{l3.HF_REVIEWS_REVISION}/data/train-00003-of-00006.parquet"
    )
    assert l3.L3_SHARDS == (2, 3, 4, 5) and l3.KIT_SHARDS == (0, 1)


def test_fetch_writes_files_and_manifest(tmp_path: Path) -> None:
    out = tmp_path / "data" / "raw" / "researcharcade"
    with _fake_hf(BLOBS) as client:
        m = l3.fetch_shards(out, (2, 3), client=client, revision=REV, kit_raw_dir=_kit(tmp_path), log=lambda *_: None)
    assert [f["path"] for f in m["files"]] == ["reviews/train-00002-of-00006.parquet", "reviews/train-00003-of-00006.parquet"]
    for f, i in zip(m["files"], (2, 3)):
        data = (out / f["path"]).read_bytes()
        assert data == BLOBS[i]
        assert f["bytes"] == len(data)
        assert f["sha256"] == hashlib.sha256(data).hexdigest() == f["hf_lfs_sha256"]
        assert f["sha256_match"] is True
        assert f["url"] == l3.shard_url(i, REV) and f["revision"] == REV
        assert len(f["retrieved_at_utc"]) == 20 and f["retrieved_at_utc"].endswith("Z")
    on_disk = json.loads((out / l3.SHARD_MANIFEST).read_text(encoding="utf-8"))
    assert on_disk["files"] == m["files"] and on_disk["revision"] == REV
    assert [k["same"] for k in m["kit_consistency"]] == [True, False]  # 키트 샤드 1은 리비전이 다르다고 알린다
    assert not list(out.rglob("*.part"))


def test_fetch_rejects_sha_mismatch_and_leaves_nothing(tmp_path: Path) -> None:
    out = tmp_path / "raw"
    with _fake_hf(BLOBS, lie_about=3) as client, pytest.raises(l3.ShardIntegrityError):
        l3.fetch_shards(out, (3,), client=client, revision=REV, log=lambda *_: None)
    assert not (out / l3.shard_rel_path(3)).exists()
    assert not list(out.rglob("*.part"))


def test_fetch_skips_verified_existing(tmp_path: Path) -> None:
    out = tmp_path / "raw"
    with _fake_hf(BLOBS) as client:
        first = l3.fetch_shards(out, (2,), client=client, revision=REV, log=lambda *_: None)
    calls: list[str] = []
    with _fake_hf(BLOBS, calls=calls) as client:
        second = l3.fetch_shards(out, (2,), client=client, revision=REV, log=lambda *_: None)
    assert not any(u.endswith(".parquet") for u in calls)  # tree만 묻고 파일은 다시 받지 않는다
    assert second["files"] == first["files"]
    # 파일이 바뀌면(손상) 다시 받는다
    (out / l3.shard_rel_path(2)).write_bytes(b"corrupted")
    calls.clear()
    with _fake_hf(BLOBS, calls=calls) as client:
        l3.fetch_shards(out, (2,), client=client, revision=REV, log=lambda *_: None)
    assert any(u.endswith(".parquet") for u in calls)
    assert (out / l3.shard_rel_path(2)).read_bytes() == BLOBS[2]


def test_fetch_missing_shard_in_revision(tmp_path: Path) -> None:
    with _fake_hf({2: BLOBS[2]}) as client, pytest.raises(l3.ShardIntegrityError):
        l3.fetch_shards(tmp_path / "raw", (4,), client=client, revision=REV, log=lambda *_: None)


# ── 일반 ML 표본 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("n", [0, 1, 7, 50, 99, 100, 250])
def test_allocate_exact_and_bounded(n: int) -> None:
    sizes = {("ICLR 2024", "reject"): 40, ("ICLR 2024", "accept_poster"): 25, ("ICLR 2025", "reject"): 30, ("ICLR 2025", "accept_oral"): 5}
    alloc = l3.allocate(sizes, n)
    assert sum(alloc.values()) == min(n, 100)
    assert all(0 <= alloc[k] <= sizes[k] for k in sizes)
    if 0 < n <= 100:
        for k, v in sizes.items():  # 비례에서 1 이상 벗어나지 않는다
            assert abs(alloc[k] - n * v / 100) < 1 + 1e-9


def test_sample_general_ml_deterministic_stratified() -> None:
    pool = {f"P{i:04d}": ("ICLR 2024" if i % 3 else "ICLR 2025", "reject" if i % 5 < 3 else "accept_poster") for i in range(600)}
    a, spec = l3.sample_general_ml(pool, 120, seed=7)
    b, _ = l3.sample_general_ml(dict(reversed(list(pool.items()))), 120, seed=7)  # 입력 순서와 무관
    c, _ = l3.sample_general_ml(pool, 120, seed=8)
    assert a == b and a != c
    assert len(a) == len(set(a)) == 120 and set(a) <= set(pool)
    assert spec["selected"] == 120 and spec["pool"] == 600 and spec["seed"] == 7
    assert sum(s["selected"] for s in spec["strata"]) == 120
    # 층 비율 보존: 거절 비율이 후보와 같다(최대 나머지 반올림 안)
    rej_pool = sum(1 for v in pool.values() if v[1] == "reject") / len(pool)
    rej_sample = sum(1 for p in a if pool[p][1] == "reject") / len(a)
    assert abs(rej_pool - rej_sample) <= 2 / 120
    # n이 후보 수 이상이면 후보 전부
    big, _ = l3.sample_general_ml(pool, 10_000, seed=7)
    assert set(big) == set(pool)
