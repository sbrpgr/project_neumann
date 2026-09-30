"""FIN-UI 목업 최종 점검 fixture 생성기 — index.html의 ``<script id="finMockFinal">`` 블록.

    python tests/e4/fin_mock_data.py            # 블록을 새로 쓴다
    python tests/e4/fin_mock_data.py --check    # 블록이 생성 결과와 같은지만 본다(종료 코드)

내용(전부 가짜): ④ "수정 확정·검증" 뒤 ⑤ 최종 점검이 단계별(논리·물리·구조·근거·교정·재검사)로 돌며 부른 **도구 호출 기록(trace)**
(이름·입력·결과·상태·줄), ⑥ 최종 초안의 **교정(corrections)**(원문 → 수정 · 이유 · 도구 근거), 쟁점(issues)과 상태(해결·미해결·확인 필요).
모양은 contracts/finalization.schema.json(finalization@v1)의 finalization 객체를 따르되, 화면용 확장 두 가지를 더한다:
- ``trace[]``: 화면 로그 한 줄 = {t, stage, tool, name, check_id, kind, plan_lines, input, result, status, message, ms}
- ``corrections[].before/after``는 **원문 줄 문자열로 앵커**한다(줄 번호는 표시용). 연구자가 ③에서 문안을 바꾸면 앵커가 안 맞는 교정은
  화면이 "적용 못 함 · 원문이 달라짐"으로 표시한다(엔진의 anchor_mismatch와 같은 뜻).
FIN-ENGINE이 실제 fixture를 커밋하면 이 생성기를 그 fixture를 읽도록 바꾸고 화면 어댑터(normFinal)는 그대로 둔다.
JSON 안의 ``</``는 ``<\\/``로 바꿔 넣는다(script 종료 방지).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

INDEX = ROOT / "src" / "neumann" / "webui" / "index.html"
BEGIN = '<!-- FIN-UI 목업 최종 점검 데이터(?mock=final) — tests/e4/fin_mock_data.py가 만든다. 손으로 고치지 않는다 -->\n<script type="application/json" id="finMockFinal">'
END = "</script>"
BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)

STAGES = [
    {"id": "logic", "name": "논리 점검", "desc": "합계·곱·비율 같은 수치 제약을 Z3로 확인"},
    {"id": "physics", "name": "물리 점검", "desc": "단위·차원·물리 범위를 Pint로 확인"},
    {"id": "structure", "name": "구조 점검", "desc": "절 번호 연속성과 선행관계 그래프(순환)를 NetworkX로 확인"},
    {"id": "evidence", "name": "근거 점검", "desc": "참고문헌·근거의 철회·거절 기록 조회(로컬 기록) · 채택 수정안의 근거 연결"},
    {"id": "correct", "name": "교정 적용", "desc": "원문 앵커가 맞는 줄만 고치고, 모르는 값은 [확인 필요]로 남김 · 새 내용은 게이트가 제외"},
    {"id": "recheck", "name": "대상 재검사", "desc": "고친 줄에 연결된 검사만 다시 실행"},
]

TOOLS = {
    "z3": "합계·제약 (Z3)", "pint": "단위·차원 (Pint)", "networkx": "구조·선행관계 (NetworkX)",
    "records": "인용·철회 조회 (로컬 기록)", "llm": "자동 수정 (시험 모드)",
}


def line_map() -> dict[int, str]:
    from tests.e4.revise_mock_data import build_mock_final
    return {row["n"]: row["t"] for row in build_mock_final()["view"]["plan"]["lines"]}


LABELS = {
    "split-sizes": "분할 건수 계산", "split-ratio-sum": "분할 비율 합계", "budget-sum": "예산 항목 합계", "sample-volume": "시료 부피 합계",
    "schedule-months": "단계 기간 합계", "room-temp": "상온 온도 단위", "conductivity-unit": "이온전도도 단위 차원", "metric-dimension": "선별 지표 차원 합산",
    "stage-order": "단계 선행관계 순환", "section-numbering": "절 번호 연속", "ref-3-retraction": "참고문헌 [3] 철회 조회", "ref-1-status": "참고문헌 [1] 결정 조회",
    "ref-2-status": "참고문헌 [2] 결정 조회", "adopted-edits-grounding": "채택 문안 근거 연결", "correction-batch": "자동 수정 1묶음",
}


def ev(t: float, stage: str, tool: str, check_id: str, kind: str, lines: list[int], inp: str, res: str, status: str, msg: str, ms: int) -> dict:
    return {"t": t, "stage": stage, "tool": tool, "name": TOOLS[tool], "check_id": check_id, "label": LABELS[check_id], "kind": kind, "plan_lines": lines,
            "input": inp, "result": res, "status": status, "message": msg, "ms": ms}


def build_fin_mock() -> dict:
    L = line_map()
    trace = [
        # ⑤-1 논리
        ev(0.7, "logic", "z3", "split-ratio-sum", "constraint", [16], "80 + 10 + 10 == 100", "sat", "passed", "분할 비율 합계 일치", 12),
        ev(1.2, "logic", "z3", "budget-sum", "constraint", [37], "5000 + 4000 + 2000 == 12000  (만원)", "unsat · 좌변 11000", "failed",
           "예산 항목 합 1억 1,000만원 ≠ 기재 총액 1억 2,000만원", 15),
        ev(1.7, "logic", "z3", "sample-volume", "constraint", [38], "250 mL × 40회", "10,000 mL = 10 L  (기재 8 L)", "failed",
           "시료 합계가 회당 부피 × 횟수와 다름", 3),
        ev(2.1, "logic", "z3", "schedule-months", "constraint", [30, 31, 32, 33], "6 + 6 + 6 == 18", "18 = 18", "passed", "단계 기간 합이 총 기간과 일치", 2),
        # ⑤-2 물리
        ev(2.7, "physics", "pint", "room-temp", "units", [39], "25 K → °C", "-248.15 °C · 상온 범위(293–298 K) 밖", "failed",
           "‘상온(25 K)’ — 25 °C(298 K)의 단위 오기로 보임", 18),
        ev(3.1, "physics", "pint", "conductivity-unit", "units", [39, 21], "12 mS/cm → S/m", "1.2 S/m · 차원 [conductance/length] 정상", "passed",
           "이온전도도 단위 차원 정상", 9),
        ev(3.6, "physics", "pint", "metric-dimension", "units", [40], "1 mS/cm + 1 mPa·s", "DimensionalityError: [conductivity] ≠ [viscosity]", "failed",
           "전도도와 점도는 차원이 달라 더할 수 없음", 11),
        # ⑤-3 구조
        ev(4.2, "structure", "networkx", "stage-order", "dependency", [31, 32],
           "nodes: 1단계·2단계·3단계 · edges: 3단계→2단계(측정값 확보 후 시작), 2단계→3단계(학습 모델 후보 대상)",
           "cycle: 2단계 → 3단계 → 2단계 (is_directed_acyclic_graph = False)", "failed", "2단계와 3단계가 서로를 선행 조건으로 요구", 7),
        ev(4.6, "structure", "networkx", "section-numbering", "structure", [3, 8, 13, 19, 25, 28, 35, 42], "## 1 … ## 8", "1→8 연속 · 중복 없음 · 빈 절 없음", "passed",
           "절 번호 연속", 1),
        # ⑤-4 근거
        ev(5.2, "evidence", "records", "ref-3-retraction", "citation", [46], "fixture:gnn-003 (참고문헌 [3])",
           "철회 기록 있음 · post_status: retracted · FakeConf 2099", "failed", "철회된 문헌을 인용", 22),
        ev(5.5, "evidence", "records", "ref-1-status", "citation", [44], "fixture:gnn-001 (참고문헌 [1])", "결정: 거절 · 철회 아님", "failed",
           "거절된 논문을 주요 근거로 인용 — 근거로 삼을 때 주의(교정 제안 없음, 연구자 판단)", 20),
        ev(5.8, "evidence", "records", "ref-2-status", "citation", [45], "fixture:gnn-002 (참고문헌 [2])", "Poster 채택 · 철회 없음", "passed", "인용 가능", 19),
        ev(6.2, "evidence", "records", "adopted-edits-grounding", "evidence", [16, 17, 22], "채택·수정한 문안 3건의 근거 번호",
           "근거 연결 3/3 · 자리표시 [확인 필요: 개수] 1곳 미입력", "unchecked", "채택 문안의 근거는 연결됨 · 자리표시는 연구자 확인 필요", 6),
        # ⑤-5 교정
        ev(6.9, "correct", "llm", "correction-batch", "correction", [31, 32, 37, 38, 39, 40, 46], "issues 7 · tool_checks 14 · edits ≤ 8 · 앵커 = 원문 줄 그대로",
           "edits 7 · 앵커 일치 7 · 게이트 통과 6 · 제외 1 (unsupported_content: 32행 ‘논문으로 발표’ 새 내용)", "passed",
           "새 사실은 만들지 않고 [확인 필요]로 남김", 1840),
        # ⑤-6 재검사
        ev(7.6, "recheck", "networkx", "stage-order", "dependency", [31, 32], "edges: 1단계→2단계, 2단계→3단계", "acyclic (is_directed_acyclic_graph = True)", "passed",
           "순환 해소", 6),
        ev(7.9, "recheck", "z3", "budget-sum", "constraint", [37], "총액이 [확인 필요]로 바뀜", "수치 없음 → 재검사 불가", "unchecked", "연구자가 값을 확정하면 다시 검사", 1),
        ev(8.1, "recheck", "pint", "room-temp", "units", [39], "온도가 [확인 필요]로 바뀜", "수치 없음 → 재검사 불가", "unchecked", "연구자가 값을 확정하면 다시 검사", 1),
        ev(8.3, "recheck", "pint", "metric-dimension", "units", [40], "결합 방식이 [확인 필요]로 바뀜", "수식 없음 → 재검사 불가", "unchecked", "연구자가 결합 방식을 확정하면 다시 검사", 1),
    ]
    issues = [
        {"issue_id": "budget-sum", "kind": "logical", "plan_lines": [37], "message": "예산 항목 합(1억 1,000만원)과 총액(1억 2,000만원)이 다르다.", "check_ids": ["budget-sum"], "status": "unchecked"},
        {"issue_id": "sample-volume", "kind": "logical", "plan_lines": [38], "message": "250 mL × 40회 = 10 L인데 합계를 8 L로 적었다.", "check_ids": ["sample-volume"], "status": "unchecked"},
        {"issue_id": "room-temp", "kind": "physical", "plan_lines": [39], "message": "상온을 25 K로 적었다(−248 °C). 25 °C(298 K)인지 확인이 필요하다.", "check_ids": ["room-temp"], "status": "unchecked"},
        {"issue_id": "metric-dimension", "kind": "physical", "plan_lines": [40], "message": "이온전도도(mS/cm)와 점도(mPa·s)는 차원이 달라 더할 수 없다.", "check_ids": ["metric-dimension"], "status": "unchecked"},
        {"issue_id": "stage-order", "kind": "structural", "plan_lines": [31, 32], "message": "2단계가 3단계 결과를, 3단계가 2단계 결과를 요구해 선행관계가 순환한다.", "check_ids": ["stage-order"], "status": "resolved"},
        {"issue_id": "ref-3-retraction", "kind": "evidence", "plan_lines": [46], "message": "참고문헌 [3]은 철회 기록이 있는 문헌이다.", "check_ids": ["ref-3-retraction"], "status": "unchecked"},
        {"issue_id": "ref-1-status", "kind": "evidence", "plan_lines": [44], "message": "참고문헌 [1]은 거절된 논문이다. 근거로 삼을지는 연구자 판단이며 교정을 제안하지 않았다.", "check_ids": ["ref-1-status"], "status": "unresolved"},
        {"issue_id": "seed-placeholder", "kind": "logical", "plan_lines": [22], "message": "채택한 반복 실험 문안의 시드 개수가 [확인 필요]로 남아 있다.", "check_ids": ["adopted-edits-grounding"], "status": "unchecked"},
    ]

    def corr(no: int, after: str, checks: list[str], issue: str, applied: bool = True, reason: str = "applied") -> dict:
        return {"line": no, "before": L[no], "after": after if applied else "[검사에서 제외된 수정안]", "proposed": after, "applied": applied,
                "reason": reason, "issue_ids": [issue], "check_ids": checks}

    corrections = [
        corr(37, "인건비 5,000만원, 장비비 4,000만원, 재료비 2,000만원을 합산해 총 예산은 [확인 필요: 항목 합 1억 1,000만원 ≠ 기재 1억 2,000만원 — 총액 또는 항목 수정]이다.", ["budget-sum"], "budget-sum"),
        corr(38, "전해액 시료는 1회당 250 mL 씩 총 40회 합성하여 합계 [확인 필요: 250 mL × 40회 = 10 L, 기재 8 L]를 사용한다.", ["sample-volume"], "sample-volume"),
        corr(39, "목표 이온전도도는 상온([확인 필요: 25 K는 −248 °C — 25 °C(298 K)인지 확인])에서 12 mS/cm 이상이다.", ["room-temp"], "room-temp"),
        corr(40, "모델 선별 지표는 예측 이온전도도(mS/cm)와 점도(mPa·s)를 [확인 필요: 차원이 달라 단순 합산 불가 — 정규화·가중 결합 방식]으로 결합한 값으로 정의한다.", ["metric-dimension"], "metric-dimension"),
        corr(31, "2단계(7~12개월)의 GNN 학습은 1단계 데이터로 시작하고, 3단계 검증 실험의 측정값은 [확인 필요: 재학습 반영 시점]에 반영한다.", ["stage-order"], "stage-order"),
        corr(32, "3단계(13~18개월)의 검증 실험은 2단계 학습 모델이 고른 후보 조성을 대상으로 수행하며, 결과는 논문으로 발표한다.", ["stage-order"], "stage-order",
             applied=False, reason="unsupported_content"),
        corr(46, "[3] [FAKE] Uncertainty-calibrated GNN ensembles for aqueous solubility prediction. FakeConf 2099. [확인 필요: 철회 기록 있음 — 대체 문헌 또는 인용 제거]", ["ref-3-retraction"], "ref-3-retraction"),
    ]
    before = [{"check_id": e["check_id"], "kind": e["kind"], "tool": e["tool"], "status": e["status"], "plan_lines": e["plan_lines"], "message": e["message"],
               "details": {"input": e["input"], "result": e["result"], "ms": e["ms"]}} for e in trace if e["stage"] in ("logic", "physics", "structure", "evidence")]
    after = [{"check_id": e["check_id"], "kind": e["kind"], "tool": e["tool"], "status": e["status"], "plan_lines": e["plan_lines"], "message": e["message"],
              "details": {"input": e["input"], "result": e["result"], "ms": e["ms"]}} for e in trace if e["stage"] == "recheck"]
    return {
        "note": "디자인 점검용 목업 · 가짜 데이터 · 서버 호출 없음 · 도구 실행 기록도 가짜(실제 Z3·Pint·NetworkX 실행 아님)",
        "stages": STAGES, "tools": TOOLS, "trace": trace,
        "finalization": {"version": "finalization@v1", "status": "partial", "issues": issues, "tool_checks_before": before, "tool_checks_after": after,
                         "corrections": corrections, "counters": {"assessment_calls": 1, "correction_calls": 1, "correction_batches": 1, "recheck_runs": 1},
                         "generator": "mock", "model": "mock-deterministic-v1",
                         "notices": ["최종 초안입니다. 제한된 검사 범위이며 모든 오류의 부재를 보장하지 않습니다.",
                                     "mock 테스트 결과이며 실제 LLM의 과학적 검토가 아닙니다.",
                                     "도구는 명시된 수치·단위·선행관계만 검사한다 · 연구 전체의 타당성을 보증하지 않는다"]},
        "origin": "client_submitted_unverified", "finalization_sig": None,
    }


def render_block(data: dict) -> str:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return BEGIN + body + END


def current_block(html: str) -> str | None:
    m = BLOCK_RE.search(html)
    return m.group(0) if m else None


def embed(html_path: Path = INDEX) -> tuple[bool, int]:
    html = html_path.read_text(encoding="utf-8")
    block = render_block(build_fin_mock())
    if current_block(html):
        new = BLOCK_RE.sub(lambda _m: block, html, count=1)
    else:
        anchor = "\n<script>\n/* ===== FIN-UI 최종 점검·초안(VI) ====="
        assert html.count(anchor) == 1, "최종 점검 스크립트 블록 앞에 넣을 자리를 찾지 못함"
        new = html.replace(anchor, "\n" + block + anchor, 1)
    changed = new != html
    if changed:
        html_path.write_text(new, encoding="utf-8", newline="\n")
    return changed, len(block.encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        same = current_block(INDEX.read_text(encoding="utf-8")) == render_block(build_fin_mock())
        print("fin mock block", "fresh" if same else "STALE")
        return 0 if same else 1
    changed, n = embed()
    print("fin mock block", "written" if changed else "unchanged", n, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
