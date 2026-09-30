# E6-L3c 보고서 — 실서버 시연 영상 1차 녹화 + mp4

- 빌더: Claude Opus 5.5 · 브랜치 `task/E6-L3c` · 기준 main `b05de3c`
- 결과: **실서버 127.0.0.1:8010(v0, 파이프라인 연결)에서 1회 녹화**(19:32:02). 입력 → 예시 불러오기 → 분석(astra, 31.9초) → 리포트 → 위험카드까지 성공.
  **근거 패널 열기(6/7 단계)는 실패**: 녹화 스크립트의 클릭이 고정 머리글에 떨어졌다(원인·수정 아래). 재녹화는 하지 않았다(1회 규칙, 이후 대표 지시로 API 비용 중지).
- 산출물(공유 폴더, 커밋 안 함): webm 69.2s · mp4 69.2s · 편집본 mp4 28.4s. 모두 `_live`, 샘플 표시 없음.

## 영상 (C:/Users/User/Desktop/project_neumann/data/video/)

| 파일 | 길이 | 크기 | 형식 |
|---|---|---|---|
| `demo_20260930-193202_live.webm` | 69.2s (webm Duration, 1,730프레임) | 4,949,266 B | VP8 1440×900 (Playwright 원본) |
| `demo_20260930-193202_live.mp4` | 69.20s | 4,134,978 B | H.264 High · yuv420p · 1440×900 · 25fps · faststart · 소리 없음 (전체 그대로) |
| `demo_20260930-193202_live_edit.mp4` | 28.44s | 3,070,456 B | 같은 형식. 분석 대기만 ×4, 근거 단계 실패 직전에서 끝 |
| `demo_20260930-193202_live.json` | — | 2,949 B | 단계 타임스탬프·관찰값(`task: E6-L3c`) |
| `demo_20260930-193202_live_0{1,2,4,5}_*.png` | — | — | 단계 스틸(입력·예시·리포트·위험카드) |
| `health_20260930-193201_prerecord.json` | — | 1,050 B | 녹화 직전 `GET /health` 전체 응답 |

프레임 연락표(mp4에서 추출, 저장소): `docs/reports/E6-L3c_frames.png` — 2.5s 입력(범위 안내) · 5.5s 예시 불러오기 · 12s/32s 분석 실행 · 42s 리포트 · 49s 위험카드 · 51.6s 위험카드 근거 목록 · 60s 근거 단계(패널 안 열림).

## /health (녹화 직전, 19:32:01)

```
$ curl -s http://127.0.0.1:8010/health > data/video/health_20260930-193201_prerecord.json
status ok · version 0.0.1 · pipeline {'state': 'connected', 'reason': '', 'mode': 'pipeline', 'label': ''}
stages available: pipeline INPUT EVIDENCE RISK REVIEW ACTION TRACE llm models config 모두 True
routers: export·precomputed·templates·meta ok, neumann.api.upload missing
```

`classify_health` → `live` ("pipeline connected"). 샘플 모드가 아니어서 녹화했다.

## 녹화 (1회)

```
$ export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." NEUMANN_DATA_DIR=C:/Users/User/Desktop/project_neumann/data
$ python scripts/record_demo.py --base-url http://127.0.0.1:8010 --plan tests/fixtures/plans/plan.md --out data/video/ \
    --analysis-timeout 300 --stills --task E6-L3c
[record_demo][live] health: pipeline connected
[record_demo][live] 예시 불러오기: example-battery (plan.md)
[record_demo][live] 녹화 시작: http://127.0.0.1:8010 · plan.md (645자) · 1440×900
[record_demo][live]      0.09s →    3.30s  input      ok
[record_demo][live]      3.30s →    6.64s  paste      ok       example:example-battery · 645자 · 파일과 같음
[record_demo][live]      6.64s →   39.77s  analyze    ok       응답 200 · source pipeline · 31.9s
[record_demo][live]     39.77s →   46.48s  report     ok
[record_demo][live]     46.48s →   52.75s  risk_card  ok       카드 3장
[record_demo][live]     52.75s →   69.52s  evidence   failed   TimeoutError: Page.wait_for_selector: Timeout 15000ms exceeded.
[record_demo][live] 영상: …\data\video\demo_20260930-193202_live.webm · 4.72 MB · 1440×900 · 길이 69.2s (webm Duration) · 벽시계 69.5s
[record_demo][live] 화면 배지: 없음
[record_demo][live] 실패: TimeoutError: Page.wait_for_selector: Timeout 15000ms exceeded.
exit=1
```

단계 타임스탬프(원본 webm/mp4 기준 초. 기준 `new_page()` 직전, 영상 시작과 차이 ≤ `t0_lag_s` 0.094s):

| 단계 | 시작 | 끝 | 상태 | 화면 |
|---|---|---|---|---|
| 1/7 input | 0.09 | 3.30 | ok | 범위 안내 "AI 활용 과학 연구 계획서 전용 · 소재·화학·분자 · 단백질·생물·신약 · 물리·PDE·기후 · 신경과학 · 의료영상", 템플릿 5종·예시 3건. 커서가 범위 안내를 가리킴 |
| 2/7 paste | 3.30 | 6.64 | ok | "예시 불러오기 — 전해액 이온전도도 GNN (plan.md)" 버튼 클릭 → 입력칸 645자, `tests/fixtures/plans/plan.md`와 같음 |
| 3/7 analyze | 6.64 | 39.77 | ok | 클릭 7.83s → 리포트 39.75s(대기 31.9s). `POST /premortem/view` 200 · `_status.source=pipeline` |
| 4/7 report | 39.77 | 46.48 | ok | 요약: 유사 연구 10편 · 근거 문장 10건 · 위험카드 3장, 계획서 줄 스트립 |
| 5/7 risk_card | 46.48 | 52.75 | ok | 01 오차막대·절제실험 없는 성능 비교(0.42, astra 합성) → 근거 인용 #1~#5와 각 `원문 ↗` 링크, 계획서 대응 줄 |
| 6/7 evidence | 52.75 | 69.52 | **failed** | `#1` 클릭이 머리글에 떨어져 근거 패널이 안 열림. 15초 대기 뒤 종료 |
| 7/7 export | — | — | 실행 안 됨 | 앞 단계 실패로 시나리오 종료 |

### 샘플 표시 없음 확인 방법

1. 녹화 직전 `/health`: `pipeline.state=connected`, `mode=pipeline`(위). 파일 이름이 `_live`.
2. 분석 응답 `_status`: `source=pipeline`, `label` 빈 문자열, `response_sample=false` → 스크립트가 `_sample`로 바꾸지 않음. JSON `sample: false`, `sample_reason: []`.
3. 화면 배지: 단계마다 DOM에서 읽은 `observed.badge_by_step`이 input·paste·analyze·report·risk_card 모두 `""`, `badge_from: null`.
4. 앱 자체 표지: 리포트에 `#statusNotice`(샘플·비상 경로 안내) 없음(`status_notice: null`). 머리글은 "분석 파이프라인 연결 · v0.0.1"(프레임 연락표), 위험카드 생성 표기 "astra 합성".
5. 프레임 확인: mp4에서 뽑은 8프레임(`E6-L3c_frames.png`)에 SAMPLE 배지·"샘플 데이터" 문구가 없다.

## mp4 변환·편집본

```
$ python scripts/record_demo_edit.py C:/Users/User/Desktop/project_neumann/data/video/demo_20260930-193202_live.json --speed 4
[record_demo_edit] mp4: …\demo_20260930-193202_live.mp4 · 69.2s
[record_demo_edit] 편집본: …\demo_20260930-193202_live_edit.mp4 · 28.44s (예상 28.409s) · 끝 52.35s (evidence 단계 실패 → 그 자막 전에서 끝)
[record_demo_edit]      0.00s →    7.83s  ×1
[record_demo_edit]      7.83s →   39.75s  ×4
[record_demo_edit]     39.75s →   52.35s  ×1
[record_demo_edit] 가속 자막: 분석 중(가속 ×4 · 실제 대기 31.9초)
exit=0

$ ffmpeg -hide_banner -i demo_20260930-193202_live.mp4
  Duration: 00:01:09.20 … Video: h264 (High), yuv420p(progressive), 1440x900, 25 fps
$ ffmpeg -hide_banner -i demo_20260930-193202_live_edit.mp4
  Duration: 00:00:28.44 … Video: h264 (High), yuv420p(progressive), 1440x900, 25 fps
```

- 전체 mp4: `-an -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 25 -movflags +faststart`. 자르기·가속 없음.
- 편집본(3분 이내, 28.4초): 분석 대기(클릭 7.83s → 리포트 39.75s)만 ×4. 그 구간에만 붉은 자막 **"분석 중(가속 ×4 · 실제 대기 31.9초)"**(맑은 고딕 굵게, ffmpeg drawtext)를 앱의 "3/7 분석 실행 — 서버 응답 대기" 자막 위에 얹었다. 화면 속 경과 초 표시도 그대로 빨라진다.
- 끝: 원본 52.35s(근거 단계 자막 "6/7 근거 열람"이 뜨기 직전. 프레임 확인: 52.4s는 5/7, 52.6s는 6/7). 실패한 근거 단계를 성공처럼 보이지 않게 잘랐다. 편집본 마지막 화면은 "5/7 위험카드" 자막 + 근거 인용 #2~#5와 `원문 ↗` 링크.
- 편집본은 자르기와 대기 가속뿐이다. 순서 바꾸기·합성·다른 녹화 끼워 넣기 없음.

## 스크립트 보완 (소유: `scripts/record_demo*.py`)

1. `scripts/record_demo.py`
   - **예시 불러오기**: `GET /templates`의 예시 중 `filename`이 `--plan`과 같은 것(`find_example`)이 있고 화면에 그 버튼(`#exList [data-ex]`)이 있으면 붙여넣기 대신 버튼을 누른다. 입력칸 본문이 계획서 파일과 같은지(`plan_matches_file`, 줄바꿈·앞뒤 공백 정규화)와 글자 수를 JSON에 남긴다. `--example none|auto|<id>`.
   - 입력 화면: 템플릿·예시 목록이 그려질 때까지 기다리고(최대 5초), 범위 안내(`#scope`)로 커서를 옮기고 문구를 `observed.scope`에 남긴다.
   - `observed.analysis_t_click`·`analysis_t_report`(타임라인 초): 편집본이 대기 구간만 가속하는 기준.
   - **클릭이 고정 머리글에 떨어지던 문제 수정**(이번 실패 원인): `Director.move_to`가 `scroll_into_view_if_needed` 뒤 요소 가운데를 `elementFromPoint`로 확인(`HIT_JS`)하고, 가려 있으면 요소를 화면 가운데로 부드럽게 스크롤한 뒤 멈출 때까지 기다린다. 라이브에서는 위험카드 스크롤 뒤 `#1` 인용 번호가 y≈33px(머리글 밑)에 있어 Playwright는 "보인다"고 보고 스크롤하지 않았고, 가짜 커서 클릭이 머리글에 떨어졌다(프레임 54s·58s에서 커서가 머리글 위).
   - `--task`(JSON `task` 표기).
2. `scripts/record_demo_edit.py`(새로): JSON → 전체 mp4 + 편집본. 편집 계획은 순수 함수(`plan_edit`, `filter_graph`). 실패 단계가 있으면 그 자막 전에서 끝, 샘플 녹화는 편집본을 만들지 않음(`--allow-sample`로만).
3. 테스트
   - `tests/e6/test_record_demo.py` +4건(27건): 예시 버튼 흐름(가짜 앱에 범위 안내·예시 버튼 추가, `/templates/example-battery` 요청 확인, `plan_source=example:…`, 본문 일치) · `--example none`이면 조회 안 함 · `find_example`(파일 이름 일치·불일치·서버 없음) · **고정 머리글 밑 버튼 클릭**. 기존 흐름 테스트는 예시 없음(붙여넣기)으로 고정하고 `analysis_t_click ≤ analysis_t_report`가 analyze 단계 안에 있는지 추가 확인.
   - `tests/e6/test_record_demo_edit.py` 6건: 대기 구간만 가속·예상 길이·자막 문구 / 실패 단계 전에서 자름 / 잘못된 메타 거부 3가지 / drawtext가 가속 구간에만.
   - 변이 확인: `move_to`의 가림 검사를 끈 복사본(`if False:`)에서 새 테스트가 `assert ['HEADER'] == ['cite']`로 실패 — 라이브 실패와 같은 모양. 수정본은 통과.

```
$ python -m pytest tests/e6/test_record_demo.py tests/e6/test_record_demo_edit.py -q
27 passed … / 6 passed
```

## 완료 기준별

| 기준 | 결과 |
|---|---|
| webm·mp4 경로 | 위 표. `_live` 3종(webm·mp4·편집 mp4) + JSON + /health 기록 |
| 길이 | webm 69.2s · mp4 69.20s · 편집본 28.44s(3분 이내) |
| 단계 타임스탬프 | 위 표(JSON `steps`) |
| 샘플 표시 없음 | 위 "확인 방법" 1~5 |
| 1440×900 | webm 헤더·mp4 스트림 모두 1440×900 |
| 1회만 녹화·서버 건드리지 않음 | 녹화 1회(19:32:02). 서버 재시작·종료 없음. 녹화 전 점검은 GET만(`/health`, `/templates`, `/templates/example-battery` — 예시 본문이 plan.md와 같은지 비교) |

## verify

```
$ python scripts/verify.py        # 커밋 직전, 19:40
892 passed, 21 skipped in 76.11s (0:01:16)
보안: 파일 311개
계약: 2개
테스트: 통과
verify 통과
```

(skip 21건은 `NEUMANN_LIVE_TESTS`·원본 데이터가 필요한 기존 테스트. 이 과제 테스트는 skip 없음.)

## 못 한 것

- **근거 패널 열람 장면(6/7)과 내보내기(7/7)가 영상에 없다.** 녹화 스크립트 클릭 위치 문제(수정·테스트 완료). 1회 규칙과 대표의 API 비용 중지 지시로 재녹화하지 않았다. 인용 문장과 `원문 ↗` 링크는 5/7 위험카드 구간(46.5~52.4s)의 근거 목록에 보인다.
- 수정된 클릭이 라이브 화면에서 근거 패널을 여는지는 실서버로 확인하지 못했다(가짜 페이지 테스트로만). 최종 녹화 때 확인된다.

## 결정한 것

- 녹화가 근거 단계에서 실패했지만 **다시 녹화하지 않았다**(과제 규칙 "1회만"; 뒤이어 온 대표 지시 "추가 녹화·재시도 금지"와도 맞음). 실패까지의 영상으로 mp4·편집본을 만들었다.
- 편집본은 실패 단계 자막이 뜨기 전(52.35s)에서 끝낸다. 실패 구간(커서가 머리글에 멈춘 15초)을 넣으면 "근거 열람" 자막 아래 아무 일도 일어나지 않고, 빼고 뒤를 붙일 것도 없다.
- 가속 배율 ×4: 31.9초 대기가 8초가 되고, 분석 화면의 경과 초가 흐르는 것이 보인다. 가속 사실과 실제 대기 초를 자막에 적었다.
- mp4는 소리 없음(녹화에 소리 없음), CRF 20, 25fps 고정(PowerPoint 호환: H.264 High·yuv420p·faststart).
- 이번 분석은 31.9초였다(E5-L0e2e 라이브에서 plan.md는 68.9초). 측정값 그대로 적는다.

## 다음 (최종 녹화, 대표 지시 07:30)

```
python scripts/record_demo.py --base-url <서버> --plan tests/fixtures/plans/plan.md --out data/video/ --analysis-timeout 300 --stills --task <과제ID>
python scripts/record_demo_edit.py data/video/demo_<시각>_live.json --speed 4
```

- 녹화 전 `/health`가 `connected`인지 먼저 본다. 샘플이면 파일이 `_sample`이 되고 편집본은 만들지 않는다.
- 근거 패널·내보내기 장면이 들어가는지 JSON `steps`의 evidence·export 상태로 확인한다.
- `neumann.api.upload` 라우터가 `missing`(파일 업로드 경로). 시연은 예시 불러오기라 영향 없음.
