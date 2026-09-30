# FINAL 독립 검증

- 검증 모델: `codex-gpt-6-sol` (빌더 `codex-gpt-6.1-sol`과 별도)
- 범위: `final_tools.py`, `finalize.py`, 최종화 API와 화면의 좁은 경로. 실제 LLM 호출, 전체 `verify.py`, 8010/8020/8099 서비스 검증은 수행하지 않았다.
- 실행: `C:/Users/User/.venvs/neumann/Scripts/python.exe C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py -- C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e3/test_final_tools.py tests/e3/test_finalize.py tests/e4/test_finalize_api.py tests/e4/test_finalize_ui.py tests/e0/test_finalization_integration.py -q -p no:cacheprovider --basetemp C:/Users/User/Desktop/project_neumann/out/codex/final-independent-v5`
- 결과: `b9920c0` 작업트리에서 **68 passed in 1.80s**. 검증 당시 작업트리의 계약 스키마와 E0 통합 테스트는 이후 `e121eef`에 그대로 커밋됐다. 실행 helper가 provider를 mock으로 설정하고 라이브 플래그와 키를 자식 프로세스에서 제거했다.

**판정: 위 다섯 테스트 경로와 해당 작업트리 내용은 PASS.** 별도 UI 검증자가 수행한 브라우저 검사 1건도 PASS로 PM이 확인했다. 이 보고서 작성자는 브라우저 검사를 재실행하지 않았다.

## 독립 반례

`7361072`의 수치 도구는 `합계가 아님 3`, `항목 4`, `최대가 아님 10`에 대한 합계 `3+4<=10` 검사를 `passed`로 반환했다. 원문에 연산과 한계의 부정이 있는데도 표지어만 검색한 것이 원인이다. PM과 도구 빌더에게 즉시 전달했다. 수정 `63e111f`에서 전체 원문 줄의 부정·조건 표현을 검사하며, 독립 재현 `not a total 3` / `item 4` / `not at most 10`은 `unchecked negated_or_qualified_numeric_claim`로 바뀌었다. 위 57건은 수정 반영 뒤 재실행 결과다.

`ec4b756`의 수정 게이트는 근거 없는 과학 주장으로 바꾸려는 제안을 `unsupported_content`로 거절하고 최종 본문을 보존했다. 최초에는 거절된 문장이 `corrections[].after`에 노출됐다. `401e75e`에서 거절 제안을 고정 문구로 대체했고, 해당 집중 테스트가 원문 제안이 결과에 없는 것을 확인한다.

한국어 조사에 붙은 숫자(`3이다`)를 최초 수치 정규식이 놓쳐 실제 HTTP → 조립 → 엔진 → Z3 통합 검사에서 `unchecked`가 됐다. `919d89e`가 이를 접미 조사까지 인식하도록 수정했고, 위 실행의 E0 통합 테스트는 합계 `3+4<=6`에 대해 `failed`를 확인했다. 같은 요청의 재전송과 JSON 계약 검사도 통과했다.

## 완료 기준별 관찰

- 실제 Z3, Pint, NetworkX 실행과 수치·단위·그래프의 정상/실패/누락 분기: 집중 테스트 통과. 모든 연구 계획에 대한 의미적 정확성은 보장하지 않는다.
- 출처 인용·줄 결속, 임의 코드 값, 중복 수치, 상한, 도구 누락/타임아웃/취소: 집중 테스트 통과. 위 부정 반례는 수정 반영 뒤 `unchecked`로 확인했다.
- 최종 수정의 숫자·기관명·개인정보·마크업·새 과학 내용 차단, 모델 off/오류, 취소, 재검사: 집중 테스트 통과. 거절된 제안의 결과 노출도 수정 후 다시 확인했다.
- API의 일회성 요청, 동일 요청 재전송, 서명·출처, 시간 초과, 화면의 안전한 문자열 렌더링과 `.md` 내려받기: 집중 테스트 통과. 실제 HTTP 통합 경로는 mock LLM과 실제 Z3로 통과했다. 실제 브라우저/공개 서버 점검은 이 검증 범위에 포함하지 않았다.
