# E4-L2f 보고서 — 화면 "IV 내보내기" 켜기 (+ 검증 보완 F1~F7)

빌더: claude-opus-5.5 · 브랜치 `task/E4-L2f` · 모든 실행 `NEUMANN_LLM_PROVIDER=mock`(OpenAI 호출 0), 서버 8149만 사용.
main 병합: E4-L2d(2bd2b58·03503d6), SEC-4(5ed9b45), 최신 29d96ee까지.

## 무엇을 했나

### 1. 화면(index.html, 내보내기 부분)

- 단계 IV "내보내기"와 리포트 섹션 VI "ZIP 내려받기"를 켰다.
- 버튼은 `{result, result_sig, decisions}`를 `POST /premortem/package`로 보내 ZIP을 받는다. 재분석은 하지 않는다.
- 결과 없음·샘플·오류·원결과 없음이면 단계와 버튼을 끄고 사유를 보인다.
- 서버 문구(`message` → `detail` → `reason`)는 `textContent`로 넣는다.
- 내려받은 뒤 응답 헤더 `X-Neumann-Result-Origin`에 따라 "서버 서명 확인됨"이나 "서버 서명 확인 안 됨(서버 재기동 등) · ZIP에 경고가 적힘"을 보인다.
- **결정(PM 결정 ③ 반영):** 채택·보류·기각 세 상태를 `{item_id, decision, note?, decided_at?}`로 보낸다.
  - 결과에 원래 실린 결정은 그대로 싣는다.
  - 화면에서 누른 항목은 누른 시각과 함께 싣는다. 한 바퀴 돌려 "보류"로 되돌린 항목도 `hold`와 시각으로 기록한다.
  - 한 번도 건드리지 않은 항목(기본값 보류)은 싣지 않는다.

### 2. 원결과 전달(view.py, 정정 지시 2)

- `build_ui_view`가 `result`(원결과), `result_sig`(서버 서명), `_status.export`(`result`·`signed`·`reason`·`dropped_keys`)를 붙인다.
- `/premortem/view`와 jobs 화면 결과(`jobs._present` → `build_ui_view`)가 같은 경로라 둘 다 이 필드를 갖는다. `jobs.py`는 고치지 않았다.

### 3. F1 결과 출처 서명(`src/neumann/api/signing.py` 새 파일, export.py)

- **서명:** HMAC-SHA256(키, `"neumann-result-v1\n"` + 정규화 JSON). 형식은 `v1.<64hex>`.
- **정규화:** `PremortemResult`로 검증한 계약 필드를 JSON으로 되돌린다. 정수로 떨어지는 실수는 정수로 바꾼다(브라우저 JSON 왕복 대비). 키는 정렬하고 압축 JSON으로 쓴다.
- **키:** 환경변수 `NEUMANN_RESULT_HMAC_KEY`. 없으면 모듈을 처음 읽을 때(서버 기동) 무작위 32바이트를 만든다. 재기동하면 옛 서명은 무효이고, 그 결과는 "unverified"로 나간다(PM 결정 ④: 정직한 표시).
- **비노출:** 키 값과 키 설정 여부는 응답·ZIP·로그·/health 어디에도 없다(테스트). `.env.example`에는 이름만 넣었다.
- **서명 확인(`/premortem/package`):** 확인되면 `result_origin: "server_signed"`, 아니면 `"client_submitted_unverified"`. 이 값은 manifest·evidence_pack·README·리포트·ai_context와 응답 헤더에 실린다.
  - 파이썬에서 `build_package`를 직접 부르면 `"in_process"`다. 호출한 코드가 가진 결과이고 API를 거치지 않는다. 기존 E4-L2a 테스트와 동작은 그대로다.
- **미확인일 때:**
  - README·neumann_report·ai_context **첫 줄**에 경고를 넣는다: "**주의: 서버가 분석·서명한 결과가 아님.** …"
  - "제품 LLM이 만든 카드", "원문을 오프셋으로 잘라" 같은 서버 보증 문구를 빼고 "결과에 generator=astra로 적힌 카드. 서버 서명이 없어 … 확인하지 못했다"로 쓴다.
  - evidence_pack의 대조 안내도 "서버 서명이 없는 결과다"로 바꾼다.
- **jobs 가림과의 관계:** jobs 응답은 뷰 전체에 `serving.scrub_ok_payload`(진단 칸 키·경로 가림)를 한 번 더 건다. 그래서 서명 전에 같은 규칙을 원결과에 먼저 적용한다. 두 번째 가림은 값을 바꾸지 않고 서명이 맞는다(테스트).

### 4. 권고 반영

- **F2:** 첫 판 문구 "계약 밖 값은 실리지 않는다"는 틀렸다. extra=forbid는 최상위 필드만 막고, 자유형 dict 칸(manifest·checklist 항목·expected_review·plan_checks 등)은 검증을 통과한다. 정정한 내용:
  - docstring과 이 보고서를 고쳤다.
  - manifest(pipeline·precomputed 키 + view가 읽는 모델 키)와 checklist 항목(E3 checklist.py 키 + 별칭)은 **화이트리스트**로 남긴다. 뺀 키 이름은 `_status.export.dropped_keys`에 적는다.
  - 그 밖의 자유형 칸(expected_review·plan_checks 등)은 결과 값 그대로다.
- **F4:**
  - CSV 문자열 칸(work_id·title·venue·url·cited_by)이 `= + - @`·탭·CR로 시작하면 앞에 `'`를 붙인다.
  - 마크다운 4종에 옮기는 결과 문자열의 `& < >`는 HTML 엔티티로 바꾼다. 렌더하면 같은 글자다. 글자 그대로의 인용은 `evidence_pack.json`에 있다.
  - 코드 스팬 안 id의 백틱은 뺀다. http(s)가 아닌 URL은 자동 링크로 만들지 않는다.
  - 리포트의 expected_review JSON과 ai_context 인용 JSON은 `< > &`를 `\u` 이스케이프한다. 디코드하면 원문 그대로다(테스트).
- **F6:** 서빙 413 문구를 내보내기에만 따로 뒀다: `내보낼 결과가 너무 큽니다(최대 4MB).`
- **F7:** Playwright 가로채기를 jobs 폴링(`**/premortem/jobs/**`)으로 바꿨고, `route.fetch(timeout=180_000)`을 준다.

### 5. 첫 Playwright 실패(연속 클릭)

- 원인은 테스트의 경쟁 조건이었다(실제 버그 아님). 디버그로 클릭마다 반영되는 것을 확인했다.
- 집계는 다음 틱에 다시 그린다. 그래서 중간 상태("결정 3건")에서 대기가 먼저 풀렸다.
- 최종 값("결정 4건 · 채택 2 · 보류 1 · 기각 1")을 기다리도록 바꿨다.

## 완료 기준별 측정

| 기준 | 명령 | 결과 |
|---|---|---|
| 서명·출처·이스케이프·413 | `NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4/test_export_ui_sign.py tests/e4/test_export_ui.py tests/e4/test_export.py -q` | `57 passed, 1 skipped` |
| 서명 경우별 | 같은 명령 | 정상(브라우저 왕복 포함) → `server_signed`, README 첫 줄 제목 · 변조 5종(generator를 astra로, why 문구, 카드 제목, 점수, session_id) → `client_submitted_unverified`, 첫 줄 경고·서버 문구 없음 · 인용 문구·plan_id 변조는 계약 검증이 422 · 서명 없음·빈 값·형식 오류·다른 버전·가짜 hex → unverified · 재기동(무작위 키) → unverified · 설정 키 재기동 → 유지, 키 교체 → 무효 · 키 값·키 이름·"hmac"이 뷰·ZIP·헤더·로그·/health에 없음 |
| Playwright 1440×900, jobs 경로, 8149, mock, 끝나면 종료 | `NEUMANN_UI_TESTS=1 NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4/test_export_ui.py -q -s -k playwright` | `1 passed in 77.53s`. POST `["/premortem/jobs", "/premortem/package"]`(재분석 0), 뒤이어 `8149 not listening` |
| ZIP 9파일·decision_log | 같은 Playwright | 9파일 `FILE_NAMES` 순서 그대로, `manifest.result_origin == "server_signed"`, `counts.decisions == 4`, 결정은 아래 표 |
| 비활성·오류 문구 | 같은 Playwright | 결과 없음·샘플·원결과 없음이면 비활성과 사유. 422 `detail`의 `<img onerror>`는 글자로 보임(요소 0), 429 `message`도 그대로 |
| verify | `NEUMANN_LLM_PROVIDER=mock python scripts/verify.py` (main 29d96ee 병합 뒤) | `1383 passed, 27 skipped` · `verify 통과` |

decision_log.json의 `decisions`(Playwright, plan.md, mock, jobs 경로):

| item_id | decision | note | decided_at |
|---|---|---|---|
| C1 | adopt | `표본 크기 근거 보강 · 담당 [EMAIL]`(뷰에 실린 결정·메모, 이메일은 `DecisionEntry`가 가림) | null |
| C2 | reject | null | 클릭 시각 |
| C3 | adopt | null | 클릭 시각 |
| C4 | hold | null | 클릭 시각(한 바퀴 돌려 보류로 되돌림) |

스크린샷: `docs/reports/E4-L2f_export.png`(1440×900, 내려받은 뒤 "서버 서명 확인됨").

## 바꾼 파일

- `src/neumann/webui/index.html`: 단계 IV, `renderReport` 반환 줄(`expHtml()`), E4-L2f 블록(`exp*`), CSS 한 묶음.
- `src/neumann/api/view.py`: `export_result`(화이트리스트·진단 가림), `_attach_result`(result·result_sig·_status.export).
- `src/neumann/api/signing.py`(새 파일): 서명·확인·키.
- `src/neumann/api/export.py`(검증 지시로 범위 넓힘): `result_origin`, 미확인 문구, F4 이스케이프, `PackageRequest.result_sig`, 응답 헤더.
- `src/neumann/api/serving.py`: 내보내기 413 문구(F6).
- `.env.example`: `NEUMANN_RESULT_HMAC_KEY=`(이름만).
- 테스트:
  - `tests/e4/test_export_ui.py`: 정적·서버 검사 + Playwright.
  - `tests/e4/test_export_ui_sign.py`(새 파일): 서명·화이트리스트·이스케이프·413.
  - `tests/e4/test_export.py`: 0장 사유 단언을 `&lt;`로 한 줄 고침.
- `docs/reports/E4-L2f.md`, `docs/reports/E4-L2f_export.png`.
- `main.py`·`jobs.py`·계약(`contracts/`, `models.py`)은 고치지 않았다.

## 결정

- 결과 출처 값은 셋이다. API는 `server_signed`·`client_submitted_unverified` 둘만 낸다. `in_process`는 파이썬 직접 호출 전용이다.
- 서명 범위는 화면 뷰 경로(`/premortem/view`, jobs `format: "view"`)다. 다음은 서명하지 않는다: jobs `format: "result"`, `/premortem` 원결과 응답, `/premortem/precomputed` 사전 계산본. 이것들을 그대로 내보내면 unverified로 표시된다.
- 서명을 만들지 못하면 원결과도 싣지 않는다. 서명 없는 원결과를 서버가 내지 않게 하려는 것이다.
- 화이트리스트에 없는 새 manifest·checklist 키는 빠진다(안전한 쪽). E3가 키를 늘리면 `MANIFEST_EXPORT_KEYS`·`CHECKLIST_EXPORT_KEYS`에 더해야 화면·ZIP에 실린다.

## 못 한 것 · 제안

- 메모 편집 UI가 없다(체크리스트 부분은 이 과제 소유가 아님). 결과에 실린 메모만 보낸다.
- 화면 응답이 커진다(plan.md 기준 원결과 약 44KB 추가). 커지면 서버 보관 결과 id로 바꾸는 것을 제안한다.
- 공개 서버 여러 대나 재기동에도 서명을 유지하려면 `NEUMANN_RESULT_HMAC_KEY`를 실서비스 기동 환경에만 설정한다(PM).
- jobs `format: "result"`·사전 계산본에도 서명이 필요하면 `jobs._present`·`precomputed`에서 `sign_result`를 부르면 된다(E4 다음 과제).
