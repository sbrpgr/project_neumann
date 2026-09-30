# E3-L1a — 예상 심사평(astra) + 근거 게이트

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 50분
- 소유: `src/neumann/analyze/review.py`, `src/neumann/analyze/gate.py`, `tests/e3/test_review*.py`, `tests/e3/test_gate*.py` (다른 analyze 파일·llm.py·pipeline.py는 E3-L0 몫, 건드리지 않는다)

## 읽을 것
- 계획서 §2 REVIEW, §3 L1 "위험점수 식과 예상 심사평", §4 E3(불변식: LLM은 인용문을 쓰지 않는다, 근거 없는 문장은 그 문장만 뺀다)
- `02_LLM_호출_명세.md` GEN-1·GEN-3, verify/groundedness 설명
- `부록/목업/web/index.html`의 `review`(strength·weakness·request·audit) 구조
- `src/neumann/models.py`(RiskCard, Excerpt, PremortemResult의 expected_review 자리)

## 만들 것
1. `analyze/review.py`: `generate_expected_review(result: PremortemResult, llm_call) -> ExpectedReview dict`. `llm_call(schema: dict, instructions: str, input: str, *, effort: str) -> dict | None`을 **주입**받는다(E3-L0의 llm.py가 main에 들어오면 그걸 넘긴다. 없으면 테스트는 가짜 callable). 모델은 문장마다 근거 **카드 id·excerpt id**만 달고, 인용 문자열은 쓰지 않는다. 목업 `review` 구조(강점·약점·요청·감사)에 맞춘다
2. `analyze/gate.py`: 예상 심사평 문장마다 근거 id가 결과 안에 실제로 있는지, 따옴표 인용이 있으면 근거 원문과 글자 그대로(또는 20자 이상 연속 부분문자열)인지 검사. 실패 문장만 버리고 폐기 수·사유를 남긴다
3. llm_call이 None(실패·시간 초과)이면 규칙 합성(카드 제목·근거로 문장 조립)으로 대신하고 `generator="rule"`로 표기
## 완료 기준
1. 가짜 callable로 테스트: 근거 없는 문장 제거, 없는 id 참조 제거, 인용 불일치 제거, 실패 시 규칙 합성 표기
2. fixture 결과 + 실제 astra로 1회 생성 예시를 보고서에(openai SDK를 직접 부르는 임시 llm_call 허용, `NEUMANN_LIVE_TESTS=1`일 때만 도는 테스트로)
3. `python scripts/verify.py` 통과
