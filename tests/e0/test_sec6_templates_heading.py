"""SEC-6: 템플릿 칸 이름 뽑기(`api.templates.sections`)가 선형이고, 정상 골격·예시 파일에서는 옛 결과와 같다.

옛 구현은 `^##\\s+(?:\\d+\\.\\s*)?(.+?)\\s*$`(re.M)였고 "## a" + 공백 N개 + "." 에서 제곱 시간이었다.
"""

from __future__ import annotations

import random
import re
import time
from pathlib import Path

import pytest

from neumann.api import templates as T

_OLD = re.compile(r"^##\s+(?:\d+\.\s*)?(.+?)\s*$", re.M)
FILES = sorted(T.DATA_DIR.glob("*.md")) + sorted((T.DATA_DIR / "examples").glob("*.md")) + sorted(
    (Path(__file__).resolve().parents[1] / "fixtures/plans").glob("*.md")
)


def _old_sections(text: str) -> list[str]:
    return [m.group(1) for m in _OLD.finditer(text)]


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_real_files_same_as_old(path):
    text = T._read(path)
    assert T.sections(text) == _old_sections(text)


_NAMES = ["연구 목표", "방법", "데이터", "평가", "기대 성과", "Background", "1.5 배경", "2024년 계획", "a", "C# 구현 ##"]


def _doc(rng: random.Random) -> str:
    lines = []
    for _ in range(rng.randint(0, 20)):
        r = rng.random()
        if r < 0.35:
            num = rng.choice(["", "", "1. ", "12. ", "3.", "4.  ", "١. "])
            lines.append("##" + rng.choice([" ", "  ", "\t", "　"]) + num + rng.choice(_NAMES)
                         + rng.choice(["", "", " ", "  \t"]))
        elif r < 0.45:
            lines.append(rng.choice(["# 제목", "### 소제목", "##없음", " ## 들여쓰기", "####### x"]))
        elif r < 0.6:
            lines.append("")
        else:
            lines.append(rng.choice(["본문 한 줄.", "- 항목", "1. 순서", "`code`", "  공백으로 시작"]))
    return "\n".join(lines) + rng.choice(["", "\n", "\n\n"])


def test_random_markdown_same_as_old():
    rng = random.Random(20260930)
    for _ in range(500):
        doc = _doc(rng)
        assert T.sections(doc) == _old_sections(doc), repr(doc)


@pytest.mark.parametrize(
    ("text", "old", "new"),
    [
        ("##\n방법\n본문", ["방법"], []),  # 옛 `\s+`가 줄을 넘어 다음 줄을 칸 이름으로 삼았다
        ("## \n## 2. 평가", ["## 2. 평가"], ["평가"]),
        ("## 1.   ", [" "], ["1."]),  # 옛: 번호 뒤 공백 한 칸이 이름이 됐다
        ("##  ", [" "], []),
    ],
)
def test_documented_differences(text, old, new):
    assert _old_sections(text) == old
    assert T.sections(text) == new


N = 1_000_000


@pytest.mark.parametrize(
    "text",
    [
        "## a" + " " * N + ".",
        "## 1." + " " * N + ".",
        "## a" + "\t " * (N // 2) + "x",
        "##" + " " * N,
        "## " * (N // 3),
        "##\n" * (N // 3),
        "## a\n" * (N // 5),
    ],
    ids=["a_spaces_dot", "num_spaces_dot", "a_tabs_x", "hash_spaces", "hash_space_repeat", "empty_lines", "many"],
)
def test_adversarial_1m_under_200ms(text):
    best = min(_timed(text) for _ in range(3))
    assert best < 0.2


def _timed(text: str) -> float:
    t0 = time.perf_counter()
    T.sections(text)
    return time.perf_counter() - t0
