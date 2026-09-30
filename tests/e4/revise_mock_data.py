"""목업 모드(``index.html?mock=final``) embedded 데이터 생성기(E4-L4r).

    python tests/e4/revise_mock_data.py            # index.html의 <script id="rvMockFinal"> 블록을 새로 쓴다
    python tests/e4/revise_mock_data.py --check    # 블록이 생성 결과와 같은지만 본다(종료 코드)

내용: 공용 fixture(가짜 데이터)로 만든 화면 뷰(test_view_shots.rich_view, 샘플 표시 유지) + 카드 2장의 수정 권고 응답
(계약 revision.schema.json 모양, test_revise_ui.build_revision: 카드 2는 카드 1과 같은 줄 충돌 + [확인 필요] 자리표시) +
미리 적용할 결정(채택 1 · 직접 수정 1 · 기각 1 · 카드 2 채택 2 → 충돌 1 남김). 화면은 서버를 부르지 않고 이 블록만 읽는다.
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
BEGIN = '<!-- E4-L4r 목업 데이터(?mock=final) — tests/e4/revise_mock_data.py가 만든다. 손으로 고치지 않는다 -->\n<script type="application/json" id="rvMockFinal">'
END = "</script>"
BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)


"""FIN-UI: 목업 계획서에 6~8절(일정·예산·참고문헌)을 덧붙인다. 최종 점검(⑤) 시연용 **의도적 오류**가 들어 있다(전부 가짜):
- 구조: 2단계가 3단계 결과를, 3단계가 2단계 결과를 요구 → 선행관계 순환
- 논리: 예산 항목 합 1억 1,000만원 ≠ 기재 1억 2,000만원 / 250 mL × 40회 = 10 L ≠ 기재 8 L
- 물리: 상온 25 K(온도 단위) / 이온전도도(mS/cm)+점도(mPa·s) 합산(차원 불일치)
- 근거: 참고문헌 [3]은 fixture에서 철회 기록(인용·철회 조회)
원래 1~5절 줄 번호(16·17·22행)는 그대로라 위험카드·수정 권고 fixture가 그대로 맞는다."""
EXTRA_PLAN = """
## 6. 일정과 절차

1단계(1~6개월)에 데이터 수집과 정제를 마친다.
2단계(7~12개월)의 GNN 학습은 3단계 검증 실험의 측정값이 확보된 후 시작한다.
3단계(13~18개월)의 검증 실험은 2단계 학습 모델이 고른 후보 조성을 대상으로 수행한다.
총 연구 기간은 18개월이다.

## 7. 예산과 실험 규모

인건비 5,000만원, 장비비 4,000만원, 재료비 2,000만원을 합산해 총 예산은 1억 2,000만원이다.
전해액 시료는 1회당 250 mL 씩 총 40회 합성하여 합계 8 L를 사용한다.
목표 이온전도도는 상온(25 K)에서 12 mS/cm 이상이다.
모델 선별 지표는 예측 이온전도도(mS/cm)와 점도(mPa·s)를 더한 값으로 정의한다.

## 8. 참고문헌

[1] [FAKE] EquiMol: equivariant message passing for molecular property prediction. FakeConf 2099.
[2] [FAKE] Scaffold-aware contrastive pretraining for small-molecule GNNs. FakeConf 2099.
[3] [FAKE] Uncertainty-calibrated GNN ensembles for aqueous solubility prediction. FakeConf 2099.
"""


def extend_plan(view: dict, text: str) -> str:
    """계획서 본문 끝에 EXTRA_PLAN을 붙이고 view.plan.lines(n=원문 줄 번호, 빈 줄 제외)를 이어 쓴다."""
    base = text if text.endswith("\n") else text + "\n"
    full = base + EXTRA_PLAN.lstrip("\n")
    lines = view["plan"]["lines"]
    start = len(base.split("\n"))  # 다음 줄의 1-based 번호(base 끝의 개행 뒤)
    for i, raw in enumerate(EXTRA_PLAN.lstrip("\n").split("\n")):
        if not raw.strip():
            continue
        row = {"n": start + i, "t": raw}
        if raw.startswith("#"):
            row["h"] = "h"
        lines.append(row)
    view["plan"]["meta"] = f"정규화 {len(lines)}줄"
    view["plan"]["size"] = f"{len(full.encode('utf-8')) / 1024:.1f} KB"
    return full


def build_mock_final() -> dict:
    from tests.e4.test_revise_ui import build_revision
    from tests.e4.test_view_shots import rich_view
    from tests.fixtures.loader import plan_text

    view = rich_view()
    view.pop("result", None)  # 목업은 서버를 부르지 않는다(원결과 불필요)
    full_text = extend_plan(view, plan_text())
    for g in view.get("pipeline", []):  # 단계 소요 시간은 실행마다 달라 블록이 흔들린다 → 0으로(목업 표시용)
        g["ms"] = 0
    view.setdefault("kpi", {})["elapsed_s"] = 0
    view.setdefault("_status", {})["server_elapsed_s"] = 0
    c1, c2 = view["cards"][0], view["cards"][1]
    revisions = {c1["id"]: build_revision(view, c1), c2["id"]: build_revision(view, c2, conflict_line=c1["lines"][0])}
    preset = [
        {"rank": 1, "edit_id": f"{c1['id']}/e1", "d": "adopt"},
        {"rank": 1, "edit_id": f"{c1['id']}/e2", "d": "edit",
         "text": "연구자가 직접 고친 문장: 조성 그룹 단위로 분할하고 근사 중복 조성은 분할 전에 제거하며, 제거 건수를 [확인 필요: 보고 시점]에 보고한다."},
        {"rank": 1, "edit_id": f"{c1['id']}/e3", "d": "reject"},
        {"rank": 2, "edit_id": f"{c2['id']}/e2", "d": "adopt"},
        {"rank": 2, "edit_id": f"{c2['id']}/e4", "d": "adopt"},
    ]
    return {"note": "디자인 점검용 목업 · 공용 fixture(가짜 데이터) · 서버 호출 없음", "view": view, "plan_text": full_text,
            "revisions": revisions, "preset": preset}


def render_block(data: dict) -> str:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return BEGIN + body + END


def current_block(html: str) -> str | None:
    m = BLOCK_RE.search(html)
    return m.group(0) if m else None


def embed(html_path: Path = INDEX) -> tuple[bool, int]:
    """블록을 새로 쓴다. (바뀌었나, 블록 바이트 수)."""
    html = html_path.read_text(encoding="utf-8")
    block = render_block(build_mock_final())
    if current_block(html):
        new = BLOCK_RE.sub(lambda _m: block, html, count=1)
    else:
        anchor = "\n<script>\n/* ===== E4-L4r 계획서 수정 권고(V) ====="
        assert html.count(anchor) == 1, "수정 권고 스크립트 블록 앞에 넣을 자리를 찾지 못함"
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
        html = INDEX.read_text(encoding="utf-8")
        same = current_block(html) == render_block(build_mock_final())
        print("mock block", "fresh" if same else "STALE")
        return 0 if same else 1
    changed, n = embed()
    print("mock block", "written" if changed else "unchanged", n, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
