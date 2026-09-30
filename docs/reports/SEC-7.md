# SEC-7 보고서 — 공개 서빙 보강 완료, PM 전체 검증 대기

## 이번 빌더 결과 (2026-10-01 KST)

- worktree: `C:/Users/User/Desktop/project_neumann/.claude/worktrees/s2-SEC-7`
- branch: `task/SEC-7`, 인계 HEAD: `554d2b96a15d1f71bcbf0c47a69fb8a3edb815a5`
- actual builder model: `codex-gpt-6.1-sol` (최신 PM 지시). 별도 verifier 모델은 `codex-gpt-6-sol`이며 이번 빌더가 대신 검증했다고 주장하지 않는다.
- 제품 코드 커밋: `5ee685c`; 새 테스트 커밋: `abfee37`; 문맥 진입 보완: `6fbbfa6`. 최종 HEAD는 이 보고서·측정 도구를 포함한 커밋(`git rev-parse HEAD`).
- 실제 OpenAI API 호출 **0**. mock·오프라인·ASGI·자기 추출 작업자만 사용. 하위 에이전트·CLI 위임·실서비스 호출·서버 시작/종료·main 병합·push·tag 없음.
- `contracts/`, `models.py`, `config.py`, 공통 HANDOFF/QUEUE/decisions, 원본 공개자료 수정 없음. `.env`·인증 파일·키 값 열기/출력 없음.

### 무엇을 했나

인계된 1~10 보강에 새 회귀 검사를 추가했다. 내보내기 입구의 계획서 줄 제한과 항목 11을 완성했고, 항목 12의 설정 키 7개를 `.env.example`에 빈 값으로 추가했다.

`/premortem/package`는 미들웨어에서 **aux 자리 예약 전에**, 단독 라우터에서도 **PackageRequest/PremortemResult 검증 전에** 조기 검사한다. 감싼 결과·bare result 모두 카드 100장, 카드별 연결 줄 200개, 결정 1,000건을 넘으면 422. 계획서는 기본 5,000줄/50,000자(서빙 설정과 연동)를 넘으면 422/413. `plan_text`와 `result.plan.lines` 둘 다 검사하고 줄 객체 속 개행도 센다. 거절 메시지에 본문을 되돌리지 않는다. 계약 자체를 변경하지 않았다.

`_plan_annotated`는 카드 안의 중복 줄을 `dict.fromkeys`로 제거한 뒤 고유 카드 ref를 붙인다. 누적 ref 목록의 `ref not in refs` 검색을 제거했고 카드 순서·중복 제거·출력 형식을 유지한다.

PDF는 작업자 메모리 제한 설치 실패 시 503으로 거절한다(이전에는 계속 추출). 스트림 해제 상한 API가 없는 pypdf도 503으로 거절한다(이전 nullcontext 제거). 제한 예외가 쪽 객체를 받기 전에 발생해도 이전 쪽/미정의 객체를 쓰지 않는다. Windows 작업 개체 설정 실패 시 핸들을 닫는다.

### 완료 기준별 결과

아래 동작은 `tests/e4/test_sec7.py`의 **63개** 새 사례로 확인했다. 기존 인계 131개 + 업로드/내보내기 84개 + 새 63개 = **278 passed in 27.49s**. 항상 통과하는 검사는 없고 거절 전 모델 검증·ZIP 조립·자리 예약이 호출되면 실패하는 검사도 포함했다.

| 항목 | 결과와 검사 |
|---|---|
| 1 보안 헤더 | `/`, `/health`, `/queue/status`, 폰트, 404, `/docs` 404, 전역 500, view 200·413, jobs 202에 4종 헤더 일치 |
| 2 공개 health | 공개 응답은 6개 최상위 키, llm은 effective/model/live_llm_ok 3개만. key_present·실패 사유 없음. 로컬 진단은 유지 |
| 3 CF IP 검증 | 잘못된 값 5종은 peer 사용, 값 자체는 경고 로그에 없음. 올바른 IPv6 사용, trust=never는 peer |
| 4 IPv6 /56 | 서로 다른 /64 2개가 같은 /56 통, 다른 /56은 별도 통. 기존 속도 제한 회귀도 통과 |
| 5 IP 대기 몫 | 4개 공격 IP×10번 시도는 27자리에서 멈춤, 신규 5명은 모두 자리 확보(총 32). 취소 뒤 owner 잔존 0. 실제 job 입구 busy_ip 429/작업 0 |
| 6 줄 수 상한 | LF/CR/CRLF 5,001줄은 premortem/view/jobs에서 422, 파이프라인 호출·job·대기 자리 0. 업로드는 Unicode 줄 구분자까지 422, 5,000줄 허용. 내보내기에서도 조기 422 |
| 7 PDF 폭탄 | 아래 실측표 + 정상 12쪽, 쪽 스트림 건너뜀 경고, 해제 폭탄 경고, 전체 내용 413, 쪽 글자 413, 전체가 무거운 파일 422. 실제 메모리 제한 설치/할당 거절·설치 실패 시 503 확인 |
| 8 살아 있는 job id 가림 | 날것·percent·2/3중 인코딩·`+`·`/`·`.~`·`%zz`·`%25zz` 9종을 앱/접근 로그 양쪽에서 가림. 등록 해제 뒤 원문 유지 |
| 9 GET/주소/긴 로그 | 분당 2건 설정에서 2회 허용 뒤 429, 다른 IP 허용. 긴 주소 414는 요청을 세기 전. 64k 로그 인자는 2,100자 미만. 기존 poll 제한 회귀 통과 |
| 10 설정 이름 가림 예외 | `NEUMANN_UPLOAD_RATE_PER_MIN`을 경고에 그대로 남김 |
| 11 package/refs | 7종 과대 입력×서빙 설치 여부 2종 모두 비싼 처리 전에 거절. bare result·사용자 줄 상한·경계값·정상 ZIP·100카드 중복 ref 순서 확인 |
| 12 설정 견본 | 7개 새 키 이름과 빈 값 추가. 프로세스 환경변수로 전달하며 config.py 필드를 새로 만들지 않음 |

### 실행 명령과 출력

Python은 기존 저장소 지정 경로 `C:/Users/User/.venvs/neumann/Scripts/python.exe`를 사용했다. 각 실행 프로세스에 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_TESTS=0`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `PYTHONPATH=src;.`, `PYTHONIOENCODING=utf-8`를 지정하고 `NEUMANN_LIVE_LLM_OK`는 제거했다. pytest 공통 설정은 자체적으로 live 플래그를 0으로 닫는다. 사용자/시스템 환경변수는 변경하지 않았다.

```powershell
& 'C:/Users/User/.venvs/neumann/Scripts/python.exe' -m pytest -q --tb=short --basetemp=out/sec7-final-regression-3 tests/e4/test_serving.py tests/e4/test_serving_sec.py tests/e4/test_jobs.py tests/e4/test_jobs_limits.py tests/e4/test_e4_api.py tests/e0/test_health_commit.py tests/e0/test_sec3_live_guard.py tests/e4/test_upload.py tests/e4/test_export.py tests/e4/test_sec7.py
# 278 passed in 27.49s (exit 0)
& 'C:/Users/User/.venvs/neumann/Scripts/python.exe' -m tests.e4.sec7_probe
# exit 0; 아래 표의 JSON 측정값 출력
git diff --check
# 출력 없음 (exit 0)
```

최초 두 pytest 시도는 기능 실패가 아니라 임시 폴더 준비 문제였다: 기본 `pytest-of-User` 접근 거절, 이후 `out/` 부모 미생성으로 각각 `143 passed, 72 errors`. worktree 내부 `out/`을 만들고 고유 basetemp를 지정해 해결했다. 첫 새 테스트 실행은 기대 필드명/경고 상태 이름 오류로 `45 passed, 15 failed`였고 테스트를 올바른 `error_code`/상태 이름에 맞췄다. 폰트가 하위 폴더에 있어 `276 passed, 1 failed`; 실제 폰트의 상대 경로로 수정한 뒤 277 통과. pypdf 설정의 실제 __enter__ 실패 사례를 추가한 마지막 회귀는 위 278 통과. 측정 도구 초기의 CP949 출력 디코딩 오류와 가짜 id 길이 단언 실패도 수정했으며 최종 명령 exit 0. 검사 기준이나 제품 검사를 약화하지 않았다.

전체 `python scripts/verify.py`와 `--security`는 최신 PM 지시대로 실행하지 않았다. 커밋 시 정상 pre-commit 훅의 **스테이징 보안 검사**만 실행되어 제품 4파일·테스트 1파일·문맥 진입 보완 2파일 각각 `verify 통과`. 전체 verify 통과로 해석하면 안 된다. 첫 git add/commit은 공유 `.git/worktrees/.../index.lock` 쓰기 권한 부족으로 실패했으며, 승인된 자기 파일 커밋에 한정한 sandbox escalation 후 성공했다. 훅 우회 없음.

### 저부하 측정

재현 도구 `tests/e4/sec7_probe.py`. 외부 다운로드 없이 합성 입력만 사용하고 PDF는 자기 자식 프로세스 한 개씩 실행한다. 메모리는 Windows `GetProcessMemoryInfo`로 **그 작업자 자신의** peak working set/peak pagefile usage(커밋)를 측정했다. pypdf 6.19.0, 메모리 제한 설치는 모든 사례에서 True.

| PDF 사례 | 업로드 크기 B | 상태 | 추출 ms | 프로세스 포함 ms | peak RSS MB | peak commit MB |
|---|---:|---:|---:|---:|---:|---:|
| 정상 한국어 12쪽 | 11,034 | 200, 1,391자/48줄/경고 0 | 106.32 | 586.97 | 52.18 | 41.54 |
| 정상 1쪽 + 1MB 초과 내용 쪽 | 3,030 | 200, 생략 경고 1 | 103.55 | 752.67 | 53.83 | 42.15 |
| 정상 1쪽 + 8MB 해제 폭탄 | 9,828 | 200, 생략 경고 1 | 113.05 | 608.74 | 67.45 | 55.60 |
| 0.9MB 내용 6쪽(총 5MB 초과) | 8,326 | 413 | 226.23 | 714.76 | 57.91 | 46.28 |
| 쪽당 20,001자 | 81,479 | 413 | 123.07 | 640.00 | 52.02 | 41.36 |

정상 합성 PDF는 10초 제한에 충분히 들어왔다. 임의의 실제 논문·이미지 PDF 전체와 POSIX 환경 호환성을 증명한 결과는 아니다. 별도 회귀는 128MB 제한 아래 160MB `bytearray` 할당을 시도해 `limited=True`·`allocation_denied`를 확인했다. 기존 timeout 강제 종료·작업자 디스크 쓰기 거절·DOCX 격리 테스트도 통과.

| package/주석 측정 | 결과 |
|---|---|
| 3,300카드×199줄, 3,042,628B | 422, 43.18ms |
| 4,000카드×199줄, 3,688,028B | 422, 35.36ms |
| 연결 목록 500카드×100줄 | 이전 membership 루프 63.971ms → 새 루프 2.502ms |
| 연결 목록 1,000카드×100줄 | 이전 membership 루프 257.192ms → 새 루프 5.620ms |

package 측정은 4MB 본문 제한 안에서 개수 검사 자체를 재는 최소 raw 카드 입력이다. 과거 WIP의 완전한 결과 입력/전체 ZIP 측정과 같은 데이터는 아니며 13.4/22.8초를 다시 실행하지 않았다. 주석 측정은 동일 ref 목록을 두 루프에 넣어 출력 일치를 단언한다(각 1회); 카드 두 배에서 새 루프 약 두 배, 이전 루프 약 네 배.

살아 있는 가짜 id 500개(모두 실제 job id처럼 32자) 등록, 입력 끝의 쪼갠 id가 가려지는 것을 단언한 뒤 `mask_live_secrets` 3회 중앙값:

| 입력 문자 | 1,024 | 2,048 | 4,096 | 8,192 | 16,384 | 32,768 | 65,536 |
|---|---:|---:|---:|---:|---:|---:|---:|
| ms | 0.217 | 0.391 | 0.804 | 1.589 | 3.312 | 7.106 | 16.037 |

등록 수와 별개로 같은 길이 id의 set membership을 사용한다. 실측은 대략 입력 크기에 비례하며 시간 잡음/할당 비용이 있다. 길이가 제각각인 임의 비밀값 수에 대한 일반적 복잡도 보장은 아니다. 실제 로그 필터는 먼저 2,048자에서 잘라 훨씬 작은 입력만 이 함수에 넘긴다.

줄 수 표본(저장소 11개, 파일 마지막 개행 포함):

| 표본 | 줄 | 자 |
|---|---:|---:|
| fixture negative_recipe / plan / plan_elife_neuro / plan_medimaging | 23 / 28 / 29 / 29 | 442 / 645 / 630 / 690 |
| template climate_emulator / materials_gnn / molecule_reaction | 30 / 30 / 30 | 863 / 680 / 772 |
| template pde_operator / protein_binding | 31 / 30 | 832 / 844 |
| example neural_operator_weather / protein_ligand_affinity | 29 / 28 | 901 / 926 |

모든 표본이 5,000줄/50,000자 이하. PERF-pk의 normalization length/line 제안은 적용하지 않았다. 모델 정규화·모든 유니코드 줄 구분자 의미 변경은 이번 소유 범위 밖이다.

### PM 결정 기록 제안

`docs/decisions.md`는 직접 수정하지 않았다. PM이 기록할 내용: package의 100카드/200연결줄/1,000결정 상한은 분석의 정상 규모보다 넉넉한 고정 방어선이며 plan 상한은 serving과 공유한다. PDF 내용이 큰 쪽은 생략 사실을 응답 warnings에 명시하고, 전체를 추출하지 못하면 422; 메모리/해제 안전 제한을 준비하지 못하면 보호 없이 추출하지 않고 503. 새 설정 키 7개는 `.env.example`에서 값이 비어 있으며 프로세스 환경변수 전달이 필요하다.

### 남은 일 / 다음 (5줄)

1. PM 큐에서 이 HEAD에 전체 `python scripts/verify.py`·보안 검사를 실행한다(빌더 실행 금지 지시로 미실행).
2. 별도 `codex-gpt-6-sol` 검증자가 항목별 완료 기준을 다시 측정하고 merge 판정을 내린다.
3. PM이 PERF-pk normalization length/line 제안과 결합 여부를 결정한다(계약/models/config 수정 없음).
4. 합성 외 실제 대형/이미지/복잡한 정상 PDF 및 POSIX는 미측정; 필요 시 PM의 로컬 후속 표본으로 10초/512MB 호환성을 확인한다.
5. PM이 위 결정 제안을 공통 문서에 기록하고 main 병합/배포/재시작을 담당한다. 이번 빌더는 서비스에 손대지 않았다.

---

## 아래는 인계 전 WIP 기록 (이번 완료 상태와 구분)

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
