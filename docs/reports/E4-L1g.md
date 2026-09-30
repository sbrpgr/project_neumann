# E4-L1g 보고서 — 첫 화면 샘플 갤러리 + 문서 샘플 (WIP, Codex 인수)

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
