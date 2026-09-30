"""현재 색인(`data/index`) vs eLife 포함 색인(`data/index_elife`) 상위 k편 전후 비교.

    python scripts/build_index_elife_compare.py                          # 데모 3건 × (계획서 전문, 짧은 영어) + 무관한 글
    python scripts/build_index_elife_compare.py --json out.json --md out.md
    python scripts/build_index_elife_compare.py --old DIR --new DIR -k 10

- 두 색인 모두 문장 전량 오프셋 대조(`IndexStore.verify_offsets`)를 먼저 한다.
- 질의 ① 계획서 전문(`tests/fixtures/plans/*.md`, E2-L0·E2-L3와 같은 방식) ② 손으로 쓴 짧은 영어 한 줄(E2-L3와 같은 문장).
  LLM(astra)이 만든 검색어가 아니다. 이 스크립트는 OpenAI를 부르지 않는다.
- 점수 = alpha·dense + (1−alpha)·lexical(기본 설정 그대로). 색인에 임베딩이 없으면 어휘 검색만(강등 표시).
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
from neumann.sources.corpus import source_of_work_id  # noqa: E402

PLANS = ROOT / "tests" / "fixtures" / "plans"
DEMOS = ("plan", "plan_elife_neuro", "plan_medimaging")
# E2-L3 보조 질의와 같은 문장(비교 가능하게). 사람이 쓴 것이다.
ENGLISH = {
    "plan": "graph neural network surrogate model for predicting ionic conductivity of battery electrolytes",
    "plan_elife_neuro": "classifying cognitive tasks from fMRI brain activation patterns with machine learning and independent component analysis",
    "plan_medimaging": "convolutional neural network (ResNet, DenseNet) classifier for detecting pneumonia in chest X-ray images",
}
SOURCE_LABEL = {"researcharcade": "OpenReview", "elife": "eLife", "europepmc": "Europe PMC"}


def default_queries() -> list[dict[str, str]]:
    out = []
    for demo in DEMOS:
        path = PLANS / f"{demo}.md"
        text = path.read_text(encoding="utf-8")
        out.append({"demo": demo, "kind": "plan", "text": text, "title": text.strip().splitlines()[0].lstrip("# ").strip()})
        out.append({"demo": demo, "kind": "en", "text": ENGLISH[demo], "title": ENGLISH[demo]})
    neg = PLANS / "negative_recipe.md"
    if neg.is_file():
        out.append({"demo": "negative_recipe", "kind": "unrelated", "text": neg.read_text(encoding="utf-8"), "title": "무관한 글"})
    return out


def load_index(index_dir: Path) -> tuple[IndexStore, dict[str, Any]]:
    t0 = time.perf_counter()
    st = IndexStore.load(index_dir)
    load_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    chk = st.verify_offsets()
    by_src: dict[str, int] = {}
    for wid in st.works:
        s = source_of_work_id(wid) or "other"
        by_src[s] = by_src.get(s, 0) + 1
    info = {
        "dir": str(index_dir),
        "works": len(st.works),
        "excerpts": st.n_excerpts(),
        "works_by_source": dict(sorted(by_src.items())),
        "load_s": round(load_s, 2),
        "offset_check": {**chk, "rate": (chk["passed"] / chk["checked"]) if chk["checked"] else None,
                         "seconds": round(time.perf_counter() - t1, 2)},
        "has_embeddings": st.embeddings is not None,
    }
    return st, info


def top_k(store: IndexStore, text: str, k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    hits = search_mod.search([text], k=k, store=store)
    status = search_mod.last_search_status()
    rows = []
    for rank, h in enumerate(hits, 1):
        w = store.works[h.work_id]
        src = source_of_work_id(h.work_id) or "other"
        rows.append({"rank": rank, "work_id": h.work_id, "title": w.title, "source": src, "score": h.score,
                     "dense": h.dense, "lexical": h.lexical, "fields": list(w.fields)})
    return rows, {"backend": status.get("backend"), "degraded": status.get("degraded")}


def compare_hits(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> dict[str, Any]:
    old_rank = {h["work_id"]: h["rank"] for h in old}
    old_dense = {h["work_id"]: h["dense"] for h in old}
    for h in new:
        h["old_rank"] = old_rank.get(h["work_id"])
    overlap = sum(1 for h in new if h["old_rank"] is not None)
    entered = [h for h in new if h["old_rank"] is None]
    src_new: dict[str, int] = {}
    for h in new:
        src_new[h["source"]] = src_new.get(h["source"], 0) + 1
    dense_diff = [abs(h["dense"] - old_dense[h["work_id"]]) for h in new if h["work_id"] in old_dense]
    return {
        "overlap": overlap,
        "k": len(new),
        "entered": len(entered),
        "entered_by_source": {s: sum(1 for h in entered if h["source"] == s) for s in sorted({h["source"] for h in entered})},
        "new_topk_by_source": dict(sorted(src_new.items())),
        "elife_in_new_topk": src_new.get("elife", 0),
        "elife_best_rank": min((h["rank"] for h in new if h["source"] == "elife"), default=None),
        "top1_old": old[0]["score"] if old else None,
        "top1_new": new[0]["score"] if new else None,
        "top1_new_source": new[0]["source"] if new else None,
        "max_dense_diff_same_work": round(max(dense_diff), 6) if dense_diff else None,
    }


def run(old_dir: Path, new_dir: Path, queries: list[dict[str, str]], k: int = 10) -> dict[str, Any]:
    old_st, old_info = load_index(old_dir)
    new_st, new_info = load_index(new_dir)
    results = []
    for q in queries:
        old_hits, old_status = top_k(old_st, q["text"], k)
        new_hits, new_status = top_k(new_st, q["text"], k)
        summary = compare_hits(old_hits, new_hits)
        results.append({**{kk: q[kk] for kk in ("demo", "kind", "title")}, "query_chars": len(q["text"]),
                        "summary": summary, "old": old_hits, "new": new_hits,
                        "backend": {"old": old_status, "new": new_status}})
    return {"old": old_info, "new": new_info, "k": k, "results": results}


def _cut(s: str, n: int = 72) -> str:
    s = s.replace("|", "/")
    return s if len(s) <= n else s[: n - 1] + "…"


def to_markdown(rep: dict[str, Any]) -> str:
    lines = []
    o, n = rep["old"], rep["new"]
    lines.append(f"- 현재 `{o['dir']}`: 논문 {o['works']}편 {o['works_by_source']}, 문장 {o['excerpts']}, "
                 f"오프셋 {o['offset_check']['passed']}/{o['offset_check']['checked']}")
    lines.append(f"- eLife 포함 `{n['dir']}`: 논문 {n['works']}편 {n['works_by_source']}, 문장 {n['excerpts']}, "
                 f"오프셋 {n['offset_check']['passed']}/{n['offset_check']['checked']}")
    lines.append("")
    lines.append("| 데모 | 질의 | 겹침 | 새로 든 논문(eLife) | eLife 최고 순위 | 확대 상위 k 소스 | 1등 점수 현재→eLife 포함 | 1등 소스 | 같은 논문 dense 최대 차 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rep["results"]:
        s = r["summary"]
        lines.append(f"| {r['demo']} | {r['kind']} | {s['overlap']}/{s['k']} | {s['entered']} ({s['entered_by_source'].get('elife', 0)}) | "
                     f"{s['elife_best_rank'] or '-'} | {s['new_topk_by_source']} | {s['top1_old']} → {s['top1_new']} | "
                     f"{SOURCE_LABEL.get(s['top1_new_source'] or '', s['top1_new_source'])} | {s['max_dense_diff_same_work']} |")
    for r in rep["results"]:
        if r["kind"] == "unrelated":
            continue
        lines.append("")
        lines.append(f"**{r['demo']} · {r['kind']}** — {_cut(r['title'], 90)}")
        lines.append("")
        lines.append("| # | 현재 색인 | 점수 | eLife 포함 색인 | 점수 | 소스 | 현재 순위 |")
        lines.append("|---|---|---|---|---|---|---|")
        for i in range(max(len(r["old"]), len(r["new"]))):
            a = r["old"][i] if i < len(r["old"]) else None
            b = r["new"][i] if i < len(r["new"]) else None
            lines.append(
                f"| {i + 1} | {_cut(a['title']) if a else ''} | {a['score']:.3f} | " if a else f"| {i + 1} |  |  | "
            )
            if b:
                lines[-1] += (f"{_cut(b['title'])} | {b['score']:.3f} | {SOURCE_LABEL.get(b['source'], b['source'])} | "
                              f"{b['old_rank'] if b['old_rank'] else '새 논문'} |")
            else:
                lines[-1] += " |  |  |  |"
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    data = get_settings().data_dir
    ap.add_argument("--old", type=Path, default=data / "index")
    ap.add_argument("--new", type=Path, default=data / "index_elife")
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--md", type=Path, default=None)
    args = ap.parse_args(argv)

    rep = run(args.old, args.new, default_queries(), args.k)
    for side in ("old", "new"):
        i = rep[side]
        print(f"[{side}] {i['dir']}: 논문 {i['works']}편 {i['works_by_source']}, 문장 {i['excerpts']}, 로드 {i['load_s']}s, "
              f"오프셋 {i['offset_check']['passed']}/{i['offset_check']['checked']}")
    for r in rep["results"]:
        s = r["summary"]
        print(f"[{r['demo']}/{r['kind']}] 겹침 {s['overlap']}/{s['k']}, 새로 든 {s['entered']} {s['entered_by_source']}, "
              f"eLife 최고 순위 {s['elife_best_rank']}, 1등 {s['top1_old']} → {s['top1_new']} ({s['top1_new_source']})")
    if args.json:
        args.json.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md:
        args.md.write_text(to_markdown(rep), encoding="utf-8")
    ok = all(rep[s]["offset_check"]["failed"] == 0 for s in ("old", "new"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
