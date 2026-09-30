# E3-L1s 독립 검증 — PASS-조건부, 병합 보류

- 검증자: codex-gpt-6-sol (빌더와 다른 모델). 대상 `task/E3-L1s` HEAD `47acaba`, 비교 main `75072fc`.
- 실제 OpenAI 호출 0, 제품 코드 수정 0, Git 쓰기 0. 모든 Python 명령은 venv에서 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_TESTS=0`, `NEUMANN_LIVE_LLM_OK` 해제, `OPENBLAS_NUM_THREADS=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `PYTHONPATH='src;.'`로 실행했다. pytest 캐시는 껐다.

## 완료 기준과 반증 결과

| 기준 | 독립 확인 | 판정 |
|---|---|---|
| 공백 포함 300자 미만 거절·LLM 0회 | `python -m pytest -q ... tests/e3/test_short_input.py tests/e3/test_fitness.py` → **144 passed**. 299/300 경계, 한국어, 범위 밖, `llm.calls == []` 검사. `fitness.py`의 사전 거절이 `llm_call`보다 앞선다. | PASS |
| 300~600자 또는 요소 2개 이하 경고·분석 | 같은 테스트에서 `input_quality.level=warn`, 검색·추출·카드, 화면 문구를 확인. 가짜 코퍼스 기반 14개 경고 입력의 카드 생성은 빌더 보고서의 실색인 측정과 구별했다. | PASS(검사 범위) |
| 검색 G7·범위 밖 | `test_weak_search_still_stops_uncertain_non_plan`, `test_offtopic_stopped_even_if_llm_says_uncertain`, `test_live_like_short_input_now_gets_cards` 통과. 코드 상 조건은 경고 단계, 무관 표지 없음, 상위 관련도 ≥0.50, 기준 이상 논문 ≥3편 모두 필요하다. | PASS |
| 분야 수준 규칙 카드 정직성 | 카드 0장 합성 + 심사평 지적이 있는 경고 입력에서 `generator=rule`, `plan_lines=[]`, 단계 `degraded`, 원문 근거 3건·논문 2편, 화면의 규칙 생성 표기 검사 통과. 지적 자체가 0건이면 근거 없는 카드를 만들지 않으므로 0장이 가능하다. | PASS(근거 있는 경우) |
| main 호환 | 읽기 전용 `git merge-tree <merge-base> main HEAD`에서 `src/neumann/api/view.py` 충돌 1곳. main의 `display_text(...)`와 신규 입력/검색 상태 블록이 겹친다. | 병합 전 해결 필요 |

## 전체 verify 기록과 남은 차단

`C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/verify.py`를 지정 환경에서 실행했다. 각 실행의 `PYTEST_ADDOPTS`에 `-p no:cacheprovider`와 허용 경로의 `--basetemp`를 지정했다.

1. 첫 실행: pytest 임시 디렉터리 부모를 만들지 않은 실행 설정 오류. **1052 passed, 46 skipped, 290 setup errors, 1 failed**. 이 실행은 완료 판정에 쓰지 않는다.
2. 부모 생성 후 `out/codex/pytest/E3-L1s/...` 사용: **1342 passed, 46 skipped, 1 failed**, 보안 파일 415개·계약 2개 통과. 실패 `tests/e5/test_judge_run.py::test_claude_briefs_isolated`: 테스트가 절대 임시 경로의 `project_neumann` 문자열까지 판정자 문서 누출로 오인했다. 같은 테스트를 이름에 `neumann`이 없는 허용 `visualizations` 임시 경로로 실행하면 **1 passed**.
3. PM 승인 후 허용 `visualizations` 임시 경로에서 전체 재실행: **1342 passed, 46 skipped, 1 failed in 84.97s**, 보안 415·계약 2 통과. 유일 실패는 `tests/e4/test_loadtest_multiuser.py::test_direct_round_runs_concurrently_and_matches_sequential_reference`의 시간 단언 `run_s >= 0.045 * len(llm.by_task)`. 동일 테스트 단독 실행도 **1 failed in 2.62s**; main 단독 기준선은 **1 passed in 3.84s**. 상세 재현에서 한 분석의 `run_s=0.312`, 과제 종류 7개, 단언 하한 `0.315`였다. 체크리스트·심사평·2차 검증은 병렬 단계여서 과제 종류 7개를 순차 지연으로 곱하는 단언은 실행 구조와 맞지 않는다. 그러나 브랜치에서 재현되는 전체 verify 실패이므로 통과라고 쓰지 않는다.

**조건:** TEST-1 또는 통합 담당자가 시간 단언을 실제 직렬 구간·병렬 구간에 맞게 수정하고, main 충돌에서 `display_text` 보존 후, mock 전체 `verify.py` PASS를 확인하기 전에는 병합하지 않는다. L1s의 300자 관문·G7·규칙 카드 집중 검사는 통과했다. 실제 실색인과 승인 라이브 재실행은 이번 검증에서 하지 않았다.
