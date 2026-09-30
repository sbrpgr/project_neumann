# E5-L3b 검증 요약 — PASS-조건부

- 대상 커밋: `849cdaa` (브랜치 `task/E5-L3b`)
- 판정: **PASS-조건부.** 병합 전에 문서 정정 2건이 필요하다(아래 발견 1·2).
- 기록 방식: 검증자 결과를 코디네이터가 전달했고, 빌더(claude-opus-5.5)가 그 내용대로 이 파일에 옮겨 적었다. 검증자 원문 로그는 받지 않았다. 아래 근거는 전달문에 있는 항목만 적는다.

## 근거

| 항목 | 검증 결과 |
|---|---|
| 숫자 재계산 | 일치(카드·요약의 Macro-F1·구간·n, 연결·폐기·시연 개수) |
| 평가 모델 gpt-6-astra와 제품 모델 gpt-6.1-sol 구분 | 통과 |
| PM 결정 반영(P2·P6 측정 전, 43/43·3/3은 참고 행, 백테스트 n=5 문구, `e2e_cards` 이름표) | 통과 |
| 변이 검사 | 12종 모두 테스트가 잡음 |
| `python scripts/verify.py` | 1202 passed(통과) |

## 발견 5개

| # | 내용 | 구분 | 빌더 조치(이 파일 커밋 기준) |
|---|---|---|---|
| 1 | 보고서 결정 5와 "다음 과제"가 틀렸다. task/E5-L1e2e는 요약 형식이 이미 있지만(`plans[*].models.llm_model`·`card_models`·`stage_impl`, `linkage`에 summary·verdict·linkage_rate·links·cards·reason_counts·contract_valid·drop) **`linkage.card_generators`는 기록하지 않는다.** 그래서 그대로 v1 라이브를 돌리면 P2·P6은 "측정 전(참고)"으로 남는다. E5-L1e2e 쪽에 한 줄 추가가 필요하다(그쪽 빌더에게 요청됨) | 필수(문서) | 정정했다. 그쪽 커밋 요약을 파일로만 읽어 변환해 참고 행으로 남는 것을 확인했다. 변환기가 generator:model 키도 받게 해서, 그쪽이 기존 `card_generators()` 값으로 한 줄을 채워도 된다(`f936a09`) |
| 2 | 요약의 "기준: main `88f1b51`"은 분기점이라는 것을 명시하라 | 필수(문서) | 요약 머리와 보고서 머리에 "분기점, 지금 main 최신 아님"을 적었다 |
| 3 | 변환기: 요약에 `models.llm_model`이 있으면 `--model`과 대조해 다르면 종료 코드 2. 없으면 조건 칸에 "모델은 명령행 값(요약에 기록 없음)" | 선택 | 반영(`9fbf231`) |
| 4 | 카드 2절 P1 행에 "(gpt-6-astra)" 표기 | 선택 | 반영. score JSON에 모델이 없어 `eval.report_card`에 `--eval-model` 선택 옵션을 두었다(`cfd947e`). 카드 재생성은 `f9ded04` |
| 5 | P6을 "화면 흐름 통과"와 "연결 검사"로 나누는 안 | 제안만 | 보고서 "제안: P6 분리"에 적었다. 구현하지 않았다 |

## 재검증할 곳

- 새 커밋: `9fbf231` · `cfd947e` · `f9ded04` · `f936a09` · 이 파일과 문서를 담은 커밋.
- 필수 1·2는 문서만 바뀌었다(`docs/reports/E5-L3b.md` 결정 5·다음 과제, `docs/reports/metrics_summary.md` 머리).
- 선택 3·4는 코드가 바뀌었다. 테스트는 `tests/e5/test_metrics_from_e2e.py` 30개(E5-L3a 카드 테스트 31개와 합쳐 61 passed). 변이 6종을 더 검사했다.
- 판정은 그대로다. 카드는 미달 1(P1) → 측정 전 5(P2~P6) → 달성 0. 커밋된 변환 결과 `E5-L3b_metrics_e2e.json`은 `f9ded04` 이후 바이트 동일이다.
