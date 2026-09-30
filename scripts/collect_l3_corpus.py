"""E1-L3: 샤드 6개 전부로 AI for Science + 일반 ML 확대 코퍼스를 `data/processed_l3/`에 조립한다.

    python scripts/collect_l3_corpus.py                      # 조립(일반 ML 1,000편, 시드 20260930)
    python scripts/collect_l3_corpus.py --general-ml 1500    # 일반 ML 편수 바꾸기
    python scripts/collect_l3_corpus.py --audit              # 전량 검사(출처 URL·신원 키·편수·분야 태그)
    python scripts/collect_l3_corpus.py --compare            # 현재 코퍼스 data/processed와 비교(읽기만)
    python scripts/collect_l3_corpus.py --check-sample 10    # 저장된 심사평과 parquet 원문 대조(절반은 샤드 2~5)

입력: 키트 공개자료(papers, 샤드 0·1, 읽기만) + `data/raw/researcharcade/`(샤드 2~5, collect_l3_shards.py가 받음).
출력: `data/processed_l3/`만 쓴다. `data/processed/`와 `data/index/`는 건드리지 않는다.
E1-L0 모듈(neumann.sources.researcharcade·corpus)이 필요하다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from neumann.sources import corpus_l3 as l3  # noqa: E402


def _print_summary(m: dict) -> None:
    sel, cov, link, dec = m["selection"], m["coverage"], m["linking"], m["decisions"]
    print(f"편수 {sel['works']} (기준 {sel['min_total_works']} 이상), 그룹 {sel['by_group']}")
    print(f"분야 {sel['by_field_ko']}, venue {sel['by_venue']}")
    g = sel["general_ml_sampling"]
    print(f"일반 ML 표본 {g['selected']}/{g['pool']}(후보) 시드 {g['seed']}, 후보 제외 {g['pool_excluded']}")
    for when in ("before", "after"):
        c = cov[when]
        print(
            f"커버리지 {when} 샤드 {c['shards']}: 모집단 {c['population']['with_official_review']}/{c['population']['papers']}"
            f"={c['population']['ratio']}, AI4S {c['ai4science']['with_official_review']}/{c['ai4science']['papers']}"
            f"={c['ai4science']['ratio']}, 일반 ML 모집단 {c['general_ml_population']['ratio']}"
        )
    print(
        f"심사평 {link['official_reviews']} + 메타리뷰 {link['meta_reviews']} (그룹별 {link['reviews_by_group']}), "
        f"저자 답변 {link['author_responses']}, 결정 {link['decisions']}(노트 {link['decision_notes_found']})"
    )
    print(f"심사평 없는 논문 {link['works_without_review_in_shards']} {link['works_without_review_by_group']}")
    print(f"결정 {dec['distribution']}, 거절 비율 {dec['reject_ratio']} 그룹별 {dec['reject_ratio_by_group']}")
    print(f"키워드 sha256 {m['keywords']['sha256']}")
    for name, info in m["outputs"].items():
        print(f"  {name}: {info['records']}건 sha256={info['sha256']}")
    print(f"소요 {m['elapsed_s']}초")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    from neumann.config import get_settings

    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=settings.raw_dir, help="키트 공개자료(기본 NEUMANN_RAW_DIR)")
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir, help="공유 데이터 폴더(기본 NEUMANN_DATA_DIR)")
    parser.add_argument("--general-ml", type=int, default=l3.DEFAULT_GENERAL_ML_N, metavar="N")
    parser.add_argument("--seed", type=int, default=l3.DEFAULT_SEED)
    parser.add_argument("--audit", action="store_true", help="조립 대신 전량 검사")
    parser.add_argument("--compare", action="store_true", help="조립 대신 data/processed와 비교")
    parser.add_argument("--check-sample", type=int, default=0, metavar="N", help="조립 대신 무작위 N건 원문 대조")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    raw_l3 = data_dir / l3.RAW_SUBDIR
    out = data_dir / l3.L3_SUBDIR

    if args.audit:
        print(json.dumps(l3.audit_l3(out), ensure_ascii=False, indent=2))
        return 0
    if args.compare:
        print(json.dumps(l3.compare_with_processed(out, data_dir / "processed"), ensure_ascii=False, indent=2))
        return 0
    if args.raw_dir is None:
        parser.error("--raw-dir 또는 NEUMANN_RAW_DIR가 필요하다")
    if args.check_sample:
        shards = l3.resolve_shards(Path(args.raw_dir), raw_l3)
        results = l3.check_sample(out, shards, args.check_sample, args.seed)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        ok = all(r["stored_equals_rebuilt_from_parquet"] and r["provenance_hash_matches_parquet"] for r in results)
        verbatim = sum(r["all_sections_verbatim"] for r in results)
        print(f"원문 칸이 글자 그대로 있는 심사평 {verbatim}/{len(results)}(신원 가림이 있으면 줄 수 있다)")
        print("대조:", "전부 일치" if ok else "불일치 있음")
        return 0 if ok else 1

    manifest = l3.collect_l3(Path(args.raw_dir), raw_l3, out, general_ml_n=args.general_ml, seed=args.seed)
    print(f"출력: {out}")
    _print_summary(manifest)
    return 0 if manifest["selection"]["works"] >= l3.MIN_TOTAL_WORKS else 1


if __name__ == "__main__":
    sys.exit(main())
