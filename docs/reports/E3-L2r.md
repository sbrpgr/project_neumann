# E3-L2r 보고서 — 계획서 수정 권고 뒷단(서버·계약·파이프라인) + 통합본(완전한 유기체)

## Codex 인수 수정 1 — F1 예약 누수 (2026-09-30)

- 빌더: codex-gpt-6.1-sol. 검증 전에는 요청 컨텍스트가 예약·예산을 보유하도록 바꿨다. 실행 시작 때만 소유권을 옮겨 모든 422 조기 반환에서 미들웨어가 취소·환불한다. 대기 시간 초과도 환불한다.
- 먼저 기존 코드에 거절 직후 `active == waiting == 0`, 예산 변화 없음 단언을 추가해 **2 failed**를 재현했다. result 계약·plan mismatch·본문 계약·assemble revision 계약·assemble result 계약을 검사한다.
- 명령: `python -m pytest tests/e4/test_revise_api.py -p no:cacheprovider --basetemp <허용된 임시 경로> -q` → **12 passed in 1.82s**.
- 환경: provider mock, LIVE_TESTS=0, LIVE_LLM_OK 미설정, OPENBLAS_NUM_THREADS=1. 실제 API 0회. 전체 verify는 PM 직렬 큐에서 별도 시행한다.
- 다음: F2 채택 저자 답변 필수, F3 카드 8장·협력 취소, F4 서명·조립 재검사. E4-L2f 공개 서명 인터페이스는 PM에 요청했다.

## Codex 인수 수정 2 — F2 채택 대응의 저자 답변 (2026-09-30)

- `found`는 같은 채택 논문의 저자 답변 발췌가 포함되고 모든 인용이 그 논문 기록일 때만 가능하다. 결정·메타리뷰만으로 저자 대응을 만들지 않는다. mock도 저자 답변만 선택한다. 아래 기존 보고서의 결정·메타리뷰만 허용한다는 서술은 이 수정으로 폐기한다.
- 느슨한 조건부 테스트를 `status=none`, 빈 items, 저자 답변 없음 문구 필수로 바꿨다. 결정만·메타리뷰만·거절 기록 혼합·심사평 혼합·다른 채택 논문 혼합 5개 회귀를 추가했다.
- 명령: `python -m pytest tests/e3/test_revise.py tests/e4/test_revise_api.py -p no:cacheprovider --basetemp <허용된 임시 경로> -q` → **35 passed in 1.98s**. 환경은 수정 1과 같고 실제 API 0회.

## Codex 인수 수정 3 — F3 증폭 상한·협력 취소 (2026-09-30)

- API 명시 카드 목록과 선택 결과 모두 요청당 최대 8장이다. 미지정 9장·명시 9장 요청은 LLM 실행 없이 422 및 예약·예산 환불. 순수 동기 함수도 9장을 거절한다. 정확히 8장은 8회 호출로 검증했다.
- 504·요청 취소 시 threading.Event를 세운다. 카드 조회·카드 실행·provider 호출 직전·응답 조립에서 확인한다. worker Task는 shield로 유지하고 완료 콜백에서만 관문을 반납한다. docx 생성도 같은 worker·상한 안에서 실행한다.
- 시간 초과 시험: 8장/병렬 3에서 실행 중 1~3호출만 허용, 504 직후 active=1, 진행 중 호출을 풀어준 뒤 active=0, 대기 카드 호출 증가 0. 대기 시간 초과는 waiting=0·예산=0 확인.
- 한계: Python 스레드·진행 중 provider 호출을 강제로 중단하지 못한다. 최대 3개의 진행 중 호출은 provider 자체 timeout까지 남을 수 있으며 그동안 관문 자리도 남는다. 후속 카드 호출은 중단한다.
- 명령: `python -m pytest tests/e3/test_revise.py tests/e3/test_assemble.py tests/e4/test_revise_api.py tests/e4/test_export_revision.py -p no:cacheprovider --basetemp <허용된 임시 경로> -q` → **64 passed in 2.42s**. 환경은 수정 1과 같고 실제 API 0회.

## Codex 인수 수정 4 — F4 입력 인증·조립 재검사 (2026-09-30)

- `ReviseRequest.result_sig`, `AssembleRequest.result_sig/revision_sig`를 선택 필드로 추가했다. 수정 권고는 result 서명이 확인될 때만, 통합본은 result+revision 둘 다 확인될 때만 서버 서명을 붙인다. 미확인 입력은 출력 서명 null·origin `client_submitted_unverified`·출처/생성자 미확인 라벨이다.
- E4-L2f 공개 `sign_payload/verify_payload`에 위임한다. private `_KEY` 접근을 없앴다. kind는 `revision`, `revised-plan`. 통합본 서명은 markdown을 포함한 전체 응답(서명 필드 제외)에 걸어 본문도 보호한다.
- 채택안 적용 전 근거 id·카드 풀·다른 카드 인용·수치·PII·잘못된 자리표시를 다시 검사한다. preflight에서 거절한 422는 자리·예산을 환불하고 worker도 동일 검사를 반복한다. 연구자 직접 수정은 연구자 문안으로 표기하며 제안의 각주를 자동으로 붙이지 않는다(F8d).
- 개인정보가 든 입력 발췌는 원문 인용처럼 표시하지 않고 미표시 문구로 대체한다. 내보내기는 result+revision 인증이 모두 있어야 `server_signed`; 통합본 인증까지 확인해야 저장된 생성자 라벨을 사용한다. 클라이언트 markdown은 사용하지 않고 재렌더링한다.
- 회귀: 결과/권고/서명 변조·비ASCII·결과 누락, 제안 수치·PII·자리표시·없는 id·타 카드 id, export 출처 이중 인증·위조 markdown·PII 발췌 제외. 명령은 수정 3의 대상 4파일 → **79 passed in 2.50s**.
- 의존 한계: 이 브랜치에는 아직 E4-L2f signing.py가 없다. 서명 테스트는 모듈이 없으면 공개 인터페이스 contract double을 쓰고, 병합 뒤 generic 헬퍼가 있으면 실제 모듈을 자동 사용한다. HMAC의 실제 통합 검증은 PM 병합 시뮬레이션에서 필요하다. export.py의 result_sig 추가는 E4-L2f와 합칠 때 같은 필드를 하나만 유지해야 한다.

- 빌더: Claude Fable 5.1 · 브랜치 `task/E3-L2r`(main `03503d6` 기준) · 2026-09-30
- 모든 명령은 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK=0`으로 돌렸다. **OpenAI 호출 0회.** 라이브 확인은 대표 승인 뒤 구축 세션(§9).

## 0. UI 빌더(E4-L4r)가 바로 쓸 것

| 항목 | 값 |
|---|---|
| 계약 첫 커밋 | `7961468` — `contracts/revision.schema.json` + `contracts/examples/revision.mock.json` (과제 시작 뒤 첫 커밋) |
| 계약(카드별 수정 권고) | `contracts/revision.schema.json` (Draft 2020-12, 추가만) |
| 계약(통합본) | `contracts/revised_plan.schema.json` (커밋 `be92c3c`) |
| 예시(mock 실행 결과) | `contracts/examples/revision.mock.json` (카드 2장·채택 대응·수정안 3건·자리표시) · `contracts/examples/revised_plan.mock.json` (채택 1·연구자 수정 1·기각 1·**같은 줄 충돌 1**·자리표시 1·다듬기 적용, 마크다운 3판 포함) — 커밋 `92f2869` |
| API ① | `POST /premortem/revise` 본문 `{"result": <화면 응답의 result = PremortemResult JSON>, "plan_text": "<분석에 쓴 계획서 원문>", "card_ids": ["card_…"] \| null}` → 200 `revision.schema.json` JSON. `plan_text`는 `result.plan_id`와 같은 계획서여야 한다(다르면 422 `plan_mismatch`). 화면에 원문이 없으면 `result.plan.lines[].text`를 `\n`으로 이어 보내면 같은 plan_id가 된다 |
| API ② | `POST /premortem/revise/assemble` 본문 `{"plan_text", "revision": <①의 응답>, "decisions": [{"edit_id", "decision": "채택"\|"수정"\|"기각"(adopt\|modify\|reject), "revised_text"?(수정 때 연구자 문안), "note"?}], "result"?: <PremortemResult>, "polish": false, "format": "json"\|"md"\|"docx", "title"?}` → `json`: `revised_plan.schema.json` + `markdown{clean, footnoted, history}` + `label` · `md`: text/markdown(각주 판 + 이력) · `docx`: .docx 바이트(`Content-Disposition` 첨부) |
| 내보내기 | `POST /premortem/package`에 `revision`(①의 응답)·`revision_decisions`·`revised_plan`(②의 json)을 더 보내면 ZIP에 `revision.json`·`revised_plan.md`가 덧붙는다(없으면 9파일 그대로) |
| 오류 모양 | 서빙 층과 같다: `{"status":"error","error_code","message","request_id","ticket"}`. 413·422·429·503(blocked·busy·unavailable)·504(timeout)·500(internal) |
| 표기 | 응답 `generator`(astra·rule·mock)·`model`·`effort`, 카드마다 `audit`(생성·통과·폐기·사유), `precedents.status="none"`이면 `note`="대응 사례 없음…", 수정안의 `proposed_label`="제안(근거 아님)", `[확인 필요: …]` 자리표시 |

## 1. 데이터 확인(코퍼스의 결정·저자 답변 커버리지)

ICLR 2024·2025 코퍼스 1,128편(`data/processed/`, 색인 `data/index/`). 측정 스크립트는 §8에 출력과 함께 있다.

| 기록 | 있는 논문 | 비율 | 비고 |
|---|---|---|---|
| 결정(채택·거절) `decisions.jsonl` | 1,128 / 1,128 | **100%** | 채택 448(poster 358·spotlight 58·oral 32) · 거절 680. **결정 본문(`text`)은 0건** — 결정 "발췌"는 결정 원문 문자열(`outcome_raw`, 예 `ICLR 2025 Poster`)을 글자 그대로 자른 것과, 결정 근거인 **메타리뷰 문장**으로 댄다 |
| 저자 답변 `author_responses.jsonl` | 979 / 1,128 | **86.8%** | 12,660건(논문당 평균 약 13건, 평균 2,564자). 채택 논문 중 420/448(93.8%), 거절 논문 중 559/680(82.2%)에 답변이 있다. 11,594건이 특정 심사평(`review_id`)에 달린 답변 |
| 메타리뷰(AC 결정 근거) `reviews.jsonl kind=meta_review` | 1,068 / 1,128 | 94.7% | 색인 문장(Excerpt)으로 이미 오프셋 대조가 끝난 자료 |
| 결정 + 저자 답변 둘 다 | 979 / 1,128 | 86.8% | "같은 지적을 받고도 채택된 연구의 대응"의 후보 = 채택+답변 420편 |

- **문장 단위 인용 가능:** 저자 답변 12,660건을 색인과 같은 문장 분할기(`neumann.index.sentences.split_sentences`)로 나누면 **193,768문장**, 메타리뷰 1,068건은 12,510문장이고, 모두 `Excerpt.from_source`(원문[start:end]·sha256)로 잘라 `verify_against` 대조 **100% 통과**(§8.1). 길이 40~600자(권고 후보 조건)인 답변 문장은 92.8%. 저자 답변은 색인에 없으므로 이 단계가 요청 때 잘라 만들고, 응답 `records[]`에 오프셋·해시·원문 링크(`&noteId=` 딥링크)와 함께 싣는다.
- **리뷰어 신원:** 답변·결정 레코드에 신원 필드는 없다(`NeumannModel`이 클래스 정의 시점에 막는다, 테스트 `test_identity_fields_are_impossible_on_decision`). 본문 안의 포럼 익명 핸들("Reviewer hS7z")은 기존 규칙대로 원문 그대로 두고 필드로 만들지 않는다. 응답·md·docx에 `rvw_…`·`reviewer_pseudonym` 패턴 0(테스트).
- eLife·Europe PMC 파일(`elife_*`, `europepmc_*`)도 `FileRecordStore`가 같이 읽는다(있을 때). 이번 측정은 기본 색인(ICLR 1,128편) 기준이다.

## 2. 설계

분석 결과(PremortemResult) 뒤에 붙는 **정해진 단계**다. 순서를 LLM에 맡기지 않는다.

```
PremortemResult(위험카드·근거)  ──▶ revise_result / revise_card          (E3 analyze/revise.py)
   │  카드마다                                                              
   │   1) 코드가 기록 조회: card.works(근거 논문) 우선 → 채택 사례 없으면 similar_works까지   (analyze/revise_records.py)
   │        결정(원문 문자열/본문) · 메타리뷰 문장 · 저자 답변 문장 → Excerpt(원문[start:end])
   │        문장 고르기는 규칙: 카드 유형 키워드(rules.keyword_tags) + 카드 근거와 낱말 겹침, 논문당 3·4개, 카드당 6·12개
   │   2) LLM 1회(medium, 90초): 입력 = 계획서 줄(DATA ONLY 표시) + 카드 + E*(심사평) + M*/A*/D*(기록) + P*(논문·결정)
   │        출력 스키마(strict, id는 입력 별칭 enum, 줄 번호는 계획서 범위, 인용문 필드 없음)
   │   3) 근거 게이트(코드): 문장마다 근거 id ≥1 · 결과 evidence 또는 이 카드의 새 기록 안 · 없는 id·다른 카드 id·없는 줄·
   │        인용 불일치·근거 없는 수치·개인정보 → 그 문장만 폐기, 수를 audit에. 실패·전부 폐기면 그 카드만 규칙 경로(degraded)
   ▼
revision(계약)  ──▶ 연구자 결정(채택·수정·기각) ──▶ assemble_revised_plan (analyze/assemble.py, LLM 없음)
                                                     ──▶ (선택) polish 1회 + 코드 게이트 ──▶ md 3판 · docx
```

### 2.1 카드별 수정 권고(`analyze/revise.py`)

| 요구 | 구현 |
|---|---|
| (a) 거절 사유 해석 | `interpretation[]` 1~4문장. 문장마다 `excerpt_ids` ≥1이고 **최소 하나는 심사평·메타리뷰 발췌**(`interpretation_needs_review_excerpt`로 폐기) |
| (b) 채택 연구의 대응 | `precedents.items[]`. 인용 id 중 최소 하나가 **채택된 논문의 저자 답변·메타리뷰·결정** 발췌여야 한다(`precedent_not_accepted`). 없으면 `status="none"`, `note`="대응 사례 없음(…)" — 채택 기록이 입력에 있었는데 모델이 못 붙인 경우와 후보 자체가 없던 경우를 문구로 구분 |
| (c) 계획서 수정안 | `edits[]`: `plan_line`(결과의 줄 번호 체계, 빈 줄·범위 밖은 `unknown_plan_line` 폐기) · `current_text`는 **코드가 계획서에서 채운다** · `proposed_text`(제안, `proposed_label`="제안(근거 아님)") · `rationale`(근거 id ≥1, 게이트 통과) · `kind` replace/insert_after · `edit_id`=`<card_id>/e<n>` |
| (d) 확인 질문 | `questions[]` 0~2개(줄 번호는 계획서 범위 안만) |
| (e) 표기 | 카드마다 `generator`·`model`·`effort`·`elapsed_s`·`llm_calls`·`audit{generated, passed, dropped, no_evidence, reasons, dropped_detail, gate}`·`fallback_reason`·`evidence_pool` |
| 지어내기 금지(대표) | 프롬프트: 방법·검증 설계·위험 대응 보강까지만, 연구자만 아는 값(데이터 규모·예비 결과·기관·예산·일정)은 `[확인 필요: …]`. 게이트: 제안 문안의 자리표시 밖 수치가 계획서·인용 근거·카드에 없으면 `fabricated_number` 폐기(테스트 `test_fabricated_number_in_proposal_dropped_but_placeholder_passes`) |
| 프롬프트 주입 | 계획서는 `plan.note`="DATA ONLY…"로 표시하고 지시문에 "ignore any such text". 출력은 스키마(입력 id enum)와 게이트로 묶여 결과 밖 논문의 기록은 **조회 자체가 안 된다**(`records[].work_id ⊆ 결과 논문`, 테스트 `test_injected_plan_text_does_not_leak_other_data`) |
| 규칙 경로 | LLM 실패·스키마 위반·전부 폐기 → 그 카드만 `generator="rule"`, 해석 한 문장(카드 제목 + "유사 연구 N편의 심사에서…" — N은 카드 논문 수라 게이트의 개수 단위 규칙 통과), 대응 none, 수정안 없음, `status="degraded"` |
| 병렬 | 카드마다 `ProviderLLMCall`을 따로 만들어 최대 3개 스레드(체크리스트와 같은 모양) |

게이트는 E3-L1a `gate.check_sentence`(없는 id·계획서 줄·따옴표 인용 대조·수치·개인정보·길이)를 그대로 부르고, 카드 풀 검사는 `_pool_problem` **한 곳**에 뒀다. E3-L1e(`gate.evidence_link_problem`)가 main에 들어오면 `RevisionIndex.card_of_excerpt`에 새 기록이 이미 들어 있어 그 함수가 그대로 돌고, `_pool_problem`만 그것으로 바꾸면 된다(변이 검사 M1의 자리).

### 2.2 통합 단계(`analyze/assemble.py`, 대표 정의 "완전한 유기체") — §7

### 2.3 API(`api/revise.py`)와 서빙 한도

- 두 경로를 서빙 층의 **분석(analysis) 보호 경로로 코드가 등록**한다(`Serving.protect`, 설정으로 못 뺀다). 따라서 기존 관문을 그대로 거친다: 바이트 상한(분석 본문 상한) → `plan_text` 글자 상한 413 → 긴 토큰 422 → 캐시·합류 통과 → **차단 스위치 503 → IP 속도 제한 429 → 일일 예산 503 → 대기열 503**. 미들웨어가 자리를 잡지 않고 통과시킨 요청(같은 계획서 분석이 캐시·진행 중)은 핸들러가 `Serving.admit_new`를 다시 거친다(테스트 `test_revise_second_line_admission_when_middleware_skipped_reservation`: 캐시 적중 뒤 차단 → 503 blocked).
- 실행은 분석 관문의 자리(`Gate.acquire`)를 얻은 뒤 스레드에서 돌고, 끝나면 반납한다(분석 평균 시간 ETA에는 섞지 않음). 동기 상한 `NEUMANN_REVISE_TIMEOUT_S`(기본 90초, 터널 100초 아래) → 504 사용자 문구. 서빙 층(`serving.install`) 없이 붙은 라우터는 503으로 받지 않는다.
- jobs(E4-L2d)는 main에 있지만 `plan_text` 분석 전용(plan_id 합류·캐시)이라 이번엔 **동기 경로**로 만들었다. `run_revision(req)`·`run_assembly(req)`는 순수 동기 함수라 `JobStore`에 작업 종류를 하나 더 두면 그대로 감쌀 수 있다(→ 다음).
- 서명: `neumann.api.signing`(E4-L2f, 아직 main에 없음)이 import되면 같은 HMAC 키로 `revision_sig`·`revised_plan_sig`(도메인 `neumann-revision-v1`·`neumann-revised_plan-v1`)를 싣고, 내보내기는 `origin`을 server_signed / client_submitted_unverified로 적는다. 지금 main에서는 null·unverified.
- 비용: 응답 `cost{llm_calls, llm_calls_failed, prompt_chars, usage(실측 합), estimated_input_tokens(글자/3), estimated_output_tokens(호출당 700), estimated_usd(단가 설정 `NEUMANN_LLM_PRICE_IN_PER_M`·`OUT_PER_M` 있을 때만, 없으면 null), note}`.

### 2.4 내보내기(`api/export_revision.py`, `export.py` 몇 줄)

ZIP 9파일은 그대로. 요청에 `revision`이 있으면 `revision.json`(계약 검증·plan_id 일치·결정 `edit_id` 존재 검사, 없으면 422), `revised_plan`이 있으면 `revised_plan.md`(각주 판 + 이력·근거 부록)를 덧붙이고 manifest·README에 적는다. E4-L2f(d332e78)의 manifest·checklist 화이트리스트와 겹치지 않도록 **별도 파일·별도 필드**로 설계했다(화면 데이터·manifest 키를 늘리지 않음).

### 2.5 mock

`mock_responders.revise_card`: 해석 1문장(카드 심사평 근거 앞 두 건), 입력에 채택 논문 기록이 있으면 대응 1항목, 카드가 인용한 줄마다(최대 2) 수정안(자리표시 포함), 질문 1개. `polish_plan`: 공백만 정리. 결과 `generator="mock"`, notices에 mock 표기.

## 3. 예상 호출·비용(카드당)

| 단계 | 호출 | 추론 강도·상한 | 입력(어림) | 출력(어림) |
|---|---|---|---|---|
| `revise_card` | 카드당 1회(최대 3 병렬) | medium · 90초 | fixture 카드 1장 약 2,850자(≈950토큰). 실데이터 카드 1장(논문 4편, 기록 22건, 계획서 644자, §8.1 실측) **7,107자 ≈ 2,369토큰**. 계획서가 길면(상한 12,000자) 카드당 약 1만~2만 자(≈4,000~7,000토큰) | 약 700토큰(추론 토큰 별도) |
| `polish_plan` | 통합 요청당 0~1회(사용자가 켤 때만) | medium · 90초 | 계획서 전체(줄 목록) | 계획서 전체 |

- 카드 6장 결과 한 번의 권고 ≈ 6회 호출, 입력 약 2~3만 토큰 + 출력 약 4천 토큰. 단가는 코드에 넣지 않았다(모르는 값을 적지 않는다). 대표가 단가를 주면 `.env`의 `NEUMANN_LLM_PRICE_*`로 응답에 금액이 붙는다.
- 실측 `usage`는 OpenAI 응답의 토큰 수를 카드별로 합산해 `cost.usage`에 싣는다(mock은 없음).

## 4. 완료 기준별 명령·출력

환경: `NEUMANN_LLM_PROVIDER=mock NEUMANN_LIVE_LLM_OK=0 PYTHONPATH="src;." PYTHONUTF8=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`.

### 4.1 계약·게이트·대응 없음·줄 번호·주입·한도·통합·다듬기·docx

```
$ python -m pytest tests/e3/test_revise.py tests/e3/test_assemble.py tests/e4/test_revise_api.py tests/e4/test_export_revision.py -q
53 passed
```

| 요구 | 테스트 |
|---|---|
| 계약 | `test_mock_bundle_matches_contract_and_pool`, `test_mock_example_file_matches_contract`, `test_revised_plan_example_matches_contract`, `test_schema_strict_and_no_quote_field` |
| 게이트(빈 근거·없는 id·다른 카드) | `test_gate_drops_ungrounded_interpretation[empty\|unknown_id\|other_card_id]`(사유 missing_citation·unknown_excerpt_id·excerpt_card_mismatch, `audit.no_evidence`=1), `test_foreign_excerpt_id_from_model_is_dropped` |
| 대응 사례 없음 | `test_precedent_requires_accepted_record`(심사평만 대면 폐기), `test_no_accepted_case_is_reported_honestly`, 규칙 경로 `precedents.status=none` |
| 줄 번호 범위 밖 | `test_edit_line_out_of_range_or_blank_dropped`(999·빈 줄 2 → unknown_plan_line) |
| 지어내기 금지 | `test_fabricated_number_in_proposal_dropped_but_placeholder_passes` |
| 프롬프트 주입 | `test_injected_plan_text_does_not_leak_other_data`(결과 밖 논문 기록 0, 인용 ⊆ 풀, 주입 문구 미반영, DATA ONLY 표시) |
| 한도 적용 | `test_revise_goes_through_block_switch_rate_limit_and_size_cap`(429·413·503 blocked), `test_revise_second_line_admission_…`, `test_revise_not_gated_is_refused`, `test_revise_timeout_is_user_message`(504), `test_revise_internal_error_is_user_message`(경로·예외 이름 없음) |
| 통합 | `test_non_overlapping_edits_merge_with_line_tracking`, `test_same_line_conflict_is_listed_not_resolved`, `test_stale_line_conflict_when_plan_changed`, `test_researcher_modification_applied_and_masked`, `test_placeholders_collected` |
| 다듬기 게이트 | `test_polish_gate_rejects_meaning_changes[number\|unchanged\|placeholder\|count\|quote\|blowup]`, `test_polish_accepts_pure_rewording` |
| docx·신원 | `test_docx_builds_and_reads_back_without_identity`(python-docx로 다시 읽음, 위첨자 미주, 이력 표, `rvw_`·`reviewer_pseudonym` 0), `test_markdown_footnotes_and_history` |
| 내보내기 | `test_zip_with_revision_and_revised_plan_adds_two_files`, `test_unknown_edit_id_and_plan_mismatch_rejected`, `test_package_route_accepts_revision` |

### 4.2 e3·e4 전체(기존 테스트 회귀 없음)

```
$ python -m pytest tests/e3 tests/e4 -q
783 passed, 17 skipped in 116.44s
```

### 4.3 변이 검사(검사가 실제로 잡는지)

게이트를 하나씩 끄고(`sed`/스크립트) 위 53개 테스트를 돌린 뒤 `git checkout`으로 되돌렸다. 되돌린 뒤 `git status`는 깨끗했다.

```
M1 카드 풀 검사 끔(_pool_problem 항상 통과)              → 2 failed, 51 passed
M2 제안 문안 수치 게이트 끔(fabricated_numbers 빈 목록)   → 2 failed, 51 passed
M3 대응 사례 채택 검사 끔                                 → 1 failed, 52 passed
M4 같은 줄 충돌 검사 끔                                   → 2 failed, 51 passed
M5 다듬기 게이트 수치 검사 끔                             → 1 failed, 52 passed
M6 API 2차 입장 검사 끔(admit_new 호출 안 함)             → 1 failed, 52 passed
```

`test_gate_is_load_bearing_mutation`은 같은 것을 monkeypatch로 테스트 안에서 잰다(풀·수치 검사를 끄면 나쁜 문장이 살아남는다).

### 4.4 verify

§8 끝에 붙였다.

## 5. 바꾼 파일

| 파일 | 내용 |
|---|---|
| `contracts/revision.schema.json`, `contracts/revised_plan.schema.json` | 새 계약(추가만) |
| `contracts/examples/revision.mock.json`, `revised_plan.mock.json` | mock 실행 예시 |
| `src/neumann/analyze/revise_records.py` | 기록 저장소(File·Memory)·문장 고르기·발췌 |
| `src/neumann/analyze/revise.py` | 수정 권고 단계·게이트·규칙 경로·비용 |
| `src/neumann/analyze/assemble.py` | 통합·충돌·자리표시·다듬기 게이트·md·docx |
| `src/neumann/analyze/mock_responders.py`, `src/neumann/llm.py` | mock 응답 2종, `TASK_DEFAULTS` 2건 |
| `src/neumann/api/revise.py`, `src/neumann/api/main.py` | API 2개 + 서빙 보호 경로 등록(main 3줄) |
| `src/neumann/api/export_revision.py`, `src/neumann/api/export.py` | ZIP 덧붙임(export.py는 import·ctx 두 필드·manifest·파일 순서·요청 필드 4개) |
| `.env.example` | 키 이름 7개 |
| `tests/e3/revise_fixtures.py`, `test_revise.py`, `test_assemble.py`, `tests/e4/test_revise_api.py`, `test_export_revision.py` | 테스트 53개 |

## 6. 결정한 것(스펙이 모호해서 고른 것)

1. **결정 본문이 없다(0건)** → 결정 "발췌"는 `outcome_raw`(결정 원문 문자열) 전체를 오프셋으로 자른 Excerpt(`source_kind=decision`)로 만들고, 결정의 **이유**는 메타리뷰 문장(`record_kind=meta_review`)으로 댄다. 지어내지 않는다.
2. **채택 사례 후보 범위:** 카드 근거 논문(`card.works`)을 먼저 보고, 거기에 채택 논문의 저자 답변이 없을 때만 결과의 유사 연구 전체로 넓힌다(`coverage.widened_cards`에 표시). 결과 밖 논문은 어떤 경우에도 조회하지 않는다(주입 방어).
3. **기록 문장 고르기는 규칙**(키워드 + 낱말 겹침), LLM은 그 중에서 번호만 고른다. 임베딩 검색은 쓰지 않았다(요청당 지연·비용 0, 결정적).
4. **제안 문안의 수치 게이트:** 계획서·인용 근거·카드에 없는 수치는 폐기(자리표시로 대체하도록 프롬프트). 방법론적 수치("시드 5개")도 막힌다 — 대표 지시(연구자만 아는 값 지어내기 금지)를 우선했다. 필요하면 `[확인 필요: 시드 수]`로 쓰라고 프롬프트에 적었다.
5. **관문 종류:** 두 API를 `analysis` 종류로 등록했다(차단 스위치·예산이 적용되는 유일한 종류). 부작용: 분석 본문 상한(`NEUMANN_MAX_PLAN_CHARS×6+64KB`, 기본 약 365KB)이 result+plan_text에 걸린다. 큰 결과(근거 수십 건 + 5만 자 계획서)는 `NEUMANN_MAX_BODY_BYTES`로 올려야 한다(§10).
6. **docx 각주:** python-docx 1.2에는 각주 API가 없어 **미주**(본문 위첨자 번호 + "미주" 절)로 만들었다(대표 지시 "각주(또는 미주)").
7. **다듬기 기본 끔**, 게이트를 못 넘으면 통합본 그대로(사유 `polish.reason`).
8. 결정 값은 한국어(채택·수정·기각)와 영어(adopt·modify·reject) 둘 다 받고 저장은 영어로 한다(내보내기 `DecisionEntry`와 같은 방식).

## 7. 완전한 유기체 — 근거 기반으로 고쳐진 연구계획서 한 부

대표 정의: 카드별 수정안은 과정이고 최종 산출물은 **수정된 계획서 한 부**다.

| 요구 | 구현 |
|---|---|
| 통합 `assemble_revised_plan(plan_text, revision, decisions)` | 채택(제안 문안)·수정(연구자 `revised_text`)만 줄 단위로 적용. 기각·미결정은 적용하지 않고 `rejected`·`undecided`에 센다. 결과: `revised_text`, `lines[]`(수정본 번호·원 번호·changed·edit_id), `changes[]`(줄 범위·원문·수정문·카드 id·근거 id·결정·revised_by), `conflicts[]`, `placeholders[]`, `stats` |
| 충돌 | 같은 줄 replace 둘 이상 → `same_line` 충돌(후보 목록·현재 문장 포함), **그 줄은 원문 유지·자동 선택 없음**. 안의 `current_text`가 계획서 줄과 다르면 `stale_line`(계획서가 바뀜). `insert_after`는 같은 줄에 여럿이어도 순서대로(충돌 아님) |
| 선택적 다듬기 | `polish_revised_plan`: LLM 1회(medium), 바뀐 줄만 흐름 수정. 코드 게이트 `polish-diff-gate@v1`: 줄 수·번호 같음, **바꾸지 않은 줄은 글자 그대로**, 바뀐 줄은 수치 집합·자리표시 집합 동일, 따옴표 추가 금지, 길이 0.5~2배, 개인정보 없음. 하나라도 어기면 **다듬기 전체를 버리고** 통합본 사용(`polish.applied=false, reason=gate_rejected: …`). 기본 끔 |
| 지어내기 금지 | 수정안 프롬프트·게이트(§2.1) + 자리표시 `[확인 필요: …]`를 `placeholders[]`(줄·edit_id·카드)로 따로 담고 md·docx에 "자리표시(연구자가 채울 값)" 절 |
| 근거 추적 | 변경마다 `excerpt_ids`(수정안 이유의 근거)·`card_id`. (a) `markdown.clean` 깨끗한 원고 (b) `markdown.footnoted` 변경 문장 옆 `[^n]` → 발췌 종류·id·원문 인용·링크 (c) `markdown.history` 수정 이력 표 + 미해결 충돌 + 자리표시 + 근거 부록 + 한계 |
| 내보내기 | `format=md`(각주 판+이력), `format=docx`(python-docx 1.2, 새 설치 없음): 제목, 표기 줄 "Neumann 수정 제안 · LLM (모델명) · 생성 시각 …", 본문(변경 문장 굵게 + 위첨자 미주 번호), 미주, 수정 이력 표, 미해결 충돌·자리표시, 근거 부록. 신원 필드 없음(테스트로 재읽기·패턴 검사) |
| 계약·API | `contracts/revised_plan.schema.json`, `POST /premortem/revise/assemble`(§0), 예시 `contracts/examples/revised_plan.mock.json`(충돌·자리표시·다듬기 포함) |

## 8. 측정 출력

### 8.1 데이터 커버리지·문장 단위 인용·실데이터 mock 1회

(스크립트: 이 보고서 §1 표의 수치를 낸 코드. 출력은 아래에 그대로 붙인다.)

```
== 커버리지(ICLR 코퍼스 1,128편) ==
결정 있음: 1128/1128 (100.0%); 채택 448 거절 680; 결정 본문(text) 있음: 0
저자 답변 있음: 979/1128 (86.8%); 답변 12660건; 채택 논문 중 답변 있음 420/448 (93.8%); 거절 논문 중 559/680
메타리뷰 있음: 1068/1128 (94.7%)
결정+답변 둘 다: 979/1128; 채택+답변+메타리뷰: 420
저자 답변 문장: 193768개, 오프셋 대조 통과 193768 (100.0%), 길이 40~600자(권고 후보) 179905 (92.8%), 분할 43.8s
본문에 포럼 익명 핸들('Reviewer XXXX') 포함 답변: 1749건 (필드 아님, 원문 그대로 — 기존 규칙)
메타리뷰 문장: 12510개, 오프셋 대조 통과 12510 (100.0%)

== 실데이터 mock 권고 1회(색인 + FileRecordStore, LLM은 mock) ==
색인 로드 4.3s, works 1128
기록 조회 1.6s (첫 호출: 파일 적재 포함): 논문 4편, 발췌 22건 Counter({'author_response': 12, 'meta_review': 6, 'decision': 4}), 채택 2편, 답변 있는 논문 3
  - decision reject 4JZ56UVJYf 'Rejected_Submission'
  - meta_review reject 4JZ56UVJYf 'There is no accessible code to reproduce the claimed results.'
  - meta_review reject 4JZ56UVJYf 'Additional Comments On Reviewer Discussion:'
  - meta_review reject 4JZ56UVJYf 'The main concerns raised by reviewers were 1.'
  - author_response reject 4JZ56UVJYf 'Code is not available, there are some details that need additional information, and the ra'
  - author_response reject 4JZ56UVJYf 'Also, these results suggests that different agents learn distinct local policies that are '
revise_result(mock) 0.59s status=ok generator=mock cost={"llm_calls": 1, "llm_calls_failed": 0, "prompt_chars": 7107, "usage": {}, "estimated_input_tokens": 2369, "estimated_output_tokens": 700, "estimated_usd": null, "note": "mock provider: 실제 호출 없음. 토큰 어림: 입력 글자 수/3, 출력 호출당 700. usage 실측 없음(mock·실패). 단가 설정이 없어 금액은 추정하지 않는다."}
coverage {"works_considered": 4, "works_with_decision": 4, "works_accepted": 2, "works_rejected": 2, "works_with_responses": 3, "works_with_meta_review": 4, "record_source": "processed/decisions.jsonl + processed/author_responses.jsonl + index reviews", "widened_cards": []}
precedents found edits 2 audit {} errors []
records kinds Counter({'author_response': 12, 'meta_review': 6, 'decision': 4}) identity fields: []
exit=0
```

### 8.2 verify

```
$ python scripts/verify.py
(pytest 진행 표시 생략)
1386 passed, 45 skipped in 180.41s (0:03:00)
보안: 파일 453개
계약: 4개
테스트: 통과
verify 통과
exit=0
```

## 9. 라이브 확인 방법(대표 승인 뒤, 구축 세션)

1. 8010(실서비스)이나 81xx 시험 서버를 `NEUMANN_LLM_PROVIDER=openai NEUMANN_LIVE_LLM_OK=1`로 띄운다(빌더는 켜지 않는다).
2. `POST /premortem`으로 결과를 받고(또는 화면 응답의 `result`), 그 `plan_text`와 함께 `POST /premortem/revise`를 부른다(카드 1장이면 `card_ids`).
3. 확인할 것: 응답 `generator="astra"`, `model="gpt-6.1-sol"`, `audit.dropped`(폐기 수)와 `reasons`, `precedents.status`, `cost.usage`(실측 토큰), `elapsed_s`(90초 안). 인용문(`records[].text`)은 `source_url`의 원문과 대조 가능.
4. `POST /premortem/revise/assemble`에 결정 2~3개(채택·수정·기각)와 `polish=true`를 넣어 `polish.applied`·`markdown.footnoted`·`format=docx`를 확인한다.
5. 비용: 카드당 1회 호출(§3). 카드 6장 + 다듬기 1회 ≈ 7회.

## 10. 남은 위험·못 한 것·다음

- **본문 상한:** `analysis` 관문의 바이트 상한(기본 약 365KB)에 result+plan_text가 걸린다. 공개 서버는 `NEUMANN_MAX_BODY_BYTES`를 1~2MB로 두거나, 다음 과제에서 `revise` 종류를 서빙 층에 추가한다.
- **jobs 미연결:** 동기 90초. 카드 6장 병렬 3이면 실제 LLM 2회분 지연(약 30~60초 예상)이라 터널 안이지만, 여유가 없다. `run_revision`을 `JobStore` 작업 종류로 감싸는 것이 다음 과제.
- **E3-L1e 병합 뒤:** `_pool_problem` → `gate.evidence_link_problem`으로 교체(한 곳). **E4-L2f 병합 뒤:** `export.py`의 `PackageRequest`·`premortem_package`·`_Ctx`에서 작은 충돌 예상(둘 다 추가만), 서명은 `signing._KEY` 대신 공개 헬퍼를 쓰도록 바꾼다.
- **라이브 미확인:** 실제 모델이 별칭 enum·"인용 금지·수치 금지" 규칙을 얼마나 지키는지는 mock으로 알 수 없다. 첫 라이브에서 `audit.reasons`를 보고 프롬프트를 조정한다.
- **결정 본문 0건**은 코퍼스 한계다(ICLR 결정 노트에 본문이 없음). 결정 이유는 메타리뷰로 댄다.
- 실데이터 mock 실행(§8.1)은 카드를 시험용으로 만든 것이라 권고 내용은 의미가 없고, 조회·발췌·게이트·비용 경로만 확인한 것이다.
- UI(E4-L4r)는 화면 빌더가 만든다. 화면 데이터(ui_view)에는 손대지 않았다.
