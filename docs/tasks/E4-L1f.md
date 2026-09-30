# E4-L1f — 화면 파일 업로드를 `/upload/plan`에 연결

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5
- 목표 시간: 40분
- 소유: `src/neumann/webui/index.html`의 **`readFile` 함수와 드롭존 안내 문구, 파일 카드 부분만**, `tests/e4/test_webui_upload*.py`
- E4-L1e(구축 세션, AI4S 예시·템플릿)가 같은 파일을 고치고 있다. 다른 부분은 건드리지 않아 병합 충돌을 줄인다
- **실제 OpenAI 호출 금지**(mock). 서버는 `NEUMANN_LLM_PROVIDER=mock`으로 띄운다

## 배경

E4-L1a(`src/neumann/api/upload.py`, `POST /upload/plan`)가 main에 병합됐다. 받는 형식은 txt·md·pdf·docx이고, HWP는 415로 거부한다.
상한은 10MB, 정리 뒤 50,000자, PDF 200쪽, 처리 20초, 동시 2건(붐비면 503)이다.
그런데 화면(`index.html` 596행 근처 `readFile`)은 아직 md·txt만 브라우저에서 읽고, PDF·DOCX는 "준비 중"이라고 안내한다.

## 만들 것

1. `readFile(file)`
   - 서버 판: 모든 형식을 `FormData`(`file` 필드)로 `POST /upload/plan`에 보낸다.
     - 성공하면 응답의 `text`를 `S.text`, `filename`을 `S.filename`에 넣는다. `S.fileMeta`에는 형식·크기·쪽수(pdf)·인코딩을 넣는다.
     - `warnings`가 있으면 파일 카드 아래에 작게 보여 준다.
   - 오류(400·413·415·422·503)는 서버 `detail` 문구를 그대로 `S.inErr`에 보여 준다. HWP 안내 문구도 서버 것을 쓴다. 네트워크 오류는 "서버에 연결하지 못함"으로 표시한다.
   - 올리는 동안에는 드롭존에 "읽는 중…"을 표시하고 중복 제출을 막는다.
   - 정적 판(서버 없음, E6-L3a 정적 빌드. `/upload/plan`이 404이거나 fetch가 실패하면 판단):
     - md·txt는 지금처럼 브라우저에서 읽는다.
     - pdf·docx는 "PDF·DOCX는 라이브 서버에서만 읽습니다 — 본문을 직접 입력에 붙여넣기"로 안내한다.
   - 파일명과 경고는 `esc()`나 `textContent`로만 넣는다(`innerHTML`에 원문 금지. E4-L1a 검증 지적 3).
2. 드롭존 안내 문구를 "TXT · MD · PDF · DOCX · 최대 10 MB · 정리 뒤 50,000자 · HWP는 PDF·DOCX로 저장"으로 바꾼다. `accept`에 `.pdf`, `.docx`와 해당 MIME을 추가한다.
3. 테스트 `tests/e4/test_webui_upload.py`
   - FastAPI TestClient로 `/upload/plan`에 txt·md·docx(python-docx로 생성)·hwp를 보내 응답 형태를 확인한다. 화면이 쓰는 필드(`text`·`filename`·`kind`·`pages`·`encoding`·`warnings`, 오류 `detail`)가 있는지 본다.
   - index.html 정적 검사:
     - `readFile`이 `/upload/plan`을 부른다
     - "PDF · DOCX 준비 중" 문구가 없다
     - 파일명을 `esc(`로 감싼다
   - 가능하면 Playwright(1440×900, mock 서버)로 docx 업로드부터 본문 반영까지 확인한다. 스크린샷은 `docs/reports/E4-L1f_upload.png`에 둔다.

## 완료 기준

1. `python -m pytest tests/e4 -q -k "upload"` 통과
2. mock 서버에서 docx·pdf·hwp 업로드 결과(본문 반영, 415 문구)를 보고서에 적는다. 콘솔 오류 0
3. `python scripts/verify.py` 통과(venv 파이썬)
