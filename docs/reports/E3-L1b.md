# E3-L1b — 예방 체크리스트(astra) + 2차 의미검증 · 빌더 보고서

- 빌더: Claude Opus 5.5 · 브랜치 `task/E3-L1b` · 목표 50분
- 소유 파일만 고쳤다: `src/neumann/analyze/checklist.py`, `src/neumann/analyze/validate.py`, `tests/e3/test_checklist*.py`, `tests/e3/test_validate*.py`, 이 보고서

## 무엇을 했나

1. **`analyze/checklist.py`**: 카드마다 착수 전 예방 행동 1~3개를 만들고 계획서 **줄 번호**와 근거 카드 id·excerpt id에 연결한다.
   - `llm_call(schema, instructions, input, *, effort) -> dict | None`을 주입받는다(E3-L1a와 같은 모양). llm.py·pipeline.py는 건드리지 않았다.
   - 카드를 3장씩 묶어 호출하고(묶음이 여러 개면 최대 3개 동시), 모델은 `action`·`verify`·`plan_lines`·`evidence_ids`만 돌려준다. **인용문 필드는 없다.** 스키마는 OpenAI strict 모드 형식이고 card_id·excerpt id는 enum이다.
   - 코드가 다시 검사한다. 입력에 없는 card_id는 버린다. 없는 줄 번호(범위 밖, 1 미만, 빈 줄, 정수가 아닌 값)는 제거한다. 그 카드의 근거 풀 밖 excerpt id도 제거한다. 5자 미만이거나 300자 넘는 문구, 중복 문구는 버리고, 카드당 행동은 최대 3개다. 제거한 참조는 항목의 `dropped`에 남긴다. 행동이 가리킨 줄이 전부 무효면 카드가 인용한 줄로 잇고 `plan_lines_source="card"`로 표시한다.
   - **비상 규칙 경로**는 카드 단위로 돈다. 호출 실패(None, 예외, 모양 오류)이거나 응답에서 카드가 빠졌거나 행동이 전부 무효면, 그 카드만 카드 유형별 기본 문구(`RULE_ACTIONS`, R0~R9 각 2개, 직접 쓴 문구)로 대신한다. 이때 `generator="rule"`, `model=None`, `fallback_reason`(`llm_failed`, `llm_exception:<형>`, `llm_invalid_response`, `llm_missing_card`, `llm_no_valid_action`, `llm_unavailable`)을 남긴다.
   - **결정 로그 자리**: 항목마다 `decision`(None → 채택·보류·기각), `note`, `decided_at`, `decision_log`(이력). 결정은 `record_decision()`으로 기록한다. `decision_log()`는 평면 목록으로, `decision_entries()`는 E4 내보내기의 `DecisionEntry` 모양으로 꺼낸다.
   - 단계 기록 `checklist`는 규칙으로 대신한 카드가 있으면 degraded다. `with_stage()`가 결과 `status`도 degraded로 올려서 강등이 ok로 숨지 않는다.
2. **`analyze/validate.py`**: 2차 의미검증(GEN-2). 카드와 행동을 **따로** 판정한다.
   - 카드 판정: 해당 이유(why_applies.text)가 인용한 계획서 줄(원문과 함께 보냄)과 맞는가. `match`(맞음) · `weak`(약함) · `mismatch`(틀림).
   - 행동 판정: 행동이 연결된 계획서 줄에 실제로 적용되는가. 같은 세 등급이고, 카드 판정과 독립이다.
   - **틀림은 삭제하지 않고 강등 표시만 한다.** 표시 위치는 네 군데다: `result.verification["semantic"]`(카드·행동별 판정, `demoted_cards`, `demoted_actions`, 집계), 체크리스트 항목의 `card_verdict`와 `validation`, `notices` 한 줄, 단계 기록 `semantic_validate`. 카드·행동 수는 그대로다.
   - 규칙 층: 인용한 줄이 하나도 없거나 전부 없는 줄인 카드는 LLM이 '맞음'이라 해도 `weak`가 상한이다(`judge="rule"`). 없는 줄은 모델에 보내지 않는다.
   - 실패하면 그 묶음의 카드·행동을 `unverified`(미검증, `judge="none"`)로 남기고 단계를 degraded로 둔다. 의미 판정을 규칙으로 흉내 내지 않는다(옛 GEN-2의 `unverifiable` 원칙). 모델 응답에서 빠진 카드·행동, 남의 카드 밑에 넣은 item_id, enum 밖 판정은 무시하고 미검증으로 남긴다.
3. 테스트: 가짜 callable 27건과 실제 astra 2건(`NEUMANN_LIVE_TESTS=1`일 때만 돈다). E4 화면(`build_ui_view`)과 내보내기(`DecisionEntry`, `decision_log.json`) 호환 검사도 넣었다. 두 모듈이 main에 이미 있어서 `importorskip`으로 붙였다.

## 공개 함수 인터페이스 (파이프라인 연결용)

```python
from neumann.analyze.checklist import attach_checklist, build_checklist, record_decision, decision_log, decision_entries
from neumann.analyze.validate import attach_validation, validate_cards, apply_validation, card_verdicts

# llm_call(schema: dict, instructions: str, input: str, *, effort: str) -> dict | None
#   선택 속성 llm_call.generator("astra"|"mock"), llm_call.model → 항목 표기에 쓴다(없으면 astra/gpt-6-astra)

result = attach_checklist(result, plan, llm_call, effort="medium")   # result.checklist + stage "checklist"
result = attach_validation(result, plan, llm_call, effort="medium")  # verification["semantic"], 항목 판정, notices, stage "semantic_validate"
```

- `build_checklist(result, plan, llm_call, *, effort="medium", generator=None, model=None, stats=None) -> list[dict]` (과제 스펙 시그니처)
- `validate_cards(result, plan, llm_call, *, checklist=None, effort="medium", generator=None, model=None) -> dict`(보고서), `apply_validation(result, report) -> PremortemResult`(사본)
- 순서: 카드 → `attach_checklist` → `attach_validation`. 체크리스트 뒤에 검증해야 행동도 판정한다.
- 체크리스트 항목 키: `item_id`(C1…), `card_id`, `risk_code`, `subcode`, `action`, `verify`, `plan_lines`, `plan_lines_source`(llm|card|none), `evidence`, `dropped{plan_lines,evidence}`, `generator`(astra|mock|rule), `model`, `fallback_reason`, `card_verdict`, `validation{verdict,verdict_ko,reason,judge,demoted}`, `decision`, `note`, `decided_at`, `decision_log`
- **E3-L0 llm.py와 잇는 어댑터**(파이프라인 쪽, 이 과제에서는 만들지 않음). `task/E3-L0` 브랜치의 `llm.py`는 `provider.complete_json(LLMCall) -> LLMResult` 모양이라 한 겹 감싸야 한다:

```python
def as_llm_call(provider, task):
    def llm_call(schema, instructions, input, *, effort):
        r = provider.complete_json(LLMCall(task=task, instructions=instructions, payload=json.loads(input),
                                           schema=schema, schema_name=task, effort=effort,
                                           timeout_s=task_options(task)["timeout_s"]))
        return r.data if r.ok else None
    llm_call.generator, llm_call.model = generator_for(provider.name), provider.model
    return llm_call
# attach_checklist(res, plan, as_llm_call(llm, "checklist")); attach_validation(res, plan, as_llm_call(llm, "semantic_validate"))
```

## 완료 기준별 측정

### 1. 가짜 callable 테스트: 없는 줄 번호 참조 제거, 카드 기각 시 행동 유지, 실패 시 규칙 표기

```
$ python -m pytest tests/e3 -v      (mock, 실제 API 없음)
test_checklist.py::test_llm_path_links_actions_to_plan_lines_and_card_evidence PASSED
test_checklist.py::test_payload_and_schema_carry_ids_not_quotes PASSED
test_checklist.py::test_nonexistent_plan_lines_are_removed_and_recorded PASSED
test_checklist.py::test_foreign_evidence_unknown_card_and_missing_card PASSED
test_checklist.py::test_actions_capped_at_three_deduped_and_length_checked PASSED
test_checklist.py::test_failure_falls_back_to_rule_and_marks_generator[llm0-llm_failed] PASSED
test_checklist.py::test_failure_falls_back_to_rule_and_marks_generator[llm1-llm_exception:TimeoutError] PASSED
test_checklist.py::test_failure_falls_back_to_rule_and_marks_generator[llm2-llm_invalid_response] PASSED
test_checklist.py::test_failure_falls_back_to_rule_and_marks_generator[llm3-llm_invalid_response] PASSED
test_checklist.py::test_failure_falls_back_to_rule_and_marks_generator[None-llm_unavailable] PASSED
test_checklist.py::test_all_actions_invalid_falls_back_for_that_card_only PASSED
test_checklist.py::test_rule_actions_exist_for_every_risk_code PASSED
test_checklist.py::test_generator_label_follows_injection PASSED
test_checklist.py::test_attach_checklist_records_stage_and_keeps_contract PASSED
test_checklist.py::test_zero_cards_gives_empty_checklist_and_skipped_stage PASSED
test_checklist.py::test_decision_log_records_adopt_defer_reject PASSED
test_checklist.py::test_items_render_in_ui_view_checklist PASSED
test_checklist.py::test_decision_entries_feed_export_package PASSED
test_checklist.py::test_schema_without_excerpts_still_strict PASSED
test_checklist_live.py::test_live_astra_checklist_and_semantic_validation SKIPPED
test_checklist_live.py::test_live_astra_flags_card_whose_reason_does_not_match_cited_lines SKIPPED
test_validate_semantic.py::test_mismatch_card_is_demoted_but_not_deleted_and_its_actions_stay PASSED
test_validate_semantic.py::test_mismatch_action_is_flagged_not_deleted_independent_of_card PASSED
test_validate_semantic.py::test_failure_leaves_cards_unverified_and_degrades PASSED
test_validate_semantic.py::test_card_citing_nonexistent_lines_is_capped_at_weak PASSED
test_validate_semantic.py::test_payload_sends_cited_line_text_and_actions PASSED
test_validate_semantic.py::test_unknown_ids_and_invalid_verdicts_are_ignored PASSED
test_validate_semantic.py::test_zero_cards_skipped_and_contract_kept PASSED
test_validate_semantic.py::test_apply_is_pure_and_schema_enum PASSED
27 passed, 2 skipped
```

- 없는 줄 번호: `[16, 99, 29, 0, -3, 2(빈 줄), "17", True, 16]` → `[16]`만 남고 나머지 7개가 `dropped.plan_lines`에 기록된다. 전부 무효인 `[500]`은 카드 줄 `[16, 17]`로 잇고 `plan_lines_source="card"`로 표시한다(`test_nonexistent_plan_lines_are_removed_and_recorded`). 검증 쪽에서는 인용 줄이 `[99, 2]`뿐인 카드가 LLM 판정 '맞음'이어도 `weak`(judge=rule)로 떨어진다.
- 카드 기각 시 행동 유지: 카드 `mismatch` → `demoted_cards=[card-fx-leak]`이고, 카드 2장·항목 4개가 그대로 남는다. 그 카드 행동의 판정은 `match`, `demoted=False`다(`test_mismatch_card_is_demoted_but_not_deleted_and_its_actions_stay`). 반대 방향(카드는 맞음, 행동만 틀림)도 따로 검사했다.
- 실패 시 규칙 표기: None, 예외, 모양 오류, llm_call 없음의 다섯 경우 모두 `generator="rule"`, `model=None`, `fallback_reason`이 붙고, 문구는 `RULE_ACTIONS[R3]`/`[R2]`, 줄은 카드 줄이다. 단계는 `degraded`, impl은 `fallback:rule_actions`, 결과 `status="degraded"`. 검증 실패 때는 `unverified`/`judge=none`/degraded가 된다.

### 2. 실제 astra 1회 예시 (`NEUMANN_LIVE_TESTS=1`)

fixture 결과(plan.md, 카드 2장)에 openai SDK를 직접 부르는 임시 llm_call을 썼다. Responses API, `gpt-6-astra`, strict json_schema, `reasoning.effort=medium`, 받은 뒤 jsonschema로 로컬 재검증했다.

```
$ NEUMANN_LIVE_TESTS=1 python -m pytest tests/e3/test_checklist_live.py -s -q
== 호출 기록 ==
{"ok": true, "s": 16.4, "effort": "medium", "in_tok": 1404, "out_tok": 729}
{"ok": true, "s": 12.4, "effort": "medium", "in_tok": 2036, "out_tok": 484}
== 체크리스트 ==
C1 [card-fx-leak R3] gen=astra lines=[15, 17](llm) ev=1 dropped={'plan_lines': [], 'evidence': []} 행동판정=맞음
   행동: 중복 제거 절차를 두지 않는 방침을 수정하여 전해액 성분 표기와 조성 단위를 정규화하고, 동일 조성의 중복 기록 처리 규칙과 근접 조성의 유사도 기준을 분할 전에 확정한다
   확인: 데이터 처리 명세에 정규화 방법, 중복 기록 처리 규칙, 근접 조성 판정 기준이 기재되어 있으면 완료로 판단한다.
C2 [card-fx-leak R3] gen=astra lines=[16, 17, 21](llm) ev=3 dropped={'plan_lines': [], 'evidence': []} 행동판정=맞음
   행동: 항목별 무작위 80/10/10 분할을 동일·근접 조성 그룹 단위 분할로 변경하여 해당 비율을 목표로 배정하고, 그룹의 분할 간 중첩 여부와 실제 분할 비율을 점검하는 절차를 추가한다
   확인: 분할 코드에 그룹 중첩 검사와 실제 분할 비율 산출 기능이 구현되고, 동일·근접 조성을 포함한 점검용 입력에서 그룹이 여러 분할에 걸치지 않으면 완료로 판단한다.
C3 [card-fx-seed R2] gen=astra lines=[11, 21, 22](llm) ev=2 dropped={'plan_lines': [], 'evidence': []} 행동판정=맞음
   행동: 오차막대를 보고하지 않는 방침을 수정하여 제안 GNN과 baseline 2종을 동일한 고정 데이터 분할에서 사전에 정한 복수의 학습 시드로 반복 평가하고, holdout R2와 MAE의 시드별 값·평균·표준편차를 보고하도록 평가 계획을 보강한다
   확인: 평가 계획에 공통 데이터 분할, 반복 횟수와 시드 목록, 세 모델의 시드별 R2·MAE 및 평균·표준편차 보고 양식이 명시되어 있으면 완료로 판단한다.
C4 [card-fx-seed R2] gen=astra lines=[11, 21, 22, 27](llm) ev=1 dropped={'plan_lines': [], 'evidence': []} 행동판정=맞음
   행동: baseline 대비 정확도 향상이라는 기대 성과를 검증할 수 있도록 동일 시드별 제안 모델과 각 baseline의 R2·MAE 차이를 산출하고 그 차이의 불확실성과 개선 판단 기준을 사전에 정한다
   확인: 평가 명세에 모델 간 시드별 성능 차이의 집계 방식, 불확실성 산출 방법, 개선 판단 기준이 포함되어 있으면 완료로 판단한다.
== 카드 판정 ==
card-fx-leak: 맞음(match) judge=astra lines=[16, 17] — 인용된 16~17행은 무작위 80/10/10 분할과 근접 조성 중복 제거 절차의 부재를 명시하여 why의 내용을 직접 뒷받침한다.
card-fx-seed: 맞음(match) judge=astra lines=[22] — 인용된 22행은 오차막대를 보고하지 않고 절제 실험을 계획하지 않는다고 명시하여 why의 내용을 직접 뒷받침한다.
stage checklist: ok 16.404s  {'cards': 2, 'items': 4, 'items_llm': 4, 'items_rule': 0, 'cards_rule': 0, 'calls': 1, 'calls_failed': 0, 'plan_lines_dropped': 0, 'evidence_dropped': 0, 'actions_dropped': 0}
stage semantic_validate: ok 12.356s  {'cards_match': 2, 'cards_weak': 0, 'cards_mismatch': 0, 'cards_unverified': 0, 'actions_match': 4, 'actions_weak': 0, 'actions_mismatch': 0, 'actions_unverified': 0, 'calls': 1, 'calls_failed': 0}
1 passed
```

**음성 대조**(검증기가 기능을 하는지 확인). 같은 카드의 해당 이유를 "이미 스캐폴드 그룹 분할과 근사중복 제거를 한다"로 바꾸고 인용 줄을 연구 목표(5·6행)로 돌렸다. 행동은 대본으로 넣은 타당한 행동(16·17행) 하나다.

```
$ NEUMANN_LIVE_TESTS=1 python -m pytest tests/e3/test_checklist_live.py -s -q -k flags
음성 대조 카드: 틀림(mismatch) — 인용된 5~6행은 연구 목표만 설명하며, why의 그룹 분할 및 유사 중복 제거 주장은 무작위 분할과 별도 중복 제거 절차 부재를 명시한 16~17행과 반대다.
그 카드의 행동: 맞음(match) — 조성 그룹 단위 분할 규칙을 착수 전에 문서화하는 것은 16~17행의 무작위 분할과 유사 중복 항목에 따른 분할 오염을 예방하는 구체적인 행동이다.
호출: [{'ok': True, 's': 5.6, 'effort': 'medium', 'in_tok': 1280, 'out_tok': 161}]
1 passed
```

실제 astra에서도 카드는 틀림으로 강등되고, 그 카드의 타당한 행동은 맞음으로 남는다(불변식 "카드를 기각해도 타당한 행동은 남긴다").

### 3. `python scripts/verify.py`

최종 커밋 직전(main 병합 뒤, 보고서 포함 전 작업 트리):

```
$ python scripts/verify.py
210 passed, 4 skipped in 3.03s
보안: 파일 128개
계약: 2개
테스트: 통과
verify 통과
```

## 결정 (스펙이 모호해서 고른 것)

- **판정 값**: 코드·스키마 값은 영어 enum `match|weak|mismatch`(+`unverified`)로 두고 `verdict_ko`(맞음·약함·틀림·미검증)를 함께 싣는다. 모델 출력 안정성과 코드 비교 때문이다.
- **결정 값**: 목업과 같은 한국어 `채택|보류|기각`, 미결정은 `None`. E4 export가 한국어를 `adopt|hold|reject`로 받는다. E4 view는 `decision=None`을 '보류'로 보여 준다. 이 표시는 E4가 정할 일이다.
- **검증 실패 시 규칙 판정 없음**: 의미 판정은 규칙으로 흉내 내지 않고 `unverified`로 남긴다. 유일한 규칙 판정은 구조 사실인 "인용 줄 없음 → weak 상한"뿐이다.
- **규칙 카드도 검증한다**: 옛 GEN-2는 LLM 카드만 검증했지만, 비상 경로 카드의 해당 이유도 줄과 맞는지 보는 편이 정직하다고 판단했다. 판정 주체는 `judge`로 표기한다.
- **틀린 행동도 지우지 않는다**: 행동 `mismatch`는 `validation.demoted=True`와 `demoted_actions`로 표시만 한다. 화면이 흐리게 보여 줄지 숨길지는 E4 몫이다.
- **줄 연결이 전부 무효인 행동**은 버리지 않고 카드 인용 줄로 잇되 `plan_lines_source="card"`로 표시한다. 카드 줄도 없으면 `plan_lines=[]`, `"none"`이다.
- **수치·외래 개체 검사**(옛 GEN-1의 `_numeric_issues`·entity_guard)는 코드로 넣지 않고 지시문으로만 막았다. 행동 문구의 수치("5회 반복" 등)는 사실 주장이 아니라 제안이라, 코드로 깎으면 좋은 행동을 잃는다고 봤다.
- **추론 강도 기본값**: 둘 다 `medium`(계획서 §4 "합성·2차 검증은 높게"). 실측은 카드 2장 기준 체크리스트 16.4초, 검증 12.4초, 음성 대조 1장 5.6초다. 파이프라인은 `task_options("checklist"|"semantic_validate")`로 덮어쓸 수 있다.
- **기본 규칙 문구**는 택소노미의 예방 행동을 참고해 짧게 새로 썼다(기획서 원문을 복사하지 않음).

## 바꾼 파일

- `src/neumann/analyze/checklist.py` (신규)
- `src/neumann/analyze/validate.py` (신규)
- `tests/e3/test_checklist.py`, `tests/e3/test_validate_semantic.py`, `tests/e3/test_checklist_live.py` (신규)
- `docs/reports/E3-L1b.md` (이 보고서)

## 못 한 것

- 파이프라인(`run_premortem`) 배선. pipeline.py와 llm.py는 E3-L0 소유라 건드리지 않았다. 위 어댑터와 `attach_*` 두 줄이면 된다.
- E3-L0 `mock` provider용 응답 함수(`checklist`, `semantic_validate` 태스크). 지금 mock provider로 돌리면 응답 함수가 없어 `config_error` 실패가 되고, 체크리스트는 규칙 경로와 degraded로, 검증은 unverified로 간다. 정직한 표기이긴 하지만 데모용 mock이면 응답 함수를 더해야 한다.
- 실제 색인 결과(카드 3~8장, 묶음 여러 개 병렬)로 한 실측. 이번 실측은 fixture 카드 2장, 묶음 1개였다.

## 다음 과제에 넘길 것

- E3-L0/PM: 파이프라인에 `attach_checklist` → `attach_validation` 순서로 붙이고, llm 어댑터에 `generator`·`model` 속성을 달아 표기가 맞게 한다. `TASK_DEFAULTS`에 `checklist`·`semantic_validate`(effort medium, timeout 60~90초)를 추가한다.
- E4: 체크리스트 행에 `generator`(규칙이면 '규칙' 배지)와 `validation.verdict_ko`, 카드의 `verification.semantic` 판정(틀림=강등 표시)을 보여 준다. 결정은 `record_decision`/`decision_entries`로 export에 넘긴다.
- E5: `verification.semantic.counts`(맞음·약함·틀림·미검증)를 근거율 보고에 쓸 수 있다.
