# E3-L1c 보고서 — 입력 적합성 판정·무관 입력 차단·개인정보 마스킹 강화

- 빌더: claude-opus-5.5 · 브랜치 `task/E3-L1c` · 검증 대기(Sonnet)
- 소유 파일만 만들었다: `src/neumann/analyze/fitness.py`, `src/neumann/analyze/pii.py`, `tests/e3/test_fitness.py`, `tests/e3/test_fitness_live.py`, `tests/e3/test_pii.py`
- E3-L0(llm.py·pipeline)은 main에 아직 없어서 `llm_call`을 **주입**받는 방식으로 독립적으로 만들었다(E3-L1a와 같은 시그니처).

## 무엇을 했나

### 1. `analyze/pii.py` — 숫자열 기반 개인정보 마스킹

`06_교훈_함정` ID-90·91(형식 열거는 점검마다 뚫렸다)을 따라 **형식을 열거하지 않는다.**

- 숫자 덩어리를 찾고, 1~3글자 구분자(공백·하이픈류 10종·점·괄호·가운뎃점, 줄바꿈 제외)로 이어진 덩어리를 사슬로 묶는다. 사슬의 **숫자 개수·첫 숫자·묶음 길이**로 판단한다(국내 0으로 시작 9~11자리 / `+` 국제 8~15자리 / `00` 국제 접두 / `+` 없는 `82-…`). 긴 사슬 안에서는 가장 긴 유효 부분 사슬을 고른다(`010-1234-5678 2024` → `[PHONE] 2024`).
- **유니코드 숫자:** 10진 숫자(Nd: 전각·아랍-인도·데바나가리 등)를 ASCII로 1:1 치환한 사본에서 탐지한다. 길이가 같아 오프셋이 원문과 그대로 맞는다.
- **경계 가드:** 앞뒤가 영문자·숫자·밑줄이면 버린다(`R2.3`, `ex_0123…`, `abc0101…xyz`). 한글 조사(`…5678로`)는 허용. 천 단위 쉼표·소수점 한가운데서 자르지 않는다. URL·DOI·arXiv 구간 안은 전화·주민번호로 보지 않는다.
- **오탐 방지:** 점 구분자는 "모든 구분자가 점 하나 + 묶음 3개 이상"일 때만(`0.95`, `0.12 0.34 0.56` 보존). `15xx-xxxx` 대표번호와 7~8자리는 앞 24자 안에 `전화·연락·휴대·문의·Tel·Phone·Fax·☎` 단서가 있을 때만(`1600-1700` 연도 범위 보존). 단서가 있어도 날짜·증가 연도 범위는 제외.
- **주민등록번호 형태:** `YYMMDD[-]?[1-8]NNNNNN`, 뒷자리가 `*`로 가려진 형태 포함(생년월일·성별이 드러남). 월·일 유효성 검사.
- **이메일·ORCID는 `models.EMAIL_RE`·`ORCID_RE` 재사용**(`models.redact_pii`와 결과 동일, 테스트로 확인). 겹치면 email > orcid > rrn > phone 우선.
- 태그: `[EMAIL]` `[ORCID]` `[RRN]` `[PHONE]`. 두 번 불러도 같다(멱등).

### 2. `analyze/fitness.py` — 입력 적합성 판정

- **주력 astra:** `llm_call(FITNESS_SCHEMA, INSTRUCTIONS, input, effort="low")`. 입력은 빈 줄을 뺀 `번호: 본문` 목록(개인정보 재마스킹, 12,000자 상한). 모델은 `verdict`(research_plan·not_research_plan·uncertain), 요소 4개(연구 질문·방법·데이터·평가)별 `present`+**계획서 줄 번호**, `field`(한국어 분야), `reason`(한국어 1~2문장, 인용 대신 줄 번호)만 돌려준다. 스키마는 OpenAI strict 호환(테스트로 확인).
- **로컬 재검증:** jsonschema 재검사 → 범위 밖·빈 줄 번호 폐기(건수 `checks.dropped_lines`) → 근거 줄이 없는 "있음"은 없음으로 → 사유·분야도 개인정보 마스킹.
- **비상 경로:** `llm_call`이 None·예외·스키마 위반·깨진 JSON·빈 사유면 규칙 판정(요소별 한·영 키워드 + 조리법·여행·쇼핑 등 장르 표지 + 길이)으로 대신하고 `generator="rule"`, `status="degraded"`, `degraded_reason`에 사유.
- **판정 세 갈래(과잉 거절 방지, `06_교훈_함정` ID-97):** `fit`(분석) / `unfit`(**분석하지 않음** + 사유) / `uncertain`(거절하지 않고 분석 진행, 빠진 요소와 보완 질문 표시). 모델이 "연구 아님"이라 해도 규칙이 fit이면 `uncertain`으로 내린다. 모델이 "연구"라 해도 근거 줄이 있는 요소가 2개 미만이고 규칙도 fit이 아니면 `uncertain`. 신호를 하나에 걸지 않는다(모델 판정 + 근거 줄 + 규칙 신호).
- 공백 제외 40자 미만은 호출하지 않고 `unfit`(`decided_by="precheck"`, 강등 아님).
- 언어(`ko`·`en`·`mixed`·`unknown`)는 코드가 한글·로마자 글자 수로 잰다.
- `fitness_stage(result) -> StageStatus`로 파이프라인 단계 기록을 만든다(`name="fitness"`, 강등이면 `degraded`, `impl`에 실제 경로).

## 완료 기준별 결과

### 1. 테스트: 전화번호 변형 10종 이상, 오탐 보존, 조리법 → 부적합, 데모 3건 → 적합 — **통과**

```
$ python -m pytest -q tests/e3/test_pii.py tests/e3/test_fitness.py tests/e3/test_fitness_live.py
134 passed, 4 skipped in 0.53s          # 4 skipped = 실제 API 테스트(NEUMANN_LIVE_TESTS 없음)

$ python -m pytest -q tests/e3/test_pii.py -k "phone_variant_masked or false_positive_preserved or at_least_ten"
62 passed, 42 deselected in 0.25s
```

- 전화번호 변형 **25종** 마스킹(`PHONE_VARIANTS`): `010-1234-5678`, `010 1234 5678`, `010.1234.5678`, `01012345678`, `010 - 1234 - 5678`, `010·1234·5678`, U+2010·en dash·U+2212 하이픈, `02-123-4567`, `02-1234-5678`, `(02) 123-4567`, `031-123-4567`, `0505-123-4567`, `+82-10-1234-5678`, `+82 10 1234 5678`, `+82 (0)10 1234 5678`, `+82-2-123-4567`, `82-10-1234-5678`, `+1 (555) 123-4567`, `+44 20 7946 0958`, 전각 숫자+전각 하이픈, 아랍-인도 숫자, 데바나가리 숫자, 전각 `＋82`. 같은 25종을 한국어 문장 속(`연락처 …로 해 주세요.`)에서도 검사. 단서가 있을 때만 가리는 짧은 번호 3종(`Tel: 1588-1234` 등)과 단서 없으면 보존 3종.
- 오탐 보존 **36종**(`PRESERVED`): 필수 4종 `2024`, `0.95`, `10.1234/abc`, `R2.3` + `2023-2024`, `1600-1700`, `2024-01-15`, `문의 2024-01-15`, `12,000건`, `1,234,567,890`, `80/10/10`, `0.1234 0.5678 0.9012`, `0.123456789`, DOI URL, `doi:10.1016/…`, `arXiv:2401.01234`, `ex_0123456789abcdef`, `192.168.0.1`, ISBN 2종, `offset 1024-2048`, `start=1234, end=5678`, `[1234:5678]`, `L12-L34`, `vIoU@0.3`, `010\n1234-5678`(줄바꿈은 잇지 않음) 등. 데모 계획서 3건·조리법 원문도 마스킹 전후 동일.
- 섞인 문장 검사: 지표·연도·DOI·`R2.3`는 그대로, 전화 2·이메일 1·ORCID 1만 태그로(`counts == {"phone": 2, "email": 1, "orcid": 1}`).
- 적합성(가짜 llm_call과 규칙 경로 둘 다):

```
$ python -m pytest -q tests/e3/test_fitness.py -k "demo_plans_fit or recipe_unfit" -rA
PASSED tests/e3/test_fitness.py::test_demo_plans_fit_via_llm[plan.md]
PASSED tests/e3/test_fitness.py::test_demo_plans_fit_via_llm[plan_elife_neuro.md]
PASSED tests/e3/test_fitness.py::test_demo_plans_fit_via_llm[plan_medimaging.md]
PASSED tests/e3/test_fitness.py::test_recipe_unfit_via_llm
PASSED tests/e3/test_fitness.py::test_demo_plans_fit_via_rule_fallback[plan.md]
PASSED tests/e3/test_fitness.py::test_demo_plans_fit_via_rule_fallback[plan_elife_neuro.md]
PASSED tests/e3/test_fitness.py::test_demo_plans_fit_via_rule_fallback[plan_medimaging.md]
PASSED tests/e3/test_fitness.py::test_recipe_unfit_via_rule_fallback
PASSED tests/e3/test_fitness.py::test_english_recipe_unfit_by_rule
```

  그 밖에: 예외·스키마 위반 4종·깨진 JSON·빈 사유 → 규칙 강등 표기, 잘못된 줄 번호 3개 폐기·건수 기록, 모델의 진짜 계획서 거절 → `uncertain`(과잉 거절 방지), 빈약한 아이디어 → `uncertain` + 보완 질문, 영어 초록 → fit·`en`, 40자 미만 → 호출 없이 unfit, 모델 입력의 전화번호 마스킹, 모델 사유·분야의 개인정보 마스킹, `generator="mock"` 정직 표기, 스키마 strict 호환, `fitness_stage` 강등 기록.
- 규칙 분야 추정이 데모 3건에서 서로 다르다: `재료·화학` / `신경과학·뇌영상` / `의료·의료영상`.

### 2. 실제 astra 1회 예시(`NEUMANN_LIVE_TESTS=1`) — **통과(4회 호출, 전부 기대 판정)**

openai SDK를 직접 부르는 임시 `llm_call`(Responses API, `gpt-6-astra`, strict json_schema, `reasoning.effort=low`, `store=False`).

```
PS> $env:NEUMANN_LIVE_TESTS='1'; python -m pytest -q -s tests/e3/test_fitness_live.py
4 passed in 27.89s
```

| 입력 | 판정 | 모델 판정 | generator·status | 분야(astra) | 요소별 근거 줄 | 지연 | 토큰(입/출) |
|---|---|---|---|---|---|---|---|
| plan.md | fit | research_plan | astra·ok | 배터리 전해액·머신러닝 | 질문 5,6,27 · 방법 10,11,16,17 · 데이터 15,16,17 · 평가 11,16,21,22 | 7.41s | 895/221 |
| plan_elife_neuro.md | fit | research_plan | astra·ok | 인지신경과학·fMRI 기계학습 | 질문 5,6,27,28 · 방법 10,11,16,21,23 · 데이터 10,15,16,17 · 평가 11,16,21,22,23 | 6.58s | 942/244 |
| plan_medimaging.md | fit | research_plan | astra·ok | 의료영상·딥러닝 | 질문 5,6,27,28 · 방법 10,11,16,17 · 데이터 10,15,16,17 · 평가 11,16,21,22,27 | 7.06s | 944/238 |
| negative_recipe.md | **unfit** | not_research_plan | astra·ok | (없음) | 모두 없음 | 5.74s | 925/161 |

- 폐기한 줄 번호 0건, 덮어쓰기(override) 0건, 잘림 없음.
- plan.md 사유(astra): "5–6행에 연구 목표, 10행에 모델 설계, 15–17행에 데이터와 분할·처리 방침, 21–22행에 평가 지표와 범위가 명시되어 있어 분석 가능한 연구계획서이다."
- 조리법 화면 문구(`notice`): "분석하지 않음: 5~13행은 요리 재료와 조리 절차, 17~22행은 섭취·보관 방법과 개인 메모를 설명합니다. 연구 질문이나 실험·평가 설계가 없는 요리 메모이므로 연구 계획이 아닙니다."
- 단계 기록 예: `{"name": "fitness", "status": "ok", "reason": "unfit by astra", "phase": "input", "impl": "neumann.analyze.fitness:assess_fitness", ...}`

### 3. `python scripts/verify.py` — **통과**

```
$ python scripts/verify.py
354 passed, 10 skipped in 5.59s
보안: 파일 136개
계약: 2개
테스트: 통과
verify 통과
```

## 공개 인터페이스 (파이프라인 연결용)

```python
# neumann.analyze.pii
mask_pii(text: str) -> str                                   # [EMAIL]·[ORCID]·[RRN]·[PHONE]
mask_pii_counts(text: str) -> tuple[str, dict[str, int]]     # 종류별 건수
find_pii(text: str) -> list[PiiSpan]                         # PiiSpan(kind, start, end) 원문 오프셋
has_pii(text: str) -> bool
mask_plan_text(text: str) -> tuple[str, dict[str, int]]      # normalize_text → mask
plan_document_from_text(text: str, session_id: str) -> tuple[PlanDocument, dict[str, int]]
    # PlanDocument.from_text 대신 쓰면 전화·주민번호까지 가려진다(plan_id = 가린 본문의 sha256)

# neumann.analyze.fitness
assess_fitness(plan: PlanDocument, llm_call, *, generator="astra", model="gpt-6-astra",
               effort="low", max_chars=12000) -> dict
    # llm_call(schema: dict, instructions: str, input: str, *, effort: str) -> dict | None
fitness_stage(result: dict) -> StageStatus                   # PremortemResult.stages에 넣는다
rule_fitness(plan) -> dict / detect_language(text) -> dict   # 규칙 신호(비상 경로·교차 확인)
FITNESS_SCHEMA, INSTRUCTIONS
```

`assess_fitness` 반환 키: `verdict`(fit·unfit·uncertain), `analyze`(bool), `is_research_plan`(True·False·None), `label_ko`, `reason`, `notice`(화면 문구, fit이면 None), `field`, `language`, `elements`(요소별 `present`·`plan_lines`), `missing`, `followup_questions`(uncertain일 때 `{element, question}`), `generator`, `model`, `status`(ok·degraded), `decided_by`(llm·rule_fallback·precheck), `degraded_reason`, `model_verdict`, `rule`(규칙 신호 전체), `language_detail`, `checks`(`dropped_lines`·`overrides`·`truncated`·`last_line_sent`·`pii_masked`), `elapsed_s`.

권장 연결(E3-L0 `run_premortem`):

```python
plan, pii_counts = plan_document_from_text(plan_text, session_id)
fit = assess_fitness(plan, llm_call, generator=<provider의 generator>, model=<모델 id>)
result.stages.append(fitness_stage(fit))
result.plan_checks["fitness"] = fit          # 자유 형식 칸
result.plan_checks["pii_masked"] = pii_counts
if not fit["analyze"]:                       # 무관 입력: 검색·추출·카드 단계 건너뛰고 카드 0장 + 사유
    result.notices.append(fit["notice"])
    return result
if fit["verdict"] == "uncertain":
    result.notices.append(fit["notice"])
```

E3-L0 `llm.py`(task/E3-L0 브랜치 기준 `provider.complete_json(LLMCall) -> LLMResult`)를 이 시그니처로 감싸는 예:

```python
def llm_call(schema, instructions, input, *, effort):
    r = provider.complete_json(LLMCall(task="fitness", instructions=instructions, payload={"plan": input},
                                       schema=schema, schema_name="input_fitness", effort=effort, timeout_s=30))
    return r.data if r.ok else None
# generator=r.generator 에 맞춰 assess_fitness(..., generator="astra" | "mock")
```

## 결정 (스펙이 모호해서 고른 것)

- **판정 세 갈래.** 스펙은 적합·부적합 둘이지만 `06_교훈_함정` ID-97(연구 초록 과잉 거절)을 따라 `uncertain`을 두고, 이 경우 거절하지 않고 분석을 진행하며 빠진 요소와 보완 질문(규칙 문구, LLM 생성 아님)을 알린다. "분석하지 않음"은 `unfit`뿐이다.
- **모델 판정을 그대로 믿지 않는다.** 모델 "연구 아님" + 규칙 fit → `uncertain`. 모델 "연구" + 근거 줄 있는 요소 2개 미만 + 규칙 비적합 → `uncertain`. 덮어쓴 사실은 `checks.overrides`에 남긴다.
- **언어는 코드가 잰다**(모델에 묻지 않음): 결정적이고 호출 비용이 없다. 한글 1자 = 로마자 2자 가중, 한글 비중 ≥0.6 ko, ≤0.25 en, 그 사이 mixed. 데모 3건은 0.665·0.821·0.759로 ko.
- **짧은 입력(공백 제외 40자 미만)은 호출하지 않는다.** 규칙 판정이지만 실패로 인한 강등이 아니라서 `status="ok"`, `decided_by="precheck"`, `generator="rule"`.
- **분야는 모델 값 우선, 없으면 규칙 추정.** 규칙 분야 사전은 8개 대분류뿐이다(비상 경로용).
- **`generator`·`model`은 호출부가 넘긴다.** `llm_call`은 dict만 돌려주므로 mock provider일 때 `generator="mock"`을 넘겨야 정직 표기가 된다. 모르는 값은 `ValueError`(models.Generator 값만 허용).
- **대표번호(15xx·16xx·18xx)와 7~8자리 번호는 단서가 있을 때만 가린다.** 단서 없는 `1588-1234`는 남는다(연도 범위 `1600-1700` 오탐과 맞바꿈). 영문자에 바로 붙은 번호(`Tel010-…`)도 경계 가드 때문에 남는다.
- **URL·DOI 안의 숫자열은 전화번호로 보지 않는다.** 이메일·ORCID는 URL 안이어도 가린다(`models.redact_pii`와 같은 동작).
- 커밋 메시지는 저장소 관례(끝줄 `verify 통과` / `builder: claude-opus-5.5`)를 따랐다.

## 못 한 것

- 파이프라인 연결(E3-L0 `run_premortem`에서 부르기, 무관 입력 시 단계 건너뛰기)은 E3-L0 소유라 하지 않았다. 위 "권장 연결"대로 붙이면 된다.
- `llm.py`의 task 기본값(`TASK_DEFAULTS`)에 `fitness`(effort low, timeout 약 30s)를 넣는 것은 E3-L0 몫이다. 실측 지연은 4.7~7.4초(effort low).
- 화면 표시(`notice`·`followup_questions`)는 E4 몫이다.
- 이름·주소 같은 비정형 개인정보는 다루지 않는다(스펙 범위 밖: 전화·주민번호·이메일·ORCID).

## 다음 과제에 넘길 것 / 제안

- E3-L0: `PlanDocument.from_text` 대신 `plan_document_from_text`를 쓰면 전화·주민번호가 저장·로그·LLM 입력 전에 가려진다. 무관 입력이면 검색 전에 멈춰 "카드 0장 + 사유"를 `fit["notice"]`로 채운다(계획서 §3 L0 완료 기준 7).
- E4: `plan_checks.fitness.verdict`가 `unfit`이면 결과 화면 대신 사유를, `uncertain`이면 상단 안내와 보완 질문을 보여 준다. `generator`·`status`로 비상 경로 표기.
- E4-L2a(내보내기 ZIP)·E1 수집기: 내보내는 문자열·수집 본문에 `mask_pii`를 한 번 더 걸 수 있다(멱등).
- 계약 제안(PM): `PremortemResult`에 `fitness` 칸을 따로 두면 `plan_checks` 자유 칸보다 명확하다(지금은 `plan_checks["fitness"]`로 우회).
