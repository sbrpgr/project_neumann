# E5-L1b — DISAPERE 골드에 astra 지적 추출 → Macro-F1 (RQ: 구성 요소 타당성)
- 빌더 Opus 5.5 · 검증 Sonnet 5.5 · 목표 50분 · 소유: `eval/disapere_extract*.py`, `tests/e5/test_disapere_extract*.py`
## 근거
계획서 §3 L1 평가, `04_평가_명세` §0.6(튜닝은 dev 358건만, 골드 148건은 채점에만), `docs/reports/E5-L1a.md`(예측 JSONL 형식), E3-L0의 astra 추출기(브랜치 `task/E3-L0` — main에 아직 없으면 그 브랜치를 자기 브랜치에 병합해서 쓴다. 곧 main에 들어온다)
## 만들 것
1. DISAPERE 리뷰 문장을 E3 추출기(EX-4 계약)에 넣어 리뷰 단위 risk_code 집합 예측 → `data/eval/pred_astra_*.jsonl`(generator=astra), 비상 규칙 태거(`neumann.index.taxonomy`) 예측 → `pred_rule_*.jsonl`
2. dev 358건에서만 지시문·임계값 조정(골드 금지, 조정 이력 기록), 조정 고정 후 골드 148건 1회 채점: `python -m eval.macro_f1`
3. 보고: astra·규칙·빈도 기준선(0.3308)·사람 상한(0.725) 나란히, n·95% 구간
## 완료 기준
골드 채점 결과 JSON(`data/eval/score_astra.json`, `score_rule.json`), dev 튜닝과 골드 채점의 커밋 순서(골드 채점은 마지막 1회), `python scripts/verify.py` 통과
