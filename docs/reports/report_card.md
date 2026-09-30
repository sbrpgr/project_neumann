# Project Neumann — 검증 리포트 카드

- 생성: 2026-09-30T21:09:11+09:00 · 코드 커밋: `ef60c99` · 생성 명령: `python -m eval.report_card --inputs C:/Users/User/Desktop/project_neumann/data/eval/score_baseline_freq.json C:/Users/User/Desktop/project_neumann/data/eval/score_astra.json C:/Users/User/Desktop/project_neumann/data/eval/score_rule.json docs/reports/E5-L3b_metrics_e2e.json --out docs/reports/report_card.md`
- 규칙(04_평가_명세 §7): 참조선 먼저 · 미달 먼저 · 모든 숫자에 n과 95% 구간 · 없는 지표는 "측정 전"(추정 금지)
- 값은 입력 JSON의 숫자를 그대로 옮겼다. 합쳐서 계산한 값은 '계산'으로 표시했다.

## 1. 참조선 — 우리 숫자보다 먼저 본다

| 참조선 | 값 | 95% 구간 | n | 조건·출처 |
|---|---|---|---|---|
| 사람 간 일치 상한(합의 골드) Macro-F1 — 외부 실측, 우리 성능 아님 | 0.725 | [0.669, 0.772] | 29리뷰(LOO) | DISAPERE 4인 라벨 29리뷰, 1명 대 나머지 3명 다수결(leave-one-out). 과제 난이도 천장, 04_평가_명세 §1.2 |
| 빈도 기준선(안 읽음, 최빈 3코드) 지적 추출 Macro-F1 (리뷰 단위) | 0.3308 | [0.298, 0.3623] | 148 | 리뷰 단위 멀티라벨 Tier-1, 골드 disapere_gold.jsonl n=148 (sha256 ad25cb4ad575), 부트스트랩 2000회 시드 20260930 percentile, generator {'baseline': 148}, 예측 없음 0건은 빈 예측으로 채점 |
| 빈도 기준선(안 읽음, 최빈 3코드) 지적 추출 Micro-F1 (리뷰 단위) | 0.5379 | [0.4871, 0.5861] | 148 | 리뷰 단위 멀티라벨 Tier-1, 골드 disapere_gold.jsonl n=148 (sha256 ad25cb4ad575), 부트스트랩 2000회 시드 20260930 percentile, generator {'baseline': 148}, 예측 없음 0건은 빈 예측으로 채점 |
| 빈도 기준선 백테스트 적중률 precision@3 (계산만, 발표 제외) | 측정 전 | — | — | 입력 없음 |

## 2. 신청서 약속 대비 — 미달을 먼저 적는다

- **목표 미달 1건:** P1 지적 추출 Macro-F1
- **측정 전 3건:** P3 백테스트 Top-3 적중(hit@3), P4 표본 연결, P5 원문 링크

| # | 약속 (신청서) | 목표 | 측정값 | 95% 구간 | n | 판정 | 입력 |
|---|---|---|---|---|---|---|---|
| P1 | 지적 추출 Macro-F1 | ≥ 0.70 | 0.4864 | [0.4276, 0.5394] | 148 | **미달** | score_astra.json |
| P3 | 백테스트 Top-3 적중(hit@3) | ≥ 0.50 | 측정 전 | — | — | **측정 전** | — |
| P4 | 표본 연결 | ≥ 300편 | 측정 전 | — | — | **측정 전** | — |
| P5 | 원문 링크 | 100% | 측정 전 | — | — | **측정 전** | — |
| P2 | 근거 연결률 (폐기율 병기) | 100% | 1.0 (43/43; plan.md 10/10 · plan_elife_neuro.md 13/13 · plan_medimaging.md 20/20; 검사 실행 카드 generator 미기록) | 없음 | 43 | **달성(폐기율 병기)** | E5-L3b_metrics_e2e.json |
| P6 | 대표 계획 end-to-end 시연 | 3건 | 3 (3/3) | 없음 | 3 | **달성** | E5-L3b_metrics_e2e.json |

판정은 점추정과 목표를 비교한다. 구간 하한이 목표 아래면 그렇게 적는다. Macro-F1 목표는 사람 간 상한(1절) 근처라는 점을 같이 읽는다[주2].

## 3. 지표별 값·n·95% 구간·조건·한계

| 지표 | 시스템 | 값 | 95% 구간 | n | 조건 | 한계 | 입력 |
|---|---|---|---|---|---|---|---|
| 지적 추출 Macro-F1 (리뷰 단위) | 빈도 기준선(안 읽음) | 0.3308 | [0.298, 0.3623] | 148 | 리뷰 단위 멀티라벨 Tier-1, 골드 disapere_gold.jsonl n=148 (sha256 ad25cb4ad575), 부트스트랩 2000회 시드 20260930 percentile, generator {'baseline': 148}, 예측 없음 0건은 빈 예측으로 채점 | 골드 support 0 클래스 ['R3', 'R4', 'R8', 'R9'] 제외[주3], R7 근사[주1], 골드 대체[주2]. 안 읽는 기준선이다(04_평가_명세 §6: 기준선 없는 단독 숫자 보고 금지). 늘 내는 코드(R1·R2·R6)는 재현율 1.0, 안 내는 코드(R5·R7)는 재현율 0이라 Micro-F1(0.5379)이 Macro-F1(0.3308)보다 높다 | score_baseline_freq.json |
| 지적 추출 Macro-F1 (리뷰 단위) | Neumann (astra) | 0.4864 | [0.4276, 0.5394] | 148 | 리뷰 단위 멀티라벨 Tier-1, 골드 disapere_gold.jsonl n=148 (sha256 ad25cb4ad575), 부트스트랩 2000회 시드 20260930 percentile, generator {'astra': 148}, 예측 없음 0건은 빈 예측으로 채점 | 골드 support 0 클래스 ['R3', 'R4', 'R8', 'R9'] 제외[주3], R7 근사[주1], 골드 대체[주2] | score_astra.json |
| 지적 추출 Macro-F1 (리뷰 단위) | Neumann 비상 규칙 | 0.3234 | [0.2434, 0.3871] | 148 | 리뷰 단위 멀티라벨 Tier-1, 골드 disapere_gold.jsonl n=148 (sha256 ad25cb4ad575), 부트스트랩 2000회 시드 20260930 percentile, generator {'rule': 148}, 예측 없음 0건은 빈 예측으로 채점 | 골드 support 0 클래스 ['R3', 'R4', 'R8', 'R9'] 제외[주3], R7 근사[주1], 골드 대체[주2] | score_rule.json |
| 지적 추출 Macro-F1 (리뷰 단위) | Neumann 제품 기본 모델(gpt-6.1-sol) | 측정 전 | — | — | 측정 전. 이 모델로 다시 재지 않았다. 이 카드의 Neumann 수치는 평가 모델 gpt-6-astra로 잰 것 | 재측정 안 한 사유: 비용(docs/decisions.md 2026-09-30 19:38(평가 모델·제품 모델 구분)·19:42(실제 호출 동결)) | E5-L3b_metrics_e2e.json |
| 지적 추출 Micro-F1 (리뷰 단위) | 빈도 기준선(안 읽음) | 0.5379 | [0.4871, 0.5861] | 148 | 리뷰 단위 멀티라벨 Tier-1, 골드 disapere_gold.jsonl n=148 (sha256 ad25cb4ad575), 부트스트랩 2000회 시드 20260930 percentile, generator {'baseline': 148}, 예측 없음 0건은 빈 예측으로 채점 | 골드 support 0 클래스 ['R3', 'R4', 'R8', 'R9'] 제외[주3], R7 근사[주1], 골드 대체[주2]. 안 읽는 기준선이다(04_평가_명세 §6: 기준선 없는 단독 숫자 보고 금지). 늘 내는 코드(R1·R2·R6)는 재현율 1.0, 안 내는 코드(R5·R7)는 재현율 0이라 Micro-F1(0.5379)이 Macro-F1(0.3308)보다 높다 | score_baseline_freq.json |
| 지적 추출 Micro-F1 (리뷰 단위) | Neumann (astra) | 0.5644 | [0.5125, 0.612] | 148 | 리뷰 단위 멀티라벨 Tier-1, 골드 disapere_gold.jsonl n=148 (sha256 ad25cb4ad575), 부트스트랩 2000회 시드 20260930 percentile, generator {'astra': 148}, 예측 없음 0건은 빈 예측으로 채점 | 골드 support 0 클래스 ['R3', 'R4', 'R8', 'R9'] 제외[주3], R7 근사[주1], 골드 대체[주2] | score_astra.json |
| 지적 추출 Micro-F1 (리뷰 단위) | Neumann 비상 규칙 | 0.3344 | [0.263, 0.4025] | 148 | 리뷰 단위 멀티라벨 Tier-1, 골드 disapere_gold.jsonl n=148 (sha256 ad25cb4ad575), 부트스트랩 2000회 시드 20260930 percentile, generator {'rule': 148}, 예측 없음 0건은 빈 예측으로 채점 | 골드 support 0 클래스 ['R3', 'R4', 'R8', 'R9'] 제외[주3], R7 근사[주1], 골드 대체[주2] | score_rule.json |
| 근거 연결률 (링크 단위) | Neumann (astra) | 1.0 (43/43; plan.md 10/10 · plan_elife_neuro.md 13/13 · plan_medimaging.md 20/20; 검사 실행 카드 generator 미기록) | 없음 | 43 | 라이브 E2E http://127.0.0.1:8010/ 2026-09-30T10:19:48+00:00~2026-09-30T10:25:34+00:00, 1회 실행, 평가 모델 gpt-6-astra. 데모 계획서 3건 /premortem 결과 전수, eval.linkage.check_result 원문 글자 단위 대조, 계획서별 개수 합산(계산) | 연결 검사는 화면 실행과 별도인 같은 계획서의 /premortem 재실행 결과다. 그 실행의 카드 generator는 요약에 기록되지 않았다(화면 실행 카드 generator {'astra': 13}, 강등 단계 0개). 전수라 구간 없음. 제품 기본 모델로는 재측정 안 함. 폐기율과 같이 읽는다(04_평가_명세 §2.2) | E5-L3b_metrics_e2e.json |
| 근거 연결률 (링크 단위) | Neumann 제품 기본 모델(gpt-6.1-sol) | 측정 전 | — | — | 측정 전. 이 모델로 다시 재지 않았다. 이 카드의 Neumann 수치는 평가 모델 gpt-6-astra로 잰 것 | 재측정 안 한 사유: 비용(docs/decisions.md 2026-09-30 19:38(평가 모델·제품 모델 구분)·19:42(실제 호출 동결)) | E5-L3b_metrics_e2e.json |
| 카드 통과율 (모든 근거 연결된 카드) | Neumann (astra) | 1.0 (12/12; plan.md 3/3 · plan_elife_neuro.md 4/4 · plan_medimaging.md 5/5) | 없음 | 12 | 라이브 E2E http://127.0.0.1:8010/ 2026-09-30T10:19:48+00:00~2026-09-30T10:25:34+00:00, 1회 실행, 평가 모델 gpt-6-astra. 데모 계획서 3건 /premortem 결과 전수, eval.linkage.check_result 원문 글자 단위 대조, 계획서별 개수 합산(계산) | 연결 검사는 화면 실행과 별도인 같은 계획서의 /premortem 재실행 결과다. 그 실행의 카드 generator는 요약에 기록되지 않았다(화면 실행 카드 generator {'astra': 13}, 강등 단계 0개). 전수라 구간 없음. 제품 기본 모델로는 재측정 안 함 | E5-L3b_metrics_e2e.json |
| 폐기율 (버린 지적 / 전체 지적) | Neumann (astra) | 0.0034 (7/2033; plan.md 1/643 · plan_elife_neuro.md 2/701 · plan_medimaging.md 4/689) | 없음 | 2033 | 라이브 E2E http://127.0.0.1:8010/ 2026-09-30T10:19:48+00:00~2026-09-30T10:25:34+00:00, 1회 실행, 평가 모델 gpt-6-astra. 데모 계획서 3건 /premortem 결과 전수, eval.linkage.check_result 원문 글자 단위 대조, 계획서별 개수 합산(계산). 폐기 출처 verification(검증 단계에서 버린 지적) | 전수 계산 | E5-L3b_metrics_e2e.json |
| 폐기율 (버린 지적 / 전체 지적) | Neumann 제품 기본 모델(gpt-6.1-sol) | 측정 전 | — | — | 측정 전. 이 모델로 다시 재지 않았다. 이 카드의 Neumann 수치는 평가 모델 gpt-6-astra로 잰 것 | 재측정 안 한 사유: 비용(docs/decisions.md 2026-09-30 19:38(평가 모델·제품 모델 구분)·19:42(실제 호출 동결)) | E5-L3b_metrics_e2e.json |
| 백테스트 적중률 precision@3 (A 비율) | Neumann (astra) | 측정 전 | — | — | — | — | 입력 없음 |
| 백테스트 적중률 precision@3 (A 비율) | 일반 LLM 기준선 | 측정 전 | — | — | — | — | 입력 없음 |
| 백테스트 Top-3 적중 hit@3 | Neumann (astra) | 측정 전 | — | — | — | — | 입력 없음 |
| 백테스트 Top-3 적중 hit@3 | 일반 LLM 기준선 | 측정 전 | — | — | — | — | 입력 없음 |
| 백테스트 오탐률 (C 비율) | Neumann (astra) | 측정 전 | — | — | — | — | 입력 없음 |
| 백테스트 오탐률 (C 비율) | 일반 LLM 기준선 | 측정 전 | — | — | — | — | 입력 없음 |
| 백테스트 특이성 (진짜 − 셔플 적중률) | Neumann (astra) | 측정 전 | — | — | — | — | 입력 없음 |
| 백테스트 특이성 (진짜 − 셔플 적중률) | 일반 LLM 기준선 | 측정 전 | — | — | — | — | 입력 없음 |
| 백테스트 근거율 | Neumann (astra) | 측정 전 | — | — | — | — | 입력 없음 |
| 백테스트 근거율 | 일반 LLM 기준선 | 측정 전 | — | — | — | — | 입력 없음 |
| 적중률 차이 Neumann − 일반 LLM (짝지은 부트스트랩) | Neumann (astra) | 측정 전 | — | — | — | — | 입력 없음 |
| 판정 일치율 (대표 10편 vs AI 다수결, A/B/C) | 전체 | 측정 전 | — | — | — | — | 입력 없음 |
| 판정 κ (대표 vs AI 다수결, A 여부 이진) | 전체 | 측정 전 | — | — | — | — | 입력 없음 |
| 대표 계획 end-to-end 시연 | 전체 | 3 (3/3) | 없음 | 3 | 라이브 E2E http://127.0.0.1:8010/ 2026-09-30T10:19:48+00:00~2026-09-30T10:25:34+00:00, 1회 실행, 평가 모델 gpt-6-astra. 데모 계획서가 실서버에서 붙여넣기→리포트 화면·파이프라인 연결·카드 인용·원문 링크·생성 방식 표시·브라우저 오류 0·근거 연결 1.0 검사를 실패 0으로 통과한 수. 범위 밖 입력 negative_recipe.md: 카드 0장, 실패 0건, 사유 표시 | 리포트 화면까지. 결과 패키지(ZIP) 내보내기는 재지 않았다. 1회 실행 | E5-L3b_metrics_e2e.json |
| 대표 계획 end-to-end 시연 | Neumann 제품 기본 모델(gpt-6.1-sol) | 측정 전 | — | — | 측정 전. 이 모델로 다시 재지 않았다. 이 카드의 Neumann 수치는 평가 모델 gpt-6-astra로 잰 것 | 재측정 안 한 사유: 비용(docs/decisions.md 2026-09-30 19:38(평가 모델·제품 모델 구분)·19:42(실제 호출 동결)) | E5-L3b_metrics_e2e.json |
| (기타) e2e_cards | Neumann (astra) | 13 (plan.md 5 · plan_elife_neuro.md 3 · plan_medimaging.md 5) | 없음 | 3 | 라이브 E2E http://127.0.0.1:8010/ 2026-09-30T10:19:48+00:00~2026-09-30T10:25:34+00:00, 1회 실행, 평가 모델 gpt-6-astra. 화면(/premortem/view)에 나온 위험카드 수, 데모 계획서 합. 화면 카드 generator {'astra': 13} | 개수일 뿐 품질 지표가 아니다. 연결 검사 카드 수(card_pass_rate의 n)와 다른 실행이라 다를 수 있다 | E5-L3b_metrics_e2e.json |

## 4. 골드 없는 클래스 — Macro-F1에서 제외[주3]

| 시스템 | 채점 클래스 | 제외 클래스(골드 support 0) |
|---|---|---|
| 빈도 기준선(안 읽음) | R1, R2, R5, R6, R7 | R3, R4, R8, R9 |
| Neumann (astra) | R1, R2, R5, R6, R7 | R3, R4, R8, R9 |
| Neumann 비상 규칙 | R1, R2, R5, R6, R7 | R3, R4, R8, R9 |

- 골드: disapere_gold.jsonl n=148 sha256 `ad25cb4ad5759350a3c5383f6fcdcc7c7daaf15ed88256815c4a109e55f6b74c`

## 5. 각주

**[주1] R7 매핑 한계.** Macro-F1 골드의 R7(일반화·적용범위)은 DISAPERE `asp_motivation-impact`(동기·영향)를 옮긴 근사다(04_평가_명세 §3.1). 동기·영향 지적은 R7의 하위 유형 중 '영향·함의 불명확'에 가깝고, 외적 타당성·적용범위·외삽 같은 일반화 지적은 골드에 덜 잡힌다. R7 점수는 이 한계와 같이 읽는다.

**[주2] 신청서 대비 골드 대체.** 신청서는 수동 라벨 100건(2인 교차)을 약속했다. 본선은 공개 사람 라벨 DISAPERE 합의 골드(과반 합의)로 대체했다(대표 승인 2026-09-29, 계획서 §1.5, 04_평가_명세 §5 결정 5). 목표 0.70은 그대로 둔다.

**[주3] 골드 없는 클래스 제외.** 골드 support가 0인 클래스는 Macro-F1 평균에서 자동 제외한다(04_평가_명세 §2.1 규칙 ①). 사후에 support가 적다고 빼지 않는다. 제외 클래스의 FP는 Micro-F1에 들어간다.

## 6. 한계 — 먼저 말한다

1. 측정 전 지표는 비워 두지 않고 '측정 전'으로 적었다. 이 카드의 빈칸을 추정값으로 읽지 않는다.
2. 사람 간 상한 0.725는 DISAPERE 외부 실측이다. 우리 시스템 성능이 아니라 과제 난이도의 천장이다.
3. 빈도 기준선은 입력을 읽지 않는다. 기준선 없는 단독 숫자는 보고하지 않는다(04_평가_명세 §6).
4. 백테스트 n=30이면 95% 구간 폭이 약 0.2다. 유의성을 주장하지 않고 점추정·구간·차이의 방향만 말한다.
5. 백테스트 판정 조건(블라인드 여부·판정자 수와 구성·사람 재검토 여부)은 각 지표의 '조건' 칸을 본다. 입력에 없으면 측정 전이다.

## 7. 재현

| 입력 파일 | 종류 | sha256 |
|---|---|---|
| `C:\Users\User\Desktop\project_neumann\data\eval\score_baseline_freq.json` | macro_f1 | `e9b7e44c5ca4d8a704606b92a0333d277f4c3066267049012dbdec35ce066404` |
| `C:\Users\User\Desktop\project_neumann\data\eval\score_astra.json` | macro_f1 | `c409bed9f294bd14ee666b21514389fb721517da9db402bf61663a8cf4e89595` |
| `C:\Users\User\Desktop\project_neumann\data\eval\score_rule.json` | macro_f1 | `b6d90596d39ad08f4dfd2c54f1013abe0379500c6b36bda68a930deed82ebc1a` |
| `docs\reports\E5-L3b_metrics_e2e.json` | metrics | `8e6175e037a32c0226ee8a1d536fd445bc66f1d79cf6597a116d15672615d444` |

```
python -m eval.macro_f1 --pred C:\Users\User\Desktop\project_neumann\data\eval\pred_baseline_freq.jsonl --gold C:\Users\User\Desktop\project_neumann\data\eval\disapere_gold.jsonl --out <score_baseline_freq.json>
python -m eval.macro_f1 --pred C:\Users\User\Desktop\project_neumann\data\eval\pred_astra_gold.jsonl --gold C:\Users\User\Desktop\project_neumann\data\eval\disapere_gold.jsonl --out <score_astra.json>
python -m eval.macro_f1 --pred C:\Users\User\Desktop\project_neumann\data\eval\pred_rule_gold.jsonl --gold C:\Users\User\Desktop\project_neumann\data\eval\disapere_gold.jsonl --out <score_rule.json>
python -m eval.report_card --inputs C:/Users/User/Desktop/project_neumann/data/eval/score_baseline_freq.json C:/Users/User/Desktop/project_neumann/data/eval/score_astra.json C:/Users/User/Desktop/project_neumann/data/eval/score_rule.json docs/reports/E5-L3b_metrics_e2e.json --out docs/reports/report_card.md
```
