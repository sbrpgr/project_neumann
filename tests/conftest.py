"""테스트 공통 설정(PM 소유).

기본 테스트는 실제 API를 부르지 않는다. NEUMANN_LIVE_TESTS=1일 때만 설정된 provider(openai)를 그대로 쓴다.
실제 호출 테스트는 NEUMANN_LIVE_TESTS=1과 NEUMANN_LIVE_LLM_OK=1을 함께 켜야 한다(대표 승인 과제만).
설정 로더가 처음 읽히기 전에(수집 시점) 환경변수를 정한다.
"""

import os

if os.getenv("NEUMANN_LIVE_TESTS") != "1":
    os.environ["NEUMANN_LLM_PROVIDER"] = "mock"
    # SEC-3: 실제 호출 허용 플래그를 명시적으로 닫는다(.env에 1이 있어도 환경변수가 우선)
    os.environ["NEUMANN_LIVE_LLM_OK"] = "0"
