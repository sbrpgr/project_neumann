# E6-L3b 보고서 — 시연 영상 녹화 스크립트

- 빌더: Claude Opus 5.5 · 브랜치 `task/E6-L3b` · 기준 커밋 main `1bbe3e2`
- 결과: 점검 서버(127.0.0.1:8010, 샘플 데이터)로 1회 녹화 성공. **36.8초 · 1440×900 · webm 3.62MB · 샘플 표시.** verify 통과

## 무엇을 했나

1. `scripts/record_demo.py`
   - Playwright(Chromium, 1440×900, `record_video_size`도 1440×900으로 지정. 기본값은 800×800 안으로 줄어든다)로
     입력 → 계획서 붙여넣기 → 분석 대기 → 리포트 → 위험카드 → 근거 열람 → (있으면) 내보내기를 사람 속도로 녹화
   - 사람 속도: 단계마다 멈춤(`--pace` 배율), 가짜 커서(영상에 OS 커서가 안 찍혀서 붉은 점을 그려 움직임), 부드러운 스크롤
   - 화면 주석: 화면 아래 자막 `n/7 · 단계 설명`(`--no-captions`로 끔). 샘플 녹화에서도 거짓이 되지 않게 "실제"라는 말은 쓰지 않았다
   - 녹화 전 `GET /health`: `pipeline.state == "connected"`일 때만 `live`, 나머지(미연결·오류·필드 없음)는 모두 `sample`.
     샘플이면 파일 이름 `…_sample.webm`, 로그 줄마다 `[sample]`, JSON `"sample": true`, 화면 왼쪽 아래에 주황 표지
     "SAMPLE · 샘플 데이터 — 분석 결과 아님". 헬스가 연결이라 해도 `POST /premortem/view` 응답의 `_status.source`가 `sample`이면 샘플로 이름을 바꾼다
   - 서버가 응답하지 않으면 녹화하지 않고 종료 코드 2
   - 결과: `<out>/demo_<시각>_<sample|live>.webm` + 같은 이름 `.json`(길이·해상도·프레임 수·단계별 `t_start/t_end/status/note`·관찰값)
   - 길이·해상도는 webm(EBML) 헤더를 직접 읽는다(ffmpeg 없음). Duration 요소가 없으면 마지막 블록 타임코드로 잰다
   - 단계가 실패해도 그때까지의 영상과 JSON은 남기고 종료 코드 1, `error`에 사유
2. `tests/e6/test_record_demo.py` (16건, 네트워크 없이)
   - 순수 함수: 헬스 분류 5가지, 파일 이름, `--out` 경로 풀이, webm 헤더 읽기(손으로 만든 EBML: Duration 있음/없음, webm 아님)
   - 녹화 함수: 짧은 가짜 페이지(`set_content`) 녹화 → webm 생성·320×240·길이>0.5s·단계 순서·임시 폴더 정리 / 시나리오 실패해도 영상 보존
   - 시나리오 전체: 가짜 앱을 `context.route`로 띄우고 나머지 요청은 모두 abort. (헬스 미연결 → sample) · (헬스 연결 + 응답 sample → sample로 개명, live 파일 안 남음) · (연결 + pipeline + 내보내기 켜짐 → live, export ok) 3가지
   - 서버 다운이면 코드 2, 파일 0개

## 완료 기준별 측정

### 1회 녹화 (점검 서버 127.0.0.1:8010, 샘플 데이터)

```
$ NEUMANN_DATA_DIR=C:/Users/User/Desktop/project_neumann/data \
  python scripts/record_demo.py --base-url http://127.0.0.1:8010 --plan tests/fixtures/plans/plan.md --out data/video/
[record_demo][sample] health: pipeline unavailable · mode sample → 파일 이름·로그에 sample 표시
[record_demo][sample] 녹화 시작: http://127.0.0.1:8010 · plan.md (645자) · 1440×900
[record_demo][sample]      0.09s →    2.44s  input      ok
[record_demo][sample]      2.44s →    5.70s  paste      ok
[record_demo][sample]      5.70s →    7.50s  analyze    ok       응답 200 · source sample · 0.9s
[record_demo][sample]      7.50s →   14.05s  report     ok
[record_demo][sample]     14.05s →   20.14s  risk_card  ok       카드 2장
[record_demo][sample]     20.14s →   29.39s  evidence   ok       근거 #1
[record_demo][sample]     29.39s →   33.11s  export     skipped  내보내기 단계 비활성(준비 중)
[record_demo][sample] 영상: C:\Users\User\Desktop\project_neumann\data\video\demo_20260930-185420_sample.webm · 3.62 MB · 1440×900 · 길이 36.8s (webm Duration) · 벽시계 35.1s
[record_demo][sample] JSON: C:\Users\User\Desktop\project_neumann\data\video\demo_20260930-185420_sample.json
exit=0
```

| 항목 | 값 |
|---|---|
| 파일 | `data/video/demo_20260930-185420_sample.webm` (3,799,863 B) + `.json` |
| 길이 | 36.8s (webm Duration, 프레임 920 = 25fps × 36.8s) · 벽시계 35.1s(끝의 약 1.7s는 컨텍스트 종료 중 프레임) |
| 해상도 | 1440×900 (webm 헤더) |
| 헬스 | `unavailable` · mode `sample` · "분석 파이프라인 미연결(샘플 데이터)" |
| 응답 | `POST /premortem/view` 200 · `_status.source=sample` · 0.86s |
| 타임스탬프 기준 | `new_page()` 직전. 영상 시작과의 차이 ≤ `t0_lag_s` 0.094s |

단계 타임스탬프(초):

| 단계 | 시작 | 끝 | 상태 |
|---|---|---|---|
| input 입력 화면 | 0.09 | 2.44 | ok |
| paste 계획서 붙여넣기 | 2.44 | 5.70 | ok |
| analyze 분석 대기 | 5.70 | 7.50 | ok (응답 0.9s) |
| report 리포트 | 7.50 | 14.05 | ok |
| risk_card 위험카드 | 14.05 | 20.14 | ok (2장) |
| evidence 근거 열람 | 20.14 | 29.39 | ok (근거 #1 → 계획서 16행) |
| export 내보내기 | 29.39 | 33.11 | skipped (화면에 "준비 중") |
| 끝 자막 | 33.11 | 36.8 | — |

영상 자체 확인: 녹화된 webm을 Chromium `<video>`로 디코드해 각 단계 중간 시각의 프레임을 뽑았다(`docs/reports/E6-L3b_frames.png`).
브라우저가 잰 길이 36.8s, 여덟 프레임 모두 그 단계의 자막(1/7 … 7/7, 끝)과 화면이 맞고, 왼쪽 아래 SAMPLE 표지가 전 구간에 보인다.
(프레임 추출 스크립트는 검증용이라 저장소에 넣지 않았다: 파일 URL로 연 HTML에서 `video.currentTime` 이동 → canvas → 스크린샷)

### 테스트·verify

```
$ python -m pytest tests/e6 -q --durations=5
6.95s call  test_demo_flow_offline[unavailable-sample-False-sample]
5.99s call  test_demo_flow_offline[connected-pipeline-True-live]
5.92s call  test_demo_flow_offline[connected-sample-False-sample]
2.37s call  test_record_short_fake_page_makes_webm
16 passed in 24.68s

$ python scripts/verify.py
142 passed, 2 skipped in 25.06s     # skip 2건은 기존 DISAPERE 원본 없음(NEUMANN_RAW_DIR), 이 과제와 무관
보안: 파일 84개
계약: 2개
테스트: 통과
verify 통과
```

영상 커밋 금지: 영상·JSON은 저장소 밖 공유 폴더(`project_neumann/data/video/`, gitignore)에만 있다. 저장소에 들어간 것은 코드·테스트·보고서·프레임 연락표 PNG(344KB)뿐.

## 바꾼 파일

- `scripts/record_demo.py` (새로)
- `tests/e6/test_record_demo.py` (새로)
- `docs/reports/E6-L3b.md`, `docs/reports/E6-L3b_frames.png` (새로)

## 결정한 것

- **worktree 기준**: worktree가 main보다 뒤(`d263c18`)라 과제 파일이 없었다. 커밋 전 `task/E6-L3b`를 main `1bbe3e2`로 fast-forward했다(main 자체는 건드리지 않음).
- **`--out data/video/`**: `data/`로 시작하는 상대 경로는 `NEUMANN_DATA_DIR` 아래로 푼다. worktree 안 `data/`에 영상이 쌓이지 않게. 환경변수가 없으면 cwd 기준.
- **샘플 판정은 보수적으로**: `connected`만 live. 응답 `_status.source=sample`이 헬스보다 우선(샘플을 live로 부르는 일이 없게).
- **붙여넣기**: 한 글자씩 치지 않고 `fill`로 한 번에(실제 붙여넣기처럼), 넣은 뒤 입력칸을 맨 위로 올려 계획서 첫머리가 보이게.
- **내보내기**: 현재 화면에서 IV 단계 버튼이 `disabled`("준비 중")라 커서만 가져가고 `skipped`로 기록. 리포트의 PDF 버튼(`window.print`)은 헤드리스 영상에 아무것도 안 남아 누르지 않았다. IV 단계가 켜지면 스크립트가 알아서 누르고 `ok`로 기록한다(테스트로 확인).
- **분석 대기**: 샘플 서버는 0.9초 만에 답해서 분석 화면이 짧다. 멈춰 세우지 않았다(실제 파이프라인에서는 그만큼 길어진다. 상한 `--analysis-timeout` 180초).
- **시험 녹화 1건**(`--pace 0.4 --stills`)이 `data/video/_trial/`에 남아 있다(공유 폴더 안, 지우지 않음).

## 못 한 것

- 최종 화면(v2 이후, 파이프라인 연결)으로 다시 녹화하는 것: 과제 배경대로 나중에. 명령은 같고 파일 이름이 `_live`가 된다.
- 내보내기 장면: 화면에 기능이 없어 영상에 없다.
- mp4 변환: PATH에 ffmpeg가 없다(Playwright 동봉 ffmpeg는 녹화 전용 축소판). 발표 도구가 webm을 못 틀면 변환이 필요하다(새 도구 설치는 승인 사항).
- 리포트 상단 샘플 안내문을 JSON에 옮길 때 `<b>` 뒤 띄어쓰기가 붙어 나온다(`…(샘플 데이터)입력한…`). 표시용 관찰값이라 그대로 둠.

## 다음 과제에 넘길 것

- **E4(화면)**: 스크립트가 기대는 선택자 — `body[data-view][data-ready]`, `#hdrState`, `[data-mode="text"]`, `#ta`, `#btnStart`, `#jobErr`, `#statusNotice`, `#s-map`, `#s-cards .rc`, `.cite[data-ev]`, `#pbody .pq`, `#pbody .lref[data-line]`, `#steps .stp`(내보내기). 바꾸면 `scripts/record_demo.py`와 테스트의 가짜 앱(`FAKE_APP`)도 같이 바꿔야 한다. 안정용 `data-testid`를 두면 좋다(제안).
- **PM**: 발표자료용 영상은 파이프라인 연결 뒤 `python scripts/record_demo.py --base-url <서버> --plan tests/fixtures/plans/plan.md --out data/video/`로 다시 녹화. `_sample` 파일은 발표에 쓰지 않는다. 업로드는 대표 승인 뒤.
