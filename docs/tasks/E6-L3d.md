# E6-L3d — v1 라이브 결과를 사전 계산본·정적 판·시연 녹화에 쓴다(추가 API 없음)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5
- 목표 시간: 45분
- 소유: `scripts/precompute_demo*`, `scripts/build_static_site*`, `scripts/record_demo*`, `tests/e6/`, 보고서
- **실제 OpenAI 호출 금지.** 새 분석을 돌리지 않는다. 결과는 E5-L1e2e가 8020(gpt-6.1-sol)에서 얻은 라이브 결과만 쓴다.

## 배경

- 정적 판(`build_static_site`)과 `data/precomputed`의 `DEMO_PLANS`에 아직 옛 fMRI·의료영상 예시가 남아 있다.
- 대표 지시로 입력 예시는 AI4S 3건으로 바뀌었다(E4-L1e): 전해액 GNN(`tests/fixtures/plans/plan.md`), 단백질-리간드 결합 친화도, 신경 연산자 대기 유체.
- E5-L1e2e(`--plans ai4s`)가 이 세 건과 범위 밖 입력 1건을 8020에서 한 번 돌린다.

## 만들 것

1. **가져오기.** `precompute_demo`에 E5-L1e2e 라이브 결과 JSON(PremortemResult)을 가져오는 모드(예: `--from-results <폴더>`)를 추가한다.
   - 각 결과의 `manifest.llm_provider`·`llm_model`(gpt-6.1-sol)과 생성 시각을 그대로 남긴다.
   - 사전 계산본 manifest에 `source: live_e2e`, 실행 커밋, 8020이었다는 표시를 적는다.
   - 결과가 mock·rule이면 그 표기를 그대로 둔다. 숨기지 않는다.
2. **DEMO_PLANS 교체.** AI4S 3건과 범위 밖 1건으로 바꾼다. 옛 fMRI·의료영상은 뺀다(대표 지시).
3. **정적 판 재생성.** 화면에 "사전 계산본(라이브 서버, gpt-6.1-sol, <시각>)" 배지가 보이게 한다.
4. **시연 녹화.** 시연 녹화 스크립트의 예시 선택을 새 예시로 바꾼다. 녹화 자체는 PM 지시 뒤 07:30에 한다.
5. **테스트.**
   - 라이브 결과 fixture는 가짜 결과를 만들어 쓴다(실제 결과 파일을 저장소에 넣지 않음).
   - 가져오기가 모델 표기와 생성 방식을 보존하는지 확인한다.
   - DEMO_PLANS에 옛 예시가 없는지 확인한다.
   - 정적 판 검사가 통과하는지 확인한다.

## 완료 기준

1. `pytest tests/e6 -q` 통과
2. E5-L1e2e 결과가 있으면 그것으로, 없으면 가짜 결과로 정적 판을 만든다. 배지와 예시 3건 스크린샷을 보고서에 넣는다.
3. `python scripts/verify.py` 통과(venv 파이썬, `NEUMANN_LLM_PROVIDER=mock`)
