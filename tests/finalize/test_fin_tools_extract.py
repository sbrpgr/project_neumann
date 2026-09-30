"""FIN-TOOLS 규칙 추출기: 오류를 심은 계획서에서 검사가 실제로 생기고(줄까지) 도구가 fail을, 대조군은 pass를 낸다.

mock provider(LLM 검사 제안 0건)에서도 원문 수치·단위·합계·일정·참조·인용만으로 검사가 생기는지가 핵심이다.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from neumann.finalize.tools import TOOL_FOR_CHECK, ToolRegistry
from neumann.finalize.tools import citation
from neumann.finalize.tools.extract import extract_checks, run_checks
from tests.finalize.fin_tools_backend import build_backend
from tests.finalize.fin_tools_plans import CLEAN, SEEDED
from tests.fixtures.loader import DEMO_PLANS, plan_text


@pytest.fixture(scope="module", autouse=True)
def evidence_backend(tmp_path_factory: pytest.TempPathFactory):
    citation.set_backend(build_backend(Path(tmp_path_factory.mktemp("fin_tools_ev"))))
    yield
    citation.set_backend(None)


def _run(plan: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in run_checks(extract_checks(plan), reg=ToolRegistry()):
        out.setdefault(r["check"]["label"], []).append(r)
    return out


# 라벨 → (원문 줄, verdict). 줄 번호는 fin_tools_plans.SEEDED 기준.
SEEDED_EXPECT = {
    "references": [((4, 11), "fail")],
    "citation": [((5,), "fail")],
    "unit_add": [((12,), "fail")],
    "unit_derive": [((13,), "fail"), ((14,), "fail")],
    "split_sum": [((17,), "fail")],
    "schedule_sum": [((28, 29, 30, 31), "fail")],
    "table_sum": [((36, 37, 38, 39), "fail")],
    "sections": [(None, "fail")],
}


def test_seeded_errors_produce_checks_on_the_right_lines_and_fail():
    got = _run(SEEDED)
    assert set(got) == set(SEEDED_EXPECT)
    for label, expected in SEEDED_EXPECT.items():
        assert len(got[label]) == len(expected), label
        for r, (lines, verdict) in zip(got[label], expected):
            if lines is not None:
                assert tuple(r["check"]["plan_lines"]) == lines, label
            assert r["result"]["verdict"] == verdict, (label, r["result"])
            assert r["result"]["ok"] is True  # fail은 "도구가 어긋남을 확인함"이다(검사 못 함이 아니다)


def test_seeded_tool_outputs_name_the_error():
    got = _run(SEEDED)
    out = {k: [r["result"]["output"] for r in v] for k, v in got.items()}
    assert out["split_sum"][0]["computed"] == 110 and out["split_sum"][0]["stated"] == 100
    assert out["schedule_sum"][0]["computed"] == 10 and out["schedule_sum"][0]["stated"] == 12
    assert out["table_sum"][0]["computed"] == 500_000_000 and out["table_sum"][0]["stated"] == 600_000_000
    assert out["unit_add"][0]["reason"] == "incompatible_dimensions"
    rate, gpu = out["unit_derive"]
    assert rate["computed"] == pytest.approx(27.7777777778) and rate["expected"] == 10
    assert gpu["computed"] == 576 and gpu["expected"] == 500
    sec = out["sections"][0]
    assert sec["missing"] == ["risk", "impact"] and sec["order_violations"] == ["hypothesis"]
    assert sec["numbering_gaps"] == ["5"]
    assert out["references"][0]["broken_references"] == [{"line": 4, "ref": "§12"}, {"line": 11, "ref": "표 2"}]
    assert out["citation"][0]["retracted"] is True and out["citation"][0]["post_status"][0]["kind"] == "retraction"


def test_clean_control_passes_every_extracted_check():
    got = _run(CLEAN)
    assert set(got) >= {"sections", "references", "unit_add", "unit_derive", "split_sum", "schedule_sum",
                        "table_sum", "citation"}
    bad = {k: [r["result"]["output"] for r in v if r["result"]["verdict"] != "pass"] for k, v in got.items()}
    assert not any(bad.values()), bad


@pytest.mark.parametrize("name", DEMO_PLANS)
def test_demo_plans_get_checks_under_mock_without_false_arithmetic_failures(name):
    got = _run(plan_text(name))
    assert got["split_sum"][0]["result"]["verdict"] == "pass"  # 80/10/10
    assert got["sections"][0]["result"]["output"]["missing"] == ["background", "hypothesis", "schedule", "risk"]
    assert all(r["result"]["verdict"] == "pass" for k, v in got.items() if k != "sections" for r in v)


def test_anchors_are_exact_source_substrings_and_tool_choice_is_code_fixed():
    lines = SEEDED.splitlines()
    checks = extract_checks(SEEDED)
    assert checks
    for c in checks:
        assert c.call.name == TOOL_FOR_CHECK[c.kind]
        assert c.call.check_id == c.check_id
        for a in c.anchors:
            assert lines[a["line"] - 1][a["start"]:a["end"]] == a["text"]
        assert set(c.plan_lines) == {a["line"] for a in c.anchors}


@pytest.mark.parametrize("text", [
    "## 일정\n- 1단계: 약 3개월\n- 2단계: 약 4개월\n- 총 연구 기간: 12개월",           # 근사
    "## 일정\n- 1단계: 3개월(가정)\n- 2단계: 4개월(가정)\n- 총 연구 기간: 12개월(가정)",  # 가정
    "We do not split the data 70/20/20 into train/test.",                              # 부정
    "If needed, 10 mS + 1 S/cm are combined.",                                          # 조건
])
def test_negated_or_qualified_claims_are_not_extracted_codex_rule(text):
    labels = {c.label for c in extract_checks(text)}
    assert not labels & {"schedule_sum", "split_sum", "unit_add"}


def test_ambiguous_budget_and_parallel_schedule_are_left_unchecked():
    budget = "## 예산\n- 인건비 3억 원(연 1억 원)\n- 장비비 2억 원\n- 재료비 1억 원\n- 총 예산 6억 원"
    assert not [c for c in extract_checks(budget) if c.label == "budget_sum"]
    sched = "## 일정\n- 1단계: 6개월(2단계와 병행)\n- 2단계: 6개월\n- 총 연구 기간: 6개월"
    assert not [c for c in extract_checks(sched) if c.label == "schedule_sum"]


def test_korean_particles_inline_budget_and_ranges():
    text = ("## 예산\n인건비 3억 원, 장비비 1억 5천만 원, 총 4억 5천만원이다.\n"
            "## 일정\n- 1단계(M1–M4)\n- 2단계(M5–M14)\n- 총 연구 기간은 12개월이다.")
    got = _run(text)
    assert got["budget_sum"][0]["result"]["verdict"] == "pass"
    assert got["budget_sum"][0]["check"]["call"]["args"]["items"] == [300_000_000, 150_000_000]
    span = got["schedule_span"][0]
    assert span["result"]["verdict"] == "fail" and span["result"]["output"]["computed"] == 14


def test_line_budget_and_expressions_and_units_compare():
    text = ("## 예산\n- 인건비: 2,000만원\n- 재료비: 500만원\n- 합계: 2,400만원\n"
            "데이터 3 + 4 = 8이다.\n배치 크기 32 × 100 = 3200이다.\n모델 120 GB ≤ 80 GB 메모리.")
    got = _run(text)
    assert got["budget_sum"][0]["result"]["output"]["computed"] == 25_000_000
    assert got["budget_sum"][0]["result"]["verdict"] == "fail"
    assert got["expr_sum"][0]["result"]["verdict"] == "fail"
    arith = [c for c in extract_checks(text) if c.label == "arith_expr"][0]
    assert arith.call.name == "calculator" and arith.call.args == {"expression": "32*100", "expected": 3200, "tolerance": 0.0}
    assert got["unit_compare"][0]["result"]["verdict"] == "fail"


JUNK = {"none": None, "int": 3, "empty": "", "spaces": "   ", "nul": "\x00" * 1000, "digits": "1" * 300_000,
        "pipes": "|" * 5000 + "\n" * 5000, "headings": "## a\n" * 6000, "sections": "§" * 10_000,
        "korean_mult": "1억" * 20_000, "table": "| 계 | 1 |\n|---|---|\n" + "| 1 | 2 |\n" * 3000}


@pytest.mark.parametrize("key", list(JUNK))
def test_junk_inputs_never_raise_and_are_bounded(key):
    junk = JUNK[key]
    t0 = time.perf_counter()
    checks = extract_checks(junk)
    assert isinstance(checks, list) and len(checks) <= 32
    assert time.perf_counter() - t0 < 5.0


def test_large_plan_is_fast_and_deterministic():
    big = (SEEDED + "\n") * 40  # 약 4만 자
    t0 = time.perf_counter()
    a = [c.as_dict() for c in extract_checks(big)]
    assert time.perf_counter() - t0 < 5.0
    assert a == [c.as_dict() for c in extract_checks(big)]
    assert len(a) == 32
