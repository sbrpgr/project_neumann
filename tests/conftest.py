"""테스트 공통 설정(PM 소유).

기본 테스트는 실제 API를 부르지 않는다. NEUMANN_LIVE_TESTS=1일 때만 설정된 provider(openai)를 그대로 쓴다.
설정 로더가 처음 읽히기 전에(수집 시점) 환경변수를 정한다.
"""

import os

if os.getenv("NEUMANN_LIVE_TESTS") != "1":
    os.environ["NEUMANN_LLM_PROVIDER"] = "mock"
