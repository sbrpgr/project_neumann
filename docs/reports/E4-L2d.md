# E4-L2d 보고서 — 비동기 작업 API + 화면 폴링

- 빌더: Claude Opus 5.5 · 검증 예정: Claude Sonnet 5.5 · 브랜치 `task/E4-L2d`(`task/E4-L2c` 위에서 시작, 시작 때 `main` 병합 1회, 충돌 없음)
- 스펙: PM 배정 지시(과제 파일 없음). 배경: cloudflared quick tunnel은 응답을 약 100초에서 끊는다(524). 분석 1건 60~70초라 대기열에서 기다리면 넘는다.

## 재작업 4(검증 FAIL 1건: 접근 로그의 퍼센트 인코딩 job_id)

문제: uvicorn 접근 로그는 쿼리 문자열을 날것으로 적는다. 재작업 3의 가리기는 값이 `%`로 시작하거나 중간에 `%XX`가 끼면 토큰이 끊겨 job_id가 남았다(검증 퍼징: job이 아닌 쿼리 키에 인코딩 글자 하나 → 300건 중 183건 누출). 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `git stash` 안 씀.

| 한 일 | 확인 |
|---|---|
| `serving.mask_job_paths`: `[URL-safe 글자 \| %XX]`가 이어진 구간을 토큰으로 읽고 **풀어서(decoded)** 판정한다. 푼 글자가 URL-safe로 이어진 길이가 접근 로그 20자·앱 로그 26자 이상이면 그 부분을 "푼 앞 6자 + …"로 바꾼다(인코딩된 구분 글자 `%2F` 등은 그대로 두고 앞뒤를 따로 본다). `/premortem/jobs/…` 경로와 `?job=`·`?job_id=`·`?id=`·`?ticket=` 쿼리 값은 길이와 무관하게 푼 앞 6자(구분 글자에서 멈춤) + "…". 두 번 걸어도 같다. 요청 번호(16자)·예외 이름·템플릿 이름 같은 짧은 토큰은 그대로 | `test_access_log_masks_percent_encoded_job_ids_through_uvicorn_formatter`: 실제 `uvicorn.access` 로거 + uvicorn `AccessFormatter` + 서빙 로그 필터(로거·핸들러 두 번)를 거쳐 `?job=`(첫 글자·두 글자·전체 인코딩), `?x=`(평문·`%2D` 하나·전체), 다른 키 `?next=`, 인코딩된 키 `?%6Aob=`, 쿼리 안 인코딩 경로, 경로·`%2F` 경로·경로+쿼리 12종 × id 5개 — 원래 id도 푼 id(1·2회 unquote)도 12자 조각 0. `test_access_log_mask_fuzz_300_no_leak_and_idempotent`: 모양 10종 × 인코딩 확률 0~100% 무작위 300건 누출 0, 모두 멱등. **두 테스트 모두 고치기 전 코드(40e283e)에서는 실패**(스크래치 사본에서 확인) |

검증자 스크립트(scratchpad `v/`)로 다시 잼:

```
$ NEUMANN_LLM_PROVIDER=mock python v/mask_fuzz.py
cases: 1950 leaks: 0
$ NEUMANN_LLM_PROVIDER=mock python v/mask_fuzz2.py          # 모양 6종 × 인코딩 확률 5종 × 300건
/x?job={}   p=0.03~1.0 leaks 0/300 (각각)  ·  /x?x={}  0/300  ·  /premortem/jobs?job_id={}  0/300
/premortem/jobs/{}  0/300  ·  /x?a=1&ticket={}  0/300  ·  /x/{}  0/300
$ NEUMANN_LLM_PROVIDER=mock python v/e2e_log.py <worktree> 8139 …   # 실제 uvicorn(serve.py와 같은 옵션) + 가짜 파이프라인
jobs: [('fkeXtR…', 'done'), ('-0Kf7l…', 'done'), ('SwTB82…', 'done')]
id fkeXtR…: full-id-in-log=False; 12-char-slice-in-log(raw)=False; (after unquote)=False   (세 id 모두 같음)
exposed lines for id0: 0            (요청 18종: 경로·대문자·겹 슬래시·%2F·인코딩 id·?job=·?x=·?ticket=·부분·전체 인코딩)
```

```
$ git archive HEAD → E4-L2c_main.patch → E4-L2d_main.patch (둘 다 git apply --check 통과) → NEUMANN_LLM_PROVIDER=mock pytest -q
PATCHES: L2c→L2d check+apply OK
1213 passed, 26 skipped in 124.68s   (0 failed)
```

```
$ NEUMANN_LLM_PROVIDER=mock python scripts/verify.py --security
보안: 파일 410개
verify 통과
$ NEUMANN_LLM_PROVIDER=mock python scripts/verify.py
1213 passed, 26 skipped in 121.67s
보안: 파일 410개 / 계약: 2개 / 테스트: 통과 / verify 통과
```

남은 위험(병합을 막지 않음, 검증 참고): **합류했지만 끝나지 않은 작업**은 원래 분석이 끝날 때까지(최대 `NEUMANN_JOB_TIMEOUT_S` 900초) 저장소 자리를 잡는다. 대책(후속): 공개 운영에서 `NEUMANN_JOB_TIMEOUT_S`를 분석 시간의 2~3배(예 240초)로 낮추고, 합류 작업에는 따로 짧은 대기 상한(예: 원래 분석의 남은 예상 시간 + 60초)을 둬 넘으면 "잠시 뒤 같은 계획서로 다시" 문구로 끝낸다.

## 재작업 3(E4-L2d 재검증 PASS-조건부 대응, 소유 범위) + PM 결정 ①(단계 보고)

근거: main 체크아웃 `docs/reports/E4-L2d.verify.md` "재검증 (d44df68)". 필수 1번(이메일 정규식 O(n²), `models.py`)은 PM의 SEC-4가 맡아 **하지 않았다.** 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `git stash` 안 씀.

| # | 지시 | 한 일 | 테스트(`tests/e4/test_jobs_limits.py`) |
|---|---|---|---|
| 2 | 여러 IP로 저장소 채우기 | 합류·캐시 적중으로 만든 작업(`shared`: 미들웨어가 자리를 안 잡은 요청, 끝날 때 `cache=="hit"` 또는 `queue=="joined"`로 다시 판정)은 **TTL 60초**(`NEUMANN_JOB_SHARED_TTL_S`), **IP별 활성 수 계산에서 제외**. `NEUMANN_JOB_MAX` 기본 **500**. 저장소가 차면 `/queue/status`가 **`accepting:false`**(serving `accept_checks`에 작업 저장소 `has_room` 등록) | `test_shared_jobs_short_ttl_and_not_counted_per_ip`(같은 IP 5명이 같은 예시 → 5건 모두 202, 새 분석은 따로 3건까지, 합류 4건 `expires_in_s` 60·61초 뒤 404, 새 분석 3건은 900·그대로 200), `test_full_store_shows_accepting_false_in_queue_status`(가득 → false·새 POST 503, TTL 지나면 true). 합류 홍수 테스트는 기대값을 바꿨다: 한 IP 230번 → 202 6건(분당 6 속도 제한이 막음)·분석 1회 |
| 3 | 접근 로그 마스킹 | 경로(대소문자·겹 슬래시·`%2F`)와 쿼리(`?job=`·`?job_id=`·`?id=`·`?ticket=`), 접근 로그에서는 URL-safe 32자 이상 토큰 전부를 앞 6자 + "…"로. 두 번 걸려도 같은 결과(`……` 없음) | `test_access_log_masks_query_and_path_variants_idempotently`(변형 8종 × 필터 두 번) |
| 행사 | 권장 기동값 | 보고서(아래)와 `scripts/serve.py --help` 끝에 적었다. **기본값은 그대로** | `serve.py --help` 출력 확인 |
| PM ① | 단계 보고(E3-L1y `on_stage(name, state, seconds)`) | `state=="running"`일 때만 현재 단계(아직 안 끝난 단계 중 **마지막에 시작한 것**), 끝 보고는 완료 목록(`stages_done`: 이름·이름표·상태·초)에만. 병렬 구간에서 끝난 단계가 현재로 남지 않는다. 새 실행(진행 중 분석이 없을 때) 시작 때 기록 초기화. 이름표 추가: fitness 적합성 판정, expected_review 예상 심사평, checklist 체크리스트, semantic_validate 2차 검증. `on_stage` 인자가 없는 옛 파이프라인은 전처럼 queued/running(또는 `report_stage`). 화면: 6단계 목록에 없는 단계는 ANALYZE 줄에 서버 이름표로 보인다 | `test_on_stage_running_and_end_reports_with_parallel_stages`(보고 8건 순서대로: 현재 단계 fitness → running → expected_review → checklist → expected_review → semantic_validate → expected_review → running, 끝난 목록 4건·상태·초·이름표). 옛 모양 `test_stage_from_on_stage_kwarg…`(인자 하나)·`report_stage` 가짜 파이프라인도 통과 |

### 행사용 권장 기동값(공개 프로필 위에 환경변수로만, E4-L2e 부하 시험 권장)

| 키 | 권장(행사) | 기본(공개) |
|---|---|---|
| `NEUMANN_JOB_PER_IP` | 10 | 3 |
| `NEUMANN_JOB_RATE_PER_MIN` | 30 | 6 |
| `NEUMANN_RATE_PER_MIN` | 30 | 6 |
| `NEUMANN_JOB_POLL_PER_MIN` | 1200 | 600 |
| `NEUMANN_MAX_CONCURRENT` | 6 | 4 |

같은 와이파이 인원이 10명을 넘으면 앞 네 값을 인원의 2~3배로(검증 보고: 25명이면 `PER_IP=25`, 두 속도 값 60, 폴링 1800, `NEUMANN_PREPARSE_PER_MIN=120`). 행사가 끝나면 환경변수를 지워 기본값으로 되돌린다.

### 측정

```
$ NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4 -q
294 passed, 5 skipped
$ git archive HEAD → E4-L2c_main.patch → E4-L2d_main.patch (둘 다 git apply --check 통과) → pytest -q
PATCHES: L2c→L2d check+apply OK
1211 passed, 26 skipped in 117.84s   (0 failed)
$ NEUMANN_LLM_PROVIDER=mock python scripts/verify.py
1211 passed, 26 skipped in 115.65s
보안: 파일 410개 / 계약: 2개 / 테스트: 통과 / verify 통과
$ python tests/e4/test_jobs_live.py ui --port 8137 --run-s 12   # 화면 재시험
정상 흐름 콘솔 오류·페이지 오류·실패한 요청 0건, 판정 PASS
```

### 남은 것

- 이메일 정규식(최대 허용 페이로드 반복 시 이벤트 루프 정지)은 SEC-4 몫이다. 그 전에는 공개 창구에 "정지 없음"이라 말할 수 없다(검증 보고 필수 1).
- 여러 IP가 **새 분석**으로 저장소를 채우는 경우는 IP별 3건·분당 6건·대기열 30이 막는다(합류·캐시는 60초 뒤 비워진다). 다른 IP의 끝난 결과는 여전히 밀어내지 않는다.

## 재작업 2(E4-L2c 재검증 PASS-조건부 대응, 이 브랜치가 L2c를 포함)

근거: main 체크아웃 `docs/reports/E4-L2c.verify.md` "재검증 (83754ff)". 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `git stash` 안 씀.

| # | 지시 | 한 일 | 확인 |
|---|---|---|---|
| 1 | 최신 main 병합(E4-L1f 포함), 업로드 4xx 본문 | `git merge main`(충돌 없음, `2b305d3`). serving `_finish`가 4xx 본문에 `request_id`를 덧붙이던 것을 **업로드 경로에서는 하지 않는다**(앱 본문 모양 그대로, 요청 번호는 `X-Neumann-Ticket` 헤더). 분석 경로 4xx는 그대로 본문에도 싣는다. E4-L1f 테스트 파일은 안 고침 | `test_upload_4xx_body_is_the_apps_own_shape`(hwp 415 본문이 정확히 `{"detail": HWP_MESSAGE}`), 패치 적용 사본의 `tests/e4/test_webui_upload.py` 전부 통과(아래) |
| 2 | `scripts/serve.py` cp949 | `main()` 첫머리에서 stdout·stderr를 `reconfigure(encoding="utf-8", errors="replace")` | `test_serve_py_survives_cp949_redirected_stdout`(`PYTHONIOENCODING=cp949`로 파일에 돌려 `--public --dry-run` → 종료 코드 2·문구 기록). 고치기 전 판은 같은 조건에서 `UnicodeEncodeError`, 종료 코드 1(직접 재현) |
| 3 | 본문 파싱 전 IP별 사전 속도 검사 | 분석 경로(`/premortem`·`/premortem/view`·`/premortem/jobs`) POST는 **본문을 읽기 전에** IP(/64)별 `NEUMANN_PREPARSE_PER_MIN`(공개 60, 개발 끔) 검사 → 넘으면 429. 그다음 바이트 상한 → 파싱 → 글자 상한 → 긴 토큰 422 → `plan_key`(스레드) → 관문 | `test_preparse_rate_limit_runs_before_body_parse_and_hash`(상한 3: 네 번째는 잘못된 JSON 4만 바이트여도 429, `plan_key` 호출 수 그대로, 다른 IP는 202) |
| 4 | slowloris(참고) | 구현 안 함. 아래 "남은 위험" | — |

검증 보고의 재현(프로세스 안, 차단 스위치 ON, 서로 다른 IP 8건 동시 `"a"*49000`, jobs·/view 반반):

```
8건 동시(차단 ON, 'a'*49000): [(422, 'long_token')] 전체 0.313s
/health 20회 최장 16.0ms, 중앙 0.0ms          (검증 보고: 13.9초·/health 최대 10.5초)
(참고) 상한 경계 20,000자 한 토큰 plan_key 0.281s   (스레드에서 계산)
```

패치 적용 순서·확인(HEAD `git archive` 사본): `E4-L2c_main.patch` → `E4-L2d_main.patch` 둘 다 `git apply --check` 통과 후 적용. 패치 파일은 바뀌지 않았다.

```
$ git archive HEAD → git apply --check/apply E4-L2c_main.patch → E4-L2d_main.patch
PATCHES: L2c→L2d check+apply OK
$ NEUMANN_LLM_PROVIDER=mock python -m pytest -q        # 패치 적용 사본, 최신 main(E4-L1f 포함)
1207 passed, 26 skipped in 100.34s          (0 failed: test_webui_upload.py의 hwp·hwpx 415 포함)
```

```
$ NEUMANN_LLM_PROVIDER=mock python scripts/verify.py   # worktree
1207 passed, 26 skipped in 97.70s
보안: 파일 410개
계약: 2개
테스트: 통과
verify 통과
```

### 남은 위험(재작업 2 기준)

- **본문 읽기 시간 제한 없음(slowloris)**: 미들웨어가 본문을 끝까지 받을 때까지 기다린다. 반쯤 보낸 연결을 오래 붙잡아도 서버가 끊지 않는다(게이트 자리는 쓰지 않고 `/health`도 정상, 검증 실측). cloudflared·Cloudflare 엣지가 요청을 모아 보내므로 공개 경로에서는 완화되지만, 서버가 127.0.0.1에만 바인딩돼 있어야 한다. 필요하면 미들웨어 수신 루프에 `asyncio.wait_for(receive(), 본문 시간 상한)`을 넣는다.
- **이메일 정규식**: 토큰 상한(2만 자) 경계에서 `plan_key`가 약 0.28초(스레드)다. 4만~5만 자 안에 2만 자 토큰 두 개를 넣으면 요청 하나에 약 0.5초 CPU를 쓴다. 사전 속도 검사(분당 60/IP)가 상한을 두지만 IP를 바꾸는 공격은 못 막는다. 근본 수정은 SEC-4(선형 email_spans).
- 큰 IPv6 대역(/56·/48)을 가진 공격자는 /64 통을 여러 개 쓴다. 실제 상한은 게이트 처리량이다(검증 권고 3).

## 재작업(검증 PASS-조건부 대응 · 대표 지시 "여러 명이 동시에" · PM 조정)

검증 보고서 `docs/reports/E4-L2d.verify.md`(main 체크아웃)의 고칠 것 1~3·권고 4·5와 이후 지시 두 건을 반영했다. 모든 명령은 `NEUMANN_LLM_PROVIDER=mock`, 실제 OpenAI·bge-m3 호출 0회, `git stash` 안 씀.

| # | 지시 | 한 일 | 테스트(`tests/e4/test_jobs_limits.py`) |
|---|---|---|---|
| 1 | `git merge task/E4-L2c`(83754ff) | 병합 커밋 `33a8351`. 충돌은 `serving.py`의 `__all__` 한 곳(양쪽 합침). L2c가 `_admit_new_analysis`를 없애고 `run()` 재검사(`AdmissionRefused`)를 넣었으므로 내 옛 훅 `admit_new_analysis`를 지우고, 작업은 `run()`의 거절을 받아 사용자 문구로 끝낸다 | — |
| 1 | `create_job` 글자 상한 | 핸들러가 `len(plan_text) > max_plan_chars`면 직접 413(미들웨어와 이중). 공백 없는 긴 토큰도 직접 422 | `test_create_job_checks_char_limit_itself`(12만 자 → 413, 작업 0건) |
| 1 | BOM 본문 테스트 | UTF-8 BOM·UTF-16·UTF-16-LE·UTF-32 본문으로 jobs·/view 각각: 정상 202/200, 차단 스위치 503, 글자 상한 413, 거절 때 작업·분석 0건 | `test_bom_and_utf16_bodies_hit_gates_on_jobs_and_view` |
| 2 | 저장소 고갈 | IP(/64)별 보관 작업 상한 `NEUMANN_JOB_PER_IP`(3): 넘으면 **그 IP의** 끝난 작업부터 밀어내고, 모두 진행 중이면 429 `busy_ip`. IP별 작업 POST 속도 제한 `NEUMANN_JOB_RATE_PER_MIN`(공개 6): **합류·캐시 적중 POST 포함** 모든 작업 POST. 전체 상한이 차면 요청한 IP의 끝난 작업만 밀어내고, 없으면 **그 요청을 503**(다른 IP 결과는 밀어내지 않음) | `test_join_flood_from_one_ip_cannot_fill_store_or_block_others`(같은 계획서 230번 → 202 3건·429 227건, 분석 1회, 다른 IP 202), `test_cached_flood_does_not_evict_other_ip_results`(캐시 계획서 300번 → 202 ≤5, 남의 완료 결과 200 유지), `test_full_store_refuses_requester_and_keeps_other_ips_results` |
| 3 | 긴 토큰 서버 정지 | serving 미들웨어: 글자 상한(413) 다음, `plan_key` 전에 `longest_token()`(`str.split`, 선형)으로 공백 없는 토큰이 `NEUMANN_MAX_TOKEN_CHARS`(PM 조정: **20,000**)를 넘으면 422 `long_token`(사용자 문구, 입력을 되돌려 싣지 않음). `plan_key`는 `asyncio.to_thread`, 캐시 적중 복원(`PlanDocument.from_text`)도 스레드, 작업 결과 조립(`build_ui_view`)도 스레드. models.py는 안 고침(근본 수정은 SEC-4) | `test_long_single_token_is_422_at_once_and_health_stays_fast`(20만 자 한 토큰을 jobs·/view·/premortem에 동시에 → 각각 1초 안에 422, 그동안 `/health` 10회 최대 500ms 미만, 파이프라인 0회), `test_normal_plans_templates_and_long_urls_pass_token_check`(정상 예시 3건·템플릿 5종·URL 2천/5천/1만 자·base64 1.6만 자 한 줄 → 모두 202·결과) |
| 4 | 폴링 속도 제한 | `GET /premortem/jobs/{id}` IP별 분당 `NEUMANN_JOB_POLL_PER_MIN`(600, 정상 사용 약 40). 넘으면 429 + Retry-After(결과 없음). 화면은 429면 기다렸다 다시 확인 | `test_poll_rate_limit_per_ip` |
| 5 | 접근 로그 job_id | `RedactingFilter`가 모든 로그(uvicorn 접근 로그 인자 포함)에서 `/premortem/jobs/<id>`를 앞 6자 + "…"로 바꾼다. 인자 구조 유지 | `test_access_log_masks_job_id` |
| 대표 | 다중 사용자 공개 기본값 | 공개 프로필: 동시 분석 `NEUMANN_MAX_CONCURRENT` **4**, 대기열 `NEUMANN_QUEUE_MAX` **30**(작업 방식), 동기 경로(/premortem·/view) 입장 대기 상한 `NEUMANN_SYNC_QUEUE_MAX` **4**(대기가 4 이상이면 동기 요청은 바로 503, 화면은 jobs), IP당 활성 작업 3, IP당 분석 POST 분당 6(합류·캐시 포함, 남을 밀어내지 않음). 예상 시간은 serving `Gate.eta`가 동시 슬롯 수로 계산한다 | `test_ten_users_four_run_six_wait_all_get_results_and_no_ip_monopoly`(서로 다른 IP 10개 동시 → 실행 4·대기 6, 순번 1~6, 예상 시간 1~4번째 약 60초·5~6번째 약 120초, 전부 결과. 같은 IP 10건 → 2건만 더 받고 429. 대기 8일 때 /view 503·jobs 202) |

- E4-L2c 테스트 `tests/e4/test_serving.py`의 공개 기본값 단정 2줄을 대표 지시값(동시 4·대기 30·동기 대기 4)으로 바꿨다(E4 에픽 테스트, 기본값이 바뀌어 불가피).
- 긴 토큰 순서: 글자 상한(413)을 먼저 본다. 그래서 기본 설정(5만 자)에서 20만 자 한 토큰은 **즉시 413**, 5만 자 이하의 긴 토큰은 **즉시 422**다(L2c 테스트가 글자 상한 우선을 잰다). 테스트는 글자 상한을 30만 자로 올려 20만 자 한 토큰이 즉시 422임을 잰다.
- 남은 위험: 토큰 상한 2만 자에서는 이메일 정규식(O(n²))이 토큰 하나에 약 0.3초(검증 보고 수치로 추정)를 쓸 수 있다. 스레드에서 돌아 `/health`는 응답하지만 GIL을 나눠 쓴다. 근본 수정은 SEC-4(선형 email_spans).

### 권장 설정(공개, 모두 환경변수로 덮어쓰기)

| 키 | 공개 기본 | 개발 기본 | 뜻 |
|---|---|---|---|
| `NEUMANN_MAX_CONCURRENT` | 4 | 2 | 동시 분석(부하 시험 결과로 PM이 조정) |
| `NEUMANN_QUEUE_MAX` | 30 | 20 | 대기 수 상한(작업 방식) |
| `NEUMANN_SYNC_QUEUE_MAX` | 4 | 0(=QUEUE_MAX) | 동기 경로 입장 때 대기 상한 |
| `NEUMANN_RATE_PER_MIN` | 6 | 0 | IP별 새 분석(serving) |
| `NEUMANN_JOB_RATE_PER_MIN` | 6 | 0 | IP별 작업 POST(합류·캐시 적중 포함) |
| `NEUMANN_JOB_PER_IP` | 3 | 3 | IP별 보관(활성) 작업 |
| `NEUMANN_JOB_MAX` | 500 | 500 | 전체 보관 작업(재작업 3에서 200 → 500) |
| `NEUMANN_JOB_SHARED_TTL_S` | 60 | 60 | 합류·캐시 적중 작업 보관 시간(재작업 3) |
| `NEUMANN_JOB_POLL_PER_MIN` | 600 | 600 | IP별 폴링 GET |
| `NEUMANN_JOB_TTL_S` / `NEUMANN_JOB_TIMEOUT_S` / `NEUMANN_JOB_POLL_S` | 900 / 900 / 1.5 | 같음 | 보관·작업 시간 상한·폴링 간격 |
| `NEUMANN_MAX_TOKEN_CHARS` | 20000 | 20000 | 공백 없는 토큰 한 개 상한(422) |
| `NEUMANN_REQUEST_TIMEOUT_S` | 90 | 300 | 동기 경로 시간 상한(L2c) |
| `NEUMANN_PREPARSE_PER_MIN` | 60 | 0 | 본문 파싱 전 IP별 분석 경로 POST(재작업 2) |

- 같은 공유기(행사장 와이파이 NAT)의 여러 사람은 한 IP로 보인다. 그때는 IP당 활성 작업 3·분당 6이 좁을 수 있으니 `NEUMANN_JOB_PER_IP`·`NEUMANN_JOB_RATE_PER_MIN`·`NEUMANN_RATE_PER_MIN`을 올린다.

### 재작업 측정

```
$ NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4/test_jobs_limits.py -q
10 passed
$ NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4 -q
261 passed, 4 skipped
```

실제 서버(포트 8136, `scripts/serve.py`, 가짜 분석 1건 **실제 60초**, 동시 4, 서로 다른 사용자 IP 10개):

```
$ NEUMANN_LLM_PROVIDER=mock python tests/e4/test_jobs_live.py load --port 8136 --run-s 60 --jobs 10 --concurrent 4 --out docs/reports/E4-L2d_loadtest.txt
[+   1.62s]   POST L0: code=202 0.031s job_id=tVWkk2… status=queued position=0 eta_s=0.0 message="곧 분석을 시작합니다"
[+   1.62s]   POST L4: code=202 0.031s job_id=rODxfS… status=queued position=1 eta_s=60.0 message="대기 1번째 · 약 60초"
[+   1.62s]   POST L9: code=202 0.031s job_id=k3FxUn… status=queued position=6 eta_s=120.0 message="대기 6번째 · 약 120초"
[+   3.16s]   queue active=4 waiting=6 avg_run_s=60.0
[+  62.50s]   L3: 결과 받음 status=done 카드 2장 계획서 줄 18줄 대기 0.0s 실행 60.0s 작업 등록→결과 60.9s
[+ 121.70s]   L7: 결과 받음 status=done 카드 2장 계획서 줄 18줄 대기 60.0s 실행 60.0s 작업 등록→결과 120.1s
[+ 182.02s]   L9: 결과 받음 status=done 카드 2장 계획서 줄 18줄 대기 120.0s 실행 60.0s 작업 등록→결과 180.4s
[+ 182.02s] == HTTP 응답 733건(POST 10, GET 723): 가장 긴 응답 0.032s (GET code=200), POST 최장 0.031s, GET 최장 0.032s, 100초 이상 0건
[+ 182.02s] == 결과 받은 작업 10/10건, 등록→결과 시간 60.9s ×4, 120.1s ×4, 180.4s ×2
[+ 190.94s] 판정: PASS
[+ 190.95s] 서버 로그 861줄 중 계획서 본문·트레이스가 든 줄: 0
```

(전체: `docs/reports/E4-L2d_loadtest.txt`. 처음 동시 5건·동시 2 시험 로그는 이 파일로 대체했다. 예상 시간은 동시 4를 반영해 1~4번째 약 60초, 5~6번째 약 120초.)

화면(Playwright, 포트 8137) 재실행: PASS — "대기 1번째 · 약 11초" → "분석 중 · 유사 연구 검색 · 약 7초 남음" → 리포트(카드 2장), 정상 흐름 콘솔 오류 0건, 차단 문구 textContent, 404 폴백(`docs/reports/E4-L2d_ui.txt`, 스크린샷 4장 갱신).

패치 적용 사본(`git archive HEAD` → `E4-L2c_main.patch` → `E4-L2d_main.patch`, 둘 다 `git apply --check` 통과, 패치 파일은 바꿀 필요 없었음) 전체 pytest: `1085 passed, 24 skipped in 127.06s`.

```
$ NEUMANN_LLM_PROVIDER=mock python scripts/verify.py
1085 passed, 24 skipped in 110.91s (0:01:50)
보안: 파일 373개
계약: 2개
테스트: 통과
verify 통과
```

## 무엇을 했나

| 파일 | 내용 |
|---|---|
| `src/neumann/api/jobs.py` (새) | `POST /premortem/jobs`, `GET /premortem/jobs/{id}`, `JobStore`(메모리·TTL·개수 상한), `report_stage()`, `install(app, …)` |
| `src/neumann/api/serving.py` (후속, +50줄) | 작업 실행에 필요한 훅만: `Serving.protect()/kind_for()`(코드가 등록하는 보호 경로, 설정으로 못 뺌), `Serving.admit_new_analysis()`(미들웨어와 같은 입장 관문), `Serving.run(timeout_s=)`, `Gate.ticket_for_plan()`, `scrub_ok_payload()`, 앱이 만든 503 안내(`busy`·`unavailable`)는 문구 유지 |
| `src/neumann/webui/index.html` | **분석 시작·대기 부분만**(`renderJob`·`startAnalysis`·새 `paintJob`, 라우터의 1단계 한 줄). 입력·템플릿·리포트·근거 패널은 안 건드림 |
| `tests/e4/test_jobs.py` (새) | 15건 |
| `tests/e4/test_jobs_live.py` (새) | 가짜 6단계 파이프라인 앱(uvicorn 경로 `tests.e4.test_jobs_live:app`), 실제 서버 시험 `load`·`ui`, pytest 1건(같은 시나리오를 시간 배율로) |
| `docs/reports/E4-L2d_main.patch` | PM이 main.py에 적용(E4-L2c 패치 **다음**) |
| `docs/reports/E4-L2d_loadtest.txt`, `E4-L2d_ui.txt`, `E4-L2d_1~4_*.png` | 완료 기준 시험 출력·스크린샷 |

### API

```
POST /premortem/jobs   {"plan_text": str, "filename"?: str, "format"?: "view"(기본, 화면 모양) | "result"(PremortemResult)}
  → 202 {job_id, status:"queued", position, eta_s, poll_after_s, message, ticket, status_url}
  → 413·429·503: serving과 같은 {status:"error", error_code, message, request_id, retry_after_s?} (작업 안 만듦)
GET  /premortem/jobs/{job_id}
  → 200 {job_id, ticket, status: queued|running|done|error, position, eta_s, stage, stage_label, elapsed_s, message,
         poll_after_s, result(done: ui_view 또는 결과), error_code(error), retry_after_s?, expires_in_s(끝난 뒤)}
  → 404 {status:"error", error_code:"job_not_found", message}  (모르는 id·모양이 틀린 id·보관 시간 지난 id를 구분하지 않음)
```

- `job_id` = `secrets.token_urlsafe(24)`(32자, 192비트). 요청 번호(ticket)·plan_id와 무관하다. 로그에는 앞 6자만 남긴다.
- 응답 헤더 `Cache-Control: no-store`.
- 결과는 **메모리에만**. 끝난 뒤 `NEUMANN_JOB_TTL_S`(기본 900초)가 지나면 버린다(결과 안의 계획서 줄도 같이 사라진다). 개수 상한 `NEUMANN_JOB_MAX`(기본 200)를 넘으면 끝난 것부터 밀어내고, 끝나지 않은 것만으로 가득이면 503 `busy`("지금 보관 중인 분석 작업이 많습니다…"). 이때 잡은 자리·뗀 예산은 돌려준다.
- 진행 단계: 파이프라인이 `on_stage` 키워드를 받으면 콜백을 넘기고, 파이프라인 안에서 `neumann.api.jobs.report_stage(name)`을 부르면(요청 문맥이 스레드로 복사되므로 동기 파이프라인에서도 됨) 그 단계가 `stage`로 보인다. **지금 `neumann.pipeline.run_premortem`은 둘 다 없어서 실서버에서는 queued/running만** 보인다(화면: "분석 중 · 진행 단계 보고 없음"). 가짜 파이프라인은 `report_stage`로 6단계를 알린다.
- 오류: 사용자 문구 + `error_code`(internal·timeout·unavailable·blocked·busy·rate_limited·budget_exhausted)만. 예외 메시지·경로·트레이스·키 없음. 서버 로그에는 예외 **종류**만(`kind=RuntimeError`).
- 시간 상한: 작업 하나 `NEUMANN_JOB_TIMEOUT_S`(기본 900초, 대기+실행). 넘으면 `timeout` 문구. 분석은 끝까지 돌고(슬롯도 그때 반납) 결과 캐시가 켜져 있으면 같은 계획서로 다시 요청할 때 바로 받는다.
- 파이프라인이 없으면(main과 같은 흐름) 샘플 화면(`_status.source="sample"`, 화면에 샘플 표시), import 오류면 `unavailable` 문구.

### 관문(우회 경로 없음)

1. `jobs.install()`이 `POST /premortem/jobs`를 서빙 층의 **분석 보호 경로로 코드 등록**한다(`Serving.protect`). `NEUMANN_PROTECTED_PATHS`에서 빠져 있어도 보호된다(`test_jobs_path_is_gated_even_if_config_omits_it`).
2. 그래서 POST 때 serving 미들웨어가 그대로 적용한다: 본문 바이트 상한(Content-Length → 스트리밍 누적, 파싱 전 413) → 글자 상한(413) → 캐시·합류면 통과 → 차단 스위치(503) → IP 속도 제한(429) → 일일 예산(503) → 대기열(가득이면 503).
3. 핸들러는 미들웨어가 잡은 대기열 자리와 뗀 예산을 **동기적으로** 작업 문맥으로 넘긴다(미들웨어의 finally가 돌려주지 않게). 실행은 `Serving.run`(캐시 → 같은 계획서 합류 → 동시 상한·대기열)이 한다.
4. 요청 문맥(미들웨어)이 없으면 핸들러가 503 `unavailable`로 거절한다. 서빙 층이 안 붙은 앱에는 `install()`이 라우트를 붙이지 않는다(→ 화면은 404를 받고 `/premortem/view`로 폴백, 그 경로도 serving 관문).
5. 입장 때 캐시·합류라 자리 없이 들어왔는데 작업이 시작할 때 캐시·진행 중 분석이 사라졌으면 같은 관문을 **다시** 거친다(확인부터 대기열 등록까지 await가 없어 끼어들 틈 없음). `test_readmission_when_join_or_cache_vanished`.
6. `GET /premortem/jobs/{id}`는 메모리 조회뿐이라 관문이 없다(아래 "못 한 것": 폴링 속도 제한).

### 화면(index.html 분석 시작·대기 부분)

- 시작 → `POST premortem/jobs` → `poll_after_s`(1~2초로 자름)마다 `GET premortem/jobs/{id}`.
- 대기: "대기 N번째 · 약 M초"(순번 0이면 "곧 분석을 시작합니다"), 상태 글자 `queued`. 실행: 단계 타임라인(NORMALIZE → QUERIES → SEARCH → EXTRACT → SYNTHESIZE → VERIFY, 현재 단계 붉은 점) + "분석 중 · 유사 연구 검색 · 약 N초 남음". 단계 보고가 없으면 "분석 중 · 진행 단계 보고 없음".
- 503·429·413·예산·차단·작업 오류·404(보관 시간 지남): 서버 `message`를 오류 상자에 **textContent**로(`#jobErrLabel`·`#jobErrMsg`). innerHTML에 서버 문자열을 넣지 않는다. 대기 문구(`#jobWait`)도 textContent.
- 결과가 오면 기존 흐름 그대로(`D = view` → 0.7초 뒤 리포트, 기존 렌더 함수).
- `POST premortem/jobs`가 404·405면 기존 `POST premortem/view`로 폴백(작업 API가 없는 서버, E6 정적 판의 fetch 가로채기도 `premortem/*`를 404로 주므로 정적 판도 폴백으로 그대로 돈다).
- 폴링 중 네트워크 실패는 2초 간격으로 5번까지 다시 시도. "새 분석"·"다시 시도"로 작업이 바뀌면 이전 폴링은 멈춘다(`S.job.run` 토큰).

## PM이 main.py에 붙일 코드 — 적용 순서: E4-L2c 패치 → E4-L2d 패치

```bash
git apply docs/reports/E4-L2c_main.patch   # serving.install(app), wrap_pipeline, 세마포어 제거
git apply docs/reports/E4-L2d_main.patch   # 파일 끝: jobs.install(...)
```

```python
# main.py 끝(E4-L2d)
from neumann.api import jobs  # noqa: E402

jobs.install(app, load_pipeline=lambda: _load_pipeline(), sample_result=lambda reason: _sample_result(reason))
```

- lambda로 넘기는 이유: 테스트·가짜 앱이 `main._load_pipeline`을 바꿔 끼워도 작업 API가 그걸 쓰게.
- 확인(스크래치 사본: `git archive HEAD` → 두 패치 차례로 `git apply --check` 후 적용 → 전체 pytest): `930 passed, 21 skipped in 75.82s`.
- `/premortem`·`/premortem/view`(동기)는 그대로 동작한다(`test_result_format_option_and_sync_endpoints_still_work`, 기존 test_e4_api·test_serving 통과).

## 새 설정 키(jobs.py가 환경변수로 읽음. `.env.example`은 PM 소유라 안 고침)

| 키 | 기본 | 뜻 |
|---|---|---|
| `NEUMANN_JOB_TTL_S` | 900 | 끝난 작업 결과 보관 시간(초) |
| `NEUMANN_JOB_MAX` | 200 | 메모리에 두는 작업 수 상한 |
| `NEUMANN_JOB_TIMEOUT_S` | 900 | 작업 하나 시간 상한(대기+실행) |
| `NEUMANN_JOB_POLL_S` | 1.5 | 화면에 권하는 폴링 간격(1~2로 자름) |

시험 전용: `NEUMANN_FAKE_RUN_S`(tests/e4/test_jobs_live.py 앱).

## 완료 기준별 측정

### 1) 테스트 — 16 passed

```
$ python -m pytest tests/e4/test_jobs.py tests/e4/test_jobs_live.py -q -rA
tests/e4/test_jobs.py::test_post_returns_immediately_then_result_arrives        # POST < 1초, 폴링 중 단계 보임, 결과=ui_view
tests/e4/test_jobs.py::test_result_format_option_and_sync_endpoints_still_work  # format=result, /premortem·/premortem/view 호환, 빈 입력 422
tests/e4/test_jobs.py::test_queue_position_decreases_while_polling              # 순번 3→2→1→running, "대기 N번째 · 약 "
tests/e4/test_jobs.py::test_stage_from_on_stage_kwarg_and_same_plan_runs_once   # on_stage 콜백, 같은 계획서 2건 → 1회 실행
tests/e4/test_jobs.py::test_gates_apply_to_jobs_block_budget_rate_body          # 차단 파일 503, 바이트·글자 413, 예산 503, 분당 3건 429
tests/e4/test_jobs.py::test_queue_full_and_block_env_refuse_jobs                # 대기열 가득 503, NEUMANN_BLOCK_NEW 503
tests/e4/test_jobs.py::test_jobs_path_is_gated_even_if_config_omits_it          # 보호 경로 설정에서 빠져도 관문
tests/e4/test_jobs.py::test_jobs_without_serving_middleware_is_refused          # 서빙 층 없으면 안 붙음·억지로 붙여도 503, 파이프라인 0회
tests/e4/test_jobs.py::test_readmission_when_join_or_cache_vanished             # 자리 없이 시작하면 관문 다시(차단·대기열 가득)
tests/e4/test_jobs.py::test_store_full_503_returns_slot_and_budget              # 보관 상한 503, 자리·예산 반환, 끝난 작업 밀어냄
tests/e4/test_jobs.py::test_error_is_user_message_only                          # 스택·경로·키·본문·예외 메시지 없음(응답·로그)
tests/e4/test_jobs.py::test_timeout_is_user_message_then_cache_serves           # 시간 상한 문구, 분석은 끝까지 → 캐시 적중
tests/e4/test_jobs.py::test_pipeline_unavailable_gives_marked_sample            # 파이프라인 없음 → 샘플 표시, 자리 반환
tests/e4/test_jobs.py::test_results_are_discarded_after_ttl                     # TTL 29초 200 → 31초 404, 메모리에서 삭제
tests/e4/test_jobs.py::test_job_ids_are_unguessable_and_not_derived             # 30개 모두 다름·32자, 한 글자 바꾼 id 등 → 같은 404
tests/e4/test_jobs_live.py::test_five_concurrent_jobs_scaled                     # 동시 5건(1건 60초×0.02), 모든 응답 < 1초, 5/5 결과
16 passed in 7.47s
```

가짜 파이프라인만 쓴다(bge-m3·OpenAI 호출 0회).

### 2) 실제 서버 동시 5건(포트 8136, serve.py, 가짜 분석 1건 60초, 동시 상한 2) — PASS

(첫 제출 때 측정. 로그 파일 `E4-L2d_loadtest.txt`는 재작업 뒤 동시 10건·동시 4 시험으로 바뀌었다 — 위 "재작업" 절)

```
$ python tests/e4/test_jobs_live.py load --port 8136 --run-s 60 --jobs 5 --out docs/reports/E4-L2d_loadtest.txt
[+   1.55s] health 정상까지 1.5s (serve.py --app tests.e4.test_jobs_live:app --port 8136)
[+   1.77s]   POST L0: code=202 0.032s job_id=QGMfel… status=queued position=0 eta_s=0.0 message="곧 분석을 시작합니다"
[+   1.77s]   POST L2: code=202 0.016s job_id=wDVhPT… status=queued position=1 eta_s=60.0 message="대기 1번째 · 약 60초"
[+   1.77s]   POST L4: code=202 0.016s job_id=JSqhof… status=queued position=3 eta_s=120.0 message="대기 3번째 · 약 120초"
[+   3.28s]   L0: running pos=0 stage=plan_normalize eta_s=58.5 … message="분석 중 · 계획서 정리 · 약 58초 남음"
[+   3.28s]   queue active=2 waiting=3 avg_run_s=60.0
[+  62.33s]   L0: 결과 받음 status=done 카드 2장 계획서 줄 18줄 대기 0.0s 실행 60.0s 작업 등록→결과 60.6s
[+  62.33s]   L4: queued  pos=1 stage=queued eta_s=59.4 elapsed_s=60.6 message="대기 1번째 · 약 59초"
[+ 122.78s]   L3: 결과 받음 status=done 카드 2장 계획서 줄 18줄 대기 60.0s 실행 60.0s 작업 등록→결과 121.1s
[+ 181.97s]   L4: 결과 받음 status=done 카드 2장 계획서 줄 18줄 대기 120.0s 실행 60.2s 작업 등록→결과 180.2s
[+ 181.97s] == HTTP 응답 373건(POST 5, GET 368): 가장 긴 응답 0.078s (GET code=200), POST 최장 0.032s, GET 최장 0.078s, 100초 이상 0건
[+ 181.97s]    응답 코드: {"202": 5, "200": 368}
[+ 181.97s] == 결과 받은 작업 5/5건, 등록→결과 시간 60.6s, 60.6s, 121.1s, 121.1s, 180.2s
[+ 181.97s]    (동기 방식이었다면 마지막 건은 HTTP 응답 하나가 180s 걸려 Cloudflare 약 100초 상한에 끊긴다)
[+ 201.50s] 서버 종료 확인(포트 8136 닫힘)
[+ 201.50s] 판정: PASS
   … INFO neumann.jobs job JSqhof ticket=15397af4f580456b ip_32c6d30162 plan_id=c1287fb9047c chars=669 status=done cache=off queue=queued pos=3 waited_s=120.0 run_s=60.2 total_s=180.2
[+ 201.52s] 서버 로그 491줄 중 계획서 본문·트레이스가 든 줄: 0
```

- 전체 출력(순번 3→1→실행, 단계 6개 진행, 20초마다 대기열 요약, 서버 로그): `docs/reports/E4-L2d_loadtest.txt`.
- 서버 설정: 공개 프로필은 아님(serve.py `--public`은 openai·키가 없으면 기동 거부) — 대신 속도 제한 분당 6건·일일 예산 100건을 환경변수로 켜고 돌렸다. 예산·차단 파일은 임시 폴더(시험 뒤 삭제), 공유 `data/`에는 쓰지 않았다. 시험 뒤 8136 포트·프로세스 없음 확인.

### 3) 화면(Playwright, 포트 8137, 가짜 분석 1건 12초, 동시 상한 1) — PASS, 정상 흐름 콘솔 오류 0

```
$ python tests/e4/test_jobs_live.py ui --port 8137 --run-s 12 --out docs/reports --log docs/reports/E4-L2d_ui.txt
[+   2.20s] 앞선 작업(API): code=202 status=queued position=0
[+   3.23s] 화면 대기 표시: "대기 1번째 · 약 11초" · 상태 queued → E4-L2d_1_queued.png
[+  19.38s] 화면 진행 표시: "분석 중 · 유사 연구 검색 · 약 7초 남음" · 현재 단계 "유사 연구 검색" → E4-L2d_2_running.png
[+  27.95s] 결과 렌더: 리포트 화면, 위험카드 2장 → E4-L2d_3_report.png
[+  27.95s] 정상 흐름(입력→대기→진행→결과) 콘솔 오류·페이지 오류·실패한 요청: 0건 []
[+  28.27s] 차단 스위치 문구: [새 분석 일시 중지] "지금은 새 분석을 잠시 멈췄습니다. 이미 분석된 계획서와 예시 결과는 계속 볼 수 있습니다." → E4-L2d_4_blocked.png
[+  41.33s] 작업 API 404 → 폴백 요청: ['premortem/jobs', 'premortem/view'] → 리포트 렌더 2장
[+  41.41s] 차단·폴백 단계 콘솔 기록 2건(503·404 자원 로드 알림), 그 밖의 오류 0건 []
[+  45.38s] 서버 종료 확인(포트 8137 닫힘)
[+  45.38s] 판정: PASS
```

- 차단·폴백 단계의 2건은 일부러 낸 503·404에 브라우저가 적는 "Failed to load resource" 알림이다(스크립트가 그 문구만 허용하고 나머지는 실패로 센다).
- 스크린샷: `E4-L2d_1_queued.png`(대기 1번째), `E4-L2d_2_running.png`(단계 타임라인), `E4-L2d_3_report.png`(기존 렌더 함수로 리포트), `E4-L2d_4_blocked.png`(서버 사용자 문구).

### 4) `python scripts/verify.py` — 통과

```
$ python scripts/verify.py
931 passed, 21 skipped in 77.07s (0:01:17)
보안: 파일 326개
계약: 2개
테스트: 통과
verify 통과
```

## 결정(스펙이 모호하거나 고른 것)

- **작업 경로 보호를 설정이 아니라 코드로 등록**: `DEFAULT_PROTECTED`에 넣으면 E4-L2c 테스트(기본 보호 경로 4개를 잰다)를 고쳐야 하고, 운영자가 `NEUMANN_PROTECTED_PATHS`를 바꾸면 빠질 수 있다. `Serving.protect()`로 등록하고 설정보다 우선하게 했다.
- **"예산 0"은 예산 소진으로 해석**: serving에서 `NEUMANN_DAILY_BUDGET=0`은 "끔"이라, 한도 2건을 다 쓴 뒤 503을 잰다.
- **POST 응답 `status`는 항상 `queued`**(스펙대로). 빈 슬롯이면 `position=0`, 문구 "곧 분석을 시작합니다".
- **대기 순번은 계획서의 대기열 자리로 계산**(같은 계획서에 합류한 작업은 같은 순번). `eta_s`는 serving `Gate.eta`(실측 평균 EMA).
- **앱이 만든 503 문구 유지**: serving 미들웨어는 5xx 본문을 "처리 중 문제" 문구로 바꾼다. 보관 상한 503은 사용자 안내라 `error_code`가 `busy`·`unavailable`인 앱 503만 문구를 둔다(키·경로 가리기는 그대로).
- **결과 보관 TTL 900초**: 화면은 끝나자마자 받아 간다. 계획서 줄을 담은 결과를 오래 들고 있지 않게 짧게 뒀다.
- **GET 404는 모르는 id·보관 시간 지남·모양 틀림을 구분하지 않는다**(존재 여부를 흘리지 않게).
- **단계 이름 짧은 표기**(화면 왼쪽 열 폭 110px): NORMALIZE·QUERIES·SEARCH·EXTRACT·SYNTHESIZE·VERIFY.
- 실제 서버 시험은 1건 **실제 60초**로 돌렸다(배율 없이 약 3분). pytest는 배율 0.02.
- 가짜 앱·시험 도구는 소유 범위(`tests/e4/test_jobs*.py`) 안에 두었다(`scripts/serve*.py`는 이번 소유가 아님). `scripts/serve_fake_app.py`의 `integrate`·`fake_result`는 가져다 쓰기만 했다.

## 못 한 것

- 실제 파이프라인의 진행 단계: `neumann.pipeline`(E3 소유)이 `on_stage`도 `report_stage`도 부르지 않아 실서버 화면은 queued/running만 보인다(아래 제안 1).
- `GET /premortem/jobs/{id}` 폴링 속도 제한: 메모리 조회뿐이고 id를 추측할 수 없어 넣지 않았다. 공개 중 남용이 보이면 IP별 넉넉한 상한(예: 분당 120)을 serving 보조 속도 제한으로 붙일 수 있다.
- 작업 취소(DELETE) 없음. 화면을 떠나도 분석은 끝까지 돌고 TTL 뒤 버려진다.
- 실제 cloudflared 터널 뒤 실측(524가 안 나는지)은 하지 않았다(지시대로 로컬 가짜 파이프라인).
- `.env.example`에 새 키 4개 추가(PM 소유).

## 제안(다음 과제·PM)

1. **E3(pipeline)**: `_Run.stage()` 진입 때 `neumann.api.jobs.report_stage(name)`을 부르거나(`try: from neumann.api.jobs import report_stage` 선택 import) `run_premortem(..., on_stage=None)` 키워드를 받아 단계마다 부르면 화면에 단계가 바로 보인다(API·화면은 이미 준비됨).
2. **공개 운영**: 동기 경로(`/premortem/view`) 폴백도 터널 상한을 넘지 않게 `NEUMANN_REQUEST_TIMEOUT_S=90` 권장. 새 화면은 작업 API를 쓰므로 영향 없다.
3. **E6 정적 판**: 지금 가로채기가 `premortem/jobs`를 404로 주고 화면이 `/premortem/view`로 폴백해 그대로 돈다. 폴백 없이 쓰려면 가로채기에 `POST premortem/jobs → {job_id}`·`GET premortem/jobs/{id} → {status:"done", result}`를 넣으면 된다.
4. 작업 수·대기열을 `/queue/status`에 합쳐 보이려면 `app.state.jobs.summary()`를 쓰면 된다(이번에는 main.py·queue 응답 모양을 바꾸지 않으려고 넣지 않음).

## 다음 과제에 넘길 것

- worker 1개 전제(작업·대기열 상태가 프로세스 메모리). 서버를 다시 띄우면 진행 중·보관 중 작업은 사라지고 화면은 404 "작업을 찾을 수 없습니다…"를 띄운다(다시 누르면 새로 분석).
- 폴링 1회는 수 밀리초(실측 최장 0.078s). 작업 1건 폴링 약 40회/분.
