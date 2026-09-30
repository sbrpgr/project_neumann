"""SEC-6: 계획서 제목 찾기(`index.queries`)가 세제곱 되돌림 없이 선형이고, 정상 마크다운에서는 옛 결과와 같다.

옛 구현은 `^\\s{0,3}#{1,6}\\s+(.+?)\\s*#*\\s*$`(re.M)였고 "# a" + 공백 4,000개 + "b"에 55초 이상 걸렸다.
"""

from __future__ import annotations

import random
import re
import time
from pathlib import Path

import pytest

from neumann.index import queries as Q
from neumann.index.queries import plan_axis_queries

PLANS = sorted((Path(__file__).resolve().parents[1] / "fixtures/plans").glob("*.md"))

# ---- 옛 구현(참조용 복사본). 짧은 입력에서만 부른다 ----
_OLD = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.M)


def _old_plan_axis_queries(text: str, *, include_full: bool = True, min_chars: int = 8) -> list[tuple[str, str]]:
    text = text or ""
    out: list[tuple[str, str]] = []
    if include_full and text.strip():
        out.append((text.strip(), "topic"))
    heads = list(_OLD.finditer(text))
    if not heads:
        return out
    title = heads[0].group(1).strip() if heads[0].group(0).lstrip().startswith("# ") else ""
    buckets: dict[str, list[str]] = {}
    for i, m in enumerate(heads):
        body = text[m.end() : heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        axis = next((ax for pat, ax in Q._HEADING_AXIS if pat.search(m.group(1))), None)
        if axis and body:
            buckets.setdefault(axis, []).append(body)
    if title:
        buckets.setdefault("topic", []).insert(0, title)
    for axis in Q.AXES:
        q = "\n".join(buckets.get(axis, [])).strip()
        if len(q) >= min_chars and (q, axis) not in out:
            out.append((q, axis))
    return out


def _old_titles(text: str) -> list[str]:
    return [m.group(1).strip() for m in _OLD.finditer(text)]


def _new_titles(text: str) -> list[str]:
    return [h[2] for h in Q._headings(text)]


# ---- 정상 마크다운 생성기: 제목에는 글자가 있고, `#`만 있는 줄·빈 제목은 없다 ----
_TITLES = ["연구 목표", "연구 방법", "데이터 수집", "평가 계획", "기대 성과", "배경", "Methods", "Dataset",
           "Evaluation metrics", "Overview", "C# 모델 구현", "실험 설계 #2", "요약", "Related work", "일정",
           "방법론 (Approach)", "데이터·자료", "검증 및 실험", "a", "Model", "Goal", "참고문헌"]
_BODY = ["리튬이온 배터리 수명을 예측한다.", "GNN과 transformer를 비교한다.", "12,000건의 셀 데이터를 쓴다.",
         "R2와 MAE로 평가한다.", "- 항목 하나", "* 항목 둘", "1. 첫째", "> 인용문", "`code` 한 줄", "표 | 값",
         "#hashtag 는 제목이 아니다", "    # 들여쓰기 4칸 코드", "####### 일곱 개", "문장 끝에 # 기호",
         "영문 C# 과 F#", "x = y # 주석", "```", "print('hi')  # 주석", "trailing spaces   ", "\t탭으로 시작", ""]


def _heading_line(rng: random.Random) -> str:
    ind = " " * rng.choice([0, 0, 0, 1, 2, 3])
    sep = rng.choice([" ", " ", " ", "  ", "\t", "　", "\xa0"])
    close = rng.choice(["", "", "", " #", " ###", " ## ", "   ", "#"])
    return f"{ind}{'#' * rng.randint(1, 6)}{sep}{rng.choice(_TITLES)}{close}"


def _normal_doc(rng: random.Random) -> str:
    lines = []
    for _ in range(rng.randint(0, 25)):
        r = rng.random()
        lines.append(_heading_line(rng) if r < 0.3 else "" if r < 0.45 else rng.choice(_BODY))
    nl = "\r\n" if rng.random() < 0.15 else "\n"
    return nl * rng.choice([0, 0, 1, 2]) + nl.join(lines) + nl * rng.choice([0, 1, 2])


@pytest.mark.parametrize("path", PLANS, ids=[p.name for p in PLANS])
def test_fixture_plans_same_as_old(path):
    text = path.read_text(encoding="utf-8")
    assert plan_axis_queries(text) == _old_plan_axis_queries(text)
    assert _new_titles(text) == _old_titles(text)


def test_random_normal_markdown_same_as_old():
    rng = random.Random(20260930)
    for _ in range(400):
        doc = _normal_doc(rng)
        assert plan_axis_queries(doc) == _old_plan_axis_queries(doc), repr(doc)
        assert _new_titles(doc) == _old_titles(doc), repr(doc)


def test_single_line_same_as_old_except_empty_titles():
    """한 줄만 보면 옛 정규식과 제목이 같다. 다른 것은 내용이 비었거나 `#`뿐인 제목 줄뿐이다(새 쪽은 빈 제목)."""
    rng = random.Random(6)
    alphabet = ["#", "#", "#", " ", " ", "\t", "a", "가", "　", "\xa0", "\r", "x", "."]
    for _ in range(20_000):
        line = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        m = _OLD.match(line)
        new = Q._headings(line)
        old_title = m.group(1).strip() if m else None
        if old_title and old_title.strip("#").strip():
            assert [h[2] for h in new] == [old_title], repr(line)
        else:
            assert all(h[2] in ("", old_title) for h in new), repr(line)


@pytest.mark.parametrize(
    ("text", "old_titles", "new_titles"),
    [
        # 옛 `#{1,6}\s+`가 줄바꿈을 넘어 다음 줄을 제목으로 삼았다. 새 쪽은 빈 제목(CommonMark)
        ("#\n방법\n본문", ["방법"], [""]),
        ("# \n#### 데이터 수집\n본문", ["#### 데이터 수집"], ["", "데이터 수집"]),
        # 옛 `\s*#*\s*$`가 다음 줄의 `##`까지 먹어 그 줄이 제목에서 빠졌다
        ("# 데이터\n##\n본문", ["데이터"], ["데이터", ""]),
        # 내용이 `#`뿐인 제목: 옛 쪽은 `#`, 새 쪽은 빈 제목
        ("# ###", ["#"], [""]),
    ],
)
def test_documented_differences(text, old_titles, new_titles):
    assert _old_titles(text) == old_titles
    assert _new_titles(text) == new_titles


def test_empty_heading_does_not_steal_next_line():
    text = "## 평가\nR2와 MAE로 평가한다.\n######\n데이터 누수 점검 계획은 없다.\n"
    assert _old_plan_axis_queries(text)[1:] == [("R2와 MAE로 평가한다.", "evaluation")]
    assert plan_axis_queries(text)[1:] == [("R2와 MAE로 평가한다.", "evaluation")]
    text2 = "## 방법\nGNN을 쓴다.\n#\n데이터 수집 방법\n조성 12,000건\n"
    assert ("조성 12,000건", "data") in _old_plan_axis_queries(text2)  # 옛: 본문 줄이 '데이터' 제목이 됐다
    assert plan_axis_queries(text2)[1:] == [("GNN을 쓴다.", "method")]


def _best(fn, text: str, rep: int = 3) -> float:
    times = []
    for _ in range(rep):
        t0 = time.perf_counter()
        fn(text)
        times.append(time.perf_counter() - t0)
    return min(times)


N = 1_000_000
ADVERSARIAL = {
    "hash_a_spaces_b": "# a" + " " * N + "b",  # 보고된 세제곱 모양
    "hash_a_tabs_b": "# a" + "\t" * N + "b",
    "hash_a_ideographic_b": "# a" + "　" * N + "b",
    "hash_a_space_hash_b": "# a" + " #" * (N // 2) + "b",
    "hash_a_hash_space_b": "# a" + "# " * (N // 2) + "b",
    "hash_a_sp_hash_sp_b": "# a" + " " * (N // 3) + "#" * (N // 3) + " " * (N // 3) + "b",
    "hash_newlines_x": "#" + "\n" * N + "x",
    "hash_a_space_nl_b": "# a" + " \n" * (N // 2) + "b",
    "hashes_only": "#" * N,
    "spaces_only": " " * N,
    "newlines_only": "\n" * N,
    "hash_space_repeat": "# " * (N // 2),
    "indented4_lines": "    # x\n" * (N // 8),
}


@pytest.mark.parametrize("name", list(ADVERSARIAL))
def test_adversarial_1m_heading_scan_under_200ms(name):
    """제목 찾기(옛 `_HEADING` 자리)는 100만 자 적대 입력마다 0.2초 미만."""
    assert _best(Q._headings, ADVERSARIAL[name]) < 0.2


@pytest.mark.parametrize("name", list(ADVERSARIAL))
def test_adversarial_1m_plan_axis_queries_fast(name):
    """전체 함수도 선형. 100만 자 제목의 축 키워드 검색(선형)이 0.1초 남짓 들어 동시 부하 여유로 1초를 둔다."""
    text = ADVERSARIAL[name]
    assert _best(plan_axis_queries, text) < 1.0


@pytest.mark.parametrize("text", ["#\n" * (N // 2), "# a\n" * (N // 4), "## 데이터\n본문\n" * (N // 13)],
                         ids=["empty_headings", "short_headings", "axis_sections"])
def test_many_headings_1m_linear(text):
    """제목 줄이 수십만 개인 글도 선형(제목 수만큼 파이썬 반복이 돌아 0.2~0.3초대)."""
    assert _best(plan_axis_queries, text, rep=2) < 1.5
