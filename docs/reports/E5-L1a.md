# E5-L1a 보고서: DISAPERE 골드와 Macro-F1 채점기 (E1-L1 DISAPERE 수집 포함)

- 브랜치: `task/E5-L1a` · 빌더: claude-opus-5.5 · 검증 예정: Claude Sonnet 5.5
- 스펙: `docs/tasks/E5-L1a.md`, 규칙 원본: `04_평가_명세` §0.6·§2.1·§3.1 (사전 고정)

## 무엇을 했나

1. **수집기** `src/neumann/sources/disapere.py`: `DISAPERE.zip`을 읽기만 해서 심사평 단위 `Review`(문장, 본문, 본문 sha256, OpenReview URL, 주석자별 문장 라벨)를 돌려준다. 심사위원 신원 필드(`metadata.reviewer`)는 읽지 않는다. 주석자마다 문장 분할이 다르거나 같은 주석자 파일이 두 개면 오류를 낸다.
2. **골드 구성** `eval/disapere_gold.py`: §3.1 규칙 그대로. 2명 이상이 라벨한 심사평 **148건 → 골드**, 1명만 라벨한 **358건 → 튜닝(dev)**. 공유 데이터 폴더에 JSONL 2개와 manifest(건수·sha256)를 쓴다.
3. **채점기** `eval/macro_f1.py`: 클래스별 P/R/F1, Macro-F1, Micro-F1, n, 부트스트랩 95% 구간(2,000회, 시드 20260930). 골드 support 0 클래스는 자동 제외하고 목록을 출력에 적는다.
4. **빈도 기준선** `eval/baseline_freq.py`: 심사평을 읽지 않고, dev에서 센 최빈 Tier-1 코드 3개를 항상 낸다. 채점까지 했다(아래 수치).
5. **사전 고정 순서**: 규칙과 테스트를 먼저 커밋(`aa18c23`)하고, 그 다음에 골드를 만들고 기준선을 채점했다. 결과를 본 뒤에 바꾼 규칙은 없다.

### 고정한 규칙 (코드 = `eval/disapere_gold.py`, `eval/macro_f1.py`, `eval/baseline_freq.py`)

| 항목 | 값 |
|---|---|
| 매핑 | soundness-correctness→R1, substance→R2, replicability→R5, originality·meaningful-comparison→R6(합집합), motivation-impact→R7. clarity(R0, 표시 전용)·arg_other·none은 제외 |
| 채택 필터 | `polarity == "pol_negative"` 문장만 |
| 주석자별 집합 | 부정 문장의 매핑 코드 합집합(리뷰 단위) |
| 합의 | n명 중 `n//2+1`명 이상이 준 코드(2명→2, 3명→2, 4명→3). 공집합(no_risk)도 골드로 남김 |
| 채점 클래스 | C* = 골드 support ≥ 1. Macro = C* 평균 F1. Micro = R1~R9 전체 ΣTP·ΣFP·ΣFN (제외 클래스의 FP 포함) |
| 분모 0 | P·R·F1 모두 0. 골드에 라벨이 하나도 없으면 Macro는 0이 아니라 `null` |
| 구간 | 심사평 재표집 2,000회, `random.Random(20260930)`, percentile(정렬 후 50번째·1949번째), 재표집마다 C* 재계산 |
| 빈도 기준선 | dev에서 코드별 심사평 수를 세어 상위 3개. 동률은 코드 이름순. 골드 라벨은 읽지 않음 |

## 완료 기준별 결과

### 1. 골드 건수 148

```
PS> $env:PYTHONPATH='src;.'; $env:NEUMANN_RAW_DIR='C:/Users/User/Desktop/노이만_본선자료/공개자료'; $env:NEUMANN_DATA_DIR='C:/Users/User/Desktop/project_neumann/data'
PS> python -m eval.disapere_gold
원본: C:\Users\User\Desktop\노이만_본선자료\공개자료\data\disapere\DISAPERE.zip (sha256 39d90749db64…, 주석 파일 767개, 심사평 506건)
골드 148건 (주석자 수별 {2: 64, 3: 55, 4: 29}, 해결 {'agreed': 22, 'majority_vote': 126}, no_risk 35)
튜닝(dev) 358건 (no_risk 44)
  C:\Users\User\Desktop\project_neumann\data\eval\disapere_gold.jsonl: n=148 sha256=ad25cb4ad5759350a3c5383f6fcdcc7c7daaf15ed88256815c4a109e55f6b74c
  C:\Users\User\Desktop\project_neumann\data\eval\disapere_dev.jsonl: n=358 sha256=befdfd00097c2fe10fdf4606a3e1a99e44da0f5fdb89f3a65a8a53af8c72c470
  C:\Users\User\Desktop\project_neumann\data\eval\disapere_manifest.json
```

- 148건, 스펙과 같다. 다시 실행해도 두 JSONL의 sha256이 같다(결정적).
- 골드 support: R1 42 · R2 85 · R5 15 · R6 47 · R7 14 · R3/R4/R8/R9 0. dev support: R1 183 · R2 219 · R5 76 · R6 137 · R7 44.
- 정합성 확인: 골드 support가 `04_평가_명세` §3.2에 적힌 옛 골드의 클래스별 support(42/85/15/47/14)와 정확히 같다. 이 규칙을 따로 다시 구현했는데도 같은 골드가 나왔다는 뜻이다. 옛 숫자를 발표에 쓰자는 뜻은 아니다.
- 원본 zip: 3,050,876 B, sha256 `39d90749db64904fab001c7defd86bfbd08dfa572c38c3e5ef19b25585f5523e`, 받은 시각(파일 수정 시각) 2026-09-28T19:26:08+09:00.

### 2. 채점기 단위 테스트

`tests/e5/test_macro_f1.py`(19개), `tests/e5/test_disapere_gold.py`(16개), `tests/e1/test_disapere.py`(9개). 손 계산 예제: Macro = (1 + 2/3 + 0)/3 = 5/9, Micro = 0.5, R3는 FP 1이지만 support 0이라 Macro에서 제외. 완벽 예측은 1.0(구간 [1.0, 1.0]), 전부 오답은 0.0, 빈 예측은 0.0이고 골드에 있는 클래스는 그대로 채점 대상. no_risk 단위의 FP 반영, 누락 예측을 빈 집합으로 채점, 골드 밖 예측 무시, R0 제외, 형식 오류 6종, 중복 id, CLI 전체 흐름, 시드 재현성도 검사한다.

```
$ python -m pytest tests/e5 tests/e1/test_disapere.py -q -rs      (NEUMANN_RAW_DIR 설정)
............................................                             [100%]
44 passed in 0.54s

$ (NEUMANN_RAW_DIR 없이) python -m pytest tests/e5 tests/e1/test_disapere.py -q -rs
...............s...........................s                             [100%]
SKIPPED [1] tests\e5\test_disapere_gold.py:222: DISAPERE.zip 원본 없음(NEUMANN_RAW_DIR)
SKIPPED [1] tests\e1\test_disapere.py:165: DISAPERE.zip 원본 없음(NEUMANN_RAW_DIR)
42 passed, 2 skipped in 0.25s
```

원본이 있을 때만 도는 테스트 2개: 주석 파일 767 · 심사평 506 · 주석자 수 분포 {1: 358, 2: 64, 3: 55, 4: 29}, 골드 148 · dev 358 · 서로 겹치지 않음 · 골드에 R3/R4/R8/R9 없음.

### 3. 빈도 기준선 Macro-F1과 구간 (참조선)

```
PS> $D='C:/Users/User/Desktop/project_neumann/data/eval'
PS> python -m eval.baseline_freq --dev "$D/disapere_dev.jsonl" --target "$D/disapere_gold.jsonl" --out "$D/pred_baseline_freq.jsonl"
dev 358건 빈도(심사평 수): R2:219, R1:183, R6:137, R5:76, R7:44
고정 출력 top-3: ['R1', 'R2', 'R6'] → 148건 C:\Users\User\Desktop\project_neumann\data\eval\pred_baseline_freq.jsonl

PS> python -m eval.macro_f1 --pred "$D/pred_baseline_freq.jsonl" --gold "$D/disapere_gold.jsonl" --out "$D/score_baseline_freq.json"
클래스  support   TP   FP   FN      P      R     F1  채점
R1           42   42  106    0 0.2838 1.0000 0.4421  O
R2           85   85   63    0 0.5743 1.0000 0.7296  O
R3            0    0    0    0 0.0000 0.0000 0.0000  제외
R4            0    0    0    0 0.0000 0.0000 0.0000  제외
R5           15    0    0   15 0.0000 0.0000 0.0000  O
R6           47   47  101    0 0.3176 1.0000 0.4821  O
R7           14    0    0   14 0.0000 0.0000 0.0000  O
R8            0    0    0    0 0.0000 0.0000 0.0000  제외
R9            0    0    0    0 0.0000 0.0000 0.0000  제외
Macro-F1 0.3308 [95% 0.2980, 0.3623]  Micro-F1 0.5379 [95% 0.4871, 0.5861]  n=148
채점 클래스 ['R1', 'R2', 'R5', 'R6', 'R7']  제외(골드 support 0) ['R3', 'R4', 'R8', 'R9']
예측: 채점 148 · 없음 0(빈 예측으로 채점) · 골드 밖 0(무시) · 빈 집합 0 · R0 제외 0 · generator {'baseline': 148}
```

| 참조선 | Macro-F1 [95%] | Micro-F1 [95%] | n |
|---|---|---|---|
| **빈도 기준선(안 읽음, dev 최빈 3코드 R1·R2·R6)** — 이번 측정 | **0.3308 [0.2980, 0.3623]** | **0.5379 [0.4871, 0.5861]** | 148 |
| 사람 간 상한(합의 골드), `04_평가_명세` §1.2, 외부 실측 | 0.725 [0.669, 0.772] | — | 29리뷰 LOO |

- Micro P 0.3919 · R 0.8571 (ΣTP 174 · ΣFP 270 · ΣFN 29). 골드 no_risk 35건에서 기준선은 전부 FP를 낸다.
- **함정**: 안 읽는 기준선의 Micro-F1(0.5379)이 높다. 흔한 클래스(R2)를 늘 맞히기 때문이다. 시스템 비교는 Macro·Micro를 같이 싣고, 이 기준선을 나란히 둔다(§2.1 규칙 ④, §6).
- 이 Micro 0.5379는 §2.1 "함정 참고치"에 적힌 옛 최빈 3코드 Micro-F1과 같은 값이다. 정합성 확인일 뿐, 발표 숫자는 이번 측정값만 쓴다.

### 4. 테스트·verify 통과, 원본·가공본 미커밋

```
$ python scripts/verify.py
............................................                             [100%]
44 passed in 0.55s
보안: 파일 36개
주의: git 훅이 꺼져 있다. 켜려면  git config core.hooksPath .githooks
계약: 2개
테스트: 통과
verify 통과
```

- DISAPERE 원본·가공본(JSONL, manifest, 예측, 점수)은 모두 공유 데이터 폴더 `C:/Users/User/Desktop/project_neumann/data/eval/`에만 있다. 저장소에 커밋한 것은 코드·테스트·이 보고서뿐이다. 테스트 zip은 직접 지은 문장으로 `tmp_path`에 만든다.
- verify의 "훅이 꺼져 있다" 경고: 이 worktree의 `core.hooksPath`가 main의 `.githooks` 절대 경로라서 나온다. 커밋 때 pre-commit·commit-msg 훅은 실제로 돌았다(`보안(스테이징)… verify 통과`). 설정은 PM 소관이라 고치지 않았다.

## 예측 JSONL 형식 (E3 전달용)

한 줄에 심사평 1건.

```json
{"review_id": "B1eHFc49nm", "risk_codes": ["R1", "R2"], "generator": "astra"}
```

| 필드 | 필수 | 규칙 |
|---|---|---|
| `review_id` | O | DISAPERE review_id(= 골드 파일의 `review_id`). 파일 안에서 중복되면 오류 |
| `risk_codes` | O | `R0`~`R9` 문자열 목록. 지적이 없으면 `[]`(no_risk). `R0`은 채점에서 빼고 개수만 보고한다. Tier-2(`R2.3` 등)나 그 밖의 값은 오류 |
| `generator` | O | `astra` · `rule` · `mock` · `baseline` 중 하나. 비상 규칙으로 강등된 심사평은 그 줄을 `rule`로 적는다. 채점 출력에 `generator_counts`로 나온다 |
| 그 밖의 필드 | 선택 | 무시한다(`status`, `model`, `latency_s` 등은 자유롭게 넣어도 된다) |

- 골드에 있는데 예측이 없는 심사평은 **빈 예측으로 채점**한다(점수가 깎인다). 출력의 `predictions.missing`·`missing_ids`에 남는다.
- 골드에 없는 review_id(dev 예측 등)는 채점하지 않고 `extra_ignored`로 개수만 센다. dev와 골드를 한 파일에 넣어도 된다.
- **E3에 권고(골드 정의와 맞추려면)**: 심사평의 문장별 추출 결과 중 **부정(지적) 극성인 것의 risk_code 합집합**을 그 심사평의 `risk_codes`로 낸다. 골드는 `pol_negative` 문장만 센다.
- 입력: 골드 파일 줄마다 `sentences`(DISAPERE 문장 분할)와 `text`(문장+원래 공백을 이은 본문), `text_sha256`, 출처(`source.review_url` 등)가 있다. 골드 파일에는 문장별 라벨이 없다. 튜닝과 프롬프트 예시는 `disapere_dev.jsonl`(문장별 `sentence_labels` 포함)만 쓴다. **골드는 채점에만 쓴다**(§0.6).
- 실행: `python -m eval.macro_f1 --pred <예측.jsonl> --gold C:/Users/User/Desktop/project_neumann/data/eval/disapere_gold.jsonl --out <결과.json>`. astra와 비상 규칙은 파일을 나눠 따로 채점하면 §3 L1의 "나눠 보고"가 된다.

## 바꾼 파일

- `src/neumann/sources/disapere.py` (새 파일)
- `eval/disapere_gold.py`, `eval/macro_f1.py`, `eval/baseline_freq.py` (새 파일, `eval/__init__.py`는 손대지 않음)
- `tests/e1/test_disapere.py`, `tests/e5/test_macro_f1.py`, `tests/e5/test_disapere_gold.py` (새 파일, `__init__.py` 없음: 파일 이름이 겹치지 않게 지음)
- `docs/reports/E5-L1a.md` (이 보고서)

## 결정 (스펙이 모호해서 고른 것)

1. **resolution 이름**: §3.1은 불일치 건을 `adjudicator_call`이라 부르지만 사람 조정은 없고 임계값 계산뿐이다. 오해를 막으려고 `majority_vote`로 적었다(전원 일치는 `agreed`). 규칙 자체는 같다.
2. **R7 유지**: `03_risk_taxonomy` §5.1은 motivation-impact→R7 매핑이 부정확하다고 적었다. 하지만 이 과제의 기준인 `04_평가_명세` §3.1이 R7을 넣고, §2.1 규칙 ②가 사후 제외를 금지하므로 C*에 그대로 둔다. R7 점수는 이 매핑 한계와 함께 읽어야 한다(PM 확인 권장).
3. **극성 필터는 `pol_negative`만**: `03_risk_taxonomy` §5.0은 "negative 또는 arg_request"를 지적문장으로 셌지만, §3.1이 `pol_negative`만이라고 명시하므로 그것을 따른다.
4. **부트스트랩에서 C* 재계산**: `05_eval_protocol` §2.4 참조 구현처럼 재표집마다 C*를 다시 정한다(규칙 ①과 일관). C*가 비어 값이 정의되지 않는 재표집은 뺀다(이번 실행은 2000/2000 모두 정의됨, `n_defined`로 출력).
5. **generator에 `baseline` 추가**: 스펙은 rule/astra/mock만 적었지만, 빈도 기준선을 `rule`로 적으면 비상 규칙 경로와 섞인다. 그래서 따로 `baseline`을 둔다.
6. **누락 예측 = 빈 집합**: 누락을 빼고 채점하면 n이 줄어 점수가 부풀 수 있다. 빈 집합으로 벌점을 주고 누락 수를 보고한다.
7. **빈도 기준선 K=3, dev에서만**: §0.2("가장 흔한 위험 3개")와 §2.1("최빈 3코드 고정 출력")을 따랐다. 골드 빈도를 쓰면 골드를 튜닝에 쓴 셈이라 dev만 쓴다. 다른 K는 돌리지 않았다.
8. **접근 시각**: zip은 미리 받아 둔 공개자료라 현장에서 다시 받지 않았다. 레코드의 `retrieved_at`은 zip 파일의 수정 시각(2026-09-28T19:26:08+09:00)이고, 원본 해시(zip·파일별 sha256)를 같이 남긴다.
9. **골드 파일에 본문 포함**: E3가 같은 심사평으로 예측해야 하므로 골드 JSONL에 `sentences`·`text`를 넣었다(공유 데이터 폴더에만 있음). 채점 전용이라 문장별 라벨은 넣지 않았다.
10. **models.py 미사용**: 지시대로 레코드와 예측 형식을 자기 모듈 안에 정의했다. main의 `Generator(astra/rule/mock)`, `RiskCode(R0~R9)`와 값은 맞춘다.

## 못 한 것

- 규칙 단독(빌드 L0), 규칙 + astra(빌드 L1) 예측은 이 과제 범위 밖이다. E3의 추출기가 생기면 위 형식으로 넣어 채점한다.
- 시스템 간 대응표본 차이 부트스트랩(예: astra − 빈도 기준선)은 만들지 않았다. §0.4는 백테스트 비교에 요구한다. Macro-F1 비교에도 필요하면 `eval.macro_f1`에 `--compare`로 붙이면 된다(같은 재표집 인덱스 재사용).
- 자체 미니 라벨링(§5 결정 3)은 하지 않았다(선택 사항).

## 다음 과제에 넘길 것 / 제안

- **E3**: 위 예측 형식. astra 결과와 비상 규칙 결과는 파일을 나눠 채점한다. 튜닝은 `disapere_dev.jsonl`만 쓴다.
- **E5 리포트 카드**: 빈도 기준선 Macro 0.3308 [0.2980, 0.3623] · Micro 0.5379 [0.4871, 0.5861] (n=148)와 사람 상한 0.725를 참조선으로 먼저 싣는다. 제외 클래스(R3·R4·R8·R9)와 R7 매핑 한계를 각주로 단다.
- **PM**: `_COMMON.md`의 `PYTHONPATH="src:."`는 Windows 파이썬에서 안 먹는다(Git Bash에서 `ModuleNotFoundError: neumann`). PowerShell에서 `$env:PYTHONPATH='src;.'`로 돌렸다. pytest는 `pyproject.toml`의 `pythonpath` 덕분에 영향이 없다.
- **PM**: 이 브랜치에는 E1-L1 몫(`src/neumann/sources/disapere.py`, `tests/e1/test_disapere.py`)이 들어 있다. E1 담당과 파일이 겹치지 않는지 병합할 때 확인한다.
