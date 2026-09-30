"""최종 점검 시연용 scripted mock(FIN-ENGINE). generator는 ``mock``으로 남고 실제 LLM 검토가 아니다.

    from neumann.analyze.finalize_demo import DEMO_PLAN, mock_assessment, mock_correction

동작
- ``mock_assessment``: payload의 계획서 줄에서 아래 **오류 패턴**이 보이면 그 줄을 앵커로 결정적 issue·checks를 낸다.
  패턴이 하나도 없으면 기존 정직한 기본 mock(``finalize.mock_assessment``: "의미 검토 미검증" 1건, checks 0)으로 돌아간다.
- ``mock_correction``: payload의 issues 가운데 ``demo-`` 접두 항목에 대해 원문 줄을 그대로 앵커로 쓰는 교정을 낸다.
  교정은 엔진의 근거 게이트(원문 낱말·수치만, 새 사실은 ``[확인 필요: …]`` 안에서만)를 통과하도록 쓴다. 통과 여부는 엔진이 판정한다.
- 도구 판정은 여기서 하지 않는다. checks는 ``final_tools``(Z3·Pint·NetworkX)가 원문 발췌로 실제 계산한다.

심은 오류(``DEMO_PLAN``)
| id | 유형 | 줄 패턴 | 도구 |
|---|---|---|---|
| demo-budget | physical(수치 제약) | 예산 항목 합 1200+2400+600 > 명시 상한 4000만원 | Z3 constraint(sum, le) → failed |
| demo-units | physical(단위 차원) | 전도도 10 mS 를 1 S/cm 와 같다고 봄(컨덕턴스 vs 전도도) | Pint units(equality) → failed |
| demo-order | structural(선행 순환) | 데이터 정제 후 모델 학습 ↔ 모델 학습 후 데이터 정제 | NetworkX dependency → failed(cycle) |
| demo-contra | logical(모순) | 가설 "점도에 반비례" ↔ 방법 "점도가 높을수록 전도도 증가" | 도구 없음 → unchecked(no_tool_check, 판단 보류) |
"""

from __future__ import annotations

import re
from typing import Any

from neumann.analyze import finalize as _engine
from neumann.llm import LLMCall

DEMO_ID = "final-demo-battery-v1"
DEMO_TITLE = "전해액 이온전도도 예측 GNN 대리모델 (시연용 · 오류 포함)"

DEMO_PLAN = """# 연구계획서 — 전해액 이온전도도 예측 GNN 대리모델 (시연용, 오류 포함)

## 1. 연구 목표

리튬이온 배터리 전해액의 이온전도도를 예측하는 그래프 신경망(GNN) 대리모델을 개발해 실험 합성 없이 후보 조성을 사전 선별한다.
연구 질문: 조성 정보만으로 상온 이온전도도를 실험 오차 수준으로 예측할 수 있는가?

## 2. 가설

가설 1: 용매 조성 그래프와 염 농도를 함께 인코딩하면 조성만 쓰는 모델보다 예측 오차가 줄어든다.
가설 2: 이온전도도는 점도에 반비례하므로 점도 특징을 추가하면 외삽 성능이 개선된다.

## 3. 방법

분자 그래프 인코더와 조성 임베딩을 결합한 GNN을 학습하고 기존 baseline 2종과 비교한다.
점도가 높을수록 이온전도도가 증가한다는 관계를 모델 입력의 사전 지식으로 반영한다.
데이터 정제 후 모델 학습을 시작한다.
모델 학습 후 데이터 정제 기준을 확정한다.

## 4. 데이터

문헌에 보고된 전해액 조성-전도도 데이터를 수집한다.
전해액 이온전도도 10 mS 값을 문헌 기준값 1 S/cm 와 같다고 보고 비교한다.
데이터를 학습, 검증, 시험 집합으로 무작위 분할한다.

## 5. 평가

holdout 시험 집합에서 MAE와 R2를 보고한다.

## 6. 기대 성과

제안 모델이 baseline 대비 예측 정확도를 높이고 후보 조성 선별 시간을 줄인다.

## 7. 예산

예산은 장비 1200만원, 인건비 2400만원, 재료비 600만원으로 구성하며 총 합계는 최대 4000만원이다.
"""

_BUDGET = re.compile(r"장비 (\d+)만원.*인건비 (\d+)만원.*재료비 (\d+)만원.*합계는 최대 (\d+)만원")
_UNITS = re.compile(r"(\d+) mS .*?(\d+) S/cm .*같다")
_DEP_A = re.compile(r"데이터 정제 후 모델 학습")
_DEP_B = re.compile(r"모델 학습 후 데이터 정제")
_CONTRA_H = re.compile(r"반비례")
_CONTRA_M = re.compile(r"높을수록.*증가")


def _lines(payload: dict[str, Any]) -> list[tuple[int, str]]:
    out = []
    for row in payload.get("plan", []) if isinstance(payload, dict) else []:
        if isinstance(row, dict) and isinstance(row.get("no"), int) and isinstance(row.get("text"), str):
            out.append((row["no"], row["text"]))
    return out


def _find(lines: list[tuple[int, str]], pattern: re.Pattern[str]) -> tuple[int, str, re.Match[str] | None] | None:
    for no, text in lines:
        m = pattern.search(text)
        if m:
            return no, text, m
    return None


def demo_assessment(call: LLMCall) -> dict[str, Any] | None:
    """심은 오류 패턴이 payload에 있으면 issues·checks. 없으면 None."""
    lines = _lines(call.payload)
    issues: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    budget = _find(lines, _BUDGET)
    if budget:
        no, _text, m = budget
        checks.append({"check_id": "demo-budget", "kind": "constraint", "plan_lines": [no], "params": {
            "sources": [{"line": no}], "operation": "sum",
            "terms": [{"source": 0, "value": int(m.group(i))} for i in (1, 2, 3)],
            "comparator": "le", "limit": {"source": 0, "value": int(m.group(4))}}})
        issues.append({"issue_id": "demo-budget", "kind": "physical", "plan_lines": [no],
                       "message": "예산 항목의 합이 같은 줄에 명시된 총 합계 상한과 맞는지 검산이 필요하다.", "check_ids": ["demo-budget"]})
    units = _find(lines, _UNITS)
    if units:
        no, _text, m = units
        checks.append({"check_id": "demo-units", "kind": "units", "plan_lines": [no], "params": {
            "sources": [{"line": no}], "operation": "equality",
            "left": {"source": 0, "value": int(m.group(1)), "unit": "mS"},
            "right": {"source": 0, "value": int(m.group(2)), "unit": "S/cm"}}})
        issues.append({"issue_id": "demo-units", "kind": "physical", "plan_lines": [no],
                       "message": "같다고 비교한 두 전도도 값의 단위 차원이 일치하는지 확인이 필요하다.", "check_ids": ["demo-units"]})
    dep_a, dep_b = _find(lines, _DEP_A), _find(lines, _DEP_B)
    if dep_a and dep_b:
        (na, _ta, _ma), (nb, _tb, _mb) = dep_a, dep_b
        checks.append({"check_id": "demo-order", "kind": "dependency", "plan_lines": sorted({na, nb}), "params": {
            "sources": [{"line": na}, {"line": nb}],
            "nodes": [{"id": "clean", "source": 0, "phrase": "데이터 정제"}, {"id": "train", "source": 0, "phrase": "모델 학습"}],
            "edges": [{"from": "clean", "to": "train", "source": 0, "phrase": "데이터 정제 후 모델 학습"},
                      {"from": "train", "to": "clean", "source": 1, "phrase": "모델 학습 후 데이터 정제"}]}})
        issues.append({"issue_id": "demo-order", "kind": "structural", "plan_lines": sorted({na, nb}),
                       "message": "데이터 정제와 모델 학습의 선행 관계가 서로를 전제해 순서가 정해지지 않는다.", "check_ids": ["demo-order"]})
    hyp, meth = _find(lines, _CONTRA_H), _find(lines, _CONTRA_M)
    if hyp and meth:
        issues.append({"issue_id": "demo-contra", "kind": "logical", "plan_lines": sorted({hyp[0], meth[0]}),
                       "message": "가설은 점도와 이온전도도가 반비례한다고 하고 방법은 점도가 높을수록 이온전도도가 증가한다고 하여 방향이 어긋난다.",
                       "check_ids": []})
    if not issues:
        return None
    return {"issues": issues, "checks": checks}


def demo_correction(call: LLMCall) -> dict[str, Any] | None:
    """demo- issue마다 원문 줄을 앵커로 한 교정. 새 사실은 [확인 필요: …] 안에만 둔다."""
    payload = call.payload
    text_of = dict(_lines(payload))
    issues = {i.get("issue_id"): i for i in payload.get("issues", []) if isinstance(i, dict)}
    rows = {r.get("check_id"): r for r in payload.get("tool_checks", []) if isinstance(r, dict)}
    edits: list[dict[str, Any]] = []

    def anchored(issue_id: str, no: int, suffix: str, replace: tuple[str, str] | None = None) -> None:
        current = text_of.get(no)
        if current is None:
            return
        new = current
        if replace:
            new = new.replace(replace[0], replace[1], 1)
        edits.append({"line": no, "current_text": current, "replacement": f"{new} {suffix}".strip(), "issue_ids": [issue_id]})

    if "demo-budget" in issues:
        no = issues["demo-budget"]["plan_lines"][0]
        m = _BUDGET.search(text_of.get(no, ""))
        row = rows.get("demo-budget", {})
        if m and row.get("status") == "failed":
            total = sum(int(m.group(i)) for i in (1, 2, 3))
            anchored("demo-budget", no, f"[확인 필요: 항목 합 {total}만원이 상한 {m.group(4)}만원을 넘음 — 항목 또는 상한 조정]")
        elif m:
            anchored("demo-budget", no, "[확인 필요: 예산 항목 합과 상한 대조 미검사]")
    if "demo-units" in issues:
        no = issues["demo-units"]["plan_lines"][0]
        if rows.get("demo-units", {}).get("status") == "failed":
            anchored("demo-units", no, "[확인 필요: mS는 컨덕턴스 단위라 전도도 S/cm 와 차원이 다름 — 단위 정정]")
        else:
            anchored("demo-units", no, "[확인 필요: 두 값의 단위 차원 대조 미검사]")
    if "demo-order" in issues:
        target = issues["demo-order"]["plan_lines"][-1]
        if rows.get("demo-order", {}).get("status") == "failed":
            anchored("demo-order", target, "[확인 필요: 데이터 정제와 모델 학습의 선행 순서가 순환함 — 순서 확정]")
    if "demo-contra" in issues:
        target = issues["demo-contra"]["plan_lines"][-1]
        current = text_of.get(target, "")
        if "증가한다는" in current:
            anchored("demo-contra", target, "", replace=("증가한다는", "[확인 필요: 가설 2(반비례)와 방향이 어긋남 — 증가/감소 확정]"))
    return {"edits": edits[:8]} if edits else None


def mock_assessment(call: LLMCall) -> dict[str, Any]:
    return demo_assessment(call) or _engine.mock_assessment(call)


def mock_correction(call: LLMCall) -> dict[str, Any]:
    return demo_correction(call) or _engine.mock_correction(call)


__all__ = ["DEMO_ID", "DEMO_PLAN", "DEMO_TITLE", "demo_assessment", "demo_correction", "mock_assessment", "mock_correction"]
