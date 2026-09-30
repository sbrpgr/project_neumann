# UI-F9 — 최종화 debounce 및 다운로드 출처

판정: PASS (빌더 자체 검증). 2026-10-01 KST. 브랜치 `codex/ui-final`, 기준 HEAD `c07c440`.
builder: codex-gpt-6.1-sol

## 변경

- `V-COMBINED.md`의 F-9와 `v_combined_probe.py` 입력→조립→확정 순서를 확인했다. 입력 시 문안은 즉시 바뀌었지만 250ms 콜백이 다시 최종화를 지웠다.
- 뷰어 조립 시작과 확정 요청 전에 대기 편집 타이머를 취소하고 저장한다. 지연 콜백은 상태 객체·최종화 세대를 비교하고 저장·화면 갱신만 한다. 실제 입력 변경 시 이전 조립 응답도 무효화한다.
- 같은 값의 입력 이벤트, 변경 없는 문단 저장, 변경 없는 확인 필요 입력은 점검 결과를 무효화하지 않는다.
- 최종 MD(기존 뷰어 및 단계형 완성 화면)와 ZIP의 `README.md`·`final_draft.md`에 **최종 점검 결과 자체**의 생성 방식·모델명·완료 여부·notices를 표시한다. `completed`만 완료이고 `partial`·`incomplete`는 확인할 항목이 남았다고 표시한다. 서명 없는 생성자·모델은 요청자 표기라고 명시한다.
- 빠른 순서·250ms 콜백을 확정 뒤로 보류한 순서·350ms 대조군의 실제 mock HTTP/Playwright 회귀를 추가했다. 최종 MD 파일명·본문, ZIP 고지·모델·완료 표시, 무변경 보존·실제 변경 무효화, 요청 1회 및 오프라인 실패 표시를 검사한다.
- 현재 기본 화면은 단계형 채택으로 이동한다. F-9의 보존된 카드 편집기를 검사할 때는 기존 `legacyReport` 설정을 사용하며 확정 버튼도 이 설정을 따른다. 기본 흐름·디자인 토큰·CSS는 변경하지 않았다. 기존 수정 UI 검사의 내보내기 키 기대값에 이미 추가된 `title`을 반영했다.
- 실제 mock 서버 공용 검사 helper는 빈 8140~8169 포트를 고르고 자식 프로세스에서도 dotenv 로더를 끈다. 모든 자체 서버는 finally에서 종료한다.

## 완료 기준별 측정

Python은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `PYTHONPATH=src;.`. 실행 전에 OPENAI 키·가명화 salt·라이브 허용 플래그를 제거했다. mock·로컬만 사용했으며 `.env` 열기, 환경변수 값 출력·단언, 실제 제품 LLM 호출, 사용자 Chrome·데스크톱·탭 목록, 하위 에이전트는 사용하지 않았다. 런타임 실행기·이미지는 이 worktree의 무시 경로 `out/codex/`에만 있다.

```powershell
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK -ErrorAction SilentlyContinue
$env:PYTHONPATH='src;.'
$env:PYTHONUTF8='1'
$py = 'C:/Users/User/.venvs/neumann/Scripts/python.exe'
& $py out/codex/ui_f9_run.py pytest tests/e4/test_fin_static.py tests/e4/test_fin_ui.py tests/e4/test_revise_ui.py tests/e4/test_finalize_browser.py tests/e4/test_finalize_ui.py tests/e4/test_ui_final_design.py tests/e4/test_export_finalization.py tests/e4/test_revise_static.py -q --tb=short
```

출력: **46 passed in 81.47s (0:01:21)**. 요구된 `test_fin_ui.py`·`test_fin_static.py`·`test_revise_ui.py` 포함. F-9 회귀 세 경우 모두 통과. ZIP의 서명 누락·위조·결합 불일치·연구자 문안·개인정보 마스킹 검사도 통과했다.

`& $py out/codex/ui_f9_run.py negative`: 수정 전 HEAD의 HTML을 메모리에서만 제공하고 기존 legacy 화면 호환 훅만 적용했다. 실제 분석·권고·조립·최종화 응답은 그대로 mock 서버에서 받았다. **예상 실패: `window.__f9Drain()`이 1, 기대값 0**, `1 failed, 2 deselected in 7.71s`. 수정본의 동일 검사에서는 대기 타이머 0이며 350ms 뒤에도 최종화 상태와 최종 MD가 유지된다. 따라서 항상 통과하는 검사가 아니다.

`& $py out/codex/ui_f9_run.py shots`: `problems: []`, 콘솔·페이지 오류 0, 스크린샷 14개. 390px의 입력·분석·채택·수정 계획서·최종 점검·완성 모두 `scrollWidth=clientWidth=390`; 375 입력과 768 채택·문서도 넘침 0.

`& $py out/codex/ui_f9_run.py layout`: 1440·390px × 여섯 단계, 스크린샷 12개와 `out/codex/UI-F9/layout/metrics.json`. 전 단계 가로 넘침 0. 분석 대기 중 주 버튼 0, 나머지 단계 각각 1. 완성 화면 1440·390 이미지를 직접 확인했다. `test_ui_final_design.py`: 토큰 밖 색 0, 글자 크기 14·16·20·28만, Pretendard 한 종.

`& $py out/codex/ui_f9_run.py security`: **보안: 파일 805개 / verify 통과** (`scripts/verify.py --security`, 보고서 포함 재검사). `git diff --check`: 출력 없음, 종료 코드 0.

초기 검사에서 오래된 report 화면 대기와 전환 훅, 모달 밖 동명 버튼 선택, 기존 `title` 기대값 누락을 발견했다. 현재 화면에 맞게 검사 진입점을 명시하고 고친 뒤 위의 최종 통합 실행을 통과했다. 전체 `scripts/verify.py` 및 별도 독립 검증은 이 작업에서 실행하지 않았다.

## 인계

사용자가 git 쓰기 명령을 금지하고 Claude 커밋을 지시했다. git add·commit·stash·checkout·merge·fetch·push는 시도하지 않았다. main 병합·라이브 테스트는 PM 담당이다. 커밋 대상은 다음 7개 파일이다.

- `src/neumann/webui/index.html`
- `src/neumann/api/export_finalization.py`
- `tests/e4/test_finalize_browser.py`
- `tests/e4/test_export_finalization.py`
- `tests/e4/test_ui_connect.py`
- `tests/e4/test_revise_ui.py`
- `docs/reports/UI-F9.md`

권장 제목: `[UI-F9] Preserve finalization across edit debounce and include export provenance`.
검증 줄: `validation: 46 passed; 1440/390 overflow 0; verify --security passed`.
빌더 줄: `builder: codex-gpt-6.1-sol`.

다음: Claude가 위 파일만 커밋하고 독립 검증·main 병합을 진행한다. 기존 미추적 `out_ui_final_*.py` 세 파일은 수정하지 않았다.
