# E5-L1b 보고서: DISAPERE 골드에 astra 지적 추출 → 리뷰 단위 Macro-F1

- 브랜치 `task/E5-L1b` · 빌더 claude-opus-5.5 · 검증 예정 Claude Sonnet 5.5
- 스펙 `docs/tasks/E5-L1b.md`, 규칙 `04_평가_명세` §0.6(튜닝은 dev 358건만, 골드 148건은 채점에만)·§2.1·§6, 형식 `docs/reports/E5-L1a.md`
- 추출기: E3 `task/E3-L0`을 병합해 그대로 씀(`53c2070`, 골드 직전 재병합 `e801a82` = E3-L0 `c2b41ae`). 추출기 코드는 고치지 않았다

## 결과 (골드 148건, 1회 채점)

| 시스템 | Macro-F1 [95%] | Micro-F1 [95%] | n | 비고 |
|---|---|---|---|---|
| 사람 간 상한(합의 골드) | 0.725 [0.669, 0.772] | — | 29리뷰 LOO | 외부 실측, `04_평가_명세` §1.2. 과제 난이도 천장 |
| **astra 지적 추출(EX-4, gpt-6-astra)** | **0.4864 [0.4276, 0.5394]** | **0.5644 [0.5125, 0.6120]** | 148 | generator astra 148/148, 강등 0 |
| 비상 규칙 태거(`neumann.index.taxonomy`) | 0.3234 [0.2434, 0.3871] | 0.3344 [0.2630, 0.4025] | 148 | generator rule 148/148 |
| 빈도 기준선(안 읽음, dev 최빈 R1·R2·R6) | 0.3308 [0.2980, 0.3623] | 0.5379 [0.4871, 0.5861] | 148 | E5-L1a 측정값(`score_baseline_freq.json`) |

- 채점 클래스 C* = R1·R2·R5·R6·R7. R3·R4·R8·R9는 골드 support 0이라 Macro에서 뺐다(E5-L1a와 같은 규칙, `eval.macro_f1` 자동 제외). 제외 클래스의 FP는 Micro에 들어간다(astra R3 2·R4 2, 규칙 R3 2·R4 9)
- 구간: 심사평 재표집 부트스트랩 2,000회, 시드 20260930, percentile, 재표집마다 C* 재계산
- astra Macro 구간 하한(0.4276)이 빈도 기준선 구간 상한(0.3623)보다 높다. 사람 상한(0.725)과는 0.24 차이. 목표 0.70(EX-4)에는 못 미친다
- **Micro는 안 읽는 기준선과 구간이 겹친다**(0.5644 vs 0.5379). 흔한 R2를 늘 맞히는 기준선이 Micro에서 강하기 때문이다(§6 함정). Macro·Micro를 같이 싣는다
- 규칙 태거는 Macro가 빈도 기준선과 같은 수준(0.3234 vs 0.3308, 구간 겹침)이고 Micro는 훨씬 낮다. 비상 경로일 뿐 지적 추출 성능 주장에 쓰지 않는다

클래스별(골드):

| 클래스 | support | astra P / R / F1 (TP·FP·FN) | 규칙 P / R / F1 (TP·FP·FN) |
|---|---|---|---|
| R1 | 42 | 0.387 / 0.857 / **0.533** (36·57·6) | 0.583 / 0.167 / 0.259 (7·5·35) |
| R2 | 85 | 0.703 / 0.835 / **0.763** (71·30·14) | 0.720 / 0.212 / 0.327 (18·7·67) |
| R5 | 15 | 0.200 / 0.533 / **0.291** (8·32·7) | 0.600 / 0.400 / 0.480 (6·4·9) |
| R6 | 47 | 0.528 / 0.809 / **0.639** (38·34·9) | 0.541 / 0.426 / 0.476 (20·17·27) |
| R7 | 14 | 0.130 / 0.500 / **0.206** (7·47·7) | 0.077 / 0.071 / 0.074 (1·12·13) |

- astra는 재현율이 높고(Micro R 0.788) 정밀도가 낮다(Micro P 0.440). 골드 no_risk 35건 중 astra가 빈 예측을 낸 것은 5건뿐이다(규칙 19건)
- 약한 클래스는 R7(0.206)·R5(0.291). R7은 매핑 차이가 크다(한계 1)

## 완료 기준별 명령과 출력

### 1. 골드 채점 결과 JSON

```
$ export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." NEUMANN_DATA_DIR=C:/Users/User/Desktop/project_neumann/data
$ D=$NEUMANN_DATA_DIR/eval
$ python -m eval.disapere_extract extract --split gold --generator astra      # 19:20:35 시작 (HEAD c4e9329)
astra gold: 리뷰 148 · 문장 2532 · generator {'astra': 148}
{"reviews": 148, "sentences": 2532, "batches": 149, "llm_requests": 149, "llm_attempts": 149, "cached_batches": 0, "failed_requests": 0, "failures_by_reason": {}, "retry_rounds_used": 0, "reviews_fallback_final": 0, "latency_s_sum": 1450.9, "tokens": {"input_tokens": 218074, "output_tokens": 66773, "reasoning_tokens": 21937, "total_tokens": 284847}, "findings_raw": 1372, "findings_kept": 1370, "drops": {"out_of_range": 2}, "wall_s": 106.1, "mean_latency_s": 9.74}
$ python -m eval.disapere_extract extract --split gold --generator rule
rule gold: 리뷰 148 · 문장 2532 · generator {'rule': 148}
$ python -m eval.disapere_extract predict --split gold --generator astra
예측 148건 → …\pred_astra_gold.jsonl  규칙 {'polarities': ['negative'], 'min_confidence': 0.0, 'min_count': 1}  generator {'astra': 148}
$ python -m eval.macro_f1 --pred $D/pred_astra_gold.jsonl --gold $D/disapere_gold.jsonl --out $D/score_astra.json
Macro-F1 0.4864 [95% 0.4276, 0.5394]  Micro-F1 0.5644 [95% 0.5125, 0.6120]  n=148
채점 클래스 ['R1', 'R2', 'R5', 'R6', 'R7']  제외(골드 support 0) ['R3', 'R4', 'R8', 'R9']
예측: 채점 148 · 없음 0(빈 예측으로 채점) · 골드 밖 0(무시) · 빈 집합 5 · R0 제외 0 · generator {'astra': 148}
$ python -m eval.disapere_extract predict --split gold --generator rule
예측 148건 → …\pred_rule_gold.jsonl  규칙 {'polarities': ['negative', 'neutral'], 'min_confidence': 0.0, 'min_count': 1}  generator {'rule': 148}
$ python -m eval.macro_f1 --pred $D/pred_rule_gold.jsonl --gold $D/disapere_gold.jsonl --out $D/score_rule.json
Macro-F1 0.3234 [95% 0.2434, 0.3871]  Micro-F1 0.3344 [95% 0.2630, 0.4025]  n=148
예측: 채점 148 · 없음 0(빈 예측으로 채점) · 골드 밖 0(무시) · 빈 집합 67 · R0 제외 0 · generator {'rule': 148}
```

산출물(공유 데이터 폴더 `C:/Users/User/Desktop/project_neumann/data/eval/`, 커밋 안 함):

| 파일 | 내용 |
|---|---|
| `score_astra.json` | created_at 2026-09-30T19:22:28+09:00, pred sha256 `711425e4e6ff5e18…`, gold sha256 `ad25cb4ad5759350…`(E5-L1a 골드와 같음) |
| `score_rule.json` | created_at 2026-09-30T19:22:29+09:00, pred sha256 `13bb237817a97fd5…` |
| `pred_{astra,rule}_gold.jsonl` | E5-L1a 형식 + `status`·`model`·`agg`(적용한 집계 규칙) |
| `raw_{astra,rule}_{dev,gold}.jsonl` · `*.stats.json` | 문장별 지적(문장 번호·구간·코드·극성·신뢰도·생성 주체)과 호출 통계 |
| `tune_{astra,rule}_dev.json` · `score_{astra,rule}_dev.json` | dev 격자 24개 점수·선택 결과, dev 채점(구간 포함) |

### 2. dev 튜닝과 골드 채점의 커밋 순서

| 순서 | 커밋 | 시각 | 내용 |
|---|---|---|---|
| 1 | `1f452cd` | dev 추출 전 | 예측기 + **튜닝 격자·선택 규칙 사전 고정**(FROZEN=None이면 골드 예측 거부) |
| 2 | `6c84984` | | 테스트 |
| 3 | `e801a82` | | `task/E3-L0` 재병합(c2b41ae: llm 오류 문구·pipeline 보안 수정. `extract.py` 변경 없음) |
| 4 | `c4e9329` | 19:20:26 | **dev 튜닝 고정**(FROZEN에 astra·rule 규칙). 이때까지 골드 추출·예측·채점 0회 |
| 5 | 이 보고서 커밋 | 19:22 이후 | 골드 148건 추출 19:20:35 → 채점 19:22:28/29, 각 1회. 골드를 본 뒤 바꾼 규칙·코드 없음 |

- 골드 파일에서 추출기는 문장·본문만 읽는다(`load_docs`는 라벨 필드를 담지 않는다, 테스트 `test_load_docs_does_not_carry_labels`)
- 튜닝 명령은 dev가 아닌 행이 하나라도 있으면 거부한다(`load_dev_labels`, 테스트 `test_dev_labels_refuse_gold_rows`). 골드 예측은 커밋된 FROZEN으로만 만들고 `--config`를 거부한다(`test_predict_refuses_gold_without_frozen_rule_and_with_adhoc_config`)
- 재병합 전후 추출기 지문(`PROMPT_VERSION`·`INSTRUCTIONS`·스키마 해시) `7f1d7b247748d15d` 동일. 재병합 코드로 dev raw를 캐시에서 다시 만들어 astra·rule 모두 바이트 단위 동일(파이썬 객체 비교 `identical`) 확인 → dev 결과 재확인 완료. 골드 직전 `git log HEAD..task/E3-L0` 비어 있음

### 3. `python scripts/verify.py` 통과

(출력은 맨 아래 "verify" 절)

## 조정 이력 (dev 358건만)

조정 대상은 **리뷰 단위 집계 규칙**(문장별 지적 → 리뷰의 코드 집합)이다. 격자와 선택 규칙은 dev 결과를 보기 전에 커밋했다(`1f452cd`).

- 격자 24개: 극성 {negative} / {negative, neutral} × 신뢰도 하한 {0, 0.5, 0.6, 0.7, 0.8, 0.9} × 같은 코드 최소 문장 수 {1, 2}
- 선택 규칙: dev Macro-F1 최대, 1e-9 이내 동률이면 격자 순서(단순한 것 먼저)

| 회차 | 무엇을 | 왜 | dev Macro / Micro |
|---|---|---|---|
| astra 0 | E3 지시문 그대로, effort low, 묶음 50, 동시 16으로 dev 358건 추출(1회) | 제품 추출기를 그대로 잰다 | — |
| astra 1 | 격자 24개 채점 | 신뢰도·반복 문장 수로 FP를 줄일 수 있는지 | 최고 0.5553 / 0.6122 (negative·≥0·≥1). 하한 0.5~0.6은 동률, 0.7 0.5546, 0.8 0.5527, 0.9 0.5320. 최소 2문장은 0.42~0.52로 모두 나쁨. neutral 추가는 차이 없음(astra가 neutral을 거의 안 냄: 극성 negative 3,639 · positive 340 · neutral 0) |
| **astra 고정** | negative · 하한 0 · 1문장 | 선택 규칙 그대로(동률 중 첫 것) | **0.5553 [0.5251, 0.5837] / 0.6122 [0.5845, 0.6382]** |
| rule 1 | 격자 24개 채점 | 같은 방법 | 최고 0.2755 / 0.3026 (negative+neutral·≥0·≥1). negative만 0.2712. 하한 0.7 이상(= 규칙 점수 3 이상)은 0.08 이하 |
| **rule 고정** | negative+neutral · 하한 0 · 1문장 | 선택 규칙 그대로 | **0.2755 [0.2335, 0.3158] / 0.3026 [0.2607, 0.3429]** |

dev 클래스별(astra 고정 규칙): R1 0.709 · R2 0.740 · R5 0.454 · R6 0.658 · R7 0.215. R7 FP 122 · TP 20.

- **지시문은 조정하지 않았다**(결정 1). dev 튜닝은 위 집계 규칙뿐이다. 지시문 개선은 "제안"에 적었다
- dev → 골드 하락(Macro 0.5553 → 0.4864): 한계 2

## 호출 통계 (이 과제의 실제 OpenAI 호출 전부)

| 실행 | 리뷰 | 문장 | 실제 호출 | 캐시 | 실패 | 재시도 라운드 | 벽시계 | 평균 지연 | 토큰(입력/출력/추론) |
|---|---|---|---|---|---|---|---|---|---|
| 스모크(dev 앞 3건) | 3 | 76 | 3 | 0 | 0 | 0 | 14.7s | 11.9s | 4,982 / 1,942 / 439 |
| dev 전체 | 358 | 7,414 | 366 | 3(스모크분) | 0 | 0 | 255.4s | 10.6s | 571,168 / 182,184 / 54,417 |
| dev 재확인(재병합 뒤) | 358 | 7,414 | 0 | 369 | 0 | 0 | 0.3s | — | 0 |
| 골드 | 148 | 2,532 | 149 | 0 | 0 | 0 | 106.1s | 9.7s | 218,074 / 66,773 / 21,937 |
| live 테스트(`NEUMANN_LIVE_TESTS=1`) | 2(직접 지은 문장) | 5 | 2 | 0 | 0 | 0 | 8.6s | — | 기록 안 함 |
| **합계** | | | **520** | | **0** | | 약 6.4분 | | 약 1.05M 토큰(live 제외) |

- 모델 `gpt-6-astra`(Responses API), 추론 강도 low(E3 기본값), 호출 상한 90s, 묶음 50문장(E3 기본), 동시 16(E3 기본 24보다 낮춤)
- 캐시: `data/cache/e5_disapere/7f1d7b247748d15d/`(추출기 지문별 폴더, E3 캐시 키 = 문장 해시·모델·강도·지시문 판). 518개
- 속도 제한·시간 초과·스키마 오류 0건 → 규칙 강등 0건. 재시도·백오프 경로(15s·45s·90s, 최대 3라운드)는 mock 테스트로만 확인
- 검증 폐기: dev 3,986건 중 7건(out_of_range 6, duplicate 1), 골드 1,372건 중 2건(out_of_range) = 0.15%

## 바꾼 파일

- `eval/disapere_extract.py`(새 파일): extract(astra·rule·mock) / tune(dev만) / predict(FROZEN만)
- `tests/e5/test_disapere_extract.py`(새 파일): 17개(mock 16 + live 1)
- `docs/reports/E5-L1b.md`(이 보고서)
- 병합으로 들어온 E3 파일(`src/neumann/llm.py`, `src/neumann/analyze/*`, `src/neumann/pipeline.py`, `tests/e3/*`, `docs/reports/E3-L0.md`)은 고치지 않았다

## 결정 (스펙이 모호해서 고른 것)

1. **지시문은 E3 것 그대로, 조정은 집계 규칙만.** 스펙은 "지시문·임계값 조정"을 허락하지만 추출기는 E3 소유이고, 평가용 지시문을 따로 쓰면 이 숫자가 제품 추출기의 성능이 아니게 된다. 그래서 제품 경로(`extract_issues`, `INSTRUCTIONS` v1, effort low, 묶음 50)를 그대로 쟀다. 지시문 조정안은 "제안"에 적었다
2. **리뷰 단위 작업 단위.** `extract_issues`의 work 하나 = 심사평 1건(제목 없음, DISAPERE에 제목이 없다). 50문장 넘는 심사평은 E3가 묶음으로 나눈다(dev 369묶음/358건, 골드 149/148)
3. **리뷰의 generator.** 묶음 하나라도 규칙으로 강등되면 그 리뷰 줄을 `rule`, `status=degraded`로 적는다(E5-L1a 형식). 이번 실행에서는 0건
4. **실패 재시도.** E3 provider는 429·5xx를 한 번만 재시도한다. 평가에서는 실패 묶음이 있던 리뷰만 백오프(15/45/90s) 뒤 최대 3라운드 다시 부른다(성공 묶음은 캐시). 끝까지 실패하면 E3가 이미 넣은 규칙 태그로 남고 rule로 표기
5. **규칙 예측도 E3 비상 경로 그대로.** `rules.make_rule_tagger()`(→ `neumann.index.taxonomy.tag_excerpts`, min_score 2) + `extract.rule_issues`. 규칙 점수는 신뢰도 `min(0.9, 0.4+0.1×점수)`로 들어오므로 같은 격자의 신뢰도 하한이 곧 점수 하한이다
6. **캐시 폴더를 추출기 지문으로 나눔.** E3 캐시 키는 `PROMPT_VERSION`만 보고 지시문 본문은 보지 않는다. 판 번호를 안 올리고 지시문만 바꾸면 옛 응답이 재사용될 수 있어, 평가 캐시는 지시문·스키마 해시 폴더에 둔다
7. **골드 추가 분석 안 함.** "골드는 정확히 1회 채점"을 지키려고 골드로는 `eval.macro_f1` 두 번(astra·rule)만 돌렸다. 대응표본 차이 부트스트랩(astra − 기준선)은 하지 않았다(못 한 것). 위 no_risk 빈 예측 수 등은 그 채점 결과 파일과 예측 파일에서 센 것이다

## 한계 (발표에 같이 적을 것)

1. **라벨 공간 차이.** 골드는 DISAPERE aspect를 매핑한 것이고(§3.1), 제품 택소노미와 뜻이 다르다. dev 문장 라벨로 astra 지적(negative)이 붙은 문장의 DISAPERE aspect를 세어 보면(dev만 사용):
   - R7(322건): `substance`·negative 29%, 극성 없음(none·none) 18%, `soundness`·negative 17%. "다른 데이터셋·조건에서도 보여라"를 제품은 R7(일반화), DISAPERE는 substance(→ R2)로 본다. 골드 R7은 `motivation-impact`(동기·영향)라 뜻이 아예 다르다 → 골드 R7 정밀도 0.13
   - R5(231건): `replicability`·negative 27%뿐, `clarity`(R0, 채점 제외) 24%, `substance` 24%. 구현 세부 누락을 DISAPERE는 명료성 문제로 자주 라벨 → 골드 R5 FP 32
   - R2(909건) 중 8%가 `meaningful-comparison`·negative 문장(골드에선 R6). 제품 경계 규칙("실험이 더 필요하면 R2")과 골드 매핑(비교 누락 → R6)이 다르다
   - 골드 매핑을 그대로 두는 것은 §2.1 규칙 ②(사후 제외 금지)와 E5-L1a 결정 2를 따른 것이다
2. **dev → 골드 하락(0.5553 → 0.4864).** dev는 1인 라벨(리뷰당 코드 평균 1.84), 골드는 2~4인 과반 합의(1.37)라 골드가 더 좁다. astra는 리뷰당 2.46개(dev 2.70)를 내 골드에서 FP가 늘었다(Micro P 0.44). 골드와 같은 합의 조건의 튜닝셋이 없어 dev만으로는 이 차이를 조정할 수 없다(§0.6 그대로 따름)
3. **no_risk에 약함.** 골드 no_risk 35건 중 30건에 코드를 냈다. dev에서 astra 지적이 붙은 문장의 15~22%(코드별)는 주석자가 극성을 주지 않은(none) 문장이다. 지시문이 약점·요청을 넓게 negative로 받게 해서 가벼운 질문·요청도 지적이 되는 것으로 보인다(추정, 지시문 변형으로 확인하지 않음)
4. **1회 실행.** LLM 출력은 호출마다 달라질 수 있다. 같은 캐시로 다시 채점하면 같은 숫자가 나오지만(캐시 518개 보존), 캐시 없이 다시 부르면 조금 다를 수 있다. 반복 실행 분산은 재지 않았다
5. **빈도 기준선과 Micro 구간이 겹친다.** Macro로는 분명히 앞서지만 Micro로는 "안 읽는 기준선보다 낫다"고 말할 수 없다
6. **골드는 ICLR 2019·2020 ML 심사평**이다. AI for Science 분야 심사평에서의 성능은 이 숫자로 보장되지 않는다

## 못 한 것

- 지시문 변형 실험(dev). 결정 1 때문에 제품 지시문만 쟀다. 아래 제안을 E3가 반영하면 dev에서 다시 재야 한다
- astra − 빈도 기준선, astra − 규칙의 대응표본 차이 부트스트랩(§0.4 권고). `eval.macro_f1`에 `--compare`로 붙이면 같은 재표집 인덱스로 가능
- 반복 실행 분산(캐시 없이 2회 이상)

## 제안

- **E3(추출기 지시문)**: ① R7과 R2 경계: "같은 과제에서 데이터셋·실험 추가 요청"과 "다른 조건·분포로의 일반화 요청"을 예문으로 가르기(dev R7 지적의 29%가 DISAPERE substance 문장), ② "비교 대상 누락(다른 방법과 비교 안 함)"을 R2/R6 중 한쪽으로 명확히, ③ 답이 정해진 단순 질문·표현 수정 요청은 지적에서 빼라는 문장(no_risk FP), ④ 지시문을 바꾸면 `PROMPT_VERSION`도 올릴 것(캐시 키가 판 번호만 봄, 결정 6). 단 ①②는 제품 택소노미 자체의 경계라 DISAPERE 점수만 보고 바꾸면 안 된다(PM 판단). 반영하면 이 과제의 `extract --split dev` → `tune`을 다시 돌려 dev에서만 비교하고, 골드는 새 판으로 한 번만 다시 채점하되 이번 숫자와 함께 누적 보고(§6 사후 기준 변경)
- **E5 골드 동결**: 이번 골드 채점은 1회 소진했다. 다음 판을 채점하면 "2회차"로 이번 값과 나란히 적는다
- **E5 리포트 카드**: 위 결과 표를 그대로(사람 상한·빈도 기준선을 먼저). 각주: 제외 클래스 R3·R4·R8·R9, R7 매핑 한계, 1회 실행, dev는 1인 라벨. 재현 명령: `python -m eval.macro_f1 --pred data/eval/pred_astra_gold.jsonl --gold data/eval/disapere_gold.jsonl --out data/eval/score_astra.json`

## verify

```
$ python scripts/verify.py
534 passed, 23 skipped in 14.49s
보안: 파일 217개
계약: 2개
테스트: 통과
verify 통과

$ python -m pytest tests/e5/test_disapere_extract.py -q
16 passed, 1 skipped in 0.32s          (skip 1 = 실제 API, NEUMANN_LIVE_TESTS=1일 때만)

$ NEUMANN_LIVE_TESTS=1 python -m pytest tests/e5/test_disapere_extract.py -q -k live
1 passed, 16 deselected in 8.56s
```

- verify 전체 테스트 수(534)는 E3-L0 병합분을 포함한다. 이 과제 테스트: 오프셋 원문 일치(반복 문장 포함), 본문 해시 불일치 거부, 골드 라벨 미적재, dev 아닌 행 튜닝 거부, 집계(극성·하한·문장 수·R0/R9 제외), 격자 고정·동률 규칙, 실패 재시도·백오프, 끝까지 실패 → rule·degraded, 규칙 태거 impl, 예측 형식 = `eval.macro_f1` 입력, FROZEN 없거나 `--config`면 골드 예측 거부, FROZEN이 사전 격자 안, 추출기 지문이 지시문에 반응

## PM 정정·발표 표기 (검증 반영, 2026-09-30)

- §2의 "dev 추출 전"은 "dev 점수를 보기 전"으로 읽는다(스모크 3건이 10~17초 먼저 돌았다).
- 발표 각주: 추출 지시문은 E3 그대로, 조정한 것은 집계 규칙뿐(사실상 무튜닝), 골드는 1회 채점, 단일 실행. "astra가 빈도 기준선보다 높다"는 **Macro-F1에서만** 성립하고 Micro-F1은 구간이 겹친다. 목표 0.70에는 미달.
- 검증자가 원인 진단용으로 골드를 1인 라벨 기준으로 다시 채점한 값(0.5760)은 분석 전용이며 발표 수치가 아니다.
