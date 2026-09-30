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

## 재작업 (검증 PASS-조건부 → 조건 해소)

검증 보고서 `docs/reports/E5-L0e2e.verify.md`의 "고칠 것" 1건과 PM 지시 2항(`integ/v0` 모양 기준 점검)을 반영했다. 먼저 `git merge main`(충돌 없음, `88b582a`).

1. **`check_negative`가 카드 0장 사유를 `_status.empty_reason`에서만 찾던 문제**(라이브 오탐). `integ/v0:src/neumann/pipeline.py` 346행은 사유를 `notices`에 `위험카드 0장: <사유>`로 담고, `api/view.py`는 이것을 `empty_reason`으로 올리지 않는다.
   - 새 함수 `zero_card_reasons(view)`는 `_status.empty_reason`과 `_status.notices`의 `위험카드 0장: …` 둘 다에서 사유를 모은다. 기본값(`사유 없음`, `위험카드 0장 — 결과에 사유가 없다`)과 파이프라인 자리표시 `카드 0장(사유 미상)`, 빈 본문은 사유로 치지 않는다.
   - 사유가 화면 `#noCards` 또는 `#statusNotice`에 보여야 통과한다. 응답에는 사유가 있는데 화면에 없으면 "사유 없음"과 구분해서 `카드 0장 사유가 응답에는 있으나 화면(#noCards·#statusNotice)에 없다`로 실패한다. 화면은 `_status.label`이 있을 때만 상단 안내를 그리기 때문에 생길 수 있는 경우다.
   - 범위 밖 입력에서 `result_status=error`가 나오면 `분석 오류(부적합 판정 아님)`로 실패한다.
   - 단위 검사 3건을 더했다(실제 `build_ui_view` 사용).
     - `test_negative_reason_from_pipeline_notices`: 검증자가 재현한 모양, 즉 notices에만 사유가 있고 empty_reason은 기본값인 경우. 화면에 보이면 통과하고, 안 보이면 실패한다.
     - `test_negative_reason_missing_everywhere_still_fails`: 조작 입력 4종(`카드 0장(사유 미상)`, notices 비움, `위험카드 0장:` 본문 없음, 무관한 notice)은 `사유가 없다`로 실패하고, status=error는 `분석 오류`로 실패한다.
     - `test_negative_reason_from_skipped_card_stage`: `integ/v0`의 실제 흐름. `synthesize_cards`가 사유와 함께 skipped되면 view가 그 사유를 `empty_reason`으로 올려 `#noCards`에 보이므로 통과한다.
2. **`integ/v0` 모양 점검에서 찾은 다른 불일치: `check_degradation`이 skipped 단계까지 상단 안내 표시를 요구하던 것.** `integ/v0`은 범위 밖 입력이나 카드 없음일 때 단계를 `skipped`로 남긴다. `stages_not_ok`에는 skipped가 들어가지만, 결과 status가 ok면 라벨이 없어서 화면에 상단 안내가 그려지지 않는다. 그래서 라이브에서 오탐이 났을 것이다.
   - 이제 상단 안내에 표시를 요구하는 단계는 `degraded`·`error`·`unavailable`뿐이다.
   - skipped·empty 단계는 추적(V) 섹션에 단계 이름이 보이는지로 잰다. 이 검사는 전과 같다.
   - 단위 검사 `test_error_stage_must_be_displayed`를 더했다(error 단계를 숨기면 실패). 위 skipped 검사도 포함.
   - 나머지 화면 연결점도 `integ/v0` 모양과 맞는지 확인했다.
     - DOM 고리(`#ta`·`#btnStart`·`.rc[data-card]`·`.gen`·`a.src`·`#hdrState`·`#jobErr`·`#s-trace`·`data-ready`)는 병합한 main과 `integ/v0`의 `index.html`에 똑같이 있다.
     - `GEN` 문구도 같다.
     - `StageStatus`의 JSON 키는 `name/status/reason`이고 view가 읽는 키와 같다.
     - `api/view.py`·`api/main.py`는 main과 `integ/v0`이 같다.
3. `test_live.py`는 범위 밖 요약 JSON에 `zero_card_reasons`를 기록한다. docstring도 새 판정 기준에 맞춰 고쳤다.

재실행(병합한 worktree 코드를 8123번에 샘플 모드로 띄움, 결과는 scratchpad에 저장, 끝난 뒤 서버 종료·8123 비어 있음 확인, 8010 미접근):

```
$ python -m pytest tests/e2e -q
...............sssss                                                     [100%]
15 passed, 5 skipped

$ NEUMANN_LIVE_TESTS=1 python tests/e2e/test_live.py --base-url http://127.0.0.1:8123 --timeout 120 --out <scratchpad>
대상 http://127.0.0.1:8123/ · 모드 sample · 상한 120.0s
- plan.md / plan_elife_neuro.md / plan_medimaging.md: FAIL · 카드 2 · 각 6건(맨 앞 4건 "파이프라인 미연결(샘플 모드)", 나머지 _status.pipeline=unavailable·근거 연결률 미측정)
- negative_recipe.md: FAIL · 샘플 3건 + "범위 밖 입력인데 위험카드 2장이 나왔다"
============================== 5 failed in 8.67s ==============================   (기대대로)

$ python scripts/verify.py      # main 병합 뒤
471 passed, 11 skipped in 19.85s
보안: 파일 202개
계약: 2개
테스트: 통과
verify 통과
```

남은 메모(검증 보고서의 비차단 메모 그대로 두는 것): 결과 재조회 API가 없어 파이프라인이 두 번 돈다(결정 1). `get_source_text`는 `review_id`만 원문으로 돌려준다(응답·결정문·사후 기록 인용은 연결 실패로 잡히며, 원인은 `linkage.reason_counts`의 `source_not_found`로 구분된다).
