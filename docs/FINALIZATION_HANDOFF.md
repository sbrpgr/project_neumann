# 최종 검사·교정 개발 인계 — 2026-10-01

## 인수 위치와 판정

- 작업트리: `C:/Users/User/.codex/worktrees/final-check/project_neumann`
- 브랜치: `codex/finalization-20261001`; 기준 UI/core `ff7e474`, 제품·계약 최종 내용 `e121eef`, 기존 종합 보고 `d403c06`. 최신 인계 커밋은 이 브랜치의 `git log -1`로 확인한다.
- 개발 주력 `codex-gpt-6.1-sol`, 독립 검증 `codex-gpt-6-sol`. 빌더 3명·독립 검증자 2명이 작업했고 root 포함 동시 실행 4명 이내였다.
- **후속 기능 후보 검증 PASS. main 병합·push·배포·기존 서버 조작 없음. 실제 OpenAI 호출 0.** 전체 제품과 과학적 타당성의 승인 판정은 아니다.
- 인수자는 먼저 `C:/Users/User/Desktop/project_neumann/docs/HANDOFF.md`의 최신 종료 절을 읽는다. 이 작업트리의 과거 core 상태 절은 현재 root 상태를 대체하지 않는다.

## 확정한 제품 흐름

불완전한 연구계획서와 실패·심사 이력에서 보강한 문안을 연구자가 검토한다. `수정 확정·검증` 한 번으로 조립, 의미 검사, 제한된 실제 도구 검사, 근거 게이트를 통과한 교정 1묶음과 대상 도구 재검사를 수행한다. 반환물은 완성도를 높인 **최종 연구계획서 초안**, 남은 쟁점, 수정·거절 이력이다. 무한 반복이나 모든 오류가 없다는 보장은 없다.

- 의미 검사 1회, 교정 제안 1회, 최대 8줄 교정 1묶음, 대상 도구 재검사 최대 1회. 실패·취소·근거 부족은 원문과 미완료 상태를 보존한다.
- Z3: 원문에 명시된 합계/곱·비교 제약. Pint: 명시 단위의 차원·변환. NetworkX: 명시적 필수 선행 관계의 순환. 모호한 조건·부정·근거 없음·도구 없음은 `unchecked`다.
- 의미 판단은 제품 LLM의 역할이며 이번 검증은 mock/scripted다. 임의 생성 Python·범용 실험 실행·새 사실의 발명은 구현 범위에 없다.
- 연구자 편집은 원 조립 id와 대조한다. 편집/선택 변경 때 이전 최종 결과가 무효화된다. 최종 초안 내려받기는 Markdown이며 Word 버튼은 기존 통합본임을 명시한다.

## 인수자가 찾을 파일

| 담당 | 진입점 | 검증/참고 |
|---|---|---|
| E3 도구 | `src/neumann/analyze/final_tools.py` | `tests/e3/test_final_tools.py`, `reports/FINAL-TOOLS.md` |
| E3 엔진 | `src/neumann/analyze/finalize.py`, `src/neumann/llm.py`의 추가 task | `tests/e3/test_finalize.py`, `reports/FINAL-ENGINE.md` |
| E4 API | `src/neumann/api/finalize.py`, `api/main.py`, `api/serving.py` | `tests/e4/test_finalize_api.py`, `API.md` |
| E4 화면 | `src/neumann/webui/index.html` | `tests/e4/test_finalize_ui.py`, `test_finalize_browser.py`, `reports/FINAL-API-UI.md` |
| PM 계약/결합 | `contracts/finalization.schema.json`, `pyproject.toml`의 `finalization` extra | `tests/e0/test_finalization_integration.py` |
| PM/검증자 보고 | `reports/FINAL-PM.md` | `reports/FINAL-INDEPENDENT.md`, `FINAL-UI-INDEPENDENT.md` |

API는 `POST /premortem/revise/finalize`다. 기존 조립 요청에 `submission_id`, 선택 `checks`·`confirmed_text`·`confirmed_base_id`를 추가한다. 응답은 `assembled`, `finalization`, `final_text`, `origin`, `finalization_sig`를 포함한다. 요청 중복 캐시는 프로세스 메모리 64건/10분이며 영구 저장이 아니다. 서명은 처리·무결성 표시이고 과학적 검증의 증명이 아니다. 정확한 요청/응답은 [API.md](API.md)를 따른다.

## 실제 검증과 재실행

- 집중 5경로: **68 PASS / 1.91초**; 다른 모델 독립 **68 PASS / 1.80초**.
- 실제 production HTTP+fixture 근거+mock LLM 브라우저: **1 PASS / 9.41초**. 한 클릭의 요청 1회, 결과/Markdown 일치, 편집 후 무효화, 연결 실패의 정직한 표시를 확인했다.
- 전체 `scripts/verify.py`: **2175 PASS·56 skipped / 121.53초, 보안 592개·계약 5개 PASS, 종료 0**. 코드/계약 내용 `e121eef`와 동일한 후보에서 실행했다. 이후 변경은 보고·인계 문서다.
- 최초 전체 2 FAIL은 임시 경로의 제품명 문자열이 기존 블라인드 판정 검사를 건드린 것이었다. 테스트를 바꾸지 않고 중립 임시 경로로 재실행했다.

기존 로컬 Python은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`다. 필요한 선택 의존성은 `pip install -e '.[dev,finalization]'`로 선언돼 있다. 전체 검사는 PM 단일 큐로 실행하고, mock·라이브 플래그 해제·중립 basetemp를 사용한다. `.env` 내용을 열거나 복사하지 않는다. 다음 명령은 PowerShell의 해당 후보 디렉터리에서 실행한다.

```powershell
$env:NEUMANN_LLM_PROVIDER = 'mock'
$env:NEUMANN_LIVE_TESTS = '0'
$env:NEUMANN_LIVE_LLM_OK = '0'
$env:OPENBLAS_NUM_THREADS = '1'
$env:PYTEST_ADDOPTS = '-p no:cacheprovider --basetemp C:/Users/User/AppData/Local/Temp/fr-final-handoff'
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e0/test_finalization_integration.py tests/e3/test_final_tools.py tests/e3/test_finalize.py tests/e4/test_finalize_api.py tests/e4/test_finalize_ui.py -q
$env:NEUMANN_UI_TESTS = '1'
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e4/test_finalize_browser.py -q
Remove-Item Env:NEUMANN_UI_TESTS
& C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/verify.py
```

환경 설정은 이 쉘 세션에만 적용하며 실제 API 승인을 부여하지 않는다. 독립 재검증은 빌더와 다른 모델로 한다. 기존 독립 보고서에 당시 HEAD/작업트리·실행 조건과 검증 범위가 기록돼 있다.

## 기존 core에서 넘어온 병합 차단 사항

root의 **02:34 KST 종료 인계**를 읽은 결과이며 우리 후속 기능의 전체 PASS로 해결됐다고 해석하지 않는다.

1. 정상 개별서명된 result/revision/assembled의 혼합이 trusted로 남는 출처 결합 A3~A6 4반례가 미해결이다. `out/codex/results/ASTRA-provenance-coupling-audit-evidence.md`와 `out/codex/core-final`의 최신 인계/보고를 확인한다. 최종화 경로도 기존 조립·출처 관문을 사용하므로 원 export owner의 수정과 교차 artifact 음성/양성 독립 검증을 함께 반영해야 한다.
2. `export audit.dropped_reasons`의 int/list 입력 HTTP 500이 최신 core 후보에도 잔존한다. 일반 의미적 근거 함의, UI의 mock 표시/JUDGE unknown CSV ID 등 별도 미완료 항목도 root 최신 인계 범위를 따른다.
3. core 최신 후보 `f54ef1d`(제품 `f713c58`)는 정책 test-only 수정 후 전체 재검증이 없다. 과거 전체 PASS를 최신 결합 후보의 PASS로 재사용하지 않는다.

## 통합 순서와 남은 작업

1. root 최신 인계와 `out/codex/final_dispatcher_manifest.md`를 읽고 승인할 core/UI 커밋을 고정한다. `ff7e474` 기준인 이 브랜치로 최신 core를 덮지 않는다.
2. PM이 별도 결합 후보를 만든 뒤 위 차단 사항의 원 owner 수정과 독립 검증을 반영한다. 후속 기능은 이 브랜치를 병합하거나 기준 이후 커밋을 순서대로 적용한다. `llm.py`, `api/main.py`, `api/serving.py`, `index.html`, 계약·의존성·문서의 충돌은 최신 보호 관문/표시/출처 수정을 보존하며 해결한다. 모델/기존 계약은 임의 변경하지 않는다.
3. 최종화 집중·브라우저, 출처 결합 4반례 및 export 오류 회귀를 고정된 **동일 결합 후보**에서 독립 검증한다. 이어 PM 단일 큐의 전체 `scripts/verify.py`를 통과시킨다. 실패는 원인과 HEAD를 기록한다.
4. 조건 충족 후 PM만 main 병합·push를 결정하고 HANDOFF를 갱신한다. 현재 8020/8099의 기동 HEAD는 미확인이다. Git 병합을 배포로 표시하지 않으며 서비스 반영/승인된 실 API 확인은 별도 절차를 따른다.
5. 후속 제품 과제: 최종 교정본 Word 출력, 대표 승인 후 실제 LLM 품질 확인, 원문 대비 근거 있는 보강 효과 평가. 실제 반려 확률 감소는 아직 측정하지 않았다. 범용 실험 실행은 별도 설계 범위다.

모든 빌더 변경·독립 보고는 커밋돼 있다. 이번 인계를 위해 새 서비스나 지속 실행 작업을 시작하지 않았다. 작업트리·브랜치를 인수 완료 전에 삭제/아카이브하지 않는다.
