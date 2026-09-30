# E3-L1w — v1 연결: 파이프라인에 적합성·예상 심사평·체크리스트·2차 검증 + 검색어 안정화

- 빌더 Opus 5.5 · 검증 Sonnet 5.5 · 목표 50분 · 소유: `src/neumann/pipeline.py`, `src/neumann/llm.py`, `src/neumann/analyze/`(연결에 필요한 최소 수정), `tests/e3/test_pipeline_l1*.py`
- **커밋은 기능 단위로 여러 번**(한 커밋 수백 줄 이내)

## 연결할 것 (모두 main에 있음, E3-L1c만 곧 들어옴 — 없으면 그 단계는 건너뛰고 status에 기록)
1. 적합성(E3-L1c `assess_fitness`, `fitness_stage`): 검색 전에. `analyze=False`면 카드 0장·사유로 끝(지금의 조리법 처리를 대체하되 결과는 같아야 함)
2. 예상 심사평(E3-L1a `attach_expected_review(result, provider_llm_call(llm))`)
3. 체크리스트·2차 검증(E3-L1b `attach_checklist`, `attach_validation` — 이 순서)
4. 생성 주체는 추정 금지: llm 어댑터가 `generator` 속성을 단다(openai→astra, mock→mock, off→rule)
5. 검색어 안정화: 같은 계획서(plan_id)는 astra 검색어를 캐시해 같은 유사 연구가 나오게(`data/cache/`), 캐시 적중 여부를 결과에
6. 단계별 시간 상한과 전체 소요 시간 기록 유지. 강등은 status에
## 완료 기준
1. mock으로 전 단계 테스트(적합성 부적합 → 0장, 각 단계 실패 시 그 단계만 강등)
2. 실서버와 같은 조건(`NEUMANN_LIVE_TESTS=1`)으로 데모 plan.md 1회: 카드·예상 심사평·체크리스트·검증 결과가 결과에 있고 `eval.linkage.check_result` 통과, 두 번째 실행에서 같은 유사 연구(캐시)
3. `python scripts/verify.py` 통과
