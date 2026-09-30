"""실제 astra 호출 테스트. NEUMANN_LIVE_TESTS=1일 때만 돈다(키 필요).

    NEUMANN_LIVE_TESTS=1 python -m pytest tests/e3/test_live_astra.py -q -s

근거 저장소: E2 실색인이 열리면 그것, 아니면 E3 fixture 코퍼스(tests/e3/corpus.py). 어느 쪽인지 출력한다.
"""

from __future__ import annotations

import json
import os

import pytest

from neumann.analyze.backend import FixtureBackend, IndexBackend
from neumann.pipeline import run_premortem, summarize
from tests.e3.corpus import build_backend
from tests.fixtures.loader import NEGATIVE_PLAN, plan_text

pytestmark = pytest.mark.skipif(
    os.getenv("NEUMANN_LIVE_TESTS") != "1" or not os.getenv("OPENAI_API_KEY"),
    reason="실제 API 테스트는 NEUMANN_LIVE_TESTS=1과 키가 있을 때만",
)


@pytest.fixture(scope="module")
def backend():
    try:
        be = IndexBackend()
        if be.search(["graph neural network electrolyte conductivity"], k=1):
            return be
    except Exception:  # noqa: BLE001 — 색인이 없으면 fixture
        pass
    return build_backend()


def _reviews(backend, result):
    out = {}
    for w in result.similar_works:
        for r in backend.get_reviews(w.work_id):
            out[r.review_id] = r.text
    return out


def _show(tag, result, backend):
    s = summarize(result)
    print(f"\n=== {tag} backend={getattr(backend, 'impl', backend.name)} ===")
    print(json.dumps({k: s[k] for k in ("status", "stages", "timings_s", "total_s", "no_card_reason", "verification")},
                     ensure_ascii=False, indent=1, default=str))
    for c in s["cards"]:
        print(f"- [{c['risk_code']}] {c['title']} ({c['generator']}, score {c['score']}, lines {c['plan_lines']}, works {len(c['works'])})")


def test_demo_plan_astra_path(backend):
    r = run_premortem(plan_text("plan.md"), provider="openai", backend=backend, cache_dir=None)
    _show("plan.md / astra", r, backend)
    assert len(r.risk_cards) >= 1
    assert all(c.generator.value == "astra" for c in r.risk_cards)
    assert all(s.state == "ok" for s in r.stages), [(s.stage, s.state, s.detail) for s in r.stages]
    src = _reviews(backend, r)
    ev = {e.excerpt_id: e for e in r.evidence}
    for c in r.risk_cards:
        for x in c.evidence:
            e = ev[x]
            assert src[e.source_id][e.start : e.end] == e.text and e.verify_against(src[e.source_id])
    assert r.verification["linkage_rate"] == 1.0


def test_negative_control_astra(backend):
    r = run_premortem(plan_text(NEGATIVE_PLAN), provider="openai", backend=backend, cache_dir=None)
    _show("negative_recipe.md / astra", r, backend)
    assert r.risk_cards == []
    assert "연구계획서가 아니다" in r.risk_synthesis["no_card_reason"] and "astra" in r.risk_synthesis["no_card_reason"]


def test_real_api_failure_goes_to_rule_path(backend, monkeypatch):
    """실제 API가 거부하는 모델명으로 강제 실패 → 단계마다 비상 규칙 경로, 강등 표시."""
    monkeypatch.setenv("NEUMANN_LLM_MODEL", "gpt-6-astra-does-not-exist")
    from neumann.llm import make_llm

    llm = make_llm(provider="openai")
    assert llm.model == "gpt-6-astra-does-not-exist"
    r = run_premortem(plan_text("plan.md"), llm=llm, backend=backend, cache_dir=None)
    _show("plan.md / forced API failure", r, backend)
    assert r.status == "degraded"
    assert r.risk_cards and all(c.generator.value == "rule" for c in r.risk_cards)
    for name in ("query_axes", "extract_issues", "synthesize_cards"):
        st = next(s for s in r.stages if s.stage == name)
        assert st.state == "degraded" and "api_error" in st.detail


def test_two_domains_differ_astra(backend):
    a = run_premortem(plan_text("plan.md"), provider="openai", backend=backend, cache_dir=None, k=4)
    b = run_premortem(plan_text("plan_medimaging.md"), provider="openai", backend=backend, cache_dir=None, k=4)
    _show("plan_medimaging.md / astra k=4", b, backend)
    wa = [w.work_id for w in a.similar_works]
    wb = [w.work_id for w in b.similar_works]
    print("plan.md works:", wa, "\nplan_medimaging.md works:", wb)
    assert set(wa) != set(wb)
    ea = {x for c in a.risk_cards for x in c.evidence}
    eb = {x for c in b.risk_cards for x in c.evidence}
    assert ea != eb
    if isinstance(backend, FixtureBackend):
        assert wa[0].startswith("fixture:A") and wb[0].startswith("fixture:B")
