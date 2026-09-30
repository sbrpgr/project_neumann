# E4-L1a 보고서 — 계획서 업로드 파서(txt·md·pdf·docx)

- 빌더: claude-opus-5.5 · 브랜치 `task/E4-L1a` · 목표 40분
- 소유 파일만 만들었다: `src/neumann/api/upload.py`, `tests/e4/test_upload.py` (+ 이 보고서)

## 무엇을 했나

1. `parse_plan_upload(filename: str, data: bytes) -> str` — 확장자와 매직바이트로 형식을 판별해 본문을 돌려준다.
   - txt·md: BOM(UTF-8·UTF-16) → UTF-8 → CP949(경고) → UTF-8 치환(깨진 글자 5% 이하일 때만, 경고).
   - pdf: pypdf. 빈 쪽은 "텍스트가 없는 쪽: N (스캔 이미지일 수 있음, OCR 안 함)" 경고. 암호 PDF는 빈 암호로 열어 보고 안 되면 422. 200쪽 넘으면 413(아래 S-03).
   - docx: python-docx. 본문 순서대로 문단과 표를 읽는다(표는 행마다 한 줄, 셀은 ` | `). 가로 병합 셀은 한 번만, 세로 병합의 연속 셀은 되풀이하지 않는다. 내용 컨트롤(`w:sdt`) 안 문단도 읽는다. zip 상한은 아래 S-03.
   - 거부: 10MB(10 × 1024 × 1024바이트) 초과 413, HWP·HWPX 415 + `"HWP는 PDF나 DOCX로 저장해 올려 주세요"`(확장자 `.hwp .hwpx .hwt .hml` 또는 매직바이트: HWP 3 서명, OLE 안 `HWP Document File`·`HwpSummaryInformation`, zip `mimetype=application/hwp+zip`·`Contents/`), 구형 .doc 등 OLE 415, 그 밖 미지원 415, 빈 파일·손상·텍스트 없음 422.
   - 정리: `models.normalize_text`(LF·NFC) → 제어문자 제거(탭·줄바꿈 제외) → 줄 끝 공백 제거 → 앞뒤 빈 줄 제거. pdf·docx만 연속 빈 줄을 하나로 줄인다(txt·md는 사용자 줄 번호 보존).
2. `extract_plan(filename, data) -> PlanExtract` — 본문 + `kind`·`size_bytes`·`pages`·`encoding`·`warnings`·`lines`. 라우터가 쓰고, 파이프라인에서 메타가 필요하면 이것을 쓴다.
3. FastAPI `router`: `POST /upload/plan`(multipart/form-data, 필드 `file`). **디스크에 쓰지 않는다.** Starlette `UploadFile`은 1MB가 넘으면 임시 파일로 내려 쓰므로(`MultiPartParser.spool_max_size = 1MB`, 확인함) 쓰지 않고, 요청 본문을 스트림으로 읽어 `python_multipart.MultipartParser` 콜백으로 파일 파트만 `bytearray`에 모은다. Content-Length 선검사 + 스트림 누적 검사로 10MB를 넘으면 바로 413. 추출은 `run_in_threadpool`.
4. 테스트 57건(`tests/e4/test_upload.py`, S-03 상한 14건 포함). pdf·docx 견본은 테스트 안에서 만든다(커밋한 바이너리 없음). PDF는 글자마다 2바이트 CID + ToUnicode CMap을 붙인 최소 PDF를 직접 써서 한국어가 pypdf 추출을 거쳐 글자 그대로 돌아오는지 본다.

## SEC-1 S-03 대응(업로드 증폭) — PM 요청으로 추가

점검 재현: 127KB DOCX(압축 해제 37MB) → 응답 37초·24.8MB. 아래 상한을 넣었다. 상한 초과는 모두 413 + 사용자 문구, 붐비면 503.

| 상한 | 값 | 어디서 | 문구 상수 |
|---|---|---|---|
| zip 압축 해제 합계 | 20MB | 형식 판별 단계(zip 목록만 보고, 풀기 전에) | `ZIP_BOMB_MESSAGE` |
| zip 항목 수 | 1,000개 | 같음 | 같음 |
| 항목 압축비 | 100배(1MB 넘는 항목) | 같음 | 같음 |
| PDF 쪽수 | 200쪽(넘으면 거부, 전에는 300쪽까지 자르고 경고) | 쪽 추출 전 | `TOO_MANY_PAGES_MESSAGE` |
| 추출 글자 수 | 50,000자(정리 뒤). 추출 중 누적 200,000자를 넘으면 끝까지 읽지 않고 중단 | pdf 쪽·docx 문단마다 | `TOO_MANY_CHARS_MESSAGE` |
| 처리 시간 | 20초. HTTP 경로의 pdf·docx는 **별도 프로세스**에서 돌리고 넘으면 강제 종료. 루프 안 협조적 예산도 같이 | `extract_plan_isolated` | `TIMEOUT_MESSAGE` |
| 동시 처리 | 2건, 자리 대기 5초 뒤 503 | `extract_plan_isolated` | `BUSY_MESSAGE` |

- 작업자 프로세스: `python -I -B -c …`(환경변수로 코드 주입 불가, 바이트코드 안 씀). 이름에 KEY·SECRET·TOKEN·SALT·PASSWORD가 든 환경변수(API 키 포함)는 넘기지 않는다. 감사 훅(`sys.addaudithook`)으로 쓰기 모드 파일 열기를 막는다. 내부 예외 문구는 내보내지 않고 고정 문구 422(S-04 방향).
- HWP·zip 폭탄·크기 초과는 작업자를 띄우기 전에 부모에서 거부한다. txt·md는 디코딩뿐이라 같은 프로세스.
- 비용: pdf·docx 업로드 한 건마다 작업자 기동 약 0.7초(fastapi import가 대부분).

측정:

```
$ python -m pytest tests/e4/test_upload.py -q --durations=8
2.10s call  test_api_amplification_limits     # 37MB 폭탄 docx·201쪽 pdf·50,001자 txt/docx → 413, 응답 1KB 미만, 각 10초 안
...
57 passed in 13.17s
```

추가된 테스트: `test_char_limit_boundary`(50,000자 통과·50,001자 413), `test_char_limit_pdf_and_docx`, `test_docx_bomb_rejected_fast`(압축 해제 25MB·파일 500KB 미만 → 2초 안에 413, 확장자를 .txt로 바꿔도 413), `test_docx_high_ratio_entry_rejected`(합계 5MB·압축비 100배 초과), `test_zip_entry_count_rejected`, `test_pdf_page_limit_boundary`(200쪽 통과·201쪽 413), `test_cooperative_deadline`, `test_isolated_extraction_runs_in_worker`(부모의 pdf·docx 추출 함수를 망가뜨려도 격리 경로는 성공 → 실제로 작업자에서 돈다), `test_isolated_rejections_pass_through`, `test_isolated_timeout_kills_worker`, `test_concurrency_limit_503`, `test_worker_env_has_no_secrets`, `test_worker_denies_disk_writes`(작업자 안 읽기는 되고 쓰기는 PermissionError, 파일 안 생김), `test_api_amplification_limits`.

변이 확인(해당 테스트 함수 직접 호출):

```
변이6 zip 상한 제거 -> 실패로 잡힘: AssertionError
변이7 PDF 쪽수 상한 제거 -> 실패로 잡힘: Failed
변이8 글자 상한 제거 -> 실패로 잡힘: Failed
변이9 격리 프로세스 제거 -> 실패로 잡힘: Failed
```

실제 파일(격리 경로, 오탐 없음): 발표 PDF 19쪽 11,424자 1.86초, DOCX 3개 7,582~24,727자 1.07~1.31초, 모두 경고 없음.

남은 것(PM·E4-L2c): `/upload/plan`을 `serving.py`의 속도 제한 보호 경로에 넣는 일. 작업자 메모리 상한은 걸지 않았다(Windows에 RLIMIT 없음. 입력 10MB·zip 20MB·글자 상한으로 간접 제한).

## 검증 지적 반영(PASS-조건부 → 1건)

- 지적: `MultipartParser(...)` 생성이 `try` 밖이라 경계(boundary)가 256자를 넘으면 `FormParserError`가 그대로 올라가 500.
- 수정: 생성을 `try` 안으로 옮기고 `FormParserError`·`ValueError`를 400 `"multipart 본문을 해석할 수 없습니다"`로 바꾼다.
- 테스트 `test_api_overlong_boundary_400`: 256자 경계 200, 257자·4,000자 경계 400 + 문구. 대조로 수정 전(HEAD) 코드에 257자 경계를 보내면 500이었다.

```
$ python -m pytest tests/e4/test_upload.py -q
58 passed in 10.59s
$ python scripts/verify.py
243 passed in 11.71s
verify 통과
```

## main.py 연결용 인터페이스

```python
from neumann.api.upload import router            # main.py의 선택 라우터 목록에 이미 "neumann.api.upload"가 있다
from neumann.api.upload import parse_plan_upload, extract_plan, UploadRejected, HWP_MESSAGE, MAX_UPLOAD_BYTES

parse_plan_upload(filename: str, data: bytes) -> str        # 거부 시 UploadRejected(.status_code 413|415|422, .message)
extract_plan(filename, data, *, deadline_s=20.0) -> PlanExtract   # 같은 프로세스. .text .kind .size_bytes .pages .encoding .warnings .lines
extract_plan_isolated(filename, data, *, timeout_s=20.0) -> PlanExtract  # 라우터가 쓰는 것. 동시 2건(503), pdf·docx 별도 프로세스·강제 종료
```

`POST /upload/plan` 응답(200):

```json
{"filename": "계획서.md", "kind": "md", "size_bytes": 22, "pages": null, "encoding": "utf-8",
 "text": "# 연구 목표\n본문", "lines": 2, "chars": 10, "warnings": []}
```

오류는 FastAPI 기본 형태 `{"detail": "<안내 문구>"}` — 400(multipart 오류·파일 2개), 413(상한 초과: 10MB·50,000자·200쪽·압축 해제 20MB·20초), 415(HWP·미지원·multipart 아님), 422(빈 파일·손상·암호·텍스트 없음·file 필드 없음), 503(동시 처리 자리 없음).
`lines`는 `PlanDocument.from_text`와 같은 규칙(`text.split("\n")`)이라 줄 번호가 그대로 맞는다. 목업 `plan.meta`("파싱 완료 · 15줄 · 2쪽")는 `lines`·`pages`로 채우면 된다.

## 완료 기준별 측정

### 1. 형식별 추출, 한국어 보존, 크기·HWP 거부

```
$ python -m pytest tests/e4/test_upload.py -v
test_txt_utf8_korean_preserved_exactly PASSED        # fixtures/plans/plan.md를 UTF-8 txt로 → 본문 글자 그대로
test_md_kind_and_blank_lines_kept PASSED
test_txt_cp949_fallback_with_warning PASSED          # 같은 본문을 CP949로 → 글자 그대로 + 경고
test_txt_bom_crlf_and_nfd_normalized PASSED          # BOM·CRLF·NFD 한글 → LF·NFC
test_txt_utf16_bom PASSED
test_txt_undecodable_bytes PASSED
test_text_matches_plan_document_lines PASSED         # lines == PlanDocument.from_text 줄 수
test_pdf_korean_extracted PASSED                     # 2쪽 한국어 PDF → 4줄 글자 그대로, pages=2
test_pdf_fixture_plan_round_trip PASSED
test_pdf_blank_page_warns PASSED
test_pdf_without_text_rejected PASSED
test_pdf_encrypted_rejected PASSED
test_pdf_corrupt_rejected PASSED
test_docx_paragraphs_and_tables_in_order PASSED      # 제목·문단·표(가로·세로 병합) 순서대로
test_docx_corrupt_rejected PASSED
test_content_wins_over_extension_with_warning PASSED
test_pdf_marker_inside_text_stays_text PASSED
test_control_chars_removed PASSED
test_filename_path_stripped PASSED
test_size_limit_boundary PASSED                      # 정확히 10MB 통과, +1바이트 413
test_hwp_rejected_415[hwp5|hwpx|hwp-ext-only|hwpx-ext-only|hwp5-as-pdf|hwpx-as-docx|hwp3] PASSED ×7
test_unsupported_rejected_415[doc|png|pptx|rtf|binary-as-txt] PASSED ×5
test_empty_rejected PASSED
test_route_registered PASSED
test_main_app_wires_upload_router PASSED             # main.py 앱에서 /upload/plan 200, ROUTER_STATE ok
test_api_txt PASSED
test_api_pdf_and_docx PASSED
test_api_cp949_warning PASSED
test_api_hwp_415 PASSED                              # detail == "HWP는 PDF나 DOCX로 저장해 올려 주세요"
test_api_size_limits PASSED                          # 10MB 200, +1바이트 413(스트림 단계), +200KB 413(Content-Length 선검사)
test_api_request_shape_errors PASSED
test_api_never_touches_disk PASSED                   # 2.6MB txt·pdf·docx 업로드 중 임시파일·쓰기 열기 0회
test_disk_guard_catches_default_upload_path PASSED   # 대조군: 기본 UploadFile 2MB는 감시에 잡힌다
43 passed in 1.64s
```

검사기가 실제로 검사하는지 변이로 확인했다(모듈 속성을 바꿔 해당 테스트 함수 직접 호출):

```
변이1 HWP 확장자 검사 제거 -> 실패로 잡힘: AssertionError
변이2 CP949 폴백 제거 -> 실패로 잡힘: AssertionError
변이3 크기 상한 +1 -> 실패로 잡힘: Failed (DID NOT RAISE UploadRejected)
변이4 DOCX 표 무시 -> 실패로 잡힘: AssertionError
변이5 HWP 매직바이트 검사 제거 -> 실패로 잡힘: AssertionError
```

실제 파일 확인(읽기만, 저장소에 넣지 않음. 로컬 `노이만_본선자료`의 발표 PDF·DOCX):

```
발표자료\본선_발표자료.pdf   pdf  pages 19  lines 504  chars 11424  hangul 5710  warn ()  1.08s
발표자료\질의응답.docx       docx           lines 309  chars 17776  hangul 9568  warn ()  0.13s
구현_계획서.docx             docx           lines 438  chars 24727  hangul 10728 warn ()  0.10s
데이터_활용과_확장_잠재력.docx docx         lines 172  chars 7582   hangul 3838  warn ()  0.05s
```

main.py(6067212) 앱으로 확인:

```
ROUTER_STATE: {'neumann.api.export': 'ok', 'neumann.api.upload': 'ok', ...}
POST /upload/plan 계획서.md → 200 {'kind': 'md', 'lines': 2, 'warnings': [], ...}
POST /upload/plan 계획서.hwp → 415 {'detail': 'HWP는 PDF나 DOCX로 저장해 올려 주세요'}
```

### 2. `python scripts/verify.py`

```
$ python scripts/verify.py        (_COMMON.md 환경변수, main 6067212 위, S-03 상한 추가 뒤)
242 passed in 13.86s
보안: 파일 125개
계약: 2개
테스트: 통과
verify 통과
```

## 바꾼 파일

- `src/neumann/api/upload.py` (새 파일)
- `tests/e4/test_upload.py` (새 파일)
- `docs/reports/E4-L1a.md` (이 보고서)

## 결정 (스펙이 모호해서 고른 것)

- **디스크 미저장을 문자 그대로 지키려고 FastAPI `UploadFile`을 쓰지 않았다.** 대신 라우트가 `Request`를 받아 multipart를 직접 파싱한다. 그래서 OpenAPI 요청 본문은 `openapi_extra`로 적었다(`file`: binary).
- `parse_plan_upload`는 지시문대로 `str`만 돌려주고, 경고·쪽수·인코딩은 `extract_plan`(→ `PlanExtract`)으로 따로 뺐다. 거부는 FastAPI에 묶이지 않은 `UploadRejected` 예외로 내고 라우터가 `HTTPException`으로 바꾼다.
- 상태 코드: 크기 413, 형식(HWP·미지원·multipart 아님) 415, 내용(빈 파일·손상·암호·텍스트 없음) 422, 요청 모양(파일 2개·multipart 깨짐) 400.
- 내용이 PDF·DOCX로 확인되면 확장자가 달라도 내용 기준으로 읽고 경고한다. 확장자가 `.pdf`·`.docx`인데 내용이 아니면 422. 확장자 없는 텍스트나 `.rtf` 등은 415(txt·md 확장자일 때만 텍스트로 받는다).
- PDF 머리(`%PDF-`)는 0바이트 위치일 때만 믿고, 1024바이트 안 다른 위치는 확장자가 `.pdf`일 때만 믿는다(본문에 `%PDF-`가 든 md를 PDF로 오인하지 않게).
- PDF 쪽 경계에 빈 줄을 끼우지 않는다(문단이 쪽을 넘어가면 이어지게).
- 개인정보 가림은 여기서 하지 않는다. 업로드 응답은 사용자 자신에게 돌려주는 원문이고, 가림은 `PlanDocument.from_text`(분석 입력)와 E3-L1c 몫이다.
- 작업 트리가 main보다 뒤(d263c18)에 있어 지시문이 없었다. `task/E4-L1a`를 main(7022556)에서 만들고, 끝나기 전 main(6067212, main.py 라우터 연결 포함)으로 rebase해 통합을 확인했다.

## 못 한 것

- 스캔 PDF 문자 인식(OCR): 하지 않는다. 텍스트 없는 쪽은 경고, 전부 없으면 422로 안내한다.
- DOCX의 머리글·바닥글·각주·텍스트 상자(`w:txbxContent`) 본문은 읽지 않는다.
- 화면 연결(드롭존 → `/upload/plan`)은 E4 화면 과제 몫이다.

## 다음 과제에 넘길 것

- **목업 드롭존 문구에 HWP가 들어 있다**(`PDF · DOCX · HWP · MD · TXT · 최대 10 MB`). 서버는 HWP를 415로 거부하므로 화면 과제에서 문구를 `PDF · DOCX · MD · TXT`로 바꾸거나, 415 `detail`을 토스트로 그대로 보여 주면 된다.
- 화면은 `warnings`를 입력 화면에 보여 주는 것이 좋다(CP949 추정, 빈 쪽, 확장자 불일치).
- 파이프라인 입력: `PlanDocument.from_text(parse_plan_upload(name, data), session_id)` — 줄 수가 응답 `lines`와 같다.
- 새 패키지 없음(pypdf·python-docx·python-multipart는 이미 의존성에 있다).
