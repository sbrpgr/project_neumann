# E6-L2a 보고서 — 데모 사전 계산본·오프라인 폴백

- 빌더: Claude Opus 5.5 · 브랜치 `task/E6-L2a` · 2026-09-30
- 결과: 완료 기준 2건 모두 충족. 파이프라인(E3-L0)이 아직 main에 없어, 공유 폴더의 실제 사전 계산본은 **fixture 대체본**이다(결과·매니페스트·응답에 표시).

## 무엇을 했나

1. `scripts/precompute_demo.py` — 데모 계획서 3건(`tests/fixtures/plans/plan.md`·`plan_elife_neuro.md`·`plan_medimaging.md`)을 `neumann.pipeline.run_premortem(plan_text, session_id=...)`로 돌려 `<out>/<plan_id>.json`과 `manifest.json`을 쓴다.
   - `--source auto`(기본): 파이프라인이 있으면 실행하고, 없으면 fixture로 대체한다. 대체하면 결과에 `stages`(precompute_source, degraded, impl `fallback:fixture`)와 `notices[0]`(`[대체] 분석 파이프라인 미연결(…)`)을 남기고, 매니페스트에는 `source="fixture"`로 적는다. `plan.md`는 공용 fixture 결과(카드 2장, generator `mock`)를 쓴다. fixture가 없는 나머지 2건은 카드를 지어내지 않고 0장과 사유만 저장한다.
   - `--source pipeline`: 파이프라인이 반드시 있어야 한다. 없거나, 실패하거나, 결과 카드가 0장이면 exit 1이다. 카드 0장은 `--allow-empty`를 주면 넘어간다. `--source fixture`: 네트워크·API를 쓰지 않는다.
   - 매니페스트 항목: `plan_id`·`demo`·`title`·`file`·`sha256`·`bytes`·`generated_at`·`result_generated_at`·`elapsed_s`·`source`·`impl`·`status`·`cards_total`·`cards_by_generator`(astra·rule·mock)·`models`·`degraded_stages`·`warnings`(카드 0장, 건너뛴 단계)·`plan_text_included`. 최상위에는 `generated_at`·`source`·`pipeline`·`llm`(provider·모델 이름만)·`total_elapsed_s`·`failures`를 둔다.
   - 쓰기는 원자적이다(tmp → `os.replace`, 매니페스트는 마지막). 저장한 뒤에는 라우터와 같은 코드(`load_precomputed`)로 다시 읽어 "재생 확인 n/n"을 출력한다.
   - 분석 실패는 예외 종류 이름만 남긴다. 메시지에는 키 조각이 섞일 수 있어서 남기지 않는다.
2. `src/neumann/api/precomputed.py` — FastAPI `router`
   - `GET /premortem/precomputed`: 목록. 항목마다 무결성(`ok`·`mismatch`·`missing`·`bad_name`)과 라벨 `사전 계산본(YYYY-MM-DD HH:MM KST)`을 준다. 매니페스트가 없거나 깨져도 200을 돌려주고 `available:false`와 사유를 담는다.
   - `GET /premortem/precomputed/{plan_id}`: 단건. 64hex plan_id나 데모 이름(`plan_elife_neuro` 등)으로 찾는다. 다음 경우에는 **404**를 돌려준다.
     - 파일 sha256이 매니페스트와 다르다(`tampered`).
     - 결과 안의 plan_id가 매니페스트와 다르다(`tampered`).
     - 파일 이름이 허용 형식이 아니거나 폴더 밖을 가리킨다(`bad_name`).
     - 파일이 없다(`missing_file`), 매니페스트가 없다(`no_manifest`), 해당 항목이 없다(`not_found`), 결과 계약을 통과하지 못한다(`invalid`).
   - 표시: `notices` 맨 앞에 `사전 계산본(생성 시각) — 실시간 분석이 아니라 미리 계산해 둔 결과다`를 넣는다. fixture 대체본이면 그 사실도 덧붙인다. 그 밖에 `manifest.precomputed`(label·generated_at·sha256·source·models)와 헤더 `X-Neumann-Precomputed`·`…-Generated-At`·`…-Sha256`을 붙인다. 응답은 `PremortemResult` 모델과 `premortem_response.schema.json`을 그대로 통과한다.
   - main.py 폴백용 함수: `lookup_by_text(plan_text) -> PrecomputedHit | None`, `mark_result(hit) -> dict`.
   - 오프라인: 디스크만 읽는다. import해도 `neumann.pipeline`·`neumann.llm`·`openai`·`torch`·`sentence_transformers`·`httpx`를 불러오지 않는다(테스트로 확인).
3. `tests/e6/` 30건 — 목록·단건·변조 404·표시·경로 조작·매니페스트 없음/깨짐·외부 호출 0·스크립트 모드별 동작·E4 `build_ui_view`/`main.app` 연동

## 완료 기준별 측정

### 1. fixture 기반 테스트: 목록·단건·변조 404·표시

```
$ python -m pytest tests/e6 -v
test_e6_precompute.py::test_demo_plans_are_the_fixture_demo_plans PASSED
test_e6_precompute.py::test_fixture_mode_writes_results_and_manifest_offline PASSED
test_e6_precompute.py::test_auto_falls_back_to_fixture_when_pipeline_missing PASSED
test_e6_precompute.py::test_pipeline_required_but_missing_fails_without_writing PASSED
test_e6_precompute.py::test_pipeline_mode_calls_run_premortem_and_counts_by_generator PASSED
test_e6_precompute.py::test_empty_pipeline_result_fails_unless_allowed PASSED
test_e6_precompute.py::test_pipeline_failure_is_recorded_without_exception_text PASSED
test_e6_precompute.py::test_non_demo_plan_is_stored_without_plan_body PASSED
test_e6_precompute.py::test_main_replays_what_it_wrote PASSED
test_e6_precompute.py::test_script_runs_as_command_without_pythonpath PASSED
test_e6_precompute.py::test_network_guard_actually_blocks PASSED
test_e6_precomputed_api.py::test_router_paths PASSED
test_e6_precomputed_api.py::test_list_returns_items_with_label_and_integrity PASSED        ← 목록·표시
test_e6_precomputed_api.py::test_get_by_plan_id_is_marked_precomputed_and_keeps_contract PASSED  ← 단건·표시·계약
test_e6_precomputed_api.py::test_get_by_demo_name PASSED
test_e6_precomputed_api.py::test_label_is_kst_and_honest_when_time_unknown PASSED
test_e6_precomputed_api.py::test_tampered_file_returns_404_and_list_flags_it PASSED        ← 변조 404(변조 전 200 짝 검사)
test_e6_precomputed_api.py::test_single_byte_change_is_detected PASSED
test_e6_precomputed_api.py::test_manifest_sha_edit_returns_404 PASSED
test_e6_precomputed_api.py::test_swapped_file_with_matching_sha_is_caught_by_plan_id PASSED
test_e6_precomputed_api.py::test_unknown_and_traversal_ids_return_404 PASSED
test_e6_precomputed_api.py::test_manifest_file_name_outside_folder_is_refused PASSED
test_e6_precomputed_api.py::test_missing_manifest_and_missing_file PASSED
test_e6_precomputed_api.py::test_broken_manifest_is_reported_not_raised PASSED
test_e6_precomputed_api.py::test_lookup_by_text_for_main_fallback PASSED
test_e6_precomputed_api.py::test_marked_result_renders_through_e4_view_with_label PASSED
test_e6_precomputed_api.py::test_wired_into_main_app PASSED
test_e6_precomputed_api.py::test_default_folder_follows_data_dir_setting PASSED
test_e6_precomputed_api.py::test_requests_make_no_external_network_calls PASSED            ← 외부 호출 0
test_e6_precomputed_api.py::test_router_module_imports_no_pipeline_llm_or_model_code PASSED
============================= 30 passed in 4.26s ==============================
```

외부 호출 0은 이렇게 잰다. 테스트 동안 루프백이 아닌 곳으로 가는 `socket.connect`·`connect_ex`·`getaddrinfo`를 막고 시도를 기록한 뒤, 기록이 비었는지 확인한다. 루프백은 Windows asyncio의 socketpair 때문에 허용한다. 차단기가 실제로 막는지는 `test_network_guard_actually_blocks`가 따로 확인한다(`example.org` 연결 → OSError, 기록 1건).

**검사기 자체 검사(변이 시험)**: 라우터의 sha 비교를 끄자 변조 테스트 3건이 실패했다. notices 표시를 빼자 표시 테스트 2건이 실패했다. 두 경우 모두 원복 후 통과했다.

```
--- mutation 1: sha check off
FAILED ...::test_tampered_file_returns_404_and_list_flags_it
FAILED ...::test_single_byte_change_is_detected
FAILED ...::test_manifest_sha_edit_returns_404
3 failed, 24 passed
--- mutation 2: no notice
FAILED ...::test_get_by_plan_id_is_marked_precomputed_and_keeps_contract
FAILED ...::test_lookup_by_text_for_main_fallback
2 failed, 25 passed
```

(변이 시험 시점의 테스트는 27건이었다. 그 뒤 모델 정보·경고·main 연동 테스트를 더해 30건이 됐다.)

### 2. `python scripts/verify.py`

main(E1-L0까지)을 병합한 뒤 보고서 커밋 직전에 실행한 결과:

```
250 passed, 6 skipped in 8.00s
보안: 파일 137개
계약: 2개
테스트: 통과
verify 통과
```

### 추가 측정: 공유 폴더 사전 계산 실행과 재생

```
$ NEUMANN_DATA_DIR=C:/Users/User/Desktop/project_neumann/data python scripts/precompute_demo.py
출력: C:\Users\User\Desktop\project_neumann\data\precomputed
분석: fallback:fixture (neumann.pipeline 모듈 없음)
  plan: fixture · status degraded · 카드 2(mock 2) · 0.00s · 3d35460def76efc4a786dce769e614f0d54d110ee2837da6b8fc1dbcf88ef33c.json
  plan_elife_neuro: fixture · status degraded · 카드 0 · 0.00s · f0fb41c5f49d8dba30f813fcebc144b6543bdd3bf932f565a8184803f253d9ff.json
  plan_medimaging: fixture · status degraded · 카드 0 · 0.00s · 4d8d88874ab33b7df84f00e17f7d16228212c2ceefdd5c4225532459b94fe031.json
매니페스트: C:\Users\User\Desktop\project_neumann\data\precomputed\manifest.json (항목 3, 출처 fixture, 전체 0.009s)
재생 확인: 3/3
  경고 plan_elife_neuro: 카드 0장: 이 계획서의 fixture 결과가 없어 카드 없이 저장했다(파이프라인 연결 뒤 다시 만든다)
  경고 plan_medimaging: 카드 0장: 이 계획서의 fixture 결과가 없어 카드 없이 저장했다(파이프라인 연결 뒤 다시 만든다)
```

실제 서버(main.py 선택 라우터 자동 연결)를 127.0.0.1:8765에 띄우고 HTTP로 조회했다. 확인한 뒤 서버를 종료했고 포트가 비었다.

```
health routers.precomputed = ok
GET /premortem/precomputed -> 200 available=True items=3 header=1
  plan | 사전 계산본(2026-09-30 18:55 KST) | integrity=ok | cards=2
  plan_elife_neuro | 사전 계산본(2026-09-30 18:55 KST) | integrity=ok | cards=0
  plan_medimaging | 사전 계산본(2026-09-30 18:55 KST) | integrity=ok | cards=0
GET /premortem/precomputed/plan_medimaging -> 200 plan_id=4d8d88874ab3 generated_at_header=2026-09-30T09:55:05Z
  notices[0] = 사전 계산본(2026-09-30 18:55 KST) — 실시간 분석이 아니라 미리 계산해 둔 결과다 · 분석 파이프라인 미연결로 fixture 결과로 대체된 사전 계산본
GET /premortem/precomputed/unknown -> 404
```

### 추가 측정: E3-L0 `run_premortem`과의 호환(병합 전, scratch에서만)

`task/E3-L0` 브랜치를 scratch 폴더로 `git archive`하고 이 과제의 두 파일을 얹었다. 그 상태에서 `--source pipeline`을 mock provider로 돌렸다. 저장소와 공유 폴더는 건드리지 않았다.

```
분석: neumann.pipeline:run_premortem (…)
  plan: pipeline · status ok · 카드 0 · 0.03s · 3d35460d….json
  …
재생 확인: 3/3
llm {'provider': 'mock', 'model': 'gpt-6-astra'} models [['mock:mock-deterministic-v1'], …]
stages: plan_normalize ok · query_axes ok(mock) · search skipped · extract_issues skipped · synthesize_cards skipped · verify_evidence skipped
notices: '[search] 근거 저장소(E2 색인)를 열 수 없다', '위험카드 0장: 유사 연구 색인을 열 수 없어 분석하지 못했다'
```

시그니처, 반환형, 저장, 재생 모두 호환된다. 카드가 0장인 것은 scratch에 E2 색인이 없어서다. 이때 E3 결과는 `status: ok`로 끝났다. 이 과제는 그런 결과가 데모 폴백으로 조용히 저장되지 않도록 `warnings`와 exit 1을 추가했다.

## 바꾼 파일

- `scripts/precompute_demo.py` (새로 만듦)
- `src/neumann/api/precomputed.py` (새로 만듦)
- `tests/e6/e6_support.py`, `tests/e6/test_e6_precompute.py`, `tests/e6/test_e6_precomputed_api.py` (새로 만듦)
- `docs/reports/E6-L2a.md` (이 보고서)
- 공유 폴더(커밋 안 함): `C:/Users/User/Desktop/project_neumann/data/precomputed/manifest.json`, `<plan_id>.json` 3개

## 결정

1. **파일 이름과 조회 키**: 파일은 스펙대로 `<plan_id>.json`(plan_id는 `PlanDocument` 규칙의 본문 sha256)이다. 단건 조회는 plan_id와 데모 이름(`plan`·`plan_elife_neuro`·`plan_medimaging`)을 모두 받는다. 파일 경로는 요청 값으로 만들지 않고 매니페스트에서만 찾는다.
2. **표시 방식**: 응답을 `PremortemResult` 모양 그대로 두고 `notices` 맨 앞, `manifest.precomputed`(자유 형식 칸), 헤더에 표시를 넣었다. 감싸는 구조를 새로 만들지 않았으므로 E4 `build_ui_view`와 E4-L2a 내보내기에 그대로 넘길 수 있다. 화면 notices에 라벨이 남는 것도 테스트로 확인했다. 계약(`models.py`·`contracts/`)은 바꾸지 않았다.
3. **표시 시각**: 한국 시각(KST, UTC+9 고정 오프셋)으로 적는다. Windows에서 `zoneinfo`는 tzdata가 따로 필요해서 쓰지 않았다. 매니페스트와 헤더에는 UTC ISO(`…Z`)를 둔다.
4. **계획서 본문 저장**: 데모 계획서는 저장소에 공개된 fixture이고, 화면 재생에 줄 목록이 필요해서 본문을 넣었다(`plan_text_included: true`). 그 밖의 계획서(`--plan`)는 `plan=None`으로 본문을 뺀다(`PlanDocument`의 "본문 영속 저장 금지" 원칙).
5. **목록 응답**: 매니페스트가 없거나 깨지거나 항목 일부가 변조돼도 200을 돌려준다. 대신 항목별 `integrity`·`available`과 사유를 준다. 404는 단건에만 쓴다. 화면이 "무엇을 쓸 수 있는지"를 한 번에 알 수 있게 하려는 것이다.
6. **계약 불일치**: sha256은 맞는데 현재 결과 계약을 통과하지 못하는 파일은 404(`invalid`)로 돌려준다. 데모 폴백 관점에서는 "쓸 수 있는 사전 계산본 없음"이라는 점에서 같다고 봤다.
7. **fixture 대체 범위**: 과제 지시("없으면 fixture 결과로 대체하고 표시")대로 대체했다. 공용 fixture 결과는 plan.md용 1건뿐이다. 나머지 2건은 plan.md 카드를 옮겨 붙이지 않고(계획서 줄 번호가 맞지 않는다) 카드 0장과 사유로 저장했다. 이 대체는 스펙 안의 동작이라 `docs/decisions.md`에 적지 않았다(PM 소유 파일이기도 하다).
8. **카드 0장 게이트**: 파이프라인 결과가 카드 0장이면 exit 1로 막는다(`--allow-empty`로 넘길 수 있다). fixture 대체본의 0장은 이미 degraded로 표시되므로 막지 않고 `warnings`로만 드러낸다.

## router 인터페이스 (main.py 연결)

- 이미 main의 `OPTIONAL_ROUTERS`에 `"neumann.api.precomputed"`가 있어 자동으로 붙는다. `/health`에서 `routers["neumann.api.precomputed"] == "ok"`로 확인했다. 직접 붙이려면 아래처럼 한다.
  ```python
  from neumann.api.precomputed import router as precomputed_router
  app.include_router(precomputed_router)   # GET /premortem/precomputed, GET /premortem/precomputed/{plan_id}
  ```
- 폴더는 `<NEUMANN_DATA_DIR>/precomputed`다. 의존성 `precomputed_dir`로 정하며, 테스트에서는 `app.dependency_overrides[precomputed_dir]`로 바꾼다.
- (제안) 실시간 분석이 실패할 때 `/premortem/view`에 폴백을 붙이는 방법:
  ```python
  from neumann.api.precomputed import lookup_by_text, mark_result
  hit = lookup_by_text(req.plan_text)          # 데모 계획서와 본문이 같으면 PrecomputedHit, 아니면 None
  if hit is not None:
      view = build_ui_view(mark_result(hit), pipeline_state=state)   # _status.notices[0] = "사전 계산본(…) — 실시간 분석이 아니라…"
  ```

## 사전 계산 실행 명령

```bash
# Git Bash / PowerShell 공통 환경(_COMMON.md)
export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export NEUMANN_DATA_DIR="C:/Users/User/Desktop/project_neumann/data"
export NEUMANN_RAW_DIR="C:/Users/User/Desktop/노이만_본선자료/공개자료"
export NEUMANN_EMBED_MODEL="C:/Users/User/Desktop/노이만_본선자료/공개자료/models/bge-m3"

# E3-L0·E2가 main에 들어온 뒤(실제 astra, 카드 0장·실패면 exit 1):
C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/precompute_demo.py --source pipeline
# 지금(파이프라인 없음 → fixture 대체·표시):
C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/precompute_demo.py
```

출력은 `data/precomputed/manifest.json`과 `<plan_id>.json` 3개다. 매니페스트의 `source`, `pipeline`, 항목별 `cards_by_generator`·`warnings`를 확인한다.

## 못 한 것

- **실제 astra 사전 계산본**: `neumann.pipeline`(E3-L0)과 E2 색인이 main에 없어서 공유 폴더의 현재 본은 fixture 대체본이다(plan.md 카드 2장은 mock, 나머지 2건은 0장). 병합되면 위 `--source pipeline` 명령으로 다시 만들어야 한다.
- 매니페스트 서명은 하지 않았다. 파일과 매니페스트 sha를 **함께** 고치면 sha 검사는 통과한다. 다른 계획서 결과로 바꿔치기한 경우는 plan_id 대조로 잡는다(테스트 있음). 무대 폴백 용도로는 충분하다고 봤다.
- 오래된 `<plan_id>.json`은 지우지 않는다. 계획서가 바뀌어 plan_id가 달라지면 이전 파일이 폴더에 남는다. 라우터는 매니페스트 항목만 내므로 서빙되지는 않는다.
- 사전 계산본을 `ui_view`로 바로 주는 엔드포인트와 화면의 "데모 불러오기" 버튼은 만들지 않았다(E4 몫. 위 제안 참고).

## 다음

- PM: E3-L0·E2-L0 병합 뒤 `--source pipeline`으로 다시 만든다. exit 0, `source: pipeline`, 3건 모두 `cards_total ≥ 1`, `cards_by_generator.astra ≥ 1`을 확인한다. T+17h 프리즈 뒤에도 한 번 더 만든다(계획서 §3 마감).
- E3: 색인을 열 수 없을 때 `search`가 `skipped`로 기록되고 결과 `status`가 `ok`로 남는다(scratch 측정). 강등(`degraded`)으로 올려야 할지 검토를 제안한다.
- E6-L3a(정적 배포): `data/precomputed/manifest.json`의 `entries[].file`·`sha256`·`generated_at`·`models`로 "사전 계산본(생성 시각·모델)"을 표시할 수 있다. `load_precomputed()`로 무결성 검사 뒤 읽는 것을 권한다.
- E4: `lookup_by_text` + `mark_result` 폴백을 `/premortem/view`에 붙이는 것(위 제안)과, 목록 API로 데모 3건 선택 UI를 만드는 것.
