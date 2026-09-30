# EXPORT-TITLE 결과

판정: **기능·관련 검증 PASS / 커밋 BLOCKED**. 제목 손실은 수정 전 재현됐고 수정 후 회귀 테스트가 통과했다. 공용 Git 메타데이터 쓰기 오류 때문에 현재 브랜치에 커밋하지 못했다. main 병합·push는 하지 않았다.

## 기준과 재현

- 현재 worktree: `out/codex/export-title`, 브랜치 `codex/export-title`, 시작 HEAD와 당시 로컬 origin/main은 `5eac066b6afee8c363aa26acee0b0fa513dc957c`였다. 시작 작업 트리는 깨끗했다.
- 읽은 규칙: 루트 `AGENTS.md`, 과제 공통 규칙, `out/dashboard/ui_design_spec.md`. 독립 검증 `out/codex/v-core-final/docs/reports/V-core-final.md`의 발견 3을 기준으로 했다(과제 지정 보고서 커밋 `303e38d`). 다른 worktree는 읽기만 했다.
- `git fetch origin main`: exit 1, 공용 `.git/worktrees/export-title/FETCH_HEAD` 쓰기 `Permission denied`. `git ls-remote origin refs/heads/main`: exit 128, GitHub 443 연결 실패. 원격 서버 최신 상태를 직접 확인했다고 주장하지 않는다.
- 작업 중 공용 origin/main은 `5093383361c1b5e1215a4218676e3658670f7969`로 갱신됐다. `git diff --stat 5eac066 origin/main`은 **docs/decisions.md 한 파일, 1줄 추가**였고, 수정 대상 API·UI·테스트 경로의 diff는 비었다. 따라서 최신 로컬 origin/main의 제품 코드·테스트는 첫 재현 기준과 같다.
- 재현: fixture 분석 결과 → 실제 mock 수정 권고 → 첫 수정안 채택 → `run_assembly(AssembleRequest(..., title='V core custom title', polish=True), provider='mock')` → 정상 서명·결정을 `/premortem/package`로 전송. HTTP 200, 통합본 출처 server_signed를 확인한 뒤 ZIP의 `revised_plan.md`를 검사했다. 실제 조립·서명·내보내기 API를 사용하며 fixture 기록 저장소와 mock provider만 사용했다.
- 수정 전 `tests/e4/test_export_title.py::test_signed_polished_custom_title_survives_zip`: **1 failed in 1.35s**, exit 1. API `markdown.history`에는 사용자 제목이 있지만 ZIP 문서에는 없었다. 원 보고서의 `custom_title_preserved=False`를 같은 제목·polish 조건으로 재현했다.

## 원인과 수정

조립 API는 요청 제목을 Markdown 이력과 DOCX에 넣었지만 제목 자체를 별도 메타데이터로 전달하지 않았다. ZIP의 `export_revision.render_files`가 본문·근거를 다시 렌더링할 때 제목 인자를 생략해서 기본 제목으로 바꿨다. 패키지 요청·manifest·README·다운로드 이름에도 제목 경로가 없었다. 화면의 ZIP·DOCX 파일명 파서는 `filename*`보다 ASCII 기본 이름을 먼저 읽었고, MD 이름은 수정본 id만 사용했다.

- `api/export_title.py`: 제목 표시·복원·파일명 헬퍼. 제목은 단일 줄·최대 200자이며 개인정보를 가린다. 파일명 제목 부분은 문자·숫자·공백·`_`·`-`만 남기고 공백은 `_`로 바꿔 최대 60자로 제한한다. 경로 구분자·제어문자·Windows 금지 문장부호·점 경로를 제거한다. 접두·id·확장자를 붙이고 RFC 5987 UTF-8 `filename*`로 전달한다.
- 조립 출력에 사용자 `title` 메타데이터를 추가하고 MD·DOCX·다운로드 이름에 전달한다. 계약 파일과 모델은 변경하지 않았다(기존 revised-plan 계약은 추가 속성을 허용한다).
- revised-plan 서명에서 `title`과 Markdown 이력 첫 줄의 제목 부분만 제외한다. 본문·각주·나머지 수정 이력·수정 내용·polish는 계속 서명한다. 제목 없는 기존 v1 서명은 예전 바이트 그대로 검증하는 호환 경로를 둔다. legacy 응답의 제목은 `markdown.history` 첫 제목 줄에서 복원한다.
- 패키지 요청은 선택 `title`을 받는다. 제목 우선순위는 명시한 내보내기 제목 → 통합본 title → 기존 이력 제목 → 기본 제목이다. ZIP 수정본·README·manifest·ZIP 파일명에 같은 제목을 사용한다. manifest의 `title_origin=user_input_unsigned`와 README는 제목이 사용자 입력이고 서버 서명 대상이 아님을 표시한다. ZIP 내부의 기존 9/11개 고정 파일명과 각주 결합 검증은 유지한다.
- 화면의 ZIP·DOCX 이름 파서는 UTF-8 이름을 우선하고 잘못된 인코딩·경로 형태를 안전한 기본 이름으로 처리한다. 서버 MD 이름도 사용자 제목을 사용한다. 수정 권고 없는 ZIP 요청에서도 계획서 제목을 보내며, 통합본이 있으면 그 제목을 보존한다. 화면 레이아웃·스타일·컴포넌트는 변경하지 않았다.

## 명령과 실제 측정

모든 Python은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`를 사용했다. 공통 PowerShell 환경은 다음과 같다. 테스트에서 환경변수의 값 출력·단언은 하지 않았다.

```powershell
$env:NEUMANN_LLM_PROVIDER='mock'
$env:NEUMANN_LIVE_TESTS='0'
$env:PYTHONPATH='src;.'
$env:PYTHONIOENCODING='utf-8'
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK -ErrorAction SilentlyContinue
$env:TEMP="$PWD/data/export-title-tmp"
$env:TMP=$env:TEMP
```

| 검사 | 명령 | 실제 결과 |
|---|---|---|
| red 재현 | `python -m pytest -q tests/e4/test_export_title.py --basetemp data/export-title-tmp/pytest --tb=short` (첫 단일 테스트, 제품 코드 수정 전) | **1 failed in 1.35s**, exit 1 |
| green 회귀 | 위 명령(완성된 제목 회귀 19개) | **19 passed in 1.39s**, exit 0 |
| 관련 전체 묶음 | 아래 명령 | **269 passed, 3 skipped in 10.63s**, exit 0 |
| 제목 브라우저 | `NEUMANN_UI_TESTS=1`, `python -m pytest -q tests/e4/test_export_title_browser.py --basetemp data/export-title-tmp/pytest-browser --tb=short` | **1 passed in 1.30s**, exit 0 |
| 보안 | `python scripts/verify.py --security` | 보고서 추가 후 **보안: 파일 666개 / verify 통과**, exit 0 |
| 계약 | `python -c "from scripts.verify import check_contracts; p=[]; print('contracts:', check_contracts(p)); print('problems:', p); raise SystemExit(bool(p))"` | **contracts: 5개 / problems: []**, exit 0 |
| diff | `git diff --check` | 출력 없음, exit 0 |

관련 전체 묶음의 정확한 PowerShell 명령:

```powershell
$env:NEUMANN_UI_TESTS='0'
$tests = @((Get-ChildItem tests/e4/test_export*.py | ForEach-Object { $_.FullName }),
           'tests/e4/test_revise_api.py', 'tests/e4/test_payload_signing.py',
           'tests/e4/test_revise_ui.py', 'tests/e3/test_assemble.py')
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest -q @tests --basetemp data/export-title-tmp/pytest --tb=short
```

검증 범위: 정상 signed·polish ZIP에서 제목과 MD 렌더 전체 동일, JSON/MD/DOCX 제목·다운로드 이름, 제목 변경 후 서명 유효, 본문·각주·이력·수정문·polish 변조 반려, 기존 서명 제목 복원, 파일명 문자 제한·255 UTF-8 바이트 이내, 제목 없는 기본값, 수정 권고 없는 9파일 ZIP, HTML 표시·개인정보 가림, 201자 요청 422.

Playwright는 headless Chromium의 새 context와 빈 81xx 포트의 로컬 mock HTTP 서버에서만 실행했다(8171 제외). 실제 제품 다운로드 함수들을 브라우저에서 실행하여 ZIP/DOCX 이름 파서·ZIP 요청 제목 전달·MD의 실제 파일 다운로드를 검사했다. 전체 사용자 흐름이나 시각적 화면 검증으로 확대 해석하지 않는다. 생성한 서버·브라우저는 finally에서 모두 종료했다. 사용자 Chrome·데스크톱·탭 목록 도구는 사용하지 않았다.

전체 묶음의 skip 3개는 명시 실행이 필요한 브라우저 테스트이다. 새 제목 브라우저 검사는 별도로 활성화해 통과했다. 기존 전체 UI 시나리오와 전체 저장소 pytest/전체 verify는 실행하지 않았으며, 관련 묶음·보안·계약 검사 PASS만 주장한다. UI에 제목 필드가 추가돼 기존 요청 형태 정적 검사의 필드 추출식을 확장했고, result/result_sig/decisions/title이 실제 PackageRequest에 허용되는지 계속 확인한다.

## 못 한 것과 인계

- `.env`는 열지 않았다(`Test-Path .env`: False). 실제 제품 LLM 호출·OpenAI 키 사용·원본 공개자료 변경·다른 worktree 수정·stash·하위 에이전트·main 병합·push 없음. 개발·재현·검증은 모두 mock이다.
- 최종 stage 시도: 수정 코드·테스트·보고서 10개 경로를 지정한 `git add`가 PowerShell 실행 결과 exit 1, `Unable to create '.../.git/worktrees/export-title/index.lock': Permission denied`로 실패했다. FETCH_HEAD도 같은 쓰기 제한이다. stage가 실패해서 commit은 실행하지 않았다. 권한 정책을 우회하거나 Git 메타데이터를 다른 곳에 만들지 않았다. **보고서와 변경은 현재 worktree에 미커밋 상태로 남아 있다.**
- 빌더 자체 검사이며 독립 검증은 하지 않았다(하위 에이전트 위임 금지). 작업자는 Codex, 세션이 정확한 모델 ID를 제공하지 않아 지정 모델 `codex-gpt-6.1-sol`의 실행 여부를 자체 증명할 수는 없다. PM이 실행 배정 기록으로 확인해야 한다.
- PM 다음 작업: 이 worktree의 변경과 보고서를 리뷰하고 Git 쓰기 권한을 복구한 세션에서 현재 `codex/export-title` 브랜치에 `[EXPORT-TITLE]` 커밋을 생성한다. 독립 검증 뒤 PM이 main 병합을 진행한다. 제목은 사용자 메타데이터라는 점과 새 서버에서 기존 v1 서명을 검증하는 호환 범위를 확인한다.
- 완료 전달: 과제 지정 PowerShell `Invoke-RestMethod`로 `http://127.0.0.1:8099/api/inbox`에 Codex → Claude 한 줄 결과(검증 PASS·보고서 경로·커밋 차단)를 POST했다. 실제 출력 **dashboard inbox: POST succeeded**, exit 0. 8099에는 이 승인된 메시지 POST만 했고 시험 서버는 띄우지 않았다.
