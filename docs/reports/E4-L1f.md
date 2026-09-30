# E4-L1f 보고서 — 화면 파일 업로드를 `POST /upload/plan`에 연결

- 빌더: Claude Opus 5.5 · 브랜치 `task/E4-L1f` · 기준 커밋 `9dc4e8f`(main)
- 결과: 완료 기준 3개 모두 직접 실행해 통과(아래 명령·출력). 실제 OpenAI 호출 없음(모든 실행 `NEUMANN_LLM_PROVIDER=mock`)

## 무엇을 했나

1. **`readFile(file)`**(`src/neumann/webui/index.html`, 입력 화면의 업로드 부분만)
   - 서버 판: 모든 형식을 `FormData`(`file` 필드)로 `POST upload/plan`(상대 경로)에 보낸다.
     성공하면 `text` → `S.text`, `filename` → `S.filename`, `S.fileMeta` = 형식 · 크기 · 쪽수(pdf) · 인코딩(txt·md)
     (예: `PDF · 2.7 KB · 2쪽`, `MD · 25 B · CP949`, `DOCX · 35.9 KB`)
   - `warnings`는 파일 카드 바로 아래 작은 목록(`#fileWarn`, 호박색)으로 보인다. 본문이 바뀌면(템플릿·새 분석·파일 제거) 같이 사라진다
   - 오류(400·413·415·422·503)는 서버 `detail` 문자열을 그대로 `S.inErr`에 넣는다. HWP 문구도 서버 것(`HWP는 PDF나 DOCX로 저장해 올려 주세요`)
   - 올리는 동안: 드롭존이 "읽는 중…" + 파일명 · 서버에서 텍스트 추출, `aria-busy="true"`, 파일 입력 `disabled`, `readFile`은 바쁠 때 바로 돌아간다(중복 제출 차단)
   - 정적 판(업로드 API 없음 = 응답 404·405·501, 또는 `window.NEUMANN_STATIC`): md·txt는 브라우저에서 UTF-8로 읽고, pdf·docx는
     "정적 판 · 업로드 API 없음 — PDF·DOCX는 라이브 서버에서만 읽습니다 — 본문을 직접 입력에 붙여넣기". 한 번 판단하면 그 뒤로는 요청하지 않는다
   - 네트워크 오류(fetch 실패): md·txt는 브라우저 읽기로 물러나되 파일 카드 경고에 "서버에 연결하지 못함 · 브라우저에서 UTF-8로 읽음(서버 정리·인코딩 추정 없음)"을 남긴다.
     pdf·docx는 "서버에 연결하지 못함 — PDF·DOCX는 라이브 서버에서만 읽습니다 — 본문을 직접 입력에 붙여넣기"
   - 파일명·경고·서버 문구는 모두 `esc()`를 거쳐서만 HTML에 들어간다(`innerHTML`에 원문 없음). 업로드 함수들은 `innerHTML`을 쓰지 않고 `render()`만 부른다
2. **드롭존**: 안내 "TXT · MD · PDF · DOCX · 최대 10 MB · 정리 뒤 50,000자 · HWP는 PDF·DOCX로 저장",
   `accept`에 `.pdf`, `.docx`, `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document` 추가(`.txt,.md,.markdown,text/plain,text/markdown` 유지)
3. **CSS 한 줄**: `.drop.busy`(실선 테두리·progress 커서), `.filewarn`(12px 호박색 목록). 파일 카드 CSS 바로 아래
4. **테스트**
   - `tests/e4/test_webui_upload.py`(기본 pytest, 19건)
     - API(main 앱 = 실제 라우터 연결 포함, TestClient): 라우터 연결, txt(UTF-8)·md(CP949 → `encoding`·경고)·docx(python-docx로 생성)·pdf(2쪽 중 빈 쪽 → `pages`·경고) 응답에 화면이 읽는 필드(`text`·`filename`·`kind`·`pages`·`encoding`·`warnings`)와 형이 맞는지, hwp·hwpx 415 `detail` = 서버 문구, 422·413·415 `detail`이 문자열인지, 파일명이 그대로 돌아온다(→ 화면이 이스케이프해야 함)
     - index.html 정적 검사: `readFile`이 `fetch('upload/plan', POST, FormData 'file')`를 부름, "PDF · DOCX 준비 중"·"업로드는 준비 중" 없음, `esc(S.filename)`·`esc(S.fileMeta)`·`esc(b)`·`esc(x)`, `+ S.filename`/`+ S.fileMeta`/`+ S.inErr` 맨 삽입 없음, 업로드 함수에 `innerHTML` 없음, 안내 문구·accept, 읽는 중·중복 차단, 정적 판 분기, 화면이 읽는 `j.*` 필드가 `PlanUploadResponse`에 모두 있음
     - 이 정적 검사 8건은 옛 index.html(main)에 돌리면 **8건 모두 실패**한다(항상 통과하는 검사가 아님을 확인, 아래 출력)
   - `tests/e4/test_webui_upload_ui.py`(Playwright 1440×900, `NEUMANN_UI_TESTS=1`일 때만 · 스크립트로도 실행): 하위 프로세스로 uvicorn을 8131에 띄우고(**`NEUMANN_LLM_PROVIDER=mock` 강제, `NEUMANN_LIVE_TESTS` 제거, 8010·8020 거부**) 끝나면 종료. 7단계: ① docx ② pdf ③ hwp ④ 파일명 `<img onerror>` ⑤ 읽는 중·중복 차단 ⑥ 네트워크 실패 ⑦ 정적 판(404)

## 완료 기준별 측정

환경: PowerShell에서 `$env:NEUMANN_LLM_PROVIDER='mock'`, `NEUMANN_LIVE_TESTS` 제거, `PYTHONIOENCODING=utf-8`, `PYTHONPATH=src;.`(verify는 `_COMMON.md`의 나머지 변수까지). Python은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`.

### 1. `python -m pytest tests/e4 -q -k "upload"` — 통과

```
$ python -m pytest tests/e4 -q -k "upload"
........................................................................ [ 92%]
.....s                                                                   [100%]
77 passed, 1 skipped, 134 deselected in 14.32s
```

(건너뛴 1건 = Playwright 검사. 켜서 돌린 결과:)

```
$ NEUMANN_UI_TESTS=1 python -m pytest tests/e4/test_webui_upload_ui.py tests/e4/test_webui_upload.py -q
....................                                                     [100%]
20 passed in 12.58s
port 8131 closed (server stopped)
```

정적 검사가 옛 화면을 잡는지(옛 `main:src/neumann/webui/index.html`에 같은 검사 함수를 돌림):

```
FAIL(on old) test_busy_state_blocks_duplicate_submit substring not found
FAIL(on old) test_drop_hint_and_accept UP_HINT 상수가 없다
FAIL(on old) test_error_detail_shown_verbatim_and_network_message upDetail 함수가 없다
FAIL(on old) test_filename_warnings_and_errors_only_through_esc dropHtml 함수가 없다
FAIL(on old) test_pending_text_is_gone
FAIL(on old) test_readfile_posts_formdata_to_upload_plan
FAIL(on old) test_static_mode_reads_only_md_txt_locally UP_LIVE_ONLY 상수가 없다
FAIL(on old) test_ui_reads_only_fields_the_api_returns set()
```

### 2. mock 서버에서 docx·pdf·hwp 업로드 결과, 콘솔 오류 — 통과

`python tests/e4/test_webui_upload_ui.py --port 8131` → exit 0, `"problems": []`. 단계별 실측(발췌):

| 단계 | 화면 결과 |
|---|---|
| ① docx `계획서_전해액.docx` | 파일 카드 `DOCX · 35.9 KB` · 텍스트 3줄, 추출 텍스트 = 원문 3줄 그대로, 실행 버튼 활성, 오류 없음 |
| ② pdf `계획서_전해액.pdf`(2쪽, 2쪽째 빈 쪽) | `PDF · 2.7 KB · 2쪽`, 본문 3줄, 경고 "텍스트가 없는 쪽: 2 (스캔 이미지일 수 있습니다. 문자 인식(OCR)은 하지 않습니다)" |
| ③ hwp `계획서.hwp` | `#inErr` = "HWP는 PDF나 DOCX로 저장해 올려 주세요"(서버 415 `detail`과 같음). 앞서 올린 pdf 본문은 그대로 둔다 |
| ④ 파일명 `<img src=x onerror=window.__xss=1>.txt` | 파일명이 글자 그대로 보임, `window.__xss` 없음, 카드 안 `<img>` 없음 |
| ⑤ 올리는 중(요청을 잡아 둠) | 드롭존 "읽는 중…" / "계획서_전해액.docx · 서버에서 텍스트 추출", 입력 disabled, 그 사이 드롭한 두 번째 파일 무시 → `/upload/plan` 요청 1건, 풀어 준 뒤 본문 반영·`aria-busy="false"` |
| ⑥ 네트워크 실패(요청 차단) | md: 브라우저 읽기 `MD · 82 B · 브라우저 읽기` + 경고 "서버에 연결하지 못함 · 브라우저에서 UTF-8로 읽음(…)". pdf: "서버에 연결하지 못함 — PDF·DOCX는 라이브 서버에서만 읽습니다 — 본문을 직접 입력에 붙여넣기" |
| ⑦ 정적 판(업로드 API 404) | docx: "정적 판 · 업로드 API 없음 — PDF·DOCX는 라이브 서버에서만 읽습니다 — 본문을 직접 입력에 붙여넣기". md: 브라우저 읽기 + 경고 "정적 판 · 업로드 API 없음 · …". 판단 뒤 추가 요청 0(총 1건) |

콘솔:

```
"console_errors_total": 4,
"console_network_log": [
  "Failed to load resource: the server responded with a status of 415 (Unsupported Media Type)",   ← ③ hwp(의도)
  "Failed to load resource: net::ERR_FAILED",                                                        ← ⑥ 차단(의도)
  "Failed to load resource: net::ERR_FAILED",                                                        ← ⑥ 차단(의도)
  "Failed to load resource: the server responded with a status of 404 (Not Found)"                   ← ⑦ 정적 판(의도)
],
"console_other_errors": [],
"page_errors": [],
"external_requests": [],
```

- 본 흐름(① docx · ② pdf · ④ 파일명) 콘솔 오류 **0**, 스크립트 오류·페이지 오류 **0**, 외부 요청 **0**
- 남은 4줄은 Chromium이 4xx 응답·차단 요청마다 스스로 찍는 네트워크 기록이다. 모두 일부러 만든 거부·실패 단계에서만 나오며 검사기가 단계별로 확인한다(hwp 단계는 415 기록뿐이어야 통과)
- 스크린샷: `docs/reports/E4-L1f_upload.png`(docx 반영), `E4-L1f_pdf_warn.png`(쪽수·경고), `E4-L1f_hwp.png`(415 문구), `E4-L1f_busy.png`(읽는 중…·이스케이프된 파일명), `E4-L1f_static.png`(정적 판 안내)

### 3. `python scripts/verify.py` — 통과

```
$ python scripts/verify.py
...
1030 passed, 26 skipped in 100.82s (0:01:40)
보안: 파일 359개
계약: 2개
테스트: 통과
verify 통과
```

## 바꾼 파일

- `src/neumann/webui/index.html`: `readFile`과 새 도우미(`dropHtml`·`fileWarnHtml`·`upDetail`·`upDone`·`readLocal`·`upSize`·`upExt`, 상수 `UP*`), `renderInput`의 드롭존 한 줄(`area = dropHtml() +`)과 파일 카드 아래 `fileWarnHtml() +` 한 줄, CSS 한 줄. 다른 부분(템플릿·예시·적합성·전송 고지·리포트)은 손대지 않았다
- `tests/e4/test_webui_upload.py`(새), `tests/e4/test_webui_upload_ui.py`(새)
- `docs/reports/E4-L1f.md`, `docs/reports/E4-L1f_*.png`(5장)

## 결정(스펙이 모호해서 고른 것)

- **정적 판 판단**: 스펙은 "404이거나 fetch 실패". 405(GitHub Pages가 POST에 주는 응답)·501(`python -m http.server`)도 "업로드 API 없음"으로 본다. `window.NEUMANN_STATIC`(E6-L3a 정적 빌드가 주입)이 있으면 요청 없이 정적 판으로 시작한다. 404·405·501 판단은 페이지 안에서 기억해 다시 요청하지 않는다
- **fetch 실패 = 네트워크 오류이자 정적 판 신호**: 둘을 합쳐, md·txt는 브라우저 읽기로 물러나되 "서버에 연결하지 못함"을 파일 카드 경고에 남기고(폴백을 숨기지 않음), pdf·docx는 "서버에 연결하지 못함 — (라이브 서버 안내)"를 오류로 보인다. 연결 실패는 기억하지 않는다(서버가 돌아오면 다음 업로드는 서버로)
- **10 MB 초과는 브라우저에서 먼저 막는다**: "파일이 10 MB를 넘습니다(…) — 올리지 않았습니다". 큰 본문을 보내다 서버가 413으로 먼저 끊으면 브라우저에 연결 끊김(= "서버에 연결하지 못함")으로 보일 수 있어서다. 기준은 서버와 같은 10 × 1024 × 1024바이트이고, 그 밖의 413(글자·쪽수·압축·시간)은 서버 문구 그대로다
- **거부돼도 앞의 본문은 둔다**: hwp 같은 거부가 오면 오류 문구만 보이고 이미 올린 본문·파일 카드는 지우지 않는다(잘못 고른 파일 때문에 입력을 잃지 않게)
- **상태 변수**: `S`(공용 상태 선언 줄)를 고치지 않으려고 업로드 전용 `UP`(`busy`·`api`·`warn`)를 따로 두었다. 경고는 받은 본문과 짝지어 저장하고, 본문이 바뀌면 보이지 않는다
- **PDF 견본**: `tests/e4/test_upload.py`의 `make_pdf`·`HWP5_BYTES`·`HWPX_BYTES`를 가져다 쓴다(한국어 ToUnicode PDF를 다시 만들지 않음). DOCX는 스펙대로 python-docx로 새로 만든다
- **FastAPI 0.141**: 포함 라우터가 `app.routes`에 `_IncludedRouter`로 감싸여 경로가 안 보여서, 라우터 연결은 OpenAPI 스키마(`/upload/plan` POST)로 확인한다

## 못 한 것

- 없음(완료 기준 3개 충족). 실제 OpenAI 호출·8010/8020 서버·공개 서버는 쓰지 않았다
- 정적 빌드(E6-L3a) 산출물 위에서 직접 돌려 보지는 않았다. 정적 빌드는 입력 화면의 파일 업로드 탭을 데모 선택으로 바꿔 숨기므로 그 화면에서는 업로드가 보이지 않는다. 정적 판 분기는 Playwright에서 `/upload/plan` 404로 흉내 내 확인했다

## 다음

- PM: E4-L1e(같은 index.html의 AI4S 예시·템플릿)와 병합할 때 겹칠 수 있는 곳은 `renderInput`의 드롭존 줄(`area = dropHtml() +`)과 그 두 줄 아래 `fileWarnHtml() +` 한 줄, CSS `.file .x:hover` 다음 한 줄뿐이다
- 거부(415 등) 때 앞 파일 카드가 남아 있어 오류 문구와 같이 보인다. 헷갈린다는 의견이 있으면 오류가 난 파일 이름을 문구 앞에 붙이는 정도로 바꿀 수 있다
- 대용량(수 MB) pdf·docx에서 "읽는 중…" 시간과 20초 상한 문구는 실제 계획서 파일로 한 번 더 보면 좋다(이번에는 작은 견본만)
