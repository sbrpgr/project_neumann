# FIX-TOOLS-LIVE-2 — 최종 점검 추출기 배선 복구

LLM 평가가 `checks: []`를 반환해도 제품 `finalize_plan`이 원문에서 코드를 통해 검사를 선택하고 실제 도구를 실행한다. 템플릿 3편과 라이브 battery 확정 문안을 오프라인 mock으로 측정해 Z3·NetworkX 실행을 확인했다. 화면 수정·제품 OpenAI 호출·git 쓰기·서버 기동은 수행하지 않았다.

## 변경

- `analyze/finalize.py`: 입력 제한·취소 확인 뒤 의미 평가 호출 전에 `extract_checks(text) → run_checks`를 실행한다. LLM 설정·평가 실패에도 코드 검사 결과를 보존한다. 기존 LLM/외부 검사와 합치고 코드 검사 id는 `code:`로 구분한다. 충돌 시 접두사를 추가하며, 기존 어댑터가 정규화한 LLM id도 원래 id로 복구한다.
- 실패·미검사 행을 `tool:` issue로 올려 correction 입력에 도구 결과·원문 앵커와 함께 전달한다. 코드 검사도 교정의 근거 범위에 포함한다. 감사 시간·오프셋은 새 수치의 근거로 허용하지 않는다.
- correction 반환 뒤 `extract_checks(final_text) → run_checks`를 다시 실행한다. 새 문안의 계산 인자로 재검사하고, 사라진 주장은 `claim_not_reextracted / unchecked`로 남긴다. 새 실패도 잔여 issue에 포함한다. 기존 LLM 검사는 수정된 줄에 대한 targeted recheck를 유지한다.
- `counters.tool_runs`와 `tool_attempts`에 `z3/pint/networkx/citation`별 수를 기록한다. `tool_runs`는 판정이 끝난 passed/failed 행만 세고, timeout·미설치·로컬 코퍼스 미확인은 실행 성공으로 세지 않는다. `tool_attempts`는 미검사 호출도 포함한다. 수정 전후 합산이다. 선택 수는 최초 코드 검사 수인 `code_selected_checks`, 표시 필드는 `code_checks_label="코드 선택 검사 N건"`이다.
- `contracts/finalization.schema.json`: 위 필드는 선택 사항으로 추가하고 citation kind를 추가했다. 기존 필수 필드는 그대로다. before 최대 48, after 최대 80, issue 최대 128로 확장해 LLM 16개와 코드 32개의 감사 기록을 버리지 않고 패키지 검증을 통과시킨다. 과제의 하위 호환 응답 확장 지시를 근거로 `docs/decisions.md`에 기록했다.
- citation 구현은 변경하지 않았다. 기존 `citation.configure`는 명시 경로의 로컬 색인·사후 상태 파일을 읽는 백엔드이고 네트워크 조회를 만들지 않는다. 설정이 없으면 `backend_not_configured / unchecked`이다. 기존 레지스트리 상한(z3/pint/networkx 10초, citation_lookup 5초)과 취소 이벤트를 그대로 경유한다. 로컬 fixture 인용 테스트는 socket.connect를 금지한 상태에서도 통과했다.

## 완료 기준별 검증

공통 실행 환경:

```powershell
$env:PYTHONPATH='src;.'
$env:NEUMANN_LLM_PROVIDER='mock'
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK,Env:NEUMANN_LIVE_TESTS,Env:NEUMANN_UI_TESTS,Env:NEUMANN_PROV_LABEL_UI -ErrorAction SilentlyContinue
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/finalize tests/e3 tests/e4/test_finalize_api.py tests/e4/test_finalize_c2.py tests/e4/test_finalize_ui.py tests/e4/test_finalize_browser.py tests/e4/test_export_finalization.py -q --tb=short
```

최종 출력 **1161 passed, 16 skipped in 55.04s**, exit **0**. 브라우저·라이브 opt-in 검사는 실행하지 않았다. 환경변수 값을 출력·단언하는 검사를 새로 만들지 않았다. 실제 키·salt를 제거했고 공통 테스트 설정이 `.env` 로딩을 닫는다.

`tests/e3/test_finalize_code_checks.py`에서 확인한 항목:

| 완료 기준 | 측정·판정 |
|---|---|
| 빈 LLM checks에서도 battery·binding 실행 | 각 Z3 2회·NetworkX 2회, 코드 선택 2건 |
| correction 입력 배선 | missing_sections 실패가 `tool:code:…` issue와 tool_checks에 포함됨 |
| 수정 뒤 재추출 | 분할 80/10/20 실패 → 원문 내 숫자 80/10/10 수정 적용 → computed 100·passed·issue resolved |
| 사라진 주장 처리 | 확인 필요로 바꾼 분할은 재추출 없음·unchecked 유지 |
| Pint·citation 로컬 실행 | 명시 단위 덧셈과 로컬 철회 DOI에서 각 2회·failed, socket.connect 금지 상태 |
| 취소·상한 | 기존 레지스트리의 20ms 시험 상한에서 timeout·unchecked, 취소 이벤트에서 cancelled·unchecked |
| 하위 호환·패키지 | 16개 초과 코드 검사 및 citation 행 스키마 검증, 새 선택 필드 없는 기존 v1 스키마 검증, 실제 finalize 응답 ZIP export |
| 감사 숫자 유입 방지 | computed 0.3만 허용, elapsed_ms 987.123·오프셋 543/654 제외 |

호출 제거 변이는 파일을 고치지 않고 별도 프로세스의 pytest 플러그인에서 `finalize.extract_checks = lambda text: []`로 적용했다. 동일 샘플 검사 실행 명령은 `pytest.main(['tests/e3/test_finalize_code_checks.py', '-k', 'samples_execute_tools', '-q', '--tb=short'], plugins=[RemoveExtraction()])`이다. 출력 **3 failed, 6 deselected in 0.14s**, exit **1**. 세 편 모두 `assert 0 >= 2`로 실패했다. 변이가 없는 테스트에서만 성공한다.

보안·계약 검사는 `scripts/verify.py`를 import한 뒤 `load_real_secrets=lambda: {}`로 비밀값 로더를 닫고 `security_worktree` 및 `check_contracts`만 실행했다. 보고서 포함 최종 출력 **Pattern/path security: 804 files; contracts: 5개; problems: 0; secret loader disabled**, exit **0**. 원본 전체 verify는 `.env`를 읽는 `load_real_secrets()` 때문에 직접 실행하지 않았다. 전체 verify 통과 또는 실제 비밀값 대조로 보고하지 않는다. `git diff --check`도 통과했다.

## 샘플 3편 오프라인 실행 수

모두 scripted MockProvider의 assessment=`{issues: [], checks: []}`, correction=`{edits: []}`로 `finalize_plan`을 실행했다. 아래 수는 수정 전+재검사 합계이며 각 도구는 전후 1회씩 실행했다. 원문을 덧붙이거나 도구 조건을 주입하지 않았다.

| 샘플·원문 | 코드 선택 | Z3 | Pint | NetworkX | citation | 결과 |
|---|---:|---:|---:|---:|---:|---|
| example-battery / templates/samples/electrolyte_gnn.md | 2 | 2 | 0 | 2 | 0 | partial |
| example-binding / templates/samples/protein_ligand_affinity.md | 2 | 2 | 0 | 2 | 0 | partial |
| example-operator / templates/samples/neural_operator_weather.md | 2 | 2 | 0 | 2 | 0 | partial |

세 편에서 Z3는 명시된 분할 비율 합을 passed로 판정했고, NetworkX는 필수 절 누락을 failed로 판정했다. 단위 계산식·검증할 인용이 명시되지 않아 Pint·citation은 0이다. 모든 도구가 모든 문서에서 실행되었다고 주장하지 않는다. 이 규칙 추출 범위는 전체 과학적 타당성 판정이 아니다.

추가로 `out/codex/final-live/data/final_test/final_live/example-battery/finalize.json`의 `finalization.input_text`를 읽기만 해 같은 빈 checks mock으로 실행했다. 코드 선택 **2건**, Z3 **2회**, Pint **0회**, NetworkX **2회**, citation **0회**, 결과 **partial**이다. binding은 라이브에서 확정 단계에 도달하지 못해 템플릿 원문으로 측정했다. 숫자와 상태만 저장한 측정 산출물은 이 worktree의 무시 경로 `data/fix_tools_live_measurements.json`에 있으며 커밋 대상이 아니다.

## 남은 일·인계

- 실제 서비스 LLM 재시험과 재기동은 PM/대표 승인 범위에서 수행해야 한다. 이 작업에서는 제품 OpenAI 호출이 없다.
- FIX-VCOMB E-4 변경과 결합할 때 `_run_checks`의 도구 실행을 레지스트리 경유 구현으로 유지하고, 이번 id 복구·counters 합산을 함께 유지해야 한다. 새 코드 검사는 이미 `run_checks → fin_tools.run_call → ToolRegistry.run`을 경유한다. 해당 레지스트리·citation 구현 파일은 수정하지 않았다.
- 독립 검증은 별도 작업에서 해야 한다. 이 보고서는 빌더의 자체 회귀 테스트이며 "같은 모델(gpt-6.1-sol), 별도 작업 판정"을 이미 받았다고 주장하지 않는다.
- 사용자 지시대로 `.git` 쓰기 명령·stash·커밋·main 병합·push를 시도하지 않았다. Claude가 현재 브랜치 `codex/fix-tools-live`의 변경을 파일 지정으로 커밋한다. 권장 제목: `[FIX-TOOLS-LIVE-2] 코드 선택 최종 검사 배선과 수정 문안 재검사`.
- 커밋 대상: `src/neumann/analyze/finalize.py`, `contracts/finalization.schema.json`, `docs/decisions.md`, `tests/e3/test_finalize_code_checks.py`, `tests/e3/test_finalize.py`, `tests/e3/test_finalize_demo.py`, `tests/e3/test_finalize_vfix.py`, 이 보고서와 `docs/reports/FIX-TOOLS-LIVE-2.md`.
- builder: codex-gpt-6.1-sol.

최종 판정 기록: **1161 passed, 16 skipped in 55.04s**. 코드 선택 검사·재추출·실패 전달·샘플 도구 실행·계약·패키지 회귀 통과. 라이브 서비스 판정과 독립 검증은 미수행.
