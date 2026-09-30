# [FIN-ENGINE] 최종 점검·수정 엔진 — 빌더 보고

## 인계(03:5x, 문맥 절약으로 중단 — 새 에이전트가 이어받음)

1. 브랜치 `task/FIN-ENGINE`(worktree `.claude/worktrees/s3-FIN-ENGINE`), 기준 core-final f54ef1d + finalization b629789 결합(`2a8c911`) 위에 **main 39055d1 병합 완료**(`f6ff798`, docs 충돌 2건 양쪽 유지). 마지막 WIP 커밋 해시는 §7 표.
2. 완료·검증됨(`adf7798`까지): C-2 ①②③④(확정 문안 413/422 상한, preflight `asyncio.to_thread`, 정규식 선형화+`bounded_strings`, 연구자 문안 `text_source`/`provenance`·서명 없음) — `src/neumann/api/finalize.py` `_finalization`/`_preflight`/`run_finalization`/`coupled_provenance`, `src/neumann/api/revise.py` `bounded_strings`, `src/neumann/analyze/revise.py` 정규식 2개. 테스트 `tests/e4/test_finalize_c2.py`.
3. 완료·검증됨: V-finalization F1(중복 검사 id 거절)·F3(2글자 낱말·부정 게이트 `_grounded_words`/`_negations`)·F4(수정 뒤 재결속 재검사 `_rebind_for_recheck`)·F5·F6(결속)·R8(엔진 상한)·자리표시 partial — `src/neumann/analyze/finalize.py`, 테스트 `tests/e3/test_finalize_vfix.py`. F2(항목 중복·다른 개념 합산)는 `final_tools.py` 소관이라 미착수(FIN-TOOLS C-1).
4. **WIP(코드 반영, 관련 테스트 일부만 확인)**: C-4 자리표시 통로 차단 — `finalize.py` `_placeholder_problem`(`://`·`www.`·`](`·`@`·`<>` 거절, 낱말은 `_PLACEHOLDER_VOCAB` ∪ 범위 낱말), 교정 루프에서 `_text_problem` 직후 호출. 테스트 `tests/e3/test_finalize_gate.py::test_placeholder_body_is_not_a_free_text_channel`. 사유 코드+줄 번호 템플릿 생성 방식은 미착수.
5. WIP: E-1 — `_computed_numbers`에서 엔진 sum/prod 제거, 수치는 도구 params 값과 `details` 숫자 leaf(`computed`)만. **주의:** 이 브랜치의 `final_tools._constraint`는 `details.computed`를 내지 않으므로 FIN-TOOLS(fd21f56) 병합 전에는 자리표시 계산값이 안 붙는다(데모 mock은 `computed` 있을 때만 수치 삽입). 테스트 `test_tool_computed_value_only_inside_placeholder`(details.computed를 주입해 검사).
6. WIP: E-2 — 시연 대본은 `NEUMANN_DEMO_SCRIPT=1`일 때만(`analyze/finalize_demo.py` `demo_enabled`); `scripts/finalize_demo.py`가 켠다. 응답 최상위에 `generator`/`model` 추가(`run_finalization`). UI `originText`는 `finalization.generator`·`text_source`를 읽음.
7. WIP: E-4 — `src/neumann/finalize/tools/__init__.py` `ToolRegistry.run`이 `ToolSpec.timeout_s`를 스레드 풀로 강제(초과 → `unchecked/timeout`, 스레드는 중단 불가). 테스트 `tests/finalize/test_tools_interface.py::test_timeout_is_enforced…`.
8. WIP: E-8 — 레지스트리가 이름을 목록에 묶지 않음(소문자 식별자면 등록, 미등록 이름은 `tool_unavailable`). `TOOL_FOR_CHECK`는 두 계열(constraint/units/dependency→z3/pint/networkx 어댑터 + arithmetic/sum/unit/structure/reference/citation/exec→FIN-TOOLS 이름). `ensure_builtin()`이 `builtin`/`fin_tools`의 `register_all`을 부른다(FIN-TOOLS는 별도로 `citation.configure(data_dir)` 필요). **병합 시 `finalize/tools/__init__.py`는 FIN-TOOLS 쪽과 충돌하니 이 판(v3)을 기준으로 그쪽 등록 코드를 얹는다.**
9. WIP: 경로 — `FINALIZE_PATH="/premortem/finalize"`, `LEGACY_FINALIZE_PATH="/premortem/revise/finalize"` 둘 다 같은 핸들러·보호 경로(`api/finalize.py`, `serving.kind_for`), UI fetch는 새 경로. `tests/e4/test_finalize_ui.py`·`test_finalize_browser.py`·`docs/API.md`의 경로 문자열은 새 경로로 맞췄다. 브라우저 테스트는 `adf7798`에서 통과했고 WIP 뒤에는 미실행이다(`NEUMANN_UI_TESTS=1`로 1회 재확인 필요).
10. 확인된 검증: `adf7798` 브라우저 1 passed(59.7s); 전체 verify(`adf7798`, 키·솔트 제거) **1 failed·2374 passed·55 skipped / 411.8s** — 실패는 `tests/e3/test_pipeline_parallel_cache.py::test_concurrent_writes_same_key_no_torn_file_no_exception[queries]`(부하성, finalize 무관; main 인계도 부하성 실패 기록). WIP 이후 전체 verify는 미실행.
11. WIP 이후 확인해야 할 테스트: `tests/finalize tests/e3/test_finalize_gate.py tests/e3/test_finalize_demo.py tests/e3/test_finalize_vfix.py tests/e3/test_finalize.py tests/e4/test_finalize_c2.py tests/e4/test_finalize_api.py tests/e4/test_finalize_ui.py tests/e0/test_finalization_integration.py` + `scripts/finalize_demo.py --check`(fixture 재생성 필요: 자리표시 문구·`generator` 필드 변경) + 브라우저 1건.
12. 시연 fixture `docs/reports/FIN-ENGINE_demo.json`/`_final.md`는 `adf7798` 기준 산출물이라 WIP 반영 뒤 `python scripts/finalize_demo.py`로 다시 만든다.
13. 실행 규칙: `env -u OPENAI_API_KEY -u NEUMANN_PSEUDONYM_SALT`, mock, 중립 basetemp(`C:/Users/User/AppData/Local/Temp/...`), 실제 API 0. §0.2 코드 실행 미구현(보안).
14. 병합 순서(PM): FIN-ENGINE → FIN-TOOLS → B1 → B2B3 → FIN-UI → WAIT-UX. 이 브랜치는 main을 이미 담고 있다.
15. 남은 판단: C-4 템플릿 생성 방식 여부, F2(FIN-TOOLS), `details.computed` 도입 시 데모 문구 확인, 옛 경로 alias 유지 기간.

- 작성: 2026-10-01 03:2x KST · 빌더 claude-fable-5.1 · 브랜치 `task/FIN-ENGINE`(worktree `.claude/worktrees/s3-FIN-ENGINE`)
- 실행 조건: `NEUMANN_LLM_PROVIDER=mock`, 실제 OpenAI 호출 0, `.env` 미열람, 키·솔트를 뺀 환경(`env -u OPENAI_API_KEY -u NEUMANN_PSEUDONYM_SALT`)에서 검사. main 병합·push 없음.

## 0. 도구 인터페이스(첫 커밋, 02:55 `a3b973b` → 결합 기준 위 `b35fc9a`, 어댑터화 `7011d78`)

`src/neumann/finalize/tools/__init__.py` — **`ToolCall(name, args) → ToolResult(ok, output, evidence)`**

| 항목 | 내용 |
|---|---|
| `ToolCall` | `name`(도구 이름) · `args`(JSON dict, 기본은 `{"plan_text", "check"}`) · `check_id` |
| `ToolResult` | `ok`(도구가 끝까지 돌아 판정을 냈나 — 통과 아님) · `output`(`verdict` pass/fail/unchecked 포함) · `evidence` = {tool, version, input, output, verdict, reason, elapsed_ms, check_id} · `error` |
| `TOOL_FOR_CHECK` | **코드가 정한** 점검 유형 → 도구: `constraint→z3`, `units→pint`, `dependency→networkx`. LLM은 도구를 고르지 않는다 |
| `ToolSpec`/`ToolRegistry` | FIN-TOOLS가 같은 이름으로 `register(spec, replace=True)`해 구현을 바꾼다. 등록이 없으면 `analyze/final_tools.run_tool_checks` 어댑터 |
| `run_check(plan_text, check)` | 검사 1건을 코드가 정한 도구로 실행. 모르는 kind·인자 오류·도구 없음·취소·예외는 모두 `unchecked`(예외 원문 미기록) |

검증 `tests/finalize/test_tools_interface.py` 6건: 실제 Z3가 인터페이스를 거쳐 fail/pass 판정과 evidence(입력 check·출력 details)를 남기고, 근거 없는 수치(원문에 없는 30)는 unchecked, 도구 모듈 부재는 `tool_unavailable`, 예외 문구·입력 값은 evidence에 남지 않는다.

## 1. 기준과 방향 수정

- 원 지시의 기준은 `codex/finalization-20261001`(b629789)였다. core-final(f54ef1d)은 finalize 코드가 없고 serving/SEC-7만 최신이라 처음엔 finalization을 기준으로 잡았다.
- 03:0x 코디네이터 방향 수정(감사 노트 `fin_audit.md`): **새 엔진을 짜지 말고 Codex `analyze/finalize.py`를 기반으로** 게이트·mock·결합 기준을 고친다. 이에 따라 이미 쓰던 별도 엔진 초안(파일 2개, 미커밋)은 버리고, 브랜치를 **core-final `f54ef1d` + finalization `b629789` 결합**(`2a8c911`: 소스 자동 병합, `docs/decisions.md`·`docs/tasks/QUEUE.md` append 충돌 양쪽 유지) 위에 다시 세웠다. 인터페이스 커밋은 cherry-pick(`b35fc9a`).
- §0.2 연구자 코드·데이터 실행은 넣지 않았다(보안). 도구 검사(원문에 명시된 수치 제약·단위 차원·선행 관계의 실제 계산)와 코드 실행은 발표에서 구분한다.

## 2. 흐름(변경 없음, `analyze/finalize.py`)

연구자 확정 문안 → 의미 검사 1회(issue + 도구 검사 항목, 줄 번호만) → 코드가 원문 발췌를 붙임 → **Z3·Pint·NetworkX 실제 계산** → 교정 제안 1회 → 근거 게이트 통과분 1묶음(≤8줄) 적용 → 고친 줄의 도구 재검사 ≤1회 → 최종 초안·교정 이력(원문→수정→사유)·쟁점(resolved/unresolved/unchecked+사유)·도구 전후 결과·counters(상한 1·1·1·1). 자동 반복 0회. 계약 `contracts/finalization.schema.json` 불변(issues는 object라 새 필드 허용). API는 기존 `POST /premortem/revise/finalize`(관문·중복 제출·서명 그대로).

## 3. 고친 것

| # | 감사 노트 | 변경 | 위치 |
|---|---|---|---|
| 1 | 교정이 0에 수렴(`_content_words`가 같은 줄 밖 낱말을 전부 거절) | 허용 어휘·수치의 근거 범위를 **issue의 `plan_lines` + 연결된 도구 검사 `sources` 발췌**로 넓힘(`_edit_scope`). 쟁점 줄 밖의 줄을 고치는 교정은 `line_outside_issue`로 거절 | `finalize.py` `_edit_scope`, 교정 루프 |
| 2 | 계산값 무단 삽입 금지 | 도구가 완료(passed/failed)한 검사의 terms·limit·연산 결과·details 수치는 **`[확인 필요: …]` 안에서만** 허용(`_computed_numbers`, `_text_problem(tool_numbers)`). 본문 사실로 단정하면 `unsupported_number` | `finalize.py` |
| 3 | mock이 교정 0·검사 0 | **scripted mock** `analyze/finalize_demo.py`: 오류를 심은 계획서 패턴이 payload에 있으면 그 줄을 앵커로 issue 4·checks 3·edit 4를 낸다. 라벨 `generator: mock`·"mock 테스트 결과" 알림 유지. 패턴이 없으면 기존 정직한 기본 mock | `finalize_demo.py`, `llm.py` 등록 |
| 6 | `unchecked`가 보류와 미검사를 겸함 | `issues[].unchecked_reason`: `no_tool_check`(판단 보류) / `도구 실행 불가`·`tool_unavailable`·`cancelled`·`ambiguous_…`(미검사) / `review_incomplete`. `corrected_lines` 추가 | `finalize.py` `_unchecked_reason` |
| — | 결합 기준에서 시간 초과 테스트 1건 실패 | `test_http_timeout…`가 50ms 상한을 bundle 생성 **전**에 걸어 결합 기준(SEC-7 입장 검사)에서 revise 호출이 먼저 504. 상한 설정을 bundle 뒤로 옮김(검사 의도 불변) | `tests/e4/test_finalize_api.py` |

지어내기 금지 반례(`tests/e3/test_finalize_gate.py`, 실제 Z3): 새 수치 `500명`(본문·자리표시 안 모두) · 범위 밖 줄의 기관 `서울대학교` · 범위 밖 줄의 수치 `99` · 달성 주장 `이미 검증했다` · 범위에 없는 낱말 `새로운 실험 장비` · 이메일 · 마크업 → 모두 거절, 거절문은 응답 직렬화에 없음. 반대로 다른 쟁점 줄의 낱말·수치(`추가 항목은 4이다`)와 자리표시 안의 계산값(`항목 합 7`)은 적용. 도구가 안 돌면(`final_tools` 없음) 계산값 7도 거절.

## 3-1. C-2(VER-FIN 조건부)와 V-finalization(e630d23) 지적 수정

| 지적 | 재현(검증자) | 수정 | 회귀 테스트 |
|---|---|---|---|
| C-2 ① / F5 확정 문안 상한 우회 | `confirmed_text` 14만 자·긴 토큰이 200 | `api/finalize.py`: 모델 검증 직후 서빙 상한 적용 — 글자 `max_plan_chars` 초과 413 `too_large`, 공백 없는 토큰 `max_token_chars` 초과 422 `long_token`(정규식·게이트 실행 전). 엔진 자체 상한 200,000자(모델 호출 0회, R8) | `tests/e4/test_finalize_c2.py::test_confirmed_text_gets_the_same_serving_caps_as_plan_text`, `tests/e3/test_finalize_vfix.py::test_r8_…` |
| C-2 ② preflight가 이벤트 루프에서 동기 실행 | — | `_preflight()`로 묶어 `asyncio.to_thread` | `test_preflight_runs_off_the_event_loop`(작업 스레드에서 실행 확인) |
| C-2 ③ 정규식 이차 시간 | 줄바꿈 2만 개 `contains_identity` **21.8s**, 글자 2만 개 `unsupported_facts` **9.7s** | `AUTHOR_SIGNATURE_RE` `^\s*`→`^[ \t]*`, `_ENTITY_RE` `{2,}`→`{2,40}`(`\s+`→`[ \t]+`). `AssembleRequest.revision/decisions` 안 문자열 8,000자·깊이 24 상한(`bounded_strings`, 422) | `test_identity_and_entity_regexes_are_linear_on_hostile_input`(4종 < 1s), `test_revision_strings_are_bounded`(줄바꿈 9,000개 제안 → 422, < 2s) |
| C-2 ④ / F-8·F-9 정직성 | 연구자 `confirmed_text`도 server_signed; UI가 mock을 "생성 방식 별도 확인"으로 표시 | 응답에 `text_source`(`server_assembled`/`researcher_confirmed`)·`provenance`{inputs_signed, coupled, coupling, researcher_text} 추가(계약 추가만). 연구자 문안은 항상 `client_submitted_unverified`·서명 없음·알림. UI `originText`가 `finalization.generator`를 읽고 연구자 문안을 "연구자 입력 문안 · 서버 서명 없음"으로 표시 | `test_researcher_confirmed_text_is_labelled_user_input_and_never_server_signed` |
| F6 개별 서명의 결속 승격(A3~A6, B1 원칙) | result A의 revision + 카드 제목이 다른 result B(각각 정상 서명) → server_signed | `coupled_provenance(result, revision)`: 세션·plan 일치, 카드 id·risk_code·title 일치, 카드 근거 ⊆ evidence_pool ⊆ (result evidence ∪ revision records), 해석·수정 이유의 인용 id ⊆ pool. 어긋나면 `client_submitted_unverified`·서명 없음·알림 | `test_individually_signed_but_uncoupled_inputs_are_not_promoted`(H1 재현: `card_mismatch`, 세션 불일치), `test_coupled_provenance_unit_cases` |
| F1 중복 검사 id가 실패를 덮음 | 같은 id 두 제약(실패·통과) → resolved/completed | 검사 id가 비었거나 중복이면 `incomplete`로 중단(모델 교정 호출 0). 고유 id면 첫 실패가 `unresolved`로 남음 | `test_f1_duplicate_check_ids_are_refused_not_overwritten` |
| F3 짧은 한국어 주장·부정 변경 적용 | `치료 효과 입증`, `효과 입증`, `방법을 안 검토한다.` 적용 | 2글자 이상 한국어 낱말(조사 제거)까지 근거 범위와 대조하는 `_grounded_words`; 새 부정(안·못·않·없·아니·불가·금지·제외·not…)은 `negation_change` | `test_f3_short_korean_claims_and_negations_are_rejected`(6건 거절, 정상 다듬기 1건 적용) |
| F3-R9 쟁점 밖 줄 수정 | 1행 쟁점으로 3행 수정 적용 | `line_outside_issue` 거절(§3 #1) | `test_edit_outside_the_issue_scope_is_rejected` |
| F4 수정 뒤 옛 인용으로 재검사 | 순환 수정 뒤 `unchecked/source_mismatch` | 재검사 때 코드가 수정된 줄로 발췌를 다시 결속하고, 그 줄에 더는 없는 선행 edge를 제외한 뒤 같은 도구를 돌린다(`_rebind_for_recheck`, `details.rebound_to_corrected_lines`). 수치가 사라지면 `unchecked`(통과 아님) | `test_f4_structural_fix_is_rechecked_against_the_corrected_text`(NetworkX failed→passed, resolved, completed), `test_f4_vanished_number_after_correction_is_unchecked_not_passed` |
| F3 미결 표시와 완료 판정 | 자리표시가 남아도 completed | 최종 본문에 `[확인 필요: …]`가 남으면 `partial` | `test_placeholders_left_in_the_draft_keep_status_partial` |
| F2 원문 숫자로 지어낸 식(같은 항목 4회·다른 개념 합산) | Z3가 계산 | `final_tools.py`(C-1)는 FIN-TOOLS 담당이라 손대지 않았다. 엔진은 검사 항목을 그대로 넘긴다 | FIN-TOOLS |

UI 결정 반영: 최종 점검은 다시 채택을 묻지 않는 자동 수정 + 되돌리기다. 응답 `corrections[]`(줄·before·after·applied·reason)·`issues[]`(issue_id·kind·plan_lines·message·status·unchecked_reason·corrected_lines)·`tool_checks_before/after[]`(check_id·tool·status·details)로 수정별 원문·수정문·도구·근거를 되돌릴 수 있게 유지했다. 스키마는 추가만 했다.

## 4. 시연 fixture(FIN-UI 입력)

- 계획서: `neumann.analyze.finalize_demo.DEMO_PLAN`(AI4S, 전해액 이온전도도 GNN, 36줄). 심은 오류: ① 예산 항목 합 1200+2400+600 > 명시 상한 4000만원(**Z3** constraint sum/le → failed) ② 전도도 10 mS 를 1 S/cm 와 같다고 봄(**Pint** equality, 컨덕턴스 vs 전도도 → failed) ③ "데이터 정제 후 모델 학습" ↔ "모델 학습 후 데이터 정제"(**NetworkX** 선행 순환 → failed) ④ 가설 "점도에 반비례" ↔ 방법 "점도가 높을수록 증가"(논리 모순, 도구 없음 → `unchecked/no_tool_check` 판단 보류).
- 결과: 교정 **4/4 적용**(모두 원문 유지 + `[확인 필요: …]` — 계산값 4200만원은 자리표시 안), 고친 줄 도구 재검사 3건(값을 연구자가 정하기 전이라 여전히 failed → `unresolved` 정직 표기), status `partial`, counters {1,1,1,1}.
- 파일: `docs/reports/FIN-ENGINE_demo.json`(전체 흐름: fixture 분석 결과 → mock 수정 권고 → 결정(오류 줄 덮는 제안 기각, 데이터 절 제안 채택) → 조립 → `run_finalization` 응답 원문) · `FIN-ENGINE_demo_final.md`(본문·변경 이력·쟁점·도구 전후 표). 생성·검사: `python scripts/finalize_demo.py [--check]`. origin은 `client_submitted_unverified`(서명 없는 입력), generator `mock`.
- 실제 LLM(gpt-6.1-sol) 경로는 이 브랜치에서 한 번도 돌리지 않았다(호출 동결). 지시문·엄격 스키마의 실제 준수율은 미지수이며 실패 시 `incomplete`로 정직 표기된다.

## 5. 검증(명령과 출력)

```powershell
$env:NEUMANN_LLM_PROVIDER='mock'; $env:NEUMANN_LIVE_TESTS='0'; $env:NEUMANN_LIVE_LLM_OK='0'; $env:PYTHONUTF8='1'; $env:OPENAI_API_KEY=$null; $env:NEUMANN_PSEUDONYM_SALT=$null
$env:PYTEST_ADDOPTS='-p no:cacheprovider --basetemp C:/Users/User/AppData/Local/Temp/fin-engine-pt'
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/finalize tests/e3/test_finalize_gate.py tests/e3/test_finalize_demo.py tests/e3/test_finalize.py tests/e3/test_final_tools.py tests/e0/test_finalization_integration.py tests/e4/test_finalize_api.py tests/e4/test_finalize_ui.py -q
& C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/finalize_demo.py --check
& C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/verify.py
```

| 검사 | 결과 |
|---|---|
| 결합 기준(2a8c911) 집중 8파일(finalization 5 + samples + sec7_ingress + interface) | 151 passed · 3 skipped · **1 failed**(`test_http_timeout…`, 3회 재현 → §3 순서 수정) |
| 인터페이스 6 + 게이트 7 + 데모 4 + 기존 finalize 12 + final_tools 46 + e0 통합 2 + e4 finalize api 6·ui 1 (`7011d78`) | **84 passed / 44.6s** |
| 전체 `scripts/verify.py`(`7011d78`, 키·솔트 제거 환경, 중립 basetemp) | 보안 617개 · 계약 5개 · 테스트 통과 · **verify 통과**, 종료 0 |
| C-2·V-fin 회귀(e3 vfix 6 + e4 c2 7) + finalize api/ui/e0/gate/demo/tools/interface + revise/assemble/export/ui static 17파일 | **256 passed · 1 skipped / 95.4s**(첫 실행 3 failed → 게이트 순서·테스트 기대값·알림 순서 수정 뒤 재실행 45 passed) |
| `scripts/finalize_demo.py --check` · `tests/e4/revise_mock_data.py --check` · `git diff --check` | fresh · fresh · 통과 |
| 브라우저 `NEUMANN_UI_TESTS=1 tests/e4/test_finalize_browser.py`(index.html originText 수정 뒤) | (§7 최종 커밋 뒤 갱신) |
| 전체 `scripts/verify.py`(최종 커밋, 키·솔트 제거 환경) | (§7 최종 커밋 뒤 갱신) |

## 6. 못 한 것 · 다음

- 원 지시의 `POST /premortem/finalize`(jobs 경로)·md/docx 최종 초안 출력·(d) 인용/철회 대조 도구는 방향 수정으로 범위에서 뺐다. 기존 동기 `POST /premortem/revise/finalize`와 `.md` 내려받기로 시연한다. 최종 초안 Word는 후속.
- 서명·출처 결합(A3~A6 4반례, B1 원칙)은 최종화 경로도 기존 조립·출처 관문을 쓰므로 그쪽 수정에 따른다. 이 브랜치의 fixture는 서명 없는 입력이라 `client_submitted_unverified`다.
- 도구는 원문에 **명시된** 수치 제약·단위·선행 관계만 계산한다. 규칙 기반 checks 추출(감사 #4)과 Pint 레지스트리 캐시(#5)는 FIN-TOOLS 담당. 화면 가독화(#7·#8)는 FIN-UI(`unchecked_reason`·`corrected_lines`·`corrections[]`를 쓰면 된다).
- 게이트 완화는 독립 반례 재검증 대상이다(다른 모델). 낱말 게이트는 어절 단위라 조사·어미가 다른 같은 낱말은 새 낱말로 본다(보수적).

## 7. 커밋

| 해시 | 내용 |
|---|---|
| `2a8c911` | core-final f54ef1d + finalization b629789 결합(문서 충돌 2건 양쪽 유지) |
| `b35fc9a` | 도구 인터페이스(원 커밋 a3b973b cherry-pick) |
| `7011d78` | 게이트 확장·unchecked_reason·scripted demo mock·인터페이스 어댑터·시연 fixture·시간 초과 테스트 순서 |
| `adf7798` | C-2·V-finalization 수정: 확정 문안 상한(413/422)·preflight 스레드·출처 결속·연구자 문안 표시·정규식 선형화·문자열 상한·중복 검사 id·2글자 낱말/부정 게이트·수정 뒤 재결속 재검사·엔진 상한·자리표시 partial·UI originText |
| (다음) | 보고서 |
