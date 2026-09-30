# E3-L1c — 입력 적합성 판정·무관 입력 차단·개인정보 마스킹 강화

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 45분
- 소유: `src/neumann/analyze/fitness.py`, `src/neumann/analyze/pii.py`, `tests/e3/test_fitness*.py`, `tests/e3/test_pii*.py`

## 읽을 것
- 계획서 §2 INPUT, §3 L0 완료 기준 7(음성 대조), §3 L2 분석, §4 E3 L3
- `06_교훈_함정.md`의 PII 전화번호 교훈(형식 열거가 아니라 숫자열 기반 탐지 + 유니코드 숫자 + 경계 가드)
- `src/neumann/models.py`(redact_pii, PlanDocument)

## 만들 것
1. `analyze/fitness.py`: `assess_fitness(plan: PlanDocument, llm_call) -> dict` — 연구계획서인지(연구 질문·방법·데이터·평가 요소), 분야, 한국어/영어, 판정 사유. astra 판정(`llm_call` 주입, E3-L1a와 같은 방식) + 실패 시 규칙(키워드·길이) 비상 판정. 무관 입력(조리법 등)이면 "분석하지 않음"과 사유
2. `analyze/pii.py`: 전화번호(국내·국제, 구분자 변형, 유니코드 숫자), 주민번호 형태, 이메일·ORCID(models의 것 재사용)를 마스킹. 오탐 방지(연도, 지표 수치, DOI, 오프셋 번호)
## 완료 기준
1. 테스트: 전화번호 변형 10종 이상 마스킹, 오탐 사례(2024, 0.95, 10.1234/abc, R2.3) 보존, 조리법 입력 → 부적합, 데모 계획서 3건 → 적합
2. 실제 astra 1회 예시(`NEUMANN_LIVE_TESTS=1`)
3. `python scripts/verify.py` 통과
