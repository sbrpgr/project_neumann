"""astra ① 계획서 → 영어 검색어 3~6개 + 방법·데이터·평가 축 + 연구계획서 여부(호출 1회).

번역은 검색 보조로만 쓴다. 계획서 사실로 쓰지 않는다. 실패하면 계획서의 영문 기술어로 대신한다(비상 경로).

검색어 캐시(E3-L1w): 같은 계획서(plan_id)·provider·모델·추론 강도·지시문 판이면 astra가 한 번 만든 검색어를
`cache_dir`(기본 `data/cache/queries/`)에 두고 다시 쓴다. 같은 계획서는 같은 검색어 → 같은 유사 연구가 나온다.
astra 결과만 캐시한다(규칙 비상 경로·mock 결과는 캐시하지 않는다: 다음 실행에서 astra를 다시 시도하게).
적중 여부는 `QueryPlan.cache`에 남고 파이프라인이 결과(`plan_checks.queries.cache`)에 싣는다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neumann.analyze import rules
from neumann.llm import LLMCall, LLMProvider, LLMResult, generator_for, task_options, validate_output
from neumann.models import PlanDocument

log = logging.getLogger(__name__)

TASK = "query_axes"
PROMPT_VERSION = "query_axes.v2"  # v2(E3-L1s): 연구 배경·아이디어만 있는 짧은 글도 검색어를 쓴다
MAX_QUERIES = 6
MAX_QUERY_CHARS = 200
CACHE_VERSION = "query_cache.v1"
_REPLACE_TRIES = 40  # 캐시 교체 재시도(Windows 공유 위반: 다른 쪽이 같은 파일을 교체·읽는 중), 최대 약 1.4초
CACHE_GENERATORS = frozenset({"astra"})  # 캐시하는 생성 주체

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
If the text is research-related but not a full plan (for example only research background, an abstract without the
plan, or a short idea), set is_research_plan to false but STILL write the queries and domain for its research topic
and method, and axes only from what it states.
Return queries as [] and all axes as "" only when the text is not about research at all.
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
    # 검색어 캐시: enabled(캐시 대상인가), hit(적중), stored(이번에 저장), key(앞 16자), created_at(적중 항목의 생성 시각)
    cache: dict[str, Any] = field(default_factory=lambda: {"enabled": False, "hit": False, "stored": False})


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


def cache_key(plan: PlanDocument, provider: str, model: str, effort: str | None) -> str:
    """같은 계획서(plan_id)·provider·모델·추론 강도·지시문 판이면 같은 키."""
    body = json.dumps(
        {"v": CACHE_VERSION, "prompt": PROMPT_VERSION, "plan_id": plan.plan_id, "provider": provider, "model": model,
         "effort": effort},
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _atomic_write(final: Path, text: str) -> None:
    """임시 파일(`{key}.{pid}.{thread_id}.{uuid 8자}.tmp`, 쓰는 쪽마다 고유)에 쓰고 os.replace로 원자 교체한다.

    같은 키를 여러 스레드·프로세스가 동시에 써도 임시 파일이 겹치지 않아 반쯤 쓴 파일이 캐시 이름으로 올라가지 않는다.
    Windows에서 다른 쪽이 대상 파일을 교체·읽는 중이면 교체가 잠깐 거부(PermissionError)될 수 있어 다시 시도한다.
    실패하면 OSError를 올리고(호출부가 경고로 받는다) 임시 파일은 지운다.
    """
    tmp = final.with_name(f"{final.stem}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        for attempt in range(_REPLACE_TRIES):
            try:
                os.replace(tmp, final)
                return
            except PermissionError:
                if attempt == _REPLACE_TRIES - 1:
                    raise
                time.sleep(min(0.002 * (attempt + 1), 0.05))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _cache_read(cache_dir: Path, key: str) -> dict[str, Any] | None:
    """캐시 항목을 읽고 응답 스키마로 다시 검사한다. 없거나 깨졌으면 None(그때는 astra를 다시 부른다)."""
    try:
        entry = json.loads((cache_dir / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(entry, dict) or entry.get("v") != CACHE_VERSION:
        return None
    data, err, _ = validate_output(json.dumps(entry.get("data")), SCHEMA)
    if err or data is None:
        log.warning("검색어 캐시 항목 무시(스키마 위반): %s", key[:16])
        return None
    return {**entry, "data": data}


def _cache_write(cache_dir: Path, key: str, res: LLMResult, plan_id: str) -> bool:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "v": CACHE_VERSION, "prompt": PROMPT_VERSION, "plan_id": plan_id, "provider": res.provider,
            "model": res.model, "effort": res.effort, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "data": res.data,
        }
        _atomic_write(cache_dir / f"{key}.json", json.dumps(entry, ensure_ascii=False))
        return True
    except OSError as exc:
        log.warning("검색어 캐시 쓰기 실패: %s", type(exc).__name__)
        return False


def make_queries(
    plan: PlanDocument, llm: LLMProvider, settings: Any = None, *, cache_dir: Path | None = None
) -> QueryPlan:
    """astra로 검색어·축을 만든다. 실패하거나 결과가 쓸 수 없으면 규칙으로 대신하고 사유를 남긴다.

    cache_dir: 검색어 캐시 폴더(None이면 캐시 안 씀). astra 결과만 읽고 쓴다.
    """
    call = build_call(plan, settings)
    key = cache_key(plan, llm.name, llm.model, call.effort)
    enabled = cache_dir is not None and generator_for(llm.name) in CACHE_GENERATORS
    cache: dict[str, Any] = {"enabled": enabled, "hit": False, "stored": False, "key": key[:16]}
    if enabled:
        assert cache_dir is not None
        entry = _cache_read(cache_dir, key)
        if entry is not None:
            res = LLMResult(ok=True, data=entry["data"], provider=str(entry.get("provider") or llm.name),
                            model=str(entry.get("model") or llm.model), task=TASK, effort=entry.get("effort"))
            qp, problem = _from_llm(plan, res)
            if problem is None:
                qp.cache = {**cache, "hit": True, "created_at": entry.get("created_at")}
                qp.notes.append("검색어 캐시 적중: 이 계획서에 astra가 앞서 만든 검색어를 다시 썼다")
                return qp
            cache["invalid"] = problem
    res = llm.complete_json(call)
    if res.ok and res.data is not None:
        qp, problem = _from_llm(plan, res)
        if problem is None:
            if enabled and res.generator in CACHE_GENERATORS:
                assert cache_dir is not None
                cache["stored"] = _cache_write(cache_dir, key, res, plan.plan_id)
            qp.cache = cache
            return qp
        qp = _fallback(plan, res, f"{res.provider} 응답 사용 불가: {problem}")
    else:
        qp = _fallback(plan, res, res.reason())
    qp.cache = cache
    return qp


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
