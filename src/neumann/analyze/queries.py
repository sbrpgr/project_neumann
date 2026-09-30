"""astra ① 계획서 → 영어 검색어 3~6개 + 방법·데이터·평가 축 + 연구계획서 여부(호출 1회).

번역은 검색 보조로만 쓴다. 계획서 사실로 쓰지 않는다. 실패하면 계획서의 영문 기술어로 대신한다(비상 경로).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from neumann.analyze import rules
from neumann.llm import LLMCall, LLMProvider, LLMResult, task_options
from neumann.models import PlanDocument

TASK = "query_axes"
PROMPT_VERSION = "query_axes.v1"
MAX_QUERIES = 6
MAX_QUERY_CHARS = 200

INSTRUCTIONS = """\
You prepare retrieval for a tool that finds prior papers whose peer-review records reveal risks for a new research plan.
The input is a document as numbered lines. It is often Korean with English technical terms.

1. Decide whether the document is a research plan or proposal (a study with a goal and some method, data, or evaluation).
   Recipes, diaries, advertisements, news, and general essays are not research plans.
   Give suitability_reason as one short Korean sentence and suitability_lines as the line numbers that support your judgment.
2. If it is a research plan, write 3 to 6 English search queries that would retrieve similar papers by title and abstract
   (machine-learning / AI-for-science venues). Cover the core task and scientific domain, the method, the data, and the
   evaluation. Each query is 4 to 14 words, plain words only (no quotes, no boolean operators).
   Translate Korean terms faithfully. Do not add facts the plan does not state: no invented dataset names, numbers, or methods.
3. axes: one English sentence each for method, data, evaluation, based only on the plan. Use "" when the plan has none.
4. domain: a short English label such as "materials science / battery electrolytes".
If it is not a research plan, return queries as [] and all axes as "".
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "is_research_plan": {"type": "boolean"},
        "suitability_reason": {"type": "string"},
        "suitability_lines": {"type": "array", "items": {"type": "integer"}},
        "domain": {"type": "string"},
        "queries": {"type": "array", "items": {"type": "string"}},
        "axes": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "method": {"type": "string"},
                "data": {"type": "string"},
                "evaluation": {"type": "string"},
            },
            "required": ["method", "data", "evaluation"],
        },
    },
    "required": ["is_research_plan", "suitability_reason", "suitability_lines", "domain", "queries", "axes"],
}


@dataclass
class QueryPlan:
    queries: list[str]
    axes: dict[str, str]
    domain: str | None
    is_research: bool
    reason: str
    reason_lines: list[int]
    generator: str  # astra | mock | rule
    model: str | None = None
    llm: LLMResult | None = None
    fallback_reason: str | None = None
    notes: list[str] = field(default_factory=list)


def plan_payload(plan: PlanDocument) -> dict[str, Any]:
    return {"lines": [f"{ln.no}: {ln.text}" for ln in plan.lines]}


def build_call(plan: PlanDocument, settings: Any = None) -> LLMCall:
    opts = task_options(TASK, settings)
    return LLMCall(
        task=TASK,
        instructions=INSTRUCTIONS,
        payload=plan_payload(plan),
        schema=SCHEMA,
        schema_name="query_axes",
        effort=opts["effort"],
        timeout_s=opts["timeout_s"],
        max_output_tokens=4000,
    )


def make_queries(plan: PlanDocument, llm: LLMProvider, settings: Any = None) -> QueryPlan:
    """astra로 검색어·축을 만든다. 실패하거나 결과가 쓸 수 없으면 규칙으로 대신하고 사유를 남긴다."""
    res = llm.complete_json(build_call(plan, settings))
    if res.ok and res.data is not None:
        qp, problem = _from_llm(plan, res)
        if problem is None:
            return qp
        return _fallback(plan, res, f"{res.provider} 응답 사용 불가: {problem}")
    return _fallback(plan, res, res.reason())


def _from_llm(plan: PlanDocument, res: LLMResult) -> tuple[QueryPlan, str | None]:
    data = res.data or {}
    n = len(plan.lines)
    notes: list[str] = []
    queries: list[str] = []
    for q in data.get("queries", []):
        q = " ".join(str(q).split())
        if not q:
            continue
        if len(q) > MAX_QUERY_CHARS:
            notes.append("긴 검색어 잘림")
            q = q[:MAX_QUERY_CHARS]
        if q.lower() not in (x.lower() for x in queries):
            queries.append(q)
    if len(queries) > MAX_QUERIES:
        notes.append(f"검색어 {len(queries)}개 → {MAX_QUERIES}개")
        queries = queries[:MAX_QUERIES]
    lines = [x for x in data.get("suitability_lines", []) if isinstance(x, int) and 1 <= x <= n]
    if len(lines) != len(data.get("suitability_lines", [])):
        notes.append("범위 밖 줄 번호 버림")
    is_research = bool(data.get("is_research_plan"))
    axes = {k: " ".join(str(v).split()) for k, v in (data.get("axes") or {}).items() if str(v).strip()}
    qp = QueryPlan(
        queries=queries,
        axes=axes,
        domain=(str(data.get("domain") or "").strip() or None),
        is_research=is_research,
        reason=str(data.get("suitability_reason") or "").strip(),
        reason_lines=lines,
        generator=res.generator,
        model=res.model,
        llm=res,
        notes=notes,
    )
    if is_research and not queries:
        return qp, "연구계획서라면서 검색어 0개"
    return qp, None


def _fallback(plan: PlanDocument, res: LLMResult | None, why: str) -> QueryPlan:
    signal = rules.research_signal(plan)
    is_research = rules.looks_like_research(plan)
    return QueryPlan(
        queries=rules.fallback_queries(plan, MAX_QUERIES),
        axes=rules.fallback_axes(plan),
        domain=None,
        is_research=is_research,
        reason=f"규칙 판정: 연구 어휘 {signal}회" + ("" if is_research else " (기준 4회 미만)"),
        reason_lines=[],
        generator="rule",
        model=None,
        llm=res,
        fallback_reason=why,
    )
