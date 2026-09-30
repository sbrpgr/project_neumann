# E3-L1a 보고서 — 예상 심사평(astra) + 근거 게이트

- 빌더: claude-opus-5.5 · 브랜치 `task/E3-L1a` · 목표 50분
- 소유 파일만 만들었다: `src/neumann/analyze/review.py`, `src/neumann/analyze/gate.py`, `tests/e3/test_review.py`, `tests/e3/test_gate.py`, `tests/e3/test_review_live.py`
- `llm.py`·`pipeline.py`·다른 analyze 파일은 건드리지 않았다(E3-L0 몫). llm_call은 **주입**받는다.

## 무엇을 했나

1. **`analyze/review.py` — `generate_expected_review(result, llm_call)`**
   - 입력: `PremortemResult`(카드·근거·계획서). R0 제외, 근거가 결과 안에 있는 카드만, 점수 순 최대 8장·카드당 근거 4건.
   - 모델 입력: 계획서 줄(빈 줄 제외, 번호 포함)과 카드별 근거 원문. id는 별칭(`C1`·`E1`)으로 보낸다.
   - 출력 스키마(strict 호환): 절마다 문장 `{text, card_ids(enum), excerpt_ids(enum, 1~4), plan_lines}`. **인용문 필드 없음.** 지시문은 "따옴표 금지, 근거·계획서에 없는 숫자 금지, 다른 논문의 대상을 이 계획서로 끌어오기 금지"를 규칙으로 준다.
   - 코드가 별칭을 실제 id로 풀고 게이트를 돌린다. 통과한 문장만 남는다.
   - 비상 경로: llm_call 없음 / None 반환 / 예외 / 최상위 형식 오류 / 빈 출력 / 전부 게이트 탈락이면 **규칙 합성**. 약점 = 카드마다 `위험 유형: 카드 제목 (계획서 N행). 유사 연구 k편의 심사에서 같은 유형의 지적이 나왔다(예: “근거 원문 축자 인용”).`, 요청 = 위험 유형별 고정 문구 + 줄 번호. 강점은 규칙으로 판단할 수 없어서 만들지 않는다. `generator="rule"`, `status="degraded"`, `reason`에 사유. 규칙 문장도 같은 게이트를 지난다.
   - 카드 0장: 호출하지 않고 `status="skipped"`와 사유.
   - 반환 dict는 목업 `review` 구조(`contracts/ui_view.schema.json`의 review)를 그대로 통과한다. 여기에 generator·model·status·reason·attempts·elapsed_s를 더했다.
2. **`analyze/gate.py` — 근거 게이트(LLM 아님).** 문장마다 다음을 검사하고, 실패한 문장만 버린다. 사유별 건수와 `[사유, 문장]`(PII는 가림)을 남긴다.
   - `missing_citation`: excerpt id가 0개
   - `unknown_excerpt_id`·`unknown_card_id`: 결과 안에 없는 id
   - `excerpt_card_mismatch`: 인용한 excerpt가 인용한 카드의 근거가 아님
   - `unknown_plan_line`: 계획서 범위 밖 줄 번호
   - `quote_mismatch`: 따옴표(`"` `“”` `‘’` `「」` `『』` `«»`, 조건부 `'`) 안 문자열이 **인용한** 근거(또는 인용한 계획서 줄)와 글자 그대로 같지 않고 20자 이상 연속 부분문자열도 아님. 짝이 맞지 않는 따옴표도 여기에 든다
   - `fabricated_number`: 인용 밖 숫자가 인용 근거·계획서·인용 카드 제목/이유·집계값(유사 연구 수, 카드 근거·논문 수)·인용 줄 번호 어디에도 없음
   - `pii`, `empty_text`, `too_long`, `malformed`, `duplicate`
   - 통과 문장에 인용 위치 `quotes[{text, excerpt_id, start, end}]`를 붙인다. start·end는 **원문 오프셋**이다(`excerpt.start + 위치`).
3. `llm_call` 없이 E3-L0 provider를 바로 넘길 수 있게 **어댑터 `ProviderLLMCall`**(`provider.complete_json(LLMCall) -> LLMResult` 모양)을 review.py 안에 두었다. 호출 뒤 `generator`·`model`·`last_error`를 실제 provider 결과로 채워 정직하게 표기한다.

## 공개 인터페이스 (파이프라인 연결용)

```python
from neumann.analyze.review import generate_expected_review, attach_expected_review, expected_review_stage, provider_llm_call

# llm_call 규약: llm_call(schema: dict, instructions: str, input: str, *, effort: str) -> dict | None  (실패·시간 초과면 None)
review: dict = generate_expected_review(result, llm_call, effort="medium", generator=None, model=None)
stage: StageStatus = expected_review_stage(review)          # name="expected_review", ok/degraded/skipped, counts{gen,pass,drop}
result2: PremortemResult = attach_expected_review(result, llm_call, effort="medium")  # expected_review + 단계 기록, 규칙이면 status=degraded

# E3-L0 llm.py가 main에 들어온 뒤 (make_llm은 E3-L0의 것)
result2 = attach_expected_review(result, provider_llm_call(make_llm(settings), timeout_s=90))

from neumann.analyze.gate import gate_sentences, verify_expected_review
report = verify_expected_review(result.expected_review, result)   # 조립된 심사평을 결과에 대고 다시 검사(평가·API용)
```

- `generator` 표기는 (1) 명시 인자 (2) `llm_call.generator` 속성, 둘 중에서만 정한다(검증 뒤 수정, 아래 참고). 둘 다 없으면 **호출 전에 `ValueError`**다. `provider_llm_call`은 만들 때 provider 이름으로 속성을 단다(openai→astra, mock→mock, off→rule, 그 밖은 `generator=` 인자 필요). 어느 쪽에서 왔는지는 `generator_source`(`param`|`llm_call`|`fallback`)에 남긴다.
- 반환 dict 키: `version, generator, model, generator_source, effort, status(ok|degraded|skipped), reason, strength[], weakness[], request[], audit{gen,pass,drop,dropped[[사유,문장]],dropped_detail[],reasons{},gate,linked_rate}, attempts[], elapsed_s`
- 문장: `{"t": 문장, "c": [excerpt_id…], "cards": [card_id…], "plan_lines": [int…], "quotes": [{text, excerpt_id|plan_line, start, end}]}`. `c`는 excerpt id 문자열이다. 목업의 `#번호`로 바꾸는 일은 E4 뷰 변환이 한다.

## 완료 기준별 측정

### 1. 가짜 callable 테스트 — 통과

```
$ PYTHONPATH="src;." python -m pytest tests/e3/test_review.py tests/e3/test_gate.py -rA -q
PASSED tests/e3/test_review.py::test_llm_path_keeps_only_grounded_sentences          # 근거 없음·없는 id·인용 불일치·없는 수치 4건만 제거, 3문장 통과
PASSED tests/e3/test_review.py::test_llm_receives_schema_instructions_input_and_effort # strict 스키마, 인용 필드 없음, effort 전달
PASSED tests/e3/test_review.py::test_quotes_are_never_taken_from_model_but_verified
PASSED tests/e3/test_review.py::test_failure_falls_back_to_rule_and_says_so[None-llm_call_not_provided]
PASSED tests/e3/test_review.py::test_failure_falls_back_to_rule_and_says_so[call1-llm_call_failed]
PASSED tests/e3/test_review.py::test_failure_falls_back_to_rule_and_says_so[call2-llm_call_exception: TimeoutError]
PASSED tests/e3/test_review.py::test_failure_falls_back_to_rule_and_says_so[call3-llm_output_schema_invalid]
PASSED tests/e3/test_review.py::test_failure_falls_back_to_rule_and_says_so[call4-llm_empty_output]
PASSED tests/e3/test_review.py::test_all_llm_sentences_dropped_falls_back_and_keeps_audit
PASSED tests/e3/test_review.py::test_rule_sentences_quote_evidence_verbatim
PASSED tests/e3/test_review.py::test_rule_skips_quote_when_evidence_has_quote_marks
PASSED tests/e3/test_review.py::test_no_cards_skips_without_calling_llm
PASSED tests/e3/test_review.py::test_generator_label_comes_from_llm_call_or_settings
PASSED tests/e3/test_review.py::test_review_matches_ui_contract_and_result_contract
PASSED tests/e3/test_review.py::test_attach_records_stage_and_degrades_result_status
PASSED tests/e3/test_review.py::test_provider_adapter_passes_call_and_labels_honestly
PASSED tests/e3/test_gate.py::test_grounded_sentence_passes
PASSED tests/e3/test_gate.py::test_cards_are_derived_from_cited_excerpts
PASSED tests/e3/test_gate.py::test_sentence_without_evidence_is_dropped
PASSED tests/e3/test_gate.py::test_card_only_citation_is_not_enough
PASSED tests/e3/test_gate.py::test_unknown_excerpt_id_is_dropped
PASSED tests/e3/test_gate.py::test_unknown_card_id_is_dropped
PASSED tests/e3/test_gate.py::test_excerpt_from_other_card_is_dropped
PASSED tests/e3/test_gate.py::test_unknown_plan_line_is_dropped
PASSED tests/e3/test_gate.py::test_exact_quote_passes_and_points_to_source_offsets
PASSED tests/e3/test_gate.py::test_long_substring_quote_passes
PASSED tests/e3/test_gate.py::test_short_partial_quote_is_dropped
PASSED tests/e3/test_gate.py::test_altered_quote_is_dropped
PASSED tests/e3/test_gate.py::test_quote_from_uncited_excerpt_is_dropped
PASSED tests/e3/test_gate.py::test_paraphrase_in_korean_quotes_is_dropped
PASSED tests/e3/test_gate.py::test_unbalanced_quote_is_dropped
PASSED tests/e3/test_gate.py::test_quote_of_cited_plan_line_passes
PASSED tests/e3/test_gate.py::test_apostrophes_are_not_quotes
PASSED tests/e3/test_gate.py::test_fabricated_number_is_dropped
PASSED tests/e3/test_gate.py::test_numbers_from_plan_evidence_and_counts_pass
PASSED tests/e3/test_gate.py::test_number_inside_verified_quote_is_allowed
PASSED tests/e3/test_gate.py::test_extract_numbers_ignores_names_and_handles_thousands
PASSED tests/e3/test_gate.py::test_pii_sentence_is_dropped_and_redacted_in_log
PASSED tests/e3/test_gate.py::test_malformed_items_are_dropped
PASSED tests/e3/test_gate.py::test_duplicate_is_dropped_only_once
PASSED tests/e3/test_gate.py::test_only_failing_sentences_are_removed_and_audit_counts
PASSED tests/e3/test_gate.py::test_verify_expected_review_rechecks_assembled_dict
SKIPPED [1] tests\e3\test_review.py:303: could not import 'neumann.llm': No module named 'neumann.llm'
42 passed, 1 skipped
```

- 건너뛴 1건(`test_real_llm_mock_provider_reaches_review_path`)은 E3-L0 `llm.py`가 main에 들어오면 자동으로 돈다. 실제 `MockProvider`로 예상 심사평 경로가 호출되는지 보는 통합 테스트다(GEN-3 "함수만 있고 호출 안 됨" 함정 방지).
- 미리 확인해 둔 것: `task/E3-L0`의 `llm.py`를 저장소 밖 임시 폴더로 꺼내 모듈로 올려 어댑터를 돌렸다. 저장소에는 복사하지 않았다.
  ```
  strict problems: []                                  # E3-L0 check_strict_schema(내 스키마)
  neumann.llm expected_review mock mock-deterministic-v1 ok 1
  rule degraded llm_call_failed: off:none disabled (LLM provider 꺼짐)
  rule degraded llm_call_failed: mock:mock-deterministic-v1 schema_invalid (2건, 첫 오류 (root): 'weakness' is a required property)
  ```

### 2. fixture 결과 + 실제 astra 1회 — 통과

임시 llm_call(`tests/e3/test_review_live.py::OpenAIDirectCall`)이 openai SDK Responses API를 직접 부른다. strict json_schema로 요청하고, 받은 뒤 로컬에서 jsonschema로 다시 검사한다. `NEUMANN_LIVE_TESTS=1`일 때만 돈다.

```
$ NEUMANN_LIVE_TESTS=1 PYTHONPATH="src;." python -m pytest tests/e3/test_review_live.py -s -q
[E3-L1a live] usage= {'input_tokens': 1469, 'output_tokens': 467} last_error= None
generator=astra model=gpt-6-astra generator_source=llm_call effort=medium status=ok
weakness:
 - 유사 조성의 중복을 제거하지 않은 무작위 분할은 학습·시험 세트 간 정보 누출을 일으켜, 새로운 후보 조성에 대한 예측 성능을 과대평가할 위험이 있습니다.
   c=[ex_110f92f3599151f1, ex_ca5fa760fdb45841] cards=[card-fx-leak] plan_lines=[6,16,17,21]
 - 오차막대를 보고하지 않는 평가로는 기대하는 기준 모델 대비 성능 향상이 학습의 무작위 변동과 구별되는지 판단하기 어렵습니다.
   c=[ex_4b76d98627bb3f0c] cards=[card-fx-seed] plan_lines=[11,22,27]
request:
 - 분할 전에 조성 유사도에 따른 중복 판정 기준을 정하고, 중복 제거 또는 유사 조성의 그룹별 분할로 학습·시험 세트 간 누출을 방지하도록 평가 계획을 수정해 주십시오.
   c=[ex_110f92f3599151f1, ex_ca5fa760fdb45841] cards=[card-fx-leak] plan_lines=[16,17]
 - 제안 모델과 기준 모델을 여러 무작위 시드로 반복 학습하고, 평가 지표의 평균과 시드 간 변동을 나타내는 오차막대를 보고하도록 계획해 주십시오.
   c=[ex_fc88c26e0b31af5e, ex_4b76d98627bb3f0c] cards=[card-fx-seed] plan_lines=[11,21,22]
strength: (없음)
audit={"gen": 4, "pass": 4, "drop": 0, "dropped": [], "gate": "grounding@v1", "linked_rate": 1.0}
attempts=[{"generator": "astra", "model": "gpt-6-astra", "latency_s": 12.497, "gen": 4, "passed": 4, "dropped": 0, "outcome": "ok"}]
1 passed in 12.68s
```

(출력 JSON을 줄여서 옮겼다. 문장·id·수치는 원문 그대로다.) 테스트는 통과 문장을 `verify_expected_review`로 다시 검사해 폐기가 0인지도 확인한다. 한 번 호출에 약 12.5초, 입력 1,469 토큰, 출력 467 토큰이었다. strict 스키마의 `minItems`·`maxItems`·`minimum`·`maximum`을 API가 받아들였다.

### 3. `python scripts/verify.py` — 통과 (main 병합 뒤, 보고서 커밋 직전 실행)

main(`ed1d1a0`)을 병합한 뒤 실행했다(병합 커밋 `e0e564f`).

```
$ python scripts/verify.py
262 passed, 8 skipped in 5.18s
보안: 파일 137개
계약: 2개
테스트: 통과
verify 통과
```

## 결정 (스펙이 모호해서 고른 것)

- **근거가 있다는 것의 기준**: excerpt id가 1개 이상 있어야 한다. 카드 id만 달린 문장은 `missing_citation`으로 버린다. 목업은 문장마다 근거 번호를 표시하기 때문이다.
- **없는 id를 참조한 문장**: 그 id만 빼지 않고 문장 전체를 버린다. 없는 id는 지어낸 근거라는 신호로 본다.
- **카드와 excerpt가 어긋난 문장**(`excerpt_card_mismatch`): 인용한 카드의 근거가 아닌 excerpt를 달았으면 버린다. 카드를 안 달았으면 excerpt가 속한 카드를 코드가 채운다.
- **인용 대조의 대상**: 그 문장이 **인용한** 근거만 본다. 다른 근거와 맞는 인용은 잘못 귀속된 것으로 보고 버린다. 인용한 계획서 줄과 글자 그대로 같은 따옴표 인용은 허용한다. 계획서도 원문이기 때문이다. 끝 문장부호(`.`, `,` 등)만 다른 것은 같은 원문 부분문자열로 인정한다.
- **ASCII 작은따옴표**: 영어 축약형·소유격(`model's`, `reviewers'`)과 헷갈리지 않도록 경계 조건이 맞을 때만 인용으로 본다. `’`는 아포스트로피로도 쓰이므로 짝 검사에서 뺐다.
- **숫자 검사**를 게이트에 넣었다(`fabricated_number`). 과제 파일에는 없고, 계획서 §4 E3 불변식("근거 없는 수치는 그 문장만 뺀다")과 목업 audit 예시를 따랐다. 허용 범위는 인용 근거, 계획서 본문, 인용 카드 제목·이유, 인용 줄 번호다. 집계값은 개수 단위가 붙을 때만 허용한다. 계획서 본문에서 제목 줄과 줄 앞 번호 매기기는 뺀다(검증 뒤 좁힘, 아래 참고).
- **전부 탈락하면 규칙 합성으로 간다.** 옛 GEN-3는 이때 `review=None`이었다. 이번에는 LLM이 낸 문장이 전부 떨어지면 규칙 합성으로 대신하고 `reason=llm_all_sentences_dropped`로 남긴다. audit에는 LLM 폐기 기록도 함께 남긴다(`gen = pass + drop`이 항상 성립).
- **규칙 합성은 강점을 만들지 않는다.** 규칙으로는 강점을 판단할 근거가 없다.
- **모델 id는 별칭(C1·E1)으로 보낸다.** 16자리 16진 id를 베끼다 틀리는 일을 줄이고 토큰을 아끼려는 것이다. 별칭 enum 밖의 값은 그대로 두어 게이트가 버린다. 결과 안에 있는 실제 id를 그대로 돌려준 경우는 받아 준다.
- **effort 기본값은 `medium`**이다. 설정 키는 만들지 않았다(`config.py`·`.env.example`은 PM 소유). 파이프라인이 인자로 넘기면 된다. E3-L0 `task_options("expected_review")`를 쓰면 설정 키 `NEUMANN_LLM_EFFORT_EXPECTED_REVIEW`로도 조절할 수 있다.
- `c`에는 목업 `#번호` 대신 excerpt id 문자열을 넣었다. ui_view 계약이 문자열을 허용한다. 번호 매기기는 E4 뷰 변환 몫으로 둔다.

## 못 한 것

- **파이프라인 연결**은 하지 않았다. `run_premortem`에서 부르는 일은 E3-L0 또는 PM이 한다. 위 인터페이스로 한 줄이면 된다.
- 의미 검증(문장이 근거를 실제로 뒷받침하는지 보는 임베딩·LLM 2차 검증)은 넣지 않았다. id·인용·수치 같은 형식 검사만 한다. 2차 의미검증은 L2(E3-L1b) 범위다.
- 실제 E2 색인 결과로는 돌려 보지 않았다. 라이브 예시는 fixture 결과 1건이다.

## 다음에 넘길 것

- E3-L0 병합 뒤 `tests/e3/test_review.py::test_real_llm_mock_provider_reaches_review_path`가 건너뛰지 않고 도는지 확인한다.
- 파이프라인 연결: `result = attach_expected_review(result, provider_llm_call(llm, timeout_s=…), effort=task_options("expected_review")["effort"])`
- 연결 후 E3-L0 mock responder에 `expected_review` 응답 함수를 넣으면 오프라인 데모에서도 LLM 모양 경로가 돈다. 넣지 않으면 mock provider는 `config_error`로 실패하고, 이 모듈은 규칙 합성으로 가며 그렇게 표기한다.
- E4: 목업 `review` 렌더링은 `strength/weakness/request[].t`와 `c`(excerpt id → 근거 번호), `audit.gen/pass/drop/dropped`를 쓰면 된다. `generator`가 `rule`이면 화면에 "규칙 합성" 표기가 필요하다.
- 새 패키지는 필요 없었다(`jsonschema`·`openai`는 이미 의존성에 있다).

## 검증 뒤 수정 (PASS-조건부 → 병합 전 수정 1건 + 권고 반영)

검증 보고서(`docs/reports/E3-L1a.verify.md`, main)의 병합 전 수정 1과 한계 2·3의 일부를 반영했다.

1. **생성 주체를 설정에서 추정하지 않는다(병합 전 수정 1).**
   - `_resolve_generator`에서 설정(provider=openai → astra/gpt-6-astra) 경로를 없앴다. 생성 주체는 명시 인자 `generator=` 또는 callable의 `generator` 속성에서만 정한다.
   - 둘 다 없거나 값이 `astra|mock|rule` 밖이면 **호출 전에 `ValueError`**로 거부한다. 카드가 0장인 결과에도, `attach_expected_review`에도 똑같이 적용된다.
   - `model`도 인자 또는 `model` 속성에서만 정한다. 없으면 `None`이다(설정의 `gpt-6-astra`로 채우지 않는다).
   - `ProviderLLMCall`은 만들 때 `generator` 속성을 반드시 단다. provider 이름으로 정하고(openai→astra, mock→mock, off/none/disabled→rule), 모르는 이름이면 `generator=` 인자를 요구한다(`ValueError`). 호출 뒤에는 실제 `LLMResult.generator`로 갱신한다.
   - 테스트는 conftest의 mock 강제에 기대지 않는다. `monkeypatch.setenv("NEUMANN_LLM_PROVIDER", "openai")`와 `get_settings.cache_clear()`로 설정이 openai인 상태를 만든 뒤 검사한다.
     - 속성 없는 callable → `ValueError`이고 호출 0회
     - 속성 `mock|astra|rule` → 그 값 그대로 표기(`generator_source="llm_call"`, model 없음 → `None`)
     - 인자가 속성보다 우선하고, 틀린 값은 거부
     - 어댑터: provider 이름에서 표기, 실제 결과로 갱신, 모르는 이름 거부
2. **숫자 게이트를 좁혔다(한계 2).**
   - 계획서 숫자에서 제목 줄(`#`로 시작)과 줄 앞 번호 매기기(`1. `, `(2) `, `4) `, `- `)를 뺐다(`plan_fact_numbers`).
   - 집계값(유사 연구·근거·카드 수)은 개수 단위(편·건·개·장·곳)가 바로 붙을 때만 허용한다.
   - 이제 `5% 개선`(제목 `## 5.`), `3배`(유사 연구 수 3), `1단계`(제목 번호), `7편`은 떨어진다. `유사 연구 3편`, `근거 4건`, `카드 2장`, 계획서의 `12,000건`은 통과한다.
3. **인용 부호 2종 추가(한계 3 일부).** `《…》`와 전각 `＂…＂`도 인용으로 보고 대조한다. 규칙 합성의 인용 회피 문자 목록에도 넣었다.

```
$ PYTHONPATH="src;." python -m pytest tests/e3/ -q -rs      (tests/e3 전체: E3-L1a 파일)
56 passed, 2 skipped      # skip: neumann.llm 없음 1, NEUMANN_LIVE_TESTS 아님 1

# E3-L0 llm.py(task/E3-L0)를 저장소 밖 임시 폴더에서 올려 NEUMANN_LLM_PROVIDER=openai 상태로 어댑터 재확인
strict problems: []
neumann.llm expected_review mock mock-deterministic-v1 ok 1
rule degraded llm_call_failed: off:none disabled (LLM provider 꺼짐)
rule degraded llm_call_failed: mock:mock-deterministic-v1 schema_invalid (2건, 첫 오류 (root): 'weakness' is a required property)

$ python scripts/verify.py        (main 병합 뒤)
397 passed, 17 skipped in 11.08s
보안: 파일 169개
계약: 2개
테스트: 통과
verify 통과
```

- 라이브 astra는 다시 부르지 않았다(과제 허락은 1회). 앞의 라이브 결과 4문장에는 숫자가 없어서 숫자 게이트 변경의 영향을 받지 않는다.
- 남은 한계
  - 백틱 `` `…` ``은 식별자 표기와 겹쳐 인용으로 보지 않는다.
  - 문자에 붙은 숫자(`x30`)와 한글 수사(`삼십 퍼센트`)는 잡지 못한다.
  - 계획서 숫자는 아직 계획서 본문 전체에서 허용한다. 인용 줄로 좁히면 astra 폐기율이 오를 수 있어 보류했다.
  - LLM 경로의 `quotes`는 모델이 인용을 쓰지 않으면 비어 있다. 원문 인용 표시는 E4가 `c`의 excerpt id로 붙인다.
- **파이프라인 연결 시 주의:** `generate_expected_review`/`attach_expected_review`에 속성 없는 callable을 넘기면 `ValueError`다. `provider_llm_call(llm)`로 감싸거나 `generator=`를 넘긴다.

## 커밋

- `8c14807` [E3-L1a] 예상 심사평(astra, llm_call 주입) + 근거 게이트
- `e0e564f` main 병합, `74bbe79` 보고서
- 검증 뒤 수정 커밋(이 절)
