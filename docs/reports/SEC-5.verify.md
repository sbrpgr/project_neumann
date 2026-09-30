# SEC-5 검증 보고서 (검증자: Claude Sonnet 5.5)

**판정: 미완료(교대로 중단)** — PM 지시로 Codex 인계 때문에 중단했다. 아래 "확인한 것"은 diff와 소스를 읽은 정적 검토뿐이고, 실행 측정은 하나도 하지 못했다. 이 문서만으로 PASS/FAIL을 내릴 수 없다.

- 대상: `task/SEC-5` 머리 `a288b3b` (main `17f9df5`에서 분기, 현재 main `5ed9b45`)
- 실행한 python·pytest·verify.py: 없음. scratch worktree 만들지 않음(정리할 것 없음). 빌더 worktree·main 수정 없음, 커밋 없음.

## 확인한 것 (정적 검토, 명령: `git diff 17f9df5 a288b3b`, `git diff --stat`, 소스 읽기)

| 항목 | 결과 |
|---|---|
| 4. 소유 경로 | `git diff --stat 17f9df5 a288b3b`가 6개 파일만 보여 준다: `.env.example`, `docs/reports/SEC-5.md`, `src/neumann/index/search.py`, `src/neumann/llm.py`, `tests/e2/test_sec5_search_status.py`, `tests/e3/test_sec5_inflight.py`. `contracts/`·`models.py`·`pipeline.py`·`backend.py`·`config.py` 변경 없음. 통과(stat 기준) |
| B. 자리 반환 경로 (읽기만) | `complete_json` 반복문에서 `acquire` 성공 뒤 `try/except/finally: limiter.release()`. `break`·`return`·재시도 분기 모두 `finally`를 지난다. 재시도의 `time.sleep(backoff)`는 `finally` 밖이라 쉬는 동안 자리를 쥐지 않는다. `acquire`와 `try` 사이에 예외가 날 문장은 없다(`backoff = 0.0`뿐). 결함을 못 찾았다. 실측은 안 함 |
| B. 대기 상한 (읽기만) | `acquire(timeout − 경과)`, 못 얻으면 네트워크 호출 없이 `FAIL_TIMEOUT` 반환. 재시도는 `elapsed < timeout/2`일 때만이고 재시도 때도 남은 시간으로 기다린다. 총 대기는 호출 상한 안. 실측은 안 함 |
| B. SEC-3 잠금 (읽기만) | diff에서 `_guard_model`·`NEUMANN_LIVE_LLM_OK` 관련 줄은 바뀌지 않았다. `config_error`는 생성자에서 정해지고 `complete_json`이 자리 잡기 전에 돌아간다는 빌더 주장은 diff 구조와 일치. 실행 확인은 안 함 |
| B. MockProvider (읽기만) | 변경된 클래스는 `OpenAIProvider`뿐, `make_llm`의 mock 분기는 그대로. 실행 확인은 안 함 |

## 확인하지 못한 것

1. 내 스트레스 시험(가짜 클라이언트로 상한 유지·예외/재시도/시간 초과 때 반환·교착 없음·대기 시간 상한). 미실행
2. SEC-3 잠금(`NEUMANN_LIVE_LLM_OK`, astra `guard_model`) 실행 확인, `MockProvider` 무영향 실행 확인. 미실행
3. `git merge-tree`로 현재 main과 충돌 여부, 병합 결과에서 `pytest`·`scripts/verify.py`. 미실행. SEC-4가 `models.py`에 병합됐지만 SEC-5는 `models.py`를 건드리지 않아 충돌 가능성은 낮아 보이나 확인한 것은 아니다
4. 빌더가 보고한 수치(14 passed, verify 1158 passed)의 재현. 미실행
5. `src/neumann/pipeline.py`를 열지 않았다. "파이프라인은 같은 스레드에서 `search()` 다음에 곧바로 `status()`를 부른다"는 빌더 주장(349~355행)과 E3-L1y 병렬화 여부는 검증하지 못했다. `backend.py`의 `status()`는 읽었고 `last_search_status()`를 그대로 부른다(예외면 `{}`).

## 정적 검토에서 나온 우려 (A, 재현 미확인 — 병합 전에 확인·수정 필요)

**A-1. 스레드 재사용 시 이전 요청의 상태가 남을 수 있다.** `last_search_status()`는 "이 스레드가 한 번이라도 검색했으면 그 스레드의 마지막 값"을 준다. `search()`는 시작할 때 스레드별 값을 지우지 않고 끝의 `_set_status()`에서만 덮어쓴다. 그래서 같은 작업자 스레드(anyio/uvicorn 스레드풀은 스레드를 재사용한다)에서 요청 1이 검색하고, 요청 2의 `search()`가 `_set_status()`에 닿기 전에 예외를 내면(예: `fusion` 값 오류로 `ValueError`, `get_store()` 실패, `embedder.encode` 예외, `_clean_queries`의 `axes` 길이 오류), 이어서 `status()`를 부르는 경로는 요청 1의 낡은 관련성 판정·강등 정보를 읽는다. 원래 코드(공용 값)에서도 낡은 값이 남는 문제는 있었지만, 스레드별로 바꾸면서 "자기 값"처럼 보이는 낡은 값이 되어 더 눈에 띄지 않는다. 파이프라인이 `search()` 예외 뒤에 `status()`를 실제로 부르는지는 `pipeline.py`를 안 열어 모른다.

권고(둘 중 하나, 작은 쪽):
- `search()` 맨 앞(모든 검증·예외 가능 지점 앞)에서 `_THREAD_STATUS.status = None`으로 비운다. 그러면 예외로 끝난 검색 뒤에는 공용 값으로 돌아간다. 더 엄밀히는 빈 상태 `{}`를 스레드 값으로 넣어 "이 요청은 검색 결과 없음"을 뜻하게 한다. 이 경우 회귀 시험 하나가 필요하다(예외를 내는 검색 뒤 `last_search_status()`가 이전 검색의 값이 아님을 확인).
- 근본적으로는 `search()`가 상태를 반환하거나(계약 변경이라 PM 승인 필요) 파이프라인이 요청 컨텍스트에 상태를 붙잡게 한다.

**A-2. 검색과 상태 읽기가 다른 스레드면 여전히 공용 값(경합)이다.** 스레드별 값이 없는 스레드는 공용 값(마지막 호출자)으로 돌아간다. E3-L1y처럼 단계를 병렬화해 `status()`를 `search()`와 다른 스레드에서 부르면 이 수정이 무효가 되고 이전과 같은 교차 요청 혼입이 재발한다. 빌더도 "코루틴이 `await`로 끼는 경로는 없다"는 전제를 적었다. `pipeline.py`·`backend.py` 호출 구조가 바뀌는 과제(E3-L1y 등)를 병합할 때 이 전제를 다시 확인해야 한다. 빌더가 든 `backend.status()` 회귀 시험은 같은 스레드에서 부르는 경우만 잰다.

## 인계 받는 검증자에게: 남은 할 일

1. 위 A-1을 최소 재현: 스레드 하나에서 정상 검색 → 같은 스레드에서 `search(["q"], fusion="bad")`(ValueError) → `last_search_status()`가 앞 검색의 값인지 확인.
2. `pipeline.py`에서 `backend.search()`·`backend.status()` 호출 지점과 예외 처리, E3-L1y 브랜치의 병렬화 여부 확인.
3. B 스트레스 시험(가짜 클라이언트만, `NEUMANN_LIVE_LLM_OK` 켜지 않고, 키는 가짜): 상한 정확히 유지, 예외·재시도·시간 초과 뒤 `snapshot()["in_flight"] == 0`, 대기 시간이 호출 `timeout_s`를 넘지 않음, 교착 없음, `MockProvider` 무영향, SEC-3 잠금 유지.
4. `git merge-tree`로 현재 main과 병합 충돌 확인 → scratch worktree에 병합(커밋 없이) → `pytest`와 `scripts/verify.py` → worktree 삭제.
5. 위 결과와 A-1 조치(권고 수정 + 회귀 시험) 여부에 따라 PASS / PASS-조건부 판정.
