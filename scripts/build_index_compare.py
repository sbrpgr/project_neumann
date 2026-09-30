"""두 색인의 검색 결과 비교: 현재 AI4S 색인(`data/index`) vs 확대 색인(`data/index_l3`).

    python scripts/build_index_compare.py                          # 데모 계획서 3건, 상위 10편
    python scripts/build_index_compare.py --json out.json --md out.md
    python scripts/build_index_compare.py --old DIR --new DIR --plan a.md --plan b.md -k 10

- 질의: 데모 계획서 전문 한 건(`search([plan_text])`). E2-L0 보고서의 "한국어 데모 계획서" 질의와 같은 방식이다.
  파이프라인은 astra가 만든 영어 검색어를 더 넣지만, 이 비교는 실제 OpenAI를 부르지 않는다.
- 두 색인 모두 로드 뒤 문장 전량 오프셋을 다시 대조한다(빌드와 독립한 세 번째 대조).
- 그룹: 확대 색인 논문의 `fields`에 `general_ml`이 있으면 "일반 ML", 아니면 "AI4S".
- 같은 논문의 dense 점수가 두 색인에서 같은지(같은 제목+초록·같은 모델)도 본다. lexical은 코퍼스가 커지며 idf·평균 길이가
  바뀌므로 조금 달라진다.
- 무관한 글(`negative_recipe.md`)은 점수 바닥 참고로 1등 점수만 적는다(`--no-negative`로 끔).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from neumann.config import get_settings  # noqa: E402
from neumann.index import search as search_mod  # noqa: E402
from neumann.index.store import IndexStore  # noqa: E402

PLANS_DIR = ROOT / "tests" / "fixtures" / "plans"
DEMO_PLANS = ("plan.md", "plan_elife_neuro.md", "plan_medimaging.md")
NEGATIVE_PLAN = "negative_recipe.md"
GENERAL_ML = "general_ml"
GROUP_KO = {"ai4science": "AI4S", GENERAL_ML: "일반 ML"}


def group_of(store: IndexStore, work_id: str) -> str:
    w = store.works.get(work_id)
    return GENERAL_ML if w is not None and GENERAL_ML in (w.fields or []) else "ai4science"


def plan_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s
    return fallback


def compare_hits(old_hits: list, new_hits: list, old_store: IndexStore, new_store: IndexStore) -> dict[str, Any]:
    """상위 k 두 목록 → 순위표·겹침·새로 들어온 논문(그룹별)·빠진 논문·같은 논문의 dense 차이."""
    old_rank = {h.work_id: i + 1 for i, h in enumerate(old_hits)}
    new_rank = {h.work_id: i + 1 for i, h in enumerate(new_hits)}
    old_ids, new_ids = list(old_rank), list(new_rank)
    overlap = [w for w in new_ids if w in old_rank]
    entered = [w for w in new_ids if w not in old_rank]
    dropped = [w for w in old_ids if w not in new_rank]

    def row(h, store: IndexStore, rank: int) -> dict[str, Any]:
        return {
            "rank": rank,
            "work_id": h.work_id,
            "title": store.get_work(h.work_id).title,
            "score": round(h.score, 4),
            "dense": round(h.dense, 4),
            "lexical": round(h.lexical, 4),
            "group": group_of(store, h.work_id),
        }

    old_rows = [row(h, old_store, i + 1) for i, h in enumerate(old_hits)]
    new_rows = []
    for i, h in enumerate(new_hits):
        r = row(h, new_store, i + 1)
        r["old_rank"] = old_rank.get(h.work_id)  # 현재 색인 상위 k 안의 순위(없으면 None)
        r["in_old_corpus"] = h.work_id in old_store.works
        new_rows.append(r)

    old_by_id = {h.work_id: h for h in old_hits}
    dense_diff = [abs(h.dense - old_by_id[h.work_id].dense) for h in new_hits if h.work_id in old_by_id]
    entered_groups: dict[str, int] = {}
    for w in entered:
        g = group_of(new_store, w)
        entered_groups[g] = entered_groups.get(g, 0) + 1
    new_groups: dict[str, int] = {}
    for r in new_rows:
        new_groups[r["group"]] = new_groups.get(r["group"], 0) + 1
    return {
        "old": old_rows,
        "new": new_rows,
        "overlap": len(overlap),
        "entered": len(entered),
        "entered_by_group": dict(sorted(entered_groups.items())),
        "entered_from_old_corpus": sum(1 for w in entered if w in old_store.works),
        "dropped": len(dropped),
        "dropped_ids": dropped,
        "new_by_group": dict(sorted(new_groups.items())),
        "rank_moves": {w: [old_rank[w], new_rank[w]] for w in overlap},
        "same_work_dense_max_abs_diff": round(max(dense_diff), 6) if dense_diff else None,
        "old_score_range": [old_rows[-1]["score"], old_rows[0]["score"]] if old_rows else None,
        "new_score_range": [new_rows[-1]["score"], new_rows[0]["score"]] if new_rows else None,
    }


def _cell(s: str, n: int = 72) -> str:
    s = " ".join(s.split()).replace("|", "\\|")
    return s if len(s) <= n else s[: n - 1] + "…"


def render_markdown(results: list[dict[str, Any]], k: int) -> str:
    """보고서에 붙일 표(계획서마다 한 표) + 요약 표."""
    lines: list[str] = []
    lines.append("| 데모 | 겹침 | 새로 든 논문(일반 ML / AI4S) | 확대 상위 k 그룹(일반 ML / AI4S) | 1등 점수 현재→확대 | 같은 논문 dense 최대 차 |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        c = r["compare"]
        eg, ng = c["entered_by_group"], c["new_by_group"]
        top_old = c["old"][0]["score"] if c["old"] else None
        top_new = c["new"][0]["score"] if c["new"] else None
        lines.append(
            f"| {r['demo']} | {c['overlap']}/{k} | {c['entered']} ({eg.get(GENERAL_ML, 0)} / {eg.get('ai4science', 0)}) | "
            f"{ng.get(GENERAL_ML, 0)} / {ng.get('ai4science', 0)} | {top_old} → {top_new} | {c['same_work_dense_max_abs_diff']} |"
        )
    for r in results:
        c = r["compare"]
        lines.append("")
        lines.append(f"**{r['demo']}** — {_cell(r['title'], 60)}")
        lines.append("")
        lines.append("| # | 현재 AI4S 색인 | 점수 | 확대 색인 | 점수 | 그룹 | 현재 순위 |")
        lines.append("|---|---|---|---|---|---|---|")
        for i in range(max(len(c["old"]), len(c["new"]))):
            o = c["old"][i] if i < len(c["old"]) else None
            n = c["new"][i] if i < len(c["new"]) else None
            prev = "—"
            if n is not None:
                prev = str(n["old_rank"]) if n["old_rank"] else ("새 논문" if not n["in_old_corpus"] else f">{k}")
            o_cells = f"{_cell(o['title'])} | {o['score']:.3f}" if o else " | "
            n_cells = f"{_cell(n['title'])} | {n['score']:.3f} | {GROUP_KO[n['group']]} | {prev}" if n else " |  |  | "
            lines.append(f"| {i + 1} | {o_cells} | {n_cells} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    data_dir = get_settings().data_dir
    ap.add_argument("--old", type=Path, default=None, help="현재 색인(기본 {DATA_DIR}/index)")
    ap.add_argument("--new", type=Path, default=None, help="확대 색인(기본 {DATA_DIR}/index_l3)")
    ap.add_argument("--plan", type=Path, action="append", default=None, help="계획서 파일(여러 번). 기본 데모 3건")
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--no-negative", action="store_true", help="무관한 글 바닥 점수 참고를 뺀다")
    ap.add_argument("--no-verify", action="store_true", help="오프셋 전량 대조를 건너뛴다(테스트용)")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--md", type=Path, default=None)
    args = ap.parse_args(argv)

    old_dir = args.old or data_dir / "index"
    new_dir = args.new or data_dir / "index_l3"
    plans = args.plan or [PLANS_DIR / n for n in DEMO_PLANS]

    report: dict[str, Any] = {"old_index": str(old_dir), "new_index": str(new_dir), "k": args.k, "indexes": {}, "plans": []}
    stores: dict[str, IndexStore] = {}
    ok = True
    for name, d in (("old", old_dir), ("new", new_dir)):
        t = time.perf_counter()
        st = IndexStore.load(d)
        load_s = time.perf_counter() - t
        info: dict[str, Any] = {
            "dir": str(d),
            "works": len(st.work_order),
            "excerpts": st.n_excerpts(),
            "tags": st.n_tags(),
            "load_s": round(load_s, 3),
            "index_bytes": st.manifest.get("index_bytes"),
            "build_seconds": st.manifest.get("build_seconds"),
            "dense_model": st.manifest.get("dense_model"),
        }
        if not args.no_verify:
            t = time.perf_counter()
            chk = st.verify_offsets()
            info["offset_check"] = {**chk, "rate": chk["passed"] / chk["checked"] if chk["checked"] else None,
                                    "seconds": round(time.perf_counter() - t, 3)}
            ok = ok and chk["failed"] == 0
        stores[name] = st
        report["indexes"][name] = info
        print(f"[{name}] {d}: 논문 {info['works']}편, 문장 {info['excerpts']}개, 로드 {load_s:.2f}s"
              + (f", 오프셋 {info['offset_check']['passed']}/{info['offset_check']['checked']}" if "offset_check" in info else ""))
    old_ids, new_ids = set(stores["old"].works), set(stores["new"].works)
    report["corpus_overlap"] = {"old_in_new": len(old_ids & new_ids), "old_only": len(old_ids - new_ids),
                                "new_only": len(new_ids - old_ids)}
    print(f"코퍼스 겹침: 현재 {len(old_ids)}편 중 {len(old_ids & new_ids)}편이 확대 색인에 있음, 확대에만 {len(new_ids - old_ids)}편")

    for path in plans:
        text = path.read_text(encoding="utf-8")
        hits = {}
        status = {}
        for name in ("old", "new"):
            hits[name] = search_mod.search([text], k=args.k, store=stores[name])
            status[name] = search_mod.last_search_status()
            if status[name].get("degraded"):
                print(f"  주의: {name} 색인 검색이 강등됐다: {status[name].get('reason')}")
        cmp_ = compare_hits(hits["old"], hits["new"], stores["old"], stores["new"])
        entry = {"demo": path.stem, "file": str(path), "title": plan_title(text, path.stem), "status": status, "compare": cmp_}
        report["plans"].append(entry)
        print(f"\n[{path.stem}] 겹침 {cmp_['overlap']}/{args.k}, 새로 든 {cmp_['entered']}편 {cmp_['entered_by_group']}, "
              f"1등 {cmp_['old'][0]['score'] if cmp_['old'] else None} → {cmp_['new'][0]['score'] if cmp_['new'] else None}")
        for r in cmp_["new"]:
            print(f"  {r['rank']:2d}. {r['score']:.3f} [{GROUP_KO[r['group']]}] (현재 {r['old_rank'] or '-'}) {r['title'][:80]}")

    if not args.no_negative and (PLANS_DIR / NEGATIVE_PLAN).is_file():
        neg = (PLANS_DIR / NEGATIVE_PLAN).read_text(encoding="utf-8")
        floor = {}
        for name in ("old", "new"):
            h = search_mod.search([neg], k=1, store=stores[name])
            floor[name] = {"top_score": h[0].score if h else None, "title": stores[name].get_work(h[0].work_id).title if h else None}
        report["negative_floor"] = floor
        print(f"\n[무관한 글] 1등 점수 {floor['old']['top_score']} → {floor['new']['top_score']}")

    md = render_markdown(report["plans"], args.k)
    if args.md:
        args.md.write_text(md, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
