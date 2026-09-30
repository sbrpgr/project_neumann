# E5-L3a 보고서: 리포트 카드 생성기

- 브랜치: `task/E5-L3a` · 빌더: claude-opus-5.5 · 검증 예정: Claude Sonnet 5.5
- 스펙: `docs/tasks/E5-L3a.md`. 참고: 계획서 §4 E5 L3, `부록/평가/report_card_template.md`, `04_평가_명세` §1.2·§2·§3.1·§5·§6·§7, `eval/macro_f1.py` 출력, `docs/tasks/E5-L2a.md`

## 무엇을 했나

1. **생성기** `eval/report_card.py`: `python -m eval.report_card --inputs <지표 JSON들> --out <md>`. 지표 JSON을 여러 개 받아 리포트 카드 Markdown 1장을 쓴다.
   - 순서: ① 참조선(사람 간 상한 0.725 [0.669, 0.772], 빈도 기준선 Macro·Micro, 빈도 기준선 백테스트) → ② 신청서 약속 대비(표 위에 "목표 미달 N건"·"측정 전 M건" 목록, 표는 미달 → 측정 전 → 달성 순) → ③ 지표별 값·95% 구간·n·조건·한계·입력 파일 → ④ 골드 없는 클래스 제외 목록 → ⑤ 각주(R7 매핑 한계, 신청서 대비 골드 대체, 제외 규칙) → ⑥ 한계 → ⑦ 재현(입력 sha256, 실제 CLI 명령).
   - 입력에 없는 지표는 "측정 전"(값·구간·n 모두 비움, "입력 없음")으로 적는다. 추정값을 넣지 않는다.
   - 값은 입력 JSON의 숫자를 문자열로 그대로 옮긴다(다시 반올림하지 않음). 근거 연결 보고서가 여러 개일 때만 합계로 다시 계산하고 값 옆에 "계산"을 붙인다.
   - `mock` generator 결과는 약속 칸을 채우지 않는다("mock(테스트용, 성능 아님)" 행으로만). `rule` generator는 "Neumann 비상 규칙" 행으로 따로 둔다.
   - 같은 (지표, 시스템)이 두 입력에서 오면 오류로 멈춘다(어느 값을 쓸지 고르지 않는다). 형식 오류는 종료 코드 2.
2. **테스트** `tests/e5/test_report_card.py`(22개): 가짜 지표 3종 입력으로 생성해서 값이 약속 표·상세 표에 글자 그대로 옮겨지는지(반올림하면 달라지는 0.612345 같은 값 사용), 없는 지표가 "측정 전"인지, 입력 0개면 약속 6개 모두 측정 전인지, 참조선이 약속 표보다 먼저인지, 미달 행이 측정 전·달성보다 먼저인지, 구간 하한이 목표 아래면 표시하는지, 제외 클래스·각주 3개, mock 배제, 폐기율 없음 표시, 여러 연결 보고서 합산, 형식 오류 7종·중복 거부, 옛 제품 숫자가 출력에 없는지, CLI 쓰기·오류 코드.
3. **실제 지표로 1회 생성** `docs/reports/report_card.md`: 지금 있는 실제 지표 `data/eval/score_baseline_freq.json`(빈도 기준선, E5-L1a)만 넣었다. 약속 6개는 전부 "측정 전", 참조선에 빈도 기준선 Macro-F1 0.3308 [0.298, 0.3623] n=148.

## 입력 지표 JSON 형식 (파일마다 자동 판별)

| 종류 | 판별 | 만드는 곳 | 채우는 지표 |
|---|---|---|---|
| Macro-F1 결과 | `metric`이 `review-level multilabel Tier-1 Macro-F1`로 시작 | `python -m eval.macro_f1` (E5-L1a) | `macro_f1`, `micro_f1`(값·`*_ci95.low/high`·`n`), 채점·제외 클래스, 골드 sha256. 시스템은 `predictions.generator_counts`: astra→Neumann, rule→비상 규칙, baseline→빈도 기준선(예측 파일 이름에 `freq`)·기준선, mock→mock, 여럿→혼합 |
| 근거 연결 보고서 | `report_schema == "neumann.linkage/1"` | `python -m eval.linkage --out` (E5-L0) | `linkage_rate`(links_ok/links_total), `card_pass_rate`, `drop_rate`(drop.available일 때, 없으면 "측정 전 (폐기율 없음)"). 전수라 구간 없음 |
| 일반 지표 | `schema == "neumann.metrics/1"` | 백테스트(E5-L2a) 등 나머지 | 아래 목록의 id |

```json
{"schema": "neumann.metrics/1",
 "source": "eval.backtest_metrics (선택)",
 "metrics": [
   {"id": "bt_hit_at_3", "system": "neumann", "value": 0.4, "n": 30, "ci95": [0.23, 0.57],
    "conditions": "판정자 Claude Sonnet 3명 격리·블라인드 다수결, 대표 재검토 10편", "limits": "n=30, 구간 폭 약 0.2"}
 ]}
```

- `value`: 숫자 또는 `null`(= 측정 전). `n`: 0 이상 정수 또는 생략. `ci95`: `[low, high]` 또는 `{"low", "high"}` 또는 생략(생략하면 구간 칸에 "없음"). `detail`(예: `"37/40"`)은 선택.
- id: `bt_precision_at_3`, `bt_hit_at_3`, `bt_false_positive_rate`, `bt_specificity`, `bt_evidence_rate`, `bt_diff_precision_at_3`, `judge_human_agreement`, `judge_human_kappa`, `corpus_linked_papers`, `source_link_rate`, `demo_e2e` (그 밖의 id도 받아서 "(기타)"로 싣는다).
- system: `neumann`, `neumann_rule`, `llm_baseline`, `freq_baseline`, `mock`, `human`, `all`.
- 약속 판정에 쓰는 칸: P1 `macro_f1`/neumann ≥ 0.70, P2 `linkage_rate`/neumann = 1.0, P3 `bt_hit_at_3`/neumann ≥ 0.50, P4 `corpus_linked_papers`/all ≥ 300, P5 `source_link_rate`/all = 1.0, P6 `demo_e2e`/all ≥ 3.

## 완료 기준별 결과

### 1. 가짜 지표 입력으로 생성 테스트 (값이 그대로 옮겨지는지, 없는 지표 표시) — 통과

```
$ export PYTHONIOENCODING=utf-8 PYTHONPATH="src;."
$ python -m pytest tests/e5/test_report_card.py -v   (진행률 [%] 칸은 뺐고, pytest가 \u로 적는 한글 매개변수 id는 풀어 적었다)
tests/e5/test_report_card.py::test_values_copied_verbatim_into_promise_table PASSED
tests/e5/test_report_card.py::test_values_copied_verbatim_into_detail_table PASSED
tests/e5/test_report_card.py::test_missing_metrics_marked_not_measured PASSED
tests/e5/test_report_card.py::test_no_inputs_everything_not_measured PASSED
tests/e5/test_report_card.py::test_null_value_in_generic_input_is_not_measured PASSED
tests/e5/test_report_card.py::test_reference_lines_come_first_and_shortfalls_before_met PASSED
tests/e5/test_report_card.py::test_ci_below_target_is_flagged PASSED
tests/e5/test_report_card.py::test_excluded_classes_and_footnotes PASSED
tests/e5/test_report_card.py::test_mock_generator_never_fills_promise PASSED
tests/e5/test_report_card.py::test_linkage_without_drop_rate_is_marked PASSED
tests/e5/test_report_card.py::test_multiple_linkage_reports_are_summed_and_marked_computed PASSED
tests/e5/test_report_card.py::test_rule_generator_goes_to_emergency_row PASSED
tests/e5/test_report_card.py::test_bad_inputs_rejected[obj0-모르는 형식] PASSED
tests/e5/test_report_card.py::test_bad_inputs_rejected[obj1-value가 없다] PASSED
tests/e5/test_report_card.py::test_bad_inputs_rejected[obj2-숫자가 아니다] PASSED
tests/e5/test_report_card.py::test_bad_inputs_rejected[obj3-low > high] PASSED
tests/e5/test_report_card.py::test_bad_inputs_rejected[obj4-0 이상 정수] PASSED
tests/e5/test_report_card.py::test_bad_inputs_rejected[obj5-id가 없다] PASSED
tests/e5/test_report_card.py::test_bad_inputs_rejected[obj6-최상위가 객체] PASSED
tests/e5/test_report_card.py::test_duplicate_metric_rejected PASSED
tests/e5/test_report_card.py::test_old_product_numbers_never_appear PASSED
tests/e5/test_report_card.py::test_cli_writes_file_and_errors PASSED
============================= 22 passed in 0.31s ==============================
```

- 가짜 입력: Macro-F1(astra) 0.612345 [0.551234, 0.667891] n=148 → P1 행에 `0.612345 | [0.551234, 0.667891] | 148 | **미달**`로 그대로 옮겨지는 것을 칸 단위로 비교한다. 연결 37/40 → `0.925 (37/40)`, hit@3 0.4333 [0.2667, 0.6] n=30 → P3 미달, 표본 1265 → P4 달성, P5·P6 → "측정 전".

### 2. 지금 있는 실제 지표로 1회 생성 — 완료 (`docs/reports/report_card.md`)

```
$ python -m eval.report_card --inputs C:/Users/User/Desktop/project_neumann/data/eval/score_baseline_freq.json --out docs/reports/report_card.md
- 목표 미달 0건: 없음
- 측정 전 6건: P1 지적 추출 Macro-F1, P2 근거 연결률 (폐기율 병기), P3 백테스트 Top-3 적중(hit@3), P4 표본 연결, P5 원문 링크, P6 대표 계획 end-to-end 시연
리포트 카드: docs\reports\report_card.md
```

카드 1절(참조선) 발췌:

```
| 사람 간 일치 상한(합의 골드) Macro-F1 — 외부 실측, 우리 성능 아님 | 0.725 | [0.669, 0.772] | 29리뷰(LOO) | … 04_평가_명세 §1.2 |
| 빈도 기준선(안 읽음, 최빈 3코드) 지적 추출 Macro-F1 (리뷰 단위) | 0.3308 | [0.298, 0.3623] | 148 | … |
| 빈도 기준선(안 읽음, 최빈 3코드) 지적 추출 Micro-F1 (리뷰 단위) | 0.5379 | [0.4871, 0.5861] | 148 | … |
| 빈도 기준선 백테스트 적중률 precision@3 (계산만, 발표 제외) | 측정 전 | — | — | 입력 없음 |
```

- 입력 값과 대조: `score_baseline_freq.json`의 `macro_f1` 0.3308, `macro_f1_ci95` 0.298/0.3623, `micro_f1` 0.5379, `micro_f1_ci95` 0.4871/0.5861, `n` 148, `excluded_classes` R3·R4·R8·R9 → 카드와 같다.
- 4절 제외 클래스: `빈도 기준선(안 읽음) | R1, R2, R5, R6, R7 | R3, R4, R8, R9`, 골드 sha256 `ad25cb4a…`.
- Neumann 지표(Macro-F1 astra·비상 규칙, 근거 연결률, 백테스트 전부, 판정 일치율)는 아직 측정 파일이 없어 모두 "측정 전"이다.
- 옛 제품 숫자(κ 0.238, Macro-F1 0.469, Top-3 0.322 등)는 카드에 없다(테스트가 검사).

### 3. `python scripts/verify.py` — 통과

```
$ python scripts/verify.py
.....................................................s.................. [ 34%]
......................................................s................. [ 69%]
...............................................................          [100%]
205 passed, 2 skipped in 4.07s
보안: 파일 125개
계약: 2개
테스트: 통과
verify 통과
```

(skip 2개는 E5-L1a의 DISAPERE 원본 테스트. `NEUMANN_RAW_DIR`를 안 줬을 때 건너뛴다.)

## 바꾼 파일

- `eval/report_card.py` (새 파일)
- `tests/e5/test_report_card.py` (새 파일)
- `docs/reports/report_card.md` (생성 산출물)
- `docs/reports/E5-L3a.md` (이 보고서)

`contracts/`·`models.py`·다른 `eval/` 파일은 건드리지 않았다. `eval.macro_f1.REFERENCE_LINES`(사람 상한 0.725)는 import만 한다(참조선 원본을 한 곳에 둔다).

## 결정 (스펙이 모호해서 고른 것)

1. **참조선은 0.725와 빈도 기준선만.** 스펙이 이 둘을 지목했다. 템플릿의 0.629·0.430·0.840(옛 프로토콜 문서의 DISAPERE 실측)은 넣지 않았다. 옛 문서 숫자와 섞이는 것을 피했다. 필요하면 PM이 `neumann.metrics/1`로 넣을 수 있다.
2. **"미달 먼저"의 뜻:** 약속 표 위에 미달·측정 전 목록을 적고, 표는 미달 → 측정 전 → 달성 순으로 정렬(같은 판정 안에서는 약속 번호 순). 나쁜 소식을 먼저 둔다.
3. **판정은 점추정 기준.** 점추정이 목표 이상이어도 구간 하한이 목표 아래면 "달성(구간 하한은 목표 아래)"로 적는다. 근거 연결률 100%는 "달성(폐기율 병기)"로 적는다.
4. **P3 Top-3는 hit@3.** `04_평가_명세` §0.4가 "Top-3 적중(hit@3) — 신청서 목표 50%와 대조"로 고정했다. precision@3는 상세 표에 둔다.
5. **백테스트 입력 형식을 일반 지표 형식으로.** E5-L2a 브랜치에 아직 `eval/backtest_metrics.py` 출력이 없다(착수 전 확인). 그래서 모델 중립의 `neumann.metrics/1`을 정의했다. E5-L2a 출력이 다르면 여기에 어댑터를 하나 더하거나 E5-L2a가 이 형식으로 내면 된다.
6. **값은 그대로.** 입력 숫자를 `str()`로 옮긴다(0.298처럼 입력에 적힌 자릿수 그대로). 카드에서 자릿수를 맞추려고 반올림하지 않았다.
7. **generator `baseline`의 종류:** 예측 파일 이름에 `freq`가 있으면 빈도 기준선, 아니면 "기준선(종류 미상)". 일반 LLM 기준선은 Macro-F1 과제가 아니라 백테스트 쪽이라 이렇게 두었다.
8. 템플릿 §1의 약속 4~6(표본 연결 300편, 원문 링크 100%, 시연 3건)도 약속 표에 남겼다. 아직 재는 코드가 없으니 입력이 오기 전까지 "측정 전"이다.
9. 카드의 입력 경로는 공유 데이터 폴더의 절대 경로다(E5-L1a 보고서와 같은 방식). 재현 명령에 실제 경로가 필요해서다.

## 못 한 것

- Neumann 자체 지표(astra Macro-F1, 근거 연결률, 백테스트)는 아직 측정 파일이 없어 카드에 "측정 전"으로만 있다. 파일이 생기면 `--inputs`에 더해 다시 돌리면 된다.
- 템플릿의 §2 데이터·코퍼스, §3 라벨링 IAA, §7 오탐 유형, §8 블라인드 비교 표는 만들지 않았다. 스펙의 "한 장"과 본선 §0 지표에 맞춰 줄였다. 필요한 수치는 `neumann.metrics/1`의 기타 id로 넣으면 상세 표에 실린다.
- 발표용 HTML/이미지 렌더링은 하지 않았다(Markdown만).

## 다음 과제에 넘길 것

- E5-L2a: 백테스트 지표를 `neumann.metrics/1`(id `bt_*`, system `neumann`/`llm_baseline`/`freq_baseline`, `conditions`에 블라인드·판정자 수와 구성·사람 재검토 여부)로 내 주면 바로 카드에 들어간다. 대표 판정 일치율·κ는 `judge_human_agreement`/`judge_human_kappa`(system `all`).
- E3·E5: astra 예측 Macro-F1은 `python -m eval.macro_f1 ... --out data/eval/score_astra.json`, 비상 규칙은 generator `rule`로 채점하면 각각 자기 행에 들어간다.
- PM: 최종 카드 명령 예 `python -m eval.report_card --inputs data/eval/score_baseline_freq.json data/eval/score_astra.json <linkage 보고서들> <backtest metrics> --out docs/reports/report_card.md`.
