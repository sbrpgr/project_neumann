# E5-L2c 보고서 — 백테스트 n=5(진짜 조건만) 판정 준비

빌더: claude-opus-5.5 · 브랜치 `task/E5-L2c` · 기준 결정: `docs/decisions.md` 21:0x(백테스트 n=5, 사전 등록 표본 앞 5편, sol 양쪽, Sonnet 3명 다수결 + 대표 블라인드 판정)

실제 호출 없음. 모든 명령은 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK`는 켜지 않았다. 공유 `data/eval/`의 기본 파일에는 아무것도 쓰지 않았고,
실제 위험 묶음(`riskset_*.sol.first5.jsonl`)은 열거나 건드리지 않았다. 예행 산출물은 전부 세션 임시 폴더(아래 `<임시>`)에 있다.

## 1. 무엇을 했나

실제 파일(`data/eval/riskset_neumann.sol.first5.jsonl`, `data/eval/riskset_baseline_llm.sol.first5.jsonl`)이 나오는 즉시
`build → briefs → (Sonnet 판정자 3명) → validate → aggregate`가 한 번에 돌도록 판정 경로를 고치고, mock 위험 묶음으로 끝까지 예행했다.

### 바뀐 것

| 무엇 | 내용 |
|---|---|
| 판정 폴더 분리 `--judge-dir` | 모든 하위 명령(build·briefs·codex·validate·aggregate)에 같은 값을 준다. `judge_n5` → 판정 폴더 `data/eval/judge_n5/`(봉투·답·지시문·사람 꾸러미), 짝 표 `data/eval/judge_n5_key/pairing.json`(판정 폴더 밖), 결과 `data/eval/judge_n5_results.json`·`.md`. 기본값 `judge`는 옛 경로(`judge_key/`, `judge_results.json`) 그대로 |
| 논문 선택 `--work-ids first5` | 표본 목록이 사전 등록 `list_sha256`과 같은지 확인한 뒤 앞 5편. 봉투·사람 판정 꾸러미·지표가 모두 이 5편이다. 선택은 짝 표에 남아 aggregate가 그대로 쓴다. `firstN`·`reduced`·쉼표 목록도 된다 |
| 진짜 조건만 `--conditions real` | 셔플 행이 있으면 버리고 개수를 알린다. 셔플이 없으면 특이성은 "측정 못 함"(0으로 채우지 않음), 결과 JSON `controls`와 표 머리에 "셔플 대조 없음" 문구 |
| 위험 0개·degraded 행 | 빼지 않는다. 위험 0개 = 적중 0(빈 자리 3칸). 실행 상태 열에 `ok·degraded·error` 수와 "위험 0개 N편"을 적는다. status가 ok가 아닌 논문을 뺀 짝 비교를 **민감도**로 따로 보인다. 모든 시스템이 위험 0개인 논문은 봉투를 만들지 않고(`empty_works`) 적중 0으로 센다 |
| 거부(안전장치) | ① 판정 폴더에 답이 이미 있거나 다른 입력(위험 묶음 sha256·논문·조건)으로 만든 폴더면 build 거부(`--force`로만) ② 누출 검사(`leak_check.leaks > 0`)에 걸린 행이 있으면 거부(사전 고정 규칙) ③ 선택 논문에 위험 묶음 행이 없는 칸이 있으면 거부(`--allow-missing`로만) ④ 시스템별 생성 모델이 다르면 경고 ⑤ 거부는 `[중단] …`로 알리고 종료 코드 2 |
| 블라인드 | 그대로 유지: `blind_violations`(메타데이터·위험 글 금지어) 통과한 봉투만 저장, 짝 표는 판정 폴더 밖, 봉투 안 위험 순서는 `random.Random("20260933|<work_id>")`, 판정자마다 봉투 순서도 따로 섞음. 지시문 금지 목록에 짝 표 폴더(`judge_n5_key`)·사람 판정 폴더(`human`)·결과 파일 추가 |
| 사람 판정 꾸러미 | `--work-ids`가 있으면 그 논문 전부(여기서는 5편, 옛 사전 고정 10편 목록이 아니다). `human/README.md`(시스템 정보 없는 안내), `answers_template.csv` |
| 지표 추가(`backtest_metrics`) | 낸 위험 기준 다수결 A·B·C 개수·비율, 다수결 구성(3명 일치·2:1·모두 다름), status·generator·모델, `controls`, status ok만 민감도. 대표 CSV가 있으면 대표 판정 기준 같은 지표(`human_graded`)와 사람 대 AI 일치 |
| **aggregate 죽는 버그 수정** | 한 시스템이 모든 논문에서 위험 0개면 근거율 분모가 늘 0 → 부트스트랩 값 목록이 비어 `ValueError: 빈 목록`으로 aggregate가 죽었다(예행 A에서 발견). `bootstrap_ci`가 이제 `None`(구간 없음)을 돌려준다. Neumann이 실제 실행에서 전부 실패해도 집계가 된다 |
| 발표 표(`eval/judge_summary.py`) | aggregate가 `<판정 폴더>_results.md`를 쓰고 화면에 찍는다. 결과 JSON 값을 옮기기만 한다. mock·합성 입력이나 가짜 판정이면 맨 위에 **[예행]** |
| 예행 도구(`eval/judge_rehearsal.py`) | `synth-neumann`(논문마다 가짜 위험 3개, generator `synthetic`), `fake-answers`(J1~J3 가짜 답, judge_model `mock-judge-rehearsal`, 위험 글 해시로만 등급 = 짝 표를 읽지 않음). 실제 생성(astra·rule 등)이 든 판정 폴더와 공유 `data/eval/` 바로 아래에는 쓰지 않고, 있는 답은 덮지 않는다 |
| **실행기 예행 격리** | 과제 지시문의 예행 명령 `backtest_run_neumann --provider mock --limit 5 … --out <임시>`를 그대로 돌리면 논문별 결과를 **`data/eval/neumann_runs/real__<논문>.json`에 덮어쓴다** — 지금 돌고 있는 sol 실행이 같은 5편을 같은 경로에 쓴다. 그래서 그대로 돌리지 않고 `--runs-dir`·`--cache-dir`를 추가했다. provider가 mock이면 기본 이름에 `.mock`, 결과 폴더는 `<out 폴더>/neumann_runs.mock`(기본 `neumann_runs` 아님). 기준선에도 `--cache-dir` 추가. 실제 provider의 기본 경로는 그대로 |

### 바꾼 파일

- `eval/judge_run.py` — `--judge-dir`, `resolve_work_ids`, `build_package`(거르기·빈 칸·누출·폴더 보호·사람 꾸러미), `restore`/`human_graded`, CLI
- `eval/judge_envelope.py` — 위험 0개 논문은 봉투 없이 `empty_works`
- `eval/backtest_metrics.py` — 추가 지표, `controls`, 민감도, `bootstrap_ci` 버그 수정
- `eval/judge_summary.py`(새) — 발표 표
- `eval/judge_rehearsal.py`(새) — 예행 도구
- `eval/backtest_run_neumann.py` — `--runs-dir`·`--cache-dir`, `output_paths`(mock 격리)
- `eval/baseline_llm.py` — `--cache-dir`
- `tests/e5/test_judge_n5.py`(새, 11개), `tests/e5/test_judge_rehearsal.py`(새, 3개), `tests/e5/test_backtest_run_neumann.py`(+1개)

## 2. 예행 (mock — 결과 아님)

> 아래 표의 숫자는 전부 **mock 기준선 + mock/합성 Neumann + 가짜 판정 답**으로 만든 예행 값이다. 실제 결과가 아니고 발표에 쓰지 않는다.
> 목적은 경로가 끝까지 돌고 표가 어떻게 나오는지 확인하는 것뿐이다.

공통 환경(PowerShell, worktree에서):

```powershell
$S="<임시>/n5"; $env:NEUMANN_LLM_PROVIDER="mock"; $env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;."
$env:NEUMANN_DATA_DIR="C:/Users/User/Desktop/project_neumann/data"; $env:HF_HUB_OFFLINE="1"; $env:TRANSFORMERS_OFFLINE="1"
$env:NEUMANN_EMBED_MODEL="C:/Users/User/Desktop/노이만_본선자료/공개자료/models/bge-m3"; $py="C:/Users/User/.venvs/neumann/Scripts/python.exe"
```

### 2.1 mock 위험 묶음 만들기

```powershell
& $py -m eval.backtest_run_neumann --limit 5 --provider mock --conditions real --out "$S/riskset_neumann.mock.first5.jsonl" --runs-dir "$S/neumann_runs" --cache-dir "$S/cache"
& $py -m eval.baseline_llm --provider mock --limit 5 --conditions real --out "$S/riskset_baseline_llm.mock.first5.jsonl" --cache-dir "$S/baseline_cache"
```

출력(요약):

```
provider mock · 실행 결과 <임시>\n5\neumann_runs
- [real] researcharcade_hf:VqEE9i6jhE status=degraded generator=none 위험 0 근거통과 0 누출 0 19.35s
- [real] researcharcade_hf:U3PBITXNG6 status=degraded generator=none 위험 0 근거통과 0 누출 0 0.0s
- [real] researcharcade_hf:SFCHv2G33F status=degraded generator=none 위험 0 근거통과 0 누출 0 0.0s
- [real] researcharcade_hf:o1IiiNIoaA status=degraded generator=none 위험 0 근거통과 0 누출 0 0.16s
- [real] researcharcade_hf:ihHeqPLRDk status=degraded generator=none 위험 0 근거통과 0 누출 0 0.0s
{"risksets": 5, "leaks_total": 0}
provider mock · 요청 모델 mock-baseline-v1 · effort medium · 프롬프트 6f376a166bc06829
위험 묶음 5건(조건 ('real',)) · 형식 통과 5 · 0.0s
```

mock Neumann은 이 5편에서 카드 0장(degraded)이다. 그래서 예행을 둘로 나눴다: **A** = 이 mock 출력 그대로(위험 0개 경로), **B** = 합성 Neumann(논문마다 가짜 위험 3개, 마지막 1편 degraded)으로 전체 경로.

### 2.2 예행 A — mock Neumann(위험 0개·degraded) + mock 기준선

```powershell
& $py -m eval.judge_run build --judge-dir "$S/judge_n5_A" --work-ids first5 --conditions real --risksets "$S/riskset_neumann.mock.first5.jsonl" "$S/riskset_baseline_llm.mock.first5.jsonl"
& $py -m eval.judge_run briefs --judge-dir "$S/judge_n5_A"
& $py -m eval.judge_rehearsal fake-answers --judge-dir "$S/judge_n5_A"
& $py -m eval.judge_run validate --judge-dir "$S/judge_n5_A"
& $py -m eval.judge_run aggregate --judge-dir "$S/judge_n5_A"
```

```
봉투 5개 · 위험 15개 · 사람 판정 봉투 5개
논문 5편 · 시스템 ['baseline_llm', 'neumann'] · 조건 ['real']
  baseline_llm/real: 행 5 · 위험 15 · 위험 0개 0 · 상태 {'ok': 5} · 생성 {'mock': 5} · 모델 {'mock-baseline-v1': 5}
  neumann/real: 행 5 · 위험 0 · 위험 0개 5 · 상태 {'degraded': 5} · 생성 {'none': 5} · 모델 {'None': 5}
[알림] 셔플 대조 없음(진짜 조건만 실행): 특이성(진짜 − 셔플)을 측정하지 않았다. 적중이 그 계획서에만 맞는 지적인지는 이 결과로 말할 수 없다.
지시문 3개 → …/judge_n5_A/briefs (J1_b1.md, J2_b1.md, J3_b1.md)
{"fake_answers": 15, "judge_model": "mock-judge-rehearsal", …}
답 15/15 통과 · 누락 0 · 오류 0 · 경고 0
```

수정 전에는 여기서 aggregate가 `ValueError: 빈 목록`(근거율 부트스트랩)으로 죽었다. 수정 뒤 표(**[예행] — 결과 아님**):

| 시스템 | 논문 | 낸 위험 | A 적중 | B 타당 | C 오탐 | 빈 자리 | precision@3 [95% 구간] | hit@3 [95% 구간] | 오탐률 | 근거율 | 실행 상태 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Neumann | 5 | 0 | — | — | — | 15 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 | — | degraded 5 · 위험 0개 5편 |
| 일반 LLM(기준선) | 5 | 15 | 7/15 (47%) | 7/15 (47%) | 1/15 (7%) | 0 | 0.467 [0.200, 0.800] | 0.800 [0.400, 1.000] | 0.067 | 0.000 | ok 5 |

| 지표 | Neumann − 일반 LLM [95% 구간] | 짝 n |
|---|---|---|
| precision@3 | -0.467 [-0.800, -0.200] | 5 |
| hit@3 | -0.800 [-1.000, -0.400] | 5 |
| 오탐률 | -0.067 [-0.200, +0.000] | 5 |
| hit@3 불일치 쌍 | Neumann만 적중 0편 · 일반 LLM만 적중 4편 | 5 |
| 민감도: 두 시스템 모두 status ok인 논문만 precision@3 | — | 0 (뺀 논문 5편) |

확인한 것: 위험 0개 행이 빠지지 않고 적중 0으로 들어간다(빈 자리 15), 근거율은 정의 안 됨(—), 상태 열에 degraded·위험 0개가 보인다.

### 2.3 예행 B — 합성 Neumann(3개씩, 1편 degraded) + mock 기준선 + 가짜 대표 CSV

```powershell
& $py -m eval.judge_rehearsal synth-neumann --work-ids first5 --degraded 1 --out "$S/riskset_neumann.synthetic.first5.jsonl"
& $py -m eval.judge_run build --judge-dir "$S/judge_n5_B" --work-ids first5 --conditions real --risksets "$S/riskset_neumann.synthetic.first5.jsonl" "$S/riskset_baseline_llm.mock.first5.jsonl"
& $py -m eval.judge_run briefs --judge-dir "$S/judge_n5_B"
& $py -m eval.judge_rehearsal fake-answers --judge-dir "$S/judge_n5_B"
& $py -m eval.judge_run validate --judge-dir "$S/judge_n5_B"
& $py <임시>/fake_human.py "$S/judge_n5_B/human/answers_template.csv" "$S/judge_n5_B/human/answers.csv"   # 해시로 채운 가짜 대표 CSV(저장소 밖 임시 스크립트)
& $py -m eval.judge_run aggregate --judge-dir "$S/judge_n5_B" --human "$S/judge_n5_B/human/answers.csv"
```

```
합성 Neumann 위험 묶음 5건(예행용, degraded 1)
봉투 5개 · 위험 30개 · 사람 판정 봉투 5개
  neumann/real: 행 5 · 위험 15 · 위험 0개 0 · 상태 {'ok': 4, 'degraded': 1} · 생성 {'synthetic': 5} · 모델 {'synthetic-rehearsal': 5}
지시문 3개 · {"fake_answers": 15, …} · 답 15/15 통과 · 누락 0 · 오류 0 · 경고 0 · aggregate exit 0
```

발표 표 모양(**[예행] — mock·합성·가짜 판정, 결과 아님**):

| 시스템 | 논문 | 낸 위험 | A 적중 | B 타당 | C 오탐 | 빈 자리 | precision@3 [95% 구간] | hit@3 [95% 구간] | 오탐률 | 근거율 | 실행 상태 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Neumann | 5 | 15 | 4/15 (27%) | 7/15 (47%) | 4/15 (27%) | 0 | 0.267 [0.067, 0.467] | 0.600 [0.200, 1.000] | 0.267 | 0.667 | degraded 1 · ok 4 |
| 일반 LLM(기준선) | 5 | 15 | 7/15 (47%) | 5/15 (33%) | 3/15 (20%) | 0 | 0.467 [0.200, 0.800] | 0.800 [0.400, 1.000] | 0.200 | 0.000 | ok 5 |

| 지표 | Neumann − 일반 LLM [95% 구간] | 짝 n |
|---|---|---|
| precision@3 | -0.200 [-0.467, +0.000] | 5 |
| hit@3 | -0.200 [-0.600, +0.000] | 5 |
| 오탐률 | +0.067 [-0.133, +0.267] | 5 |
| hit@3 불일치 쌍 | Neumann만 적중 0편 · 일반 LLM만 적중 1편 | 5 |
| 민감도: 두 시스템 모두 status ok인 논문만 precision@3 | -0.167 [-0.500, +0.000] | 4 (뺀 논문 1편) |

| 다수결 구성(위험 수) | 3명 일치 | 2:1 | 모두 다름(→B) |
|---|---|---|---|
| Neumann | 3 | 9 | 3 |
| 일반 LLM(기준선) | 7 | 8 | 0 |

판정자 쌍 일치율(가짜 답): J1-J2 0.467 · J1-J3 0.600 · J2-J3 0.500 · 3명 모두 일치 0.333(위험 30개).

대표 판정 기준(가짜 CSV, **[예행]**): Neumann A 5/15 · precision@3 0.333, 일반 LLM A 5/15 · precision@3 0.333, 차이 +0.000 [-0.400, +0.333].
사람 대 AI 다수결: 위험 30개 · 3등급 일치 0.400 · κ 0.077 · A 여부 일치 0.500 · κ(A) -0.098.

실제 표에는 이 밖에 머리 문구(논문 5편·`first5`·조건 real·판정 모델·답 통과 수·**셔플 대조 없음**·작은 n)와 정의가 붙는다
(`data/eval/judge_n5_results.md` 전체를 그대로 슬라이드 원본으로 쓰면 된다).

### 2.4 교차 계산(판정 코드를 쓰지 않고)

답 파일 + 짝 표만 읽는 임시 스크립트로 다수결·A 개수·precision@3·hit@3를 다시 셌다:

```
baseline_llm: 교차 A/B/C {'A': 7, 'C': 3, 'B': 5} p@3 0.4667 hit 0.8000 | 결과 {'A': 7, 'B': 5, 'C': 3} p@3 0.4667 hit 0.8
neumann: 교차 A/B/C {'C': 4, 'A': 4, 'B': 7} p@3 0.2667 hit 0.6000 | 결과 {'A': 4, 'B': 7, 'C': 4} p@3 0.2667 hit 0.6
교차 확인 일치
```

### 2.5 보호 확인

답이 있는 예행 B 폴더를 다시 build:

```
[중단] …\judge_n5_B에 판정 답이 이미 15개 있다(예 ['J1/env_039215fc4773.json', 'J1/env_3b1ca162c804.json']). 다른 --judge-dir을 쓰거나, 의도한 것이면 --force
```

(이 확인 때는 아직 예외 출력이었고, 그 뒤 CLI가 `[중단] …`·종료 코드 2로 알리게 바꿨다. 누출·빈 칸·가짜 답 거부는 테스트로 확인.)

예행 폴더 구성(판정자가 보는 것): `judge_n5_A/envelopes/`(봉투 5 + manifest), `briefs/J1_b1.md·J2_b1.md·J3_b1.md`, `answers/J1..J3/`, `human/`(봉투 5개 .md·.json, `answers_template.csv`, `README.md`). 짝 표는 형제 폴더 `judge_n5_A_key/pairing.json`.

## 3. 실제 실행 명령 (PM, 두 파일이 생기면 바로)

이 브랜치 코드가 필요하다(main 병합 뒤 main 체크아웃에서, 또는 이 worktree에서). 병합 전 main에서 돌리면 `--judge-dir`가 없어 argparse 오류로 멈춘다(아무것도 쓰지 않음).

```powershell
$env:NEUMANN_LLM_PROVIDER="mock"; $env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;."; $env:NEUMANN_DATA_DIR="C:/Users/User/Desktop/project_neumann/data"
$py="C:/Users/User/.venvs/neumann/Scripts/python.exe"; $E="C:/Users/User/Desktop/project_neumann/data/eval"
& $py -m eval.judge_run build --judge-dir judge_n5 --work-ids first5 --conditions real --risksets "$E/riskset_neumann.sol.first5.jsonl" "$E/riskset_baseline_llm.sol.first5.jsonl"
& $py -m eval.judge_run briefs --judge-dir judge_n5
#   (Sonnet 판정자 3명 — 4절)
& $py -m eval.judge_run validate --judge-dir judge_n5
& $py -m eval.judge_run aggregate --judge-dir judge_n5 --human "$E/judge_n5/human/answers.csv"   # 대표 판정이 끝나기 전에는 --human을 뺀다
```

- 판정 단계는 OpenAI를 부르지 않는다(`NEUMANN_LLM_PROVIDER=mock`은 안전을 위해 둔다. `NEUMANN_LIVE_LLM_OK`는 주지 않는다).
- build 출력에서 확인: `봉투 5개`(Neumann이 두 시스템 모두 위험 0개인 논문이 있으면 그만큼 적고 `[알림]`), 시스템별 `상태`·`모델`(둘 다 `gpt-6.1-sol`이어야 한다. 다르면 `[경고]`), `[알림] 셔플 대조 없음`.
- build가 `[중단]`으로 멈추는 경우: 누출 행(그 결과로는 판정하지 않는다 — 실행 쪽 확인), 빠진 칸(Neumann 실행이 5편을 다 못 냈다 — 다시 돌리거나, 알고 진행하려면 `--allow-missing`, 보고서에 적는다), 이미 답이 있는 폴더(새 이름 `--judge-dir judge_n5b`).
- 위험 묶음을 다시 만들어 build를 다시 해야 하면: 판정 답이 아직 없으면 `--force`, 답이 있으면 새 `--judge-dir`.
- 결과: `data/eval/judge_n5_results.json`(sha256 출력), 발표 표 `data/eval/judge_n5_results.md`. 판정 답이 모자라면 aggregate는 표를 쓰되 **미완**으로 적고 종료 코드 1.
- 대표 판정: `data/eval/judge_n5/human/` 안의 `README.md`와 봉투 `.md` 5개를 보고 `answers_template.csv`를 채워 같은 폴더에 `answers.csv`로 저장. AI 답·결과 파일은 판정이 끝날 때까지 열지 않는다.

## 4. Sonnet 판정자 3명 띄우는 법

`briefs`가 판정자마다 지시문 하나(`data/eval/judge_n5/briefs/J1_b1.md`, `J2_b1.md`, `J3_b1.md`, 봉투 5개씩)를 쓴다. PM 세션에서:

1. **한 메시지에서 Agent 호출 3개를 함께** 띄운다(동시에 시작 → 누구도 다른 판정자의 답이 생기기 전에 시작한다). 각 호출: `subagent_type: "general-purpose"`, `model: "sonnet"`, `run_in_background: true`.
2. 프롬프트는 자기 지시문 경로 하나만 준다(시스템 이름·짝 표·다른 판정자 정보를 넣지 않는다):
   - J1: `너는 판정자 J1이다. C:/Users/User/Desktop/project_neumann/data/eval/judge_n5/briefs/J1_b1.md 파일 하나만 먼저 읽고 그 지시를 그대로 따른다. 다른 판정자의 답 폴더, judge_n5_key 폴더, human 폴더, 결과 파일, 저장소 코드는 열지 않는다. 하위 에이전트를 띄우지 않는다.`
   - J2·J3: 위 문장에서 `J1`을 `J2`·`J3`로(지시문 경로 `J2_b1.md`·`J3_b1.md`).
3. 셋이 끝나면 `validate --judge-dir judge_n5` → `답 15/15 통과`여야 한다. 오류·누락이 있는 판정자만 같은 지시문으로 다시 띄운다(다른 판정자의 답은 그대로 둔다).
4. `aggregate` 결과의 `판정 모델`에 실제 Sonnet 모델 id가 찍힌다(가짜면 `[예행]`이 붙는다).

비상 경로(Claude 한도가 없을 때): `& $py -m eval.judge_run codex --judge-dir judge_n5`(기본 dry-run, 실제 실행 `--execute`는 PM 지시로만). 두 경로를 섞지 않는다.

## 5. 테스트·검증

```
& $py -m pytest tests/e5/test_judge_n5.py tests/e5/test_judge_rehearsal.py tests/e5/test_backtest_run_neumann.py -q
19 passed
& $py -m pytest tests/e5 -q
187 passed, 4 skipped
& $py scripts/verify.py
1204 passed, 46 skipped · 보안: 파일 408개 · 계약: 2개 · 테스트: 통과 · verify 통과
```

새 테스트 15개: `test_judge_n5.py` 11개(first5 선택·사전 등록 확인, 폴더 배치, 진짜 조건만 봉투·블라인드·사람 꾸러미 5편, 빈 칸 거부, 폴더 보호, 위험 0개 논문, 셔플 없는 지표 손 계산·민감도·발표 표, 대표 판정 지표, 누출 거부, 모든 값 정의 안 되는 부트스트랩, 지시문),
`test_judge_rehearsal.py` 3개(합성 위험 묶음, 가짜 답 전 경로·실제 생성 폴더 거부·덮지 않음, 공유 data/eval 거부), `test_backtest_run_neumann.py` 1개(mock 출력 경로 격리).

## 6. 결정(스펙이 모호해서 고른 것)

- 짝 표·결과는 판정 폴더의 **형제**(`<이름>_key/`, `<이름>_results.*`)에 둔다. 기본 `judge`에서 옛 경로와 같아진다.
- `--work-ids`를 주면 사람 꾸러미 = 그 논문 전부(대표가 같은 5편을 판정). 안 주면 예전처럼 사전 고정 `human_sample` 10편.
- 위험이 하나도 없는 논문은 봉투를 만들지 않는다(빈 봉투를 판정자에게 주지 않는다). 지표에서는 적중 0.
- 주 지표는 degraded·위험 0개 논문을 빼지 않고, status ok만 비교는 민감도로만 보인다.
- aggregate는 판정 답이 모자라면 종료 코드 1(예전 0). 표는 쓰되 미완으로 적는다.
- 실행기 mock 기본 경로를 바꿨다(`.mock` 이름, `neumann_runs.mock`). 실제 provider 기본 경로는 그대로.

## 7. 못 한 것·다음

- 두 번째 커밋(`b92f0a2`)은 PM 일시정지 지시로 기능별로 쪼개지 못하고 WIP 한 덩어리로 커밋했다.
- 실제 `.sol.first5` 파일로는 돌리지 않았다(지시대로 건드리지 않음). 실제 build에서 모델 경고·빈 칸·누출 여부는 PM이 build 출력으로 확인한다.
- `codex` 비상 경로는 `--judge-dir` 연결만 했고 n5 폴더로 dry-run하지 않았다(단위 테스트는 옛 경로로 통과).
- mock Neumann이 이 5편에서 카드 0장인 이유는 조사하지 않았다(판정 경로와 무관, 예행은 합성 묶음으로 대신).
- 다음: PM이 병합 → 3절 명령 → 4절 판정자 3명 → 대표 CSV → aggregate `--human` → `judge_n5_results.md`를 슬라이드로.
