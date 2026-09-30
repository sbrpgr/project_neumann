# E3-L1e 보고서 — 근거 없는 체크리스트 항목·심사평 문장 차단(근거 게이트)

- 빌더: Claude Opus 5.5 · 브랜치 `task/E3-L1e`(main `1864d70` 기준) · 2026-09-30
- 모든 명령은 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK` 없음으로 돌렸다. **OpenAI 호출 0회**, 라이브 재실행 없음.
- 배경: v1 라이브 E2E(E5-L1e2e, gpt-6.1-sol, 8020)에서 protein_ligand_affinity C3, neural_operator_weather C6 항목이
  근거 번호 없이 화면에 나왔다(카드 연결만 있음). `checklist.py`는 행동 근거가 비거나 풀 밖 id만 있어도 항목을 그대로 두었다.
- 과제 중 PM 추가 요구(재개 지시): 체크리스트만이 아니라 **예상 심사평·2차 검증에도 같은 게이트**를 두고,
  화면에 "근거 없는 항목 k개 제외"를 표시한다. 기본값은 폐기 + 폐기 수 표기.

## 고른 처리 방식: (a) 폐기 + 폐기 수 표기

| 선택지 | 판단 |
|---|---|
| **(a) 폐기** | **기본값으로 골랐다.** 근거 없는 문장이 화면·결과에 남지 않는다. 폐기 수는 단계 기록(status)·결과·화면에 남아 숨기지 않는다. 비용·시간이 늘지 않는다. |
| (b) 카드 근거 승계 | 쓰지 않았다. 모델이 근거로 대지 않은 발췌를 코드가 붙이면, 필드로 구분해도 "이 행동의 근거"처럼 읽힌다. 카드 근거가 그 행동을 실제로 뒷받침하는지 아무도 확인하지 않은 연결이 생긴다. 근거 정직성 규칙(근거 없는 문장을 내보내지 않는다)을 연결 조작으로 우회하는 셈이다. |
| (c) 1회 재요청 | 쓰지 않았다(지시대로 기본값 금지). 호출과 시간이 늘고, 재요청 결과도 같은 게이트를 다시 거쳐야 한다. |

- 한 행동이 좋은 id와 나쁜 id를 섞어 댔으면 나쁜 id만 빼고(`dropped.evidence`, 기존 동작) 항목은 남긴다. 남은 근거가 그 카드의 근거이므로 뒷받침이 있다. **남은 근거가 하나도 없을 때만** 항목을 폐기한다.
- 한 카드의 LLM 행동이 전부 근거 없음으로 빠지면, 그 카드만 기존 비상 규칙 경로로 대신한다. 이때 `generator="rule"`, `fallback_reason="llm_no_grounded_action"`이고 단계는 degraded다. 화면에는 "규칙 합성 · 비상 경로"로 나온다. 규칙 문구는 LLM 문장이 아니고, 카드 근거에 연결되며, 표기된다(E3-L1b 규칙: "행동이 전부 무효면 그 카드만 규칙 경로"). 버려진 LLM 문구는 되살리지 않는다.
- 게이트 폐기만으로는 단계를 강등하지 않는다(ok 유지). 심사평 근거 게이트가 문장을 빼도 ok인 것과 맞췄다. 라이브에서 두 번에 한 번꼴로 생기는 일로 결과 전체에 "일부 단계 강등"을 띄우지 않기 위해서다. 대신 수는 counts, detail, 결과, 화면에 남는다.

## 층별 게이트(모두 같은 검사 `gate.evidence_link_problem`)

검사 내용: 근거 excerpt id가 1개 이상 있어야 한다. 전부 결과 `evidence` 안에 있어야 한다. 연결 카드가 결과에 있어야 한다. 근거가 전부 그 카드의 근거 안에 있어야 한다. 카드를 달지 않은 심사평 문장은 근거마다 어느 위험카드의 근거여야 한다(이번에 조였다).

실패 사유는 `missing_citation` · `unknown_excerpt_id` · `unknown_card_id` · `excerpt_card_mismatch`(`gate.NO_EVIDENCE_REASONS`)다.

| 층 | 어디 | 처리 | 수 기록 |
|---|---|---|---|
| 체크리스트 생성 직후 | `checklist._clean_actions`에 더해, 규칙 항목까지 전부 `gate_checklist_items`로 한 번 더(번호는 거른 뒤 C1…) | 폐기 | 단계 counts `items_dropped_no_evidence`, detail "근거 없는 항목 k개 제외", `result.verification["checklist_evidence"]`(gate·policy=drop·dropped·reasons·dropped_detail) |
| 2차 검증 | `validate.validate_cards`가 판정 전에 같은 게이트로 거르고, 근거 없는 항목은 모델에 보내지 않는다. `apply_validation`이 내보낼 체크리스트를 다시 걸러 뺀다 | 폐기(틀림 강등과 달리 삭제) | `semantic.counts.actions_no_evidence`, `evidence_gate`, `dropped_actions`, 폐기가 있으면 degraded + notice. 정상 흐름이면 0이다. 0이 아니면 앞 게이트를 우회한 항목이 있다는 뜻이다 |
| 예상 심사평 | 기존 `gate_sentences`(생성 게이트)가 이제 공용 검사를 쓴다. 전부 떨어지면 기존 규칙 합성 경로를 탄다 | 폐기 | `audit.no_evidence`, 단계 counts `no_evidence`, detail "근거 없는 문장 k개 제외" |
| 화면(view) | 근거 번호로 풀리지 않는 체크리스트 항목은 내보내지 않는다(심사평 문장은 원래 그랬다) | 폐기 | `checklist_audit`{shown, excluded, by_stage{checklist, semantic_validate, view}, note}, `review.audit.no_evidence`·`note`, `_status.dropped.checklist_items_without_evidence` |

- 2차 검증은 심사평과 **병렬**로 돈다(E3-L1y: `semantic_validate`는 `checklist`에만 의존한다). 그래서 2차 검증이 심사평을 고치면 순차·병렬 결과가 달라진다. 심사평 문장은 자기 생성 게이트와 화면 게이트가 맡는다(결정 2).
- 체크리스트 프롬프트: `evidence_ids`를 "0~3개"에서 "1~3개"로 바꾸고 "그 카드의 근거로 뒷받침할 수 없는 행동은 쓰지 않는다(근거 id가 없는 행동은 버려진다)"를 넣었다. 스키마에 `minItems:1`은 넣지 않았다. 억지로 아무 id나 고르게 만드는 것보다 모델이 그 행동을 빼는 편이 정직하기 때문이다(결정 3).

## 화면

`index.html`은 기존 줄을 고치지 않고 새 줄 4개만 넣었다(`var check = …` 바로 뒤). view의 `note`가 있을 때만 체크리스트 절 끝과 심사평 감사 카드 위에 다음 문구가 나온다.

> 근거 없는 항목 k개 제외 (근거 번호 없음·연결 카드의 근거 밖)

폐기된 문구는 view에 싣지 않고 수만 싣는다.

- `docs/reports/E3-L1e_check.png`: 체크리스트 2행이 모두 근거 번호 `#2`·`#5`를 달고 있다. 아래에 "근거 없는 항목 1개 제외"가 있다.
- `docs/reports/E3-L1e_review.png`: 심사평 문장마다 근거 번호가 있다. 감사 카드 위에 "근거 없는 항목 1개 제외"가 있다.
- 두 장 모두 가짜 뷰다(fixture + 가짜 응답, mock 표기, 샘플 표시). 서버는 mock provider·키 없이 8163에 띄웠다가 껐다.

## 완료 기준별 명령·출력

환경: `NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." PYTHONUTF8=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`, `NEUMANN_LIVE_LLM_OK` 해제.

### 1·2·3·4. mock 테스트(근거 빈 항목·없는 id·다른 카드 id·전부 빔·정상, 2차 검증, 심사평, 화면)

```
$ python -m pytest tests/e3/test_evidence_gate_l1e.py tests/e3/test_evidence_gate_view_l1e.py -v
test_ungrounded_action_is_dropped_and_counted[empty] PASSED
test_ungrounded_action_is_dropped_and_counted[unknown_id] PASSED
test_ungrounded_action_is_dropped_and_counted[other_card_id] PASSED
test_ungrounded_action_is_dropped_and_counted[unknown_and_other] PASSED
test_all_actions_ungrounded_fall_back_to_labeled_rule_per_card PASSED      # 전부 비었을 때
test_only_the_card_with_all_ungrounded_actions_falls_back PASSED
test_normal_checklist_drops_nothing PASSED                                  # 정상
test_gate_function_rejects_every_ungrounded_shape PASSED
test_prompt_asks_for_at_least_one_evidence_id PASSED
test_invariant_holds_for_mixed_bad_responses[0..5] PASSED (6)
test_second_validation_catches_items_that_bypassed_the_checklist_gate PASSED
test_second_validation_passes_normal_checklist_unchanged PASSED
test_apply_validation_regates_checklist_it_is_given PASSED
test_review_sentences_without_evidence_never_reach_output PASSED
test_review_all_ungrounded_falls_back_to_rule_and_every_sentence_is_grounded PASSED
test_view_shows_excluded_count_and_never_shows_ungrounded_items PASSED
test_view_normal_checklist_has_zero_excluded_and_no_note PASSED
test_view_review_audit_carries_excluded_note PASSED
test_excluded_note_renders_in_browser SKIPPED                               # NEUMANN_UI_TESTS=1일 때만
23 passed, 1 skipped in 0.92s

$ NEUMANN_UI_TESTS=1 NEUMANN_UI_SHOTS_OUT=docs/reports python -m pytest tests/e3/test_evidence_gate_view_l1e.py -k browser
1 passed in 10.92s        # 실제 index.html: #ckExcluded·#revExcluded 문구, 행마다 근거 번호, 폐기 문구 없음, 콘솔 오류 0
```

기존 테스트도 고쳤다(`tests/e3/test_checklist.py`의 가짜 응답). 행동 대부분이 `evidence_ids: []`였는데, 이제 그런 행동은 버려진다. 그 테스트들은 줄 번호·길이·중복을 보는 것이라 가짜 행동에 카드 근거를 달았다. 판정 내용은 바꾸지 않았다. `test_review.py`의 단계 counts 기대값에는 `no_evidence: 2`를 더했다. `test_gate.py`에는 공용 검사와 "카드 밖 발췌" 테스트를 더했다.

### 변이 검사(검사가 실제로 잡는지)

게이트를 하나씩 끄고 돌린 뒤 원본을 되돌렸다. 되돌린 뒤 `git status`는 깨끗했다.

```
M1 체크리스트 두 게이트 끔        → test_evidence_gate_l1e.py 12 failed, 8 passed
M2 2차 검증 게이트 끔            → 2 failed, 18 passed
M3 화면 게이트 끔                → test_evidence_gate_view_l1e.py 1 failed
M4 공용 검사의 다른 카드 근거 검사 끔 → gate·l1e 6 failed, 50 passed
```

### mock 파이프라인 한 번(fixture 백엔드, 새 필드 확인)

```
manifest provider mock cards 1 items 1
all items grounded: True
checklist stage: ok 0 None
semantic: ok 0
review: ok {'gen': 2, 'pass': 2, 'drop': 0, 'no_evidence': 0}
verification.checklist_evidence: {'gate': 'checklist_evidence@v1', 'policy': 'drop', 'items': 1, 'dropped': 0, 'reasons': {}}
view checklist_audit: {'shown': 1, 'excluded': 0, 'by_stage': {'checklist': 0, 'semantic_validate': 0, 'view': 0}, 'note': ''} review note: ''
```

### 5. 계약(추가만)

`contracts/ui_view.schema.json`에 다음을 추가했다. 모두 선택 필드이고, 기존 필드·required는 그대로다.

- 최상위 `checklist_audit`
- `review.audit.no_evidence`·`note`

`premortem_response.schema.json`은 바꾸지 않았다. `checklist` 항목과 `verification`은 이미 자유 형식(additionalProperties: true)이다.

### verify

```
$ NEUMANN_LLM_PROVIDER=mock python scripts/verify.py
1276 passed, 28 skipped in 189.26s (0:03:09)
보안: 파일 416개
계약: 2개
테스트: 통과
verify 통과
```

- main과 합칠 때 충돌이 있는지 확인했다(`git merge-tree --write-tree main HEAD`). 충돌이 없다. main에는 그 뒤 E4-L2d의 index.html 변경이 들어왔지만 겹치지 않는다.

## 바꾼 파일

| 파일 | 내용 | 소유 |
|---|---|---|
| `src/neumann/analyze/gate.py` | `evidence_link_problem`(공용 검사), `NO_EVIDENCE_REASONS`, `count_no_evidence`, audit `no_evidence`. 카드 없는 문장의 카드 밖 발췌 차단 | E3 |
| `src/neumann/analyze/checklist.py` | 생성 직후 게이트와 마지막 게이트(`gate_checklist_items`), `evidence_audit`, 단계 counts·detail, `verification.checklist_evidence`, 프롬프트 1~3개 | E3 |
| `src/neumann/analyze/validate.py` | 2차 검증 같은 게이트(모델에 안 보냄·apply에서 뺌), counts·evidence_gate·dropped_actions·notice | E3 |
| `src/neumann/analyze/review.py` | audit `no_evidence`, 단계 counts·detail | E3 |
| `src/neumann/api/view.py` | 화면 게이트, `checklist_audit`, `review.audit.no_evidence·note` | E4(과제 지시로 최소 변경) |
| `src/neumann/webui/index.html` | 새 줄 4개(기존 줄 수정 없음) | E4(과제 지시로 최소 변경) |
| `contracts/ui_view.schema.json` | 선택 필드 추가 | PM(과제 지시 "계약은 추가만") |
| `tests/e3/test_evidence_gate_l1e.py`, `tests/e3/test_evidence_gate_view_l1e.py` | 새 테스트 | E3 |
| `tests/e3/test_checklist.py`, `test_review.py`, `test_gate.py` | 위 "기존 테스트도 고쳤다" 참조 | E3 |
| `docs/reports/E3-L1e.md`, `E3-L1e_check.png`, `E3-L1e_review.png` | 보고서·스크린샷 | — |

새 패키지는 없다.

## 결정(스펙이 모호해서 고른 것)

1. **기본값은 (a) 폐기**다(위 표). 이 과제에는 승계나 재요청을 켜는 설정을 두지 않았다. 필요하면 PM이 따로 과제로 정한다.
2. **2차 검증이 거르는 대상은 체크리스트 항목**이다. 심사평은 2차 검증과 병렬로 돌아서, 2차 검증이 고치면 순차·병렬 결과가 달라진다(E3-L1y 불변). 심사평은 생성 게이트(공용 검사)와 화면 게이트 두 겹이다.
3. **프롬프트는 바꾸고 스키마 `minItems`는 넣지 않았다.** 스키마로 강제하면 모델이 아무 id나 골라 채울 수 있다. 그러면 근거처럼 보이는 연결이 생긴다. 이 판단은 라이브로 검증하지 않았다(API 0). 효과는 다음 승인 라이브에서 `items_dropped_no_evidence`로 잰다.
4. **게이트 폐기만으로는 단계를 ok로 둔다**(심사평 게이트와 같다). 규칙 대체가 생기면 기존대로 degraded다. 2차 검증에서 폐기가 생기면 degraded다(앞 게이트를 우회했다는 신호이기 때문).
5. **카드를 달지 않은 심사평 문장도 인용 발췌가 위험카드의 근거여야 한다.** 파이프라인의 `evidence`는 카드 근거만 남기므로 실제 동작은 같다. 기존 테스트는 모두 통과했다.
6. **view는 뺀 문구를 싣지 않고 수만 싣는다.** 결과 JSON의 `verification.checklist_evidence.dropped_detail`에는 감사용으로 문구(개인정보 가림·300자)와 사유가 남는다.

## 못 한 것 · 관찰

- **라이브 재확인 안 함**(지시: API 0, 재실행 금지). E5-L1e2e의 2건(C3·C6)이 이제 어떻게 나오는지는 다음 승인 라이브에서 확인한다. 기대 결과: 그 항목은 폐기되고 화면에 "근거 없는 항목 1개 제외"가 나오며 E5 판정은 PASS다.
- (PM 판단) 심사평 감사 카드는 기존 목업 설계대로 삭제된 문장을 **취소선과 사유 코드**로 보여 준다(`R.audit.dropped`, 스크린샷 `E3-L1e_review.png`의 `missing_citation`). "삭제됨" 표시가 붙은 감사 기록이지만, "근거 없는 문장은 출력하지 않는다"를 엄격히 읽으면 걸릴 수 있다. E4 화면 설계라 고치지 않았다. 체크리스트는 이렇게 문구를 보여 주지 않고 수만 보여 준다.
- `hasCheck`가 거짓이면(체크리스트가 0행이면) 체크리스트 절이 그려지지 않아 제외 문구도 보이지 않는다. 카드가 있으면 규칙 경로가 항목을 채우므로 실제로는 생기지 않는다.
- 기준선 실행에서 `tests/e3/test_pipeline_parallel_sim.py::test_simulated_parallel_is_faster_and_same`가 한 번 시간 초과로 실패했다(0.858s < 0.624s 기대, 다른 빌더들이 동시에 돌아 부하가 있었음). 코드를 바꾸기 전의 일이고, 마지막 verify에서는 통과했다. 시간 기반 테스트라 부하에 약하다.

## 다음 과제에 넘길 것

- (PM) 다음 승인 라이브 E2E(`tests/e2e/test_live.py --plans ai4s`)에서 확인할 것:
  - 체크리스트 단계 counts `items_dropped_no_evidence`
  - `verification.checklist_evidence.reasons`
  - 화면 `#ckExcluded`
- (E5) E2E 판정기가 `checklist_audit.excluded`·`review.audit.no_evidence`를 요약 줄에 기록하면 폐기율을 계획서별로 볼 수 있다.
- (E4) 심사평 감사 카드의 취소선 문장 표시를 유지할지 결정한다(위 관찰).
