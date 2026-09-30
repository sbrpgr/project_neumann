"""코퍼스 → 검색 색인(`data/index/`): 문장 Excerpt·규칙 태그·BM25·bge-m3 임베딩·manifest.json.

    python scripts/build_index.py                       # 공유 data/processed (E1 load_corpus)
    python scripts/build_index.py --source fixtures     # tests/fixtures (개발용)
    python scripts/build_index.py --out DIR --no-embed  # 임베딩 없이(어휘만, 강등 표시)
    python scripts/build_index.py --source jsonl --processed DIR   # 폴더의 works.jsonl·reviews.jsonl

환경변수: NEUMANN_DATA_DIR, NEUMANN_EMBED_MODEL, (선택) NEUMANN_INDEX_DIR, NEUMANN_EMBED_DEVICE, NEUMANN_EMBED_BATCH.
색인 파일은 커밋하지 않는다(.gitignore의 data/).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from neumann.config import get_settings  # noqa: E402
from neumann.index.embed import EmbedderUnavailable, get_embedder  # noqa: E402
from neumann.index.settings import get_index_settings  # noqa: E402
from neumann.index.store import IndexStore  # noqa: E402
from neumann.models import ReviewEvent, Work  # noqa: E402


# 색인이 실제로 읽는 입력(해시 대상). corpus_manifest.json은 생성 시각이 바뀌므로 넣지 않는다
CORPUS_FILES = ("works.jsonl", "reviews.jsonl")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def input_digest(files: list[Path], base: Path) -> dict[str, Any]:
    per = {str(p.relative_to(base)).replace("\\", "/"): sha256_file(p) for p in sorted(files)}
    combined = hashlib.sha256("".join(f"{k}:{v}\n" for k, v in per.items()).encode()).hexdigest()
    return {"sha256": combined, "files": per}


def _values(x: Any) -> list[Any]:
    return list(x.values()) if isinstance(x, dict) else list(x)


def _parts(corpus: Any) -> tuple[list[Work], list[ReviewEvent]]:
    """load_corpus 반환값(E1 `Corpus`: works는 dict, reviews는 list)에서 works·reviews를 꺼낸다."""
    if isinstance(corpus, dict):
        works, reviews = corpus["works"], corpus["reviews"]
    elif hasattr(corpus, "works") and hasattr(corpus, "reviews"):
        works, reviews = corpus.works, corpus.reviews
    elif isinstance(corpus, tuple) and len(corpus) >= 2:
        works, reviews = corpus[0], corpus[1]
    else:
        raise TypeError(f"load_corpus 반환형을 모른다: {type(corpus).__name__}")
    works, reviews = _values(works), _values(reviews)
    bad = [type(w).__name__ for w in works[:1] if not isinstance(w, Work)] + [
        type(r).__name__ for r in reviews[:1] if not isinstance(r, ReviewEvent)
    ]
    if bad:
        raise TypeError(f"load_corpus가 Work/ReviewEvent가 아닌 것을 돌려줬다: {bad}")
    return works, reviews


def load_source(source: str, processed_dir: Path) -> tuple[list[Work], list[ReviewEvent], dict[str, Any]]:
    if source == "fixtures":
        from tests.fixtures.loader import FIXTURES_DIR, load_fixtures

        fx = load_fixtures()
        files = [FIXTURES_DIR / "works.jsonl", FIXTURES_DIR / "reviews.jsonl"]
        return list(fx.works), list(fx.reviews), {"source": "fixtures", "dir": "tests/fixtures", **input_digest(files, FIXTURES_DIR)}
    # 색인이 실제로 읽는 입력만 해시한다(같은 폴더의 다른 소스 파일, 예 retraction.jsonl은 제외)
    files = [processed_dir / n for n in CORPUS_FILES]
    note = None
    if source == "processed":
        try:
            from neumann.sources.corpus import load_corpus
        except ImportError as exc:  # E1 코드가 아직 병합되지 않은 브랜치
            note = f"load_corpus를 불러오지 못해 jsonl 직접 읽기로 대신함: {exc}"
            print(f"[build_index] 주의: {note}")
        else:
            works, reviews = _parts(load_corpus(processed_dir))
            return works, reviews, {"source": "processed", "dir": str(processed_dir), **input_digest(files, processed_dir)}
    # 폴더의 works.jsonl·reviews.jsonl을 계약 모델로 바로 읽는다(검증 포함)
    wpath, rpath = files
    works = [Work.model_validate_json(x) for x in wpath.read_text(encoding="utf-8").splitlines() if x.strip()]
    reviews = [ReviewEvent.model_validate_json(x) for x in rpath.read_text(encoding="utf-8").splitlines() if x.strip()]
    info = {"source": "jsonl", "dir": str(processed_dir), **input_digest(files, processed_dir)}
    if note:
        info["fallback"] = note
    return works, reviews, info


def gpu_info(device: str | None) -> dict[str, Any]:
    info: dict[str, Any] = {"device": device, "cuda_available": False}
    try:
        import torch

        info["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["vram_total_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2)
            info["peak_vram_alloc_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 3)
    except Exception:  # pragma: no cover
        pass
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["processed", "fixtures", "jsonl"], default="processed",
                    help="processed: E1 load_corpus(기본) · fixtures: tests/fixtures · jsonl: 폴더의 works/reviews.jsonl")
    ap.add_argument("--processed", type=Path, default=None, help="코퍼스 폴더(기본 {DATA_DIR}/processed)")
    ap.add_argument("--out", type=Path, default=None, help="색인 폴더(기본 {DATA_DIR}/index)")
    ap.add_argument("--no-embed", action="store_true", help="임베딩 없이 만든다(어휘 검색만, 강등 표시)")
    args = ap.parse_args(argv)

    settings = get_settings()
    ist = get_index_settings()
    processed = args.processed or settings.data_dir / "processed"
    out = args.out or ist.resolved_index_dir()

    t_start = time.perf_counter()
    stages: dict[str, float] = {}
    t = time.perf_counter()
    works, reviews, input_info = load_source(args.source, processed)
    stages["load_corpus_s"] = time.perf_counter() - t
    print(f"[build_index] 입력 {input_info['source']}: 논문 {len(works)}편, 심사평 {len(reviews)}건 ({stages['load_corpus_s']:.1f}s)")

    embedder = None
    degraded_reason = None
    if args.no_embed:
        degraded_reason = "--no-embed: 임베딩 없이 빌드"
    else:
        t = time.perf_counter()
        try:
            embedder = get_embedder()
        except EmbedderUnavailable as exc:
            degraded_reason = str(exc)
        stages["embed_model_load_s"] = time.perf_counter() - t
    if degraded_reason:
        print(f"[build_index] 강등: {degraded_reason}")
    else:
        print(f"[build_index] 임베딩 {embedder.model_id} on {embedder.device} (로드 {stages['embed_model_load_s']:.1f}s)")

    timings: dict[str, float] = {}
    store = IndexStore.from_corpus(works, reviews, embedder=embedder, timings=timings)
    stages.update(timings)
    print(
        f"[build_index] 문장 {store.n_excerpts()}개 ({timings['sentences_s']:.1f}s), 태그 {store.n_tags()}개 "
        f"({timings['tags_s']:.1f}s), BM25 {timings['bm25_s']:.1f}s, 임베딩 {timings['embed_s']:.1f}s"
    )

    t = time.perf_counter()
    check_mem = store.verify_offsets()
    stages["verify_memory_s"] = time.perf_counter() - t

    tag_counter: Counter[str] = Counter()
    pol_counter: Counter[str] = Counter()
    for _wid, row in store.iter_tag_rows():
        tag_counter[row["risk_code"]] += 1
        pol_counter[row["polarity"]] += 1
    works_with_reviews = sum(1 for w in store.works if store.reviews.get(w))

    manifest_extra = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "input": input_info,
        "counts": {
            "works": len(store.works),
            "reviews": sum(len(v) for v in store.reviews.values()),
            "reviews_dropped_unknown_work": len(reviews) - sum(len(v) for v in store.reviews.values()),
            "works_with_reviews": works_with_reviews,
            "works_without_reviews": len(store.works) - works_with_reviews,
            "excerpts": store.n_excerpts(),
            "tags": store.n_tags(),
            "tag_counts": dict(sorted(tag_counter.items())),
            "tag_polarity_counts": dict(sorted(pol_counter.items())),
            "tag_kinds": len(tag_counter),
        },
        "offset_check": {**check_mem, "rate": (check_mem["passed"] / check_mem["checked"]) if check_mem["checked"] else None},
        "backend": {
            "lexical": f"bm25-okapi(k1={store.bm25.k1},b={store.bm25.b})",
            "dense": None if embedder is None else embedder.model_id,
            "dense_dim": None if store.embeddings is None else int(store.embeddings.shape[1]),
            "embed_batch": ist.embed_batch,
            "embed_max_seq": ist.embed_max_seq,
            "fp16": bool(embedder is not None and embedder.device == "cuda"),
            "degraded": embedder is None,
            "degraded_reason": degraded_reason,
            **gpu_info(None if embedder is None else embedder.device),
        },
        "search_defaults": {"alpha": ist.search_alpha, "score_floor": ist.search_score_floor},
        "rule_tagger": {"generator": "rule", "module": "neumann.index.taxonomy"},
    }

    t = time.perf_counter()
    store.save(out, manifest_extra)
    stages["save_s"] = time.perf_counter() - t

    # 디스크에서 다시 읽어 전량 대조(저장 형식까지 포함한 검사)
    t = time.perf_counter()
    reloaded = IndexStore.load(out)
    check_disk = reloaded.verify_offsets()
    stages["reload_verify_s"] = time.perf_counter() - t

    stages = {k: round(v, 3) for k, v in stages.items()}
    total = round(time.perf_counter() - t_start, 3)
    manifest = reloaded.manifest
    manifest["offset_check_reloaded"] = {
        **check_disk,
        "rate": (check_disk["passed"] / check_disk["checked"]) if check_disk["checked"] else None,
    }
    manifest["stages"] = stages
    manifest["build_seconds"] = total
    (Path(out) / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[build_index] 오프셋 대조(메모리) {check_mem['passed']}/{check_mem['checked']}, (디스크) {check_disk['passed']}/{check_disk['checked']}")
    print(f"[build_index] 태그 종류 {len(tag_counter)}: {dict(sorted(tag_counter.items()))}, 극성 {dict(pol_counter)}")
    print(f"[build_index] 색인 {out} {manifest['index_bytes'] / 1e6:.2f}MB, 총 {total:.1f}s, 단계 {stages}")
    ok = check_mem["failed"] == 0 and check_disk["failed"] == 0 and check_disk["checked"] == store.n_excerpts()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
