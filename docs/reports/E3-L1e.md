# E3-L1e 보고서 — 근거 없는 체크리스트 항목·심사평 문장 차단(근거 게이트)

## 남은 일 (Codex 마무리, 2026-09-30)

1. 최초 조건 반영 코드는 `0e50227`, 인수 HEAD는 `9e9d65a`, 1차 보고서 마무리는 `53e30c2`다. 이후 독립 검증에서 화면 심사평 혼합 참조·내보내기 생성 게이트 우회 2건이 확인돼 이번 후속에서 제품 코드와 회귀를 고쳤다.
2. 과거 전체 verify의 캐시 실패 1건을 포함한 대상 파일은 이번 실행에서 `7 passed in 1.17s`였다. 당시 실패 원인은 재현되지 않았으며 간헐 실패의 원인까지 규명한 것은 아니다.
3. 후속 최종 대상 회귀는 E3 근거 관문 + E4 화면·패널·내보내기 **186 passed, 1 skipped in 0.94s**다. skip은 별도 브라우저 실행에서 해소했고 **1 passed, 21 deselected in 19.10s**였다. 반례 새 테스트는 수정 전 5 failed/2 passed였고, 최종에는 정상 유지·혼합/다른 카드/없는 카드/형식 오류/개인정보 감사 가림·9파일 미누출을 검사한다.
4. **남은 병합 조건:** PM 직렬 큐 전체 `scripts/verify.py`, 별도 모델의 독립 재검증. 이번 빌더가 전체 verify나 후속 코드의 독립 검증 PASS를 주장하지 않는다. PM은 원문 과제지시문·검증보고서가 실제 누락된 것을 확인하고 이 절의 인수 기준과 main HANDOFF를 현재 기준으로 지정했다.
5. 실제 API 0회, main 코드/Git 쓰기 0회, 타인 프로세스·8010·8020·8099 조작 0회. 전용 브라우저 시험 서버는 8164에서 시험이 띄우고 종료했다. 코드 작업은 정지하고 PM에 커밋·대상 검증 결과·전체 검증 요청을 전달한다.

## 독립 검증 반례 2건 수정 (2026-09-30 23:5x)

- **화면 심사평:** 정상 excerpt id + ghost id를 섞으면 기존 `_build_review`가 ghost만 제거하고 문장을 표시했다. 다른 카드의 근거·없는 카드도 같은 경로를 통과했다. 이제 `review_evidence_problem`이 별칭 필드를 읽고 **공용 `evidence_link_problem`**으로 모든 발췌·카드 관계를 검사한다. 하나라도 실패하면 문장을 통째로 제외하며 실제 사유 코드·수와 개인정보를 가린 감사 기록을 남긴다. 화면에 있는 카드 근거를 색인하는 `EvidenceLinkIndex`는 불완전한 화면 입력도 공용 검사에 넣기 위한 내부 도구다. 근거 id 대신 `map`만 있는 문장도 실제 발췌 근거가 없어 제외한다.
- **내보내기:** 계약에 맞는 저장 결과가 생성 게이트를 우회하면 기존 리포트가 근거 없는 심사평/체크리스트를 그대로 옮겼다. 이제 `_make_ctx` 전에 `_gate_export_result`로 같은 근거 검사를 수행해 모든 9파일이 정리된 사본을 사용한다. 기존 감사 원문과 새 제외 원문은 문서에 넣지 않고 사유 코드·개수와 "분석 결과 아님" 경고만 남긴다. 제외한 체크리스트 항목에 붙은 결정 기록·메모도 내보내지 않는다. 입력 모델·기존 원본 감사 기록·정상 항목·generator/model은 그대로다. 규칙으로 재합성하거나 근거를 승계하지 않는다.
- **테스트 조정:** E4 기존 내보내기 표시 테스트의 가짜 항목 두 개에 실제 카드 근거를 추가했다. 기존 화면 테스트는 포괄 `no_evidence_in_view` 대신 공용 검사의 `missing_citation`·`unknown_excerpt_id`를 확인한다. 이전 표시/결정 기능 기대는 유지한다. 계약 파일·pipeline.py 변경은 없다.

최종 명령(환경과 `$TMP`는 다음 절과 같다):

```text
python -m pytest tests/e3/test_evidence_gate_l1e.py tests/e3/test_evidence_gate_view_l1e.py tests/e3/test_gate.py tests/e3/test_checklist.py tests/e3/test_review.py tests/e3/test_validate_semantic.py tests/e4/test_e4_view.py tests/e4/test_view_panel.py tests/e4/test_export.py -q -p no:cacheprovider --basetemp=$TMP/e3l1e-expanded-03
186 passed, 1 skipped in 0.94s

NEUMANN_UI_TESTS=1 NEUMANN_UI_TESTS_PORT=8164 NEUMANN_UI_SHOTS_OUT=$TMP python -m pytest tests/e3/test_evidence_gate_view_l1e.py -k browser -q -p no:cacheprovider --basetemp=$TMP/e3l1e-browser-02
1 passed, 21 deselected in 19.10s
```

반례 고정 최초 명령: `python -m pytest tests/e3/test_evidence_gate_view_l1e.py -k 'invalid_link or stored_result' -q -p no:cacheprovider --basetemp=$TMP/e3l1e-red-01` → **5 failed, 2 passed, 11 deselected in 0.55s**. 혼합 id·다른 카드·없는 카드 화면 3건과 미근거 문장 내보내기 2건을 실제로 잡았다. 수정 직후 같은 범위는 **7 passed, 11 deselected in 0.42s**였으며 이후 반례를 늘려 최종 대상 전체에 포함했다.

## 1차 인수 마무리의 재현 명령과 출력 (53e30c2 시점)

모든 명령 환경: `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_TESTS=0`, `NEUMANN_LIVE_LLM_OK` 해제, `OPENBLAS_NUM_THREADS=1`, `PYTHONPATH=src;.`, `PYTHONUTF8=1`. Python은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`다. 브라우저와 근거 회귀는 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`도 설정했다.

초기 캐시 재실행은 기본 pytest 임시 경로 접근 거부로 **setup 7 errors**였다. 제품 코드 실패로 판정하지 않았고, 캐시 provider를 끄고 쓰기 허용 임시 경로를 지정해 해결했다. 아래 `$TMP`는 `C:/Users/User/.codex/visualizations/2026/09/30/01a0f2aa-0210-72d1-8f81-8672327a7f89`다. 각 실행은 서로 다른 basetemp를 사용했다.

```text
python -m pytest tests/e3/test_pipeline_parallel_cache.py -q -p no:cacheprovider --basetemp=$TMP/e3l1e-cache-01
7 passed in 1.17s

python -m pytest tests/e3/test_evidence_gate_l1e.py tests/e3/test_evidence_gate_view_l1e.py tests/e3/test_gate.py tests/e3/test_checklist.py tests/e3/test_review.py tests/e3/test_validate_semantic.py -q -p no:cacheprovider --basetemp=$TMP/e3l1e-evidence-01
120 passed, 1 skipped in 0.92s

NEUMANN_UI_TESTS=1 NEUMANN_UI_TESTS_PORT=8164 NEUMANN_UI_SHOTS_OUT=$TMP python -m pytest tests/e3/test_evidence_gate_view_l1e.py -k browser -q -p no:cacheprovider --basetemp=$TMP/e3l1e-browser-01
1 passed, 10 deselected in 20.95s
```

이번 브라우저 테스트는 queued → running → done 작업 API 흐름을 가로챈 mock 시험이다. 근거/기타 검증 제외 목록 두 개의 기본 접힘, 항목별 "제외됨", 목록 제목 수와 제외 안내 수 일치, 근거 번호, 전부 제외 안내, 콘솔 오류 0을 검사했다. 시각화 폴더의 새 심사평 스크린샷도 직접 확인했다. 아래 기존 스크린샷은 Claude 반영 시점의 커밋 산출물이며 이번에 다시 덮어쓰지 않았다.

- 최초 빌더: Claude Opus 5.5 · 마무리 빌더: codex-gpt-6.1-sol · 브랜치 `task/E3-L1e`(main `1864d70` 기준) · 2026-09-30
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
- 한 카드의 LLM 행동이 전부 근거 없음으로 빠지면, 그 카드만 기존 비상 규칙 경로로 대신한다. 이때 `generator="rule"`, `fallback_reason="llm_no_grounded_action"`이고 단계는 degraded다. 화면에는 DISP-1의 "비상 규칙" 표기로 나온다. 규칙 문구는 LLM 문장이 아니고, 카드 근거에 연결되며, 표기된다(E3-L1b 규칙: "행동이 전부 무효면 그 카드만 규칙 경로"). 버려진 LLM 문구는 되살리지 않는다.
- 게이트 폐기만으로는 단계를 강등하지 않는다(ok 유지). 심사평 근거 게이트가 문장을 빼도 ok인 것과 맞췄다. 라이브에서 두 번에 한 번꼴로 생기는 일로 결과 전체에 "일부 단계 강등"을 띄우지 않기 위해서다. 대신 수는 counts, detail, 결과, 화면에 남는다.

## 층별 게이트(생성·2차 검증 공용 검사, 화면 방어 검사)

검사 내용: 근거 excerpt id가 1개 이상 있어야 한다. 전부 결과 `evidence` 안에 있어야 한다. 연결 카드가 결과에 있어야 한다. 근거가 전부 그 카드의 근거 안에 있어야 한다. 카드를 달지 않은 심사평 문장은 근거마다 어느 위험카드의 근거여야 한다(이번에 조였다).

실패 사유는 `missing_citation` · `unknown_excerpt_id` · `unknown_card_id` · `excerpt_card_mismatch`(`gate.NO_EVIDENCE_REASONS`)다. 제외 수를 세는 `gate.NO_EVIDENCE_FAMILY`는 여기에 `malformed`를 추가한다(근거 id를 읽을 수 없는 형식 오류). 체크리스트 비객체 항목도 마지막 게이트에서 `malformed`로 기록한다.

| 층 | 어디 | 처리 | 수 기록 |
|---|---|---|---|
| 체크리스트 생성 직후 | `checklist._clean_actions`에 더해, 규칙 항목까지 전부 `gate_checklist_items`로 한 번 더(번호는 거른 뒤 C1…) | 폐기 | 단계 counts `items_dropped_no_evidence`, detail "근거 없는 항목 k개 제외", `result.verification["checklist_evidence"]`(gate·policy=drop·dropped·reasons·dropped_detail) |
| 2차 검증 | `validate.validate_cards`가 판정 전에 같은 게이트로 거르고, 근거 없는 항목은 모델에 보내지 않는다. `apply_validation`이 내보낼 체크리스트를 다시 걸러 뺀다 | 폐기(틀림 강등과 달리 삭제) | `semantic.counts.actions_no_evidence`, `evidence_gate`, `dropped_actions`, 폐기가 있으면 degraded + notice. 정상 흐름이면 0이다. 0이 아니면 앞 게이트를 우회한 항목이 있다는 뜻이다 |
| 예상 심사평 | 기존 `gate_sentences`(생성 게이트)가 이제 공용 검사를 쓴다. 전부 떨어지면 기존 규칙 합성 경로를 탄다 | 폐기 | `audit.no_evidence`, 단계 counts `no_evidence`, detail "근거 없는 문장 k개 제외" |
| 화면(view) | 체크리스트는 카드가 화면에 있고 모든 근거가 그 카드의 근거이며 번호로 풀리는지 검사한다. 심사평도 공용 검사로 모든 발췌·카드 관계가 유효한 문장만 남긴다 | 폐기 | `checklist_audit`{shown, excluded, by_stage{checklist, semantic_validate, view}, note}, `review.audit.no_evidence`·`note`, `_status.dropped.checklist_items_without_evidence` |

- 2차 검증은 심사평과 **병렬**로 돈다(E3-L1y: `semantic_validate`는 `checklist`에만 의존한다). 그래서 2차 검증이 심사평을 고치면 순차·병렬 결과가 달라진다. 심사평 문장은 자기 생성 게이트와 화면 게이트가 맡는다(결정 2).
- 체크리스트 프롬프트: `evidence_ids`를 "0~3개"에서 "1~3개"로 바꾸고 "그 카드의 근거로 뒷받침할 수 없는 행동은 쓰지 않는다(근거 id가 없는 행동은 버려진다)"를 넣었다. 스키마에 `minItems:1`은 넣지 않았다. 억지로 아무 id나 고르게 만드는 것보다 모델이 그 행동을 빼는 편이 정직하기 때문이다(결정 3).

## 화면

조건부 지적 반영 뒤 현재 화면: 심사평 제외 목록은 **근거가 없어 제외한 문장**과 **검증에서 제외한 문장** 둘이다. 모두 기본 접힘이고 제목에 "분석 결과 아님"과 실제 목록 수를 표시하며 각 항목에 "제외됨"을 붙인다. `review.audit.no_evidence`는 화면에 싣는 삭제 목록 중 `no_evidence_reasons` 계열 사유 수다. 기타 사유(예: 없는 수치)는 별도 목록에 남으며 근거 제외 안내 수에 더하지 않는다.

체크리스트가 전부 제외되면 `hasCheck`가 제외 수도 확인해 절을 유지하고 **근거 있는 항목이 없어 모두 제외했습니다(k개)**를 표시한다. 내보내기 `neumann_report.md`는 `_review_for_report`로 예상 심사평 감사 원문을 제거하고 사유 코드·개수만 남긴다. 입력 원본 결과 JSON의 감사 기록은 유지한다. 내보내기 생성 직전에도 문장·항목 전체의 근거 관계를 검사하고 정리한 사본을 모든 파일에 쓴다.

최초 구현 당시 `index.html`은 기존 줄을 고치지 않고 새 줄 4개만 넣었다(`var check = …` 바로 뒤). view의 `note`가 있을 때만 체크리스트 절 끝과 심사평 감사 카드 위에 다음 문구가 나온다.

> 근거 없는 항목 k개 제외 (근거 번호 없음·연결 카드의 근거 밖)

폐기된 문구는 view에 싣지 않고 수만 싣는다.

- `docs/reports/E3-L1e_check.png`: 체크리스트 2행이 모두 근거 번호 `#2`·`#5`를 달고 있다. 아래에 "근거 없는 항목 1개 제외"가 있다.
- `docs/reports/E3-L1e_review.png`: 심사평 문장마다 근거 번호가 있다. 감사 카드 위에 "근거 없는 항목 1개 제외"가 있다.
- 두 장 모두 가짜 뷰다(fixture + 가짜 응답, mock 표기, 샘플 표시). 서버는 mock provider·키 없이 8163에 띄웠다가 껐다.

## 완료 기준별 명령·출력

환경: `NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." PYTHONUTF8=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`, `NEUMANN_LIVE_LLM_OK` 해제.

### 최초 구현 시점 기록: 1·2·3·4. mock 테스트(근거 빈 항목·없는 id·다른 카드 id·전부 빔·정상, 2차 검증, 심사평, 화면)

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
- `review.audit.no_evidence`·`note`·`no_evidence_reasons`

`premortem_response.schema.json`은 바꾸지 않았다. `checklist` 항목과 `verification`은 이미 자유 형식(additionalProperties: true)이다.

### 최초 구현 시점 verify 기록(이번 HEAD의 전체 PASS가 아님)

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
| `src/neumann/analyze/gate.py` | `evidence_link_problem`(공용 검사), `EvidenceLinkIndex`·`review_evidence_problem`, `NO_EVIDENCE_REASONS`·`NO_EVIDENCE_FAMILY`, `count_no_evidence`, audit `no_evidence`. 카드 없는 문장의 카드 밖 발췌 차단 | E3 |
| `src/neumann/analyze/checklist.py` | 생성 직후 게이트와 마지막 게이트(`gate_checklist_items`), `evidence_audit`, 단계 counts·detail, `verification.checklist_evidence`, 프롬프트 1~3개 | E3 |
| `src/neumann/analyze/validate.py` | 2차 검증 같은 게이트(모델에 안 보냄·apply에서 뺌), counts·evidence_gate·dropped_actions·notice | E3 |
| `src/neumann/analyze/review.py` | audit `no_evidence`, 단계 counts·detail | E3 |
| `src/neumann/api/view.py` | 화면 카드 근거 검사, `checklist_audit`, `review.audit.no_evidence·note·no_evidence_reasons`, 표시 목록에서 제외 수 집계 | E4(과제 지시로 최소 변경) |
| `src/neumann/webui/index.html` | 제외 안내, 기본 접힘 두 목록·항목별 제외됨, 전부 제외 시 절 유지 | E4(과제 지시로 최소 변경) |
| `src/neumann/api/export.py` | `_gate_export_result`: 9파일 공용 근거 검사, 미근거 문장·항목·결정 메모 제외. `_review_for_report`: 감사 원문 제거, 사유 코드·개수 유지 | E4(과제 지시로 최소 변경) |
| `contracts/ui_view.schema.json` | 선택 필드 추가(`review.audit.no_evidence_reasons` 포함) | PM(과제 지시 "계약은 추가만") |
| `tests/e3/test_evidence_gate_l1e.py`, `tests/e3/test_evidence_gate_view_l1e.py` | 새 테스트 | E3 |
| `tests/e3/test_checklist.py`, `test_review.py`, `test_gate.py` | 위 "기존 테스트도 고쳤다" 참조 | E3 |
| `tests/e4/test_e4_view.py`, `test_export.py` | 공용 실패 사유, 정상 표시/결정 항목의 실제 카드 근거 | E4(후속 지시로 변경) |
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
- (조건부 지적 반영 완료) 심사평 감사 카드 삭제 목록 둘은 모두 기본 접힘이고 각 항목에 "제외됨"이 있다. 브라우저 회귀는 목록 수·제외 안내 수 일치와 접힌 문장의 비가시성을 검사한다. 체크리스트 전부 제외도 절과 안내를 유지한다.
- 이번 대상 재실행에서 캐시 실패는 재현되지 않았다. 과거 전체 verify 실패의 원인을 입증한 것은 아니므로 PM 전체 검증을 병합 조건으로 남긴다.

- 기준선 실행에서 `tests/e3/test_pipeline_parallel_sim.py::test_simulated_parallel_is_faster_and_same`가 한 번 시간 초과로 실패했다(0.858s < 0.624s 기대, 다른 빌더들이 동시에 돌아 부하가 있었음). 코드를 바꾸기 전의 일이고, 마지막 verify에서는 통과했다. 시간 기반 테스트라 부하에 약하다.

## 다음 과제에 넘길 것

- (PM) 다음 승인 라이브 E2E(`tests/e2e/test_live.py --plans ai4s`)에서 확인할 것:
  - 체크리스트 단계 counts `items_dropped_no_evidence`
  - `verification.checklist_evidence.reasons`
  - 화면 `#ckExcluded`
- (E5) E2E 판정기가 `checklist_audit.excluded`·`review.audit.no_evidence`를 요약 줄에 기록하면 폐기율을 계획서별로 볼 수 있다.
