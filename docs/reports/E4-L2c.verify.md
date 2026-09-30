# E4-L2c 검증 보고서 (검증자: Claude Sonnet 5.5)

**FAIL — 공개 금지.** 본문 JSON을 `\ufeff`(BOM) 한 글자 붙여 보내거나 UTF-16으로 보내면 **속도 제한·대기열 상한·일일 예산·차단 스위치·글자 상한이 전부 우회된다.** 정상 경로에서는 모두 막히지만, 이 서버는 토큰도 지출 한도도 없어서 이 관문이 유일한 방어선이고, 공격자는 헤더를 위조할 필요도 없이 본문 인코딩만 바꾸면 된다. 고칠 곳은 작다(아래 "고칠 것" 1번). 고친 뒤 재검증이 필요하다. 나머지 항목(오류 문구·로그·캐시·`--public`·감시·본문 바이트 상한)은 통과했다.

- 대상: 브랜치 `task/E4-L2c`(HEAD `af008bb`, 빌더 claude-opus-5.5), worktree `.claude/worktrees/s2-E4-L2c`, 통합 패치 `docs/reports/E4-L2c_main.patch`
- 방법: 빌더 보고서를 믿지 않고 직접 공격했다. 임시 폴더 `C:\Users\User\AppData\Local\Temp\v_e4l2c`에 **main(`ecedeb9`) 사본 + 브랜치 변경(`git diff main...task/E4-L2c -- src scripts tests`) + PM 패치를 적용**해 만들고(worktree는 건드리지 않았다. 사본에 패치와 브랜치가 충돌 없이 적용됐다), 그 안에 검증용 앱 `scripts/verify_app.py`(실제 patched `main.app` + **가짜 느린 파이프라인**, 시험 입력에 따라 예외·경로·키 모양 문구를 일부러 던짐)를 두어 `scripts/serve.py --public --app scripts.verify_app:app --port 8135`로 띄웠다(총 5회 기동, 매번 종료 확인, 8010 미사용, 8135 닫힘 확인). 실제 OpenAI 호출 0회, bge-m3 적재 0회, 하위 에이전트 0, `.env` 안 염. 서버 자식 프로세스의 `OPENAI_API_KEY`는 **가짜 값**이고 실제 키는 넘기지 않았다. 데이터 폴더는 회차마다 새 임시 폴더(`v_data1~5`)다.
- 환경: Python 3.12 `neumann` venv, fastapi 0.141.1, starlette 1.7.0, uvicorn 0.54.0.

## 판정 요약

| 영역 | 결과 |
|---|---|
| 정상 경로(본문이 평범한 UTF-8 JSON) | 동시 상한 2, 대기 순번, 큐 상한 503, IP 429, 예산 503, 차단 503, 바이트·글자 상한 413 모두 **작동** |
| **본문이 BOM·UTF-16 JSON** | **위 관문 전부 우회 → FAIL** |
| 오류 문구·로그·캐시·`--public`·감시 | 통과 |
| Cloudflare 100초 | 위험 실재(동시 3번째 사용자부터 524). 비동기 작업 API 권고 |

## 고칠 것

**공개 전 필수(재검증 대상)**

1. **본문 파서 불일치로 모든 관문 우회(높음).** `serving.py:1184`가 `json.loads(body.decode("utf-8"))`로 `plan_text`를 읽는데, FastAPI는 `json.loads(bytes)`(BOM·UTF-16·UTF-32 자동 판별)로 읽는다. BOM이 붙으면 미들웨어는 파싱에 실패해 `plan_text=None`, `plan_id=""` → `serving.py:1220 elif ctx.plan_id:`를 건너뛰어 **차단·속도 제한·예산·대기열 검사가 하나도 안 돌고**, 앱은 정상 파싱해 `Serving.run()`에 들어가며 `serving.py:907 reserve(..., force=True)`(대기열 상한 무시)와 `:909 budget.spend()`(세기만 하고 검사 안 함)로 분석이 실행된다. 수정:
   - (a) `serving.py:1184`를 `json.loads(body)`(bytes)로: 임시 사본에서 이 한 줄만 바꿔 BOM·UTF-16 본문이 `503 blocked`로 막히는 것을 확인했다(원상 복구함).
   - (b) 분석 경로(`analysis`)에서 `plan_text`를 문자열로 못 읽으면 **앱에 넘기지 말고 거절**(fail-closed, 400/422).
   - (c) 방어선을 `Serving.run()`에도 둔다: 미들웨어가 예약하지 않은 실행(`ctx.reservation is None`)은 차단 스위치·예산·대기열 상한을 다시 검사하고, `force=True`는 예열에만 쓴다. 파서 차이가 다른 모양으로 또 생겨도(같은 계획서 합류 판단과 `run()` 사이의 경쟁 포함) 뚫리지 않는다.
   - (d) 테스트 추가: BOM·UTF-16·UTF-32 본문이 차단 스위치·예산 소진·속도 제한·대기열 상한·글자 상한에 걸리는지(현재 34건 중 이 경우를 다루는 것이 없다).
2. **IPv6 속도 제한 우회(중간).** 키가 주소 전체 문자열이라 같은 /64 안에서 주소만 바꾸면 한도 6이 12/12 통과한다(위조 불필요, 가정용·모바일·VPS는 /64를 갖는다). IPv6는 /64로 묶어 센다. 같은 이유로 **IP(/64)별 일일 상한**(예: 10건)을 추가하면 한 사람이 일일 예산 200건을 혼자 태워 심사위원이 "오늘 한도"를 보는 사고를 줄인다.
3. **`/premortem/package`에 plan_text만 보내는 요청이 예산·속도 제한·분석 슬롯을 소모(중간~낮음).** 422로 끝나 파이프라인은 안 돌지만 `analysis_mw` 분기(`serving.py:1191-1192`)가 분석 관문에 입장시켜 예산 1건을 뗀다(실측 2건 요청에 +2). 경로가 삭제된 지금은 이 분기를 없애고 보조 관문으로 보내 바로 422를 주면 된다.
4. **Cloudflare 100초(아래 절):** 최소 `NEUMANN_REQUEST_TIMEOUT_S=90`으로 낮추고 `NEUMANN_QUEUE_MAX`를 동기 API로 견딜 값(2~4)으로 줄인다. 다인 동시 시연이 목표라면 비동기 작업 API가 필요하다.
5. **코드 밖 최후 방어선:** OpenAI 프로젝트 키에 월 지출 한도를 건다(SEC-1 S-01 권고 5). 일일 예산은 "건수"이고 건당 토큰 비용은 이번에 측정하지 못했다(실호출 금지). 최악 비용 = 건수 상한 × 건당 비용이므로 E5 라이브 로그의 사용량으로 건당 비용을 잡아 `NEUMANN_DAILY_BUDGET`을 정한다.

**권고(비차단)**

- 캐시 적중·합류는 속도 제한과 무관해 무제한이다. 적중 400건 폭주(동시 40)에서 처리량 약 14건/초(건당 약 70ms가 이벤트 루프를 점유), `/health` 지연 중앙값 2.2초, 최대 2.6초. 결과가 더 큰 실제 분석이면 `/health`가 감시 스크립트 시한(10초×3)을 넘겨 불필요한 재시작(대기열·메모리 캐시 소실)을 부를 수 있다. 적중·합류에도 넉넉한 IP별 제한(예: 분당 60)과 plan당 합류자 상한(예: 30)을 둔다. 같은 계획서(본문 121KB) 400건 동시(합류 134, 나머지는 끝난 뒤 적중)에서 서버 메모리 71 → 143MB, 속도 제한 0건.
- 깊게 중첩된 JSON(10만 단계)은 미들웨어에서 `RecursionError`가 나 500이 된다(응답은 고정 문구+요청 id라 안전, 로그에는 예외 종류만). 400으로 처리한다.
- 로그의 IP 표시 `ip_<sha256 앞 10자>`는 솔트가 없어 IPv4 전수 대입으로 되돌릴 수 있다("IP 원문 없음"은 가명화 수준). 기동 시 무작위 솔트를 섞는다.
- 본문 읽기에 시간 제한이 없다(느린 전송으로 연결을 오래 붙잡을 수 있음). Cloudflare가 앞단에서 완화하지만 `receive()` 루프에 시한을 둔다.
- `GET /queue/status`가 공개로 예산 잔량·차단 여부·카운터를 보인다. 공격자가 예산 소진 시점을 잰다. 공개 프로필에서는 `budget`·`counters`·`limits`를 뺀다(화면은 `ticket`·`accepting`만 필요).
- 공백만 있는 `OPENAI_API_KEY`도 `--public` 사전 점검을 통과한다(`has_openai_key`가 참). 값을 출력하지 않는 조건에서 길이 하한 정도만 본다.
- 예열의 `warmup()` 훅이 실제 `neumann.pipeline`에는 없다(`grep`으로 확인: `run_premortem`만 있음). 그래서 색인·모델 선적재는 안 일어나고, 새 데이터 폴더에서 시작할 때마다 데모 3건이 **실제 분석으로** 돌아 비용이 든다(디스크 캐시가 채워지면 이후는 없음). `status: ok`가 아니면 캐시되지 않아 재시작마다 다시 돈다.
- 캐시는 `status: ok`만 저장한다. 그래서 강등(degraded) 결과는 504·524 뒤 재시도가 **분석을 다시 돌려 비용이 두 번** 든다. 끝난 작업 결과를 상태와 무관하게 60~120초 보관해 재시도가 받게 한다.
- 파이프라인 모듈이 없을 때 샘플(가짜 fixture)을 200으로 내는 흐름(SEC-1 HON-L1)은 그대로다(빌더 "제안 5"). 공개 시 503 "서비스 준비 중"이 낫다.

## 항목별 결과

| # | 확인 항목 | 실행한 방법 | 실제 결과 | 판정 |
|---|---|---|---|---|
| 1 | 동시 상한 | 가짜 파이프라인(3초)에 서로 다른 계획서·IP로 동시 요청, 파이프라인 호출 로그에서 동시 실행 수 집계 | 동시 실행 최대 **2**(로그 `max=2`), 나머지는 대기. 6건 동시: 순번 0,0,1,2,3,4·대기 0/0/2.7/2.6/5.3/5.4초, 응답 헤더 `X-Neumann-Queue-Position`과 `_status.serving`이 일치 | 통과 |
| 2 | 대기 순번·예상 시간 | `GET /queue/status?ticket=`를 대기 중에 조회 | `running`·`waiting position=1..4 eta_s=1.1~4.0` 정확(EMA 평균이 3초일 때) | 통과 |
| 3 | 대기열 상한 503 | 서로 다른 계획서 30건 동시(기본 큐 20) | **200×22(실행 2+대기 20), 503×8**, 관찰된 대기 최대 20. 문구·`Retry-After` 있음. 같은 조건에서 `/premortem`만 26건도 22/4. (큐 상한을 낮춰 시험한 회차는 예산 소진 503이 섞여 큐 상한 단독 증거로 쓰지 않았다) | 통과(정상 본문) |
| 4 | 같은 계획서 합류 | 동일 계획서 12건 동시 | 파이프라인 호출 **+1**, 예산 **+1**, 응답 `queue`: joined 11·queued 1 | 통과 |
| 5 | IP 속도 제한 429 | 같은 `CF-Connecting-IP`로 9건 동시 | 200×6, **429×3**(분당 6). 업로드·내보내기(보조)는 별도 통(분당 30): 40건 중 429×10 | 통과(정상 본문) |
| 6 | **IP 헤더 위조** | 아래 "IP 위조 위험 평가" | 로컬 peer + 헤더 회전 12/12 통과. 비루프백 peer는 헤더 무시(6/12). IPv6 /64 내 회전 12/12 통과 | 조건부(고칠 것 2) |
| 7 | 일일 예산 | 예산 8(예열 3 사용)로 기동, 5건 사용 뒤 새 계획서 | 소진 후 새 분석 **503 `budget_exhausted`**, 데모(캐시)는 **200 hit**, 감시 재시작 뒤에도 예산 사용량 유지(17번, `used: 4`) | 통과(정상 본문) |
| 8 | 차단 스위치 | 파일 `<data>/serving_block.flag` 생성, 별도 회차에 `NEUMANN_BLOCK_NEW=1` | 정상 본문: **503 `blocked`**(파일·환경변수 둘 다, 재시작 없이 파일 즉시 반영). 캐시 응답은 계속 | 통과(정상 본문) |
| 9 | **BOM·UTF-16 본문** | 같은 요청을 `\ufeff`+JSON, `utf-16` 인코딩으로 | 예산 소진 상태에서 **200 miss(분석 실행)**, 차단 스위치 켠 채 **200**(파일·환경변수 둘 다), 한 IP 12건 **12/12 통과**(한도 6), 동시 40건 **전부 200·대기 38**(상한 20), **15만 자 계획서 200**(상한 5만 자, 정상 본문은 413), 예산 카운터는 한도 8을 넘어 10까지 증가 | **실패** |
| 10 | 본문 바이트 상한 | 원시 소켓으로 Content-Length 거짓·chunked·과대 | `CL: 99,999,999`+작은 본문 → **413** 즉시. chunked 1MB → **413**. chunked 365.6KB(상한 직후) → 413. chunked 36만 바이트 `a` → 413(글자 상한, 현재 글자 수 안내). `CL`보다 실제 본문이 크면 h11이 **400**. `CL`+`TE` 동시 → 400. 업로드 11MB → 413 | 통과(BOM 제외) |
| 11 | 세 경로가 같은 관문에 묶임 | `/premortem`·`/premortem/view`·`/premortem/package`·`/upload/plan` 각각 | `/premortem` 26건 동시 → 200×22·503×4(view와 같은 분석 관문·큐). 내보내기·업로드는 보조 관문(동시 2·큐 10·시간 60초·분당 30): 업로드 41번째 429, 11MB 413. main에 `upload.py`가 없어(E4-L1a 미병합) 업로드 경로는 404로 응답했으나 관문(속도 제한·바이트 상한)은 라우트와 무관하게 적용됨. 업로드 파서 내부(DOCX 폭탄)는 이 과제 범위 밖(E4-L1a) | 통과 |
| 12 | package에 plan_text만 | `{"plan_text": ...}`, `{"plan_text":..., "result": null}`, 1,000,000자 | 422 "내보내기에는 분석 결과가 필요합니다…", **파이프라인 호출 0**, 1M자는 413. `result`를 실어 보내면 정상 ZIP(9파일 스모크: 11,913바이트, zip 유효). 단 422 요청이 예산 +1(고칠 것 3) | 통과(예산 소모 지적) |
| 13 | 오류 응답에 내부 정보 없음 | 파이프라인이 `RuntimeError("Incorrect API key provided: <가짜 키>… C:\Users\SECRET\…\llm.py … /home/x/y")`, `ValueError("boom <키>")`를 던지게, 정상 200 응답에는 `notices`·`stages.detail`에 경로·키·상류 API 문구를 심음. `/premortem/view`·`/premortem` 양쪽 | 응답 본문에서 키 조각(`FAKEVERIFIERKEY`·`sk-proj`), `C:\Users`, `SECRET`, `/home/x`, `llm.py`, `.py`, `Traceback`, `line N`, `Incorrect API key`, `platform.openai` **0건**. 500은 고정 문구+`요청 번호`+"(오류 종류: RuntimeError)"만. 정상 200의 `notices`는 `IndexNotBuilt: 색인이 없다: [경로] key=[가림]`으로 가려짐. 422는 입력을 되돌려 싣지 않음(`secretfield` 미노출). 깨진 JSON·잘못된 UTF-8도 422 고정 문구. `/docs`·`/openapi.json` 404. `/health`는 모듈 import 상태(모듈 이름)를 그대로 공개(낮음, 빌더 제안 4) | 통과 |
| 14 | 서버 로그에 본문·키 없음 | 5회 기동의 서버 출력 전체(합계 약 2,800줄)에서 grep | 가짜 키 조각 0, 계획서 본문 문구 0(`연구계획서`·`심층 신경망` 등), `Traceback` 0, `RAISE_ME`·`SECRET` 0. 요청 로그는 `ticket·ip_<해시>·path·plan_id 앞 12자·chars·status…`뿐, 예외는 "[트레이스 생략: RecursionError]" 한 줄로 줄어듦 | 통과 |
| 15 | 캐시: 디스크엔 데모만 | 첫 회차에 사용자 입력 200건 이상(정상·BOM·큐·합류·오류 포함) 뒤 `data/cache/results/` 확인, 5회차 모두 | `results/` 파일은 **정확히 3개(데모 3건 plan_id)**, 사용자 입력으로 늘어난 파일 0(회차 1·2·4·5). 파일에 계획서 줄 텍스트 없음(37개 줄 대조 0건 일치, `plan`은 `n_lines`뿐). 차단 상태로 기동한 3회차는 예열이 건너뛰어 0개. `data/` 밖 새 파일은 `serving_budget.json`(날짜·건수)과 `logs/serve.log`(감시 로그)뿐 | 통과 |
| 16 | `--public` 기동 거부 | 환경변수를 비운 하위 프로세스(최소 환경)로 `serve.py --public --dry-run` | 키 없음 → **exit 2**("OPENAI_API_KEY가 없다"). 가짜 키+provider=mock → **exit 2**. 가짜 키+openai → exit 0. 빈 문자열 키 → exit 2. provider=rule·`OPENAI`(대문자) → exit 2(설정 검증 오류). `--public` 없이는 점검 안 함(exit 0). 공백만 있는 키는 통과(권고) | 통과 |
| 17 | 감시·재시작 | 서버 자식 uvicorn 프로세스를 강제 종료 | 감시가 **1초 안에 재시작**(`재시작 #1 이유: 프로세스 종료(code=1)`), health 정상, 예산 파일 값 유지, 횟수·시각·이유가 표준 출력과 `logs/serve.log`에 기록 | 통과 |
| 18 | pytest 지정 필터 | worktree에서 `python -m pytest tests/e4 -q -k "serving or export" -p no:cacheprovider` | **60 passed**, 89 deselected, 3.5s | 통과 |
| 19 | verify.py | worktree에서 `python scripts/verify.py` | **476 passed, 19 skipped**, 보안 206개 파일, 계약 2개, `verify 통과`(빌더 보고 "489/6"과 skip 수가 다른 것은 `NEUMANN_EMBED_MODEL`·`NEUMANN_RAW_DIR` 유무 차이). 통합 사본(main+브랜치+패치) 전체 pytest도 **899 passed, 37 skipped**. worktree는 검증 후 `.pytest_cache`·`__pycache__`를 지워 `git status` 깨끗 | 통과 |
| 20 | 소유 경로·계약 | `git diff main...task/E4-L2c --stat` (11개 파일, +3,465/−76) | 새 파일: `api/serving.py`, `scripts/serve.py`·`serve_fake_app.py`·`serve_loadtest.py`, `tests/e4/test_serving*.py`, 보고서·부하 로그·패치(`docs/reports/`). 수정: **`api/export.py`(PM 위임분: `/premortem/package`의 plan_text→파이프라인 경로 삭제 + 422, 허용)**, `tests/e4/test_export.py`(옛 규칙 3건→새 규칙 2건). `contracts/`·`models.py`·`main.py`·`view.py`·`pyproject.toml` 변경 0, 데이터·비밀값·`.env` 추가 0 | 통과 |
| 21 | 테스트가 항상 통과하는가 | 위 9번 조작 입력(BOM·UTF-16)으로 직접 시험 | 빌더 테스트 34건은 **BOM·UTF-16 본문을 넣지 않아** 이 결함을 못 잡는다. 정상 본문에 대한 관문 시험은 실제로 실패할 수 있는 형태(순번·503·429·413·예산·차단 확인) | 결함 있음(고칠 것 1d) |

## IP 위조 위험 평가(cloudflared 뒤 전제)

`client_ip`(`serving.py:1065-1087`)는 직접 연결 peer가 루프백일 때만 `CF-Connecting-IP` → `X-Forwarded-For` 첫 값을 믿는다.

| 조건(실측) | 한도 6에 대한 결과 |
|---|---|
| peer=127.0.0.1(cloudflared 위치) + `CF-Connecting-IP` 회전 | 12/12 통과 |
| peer=127.0.0.1 + `X-Forwarded-For`만 회전 | 12/12 통과 |
| peer=127.0.0.1 + 헤더 없음 | 6 통과, 2 차단(전원이 한 통) |
| peer=이 PC의 LAN IP(비루프백) + `CF-Connecting-IP`·XFF 회전 | **6 통과, 6 차단(헤더 무시)** |
| 같은 IPv6 /64 안에서 `CF-Connecting-IP` 회전 | 12/12 통과 |

판단:
- cloudflared가 같은 PC에서 접속하므로 공개 트래픽 전부가 "루프백 peer"라 신뢰 조건은 항상 참이다. 따라서 속도 제한의 정확성은 (a) Cloudflare 엣지가 `CF-Connecting-IP`를 자기 값으로 채워 준다는 점(알려진 동작이며 이 검증에서 실제 터널로는 확인하지 못했다), (b) 127.0.0.1 바인딩으로 외부가 원본 포트에 직접 못 붙는다는 점에 기댄다. 이 둘이 지켜지면 **헤더 위조 자체는 위험이 낮다**. 호스트를 `0.0.0.0`으로 잘못 열어도 비루프백 peer는 헤더를 무시해 위조가 안 통한다(실측).
- 약점은 두 가지다. (1) `CF-Connecting-IP`가 없을 때 XFF **첫 값**을 믿는다. Cloudflare는 XFF에 클라이언트가 보낸 값을 앞에 남기므로 첫 값은 공격자 조작 대상이다. 공개 프로필에서는 XFF를 아예 무시하고 CF 헤더가 없으면 한 통(루프백)으로 세는 편이 안전하다. (2) **IPv6는 위조 없이** 한 사람이 /64 안의 주소를 바꿔 한도를 무력화한다(실측 12/12). /64 단위로 센다.
- 어느 쪽이든 속도 제한은 봇넷·다수 IP 앞에서 어차피 부분 방어다. 실제 상한은 일일 예산·대기열 상한이고, 그것이 지금 BOM 한 글자로 뚫린다(9번). 그러므로 현재 위험도는 **높음**, 고칠 것 1·2 뒤 **중간**(예산 200건이 하루 안에 소진되는 서비스 거부는 남는다. 데모 3건은 캐시로 계속 나온다).

## Cloudflare 약 100초 응답 제한 평가

- 근거: 빌더 수치(분석 60~70초, 동시 2). 요청이 원본에 도달한 뒤 응답이 100초 안에 안 오면 Cloudflare가 524를 낸다고 알려져 있다(이 검증에서 실제 터널로는 확인하지 못했고 실분석 시간도 실측하지 못했다). 이 서버의 요청 시간 상한 기본값은 300초라 그 전에 Cloudflare가 먼저 끊는다.
- 계산(분석 65초, 슬롯 2): 동시 사용자 k번째의 완료 시각 = ceil(k/2)×65초. **1~2번째만 65초에 끝나고 3~4번째는 130초, 5~6번째 195초…** 즉 동시 3명부터는 Cloudflare 524(JSON이 아닌 HTML 오류 페이지, 화면은 일반 실패로 보임)를 받는다. 심사위원 10명이 동시에 누르면 8명이 오류를 본다. 큐 상한 20은 마지막 사람이 약 11분을 기다리는 값이라 동기 API에서는 의미가 없다.
- 원본은 끊긴 뒤에도 분석을 끝까지 돌리므로 **아무도 받지 못한 분석에 비용이 든다**(`asyncio.shield`). 결과가 `status: ok`면 메모리 캐시에 남아 사용자가 같은 계획서를 다시 누르면 즉시 받지만(실측: 504 뒤 재시도가 `cache=hit`, 파이프라인 호출 증가 0), 강등 결과는 캐시되지 않아 재시도가 비용을 한 번 더 쓴다.
- 권고:
  1. **지금 바로(설정만):** `NEUMANN_REQUEST_TIMEOUT_S=90`으로 Cloudflare보다 먼저 JSON 504("잠시 뒤 같은 계획서로 다시 누르면 결과를 바로 받는다")를 돌려주고, 화면이 504를 받으면 같은 본문·같은 `X-Neumann-Ticket`으로 자동 재요청(합류라 비용·슬롯 추가 없음)한다. `NEUMANN_QUEUE_MAX`는 2~4로 줄여 대기가 100초를 넘을 요청은 처음부터 503 "잠시 후 다시"로 돌린다. 끝난 작업 결과를 상태와 무관하게 짧게 보관한다(위 권고).
  2. **비동기 작업 API가 필요한가: 필요하다(동시 시연이 목표라면).** `POST /premortem/view`가 입장 검사(차단·예산·큐)를 마치고 즉시 `202 {job_id, position, eta_s}`를 돌려주고, `GET /premortem/jobs/{job_id}`가 `{state, position, eta_s, result?}`를 준다. 작업 id는 무작위 128비트, 결과는 메모리에 10분 보관. 화면은 이미 1.5초 폴링을 하도록 설계돼 있어(`queue/status`) 응답 형식만 바꾸면 된다. 서빙 층은 이미 `plan_id`별 작업(`inflight`)과 티켓을 가지고 있어 변경 폭이 작다. 그러면 큐 상한을 다시 20 안팎으로 키워도 Cloudflare 제한과 무관하게 동작한다.
  3. 응답을 헤더 먼저 흘리고 20초마다 공백을 보내 연결을 유지하는 방법도 있으나 상태 코드를 미리 정해야 해서 오류 표시가 어렵다. 비동기 API가 낫다.

## 검증하지 못한 것

- 실제 cloudflared 터널 뒤의 `CF-Connecting-IP`·XFF 동작, 100초 제한의 실제 발생(오프라인·터널 없음).
- 실제 파이프라인·OpenAI를 부른 부하와 건당 비용(금지). 예산 200건의 금액 환산은 못 했다.
- E4-L1a `upload.py`는 main에 없어(미병합) 업로드 파서의 증폭(DOCX 폭탄·S-03)은 다루지 않았다. 임시 사본에 브랜치 `task/E4-L1a`의 `upload.py`를 잠시 얹어 본 시험에서는 해제 크기 17MB·58MB DOCX가 모두 413에 걸렸다(현재 브랜치 값, 이 과제 범위 밖).
- 병합 뒤 main에서의 동작: 위 패치는 임시 사본에 적용했을 뿐이다.

## 재현 절차(고칠 것 1)

```
서버: NEUMANN_PUBLIC=1 로 기동(예: 일일 예산 8 소진, 또는 NEUMANN_BLOCK_NEW=1, 또는 <data>/serving_block.flag 생성)
정상   : POST /premortem/view  {"plan_text": "<새 계획서>"}                  -> 503 blocked / budget_exhausted
BOM    : 같은 JSON 문자열 앞에 "\ufeff"를 붙여 UTF-8로 전송(Content-Type: application/json) -> 200 (분석 실행)
UTF-16 : json.dumps(...).encode("utf-16") 로 전송                              -> 200
```

한 IP에서 12건(한도 6) 12/12, 동시 40건 대기 38(상한 20), 15만 자 200(상한 5만 자)도 같은 방법이다.

## 재검증 (83754ff)

**PASS-조건부** — 1차 FAIL 원인(본문 인코딩으로 모든 관문 우회)은 **완전히 막혔다.** BOM·UTF-16·UTF-32·Content-Type 위조·중복 키·깨진 JSON 전부에서 차단 스위치·속도 제한·대기열·글자 상한·일일 예산이 작동했고(파이프라인 실제 호출 수로 확인), 업로드·내보내기·`/queue/status`·오류/로그 위생도 통과했다. 다만 (1) **관문 앞단의 다른 구멍 1건**을 새로 찾았고(계획서를 `plan_id`로 해시하기 전에 이메일 정규식이 이벤트 루프를 수 초 멈춘다: 49KB 요청 1건 = 서버 약 1.7초 정지, 8건 동시 = 약 14초, 차단 스위치를 켠 채로도), (2) 최신 main에 병합하면 E4-L1f 테스트 2건이 깨진다. 토큰 없는 공개 서버이므로 둘 다 **공개·병합 전에 고쳐야** 한다("고칠 것" 1·2번, 각각 작은 수정).

- 대상: 브랜치 `task/E4-L2c` HEAD `83754ff`(빌더 claude-opus-5.5). 검증자 claude-sonnet-5.5.
- 방법: 임시 폴더 두 곳(`Temp\v2_e4l2c` = main `99ee44e`, `Temp\v3_e4l2c` = main 최신 `f938469`)에 `git archive main` + 브랜치가 바꾼 11개 파일 + `docs/reports/E4-L2c_main.patch`를 얹어 만들었다(worktree·main 체크아웃은 건드리지 않았고, 검증 뒤 임시 폴더·데이터·로그를 삭제). `99ee44e` 이후 main 변경(templates·업로드 화면·테스트·보고서 등)은 L2c 파일·`main.py`와 겹치지 않는다(`git diff --name-only`로 확인). 서버는 **8143** 한 곳만 썼고(8010·8020 미사용) 종료·포트 닫힘을 확인했다. 모든 python·pytest·서버 명령에 `NEUMANN_LLM_PROVIDER=mock`을 명시했고 서버 프로세스에서 `OPENAI_API_KEY`를 unset했으며 사본에 `.env`가 없다. 서버는 `scripts/serve.py --app <검증용 앱>`이고 공개 프로필은 `NEUMANN_PUBLIC=1` 환경변수로 켰다(`--public`은 provider=openai를 요구해 mock으로는 일부러 기동을 거부한다. 그 거부는 따로 확인). 앱은 **실제로 패치된 `main.app` + 가짜 느린 파이프라인**이고, 파이프라인 함수가 불릴 때마다 파일에 한 줄 남겨 "분석이 실제로 몇 번 돌았는가"를 셌다. 실제 OpenAI 호출 0, bge-m3 적재 0, 하위 에이전트 0, 코드 수정 0, 프로젝트 git 쓰기 0(임시 폴더에서 `verify.py`가 `git ls-files`를 쓰므로 그 폴더 안에서만 `git init`).

### 1. 통합 사본 시험

| 항목 | 결과 |
|---|---|
| 패치 적용 | 최신 main에 `git apply --check`·적용 성공(`main.py`에 `serving.install`·`wrap_pipeline`) |
| 전체 `pytest -q`(main 99ee44e + 브랜치 + 패치) | **1107 passed, 44 skipped**(73초) |
| `python scripts/verify.py`(같은 사본) | 테스트 통과, 보안 374개 파일, 계약 2개, **verify 통과**(첫 시도는 사본에 둔 내 공격 스크립트의 가짜 키 문자열에 걸려 실패해서 스크립트를 치우고 다시 돌렸다) |
| 전체 `pytest -q`(main 최신 f938469 + 브랜치 + 패치) | **2 failed**, 1157 passed, 45 skipped. 실패는 `tests/e4/test_webui_upload.py::test_hwp_is_415_with_server_message`(hwp·hwpx 2건). main 단독은 19건 전부 통과, 패치를 얹으면 2건 실패: `serving.py:1497`이 4xx 응답 본문에 `request_id`를 덧붙이는데(`data.setdefault("request_id", ctx.ticket)`) E4-L1f 테스트가 `r.json() == {"detail": HWP_MESSAGE}`로 **정확히 같음**을 요구한다. 빌더의 마지막 main 병합(47e45e5)보다 뒤에 들어온 테스트라 빌더가 알 수 없었다. 화면은 `detail`만 읽으므로 기능 문제는 아니지만 병합하면 main의 verify가 깨진다 |
| 새 테스트가 옛 버그를 잡는가(돌연변이) | (A) 미들웨어를 `body.decode("utf-8")`로 되돌림 → `test_encoded_bodies_are_parsed_like_the_app_and_cannot_bypass_admission` 실패. (B) `run()` 2차 검사를 없앰 → `test_run_rechecks_admission_when_middleware_did_not_reserve` 실패. (C) 둘 다 + 읽지 못한 본문을 앱에 넘김 → 3건 실패. 원본 복원 확인. 두 겹의 방어가 각자 시험으로 지켜진다 |

### 2. 1차 공격 재현(서버 8143, 공개 프로필)

**차단 스위치를 켠 채(`NEUMANN_BLOCK_NEW=1`) — 파이프라인 호출 0 유지**

| 공격 | 결과 |
|---|---|
| `/premortem/view`·`/premortem` × 인코딩 11종(UTF-8, UTF-8 BOM, UTF-16 BOM, UTF-16 LE·BE BOM 없음, UTF-16 BE BOM, UTF-32 BOM, UTF-32 LE·BE BOM 없음, 앞 공백, ASCII 이스케이프) | 22건 전부 **503 blocked** |
| Content-Type 위조 10종(text/plain, form-urlencoded, multipart, `charset=utf-16` 표기, `+json`, text/json, jsonx, 없음, 빈 값, 대문자) × (평문·BOM) | 20건 전부 **503 blocked** |
| 중복 키 `{"plan_text":"a","plan_text":"<15만자>"}`와 순서 뒤집기, BOM·UTF-16 판 | 마지막 값이 기준(앱과 같음): 15만자면 **413**, `a`면 503. 15만자 평문·BOM·UTF-16·UTF-32 전부 **413** |
| 잘못된 JSON, 뒤에 쓰레기, 10만 단계 중첩(2모양), 5,000자리 정수, plan_text가 정수·null·목록·객체·빈 문자열·공백·키 없음·배열 본문·문자열 본문·빈 본문, 잘못된 UTF-8, 잘린 UTF-16, BOM만, NUL 바이트, 대문자 키 | 전부 **422**(앱 호출 0). NaN·`\ud800` 이스케이프·`\u0070lan_text` 키는 앱과 같이 읽혀 503 |
| 경로 변형 16종(`/premortem/view/`, `//premortem/view`, `;x=1`, `/./`, `/../`, `%70`, `%76`, `%2F`, `%00`, 대문자, `//`, 절대 URI, 쿼리·프래그먼트, `/premortem/`, `/premortem`) + PUT·PATCH·DELETE·GET·HEAD·OPTIONS | 보호 경로로 해석되는 8건은 503, 나머지 8건은 404, 다른 메서드는 405. 앱까지 새는 것 없음 |

**일일 예산 3**(`NEUMANN_DAILY_BUDGET=3`, 예열 끔): 서로 다른 계획서·IP 24건 동시(인코딩 6종 혼합) → **200×3, 503 budget_exhausted×21**, 파이프라인 호출 정확히 **3**, 예산 파일 `used: 3`. 소진 뒤 인코딩 6종과 `/premortem`의 BOM 본문 전부 503.

**기본 공개 프로필**(동시 2·대기 4·분당 6·예산 200): 40건 동시(서로 다른 계획서·IP, 인코딩 6종 혼합) → **200×6(실행 2 + 대기 4), 503 busy×34**, 파이프라인 호출 +6, 인코딩별 편차 없음. 같은 IP 12건(인코딩 혼합) → 200×6·**429×6**. 글자 상한: 50,001자 → UTF-8·BOM·UTF-16·UTF-32·UTF-16 BE 전부 **413**, 정확히 50,000자 200, 이모지 50,000자(약 200KB) 200·50,001자 413, 공백 60,000자 413. **예산 카운터 = 파이프라인 호출 수**가 시험 내내 일치(62=62, 65=65, 72=72, 다른 회차 9=9): 422·413·429·503으로 끝난 요청의 예산·자리 환불이 정확하다. 디스크 캐시는 데모 3건뿐.

**본문 바이트 상한(분석 경로, 365,536B)**: `Content-Length: 99999999`+작은 본문 → 413 즉시, `Expect: 100-continue`+큰 CL → 413(본문 수신 0), chunked 400KB → 413, chunked 1MB·10MB → 서버 로그에 413(연결이 먼저 끊겨 클라이언트는 응답을 못 받음), CL+TE 동시·음수·`0x10`·20자리 CL → 400, CL이 실제 본문보다 작으면 앞부분만 읽고 422. 같은 계획서를 6가지 인코딩·30개 IP로 30건 동시 → 200×30, 파이프라인 +1·예산 +1(합류).

**같은 티켓 남용**: 서로 다른 계획서 20건이 모두 같은 `X-Neumann-Ticket`을 달아도 200×6·503×14, 호출 +6(충돌 티켓에 접미사가 붙어 상한 유지). 규칙에 안 맞는 헤더 값은 무시되고 새 티켓이 발급된다.

### 3. IP 집계·헤더 위조 평가(cloudflared 뒤 전제)

| 시험(분당 6) | 결과 |
|---|---|
| 같은 IPv6 /64 안에서 호스트 비트만 바꿔 12건 | 200×6·429×6 |
| 같은 /64를 확장형·대문자·`[..]`·`%zone` 표기로 섞음 | 같은 통(12/12 429) |
| 서로 다른 /64 6개 | 각각 통과 |
| IPv4 3건 뒤 `::ffff:198.51.100.77`·`::ffff:c633:644d` | IPv4와 한 통(합쳐 3 통과 뒤 429) |
| CF 헤더 없이 `X-Forwarded-For` 회전 12건 | 한 통(6/6): **XFF 무시 확인** |
| CF 헤더 고정 + XFF 회전 12건 | CF 헤더 기준(6/6) |
| `X-Real-IP`·`True-Client-IP`·`Forwarded` 회전(CF 헤더 없음) | 무시. 앞선 XFF 시험이 `127.0.0.1` 통을 이미 소진해 12/12 429 |

판단: 코드는 직접 연결 peer가 루프백일 때만 `CF-Connecting-IP`를 믿는다(`client_ip`). cloudflared가 같은 PC의 루프백으로 붙으므로 신뢰 조건은 늘 참이고, 정확성은 (a) Cloudflare 엣지가 클라이언트가 보낸 `CF-Connecting-IP`를 자기 값으로 덮어쓴다는 점, (b) 서버가 127.0.0.1에만 바인딩돼 원본 포트로 직접 못 온다는 점에 기댄다. 둘 다 이 검증에서 **실제 터널로는 확인하지 못했다.** 이 전제가 지켜지면 헤더 위조 위험은 낮고, 어긋나도 비루프백 peer는 헤더가 무시된다(1차에서 실측). 브라우저의 교차 출처 요청은 사용자 지정 헤더에 CORS 사전 요청이 필요한데 CORS가 없어 로컬 웹페이지가 헤더를 위조해 보낼 수 없고, 헤더 없이 온 요청은 `127.0.0.1` 한 통으로 묶여 무해하다. 남는 약점은 **더 큰 IPv6 대역**이다. /56·/48을 받은 공격자는 /64 통이 256개 이상이라 속도 제한만으로는 못 막고, 실제 상한은 게이트 처리량이다(아래 권고 3).

### 4. 업로드 `/upload/plan`

- Content-Type: JSON 본문+`application/json`, **BOM JSON, UTF-16 JSON, UTF-32 JSON**, text/plain, 없음 → 전부 **415**. `multipart/mixed` 415. boundary 없음·빈 값 **400**. `Content-Type` 헤더 값 앞에 BOM 바이트(`EF BB BF`)가 붙으면 415, NUL이 섞이면 400. (대문자 `MULTIPART/FORM-DATA`는 200: 앱과 같은 파서라 앱과 같은 판단.)
- 속도 제한: 같은 IP 12건 → 200×10·429×2(분당 10). IPv6 /64 회전도 200×10·429×2. 415로 거절되는 요청은 통을 쓰지 않는다(값싼 응답이라 무해).
- 동시 1건/IP: 같은 IP 4건 동시(docx) → 200×1·**429 busy_ip×3**, IP 4개 → 200×4(2건은 대기), 끝난 뒤 같은 IP 다시 200.
- 크기: `Content-Length` 11MB → 413, `CL: 99999999` → 413, `CL: 100`이라 적고 11MB를 흘려도 앞 100바이트만 앱에 가고(앱이 400) 초과분은 버려지며, chunked 11MB → 서버 로그 413(연결이 먼저 끊겨 응답은 못 받음), 9MB md는 관문을 통과해 앱이 글자 상한으로 413.
- **분석 제한 우회 불가**: 업로드 시험 전체에서 파이프라인 호출 0, 예산 무변동. 업로드는 텍스트만 돌려주며 분석은 다시 `/premortem/view`의 관문을 거쳐야 한다.

### 5. package·오류·로그·공개 응답

- `/premortem/package`에 plan_text만 → **422**(평문·BOM·UTF-16·`result:null` 모두), 예산 62→62, 파이프라인 호출 62→62, 분석 슬롯 0. 보조 관문 분당 30: 34건 → 422×30·429×4.
- 파이프라인이 `RuntimeError("Incorrect API key provided: FAKE… C:/SECRET/llm.py /home/x/y")`를 던지게 한 6건(`/premortem/view`·`/premortem` × UTF-8·BOM·UTF-16) 응답: 키 조각·`SECRET`·`llm.py`·`/home/x`·`Traceback`·`Incorrect API key`·`C:\`·`.py", line`·`sk-`·`AppData`·`site-packages` **0건**. 500은 고정 문구+요청 번호+(오류 종류: RuntimeError)뿐. 422는 보낸 필드를 되돌려 싣지 않음(`secretfield` 미노출). `/docs`·`/redoc`·`/openapi.json` 404.
- 서버 로그 652줄 전수 검색: 가짜 키 조각·`SECRET`·`llm.py`·`/home/x`·`Traceback`·`sk-proj`·계획서 본문 문구·`RAISE_ME` **0건**. 파이프라인 실패는 `RuntimeError @ v2_app.py:15`(파일 이름·줄)까지만. 감독자 시작 줄에 로그 파일 경로가 한 번 나온다(운영자 콘솔 전용, 사용자 응답 아님). python-multipart가 잘못된 본문에서 `Expected boundary character 45, got 97 at index 2` 한 줄을 표준 출력에 남긴다(바이트 코드 몇 개, 본문 문구 아님, 낮음).
- 공개 `/queue/status` 키: `accepting·active·aux·avg_run_s·blocked·eta_new_s·limits·max_active·max_waiting·waiting`. **예산 수치·counters·cache·warmup 없음.** 다만 `limits`(rate_per_min·queue_max·request_timeout_s·max_plan_chars)가 남고 `accepting=false`가 예산 소진에도 켜져 소진 여부를 추론할 수 있다(낮음).
- `run()` 2차 검사를 미들웨어 없이 직접 시험: 차단·예산 소진·대기열 가득·속도 제한 각각 `AdmissionRefused`, 파이프라인 호출 0.
- `serve.py --public --dry-run`(provider=mock): **exit 2(기동 거부)**, `--public` 없이는 점검 안 함(exit 0). provider=mock이 키 검사보다 먼저 걸리므로 공백 키 경로는 이번에 따로 실행하지 않았고(openai 값 사용 금지) 단위 시험 `test_serve_public_preflight_refuses_whitespace_key` 통과로 갈음.

### 6. diff 범위

- `git diff main...task/E4-L2c --stat`: **11개 파일**(`docs/reports/E4-L2c.md`·`_loadtest.txt`·`_main.patch`, `scripts/serve.py`·`serve_fake_app.py`·`serve_loadtest.py`, `src/neumann/api/export.py`, `src/neumann/api/serving.py`, `tests/e4/test_export.py`·`test_serving.py`·`test_serving_sec.py`). `contracts/`·`models.py`·`main.py`·`view.py`·`pyproject.toml`·`.env` 변경 0.
- **E4-L1e 파일(templates/·index.html·test_templates) 혼입 0**: `git log main..task/E4-L2c --name-only` 15개 커밋 전체에 해당 경로 0건, 병합 커밋 `651718b`는 main 쪽 부모(`47e45e5`) 대비 diff가 위 11개 파일뿐(`git diff --stat 47e45e5 651718b`), `git stash list` 비어 있음, worktree `git status` 깨끗.
- 소유 목록에 없는 것: `tests/e4/test_export.py` 수정은 `export.py` 위임분(plan_text→파이프라인 경로 삭제, 422)의 동반 수정이라 허용 범위로 본다. `main.py`는 브랜치가 고치지 않고 패치 파일로만 제공한다(병합 때 PM이 적용).

### 새로 찾은 것: 이메일 정규식이 이벤트 루프를 멈춘다 (높음)

`serving.py`의 `plan_key()`가 미들웨어에서(속도 제한·차단·예산 검사보다 **앞서**, 이벤트 루프 위에서) `neumann.models.redact_pii`를 부른다. `models.py:43`의 `EMAIL_RE = [A-Za-z0-9._%+\-]+@…`는 `@` 없이 길게 이어진 글자에서 제곱 시간이 걸린다.

| 입력(50,000자 안팎) | `plan_key` 시간 |
|---|---|
| `"a"*50000` | 1,830ms |
| `"x@" + "a."*25000` | 2,370ms |
| `"0-"*25000` | 2,670ms |
| 일반 한글 5만 자 | 27ms |

실서버 실측(가짜 파이프라인·공개 프로필, 계획서 `"a"*49000`):
- **차단 스위치를 켠 채 1건 = 1.66초**(503으로 끝나는데도), **서로 다른 IP 8건 동시 = 13.9초**, 그동안 `/health` 응답 최대 **10.5초**(파이프라인 호출 0). 속도 제한도 차단 스위치도 이 앞에서는 못 막는다.
- 기본 프로필에서 6건 동시(분석이 실제로 돌 때): `/health` 최대 **18.1초** 정지. 파이썬 `re`는 GIL을 쥔 채 끝까지 돌므로 분석이 스레드에서 돌아도 같다(실제 파이프라인의 `PlanDocument.from_text`도 같은 정규식이라 분석 1건마다 약 2초 정지. 이쪽은 관문을 통과한 요청만 해당).
- 감독 스크립트는 `/health`가 10초 안에 안 오면 실패로 세고 3회 연속이면 재시작한다. 이번 시험의 최대 정지는 18초라 재시작이 실제로 일어나지는 않았지만, 49KB 요청을 계속 보내면 가능한 크기다(재시작하면 대기열·메모리 캐시가 사라진다). 토큰이 없어 누구나 보낼 수 있다.

원인은 이번 재작업이 아니라 1차부터 있던 설계(관문 앞 해시)와 E0b `EMAIL_RE`의 결합이라 1차 검증도 놓쳤다. 고칠 곳(함께 권장):
1. `models.py`의 `EMAIL_RE`를 선형으로: 앞에 `(?<![A-Za-z0-9._%+\-])`, 로컬 파트 `{1,64}`로 제한. 임시 시험에서 `"a"*50000` 0.5ms, 점 이어진 도메인 6.8ms로 줄었다(**의미가 같은지, 다른 적대 입력에서도 빠른지는 고치는 쪽이 12개 이상 패턴으로 재측정**해야 한다. `models.py`는 E0b 소유라 PM 결정 필요).
2. `serving.py`: 본문 파싱·해시 이전에 IP별 값싼 사전 제한(보호 경로 POST를 IP당 분당 N건)을 두고, 가능하면 `plan_key`를 캐시·합류 판단이 꼭 필요한 요청만 하도록 관문 뒤로 미룬다. 정규식이 그대로면 (2)만으로는 IP를 바꾸는 공격을 못 막으므로 (1)이 본 해결이다.

### 고칠 것

**공개·병합 전 필수**
1. 위 이메일 정규식 정지. 수정 뒤 "차단 스위치를 켠 채 `"a"*49000` 8건 동시일 때 `/health` 1초 미만"으로 재측정.
2. **병합 충돌**: `tests/e4/test_webui_upload.py::test_hwp_is_415_with_server_message` 2건이 패치 적용 후 실패. `serving.py:1497`의 4xx `request_id` 덧붙임을 업로드(하위 앱이 만든 4xx)에서는 빼거나(티켓은 `X-Neumann-Ticket` 헤더로도 나간다) E4-L1f 테스트를 `r.json()["detail"] == HWP_MESSAGE`로 완화. 어느 쪽이든 최신 main+패치로 전체 pytest를 다시 돌려 0 failed 확인.
3. `scripts/serve.py`가 표준 출력이 파일로 리다이렉트된 한국어 Windows(cp949)에서 첫 로그 줄(`—` 문자)에서 `UnicodeEncodeError`로 죽는다(`serve.py --public --dry-run > out.txt` 재현: exit 1, 거부·통과 경로가 같은 줄). 기동이 안 되는 쪽으로 실패하므로 안전하지만 운영 스크립트가 리다이렉트하면 서버가 안 뜬다. `main()` 첫머리에 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` 또는 실행 스크립트에서 `PYTHONUTF8=1`.

**권고(비차단)**
4. **예산 기본 끔(대표 결정)**의 최악 비용을 문서에 못박는다: 동시 2·분석 약 60~70초면 처리량 상한이 하루 약 2,500~2,900건이다(24시간 포화 시). 건당 비용을 곱한 값이 상한이고, OpenAI 프로젝트 키의 월 지출 한도가 유일한 외부 최후 방어선이다.
5. 본문 읽기 시간 제한 없음(1차 권고 미반영): 반쯤 보낸 연결 300개를 20초 넘게 붙잡아도 서버가 끊지 않았다(게이트 자리는 안 쓰고 `/health` 정상). Cloudflare가 앞단에서 완화하므로 낮음.
6. 캐시 적중·합류는 속도 제한이 없다(1차 권고 미반영, 낮음). `/queue/status`의 `accepting`·`limits` 노출(낮음).
7. Cloudflare 100초: 기본값(90초·대기 4)은 반영됐지만 분석 65초·동시 2에서는 3번째 사용자부터 대기가 90초를 넘어 504다(같은 계획서로 다시 누르면 합류). 비동기 작업 API는 E4-L2d에서 다룬다는 빌더 기록을 확인했다.

### 검증하지 못한 것

- 실제 cloudflared 터널 뒤의 `CF-Connecting-IP` 덮어쓰기와 100초 제한(오프라인·터널 없음). 위 판단은 문서화된 동작과 코드에 근거한다.
- 실제 파이프라인·OpenAI 부하와 건당 비용(금지). `serve.py --public`의 openai 성공 경로는 실행하지 않았다.
- 이메일 정규식 수정안의 의미 동등성(위 1번)과 실제 파이프라인 `from_text`의 정지 시간.
