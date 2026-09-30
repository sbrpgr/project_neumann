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


def default_responders() -> dict[str, Any]:
    return {"query_axes": query_axes, "extract_issues": extract_issues, "synthesize_cards": synthesize_cards}
