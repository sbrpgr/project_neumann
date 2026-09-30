# E6-L3a 검증 보고서 (Claude Sonnet 5.5)

- 대상: 브랜치 `task/E6-L3a` (`9808e36`), worktree `.claude/worktrees/agent-afd0b1bf741c5a035`, 2026-09-30
- 방법: 빌더 보고서를 믿지 않고 완료 기준을 다시 실행. 빌드는 `%TEMP%`에 새로 만들었다(공유 `data/site/`는 건드리지 않음). 코드·git 쓰기 없음. worktree 깨끗함(`git status` 빈 출력)

## 최종 판정: **PASS-조건부**

이 브랜치 기준(빌더가 병합한 main `0ba4a4c` 화면)으로는 완료 기준을 모두 통과한다. 그러나 **지금 main의 화면(E4-L1b 병합 뒤)으로 다시 빌드하면 콘솔 오류 3건이 난다.** 게시(Pages) 전에 아래 1번을 고쳐야 한다.

### 병합 전(또는 게시 전) 고칠 것

1. **[필수] main 화면과 호환**: 현재 main의 `src/neumann/webui/index.html`(E4-L1b: 템플릿 선택기·범위 안내)은 입력 화면을 그릴 때 `fetch('templates')`를 부른다. 정적 판의 fetch 가로채기는 `health`·`premortem*`만 처리하고 나머지는 실제 서버로 보내므로 `http.server`가 404를 돌려준다.
   - 재현: `git show main:src/neumann/webui/index.html`을 임시 폴더에 두고(폰트는 worktree 것) `python scripts/build_static_site.py --data-dir <data> --out <TEMP> --webui <그 폴더>` → 빌드·`--check`는 통과, 그러나 `/project_neumann/`을 http.server로 열면 `GET /project_neumann/templates` 404 ×3, 콘솔 오류 "Failed to load resource … 404" ×3, 입력 화면에 붉은 글씨 "템플릿 목록을 불러오지 못함 · GET /templates 404"
   - 빌더의 `python scripts/build_static_site_shots.py --site <그 산출물>` 도 `shots: 실패`(exit 1)로 이를 잡는다(콘솔 오류 목록·bad_status 3건). 즉 게이트는 작동하지만, 지금 상태 그대로 병합해 Pages에 올리면 이 게이트에서 막힌다
   - 고칠 곳(빌더 소유 `scripts/build_static_site.py`의 `STATIC_SHIM_JS`): `templates`, `templates/<id>` 요청을 정적으로 처리한다. 두 가지 중 하나: (a) `src/neumann/api/templates/catalog.json`·템플릿 md를 산출물에 넣어 정적 JSON으로 응답, (b) 정적 판에서는 템플릿 선택기를 감춘다. 어느 쪽이든 실제 네트워크 404가 없어야 콘솔 오류 0이 된다. 고친 뒤 main 화면으로 빌드·shots 재실행
2. [권고, 게시 전 PM 결정] 화면 머리에 대표 실명 배지("김대운")가 공개된다(빌더가 승인 항목으로 이미 적음). 근거 원문 링크가 가짜 `https://example.org/fake-venue/...`이다(데모 1, `<a href>`, 클릭해야 이동하고 요청은 아님)
3. [경미] 리포트 머리 소요 시간이 정적 판에서는 요청 왕복 시간(0.0S)이다(빌더가 E4에 제안한 항목과 같음). 실제 분석 시간이 아니다

## 완료 기준 재측정

| # | 항목 | 실행한 명령 | 실제 출력(핵심) | 결과 |
|---|---|---|---|---|
| 1 | 정적 테스트 | `pytest tests/e6 -k static -q` (PYTHONPATH `src;.`) | `26 passed in 5.86s` | 통과 |
| 2 | 빌드(새 출력 위치) | `python scripts/build_static_site.py --data-dir <data> --out %TEMP%/verify_site_e6l3a` | exit 0, 파일 26개(6.0MB), 데모 3건, "검사 통과: … 비밀값 0, 환경변수 이름 0, 로컬 경로 0, 외부·루트 절대 참조 0" | 통과 |
| 3 | 산출물에 비밀값 0 | 직접 만든 스캔(패턴 + 환경변수 중 KEY/TOKEN/SECRET/PASSWORD 이름의 실제 값 2개를 바이트 검색, 값은 출력 안 함) | secret-like 0, secret-value 0 | 통과 |
| 4 | 환경변수 이름 0 | 정규식(`OPENAI_API_KEY`·`NEUMANN_*`·`HF_*`·`PYTHONPATH`·`.env`·`os.environ` 등, 주입 전역 `NEUMANN_STATIC` 제외) | 0건. `NEUMANN_STATIC`(화면에 주입한 전역 변수 이름, 환경변수 아님) 3곳만 | 통과 |
| 5 | 로컬 경로 0 | 정규식(드라이브·UNC·`/Users/`·`AppData`·`.venvs`·`worktrees`·`노이만`·`Desktop`·`file:`) | 0건 | 통과 |
| 6 | 외부 도메인 0 | 스캔 + `src`/`href`/`url()`/fetch 목록 | 리소스 참조는 `fonts/…` 상대 경로와 `data:` SVG 노이즈뿐. 텍스트로만 남은 URL: `demo/plan.json`의 가짜 원문 링크 `example.org`(a 태그 href), 폰트 라이선스 파일 속 URL, SVG 네임스페이스(`w3.org`, 원본 그대로). 요청되는 외부 리소스 0 | 통과(요청 0. 위 2번 참고) |
| 7 | 검사기가 실제로 잡는지 | 산출물 복사본에 하나씩 심고 `--check` | 비밀값 형태·외부 script·환경변수 이름·Windows 경로 3종(`C:\…`, `D:/…`, `c:\\…`)·UNC·`/Users/`·`file:`·`AppData`·루트 절대 경로·"라이브 분석 아님" 삭제·데모 JSON 삭제·데모 JSON 변조(sha256)·JSON 속 경로 모두 exit 1, 원본은 exit 0 | 통과 |
| 8 | "라이브 분석 아님"·fixture 대체 표시가 모든 화면에 | Playwright 1440×900, 입력 → 분석(job) → 리포트 3건 | 아래 표 | 통과 |
| 9 | 하위 경로 `/project_neumann/`, 콘솔 오류·외부 요청 0 | 임시 폴더에 `project_neumann/`으로 복사해 `python -m http.server 8147`(8000·8010 미사용), 비로컬 요청은 차단하며 기록 | console error/warn 0, pageerror 0, requestfailed 0, 4xx/5xx 0, 외부 요청 0, 요청 37건 모두 `127.0.0.1:8147/project_neumann/…`(demo JSON 3 + 폰트 11 + 페이지). 서버 종료·포트 반환 확인 | 통과(브랜치 화면 기준) |
| 10 | 원본 index.html 무변경 | 빌드 전후 sha256, `git diff main...task/E6-L3a -- src/neumann/webui`, 산출물에서 주입분 제거 후 원본과 비교 | sha256 전후 동일(`11882558…6948`), 브랜치의 webui 변경 0, 주입분을 뺀 산출물 == 원본(68579자) | 통과 |
| 11 | 소유 경로 밖 변경 | `git diff --name-status main...task/E6-L3a` | 7개 파일 모두 추가: `scripts/build_static_site.py`, `scripts/build_static_site_shots.py`, `tests/e6/test_static_site.py`, `docs/reports/E6-L3a.md`, 스크린샷 PNG 3장. `contracts/`·`models.py`·`data/`·비밀값 파일 변경 0. `data/site/` 미커밋 | 통과 |
| 12 | `python scripts/verify.py` | worktree에서 실행 | `368 passed, 3 skipped`, 보안 166개, 계약 2개, `verify 통과`, exit 0 | 통과 |
| 13 | 빌더 shots 게이트 재실행 | `build_static_site_shots.py --site <내 산출물> --out <scratch>` | 브랜치 화면 산출물 `shots: 통과`(exit 0) / **main 화면 산출물 `shots: 실패`(exit 1)** | 위 1번 |

### 8번 상세: 화면별 표시 (브랜치 화면 산출물, 실제 브라우저 텍스트)

| 화면 | 상단 띠(모든 화면 공통, `</header>` 뒤라 #app 밖) | 헤더 알약 | 화면 본문 표시 |
|---|---|---|---|
| 입력 | "정적 판 미리 계산해 둔 결과만 보여 줍니다 — 라이브 분석 아님 … 사전 계산본 3건(대체 결과 · 가짜 데이터)" | "정적 판 · 사전 계산본(fixture 대체) — 라이브 분석 아님" | 데모 3칸 각각 "사전 계산본(fixture 대체 · 가짜 데이터) · 생성 시각", 본문 읽기 전용(입력해도 안 바뀜), 파일 업로드 없음 |
| 분석(job) | 같음 | 같음 | 단계 "✓ … 정상 · fixture", "! precompute_source — 강등 · … 실제 분석 대신 fixture 결과로 대체 · fallback:fixture" |
| 리포트 데모 1·2·3 | 같음 | 같음 | 상단 상자 "사전 계산본(fixture 대체 · 가짜 데이터 · 생성 … KST · 모델 mock provider 또는 미기록) — 라이브 분석 아님", "입력한 계획서(N자)는 분석되지 않았습니다. 아래는 공용 fixture(가짜 데이터)입니다", "[대체] … 실제 분석이 아니라 fixture 결과다", 추적 패널 "샘플 데이터 · 분석 결과 아님" |

- 데모 밖 본문을 POST하면 404 + "정적 판: 데모 3건만 — 라이브 분석 아님"(상태 라벨). 데모 2·3은 카드 0장(E6-L2a가 fixture 결과 없음으로 저장)이며 화면에 그렇게 표시된다. 모델은 "mock provider"/"미기록"으로 적혀 gpt-6-astra로 위장하지 않는다
- 인용 정직성: 데모 1의 근거 8건 모두 `q` == fixture evidence 텍스트, 오프셋 `[start,end]`·길이 일치, `sha` == text_sha256 앞 16자(8/8). 데모 2·3은 근거 0건. 규칙·fixture 결과를 LLM 결과로 표시하지 않음

## 참고(판정에 영향 없음)

- 내가 리포트 화면을 확인할 때 분석 화면을 잡으려고 데모 JSON 응답을 1.5초 늦췄기 때문에 "1.5S"가 보였다. 지연 없이는 0.0S다
- 테스트 26건은 실제로 검사한다(합성 화면으로 빌드 절차를 재고, 심은 문제 13종을 검사기가 잡는지 확인). 위 7번에서 독립적으로 재현했다
- 정적 판이 `src/neumann/webui`의 DOM(`#ta`, `.seg`, `[data-mode]`, `#btnStart`)에 기대는 것은 빌더가 밝혔고, 원본 화면 변경은 빌드 주입 지점 검사와 shots 게이트로 드러난다(이번 1번이 그 사례)
- 스크린샷 3장은 빌더 것을 그대로 두었다(내 스크린샷은 scratchpad에만 저장, 저장소에 남기지 않음). 검증이 만든 임시 폴더(`%TEMP%` 빌드 2개·변조 사본)와 서버(8147·8148)는 모두 지웠고, 8010 서버(PM)는 건드리지 않았다
