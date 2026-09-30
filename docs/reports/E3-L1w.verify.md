# E3-L1w 검증 보고서 (검증자: Claude Sonnet 5.5)

- 대상: 브랜치 `task/E3-L1w`(19b3fc1), worktree `.claude/worktrees/agent-ad00b98aba2ee5f0e`. 빌더 claude-opus-5.5
- 이 브랜치는 main c4679f9까지만 병합돼 있다. main 최신(ac0bb30, E2-L1 병합 포함)에는 뒤처져 있어서 **main 최신 + 브랜치를 합친 사본**을 따로 만들어 같은 시험을 다시 했다(아래 "합친 사본").
- **실제 OpenAI 호출: 0회.** `NEUMANN_LIVE_TESTS`는 끄고, 모든 시험은 `NEUMANN_LLM_PROVIDER=mock`, `OPENAI_BASE_URL=http://127.0.0.1:9`(연결 불가 주소)로 돌렸다. 키는 있는지만 봤다. 검증자 셸의 기본 환경이 `NEUMANN_LLM_PROVIDER=openai`라서 위 안전장치를 걸었다.
- 코드·git 쓰기 없음. 브랜치 worktree는 시험 뒤에도 `git status` 깨끗(무시 대상 캐시만). 공유 `data/`에는 아무것도 쓰지 않았다(캐시는 임시 폴더).

## 최종 판정: **PASS**

병합 전에 고칠 것은 없다. 단 **완료 기준 2의 실제 astra 실행은 동결 규칙 때문에 하지 않았고 검증도 못 했다.** 그 부분은 "실제 색인 + mock/대역"으로 연결·캐시 적중·근거 연결률을 대신 쟀다(아래). 실제 astra 1회 확인은 PM 승인 뒤 별도로 해야 한다. 그 밖의 관찰은 전부 병합을 막지 않는다(맨 아래).

## 완료 기준별 결과

| # | 항목 | 실행한 명령 | 실제 출력(핵심) | 판정 |
|---|---|---|---|---|
| 1 | tests/e3 (브랜치) | `pytest tests/e3 -q` | `342 passed, 12 skipped`(skip 12 = 실제 API 시험) | 통과 |
| 1 | tests/e3 (합친 사본) | 같은 명령 | `342 passed, 12 skipped` | 통과 |
| 1 | 환경 독립 | `NEUMANN_LLM_PROVIDER=openai`+키+연결불가 주소로 `pytest tests/e3` | `342 passed, 12 skipped`(환경 provider를 안 따라간다, 실제 호출 시도 없음) | 통과 |
| 3 | `verify.py` (브랜치) | `python scripts/verify.py` | `950 passed, 25 skipped in 67.72s` · 보안 327파일 · 계약 2개 · `verify 통과` | 통과 |
| 3 | `verify.py` (합친 사본) | 같은 명령(사본에 임시 git 저장소를 만들어) | `989 passed, 26 skipped in 82.32s` · 보안 351파일 · 계약 2개 · `verify 통과` | 통과 |
| 2 | 실제 astra로 plan.md 2회 | (실행 안 함: 동결) | — | **미검증** |
| 2' | 대체: E2 실색인 + mock 1회 + `check_result` | 합친 사본에서 `run_premortem(tests/fixtures/plans/plan.md, mock, IndexBackend)`, 임베딩 CPU | 카드 6·유사 연구 10, 10단계 전부 ok, `linkage passed=True rate=1.0 card_pass_rate=1.0`, 근거 27/27 원문 일치, 예상 심사평 ok(8/8)·체크리스트 6항목·2차 검증 ok | 통과 |
| 2' | 대체: 대역(이름만 openai, 실제 astra 아님) 2회 캐시 | 같은 조건으로 2회 | 1회차 `stored=True`, 2회차 `hit=True`(단계 detail "검색어 캐시 적중… 생성"), 검색어·유사 연구 10편 동일, `query_axes` 호출 총 1회, 두 번 다 `check_result` 통과 | 통과 |

## 요청받은 특별 확인

| 확인 | 방법과 결과 | 판정 |
|---|---|---|
| 10단계 각각 실패하면 그 단계만 강등 | LLM 강제 실패(`fail={task:"timeout"}`) 7개 task(fitness·query_axes·extract_issues·synthesize_cards·expected_review·checklist·semantic_validate): 각각 **그 단계만 degraded, 나머지 전부 ok**, `status=degraded`, notice에 남음. 단계 함수 예외 주입 7개: fitness·expected_review·checklist·semantic_validate는 **그 단계만 error, 나머지 ok**. query_axes·extract·synthesize는 error 뒤 산출물이 없어 뒤 단계가 skipped(정당). 검색 백엔드 예외: search만 error, 앞 단계 ok. 예외 원문의 경로·키 모양 문자열은 결과 JSON에 없음. plan_normalize·verify_evidence는 기존 E3-L0 동작 그대로 | 통과 |
| 부적합 입력은 검색 전 중단, LLM 추가 호출 0 | 실제 E3-L1c 적합성 모듈 + mock: 조리법 → 호출 목록 `['fitness']` 1건뿐, 카드 0·유사 연구 0, 이후 8단계 전부 skipped, `make_backend`를 부르면 실패하도록 막아 둔 상태에서도 통과(색인 안 염). 영어 광고도 같음. 한 줄 잡담은 규칙 사전검사로 LLM 호출 0건. 연구계획서를 가짜 적합성 모듈로 unfit 강제 + 검색 감시 백엔드: 검색 0회·LLM 0건. 옛 처리(c4679f9)와 비교: 카드 0·`입력이 연구계획서가 아니다(mock 판단: …)`·suitability False 같음, 끝만 "검색 안 함"(옛 "유사 연구 검색 결과 0건")이고 호출은 1건 그대로(옛 query_axes → 새 fitness) | 통과 |
| 생성 주체 추정 금지 | `generator` 속성: OpenAIProvider→astra, MockProvider→mock, DisabledProvider→rule. 속성도 알려진 이름도 없는 provider: `provider_generator`가 ValueError, 파이프라인은 fitness·예상 심사평·체크리스트·2차 검증에서 **LLM을 아예 부르지 않고**(호출 목록에 없음) 규칙·미검증으로 강등, 결과에 astra 표기 없음. 강등 시 표기 확인: fitness 실패 → `('rule','rule_fallback')`, 예상 심사평 실패 → `rule`·degraded, 체크리스트 실패 → 전 항목 `rule` | 통과(관찰 1) |
| 검색어 캐시가 astra 결과만 저장 | mock provider: `queries/` 파일 0개. off(규칙): 0개. astra(대역)인데 LLM 실패 → 규칙 대체: 저장 안 함(`stored=False`). astra 성공: 파일 1개(provider=openai, 경로·키 문자열 없음), 저장 키는 `created_at·data·effort·model·plan_id·prompt·provider·v`. mock provider는 astra 캐시를 못 읽음. 깨진 JSON·스키마 위반 항목은 무시하고 다시 호출·재저장 | 통과 |
| mock으로 E2 실색인 1회 + `eval.linkage.check_result` | 위 2'. 표본 12건을 원문 `review.text[start:end]`로 직접 잘라 비교: 전부 `text`와 같음. 예상 심사평·체크리스트가 인용하는 근거 id는 전부 결과 `evidence`에 있음 | 통과 |
| 결과 JSON에 경로·키 문자열 없음 | 실색인 결과 3건(mock, 대역 2회, 각 약 4.3만 자) JSON을 정규식으로 검사: 드라이브·UNC·`/Users/`·`/home/`·`/tmp/`, `sk-`·`Bearer`, **실제 키 값(프로세스 안에서 부분문자열 비교, 출력 안 함)**, `project_neumann`·`노이만_본선자료`·임시 폴더 이름·`AppData`·`.env`·`Traceback` 모두 없음. 캐시 항목도 없음. 40자 이상 토큰 56개는 sha256 id(plan_id·근거 id 등) | 통과 |
| 소유 경로 밖 변경 | `git diff main...task/E3-L1w --stat`: 12파일 = `pipeline.py`·`llm.py`·`analyze/mock_responders.py`·`analyze/queries.py`·`tests/e3/*`·`docs/reports/E3-L1w.md`. `contracts/`·`models.py`·`config.py`·`.env.example`·데이터·비밀값 파일 변경 없음 | 통과(관찰 4) |

## 정직성·시험의 실효성

- **항상 통과하는 시험이 아닌지**: 합친 사본을 복사해 코드를 일부러 망가뜨리고 `tests/e3`를 돌렸다. 8건 모두 시험이 실패로 잡았다.
  - 부적합인데 검색 계속(M1)
  - v1 단계 예외를 안 막음(M2)
  - mock·규칙 결과도 캐시(M3)
  - 미지 provider를 astra로 추정(M4)
  - 단계 컨텍스트가 예외를 안 막음(M5)
  - 캐시 적중 표시 제거(M6)
  - 체크리스트와 검증 순서를 뒤집음(M7)
  - 빈 입력(정규화 실패)인데도 fitness를 부름(M8)
- 규칙 결과를 LLM 결과로 표시하지 않음: 위 강등 표기 확인. provider off면 카드·예상 심사평·체크리스트 전부 `rule`, 2차 검증은 `rule`·degraded·`unverified`(규칙으로 의미 판정을 흉내 내지 않음)
- mock 결과: `status=degraded` + MOCK_NOTICE. 대역(이름 openai)만 `ok`이며 실제 astra가 아니라는 점은 빌더 보고서와 이 보고서에 적혀 있다
- 인용은 원문 오프셋으로 잘린 것(표본 12건 일치, `check_result` 27/27)
- 검색어 캐시에서 온 결과도 `query_axes` 단계에 "검색어 캐시 적중(생성 시각)"이 남고 `manifest.query_cache`·`plan_checks.queries.cache`에 실림. 캐시 적중은 강등이 아님(status ok 유지)

## 관찰 (병합을 막지 않음. 다음 과제·PM 참고)

1. **`provider_generator`는 `generator` 속성이 없어도 이름이 openai/mock/off이면 이름 대응으로 받는다**(시험 `NamedOnly`로 의도된 결정). 속성도 알려진 이름도 없으면 거부한다. 출하된 세 provider는 모두 속성이 있다. 엄격하게 "속성 없으면 거부"로 읽으면 이 이름 대응은 한 단계 추정이다. 필요하면 이름 대응 폴백을 없애면 된다. 또 검색어·추출·카드 합성 3단계는 이 어댑터가 아니라 `LLMResult.generator`(provider 이름 기준, 모르면 rule)를 그대로 쓴다.
2. **같은 계획서를 동시에 두 번 돌리면 캐시 쓰기 경합.** 임시 파일 이름이 `<키>.tmp`로 고정이라, 스레드 4개로 같은 계획서를 동시에 돌렸더니 검색어 캐시 쓰기 2건이 `PermissionError`로 실패했다(추출 캐시는 E3-L0 기존 방식이라 더 자주 남). 결과는 정상(예외 0, status ok, 같은 유사 연구)이고 캐시 파일도 남았다. 그 실행이 캐시를 못 남길 뿐이다. 임시 파일 이름에 pid·스레드·난수를 넣으면 없어진다.
3. `manifest.stage_limits_s`에 `extract_issues`·`synthesize_cards`의 호출 상한(90s·120s)은 없다(fitness·query_axes·v1 3단계만). 상한은 호출 단위이고 단계 전체를 자르는 벽시계 중단은 없다(빌더 보고서가 공개함). 카드가 8장 이하면 v1 단계 시간은 대략 호출 상한 하나(90초) 안이다. 실제 소요(v0 70~86초 + v1 약 41초 예상)는 실제 호출 승인 뒤 측정해야 한다.
4. 새 v1 task의 시간·강도 덮어쓰기용 환경변수 이름(`NEUMANN_LLM_TIMEOUT_<TASK>_S`, `NEUMANN_LLM_EFFORT_<TASK>`, task는 FITNESS·EXPECTED_REVIEW·CHECKLIST·SEMANTIC_VALIDATE)이 `.env.example`에 없다(PM 소유 파일). 기존 `test_pipeline.py`·`test_security.py`·`test_live_astra.py` 3개도 고쳤는데, 지시문 소유 경로(`test_pipeline_l1*.py`)엔 없지만 `tests/e3/` 안이고 단계 목록 10개 확장과 "적합성 모듈 없을 때만 fitness skipped 허용"뿐이라 단언을 약화시키지 않았다.
5. 실제 실행 시험(`test_pipeline_l1w_live.py`)은 provider를 명시하지 않고 설정을 따른다. 설정 기본이 이제 mock이라서 `.env` 없는 worktree에서 `NEUMANN_LIVE_TESTS=1`만 켜면 mock으로 돌아 "전부 astra" 단언에서 떨어진다(비용은 안 든다). 실제 실행 명령에 `NEUMANN_LLM_PROVIDER=openai NEUMANN_LLM_MODEL=…`를 같이 적어야 한다.
6. 2차 검증이 LLM 실패로 전부 미검증이 될 때 `verification.semantic.generator`는 astra(시도한 주체)로 남고 `status=degraded`, 카드 판정은 전부 `unverified`다(E3-L1b 동작). 규칙 결과라고 주장하진 않지만 화면에서 "astra가 검증"으로 읽히지 않게 status를 함께 보여 줘야 한다.
7. E5 백테스트(`eval/backtest_run_neumann.py`)는 `run_premortem`을 그대로 부르므로 이제 계획서마다 v1 3단계 호출이 더 붙는다(호출 수·시간 증가). 백테스트에는 v1을 끄는 옵션이 없다.

## 합친 사본 만드는 법(재현)

`git archive main`(ac0bb30)을 스크래치 폴더에 풀고, 브랜치가 바꾼 12개 파일 중 `llm.py`를 뺀 11개를 브랜치 판으로 덮고, 양쪽이 바꾼 `src/neumann/llm.py`는 `git merge-file`로 3방향 합쳤다(충돌 표식 0개, main 쪽 변경은 기본 provider를 mock으로 바꾼 2줄). main이 c4679f9 이후 `pipeline.py`·`analyze/`를 바꾼 것은 없다.
