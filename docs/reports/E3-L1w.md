# E3-L1w 보고서: v1 연결(적합성·예상 심사평·체크리스트·2차 검증) + 검색어 안정화

- 빌더: claude-opus-5.5 · 브랜치 `task/E3-L1w` · 목표 50분
- 시작할 때 main(48e33d1)을 받았고, 작업 중에 main을 두 번 더 병합했다: 2b1aee3, 그다음 234b0f3·c4679f9(E3-L1c 적합성 병합, 제품 기본 모델 `gpt-6.1-sol`, OpenAI 호출 동결 결정)
- **실제 OpenAI 호출: 0회, 토큰 0.** 키가 있는지만 참·거짓으로 확인했다. PM 긴급 지시(실제 호출 전면 동결)에 따라 완료 기준 2의 실제 실행은 하지 않았다. **PM 승인 뒤에 한다**(아래 "못 한 것").

## 무엇을 했나

| 파일 | 내용 |
|---|---|
| `src/neumann/pipeline.py` | 10단계로 늘렸다: `plan_normalize → fitness → query_axes → search → extract_issues → synthesize_cards → verify_evidence → expected_review → checklist → semantic_validate`. 적합성은 검색 전에 돈다. 결과가 unfit이면 카드 0장과 사유를 남기고 끝낸다(검색어·검색·추출·합성·v1 단계 모두 skipped, LLM 호출 없음). v1 세 단계는 `_attach_v1`이 단계마다 따로 막는다(예외면 그 단계만 error, LLM 실패면 모듈이 규칙·미검증으로 물러나 그 단계만 degraded). 화면 단계 묶음은 INPUT·REVIEW·ACTION이다. `manifest`에 `timings_s`(전 단계)·`total_s`·`stage_limits_s`·`query_cache`를 싣는다. `PIPELINE_VERSION = neumann-e3-l1w` |
| `src/neumann/llm.py` | provider마다 `generator` 속성을 단다(openai→astra, mock→mock, off→rule, `PROVIDER_GENERATOR`). `provider_generator()`는 속성도 이름 대응도 없으면 ValueError를 낸다(추정 금지). `TASK_DEFAULTS`에 fitness(low, 30s)·expected_review·checklist·semantic_validate(medium, 90s)를 넣었다 |
| `src/neumann/analyze/queries.py` | 검색어 캐시. 키는 `plan_id·provider·모델·추론 강도·지시문 판`이고 `data/cache/queries/<sha256>.json`에 둔다. astra 결과만 저장하고, 규칙 비상 경로·mock 결과는 저장하지 않는다. 읽을 때 응답 스키마로 다시 검사하고, 깨진 항목은 무시한 뒤 새로 호출한다. `QueryPlan.cache = {enabled, hit, stored, key, created_at}` |
| `src/neumann/analyze/mock_responders.py` | v1 네 단계(fitness·expected_review·checklist·semantic_validate)의 결정적 mock 응답. 문장에 숫자·따옴표를 넣지 않아 근거 게이트를 통과한다 |
| `tests/e3/test_pipeline_l1w*.py` | 새 테스트 36건(mock·fixture) + 실제 API 1건(`NEUMANN_LIVE_TESTS=1`일 때만) |
| `tests/e3/test_pipeline.py`, `test_security.py`, `test_live_astra.py` | 연결에 필요한 최소 수정. 단계 목록을 10개로 늘렸고, 적합성 모듈이 없을 때만 fitness의 skipped를 허용한다 |

연결 방식(과제 파일 "연결할 것" 1~6):

1. **적합성**: `fitness.assess_fitness(plan, llm_call, effort=…)`와 `fitness_stage(fit)`를 부른다. 결과 전체는 `plan_checks.fitness`에, 판정 notice는 `notices`에 싣는다. unfit이면 사유를 `입력이 연구계획서가 아니다(<generator> 판단: <reason>); 검색 안 함`으로 쓰고 `plan_checks.suitability.is_research_plan=False`(`source="fitness"`)로 둔다. 예전 조리법 처리와 꼴이 같다. 모듈을 못 불러오면 `fitness`를 skipped(`FITNESS_MISSING`)로 남기고 astra ①의 판정으로 대신한다.
2. **예상 심사평**: `review.attach_expected_review(result, provider_llm_call(llm, task="expected_review", timeout_s=…, generator=…), effort=…)`.
3. **체크리스트 → 2차 검증**: 이 순서로 `checklist.attach_checklist`, `validate.attach_validation`. 같은 어댑터에 task를 `checklist`·`semantic_validate`로 준다.
4. **생성 주체**: 네 단계 모두 `review.provider_llm_call` 어댑터로 부른다. `generator`는 `llm.provider_generator(llm)`에서만 받는다. 모르는 provider면 어댑터를 만들지 않는다(llm_call=None). 이때 모듈은 규칙·미검증 경로로 가고, 단계 detail에 "생성 주체를 알 수 없어 LLM을 부르지 않았다"가 남는다.
5. **검색어 안정화**: 위 캐시. 적중 여부는 `plan_checks.queries.cache`, `manifest.query_cache`, `query_axes` 단계의 `counts.cache_hit`·detail("검색어 캐시 적중(…, <생성 시각> 생성)")·impl(`cache:openai:<model>`)에 드러난다.
6. **시간**: 호출마다 `task_options(task)`의 `timeout_s`를 LLMCall에 넣는다. 설정 `NEUMANN_LLM_TIMEOUT_<TASK>_S`와 `NEUMANN_LLM_EFFORT_<TASK>`로 덮어쓸 수 있다. 단계별 소요와 전체 소요, 상한을 manifest에 남긴다. 강등은 단계 state, `notices`, 결과 `status`에 남는다.

## 완료 기준별 측정

### 1. mock으로 전 단계 테스트(적합성 부적합 → 0장, 각 단계 실패 시 그 단계만 강등)

```
$ PYTHONPATH="src;." python -m pytest tests/e3/test_pipeline_l1w.py tests/e3/test_pipeline_l1w_cache.py \
      tests/e3/test_pipeline_l1w_llm.py tests/e3/test_pipeline_l1w_live.py -v -rs
test_pipeline_l1w.py::test_mock_all_stages_attached_in_order_with_results PASSED
test_pipeline_l1w.py::test_timings_total_and_limits_recorded PASSED
test_pipeline_l1w.py::test_llm_calls_carry_task_limits_and_efforts PASSED
test_pipeline_l1w.py::test_linkage_checker_passes_with_v1_results PASSED
test_pipeline_l1w.py::test_ui_view_accepts_v1_result PASSED
test_pipeline_l1w.py::test_llm_failure_degrades_only_that_stage[expected_review] PASSED
test_pipeline_l1w.py::test_llm_failure_degrades_only_that_stage[checklist] PASSED
test_pipeline_l1w.py::test_llm_failure_degrades_only_that_stage[semantic_validate] PASSED
test_pipeline_l1w.py::test_exception_in_a_v1_stage_is_contained[attach_expected_review] PASSED
test_pipeline_l1w.py::test_exception_in_a_v1_stage_is_contained[attach_checklist] PASSED
test_pipeline_l1w.py::test_exception_in_a_v1_stage_is_contained[attach_validation] PASSED
test_pipeline_l1w.py::test_provider_off_marks_v1_stages_rule_or_unverified PASSED
test_pipeline_l1w.py::test_zero_cards_skips_v1_without_llm_calls PASSED
test_pipeline_l1w.py::test_llm_call_for_uses_provider_attribute_and_refuses_unknown PASSED
test_pipeline_l1w.py::test_unfit_stops_before_search_with_zero_cards PASSED
test_pipeline_l1w.py::test_unfit_result_matches_old_recipe_handling PASSED
test_pipeline_l1w.py::test_fit_overrides_query_axes_rejection_but_uncertain_does_not PASSED
test_pipeline_l1w.py::test_fitness_exception_degrades_only_that_stage PASSED
test_pipeline_l1w.py::test_missing_fitness_module_is_recorded PASSED
test_pipeline_l1w.py::test_real_fitness_fit_plan_runs_all_stages PASSED
test_pipeline_l1w.py::test_real_fitness_recipe_is_not_analyzed PASSED
test_pipeline_l1w.py::test_real_fitness_failure_falls_back_to_rule_only_there PASSED
test_pipeline_l1w.py::test_query_cache_gives_same_similar_works_and_is_reported PASSED
test_pipeline_l1w.py::test_no_cache_dir_disables_query_cache PASSED
test_pipeline_l1w.py::test_with_stage_helper_is_what_pipeline_uses_for_errors PASSED
test_pipeline_l1w_cache.py (6건) PASSED
test_pipeline_l1w_llm.py (5건) PASSED
test_pipeline_l1w_live.py::test_demo_plan_v1_twice_with_query_cache SKIPPED (NEUMANN_LIVE_TESTS=1과 키가 있을 때만)
======================== 36 passed, 1 skipped in 1.16s ========================

$ python -m pytest tests/e3 -q
342 passed, 12 skipped in 6.43s          (skip 12 = 실제 API 테스트)
```

| 요구 | 테스트 |
|---|---|
| 적합성 부적합이면 0장 | `test_unfit_stops_before_search_with_zero_cards`(가짜 모듈: 카드·유사 연구 0, 이후 단계 전부 skipped, **LLM 호출 0건**), `test_real_fitness_recipe_is_not_analyzed`(실제 E3-L1c 모듈 + mock: 호출은 `fitness` 1건뿐), `test_unfit_result_matches_old_recipe_handling`(옛 처리와 새 처리가 같은 꼴: 0장, `입력이 연구계획서가 아니다(mock 판단: …`, suitability False, extract skipped) |
| 단계마다 실패하면 그 단계만 강등 | `test_llm_failure_degrades_only_that_stage[×3]`(mock 강제 timeout: 그 단계만 degraded, 나머지 ok, 카드는 그대로), `test_exception_in_a_v1_stage_is_contained[×3]`(예외: 그 단계만 error, 예외 원문·경로는 결과에 없음), `test_fitness_exception_degrades_only_that_stage`, `test_real_fitness_failure_falls_back_to_rule_only_there`(적합성 timeout이면 규칙 판정으로 degraded, 나머지 ok), `test_provider_off_marks_v1_stages_rule_or_unverified`(off면 v1은 rule 또는 미검증, 의미 판정을 규칙으로 흉내 내지 않음) |
| 생성 주체 추정 금지 | `test_provider_generator_refuses_to_guess`, `test_llm_call_for_uses_provider_attribute_and_refuses_unknown`(모르는 provider는 호출하지 않음), `test_provider_generator_attribute_follows_name_mapping` |
| 검색어 캐시 | `test_query_cache_gives_same_similar_works_and_is_reported`(2회차: 같은 검색어·같은 유사 연구, query_axes 호출 1회, 결과·manifest·단계에 적중 표시), `test_pipeline_l1w_cache.py`(저장·재사용, 다른 계획서·모델이면 미적중, mock·규칙 결과는 저장 안 함, 깨진 항목 무시, 키 구성) |
| 시간 상한·기록 | `test_timings_total_and_limits_recorded`, `test_llm_calls_carry_task_limits_and_efforts`(환경변수 상한이 LLMCall과 manifest에 반영), `test_v1_task_limits_can_be_overridden` |
| 근거 연결·계약·화면 | `test_linkage_checker_passes_with_v1_results`(`eval.linkage.check_result` 통과, 연결률 1.0), `jsonschema`로 `premortem_response` 계약 확인, `test_ui_view_accepts_v1_result`(E4 `build_ui_view`에 review·checklist가 채워짐) |

### 2. 실서버와 같은 조건으로 데모 plan.md를 두 번 실행(실제 astra)

**하지 않았다. PM 지시(실제 OpenAI 호출 전면 동결)에 따라 PM 승인 뒤에 한다.** 이 세션의 실제 API 호출은 0회다.

승인되면 다음을 돌린다. 서버와 같은 호출(`run_premortem(plan_text)`, E2 실색인, 설정 provider, `data/cache`)이다.

```
NEUMANN_LIVE_TESTS=1 PYTHONPATH="src;." python -m pytest tests/e3/test_pipeline_l1w_live.py -q -s
```

검사 내용:

- 1회차: 카드가 1장 이상이고 전부 astra다. 예상 심사평은 astra·ok이고 약점 문장마다 근거가 있다. 체크리스트는 모든 카드를 덮는다. `verification.semantic`은 astra로 모든 카드를 판정한다. `check_result`가 통과하고 연결률은 1.0이다.
- 2회차: 검색어 캐시가 적중하고, 검색어와 유사 연구가 1회차와 같다. `check_result`가 통과한다.

**대신 한 측정: 실제 E2 색인 + mock(API 호출 없음).** 스크래치 스크립트다. 임베딩은 CPU로 돌렸고(8010 서버가 쓰는 GPU를 건드리지 않으려고) 캐시는 스크래치 폴더에 뒀다.

- A: `MockProvider`
- B1·B2: 시험용 대역 `AstraLike`. `MockProvider`의 이름만 `openai`로 바꾼 것이라 캐시 대상이 되고, 표기가 astra로 나온다. **실제 astra 결과가 아니다.**

```
=== A mock + 실색인 ===   status degraded(mock) | total_s 14.66(bge-m3 CPU 첫 로드 포함) | backend neumann.index.search:search
  fitness ok(fit by mock) · query_axes ok · search ok 14.506s(상위 0.569) · extract ok · synthesize ok · verify 13/13
  expected_review ok(mock 통과 6/6) · checklist ok(3항목) · semantic_validate ok(cards_match 3, actions_match 3)
  linkage passed=True rate=1.0 cards_ok=3/3 links=13/13
  stage_limits_s {'fitness': 30.0, 'query_axes': 45.0, 'expected_review': 90.0, 'checklist': 90.0, 'semantic_validate': 90.0}
=== B1 대역 + 실색인 + 캐시(1회차) ===  query_cache {'enabled': True, 'hit': False, 'stored': True}  linkage passed=True 13/13
=== B2 대역 + 실색인 + 캐시(2회차) ===  query_axes: 검색어 캐시 적중(astra:test-double, 2026-09-30T10:40:59+00:00 생성)
  query_cache {'enabled': True, 'hit': True, 'stored': False, ...}  linkage passed=True 13/13
query_axes 호출 수(대역): 1 · same similar works: True · same queries: True
  similar_works(1·2회차 동일) researcharcade_hf:7bAjVh3CG3, 4lqA5EuieJ, bFHR8hNk4I, Abr7dU98ME, fyCPspuM5L, nTwb2vBLOV, pXN8T5RwNN, sTQC4TeYo1, qaJxPhkYtD, 9tKC0YM8sX
negative_recipe(mock): cards 0 | 입력이 연구계획서가 아니다(mock 판단: …); 검색 안 함 | fitness ok, 이후 9단계 skipped
```

### 3. `python scripts/verify.py`

```
$ python scripts/verify.py        (main c4679f9 병합 뒤)
950 passed, 25 skipped in 72.92s (0:01:12)
보안: 파일 326개
계약: 2개
테스트: 통과
verify 통과
```

참고: main 234b0f3을 병합한 직후에는 `tests/e4/test_export.py::test_degraded_stages_and_rule_cards_are_labelled_honestly` 1건이 실패했다. 원인은 main 쪽이다. `export.py`의 표시 문구는 바뀌었는데 테스트는 그대로였다. main c4679f9가 이 테스트를 고쳤고, 그것을 병합한 뒤 통과했다. 이 과제는 두 파일을 고치지 않았다.

## 바꾼 파일

`src/neumann/pipeline.py`, `src/neumann/llm.py`, `src/neumann/analyze/queries.py`, `src/neumann/analyze/mock_responders.py`, `tests/e3/test_pipeline_l1w.py`, `tests/e3/test_pipeline_l1w_cache.py`, `tests/e3/test_pipeline_l1w_llm.py`, `tests/e3/test_pipeline_l1w_live.py`, `tests/e3/test_pipeline.py`, `tests/e3/test_security.py`, `tests/e3/test_live_astra.py`, `docs/reports/E3-L1w.md`

커밋: 648b048(llm 생성 주체·상한·mock 응답) · bda4d21(검색어 캐시) · dee12b3(파이프라인 연결) · b42e39b(실제 API 시험 파일) · 이 보고서

## 결정 (스펙이 모호해서 고른 것)

- **적합성과 astra ① 판정이 다를 때.** 적합성 판정이 있으면 그것을 기준으로 삼는다.
  - `fit`이면 astra ①이 "연구 아님"이라고 해도 진행한다.
  - `uncertain`이면 astra ①도 "연구 아님"일 때만 멈추고, 사유에 "적합성 판정 보류"를 덧붙인다(과잉 거절 방지와 조리법 차단 사이의 절충).
  - 적합성 판정이 없으면(모듈 없음·오류) 예전처럼 astra ①만 본다.
- **적합성이 unfit이면 astra ①을 부르지 않는다.** 검색 전에 끝내므로 조리법 입력의 LLM 호출이 2회에서 1회로 준다. 사유 끝이 "검색 점수" 대신 "검색 안 함"이 된다. 나머지 꼴(0장, `입력이 연구계획서가 아니다(<주체> 판단: …)`, suitability False)은 같다.
- **어댑터는 `review.provider_llm_call` 하나를 네 단계에 쓴다.** task 이름은 `fitness`·`expected_review`·`checklist`·`semantic_validate`로, `TASK_DEFAULTS`와 mock 응답 키에 맞췄다. E3-L1c 보고서가 제안한 `input_fitness` 대신 `fitness`를 썼다. 생성 주체는 `generator=provider_generator(llm)`로 명시해서 넘긴다.
- **생성 주체 이름 `astra` 유지.** main 234b0f3에서 제품 기본 모델이 `gpt-6.1-sol`로 바뀌었지만, decisions.md(19:38)대로 `astra`는 계약 이름("제품 LLM")이다. 실제 모델 id는 각 결과의 `model`과 `manifest.llm_model`에 남는다.
- **`cache_dir` 인자는 이제 캐시 뿌리다.** 기본값은 `data/cache`이고, 추출은 `extract/`, 검색어는 `queries/`에 둔다. 예전 기본값 `data/cache/extract`와 같은 폴더를 쓰므로 기존 추출 캐시는 그대로 적중한다. 이 인자를 명시해서 넘기는 호출부는 테스트의 `None`뿐이었다.
- **검색어 캐시에 저장하는 것은 astra 응답 전체다**(검색어·축·분야·연구계획서 판정과 사유·근거 줄). 적중했을 때 결과를 똑같이 되살리려고 전체를 둔다. 계획서 본문은 저장하지 않는다. 사유 문장은 이미 PII를 가린 계획서에서 나온다. mock·규칙 결과는 저장하지 않는다.
- **v1 단계의 phase는 파이프라인 기준으로 덮어쓴다.** 모듈은 `input`·`analyze`를 쓰지만, 화면 묶음이 대문자 단계명(`INPUT`·`REVIEW`·`ACTION`, `api/main.py` STAGE_MODULES)이라서다.
- **v1 단계는 순서대로 돈다**(심사평 → 체크리스트 → 검증). 실측 지연(E3-L1a·b)으로 잡으면 12.5 + 16.4 + 12.4초, 약 41초가 늘어난다. 심사평을 체크리스트·검증과 병렬로 돌리면 약 12초를 줄일 수 있다. 다음 과제로 넘긴다.
- **단계 상한은 호출 단위로 건다.** 체크리스트·검증은 3장씩 묶어 최대 3개를 병렬로 보낸다. 카드가 8장 이하면 묶음이 한 번에 모두 나가므로 단계 시간도 대략 호출 상한 하나(90초) 안이다. 파이프라인에 벽시계 강제 중단은 넣지 않았다.
- **모듈이 `llm_failed`처럼 분류만 남기면** 어댑터의 `last_error`(예: `호출 실패(시간 초과) [timeout]`, 비밀값 없음)를 단계 detail에 "마지막 호출:"로 덧붙인다.
- **기존 E3 테스트는 최소로 고쳤다**(`test_pipeline.py`·`test_security.py`·`test_live_astra.py`). 단계 목록을 10개로 늘리고, 적합성 모듈이 없을 때만 fitness의 skipped를 허용했다.

## 못 한 것

- **완료 기준 2(실제 astra로 plan.md 두 번 실행)는 PM 승인 뒤에 한다.** 시험 파일과 명령은 준비돼 있다(`tests/e3/test_pipeline_l1w_live.py`). 대신 실제 색인 + mock으로 연결·연결률·캐시 적중·같은 유사 연구를 쟀다(위 측정).
- `test_live_astra.py`·`test_fitness_live.py`·`test_checklist_live.py` 같은 기존 실제 API 시험도 같은 이유로 돌리지 않았다.

## 다음 과제에 넘길 것

- 승인되면 위 실제 시험을 돌리고, 실측 단계별 시간·총 시간(v0는 70~86초, v1은 약 +41초로 예상)과 토큰을 이 보고서에 더한다.
- 예상 심사평을 체크리스트→검증과 병렬로 돌려 약 12초를 줄인다.
- E3-L1c가 권장한 `pii.plan_document_from_text`(전화·주민번호 강화 마스킹)를 `plan_normalize`에 연결한다. 지금은 E3-L0의 `mask_extra_pii`를 쓴다.
- E4: `plan_checks.fitness`의 `notice`·`followup_questions`(uncertain일 때)와 `query_axes` 캐시 적중을 화면에 표시한다.
