"""E3-L1y: 카드 뒤 v1 단계 병렬화와 진행 보고(on_stage). mock·fixture만(실제 API 없음).

- 의존 그래프: 예상 심사평 ∥ (체크리스트 → 2차 검증). 모듈 입력을 바꿔 보며 코드로 확인한다.
- 병렬 결과 = 순차 결과(카드·예상 심사평·체크리스트·검증·단계 목록·notices·status), 실패·예외·꺼짐 포함.
- 한 단계 실패가 다른 단계에 번지지 않고 강등 표시가 남는다(실제로 겹쳐 도는 상태에서).
- on_stage 호출 순서·횟수, 콜백 스레드, 콜백 예외 무시.
- 스레드 안전: 단계별 llm_call이 따로라 모델·생성 주체·실패 사유가 섞이지 않는다(PM 추가 요건), v1 작업 스레드는
  캐시를 쓰지 않는다.
"""

from __future__ import annotations

import json
import random
import threading
import time
from typing import Any

import pytest

import neumann.pipeline as pl
from neumann.analyze import checklist as checklist_mod
from neumann.analyze import extract as extract_mod
from neumann.analyze import queries as queries_mod
from neumann.analyze import review as review_mod
from neumann.analyze import validate as validate_mod
from neumann.analyze.mock_responders import default_responders
from neumann.llm import LLMCall, LLMResult, MockProvider
from neumann.pipeline import V1_DEPENDS, V1_STAGES, run_premortem
from tests.e3.corpus import PLAN_BATTERY, PLAN_IMAGING, build_backend

V1 = [name for name, _ in V1_STAGES]
PRE_V1 = ["plan_normalize", "fitness", "query_axes", "search", "extract_issues", "synthesize_cards", "verify_evidence"]
TERMINAL = {"ok", "degraded", "error", "skipped"}
# 실행마다 달라지는 값(시간). 나머지는 모두 같아야 한다.
VOLATILE = {"elapsed_s", "latency_s", "total_s", "timings_s", "v1_wall_s", "v1_parallel", "generated_at"}


class AstraLike(MockProvider):
    """응답은 결정적이지만 이름은 openai(생성 주체 astra)인 시험용 provider."""

    name = "openai"


class SlowMock(MockProvider):
    """호출마다 지연(과제별)을 넣고, 호출 구간(시작·끝·스레드)을 기록한다."""

    def __init__(self, *a: Any, delays: dict[str, float] | None = None, jitter: float = 0.0, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.delays = dict(delays or {})
        self.jitter = jitter
        self.spans: list[tuple[str, float, float, str]] = []
        self._lock = threading.Lock()

    def complete_json(self, call: LLMCall) -> LLMResult:
        t0 = time.perf_counter()
        time.sleep(self.delays.get(call.task, 0.0) + (random.random() * self.jitter if self.jitter else 0.0))
        res = super().complete_json(call)
        with self._lock:
            self.spans.append((call.task, t0, time.perf_counter(), threading.current_thread().name))
        return res


class SlowAstra(SlowMock):
    name = "openai"


class TaskModelAstra(SlowAstra):
    """실제 호출 결과의 모델명이 과제마다 다른 provider(결과 표기가 스레드 사이에 섞이는지 보려고)."""

    def complete_json(self, call: LLMCall) -> LLMResult:
        res = super().complete_json(call)
        res.model = f"{self.model}@{call.task}"
        return res


def _norm(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [_norm(v) for v in x]
    return x


def _dump(r) -> dict[str, Any]:
    return _norm(r.model_dump(mode="json"))


def _run(plan: str = PLAN_BATTERY, *, llm=None, provider: str | None = "mock", **kw):
    kw.setdefault("backend", build_backend())
    kw.setdefault("cache_dir", None)
    kw.setdefault("session_id", "sess-e3-l1y")
    return run_premortem(plan, llm=llm, provider=None if llm is not None else provider, **kw)


def _both(monkeypatch, make_llm, **kw):
    """같은 입력으로 순차(E3-L1w)·병렬(E3-L1y) 한 번씩."""
    out = {}
    for mode in (False, True):
        monkeypatch.setattr(pl, "V1_PARALLEL", mode)
        out[mode] = _run(llm=make_llm(), **kw)
    return out[False], out[True]


def _st(result, name):
    return next(s for s in result.stages if s.stage == name)


@pytest.fixture
def no_fitness(monkeypatch):
    monkeypatch.setattr(pl, "_load_fitness", lambda: None)


# ── 의존 그래프 ────────────────────────────────────────────────────────────


def test_dependency_graph_is_checklist_then_validate_only():
    assert V1_DEPENDS == {"expected_review": (), "checklist": (), "semantic_validate": ("checklist",)}
    assert set(V1_DEPENDS) == set(V1) and pl._v1_graph_errors() == []
    # 검사기가 틀린 그래프를 잡는다(두 의존, 뒤 단계 의존, 빠진 단계)
    assert pl._v1_graph_errors(depends={**V1_DEPENDS, "checklist": ("expected_review", "semantic_validate")})
    assert pl._v1_graph_errors(depends={**V1_DEPENDS, "checklist": ("semantic_validate",)})
    assert pl._v1_graph_errors(depends={k: v for k, v in V1_DEPENDS.items() if k != "checklist"})


def test_dependency_graph_holds_in_module_code(no_fitness, monkeypatch):
    """모듈에 서로의 결과를 넣고 빼 보며 확인: 심사평·체크리스트는 서로 안 읽고, 검증은 체크리스트를 읽는다."""
    monkeypatch.setattr(pl, "V1_PARALLEL", False)
    full = _run()
    assert full.expected_review and full.checklist and full.verification.get("semantic")
    base = full.model_copy(update={"expected_review": {}, "checklist": [],
                                   "verification": {k: v for k, v in full.verification.items() if k != "semantic"}})
    llm = MockProvider(default_responders())

    def call(task):
        return pl._llm_call_for(llm, task, None)[0]

    # 체크리스트: 예상 심사평이 있든 없든 같은 항목
    with_review = base.model_copy(update={"expected_review": full.expected_review})
    assert (checklist_mod.build_checklist(base, base.plan, call("checklist"))
            == checklist_mod.build_checklist(with_review, base.plan, call("checklist")))
    # 예상 심사평: 체크리스트·검증이 있든 없든 같은 문장
    with_list = base.model_copy(update={"checklist": full.checklist, "verification": full.verification})
    a = review_mod.generate_expected_review(base, call("expected_review"))
    b = review_mod.generate_expected_review(with_list, call("expected_review"))
    assert _norm(a) == _norm(b)
    # 2차 검증: 체크리스트가 있어야 행동을 판정한다 → 체크리스트 뒤에 돌아야 한다
    no_items = validate_mod.validate_cards(base, base.plan, call("semantic_validate"))
    with_items = validate_mod.validate_cards(with_list, base.plan, call("semantic_validate"))
    assert no_items["actions"] == [] and len(with_items["actions"]) == len(full.checklist) > 0


# ── 병렬 = 순차 ────────────────────────────────────────────────────────────


SCENARIOS: dict[str, Any] = {
    "mock": lambda: MockProvider(default_responders()),
    "astra_like": lambda: AstraLike(default_responders(), model="gpt-6.1-sol"),
    **{f"fail_{t}": (lambda t=t: MockProvider(default_responders(), fail={t: "timeout"})) for t in V1},
    "fail_all_v1": lambda: MockProvider(default_responders(), fail={t: "api_error" for t in V1}),
    "slow_jitter": lambda: SlowMock(default_responders(), delays={t: 0.02 for t in V1}, jitter=0.03),
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_parallel_result_equals_sequential(no_fitness, monkeypatch, scenario):
    seq, par = _both(monkeypatch, SCENARIOS[scenario])
    assert _dump(par) == _dump(seq)
    # 핵심 항목은 따로도 확인(차이가 나면 어디인지 바로 보이게)
    assert [s.stage for s in par.stages] == [s.stage for s in seq.stages] == PRE_V1 + V1
    assert [(s.stage, s.state, s.phase, s.impl, s.detail) for s in par.stages] == \
        [(s.stage, s.state, s.phase, s.impl, s.detail) for s in seq.stages]
    assert _norm(par.expected_review) == _norm(seq.expected_review)
    assert par.checklist == seq.checklist and par.notices == seq.notices and par.status == seq.status
    assert par.manifest["v1_parallel"] is True and seq.manifest["v1_parallel"] is False
    assert list(par.manifest["timings_s"]) == PRE_V1 + V1


def test_parallel_equals_sequential_with_provider_off_and_other_plan(no_fitness, monkeypatch):
    for kw in ({"provider": "off"}, {"provider": "mock"}):
        out = {}
        for mode in (False, True):
            monkeypatch.setattr(pl, "V1_PARALLEL", mode)
            out[mode] = _run(PLAN_IMAGING, **kw)
        assert _dump(out[True]) == _dump(out[False]), kw


def test_parallel_equals_sequential_with_real_fitness_module(monkeypatch):
    if pl._load_fitness() is None:
        pytest.skip("적합성 모듈(E3-L1c) 없음")
    seq, par = _both(monkeypatch, lambda: MockProvider(default_responders()))
    assert _st(par, "fitness").state != "skipped" and _dump(par) == _dump(seq)


@pytest.mark.parametrize("target", ["attach_expected_review", "attach_checklist", "attach_validation"])
def test_exception_in_one_stage_equals_sequential_and_is_contained(no_fitness, monkeypatch, target):
    module = {"attach_expected_review": review_mod, "attach_checklist": checklist_mod,
              "attach_validation": validate_mod}[target]
    stage = {"attach_expected_review": "expected_review", "attach_checklist": "checklist",
             "attach_validation": "semantic_validate"}[target]

    def boom(*a: Any, **kw: Any):
        time.sleep(0.05)  # 다른 단계가 도는 동안 죽게
        raise RuntimeError("C:\\Users\\alice\\secret.json")

    monkeypatch.setattr(module, target, boom)
    seq, par = _both(monkeypatch, lambda: SlowMock(default_responders(), delays={t: 0.05 for t in V1}))
    assert _dump(par) == _dump(seq)
    st = _st(par, stage)
    assert st.state == "error" and "RuntimeError" in st.detail and "alice" not in st.detail
    assert par.status == "degraded" and par.risk_cards
    for other in (n for n in V1 if n != stage):
        assert _st(par, other).state == "ok", (other, _st(par, other).detail)
    if stage == "checklist":  # 체크리스트가 죽으면 검증은 카드만 판정(순차와 같다)
        assert par.checklist == [] and par.verification["semantic"]["actions"] == []


# ── 실제로 겹쳐 돈다 + 실패 격리 ──────────────────────────────────────────


def test_v1_stages_overlap_and_respect_dependency(no_fitness, monkeypatch):
    """두 독립 단계는 함께 진입하고, 검증은 체크리스트 반환 뒤에만 진입한다."""
    monkeypatch.setattr(pl, "V1_PARALLEL", True)
    rendezvous = threading.Barrier(2, timeout=20)
    checklist_done = threading.Event()
    completed_checklists: list[list] = []
    entered: dict[str, int] = {}
    violations: list[str] = []

    def wrap(module, target, stage):
        original = getattr(module, target)

        def run(*args, **kwargs):
            entered[stage] = threading.get_ident()
            if stage == "semantic_validate":
                if not checklist_done.is_set():
                    violations.append("2차 검증이 체크리스트 반환 전에 진입했다")
                elif not args[0].checklist or args[0].checklist != completed_checklists[0]:
                    violations.append("2차 검증에 완료된 체크리스트가 전달되지 않았다")
            else:
                try:
                    rendezvous.wait()
                except threading.BrokenBarrierError:
                    # 파이프라인은 단계 예외를 결과로 변환하므로 바깥에서도 실패를 검사한다.
                    violations.append("예상 심사평과 체크리스트가 함께 진입하지 못했다")
            result = original(*args, **kwargs)
            if stage == "checklist":
                completed_checklists.append(result.checklist)
                checklist_done.set()
            return result

        monkeypatch.setattr(module, target, run)

    wrap(review_mod, "attach_expected_review", "expected_review")
    wrap(checklist_mod, "attach_checklist", "checklist")
    wrap(validate_mod, "attach_validation", "semantic_validate")
    r = _run()
    assert violations == []
    assert set(entered) == set(V1)
    assert all(ident != threading.get_ident() for ident in entered.values())
    assert all(_st(r, stage).state == "ok" for stage in V1)
    assert r.expected_review and r.checklist and r.verification["semantic"]


@pytest.mark.parametrize("failing", V1)
def test_failure_in_one_overlapping_stage_degrades_only_it(no_fitness, monkeypatch, failing):
    monkeypatch.setattr(pl, "V1_PARALLEL", True)
    llm = SlowMock(default_responders(), delays={t: 0.05 for t in V1}, fail={failing: "timeout"})
    r = _run(llm=llm)
    for name in V1:
        st = _st(r, name)
        if name == failing:
            assert st.state == "degraded" and ("timeout" in (st.detail or "") or "미검증" in (st.detail or ""))
        else:
            assert st.state == "ok", (name, st.detail)
    assert r.status == "degraded"
    assert any(n.startswith(f"[{failing}]") or "2차 의미검증" in n for n in r.notices)
    if failing == "expected_review":
        assert r.expected_review["generator"] == "rule" and all(it["generator"] == "mock" for it in r.checklist)
    if failing == "checklist":
        assert all(it["generator"] == "rule" for it in r.checklist)
        assert r.verification["semantic"]["status"] == "ok"
    if failing == "semantic_validate":
        assert r.verification["semantic"]["counts"]["cards_unverified"] == len(r.risk_cards)
        assert r.expected_review["status"] == "ok"


# ── 진행 보고(on_stage) ────────────────────────────────────────────────────


def _record(events: list, threads: list):
    def cb(stage: str, state: str, elapsed_s: float) -> None:
        events.append((stage, state, elapsed_s))
        threads.append(threading.current_thread().ident)
    return cb


@pytest.mark.parametrize("parallel", [True, False])
def test_on_stage_order_and_counts(no_fitness, monkeypatch, parallel):
    monkeypatch.setattr(pl, "V1_PARALLEL", parallel)
    events: list[tuple[str, str, float]] = []
    threads: list[int | None] = []
    llm = SlowMock(default_responders(), delays={t: 0.05 for t in V1}, jitter=0.05)
    r = _run(llm=llm, on_stage=_record(events, threads))
    # 콜백은 run_premortem을 부른 스레드에서만(작업 스레드에서 부르지 않는다)
    assert set(threads) == {threading.get_ident()}
    # 결과 stages마다 끝 보고가 정확히 한 번, 상태·소요가 결과와 같다
    done = [(s, st, el) for s, st, el in events if st != "running"]
    assert sorted(done) == sorted((s.stage, s.state, s.elapsed_s) for s in r.stages)
    assert all(st in TERMINAL for _, st, _ in done)
    # 시작 보고는 실제로 돈 단계만, 한 번씩, 끝 보고보다 먼저, elapsed 0.0
    started = [s for s, st, _ in events if st == "running"]
    assert "fitness" not in started  # 건너뛴 단계는 끝 보고(skipped)만
    assert started == [s for s in [*PRE_V1, *V1] if s != "fitness"]  # 시작 보고 순서는 두 방식 모두 고정
    assert len(started) == len(set(started)) == len(r.stages) - 1
    for s in started:
        i_run = events.index((s, "running", 0.0))
        i_done = next(i for i, e in enumerate(events) if e[0] == s and e[1] != "running")
        assert i_run < i_done
    # 카드 합성까지는 순서가 그대로: 시작→끝이 단계마다 붙어 있다
    pre = [e for e in events if e[0] in PRE_V1]
    expect = []
    for s in PRE_V1:
        st = _st(r, s)
        expect += [(s, st.state, st.elapsed_s)] if st.state == "skipped" else [(s, "running", 0.0), (s, st.state, st.elapsed_s)]
    assert pre == expect
    assert events.index(pre[-1]) < min(events.index((t, "running", 0.0)) for t in V1)
    # 의존: 체크리스트 끝 보고 뒤에 2차 검증 시작 보고
    i_cl = next(i for i, e in enumerate(events) if e[0] == "checklist" and e[1] != "running")
    assert i_cl < events.index(("semantic_validate", "running", 0.0))
    if parallel:  # 독립 단계는 둘 다 시작한 뒤에 끝난다
        assert events.index(("checklist", "running", 0.0)) < next(
            i for i, e in enumerate(events) if e[0] == "expected_review" and e[1] != "running")


def test_on_stage_zero_cards_and_default_none_unchanged(no_fitness, monkeypatch):
    from neumann.analyze.backend import FixtureBackend
    from tests.e3.corpus import build

    works, _ = build()
    events: list = []
    r = _run(backend=FixtureBackend(works, []), on_stage=_record(events, []))
    assert r.risk_cards == [] and all(_st(r, t).state == "skipped" for t in V1)
    assert sorted(e for e in events if e[1] != "running") == sorted((s.stage, s.state, s.elapsed_s) for s in r.stages)
    # on_stage 없이(기존 호출자) 같은 결과
    assert _dump(_run()) == _dump(_run(on_stage=lambda *a: None))


def test_on_stage_callback_errors_do_not_break_analysis(no_fitness, caplog):
    calls = {"n": 0}

    def bad(stage: str, state: str, elapsed_s: float) -> None:
        calls["n"] += 1
        raise ValueError("C:\\secret\\path")

    base = _run()
    r = _run(on_stage=bad)
    assert calls["n"] >= len(r.stages) and _dump(r) == _dump(base)
    assert "secret" not in caplog.text


def test_on_stage_accepts_jobs_style_lambda(no_fitness):
    """E4-L2d jobs.py 모양: `lambda stage, *a, **k: _set_progress(pid, stage)`."""
    seen: list[str] = []
    r = _run(on_stage=lambda stage, *a, **k: seen.append(stage))
    assert seen[0] == "plan_normalize" and set(seen) == {s.stage for s in r.stages}


def test_on_stage_sees_request_context_in_v1(no_fitness, monkeypatch):
    """콜백은 부른 스레드에서 돌므로 문맥 변수(serving 요청 문맥)가 그대로 보인다."""
    import contextvars

    var: contextvars.ContextVar[str | None] = contextvars.ContextVar("req", default=None)
    var.set("ticket-1")
    seen = set()
    monkeypatch.setattr(pl, "V1_PARALLEL", True)
    _run(on_stage=lambda stage, state, el: seen.add(var.get()))
    assert seen == {"ticket-1"}


# ── 스레드 안전: 표기가 섞이지 않는다(PM 추가 요건) · 캐시 ────────────────────


@pytest.mark.parametrize("rep", range(6))
def test_labels_are_actual_values_per_stage_under_interleaving(no_fitness, monkeypatch, rep):
    monkeypatch.setattr(pl, "V1_PARALLEL", True)
    model = "gpt-6.1-sol"
    failing = V1[rep % len(V1)]
    llm = TaskModelAstra(default_responders(), model=model, delays={t: 0.01 for t in V1}, jitter=0.04,
                         fail={failing: "timeout"})
    r = _run(llm=llm)
    m = r.manifest
    assert m["llm_provider"] == "openai" and m["llm_model"] == model
    # 카드 합성 전 단계 impl은 provider:모델
    assert _st(r, "synthesize_cards").impl == f"openai:{model}"
    assert _st(r, "query_axes").impl == f"openai:{model}"
    # 단계별 실패 사유(last_error)는 그 단계에만: 다른 단계 detail에 섞이지 않는다
    for name in V1:
        detail = _st(r, name).detail or ""
        if name == failing:
            assert _st(r, name).state == "degraded"
            if name != "semantic_validate":  # 검증은 자기 사유(미검증 N장)를 쓴다
                assert "timeout" in detail
        else:
            assert _st(r, name).state == "ok" and "timeout" not in detail and "마지막 호출" not in detail
    # 예상 심사평: 실제 호출 결과의 모델(과제별로 다르게 돌려준 값)이 자기 과제 것
    er = r.expected_review
    if failing == "expected_review":
        assert er["generator"] == "rule" and er["model"] is None
    else:
        assert er["generator"] == "astra" and er["model"] == f"{model}@expected_review"
        assert _st(r, "expected_review").detail.startswith(f"astra:{model}@expected_review ")
    # 체크리스트·검증: 생성 주체 astra, 모델은 provider 값(호출 전 표기) — 다른 과제 모델명이 끼지 않는다
    for it in r.checklist:
        if failing == "checklist":
            assert it["generator"] == "rule" and it["model"] is None
        else:
            assert it["generator"] == "astra" and it["model"] == model
    sem = r.verification["semantic"]
    assert sem["generator"] == "astra" and sem["model"] == model
    # 과제별 모델명(@과제)은 그 과제 자리에만: 다른 단계 기록·체크리스트·검증 보고서에 끼지 않는다
    for name in V1:
        detail = _st(r, name).detail or ""
        assert all(f"@{t}" not in detail for t in V1 if t != name), (name, detail)
    assert "@" not in json.dumps([r.checklist, sem["cards"], sem["actions"]], ensure_ascii=False)
    assert all(f"@{t}" not in json.dumps(er, ensure_ascii=False) for t in V1 if t != "expected_review")


def test_v1_workers_never_write_caches(no_fitness, monkeypatch, tmp_path):
    """캐시(검색어·추출)는 v1 전에 다 쓰이고, v1 작업 스레드는 캐시를 쓰지 않는다(쓰기 경합 없음)."""
    monkeypatch.setattr(pl, "V1_PARALLEL", True)
    writes: list[tuple[str, float]] = []
    lock = threading.Lock()
    for mod in (queries_mod, extract_mod):
        orig = mod._cache_write

        def spy(*a: Any, _orig=orig, **kw: Any):
            with lock:
                writes.append((threading.current_thread().name, time.perf_counter()))
            return _orig(*a, **kw)

        monkeypatch.setattr(mod, "_cache_write", spy)
    v1_start: list[float] = []

    def cb(stage: str, state: str, el: float) -> None:
        if stage in V1 and state == "running" and not v1_start:
            v1_start.append(time.perf_counter())

    llm = SlowAstra(default_responders(), model="gpt-6.1-sol", delays={t: 0.05 for t in V1})
    r = _run(llm=llm, cache_dir=tmp_path, on_stage=cb)
    assert r.plan_checks["queries"]["cache"]["stored"] and writes
    assert all(not name.startswith("neumann-v1") for name, _ in writes)
    assert max(t for _, t in writes) < v1_start[0]
    for f in tmp_path.rglob("*.json"):
        json.loads(f.read_text(encoding="utf-8"))
    assert not list(tmp_path.rglob("*.tmp"))
    # 캐시 적중으로 다시 돌려도 같은 결과(병렬 경로)
    again = _run(llm=SlowAstra(default_responders(), model="gpt-6.1-sol"), cache_dir=tmp_path)
    assert [c.card_id for c in again.risk_cards] == [c.card_id for c in r.risk_cards]
    assert again.checklist == r.checklist


def test_concurrent_analyses_do_not_share_state(no_fitness, monkeypatch):
    """두 분석을 동시에(서버 동시 상한 2 상황) 돌려도 각자 순차 결과와 같다."""
    monkeypatch.setattr(pl, "V1_PARALLEL", False)
    expect = {p: _dump(_run(p)) for p in (PLAN_BATTERY, PLAN_IMAGING)}
    monkeypatch.setattr(pl, "V1_PARALLEL", True)
    got: dict[str, Any] = {}

    def work(p: str) -> None:
        got[p] = _dump(_run(p, llm=SlowMock(default_responders(), delays={t: 0.03 for t in V1}, jitter=0.03)))

    ths = [threading.Thread(target=work, args=(p,)) for p in (PLAN_BATTERY, PLAN_IMAGING)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    assert got == expect
