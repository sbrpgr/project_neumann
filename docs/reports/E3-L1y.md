# E3-L1y 보고서 — 분석 속도 개선(품질 손해 없이)과 단계 진행 보고

- 빌더: claude-opus-5.5 · 브랜치 `task/E3-L1y`(main 548d928 기준, main 17f9df5까지 병합: 문서만 바뀜)
- 모든 명령 `NEUMANN_LLM_PROVIDER=mock`. 실제 OpenAI 호출 없음(`NEUMANN_LIVE_LLM_OK` 안 켬).

## 무엇을 했나

| 파일 | 내용 |
|---|---|
| `src/neumann/pipeline.py` | 카드 뒤 v1 단계(예상 심사평·체크리스트·2차 검증)를 **의존 그래프대로 동시에** 돌린다. `V1_DEPENDS`(코드로 확인한 의존), `_attach_v1`(준비는 호출 스레드) → `_attach_v1_parallel`(의존 풀린 단계부터 스레드풀에 넣음) → `_merge_v1`(V1_STAGES 순서로 합침). 단계 처리 본문 `_v1_task`는 E3-L1w 루프 한 바퀴 그대로. `V1_PARALLEL=False`면 옛 순차 동작. `run_premortem(..., on_stage=None)` 진행 보고. `manifest.v1_parallel`·`v1_wall_s` 추가 |
| `tests/e3/test_pipeline_parallel.py` | 32개: 의존 그래프(선언·모듈 코드), 병렬=순차(7개 시나리오: mock·astra 이름·단계별 timeout 3·전부 실패·지연 흔들기, + off·다른 계획서 + 실제 적합성 모듈 + 단계별 예외 3), 실제 겹침·의존 순서, 겹친 상태의 단계별 실패 격리 3, on_stage(순서·횟수·스레드·0장·콜백 예외·jobs 모양 람다·요청 문맥), 표기 섞임 없음(PM 추가 요건, 6회 흔들기), v1 작업 스레드 캐시 쓰기 없음, 두 분석 동시 실행 |
| `tests/e3/test_pipeline_parallel_sim.py` | 지연 mock 시뮬레이션(테스트는 1/50 배율, `python -m`으로 실제 크기) |

analyze/·llm.py·models.py·api/는 고치지 않았다.

## 의존 그래프 (코드로 확인)

```
plan_normalize → fitness → query_axes → search → extract_issues → synthesize_cards → verify_evidence
                                                                                        │
                                              ┌─────────────────────────────────────────┤ (카드·근거·계획서)
                                              ▼                                         ▼
                                      expected_review                               checklist
                                      (카드·근거·계획서·유사연구 수)                  (카드·근거·계획서)
                                                                                        │ result.checklist
                                                                                        ▼
                                                                                 semantic_validate
                                                                                 (카드·근거·계획서 + 행동)
```

| 단계 | 입력으로 읽는 것 (코드 위치) | 앞 v1 단계 결과를 읽나 |
|---|---|---|
| expected_review | `review.usable_cards`·`build_review_prompt`·`gate_sentences`: `risk_cards`·`evidence`·`plan`·`similar_works` 수 | 아니오 |
| checklist | `checklist.build_checklist`: `risk_cards`·`evidence`·`plan` | 아니오 |
| semantic_validate | `validate.validate_cards`: `risk_cards`·`evidence`·`plan` + **`result.checklist`**(행동 판정) | **체크리스트** |

- 테스트로도 확인(`test_dependency_graph_holds_in_module_code`): 체크리스트는 예상 심사평이 있든 없든 같은 항목, 예상 심사평은 체크리스트·검증이 있든 없든 같은 문장, 검증은 체크리스트가 없으면 행동 판정 0건.
- 그래서 임계 경로는 `카드 → 체크리스트 → 2차 검증`이고, 예상 심사평이 그 옆에서 같이 돈다. 순차 3단계(12+12+12) → 병렬 max(12, 12+12)=24, **12초 단축**(모의 지연 기준).
- 병렬화하지 않은 곳과 이유: `fitness`와 `query_axes`는 서로 독립이지만, 적합성 판정이 unfit이면 검색어 단계를 **아예 부르지 않는다**(비용·캐시 쓰기 없음). 동시에 돌리면 계획서가 아닌 입력에도 검색어 호출·캐시 쓰기가 생겨 결과(`query_axes` skipped)와 비용이 달라지므로 이번엔 두었다(아래 제안 3).

## 결정성·강등 처리 (지금과 똑같이)

- **준비는 호출 스레드에서**: 단계별 `llm_call`(`_llm_call_for`)·호출 옵션·`stage_limits` 기록을 스레드에 넣기 전에 V1_STAGES 순서로 만든다. 작업 스레드는 공유 dict에 쓰지 않는다.
- **단계별 llm_call이 따로**: `ProviderLLMCall`의 `last_error`·`model`·`generator`가 단계마다 따로라 동시에 돌아도 섞이지 않는다.
- **합치기(`_merge_v1`)**: V1_STAGES 순서로, 단계마다 "자기 입력 대비 바뀐 필드"만 옮긴다(딕셔너리 필드는 바뀐 키만: 검증의 `verification.semantic`). 단계 기록은 그 단계 것만(순서 = V1_STAGES), notices는 그 단계가 덧붙인 것만, status는 가장 나쁜 값(모듈은 ok→degraded만 한다). 순차 실행에서 체크리스트·심사평은 서로의 필드를 읽지 않으므로 결과가 같다.
- **강등·실패 처리 그대로**: 단계 처리 본문 `_v1_task`는 E3-L1w 루프 한 바퀴를 옮긴 것(예외 → 그 단계만 error + notice, LLM 실패 → 모듈이 규칙·미검증으로 물러나 degraded + `마지막 호출: …` 사유). 체크리스트가 예외로 죽으면 검증은 체크리스트 없는 결과로 돈다(순차와 같다).
- **확인**: 병렬 결과를 순차 결과와 통째로 비교(시간 값만 뺌): mock·astra 이름·단계별 timeout·전부 실패·지연 흔들기·off·다른 계획서·실제 적합성 모듈·단계별 예외. 모두 같다.

## on_stage 형태 (jobs.py 연결용)

```python
def on_stage(stage: str, state: str, elapsed_s: float) -> None: ...
result = run_premortem(plan_text, on_stage=on_stage)   # 기본 None: 기존 호출자 그대로
```

- 단계를 시작할 때 `(이름, "running", 0.0)`, 끝날 때 `(이름, 최종 상태, 그 단계 소요 초)`. 최종 상태 = `ok|degraded|error|skipped`(결과 `stages[].state`와 같음). 파이프라인이 건너뛴 단계(예: 적합성 모듈 없음, 앞 단계 실패)는 끝 보고(`skipped`)만.
- 결과 `stages`마다 끝 보고가 **정확히 한 번**(상태·소요가 결과와 같다). 결과 조립이 실패하면 `("assemble", "error", 0.0)`.
- 순서: 카드 합성·원문 대조까지는 단계 순서대로 `running → 끝`. v1은 `expected_review running → checklist running → (끝나는 대로) … → checklist 끝 → semantic_validate running → …`. 시작 보고 순서는 늘 고정, 독립 단계의 끝 보고 순서는 실제 완료 순서다.
- **콜백은 run_premortem을 부른 스레드에서만** 불린다(작업 스레드에서 부르지 않음): 콜백에 잠금이 필요 없고, 요청 문맥(contextvars, `serving.current_request()`)도 그대로 보인다. v1 작업 스레드에도 문맥을 복사해 넘긴다(`contextvars.copy_context().run`).
- 콜백 예외는 무시하고 분석을 계속한다(로그에는 예외 종류만).
- 단계 이름: `plan_normalize, fitness, query_axes, search, extract_issues, synthesize_cards, verify_evidence, expected_review, checklist, semantic_validate`(+ 실패 때 `assemble`).

jobs.py(E4-L2d, 수정 안 함)는 `inspect.signature`로 `on_stage`를 찾아 `lambda stage, *a, **k: _set_progress(pid, stage)`를 넘긴다 → **지금 모양 그대로 붙는다**(`test_on_stage_accepts_jobs_style_lambda`). PM에게 제안:

1. 끝 보고까지 "현재 단계"로 덮으면 병렬 구간에서 이미 끝난 `expected_review`가 표시될 수 있다. 시작 보고만 쓰면 된다:
   `kw["on_stage"] = lambda stage, state="running", *a, **k: state == "running" and _set_progress(pid, stage)`
2. `STAGE_LABELS`에 없는 단계 이름: `fitness`("입력 확인"), `expected_review`("예상 심사평"), `checklist`("예방 체크리스트"), `semantic_validate`("2차 검증"). 병렬 구간 표시는 "예상 심사평·체크리스트"처럼 묶어도 된다.

## 측정 — 지연 mock 시뮬레이션 (실제 API 없음)

명령:
```bash
export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 NEUMANN_LLM_PROVIDER=mock
python -m tests.e3.test_pipeline_parallel_sim 1.0
```

출력(배율 1.0, 한 번):

```
배율 1.0, 카드 4장, 추출 묶음 6개, 호출 수 {'checklist': 2, 'expected_review': 1, 'extract_issues': 6, 'fitness': 1, 'query_axes': 1, 'semantic_validate': 2, 'synthesize_cards': 1}
```

| 단계 | 모의 지연 | 순차(E3-L1w) s | 병렬(E3-L1y) s |
|---|---|---:|---:|
| plan_normalize | - | 0.00 | 0.00 |
| fitness | 0s/호출 | 0.00 | 0.00 |
| query_axes | 3s/호출 | 3.00 | 3.00 |
| search | - | 0.00 | 0.00 |
| extract_issues | 3s/호출 | 3.02 | 3.01 |
| synthesize_cards | 12s/호출 | 12.00 | 12.00 |
| verify_evidence | - | 0.00 | 0.00 |
| expected_review | 12s/호출 | 12.00 | 12.00 |
| checklist | 12s/호출 | 12.00 | 12.00 |
| semantic_validate | 12s/호출 | 12.00 | 12.00 |
| **v1 구간 벽시계** | | **36.01** | **24.01** |
| **전체(total_s)** | | **54.11** | **42.02** |

**단축 12.09s (22.3%)** — 결과(카드·예상 심사평·체크리스트·검증·단계 목록)는 두 방식이 같다(테스트가 비교).

- 모의 지연: 검색어 3초, 추출 묶음 3초(묶음끼리 동시, `NEUMANN_EXTRACT_PARALLEL` 기본 24), 카드 12초, 예상 심사평·체크리스트·2차 검증 호출마다 12초(체크리스트·검증은 카드 3장 묶음끼리 이미 동시). 적합성은 지시에 없어 0초(실제 적합성 모듈은 돌지만 지연 없음). 코퍼스는 fixture(카드 4장, 추출 6묶음).
- 병렬 쪽 단계별 소요는 순차와 같고(단계 자체는 안 빨라진다), **v1 구간 벽시계가 36초 → 24초**가 된다. 단계 소요 합(timings_s 합)이 total_s보다 커지므로 `manifest.v1_parallel`·`v1_wall_s`를 같이 싣는다.
- 테스트 `test_simulated_parallel_is_faster_and_same`(1/50 배율)이 매번 같은 결과·단축을 확인한다.

### 지적 추출 동시 호출 수 점검

- 설정: `NEUMANN_EXTRACT_PARALLEL`(기본 `extract.DEFAULT_PARALLEL=24`), 묶음 `NEUMANN_EXTRACT_BATCH`(기본 50).
- E3-L0 실측(실색인): 1,356문장 → **32묶음**, 동시 24 → 2번에 나눠 나감(24+8), extract 39.4초. 동시 10에서는 42묶음 85초. 걸린 시간이 대략 "묶음 수 ÷ 동시 수(올림) × 묶음 지연"을 따른다.
- 지금 기본 24는 흔한 32묶음을 두 번에 보낸다. **제안: 서버 기동 값에 `NEUMANN_EXTRACT_PARALLEL=32`**(한 번에 나감, 추출 구간 약 절반 기대). 단 E3-L0 이후 429(속도 제한)는 본 적이 없을 뿐 32에서 확인하지 않았다 — 대표 승인 확인 테스트 때 429·시간 초과 묶음 수를 같이 본다. 코드 기본값 변경은 extract.py(E3, 이번 과제 소유 밖) 몫이라 하지 않았다.
- 체크리스트·검증 묶음 동시 수(`checklist.MAX_PARALLEL_CALLS=3`, 3장씩)는 카드 9장까지 한 번에 나가므로 충분하다.

## 완료 기준별 측정 (명령·출력)

공통 환경: `PYTHONIOENCODING=utf-8 PYTHONPATH="src;." HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 NEUMANN_LLM_PROVIDER=mock`

| 기준 | 명령 | 출력 |
|---|---|---|
| 병렬화(의존 그래프·결정성·강등 유지) + 진행 보고 + 스레드 안전 테스트 | `python -m pytest -q tests/e3/test_pipeline_parallel.py tests/e3/test_pipeline_parallel_sim.py` | `33 passed in 7.34s` |
| E3 전체(기존 파이프라인 테스트 포함, 병렬이 기본값) | `python -m pytest -q tests/e3` | `401 passed, 12 skipped in 13.43s` |
| 전후 시간(지연 mock, 실제 크기) | `python -m tests.e3.test_pipeline_parallel_sim 1.0` | 위 표: 전체 54.11s → 42.02s |
| verify | `python scripts/verify.py` | `1196 passed, 27 skipped in 119.24s` · `보안: 파일 394개` · `계약: 2개` · `테스트: 통과` · `verify 통과` |
| 기존 호출 순서 단언의 경쟁 정도 | mock으로 `run_premortem` 300회, LLM 호출 순서 `expected_review < checklist < semantic_validate` 확인(일회성 스크립트) | `order flips 0 / 300` |

테스트가 확인하는 것(요약):

- 병렬 = 순차: `test_parallel_result_equals_sequential[7개]`, `..._with_provider_off_and_other_plan`, `..._with_real_fitness_module`, `test_exception_in_one_stage_equals_sequential_and_is_contained[3개]` — 결과 JSON 전체(시간 값만 뺌)가 같다: 카드·예상 심사평·체크리스트 내용·검증·stage 목록(이름·상태·phase·impl·detail)·notices·status.
- 한 단계 실패: `test_failure_in_one_overlapping_stage_degrades_only_it[3개]`(겹쳐 도는 상태에서 timeout → 그 단계만 degraded, 나머지 ok, notices에 한 줄), 예외 3개(그 단계만 error, 경로 문자열 안 나감).
- 실제 병렬: `test_v1_stages_overlap_and_respect_dependency`(심사평·체크리스트 호출 구간이 겹치고, 검증은 체크리스트가 끝난 뒤 시작, v1 벽시계 < 단계 합 × 0.85).
- on_stage: `test_on_stage_order_and_counts[병렬·순차]`(단계마다 끝 보고 정확히 1번·결과와 같은 상태·소요, 시작 보고 순서 고정, 시작 < 끝, 체크리스트 끝 < 검증 시작, 콜백은 호출 스레드에서만), 0장·None 동일, 콜백 예외 무시, jobs 모양 람다, 요청 문맥.
- 표기 섞임 없음(PM 추가 요건): `test_labels_are_actual_values_per_stage_under_interleaving[6회]` — 과제마다 다른 모델명을 돌려주는 openai 이름 provider + 무작위 지연 + 한 과제 강제 실패. manifest `llm_provider/llm_model`, `query_axes`·`synthesize_cards` impl(`openai:<모델>`), 예상 심사평 `generator=astra`·`model=<모델>@expected_review`, 체크리스트 항목·검증 보고서 `astra`/`<모델>`, 실패 사유(`마지막 호출: …`)가 실패한 단계에만.
- 캐시: `test_v1_workers_never_write_caches`(검색어·추출 캐시 쓰기는 모두 v1 시작 전·v1 작업 스레드 밖, 캐시 JSON 정상·임시 파일 없음, 캐시 적중 재실행 같은 결과), `test_concurrent_analyses_do_not_share_state`(두 분석 동시 = 각자 순차 결과).

## 한계

- **실제 sol 지연은 재지 않았다**(실제 API 금지). 표는 지시한 모의 지연으로 잰 것이다. 실서버에서 줄어드는 폭은 대략 `min(예상 심사평, 체크리스트+2차 검증)` — E3-L1a·b 실측(12.5초·16.4초·12.4초)으로 치면 약 12초다. 80초 전체에서 v1 외 구간(검색어·추출·카드)은 그대로다.
- 병렬 구간에서는 OpenAI로 동시에 나가는 요청이 늘어난다(예상 심사평 1 + 체크리스트 묶음 최대 3). 추출(24 동시)보다 작아 속도 제한 위험은 낮다고 봤지만 실측하지 않았다.
- 체크리스트·검증 안의 묶음 병렬(모듈 기존 동작)은 같은 `llm_call`을 여러 스레드가 같이 쓴다 → 그 단계 안의 `last_error`는 마지막으로 끝난 묶음 값이다(E3-L1w와 같은 동작, 이번 변경과 무관). 단계 사이에는 섞이지 않는다(테스트).
- 기존 `tests/e3/test_pipeline_l1w.py::test_mock_all_stages_attached_in_order_with_results`는 LLM 호출 순서 `expected_review < checklist`를 단언한다. 병렬에서는 두 호출이 동시에 나가므로 이 순서는 보장이 아니다. 제출 순서(심사평 먼저)와 GIL 때문에 300회 돌려 0회 뒤집혔지만(아래 명령) 원리상 경쟁이다. 소유 밖 파일이라 고치지 않았다 → 제안 1.

## 결정

- 병렬을 기본으로 켰다(`V1_PARALLEL = True`). 끄는 스위치는 모듈 상수만 두고 환경변수는 만들지 않았다(새 설정 키는 `.env.example`(PM 소유)에 이름을 넣어야 해서). 필요하면 제안 2.
- 의존 그래프는 "단계마다 앞 단계 하나까지"만 허용한다(사슬·나무). 어긋나면(`_v1_graph_errors`) 로그 남기고 순차로 돈다.
- 콜백을 작업 스레드가 아니라 호출 스레드에서 부르게 했다(jobs.py 콜백이 잠금 없이도 안전하고, 요청 문맥이 보이게).
- `manifest`에 `v1_parallel`·`v1_wall_s`를 더했다(계약상 manifest는 자유 키). 단계 소요(`timings_s`)는 단계 자체 시간 그대로다.

## 제안 (PM·E3·E4)

1. `tests/e3/test_pipeline_l1w.py` 한 줄: `tasks.index("expected_review") < tasks.index("checklist") < …` → `tasks.index("checklist") < tasks.index("semantic_validate")`(실제 의존만). 지금은 통과하지만 원리상 경쟁.
2. 운영 스위치가 필요하면 `NEUMANN_V1_PARALLEL`(기본 1)을 `.env.example`에 넣고 pipeline이 읽게 한다.
3. 적합성 ∥ 검색어: 둘 다 계획서만 읽는다. 동시에 돌리면 약 3~6초(짧은 쪽) 더 줄지만, unfit 입력에도 검색어 호출·캐시 쓰기가 생긴다. unfit이면 검색어 결과를 버리고 `skipped`로 적고 캐시는 쓰지 않게(queries.py에 "쓰기 미루기" 인자) 하면 결과는 같게 할 수 있다 — 비용 증가를 받아들일지 PM 판단.
4. 2차 검증을 "카드 판정"(체크리스트 불필요)과 "행동 판정"으로 쪼개면 카드 판정은 체크리스트와 동시에 돌 수 있다. 호출이 늘고 지시문이 바뀌므로(품질 재측정 필요) validate.py 과제로.
5. 캐시 쓰기(`extract._cache_write`, `queries._cache_write`)는 임시 파일 이름이 `{key}.tmp`로 고정이다. 같은 키를 두 스레드·프로세스가 동시에 쓰면(같은 계획서 동시 분석, 같은 문장 묶음) 임시 파일이 겹칠 수 있다(읽기는 깨진 JSON을 적중 실패로 넘기므로 결과는 안전). `{key}.{uuid}.tmp`로 바꾸기를 제안. 이번 병렬화는 캐시를 쓰지 않는 단계만 동시에 돌리므로 새 경합은 없다(`test_v1_workers_never_write_caches`).
6. jobs.py 연결: 위 "on_stage 형태"의 1·2.

## 못 한 것

- 실제 sol 지연 측정(금지).
- 위 제안 1~6(소유 밖 또는 PM 판단).

## 다음

- PM: jobs.py 콜백을 시작 보고만 쓰게 바꾸고 v1 단계 이름표를 더한 뒤, 대표 승인 확인 테스트 때 `manifest.timings_s`·`v1_wall_s`·`total_s`를 실서버 값으로 한 번 기록.
