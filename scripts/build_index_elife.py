"""ResearchArcade(E1-L0) + eLife(E1-L1b) 코퍼스 → 새 색인 폴더 `data/index_elife/`.

    python scripts/build_index_elife.py                         # 공유 data/processed → data/index_elife (bge-m3)
    python scripts/build_index_elife.py --batch 8               # VRAM이 모자라면(OOM이면 자동으로 반씩 줄여 재시도)
    python scripts/build_index_elife.py --include researcharcade,elife,europepmc --out DIR
    python scripts/build_index_elife.py --processed DIR --out DIR --no-embed   # 테스트·개발용

빌드 자체는 `scripts/build_index.py`(E2-L0)를 고치지 않고 그대로 부른다. 입력만 E1 `load_corpus(include=...)`로
바꿔 끼운다. 이 스크립트가 더하는 것:
1. **현재 색인(`{DATA_DIR}/index`)·확대 색인(`{DATA_DIR}/index_l3`)·`NEUMANN_INDEX_DIR`·입력 폴더에는 쓰지 않는다**(거부, rc 2).
2. 빌드 전에 소스별 전량 검사(`audit_sources`: 출처 URL·원문 해시·신원 키)와 eLife 결정 매핑 검사를 통과해야 한다.
3. 색인 입력 해시를 소스별 manifest(`corpus_manifest.json`·`elife_manifest.json`)의 `outputs` sha256과 대조한다.
4. manifest.json에 `elife`(소스별 논문·심사평·문장 수, 검사 결과, 해시 대조, 전환 방법)를 덧붙인다.

전환은 설정으로만 한다: `NEUMANN_INDEX_DIR=<data>/index_elife`. 코드 기본값(`{DATA_DIR}/index`)은 그대로다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from neumann.config import get_settings  # noqa: E402
from neumann.index.settings import get_index_settings  # noqa: E402
from neumann.sources.corpus import (  # noqa: E402
    ELIFE_SOURCES,
    SOURCE_MANIFEST_FILES,
    audit_sources,
    check_elife_decisions,
    load_corpus,
    source_files,
    source_of_work_id,
)

DEFAULT_OUT = "index_elife"
TAG = "[build_index_elife]"


def _load_build_index():
    spec = importlib.util.spec_from_file_location("build_index", ROOT / "scripts" / "build_index.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))


def protected_dirs() -> list[Path]:
    """덮으면 안 되는 색인 폴더: 기본 `{DATA_DIR}/index`, 확대 `{DATA_DIR}/index_l3`, 지금 설정이 가리키는 색인."""
    data = get_settings().data_dir
    dirs = [data / "index", data / "index_l3"]
    ist_dir = get_index_settings().index_dir
    if ist_dir is not None:
        dirs.append(Path(ist_dir))
    return dirs


def check_out_dir(out: Path, processed: Path, protect: list[Path]) -> str | None:
    """쓰면 안 되는 출력 경로면 사유를, 괜찮으면 None."""
    for d in protect:
        if _same(out, d):
            return f"출력 폴더 {out}는 보호 색인({d})이다. eLife 포함 색인은 새 폴더에 만든다(--out)"
    if _same(out, processed) or _same(out, processed.parent / "processed"):
        return f"출력 폴더 {out}가 입력 코퍼스 폴더다"
    return None


def parse_include(text: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in text.split(",") if s.strip())


def make_load_source(build: Any, include: tuple[str, ...]):
    """build_index.load_source 대체: E1 load_corpus(include=...)로 읽고, 색인이 읽는 파일(소스별 works·reviews)을 해시한다."""

    def load_source(source: str, processed_dir: Path):
        corpus = load_corpus(processed_dir, include=include)
        works, reviews = build._parts(corpus)
        files = []
        for src in include:
            f = source_files(processed_dir, src)
            files += [f["works"], f["reviews"]]
        info = {"source": "processed", "include": list(include), "dir": str(processed_dir),
                **build.input_digest(files, processed_dir)}
        return works, reviews, info

    return load_source


def manifest_hash_check(processed: Path, include: tuple[str, ...], input_files: dict[str, str]) -> dict[str, Any]:
    """색인 입력 sha256을 소스별 manifest의 outputs sha256과 대조한다."""
    per_file: dict[str, Any] = {}
    for src in include:
        mpath = processed / SOURCE_MANIFEST_FILES[src]
        outputs = {}
        if mpath.is_file():
            outputs = json.loads(mpath.read_text(encoding="utf-8")).get("outputs") or {}
        for key in ("works", "reviews"):
            name = source_files(processed, src)[key].name
            want = (outputs.get(name) or {}).get("sha256")
            got = input_files.get(name)
            per_file[name] = {"source": src, "index_input": got, "source_manifest": want,
                              "match": None if want is None else want == got}
    known = [v["match"] for v in per_file.values() if v["match"] is not None]
    return {"sha256_match": (all(known) if known else None), "files": per_file,
            "unchecked": sorted(k for k, v in per_file.items() if v["match"] is None)}


def source_counts(index_dir: Path) -> dict[str, dict[str, int]]:
    """색인 안의 소스별 논문·심사평·문장 수와 문장 오프셋 독립 재대조(원문[start:end] == text)."""
    from neumann.index.store import IndexStore

    st = IndexStore.load(index_dir)
    out: dict[str, Counter[str]] = {}
    for wid in st.works:
        c = out.setdefault(source_of_work_id(wid) or "other", Counter())
        revs = st.reviews.get(wid, [])
        c["works"] += 1
        c["works_with_reviews"] += 1 if revs else 0
        c["reviews"] += len(revs)
        text = {r.review_id: r.text for r in revs}
        for row in st._excerpt_rows.get(wid, []):
            c["excerpts"] += 1
            src = text.get(row["source_id"])
            if src is not None and src[row["start"]:row["end"]] == row["text"]:
                c["excerpt_offsets_ok"] += 1
    return {s: dict(sorted(c.items())) for s, c in sorted(out.items())}


def _is_oom(exc: BaseException) -> bool:
    return "out of memory" in str(exc).lower() or type(exc).__name__ == "OutOfMemoryError"


def _release_gpu() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # pragma: no cover
        pass


def _set_cached_embedder_batch(batch: int) -> None:
    try:
        from neumann.index.embed import get_embedder

        emb = get_embedder()
        if hasattr(emb, "batch_size"):
            emb.batch_size = batch
    except Exception:  # pragma: no cover
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--processed", type=Path, default=None, help="코퍼스 폴더(기본 {DATA_DIR}/processed)")
    ap.add_argument("--out", type=Path, default=None, help=f"새 색인 폴더(기본 {{DATA_DIR}}/{DEFAULT_OUT})")
    ap.add_argument("--include", default=",".join(ELIFE_SOURCES),
                    help="합칠 소스(쉼표). 기본 researcharcade,elife. 가능: researcharcade, elife, europepmc")
    ap.add_argument("--batch", type=int, default=None, help="임베딩 배치(기본 NEUMANN_EMBED_BATCH 또는 16)")
    ap.add_argument("--no-embed", action="store_true", help="임베딩 없이(어휘 검색만, 강등 표시)")
    args = ap.parse_args(argv)

    data_dir = get_settings().data_dir
    processed = args.processed or data_dir / "processed"
    out = args.out or data_dir / DEFAULT_OUT
    include = parse_include(args.include)
    reason = check_out_dir(out, processed, protected_dirs())
    if reason:
        print(f"{TAG} 거부: {reason}")
        return 2

    # 빌드 전 전량 검사: 출처 URL·원문 해시·신원 키, eLife 결정 매핑
    try:
        audit = audit_sources(processed, include=include)
        decisions = check_elife_decisions(load_corpus(processed, include=include)) if "elife" in include else None
    except (ValueError, FileNotFoundError) as exc:
        print(f"{TAG} 실패: 입력 검사 {exc}")
        return 1
    print(f"{TAG} 입력 검사 통과: 레코드 {audit['records_total']}, 출처 URL {audit['source_url_ratio']}, "
          f"원문 해시 {audit['content_sha256_ratio']}, 신원 키 {audit['identity_key_records']}, eLife 결정 {decisions}")

    build = _load_build_index()
    build.load_source = make_load_source(build, include)
    batch = args.batch
    while True:
        if batch is not None:
            os.environ["NEUMANN_EMBED_BATCH"] = str(batch)
            get_index_settings.cache_clear()
        bargs = ["--source", "processed", "--processed", str(processed), "--out", str(out)]
        if args.no_embed:
            bargs.append("--no-embed")
        print(f"{TAG} {processed} {list(include)} → {out} (배치 {get_index_settings().embed_batch})")
        try:
            rc = build.main(bargs)
            break
        except Exception as exc:  # CUDA OOM이면 배치를 반으로 줄여 다시
            cur = get_index_settings().embed_batch
            if not _is_oom(exc) or cur <= 1:
                raise
            batch = max(1, cur // 2)
            print(f"{TAG} GPU 메모리 부족(배치 {cur}) → 배치 {batch}로 다시")
            _release_gpu()
            _set_cached_embedder_batch(batch)

    mpath = out / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    hashes = manifest_hash_check(processed, include, manifest.get("input", {}).get("files", {}))
    by_source = source_counts(out)
    n_ex = sum(v.get("excerpts", 0) for v in by_source.values())
    n_ok = sum(v.get("excerpt_offsets_ok", 0) for v in by_source.values())
    manifest["elife"] = {
        "task": "E1-L1c",
        "builder_script": "scripts/build_index_elife.py",
        "include": list(include),
        "input_audit": audit,
        "elife_decisions": decisions,
        "corpus_hash_check": hashes,
        "sources": by_source,
        "offset_recheck": {"checked": n_ex, "passed": n_ok, "rate": (n_ok / n_ex) if n_ex else None},
        "index_dir": str(out),
        "switch": f"NEUMANN_INDEX_DIR={out}",
        "note": "현재 색인(data/index)·확대 색인(data/index_l3)은 건드리지 않는다. 전환은 NEUMANN_INDEX_DIR 설정으로만",
    }
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{TAG} 소스별 {by_source}")
    print(f"{TAG} 소스별 오프셋 재대조 {n_ok}/{n_ex}")
    print(f"{TAG} 소스 manifest 해시 대조: {hashes['sha256_match']} (대조 못 한 파일 {hashes['unchecked']})")
    print(f"{TAG} 전환: {manifest['elife']['switch']}")
    if hashes["sha256_match"] is False:
        print(f"{TAG} 실패: 색인 입력 해시가 소스 manifest와 다르다")
        return 1
    if n_ok != n_ex:
        return 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
