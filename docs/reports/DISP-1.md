# DISP-1 — 생성 방식 표시 이름: "astra" → "LLM (실제 모델명)"

- 빌더: Claude Opus 5.5 · 브랜치 `task/DISP-1` (worktree `.claude/worktrees/s2-DISP-1`, main 6dea51e에서 시작)
- 실제 OpenAI 호출 0회. 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK` 없음.

## 무엇을 했나

계약 값 `generator="astra"`(제품 LLM이라는 이름)는 저장 JSON에 그대로 두고, 사람이 보는 화면·ZIP 문서·리포트 카드에서만
표시 이름으로 바꿨다. 표시 변환은 한 곳에 있다.

- `src/neumann/api/view.py`
  - `display_generator(generator, model)`: `astra` → `"LLM (모델명)"`(모델명이 없으면 `"LLM"`), `rule` → `"비상 규칙"`,
    `mock` → `"모의(mock)"`, `sample` → `"샘플 · 분석 결과 아님"`, 없음·unknown → `"생성 방식 미표기"`, 모르는 값은 그대로.
    규칙·mock에는 모델명을 붙이지 않는다(LLM 결과로 보이지 않게).
  - `display_text(text)`: 자유 문구(알림·단계 사유·카드 0장 사유·표 칸)에서 **계약 이름으로 쓴 astra만** `LLM`으로 바꾼다.
    앞뒤가 영숫자·`_`·`-`·`.`이면 건드리지 않아서 모델명(`gpt-6-astra`)과 파일 이름(`score_astra.json`)은 그대로다.
    인용·계획서 줄·카드 제목에는 쓰지 않는다.
  - 화면 뷰: 카드·예상 심사평·체크리스트에 `genl`(표시 이름) 추가, `_status.generator_labels`(생성 방식별 표시 이름) 추가.
    카드에 모델이 없는 LLM 항목은 결과 manifest의 모델(`llm_model`)로 채운다. 계약 값 `gen`은 그대로.
    `_status.notices`, 단계 사유(`pipeline` 로그·`stages_not_ok`), `empty_reason`, 예상 심사평 `why`에 `display_text`.
- `src/neumann/webui/index.html`: `genLabel(g, genl)`·`genName(g)`가 서버 표시 이름을 먼저 쓴다(카드 배지, 근거 패널 카드,
  예상 심사평 머리, 체크리스트, 추적 Generate, 패널 경고). 대비 표 `GEN`·`FITGEN`에서 astra 문구 제거.
  CSS 클래스 `.gen.astra`(보이지 않는 이름)는 그대로 둬서 디자인 헝크와 겹치지 않게 했다.
- `src/neumann/api/export.py`(README·`neumann_report.md`·`plan_annotated.md`·`ai_context.md`): 생성 방식 요약·카드별 줄·
  카드 범례·체크리스트 줄을 표시 이름으로, 알림·단계 사유에 `display_text`. JSON 파일(risk_cards·evidence_pack·manifest)은
  그대로. README와 ai_context에 JSON 설명 한 줄 `JSON_GENERATOR_NOTE`:
  "JSON 값 `generator: "astra"`는 계약 이름(제품 LLM)이고 모델명이 아니다. 실제 모델은 `model`(카드·예상 심사평·체크리스트)에 있다."
  리포트의 예상 심사평 JSON 블록 앞에는 `생성: LLM (모델명)`만 적는다(설명 한 줄은 README·ai_context에만).
  LLM 카드가 0장이면 요약에 모델명을 붙이지 않는다("LLM 0장").
- `eval/report_card.py`: 시스템 이름 `"Neumann (astra)"` → `"Neumann (LLM)"`, generator 개수 dict 표기 → `LLM 8 · 비상 규칙 2`,
  한계 문구의 "astra 카드" → "LLM 카드", 표 칸(`_cell`: 조건·한계·입력)에 `display_text`(입력 JSON 문구도 표시에서만 바꿈).
- 테스트
  - 새 `tests/e4/test_display_generator.py`(17건 + 스크린샷 1건 선택): 표시 함수(조사 포함), 화면 뷰에 astra 없음(계약 값 `gen`·
    원결과 `result`·dict 키 제외), 모델 대비(manifest), 규칙≠LLM, mock 표시, 실제 astra 모델만 예외, ZIP 사람용 문서 5개에 astra
    없음(```json 블록과, README·ai_context의 설명 한 줄만 허용), LLM 0장이면 모델명 없음, JSON 값 그대로, 입력(저장 JSON) 불변.
  - 새 `tests/e4/test_webui_gen_labels.py`(2건, 정적·기본 pytest): index.html의 문자열 리터럴·마크업 텍스트·한 줄 주석에 astra
    표시 문자열 없음(비교용 키 `'astra'`만 허용), `GEN`·`FITGEN` 값에 astra·"mock provider" 없음, `genLabel` 호출은 모두
    `x.gen, x.genl`, 집계는 `D._status.generator_labels`·`genName`. DISP-1 이전 index.html(6dea51e)에서는 두 건 모두 실패함을 확인.
  - 새 `tests/e5/test_report_card_display.py`(3건): 리포트 카드에 astra 없음, 실제 모델명·입력 파일 이름은 그대로, 규칙·mock 행.
  - 기존 테스트 새 문구로: `tests/e4/test_export.py`, `tests/e5/test_report_card.py`, `tests/e2e/e2e_checks.py`(카드 배지를
    서버 `genl`과 비교, 대비 표 `GEN_LABEL` 새 이름), `tests/e2e/test_e2e_checks.py`(카드 0장 사유는 화면 문구 기준).

## 완료 기준별 명령과 출력

공통 환경: `NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." PYTHONUTF8=1 PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`
(+ `NEUMANN_DATA_DIR`·`NEUMANN_RAW_DIR`·`NEUMANN_EMBED_MODEL`), `NEUMANN_LIVE_LLM_OK`·`NEUMANN_LIVE_TESTS` 없음.
파이썬 `C:/Users/User/.venvs/neumann/Scripts/python.exe`.

1. `python -m pytest tests/e4 tests/e5 -q`

   ```
   418 passed, 9 skipped in 37.06s
   ```

2. mock 서버 화면 스크린샷 — `NEUMANN_UI_SHOTS=1 NEUMANN_UI_SHOTS_OUT=docs/reports NEUMANN_UI_SHOTS_PORT=8137 python -m pytest tests/e4/test_display_generator.py -k screenshot -rA`

   ```
   PASSED tests/e4/test_display_generator.py::test_screenshot_llm_badge_without_astra
   1 passed, 15 deselected in 15.66s
   ```

   uvicorn(mock, `OPENAI_API_KEY`·`NEUMANN_LIVE_LLM_OK`·`NEUMANN_ALLOW_ASTRA` 제거)을 8137에 띄우고 `/premortem/view` 응답을
   openai 모양 결과(카드 generator astra, model gpt-6.1-sol, 알림·단계 사유에 파이프라인의 astra 문구)로 바꿔 그렸다.
   검사: 카드 배지 전부 `LLM (gpt-6.1-sol)`, 추적 `LLM (gpt-6.1-sol) 2장`, 예상 심사평 머리 `LLM (gpt-6.1-sol)`,
   `document.body.innerText`에 astra 없음, 페이지 오류 0.
   - `docs/reports/DISP-1_cards.png`: 카드 배지 `LLM (gpt-6.1-sol)`
   - `docs/reports/DISP-1_trace.png`: 체크리스트 `LLM (gpt-6.1-sol)`, 추적 Generate `LLM (gpt-6.1-sol) 2장 · 모델 gpt-6.1-sol · openai`

3. `python scripts/verify.py`

   ```
   1226 passed, 28 skipped in 282.85s (0:04:42)
   보안: 파일 411개
   계약: 2개
   테스트: 통과
   verify 통과
   ```

## 사람이 보는 출력 경로 전수 확인(`grep -rn astra src eval scripts`)

E5-L2d 보고서(`docs/reports/E5-L2d.md`)는 아직 없어서 직접 확인했다.

| 경로 | 처리 |
|---|---|
| index.html `GEN`·`FITGEN` 표, `genLabel`·`genName` 호출 6곳 | 서버 표시 이름 사용(이번 과제) |
| view.py 카드·심사평·체크리스트·상태 | `genl`·`generator_labels`·`display_text`(이번 과제) |
| export.py README·리포트·plan_annotated·ai_context | 표시 이름·`display_text`(이번 과제). JSON 파일은 계약 그대로 |
| eval/report_card.py 시스템 이름·조건·한계 | 표시 이름·`display_text`(이번 과제) |
| pipeline.py `MOCK_NOTICE`("실제 astra 분석이 아니다")·`FITNESS_MISSING`, queries.py 캐시 알림 | 원문(E3 소유)은 그대로, 화면·ZIP에서는 `display_text`로 "LLM" |
| api/main.py `/health`의 `llm.astra_allowed` 키, precomputed `cards_by_generator` | JSON 키·값(사람이 보는 화면에 안 그림) — 그대로 |
| index.html CSS `.gen.astra` | 클래스 이름(안 보임) — 그대로(디자인 헝크 회피) |
| scripts/build_static_site.py `_model_of` | 모델 미기록 결과일 때만 "미기록(생성 방식 astra)" — E6 소유라 안 고침(다음 과제로) |
| analyze/*, llm.py, config.py, eval 추출기 등 | 주석·docstring·예외 메시지·CLI 인자(`--generator astra`)·파일 이름 — 사람용 화면 출력 아님 |

## 바꾼 파일

`src/neumann/api/view.py`, `src/neumann/webui/index.html`, `src/neumann/api/export.py`, `eval/report_card.py`,
`tests/e4/test_display_generator.py`(새), `tests/e5/test_report_card_display.py`(새), `tests/e4/test_export.py`,
`tests/e5/test_report_card.py`, `tests/e2e/e2e_checks.py`, `tests/e2e/test_e2e_checks.py`, 이 보고서와 스크린샷 2장.
계약(`contracts/`, `models.py`)은 건드리지 않았다(ui_view는 추가 필드를 허용한다: `genl`, `_status.generator_labels`).

## 결정(지시가 모호해서 고른 것)

1. **표시 이름.** 과제 파일은 rule "비상 규칙"·mock "mock(시험용)", 조정 메시지는 mock "모의(mock)"·rule "규칙". mock은 최근 지시인
   "모의(mock)"을, rule은 "비상 규칙"을 골랐다("규칙"을 포함하고, AGENTS.md "비상 경로로 돌면 화면에 표시"를 배지에서도 지키려고).
   바꾸려면 `view.GENERATOR_DISPLAY` 한 줄만 고치면 된다(테스트 몇 줄 같이).
2. **JSON 설명 한 줄의 astra.** 과제 파일이 "JSON 문서 설명에 'astra는 계약 이름, 실제 모델은 model'을 한 줄 적는다"라고 해서
   README·ai_context에만 `JSON_GENERATOR_NOTE`를 둔다(검증 지적으로 리포트에서는 뺐다). 사람용 문서에서 astra 글자는 이 줄과
   리포트의 ```json 블록(결과 값 그대로)에만 나온다(테스트가 그것만 허용).
3. **자유 문구 변환.** 파이프라인(E3 소유) 문구의 astra를 고치지 않고 표시 단계(`display_text`)에서 바꿨다. 경계 규칙으로 모델명·파일
   이름은 보존한다. 바로 붙은 조사는 받침에 맞게 바꾼다: "astra가" → "LLM이", "astra는/를/와/로/라/나/랑" →
   "LLM은/을/과/으로/이라/이나/이랑". 예: "astra 판단" → "LLM 판단", "astra가 앞서 만든" → "LLM이 앞서 만든".
4. **모델 대비.** 카드에 `model`이 없는 LLM 카드는 결과 manifest의 `llm_model`(없으면 `model_id`·`model`)로 표시한다. 둘 다 없으면
   "LLM"만(지어내지 않음).
5. **리포트 카드 입력 문구.** 다른 과제가 만든 지표 JSON의 조건·한계 문구(예: `generator {'astra': 13}`)도 표 칸 출력에서만
   `{'LLM': 13}`으로 보인다. 입력 파일은 그대로이고, 실제 모델명(`평가 모델 gpt-6-astra`)은 그대로 보인다.

## 검증 뒤 수정(PASS-조건부, 20211eb 이후)

1. `neumann_report.md`의 JSON 설명 한 줄 제거(README·ai_context만). 테스트가 문서별 허용 여부를 검사한다.
2. LLM 카드가 0장이면 요약·생성 방식 목록에 모델명을 붙이지 않는다(`export._gen_name`: "LLM 0장"). 테스트 추가.
3. 조사: `display_text`가 astra 뒤에 붙은 조사를 받침에 맞게 바꾼다("LLM가" → "LLM이"). 쓰이지 않던
   `GENERATOR_DISPLAY["astra"]` 항목 삭제(astra는 모델명을 붙여 `display_generator`가 만든다). 적합성 훅 `FITGEN.mock`
   "mock provider" → "모의(mock)"(`tests/e4/test_templates_ui.py`는 "mock" 포함만 보므로 주석만 고침).
4. 기본 pytest 정적 회귀 테스트 `tests/e4/test_webui_gen_labels.py` 추가(위 테스트 목록). 예전 정적 검사 1건은 여기로 옮겼다.

검증 뒤 수정 반영 후 다시 잰 값(같은 환경):

```
python -m pytest tests/e4 tests/e5 -q   → 422 passed, 9 skipped in 45.84s
python scripts/verify.py                → 1230 passed, 28 skipped in 294.47s · 보안: 파일 413개 · 계약: 2개 · 테스트: 통과 · verify 통과
```

## 다른 브랜치와 겹칠 수 있는 파일·헝크

처음 확인(E4-L2f 552e9de·E4-L3m 88f1b51·E5-L3b 849cdaa·main aed34b7)에서는 모두 텍스트 충돌이 없었다. 검증 반영 뒤(9c2eef8)
최신 머리로 다시 확인한 결과(임시 worktree에서 실제 `git merge --no-commit` 후 되돌림):

| 상대 | 머리 | 결과 |
|---|---|---|
| main | 29d96ee | 충돌 없음 |
| E4-L3m | 58191fc | 충돌 없음. 합친 트리에서 `test_responsive.py`·이번 테스트 19 passed, 2 skipped |
| E5-L3b | 4cb5f39 | 충돌 없음. 합친 트리에서 `tests/e5` 213 passed, 4 skipped(아래 의미 충돌은 E5-L3b가 `rc.SYSTEM_LABELS`를 쓰게 바꿔 해소됨) |
| E4-L2f | a5d053f | **`src/neumann/api/export.py` 텍스트 충돌 8헝크**(view.py·index.html·test_export.py는 자동 병합) |

**E4-L2f 충돌(a5d053f, b2471dc "서명 확인 → result_origin")**: E4-L2f가 같은 자리에 `_gen_short(c, g)`·`_gen_desc(c, g)`·
`_gen_label(c, card)`(서명 미확인이면 "결과에 적힌 표기, 미확인"), `_code(...)`, `_json_md(...)`, `_one_line(item_id)`를 넣었다.
충돌 자리: `_checklist_line`의 "생성 …" 줄, `_gen_label`·`_gen_summary` 정의, README "## 생성 방식"·카드별 줄, `_card_legend`,
리포트 "## 생성 방식과 단계"·카드 "생성:" 줄, 예상 심사평 JSON 블록 머리, ai_context 카드 "generator:" 줄.
나중에 병합하는 쪽의 해소 방법(두 쪽 의미를 다 살림): E4-L2f 구조를 그대로 두고 표시 이름만 DISP-1 함수로 바꾼다.

- `_gen_short(c, g)`: 서명 확인이면 `_gen_name(c, g)`(DISP-1, "LLM (모델명)"·LLM 0장이면 모델 없음), 미확인이면
  `f"{display_generator(g.value)}(결과에 적힌 표기, 미확인)"`. `_gen_summary`는 E4-L2f 판 그대로(`_gen_short` 사용).
- `_gen_label(c, card)`: 서명 확인이면 `display_generator(card.generator.value, _one_line(card.model or '') or _result_model(c.result))`,
  미확인이면 `_gen_short(c, card.generator)`(+ 모델이 있으면 `, 모델 …`).
- README·리포트 생성 방식 목록: `f"- **{_gen_short(c, g)}** {c.gen_counts[g.value]}장: {_gen_desc(c, g)}"`.
- 예상 심사평: DISP-1의 `생성: …` 줄 + E4-L2f의 `_json_md(...)` 블록. 체크리스트 줄: E4-L2f의 `_one_line(item_id)` + DISP-1의 `display_generator`.
- ai_context 카드 줄: `f"- 생성: {_gen_label(c, card)}" + ("" if c.verified else " — 결과에 적힌 표기, 미확인")`.
- 정책 확인 필요(PM): E4-L2f의 `_gen_desc` 미확인 문구 "결과에 generator={g.value}로 적힌 카드"와 그 테스트
  (`tests/e4/test_export_ui_sign.py` 138행 `"결과에 generator=astra로 적힌 카드"`)는 JSON 값을 인용하는 문구라 astra가 남는다.
  JSON 값 인용으로 허용할지, "결과에 LLM(generator 값 astra)로 적힌…"처럼 바꿀지 PM이 정한다. 같은 테스트의
  `"astra(LLM)" not in readme`는 DISP-1 뒤에도 참이다.

E4-L2f가 먼저 main에 들어가면 DISP-1의 export.py를 그 위에 다시 얹는 작업(위 방법, 30분 안팎)을 이 브랜치에서 할 수 있다.

- `src/neumann/webui/index.html`(E4-L2f·E4-L3m): 460(GEN, 주석 2줄 추가), 470(genLabel → genName + genLabel), 558(FITGEN),
  754(카드), 762(심사평 머리), 767~768(체크리스트·genTxt), 786(panelWarn), 808(근거 패널 카드) — 모두 한 줄짜리 치환.
  E4-L2f의 472(renderSteps)와 한 줄 떨어져 있다. CSS는 안 건드림(E4-L3m 반응형과 무관).
- `src/neumann/api/view.py`(E4-L2f): 53 근처 표시 함수, `_build_cards`·`_build_review`·`_build_checklist`·`_build_pipeline` 각
  1~4줄, `_generator_labels`(공개 함수 머리 앞), `_build`의 notices·generators·empty_reason 3줄. E4-L2f의 `build_ui_view`·
  `_attach_result`와 떨어져 있다. E4-L2f가 붙이는 `view["result"]`(원결과 JSON)의 astra는 계약 값이라 그대로(테스트도 제외).
- `eval/report_card.py`(E5-L3b): import, `SYSTEM_LABELS["neumann"]`, macro·linkage 조건 문구, `_gens_text`(새), `_cell`.
  E5-L3b의 `METRIC_LABELS`·`EXPECTED_DETAIL`·`BACKTEST_LIMIT` 헝크와 떨어져 있다.
- **의미 충돌(해소됨):** E5-L3b 849cdaa의 `tests/e5/test_metrics_from_e2e.py::test_output_feeds_report_card`가
  `"Neumann (astra)"`를 기대해 합친 트리에서 1건 실패했으나, E5-L3b 4cb5f39가 `rc.SYSTEM_LABELS["neumann"]`을 쓰게 바뀌어
  합친 트리 `tests/e5` 213 passed. E5-L3b가 커밋한 `docs/reports/report_card.md`는 병합 뒤 다시 생성해야 새 이름이 반영된다.

## 못 한 것

- `scripts/build_static_site.py`(E6)의 모델 미기록 경우 "미기록(생성 방식 astra)" 문구는 소유가 아니라 두었다.
- `docs/reports/report_card.md`(E5-L3b 산출물)는 재생성하지 않았다(E5-L3b 헝크와 겹침).

## 다음 과제에 넘길 것

- E6: `build_static_site._model_of`에서 `neumann.api.view.display_generator`를 쓰면 정적 판도 같은 이름이 된다.
- E3(선택): `pipeline.MOCK_NOTICE`·`FITNESS_MISSING`·queries 캐시 알림의 "astra"를 "LLM"으로 바꾸면 원문도 맞는다(화면은 이미 변환).
- E5: 병합 뒤 `python -m eval.report_card …`로 `docs/reports/report_card.md` 재생성.
- PM: E4-L2f와의 export.py 충돌 해소(위 방법) 또는 병합 순서 지정, 서명 미확인 문구의 astra 허용 여부 결정.
