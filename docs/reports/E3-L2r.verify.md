# E3-L2r 검증 보고서 (Claude Sonnet 5.5, 독립 검증자)

- 대상: worktree `.claude/worktrees/s2-E3-L2r`, 브랜치 `task/E3-L2r`, HEAD `68385cd`(main `03503d6` 기준). main 최신 병합은 **보지 못했다**(인수 신호로 중단).
- 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK` 미설정(OpenAI 호출 0). `.env` 열지 않음. git 쓰기 없음, 빌더 worktree에 파일 남기지 않음(`git status` 깨끗). 포트 서버 없음(httpx ASGI).
- 시험 스크립트: scratchpad `l2r/adv1~5.py`, `l2r/mutate.py`(재현용).

## 최종 판정: FAIL

이유: 대표 목표("재탄생")의 정직성·보안 두 축에서 병합 불가 결함이 있다. (1) 잘못된 요청 몇 건으로 분석 서비스 전체가 멈춘다. (2) "채택 연구의 대응"이 저자 답변 없이 결정 기록·메타리뷰만으로 "있음"이 된다. (3) 카드 수 상한이 없어 요청 하나가 LLM 호출 수백 건을 만들고 시간 초과 뒤에도 계속 돈다.

## 항목별 결과

| # | 확인 | 결과 |
|---|---|---|
| 1 | 근거 게이트 | 통과: 빈 근거·없는 id·다른 카드 id·지어낸 따옴표·저자 답변만 인용한 해석·이메일·ORCID·지어낸 수치(37%)는 폐기되고 `audit.reasons`에 기록. 실패: 대응 사례(F2) |
| 2 | 지어내기 금지 | 아라비아 숫자만 잡는다(F5). 기관·예비 결과·한글 수사·데이터셋명은 통과. 폐기이지 자리표시 치환이 아니다 |
| 3 | 신원·개인정보 | 실데이터 80카드 mock 전수: 발췌 1,819건 오프셋·sha256 원문 대조 불일치 0, 이메일·ORCID·프로필 ID 0. 그러나 `Reviewer uusj` 류 익명 핸들 22곳이 `records[].text`에 그대로(F7) |
| 4 | 통합 | 통과: 줄 단위 합치기 정확(교체·삽입·연구자 수정), 같은 줄 충돌은 자동 선택 없이 목록(3건 겹쳐도), 범위 밖 `unknown_line`, md 3판, docx 재읽기. 자잘한 결함 F8 |
| 5 | API 보안 | 통과: 429·413·503 차단, plan_mismatch 422, 거대 입력 413, 주입 계획서 누출 0. **실패: F1, F3, F4** |
| 6 | mock 정직성 | 통과: 라벨 `mock (mock-deterministic-v1)`. 단 위조 revision이 `generator=astra`면 "LLM"으로 표기(F4) |
| 7 | 병합 호환 | **못 봄** |
| 8 | 전체 검사 | 아래 |

### 8. verify·변이

- `verify.py` 전체: 1402 passed, **3 failed**, 26 skipped(861초, 다른 검증자들이 동시에 돌아 기계 부하 큼). 실패 3건은 모두 시간 임계 테스트이고 이 브랜치가 안 건드린 파일: `test_pipeline_parallel`, `test_pipeline_parallel_sim`, `test_upload::test_api_amplification_limits`. 단독 재실행에서 2건 통과, `test_pipeline_parallel_sim`은 부하 중 계속 실패(0.744 vs 임계 0.624). main에서 같은 부하로 재현 확인은 못 했다. 보안 검사 통과(파일 454개), `--security` 단독 실행은 안 함.
- 대상 53개 테스트: 53 passed.
- 변이 재현(scratchpad 사본): M1~M6은 빌더 기록과 같다(2·2·1·2·1·1건 실패). 검증자 추가 변이 중 **생존 4건**(53개 모두 통과): V1 해석에 심사평·메타리뷰 발췌 요구 끄기, V2 수정안 PII 검사 끄기, V7 assemble 줄 번호 범위 밖 검사 끄기, V10 기록 조회가 다른 논문 답변을 섞음. 잡힌 것: stale_line, plan_mismatch, 줄 번호 범위, 기각 적용, 다듬기 3종, 내보내기 edit_id.
- 항상 통과하는 테스트: `test_no_accepted_case_is_reported_honestly`는 `if`로 감싸 통과 조건이 느슨하다. 422 경로에서 게이트 반납을 확인하는 단언이 없다(F1을 놓친 이유).

## 발견

| ID | 심각도 | 내용 | 재현 |
|---|---|---|---|
| F1 | **치명** | 잘못된 요청 한 건마다 분석 관문 자리를 영구 점유한다. `_Gate.refusal_response`가 `ctx.reservation`을 `self.ticket`으로 옮기고 `ctx.reservation=None`·`budget_spent=False`로 바꾼 뒤, 422 경로(본문 오류·result 계약 위반·plan_mismatch·revision 계약 위반)가 `gate.cancel`·예산 환불 없이 반환한다. 미들웨어의 `_drop_reservation`은 `ctx.reservation`만 본다. 결과: 공개 설정(동시 4·대기 30·동기 대기 4·IP당 분당 6)에서 **한 IP가 잘못된 result 6건**을 보내면 `active=4 waiting=2`가 남고 다른 IP의 정상 `/premortem`·`/premortem/revise`가 504다. 재시작 전까지 회복 없음. 예산도 요청당 1씩 소모 | `l2r/adv3d.py` |
| F2 | 높음 | 채택 논문에 저자 답변이 없어도 대응 "있음". 게이트는 채택 논문의 저자 답변·메타리뷰·**결정** 발췌 중 하나만 있으면 통과. 결정 발췌는 `ICLR 2025 Poster` 문자열뿐인데 "저자 답변에서 대응했다고 밝혔다"가 `status=found`(`coverage.works_with_responses=0`). 메타리뷰만으로 "저자들은 반박문에서 해소했다"도 통과. 거절 논문 답변+채택 논문 결정을 섞어 인용해도 통과. mock 응답기와 테스트 주석이 이 동작을 인정한다 | `l2r/adv1.py`(P1·P4), `adv2.py`(P2') |
| F3 | 높음 | 카드 수 상한 없음(`card_ids`=None이면 전부, `PremortemResult.risk_cards` 무제한). 카드 200장 결과(138KB, 본문 상한 365KB 이내)로 LLM 호출 200건. 시간 상한(504)이 나도 `asyncio.to_thread`가 스레드를 못 멈춰 **호출이 끝까지 돈다**(카드 40장·상한 0.5초: 504 시점 12건, 4초 뒤 40건)이고 관문 자리는 504 즉시 반납된다. 일일 예산은 요청 1건=1 단위라 증폭을 못 막는다. 공개 서버에서 OpenAI 비용 증폭 경로 | `adv2.py` 끝, `adv3.py` A |
| F4 | 높음(병합 시) | 입력 진위 미확인. 위조한 result(원문 오프셋과 무관한 자기 일관 `text_sha256`, 이메일 포함)로 수정 권고·조립이 200이고 이메일이 md 각주에 그대로 나간다. 위조한 revision(`generator=astra`, 지어낸 문안 "예비 실험에서 이미 정확도 99%…서울대병원과 공동")이 조립되어 라벨 "Neumann 수정 제안 · LLM (gpt-6-astra)"로 나온다. assemble은 `revision_sig`를 확인하지 않고 `proposed_text`에 게이트를 다시 걸지 않는다. E4-L2f가 병합되면 `sign_payload`가 이 위조 입력의 산출물에 **서버 서명**을 붙이고 내보내기 `origin`이 `server_signed`가 된다(`_origin`은 revision 서명만 보고 result 서명은 안 본다) | `adv3.py` B·C |
| F5 | 중간 | 지어내기 게이트가 수치만 본다. 통과: 기관("서울대학교병원 영상의학과와 공동"), 예비 결과("이미 확인했다"), 한글 수사("연구비 오천만 원"), 데이터셋명, 영어 수사. 자리표시 안 수치 `[확인 필요: 이미 확보한 표본 3000건 규모]` 통과(정규식이 자리표시 안을 제외). 확인 질문에는 수치 게이트가 없어 "표본 3000건·정확도 92%"가 통과. 보고서 §10 한계에 이 범위가 없다 | `adv1.py` E·Q |
| F6 | 중간 | 다듬기 게이트가 수치·자리표시·따옴표·길이(0.5~2배)만 본다. 새 기관 삽입("서울대병원과 공동 수행한다")·핸들 삽입이 `applied=True`. 새 주장은 길이 비율에 걸릴 때만 막힌다 | `adv4.py` 10 |
| F7 | 중간(정책 충돌) | 실데이터 `records[].text`에 익명 핸들 22곳(예: "Reviewer uusj and Reviewer Pevo raised their scores"), 답변 서명 줄 2건("Best regards, The Authors of …", 저자 서명). 9/30 19:00 결정은 본문 원문 유지를 허용하나 이번 검증 규칙(가명 금지)과 충돌. LLM이 쓰는 해석·수정안·질문에는 핸들이 게이트 없이 통과("Reviewer XYZq" 통과, 숫자가 든 핸들은 우연히 수치 게이트에 걸림) | `adv5.py`, `adv1.py` I6·E10 |
| F8 | 낮음 | (a) `proposed_text`에 `<img onerror=…>`·`[x](javascript:…)`가 그대로 통과 — E4-L4r이 이스케이프해야 함. (b) 연구자 문안에 제어문자(`\x00`)가 있으면 `format=docx`만 500. (c) `insert_after`와 `current_text` 빈 값은 stale 검사 없음. (d) 연구자가 직접 수정(`modify`)한 줄에도 규칙 수정안의 근거 id가 각주로 붙는다. (e) 거절된 다듬기의 generator·model이 라벨에 남는다. (f) 추가 `plan_line`이 float·str인 edit는 `unknown_edit`로 조용히 빠진다 | `adv4.py` |

## 병합 전 필수 조치

1. F1: 모든 조기 반환(422)에서 `gate.cancel(self.ticket)`과 예산 환불(try/finally). 422 경로마다 `srv.gate.active==0`·`budget.used==0`을 단언하는 테스트 추가(assemble 포함).
2. F2: `precedents.status="found"`는 채택 논문의 **저자 답변** 발췌를 인용할 때만. 인용 id는 모두 채택 논문 기록이어야 한다. 결정·메타리뷰만이면 `none`("대응 사례 없음: 저자 답변 없음"). mock 응답기·테스트도 고친다.
3. F3: 요청당 카드 상한(예 8), 상한 초과는 422 또는 절단 공지. 시간 초과 뒤 작업이 이어지지 않게 취소 표지를 카드 사이에서 확인하고, 스레드가 끝날 때까지 관문 자리를 잡아 둔다.
4. F4: result(`result_sig`)·revision(`revision_sig`) 서명을 확인하고, 미확인 입력의 산출물에는 서명을 붙이지 않으며 라벨·`origin`을 "client_submitted_unverified"로 표기. assemble은 `proposed_text`에 수치·자리표시·PII 게이트를 다시 건다.
5. F5·F6: 최소한 한글 수사·자리표시 안 수치·질문 수치를 게이트에 넣고, 다듬기 게이트에 새 낱말(고유명사·기관) 검사를 추가하거나 다듬기 기본 끔을 유지하되 API 노출을 문서로 제한. 한계를 보고서에 명시.
6. F7: PM·대표 결정 필요. 권고는 발췌 선택에서 리뷰어 핸들 문장을 제외하고, LLM 작성 문장에는 핸들 정규식 게이트.
7. 이 조치 뒤 재검증: 병합 시뮬레이션(main 최신 + E3-L1e·E4-L2f, 특히 `export.py`·`main.py`), `verify.py`·`--security`, 생존 변이 V1·V2·V7·V10 잡는 테스트.

## 못 본 것

- 항목 7 전부: main 최신·scratchpad 병합, E3-L1e `gate.evidence_link_problem`·E4-L2f `signing` 연결, `export.py`·`main.py` 충돌.
- `verify.py --security` 단독 실행, `test_pipeline_parallel_sim`의 main 재현.
- 실제 astra 응답(별칭 enum·인용 금지 준수), E4-L4r 화면(이스케이프).
