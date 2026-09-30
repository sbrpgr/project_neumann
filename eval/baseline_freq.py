"""빈도 기준선(참조선): 심사평을 읽지 않고 가장 흔한 Tier-1 코드 3개를 항상 낸다.

사전 고정(결과를 보기 전에 정함):
- 빈도는 튜닝셋(dev, 1인 라벨 심사평)에서만 센다. 골드는 채점에만 쓴다(04_평가_명세 §0.6).
- 빈도 = 그 코드를 가진 dev 심사평 수. 상위 K=3(§0.2 "가장 흔한 위험 3개", §2.1 "최빈 3코드 고정 출력").
- 동률은 코드 이름순.
- 대상 파일에서는 review_id만 읽는다(라벨을 보지 않는다).

실행:
    python -m eval.baseline_freq --dev data/eval/disapere_dev.jsonl \
        --target data/eval/disapere_gold.jsonl --out data/eval/pred_baseline_freq.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

TIER1 = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9")
K = 3


def code_frequency(dev_records: list[dict]) -> Counter:
    cnt: Counter = Counter()
    for r in dev_records:
        cnt.update(c for c in set(r["risk_codes"]) if c in TIER1)
    return cnt


def top_k(freq: Counter, k: int = K) -> list[str]:
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return sorted((c for c, _ in ranked[:k]), key=lambda c: (len(c), c))


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def predictions(target_ids: list[str], codes: list[str]) -> list[dict]:
    return [{"review_id": rid, "risk_codes": list(codes), "generator": "baseline", "system": "freq_top3"} for rid in target_ids]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="빈도 기준선 예측(안 읽음, dev 최빈 3코드)")
    ap.add_argument("--dev", type=Path, required=True, help="튜닝셋 JSONL(빈도를 셀 곳)")
    ap.add_argument("--target", type=Path, required=True, help="예측할 심사평 JSONL(review_id만 읽음)")
    ap.add_argument("--out", type=Path, required=True, help="예측 JSONL")
    ap.add_argument("--k", type=int, default=K, help=f"코드 수(기본 {K}, 사전 고정)")
    args = ap.parse_args(argv)

    dev = _read_jsonl(args.dev)
    freq = code_frequency(dev)
    codes = top_k(freq, args.k)
    target_ids = [r["review_id"] for r in _read_jsonl(args.target)]
    rows = predictions(target_ids, codes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    ranked = ", ".join(f"{c}:{n}" for c, n in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])))
    print(f"dev {len(dev)}건 빈도(심사평 수): {ranked}")
    print(f"고정 출력 top-{args.k}: {codes} → {len(rows)}건 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
