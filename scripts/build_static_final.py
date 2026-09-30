"""Build an offline, six-step GitHub Pages prototype from repository fixtures.

No settings loader, environment file, product provider, or network is used.
Run: python scripts/build_static_final.py [--out data/site_final]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(__file__).with_name("static_final")
FIXTURES = ROOT / "tests/fixtures"


def rows(name: str) -> list[dict]:
    return [json.loads(x) for x in (FIXTURES / name).read_text(encoding="utf-8").splitlines() if x]


def load_evidence() -> dict:
    sources = {r["review_id"]: r["text"] for r in rows("reviews.jsonl")}
    sources.update({r["decision_id"]: r["text"] for r in rows("decisions.jsonl")})
    result = {}
    for item in rows("excerpts.jsonl"):
        source = sources[item["source_id"]]
        start, end = item["start"], item["end"]
        if not 0 <= start < end <= len(source):
            raise ValueError("Invalid excerpt offsets")
        quote = source[start:end]
        if quote != item["text"] or hashlib.sha256(source.encode()).hexdigest() != item["source_sha256"]:
            raise ValueError("Source/excerpt mismatch")
        result[item["excerpt_id"]] = {"quote": quote, "start": start, "end": end,
                                     "source": item["source_id"]}
    return result


def measure(lines: list[str]) -> list[dict]:
    """Actually run local tools on these exact, bounded execution conditions."""
    import z3
    import pint
    import networkx as nx

    counts = [int(re.fullmatch(r"(?:학습|검증|시험) 배분 (\d+)건", s)[1]) for s in lines[:3]]
    limit = int(re.fullmatch(r"배분 합계 최대 (\d+)건", lines[3])[1])
    solver = z3.Solver()
    solver.set(timeout=1000)
    solver.add(z3.Sum([z3.IntVal(n) for n in counts]) <= limit)
    logic = solver.check()
    registry = pint.UnitRegistry()
    left = registry.Quantity(1, "mS/cm")
    value = float(re.fullmatch(r"변환 전도도 ([\d.]+) S/m 와 같다", lines[5])[1])
    converted = left.to("S/m").magnitude
    edges = []
    for line in lines[6:]:
        match = re.fullmatch(r"(.+) 완료 후 (.+) 시작", line)
        if match is None:
            raise ValueError("Unsupported execution condition")
        edges.append(match.groups())
    graph = nx.DiGraph(edges)
    return [
        {"tool": "Z3", "passed": logic == z3.sat, "sources": lines[:4],
         "message": f"배분 합계 {sum(counts):,}건 / 상한 {limit:,}건을 확인했습니다.",
         "scope": "명시한 배분 합계의 상한만 점검합니다."},
        {"tool": "Pint", "passed": abs(converted - value) < 1e-12, "sources": lines[4:6],
         "message": f"1 mS/cm = {converted:g} S/m입니다. 문서의 변환값 {value:g} S/m와 대조했습니다.",
         "scope": "명시한 전도도 단위와 환산값만 점검합니다."},
        {"tool": "NetworkX", "passed": nx.is_directed_acyclic_graph(graph), "sources": lines[6:],
         "message": "선행 관계의 순환을 " + ("발견하지 않았습니다." if nx.is_directed_acyclic_graph(graph) else "발견했습니다."),
         "scope": "명시한 작업 순서의 순환만 점검합니다."},
    ]


def make_samples() -> list[dict]:
    evidence = load_evidence()
    configs = [
        ("plan", "재료과학", "전해액 조성으로 이온전도도를 예측합니다.", 12000,
         "유사 조성을 그룹화하고 중복을 제거한 뒤, 그룹 단위로 학습·검증·시험 데이터를 나눕니다. 분할 목록과 중복 검사 결과를 기록합니다.",
         "서로 다른 초기값으로 5회 반복 학습하고 평균 절대 오차의 평균과 표준편차를 보고합니다. 조성 임베딩을 제거한 비교 실험을 같은 분할에서 수행합니다.",
         ["ex_110f92f3599151f1", "ex_4b76d98627bb3f0c"]),
        ("plan_medimaging", "의료영상", "흉부 영상으로 폐렴 징후를 분류합니다.", 50000,
         "환자 단위로 학습·검증·시험 데이터를 나누고, 동일 환자가 여러 분할에 포함되지 않는지 확인합니다. 촬영 기관별 성능도 별도로 보고합니다.",
         "서로 다른 초기값으로 5회 반복 학습하고 분류 성능의 평균과 표준편차를 보고합니다. 주요 구성요소를 제거한 비교 실험을 같은 분할에서 수행합니다.",
         ["ex_a2237bdefb099544", "ex_7686b8804b5212e3"]),
        ("plan_elife_neuro", "신경과학", "뇌영상 신호로 인지과제 유형을 분류합니다.", 200,
         "피험자 단위로 학습·검증·시험 데이터를 나누고 동일 피험자의 신호가 여러 분할에 포함되지 않는지 확인합니다. 전처리 기준은 학습 데이터로만 정합니다.",
         "서로 다른 초기값으로 5회 반복 학습하고 분류 정확도의 평균과 표준편차를 보고합니다. 독립 성분 분석을 제거한 비교 실험을 같은 분할에서 수행합니다.",
         ["ex_a2237bdefb099544", "ex_7686b8804b5212e3"]),
    ]
    samples = []
    for name, field, intro, n, split, repeats, ids in configs:
        original = (FIXTURES / "plans" / f"{name}.md").read_text(encoding="utf-8")
        lines = original.splitlines()
        edits = []
        for index, (title, after, eid) in enumerate(zip(
            ["분할 간 데이터 누수를 방지합니다", "반복 실험으로 불확실성을 보고합니다"],
            [split, repeats], ids, strict=True)):
            numbers = [16, 17] if name == "plan" and index == 0 else [16] if index == 0 else [22]
            edits.append({"id": f"{name}-{index}", "title": title, "lines": numbers,
                          "before": "\n".join(lines[i - 1] for i in numbers), "after": after,
                          "evidence": evidence[eid], "origin": "Claude/Codex 오프라인",
                          "reference": "분야 수준 참고" if name == "plan_elife_neuro" else "가상 심사 기록",
                          "paper": "가상 연구의 심사 기록 · 데이터 분할" if index == 0 else "가상 연구의 심사 기록 · 반복 실험"})
        conditions = [f"학습 배분 {n * 8 // 10}건", f"검증 배분 {n // 10}건", f"시험 배분 {n // 5}건",
                      f"배분 합계 최대 {n}건", "기준 전도도 1 mS/cm", "변환 전도도 1 S/m 와 같다",
                      "전처리 완료 후 분할고정 시작", "분할고정 완료 후 학습 시작", "평가 완료 후 학습 시작", "학습 완료 후 평가 시작"]
        corrections = [
            {"before": conditions[2], "after": f"시험 배분 {n // 10}건", "reason": "시험 배분을 조정해 합계가 상한을 넘지 않도록 수정했습니다."},
            {"before": conditions[5], "after": "변환 전도도 0.1 S/m 와 같다", "reason": "전도도 환산값을 0.1 S/m로 수정했습니다."},
            {"before": conditions[8], "after": "분할고정 완료 후 평가 시작", "reason": "평가에서 학습으로 되돌아가는 순환 관계를 제거했습니다."},
        ]
        final_conditions = list(conditions)
        for correction in corrections:
            final_conditions[final_conditions.index(correction["before"])] = correction["after"]
        before, after = measure(conditions), measure(final_conditions)
        if any(r["passed"] for r in before) or not all(r["passed"] for r in after):
            raise ValueError("Expected failing conditions and passing corrections")
        samples.append({"id": name, "field": field, "intro": intro,
                        "title": lines[0].split("—")[-1].strip(), "original": original,
                        "edits": edits, "conditions": conditions, "corrections": corrections,
                        "before_checks": before, "after_checks": after,
                        "condition_note": "시연을 위해 제안한 실행 조건입니다. 전도도 환산은 도구 사용 예이며 해당 연구의 실험 조건을 의미하지 않습니다."})
    return samples


def build(out: Path) -> list[dict]:
    samples = make_samples()
    font = ROOT / "src/neumann/webui/fonts/Pretendard/PretendardVariable.woff2"
    replacements = {
        "@@FONT@@": base64.b64encode(font.read_bytes()).decode("ascii"),
        "@@CSS@@": (ASSETS / "style.css").read_text(encoding="utf-8"),
        "@@WAITCSS@@": (ASSETS / "wait.css").read_text(encoding="utf-8"),
        "@@WAITJS@@": (ASSETS / "wait.js").read_text(encoding="utf-8"),
        "@@JS@@": (ASSETS / "flow.js").read_text(encoding="utf-8"),
        "@@DATA@@": json.dumps(samples, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026"),
    }
    page = (ASSETS / "index.html").read_text(encoding="utf-8")
    for key, value in replacements.items():
        page = page.replace(key, value)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8", newline="\n")
    (out / "flow.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "FONT-LICENSE.txt").write_text(font.with_name("LICENSE").read_text(encoding="utf-8"), encoding="utf-8")
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "data/site_final")
    args = parser.parse_args()
    samples = build(args.out)
    print(f"STATIC-FINAL: {len(samples)} samples; 6 stages; 9 corrected local tool checks; offline HTML")


if __name__ == "__main__":
    main()
