# E5-L1a 검증 보고서 (검증자: Claude Sonnet 5.5)

- 대상: 브랜치 `task/E5-L1a` (HEAD `5bc8f7f`, 커밋 3개), worktree `.claude/worktrees/agent-a2929adbae04d9290`, 빌더 claude-opus-5.5
- 방법: 빌더 보고서를 믿지 않고 완료 기준을 직접 실행했다. 골드는 빌더 코드를 쓰지 않고 zip 원본에서 따로 다시 만들어 대조했고, 채점기는 임시 폴더(`%TEMP%\e5v`)에 만든 예측 파일로 손계산과 대조했다. 코드·git은 건드리지 않았다.
- 환경: Windows Python `neumann` venv, `PYTHONPATH="src;."`, `NEUMANN_RAW_DIR`, `NEUMANN_DATA_DIR` 설정.

## 결론

**PASS.** 병합을 막는 결함은 없다. 비차단 권고 2건은 맨 아래에 있다.

## 항목별 결과

| # | 확인 항목 | 실행한 명령 / 방법 | 실제 결과 | 판정 |
|---|---|---|---|---|
| 1a | 골드 건수 148 | zip을 직접 파싱해 다시 계산(`indep_gold.py`), 빌더 `data/eval/*.jsonl`과 비교 | 주석 파일 767, 심사평 506(주석자 수 {1:358, 2:64, 3:55, 4:29}). 골드 148·dev 358, 겹침 0. review_id 집합이 골드·dev 모두 빌더 산출물과 같음 | 통과 |
| 1b | 합의 규칙이 §3.1과 같은가 | `eval/disapere_gold.py` 코드를 §3.1과 줄 단위로 대조 | 매핑(soundness→R1, substance→R2, replicability→R5, originality+meaningful-comparison→R6, motivation-impact→R7), clarity·arg_other·none 제외, `pol_negative`만, 주석자별 합집합, `n//2+1` 과반, 공집합(no_risk) 유지가 §3.1과 일치. 명세와 다른 곳은 resolution 이름 하나(`adjudicator_call` 대신 `majority_vote`)뿐이고 보고서 결정 1에 적혀 있다(규칙은 같음) | 통과 |
| 1c | 골드 전건 독립 대조 | 독립 구현의 골드 라벨과 빌더 골드 라벨 비교 | 골드 148건 라벨 불일치 **0건**, dev 358건도 불일치 0건. 골드 support R1 42·R2 85·R5 15·R6 47·R7 14·R3/R4/R8/R9 0, no_risk 35. 빌더 manifest와 같음 | 통과 |
| 1d | 무작위 5건 원본 직접 대조 | 시드 7로 골드 5건을 뽑아 zip의 주석자별 `pol_negative` 문장·aspect를 손으로 다시 계산 | 5건 모두 빌더 골드와 일치. `SJgxZjtRnX`(4명, 임계 3): R1 2표·R6 2표·R2 1표라 골드 `[]`. `HJg1qgpZTm`(2명): clarity만이라 `[]`. `SyeMmx63FS`(3명, 임계 2): R2 3표·R6 3표·R1 2표·R5 1표라 `[R1,R2,R6]`. `BJlJ-YsaKS`(3명): 전원 R5라 `[R5]`. `BkeVYzOCnm`(2명, 임계 2): R2·R6만 양쪽에 있어 `[R2,R6]`. 주석자별 집합과 득표수도 원본과 같음 | 통과 |
| 1e | 산출물 정합성 | manifest의 건수·sha256을 파일 실제 값과 대조, 골드 `text`·`sentences`를 zip 원문과 대조, 신원 필드 검색 | 두 JSONL 모두 sha256·바이트 수 일치, zip sha256 `39d90749…` 일치. 본문 불일치 0건. `AnonReviewer`·`reviewer` 필드 유출 0건. 골드 파일에 문장별 라벨 없음(채점 전용) | 통과 |
| 2a | 채점기 정의 대 §2.1 | `eval/macro_f1.py` 코드 대조 | P/R/F1 분모 0이면 0. C* = support≥1이고 Macro는 C* 평균. Micro = F1(ΣTP,ΣFP,ΣFN)(R1~R9 전체). support 0 클래스는 자동 제외하고 목록 출력. no_risk 단위 유지. R0은 예측에서 빼고 개수만 보고. 부트스트랩 2000회·시드 20260930·percentile 95% | 통과 |
| 2b | 손계산 대조 | 골드 6건·예측 6건을 임시 폴더에 만들고 `python -m eval.macro_f1` 실행 | 손계산: R1은 P 2/3·R 1이라 F1 0.8, R2 0.5, R5 0, R6 1, R7 0, R3은 FP 1이지만 support 0이라 제외. Macro (0.8+0.5+0+1+0)/5 = **0.46**, Micro TP4·FP3·FN3 → 8/14 = **0.5714**. 출력 Macro 0.4600, Micro 0.5714, 제외 목록 [R3,R4,R8,R9]로 일치 | 통과 |
| 2c | 완벽·전부 오답·빈 예측 | 같은 골드로 예측 3종을 만들어 실행 | 완벽 예측 Macro 1.0000·Micro 1.0000(구간 [1,1]). 전부 오답(TP 0) 0.0000·0.0000. 전부 빈 예측 0.0000이고 R1·R2·R5·R6·R7은 계속 채점 대상 | 통과 |
| 2d | 누락·골드 밖·R0·형식 오류 | 예측에서 u5를 빼고, 골드에 없는 id와 R0을 넣어 실행. 형식 오류 4종 실행 | 누락은 빈 집합으로 채점(Macro 0.4000, Micro 0.4615 = 6/13, 손계산과 일치). `missing 1`, `골드 밖 1(무시)`, `R0 제외 1`이 출력됨. 잘못된 generator·중복 id·Tier-2 코드(`R2.3`)·risk_codes 없음은 각각 오류 메시지와 종료 코드 2 | 통과 |
| 3 | 빈도 기준선 재현 | `python -m eval.baseline_freq --dev … --target …` 후 `python -m eval.macro_f1`(출력은 임시 폴더) | dev 빈도 R2:219, R1:183, R6:137, R5:76, R7:44. 고정 출력 R1·R2·R6. **Macro 0.3308 [0.2980, 0.3623], Micro 0.5379 [0.4871, 0.5861], n=148**. 예측 파일 sha256이 빌더 것(`b85069dd…`)과 바이트 단위로 같고, 저장된 `score_baseline_freq.json`과 수치·구간·시드가 모두 같음 | 통과 |
| 3b | 기준선 독립 계산 | 독립 골드로 손수 P/R/F1(단순 구현)과 sklearn 계산, 다른 시드로 부트스트랩 | R1 F1 0.4421·R2 0.7296·R6 0.4821·R5 0·R7 0 → Macro 0.3308, Micro 0.5379. sklearn도 0.33075·0.53787. 독립 부트스트랩 구간 [0.2979, 0.3608], Micro [0.4877, 0.5865]로 빌더 구간과 사실상 같음 | 통과 |
| 4 | 결과를 보고 규칙을 바꾸지 않았는가 | `git log`, `git diff aa18c23 HEAD -- eval src tests`, 파일 수정 시각 | 순서: `5883c35` 수집기(18:26:42) → `aa18c23` 규칙·채점기·기준선·테스트(18:26:57) → `5bc8f7f` 보고서(18:29:36). 산출 데이터 파일 시각은 18:27:24~18:27:33으로 **규칙 커밋 뒤**. `aa18c23` 이후 `eval/`·`src/`·`tests/` 변경 0줄. 골드는 §3.1 텍스트만으로 내가 다시 구현해도 같은 값이 나오므로 규칙은 명세 그대로다. 한계: 커밋 시각만으로 커밋 전 비공개 실행이 없었다는 증명은 못 한다 | 통과 |
| 5a | 원본·가공본 미커밋(CC BY-NC) | `git ls-tree -r task/E5-L1a`에서 jsonl·zip·data 검색, `.gitignore` 확인 | 커밋된 파일에 jsonl·zip·data 없음(이름에 disapere가 들어간 코드·테스트 3개만). `.gitignore`에 `data/` 있음. 테스트 zip은 직접 지은 문장으로 `tmp_path`에 만듦. 비밀값 패턴 검색 0건 | 통과 |
| 5b | 소유 경로 밖 변경 | `git diff main...task/E5-L1a --stat` | 8개 파일뿐: `eval/{baseline_freq,disapere_gold,macro_f1}.py`, `src/neumann/sources/disapere.py`, `tests/e1/test_disapere.py`, `tests/e5/{test_disapere_gold,test_macro_f1}.py`, `docs/reports/E5-L1a.md`. `contracts/`·`models.py`·`config.py`·`tests/fixtures`·`scripts` 변경 0. 병합 기준(`17a4e13`) 이후 main이 이 경로들을 바꾸지 않아 충돌 없음 | 통과 |
| 6a | pytest | `python -m pytest tests/e5 tests/e1/test_disapere.py -q -rs` | 원본 있음: **44 passed**. `NEUMANN_RAW_DIR` 없이: 42 passed, 2 skipped(원본 필요 테스트 2개, 사유 표시됨) | 통과 |
| 6b | verify | `python scripts/verify.py` | 44 passed, 보안 36개 파일, 계약 2개, 테스트 통과, `verify 통과`. "git 훅이 꺼져 있다" 경고는 worktree 설정 때문이라 빌더 잘못이 아님 | 통과 |
| 7 | 테스트가 항상 통과하는가 | 임시 복사본에 결함을 넣어 테스트가 깨지는지 확인(원본 worktree는 수정 안 함) | 결함 9종 모두 테스트 실패: Macro에 support 0 클래스 포함, 과반 임계 `n//2`, 극성 필터 제거, originality→R7, 누락 예측 건너뜀, Macro 항상 1.0, F1을 precision으로 대체, 기준선 K=2, Micro를 채점 클래스만으로 계산, 시드 변경(`test_defaults_are_prefixed`). 결함 없는 복사본은 44 passed | 통과 |

## 비차단 권고

1. **사람 상한 설명 문구 출처 불명.** `eval/macro_f1.py`의 `REFERENCE_LINES` note와 보고서 참조선 표가 "DISAPERE 4인 라벨 29리뷰, 1명 대 나머지 3명 다수결(leave-one-out)"이라 적는다. 로컬 명세(`04_평가_명세` §1.2)는 0.725 [0.669, 0.772]와 "골드=합의(3인 다수결)"까지만 적고 29리뷰·LOO는 적지 않는다(§3.1의 "4인 라벨 29건"과 짜 맞춘 추정으로 보인다). 이 note는 모든 채점 JSON에 들어간다. 발표 각주로 옮기기 전에 "0.725 [0.669, 0.772], 합의 골드 기준, 외부 실측(04 §1.2)"로 줄이거나 원 출처를 확인한다. 수치 자체는 명세와 같다.
2. **R7 매핑 한계.** 빌더가 결정 2에 적은 대로 `03_risk_taxonomy` §5.1은 motivation-impact→R7 매핑이 부정확해 R7을 DISAPERE로 평가하지 말라고 하지만, 04 §3.1·§2.1 규칙 ②는 R7을 C*에 두라고 한다. 코드는 04를 따랐고 맞는 판단이다. 다만 R7(support 14)이 Macro 분모 5개 중 하나라 점수에 영향이 크다. 리포트 카드에 이 각주를 반드시 넣는다.

## 참고(결함 아님)

- 이 브랜치는 `17a4e13`에서 갈라졌고 main은 그 뒤로 E0/E0b 커밋(`tests/conftest.py` 등)이 더 있다. verify는 브랜치 단독으로만 돌렸으므로 병합 뒤 `python scripts/verify.py`를 한 번 더 돌린다.
- 이 브랜치에는 E1-L1 몫(`src/neumann/sources/disapere.py`)이 들어 있다. 과제 지시문상 E5-L1a 소유이므로 위반은 아니고, E1 담당이 같은 파일을 만들면 병합 때 겹칠 수 있다.
- worktree에는 `.pytest_cache/`(gitignore 대상)가 검증 전부터 있었고, 내가 새로 남긴 파일은 없다. 임시 파일은 `%TEMP%\e5v`에만 만들었다가 지웠다.

## 최종 판정

**PASS**
