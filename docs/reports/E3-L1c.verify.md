# E3-L1c 검증 보고서 — 입력 적합성 판정·개인정보 마스킹

- 검증자: Claude Sonnet 5.5 · 대상: 브랜치 `task/E3-L1c`(worktree `.claude/worktrees/agent-a421bb258ca164d24`, 커밋 bde6e91) · 검증일 2026-09-30
- 환경: `_COMMON.md` 환경변수(PYTHONPATH `src;.`), Python `~/.venvs/neumann`. 코드·git 쓰기 없음. 내 시험 스크립트는 세션 scratchpad에만 두었고 worktree에는 파일을 남기지 않았다(`.pytest_cache` 삭제, `git status` 깨끗).

## 최종 판정: **PASS-조건부** (병합 전 고칠 것 2개)

핵심 기능은 실제로 동작한다. 전화번호 마스킹·오탐 보존·조리법 부적합·짧은 초록 비거절·강등 표기·실제 astra 판정이 모두 재현됐고, 변이 시험 18건이 전부 테스트에 잡혔다. 다만 (1) `generator` 기본값이 `astra`라서 속성 없는 callable이 astra로 표기되고(E3-L1a에서 병합 전 수정 대상이던 것과 같은 결함), (2) 한 줄에 숫자가 수백 개 이어지면 `mask_pii`가 수십 초 걸린다.

## 병합 전 고칠 것

1. **`assess_fitness`가 `generator` 기본값으로 `astra`, `model`은 `gpt-6-astra`를 적는다.** 어떤 callable을 넘기든(가짜·mock 포함) `generator="astra", status="ok"`가 된다. 재현: 아무 가짜 `llm_call`을 넣고 `assess_fitness(plan, fake)` → `generator=astra model=gpt-6-astra status=ok decided_by=llm`(내 시험 3의 "모델 reject / 조리법" 등 전부). main의 `analyze/review.py::_resolve_generator`(E3-L1a 정정)처럼 인자 `generator=` 또는 `llm_call.generator` 속성이 있을 때만 값을 쓰고, 둘 다 없으면 `ValueError`(또는 `mock`+"unspecified" 표기)로 바꿔야 한다. 새 테스트는 인자 없이 bare callable을 넣어 astra가 아님을 확인해야 한다(지금 테스트는 `generator="mock"`을 직접 넘기는 것만 본다). 보고서 "결정"에 호출부가 넘겨야 한다고 적혀 있지만, 안 넘기면 조용히 astra가 되는 기본값이 문제다.
2. **`pii.find_phones` 시간이 숫자 덩어리 사슬 길이의 3제곱이다.** 줄 하나에 공백·점으로 이어진 숫자가 많으면 멈춘 것처럼 보인다. 측정: 공백으로 이은 숫자 200개 0.54s, 400개 3.98s, 800개(3.9KB) **33.2s**, `"0.1 " * 400`은 9.0s, 숫자 3000개는 300초 안에 끝나지 않았다. 원인: `find_phones`가 시작점 i마다 j를 사슬 끝에서부터 줄이며 `_phone_span`을 부르고, 그 안에서 묶음·구분자 목록을 매번 다시 만든다. 전화번호 사슬은 실제로 묶음 6개 안이므로 `j - i`에 상한(예: 8묶음)을 두면 해결된다. 입력은 사용자 붙여넣기(`plan_document_from_text`가 전체 본문에 부른다)라서 표·배열을 한 줄로 붙이면 화면이 멈춘다. 줄바꿈은 사슬을 끊으므로 줄마다 숫자가 적은 본문은 영향이 없다.

## 완료 기준별 결과

| # | 기준 | 실행한 명령 | 실제 출력(핵심) | 판정 |
|---|---|---|---|---|
| 1a | pii·fitness 테스트 | `pytest tests/e3 -k "pii or fitness" -q` | `134 passed, 4 skipped in 0.53s`(4 skip = 라이브) | 통과 |
| 1b | 전화번호 변형 10종 이상 마스킹 | 내가 새로 만든 변형으로 `mask_pii` 직접 호출(아래 표) | 새 변형 **32종 중 22종 마스킹**(현실적인 표기 전부), 못 잡은 10종은 비정형이거나 설계상 제외(표기 참조) | 통과 |
| 1c | 오탐 보존 | 내가 만든 사례 30종 + 실제 코퍼스 133,769개 발췌 | 26/30 보존, 오탐 4종(아래). 실제 코퍼스 발췌 133,769건에서 전화 탐지 2건, **둘 다 오탐** | 통과(주의 있음) |
| 1d | 조리법 → 부적합 | 규칙 경로 + 라이브 astra | 자연스러운 한·영 조리법 규칙 unfit, fixture `negative_recipe.md` 라이브 astra `unfit`(`not_research_plan`) | 통과 |
| 1e | 데모 3건 → 적합 | 빌더 테스트(가짜 llm_call·규칙) + 라이브 1건 | 테스트 `test_demo_plans_fit_via_llm/rule_fallback` 통과. 내 라이브는 데모 계획서가 아니라 영어 초록 1건(fit) | 통과 |
| 2 | 실제 astra | `NEUMANN_LIVE_TESTS=1 pytest tests/e3/test_fitness_live.py -k recipe -s`(키는 참·거짓만 확인: `True`) + 내 프로브 1회 | 조리법: `unfit`, `generator=astra`, `status=ok`, 6.2s, 입력 925/출력 161 토큰, 사유는 줄 번호 인용. 영어 초록 1건: `fit`, `en`, 분야 "분자 머신러닝·물성 예측", 7.3s. 호출 2회(지시는 1회였는데 짧은 초록 과잉 거절 확인용으로 1회 더 썼다) | 통과 |
| 3 | `scripts/verify.py` | 그 브랜치에서 실행 | `360 passed, 4 skipped`, 보안 137개, 계약 2개, `verify 통과` | 통과 |

### 1b. 전화번호 변형(새로 만든 것)

마스킹됨(22): `+82 10-1234-5678`, `+821012345678`, `0082-10-1234-5678`, NBSP 구분, 탭 구분, 전각공백(U+3000) 구분, `+82.10.1234.5678`, 혼합 스크립트 숫자 `010-١٢٣٤-5678`, `(031) 1234-5678`, `010-12345678`, `Tel. 02-1234-5678 ext. 89`, `+8210-1234-5678`, 전각 `＋８２ １０ １２３４ ５６７８`, 조사 붙음 `연락처는01012345678입니다`, `+1-555-123-4567`, `문의 010 - 1234 - 5678`, `Phone:010-1234-5678,`, `(+82) 10 1234 5678`, `Tel 1588-1234`, `전화 1234-5678`, 앞뒤 줄바꿈, 슬래시로 이은 두 번호(`[PHONE]/[PHONE]`).

못 잡음(10종, 모두 비정형이거나 의도된 설계): 미국식 `(555) 123-4567`·`555-123-4567`(`+1` 없음, 단서 없음), `010/1234/5678`, `010_1234_5678`, 제로폭 공백이 낀 번호, 숫자를 한 자씩 띄운 `0 1 0 - 1 2 3 4 …`, 한글 숫자 `공일공-…`, `82-2-123-4567`(서울, `+` 없음: 숫자 10개라서 11~12개 조건에서 빠짐), 단서 없는 `1588-1234`(설계: 연도 범위 `1600-1700` 보존과 맞바꿈). 주민번호: `900101-1234567`, 구분자 없음, 공백 끼움, 가려진 뒤자리, 외국인, 전각 모두 마스킹. 월이 13인 `901301-1234567`은 보존. 성별 자리 9, `900101.1234567`·`/` 구분은 못 잡는다.

### 1c. 오탐 사례(내가 만든 30종 중 보존 26종)

보존: `p < 0.001, n = 1234`, `2019.03.05`, `v2.1.0`, `0.85 0.91 0.88`, `2018-2023`, `arXiv 2401.01234v2`, `RS-2023-00123456`, IP `100.0.0.1`, ISSN, 좌표, `01.02.2020`, `0.95 - 0.97 - 0.99`, `10:30-11:45`, `PMID 12345678`, `1,234,567`, 해시 `a0123456789b`, `0.5-0.8`, `5-fold, 10 20 30 epochs`, `8:1:1`, `[12-15]`, `3.1.2`, DOI `10.1109/5.771073`, `0.1234 0.5678 0.9012`, `2024-05-12` 등.

오탐(마스킹됨) 4종, 모두 낮은 빈도:
- `id 0001 0002 0003`, `00 1234 5678 9012`: 앞이 `00`이면 국제 접두로 보고 10~17자리를 전화로 본다(영이 앞에 붙은 일련번호·ID).
- `sample 0123456789`(0으로 시작하는 10자리 일련번호, 구분자 없음).
- `Call for papers 1600-1700`: 단서 `call`이 앞 24자 안에 있으면 대표번호 규칙(15xx·16xx·18xx)이 날짜·연도 범위 제외보다 먼저 적용된다.
- 실제 코퍼스(`data/index/excerpts.jsonl` 133,769건)에서 전화 탐지 2건: `physics/0004057 (2000)`의 `0004057 (2000`, `math-ph/0511034 (2005)`의 `0511034 (2005`(옛 arXiv 번호+연도, `[PHONE]` 태그로 바뀌고 괄호가 반쪽만 남음). 참고문헌이 많은 리뷰 인용에서 나올 수 있는 패턴이다. 이메일·ORCID·주민번호는 0건. 계획서 30건(`backtest_plans.jsonl`)은 0건.

### 적합성 판정(가짜 llm_call·규칙 경로)

| 입력 | 규칙 경로 판정 | 비고 |
|---|---|---|
| 자연스러운 한국어 조리법(된장찌개) | unfit(`분석하지 않음`) | 요소 1/4, 무관 표지 5줄 |
| 자연스러운 영어 조리법(pancakes) | unfit | 같은 사유 |
| 한국어 짧은 연구 초록(59자) | fit | 요소 3/4 |
| 영어 짧은 초록 2문장 | fit, `en` | 요소 3/4 |
| 영어 한 문장 연구 아이디어 | uncertain(거절하지 않음) | 요소 1/4 |
| 영어 연구계획서(Aims·Data·Methods·Evaluation) | fit, `en` | 요소 4/4 |
| "고양이 사진 분류 AI" 빈약 아이디어 | uncertain(거절하지 않음) | 요소 2/4 |
| 영어 짧은 계획(가설·60명·t-test) | uncertain(거절하지 않음) | |
| 6자 "AI 연구 계획" | unfit, `decided_by=precheck`, `status=ok`, 호출 없음 | 40자 미만 사전 판정 |
| 무의미 lorem, 광고 | unfit | |
| 연구 어휘를 흉내 낸 적대적 입력(조리법에 Goal·Data·Method·Evaluate 제목, 연구실 일기, 한글 주석 붙은 코드) | fit로 나옴 | **규칙 경로만**의 한계. 라이브 astra는 자연 조리법을 부적합으로 판정했다 |

### 모델 판정 뒤집기·강등 표기(가짜 llm_call)

- 모델 `not_research_plan` + 규칙 fit(진짜 계획서): 최종 `uncertain`(분석 진행), `checks.overrides`에 "모델은 연구계획서가 아니라고 봤지만 규칙 신호(연구 요소 4/4)가 강해 거절하지 않는다", `model_verdict=not_research_plan`로 원 판정 보존. 기록됨.
- 모델 `research_plan` + 근거 줄 있는 요소 1개: `uncertain`, `overrides`에 사유. 기록됨.
- 모델 `not_research_plan` + 조리법: `unfit` 유지, `overrides` 없음.
- `llm_call` 예외(예외 메시지에 `sk-…` 문자열을 넣어 시험): `generator=rule`, `model=None`, `status=degraded`, `decided_by=rule_fallback`, `degraded_reason=llm_exception: RuntimeError`. 예외 메시지·키 문자열은 결과에 새지 않음. `None` 반환·깨진 JSON·enum 밖 판정 모두 같은 방식으로 `generator=rule`, `status=degraded`, 사유 기록. `fitness_stage`는 `state=degraded`, `impl=fallback:rule_fitness`.
- 환각 줄 번호(999, -1): 버리고 `checks.dropped_lines=2`. 근거 줄 없는 "있음"은 인정하지 않음.
- 개인정보: 모델 입력에 전화·이메일·주민번호가 `[PHONE]`·`[EMAIL]`·`[RRN]`으로 바뀐 채 들어가고, 모델이 사유·분야에 전화·이메일을 써도 마스킹된다.
- 잘못된 `generator="gpt"`는 `ValueError`.

## 계약 위반·범위 확인

- `git diff main...task/E3-L1c --name-status`: 추가 6개뿐. `docs/reports/E3-L1c.md`, `src/neumann/analyze/{fitness,pii}.py`, `tests/e3/{test_fitness,test_fitness_live,test_pii}.py`. 소유 경로 밖 변경 없음, `contracts/`·`models.py` 변경 없음, 데이터·비밀값 파일 추가 없음, diff에서 키 형태 문자열 검색 0건.
- main과 파일명 충돌 없음(main에는 `checklist/gate/review/validate`만 있음). 분기점은 ed1d1a0이고 main이 앞서 있으니 병합 뒤 `verify.py`를 한 번 더 돌려야 한다.
- `models.EMAIL_RE`·`ORCID_RE`를 그대로 재사용한다(재정의 없음).

## 정직성·테스트 실효성

- 변이 시험 18건(worktree 복사본을 scratchpad에서 고쳐 `pytest tests/e3 -k "pii or fitness"` 실행): 강등을 astra로 표기, 강등 status ok, override 기록 삭제, 모델 reject 뒤집기 삭제, 전화 탐지 끔, 경계 가드 끔, 유니코드 숫자 끔, 줄 번호 검증 끔, 모델 입력 재마스킹 끔, 규칙 fit 기준 완화, DOI·URL 보호 끔, 점 구분자 규칙 끔, 단서 없이 대표번호 마스킹, 근거 없는 present 인정, 사유·분야 마스킹 끔, 짧은 입력 사전 판정 끔, 주민번호 월·일 검증 끔, 이메일 재사용 끔. **18건 모두 실패로 잡혔다**(항상 통과하는 테스트가 아니다).
- 인용: 이 과제는 인용을 만들지 않는다(줄 번호만 다룬다). 모델 사유가 인용 대신 줄 번호를 쓰는 것을 라이브 출력에서 확인.
- 규칙 결과는 `generator=rule`로 표기되고 LLM 결과로 표시되지 않는다(위 고칠 것 1의 기본값 문제만 예외).

## 병합 뒤에 다룰 것(권고, 조건 아님)

- 강등이 아니라 규칙이 모델 판정을 뒤집은 경우, `fitness_stage`의 `detail`이 "uncertain by astra"로만 남는다. override 사실은 `plan_checks.fitness.checks.overrides`에만 있고 단계 기록에는 없다. 단계 `detail`이나 `counts`에 override 건수를 넣으면 화면 표시가 정직해진다. 이때 `reason`은 모델의 "연구계획서가 아니다" 문장 그대로라서 `notice`(uncertain 문구)와 어긋나 읽힌다.
- 뒤집기는 한 방향이다. 모델이 조리법을 `research_plan`으로 잘못 판정하면(가짜 응답으로 시험) 규칙이 unfit이어도 fit이 된다. 실제 astra는 조리법을 정확히 거절했으므로 실사용 문제는 아니지만, 설계 결정으로 남겨 둘 만하다.
- E4 화면(`webui/index.html normFit`)은 `is_research_plan`이 boolean일 때만 판정을 읽는다. `uncertain`은 `is_research_plan=None`이라 "결과 해석 불가"로 뜬다. 연결 시 `verdict`·`analyze`를 읽도록 맞춰야 한다(E4/PM).
- 오탐 완화: 옛 arXiv 번호(`[a-z-]+/\d{7}`)와 `\d{7}\s*\(\d{4}\)` 패턴을 보호 구간에 넣고, `00`으로 시작하는 국제 접두 규칙은 `+`·`00` 뒤 국가번호가 유효할 때만 인정하면 위 오탐 대부분이 사라진다. 대표번호 규칙은 날짜·증가 연도 범위 검사 뒤에 두면 `Call for papers 1600-1700` 유형이 사라진다.
- `82-2-123-4567`(국가번호 82, 서울, `+` 없음)은 숫자 10개라 놓친다. 필요하면 82 뒤 9~10자리로 넓힌다.
- 사용자에게 보이는 지연: 라이브 4.7~7.4초(빌더 측정)와 내 측정 6.2·7.3초로 일치.
