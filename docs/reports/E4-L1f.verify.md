**판정: PASS** (병합 전에 고칠 것 없음. 병합을 막지 않는 선택 개선 3건은 맨 아래)

# E4-L1f 검증 보고서 — 화면 파일 업로드를 `POST /upload/plan`에 연결

- 검증자: Claude Sonnet 5.5 · 빌더: Claude Opus 5.5
- 대상: 브랜치 `task/E4-L1f` 끝 `3c0ba40`(기준 `9dc4e8f`). 빌더 worktree는 건드리지 않고, 검증용 worktree를 스크래치패드에 따로 만들어 돌렸다(끝에 삭제)
- 환경: 모든 실행에 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK`·`NEUMANN_LIVE_TESTS` 제거, venv 파이썬, `PYTHONPATH="src;."`. `.env` 열지 않음, 실제 OpenAI 호출 없음
- 서버 포트: 8241(uvicorn mock), 8242(정적 호스트 `python -m http.server`). 8010·8020 미사용. 끝난 뒤 두 포트 모두 LISTEN 0 확인

## 완료 기준 재측정

| # | 기준 | 실행한 명령 | 실제 출력(핵심) | 결과 |
|---|---|---|---|---|
| 1 | `pytest tests/e4 -q -k upload` 통과 | `python -m pytest tests/e4 -q -k upload` | `77 passed, 1 skipped, 134 deselected` (건너뜀 1건 = Playwright, 기본은 꺼짐) | 통과 |
| 1b | 켜서 돌린 Playwright | `NEUMANN_UI_TESTS=1 pytest tests/e4/test_webui_upload_ui.py tests/e4/test_webui_upload.py` | `20 passed`, 끝난 뒤 8131 LISTEN 0 | 통과 |
| 2 | mock 서버에서 docx·pdf·hwp, 콘솔 오류 0 | 검증자 자체 Playwright 스크립트(1440×900) 47항목 | 아래 표. `TOTAL 47 checks, 0 failed` | 통과 |
| 3 | `python scripts/verify.py` | 검증 worktree에서 실행 | `1030 passed, 26 skipped in 89.16s` / 보안 파일 360개 / 계약 2개 / `verify 통과`, exit 0 | 통과 |

빌더 보고서의 수치(77 passed·20 passed·1030 passed 26 skipped)는 내 실행과 같다.

## 화면 실측(내가 만든 파일, Playwright 1440×900, 서버 mock)

시료: python-docx로 만든 DOCX(한국어 3문단), 손으로 쓴 최소 PDF(Helvetica, ASCII 3줄), 매직바이트를 붙인 가짜 HWP.

| 항목 | 결과 |
|---|---|
| 드롭존 안내 | `TXT · MD · PDF · DOCX · 최대 10 MB · 정리 뒤 50,000자 · HWP는 PDF·DOCX로 저장` 그대로 |
| `accept` | `.txt,.md,.markdown,.pdf,.docx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| "준비 중" 문구 | 화면 어디에도 없음 |
| DOCX 업로드(파일 선택) | 카드 `검증_전해액.docx`, `DOCX · 35.9 KB`, 텍스트 3줄. 미리보기 3줄이 원문 문단과 글자 그대로 같음. `직접 입력` 탭으로 바꿔 보면 textarea 값 = 추출 본문(계획서 본문 상태에 들어감). 실행 버튼 활성 |
| PDF 업로드(drop 이벤트) | 카드 `PDF · 734 B · 1쪽`, 본문이 서버 추출 결과와 같음 |
| HWP 업로드 | `#inErr` = `HWP는 PDF나 DOCX로 저장해 올려 주세요`(서버 415 `detail`과 글자 그대로 같음). 입력 잠금 해제(`aria-busy=false`, 파일 입력 활성). 다음 성공 업로드에서 오류 문구가 사라짐 |
| XSS 파일명 7종 | `<img src=x onerror=alert(1)>.txt`, `"><svg onload=alert(1)>.md`, `x' onerror='alert(1)'.txt`, `<iframe src=javascript:alert(1)>.txt`, `<details open ontoggle=alert(1)>.txt`, `&lt;b&gt;bold&lt;b&gt;.txt`, `<script>alert(1)<script>.txt`. 모두 `.fn` 텍스트가 서버가 돌려준 이름과 같고 자식 요소 0, 카드·미리보기 안에 `img`·`svg[onload]`·`iframe`·`details` 0개. `alert`·`confirm`·`prompt` 후킹 기록 0, `dialog` 이벤트 0 |
| XSS 파일 내용 | 본문에 `<img onerror>`·`<script>`가 든 txt: 미리보기가 글자로만 보임, 실행 없음 |
| 서버 응답이 적대적일 때(경로 가로채 주입) | `filename`·`kind`·`encoding`·`warnings`·415 `detail`에 `<img onerror>`·`<svg onload>`·`<i>`를 넣어도 글자로만 표시, 요소 0, alert 0 |
| 10 MB 초과(10 MB + 1 B) | 브라우저가 먼저 막음: `파일이 10 MB를 넘습니다(10.0 MB) — 올리지 않았습니다`, `/upload/plan` 요청 0건 |
| 정확히 10 MB 텍스트 | 서버로 보내고 요청 1건, 서버 413 문구(`계획서 글자 수가 상한(50,000자)을 넘습니다…`) 그대로 표시 |
| 깨진 DOCX | 서버 문구 `DOCX 파일이 아니거나 손상되었습니다. 다시 저장해 올려 주세요` 표시 |
| 다른 상태 코드(경로 가로채기) | 400·413·503은 `detail` 그대로, 422(배열 `detail`)는 `msg` 이어 붙임, 500(HTML 본문·`<script>`)은 `업로드 실패 · HTTP 500`(HTML 실행 없음) |
| 올리는 중 | 드롭존 `읽는 중… / first.docx · 서버에서 텍스트 추출`, 파일 입력 disabled, 그 사이 두 번째 drop 무시, `/upload/plan` 요청 1건, 끝난 뒤 카드 = 첫 파일 |
| CP949 txt | 본문 복원, 파일 카드 아래 서버 경고(`UTF-8이 아니어서 CP949(EUC-KR)로 읽었습니다…`). 파일 제거(×)하면 카드·경고 함께 사라짐 |
| 정적 판 ① `/upload/plan` 404(경로 가로채기) | docx: `정적 판 · 업로드 API 없음 — PDF·DOCX는 라이브 서버에서만 읽습니다 — 본문을 직접 입력에 붙여넣기`. md: 브라우저 읽기 + 카드 경고에 그렇게 읽었다고 표시. 판단을 기억해 그 뒤 요청 0(총 1건) |
| 정적 판 ② `window.NEUMANN_STATIC` 설정 | pdf 업로드: 같은 안내, `/upload/plan` 요청 0건 |
| 정적 판 ③ 실제 정적 호스트 `python -m http.server`(POST → 501 확인) | docx: 같은 안내. md: 브라우저 읽기 + 경고. 요청 1건, 페이지 오류 0 |
| 네트워크 실패(요청 abort) | pdf: `서버에 연결하지 못함 — PDF·DOCX는 라이브 서버에서만 읽습니다 — 본문을 직접 입력에 붙여넣기`. txt: 브라우저 읽기로 물러나되 경고 `서버에 연결하지 못함 · 브라우저에서 UTF-8로 읽음(…)`를 남김(폴백 숨기지 않음) |
| 진짜 서버 다운(서버 프로세스를 종료한 뒤 업로드) | docx: `서버에 연결하지 못함 — …`, 입력 잠금 없음. md: 브라우저 읽기 + 경고 표시 |
| 콘솔·네트워크 | 페이지 오류(pageerror) 0, 스크립트 콘솔 오류·경고 0, dialog 0, 외부 요청 0. 콘솔의 `Failed to load resource` 14줄은 모두 내가 일부러 만든 415·413·422·400·503·500·404 응답과 abort·연결 거부 단계에서만 나옴(브라우저가 4xx·차단마다 자동으로 찍는 네트워크 기록). 페이지 로드·DOCX·PDF 정상 흐름에서는 0줄 |

## 그 밖의 확인

| 항목 | 방법 | 결과 |
|---|---|---|
| 소유 범위 | `git diff main...task/E4-L1f --name-only`, index.html hunk 4개 확인 | 바뀐 파일: `src/neumann/webui/index.html`, 새 테스트 2개, 보고서, 스크린샷 5장뿐. index.html hunk = CSS 한 줄(`.drop.busy`·`.filewarn`, 파일 카드 CSS 바로 아래), `renderInput`의 드롭존 줄(`dropHtml()`)과 파일 카드 아래 `fileWarnHtml()`, `readFile`과 새 도우미 함수·상수. 템플릿·예시·적합성·리포트 등 다른 부분 무변경. 통과 |
| 계약·비밀값 | `contracts/`·`models.py` 변경 여부, 커밋 diff에서 키 패턴·`NEUMANN_LIVE_*` 켜기 검색 | 변경 없음, 키 없음. 테스트는 `mock` 강제·`NEUMANN_LIVE_TESTS` 제거. 통과 |
| `innerHTML`에 원문 | diff에서 `innerHTML`·`insertAdjacent`·`document.write`·`eval` 검색 | 추가 0건. `dropHtml`·`fileWarnHtml`·파일 카드·`#inErr` 모두 `esc()`(`& < > " '` 이스케이프)를 거침. `S.fileMeta`(서버 `kind`·`encoding`이 들어감)도 카드에서 `esc()` 통과 — 위 적대 응답 실험으로 확인. 통과 |
| 항상 통과하는 검사가 아닌지(변이 시험) | 검증용 worktree의 index.html에 결함을 넣고 `tests/e4/test_webui_upload.py` 실행 | 엔드포인트 오타 → 실패 1, "준비 중" 문구 복귀 → 실패 2, `esc(S.filename)` 제거 → 실패, `esc(S.fileMeta)` 제거 → 실패, 드롭존 `esc(b)` 제거 → 실패, 경고 `esc(x)` 제거 → 실패, `S.inErr` 맨 삽입 → 실패, 중복 제출 차단 삭제 → 실패. 원복 후 19 passed(파일 동일 확인). 통과 |
| main과의 병합 | main의 index.html은 기준 이후 E4-L1e(`920324c`)가 `SCOPE` 한 줄만 바꿈. `git merge-tree`로 시험 | 충돌 표시 0. 겹치는 줄 없음(SCOPE는 508행, 이 과제는 129·489~494·595~665행) |
| 커밋 규칙 | 3개 커밋 메시지 | `[E4-L1f]` 접두, `builder: claude-opus-5.5`, 작은 커밋(가장 큰 것은 테스트 파일 344줄). 첫 커밋 본문에 "verify는 다음 커밋에서"라고 적고 마지막 커밋에 `verify 통과` — 실제 측정으로도 통과 |
| 빌더 worktree | `git status --short` | 커밋 안 된 변경 0줄 |

## 판단: 실패한 업로드 뒤 상태(빌더가 남긴 관찰)

- 재현: PDF 카드가 있는 상태에서 `계획서.hwp`를 올리면 카드·미리보기는 PDF 그대로이고 그 아래 붉은 `HWP는 PDF나 DOCX로 저장해 올려 주세요`만 뜬다(내 스크린샷으로 확인).
- 판정: **허용, 병합 전 수정 불필요.** 근거 — (1) 상태가 사실과 어긋나지 않는다. 화면에 보이는 카드·본문이 실제로 `S.text`이고 실행 버튼이 분석하는 것도 그 본문이다. 오류 문구는 "HWP는 …"라고 형식을 밝혀 다른 파일이 거부됐음을 알 수 있다. (2) 반대로 지우면 잘못 고른 파일 하나 때문에 입력을 잃는다. (3) 스펙이 "서버 `detail` 문구를 그대로 `S.inErr`에" 넣으라고 했고 빌더 테스트도 글자 그대로를 검사한다. (4) 카드가 없을 때(첫 업로드가 거부) 본문 비어 있고 실행 버튼도 꺼짐 — 오해 여지 없음. 다음 성공 업로드나 새 분석에서 오류가 사라지는 것도 확인.

## 못 한 것·범위 밖

- 실제 정적 빌드(E6-L3a) 산출물 위 실행은 안 함(아직 병합 전). 정적 빌드의 fetch 가로채기는 `upload/plan`을 원래 fetch로 넘기므로(`build_static_site.py`) 호스트가 404·405·501을 주면 이 화면의 정적 판 분기가 받는다. 대신 경로 가로채기 404, `NEUMANN_STATIC`, 실제 `http.server`(501)로 세 경로를 확인했다.
- 대용량(수 MB) 실제 PDF·DOCX의 처리 시간은 재지 않음(서버 쪽 20초 상한은 E4-L1a 검증 범위).

## 선택 개선(병합을 막지 않음, PM 판단)

1. **응답이 아예 안 오는 경우 탈출구 없음.** 요청을 끝내 답 없이 붙잡아 보면(경로 가로채기) "읽는 중…"이 계속되고 파일 입력이 잠긴 채 `직접 입력` 탭으로 갔다 와도 그대로다(페이지 새로고침 전까지). 서버가 붙어 있으면 20초(+대기 5초) 상한이 응답을 내므로 실제로는 네트워크가 끊겨 멈춘 경우에만 생긴다. `AbortController` 타임아웃(예: 40초)으로 `서버 응답 없음`을 내고 `UP.busy`를 풀면 된다.
2. **오류 문구에 파일명이 없다.** 위 판단대로 허용이지만, 앞 카드가 남아 있을 때 헷갈림을 더 줄이려면 `S.inErr` 앞에 거부된 파일명을 붙이는 정도(`계획서.hwp — HWP는 …`)가 있다. 스펙의 "서버 문구 그대로"와 빌더 테스트(`#inErr` = `detail`)를 같이 고쳐야 하므로 PM이 원할 때만.
3. **404·405·501 판단을 페이지 수명 동안 기억한다.** 게이트웨이가 한 번 404·405를 내면 새로고침 전까지 PDF·DOCX가 안내 문구로만 처리된다. 안내 문구가 "업로드 API 없음"을 밝히고 있어 오도는 아니다. 라이브 서버에서만 드문 일.

## 정리

- 검증용 worktree는 스크래치패드에서 제거했다. 커밋·merge·stash·push 없음. 이 파일만 main 체크아웃에 커밋 없이 추가했다.
