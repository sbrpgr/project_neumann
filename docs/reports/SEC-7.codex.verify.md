# SEC-7 독립 검증 — Codex

## 판정과 범위

- **FAIL** — 완료 기준 9(GET 제한)에 재현 가능한 두 결함이 있다. 다른 11개 항목은 아래 오프라인 합성 범위에서 통과했다. 수정 후 기준 9와 전체 PM 검증을 다시 실행해야 한다.
- 검증 코드 고정 HEAD: `7f796b0080d4d282447f9a0c3c64755417dd7ccb`, 브랜치 `task/SEC-7`. 시작 작업 트리는 깨끗했다. PM 요청 모델 표기는 `codex-gpt-6-sol/medium`; 세션 내부에서 실제 런타임 모델 ID를 독립 조회할 수는 없었다.
- `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_TESTS=0`, `NEUMANN_LIVE_LLM_OK` 제거. 지정된 two-slot 러너는 자식 프로세스에서 라이브 플래그와 API 키도 제거한다. 실제 OpenAI 호출 **0**, 실서비스·외부 네트워크 호출 **0**. 제품 코드·테스트·계약·설정은 수정하지 않았다.
- 전체 `scripts/verify.py`, 전체 pytest, 부하 시험은 PM 전담이므로 실행하지 않았다. 데이터·모델·색인을 열지 않았다. POSIX 및 복잡한 실제 PDF는 측정하지 않았다.

## 재현 명령과 핵심 출력

표적 명령은 모두 `C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py --`를 통해 실행했다. 합성 탐침 파일 `C:/Users/User/Desktop/project_neumann/out/codex/sec7_verify_probe.py`는 저장소 밖 scratch이며 커밋 대상이 아니다.

```powershell
$env:PYTHONPATH='src;.'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'
& 'C:/Users/User/.venvs/neumann/Scripts/python.exe' 'C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py' -- 'C:/Users/User/.venvs/neumann/Scripts/python.exe' 'C:/Users/User/Desktop/project_neumann/out/codex/sec7_verify_probe.py'
# exit 0: security_414 414 True; get_rate [200,200,429]
# exact_8192_target 8192 414; poll_prefix_nonroute [404,404,404]
# package_prevalidation 422 package_limits True
# package_more_prevalidation {'decisions': 422, 'embedded_lines': 422}
# package_bare_prevalidation 422 package_limits; package_boundaries True 422
# public_health 6키/llm 3키, private failure 미포함 True
# cf_invalid 127.0.0.1; cf_valid 2001:db8::1; ipv6_56 True True
# queue_share 2 2; queue_release_idempotent 0 0 0
# line_count 4 422; log_exact True; log_forget True; setting_name_preserved True
# zip_declaration rejected_413; pdf_limit_unavailable rejected_503
# env_example_names_blank True
```

```powershell
& 'C:/Users/User/.venvs/neumann/Scripts/python.exe' 'C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py' -- 'C:/Users/User/.venvs/neumann/Scripts/python.exe' -m pytest -q --tb=short --basetemp='C:/Users/User/Desktop/project_neumann/out/codex/sec7-verify-pytest-a' tests/e4/test_sec7.py::test_worker_memory_limit_is_active_and_denies_allocation tests/e4/test_sec7.py::test_worker_refuses_when_memory_limit_cannot_be_installed tests/e4/test_upload.py::test_isolated_timeout_kills_worker tests/e4/test_sec7.py::test_pdf_decode_bomb_is_skipped_with_warning
# 4 passed in 1.81s
& 'C:/Users/User/.venvs/neumann/Scripts/python.exe' 'C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py' -- 'C:/Users/User/.venvs/neumann/Scripts/python.exe' -m pytest -q --tb=short --basetemp='C:/Users/User/Desktop/project_neumann/out/codex/sec7-verify-pytest-b' tests/e4/test_sec7.py -k 'line_limits_before_pipeline_and_job_creation or upload_line_limits_after_cleanup'
# 10 passed, 53 deselected in 0.51s
git diff --check main...HEAD
# 출력 없음, exit 0
```

## 완료 기준 12개

| 번호 | 독립 확인 | 판정 |
|---|---|---|
| 1 보안 헤더 | 합성 ASGI에서 414·422의 네 헤더 일치. 변경 코드의 바깥 `SecurityHeadersMiddleware`와 전역 500 직접 헤더 경로 확인. 빌더의 여러 정상 경로 63개 테스트 주장은 전체 재실행하지 않음. | 이 범위 PASS |
| 2 공개 health | 실패 사유와 키 존재 정보를 넣은 합성 `_llm_state`에도 공개 응답은 최상위 6키, `llm` 3키이며 실패 사유 문자열 없음. | PASS |
| 3 CF IP | IPv6 zone이 붙은 무효 헤더는 peer `127.0.0.1`; 정상 단일 IPv6는 선택됨. 경고는 헤더 값 대신 이름·건수만 기록하는 코드 확인. | PASS |
| 4 IPv6 /56 | 같은 /56의 서로 다른 /64는 같은 통, 다른 /56은 별도 통. | PASS |
| 5 IP 대기 몫 | 작은 합성 Gate에서 소유자 2자리의 추가 거절과 취소 두 번 뒤 소유자 0·전체 0 확인. 빌더의 4 IP×10 장시간 부하 수치는 재측정하지 않음. | 이 범위 PASS |
| 6 줄 수 | CRLF·CR·LF의 모델 기준 줄 계산 4; `result.plan.lines` 내부 5,001줄을 package에서 422. `/premortem`, `/premortem/view`, `/premortem/jobs`의 5,001줄 및 업로드 경계 표적 테스트 10개 통과. | PASS |
| 7 PDF·ZIP | 선언된 ZIP 21MB/압축 크기 10B는 413. pypdf 스트림 제한 문맥 진입 실패는 503. 작업자 128MB 제한의 160MB 할당 거절, 제한 설치 실패 503, 격리 timeout, 해제 폭탄 경고 표적 테스트 4개 통과. | Windows 합성 범위 PASS |
| 8 살아 있는 job 토큰 | 32자 합성 ID를 `+`로 쪼개도 정확 가림; 등록 해제 뒤 원문으로 복귀. 기존 코드의 raw·percent·다중 인코딩 검사 확인. | 이 범위 PASS |
| 9 GET 8KB·rate | 정상 `/health`는 2회 200 뒤 429, 414 응답에도 보안 헤더 존재. 다만 정확히 8,192바이트인 쿼리 없는 경로가 414이고, 폴링 경로가 아닌 `/premortem/jobs/missing/extra`는 3회 연속 404로 GET 통을 전혀 쓰지 않는다(아래 재현). | **FAIL** |
| 10 설정 이름 | 긴 `NEUMANN_UPLOAD_RATE_PER_MIN` 경고 이름은 마스킹되지 않고, 64k 로그 인자는 13자 생략문으로 잘림. | PASS |
| 11 package·refs | 201 연결 줄, 1,001 결정, 단일 embedded line의 5,001줄은 보호 ASGI에서 자리 예약·Pydantic·ZIP 전에 422. bare router의 101카드도 검증 전에 422. 100카드/1,000결정은 허용. `_plan_annotated`는 카드 내부 `dict.fromkeys` 후 고유 ref만 추가하는 코드 확인. | PASS |
| 12 설정 견본 | 지정된 7개 이름이 `.env.example`에서 모두 빈 값. `.env`는 열지 않음. | PASS |

## 기준 9 실패 재현과 수정 방향

1. **정확히 8KB인 요청 대상이 거절됨.** 합성 ASGI에서 `max_request_line=8192`로 두고 `GET /` + ASCII `x` 8,191개를 보냈다. 경로 바이트 길이 **8192**, 쿼리 없음, 실제 상태 **414**. `serving.py`의 `_precheck`는 `len(raw_path)+len(query_string)+1`을 무조건 더해 쿼리가 없어도 `?` 1바이트를 센다. 쿼리가 있을 때만 구분자 1바이트를 세고, 경계 8192 허용·8193 거절을 합성 테스트에 고정해야 한다.
2. **작업 폴링 경로 접두어로 GET 제한을 우회함.** 같은 합성 앱에 `/premortem/jobs/{job_id}` 라우트를 붙이고 `get_rate_per_min=2`로 둔 뒤, 실제 폴링 라우트와 일치하지 않는 `GET /premortem/jobs/missing/extra`를 3회 보냈다. 출력은 **`[404, 404, 404]`**이며 기대한 세 번째 **429**가 없다. `_precheck`가 `path.startswith('/premortem/jobs/')`만 보고 예외 처리하기 때문이다. 실제 job 폴링 라우트와 형태가 맞는 GET에만 예외를 주거나, 404 등 라우트 불일치는 일반 GET 통에 포함해야 한다. 이 결함은 임의 404 요청을 분당 상한 밖으로 보내게 한다.

## 변경 범위·남은 일

`git diff --stat main...HEAD`: `.env.example`, SEC-7 빌더 보고서, API `export/jobs/main/serving/upload`, E4 테스트·합성 측정 도구만 변경됐다. `contracts/`, `models.py`, `config.py` 변경은 없다. 아래 보고서 외에는 이 검증 작업트리를 수정하지 않았다.

1. 빌더가 기준 9의 두 경계 사례를 수정하고, 같은 합성 탐침을 다시 실행할 것.
2. PM 단일 큐가 고정 코드 수정본의 전체 `scripts/verify.py`를 실행할 것(이번 검증에서는 미실행).
3. POSIX 작업자 메모리 제한과 복잡한 실제 PDF의 시간·메모리는 미측정으로 유지할 것.
4. 빌더 주장 `278 passed`는 전체 재실행하지 않았고, 이번 별도 표적 결과는 `4 passed`와 `10 passed`임을 구분할 것.
5. 수정·재검증 뒤 PM이 병합·공통 결정 문서 갱신 여부를 판단할 것.
