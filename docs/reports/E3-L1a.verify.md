# E3-L1a 검증 보고서 (Sonnet 5.5, 빌더: Opus 5.5)

- 대상: 브랜치 `task/E3-L1a` (HEAD `74bbe79`), worktree `.claude/worktrees/agent-a1a9b1a6777db609a`
- 방법: 빌더 보고서를 믿지 않고 완료 기준을 다시 실행하고, 가짜 `llm_call`과 조작 입력으로 게이트를 직접 공격했다. 코드는 고치지 않았다. 변이 시험은 worktree를 임시 폴더로 복사해서 했고 원본에는 손대지 않았다.
- 환경: `_COMMON.md`의 환경변수(`PYTHONPATH="src;."` 등), Python `C:/Users/User/.venvs/neumann/Scripts/python.exe`

## 최종 판정: PASS-조건부

핵심 기능(근거 없는 문장·없는 id·조작 인용·근거 없는 수치 제거, 실패 시 규칙 합성 표기, 라이브 astra 1회)은 실제로 동작한다. 다만 `generator` 표기에 정직성 결함이 하나 있다. 속성 없는 callable이 설정 기본값(openai)에서 `astra`로 표기된다. 이것은 병합 전에 고쳐야 한다.

### 병합 전 고칠 것

1. **속성 없는 callable을 `astra`로 표기한다 (완료 기준 밖이지만 AGENTS.md "규칙·가짜 결과를 LLM 생성이라고 쓰지 않는다" 위반 위험).** `review._resolve_generator`는 인자도 `llm_call.generator` 속성도 없으면 설정 `NEUMANN_LLM_PROVIDER`(기본값 `openai`)를 보고 `astra`, model은 `gpt-6-astra`로 채운다. 실제로 무엇이 호출됐는지는 확인하지 않는다.
   - 재현: 환경변수 `NEUMANN_LLM_PROVIDER`를 지운 채(기본 openai), `fx = load_fixtures().premortem_result`에 대해 `generate_expected_review(fx, lambda schema, instructions, input, *, effort: {"strength": [], "request": [], "weakness": [{"text": "누출 위험.", "excerpt_ids": ["ex_110f92f3599151f1"], "card_ids": ["card-fx-leak"], "plan_lines": []}]})`
   - 결과: `generator="astra", model="gpt-6-astra", status="ok", generator_source="settings"`. 같은 코드에서 `NEUMANN_LLM_PROVIDER=mock`이면 `mock`.
   - 빌더 테스트 `test_generator_label_comes_from_llm_call_or_settings`는 `tests/conftest.py`가 provider를 mock으로 강제하기 때문에만 통과한다. 기본 설정에서는 그 테스트가 말하는 "astra로 부풀리지 않는다"가 성립하지 않는다.
   - 권장 수정: 설정에서 astra를 추론하지 않는다. 인자 `generator=` 또는 `llm_call.generator` 속성이 있을 때만 그 값을 쓰고, 없으면 `mock`(또는 새 값 없이 예외/None)으로 표기하고 `generator_source="unspecified"`로 남긴다. astra 표기는 실제 응답을 본 `ProviderLLMCall`(호출 뒤 provider 결과의 generator를 채움)이나 명시 인자에서만 나오게 한다. 새 테스트는 conftest 환경과 무관하게(`monkeypatch.setenv("NEUMANN_LLM_PROVIDER","openai")` 후) bare callable이 astra가 아님을 확인해야 한다.

### 병합 후로 미뤄도 되지만 PM이 알아야 할 한계

2. **숫자 게이트가 넓게 열려 있다.** 규칙 5는 "숫자 토큰이 계획서 전체·인용 카드 문구·집계값 어디에든 있으면 허용"이다. fixture 기준 허용 집합은 `{1,2,3,4,5,10,80,12000}`(계획서 번호·헤더 포함)과 `{2,3,8}`(유사 연구·근거·카드 개수)다. 그래서 단위와 상관없이 `5%`, `3배`가 통과한다(계획서 `## 5.` 헤더와 유사 연구 수 3에 걸린다). 근거에 전혀 없는 값(`30%`, `0.95`, `20,000건`, `0.3`, 전각 `３０`, `7개`)은 모두 떨어진다. 빌더 보고서 "결정"에 허용 범위가 적혀 있어 숨긴 것은 아니다. 개선 권고: 계획서 헤더 줄(`#`로 시작)의 번호는 제외하고, 집계값은 "편·건·개"류 단위가 붙을 때만 허용하며, 계획서 숫자는 문장이 인용한 줄 번호에 있는 것으로 좁힌다.
3. **인식하지 못하는 인용 부호**: `《…》`, 전각 `＂…＂`, 백틱 `` `…` ``로 감싼 조작 인용은 게이트를 통과한다(인용으로 안 본다). 문자에 붙은 숫자(`x30`)와 한글 수사(`삼십 퍼센트`)도 못 잡는다. 지시문이 따옴표를 금지하고 스키마에 인용 필드가 없어 실사용 위험은 낮다. 알려진 한계로 남기면 된다.
4. LLM 경로에서 코드가 근거 원문을 잘라 붙이는 기능은 없다. 게이트는 **모델이 쓴 따옴표 인용을 원문과 대조**한다(통과한 인용의 `text`는 원문 부분문자열과 동일, 오프셋은 `ex.start+idx`). 그리고 모델이 인용을 안 쓰므로 라이브 결과의 `quotes`는 전부 `[]`다(아래). 원문 인용이 화면에 필요하면 E4가 `c`의 excerpt id로 원문을 불러 붙이면 된다. 규칙 합성 경로는 코드가 원문에서 잘라 붙인다.
5. E3-L0 `llm.py`가 아직 main에 없어서 `test_real_llm_mock_provider_reaches_review_path`는 건너뛴다(빌더도 적음). E3-L0 병합 뒤 건너뛰지 않고 도는지 확인해야 한다.

## 완료 기준 재측정

| # | 항목 | 실행한 명령 | 실제 출력(핵심) | 결과 |
|---|---|---|---|---|
| 1 | tests/e3 | `pytest tests/e3 -q -rs` | `42 passed, 2 skipped in 0.39s` (skip: llm.py 없음 1, `NEUMANN_LIVE_TESTS` 아님 1) | 통과 |
| 2 | verify.py | `python scripts/verify.py` | `268 passed, 2 skipped`, 보안 137개 파일·계약 2개·`verify 통과` | 통과 |
| 3 | 근거 없는 문장 제거 | 직접 공격(`attack_gate.py`, 52건) | `no_evidence`·`card_only` → `missing_citation` | 통과 |
| 4 | 없는 id 제거 | 같은 스크립트 | 없는 excerpt(단독·진짜와 혼합)→`unknown_excerpt_id`, 없는 카드→`unknown_card_id`, 다른 카드의 근거→`excerpt_card_mismatch`, 범위 밖 줄→`unknown_plan_line` | 통과 |
| 5 | 조작 인용 제거 | 같은 스크립트 | 따옴표 7종(`" “” ‘’ ' 「」 『』 «»`)+`„“`, 한 글자 변경, 대소문자 변경, 이중 공백, 생략부호 이어붙이기, 19자 부분문자열, 3자 `MAE`, 미인용 근거·미인용 계획서 줄의 진짜 문장, 한국어 번역, 짝 안 맞는 따옴표, 진짜+가짜 혼합 → 모두 `quote_mismatch`. 진짜 20자 이상 부분문자열·전체 문장·인용한 계획서 줄은 통과 | 통과 (단 한계 3 참조) |
| 6 | 근거에 없는 숫자 제거 | 같은 스크립트 | `30%`, `R² 0.95`, `20,000건`, `0.3`, 전각 `３０`, `7개` → `fabricated_number`. 계획서의 `12,000`은 통과 | 부분 통과 (한계 2: `5%`·`3배`는 통과) |
| 7 | 인용 오프셋 = 원문 | 통과한 인용 4건을 `fx.source_text(ex)[start:end]`와 비교 | 전부 `True` (예: `start=87 end=139`, `leak near-duplicate scaffolds between train and test`). 계획서 줄 인용도 `True`. 규칙 합성 인용도 전부 원문과 일치 | 통과 |
| 8 | 모델의 여분 필드가 결과에 새지 않는가 | 모델 응답에 `"quote": "FAKE QUOTE ..."` 추가 | 결과 JSON에 없음. 문장 키는 `c, cards, plan_lines, quotes, t`뿐 | 통과 |
| 9 | 실패 시 규칙 합성 표기 | `attack_review.py` 시나리오 3, 10가지 실패 | `None`, `TimeoutError`, `RuntimeError`, list·str·`{}` 반환, 섹션이 문자열 목록, 전부 게이트 탈락, `llm_call=None`, bare None 반환 → 모두 `generator="rule", model=None, status="degraded", generator_source="fallback"`, `reason`에 사유, 규칙 문장 재검증 폐기 0, 강점은 비어 있음. `attach` 뒤 `result.status="degraded"`, 단계 `impl="fallback:rule"` | 통과 |
| 10 | 속성 없는 callable 표기 | `attack_review.py` 시나리오 2 | provider=`openai`(기본) → **`astra`, `gpt-6-astra`**(`generator_source="settings"`), provider=`mock` → `mock` | **실패** (병합 전 수정 1) |
| 11 | 카드 0장 | 카드 비운 결과 | 호출 안 함, `status="skipped"`, `generator=None`, ui·API 계약 통과 | 통과 |
| 12 | 계약 | `ui_view.schema.json`의 review, `premortem_response.schema.json` | skipped·규칙 합성·LLM 경로 모두 검증 통과 | 통과 |
| 13 | 라이브 astra 1회 | `NEUMANN_LIVE_TESTS=1 pytest tests/e3/test_review_live.py -s -q` (키는 참·거짓만 확인: `True`) | `1 passed in 11.53s`. `generator=astra`, `model=gpt-6-astra`, `status=ok`, `gen=4 pass=4 drop=0`, `latency 11.36s`, `linked_rate=1.0`, `quotes`는 전부 `[]`(모델이 인용을 안 씀), 통과 문장을 게이트로 다시 검사해도 폐기 0. 키·헤더는 출력되지 않았다 | 통과 |
| 14 | 소유 경로·계약 | `git diff main...task/E3-L1a --stat` | 6개 파일: `docs/reports/E3-L1a.md`, `analyze/gate.py`, `analyze/review.py`, `tests/e3/test_gate.py`, `test_review.py`, `test_review_live.py`. `llm.py`·`pipeline.py`·`contracts/`·`models.py`·`config.py`·`tests/fixtures/`·`.env.example` 변경 없음. 키 패턴 grep 0건 | 통과 |
| 15 | 항상 통과하는 테스트인가 | 변이 시험 15건(worktree 복사본) | 15건 전부 테스트가 잡음: 근거 id 검사 제거, 없는 excerpt/카드/계획서 줄 검사 제거, 인용 항상 통과, 숫자 검사 제거, 최소 인용 길이 20→5, 카드-근거 불일치 검사 제거, 규칙 합성을 astra로 표기, 규칙 합성 status=ok, PII 검사 제거, 오프셋에서 `ex.start` 제거, 설정 폴백 항상 astra(변이 12), 한 문장 실패에 전체 폐기, 예외 미포착 | 통과 (단 변이 12는 conftest의 mock 강제에 의존해 잡힌 것: 수정 1과 같은 문제) |

## 정직성 확인 요약

- 인용: 게이트는 인용 부호 안의 문자열이 인용한 근거(또는 인용한 계획서 줄)와 글자 그대로 같거나 20자 이상 연속 부분문자열일 때만 통과시키고, 통과 시 `quotes[]`에 원문 오프셋을 붙인다. 표본 4건 오프셋이 원문과 일치했다.
- 강등: 모든 실패 경로가 `generator="rule"`, `status="degraded"`, `reason`, `attempts`(LLM 시도 기록 + 규칙 시도)를 남긴다. LLM 문장이 전부 떨어져 규칙으로 간 경우 LLM 폐기 기록도 audit에 남는다(`gen = pass + drop`).
- 규칙 결과를 LLM 결과로 표기하는 경로는 실패 경로 쪽에서는 발견하지 못했다. 위 수정 1은 성공 경로에서 "무엇이 호출됐는지 모르는 callable"을 astra로 적는 문제다.
- 게이트 자체는 형식·근거 존재 검사이고 의미 검증(문장이 근거를 실제로 뒷받침하는지)은 하지 않는다. 빌더가 L2(E3-L1b) 몫으로 명시했다.

## 재현용 스크립트(저장소 밖, scratchpad)

- `attack_gate.py`(게이트 52건), `attack_review.py`(표기·규칙 합성 시나리오), `mutate.py`(변이 15건). worktree에는 남기지 않았고 검증 중 생긴 `.pytest_cache`는 지웠다(`git status --ignored` 깨끗).
