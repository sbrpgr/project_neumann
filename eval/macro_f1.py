"""리뷰 단위 멀티라벨 Tier-1 Macro-F1 채점기(04_평가_명세 §2.1, 사전 고정).

정의:
- 단위: 심사평 1건. 정답 y·예측 ŷ 모두 Tier-1 코드(R1~R9) 부분집합. 공집합(no_risk) 허용.
- 클래스 c마다 TP/FP/FN을 세고 P·R·F1을 낸다. 분모가 0이면 값은 0.
- 채점 대상 C* = 골드 support(TP+FN) ≥ 1인 클래스. Macro-F1 = C* 평균 F1.
  support 0 클래스(DISAPERE는 R3·R4·R8·R9)는 자동 제외하고 제외 목록을 출력에 적는다.
  support가 적다고 사후에 빼지 않는다. no_risk 단위도 버리지 않는다.
- Micro-F1 = F1(ΣTP, ΣFP, ΣFN), R1~R9 전체 합(제외 클래스의 FP도 들어간다). Macro와 항상 같이 낸다.
- 95% 구간: 단위(심사평) 재표집 부트스트랩 2,000회, 시드 20260930 고정, percentile.
  재표집마다 C*를 다시 정한다(규칙 ①을 재표집에도 그대로 적용).

예측 JSONL(한 줄 = 심사평 1건):
    {"review_id": "<DISAPERE review_id>", "risk_codes": ["R1", "R2"], "generator": "astra"}
- generator: rule | astra | mock | baseline
- risk_codes: R0~R9. R0(서술·표현, 비위험)은 채점에서 빼고 개수만 센다. 그 밖의 값은 오류.
- 골드에 있는데 예측이 없는 심사평은 빈 예측으로 채점한다(missing으로 보고).
- 골드에 없는 review_id(예: dev 예측)는 채점하지 않고 개수만 보고한다.

실행:
    python -m eval.macro_f1 --pred <예측.jsonl> --gold <골드.jsonl> --out <결과.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

TIER1 = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9")
NON_SCORED_CODES = ("R0",)
GENERATORS = ("rule", "astra", "mock", "baseline")
N_BOOT = 2000
SEED = 20260930
ALPHA = 0.05

# 참조선(04_평가_명세 §1.2): DISAPERE 인간 상한, 리뷰 단위·합의 골드. 우리 시스템 성능이 아니다.
REFERENCE_LINES = {
    "human_upper_bound_consensus_gold": {
        "macro_f1": 0.725,
        "ci95": [0.669, 0.772],
        "note": "DISAPERE 4인 라벨 29리뷰, 1명 대 나머지 3명 다수결(leave-one-out). 과제 난이도 천장, 04_평가_명세 §1.2",
    }
}


class PredictionError(ValueError):
    """예측 파일 형식 오류."""


@dataclass(frozen=True)
class Prediction:
    review_id: str
    codes: frozenset[str]
    generator: str
    dropped_r0: int = 0


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def multilabel_scores(
    gold_sets: Sequence[frozenset[str] | set[str]],
    pred_sets: Sequence[frozenset[str] | set[str]],
    classes: Sequence[str] = TIER1,
) -> dict:
    """정렬된 단위 목록(gold_sets[i] ↔ pred_sets[i])에서 클래스별 P/R/F1, Macro·Micro-F1."""
    if len(gold_sets) != len(pred_sets):
        raise ValueError("골드와 예측의 단위 수가 다르다")
    cnt = {c: [0, 0, 0] for c in classes}  # tp, fp, fn
    for g, p in zip(gold_sets, pred_sets):
        for c in classes:
            if c in g and c in p:
                cnt[c][0] += 1
            elif c in p:
                cnt[c][1] += 1
            elif c in g:
                cnt[c][2] += 1
    per_class = {}
    for c in classes:
        tp, fp, fn = cnt[c]
        p, r, f = prf(tp, fp, fn)
        per_class[c] = {
            "support": tp + fn,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": p,
            "recall": r,
            "f1": f,
            "scored": tp + fn >= 1,
        }
    scored = [c for c in classes if per_class[c]["scored"]]
    excluded = [c for c in classes if not per_class[c]["scored"]]
    macro = sum(per_class[c]["f1"] for c in scored) / len(scored) if scored else None
    TP = sum(v[0] for v in cnt.values())
    FP = sum(v[1] for v in cnt.values())
    FN = sum(v[2] for v in cnt.values())
    mp, mr, mf = prf(TP, FP, FN)
    return {
        "n": len(gold_sets),
        "macro_f1": macro,
        "micro_f1": mf,
        "micro_precision": mp,
        "micro_recall": mr,
        "TP": TP,
        "FP": FP,
        "FN": FN,
        "scored_classes": scored,
        "excluded_classes": excluded,
        "per_class": per_class,
    }


def bootstrap_ci(
    gold_sets: Sequence[frozenset[str]],
    pred_sets: Sequence[frozenset[str]],
    metric: Callable[[list, list], float | None],
    n: int = N_BOOT,
    seed: int = SEED,
    alpha: float = ALPHA,
) -> dict:
    """단위 재표집 부트스트랩 percentile 구간. 값이 정의되지 않는 재표집(C* 공집합)은 뺀다."""
    N = len(gold_sets)
    if N == 0:
        return {"low": None, "high": None, "n_resamples": n, "n_defined": 0, "seed": seed}
    rnd = random.Random(seed)
    vals = []
    for _ in range(n):
        idx = [rnd.randrange(N) for _ in range(N)]
        v = metric([gold_sets[i] for i in idx], [pred_sets[i] for i in idx])
        if v is not None:
            vals.append(v)
    if not vals:
        return {"low": None, "high": None, "n_resamples": n, "n_defined": 0, "seed": seed}
    vals.sort()
    m = len(vals)
    lo = vals[int(alpha / 2 * m)]
    hi = vals[max(int((1 - alpha / 2) * m) - 1, 0)]
    return {"low": lo, "high": hi, "n_resamples": n, "n_defined": m, "seed": seed}


def _macro(g, p):
    return multilabel_scores(g, p)["macro_f1"]


def _micro(g, p):
    return multilabel_scores(g, p)["micro_f1"]


def _read_jsonl(path: Path) -> list[tuple[int, dict]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PredictionError(f"{path}:{lineno}: JSON 파싱 실패 ({exc})") from exc
            if not isinstance(obj, dict):
                raise PredictionError(f"{path}:{lineno}: 한 줄은 JSON 객체여야 한다")
            rows.append((lineno, obj))
    return rows


def _codes(raw, where: str, allowed: Sequence[str]) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(c, str) for c in raw):
        raise PredictionError(f"{where}: risk_codes는 문자열 목록이어야 한다")
    bad = sorted({c for c in raw if c not in allowed})
    if bad:
        raise PredictionError(f"{where}: 허용되지 않는 코드 {bad} (허용: {', '.join(allowed)})")
    return raw


def load_gold(path: str | Path) -> dict[str, frozenset[str]]:
    """골드 JSONL: 줄마다 review_id, risk_codes(R1~R9)."""
    path = Path(path)
    gold: dict[str, frozenset[str]] = {}
    for lineno, obj in _read_jsonl(path):
        where = f"{path}:{lineno}"
        rid = obj.get("review_id")
        if not isinstance(rid, str) or not rid:
            raise PredictionError(f"{where}: review_id가 없다")
        if rid in gold:
            raise PredictionError(f"{where}: review_id 중복 {rid}")
        gold[rid] = frozenset(_codes(obj.get("risk_codes"), where, TIER1))
    return gold


def load_predictions(path: str | Path) -> dict[str, Prediction]:
    path = Path(path)
    preds: dict[str, Prediction] = {}
    for lineno, obj in _read_jsonl(path):
        where = f"{path}:{lineno}"
        rid = obj.get("review_id")
        if not isinstance(rid, str) or not rid:
            raise PredictionError(f"{where}: review_id가 없다")
        if rid in preds:
            raise PredictionError(f"{where}: review_id 중복 {rid}")
        gen = obj.get("generator")
        if gen not in GENERATORS:
            raise PredictionError(f"{where}: generator는 {'/'.join(GENERATORS)} 중 하나여야 한다(받음: {gen!r})")
        if "risk_codes" not in obj:
            raise PredictionError(f"{where}: risk_codes가 없다(없으면 빈 목록 [])")
        codes = _codes(obj["risk_codes"], where, (*NON_SCORED_CODES, *TIER1))
        kept = frozenset(c for c in codes if c in TIER1)
        preds[rid] = Prediction(rid, kept, gen, dropped_r0=sum(1 for c in codes if c in NON_SCORED_CODES))
    return preds


def score(
    gold: dict[str, frozenset[str]],
    preds: dict[str, Prediction],
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict:
    """골드 전체(review_id 순)를 단위로 채점한다. 없는 예측은 빈 집합."""
    ids = sorted(gold)
    missing = [r for r in ids if r not in preds]
    extra = sorted(r for r in preds if r not in gold)
    gold_sets = [gold[r] for r in ids]
    pred_sets = [preds[r].codes if r in preds else frozenset() for r in ids]
    res = multilabel_scores(gold_sets, pred_sets)
    res["macro_f1_ci95"] = bootstrap_ci(gold_sets, pred_sets, _macro, n=n_boot, seed=seed)
    res["micro_f1_ci95"] = bootstrap_ci(gold_sets, pred_sets, _micro, n=n_boot, seed=seed)
    scored_preds = [preds[r] for r in ids if r in preds]
    res["predictions"] = {
        "scored": len(scored_preds),
        "missing": len(missing),
        "missing_ids": missing,
        "extra_ignored": len(extra),
        "empty_sets": sum(1 for s in pred_sets if not s),
        "dropped_r0_labels": sum(p.dropped_r0 for p in scored_preds),
        "generator_counts": dict(sorted(Counter(p.generator for p in scored_preds).items())),
    }
    res["gold_no_risk_units"] = sum(1 for s in gold_sets if not s)
    res["exclusion_rule"] = "골드 support=0 클래스는 Macro-F1에서 제외(04_평가_명세 §2.1 규칙 ①). Micro에는 FP로 들어간다"
    res["bootstrap"] = {
        "method": "단위(심사평) 재표집, percentile 95%, 재표집마다 C* 재계산",
        "n_resamples": n_boot,
        "seed": seed,
    }
    return res


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _r(x):
    return None if x is None else round(x, 4)


def rounded(res: dict) -> dict:
    out = dict(res)
    for k in ("macro_f1", "micro_f1", "micro_precision", "micro_recall"):
        out[k] = _r(res[k])
    for k in ("macro_f1_ci95", "micro_f1_ci95"):
        ci = dict(res[k])
        ci["low"], ci["high"] = _r(ci["low"]), _r(ci["high"])
        out[k] = ci
    out["per_class"] = {
        c: {**v, "precision": _r(v["precision"]), "recall": _r(v["recall"]), "f1": _r(v["f1"])}
        for c, v in res["per_class"].items()
    }
    return out


def format_table(res: dict) -> str:
    lines = ["클래스  support   TP   FP   FN      P      R     F1  채점"]
    for c, v in res["per_class"].items():
        lines.append(
            f"{c:<6} {v['support']:>8} {v['tp']:>4} {v['fp']:>4} {v['fn']:>4}"
            f" {v['precision']:>6.4f} {v['recall']:>6.4f} {v['f1']:>6.4f}  {'O' if v['scored'] else '제외'}"
        )
    m, mi = res["macro_f1_ci95"], res["micro_f1_ci95"]

    def fmt(x):
        return "없음" if x is None else f"{x:.4f}"

    lines.append(
        f"Macro-F1 {fmt(res['macro_f1'])} [95% {fmt(m['low'])}, {fmt(m['high'])}]"
        f"  Micro-F1 {fmt(res['micro_f1'])} [95% {fmt(mi['low'])}, {fmt(mi['high'])}]  n={res['n']}"
    )
    lines.append(f"채점 클래스 {res['scored_classes']}  제외(골드 support 0) {res['excluded_classes']}")
    p = res["predictions"]
    lines.append(
        f"예측: 채점 {p['scored']} · 없음 {p['missing']}(빈 예측으로 채점) · 골드 밖 {p['extra_ignored']}(무시)"
        f" · 빈 집합 {p['empty_sets']} · R0 제외 {p['dropped_r0_labels']} · generator {p['generator_counts']}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="리뷰 단위 Tier-1 Macro-F1 채점(04_평가_명세 §2.1)")
    ap.add_argument("--pred", type=Path, required=True, help="예측 JSONL")
    ap.add_argument("--gold", type=Path, required=True, help="골드 JSONL (disapere_gold.jsonl)")
    ap.add_argument("--out", type=Path, required=True, help="결과 JSON")
    ap.add_argument("--n-boot", type=int, default=N_BOOT, help=f"부트스트랩 횟수(기본 {N_BOOT}, 사전 고정)")
    ap.add_argument("--seed", type=int, default=SEED, help=f"부트스트랩 시드(기본 {SEED}, 사전 고정)")
    args = ap.parse_args(argv)

    try:
        gold = load_gold(args.gold)
        preds = load_predictions(args.pred)
    except PredictionError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    res = score(gold, preds, n_boot=args.n_boot, seed=args.seed)
    out = {
        "metric": "review-level multilabel Tier-1 Macro-F1 (04_평가_명세 §2.1)",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "gold_file": str(args.gold),
        "gold_sha256": _sha256_file(args.gold),
        "pred_file": str(args.pred),
        "pred_sha256": _sha256_file(args.pred),
        **rounded(res),
        "reference_lines": REFERENCE_LINES,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(format_table(res))
    print(f"결과: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
