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

축소 실행(n=5, 진짜 조건만, 21:0x 결정): 모든 하위 명령에 같은 `--judge-dir judge_n5`를 준다.
    python -m eval.judge_run build --judge-dir judge_n5 --work-ids first5 --conditions real \
        --risksets data/eval/riskset_neumann.sol.first5.jsonl data/eval/riskset_baseline_llm.sol.first5.jsonl
- 판정 폴더 `<eval>/<이름>/`(봉투·답·지시문·사람 꾸러미), 짝 표 `<eval>/<이름>_key/pairing.json`(판정 폴더 밖),
  결과 `<eval>/<이름>_results.json`·`.md`. 기본 이름 `judge`는 옛 경로 그대로다.
- `--work-ids first5`: 사전 등록 표본(list_sha256 확인)의 앞 5편. 봉투·사람 꾸러미·지표가 모두 이 5편이다(짝 표에 남아
  aggregate가 그대로 쓴다).
- 셔플 행이 없으면 특이성은 "측정 못 함"으로, 결과·표에 "셔플 대조 없음"을 적는다. 위험 0개·degraded 행은 빼지 않는다.
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
    canonical_sha256,
    data_dir,
    eval_dir,
    file_sha256,
    load_corpus_view,
    read_json,
    read_jsonl,
    utf8_stdio,
    write_json,
)
from eval.backtest_metrics import NO_SHUFFLE_NOTE
from eval.backtest_riskset import FORMAT as RISKSET_FORMAT
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
DEFAULT_JUDGE_DIR = "judge"
CODEX_MODEL = "gpt-6-sol"
CODEX_EFFORT = "high"
PLACEHOLDER = re.compile(r"^<.*>$")
_FIRST_N = re.compile(r"^first(\d+)$")
_ENV_FILE = re.compile(r"^env_[0-9a-f]{12}\.(?:json|md)$")


def resolve_judge_dir(judge_dir: str | Path | None, e: Path) -> Path:
    """판정 폴더. 없으면 <eval>/judge(옛 경로). 이름만(구분자 없음)이면 <eval>/<이름>, 경로면 그대로."""
    if judge_dir is None or str(judge_dir) == "":
        return e / DEFAULT_JUDGE_DIR
    s = str(judge_dir)
    if Path(s).is_absolute() or "/" in s or "\\" in s:
        return Path(s)
    return e / s


def paths(base: Path | None = None, judge_dir: str | Path | None = None) -> dict[str, Path]:
    """판정 폴더 배치. 짝 표·결과는 판정 폴더 밖(형제)에 둔다: <이름>_key/pairing.json, <이름>_results.json."""
    e = Path(base) if base else eval_dir()
    j = resolve_judge_dir(judge_dir, e)
    return {
        "eval": e,
        "judge": j,
        "envelopes": j / "envelopes",
        "answers": j / "answers",
        "briefs": j / "briefs",
        "codex_prompts": j / "codex_prompts",
        "codex_work": j / "codex_work",
        "human": j / "human",
        "key": j.parent / f"{j.name}_key" / "pairing.json",  # 판정 폴더 밖
        "results": j.parent / f"{j.name}_results.json",
        "results_md": j.parent / f"{j.name}_results.md",
    }


# ── 판정 논문 선택 ────────────────────────────────────────────────────────


def resolve_work_ids(spec: str | None, sample: dict[str, Any]) -> list[str] | None:
    """판정 논문 선택. None·'all' → None(표본 전체), 'reduced' → 앞 reduced_n편, 'firstN' → 앞 N편, 그 밖은 쉼표 목록.

    '앞 N편'은 사전 등록 순서에 기대므로, 표본 목록이 등록된 list_sha256과 같은지 먼저 확인한다."""
    items = [it["work_id"] for it in sample["items"]]
    registered = sample.get("list_sha256")
    if registered and canonical_sha256(items) != registered:
        raise ValueError("표본 목록이 사전 등록(list_sha256)과 다르다 — 앞 N편을 정할 수 없다")
    if spec is None or spec == "all":
        return None
    if spec == "reduced":
        return items[: int(sample["reduced_n"])]
    m = _FIRST_N.match(spec)
    if m:
        n = int(m.group(1))
        if not 1 <= n <= len(items):
            raise ValueError(f"{spec}: 표본은 {len(items)}편이다")
        return items[:n]
    ids = [x.strip() for x in spec.split(",") if x.strip()]
    unknown = [w for w in ids if w not in items]
    if unknown:
        raise ValueError(f"표본에 없는 논문 {unknown}")
    if len(set(ids)) != len(ids):
        raise ValueError("논문 목록에 중복이 있다")
    return ids


# ── 봉투 만들기 ──────────────────────────────────────────────────────────


def _guard_existing(P: dict[str, Path], new_key: dict[str, Any], *, force: bool) -> None:
    """이미 판정이 시작된 폴더나 다른 입력으로 만든 폴더를 덮지 않는다(옛 30편 판정 폴더 보호)."""
    if force:
        return
    answered = sorted(p.relative_to(P["answers"]).as_posix() for p in P["answers"].rglob("*.json")) if P["answers"].is_dir() else []
    if answered:
        raise FileExistsError(f"{P['judge']}에 판정 답이 이미 {len(answered)}개 있다(예 {answered[:2]}). "
                              "다른 --judge-dir을 쓰거나, 의도한 것이면 --force")
    if P["key"].is_file():
        old = read_json(P["key"])
        same = (old.get("riskset_sha256") == new_key.get("riskset_sha256") and old.get("work_ids") == new_key.get("work_ids")
                and old.get("conditions") == new_key.get("conditions"))
        if not same:
            raise FileExistsError(f"{P['judge']}는 다른 입력(위험 묶음·논문·조건)으로 만든 판정 폴더다. "
                                  "다른 --judge-dir을 쓰거나, 의도한 것이면 --force")


def _clear_stale(d: Path) -> None:
    if d.is_dir():
        for p in d.iterdir():
            if p.is_file() and (_ENV_FILE.match(p.name) or p.name in ("manifest.json", "answers_template.csv")):
                p.unlink()


def build_package(sample: dict[str, Any], plans: dict[str, dict[str, Any]], reviews: dict[str, list[str]],
                  rows: list[dict[str, Any]], P: dict[str, Path], *, work_ids: list[str] | None = None,
                  work_ids_spec: str | None = None, conditions: tuple[str, ...] | None = None,
                  allow_missing: bool = False, force: bool = False,
                  riskset_sha256: dict[str, str] | None = None) -> dict[str, Any]:
    """위험 묶음 행 → 봉투·짝 표·사람 판정 꾸러미(파일로 쓴다). 입력을 거르고 빈 칸을 검사한 뒤 만든다."""
    for r in rows:
        if r.get("format") != RISKSET_FORMAT:
            raise ValueError(f"위험 묶음 형식이 아니다: {r.get('format')!r}")
    sel = list(work_ids) if work_ids else [it["work_id"] for it in sample["items"]]
    sel_set = set(sel)
    dropped = {"condition": 0, "work": 0}
    kept = []
    for r in rows:
        if conditions and r["condition"] not in conditions:
            dropped["condition"] += 1
        elif r["work_id"] not in sel_set:
            dropped["work"] += 1
        else:
            kept.append(r)
    if not kept:
        raise ValueError("선택한 논문·조건에 위험 묶음이 없다")
    leaky = [f"{r['system']}/{r['condition']}/{r['work_id']}" for r in kept if (r.get("leak_check") or {}).get("leaks", 0) > 0]
    if leaky:  # 사전 고정: 누출이 0이 아닌 결과로는 판정하지 않는다(backtest_run_neumann 머리말)
        raise ValueError(f"누출 검사에 걸린 위험 묶음 {leaky}: 그 결과로는 판정하지 않는다")
    systems = sorted({r["system"] for r in kept})
    present = sorted({r["condition"] for r in kept})
    have = {(r["system"], r["condition"], r["work_id"]) for r in kept}
    missing = [f"{s}/{c}/{w}" for s in systems for c in present for w in sel if (s, c, w) not in have]
    if missing and not allow_missing:
        raise ValueError(f"선택한 논문에 위험 묶음이 없는 칸 {len(missing)}개: {missing[:6]} "
                         "(실행이 덜 끝났는지 확인. 알고 진행하려면 --allow-missing)")

    envs, key = build_envelopes(sample, plans, reviews, kept, work_ids=sel)
    key.update({
        "work_ids": sel,
        "work_ids_spec": work_ids_spec,
        "systems": systems,
        "conditions": present,
        "controls": {"shuffle": "shuffle" in present, "note": None if "shuffle" in present else NO_SHUFFLE_NOTE},
        "dropped_rows": dropped,
        "missing_risksets": missing,
        "riskset_sha256": dict(riskset_sha256 or {}),
    })
    _guard_existing(P, key, force=force)
    _clear_stale(P["envelopes"])
    _clear_stale(P["human"])
    manifest = save_envelopes(envs, key, P["envelopes"], P["key"])
    # 사람 판정 꾸러미: 진짜 조건 위험만. 논문 선택(--work-ids)이 있으면 그 논문 전부, 없으면 사전 고정 10편
    human_ids = sel_set if work_ids_spec else set(sample.get("human_sample", []))
    henvs = [human_envelope(e, key) for e in envs if key["envelopes"][e["envelope_id"]]["work_id"] in human_ids]
    henvs = [e for e in henvs if e["risks"]]
    P["human"].mkdir(parents=True, exist_ok=True)
    for e in henvs:
        (P["human"] / f"{e['envelope_id']}.md").write_text(render_markdown(e), encoding="utf-8")
        write_json(P["human"] / f"{e['envelope_id']}.json", e)
    (P["human"] / "answers_template.csv").write_text(human_answer_sheet(henvs), encoding="utf-8")
    (P["human"] / "README.md").write_text(human_readme(henvs), encoding="utf-8")
    by_sys: dict[str, dict[str, Any]] = {}
    for rs in key["risksets"]:
        d = by_sys.setdefault(f"{rs['system']}/{rs['condition']}", {"rows": 0, "risks": 0, "zero_risk_rows": 0, "status": Counter(),
                                                                    "generator": Counter(), "model": Counter()})
        d["rows"] += 1
        d["risks"] += rs["n_risks"]
        d["zero_risk_rows"] += rs["n_risks"] == 0
        d["status"][rs["status"]] += 1
        d["generator"][str(rs.get("generator"))] += 1
        d["model"][str(rs.get("model"))] += 1
    return {"envelopes": manifest["n"], "risks": manifest["n_risks"], "human_envelopes": len(henvs),
            "work_ids": sel, "systems": systems, "conditions": present, "controls": key["controls"],
            "dropped_rows": dropped, "missing_risksets": missing, "empty_works": key.get("empty_works", []),
            "by_system": {k: {kk: (dict(vv) if isinstance(vv, Counter) else vv) for kk, vv in v.items()} for k, v in by_sys.items()}}


def human_readme(henvs: list[dict[str, Any]]) -> str:
    """대표 블라인드 판정 안내(시스템 정보 없음)."""
    n = sum(len(e["risks"]) for e in henvs)
    lines = [
        "# 블라인드 판정 꾸러미",
        "",
        f"봉투 {len(henvs)}개(논문 {len(henvs)}편), 위험 {n}개. 봉투마다 `<봉투 id>.md`를 읽고 `answers_template.csv`를 채운다.",
        "",
        "- grade: A(적중: 실제 심사평에 같은 사안의 지적) · B(타당: 심사평엔 없지만 계획서에 맞음) · C(오탐: 무관하거나 틀림)",
        "- review_no: A일 때 그 지적이 있는 심사평 번호, 아니면 비운다",
        "- reason: 한 줄 이유",
        "",
        "위험은 여러 출처에서 모아 섞었다. 출처를 추측하지 말고 문장만 보고 판정한다. 판정이 끝날 때까지 AI 판정 답·결과 파일을 열지 않는다.",
        "채운 파일은 이 폴더에 `answers.csv`로 저장한다(UTF-8).",
    ]
    return "\n".join(lines) + "\n"


def build(base: Path | None = None, riskset_files: list[Path] | None = None, *, judge_dir: str | Path | None = None,
          work_ids_spec: str | None = None, conditions: tuple[str, ...] | None = None, allow_missing: bool = False,
          force: bool = False) -> dict[str, Any]:
    P = paths(base, judge_dir)
    sample = read_json(P["eval"] / "backtest_sample.json")
    work_ids = resolve_work_ids(work_ids_spec, sample)
    plans = {r["work_id"]: r for r in read_jsonl(P["eval"] / "backtest_plans.jsonl")}
    files = riskset_files or [P["eval"] / f for f in DEFAULT_RISKSET_FILES]
    missing = [str(f) for f in files if not Path(f).is_file()]
    if missing:
        raise FileNotFoundError(f"위험 묶음 파일이 없다: {missing}")
    targets = work_ids or [it["work_id"] for it in sample["items"]]
    view = load_corpus_view(data_dir())
    reviews = {w: [r.text for r in view.reviews_for(w)] for w in targets}
    rows = [r for f in files for r in read_jsonl(f)]
    res = build_package(sample, plans, reviews, rows, P, work_ids=work_ids, work_ids_spec=work_ids_spec,
                        conditions=conditions, allow_missing=allow_missing, force=force,
                        riskset_sha256={str(f): file_sha256(Path(f)) for f in files})
    res["riskset_files"] = [str(f) for f in files]
    return res


def load_envelopes(base: Path | None = None, judge_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    P = paths(base, judge_dir)
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
                f"- 위 목록 밖의 파일을 읽지 않는다: 다른 판정자의 답 폴더, 짝 표(`{P['key'].parent.name}`), 사람 판정 폴더(`human`), "
                f"결과 파일(`{P['results'].name}`), 목록에 없는 봉투, 저장소 코드, 위험 묶음 파일.",
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


def restore(key: dict[str, Any], grades: dict[tuple[str, str], str], complete: set[str], *,
            votes: dict[tuple[str, str], list[str]] | None = None,
            conditions: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """(봉투, 위험) 등급 → 짝 표로 (시스템, 조건, 논문)별 순위 등급. `complete` 봉투만 판정됨으로 센다.

    - 위험 0개 행(시스템 실패)은 그 논문 봉투가 판정됐으면 적중 0으로 센다(빼지 않는다).
    - 봉투가 없는 논문(모든 시스템 위험 0개, `empty_works`)은 판정할 것이 없으므로 모든 행을 적중 0으로 센다.
    - conditions를 주면 그 조건의 위험만 복원한다(사람 판정은 진짜 조건만)."""
    graded: dict[tuple[str, str, str], dict[str, Any]] = {}
    for rs in key["risksets"]:
        graded[(rs["system"], rs["condition"], rs["work_id"])] = {
            "system": rs["system"], "condition": rs["condition"], "work_id": rs["work_id"],
            "plan_work_id": rs["plan_work_id"], "status": rs["status"], "generator": rs.get("generator"),
            "model": rs.get("model"), "n_risks": rs["n_risks"],
            "grades": [None, None, None], "votes": [None, None, None],
            "evidence_ok": (rs["evidence_ok"] + [False, False, False])[:3], "judged": False,
        }
    use = (lambda c: c in conditions) if conditions else (lambda c: True)
    for e, meta in key["envelopes"].items():
        if e not in complete:
            continue
        for rid, m in meta["risks"].items():
            if not use(m["condition"]):
                continue
            g = graded[(m["system"], m["condition"], meta["work_id"])]
            g["grades"][m["rank"] - 1] = grades[(e, rid)]
            if votes is not None:
                g["votes"][m["rank"] - 1] = votes[(e, rid)]
            g["judged"] = True
        for g in graded.values():
            if g["work_id"] == meta["work_id"] and g["n_risks"] == 0 and use(g["condition"]):
                g["judged"] = True  # 위험 0개(시스템 실패)도 판정 대상 논문이면 적중 0으로 센다
    empty = set(key.get("empty_works", []))
    for g in graded.values():
        if g["work_id"] in empty and use(g["condition"]):
            g["judged"] = True
            g["no_envelope"] = True
    return sorted(graded.values(), key=lambda g: (g["system"], g["condition"], g["work_id"]))


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
    complete = set(envs) - set(incomplete)
    graded = restore(key, {k: v["grade"] for k, v in per_risk.items()}, complete,
                     votes={k: v["votes"] for k, v in per_risk.items()})
    ai_grades = {f"{e}/{rid}": v["grade"] for (e, rid), v in per_risk.items()}
    return {"graded": graded, "ai_grades": ai_grades, "incomplete_envelopes": incomplete,
            "judge_pairwise_agreement": pairwise_agreement(per_risk, judges)}


def human_graded(envs: dict[str, dict[str, Any]], key: dict[str, Any], human: dict[tuple[str, str], str],
                 condition: str = "real") -> tuple[list[dict[str, Any]], list[str]]:
    """대표 판정(진짜 조건 위험) → 같은 복원. (graded, 다 채우지 않은 봉투). 봉투의 진짜 조건 위험을 모두 채운 봉투만 센다."""
    complete, incomplete = set(), []
    for e, env in sorted(envs.items()):
        meta = key["envelopes"][e]["risks"]
        want = [r["risk_id"] for r in env["risks"] if meta[r["risk_id"]]["condition"] == condition]
        if not want:
            continue
        if all((e, rid) in human for rid in want):
            complete.add(e)
        else:
            incomplete.append(e)
    return restore(key, human, complete, conditions=(condition,)), incomplete


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
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--judge-dir", default=None,
                        help="판정 폴더(이름이면 data/eval/<이름>, 경로면 그대로). 기본 judge. n=5 실행은 judge_n5")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", parents=[common], help="위험 묶음 → 봉투·짝 표·사람 판정 꾸러미")
    b.add_argument("--risksets", nargs="*", type=Path, default=None,
                   help="기본 data/eval/riskset_neumann.jsonl + riskset_baseline_llm.jsonl")
    b.add_argument("--work-ids", default=None, help="'first5'(사전 등록 앞 5편)·'firstN'·'reduced'·쉼표 목록. 기본 표본 전체")
    b.add_argument("--conditions", default=None, help="'real'이면 진짜 조건만(셔플 행은 버리고 개수를 알린다). 기본 있는 그대로")
    b.add_argument("--allow-missing", action="store_true", help="선택 논문에 위험 묶음이 없는 칸이 있어도 진행")
    b.add_argument("--force", action="store_true", help="이미 판정이 시작됐거나 다른 입력으로 만든 폴더를 덮는다")
    br = sub.add_parser("briefs", parents=[common], help="Claude 경로: 판정자 지시문")
    br.add_argument("--batch-size", type=int, default=10)
    cx = sub.add_parser("codex", parents=[common], help="Codex 비상 경로(gpt-6-sol). 기본 dry-run")
    cx.add_argument("--execute", action="store_true", help="실제 실행(PM 지시가 있을 때만)")
    cx.add_argument("--workers", type=int, default=3)
    cx.add_argument("--model", default=CODEX_MODEL)
    cx.add_argument("--effort", default=CODEX_EFFORT)
    cx.add_argument("--judges", default=",".join(JUDGES))
    cx.add_argument("--envelopes", default=None, help="쉼표로 봉투 id 일부만")
    sub.add_parser("validate", parents=[common], help="답 파일 형식·누락 검사")
    ag = sub.add_parser("aggregate", parents=[common], help="다수결 → 복원 → 지표")
    ag.add_argument("--human", type=Path, default=None, help="대표 판정 CSV(answers_template.csv를 채운 것)")
    ag.add_argument("--work-ids", default=None,
                    help="지표에 쓸 논문. 기본은 build 때 고른 논문(짝 표). 'reduced'·'firstN'·쉼표 목록")
    args = ap.parse_args(argv)
    P = paths(judge_dir=args.judge_dir)

    if args.cmd == "build":
        conds = tuple(c.strip() for c in args.conditions.split(",") if c.strip()) if args.conditions else None
        try:
            res = build(riskset_files=args.risksets, judge_dir=args.judge_dir, work_ids_spec=args.work_ids,
                        conditions=conds, allow_missing=args.allow_missing, force=args.force)
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            print(f"[중단] {exc}")
            return 2
        print(f"봉투 {res['envelopes']}개 · 위험 {res['risks']}개 · 사람 판정 봉투 {res['human_envelopes']}개")
        print(f"논문 {len(res['work_ids'])}편 · 시스템 {res['systems']} · 조건 {res['conditions']}")
        for k, v in res["by_system"].items():
            print(f"  {k}: 행 {v['rows']} · 위험 {v['risks']} · 위험 0개 {v['zero_risk_rows']} · 상태 {v['status']} · "
                  f"생성 {v['generator']} · 모델 {v['model']}")
        models = {k.split("/")[0]: set(v["model"]) - {"None"} for k, v in res["by_system"].items()}
        if len({frozenset(v) for v in models.values() if v}) > 1:
            print(f"[경고] 시스템별 생성 모델이 다르다 {({k: sorted(v) for k, v in models.items()})} — 같은 모델이어야 하면 입력 파일을 확인")
        if not res["controls"]["shuffle"]:
            print(f"[알림] {NO_SHUFFLE_NOTE}")
        if any(res["dropped_rows"].values()):
            print(f"[알림] 버린 행: 조건 밖 {res['dropped_rows']['condition']} · 선택 논문 밖 {res['dropped_rows']['work']}")
        if res["missing_risksets"]:
            print(f"[경고] 위험 묶음이 없는 칸 {res['missing_risksets']}")
        if res["empty_works"]:
            print(f"[알림] 모든 시스템 위험 0개라 봉투를 만들지 않은 논문 {len(res['empty_works'])}편(지표는 적중 0)")
        print(f"위험 묶음 파일 {res['riskset_files']}")
        print(f"봉투 {P['envelopes']} · 짝 표 {P['key']} · 사람 {P['human']}")
        return 0

    envs = load_envelopes(judge_dir=args.judge_dir)
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
        from eval.judge_summary import render_results_md

        key = read_json(P["key"])
        agg = aggregate(envs, key, good)
        sample = read_json(P["eval"] / "backtest_sample.json")
        work_ids = resolve_work_ids(args.work_ids, sample) if args.work_ids else key.get("work_ids")
        metrics = compute_metrics(agg["graded"], work_ids=work_ids)
        out = {"validation": {k: report[k] for k in ("valid", "expected", "complete")} | {"missing": report["missing"]},
               "incomplete_envelopes": agg["incomplete_envelopes"], "judge_agreement": agg["judge_pairwise_agreement"],
               "judge_models": sorted({str(a.get("judge_model")) for j in good.values() for a in j.values()}),
               "run": {k: key.get(k) for k in ("work_ids", "work_ids_spec", "systems", "conditions", "controls",
                                              "empty_works", "missing_risksets", "riskset_sha256")},
               "metrics": metrics, "graded": agg["graded"]}
        if args.human:
            human = read_human_answers(args.human)
            ai = {tuple(k.split("/")): v for k, v in agg["ai_grades"].items()}
            out["human_agreement"] = human_agreement(human, ai)
            hg, h_incomplete = human_graded(envs, key, human)
            out["human_metrics"] = compute_metrics(hg, work_ids=work_ids)
            out["human_incomplete_envelopes"] = h_incomplete
        sha = write_json(P["results"], out)
        md = render_results_md(out)
        P["results_md"].write_text(md, encoding="utf-8")
        print(md)
        print(f"sha256 {sha} → {P['results']}")
        print(f"표 → {P['results_md']}")
        return 0 if report["complete"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
