# FIX-B3 — SDK 전송 effort와 기준선 캐시 키 일치

판정: 빌더 검증 PASS. `b1bd7fa`에서 독립 검증 V-B1-B2B3의 effort 반례를 먼저 재현했고, 수정 후 동일 조건이 통과했다. 별도 모델의 독립 재검증은 PM 인계 사항이다.

- 작업일: 2026-10-01 KST.
- 브랜치: `codex/fix-b3`; 시작 HEAD: `b1bd7fa` (task/B2B3 최신).
- 근거: `out/codex/v-b1b2b3/docs/reports/V-B1-B2B3.md`의 B3 조건부 FAIL 및 내장 합성 SDK 재현.
- 빌더: Codex, 배정 기준 `codex-gpt-6.1-sol`.

## 무엇을 했나

`OpenAIBaseline.generate()`가 SDK 호출 직전에 정한 provider/model/effort를 결과에 남긴다. `generate_cached()`는 이 전송 기록으로 시도별 identity와 저장 키를 계산한다. 클라이언트 취득 중 medium→high로 바뀌어도 high 결과는 high 키에만 저장한다. SDK 전송 후 provider 속성이 바뀌면 이미 보낸 snapshot을 유지한다.

재시도 간 provider/model/effort가 다르면 `ok=False`, `output=None`, 캐시 미저장, riskset `status=error`로 처리한다. 모델 변경의 기존 `effective_model_changed` 표시는 유지하고 provider/effort 변경은 `effective_identity_changed`와 사유를 기록한다. 캐시 재사용 시 시도별 provider/effort도 검사하며, 해당 필드가 없는 기존 캐시는 이전 호환 규칙을 유지한다.

회귀 테스트는 클라이언트 취득 중 effort 변경 두 방향, 전송 후 변경, 동일 effort 재시도, provider/model/effort 혼합 재시도, 시도 기록 불일치를 검사한다. 실제 SDK와 설정 접근은 테스트에서 차단하고 합성 응답만 사용한다.

E5 기존 합성 SDK 테스트 세 파일에서 프로세스 live 허용 환경변수를 켜던 코드를 로컬 권한 함수 또는 config 전용 합성 매핑으로 바꿨다. 권한 파싱·철회·잠금 검사는 유지한다. E5 전체 실행에서 드러난 판정 지시문 테스트 두 건의 경로 오탐도 보정했다: 파일 경로·다른 판정자 접근 검사는 그대로 검사하고, 본문 시스템명 검사에서 호스트 임시 디렉터리 접두어만 제외한다. 제품 판정 지시문 코드는 변경하지 않았다.

## 완료 기준별 측정

모든 Python 실행은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `PYTHONPATH=src;.`를 사용했다. 공통 실행 환경은 다음과 같다. 비밀값을 읽거나 출력하지 않고 해당 이름을 환경에서 제거했다.

```powershell
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK,Env:NEUMANN_LIVE_TESTS,Env:NEUMANN_REAL_DATA_TESTS -ErrorAction SilentlyContinue
$env:NEUMANN_LLM_PROVIDER='mock'
$env:PYTHONPATH='src;.'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
```

| 기준 | 실제 명령/조건 | 출력 및 판정 |
|---|---|---|
| 수정 전 재현 | 제품 코드 수정 전 HEAD `b1bd7fa`; V-B1-B2B3 내장 Python 재현을 PowerShell here-string으로 `python.exe -`에 전달 | `recorded_effort=medium`, `sent_effort=high`, `second_cache_hit=false`, 합성 SDK 2회, 캐시 JSON 2개. 원래 FAIL 재현 |
| red | `python.exe -m pytest -q tests/e5/test_baseline_effort_identity.py` (최초 7케이스, 제품 수정 전) | `7 failed in 0.33s`, exit 1. effort 기록/키, 시도별 기록, 혼합 재시도, stale 재사용 반례 |
| green | 같은 명령, 제품 수정 직후 | `7 passed in 0.32s`, exit 0 |
| 원래 반례 재측정 | 같은 합성 SDK·취득 중 high 변경; 수정 후 올바른 결과를 단언 | `recorded_effort=high`, `sent_effort=high`, `second_cache_hit=true`, 합성 SDK 1회, 캐시 JSON 1개, exit 0 |
| E5 첫 전체 실행 | 로컬 무시 경로 `.cache/fix-b3/offline_pytest.py -q tests/e5` | `2 failed, 268 passed, 4 skipped in 3.98s`. 두 실패는 임시 경로 `project_neumann` 문자열의 본문 누출 오탐 |
| E5 최종 차단 실행 | `python.exe .cache/fix-b3/offline_pytest.py -q tests/e5` (혼합 모델/provider 케이스도 추가, 최종 신규 회귀 9케이스) | `272 passed, 4 skipped in 6.26s`, exit 0 |
| E5 표준 명령 | `.env` 존재 확인 false 뒤 `python.exe -m pytest -q tests/e5 -ra` | `272 passed, 4 skipped in 8.44s`, exit 0 |
| 보안 | `python.exe scripts/verify.py --security` | `보안: 파일 543개`, `verify 통과`, exit 0 (보고서 추가 전) |
| 최종 보안 | 보고서·Git 권한 차단 기록 포함 뒤 같은 명령 | `보안: 파일 544개`, `verify 통과`, exit 0 |
| diff | `git diff --check` | 출력 없음, exit 0 |

차단 실행의 로컬 runner는 자격 증명을 제거하고 provider를 mock으로 고정한다. Python audit hook으로 `.env` 파일 열기·socket 연결·자격 증명 환경 쓰기·프로세스 live 허용 켜기를 거절하고, 메모리에서 `Settings.model_config['env_file']=None`을 지정했다. 이 runner와 임시 캐시는 무시 경로에만 있으며 커밋하지 않는다. 최종 표준 명령도 같은 정리된 환경에서 통과했다. 환경변수 실제 값을 출력하거나 단언하는 테스트는 추가하지 않았다.

최종 건너뜀 4건: baseline 실제 API, DISAPERE 실제 API, 공유 실색인 회귀, DISAPERE 원본 ZIP 부재. 나머지 E5 테스트는 모두 통과했다.

## 못 한 것 · 다음

- 실제 제품 LLM 호출 0회. 시험 서버·브라우저를 기동하지 않았다. main 병합·push·stash·하위 에이전트 위임을 하지 않았다. 다른 worktree는 지정 보고서 읽기만 했다.
- 전체 저장소 pytest 및 `scripts/verify.py` 전체 모드는 실행하지 않았다. 이번 범위는 E5 전체와 보안 검사다. PM은 병합 전에 별도 모델 독립 검증과 전체 verify를 수행한다.
- 시도별 effort가 없는 과거 캐시에는 실제 전송 effort를 복원할 정보가 없다. 기존 호환성을 유지하며, 수정 이후 생성하는 항목에는 전송 snapshot을 기록한다.
- 기능 폴백이나 계약 변경은 없다. 커밋 대상은 `eval/baseline_llm.py`, E5 테스트, 이 보고서다. 완료 후 지정 대시보드 inbox에 커밋·검증 결과 한 줄을 전송한다.

## Git 권한 차단 — 커밋 미완료

사용자 지시상 `.git` 쓰기는 허용됐지만 실제 실행에서 아래 두 명령이 모두 exit 1로 거절됐다. 기존 lock 파일 존재 확인은 false다. HEAD는 계속 `b1bd7fa`이며 staging·커밋 완료를 주장하지 않는다. 훅 우회·권한 변경·외부 저장소 쓰기를 하지 않았다.

```text
fatal: Unable to create 'C:/Users/User/Desktop/project_neumann/.git/worktrees/fix-b3/index.lock': Permission denied
```

권한이 있는 PM/실행 환경이 이 worktree에서 다음 명령을 실행해야 한다. 커밋 메시지는 로컬 무시 경로에 준비했다.

```powershell
git add -- eval/baseline_llm.py tests/e5/test_baseline_effort_identity.py tests/e5/test_baseline_retry_cache_identity.py tests/e5/test_baseline_calltime_guard.py tests/e5/test_backtest_baseline_llm.py tests/e5/test_judge_n5.py tests/e5/test_judge_run.py docs/reports/FIX-B3.md
git commit --file .cache/fix-b3/commit-message.txt
```

제목: `[FIX-B3] Bind baseline cache to SDK-boundary effort identity`. 끝에 실제 E5·보안·diff 검증 결과와 `builder: codex-gpt-6.1-sol` 표기를 넣었다. 권한 차단과 테스트 결과를 지정 inbox에 한 줄 보고한다.

지정 PowerShell `Invoke-RestMethod -Method Post`로 `http://127.0.0.1:8099/api/inbox` 보고 완료: `kind=msg`, `id=m1790795206515`. 전송 내용은 FIX-B3 수정 완료, E5 272 통과/4 건너뜀, 보안 PASS, Git 권한 차단으로 미커밋, 보고서 경로와 PM 커밋 필요를 담은 ASCII 한 줄이다. 이 POST 외에 8099를 시험 용도로 사용하지 않았다.
