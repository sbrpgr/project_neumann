"""DISP-1 회귀 방지(정적, 브라우저·서버 없음): 화면 원본에 astra 표시 문자열이 없고, 생성 방식 배지는 서버 표시 이름을 쓴다.

- 계약 값 ``astra``는 비교용 키(``g !== 'astra'``)·객체 키·CSS 클래스(``.gen.astra``)로만 남는다. 사람이 보는 문자열 리터럴·
  마크업 텍스트에는 없다(실제 화면 글자 검사는 ``test_display_generator.py``의 선택 스크린샷 테스트).
- 배지·집계는 서버가 내려 준 ``genl``·``_status.generator_labels``(``view.display_generator``)를 먼저 쓴다.
"""

from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "src" / "neumann" / "webui" / "index.html").read_text(encoding="utf-8")


def _script() -> str:
    blocks = re.findall(r"<script>(.*?)</script>", HTML, flags=re.S)
    assert blocks, "index.html에 인라인 스크립트가 없다"
    return re.sub(r"/\*.*?\*/", "", "\n".join(blocks), flags=re.S)  # 블록 주석은 화면에 안 나온다


def test_no_astra_in_displayed_strings() -> None:
    js = _script()
    literals = re.findall(r"'((?:[^'\\\n]|\\.)*)'", js)
    assert literals
    shown = [s for s in literals if "astra" in s.lower() and s != "astra"]  # 'astra' 그 자체는 비교용 키
    assert shown == [], shown
    lines = [ln for ln in js.splitlines() if re.search(r"//.*astra", ln, re.I)]
    assert lines == [], lines
    markup = re.sub(r"<(script|style)\b.*?</\1>|<!--.*?-->", "", HTML, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", markup)
    assert "astra" not in text.lower()
    for var in ("GEN", "FITGEN"):
        m = re.search(r"var " + var + r" = \{([^}]*)\};", js)
        assert m, var
        values = re.findall(r":\s*'([^']*)'", m.group(1))
        assert values and not any("astra" in v.lower() for v in values), (var, values)
        assert "mock provider" not in values, (var, values)  # mock은 "모의(mock)"


def test_badges_use_server_display_names() -> None:
    js = _script()
    calls = re.findall(r"genLabel\(([^()]*)\)", js)
    uses = [c for c in calls if not c.startswith("g,")]  # 정의(function genLabel(g, l)) 제외
    assert len(uses) >= 4, uses  # 카드·근거 패널 카드·예상 심사평·체크리스트
    assert all(re.fullmatch(r"(\w+)\.gen, \1\.genl", c) for c in uses), uses
    assert "D._status.generator_labels" in js  # 집계(추적 Generate·패널 경고)는 서버 이름
    assert "(GEN[g] || g)" not in js
    assert re.search(r"genTxt = Object\.keys\(gens\)\.map\(function \(g\) \{ return genName\(g\)", js)
