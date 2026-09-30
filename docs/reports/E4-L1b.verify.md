# E4-L1b 검증 보고서 — AI for Science 템플릿 선택기·범위 안내

- 검증자: Claude Sonnet 5.5 (빌더 Opus 5.5와 다른 모델) · 대상: `task/E4-L1b` @ `4393add` · 검증일 2026-09-30
- 방법: 빌더 worktree에서 완료 기준을 직접 실행. 코드·git은 건드리지 않음(worktree `git status` 깨끗). 임시 산출물은 `%TEMP%`에 두고 삭제. 서버는 8128, 끝나고 종료 확인(8010은 손대지 않음)

## 최종 판정: **PASS**

병합 전에 고칠 것은 없다. 아래 "PM 참고"는 병합 뒤 연결 때 처리할 것이다.

## 완료 기준별 결과

| # | 항목 | 실행한 명령 | 실제 출력(핵심) | 판정 |
|---|---|---|---|---|
| 1 | 템플릿 pytest | `pytest tests/e4 -q -k templates` | `25 passed, 1 skipped, 30 deselected` (skip 1 = Playwright 테스트, `NEUMANN_UI_TESTS=1` 전용) | 통과 |
| 1b | 스키마 테스트가 실제로 실패하는가 | `%TEMP%`에 src·tests를 복사해 카탈로그를 하나씩 망가뜨리고 같은 pytest 실행(worktree는 무변경) | 7종 모두 실패로 잡힘: 필수 필드(`scope.label`) 삭제 → 18 failed / id를 `../etc`로 → 18 failed / 예시 경로를 `../../.env`로 → 17 failed / 골격 `## 2. 방법` 제목을 바꿈 → 12 failed / 템플릿 4종으로 축소 → 12 failed / 범위 문구 변경 → 2 failed / index.html 범위 문구 삭제 → 1 failed. 원본 복사본은 25 passed | 통과(항상 통과하는 테스트 아님) |
| 2a | 범위 안내 | Playwright 1440×900, 직접 렌더(`#scope`) | 첫 화면 y=96px에 "AI 활용 과학 연구 계획서 전용"(붉은 14px 굵게) + 분야 5개. 스크린샷 확인 | 통과 |
| 2b | 템플릿 선택기 5개 | 같은 스크립트 | `#tplList .tp` 5개: 재료·배터리 GNN 대리모델 / 단백질·분자 / 물리·PDE·기후 / 신경과학 fMRI / 의료영상. 모두 뷰포트 안(첫 화면에서 스크롤 없이 보임) | 통과 |
| 2c | 고르면 입력칸이 채워짐 | 5개를 차례로 클릭 | 5개 모두 textarea가 채워짐(680~777자), 5칸(`## 1. 연구 목표`~`## 5. 일정`) 포함, 실행 버튼 활성화 | 통과 |
| 2d | 예시 3건 불러오기 | 3개 클릭 | 3건 모두 채워짐, 연결 템플릿(i/iv/v)이 선택 표시됨. 채워진 글이 `tests/fixtures/plans/{plan,plan_elife_neuro,plan_medimaging}.md`와 **글자 단위로 같음**(3/3 true) | 통과 |
| 2e | 콘솔 오류 0 | `console`(error·warning), `pageerror`, `requestfailed` 수집 | 모두 빈 배열 | 통과 |
| 2f | 외부 요청 0(CDN 없음) | 모든 request URL 수집 | 21건 전부 `127.0.0.1:8128`(`/`, `/fonts/*`(7), `/health`, `/templates*`). 외부 0 | 통과 |
| 2g | 서버 종료 | 포트 8128 리스닝 확인 | 종료 후 리스닝 없음(8010 미사용) | 통과 |
| 3 | 전체 검증 | `python scripts/verify.py` | `183 passed, 1 skipped` · 보안 130파일 · 계약 2개 · `verify 통과` | 통과 |

## 대표 의도 확인

| 확인 | 결과 |
|---|---|
| 화면만 봐도 "AI for Science 계획서 전용"인가 | 예. 맨 위(히어로보다 위)에 붉은 굵은 문구 + 분야 5개. 문구는 JS 상수(`SCOPE`)라 `/templates`가 죽어도 보임(코드로 확인: `T.cat`이 없으면 `SCOPE` 상수로 그린다. `/templates`에 500을 주입하면 "템플릿 목록을 불러오지 못함" 문구가 뜨는 것은 직접 봤다. 그 화면의 `#scope`는 따로 캡처하지 않았고 빌더의 404 스크린샷도 열어 보지 않음) |
| 템플릿으로 시작하도록 유도되는가 | 예. 입력칸 바로 위에 템플릿 5칸과 예시 3건이 첫 화면(y≈577~636)에 있고, 입력칸은 처음에 비어 있어 골격을 고르는 것이 가장 쉬운 시작이다. 다만 **강제는 아니다**: 직접 입력이 열려 있고 "오늘 저녁 김치찌개 레시피"를 넣어도 실행 버튼이 켜진다. 이 막이 `assess_fitness` 연결(PM)에 달려 있다는 점을 아래에 적었다 |
| 부적합 판정 결과 자리 `#fitBox` | 있음(`role="status"`, 평소 숨김). `window.NeumannInput.showFitness({fit:false, reasons:[...], generator:'rule'|'astra'|'mock'})`로 "적합성 판정 · 부적합 — 분석하지 않음" + 사유 + 분야·언어·판정 방식을 보임. 판정 방식이 없으면 "판정 방식 미표기", 규칙 판정은 "규칙 비상 판정"으로 표기해 astra로 오인시키지 않음 |

## 계약·소유 확인 (`git diff main...task/E4-L1b --stat`)

| 확인 | 결과 |
|---|---|
| 변경 파일 17개 | `src/neumann/api/templates.py`, `src/neumann/api/templates/*`(7), `src/neumann/webui/index.html`, `tests/e4/test_templates.py`, `tests/e4/test_templates_ui.py`, `docs/reports/E4-L1b.md`, `docs/reports/E4-L1b_*.png`(5). **전부 소유 경로 또는 허용 예외** |
| `main.py`·`contracts/`·`models.py`·`tests/fixtures/` | 변경 없음 |
| index.html diff(+106/−3) | CSS 블록 1개("E4-L1b 입력") 추가, `renderInput()` 반환 HTML, 새 함수 묶음(범위·템플릿·예시·적합성), 입력 분기의 클릭 위임 1개, 부팅 줄에 `loadTemplates()`만. 리포트·실행 화면과 `S` 상태 구조는 건드리지 않음 |
| 비밀값·데이터 파일 | 추가 없음(diff에서 키 패턴 검색 0건, verify 보안 통과) |
| main과 병합 충돌 | 없음. `git merge-tree --write-tree main task/E4-L1b` 정상 종료(충돌 목록 없음). main은 기준 커밋 이후 `main.py`(+19)·`export.py` 등을 바꿨지만 index.html과 겹치지 않음 |
| 병합 결과 통합 | 병합 트리(`git archive`로 `%TEMP%`에 풂)에서 `pytest tests/e4` = 82 passed, 1 skipped. main의 `main.py`는 이미 `OPTIONAL_ROUTERS`에 `neumann.api.templates`를 넣어 놓아서, 병합만 하면 `GET /templates`·`/templates/neuro-fmri`가 **200**으로 열린다(서버 직접 기동해 확인) |

## 보안(공개 서버 전제)

| 확인 | 결과 |
|---|---|
| path traversal | 통과. 서버에 `--path-as-is`로 `/templates/..%2F..%2F.env`, `%2e%2e%2f…`, `..%5C..%5C…`, `%252e…`(이중 인코딩), `....//`, `materials_gnn.md`, `catalog.json`, `%00`, 64자 초과 등을 던짐 → 전부 404 또는 422(id 패턴 `^[a-z0-9]+(-[a-z0-9]+)*$` + 64자), 파일 내용 반환 0건. 코드도 id를 카탈로그 사전에서만 찾고 요청 문자열로 경로를 만들지 않음. 예시 경로는 스키마(`tests/fixtures/plans/*.md`)와 `parent` 비교로 이중 차단 |
| 정적 노출 | `/templates.py`, `/catalog.json` 모두 404 |
| XSS: 사용자·템플릿 텍스트 | 통과. 새 코드의 동적 값은 모두 `esc()`(`& < > " '` 이스케이프)를 거침(`scopeInner`·`tplInner`·`fitInner`·`T.err`). 입력 본문은 `<textarea>` 안에 esc해서 넣음. `innerHTML` 사용처는 기존 렌더 패턴과 같은 방식 |
| XSS 실측 | 적대적 카탈로그(`<img onerror>`, `"><svg onload>`, `<script>`를 이름·요약·분야·칸·파일명·제목에 주입), 적대적 항목 본문(`</textarea><img onerror>`), 적대적 500 `reason`, `showFitness`에 적대적 사유·분야를 `page.route`/`evaluate`로 주입 → `window.__xss` 미설정, `img`·`script`·`svg[onload]` 요소 0, 페이지 오류 0. 문자열이 글자 그대로 화면에 보일 뿐 |
| 500 오류 문구 | `catalog.json` 스키마 위반 메시지가 응답에 실림. 비밀값 없음, 파일 경로 외 정보 없음(낮음) |

## 정직성 확인

- 규칙·mock 판정을 LLM 판정으로 표시하지 않는다(`FITGEN` 표: rule→"규칙 비상 판정", mock→"mock provider", 미표기→"판정 방식 미표기").
- 예시는 복사가 아니라 fixture 경로를 읽는다. 화면에 채워진 글이 원문과 같음을 3건 모두 확인했다. 범위 밖 fixture(`negative_recipe.md`)는 예시에서 빠져 있고 테스트가 이를 지킨다.
- 카탈로그가 깨지면 빈 목록으로 숨기지 않고 500 + 사유, 화면에는 "템플릿 목록을 불러오지 못함 · GET /templates 500 · …"이 붉게 보인다.
- 빌더 보고서 수치는 모두 재현됨(25 passed, 183 passed, 콘솔 0, 외부 0, 예시 3건).

## PM 참고 (병합 전 고칠 것 아님)

1. **아무 글이나 통과하는 상태**: 템플릿은 강제가 아니고, 부적합 글을 막는 것은 `assess_fitness` 연결뿐이다. 연결 전에는 "김치찌개 레시피"로도 분석이 시작된다. 스펙상 PM 연결 몫이니 E3-L1c 병합 뒤 `startAnalysis` 앞에서 막고 `NeumannInput.showFitness(result)`를 호출할 것.
2. **`#fitBox` 위치**: 입력칸 아래라서 템플릿을 채운 상태에서는 1440×900의 첫 화면 밖(y≈1079)이다. `showFitness`가 스크롤하지 않으므로 부적합 판정을 보일 때 `#fitBox.scrollIntoView()`를 함께 부르는 편이 좋다(연결 때 한 줄).
3. 입력칸 placeholder가 여전히 "연구계획서 본문"이다. "AI 활용 과학 연구 계획서"를 넣으면 범위 안내가 한 번 더 보인다(선택 사항).
4. 빌더 보고서의 "main.py에 붙이는 법"은 낡았다. main은 이미 `OPTIONAL_ROUTERS`로 자동 연결하니 별도 작업이 필요 없다.
5. 스펙 밖: 390px 폭에서는 가로 스크롤이 생기지만 기준 커밋(e0008d0)의 index.html도 똑같이 702px이라 이 과제의 회귀가 아니다.
