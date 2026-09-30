# E5-L2a 검증 보고서 (Claude Sonnet 5.5)

- 대상: 브랜치 `task/E5-L2a`(worktree `.claude/worktrees/agent-a41d6f2843ba4657e`, HEAD `fbde145`), 빌더 보고서 `docs/reports/E5-L2a.md`
- 검증일: 2026-09-30. 검증자는 코드·데이터를 고치지 않았다. 재실행은 `%TEMP%\verify_e5l2a\`에서 했다(재현 표본, 시험용 봉투, 변이 시험 복사본). 공유 데이터 폴더는 읽기만 했고, worktree에는 아무것도 남기지 않았다(`git status --short` 비어 있음).
- API 호출 없음. 판정(Claude·Codex) 실행 없음. `codex exec --help`로 플래그 이름만 확인했다.

## 최종 판정: **PASS**

완료 기준 5개와 특별 확인 항목을 직접 재현했고 반증하지 못했다. 병합 전에 고칠 것은 없다. 아래 "권고"는 판정 단계 전에 PM이 알고 있으면 되는 것들이다.

| 핵심 근거 | 값 |
|---|---|
| 규칙 커밋 → 산출 순서 | 규칙 커밋 `8eb01ec` 19:01:48 → 표본 파일 19:01:57 → 계획서 19:02:04 → 기준선 캐시 19:03:07. PM의 강한 층 결정(decisions.md)은 19:00 |
| 표본 재현 | 임시 폴더에 재실행한 `backtest_sample.json`이 공유 폴더 파일과 **바이트 단위로 같음**(file sha256 `574c5387…ac6c`), list sha256 `fdea4d25…905c` |
| 층화 | 내가 따로 짠 코드로 강한 층 810 → 적격 765(거절 457·채택 308) → 30 × 457/765 = 17.92 → 18·12. 표본 집합 일치 |
| 계획서 잔여 패턴 | 05_eval_protocol 원문에서 정규식을 그대로 추출해 검사: **0**(30건). 마스킹 토큰 0, 계획서 = 초록 문장의 부분 열(드롭만) |
| 누출(실색인) | 색인 1128편, hybrid bge-m3+BM25, top-50: 제외 없음 30/30 새어 나옴 → 정규화 제외 **0/30**. 접두어 없는 id만 넣으면 30/30 새어 나옴(B-10 재현) |
| 봉투 블라인드 | 시험 봉투 30개(진짜 기준선 3편 + 흔적을 일부러 넣은 Neumann 형식 위험): 위반 0, 시스템 흔적 0, 짝 표는 봉투 폴더 밖 |
| 다수결·지표 | 손계산·독립 부트스트랩(같은 시드)과 전부 일치. 3명 모두 다르면 B |
| 판정 실제 실행 | 없음(`data/eval`에 judge·answers·pairing·riskset_neumann 없음, Codex 세션 기록에 봉투 0건) |
| 소유 경로 밖 변경 | 없음(21개 파일 전부 `eval/backtest*·judge*·baseline*`, `eval/prompts/baseline_llm.txt`, `tests/e5/test_(backtest|judge)*`, 보고서) |
| verify | 430 passed, 6 skipped · 보안 201 · 계약 2 · `verify 통과`. 실색인 회귀(`NEUMANN_REAL_DATA_TESTS=1`) 8 passed |

## 1. 완료 기준별 실행 결과

| # | 항목 | 실행한 명령 | 실제 출력(핵심) | 판정 |
|---|---|---|---|---|
| 1a | 표본 30편·sha256·층화 재현 | `python -m eval.backtest_sample --out %TEMP%\verify_e5l2a\sample.json` 후 `cmp`와 `sha256sum` | "IDENTICAL". 적격 765편(강도 title 566·multi 199), 모집단 거절 457·채택 308(거절 0.5974), 표본 거절 18·채택 12, 앞 15편 9·6, 셔플 짝 30쌍(같은 분야 30), 사람 판정 10편. list sha256 `fdea4d2514fca5357605660003308e25c036b6640d88b8ada3d2033dd0f2905c`, reduced `fc5bba1a…0779` | 통과 |
| 1b | 독립 재계산(층화·시드) | 내 스크립트: `works/selection/decisions/reviews.jsonl`에서 강도(E1의 `keyword_regex`·`MASK_PHRASES`만 재사용), 채택/거절, 초록 비어 있지 않음, 공식 심사평 ≥3 적용 후 `random.Random(20260930)`로 거절 → 채택 순 `sample` | 강도 {title 600, multi 210, single 318}, 적격 765, 쿼터 18/12, **표본 집합 일치**, 표본 30편 모두 강한 층, list sha256 독립 계산값 일치, reduced sha 일치. 앞 k편 층 비율이 모집단과 1편 안쪽(5→3/2, 10→6/4, 15→9/6, 20→12/8, 25→15/10) | 통과 |
| 1c | 강한 층 810편 기준 | 위와 같음 + `docs/decisions.md` 19:00 항목과 E1-L0 검증 보고서 표 | 600 + 210 = 810, 약한 층(single 318) 표본 0편. 적격 765 = 810 − 심사평 3건 미만 45 | 통과 |
| 1d | 셔플 짝·사람 판정 표본 | 내 스크립트로 시드 20260931·20260932 재현 | 짝 재현 일치, 자기 짝 0, 같은 분야 30/30, 앞 15편 안의 i는 짝 j도 앞 15편, 한 계획서 최대 5회 사용. 사람 10편 재현 일치·모두 앞 15편 | 통과 |
| 1e | 계획서 30건, 잔여 0 | 정규식을 `05_eval_protocol.md`에서 **원문 그대로 추출**(`exec`)해 빌더 정규식과 `pattern`·`flags` 비교, 계획서 30건에 재검사, 초록에서 문장 드롭을 독립 재현 | 정규식 4쌍 동일(URL 추가 규칙 제외). 잔여 NUM+CLAIM+EVID **0**. 30건 모두 "초록 문장 중 패턴 없는 것을 이은 문자열"과 같음(마스킹 아님). `[CLAIM]` 등 토큰 0. 빈 계획서 0. 평균 727.7자, 보존율 0.5397, **400자 미만 7건**(281, 287, 153, 342, 320, 128, 365)이 빌더 보고서와 같음 | 통과 |
| 2 | 누출 0/30, 실색인 직접 재현 | 내 스크립트 `indep_leak.py`: `IndexStore.load(data/index)`, E2 `search(..., exclude_work_ids=..., store=...)`, k=50, 내 정의(접두어 뗀 id ∪ 제목 정규화 ∪ 모든 심사평 본문 해시)로 제외 목록을 독립 계산 | 색인 1128편, 백엔드 hybrid. **제외 없음: 자기 논문이 top-50에 30/30** → **제외 후 0**. 내가 계산한 제외 목록과 빌더 `backtest_exclusions.json`이 30편 모두 **동일**(각 대상 정확히 1편, 사유 id·title·review 각 30). 셔플 짝 30쌍: i와 j 모두 제외 시 top-50에 0. **접두어 없는 id 하나만 넣으면 30/30 새어 나옴**(B-10 재현). 제외 id 전부 색인에 있고 `researcharcade_hf:` 형식 | 통과 |
| 2b | 회귀 테스트가 실제로 검사하는가 | 변이 시험(아래 §3) + `NEUMANN_REAL_DATA_TESTS=1 pytest tests/e5/test_backtest_leakage.py` | 접두어 정규화를 끄면 실패. 실색인 테스트 포함 `8 passed in 20.62s`. 테스트 안에 음성 대조(제외 없으면 자기 논문 1위, 옛 방식이면 새어 나옴)가 있어 항상 통과하지 않음 | 통과 |
| 3a | mock 판정 답으로 전 과정 | 내 스크립트 `e2e_probe.py`: 시험 봉투에 3명 답을 결정적으로 생성 → `load_answers` → `aggregate` → `compute_metrics`. 복원은 내가 짝 표에서 다시 만든 값과 비교 | 검증 9/9. 다수결 손계산 일치(`A,B,C`→B, `C,A,C`→C, `A,A,B`→A). 짝 표 복원 12/12 일치. Neumann 진짜 p@3 손계산 0.1111 = 구현값. 오류 답 8종(누락·중복·잘못된 등급·자리표시 모델·다른 판정자 id·범위 밖 review_no·여러 줄 이유·다른 봉투 id)을 모두 오류로 잡고, "A인데 review_no 없음"은 경고. 답 하나를 지우면 그 봉투만 `incomplete`로 빠짐 | 통과 |
| 3b | 블라인드 | `blind_probe.py`: 실제 기준선 3편 위험 + 시스템 흔적(`[ex_1a2b3c4d]`, `R2`, `(규칙: R2.1)`, `L12-L14`, URL, `researcharcade_hf:ZZZ12345`, 카드 #3, `[근거 1]`)을 넣은 Neumann 형식 위험으로 `judge_run.build` | 봉투 30개, 위반 0. 위험·지시문·루브릭·메타에서 `neumann/baseline/astra/gpt-6/shuffle/system/condition/evidence_ok/plan_work_id/ex_id/URL/R코드/L줄번호` 0건. 봉투 키는 8개로 고정. 봉투 id는 work_id 해시. 위험 배열 순서가 시스템·조건으로 뭉치지 않음(`NrBrNrBr NsBsBsNr…`). 짝 표는 `judge_key/pairing.json`, 봉투 폴더 밖이고 같은 폴더에 두면 `save_envelopes`가 거부. 사람 판정 꾸러미는 진짜 조건 위험만 | 통과 |
| 3c | 지표·부트스트랩 손계산 | 내 스크립트 `indep_metrics.py`: 5편 × 2시스템 × 2조건을 직접 정하고 손으로 계산, 부트스트랩은 `random.Random(20260930)`·`randrange`·`np.percentile`로 독립 구현 | Neumann p@3 0.2667(손 0.2667), hit 0.6, 오탐률 0.3333, 특이성 0.2(짝지은 차이), 근거율 8/14 = 0.5714(분모 = 낸 위험 수, 빈 자리 제외), 기준선 p@3 0.0667·근거율 0, 차이 0.2. **CI 4종 전부 일치**: p@3 (0.0667, 0.4667), 특이성 (0.0667, 0.3333), 차이 (−0.1333, 0.4667), 근거율 (0.2143, 0.9231). 불일치 쌍 3/1. κ(3등급) 손계산 0.36842 = 구현, 이진 κ 0.3333, 일치율 0.625·0.75. 분산 없음이면 `None`(0으로 속이지 않음) | 통과 |
| 4 | 일반 LLM 기준선 astra 3편 | 캐시 3건·위험 묶음 파일 직접 분석(API 호출 없이). 프롬프트 sha 재계산, 문장 수는 내 분할기로 | 프롬프트 버전 `6f376a166bc06829` 재계산 일치. 3편 모두 `status=ok`, 요청·응답 모델 `gpt-6-astra`, 추론 강도 medium, 시도 1회, 위험 **정확히 3개**, 설명 **2문장**씩(내 분할기로도), 자름 0, 제목 19~23자, `evidence_ok` 전부 false(일반 LLM은 원문 근거 없음). 계획서 id 일치. 캐시에 키·헤더·토큰 문자열 없음. 코드가 보내는 것은 프롬프트 파일 + 계획서 본문뿐(코퍼스·검색 없음). 프롬프트에 "이 연구계획서가 심사에서 받을 위험 3개를 구체적으로" 문구 있음 | 통과 |
| 5 | verify·커밋 위생 | `python scripts/verify.py`(브랜치 worktree) | `430 passed, 6 skipped`, 보안 201개 파일, 계약 2개, `verify 통과`. 데이터 파일 커밋 0, 프롬프트 원문 커밋 | 통과 |

## 2. 계약·정직성 확인

| 항목 | 방법 | 결과 |
|---|---|---|
| 소유 경로 밖 변경 | `git diff main...task/E5-L2a --name-only`를 소유 경로 패턴으로 걸러 봄 | 밖의 파일 0. `contracts/`·`src/neumann/models.py` 변경 0줄. 비밀값 패턴(`sk-…`, `Bearer`, `api_key=`) 0 |
| 데이터 산출물 커밋 금지 | 파일 목록 | `.py`·`.txt`·`.md`뿐. 표본·계획서·기준선 결과는 공유 데이터 폴더에만 있음 |
| 사전 고정 순서 | `git reflog`, 파일 mtime, `git diff 8eb01ec HEAD` | 규칙 커밋 뒤 표본·계획서 산출. 규칙 커밋 이후 바뀐 코드는 `stale_exclusions`·봉투 중복 검사·`DEFAULT_RISKSET_FILES`뿐이고 표본·계획서·지표·기준선·위험 묶음 코드(`backtest_sample/plans/common/metrics/riskset`, `baseline_llm`, 프롬프트)는 **바이트 단위로 변경 없음**. reset·amend 없음 |
| 판정을 실제로 돌리지 않았는가 | `data/eval` 전체 검색, `%USERPROFILE%\.codex\sessions` 9/30 18시 이후 기록에서 `judge-envelope-v1`·`judge-answer-v1` 검색 | judge·envelope·pairing·riskset_neumann·전체 기준선 파일 없음(있는 것은 `riskset_baseline_llm.first3.jsonl` 하나). Codex 세션 기록에 봉투 0건. 기준선 API 호출은 캐시 3건뿐 |
| 규칙 결과를 LLM 결과로 표시하지 않는가 | `riskset_from_premortem`, `riskset_from_entry`, 짝 표 | 생성기(`astra`/`rule`/`mixed:`/`mock`)와 status를 위험 묶음과 짝 표에 기록. mock 기준선 출력은 파일 이름에 `.mock`이 붙어 기본 봉투 입력에서 빠짐. 근거율은 `verify_against` 통과만 참(원문이 바뀐 경우·못 찾은 경우 거짓 — 테스트 있음) |
| 판정 실행기가 모델 중립인가 | 코드·`codex exec --help` | 같은 봉투 JSON을 Claude 지시문(`briefs`)과 Codex 명령(`codex`, 기본 dry-run) 둘로 돌림. 플래그(`-m`, `-s`, `-C`, `--skip-git-repo-check`, `--ephemeral`, `--output-schema`, `-o`)가 실제 CLI에 있음. 모델 `gpt-6-sol`, 강도 high, read-only는 §5.7과 같음. `--execute` 없이는 실행하지 않음 |
| 인용 정직성 | 이 과제는 인용을 새로 만들지 않음(근거율만 계산) | 해당 없음. 근거율 조작 입력 테스트 통과(§3 참고) |

## 3. 항상 통과하는 테스트가 없는지: 변이 시험

복사본(`%TEMP%\verify_e5l2a\mut\`)의 코드를 바꿔 `pytest tests/e5 -k "backtest or judge"`를 돌렸다. worktree는 건드리지 않았다.

| # | 변이 | 결과 |
|---|---|---|
| M1 | id 정규화에서 접두어 떼기 제거 | 실패(`test_normalize_work_id_prefix_namespace_url`) |
| M2 | 다수결에서 3명 모두 다르면 B 대신 최빈 첫 표 | 실패(`test_majority_rule`) |
| M3 | `residual_hits`가 항상 0 | 실패(`test_residual_check_really_detects`) |
| M4 | `blind_violations`가 항상 빈 목록 | 실패(`test_blind_violations_really_detect`) |
| M5 | p@3 분모를 채워진 자리 수로 | 실패(`test_per_plan_scores_missing_slot_not_a`) |
| M8 | `blind_text`가 아무것도 안 지움 | 실패(`test_blind_text_strips_system_traces`) |
| M6 | 표본 추출 층 순서 바꿈 | **통과(잡히지 않음)** |
| M7 | 표본 시드 20260930 → 20260929 | **통과(잡히지 않음)** |

M6·M7은 단위 테스트가 시드와 골든 list sha256을 고정하지 않는다는 뜻이다. 실제 표본은 공유 파일의 sha256 잠금(`save_sample`이 목록이 다르면 덮어쓰기를 거부)과 내 독립 재현으로 보호되므로 이번 판정에는 영향이 없다.

## 4. 권고(병합을 막지 않음)

1. **판정 전 완전성 확인.** `judge_run build`는 논문에 위험 묶음이 없어도 위험 0개짜리 봉투를 조용히 만든다(시험에서 3편만 있는 입력으로 봉투 30개 중 27개가 위험 0개). 전체 실행 뒤 `build` 요약이 "봉투 30개 · 위험 360개"(30 × 12, 시스템 실패 시 그보다 적음)인지 PM이 확인한다.
2. **격리는 지시문으로만 한다.** 지시문이 `judge_key`라는 폴더 이름을 밝히고, 짝 표(`data/eval/judge_key/pairing.json`)와 위험 묶음 파일이 서브에이전트가 읽을 수 있는 같은 트리 아래에 있다. 봉투 경로에 `project_neumann`이 보이는 것은 시스템 정보는 아니다. 빌더 보고서의 제안대로 판정 직전에 짝 표를 다른 위치로 옮기면 더 강해진다.
3. **결과 파일 기록.** `judge_results.json`에 판정자 모델 id(답 파일의 `judge_model`)와 위험 묶음의 생성기·강등 수가 들어가지 않는다(`graded`에는 status만 있음). §3.2 교훈 1과 `decisions.md` 19:16("규칙 카드 k/N 포함")에 필요하므로, 리포트 카드 취합(E5-L3)에서 짝 표의 `generator`를 함께 읽는다.
4. **민감도 분석 23편.** `aggregate --work-ids`는 `reduced` 또는 명시한 id 목록만 받는다. 400자 미만 7편을 뺀 23편은 `backtest_plans_summary.json`의 `under_400_work_ids`를 뺀 id 목록을 넘기면 된다. 이 계산은 아직 돌리지 않았다.
5. **Neumann 쪽은 실전 검증 전이다.** E3 `run_premortem`이 main에 없어 `backtest_run_neumann`은 가짜 파이프라인으로만 시험됐다(빌더가 밝힘). 실제 Neumann 위험 글로 만든 봉투가 `blind_violations`를 통과하는지는 첫 실행에서 봐야 한다(위반이면 `build`가 멈춘다). 시험 봉투에서 "유사 연구 …에서 지적됨" 같은 서술은 지워지지 않고 남았다. 그런 문장이 Neumann 글의 습관이면 판정자가 시스템을 짐작할 수 있다.
6. **계획서의 의미 잔여.** 정규식 3종은 통과하지만 몇 편에 결과 암시가 남았다(예: `otXB6odSG8`의 "dramatically reduces the computational burden", `plAiJUFNja`의 "potentially revolutionizing…"). 3단 사람 검증을 하지 않은 것은 빌더가 밝혔다. 리포트 카드 조건에 "정규식 2단까지"임을 적는다.
7. 표본 단위 테스트에 시드·list sha256 고정 테스트를 하나 추가하면 M6·M7이 잡힌다(시간이 남을 때).

## 5. 재현 방법

`_COMMON.md`의 환경변수로(`PYTHONPATH="src;."`) 다음을 실행했다.

- 표본: `python -m eval.backtest_sample --out %TEMP%\verify_e5l2a\sample.json` → 공유 파일과 `cmp`
- 독립 스크립트(모두 `%TEMP%\verify_e5l2a\`): `indep_sample.py`(층화·시드·sha), `indep_plans.py`(정규식·잔여·드롭), `indep_leak.py`(실색인 누출 0/30, 제외 목록 독립 계산, 셔플, B-10), `indep_metrics.py`(지표·부트스트랩·κ·다수결), `blind_probe.py`(봉투·블라인드·지시문·Codex dry-run), `e2e_probe.py`(답 검증·다수결·복원)
- `python -m pytest tests/e5 -q -k "backtest or judge" -p no:cacheprovider` → `52 passed, 2 skipped`
- `NEUMANN_REAL_DATA_TESTS=1 python -m pytest tests/e5/test_backtest_leakage.py` → `8 passed`
- `python scripts/verify.py` → `430 passed, 6 skipped`, `verify 통과`
