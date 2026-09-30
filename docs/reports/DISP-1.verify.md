# DISP-1 검증 보고서

- 검증자: Claude Sonnet 5.5 · 대상: `task/DISP-1` (worktree `.claude/worktrees/s2-DISP-1`, HEAD `20211eb`) · 2026-09-30
- 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK`·`NEUMANN_LIVE_TESTS` 없음(OpenAI 호출 0). `.env` 열지 않음. 서버는 8151·8152·8153만 썼고 모두 종료. 빌더 worktree는 `git status` 깨끗(파일 안 남김). 병합 시험은 scratchpad 복제본(`merge_disp1`)에서만 했다.

## 최종 판정: PASS-조건부

DISP-1 브랜치 자체는 완료 기준 3개와 요청한 확인 7개를 모두 통과했다. 병합 때 고칠 것이 2개 있다(E5-L3b 테스트 2줄, 리포트 카드 재생성). 브랜치 안의 결함은 아니다.

## 완료 기준

| # | 명령 | 실제 출력 | 판정 |
|---|---|---|---|
| 1 | `pytest tests/e4 tests/e5 -q` | `418 passed, 9 skipped in 51s` | 통과 |
| 2 | 화면 배지·astra 없음 (빌더 스크린샷 2장 확인 + 내가 따로 짠 Playwright 프로브 12 시나리오) | 카드 배지 `LLM (gpt-6.1-sol)`, 추적 `LLM (gpt-6.1-sol) 2장`, DOM 글자(innerText·텍스트 노드·속성) astra 0. 빌더의 `NEUMANN_UI_SHOTS=1` 테스트도 내가 다시 돌려 통과(8153) | 통과 |
| 3 | `python scripts/verify.py` (task/DISP-1) | `1226 passed, 28 skipped in 145s` · 보안 412 · 계약 2 · `verify 통과` | 통과 |

계약 위반 확인: `git diff main...task/DISP-1 --stat` = 13파일(소유 경로·관련 테스트·보고서·스크린샷). `contracts/`·`models.py` 변경 없음, 비밀·데이터 파일 없음.

## 요청 확인 1~7

| # | 확인 | 방법·결과 |
|---|---|---|
| 1 | 사람이 보는 출력 astra 전수 | (a) 화면 뷰 JSON: sol 결과(generator astra + 모델 gpt-6.1-sol)에서 astra는 `gen` 값과 `_status.generators`·`generator_labels`의 dict 키뿐(계약 값). 표시 문자열 0건. (b) 렌더 후 DOM: innerText·텍스트 노드·근거 패널·속성 모두 0건(CSS 클래스 `gen astra`만 있고 안 보임). (c) ZIP 사람용 5문서: README·ai_context는 "계약 이름" 설명 한 줄뿐, plan_annotated·similar_works 0건. (d) 성적표 재생성: `Neumann (LLM)`. 남은 astra는 아래 발견 2·3. (e) 실제 과거 결과 26건(`data/eval/neumann_runs`)에 뷰·ZIP을 돌려 gpt-6-astra 모델명을 뺀 astra 0건 |
| 2 | 실제 모델 gpt-6-astra 정직성 | 합성 시나리오와 실제 과거 결과 11건 모두 `LLM (gpt-6-astra)`. sol로 바뀌지 않음(카드·심사평·체크리스트·추적·ZIP 전부). 실제 sol 결과 2건은 `LLM (gpt-6.1-sol)` |
| 3 | model 없음·빈 문자열·공백 | 카드·심사평·체크리스트·`_status.generator_labels` 모두 `LLM`만(지어내지 않음). 추적은 `모델 —`. 카드 model이 없고 manifest에 모델이 있으면 manifest 모델로 채움(결과 자체 값, 설정 기본값 아님) |
| 4 | mock·rule·XSS | mock 카드·심사평·체크리스트 `모의(mock)`, rule `비상 규칙`(모델이 적혀 있어도 LLM으로 안 씀). 실제 mock 서버 응답 `/premortem/view`도 `모의(mock)`, 알림 `mock provider(테스트용) 결과 — 실제 LLM 분석이 아니다`. 모델명에 `<script>alert(1)</script>`·`"><img src=x onerror=…>`·`<b>`를 넣어 렌더: 글자로만 나옴, script 개수 1(페이지 자체), 주입된 img 0, 대화상자 0, 페이지 오류 0 |
| 5 | 저장 JSON generator 그대로 | ZIP `risk_cards.json`·`evidence_pack.json`·`manifest.json cards_by_generator`의 generator가 입력 그대로(astra/rule/mock), 실제 과거 결과 26건도 동일. `build_ui_view`는 입력을 바꾸지 않음. `verify.py` 계약 2개 통과 |
| 6 | 병합 호환 | 아래 별도 표 |
| 7 | 전체 pytest·verify | task/DISP-1: 1226 passed·28 skipped, verify 통과. 병합본(수정 2줄 적용): 1324 passed·29 skipped, verify 통과 |

## 병합 시험 (scratchpad 복제본)

main `a9f28e1` → `task/E4-L2f`(552e9de) → `task/E5-L3b`(b462c21, 최신) → `task/DISP-1`(20211eb) 순서.

| 단계 | 결과 |
|---|---|
| 세 병합 | 텍스트 충돌 0(view.py·index.html·report_card.py 자동 병합) |
| e4·e5·e2e 테스트 | 469 passed·16 skipped·**1건 실패**: `tests/e5/test_metrics_from_e2e.py::test_output_feeds_report_card` — 188·194행이 `Neumann (astra)`를 기대. 빌더 보고와 같은 재현 |
| 수정 범위 | **그 2줄만** `Neumann (astra)` → `Neumann (LLM)`. 고친 뒤 e5 리포트 카드 관련 64개 통과, 병합본 전체 `verify.py` 통과(1324 passed) |
| 리포트 카드 산출물 | 커밋된 `docs/reports/report_card.md`에 `Neumann (astra)`가 12줄 남음. E5-L3b 입력으로 재생성하면 전부 `Neumann (LLM)`, 평가 모델 `gpt-6-astra`는 그대로 표시(정직) |
| 참고: E4-L3m | DISP-1과는 충돌 없음(`merge-tree` 깨끗). 다만 E4-L3m은 E4-L2f와 index.html CSS 꼬리에서 충돌한다(DISP-1이 없어도 발생, 이 과제와 무관) |

## 변조 시험(테스트가 항상 통과하는지)

병합 복제본에서 코드를 일부러 망가뜨려 새 테스트가 실패하는지 봤다.

| 변조 | 결과 |
|---|---|
| 모델명을 라벨에서 뺌 / rule을 LLM으로 / mock을 LLM으로 | 실패(잡음) |
| `display_text` 무동작 / export 카드 라벨을 원 값으로 / README 요약을 원 값으로 | 실패(잡음) |
| 리포트 카드 시스템 이름을 `Neumann (astra)`로 | 실패(잡음) |
| 카드 `genl`을 원 값으로 / manifest 모델 대체 제거 | 실패(잡음) |
| `GENERATOR_DISPLAY["astra"]`를 `"astra"`로 | 통과 — 그 항목은 `display_generator`가 astra를 먼저 가로채서 쓰이지 않는 죽은 값(동등 변조, 결함 아님) |
| index.html `genName`을 `astra 합성`으로 되돌림 | **기본 pytest 전체 통과** — 화면 DOM 검사는 `NEUMANN_UI_SHOTS=1` 선택 실행이라 기본 게이트가 못 잡는다(프로젝트 공통 규약, 아래 발견 5) |

## 발견 (병합 막지 않음, 심각도 낮음 → 중간 순)

1. **`neumann_report.md`에도 계약 이름 설명 줄이 들어감.** 예상 심사평 JSON 블록 앞에 `JSON_GENERATOR_NOTE`가 붙어 astra 글자가 3번째 문서에 나온다(허용 목록은 README·ai_context 두 곳). 블록 안의 `"generator": "astra"`는 JSON 원본이라 허용이고 설명 줄은 그 블록을 풀이하는 것이라 이해되지만, 엄격히 읽으면 목록 밖이다. 대표 지시를 엄격히 볼 거면 그 줄을 뺀다(블록 위 `생성: LLM (…)` 줄은 남김).
2. **성적표의 파일 이름.** 재생성한 성적표에도 `score_astra.json`(P1 행 마지막 칸, 입력 파일 표)과 `pred_astra_gold.jsonl`(명령 블록)이 보인다. 모델명 `gpt-6-astra`는 실제 평가 모델이라 허용. 파일 이름은 디스크 이름 그대로라 빌더가 두었다. 표지에 오를 문서면 파일 이름을 바꿔 다시 뽑거나 그대로 두기로 정한다.
3. **E5-L3b 산문 문서.** `docs/reports/metrics_summary.md` 35·43행에 "generator astra 13/13"·"astra 하한" 같은 산문이 있다(E5-L3b 소유, report_card가 만든 게 아님). DISP-1 범위 밖.
4. **0장인 LLM 줄에 모델명이 붙음.** 결과에 LLM 카드가 없어도 README·리포트 생성 방식 요약에 `**LLM (모델명)** 0장`이 나온다. mock 실행에서는 manifest 모델이 `mock-deterministic-v1`이라 `LLM (mock-deterministic-v1) 0장`이 나온다. 같은 줄 아래 `모의(mock) 6장`이 있어 정직성은 지켜지지만 어색하다. 카드가 0장이면 모델을 붙이지 않는 편이 낫다(`export._gen_name`).
5. **화면 배지는 기본 게이트에서 안 지켜진다.** 브라우저 테스트가 전부 선택 실행이라(프로젝트 공통) index.html 표시 회귀는 verify가 못 잡는다. 이번엔 내 DOM 프로브(12 시나리오)와 빌더 스크린샷 테스트로 확인했다.
6. 작은 것들: `_status_block`이 `error` 인자를 `display_text`에 안 거친다(서버의 실패 사유는 예외 종류·파일 줄뿐이라 실제로는 astra가 안 들어감). 적합성 판정 훅 `FITGEN.mock`은 `mock provider`로 남아 `모의(mock)`와 표기가 다르다(훅이 서버에 아직 안 연결됨). 조사 "LLM가"(빌더가 보고). `scripts/build_static_site.py` `_model_of`의 "미기록(생성 방식 astra)"(E6 소유, 이 기기의 사전 계산본은 해당 없음).

## 병합 전 필수 조치

1. `task/E5-L3b` 뒤에 DISP-1을 병합한 커밋에서 `tests/e5/test_metrics_from_e2e.py` 188행·194행의 `Neumann (astra)`를 `Neumann (LLM)`으로 바꾼다(다른 줄은 그대로: `gpt-6-astra` 모델명 인자·`{"astra": n}` 입력 값은 계약 값·모델명이라 두어야 한다). 이 2줄이 없으면 병합본 pytest 1건 실패.
2. 병합 뒤 `docs/reports/report_card.md`를 재생성해 커밋한다. 명령은 파일 머리의 생성 명령 그대로(`python -m eval.report_card --inputs …score_baseline_freq.json …score_astra.json …score_rule.json docs/reports/E5-L3b_metrics_e2e.json --out docs/reports/report_card.md --eval-model gpt-6-astra`). 안 하면 커밋된 성적표에 `Neumann (astra)`가 12줄 남는다.
3. 병합 순서 참고: E4-L3m은 DISP-1과 충돌하지 않지만 E4-L2f와 CSS 꼬리에서 충돌한다. 어느 쪽이 먼저든 그 충돌은 PM이 손으로 푼다(DISP-1 무관).

선택(발견 1·4): 필요하면 작은 후속으로 처리해도 된다.
