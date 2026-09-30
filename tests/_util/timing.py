"""시간 의존 시험 보조(TEST-1): 벽시계 절대 상한 대신 쓰는 판정 도구.

외부 부하가 벽시계 측정에 잡음을 얹으므로 다음 순서로 판정한다.

1. 순서·겹침은 시각 비교가 아니라 이벤트·배리어로 증명한다(부하와 무관).
2. "병렬이 더 빠르다"는 같은 조건에서 잰 두 시간의 비율로, 반복 최솟값끼리 비교한다(`assert_faster`).
   반복 최솟값은 스케줄링 잡음을 줄인다. 두 실행의 부하가 다르면 비율도 흔들릴 수 있어 이벤트 검사와 함께 쓴다.
3. 선형성은 입력 길이를 늘렸을 때의 시간 비율로 판정한다(`assert_scales_linearly`). 절대 초가 아니다.
4. 벽시계 상한은 교착 감시에 쓴다. 적대 입력의 크기·절대 계산 예산은 process_time으로 별도 보존한다.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


def wall(fn: Callable[[], Any]) -> float:
    """fn을 한 번 실행하고 걸린 초를 돌려준다."""
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def best_of(fn: Callable[[], Any], repeat: int = 3) -> float:
    """fn을 repeat번 실행한 걸린 시간의 최솟값."""
    return min(wall(fn) for _ in range(repeat))


def assert_faster(
    fast: Callable[[], float],
    slow: Callable[[], float],
    *,
    max_ratio: float = 0.8,
    attempts: int = 3,
    what: str = "",
) -> tuple[float, float]:
    """`fast()`가 `slow()`보다 빠름을 비율로 판정한다. 둘 다 걸린 시간(초)을 돌려주는 호출이다.

    시도마다 (slow, fast)를 한 번씩 재고 지금까지의 최솟값끼리 비교한다: min(fast) / min(slow) < max_ratio면 통과.
    첫 시도에 통과하면 바로 끝낸다. 결함이 있으면(병렬이 꺼짐·직렬화) 부하와 무관하게 비율이 1 근처라서 매번 실패한다.
    `(min_fast, min_slow)`를 돌려준다.
    """
    fasts: list[float] = []
    slows: list[float] = []
    for _ in range(attempts):
        slows.append(slow())
        fasts.append(fast())
        if min(fasts) < max_ratio * min(slows):
            return min(fasts), min(slows)
    raise AssertionError(
        f"{what or '빠름'} 판정 실패: 빠른 쪽 {[round(x, 3) for x in fasts]} / 느린 쪽 {[round(x, 3) for x in slows]} "
        f"최솟값 비율 {min(fasts) / min(slows):.2f} (기준 < {max_ratio})"
    )


def assert_scales_linearly(
    make: Callable[[int], Any],
    run: Callable[[Any], Any],
    n: int,
    *,
    factor: int = 4,
    max_ratio: float | None = None,
    repeat: int = 3,
    what: str = "",
) -> float:
    """길이 n과 factor*n의 입력(`make(길이)`)에서 `run(입력)`의 시간 비율(최솟값끼리)이 max_ratio 미만인지 본다.

    선형이면 비율이 factor, 제곱이면 factor**2다. 기본 기준은 그 둘의 기하평균(factor**1.5, factor=4면 8)이다.
    입력은 시간을 재기 전에 만든다. 비율을 돌려준다.
    """
    limit = factor**1.5 if max_ratio is None else max_ratio
    small_in, big_in = make(n), make(factor * n)
    small = best_of(lambda: run(small_in), repeat)
    big = best_of(lambda: run(big_in), repeat)
    ratio = big / max(small, 1e-6)
    assert ratio < limit, (
        f"{what or '선형성'} 판정 실패: 길이 {n} → {factor * n}(x{factor})에서 시간 {small * 1000:.2f}ms → {big * 1000:.2f}ms "
        f"(x{ratio:.1f}, 기준 < x{limit:g}; 선형 x{factor}, 제곱 x{factor**2})"
    )
    return ratio
