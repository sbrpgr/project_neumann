결과 브랜치 HEAD: `ba9f4407765a5e88ebdd902a670789769734f21f` (`codex/fin-combine`; Git 쓰기 차단으로 HEAD 미변경, 아래 결과는 미커밋 파일 결합 후보).

# FIN-COMBINE — 엔진·도구 결합 후보

상태: 코드 후보 작성·관련 검사·브라우저·전체 verify 완료(아래 중립 경로 조건). **Git 병합 이력·커밋은 미완료**이며 main 반영 승인으로 표시하지 않는다.

- 기반 FIN-ENGINE: `ba9f440`.
- 읽을 수 있는 origin/main: `5093383` (실제 GitHub fetch는 네트워크 제한으로 실패, 원격의 최신 HEAD 확인은 못 함).
- FIN-TOOLS: `f7ade06dd570081374c8f0c55f06560aa2d80fce`.
- 빌더 배정: `codex-gpt-6.1-sol`. 하위 에이전트 없음. 별도 작업자의 독립 검증은 미수행.
- 기록 시각: 2026-10-01 04:29 KST.
- 실제 제품 LLM 호출 0, mock만 사용. `.env` 존재 여부는 False이며 내용은 읽지 않음. 키·솔트·라이브 플래그를 자식 환경에서 제거했고 설정 파일 로딩도 막았다. main 병합·push·stash 없음.

## 결합한 것

Git 메타데이터가 쓰기 거부 ACL로 막혀 `FETCH_HEAD`, `ORIG_HEAD.lock`, `index.lock` 생성이 실패했다. Git 디렉터리 이동·ACL 변경·훅 우회는 하지 않았다. 읽기 가능한 Git 객체와 `git merge-file -p`로 **현재 worktree 파일만** 3-way 결합했다. 정식 `git merge`가 완료된 것은 아니다.

main 변경 15개와 FIN-TOOLS 변경을 순서대로 계산해 36개 파일을 결합했다. 문서 충돌 `docs/tasks/QUEUE.md`는 양쪽 내용을 보존했다. FIN-ENGINE v3 `ToolRegistry`의 개방 등록·시간 제한·실패 evidence 계약을 유지했다.

FIN-TOOLS 정규 이름은 `z3`, `pint`, `networkx`, `citation_lookup`이다. `arithmetic_sum → z3`, `unit_dimension → pint`, `structure → networkx` 별칭을 유지한다. 인용 조회도 v3 레지스트리에서 실행해 동일한 schema/evidence/timeout 경계를 공유한다. 코드 고정 유형 매핑을 이 이름과 맞췄고 자동 기본 등록은 사용자 구현을 덮어쓰지 않는다. `calculator`·`restricted_exec`는 기존 미구현 상태다.

## 미완 항목 마무리

| 항목 | 변경 및 실제 검사 |
|---|---|
| details.computed | `analyze/final_tools.py` 도구 경계에서 정확한 Fraction 합·곱을 계산해 완료된 Z3 결과의 `details.computed`로 방출. 실제 `3+4` 검사 결과 7, 데모 예산 4200 확인. 엔진은 합·곱을 계산하지 않음. |
| C-4 자리표시 | 모델이 제안한 자리표시를 기존 안전성 게이트로 검사한 후 코드가 고정 사유 코드·근거 줄 번호·완료 도구 계산값 템플릿으로 다시 생성. 모델 본문은 최종 자리표시에 복사하지 않음. 각 본문 120자 이내로 나누고 최종 수정 줄 12,000자 제한 유지. |
| F2 중복 항목 | 피연산자를 원문 줄·숫자 오프셋에 결속. 같은 원문 숫자 재사용, 중복 source 별칭, limit를 term으로 재사용, 숫자 일부만 잘라낸 발췌는 unchecked. 서로 다른 줄의 같은 값은 허용. |
| F2 혼합 개념 | 전체 원문 줄의 숫자 주변 개념·단위로 대조. 용량+온도, 예산+기간, 표본+실험, 불명확한 상이한 표지는 unchecked. 발췌를 잘라 개념을 지워도 전체 줄을 검사. |
| 데모 갱신 | `FIN-ENGINE_demo.json`·`FIN-ENGINE_demo_final.md` 재생성. 교정 4/4 적용, Z3/Pint/NetworkX 세 검사 모두 failed 유지, 의미 쟁점 unchecked, 전체 partial. 예산 4200은 확인 자리표시 안에만 있음. |

사유 코드는 `NUMERIC_CONSTRAINT`, `UNIT_DIMENSION`, `DEPENDENCY_ORDER`, `SEMANTIC_REVIEW`, `TOOL_UNCHECKED`, `TOOL_REVIEW`, `TOOL_COMPUTED`의 코드 소유 목록이다. 모델 prose로 새로운 사유 문장을 만들지 않는다. 반복 자리표시가 큰 템플릿으로 확장되면 수정안을 거절한다.

F2는 제한된 명시적 관계 검사다. 모든 연구 개념의 동치·관계나 과학적 타당성을 판정하지 않는다. 다른 표기 단위의 암묵적 환산은 허용하지 않고, 불명확한 합계는 판단 보류한다.

## 검증 명령과 측정

공통 PowerShell 준비:

```powershell
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK -ErrorAction SilentlyContinue
$env:NEUMANN_LLM_PROVIDER='mock'
$env:NEUMANN_LIVE_TESTS='0'
$env:PYTHONPATH='src;.'
$env:PYTHONUTF8='1'
```

Python은 모든 실행에서 `C:/Users/User/.venvs/neumann/Scripts/python.exe`를 썼다. 로컬 재현 harness는 `out/codex/fin_combine_checks.py`, `out/codex/local_neutral_paths.py`이며 실행 로그나 harness를 커밋 대상으로 지정하지 않았다.

| 명령 (`& C:/Users/User/.venvs/neumann/Scripts/python.exe` 뒤) | 출력 |
|---|---|
| `out/codex/fin_combine_checks.py targeted` | **322 passed, 1 skipped / 22.10s.** |
| `out/codex/fin_combine_checks.py browser -s` | 1 passed / 8.55s. Playwright headless, 빈 8181·8182 사용, 서버 종료. 한 클릭 최종화 1회·원문/화면/MD 일치·결정 변경 무효화·오프라인 실패 표시 확인. |
| `out/codex/fin_combine_checks.py demo` | status=partial, corrections=4/4, Z3/Pint/NetworkX failed. |
| `out/codex/fin_combine_checks.py demo --check` | demo fixture fresh. |
| 전체 verify 1차 | 2 failed, 2666 passed, 55 skipped / 175.30s. 보안 통과, 계약 5개. |
| 전체 verify 2차 | 2 failed, 2667 passed, 55 skipped / 174.29s. 보안 통과, 계약 5개. |
| E5 중립 경로 어댑터 적용 후 `tests/e5/test_judge_n5.py tests/e5/test_judge_run.py` | 18 passed / 0.60s. |
| `out/codex/fin_combine_checks.py verify` 최종 | **2669 passed, 55 skipped / 163.89s; 보안 파일 2091개·계약 5개·테스트 통과, verify 통과, 종료 0.** |
| `git diff --check` | 종료 0. |
| 보고서 포함 `out/codex/fin_combine_checks.py verify --security` | 보안 파일 2092개, verify 통과, 종료 0. |
| `git apply --reverse --check out/codex/final_task.patch` | 종료 0; 인계 패치가 현재 작업 코드와 일치. |

첫 두 전체 실행의 실패는 `test_briefs_for_n5_one_per_judge`, `test_claude_briefs_isolated`다. 판정문이 절대 임시 경로를 포함해 `project_neumann`이라는 디렉터리 이름이 블라인드 금칙어 `neumann`에 걸렸다. 허용된 샌드박스 임시 경로 역시 이 이름 아래였다. 저장소 밖 중립 경로 생성은 쓰기 거부됐다.

최종 전체 verify는 **두 E5 판정 모듈의 tmp_path에 실제 Windows 8.3 짧은 경로를 제공하는 시험 환경 어댑터**를 사용한다. 실제 파일·디렉터리는 동일하고 제품 코드·검사 단언·기대값·검사 수는 바꾸지 않았다. 이 조건 없이 현재 workspace의 긴 절대 경로로 실행한 결과는 위 2건 실패이며, 이를 숨기거나 일반 기본 실행 PASS라고 주장하지 않는다.

## 커밋·미완 및 다음

현재 branch HEAD는 첫 줄의 ba9f440 그대로다. 정상 `git merge --no-commit --no-ff origin/main`과 파일 지정 `git add -- docs/reports/FIN-COMBINE.md`는 Permission denied로 차단됐다. 30분 중간 커밋도 이 이유로 불가. 보고서가 커밋됐다고 주장하지 않는다.

보고서 지정 add와 `[FIN-COMBINE] Combine ENGINE v3 and FIN-TOOLS with grounded correction templates` 커밋도 각각 `index.lock: Permission denied`로 실패했다. 훅을 우회하지 않았으며 실제 새 커밋은 없다. 04:30 KST 8099 inbox에 위 결과와 Git 차단·보고서·패치 경로를 한 줄로 보고했고 `inbox_report_sent=true`를 확인했다.

권한 있는 PM 세션에서 FIN-ENGINE ba9f440 → 최신 main → FIN-TOOLS f7ade06 정식 병합을 수행하고, 개방 레지스트리 v3·위 도구 이름·문서 양쪽 보존을 유지해야 한다. 자체 변경 10개 파일의 인계 패치는 `out/codex/final_task.patch`다. 이 패치는 정식 결합 기준에서 적용할 용도이며 이미 적용된 현재 후보에 다시 적용하지 않는다. 데모를 다시 생성하고 별도 작업의 독립 검증·전체 verify 뒤 후보를 커밋한다. main 병합·push는 PM만 한다.

작업 트리에는 imported main/FIN-TOOLS 파일과 자체 수정이 함께 남아 있다. 저장소/폴더 전체 복사로 버전을 만들지 않았다. `out/codex/composition.json`에 결합 기준과 변경 파일을 기록했다.

임시 폴더 `UsersUserDesktopproject_neumannoutcodexfin-combineoutcodextmp-verify/` 삭제는 검증된 현재 worktree 내부 경로로도 도구 정책이 `blocked by policy`로 거부했다. 미추적 시험 산출물로 남았으며 **add 대상이 아니다**. Git add는 파일 지정으로만 시도했고 이 폴더·실행 로그·데이터를 지정하지 않았다.

실제 LLM 품질·실서비스·8020 라이브 확인·독립 검증은 하지 않았다. 시험 서버에는 8020·8099·8171을 쓰지 않았다. 8099에는 과제에서 허용한 최종 inbox 보고 POST만 사용한다.
