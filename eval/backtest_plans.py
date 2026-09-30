r"""초록 → 계획서(드롭형 스크러빙, 04_평가_명세 §4.1, 부록/평가/05_eval_protocol §4.2 1·2단).

규칙(사전 고정, 2026-09-30):
- 계획서 = 초록에서 수치(NUM)·우월성(CLAIM)·실증(EVID) 표현이 하나라도 있는 문장을 **통째로 지운** 나머지.
  마스킹하지 않는다(마스킹은 "우리가 이겼다"는 문장 구조가 남는다). 정규식 3종은 05_eval_protocol §4.2 원문 그대로.
- 추가 규칙 URL: 링크가 있는 문장도 지운다(익명 코드 저장소 링크 등 논문 식별 정보). 드롭만 하므로 누출을 늘리지 않는다.
- 제목은 계획서에 넣지 않는다(논문 고유 식별 정보를 줄인다. 초록 속 기법 이름은 남는다).
- 문장 나누기 = `(?<=[.!?])\s+`(원문 그대로). 남은 문장을 공백 하나로 잇는다.
- 2단 자동 검사: 완성된 계획서 전체에 네 패턴을 다시 돌려 잔여 0이어야 한다. 0이 아니면 실패로 멈춘다.
- 400자 미만이 된 계획서는 `needs_manual_restore=true`로 표시만 한다(3단 사람 복구 대상. 이 코드는 복구하지 않는다).

실행:
    python -m eval.backtest_plans        # data/eval/backtest_sample.json → data/eval/backtest_plans.jsonl
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from eval.backtest_common import (
    data_dir,
    eval_dir,
    load_corpus_view,
    read_json,
    sha256_text,
    utf8_stdio,
    write_json,
    write_jsonl,
)

SCRUBBER_VERSION = "drop-v1(NUM,CLAIM,EVID,URL)"
MIN_PLAN_CHARS = 400

# 05_eval_protocol §4.2 원문 그대로(바꾸지 않는다).
NUM = re.compile(r'\b\d+(?:\.\d+)?\s?%|\b\d+\.\d+\b|\b\d+(?:\.\d+)?\s?(?:x|×)\b|\bp\s?<\s?0?\.\d+')
CLAIM = re.compile(r'\b(?:out[- ]?perform\w*|state[- ]of[- ]the[- ]art|SOTA|surpass\w*|superior\w*|'
                   r'outstrip\w*|beat\w*|exceed\w*|best[- ]performing|new\s+record|'
                   r'achiev\w*|improv\w*|boost\w*|gain\w*|effective\w*|efficien\w*|'
                   r'significant\w*|substantial\w*|consistent\w*\s+better|demonstrat\w*|'
                   r'validat\w*|verif\w*|confirm\w*|show[s]?\s+that|prove[sd]?)\b', re.I)
EVID = re.compile(r'\b(?:experiment\w*|evaluat\w*|result\w*|empiric\w*|benchmark\w*|ablation\w*|'
                  r'we\s+show|we\s+demonstrate|extensive\w*|comprehensive\s+(?:experiments|evaluation))\b', re.I)
# 추가 규칙(식별 정보): http(s) 링크, www., 익명 저장소 도메인
URL = re.compile(r'https?://\S+|\bwww\.\S+|\banonymous\.4open\.science\S*|\bgithub\.com/\S+', re.I)

PATTERNS: dict[str, re.Pattern[str]] = {"NUM": NUM, "CLAIM": CLAIM, "EVID": EVID, "URL": URL}
SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text) if s and s.strip()]


def sentence_hits(sentence: str) -> list[str]:
    return [name for name, pat in PATTERNS.items() if pat.search(sentence)]


def scrub_drop_only(text: str) -> tuple[str, list[dict[str, Any]]]:
    """(계획서 문자열, 지운 문장 목록[{text, hits}])."""
    kept: list[str] = []
    dropped: list[dict[str, Any]] = []
    for s in split_sentences(text):
        hits = sentence_hits(s)
        if hits:
            dropped.append({"text": s, "hits": hits})
        else:
            kept.append(s)
    return " ".join(kept), dropped


def residual_hits(plan_text: str) -> dict[str, int]:
    """2단 자동 검사: 계획서 전체에서 네 패턴의 잔여 매치 수. 전부 0이어야 한다."""
    return {name: len(pat.findall(plan_text)) for name, pat in PATTERNS.items()}


class ResidualPatternError(ValueError):
    """스크러빙 뒤 잔여 패턴이 남았다(2단 검사 실패)."""


def make_plan(work_id: str, abstract: str) -> dict[str, Any]:
    plan_text, dropped = scrub_drop_only(abstract)
    resid = residual_hits(plan_text)
    if any(resid.values()):
        raise ResidualPatternError(f"{work_id}: 잔여 패턴 {resid}")
    n_sent = len(split_sentences(abstract))
    return {
        "work_id": work_id,
        "plan_id": sha256_text(plan_text),
        "plan_text": plan_text,
        "chars": len(plan_text),
        "source_chars": len(abstract),
        "retention": round(len(plan_text) / len(abstract), 4) if abstract else 0.0,
        "sentences_total": n_sent,
        "sentences_kept": n_sent - len(dropped),
        "sentences_dropped": len(dropped),
        "drop_reasons": {name: sum(name in d["hits"] for d in dropped) for name in PATTERNS},
        "dropped": dropped,
        "residual_hits": resid,
        "residual_total": sum(resid.values()),
        "needs_manual_restore": len(plan_text) < MIN_PLAN_CHARS,
        "scrubber": SCRUBBER_VERSION,
    }


def build_plans(sample: dict[str, Any], view: Any) -> list[dict[str, Any]]:
    rows = []
    for it in sample["items"]:
        w = view.works[it["work_id"]]
        row = make_plan(it["work_id"], w.abstract or "")
        row["pos"] = it["pos"]
        row["abstract_sha256"] = sha256_text(w.abstract or "")
        rows.append(row)
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    short = [r["work_id"] for r in rows if r["needs_manual_restore"]]
    return {
        "n_plans": n,
        "scrubber": SCRUBBER_VERSION,
        "residual_total": sum(r["residual_total"] for r in rows),
        "plans_with_residual": sum(1 for r in rows if r["residual_total"]),
        "mean_chars": round(sum(r["chars"] for r in rows) / n, 1) if n else 0,
        "mean_retention": round(sum(r["retention"] for r in rows) / n, 4) if n else 0,
        "under_400": len(short),
        "under_400_work_ids": short,
        "empty_plans": sum(1 for r in rows if r["chars"] == 0),
        "drop_reasons_total": {k: sum(r["drop_reasons"][k] for r in rows) for k in PATTERNS},
    }


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(description="초록 → 계획서(드롭형 스크러빙, 잔여 0 검사)")
    ap.add_argument("--sample", type=Path, default=None, help="기본 data/eval/backtest_sample.json")
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None, help="기본 data/eval/backtest_plans.jsonl")
    args = ap.parse_args(argv)

    sample = read_json(args.sample or eval_dir() / "backtest_sample.json")
    view = load_corpus_view(args.data_dir or data_dir())
    rows = build_plans(sample, view)
    out = args.out or eval_dir() / "backtest_plans.jsonl"
    sha = write_jsonl(out, rows)
    summ = summarize(rows)
    summ.update({"plans_sha256": sha, "sample_list_sha256": sample["list_sha256"]})
    write_json(out.with_name("backtest_plans_summary.json"), summ)
    print(f"계획서 {summ['n_plans']}건 · 잔여 패턴 합계 {summ['residual_total']} · 빈 계획서 {summ['empty_plans']}")
    print(f"평균 {summ['mean_chars']}자 · 보존율 {summ['mean_retention']} · 400자 미만 {summ['under_400']}건(수동 복구 대상 표시)")
    print(f"지운 문장 사유 {summ['drop_reasons_total']}")
    print(f"plans_sha256 {sha} → {out}")
    for r in rows:
        flag = " ← 400자 미만" if r["needs_manual_restore"] else ""
        print(f"  {r['pos']:>2} {r['work_id']:<32} {r['chars']:>5}자 (원문 {r['source_chars']}) 남은 문장 {r['sentences_kept']}/{r['sentences_total']}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
