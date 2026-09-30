"""E4-L2e 부하 시험 도구의 가벼운 단위 시험(GPU·서버·실색인 없이, fixture backend·짧은 지연).

실제 측정은 `scripts/loadtest_multiuser.py`로 한다(보고서 docs/reports/E4-L2e.md).
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

import scripts.loadtest_multiuser as lt
from neumann.analyze import rules
from neumann.analyze.backend import FixtureBackend
from neumann.llm import LLMCall, OpenAIProvider
from neumann.models import PlanDocument
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


def test_delayed_mock_real_sleep_overlaps_across_threads():
    """지연은 time.sleep이라 GIL을 놓는다: 4개 동시 호출이 0.2초씩이면 전체는 0.8초보다 훨씬 짧다."""
    llm = lt.DelayedMockProvider({"query_axes": (0.2, 0.2)})
    ths = [threading.Thread(target=llm.complete_json, args=(_call(),)) for _ in range(4)]
    t0 = time.perf_counter()
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    assert time.perf_counter() - t0 < 0.6
    assert llm.stats.totals()["max_inflight"] >= 2


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


def test_timed_lock_measures_wait_and_hold_per_thread():
    lock = lib.TimedLock()
    got: dict[str, dict[str, float]] = {}
    held = threading.Event()

    def holder() -> None:
        with lock:
            held.set()
            time.sleep(0.15)
        got["holder"] = lock.thread_totals()

    def waiter() -> None:
        held.wait()
        with lock:
            pass
        got["waiter"] = lock.thread_totals()

    ths = [threading.Thread(target=holder), threading.Thread(target=waiter)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    assert got["holder"]["hold"] >= 0.12 and got["holder"]["wait"] < 0.05
    assert got["waiter"]["wait"] >= 0.08 and got["waiter"]["n"] == 1
    snap = lock.snapshot()
    assert snap["calls"] == 2 and snap["wait_max_s"] >= 0.08 and snap["max_waiting"] >= 1


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


def test_direct_round_runs_concurrently_and_matches_sequential_reference():
    """fixture backend로 동시 3명: 모두 성공, 지문이 순차 기준과 같고, 실행이 겹친다(전체 < 건별 합)."""
    fx = load_fixtures()
    backend = FixtureBackend(fx.works, fx.reviews)
    delays = {k: (0.05, 0.05) for k in lib.DEFAULT_DELAYS}
    texts = lt.round_texts(lt.plan_bases(), 3, "시험")
    probe = lt.EmbedProbe(None)
    sampler = lt.ProcSampler(interval=0.05).start()
    try:
        ref = lt.reference_pass([t for _, t in texts], delays, probe, backend)
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
    # 과제(단계)끼리는 대체로 차례로 돈다(한 과제 안의 묶음만 병렬). 예외(E3-L1y): 예상 심사평은
    # 체크리스트→2차 검증과 동시에 돌므로, 둘 다 불렸으면 임계 경로에서 과제 하나를 뺀다
    def _serial_tasks(by_task: dict) -> int:
        n = len(by_task)
        return n - 1 if "expected_review" in by_task and "checklist" in by_task else n

    assert all(r["run_s"] >= 0.045 * _serial_tasks(r["llm"]["by_task"]) for r in rnd["records"])
    assert rnd["makespan_s"] < 0.8 * sum(runs)
    assert row["llm_calls_per_analysis"]["min"] >= 2 and row["proc"]["rss_max_mb"] > 0
    md = lt.table([row], "시험")
    assert md.count("\n| 3 |") == 1 and "| 3/3 |" in md
