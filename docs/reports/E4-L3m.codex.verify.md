# E4-L3m 독립 검증 (Codex)

**판정: PASS — 고정 HEAD `8803fddae793d39b038bac5bb1aee22bf4ac3d1c`의 반응형 완료 기준.** E4-L2f 통합 화면은 이 판정에 포함하지 않는다.

- 작업 트리: `C:\Users\User\Desktop\project_neumann\.claude\worktrees\s2-E4-L3m`; 브랜치 `task/E4-L3m`; 검증 시작 HEAD `8803fdd`, 변경 없음.
- 검증 모델: `codex-gpt-6-sol` (PM 지정). 대상 커밋의 빌더 기록은 `claude-opus-5.5`.
- 규칙: `AGENTS.md`, 빌더 보고서 `E4-L3m.md`, 이전 검증 `E4-L3m.verify.md`, PM의 이번 검증 과제를 읽었다. 계획서 `00_구현_계획서.md`는 읽기 전용으로 확인했다. 저장소 안에 별도 E4-L3m 과제 문서는 찾지 못했다.
- 제품 코드·테스트 코드 수정 없음. `.env` 내용과 키 값 미열람. 각 테스트 프로세스에서 provider `mock`, `NEUMANN_LIVE_TESTS=0`, `NEUMANN_LIVE_LLM_OK`·`OPENAI_API_KEY` 해제. 작업 API 응답은 Playwright에서 가로챘고 외부 요청 0건이었다. 실제 OpenAI 호출 0건.

## 완료 기준별 측정

venv `C:\Users\User\.venvs\neumann\Scripts\python.exe`, 테스트 서버는 각 실행이 소유한 8150·8177만 사용했고 종료 후 두 포트의 LISTEN이 없었다. 8010·8020·8099는 건드리지 않았다.

| 기준 | 명령·측정 출력 | 결과 |
|---|---|---|
| 대상 고정·범위 | `git rev-parse HEAD` → `8803fddae793d39b038bac5bb1aee22bf4ac3d1c`; `git status --short --branch` → `## task/E4-L3m`; `git diff main...HEAD --name-only` → E4 웹 UI·반응형 테스트·보고서·사진만 | PASS |
| UI 목표 검사 | `NEUMANN_UI_TESTS=1 NEUMANN_LLM_PROVIDER=mock NEUMANN_LIVE_TESTS=0 python -m pytest tests/e4/test_responsive.py -q -s -p no:cacheprovider --basetemp <out/codex>` (위 venv, live 플래그·키 제거) → **1 passed in 39.25s** | PASS |
| 경계 폭·넘침 | 별도 8177 서버로 `test_responsive._run`의 원시 계측값을 다시 수집. 입력/대기/리포트 `scrollWidth`: 390=`390/390/390`, 601=`601/601/601`, 616=`616/616/616`, 768=`768/768/768`, 1440=`1440/1440/1440`. 모든 폭 리포트의 화면 밖 요소/글자 잘림/형제 겹침=`0/0/0`; `check(res)` 위반 0건 | PASS |
| 터치·iOS 입력칸 | 390px 결정 버튼 최소 44px, 단계 탭 최소 45px, 근거 번호 표시 높이 20px이나 위·아래 10px 바깥 hit test 둘 다 참. 390/601/616/768px의 서랍 탭·닫기·떠 있는 버튼=`44/44/44px`. 390px `textarea` 글자 16px | PASS (Chromium 계측) |
| 서랍·초점 | 네 좁은 폭 모두 열 때 `role=dialog`, `aria-modal=true`, 초점 서랍 안. Tab·Shift+Tab 순환, 닫기·Esc 뒤 여는 요소로 초점 복귀 모두 참. 1440px 근거 번호 클릭 뒤 패널로 초점 이동 거짓 | PASS |
| 푸터·오류 | 390/601/616/768px 맨 아래 떠 있는 버튼과 푸터 글자 겹침 `0px²`. 콘솔 오류/페이지 오류/실패 요청/외부 요청=`0/0/0/0` | PASS |

첫 pytest 시도는 제품 실행 전에 기본 `%TEMP%\pytest-of-User` 접근 거부로 setup 오류였다. `--basetemp`를 허용된 `out/codex`에 두고 재실행해 통과했다. 전체 `scripts/verify.py`는 PM 큐 담당 지시로 실행하지 않았다.

## 한계와 다음

1. 이 검사는 Chromium 창 크기 에뮬레이션이다. iOS Safari의 실제 확대 동작과 실기기 터치는 측정하지 못했다.
2. 리포트는 fixture 뷰이고 작업 API의 queued→running→done 응답을 브라우저가 가로챘다. 실제 분석 파이프라인의 모바일 결과는 이 검사의 범위 밖이다.
3. `task/E4-L2f`는 이 HEAD의 조상이 아니다(`git merge-base --is-ancestor task/E4-L2f HEAD` → 비통합). E4-L2f 통합 뒤 내보내기 화면 390/768px과 CSS 꼬리 충돌을 PM이 별도 확인해야 한다. 현재 고정 HEAD의 PASS를 통합본 PASS로 확대하지 않는다.
4. 근거 번호의 44px은 가상 누름 영역으로 확인했다. 인접 번호 사이의 모든 접점을 실기기에서 재지는 않았다.
5. PM은 이 보고서와 고정 HEAD를 검토한 뒤 통합·전체 verify 관문을 맡는다. 검증자는 main 병합·push·tag를 하지 않았다.
