# SEC-1 보안·정직성 점검 보고서

- 점검자: Claude Sonnet 5.5 (코드를 고치지 않음, git 쓰기 조작 없음)
- 점검 대상: main `82146f9`와 모든 `task/*` 브랜치의 점검 시점 끝 커밋(아래 "점검 범위"), 각 worktree의 커밋 안 된 작업 파일(읽기만)
- 전제: 이 서버는 곧 터널로 인터넷에 공개되고 접근 토큰이 없다(대표 승인)

## 판정: 조건부 (공개 전 고칠 것 있음)

- 저장소는 깨끗하다. 비밀값·데이터 원본·라이선스 자료는 main·모든 브랜치·전체 이력·worktree 어디에도 없다. 화면(XSS)과 경로 이동도 안전하다.
- 그러나 **공개 서버로는 아직 못 연다.** 접근 토큰이 없는 상태에서 비용 폭주와 서비스 거부를 막는 장치가 main에도, 병합 대기 중인 어느 브랜치에도 완성돼 있지 않다(E4-L2c는 작성 중). 오류 메시지로 내부 경로와 상류 API 오류 문구가 나간다. 업로드 하나로 CPU를 수십 초 붙잡을 수 있다.

### 공개 전 반드시 고칠 것 (번호는 아래 발견 번호)

| # | 고칠 것 | 심각도 | 소유(제안) |
|---|---|---|---|
| S-01 | 분석 비용 상한: 대기열 상한·IP별 속도 제한(터널 뒤 IP 처리 포함)·**전역 일일 예산 상한과 차단 스위치**·본문 바이트 상한. OpenAI 프로젝트 자체에도 월 한도를 건다 | 높음 | E4-L2c + PM |
| S-02 | `POST /premortem/package`가 동시성 제한·속도 제한을 우회해 파이프라인(LLM)을 돌리고 1,000,000자까지 받는다. plan_text 경로를 없애거나 같은 관문으로 묶는다 | 높음 | E4(export)·PM |
| S-03 | 업로드 증폭: 127KB DOCX 하나가 서버 37초·응답 24.8MB를 만든다. DOCX 압축 해제 상한을 낮추고, 추출 글자 수 상한과 동시 처리 상한·시간 상한을 건다 | 높음 | E4-L1a |
| S-04 | 예외 메시지·상류 API 오류 문구가 응답과 화면으로 나간다(내부 절대 경로, 키 조각 가능). 응답에는 분류 문자열과 HTTP 코드만 싣는다 | 중간 | E3(pipeline·llm)·E4 |
| S-05 | mock provider 결과가 `status: ok`에 배너 없이 "분석 파이프라인 연결"로 나갈 수 있다. 공개 모드는 provider가 openai가 아니면 기동을 거부하거나 화면에 크게 표시한다 | 중간 | E4·PM |
| S-06 | 계획서가 OpenAI로 전송된다는 고지와 "기밀·개인정보 입력 금지" 문구가 화면에 없다. 결과 캐시(E4-L2c)가 계획서 본문을 디스크에 남기지 않게 한다 | 중간 | E4·PM |

이 밖의 중간·낮음 항목은 병합 전후에 처리해도 된다.

---

## 점검 범위와 방법

- main `82146f9` + 브랜치 끝 커밋: E1-L0 `d86f8ec` · E1-L1b `cafc09d` · E1-L2 `64b597d` · E1-L3 `a525038` · E2-L0 `427dcb0` · E3-L0 `b516cb4` · E3-L1a `74bbe79` · E3-L1b `2fbd01e` · E3-L1c `bde6e91` · E4-L0 `da093af` · E4-L1a `88e5aa2` · E4-L1b `4393add` · E4-L1d `381330d` · E4-L2a `ea53a8a` · E4-L2b `c1095de` · E4-L2c `66e76c7` · E5-L0 `7eac570` · E5-L0e2e `372fd70` · E5-L1a `5bc8f7f` · E5-L2a `8eb01ec` · E5-L3a `f41a7e5` · E6-L2a `ee0d7b4` · E6-L3a `347bd34` · E6-L3b `3f4396f` · E6-docs `1f56789` (다른 빌더들이 점검 중에도 커밋했다. 위는 마지막으로 읽은 값이다).
- 비밀값: `python scripts/verify.py --security`(통과, 파일 125개), 전체 이력 `git log --all -p` 패턴 검사, main과 worktree 27곳(main 포함 28곳)의 파일 2,316개 검사. 환경변수의 실제 OpenAI 키 값과 글자 그대로 대조는 메모리 안에서만 했고 값은 출력하지 않았다. `.env`는 직접 열지 않았다(`verify.py`는 도구 안에서 스스로 읽으며 값을 출력하지 않는다).
- 서버 동작: main + E3-L0(pipeline·llm) + E4-L1a(upload) + E6-L2a(precomputed) + E2-L0(index) + E3-L1a·L1b를 스크래치 폴더에 합친 임시 트리를 만들어 **8126번 포트**로 띄웠다(mock provider, `OPENAI_API_KEY`는 그 프로세스에서 제거, 색인 없는 빈 데이터 폴더). 점검 뒤 종료하고 임시 트리를 지웠다. 실제 OpenAI 호출은 0회, 8010번 서버는 건드리지 않았다.
- 못 한 것(한계): 실제 OpenAI 오류 문구(오프라인으로 가짜 클라이언트 모사만 했다), 실제 터널(cloudflared)의 클라이언트 IP 헤더 동작, 스크린샷 png의 화소 단위 검사, 미병합 E4-L2c의 병합 뒤 동작. 병합된 뒤 같은 절차로 재점검이 필요하다.

---

## 1. 비밀값 — 통과

| 확인 | 결과 |
|---|---|
| `python scripts/verify.py --security` | 통과(추적·미추적 125개 + 전 브랜치 커밋 메시지) |
| 전체 이력(`git log --all -p`, 1.8MB) 키 패턴 8종 + 환경변수 실제 값 | 0건 |
| main 및 worktree 파일 2,316개 (28곳 중 .git·폰트·바이너리 제외) | 0건 (worktree 안 커밋 안 된 파일 포함) |
| `.env`류·`data/`·parquet·zip 등 금지 파일이 어느 브랜치 이력에도 추가된 적 있나 | 없음(`.env.example`만) |
| `.env.example` | 비밀값 칸이 전부 비어 있음 |
| 커밋 메시지·작성자 | 키 형태 0건, 136개 커밋 전부 GitHub noreply 주소 |
| 라이브 테스트 | 전부 `NEUMANN_LIVE_TESTS=1`일 때만 실행. `tests/conftest.py`가 기본으로 provider를 mock으로 고정 |

발견(낮음)
- **SEC-L1 낮음 · main `AGENTS.md:8-9`, `docs/HANDOFF.md:8-25`, `.claude/launch.json`, `.claude/settings.json`, `scripts/codex_task.sh:8` 등 · 로컬 절대 경로 노출.** Windows 사용자 이름, 자료 폴더, cloudflared·ffmpeg 설치 경로가 공개 저장소에 있다. 비밀값은 아니지만 공개 전에 필요 없다면 일반화한다. 재현: `git grep -nE "C:[/\\\\]+Users" main`.
- **SEC-L2 낮음 · `scripts/verify.py` 보안 검사 범위.** 현재 체크아웃의 파일과 커밋 메시지만 본다. 다른 브랜치·이력의 패치 내용은 안 본다. 이번 점검에서 이력 전체를 따로 검사해 0건이었지만, push·태그 전에 `git log --all -p` 검사를 `--security`에 넣으면 안전하다.

---

## 2. 공개 서버

### S-01 [높음] 비용 폭주·서비스 거부 방어 없음
- 위치: main `src/neumann/api/main.py:52-53`(`MAX_PLAN_CHARS=200_000`, `MAX_CONCURRENT=2`), `:90-97`(세마포어), `:151-163`(`_run_pipeline`); `task/E4-L2c` 브랜치는 main과 같은 커밋(`serving.py`만 작성 중, 미병합)
- 현황
  - 세마포어는 동시 실행만 2로 막는다. **기다리는 요청 수 상한이 없다.** 기다리는 동안 요청 본문(최대 200,000자)이 메모리에 그대로 남는다.
  - IP별 속도 제한, 일일·월 예산 상한, 본문 바이트 상한이 없다. 실측: 60MB JSON을 그대로 받아 버퍼링한 뒤 422를 돌려줬다(0.78초). 20MB를 보내면 422 본문이 입력을 20MB 그대로 되돌려 준다(대역폭 두 배).
  - 분석 1건이 부르는 LLM 수(코드 기준 추정): 검색어 1 + 지적 추출(유사 연구 최대 10편 × ceil(문장/50) 묶음, 최대 24병렬, 출력 상한 16k) + 카드 합성 1(출력 16k) + 예상 심사평 1~2 + 체크리스트 ceil(카드/3) + 2차 검증 ceil(카드/3). 계획서 본문은 검색어·합성·심사평·체크리스트·검증 입력에 **잘림 없이** 들어간다. 지적 추출은 코퍼스 문장 해시로 캐시되지만 나머지는 계획서마다 새로 부른다. 계획서 끝에 임의 글자를 붙이면 결과 캐시(E4-L2c 예정)도 비켜 간다.
  - `extract_issues`는 단계 시간 상한을 넘기면 `pool.shutdown(wait=False, cancel_futures=True)`로 끝낸다. 이미 나간 호출은 계속 돌아 과금된다.
  - LLM이 "연구계획서인가"를 판정하므로(`queries.py`), 계획서 아닌 글도 판정 호출 1회 비용은 든다. 프롬프트 인젝션으로 판정을 뒤집어 전체 파이프라인을 태울 수도 있다(보안 침해는 아니고 비용 문제).
- 재현: 서버를 띄우고 `POST /premortem`에 서로 다른 계획서를 병렬로 계속 보낸다. 대기열이 무한히 늘고 요청마다 LLM이 호출된다(mock provider로는 호출 수만 셀 수 있다).
- 권고
  1. 대기열 상한(예: 4~20)과 초과 시 503, 대기 시간 상한.
  2. IP별 속도 제한. **터널 뒤에서는 `request.client.host`가 터널 주소라 전 사용자가 한 통을 공유한다.** E4-L2c의 `client_ip`(CF-Connecting-IP, 없으면 XFF 마지막 값)처럼 터널이 붙인 헤더를 쓰되, 서버가 터널 외 경로로 열려 있으면 헤더가 위조되므로 127.0.0.1 바인딩을 지킨다.
  3. **전역 일일 예산 상한**(LLM 호출 수·토큰 합계, `LLMResult.usage` 이용)과 소진 시 "오늘 한도 소진" 안내 + 사전 계산본 안내. IP 제한만으로는 여러 IP·캐시 우회를 못 막는다.
  4. 본문 바이트 상한을 ASGI 미들웨어에서(현재 값 20MB+가 통과한다). 계획서는 50,000자(E4-L2c 값)가 알맞다.
  5. OpenAI 쪽에서 이 키(또는 전용 프로젝트 키)에 월 지출 한도를 건다. 코드가 뚫려도 최악의 금액이 정해진다. 공개 기간이 끝나면 키를 폐기한다.
  6. 병합될 E4-L2c 기본값 `NEUMANN_RATE_PER_MIN`은 공개 모드에서만 6이고 그 밖에는 0(끔)이다(`serving.py:167`). 공개 실행 스크립트가 공개 모드를 확실히 켜는지 확인한다.

### S-02 [높음] `/premortem/package`가 제한을 우회해 파이프라인을 돌린다
- 위치: main `src/neumann/api/export.py:52`(`MAX_PLAN_CHARS=1_000_000`), `:860-868`(`PackageRequest`), `:889-906`(`_run_pipeline`), `:913-947`(`premortem_package`, 동기 함수라 스레드풀에서 실행)
- 현황: 본문에 `plan_text`만 보내면 `run_premortem`이 돈다. main.py의 세마포어가 없으므로 스레드풀 크기(기본 약 40)만큼 동시에 LLM 분석이 뜬다. 글자 상한은 `/premortem`의 5배다. E4-L2c 작성본의 `PROTECTED_PATHS`도 `/premortem`, `/premortem/view` 둘뿐이라(`serving.py:65`) 이 경로는 보호 밖이다. `result`(dict)는 크기 제한이 없다.
- 재현: `POST /premortem/package {"plan_text": "<1,000,000자>"}`를 여러 개 동시에. 실측으로 mock에서 200(0.5초)이었다.
- 권고: 화면이 이미 결과를 갖고 있으므로 패키지는 `result`만 받도록 하고 plan_text 경로(파이프라인 실행)를 없앤다. 남기려면 `/premortem`과 같은 관문·속도 제한·글자 상한을 적용한다. `result`에도 바이트 상한을 건다.

### S-03 [높음] 업로드 증폭(DOCX 폭탄·CPU 점유)
- 위치: `task/E4-L1a:src/neumann/api/upload.py:40`(`MAX_DOCX_UNCOMPRESSED=100MB`), `:279-292`(`_extract_docx`), `:486-502`(응답에 `text` 전체), `:38`·`:193-231`(PDF 300쪽)
- 재현(측정): 127,231바이트 DOCX(압축 해제 37.2MB의 반복 문단)를 `POST /upload/plan` → **응답까지 37.3초, 응답 본문 24.8MB.** 상한(100MB)까지 채우면 요청당 약 100초·66MB로 늘어난다. 동시 처리 상한이 없어 몇 건이면 CPU가 찬다. 응답에 글자 수 상한이 없다(뒤에 `/premortem`이 200,000자로 거절하므로 쓸모도 없다).
- 잘된 점: 10MB 초과는 413(11MB 실측 확인, Content-Length 선검사 + 스트림 누적 검사), 디스크에 쓰지 않음, 파일명 경로 성분 제거(`../../etc/passwd.md` → `passwd.md`), HWP 415, 손상 파일은 고정 문구 422.
- 권고: DOCX 압축 해제 상한을 계획서에 맞게 낮춘다(10MB 안팎), 압축비·항목 수 상한. 추출 글자 수가 계획서 상한을 넘으면 413. 업로드 파싱은 별도 동시 상한(1~2)과 시간 상한(프로세스로 분리해 강제 종료)에서 돌린다. PDF도 같은 상한을 적용한다. `/upload/plan`도 속도 제한 보호 경로에 넣는다.

### S-04 [중간] 예외 메시지·상류 API 오류 문구 노출
- **내부 절대 경로**: `task/E3-L0:src/neumann/pipeline.py:82`, `:206`, `:399`가 `f"{type(exc).__name__}: {str(exc)[:200]}"`를 `StageStatus.detail`·`notices`에 넣는다. 응답의 `stages[].reason`, `notices`, `/premortem/view`의 `_status.notices`, `stages_not_ok[].reason`으로 나가고 화면(`index.html:486-487`)이 그대로 그린다.
  - 재현(실측): 색인이 없는 데이터 폴더로 띄우고 `POST /premortem/view` → `_status.notices`에 `IndexNotBuilt: 색인이 없다: C:\Users\...\index\manifest.json (python scripts/build_index.py)`가 그대로 들어 있었다(사용자 이름·폴더 구조 노출). OSError·SQLite·torch 오류도 같은 경로로 나온다.
- **상류 API 오류 문구**: `task/E3-L0:src/neumann/llm.py:225`가 `HTTP {code} {_short_api_message(exc)}`(API가 준 message 160자)를 `detail`에 넣고, `reason()`(`:89-93`)이 `StageStatus.detail`·notices("비상 규칙 경로: …")로 옮기며 `:245`가 로그에도 남긴다.
  - 재현(오프라인, 가짜 클라이언트로 401 예외를 던짐): `reason()`이 `openai:gpt-6-astra api_error (HTTP 401 Incorrect API key provided: <가려진 키 조각>. You can find your API key at …)`를 돌려줬다. 실제 OpenAI의 401 문구는 키 앞부분과 끝 4자를 담는 것으로 알려져 있다(이번에 실호출로 확인하지는 않았다). 키가 잘못되거나 한도가 소진된 순간 그 문구가 공개 화면에 뜬다. 429·400 문구에는 조직 정보나 한도 수치가 들어갈 수 있다.
- 그 밖: main `main.py:166-170` `_failure_reason`이 `@ 파일명:줄`을 붙인다(코드 구조 노출, 낮음). `main.py:214-233` `/health`가 모듈 import 상태·예외 종류·내부 라우터 이름을 공개한다(낮음). `/docs`·`/redoc`·`/openapi.json`이 열려 있다(낮음). 기본 422가 입력을 통째로 되돌려 준다(위 S-01). `export.py:947`은 `str(exc)`를 422에 싣지만 사용자 입력에서 온 ValueError라 낮다.
- 권고: 공개 응답·화면·로그에 예외 메시지를 싣지 않는다. 분류 문자열(timeout·api_error·schema_invalid)과 HTTP 코드, 서버 로그 참조 id만 싣는다. E4-L2c 작성본의 `scrub_secrets`·`RedactingFilter`는 방향이 맞지만 경로 패턴(드라이브 문자·홈 경로)과 API 오류 문구까지 지우는지 병합 뒤 확인이 필요하다. 근본 수정은 pipeline·llm이 애초에 메시지를 넣지 않는 것이다. 공개 모드에서는 `/docs`와 자세한 `/health`를 끈다.

### 통과 또는 낮음 항목
- **XSS — 통과.** `index.html`의 모든 동적 문자열이 `esc()`(& < > " ')를 거친다(`:377`). URL은 `safeUrl`(http·https만)+`esc`+`rel="noopener noreferrer"`. 계획서 본문·LLM 출력(사유·설명·행동·예상 심사평)·인용·파일명 모두 이스케이프됨. eval·document.write·인라인 핸들러에 데이터가 들어가지 않는다. E4-L1b가 더한 UI(+109줄)도 같은 규칙. 정적 배포 빌드(E6-L3a)는 `<script>` 안 JSON에서 `< > &`를 `\u00XX`로 바꾼다(`_script_json`).
  - **SEC-L3 낮음 · `index.html:499,504,513`.** `cd.sev`·`cd.rank`·`R.audit.gen/pass/drop`·`l.n`은 이스케이프 없이 붙는다. 지금은 서버(`view.py:115-125` `_int`, `:389-403`, `:567-572`)가 정수로 강제해 안전하지만, 이 값이 문자열로 오면 바로 XSS가 된다. `Number(...)`나 `esc(...)`로 감싼다.
  - 보안 헤더(CSP·X-Content-Type-Options·frame-ancestors·Referrer-Policy)가 없다(낮음). 화면이 인라인 스크립트를 쓰므로 CSP는 nonce나 해시가 필요하다.
- **경로 이동 — 통과.** `/fonts`(StaticFiles)에 `..`, `%2e%2e`, `%5c`, 중첩 변형 6종을 보냈고 전부 404. 사전 계산본은 파일 이름을 매니페스트에서만 가져오고 `RESULT_FILE_RE`와 `resolve().parent` 검사를 통과해야 읽는다(`precomputed.py:45,140-149`). 업로드는 디스크에 쓰지 않는다. 내보내기 파일명은 `[0-9A-Za-z_-]` 12자. 추출 캐시 키는 sha256 16진수.
- **CORS — 통과.** CORS 미들웨어가 없어 브라우저가 다른 출처에서 응답을 읽지 못한다(preflight는 405). 쿠키·세션이 없어 CSRF 문제도 없다. 다른 출처에서 POST는 도달하지만 토큰이 없는 공개 API라 직접 호출과 같다(S-01이 대응). 나중에 CORS를 열 때 `*`는 쓰지 않는다.
- **로그 — 통과.** 서버 로그는 uvicorn 접근 로그뿐이고 계획서 본문이 없다(실측: 33줄, 본문 0건). `log.error`는 예외 종류·파일:줄만 쓴다. 단 위 S-04의 LLM 오류 문구가 WARNING 로그에 남는다.
- **위험 함수 — 없음.** 전 브랜치 `src`·`scripts`에서 pickle·eval·exec·shell=True·os.system·torch.load·trust_remote_code·yaml.load 검색 0건. 서버는 사용자 URL을 가져오지 않는다(SSRF 없음).
- **MCP 서버(E4-L2b) — 공개 범위 밖.** stdio 전송, 읽기 전용, 검색어 300자 상한, 외부 호출 없음. 다만 `ToolError(f"…{exc}")`(`mcp_server.py:549,584,656`)가 경로를 담을 수 있으니 이 서버를 HTTP로 감싸 공개하지 않는다.
- **SEC-L4 낮음 · `export.py:483-505` similar_works.csv 수식 주입.** 제목·학회·URL을 그대로 쓴다. `= + - @`로 시작하면 엑셀이 수식으로 읽는다. 앞에 `'`를 붙인다.
- **SEC-L5 낮음 · `export.py:913-947` 패키지 출처 위조.** 클라이언트가 보낸 `result`를 그대로 담고 서버가 생성했는지 확인하지 않는다. 임의로 만든 카드에 `generator: astra`를 써서 "astra 생성" 패키지를 만들 수 있다. 매니페스트에 "요청 본문의 결과를 그대로 담음(서버 재생성·검증 없음)"을 명시하거나, 서버가 만든 결과를 세션 id로 보관했다가 그것만 내보내게 한다.

### S-06 [중간] 개인정보·기밀 고지 없음
- 위치: main `src/neumann/webui/index.html`(고지 문구 0건, `grep OpenAI|전송|개인정보|보관` 결과 없음), `llm.py:198`(`store: False`), `pipeline.py:49-65`(전화·주민번호 형태만 추가 마스킹; 이메일·ORCID는 `models.redact_pii`)
- 현황: 사용자가 붙여 넣은 미공개 연구계획서가 OpenAI API로 전송된다. 이름·소속·주소는 마스킹되지 않는다. E4-L2c 계획은 결과 캐시를 `data/cache/results/`에 디스크로 남긴다고 한다(`docs/tasks/E4-L2c.md`). E4-L1a는 업로드를 디스크에 안 쓰지만 이 캐시는 계획서 줄(`plan`)을 담을 수 있다(작성본은 `_strip_plan_body`로 본문을 떼는 것으로 보이나 병합 뒤 확인).
- 권고: 입력 화면에 "입력한 글은 분석을 위해 OpenAI API로 전송됩니다. 미공개 기밀·개인정보는 넣지 마세요" 고지. 캐시에는 본문을 남기지 않거나 보존 기간(예: 24시간)을 두고 지운다. 로그에는 plan_id와 길이만.

---

## 3. 데이터 라이선스

- **저장소 — 통과.** 전 브랜치·이력에 DISAPERE·ResearchArcade·Retraction Watch의 원본이나 가공본이 없다. 커밋된 데이터는 가짜 fixture뿐이다(`tests/fixtures/*.jsonl`은 `provenance.license="fixture-fake-data"`, 제목 `[FIXTURE]`, URL `example.org`, `tests/e3/corpus.py`도 가짜 코퍼스). jsonl·parquet·zip·`data/` 추가 이력 0건, 가장 큰 블롭은 415KB 스크린샷. 보고서(`docs/reports/*.md`)에 원문 심사평을 길게(160자 이상 영문 연속) 옮긴 줄이 0건. DISAPERE는 채점 골드로만 쓰고 출력은 gitignore된 `data/eval`이다. 색인은 `works.jsonl`·`reviews.jsonl`(ResearchArcade 유래)만 읽고 DISAPERE를 읽지 않는다(`scripts/build_index.py`, `src/neumann/index`에 disapere 참조 없음).
- **DL-1 중간 · 공개 서비스의 원문 재배포(저장소 밖).** 제품이 ResearchArcade(HF, 라이선스 선언 없음) 심사평 문장을 화면·내보내기 ZIP(`evidence_pack.json`·`neumann_report.md`)·정적 배포(E6-L3a, GitHub Pages)에 글자 그대로 싣는다. 문장 단위 발췌와 원문 링크 병기라 설계상 의도지만, 라이선스 미선언 자료의 공개 재배포임은 사실이다. 권고: 화면 하단에 출처 표기("심사평 출처: OpenReview(ICLR 2024·2025) 공개 기록, ResearchArcade 경유, 원문 링크")를 넣고, 인용은 문장 단위 상한을 유지하고, 위험 수용을 `docs/decisions.md`에 대표 이름으로 남긴다. DISAPERE는 색인에 절대 들어가지 않게 지금처럼 유지한다.
- **DL-2 낮음 · Retraction Watch 표기.** `retraction.py`는 출처 문구를 모든 출력에 붙이지만(라이선스 선언 없음, 인용 필수), 화면·내보내기에는 아직 연결되지 않아 표기 문구가 없다. 사후 상태를 화면·ZIP에 붙일 때 "Retraction Watch Database, Crossref" 표기를 함께 낸다.
- E6-L3b 시연 프레임·E4-L1b 스크린샷 등은 지금 fixture·샘플이다. 실데이터 화면을 스크린샷·영상으로 낼 때는 인용이 문장 단위인지, 사용자 계획서 원문이 보이지 않는지 그때 다시 본다.

---

## 4. 정직성

### 잘된 점(확인함)
- 샘플 경로(main `main.py:173-195`): `sample:true`, `status:degraded`, stages `fallback:sample`, 공지 문구, 헤더 pill, 배너("입력한 계획서는 분석되지 않았습니다 … 공용 fixture(가짜 데이터)")가 모두 붙는다. 모듈이 있는데 import·실행이 실패하면 샘플로 숨기지 않고 500이다.
- 카드 단위 생성 방식 표기: `astra`/`rule`/`mock`이 화면(`GEN` 라벨, 규칙·mock은 붉은색)과 내보내기(`export.py:78-87`)에 그대로 나온다. 규칙 결과를 astra로 쓰는 코드 경로는 찾지 못했다(`generator_for`는 openai→astra, mock→mock, 그 밖→rule).
- 인용은 코드가 원문에서 오프셋으로 잘라 붙이고(`verify_against`), LLM은 발췌 id·줄 번호만 돌려준다. 통과하지 못한 근거는 카드에서 빠진다.
- 사전 계산본(E6-L2a): 응답 `notices` 맨 앞, `manifest.precomputed`, 헤더에 "사전 계산본(생성 시각)"이 붙고 sha256 변조 검사를 한다. fixture로 대체된 것은 그렇다고 적는다. 정적 배포도 "정적 판 · 사전 계산본 — 라이브 분석 아님" 띠를 넣는다.
- 지적 추출 캐시는 openai provider가 만든 것만 쓰고 모델을 키에 넣는다.

### S-05 [중간] mock 결과가 정상 연결처럼 보일 수 있음
- 위치: `models.py:642-652`(강등은 **단계 상태**만 보고 status를 degraded로 바꾼다. 카드가 mock이어도 ok), main `view.py:679-702`(`_status_block`: `label`은 sample·error·degraded 때만 채움), `view.py:772`(`degraded` 플래그는 켜지지만), `index.html:482-483`(**배너는 `st.label`이 있을 때만 그린다**), `index.html:401`(pill은 "분석 파이프라인 연결 · v…")
- 재현(실측): 공용 fixture(카드 전부 `generator: mock`, status `ok`)를 `build_ui_view`에 넣으면 `result_status: ok`, `degraded: true`, `label: ''` → **배너 없음.** 카드마다 붉은 "mock provider" 태그가 있을 뿐 화면 머리는 "분석 파이프라인 연결"이다. `NEUMANN_LLM_PROVIDER=mock`으로 서버를 띄우면(`tests/conftest.py`가 pytest 안에서 그렇게 설정한다. 셸에 export된 값이 새는 사고가 가능) 파이프라인은 단계 오류 없이 ok로 돌아 같은 상황이 된다.
- 권고: (1) `view.py`가 카드·예상 심사평·체크리스트 중 `astra`가 아닌 생성 방식이 하나라도 있으면 `label`을 채워 배너를 띄운다. (2) `/health`가 `llm.provider`·`llm.model`·키 유무(참·거짓)를 보이고 pill이 이를 표시한다. (3) 공개 실행(`serve.py --public`)은 provider가 openai가 아니거나 키가 없으면 기동을 거부한다(조용히 규칙·mock으로 도는 것보다 낫다).

### S-05b [중간·잠재] 체크리스트·2차 검증의 생성 방식 기본값이 `astra`
- 위치: main `analyze/checklist.py:170-175`(`llm_label`: `generator`도 `llm_call.generator`도 없으면 `"astra"`, 모델 `"gpt-6-astra"`), `analyze/validate.py:149`
- 현황: 호출부가 `generator`·`model`을 넘기지 않으면 mock·규칙 LLM 응답에도 astra 표기가 붙는다. 파이프라인에는 아직 연결되지 않아 지금은 발생하지 않는다(E3-L0 `pipeline.py`는 `build_checklist`를 부르지 않는다). PM이 연결할 때 실수하기 쉬운 자리다.
- 권고: 기본값을 `"unknown"`으로 하거나 인자 없으면 예외로 한다. 연결 시 provider의 `generator_for(provider)`와 `llm.model`을 반드시 넘기고 테스트로 못 박는다.

### S-05c [중간·잠재] 사전 계산본이 정상 결과처럼 보일 수 있음
- 위치: `task/E6-L2a:src/neumann/api/precomputed.py:203-224`(`mark_result`는 `notices`·`manifest.precomputed`만 붙이고 `status`·`_status.label`은 안 바꾼다)
- 현황: 사전 계산본이 `status: ok`이면 `view.py`가 `label`을 안 채워 화면 배너가 안 뜬다(배너는 `st.label` 조건). 실시간 분석 실패 시 `lookup_by_text`로 사전 계산본을 대신 내는 흐름(docstring이 예고)에서 사용자가 라이브 결과로 오해할 수 있다. 정적 배포는 자체 띠가 있어 해당 없다.
- 권고: `build_ui_view`가 `precomputed` 표시를 받아 `label`을 "사전 계산본(생성 시각) — 실시간 분석 아님"으로 채운다. 실시간 실패를 사전 계산본으로 대체할 때는 "실시간 분석이 실패해 미리 계산한 결과를 보여 준다"를 함께 표시한다.

### 낮음
- **HON-L1 · 샘플 모드를 공개에서 서빙.** 파이프라인 모듈이 없을 때(`unavailable`) 서버가 라벨을 붙인 샘플을 내보낸다. 표기는 정직하지만 공개 기간에는 "서비스 준비 중" 503이 더 낫다. 공개 실행에서는 샘플 모드로 서빙하지 않게 한다.
- **HON-L2 · 화면 카드 수만 보는 요약.** `view.py`의 `generators`는 카드만 센다. 예상 심사평·체크리스트가 규칙 대체여도 단계 강등이 함께 기록되면 배너가 뜨지만, 단계 기록이 없는 경로가 생기면 놓친다. S-05 권고 (1)로 같이 해결된다.

---

## 병합 대기 중인 E4-L2c 초견(작성 중, `66e76c7`)

공개 안정성 과제라 이 점검의 S-01·S-04와 직결된다. 아직 미병합·작성 중이므로 병합 뒤 재점검이 필요하다. 소스에서 본 것만 적는다.
- 다룬 것: 동시 상한 + FIFO 대기열 상한(503), IP별 분당 제한(429, 터널 헤더로 IP 판별), 50,000자 상한과 바이트 상한(413), 요청 시간 상한(504), 결과 캐시, 비밀값 스크럽·로그 필터, 오류 사용자 문구.
- 빠진 것(S-01·S-02·S-03에 반영): 보호 경로가 `/premortem`, `/premortem/view` 둘뿐(`serving.py:65`)이라 `/premortem/package`(파이프라인 실행)와 `/upload/plan`(CPU 점유)이 밖이다. 전역 일일 예산 상한이 없다(IP 제한과 캐시는 IP를 바꾸거나 글자를 덧붙이면 우회된다). 공개 모드가 아니면 속도 제한이 0(끔)이다.

## 요약 표

| 영역 | 판정 | 비고 |
|---|---|---|
| 1 비밀값 | 통과 | 이력·worktree 0건. 낮음 2건(경로 노출, 이력 검사 범위) |
| 2 공개 서버 | **조건부** | 높음 3(S-01 비용·DoS, S-02 package 우회, S-03 업로드 증폭), 중간 2(S-04 오류 노출, S-06 고지). XSS·경로 이동·CORS·로그·위험 함수는 통과 |
| 3 데이터 라이선스 | 통과(저장소), 중간 1(서비스 재배포 표기) | 원본·대량 인용 없음 |
| 4 정직성 | 조건부 | 중간 3(S-05, S-05b, S-05c) 모두 표시 누락·기본값 문제. 규칙·mock을 astra로 쓰는 경로는 현재 코드에 없음 |

재점검 요청: E4-L2c 병합 뒤(보호 경로·예산 상한·오류 스크럽 확인), E3-L0 pipeline이 main에 들어온 뒤(S-04 실제 응답 재현), 공개 직전 실서버(8010 아닌 별도 포트)에서 mock 아닌 provider·키 없음·색인 없음 세 상태로 응답을 훑는다.
