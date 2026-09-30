# 확정 지표 한 장 요약 (발표 12쪽·README용)

- 기준: 2026-09-30 21시 main `88f1b51` + E5-L3b. 원본 카드 `docs/reports/report_card.md`
- **평가 모델 `gpt-6-astra`, 제품 기본 모델 `gpt-6.1-sol`.** 아래 Neumann 수치는 모두 `gpt-6-astra`로 쟀다. sol로는 다시 재지 않았다. 사유는 비용이다(`docs/decisions.md` 19:38·19:42). 표에서 `Neumann (astra)`의 astra는 평가 모델 이름이다.
- 순서는 미달, 측정 전, 달성이다. 값은 출처 파일의 숫자를 그대로 옮겼다.

## 1. 참조선 (먼저 말한다)

| 참조선 | 값 [95% 구간] | n | 출처 |
|---|---|---|---|
| 사람 간 일치 상한, Macro-F1 (DISAPERE 외부 실측, 우리 성능 아님) | 0.725 [0.669, 0.772] | 29리뷰(LOO) | `eval/macro_f1.py` `REFERENCE_LINES`, 04_평가_명세 §1.2 |
| 빈도 기준선(안 읽음), Macro-F1 | 0.3308 [0.298, 0.3623] | 148 | `data/eval/score_baseline_freq.json` (sha256 `e9b7e44c…`) |
| 빈도 기준선(안 읽음), Micro-F1 | 0.5379 [0.4871, 0.5861] | 148 | 같은 파일 |

## 2. 신청서 약속 대비

| 판정 | 약속 | 목표 | 측정값 | n·구간 | 출처 파일 |
|---|---|---|---|---|---|
| **미달** | P1 지적 추출 Macro-F1 | ≥ 0.70 | **0.4864** | n=148, [0.4276, 0.5394] | `data/eval/score_astra.json` (sha256 `c409bed9…`), `docs/reports/E5-L1b.md` |
| 측정 전 | P3 백테스트 Top-3 적중(hit@3) | ≥ 0.50 | 측정 전 | — | 지표 파일 없음. Neumann 생성은 실제 호출 동결로 보류(decisions 19:42) |
| 측정 전 | P4 표본 연결 | ≥ 300편 | 측정 전 | — | 지표 파일 없음 |
| 측정 전 | P5 원문 링크 | 100% | 측정 전 | — | 지표 파일 없음 |
| 달성(폐기율 병기) | P2 근거 연결률 | 100% | **1.0 = 43/43** (plan.md 10/10 · plan_elife_neuro.md 13/13 · plan_medimaging.md 20/20) | 전수, 구간 없음 | `docs/reports/E5-L0e2e_live_summary.json` → `docs/reports/E5-L3b_metrics_e2e.json` |
| 달성 | P6 대표 계획 end-to-end 시연 | 3건 | **3/3** (리포트 화면까지) | 1회 실행 | 같은 파일, 커밋 `b671d0e` |

## 3. 같이 적을 숫자

| 지표 | 값 | 출처 |
|---|---|---|
| 폐기율(검증 단계에서 버린 지적) | **7/2033 = 0.0034** (1/643 · 2/701 · 4/689) | `E5-L0e2e_live_summary.json` 각 계획서 `linkage.summary` |
| 카드 통과율(모든 근거가 연결된 카드) | 12/12 = 1.0 (3/3 · 4/4 · 5/5) | 같은 파일 `linkage.cards` |
| 화면에 나온 위험카드 수 | 13장 (5 · 3 · 5), 화면 카드 generator astra 13/13, 강등 단계 0 | 같은 파일 `n_cards`·`generators`·`stages_not_ok` |
| 범위 밖 입력(요리 메모) | 카드 0장, 사유 표시, 4.433초 | 같은 파일 `negative_recipe.md` |
| 화면 전체 소요(클릭 → 리포트) | 69.645초 · 62.046초 · 65.096초 | 같은 파일 `timings.ui_total_s` |
| Micro-F1 (Neumann) | 0.5644 [0.5125, 0.612], n=148 | `score_astra.json` |
| 비상 규칙 Macro-F1 / Micro-F1 | 0.3234 [0.2434, 0.3871] / 0.3344 [0.263, 0.4025], n=148 | `data/eval/score_rule.json` (sha256 `b6d90596…`) |

## 4. 발표 문구에 붙일 조건

1. **Macro-F1은 미달부터 말한다.** 0.4864는 목표 0.70에 못 미치고, 사람 상한 0.725와 0.24 차이다. 빈도 기준선보다 높다는 말은 Macro에서만 맞다(astra 하한 0.4276 > 기준선 상한 0.3623). Micro는 구간이 겹친다(0.5644 대 0.5379).
2. **근거 연결률은 계획서별 값으로 적는다(10/10 · 13/13 · 20/20).** 합계 43/43은 카드용 계산이다. 이 값은 화면 실행과 별도로 같은 계획서를 `/premortem`으로 다시 돌린 결과에서 쟀다. 그래서 plan.md는 화면 카드 5장, 검사 카드 3장이다. 검사 실행의 카드 generator는 요약에 기록되지 않았다.
3. **폐기율을 같이 적는다(0.34%).** 폐기율 없는 100%는 의미가 약하다(04_평가_명세 §2.2).
4. **시연 3건은 리포트 화면까지다.** 결과 패키지(ZIP) 내보내기는 재지 않았다. 라이브 E2E 테스트 5개(연결 1 + 데모 3 + 범위 밖 1)가 모두 통과했다.
5. **모델 표기:** "평가 모델 gpt-6-astra로 잰 값. 제품 기본 모델 gpt-6.1-sol로는 재측정하지 않음(비용)."
6. **1회 실행이다.** LLM 출력은 호출마다 달라질 수 있다. 골드는 1회만 채점했다.
7. 12쪽의 커밋 수·태그 수·테스트 수는 이 표에 없다. 07:00 동결 때 `git rev-list --count HEAD`, `git tag --list`, `pytest -q`(mock)로 다시 센다(`E6-pres2.verify.md` 권고 1).

## 5. README용 (그대로 붙여 쓸 수 있음)

> 평가 모델 `gpt-6-astra`로 쟀다. 제품 기본 모델 `gpt-6.1-sol`로는 다시 재지 않았다.
> - 지적 추출 Macro-F1: **0.4864** [0.4276, 0.5394], n=148 (DISAPERE 합의 골드). 목표 0.70 미달. 사람 간 상한 0.725, 안 읽는 빈도 기준선 0.3308
> - 근거 연결률: **100%** (데모 계획서 3건, 링크 43/43), 폐기율 0.34% (7/2033)
> - 대표 계획 end-to-end 시연: 3/3 (리포트 화면까지, 라이브 E2E 1회)
> - 백테스트 Top-3 적중·표본 연결·원문 링크: 측정 전
>
> 전체 표: `docs/reports/report_card.md`

## 6. 재현

```bash
export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." NEUMANN_LLM_PROVIDER=mock   # 파일만 읽는다. OpenAI 호출 없음
python scripts/metrics_from_e2e.py --summary docs/reports/E5-L0e2e_live_summary.json \
  --model gpt-6-astra --product-model gpt-6.1-sol --out docs/reports/E5-L3b_metrics_e2e.json
D=C:/Users/User/Desktop/project_neumann/data/eval
python -m eval.report_card --inputs $D/score_baseline_freq.json $D/score_astra.json $D/score_rule.json \
  docs/reports/E5-L3b_metrics_e2e.json --out docs/reports/report_card.md
```
