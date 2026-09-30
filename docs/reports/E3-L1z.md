# E3-L1z 보고서 — 규칙 판정(비상 경로) 한국어 조사·"~인지" 오탐 정리

- 빌더: claude-opus-5.5 · 브랜치 `task/E3-L1z` (worktree `.claude/worktrees/s2-E3-L1z`, 기준 main `4cbf0f0`)
- 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK`·`NEUMANN_LIVE_TESTS` 미설정. 실제 OpenAI 호출 0회. `.env` 열지 않음. stash 안 씀.
- PM 추가 범위(작업 중 지시): main(`c8ba766`, E3-L1y 병합본) 병합 뒤 병렬 파이프라인 status 합치기 검사 → §7.

## 1. 무엇을 했나

`src/neumann/analyze/fitness.py`의 **분야(field) 표지만** 고쳤다. 판정(fit·unfit·uncertain), 요소 줄 번호, 무관 표지, 사유, 강등 표기는 그대로다(§3에서 main과 대조).

1. **`~인지 과제`·`~인지 기능` 오탐.** `_NEURO_KO`의 인지 복합어를 두 갈래로 나눴다.
   - 띄어 쓴 `인지 과제·기능·능력·부하·저하·장애·심리·과학`: `(?:(?<![가-힣])|(?<=사회|경도|신경|시각|청각|공간|언어|정서|메타))인지\s…` — "인지"가 낱말 첫머리이거나 인지 접두어 바로 뒤일 때만. 접두어 목록은 검증 발견 A(§9)로 더했다.
   - 붙여 쓴 `인지과제`·`인지장애`…: `인지(?:과학|과제|…)` — 앞 글자와 상관없이.
   - 지시문의 "앞에 `(?<![가-힣])`만 붙이면 된다"를 그대로 하면 `경도인지장애`(경도 인지 장애, MCI)·`사회인지기능`·`시각인지과제` 같은 **붙여 쓴 진짜 신경과학 복합어가 빠진다**(기존 정답 사례 회귀, §5 변이 M5가 잡음). 어미 `-ㄴ지` 뒤에 명사를 띄어 쓰지 않고 붙이는 일은 맞춤법상 드물어서 붙여 쓴 쪽은 그대로 잡았다.
2. **영어 약어 + 한글 조사.** 분야 영어 표지를 새 `_en_ascii`로 만든다. 경계는 `(?i)(?<![a-z0-9])(?:…)(?![a-z0-9])`(로마자·숫자만 봄)이고, 낱말 안 반복은 `\w*` 대신 `[a-z0-9]*`로 바꿔 뒤에 붙은 조사가 표지 문자열에 들어가지 않는다(`neuroimaging을` → `neuroimaging`). 8개 분야 영어 패턴 전부(신경과학 `_NEURO_EN` 포함)에 적용했다.
   - **요소·무관 사전(`_LEXICON`, `_OFFTOPIC_EN`)은 `\b` 그대로 뒀다.** 이 사전은 판정과 요소 줄 번호를 정한다. 같이 바꾸면 이번 코퍼스 251건 중 184건에서 분야 밖 반환값이 달라지고 42건은 판정이 바뀐다(§4 M4). 과제 요건("분야를 뺀 반환값이 main과 같아야 한다")과 맞지 않아 뒀다(결정 §6-1).
3. **AI 용어.** `neuro(?!morphic|[-\s]?symbolic)[a-z0-9]*`. 지시문 `-?symbolic`에 공백(`neuro symbolic`)도 더했다.

### 고친 오탐 전후 예시 (`rule_fitness`의 분야, 괄호는 신경과학 표지로 잡힌 말)

| 입력 | 전(main 4cbf0f0) | 후 |
|---|---|---|
| 효과적인지 과제별로 검증한다. | 신경과학·뇌영상 (`인지 과제`) | 없음 |
| 나은 것인지 기능 단위로 분해한다. | 신경과학·뇌영상 (`인지 기능`) | 없음 |
| 타당한 설계인지 부하 시험으로 확인한다. | 신경과학·뇌영상 (`인지 부하`) | 없음 |
| neuromorphic hardware accelerator에 올린다. | 신경과학·뇌영상 (`neuromorphic`) | 없음 |
| neuro-symbolic reasoning으로 규칙을 배운다. | 신경과학·뇌영상 (`neuro`) | 없음 |
| neuro symbolic 모델과 비교한다. | 신경과학·뇌영상 (`neuro`) | 없음 |
| EEG와 fMRI로 작업기억 과제 중 신호를 기록한다. | 없음(놓침) | 신경과학·뇌영상 (`eeg, fmri`) |
| DNA와 RNA를 시퀀싱해 발현량을 잰다. | 없음(놓침) | 생명과학·생물정보 |
| LLM으로 초록을 요약하고 NLP를 적용한다. | 없음(놓침) | 자연어처리 |
| x-ray로 찍은 흉부 사진을 쓴다. | 없음(놓침) | 의료·의료영상 |
| 경도인지장애 환자의 기억 검사 점수를 본다. | 신경과학·뇌영상 (`인지장애`) | 같음(유지) |
| 인지 과제 수행 중 반응 시간을 잰다. | 신경과학·뇌영상 (`인지 과제`) | 같음(유지) |
| neuroscience 공개 데이터를 쓴다. | 신경과학·뇌영상 | 같음(유지) |
| brainstorming과 rebranding을 논의한다. | 없음 | 없음(로마자 낱말 한가운데는 안 잡음) |

(측정: 스크래치 `examples.py`, 기준 모듈은 `git show 4cbf0f0:src/neumann/analyze/fitness.py`)

## 2. 템플릿·예시·데모 계획서 분야 (수정 전후)

`rule_fitness` 분야와 분야 점수(표지가 잡힌 줄 수, 상위 3개). 11건 모두 분야·점수·잡힌 표지가 수정 전과 같다.

| 문서 | 판정 | 분야 전 | 분야 후 | 점수 전 | 점수 후 |
|---|---|---|---|---|---|
| 템플릿 `materials_gnn.md` | fit | 재료·화학 | 재료·화학 | 재료·화학 2 | 같음 |
| 템플릿 `molecule_reaction.md` | fit | 재료·화학 | 재료·화학 | 재료·화학 4 | 같음 |
| 템플릿 `protein_binding.md` | fit | 생명과학·생물정보 | 생명과학·생물정보 | 생명과학 3, 자연어처리 1, 재료·화학 1 | 같음 |
| 템플릿 `pde_operator.md` | fit | 물리·공학 | 물리·공학 | 물리·공학 3 | 같음 |
| 템플릿 `climate_emulator.md` | fit | 기후·지구과학 | 기후·지구과학 | 기후 5, 물리·공학 1 | 같음 |
| 예시 `tests/fixtures/plans/plan.md` (example-battery) | fit | 재료·화학 | 재료·화학 | 재료·화학 4 | 같음 |
| 예시 `examples/protein_ligand_affinity.md` | fit | 생명과학·생물정보 | 생명과학·생물정보 | 생명과학 4, 재료·화학 1 | 같음 |
| 예시 `examples/neural_operator_weather.md` | fit | 기후·지구과학 | 기후·지구과학 | 기후 5, 물리·공학 1, 재료·화학 1 | 같음 |
| 데모 `plan_elife_neuro.md` | fit | 신경과학·뇌영상 | 신경과학·뇌영상 | 신경과학 7 | 같음 |
| 데모 `plan_medimaging.md` | fit | 의료·의료영상 | 의료·의료영상 | 의료 9, 컴퓨터비전 1 | 같음 |
| 음성 대조 `negative_recipe.md` | unfit | 없음 | 없음 | — | — |

(데모 `plan.md`는 예시 example-battery와 같은 파일이라 한 줄로 적었다.)

## 3. 판정 불변 — main과 대조 (`tests/e3/test_fitness_diff.py`)

- 기준 커밋 `4cbf0f0`의 `fitness.py`를 `git show`로 읽어 별도 모듈로 올리고, 같은 입력을 두 판에 넣는다. git·커밋이 없으면 건너뛴다.
- 입력: 위 문서 11건 + 무작위 240건(시드 20260930; 요소·무관·분야 어휘, 영어 낱말+조사 17종, 인지 구절 13종, 가끔 붙여 쓰기로 한글·로마자가 맞닿게). 무작위 판정 분포 fit 109 · unfit 45 · uncertain 86, `too_short` 포함.
- 입력마다 5가지 반환값에서 `field`·`elapsed_s`(와 `rule.field`)만 빼고 JSON 문자열로 비교: `rule_fitness`, `assess_fitness(plan, None)`(강등), `assess_fitness`에 고정 응답 llm_call(research_plan·not_research_plan·uncertain, 분야 빈 문자열이라 규칙 분야로 떨어짐).
- 결과: **251건 × 5 = 1,255개 반환값 모두 같다.** 분야는 무작위 42건에서 바뀌었다. 신경과학 → 다른 분야·없음이 30건(인지 어미·neuromorphic·neuro-symbolic 제외), 나머지 12건은 조사 붙은 약어(`DNA를`, `plasma로` 등)가 새로 잡혀 점수 순위가 바뀐 경우다(없음 → 분야 5건, 다른 분야·없음 → 신경과학 3건 포함, 두 묶음은 1건 겹침). 분야 표지에서 새로 잡히거나 빠진 말을 모두 뽑아 봤고 세 가지 수정으로 설명되지 않는 변화는 없었다(스크래치 `e3l1z_terms.py`).
- 이 파일의 다른 검사: 문서 11건 분야가 기준과 같음, 기준에서 신경과학이던 진짜 신경과학 구절 25개(E3-L1x 검증 3-2절 + 인지 복합어)가 여전히 신경과학, 무작위 입력에서 분야가 10건 넘게 바뀜(코퍼스가 수정을 실제로 건드린다).

## 4. 완료 기준

| 기준 | 명령 | 출력 |
|---|---|---|
| 1 | `python -m pytest tests/e3 -q -p no:cacheprovider` | `495 passed, 12 skipped in 20.33s` (main 병합 뒤, PM 추가 검사 포함) |
| 2 | `python scripts/verify.py` (venv, mock) | main 병합 전(`39ebca9`·`34295f0` 커밋 직전 작업 트리): `1282 passed, 27 skipped in 87.95s` · `보안: 파일 407개` · `계약: 2개` · `테스트: 통과` · `verify 통과` / 최종(병합·PM 추가 뒤): §8 |

### 새로 넣거나 바꾼 정규식의 적대 입력 (ReDoS 금지)

`test_changed_patterns_are_linear_on_adversarial_input`: `_NEURO_KO`, `_NEURO_EN`, 분야 영어 패턴 8개를 반복 단위 23종(발견 A 수정 때 `사회인지 `·`경도인지`·`사회인지　`·`사회`를 더해 27종, §9)(`인지`, `인지 `, `가인지 `, `인지　`, `인지과`, `신경 `, `뇌`, `가`, `a`, `a가`, `neuro`, `neuro-`, `neuro `, `neurosymboli`, `neuromorphi`, `neuro-symboli`, `cognit`, `eeg와`, `x-`, `x-ra`, `brain`, `_`, `9`)으로 만든 **10만 자** 입력에 `finditer`하고 한 번마다 0.2초 미만을 단언한다. 실측 최악(스크래치 `redos.py`):

| 패턴 | 최악 | 반복 단위 |
|---|---:|---|
| `_NEURO_KO` | 12.4 ms | `뇌` (일치 10만 건) |
| `_NEURO_EN` | 6.6 ms | `eeg와` |
| 분야 영어 패턴 7개 | 5.3~7.4 ms | 한글·공백 반복 |

둘러보기는 한 글자, neuro 부정 전방탐색은 최대 9글자이고, `[a-z0-9]*` 뒤 경계는 반복이 먹지 못한 글자에서만 검사하므로 되돌아가기가 없다.

### 변이 검사 (테스트가 실제로 잡는가)

`fitness.py`를 한 곳씩 망가뜨리고 `test_fitness_field.py`+`test_fitness_diff.py`(100건)를 돌린 뒤 원본으로 되돌렸다(`cmp` 확인).

주: M2를 처음 잴 때 변이 스크립트가 `\b`를 백스페이스 문자로 넣어(따옴표 탈출 실수) 엉뚱한 결과(23 실패)가 나왔다. 다시 잴 때는 원본 파일을 고치지 않고, 변이 소스를 메모리 모듈로 올려 pytest 플러그인이 테스트 모듈 전역(`_FIELDS`, `_line_hits`, `rule_fitness`, `current` 등)에 끼우는 방식으로 쟀다(스크래치 `plug/m2plugin.py`). 그 사이 사용자 중단으로 끊긴 명령 하나가 작업 트리 `fitness.py`에 M2 변이를 남겼다. 원본으로 되돌리고 `git diff --quiet HEAD -- src/neumann/analyze/fitness.py`로 커밋본과 같음을 확인했다. §8 verify는 그 변이보다 먼저 끝난 실행이다.

| 변이 | 결과 |
|---|---|
| M1 인지 앞 `(?<![가-힣])` 제거 | 5 실패 (어미 오탐 검사) |
| M2 `_en_ascii`를 `\b` 경계로 되돌림 | 8 실패 (조사 검사 8건 전부) — 파일이 아니라 메모리에서 변이 모듈을 끼워 쟀다(아래 주) |
| M3 neuro 부정 전방탐색 제거 | 6 실패 (AI 용어 검사) |
| M4 요소·무관 사전 `_en`도 로마자 경계로 | 1 실패 (`test_non_field_outputs_equal_base`: 184건 달라짐, 문서 중 `climate_emulator.md`·`protein_ligand_affinity.md`의 요소 줄 번호 포함) |
| M5 붙여 쓴 인지 복합어 갈래 제거(지시문 그대로) | 10 실패 (경도인지장애·인지과제·사회인지기능·인지심리 등, 차등 검사 5 포함) |

M4를 따로 재면 판정이 바뀌는 입력이 42건(uncertain→fit 30, unfit→uncertain 8, unfit→fit 4), 판정은 같고 요소·줄 번호만 바뀌는 입력이 142건이다(스크래치 `m4impact.py`).

## 5. 바꾼 파일

| 파일 | 내용 |
|---|---|
| `src/neumann/analyze/fitness.py` | `_en_ascii` 추가, `_NEURO_KO` 인지 복합어 두 갈래, `_NEURO_EN` neuro 제외, `_FIELDS` 영어 패턴을 `_en_ascii`로. `_en`(요소·무관)은 주석만 |
| `tests/e3/test_fitness_field.py` | 회귀 테스트: 어미 오탐 7, 인지 복합어 유지 13(발견 A 5 포함), 조사 8, 로마자 낱말 안 3, AI 용어 6, 다른 neuro 표지 유지 4, 적대 입력 10 패턴 |
| `tests/e3/test_fitness_diff.py` (새) | main 대조 차등 검사(§3) |
| `tests/e3/test_pipeline_parallel_status.py` (새, PM 추가) | §7 |
| `docs/reports/E3-L1z.md` | 이 보고서 |

## 6. 결정 (스펙이 모호해 고른 것)

1. **조사 경계는 분야 표지에만.** 지시문은 "파일 전체의 영어 패턴에 해당한다… 검토한다"와 "판정 로직은 분야를 뺀 반환값이 main과 같아야 한다"를 함께 요구한다. 요소 사전까지 바꾸면 판정이 42건 바뀌어 두 요건이 충돌한다(§4 M4). 분야에만 적용하고 요소 사전은 `\b`로 뒀다. `GNN을`·`CNN으로`가 방법 요소로 안 잡히는 한계는 남는다(§9).
2. **붙여 쓴 인지 복합어는 앞 글자와 상관없이 잡는다.** 지시문 방식(앞에 `(?<![가-힣])`만)은 `경도인지장애`를 놓친다.
3. **밑줄은 경계로 본다.** 지시문 경계 `[A-Za-z0-9]`를 그대로 따라 `EEG_data`의 `eeg`를 잡는다(`\b`는 못 잡았다). 테스트로 고정했다.
4. **`neuro symbolic`(띄어 씀)도 뺀다.** 지시문 `-?symbolic`을 `[-\s]?symbolic`로 넓혔다.
5. **차등 검사 기준은 고정 커밋 `4cbf0f0`.** "main"이라는 이름은 병합 뒤 자기 자신을 가리켜 검사가 무의미해지므로 해시로 박았다. 이후 과제가 판정 규칙을 일부러 바꾸면 이 검사가 실패하며, 그때 `BASE_REV`를 옮기라고 파일 머리에 적었다.

## 7. PM 추가 범위 — 병렬 파이프라인 status 합치기 검사

- `git merge main`(`c8ba766`, E3-L1y 병합본) → 병합 커밋 `61d66b0`. 충돌 없음.
- 새 파일 `tests/e3/test_pipeline_parallel_status.py`(10건). E3-L1y 파일을 고치지 않고 따로 뒀다.
  - provider: 이름이 `openai`인 `AstraLike(MockProvider)`(생성 주체 astra, 결과 기본 status `ok`), 모델 `gpt-6.1-sol`.
  - 대조군 1: 실패 없음 → 순차·병렬 모두 `ok`, 단계 전부 ok/skipped.
  - 실패 6: timeout(심사평·체크리스트·검증 각각), api_error(심사평+검증), 깨진 JSON(체크리스트, 응답이 `"{깨진 JSON"`), api_error(v1 전체).
  - 예외 3: `attach_expected_review`·`attach_checklist`·`attach_validation`이 `RuntimeError`.
  - 단언: 순차 기준값(실패 단계만 degraded 또는 error, 나머지 v1 단계 ok, 결과 status `degraded`) → 병렬 status = 순차 status → 단계별 state·예상 심사평 generator·model·체크리스트 항목 generator·model·검증 generator·model·status가 같음 → 시간 값을 뺀 결과 JSON 전체가 같음 → 실패하지 않은 심사평은 `astra` 표기 유지.
- **변이 확인:** `src/neumann/pipeline.py`의 `_merge_v1`에서 status 합치기 두 줄(`if _STATUS_RANK.get(out.status, 2) > …: status = out.status`)을 지운 사본으로 돌렸다.

| 파일 | 변이 상태 결과 |
|---|---|
| 기존 `tests/e3/test_pipeline_parallel.py` | `32 passed` (E3-L1y 검증 §8 M2 재현: 못 잡음) |
| 새 `tests/e3/test_pipeline_parallel_status.py` | `9 failed, 1 passed` — 실패 9건 모두 `assert par.status == seq.status` / `AssertionError: assert 'ok' == 'degraded'`. 통과 1건은 대조군(실패 없음) |

  되돌린 뒤 `cmp`로 원본과 같음을 확인했고 `git status`에 `pipeline.py` 변경 없음.

## 8. 최종 verify

명령: `NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." python scripts/verify.py` (venv, 작업 트리 = `aa10d38` + 이 보고서 초안, `NEUMANN_LIVE_LLM_OK`·`NEUMANN_LIVE_TESTS` 해제)

```
1335 passed, 27 skipped in 275.29s (0:04:35)
보안: 파일 414개
계약: 2개
테스트: 통과
verify 통과
```

같은 실행 직전 `python -m pytest tests/e3 -q -p no:cacheprovider`: `495 passed, 12 skipped in 18.25s`.

**발견 A 수정 뒤 재실행**(작업 트리 = `3e991ae` 직전, 코드·테스트는 `3e991ae`와 같음):

- `python -m pytest tests/e3 -q -p no:cacheprovider` → `506 passed, 12 skipped in 36.23s`
- 첫 `python scripts/verify.py` → **`verify 실패 1건: [테스트] pytest 실패 (exit 1)`**. 출력 끝 5줄만 남겨서 어느 테스트인지 못 봤다. 같은 시각에 검증 측 작업이 돌아 기계 부하가 높았다(적대 입력 최악 시간이 12→31 ms로 늘어난 것과 같은 때). 시간 상한이 있는 검사가 부하로 한 번 넘었을 가능성이 크지만 **확인하지 못했다.**
- 바로 이어 전체 `python -m pytest -q -p no:cacheprovider -rf` → `1346 passed, 27 skipped in 127.76s`, 실패 0
- 다시 `python scripts/verify.py`(전체 로그를 파일로 남김) → 실패 줄 없음:

```
1346 passed, 27 skipped in 128.70s (0:02:08)
보안: 파일 415개
계약: 2개
테스트: 통과
verify 통과
```

### 커밋 (`task/E3-L1z`)

| 커밋 | 내용 |
|---|---|
| `39ebca9` | 분야 표지 수정 3종 + 회귀·적대 입력 테스트 |
| `34295f0` | main 대조 차등 검사 |
| `61d66b0` | main(`c8ba766`) 병합 |
| `aa10d38` | PM 추가: 병렬 status 합치기 검사 |
| `58d0069` | 보고서 |
| `3e991ae` | 검증 발견 A: 인지 접두어 뒤 띄어 쓴 복합어 복구 + 테스트 |
| (이 커밋) | 보고서 갱신(§9 발견 A·B, §8 재실행 verify) |

## 9. 검증 발견 A (고침)와 못 한 것·다음 과제에 넘길 것

### 발견 A — 접두어가 붙은 "인지" 뒤에 띄어 쓴 복합어를 놓침 (검증 PASS-조건부, 고침)

- 현상: `58d0069`까지의 `_NEURO_KO`는 띄어 쓴 `인지 기능`을 "인지"가 낱말 첫머리일 때만 잡았다. 그래서 main에서는 잡히던 진짜 신경과학 입력 5건 `사회인지 기능`, `경도인지 장애`, `신경인지 기능`, `사회인지 과제`, `시각인지 능력`을 놓쳤다. 화면의 분야 표지만 영향을 받고 판정에는 영향이 없다(§3 차등 검사대로).
- 고침: 띄어 쓴 갈래의 뒷보기를 `(?:(?<![가-힣])|(?<=사회|경도|신경|시각|청각|공간|언어|정서|메타))`로 넓혔다. 접두어는 모두 두 글자라 고정 길이 뒷보기다. 목록 밖 앞말(`문화인지 기능인지`, `효과적인지 과제별로`)은 어미로 보고 계속 뺀다.
- 테스트: `test_cognition_compounds_stay_neuroscience`에 5건, `test_fitness_diff.KNOWN_NEURO`에 5건(기준 커밋에서도 신경과학인지 같이 확인)을 더했다. 목록 밖 앞말 음성 사례 1건과 적대 입력 반복 단위 4종(`사회인지 `, `경도인지`, `사회인지　`, `사회`)도 더했다.
- 고치기 전 코드(`58d0069`)를 메모리 모듈로 끼우면(스크래치 `plug/headplugin.py`, 파일은 안 고침) 새 테스트 10건이 정확히 실패하고, 고친 코드에서는 통과한다.
- main 대비 재차등: 분야 밖 반환값 251건 × 5가 모두 같다(`test_non_field_outputs_equal_base` 통과). 문서 11건 분야 차이 0, 무작위 입력의 분야 차이는 42건 그대로다.
- 적대 입력(10만 자, 반복 단위 27종) 최악 30.9 ms(`_NEURO_KO`, `인지　`). 이 측정은 다른 작업과 겹쳐 돈 것이라 §4 표(12.4 ms)보다 느리다. 0.2초 단언은 그대로 통과한다.

### 못 한 것·다음 과제에 넘길 것

- **검증 발견 B**(다음 과제): `neuro–symbolic`(en dash)·`neuro-morphic`(하이픈으로 끊음)은 아직 신경과학 표지(`neuro`)로 잡힌다. 숫자 뒤 "인지"(예: `3인지 과제`처럼 숫자가 앞에 붙은 어미)는 뒷보기가 한글만 보므로 어미인데도 잡힌다.
- 인지 접두어 목록은 손으로 고른 9개다. `운동인지`·`지각인지`·`수리인지` 같은 다른 접두어가 띄어 쓴 복합어로 오면 여전히 놓친다.

- **요소 사전의 조사 경계**(`GNN을`, `CNN으로`, `F1로`, `AUC가`는 방법·평가 요소로 안 잡힘). 고치면 판정이 바뀌므로(§4 M4: 251건 중 42건) 판정 변화를 받아들이는 별도 과제로 하고, 그때 `test_fitness_diff.BASE_REV`를 옮긴다. 판정이 주로 uncertain→fit 쪽(과잉 거절 감소)으로 움직여 방향은 나쁘지 않다.
- 남은 분야 오탐: `128 neurons`(은닉층 설명), `neuroevolution`, `cognitive radio`, `고뇌·번뇌·뇌물·세뇌`(맨 `뇌`). 지시 범위 밖이라 두었다.
- 남은 분야 누락: 맨 `신경`(`신경전달물질`, `신경가소성`), `neural recordings`, `시냅스`, `해마`, `cortex`, `MEG`·`PET`(어휘에 없음). 붙여 쓴 어미(`효과적인지과제`처럼 맞춤법에 어긋나게 붙인 경우)는 여전히 잡힌다.
- 병렬 파이프라인: 카드 8장 이상(체크리스트 묶음 3개 초과)은 mock으로 만들지 못해 새 status 검사도 카드 수가 적은 `PLAN_BATTERY`로만 돈다.
