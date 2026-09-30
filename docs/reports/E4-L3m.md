# E4-L3m 반응형 화면(휴대폰·태블릿) 보고서

- 브랜치 `task/E4-L3m`(시작 88f1b51 → `git merge main` 세 번: c8ba766, ffd67f3(E4-L2d 작업 API 화면), 4753b3d(DISP-1 표시 이름). 모두 충돌 없음)
- 빌더 claude-opus-5.5 · provider mock만 사용(실제 OpenAI 호출 0) · 서버 8150(8010·8020 안 씀, 끝나면 종료 확인)

## 검증 지적 반영 (PASS-조건부 58191fc → 대표 지시로 2~5도 필수)

| # | 지적 | 고친 것(모두 `≤1180`·`≤600` 블록 안) | Playwright 측정(390 · 601 · 616 · 768) |
|---|---|---|---|
| 1 | 601~616px 리포트 가로 넘침(64자 세션 해시가 `.trace` 칸을 밈) | `≤1180`: `.trace { repeat(2, minmax(0,1fr)) }` + `.trace .mono { break-all }`. `≤600`은 1열 유지. 태블릿 2열을 1열로 바꾸지 않으려고 "옮기기" 대신 2열 판으로 넣었다 | 고치기 전(HEAD e93fe9d를 `--html`로): 601·616 리포트 scrollWidth **617**. 고친 뒤: 601/601, 616/616. 테스트 VIEWPORTS에 601·616 추가 |
| 2 | 터치 대상 44px | `≤1180`: 서랍 탭·닫기 `height:44px`, 떠 있는 버튼 `.btn.sm.pfab { height:44px }`(`.btn.sm` 32px를 이겨야 해서 선택자 셋). `≤600`: 결정 버튼 44px, 단계 탭 위아래 12px, 근거·행 번호는 `::after`로 누르는 자리만 위아래 12px(글줄은 그대로) | 탭 44 · 닫기 44 · 떠 있는 버튼 44(네 폭 모두). 390: 결정 최소 44, 단계 탭 최소 45, 근거 번호 20px인데 위·아래 10px 바깥을 눌러도 그 번호가 잡힘(`elementFromPoint`) |
| 3 | 서랍 초점 관리 | JS: 패널이 `position:fixed`(서랍)일 때만 열면 현재 탭 버튼으로 초점 + `role=dialog`·`aria-modal=true`, Tab/Shift+Tab이 서랍 안에서 돈다, 닫기·Esc·바깥을 누르면 연 요소(없으면 떠 있는 버튼)로 복귀 | 열면 초점 `button.on`(근거/계획서 탭), Tab·Shift+Tab 각각 (초점 요소 수+3)번 눌러도 늘 서랍 안, 닫기 뒤 초점 = 떠 있는 버튼, 근거 번호로 열고 Esc 뒤 초점 = 그 근거 번호. 1440: 근거 번호를 눌러도 초점이 패널로 안 감·dialog 속성 없음 |
| 4 | iOS 확대 방지 | `≤600`: `textarea.ta { font-size:16px }` | 390 입력칸 16px(601 이상은 14px 그대로) |
| 5 | 떠 있는 버튼이 맨 아래에서 푸터를 가림 | `≤1180`: 리포트 화면 `.foot { padding-bottom:84px }`(16 + 44 + 여유) | 맨 아래로 내렸을 때 떠 있는 버튼과 푸터 글자(`.foot .sc`·`.by`) 겹친 넓이 **0px²**(네 폭) |

병합으로 들어온 E4-L2d 작업 API 대기 화면(`POST /premortem/jobs` → `GET /premortem/jobs/{id}`)도 쟀다: 테스트가 작업 API를 가로채
queued → running · SEARCH 단계를 보여 준 뒤 fixture 뷰로 끝낸다(서버 파이프라인은 돌지 않음). 네 폭 모두 대기 화면 넘침 0.

## 무엇을 했나

1. `src/neumann/webui/index.html` 스타일 블록 끝에 `@media` 셋을 덧붙였다. 1181px 이상 규칙은 한 줄도 바꾸지 않았다.
   - `≤1180px`(서랍): 근거 패널을 오른쪽 서랍으로. 닫힌 서랍은 `visibility:hidden`(보이지 않는 채로 탭 이동되던 것 막음).
     **이전부터 있던 버그 수정**: `.wrap { z-index:1 }`이 쌓임 맥락을 만들어 서랍(z 31)이 scrim(z 30) **밑에** 깔렸다.
     좁은 화면에서 패널 안을 누르면 scrim이 눌려 패널이 닫혔다(Playwright: "scrim intercepts pointer events").
     이 폭에서만 `.wrap { z-index:auto }`로 맥락을 풀었다(종이 질감보다 위인 것은 문서 순서로 그대로).
   - `≤900px`(태블릿): 상단바 두 줄(단계 탭은 둘째 줄), 좌우 여백 16px, 히어로 제목 40px, 섹션 목차 줄바꿈,
     감사 카드의 삭제 목록을 전체 폭으로.
   - `≤600px`(휴대폰): 상단바 sticky 해제(두세 줄이라 따라오면 본문을 가림)·영문 부제 숨김, 히어로 30px·훅 19px,
     입력 카드 안쪽 여백 16/14px, 템플릿 선택기 5열 → 2열(라벨은 위로), 예시 세로 목록, 입력칸 240px,
     전송 고지는 접힌 상태 그대로(세 사실 한 줄 요약이 2~3줄로 접힘) + `scroll-padding-bottom` 96/200px,
     대기 타임라인 `단계 | 시간` / 메시지 두 줄, 리포트 제목 23px, 줄 스트립 15열 → 10열, KPI·상위 3·위험카드 크기 축소,
     체크리스트 `번호 | 행동(전체 폭)` / `위험 · 결정` 두 줄(머리행 숨김, 메모 열은 1180 이하에서 원래 숨김),
     추적 1열(긴 세션 해시가 줄을 밀던 것 `minmax(0,1fr)` + `break-all`), 근거 패널은 화면 전체 서랍.
2. JS는 최소로: 패널 탭 줄에 닫기 버튼 `.pclose`, 리포트에 떠 있는 여는 버튼 `.pfab`(근거 · 계획서, 오른쪽 아래),
   클릭 처리 두 줄(`[data-pclose]` → 닫기, `[data-popen]` → 패널 그리고 열기). 둘 다 1181px 이상에서는 `display:none`.
3. `tests/e4/test_responsive.py`(NEUMANN_UI_TESTS=1일 때만): 390×844 · 768×1024 · 1440×900에서 입력(빈 칸·예시 불러옴·파일 모드) ·
   대기(응답을 붙잡아 둔 채) · 리포트 · 서랍 열림을 재고 스크린샷을 찍는다. `--html`로 다른 판 index.html을 끼워 전후 비교.

## 완료 기준별 측정

### 가로 넘침 없음 · 16px 여백 · 잘림·겹침 없음 · 콘솔 오류 0

```
$ NEUMANN_LLM_PROVIDER=mock python tests/e4/test_responsive.py        # 서버 8150, 끝나면 종료
problems [] {'console_errors': 0, 'page_errors': 0, 'failed_requests': 0, 'external_requests': 0}
390  input 390/390 off0 clip0 ov0 pad[16,16] box[16,16] | job 390/390 ... | report 390/390 off0 clip0 ov0 pad[16,16] box[16,16]
768  input 768/768 off0 clip0 ov0 pad[16,16] box[16,16] | job 768/768 ... | report 768/768 off0 clip0 ov0 pad[16,16] box[16,16]
1440 input 1440/1440 off0 clip0 ov0 pad[36,36]        | job 1440/1440 ... | report 1440/1440 off0 clip0 ov0 pad[36,36]
```
(`scrollWidth/innerWidth`, off = 화면 밖 요소, clip = 버튼·라벨 글자가 상자를 넘침, ov = 형제 겹침, pad = `.wrap` 좌우 여백, box = 입력 카드·리포트 본문의 좌우 여백)

바꾸기 전(같은 검사, `--html`로 시작 커밋의 index.html을 끼움):
```
BEFORE 390 input 702/390 off9 clip1 pad[18,18] | job 707/390 off9 | report 708/390 off27 clip1 · 템플릿 5열(글자 한 자씩 세로) · 스트립 15열
BEFORE 768 input 768/768 off0 pad[18,18] | report 768/768 · 서랍 안을 누르면 scrim이 가로챔
```

### 근거 패널·실행 버튼

```
390 panel_closed  fixed  left 390 right 780  visibility hidden  pfab 보임
390 panel_fab     열림    left 0   right 390  닫기 버튼 보임 → 닫기 → left 390 hidden
390 panel_cite    #1 근거 번호로 열림 left 0 right 390, 패널 안 가로 넘침 없음 → 닫기 → hidden
768 panel_cite    열림    left 348 right 768 (420px 서랍) → 닫기 → hidden
1440 panel        position sticky, pclose·pfab 숨김(그대로)
390 run_btn  맨 아래로 내렸을 때 실행 버튼 위에 다른 요소 없음(48px 높이), 전송 고지 58px
```

### 1440 화면 불변(전후 픽셀 비교)

시작 커밋의 index.html(`git show HEAD:…`)을 `--html`로 끼워 찍은 것과 이번 판을 PIL로 비교:
```
1440 input  (1440, 1454) (1440, 1454) diff bbox None   ← 0픽셀 다름
1440 report (1440, 4536) (1440, 4536) diff bbox None   ← 0픽셀 다름
```
검증 지적 반영 뒤 다시(최신 main 4753b3d의 index.html vs 이번 판, 1440만 세 번씩):
```
main vs now  input  run1 11픽셀(카드 모서리, x 330·1106~1109 y 488~491) · run2 0 · run3 0
main vs main input  run1↔run2 같은 11픽셀 · run2↔run3 0      ← 첫 실행 렌더 흔들림, 이번 변경과 무관
main vs now  report run2 0 · run3 0   (run1은 리포트 머리 경과 시간 "2.1s"↔"2.0s" 글자만 다름)
```

### 테스트 · verify

검증 지적 반영·두 번째 병합 뒤:
```
$ NEUMANN_UI_TESTS=1 NEUMANN_LLM_PROVIDER=mock pytest tests/e4/test_responsive.py tests/e4/test_notice_ui.py tests/e4/test_templates_ui.py tests/e4/test_webui_upload_ui.py -q
4 passed in 122.25s
$ python tests/e4/test_responsive.py     # 390·601·616·768·1440
problems [] {'console_errors': 0, 'page_errors': 0, 'failed_requests': 0, 'external_requests': 0}
$ python scripts/verify.py
보안: 파일 473개 · 계약: 2개 · 테스트: 통과 · verify 통과
```
(`test_notice_ui`·`test_webui_upload_ui`가 다시 쓴 `E4-S06_*`·`E4-L1f_*` png는 내 파일이 아니라 `git checkout`으로 되돌렸다.)

첫 판:
```
$ NEUMANN_UI_TESTS=1 NEUMANN_LLM_PROVIDER=mock pytest tests/e4/test_responsive.py tests/e4/test_notice_ui.py tests/e4/test_templates_ui.py -q
3 passed in 46.67s          (병합 뒤. 기존 1440 화면 검사 둘도 그대로 통과)
$ python scripts/verify.py  (병합 뒤)
보안: 파일 427개 · 계약: 2개 · 테스트: 통과 · verify 통과
```
병합 전 첫 verify에서 `tests/e4/test_upload.py::test_api_amplification_limits` 1건이 시간 제한(<10초)으로 실패했다.
다른 과제가 같은 기계에서 돌던 부하 탓으로 보인다: 단독 재실행 `1 passed in 6.71s`, 병합 뒤 verify 전체 통과.

## 스크린샷 (`docs/reports/`)

| 파일 | 내용 |
|---|---|
| `E4-L3m_390_input.png`, `E4-L3m_768_input.png`, `E4-L3m_1440_input.png` | 입력(예시 1 불러옴). 창을 문서 높이로 늘려 찍어 sticky 전송 고지가 제자리(실행 버튼 바로 위)에 보인다 |
| `E4-L3m_390_report.png`, `E4-L3m_768_report.png`, `E4-L3m_1440_report.png` | 리포트 전체 페이지(요약·지도·위험카드·예상 심사평·체크리스트·추적). 좁은 화면의 오른쪽 아래 "근거 · 계획서"는 화면에 떠 있는 버튼이라 전체 페이지 사진에서는 첫 화면 높이에 찍힌다 |
| `E4-L3m_390_job.png`, `E4-L3m_768_job.png`, `E4-L3m_1440_job.png` | 대기 화면(작업 API running · SEARCH 단계) |
| `E4-L3m_390_panel.png`, `E4-L3m_768_panel.png` | 근거 번호 #1로 연 서랍(휴대폰은 전체 화면) |

리포트 데이터는 `/premortem/view` 응답을 가로채 넣은 fixture 뷰(`test_view_shots.rich_view`, 샘플 표시가 화면에 남음)다.

## 바꾼 파일

- `src/neumann/webui/index.html`: 스타일 블록 끝 반응형 규칙(약 110줄), 패널 문자열 한 줄(닫기·여는 버튼), 클릭 처리 두 줄,
  서랍 초점 관리(`openPanel`·`closeAll`·Tab 가두기, 약 25줄)
- `tests/e4/test_responsive.py`(새 파일)
- `docs/reports/E4-L3m.md`, `docs/reports/E4-L3m_*.png`

## 결정

- 근거 패널은 "아래로 쌓기" 대신 **서랍(펼치기)**. 아래로 쌓으면 근거 번호를 누를 때마다 리포트 끝까지 내려가야 한다. 휴대폰은 화면 전체, 태블릿은 420px.
- 휴대폰 상단바는 sticky를 푼다(두세 줄이라 따라오면 본문 첫 화면의 1/8을 가림). 태블릿은 두 줄 sticky 유지.
- 평가이력 지도 표는 휴대폰에서 카드 안 가로 스크롤(기존 `min-width:820px` 규칙). 표 열(분류별 칸)을 접으면 지도의 뜻이 사라져서 그대로 두었다. 페이지 자체는 넘치지 않는다.
- 휴대폰에서 숨긴 것: 상단바 영문 부제(RESEARCH PRE-MORTEM), 체크리스트 머리행. 사용자 이름은 남겼다(05_디자인_규칙 §10).
- 인라인 스타일(입력 카드 여백, 대기 제목 32px, 리포트 제목 30px)은 JS를 안 건드리려고 휴대폰 규칙에서만 `!important`로 덮었다.
- 입력 스크린샷은 창을 문서 높이로 늘려 찍었다(Playwright 전체 페이지 모드는 sticky 고지를 첫 화면 높이에 그려 입력칸 가운데에 떠 보인다).
- `test_notice_ui.py`를 회귀 확인으로 돌리면 `docs/reports/E4-S06_*.png`를 다시 쓴다. 내 파일이 아니라 `git checkout`으로 되돌렸다.
- 근거·행 번호는 44px 버튼으로 키우면 심사평 문단의 글줄이 벌어져서, 보이는 크기(20px)는 두고 `::after`로 누르는 자리만 넓혔다.
  위아래 이웃 줄의 번호와 누르는 자리가 조금 겹칠 수 있다(겹치면 뒤 요소가 잡힌다).
- 서랍 초점 관리는 패널이 `position:fixed`일 때만(1180px 이하) 한다. 1440에서 근거 번호를 누를 때 초점이 옮겨가면 기존 동작이 바뀐다.
- 대기 화면 검사는 작업 API를 가로챈다(fixture 결과). 서버의 mock 파이프라인을 돌리면 색인·임베딩 모델을 올려야 해 느리고 결과가 매번 달라진다.

## 못 한 것

- 실제 휴대폰 브라우저(iOS Safari·Android Chrome)와 가로 모드는 재지 않았다. Chromium 창 크기 에뮬레이션(`is_mobile` 없이)만 했다. 서랍은 `top/bottom:0`이라 주소창 높이(100vh) 문제는 피하게 했다.
- 내보내기 화면(단계 IV)은 이 판에서 아직 "준비 중"이라 재지 않았다. 마지막 병합 시점 main(4753b3d)에도 E4-L2f의 내보내기 화면은 없었다. PM이 E4-L2f를 먼저 병합하면 style 끝은 "L2f 내보내기 블록 먼저, L3m 반응형 블록 뒤" 순서로 맞춘다. E4-L2f가 들어오면 `.pk`·`.ai`(1180 이하 1열 규칙 있음)를 390에서 한 번 재야 한다: `NEUMANN_UI_TESTS=1 pytest tests/e4/test_responsive.py`의 BOXES·FIX 목록에 내보내기 선택자를 더하면 된다.
- 떠 있는 "근거 · 계획서" 버튼은 페이지 맨 아래에서 오른쪽 아래 몇 줄을 가린다(서랍이 열리면 숨는다).

## 다음

- E4-L2f 병합 뒤 390·768에서 내보내기 화면 넘침 재측정.
- 공개 주소로 심사위원이 휴대폰에서 열 때 첫 화면 확인(실기기 한 번).
