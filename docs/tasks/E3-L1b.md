# E3-L1b — 예방 체크리스트(astra) + 2차 의미검증

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 50분
- 소유: `src/neumann/analyze/checklist.py`, `src/neumann/analyze/validate.py`, `tests/e3/test_checklist*.py`, `tests/e3/test_validate*.py`

## 읽을 것
- 계획서 §2 ACTION, §3 L2 "분석"(체크리스트·결정 로그), §4 E3 불변식(카드와 행동은 따로 검증, 카드를 기각해도 타당한 행동은 남긴다)
- `02_LLM_호출_명세.md` GEN-1(뒷단 합성: 계획서 줄 연결 체크리스트), GEN-2(2차 의미검증)
- 목업 `checklist` 구조, `src/neumann/models.py`

## 만들 것
1. `analyze/checklist.py`: `build_checklist(result, plan: PlanDocument, llm_call) -> list[dict]` — 카드마다 예방 행동 1~3개, 각 행동은 계획서 **줄 번호**에 연결, 근거 카드 id. 채택·보류·기각 기록 자리(decision_log). `llm_call` 주입 방식은 E3-L1a와 같다(`llm_call(schema, instructions, input, *, effort) -> dict | None`)
2. `analyze/validate.py`: 2차 의미검증 — 카드의 "이 계획서에 해당하는 이유"가 인용된 계획서 줄과 실제로 맞는지 astra로 판정(맞음/약함/틀림), 틀림 카드는 결과에 표시(삭제하지 않고 강등 표시)
3. 실패 시 규칙 경로(카드 유형별 기본 행동 문구)와 `generator` 표기
## 완료 기준
1. 가짜 callable 테스트: 없는 줄 번호 참조 제거, 카드 기각 시 행동 유지, 실패 시 규칙 표기
2. 실제 astra 1회 예시(`NEUMANN_LIVE_TESTS=1` 테스트)
3. `python scripts/verify.py` 통과
