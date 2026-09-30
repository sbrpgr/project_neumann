# E5-L2e — 정답 없는 블라인드 쌍비교 판정(RFP 추가 실험용)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5
- 목표 시간: 60분
- 소유: `eval/judge_pairwise.py`(새 파일). `eval/judge_envelope.py`는 블라인드 함수를 재사용만 하고 수정하면 테스트를 추가한다. 그 밖에 `tests/e5/test_judge_pairwise*.py`, 보고서
- **실제 OpenAI 호출 금지(mock).** 판정자는 Claude 구독 서브에이전트(PM이 띄움)

## 배경

- 사전 기록: `docs/decisions.md` 2026-09-30 23:4x "추가 실험 RFP".
- RFP에는 실제 심사평 정답이 없다. 그래서 같은 RFP에 대한 Neumann과 일반 LLM(둘 다 gpt-6.1-sol)의 위험 묶음을 판정자에게 나란히 보여 주고 어느 쪽이 나은지 고르게 한다.

## 만들 것

1. **봉투.** RFP 하나당 봉투 하나를 만든다.
   - 내용: RFP 본문과 위험 묶음 두 개("왼쪽", "오른쪽"). 좌우 배치는 시드 고정 무작위이고, 짝 표는 별도 폴더에 둔다.
   - 위험 문장은 E5-L2c의 `normalize_risk_text`(앞머리 조사, 근거 출처 문장 제거)를 통과시키고 `blind_violations`를 검사한다.
   - 한쪽이 0장(관문 거절 포함)이면 봉투에 "이 쪽은 위험을 내지 않았다(사유: 관문 거절/카드 0장)"를 적고, 판정은 그대로 한다.
2. **루브릭.** 기준 세 가지(구체성, 타당성, 실행 가능성)마다 "왼쪽 / 오른쪽 / 비슷함"과 한 줄 이유를 적는다. 답 스키마 검사(`validate`)를 둔다.
3. **집계.**
   - 기준마다 3명 다수결을 낸다. 모두 다르면 "비슷함"으로 본다.
   - 짝 표로 시스템 이름을 복원한다.
   - 주 지표: Neumann 합산 승률(비슷함 제외)과 부트스트랩 95% 구간.
   - 보조 지표: 기준별 승률, 판정자 일치율, 근거 연결률·카드 수·관문 통과(입력 묶음에서 옮김).
   - 결과 md와 json을 만들고, 맨 위에 "추가 실험·n 작음·통계적 결론 없음·판정자는 LLM"을 적는다.
4. **CLI.** `python -m eval.judge_pairwise build|briefs|validate|aggregate --judge-dir <폴더> --left-right-seed …`. 지시문(briefs)은 판정자 J1~J3 각자에게 자기 봉투 목록과 답 경로만 준다.
5. **테스트.**
   - 가짜 위험 묶음 2개와 가짜 답 3세트로 build → validate → aggregate를 확인한다.
   - 좌우 무작위와 짝 표 복원을 확인한다.
   - 블라인드 위반(조사, 근거 출처 문장, 시스템 이름)을 잡는지 확인한다.
   - 0장 쪽 처리를 확인한다.

## 완료 기준

1. `pytest tests/e5 -q` 통과
2. mock 위험 묶음으로 예행한 결과 표를 보고서에 넣는다("예행, 결과 아님")
3. `python scripts/verify.py` 통과(venv 파이썬, `NEUMANN_LLM_PROVIDER=mock`)
