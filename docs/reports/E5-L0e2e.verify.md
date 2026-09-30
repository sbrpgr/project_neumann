# E5-L0e2e 검증 보고서 (검증자: Claude Sonnet 5.5 · 빌더: Claude Opus 5.5)

대상: 브랜치 `task/E5-L0e2e` @ `372fd70` · worktree `.claude/worktrees/s2-E5-L0e2e` · 2026-09-30

## 최종 판정: **PASS-조건부** (병합 전 고칠 것 1건)

완료 기준 3개(테스트 코드 커밋 / 샘플 모드에서 기대대로 실패 보고 / verify 통과·e2e 기본 건너뜀)는 직접 재현했고 통과했다. 조작 입력 40여 건이 모두 실패로 잡혔다(항상 통과하는 검사 아님). 소유 밖 변경·계약 변경·비밀값 없음. 다만 **범위 밖 입력 판정(`check_negative`)이 실제 파이프라인의 결과 모양과 어긋난다**: 실제 파이프라인은 카드 0장 사유를 `notices`(`위험카드 0장: …`)에 담고, 화면 데이터 조립기(`api/view.py`)는 그것을 `_status.empty_reason`으로 올리지 않는다. 그래서 PM이 v0 통합 뒤 라이브로 돌리면 범위 밖 검사가 사유가 화면에 있어도 "사유가 없다"로 잘못 실패할 가능성이 높다(아래 "고칠 것").

## 고칠 것 (병합 전)

1. **`tests/e2e/e2e_checks.py::check_negative` — 카드 0장 사유를 `#noCards`의 `empty_reason`에서만 찾는다.** 재현(내 시뮬레이션, 실제 `build_ui_view` 사용): 결과 `risk_cards=[]`, `notices=["위험카드 0장: 입력이 연구계획서가 아니다(…)"]`, `risk_synthesis.no_card_reason` 설정 → `_status.empty_reason == "위험카드 0장 — 결과에 사유가 없다"`(기본값), `_status.notices`에는 사유가 있음 → `check_negative`가 `카드 0장이지만 사유가 없다`로 실패. 근거: `integ/v0:src/neumann/pipeline.py` 346행 `run.notices.append(f"위험카드 0장: {reason}")`, `view.py` 774행은 `empty_reason`/`no_cards_reason`만 읽는다. 조치: 사유를 `_status.notices`의 `위험카드 0장:` 항목(그리고 그 문구가 `#statusNotice`에 표시되는지)에서도 인정하도록 고치고 단위 검사 1건 추가. (다른 방법: E4가 `view.py`에서 `risk_synthesis.no_card_reason`을 `empty_reason`으로 올리도록 고치는 것 — PM이 어느 쪽으로 할지 정한다. 어느 쪽이든 라이브 실행 전에 정리해야 한다.)

## 완료 기준 · 확인 항목별 결과

| # | 항목 | 실행한 명령 | 실제 출력(핵심) | 판정 |
|---|---|---|---|---|
| 1a | 기본 pytest에서 라이브 e2e 건너뜀, 판정 함수 단위 검사는 돈다 | `python -m pytest tests/e2e -q -rs` (`_COMMON.md` 환경변수) | `11 passed, 5 skipped` (skip 사유: `NEUMANN_LIVE_TESTS=1일 때만 실행`, test_live.py 5건) | 통과 |
| 1b | verify | `python scripts/verify.py` | `169 passed, 5 skipped` · 보안: 파일 124개 · 계약: 2개 · `verify 통과` | 통과 |
| 2 | 샘플 모드 재현(8129, worktree 코드, mock provider, `OPENAI_API_KEY` 제거) | 서버: `PYTHONPATH="src;." NEUMANN_LLM_PROVIDER=mock python -m uvicorn neumann.api.main:app --port 8129` / 라이브: `NEUMANN_LIVE_TESTS=1 python tests/e2e/test_live.py --base-url http://127.0.0.1:8129 --timeout 120 --out <Temp>` | `/health` = `pipeline.state=unavailable · mode=sample`. **5 failed** (연결 1 + 데모 3 + 범위 밖 1). 모두 맨 앞 사유가 `파이프라인 미연결(샘플 모드)`. 데모 3건은 각 6건 실패(`/health`·`/premortem/view _status.source=sample`·헤더·`/premortem sample=True stages.impl=['fallback:sample']`·`_status.pipeline=unavailable`·`근거 연결률 미측정`), 범위 밖은 4건(샘플 3 + `범위 밖 입력인데 위험카드 2장이 나왔다`). 브라우저 콘솔 오류·외부 요청 0. 빌더 보고서의 출력과 일치. 서버 종료·8129 비어 있음 확인, 8010 미접근, OpenAI 미호출(키 제거 + mock) | 통과 |
| 3a | 카드 0장 | `check_cards(dom(cards=[]))` | `위험카드 0장` 실패 | 통과 |
| 3b | 카드에 인용 없음 / 인용문 빔 | `ev=[]`, `quote_len=0` | `인용 0개`, `인용문이 모두 비었다` 실패 | 통과 |
| 3c | 원문 링크 없음·잘못됨 | href `""`, `ftp://…`, `http://`(호스트 없음), 여러 근거 중 하나만 링크 없음 | 모두 `원문 링크 없음·잘못됨` 실패 | 통과 |
| 3d | 화면 카드 수 ≠ 응답 카드 수 | DOM 1장 vs 응답 2장 | 실패 | 통과 |
| 3e | 인용이 원문과 다름(근거 연결) | `eval.linkage.check_result`에 조작 evidence 8종 + 원문 조작 | 텍스트 교체 `text_hash_mismatch+text_mismatch`, 오프셋 +1 `text_mismatch`, `text_sha256` 틀림, `source_url` 빔/`javascript:`, 없는 `source_id`, 오프셋 범위 밖, 카드 근거 0개, evidence 비움(연결률 0.0), 원문 뒤집음(`source_hash_mismatch`) → 전부 실패. 기준선(무조작)은 `8/8 = 1.000 · pass` | 통과 |
| 3f | 근거 조회 실패·카드 0장 결과 | lookup이 예외 / `None` 반환 / `risk_cards=[]` | `source_lookup_error` 8건·`source_not_found` 8건, 카드 0장은 `linkage_rate=None, verdict=no_cards` → 실패(1.0으로 세지 않음) | 통과 |
| 3g | `eval.linkage.check_result`를 제대로 쓰는가 | 코드 확인(`check_linkage`) + 3e 동작 | 결과 dict와 `source_lookup`을 그대로 `check_result`에 넘기고 `linkage_rate != 1.0 or verdict != "pass"`를 실패로 본다. 라이브 테스트는 `neumann.index.store.get_source_text`를 넘기며 import 실패·색인 없음도 `근거 연결률 미측정`으로 실패(건너뛰지 않음). 결과가 계약 검증(`contract_valid`)을 못 넘어도 링크만 맞으면 통과하는 점은 아래 메모 | 통과(메모 1) |
| 3h | 강등 표시 누락 | `SEARCH·retrieve·degraded` 강등 결과 + 상단 안내 None / 라벨만 / 빈 문자열 | `강등 결과인데 상단 안내에 라벨…없다` · `강등 단계가 화면에 없다: SEARCH · retrieve · degraded` 실패. 표시 포맷은 실제 `index.html` 487행(`phase · name · status · reason`)과 같음. 통제(표시됨)는 통과 | 통과(메모 2) |
| 3i | 규칙 카드를 astra로 표시 | generator=rule인데 화면 `astra 합성` | `generator=rule인데 화면 표시…` 실패 | 통과 |
| 3j | 외부 요청·콘솔·페이지·실패 요청 | `is_external`·`check_browser` 조작 | `api.openai.com`, `fonts.googleapis.com`, `127.0.0.2`, `//cdn…` 모두 외부. `localhost`·`[::1]`·`data:`는 내부. 콘솔 오류·페이지 오류·외부·실패 요청 각각 1건이면 실패. 실제 샘플 실행에서 4개 모두 0 | 통과 |
| 3k | 샘플 상태 판정 | `check_health/view_status/result_json/header`에 샘플·오류 입력 | 전부 `파이프라인 미연결(샘플 모드)` 또는 상태 오류로 실패. HTTP 500·`status=error`·계약 위반도 실패 | 통과 |
| 3l | 범위 밖 입력 판정(단독) | `check_negative`: 카드 2장 / 0장+사유 없음 / 500 / 0장+사유 | 앞 3건 실패, 통제(0장+`empty_reason`+`#noCards` 표시) 통과 | 통과. **단 실제 파이프라인 결과 모양에서 오탐 가능 — "고칠 것" 1** |
| 4a | 소유 밖 변경 | `git diff main...task/E5-L0e2e --stat` | 10개 파일 전부 `tests/e2e/`(4) 또는 `docs/reports/E5-L0e2e*`(6: 보고서, 요약 JSON, PNG 4). 그 밖 없음 | 통과 |
| 4b | 계약·모델·데이터·비밀값 | 같은 diff + `git ls-files` | `contracts/`·`src/neumann/models.py`·`.env`·`data/`·parquet·모델 가중치 변경 없음 | 통과 |
| 4c | 커밋된 산출물의 비밀·로컬 정보 | 요약 JSON·보고서·테스트에서 키 패턴(`sk-`, `AIza`, `Bearer`, `token`, `secret`…)·로컬 경로(`C:\Users`, `AppData`)·`OPENAI` 문자열 검색, PNG 4장 중 3장 육안 확인 | 키·토큰·로컬 경로 없음. `OPENAI`는 보고서에서 "`OPENAI_API_KEY` 제거"로 이름만 언급. 요약 JSON은 base_url·시각·`/health` 상태·측정값뿐. 스크린샷은 샘플 화면(UI 헤더의 고정 사용자명 표시 외 개인 정보 없음) | 통과 |
| 4d | 커밋 형식 | 마지막 커밋 메시지 | 끝줄 `verify 통과(169 passed, 5 skipped)` · `builder: claude-opus-5.5` | 통과 |
| 5 | 알려진 한계의 정직한 기록 | 보고서 읽기 | (a) 파이프라인 두 번 실행: "결정" 1에 이유(ui_view에 `source_id`·`text_sha256` 없음, 결과 재조회 API 없음)와 astra 두 번 호출·카드 불일치 가능성까지 적음. (b) 결정문 인용 카드의 연결 실패 가능성: "못 한 것"에 적고 "다음 과제에 넘길 것"에서 E2 제안(get_source_text가 결정문 id도 반환) 남김. (c) 못 한 것: 실제 astra 라이브 실행, 카드·인용 "통과 쪽"은 fixture 단위 검사로만 확인했다고 명시. 샘플에서 카드·인용·링크 검사가 통과한다는 사실도 숨기지 않고 적음 | 통과(메모 3) |
| 6 | worktree 청결 | `git status --short --ignored` (verify·라이브 실행 뒤) | 추적·미추적 변경 없음. 내가 만든 `.pytest_cache`·임시 산출(Temp 아래)은 삭제 | 통과 |

## 메모 (비차단)

1. `check_result`가 `contract_valid=False`(PremortemResult 계약 위반)를 알려줘도 링크가 맞으면 `check_linkage`는 실패로 보지 않는다(엉뚱한 필드를 넣은 결과로 재현). 실제 서버는 계약 모델을 돌려주므로 위험은 낮다. `info["contract_valid"]`가 요약 JSON에 남으니 라이브 결과에서 눈으로 볼 수 있다.
2. `check_degradation`은 서버가 보고한 `_status.stages_not_ok`를 기준으로 화면 표시를 잰다. 서버가 강등을 `_status`에서 빼면(결과 JSON `stages`에는 degraded) 잡지 못한다. 결과 JSON의 단계 상태와 교차 확인하면 더 단단하지만, 화면 실행과 API 실행이 따로 돌기 때문에(결정 1) 지금은 비교가 어렵다. 결과 재조회 엔드포인트가 생기면 같이 개선할 것.
3. 빌더가 적은 "결정문 인용 카드" 한계는 실제로는 더 넓다: `integ/v0`의 `IndexStore.get_source_text`는 `review_id`만 원문으로 돌려주고(`response_id`·`decision_id`·`post_status_id`는 미지원), 파이프라인 `_verify`도 `source_kind == "review"`만 원문 대조한다. 라이브 실행에서 이런 근거가 인용되면 연결률이 1.0 미만으로 나오는데, 이는 검사기 결함이 아니라 원문 조회의 한계다(PM이 라이브 결과의 `linkage.reason_counts`로 구분).
4. 라이브 실행은 계획서마다 파이프라인을 두 번(화면 1 + API 1) 돈다. 상한은 계획서·요청당 300초이므로 4건 최악 시간이 길 수 있다(`--timeout`으로 조정).
5. 8010(대표 점검 서버)이 검증 중에도 떠 있었다(PID 13808). 손대지 않았다.

## 검증 환경

- Python: `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `_COMMON.md` 환경변수. worktree 코드로 서버 8129(샘플 모드), 검증 뒤 종료(`Get-NetTCPConnection`으로 리스너 없음 확인).
- 조작 검사 스크립트는 세션 scratchpad에만 두었고 worktree·main 저장소에는 넣지 않았다.
- 금지 사항 준수: 코드 수정·git 쓰기·`.env` 열기·키 값 출력·하위 에이전트·실제 OpenAI 호출 없음.

## 재검증 (2c5a791)

**PASS** (검증자: Claude Sonnet 5.5 · 빌더: Claude Opus 5.5 · 브랜치 `task/E5-L0e2e` @ `2c5a791` · 2026-09-30)

1차의 "고칠 것" 1건(`check_negative`가 notices의 카드 0장 사유를 인정하지 않음)은 해결됐다. 사유가 notices에만 있는 결과를 실제 `build_ui_view`에 넣어 직접 확인했고, 사유가 없거나 기본 문구뿐이면 실패한다. 강등 표시 규칙 변경(skipped는 추적 섹션, degraded·error·unavailable은 상단 안내)은 정직성을 약화하지 않았다(error 단계를 숨기는 조작 입력은 모두 실패). 병합을 막는 문제는 없다. 비차단 메모 2건은 아래에 적었다.

### 확인 결과

| # | 항목 | 실행한 것 | 실제 출력(핵심) | 판정 |
|---|---|---|---|---|
| 1a | 조건 1: notices에만 사유 | worktree의 실제 `neumann.api.view.build_ui_view`에 카드 0장 결과를 넣음(`notices=["위험카드 0장: 입력이 연구계획서가 아니다(요리 메모)"]`, `status=degraded`). 조작 스크립트는 scratchpad에만 있고 `index.html` 584~586·609행의 렌더 규칙을 흉내 낸 화면을 썼다 | `_status.empty_reason`은 기본값 `위험카드 0장 — 결과에 사유가 없다`, 사유는 `_status.notices`에만 있다(1차가 재현한 모양 그대로). 상단 안내에 사유가 보이면 `check_negative == []` 통과. `status=ok`라 라벨이 없어 상단 안내가 안 그려지는 화면(사유가 응답에만 있음)은 `카드 0장 사유가 응답에는 있으나 화면(#noCards·#statusNotice)에 없다`로 실패(사유 없음과 구분됨). 응답에는 있고 화면 안내를 지운 조작도 같은 사유로 실패 | 통과 |
| 1b | 사유가 어디에도 없으면 실패 | notices 비움(degraded·ok 각각) · 무관한 notice(`[search] degraded: 색인 느림`)만 있음 · `empty_reason`이 `카드 0장(사유 미상)`·`사유 없음` · 화면에만 사유를 주입하고 응답에는 없음 | 전부 `카드 0장이지만 사유가 없다`로 실패 | 통과 |
| 1c | 기본 문구·자리표시는 사유로 안 침 | notice 본문이 `카드 0장(사유 미상)` · `사유 없음` · `위험카드 0장 — 결과에 사유가 없다` · 빈 본문(`위험카드 0장:`) · 본문 없음(`위험카드 0장`) · `— 사유 없음` · `— 카드 0장(사유 미상)` | 전부 실패. 예외 1건은 메모 1 | 통과(메모 1) |
| 1d | 진짜 사유는 통과, 오분류는 실패 | 응답 최상위 `empty_reason`에 사유(→ `#noCards`) · 카드 단계 `skipped`+사유(view가 `empty_reason`으로 승격) · HTTP 422+notices 사유 / `status=error`(`분석 오류(부적합 판정 아님)`) · 카드가 나온 정상 결과(`위험카드 2장이 나왔다`) · HTTP 500 · 4xx인데 사유 없음 | 앞 3건 통과, 뒤 4건 실패 | 통과 |
| 2 | 조건 2: 강등 표시 규칙이 정직성을 약화하지 않는가 | `degraded`·`error`·`unavailable` 단계를 각각 넣고 (통제) 실제 화면 / 라벨만 / 안내 없음 / 빈 안내 / 단계 이름 바꿈 / 상태를 `ok`로 바꿔 표시 | 통제 3건 통과, 조작 15건 전부 `강등 단계가 화면에 없다: REVIEW · expected_review · <상태>` 또는 `강등 결과인데 상단 안내에 라벨…이 없다`로 실패. 결과 `status=error`+error 단계+안내 숨김도 실패. skipped와 error가 섞인 결과에서 skipped만 보이고 error를 숨기면 `RISK · synthesize_cards · error` 실패. error 단계인데 결과 `status=ok`라 상단 안내가 안 그려지는 화면도 실패(모델은 이런 결과를 막지만 view에 직접 넣어 확인). `StageState`에는 ok·degraded·skipped·error만 있고 view는 empty·unavailable도 다루는데, 상단 안내 요구 대상(degraded·error·unavailable)에서 빠지는 것은 건너뜀(skipped)·결과 없음(empty)뿐이다 | 통과 |
| 2b | skipped 규칙 | skipped 단계만 있는 범위 밖 결과(상단 안내 없음) · 같은 화면에서 추적 섹션의 단계를 지움 | 앞은 통과, 뒤는 `추적 섹션에 단계 EVIDENCE 표시 없음` 실패. skipped를 화면에서 완전히 숨길 수는 없다 | 통과 |
| 3 | 기본 pytest | `python -m pytest tests/e2e -q -rs` | `15 passed, 5 skipped`(skip 5건 모두 `NEUMANN_LIVE_TESTS=1일 때만 실행`, test_live.py) | 통과 |
| 3b | verify | `python scripts/verify.py` | `471 passed, 11 skipped in 20.18s` · 보안: 파일 202개 · 계약: 2개 · 테스트: 통과 · `verify 통과` | 통과 |
| 4 | 샘플 모드 서버 8129(worktree 코드, `NEUMANN_LLM_PROVIDER=mock`, `OPENAI_API_KEY` 제거) | 서버 기동 뒤 `NEUMANN_LIVE_TESTS=1 python tests/e2e/test_live.py --base-url http://127.0.0.1:8129 --timeout 120 --out <Temp>` | `/health` = `pipeline.state=unavailable · mode=sample`. **5 failed**. 파이프라인 연결 1건은 `파이프라인 미연결(샘플 모드): /health pipeline.state=unavailable · neumann.pipeline 모듈 없음`. 데모 3건은 각 6건 실패(맨 앞 4건 `파이프라인 미연결(샘플 모드)`, `_status.pipeline=unavailable`, `근거 연결률 미측정`). 범위 밖은 4건 실패(샘플 3건 + `범위 밖 입력인데 위험카드 2장이 나왔다`). 샘플 화면이 카드 0장 사유 검사를 우회해 통과하지 않는다. 서버를 종료하고 8129가 비었음을 `Get-NetTCPConnection`으로 확인. 8010은 손대지 않았다(리스너 PID 13808 그대로) | 통과(기대대로 실패) |
| 5 | 소유 밖 변경 | `git diff main...task/E5-L0e2e --stat` | 10개 파일 전부 `tests/e2e/`(4) 또는 `docs/reports/E5-L0e2e*`(6). `contracts/`·`src/neumann/models.py`·`.env`·`data/` 변경 없음. 재작업 커밋(2c5a791)은 `e2e_checks.py`·`test_e2e_checks.py`·`test_live.py`·보고서만 바꿈 | 통과 |
| 6 | worktree 청결 | `git status --short --ignored` | 추적·미추적 변경 없음. verify가 만든 `.pytest_cache`는 삭제 | 통과 |

### 메모 (비차단)

1. **notice 본문이 `결과에 사유가 없다`(뷰의 기본 문구 `위험카드 0장 — 결과에 사유가 없다`가 notice로 나온 경우)는 사유로 인정된다.** `zero_card_reasons`가 `위험카드 0장`을 떼고 구분자를 벗긴 본문 `결과에 사유가 없다`를 `DEFAULT_EMPTY_REASONS`(전체 문구만 들어 있음)와 대조해서 생긴 틈이다. 실제 파이프라인은 이 문구를 notices에 쓰지 않고 자리표시로 `카드 0장(사유 미상)`을 써서(제외됨) 실제 라이브에서 걸릴 가능성은 낮다. 고친다면 `DEFAULT_EMPTY_REASONS`에 `결과에 사유가 없다`를 더하면 된다.
2. **범위 밖 검사는 "범위 밖이라 카드가 없음"과 "파이프라인 오류로 카드가 없음"을 구분하지 않는다.** 재현(실제 `build_ui_view`): 카드 합성 단계 `error`(`TimeoutError`)와 notices `위험카드 0장: 카드 합성 단계 오류`, 결과 `status=degraded`이면 view가 단계 사유를 `empty_reason`으로 올려 `check_negative == []`(통과)이고 `check_degradation`도 통과한다(강등이 화면에 보이므로). `check_negative`가 `result_status == "error"`만 분석 오류로 보기 때문이다. 이 상태는 1차 판정 때도 같았고(재작업이 만든 것이 아니다) 정직성은 깨지지 않는다(강등이 화면에 그대로 보이고 요약 JSON에 `result_status`·`empty_reason`·`zero_card_reasons`가 남는다). 다만 astra가 실패하면 범위 밖 통과처럼 보일 수 있으니, PM은 라이브 결과의 `result_status`가 `ok`이고 카드 합성 단계가 `skipped`인지 요약 JSON에서 같이 본다. 개선 시 `error` 단계가 있으면 부적합 판정으로 치지 않도록 한다.
3. 화면 표시 검증은 `index.html` 소스를 읽어 렌더 규칙을 흉내 낸 조작 입력으로 했다. 실제 브라우저 실행은 샘플 모드(4번)에서만 했고, notices만 있는 결과를 실제 브라우저로 그린 것은 아니다(이 브랜치 서버로는 그런 결과를 만들 수 없다). 라이브 실행에서 확인된다.

### 검증 환경

- Python: `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `_COMMON.md` 환경변수. 서버는 8129 하나만 띄웠다가 종료. 임시 산출·서버 로그는 `C:/Users/User/AppData/Local/Temp/reverify_e5`(저장소 밖).
- 금지 사항 준수: 코드 수정·git 쓰기·`.env` 열기·키 값 출력·하위 에이전트·실제 OpenAI 호출·8010 접근 없음.
