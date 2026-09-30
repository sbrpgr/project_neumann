# E4-L2c 보고서 — 공개 라이브 서버 안정성(대기열·속도 제한·캐시·예열·감시) + SEC-1 대응

> **재작업 반영(검증 FAIL 대응, 2026-09-30 20:05).** 맨 아래 "재작업(FAIL 대응)" 절이 최신이다. 그 절이 이 위 내용과
> 다르면 그 절을 따른다(공개 기본값: 요청 시간 90초·대기 4·일일 예산 끔·XFF 무시, 업로드 IP별 상한 추가, 내보내기 예산 미소모).

- 빌더: Claude Opus 5.5 · 검증 예정: Claude Sonnet 5.5 · 브랜치 `task/E4-L2c`(작업 중 `main` 병합 1회)
- 추가 지시 반영: SEC-1 보안 점검 결과(S-01~S-06), PM 결정 19:20(내보내기는 결과만·업로드도 관문·디스크 캐시는 데모만), 화면 고지 "이 서버는 계획서 본문을 파일로 저장하지 않습니다."

## 무엇을 했나

| 파일 | 내용 |
|---|---|
| `src/neumann/api/serving.py` (새 파일) | 서빙 층 전부. `install(app)`, `wrap_pipeline(fn)`, `GET /queue/status`, 미들웨어, 전역 예외 처리기, 로그 필터, 예열 |
| `scripts/serve.py` (새 파일) | uvicorn(worker 1) 실행 + `/health` 감시·자동 재시작(횟수·시각·이유 로그), `--public` 사전 점검 |
| `scripts/serve_fake_app.py` (새 파일) | main.py 라우트 + 서빙 층 + **가짜 느린 파이프라인**(부하·감시 시험용, 실제 분석 안 부름) |
| `scripts/serve_loadtest.py` (새 파일) | 감시 스크립트로 가짜 서버를 8122번에 띄우고 시나리오 A~F를 돌린 뒤 서버를 끈다 |
| `tests/e4/test_serving.py`, `tests/e4/test_serving_sec.py` (새 파일) | 34건 |
| `src/neumann/api/export.py` (PM 위임: `/premortem/package` 한 곳만) | plan_text → 파이프라인 실행 경로(`_run_pipeline`, `_pipeline_unavailable`) 삭제. plan_text만 오면 422 + 사용자 문구 |
| `tests/e4/test_export.py` | 옛 규칙 테스트 3건(plan_text로 파이프라인 실행)을 새 규칙 2건으로 교체 |
| `docs/reports/E4-L2c_main.patch` | PM이 main.py에 적용할 패치(아래와 같음) |
| `docs/reports/E4-L2c_loadtest.txt` | 부하 시험 전체 출력 |

### 동작 요약

- **동시 상한·대기열**: 분석 슬롯 2(설정), 대기 수 상한 20(설정). FIFO. 대기 순번·예상 대기 시간(실행 중 작업의 남은 시간 + 평균 실행 시간 EMA로 슬롯 비는 순서를 흉내)을 `GET /queue/status?ticket=`와 응답(`_status.serving`, 헤더 `X-Neumann-Queue-Position`)으로 준다. 넘치면 503 + 사용자 문구 + `Retry-After`.
- **같은 계획서 합류**: 같은 plan_id가 대기·실행 중이면 새로 돌리지 않고 그 결과를 같이 받는다(심사위원이 같은 데모를 동시에 눌러도 1회만 실행). 합류·캐시 적중은 대기열·속도 제한·예산을 쓰지 않는다.
- **IP 속도 제한**: 공개 프로필에서 분석 분당 6건, 업로드·내보내기(보조) 분당 30건. 넘치면 429 + 사용자 문구 + `Retry-After`. IP는 `CF-Connecting-IP` → `X-Forwarded-For` 첫 값 → client.host. 헤더는 직접 연결 peer가 로컬(터널)일 때만 믿는다(`NEUMANN_TRUST_PROXY`로 켜고 끔).
- **입력 상한**: 본문 바이트 상한을 미들웨어에서 Content-Length와 스트리밍 누적 둘 다로(파싱 전 413). plan_text 50,000자(413, 입력을 되돌려 싣지 않음). 요청 시간 상한 300초(504).
- **시간 상한을 넘겨도** 분석은 끝까지 돌고 슬롯은 그때 반납한다(과부하가 쌓이지 않게). 결과는 캐시에 들어가 같은 계획서로 다시 누르면 즉시 받는다(504 문구가 그렇게 안내).
- **일일 예산**: 새 분석 건수 상한(설정, **기본 끔**: 대표 결정). 입장 때 떼고, 쓰지 않으면(샘플·캐시·합류) 돌려준다. 파일에 남겨 재시작해도 이어진다. 넘치면 503 "오늘 한도" 문구, 캐시 응답은 계속.
- **차단 스위치**: `NEUMANN_BLOCK_NEW=1` 또는 파일 `<data_dir>/serving_block.flag`가 있으면 즉시 새 분석 거부(503), 캐시 응답은 계속. 파일은 요청마다 보므로 재시작 없이 켜고 끈다.
- **결과 캐시(S-06)**: 사용자 입력 결과는 **메모리에만**(TTL 6시간, 64건 LRU). 디스크(`<data_dir>/cache/results/<plan_id>.json`)는 **데모 계획서 3건의 plan_id 허용 목록만**. 메모리·디스크 모두 계획서 줄 텍스트를 뺀 저장본이고, 적중 때 요청 본문으로 줄을 다시 붙인다. `status: ok`만 저장(강등 결과는 다시 돌림), provider·모델·버전이 다르면 다른 결과로 본다.
- **예열**: 서버 시작 때 배경으로 `neumann.pipeline.warmup()` 훅(있으면: 색인·모델 로드) → 데모 3건을 돌려 캐시(디스크)에 채운다. 요청은 바로 받는다. 이미 디스크에 있으면 다시 안 돌린다.
- **오류 문구**: 보호 경로의 4xx·5xx는 사용자 문구 + `error_code`(분류) + `request_id`. 예외 메시지·파일 경로·줄 번호·트레이스·키를 지운다. 화면 모양(ui_view)의 500은 모양을 유지하고 문자열만 바꾼다(실패를 숨기지 않게 예외 **종류** 이름은 "오류 종류: RuntimeError"로 남김). 422는 입력을 되돌려 싣지 않는다. 전역 예외 처리기는 모든 경로에서 분류·요청 id만 싣는다.
- **정상 응답 가림**: 분석 응답의 진단 필드(notices·reason·detail 등)에서 키·절대 경로·상류 API 오류 문구를 가린다("HTTP 401"은 남김). 근거 인용·계획서 줄은 글자 그대로 둔다(인용은 원문과 같아야 하므로).
- **로그**: 요청마다 한 줄 `req ticket=… ip_<해시> path=… mode=… plan_id=<앞 12자> chars=<글자 수> status=… cache=… queue=… pos=… waited_s=… run_s=… total_s=…`. 본문·키·IP 원문 없음. `RedactingFilter`가 모든 로거·핸들러에서 키 모양·실제 키 값을 가리고 트레이스(exc_info)를 "[트레이스 생략: 종류]"로 줄인다(uvicorn 접근 로그 인자 구조는 유지).
- **감시**: `scripts/serve.py`가 자식 uvicorn을 띄우고 주기적으로 `/health`를 본다. 프로세스가 죽거나 health가 연속 실패하면 다시 띄운다(시작 유예 180초: 모델 로드 중 실패는 세지 않음). 재시작 횟수·시각·이유를 표준 출력과 `<data_dir>/logs/serve.log`에 남긴다.

## PM이 main.py에 붙일 코드

`git apply docs/reports/E4-L2c_main.patch`(현재 main.py 기준 `git apply --check` 통과). 세 곳이다.

```python
# 1) app 생성 바로 뒤(app.mount("/fonts", ...) 다음 줄)
from neumann.api import serving  # noqa: E402  E4-L2c 서빙 층(동시 상한·대기열·속도 제한·예산·캐시·오류 문구·로그 위생)

serving.install(app)
```

```python
# 2) _load_pipeline() 마지막 줄
-    return fn, "connected", ""
+    return serving.wrap_pipeline(fn), "connected", ""
```

```python
# 3) _run_pipeline(): 세마포어를 지운다(동시 상한은 serving.Gate가 한다. 남겨 두면 캐시 적중도 세마포어를 기다린다)
-    async with _semaphore():
-        if inspect.iscoroutinefunction(fn):
-            result = await fn(req.plan_text, **kwargs)
-        else:
-            result = await run_in_threadpool(fn, req.plan_text, **kwargs)
+    if inspect.iscoroutinefunction(fn):
+        result = await fn(req.plan_text, **kwargs)
+    else:
+        result = await run_in_threadpool(fn, req.plan_text, **kwargs)
```

- 확인: 이 패치를 적용한 사본(스크래치 폴더)에서 전체 테스트 `476 passed, 19 skipped`(기존 test_e4_api·test_export·업로드·메타 테스트 포함). 기본(비공개) 설정에서는 속도 제한·캐시·예산·예열이 꺼져 있어 기존 테스트에 영향이 없다.
- 공개 운영: `python scripts/serve.py --public` (host 127.0.0.1 유지, 터널은 이 포트를 가리킴). uvicorn을 직접 띄울 때는 `NEUMANN_PUBLIC=1`과 `--workers 1 --no-proxy-headers`를 준다.

## 새 설정 키(serving.py가 환경변수로 읽음. config.py는 바꾸지 않았다)

`공개` 열은 `NEUMANN_PUBLIC=1`일 때 기본값, `개발` 열은 없을 때 기본값.

| 키 | 공개 | 개발 | 뜻 |
|---|---|---|---|
| `NEUMANN_PUBLIC` | 1 | 0 | 공개 프로필(serve.py `--public`이 켬) |
| `NEUMANN_MAX_CONCURRENT` | 2 | 2 | 동시 분석 상한 |
| `NEUMANN_QUEUE_MAX` | **4** | 20 | 대기 수 상한(넘으면 503). 긴 대기는 E4-L2d 비동기 작업이 맡는다 |
| `NEUMANN_RATE_PER_MIN` | 6 | 0(끔) | IP별 분당 새 분석 수 |
| `NEUMANN_MAX_PLAN_CHARS` | 50000 | 50000 | plan_text 글자 상한 |
| `NEUMANN_MAX_BODY_BYTES` | 글자×6+64KB | 같음 | 분석 경로 본문 바이트 상한 |
| `NEUMANN_MAX_EXPORT_BYTES` | 4MB | 4MB | 내보내기·기타 보호 경로 바이트 상한 |
| `NEUMANN_MAX_UPLOAD_BYTES` | 10MB+64KB | 같음 | 업로드 바이트 상한 |
| `NEUMANN_REQUEST_TIMEOUT_S` | **90** | 300 | 분석 요청 시간 상한(대기+실행). Cloudflare 약 100초보다 먼저 JSON 504 |
| `NEUMANN_AVG_RUN_S` | 60 | 60 | 예상 대기 시간 초깃값(실측으로 갱신) |
| `NEUMANN_AUX_CONCURRENT` / `_AUX_QUEUE_MAX` / `_AUX_TIMEOUT_S` | 2 / 10 / 60 | 같음 | 업로드·내보내기 관문 |
| `NEUMANN_AUX_RATE_PER_MIN` | 30 | 0 | 내보내기·기타 보조 경로 IP(/64)별 분당 |
| `NEUMANN_UPLOAD_RATE_PER_MIN` | 10 | 0 | 업로드 전용 IP(/64)별 분당 |
| `NEUMANN_UPLOAD_PER_IP` | 1 | 0(끔) | 업로드 IP(/64)별 동시 처리 상한(느린 파일로 슬롯 독점 방지) |
| `NEUMANN_DAILY_BUDGET` | **0(끔)** | 0(끔) | 전역 일일 새 분석 건수(대표 결정: 기능은 두되 기본 끔) |
| `NEUMANN_BUDGET_FILE` | `<data_dir>/cache/serving_budget.json` | 같음 | 예산 사용량(날짜·건수만) |
| `NEUMANN_BLOCK_NEW` | 0 | 0 | 1이면 새 분석 거부 |
| `NEUMANN_BLOCK_FILE` | `<data_dir>/serving_block.flag` | 같음 | 이 파일이 있으면 새 분석 거부(즉시) |
| `NEUMANN_RESULT_CACHE` | 1 | 0 | 결과 캐시 |
| `NEUMANN_RESULT_CACHE_DIR` | `<data_dir>/cache/results` | 같음 | 디스크 캐시(데모만) |
| `NEUMANN_CACHE_MEM_ITEMS` / `NEUMANN_CACHE_TTL_S` | 64 / 21600 | 같음 | 메모리 캐시 상한 |
| `NEUMANN_DISK_CACHE_ALLOW` | 비움 | 비움 | 디스크 허용 plan_id 추가(`;` 구분). 기본은 데모 3건 |
| `NEUMANN_TRUST_PROXY` | loopback | loopback | 프록시 헤더 신뢰: loopback(로컬 peer일 때만)·always·never |
| `NEUMANN_XFF_PICK` | first | first | X-Forwarded-For에서 첫 값·마지막 값 |
| `NEUMANN_TRUST_XFF` | **0** | 1 | X-Forwarded-For를 믿을지. 공개는 `CF-Connecting-IP`만 믿는다 |
| `NEUMANN_PSEUDONYM_SALT` | (기존 키 재사용) | | 로그 IP 해시(HMAC) 솔트. 없으면 프로세스마다 무작위. 값은 어디에도 쓰지 않는다 |
| `NEUMANN_HIDE_DOCS` | 1 | 0 | /docs·/redoc·/openapi.json 404 |
| `NEUMANN_PROTECTED_PATHS` | 아래 | 같음 | `/premortem=analysis;/premortem/view=analysis;/premortem/package=export;/upload/plan=upload` |
| `NEUMANN_WARMUP` / `NEUMANN_WARMUP_PLANS` | 1 / 데모 3건 | 0 | 시작 예열 |

시험 전용: `NEUMANN_FAKE_RUN_S`, `NEUMANN_FAKE_CRASH`(serve_fake_app), `NEUMANN_LOADTEST_KEEP`(serve_loadtest).

## 화면 "대기 N번째" 반영 방법(UI 담당에게)

1. 분석 요청을 보낼 때 요청 번호를 만들어 헤더로 보낸다. 형식은 `[A-Za-z0-9_-]{6,64}`.
2. 응답을 기다리는 동안 1.5초마다 `GET queue/status?ticket=<번호>`를 부른다. `ticket.state`가
   - `waiting`: "대기 {position}번째 · 약 {eta_s}초"
   - `running`: "분석 중 · 약 {eta_s}초 남음"
   - `done`·`unknown`: 표시하지 않음(응답이 곧 온다)
3. 응답이 오면 폴링을 멈춘다. 응답 코드별:
   - 200: 그대로 그린다. `_status.serving.cache == "hit"`이면 "이전에 분석한 결과"라고 작게 표시한다.
   - 503·429·413: 본문이 ui_view가 아니라 `{status:"error", error_code, message, request_id, retry_after_s?}`다. `message`를 그대로 띄운다(`error_code`: busy·blocked·budget_exhausted·rate_limited·too_large). `Retry-After` 초가 지나면 다시 누를 수 있게 한다.
   - 500·504: ui_view 모양 + `message`·`error_code`·`request_id`. 기존 오류 화면을 쓰고 `message`를 띄운다. 504면 "잠시 뒤 다시 누르면 결과를 바로 받는다"는 안내가 이미 들어 있다.

```js
const ticket = 'tk' + crypto.randomUUID().replace(/-/g, '').slice(0, 14);
let poll = setInterval(() => fetch('queue/status?ticket=' + ticket, { cache: 'no-store' })
  .then(r => r.json()).then(q => {
    const t = q.ticket || {};
    if (t.state === 'waiting') setBusy(`대기 ${t.position}번째 · 약 ${Math.round(t.eta_s)}초`);
    else if (t.state === 'running') setBusy(`분석 중 · 약 ${Math.round(t.eta_s)}초 남음`);
  }).catch(() => {}), 1500);
fetch('premortem/view', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Neumann-Ticket': ticket },
  body: JSON.stringify({ plan_text: S.text, filename: S.filename || null }) })
  .then(r => r.json().then(j => ({ code: r.status, j })))
  .then(({ code, j }) => { clearInterval(poll); if (!j._status) return showError(esc(j.message)); render(j); });
```

(`setBusy`·`showError`·`render`·`esc`는 화면의 기존 함수 이름에 맞춘다. `message`도 `esc()`를 거친다.)

## 완료 기준별 측정

### 1) 테스트(동시 상한·순번, 속도 제한, 캐시 적중, 오류 문구에 내부 정보 없음, 로그에 본문 없음) — 통과

```
$ python -m pytest tests/e4/test_serving.py tests/e4/test_serving_sec.py tests/e4/test_export.py -q -rA
tests/e4/test_serving.py::test_concurrency_cap_and_queue_positions
tests/e4/test_serving.py::test_queue_full_returns_503_with_user_message
tests/e4/test_serving.py::test_same_plan_in_flight_runs_once
tests/e4/test_serving.py::test_rate_limit_per_ip_with_user_message
tests/e4/test_serving.py::test_proxy_headers_trusted_only_from_loopback
tests/e4/test_serving.py::test_input_size_limit_413
tests/e4/test_serving.py::test_user_input_is_cached_in_memory_only_never_on_disk
tests/e4/test_serving.py::test_public_demo_input_goes_to_disk_without_plan_body
tests/e4/test_serving.py::test_disk_allowlist_is_exactly_three_demo_plans
tests/e4/test_serving.py::test_public_profile_user_input_leaves_no_file_in_data_cache_results
tests/e4/test_serving.py::test_memory_cache_ttl_and_size_cap
tests/e4/test_serving.py::test_cache_skips_degraded_and_other_variant
tests/e4/test_serving.py::test_warmup_fills_cache_from_demo_plans
tests/e4/test_serving.py::test_timeout_504_then_cached_result
tests/e4/test_serving.py::test_pipeline_error_is_user_message_without_internals
tests/e4/test_serving.py::test_unexpected_exception_in_app_becomes_500_message
tests/e4/test_serving.py::test_logs_have_plan_id_and_length_but_no_body_key_or_traceback
tests/e4/test_serving.py::test_redacting_filter_hides_real_env_secret
tests/e4/test_serving.py::test_config_defaults_and_public_profile
tests/e4/test_serving_sec.py::test_upload_path_has_concurrency_cap_queue_limit_and_503
tests/e4/test_serving_sec.py::test_upload_time_limit_504_keeps_slot_until_work_ends
tests/e4/test_serving_sec.py::test_upload_rate_limit_is_separate_bucket
tests/e4/test_serving_sec.py::test_body_byte_cap_by_content_length_and_streaming_before_parse
tests/e4/test_serving_sec.py::test_legacy_package_plan_text_uses_analysis_gate_budget_and_block
tests/e4/test_serving_sec.py::test_protected_paths_are_configurable
tests/e4/test_serving_sec.py::test_daily_budget_503_cache_still_served_and_persists
tests/e4/test_serving_sec.py::test_budget_day_rollover_and_join_does_not_spend
tests/e4/test_serving_sec.py::test_block_switch_by_file_and_env_keeps_cache
tests/e4/test_serving_sec.py::test_global_exception_handler_returns_only_code_and_request_id
tests/e4/test_serving_sec.py::test_ok_response_hides_paths_and_upstream_api_text_but_keeps_quotes
tests/e4/test_serving_sec.py::test_docs_hidden_in_public_mode
tests/e4/test_serving_sec.py::test_log_filter_keeps_uvicorn_access_args_and_scrubs_them
tests/e4/test_serving_sec.py::test_serve_public_preflight_refuses_mock_or_missing_key
tests/e4/test_serving_sec.py::test_serve_public_dry_run_exit_code
(test_export.py 26건 생략)
60 passed in 2.99s
```

테스트는 전부 가짜 파이프라인(이벤트로 멈추거나 짧게 자는 함수)으로 돈다. bge-m3·OpenAI 호출 0회.

### 2) 부하 스크립트로 동시 10건 — 대기열 작동 로그(가짜 느린 파이프라인, 포트 8122) — PASS

```
$ python scripts/serve_loadtest.py --port 8122 --out docs/reports/E4-L2c_loadtest.txt
[+  0.02s] 감시 스크립트 시작: serve.py --app scripts.serve_fake_app:app --port 8122 (동시 2, 대기열 8, 분당 6건, 가짜 분석 2.0s)
[+  1.25s] == A 동시 10건(서로 다른 계획서·IP): 동시 10건
[+  2.67s]   queue active=2 waiting=8 eta_new=9.4s | 00:실행 01:실행 02:1번째/1.4s 03:4번째/3.6s 04:7번째/7.4s 05:2번째/1.6s 06:3번째/3.4s 07:5번째/5.4s 08:6번째/5.6s 09:8번째/7.6s
[+  4.23s]   queue active=2 waiting=7 eta_new=7.9s | 01:실행 02:실행 03:3번째/3.0s 04:6번째/5.9s 05:1번째/1.0s 06:2번째/1.9s 07:4번째/3.9s 08:5번째/5.0s 09:7번째/7.0s
[+  6.33s]   queue active=2 waiting=4 eta_new=5.8s | 03:실행 04:3번째/3.8s 06:실행 07:1번째/1.8s 08:2번째/2.0s 09:4번째/4.0s
[+  8.41s]   queue active=2 waiting=2 eta_new=3.7s | 04:1번째/1.7s 07:실행 08:실행 09:2번째/1.9s
[+ 10.48s]   queue active=2 waiting=0 eta_new=1.7s | 04:실행 09:실행
[+ 12.31s]   tk_A_00 code=200 cache=miss 도착순번=0 대기=0.0s 총=2.92s
[+ 12.31s]   tk_A_01 code=200 cache=miss 도착순번=0 대기=0.0s 총=3.0s
[+ 12.31s]   tk_A_02 code=200 cache=miss 도착순번=1 대기=1.6s 총=4.77s
[+ 12.31s]   tk_A_05 code=200 cache=miss 도착순번=2 대기=1.8s 총=4.8s
[+ 12.31s]   tk_A_06 code=200 cache=miss 도착순번=3 대기=3.5s 총=6.56s
[+ 12.31s]   tk_A_03 code=200 cache=miss 도착순번=4 대기=3.7s 총=6.91s
[+ 12.31s]   tk_A_07 code=200 cache=miss 도착순번=5 대기=5.5s 총=8.5s
[+ 12.31s]   tk_A_08 code=200 cache=miss 도착순번=6 대기=5.7s 총=8.64s
[+ 12.31s]   tk_A_04 code=200 cache=miss 도착순번=7 대기=7.5s 총=10.67s
[+ 12.31s]   tk_A_09 code=200 cache=miss 도착순번=8 대기=7.7s 총=10.59s
[+ 12.31s]   요약 A 동시 10건(서로 다른 계획서·IP): {"200": 10} 최장=10.67s
[+ 13.27s]   요약 B 같은 10건 다시(캐시): {"200": 10} 최장=0.52s      (10건 모두 cache=hit)
[+ 23.86s]   tk_C_10 code=503 ... msg="지금 분석 요청이 많아 대기열이 가득 찼습니다. 약 10초 뒤에 다시 시도해 주세요."
[+ 23.86s]   요약 C 동시 12건(대기열 상한 8): {"200": 10, "503": 2} 최장=10.14s
[+ 30.23s]   tk_D_06 code=429 ... msg="요청이 너무 잦습니다. 60초 뒤에 다시 시도해 주세요(분당 6건)."
[+ 30.23s]   요약 D 한 IP에서 7건(분당 6건): {"200": 6, "429": 1} 최장=6.11s
[+ 32.56s]   데모: code=200 cache=miss | 결과 캐시 폴더 파일 1개 (사용자 입력 29건 요청 뒤): ['3d35460def76']
[+ 32.56s]   디스크 파일 중 사용자 입력 본문 조각이 든 파일: 0개
[+ 35.23s]   재시작 뒤 데모 다시: code=200 cache=hit 총=0.23s (디스크 캐시)
[+ 37.41s]   재시작 뒤 사용자 입력 A03 다시: code=200 cache=miss 총=2.17s (메모리 캐시는 재시작으로 비워짐 → 다시 분석)
[+ 37.41s] 판정: PASS
[+ 41.05s] 서버 종료 확인(포트 8122 닫힘)
   [serve] 2026-09-30T19:21:50 재시작 #1 이유: 프로세스 종료(code=3)
   [serve] 2026-09-30T19:21:51 시작 pid=30356 app=scripts.serve_fake_app:app host=127.0.0.1 port=8122 재시작 누적=1
   [serve] 2026-09-30T19:21:52 health 정상 (뜨는 데 1.0s)
   2026-09-30 19:21:22,997 INFO neumann.serving req ticket=tk_A_02 ip_aa4133edd4 path=/premortem/view mode=analysis plan_id=4873609baa5d chars=665 status=200 cache=miss queue=queued pos=1 waited_s=1.6 run_s=2.0 total_s=3.61
[+ 41.08s] 서버 로그 623줄 중 계획서 본문·트레이스가 든 줄: 0
```

- 동시 실행은 항상 2, 나머지 8건은 도착 순서대로 대기 순번 1~8(실제 대기 시간이 순번과 맞게 1.6→7.7초로 는다). A의 도착 순서는 스레드 스케줄링 때문에 보낸 순서와 조금 다르다(서버 도착 순서 기준 FIFO는 지켜진다).
- 전체 출력: `docs/reports/E4-L2c_loadtest.txt`. 결과 캐시·예산·차단 파일·감시 로그는 임시 폴더에 쓰고 지웠다(공유 `data/`에는 쓰지 않았다: 시험 뒤 `data/cache/`에 `results/`·`serving_budget.json` 없음 확인). 8122번 서버는 시험 끝에 종료 확인.

### 3) `python scripts/verify.py` — 통과

```
$ python scripts/verify.py
489 passed, 6 skipped in 17.76s
보안: 파일 204개
계약: 2개
테스트: 통과
verify 통과
```

## SEC-1 대응

| # | 대응 | 테스트 |
|---|---|---|
| S-01 대기 수 상한 | `NEUMANN_QUEUE_MAX`(20). 넘치면 503 + 사용자 문구 + Retry-After, 응답에 대기열 요약 | `test_queue_full_returns_503_with_user_message`, 부하 시험 C |
| S-01 IP 식별(터널) | `CF-Connecting-IP` → XFF 첫 값(`NEUMANN_XFF_PICK=last` 가능) → client.host. 신뢰는 `NEUMANN_TRUST_PROXY`(기본 loopback: 로컬 peer일 때만). serve.py는 uvicorn `--no-proxy-headers`로 IP 판정을 serving 한 곳에 둔다 | `test_proxy_headers_trusted_only_from_loopback`, `test_rate_limit_per_ip_with_user_message`, `test_upload_rate_limit_is_separate_bucket` |
| S-01 전역 일일 예산 | `NEUMANN_DAILY_BUDGET`(공개 200건). 입장 때 떼고 안 쓰면 돌려줌, 파일로 재시작 뒤에도 이어짐, 날짜 바뀌면 0. 넘치면 503, 캐시 응답은 계속 | `test_daily_budget_503_cache_still_served_and_persists`, `test_budget_day_rollover_and_join_does_not_spend` |
| S-01 차단 스위치 | `NEUMANN_BLOCK_NEW=1` 또는 `NEUMANN_BLOCK_FILE`(기본 `<data_dir>/serving_block.flag`) 존재 → 즉시 새 분석 503, 캐시 응답 계속 | `test_block_switch_by_file_and_env_keeps_cache` |
| S-01 본문 바이트 상한 | 미들웨어에서 Content-Length 먼저, 없으면 스트리밍 누적으로 파싱 전 413. 413·422 응답에 입력을 싣지 않음 | `test_body_byte_cap_by_content_length_and_streaming_before_parse`, `test_input_size_limit_413` |
| S-02 보호 경로 | `NEUMANN_PROTECTED_PATHS`(기본 /premortem·/premortem/view·/premortem/package·/upload/plan). 내보내기·업로드는 보조 관문(동시 상한·대기열·시간 상한·IP 속도 제한). 옛 내보내기(plan_text만)는 분석 관문·예산·차단 스위치로 묶는 경로도 둠 | `test_protected_paths_are_configurable`, `test_legacy_package_plan_text_uses_analysis_gate_budget_and_block` |
| S-02 내보내기 plan_text 경로 삭제(PM 결정) | `export.py`의 `/premortem/package`에서 파이프라인 실행 경로 삭제. plan_text만 오면 422 "내보내기에는 분석 결과가 필요합니다…", result가 오면 기존대로 ZIP | `test_api_plan_text_only_is_rejected_without_running_pipeline`, `test_api_result_with_plan_text_still_packages` |
| S-03 업로드 시간·동시 상한 | `/upload/plan`을 보조 관문에: 동시 2·대기 10·시간 60초. 시간을 넘기면 504로 답하되 슬롯은 파싱이 실제로 끝날 때 반납(요청을 거듭 보내 CPU를 쌓지 못하게). 파서 내부 상한은 아래 "제안" | `test_upload_path_has_concurrency_cap_queue_limit_and_503`, `test_upload_time_limit_504_keeps_slot_until_work_ends` |
| S-04 전역 예외 처리기 | `install_exception_handlers`: 처리 안 된 예외 → 500 `{status, error_code:"internal", message(고정 문구), request_id}`만. 422는 입력(input)을 빼고 위치·종류만. 보호 경로 오류는 경로·줄 번호·트레이스·키를 지움. 정상 분석 응답의 진단 필드에서 절대 경로(`C:\Users\…`, `/home/…`)·상류 API 오류 문구(`Incorrect API key provided…`)·키 조각을 가림("HTTP 401"·"IndexNotBuilt" 같은 분류는 남김). 공개 모드는 /docs·/redoc·/openapi.json 404 | `test_global_exception_handler_returns_only_code_and_request_id`, `test_pipeline_error_is_user_message_without_internals`, `test_unexpected_exception_in_app_becomes_500_message`, `test_ok_response_hides_paths_and_upstream_api_text_but_keeps_quotes`, `test_docs_hidden_in_public_mode` |
| S-04 로그 | 키·실제 키 값 가림, 트레이스 생략, 요청 로그는 plan_id·길이·IP 해시만 | `test_logs_have_plan_id_and_length_but_no_body_key_or_traceback`, `test_redacting_filter_hides_real_env_secret`, `test_log_filter_keeps_uvicorn_access_args_and_scrubs_them` |
| S-05 공개 모드 기동 거부 | `serve.py --public`: provider가 openai가 아니거나 `OPENAI_API_KEY`가 없으면(참·거짓만 확인) 기동 거부(종료 코드 2). `--dry-run`으로 점검만 | `test_serve_public_preflight_refuses_mock_or_missing_key`, `test_serve_public_dry_run_exit_code` |
| S-06 캐시에 본문 안 남김 | 사용자 입력 결과는 메모리 캐시만(TTL 6시간·64건). 디스크는 데모 3건 plan_id 허용 목록만(템플릿도 제외). 저장본에는 계획서 줄 텍스트 없음. 화면 고지 "이 서버는 계획서 본문을 파일로 저장하지 않습니다."와 맞다 | `test_user_input_is_cached_in_memory_only_never_on_disk`, `test_public_profile_user_input_leaves_no_file_in_data_cache_results`(공개 기본 설정 그대로 사용자 입력 3건 → `data/cache/results/` 새 파일 0개, 데모만 1개), `test_disk_allowlist_is_exactly_three_demo_plans`, `test_public_demo_input_goes_to_disk_without_plan_body`, `test_memory_cache_ttl_and_size_cap`, 부하 시험 E·F |

## 결정(스펙이 모호하거나 지시가 겹친 곳)

- **공개 프로필 스위치**: 속도 제한·캐시·예산·예열·/docs 숨김은 `NEUMANN_PUBLIC=1`일 때만 기본으로 켠다. main.py에 붙어도 테스트·개발(기존 테스트 전부)이 영향받지 않게 하려는 것이다. 관문·상한·오류 문구·로그 위생은 항상 켜진다. 공개 운영은 `serve.py --public`으로 한다.
- **XFF는 첫 값**(추가 지시). 첫 값은 위조할 수 있지만 cloudflared 뒤에서는 `CF-Connecting-IP`가 먼저 쓰이므로 XFF는 거의 쓰이지 않는다. 필요하면 `NEUMANN_XFF_PICK=last`.
- **업로드·내보내기는 분석과 다른 슬롯(보조 관문)**: "같은 관문"을 같은 장치(동시 상한·대기열·시간 상한·속도 제한)로 해석했다. 같은 슬롯을 쓰면 몇 초짜리 업로드가 몇 분짜리 분석 뒤에 줄을 선다. 예산은 LLM을 부르는 경로만 센다(업로드·결과 내보내기는 LLM 호출 없음).
- **내보내기 plan_text만 → 422**(400이 아니라): 기존 `test_api_rejects_bad_input`이 같은 종류의 거절을 422로 잰다.
- **예외 종류 이름은 남김**: 화면 모양 500의 notices에 "(오류 종류: RuntimeError)"를 남긴다. 예외 메시지·경로·줄 번호는 없다. 실패를 숨기지 않는 규칙과 기존 test_e4_api(종류 이름을 확인)를 지키려는 것이다. 전역 예외 처리기 응답에는 종류 이름도 싣지 않는다.
- **정상 응답은 진단 필드만 가림**: 근거 인용·계획서 줄을 바꾸면 "인용은 원문과 글자 단위로 같다" 규칙이 깨진다.
- **캐시는 status ok만**: API 일시 장애로 규칙 비상 경로가 돈 강등 결과를 오래 붙잡지 않게.
- **예열 대상은 데모 3건**(템플릿 5건은 빈칸이 있는 틀이라 돌리지 않음). 디스크 허용 목록도 데모 3건만(추가 지시).
- **시간 상한을 넘긴 분석은 끝까지 돌린다**: 스레드로 도는 동기 파이프라인은 중간에 못 끊는다. 슬롯을 먼저 풀면 GPU·API 동시 실행이 상한을 넘는다. 대신 결과를 캐시에 넣어 다시 누르면 즉시 받게 했다.
- **요청 번호 길이 6~64자**.

## 못 한 것

- main.py 적용(PM 몫, 패치 제공). `.env.example`에 새 키 이름 추가(루트 파일은 PM 소유, 위 표 참조).
- 화면(`webui/index.html`)의 "대기 N번째" 표시와 503·429 문구 표시(UI 담당, 위 방법·코드 제공).
- 실제 cloudflared 터널 뒤 `CF-Connecting-IP` 실측, 실제 파이프라인(bge-m3·OpenAI)으로 부하 시험(지시대로 가짜 파이프라인만).
- 토큰 기반 예산(`LLMResult.usage` 합계). 지금은 새 분석 건수만 센다.
- 업로드 파서 내부 상한(S-03의 DOCX 압축 해제·추출 글자 수·프로세스 분리).

## 제안(다음 과제·PM)

1. **Cloudflare 응답 시간 상한**: Cloudflare를 거치는 요청은 원 서버 응답을 약 100초까지만 기다리는 것으로 알려져 있다(넘으면 524). 분석이 그보다 길면 `NEUMANN_REQUEST_TIMEOUT_S=90`으로 두고, 화면은 504를 받으면 `queue/status`로 끝났는지 본 뒤 같은 계획서로 다시 요청하게 한다(분석은 계속 돌고 결과는 메모리 캐시에 들어간다). 근본 해결은 작업 id를 돌려주고 폴링하는 비동기 API다.
2. **E4-L1a(업로드)**: DOCX 압축 해제 상한 10MB 안팎, 압축비·항목 수 상한, 추출 글자 수가 50,000자를 넘으면 413, 응답에 추출 본문 상한. 파싱을 별도 프로세스로 돌려 시간 상한에서 강제 종료.
3. **E3(pipeline·llm)**: `StageStatus.detail`·notices에 예외 메시지·상류 API 문구를 애초에 넣지 않는다(분류 문자열만). 지금은 서빙 층이 공개 응답에서 가리지만 근본 수정이 낫다. 예열 속도를 위해 `neumann.pipeline.warmup()`(색인·모델 로드) 훅을 두면 서빙 층이 시작 때 부른다.
4. **main.py `/health`**: 공개 모드에서는 모듈 import 상태·예외 종류를 줄인다(SEC-1 S-04 낮음). 화면 머리 표시에 쓰는 값은 남긴다.
5. **공개 모드 샘플 경로(SEC-1 HON-L1)**: 파이프라인이 없을 때 샘플 대신 503 "서비스 준비 중". 서빙 층에 넣을 수 있지만 main.py의 샘플 흐름과 겹쳐 이번에는 넣지 않았다.
6. OpenAI 쪽 프로젝트 키에 월 지출 한도를 건다(코드 밖 최후 방어선).

## 다음 과제에 넘길 것

- worker는 1개여야 한다(대기열·속도 제한 상태가 프로세스 메모리에 있다). 여러 개가 필요하면 상태를 공유 저장소로 옮겨야 한다.
- 차단 스위치 사용법: 공개 중 비용이 걱정되면 `data/serving_block.flag` 파일을 만든다(재시작 불필요). 지우면 다시 받는다. 예산 사용량은 `GET /queue/status`의 `budget`.

## 재작업(FAIL 대응)

검증 보고서 `docs/reports/E4-L2c.verify.md`(FAIL)와 PM 추가 요청(E4-L1a 병합 뒤 업로드)에 대한 수정이다. 실제 OpenAI 호출 0회, 가짜 파이프라인만 썼다. 시험·부하 시험은 모두 `NEUMANN_LLM_PROVIDER=mock`을 명시해 돌렸다.

### 커밋

| 커밋 | 내용 |
|---|---|
| `fb4ee8c` | 본문 인코딩 우회 차단(fail-closed)·run() 2차 입장 검사·IPv6 /64·공개 XFF 무시·내보내기 예산 미소모·공개 기본값·/queue/status 예산 수치 제거·IP 해시 솔트·공백 키 거부 |
| `eedf1b5` | 부하 시험: CF-Connecting-IP로 IP 지정, 차단 스위치 켠 채 BOM·UTF-16·UTF-32 우회 시도 시나리오(G) |
| `651718b` | `main` 병합(E4-L1a 업로드 파서 받기) |
| `81b8328` | 업로드: IP별 속도 제한·IP별 동시 1건·Content-Type fail-closed·업로드 전용 10MB 상한 시험 |

### 항목별 수정·테스트·재현이 막히는 증거

| # | 지적 | 수정 | 테스트(새로 넣음) | 재현이 막히는 증거 |
|---|---|---|---|---|
| 1 치명 | BOM·UTF-16으로 보내면 미들웨어가 plan_text를 못 읽어 입장 검사를 건너뛰고, `Serving.run()`이 `force=True`로 대기열 상한·예산·차단을 무시 | (a) 미들웨어가 앱과 같은 파서 `json.loads(bytes)`(BOM·UTF-16·UTF-32 자동 판별)로 읽는다. (b) 분석 경로는 plan_text를 문자열로 못 읽으면(잘못된 JSON·깊은 중첩·문자열 아님·키 없음·빈 본문) **앱에 넘기지 않고 422**. (c) `Serving.run()`: 미들웨어 예약이 없으면 `admit_new()`로 차단·IP 속도 제한·예산·대기열을 다시 검사하고, 거절이면 `AdmissionRefused` → 미들웨어가 사용자 문구 503/429로 바꾼다. `force=True`는 예열(`internal=True`)만. 입장 검사는 `Serving.admit_new()` 한 곳에서 미들웨어와 run()이 같이 쓴다. `plan_key`는 짝 없는 서로게이트에도 예외 없이 동작 | `test_encoded_bodies_are_parsed_like_the_app_and_cannot_bypass_admission`(BOM·UTF-16·UTF-16LE·UTF-32 × 차단 스위치·글자 상한), `test_encoded_bodies_hit_budget_rate_and_queue_limits`(대기열·속도 제한·예산), `test_unreadable_or_invalid_analysis_body_is_rejected_before_the_app`(깨진 UTF-16·잘못된 JSON·10만 단계 중첩·문자열 아님·키 없음·배열·공백·빈 본문 → 422, 파이프라인 0회), `test_run_rechecks_admission_when_middleware_did_not_reserve` | 이전 serving.py(af008bb)로 새 테스트를 돌리면 `assert (200 == 503)`(BOM·UTF-16이 차단 스위치를 통과)으로 실패한다. 수정본은 통과. 부하 시험 G: 실제 uvicorn 서버에서 차단 파일을 켠 채 `utf-8`·`utf-8+BOM`·`utf-16`·`utf-32` 본문 → **전부 `(503, 'blocked')`** |
| 2 | IPv6 같은 /64 안에서 주소만 바꾸면 속도 제한 통과. XFF 첫 값은 위조 가능 | 속도 제한 키(`ip_key`)를 IPv6는 /64, IPv4-매핑은 IPv4로 묶는다(분석·보조·업로드 모두). 공개 프로필은 `NEUMANN_TRUST_XFF=0`(기본): X-Forwarded-For를 보지 않고 `CF-Connecting-IP`만 믿는다(없으면 한 통) | `test_ipv6_addresses_in_same_64_share_one_rate_limit`(같은 /64 5개 주소 → 200,200,200,429,429), `test_public_profile_ignores_x_forwarded_for`(XFF 4개 회전 → 200,200,429,429) | 이전 코드에서 /64 시험은 5/5 통과(한도 3)로 실패, 수정본은 3건 뒤 429 |
| 3 | `/premortem/package`에 plan_text만 보내면 422인데 예산·분석 슬롯 소모 | `analysis_mw` 분기 삭제. 내보내기는 항상 보조 관문 → 앱이 422 | `test_package_plan_text_only_is_422_without_touching_analysis_gate_or_budget`(실제 export 라우터, 3건 → 422, 예산 0·분석 슬롯 0·분석 속도 제한 0) | 이전 코드는 이 시험에서 분석 속도 제한(분당 1)에 걸려 `assert (429 == 422)`로 실패 |
| 4 | 기본값(Cloudflare 약 100초) | 공개 프로필 기본: `NEUMANN_REQUEST_TIMEOUT_S=90`, `NEUMANN_QUEUE_MAX=4`, `NEUMANN_DAILY_BUDGET=0`(끔, 대표 결정). 개발 기본은 300초·20 그대로 | `test_config_defaults_and_public_profile` | 설정값 확인(시험 통과) |
| 5 | /queue/status 예산 수치 노출, IP 해시 솔트 없음 | `/queue/status`에서 `budget`과 `limits.daily_budget` 제거. 공개 프로필은 `counters`·`cache`·`warmup`도 뺌(화면에 필요한 `ticket`·`accepting`·대기 수는 남김). 로그 IP 표시는 `HMAC-SHA256(솔트, IP/64)` 앞 10자. 솔트는 `NEUMANN_PSEUDONYM_SALT`(있으면, 값은 출력·기록 안 함) 또는 프로세스마다 무작위 | `test_queue_status_public_hides_budget_and_counters`, `test_daily_budget_503_cache_still_served_and_persists`(예산 키 없음 확인), `test_ip_tag_is_salted_hmac_and_hides_env_salt` | 부하 시험: 공개 프로필 `/queue/status` 키 = `accepting·active·aux·avg_run_s·blocked·eta_new_s·limits·max_active·max_waiting·waiting` |
| (권고) | 공백뿐인 `OPENAI_API_KEY`가 `--public` 사전 점검 통과 | 키 값을 출력하지 않고 공백을 뺀 길이만 확인 | `test_serve_public_preflight_refuses_whitespace_key` | 시험 통과 |
| (권고) | 깊게 중첩된 JSON → 500 | 분석 경로 파싱에서 `RecursionError`도 잡아 422 | 위 1번 `test_unreadable_...` | 시험 통과 |

### PM 추가 요청(E4-L1a 병합 뒤 업로드)

`git merge main`으로 E4-L1a(`upload.py`)를 받은 뒤 실제 업로드 라우터로 시험했다.

| 요청 | 수정 | 테스트 |
|---|---|---|
| 1. /upload/plan을 IP별 속도 제한 보호 경로에 | 업로드 전용 IP(/64)별 분당 상한 `NEUMANN_UPLOAD_RATE_PER_MIN`(공개 10, 내보내기와 따로 셈) + **IP별 동시 처리 상한** `NEUMANN_UPLOAD_PER_IP`(공개 1): 느린 PDF 2건을 한 IP가 올려 두 슬롯을 모두 잡을 수 없다(두 번째는 429 `busy_ip`, 다른 IP는 계속 올림). 시간 상한(504)을 넘겨도 처리가 실제로 끝날 때까지 그 IP의 동시 수를 쥔다 | `test_upload_per_ip_concurrency_so_slow_files_cannot_hold_every_slot`, `test_upload_timeout_releases_per_ip_count_only_when_work_ends`, `test_upload_rate_limit_is_separate_bucket`, `test_upload_defaults_public_profile` |
| 2. 요청 크기 상한은 업로드에만 10MB | 업로드 상한 = 파일 10MB + multipart 64KB(`upload.py`의 `MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES`와 같다), 분석 경로(글자×6+64KB ≈ 0.36MB)와 따로. multipart 본문 전체 기준, Content-Length 먼저, 없거나 거짓이면 스트리밍 누적으로 앱에 닿기 전 413 | `test_upload_body_cap_is_upload_only_10mb_by_length_chunked_and_lying_length`(정상 md 200, 10MB+64KB+1 → 413, chunked 11MB → 413, `Content-Length: 100`이라 적고 11MB 흘림 → 413이며 앱 호출 0) |
| 3. 업로드도 BOM·인코딩 우회 fail-closed | 본문을 읽기 전에 **앱과 같은 python-multipart 파서**로 Content-Type을 본다. multipart가 아니면(BOM 붙은 JSON·UTF-16 JSON·text/plain·Content-Type 없음·앞에 BOM이 붙은 Content-Type) 415, 경계 없음 400, 앱과 같은 문구(`detail`). 입장 검사(속도 제한·동시 상한·바이트 상한)는 본문 해석과 무관하게 걸리므로 인코딩으로 우회할 수 없다 | `test_upload_fail_closed_on_content_type_and_encoding`(6가지 거절 + BOM·UTF-16·UTF-32 multipart 본문이 분당 3에서 4번째 429) |

오류 본문에는 이제 `detail`(같은 사용자 문구)도 싣는다. 업로드 화면(E4-L1f)처럼 FastAPI 기본 모양(`detail`)을 읽는 화면이 관문 거절 문구도 그대로 보인다.

### 완료 기준 재측정

```
$ NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4/test_serving.py tests/e4/test_serving_sec.py -q
48 passed

$ git apply --check docs/reports/E4-L2c_main.patch        # main 병합 뒤 main.py 기준
(출력 없음 = 통과)
# 패치를 적용한 사본(HEAD 81b8328 + 패치)에서 전체 테스트, NEUMANN_LLM_PROVIDER=mock
1042 passed, 41 skipped in 68.27s

$ NEUMANN_LLM_PROVIDER=mock python scripts/serve_loadtest.py --port 8122 --out docs/reports/E4-L2c_loadtest.txt
  요약 A 동시 10건(서로 다른 계획서·IP): {"200": 10}          (동시 2, 대기 순번 1~8)
  요약 B 같은 10건 다시(캐시): {"200": 10} 최장=0.39s
  요약 C 동시 12건(대기열 상한 8): {"200": 10, "503": 2}
  요약 D 한 IP에서 7건(분당 6건): {"200": 6, "429": 1}
  G 결과: {'utf-8': (503, 'blocked'), 'utf-8+BOM': (503, 'blocked'), 'utf-16': (503, 'blocked'), 'utf-32': (503, 'blocked')}
  재시작 #1 이유: 프로세스 종료(code=3) → 재시작 뒤 데모 디스크 캐시 hit
  판정: PASS / 서버 종료 확인(포트 8122 닫힘) / 서버 로그 630줄 중 계획서 본문·트레이스가 든 줄: 0
```

```
$ NEUMANN_LLM_PROVIDER=mock python scripts/verify.py      # E4-L1e 파일 정리 뒤, worktree(패치 미적용)
1059 passed, 24 skipped in 103.34s
보안: 파일 361개 / 계약: 2개 / 테스트: 통과 / verify 통과
```

### git stash 사고와 정리(내 실수)

- **원인**: 재작업 중 새 테스트가 옛 코드에서 실패하는지 보려고 `git stash push src/neumann/api/serving.py`(내 stash `69c9414`) → 시험 → `git stash pop`을 했다. stash 목록은 모든 worktree가 같이 쓴다. 그 사이 E4-L1e가 자기 stash(`544fb16`)를 쌓아서, 내 `pop`이 **E4-L1e의 stash를 내 작업 트리에 적용하고 목록에서 지웠다**(19:56). 내 stash는 목록에 남았다.
- **내 작업 복구**: `git checkout 69c9414 -- src/neumann/api/serving.py`로 내 serving.py를 되살리고 그 stash 항목을 목록에서 지웠다. 커밋 객체 `69c9414`는 남아 있다. `fb4ee8c`의 serving.py는 `69c9414`의 내용 그대로다(그 뒤 `81b8328`에서 업로드 부분만 더함). `git stash apply 69c9414`는 따로 할 필요가 없었다.
- **E4-L1e 변경 정리(커밋 안 함, 버림)**: 되돌린 파일 `src/neumann/api/templates.py`, `src/neumann/api/templates/catalog.json`, `src/neumann/api/templates/catalog.schema.json`, 지워졌던 `templates/medical_imaging.md`·`neuro_fmri.md`·`physics_pde_climate.md`·`protein_molecule.md`(복원), `src/neumann/webui/index.html`(SCOPE 한 줄), `tests/e4/test_templates.py` → `git restore --staged --worktree`. 새로 생긴 `templates/examples/neural_operator_weather.md`·`protein_ligand_affinity.md`(스테이징돼 있었음)와 `templates/climate_emulator.md`·`molecule_reaction.md`·`pde_operator.md`·`protein_binding.md` → 스테이징 해제 뒤 삭제. 정리 뒤 `git status`에 E4-L1e 파일 없음.
- **내 커밋에는 섞이지 않았다**: 그동안 커밋은 모두 `git commit -- <내 파일>`로 내 파일만 담았다. `main` 병합(`651718b`) 직전에는 `index.html`을 잠시 HEAD로 돌리고 스테이징 2개를 내렸다가 병합 뒤 되돌려 놓았으므로 병합 커밋에도 E4-L1e 파일이 없다(`git show --stat 651718b -- src/neumann/api/templates* tests/e4/test_templates.py` 결과 없음).
- E4-L1e 변경의 사본(추적 파일 diff, 스테이징 목록, 새 파일)은 스크래치 폴더에 있다. 원본은 커밋 객체 `544fb16`으로 남아 있다(E4-L1e worktree에서 `git stash apply 544fb16`).
- 앞으로 `git stash`를 쓰지 않는다(작게 커밋하거나 파일 복사로).

### 여전히 남은 것(재작업 범위 밖)

- 비동기 작업 API(긴 대기, Cloudflare 100초): E4-L2d.
- 캐시 적중·합류의 별도 넉넉한 IP 제한, plan당 합류자 상한, 본문 읽기 시간 제한, 강등 결과 짧은 보관, 공개 모드 샘플 경로 503, IP별 일일 상한: 검증 보고서의 비차단 권고. 이번에는 넣지 않았다.
- 실제 cloudflared 터널 뒤 실측, 실제 파이프라인 비용 측정(실호출 금지).
