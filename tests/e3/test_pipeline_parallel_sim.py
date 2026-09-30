"""E3-L1y 측정: mock provider에 호출별 지연을 넣은 시뮬레이션(실제 API 없음)으로 순차·병렬 전체 시간을 비교한다.

지연(과제 지시, 초): 검색어 3 · 지적 추출 묶음 3(묶음끼리 병렬) · 카드 합성 12 · 예상 심사평 12 · 체크리스트 12(호출마다,
카드 3장 묶음끼리 병렬) · 2차 검증 12(호출마다, 묶음끼리 병렬). 적합성은 지시에 없어 0.

테스트는 지연을 1/50로 줄여 돈다. 보고서 표는 실제 크기로 한 번 돌린 값이다:

    NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." python -m tests.e3.test_pipeline_parallel_sim [배율=1.0]
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

import neumann.pipeline as pl
from neumann.analyze.mock_responders import default_responders
from neumann.llm import LLMCall, LLMResult, MockProvider
from tests._util.timing import assert_faster
from tests.e3.corpus import PLAN_BATTERY, build_backend

DELAYS_S: dict[str, float] = {
    "fitness": 0.0,
    "query_axes": 3.0,
    "extract_issues": 3.0,
    "synthesize_cards": 12.0,
    "expected_review": 12.0,
    "checklist": 12.0,
    "semantic_validate": 12.0,
}
V1 = [name for name, _ in pl.V1_STAGES]


class DelayedMock(MockProvider):
    """호출마다 과제별 지연을 넣는 mock. 호출 수를 과제별로 센다."""

    def __init__(self, scale: float) -> None:
        super().__init__(default_responders())
        self.scale = scale
        self.count: dict[str, int] = {}
        self._lock = threading.Lock()

    def complete_json(self, call: LLMCall) -> LLMResult:
        with self._lock:
            self.count[call.task] = self.count.get(call.task, 0) + 1
        time.sleep(DELAYS_S.get(call.task, 0.0) * self.scale)
        return super().complete_json(call)


def simulate(scale: float, parallel: bool) -> dict[str, Any]:
    old = pl.V1_PARALLEL
    pl.V1_PARALLEL = parallel
    try:
        llm = DelayedMock(scale)
        t0 = time.perf_counter()
        r = pl.run_premortem(PLAN_BATTERY, llm=llm, backend=build_backend(), cache_dir=None, session_id="sim")
        wall = time.perf_counter() - t0
    finally:
        pl.V1_PARALLEL = old
    return {
        "parallel": parallel,
        "wall_s": round(wall, 2),
        "total_s": r.manifest["total_s"],
        "v1_wall_s": r.manifest["v1_wall_s"],
        "timings_s": r.manifest["timings_s"],
        "calls": dict(sorted(llm.count.items())),
        "cards": len(r.risk_cards),
        "extract_batches": r.stages[[s.stage for s in r.stages].index("extract_issues")].counts.get("batches"),
        "states": {s.stage: s.state for s in r.stages},
        "result": r,
    }


def test_simulated_parallel_is_faster_and_same(monkeypatch):
    """병렬은 순차와 결과가 같고 더 빠르다. 빠르기는 벽시계 절대값이 아니라 같은 조건에서 잰 두 시간의 비율로 판정한다.

    과부하 때 스레드 기동·스케줄링 지연이 시간에 얹히므로 절대 상한(par < 2.6 단위)은 흔들린다(과부하에서 3/3 실패).
    부하 잡음은 시간을 늘리기만 하므로 (병렬/순차) 최솟값 비율이 기준(< 0.8)을 못 넘는 일은 병렬이 꺼졌을 때뿐이다.
    이상적인 비율: v1 병렬 24 / 순차 36 = 0.67. 한 단위 = 12초 × 배율.
    """
    scale = 0.05  # 12초 → 0.6초
    unit = 12.0 * scale
    runs: dict[bool, list[dict[str, Any]]] = {False: [], True: []}

    def measure(parallel: bool) -> float:
        out = simulate(scale, parallel)
        runs[parallel].append(out)
        return out["v1_wall_s"]

    assert_faster(lambda: measure(True), lambda: measure(False), max_ratio=0.8, what="병렬 v1 구간 / 순차 v1 구간")
    seq, par = runs[False][0], runs[True][0]
    assert seq["states"] == par["states"] and seq["calls"] == par["calls"]
    from tests.e3.test_pipeline_parallel import _dump

    assert _dump(seq["result"]) == _dump(par["result"])
    # 하한은 부하가 늘려도 깨지지 않는다(잠자기는 더 짧아질 수 없다):
    # 순차 v1 = 12×3 = 3단위. 병렬 v1 = max(12, 12+12) = 2단위(체크리스트 → 2차 검증 사슬이 임계 경로)
    assert min(r["v1_wall_s"] for r in runs[False]) >= 3 * unit * 0.95
    # 병렬이 2단위보다 짧으면 의존(체크리스트 뒤 2차 검증)이 깨진 것이다
    assert min(r["v1_wall_s"] for r in runs[True]) >= 2 * unit * 0.95
    # 전체 시간도 같은 방향: 병렬이 v1 구간 한 단위를 덜 쓴다(비율로, 최솟값끼리)
    assert min(r["total_s"] for r in runs[True]) < 0.92 * min(r["total_s"] for r in runs[False])


def _table(seq: dict[str, Any], par: dict[str, Any]) -> str:
    rows = ["| 단계 | 모의 지연 | 순차(E3-L1w) s | 병렬(E3-L1y) s |", "|---|---|---:|---:|"]
    for name in seq["timings_s"]:
        d = DELAYS_S.get(name)
        rows.append(f"| {name} | {'-' if d is None else f'{d:g}s/호출'} | {seq['timings_s'][name]:.2f} | "
                    f"{par['timings_s'][name]:.2f} |")
    rows.append(f"| **v1 구간 벽시계** | | **{seq['v1_wall_s']:.2f}** | **{par['v1_wall_s']:.2f}** |")
    rows.append(f"| **전체(total_s)** | | **{seq['total_s']:.2f}** | **{par['total_s']:.2f}** |")
    return "\n".join(rows)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sc = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    s, p = simulate(sc, False), simulate(sc, True)
    print(f"배율 {sc}, 카드 {s['cards']}장, 추출 묶음 {s['extract_batches']}개, 호출 수 {s['calls']}")
    print(_table(s, p))
    print(f"단축 {s['total_s'] - p['total_s']:.2f}s ({(1 - p['total_s'] / s['total_s']) * 100:.1f}%)")
