"""E3-L1w: 파이프라인 v1 연결(mock·fixture, 실제 API 없음).

적합성(E3-L1c) → … → 예상 심사평(E3-L1a) → 체크리스트 → 2차 검증(E3-L1b). 단계마다 실패하면 그 단계만 강등.
적합성 모듈이 아직 없으면(E3-L1c 병합 전) 가짜 모듈로 연결을 시험하고, 실제 모듈 시험은 있을 때만 돈다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest

import neumann.pipeline as pl
from neumann.analyze import checklist as checklist_mod
from neumann.analyze.backend import FixtureBackend
from neumann.analyze.mock_responders import default_responders
from neumann.llm import DisabledProvider, MockProvider
from neumann.models import StageStatus
from neumann.pipeline import FITNESS_MISSING, MOCK_NOTICE, V1_STAGES, run_premortem
from tests.e3.corpus import PLAN_BATTERY, PLAN_IMAGING, RECIPE, build, build_backend

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "contracts" / "premortem_response.schema.json").read_text(encoding="utf-8"))
UI_CONTRACT = ROOT / "contracts" / "ui_view.schema.json"
STAGES = ["plan_normalize", "fitness", "query_axes", "search", "extract_issues", "synthesize_cards", "verify_evidence",
          "expected_review", "checklist", "semantic_validate"]
V1 = [name for name, _ in V1_STAGES]
PHASES = {"fitness": "INPUT", "expected_review": "REVIEW", "checklist": "ACTION", "semantic_validate": "ACTION"}


class AstraLike(MockProvider):
    """응답은 결정적이지만 이름은 openai(생성 주체 astra)인 시험용 provider."""

    name = "openai"


def _run(plan: str = PLAN_BATTERY, *, llm=None, provider: str | None = "mock", backend=None, cache_dir=None, **kw):
    return run_premortem(plan, llm=llm, provider=None if llm is not None else provider,
                         backend=backend or build_backend(), cache_dir=cache_dir, **kw)


def _st(result, name) -> StageStatus:
    return next(s for s in result.stages if s.stage == name)


def _tasks(llm: MockProvider) -> list[str]:
    return [c.task for c in llm.calls]


def _reviews(backend: FixtureBackend) -> dict[str, str]:
    return {r.review_id: r.text for rs in backend.reviews.values() for r in rs}


@pytest.fixture
def no_fitness(monkeypatch):
    """적합성 모듈이 없는 상태(E3-L1c 병합 전)를 강제한다."""
    monkeypatch.setattr(pl, "_load_fitness", lambda: None)


# ── 전 단계(mock) ──────────────────────────────────────────────────────────


def test_mock_all_stages_attached_in_order_with_results(no_fitness):
    be = build_backend()
    llm = MockProvider(default_responders())
    r = _run(llm=llm, backend=be)
    assert [s.stage for s in r.stages] == STAGES
    assert _st(r, "fitness").state == "skipped" and _st(r, "fitness").detail == FITNESS_MISSING
    for name in V1:
        st = _st(r, name)
        assert st.state == "ok", (name, st.detail)
        assert st.phase == PHASES[name] and st.impl and st.impl.startswith("neumann.analyze.")
    assert r.risk_cards and all(c.generator.value == "mock" for c in r.risk_cards)
    # 예상 심사평: mock 표기, 게이트 통과 문장, 문장마다 근거 excerpt id
    er = r.expected_review
    assert er["generator"] == "mock" and er["status"] == "ok" and er["audit"]["pass"] > 0
    ev_ids = {e.excerpt_id for e in r.evidence}
    assert all(set(s["c"]) <= ev_ids and s["c"] for sec in ("weakness", "request") for s in er[sec])
    # 체크리스트: 카드마다 행동, 계획서 줄·카드 근거에 연결, mock 표기
    card_ids = {c.card_id for c in r.risk_cards}
    assert {it["card_id"] for it in r.checklist} == card_ids
    for it in r.checklist:
        card = next(c for c in r.risk_cards if c.card_id == it["card_id"])
        assert it["generator"] == "mock" and it["plan_lines"] and set(it["evidence"]) <= set(card.evidence)
        assert it["validation"]["verdict"] in ("match", "weak", "mismatch") and it["card_verdict"]
    # 2차 검증: 체크리스트 뒤에 돌아 행동까지 판정
    sem = r.verification["semantic"]
    assert sem["generator"] == "mock" and sem["status"] == "ok"
    assert {row["card_id"] for row in sem["cards"]} == card_ids
    assert {row["item_id"] for row in sem["actions"]} == {it["item_id"] for it in r.checklist}
    # LLM 호출 순서: 체크리스트가 검증보다 먼저
    tasks = _tasks(llm)
    assert tasks.index("expected_review") < tasks.index("checklist") < tasks.index("semantic_validate")
    # mock은 status를 ok로 두지 않는다(SEC-1 S-05)
    assert r.status == "degraded" and MOCK_NOTICE in r.notices
    jsonschema.validate(r.model_dump(mode="json"), CONTRACT)


def test_timings_total_and_limits_recorded(no_fitness):
    r = _run()
    timings = r.manifest["timings_s"]
    assert list(timings) == STAGES
    assert all(timings[s.stage] == s.elapsed_s for s in r.stages)
    assert r.manifest["total_s"] >= max(timings.values()) and r.manifest["total_s"] > 0
    limits = r.manifest["stage_limits_s"]
    assert set(V1) | {"query_axes"} <= set(limits) and all(v > 0 for v in limits.values())
    assert r.manifest["pipeline_version"] == pl.PIPELINE_VERSION == r.pipeline_version
    assert "expected_review@v1" in r.manifest["prompt_versions"]


def test_llm_calls_carry_task_limits_and_efforts(no_fitness, monkeypatch):
    monkeypatch.setenv("NEUMANN_LLM_TIMEOUT_CHECKLIST_S", "17")
    llm = MockProvider(default_responders())
    r = _run(llm=llm)
    by_task = {c.task: c for c in llm.calls}
    assert by_task["checklist"].timeout_s == 17.0 and r.manifest["stage_limits_s"]["checklist"] == 17.0
    assert by_task["expected_review"].timeout_s == 90.0 and by_task["expected_review"].effort == "medium"
    assert by_task["semantic_validate"].effort == "medium"


def test_linkage_checker_passes_with_v1_results(no_fitness):
    from eval.linkage import check_result

    be = build_backend()
    r = _run(backend=be)
    rep = check_result(r, _reviews(be))
    assert rep.passed and rep.linkage_rate == 1.0 and rep.card_pass_rate == 1.0
    assert check_result(r.model_dump(mode="json"), _reviews(be)).passed


def test_ui_view_accepts_v1_result(no_fitness):
    view_mod = pytest.importorskip("neumann.api.view")
    r = _run()
    view = view_mod.build_ui_view(r)
    assert view["review"] and view["checklist"]
    names = [log[1] for g in view.get("pipeline", []) for log in g.get("log", [])]
    assert any("checklist" in n for n in names) and any("expected_review" in n for n in names)
    if UI_CONTRACT.exists():
        jsonschema.validate(view, json.loads(UI_CONTRACT.read_text(encoding="utf-8")))


# ── 단계별 실패 → 그 단계만 강등 ───────────────────────────────────────────


@pytest.mark.parametrize("failing", V1)
def test_llm_failure_degrades_only_that_stage(no_fitness, failing):
    base = _run()
    llm = MockProvider(default_responders(), fail={failing: "timeout"})
    r = _run(llm=llm)
    assert [c.card_id for c in r.risk_cards] == [c.card_id for c in base.risk_cards]
    for name in STAGES:
        st = _st(r, name)
        if name == failing:
            assert st.state == "degraded", (name, st.detail)
            assert "timeout" in (st.detail or "") or "미검증" in (st.detail or "")
        elif name == "fitness":
            assert st.state == "skipped"
        else:
            assert st.state == "ok", (name, st.state, st.detail)
    assert r.status == "degraded"
    assert any(n.startswith(f"[{failing}]") or "2차 의미검증" in n for n in r.notices)
    if failing == "expected_review":
        assert r.expected_review["generator"] == "rule" and r.expected_review["status"] == "degraded"
        assert r.checklist and all(it["generator"] == "mock" for it in r.checklist)
    if failing == "checklist":
        assert r.checklist and all(it["generator"] == "rule" and it["fallback_reason"] for it in r.checklist)
        assert r.verification["semantic"]["status"] == "ok"  # 규칙 행동도 검증은 된다
    if failing == "semantic_validate":
        sem = r.verification["semantic"]
        assert sem["status"] == "degraded" and sem["counts"]["cards_unverified"] == len(r.risk_cards)
        assert r.checklist and all(it["generator"] == "mock" for it in r.checklist)  # 행동은 지우지 않는다


@pytest.mark.parametrize("target", ["attach_expected_review", "attach_checklist", "attach_validation"])
def test_exception_in_a_v1_stage_is_contained(no_fitness, monkeypatch, target):
    stage = {"attach_expected_review": "expected_review", "attach_checklist": "checklist",
             "attach_validation": "semantic_validate"}[target]
    module = {"attach_expected_review": pl.review_mod, "attach_checklist": pl.checklist_mod,
              "attach_validation": pl.validate_mod}[target]
    secret = "C:\\Users\\alice\\secret\\x.json"

    def boom(*a: Any, **kw: Any):
        raise RuntimeError(secret)

    monkeypatch.setattr(module, target, boom)
    r = _run()
    st = _st(r, stage)
    assert st.state == "error" and "RuntimeError" in st.detail and secret not in st.detail
    assert r.status == "degraded" and r.risk_cards
    others = [n for n in V1 if n != stage]
    assert all(_st(r, n).state == "ok" for n in others), [(n, _st(r, n).state) for n in others]
    assert secret not in json.dumps(r.model_dump(mode="json"), ensure_ascii=False)


def test_provider_off_marks_v1_stages_rule_or_unverified(no_fitness):
    r = _run(provider="off")
    assert r.risk_cards and all(c.generator.value == "rule" for c in r.risk_cards)
    assert r.expected_review["generator"] == "rule" and _st(r, "expected_review").state == "degraded"
    assert r.checklist and all(it["generator"] == "rule" for it in r.checklist)
    assert _st(r, "checklist").state == "degraded"
    sem = r.verification["semantic"]
    assert sem["generator"] == "rule" and sem["status"] == "degraded"
    assert all(row["verdict"] in ("unverified", "weak") for row in sem["cards"])  # 규칙으로 의미 판정을 흉내 내지 않는다
    assert r.status == "degraded" and MOCK_NOTICE not in r.notices


def test_zero_cards_skips_v1_without_llm_calls(no_fitness):
    works, _ = build()
    llm = MockProvider(default_responders())
    r = _run(llm=llm, backend=FixtureBackend(works, []))
    assert r.risk_cards == []
    for name in V1:
        assert _st(r, name).state == "skipped"
    assert not {"expected_review", "checklist", "semantic_validate"} & set(_tasks(llm))
    assert r.risk_synthesis["no_card_reason"]


def test_llm_call_for_uses_provider_attribute_and_refuses_unknown():
    call, opts, why = pl._llm_call_for(MockProvider(default_responders()), "checklist", None)
    assert call.generator == "mock" and call.task == "checklist" and why is None and opts["timeout_s"] > 0
    call, _, _ = pl._llm_call_for(AstraLike(default_responders(), model="gpt-6-astra"), "expected_review", None)
    assert call.generator == "astra" and call.model == "gpt-6-astra"
    call, _, _ = pl._llm_call_for(DisabledProvider(), "fitness", None)
    assert call.generator == "rule"

    class Unknown:
        name, model = "boom", "x"

        def complete_json(self, c):  # pragma: no cover — 부르지 않아야 한다
            raise AssertionError("부르면 안 된다")

    call, opts, why = pl._llm_call_for(Unknown(), "checklist", None)
    assert call is None and "생성 주체" in why and opts["timeout_s"] > 0


# ── 적합성 연결(가짜 모듈: E3-L1c 인터페이스대로) ────────────────────────────


def _fake_fitness(verdict: str, *, record: list | None = None, raises: Exception | None = None):
    def assess_fitness(plan, llm_call, *, effort="low", **kw):
        if record is not None:
            record.append({"generator": getattr(llm_call, "generator", None), "effort": effort,
                           "plan_id": plan.plan_id})
        if raises is not None:
            raise raises
        return {
            "verdict": verdict, "analyze": verdict != "unfit", "reason": f"가짜 판정 {verdict}",
            "notice": f"분석하지 않음: 가짜 판정 {verdict}" if verdict == "unfit" else None,
            "generator": getattr(llm_call, "generator", "rule"), "status": "ok", "decided_by": "llm",
            "degraded_reason": None, "elapsed_s": 0.0, "checks": {},
        }

    def fitness_stage(result):
        return StageStatus(stage="fitness", state="ok", detail=f"{result['verdict']} by {result['generator']}",
                           phase="input", impl="fake:assess_fitness", counts={"elements_present": 4})

    return SimpleNamespace(assess_fitness=assess_fitness, fitness_stage=fitness_stage)


def test_unfit_stops_before_search_with_zero_cards(monkeypatch):
    seen: list = []
    monkeypatch.setattr(pl, "_load_fitness", lambda: _fake_fitness("unfit", record=seen))
    llm = MockProvider(default_responders())
    r = _run(PLAN_BATTERY, llm=llm)
    assert r.risk_cards == [] and r.similar_works == []
    reason = r.risk_synthesis["no_card_reason"]
    assert reason.startswith("입력이 연구계획서가 아니다(mock 판단: 가짜 판정 unfit)") and "검색 안 함" in reason
    assert _st(r, "fitness").state == "ok" and _st(r, "fitness").phase == "INPUT"
    for name in ("query_axes", "search", "extract_issues", "synthesize_cards", "verify_evidence", *V1):
        assert _st(r, name).state == "skipped", name
    assert _tasks(llm) == []  # astra ①·추출·합성·v1 모두 부르지 않았다
    assert r.plan_checks["suitability"]["is_research_plan"] is False
    assert r.plan_checks["suitability"]["source"] == "fitness" and r.plan_checks["fitness"]["verdict"] == "unfit"
    assert "분석하지 않음: 가짜 판정 unfit" in r.notices and any("위험카드 0장" in n for n in r.notices)
    assert seen == [{"generator": "mock", "effort": "low", "plan_id": r.plan_id}]  # 어댑터 표기·상한이 넘어간다
    jsonschema.validate(r.model_dump(mode="json"), CONTRACT)


def test_unfit_result_matches_old_recipe_handling(monkeypatch):
    """적합성 판정이 조리법 처리를 대체해도 결과(카드 0장·같은 꼴의 사유·판정 기록)는 같다."""
    monkeypatch.setattr(pl, "_load_fitness", lambda: None)  # 옛 처리(astra ① 판정)
    old = _run(RECIPE)
    monkeypatch.setattr(pl, "_load_fitness", lambda: _fake_fitness("unfit"))
    new = _run(RECIPE)
    for r in (old, new):
        assert r.risk_cards == [] and r.checklist == []
        assert r.risk_synthesis["no_card_reason"].startswith("입력이 연구계획서가 아니다(mock 판단: ")
        assert r.plan_checks["suitability"]["is_research_plan"] is False
        assert _st(r, "extract_issues").state == "skipped"
        assert any("위험카드 0장" in n for n in r.notices)


def test_fit_overrides_query_axes_rejection_but_uncertain_does_not(monkeypatch):
    # 조리법을 적합성은 fit이라고 보면(가짜) astra ①의 '연구 아님'으로 멈추지 않는다
    monkeypatch.setattr(pl, "_load_fitness", lambda: _fake_fitness("fit"))
    r = _run(RECIPE)
    assert "연구계획서가 아니다" not in (r.risk_synthesis.get("no_card_reason") or "")
    assert _st(r, "search").state == "ok"
    # uncertain이면 astra ①도 연구가 아니라고 볼 때 멈춘다(사유에 둘 다)
    monkeypatch.setattr(pl, "_load_fitness", lambda: _fake_fitness("uncertain"))
    r = _run(RECIPE)
    reason = r.risk_synthesis["no_card_reason"]
    assert "연구계획서가 아니다(mock 판단" in reason and "적합성 판정 보류" in reason
    # uncertain + 연구계획서면 분석한다
    r = _run(PLAN_BATTERY)
    assert r.risk_cards


def test_fitness_exception_degrades_only_that_stage(monkeypatch):
    monkeypatch.setattr(pl, "_load_fitness", lambda: _fake_fitness("fit", raises=RuntimeError("C:\\secret\\p")))
    r = _run(PLAN_BATTERY)
    st = _st(r, "fitness")
    assert st.state == "error" and "RuntimeError" in st.detail and "secret" not in st.detail
    assert r.risk_cards and all(_st(r, n).state == "ok" for n in STAGES if n != "fitness")
    assert r.status == "degraded" and "fitness" not in r.plan_checks


def test_missing_fitness_module_is_recorded(no_fitness):
    r = _run(PLAN_BATTERY)
    st = _st(r, "fitness")
    assert st.state == "skipped" and st.detail == FITNESS_MISSING and st.phase == "INPUT"
    assert r.risk_cards  # 조리법 처리는 astra ① 판정으로 계속된다
    rec = _run(RECIPE)
    assert rec.risk_cards == [] and "연구계획서가 아니다" in rec.risk_synthesis["no_card_reason"]


# ── 적합성 연결(실제 E3-L1c 모듈: 병합돼 있을 때만) ──────────────────────────


@pytest.fixture
def real_fitness():
    return pytest.importorskip("neumann.analyze.fitness", reason="E3-L1c 적합성 모듈이 아직 병합되지 않았다")


def test_real_fitness_fit_plan_runs_all_stages(real_fitness):
    llm = MockProvider(default_responders())
    r = _run(PLAN_BATTERY, llm=llm)
    assert [s.stage for s in r.stages] == STAGES
    st = _st(r, "fitness")
    assert st.state == "ok" and st.phase == "INPUT" and st.impl == "neumann.analyze.fitness:assess_fitness"
    fit = r.plan_checks["fitness"]
    assert fit["verdict"] == "fit" and fit["generator"] == "mock" and fit["analyze"] is True
    assert r.risk_cards and all(_st(r, n).state == "ok" for n in STAGES)
    assert _tasks(llm)[0] == "fitness"
    jsonschema.validate(r.model_dump(mode="json"), CONTRACT)


def test_real_fitness_recipe_is_not_analyzed(real_fitness):
    llm = MockProvider(default_responders())
    r = _run(RECIPE, llm=llm)
    assert r.risk_cards == [] and r.similar_works == []
    reason = r.risk_synthesis["no_card_reason"]
    assert "연구계획서가 아니다" in reason and "mock 판단" in reason
    assert _tasks(llm) == ["fitness"]  # 검색어·추출·합성·v1은 부르지 않았다
    assert r.plan_checks["suitability"]["is_research_plan"] is False


def test_real_fitness_failure_falls_back_to_rule_only_there(real_fitness):
    llm = MockProvider(default_responders(), fail={"fitness": "timeout"})
    r = _run(PLAN_BATTERY, llm=llm)
    st = _st(r, "fitness")
    assert st.state == "degraded" and "timeout" in st.detail
    assert r.plan_checks["fitness"]["generator"] == "rule" and r.plan_checks["fitness"]["decided_by"] == "rule_fallback"
    assert r.risk_cards and all(_st(r, n).state == "ok" for n in STAGES if n != "fitness")


# ── 검색어 캐시(파이프라인) ─────────────────────────────────────────────────


def test_query_cache_gives_same_similar_works_and_is_reported(no_fitness, tmp_path):
    be = build_backend()
    llm = AstraLike(default_responders(), model="gpt-6-astra")
    first = _run(PLAN_BATTERY, llm=llm, backend=be, cache_dir=tmp_path, session_id="s1")
    second = _run(PLAN_BATTERY, llm=llm, backend=be, cache_dir=tmp_path, session_id="s2")
    assert _tasks(llm).count("query_axes") == 1
    assert first.plan_checks["queries"]["cache"]["hit"] is False and first.plan_checks["queries"]["cache"]["stored"]
    assert second.plan_checks["queries"]["cache"]["hit"] is True and second.manifest["query_cache"]["hit"] is True
    qa = _st(second, "query_axes")
    assert qa.state == "ok" and qa.counts["cache_hit"] == 1 and "캐시 적중" in qa.detail and qa.impl.startswith("cache:")
    assert second.plan_checks["queries"]["queries"] == first.plan_checks["queries"]["queries"]
    assert [w.work_id for w in second.similar_works] == [w.work_id for w in first.similar_works]
    assert first.status == "ok" and second.status == "ok"  # astra 표기 경로, 캐시 적중은 강등이 아니다
    assert list((tmp_path / "queries").glob("*.json")) and list((tmp_path / "extract").glob("*.json"))
    other = _run(PLAN_IMAGING, llm=llm, backend=be, cache_dir=tmp_path)
    assert other.plan_checks["queries"]["cache"]["hit"] is False


def test_no_cache_dir_disables_query_cache(no_fitness):
    llm = AstraLike(default_responders(), model="gpt-6-astra")
    a = _run(PLAN_BATTERY, llm=llm)
    b = _run(PLAN_BATTERY, llm=llm)
    assert _tasks(llm).count("query_axes") == 2
    assert not a.manifest["query_cache"]["enabled"] and not b.plan_checks["queries"]["cache"]["hit"]


def test_with_stage_helper_is_what_pipeline_uses_for_errors():
    # 파이프라인은 E3-L1b의 with_stage로 error 단계를 붙인다(강등이면 status도 degraded)
    assert pl.checklist_mod.with_stage is checklist_mod.with_stage
