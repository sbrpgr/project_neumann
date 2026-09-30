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


def build_mock_final() -> dict:
    from tests.e4.test_revise_ui import build_revision
    from tests.e4.test_view_shots import rich_view
    from tests.fixtures.loader import plan_text

    view = rich_view()
    view.pop("result", None)  # 목업은 서버를 부르지 않는다(원결과 불필요)
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
    return {"note": "디자인 점검용 목업 · 공용 fixture(가짜 데이터) · 서버 호출 없음", "view": view, "plan_text": plan_text(),
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
