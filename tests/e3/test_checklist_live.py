"""E3-L1b 실제 astra 1회 예시: 체크리스트 → 2차 의미검증. `NEUMANN_LIVE_TESTS=1`일 때만 돈다.

llm.py(E3-L0)에 기대지 않고 openai SDK를 직접 부르는 임시 llm_call을 쓴다(과제 지시문이 허락한 형태).
키는 SDK가 환경변수에서 읽는다. 키·헤더를 출력하지 않는다.

    NEUMANN_LIVE_TESTS=1 python -m pytest tests/e3/test_checklist_live.py -s
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import jsonschema
import pytest

from neumann.analyze.checklist import attach_checklist
from neumann.analyze.validate import VERDICTS, attach_validation
from tests.fixtures.loader import load_fixtures

pytestmark = pytest.mark.skipif(
    os.getenv("NEUMANN_LIVE_TESTS") != "1" or not os.getenv("OPENAI_API_KEY"),
    reason="실제 API 테스트는 NEUMANN_LIVE_TESTS=1과 OPENAI_API_KEY가 있을 때만",
)


def _openai_llm_call() -> Any:
    from openai import OpenAI

    client = OpenAI(max_retries=0, timeout=180.0)
    model = os.getenv("NEUMANN_LLM_MODEL") or "gpt-6-astra"
    log: list[dict[str, Any]] = []

    def llm_call(schema: dict, instructions: str, input: str, *, effort: str) -> dict | None:
        t0 = time.perf_counter()
        try:
            resp = client.responses.create(
                model=model,
                instructions=instructions,
                input=input,
                text={"format": {"type": "json_schema", "name": "neumann_e3_l1b", "schema": schema, "strict": True}},
                reasoning={"effort": effort},
                store=False,
            )
        except Exception as exc:  # noqa: BLE001
            log.append({"ok": False, "error": type(exc).__name__, "s": round(time.perf_counter() - t0, 1)})
            return None
        usage = getattr(resp, "usage", None)
        entry = {"ok": True, "s": round(time.perf_counter() - t0, 1), "effort": effort,
                 "in_tok": getattr(usage, "input_tokens", None), "out_tok": getattr(usage, "output_tokens", None)}
        if getattr(resp, "status", "completed") != "completed":
            entry.update(ok=False, error=f"status={resp.status}")
            log.append(entry)
            return None
        try:
            data = json.loads(resp.output_text)
            jsonschema.validate(data, schema)  # 로컬 재검증
        except Exception as exc:  # noqa: BLE001
            entry.update(ok=False, error=type(exc).__name__)
            log.append(entry)
            return None
        log.append(entry)
        return data

    llm_call.model = model  # type: ignore[attr-defined]
    llm_call.generator = "astra"  # type: ignore[attr-defined]
    llm_call.log = log  # type: ignore[attr-defined]
    return llm_call


def test_live_astra_checklist_and_semantic_validation() -> None:
    res = load_fixtures().premortem_result
    plan = res.plan
    assert plan is not None
    llm = _openai_llm_call()

    effort = os.getenv("NEUMANN_LIVE_EFFORT") or "medium"  # 모듈 기본값과 같다
    out = attach_checklist(res, plan, llm, effort=effort)
    out = attach_validation(out, plan, llm, effort=effort)

    print("\n== 호출 기록 ==")
    for row in llm.log:
        print(json.dumps(row, ensure_ascii=False))
    print("== 체크리스트 ==")
    for it in out.checklist:
        v = it["validation"] or {}
        print(f"{it['item_id']} [{it['card_id']} {it['risk_code']}] gen={it['generator']} lines={it['plan_lines']}"
              f"({it['plan_lines_source']}) ev={len(it['evidence'])} dropped={it['dropped']} "
              f"행동판정={v.get('verdict_ko')}")
        print(f"   행동: {it['action']}")
        print(f"   확인: {it['verify']}")
    print("== 카드 판정 ==")
    for r in out.verification["semantic"]["cards"]:
        print(f"{r['card_id']}: {r['verdict_ko']}({r['verdict']}) judge={r['judge']} lines={r['cited_lines']} — {r['reason']}")
    for s in out.stages:
        if s.stage in ("checklist", "semantic_validate"):
            print(f"stage {s.stage}: {s.state} {s.elapsed_s}s {s.detail or ''} {s.counts}")

    assert all(row["ok"] for row in llm.log), llm.log
    stage = next(s for s in out.stages if s.stage == "checklist")
    assert stage.state == "ok", stage.detail
    assert out.checklist and all(it["generator"] == "astra" for it in out.checklist)
    valid = {ln.no for ln in plan.lines if ln.text.strip()}
    assert all(it["plan_lines"] and set(it["plan_lines"]) <= valid for it in out.checklist)
    report = out.verification["semantic"]
    assert report["status"] == "ok", report["reason"]
    assert all(r["verdict"] in VERDICTS for r in report["cards"])
    assert all(r["verdict"] in VERDICTS for r in report["actions"])


def test_live_astra_flags_card_whose_reason_does_not_match_cited_lines() -> None:
    """음성 대조: 해당 이유가 인용한 줄(연구 목표 5·6행)과 맞지 않는 카드를 astra가 '맞음'으로 넘기지 않는지.
    같은 카드의 행동(분할 규칙 문서화, 16·17행)은 카드 판정과 따로 남아야 한다."""
    from neumann.analyze.checklist import build_checklist
    from neumann.models import WhyApplies

    res = load_fixtures().premortem_result
    plan = res.plan
    assert plan is not None
    leak = next(c for c in res.risk_cards if c.card_id == "card-fx-leak")
    wrong = leak.model_copy(update={"why_applies": WhyApplies(
        text="The plan already uses a scaffold-grouped split and removes near-duplicate compositions.",
        plan_lines=[5, 6])})
    res = res.model_copy(update={"risk_cards": [wrong]})

    def scripted(schema: dict, instructions: str, input: str, *, effort: str) -> dict:
        return {"cards": [{"card_id": "card-fx-leak", "actions": [
            {"action": "무작위 분할 대신 조성 그룹 단위 분할 규칙을 문서로 고정한다.", "verify": "분할 규칙 문서가 있다.",
             "plan_lines": [16, 17], "evidence_ids": []}]}]}

    items = build_checklist(res, plan, scripted, generator="mock", model="scripted")
    res = res.model_copy(update={"checklist": items})
    llm = _openai_llm_call()
    out = attach_validation(res, plan, llm, effort=os.getenv("NEUMANN_LIVE_EFFORT") or "medium")
    report = out.verification["semantic"]
    card = report["cards"][0]
    action = report["actions"][0]
    print(f"\n음성 대조 카드: {card['verdict_ko']}({card['verdict']}) — {card['reason']}")
    print(f"그 카드의 행동: {action['verdict_ko']}({action['verdict']}) — {action['reason']}")
    print(f"호출: {llm.log}")
    assert all(row["ok"] for row in llm.log), llm.log
    assert card["verdict"] in ("mismatch", "weak") and card["judge"] == "astra"
    assert action["verdict"] in ("match", "weak")  # 카드가 틀려도 타당한 행동은 남는다
    assert len(out.checklist) == 1
