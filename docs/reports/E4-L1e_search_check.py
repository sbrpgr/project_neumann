"""E4-L1e 예시 계획서 로컬 검색 확인: 계획서 전문 1개 질의 → main neumann.index.search 상위 10편.

    PYTHONPATH=<main>/src NEUMANN_DATA_DIR=... NEUMANN_EMBED_MODEL=... NEUMANN_EMBED_BATCH=2 \
    python docs/reports/E4-L1e_search_check.py <이 worktree> <main 체크아웃> <출력.json>

API 호출 없음. bge-m3는 프로세스에서 한 번만 읽고 끝나면 해제한다.
"""
import json
import sys
from pathlib import Path

WT = Path(sys.argv[1])
MAIN = Path(sys.argv[2])
OUT = Path(sys.argv[3])
EXTRA = sys.argv[4:]  # 추가 파일(조정 전 초안 등)

PLANS = [
    ("example-battery", "소재·화학·분자", "materials_chemistry_molecules", MAIN / "tests/fixtures/plans/plan.md"),
    ("example-binding", "단백질·생물·신약", "protein_biology_drug", WT / "src/neumann/api/templates/examples/protein_ligand_affinity.md"),
    ("example-operator", "물리·PDE·기후", "physics_pde_climate", WT / "src/neumann/api/templates/examples/neural_operator_weather.md"),
    ("old-fmri", "신경과학(옛)", None, MAIN / "tests/fixtures/plans/plan_elife_neuro.md"),
    ("old-medimaging", "의료영상(옛)", None, MAIN / "tests/fixtures/plans/plan_medimaging.md"),
]
for p in EXTRA:
    name, field, path = p.split("=", 2)
    PLANS.append((name, field, field, Path(path)))


def main() -> None:
    import neumann.index.search as S
    from neumann.index.embed import clear_embedder_cache
    from neumann.index.store import get_store

    store = get_store()
    from neumann.index.settings import get_index_settings

    works = {}
    idx = Path(get_index_settings().resolved_index_dir())
    for line in (idx / "works.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        works[r["work_id"]] = r
    out = {"index_dir": str(idx), "n_works": len(works), "manifest_model": store.manifest.get("dense_model"), "plans": []}
    for pid, dom, field_key, path in PLANS:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        hits = S.search([text], k=10)
        st = S.last_search_status()
        rows = []
        for h in hits:
            w = works.get(h.work_id, {})
            rows.append({"work_id": h.work_id, "title": w.get("title", ""), "fields": w.get("fields", []),
                         "score": round(h.score, 3), "dense": round(h.dense, 3), "lexical": round(h.lexical, 3)})
        own = sum(1 for r in rows if field_key and field_key in r["fields"]) if field_key else None
        out["plans"].append({"id": pid, "domain": dom, "file": path.name, "chars": len(text),
                             "relevance": st.get("relevance"), "backend": st.get("backend"),
                             "degraded": st.get("degraded"), "own_field_in_top10": own, "hits": rows})
    clear_embedder_cache()
    try:
        import gc, torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for p in out["plans"]:
        rel = p["relevance"] or {}
        print(f"\n## {p['id']} ({p['domain']}) verdict={rel.get('verdict')} own_field={p['own_field_in_top10']} degraded={p['degraded']}")
        for i, r in enumerate(p["hits"], 1):
            print(f"{i:2d}. {r['score']:.3f} d{r['dense']:.3f} l{r['lexical']:.3f} {','.join(f[:7] for f in r['fields'])} | {r['title'][:90]}")


if __name__ == "__main__":
    main()
