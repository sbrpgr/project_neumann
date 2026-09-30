"""ResearchArcade 원본 parquet → AI for Science 코퍼스(E1-L0) 조립.

    python scripts/collect_researcharcade.py                  # 조립 → data/processed/
    python scripts/collect_researcharcade.py --check-sample 5 # 저장된 심사평과 parquet 원문 대조

경로: --raw-dir(기본 NEUMANN_RAW_DIR), --data-dir(기본 NEUMANN_DATA_DIR, 산출은 그 아래 processed/).
두 번 돌려도 JSONL 출력의 sha256은 같다(corpus_manifest.json의 outputs 참고).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from neumann.sources import researcharcade as ra  # noqa: E402
from neumann.sources.corpus import load_corpus  # noqa: E402


def check_sample(raw_dir: Path, processed: Path, n: int, seed: int) -> list[dict]:
    """무작위 n건: 저장된 심사평 텍스트가 parquet 원문의 칸들을 같은 순서로 글자 그대로 담는지 대조."""
    import pyarrow.parquet as pq

    corpus = load_corpus(processed)
    rng = random.Random(seed)
    sample = rng.sample(sorted(corpus.reviews, key=lambda r: r.review_id), n)
    wanted = {r.review_id.split(":", 1)[1]: r for r in sample}
    raw: dict[str, str] = {}
    for rel in ra.REVIEW_FILES:
        tab = pq.read_table(raw_dir / rel, columns=["review_openreview_id", "content"])
        ids = tab.column("review_openreview_id").to_pylist()
        for i, nid in enumerate(ids):
            if nid in wanted:
                raw[nid] = tab.column("content")[i].as_py()
    results = []
    for nid, rev in wanted.items():
        content = json.loads(raw[nid])
        names = ra.OFFICIAL_SECTIONS if rev.kind.value == "official_review" else ra.META_SECTIONS
        rebuilt, _ = ra.clean_text(ra.compose_sections(content, names))
        per_section = []
        for name in names:
            original = content.get(name)
            if original is None or not str(original).strip():
                continue
            body = str(original).strip()
            per_section.append(
                {
                    "section": name,
                    "raw_chars": len(body),
                    "raw_in_stored_verbatim": body in rev.text,
                }
            )
        results.append(
            {
                "review_id": rev.review_id,
                "kind": rev.kind.value,
                "url": rev.url,
                "stored_chars": len(rev.text),
                "stored_equals_rebuilt_from_parquet": rebuilt == rev.text,
                "provenance_hash_matches_parquet": ra.raw_hash(raw[nid]) == rev.provenance.content_sha256,
                "sections": per_section,
            }
        )
    return results


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    from neumann.config import get_settings

    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=settings.raw_dir)
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    parser.add_argument("--check-sample", type=int, default=0, metavar="N", help="조립 대신 무작위 N건 원문 대조")
    parser.add_argument("--seed", type=int, default=20260930)
    args = parser.parse_args()
    if args.raw_dir is None:
        parser.error("--raw-dir 또는 NEUMANN_RAW_DIR가 필요하다")
    processed = Path(args.data_dir) / "processed"

    if args.check_sample:
        results = check_sample(Path(args.raw_dir), processed, args.check_sample, args.seed)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        ok = all(r["stored_equals_rebuilt_from_parquet"] and r["provenance_hash_matches_parquet"] for r in results)
        print("대조:", "전부 일치" if ok else "불일치 있음")
        return 0 if ok else 1

    manifest = ra.collect(Path(args.raw_dir), processed)
    sel, link, dec = manifest["selection"], manifest["linking"], manifest["decisions"]
    print(f"출력: {processed}")
    print(f"편수 {sel['works']} (사전 집계 {sel['precount']['works']}), 분야별 {sel['by_field_ko']}")
    print(
        f"심사평 {link['official_reviews']} + 메타리뷰 {link['meta_reviews']}, 저자 답변 {link['author_responses']}, "
        f"결정 {link['decisions']}"
    )
    print(f"샤드 0·1에 심사평 없는 논문 {link['works_without_review_in_shards']} {link['works_without_review_by_venue']}")
    print(f"결정 분포 {dec['distribution']}, 거절 비율 {dec['reject_ratio']} (사전 집계 {dec['precount_reject_ratio']})")
    print(f"키워드 sha256 {manifest['keywords']['sha256']}")
    for name, info in manifest["outputs"].items():
        print(f"  {name}: {info['records']}건 sha256={info['sha256']}")
    print(f"소요 {manifest['elapsed_s']}초")
    return 0


if __name__ == "__main__":
    sys.exit(main())
