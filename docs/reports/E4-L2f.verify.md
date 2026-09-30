# E4-L2f 검증 보고서 (독립 검증자: Claude Sonnet 5.5)

VERDICT: PASS-조건부 (재검증 d332e78 기준. 1차 552e9de도 PASS-조건부)

## 재검증 (HEAD d332e78, main 29d96ee 병합 포함) — F1 서버 서명 중심

환경: 모든 명령 mock, `NEUMANN_LIVE_*` 해제, `.env` 미열람, worktree `git status` 0줄(코드·git 쓰기 없음). 시험은 scratchpad `v_l2f/r2/`의 `git clone`(`l2f2` = d332e78 그대로). 시험 서버 8149·8188, 끝나면 종료. 시험에 쓴 키는 시험용 값(`VERIFIER-TEST-KEY-…`)뿐.

| 항목 | 명령·측정 | 결과 |
|---|---|---|
| verify | worktree `scripts/verify.py` | `1383 passed, 27 skipped in 217.68s`, `보안: 파일 445개`, `verify 통과` |
| verify --security | 〃 | 통과 |
| L2f 테스트·Playwright | `NEUMANN_UI_TESTS=1 pytest tests/e4/test_export_ui.py tests/e4/test_export_ui_sign.py` (l2f2) | `32 passed in 71.40s`(jobs 경로 POST `jobs`·`package`, `route.fetch` 180초). F7 조치 확인 |
| 소유 밖 변경 | `git diff main...HEAD --stat` | `serving.py` +3줄(413 문구 분기만), `.env.example` +4줄(`NEUMANN_RESULT_HMAC_KEY=` 값 비움). 계약·`models.py` 변경 0 |
| 서명 변조 시험 | `sig_adv1.py`(실제 `/premortem/view` 결과, 서빙 미들웨어 통과) | 정상 서명 → `server_signed`(헤더·manifest 일치, README에 경고 없음). 카드 제목·generator(mock→astra)·점수·알림·상태·계획서 줄·카드 삭제·manifest·근거 text(sha 맞춤)·유사연구 제목·공백·제로폭 문자·NFD 정규화·시각 오프셋 14종 모두 `client_submitted_unverified` + README/리포트/ai_context 첫 줄 경고 |
| 정규화 우회 | 〃 | 키 순서 뒤집기·들여쓰기 JSON: 같은 내용이라 서명 유지(정상). 자유형 dict의 정수↔실수 22곳: 서명 유지(값이 같아 설계 의도, 표기만 다름). `1`→`true`, 2^53+1 정수 추가: 깨짐. 중복 키: 파서가 마지막 값을 쓰고 서명·렌더가 같은 dict를 쓰므로 원본이 마지막이면 signed, 다른 값이 마지막이면 unverified. `result` 두 번(원본 뒤 위조): unverified. `result_sig` 중복도 마지막 값 기준 |
| 서명 재사용 | 〃 | 다른 계획서 결과·fixture·같은 계획서 재분석 결과에 옛 서명: 모두 unverified. `reset_key()`(재기동): 옛 서명 unverified |
| 키 누출·설정 여부 | `sig_adv2.py`, 키 설정/미설정 두 번(응답 본문·헤더·ZIP 9파일·`/health`·`/openapi.json`·`/docs`·jobs·422·413·500 경로·로그·stdout/stderr 전부 검색) | 키 값·`NEUMANN_RESULT_HMAC_KEY`·`hmac` 언급 0건. 설정/미설정 응답 구조(`/health`, `_status.export`, 뷰 최상위 키, 패키지 상태·헤더) 전부 동일 |
| jobs·진단 가림 뒤 서명 | `sig_adv3.py`(경로·키·트레이스를 심은 결과) | `/premortem/view`·jobs 둘 다 `server_signed`, jobs 결과의 `notices`·`stages`가 뷰와 동일(가림이 멱등), 경로→`[경로]`·키→`[가림]`·트레이스→종류만. ZIP에 경로·키 0건. 서빙 캐시 적중(`NEUMANN_PUBLIC=1`, 임시 데이터 폴더) 3회·jobs 2회 모두 `server_signed` |
| 서명 없는 결과 | 〃 | jobs `format=result`, raw `POST /premortem`(감싼 것·감싸지 않은 것), precomputed 항목, 서명 붙은 뷰 서명을 scrub 전 raw 결과에 붙인 경우: 모두 `client_submitted_unverified` + 경고. `result_origin` 주입(server_signed·in_process)은 422(extra=forbid), `in_process`는 API로 못 감(직접 호출 전용, 다른 호출자 없음) |
| 화면 표시 | `ui_sig.py`(Playwright) | 정상: "서버 서명 확인됨". 결과 조작·서명 없음: 다운로드는 되고 "서버 서명 확인 안 됨(서버 재기동 등) · ZIP에 경고가 적힘"이 오류 색으로 표시, ZIP README 첫 줄 경고, manifest `client_submitted_unverified` |
| F2 화이트리스트 | `sig_adv3.py` | `manifest`·`checklist[]`의 모르는 키(`data_dir`, `env`, `reviewer_name`, `contact`, `email`, `path` 등)가 제거되고 `_status.export.dropped_keys`에 키 이름만 나옴(값 없음). 진짜 mock 결과는 `dropped_keys: []`(정상 키 손실 없음) |
| F4 서식 | `f4_adv.py` | 마크다운의 HTML 이스케이프 1회(`&amp;amp;`는 원문 `&amp;`를 한 번 이스케이프한 것이라 정상). 리포트 JSON 블록 왕복 동일, ai_context 인용 8/8 왕복 동일, `evidence_pack.json`·`risk_cards.json` 원문 그대로. CSV `= + - @ TAB CR` 시작 칸 0건(앞에 `'`) |
| F6 | `f6.py` | 내보내기 413: "내보낼 결과가 너무 큽니다(최대 4MB)." 분석 경로 413은 옛 문구 유지 |
| F5 | `ui_adv2` 재확인은 안 함, 빌더 테스트 `되돌린 보류=hold` 통과 | 결정한 보류는 `hold`로 기록(연구자가 안 건드린 기본값만 제외). 의도한 설계로 명시됨 |
| 변이 시험 | 사본 M7~M11 | M7(verify 항상 True)·M9(서명 전 가림 제거)·M11(origin 항상 signed)은 테스트가 잡음. M8(`compare_digest`→`==`)·M10(정수 실수 정규화 제거)은 통과함 — M8은 동작 동치, M10은 오프라인 테스트가 못 잡고 실제 브라우저 왕복에서만 드러남(낮음) |

### 재검증 발견

| # | 심각도 | 내용 | 재현 |
|---|---|---|---|
| R1 | **중간(병합 전 필수)** | **비ASCII 서명(64자 이상)이 500을 낸다.** `verify_result`가 `hmac.compare_digest(expected, mac)`에 문자열을 넘기는데 `mac`에 비ASCII 글자가 있으면 `TypeError`(try 밖). 실패-닫힘(ZIP 안 만들어짐)이지만 "형식 오류 서명 → unverified" 계약을 어기고 500·오류 카운터·서버 경고 로그를 유발한다 | `POST /premortem/package {"result": <정상>, "result_sig": "v1." + "é"*64}` → 500(`internal`, `kind=TypeError`). 전각 숫자 64자도 동일. 화면에서는 "처리 중 문제가 생겼습니다…". 고침: `mac.isascii()` 확인하거나 양쪽을 `.encode()` 바이트로 비교 |
| R2 | 낮음 | 서명 키 최소 길이 검사가 없다. `NEUMANN_RESULT_HMAC_KEY=1234`도 받아들이고, 화면 응답 하나(결과+서명)로 키를 0.01초에 오프라인 복원할 수 있다 → 그 키면 임의 결과에 서명 위조 가능 | `sig_adv3.py` 끝부분. 고침: 16바이트 미만이면 기동 때 무시하고 무작위 키 + 경고(값은 로그에 쓰지 않음), `.env.example`에 "32자 이상 무작위" 문구 |
| R3 | 낮음 | F2 화이트리스트는 `manifest`·`checklist[]`뿐이다. `expected_review`·`verification`·`post_status`·`plan_checks` 등 다른 자유형 칸은 그대로라, 그 칸에 심은 값은 `server_signed` 결과·ZIP(리포트의 `expected_review` 덤프)에 실린다. 진짜 결과에는 0건. 즉 서명은 "서버를 거쳤다"이지 "값이 안전하다"가 아니다 | `sig_adv3.py`: `expected_review.secret_field`·`reviewer_name` → 리포트에 실림 |
| R4 | 낮음(정보) | F4 잔여: ① ai_context의 정상이 아닌 단계 줄은 단계 이름을 이스케이프하지 않아(`_stage_line`) `<b>`가 그대로 나온다(README·리포트 표는 이스케이프됨). ② 마크다운 링크·이미지 문법(`![](http://…)`, `](javascript:…)`)은 무력화하지 않는다 — 뷰어에 따라 원격 이미지를 불러올 수 있다(심사평 원문 인용에 이미 있는 문법일 수 있음) | `f4_adv.py` 1·6번 |
| R5 | 낮음(정보) | 서명은 결과 값 기준(표기 무관)이며 `plan_text`·`decisions`는 서명 밖이다. 서버 결과는 항상 `plan`을 가지므로 `plan_text`는 쓰이지 않고, 결정은 연구자 본인 값이라 설계상 문제 없음 | — |

### 재검증 병합 전 필수 조치

1. **R1 고침**(`signing.verify_result`: 비ASCII·형식 오류 서명은 `False`). 회귀 테스트로 `"v1." + "é"*64` 넣기.
2. (강력 권고, 공개 전) R2: 키 최소 길이. 행사 서버 기동 지침에 "`NEUMANN_RESULT_HMAC_KEY`는 32자 이상 무작위(또는 비워서 재기동마다 새 키)" 명시.
3. DISP-1 병합에 따른 export.py 충돌 해결은 PM이 따로 확인(이 재검증 범위 밖). 서명 관련 줄(`result_origin`, `verify_result`)이 충돌 해결에서 남는지 병합 뒤 `tests/e4/test_export_ui_sign.py`로 확인.

### 1차 검증 발견(F1~F7) 조치 확인

| # | 1차 발견 | 조치 확인(d332e78) |
|---|---|---|
| F1 | 조작 result를 서버가 만든 것처럼 패키지화 | **조치됨**: HMAC 서명·`result_origin`·미확인 경고. 위 표대로 변조·재사용·중복 키·정규화·키 누출 시험 통과. 단 R1(500)·R2(약한 키) 남음 |
| F2 | 자유형 dict 통과 | **부분 조치**: `manifest`·`checklist[]`만 화이트리스트, 나머지 칸은 그대로(R3) |
| F3 | 본문 상한 없음 | main에 L2d가 병합됨(4MiB 상한). 1차에서 병합본 확인 |
| F4 | HTML·CSV 방어 없음 | **조치됨**(R4 잔여 정보성) |
| F5 | 보류 기록 | 설계로 명시(hold 기록, 테스트 고정) |
| F6 | 413 문구 | **조치됨** |
| F7 | Playwright 30초 | **조치됨**(jobs 경로·180초, 32 passed) |

---

## 1차 검증 (HEAD 552e9de)

- 대상: worktree `.claude/worktrees/s2-E4-L2f`, 브랜치 `task/E4-L2f`, HEAD `552e9de`(main 4cbf0f0 병합 포함). 코드·git 쓰기 없음(worktree `git status` 0줄 확인).
- 환경: 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK`·`NEUMANN_LIVE_TESTS` 해제(OpenAI 호출 0), `.env` 미열람. 시험 서버는 8149·8183·8185·8186·8187(끝나면 종료, LISTEN 0 확인), 8020·8099 미접촉.
- 임시 작업은 scratchpad `v_l2f/`의 `git clone`(원본 저장소는 읽기만): `l2f_only`(552e9de 그대로), `merge`(L2f + 현재 main c8ba766 + task/E4-L2d 74f054d + PM 패치 `E4-L2c_main.patch`→`E4-L2d_main.patch`).

## 1. 항목별 결과

| 항목 | 명령·측정 | 결과 |
|---|---|---|
| 소유 경로·계약 | `git diff main...task/E4-L2f --stat` | view.py, index.html, tests/e4/test_export_ui.py, 보고서·스크린샷만. `contracts/`·`models.py`·데이터·비밀값 파일 변경 0 |
| verify 전체 | worktree에서 `python scripts/verify.py` | `1216 passed, 28 skipped in 98.11s`, `verify 통과`(exit 0) |
| verify --security | `python scripts/verify.py --security` | `보안: 파일 409개`, `verify 통과` |
| 정적·서버 검사 | `pytest tests/e4/test_export_ui.py` | 8 passed, 1 skipped |
| Playwright(빌더 테스트) | `NEUMANN_UI_TESTS=1 pytest tests/e4/test_export_ui.py`(l2f_only) | 1회차 실패: 첫 `route.fetch()`가 30초 기본 제한을 넘김(다른 세션 서버들이 CPU를 쓰는 중 첫 분석, 총 308초, 제품 결함 아님). 2회차 `9 passed in 54.36s`. 이후 8149 LISTEN 없음 |
| 변이 시험 | 사본에서 M1~M6 | M1(result 항상 None)·M2(재분석 fetch 복원)·M3(결정 전 항목 전송)·M4(innerHTML)·M6(계약 검증 제거)은 각각 테스트 실패로 잡힘. M5는 동치 변이(검증은 그대로)라 통과 — 항상 통과하는 테스트는 아님 |
| ZIP 9파일 순서 | Playwright 내려받기 → `zipfile.namelist()` | `README.md, manifest.json, risk_cards.json, evidence_pack.json, similar_works.csv, plan_annotated.md, neumann_report.md, ai_context.md, decision_log.json` = `FILE_NAMES` 순서 |
| decision_log | 자체 Playwright(`ui_adv2.py`) | 클릭 없음: `decisions: []`, ZIP 9개 정상, 화면 "결정 0건 · 결정 전 6건은 싣지 않음". C2 기각 클릭: `{item_id:"C2", decision:"reject", decided_at:"…Z"}`. 결과에 실린 메모의 이메일은 `[EMAIL]`로 가려짐(빌더 테스트) |
| 내보내기 때 `POST /premortem` | 자체 Playwright, `page.on("request")` | 세션 전체 POST = `/premortem/view` 1건 + `/premortem/package` 1건(본문 41,156바이트). `POST /premortem` 0건. L2d 병합 화면에서는 `/premortem/jobs` + `/premortem/package`, 내보내기 클릭 뒤 요청은 package 1건 |
| 비활성 조건 | 빌더 Playwright A/B/C(2회차 통과) + 자체 시험 | 결과 없음("분석 결과 없음"), 샘플, 원결과 없음은 통과. `_status.export.reason`에 `"><img onerror>` 넣어도 `esc()`로 글자 그대로 표시, `window.__xss` null |

## 2. 보안(핵심)

### (a) `result`로 새는 값

- 진짜 mock 결과(plan.md): `view.result` 46,432바이트. 경로·드라이브·`project_neumann`·`sk-`·이메일·ORCID·`rvw_`·`NEUMANN_`·트레이스 검색 0건(모델 이름 `bge-m3` 1건뿐). `/premortem` 응답과 비교하면 시간·세션 id 13곳만 다르고 나머지 동일 — 새 노출 면이 아니다(같은 값을 `/premortem`이 원래 돌려줌).
- 적대 결과(계약은 통과하되 자유형 dict에 값을 심음, `adv_a.py`): 옛 동작(attach 끄기)과 비교하면 `manifest`·`expected_review`·`axes`·`checklist[*]` 여분 키의 경로·키·환경값·리뷰어 이름이 `view.result`에 **새로 실림**(T_ENV, T_REVIEWER). ZIP `neumann_report.md`에도 그대로 들어감(`expected_review` JSON 덤프는 이메일 가림도 안 거침). 반면 계약 밖 최상위 키(`api_key`, `_env`, `reviewer_name`, `email`)는 `result: null` + 사유로 막히고 뷰 어디에도 없음.
- 계획서 줄의 이메일·ORCID: 분석 입구에서 가려짐. 이메일 2개·ORCID 1개가 든 계획서로 `/premortem/view` → 뷰·`result`·ZIP에 원문 0건, `[EMAIL]` 표시 2건.
- 판정: 실제 파이프라인 결과에서는 유출 0. 다만 빌더의 "계약 밖 값(설정·경로·키)은 extra=forbid라 실리지 않는다"는 자유형 dict 칸에는 해당하지 않는다(F2).

### (b) 조작한 `result`로 ZIP 만들기 (`adv_b.py`, TestClient)

| 시험 | 결과 |
|---|---|
| 가짜 카드+가짜 근거(해시 일치)+`generator:astra`, `model:gpt-6-astra` | 200. README "Neumann 내보내기 패키지 … astra(LLM) … 제품 LLM(OpenAI)이 만든 카드", 리포트 "인용문은 원문을 오프셋으로 잘라 그대로 옮긴 것이다". 서명·출처 표기 없음. `manifest`의 sha256은 자기 일관성일 뿐(공격자도 계산 가능). 표기는 `evidence_reverification: not_reverified`, `plan_source: result.plan`뿐 (F1) |
| `<script>`·`<img onerror>` 제목·근거·계획서 줄 | 200. 7개 텍스트 파일에 그대로 들어감(이스케이프 없음). .md/.json은 내려받은 파일이라 실행되지 않지만 느슨한 뷰어에선 위험 (F4) |
| CSV 수식 `=HYPERLINK(...)`, `@SUM`, `+SUM`, `-2+3` | `similar_works.csv`에 그대로 → 엑셀에서 수식으로 해석될 수 있음 (F4) |
| 경로·헤더 주입 파일명(`../../evil.zip`, CRLF, 유니코드 RLM, 5000자, `C:\Windows`) | 전부 `[0-9A-Za-z_-]`만 남긴 12자 이내 파일명. `X-Injected` 헤더 없음. ZIP 항목명은 고정 |
| 크기 상한(L2f 단독) | 상한 없음. 1.4/5.4/8.1/26.9MB 본문 모두 200(0.1~0.8초), 결정 10만건(7.2MB) 200(1.9초). 적대 형태(카드 8,000장×줄 199개, 9.6MB) **56.9초** CPU, 응답 5.3MB |
| 크기 상한(L2d+PM 패치 병합본) | 4MiB 초과는 `413 too_large`(5.4MB·8.1MB·26.9MB·7.2MB·9.6MB 모두). 상한 안 최악(3,300장×199줄, 3.99MB) **10.5초** 200. 원인은 `_plan_annotated`·`_plan_line_text`·`_one_line`의 제곱 비용(프로파일 24.5초/프로파일러 켠 상태) |
| 결정 항목 검증 | 없는 `item_id`는 422(반사 문구는 JSON `detail`, `application/json`), PII는 `[EMAIL]`·`[ORCID]`로 가림 |

### (c) 서버 오류 문구 XSS

- 빌더 테스트(가로챈 422·429)에 더해, **서버가 진짜로 만든 422**(뷰의 `result.evidence[0].source_url`에 `xx <img src=x onerror=…>`·`<script>`·`<svg onload>`·`"'><b id=pwn>` 삽입 → 서버 검증이 그 값을 오류 문구에 되돌려 줌)를 브라우저로 시험: 4종 모두 `#expMsg`에 글자 그대로 표시, 자식 요소 0, `window.__xss` null, 다시 그린 뒤에도 안전.
- 코드: `expPaint`는 `textContent`, 다시 그릴 때·속성(`title`)은 `esc()`(`& < > " '` 모두 치환). `D.result`는 어디에서도 innerHTML로 그려지지 않는다.
- L2d 병합본: 422 문구는 서버가 고정 문구("요청 형식이 올바르지 않습니다…")로 바꿔 반사 자체가 없음.

### (d) 화면 데이터 크기

- plan.md(645자): 뷰 72.5KB(`result` 46.4KB + 나머지 30.9KB). jobs 폴링 응답 73KB.
- 49,115자 계획서: 뷰 315,456바이트, `result` 192,468바이트, 패키지 요청 192,497바이트 → 200(0.03초), ZIP 36KB. L2d 내보내기 상한 4MiB의 약 4.6%. 계획서가 뷰(`plan.lines`)와 `result.plan.lines`에 두 번 실리는 것이 증가의 대부분.
- 업로드 상한(10MB)·분석 본문 상한과 무관(응답 방향). 응답 크기 상한은 L2c/L2d에 없음. 작업 저장소 500건 × 73KB 수준(약 36MB)은 메모리에서 감당 가능.

## 3. E4-L2d 병합 (scratchpad 임시 병합)

- `git merge origin/main` → 충돌 0. `git merge origin/task/E4-L2d`(74f054d) → 충돌 0(index.html·export.py·tests 자동 병합). PM 패치 `E4-L2c_main.patch`→`E4-L2d_main.patch` 둘 다 `git apply --check` 통과 후 적용.
- 병합본 전체 pytest: `1342 passed, 27 skipped in 181.68s`, 실패 0.
- jobs 결과: `POST /premortem/jobs`(view) 완료 결과에 `result`(46,474바이트)와 `_status.export = {result: true, reason: null}`가 그대로 실림. 그 `result`로 `POST /premortem/package`(결정 2건) → 200, ZIP 9파일, decision_log 2건. `plan_text`만 보내면 422 "내보내기에는 분석 결과가 필요합니다…"(L2d의 SEC-1 S-02 결정과 일치). `format=result`와 `view.result`는 `manifest`(캐시·시간)·세션·시각만 다름.
- L2d의 `scrub_ok_payload`가 중첩된 `result`의 진단 키(`notices`, `reason` 등)를 가리며(경로→`[경로]`, 키→`[가림]`, 트레이스→종류만), 실제 결과에는 무변경이고 가린 뒤에도 `PremortemResult` 검증 통과. 다만 `manifest` 같은 비진단 키는 가리지 않음.
- 병합 화면(jobs 경로): 자체 Playwright로 내보내기 → ZIP 9파일, 내보내기 클릭 뒤 요청은 package 1건.
- **빌더 Playwright 테스트는 병합본에서 실패**(`NEUMANN_UI_TESTS=1`, 8 passed 1 failed): 화면이 jobs 경로로 분석해 `**/premortem/view` 가로채기가 안 먹어 C1 결정이 없음 → 결정 집계 기대값 불일치. 빌더 보고서가 예고한 "기대값만 고친다"가 필요하다. 이 테스트는 옵트인이라 `verify.py`로는 안 잡힌다.

## 4. 발견

| # | 심각도 | 내용 | 재현 |
|---|---|---|---|
| F1 | 중간(SEC-1의 SEC-L5는 낮음으로 분류, L2f가 이 경로를 유일한 내보내기로 만들어 격상) | 클라이언트가 보낸 `result`를 서버가 만든 것처럼 패키지화. 서명·출처 표기 없음. 조작 카드가 "astra(LLM) … 제품 LLM이 만든 카드"로 표기됨 | `adv_b.py basic` [1]. SEC-1 권고(매니페스트에 "요청 본문의 결과를 그대로 담음(서버 재생성·검증 없음)")가 미반영 |
| F2 | 낮음 | 빌더 주장 "extra=forbid라 계약 밖 값은 실리지 않는다"는 자유형 dict(`manifest`, `verification`, `expected_review`, `checklist[*]`, `plan_checks`, `post_status` 등)에는 거짓. 옛 뷰는 안 싣던 값이 `view.result`·ZIP에 실림. 진짜 결과에선 0건 | `adv_a.py` |
| F3 | 중간(단독), 낮음(L2d 병합 후) | `/premortem/package`에 본문 상한이 없음(L2f 단독). 27MB 200, 적대 9.6MB 56.9초. L2d 병합 시 4MiB 상한·보조 관문으로 완화되나 4MiB 안에서도 10.5초 | `adv_b.py big`, `adv_cpu.py` |
| F4 | 낮음(기존 export.py 동작) | ZIP 텍스트 파일에 HTML 이스케이프 없음, CSV 수식 미방어(README가 "엑셀에서 바로 열림"이라 안내). 진짜 논문 제목이 `=`·`@`·`+`·`-`로 시작하면 발생 가능 | `adv_b.py basic` [2] |
| F5 | 낮음 | 화면에서 다시 "보류"로 돌려놓은 항목은 `decision:"hold"`로 로그에 실림(연구자가 건드리지 않은 기본값만 제외). "보류 제외"가 명시적 보류까지 뺀다는 뜻이면 미충족 | `ui_adv2.py`: 클릭 3번 → `C1 hold` |
| F6 | 낮음 | 병합본 413 문구가 "계획서는 50,000자 이하로 올려 주세요"라 내보내기 실패에도 그대로 표시됨(오도) | `ui_adv_m.py` |
| F7 | 낮음 | 빌더 Playwright가 `route.fetch()` 기본 30초에 걸려, 부하가 있으면 콜드 첫 분석에서 실패(1회 재현) | 1회차 308초 실패, 2회차 통과 |
| F8 | 정보 | 결정 시각 `decided_at`은 클라이언트 시계(`new Date().toISOString()`). 결정 id는 뷰의 `id`(← `item_id`)와 패키지의 체크리스트 id 규칙이 실제 결과에선 일치(C1~C6) | — |

## 5. 병합 전 필수 조치

1. **공개 서버에는 L2d(4MiB 내보내기 상한) 병합 뒤에만 올린다.** L2f 단독은 본문 상한이 없다(F3). 병합 순서는 L2d 먼저 또는 함께.
2. **L2d 병합 시 `tests/e4/test_export_ui.py` Playwright 기대값을 jobs 경로로 고친다**(POST 목록 `["/premortem/jobs","/premortem/package"]`, 가로채기 대상 `**/premortem/jobs/**`, C1 결정 주입 위치). 지금은 병합본에서 1건 실패한다.
3. **공개 전까지 패키지 출처 표기 추가(F1)**: `manifest.json`과 README에 "결과 JSON은 요청자가 보낸 값이며 서버가 분석·서명한 것이 아님" 한 줄(예 `result_origin: "client_submitted_unverified"`). 작은 수정(export.py, E4 소유)이다.
4. (권고) F2 문구 정정 — `export_result`·보고서의 "계약 밖 값은 실리지 않는다"를 "최상위 계약 밖 필드만 막는다, 자유형 dict는 그대로"로. F4는 CSV 셀이 `= + - @`로 시작하면 앞에 `'`를 붙이도록. F6은 export용 413 문구 분리. F5는 의도 확인.

## 6. 남긴 것·정리

- worktree에 남긴 파일 없음(`git status` 0줄). 시험 서버 전부 종료(8149·8183·8185~8187 LISTEN 없음). 임시 사본·스크립트는 scratchpad `v_l2f/`.
- 제 로그 위치: `verify_full.log`(verify.py), `merged_full_pytest.log`, `ui_l2f_only.log`·`ui_l2f_only2.log`·`ui_merged.log`.
