# E5-L3a — 리포트 카드 생성기 (앞당김)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 45분
- 소유: `eval/report_card.py`, `tests/e5/test_report_card*.py`
## 읽을 것
계획서 §4 E5 L3, `부록/평가/report_card_template.md`, `04_평가_명세.md` §1.2·§2·§6·§7(정직 표기), `eval/macro_f1.py` 출력 형식, `docs/tasks/E5-L2a.md`(백테스트 지표 형식)
## 만들 것
`python -m eval.report_card --inputs <지표 JSON들> --out docs/reports/report_card.md`: 지표마다 값·n·95% 구간·조건·한계를 한 장에. 참조선(사람 상한 0.725, 빈도 기준선) 먼저, 목표 대비 미달이면 먼저 적음, 골드 없는 클래스 제외 목록, R7 매핑 한계 각주, 신청서 대비 골드 대체 각주. 없는 지표는 "측정 전"으로(추정·지어내기 금지)
## 완료 기준
가짜 지표 입력으로 생성 테스트(값이 그대로 옮겨지는지, 없는 지표 표시), 지금 있는 실제 지표(`data/eval/score_baseline_freq.json`)로 1회 생성, `python scripts/verify.py` 통과
