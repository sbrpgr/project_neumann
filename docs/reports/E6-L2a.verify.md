# E6-L2a 검증 보고서 (검증자: Claude Sonnet 5.5)

- 대상: 브랜치 `task/E6-L2a` (HEAD `ee0d7b4`, main `ed1d1a0` 위에 커밋 3개 + main 병합 1개), worktree `.claude/worktrees/agent-a9b32838092a5aca8`, 빌더 claude-opus-5.5
- 방법: 빌더 보고서를 믿지 않고 완료 기준을 직접 실행했다. 서버는 **포트 8147**(8010 아님)에 띄웠고 끝난 뒤 종료해 포트가 비었다. 조작 시험은 전부 스크래치 폴더(`scratchpad\e6v`)의 데이터 복사본에서 했다. 공유 데이터 폴더(`data/precomputed`)는 읽기만 했고 매니페스트 sha256이 시험 전후 같다(`77afb3d5…89e6`). worktree 코드·git은 건드리지 않았다.
- 환경: Windows Python `neumann` venv, `PYTHONPATH="src;."`, `_COMMON.md`의 환경변수. `.env`는 열지 않았다.

## 결론

**PASS.** 병합을 막는 결함은 없다. 비차단 권고 4건은 맨 아래에 있다. 다만 공유 폴더의 현재 사전 계산본은 **fixture 대체본**이라(3건 중 2건은 카드 0장) 실제 데모 폴백으로 쓰려면 E3-L0·E2 병합 뒤 `--source pipeline`으로 다시 만들어야 한다. 빌더도 같은 내용을 보고서에 적었고, 응답·매니페스트에도 그렇게 표시된다.

## 항목별 결과

| # | 확인 항목 | 실행한 명령 / 방법 | 실제 결과 | 판정 |
|---|---|---|---|---|
| 1 | 완료 기준 1: fixture 기반 테스트(목록·단건·변조 404·표시) | `python -m pytest tests/e6 -q -p no:cacheprovider` | **30 passed** in 4.11s | 통과 |
| 2 | 완료 기준 2: verify | `python scripts/verify.py` (브랜치 worktree) | **256 passed**, 보안 137개 파일, 계약 2개, `verify 통과`, exit 0. (빌더의 "250 passed, 6 skipped"와 skip 수가 다른 것은 내가 `NEUMANN_RAW_DIR` 등을 설정해 원본 필요 테스트가 돈 차이) | 통과 |
| 3a | 계약 위반·소유 경로 | `git diff main...task/E6-L2a --name-status` | 추가 6개뿐(수정·삭제 0): `docs/reports/E6-L2a.md`, `scripts/precompute_demo.py`, `src/neumann/api/precomputed.py`, `tests/e6/` 3개. 전부 소유 경로(`scripts/precompute_demo*`, `api/precomputed.py`, `tests/e6/`)와 자기 보고서 안. `contracts/`·`models.py`·`main.py`·`tests/fixtures/`·데이터·비밀값 변경 0. `main`과 merge-base가 main HEAD와 같다 | 통과 |
| 3b | 비밀값·`.env` | 코드·테스트·보고서 열람 | 키·토큰 값 없음. 분석 실패 시 예외 **클래스 이름**만 매니페스트에 남기고 메시지는 남기지 않음(테스트 `LEAKMARKER`로 확인). 매니페스트 `llm`에는 provider·모델 이름만 | 통과 |
| 4a | 변조: 파일 바이트 | 실제 서버(8147)에서 scratch 파일을 8가지로 바꿈: 카드 제목 글자, 끝 개행→공백, 1바이트 추가, BOM, CRLF 변환, 절반 절단, 빈 파일, `"status":"degraded"`→`"ok"`(계약상 유효한 JSON) | **8종 전부 404 `tampered`**. 같은 시점에 목록은 해당 항목만 `integrity=mismatch`·`available=false`, 나머지는 `ok`. 데모 이름(`/plan`)으로 조회해도 404(우회 불가). 변조 전에는 200(짝 검사) | 통과 |
| 4b | 변조: 매니페스트 | 항목 sha 바꿈 / sha 삭제 / null / 숫자 타입 / 매니페스트 바이너리·리스트 루트·`entries`가 문자열·쓰레기 항목 섞임·매니페스트 삭제 | sha 불일치·삭제·null·숫자 → **404, 500 없음**. 매니페스트 깨짐·삭제 → 목록은 200 `available=false`+사유, 단건은 404(`bad_manifest`/`no_manifest`). 쓰레기 항목은 무시하고 나머지 정상. 대문자 sha(같은 값)는 200(변조 아님) | 통과 |
| 4c | 변조: 다른 계획서 바꿔치기 | (i) A 파일을 B 결과로 교체(sha 그대로) (ii) 교체 + 매니페스트 sha까지 맞춤 (iii) 매니페스트 A 항목이 B의 file+sha를 가리킴 (iv) A 항목의 file만 B로 | (i) 404 sha 불일치, (ii) **404 `tampered` "plan_id가 매니페스트와 다르다"**, (iii) 404 plan_id 불일치, (iv) 404 sha 불일치. plan_id·데모 이름 두 경로 모두 404. **한계(문서화됨)**: 파일+sha+`plan_id`를 함께 고친 매니페스트는 통과(서명 없음). 파일·매니페스트 접근 권한이 있는 공격자는 막지 못한다. 빌더 보고서 "못 한 것"에 적혀 있고 무대 폴백 용도로는 수용 가능 | 통과(한계 명시) |
| 5a | 경로 이동: 요청 값 | 원시 HTTP(`http.client`, 정규화 없음)로 22종: `manifest`, `manifest.json`, `..%2F`, `..%5C`, `%2e%2e%2f`, `C%3A%5CWindows%5Cwin.ini`, UNC 형태, `%00`, `<plan_id>%00.json`, `<plan_id>.json`, `..`, `.`, `../precomputed/manifest.json`, `..;/`, 3000자, 깨진 퍼센트 인코딩, `<id>/../<id>` 등 | **전부 404**, 응답 본문에 매니페스트·`risk_cards`·win.ini 내용 누출 0, 500 없음. 요청 값은 조회 키로만 쓰고 경로를 만들지 않는다(코드 확인) | 통과 |
| 5b | 경로 이동: 매니페스트 `file` 이름 | 매니페스트 `file`을 25종으로 바꿔 서버 조회: `../outside.json`, `..\..\`, 절대경로(Windows·POSIX), `manifest.json`, `sub/x.json`, `a:b.json`, `x.json::$DATA`, 공백, `CON.json`·`NUL.json`·`aux.json`, 후행 개행, 유니코드 `‥/`, 빈 값·None·숫자·리스트, 300자 등 (sha는 밖의 파일과 맞춤) | **전부 404**(`bad_name` 또는 `missing_file`), 밖의 파일이 서빙된 경우 0. 예약 장치 이름도 멈추지 않고 404. 폴더 안 심볼릭 링크→밖 파일은 이 계정에 권한이 없어 만들지 못해 시험 못 함(코드상 `resolve()` 뒤 `parent != base`로 거른다). 변이로 두 방어(정규식·폴더 검사)를 **둘 다** 끄면 테스트가 실패하고 밖 파일이 200으로 나옴 | 통과 |
| 6a | "사전 계산본" 표시(단건) | 실서버에서 plan_id 2종·데모 이름 2종으로 조회 | 4건 모두 200, `notices[0]` = `사전 계산본(2026-09-30 18:55 KST) — 실시간 분석이 아니라 미리 계산해 둔 결과다 · 분석 파이프라인 미연결로 fixture 결과로 대체된 사전 계산본`. 헤더 `X-Neumann-Precomputed: 1`·`-Generated-At`·`-Sha256`(= 실제 파일 sha), `Cache-Control: no-store`. `manifest.precomputed`(label·source=fixture·integrity=ok). 결과 `status=degraded` 유지, `precompute_source` 단계 degraded(impl `fallback:fixture`) | 통과 |
| 6b | "사전 계산본" 표시(목록) | `GET /premortem/precomputed` | 200, 항목 3건 라벨 `사전 계산본(… KST)`, `source=fixture`, 항목별 `cards_by_generator`·`models`·`elapsed_s`·`warnings`·`integrity`. 응답은 `PremortemResult`·`premortem_response.schema.json`을 통과(테스트 확인) | 통과 |
| 7 | fixture 대체 표시의 정직성 | 공유 폴더 실물·`scripts/precompute_demo.py` 3모드 실행 | 매니페스트 `source=fixture`, `pipeline.available=false`, `llm=null`, `models=[]`(대체본에 모델을 지어 붙이지 않음). `plan.md`는 공용 fixture 카드 2장을 `generator=mock`으로 세고 astra 0. fixture가 없는 2건은 카드를 지어내지 않고 0장+사유+`warnings`. 결과 안에 `[대체]` 알림과 저장본의 `[FAKE] fixture result…` 알림이 남고, 근거 URL은 `example.org` 가짜 주소다(fixture라는 표시와 함께 나가므로 위조 아님). `--source pipeline`은 파이프라인이 없으면 **exit 1**, 파일 미생성(`out_pipeline`에 안 만들어짐). `auto`·`fixture`는 exit 0, 재생 확인 3/3. 저장 sha256을 파일에서 직접 다시 계산하니 매니페스트와 3건 모두 일치 | 통과 |
| 8a | 외부 요청 0: 서버 | 소켓 차단·기록 래퍼(비루프백 `connect`·`connect_ex`·`getaddrinfo`를 막고 로그)로 `neumann.api.main:app`을 띄우고 위 시험 99건을 전부 보냄. 래퍼가 실제로 기록하는지는 `example.org` 접속 시도로 자체 검사(`getaddrinfo example.org` 기록·차단 확인) | 시험 뒤 가드 로그 **파일 자체가 생기지 않음(시도 0)**. 서버 프로세스의 TCP 연결은 8147 Listen과 asyncio 루프백 소켓쌍뿐. 라우터 모듈은 `fastapi`·`pydantic`·`neumann.config`·`neumann.models`만 import, 새 프로세스 import 시 `neumann.pipeline`·`neumann.llm`·`openai`·`torch`·`sentence_transformers`·`httpx` 미적재(테스트 확인) | 통과 |
| 8b | 외부 요청 0: 스크립트 | 같은 가드 아래서 `precompute_demo.py --source auto` | exit 0, 가드 로그 파일 생성 없음(시도 0) | 통과 |
| 9 | 테스트가 항상 통과하는가 | `git archive`로 스크래치에 푼 복사본에 결함을 하나씩 주입해 `pytest tests/e6` (기준선 30 passed) | 잡힘 7종: sha 비교 끄기(변조 테스트 실패), 결과 plan_id 대조 끄기(바꿔치기 테스트 실패), `notices` 표시 삭제, fixture 대체 문구 삭제, 404→410, 응답 헤더 삭제, 라벨에서 시각 삭제. 경로 방어는 정규식·폴더 검사가 **중복 방어**라 하나만 끄면 살아남지만(동치 변이) 둘 다 끄면 `test_manifest_file_name_outside_folder_is_refused`가 실패. 원복 뒤 30 passed. 차단기 자체 검사 테스트도 있음(`test_network_guard_actually_blocks`) | 통과 |
| 10 | 조작 입력 종합 | 위 4~5절 HTTP 시험 스크립트 | 확인 99건, 실패 0(한계 사례 1건은 정보 출력) | 통과 |
| 11 | worktree 청결 | `git status --short --ignored` | 변경 0. `.pytest_cache/`는 내가 시작하기 전부터 있던 무시 파일. `__pycache__` 없음(`PYTHONDONTWRITEBYTECODE=1`). 검증 산출물은 스크래치에만 있다 | 통과 |

## 비차단 권고 (병합 뒤 또는 다음 과제에서)

1. **mock provider로 만든 `--source pipeline` 결과가 알림에는 mock이라고 나오지 않는다.** `mark_result`의 `_source_note`는 `source=="fixture"`만 덧붙인다. `NEUMANN_LLM_PROVIDER=mock`으로 파이프라인을 돌리면 `source: "pipeline"`으로 저장되고, mock 사실은 매니페스트 `llm.provider`와 항목 `models`(`mock:…`)에만 있고 `notices[0]`에는 안 나온다. 실제 데모용 재생성 때 PM이 `manifest.llm.provider == "openai"`와 `cards_by_generator.astra ≥ 1`을 확인해야 한다(빌더 "다음"의 확인 항목과 같은 취지). 가능하면 `_source_note`에 provider가 mock이면 "가짜(mock) LLM 결과" 문구를 추가하는 편이 안전하다.
2. **매니페스트 서명 없음.** 파일·sha·`plan_id`를 함께 고치면 통과한다(위 4c). 무대 폴백 용도면 수용 가능하지만, 사전 계산본을 신뢰 근거로 배포할 일이 생기면(E6-L3a 정적 배포) 매니페스트 자체의 해시를 별도 채널(커밋·보고서)에 고정하는 것을 권한다.
3. **파일 이름 정규식의 `$`가 후행 개행을 허용한다.** `RESULT_FILE_RE.match`의 `$`는 `x.json\n`도 통과시킨다. 폴더 밖으로 나가지는 못하고(폴더 검사가 이어짐, 시험에서 `missing_file` 404) 매니페스트를 고칠 수 있어야 하므로 위험은 낮다. `fullmatch`로 바꾸면 깔끔하다.
4. **공유 폴더의 사전 계산본은 데모에 쓸 수 없는 상태다.** 3건 모두 fixture 대체본이고 `plan_elife_neuro`·`plan_medimaging`은 카드 0장이다. 표시는 정직하다. 다만 T+17h 프리즈 전에 E3-L0·E2 병합 뒤 `--source pipeline`을 실제 astra로 돌려 3건 모두 카드 ≥ 1인지 확인해야 한다(빌더가 PM 할 일로 적어 둠). 또 `main.py`의 `/premortem/view`에 `lookup_by_text`+`mark_result` 폴백을 붙이는 일은 아직 없다(E4 몫).
