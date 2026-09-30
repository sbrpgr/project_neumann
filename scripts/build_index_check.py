"""색인 점검: 로드 시간, 저장 문장 전량 오프셋 대조, 질의별 상위 k편과 점수.

    python scripts/build_index_check.py                     # 기본 질의 3건(영어·한국어 데모 계획서·무관한 글)
    python scripts/build_index_check.py --index DIR -q "..." -q "..."
    python scripts/build_index_check.py --json out.json     # 결과를 JSON으로도 남긴다

기본 질의
1. 영어: 데모 계획서 주제의 영어 서술
2. 한국어 데모 계획서: `tests/fixtures/plans/plan.md`(없으면 기획 키트 `부록/데모입력/plan.md`) 전문
3. 한국어만: 데모 계획서 목표 문장(영어 낱말 없음) — BM25가 못 잡으니 임베딩만으로 찾는지 본다
4. 무관한 글: `tests/fixtures/plans/negative_recipe.md`(없으면 내장 조리법 글)
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

from neumann.index import search as search_mod  # noqa: E402
from neumann.index import store as store_mod  # noqa: E402
from neumann.index.settings import get_index_settings  # noqa: E402

KIT_PLAN = Path("C:/Users/User/Desktop/노이만_본선자료/기획서/부록/데모입력/plan.md")
RECIPE_FALLBACK = (
    "김치찌개 끓이는 법. 돼지고기 200g과 잘 익은 김치 반 포기를 냄비에 넣고 참기름에 5분 볶는다. "
    "물 500ml를 붓고 두부, 대파, 고춧가루를 넣어 20분 끓인다. 간은 국간장으로 맞춘다."
)


def default_queries() -> list[tuple[str, str]]:
    plan = ROOT / "tests/fixtures/plans/plan.md"
    plan_text = (plan if plan.is_file() else KIT_PLAN).read_text(encoding="utf-8")
    neg = ROOT / "tests/fixtures/plans/negative_recipe.md"
    neg_text = neg.read_text(encoding="utf-8") if neg.is_file() else RECIPE_FALLBACK
    return [
        ("en", "graph neural network surrogate model for predicting ionic conductivity of battery electrolytes"),
        ("ko_plan", plan_text),
        ("ko_only", "리튬이온 배터리 전해액의 이온전도도를 예측하는 그래프 신경망 대리모델로 후보 조성을 사전 선별한다"),
        ("unrelated", neg_text),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", type=Path, default=None)
    ap.add_argument("-q", "--query", action="append", default=None)
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    index_dir = args.index or get_index_settings().resolved_index_dir()
    t0 = time.perf_counter()
    store = store_mod.IndexStore.load(index_dir)
    load_s = time.perf_counter() - t0
    store_mod.set_store(store)
    t1 = time.perf_counter()
    check = store.verify_offsets()
    verify_s = time.perf_counter() - t1
    m = store.manifest
    print(f"색인 {index_dir}: 논문 {len(store.work_order)}편, 문장 {store.n_excerpts()}개, 태그 {store.n_tags()}개, "
          f"로드 {load_s:.2f}s, 크기 {m.get('index_bytes', 0) / 1e6:.1f}MB")
    print(f"오프셋 대조(전량): {check['passed']}/{check['checked']} 통과, 실패 {check['failed']} ({verify_s:.2f}s)")
    print(f"빌드: {m.get('build_seconds')}s, 백엔드 {json.dumps(m.get('backend', {}), ensure_ascii=False)}")

    queries = [(f"q{i + 1}", q) for i, q in enumerate(args.query)] if args.query else default_queries()
    t2 = time.perf_counter()
    info = search_mod.warmup()
    print(f"질의 임베더 준비 {time.perf_counter() - t2:.1f}s: {info}")
    report: dict[str, Any] = {"index_dir": str(index_dir), "load_s": load_s, "offset_check": check, "queries": []}
    for label, q in queries:
        t = time.perf_counter()
        hits = search_mod.search([q], k=args.k)
        dt = time.perf_counter() - t
        status = search_mod.last_search_status()
        head = q.replace("\n", " ")[:70]
        print(f"\n[{label}] {head}… ({dt * 1000:.0f}ms, {status.get('backend')})")
        rows = []
        for rank, h in enumerate(hits, 1):
            title = store.get_work(h.work_id).title
            print(f"  {rank:2d}. {h.score:.3f} (dense {h.dense:.3f}, lex {h.lexical:.3f})  {h.work_id}  {title[:80]}")
            rows.append({**h.model_dump(), "title": title})
        report["queries"].append({"label": label, "query": q, "elapsed_s": dt, "status": status, "hits": rows})
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if check["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
