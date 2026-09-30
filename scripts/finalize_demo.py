"""FIN-ENGINE 시연 fixture: 오류를 심은 계획서 → (가짜 fixture 분석 결과) → mock 수정 권고 → 연구자 결정 → 조립 → 최종 점검·교정.

    python scripts/finalize_demo.py            # docs/reports/FIN-ENGINE_demo.json · FIN-ENGINE_demo_final.md 를 쓴다
    python scripts/finalize_demo.py --check    # 파일이 현재 코드의 결과와 같은지(시각 등 가변 필드 제외) 본다

FIN-UI 목업 입력이다. 실제 OpenAI 호출 없음(mock). 분석 결과는 공용 fixture(가짜 데이터)에 시연 계획서를 붙인 것이고,
최종 결과의 generator는 mock이다. 서명 확인이 없는 입력이라 origin은 client_submitted_unverified다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

OUT_JSON = ROOT / "docs" / "reports" / "FIN-ENGINE_demo.json"
OUT_MD = ROOT / "docs" / "reports" / "FIN-ENGINE_demo_final.md"
VOLATILE = {"generated_at", "elapsed_s", "server_elapsed_s", "decided_at", "session_id", "ticket"}


def build() -> dict[str, Any]:
    os.environ.setdefault("NEUMANN_LLM_PROVIDER", "mock")
    os.environ["NEUMANN_DEMO_SCRIPT"] = "1"  # 시연 대본 mock은 이 플래그로만 켜진다(운영 기본 꺼짐)
    from neumann.analyze.finalize_demo import DEMO_ID, DEMO_PLAN, DEMO_TITLE
    from neumann.analyze.revise import revise_result
    from neumann.api import finalize as finalize_api
    from scripts.serve_fake_app import fake_result
    from tests.e3.revise_fixtures import make_store

    result = fake_result(DEMO_PLAN)  # 공용 fixture 결과 + 시연 계획서의 plan_id·줄(내용은 [FAKE])
    revision = revise_result(result, plan_text=DEMO_PLAN, provider="mock", store=make_store())
    # 연구자 결정: 오류를 심은 줄(가설↔방법 모순·선행 순환)을 덮는 카드 제안은 기각, 데이터 절 제안은 채택
    keep = {"데이터 정제", "모델 학습", "높을수록"}
    decisions = []
    for rev in revision["revisions"]:
        for e in rev["edits"]:
            covers_flaw = any(k in e["current_text"] for k in keep)
            decisions.append({"edit_id": e["edit_id"], "decision": "reject" if covers_flaw else "adopt"})
    req = finalize_api.FinalizeRequest(plan_text=DEMO_PLAN, revision=revision, decisions=decisions, result=result,
                                       submission_id=DEMO_ID, title=DEMO_TITLE)
    response = finalize_api.run_finalization(req, threading.Event())
    return {"demo_id": DEMO_ID, "title": DEMO_TITLE,
            "note": "시연용 fixture — mock provider, 공용 fixture(가짜) 분석 결과 기반. 실제 LLM 검토·실제 API 호출이 아니다.",
            "plan_text": DEMO_PLAN, "decisions": decisions, "revision_edits": [
                {"edit_id": e["edit_id"], "plan_line": e["plan_line"], "current_text": e["current_text"], "proposed_text": e["proposed_text"]}
                for rev in revision["revisions"] for e in rev["edits"]],
            "response": response}


_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")


def stable(obj: Any) -> Any:
    """가변 필드(시각·소요 시간·세션 id)와 문자열 안의 생성 시각을 지운 비교용 사본."""
    if isinstance(obj, dict):
        return {k: stable(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [stable(v) for v in obj]
    if isinstance(obj, str):
        return _TIME_RE.sub("<time>", obj)
    return obj


def render_md(data: dict[str, Any]) -> str:
    fin = data["response"]["finalization"]
    lines = [f"# {data['title']} — 최종 초안", "", f"_{data['note']}_", "",
             f"- status `{fin['status']}` · generator `{fin['generator']}` · origin `{data['response']['origin']}` · counters `{json.dumps(fin['counters'])}`",
             "", "## 본문", "", "```", fin["final_text"], "```", "", "## 변경 이력(원문 → 수정 → 사유)", "",
             "| 줄 | 적용 | 사유 | 원문 | 수정문 |", "|---|---|---|---|---|"]
    for c in fin["corrections"]:
        lines.append(f"| {c['line']} | {'적용' if c['applied'] else '거절'} | {c['reason']} | {c['before'][:80]} | {c['after'][:120]} |")
    lines += ["", "## 잔여 쟁점(해결·미해결·확인 필요)", "", "| id | 유형 | 줄 | 상태 | 사유 | 설명 |", "|---|---|---|---|---|---|"]
    for i in fin["issues"]:
        lines.append(f"| {i['issue_id']} | {i['kind']} | {i['plan_lines']} | {i['status']} | {i.get('unchecked_reason', '')} | {i['message'][:100]} |")
    lines += ["", "## 도구 검사(전 → 후)", "", "| check | 도구 | 전 | 후 | 줄 |", "|---|---|---|---|---|"]
    after = {r["check_id"]: r for r in fin["tool_checks_after"]}
    for r in fin["tool_checks_before"]:
        a = after.get(r["check_id"])
        lines.append(f"| {r['check_id']} | {r['tool']} | {r['status']} ({r['message']}) | {a['status'] if a else '-'} | {r['plan_lines']} |")
    lines += ["", "## 알림", ""] + [f"- {n}" for n in fin["notices"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    data = build()
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if args.check:
        current = json.loads(OUT_JSON.read_text(encoding="utf-8")) if OUT_JSON.is_file() else None
        same = current is not None and stable(current) == stable(data)
        print("demo fixture", "fresh" if same else "STALE")
        return 0 if same else 1
    OUT_JSON.write_text(text + "\n", encoding="utf-8", newline="\n")
    OUT_MD.write_text(render_md(data), encoding="utf-8", newline="\n")
    fin = data["response"]["finalization"]
    print(f"wrote {OUT_JSON.name} ({len(text)} chars) status={fin['status']} corrections={sum(c['applied'] for c in fin['corrections'])}"
          f"/{len(fin['corrections'])} tools={[(r['tool'], r['status']) for r in fin['tool_checks_before']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
