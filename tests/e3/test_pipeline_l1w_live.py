"""E3-L1w 실제 astra: 실서버와 같은 호출(`run_premortem(plan_text)`, 설정 기본값)로 데모 plan.md를 두 번 돌린다.

    NEUMANN_LIVE_TESTS=1 python -m pytest tests/e3/test_pipeline_l1w_live.py -q -s

- 근거 저장소·provider·캐시는 서버와 같은 기본값(E2 실색인, openai, `data/cache`)이다.
- 1회차: 카드·예상 심사평·체크리스트·2차 검증 결과가 결과에 있고 `eval.linkage.check_result`가 통과한다.
- 2회차: 검색어 캐시가 적중해 같은 유사 연구가 나온다.
"""

from __future__ import annotations

import json
import os

import pytest

from neumann.pipeline import run_premortem, summarize
from tests.fixtures.loader import plan_text

pytestmark = pytest.mark.skipif(
    os.getenv("NEUMANN_LIVE_TESTS") != "1" or not os.getenv("OPENAI_API_KEY"),
    reason="실제 API 테스트는 NEUMANN_LIVE_TESTS=1과 키가 있을 때만",
)


def _reviews(result) -> dict[str, str]:
    from neumann.analyze.backend import IndexBackend

    be = IndexBackend()
    return {r.review_id: r.text for w in result.similar_works for r in be.get_reviews(w.work_id)}


def _show(tag: str, result, rep) -> None:
    s = summarize(result)
    keep = ("status", "stages", "total_s", "no_card_reason", "fitness", "query_cache", "expected_review", "semantic")
    print(f"\n=== {tag} ===")
    print(json.dumps({k: s[k] for k in keep}, ensure_ascii=False, indent=1, default=str))
    print("similar_works:", [w[0] for w in s["similar_works"]])
    for c in s["cards"]:
        print(f"- [{c['risk_code']}] {c['title']} ({c['generator']}, lines {c['plan_lines']}, works {len(c['works'])})")
    for it in s["checklist"]:
        print(f"  * {it['item_id']} {it['card_id']} {it['generator']} L{it['plan_lines']} [{it['verdict']}] {it['action']}")
    print(f"linkage: passed={rep.passed} rate={rep.linkage_rate} cards_ok={rep.cards_ok}/{rep.cards_total} "
          f"drop={rep.drop.findings_drop_rate if rep.drop.available else None}")


def test_demo_plan_v1_twice_with_query_cache():
    from eval.linkage import check_result

    text = plan_text("plan.md")
    first = run_premortem(text)  # 서버(neumann.api.main)와 같은 호출
    rep1 = check_result(first, _reviews(first))
    _show("plan.md 1회차", first, rep1)

    assert first.risk_cards and all(c.generator.value == "astra" for c in first.risk_cards)
    assert rep1.passed and rep1.linkage_rate == 1.0
    er = first.expected_review
    assert er["generator"] == "astra" and er["status"] == "ok", (er.get("status"), er.get("reason"))
    assert er["weakness"] and all(s["c"] for s in er["weakness"])
    assert first.checklist and any(it["generator"] == "astra" for it in first.checklist)
    assert {it["card_id"] for it in first.checklist} == {c.card_id for c in first.risk_cards}
    sem = first.verification["semantic"]
    assert sem["generator"] == "astra" and sem["counts"]["calls"] >= 1
    assert {r["card_id"] for r in sem["cards"]} == {c.card_id for c in first.risk_cards}
    names = [s.stage for s in first.stages]
    assert names[-3:] == ["expected_review", "checklist", "semantic_validate"]
    assert first.manifest["total_s"] > 0 and set(first.manifest["timings_s"]) == set(names)

    second = run_premortem(text)
    rep2 = check_result(second, _reviews(second))
    _show("plan.md 2회차", second, rep2)
    assert second.plan_checks["queries"]["cache"]["hit"] is True
    assert second.plan_checks["queries"]["queries"] == first.plan_checks["queries"]["queries"]
    assert [w.work_id for w in second.similar_works] == [w.work_id for w in first.similar_works]
    assert rep2.passed
