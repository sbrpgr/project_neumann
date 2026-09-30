"""Neumann 위험 묶음 만들기(백테스트 통합 단계): 계획서마다 제품 파이프라인을 누출 제거 상태로 돌린다.

사전 고정(2026-09-30):
- 진짜 조건: 계획서 i, 검색 제외 = 논문 i의 exclude_work_ids.
- 셔플 조건: 계획서 j(같은 분야 짝), 검색 제외 = i ∪ j(판정할 논문 i의 심사평이 근거로 새지 않게).
- 결과(PremortemResult)의 카드를 점수 순 앞 3장 → 위험 묶음(`backtest_riskset.riskset_from_premortem`).
  근거율은 근거 발췌를 원문(공유 데이터 폴더의 심사평·결정·저자 답변)과 글자 단위로 대조해 계산한다.
- 자동 누출 검사(실행마다): 유사 연구·근거 발췌의 논문이 제외 목록에 있으면, 또는 근거 인용문이 판정 논문 i의
  심사평에 글자 그대로 들어 있으면 `leak`로 기록하고 종료 코드 1. 누출 0이 아니면 그 결과로 판정하지 않는다.
- 파이프라인 강등(status degraded, 규칙 경로)은 숨기지 않고 위험 묶음의 status·generator에 그대로 남긴다.

실행(E3 `neumann.pipeline.run_premortem`과 E2 색인이 main에 있을 때):
    python -m eval.backtest_run_neumann [--limit N] [--conditions real,shuffle] [--out F] [--runs-dir D] [--cache-dir D]
mock 예행은 기본 실행 폴더(`data/eval/neumann_runs`, 실제 실행 결과)에 쓰지 않는다(`output_paths`).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eval.backtest_common import data_dir, eval_dir, read_json, read_jsonl, utf8_stdio, write_jsonl
from eval.backtest_leakage import IndexCatalog, evidence_leaks, stale_exclusions
from eval.backtest_riskset import riskset_from_premortem


def source_lookup(processed: Path) -> Callable[[Any], str | None]:
    """Excerpt → 원문. 심사평·결정은 바로 읽고, 저자 답변은 필요할 때 한 번 읽는다."""
    reviews = {r["review_id"]: r["text"] for r in read_jsonl(processed / "reviews.jsonl")}
    decisions = {d["decision_id"]: d.get("text") for d in read_jsonl(processed / "decisions.jsonl")}
    responses: dict[str, str] = {}

    def lookup(ex: Any) -> str | None:
        if ex.source_kind == "review":
            return reviews.get(ex.source_id)
        if ex.source_kind == "decision":
            return decisions.get(ex.source_id)
        if ex.source_kind == "author_response":
            if not responses and (processed / "author_responses.jsonl").is_file():
                responses.update({a["response_id"]: a["text"] for a in read_jsonl(processed / "author_responses.jsonl")})
            return responses.get(ex.source_id)
        return None

    lookup.review_work = {r["review_id"]: r["work_id"] for r in read_jsonl(processed / "reviews.jsonl")}  # type: ignore[attr-defined]
    return lookup


def leak_report(result: Any, exclude: set[str], target_review_texts: list[str], review_work: dict[str, str]) -> dict[str, Any]:
    similar = [s.work_id for s in result.similar_works if s.work_id in exclude]
    card_works = [w for c in result.risk_cards for w in c.works if w in exclude]
    ev_works = [review_work.get(e.source_id) for e in result.evidence if e.source_kind == "review"]
    ev_excluded = [w for w in ev_works if w in exclude]
    quotes = evidence_leaks([e.text for e in result.evidence], target_review_texts)
    n = len(similar) + len(card_works) + len(ev_excluded) + len(quotes)
    return {"leaks": n, "similar_in_exclude": similar, "card_works_in_exclude": card_works,
            "evidence_works_in_exclude": ev_excluded, "evidence_quotes_in_target_reviews": len(quotes)}


def run(sample: dict[str, Any], plans: dict[str, dict[str, Any]], exclusions: dict[str, Any], view: Any,
        premortem_fn: Callable[..., Any], lookup: Callable[[Any], str | None], *, limit: int | None = None,
        conditions: tuple[str, ...] = ("real", "shuffle"), runs_dir: Path | None = None) -> list[dict[str, Any]]:
    items = sample["items"][:limit] if limit else sample["items"]
    ex_by = {t["work_id"]: set(t["exclude_work_ids"]) for t in exclusions["targets"]}
    pairs = {p["work_id"]: p["plan_work_id"] for p in sample["shuffle_pairs"]}
    review_work = getattr(lookup, "review_work", {})
    rows = []
    for it in items:
        i = it["work_id"]
        targets = [r.text for r in view.reviews_for(i)]
        for cond in conditions:
            j = i if cond == "real" else pairs[i]
            exclude = ex_by[i] | ex_by.get(j, set())
            if not ex_by[i]:
                raise ValueError(f"{i}: 제외 목록이 비었다(색인에서 대상을 못 찾음) — 누출 위험, 중단")
            t0 = time.perf_counter()
            res = premortem_fn(plans[j]["plan_text"], exclude_work_ids=exclude, session_id=f"backtest-{cond}-{i}")
            rs = riskset_from_premortem(res, condition=cond, work_id=i, plan_work_id=j, plan_id=plans[j]["plan_id"],
                                        source_text_for=lookup)
            rs["leak_check"] = leak_report(res, exclude, targets, review_work)
            rs["elapsed_s"] = round(time.perf_counter() - t0, 2)
            rs["n_exclude"] = len(exclude)
            if runs_dir is not None:
                p = Path(runs_dir) / f"{cond}__{i.replace(':', '_')}.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(res.model_dump_json(indent=1), encoding="utf-8")
            rows.append(rs)
    return rows


def effective_provider(cli: str | None) -> str:
    """run_premortem이 실제로 쓸 provider 이름(--provider > NEUMANN_LLM_PROVIDER/설정 > mock)."""
    if cli:
        return cli
    try:
        from neumann.config import get_settings

        return str(get_settings().llm_provider)
    except Exception:  # noqa: BLE001 — 설정을 못 읽으면 설정 기본값(mock)으로 본다
        return "mock"


def output_paths(provider: str, *, limit: int | None, out: Path | None, runs_dir: Path | None,
                 base: Path) -> tuple[Path, Path]:
    """(위험 묶음 파일, 실행 결과 폴더). mock은 기본 이름·기본 실행 폴더(`neumann_runs`)에 쓰지 않는다.

    기본 `neumann_runs/`에는 실제 실행의 결과가 논문별로 들어 있어, mock 예행이 덮어쓰면 실제 결과가 사라진다."""
    mock = provider == "mock"
    name = "riskset_neumann" + (f".first{limit}" if limit else "") + (".mock" if mock else "") + ".jsonl"
    out_path = Path(out) if out else base / name
    if runs_dir is not None:
        rd = Path(runs_dir)
    elif mock:
        rd = out_path.parent / "neumann_runs.mock"
    else:
        rd = base / "neumann_runs"
    return out_path, rd


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(description="Neumann 위험 묶음(누출 제거 상태로 파이프라인 실행)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--conditions", default="real,shuffle")
    ap.add_argument("--provider", default=None, help="run_premortem provider(기본 설정값, 보통 openai)")
    ap.add_argument("--out", type=Path, default=None,
                    help="기본 data/eval/riskset_neumann.jsonl(--limit면 .firstN, mock이면 .mock)")
    ap.add_argument("--runs-dir", type=Path, default=None,
                    help="논문별 PremortemResult 폴더. 기본 data/eval/neumann_runs(mock이면 <out 폴더>/neumann_runs.mock)")
    ap.add_argument("--cache-dir", type=Path, default=None,
                    help="run_premortem 캐시 뿌리(기본 설정값 data/cache). 예행은 임시 폴더를 준다")
    args = ap.parse_args(argv)
    try:
        from neumann.pipeline import run_premortem
    except ImportError as exc:
        print(f"[중단] neumann.pipeline.run_premortem 없음(E3 미병합): {exc}")
        return 2
    from eval.backtest_common import load_corpus_view

    provider = effective_provider(args.provider)
    out, runs_dir = output_paths(provider, limit=args.limit, out=args.out, runs_dir=args.runs_dir, base=eval_dir())

    base = data_dir()
    sample = read_json(eval_dir() / "backtest_sample.json")
    plans = {r["work_id"]: r for r in read_jsonl(eval_dir() / "backtest_plans.jsonl")}
    excl = read_json(eval_dir() / "backtest_exclusions.json")
    stale = stale_exclusions(excl, IndexCatalog.load(base / "index"))
    if stale:
        print(f"[중단] 제외 목록이 지금 색인과 맞지 않는다({len(stale)}건, 예 {stale[:3]}). "
              "`python -m eval.backtest_leakage --probe-search`를 다시 돌린다")
        return 2
    view = load_corpus_view(base)
    lookup = source_lookup(Path(view.processed_dir))

    extra: dict[str, Any] = {"cache_dir": args.cache_dir} if args.cache_dir is not None else {}

    def fn(plan_text: str, **kw: Any) -> Any:
        return run_premortem(plan_text, provider=args.provider, **extra, **kw)

    conditions = tuple(c.strip() for c in args.conditions.split(",") if c.strip())
    rows = run(sample, plans, excl, view, fn, lookup, limit=args.limit, conditions=conditions, runs_dir=runs_dir)
    sha = write_jsonl(out, rows)
    print(f"provider {provider} · 실행 결과 {runs_dir}")
    leaks = sum(r["leak_check"]["leaks"] for r in rows)
    for r in rows:
        print(f"- [{r['condition']}] {r['work_id']} status={r['status']} generator={r['generator']} 위험 {r['n_risks']} "
              f"근거통과 {sum(x['evidence_ok'] for x in r['risks'])} 누출 {r['leak_check']['leaks']} {r['elapsed_s']}s")
    print(json.dumps({"risksets": len(rows), "leaks_total": leaks}, ensure_ascii=False))
    print(f"sha256 {sha} → {out}")
    return 0 if leaks == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
