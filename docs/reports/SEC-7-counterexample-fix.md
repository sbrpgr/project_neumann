# SEC-7-counterexample-fix — 기준 9 반례 수정

- worktree: `C:/Users/User/Desktop/project_neumann/.claude/worktrees/s2-SEC-7`, branch: `task/SEC-7`.
- 시작 HEAD: `cd076ab754d312cf2054d594b56979c6348f6c68`, 시작 작업 트리 깨끗함.
- builder actual model: `codex-gpt-6.1-sol/medium` (PM 지정). 코드·테스트 커밋: `e70942e`. 최종 HEAD는 이 보고서를 포함하는 다음 커밋.
- 이번 변경은 `serving.py`, 새 `tests/e4/test_sec7_counterexamples.py`, 이 보고서뿐. upload/models/index/export 및 다른 제품 파일 변경 **0**.
- 제품 OpenAI API 호출 **0**. 합성 ASGI 요청만 사용. 실제 서비스·외부 네트워크·하위 에이전트·CLI 위임·main 병합/push/tag·다른 프로세스 조작 없음. `.env`/auth/키/전체 환경변수 출력·옛 프로젝트 접근·공개 원본 쓰기 없음.

## 수정과 완료 기준

독립 `SEC-7.codex.verify.md` 기준 9의 두 반례를 대상으로 수정했다.

1. 요청 대상 길이는 `raw_path` 바이트와 **쿼리가 있을 때만** `?` 1바이트+쿼리 바이트를 센다. 쿼리가 없는 정확한 8,192바이트 경로를 414로 거절하던 결함을 수정했다. URI 디코딩 후 문자 수로 세지 않는다.
2. GET 폴링 예외는 `/premortem/jobs/` 뒤 **비어 있지 않은 단일 구간**이 전체 경로와 일치할 때만 적용한다(`fullmatch`). 추가 구간·빈 구간·중복 슬래시·뒤 슬래시·인코딩된 슬래시로 생긴 추가 구간은 일반 GET 통을 사용한다. 정상 라우트의 모르는/형식이 틀린 job id도 jobs 핸들러의 기존 poll limiter가 처리하므로, 32자 토큰만으로 예외를 좁히지 않았다. HEAD 등 GET 이외 요청도 예외가 아니다.

| 합성 검사 | 수정 전 | 수정 후 |
|---|---|---|
| no-query raw target 8,191 / 8,192 / 8,193B | 204 / **414** / 414 | 204 / **204** / 414 |
| query 포함 target 8,191 / 8,192 / 8,193B | 204 / 204 / 414 | 동일 |
| percent-encoded raw path 8,192 / 8,193B | **414** / 414 | **204** / 414 |
| `/premortem/jobs/missing/extra`, GET 분당 2건 설정 | 404 / 404 / **404** | 404 / 404 / **429** |
| 빈/중복/뒤 슬래시 및 `%2F` 추가 구간, 5종 | 세 번째도 404 또는 307 | 세 번째 **429**, 다른 IP는 허용 |
| 정확한 단일 구간 폴링, 일반 GET=1 / poll=3 | 자체 poll limiter 사용 | 404×3 뒤 429; 일반 GET 통 소비 0 |
| HEAD 단일 구간 | 일반 GET 통 | 405 / 405 / 429 유지 |

새 18개 사례는 모든 응답의 기존 보안 헤더도 확인한다. 두 변이 검사는 이전 결함을 메모리에서 각각 되살리고 동일 경계/속도 제한 단언이 `AssertionError`로 깨지는 것을 확인한다. 제품 파일을 변이하거나 실패 검사를 건너뛰지 않는다.

## 명령과 출력

모든 pytest는 PM 지정 two-slot 러너를 거쳤다. 러너가 제품 키/live 플래그를 자식 환경에서 제거하고 mock·live tests=0을 지정한다. 전체 verify/전체 pytest/부하 시험은 실행하지 않았다.

```powershell
$env:PYTHONPATH='src;.'; $env:PYTHONIOENCODING='utf-8'
& 'C:/Users/User/.venvs/neumann/Scripts/python.exe' 'C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py' -- 'C:/Users/User/.venvs/neumann/Scripts/python.exe' -m pytest -q --tb=short --basetemp=out/sec7-counterexample-red tests/e4/test_sec7_counterexamples.py
# 수정 전: Target test slot 1/2 acquired; 7 failed, 11 passed in 0.54s; exit 1
& 'C:/Users/User/.venvs/neumann/Scripts/python.exe' 'C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py' -- 'C:/Users/User/.venvs/neumann/Scripts/python.exe' -m pytest -q --tb=short --basetemp=out/sec7-counterexample-green tests/e4/test_sec7_counterexamples.py tests/e4/test_sec7.py::test_get_rate_and_request_target_caps_are_early_and_ip_scoped tests/e4/test_jobs_limits.py::test_poll_rate_limit_per_ip
# 수정 후: Target test slot 1/2 acquired; 21 passed in 0.63s; exit 0
git diff --check
# 출력 없음; exit 0
```

18개 새 사례 + 기존 GET 2개 + 기존 jobs poll 1개 = 21개. 코드·테스트 커밋의 정상 pre-commit 훅은 `보안(스테이징): 파일 2개`, `verify 통과`였다. 이는 전체 PM verify 결과가 아니다. Git 공유 메타데이터 권한은 지정 두 파일의 require_escalated 커밋에만 사용했고 훅을 우회하지 않았다.

## PERF-pk 입구 제안 좁은 확인 / PM 인계

읽기 전용 기준: `task/PERF-pk` HEAD `06b649501121a4410584dc7989ede0e64a4cad1f`의 `docs/reports/PERF-pk_followup.md`, `PERF-pk_SEC7.patch`, `PERF-pk_L2g.patch`.

- `PERF-pk_SEC7.patch`: 새 `api/plan_limits.py`(75줄)에 정규화 전 **200,000자/5,000줄** 검사, 업로드 원시 줄 **100,000줄** 검사와 ASCII 줄 끝 패딩 정리. `upload._clean`의 NFC 앞에 `prepare_upload_text`를 넣고 main/jobs/export에도 관문을 넣는 복합 패치다.
- `PERF-pk_L2g.patch`: serving에서 `plan_key` 직전에 `check_plan_text`를 호출하는 7줄 제안. 위 새 모듈이 의존성이다. 현재 SEC-7 트리에 `api/plan_limits.py`는 없다. 기존 serving 원문 50,000자/5,000줄 관문과 제안의 200,000자·Unicode 줄 구분자 정책 조정도 필요하다.
- **미적용**: upload 및 신규 입구 모듈·main/jobs/export 변경은 이번 검토된 serving 경계 수정 범위를 벗어난다. PM이 기존 `PERF-pk_SEC7.patch`를 SEC7/E4 입구 담당자에게 별도 범위로 위임하고, L2g serving 담당자와 같은 관문 정책으로 통합해야 한다. models 정규화 패치는 여전히 PM 소유다. 기존 패치를 통째로 가져오거나 새 패치를 제품에 적용하지 않았다.

## 남은 일 (5줄)

1. 별도 `gpt-6-sol` 검증자가 기준 9의 두 반례와 폴링 예외 보존을 수정 HEAD에서 재측정한다.
2. PM 전체 verify 큐가 통합 HEAD를 검사한다(이번 빌더는 좁은 21개만 실행).
3. PM이 PERF-pk 입구 복합 패치의 신규 모듈/upload/main/jobs/export 소유와 정책을 별도 배정한다.
4. 이전 SEC-7의 278개 전체 표적 묶음·PDF·POSIX·성능 부하는 이번 범위에서 재측정하지 않았다.
5. 재검증 뒤 main 병합·공통 문서·배포는 PM이 담당한다. 이번 빌더는 서비스와 공통 문서에 손대지 않았다.
