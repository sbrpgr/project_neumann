"""SEC-5 B: 프로세스 전체 동시 OpenAI 호출 상한(InflightLimiter).

실제 호출 없음: 가짜 클라이언트(create()가 sleep하며 동시 진입 수를 센다)를 OpenAIProvider에 주입한다.
- 스레드·provider가 많아도 동시에 네트워크에 나가는 수는 상한을 넘지 않는다(그리고 상한까지는 실제로 병렬).
- 자리 대기가 호출 시간 상한을 넘으면 네트워크에 나가지 않고 timeout 실패 결과로 돌아온다(매달리지 않는다).
- 성공·실패·재시도 어느 경로든 자리를 돌려준다(교착 없음). 재시도 전 쉬는 동안은 자리를 비운다.
- mock·off provider는 상한을 거치지 않는다. SEC-3 잠금(config_error)은 자리를 잡기 전에 돌아간다.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from neumann import llm as llm_mod
from neumann.llm import (
    DEFAULT_MAX_INFLIGHT,
    DisabledProvider,
    InflightLimiter,
    LLMCall,
    MockProvider,
    OpenAIProvider,
    inflight_limiter,
    max_inflight,
    reset_inflight_limiter,
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"n": {"type": "integer"}, "tag": {"type": "string", "enum": ["a", "b"]}},
    "required": ["n", "tag"],
}
MODEL = "gpt-6.1-sol"
OK_TEXT = '{"n": 1, "tag": "a"}'


@pytest.fixture(autouse=True)
def _fresh_global_limiter(monkeypatch):
    monkeypatch.delenv("NEUMANN_LLM_MAX_INFLIGHT", raising=False)
    reset_inflight_limiter(None)
    yield
    reset_inflight_limiter(None)


def _call(timeout_s: float = 30.0, task: str = "t") -> LLMCall:
    return LLMCall(task=task, instructions="x", payload={"q": 1}, schema=SCHEMA, schema_name="s", timeout_s=timeout_s)


def _resp(text: str = OK_TEXT, status: str = "completed") -> Any:
    return SimpleNamespace(
        output_text=text, status=status, incomplete_details=None,
        usage=SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2, output_tokens_details=None),
    )


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/responses")


class _Tracker:
    """여러 가짜 클라이언트가 같이 쓰는 동시 진입 계수기."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0
        self.calls = 0

    def enter(self) -> None:
        with self.lock:
            self.current += 1
            self.calls += 1
            self.peak = max(self.peak, self.current)

    def leave(self) -> None:
        with self.lock:
            self.current -= 1


class _SleepyClient:
    """OpenAI 클라이언트 흉내: responses.create()가 sleep_s 동안 머물고 behaviour를 돌려준다(예외면 던진다)."""

    def __init__(self, tracker: _Tracker, sleep_s: float = 0.05, behaviour: Any = None, gate: threading.Event | None = None):
        self.tracker = tracker
        self.sleep_s = sleep_s
        self.behaviour = behaviour
        self.gate = gate
        self.entered = threading.Event()
        self.responses = self

    def with_options(self, timeout: float) -> _SleepyClient:
        return self

    def create(self, **kwargs: Any) -> Any:
        self.tracker.enter()
        self.entered.set()
        try:
            if self.gate is not None:
                assert self.gate.wait(20), "gate가 열리지 않았다"
            time.sleep(self.sleep_s)
            b = self.behaviour.pop(0) if isinstance(self.behaviour, list) else self.behaviour
            if isinstance(b, BaseException):
                raise b
            return b if b is not None else _resp()
        finally:
            self.tracker.leave()


def _run_all(fns: list[Any], timeout: float = 30.0) -> list[Any]:
    """fns를 각자 스레드에서 한꺼번에 출발시켜(Barrier) 결과를 모은다. 제한 시간 안에 안 끝나면 교착으로 실패."""
    start = threading.Barrier(len(fns), timeout=10)
    out: list[Any] = [None] * len(fns)
    errors: list[BaseException] = []

    def wrap(i, fn):
        def run():
            try:
                start.wait()
                out[i] = fn()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        return run

    threads = [threading.Thread(target=wrap(i, f), name=f"sec5-llm-{i}") for i, f in enumerate(fns)]
    for t in threads:
        t.start()
    deadline = time.perf_counter() + timeout
    for t in threads:
        t.join(max(0.0, deadline - time.perf_counter()))
    assert not any(t.is_alive() for t in threads), "제한 시간 안에 끝나지 않은 스레드가 있다(교착)"
    if errors:
        raise errors[0]
    return out


# ── 상한 ────────────────────────────────────────────────────────────────


def test_default_is_32_and_setting_is_read(monkeypatch):
    assert DEFAULT_MAX_INFLIGHT == 32
    assert max_inflight() == 32
    monkeypatch.setenv("NEUMANN_LLM_MAX_INFLIGHT", "5")
    assert max_inflight() == 5
    assert max_inflight(SimpleNamespace(llm_max_inflight=7)) == 7  # 설정 객체 속성이 환경변수보다 먼저
    for bad in ("0", "-3", "abc", "2.5"):
        monkeypatch.setenv("NEUMANN_LLM_MAX_INFLIGHT", bad)
        assert max_inflight() == DEFAULT_MAX_INFLIGHT
    with pytest.raises(ValueError):
        InflightLimiter(0)


def test_cap_holds_across_many_threads_and_providers():
    """요청마다 provider가 따로여도(동시 요청 흉내) 상한 하나를 같이 쓴다: 동시 네트워크 호출 ≤ 3, 그리고 = 3까지 병렬."""
    limiter = InflightLimiter(3)
    tracker = _Tracker()
    n = 24
    providers = [
        OpenAIProvider(api_key=None, model=MODEL, client=_SleepyClient(tracker, 0.05), limiter=limiter) for _ in range(n)
    ]
    t0 = time.perf_counter()
    results = _run_all([lambda p=p: p.complete_json(_call()) for p in providers])
    wall = time.perf_counter() - t0
    assert all(r.ok for r in results), [r.reason() for r in results if not r.ok]
    assert tracker.calls == n
    assert tracker.peak == 3  # 넘지 않고, 상한까지는 실제로 동시에 나간다
    snap = limiter.snapshot()
    assert snap == {"limit": 3, "in_flight": 0, "peak": 3, "acquired": n, "waited": snap["waited"], "wait_timeouts": 0}
    assert snap["waited"] >= n - 3  # 나머지는 자리를 기다렸다
    assert wall >= (n / 3) * 0.05 * 0.8  # 직렬 8회분(24/3) 이상 걸렸다 = 3개씩 묶였다


def test_process_wide_limiter_from_setting(monkeypatch):
    """limiter를 주입하지 않은 provider는 프로세스 공용 상한(NEUMANN_LLM_MAX_INFLIGHT)을 쓴다."""
    monkeypatch.setenv("NEUMANN_LLM_MAX_INFLIGHT", "2")
    reset_inflight_limiter(None)
    tracker = _Tracker()
    providers = [OpenAIProvider(api_key=None, model=MODEL, client=_SleepyClient(tracker, 0.04)) for _ in range(10)]
    results = _run_all([lambda p=p: p.complete_json(_call()) for p in providers])
    assert all(r.ok for r in results)
    assert tracker.peak == 2 and tracker.calls == 10
    glob = inflight_limiter()
    assert glob.limit == 2 and glob.snapshot()["peak"] == 2 and glob.snapshot()["in_flight"] == 0
    assert inflight_limiter() is glob  # 한 프로세스에 하나


def test_wait_timeout_returns_failure_without_network():
    """상한이 찼고 호출 시간 상한 안에 자리가 안 나면 timeout 실패(대기 초과) — 매달리지 않고 네트워크에도 안 나간다."""
    limiter = InflightLimiter(1)
    tracker = _Tracker()
    gate = threading.Event()
    holder_client = _SleepyClient(tracker, 0.0, gate=gate)
    holder = OpenAIProvider(api_key=None, model=MODEL, client=holder_client, limiter=limiter)
    box: dict[str, Any] = {}
    th = threading.Thread(target=lambda: box.setdefault("res", holder.complete_json(_call(timeout_s=30))))
    th.start()
    try:
        assert holder_client.entered.wait(10)  # 자리 하나를 잡고 네트워크 안에 머무는 중

        waiter_client = _SleepyClient(tracker, 0.0)
        waiter = OpenAIProvider(api_key=None, model=MODEL, client=waiter_client, limiter=limiter)
        t0 = time.perf_counter()
        res = waiter.complete_json(_call(timeout_s=0.3, task="extract_issues"))
        took = time.perf_counter() - t0
    finally:
        gate.set()
        th.join(10)
    assert not th.is_alive()
    assert not res.ok and res.error == "timeout" and res.task == "extract_issues"
    assert "동시 호출 상한 1개" in res.detail and "대기 초과" in res.detail and "0.3s" in res.detail
    assert "시간 초과" in res.reason()
    assert not waiter_client.entered.is_set() and tracker.calls == 1  # 기다린 쪽은 네트워크에 나가지 않았다
    assert 0.25 <= took < 5.0 and res.latency_s >= 0.25
    assert box["res"].ok  # 자리를 잡고 있던 호출은 정상 완료
    snap = limiter.snapshot()
    assert snap["wait_timeouts"] == 1 and snap["in_flight"] == 0 and snap["acquired"] == 1
    assert limiter.acquire(0)  # 자리가 돌아왔다
    limiter.release()


def test_slot_released_on_every_outcome():
    """상한 1: 성공·시간 초과·HTTP 오류·기타 예외·스키마 위반·미완료 뒤에도 다음 호출이 곧바로 자리를 얻는다(누수 없음)."""
    limiter = InflightLimiter(1)
    tracker = _Tracker()
    outcomes = [
        (_resp(), None),
        (openai.APITimeoutError(request=_req()), "timeout"),
        (openai.BadRequestError("bad", response=httpx.Response(400, request=_req()), body=None), "api_error"),
        (RuntimeError("boom"), "api_error"),
        (_resp('{"n": "x", "tag": "a"}'), "schema_invalid"),
        (_resp("", status="incomplete"), "incomplete"),
        (_resp(), None),
    ]
    for behaviour, want in outcomes:
        p = OpenAIProvider(api_key=None, model=MODEL, client=_SleepyClient(tracker, 0.0, behaviour), limiter=limiter)
        res = p.complete_json(_call(timeout_s=0.5))
        assert res.error == want, res.reason()
        assert "대기 초과" not in (res.detail or "")
        assert limiter.snapshot()["in_flight"] == 0
    snap = limiter.snapshot()
    assert snap["acquired"] == len(outcomes) and snap["wait_timeouts"] == 0 and snap["waited"] == 0


def test_retry_backoff_does_not_hold_slot(monkeypatch):
    """일시 오류 뒤 재시도: 쉬는 동안 자리를 비우고, 재시도할 때 다시 얻는다."""
    limiter = InflightLimiter(1)
    seen_during_sleep: list[int] = []

    def fake_sleep(s: float) -> None:
        seen_during_sleep.append(limiter.snapshot()["in_flight"])

    monkeypatch.setattr(llm_mod, "time", SimpleNamespace(perf_counter=time.perf_counter, sleep=fake_sleep))
    transient = openai.InternalServerError("x", response=httpx.Response(500, request=_req()), body=None)
    p = OpenAIProvider(
        api_key=None, model=MODEL, client=_SleepyClient(_Tracker(), 0.0, [transient, _resp()]), limiter=limiter
    )
    res = p.complete_json(_call(timeout_s=60))
    assert res.ok and res.attempts == 2
    assert seen_during_sleep == [0]  # 쉬는 동안 자리 0개 사용
    assert limiter.snapshot()["acquired"] == 2 and limiter.snapshot()["in_flight"] == 0


def test_no_deadlock_under_mixed_load():
    """상한 4, 스레드 40: 느린 호출·빠른 실패·짧은 상한(대기 초과)이 섞여도 모두 끝나고 자리가 전부 돌아온다."""
    limiter = InflightLimiter(4)
    tracker = _Tracker()
    fns = []
    for i in range(40):
        if i % 5 == 0:
            behaviour, sleep_s, timeout_s = RuntimeError("x"), 0.0, 30.0
        elif i % 7 == 0:
            behaviour, sleep_s, timeout_s = None, 0.02, 0.05  # 짧은 상한: 자리를 못 얻으면 대기 초과
        else:
            behaviour, sleep_s, timeout_s = None, 0.03, 30.0
        p = OpenAIProvider(api_key=None, model=MODEL, client=_SleepyClient(tracker, sleep_s, behaviour), limiter=limiter)
        fns.append(lambda p=p, t=timeout_s: p.complete_json(_call(timeout_s=t)))
    results = _run_all(fns)
    assert tracker.peak <= 4
    wait_fail = [r for r in results if not r.ok and "대기 초과" in (r.detail or "")]
    snap = limiter.snapshot()
    assert snap["in_flight"] == 0 and snap["peak"] <= 4
    assert snap["wait_timeouts"] == len(wait_fail)
    assert snap["acquired"] + snap["wait_timeouts"] == 40 == tracker.calls + len(wait_fail)
    assert all(r.error == "timeout" for r in wait_fail)
    assert limiter.acquire(0)
    limiter.release()


def test_over_release_is_loud():
    limiter = InflightLimiter(2)
    with pytest.raises(ValueError):
        limiter.release()  # BoundedSemaphore: 얻지 않은 자리 반환은 숨기지 않는다
    assert limiter.snapshot()["in_flight"] == 0


# ── 걸지 않는 곳 · SEC-3 ─────────────────────────────────────────────────


def test_mock_and_off_providers_bypass_limiter():
    glob = reset_inflight_limiter(1)
    assert glob is not None and glob.acquire(0)  # 공용 상한의 유일한 자리를 잡아 둔다
    try:
        mock = MockProvider({"t": lambda c: {"n": 1, "tag": "a"}})
        t0 = time.perf_counter()
        results = _run_all([lambda: mock.complete_json(_call(timeout_s=0.2)) for _ in range(8)])
        assert all(r.ok for r in results) and time.perf_counter() - t0 < 5.0
        off = DisabledProvider().complete_json(_call(timeout_s=0.2))
        assert off.error == "disabled"
        assert glob.snapshot()["acquired"] == 1 and glob.snapshot()["wait_timeouts"] == 0
    finally:
        glob.release()


def test_live_lock_config_error_returns_before_limiter(monkeypatch):
    """SEC-3 잠금 그대로: 허용 플래그 없는 실제 provider는 자리를 잡지 않고 config_error로 돌아간다."""
    monkeypatch.setenv("NEUMANN_LIVE_LLM_OK", "0")
    limiter = InflightLimiter(1)
    p = OpenAIProvider(api_key="fake-test-key", model=MODEL, limiter=limiter)  # 실제 키 아님, 클라이언트 안 만듦
    res = p.complete_json(_call())
    assert not res.ok and res.error == "config_error" and "NEUMANN_LIVE_LLM_OK" in res.detail
    assert p._client is None
    assert limiter.snapshot()["acquired"] == 0 and limiter.snapshot()["wait_timeouts"] == 0
