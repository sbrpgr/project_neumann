"""mock provider의 결정적 응답: 규칙 결과를 LLM 응답 모양으로 만든다(테스트·오프라인 데모용).

이 응답으로 만든 결과는 generator="mock"으로 표기된다. astra 결과라고 쓰지 않는다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from neumann.analyze import rules
from neumann.analyze.risk_brief import CARD_CODES
from neumann.llm import LLMCall
from neumann.models import PlanDocument, PlanLine, RiskCode, sha256_text

_LINE = re.compile(r"^(\d+): ?(.*)$", re.S)


def _plan_from_lines(lines: list[str]) -> PlanDocument:
    parsed = []
    for raw in lines:
        m = _LINE.match(raw)
        parsed.append(m.group(2) if m else raw)
    text = "\n".join(parsed)
    return PlanDocument(
        plan_id=sha256_text(text), session_id="mock", lines=[PlanLine(no=i, text=t) for i, t in enumerate(parsed, 1)]
    )


def query_axes(call: LLMCall) -> dict[str, Any]:
    plan = _plan_from_lines(call.payload["lines"])
    is_research = rules.looks_like_research(plan)
    return {
        "is_research_plan": is_research,
        "suitability_reason": "mock: 연구 어휘 개수로 판정",
        "suitability_lines": [],
        "domain": "",
        "queries": rules.fallback_queries(plan) if is_research else [],
        "axes": {"method": "", "data": "", "evaluation": ""} | rules.fallback_axes(plan),
    }


def extract_issues(call: LLMCall) -> dict[str, Any]:
    issues = []
    for s in call.payload["sentences"]:
        for code, conf in rules.keyword_tags(s["text"]):
            issues.append(
                {"excerpt_id": s["id"], "start": None, "end": None, "risk_code": code.value, "polarity": "negative",
                 "confidence": conf}
            )
    return {"issues": issues}


def synthesize_cards(call: LLMCall) -> dict[str, Any]:
    plan = _plan_from_lines(call.payload["plan"])
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in call.payload["pool"]:
        by_code[item["risk_code"]].append(item)
    cards = []
    for code_s, items in sorted(by_code.items()):
        code = RiskCode(code_s)
        papers = {i["paper"] for i in items}
        lines = rules.plan_lines_for(code, plan)
        if code not in CARD_CODES or len(items) < 3 or len(papers) < 2 or not lines:
            continue
        # 논문을 돌아가며 근거를 고른다.
        per_paper: dict[str, list[str]] = defaultdict(list)
        for i in items:
            per_paper[i["paper"]].append(i["id"])
        ev: list[str] = []
        while len(ev) < 5 and any(per_paper.values()):
            for p in sorted(per_paper):
                if per_paper[p] and len(ev) < 5:
                    ev.append(per_paper[p].pop(0))
        cards.append(
            {
                "risk_code": code.value,
                "title": f"mock: {code.title_ko}",
                "why_applies": "mock 응답: 계획서 " + ", ".join(f"L{n}" for n in lines) + " 줄이 이 유형에 해당한다.",
                "plan_lines": lines,
                "evidence_ids": ev,
            }
        )
    return {"cards": cards[:8], "no_card_reason": None if cards else "mock: 해당 카드 없음"}


# ── v1 단계(E3-L1w): 적합성 · 예상 심사평 · 체크리스트 · 2차 검증 ────────────────────────
# 입력은 각 모듈이 만든 JSON payload(provider 어댑터가 풀어 준다). 문장에 숫자·따옴표를 넣지 않는다(게이트 통과용).


def _plan_from_numbered(text: str, n_lines: int) -> PlanDocument:
    """'번호: 본문' 줄(빈 줄 생략)을 원래 줄 번호 그대로 PlanDocument로 되돌린다."""
    by_no: dict[int, str] = {}
    for raw in text.split("\n"):
        m = _LINE.match(raw)
        if m:
            by_no[int(m.group(1))] = m.group(2)
    n = max([n_lines, *by_no]) if by_no else max(n_lines, 1)
    lines = [PlanLine(no=i, text=by_no.get(i, "")) for i in range(1, n + 1)]
    body = "\n".join(ln.text for ln in lines)
    return PlanDocument(plan_id=sha256_text(body), session_id="mock", lines=lines)


def fitness(call: LLMCall) -> dict[str, Any]:
    """적합성: 판정은 query_axes mock과 같은 규칙(연구 어휘 수), 요소별 줄은 적합성 규칙 신호."""
    from neumann.analyze.fitness import ELEMENTS, rule_fitness  # E3-L1c. 없으면 파이프라인이 이 단계를 부르지 않는다

    payload = call.payload
    plan = _plan_from_numbered(str(payload.get("plan", "")), int(payload.get("n_lines") or 0))
    signal = rule_fitness(plan)
    is_research = rules.looks_like_research(plan)
    return {
        "verdict": "research_plan" if is_research else "not_research_plan",
        "elements": {e: {"present": bool(signal["elements"][e]["plan_lines"]),
                         "plan_lines": list(signal["elements"][e]["plan_lines"])} for e in ELEMENTS},
        "field": "",
        "reason": "mock: 연구 어휘 개수로 판정",
    }


def expected_review(call: LLMCall) -> dict[str, Any]:
    """예상 심사평: 카드마다 약점·요청 한 문장씩(그 카드의 첫 근거와 카드 인용 줄에 연결)."""
    weakness: list[dict[str, Any]] = []
    request: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in call.payload.get("cards", []):
        if card.get("risk_code") in seen or not card.get("evidence"):
            continue
        seen.add(card["risk_code"])
        ids = {"card_ids": [card["id"]], "excerpt_ids": [card["evidence"][0]["id"]],
               "plan_lines": list(card.get("plan_lines", []))[:6]}
        kind = card.get("risk_type", "")
        weakness.append({"text": f"mock 응답: {kind} 유형의 지적이 유사 연구 심사에서 나왔다.", **ids})
        request.append({"text": f"mock 응답: {kind} 위험을 막는 절차를 착수 전에 계획서에 적을 것.", **ids})
    return {"strength": [], "weakness": weakness[:4], "request": request[:4]}


def checklist(call: LLMCall) -> dict[str, Any]:
    """체크리스트: 카드마다 행동 하나(카드가 인용한 줄, 카드 근거 앞 두 건)."""
    first_line = next((ln["no"] for ln in call.payload.get("plan_lines", [])), None)
    cards = []
    for card in call.payload.get("cards", []):
        lines = list(card.get("why_plan_lines") or ([first_line] if first_line else []))
        cards.append(
            {
                "card_id": card["card_id"],
                "actions": [
                    {
                        "action": f"mock 응답: {card.get('risk_name', '')} 위험을 줄이는 절차를 착수 전에 계획서에 적는다.",
                        "verify": "mock 응답: 계획서 해당 줄에 절차가 적혀 있다.",
                        "plan_lines": lines,
                        "evidence_ids": [e["excerpt_id"] for e in card.get("evidence", [])][:2],
                    }
                ],
            }
        )
    return {"cards": cards}


def semantic_validate(call: LLMCall) -> dict[str, Any]:
    """2차 검증: 인용 줄이 있으면 맞음, 없으면 약함(행동도 연결 줄 유무로)."""
    cards = []
    for card in call.payload.get("cards", []):
        cards.append(
            {
                "card_id": card["card_id"],
                "verdict": "match" if card.get("cited_lines") else "weak",
                "reason": "mock 판정: 인용한 계획서 줄 유무로 정함",
                "actions": [
                    {"item_id": a["item_id"], "verdict": "match" if a.get("plan_lines") else "weak",
                     "reason": "mock 판정: 연결된 계획서 줄 유무로 정함"}
                    for a in card.get("actions", [])
                ],
            }
        )
    return {"cards": cards}


def default_responders() -> dict[str, Any]:
    return {
        "fitness": fitness,
        "query_axes": query_axes,
        "extract_issues": extract_issues,
        "synthesize_cards": synthesize_cards,
        "expected_review": expected_review,
        "checklist": checklist,
        "semantic_validate": semantic_validate,
    }
