"""E4-L4r 정적 검사(브라우저 없이 verify에서 돈다): 수정 권고 블록·진입 훅·목업 데이터 블록의 신선도·외부 스크립트 없음."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.e4.revise_mock_data import BEGIN, BLOCK_RE, END, build_mock_final, current_block, render_block

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "src" / "neumann" / "webui" / "index.html"


def html() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_revise_block_and_hooks_present():
    h = html()
    assert "window.NeumannUI = {" in h and "setD: function (v) { D = v; }" in h, "주 스크립트의 내부 훅 한 줄"
    assert h.count("/* ===== E4-L4r 계획서 수정 권고(V) =====") == 1, "수정 권고 스크립트 블록 하나"
    assert "window.NeumannRevise = {" in h
    for marker in ("'premortem/revise'", "'premortem/revise/assemble'", "data-rstep", "수정 권고", "제안(근거 아님)", "대응 사례 없음",
                   "확인 필요", "깨끗한 원고", "각주 판", "rvViewer", "aria-modal", "localStorage", "?mock=final"):
        assert marker in h, marker


def test_revise_script_has_no_external_or_inline_html_from_server():
    h = html()
    start = h.index("/* ===== E4-L4r 계획서 수정 권고(V) =====")
    block = h[start:h.index("</script>", start)]
    assert not re.search(r"https?://", block), "수정 권고 블록에 외부 URL 없음"
    assigns = re.findall(r"\.innerHTML\s*=\s*([^;]+);", block)
    assert assigns == ["U.CHECK"], f"서버 문자열은 textContent로만(innerHTML 대입은 상수 SVG 한 곳): {assigns}"
    assert "eval(" not in block and "new Function" not in block


def test_mock_final_block_is_fresh_and_parseable():
    h = html()
    block = current_block(h)
    assert block, "목업 데이터 블록(id=rvMockFinal)이 index.html에 있어야 한다"
    inner = block[len(BEGIN):-len(END)]
    assert "</" not in inner, "JSON 안에 script 종료 문자열이 없어야 한다(<\\/ 로 바꿈)"
    data = json.loads(inner.replace("<\\/", "</"))
    fresh = build_mock_final()
    assert data["view"]["plan_id"] == fresh["view"]["plan_id"]
    assert [c["id"] for c in data["view"]["cards"]] == [c["id"] for c in fresh["view"]["cards"]]
    assert set(data["revisions"]) == set(fresh["revisions"]) and data["preset"] == fresh["preset"]
    assert "가짜 데이터" in data["note"]
    assert render_block(fresh) == block, "python tests/e4/revise_mock_data.py 로 다시 만들 것"
    assert len(BLOCK_RE.findall(h)) == 1
