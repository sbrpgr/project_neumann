# E6-L3b 검증 보고서 (검증자: Claude Sonnet 5.5)

- 대상: 브랜치 `task/E6-L3b` (HEAD `3f4396f`, 기준 main `1bbe3e2` 위 커밋 2개), worktree `.claude/worktrees/agent-ad7d4d36e5dfefa49`, 빌더 claude-opus-5.5
- 방법: 빌더 보고서를 믿지 않고 완료 기준을 직접 실행했다. 녹화는 새로 돌리지 않았다(8010 서버는 `GET /health` 한 번만). 변이 시험은 스크립트·테스트를 스크래치 폴더로 복사해 그 복사본에 결함을 넣어 확인했고(끝난 뒤 삭제), 빌더 worktree의 코드·git은 건드리지 않았다. 남은 녹화 영상은 공유 폴더 `data/video/`의 기존 파일을 읽기만 했다.
- 환경: Windows Python `neumann` venv, `PYTHONPATH="src;."`, `_COMMON.md`의 환경변수.

## 결론

**PASS-조건부.** 기능·완료 기준·영상 미커밋은 모두 통과한다. 다만 이번 검증의 중점인 "샘플이면 화면 배지가 **반드시** 붙는가"에서 결함이 둘 있다. (1) 헬스는 `connected`인데 응답이 `source=sample`인 경로는 파일명만 `_sample`로 바뀌고 **영상 화면에는 SAMPLE 배지가 없다**. (2) 화면 배지를 검사하는 테스트가 없어서, 배지 코드를 지워도 16건이 전부 통과한다. 병합 전 고칠 것은 맨 아래에 있다(둘 다 작다).

## 항목별 결과

| # | 확인 항목 | 실행한 명령 / 방법 | 실제 결과 | 판정 |
|---|---|---|---|---|
| 1 | pytest | `python -m pytest tests/e6 -k record -q --durations=5` | **16 passed in 20.2s** (빌더 수치 16건과 같음). 가장 느린 건 시나리오 전체 3종 각 약 5.5s. 실행 뒤 `git status` 깨끗 | 통과 |
| 2 | verify | `python scripts/verify.py` (브랜치) | **144 passed**, 보안 85개 파일, 계약 2개, `verify 통과`. (빌더는 142 passed·2 skipped였고 이 환경은 `NEUMANN_RAW_DIR`가 잡혀 있어 skip 2건도 실행된 것. 합 144로 같음) | 통과 |
| 3a | 완료 기준: 1회 녹화 결과가 보고서에 있는가 | 보고서 표와 `data/video/demo_20260930-185420_sample.json`을 대조 | 보고서의 길이 36.8s, 1440×900, 단계 7개 타임스탬프가 JSON과 한 글자도 다르지 않다 | 통과 |
| 3b | 영상이 실제로 그렇게 생겼는가 | 기존 webm을 Chromium `<video>`로 열어 길이·크기·8개 시각의 프레임을 읽음(재녹화 아님) | `duration 36.8`, `1440×900`, 1·3·6·10·17·25·31·36초 8개 프레임 모두에서 왼쪽 아래 배지 영역(16,850)-(316,890)에 배지 색 `#b45309` 픽셀 약 3,000~3,700개 → **SAMPLE 배지가 전 구간 보임**. 프레임 연락표 PNG(1470×510)를 눈으로 봐도 단계 자막(1/7~7/7·끝)과 화면이 맞고, 화면 안에 `[FAKE]`·"샘플 데이터" 안내가 함께 보인다 | 통과 |
| 3c | 파일명·로그·JSON의 sample 표시 | 코드·JSON·보고서 로그 확인 + 변이 M1~M3 | 파일 `demo_…_sample.webm`, 로그 줄마다 `[sample]`, JSON `"sample": true`·`"mode": "sample"`. 판정은 보수적: `pipeline.state == "connected"`일 때만 live, 미연결·오류·필드 없음·응답 없음은 sample. 이 세 표시는 변이 시험이 잡는다(아래 6) | 통과 |
| 3d | 화면 배지 | 코드 검토 + 아래 6의 M4 + 배지 호출 탐침 | 배지(`d.badge`)는 `input` 단계에서 **녹화 시작 때의 mode가 sample일 때만** 한 번 켠다. 헬스가 connected여서 live로 시작했다가 응답 `_status.source=sample`로 사후에 sample로 바뀌면 파일명만 바뀌고 화면 배지는 켜지지 않는다(탐침 결과 아래 5). 배지 자체를 검사하는 테스트는 없다 | **결함(조건부)** |
| 4 | 영상·대용량이 커밋에 있는가 | `git ls-files \| grep -Ei '\.(webm\|mp4\|mkv\|mov\|avi\|gif)$'`, `git ls-tree -r -l HEAD`, `git ls-files \| grep ^data/` | 영상 파일 0개, `data/` 추적 파일 0개. 저장소 최대 파일은 `docs/reports/E6-L3b_frames.png` 352,428 B(344KB, 1470×510 PNG, 실제 PNG 헤더 확인)로 verify 5MB 상한의 약 7%. 영상·JSON은 저장소 밖 `project_neumann/data/video/`(gitignore)에만 있다 | 통과 |
| 5 | 소유 경로 밖 변경 | `git diff main...task/E6-L3b --stat / --name-status` | 4개 파일, 모두 추가(A): `scripts/record_demo.py`(소유 `scripts/record_demo*.py`), `tests/e6/test_record_demo.py`(소유 `tests/e6/test_record*.py`), `docs/reports/E6-L3b.md`와 `E6-L3b_frames.png`(허용된 예외). `contracts/`·`src/neumann/models.py`·`src/` 변경 0줄. `.env`·키·토큰 패턴 0건(스크립트의 `os.environ`은 `NEUMANN_DATA_DIR` 읽기뿐). 현재 main(`a6eab0c`)은 병합 기준보다 앞서 있지만 겹치는 파일이 없다 | 통과 |
| 6 | 테스트가 항상 통과하는가 | 스크래치 복사본에 결함 4종을 하나씩 넣고 `tests/e6` 실행(결함 없는 복사본은 16 passed) | M1 non-connected를 live로 판정 → **실패(잡힘)** `test_classify_health_only_connected_is_live`. M2 파일명에서 mode 제거 → **잡힘** `test_basename_carries_mode`. M3 응답이 sample이어도 이름을 안 바꿈 → **잡힘** `test_demo_flow_offline[connected-sample-False-sample]`. **M4 화면 배지 호출 삭제 → 16건 모두 통과(생존)** | 통과, M4는 결함(조건부) |
| 7 | 정직성 | 코드·자막·JSON 검토 | 자막에 "실제"라는 말을 쓰지 않는다. 샘플 안내문(`statusNotice`)은 화면 텍스트를 그대로 JSON에 옮기고 LLM 결과처럼 표시하지 않는다. 서버가 응답하지 않으면 녹화하지 않고 exit 2(테스트가 파일 0개 확인). 단계 실패 시 영상·JSON을 남기고 exit 1(테스트 있음). 규칙·샘플을 실제 결과라고 쓰는 곳 없음 | 통과 |

## 5. 배지 탐침 결과 (재현 절차 포함)

`run_demo`를 오프라인 가짜 앱(빌더의 `_fake_server`)으로 돌리면서 `Director.badge` 호출을 기록했다(스크래치 복사본, 코드 미수정).

| 헬스 state | 응답 `_status.source` | 최종 mode | 파일명 | 화면 배지 호출 |
|---|---|---|---|---|
| unavailable | sample | sample | `demo_…_sample.webm` | `['SAMPLE · 샘플 데이터 — 분석 결과 아님']` |
| **connected** | **sample** | sample | `demo_…_sample.webm` | **`[]` (없음)** |
| connected | pipeline | live | `demo_…_live.webm` | `[]` (정상) |

재현: `tests/e6/test_record_demo.py`의 `test_demo_flow_offline` 둘째 매개변수(`connected`, `sample`)와 같은 입력에서 `Director.badge`를 감싸 호출을 세면 된다. 지금 8010 서버의 `/health`는 `pipeline.state = "connected"`(단계 INPUT·EVIDENCE·REVIEW는 모듈 없음)라서, 녹화 시점(unavailable)과 달리 **지금 다시 녹화하면 이 둘째 경로로 갈 가능성이 있다.** 응답이 `sample`이면 영상 안에는 앱 자체 안내문(`statusNotice`)만 있고 스크립트의 배지는 없다. 영상만 따로 떼어 발표자료에 넣으면 파일명은 따라가지 않으므로 이 경로가 "샘플을 실제 시연처럼 못 쓰게"의 구멍이다.

## 병합 전 고칠 것 (PASS-조건부)

1. `scripts/record_demo.py`: 분석 응답에서 `response_source == "sample"`을 알게 되는 시점(analyze 단계 직후)에 `d.badge(...)`를 켜서, 헬스 판정과 무관하게 영상 나머지 구간에 SAMPLE 배지가 남게 한다. 앞부분(input·paste)은 배지가 없는 채로 찍혔으니 파일명을 `_sample`로 바꾸는 지금 동작은 유지하고, 가능하면 JSON에 `observed.badge`(마지막으로 화면에 있던 배지 문구)를 남긴다.
2. `tests/e6/test_record_demo.py`: 화면 배지를 검사하는 단정을 추가한다. 시나리오 끝에서 `#__demo_badge` 텍스트(또는 JSON `observed.badge`)를 읽어 (unavailable→sample)·(connected+응답 sample→sample) 둘 다 "SAMPLE"이 들어 있고 live에는 비어 있음을 확인한다. 이 테스트가 있으면 M4(배지 삭제)가 실패해야 한다.

비차단 참고: 시험 녹화 폴더 `data/video/_trial/`이 공유 폴더에 남아 있다(빌더 보고서에 명시, gitignore). 발표용 영상은 파이프라인 연결 뒤 재녹화하고 `_sample` 파일은 쓰지 않는다는 인계(보고서 "다음 과제에 넘길 것")에 동의한다.
