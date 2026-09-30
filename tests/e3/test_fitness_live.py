"""E3-L1c: 실제 astra로 적합성 판정 1회씩(데모 계획서 3건·조리법 1건, 호출 4회). `NEUMANN_LIVE_TESTS=1`일 때만 돈다.

E3-L0의 `llm.py`가 main에 들어오기 전이라 openai SDK를 직접 부르는 임시 llm_call을 쓴다(과제 지시문 허용).
키는 환경변수에서 SDK가 읽는다. 키·요청 헤더를 출력하지 않는다.

    NEUMANN_LIVE_TESTS=1 python -m pytest -q -s tests/e3/test_fitness_live.py
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import pytest

from neumann.analyze.fitness import assess_fitness, fitness_stage
from neumann.models import PlanDocument
from tests.fixtures.loader import DEMO_PLANS, NEGATIVE_PLAN, plan_text

pytestmark = pytest.mark.skipif(
    os.getenv("NEUMANN_LIVE_TESTS") != "1" or not os.getenv("OPENAI_API_KEY"),
    reason="실제 API 테스트는 NEUMANN_LIVE_TESTS=1이고 키가 있을 때만 돈다",
)

MODEL = os.getenv("NEUMANN_LLM_MODEL") or "gpt-6-astra"


def _openai_llm_call(timeout_s: float = 60.0):
    from openai import OpenAI

    client = OpenAI(max_retries=0, timeout=timeout_s)
    log: list[dict[str, Any]] = []

    def call(schema: dict, instructions: str, input: str, *, effort: str) -> dict | None:  # noqa: A002
        t0 = time.perf_counter()
        try:
            resp = client.responses.create(
                model=MODEL,
                instructions=instructions,
                input=input,
                reasoning={"effort": effort},
                text={"format": {"type": "json_schema", "name": "input_fitness", "schema": schema, "strict": True}},
                store=False,
            )
        except Exception as exc:  # noqa: BLE001 — 실패는 None으로(비상 경로)
            log.append({"ok": False, "error": type(exc).__name__, "latency_s": round(time.perf_counter() - t0, 2)})
            return None
        usage = getattr(resp, "usage", None)
        log.append({
            "ok": True,
            "latency_s": round(time.perf_counter() - t0, 2),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        })
        return json.loads(resp.output_text)

    call.log = log  # type: ignore[attr-defined]
    return call


def _summary(name: str, r: dict[str, Any], call_log: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "plan": name,
        "verdict": r["verdict"],
        "analyze": r["analyze"],
        "model_verdict": r["model_verdict"],
        "generator": r["generator"],
        "model": r["model"],
        "status": r["status"],
        "field": r["field"],
        "language": r["language"],
        "elements": {e: v["plan_lines"] for e, v in r["elements"].items()},
        "reason": r["reason"],
        "notice": r["notice"],
        "checks": r["checks"],
        "call": call_log[-1] if call_log else None,
        "stage": fitness_stage(r).model_dump(mode="json"),
    }


@pytest.mark.parametrize(("name", "expected"), [*((n, "fit") for n in DEMO_PLANS), (NEGATIVE_PLAN, "unfit")])
def test_live_astra_fitness(name: str, expected: str) -> None:
    call = _openai_llm_call()
    plan = PlanDocument.from_text(plan_text(name), "live-e3-l1c")
    r = assess_fitness(plan, call, model=MODEL)
    print("\n" + json.dumps(_summary(name, r, call.log), ensure_ascii=False, indent=2))
    assert r["decided_by"] == "llm", r["degraded_reason"]
    assert r["generator"] == "astra" and r["status"] == "ok"
    assert r["verdict"] == expected
