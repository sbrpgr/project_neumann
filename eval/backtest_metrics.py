"""백테스트 지표(04_평가_명세 §0.4, 사전 고정 2026-09-30).

입력 = 판정 복원 결과(`judge_run.aggregate`의 graded): (시스템, 조건, 논문)마다 순위 1~3의 다수결 등급.
빈 자리(시스템이 위험을 3개 못 냄)는 None이다.

정의(논문 단위로 계산해 평균):
- 적중률 precision@3 = A 개수 / 3. 빈 자리는 A가 아니다(분모 3 고정).
- Top-3 적중 hit@3 = A가 하나라도 있으면 1.
- 오탐률 = C 개수 / 3(빈 자리는 C가 아니다).
- 특이성 = 적중률(진짜) − 적중률(셔플). 같은 논문끼리 짝지어 부트스트랩.
- 근거율 = 원문 대조를 통과한 근거가 붙은 위험 / 낸 위험(합의 비율). 일반 LLM은 0.
- 시스템 실패(위험 0개)도 빼지 않는다: 그 논문은 적중 0으로 센다.
- 모든 지표에 n과 95% 부트스트랩 구간(논문 재표집 2,000회, `random.Random(20260930)`, percentile).
- Neumann − 일반 LLM: 두 시스템이 모두 있는 논문끼리 짝지은 차이를 부트스트랩.
- 사람 대 AI: 3등급 일치율, A 여부 이진 일치율과 Cohen κ(분산이 없으면 undefined, 0으로 속이지 않는다),
  유병률·지지 수를 같은 표에(§2.4).
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from eval.backtest_common import ALPHA, N_BOOT, SEEDS

SYSTEMS = ("neumann", "baseline_llm")
MAIN = "neumann"
BASELINE = "baseline_llm"


def precision_at_3(grades: Sequence[str | None]) -> float:
    return sum(1 for g in grades if g == "A") / 3


def hit_at_3(grades: Sequence[str | None]) -> float:
    return 1.0 if any(g == "A" for g in grades) else 0.0


def fp_rate(grades: Sequence[str | None]) -> float:
    return sum(1 for g in grades if g == "C") / 3


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _pct(sorted_xs: list[float], q: float) -> float:
    """numpy 'linear' percentile과 같은 보간."""
    if not sorted_xs:
        raise ValueError("빈 목록")
    pos = (len(sorted_xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_xs) - 1)
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (pos - lo)


def bootstrap_ci(units: Sequence[Any], stat: Callable[[Sequence[Any]], float | None], *, n_boot: int = N_BOOT,
                 seed: int = SEEDS["bootstrap"], alpha: float = ALPHA) -> tuple[float, float] | None:
    """단위(논문) 재표집 percentile 구간. 단위가 없거나 어떤 재표집에서도 값이 정의되지 않으면 None
    (예: 모든 논문이 위험 0개라 근거율 분모가 늘 0)."""
    n = len(units)
    if n == 0:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(n_boot):
        s = stat([units[rng.randrange(n)] for _ in range(n)])
        if s is not None:
            vals.append(s)
    if not vals:
        return None
    vals.sort()
    return (round(_pct(vals, alpha / 2), 4), round(_pct(vals, 1 - alpha / 2), 4))


def _metric(units: Sequence[Any], stat: Callable[[Sequence[Any]], float | None], **kw: Any) -> dict[str, Any]:
    v = stat(units)
    return {"value": None if v is None else round(v, 4), "ci95": bootstrap_ci(units, stat, **kw), "n": len(units)}


def _ratio_stat(units: Sequence[tuple[int, int]]) -> float | None:
    num = sum(u[0] for u in units)
    den = sum(u[1] for u in units)
    return num / den if den else None


NO_SHUFFLE_NOTE = ("셔플 대조 없음(진짜 조건만 실행): 특이성(진짜 − 셔플)을 측정하지 않았다. "
                   "적중이 그 계획서에만 맞는 지적인지는 이 결과로 말할 수 없다.")


def risk_grade_share(grades: Sequence[Sequence[str | None]]) -> dict[str, Any]:
    """낸 위험(빈 자리 제외) 중 다수결 A·B·C 개수와 비율."""
    flat = [x for gs in grades for x in gs if x is not None]
    n = len(flat)
    c = Counter(flat)
    return {"n": n, "counts": {k: c[k] for k in ("A", "B", "C")},
            "share": {k: (round(c[k] / n, 4) if n else None) for k in ("A", "B", "C")}}


def vote_patterns(votes_rows: Sequence[Sequence[Sequence[str] | None]]) -> dict[str, int]:
    """위험별 3명 표의 모양: 만장일치 / 2:1 / 모두 다름(다수결 규칙상 B)."""
    out = {"unanimous": 0, "split_2_1": 0, "all_differ": 0}
    for row in votes_rows:
        for v in row or []:
            if not v:
                continue
            k = len(set(v))
            out[{1: "unanimous", 2: "split_2_1"}.get(k, "all_differ")] += 1
    return out


def compute_metrics(graded: list[dict[str, Any]], *, work_ids: list[str] | None = None, n_boot: int = N_BOOT,
                    seed: int = SEEDS["bootstrap"]) -> dict[str, Any]:
    """graded 목록 → 시스템별 지표·특이성·Neumann−일반 LLM(짝지은 부트스트랩)."""
    kw = {"n_boot": n_boot, "seed": seed}
    wanted = set(work_ids) if work_ids else None
    table: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for g in graded:
        if not g.get("judged"):
            continue
        if wanted is not None and g["work_id"] not in wanted:
            continue
        table.setdefault((g["system"], g["condition"]), {})[g["work_id"]] = g

    has_shuffle = any(c == "shuffle" for _, c in table)
    out: dict[str, Any] = {"systems": {}, "comparison": {}, "definitions": "04_평가_명세 §0.4, eval/backtest_metrics.py 머리말",
                           "n_boot": n_boot, "seed": seed, "work_ids_filter": sorted(wanted) if wanted else None,
                           "controls": {"shuffle": has_shuffle, "conditions": sorted({c for _, c in table}),
                                        "note": None if has_shuffle else NO_SHUFFLE_NOTE}}
    summary: dict[str, Any] = {}
    for system in sorted({s for s, _ in table}):
        res: dict[str, Any] = {}
        for cond in ("real", "shuffle"):
            rows = table.get((system, cond), {})
            wids = sorted(rows)
            grades = [rows[w]["grades"] for w in wids]
            if not grades:
                res[cond] = {"n": 0, "measured": False}
                continue
            ev_units = [(sum(1 for i, x in enumerate(rows[w]["evidence_ok"]) if x and i < rows[w]["n_risks"]), rows[w]["n_risks"]) for w in wids]
            res[cond] = {
                "n": len(wids),
                "measured": True,
                "precision_at_3": _metric(grades, lambda gs: _mean([precision_at_3(x) for x in gs]), **kw),
                "hit_at_3": _metric(grades, lambda gs: _mean([hit_at_3(x) for x in gs]), **kw),
                "fp_rate": _metric(grades, lambda gs: _mean([fp_rate(x) for x in gs]), **kw),
                "evidence_rate": _metric(ev_units, _ratio_stat, **kw),
                "grade_counts": dict(Counter(x if x else "-" for gs in grades for x in gs)),
                "missing_slots": sum(1 for gs in grades for x in gs if x is None),
                "failed_runs": sum(1 for w in wids if rows[w]["n_risks"] == 0),
                "n_risks": sum(rows[w]["n_risks"] for w in wids),
                "risk_grades": risk_grade_share(grades),
                "vote_patterns": vote_patterns([rows[w].get("votes") for w in wids]),
                "status_counts": dict(Counter(str(rows[w].get("status")) for w in wids)),
                "generator_counts": dict(Counter(str(rows[w].get("generator")) for w in wids)),
                "models": sorted({str(rows[w].get("model")) for w in wids}),
            }
        real, shuf = table.get((system, "real"), {}), table.get((system, "shuffle"), {})
        both = sorted(set(real) & set(shuf))
        if both:
            diffs = [precision_at_3(real[w]["grades"]) - precision_at_3(shuf[w]["grades"]) for w in both]
            res["specificity"] = _metric(diffs, _mean, **kw) | {"measured": True}
        else:
            res["specificity"] = {"measured": False, "note": "측정 못 함(셔플 대조 없음)", "n": 0}
        out["systems"][system] = res
        summary[system] = {
            "precision_at_3": res["real"].get("precision_at_3"),
            "hit_at_3": res["real"].get("hit_at_3"),
            "fp_rate": res["real"].get("fp_rate"),
            "specificity": res["specificity"] if res["specificity"].get("measured") else "측정 못 함",
            "evidence_rate": res["real"].get("evidence_rate"),
            "risk_grades": res["real"].get("risk_grades"),
            "status_counts": res["real"].get("status_counts"),
        }

    a, b = table.get((MAIN, "real"), {}), table.get((BASELINE, "real"), {})
    paired = sorted(set(a) & set(b))
    if paired:
        for name, fn in (("precision_at_3", precision_at_3), ("hit_at_3", hit_at_3), ("fp_rate", fp_rate)):
            diffs = [fn(a[w]["grades"]) - fn(b[w]["grades"]) for w in paired]
            out["comparison"][f"{name}_diff_{MAIN}_minus_{BASELINE}"] = _metric(diffs, _mean, **kw)
        # McNemar용 불일치 쌍(hit@3). n이 작아 유의성은 주장하지 않는다(§2.3)
        bc = Counter((hit_at_3(a[w]["grades"]), hit_at_3(b[w]["grades"])) for w in paired)
        out["comparison"]["hit_at_3_discordant"] = {"neumann_only": bc[(1.0, 0.0)], "baseline_only": bc[(0.0, 1.0)], "n": len(paired)}
        # 민감도: 어느 쪽이든 status가 ok가 아닌 논문(강등·실패)을 뺀 짝. 주 지표는 그 논문을 빼지 않는다
        not_ok = [w for w in paired if a[w].get("status") != "ok" or b[w].get("status") != "ok"]
        if not_ok:
            ok_pairs = [w for w in paired if w not in not_ok]
            sens: dict[str, Any] = {"excluded_work_ids": not_ok, "n": len(ok_pairs)}
            for name, fn in (("precision_at_3", precision_at_3), ("hit_at_3", hit_at_3)):
                diffs = [fn(a[w]["grades"]) - fn(b[w]["grades"]) for w in ok_pairs]
                sens[f"{name}_diff"] = _metric(diffs, _mean, **kw) if ok_pairs else {"value": None, "ci95": None, "n": 0}
            out["comparison"]["sensitivity_status_ok_only"] = sens
    summary["comparison"] = out["comparison"]
    summary["controls"] = out["controls"]
    out["summary"] = summary
    return out


# ── 사람 대 AI 일치 ──────────────────────────────────────────────────────


def cohen_kappa(pairs: Sequence[tuple[str, str]], labels: Sequence[str]) -> float | None:
    """다중 등급 Cohen κ. 기대 일치가 1이면(분산 없음) None."""
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for x, y in pairs if x == y) / n
    ca = Counter(x for x, _ in pairs)
    cb = Counter(y for _, y in pairs)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in labels)
    if pe >= 1.0:
        return None
    return (po - pe) / (1 - pe)


def human_agreement(human: dict[tuple[str, str], str], ai: dict[tuple[str, str], str]) -> dict[str, Any]:
    """{(envelope_id, risk_id): 등급} 두 개 → 일치율·κ. 둘 다 있는 위험만."""
    keys = sorted(set(human) & set(ai))
    pairs = [(human[k], ai[k]) for k in keys]
    n = len(pairs)
    bin_pairs = [("A" if h == "A" else "notA", "A" if a == "A" else "notA") for h, a in pairs]
    k3 = cohen_kappa(pairs, ("A", "B", "C"))
    k2 = cohen_kappa(bin_pairs, ("A", "notA"))
    conf = Counter(f"{h}->{a}" for h, a in pairs)
    return {
        "n": n,
        "only_human": len(set(human) - set(ai)),
        "only_ai": len(set(ai) - set(human)),
        "exact_agreement_3class": round(sum(h == a for h, a in pairs) / n, 4) if n else None,
        "kappa_3class": None if k3 is None else round(k3, 4),
        "binary_A_agreement": round(sum(h == a for h, a in bin_pairs) / n, 4) if n else None,
        "kappa_binary_A": None if k2 is None else round(k2, 4),
        "kappa_note": "undefined = 기대 일치 1(한쪽 등급 분산 없음), 0으로 대체하지 않음",
        "prevalence_A_human": round(sum(h == "A" for h, _ in pairs) / n, 4) if n else None,
        "prevalence_A_ai": round(sum(a == "A" for _, a in pairs) / n, 4) if n else None,
        "support": {"human": dict(Counter(h for h, _ in pairs)), "ai": dict(Counter(a for _, a in pairs))},
        "confusion_human_to_ai": dict(sorted(conf.items())),
    }


__all__ = [
    "bootstrap_ci",
    "cohen_kappa",
    "compute_metrics",
    "fp_rate",
    "hit_at_3",
    "human_agreement",
    "precision_at_3",
]
