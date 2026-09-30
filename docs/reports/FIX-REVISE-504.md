# FIX-REVISE-504 — revise 504 제한·카드 병렬 상한 수정

- 빌더: `codex-gpt-6.1-sol`
- 작업 브랜치: `codex/fix-revise-504`; 기준 HEAD: `983f3e9`.
- 빌더 검증 결과: 아래 mock 회귀 검사 통과. 별도 문맥의 독립 검증·커밋·병합은 Claude/PM에게 인계한다.
- 실제 제품 LLM 호출 0. `.env` 읽기·키 출력·Git 쓰기·다른 worktree 수정·하위 에이전트·사용자 브라우저 사용 없음.
- 화면 변경 없음. 시험 서버와 브라우저를 띄우지 않고 ASGITransport로 API를 검사했다.

## 원인과 수정

1. **90초 504의 직접 출처는 revise 라우트의 시간 제한이다.** 기존 `src/neumann/api/revise.py`의
   `DEFAULT_TIMEOUT_S=90.0` → `_timeout_s()` → `premortem_revise()` → `_Gate.run()` 순서로 전달된다.
   `_Gate.run()`은 대기열 진입과 실행에 `asyncio.wait_for`를 적용하고 남은 시간이 끝나면
   `AnalysisTimeout`을 올려 HTTP 504로 바꾼다. `src/neumann/api/finalize.py`도 `revise._timeout_s()`와
   같은 `_Gate.run()`을 사용한다. uvicorn의 keep-alive 설정에서 나온 제한이 아니다.
2. `ServingConfig.from_env()`의 공개 서버 기본 `NEUMANN_REQUEST_TIMEOUT_S=90`도 존재하지만,
   serving 미들웨어는 이 세 라우트를 `analysis`로 등록하고 하위 앱을 직접 기다린다.
   revise/finalize 실행 제한은 핸들러에서 별도로 적용되므로 전체 서버 설정을 올릴 필요가 없다.
3. **현재 기준 코드에는 이미 기본 3개 스레드의 카드 병렬 처리가 있었다.** `run_revision()`은
   `revise_result()`의 기본값을 그대로 사용한다. 따라서 이번 변경은 순차 코드를 새로 병렬화한 것이 아니라
   기존 `MAX_PARALLEL=3`을 **4**로 올리고, 명시적으로 `parallel=99` 같은 값을 줘도
   `min(parallel, MAX_PARALLEL, 카드 수)`로 **최대 4개**를 강제한 것이다.
4. revise·finalize 기본 제한을 **240초**로 변경했다. 기존 `NEUMANN_REVISE_TIMEOUT_S` 운영자 지정값과
   짧은 제한을 쓰는 회귀 검사는 계속 지원한다. assemble은 기본 **90초**를 유지한다.
   전체 serving 기본값(일반 300초/공개 90초)과 카드별 LLM 호출 제한은 변경하지 않았다.

## 보존한 동작과 분석 슬롯

- `ThreadPoolExecutor.map`이 요청 카드 순서를 보존한다. 작업 완료 순서를 의도적으로 뒤집어도 반환 순서는 같다.
- 기록 조회와 근거 색인은 병렬 시작 전에 구성한다. 카드마다 독립적인 `ProviderLLMCall`을 만들어
  `last_result`·model·usage 상태를 공유하지 않는다. 근거 게이트·원문 인용 조립은 기존 코드를 그대로 거친다.
- 각 카드의 실패는 해당 카드만 `generator=rule`, `status=degraded`로 표시한다. 나머지 카드의 정상 수정안을 반환한다.
  게이트에서 탈락한 문장과 실패 호출도 기존 감사·비용 집계에 반영한다.
- 요청 하나가 `Serving.gate`의 분석 슬롯 **1개**를 보유한다. 카드 스레드가 분석 슬롯을 추가로 얻지 않는다.
  `NEUMANN_MAX_CONCURRENT`는 요청 단위 상한이므로 스레드 4개와 재귀적 슬롯 경쟁이나 교착이 없다.
  `max_concurrent=1`에서 카드 4개가 동시에 실행되는 동안 다른 분석은 대기하고, 종료 후 정상 실행됨을 검사했다.
- 실제 OpenAI 네트워크 호출은 기존 프로세스 공용 `InflightLimiter`의 별도 상한
  (`NEUMANN_LLM_MAX_INFLIGHT`, 코드 기본 32)을 계속 적용받는다. 이 설정도 변경하지 않았다.
  동시 revise 요청 S개는 최대 4S개 카드 작업을 만들며, 공급자 호출은 별도 limiter의 제한을 받는다.
- timeout 뒤 협력 취소와 슬롯 유지/반납 회귀 검사를 통과했다. 실행 중인 카드가 끝날 때까지 슬롯을 유지하고,
  취소된 대기 카드는 공급자를 호출하지 않는다.
- API에서 실제 병렬 revision의 서명을 검증하고 같은 result와 finalize에 연결했다.
  `origin=server_signed`, `provenance.coupled=True`, finalization 서명 검증을 확인했다.
  기존 B1의 잘못된 결과·권고·통합본 결합 반례도 통과했다.

## 검증 명령과 측정값

모든 테스트 프로세스의 준비 명령:

```powershell
$env:PYTHONPATH='src;.'
$env:NEUMANN_LLM_PROVIDER='mock'
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK,Env:NEUMANN_LIVE_TESTS,Env:NEUMANN_UI_TESTS -ErrorAction SilentlyContinue
```

환경변수 값을 출력하거나 단언하는 새 테스트를 추가하지 않았다. 공통 conftest도 설정 로더의 `.env` 읽기를 끈다.

### 카드당 10초 지연 회귀 검사

```powershell
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e3/test_revise_parallel.py -q -s
```

출력:

```text
7 cards x 10s mock: serial=70.029s parallel=20.013s speedup=3.50x peak=4
4 passed in 92.16s (0:01:32)
```

- 순차 기준은 `parallel=1`, 병렬 기준은 제품 함수의 **기본값**이다. 둘 다 카드 7장·카드당 공급자 지연 10초를 실제로 기다렸다.
- 비교 시 생성 시각·실행 시간만 제외하고 권고·인용·감사·비용·기록·순서를 포함한 전체 출력이 같아야 한다.
- 통과 조건: 순차 70~85초, 병렬 20~30초, 병렬 시간 < 순차 시간/3, 동시 호출 peak=4.
- **70→20초는 순차 비교 기준의 측정값이다.** 이전 코드의 기본 3개 병렬을 70초였다고 주장하지 않는다.
  동일한 10초 호출 가정에서 기존 3개는 3회 묶음, 새 4개는 2회 묶음이다. 실제 서비스 87~90초의
  호출별 지연은 측정하지 않았으므로 서비스 실측 3.5배 개선으로 주장하지 않는다.

### E3/E4 revise·finalize·B1 회귀 검사

```powershell
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e3/test_revise.py tests/e3/test_revise_parallel.py tests/e4/test_revise_api.py tests/e4/test_revise_parallel_api.py tests/e4/test_revise_static.py tests/e4/test_revise_ui.py tests/e4/test_finalize_api.py tests/e4/test_export_pairing.py -q -s -k 'not ten_seconds'
```

최종 출력:

```text
126 passed, 1 skipped, 1 deselected in 7.06s
```

- `skipped`: 기존 브라우저 UI 검사는 `NEUMANN_UI_TESTS`가 꺼져 있어 실행하지 않았다. 화면 변경은 없다.
- `deselected`: 위에서 이미 실측한 90초 지연 검사의 중복 실행만 제외했다.
- 순서가 뒤섞인 병렬 2/4/99, 단일 카드 실패·근거 게이트 탈락, usage 합계
  input=280/output=28/total=308, 호출 7/실패 1, 정상 카드 유지 등을 검사했다.
- `_Gate.run()`에 revise와 finalize 각각 **240초**가 전달됨을 검사했다.
  serving 요청 기본을 0.5초로 둔 앱에서 finalize가 0.6초 걸려도 HTTP 200을 반환했다.
  전체 요청 기본은 0.5초 그대로이고 assemble 기본은 90초임을 검사했다.
- 먼저 실행한 핵심 5개 파일 검사도 `120 passed in 5.11s`였다.

### 정적 보안·계약 검사

`scripts.verify.load_real_secrets`를 메모리에서 `lambda: {}`로 대체한 다음
`security_worktree()`와 `check_contracts()`만 실행했다. 원본 파일은 수정하지 않았다.
이 방식은 `.env`와 실제 비밀값을 읽지 않는 **패턴·금지 경로·계약 검사**이며 전체 verify 통과를 뜻하지 않는다.

보고서까지 포함한 최종 출력:

```text
Pattern/path security: 804 files; contracts: 5개; problems: 0
```

`git diff --check`: exit 0, 출력 없음.

## 남은 일과 인계

- 실제 API 재시험은 과제 지시로 수행하지 않았다. Claude/PM이 별도 검증·커밋·병합 후 승인된 서비스에서 확인한다.
- 독립 검증 판정은 아직 없다. 빌더의 위 회귀 결과를 별도 작업 검증으로 표기하지 않는다.
  별도 검증자는 규칙에 따라 판정 기록에 `같은 모델(gpt-6.1-sol), 별도 작업 판정`을 남겨야 한다.
- Git 쓰기 금지 지시에 따라 add/commit/stash/merge/push는 시도하지 않았다. 아래 **6개 파일**이 Claude 커밋 대상이다.
  `src/neumann/analyze/revise.py`, `src/neumann/api/revise.py`, `tests/e3/test_revise_parallel.py`,
  `tests/e4/test_revise_api.py`, `tests/e4/test_revise_parallel_api.py`, `docs/reports/FIX-REVISE-504.md`.
- 권장 커밋 제목: `[FIX-REVISE-504] revise 카드 동시 호출 4개 상한·revise/finalize 기본 제한 240초`.
  본문 검증 줄: `mock 7x10s: 70.029s -> 20.013s; revise/finalize/B1 126 passed; builder: codex-gpt-6.1-sol`.
- 전체 `scripts/verify.py`는 비밀값 로더 때문에 직접 실행하지 않았다. 전체 verify와 커밋은 PM 절차에서 완료한다.
