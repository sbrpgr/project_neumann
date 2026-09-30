"""FIN-UI 정적 검사(브라우저 없이 verify에서 돈다): 최종 점검·초안(VI) 블록 · ④ 버튼 훅 · 목업 fixture 블록 신선도 · textContent만 · 외부 URL 없음 ·
서버 계약 경로/본문 키(Codex codex/final-ui-20261001 2ac62f8과 같은 rvFinalize · premortem/revise/finalize · submission_id · confirmed_text · confirmed_base_id)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.e4.fin_mock_data import BEGIN, BLOCK_RE, END, build_fin_mock, current_block, render_block
from tests.e4.revise_mock_data import EXTRA_PLAN, build_mock_final

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "src" / "neumann" / "webui" / "index.html"
MARK = "/* ===== FIN-UI 최종 점검·초안(VI) ====="


def html() -> str:
    return INDEX.read_text(encoding="utf-8")


def fin_block(h: str) -> str:
    start = h.index(MARK)
    return h[start:h.index("</script>", start)]


def test_fin_block_and_hooks_present():
    h = html()
    assert h.count(MARK) == 1, "최종 점검 스크립트 블록 하나"
    assert h.count('<style id="finStyle">') == 1
    assert "window.NeumannFinal = {" in h
    # ④ 버튼(수정 권고 요약 + 뷰어 바)과 무효화 훅, 확정 문안 export
    assert "'수정 확정·검증 →', 'rvFinalize'" in h and "'rvFinalize2'" in h
    assert "if (window.NeumannFinal) window.NeumannFinal.invalidate();" in h
    assert "confirmed: confirmed" in h and "assembleBody: assembleBody" in h
    for marker in ("dataset.view = 'final'", "'premortem/revise/finalize'", "submission_id", "confirmed_text", "confirmed_base_id", "finMockFinal",
                   "논리 → 물리 → 구조 → 근거 → 교정 → 재검사", "도구 호출 기록", "최종 초안", "전후 비교", "anchor_mismatch", "unsupported_content",
                   "waitHook", "window.NeumannWait", "data-mockat", "finSamples", "300자", "HWPX", "stpFinal", "role', 'log'"):
        assert marker in h, marker


def test_fin_script_uses_textcontent_only_and_no_external():
    block = fin_block(html())
    assert not re.search(r"https?://", block), "외부 URL 없음"
    assigns = re.findall(r"\.innerHTML\s*=\s*([^;]+);", block)
    assert assigns == ["U.CHECK"], f"서버·fixture 문자열은 textContent로만(innerHTML 대입은 상수 SVG 한 곳): {assigns}"
    assert "eval(" not in block and "new Function" not in block and "document.write" not in block
    assert "window.open(" not in block


def test_fin_mock_block_is_fresh_and_contract_shaped():
    h = html()
    block = current_block(h)
    assert block, "목업 최종 점검 데이터 블록(id=finMockFinal)이 index.html에 있어야 한다"
    inner = block[len(BEGIN):-len(END)]
    assert "</" not in inner
    data = json.loads(inner.replace("<\\/", "</"))
    fresh = build_fin_mock()
    assert render_block(fresh) == block, "python tests/e4/fin_mock_data.py 로 다시 만들 것"
    assert len(BLOCK_RE.findall(h)) == 1
    assert "가짜" in data["note"]
    fz = data["finalization"]
    assert fz["version"] == "finalization@v1" and fz["status"] in ("completed", "partial", "incomplete")
    assert fz["generator"] == "mock" and data["origin"] in ("server_signed", "client_submitted_unverified") and data["finalization_sig"] is None
    for row in fz["tool_checks_before"] + fz["tool_checks_after"]:
        assert {"check_id", "kind", "tool", "status", "plan_lines", "message", "details"} <= set(row)
        assert row["status"] in ("passed", "failed", "unchecked")
    assert 1 <= len(fz["corrections"]) <= 8 and all({"line", "before", "after", "applied", "reason"} <= set(c) for c in fz["corrections"])
    assert any(not c["applied"] for c in fz["corrections"]), "게이트가 제외한 교정 예시 하나 이상"
    counters = fz["counters"]
    assert all(0 <= counters[k] <= 1 for k in ("assessment_calls", "correction_calls", "correction_batches", "recheck_runs"))
    stages = [s["id"] for s in data["stages"]]
    assert stages == ["logic", "physics", "structure", "evidence", "correct", "recheck"]
    tools = {e["tool"] for e in data["trace"]}
    assert {"calc", "z3", "pint", "networkx", "records", "sandbox"} <= tools, "계산기·합계·단위·구조·인용·철회·제한 실행이 기록에 있어야 한다"
    assert all(e["stage"] in stages for e in data["trace"]) and [e["t"] for e in data["trace"]] == sorted(e["t"] for e in data["trace"])


def test_fin_mock_corrections_anchor_to_plan_lines():
    """교정의 before는 목업 계획서의 실제 줄이어야 앵커가 맞는다. 의도적 오류 줄(6~8절)은 rvMockFinal 계획서에 있어야 한다."""
    plan = build_mock_final()
    lines = {row["n"]: row["t"] for row in plan["view"]["plan"]["lines"]}
    for c in build_fin_mock()["finalization"]["corrections"]:
        assert lines.get(c["line"]) == c["before"], (c["line"], c["before"])
    text = plan["plan_text"]
    for needle in ("1억 2,000만원", "합계 8 L", "상온(25 K)", "점도(mPa·s)를 더한", "3단계 검증 실험의 측정값이 확보된 후", "[3] [FAKE]"):
        assert needle in text and needle in EXTRA_PLAN
    assert [row["n"] for row in plan["view"]["plan"]["lines"] if row["n"] <= 27] == [1, 3, 5, 6, 8, 10, 11, 13, 15, 16, 17, 19, 21, 22, 23, 25, 27], "1~5절 줄 번호 불변(위험카드 16·17·22행)"
