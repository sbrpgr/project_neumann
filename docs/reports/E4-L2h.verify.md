**최종 판정: PASS-조건부** (브랜치 자체는 완료 기준을 모두 통과. 병합 때 할 것 3개: core-final과 `upload.py` 충돌 5곳 해소 뒤 재측정, `docs/API.md` 갱신, 조용한 시간에 전체 verify 0 종료 확인)

# E4-L2h 검증 보고서 (HWPX 업로드, HWP 5.0은 415 유지)

- 검증자: Claude Sonnet 5.5 · 2026-10-01 · 대상: `task/E4-L2h` 머리 `0220be3`(`[E4-L2h-reverify]`). `git log --grep '^\[E4-L2h\]'`의 가장 새 커밋은 `2e36931`이지만, 그 뒤 `378414e`(검증 FAIL 보고서)·`c11ae5a`(mimetype 경계 수정)·`0220be3`(재검증 PASS)이 같은 브랜치에 쌓여 있어 브랜치 머리를 검증했다.
- 읽은 것: `docs/reports/E4-L2h.md`(빌더 보고서), `E4-L2h.codex.verify.md`(이전 FAIL: mimetype 크기 위조), `E4-L2h-counterexample-fix.md`, `E4-L2h.codex.reverify.md`(PASS), `docs/decisions.md` 65행(23:4x, HWPX 압축 해제 한도는 실제로 푸는 본문 항목에만, HWP 5.0은 범위 밖·415 유지).
- 환경: scratch worktree `…/scratchpad/wt_l2h`(`0220be3`, 끝난 뒤 제거). 파이썬 `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `PYTHONPATH="src;."`, `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_TESTS=0`, `NEUMANN_LIVE_LLM_OK`·`OPENAI_API_KEY` 제거. **OpenAI 호출 0, `.env`·환경변수 값 열람 0, 커밋 0, `git stash` 0.** 시험 서버 포트는 8193 하나(8158·8171은 다른 에이전트가 쓰고 있어 건드리지 않았다), 끝난 뒤 LISTEN 없음 확인.
- 검증 입력은 전부 내가 새로 만든 것이다(생성기 `hgen.py`, 프로브 `probe1~4.py`는 scratchpad에 있고 저장소에 넣지 않는다). 빌더 테스트 코드는 재사용하지 않았다. 실제 한글 앱이 저장한 HWPX는 승인된 폴더(`노이만_본선자료`)에 없어서 구조를 같게 만든 합성 파일이다(한계 1).

## 요약표

| # | 요청 항목 | 결과 | 근거 |
|---|---|---|---|
| 1 | 직접 만든 실제 구조 HWPX: zip 부품·한글·구역·표 | PASS | 아래 A |
| 2 | BMP가 많은 HWPX에 거짓 413 없음 | PASS | 아래 B |
| 3 | 본문 항목 zip 폭탄 거부 | PASS | 아래 C (19건 전부 413/422, 최대 1.4초) |
| 4 | 암호·DRM HWPX 거부와 안내 | PASS(DRM은 일반 안내) | 아래 D |
| 5 | 손상 HWPX에 500 없음 | PASS | 아래 E (31건) |
| 6 | .hwp는 415 안내 | PASS | 아래 F (13건) |
| 7 | PDF·DOCX 영향 없음 | PASS | 아래 G (main과 글자 해시 동일) |
| 8 | 변이 500건 퍼징, 격리 프로세스·20초 | PASS | 아래 H (예외 0, 500 0, 최대 3.55초) |
| 9 | 화면 accept·문구 | PASS | 아래 I (Playwright 통과) |
| 10 | `git merge-tree` | main 깨끗, core-final 충돌 5곳 | 아래 J |
| 11 | pytest(업로드)·`scripts/verify.py` | 업로드·HWPX 테스트 전부 통과. verify 전체는 L2h 미접촉 시간 단언 1건이 부하로 실패(2회, 매번 다른 테스트) — 0 종료 미확인 | 아래 K |

## A. 실제 구조 HWPX (직접 생성, HTTP `POST /upload/plan`)

생성한 zip 부품: `mimetype`(무압축·맨 앞) · `version.xml` · `META-INF/container.xml`·`manifest.xml` · `settings.xml` · `Contents/header.xml`·`content.hpf`·`section0~2.xml` · `Preview/PrvText.txt` · `BinData/image1.bmp`. 누락 0.

- 한글 문서(구역 3개, spine 순서를 파일 번호와 다르게 0·2·1, 표 3행×3열 + 셀 안 두 문단, 각주, 탭·줄바꿈, 머리말): **기대한 12줄(줄바꿈 포함 13줄)과 글자 그대로 일치.** 구역은 spine 순서, 각주는 본문 문단 바로 뒤, 표는 행마다 한 줄(` | `), 셀 안 두 문단은 공백으로 이음, 머리말 "숨김텍스트"는 나오지 않음, 경고 0. 0.66초.
- 응답 필드: `kind=hwpx`, `lines=13`, `chars=208`, `chars_no_space=153`, `paragraphs=13`을 내가 다시 센 값과 비교해 모두 같다. `PlanDocument.from_text(text)`의 줄 수 13·본문 왕복 동일(줄 번호와 일치).
- `mimetype`·`content.hpf`·manifest가 없는 최소 문서 200. `content.hpf`가 없으면 번호순(`section2`가 `section10`보다 앞) 200. `.HWPX` 대문자·확장자 `.bin`(경고 "내용 기준(HWPX)") 200. 본문 구역이 깨졌을 때 `PrvText.txt`로 물러나 경고와 함께 200. UTF-16 구역 200.
- 글자 수 상한: 40,000자 200, 50,398자·60,000자 413(격리 경로).

## B. BMP가 많은 HWPX에 거짓 413 없음

| 입력 | zip 크기 / 풀었을 때 | 결과 |
|---|---|---|
| 매끈한 BMP 14장×6MB(압축비 >>100) | 148KB / 84MB | **200** |
| 그림 항목 980개(전체 항목 988개) | 작음 | **200** |
| BinData 안에 중첩 zip(풀면 30MB) | 작음 | **200**(풀지 않음) |
| BMP 한 장 50MB(압축비 >100) | 작음 | **200** |
| 같은 50MB 영(零) 그림을 넣은 **DOCX** | — | **413**(DOCX는 모든 항목을 읽으므로 기존 한도 유지, 회귀 없음) |
| 잡음 섞은 BMP 6장×10MB | 25.3MB / 60MB | 413 "파일이 10MB를 넘습니다"(파일 상한, 내 입력이 10MB 초과였음. 정상 동작) |

결정 23:4x("한도는 실제로 푸는 본문 항목에만")가 구현과 일치한다. 그림 때문에 압축 해제 합계 20MB·압축비 100배에 걸리는 거짓 413은 재현되지 않는다. 항목 수 상한 1,000개는 전체를 세므로, 그림이 1,000개가 넘는 문서는 413이다(한계 4).

## C. 본문 항목 zip 폭탄 (모두 거부)

| 입력 | 결과 | 시간 |
|---|---|---|
| section0 25MB 해제(zip 76KB) | 413 | 0.01초 |
| section0 19MB(압축비 >100) | 413 | 0.01초 |
| 구역 5개×5MB = 25MB 합계 | 413 | 0.01초 |
| 구역 25개×0.9MB = 22MB 합계(항목별 비율검사 회피) | 413 | 0.00초 |
| 항목 1,004개 | 413 | 0.02초 |
| content.hpf 40MB / PrvText 40MB / manifest 40MB / manifest 1.1MB | 413 ×4 | 0.01초 |
| mimetype 70KB | 422(격리 전 유한 읽기) | 0.01초 |
| 구역 257개 | 413 | 0.78초 |
| 구역 19개×14만 요소(요소만 있는 폭탄 2.7M, 측정 `elements_2.7M`) | 413 | 0.68초 |
| 중첩 문단 400단계 / 표 중첩 200단계 | 422(libxml2 깊이 256) | 1.1 / 0.9초 |
| 엔티티 폭탄(DTD) / XXE `file:///C:/Windows/win.ini` | 422, 응답에 파일 내용 없음 | 0.9초 |
| 중앙 디렉터리 선언 크기를 40바이트로 위조 / 0.9MB로 위조 | 422(읽기 유한) | 0.8초 |
| 구역 5×5MB인데 선언 크기를 100KB로 위조(합계 검사 회피 시도) | 422 | 0.7초 |

요소 상한 직전 문서(49.6만 요소)는 0.75초, 최대 커밋 메모리 72MB(SEC-7의 512MB 상한 안). 6백만 자 단일 텍스트 노드는 libxml2가 거부해 422(0.22초, 119MB).

## D. 암호·DRM

| 입력 | 결과 |
|---|---|
| manifest에 `encryption-data`(ODF 방식) | 422 "암호가 걸린 문서는 처리할 수 없습니다. 한글에서 암호를 풀고 다시 저장해 올려 주세요" |
| 같은 manifest를 UTF-16으로 저장 | 422 위와 같은 안내 |
| 본문이 이진 쓰레기 + manifest 암호 | 422 암호 안내 |
| 구역 항목의 zip 암호 플래그(중앙 디렉터리) | 422 암호 안내 |
| BinData 항목만 암호 플래그 | 422 암호 안내(플래그 붙은 항목이 하나라도 있으면 거부. 보수적) |
| DRM 봉투(zip이 아닌 독자 헤더) `.hwpx` 2종 | 422 "HWPX 파일이 아니거나 손상되었습니다. 다시 저장해 올려 주세요" (안내는 있으나 DRM 전용 문구는 아님. 한계 2) |

## E. 손상 HWPX: 500 없음 (31건 모두 구조화된 4xx 또는 안전한 200)

빈 파일(422 "빈 파일입니다"), PK 머리만, EOCD만, 절반·10바이트·1바이트 잘림, 앞뒤 쓰레기(뒤 쓰레기 200 = zip은 끝에서 읽으므로 정상), 전부 0, 무작위 4KB, PK+무작위, 텍스트 파일 `.hwpx`, 구역 UTF-8 깨짐, 빈 구역, 글자 없는 구역(422 "텍스트를 찾지 못했습니다"), 구역 없음, content.hpf 깨짐(200, 번호순으로 물러남), hpf에 `../../etc/passwd`·`C:/x.xml`(200, 무시), manifest 깨짐(422), 같은 이름 구역 2개(422), 치환 문자 500개(422 "글자가 많이 깨져 있습니다"), `&#0;`·`&#x1;` 참조(422), 중앙 디렉터리 필드 6종 손상(crc·csize·usize·method·flags·offset) 및 모든 CRC 손상(422 "mimetype이 손상…", 격리 전). **500·빈 응답·스택 문구 0건.** 모든 응답 본문이 `{"detail": "<한국어 안내>"}` 한 필드다.

## F. HWP는 415 안내

`plan.hwp`(OLE + `HWP Document File`), `plan.hwp`(쓰레기), `.hwt`, `.hml`, `.HWP` 대문자, **`.hwpx`·`.docx`·`.pdf`·`.txt`·확장자 없음 이름이라도 내용이 HWP 5(OLE, `HWP Document File` 또는 `HwpSummaryInformation`)·HWP 3인 파일** 전부 415 "HWP는 한글에서 HWPX 또는 PDF로 저장해 올려 주세요" (13건). 일반 구형 `.doc`(OLE, HWP 표식 없음)은 기존대로 415 "구형 Office 문서…". HWP 5.0을 읽으려는 코드 경로는 없다.

## G. PDF·DOCX·TXT·MD 영향 없음

같은 입력 20건을 머리(`0220be3`)와 main(`91a7602`)에 넣어 HTTP 응답을 비교했다.

- 같다(상태·kind·쪽수·줄 수·글자 수·본문 SHA-256 앞 16자·경고): 실제 문서 3건(구현_계획서.docx 24,727자 438줄, 질의응답.docx 17,776자 309줄, 본선_발표자료.pdf 19쪽 11,424자 504줄, 읽기만 했고 저장소에 복사하지 않음), 합성 PDF·DOCX(한글·표), UTF-8·CP949 txt, md, 확장자 위장(PDF를 .docx로, DOCX를 .pdf로: 내용 기준 + 경고), 손상 PDF·DOCX(422 같은 문구), 빈 파일, 30MB 영 미디어 DOCX(413 같은 문구).
- 다른 것은 의도한 문구 변경 4건뿐: 미지원 형식 안내에 `hwpx` 추가(exe·png·zip 3건), 스캔(텍스트 없는) PDF가 "텍스트가 없는 PDF(스캔본)는 처리할 수 없습니다. 문자 인식(OCR)은 하지 않습니다…"로 구체화(422 유지).

## H. 변이 퍼징 500건 (격리 작업자, 20초 상한)

- 생성: 기준 문서 5종 × 변이 6방식(바이트 11종: 비트 뒤집기·잘림·삭제·삽입·복제·0 채우기·교환·타 문서 이어붙이기·접두/접미·중앙 디렉터리 필드 조작 / XML 13종: 조각 삭제·복제·`<`·`&#0;`·`&#xD800;`·CDATA·DOCTYPE 삽입·문단 2만 반복·표 중첩 5~300단계·태그 이름 변경·네임스페이스 제거·90만자 본문·요소 14만 개 / 구조 14종: mimetype·hpf·manifest·구역 제거, 대소문자 바꿈, 중복 이름, 압축 방식 bzip2·lzma, 구역 300개, `../`·절대 경로 이름, 나쁜 mimetype, 30MB 그림, 암호 manifest, 미리보기만, 순서 섞기 / 복합) 시드 20261001, 확장자 `.hwpx`·`.docx`·`.pdf`·`.txt`·없음 섞음. 크기 423B~126KB.
- 경로: `_safe_filename` → `_detect_kind`(부모) → `_run_worker`(`python -I -B` 격리 작업자, 20초 강제 종료) = `extract_plan_isolated`와 같은 경로에서 동시 슬롯만 뺐다(8스레드 병렬).

```
ISOLATED  statuses: {200: 268, 422: 184, 413: 18, 415: 30}   kinds: {hwpx: 268}
ISOLATED  wall=71s  max_case=3.55s  over_26s=[]  exceptions=0
ISOLATED  time p50=1.23s p95=2.38s
INPROC    (같은 500건을 같은 프로세스에서)  statuses 동일  exceptions=0
HTTP(60건 표본, 실제 라우터·TestClient)  {200: 28, 422: 26, 415: 2, 413: 4}  max=2.12s  bad=[]  (500 0건)
```

- 예외 0, 500 0, 20초 초과 0. 가장 느린 케이스 3.55초는 8스레드가 CPU를 나눠 쓰는 상황이라, 단독 실행은 0.7~0.9초 안팎이다(core-final의 10초 상한에도 여유).
- 참고: 위조한 중앙 디렉터리 오프셋으로 zipfile이 `UserWarning: Overlapped entries: 'mimetype' (possible zip bomb)`을 stderr에 찍은 경우가 있다(예외가 아니라 경고이고 뒤이어 크기·CRC 대조에서 422). 동작 문제 없음, 로그 잡음만.

## I. 화면 accept·문구

- `src/neumann/webui/index.html` 604~605행: `UP_ACCEPT = '.txt,.md,.markdown,.pdf,.docx,.hwpx,text/plain,text/markdown,application/pdf,…wordprocessingml.document,application/hwp+zip'`, `UP_HINT = 'TXT · MD · PDF · DOCX · HWPX · 최대 10 MB · 정리 뒤 50,000자 · HWP는 HWPX·PDF로 저장'`.
- Playwright(`tests/e4/test_webui_upload_ui.py`, mock 서버 포트 8193, 스크린샷은 scratchpad): `problems []`, 콘솔 "기타 오류" 0, 페이지 오류 0, 외부 요청 0. 위 accept·드롭존 문구가 실제 화면 값과 같다. `.hwp` 올리기는 서버 415 문구 "HWP는 한글에서 HWPX 또는 PDF로 저장해 올려 주세요"가 그대로 보이고, `.hwpx`는 "HWPX · 2.0 KB"로 본문 3줄이 반영된다(콘솔의 "Failed to load resource" 4줄은 의도한 415·404·차단 응답).
- 정적 판(업로드 API 없음)에서 HWPX는 "HWPX 형식은 읽지 못함 · 브라우저에서는 TXT·MD만 읽습니다"로 정직하게 안내한다(코드 읽기로 확인, 실행하지 않음. PDF·DOCX용 "라이브 서버 안내" 문구는 아님. 사소한 다듬기 거리, 차단 아님).

## J. `git merge-tree` (머리 `0220be3`, 공통 조상 `14522ae`)

| 대상 | 결과 |
|---|---|
| `main` (`91a7602`) | **충돌 없음**(`git merge-tree --write-tree` 종료 0, 트리 `4ba7618…`) |
| `codex/core-final-20261001` (`f54ef1d`) | **`src/neumann/api/upload.py` 충돌 5곳**(종료 1). `index.html`·`tests/e4/test_upload.py`는 자동 병합 |

충돌 5곳은 모두 **두 쪽을 함께 남기면 되는 기계적 충돌**이다: ① 모듈 docstring의 상한 줄(SEC-7의 "줄 5,000줄·10초·PDF 폭탄" 문장과 L2h의 "DOCX·HWPX·HWPX XML 요소" 문장), ② import(`zlib`와 `ExitStack, contextmanager`), ③ `extract_plan`의 `_clean` 호출(L2h `collapse_blank=kind in ("pdf","docx","hwpx")` + SEC-7 줄바꿈 수 사전 검사), ④ 글자 수 검사 뒤(L2h `_check_broken_chars` + SEC-7 `MAX_PLAN_LINES` 검사), ⑤ `_ERROR_RESPONSES` 설명문. 병합 뒤 할 일: (a) HWPX도 SEC-7 작업자의 10초·메모리 512MB·자식 프로세스 금지·줄 5,000줄 상한 아래서 돌도록 `tests/e4/test_upload_hwpx.py`·`test_hwpx_*`를 다시 돌리고(이 검증에서 HWPX 최악 입력의 최대 커밋 메모리는 123MB, 최장 0.94초), (b) `_read_zip_mimetype`가 격리 전 경로에 그대로 남는지 확인(이전 재검증 권고와 같음). 위 병합은 PM 몫이라 이 scratch에서는 하지 않았다.

## K. 테스트

- 업로드 관련 7개 파일(`test_upload.py`·`test_upload_hwpx.py`·`test_hwpx_security_regression.py`·`test_hwpx_mimetype_boundary.py`·`test_webui_upload.py`·`test_upload_e2e_ui.py`·`test_webui_upload_ui.py`): **152 passed, 2 skipped(UI 2개는 `NEUMANN_UI_TESTS=1` 없이 건너뜀), 2 failed**. 실패 2건(`test_api_amplification_limits`, `test_api_never_touches_disk`)은 PDF 작업자가 20초 상한을 넘겼다는 413이다. 그 시각에 내 Playwright 서버 기동과 다른 에이전트 프로세스가 CPU를 나눠 쓰고 있었다. **두 테스트만 따로 다시 돌리면 2 passed(51초).**  전체 verify의 pytest가 이 파일들을 모두 포함하고 거기서는 통과했다(아래).
- **`python scripts/verify.py`(scratch worktree 전체)**
  - 1차: 보안 425개 파일·계약 2개 통과, pytest `1 failed, 1308 passed, 47 skipped in 100.11s`. 실패는 `tests/e4/test_loadtest_multiuser.py::test_direct_round_runs_concurrently_and_matches_sequential_reference`(시간 단언, `run_s >= 0.045*n`). 이 브랜치는 그 파일을 건드리지 않았고(14522ae 대비 diff 없음), 같은 파일을 따로 돌리면 13 passed(72초). `docs/decisions.md` 80행이 말한 "부하 중 시간 단언 테스트" 부류(TEST-1 범위)다.
  - 2차(다른 작업이 없을 때 다시): 보안 425개·계약 2개 통과, pytest `1 failed, 1308 passed, 47 skipped in 727.04s`(다른 에이전트 프로세스로 CPU 약 50% 점유, 1차의 7배 걸림). 이번 실패는 1차와 **다른** 시간 단언 테스트 `tests/e3/test_pipeline_parallel_sim.py::test_simulated_parallel_is_faster_and_same`(병렬 벽시계 0.808초 < 2.6×0.24초 기대). 이 브랜치는 `tests/e3`·`pipeline.py`를 건드리지 않았고(14522ae 대비 diff 없음), 따로 돌리면 1 passed(2.98초). 업로드·HWPX 테스트는 두 번 모두 전부 통과.
  - 정리: 전체 verify의 **종료 0은 확인하지 못했다**(두 번 다 부하에 민감한 시간 단언 1건이 실패, 매번 다른 테스트이고 L2h 범위 밖). 1,308건 통과·실패는 L2h 미접촉 파일뿐이라는 것까지가 이 검증의 측정이다. PM이 조용한 시간에 병합 뒤 verify를 다시 돌려 0 종료를 확인해야 한다(TEST-1 범위의 기존 문제, `decisions.md` 80행
- 구조 요구 대조(`0220be3`의 이전 FAIL 반례): 중앙 디렉터리 mimetype 선언 1바이트·실제 64KiB 입력은 `_read_zip_mimetype`가 압축 입력 4KiB·해제 출력 256B로 끊고 크기·CRC·스트림 끝을 맞춰 422로 돌려보낸다. 내 프로브 `cd_corrupt_*`·`mimetype_70KB`가 같은 경계를 독립 입력으로 확인했다(E 절).

## 한계와 권고

1. **실제 한글 앱이 저장한 HWPX는 이 검증에서 읽지 않았다.** 승인된 자료 폴더에 HWPX가 없고, 빌더가 읽었다는 바탕화면 개인 문서 3건은 열지 않았다. 구조(mimetype·content.hpf spine·OWPML 2011 네임스페이스·표·각주·머리말·PrvText)를 같게 합성해 확인했다. 대표 시연 샘플(E4-L1g의 HWPX 문서 샘플)을 고를 때 실제 한글에서 저장한 파일 1~2개로 한 번 더 올려 보길 권한다.
2. DRM 봉투(zip이 아닌 독자 포맷)는 일반 "HWPX 파일이 아니거나 손상" 안내로 거부된다. 거부와 대안 안내(PDF 저장)는 있으나 DRM 전용 문구는 없다. 실제 배포용 문서 표본은 없어 확인하지 못했다.
3. 플래그가 붙은 zip 항목이 하나라도 있으면(BinData 포함) 암호 안내로 거부한다. 안전한 쪽이다.
4. 항목 수 상한 1,000개는 그림까지 센다. 한글이 그림을 1,000개 넘게 넣은 문서는 413이다(매우 드묾, 안내 문구는 "압축 해제 크기" 표현이라 원인이 덜 분명함).
5. **병합 조건(PASS-조건부의 이유):** ① core-final과 `upload.py` 충돌 5곳 해소 뒤 HWPX·PDF·DOCX 업로드 테스트와 전체 verify를 다시 돌린다(부하가 적을 때 돌려 verify 0 종료를 확인). ② **`docs/API.md`가 낡았다**(25행 "txt·md·pdf·docx … HWP 거부", 276행 예시 문구 "HWP는 PDF나 DOCX로 저장해 올려 주세요", 284행 "415 HWP·HWPX"). `docs/`는 PM 소유이므로 병합 때 "HWPX 수락, HWP 415, 응답에 `chars_no_space`·`paragraphs` 추가"로 고친다. ③ `docs/decisions.md` 44행(HWP 5.0을 읽는다)은 65행이 범위를 줄였다고 뒤에서 덮는다. 읽는 사람이 헷갈리지 않게 44행에 "(HWP 5.0은 65행에서 제외)" 한 줄을 붙이길 권한다.

## 재현 명령(요약)

```
wt=<scratchpad>/wt_l2h   # git worktree add <scratchpad>/wt_l2h 0220be3
cd $wt; PYTHONPATH="src;." NEUMANN_LLM_PROVIDER=mock NEUMANN_LIVE_TESTS=0 python scripts/verify.py
python <scratchpad>/probe1.py    # A~F 85건
python <scratchpad>/probe2.py out.json    # G, HEAD와 main에서 각각 실행해 diff
python <scratchpad>/probe3.py 500 20261001   # H
python <scratchpad>/probe4.py <case>     # 최악 입력 시간·메모리
python tests/e4/test_webui_upload_ui.py --port 8193 --out <scratchpad>/uishots   # I
git merge-tree --write-tree --name-only 0220be3 f54ef1d   # J (종료 1, upload.py)
git merge-tree --write-tree --name-only 0220be3 main      # J (종료 0)
```

프로브 로그: `probe1.log`(85건 전부 OK)·`probe3.log`·`probe4` 출력은 scratchpad에 있고 저장소에는 넣지 않는다.
