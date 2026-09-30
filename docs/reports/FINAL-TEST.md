# FINAL-TEST — 최종 흐름 실행기 준비·mock 예행연습

작성: 2026-10-01 KST. 작업 브랜치: `codex/final-test`. 기준 코드: `5eac066`.
빌더: `codex-gpt-6.1-sol`. 실제 OpenAI 호출 0회. 다른 worktree 수정, main 병합, push, 하위 에이전트, 브라우저 사용 없음.

## 구현

- `scripts/final_test.py`: 기본 대상 `http://127.0.0.1:8020`. 공개 샘플 2~3건을 ID, 카탈로그 상대 경로, 파일명으로 선택한다. 기본은 `example-battery`, `example-binding`, `example-operator`다. 임의 파일과 비공개 샘플은 받지 않는다.
- 순서: 입력 → `/premortem/jobs` 접수 → 잡 폴링 → 모든 카드 선택 → `/premortem/revise` → 모든 수정안 채택 → `/premortem/revise/assemble` → 문안 확정 → finalize → 최종 초안 확인 → `/premortem/package` ZIP 내보내기.
- 카드 채택 별도 API는 현재 없으므로 `card_ids`에 모든 카드를 전달한다. 수정안은 각각 `decision: 채택`을 보낸다. 조립의 충돌과 적용 수는 그대로 기록한다.
- 현재 finalize 경로는 `/premortem/revise/finalize`다. OpenAPI에 `/premortem/finalize`가 있으면 우선 사용하고, 현재 경로도 지원한다. 둘 다 없으면 `finalize_endpoint_missing`으로 실패한다. 제품 라우트는 변경하지 않았다.
- `data/final_test/<UTC 시각>/summary.json`, `summary.md`, 샘플별 ZIP을 저장한다. 단계별 소요·상태, 분석 단계 상태, 카드·수정안·적용·충돌·최종 교정 수, 도구별 before/after 상태, 모델 호출 카운터, 최종 초안 길이, ZIP 크기·SHA256을 기록한다. HTTP 오류는 상태 코드만 기록하며 원문 오류·헤더·설정·서명·잡 ID를 요약에 넣지 않는다.
- 서버 package API가 현재 조립본까지만 내보내므로 원래 ZIP 항목을 유지하고 실제 finalize 응답의 `final_draft.md`와 `final_test_validation.json`을 추가한다. 추가 검증 파일의 출처는 `final_test_runner_added`로 표시한다. 서버 서명을 새로 만들거나 서버 manifest를 바꾸지 않는다.
- 샘플·단계는 순차 실행하며 같은 출력 루트의 실행기 중복은 잠금 파일로 거절한다. 시작 전 서버 동시 상한도 1인지 확인한다. 프로세스 강제 종료로 잠금이 남으면 PM이 실행 중인 실행기가 없는지 확인한 뒤 해당 잠금만 제거해야 한다.
- `--mock`은 loopback HTTP 81xx만 허용하며 8171은 거절한다. 8099는 실행기 대상으로도 거절한다. `/health`의 실제 provider가 mock이 아니면 분석 POST 전에 거절한다.
- 라이브는 네트워크 요청 전에 `--i-have-approval`과 프로세스의 `NEUMANN_LIVE_LLM_OK=1`을 둘 다 요구한다. 라이브 health의 실제 provider도 openai여야 한다. 이번 작업에서는 라이브 플래그를 켜지 않았다. 종료 코드는 성공 0, 흐름/사전 점검 실패 1, 승인·입력·중복 실행 거절 2다.
- `scripts/final_test_mock_server.py`: 빈 loopback 81xx 포트 확인, worker 1, main과 serving의 동시 상한 1. `.env` 로더를 비활성화하고 키·솔트·라이브 플래그를 제거한다. 실제 API·파이프라인·수정·조립·확정 엔진을 쓰며 연구 기록은 명시적인 합성 fixture, LLM은 mock이다. OpenAI 호출 메서드도 차단한다. 원본 색인·모델·데이터는 사용하지 않는다.
- `--tool-probes`는 mock 전용이다. 조립 후 확정 문안에 합계·단위·의존 관계의 합성 부록을 추가하고 그 정확한 줄을 도구로 확인한다. 모델이 합성 부록을 수정 제안의 근거로 사용하지 않도록 분석 입력에는 부록을 넣지 않는다. 연구 자체의 검증이나 제품 성능 측정으로 해석하지 않는다.

## 실제 측정

예행연습 명령(지정 Python, `PYTHONPATH=src;.`, provider mock, 키·솔트·라이브 플래그 제거 환경):

```powershell
& C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/final_test_mock_server.py --port 8156
# 별도 터미널에서
& C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/final_test.py --url http://127.0.0.1:8156 --mock --tool-probes
```

최종 출력:

```text
FINAL-TEST passed: 3/3 cases; data/final_test/20260930T190755_718858Z/summary.json
```

총 5.641초. 모든 건에서 분석 결과는 `degraded`, 카드·최종 검토 generator는 `mock`, 최종 검토 상태는 `partial`다. PASS는 HTTP와 실행 순서, 실제 초안·ZIP 생성의 통과를 뜻하며 연구 검증 완료를 뜻하지 않는다.

| 공개 예시 | 카드 | 수정안 채택 요청 | 실제 적용 | 조립 충돌 | 최종 도구 교정 적용 | 최종 초안 글자 | 단계 소요 합 | ZIP 바이트 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| example-battery | 6 | 9 | 5 | 2 | 0 | 877 | 1.813초 | 30,359 |
| example-binding | 3 | 5 | 5 | 0 | 0 | 918 | 1.734초 | 25,597 |
| example-operator | 3 | 4 | 4 | 0 | 0 | 1002 | 1.750초 | 25,638 |

각 샘플에서 Z3 합계 검사, Pint 차원 검사, NetworkX DAG 검사 각 1건이 실제 실행되어 `passed`였다(총 9건). 모두 원문 줄에 연결한 합성 smoke 검사다. 각 샘플의 최종 의미 검토 mock 1회, 교정 mock 1회, 교정 배치 0회, 재검사 0회. ZIP은 각각 CRC 검사 통과, 원래 11항목과 실행기 추가 2항목으로 13항목이다. ZIP의 `final_draft.md`는 실제 finalize 응답 문안이다.

기능 검사 명령:

```powershell
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/test_final_test_runner.py tests/e0/test_finalization_integration.py tests/e3/test_final_tools.py tests/e4/test_finalize_api.py -q
```

출력: `89 passed in 5.23s`. 신규 실행기 검사 34개와 기존 확정·도구 검사 55개. 승인 누락, 잘못된 대상·포트, 비공개/임의 입력, 중복 실행, 실제 mock 상태와 상한 검사, 폴링 실패·시간 초과, 카드/수정안 없음, 각 HTTP 단계 실패, 빈 최종 초안, 미완료 확정, 잘못된 ZIP, 전체 순서·전부 채택·실제 초안 ZIP 포함, 실패 원문 미출력을 검사했다. 환경변수 값을 출력하거나 단언하는 테스트는 실행하지 않았다.

검증 러너도 동일한 **위 4개 파일에 한정한** `PYTEST_ADDOPTS`를 프로세스에 설정하고 실행했다:

```text
python scripts/verify.py
89 passed in 3.70s
보안: 파일 665개
계약: 5개
테스트: 통과
verify 통과
```

이는 저장소 전체 테스트 통과 주장이 아니다. `scripts/verify.py --security`도 별도 통과했다. 검증·훅 실행 전 worktree에 `.env`가 없는지 존재 여부만 확인했으며 파일을 읽지 않았다. `git diff --check` 통과. mock 서버는 이 작업에서 시작한 세션만 종료했고 `mock_port_closed: True`로 8156 포트 종료를 확인했다. 결과 data와 실행 로그는 커밋하지 않는다.

초기 예행연습 실패도 결과 폴더에 남겼다. 첫 실패는 mock 서버 wrapper가 실제 파이프라인에 지원되지 않는 filename 인자를 전달한 것으로 수정했다. 다음 실패는 모델 수정안이 합성 부록 줄을 바꿔 도구 원문 참조가 달라진 것으로, 부록 추가를 조립 후 문안 확정 단계로 옮겼다. 해당 실패를 성공으로 덮어쓰지 않고 최종 성공 결과를 별도 시각 폴더에 저장했다.

## 실행 방법과 남은 일

mock 준비 환경:

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONIOENCODING='utf-8'
$env:NEUMANN_LLM_PROVIDER='mock'
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK,Env:NEUMANN_LIVE_TESTS -ErrorAction SilentlyContinue
```

대표 승인 뒤 운영자가 승인된 프로세스에서 사용할 명령(이번 작업에서는 실행하지 않음):

```powershell
& C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/final_test.py --i-have-approval --samples example-battery example-binding example-operator
```

기본 URL은 8020이다. 해당 운영자 프로세스의 라이브 허용 확인과 서버 `MAX_CONCURRENT=1`이 필요하다. 실제 호출 권한 없는 현재 환경에서는 기본 명령이 `FINAL-TEST refused: live_requires_approval_and_process_flag`, 종료 코드 2로 요청 전 거절됨을 확인했다. 승인 플래그만 있는 경우도 거절하도록 순수 함수 검사했다. 실행기 자체는 OpenAI 키를 받거나 읽지 않는다.

남은 일: PM의 main 통합·전체 회귀 검증·독립 모델 검증과 05:30~06:00 대표 승인 라이브 테스트. 하위 에이전트 금지에 따라 독립 검증을 수행했다고 주장하지 않는다. 현재 mock에서는 같은 줄 수정 충돌, 확인 필요 자리표시, 실제 도구 교정 적용 및 재검사까지의 성공을 입증하지 못했다. 라이브 요약의 `partial`/`incomplete`, 미검사 도구, 충돌을 실제로 확인해야 한다. 이 작업에서는 제품 분석·UI·계약을 변경하지 않았다.

## 커밋 차단

파일을 명시한 `git add`와 `[FINAL-TEST]` 제목의 `git commit`을 시도했으나 둘 다 아래 오류로 실패했다:

```text
fatal: Unable to create 'C:/Users/User/Desktop/project_neumann/.git/worktrees/final-test/index.lock': Permission denied
```

worktree 메타데이터 경로가 존재하고 index.lock은 없으며 해당 경로에 Deny ACL이 있음을 읽기 전용 확인했다. 안내된 `.git` 쓰기 허용이 실제 실행 환경에는 반영되지 않은 상태다. ACL·훅·잠금을 바꾸거나 우회하지 않았다. 스테이징 0개 검사 통과를 코드 검증으로 주장하지 않는다. 코드와 이 보고서 4개 파일은 현재 브랜치 worktree에 미추적 상태로 남아 있다. PM이 실행 환경의 쓰기 권한을 반영한 뒤 이 worktree에서 명시적 add·커밋을 완료해야 한다.
