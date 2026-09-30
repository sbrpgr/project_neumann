# FINAL-API-UI

Builder: codex-gpt-6.1-sol. Worktree branch: codex/final-ui-20261001.

## 구현

- 단일 POST /premortem/revise/finalize: 기존 AssembleRequest 입력과 submission_id, checks(최대 16)를 받는다. 기존 revision/result 계약·계획서 일치·실제 조립 preflight를 검사한다. polish=false 조립 뒤 finalize_plan을 호출한다.
- 보호 경로는 Serving.kind_for에서 강제 analysis로 등록한다. 설정에서 보호 경로를 비워도 우회하지 못한다. 기존 _Gate의 예약·환불·실행 상한·협력 취소를 쓴다.
- 프로세스 메모리에 요청 해시와 응답을 최대 64개/10분 저장한다. 같은 ID/같은 입력은 진행 중 요청에 합류하거나 결과를 재사용한다. 다른 입력은 409. 진행 중 항목은 퇴거하지 않으며 모두 진행 중이면 503. 중복 요청의 사용하지 않은 예산 예약은 환불한다. 오류/timeout도 저장해 동일 요청의 의미 호출을 반복하지 않는다.
- 입력 분석 결과와 수정 권고의 서명이 모두 확인된 경우에만 전체 finalization 응답에 서명한다. 미확인 입력은 서버에서 실행하더라도 client_submitted_unverified와 null 서명을 유지한다.
- 연구자가 원문 문단을 직접 편집한 경우 confirmed_text를 받아 confirmed_base_id와 조립 결과 ID를 대조한다. 개인정보/마크업/제어문자는 거절한다. 원본과 assembled는 유지하며 새 내용의 출처 미확인 안내를 finalization.notices에 넣는다.
- 기존 수정본 뷰어 안에 수정 확정·검증 버튼 한 개를 추가했다. 별도 확인 대화상자 없이 서버에 요청하고 최종 초안/변경/잔여 쟁점/실제 도구 검사 전후를 안전한 textContent DOM으로 보여준다. MD는 최종 초안을 내려받으며 DOCX는 통합본이라고 표시한다. 결정/편집/자리표시/충돌 변경은 최종 결과를 무효화하고 진행 중 요청을 취소한다.

## 검증

프로세스 설정은 mock, LIVE_TESTS=0, LIVE_LLM_OK=0, PYTHONUTF8=1. 실제 API 호출이나 서비스 서버 기동 없음.

명령: C:/Users/User/.venvs/neumann/Scripts/python.exe C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py -- C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e4/test_finalize_api.py tests/e4/test_finalize_ui.py tests/e4/test_revise_api.py -q

출력: 43 passed in 3.09s. git diff --check: 성공(출력 없음).

측정: 실제 HTTP 요청/실제 mock revision·assembly를 사용했다. 동시 중복 의미 호출 1회, payload 충돌 409, checks 17개 422, signed/unverified 출처 분리, 연구자 문안 binding/PII/markup 거절, 관문 없는 요청 503, 차단 503, rate 429, 크기 413, 검증 실패 예산 0, timeout 504 재사용, 엔진 예외 500 재사용, cache 64개 상한을 검사했다. 기존 revise API 회귀 35개도 통과했다.

## 제한과 다음

- 이 브랜치 테스트는 최종 엔진 호출만 mock으로 바꾼다. PM 통합 후 엔진/도구 커밋과 실제 mock-provider 통합 및 독립 모델 검증이 필요하다.
- UI 테스트는 정적 연결·안전 DOM 검사다. 실행 브라우저 클릭 흐름은 독립 검증에서 확인해야 한다.
- Idempotency는 단일 API 프로세스의 메모리 범위이며 10분/퇴거 이후 또는 서버 재시작 후 재실행할 수 있다. 완료 항목 퇴거는 오래된 것부터다.
- 원문 문단 직접 편집은 서버 통합본 응답을 받은 뒤 확정할 수 있다. 직접 편집의 새로운 사실은 출처를 검증한 것으로 표시하지 않는다.
- full verify, main 병합, push는 실행하지 않았다(PM 소관).
