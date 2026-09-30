"""Score existing local result JSONs, then optionally record human curation.

No analysis generation, network access, licence approval or sample text creation.
Usage (mock/live calls are not needed):
  python scripts/curate_samples.py score RESULT.json --output out/curation
  python scripts/curate_samples.py score RESULT.json --output out/curation --apply
  python scripts/curate_samples.py feature SAMPLE_ID --confirm-human
  python scripts/curate_samples.py suggest RESULT.json --output out/curation
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neumann.api.sample_curation import score_result
from neumann.api.samples import REGISTRY_PATH, registry_errors, sample_plan_id
from neumann.models import PremortemResult


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_registry(path: Path) -> dict[str, Any]:
    if path.suffix.lower() != ".json":
        raise ValueError("레지스트리는 JSON 파일만 읽습니다")
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry_errors(registry):
        raise ValueError("레지스트리 검사 실패")
    return registry


def read_results(paths: list[Path]) -> list[dict[str, Any]]:
    files = set()
    for path in paths:
        if path.is_dir():
            result_files = list(path.glob("*.result.json"))
            files.update(f.resolve() for f in (result_files or path.glob("*.json")))
        elif path.suffix.lower() == ".json":
            files.add(path.resolve())
        else:
            raise ValueError("결과는 JSON 파일만 읽습니다")
    if not files:
        raise ValueError("결과 JSON 파일 없음")
    rows = []
    for path in sorted(files):
        raw = path.read_bytes()
        try:
            result = PremortemResult.model_validate(json.loads(raw)).model_dump(mode="json", by_alias=True)
        except ValueError:
            # ValidationError can include the complete rejected input; do not print it.
            raise ValueError("결과 계약 검사 실패: " + path.name) from None
        rows.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "result": result})
    return rows


def match_result(sample: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    plan_id = sample_plan_id(sample)
    if plan_id:
        matches = [r for r in rows if r["result"]["plan_id"] == plan_id]
    else:
        hint = sample["source_test"].get("result_hint")
        matches = [r for r in rows if hint and fnmatch.fnmatchcase(r["path"].name, hint)]
    if len(matches) > 1:
        raise ValueError("결과 짝이 둘 이상입니다: " + sample["id"])
    return matches[0] if matches else None


def curate(registry: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = {f["id"]: f for f in registry["fields"]}
    ranked = []
    for sample in registry["samples"]:
        if sample["kind"] == "reject":
            continue
        row = match_result(sample, rows)
        if row is None:
            continue
        ranked.append({"id": sample["id"], "title": sample["title"], "plan_id": row["result"]["plan_id"],
                       "result_file": str(row["path"]), "result_sha256": row["sha256"],
                       "result_generated_at": row["result"]["generated_at"],
                       **score_result(row["result"], sample, fields[sample["field"]])})
    return sorted(ranked, key=lambda r: (-r["score"], r["id"]))


def apply_scores(registry: dict[str, Any], ranked: list[dict[str, Any]], now: str) -> dict[str, Any]:
    updated = copy.deepcopy(registry)
    by_id = {r["id"]: r for r in ranked}
    for sample in updated["samples"]:
        if sample["id"] not in by_id:
            continue
        row = by_id[sample["id"]]
        # Changing a result invalidates prior human confirmation. Status/public_ok/path are untouched.
        same = sample["curation"].get("result_sha256") == row["result_sha256"]
        sample["curation"] = {k: row[k] for k in ("score", "breakdown", "reason", "generation",
                                                  "result_file", "result_sha256", "result_generated_at")}
        sample["curation"].update(checked_by_human=bool(same and registry_sample(registry, sample["id"])["curation"].get("checked_by_human")),
                                  scored_at=now)
    return updated


def registry_sample(registry: dict[str, Any], sample_id: str) -> dict[str, Any]:
    for sample in registry["samples"]:
        if sample["id"] == sample_id:
            return sample
    raise ValueError("등록된 샘플 없음")


def feature(registry: dict[str, Any], sample_id: str, *, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("사람 확인 후 --confirm-human을 명시해야 합니다")
    updated = copy.deepcopy(registry)
    sample = registry_sample(updated, sample_id)
    if not sample["public_ok"]:
        raise ValueError("공개 승인 없는 후보는 선별할 수 없습니다")
    if sample["kind"] == "reject":
        raise ValueError("거절 시연은 분석 결과 선별 대상이 아닙니다")
    curation = sample["curation"]
    if not curation.get("result_file"):
        raise ValueError("먼저 결과를 채점해야 합니다")
    rows = read_results([Path(curation["result_file"])])
    match = match_result(sample, rows)
    if match is None or match["sha256"] != curation.get("result_sha256"):
        raise ValueError("결과가 바뀌었습니다. 다시 채점해야 합니다")
    field = next(f for f in updated["fields"] if f["id"] == sample["field"])
    score = score_result(match["result"], sample, field)
    if not score["eligible"] or score["score"] != curation.get("score") or score["generation"] != curation.get("generation"):
        raise ValueError("선별 조건 미충족: " + score["reason"])
    sample["status"] = "featured"
    sample["curation"]["checked_by_human"] = True
    return updated


def export_reports(output: Path, ranked: list[dict[str, Any]]) -> str:
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "curation.json", ranked)
    lines = ["# 시연 예시 선별 — 성능 주장 아님", "", "| ID | 점수 | 생성 방식 | 선별 가능 |", "|---|---:|---|---|"]
    for row in ranked:
        lines.append(f"| {row['id']} | {row['score']} | {row['generation']} | {row['eligible']} |")
    markdown = "\n".join(lines) + "\n"
    (output / "curation.md").write_text(markdown, encoding="utf-8")
    sections = []
    for row in ranked:
        cards = "".join("<li>" + html.escape(c["title"]) + f" · 근거 {c['evidence_count']}개</li>" for c in row["cards"])
        weaknesses = "".join("<li>" + html.escape(w["text"]) + " · 일치 카드 " +
                             html.escape(", ".join(w["card_ids"]) or "없음") + "</li>" for w in row["weakness_matches"])
        sections.append("<section><h2>" + html.escape(row["title"]) + "</h2><p>" +
                        html.escape(f"{row['score']} · {row['generation']} · {row['reason']}") +
                        "</p><ul>" + cards + "</ul><p>심사평 첫 문장: " + html.escape(row["review_first_line"]) +
                        "</p><h3>의도한 약점 대조</h3><ul>" + weaknesses + "</ul></section>")
    (output / "summary.html").write_text(
        '<!doctype html><html lang="ko"><meta charset="utf-8"><title>샘플 선별</title>'
        '<h1>사람 확인용 · 시연 예시 선별 — 성능 주장 아님</h1>' + "".join(sections) + "</html>", encoding="utf-8")
    return markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    commands = parser.add_subparsers(dest="command", required=True)
    score = commands.add_parser("score")
    score.add_argument("results", nargs="+", type=Path)
    score.add_argument("--output", type=Path, required=True)
    score.add_argument("--apply", action="store_true")
    select = commands.add_parser("feature")
    select.add_argument("sample_id")
    select.add_argument("--confirm-human", action="store_true")
    suggest = commands.add_parser("suggest")
    suggest.add_argument("results", nargs="+", type=Path)
    suggest.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        registry = read_registry(args.registry)
        if args.command == "feature":
            updated = feature(registry, args.sample_id, confirmed=args.confirm_human)
            if registry_errors(updated):
                raise ValueError("변경 레지스트리 검사 실패")
            write_json(args.registry, updated)
            print("featured: " + args.sample_id)
            return 0
        rows = read_results(args.results)
        ranked = curate(registry, rows)
        if args.command == "suggest":
            # Proposed entries stay private; never include result plan text or evidence quotations.
            matched = {r["plan_id"] for r in ranked}
            proposals = [{"plan_id": r["result"]["plan_id"], "status": "candidate", "public_ok": False,
                          "result_file": str(r["path"]), "result_sha256": r["sha256"]}
                         for r in rows if r["result"]["plan_id"] not in matched]
            args.output.mkdir(parents=True, exist_ok=True)
            write_json(args.output / "suggestions.json", proposals)
            print(f"미등록 후보 {len(proposals)}개 · 공개 승인 없음")
        else:
            if not ranked:
                raise ValueError("등록된 샘플과 일치하는 결과 없음")
            print(export_reports(args.output, ranked), end="")
            if args.apply:
                updated = apply_scores(registry, ranked, datetime.now(UTC).isoformat())
                if registry_errors(updated):
                    raise ValueError("변경 레지스트리 검사 실패")
                write_json(args.registry, updated)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Only our short validation messages are shown; file/config/validation reprs are excluded.
        print("선별 실패: " + (str(exc) if type(exc) is ValueError else type(exc).__name__))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
