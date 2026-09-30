"""structure(NetworkX): 필수 절·순서·번호·참조. 정상·경계·적대·시간."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from neumann.finalize.tools import ToolCall, ToolRegistry
from neumann.finalize.tools import structure
from neumann.finalize.tools.fin_tools import register_all

REQUIRED = ["배경", "연구 질문", "가설", "방법", "데이터", "평가", "일정", "위험", "기대효과"]
FULL = """# 계획서
## 1. 배경
## 2. 연구 질문
## 3. 가설
## 4. 방법
### 4.1 모델
### 4.2 학습
## 5. 데이터
표 1. 데이터 구성
## 6. 평가
표 1 참조, §4.2 참조.
## 7. 일정
## 8. 위험
## 9. 기대효과"""


def lines(text):
    return {"lines": text.splitlines()}


# (args, verdict, 추가 기대) — 변이 검사도 이 표를 쓴다.
CASES = [
    ({**lines(FULL), "required_sections": REQUIRED}, "pass", {"missing": [], "order_violations": [], "broken_references": []}),
    ({**lines(FULL.replace("## 3. 가설\n", "")), "required_sections": REQUIRED}, "fail",
     {"missing": ["hypothesis"], "numbering_gaps": ["3"]}),
    ({**lines(FULL.replace("## 3. 가설", "## 3. 방법론 개요").replace("## 8. 위험", "## 8. 위험\n## 10. 가설")),
      "required_sections": REQUIRED}, "fail", {"order_violations": ["hypothesis"]}),
    ({**lines(FULL.replace("§4.2", "§4.3")), "required_sections": REQUIRED}, "fail",
     {"broken_references": [{"line": 11, "ref": "§4.3"}]}),
    ({**lines(FULL.replace("표 1 참조", "표 2 참조")), "required_sections": REQUIRED}, "fail",
     {"broken_references": [{"line": 11, "ref": "표 2"}]}),
    ({**lines(FULL.replace("### 4.2 학습", "### 4.1 학습")), "required_sections": REQUIRED}, "fail",
     {"duplicate_numbers": ["4.1"]}),
    ({**lines(FULL.replace("### 4.2 학습", "### 4.3 학습").replace("§4.2", "§4.3")), "required_sections": REQUIRED},
     "fail", {"numbering_gaps": ["4.2"]}),
    ({**lines(FULL), "required_sections": [], "references": [{"line": 11, "ref": "§9"}], "checks": ["references"]},
     "pass", {}),
    ({**lines(FULL), "required_sections": [], "references": [{"line": 11, "ref": "§11"}], "checks": ["references"]},
     "fail", {"broken_references": [{"line": 11, "ref": "§11"}]}),
    ({"line_map": {"2": "## 1. 배경", "3": "## 2. 방법", "9": "§3 참조"}, "required_sections": []}, "fail",
     {"broken_references": [{"line": 9, "ref": "§3"}]}),
    ({**lines("1. 배경\n본문이다.\n2. 연구 질문\n3. 방법\n1. 데이터를 모은다.\n4. 평가"), "required_sections": ["배경", "방법", "평가"]},
     "pass", {"missing": []}),                                                      # 번호 제목(마크다운 아님), 문장 목록은 제목 아님
    ({**lines("## Background\n## Research question\n## Methods\n## Evaluation"),
      "required_sections": ["background", "question", "method", "evaluation", "risk"]}, "fail", {"missing": ["risk"]}),
]


@pytest.mark.parametrize("args,verdict,extra", CASES)
def test_sections_order_numbering_and_reference_graph(args, verdict, extra):
    out = structure.run(args)
    assert out["verdict"] == verdict, out
    assert out["engine"] == "networkx"
    for k, v in extra.items():
        assert out[k] == v, (k, out[k])


def test_plain_text_without_headings_is_unchecked_not_missing():
    out = structure.run({"lines": ["그냥 문장이다.", "또 다른 문장이다."], "required_sections": REQUIRED})
    assert out == {"verdict": "unchecked", "reason": "no_headings", "engine": "networkx"}


def test_unnumbered_headings_cannot_resolve_section_refs():
    out = structure.run({"lines": ["## 배경", "§3 참조", "## 방법"], "required_sections": []})
    assert out["verdict"] == "pass" and out["unresolvable_references"] == 1 and not out["broken_references"]


@pytest.mark.parametrize("args", [
    {"lines": "not a list"}, {"lines": [1, 2]}, {"line_map": {"x": "a"}}, {"line_map": {"1": 3}},
    {"lines": ["## a"], "required_sections": ["우주"]}, {"lines": ["## a"], "checks": ["everything"]},
    {"lines": ["## a"], "references": "§1"}, {"lines": ["## a", "## b"], "references": [{"line": "1", "ref": 3}]},
    {"lines": ["x"] * 5001}, [], "## a",
])
def test_invalid_args_are_unchecked(args):
    assert structure.run(args)["verdict"] == "unchecked"


def test_networkx_unavailable_is_tool_unavailable():
    reg = ToolRegistry()
    register_all(reg)
    real = structure.importlib.import_module

    def no_nx(name, *a, **k):
        if name == "networkx":
            raise ImportError("networkx")
        return real(name, *a, **k)

    with patch.object(structure.importlib, "import_module", side_effect=no_nx):
        res = reg.run(ToolCall("structure", {**lines(FULL), "required_sections": REQUIRED}))
    assert res.verdict == "unchecked" and res.error == "tool_unavailable"


def test_large_and_hostile_input_time_bound():
    hostile = ["## " + "§1 " * 600] + ["§" + "9" * 50 + " 참조 표 999 그림 1" * 50] * 4000
    t0 = time.perf_counter()
    out = structure.run({"lines": hostile, "required_sections": REQUIRED})
    assert time.perf_counter() - t0 < 5.0
    assert out["verdict"] in ("pass", "fail", "unchecked") and len(out.get("broken_references", [])) <= 50
