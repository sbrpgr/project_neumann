# SEC-7 보고서 — 공개 서빙 보강(인수인계 시점 WIP)

## 남은 일 (인수인계 요약)

1. **완료(코드, WIP 커밋 `54f63c8`)**: 1 보안 헤더 · 2 공개 /health 축소 · 3 CF-Connecting-IP 검증 · 4 IPv6 /56 · 5 IP별 대기열 몫 · 6 줄 수 상한(붙여넣기·jobs·업로드) · 8 살아 있는 job_id 정확 일치 가림 · 9 GET 속도 제한·요청 대상 8KB 414 · 10 설정 이름 허용 목록. 아래 "전후 측정"의 후 값으로 동작 확인.
2. **부분**: 7 PDF 폭탄 — 코드만(작업자 메모리 512MB 작업 개체, 스트림 해제 8MB, 쪽 내용 1MB 넘으면 건너뜀, 전체 5MB 넘으면 413, 쪽당 20,000자, 시간 20→10초). **실측·테스트 안 함**(폭탄·정상 PDF로 시간·메모리 재기, 10초가 정상 PDF를 깨지 않는지). 6의 **내보내기 입구 줄 수 상한 미적용**.
3. **미완**: 11 `/premortem/package` 조기 컷(카드 수·카드별 줄·계획서 줄·결정 수, `_plan_annotated`의 `ref not in refs` 제곱 제거) — 전: 3,300장×199줄 3.0MB **13.4초**, 4,000장 3.6MB **22.8초**(200). 12 `.env.example` 새 키 이름(`NEUMANN_MAX_PLAN_LINES`, `NEUMANN_MAX_REQUEST_LINE`, `NEUMANN_GET_RATE_PER_MIN`, `NEUMANN_QUEUE_PER_IP`, `NEUMANN_QUEUE_RESERVE`, `NEUMANN_UPLOAD_TIMEOUT_S`, `NEUMANN_UPLOAD_MEMORY_MB`).
4. **미완(검증)**: 항목별 새 테스트(tests/e4/test_sec7.py 예정), 전체 `python scripts/verify.py`·`--security`(커밋 훅의 스테이징 보안 검사만 통과), 줄 수 분포 표(정상 계획서·템플릿·fixture), mask_live_secrets 선형성 표(1k~64k, 살아 있는 id 500개).
5. **PERF-pk 충돌: 없음(확인)** — 이 브랜치 트리에 `PERF-pk_serving.patch`·`PERF-pk_models.patch` 모두 `git apply --check` 통과. PERF-pk 커밋 `1b62266`의 export.py 헝크는 이 브랜치가 export.py를 안 건드렸는데도 적용 실패 → main의 export.py(DISP-1 등)와의 기존 충돌이고 SEC-7과 무관.

## 전후 측정(측정 스크립트: scratchpad `sec7/sec7_probe.py`, 전 = main `d8f7c85` 사본, 후 = WIP 트리, 공개 프로필 + 행사 기동값, 가짜 파이프라인·mock)

| 항목 | 전 | 후 |
|---|---|---|
| 1 보안 헤더(/, /health, /queue/status, 폰트, 404, view 200·413, jobs 202, /docs 404) | 4종 모두 없음 | 9개 응답 모두 `nosniff`·`frame-ancestors 'none'`·`X-Frame-Options: DENY`·`no-referrer` |
| 2 공개 /health | 8키(stages·routers·started_at·llm.key_present·provider_requested·astra_allowed·pipeline.reason) 1,341B | `status·version·commit·pipeline{state,mode,label}·llm{effective,model,live_llm_ok}·accepting` 210B, key_present·stages 없음(로컬 모드는 그대로) |
| 3 CF-Connecting-IP `"a, b"`·`garbage<script>`·`999.1.1.1` | 그 문자열이 그대로 IP 통 | peer(127.0.0.1)로 처리 + 60초에 한 번 경고(값은 안 적음) |
| 4 같은 /56의 다른 /64 | 다른 통(`…:10::/64` ≠ `…:20::/64`) | 한 통(`2001:db8:1::/56`), 다른 /56은 다른 통 |
| 5 가짜 IP 4개 × 10건 뒤 새 사용자 5명 | 대기열 6+30 가득, 새 사용자 **5/5 503 busy** | 공격 IP 27칸에서 멈춤(429 busy_ip), 새 사용자 **5/5 202** |
| 6 짧은 줄 24,000줄(4.8만 자) | jobs 202 · view 200(0.93s) · /premortem 200 · 업로드 200 · 내보내기 200 | jobs·view·/premortem **422 too_many_lines 즉시** · 업로드 422(코드 반영, 재측정 필요) · 내보내기 미적용 |
| 8 살아 있는 job_id 쪼갠·겹 인코딩 10형태(접근·앱 로그) | 7형태 노출(이중 인코딩·%25XX·`+`·`%zz`·`/`·`.~`) | **0형태 노출** |
| 9 GET 60k 쿼리 / 8.3k / 한 IP /health 700회 | 200 / 200 / 700건 200 | **414 / 414 / 600건 200 + 100건 429**, 다른 IP 200 |
| 9 접근 로그 필터 1건(ms, 2k·8k·32k·64k자) | 0.7·2.7·10.8·22.5 | 1.05·0.16·0.16·0.16(2,048자에서 자르고 잘린 토큰 조각은 뺌) |
| 10 설정 이름 경고 | `설정 NEUMAN… 값이…` | `설정 NEUMANN_UPLOAD_RATE_PER_MIN 값이…` |

## 결정(스펙이 모호해서 고른 것)

- 5: "대기 칸의 1/3"만으로는 IP 4개 × 10 = 40 ≥ 36이라 재현이 안 막힌다. 그래서 **IP별 몫(대기 칸의 1/3 = 10)** + **남은 자리 몫(기본 10칸: 이미 자리를 가진 IP는 남은 자리가 10칸 이하이면 더 못 잡음, 처음 오는 IP는 예외)** 두 겹으로 했다. 공개 프로필에서만 켜진다(`NEUMANN_QUEUE_PER_IP`·`NEUMANN_QUEUE_RESERVE`).
- 4 근거(요약): RIPE-690은 가정 가입자에 /56(기업 /48)을 권한다. /64로 묶으면 /56 가입자 한 명이 256개, /48이면 65,536개 통을 갖는다. 휴대폰은 기기마다 /64를 받아 같은 /56에 다른 가입자가 섞일 수 있으나, IPv4 CGNAT(수천 명이 한 주소)보다 훨씬 잘다.
- 2: OPS-tun `public_ops.ps1`이 읽는 `pipeline.state`·`llm.effective`·`llm.model`·`llm.live_llm_ok`는 남겼다. `llm.key_present`는 지시대로 숨겨 공개 모드에서 그 칸은 빈 값으로 찍힌다(StrictMode 1이라 오류 없음). 키 없음은 `effective=openai_no_key`로 보인다.
- 9: 요청 대상 상한은 미들웨어(414)로 했다(httptools 기본 경로 유지). 414여도 uvicorn 접근 로그는 전체 경로를 적으므로 로그 필터가 인자를 2,048자에서 자른다.

## 바꾼 파일(WIP 커밋)

`src/neumann/api/serving.py`, `jobs.py`, `main.py`(/health만), `upload.py`, `tests/e4/test_serving_sec.py`(IPv6 /56으로 기대값 변경). 관련 테스트 `tests/e4/test_serving.py test_serving_sec.py test_jobs.py test_jobs_limits.py test_e4_api.py tests/e0/test_health_commit.py test_sec3_live_guard.py` → 131 passed. 시험 서버는 띄우지 않았다(모두 프로세스 안 ASGI 측정).
