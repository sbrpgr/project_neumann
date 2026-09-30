"""E4-L4r 계획서 수정 권고(V) 화면 Playwright 검사: 진입 버튼 → 수정 권고(a~e) → 근거 번호 → 결정(채택·직접 수정·기각)
→ 수정본 뷰어 모달(보기 3종·툴팁·[확인 필요] 입력·문단 편집·Ctrl+Z·Esc·포커스 복귀·인쇄용 CSS) → 서버 통합본(assemble: 충돌 선택·
다듬기 게이트) → .md·.docx 내려받기 → 실패·재시도·취소 → 브라우저 보존(새로고침) → 목업 모드(?mock=final, 외부 요청 0) → 390·1440.

    NEUMANN_UI_TESTS=1 NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4/test_revise_ui.py -q -s
    NEUMANN_LLM_PROVIDER=mock python tests/e4/test_revise_ui.py [--port 8171] [--out out/shots]

- 기본 pytest(verify)에서는 건너뛴다(브라우저·서버 필요). ``NEUMANN_UI_TESTS=1``일 때만 돈다.
- 서버(uvicorn)는 하위 프로세스로 띄우고 끝나면 끈다. 포트 기본 8171(8010·8020·8099 금지). 서버에는 mock provider만 주고
  ``OPENAI_API_KEY``를 넘기지 않는다(실제 API 호출 0).
- 화면 데이터: ``/premortem/view`` 응답을 fixture 기반 풍부한 뷰(test_view_shots.rich_view, 샘플 표시 유지)로 가로채고,
  E4-L2f처럼 원결과 ``result``와 합성 ``result_sig``를 싣는다. 최신 E3-L2r 선택 서명 필드의 전달을 검사한다(HMAC 검증 아님).
- 수정 권고 ``POST /premortem/revise`` 응답은 계약(contracts/revision.schema.json) 모양으로 여기서 만든다
  (카드 1 = E3-L2r mock 예시와 같은 줄·근거, 카드 2 = 같은 줄 충돌·[확인 필요] 자리표시 포함). 서버가 그 API를 갖든 아니든
  경로를 가로채므로 화면 어댑터는 서버와 같은 경로로 돈다. ``contracts/examples/revision.mock.json``이 있으면 카드 1에 그대로 쓴다.
- 통합본 ``POST /premortem/revise/assemble``: 처음엔 404(화면 조립 경로), 뒤에는 계약(revised_plan.schema.json) 모양의
  작은 조립기 스텁(요청의 decisions로 줄 단위 통합·같은 줄 충돌·자리표시·통계·markdown 3판, polish는 게이트 거부 응답,
  format=docx는 python-docx로 만든 합성 문서 + Content-Disposition; ZIP/XML과 채운 값·편집 제외 안내도 검사).
- 실패·취소: 카드 2 첫 요청은 500 → 재시도 → 성공. 취소는 응답을 붙잡아 둔 채 취소 버튼.
- 목업 모드는 새 브라우저 문맥(빈 저장소)에서 ``/?mock=final``을 열어 서버 API 요청 0·외부 요청 0을 확인하고 새로고침 뒤 편집 보존을 본다.
- 콘솔 오류·페이지 오류·실패 요청·외부 도메인 요청이 하나라도 있으면 실패(일부러 낸 404·500의 리소스 오류는 따로 센다).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

PREFIX = "E4-L4r"
DEFAULT_PORT = 8171
FORBIDDEN_PORTS = {8010, 8020, 8099}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
REPORT_READY = ("document.body.dataset.view === 'report' && document.body.dataset.ready === '1' && "
                "!!(document.querySelector('#s-cards .rc') || document.querySelector('#noCards'))")
REVISE_READY = "document.body.dataset.view === 'revise' && document.body.dataset.ready === '1'"
MOCK_EXAMPLE = ROOT / "contracts" / "examples" / "revision.mock.json"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DEC_EN = {"채택": "adopt", "수정": "modify", "기각": "reject", "adopt": "adopt", "modify": "modify", "reject": "reject"}
EDIT_TEXT = "연구자가 뷰어에서 직접 편집한 문장이다."

pytestmark = pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="NEUMANN_UI_TESTS=1일 때만(브라우저·서버 필요)")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sentence(text: str, eids: list[str], lines: list[int] | None = None) -> dict:
    return {"text": text, "excerpt_ids": eids, "plan_lines": lines or [], "quotes": []}


def edit(card_id: str, i: int, line: int, current: str, proposed: str, why: str, eids: list[str], kind: str = "replace") -> dict:
    return {"edit_id": f"{card_id}/e{i}", "plan_line": line, "kind": kind, "current_text": current, "proposed_text": proposed,
            "proposed_label": "제안(근거 아님)", "rationale": sentence(why, eids, [line])}


def build_revision(view: dict, card: dict, *, conflict_line: int | None = None) -> dict:
    """계약 모양(revision@v1) 응답. 카드의 실제 근거 id·줄을 쓴다. 새 발췌(records) 1건(저자 답변)을 붙인다."""
    ev = view["ev"]
    eids = [ev[str(k)]["eid"] for k in card["ev"]]
    lines = card["lines"] or [view["plan"]["lines"][1]["n"]]
    text_of = {l["n"]: l["t"] for l in view["plan"]["lines"]}
    cid = card["id"]
    accepted = [ev[str(k)] for k in card["ev"] if ev[str(k)].get("d") not in (None, "", "거절", "미정", "철회")]
    rec_id = f"ex_test_resp_{card['rank']}"
    rec_work = accepted[0]["id"] if accepted else view["works"][0]["id"]
    rec_text = "We re-ran all experiments with a scaffold split and report the numbers."
    interp = [sentence(f"테스트 해석 1: 심사자는 {card['rank']}번 카드의 지적을 거절 사유로 들었다.", eids[:1], lines[:1]),
              sentence("테스트 해석 2: 같은 지적이 다른 심사평에도 반복된다.", eids[1:2] or eids[:1], lines[:1]),
              sentence("테스트 해석 3(근거 없음): 화면 게이트가 빼야 한다.", [])]
    edits = [edit(cid, 1, lines[0], text_of[lines[0]], f"테스트 제안 1: {text_of[lines[0]]} 그리고 분할을 그룹 단위로 바꾼다.",
                  "테스트 이유 1: 근사 중복 누출을 막는다.", eids[:1])]
    if len(lines) > 1:
        edits.append(edit(cid, 2, lines[1], text_of[lines[1]], "테스트 제안 2: 중복 제거 기준을 착수 전에 정하고 제거 건수를 [확인 필요: 보고 시점]에 보고한다.",
                          "테스트 이유 2: 절차가 없다는 것이 지적의 핵심이다.", eids[1:2] or eids[:1]))
    else:
        edits.append(edit(cid, 2, lines[0], text_of[lines[0]], "테스트 제안 2: 시드 [확인 필요: 개수]개로 반복해 평균과 표준편차를 보고한다.",
                          "테스트 이유 2: 반복 없는 단일 수치가 지적됐다.", eids[1:2] or eids[:1]))
    edits.append(edit(cid, 3, lines[-1], text_of[lines[-1]], f"테스트 추가 문단: 카드 {card['rank']} 위험의 사전 점검 결과를 부록에 첨부한다.",
                      "테스트 이유 3: 확인 절차를 계획서에 적는다.", eids[:1], kind="insert_after"))
    if conflict_line is not None and conflict_line in text_of:
        edits.append(edit(cid, 4, conflict_line, text_of[conflict_line], f"테스트 교차 제안(카드 {card['rank']}): {text_of[conflict_line]} — 다른 관점의 수정.",
                          "테스트 이유 4: 다른 카드와 같은 줄(충돌 확인용).", eids[:1]))
    rev = {"card_id": cid, "risk_code": view["fams"][card["fam"]]["k"][:2], "title": view["fams"][card["fam"]]["n"], "generator": "mock",
           "model": "mock-deterministic-v1", "effort": "medium", "status": "ok", "reason": None,
           "interpretation": interp,
           "precedents": {"status": "found", "note": None, "items": [
               {"text": "테스트 대응: 같은 지적을 받은 채택 연구는 그룹 단위 분할로 다시 실험하고 답변했다.", "excerpt_ids": [rec_id] + eids[:1],
                "work_id": rec_work, "outcome": "accept_poster", "outcome_label": "Poster", "quotes": []}]},
           "edits": edits,
           "questions": [{"text": f"테스트 질문: {lines[0]}행의 기준을 실제로 바꿀 수 있는가?", "plan_lines": lines[:1]}],
           "audit": {"generated": 8, "passed": 7, "dropped": 1, "no_evidence": 1, "reasons": {"no_evidence": 1},
                     "dropped_detail": [{"section": "interpretation", "reason": "no_evidence", "text": "서버 게이트가 뺀 문장(테스트)"}],
                     "gate": "revision-grounding@v1"},
           "elapsed_s": 0.5, "llm_calls": 1, "fallback_reason": None, "evidence_pool": eids + [rec_id]}
    return {"version": "revision@v1", "plan_id": view["plan_id"], "session_id": view["session_id"], "generated_at": "2026-09-30T14:00:00+00:00",
            "generator": "mock", "model": "mock-deterministic-v1", "effort": "medium", "prompt_version": "revise_card@v1", "status": "ok", "reason": None,
            "cards_requested": [cid], "cards_skipped": [], "revisions": [rev],
            "records": [{"excerpt_id": rec_id, "source_kind": "author_response", "source_id": f"resp-test-{card['rank']}", "start": 0, "end": len(rec_text),
                         "text": rec_text, "text_sha256": _sha(rec_text), "source_url": "https://example.org/fake-venue/forum?id=gnn-002&noteId=resp",
                         "source_sha256": None, "work_id": rec_work, "record_kind": "author_response", "outcome": "accept_poster"}],
            "works": [{"work_id": rec_work, "title": "[FAKE] 채택 논문(테스트)", "url": "https://example.org/fake-venue/forum?id=gnn-002", "outcome": "accept_poster",
                       "outcome_raw": "FakeConf 2099 poster", "outcome_label": "Poster", "n_responses": 1, "n_meta_reviews": 0}],
            "audit": {"generated": 8, "passed": 7, "dropped": 1, "no_evidence": 1, "reasons": {"no_evidence": 1}, "dropped_detail": [], "gate": "revision-grounding@v1"},
            "cost": {"llm_calls": 1, "llm_calls_failed": 0, "prompt_chars": 4200, "usage": {}, "estimated_input_tokens": 1400, "estimated_output_tokens": 900,
                     "estimated_usd": None, "note": "mock provider: 실제 호출 없음"},
            "coverage": {"works_considered": 2, "works_with_decision": 2, "works_accepted": 1, "works_rejected": 1, "works_with_responses": 1,
                         "works_with_meta_review": 0, "record_source": "fixture"},
            "notices": ["mock provider(테스트용) 결과 — 실제 LLM 분석이 아니다"], "elapsed_s": 0.5, "revision_sig": None}


def assemble_stub(body: dict) -> dict:
    """계약 revised_plan@v1 모양의 작은 조립기: 채택·수정 안을 줄 단위로 합치고, 같은 줄 replace 둘 이상은 충돌(원문 유지)."""
    plan_lines = body["plan_text"].splitlines()
    revision, decisions = body["revision"], body.get("decisions") or []
    edits = {e["edit_id"]: (rev["card_id"], e) for rev in revision["revisions"] for e in rev["edits"]}
    decided = {d["edit_id"]: d for d in decisions if d.get("edit_id") in edits}
    applied: dict[tuple[int, str], list] = {}
    for eid, d in decided.items():
        dec = DEC_EN.get(str(d.get("decision", "")).strip(), "")
        if dec != "adopt" and dec != "modify":
            continue
        cid, e = edits[eid]
        text = d.get("revised_text") if dec == "modify" else e["proposed_text"]
        applied.setdefault((e["plan_line"], e["kind"]), []).append((eid, cid, text, dec, e, d))

    def change(eid, cid, kind, i, old, text, no, dec, e, d):
        return {"edit_id": eid, "card_id": cid, "kind": kind, "old_range": [i, i], "old_text": old, "new_text": text, "new_range": [no, no],
                "excerpt_ids": e["rationale"]["excerpt_ids"], "rationale": e["rationale"]["text"], "decision": dec, "decision_ko": "채택" if dec == "adopt" else "수정",
                "revised_by": "proposal" if dec == "adopt" else "researcher", "proposed_label": "제안(근거 아님)", "note": d.get("note"),
                "decided_at": d.get("decided_at"), "placeholders": re.findall(r"\[확인 필요:[^\]]*\]", text)}

    lines, changes, conflicts, no = [], [], [], 0
    for i, raw in enumerate(plan_lines, 1):
        repl = applied.get((i, "replace"), [])
        if len(repl) > 1:
            conflicts.append({"kind": "same_line", "plan_line": i, "edit_ids": [x[0] for x in repl], "card_ids": [x[1] for x in repl],
                              "detail": "같은 줄을 바꾸는 안이 둘 이상이다 — 연구자가 하나를 고르거나 직접 합쳐 수정한다",
                              "candidates": [{"edit_id": x[0], "card_id": x[1], "text": x[2], "decision": x[3]} for x in repl], "current_text": raw})
            no += 1
            lines.append({"no": no, "orig_no": i, "text": raw, "changed": False})
        elif repl:
            eid, cid, text, dec, e, d = repl[0]
            no += 1
            lines.append({"no": no, "orig_no": i, "text": text, "changed": True, "edit_id": eid, "card_id": cid, "polished": False})
            changes.append(change(eid, cid, "replace", i, raw, text, no, dec, e, d))
        else:
            no += 1
            lines.append({"no": no, "orig_no": i, "text": raw, "changed": False})
        for eid, cid, text, dec, e, d in applied.get((i, "insert_after"), []):
            no += 1
            lines.append({"no": no, "orig_no": None, "text": text, "changed": True, "edit_id": eid, "card_id": cid, "polished": False})
            changes.append(change(eid, cid, "insert_after", i, "", text, no, dec, e, d))
    holders = [{"text": ph, "edit_id": c["edit_id"], "card_id": c["card_id"], "line": c["new_range"][0]} for c in changes for ph in c["placeholders"]]
    polish = {"requested": bool(body.get("polish")), "applied": False}
    if body.get("polish"):
        polish.update({"reason": "gate_rejected: placeholders_changed at 17", "generator": "mock", "model": "mock-deterministic-v1",
                       "gate": "polish-diff-gate@v1", "lines_polished": 0})
    rejected = [eid for eid, d in decided.items() if DEC_EN.get(str(d.get("decision", "")).strip()) == "reject"]
    undecided = [eid for eid in edits if eid not in decided]
    text = "\n".join(l["text"] for l in lines)
    stats = {"edits_total": len(edits), "applied": len(changes), "adopted": sum(1 for c in changes if c["decision"] == "adopt"),
             "modified": sum(1 for c in changes if c["decision"] == "modify"), "rejected": len(rejected), "undecided": len(undecided),
             "conflicts": len(conflicts), "skipped": 0, "placeholders": len(holders), "lines_original": len(plan_lines), "lines_revised": len(lines)}
    label = "Neumann 수정 제안 · mock (mock-deterministic-v1) · 생성 시각 2026-09-30T14:05:00+00:00"
    return {"version": "revised_plan@v1", "plan_id": revision["plan_id"], "revised_plan_id": _sha(text), "generated_at": "2026-09-30T14:05:00+00:00",
            "revised_text": text, "lines": lines, "changes": changes, "conflicts": conflicts, "placeholders": holders, "skipped": [], "undecided": undecided,
            "rejected": rejected, "stats": stats, "notices": ([f"미해결 충돌 {len(conflicts)}건 — 해당 줄은 원문을 유지했다"] if conflicts else []),
            "polish": polish, "markdown": {"clean": text, "footnoted": text + "\n\n[^1]: 테스트 각주", "history": "# 수정 이력(테스트)\n\n| # |"},
            "label": label, "docx_available": True, "revised_plan_sig": None}


def intentional(msg: str) -> bool:
    """검사 시나리오가 일부러 낸 리소스 오류(작업 API 404 대체, 카드 2 첫 요청 500, assemble 404 구간)."""
    return "Failed to load resource" in msg and ("/premortem/jobs" in msg or "/premortem/revise" in msg)


def trust_checks(browser, base: str, view: dict, revision: dict) -> dict:
    """HMAC 검증은 서버 몫. 합성 응답·가짜 서명을 인증 배지로 오인하는 UI를 반증한다."""
    from tests.fixtures.loader import plan_text

    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    mode = {"value": "foreign"}
    calls = []

    def revise_route(route, request):
        calls.append(json.loads(request.post_data or "{}"))
        raw = json.loads(json.dumps(revision))
        if mode["value"] == "missing":
            route.fulfill(status=404, json={"message": "합성 테스트: 의존 API 없음"})
            return
        if mode["value"] == "foreign":
            for card in raw["revisions"]:
                card["card_id"] = "another-plan-card"
                card["card_rank"] = 1  # 같은 순위라도 다른 카드 id면 거절
        if mode["value"] == "other_plan":
            raw["plan_id"] = "another-plan"
        raw["origin"] = "client_submitted_unverified"
        raw["revision_sig"] = "v1." + "0" * 64  # 가짜 서명 모양; 실제 키·인증값 아님
        raw["notices"] = []  # 서버 안내가 빠져도 UI가 origin을 표시해야 한다
        for card in raw["revisions"]:
            card.update(generator="astra", model="forged-model", generator_label="LLM (forged-model)")
        route.fulfill(status=200, json=raw)

    def assembly_route(route, request):
        raw = assemble_stub(json.loads(request.post_data or "{}"))
        raw.update(origin="client_submitted_unverified", label="LLM (forged-model)", revised_plan_sig="v1." + "0" * 64)
        route.fulfill(status=200, json=raw)

    page.route("**/premortem/jobs", lambda route: route.fulfill(status=404, json={}))
    page.route("**/premortem/view", lambda route: route.fulfill(status=200, json=view))
    page.route("**/premortem/revise", revise_route)
    page.route("**/premortem/revise/assemble", assembly_route)
    try:
        page.goto(base + "/", wait_until="networkidle")
        page.fill("#ta", plan_text())
        page.click("#btnStart")
        page.wait_for_function(REPORT_READY)
        page.evaluate("window.NeumannRevise.config.dev = false")  # 병합 후 설정을 브라우저 안에서만 시험
        page.click("#s-cards .rc[data-card='1'] [data-rv]")
        page.wait_for_selector("#rv-1 .errbox")
        foreign_rejected = page.evaluate("!window.NeumannRevise.state().items[1].rev")
        mode["value"] = "other_plan"
        page.click("#rv-1 [data-rvretry]")
        page.wait_for_function("window.NeumannRevise.state().items[1].status === 'error' && window.NeumannRevise.state().items[1].raw.plan_id === 'another-plan'")
        other_plan_rejected = page.evaluate("!window.NeumannRevise.state().items[1].rev")
        mode["value"] = "missing"
        page.click("#rv-1 [data-rvretry]")
        page.wait_for_function("window.NeumannRevise.state().items[1].status === 'error' && document.querySelector('#rv-1 .errbox').innerText.includes('의존 API 없음')")
        api_missing = page.evaluate("() => ({no_revision: !window.NeumannRevise.state().items[1].rev, no_mock: !window.NeumannRevise.state().items[1].dev})")
        mode["value"] = "unverified"
        page.click("#rv-1 [data-rvretry]")
        page.wait_for_selector("#rv-1 .rvdiff")
        unverified = page.evaluate("""() => ({head: document.querySelector('#rv-1 .rvh').innerText,
          generator: document.querySelector('#rv-1 .rvh .gen').innerText,
          notice: document.getElementById('rvNotice').innerText})""")
        page.click("#rv-1 .rdec[data-edit$='/e1'][data-d='adopt']")
        page.click("#rvOpen")
        page.wait_for_function("window.NeumannRevise.state().asm && window.NeumannRevise.state().asm.source === 'server' && !document.getElementById('rvAsmMsg').innerText.includes('조립 중')")
        assembled = page.evaluate("""() => ({message: document.getElementById('rvAsmMsg').innerText,
          paper: document.getElementById('rvPaper').innerText, md: window.NeumannRevise.markdown()})""")
        page.evaluate("""() => { const key = 'neumann.revise.' + window.NeumannUI.D().plan_id;
          const saved = JSON.parse(localStorage.getItem(key)); saved.items[1].raw.origin = 'server_signed';
          localStorage.setItem(key, JSON.stringify(saved)); }""")  # 보존값 출처를 위조해도 이번 세션 인증이 아니다
        page.reload(wait_until="networkidle")
        page.fill("#ta", plan_text())
        page.click("#btnStart")
        page.wait_for_function(REPORT_READY)
        page.click("#stpRevise")
        page.wait_for_function(REVISE_READY)
        restored = page.evaluate("""() => ({restored: window.NeumannRevise.state().restored,
          head: (document.querySelector('#rv-1 .rvh') || {}).innerText || '', notice: document.getElementById('rvNotice').innerText,
          items: Object.keys(window.NeumannRevise.state().items), stored: !!localStorage.getItem('neumann.revise.' + window.NeumannUI.D().plan_id)})""")
        return {"foreign_rejected": foreign_rejected, "other_plan_rejected": other_plan_rejected, "api_missing": api_missing, "unverified": unverified,
                "assembled": assembled, "restored": restored, "page_errors": errors, "requests": len(calls)}
    finally:
        ctx.close()


def shoot(base: str, out: Path, prefix: str = PREFIX) -> dict:
    from playwright.sync_api import sync_playwright

    from tests.e4.test_view_shots import rich_view
    from tests.fixtures.loader import load_fixtures, plan_text

    view = rich_view()
    view["result"] = load_fixtures().premortem_result.model_dump(mode="json")  # E4-L2f처럼 원결과를 실어 둔다
    view["result_sig"] = "fixture-result-signature"  # 합성 전달값; HMAC 인증 검사는 아니다
    assert view["result"]["plan_id"] == view["plan_id"]
    assert len(view["cards"]) >= 2, "fixture 뷰에 카드 2장이 있어야 한다"
    c1, c2 = view["cards"][0], view["cards"][1]
    resp1 = build_revision(view, c1)
    example_used = False
    if MOCK_EXAMPLE.is_file():
        ex = json.loads(MOCK_EXAMPLE.read_text(encoding="utf-8"))
        if ex.get("plan_id") == view["plan_id"] and ex.get("revisions") and ex["revisions"][0].get("card_id") == c1["id"]:
            resp1, example_used = ex, True
    resp2 = build_revision(view, c2, conflict_line=c1["lines"][0])
    resp1["revision_sig"] = "fixture-revision-signature"
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed: list[str] = []
    requests: list[str] = []
    revise_calls: list[dict] = []
    asm_calls: list[dict] = []
    shots: list[str] = []
    fail_once = {"n": 1}
    hold = {"on": False, "routes": []}
    asm_mode = {"on": False}

    def revise_route(route, req):
        body = json.loads(req.post_data or "{}")
        revise_calls.append(body)
        cid = (body.get("card_ids") or [None])[0]
        if hold["on"]:
            hold["routes"].append(route)  # 취소 시나리오: 응답을 붙잡아 둔다
            return
        if cid == c2["id"] and fail_once["n"] > 0:
            fail_once["n"] -= 1
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"error_code": "internal", "message": "테스트: 처리 중 문제(첫 요청 실패)"}))
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(resp1 if cid == c1["id"] else resp2, ensure_ascii=False))

    def assemble_route(route, req):
        body = json.loads(req.post_data or "{}")
        asm_calls.append({"format": body.get("format"), "polish": body.get("polish"), "keys": sorted(body.keys()), "decisions": body.get("decisions"),
                          "result_sig": body.get("result_sig"), "revision_sig": body.get("revision_sig")})
        if not asm_mode["on"]:
            route.fulfill(status=404, content_type="application/json", body="{}")
            return
        if body.get("format") == "docx":
            from docx import Document

            document = Document()
            for line in assemble_stub(body)["lines"]:
                document.add_paragraph(line["text"])
            stream = io.BytesIO()
            document.save(stream)
            route.fulfill(status=200, content_type=DOCX_MEDIA, headers={"Content-Disposition": 'attachment; filename="neumann_revised_plan_test.docx"',
                                                                        "X-Neumann-Changes": "3", "X-Neumann-Conflicts": "0"}, body=stream.getvalue())
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(assemble_stub(body), ensure_ascii=False))

    def wire(page) -> None:
        page.on("console", lambda m: console_errors.append(m.text + " @ " + str((m.location or {}).get("url", ""))) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}"))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="ko-KR", accept_downloads=True)
        page = ctx.new_page()
        wire(page)
        # 작업 API(E4-L2d)는 404로 돌려 화면이 동기 /premortem/view(가로챈 뷰)로 가게 한다
        page.route("**/premortem/jobs", lambda route, _req: route.fulfill(status=404, content_type="application/json", body="{}"))
        page.route("**/premortem/view", lambda route, _req: route.fulfill(status=200, content_type="application/json", body=json.dumps(view, ensure_ascii=False)))
        page.route("**/premortem/revise", revise_route)
        page.route("**/premortem/revise/assemble", assemble_route)

        def snap(name: str, full: bool = False, pg=None) -> None:
            pg = pg or page
            pg.wait_for_timeout(250)
            path = out / f"{prefix}_{name}.png"
            pg.screenshot(path=str(path), full_page=full)
            shots.append(path.name)

        def no_hscroll(pg=None) -> dict:
            return (pg or page).evaluate("() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth})")

        # 1) 리포트 → 진입 버튼
        page.goto(base + "/", wait_until="networkidle")
        page.wait_for_selector('body[data-view="input"][data-ready="1"]')
        page.evaluate("() => { try { localStorage.clear(); } catch (e) {} }")
        page.fill("#ta", plan_text())
        page.click("#btnStart")
        page.wait_for_function(REPORT_READY, timeout=120_000)
        page.wait_for_selector("#s-cards .rc [data-rv]")
        entry = page.evaluate("""() => ({
          card_buttons: document.querySelectorAll('#s-cards .rc [data-rv]').length,
          top_button: !!document.getElementById('rvTop'),
          step_v: (document.getElementById('stpRevise') || {}).innerText || '',
          step_v_disabled: !!(document.getElementById('stpRevise') || {}).disabled,
          steps: Array.from(document.querySelectorAll('#steps .stp')).map(b => b.innerText.replace(/\\s+/g, ' ').trim()),
        })""")
        page.evaluate("document.getElementById('s-cards').scrollIntoView({block: 'start'})")
        snap("report_entry")

        # 2) 카드 1 "수정안 보기" → 수정 권고 화면
        page.click("#s-cards .rc[data-card='1'] [data-rv]")
        page.wait_for_function(REVISE_READY)
        page.wait_for_selector("#rv-1 .rvg", timeout=30_000)
        rev1 = page.evaluate("""() => {
          const sec = document.getElementById('rv-1');
          const g = Array.from(sec.querySelectorAll('.rvg'));
          return {
            focus: document.activeElement && document.activeElement.id,
            groups: g.map(x => x.querySelector('.h b').innerText),
            interp: sec.querySelectorAll('#rvA-1 .rvs p').length,
            interp_cites: sec.querySelectorAll('#rvA-1 .rvs .cite').length,
            interp_gate: (sec.querySelector('#rvA-1 .rvaudit') || {}).innerText || '',
            prec: sec.querySelectorAll('#rvB-1 .rvs p').length,
            prec_text: (sec.querySelector('#rvB-1') || {}).innerText || '',
            edits: sec.querySelectorAll('.rvdiff .rvdec').length,
            tags: Array.from(sec.querySelectorAll('.rvdiff .rvtag')).map(x => x.innerText),
            old_lines: Array.from(sec.querySelectorAll('.rvdiff .old .lref')).map(x => x.innerText),
            questions: sec.querySelectorAll('.rvq2 li').length,
            head: (sec.querySelector('.rvh .sub') || {}).innerText || '',
            gen: (sec.querySelector('.rvh .gen') || {}).innerText || '',
            notice: (document.getElementById('rvNotice') || {}).innerText || '',
            hub_status: (document.getElementById('rvHs-1') || {}).innerText || '',
          };
        }""")
        snap("revise_card", full=True)

        # 3) 근거 번호 → 기존 근거 패널(발췌·원문 링크). 새 발췌(저자 답변)도 등록됐는지
        page.click("#rvA-1 .rvs .cite >> nth=0")
        page.wait_for_selector("#pbody #evQuote")
        ev = page.evaluate("""() => ({
          k: document.querySelector('#evHead .cite').innerText, quote: document.getElementById('evQuote').textContent,
          link: (document.getElementById('evLink') || {}).href || '', lines: document.querySelectorAll('#evLines .pline').length,
        })""")
        page.click("#rvB-1 .rvs .cite >> nth=0")
        page.wait_for_function("document.getElementById('evQuote') && document.getElementById('evQuote').textContent.indexOf('scaffold') >= 0", timeout=10_000)
        rec = page.evaluate("() => ({quote: document.getElementById('evQuote').textContent, kind: document.querySelector('#pbody .plbl').innerText, head: document.getElementById('pbody').innerText})")
        page.evaluate("document.getElementById('rv-1').scrollIntoView({block: 'start'})")
        snap("evidence")

        # 4) 결정: e1 채택(키보드) · e2 직접 수정(편집 칸에 입력) · e3 기각
        page.focus("#rv-1 .rdec[data-edit$='/e1'][data-d='adopt']")
        page.keyboard.press("Enter")
        page.click("#rv-1 .rdec[data-edit$='/e2'][data-d='edit']")
        page.wait_for_selector("#rv-1 textarea.rvedit")
        page.fill("#rv-1 textarea.rvedit", "직접 수정한 문장: 중복 제거 기준을 착수 전에 정하고 제거 건수를 [확인 필요: 보고 시점]에 보고한다.")
        page.click("#rv-1 .rdec[data-edit$='/e3'][data-d='reject']")
        page.wait_for_timeout(400)
        dec = page.evaluate("""() => ({
          pressed: Array.from(document.querySelectorAll('#rv-1 .rdec[aria-pressed="true"]')).map(b => b.dataset.edit.split('/').pop() + ':' + b.dataset.d),
          cnt: (document.getElementById('rvCnt-1') || {}).innerText || '',
          sum: (document.getElementById('rvSum') || {}).innerText || '',
          log: window.NeumannRevise.decisions(),
          server: window.NeumannRevise.serverDecisions(),
          stored: !!localStorage.getItem('neumann.revise.' + window.NeumannUI.D().plan_id),
        })""")
        snap("decisions", full=True)

        # 5) 뷰어 모달(서버 assemble 없음 → 화면 조립): 열기(포커스 제목) → 보기 3종 → 툴팁 → 확인 필요 칩 입력 → Esc(포커스 복귀) → 인쇄용 CSS
        page.click("#rvOpen")
        page.wait_for_selector("#rvViewer.on")
        page.wait_for_function("(document.getElementById('rvAsmMsg') || {}).innerText && document.getElementById('rvAsmMsg').innerText.indexOf('화면 조립') >= 0")
        vw = page.evaluate("""() => {
          const m = document.getElementById('rvViewer');
          return {
            role: m.getAttribute('role'), modal: m.getAttribute('aria-modal'), focus: document.activeElement && document.activeElement.id,
            title: document.getElementById('rvVTitle').innerText, cnt: document.getElementById('rvVCnt').innerText, asm: document.getElementById('rvAsmMsg').innerText,
            chg: m.querySelectorAll('.rvpaper p.chg').length, ins: m.querySelectorAll('.rvpaper p.ins').length, del: m.querySelectorAll('.rvpaper p.del').length,
            me_tags: m.querySelectorAll('.rvpaper .rvtag.me').length,
            chips: m.querySelectorAll('.rvph:not(.filled)').length, fillcnt: (document.getElementById('rvFillCnt') || {}).innerText || '',
            marks: m.classList.contains('marks'), body_overflow: getComputedStyle(document.body).overflow,
            paper_w: document.getElementById('rvPaper').getBoundingClientRect().width,
            print_rule: Array.from(document.styleSheets).some(s => { try { return Array.from(s.cssRules).some(r => r.media && /print/.test(r.media.mediaText) && r.cssText.indexOf('rvmopen') >= 0); } catch (e) { return false; } }),
          };
        }""")
        snap("viewer_marks")
        page.emulate_media(media="print")
        print_view = page.evaluate("""() => ({paper_visible: document.getElementById('rvPaper').getBoundingClientRect().height > 0,
          app_display: getComputedStyle(document.getElementById('app')).display,
          controls_display: getComputedStyle(document.getElementById('rvVBar')).display,
          draft_visible: document.querySelector('#rvPaper .meta').innerText.includes('초안'),
          source_visible: document.getElementById('rvPaper').innerText.includes('출처 확인 정보 없음')})""")
        snap("viewer_print")
        page.emulate_media(media="screen")
        page.hover("#rvViewer .rvpaper p.chg >> nth=0")
        page.wait_for_selector("#rvTip.on")
        tip = page.inner_text("#rvTip")
        page.click('[data-rvview="clean"]')
        clean = page.evaluate("() => ({marks: document.getElementById('rvViewer').classList.contains('marks'), del_visible: Array.from(document.querySelectorAll('#rvViewer .rvpaper p.del')).filter(e => e.offsetParent !== null).length, chg_bg: getComputedStyle(document.querySelector('#rvViewer .rvpaper p.chg')).backgroundColor, me_tags: document.querySelectorAll('#rvViewer .rvtag.me').length})")
        snap("viewer_clean")
        page.click('[data-rvview="notes"]')
        page.wait_for_selector("#rvViewer [data-rvfn]")
        page.click("#rvViewer [data-rvfn] >> nth=0")
        notes = page.evaluate("() => ({fnrefs: document.querySelectorAll('#rvViewer [data-rvfn]').length, notes: document.querySelectorAll('#rvViewer [id^=rvFn-]').length, links: document.querySelectorAll('#rvViewer [id^=rvFn-] a[href^=\"https://\"]').length, focus: document.activeElement.id, first: document.getElementById('rvFn-1').innerText})")
        page.evaluate("document.getElementById('rvFn-1').scrollIntoView({block: 'center'})")
        snap("viewer_notes")
        page.click('[data-rvview="marks"]')
        page.click("#rvViewer .rvph:not(.filled) >> nth=0")
        page.wait_for_selector("#rvViewer input.rvphin")
        page.fill("#rvViewer input.rvphin", "착수 후 4주 차")
        page.keyboard.press("Enter")
        page.wait_for_function("document.querySelectorAll('#rvViewer .rvph:not(.filled)').length === 0")
        filled = page.evaluate("() => ({filled: Array.from(document.querySelectorAll('#rvViewer .rvph.filled')).map(x => x.innerText), cnt: document.getElementById('rvVCnt').innerText, fillcnt: !!document.getElementById('rvFillCnt'), md_has: window.NeumannRevise.markdown().indexOf('착수 후 4주 차') >= 0, server: window.NeumannRevise.serverDecisions()})")

        # 5b) 문단 편집: 원문 문단 클릭 → 편집 → Ctrl+Enter 저장 → "직접 수정" 태그·결정 로그(modify) → Ctrl+Z 되돌리기 → 다시 편집 → 제안 문단 편집은 결정 '수정'
        page.click("#rvViewer .rvpaper p[data-rvedit^='n:'] >> nth=0")
        page.wait_for_selector("#rvViewer textarea.rvpta")
        edit_dom = page.evaluate("() => ({rows: document.querySelectorAll('#rvViewer .rvedbox').length, tools: Array.from(document.querySelectorAll('#rvViewer .rvtb [data-rvact]')).map(b => b.innerText), focus: document.activeElement.className})")
        snap("viewer_editing")
        page.fill("#rvViewer textarea.rvpta", EDIT_TEXT)
        page.keyboard.press("Control+Enter")
        page.wait_for_function("!document.querySelector('#rvViewer textarea.rvpta')")
        after_edit = page.evaluate("""() => ({
          cnt: document.getElementById('rvVCnt').innerText,
          me_tags: document.querySelectorAll('#rvViewer .rvtag.me').length,
          text_in_paper: document.getElementById('rvPaper').innerText.indexOf(%s) >= 0,
          log_edit: window.NeumannRevise.decisions().filter(x => x.item_id.indexOf('rev-edit:') === 0),
          md_has: window.NeumannRevise.markdown().indexOf(%s) >= 0,
          stored_has: (localStorage.getItem('neumann.revise.' + window.NeumannUI.D().plan_id) || '').indexOf(%s) >= 0,
        })""" % (json.dumps(EDIT_TEXT), json.dumps(EDIT_TEXT), json.dumps(EDIT_TEXT)))
        page.keyboard.press("Control+z")
        page.wait_for_timeout(300)
        undone = page.evaluate("() => ({text_in_paper: document.getElementById('rvPaper').innerText.indexOf(%s) >= 0, log_edit: window.NeumannRevise.decisions().filter(x => x.item_id.indexOf('rev-edit:') === 0).length, cnt: document.getElementById('rvVCnt').innerText})" % json.dumps(EDIT_TEXT))
        page.click("#rvViewer .rvpaper p[data-rvedit^='n:'] >> nth=0")
        page.wait_for_selector("#rvViewer textarea.rvpta")
        page.fill("#rvViewer textarea.rvpta", EDIT_TEXT)
        page.click("#rvViewer [data-rvact='save']")
        page.wait_for_function("!document.querySelector('#rvViewer textarea.rvpta')")
        # 제안 문단(변경 문단) 편집 → 그 수정안의 결정이 '수정'
        page.click("#rvViewer .rvpaper p.chg[data-rvedit^='e:'] >> nth=0")
        page.wait_for_selector("#rvViewer textarea.rvpta")
        page.fill("#rvViewer textarea.rvpta", "제안 문단을 뷰어에서 고친 문장: 그룹 단위 분할과 중복 제거 절차를 명시한다.")
        page.keyboard.press("Control+Enter")
        page.wait_for_function("!document.querySelector('#rvViewer textarea.rvpta')")
        edit2 = page.evaluate("() => { const st = window.NeumannRevise.state(); const it = st.items[1]; const e1 = Object.keys(it.dec).filter(k => k.endsWith('/e1'))[0]; return {d: it.dec[e1] && it.dec[e1].d, text: it.dec[e1] && it.dec[e1].text, cnt: document.getElementById('rvVCnt').innerText, server_modify: window.NeumannRevise.serverDecisions().filter(x => x.decision === '수정').length, undo: st.undo.length}; }")
        page.keyboard.press("Escape")
        page.wait_for_function("!document.getElementById('rvViewer').classList.contains('on')")
        esc = page.evaluate("() => ({focus: document.activeElement.id, body_overflow: getComputedStyle(document.body).overflow, card_ta: (document.querySelector('#rv-1 textarea.rvedit') || {}).value || ''})")

        # 6) .md 내려받기(화면 조립: 수정본 + 편집 + 결정 로그) · .docx는 서버 API 없음 → 안내
        with page.expect_download() as dl:
            page.click("#rvSum [data-rvdl]")
        md_name = dl.value.suggested_filename
        md_text = Path(dl.value.path()).read_text(encoding="utf-8")
        page.click("#rvOpen2")
        page.wait_for_selector("#rvViewer.on")
        page.click("#rvDocx")
        page.wait_for_function("document.getElementById('rvDocxMsg').innerText.indexOf('실패') >= 0")
        docx_absent = page.inner_text("#rvDocxMsg")
        page.click("#rvVClose")
        page.wait_for_function("!document.getElementById('rvViewer').classList.contains('on')")

        # 7) 여러 장: 리포트 상단 "채택한 위험으로 수정안 받기" → 카드 2 첫 요청 500 → 재시도 → 완료
        page.click("#rvBack")
        page.wait_for_function(REPORT_READY)
        report_after = page.evaluate("() => ({status1: document.querySelector('#s-cards .rc[data-card=\"1\"] .rvst').innerText, step_v: document.getElementById('stpRevise').className})")
        page.click("#rvTop")
        page.wait_for_function(REVISE_READY)
        page.wait_for_selector("#rv-2 .errbox", timeout=30_000)
        err = page.evaluate("() => ({err: document.querySelector('#rv-2 .errbox').innerText, hub: document.getElementById('rvHs-2').innerText, live: document.getElementById('rvLive').innerText})")
        snap("retry")
        page.click("#rv-2 [data-rvretry]")
        page.wait_for_selector("#rv-2 .rvdiff", timeout=30_000)
        multi = page.evaluate("() => ({hub2: document.getElementById('rvHs-2').innerText, idx: document.getElementById('rvIdx').innerText, sections: document.querySelectorAll('.rvsec').length})")
        page.click("#rv-2 .rdec[data-edit$='/e4'][data-d='adopt']")
        page.click("#rv-2 .rdec[data-edit$='/e2'][data-d='adopt']")
        page.wait_for_timeout(300)

        # 8) 서버 통합본(assemble 스텁 켬): 충돌 배너(서버 conflicts) → 선택(고르지 않은 안은 기각으로 전송) → 재조립 → 충돌 0 · .docx · 다듬기 게이트 거부 표시
        asm_mode["on"] = True
        page.evaluate("window.NeumannRevise.state().asmAvail = null")  # 앞 단계의 404로 '없음'이 기억됐다 — 실제로는 서버가 바뀌지 않으니 검사에서만 되돌린다
        page.click("#rvOpen")
        page.wait_for_selector("#rvConfBanner")
        page.wait_for_function("(document.getElementById('rvAsmMsg') || {}).innerText && document.getElementById('rvAsmMsg').innerText.indexOf('서버 통합본') >= 0")
        conf = page.evaluate("() => ({banner: document.getElementById('rvConfBanner').innerText, cnt: document.getElementById('rvVCnt').innerText, asm: document.getElementById('rvAsmMsg').innerText, options: document.querySelectorAll('#rvViewer .rvconf [data-rvpick]').length, chg: document.querySelectorAll('#rvViewer .rvpaper p.chg').length, ins: document.querySelectorAll('#rvViewer .rvpaper p.ins').length, filled: Array.from(document.querySelectorAll('#rvViewer .rvph.filled')).map(x => x.innerText), overlay: document.getElementById('rvPaper').innerText.indexOf(%s) >= 0})" % json.dumps(EDIT_TEXT))
        page.click("[data-rvjumpconf]")
        page.wait_for_timeout(200)
        snap("viewer_conflict")
        page.click("#rvViewer .rvconf [data-rvpick] >> nth=1")
        page.wait_for_function("!document.getElementById('rvConfBanner') && document.getElementById('rvAsmMsg').innerText.indexOf('서버 통합본') >= 0")
        picked = page.evaluate("() => ({cnt: document.getElementById('rvVCnt').innerText, chosen: (document.querySelector('#rvViewer .rvconf .btn.dark') || {}).innerText || '', log: window.NeumannRevise.decisions().filter(x => x.decision === 'choose'), server: window.NeumannRevise.serverDecisions(), payload_keys: Object.keys(window.NeumannRevise.exportPayload())})")
        with page.expect_download() as dl2:
            page.click("#rvDocx")
        docx_name = dl2.value.suggested_filename
        docx_bytes = Path(dl2.value.path()).read_bytes()
        from docx import Document

        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as archive:
            docx_xml = archive.read("word/document.xml").decode("utf-8")
        docx_text = "\n".join(p.text for p in Document(io.BytesIO(docx_bytes)).paragraphs)
        page.wait_for_function("document.getElementById('rvDocxMsg').innerText.indexOf('내려받음') >= 0")
        docx_msg = page.inner_text("#rvDocxMsg")
        page.check("#rvPolish")
        page.wait_for_function("document.getElementById('rvAsmMsg').innerText.indexOf('다듬기') >= 0 && document.getElementById('rvAsmMsg').innerText.indexOf('조립 중') < 0", timeout=10_000)
        polish = page.evaluate("() => ({asm: document.getElementById('rvAsmMsg').innerText, checked: document.getElementById('rvPolish').checked})")
        page.uncheck("#rvPolish")
        page.wait_for_function("document.getElementById('rvAsmMsg').innerText.indexOf('다듬기') < 0 && document.getElementById('rvAsmMsg').innerText.indexOf('서버 통합본') >= 0", timeout=10_000)
        with page.expect_download() as dl3:
            page.click("#rvVBar [data-rvdl]")
        md_server = Path(dl3.value.path()).read_text(encoding="utf-8")
        page.click("#rvVClose")
        asm_mode["on"] = False

        # 9) 취소: 응답을 붙잡아 둔 채 카드 1을 다시 요청 → 취소 → 재시도 가능
        hold["on"] = True
        page.evaluate("window.NeumannRevise.state().items[1].status = 'idle'; window.NeumannRevise.state().items[1].rev = null;")
        page.evaluate("document.querySelector('[data-rvsel=\"1\"]').checked = true; document.querySelector('[data-rvsel=\"2\"]').checked = false;")
        page.click("#rvRun")
        page.wait_for_selector("#rv-1 .rvwait", timeout=10_000)
        wait_dom = page.evaluate("() => ({msg: document.querySelector('#rv-1 .rvwait').innerText, stages: document.querySelectorAll('#rv-1 .rvstages span').length, cancel: !!document.querySelector('#rv-1 [data-rvcancel]')})")
        snap("waiting")
        page.click("#rv-1 [data-rvcancel]")
        page.wait_for_selector("#rv-1 .errbox", timeout=10_000)
        cancel = page.evaluate("() => ({err: document.querySelector('#rv-1 .errbox').innerText, retry: !!document.querySelector('#rv-1 [data-rvretry]'), hub: document.getElementById('rvHs-1').innerText})")
        for r in hold["routes"]:
            try:
                r.abort()
            except Exception:  # noqa: BLE001 - 이미 취소된 요청
                pass
        hold["on"] = False
        main_console_errors = list(console_errors)

        # 10) 390 폭: 수정 권고 화면·뷰어(전체 화면 시트) 가로 스크롤 없음
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        page.evaluate("window.scrollTo(0, 0)")
        narrow = {"revise": no_hscroll()}
        snap("390_revise", full=True)
        page.click("#rvOpen")
        page.wait_for_selector("#rvViewer.on")
        page.wait_for_timeout(300)
        narrow["viewer"] = no_hscroll()
        narrow["sheet"] = page.evaluate("() => { const r = document.querySelector('#rvViewer .sheet').getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height), iw: innerWidth, ih: innerHeight}; }")
        narrow["viewer_inner"] = page.evaluate("() => { const b = document.getElementById('rvVBody'); return {sw: b.scrollWidth, cw: b.clientWidth}; }")
        snap("390_viewer")
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(200)
        narrow["revise_1440"] = no_hscroll()
        page.evaluate("() => { try { localStorage.clear(); } catch (e) {} }")
        ctx.close()

        # 11) 목업 모드(?mock=final)는 FIN-UI v2 단계 전환형 흐름으로 바뀌어 tests/e4/test_fin_ui.py가 검사한다
        trust = trust_checks(browser, base, view, resp1)
        browser.close()

    external = [u for u in requests if urlparse(u).scheme not in {"data", "blob", "about"} and urlparse(u).hostname not in LOCAL_HOSTS]
    return {
        "shots": shots, "example_used": example_used, "console_errors": [c for c in main_console_errors if not intentional(c)],
        "console_errors_intentional": [c for c in main_console_errors if intentional(c)],
        "console_errors_after_cancel": [c for c in console_errors[len(main_console_errors):] if not intentional(c)], "page_errors": page_errors,
        "failed_requests": [f for f in failed if "premortem/revise" not in f], "external_requests": external, "requests_total": len(requests),
        "revise_calls": [{"keys": sorted(c.keys()), "card_ids": c.get("card_ids"), "result_sig": c.get("result_sig"), "plan_text_ok": c.get("plan_text") == plan_text(),
                          "result_plan_id": (c.get("result") or {}).get("plan_id")} for c in revise_calls],
        "asm_calls": asm_calls,
        "entry": entry, "rev1": rev1, "ev": ev, "record": rec, "dec": dec, "viewer": vw, "print": print_view, "tip": tip, "clean": clean, "notes": notes, "filled": filled,
        "edit_dom": edit_dom, "after_edit": after_edit, "undone": undone, "edit2": edit2, "esc": esc,
        "md": {"name": md_name, "has_adopted": "제안 문단을 뷰어에서 고친 문장" in md_text, "has_edited": "직접 수정한 문장" in md_text, "has_overlay": EDIT_TEXT in md_text,
               "rejected_absent": "테스트 추가 문단: 카드 1" not in md_text, "has_log": "## 수정 결정 로그" in md_text, "has_fill": "착수 후 4주 차" in md_text,
               "head": md_text.splitlines()[0][:200]},
        "md_server": {"has_footnote": "[^1]" in md_server, "has_history": "수정 이력" in md_server, "has_fill": "착수 후 4주 차" in md_server, "has_overlay": EDIT_TEXT in md_server},
        "docx_absent": docx_absent, "docx": {"name": docx_name, "bytes": len(docx_bytes), "magic": docx_bytes[:2] == b"PK", "msg": docx_msg,
                                            "valid_xml": "<w:document" in docx_xml, "filled": "착수 후 4주 차" in docx_text, "overlay_absent": EDIT_TEXT not in docx_text},
        "polish": polish, "report_after": report_after, "err": err, "multi": multi, "conflict": conf, "picked": picked, "wait": wait_dom, "cancel": cancel,
        "narrow": narrow,
        "rich_ev1_quote": view["ev"]["1"]["q"], "plan_id": view["plan_id"],
        "trust": trust,
    }


def check(r: dict) -> list[str]:
    """완료 기준 판정. 빈 목록이면 통과."""
    bad = []
    trust = r["trust"]
    if not trust["foreign_rejected"] or not trust["other_plan_rejected"] or trust["api_missing"] != {"no_revision": True, "no_mock": True} or trust["page_errors"] or trust["requests"] != 4:
        bad.append(f"타 카드 거절·병합 후 API 오류 표시 이상: {trust}")
    uv = trust["unverified"]
    if "미확인" not in uv["generator"] or "서버 서명 확인 안 됨" not in uv["head"] or "미확인" not in uv["notice"] or "LLM (forged-model)" in uv["head"]:
        bad.append(f"가짜 서명·미확인 생성자 표시 이상: {uv}")
    assembled = trust["assembled"]
    if "미확인" not in assembled["message"] or "LLM (forged-model)" in assembled["message"] or "서버 서명 확인 안 됨" not in assembled["md"] or "통합본 출처: 서버 서명 확인 안 됨" not in assembled["paper"]:
        bad.append(f"미확인 통합본·MD·인쇄 원고 표시 이상: {assembled}")
    restored = trust["restored"]
    if not restored["restored"] or "서명 재검증 안 됨" not in restored["head"] or "다시 확인하지 않음" not in restored["notice"] or "LLM (forged-model)" in restored["head"] or "서명 확인됨" in restored["head"]:
        bad.append(f"브라우저 보존값 출처 표시 이상: {restored}")
    for key in ("console_errors", "console_errors_after_cancel", "page_errors", "failed_requests", "external_requests"):
        if r[key]:
            bad.append(f"{key}: {r[key][:3]}")
    e = r["entry"]
    if e["card_buttons"] < 2 or not e["top_button"] or "수정 권고" not in e["step_v"] or e["step_v_disabled"] or "V" not in e["step_v"]:
        bad.append(f"진입점 이상: {e}")
    if not r["revise_calls"] or any(c["keys"] != ["card_ids", "plan_text", "result", "result_sig"] or c["result_sig"] != "fixture-result-signature" or not c["plan_text_ok"] or c["result_plan_id"] != r["plan_id"] for c in r["revise_calls"]):
        bad.append(f"수정 권고 요청 모양 이상(계약 {{result, plan_text, card_ids}}): {r['revise_calls'][:2]}")
    v = r["rev1"]
    if v["focus"] != "rvTitle":
        bad.append(f"수정 권고 화면 제목에 포커스 없음: {v['focus']}")
    if v["groups"][:4] != ["거절 사유 해석", "채택 연구의 대응", "계획서 수정안", "확인 질문"]:
        bad.append(f"(a)~(d) 순서 이상: {v['groups']}")
    if v["interp"] < 1 or v["interp_cites"] < 1 or (not r["example_used"] and (v["interp"] != 2 or "1" not in v["interp_gate"])):
        bad.append(f"해석 문장·근거 번호·화면 게이트 이상: {v['interp']} {v['interp_cites']} {v['interp_gate']!r}")
    if v["prec"] < 1 or "Poster" not in v["prec_text"]:
        bad.append(f"채택 연구 대응 이상: {v['prec']} {v['prec_text'][:80]!r}")
    if v["edits"] < 2 or not all(t.startswith("제안(근거 아님)") or t.startswith("원문 불일치") for t in v["tags"]) or not v["old_lines"]:
        bad.append(f"수정안 diff 이상: {v['edits']} {v['tags']} {v['old_lines']}")
    if v["questions"] < 1 or "근거 없는 문장 제외" not in v["head"] or "모의(mock)" not in v["gen"]:
        bad.append(f"확인 질문·정직성 표시 이상: {v['questions']} {v['head']!r} {v['gen']!r}")
    if "샘플" not in v["notice"] or "완료" not in v["hub_status"]:
        bad.append(f"알림·진행 표시 이상: {v['notice'][:80]!r} {v['hub_status']!r}")
    if r["ev"]["quote"] != r["rich_ev1_quote"] or not r["ev"]["link"].startswith("https://") or not r["ev"]["lines"]:
        bad.append(f"근거 패널 이상: {r['ev']}")
    if not r["example_used"] and ("scaffold" not in r["record"]["quote"] or "저자 답변" not in r["record"]["kind"]):
        bad.append(f"새 발췌(저자 답변) 패널 등록 이상: {r['record']['kind']!r}")
    d = r["dec"]
    if sorted(d["pressed"]) != ["e1:adopt", "e2:edit", "e3:reject"] or "채택 1" not in d["cnt"] or "직접 수정 1" not in d["cnt"] or "기각 1" not in d["cnt"] or not d["stored"]:
        bad.append(f"결정·보존 이상: {d['pressed']} {d['cnt']!r} stored={d['stored']}")
    if len(d["log"]) != 3 or {x["decision"] for x in d["log"]} != {"adopt", "edit", "reject"} or not all(x["item_id"].startswith("rev:") and x["decided_at"] for x in d["log"]):
        bad.append(f"결정 로그 모양 이상: {d['log']}")
    if sorted(x["decision"] for x in d["server"]) != ["기각", "수정", "채택"] or not any(x.get("revised_text", "").startswith("직접 수정한 문장") for x in d["server"]):
        bad.append(f"서버용 결정(채택·수정·기각) 이상: {d['server']}")
    w = r["viewer"]
    if r["print"] != {"paper_visible": True, "app_display": "block", "controls_display": "none", "draft_visible": True, "source_visible": True}:
        bad.append(f"실제 print 렌더링 이상: {r['print']}")
    if w["role"] != "dialog" or w["modal"] != "true" or w["focus"] != "rvVTitle" or w["chg"] != 2 or w["chips"] != 1 or w["me_tags"] != 1 or not w["marks"] or w["body_overflow"] != "hidden" or not w["print_rule"] or w["paper_w"] > 760 or "화면 조립" not in w["asm"]:
        bad.append(f"뷰어 모달 이상: {w}")
    if "원문" not in r["tip"] or "근거 요약" not in r["tip"] or "#" not in r["tip"]:
        bad.append(f"툴팁 이상: {r['tip'][:120]!r}")
    if r["clean"]["marks"] or r["clean"]["chg_bg"] not in ("rgba(0, 0, 0, 0)", "transparent") or r["clean"]["me_tags"]:
        bad.append(f"깨끗한 원고 보기 이상: {r['clean']}")
    n = r["notes"]
    if n["fnrefs"] != 2 or n["notes"] != 2 or n["links"] < 1 or n["focus"] != "rvFn-1" or "#" not in n["first"]:
        bad.append(f"각주 판 이상: {n}")
    f = r["filled"]
    if f["filled"] != ["착수 후 4주 차"] or "확인 필요 0" not in f["cnt"] or f["fillcnt"] or not f["md_has"] or not any("착수 후 4주 차" in x.get("revised_text", "") for x in f["server"]):
        bad.append(f"[확인 필요] 입력 이상: {f}")
    ed = r["edit_dom"]
    if ed["rows"] != 1 or ed["tools"] != ["저장", "취소", "원래대로"] or "rvpta" not in ed["focus"]:
        bad.append(f"편집 모드 이상: {ed}")
    a = r["after_edit"]
    if not a["text_in_paper"] or a["me_tags"] != 2 or "직접 수정 2" not in a["cnt"] or len(a["log_edit"]) != 1 or a["log_edit"][0]["decision"] != "modify" or a["log_edit"][0].get("revised_text") != EDIT_TEXT or not a["md_has"] or not a["stored_has"]:
        bad.append(f"문단 편집 저장·결정 로그·.md·보존 이상: {a}")
    u = r["undone"]
    if u["text_in_paper"] or u["log_edit"] != 0 or "직접 수정 1" not in u["cnt"]:
        bad.append(f"Ctrl+Z 되돌리기 이상: {u}")
    e2 = r["edit2"]
    if e2["d"] != "edit" or "고친 문장" not in (e2["text"] or "") or "직접 수정 3" not in e2["cnt"] or e2["server_modify"] < 2:
        bad.append(f"제안 문단 편집 → 결정 '수정' 이상: {e2}")
    if r["esc"]["focus"] != "rvOpen" or r["esc"]["body_overflow"] == "hidden":
        bad.append(f"Esc 닫기·포커스 복귀 이상: {r['esc']}")
    m = r["md"]
    if not (m["name"].endswith(".md") and m["has_adopted"] and m["has_edited"] and m["has_overlay"] and m["rejected_absent"] and m["has_log"] and m["has_fill"] and "근거가 아니" in m["head"] and "직접 편집 1문단" in m["head"]):
        bad.append(f".md 내려받기(화면 조립) 이상: {m}")
    if "없음" not in r["docx_absent"]:
        bad.append(f"서버 없을 때 .docx 안내 이상: {r['docx_absent']!r}")
    if "완료" not in r["report_after"]["status1"] or "done" not in r["report_after"]["step_v"]:
        bad.append(f"리포트 복귀 상태 이상: {r['report_after']}")
    if "첫 요청 실패" not in r["err"]["err"] or "실패" not in r["err"]["hub"]:
        bad.append(f"실패·재시도 안내 이상: {r['err']}")
    if "완료" not in r["multi"]["hub2"] or r["multi"]["sections"] != 2:
        bad.append(f"여러 장 진행 이상: {r['multi']}")
    c = r["conflict"]
    if "선택 필요 1건" not in c["banner"] or c["options"] != 2 or "충돌 1" not in c["cnt"] or "서버 통합본" not in c["asm"] or c["filled"] != ["착수 후 4주 차"] or not c["overlay"]:
        bad.append(f"서버 통합본 충돌 배너·자리표시·편집 겹침 이상: {c}")
    pk = r["picked"]
    losers = [x for x in pk["server"] if x.get("note", "").startswith("충돌 선택에서 제외")]
    if "충돌 0" not in pk["cnt"] or pk["chosen"] != "선택됨" or len(pk["log"]) != 1 or len(losers) != 1 or losers[0]["decision"] != "기각":
        bad.append(f"충돌 선택·서버 결정 이상: {pk}")
    if sorted(pk["payload_keys"]) != ["revised_plan", "revision", "revision_decisions", "revision_sig"]:
        bad.append(f"내보내기 payload 모양 이상: {pk['payload_keys']}")
    x = r["docx"]
    if not (x["valid_xml"] and x["filled"] and x["overlay_absent"]):
        bad.append(f"DOCX 스텁 문서·채운 값·원문 편집 제외 이상: {x}")
    if not (x["name"].endswith(".docx") and x["magic"] and "내려받음" in x["msg"] and "변경 3" in x["msg"] and "직접 편집한 1문단" in x["msg"]):
        bad.append(f".docx 내려받기(편집 문단 안내 포함) 이상: {x}")
    if "게이트 거부" not in r["polish"]["asm"] or "미적용" not in r["polish"]["asm"]:
        bad.append(f"문장 다듬기 게이트 거부 표시 이상: {r['polish']}")
    ms = r["md_server"]
    if not (ms["has_overlay"] and ms["has_fill"]):  # 직접 편집 문단이 있으면 화면 조립 .md(편집 반영)
        bad.append(f"서버 통합본 상태의 .md 이상: {ms}")
    formats = [a["format"] for a in r["asm_calls"]]
    if "docx" not in formats or not all(set(a["keys"]) <= {"decisions", "format", "plan_text", "polish", "result", "result_sig", "revision", "revision_sig", "title"} for a in r["asm_calls"]):
        bad.append(f"assemble 요청 모양 이상: {[(a['format'], a['keys']) for a in r['asm_calls']][:3]}")
    if not all(a["result_sig"] == "fixture-result-signature" for a in r["asm_calls"]) or not any(a["revision_sig"] == "fixture-revision-signature" for a in r["asm_calls"]) or not any(a["revision_sig"] is None for a in r["asm_calls"]):
        bad.append("assemble 서명 전달·다중 카드 서명 제거 이상")
    if "만드는 중" not in r["wait"]["msg"] or r["wait"]["stages"] != 4 or not r["wait"]["cancel"]:
        bad.append(f"대기 화면 이상: {r['wait']}")
    if "취소" not in r["cancel"]["err"] or not r["cancel"]["retry"]:
        bad.append(f"취소 이상: {r['cancel']}")
    nw = r["narrow"]
    for k in ("revise", "viewer", "revise_1440"):
        if nw[k]["sw"] > nw[k]["iw"]:
            bad.append(f"{k} 가로 스크롤: {nw[k]}")
    if nw["viewer_inner"]["sw"] > nw["viewer_inner"]["cw"] or nw["sheet"]["w"] != nw["sheet"]["iw"] or nw["sheet"]["h"] != nw["sheet"]["ih"]:
        bad.append(f"390 뷰어 시트 이상: {nw}")
    return bad


def _run(port: int, out: Path) -> dict:
    from tests.e4.ui_shots import start_server, stop_server

    if port in FORBIDDEN_PORTS:
        raise SystemExit(f"{port}는 금지 포트(8010·8020·8099)")
    out.mkdir(parents=True, exist_ok=True)
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("NEUMANN_LIVE_LLM_OK", None)
    os.environ.update({"NEUMANN_LLM_PROVIDER": "mock", "NEUMANN_LIVE_TESTS": "0", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    proc = start_server(port)
    try:
        return shoot(f"http://127.0.0.1:{port}", out)
    finally:
        stop_server(proc, port)


def test_revise_ui(tmp_path):
    out = Path(os.environ.get("NEUMANN_UI_SHOTS_OUT") or tmp_path)
    r = _run(int(os.environ.get("NEUMANN_UI_SHOTS_PORT", DEFAULT_PORT)), out)
    if os.environ.get("NEUMANN_UI_SHOTS_OUT"):
        (out / "E4-L4r.metrics.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in r.items() if k not in ("rich_ev1_quote",)}, ensure_ascii=False, indent=1))
    assert check(r) == []


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "reports")
    args = ap.parse_args()
    r = _run(args.port, args.out)
    print(json.dumps({k: v for k, v in r.items() if k != "rich_ev1_quote"}, ensure_ascii=False, indent=1))
    bad = check(r)
    print("problems", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
