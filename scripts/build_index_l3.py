"""확대 코퍼스(E1-L3, `data/processed_l3/`) → 새 색인 폴더 `data/index_l3/`.

    python scripts/build_index_l3.py                   # 공유 data/processed_l3 → data/index_l3 (bge-m3)
    python scripts/build_index_l3.py --batch 8         # VRAM이 모자라면 배치를 줄인다(OOM이면 자동으로 반씩 줄여 재시도)
    python scripts/build_index_l3.py --processed DIR --out DIR --no-embed   # 테스트·개발용

빌드 자체는 `scripts/build_index.py`(E2-L0)를 그대로 부른다. 이 스크립트가 더하는 것:
1. **현재 색인(`{DATA_DIR}/index`, `NEUMANN_INDEX_DIR`)과 입력 폴더에는 절대 쓰지 않는다**(같은 경로면 거부).
2. 입력 해시를 E1-L3 `corpus_manifest.json`의 `outputs` sha256과 대조한다(다르면 실패).
3. manifest.json에 `corpus`(E1-L3 요약·해시 대조), 그룹별(AI4S·일반 ML) 논문·심사평·문장 수,
   전환 방법(`switch`)을 덧붙인다.

전환은 설정으로만 한다: `NEUMANN_INDEX_DIR=<data>/index_l3`. 코드 기본값(`{DATA_DIR}/index`)은 그대로다.
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

DEFAULT_PROCESSED = "processed_l3"
DEFAULT_OUT = "index_l3"
GENERAL_ML = "general_ml"


def _load_build_index():
    spec = importlib.util.spec_from_file_location("build_index", ROOT / "scripts" / "build_index.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))


def protected_dirs() -> list[Path]:
    """덮으면 안 되는 색인 폴더: 코드 기본값 `{DATA_DIR}/index`와 지금 설정이 가리키는 색인."""
    dirs = [get_settings().data_dir / "index"]
    ist_dir = get_index_settings().index_dir
    if ist_dir is not None:
        dirs.append(Path(ist_dir))
    return dirs


def check_out_dir(out: Path, processed: Path, protect: list[Path]) -> str | None:
    """쓰면 안 되는 출력 경로면 사유를, 괜찮으면 None."""
    for d in protect:
        if _same(out, d):
            return f"출력 폴더 {out}는 현재 색인({d})이다. 확대 색인은 새 폴더에 만든다(--out)"
    if _same(out, processed):
        return f"출력 폴더 {out}가 입력 코퍼스 폴더와 같다"
    return None


def corpus_summary(processed: Path, input_files: dict[str, str]) -> dict[str, Any]:
    """E1-L3 corpus_manifest.json 요약 + 색인이 읽은 입력 해시와 대조."""
    mpath = processed / "corpus_manifest.json"
    if not mpath.is_file():
        return {"manifest": None, "sha256_match": None, "note": "corpus_manifest.json 없음(해시 대조 못 함)"}
    cm = json.loads(mpath.read_text(encoding="utf-8"))
    outputs = cm.get("outputs") or {}
    per_file = {}
    for name, digest in sorted(input_files.items()):
        want = (outputs.get(name) or {}).get("sha256")
        per_file[name] = {"index_input": digest, "corpus_manifest": want, "match": want == digest}
    sel = cm.get("selection") or {}
    return {
        "manifest": str(mpath),
        "task": cm.get("task"),
        "generated_at": cm.get("generated_at"),
        "generator": cm.get("generator"),
        "selection": {k: sel.get(k) for k in ("works", "by_group", "by_field", "by_venue") if k in sel},
        "sha256_match": bool(per_file) and all(v["match"] for v in per_file.values()),
        "files": per_file,
    }


def group_of(fields: list[str] | tuple[str, ...]) -> str:
    return GENERAL_ML if GENERAL_ML in (fields or ()) else "ai4science"


def group_counts(index_dir: Path) -> dict[str, dict[str, int]]:
    """색인 안의 그룹별 논문·심사평·문장 수(works.fields의 general_ml 여부)."""
    from neumann.index.store import IndexStore

    st = IndexStore.load(index_dir)
    out: dict[str, Counter[str]] = {}
    for wid, w in st.works.items():
        c = out.setdefault(group_of(w.fields), Counter())
        c["works"] += 1
        c["reviews"] += len(st.reviews.get(wid, []))
        c["works_with_reviews"] += 1 if st.reviews.get(wid) else 0
        c["excerpts"] += len(st._excerpt_rows.get(wid, []))  # 행 수만 센다(Excerpt 객체를 만들지 않는다)
    return {g: dict(sorted(c.items())) for g, c in sorted(out.items())}


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
    """프로세스 캐시에 이미 올라간 임베더(get_embedder는 같은 객체를 돌려준다)의 배치도 줄인다."""
    try:
        from neumann.index.embed import get_embedder

        emb = get_embedder()
        if hasattr(emb, "batch_size"):
            emb.batch_size = batch
    except Exception:  # pragma: no cover
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--processed", type=Path, default=None, help=f"확대 코퍼스 폴더(기본 {{DATA_DIR}}/{DEFAULT_PROCESSED})")
    ap.add_argument("--out", type=Path, default=None, help=f"새 색인 폴더(기본 {{DATA_DIR}}/{DEFAULT_OUT})")
    ap.add_argument("--source", choices=["processed", "jsonl"], default="processed",
                    help="processed: E1 load_corpus(기본) · jsonl: works/reviews.jsonl 직접")
    ap.add_argument("--batch", type=int, default=None, help="임베딩 배치(기본 NEUMANN_EMBED_BATCH 또는 16)")
    ap.add_argument("--no-embed", action="store_true", help="임베딩 없이(어휘 검색만, 강등 표시)")
    args = ap.parse_args(argv)

    data_dir = get_settings().data_dir
    processed = args.processed or data_dir / DEFAULT_PROCESSED
    out = args.out or data_dir / DEFAULT_OUT
    reason = check_out_dir(out, processed, protected_dirs())
    if reason:
        print(f"[build_index_l3] 거부: {reason}")
        return 2
    if not (processed / "works.jsonl").is_file():
        print(f"[build_index_l3] 입력이 없다: {processed / 'works.jsonl'}")
        return 2

    build = _load_build_index()
    batch = args.batch
    while True:
        if batch is not None:
            os.environ["NEUMANN_EMBED_BATCH"] = str(batch)
            get_index_settings.cache_clear()
        bargs = ["--source", args.source, "--processed", str(processed), "--out", str(out)]
        if args.no_embed:
            bargs.append("--no-embed")
        print(f"[build_index_l3] {processed} → {out} (배치 {get_index_settings().embed_batch})")
        try:
            rc = build.main(bargs)
            break
        except Exception as exc:  # CUDA OOM이면 배치를 반으로 줄여 한 번 더
            cur = get_index_settings().embed_batch
            if not _is_oom(exc) or cur <= 1:
                raise
            batch = max(1, cur // 2)
            print(f"[build_index_l3] GPU 메모리 부족(배치 {cur}) → 배치 {batch}로 다시")
            _release_gpu()
            _set_cached_embedder_batch(batch)

    mpath = out / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    corpus = corpus_summary(processed, manifest.get("input", {}).get("files", {}))
    manifest["corpus"] = corpus
    manifest["groups"] = group_counts(out)
    manifest["l3"] = {
        "task": "E2-L3",
        "builder_script": "scripts/build_index_l3.py",
        "index_dir": str(out),
        "switch": f"NEUMANN_INDEX_DIR={out}",
        "note": "현재 색인(data/index)은 건드리지 않는다. 전환은 NEUMANN_INDEX_DIR 설정으로만",
    }
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[build_index_l3] 그룹별 {manifest['groups']}")
    print(f"[build_index_l3] E1-L3 manifest 해시 대조: {corpus.get('sha256_match')}")
    print(f"[build_index_l3] 전환: {manifest['l3']['switch']}")
    if corpus.get("sha256_match") is False:
        print("[build_index_l3] 실패: 색인 입력 해시가 E1-L3 corpus_manifest와 다르다")
        return 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
