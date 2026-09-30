"""판정 경로 예행(mock 전용). 실제 판정이 아니고, 만든 값은 결과로 쓰지 않는다.

- `synth-neumann`: 논문마다 가짜 위험 3개인 Neumann 위험 묶음(generator `synthetic`, model `synthetic-rehearsal`).
  mock Neumann은 이 계획서들에서 카드 0장(degraded)이라 봉투·다수결·지표의 전체 경로를 못 태운다. 그 빈 곳을 채우는 용도다.
- `fake-answers`: 판정자 J1·J2·J3의 가짜 답(judge_model `mock-judge-rehearsal`). 등급은 봉투 안의 위험 글 해시로만 정한다
  (짝 표를 읽지 않는다 = 블라인드 조건 그대로). 판정자마다 일부 등급을 다르게 바꿔 다수결 2:1·모두 다름도 생긴다.

안전장치:
- 합성 위험 묶음은 `--out`을 꼭 받고 공유 `data/eval/` 바로 아래에는 쓰지 않는다.
- 가짜 답은 짝 표의 위험 묶음이 전부 예행 생성(`mock`·`synthetic`·`none`)일 때만 쓴다. 실제 생성(astra·rule 등)이 든
  판정 폴더에는 쓰지 않는다. 이미 답이 있으면 --force 없이 덮지 않는다.

    python -m eval.judge_rehearsal synth-neumann --work-ids first5 --out <임시>/riskset_neumann.synthetic.first5.jsonl [--degraded 1]
    python -m eval.judge_rehearsal fake-answers --judge-dir <임시 판정 폴더>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from eval.backtest_common import eval_dir, read_json, read_jsonl, utf8_stdio, write_json, write_jsonl
from eval.backtest_riskset import make_risk, make_riskset
from eval.judge_envelope import ANSWER_FORMAT

REHEARSAL_GENERATORS = frozenset({"mock", "synthetic", "none"})
FAKE_JUDGE_MODEL = "mock-judge-rehearsal"
SYNTH_MODEL = "synthetic-rehearsal"

# 계획서와 무관한 일반 위험 문장(예행용). 시스템 이름·코드·링크가 없어 블라인드 검사를 통과한다.
TEMPLATES = (
    ("평가 지표 선택 근거 부족", "비교 기준과 평가 지표를 고른 이유가 계획서에 없다."),
    ("기준선 비교 범위 부족", "최근 방법과의 비교가 빠져 있어 개선 폭을 판단하기 어렵다."),
    ("데이터 규모와 분할 불명확", "학습·검증·시험 분할과 데이터 규모가 적혀 있지 않다."),
    ("구성 요소별 기여 분석 없음", "제안한 모듈 하나씩을 뺀 비교 계획이 없다."),
    ("일반화 주장 과장 위험", "한 영역 결과로 넓은 적용성을 주장할 위험이 있다."),
    ("계산 비용 보고 누락", "학습·추론 비용을 기존 방법과 비교하는 계획이 없다."),
    ("재현성 정보 부족", "하이퍼파라미터 선택 절차와 시드 고정이 빠져 있다."),
    ("이론적 가정 검증 부족", "핵심 가정이 실제 데이터에서 성립하는지 확인하지 않는다."),
)


def _h(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def synth_neumann(work_ids: list[str], plans: dict[str, dict[str, Any]], *, degraded: int = 0) -> list[dict[str, Any]]:
    """논문마다 가짜 위험 3개. 근거 통과는 1·2순위만(근거율 경로 확인용). 뒤에서 `degraded`편은 status degraded로 둔다."""
    rows = []
    for i, w in enumerate(work_ids):
        picks: list[int] = []
        for k in range(len(TEMPLATES)):
            t = (_h(f"synth|{w}") + k * 3) % len(TEMPLATES)
            if t not in picks:
                picks.append(t)
            if len(picks) == 3:
                break
        risks = [make_risk(rank, TEMPLATES[t][0], TEMPLATES[t][1], evidence_ok=rank <= 2, n_evidence=1 if rank <= 2 else 0)
                 for rank, t in enumerate(picks, 1)]
        is_degraded = i >= len(work_ids) - degraded
        rows.append(make_riskset(
            system="neumann", condition="real", work_id=w, plan_work_id=w, plan_id=plans[w]["plan_id"], risks=risks,
            status="degraded" if is_degraded else "ok", generator="synthetic", model=SYNTH_MODEL,
            notes=["예행용 합성 위험(제품 출력 아님)"] + (["예행: degraded 표시 경로 확인용"] if is_degraded else []),
        ))
    return rows


def _grade(seed: str, judge: str, env_id: str, risk: dict[str, Any]) -> str:
    base = _h(f"{seed}|{env_id}|{risk['text']}") % 10
    g = "A" if base < 3 else ("B" if base < 7 else "C")
    if _h(f"{seed}|{judge}|{env_id}|{risk['risk_id']}") % 10 < 3:  # 판정자마다 30%는 다른 등급
        g = {"A": "B", "B": "C", "C": "A"}[g] if judge != "J2" else {"A": "C", "B": "A", "C": "B"}[g]
    return g


def check_rehearsal_key(key: dict[str, Any]) -> None:
    gens = {str(rs.get("generator")) for rs in key.get("risksets", [])}
    real = sorted(gens - REHEARSAL_GENERATORS)
    if real:
        raise PermissionError(f"실제 생성 위험 묶음(generator {real})이 든 판정 폴더에는 가짜 답을 쓰지 않는다")


def fake_answers(P: dict[str, Path], envs: dict[str, dict[str, Any]], key: dict[str, Any], *,
                 judges: tuple[str, ...] = ("J1", "J2", "J3"), seed: str = "rehearsal", force: bool = False) -> int:
    check_rehearsal_key(key)
    n = 0
    for j in judges:
        for e, env in sorted(envs.items()):
            path = P["answers"] / j / f"{e}.json"
            if path.exists() and not force:
                raise FileExistsError(f"답이 이미 있다: {path}(덮으려면 --force)")
            judg = []
            for r in env["risks"]:
                g = _grade(seed, j, e, r)
                judg.append({"risk_id": r["risk_id"], "grade": g, "review_no": 1 if g == "A" else None,
                             "reason": "예행용 가짜 판정(실제 판정 아님)"})
            write_json(path, {"format": ANSWER_FORMAT, "envelope_id": e, "judge_id": j, "judge_model": FAKE_JUDGE_MODEL,
                              "judgments": judg})
            n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    from eval import judge_run as jr

    ap = argparse.ArgumentParser(description="판정 경로 예행(mock 전용, 실제 판정 아님)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("synth-neumann", help="논문마다 가짜 위험 3개인 Neumann 위험 묶음")
    s.add_argument("--work-ids", default="first5")
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--degraded", type=int, default=0, help="뒤에서 N편을 status degraded로")
    f = sub.add_parser("fake-answers", help="J1·J2·J3 가짜 답(예행 판정 폴더에만)")
    f.add_argument("--judge-dir", required=True)
    f.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "synth-neumann":
        if args.out.resolve().parent == eval_dir().resolve():
            print(f"[중단] 공유 {eval_dir()} 바로 아래에는 합성 위험 묶음을 쓰지 않는다. 임시 폴더를 준다")
            return 2
        sample = read_json(eval_dir() / "backtest_sample.json")
        plans = {r["work_id"]: r for r in read_jsonl(eval_dir() / "backtest_plans.jsonl")}
        work_ids = jr.resolve_work_ids(args.work_ids, sample) or [it["work_id"] for it in sample["items"]]
        rows = synth_neumann(work_ids, plans, degraded=args.degraded)
        sha = write_jsonl(args.out, rows)
        print(f"합성 Neumann 위험 묶음 {len(rows)}건(예행용, degraded {args.degraded}) sha256 {sha} → {args.out}")
        return 0

    P = jr.paths(judge_dir=args.judge_dir)
    envs = jr.load_envelopes(judge_dir=args.judge_dir)
    key = read_json(P["key"])
    try:
        n = fake_answers(P, envs, key, force=args.force)
    except (PermissionError, FileExistsError) as exc:
        print(f"[중단] {exc}")
        return 2
    print(json.dumps({"fake_answers": n, "judge_model": FAKE_JUDGE_MODEL, "answers": str(P["answers"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
