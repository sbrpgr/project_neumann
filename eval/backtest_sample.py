"""백테스트 표본 30편(04_평가_명세 §0.1, 사전 고정).

규칙(결과를 보기 전에 고정, 2026-09-30):
- 모집단: E1-L0 AI for Science 코퍼스(ICLR 2024·2025, 분야 3개) 중 다음을 모두 만족하는 논문
  0) 선별 **강한 층**(PM 결정 2026-09-30 19:00, docs/decisions.md): `selection.jsonl`에 걸린 키워드 중 하나라도
     제목에서 걸림(`title`, 600편) 또는 서로 다른 키워드 2개 이상(`multi`, 210편). 초록에서 키워드 1개만 걸린
     약한 층(`single`, 318편)은 뺀다(E1-L0 검증: 전체 선별 오탐 약 30%, 약한 층 65~85%).
     제목 판정은 E1 선별 규칙 그대로(`researcharcade.keyword_regex`, 지우는 구 `MASK_PHRASES` 먼저 적용).
  1) 결정이 채택(accept_oral·accept_spotlight·accept_poster·accept) 또는 거절(reject)
  2) 초록이 비어 있지 않다
  3) 공식 심사평(official_review)이 3건 이상(계획서 §4.3 "심사평 3건 이상". 심사평 없는 60편도 여기서 빠진다)
- 층화: 거절·채택 두 층. 층별 편수 = 30 × 모집단 층 비율, 최대 나머지 방식(Hamilton)으로 반올림.
- 추출: 후보를 work_id 순으로 정렬한 뒤 `random.Random(20260930)`으로 거절 층 → 채택 층 순서로 `sample`.
- 순서: 앞에서부터 어느 길이로 잘라도 층 비율이 모집단과 가깝도록 비례 교차 배열(t번째 자리에 부족분이 가장 큰 층,
  같으면 거절 먼저). 그래서 앞 15편이 축소 표본이다(§0.1 "목록의 앞에서부터").
- 셔플 대조 짝(§0.4): 논문 i마다 같은 분야(분야 하나 이상 공유) 다른 표본 논문 j를 `random.Random(20260931)`로 고른다.
  i가 앞 15편이면 j도 앞 15편에서 고른다(축소해도 짝이 표본 안에 남게). 같은 분야 후보가 없으면 아무 다른 논문,
  `field_match=false`로 적는다.
- 사람 블라인드 판정 10편(§0.5): 앞 15편에서 `random.Random(20260932)`로 10편.
- 목록 sha256 = 표본 work_id 목록(순서 포함)의 정규 JSON sha256. 파일이 이미 있고 목록이 다르면 덮어쓰지 않는다.

실행:
    python -m eval.backtest_sample                 # data/eval/backtest_sample.json
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eval.backtest_common import (
    N_HUMAN,
    N_REDUCED,
    N_SAMPLE,
    SEEDS,
    canonical_sha256,
    data_dir,
    eval_dir,
    load_corpus_view,
    read_json,
    utf8_stdio,
    write_json,
)

FORMAT = "neumann-backtest-sample-v1"
MIN_OFFICIAL_REVIEWS = 3
STRATA = ("reject", "accept")  # 추출·교차 배열 순서(고정)
ACCEPT_OUTCOMES = frozenset({"accept_oral", "accept_spotlight", "accept_poster", "accept"})
REJECT_OUTCOMES = frozenset({"reject"})


def binary_decision(outcome: str | None) -> str | None:
    if outcome in ACCEPT_OUTCOMES:
        return "accept"
    if outcome in REJECT_OUTCOMES:
        return "reject"
    return None


STRONG = frozenset({"title", "multi"})


def selection_strength(title: str, keywords: dict[str, list[str]] | None) -> str:
    """선별 강도: title(걸린 키워드가 제목에서도 걸림) / multi(서로 다른 키워드 2개 이상) / single / none."""
    from neumann.sources.researcharcade import MASK_PHRASES, keyword_regex  # E1 선별 규칙 그대로

    kws = sorted({k for ks in (keywords or {}).values() for k in ks})
    if not kws:
        return "none"
    t = title or ""
    for m in MASK_PHRASES:
        t = m.sub(" ", t)
    if any(keyword_regex(k).search(t) for k in kws):
        return "title"
    return "multi" if len(kws) >= 2 else "single"


def candidates_from_corpus(view: Any) -> tuple[list[dict[str, Any]], Counter]:
    """코퍼스 → 후보 레코드(work_id 순)와 제외 사유 집계."""
    out: list[dict[str, Any]] = []
    excluded: Counter = Counter()
    for wid in sorted(view.works):
        w = view.works[wid]
        dec = view.decisions.get(wid)
        outcome = dec.outcome.value if dec is not None else None
        binary = binary_decision(outcome)
        revs = view.reviews_for(wid)
        strength = selection_strength(w.title, (view.selection.get(wid) or {}).get("keywords"))
        if strength not in STRONG:
            excluded[f"weak_selection_{strength}"] += 1
            continue
        if binary is None:
            excluded["decision_not_binary"] += 1
            continue
        if not (w.abstract or "").strip():
            excluded["no_abstract"] += 1
            continue
        if len(revs) < MIN_OFFICIAL_REVIEWS:
            excluded[f"official_reviews_lt_{MIN_OFFICIAL_REVIEWS}"] += 1
            continue
        out.append(
            {
                "work_id": wid,
                "native_id": w.native_id,
                "title": w.title,
                "url": w.url,
                "venue": w.venue,
                "decision": binary,
                "outcome": outcome,
                "fields": list(w.fields),
                "selection_strength": strength,
                "n_official_reviews": len(revs),
                "review_ids": [r.review_id for r in revs],
                "abstract_chars": len(w.abstract or ""),
                "content_sha256": w.provenance.content_sha256,
            }
        )
    return out, excluded


def largest_remainder(n: int, sizes: dict[str, int], order: Sequence[str] = STRATA) -> dict[str, int]:
    """n을 층 크기 비율로 나눈다(Hamilton). 나머지가 같으면 order 순서."""
    total = sum(sizes.values())
    if total < n:
        raise ValueError(f"모집단 {total}편 < 표본 {n}편")
    exact = {s: n * sizes.get(s, 0) / total for s in order}
    quota = {s: int(exact[s]) for s in order}
    rest = n - sum(quota.values())
    for s in sorted(order, key=lambda s: (-(exact[s] - quota[s]), order.index(s)))[:rest]:
        quota[s] += 1
    for s in order:
        if quota[s] > sizes.get(s, 0):
            raise ValueError(f"층 {s}: 필요 {quota[s]}편 > 모집단 {sizes.get(s, 0)}편")
    return quota


def proportional_interleave(picks: dict[str, list[Any]], order: Sequence[str] = STRATA) -> list[Any]:
    """층별 목록을 비례 교차 배열. t번째 자리 = 부족분(t·q_s/n − 뽑은 수)이 가장 큰 층."""
    n = sum(len(v) for v in picks.values())
    taken = {s: 0 for s in order}
    out: list[Any] = []
    for t in range(1, n + 1):
        best = None
        for s in order:
            if taken[s] >= len(picks.get(s, [])):
                continue
            deficit = t * len(picks[s]) / n - taken[s]
            if best is None or deficit > best[0] + 1e-12:
                best = (deficit, s)
        s = best[1]  # type: ignore[index]
        out.append(picks[s][taken[s]])
        taken[s] += 1
    return out


def draw_sample(cands: list[dict[str, Any]], n: int = N_SAMPLE, seed: int = SEEDS["sample"]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    cands = sorted(cands, key=lambda c: c["work_id"])
    by = {s: [c for c in cands if c["decision"] == s] for s in STRATA}
    quota = largest_remainder(n, {s: len(v) for s, v in by.items()})
    rng = random.Random(seed)
    picks = {s: rng.sample(by[s], quota[s]) for s in STRATA}
    return proportional_interleave(picks), quota


def shuffle_pairs(items: list[dict[str, Any]], seed: int = SEEDS["shuffle"], reduced: int = N_REDUCED) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    pairs = []
    for pos, it in enumerate(items):
        pool = items[:reduced] if pos < reduced else items
        others = [o for o in pool if o["work_id"] != it["work_id"]]
        same = [o for o in others if set(o["fields"]) & set(it["fields"])]
        cand = same or others
        j = rng.choice(cand)
        pairs.append(
            {
                "work_id": it["work_id"],
                "plan_work_id": j["work_id"],
                "field_match": bool(same),
                "shared_fields": sorted(set(j["fields"]) & set(it["fields"])),
            }
        )
    return pairs


def human_sample(items: list[dict[str, Any]], k: int = N_HUMAN, seed: int = SEEDS["human"], reduced: int = N_REDUCED) -> list[str]:
    head = [it["work_id"] for it in items[:reduced]]
    chosen = set(random.Random(seed).sample(head, min(k, len(head))))
    return [w for w in head if w in chosen]


def strata_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    c = Counter(it["decision"] for it in items)
    return {s: c.get(s, 0) for s in STRATA}


def build_sample(view: Any, n: int = N_SAMPLE) -> dict[str, Any]:
    cands, excluded = candidates_from_corpus(view)
    items, quota = draw_sample(cands, n)
    for pos, it in enumerate(items, 1):
        it["pos"] = pos
        it["reduced"] = pos <= N_REDUCED
    pop = strata_counts(cands)
    work_ids = [it["work_id"] for it in items]
    outputs = (view.manifest or {}).get("outputs", {})
    return {
        "format": FORMAT,
        "seeds": {"sample": SEEDS["sample"], "shuffle": SEEDS["shuffle"], "human": SEEDS["human"]},
        "n": len(items),
        "reduced_n": N_REDUCED,
        "list_sha256": canonical_sha256(work_ids),
        "reduced_list_sha256": canonical_sha256(work_ids[:N_REDUCED]),
        "corpus": {
            "adapter": view.source,
            "processed_dir": view.processed_dir,
            "generated_at": (view.manifest or {}).get("generated_at"),
            "works_sha256": outputs.get("works.jsonl", {}).get("sha256"),
            "reviews_sha256": outputs.get("reviews.jsonl", {}).get("sha256"),
            "decisions_sha256": outputs.get("decisions.jsonl", {}).get("sha256"),
        },
        "eligibility": {
            "rules": [
                "selection strength in {title, multi} (strong stratum, PM decision 2026-09-30 19:00)",
                "decision in accept_oral|accept_spotlight|accept_poster|accept|reject",
                "abstract non-empty",
                f"official_review >= {MIN_OFFICIAL_REVIEWS}",
            ],
            "corpus_works": len(view.works),
            "eligible": len(cands),
            "excluded": dict(sorted(excluded.items())),
            "population_strata": pop,
            "population_reject_ratio": round(pop["reject"] / len(cands), 4) if cands else None,
            "population_by_field": dict(sorted(Counter(f for c in cands for f in c["fields"]).items())),
            "population_by_strength": dict(sorted(Counter(c["selection_strength"] for c in cands).items())),
            "corpus_by_strength": dict(sorted(Counter(
                selection_strength(w.title, (view.selection.get(wid) or {}).get("keywords")) for wid, w in view.works.items()
            ).items())),
        },
        "strata_quota": quota,
        "sample_strata": strata_counts(items),
        "reduced_strata": strata_counts(items[:N_REDUCED]),
        "sample_by_field": dict(sorted(Counter(f for it in items for f in it["fields"]).items())),
        "sample_by_venue": dict(sorted(Counter(it["venue"] for it in items).items())),
        "sample_by_strength": dict(sorted(Counter(it["selection_strength"] for it in items).items())),
        "items": items,
        "shuffle_pairs": shuffle_pairs(items),
        "human_sample": human_sample(items),
    }


def save_sample(sample: dict[str, Any], out: Path, *, force: bool = False) -> str:
    if out.is_file() and not force:
        old = read_json(out)
        if old.get("list_sha256") != sample["list_sha256"]:
            raise SystemExit(
                f"{out}가 이미 있고 목록이 다르다(사전 고정 위반 방지). 이전 {old.get('list_sha256')} "
                f"!= 새 {sample['list_sha256']}. 의도한 것이면 --force와 사유를 보고서에 남긴다."
            )
    return write_json(out, sample)


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(description="백테스트 표본 30편(층화·시드 고정)")
    ap.add_argument("--data-dir", type=Path, default=None, help="공유 데이터 폴더(기본 NEUMANN_DATA_DIR)")
    ap.add_argument("--out", type=Path, default=None, help="기본 data/eval/backtest_sample.json")
    ap.add_argument("--force", action="store_true", help="목록이 달라도 덮어쓴다(사유를 보고서에)")
    args = ap.parse_args(argv)

    view = load_corpus_view(args.data_dir or data_dir())
    sample = build_sample(view)
    out = args.out or eval_dir() / "backtest_sample.json"
    file_sha = save_sample(sample, out, force=args.force)
    el = sample["eligibility"]
    print(f"코퍼스 {el['corpus_works']}편(어댑터 {sample['corpus']['adapter']}) 선별 강도 {el['corpus_by_strength']}")
    print(f"→ 적격 {el['eligible']}편(강도 {el['population_by_strength']}), 제외 {el['excluded']}")
    print(f"모집단 층 {el['population_strata']} 거절 비율 {el['population_reject_ratio']} · 분야 {el['population_by_field']}")
    print(f"표본 {sample['n']}편 층 {sample['sample_strata']} · 앞 {sample['reduced_n']}편 층 {sample['reduced_strata']}")
    print(f"분야 {sample['sample_by_field']} · 연도 {sample['sample_by_venue']} · 강도 {sample['sample_by_strength']}")
    fm = sum(p["field_match"] for p in sample["shuffle_pairs"])
    print(f"셔플 짝 {len(sample['shuffle_pairs'])}쌍(같은 분야 {fm}) · 사람 판정 {len(sample['human_sample'])}편")
    print(f"list_sha256 {sample['list_sha256']}")
    print(f"reduced_list_sha256 {sample['reduced_list_sha256']}")
    print(f"file_sha256 {file_sha}  → {out}")
    for it in sample["items"]:
        print(f"  {it['pos']:>2} {it['decision']:<6} {it['work_id']:<32} {','.join(it['fields'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
