"""DISAPERE 사람 라벨 → 리뷰 단위 Tier-1 골드(04_평가_명세 §3.1, 사전 고정).

규칙(결과를 보기 전에 고정. 바꾸지 않는다):
- 매핑: soundness-correctness→R1, substance→R2, replicability→R5,
  originality·meaningful-comparison→R6(합집합), motivation-impact→R7.
  clarity(R0/R5c 표시 전용)와 arg_other·none은 Tier-1 채점에서 뺀다.
- 채택 필터: `polarity == "pol_negative"`인 문장만 후보.
- 주석자별 Tier-1 집합 = 부정 문장들의 매핑 코드 합집합.
- 합의: n명 중 `n//2 + 1`명 이상이 준 코드만 골드. 공집합(no_risk)도 버리지 않는다.
- 골드 = 2명 이상이 라벨한 심사평 전부(148건). 1명만 라벨한 심사평은 튜닝용(dev, 약 358건).
  골드는 채점에만 쓴다.

실행:
    python -m eval.disapere_gold [--zip DISAPERE.zip] [--out-dir data/eval]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from neumann.sources import disapere

TIER1 = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9")
ASPECT_TO_TIER1: dict[str, str] = {
    "asp_soundness-correctness": "R1",
    "asp_substance": "R2",
    "asp_replicability": "R5",
    "asp_originality": "R6",
    "asp_meaningful-comparison": "R6",
    "asp_motivation-impact": "R7",
}
# DISAPERE에 대응 라벨이 없는 Tier-1. 골드 support=0 → 채점기가 규칙대로 자동 제외한다.
UNCOVERED = ("R3", "R4", "R8", "R9")
EXCLUDED_ASPECTS = ("asp_clarity", "arg_other", "none")
NEGATIVE = "pol_negative"

GOLD_FILE = "disapere_gold.jsonl"
DEV_FILE = "disapere_dev.jsonl"
MANIFEST_FILE = "disapere_manifest.json"


def sort_codes(codes) -> list[str]:
    return sorted(set(codes), key=lambda c: (len(c), c))


def annotator_codes(annotation: disapere.Annotation) -> frozenset[str]:
    """한 주석자의 리뷰 단위 Tier-1 집합: 부정 극성 문장의 매핑 코드 합집합."""
    return frozenset(
        ASPECT_TO_TIER1[s.aspect]
        for s in annotation.labels
        if s.polarity == NEGATIVE and s.aspect in ASPECT_TO_TIER1
    )


def majority_threshold(n: int) -> int:
    if n < 1:
        raise ValueError("주석자가 없다")
    return n // 2 + 1


def majority_gold(code_sets: list[frozenset[str]]) -> dict:
    """과반(n//2+1) 이상이 준 코드만 골드. 전원 일치가 아닌 코드는 disagreement에 남긴다."""
    n = len(code_sets)
    k = majority_threshold(n)
    votes = Counter(c for s in code_sets for c in s)
    gold = sort_codes(c for c, v in votes.items() if v >= k)
    disagreement = sort_codes(c for c, v in votes.items() if v < n)
    return {
        "risk_codes": gold,
        "threshold": k,
        "votes": {c: votes[c] for c in sort_codes(votes)},
        "disagreement_codes": disagreement,
        # 사람 조정(adjudication)은 없다. 불일치는 임계값 계산으로만 정했다.
        "resolution": "agreed" if not disagreement else "majority_vote",
    }


def _source(review: disapere.Review, info: disapere.ZipInfo) -> dict:
    return {
        **info.as_dict(),
        "review_url": review.source_url,
        "members": [{"path": a.member, "sha256": a.member_sha256} for a in review.annotations],
    }


def gold_record(review: disapere.Review, info: disapere.ZipInfo) -> dict:
    sets = [annotator_codes(a) for a in review.annotations]
    maj = majority_gold(sets)
    return {
        "review_id": review.review_id,
        "role": "gold",
        "risk_codes": maj["risk_codes"],
        "no_risk": not maj["risk_codes"],
        "n_annotators": review.n_annotators,
        "threshold": maj["threshold"],
        "annotator_codes": [sort_codes(s) for s in sets],
        "votes": maj["votes"],
        "disagreement_codes": maj["disagreement_codes"],
        "resolution": maj["resolution"],
        "forum_id": review.forum_id,
        "conference": review.conference,
        "disapere_split": review.split,
        "sentences": list(review.sentences),
        "text": review.text,
        "text_sha256": review.text_sha256,
        "source": _source(review, info),
    }


def dev_record(review: disapere.Review, info: disapere.ZipInfo) -> dict:
    """1인 라벨 심사평(튜닝용). 문장 라벨도 같이 둔다."""
    (ann,) = review.annotations
    codes = sort_codes(annotator_codes(ann))
    return {
        "review_id": review.review_id,
        "role": "dev",
        "risk_codes": codes,
        "no_risk": not codes,
        "n_annotators": 1,
        "forum_id": review.forum_id,
        "conference": review.conference,
        "disapere_split": review.split,
        "sentences": list(review.sentences),
        "sentence_labels": [
            {
                "aspect": s.aspect,
                "polarity": s.polarity,
                "tier1": ASPECT_TO_TIER1.get(s.aspect) if s.polarity == NEGATIVE else None,
            }
            for s in ann.labels
        ],
        "text": review.text,
        "text_sha256": review.text_sha256,
        "source": _source(review, info),
    }


def build(reviews: list[disapere.Review], info: disapere.ZipInfo) -> tuple[list[dict], list[dict]]:
    gold, dev = [], []
    for r in reviews:
        if r.n_annotators >= 2:
            gold.append(gold_record(r, info))
        else:
            dev.append(dev_record(r, info))
    return gold, dev


def _jsonl_bytes(records: list[dict]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records).encode("utf-8")


def _support(records: list[dict]) -> dict[str, int]:
    cnt = Counter(c for r in records for c in r["risk_codes"])
    return {c: cnt.get(c, 0) for c in TIER1}


def write_outputs(gold: list[dict], dev: list[dict], info: disapere.ZipInfo, out_dir: Path, n_members: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, records in ((GOLD_FILE, gold), (DEV_FILE, dev)):
        data = _jsonl_bytes(records)
        (out_dir / name).write_bytes(data)
        files[name] = {"n": len(records), "sha256": disapere.sha256_bytes(data), "bytes": len(data)}
    manifest = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generator": "eval.disapere_gold",
        "source": info.as_dict(),
        "rules": {
            "spec": "04_평가_명세 §0.6·§2.1·§3.1 (사전 고정)",
            "aspect_to_tier1": ASPECT_TO_TIER1,
            "excluded_aspects": list(EXCLUDED_ASPECTS),
            "polarity_filter": NEGATIVE,
            "majority_threshold": "n//2+1",
            "gold": "주석자 2명 이상인 심사평 전부(채점 전용)",
            "dev": "주석자 1명인 심사평(튜닝 전용)",
            "uncovered_tier1": list(UNCOVERED),
            "unit": "review (멀티라벨 Tier-1 집합, 공집합 = no_risk 유지)",
        },
        "counts": {
            "annotation_files": n_members,
            "reviews": len(gold) + len(dev),
            "gold": len(gold),
            "dev": len(dev),
            "gold_by_n_annotators": dict(sorted(Counter(r["n_annotators"] for r in gold).items())),
            "gold_resolution": dict(sorted(Counter(r["resolution"] for r in gold).items())),
            "gold_no_risk": sum(1 for r in gold if r["no_risk"]),
            "dev_no_risk": sum(1 for r in dev if r["no_risk"]),
        },
        "support": {"gold": _support(gold), "dev": _support(dev)},
        "files": files,
        "license_note": "CC BY-NC 4.0. 원본·가공본은 저장소에 커밋하지 않는다",
    }
    (out_dir / MANIFEST_FILE).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def default_out_dir() -> Path:
    data = os.environ.get("NEUMANN_DATA_DIR")
    if not data:
        raise SystemExit("NEUMANN_DATA_DIR가 없다. --out-dir를 준다")
    return Path(data) / "eval"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="DISAPERE 과반 합의 골드·튜닝셋 만들기(§3.1)")
    ap.add_argument("--zip", type=Path, default=None, help="DISAPERE.zip (기본: $NEUMANN_RAW_DIR/data/disapere/DISAPERE.zip)")
    ap.add_argument("--out-dir", type=Path, default=None, help="출력 폴더 (기본: $NEUMANN_DATA_DIR/eval)")
    args = ap.parse_args(argv)

    zip_path = args.zip or disapere.default_zip_path()
    out_dir = args.out_dir or default_out_dir()
    info = disapere.zip_info(zip_path)
    reviews = disapere.load_reviews(zip_path)
    gold, dev = build(reviews, info)
    manifest = write_outputs(gold, dev, info, out_dir, disapere.count_members(zip_path))

    c = manifest["counts"]
    print(f"원본: {zip_path} (sha256 {info.sha256[:12]}…, 주석 파일 {c['annotation_files']}개, 심사평 {c['reviews']}건)")
    print(f"골드 {c['gold']}건 (주석자 수별 {c['gold_by_n_annotators']}, 해결 {c['gold_resolution']}, no_risk {c['gold_no_risk']})")
    print(f"튜닝(dev) {c['dev']}건 (no_risk {c['dev_no_risk']})")
    for name, f in manifest["files"].items():
        print(f"  {out_dir / name}: n={f['n']} sha256={f['sha256']}")
    print(f"  {out_dir / MANIFEST_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
