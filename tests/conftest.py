"""테스트 공통 설정(PM 소유).

기본 테스트는 실제 API를 부르지 않는다. NEUMANN_LIVE_TESTS=1일 때만 설정된 provider(openai)를 그대로 쓴다.
실제 호출 테스트는 NEUMANN_LIVE_TESTS=1과 NEUMANN_LIVE_LLM_OK=1을 함께 켜야 한다(대표 승인 과제만).
astra 모델은 NEUMANN_ALLOW_ASTRA=1이 없으면 gpt-6.1-sol로 바뀐다(대표 지시: astra 금지).
설정 로더가 처음 읽히기 전에(수집 시점) 환경변수를 정한다.
"""

import os

_TRUE = {"1", "true", "yes", "on"}

if os.getenv("NEUMANN_LIVE_TESTS") == "1" and os.getenv("NEUMANN_LIVE_LLM_OK", "").strip().lower() not in _TRUE:
    # SEC-3: 라이브 테스트는 실제 호출 허용 플래그가 함께 있어야 돈다.
    # 조용히 건너뛰면 "전부 skip, 종료 코드 0"이 통과처럼 보이므로 사용 오류로 멈춘다.
    import pytest

    raise pytest.UsageError("NEUMANN_LIVE_TESTS=1에는 NEUMANN_LIVE_LLM_OK=1이 함께 필요하다(SEC-3). 라이브 테스트를 돌리지 않았다")

if os.getenv("NEUMANN_LIVE_TESTS") != "1":
    os.environ["NEUMANN_LLM_PROVIDER"] = "mock"
    # SEC-3: 실제 호출 허용 플래그를 명시적으로 닫는다
    os.environ["NEUMANN_LIVE_LLM_OK"] = "0"
elif "astra" in os.getenv("NEUMANN_LLM_MODEL", "").lower() and os.getenv("NEUMANN_ALLOW_ASTRA", "").strip().lower() not in _TRUE:
    # astra 금지(대표 지시): 옛 프로세스 환경에 astra가 남아 있어도 라이브 테스트는 sol로 돈다
    os.environ["NEUMANN_LLM_MODEL"] = "gpt-6.1-sol"
