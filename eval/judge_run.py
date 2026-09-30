"""판정 실행기 — 모델 중립(계획서 §5.7). 같은 봉투를 Claude 서브에이전트와 `codex exec` 둘 다로 돌린다.

경로(판정을 시작하기 전에 하나를 정하고 섞지 않는다):
- Claude(기본): `briefs`가 판정자 J1·J2·J3의 지시문(봉투 파일 목록, 답 파일 경로, 금지 사항)을 쓴다.
  PM이 지시문 하나당 Claude Code 서브에이전트(Sonnet 5.5) 하나를 띄운다. 판정자끼리 서로의 답을 볼 수 없다.
- Codex 비상: `codex`가 같은 봉투를 `codex exec -m gpt-6-sol`(read-only, 빈 작업 폴더, 세션 저장 안 함, 답 스키마 강제)로
  판정자·봉투마다 따로 돌린다. 기본은 명령만 보여 준다(dry-run). 실제 실행은 `--execute`, PM 지시가 있을 때만.
그다음은 공통:
- `validate`: 답 파일 형식·누락 검사.
- `aggregate`: 위험별 3명 다수결(모두 다르면 B) → 짝 표로 시스템·조건·순위 복원 → 지표(backtest_metrics).

실행 순서(판정 단계):
    python -m eval.judge_run build                      # 위험 묶음 → 봉투 + 짝 표 + 사람 판정 꾸러미
    python -m eval.judge_run briefs --batch-size 10     # Claude 경로 지시문
    python -m eval.judge_run codex [--execute]          # Codex 비상 경로(기본 dry-run)
    python -m eval.judge_run validate
    python -m eval.judge_run aggregate [--human data/eval/judge/human/answers.csv]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from eval.backtest_common import (
    SEEDS,
    data_dir,
    eval_dir,
    load_corpus_view,
    read_json,
    read_jsonl,
    utf8_stdio,
    write_json,
)
from eval.judge_envelope import (
    ANSWER_FORMAT,
    ANSWER_SCHEMA,
    GRADES,
    MAX_REASON_CHARS,
    build_envelopes,
    human_answer_sheet,
    human_envelope,
    read_human_answers,
    render_markdown,
    save_envelopes,
)

JUDGES = ("J1", "J2", "J3")
# 판정에 넣는 위험 묶음(전체 실행 결과). --limit 시험 파일(.firstN)·mock 파일은 기본으로 넣지 않는다.
DEFAULT_RISKSET_FILES = ("riskset_neumann.jsonl", "riskset_baseline_llm.jsonl")
CODEX_MODEL = "gpt-6-sol"
CODEX_EFFORT = "high"
PLACEHOLDER = re.compile(r"^<.*>$")


def paths(base: Path | None = None) -> dict[str, Path]:
    e = Path(base) if base else eval_dir()
    j = e / "judge"
    return {
        "eval": e,
        "judge": j,
        "envelopes": j / "envelopes",
        "answers": j / "answers",
        "briefs": j / "briefs",
        "codex_prompts": j / "codex_prompts",
        "codex_work": j / "codex_work",
        "human": j / "human",
        "key": e / "judge_key" / "pairing.json",  # 봉투 폴더 밖
        "results": e / "judge_results.json",
    }


# ── 봉투 만들기 ──────────────────────────────────────────────────────────


def build(base: Path | None = None, riskset_files: list[Path] | None = None) -> dict[str, Any]:
    P = paths(base)
    sample = read_json(P["eval"] / "backtest_sample.json")
    plans = {r["work_id"]: r for r in read_jsonl(P["eval"] / "backtest_plans.jsonl")}
    view = load_corpus_view(data_dir())
    reviews = {it["work_id"]: [r.text for r in view.reviews_for(it["work_id"])] for it in sample["items"]}
    files = riskset_files or [P["eval"] / f for f in DEFAULT_RISKSET_FILES]
    missing = [str(f) for f in files if not Path(f).is_file()]
    if missing:
        raise FileNotFoundError(f"위험 묶음 파일이 없다: {missing}")
    rows = [r for f in files for r in read_jsonl(f)]
    envs, key = build_envelopes(sample, plans, reviews, rows)
    key["riskset_files"] = [str(f) for f in files]
    manifest = save_envelopes(envs, key, P["envelopes"], P["key"])
    # 사람 판정 꾸러미: 진짜 조건 위험만, 10편
    human_ids = set(sample.get("human_sample", []))
    henvs = [human_envelope(e, key) for e in envs if key["envelopes"][e["envelope_id"]]["work_id"] in human_ids]
    P["human"].mkdir(parents=True, exist_ok=True)
    for e in henvs:
        (P["human"] / f"{e['envelope_id']}.md").write_text(render_markdown(e), encoding="utf-8")
        write_json(P["human"] / f"{e['envelope_id']}.json", e)
    (P["human"] / "answers_template.csv").write_text(human_answer_sheet(henvs), encoding="utf-8")
    return {"envelopes": manifest["n"], "risks": manifest["n_risks"], "human_envelopes": len(henvs), "riskset_files": [str(f) for f in files]}


def load_envelopes(base: Path | None = None) -> dict[str, dict[str, Any]]:
    P = paths(base)
    man = read_json(P["envelopes"] / "manifest.json")
    return {e["envelope_id"]: read_json(P["envelopes"] / e["file"]) for e in man["envelopes"]}


# ── Claude 경로: 서브에이전트 지시문 ──────────────────────────────────────


def claude_briefs(envelope_ids: list[str], P: dict[str, Path], judges: tuple[str, ...] = JUDGES, batch_size: int = 10,
                  seed: int = SEEDS["envelope"]) -> dict[str, str]:
    """판정자·묶음마다 지시문 {파일 이름: 내용}. 판정자마다 봉투 순서를 따로 섞는다."""
    out = {}
    for j in judges:
        order = sorted(envelope_ids)
        random.Random(f"{seed}|{j}").shuffle(order)
        batches = [order[i:i + batch_size] for i in range(0, len(order), batch_size)] or [[]]
        for b, ids in enumerate(batches, 1):
            ans_dir = P["answers"] / j
            lines = [
                f"# 판정자 {j} — 묶음 {b}/{len(batches)} (봉투 {len(ids)}개)",
                "",
                f"너는 독립 판정자 {j}다. 다른 판정자가 따로 같은 봉투를 판정하지만, 너는 그 결과를 볼 수 없고 보려 하지 않는다.",
                "",
                "## 할 일",
                "",
                "아래 봉투 파일을 하나씩 읽는다. 봉투의 `task`와 `rubric`대로 위험마다 A·B·C를 판정하고,",
                "봉투의 `answer_template`과 같은 모양의 답 JSON을 봉투마다 파일 하나로 쓴다(UTF-8).",
                f"- `judge_id`는 \"{j}\", `judge_model`은 너의 실제 모델 id(예: claude-sonnet-5-5)로 적는다.",
                "- 모든 risk_id를 한 번씩 빠짐없이 판정한다. reason은 한국어 한 줄(200자 이내).",
                "",
                "## 봉투 → 답 파일",
                "",
            ]
            for e in ids:
                lines.append(f"- 읽기 `{(P['envelopes'] / f'{e}.json').as_posix()}` → 쓰기 `{(ans_dir / f'{e}.json').as_posix()}`")
            lines += [
                "",
                "## 금지",
                "",
                "- 위 목록 밖의 파일을 읽지 않는다: 다른 판정자의 답 폴더, 짝 표(`judge_key`), 목록에 없는 봉투, 저장소 코드, 위험 묶음 파일.",
                "- 웹 검색·외부 도구로 논문이나 심사평을 찾지 않는다. 명령을 실행하지 않는다(파일 읽기·쓰기만).",
                "- 하위 에이전트를 띄우지 않는다. 답 파일 말고는 아무것도 쓰지 않는다.",
                "",
                "끝나면 쓴 답 파일 수와, 판정하기 어려웠던 위험이 있으면 봉투 id·risk_id만 한 줄씩 보고한다(등급 분포는 보고하지 않는다).",
            ]
            out[f"{j}_b{b}.md"] = "\n".join(lines) + "\n"
    return out


# ── Codex 비상 경로 ──────────────────────────────────────────────────────


def find_codex() -> str | None:
    """%LOCALAPPDATA%\\OpenAI\\Codex\\bin 아래 최신 codex.exe(계획서 §5.6). 없으면 PATH의 codex."""
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    if root.is_dir():
        exes = sorted(root.rglob("codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
        if exes:
            return str(exes[0])
    from shutil import which

    return which("codex")


def codex_schema() -> dict[str, Any]:
    """`--output-schema`용: strict 호환(const 대신 enum)."""
    s = json.loads(json.dumps(ANSWER_SCHEMA))
    s["properties"]["format"] = {"type": "string", "enum": [ANSWER_FORMAT]}
    s["properties"]["judgments"]["items"]["properties"]["grade"] = {"type": "string", "enum": list(GRADES)}
    return s


def codex_prompt(env: dict[str, Any], judge: str, model: str = CODEX_MODEL) -> str:
    return (
        f"{env['task']}\n\n"
        f"너는 독립 판정자 {judge}다. 파일을 읽거나 명령을 실행하지 말고, 아래 봉투 내용만 보고 판정한다.\n"
        f"답의 judge_id는 \"{judge}\", judge_model은 \"{model}\"로 적는다.\n"
        "마지막 메시지는 answer_template 모양의 JSON 객체 하나만 쓴다(설명·코드 블록 없이).\n\n"
        "봉투:\n" + json.dumps(env, ensure_ascii=False, indent=1) + "\n"
    )


def codex_command(codex: str, *, workdir: Path, schema_path: Path, out_path: Path, model: str = CODEX_MODEL,
                  effort: str = CODEX_EFFORT) -> list[str]:
    """판정자·봉투 하나의 codex exec 명령(프롬프트는 stdin '-')."""
    return [
        codex, "exec",
        "-m", model,
        "-c", f'model_reasoning_effort="{effort}"',
        "-s", "read-only",
        "-C", str(workdir),
        "--skip-git-repo-check",
        "--ephemeral",
        "--output-schema", str(schema_path),
        "-o", str(out_path),
        "-",
    ]


def extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


def codex_jobs(envs: dict[str, dict[str, Any]], P: dict[str, Path], judges: tuple[str, ...] = JUDGES,
               codex: str = "codex", model: str = CODEX_MODEL, effort: str = CODEX_EFFORT) -> list[dict[str, Any]]:
    """(판정자, 봉투)마다 프롬프트 파일·명령·답 경로. 파일은 아직 쓰지 않는다."""
    schema_path = P["codex_prompts"] / "answer_schema.json"
    jobs = []
    for j in judges:
        for e in sorted(envs):
            raw = P["answers"] / j / f"{e}.codex_last.txt"
            jobs.append({
                "judge": j,
                "envelope_id": e,
                "prompt_path": P["codex_prompts"] / j / f"{e}.txt",
                "prompt": codex_prompt(envs[e], j, model),
                "raw_path": raw,
                "answer_path": P["answers"] / j / f"{e}.json",
                "cmd": codex_command(codex, workdir=P["codex_work"] / j, schema_path=schema_path, out_path=raw,
                                     model=model, effort=effort),
            })
    return jobs


def run_codex(jobs: list[dict[str, Any]], P: dict[str, Path], *, execute: bool = False, workers: int = 3,
              runner: Callable[..., Any] = subprocess.run, timeout_s: int = 900) -> list[dict[str, Any]]:
    """Codex 판정 실행. execute=False면 명령만 돌려준다. 이미 답이 있는 (판정자, 봉투)는 건너뛴다."""
    schema_path = P["codex_prompts"] / "answer_schema.json"
    write_json(schema_path, codex_schema())
    for j in {job["judge"] for job in jobs}:
        (P["codex_work"] / j).mkdir(parents=True, exist_ok=True)  # 빈 작업 폴더(판정자마다)
    for job in jobs:
        job["prompt_path"].parent.mkdir(parents=True, exist_ok=True)
        job["prompt_path"].write_text(job["prompt"], encoding="utf-8")
    if not execute:
        return [{"judge": j["judge"], "envelope_id": j["envelope_id"], "status": "dry-run", "cmd": j["cmd"]} for j in jobs]

    def one(job: dict[str, Any]) -> dict[str, Any]:
        base = {"judge": job["judge"], "envelope_id": job["envelope_id"]}
        if job["answer_path"].is_file():
            return {**base, "status": "skip(있음)"}
        job["raw_path"].parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = runner(job["cmd"], input=job["prompt"], text=True, encoding="utf-8", capture_output=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {**base, "status": "timeout"}
        if getattr(proc, "returncode", 1) != 0:
            return {**base, "status": f"exit {proc.returncode}"}
        raw = job["raw_path"].read_text(encoding="utf-8") if job["raw_path"].is_file() else ""
        ans = extract_json(raw)
        if ans is None:
            return {**base, "status": "json 없음"}
        ans["judge_id"] = job["judge"]
        if not ans.get("judge_model") or PLACEHOLDER.match(str(ans.get("judge_model"))):
            ans["judge_model"] = CODEX_MODEL
        write_json(job["answer_path"], ans)
        return {**base, "status": "ok"}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(one, jobs))


# ── 답 검증·다수결·복원 ──────────────────────────────────────────────────


def validate_answer(ans: Any, env: dict[str, Any], judge: str | None = None) -> tuple[list[str], list[str]]:
    """(오류, 경고). 오류가 있으면 그 답은 집계에 쓰지 않는다."""
    errs: list[str] = []
    warns: list[str] = []
    if not isinstance(ans, dict):
        return ["JSON 객체가 아니다"], warns
    if ans.get("format") != ANSWER_FORMAT:
        errs.append(f"format {ans.get('format')!r}")
    if ans.get("envelope_id") != env["envelope_id"]:
        errs.append(f"envelope_id {ans.get('envelope_id')!r} != {env['envelope_id']}")
    if judge and ans.get("judge_id") != judge:
        errs.append(f"judge_id {ans.get('judge_id')!r} != {judge}")
    jm = str(ans.get("judge_model") or "")
    if not jm or PLACEHOLDER.match(jm):
        errs.append("judge_model 없음")
    want = [r["risk_id"] for r in env["risks"]]
    n_rev = len(env["reviews"])
    seen: Counter = Counter()
    for x in ans.get("judgments") or []:
        if not isinstance(x, dict):
            errs.append("판정 항목이 객체가 아니다")
            continue
        rid = x.get("risk_id")
        seen[rid] += 1
        if rid not in want:
            errs.append(f"없는 risk_id {rid!r}")
        if x.get("grade") not in GRADES:
            errs.append(f"{rid}: 등급 {x.get('grade')!r}")
        reason = str(x.get("reason") or "")
        if not reason.strip() or PLACEHOLDER.match(reason.strip()):
            errs.append(f"{rid}: 이유 없음")
        elif "\n" in reason.strip():
            errs.append(f"{rid}: 이유가 한 줄이 아니다")
        elif len(reason) > MAX_REASON_CHARS:
            warns.append(f"{rid}: 이유 {len(reason)}자 > {MAX_REASON_CHARS}")
        rn = x.get("review_no")
        if rn is not None and (not isinstance(rn, int) or isinstance(rn, bool) or not 1 <= rn <= n_rev):
            errs.append(f"{rid}: review_no {rn!r}(1~{n_rev})")
        if x.get("grade") == "A" and rn is None:
            warns.append(f"{rid}: A인데 review_no 없음")
    missing = [r for r in want if seen[r] == 0]
    dup = [r for r, c in seen.items() if c > 1]
    if missing:
        errs.append(f"누락 {missing}")
    if dup:
        errs.append(f"중복 {dup}")
    return errs, warns


def load_answers(envs: dict[str, dict[str, Any]], P: dict[str, Path], judges: tuple[str, ...] = JUDGES) -> tuple[dict[str, dict[str, dict]], dict[str, Any]]:
    """답 파일 → {judge: {envelope_id: answer}}(오류 없는 것만)와 검사 보고."""
    good: dict[str, dict[str, dict]] = {j: {} for j in judges}
    report: dict[str, Any] = {"missing": [], "invalid": {}, "warnings": {}, "valid": 0, "expected": len(envs) * len(judges)}
    for j in judges:
        for e, env in sorted(envs.items()):
            f = P["answers"] / j / f"{e}.json"
            if not f.is_file():
                report["missing"].append(f"{j}/{e}")
                continue
            try:
                ans = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                report["invalid"][f"{j}/{e}"] = [f"JSON 파싱 실패: {exc.msg}"]
                continue
            errs, warns = validate_answer(ans, env, j)
            if warns:
                report["warnings"][f"{j}/{e}"] = warns
            if errs:
                report["invalid"][f"{j}/{e}"] = errs
            else:
                good[j][e] = ans
                report["valid"] += 1
    report["complete"] = report["valid"] == report["expected"]
    return good, report


def majority(votes: list[str]) -> str:
    """3명 다수결. 2명 이상 같으면 그 등급, 3명이 모두 다르면 B(§0.5)."""
    if len(votes) != 3:
        raise ValueError(f"판정 {len(votes)}개(3개여야 한다)")
    grade, n = Counter(votes).most_common(1)[0]
    return grade if n >= 2 else "B"


def aggregate(envs: dict[str, dict[str, Any]], key: dict[str, Any], answers: dict[str, dict[str, dict]],
              judges: tuple[str, ...] = JUDGES) -> dict[str, Any]:
    """다수결 → 짝 표로 복원. 3명 답이 다 있는 봉투만 집계하고, 모자란 봉투는 목록으로 돌려준다."""
    per_risk: dict[tuple[str, str], dict[str, Any]] = {}
    incomplete = []
    for e, env in sorted(envs.items()):
        if not all(e in answers.get(j, {}) for j in judges):
            incomplete.append(e)
            continue
        votes_by_risk = {j: {x["risk_id"]: x["grade"] for x in answers[j][e]["judgments"]} for j in judges}
        for r in env["risks"]:
            votes = [votes_by_risk[j][r["risk_id"]] for j in judges]
            per_risk[(e, r["risk_id"])] = {"votes": votes, "grade": majority(votes)}
    # 짝 표로 복원: (system, condition, work_id) → 순위별 등급
    graded: dict[tuple[str, str, str], dict[str, Any]] = {}
    for rs in key["risksets"]:
        graded[(rs["system"], rs["condition"], rs["work_id"])] = {
            "system": rs["system"], "condition": rs["condition"], "work_id": rs["work_id"],
            "plan_work_id": rs["plan_work_id"], "status": rs["status"], "n_risks": rs["n_risks"],
            "grades": [None, None, None], "votes": [None, None, None],
            "evidence_ok": (rs["evidence_ok"] + [False, False, False])[:3], "judged": False,
        }
    for e, meta in key["envelopes"].items():
        if e in incomplete or e not in envs:
            continue
        for rid, m in meta["risks"].items():
            g = graded[(m["system"], m["condition"], meta["work_id"])]
            pr = per_risk[(e, rid)]
            g["grades"][m["rank"] - 1] = pr["grade"]
            g["votes"][m["rank"] - 1] = pr["votes"]
            g["judged"] = True
        for g in graded.values():
            if g["work_id"] == meta["work_id"] and g["n_risks"] == 0:
                g["judged"] = True  # 위험 0개(시스템 실패)도 판정 대상 논문이면 적중 0으로 센다
    ai_grades = {f"{e}/{rid}": v["grade"] for (e, rid), v in per_risk.items()}
    return {"graded": sorted(graded.values(), key=lambda g: (g["system"], g["condition"], g["work_id"])),
            "ai_grades": ai_grades, "incomplete_envelopes": incomplete,
            "judge_pairwise_agreement": pairwise_agreement(per_risk, judges)}


def pairwise_agreement(per_risk: dict[tuple[str, str], dict[str, Any]], judges: tuple[str, ...]) -> dict[str, Any]:
    out = {}
    for a in range(len(judges)):
        for b in range(a + 1, len(judges)):
            pairs = [(v["votes"][a], v["votes"][b]) for v in per_risk.values()]
            out[f"{judges[a]}-{judges[b]}"] = round(sum(x == y for x, y in pairs) / len(pairs), 4) if pairs else None
    all3 = [len(set(v["votes"])) == 1 for v in per_risk.values()]
    out["all_three_agree"] = round(sum(all3) / len(all3), 4) if all3 else None
    out["all_three_differ"] = sum(1 for v in per_risk.values() if len(set(v["votes"])) == 3)
    out["n_risks"] = len(per_risk)
    return out


# ── CLI ─────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(description="판정 실행기(모델 중립: Claude 서브에이전트 / Codex 비상)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="위험 묶음 → 봉투·짝 표·사람 판정 꾸러미")
    b.add_argument("--risksets", nargs="*", type=Path, default=None,
                   help="기본 data/eval/riskset_neumann.jsonl + riskset_baseline_llm.jsonl")
    br = sub.add_parser("briefs", help="Claude 경로: 판정자 지시문")
    br.add_argument("--batch-size", type=int, default=10)
    cx = sub.add_parser("codex", help="Codex 비상 경로(gpt-6-sol). 기본 dry-run")
    cx.add_argument("--execute", action="store_true", help="실제 실행(PM 지시가 있을 때만)")
    cx.add_argument("--workers", type=int, default=3)
    cx.add_argument("--model", default=CODEX_MODEL)
    cx.add_argument("--effort", default=CODEX_EFFORT)
    cx.add_argument("--judges", default=",".join(JUDGES))
    cx.add_argument("--envelopes", default=None, help="쉼표로 봉투 id 일부만")
    sub.add_parser("validate", help="답 파일 형식·누락 검사")
    ag = sub.add_parser("aggregate", help="다수결 → 복원 → 지표")
    ag.add_argument("--human", type=Path, default=None, help="대표 판정 CSV(answers_template.csv를 채운 것)")
    ag.add_argument("--work-ids", default=None, help="축소 표본 등: 'reduced'면 앞 15편")
    args = ap.parse_args(argv)
    P = paths()

    if args.cmd == "build":
        res = build(riskset_files=args.risksets)
        print(f"봉투 {res['envelopes']}개 · 위험 {res['risks']}개 · 사람 판정 봉투 {res['human_envelopes']}개")
        print(f"위험 묶음 파일 {res['riskset_files']}")
        print(f"봉투 {P['envelopes']} · 짝 표 {P['key']} · 사람 {P['human']}")
        return 0

    envs = load_envelopes()
    if args.cmd == "briefs":
        briefs = claude_briefs(list(envs), P, batch_size=args.batch_size)
        P["briefs"].mkdir(parents=True, exist_ok=True)
        for name, text in briefs.items():
            (P["briefs"] / name).write_text(text, encoding="utf-8")
        print(f"지시문 {len(briefs)}개 → {P['briefs']}")
        for name in briefs:
            print(f"  {(P['briefs'] / name).as_posix()}")
        print("PM: 지시문 하나당 Claude Code 서브에이전트(Sonnet 5.5) 하나. 판정자 J1·J2·J3는 서로 다른 세션으로.")
        return 0

    if args.cmd == "codex":
        codex = find_codex() or "codex"
        judges = tuple(j.strip() for j in args.judges.split(",") if j.strip())
        sel = {e: v for e, v in envs.items() if not args.envelopes or e in args.envelopes.split(",")}
        jobs = codex_jobs(sel, P, judges, codex=codex, model=args.model, effort=args.effort)
        res = run_codex(jobs, P, execute=args.execute, workers=args.workers)
        print(f"codex {codex} · 모델 {args.model} · 추론 {args.effort} · 작업 {len(jobs)}개 · {'실행' if args.execute else 'dry-run'}")
        if not args.execute and jobs:
            j0 = jobs[0]
            print("예(PowerShell):")
            print(f"  Get-Content \"{j0['prompt_path']}\" -Raw | & \"{codex}\" " + " ".join(
                f'"{c}"' if (" " in c or "=" in c) else c for c in j0["cmd"][1:]))
        print(dict(Counter(r["status"] for r in res)))
        return 0

    good, report = load_answers(envs, P)
    if args.cmd == "validate":
        print(f"답 {report['valid']}/{report['expected']} 통과 · 누락 {len(report['missing'])} · 오류 {len(report['invalid'])} · 경고 {len(report['warnings'])}")
        for k, v in list(report["invalid"].items())[:20]:
            print(f"  [오류] {k}: {v}")
        for k, v in list(report["warnings"].items())[:10]:
            print(f"  [경고] {k}: {v}")
        return 0 if report["complete"] else 1

    if args.cmd == "aggregate":
        from eval.backtest_metrics import compute_metrics, human_agreement

        key = read_json(P["key"])
        agg = aggregate(envs, key, good)
        sample = read_json(P["eval"] / "backtest_sample.json")
        work_ids = None
        if args.work_ids == "reduced":
            work_ids = [it["work_id"] for it in sample["items"][: sample["reduced_n"]]]
        elif args.work_ids:
            work_ids = args.work_ids.split(",")
        metrics = compute_metrics(agg["graded"], work_ids=work_ids)
        out = {"validation": {k: report[k] for k in ("valid", "expected", "complete")} | {"missing": report["missing"]},
               "incomplete_envelopes": agg["incomplete_envelopes"], "judge_agreement": agg["judge_pairwise_agreement"],
               "metrics": metrics, "graded": agg["graded"]}
        if args.human:
            human = read_human_answers(args.human)
            ai = {tuple(k.split("/")): v for k, v in agg["ai_grades"].items()}
            out["human_agreement"] = human_agreement(human, ai)
        sha = write_json(P["results"], out)
        print(json.dumps(out["metrics"]["summary"], ensure_ascii=False, indent=1))
        if "human_agreement" in out:
            print(json.dumps(out["human_agreement"], ensure_ascii=False, indent=1))
        print(f"sha256 {sha} → {P['results']}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
