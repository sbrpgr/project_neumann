"""E4-S06 입력 화면 전송 고지(SEC-1 S-06) 정적 검사.

index.html을 글자로 읽어 확인한다(브라우저 없이 기본 pytest에서 돈다).
- 고지 문구(라벨·한 줄 요약·전문 두 줄)가 글자 그대로 있고, 확인할 수 없는 약속(학습 미사용 등)은 없다.
- 고지 자리(#sendNote)가 입력 카드(#inCard) 안, 실행 버튼(#btnStart) 바로 앞에 있고, 모드별 입력 영역(area) 밖이라
  직접 입력·파일 업로드 두 모드에 같이 나온다.
- 고지 글은 textContent로만 들어간다(innerHTML·문자열 이어 붙이기 없음). 색은 토큰, 외부 요청 없음.
- (조건부) 결과를 파일로 캐시하는 서빙 층이 있으면, 그 저장본에서 본문을 떼는지 확인한다("본문 파일 저장 없음"의 근거).
화면에서 실제로 보이는지(첫 화면 viewport 안)는 ``test_notice_ui.py``(Playwright)가 잰다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = ROOT / "src" / "neumann" / "webui" / "index.html"
SERVING = ROOT / "src" / "neumann" / "api" / "serving.py"

SEND_LINE = "입력한 계획서는 분석을 위해 OpenAI API로 전송됩니다. 개인정보·미공개 기밀은 넣지 마세요."
STORE_LINE = "이 서버는 계획서 본문을 파일로 저장하지 않습니다."
SUMMARY = "OpenAI API로 전송 · 개인정보·미공개 기밀 입력 금지 · 본문 파일 저장 없음"
LABEL = "외부 전송"
# 우리가 직접 확인할 수 없는 약속, 또는 서빙 층 구현에 따라 거짓이 되는 보관 설명. 고지에 쓰지 않는다.
UNVERIFIABLE = ("학습에 쓰지", "학습에 사용하지", "학습하지 않", "모델 학습", "학습 미사용", "학습에 이용",
                "즉시 삭제", "영구 삭제", "암호화", "제3자", "안전하게 보호", "메모리에 잠시 보관", "보관")


@pytest.fixture(scope="module")
def html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _func(html: str, name: str) -> str:
    """`function name(...) {` 부터 같은 들여쓰기의 닫는 `}`까지 잘라 낸다."""
    m = re.search(r"\n( *)function " + re.escape(name) + r"\([^)]*\) \{", html)
    assert m, f"{name}() 없음"
    indent = m.group(1)
    end = html.find("\n" + indent + "}\n", m.end())
    assert end > 0, f"{name}() 끝을 못 찾음"
    return html[m.start():end + len(indent) + 2]


def _send_note_block(html: str) -> str:
    m = re.search(r"var SEND_NOTE = \{.*?\n  \};", html, re.S)
    assert m, "SEND_NOTE 정의 없음"
    return m.group(0)


def test_notice_text_exact(html: str) -> None:
    block = _send_note_block(html)
    assert f"'{SEND_LINE}'" in block
    assert f"'{STORE_LINE}'" in block
    assert f"summary: '{SUMMARY}'" in block
    assert f"label: '{LABEL}'" in block
    # 고지 글은 SEND_NOTE 한 곳에만 있다(다른 곳에서 HTML 문자열로 다시 쓰지 않음)
    for t in (SEND_LINE, STORE_LINE, SUMMARY):
        assert html.count(t) == 1, t


def test_notice_mentions_facts_only(html: str) -> None:
    block = _send_note_block(html)
    for w in UNVERIFIABLE:
        assert w not in block, f"확인할 수 없거나 구현 따라 거짓이 되는 문구: {w}"
    # 전문과 한 줄 요약이 같은 세 사실(전송 대상·모델, 입력 금지 대상, 본문 파일 미저장)을 모두 밝힌다
    for w in ("OpenAI API", "전송", "개인정보", "미공개 기밀", "본문"):
        assert w in SEND_LINE + STORE_LINE and w in SUMMARY, f"빠진 요소: {w}"
    assert "파일로 저장하지 않습니다" in STORE_LINE and "파일 저장 없음" in SUMMARY
    # 모델명은 넣지 않는다(제품 모델이 바뀌어도 사실이게. 2026-09-30 대표 지시: gpt-6-astra → gpt-6.1-sol)
    assert not re.search(r"gpt-|o\d-|astra|sol\b", block, re.I), "고지에 모델명"


def test_notice_inside_input_card_before_run_button(html: str) -> None:
    body = _func(html, "renderInput")
    i_card, i_note, i_btn = body.find('id="inCard"'), body.find('id="sendNote"'), body.find('id="btnStart"')
    assert i_card > 0 and i_note > 0 and i_btn > 0
    assert i_card < i_note < i_btn, "고지는 입력 카드 안, 실행 버튼 앞이어야 한다"
    # 실행 버튼 줄 바로 앞: 고지와 버튼 사이에는 버튼 줄의 여는 div 하나뿐
    between = body[i_note:i_btn]
    assert between.count("<div") == 1, between  # 버튼 줄의 여는 div
    assert "fitBox" not in between and "area" not in between
    # 모드별 영역(area = ...) 안에 있지 않다 → 직접 입력·업로드 공통
    for m in re.finditer(r"area = (.*?);\n", body, re.S):
        assert "sendNote" not in m.group(1)
    assert body.count('id="sendNote"') == 1


def test_notice_painted_with_textcontent(html: str) -> None:
    fn = _func(html, "paintSendNote")
    assert "innerHTML" not in fn and "insertAdjacentHTML" not in fn and "outerHTML" not in fn
    for want in ("textContent = SEND_NOTE.label", "textContent = SEND_NOTE.summary", "textContent = t",
                 "SEND_NOTE.lines.forEach", "createElement('summary')"):
        assert want in fn, want
    # 자리 표시는 빈 채로 문자열에 들어가고, 글은 렌더 직후 칠한다
    assert '<details class="sendnote" id="sendNote"></details>' in html
    render = _func(html, "render")
    assert "app.innerHTML = renderInput(); paintSendNote();" in render
    # SEND_NOTE가 HTML 문자열에 이어 붙지 않는다
    assert not re.search(r"['\"]\s*\+\s*SEND_NOTE", html)
    assert not re.search(r"SEND_NOTE[.\w\[\]]*\s*\+\s*['\"]", html)


def test_notice_style_tokens_and_sticky(html: str) -> None:
    rules = re.findall(r"^\s*\.sendnote[^{]*\{([^}]*)\}", html, re.M)
    assert len(rules) >= 5
    css = " ".join(rules)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "색은 :root 토큰만"
    assert "position: sticky" in css and "bottom: 0" in css
    assert "background: var(--card)" in css
    for bad in ("letter-spacing", "uppercase", "var(--mono)", "border-left", "border-radius"):
        assert bad not in css, f"디자인 규칙 위반: {bad}"
    # 긴 글 끝에서 치거나 붙여넣을 때 캐럿이 sticky 고지 밑으로 가지 않게(접힘·펼침 각각)
    assert re.search(r"^\s*html \{ scroll-padding-bottom: (\d+)px; \}", html, re.M)
    assert re.search(r"^\s*html:has\(#sendNote\[open\]\) \{ scroll-padding-bottom: (\d+)px; \}", html, re.M)
    closed = int(re.search(r"html \{ scroll-padding-bottom: (\d+)px", html).group(1))
    opened = int(re.search(r"html:has\(#sendNote\[open\]\) \{ scroll-padding-bottom: (\d+)px", html).group(1))
    assert closed >= 56 and opened > closed


def test_no_external_requests_in_page(html: str) -> None:
    assert not re.search(r"""(src|href)\s*=\s*["']\s*(https?:)?//""", html, re.I)
    assert not re.search(r"""url\(\s*["']?\s*(https?:)?//""", html, re.I)
    assert "@import" not in html
    assert not re.search(r"fetch\(\s*['\"](https?:)?//", html)


def test_result_file_cache_strips_plan_body() -> None:
    """'본문을 파일로 저장하지 않습니다'의 근거: 결과 파일 캐시(E4-L2c serving.py)가 있으면 저장본에서 본문을 뗀다.

    지금 main(8f77957)에는 serving.py가 없어 건너뛴다.
    """
    if not SERVING.exists():
        pytest.skip("serving.py 없음(E4-L2c 미병합): 결과 파일 캐시 없음")
    src = SERVING.read_text(encoding="utf-8")
    if "cache/results" not in src and "write_text" not in src:
        pytest.skip("serving.py에 결과 파일 쓰기 없음")
    assert re.search(r"def _strip_plan_body\(", src), "결과 파일 캐시가 본문을 떼는 함수(_strip_plan_body)가 없다"
    assert re.search(r"[\"']result[\"']\s*:\s*_strip_plan_body\(", src), (
        "결과 파일 캐시 저장본이 _strip_plan_body를 거치지 않는다 → 고지 '본문을 파일로 저장하지 않습니다'가 거짓이 된다")
