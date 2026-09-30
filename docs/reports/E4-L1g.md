# E4-L1g 보고서 — 샘플 API·선별 도구 구현 완료, PM 통합·독립검증 대기

## 최신 배정 범위와 실행 정보 (2026-10-01 02:17 KST)

- 역할: builder. 실제 모델: **gpt-6.1-sol**(PM 최신 배정 명시), 커밋 라벨 `builder: codex-gpt-6.1-sol`.
- worktree: `C:/Users/User/Desktop/project_neumann/.claude/worktrees/s2-E4-L1g`.
- branch: `task/E4-L1g`. 시작 HEAD: `a97a165a2bbac5d9eafdd5cf8d2cfa0e1b8bd0a9`.
- 보고서 작성 시 구현 HEAD: `8666244a387780db22509a28402692b207ff994d`(API b10d125·API 검사 b9701ee·선별/검사 8666244). 최종 HEAD는 최종 응답에 기록한다(보고서 자체 커밋의 해시는 문서 안에 넣을 수 없음).
- **OpenAI 실제 호출 0**. 명령마다 provider=mock, NEUMANN_LIVE_TESTS=0, NEUMANN_LIVE_LLM_OK 제거. 기본 pytest conftest는 자체적으로 이 플래그를 0으로 닫는다. `.env`·인증 키·전체 환경변수는 열거나 출력하지 않았다.
- `00_구현_계획서.md`, AGENTS, 공통 task/verify 지시, 기존 인수 보고서를 읽음. E4-L1g 전용 task/verify 파일은 현재 트리에 없음. 최신 PM 지시가 이전 인수 계획의 UI·문서 생성·전체 verify 요구보다 우선한다.
- 서버 기동·8020/8099/8010 호출·프로세스 종료·원본 데이터 변경·외부 웹·arXiv 다운로드·하위 에이전트 없음.
- 02:19 KST 종료 전 점검: stop-request.txt 없음; 마지막 diff는 아래 소유 파일 7개뿐. 후속 커밋 뒤 작업 트리 청결 여부를 최종 응답으로 보고한다.

## 한 일

- `src/neumann/api/samples.py`: 레지스트리 스키마·중복 ID·분야 참조·본문 plan_id·허용 디렉터리 검사를 구현. 목록은 **featured + public_ok=true**만 제공한다. 후보·비공개·retired는 모든 단건 경로에서 404. 내부 curation·의도한 약점·결과 경로는 API에 내지 않는다.
- GET 목록·본문·문서·사전 계산 view의 네 경로 구현. 본문은 기존 허용 파일 그대로, 문서는 레지스트리 파일 이름만 사용한다. 파일이 없으면 문서 목록에 넣지 않고 다운로드 404. case에는 본문·문서·view를 제공하지 않는다.
- 사전 계산본은 기존 로더의 sha256·계약 검사를 거친다. 매니페스트 source=fixture 또는 결과의 mock/fixture 흔적이 있으면 배지·view를 제공하지 않는다. rule·생성 출처 불명도 즉시 결과로 제공하지 않는다. view는 `사전 계산본 · 라이브 분석 아님`을 표시하며 기존 강등/오류 표지도 보존한다.
- `src/neumann/api/sample_curation.py`: 가중 채점과 기록된 생성 방식 판정. `astra` 계약 값만 보고 실모델을 추정하지 않는다. offline manifest는 **Claude/Codex 오프라인**으로 기록·목록·view에 표시한다. 이 작업은 제품 분석 결과를 새로 생성하지 않았다.
- `scripts/curate_samples.py`: `score`, `score --apply`, `feature ID --confirm-human`, `suggest`. 결과 계약을 검사하고 plan_id 우선으로 짝짓는다. 파일 이름 hint는 plan_id가 없을 때만 사용하며 중복 짝은 오류. 결과 폴더에서는 `*.result.json`을 우선 읽는다.
- `score --apply`는 curation만 갱신하며 status/public_ok/본문 경로를 보존한다. `feature`는 공개 승인·사람 확인·현재 결과 sha256·현재 채점 통과를 다시 검사한다. mock/rule/출처 불명·강등·근거 누락은 선별 불가. 자동 라이선스 승인 없음.
- 로컬 출력: curation.json·curation.md·사람 확인용 summary.html(제목·근거 수·검사를 통과한 심사평 첫 문장·의도한 약점 대조). HTML 문자열은 escape. 미등록 제안은 candidate/public_ok=false로 유지하며 본문·인용을 담지 않는다.
- `docs/reports/E4-L1g_main.patch`: OPTIONAL_ROUTERS에 samples를 templates **앞에** 추가하는 한 줄 패치. `main.py`, `templates.py`, `index.html`, `samples.json`은 최종 diff에서 변경 없음.

## 완료 기준별 측정값

Python: 공통 과제 지시의 `C:/Users/User/.venvs/neumann/Scripts/python.exe` 사용.

최종 대상 시험 명령(매번 새 basetemp 사용):

```powershell
$env:NEUMANN_LLM_PROVIDER='mock'
$env:NEUMANN_LIVE_TESTS='0'
Remove-Item Env:NEUMANN_LIVE_LLM_OK -ErrorAction SilentlyContinue
$env:PYTHONIOENCODING='utf-8'
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest -q --tb=short --basetemp C:/Users/User/Desktop/project_neumann/out/codex/E4-L1g-pytest-04 tests/e4/test_samples.py tests/e4/test_curate_samples.py tests/e4/test_templates.py
```

실제 출력: **123 passed, 3 skipped in 1.87s**. 3 skip은 Windows 심볼릭 링크 생성 권한이 없는 경우의 PDF/DOCX/HWPX 탈출 검사다. 다른 경로 조작 검사는 실행·통과했다. 통과 수는 기존 templates 회귀 시험을 포함한다.

| 완료 기준 | 측정·시험 | 결과 |
|---|---|---|
| 기존 선별·공개 정직성 보존 | registry_errors, 목록, public_ok/status 조합 및 12개 case의 3개 경로 검사 | 검사 오류 0; 17개 중 공개 featured 5개·비공개 candidate 12개. 후보 노출 0 |
| API 네 경로와 라우트 순서 | samples router → templates router인 TestClient에서 GET; 기존 template도 GET | 모두 기대 상태; `/templates/samples` 200, 기존 template 200. PM 패치 전 실제 main에는 아직 연결되지 않음 |
| 내부 정보 비공개 | API 키 allowlist 및 응답 검사 | curation·intended_weaknesses·result_file·result_hint·keywords·path 노출 0 |
| 허용 본문과 관문 | 공개 5편 원문 일치; 300자 규칙 + 로컬 rule_fitness | 예시 3편 ok, 짧은 초안 reject, 여행 글 unfit |
| 문서 파일·경로 | 임시 테스트 바이트만 사용하여 PDF 다운로드 MIME/파일 이름 및 없는 파일·미허용 형식·폴더 탈출 검사 | 정상 응답/404/500 기대값 통과. 문서 자체 추출·렌더 시험은 미실행 |
| fixture 배지 금지 | fixture source, pipeline source 아래 mock 결과, 변조 JSON | 배지 available=false, view 404 |
| 사전 계산본 표시 | 임시 구조 변형 fixture로 live/offline 분기·ui_view 계약·degraded 분기 검사 | 계약 오류 0; offline 생성 방식 및 강등 표시 보존. 실제 live 실행 아님 |
| 선별 점수와 필수 조건 | 관문·강등·카드 수·근거 연결·심사평·체크리스트·분야·수정 권고 각각 조작 | 각 실패 시 점수 하락·eligible=false; 완전한 테스트 변형 100점 |
| 선별 변경 안전성 | --apply 보존, 사람 확인·공개 승인·hash 재검사, mock 점수 위조 | 보존/차단 통과; 바뀐 결과는 사람 확인 무효화 |
| 실패를 숨기지 않음 | 깨진 레지스트리·잘못된 결과·빈 폴더·짝 없는 결과 | API 500 또는 CLI exit 1; 거부된 본문은 오류에 출력하지 않음 |
| 외부 호출 없음 | socket.socket.connect를 실패하도록 바꿔 API 목록/본문/view와 CLI 실행 | 모두 통과. 실제 OpenAI 호출 0 |

CLI 예행 명령(실제 제품 레지스트리 쓰기 없음):

```powershell
$env:PYTHONPATH='src;.'
& C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/curate_samples.py score tests/fixtures/premortem_result.json --output C:/Users/User/Desktop/project_neumann/out/codex/E4-L1g-curation
```

실제 순위 행: `example-battery | 15.79 | mock | False`. 산출물은 저장소 밖 out/codex에만 있으며 커밋하지 않는다. --apply/feature는 임시 테스트 레지스트리로만 시험했다.

추가 검사: `git apply --check docs/reports/E4-L1g_main.patch` exit 0; `git diff --check` exit 0. git hook의 staged/message 보안 검사는 통과. **전체 python scripts/verify.py는 최신 지시대로 실행하지 않음(PM 큐 담당)**. 독립 gpt-6-sol 검증은 아직 없음.

원문 분량 실측(파일 끝 개행 포함): battery 645자/27줄, binding 926자/27줄, operator 901자/28줄, short 127자/4줄, off-scope 539자/26줄. 이전 인수 기록의 숫자는 끝 개행 제외. short의 rule_fitness 단독 결과는 fit이지만 300자 미만 관문이 먼저 reject하며 이 순서를 시험했다.

실행 안전 상태 실측: `provider_is_mock: True; live_tests: False; live_llm_allowed: False`(선택한 참·거짓만 출력, 설정 객체/키 출력 없음).

## 실패·제약 및 PM 결정 제안

- 최초 시험: `1 failed, 91 passed, 21 errors`. 1 fail은 인수 보고서의 총 16개 표기를 그대로 시험에 옮긴 오류(실제 17개), 21 errors는 기본 Temp/pytest-of-User 접근 거부. 항목은 보존하고 실측으로 수정; 허용된 out/codex의 새 basetemp로 해결했다.
- 최초 git add/commit은 공유 `.git/worktrees/.../index.lock` 쓰기 권한이 없어 실패. 같은 소유 파일만 명시한 승인 범위 커밋을 권한 확장으로 실행했고 훅을 유지한 채 통과했다. force/reset/stash/clean/전체 add 없음.
- 필수 채점 항목 모두 통과해야 선별 가능한 보수적 기준을 택했다. 수정 권고가 없으면 95점 가중 분모를 100점으로 정규화한다. 현재 수정 권고 검사 대상은 `plan_checks.revision_advice.items[].evidence`; 다른 E3 계약으로 연결한다면 PM/E3 합의 후 조정 필요.
- 타인 사례를 public_ok=false면 요약까지 목록에서 숨기는 최신 지시를 적용했다. 라이선스 승인이나 featured/candidate 재배치는 수행하지 않았다.
- fixture/mock뿐 아니라 rule·출처 불명 사전 계산본도 즉시 배지를 막았다. 완성도 점수는 과학적 정확도·성능 측정이 아니다.
- 공통 HANDOFF/QUEUE/decisions를 수정하지 않았다. 위 기준과 범위 축소는 PM이 필요하면 decisions에 반영할 제안이다.

## 후속 UI 통합 제안 (코드 변경 없음)

- 먼저 main 패치를 적용해 samples를 generic templates보다 앞에 등록한다. 중복 include_router는 추가하지 않는다.
- 현 index.html의 toast(447행)와 기존 script(448행) 사이에 독립 gallery script/style를 붙이는 기존 제안을 유지. 실제 병합 후 줄 번호보다 DOM/함수 이름으로 위치를 찾는다.
- `renderInput()`의 `.card#inCard` 앞에 gallery 자리 제안. 577행 `window.NeumannInput`에 setPlan/start/readFile/showView 훅을 한 번만 통합. 이 작업에서는 아무 훅도 추가하지 않았다.
- `/templates/samples`의 notice·body_available·documents·precomputed.available/generation을 그대로 사용. available=false이면 즉시 버튼 금지; 문서 목록이 비어 있으면 업로드 체험 버튼도 만들지 않는다. 기존 tplList/exList 유지.

## 남은 일 (5줄)

1. PM이 E4-L1g_main.patch를 통합해 실제 main의 라우트 순서를 확인한다.
2. 독립 gpt-6-sol 검증 후 PM 큐에서 전체 verify를 실행한다.
3. 후속 UI 담당이 gallery·NeumannInput 훅을 한 번만 통합하고 반응형/키보드 시험을 한다.
4. 문서 담당이 허용 텍스트로 PDF/DOCX/HWPX를 생성할 때 관련 SKILL을 읽고 추출·렌더 검사를 한다.
5. PM이 승인된 기존 실결과를 이 도구로 채점·사람 확인하고 사전 계산본을 연결한다(새 API 실행 없음).

---

## 이하: 인수 당시 기록 (현재 완료/범위는 위 최신 보고가 우선)

## 남은 일 (인수 시점, 우선순위 순)

1. **API·라우터**: `src/neumann/api/samples.py` 새로 쓰기 — `samples.json`(작성 완료, 스키마 `samples.schema.json`) 읽기·검사, `GET /templates/samples`(featured만, `intended_weaknesses`·`curation.reason` 숨김, public_ok=false면 본문 없음, 사전 계산본 `load_precomputed(plan_id)` 조회로 `precomputed.available` 배지 — source=fixture는 미제공), `GET /templates/samples/{id}`(본문, public_ok만), `GET /templates/samples/{id}/document/{pdf|docx|hwpx}`(파일 이름은 레지스트리에서만, `webui/samples/` 밖 금지), `GET /templates/samples/{id}/view`(사전 계산본 → `build_ui_view`, `_status.label="사전 계산본 · 라이브 분석 아님"`). **주의: `templates.py`의 `/templates/{item_id}` 패턴이 `samples`와 맞으므로 새 라우트를 그 앞에 등록**(templates.py 맨 위에서 `router.include_router(samples_router)`).
2. **문서 샘플 3종**: `scripts/make_sample_documents.py` — 예시 3편(plan.md·protein_ligand_affinity.md·neural_operator_weather.md)을 PDF(playwright chromium `page.pdf()`, 로컬 Pretendard woff2 @font-face), DOCX(python-docx, 제목·절 스타일, 줄마다 문단), HWPX(zipfile, `mimetype`(무압축 첫 항목)+`Contents/content.hpf`+`Contents/section0.xml`+`Contents/header.xml`+`META-INF/manifest.xml`+`Preview/PrvText.txt`, 구조는 `git show task/E4-L2h:tests/e4/test_upload_hwpx.py`의 `make_hwpx` 헬퍼와 같게)로 `src/neumann/webui/samples/`에 생성. `#`·`##` 표식은 떼고 제목·절 제목으로 넣는다. 검사 기준: DOCX·HWPX 추출 텍스트 == 표식 뗀 원문(정확히), PDF는 공백 제거 뒤 같음. HWPX 추출 시험은 `PYTHONPATH=.claude/worktrees/s2-E4-L2h/src`로(main에는 hwpx.py 없음, main은 415).
3. **UI(index.html)**: 충돌 최소화 원칙 — 새 `<style>`·`<script>` 블록은 447행(`<div class="toast">`)과 448행(`<script>`) 사이에 넣고 DOMContentLoaded 뒤 실행(다른 브랜치 E4-L2f·L3m·L1e·L2h가 안 건드리는 자리). 기존 스크립트 수정은 두 줄만: ① 503~504행 `renderInput()` 반환에 `<div id="gallery"></div>` 자리(`.card#inCard` 앞) ② 577행 `window.NeumannInput`에 `setPlan(text, meta)`·`start()`·`readFile(file)`(S.mode='file' 뒤 readFile)·`showView(view, meta)`(D=view; go(2)) 추가. 갤러리는 MutationObserver로 `#gallery`가 생길 때마다 그린다. 카드: 분야 태그·제목·요약·분량·형식 아이콘, "이 샘플로 분석"/"입력 칸에 채우기", 문서는 "문서로 업로드 체험(PDF·DOCX·HWPX)"(fetch→File→NeumannInput.readFile)·"내려받기", 거절 시연은 "거절되는 예" 묶음, case는 "백테스트 사례"(요약·원문 링크만), "사전 계산본 · 즉시" 배지 → `/view`로 바로 결과. 분야 칩(radiogroup, 화살표 키), 카드 화살표 이동, 반응형 3/2/1열(900·600px, E4-L3m 기준). 갤러리 제목에 "시연 예시(선별) — 성능 주장 아님" 문구. 기존 템플릿·예시 행(`#tplList`·`#exList`)은 테스트가 보므로 그대로 둔다.
4. **선별 스크립트 `scripts/curate_samples.py`**: 결과 JSON(PremortemResult; 라이브 3편은 `.claude/worktrees/s2-E5-L1e2e/docs/reports/E5-L1e2e_live/*.result.json`, mock 시험본은 scratchpad `mock_plan.result.json` 또는 `NEUMANN_LLM_PROVIDER=mock`으로 `run_premortem` 재실행 약 140초)을 읽어 plan_id(본문은 `PlanDocument.from_text`, case는 레지스트리 plan_id, 보조로 `result_hint` glob)로 짝짓고 점수(0~100, 가중치 제안: 관문 정상 20 필수 / 강등 0 15 / 카드 4~8 15 / 근거 연결 `verification.linkage_rate`=1·카드 evidence⊂evidence 15 / 심사평 문장 전부 `c`≠∅ 10 / 체크리스트 항목 evidence⊂카드 evidence·`verification.checklist_evidence.dropped`=0 10 / 분야 일치(`domain`·`plan_checks.fitness.field` vs fields.keywords) 10 / 수정 권고(있으면) 근거 완비 5, 없으면 분모에서 뺌). mock 결과는 점수를 내되 `generation="mock"`으로 표시하고 선별 불가. 출력: 순위 표(stdout·`curation.md`), `curation.json`, 사람 확인용 `summary.html`(카드 제목·근거 수·심사평 첫 줄·의도한 약점 대조: 같은 risk_code + keywords 겹침). `--apply`로 `samples.json` `curation` 칸 갱신(status는 안 바꿈), `feature ID`로 사람 확인 뒤 status 변경, `suggest`로 미등록 결과의 후보 항목 제안. 테스트는 `tests/fixtures/premortem_result.json`(plan_id가 example-battery와 같음)과 그 변형으로.
5. **테스트·검증·보고**: `tests/e4/test_samples.py`(스키마·경로 검사, 샘플별 관문 판정 — E3-L1s `input_quality` 있으면 그것, 없으면 300자 규칙+`rule_fitness`: 예시 3편 ok, reject-too-short 126자 reject, reject-off-scope 538자 unfit; API 4종·경로 조작 404; 문서 3종 `extract_plan`·`/upload/plan` 추출 일치), `tests/e4/test_samples_ui.py`(NEUMANN_UI_TESTS=1, 81xx 포트, mock 서버: 갤러리→분석→mock 결과(약 140초), 문서 업로드 체험, 필터, 390·1440 스크린샷 `docs/reports/E4-L1g_*.png`, 외부 요청 0), `tests/e4/test_curate_samples.py`. `python scripts/verify.py` 통과 뒤 보고서 표(분야·분량·의도한 약점·형식) 갱신, 사전 계산 명령은 **새 실행이 아니라** `python scripts/precompute_demo.py --from-results <결과 폴더> --server-port 8020 --run-commit <sha>`(E6-L3d 형식, 추가 비용 $0)로 적는다.

## 지금까지 한 것 (Fable 세션, mock만, OpenAI 호출 0)

- 읽음: `_COMMON.md`·`AGENTS.md`·`index.html`·`templates.py`·`upload.py`·`precomputed.py`·decisions(300자 거절·600자 경고·범위 밖 거절), 동시 수정 브랜치 헝크(E4-L2f 433·472·827·875행, E4-L3m 433·825·909·922행, E3-L1e 294·762행, E4-L2h 601~608행), E4-L2h `hwpx.py`, E6-L3d `precompute_demo.py --from-results` 규칙, E5-L1e2e 라이브 결과 3편 구조(status ok, 카드 5~7, 근거 연결률 1.0, 체크리스트 11~18, 심사평 8문장 전부 근거).
- 대표 정정 반영: 후보 15~18편 작성·후보 라이브 실행 **취소**. 샘플 풀 = 실제 테스트 입력·결과. 새로 쓴 계획서는 거절 시연 2편뿐.
- 작성: `src/neumann/api/templates/samples.json`(스키마 `samples.schema.json`) — featured 5(예시 3편 임시 featured + 거절 시연 2편), candidate 11(E5-L2f 원문 복원 7편: yUefexs79U·mBXLtNKpeQ·5AtlfHYCPa·p6eQRlaxGo·jUxzh1bi3i·vsLohTBH4h·ARQIJXFcTH, `data/eval/fulltext/manifest.json` 기준 arXiv v1; E2-L5 분야 테스트 5편: PINN PxRATSTDlS·kqdNvAhJrJ·BSGQHpGI1Q, 결합·도킹 S2WHlhvFGg·mOpNrrV2zH). 모든 타인 논문 사례는 `public_ok=false`, `license` "미확인"(arXiv OAI-PMH 메타로 확인 전 비공개), 본문 경로 없음. 예시 3편의 `intended_weaknesses`를 줄 번호·risk_code·대조 낱말과 함께 구체적으로 적음.
- 작성: 거절 시연 `src/neumann/api/templates/samples/reject_too_short.md`(126자, 단백질 백본 확산 모델 초안)·`reject_off_scope.md`(538자, 제주 여행 계획 — `rule_fitness` 무관 표지어 여행·숙소·맛집 포함).
- 확인: mock 파이프라인 `run_premortem(plan.md)` 137초, status degraded(mock), 카드 6·근거 27·연결률 1.0 — UI 테스트의 "갤러리→분석→mock 결과" 대기 시간 기준.

## 샘플 표 (레지스트리 기준)

| id | 종류 | 분야 | 분량 | 형식 | 의도한 약점 | 결과 출처 | 공개 |
|---|---|---|---|---|---|---|---|
| example-battery | plan·featured | 소재·화학·분자 / 배터리·전해질 | 644자 27줄 | 텍스트 (+PDF·DOCX·HWPX 예정) | R3 무작위 분할·중복 미제거, R2 기준선 불명·오차 막대 없음, R7 일반화 없음, R5 비공개 | E5-L1e2e v1 라이브 | 우리 작성 |
| example-binding | plan·featured | 단백질·생물·신약 / 결합 | 925자 27줄 | 텍스트 (+3종 예정) | R3 패밀리 분할 없음·세트 겹침, R4 도킹 점수 라벨, R2 Vina 1종·시드 1개 | E5-L1e2e v1 라이브 | 우리 작성 |
| example-operator | plan·featured | 물리·PDE·기후 / 신경 연산자 | 900자 28줄 | 텍스트 (+3종 예정) | R3 시점 무작위 분할, R8 보존 법칙 미반영, R2 롤아웃 없음·시드 1개, R7 해상도 밖 없음, R1 속도 주장 미측정 | E5-L1e2e v1 라이브 | 우리 작성 |
| reject-too-short | reject·featured | (단백질) | 126자 | 텍스트 | — (300자 미만 거절 시연) | 관문 규칙 | 우리 작성 |
| reject-off-scope | reject·featured | (여행) | 538자 | 텍스트 | — (범위 밖 거절 시연) | 적합성 판정 | 우리 작성 |
| case-* 11편 | case·candidate | 각 분야 | 미정(복원본) | 요약·링크만 | 실제 논문 — 없음 | E5-L2f 7편(예정)·E2-L5 5편(예정) | 비공개(라이선스 미확인) |

## 사전 계산(실행 금지, 명령만)

새 라이브 실행 없음. 선별된 결과를 그대로 가져온다(E6-L3d 형식, 비용 $0):

```
NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." python scripts/precompute_demo.py --from-results .claude/worktrees/s2-E5-L1e2e/docs/reports/E5-L1e2e_live --server-port 8020 --run-commit <라이브 서버 커밋> --allow-partial
```

case(백테스트 사례)는 E5-L2f·E2-L5 결과가 들어온 뒤 `--plan <복원본 경로>`를 더해 같은 명령으로(본문은 공개 fixture가 아니므로 사전 계산본에 실리지 않는다 — 저작권 요건과 맞음).

## 결정

- 후보 계획서를 새로 쓰지 않는다(대표 00:3x 정정). 거절 시연 2편만 새로 썼다.
- 타인 논문 사례는 라이선스 확인 전까지 `public_ok=false`·본문 없음. 라이선스 확인은 arXiv OAI-PMH 메타(`http://export.arxiv.org/oai2?verb=GetRecord&metadataPrefix=arXiv&identifier=oai:arXiv.org:<id>`)로만, 다운로드 없이 — 선별 스크립트의 별도 하위 명령(테스트는 네트워크 없음).
- 사전 계산본 배지는 source=fixture면 달지 않는다(가짜 데이터를 "즉시 결과"로 보이지 않게).

## 못 한 것

위 "남은 일" 1~5 전부(코드·문서 파일·UI·스크립트·테스트·스크린샷). verify 미실행. 서버 띄운 것 없음(종료할 프로세스 없음).
