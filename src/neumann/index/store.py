"""색인 저장소: 논문·심사평·문장(Excerpt)·규칙 태그·BM25·임베딩.

공개 함수(E3·E4·E5가 쓴다):
- `get_excerpts(work_id) -> list[Excerpt]`: 그 논문의 심사평 문장, 번호 순서(심사평 순서 → 원문 위치)
- `get_work(work_id) -> Work` (없으면 KeyError), `get_reviews(work_id) -> list[ReviewEvent]`
- `get_excerpt(excerpt_id) -> Excerpt | None`, `get_rule_tags(work_id) -> list[RiskTag]`
- `get_store()`: 공유 데이터 폴더 `data/index/`를 프로세스당 한 번 읽어 캐시한다(서버 시작 때 한 번)
- `set_store(store)`: 테스트·fixture 어댑터가 메모리 저장소를 주입한다. `None`이면 캐시를 비운다

디스크 형식(`data/index/`): works.jsonl, reviews.jsonl, excerpts.jsonl, tags.jsonl, bm25.json,
embeddings.npy(float16, 행 순서 = bm25.json의 doc_ids), manifest.json.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from neumann.index.bm25 import BM25Index
from neumann.index.sentences import excerpts_for_reviews, review_sort_key
from neumann.index.settings import get_index_settings
from neumann.index.taxonomy import tag_excerpts
from neumann.models import Excerpt, ReviewEvent, RiskTag, Work

INDEX_FORMAT = "neumann-index-v1"
FILES = {
    "works": "works.jsonl",
    "reviews": "reviews.jsonl",
    "excerpts": "excerpts.jsonl",
    "tags": "tags.jsonl",
    "bm25": "bm25.json",
    "embeddings": "embeddings.npy",
    "manifest": "manifest.json",
}


class IndexNotBuilt(FileNotFoundError):
    """색인 폴더에 manifest.json이 없다. `python scripts/build_index.py`를 먼저 돌린다."""


def work_text(work: Work) -> str:
    """검색 문서 텍스트: 제목 + 초록(임베딩·BM25 공용)."""
    return work.title if not work.abstract else f"{work.title}\n\n{work.abstract}"


class IndexStore:
    """메모리 색인. 만들기는 `from_corpus`(빌드·테스트) 또는 `load`(디스크)."""

    def __init__(
        self,
        works: dict[str, Work],
        reviews: dict[str, list[ReviewEvent]],
        excerpt_rows: dict[str, list[dict[str, Any]]],
        tag_rows: dict[str, list[dict[str, Any]]],
        bm25: BM25Index,
        embeddings: np.ndarray | None,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        self.works = works
        self.reviews = reviews
        self._excerpt_rows = excerpt_rows
        self._tag_rows = tag_rows
        self._excerpts: dict[str, list[Excerpt]] = {}
        self._tags: dict[str, list[RiskTag]] = {}
        self._excerpt_work: dict[str, str] = {
            row["excerpt_id"]: wid for wid, rows in excerpt_rows.items() for row in rows
        }
        self.bm25 = bm25
        self.work_order: list[str] = list(bm25.doc_ids)
        if embeddings is not None and embeddings.shape[0] != len(self.work_order):
            raise ValueError(f"임베딩 행 수 {embeddings.shape[0]} != 논문 수 {len(self.work_order)}")
        self.embeddings = None if embeddings is None else np.ascontiguousarray(embeddings, dtype=np.float32)
        self.manifest: dict[str, Any] = manifest or {}
        self._lock = threading.Lock()

    # ── 만들기 ──
    @classmethod
    def from_corpus(
        cls,
        works: Iterable[Work],
        reviews: Iterable[ReviewEvent],
        *,
        embedder: Any | None = None,
        timings: dict[str, float] | None = None,
    ) -> IndexStore:
        """코퍼스 → 메모리 색인. embedder가 없으면 임베딩 없이(어휘 검색만) 만든다.

        timings를 주면 단계별 소요 초(sentences·tags·bm25·embed)를 채운다.
        """
        tm = timings if timings is not None else {}
        t0 = time.perf_counter()
        works_by_id = {w.work_id: w for w in sorted(works, key=lambda w: w.work_id)}
        rev_by_work: dict[str, list[ReviewEvent]] = {}
        for r in reviews:
            if r.work_id in works_by_id:
                rev_by_work.setdefault(r.work_id, []).append(r)
        for wid in rev_by_work:
            rev_by_work[wid].sort(key=review_sort_key)
        excerpts_by_work: dict[str, list[Excerpt]] = {wid: excerpts_for_reviews(revs) for wid, revs in rev_by_work.items()}
        excerpt_rows = {wid: [ex.model_dump(mode="json") for ex in exs] for wid, exs in excerpts_by_work.items()}
        t1 = time.perf_counter()
        tm["sentences_s"] = t1 - t0
        tag_rows = {
            wid: [t.model_dump(mode="json") for t in tag_excerpts(exs)] for wid, exs in excerpts_by_work.items()
        }
        t2 = time.perf_counter()
        tm["tags_s"] = t2 - t1
        order = list(works_by_id)
        texts = [work_text(works_by_id[w]) for w in order]
        bm25 = BM25Index.build(order, texts)
        t3 = time.perf_counter()
        tm["bm25_s"] = t3 - t2
        emb = None
        if embedder is not None and order:
            emb = np.asarray(embedder.encode(texts), dtype=np.float32)
        tm["embed_s"] = time.perf_counter() - t3
        manifest = {
            "format": INDEX_FORMAT,
            "dense_model": getattr(embedder, "model_id", None) if embedder is not None else None,
            "dense_dim": int(emb.shape[1]) if emb is not None else None,
        }
        return cls(works_by_id, rev_by_work, excerpt_rows, tag_rows, bm25, emb, manifest)

    @classmethod
    def load(cls, index_dir: str | Path) -> IndexStore:
        d = Path(index_dir)
        mpath = d / FILES["manifest"]
        if not mpath.is_file():
            raise IndexNotBuilt(f"색인이 없다: {mpath} (python scripts/build_index.py)")
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        if manifest.get("format") != INDEX_FORMAT:
            raise ValueError(f"색인 형식이 다르다: {manifest.get('format')!r} != {INDEX_FORMAT}")
        works: dict[str, Work] = {}
        for row in _read_jsonl(d / FILES["works"]):
            w = Work.model_validate(row)
            works[w.work_id] = w
        reviews: dict[str, list[ReviewEvent]] = {}
        for row in _read_jsonl(d / FILES["reviews"]):
            r = ReviewEvent.model_validate(row)
            reviews.setdefault(r.work_id, []).append(r)
        excerpt_rows: dict[str, list[dict[str, Any]]] = {}
        for row in _read_jsonl(d / FILES["excerpts"]):
            wid = row.pop("work_id")
            row.pop("seq", None)
            excerpt_rows.setdefault(wid, []).append(row)
        tag_rows: dict[str, list[dict[str, Any]]] = {}
        for row in _read_jsonl(d / FILES["tags"]):
            wid = row.pop("work_id")
            tag_rows.setdefault(wid, []).append(row)
        bm25 = BM25Index.from_json(json.loads((d / FILES["bm25"]).read_text(encoding="utf-8")))
        emb_path = d / FILES["embeddings"]
        emb = np.load(emb_path).astype(np.float32) if emb_path.is_file() else None
        return cls(works, reviews, excerpt_rows, tag_rows, bm25, emb, manifest)

    # ── 저장 ──
    def save(self, index_dir: str | Path, manifest_extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """디스크에 쓴다. 파일마다 임시 이름으로 쓰고 바꿔치기, manifest.json은 맨 마지막."""
        d = Path(index_dir)
        d.mkdir(parents=True, exist_ok=True)
        _write_jsonl(d / FILES["works"], (w.model_dump(mode="json") for w in self.works.values()))
        _write_jsonl(
            d / FILES["reviews"],
            (r.model_dump(mode="json") for wid in sorted(self.reviews) for r in self.reviews[wid]),
        )
        _write_jsonl(
            d / FILES["excerpts"],
            (
                {"work_id": wid, "seq": i, **row}
                for wid in sorted(self._excerpt_rows)
                for i, row in enumerate(self._excerpt_rows[wid])
            ),
        )
        _write_jsonl(
            d / FILES["tags"],
            ({"work_id": wid, **row} for wid in sorted(self._tag_rows) for row in self._tag_rows[wid]),
        )
        _atomic_write_text(d / FILES["bm25"], json.dumps(self.bm25.to_json(), ensure_ascii=False))
        emb_path = d / FILES["embeddings"]
        if self.embeddings is not None:
            tmp = emb_path.with_name(emb_path.name + ".tmp.npy")
            np.save(tmp, self.embeddings.astype(np.float16))
            os.replace(tmp, emb_path)
        elif emb_path.exists():
            emb_path.unlink()
        manifest = {**self.manifest, **(manifest_extra or {}), "format": INDEX_FORMAT}
        manifest["files"] = {
            name: {"path": fname, "bytes": (d / fname).stat().st_size}
            for name, fname in FILES.items()
            if name != "manifest" and (d / fname).exists()
        }
        manifest["index_bytes"] = sum(f["bytes"] for f in manifest["files"].values())
        _atomic_write_text(d / FILES["manifest"], json.dumps(manifest, ensure_ascii=False, indent=2))
        self.manifest = manifest
        return manifest

    # ── 조회 ──
    def get_work(self, work_id: str) -> Work:
        return self.works[work_id]

    def get_reviews(self, work_id: str) -> list[ReviewEvent]:
        return list(self.reviews.get(work_id, []))

    def get_excerpts(self, work_id: str) -> list[Excerpt]:
        cached = self._excerpts.get(work_id)
        if cached is None:
            with self._lock:
                cached = [Excerpt.model_validate(row) for row in self._excerpt_rows.get(work_id, [])]
                self._excerpts[work_id] = cached
        return list(cached)

    def get_excerpt(self, excerpt_id: str) -> Excerpt | None:
        wid = self._excerpt_work.get(excerpt_id)
        if wid is None:
            return None
        for ex in self.get_excerpts(wid):
            if ex.excerpt_id == excerpt_id:
                return ex
        return None

    def excerpt_work_id(self, excerpt_id: str) -> str | None:
        return self._excerpt_work.get(excerpt_id)

    def get_rule_tags(self, work_id: str) -> list[RiskTag]:
        cached = self._tags.get(work_id)
        if cached is None:
            with self._lock:
                cached = [RiskTag.model_validate(row) for row in self._tag_rows.get(work_id, [])]
                self._tags[work_id] = cached
        return list(cached)

    def work_ids(self) -> list[str]:
        return list(self.work_order)

    def n_excerpts(self) -> int:
        return sum(len(v) for v in self._excerpt_rows.values())

    def n_tags(self) -> int:
        return sum(len(v) for v in self._tag_rows.values())

    def iter_excerpt_rows(self) -> Iterable[tuple[str, dict[str, Any]]]:
        for wid in sorted(self._excerpt_rows):
            for row in self._excerpt_rows[wid]:
                yield wid, row

    def iter_tag_rows(self) -> Iterable[tuple[str, dict[str, Any]]]:
        for wid in sorted(self._tag_rows):
            for row in self._tag_rows[wid]:
                yield wid, row

    def verify_offsets(self) -> dict[str, int]:
        """저장된 문장 전량을 원문 오프셋으로 잘라 대조한다."""
        review_text = {r.review_id: r.text for revs in self.reviews.values() for r in revs}
        checked = passed = 0
        for _wid, row in self.iter_excerpt_rows():
            checked += 1
            src = review_text.get(row["source_id"])
            if src is None:
                continue
            ex = Excerpt.model_validate(row)
            if src[ex.start : ex.end] == ex.text and ex.verify_against(src):
                passed += 1
        return {"checked": checked, "passed": passed, "failed": checked - passed}


# ── 파일 도우미 ──
def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


# ── 프로세스 공용 저장소 ──
_STORE: IndexStore | None = None
_STORE_LOCK = threading.Lock()
_LOAD_SECONDS: float | None = None


def get_store() -> IndexStore:
    """공유 색인을 한 번 읽어 캐시한다. 없으면 IndexNotBuilt."""
    global _STORE, _LOAD_SECONDS
    if _STORE is not None:
        return _STORE
    with _STORE_LOCK:
        if _STORE is None:
            t0 = time.perf_counter()
            _STORE = IndexStore.load(get_index_settings().resolved_index_dir())
            _LOAD_SECONDS = time.perf_counter() - t0
        return _STORE


def set_store(store: IndexStore | None) -> None:
    """메모리 저장소 주입(테스트·fixture). None이면 캐시를 비워 다음 호출 때 디스크에서 다시 읽는다."""
    global _STORE, _LOAD_SECONDS
    with _STORE_LOCK:
        _STORE = store
        _LOAD_SECONDS = None


def store_load_seconds() -> float | None:
    return _LOAD_SECONDS


def get_excerpts(work_id: str) -> list[Excerpt]:
    return get_store().get_excerpts(work_id)


def get_work(work_id: str) -> Work:
    return get_store().get_work(work_id)


def get_reviews(work_id: str) -> list[ReviewEvent]:
    return get_store().get_reviews(work_id)


def get_excerpt(excerpt_id: str) -> Excerpt | None:
    return get_store().get_excerpt(excerpt_id)


def get_rule_tags(work_id: str) -> list[RiskTag]:
    return get_store().get_rule_tags(work_id)


def build_store_from(works: Sequence[Work], reviews: Sequence[ReviewEvent], *, embedder: Any | None = None) -> IndexStore:
    """편의 함수: 코퍼스로 메모리 저장소를 만들어 공용 저장소로 주입하고 돌려준다(E3 fixture 어댑터용)."""
    store = IndexStore.from_corpus(works, reviews, embedder=embedder)
    set_store(store)
    return store


__all__ = [
    "FILES",
    "INDEX_FORMAT",
    "IndexNotBuilt",
    "IndexStore",
    "build_store_from",
    "get_excerpt",
    "get_excerpts",
    "get_reviews",
    "get_rule_tags",
    "get_store",
    "get_work",
    "set_store",
    "store_load_seconds",
    "work_text",
]
