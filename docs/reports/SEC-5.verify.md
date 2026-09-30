# SEC-5 검증 보고서 (검증자: Claude Sonnet 5.5)

**판정: PASS** — 병합해도 된다. 완료 기준 전부 직접 실행으로 확인했고 반증하지 못했다. 다만 A에 잠재 결함 하나(아래 권고 R1, 두 줄 수정 + 시험 하나)를 재현했다. 현재 코드 경로에서는 도달하지 않아 병합을 막지 않지만, 고치기 쉬우니 SEC-5와 함께 넣기를 권한다.

- 대상: `task/SEC-5`. 검증을 시작할 때 머리는 `a288b3b`였고 중간에 빌더가 main(`5ed9b45`)을 병합해 `6ff0255`가 됐다. 두 커밋 사이에서 SEC-5 파일(`search.py`, `llm.py`, `.env.example`, 새 시험 2개, 보고서)은 **바이트 단위로 같다**(`git diff a288b3b 6ff0255 -- <그 파일들>` 빈 출력). 아래 실행은 (1) main `674901d` + `a288b3b`, (2) 마지막으로 main `c8ba766` + `6ff0255`에서 했다.
- 실제 OpenAI 호출 없음. 전 명령 앞에 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK`는 켜지 않았고 가짜 클라이언트·가짜 키만 썼다. `.env`는 열지 않았다.
- 내 시험은 scratch worktree(`scratchpad/wt_merged`)에만 두었고, worktree는 모두 제거했다. main·빌더 worktree 수정 없음, 커밋 없음, `git stash` 없음.

## 1. A. 검색 상태 (요청 간 혼입)

| 확인 | 방법 / 출력 | 결과 |
|---|---|---|
| 호출 구조 읽기 | `pipeline.py` 349행 `backend.search()` → 355행 `backend.status()`는 같은 `with run.stage("search")` 블록, 같은 스레드. `main.py` 163행이 파이프라인 전체를 `run_in_threadpool`로 한 스레드에서 돌림. `mcp_server.py`는 `search_lock` 안에서 검색+상태 읽기 | 요청 하나 = 스레드 하나 |
| E3-L1y가 병렬화해도 안전한가 | `git show task/E3-L1y:src/neumann/pipeline.py`에서 `backend.search`(391행)·`backend.status`(397행)는 여전히 같은 검색 단계 안. 병렬화는 카드 **뒤** v1 단계(예상 심사평 ∥ 체크리스트→2차 검증)뿐이고 이들은 `search`·`status`를 안 부름 | 안전 |
| 실제 파이프라인 동시 실행, 겹침 강제(내 시험) | `run_premortem` 2건을 스레드 2개에서, `IndexBackend.status` 안에 Barrier를 넣어 **두 검색이 다 끝난 뒤에** 각자 상태를 읽게 함. 6라운드(12건). **현재 코드: 불일치 0/12.** 사전 SEC-5 의미(공용 값만 읽기)로 바꾸면 **6/12** | 통과. 시험이 실제로 잡는다 |
| 겹침 강제 없는 동시 실행(내 시험) | 스레드 4개 재사용 풀에서 8라운드(32건). 현재 0/32, 사전 의미도 0/32 | 참고만: 검색이 ms 단위라 자연 겹침으로는 재현이 안 됨. 위 겹침 강제 시험이 결정적 |
| 빌더 시험이 옛 코드에서 실패하는가 | 분기 이전 `search.py`(`git show 17f9df5:…`)로 교체해 `tests/e2/test_sec5_search_status.py`: `3 failed, 1 passed` | 빌더 주장과 일치 |
| 스레드풀 재사용 + 검색 실패(내 시험) | 워커 1개 풀. 요청 1 성공 → 요청 2에서 `search()`가 예외(`fusion="bogus"` → ValueError, `_set_status` 전) → 같은 스레드 `last_search_status()` | **요청 1의 낡은 상태를 그대로 돌려준다** (`STALE_SAME_THREAD: True`, per_query 질의가 요청 1 것) |
| 같은 상황을 실제 파이프라인으로 | 워커 1개 풀. 요청 1 정상, 요청 2는 `search`가 예외를 던지게 해 `run_premortem` | 요청 2 결과에 `backend_status` **없음**(검색 단계 error). 낡은 상태를 소비하지 않는다 |

### A 판정과 권고

- **낡은 상태는 API 수준(`last_search_status()`)에서 실제로 재현된다.** 스레드별 값이 `search()` 끝의 `_set_status()`에서만 갱신되므로, 같은 스레드에서 이어진 요청의 `search()`가 `_set_status()` 전에 예외(잘못된 `fusion`, `axes` 길이 오류, `get_store()` 실패, `embedder.encode` 예외)로 끝나면 이전 요청의 판정·강등·질의가 남는다.
- **현재 코드에서는 이 값을 읽는 경로가 없다.** 파이프라인은 검색이 예외로 끝나면 `status()`에 도달하지 않고(위 표), MCP 서버도 예외가 그대로 나간다. 그래서 병합을 막지 않는다.
- **R1(권고, 병합과 같이 넣기 좋음).** `search()` 맨 앞(첫 줄, 예외 가능 지점 앞)에 `_THREAD_STATUS.status = {}`를 둔다. 그러면 예외로 끝난 검색 뒤에는 이 스레드 값이 빈 상태가 되어 낡은 값도, 남의 값도 돌려주지 않는다. 시험은 "예외를 내는 검색 뒤 `last_search_status()`가 이전 검색의 값이 아님" 하나면 된다.
  - **`None`으로 비우는 방식은 안 된다.** `last_search_status()`가 `None`이면 공용 값으로 돌아가는데 공용 값은 마지막 검색(요청 1 또는 남의 요청)이라 그대로 낡은 값이다. 실험으로 확인: `= {}` 변형을 scratch에 넣고 `tests/e2` 전체 + 내 시험을 돌리면 `76 passed, 2 skipped`, 실패는 낡은 상태를 기대한 내 특성화 시험 하나뿐(= 낡은 상태가 사라졌다는 뜻). `= None` 변형은 같은 시험이 그대로 통과(= 여전히 낡음).
- **A-2(잔여 위험, 조치 불필요).** 검색한 적 없는 스레드는 공용 값(마지막 호출자)을 읽는다. `status()`를 `search()`와 다른 스레드에서 부르는 변경이 들어오면 이 보호가 조용히 무효가 된다. 지금은 없다(E3-L1y 포함). 빌더가 이 전제를 코드 주석·보고서에 적었다. 요청 컨텍스트로 상태를 넘기는 구조(반환값에 상태 포함)는 계약 변경이라 지금 하지 않는 게 맞다.
- 사소: `_THREAD_STATUS.status = dict(status)`와 `_STATUS.update(status)`가 중첩 dict(`per_query` 등)를 공유한다(얕은 복사). 예전 공용 값도 같았다. 호출부가 중첩 값을 바꾸는 곳은 못 찾았다.

## 2. B. 동시 호출 상한 (내 스트레스 시험, 가짜 클라이언트만)

내 시험 8건(`tests/e3/test_v_sec5_b.py`, scratch에서만 실행): 모두 통과. 병합 트리에서 실행.

| 확인 | 측정 |
|---|---|
| 상한 유지 + 자리 새지 않음 | 공용 상한 5, 스레드 120개, provider 3개, 성공·APITimeout·429·500·400·RuntimeError·JSON 오류·미완료를 무작위로 섞음(실제 분포: ok 67, api_error 24, timeout 13, incomplete 11, json_invalid 5). 가짜 클라이언트 동시 진입 최고 **5**(= 상한), `snapshot`: `in_flight 0`, `acquired 145`(재시도 포함), `wait_timeouts 0`. 끝난 뒤 `_sem._value == 5`(모든 자리 복귀, BoundedSemaphore라 이중 반환이면 예외였을 것) |
| 대기 시간이 호출 상한으로 묶임 | 자리 1개를 한 호출이 쥔 채, `timeout_s=0.6` 대기자 8개: 전원 `error="timeout"`, detail "…자리 대기 초과", 각 **0.616~0.618초**에 돌아옴(상한 +18ms). 가짜 클라이언트 진입은 쥐고 있던 1건뿐(대기자는 네트워크에 안 나감). `wait_timeouts == 8` |
| 재시도 경로 | 500 → 재시도 전 2초 쉬는 동안 `in_flight == 0`(자리 비움). 그 사이 경쟁 호출이 자리를 잡아 4.6초 쥐면, 재시도 호출은 남은 시간(4초 상한 − 쉰 2초)만 기다리고 **4.0초에** `timeout`(자리 대기 초과 4s 상한)으로 끝남 |
| 예외 종류 | `BaseException` 하위(`Kill`)가 `create()`에서 나가도 예외는 그대로 전파되고 `in_flight 0`, 다음 호출이 자리를 얻음 |
| 교착 없음 | 상한 2, 스레드 300개, 시간 상한 0.05/0.2/1/5초 섞임: 2.49초에 전부 끝남. 진입 최고 2, `in_flight 0`, `acquired 98 + wait_timeouts 202 == 300`, 가짜 클라이언트 호출 수 == `acquired` (대기 초과는 네트워크에 안 나감) |
| 자리가 나면 대기자가 얻음 | 자리를 1초 쥔 호출 뒤 대기자가 약 0.9초 후 성공 |
| 중간에 공용 상한 교체 | 진행 중 호출 도중 `reset_inflight_limiter(7)`: 옛 객체에 반환(`in_flight 0`, `_value 2`), 새 객체는 7 |
| 시험이 실제로 잡는가(변이) | (a) `BoundedSemaphore(limit)`→`(1000)`: `test_v_cap_and_no_leak…` 실패. (b) `finally: release`를 성공 때만 반환(`else`)으로: 내 3건 실패(`cap_and_no_leak`, `retry_backoff`, `baseexception`). 모두 원복 |
| SEC-3 잠금 유지 | `NEUMANN_LIVE_LLM_OK=0` + 가짜 키 + 클라이언트 없음: `complete_json`이 `config_error`로 돌아오고 **공용 상한이 만들어지지도 않음**(`_INFLIGHT is None`). `make_llm(None,"openai")`는 잠금 상태에서 `MockProvider`(name `mock`)를 돌려주고 역시 상한을 만들지 않음. astra `_guard_model("gpt-6-astra")`는 변환됨(NEUMANN_ALLOW_ASTRA 없이). diff에서 `_guard_model`·`_live_llm_allowed`·잠금 관련 줄은 바뀌지 않음. `tests/e0/test_sec3_live_guard.py`는 verify 안에서 통과 |
| MockProvider 무영향 | 공용 상한 1의 자리를 내가 쥔 채 `make_llm(None,"mock")`으로 16스레드 동시 호출: 2초 안에 전부 끝, `acquired` 1(내 것뿐), `waited` 0 |

B 코드 읽기: `acquire` 성공 뒤 `try/except/finally: limiter.release()`. `break`·`return`·재시도 분기 모두 `finally`를 지난다. 재시도 `time.sleep(backoff)`는 `finally` 밖. `acquire`와 `try` 사이에 예외가 날 문장 없음. 호출 시작 때 잡은 `limiter` 참조를 반복문 끝까지 씀.

## 3. 병합 확인 (현재 main 대비)

| 확인 | 명령 / 출력 |
|---|---|
| 충돌 | `git merge-tree --write-tree --name-only main task/SEC-5` → 종료 0, 충돌 없음(트리 `2cd2d08…` 그리고 마지막에 main `c8ba766` 대비 `272b379…`) |
| 병합 결과 시험 | scratch worktree에 main을 놓고 `git merge --no-commit --no-ff task/SEC-5`(자동 병합 성공) 후 `python scripts/verify.py`: 처음(main `674901d` + `a288b3b`) **`1203 passed, 46 skipped in 70.35s` verify 통과**, 마지막(main `c8ba766` + `6ff0255`) **`1246 passed, 46 skipped in 91.89s`, 보안: 파일 415개, 계약: 2개, 테스트: 통과, verify 통과** |
| worktree 정리 | 둘 다 `git worktree remove --force`, `git worktree list`에 남은 것 없음 |

## 4. 소유·정직성

- `git diff main...task/SEC-5 --stat`: `.env.example`, `docs/reports/SEC-5.md`, `src/neumann/index/search.py`, `src/neumann/llm.py`, `tests/e2/test_sec5_search_status.py`, `tests/e3/test_sec5_inflight.py` 6개(819줄 추가). `contracts/`·`models.py`·`config.py`·`pipeline.py`·`backend.py` 변경 없음. `models.py`가 `git diff 17f9df5 task/SEC-5`에 보이는 것은 분기 뒤 main의 SEC-4 병합이 들어와서이고 SEC-5 자체의 변경이 아니다.
- 비밀값: 변경분에서 키 모양 문자열은 시험의 가짜 값 하나(`"fake-test-key"`)뿐. `.env`는 트리에 없다.
- `.env.example`에는 이름만(`NEUMANN_LLM_MAX_INFLIGHT=` 빈 값), 설명이 `.env` 줄은 지금 무시된다고 정직하게 적음(`config.Settings`에 필드 없음). 이는 보고서의 "못 한 것 1"과 같다.
- 보고서의 실패·한계 서술은 정직했다. 검증 중 발견한 보고서와 어긋나는 점은 없다.

## 5. 남은 위험 (병합을 막지 않음, PM이 알아 둘 것)

1. **캡이 429 문제를 시간 초과 문제로 바꿀 수 있다.** 대기가 호출 시간 상한에 들어가므로, 동시 6명(`NEUMANN_MAX_CONCURRENT=6`, E4-L2e 권장)이 요청당 24개 추출 호출을 내면 약 144개가 상한 32에서 5라운드 가까이 돈다. `extract_issues` 상한은 90초(`TASK_DEFAULTS`)라서 호출 하나가 약 20초 이상 걸리면 뒷줄 호출은 대기 초과(비상 경로)가 된다. 코드 결함이 아니라 값 조정 문제다. 대표 승인 확인 테스트에서 `snapshot()`의 `wait_timeouts`와 추출 비상 경로 비율을 재고 32를 조정해야 한다(빌더 보고서의 다음 단계와 같다).
2. 세마포어는 FIFO가 아니라서 부하가 크면 일부 호출이 평균보다 오래 기다린다(내 300스레드 시험에서도 짧은 상한 호출이 대거 대기 초과). 매달리지는 않는다(상한으로 묶임).
3. 자리를 얻은 뒤 남은 시간이 1초 미만이면 네트워크 호출은 최소 1초(`max(1.0, remaining)`, 예전과 같음). 대기 시간 자체는 상한 안이지만 총 소요는 상한 +1초까지 갈 수 있다.
4. 상한은 프로세스 단위다(uvicorn 작업자 여럿이면 작업자마다 32).
5. `.env`의 `NEUMANN_LLM_MAX_INFLIGHT`는 읽히지 않는다(환경변수로만). PM이 `config.py`에 필드를 넣기 전까지 기동 명령에 환경변수로 줘야 한다.

## 6. 권고 요약

- 병합 전에 꼭 고칠 것: **없음.**
- 같이 넣기를 권함: R1 — `search()` 첫 줄에 `_THREAD_STATUS.status = {}` + 회귀 시험 하나(예외를 내는 검색 뒤 낡은 상태가 없음). `None`은 안 됨(위 참고).
- 병합 뒤 PM 몫: `config.py`에 `llm_max_inflight` 필드, `docs/HANDOFF.md` 한 줄, 대표 승인 확인 테스트에서 `wait_timeouts` 측정.

---

## 재검증 (e69a88e)

**판정: PASS** — 후속 변경분(`6ff0255..e69a88e`)은 요구를 만족하고 병합해도 된다. 병합 충돌 없음(main `c8ba766`과 최신 main `f37100a` 둘 다), 병합 트리 전체 pytest(main의 알려진 불안정 시험 1건만 `--deselect`) `1248 passed, 46 skipped, 1 deselected`, `verify.py`(`c8ba766` 병합 트리) `1247 passed` 통과. 병합 전에 고칠 것 없음.

- 검증자: Claude Sonnet 5.5. 앞선 두 검증(정적 검토만 한 `a288b3b` 판, 전체 검증 `6ff0255` PASS)이 이 파일 위쪽에 있다. 이 절은 그 뒤 `e69a88e`(후속 커밋 하나, 3개 파일)만 다시 잰 것이다.
- 실제 OpenAI 호출 없음. 전 명령 앞에 `NEUMANN_LLM_PROVIDER=mock`, 가짜 임베더·가짜 코퍼스·mock provider만 썼다. `.env`는 열지 않았고 키 값은 다루지 않았다. main·빌더 worktree 수정 없음, 커밋 없음, `git stash` 없음(빌더 worktree `git status` 깨끗). scratch worktree(`wt_merged`, `wt_main`, 재개 뒤 `wt_merged2`)는 모두 제거했다.

### 1. 후속 변경분 (`git diff --stat 6ff0255 e69a88e`: `search.py` +15/-1, `tests/e2/test_sec5_search_status.py` +53, `docs/reports/SEC-5.md`)

`search()` 첫 문장에서 이 스레드 몫을 미완료 표지(`{"backend":"unknown","incomplete":True,"reason":…}`)로 바꾼다. 정상 종료 때는 `_set_status()`가 실제 상태로 덮는다. 앞선 검증의 권고 R1(`= {}`)을 표지 dict로 이행한 것이다. `None`이 아니라서 공용 값으로 돌아가지 않는다.

| # | 확인 | 방법 / 출력 | 결과 |
|---|---|---|---|
| 1a | 낡은 상태 재현(수정 전) | 내 스크립트: 작업 스레드 1개 풀. 요청 1 검색 성공(`hybrid`, `related`) → 요청 2의 `search()`가 `_set_status` 전에 예외 → 같은 스레드에서 `last_search_status()`. 예외 4종: `fusion="bogus"`(ValueError), `axes` 길이 오류(ValueError), `get_store()` 실패, `embedder.encode` 예외(RuntimeError). 넷 다 같은 스레드였음을 확인 | `a288b3b`의 `search.py`: **4/4 낡은 상태**(요청 1의 `per_query`·`relevance` 그대로). main `c8ba766`의 `search.py`: 4/4 낡은 상태 |
| 1b | 수정 후 | 같은 스크립트를 `e69a88e`(빌더 worktree, 읽기 전용 실행)와 병합 트리(main+SEC-5)에서 | **0/4 낡은 상태.** 네 경우 모두 `{'backend':'unknown','incomplete':True,'reason':…}`. 이어서 정상 검색을 하면 다시 `hybrid`로 복구(매번 단언). 검색한 적 없는 스레드는 공용 값(마지막으로 끝난 호출)을 그대로 읽음(이전 동작 유지) |
| 1c | 빌더 회귀 시험이 실제로 잡는가 | 빌더의 `test_failed_search_in_reused_thread_does_not_leave_stale_status`를 `a288b3b`의 `search.py`로 돌림(`-o pythonpath=`로 옛 소스를 앞에 둠) | `1 failed, 4 passed`. 실패는 그 시험 하나, 낡은 상태 단언에서. `e69a88e`에서는 통과 |
| 1d | 파이프라인 `backend_status` 처리(병합 트리의 E3-L1y 파이프라인, 실제 `index.search.search` + 가짜 저장소, mock provider) | 작업 스레드 1개 풀에서 `run_premortem` 3건: ① 정상 → `backend_status.backend == "hybrid"`, `degraded False`. ② `search`가 예외 → 검색 단계 `error`(내부 오류 ValueError), `plan_checks`에 `search` 없음, **`status()`는 불리지 않음**(호출 기록 `['search']`), 결과가 계약 스키마 통과, 그 스레드 상태는 표지. ③ 다시 정상 → 복구, 호출 순서 `['search','status']`, **같은 스레드 id** | 통과. 예외로 끝난 검색은 낡은 상태도 표지도 파이프라인에 싣지 않는다 |
| 1e | 표지가 (가정으로) 소비돼도 안 깨지는가 | `status()`가 표지를 돌려주게 강제한 뒤 `run_premortem` | 죽지 않음, 검색 단계 `ok`, `backend_status == {'backend':'unknown'}`(`_SEARCH_STATUS_KEYS`만 옮기므로 `incomplete`·`reason`은 안 실림), 계약 스키마 통과, 결과 전체에 표지 사유 문자열 없음 |
| 1f | mcp_server | `mcp_server.py` 404~406행: `search()`와 `last_search_status()`를 `search_lock` 안에서 한 스레드로 부름. `search()`가 예외면 상태 읽기에 도달하지 않고 예외가 `ToolError`/호출부로 나감. 표지가 읽힌다고 가정해 그 변환식(`st.get`)을 돌리면 `{'backend':'unknown','degraded':False,'reason':…}` | 깨지지 않음. 도달 불가 경로 |
| 1g | E3-L1y 이후에도 같은 스레드·직후인가 | 병합 트리 `pipeline.py` 391행 `backend.search(...)`, 397행 `backend.status()`: 같은 `with run.stage("search")` 블록, 사이에 검색 없음(`top`·`kept`·`counts` 계산뿐). 1d의 스레드 id 기록으로도 확인. 병렬화는 카드 뒤 v1 단계(`_attach_v1_parallel`, `neumann-v1` 스레드)뿐이고 이들은 검색을 안 부름. `src/neumann`에서 `.search(`를 부르는 곳은 `backend.py:60`과 `pipeline.py:391`뿐 | 안전. A-2 전제(검색·상태 읽기 같은 스레드) 유지 |
| 1h | 소유·비밀값 | `git diff main...task/SEC-5 --name-only`: `.env.example`, `docs/reports/SEC-5.md`, `src/neumann/index/search.py`, `src/neumann/llm.py`, `tests/e2/test_sec5_search_status.py`, `tests/e3/test_sec5_inflight.py` 6개. 후속 커밋은 그 중 3개. `pipeline.py`·`backend.py`·`models.py`·`config.py` 변경 없음. 후속 diff에서 키 모양 문자열 검색 결과 없음 | 통과 |

정보성(수정 불필요): 표지에 `degraded`를 싣지 않아서, 만약 어떤 호출부가 표지를 읽고 `bool(st.get("degraded"))`로 바꾸면 `False`가 된다(mcp_server 변환식이 그렇다). 표지를 읽는 경로는 현재 없고(예외 뒤에는 상태 읽기에 도달하지 않음) 표지의 `backend`가 `"unknown"`이라 정직하게 드러난다. 표지는 `incomplete=True`를 싣고 있으니 나중에 상태를 소비하는 코드를 새로 쓴다면 그 키를 보면 된다.

### 2. 병합 확인 (`e69a88e` → 현재 main `c8ba766`, E3-L1y 포함)

| # | 확인 | 명령 / 출력 | 결과 |
|---|---|---|---|
| 2a | 충돌 | `git merge-tree --write-tree --name-only main task/SEC-5` → 종료 0, 충돌 없음(트리 `0c6a799…`). scratch worktree에 main을 놓고 `git merge --no-commit --no-ff task/SEC-5` → "Automatic merge went well", 변경 6개 파일(위 1h와 같음), `MERGE_HEAD`=`e69a88e` | 충돌 없음 |
| 2b | `scripts/verify.py` (병합 트리) | `1247 passed, 46 skipped in 86.91s (0:01:26)` / 보안: 파일 415개 / 계약: 2개 / 테스트: 통과 / `verify 통과`(종료 0) | 통과 |
| 2c | 전체 `pytest` (병합 트리, `-q -p no:cacheprovider`) | 첫 실행 `1 failed, 1246 passed, 46 skipped in 93.73s`(그 동안 내 다른 스크립트가 같이 돌았음). 부하 없이 다시 `1 failed, 1246 passed, 46 skipped in 80.31s`. 실패는 두 번 다 같은 시험: `tests/e4/test_loadtest_multiuser.py::test_direct_round_runs_concurrently_and_matches_sequential_reference`(`tests/e4/test_loadtest_multiuser.py:211`) | **아래 3의 이유로 SEC-5와 무관한 main의 불안정 시험.** `verify.py` 안에서는 같은 시험이 통과함 |
| 2d | SEC-5 시험만 | 병합 트리 전체 실행에서 `tests/e2/test_sec5_search_status.py`(5건)·`tests/e3/test_sec5_inflight.py`(10건)는 실패 목록에 없음 | 통과 |

### 3. 실패한 시험이 SEC-5와 무관하다는 근거

- 시험이 하는 말: fixture 백엔드로 동시 3명을 돌리고 `run_s >= 0.045 × 부른 과제 수`를 단언한다(과제끼리는 차례로 돈다는 옛 가정, 단계당 mock 지연 0.05초).
- 원인 추정(측정): E3-L1y가 카드 뒤 단계를 병렬화(`expected_review ∥ checklist→semantic_validate`)해서 과제 7개짜리 건은 지연이 겹친다. 진단 스크립트(같은 시험 본문, 6라운드)에서 7과제 건의 `run_s`가 main에서 **0.315~0.474초**로, 기준선 0.045×7 = **0.315초**에 딱 붙어 있다. 그래서 겹침이 조금 커지면 실패한다.
- 순수 main `c8ba766`(SEC-5 없음)에서도 실패한다. 이 시험 한 건만 반복: 부하 없이 10회 중 2회 실패, main과 병합 트리를 번갈아 15회씩 돌려서 main 3/15 실패·병합 2/15 실패. 합계 main 5/25, 병합 7/25. 표본이 작아 차이는 의미 없다.
- SEC-5는 mock 경로를 안 건드린다(`MockProvider`·`DisabledProvider`는 상한을 안 거친다는 앞선 검증의 실행 확인). `search.py` 변경은 `FixtureBackend` 경로에 닿지 않는다.
- **조치 제안(SEC-5 밖):** 이 시험은 E4 소유(`tests/e4/`)이고 E3-L1y 병합이 만든 불안정이다. 기준선을 병렬화 뒤 구조(단계 종속 사슬 길이 × 지연)에 맞게 낮추거나 마진을 두는 E4 후속 과제가 필요하다. SEC-5 병합의 조건으로 삼지는 않는다. `verify.py`가 이 시험 때문에 가끔 실패할 수 있음을 PM이 알아 둘 것.

### 4. 재개 뒤 최종 병합 시험 (PM 지시: 불안정 시험 1건만 `--deselect`)

| # | 확인 | 명령 / 출력 | 결과 |
|---|---|---|---|
| 4a | 최신 main과 충돌 | main은 그 사이 `f37100a`(QUEUE·conftest·결정 문서 커밋들)로 전진했다. `git merge-tree --write-tree --name-only main task/SEC-5` → 종료 0, 충돌 없음(트리 `e7ab115…`). scratch worktree(`f37100a`)에서 `git merge --no-commit --no-ff task/SEC-5` → "Automatic merge went well", 변경 6개 파일(위 1h와 같음), `MERGE_HEAD`=`e69a88e` | 충돌 없음 |
| 4b | 전체 pytest (병합 트리 `f37100a`+`e69a88e`) | `NEUMANN_LLM_PROVIDER=mock`, `PYTHONPATH="src;."`, `python -m pytest -q -p no:cacheprovider --deselect "tests/e4/test_loadtest_multiuser.py::test_direct_round_runs_concurrently_and_matches_sequential_reference"` → **`1248 passed, 46 skipped, 1 deselected in 277.67s (0:04:37)`**, 실패 0 | 통과 |

(4b의 소요 시간이 앞선 80~94초보다 긴 것은 이 시간대에 다른 세션이 기계를 같이 쓴 탓으로 보이며, 통과·실패 결과와는 무관하다.) `verify.py`는 4b 시점의 병합 트리에서는 다시 돌리지 않았고, `c8ba766` 병합 트리의 통과(2b)를 그대로 쓴다. `f37100a`까지의 main 변경은 문서·conftest 쪽이고 SEC-5 파일과 겹치지 않는다(4a 충돌 없음).

### 5. 최종 결론

- 후속 커밋은 요구를 만족한다: 스레드 재사용 + 검색 실패 시 앞 요청 상태가 더 이상 남지 않고(4종 예외 재현, 수정 전 4/4 낡음 → 수정 후 0/4), 파이프라인·mcp_server 처리를 깨지 않으며, E3-L1y 뒤에도 `search()`→`status()`가 같은 스레드에서 붙어 있다.
- 후속 변경분 밖의 B(llm.py 동시 호출 상한)는 이번 재검증에서 다시 재지 않았다. 후속 커밋은 `llm.py`를 건드리지 않았고(`git diff --stat 6ff0255 e69a88e`에 없음) B 스트레스 시험·SEC-3 잠금·MockProvider 무영향은 위쪽 전체 검증(`6ff0255`, 병합 트리 실행) 결과가 그대로 유효하다. 전체 pytest(4b)에서 SEC-5의 시험 15건(`test_sec5_search_status` 5건, `test_sec5_inflight` 10건)도 통과했다.
- 병합 전에 고칠 것 **없음**. 병합 뒤 별도 과제(SEC-5 밖, PM이 이미 진행 중): `test_loadtest_multiuser` 기준선 조정(E4, 위 3).
