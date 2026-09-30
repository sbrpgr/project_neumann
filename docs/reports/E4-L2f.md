# E4-L2f 보고서 — 화면 "IV 내보내기" 켜기 (+ 검증 보완 F1~F7, DISP-1 병합, 서명 재검증 R1~R4·M10)

## Codex 인계 보완 — 2026-10-01 00:09 KST

- 역할: builder. actual model: `gpt-6.1-sol`(최신 PM 배정 지시), 커밋 표기 `builder: codex-gpt-6.1-sol`. 독립 `gpt-6-sol` 검증은 아직 받지 않았다.
- 작업 트리: `C:/Users/User/Desktop/project_neumann/.claude/worktrees/s2-E4-L2f`, 브랜치 `task/E4-L2f`, 인계 HEAD `c3ff65913cfa2b7ee49b5e05319f932af4ea0e38`.
- 기존 미커밋 보고서·스크린샷·PM generic 서명 추가분을 보존했다. 이 보고서 아래 Claude 측정은 이전 세션 기록이다. 이번 최종 커밋 해시는 최종 인계 결과에 적는다.
- 모든 실행은 별도 Python 프로세스에서 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_TESTS=0`, `NEUMANN_LIVE_LLM_OK` 제거, `OPENAI_API_KEY` 제거(복원 없음), 모델·HF 다운로드 offline 설정. pytest의 공통 conftest가 live 허용 값을 `0`으로 닫는다. 실제 OpenAI API 호출 0. 제품 데이터에 Codex 생성물을 쓰지 않았다.
- 계획서·공유 결과는 읽기만 했다. 공통 문서·계약·models/config·다른 worktree·실서비스 포트(8010/8020/8099)는 수정·호출하지 않았다. 전체 `scripts/verify.py`는 PM 큐에 남겼다.

### 이번 변경

1. PM이 추가한 `sign_payload(kind, data)` / `verify_payload(kind, data, sig)` 이름과 인자 순서를 유지했다. 키·형식은 기존 결과 서명과 같고 도메인은 `neumann-{kind}-v1\n`으로 분리한다. `result` 도메인은 generic 서명에서 금지한다.
2. generic 서명에서 중첩 객체의 키도 문자열만 허용한다. 기존 구현은 `{1: "내용"}`과 `{"1": "내용"}`을 같은 값으로 인증했다. 최상위·중첩 객체·목록 속 객체 3건을 먼저 실패시킨 뒤 고쳤다. 기존 `sign_result` 정규화 정책은 유지했다.
3. generic 검사에 정상 브라우저 JSON 왕복, 값 변조, 유효한 PremortemResult와 양방향 교차 서명 거부, 고정 합성 테스트 키의 HMAC 계산, 키 교체, bool/null/목록 순서 차이, 순환 payload 거부를 보강했다. 합성 테스트 키는 실제 비밀값이 아니다.
4. 브라우저 검사에서 실제 `/premortem/package`에 비ASCII 서명을 보내 화면·ZIP의 미확인 표시를 확인한다. 시험 서버는 8149만 사용하고 live tests를 명시적으로 0으로 준다. 시험 도우미의 금지 포트에 8099를 추가했다.
5. 검사기의 `--out`이 저장소 밖 허용 경로도 받도록 경로 표기를 고쳤다. 기존 `docs/reports/E4-L2f_export.png`는 덮어쓰지 않았고, 새 검사의 이미지는 `out/codex/e4-l2f-ui-4730405add3048b0b8d5f7cd32b17b5e/E4-L2f_export.png`에 남겼다. 기존·새 이미지에서 내보내기 표시를 육안 확인했다.

### 이번 완료 기준별 실측

Python은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`다. 아래 pytest는 `python -c` 안에서 위 mock 환경을 먼저 설정하고 `pytest.main([...])`으로 실행했다. 캐시는 `-p no:cacheprovider`, tmp fixture는 쓰기 가능한 `out/codex/e4-l2f-tests-<uuid>`를 `--basetemp`로 지정했다.

| 기준 | 실행한 대상·명령 | 실제 출력·결과 |
|---|---|---|
| 인계 상태 확인 | `pytest.main(["tests/e4/test_payload_signing.py", "tests/e4/test_export_ui_sign.py", "-q", "-rs"])` | `53 passed, 1 warning in 1.42s`. 기존 pytest cache 쓰기 권한 경고, 다음 실행부터 캐시 비활성화 |
| generic 키 충돌 반증 | `tests/e4/test_payload_signing.py -q -p no:cacheprovider`(수정 전) | `3 failed, 25 passed in 0.23s`. 정수 키를 문자열 키와 같은 값으로 인증한 3건 |
| 최종 대상 회귀 | `tests/e4/test_payload_signing.py tests/e4/test_export_ui_sign.py tests/e4/test_webui_gen_labels.py tests/e4/test_display_generator.py tests/e4/test_export_ui.py tests/e4/test_export.py tests/e4/test_e4_view.py tests/e4/test_view_panel.py -q -rs -p no:cacheprovider --basetemp <새 전용경로>` | `146 passed, 2 skipped in 1.59s`. generic 28건 포함. skip은 별도 화면 샷·브라우저 opt-in이며 내보내기 브라우저는 아래에서 직접 실행 |
| R1~R4·M10 개별 재측정 | `tests/e4/test_export_ui_sign.py -k "r1 or r2 or r3 or r4 or m10" -v -p no:cacheprovider` | `12 passed, 24 deselected in 0.57s`. R1 7종 모두 200·unverified, R2 짧은 키·재기동, R3 화이트리스트 2건, R4 이미지·링크·단계 이름, M10 정수/실수 정규화 |
| R3 실제 결과 손실 | 기존 `_real_results()` 파일을 계약 검증하고 `test_r3_real_results_lose_no_keys_and_package_unchanged()` 직접 실행 | `R3 valid_results=29 non_result_files=0 dropped_keys=0 package_bytes_unchanged=True` |
| 서명·출처·세션·재기동 | 최종 대상 회귀의 `test_export_ui_sign.py` | 정상·브라우저 왕복·jobs 가림 후 확인됨. generator·문구·제목·점수·session_id 변조는 미확인. 인용/plan_id 계약 위반은 422. 무작위 키 재기동·키 교체는 무효, 설정 키 재기동은 유지. ZIP 경고·헤더·키 비노출 검사 통과 |
| 브라우저 1440×900·8149·mock | `python tests/e4/test_export_ui.py --port 8149 --out C:/Users/User/Desktop/project_neumann/out/codex/e4-l2f-ui-4730405add3048b0b8d5f7cd32b17b5e`(동일 안전 프로세스 래퍼, TEMP/TMP도 전용 경로) | exit 0. 정상 POST `["/premortem/jobs", "/premortem/package"]`, `result_origin=server_signed`, ZIP 9파일, 결정 4건(채택 2·보류 1·기각 1). 비ASCII 서명으로 두 번째 package만 호출: `client_submitted_unverified`·README 첫 줄 경고·화면 `서버 서명 확인 안 됨(서버 재기동 등) · ZIP에 경고가 적힘`. 샘플·원결과 없음 비활성, 422 XSS·429 문구 검사 통과 |
| 시험 서버 종료 | socket으로 8149만 확인 | `8149_listening=False`. 두 UI 시도 모두 자신이 띄운 서버를 finally에서 종료 |
| diff 형식 | `git diff --check` | exit 0, 출력 없음 |

실행 중 문제를 숨기지 않는다: 첫 확대 pytest는 시스템 TEMP 접근 거부로 `145 passed, 2 skipped, 1 error`였다. 검사나 기대값을 낮추지 않고 전용 `--basetemp`로 다시 실행해 통과했다. 첫 브라우저는 정상 다운로드 뒤 외부 `--out`의 `relative_to(ROOT)`가 ValueError를 내어 exit 1이었다. 시험 서버 종료를 확인한 뒤 경로 처리만 수정하고 전체 브라우저 시나리오를 재실행해 exit 0을 받았다.

첫 파일 지정 `git add`도 worktree 공용 Git index의 `index.lock` 생성 권한으로 막혔다. 승인된 과제 파일 5개만 같은 명령의 권한 확장으로 다시 지정해 스테이징했다. 훅을 우회하지 않는다.

### E3-L2r 서명 API 인계

```python
from neumann.api.signing import sign_payload, verify_payload

# 서버가 검증·생성한 JSON 객체에만 서명한다.
signature = sign_payload("revision", validated_payload)
ok = verify_payload("revision", returned_payload, signature)
```

`kind`: `[a-z][a-z0-9-]{0,31}`, `result` 제외. payload는 중첩 키가 모두 문자열인 Mapping이며 JSON 값만 사용한다. 반환 서명은 `v1.<소문자 hex 64자>`. 검증할 때 같은 kind와 payload 전체를 넘긴다. 변조·다른 kind·잘못된 서명·비JSON 값·순환 참조는 False다. 스키마·출처 권한은 호출자가 먼저 검사해야 한다. 여러 서버/재기동 간 유지가 필요하면 기존 `NEUMANN_RESULT_HMAC_KEY` 운영 정책을 따른다. L2r/L1e worktree는 변경하지 않았다.

### 못 한 것·다음(PM 인계 5줄)

1. 최신 전체 `scripts/verify.py`는 미실행이며 PM 검증 큐에서 실행한다.
2. 독립 `gpt-6-sol` 검증 및 판정은 PM이 배정한다. 기존 verify 보고서는 수정하지 않았다.
3. E3-L2r에서 위 generic API를 연결하고, 스키마/출처를 검증한 출력에만 서명한다.
4. main 병합·push·tag 및 공통 HANDOFF/QUEUE/decisions 갱신은 PM이 한다.
5. 실서비스·실제 OpenAI 확인은 수행하지 않았다. 기존 보고서·스크린샷과 새 검증 산출물 위치를 보존해 인계한다.

## 이전 Claude 구축 기록

빌더: claude-opus-5.5 · 브랜치 `task/E4-L2f` · 모든 실행 `NEUMANN_LLM_PROVIDER=mock`(OpenAI 호출 0), 서버 8149만 사용.
main 병합: E4-L2d(2bd2b58·03503d6), SEC-4(5ed9b45), DISP-1(4753b3d), 최신 4152c58(SEC-6)까지.

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
  - "제품 LLM이 만든 카드", "원문을 오프셋으로 잘라" 같은 서버 보증 문구를 뺀다. 생성 방식은 "LLM(결과에 적힌 표기, 미확인)"처럼 표기만 옮기고(모델명 없음), 설명은 "결과에 적힌 생성 방식 표기일 뿐이다. 서버 서명이 없어 … 확인하지 못했다"로 쓴다(DISP-1 병합 뒤, "generator=astra" 인용 삭제).
  - README·ai_context의 JSON 설명 줄도 미확인 결과에서는 중립 문구("JSON 값 `generator`·`model`은 요청자가 보낸 결과에 적힌 표기다…")로 바꾼다.
  - evidence_pack의 대조 안내도 "서버 서명이 없는 결과다"로 바꾼다.
- **jobs 가림과의 관계:** jobs 응답은 뷰 전체에 `serving.scrub_ok_payload`(진단 칸 키·경로 가림)를 한 번 더 건다. 그래서 서명 전에 같은 규칙을 원결과에 먼저 적용한다. 두 번째 가림은 값을 바꾸지 않고 서명이 맞는다(테스트).

### 4. 권고 반영

- **F2:** 첫 판 문구 "계약 밖 값은 실리지 않는다"는 틀렸다. extra=forbid는 최상위 필드만 막고, 자유형 dict 칸(manifest·checklist 항목·expected_review·plan_checks 등)은 검증을 통과한다. 정정한 내용:
  - docstring과 이 보고서를 고쳤다.
  - 자유형 칸 전부를 **화이트리스트**로 거른다(R3로 넓힘): manifest·checklist·expected_review·plan_stats·plan_checks·verification·risk_synthesis·field_prior·research_questions·post_status·plan_side_candidates.
    - 기준: 실제 결과 29건(사전 계산본 3·백테스트 실행 26)과 mock 실행에서 모은 키, 각 칸을 쓰는 코드(E3·retraction), `PostStatus` 필드, view가 읽는 별칭.
    - 걸러지는 것은 한 단계(최상위 키, 목록이면 항목 키)다. 그 아래 값은 결과 그대로다.
    - 채우는 코드가 없는 research_questions·plan_side_candidates는 오는 키를 모두 뺀다.
  - 뺀 키 이름(값 아님)은 `_status.export.dropped_keys`에 적는다.
  - 실제 결과 29건은 빠지는 키가 0이고, 패키지 출력(생성 시각 고정)이 바이트 단위로 같다(`test_r3_real_results_lose_no_keys_and_package_unchanged`).
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

### 6. DISP-1 병합(main 4753b3d)

- `export.py` 충돌 8곳을 풀었다. 서명 구조(`_gen_short`·`_gen_desc`·`_gen_label(c, card)`)는 유지하고, 표시 문자열만 `display_generator`로 바꿨다.
  - 서명 확인·직접 호출: "LLM (모델명)"·"비상 규칙"·"모의(mock)".
  - 미확인: "LLM(결과에 적힌 표기, 미확인)"·"비상 규칙(결과에 적힌 표기, 미확인)"·"모의(mock, 결과에 적힌 표기, 미확인)".
- 나머지는 자동 병합됐다: 체크리스트 줄 생성 표시, 예상 심사평 머리 "생성: …"(미확인이면 표기만), ai_context 카드 줄 "생성: …".
- `index.html`은 자동 병합됐고, 스타일 끝은 L2f 내보내기 블록이 마지막 그대로다(DISP-1 추가 CSS 없음).
- **사람용 문서의 astra:** 서명 확인·미확인 모두 README·리포트·계획서 주석·ai_context에서 0건이다(`_assert_no_astra`).
  - 제외: DISP-1이 정한 예외인 JSON 설명 줄(서명 확인 결과만)과 결과 값을 그대로 옮긴 ```json 코드 블록.
  - 내보내기 화면 문구에도 astra가 없다.

### 7. 서명 재검증 R1~R4·M10

- **R1:** 서명 문자열은 먼저 ASCII·길이 67·`v1.`+소문자 hex 64자(정규식, re.ASCII)인지 보고, 비교는 `hmac.compare_digest(bytes, bytes)`로 한다.
  - 비ASCII(`é`)·전각 숫자·전각 접두·대문자 hex·공백·줄바꿈 꼬리·길이 초과 7종은 500이 아니라 200 + `client_submitted_unverified`다(회귀 테스트).
- **R2:** 키가 16바이트 미만이면 쓰지 않고 무작위 키로 바꾸고, 경고 로그 한 줄을 남긴다(키 값·길이 없음). 테스트는 로그에 키가 없는지, 같은 짧은 키로 재기동하면 옛 서명이 무효인지 본다. `.env.example` 주석은 "32자 이상 무작위 값 또는 비움"이다.
- **R3:** 위 F2 항목.
- **R4:** `_md_escape`가 HTML 엔티티에 더해 링크·이미지 문법을 무력화한다.
  - 백슬래시를 두 배로 하고 대괄호 앞에 백슬래시를 붙인다. 그래서 `![…](…)`·`[…](…)`·참조 정의가 렌더되지 않고, 원격 이미지를 불러올 수 없다.
  - ai_context·README의 단계 이름과 경고 속 카드 id도 이스케이프한다.
  - 테스트는 마크다운 4종에 "이스케이프되지 않은 `![`·`](`"가 없는지 백슬래시 개수(홀짝)로 확인한다.
- **M10:** 기존 테스트는 계약 모델이 실수 칸을 float로 되돌려서 정규화가 빠져도 통과했다. 그래서 자유형 칸(manifest `total_s: 12.0`)으로 다시 잰다.
  - 브라우저 왕복 뒤 12(int)여도 서명이 맞아야 한다. 정규화를 빼면 이 테스트가 실패한다.
  - 정수가 아닌 값(1.25 → 1.26)은 구별한다.
  - 2^53 이상은 정수로 바꾸지 않는다.

## 완료 기준별 측정

| 기준 | 명령 | 결과 |
|---|---|---|
| 서명·출처·이스케이프·413·R1~R4·M10 + DISP-1 | `NEUMANN_LLM_PROVIDER=mock python -W error::SyntaxWarning -m pytest tests/e4/test_export_ui_sign.py tests/e4/test_webui_gen_labels.py tests/e4/test_display_generator.py tests/e4/test_export_ui.py tests/e4/test_export.py tests/e3/test_checklist.py -q` | `109 passed, 2 skipped` (R 테스트 11건은 건너뜀 없이 실행: `-rs -v`로 확인) |
| 서명 경우별 | 같은 명령 | 정상(브라우저 왕복 포함) → `server_signed`, README 첫 줄 제목 · 변조 5종(generator를 astra로, why 문구, 카드 제목, 점수, session_id) → `client_submitted_unverified`, 첫 줄 경고·서버 문구 없음 · 인용 문구·plan_id 변조는 계약 검증이 422 · 서명 없음·빈 값·형식 오류·다른 버전·가짜 hex → unverified · 재기동(무작위 키) → unverified · 설정 키 재기동 → 유지, 키 교체 → 무효 · 키 값·키 이름·"hmac"이 뷰·ZIP·헤더·로그·/health에 없음 |
| Playwright 1440×900, jobs 경로, 8149, mock, 끝나면 종료 | `NEUMANN_UI_TESTS=1 NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4/test_export_ui.py -q -s -k playwright` | `1 passed in 160.30s`(4152c58 병합 뒤, 부하 중). POST `["/premortem/jobs", "/premortem/package"]`(재분석 0), 뒤이어 `8149 not listening` |
| ZIP 9파일·decision_log | 같은 Playwright | 9파일 `FILE_NAMES` 순서 그대로, `manifest.result_origin == "server_signed"`, `counts.decisions == 4`, 결정은 아래 표 |
| 비활성·오류 문구 | 같은 Playwright | 결과 없음·샘플·원결과 없음이면 비활성과 사유. 422 `detail`의 `<img onerror>`는 글자로 보임(요소 0), 429 `message`도 그대로 |
| 최신 전체 verify | `python scripts/verify.py` | 이번 Codex 세션은 PM 지시로 미실행. PM 큐에서 측정 필요 |

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
