"""검색 보정 실측(E2-L1): 관련/무관 질의 세트의 점수 분포, 데모 3건 상위 10편, 여러 질의 결합.

    python scripts/build_index_calibrate.py --label before          # 현재 search() 기본값으로 잰다
    python scripts/build_index_calibrate.py --label after
    python scripts/build_index_calibrate.py --out DIR               # 기본: {NEUMANN_DATA_DIR}/index_exp_e2l1

- 색인은 **읽기만** 한다(`NEUMANN_INDEX_DIR` 또는 `{DATA}/index`). 재색인하지 않는다.
- bge-m3는 이 프로세스에서 한 번만 읽고, 질의마다 한 번만 임베딩한다(캐시 래퍼). 끝나면 해제한다.
- 번역된(영어) 축별 질의는 astra를 부르지 않고 아래 고정 예시 문자열을 쓴다.
- 결과: `<out>/<label>.json`과 표준출력 표. 보고서 `docs/reports/E2-L1.md`의 전후 표는 이 출력이다.
"""

from __future__ import annotations

import argparse
import gc
import inspect
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from neumann.index import search as search_mod  # noqa: E402
from neumann.index import store as store_mod  # noqa: E402
from neumann.index.embed import get_embedder  # noqa: E402
from neumann.index.settings import get_index_settings  # noqa: E402

PLANS = ROOT / "tests/fixtures/plans"
DEMOS = {"battery": "plan.md", "medimaging": "plan_medimaging.md", "fmri": "plan_elife_neuro.md"}

# 데모 계획서별 영어 축 질의(astra가 만들 법한 고정 예시. 실제 호출 없음)
AXIS_QUERIES: dict[str, dict[str, str]] = {
    "battery": {
        "method": "graph neural network surrogate model with a molecular graph encoder and composition embedding "
        "to predict ionic conductivity",
        "data": "literature-curated dataset of about 12,000 lithium-ion battery electrolyte formulations with measured "
        "ionic conductivity, random 80/10/10 split",
        "evaluation": "R2 and MAE on a holdout test set compared with two published baselines, no error bars or ablation",
    },
    "medimaging": {
        "method": "convolutional neural network classifier (ResNet, DenseNet) for pneumonia detection in chest X-ray images",
        "data": "public chest X-ray benchmark datasets such as CheXpert and NIH ChestX-ray, about 50,000 images, random split",
        "evaluation": "ROC-AUC, sensitivity and specificity on a validation set compared with a clinical baseline",
    },
    "fmri": {
        "method": "machine learning classifier with independent component analysis to decode cognitive task type "
        "from fMRI brain activity",
        "data": "fMRI data from about 200 subjects from OpenNeuro and the Human Connectome Project, random split",
        "evaluation": "classification accuracy, precision and recall with cross-validation, holdout test and "
        "permutation tests",
    },
}

# 짧은 한국어 5쌍(E2-L0 검증 3c와 같은 문장)
PAIRS: list[tuple[str, str]] = [
    ("Predicting crystal material properties with graph neural networks", "그래프 신경망으로 결정 재료의 물성을 예측한다"),
    ("protein language models for structure and function prediction", "단백질 언어모델로 구조와 기능을 예측한다"),
    ("molecular docking and drug design with generative models", "생성 모델을 이용한 분자 도킹과 신약 설계"),
    ("neural operators for solving partial differential equations", "편미분방정식을 푸는 뉴럴 연산자"),
    ("battery degradation prediction with machine learning", "머신러닝을 이용한 배터리 열화 예측"),
]

RELATED_EXTRA: list[tuple[str, str]] = [
    ("en_battery", "graph neural network surrogate model for predicting ionic conductivity of battery electrolytes"),
    ("ko_battery_sentence", "리튬이온 배터리 전해액의 이온전도도를 예측하는 그래프 신경망 대리모델로 후보 조성을 사전 선별한다"),
    ("ko_title_battery", "전해액 이온전도도 예측 대리모델"),
    ("ko_title_medimaging", "의료영상 분류 심층신경망"),
    ("ko_title_fmri", "fMRI 기반 인지과제 분류"),
]

# 무관한 글(코퍼스 = AI for Science 논문). 짧은·긴·영어·한국어
UNRELATED: list[tuple[str, str]] = [
    ("un_recipe_plan", "__RECIPE__"),
    ("un_ko_kimchi", "김치찌개 끓이는 법. 돼지고기 200g과 잘 익은 김치 반 포기를 냄비에 넣고 참기름에 5분 볶는다. "
     "물 500ml를 붓고 두부, 대파, 고춧가루를 넣어 20분 끓인다."),
    ("un_ko_camping", "주말 캠핑 갈 때 챙길 준비물 목록"),
    ("un_ko_lease", "아파트 전세 계약할 때 확인해야 할 주의사항"),
    ("un_ko_travel", "제주도 2박 3일 여행 일정: 첫날은 성산일출봉과 우도, 둘째 날은 한라산 등반, 셋째 날은 동문시장에서 "
     "기념품을 사고 공항으로 간다. 렌터카는 미리 예약한다."),
    ("un_en_bread", "how to bake sourdough bread at home with a starter"),
    ("un_en_lease", "tips for signing an apartment rental contract and getting the deposit back"),
    ("un_en_history", "the fall of the Roman empire and the rise of medieval kingdoms in Europe"),
    ("un_en_football", "football transfer news: the club signed a new striker for the upcoming season"),
]

# 한 질의 독점 재현(E2-L0 검증 관찰 D)
MONOPOLY = ["ionic conductivity battery electrolyte", "protein language model"]

# 데모 1(배터리)에서 코퍼스에 실제로 가장 가까운 두 편(E2-L0 검증 관찰 A)
TARGET_TITLES = ("BatteryML", "Atomic Transport")


class CachingEmbedder:
    """같은 문자열은 한 번만 임베딩한다(bge-m3 호출 수를 줄인다)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.model_id = inner.model_id
        self.dim = inner.dim
        self.device = inner.device
        self.cache: dict[str, np.ndarray] = {}

    def prime(self, texts: list[str]) -> None:
        todo = [t for t in dict.fromkeys(texts) if t not in self.cache]
        if todo:
            for t, v in zip(todo, self.inner.encode(todo), strict=True):
                self.cache[t] = np.asarray(v, dtype=np.float32)

    def encode(self, texts: list[str]) -> np.ndarray:
        self.prime(texts)
        return np.stack([self.cache[t] for t in texts]) if texts else np.zeros((0, self.dim), np.float32)


def raw_stats(store: Any, emb: CachingEmbedder, q: str, alpha: float) -> dict[str, Any]:
    """검색 구현과 무관한 원점수 분포(분리점 측정용)."""
    lex = np.asarray(store.bm25.scores(q), dtype=np.float32)
    dense = np.clip(emb.encode([q])[0] @ store.embeddings.T, 0.0, 1.0)
    comb = alpha * dense + (1 - alpha) * lex
    toks = set(search_mod.tokenize(q)) if hasattr(search_mod, "tokenize") else set()
    cov_fn = getattr(search_mod, "lexical_coverage", None)
    cov = float(cov_fn(store.bm25, q)) if cov_fn else None
    a_eff = alpha if cov is None else 1 - (1 - alpha) * cov
    adapt = a_eff * dense + (1 - a_eff) * lex

    def top(a: np.ndarray, n: int) -> list[float]:
        return [round(float(x), 4) for x in np.sort(a)[::-1][:n]]

    return {"n_tokens": len(toks), "coverage": cov, "dense_top10": top(dense, 10), "lex_top10": top(lex, 10),
            "comb_top10": top(comb, 10), "adaptive_top10": top(adapt, 10)}


def hits_rows(store: Any, hits: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for h in hits:
        d = h.model_dump()
        d["title"] = store.get_work(h.work_id).title
        rows.append(d)
    return rows


def target_ranks(store: Any, hits: list[Any]) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for t in TARGET_TITLES:
        out[t] = next((i + 1 for i, h in enumerate(hits) if t in store.get_work(h.work_id).title), None)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--label", default="run")
    args = ap.parse_args(argv)

    from neumann.config import get_settings

    index_dir = args.index or get_index_settings().resolved_index_dir()
    out_dir = args.out or (get_settings().data_dir / "index_exp_e2l1")
    if out_dir.resolve() == Path(index_dir).resolve():
        raise SystemExit("--out이 색인 폴더와 같다(색인은 읽기만 한다)")
    out_dir.mkdir(parents=True, exist_ok=True)

    store = store_mod.IndexStore.load(index_dir)
    store_mod.set_store(store)
    t0 = time.perf_counter()
    emb = CachingEmbedder(get_embedder())
    print(f"색인 {index_dir}: {len(store.work_order)}편 · 임베더 {emb.model_id} {emb.device} ({time.perf_counter() - t0:.1f}s)")
    search_mod.set_query_embedder(emb)

    plans = {name: (PLANS / f).read_text(encoding="utf-8") for name, f in DEMOS.items()}
    recipe = (PLANS / "negative_recipe.md").read_text(encoding="utf-8")
    related = [(f"demo_{n}", t) for n, t in plans.items()] + RELATED_EXTRA
    related += [(f"pair{i + 1}_en", en) for i, (en, _) in enumerate(PAIRS)]
    related += [(f"pair{i + 1}_ko", ko) for i, (_, ko) in enumerate(PAIRS)]
    unrelated = [(lbl, recipe if q == "__RECIPE__" else q) for lbl, q in UNRELATED]
    all_q = [q for _, q in related + unrelated] + MONOPOLY
    all_q += [q for axes in AXIS_QUERIES.values() for q in axes.values()]
    emb.prime(all_q)

    params = set(inspect.signature(search_mod.search).parameters)
    alpha = get_index_settings().search_alpha
    report: dict[str, Any] = {"label": args.label, "index_dir": str(index_dir), "search_params": sorted(params),
                              "settings": get_index_settings().model_dump(mode="json"), "single": [], "multi": []}

    # 1) 질의 하나씩: 관련/무관 (기본 설정의 search()와 원점수 분포)
    for group, items in (("related", related), ("unrelated", unrelated)):
        for lbl, q in items:
            hits = search_mod.search([q], k=10)
            st = search_mod.last_search_status()
            report["single"].append({"group": group, "label": lbl, "query": q, "status": st,
                                     "raw": raw_stats(store, emb, q, alpha), "hits": hits_rows(store, hits)})

    # 2) 여러 질의: 한 질의 독점 + 데모 3건(계획서 전문 + 영어 축 질의)
    multi_cases: list[tuple[str, list[str], list[str | None]]] = [("monopoly", MONOPOLY, [None, None])]
    for name, text in plans.items():
        ax = AXIS_QUERIES[name]
        multi_cases.append((f"demo_{name}_axes", [text, *ax.values()], [None, *ax.keys()]))
    pq = getattr(__import__("neumann.index.queries", fromlist=["x"]), "plan_axis_queries", None) if "axes" in params else None
    if pq is not None:
        for name, text in plans.items():
            sec = pq(text)
            multi_cases.append((f"demo_{name}_sections", [q for q, _ in sec], [a for _, a in sec]))
            ax = AXIS_QUERIES[name]
            multi_cases.append((f"demo_{name}_sections+en", [q for q, _ in sec] + list(ax.values()),
                                [a for _, a in sec] + list(ax.keys())))
    for lbl, qs, axes in multi_cases:
        kw: dict[str, Any] = {"axes": axes} if "axes" in params else {}
        hits = search_mod.search(qs, k=10, **kw)
        st = search_mod.last_search_status()
        deep = search_mod.search(qs, k=200, **kw)
        report["multi"].append({"label": lbl, "queries": qs, "axes": axes, "status": st, "hits": hits_rows(store, hits),
                                "target_ranks_top200": target_ranks(store, deep)})

    # L0 설정(max·alpha 고정·하한 0)으로 되돌리면 before와 같은지(회귀 확인)
    if "fusion" in params:
        legacy = {"fusion": "max", "adaptive_alpha": False, "score_floor": 0.0, "per_query_min": 0}
        report["legacy_regression"] = {}
        for lbl, qs, _ax in multi_cases[:4]:
            hl = search_mod.search(qs, k=10, **legacy)
            report["legacy_regression"][lbl] = [(h.work_id, h.score) for h in hl]
        for lbl, q in related[:3] + unrelated[:1]:
            hl = search_mod.search([q], k=10, **legacy)
            report["legacy_regression"][lbl] = [(h.work_id, h.score) for h in hl]

    # 하한 훑기: 하한마다 관련 질의가 10편을 다 받는지, 무관한 글이 1편이라도 받는지
    if "fusion" in params:
        sweep = []
        for fl in (0.38, 0.40, 0.42, 0.43, 0.44, 0.45, 0.46, 0.47, 0.48, 0.50):
            rel_n = [len(search_mod.search([q], k=10, score_floor=fl)) for _, q in related]
            unr_n = [len(search_mod.search([q], k=10, score_floor=fl)) for _, q in unrelated]
            sweep.append({"floor": fl, "related_full10": sum(n == 10 for n in rel_n), "related_any": sum(n > 0 for n in rel_n),
                          "related_total": len(rel_n), "unrelated_any": sum(n > 0 for n in unr_n),
                          "unrelated_total": len(unr_n)})
        report["floor_sweep"] = sweep

    # 데모 1 전문 단독 질의에서 두 표적 논문 순위
    solo = search_mod.search([plans["battery"]], k=200, **({"score_floor": 0.0} if "fusion" in params else {}))
    report["demo_battery_plan_only_target_ranks_top200"] = target_ranks(store, solo)

    path = out_dir / f"{args.label}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(report)
    print(f"\n저장: {path}")

    search_mod.set_query_embedder(None)
    del emb
    try:
        from neumann.index.embed import clear_embedder_cache

        clear_embedder_cache()
        gc.collect()
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return 0


def print_summary(rep: dict[str, Any]) -> None:
    print(f"\n## 단일 질의 [{rep['label']}]  (결과 수·1위 점수·10위 점수 | 원점수 dense 1위·10위, lex 1위, 결합 1위)")
    for r in rep["single"]:
        h = r["hits"]
        raw = r["raw"]
        s1 = f"{h[0]['score']:.3f}" if h else "-"
        s10 = f"{h[-1]['score']:.3f}" if h else "-"
        cov = raw["coverage"]
        ad = raw.get("adaptive_top10") or [0.0]
        print(f"{r['group'][:3]} {r['label']:<22} n={len(h):2d} top={s1} last={s10} | dense {raw['dense_top10'][0]:.3f}"
              f"/{raw['dense_top10'][-1]:.3f} lex {raw['lex_top10'][0]:.3f} comb {raw['comb_top10'][0]:.3f}"
              f" cov={'-' if cov is None else f'{cov:.2f}'} adapt {ad[0]:.3f}/{ad[-1]:.3f}"
              f" | {r['status'].get('relevance', {}).get('verdict', '')}")
    for m in rep["multi"]:
        print(f"\n## {m['label']} [{rep['label']}] 표적 순위(상위 200): {m['target_ranks_top200']}")
        for i, h in enumerate(m["hits"], 1):
            q = (h["matched_query"] or "").replace("\n", " ")[:28]
            print(f"  {i:2d}. {h['score']:.3f} d{h['dense']:.3f} l{h['lexical']:.3f} [{q}] {h['title'][:70]}")
    for w in rep.get("floor_sweep", []):
        print(f"하한 {w['floor']:.2f}: 관련 {w['related_full10']}/{w['related_total']} 10편 다 받음, "
              f"{w['related_any']}/{w['related_total']} 1편 이상 · 무관 {w['unrelated_any']}/{w['unrelated_total']} 1편 이상")
    print(f"\n데모1 전문 단독 표적 순위: {rep['demo_battery_plan_only_target_ranks_top200']}")


if __name__ == "__main__":
    raise SystemExit(main())
