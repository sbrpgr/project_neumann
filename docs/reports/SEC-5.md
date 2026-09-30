# SEC-5 여러 사용자 동시 사용 안전성 보고서

- 빌더: Claude Opus 5.5 (`builder: claude-opus-5.5`)
- 브랜치: `task/SEC-5` (main `17f9df5`에서 시작)
- 커밋: `f37a335` (A 검색 상태 스레드별), `29e166c` (B 동시 호출 상한), 이 보고서 커밋
- 실제 OpenAI 호출: **없음.** 모든 명령에 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK`는 켜지 않았다(conftest가 `0`으로 고정). 가짜 클라이언트만 썼다.

## 배경

부하 시험에서 공개 서버에 사용자가 여럿(비동기 작업, 동시 4~6)일 때 문제가 될 두 가지가 나왔다.

1. `last_search_status()`가 프로세스 공용이다. 두 요청이 `search()`를 겹쳐 돌리면 파이프라인의 `backend.status()`가 **다른 요청의** 검색 상태(관련성 판정, 강등 여부)를 읽어 자기 StageStatus에 적을 수 있다(관측되지는 않았지만 경합이다).
2. 요청마다 쟁점 추출이 `NEUMANN_EXTRACT_PARALLEL`(기본 24)개 OpenAI 호출을 동시에 낸다. 동시 요청 N개면 N×24개가 한꺼번에 나가 OpenAI 속도 제한(TPM·RPM)에 걸리고, 시간 초과와 비상 경로가 늘어난다.

## 무엇을 했나

### A. 검색 상태를 호출 스레드별로 (`src/neumann/index/search.py`)

- `_THREAD_STATUS = threading.local()`을 공용 `_STATUS` 옆에 두었다. `_set_status()`는 두 곳에 모두 적는다.
- `last_search_status()`는 **이 스레드가 `search()`를 부른 적이 있으면 이 스레드의 마지막 상태**를 주고, 없으면 예전처럼 공용 값(어느 스레드든 마지막 호출)을 준다. `mcp_server`는 이미 `search_lock`으로 검색과 상태 읽기를 한 스레드에서 묶어 부르므로 그대로 맞다.
- 검색 결과·점수·정렬은 바꾸지 않았다(아래 시험에서 동시 실행 결과가 차례 실행 결과와 같음을 확인).
- 파이프라인(`pipeline.py` 349~355행)은 같은 스레드에서 `backend.search()` 다음에 곧바로 `backend.status()`를 부르고, API(`main.py`)는 파이프라인 전체를 `run_in_threadpool`로 한 스레드에서 돌린다. 그래서 스레드별 값이면 요청별 값이 된다. `pipeline.py`는 고치지 않았다(다른 세션 작업 중).

### B. 프로세스 전체 동시 OpenAI 호출 상한 (`src/neumann/llm.py`)

- `InflightLimiter`: `threading.BoundedSemaphore(limit)`와 관측용 숫자(진행 중·최고 동시 수·얻은 횟수·기다린 횟수·대기 초과 횟수, `snapshot()`). 얻지 않은 자리를 돌려주면 `ValueError`(누수·중복 반환을 숨기지 않는다).
- `inflight_limiter(settings=None)`: 프로세스 공용 상한 하나. 처음 부를 때 `setting(settings, "llm_max_inflight", "NEUMANN_LLM_MAX_INFLIGHT", 32)`를 한 번 읽어 만든다(이중 확인 잠금). 1 이상 정수가 아니면 기본값과 경고 로그. `make_llm`이 openai provider를 만들 때 이 설정으로 초기화한다. `reset_inflight_limiter(limit)`은 테스트·기동용.
- **기본값 32 (PM 조정).** 요청 하나의 추출 병렬 수(`NEUMANN_EXTRACT_PARALLEL`)가 지금 24이고 나중에 32가 될 수 있어서, 16이면 사용자 한 명도 느려진다. 32면 한 명은 영향이 없고, 동시 사용자 6명일 때 전체 동시 요청이 약 144개(6×24) 대신 32개로 묶인다. 이 까닭은 `llm.py`의 `DEFAULT_MAX_INFLIGHT` 주석과 `.env.example`에도 적었다.
- `OpenAIProvider.complete_json`에서 **네트워크 호출(`responses.create`)만** 감싼다.
  - 호출 시작 때 잡은 limiter 참조에 자리를 돌려준다(도중에 공용 상한이 바뀌어도 반환이 꼬이지 않는다).
  - 자리 대기는 **그 호출의 시간 상한에 들어간다**: `acquire(timeout − 지금까지 걸린 시간)`. 못 얻으면 네트워크에 나가지 않고 `LLMResult(ok=False, error="timeout", detail="동시 호출 상한 N개 자리 대기 초과(Ts 상한)")`로 돌아간다. `reason()`은 "호출 실패(시간 초과, 동시 호출 상한 …) [timeout]"이라 호출부가 그 단계만 비상 경로로 돌리고 status에 드러난다. 매달리지 않는다.
  - 성공·시간 초과·HTTP 오류·기타 예외·스키마 위반·미완료 모두 `finally`에서 자리를 돌려준다. 일시 오류 재시도는 **쉬는 동안 자리를 비우고** 재시도 때 남은 시간 안에서 다시 얻는다(예전에는 `except` 안에서 sleep했는데, 그대로 두면 쉬는 동안 자리를 쥐고 있게 된다).
  - provider 생성자에 `limiter=` 주입 인자를 두었다(테스트용, 기본 None = 공용 상한).
- `MockProvider`·`DisabledProvider`에는 걸지 않았다(네트워크 호출이 없다).
- SEC-3 잠금은 그대로다: `NEUMANN_LIVE_LLM_OK` 없는 실제 provider는 생성자에서 `config_error`가 정해지고 `complete_json`은 **자리를 잡기 전에** 돌아간다. astra `_guard_model`도 그대로다(바꾼 줄 없음).
- `.env.example`에 `NEUMANN_LLM_MAX_INFLIGHT=`(빈 값)와 설명을 추가했다.

## 완료 기준별 측정

모든 명령은 worktree에서 PowerShell로 실행했고 앞에 다음 환경을 두었다.
`$env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH='src;.'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; $env:NEUMANN_LLM_PROVIDER='mock'`

### A. 동시 검색이 각자 자기 상태를 읽는다

`tests/e2/test_sec5_search_status.py` (4건). 가짜 코퍼스·가짜 임베더(`tests/e2/conftest.py`)만 쓴다.

| 시험 | 무엇을 재나 |
|---|---|
| `test_concurrent_searches_each_read_own_status` | 스레드 A(혼합 검색, 질의 2개, 하한 0.3 → related)와 B(임베딩 없는 색인 → 어휘 검색 강등, 무관 질의 → unrelated)를 **Barrier로 검색 한가운데(BM25 점수 계산)에서 겹치게** 돌리고, 둘 다 끝난 뒤(두 번째 Barrier) 각자 상태를 읽는다. A는 `hybrid`·`degraded=False`·자기 질의·`related`, B는 `lexical_only`·`degraded=True`·자기 질의·`unrelated`. 결과(hits)는 차례 실행과 같다. 공용 값은 둘 중 하나뿐임을 확인(공용 값만 읽었다면 한쪽은 틀림) |
| `test_thread_without_search_falls_back_to_global` | 검색한 적 없는 새 스레드는 공용(마지막 호출) 값을 읽는다(mcp_server 호환) |
| `test_thread_status_survives_later_search_elsewhere` | 스레드 1이 검색 → 스레드 2가 다른 질의·제외 목록으로 검색 → 스레드 1은 여전히 자기 상태(`n_excluded=0`), 공용 값은 스레드 2 것 |
| `test_backend_status_per_request_thread` | 파이프라인 경로 `IndexBackend.search()` → `.status()`를 두 스레드가 동시에(검색 둘 다 끝난 뒤 상태 읽기) 해도 섞이지 않는다 |

옛 `search.py`(`git show HEAD:…`)로 같은 시험을 돌린 결과(수정이 실제로 잡는지 확인, 확인 후 되돌림):

```
FAILED tests/e2/test_sec5_search_status.py::test_concurrent_searches_each_read_own_status
FAILED tests/e2/test_sec5_search_status.py::test_thread_status_survives_later_search_elsewhere
FAILED tests/e2/test_sec5_search_status.py::test_backend_status_per_request_thread
3 failed, 1 passed in 0.14s
```

(통과한 1건은 공용 값으로 돌아가는 호환 시험이라 옛 코드에서도 통과하는 것이 맞다.)

### B. 동시 호출 상한

`tests/e3/test_sec5_inflight.py` (10건). `responses.create()`가 sleep하며 동시 진입 수를 세는 가짜 클라이언트를 `OpenAIProvider(client=…)`에 주입한다.

| 시험 | 무엇을 재나 |
|---|---|
| `test_default_is_32_and_setting_is_read` | 기본 32, 환경변수 `5` → 5, 설정 객체 속성 우선, `0`·`-3`·`abc`·`2.5` → 기본값, `InflightLimiter(0)`은 ValueError |
| `test_cap_holds_across_many_threads_and_providers` | 상한 3, 스레드 24개가 **각자 다른 provider**(동시 요청 흉내)로 한꺼번에 출발: 동시 진입 최고 **정확히 3**(넘지 않고, 상한까지는 실제로 병렬), 24건 모두 성공, `in_flight=0`·`wait_timeouts=0`, 21건 이상 대기, 걸린 시간 ≥ 직렬 8회분 |
| `test_process_wide_limiter_from_setting` | `limiter=`를 주지 않은 provider 10개가 `NEUMANN_LLM_MAX_INFLIGHT=2`로 만든 공용 상한 하나를 같이 쓴다(최고 2) |
| `test_wait_timeout_returns_failure_without_network` | 상한 1을 한 호출이 쥔 동안 `timeout_s=0.3` 호출: `error="timeout"`, detail에 "동시 호출 상한 1개 … 대기 초과(0.3s 상한)", **네트워크에 안 나감**, 0.25~5초 안에 돌아옴. 쥐고 있던 호출은 정상 완료, 자리 복귀 |
| `test_slot_released_on_every_outcome` | 상한 1에서 성공·APITimeoutError·400·RuntimeError·스키마 위반·미완료·성공을 차례로: 각 호출이 원래 오류 분류로 끝나고 다음 호출이 곧바로 자리를 얻는다(`waited=0`, `wait_timeouts=0`) |
| `test_retry_backoff_does_not_hold_slot` | 500 뒤 재시도: 쉬는 동안 `in_flight=0`, 재시도 성공(`attempts=2`, 자리 2번 얻음) |
| `test_no_deadlock_under_mixed_load` | 상한 4, 스레드 40개(느린 호출·즉시 예외·짧은 상한 섞음): 모두 제한 시간 안에 끝나고 최고 ≤ 4, `in_flight=0`, `얻음 + 대기초과 = 40 = 네트워크 진입 + 대기초과 실패` |
| `test_over_release_is_loud` | 얻지 않은 자리 반환은 ValueError, 숫자 안 꼬임 |
| `test_mock_and_off_providers_bypass_limiter` | 공용 상한 1의 자리를 잡아 둔 채로 mock 호출 8개 동시·off 호출이 곧바로 끝난다(상한 안 거침) |
| `test_live_lock_config_error_returns_before_limiter` | `NEUMANN_LIVE_LLM_OK=0`에서 키를 준 실제 provider: 클라이언트 안 만들고 `config_error`, 자리도 안 잡음 |

변이 시험(검사기가 실제로 잡는지, 각각 확인 후 원본 복구):

```
== mutation nocap            (BoundedSemaphore(limit) → BoundedSemaphore(1000))
FAILED ...::test_cap_holds_across_many_threads_and_providers
FAILED ...::test_process_wide_limiter_from_setting
FAILED ...::test_wait_timeout_returns_failure_without_network
FAILED ...::test_no_deadlock_under_mixed_load
4 failed, 6 passed in 1.26s
== mutation holdsleep        (재시도 전 sleep을 자리를 쥔 채로)
FAILED ...::test_retry_backoff_does_not_hold_slot
1 failed, 9 passed in 2.77s
== mutation noreleasefail    (성공 때만 반환, 실패 경로는 미반환)
FAILED ...::test_slot_released_on_every_outcome
FAILED ...::test_retry_backoff_does_not_hold_slot
FAILED ...::test_no_deadlock_under_mixed_load
3 failed, 7 passed in 92.07s
```

마지막 변이에서도 스레드가 매달리지 않고 끝났다(새는 자리 때문에 뒤 호출들이 30초 상한까지 기다린 뒤 대기 초과 실패로 돌아옴). 대기 상한이 교착을 막는다는 뜻이다.

### 새 시험 실행 결과

```
> python -m pytest tests/e2/test_sec5_search_status.py tests/e3/test_sec5_inflight.py -v -p no:cacheprovider
tests/e2/test_sec5_search_status.py::test_concurrent_searches_each_read_own_status PASSED
tests/e2/test_sec5_search_status.py::test_thread_without_search_falls_back_to_global PASSED
tests/e2/test_sec5_search_status.py::test_thread_status_survives_later_search_elsewhere PASSED
tests/e2/test_sec5_search_status.py::test_backend_status_per_request_thread PASSED
tests/e3/test_sec5_inflight.py::test_default_is_32_and_setting_is_read PASSED
tests/e3/test_sec5_inflight.py::test_cap_holds_across_many_threads_and_providers PASSED
tests/e3/test_sec5_inflight.py::test_process_wide_limiter_from_setting PASSED
tests/e3/test_sec5_inflight.py::test_wait_timeout_returns_failure_without_network PASSED
tests/e3/test_sec5_inflight.py::test_slot_released_on_every_outcome PASSED
tests/e3/test_sec5_inflight.py::test_retry_backoff_does_not_hold_slot PASSED
tests/e3/test_sec5_inflight.py::test_no_deadlock_under_mixed_load PASSED
tests/e3/test_sec5_inflight.py::test_over_release_is_loud PASSED
tests/e3/test_sec5_inflight.py::test_mock_and_off_providers_bypass_limiter PASSED
tests/e3/test_sec5_inflight.py::test_live_lock_config_error_returns_before_limiter PASSED
14 passed in 2.01s
```

시간에 기대는 시험이라 5번 거듭 돌렸다: `14 passed` × 5 (1.77~1.93s).

기존 관련 시험: `tests/e3/test_llm.py`, `tests/e0/test_sec3_live_guard.py`와 새 시험을 함께 → `64 passed in 4.92s`. `tests/e2` 전체 → `71 passed, 2 skipped`.

### verify

```
> C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/verify.py
1158 passed, 46 skipped in 86.33s (0:01:26)
보안: 파일 393개
계약: 2개
테스트: 통과
verify 통과
```

A 커밋(`f37a335`) 때는 `1148 passed, 46 skipped`, B 커밋(`29e166c`) 때 위 값이다. 보고서를 커밋하기 직전에 한 번 더 돌렸다:

```
1158 passed, 46 skipped in 77.91s (0:01:17)
보안: 파일 394개
계약: 2개
테스트: 통과
verify 통과
```

## 바꾼 파일

- `src/neumann/index/search.py` — 스레드별 상태(+14줄, 결과·점수 로직 무변경)
- `src/neumann/llm.py` — `InflightLimiter`, `inflight_limiter`, `max_inflight`, `reset_inflight_limiter`, `DEFAULT_MAX_INFLIGHT=32`, `OpenAIProvider(limiter=)`, `complete_json` 네트워크 호출 감싸기, `make_llm`에서 공용 상한 초기화
- `.env.example` — `NEUMANN_LLM_MAX_INFLIGHT=` 추가
- `tests/e2/test_sec5_search_status.py`, `tests/e3/test_sec5_inflight.py` — 새 시험
- `docs/reports/SEC-5.md` — 이 보고서

## 결정한 것

- **스레드별 저장은 `threading.local`.** 지시문의 예시를 따랐다. 제품 경로(파이프라인 전체가 `run_in_threadpool` 한 스레드)에서는 이것으로 요청별이 된다. asyncio 코루틴이 한 스레드에서 `search`와 `status` 사이에 `await`를 끼우는 경로는 지금 없다(있으면 `contextvars`가 필요).
- **대기 초과 분류는 새 코드가 아니라 기존 `timeout`.** 호출부(추출·카드·체크리스트)가 이미 `timeout`을 비상 경로로 처리하므로 새 분류를 만들면 호출부를 고쳐야 한다. 구분은 detail("동시 호출 상한 N개 자리 대기 초과")로 한다.
- **대기 시간은 호출 시간 상한에 넣었다(별도 대기 상한 없음).** 호출 하나가 자기 상한을 넘지 않는다는 기존 약속을 지키고 설정 키를 하나 덜 만든다. 자리를 얻은 뒤 남은 시간이 1초 미만이면 기존 코드처럼 최소 1초로 네트워크 호출을 한다.
- **공용 상한은 처음 부를 때 한 번만 설정을 읽는다.** 실행 중에 값을 바꾸려면 `reset_inflight_limiter()`(테스트·기동용). 진행 중인 호출은 자기가 얻은 옛 객체에 반환하므로 안전하다.

## 못 한 것 · 남은 것

1. **`.env`의 `NEUMANN_LLM_MAX_INFLIGHT`는 읽히지 않는다.** `config.Settings`가 `extra="ignore"`라서 필드 없는 키는 `.env`에 있어도 무시되고 `setting()`은 프로세스 환경변수만 본다(`Settings(_env_file=임시파일)`로 확인: `attr None max_inflight 32`). `NEUMANN_EXTRACT_PARALLEL` 등 기존 세부 키도 같은 처지다. 바꾸려면 서버 기동 명령에 환경변수로 주거나, PM이 `config.py`에 `llm_max_inflight: int | None = Field(default=None, validation_alias="NEUMANN_LLM_MAX_INFLIGHT")`를 추가하면 `setting()`이 속성을 먼저 읽으므로 코드 변경 없이 된다(`config.py`는 PM 소유라 손대지 않았다). `.env.example` 주석에 이 사실을 적었다.
2. **세마포어는 공정(FIFO)하지 않다.** 지시대로 `threading.BoundedSemaphore`를 썼다. 자리가 날 때 새로 온 스레드가 오래 기다린 스레드를 앞지를 수 있어, 부하가 몰리면 일부 호출이 평균보다 오래 기다려 대기 초과(비상 경로)가 될 수 있다. 대기는 호출 상한으로 묶여 매달리지는 않는다. 실측에서 대기 초과가 잦으면 FIFO 표 순번 방식으로 바꾸거나 상한을 올린다.
3. **상한은 한 프로세스 안에서만이다.** uvicorn 작업자(worker) 여러 개나 서버 여러 대면 작업자마다 32개씩이다. 저장소에는 `--workers`를 주는 기동 명령이 없다(grep 기준, 단일 프로세스).
4. **관측 값을 화면에 싣지 않았다.** `inflight_limiter().snapshot()`(상한·진행 중·최고·대기·대기 초과)을 `/health`에 싣는 것은 E4(api) 소유라 하지 않았다. 부하 시험 때 유용하다.
5. **실제 OpenAI로 잰 효과는 없다.** 규칙상 실제 호출을 하지 않았다. 대표 승인 확인 테스트에서 동시 4~6 요청을 돌려 `wait_timeouts`, 429 횟수, 추출 비상 경로 비율을 재 보는 것이 다음 단계다.
6. `eval/`의 기준선 LLM(`OpenAIBaseline`)은 자체 클라이언트라 이 상한을 거치지 않는다(평가 전용, 제품 서버 경로 아님, E5 소유).

## 다음 과제에 넘길 것

- PM: `config.py`에 `llm_max_inflight` 필드 추가(위 1), 병합 뒤 `docs/HANDOFF.md`에 "동시 OpenAI 상한 32, 대기 초과는 timeout 실패" 한 줄.
- E4: `/health.llm`에 `inflight_limiter().snapshot()` 싣기(비밀값 없음).
- 부하 확인(대표 승인 시): 동시 요청 4~6에서 대기 초과·429·비상 경로 비율.
