# E5-L3b 보고서 (코디네이터 지시로 짧게 마감, builder claude-opus-5.5)

- 된 것: `scripts/metrics_from_e2e.py`(라이브 E2E 요약 → neumann.metrics/1, `--model gpt-6-astra --product-model gpt-6.1-sol`, 샘플 모드·개수 불일치는 종료 코드 2로 거부, LF 고정) + `tests/e5/test_metrics_from_e2e.py` 17개. `docs/reports/E5-L3b_metrics_e2e.json`(변환 결과), `docs/reports/report_card.md` 재생성(astra·rule·빈도 기준선 score JSON 3개 + 변환 지표), `docs/reports/metrics_summary.md`(발표 12쪽·README용 숫자와 출처 파일 표).
- 카드 결과: 미달 1건(P1 Macro-F1 0.4864 [0.4276, 0.5394] n=148), 측정 전 3건(P3·P4·P5), 달성 2건(P2 근거 연결률 43/43, 폐기율 7/2033=0.0034 병기 · P6 시연 3/3). 제품 기본 모델 gpt-6.1-sol 행은 전부 측정 전.
- 결정: 연결 검사 실행(/premortem 재실행)의 카드 generator가 요약에 기록되지 않았다. 그래도 P2는 Neumann 칸에 넣었다. 대신 약속 칸과 한계 칸에 "검사 실행 카드 generator 미기록"을 적었다. 근거로 화면 실행 카드는 astra 13/13이고 강등 단계는 0개였다. 리포트 카드의 linkage 경로였다면 이 값을 unknown_generator로 보냈을 것이다. PM 판단이 필요하다.
- 테스트 상태: `python scripts/verify.py` 통과(1193 passed, 27 skipped). OpenAI 호출 0회(파일만 읽음, NEUMANN_LLM_PROVIDER=mock).
- 남은 것·제안: (E5 eval) `METRIC_LABELS`에 `e2e_cards` 이름을 추가하고, 한계 문구 "백테스트 n=30"을 15편 축소 규칙에 맞게 고칠 것. 모델 칸도 있으면 좋다. (E5 tests/e2e) 연결 요약에 `card_generators`를 기록할 것. 검증자 재측정은 아직 하지 않았다.
