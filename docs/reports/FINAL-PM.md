# [FINAL-PM] 최종 검사·교정 통합 완료 보고

- 작업일: 2026-10-01 (KST)
- 통합/계약 빌더: codex-gpt-6.1-sol. 병렬 빌더 3개와 독립 codex-gpt-6-sol 검증자 2개를 사용했다. 실제 동시 실행은 도구 상한인 root 포함 4개 이내였다.
- 브랜치: `codex/finalization-20261001`, UI/core 후보 `ff7e474`에서 분리. main 병합·push·공개 배포·기존 서버 변경 없음.
- 실제 OpenAI 호출 0회. 의미 모델은 mock/scripted 검증, 도구 계산은 실제 설치된 Z3/Pint/NetworkX로 수행했다.

## 구현한 것

연구자가 수정 방향을 결정한 뒤 `수정 확정·검증` 한 번으로 기존 조립과 최종 의미 검사·제한된 도구 검사·교정 1묶음·대상 도구 재검사를 수행한다. 최종 초안, 적용/거절 이유, 남은 쟁점, 도구 전후 결과와 생성 방식이 반환된다. 편집 뒤 이전 결과는 무효화한다.

- FINAL-TOOLS: 정확한 원문 위치에 연결된 제약 충돌(Z3), 단위 차원(Pint), 명시적 선행 관계(NetworkX). 부정·조건·모호한 수치/관계·없는 도구·범위 초과는 미검사이며 정상으로 꾸미지 않는다.
- FINAL-ENGINE: 구조화 의미 검사 1회와 교정 제안 1회, 최대 8개 줄의 교정 1묶음 및 대상 도구 재검사 최대 1회. 원문 앵커·수치·새 내용·개인정보·마크업 검사를 통과한 수정만 적용한다. 거절한 제안 자체도 출력하지 않는다. 실패·취소 때 미완료와 보존된 문안을 반환한다.
- FINAL-API-UI: 보호 관문·동시 실행/시간 상한·프로세스 안의 중복 제출 방지·입력 출처와 결과 무결성 서명, 연구자 직접 편집의 조립 id 대조, 최종 초안 화면/Markdown 내려받기.
- PM: 기존 계약을 바꾸지 않고 추가 응답 계약과 선택 의존성을 등록했다. 실제 HTTP→조립→최종 엔진→Z3→응답 계약·중복 제출을 검사하는 통합 테스트를 작성했다.

## 완료 기준별 검증

- 통합 집중 검사: `python -m pytest tests/e0/test_finalization_integration.py tests/e3/test_final_tools.py tests/e3/test_finalize.py tests/e4/test_finalize_api.py tests/e4/test_finalize_ui.py -q -p no:cacheprovider` — **68 passed in 1.91s**. 도구 미설치/취소/상한·잘못된 제안·단위/제약/구조 실패·보호 관문/출처/중복 요청·실제 도구 결과와 JSON 계약 검사 포함.
- 다른 모델 독립 집중 검사: **68 passed in 1.80s**, 보고서 `FINAL-INDEPENDENT.md`, 최종 제품/계약 내용 `e121eef`와 동일한 검사 대상. 독립 반례의 부정 수치 조건, 거절된 주장 노출, 한국어 숫자 접사 문제를 수정 후 재검사했다.
- 다른 모델 독립 브라우저 검사: `NEUMANN_UI_TESTS=1 python -m pytest tests/e4/test_finalize_browser.py` — **1 passed in 9.41s**. 실제 production HTTP와 fixture evidence/mock LLM으로 단일 클릭, 패널/Markdown 일치, 변경 후 무효화, 연결 실패를 확인했다. 보고서 `FINAL-UI-INDEPENDENT.md`.
- 중앙 전체 검사: `python scripts/verify.py` — **2175 passed, 56 skipped in 121.53s**, 보안 **592개**, 계약 **5개**, **verify 통과**, 종료 코드 0. 중립적인 `fr-final-whole-02` 임시 경로와 mock/offline 환경에서 수행했다.
- 첫 전체 검사: **2 failed, 2173 passed, 56 skipped**. 임시 경로의 `project_neumann` 문자열이 기존 블라인드 판정 테스트의 제품명 누출 검사를 건드렸다. 테스트를 약화하지 않고 중립 경로로 바꿔 전체를 다시 실행했다.
- `git diff --check`와 커밋 보안 훅을 정상 사용한다. 최종 인계 문서만 추가한 후 제품 검사를 불필요하게 반복하지 않는다.

## 한계와 다음

실제 LLM의 과학적 의미 판단과 교정 품질은 이번 mock 검사로 입증되지 않았다. 도구는 명시된 조건·수치·단위·선행 관계의 제한된 검사이며 연구 전체의 논리/물리적 타당성을 보증하지 않는다. 안전 게이트는 보수적이어서 제안을 거절하고 원문/미확인 항목을 유지할 수 있다.

임의 생성 코드나 범용 실험은 실행하지 않는다. 별도의 격리 실행기와 실행 승인 계약이 필요한 후속 범위다. 최종 교정본은 Markdown으로 제공하고 Word는 기존 통합본임을 화면에 구분했다. 실제 반려율 감소·보강본 효과 평가·최종 Word·실서비스 연결은 미완료다.

PM의 기존 core/UI 후보와 이 후속 브랜치를 합친 뒤 필요한 결합 검증을 하고 서비스 연결/승인된 확인 테스트를 진행해야 한다. 이번 후보 완료를 main이나 현재 실서비스에 반영된 것으로 표시하지 않는다.
