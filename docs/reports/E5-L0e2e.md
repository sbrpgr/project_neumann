# E5-L0e2e 보고서 — 라이브 E2E 검사(실데이터·실제 astra, 로컬 서버)

- 빌더: Claude Opus 5.5 · 브랜치 `task/E5-L0e2e` · 2026-09-30
- 상태: 테스트 코드 완료. main에 분석 파이프라인(`neumann.pipeline`)이 아직 없어 **샘플 모드에서 "파이프라인 미연결"을 실패로 보고하는지까지만** 확인했다(스펙 2항). 실제 astra 라이브 실행은 v0 통합 뒤 PM이 한다.

## 무엇을 했나

| 파일 | 내용 |
|---|---|
| `tests/e2e/test_live.py` | 라이브 E2E 본체. `NEUMANN_LIVE_TESTS=1`일 때만 실행(아니면 5건 skip). Playwright(Chromium, 1440×900)로 화면 흐름을 끝까지 돈다. `python tests/e2e/test_live.py --base-url …`로 스크립트 실행도 된다 |
| `tests/e2e/conftest.py` | 옵션 `--e2e-base-url`(기본 `http://127.0.0.1:8010`)·`--e2e-timeout`(기본 300초)·`--e2e-out`(기본 `docs/reports`), 같은 이름의 환경변수 `NEUMANN_E2E_*`. 실행 요약 JSON(`E5-L0e2e_<mode>_summary.json`)과 터미널 요약 |
| `tests/e2e/e2e_checks.py` | 판정 함수(순수 함수). 실패 사유 목록을 돌려준다. 샘플 모드는 어느 재료에서 드러나든 `파이프라인 미연결(샘플 모드)`로 시작 |
| `tests/e2e/test_e2e_checks.py` | 판정 함수 단위 검사(기본 pytest, 11건). 이 브랜치의 실제 `/health`·`/premortem`·`/premortem/view`(TestClient, 샘플 모드)와 `build_ui_view`·공용 fixture로 판정기가 실제로 떨어지는지 잰다 |

### 라이브 테스트가 재는 것

`test_pipeline_connected` — `/health`의 `pipeline.state == "connected"`. 샘플이면 실패.

`test_demo_plan[plan.md | plan_elife_neuro.md | plan_medimaging.md]` — 계획서마다:
1. 입력 화면에서 `#ta`에 붙여넣기 → `#btnStart` → 브라우저가 보낸 `POST /premortem/view` 응답을 받고(상한 `--e2e-timeout`) 리포트 렌더(`body[data-view=report][data-ready=1]`) 또는 `#jobErr`를 기다린다
2. 파이프라인 연결: `/health`, 응답 `_status.source/pipeline/label`, 헤더 알약(`#hdrState`의 `st-ok` + "파이프라인 연결"). 샘플이면 `파이프라인 미연결(샘플 모드)`로 실패
3. 카드 1장 이상, 화면 카드 수 = 응답 카드 수, 카드마다 인용(비어 있지 않음)과 http(s) 원문 링크(`a.src`)
4. 생성 방식 표시: 카드의 `.gen` 문구가 응답 `generator`와 맞는다(규칙 카드를 "astra 합성"으로 보이면 실패)
5. 단계별 강등 표시: `_status.stages_not_ok`의 단계마다 상단 안내(`#statusNotice`)에 `phase · name · status`가 있다, 강등이면 라벨이 있다, 추적(V) 섹션에 응답 `pipeline`의 단계가 모두 있다
6. 같은 계획서로 `POST /premortem`(PremortemResult) → `eval.linkage.check_result(result, neumann.index.store.get_source_text)` → 근거 연결률 1.0·verdict pass. 결과가 샘플이면 "근거 연결률 미측정: 파이프라인 미연결(샘플 모드)"로 실패
7. 브라우저: 콘솔 오류 0, 페이지 오류 0, 외부 요청 0(서버 호스트·localhost·data: 밖이면 외부), 실패한 요청 0
8. 시간: 클릭→응답(`ui_response_s`), 클릭→리포트(`ui_total_s`), 서버 처리(`_status.server_elapsed_s`), 단계(phase)별 초(`view.pipeline[].ms`), 결과 JSON의 단계별 `elapsed_s`, `/premortem` 왕복(`api_premortem_s`)
9. 스크린샷 `docs/reports/E5-L0e2e_<mode>_<계획서>_{input,report,cards}.png`(리포트는 전체 페이지)

`test_negative_recipe` — `negative_recipe.md`: (a) 리포트에 카드 0장 + 기본값이 아닌 `empty_reason`이 `#noCards`에 표시, 또는 (b) 4xx 부적합 판정 + 사유. 500(실행 실패)은 부적합 판정으로 치지 않는다. 샘플이면 실패.

실패는 계획서마다 모아서 한 번에 보고한다(샘플 모드 사유가 맨 앞). 한 검사가 실패해도 나머지 검사는 계속 잰다.

## 완료 기준

### 1. 테스트 코드 커밋 — 통과

```
77ea45d [E5-L0e2e] 라이브 E2E 테스트 골격: Playwright 화면 흐름·판정 함수·실행 기록
1826e26 [E5-L0e2e] 판정 함수 단위 검사(기본 pytest): 샘플 모드 실패·카드·링크·강등·범위 밖·외부 요청·근거 연결
d02c034 [E5-L0e2e] 샘플 모드 실행 결과: 스크린샷 4장·요약 JSON, 카드 스크린샷을 페이지 좌표로 잘라 고정 헤더 겹침 제거
(+ 이 보고서 커밋)
```

### 2. 샘플 모드 실행 결과(기대대로 실패 보고) — 통과

대상: main 코드(`ed1d1a0`, `neumann.pipeline` 없음)를 main 체크아웃에서 8123번으로 띄운 서버(샘플 모드, `NEUMANN_LLM_PROVIDER=mock`, `OPENAI_API_KEY` 제거, 바이트코드 쓰기 끔). 8010(대표 점검 서버)에는 요청하지 않았다. 실행 뒤 서버를 종료하고 8123이 비었음을 확인했다.

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="<main>/src;<main>" NEUMANN_LLM_PROVIDER=mock env -u OPENAI_API_KEY \
    python -m uvicorn neumann.api.main:app --host 127.0.0.1 --port 8123     # cwd = main 체크아웃
$ NEUMANN_LIVE_TESTS=1 python tests/e2e/test_live.py --base-url http://127.0.0.1:8123 --timeout 120
tests/e2e/test_live.py::test_pipeline_connected FAILED                   [ 20%]
tests/e2e/test_live.py::test_demo_plan[plan.md] FAILED                   [ 40%]
tests/e2e/test_live.py::test_demo_plan[plan_elife_neuro.md] FAILED       [ 60%]
tests/e2e/test_live.py::test_demo_plan[plan_medimaging.md] FAILED        [ 80%]
tests/e2e/test_live.py::test_negative_recipe FAILED                      [100%]
...
E       AssertionError: 파이프라인 미연결(샘플 모드): /health pipeline.state=unavailable · neumann.pipeline 모듈 없음 · 화면 표시 '분석 파이프라인 미연결(샘플 데이터)'
...
============================= E5-L0e2e 라이브 E2E 요약 =============================
대상 http://127.0.0.1:8123/ · 모드 sample · 상한 120.0s
- plan.md: FAIL · 카드 2 · 화면 전체 0.833s(응답 0.056s) · 서버 0.007s · 단계 {'PIPELINE': 0.0} · /premortem 0.005s · 연결 검사 안 함: 샘플 결과(공용 fixture)는 근거 연결 검사 대상이 아니다
    ✗ 파이프라인 미연결(샘플 모드): /health pipeline.state=unavailable · neumann.pipeline 모듈 없음 · 화면 표시 '분석 파이프라인 미연결(샘플 데이터)'
    ✗ 파이프라인 미연결(샘플 모드): /premortem/view _status.source=sample · label='분석 파이프라인 미연결(샘플 데이터)' — 입력한 계획서는 분석되지 않았고 화면 값은 공용 fixture다
    ✗ 파이프라인 미연결(샘플 모드): 헤더 표시 '분석 파이프라인 미연결(샘플 데이터)'
    ✗ 파이프라인 미연결(샘플 모드): /premortem 결과 sample=True · stages.impl=['fallback:sample']
    ✗ /premortem/view _status.pipeline=unavailable
    ✗ 근거 연결률 미측정: 파이프라인 미연결(샘플 모드)
- plan_elife_neuro.md: FAIL · 카드 2 · 화면 전체 0.848s(응답 0.07s) · 서버 0.007s · … (plan.md와 같은 6건)
- plan_medimaging.md: FAIL · 카드 2 · 화면 전체 0.803s(응답 0.061s) · 서버 0.007s · … (plan.md와 같은 6건)
- negative_recipe.md: FAIL · 카드 2 · 화면 전체 0.831s(응답 0.066s) · 서버 0.006s · 단계 {'PIPELINE': 0.0}
    ✗ 파이프라인 미연결(샘플 모드): /health pipeline.state=unavailable · neumann.pipeline 모듈 없음 · 화면 표시 '분석 파이프라인 미연결(샘플 데이터)'
    ✗ 파이프라인 미연결(샘플 모드): /premortem/view _status.source=sample — 범위 밖 판정을 잴 수 없다
    ✗ 파이프라인 미연결(샘플 모드): 헤더 표시 '분석 파이프라인 미연결(샘플 데이터)'
    ✗ 범위 밖 입력인데 위험카드 2장이 나왔다
요약 JSON: …\docs\reports\E5-L0e2e_sample_summary.json
============================== 5 failed in 10.84s ==============================
```

읽는 법
- 5건 모두 실패했고, 실패 사유의 맨 앞은 전부 `파이프라인 미연결(샘플 모드)`다. `/health`·화면 응답·헤더·결과 JSON 네 곳에서 따로 잡혔다.
- 샘플 모드인데도 **카드·인용·원문 링크·생성 방식·강등 표시·브라우저 검사는 통과**했다(실패 목록에 없다). 샘플 fixture 카드 2장에 인용 8개·링크가 있어 DOM 탐침이 실제로 카드를 읽었다는 뜻이다. 그래서 "카드가 나왔다"만으로는 샘플을 못 거르고, 상태 검사가 따로 필요하다(단위 검사 `test_sample_view_and_result_are_reported_as_sample`가 이것을 고정).
- 브라우저: 4건 모두 콘솔 오류 0 · 페이지 오류 0 · 외부 요청 0 · 실패한 요청 0(요약 JSON `browser`).
- 범위 밖 입력(요리 메모)에도 샘플 카드 2장이 나와 "범위 밖 입력인데 위험카드 2장"으로 실패 — 기대대로.

스크린샷(커밋한 것 4장, 나머지 8장은 같은 샘플 화면이라 저장소 크기 때문에 뺐다)
- `docs/reports/E5-L0e2e_sample_plan_input.png` — 입력 화면(붙여넣기 뒤)
- `docs/reports/E5-L0e2e_sample_plan_report.png` — 리포트 전체(상단 "분석 파이프라인 미연결(샘플 데이터)" 안내)
- `docs/reports/E5-L0e2e_sample_plan_cards.png` — 위험카드 섹션(인용·원문 링크·`mock provider` 표시)
- `docs/reports/E5-L0e2e_sample_negative_recipe_report.png` — 요리 메모 입력에도 샘플 카드가 나온 화면

### 3. 기본 pytest에서 e2e 건너뜀 + `python scripts/verify.py` 통과 — 통과

```
$ python -m pytest tests/e2e -q -rs
...........sssss                                                         [100%]
SKIPPED [1] tests\e2e\test_live.py:…: 라이브 E2E: NEUMANN_LIVE_TESTS=1일 때만 실행(실서버·실제 astra)
SKIPPED [3] …  SKIPPED [1] …
11 passed, 5 skipped

$ python scripts/verify.py        # _COMMON.md의 환경변수
169 passed, 5 skipped in 3.05s
보안: 파일 123개
계약: 2개
테스트: 통과
verify 통과
```

(보고서 커밋 직전에 verify를 다시 돌렸다 — 아래 "마지막 verify".)

## PM이 v0 통합 뒤 돌릴 명령

```bash
# 통합 서버가 8010에 떠 있고, 환경변수는 _COMMON.md대로(NEUMANN_DATA_DIR 필수: get_source_text가 공유 색인을 읽는다)
NEUMANN_LIVE_TESTS=1 python tests/e2e/test_live.py --base-url http://127.0.0.1:8010 --timeout 300
```

결과는 터미널 요약과 `docs/reports/E5-L0e2e_live_summary.json`, 스크린샷 `docs/reports/E5-L0e2e_live_*.png`에 남는다.

## 결정(스펙이 모호해서 고른 것)

1. **근거 연결 검사용 결과 JSON은 `POST /premortem`을 한 번 더 불러 받는다.** 화면은 `/premortem/view`(ui_view)만 받고, ui_view에는 `source_id`·`text_sha256`가 없어 `check_result`에 넣을 수 없다. 세션 id로 결과를 다시 받는 API도 없다. 그래서 계획서마다 파이프라인이 두 번 돈다(화면 1 + API 1, astra 호출도 두 번). 두 실행은 LLM 비결정성 때문에 카드가 다를 수 있으나, 연결률 검사는 API 결과 자체에 대해 정확하다. 결과를 세션 id로 다시 받는 엔드포인트가 생기면 한 번으로 줄일 수 있다(다음 항목).
2. **샘플 모드에서는 근거 연결 검사를 하지 않고 실패로 적는다.** 샘플 결과는 공용 fixture(가짜)라 색인 원문과 대조할 대상이 아니다. "근거 연결률 미측정: 파이프라인 미연결(샘플 모드)".
3. **범위 밖 입력의 합격 조건**: 카드 0장 + 기본값이 아닌 사유가 화면에 표시, 또는 4xx 부적합 판정 + 사유. 500은 실패. 사유의 문구 자체는 검사하지 않는다(파이프라인이 정할 몫).
4. **외부 요청 판정**: 요청 호스트가 대상 서버 호스트 또는 127.0.0.1·localhost·::1이 아니면 외부. data:/blob:/about:은 내부.
5. **시간 상한 기본 300초**(계획서 1건, 화면 응답 대기와 `/premortem` 요청 각각). `--e2e-timeout`으로 바꾼다.
6. **스크린샷 이름에 모드(sample/live)를 넣었다.** PM의 라이브 실행이 이 샘플 스크린샷을 덮어쓰지 않는다.
7. **실행한 서버는 main 체크아웃 코드**(worktree 브랜치 기점 `e0008d0`보다 main이 앞서 있어서). main 체크아웃 파일은 고치지 않았고, `PYTHONDONTWRITEBYTECODE=1`로 `__pycache__`도 만들지 않았다.
8. 판정 로직을 `e2e_checks.py`(순수 함수)로 떼어 기본 pytest에서 검사한다. 라이브 테스트는 서버 없이는 못 돌기 때문에, 판정기가 "항상 통과"가 아님을 기본 테스트로 보장하려는 것.

## 못 한 것

- 실제 astra·실데이터 라이브 실행(파이프라인이 main에 없음). 그래서 카드·인용·링크·강등 표시·연결률 1.0의 "통과" 쪽은 단위 검사(fixture·`build_ui_view`)로만 확인했고, 실제 파이프라인 결과로는 아직 재지 않았다.
- 분석 중(job) 화면 스크린샷: 완료 뒤 0.7초 만에 리포트로 넘어가서 찍지 않았다(단계 기록은 추적 섹션과 응답 `pipeline`으로 검사).
- `get_source_text`는 E2-L0 브랜치 인터페이스(`review_id → 원문`)에 맞췄다. 카드가 결정문(decision) excerpt를 인용하면 이 조회로는 원문을 못 찾아 연결 실패로 잡힌다 — 통합 뒤 실제로 그런지 PM 라이브 실행에서 확인이 필요하다.

## 다음 과제에 넘길 것

- (E4 제안) `GET /premortem/{session_id}` 같은 결과 재조회가 있으면 E2E가 화면과 **같은 실행**의 결과로 근거 연결을 잴 수 있고 astra 호출이 절반으로 준다.
- (E2 제안) `get_source_text`가 결정문 id도 돌려주면 결정문 인용 카드도 연결 검사가 된다.
- 라이브 실행 뒤 `E5-L0e2e_live_summary.json`의 단계별 시간을 v0 성능 기준(계획서 1건 소요)과 비교.

## 바꾼 파일

- `tests/e2e/test_live.py`, `tests/e2e/conftest.py`, `tests/e2e/e2e_checks.py`, `tests/e2e/test_e2e_checks.py`(새 폴더)
- `docs/reports/E5-L0e2e.md`, `docs/reports/E5-L0e2e_sample_summary.json`, `docs/reports/E5-L0e2e_sample_{plan_input,plan_report,plan_cards,negative_recipe_report}.png`
- 새 패키지 없음(playwright·httpx는 이미 설치됨).

## 마지막 verify

```
$ python scripts/verify.py      # 보고서 커밋 직전, conftest.py 줄바꿈·요약 문구 수정 뒤
169 passed, 5 skipped in 3.12s
보안: 파일 124개
계약: 2개
테스트: 통과
verify 통과
```
