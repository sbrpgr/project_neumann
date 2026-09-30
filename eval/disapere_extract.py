"""E5-L1b: DISAPERE 심사평에 제품 지적 추출기(E3 EX-4, astra)와 비상 규칙 태거를 돌려 리뷰 단위 예측을 만든다.

흐름(04_평가_명세 §0.6: 튜닝은 dev 358건만, 골드 148건은 채점에만):

1. extract  : 심사평 문장 → 문장별 지적(raw). astra는 E3 `neumann.analyze.extract.extract_issues`를 그대로 부르고,
              rule은 E3 비상 경로(`rules.make_rule_tagger` → `neumann.index.taxonomy.tag_excerpts`)를 그대로 부른다.
              골드 파일에서는 문장·본문만 읽는다(라벨 필드 `risk_codes` 등은 읽지 않는다).
2. tune     : dev raw + dev 라벨로 리뷰 단위 집계 규칙(극성·신뢰도 하한·최소 문장 수)을 격자에서 고른다.
              입력 행이 하나라도 dev가 아니면 거부한다. 선택 규칙은 아래 `select_config`로 사전 고정.
3. predict  : raw + 고정 집계 규칙(`FROZEN`) → 예측 JSONL(E5-L1a 형식). 채점은 `python -m eval.macro_f1`.

추출기 코드(E3 소유)는 고치지 않는다. 지시문은 E3의 `extract.INSTRUCTIONS`를 그대로 쓴다.

실행 예(공유 데이터 폴더 D=$NEUMANN_DATA_DIR/eval):
    python -m eval.disapere_extract extract --split dev --generator astra
    python -m eval.disapere_extract tune --generator astra
    python -m eval.disapere_extract predict --split gold --generator astra
    python -m eval.macro_f1 --pred $D/pred_astra_gold.jsonl --gold $D/disapere_gold.jsonl --out $D/score_astra.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from eval.macro_f1 import TIER1, multilabel_scores

# 리뷰 단위로 올리는 코드. R0(서술·표현)은 채점 대상이 아니고, R9는 심사평에서 만들지 않는다.
REVIEW_CODES = tuple(c for c in TIER1 if c != "R9")
POLARITIES = ("negative", "positive", "neutral")
DEFAULT_PARALLEL = 16
DEFAULT_RETRY_ROUNDS = 3
RETRY_BACKOFF_S = (15.0, 45.0, 90.0)
STAGE_TIMEOUT_S = 3600.0

# ── 사전 고정: 튜닝 격자와 선택 규칙 (dev 결과를 보기 전에 커밋) ───────────────────────
# 격자 순서 = "단순한 것 먼저". 동률이면 앞의 것을 고른다.
GRID_POLARITIES: tuple[tuple[str, ...], ...] = (("negative",), ("negative", "neutral"))
GRID_MIN_CONFIDENCE: tuple[float, ...] = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9)
GRID_MIN_COUNT: tuple[int, ...] = (1, 2)
SELECTION_RULE = "dev Macro-F1(점 추정) 최대. 차이 1e-9 이하 동률이면 격자 순서(극성 → 신뢰도 하한 → 최소 문장 수)에서 앞선 것"

# ── 고정 집계 규칙 (dev 튜닝 결과로 채운 뒤 커밋하고, 그 뒤 골드를 1회 채점한다) ────────────
# None이면 predict가 거부한다(튜닝 전 골드 채점 방지).
# 2026-09-30 dev 358건 튜닝(tune_*_dev.json, 선택 규칙 SELECTION_RULE 그대로):
#   astra: dev Macro 0.5553 · Micro 0.6122 (추출기 지문 7f1d7b247748d15d, E3 extract_issues.v1)
#   rule : dev Macro 0.2755 · Micro 0.3026 (neumann.index.taxonomy:tag_excerpts, min_score 2)
FROZEN: dict[str, dict[str, Any] | None] = {
    "astra": {"polarities": ["negative"], "min_confidence": 0.0, "min_count": 1},
    "rule": {"polarities": ["negative", "neutral"], "min_confidence": 0.0, "min_count": 1},
}


@dataclass(frozen=True)
class AggConfig:
    """문장별 지적 → 리뷰 단위 코드 집합 규칙."""

    polarities: tuple[str, ...] = ("negative",)
    min_confidence: float = 0.0
    min_count: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {"polarities": list(self.polarities), "min_confidence": self.min_confidence, "min_count": self.min_count}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AggConfig:
        pols = tuple(d["polarities"])
        if not pols or any(p not in POLARITIES for p in pols):
            raise ValueError(f"극성 값 오류: {pols}")
        return cls(pols, float(d["min_confidence"]), int(d["min_count"]))


def grid() -> list[AggConfig]:
    return [AggConfig(p, c, k) for p in GRID_POLARITIES for c in GRID_MIN_CONFIDENCE for k in GRID_MIN_COUNT]


# ── 입력 ─────────────────────────────────────────────────────────────────


@dataclass
class ReviewDoc:
    review_id: str
    role: str
    text: str
    sentences: list[str]
    review_url: str
    text_sha256: str


def load_docs(path: str | Path) -> list[ReviewDoc]:
    """DISAPERE JSONL에서 문장·본문만 읽는다. 라벨 필드(risk_codes·sentence_labels·votes 등)는 읽지 않는다."""
    docs: list[ReviewDoc] = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            obj = json.loads(line)
            rid = obj["review_id"]
            if rid in seen:
                raise ValueError(f"review_id 중복 {rid}")
            seen.add(rid)
            docs.append(
                ReviewDoc(
                    review_id=rid,
                    role=str(obj.get("role", "")),
                    text=obj["text"],
                    sentences=list(obj["sentences"]),
                    review_url=obj["source"]["review_url"],
                    text_sha256=obj["text_sha256"],
                )
            )
    return docs


def load_dev_labels(path: str | Path) -> dict[str, frozenset[str]]:
    """튜닝 전용: dev 라벨. 행이 하나라도 dev가 아니면(골드 등) 거부한다(§0.6)."""
    labels: dict[str, frozenset[str]] = {}
    with Path(path).open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("role") != "dev" or int(obj.get("n_annotators", 0)) != 1:
                raise ValueError(f"{path}:{lineno}: dev가 아닌 행(role={obj.get('role')!r}) — 골드는 튜닝에 쓰지 않는다")
            labels[obj["review_id"]] = frozenset(obj["risk_codes"])
    return labels


def excerpts_for(doc: ReviewDoc) -> list[Any]:
    """문장 → Excerpt(원문 본문의 오프셋 구간). 문장을 본문에서 차례로 찾는다."""
    from neumann.models import Excerpt, sha256_text

    if sha256_text(doc.text) != doc.text_sha256:
        raise ValueError(f"{doc.review_id}: 본문 해시 불일치")
    out = []
    cur = 0
    for sent in doc.sentences:
        i = doc.text.find(sent, cur)
        if i < 0:
            raise ValueError(f"{doc.review_id}: 문장을 본문에서 찾지 못함")
        cur = i + len(sent)
        if not sent.strip():
            continue
        out.append(
            Excerpt.from_source(doc.text, i, i + len(sent), source_kind="review", source_id=doc.review_id,
                                source_url=doc.review_url)
        )
    return out


# ── 추출 ─────────────────────────────────────────────────────────────────


def extractor_fingerprint() -> str:
    """E3 추출기 지시문·판 번호·스키마의 해시. 캐시 폴더를 가르고 raw에 남긴다(추출기가 바뀌면 다시 부른다)."""
    from neumann.analyze import extract

    body = json.dumps(
        {"v": extract.PROMPT_VERSION, "instructions": extract.INSTRUCTIONS, "schema": extract.build_schema(["s1"])},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


@dataclass
class ExtractStats:
    reviews: int = 0
    sentences: int = 0
    batches: int = 0
    llm_requests: int = 0  # 캐시가 아닌 실제 호출(재시도 라운드 포함)
    llm_attempts: int = 0  # provider 안의 재시도 포함
    cached_batches: int = 0
    failed_requests: int = 0
    failures_by_reason: Counter = field(default_factory=Counter)
    retry_rounds_used: int = 0
    reviews_fallback_final: int = 0
    latency_s_sum: float = 0.0
    tokens: Counter = field(default_factory=Counter)
    findings_raw: int = 0
    findings_kept: int = 0
    drops: Counter = field(default_factory=Counter)
    wall_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        for k in ("failures_by_reason", "tokens", "drops"):
            d[k] = dict(sorted(d[k].items()))
        d["latency_s_sum"] = round(self.latency_s_sum, 1)
        d["wall_s"] = round(self.wall_s, 1)
        d["mean_latency_s"] = round(self.latency_s_sum / self.llm_requests, 2) if self.llm_requests else None
        return d


def _issue_rows(issues: Iterable[Any], index: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {
            "s": index[iss.excerpt.excerpt_id],
            "start": iss.rel_start,
            "end": iss.rel_end,
            "code": iss.risk_code.value,
            "pol": iss.polarity,
            "conf": round(float(iss.confidence), 4),
            "gen": iss.generator,
        }
        for iss in issues
    ]


def extract_astra(
    docs: Sequence[ReviewDoc],
    llm: Any,
    *,
    cache_dir: Path | None,
    parallel: int = DEFAULT_PARALLEL,
    retry_rounds: int = DEFAULT_RETRY_ROUNDS,
    backoff_s: Sequence[float] = RETRY_BACKOFF_S,
    stage_timeout_s: float = STAGE_TIMEOUT_S,
    sleep=time.sleep,
) -> tuple[list[dict[str, Any]], ExtractStats]:
    """E3 extract_issues를 리뷰 단위(work = 심사평 1건)로 부른다. 실패 묶음이 있던 리뷰는 백오프 뒤 다시 부른다
    (성공 묶음은 캐시에서 온다). 끝까지 실패한 묶음은 E3가 이미 규칙 태그로 대신했고, 그 리뷰는 generator=rule."""
    from neumann.analyze.extract import extract_issues
    from neumann.analyze.rules import make_rule_tagger
    from neumann.llm import generator_for

    tagger, _impl = make_rule_tagger()
    default_gen = generator_for(getattr(llm, "name", "off"))
    stats = ExtractStats(reviews=len(docs))
    t0 = time.perf_counter()
    exs = {d.review_id: excerpts_for(d) for d in docs}
    stats.sentences = sum(len(v) for v in exs.values())
    outcome_by_review: dict[str, list[Any]] = {}

    def run(ids: list[str]) -> None:
        works = [(rid, None, exs[rid]) for rid in ids]
        res = extract_issues(works, llm, tagger=tagger, cache_dir=cache_dir, parallel=parallel,
                             stage_timeout_s=stage_timeout_s)
        per: dict[str, list[Any]] = {rid: [] for rid in ids}
        for b in res.batches:
            per[b.work_id].append(b)
            if b.cached:
                stats.cached_batches += 1
                continue
            if b.llm is not None:
                stats.llm_requests += 1
                stats.llm_attempts += b.llm.attempts
                stats.latency_s_sum += b.llm.latency_s
                stats.tokens.update(b.llm.usage)
                if not b.llm.ok:
                    stats.failed_requests += 1
                    stats.failures_by_reason[b.llm.error or "unknown"] += 1
            elif b.fallback_reason:  # 단계 상한·묶음 처리 오류(호출 결과 없음)
                stats.failed_requests += 1
                stats.failures_by_reason["stage_or_exception"] += 1
        outcome_by_review.update(per)

    ids = [d.review_id for d in docs if exs[d.review_id]]
    run(ids)
    for rnd in range(retry_rounds):
        failed = [rid for rid in ids if any(b.fallback_reason for b in outcome_by_review[rid])]
        if not failed:
            break
        stats.retry_rounds_used = rnd + 1
        sleep(backoff_s[min(rnd, len(backoff_s) - 1)])
        run(failed)

    rows = []
    for d in docs:
        index = {ex.excerpt_id: i for i, ex in enumerate(exs[d.review_id])}
        batches = outcome_by_review.get(d.review_id, [])
        fallbacks = [b.fallback_reason for b in batches if b.fallback_reason]
        issues = [iss for b in batches for iss in b.issues]
        gens = {b.generator for b in batches} or {default_gen}
        generator = "rule" if fallbacks or len(gens) != 1 else gens.pop()
        stats.batches += len(batches)
        stats.findings_raw += sum(b.n_raw for b in batches if not b.fallback_reason)
        stats.findings_kept += sum(len(b.issues) for b in batches if not b.fallback_reason)
        for b in batches:
            stats.drops.update(b.drops)
        if fallbacks:
            stats.reviews_fallback_final += 1
        rows.append(
            {
                "review_id": d.review_id,
                "generator": generator,
                "status": "degraded" if fallbacks else "ok",
                "fallback_reasons": fallbacks,
                "n_sentences": len(exs[d.review_id]),
                "n_batches": len(batches),
                "model": getattr(llm, "model", None),
                "issues": _issue_rows(issues, index),
            }
        )
    stats.wall_s = time.perf_counter() - t0
    return rows, stats


def extract_rule(docs: Sequence[ReviewDoc]) -> tuple[list[dict[str, Any]], ExtractStats, str]:
    """E3 비상 경로 그대로: make_rule_tagger(→ neumann.index.taxonomy.tag_excerpts) + rule_issues."""
    from neumann.analyze.extract import rule_issues
    from neumann.analyze.rules import make_rule_tagger

    tagger, impl = make_rule_tagger()
    stats = ExtractStats(reviews=len(docs))
    t0 = time.perf_counter()
    rows = []
    for d in docs:
        exs = excerpts_for(d)
        stats.sentences += len(exs)
        index = {ex.excerpt_id: i for i, ex in enumerate(exs)}
        issues = rule_issues(exs, d.review_id, tagger)
        stats.findings_kept += len(issues)
        rows.append(
            {
                "review_id": d.review_id,
                "generator": "rule",
                "status": "ok",
                "fallback_reasons": [],
                "n_sentences": len(exs),
                "n_batches": 0,
                "model": None,
                "issues": _issue_rows(issues, index),
            }
        )
    stats.wall_s = time.perf_counter() - t0
    return rows, stats, impl


# ── 집계 · 튜닝 ──────────────────────────────────────────────────────────


def aggregate(issues: Iterable[dict[str, Any]], cfg: AggConfig) -> list[str]:
    """문장별 지적 → 리뷰 단위 코드(정렬). 극성·신뢰도 하한을 통과한 지적이 min_count개 이상인 코드만."""
    cnt: Counter = Counter()
    for it in issues:
        if it["code"] in REVIEW_CODES and it["pol"] in cfg.polarities and float(it["conf"]) >= cfg.min_confidence:
            cnt[it["code"]] += 1
    return sorted(c for c, n in cnt.items() if n >= cfg.min_count)


def predictions(raw_rows: Sequence[dict[str, Any]], cfg: AggConfig) -> list[dict[str, Any]]:
    return [
        {
            "review_id": r["review_id"],
            "risk_codes": aggregate(r["issues"], cfg),
            "generator": r["generator"],
            "status": r["status"],
            "model": r.get("model"),
            "agg": cfg.as_dict(),
        }
        for r in raw_rows
    ]


def score_config(raw_rows: Sequence[dict[str, Any]], labels: dict[str, frozenset[str]], cfg: AggConfig) -> dict[str, Any]:
    by_id = {r["review_id"]: r for r in raw_rows}
    ids = sorted(labels)
    missing = [rid for rid in ids if rid not in by_id]
    if missing:
        raise ValueError(f"raw에 없는 dev 리뷰 {len(missing)}건")
    gold = [labels[rid] for rid in ids]
    pred = [frozenset(aggregate(by_id[rid]["issues"], cfg)) for rid in ids]
    res = multilabel_scores(gold, pred)
    return {
        "config": cfg.as_dict(),
        "macro_f1": res["macro_f1"],
        "micro_f1": res["micro_f1"],
        "per_class_f1": {c: round(v["f1"], 4) for c, v in res["per_class"].items() if v["scored"]},
        "n": res["n"],
    }


def select_config(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """사전 고정 선택 규칙: Macro 최대, 동률(1e-9)이면 격자 순서에서 앞선 것."""
    best = None
    for r in results:
        if r["macro_f1"] is None:
            continue
        if best is None or r["macro_f1"] > best["macro_f1"] + 1e-9:
            best = r
    if best is None:
        raise ValueError("정의된 Macro-F1이 없다")
    return best


def tune(raw_rows: Sequence[dict[str, Any]], labels: dict[str, frozenset[str]]) -> dict[str, Any]:
    results = [score_config(raw_rows, labels, cfg) for cfg in grid()]
    best = select_config(results)
    return {"grid": results, "selected": best, "selection_rule": SELECTION_RULE, "n_configs": len(results)}


# ── 입출력 ───────────────────────────────────────────────────────────────


def _data_dir() -> Path:
    d = os.environ.get("NEUMANN_DATA_DIR")
    if not d:
        raise SystemExit("NEUMANN_DATA_DIR가 없다")
    return Path(d)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def cmd_extract(args: argparse.Namespace) -> int:
    ev = _data_dir() / "eval"
    src = ev / f"disapere_{args.split}.jsonl"
    docs = load_docs(src)
    if args.limit:
        docs = docs[: args.limit]
    wrong = [d.review_id for d in docs if d.role != args.split]
    if wrong:
        raise SystemExit(f"{src}: role이 {args.split}가 아닌 행 {len(wrong)}건")
    meta: dict[str, Any] = {"split": args.split, "generator": args.generator, "source": str(src), "source_sha256": _sha(src),
                            "started_at": _now()}
    if args.generator == "rule":
        rows, stats, impl = extract_rule(docs)
        meta["rule_impl"] = impl
    else:
        from neumann.analyze import extract as e3
        from neumann.llm import make_llm, task_options

        llm = make_llm(provider="openai" if args.generator == "astra" else "mock")
        fp = extractor_fingerprint()
        cache = _data_dir() / "cache" / "e5_disapere" / fp if args.generator == "astra" else None
        meta.update({"model": llm.model, "prompt_version": e3.PROMPT_VERSION, "extractor_fingerprint": fp,
                     "task_options": task_options(e3.TASK), "batch_size": e3.DEFAULT_BATCH, "parallel": args.parallel,
                     "cache_dir": str(cache) if cache else None})
        rows, stats = extract_astra(docs, llm, cache_dir=cache, parallel=args.parallel)
    meta["finished_at"] = _now()
    meta["stats"] = stats.as_dict()
    out = Path(args.out) if args.out else ev / f"raw_{args.generator}_{args.split}.jsonl"
    write_jsonl(out, rows)
    meta["raw_file"] = str(out)
    meta["raw_sha256"] = _sha(out)
    stats_path = out.with_suffix(".stats.json")
    stats_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gens = Counter(r["generator"] for r in rows)
    print(f"{args.generator} {args.split}: 리뷰 {len(rows)} · 문장 {stats.sentences} · generator {dict(gens)}")
    print(json.dumps(meta["stats"], ensure_ascii=False))
    print(f"raw: {out}\nstats: {stats_path}")
    return 0


def cmd_tune(args: argparse.Namespace) -> int:
    ev = _data_dir() / "eval"
    raw_path = Path(args.raw) if args.raw else ev / f"raw_{args.generator}_dev.jsonl"
    labels = load_dev_labels(ev / "disapere_dev.jsonl")
    raw = read_jsonl(raw_path)
    res = tune(raw, labels)
    res.update({"generator": args.generator, "raw_file": str(raw_path), "raw_sha256": _sha(raw_path), "created_at": _now()})
    out = Path(args.out) if args.out else ev / f"tune_{args.generator}_dev.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("극성                 신뢰도≥  문장≥   dev Macro   dev Micro")
    for r in res["grid"]:
        c = r["config"]
        print(f"{'+'.join(c['polarities']):<20} {c['min_confidence']:>6.2f} {c['min_count']:>5}   {r['macro_f1']:.4f}      {r['micro_f1']:.4f}")
    s = res["selected"]
    print(f"선택: {s['config']}  dev Macro {s['macro_f1']:.4f} · Micro {s['micro_f1']:.4f} · 클래스 {s['per_class_f1']}")
    print(f"결과: {out}")
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    ev = _data_dir() / "eval"
    frozen = FROZEN.get(args.generator)
    if frozen is None and not args.config:
        raise SystemExit(f"{args.generator}: 고정 집계 규칙(FROZEN)이 없다. dev 튜닝 후 커밋하고 부른다")
    cfg = AggConfig.from_dict(json.loads(args.config) if args.config else frozen)
    if args.config and args.split == "gold":
        raise SystemExit("골드 예측은 커밋된 FROZEN 규칙으로만 만든다(--config 금지)")
    raw_path = Path(args.raw) if args.raw else ev / f"raw_{args.generator}_{args.split}.jsonl"
    rows = predictions(read_jsonl(raw_path), cfg)
    out = Path(args.out) if args.out else ev / f"pred_{args.generator}_{args.split}.jsonl"
    write_jsonl(out, rows)
    print(f"예측 {len(rows)}건 → {out}  규칙 {cfg.as_dict()}  generator {dict(Counter(r['generator'] for r in rows))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="DISAPERE 지적 추출 예측(E5-L1b)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("extract", help="문장별 지적(raw) 만들기")
    p.add_argument("--split", choices=("dev", "gold"), required=True)
    p.add_argument("--generator", choices=("astra", "rule", "mock"), required=True)
    p.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    p.add_argument("--limit", type=int, default=0, help="앞에서 N건만(점검용)")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_extract)
    p = sub.add_parser("tune", help="dev에서 집계 규칙 고르기(골드 금지)")
    p.add_argument("--generator", choices=("astra", "rule", "mock"), required=True)
    p.add_argument("--raw", default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_tune)
    p = sub.add_parser("predict", help="raw + 고정 규칙 → 예측 JSONL")
    p.add_argument("--split", choices=("dev", "gold"), required=True)
    p.add_argument("--generator", choices=("astra", "rule", "mock"), required=True)
    p.add_argument("--raw", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--config", default=None, help="dev 점검용 집계 규칙 JSON(골드에는 못 씀)")
    p.set_defaults(fn=cmd_predict)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
