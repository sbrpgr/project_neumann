"""E4-L2e 부하 시험 도구의 가벼운 단위 시험(GPU·서버·실색인 없이, fixture backend·짧은 지연).

실제 측정은 `scripts/loadtest_multiuser.py`로 한다(보고서 docs/reports/E4-L2e.md).
"""

from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace

import pytest

import scripts.loadtest_multiuser as lt
from neumann.analyze import rules
from neumann.analyze.backend import FixtureBackend
from neumann.llm import LLMCall, OpenAIProvider
from neumann.models import PlanDocument
from tests._util.timing import assert_faster
from tests.fixtures.loader import load_fixtures

lib = sys.modules["loadtest_multiuser_lib"]  # 실행기가 쓰는 것과 같은 모듈 객체

SCHEMA = {"type": "object", "properties": {"queries": {"type": "array"}}, "required": ["queries"]}


def _call(task: str = "query_axes", timeout_s: float | None = 45.0) -> LLMCall:
    plan = ["1: Graph Neural Network surrogate model", "2: We randomly split the dataset into train and test sets."]
    return LLMCall(task=task, instructions="x" * 10, payload={"lines": plan}, schema={"type": "object"},
                   schema_name="t", timeout_s=timeout_s)


def test_parse_delays_overrides_and_rejects_bad_input():
    d = lt.parse_delays(["query_axes=1", "extract_issues=0.5:2", "new_task=3"])
    assert d["query_axes"] == (1.0, 1.0)
    assert d["extract_issues"] == (0.5, 2.0)
    assert d["new_task"] == (3.0, 3.0)
    assert d["synthesize_cards"] == lib.DEFAULT_DELAYS["synthesize_cards"]
    for bad in ("query_axes", "=1", "query_axes=3:1", "query_axes=-1"):
        with pytest.raises(ValueError):
            lt.parse_delays([bad])


def test_default_delays_sum_close_to_live_minute():
    """기본 지연 합(추출 2파·2차 검증 1~2회)이 라이브 1건(E5-L0e2e 61~69초)과 같은 규모인지."""
    mid = {k: (lo + hi) / 2 for k, (lo, hi) in lib.DEFAULT_DELAYS.items()}
    total = sum(v for k, v in mid.items() if k != "extract_issues") + 2 * mid["extract_issues"]
    assert 50 <= total <= 70


def test_delayed_mock_sleeps_per_task_and_stays_mock():
    slept: list[float] = []
    stats = lt.CallStats()
    llm = lt.DelayedMockProvider({"query_axes": (2.0, 2.0)}, scale=0.5, seed=1, stats=stats, sleep=slept.append)
    res = llm.complete_json(_call())
    assert res.ok and res.generator == "mock" and res.provider == "mock"
    assert slept == [1.0]  # 2초 × 배율 0.5
    assert res.latency_s == 1.0
    tot = stats.totals()
    assert tot["calls"] == 1 and tot["by_task"]["query_axes"]["calls"] == 1 and tot["chars"] > 10
    assert tot["max_inflight"] == 1


def test_delayed_mock_times_out_like_a_real_provider():
    slept: list[float] = []
    llm = lt.DelayedMockProvider({"query_axes": (10.0, 10.0)}, sleep=slept.append)
    res = llm.complete_json(_call(timeout_s=3.0))
    assert not res.ok and res.error == "timeout"
    assert slept == [3.0]
    assert llm.stats.totals()["failed"] == 1


def _timed_calls(llm: lt.DelayedMockProvider, n: int, *, threaded: bool) -> float:
    """같은 호출 n개를 (threaded) 스레드 n개로 동시에 / (아니면) 한 스레드에서 차례로 하고 걸린 초를 돌려준다.

    스레드는 미리 띄워 배리어에서 세워 두었다가 한꺼번에 푼다: 스레드 기동 지연(과부하에서 초 단위로 튄다)이
    잰 시간에 들어가지 않는다.
    """
    if not threaded:
        t0 = time.perf_counter()
        for _ in range(n):
            assert llm.complete_json(_call()).ok
        return time.perf_counter() - t0
    go = threading.Barrier(n + 1, timeout=30)
    release = threading.Event()
    results, errors = [], []

    def work() -> None:
        try:
            go.wait()
            assert release.wait(30)
            results.append(llm.complete_json(_call()))
        except BaseException as exc:
            errors.append(exc)

    ths = [threading.Thread(target=work) for _ in range(n)]
    for t in ths:
        t.start()
    try:
        go.wait()
        t0 = time.perf_counter()
        release.set()  # 시계를 시작한 뒤에 호출을 푼다(스케줄링 지연으로 측정 시작이 늦어지지 않는다).
    finally:
        release.set()
        deadline = time.monotonic() + 30
        for t in ths:
            t.join(max(0.0, deadline - time.monotonic()))
    elapsed = time.perf_counter() - t0
    assert not any(t.is_alive() for t in ths), "지연 호출이 종료되지 않았다"
    assert errors == [] and len(results) == n and all(r.ok for r in results)
    return elapsed


def test_delayed_mock_real_sleep_overlaps_across_threads():
    """지연은 time.sleep이라 GIL을 놓는다: 4개 동시 호출은 같은 4개를 차례로 부른 것보다 확연히 빠르다.

    벽시계 절대값(<0.6초)은 과부하에서 흔들려서, 같은 조건에서 잰 동시/차례 시간의 비율(<0.8, 반복 최솟값)로 판정한다.
    이상적인 비율은 0.25다. 지연이 락 안에서 돌거나 GIL을 잡는 바쁜 대기면 비율이 1 근처라 실패한다.
    """
    llm = lt.DelayedMockProvider({"query_axes": (0.2, 0.2)})
    assert_faster(lambda: _timed_calls(llm, 4, threaded=True), lambda: _timed_calls(llm, 4, threaded=False),
                  max_ratio=0.8, what="지연 mock 4개 동시 vs 차례")
    assert llm.stats.totals()["max_inflight"] >= 2


def test_delayed_mock_delays_are_in_flight_together():
    """시간과 무관한 겹침 증명: 지연 자리에 4자 배리어를 넣는다. 4개 호출이 지연 안에 동시에 있어야만 풀린다.

    지연 구간이 직렬화되면(락 안에서 잔다 등) 배리어가 풀리지 않아 시간 초과로 실패한다.
    """
    rendezvous = threading.Barrier(4, timeout=20)
    llm = lt.DelayedMockProvider({"query_axes": (0.2, 0.2)}, sleep=lambda _s: rendezvous.wait())
    errors: list[BaseException] = []
    results: list[object] = []

    def work() -> None:
        try:
            results.append(llm.complete_json(_call()))
        except BaseException as exc:  # noqa: BLE001 — BrokenBarrierError를 모은다
            errors.append(exc)

    ths = [threading.Thread(target=work) for _ in range(4)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    assert errors == [], "지연 구간에 4개 호출이 동시에 있지 못했다(직렬화)"
    assert len(results) == 4 and llm.stats.totals()["max_inflight"] == 4


def test_block_openai_refuses_real_calls(monkeypatch):
    monkeypatch.setattr(OpenAIProvider, "complete_json", OpenAIProvider.complete_json)  # 끝나면 되돌린다
    lt.block_openai()
    prov = OpenAIProvider(api_key=None, model="m", client=object())
    with pytest.raises(RuntimeError, match="mock"):
        prov.complete_json(_call())


def test_require_mock_env(monkeypatch):
    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")
    with pytest.raises(SystemExit):
        lt.require_mock_env()
    monkeypatch.delenv("NEUMANN_LLM_PROVIDER")
    with pytest.raises(SystemExit):
        lt.require_mock_env()
    monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "mock")
    lt.require_mock_env()


class _FakeClock:
    """손으로 돌리는 시계. perf_counter 자리에 넣으면 잠자기·스케줄링 지연 없이 대기·점유 시간이 정확히 잰다."""

    def __init__(self) -> None:
        self._t = 0.0
        self._mu = threading.Lock()
        self.readers: set[int] = set()  # 시계를 읽어 본 스레드

    def now(self) -> float:
        with self._mu:
            t = self._t
            self.readers.add(threading.get_ident())
            return t

    def advance(self, dt: float) -> None:
        with self._mu:
            self._t += dt


def test_timed_lock_measures_wait_and_hold_per_thread(monkeypatch):
    """계측 락이 스레드별 대기·점유 시간을 잰다. 가짜 시계로 잰다(진짜 sleep·시각 비교는 과부하에서 흔들린다)."""
    clock = _FakeClock()
    monkeypatch.setattr(lib, "time", SimpleNamespace(perf_counter=clock.now))  # TimedLock이 읽는 시계만 바꾼다
    lock = lib.TimedLock()
    got: dict[str, dict[str, float]] = {}
    ident: dict[str, int] = {}
    held, release = threading.Event(), threading.Event()

    def holder() -> None:
        ident["holder"] = threading.get_ident()
        with lock:
            held.set()
            assert release.wait(10)
        got["holder"] = lock.thread_totals()

    def waiter() -> None:
        ident["waiter"] = threading.get_ident()
        assert held.wait(10)
        with lock:
            pass
        got["waiter"] = lock.thread_totals()

    ths = [threading.Thread(target=holder), threading.Thread(target=waiter)]
    for t in ths:
        t.start()
    # 기다리는 쪽이 대기 시작 시각(t0)을 읽은 뒤에 시계를 0.15초 돌리고 점유자를 놓는다(스케줄링 순서와 무관하게 같은 결과)
    try:
        deadline = time.monotonic() + 10
        while ident.get("waiter") not in clock.readers:
            assert time.monotonic() < deadline, "기다리는 스레드가 락을 요청하지 않았다"
            time.sleep(0.005)
        clock.advance(0.15)
    finally:
        release.set()
        deadline = time.monotonic() + 20
        for t in ths:
            t.join(max(0.0, deadline - time.monotonic()))
    assert not any(t.is_alive() for t in ths), "계측 락 시험 스레드가 남아 있다"
    assert got["holder"] == {"n": 1, "wait": 0.0, "hold": pytest.approx(0.15)}
    assert got["waiter"] == {"n": 1, "wait": pytest.approx(0.15), "hold": 0.0}
    snap = lock.snapshot()
    assert snap["calls"] == 2 and snap["wait_max_s"] == pytest.approx(0.15) and snap["max_waiting"] >= 1
    assert snap["wait_total_s"] == pytest.approx(0.15) and snap["hold_total_s"] == pytest.approx(0.15)


def test_embed_probe_swaps_lock_on_embedder():
    class FakeEmb:
        def __init__(self) -> None:
            self._lock = threading.Lock()

        def encode(self, texts):
            with self._lock:
                return len(texts)

    emb = FakeEmb()
    probe = lt.EmbedProbe(emb)
    assert isinstance(emb._lock, lib.TimedLock)
    emb.encode(["a"])
    assert probe.snapshot()["calls"] == 1 and probe.thread_totals()["n"] == 1
    assert lt.EmbedProbe(None).snapshot()["calls"] == 0


def test_variants_are_unique_and_do_not_change_english_queries():
    bases = lt.plan_bases()
    names = [b for b, _ in bases]
    assert names[:3] == ["plan", "plan_elife_neuro", "plan_medimaging"] and len(bases) == 10
    texts = lt.round_texts(bases, 12, "12")
    assert len({t for _, t in texts}) == 12
    for k, (name, text) in enumerate(texts):
        base = dict(bases)[name]
        assert text.startswith(base.rstrip("\n")) and f"사용자 {k + 1}번" in text
        q_base = rules.fallback_queries(PlanDocument.from_text(base, "s"))
        q_var = rules.fallback_queries(PlanDocument.from_text(text, "s"))
        assert q_base == q_var  # 변형 줄은 검색어를 바꾸지 않는다(같은 유사 연구 → 기반끼리 비교 가능)
    assert lt.text_key(texts[0][1]) != lt.text_key(texts[1][1])


def _result(evidence: list[str], n_hits: int = 2, top: float = 0.9) -> dict:
    return {
        "similar_works": [{"work_id": "w1", "similarity": 0.9}, {"work_id": "w2", "similarity": 0.8}],
        "risk_cards": [{"risk_code": "R2", "evidence": evidence}],
        "checklist": [{"item_id": "a"}],
        "stages": [{"stage": "search", "state": "ok"}],
        "plan_checks": {"search": {"scores": [0.9, 0.8], "backend_status": {"n_hits": n_hits, "top_score": top}}},
    }


def test_fingerprint_detects_changes_and_search_status_mixup():
    a = lt.fingerprint(_result(["e1", "e2"]))
    assert a == lt.fingerprint(_result(["e1", "e2"]))
    assert a["digest"] != lt.fingerprint(_result(["e1", "e3"]))["digest"]
    assert a["status_mixup"] is False
    assert lt.fingerprint(_result(["e1"], n_hits=7))["status_mixup"] is True  # 남의 검색 상태
    assert lt.fingerprint(_result(["e1"], top=0.51))["status_mixup"] is True
    assert lt.stage_states({"stages": [{"state": "ok"}, {"state": "degraded"}, {"state": "ok"}]}) == {"ok": 2, "degraded": 1}


def test_stats_percentiles():
    s = lt.stats([5, 1, 3, 2, 4])
    assert s["min"] == 1 and s["max"] == 5 and s["p50"] == 3 and s["mean"] == 3
    assert lt.stats([]) == {"n": 0}


def test_direct_round_runs_concurrently_and_matches_sequential_reference(monkeypatch):
    """fixture backend로 동시 3명: 순차 기준과 같은 결과, 사용자 3명의 검색어 호출이 함께 진입."""
    fx = load_fixtures()
    backend = FixtureBackend(fx.works, fx.reviews)
    delays = {k: (0.05, 0.05) for k in lib.DEFAULT_DELAYS}
    texts = lt.round_texts(lt.plan_bases(), 3, "시험")
    probe = lt.EmbedProbe(None)
    sampler = lt.ProcSampler(interval=0.05).start()
    rendezvous = threading.Barrier(3, timeout=20)
    entered: set[int] = set()
    errors: list[BaseException] = []
    original = lt.DelayedMockProvider

    class ConcurrentMock(original):
        def complete_json(self, call):
            if call.task == "query_axes":
                entered.add(threading.get_ident())
                try:
                    rendezvous.wait()
                except threading.BrokenBarrierError as exc:
                    errors.append(exc)
            return super().complete_json(call)

    try:
        ref = lt.reference_pass([t for _, t in texts], delays, probe, backend)
        monkeypatch.setattr(lt, "DelayedMockProvider", ConcurrentMock)
        rnd = lt.run_round_direct(texts, delays, 1.0, probe, sampler, backend)
    finally:
        sampler.stop()
    row = lt.summarize_round(rnd, ref, None)
    assert row["n"] == 3 and row["ok"] == 3 and row["errors"] == 0
    assert row["no_reference"] == 0 and row["fingerprint_mismatch"] == 0
    runs = [r["run_s"] for r in rnd["records"]]
    # 지연이 실제로 들어갔다: 적어도 적합성·검색어 두 호출(각 0.05초). fixture 코퍼스가 작아 유사 연구가 없으면
    # 그 뒤 단계는 건너뛴다(그래서 건마다 호출 수가 다르다)
    assert min(runs) >= 0.09
    # 이름 수는 임계 경로가 아니다: 지연표에 없는 호출은 지연 0이며, v1은
    # expected_review ∥ (checklist → semantic_validate)다. 묶음 내부 병렬은
    # 해당 단계의 호출 한 번분만 하한에 넣는다(추가 파가 있으면 더 길어진다).
    def critical_delay(by_task: dict) -> float:
        one_call = {task: row["delay_s"] / row["calls"] for task, row in by_task.items()}
        review = one_call.pop("expected_review", 0.0)
        chain = one_call.pop("checklist", 0.0) + one_call.pop("semantic_validate", 0.0)
        return sum(one_call.values()) + max(review, chain)

    for rec in rnd["records"]:
        # run_s 통계는 소수 셋째 자리로 반올림하므로 양자화 오차만 허용한다.
        assert rec["run_s"] + 0.0005 >= critical_delay(rec["llm"]["by_task"]), rec
    assert errors == [] and len(entered) == 3, "사용자 3명의 검색어 호출이 함께 진입하지 못했다"
    assert row["llm_calls_per_analysis"]["min"] >= 2 and row["proc"]["rss_max_mb"] > 0
    md = lt.table([row], "시험")
    assert md.count("\n| 3 |") == 1 and "| 3/3 |" in md
