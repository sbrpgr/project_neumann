**판정: PASS** (병합 전 필수 수정 없음. 아래 "권고"는 병합을 막지 않는다.)

# E3-L1y 검증 보고서 — 카드 뒤 단계 병렬화와 on_stage 진행 보고

- 검증자: claude-sonnet-5.5 (빌더 claude-opus-5.5와 다른 모델)
- 대상: 브랜치 `task/E3-L1y`. PM이 알려 준 마지막 커밋은 `795ec31`이었으나 검증 중 빌더가 후속 4커밋을 올려(e88f9e5, ed9b6b7, a24764f, **06d902a**) 조정자 지시로 **06d902a까지** 검증했다. `pipeline.py`는 795ec31과 06d902a가 바이트 단위로 같다(`git diff 795ec31 06d902a`에 없음). QUEUE 행이 "795ec31 검증 중"이면 06d902a로 고쳐 적어야 한다.
- 방법: `git archive`로 795ec31·06d902a를 스크래치 폴더에 풀어 재현(빌더 worktree는 읽기만, 파일·git 쓰기 없음. 워크트리의 무시 파일 `.pytest_cache`·`__pycache__`는 내가 오기 전부터 있던 것). 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK` 미설정, `.env` 열지 않음, 실제 OpenAI 호출 없음, 캐시는 `cache_dir=None` 또는 스크래치 폴더.
- 측정 스크립트는 스크래치 폴더에만 있다(`h_det.py` `h_real.py` `h_dep.py` `h_lbl.py` `h_evt.py` `h_cache.py` `h_status.py` `h_time.py` `mutate.py`). 커밋하지 않는다.

## 1. 요약 표

| # | 확인 | 결과 |
|---|---|---|
| 1 | 의존 그래프가 코드와 맞는가, 공유 객체 경합 | **통과.** 심사평은 `evidence·plan·risk_cards·similar_works`만, 체크리스트는 `evidence·risk_cards`만, 검증은 `checklist·evidence·risk_cards`만 읽는다(속성 접근 감시). 6가지 순서 교환에서 심사평·체크리스트 산출물은 순서와 무관, 검증은 체크리스트 뒤일 때만 같다. 병렬 240회+ 실행에서 입력 결과·계획서·옵션 변경 0건(카나리아로 감지기 작동 확인) |
| 2 | 결정성(병렬 = 순차) | **통과.** 시나리오 34개, 병렬 무작위 지연 실행 283회, 불일치 0. 시간 값 외 결과 JSON 전체 동일 |
| 3 | 표기(모델·impl·generator) 섞임 | **통과.** 과제·호출마다 다른 모델명을 내는 가짜 provider로 57회, 오류 0(§4). 단, §4의 관찰 하나 |
| 4 | on_stage 순서·횟수·예외·호환 | **통과.** 순서·횟수 검사 50회+시나리오, 콜백 예외·느린 콜백·1인자 콜백에도 결과 동일, 기존 호출 그대로 |
| 5 | 시간 재현, pytest, verify, 소유 | **통과.** 54.10→42.02초 재현. `python scripts/verify.py` 통과(06d902a: 1206 passed, 27 skipped). 소유 밖 변경은 PM 지시 후속뿐(§7) |
| 6 | 후속 ④ 캐시 원자 교체(Windows 재시도) | **통과.** 재시도 40회·약 1.4초 상한, 영구 거부에도 무한 대기 없음, 손상 0, 실패 시 tmp 삭제(§6). 극단 읽기 경쟁에서는 쓰기를 포기할 수 있다(안전, 캐시 미스일 뿐) |
| 7 | 테스트가 실제로 버그를 잡는가 | 변이 7종 모두 잡힘. 단 1종(status 합치기 제거)은 빌더의 병렬 테스트가 아니라 l1w 연결 검사가 잡았다(§8) |

## 2. 의존 그래프와 경합 (직접 확인)

명령(스크래치, 06d902a): `python h_dep.py`, `python h_det.py`, `python h_real.py`

| 항목 | 방법 | 결과 |
|---|---|---|
| 읽는 필드 | 결과 객체를 감시 프록시로 감싸 `generate_expected_review`·`build_checklist`·`validate_cards`가 접근한 속성을 기록 | 심사평 `evidence, plan, risk_cards, similar_works` / 체크리스트 `evidence, risk_cards` / 검증 `checklist, evidence, risk_cards`. 허용 밖 접근 없음 |
| 순서 교환 | 3단계를 6가지 순서로 순차 실행해 단계별 산출물 비교 | 심사평·체크리스트: 6/6 순서에서 같음. 검증: 체크리스트가 앞인 3/3에서만 같고 앞이 아니면 다름 → "체크리스트 → 검증"만 실제 의존 |
| 2차 검증이 체크리스트 뒤인가 | on_stage 시작·끝 순서(무작위 지연 30회+시나리오), 공급자 호출 구간(모형 3종) | 순서 역전 0건. 호출 구간에서 검증 시작 − 체크리스트 끝 = +0.001초(3종 모두 0 이상). 이벤트열에 `checklist ok` 다음에 `semantic_validate running` |
| 공유 객체 변경 | `_v1_task`·`_attach_v1_parallel`을 감싸 입력 결과·계획서·옵션의 JSON 스냅샷을 전후 비교 | 병렬 283회 모두 변경 0. `llm_call`은 단계마다 별개 객체. 카나리아(입력 리스트를 일부러 뒤집음)는 감지됨 |
| 코드 읽기 | `_attach_v1`이 llm_call·옵션·`stage_limits`를 호출 스레드에서 미리 만들고, 작업 스레드는 새 결과만 만들어 돌려줌. `apply_validation`은 항목 dict를 복사, `attach_expected_review`는 `model_dump`→`model_validate` 사본. review·checklist·validate·gate·pii에 전역 가변 상태 없음. `MockProvider`의 `scripted.pop`은 과제별 목록이고 `calls.append`는 원자적. `OpenAIProvider.complete_json`은 호출별 상태를 인스턴스에 두지 않음 | 경합 요소 못 찾음 |

## 3. 결정성 (병렬 vs 순차)

병렬(`V1_PARALLEL=True`, 호출당 0~20ms 무작위 지연)과 순차(`False`)를 같은 입력으로 돌려 `model_dump(mode="json")`을 비교했다. 뺀 키: `elapsed_s latency_s total_s timings_s v1_wall_s generated_at v1_parallel`(시간 값과 모드 표식뿐). 순차도 지연을 줘서 지연 무관함을 확인했다.

| 시나리오 | 병렬 실행 수 | 카드 | 결과 |
|---|---:|---:|---|
| 데모 3건(fixture 코퍼스) | 26 ×3 | 1/0/0 | 동일 |
| 데모 3건 + 템플릿 `molecule_reaction` + 범위 밖 `negative_recipe` (**실색인 E2**, mock LLM) | 5·5·5·5·4 | 6/6/5/6/0 | 동일 (v1 단계가 실제로 도는 경우) |
| 가짜 코퍼스 배터리·영상 | 9 ×2 | 4/6 | 동일 |
| 범위 밖(요리)·빈 입력·비연구 한 줄 | 7·4·4 | 0 | 동일 |
| provider 이름 openai(astra 표기) | 9 | 1 | 동일 |
| 단계별 timeout: 심사평 / 체크리스트 / 검증 / 셋 다 | 9 ×4 | 1 | 동일(해당 단계만 degraded) |
| api_error(심사평+검증), 깨진 JSON(체크리스트, 심사평+검증) | 9·7·7 | 0~1 | 동일 |
| 카드 앞 단계 실패(적합성·검색어·추출·카드 합성) | 6·7 | 1 | 동일 |
| 예외: 심사평 / 체크리스트 / 검증 / 셋 다(모듈이 `RuntimeError`) | 7 ×4 | 1 | 동일(해당 단계만 error, 나머지 ok) |
| provider off(규칙 경로) | 7·5 | 1/0 | 동일 |
| 실색인 + timeout·예외·off·astra 표기 조합 | 4·4·4·4 | 5~7 | 동일 |
| astra 이름 provider + 단계 실패 5조합(status 확인) | 각 1쌍 | 4 | 동일, status 순차·병렬 모두 정상(`ok` / 실패 시 `degraded`) |
| 같은 캐시 상태(적중)에서 순차 vs 병렬 | 2쌍 | 4 | 동일. (미스 vs 적중은 `plan_checks.queries.notes`만 달라짐: 병렬과 무관한 기존 동작) |

- 총 시나리오 34개(하네스 25 + 실색인 9), 병렬 실행 283회, 불일치 0.
- 0-카드 데모(`plan_elife_neuro`, `plan_medimaging`)는 fixture 코퍼스 탓에 v1 단계가 skipped라서 실색인으로 다시 돌려 v1이 도는 경우(5~6장)를 확인했다.
- 카드 8장 이상(체크리스트 묶음 3개 초과)은 mock에서 만들지 못했다. → 미확인.

## 4. 표기 정확성 (PM 요건)

`Fake(MockProvider)`: 이름 `openai`(생성 주체 astra), 속성 `model=gpt-fake-base`, **호출마다 `gpt-fake-base@<과제>#<번호>`를 결과 모델로** 돌려주고 호출당 무작위 지연. 실패 조합 6가지(없음·체크리스트·심사평·검증·심사평+체크리스트·체크리스트+검증), 병렬 45회(무실패 15 + 나머지 5조합 × 6) + 순차 12회 = 57회. 점검: manifest, 단계 impl, 예상 심사평 model·generator, 체크리스트 항목 generator·model, 검증 보고서 generator·model, 실패 사유·notices가 실패한 단계에만 있는지, 한 섹션에 다른 과제의 모델 표기가 섞였는지.

| 항목 | 관찰 | 결과 |
|---|---|---|
| manifest | `llm_provider=openai`, `llm_model=gpt-fake-base`(provider 속성) | 섞임 없음 |
| `query_axes`·`synthesize_cards` impl | `openai:gpt-fake-base` | 섞임 없음 |
| 예상 심사평 | `generator=astra`, `model=gpt-fake-base@expected_review#N`. 실패 시 `rule`·model 없음 | 섞임 없음 |
| 체크리스트 항목 | `astra` + 모델 `gpt-fake-base`. 실패 시 `rule` | 섞임 없음 |
| 검증 보고서 | `astra` + 모델 `gpt-fake-base`. 실패 시 규칙·미검증 + `degraded` | 섞임 없음 |
| 실패 사유·notices | 실패시킨 단계의 stage detail·notice에만 `timeout` 계열 문구. 성공한 단계에는 없음 | 섞임 없음 |

- 57회 중 오류 0. 어느 섹션에도 다른 v1 과제의 `@과제#` 표기가 들어가지 않았다. 순차도 같은 값이다.
- **관찰(이번 변경과 무관, 순차도 동일):** 체크리스트 항목·검증 보고서의 `model`은 provider가 설정한 모델(호출 전에 읽음)이고, 예상 심사평의 `model`만 호출 결과가 돌려준 모델이다. 실제 API가 별칭 대신 날짜 붙은 모델명을 돌려주면 셋의 표기가 서로 다를 수 있다. 섞임 문제는 아니며 E3(checklist·validate) 몫이다.

## 5. on_stage

명령: `python h_evt.py`(06d902a)

| 항목 | 결과 |
|---|---|
| 끝 보고 | 결과 `stages` 10개 각각 정확히 1회. 상태·소요 초가 결과와 같다(병렬 무작위 지연 30회 + 순차 + 범위 밖·빈 입력·카드 0·실패 3·예외 3·off) |
| 시작 보고 | 단계당 최대 1회, 끝보다 먼저. 시작 보고 순서는 병렬(무작위 지연 20회 추가)·순차와 무관하게 항상 `…verify_evidence, expected_review, checklist, semantic_validate` |
| 의존 | `checklist` 끝 → `semantic_validate` 시작(위 실행 전부). 카드 앞 단계 보고는 v1 보고보다 항상 먼저 |
| 스레드 | 모든 콜백이 `run_premortem`을 부른 스레드에서만 불림 |
| 콜백 예외 | 항상 예외 / v1 단계에서만 예외 / 느린 콜백(30ms) / 1인자 lambda(TypeError) → 병렬·순차 모두 결과가 콜백 없는 실행과 동일. `KeyboardInterrupt`는 전파(Exception만 무시) |
| 호환 | `on_stage`는 키워드 전용·기본 None, 기존 파라미터 목록·순서 그대로. `on_stage` 없이 호출 정상. E4-L2d(`task/E4-L2d:src/neumann/api/jobs.py`)의 `lambda stage, *a, **k` 모양과 시그니처 검사(`"on_stage" in params`) 호환 |
| 이벤트 예 | 카드 0(범위 밖): 파이프라인이 건너뛴 앞 단계는 끝 보고만, v1 3단계는 `running` 뒤 `skipped`(모듈이 skipped를 결정). 빌더 문서는 "건너뛴 단계는 끝 보고만"이라 적었는데 v1은 시작 보고가 붙는다. 무해(끝 보고는 1회) |

## 6. 후속 ④ — 캐시 임시 파일 고유화·`os.replace` 재시도 (조정자 요청)

명령: `python h_cache.py`(06d902a `extract._cache_write`·`queries._cache_write`, 스크래치 캐시 폴더, 끝나고 삭제)

| 시험 | 결과 |
|---|---|
| A. 같은 키, 쓰기 16스레드×60회 + 읽기 4스레드 상시 읽기(모듈별 실행에서 읽기 합계 각각 약 81만·102만 회) | 예외 0, **깨진 JSON 읽기 0**, 최종 파일 온전, 남은 tmp 0. 읽기 쪽 `OSError`(교체 순간의 일시 거부)는 2천여 회(`_cache_read`가 미스로 처리). 쓰기 960회 중 약 700회는 읽기 폭주 때문에 1.4초 재시도 뒤 **포기**(경고 로그, 기존 파일 유지) |
| B. 3프로세스 × 8스레드 × 30회, 같은 키 | 종료코드 0, 포기 0, 최종 온전, tmp 0 (1.0초) |
| C. `os.replace`가 영구 `PermissionError` | 1.37초 뒤 포기(시도 정확히 40회), 예외 안 새고 경고 1줄, **tmp 삭제**, 최종 파일 안 생김. 검색어는 `False` 반환. **무한 대기 없음** |
| D. 다른 `OSError`(EIO) | 재시도 없이 즉시 실패(시도 1회), tmp 삭제. 쓰다 디스크 가득(반쯤 쓴 tmp) → tmp 삭제, 최종 파일 안 생김 |
| E. Windows 실제 핸들: 대상 파일을 다른 스레드가 연 채 | 0.4초 잡고 있으면 0.43초 뒤 교체 성공(새 내용). 3초 잡고 있으면 1.38초 뒤 포기, **기존 파일 그대로 온전**, tmp 0 |
| 종단(검색어 캐시 astra) | 순차(미스·저장) → 순차(적중) → 병렬(적중) ×2: 캐시 파일 7개(추출 6 + 검색어 1), tmp 0, 순차(적중) = 병렬(적중) |

- 판정: 재시도는 유한(약 1.4초)하고, 실패해도 파일이 손상되거나 임시 파일이 남지 않는다. 최악은 캐시 저장 포기(다음에 LLM 재호출)다. 시험 A의 포기율은 같은 키를 80만 번 읽는 인위적 폭주 때문이고, 실제로는 분석당 키 하나를 한 번 읽는다.
- 한계: 프로세스가 강제 종료되면 `{key}.{pid}.{tid}.{uuid}.tmp`가 남을 수 있고(옛 고정 이름은 다음 쓰기가 덮어썼다) 청소 작업이 없다. 누적은 사고 때만이라 권고 수준.

## 7. 명령·출력 (완료 기준)

| 기준 | 명령 | 출력 |
|---|---|---|
| tests/e3 (795ec31 사본) | `pytest -q -p no:cacheprovider tests/e3` | `401 passed, 12 skipped in 13.99s` |
| 전체 pytest (795ec31 사본) | `pytest -q` | `1196 passed, 27 skipped in 114.65s` |
| verify (06d902a, 빌더 worktree, 작업 트리 깨끗) | `python scripts/verify.py` | `1206 passed, 27 skipped in 102.81s` · `보안: 파일 395개` · `계약: 2개` · `테스트: 통과` · `verify 통과` |
| 전후 시간 재현 (06d902a) | `python -m tests.e3.test_pipeline_parallel_sim 1.0` | v1 구간 36.01 → 24.01초, 전체 **54.10 → 42.02초**, 단축 12.08초(22.3%). 빌더 표 54.11 → 42.02와 일치 |
| 독립 시간 모형 | 내 `DelayedMock`, 심사평·체크리스트·검증 지연을 다르게 | 병렬 v1 = max(심사평, 체크리스트+검증): (3, .5, .5) → 순차 4.01/병렬 3.0, (.5, 2, 2) → 4.51/4.0, (1, 1, 1) → 3.0/2.01. 식과 일치 |
| 소유·계약 | `git diff main...task/E3-L1y --stat` | 8개 파일, 아래 참조. `contracts/`·`models.py`·데이터·비밀값 변경 없음 |

`git diff main...task/E3-L1y --stat` (06d902a): `docs/reports/E3-L1y.md`, `src/neumann/pipeline.py`, `tests/e3/test_pipeline_parallel.py`, `tests/e3/test_pipeline_parallel_sim.py`, `tests/e3/test_pipeline_parallel_cache.py`(소유 패턴 안) + **`src/neumann/analyze/extract.py`, `src/neumann/analyze/queries.py`, `tests/e3/test_pipeline_l1w.py`**. 뒤 셋은 처음 지시한 소유 목록 밖이지만 AGENTS.md상 E3 소유 영역이고 QUEUE의 PM 결정(순서 단언 정리·병렬=순차 고정·캐시 임시 파일명 고유화)에 따른 후속이다. 795ec31 시점에는 소유 밖 변경이 없었다.

## 8. 테스트가 실제로 잡는가 (변이 시험)

스크래치 사본의 `pipeline.py`에 일부러 결함을 넣고 `tests/e3/test_pipeline_parallel.py`+`test_pipeline_l1w.py`를 돌렸다(`-x`).

| 변이 | 결과 |
|---|---|
| M1 검증이 체크리스트를 안 기다림(`V1_DEPENDS`) | 잡음 (`test_dependency_graph_is_checklist_then_validate_only`) |
| M2 `_merge_v1`에서 status 합치기 제거 | l1w의 `test_linkage_checker_passes_with_v1_results`만 잡음. **`test_pipeline_parallel.py` 32개는 전부 통과**(병렬=순차 시나리오가 mock 이름이라 status가 이미 degraded). 내 `h_status.py`(astra 이름 + 단계 실패)는 잡음 |
| M3 심사평이 체크리스트의 llm_call을 씀(표기 섞임) | 잡음 (예외 격리 테스트) |
| M4 검증 끝 보고 누락 | 잡음 (`test_on_stage_order_and_counts`) |
| M5 콜백 예외를 삼키지 않음 | 잡음 |
| M6 notices 합치기 누락 | 잡음 (`test_parallel_result_equals_sequential[fail_all_v1]`) |
| M7 검증이 붙인 체크리스트 판정을 병합에서 누락 | 잡음 (`[astra_like]`) |

## 9. 권고 (병합을 막지 않음)

1. **테스트 보강(작음):** `test_pipeline_parallel.py`의 병렬=순차 시나리오 중 하나를 astra 이름 provider + 단계 실패로 돌려 `status`가 순차와 같은지(`degraded`)를 직접 단언. 지금은 l1w 연결 검사가 우연히 받쳐 준다(M2).
2. **E4-L2d 연결:** jobs.py의 `lambda stage, *a, **k: _set_progress(pid, stage)`는 끝 보고까지 "현재 단계"로 덮는다(병렬 구간에서 이미 끝난 `expected_review`가 표시될 수 있음). 빌더 제안대로 시작 보고(`state == "running"`)만 쓰고, `STAGE_LABELS`에 `fitness`·`expected_review`·`checklist`·`semantic_validate`를 더하는 것은 E4-L2d 쪽 몫.
3. **SEC-5와의 순서:** 병렬 구간은 분석 하나당 OpenAI 동시 요청이 최대 4개(심사평 1 + 체크리스트 묶음 3)까지 늘고, 체크리스트가 끝나면 검증 묶음 3개(+ 아직 도는 심사평 1)가 이어진다. 공개 동시 6건이면 v1 구간만 최대 약 24개다. 실 API 429는 금지 규칙상 재지 못했다 → **미확인**. SEC-5(`NEUMANN_LLM_MAX_INFLIGHT`, 미병합)가 들어오면 프로세스 상한이 이 요청들도 함께 제한한다. 그 전에는 상한이 없으니 대표 승인 확인 테스트에서 429·시간 초과 수를 같이 본다.
4. **QUEUE 정정:** 검증 대상 커밋을 795ec31이 아니라 06d902a로 적는다.
5. (선택) 캐시 tmp 고아 파일 청소, 체크리스트·검증 `model`을 예상 심사평처럼 호출 결과 기준으로 통일(E3 후속).

## 10. 못 본 것

- 실제 OpenAI 지연·429·시간 초과(금지). 벽시계 단축은 모의 지연으로만 확인(약 12초, 빌더 추정과 같음).
- 카드 8장 이상, 동시 6개 분석 부하 상태에서의 v1 병렬(mock 부하 시험 없음).
- 스레드 자원 고갈로 `pool.submit`이 `RuntimeError`를 내는 극단 상황(순차 경로는 모듈 안 예외를 단계별로 잡아 error로 남기지만, 병렬 경로의 `submit` 실패는 `_v1_task`의 try 밖이라 잡히지 않고 `run_premortem` 밖으로 나간다). 발생 가능성은 매우 낮고 시험하지 않았다.
