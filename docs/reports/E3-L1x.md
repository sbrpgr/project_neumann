# E3-L1x 보고서 — 규칙 분야 판정: 인공 신경망·신경 연산자를 신경과학으로 분류하지 않기

- 빌더: claude-opus-5.5 · 브랜치 `task/E3-L1x` · 검증 대기
- 바꾼 파일: `src/neumann/analyze/fitness.py`, `tests/e3/test_fitness_field.py`(새 파일), 이 보고서
- 실제 API 호출 없음. 모든 python·pytest 명령은 `NEUMANN_LLM_PROVIDER=mock`, `PYTHONPATH="src;."`, venv python으로 돌렸다.

## 무엇을 했나

`rule_fitness`(astra 실패 때 쓰는 비상 경로이자 교차 확인 신호)는 줄마다 분야 표지를 세고, 가장 많이 잡힌 분야를
`field`로 고른다. mock provider(`mock_responders.fitness`)는 `field=""`를 돌려주므로 mock·데모 화면의 분야도 이 규칙 값이다.
"신경과학·뇌영상" 표지가 너무 넓었다.

- 영어 `neur\w*`가 `neural`(Neural Network, Neural Operator)을 잡았다.
- 한국어 부분 문자열 `"신경"`이 `신경망`·`심층신경망`·`신경 연산자`를 잡았다.
- 한국어 `"인지"`는 어미 `~인지`(예: "공정한 것인지")를, `"뇌"`는 `뇌우`(기상)를 잡았다.

고친 내용(`fitness.py`):

- 영어: `neuro\w*`(neuron·neurons·neuronal·neuroscience·neuroimaging을 모두 포함하고 neural은 제외), `fmri`, `eeg`,
  `brains?`, `cognit\w*`.
- 한국어는 정규식 `_NEURO_KO`로 바꿨다: `신경\s?(과학|세포|생리|영상|활동|신호|질환)`, `신경\s?회로(?!망)`, `신경계`,
  `뉴런`, `뇌(?!우)`, `인지\s?(과학|과제|기능|능력|부하|저하|장애|심리)`. 이제 `신경망`, `심층신경망`, `신경 연산자`,
  `신경연산자`, `신경회로망`, `뇌우`, `~인지`는 잡지 않는다.
- `_line_hits`는 한국어 표지로 부분 문자열 목록 외에 정규식도 받는다. 정규식은 신경과학 분야에만 쓴다. 다른 분야와
  요소 사전은 그대로다.

## 분야(field) 전후 비교 — `src/neumann/api/templates/` 아래 템플릿·예시 전부

측정 스크립트(스크래치 폴더, 커밋 안 함)는 각 파일을 `PlanDocument.from_text`로 읽어 `rule_fitness(plan)["field"]`를 구하고,
분야별로 표지가 잡힌 줄 수를 센다. 수정 전 값은 수정하기 전 같은 worktree에서 잰 것이다.

| 파일 | 카탈로그 도메인 | 수정 전 field | 수정 후 field | 신경과학 표지 줄 수(전→후) | 수정 전 신경과학 표지 |
|---|---|---|---|---|---|
| `climate_emulator.md` | 물리·PDE·기후 | 기후·지구과학 | 기후·지구과학 | 1 → 0 | `신경`(신경 연산자) |
| `materials_gnn.md` | 소재·화학·분자 | 재료·화학 | 재료·화학 | 0 → 0 | — |
| `molecule_reaction.md` | 소재·화학·분자 | 재료·화학 | 재료·화학 | 1 → 0 | `신경`(그래프 신경망) |
| `pde_operator.md` | 물리·PDE·기후 | **신경과학·뇌영상** | **물리·공학** | 3 → 0 | `neural`, `신경`(신경 연산자) |
| `protein_binding.md` | 단백질·생물·신약 | 생명과학·생물정보 | 생명과학·생물정보 | 0 → 0 | — |
| `examples/neural_operator_weather.md` | 물리·PDE·기후 | 기후·지구과학 | 기후·지구과학 | 2 → 0 | `neural`, `신경` |
| `examples/protein_ligand_affinity.md` | 단백질·생물·신약 | 생명과학·생물정보 | 생명과학·생물정보 | 1 → 0 | `neural`(Graph Neural Network) |

`catalog.json`과 `catalog.schema.json`은 계획서가 아니라서 표에서 뺐다.

참고로 데모 계획서(`tests/fixtures/plans/`, 카탈로그 예시 `example-battery`가 `plan.md`)도 쟀다.

| 파일 | 수정 전 field | 수정 후 field | 신경과학 표지 줄 수(전→후) | 표지(전 / 후) |
|---|---|---|---|---|
| `plan.md` | 재료·화학 | 재료·화학 | 1 → 0 | `neural` / — |
| `plan_elife_neuro.md` | 신경과학·뇌영상 | 신경과학·뇌영상 | 7 → 7 | `fmri, 뇌, 신경, 인지` / `fmri, 뇌, 신경과학, 인지과제` |
| `plan_medimaging.md` | 의료·의료영상 | 의료·의료영상 | 2 → 0 | `neural, 신경`(심층신경망) / — |

**과제 설명과 다른 점:** 과제 설명은 `neural_operator_weather.md`도 신경과학으로 나온다고 했지만, 실제로 재 보니 수정 전에도
기후·지구과학(기후 5줄, 신경과학 2줄)이었다. 분야가 틀렸던 파일은 `pde_operator.md` 하나다. 신경과학 3줄과 물리 3줄이
동률이었고, `max`가 먼저 등장한 분야를 골라 신경과학이 됐다. 나머지 파일 5건(`climate_emulator`, `molecule_reaction`,
`protein_ligand_affinity`, `plan`, `plan_medimaging`)도 신경과학 표지가 잘못 잡혔지만 이긴 분야는 바뀌지 않았다.
수정 뒤에는 AI for Science 문서 전부에서 신경과학 표지가 0줄이다.

측정 출력(수정 전):

```
pde_operator.md | field=신경과학·뇌영상 | verdict=fit | scores={'신경과학·뇌영상': 3, '물리·공학': 3}
   neuro hits: ['neural', '신경']
examples/neural_operator_weather.md | field=기후·지구과학 | verdict=fit | scores={'신경과학·뇌영상': 2, '기후·지구과학': 5, '물리·공학': 1, '재료·화학': 1}
   neuro hits: ['neural', '신경']
```

측정 출력(수정 후):

```
pde_operator.md | field=물리·공학 | verdict=fit | scores={'물리·공학': 3}
   neuro hits: []
examples/neural_operator_weather.md | field=기후·지구과학 | verdict=fit | scores={'기후·지구과학': 5, '물리·공학': 1, '재료·화학': 1}
   neuro hits: []
DEMO plan_elife_neuro.md | field=신경과학·뇌영상 | scores={'신경과학·뇌영상': 7}
   neuro hits: ['fmri', '뇌', '신경과학', '인지과제']
```

## 완료 기준별 결과

### 1. 신경 연산자 문서 2건과 단백질·분자 템플릿은 신경과학이 아니다 — 통과

`tests/e3/test_fitness_field.py`(새 테스트 26건):

- `test_ai_for_science_documents_are_not_neuroscience`: 대상은 `pde_operator.md`, `examples/neural_operator_weather.md`,
  `protein_binding.md`, `molecule_reaction.md` 4건이다. 문서 전체에서 신경과학 표지가 0줄이고 `field`가 신경과학이 아닌지
  본다. 이긴 분야만 보지 않고 표지 수를 보므로 동률 뒤집힘도 막는다.
- `test_pde_operator_template_is_physics`: `pde_operator.md`가 물리·공학으로 나오는지 본다.
- `test_neural_operator_example_field_on_rule_fallback`: `assess_fitness(plan, None)`으로 강등됐을 때 화면에 나가는 분야가
  기후·지구과학인지 본다.
- `test_catalog_documents_field_matches_domain`: `catalog.json`의 템플릿 5건과 예시 3건 전부가 자기 도메인에 맞는 분야로
  나오는지 본다(소재→재료·화학, 단백질→생명과학·생물정보, 물리·PDE·기후→물리·공학 또는 기후·지구과학).
- `test_ai_method_and_everyday_terms_are_not_neuroscience`: 9개 구절을 본다. Fourier Neural Operator, Graph Neural
  Network, physics-informed neural networks, 그래프 신경망, 합성곱·심층신경망, 신경 연산자·신경연산자,
  신경회로망·신경 회로망, 어미 `~인지`, `뇌우`.

### 2. 진짜 fMRI·EEG 계획서는 그대로 신경과학 — 통과

- `test_real_neuroscience_plans_stay_neuroscience`: 한국어 fMRI·EEG 계획서, 영어 EEG 계획서, 한국어만 쓴 신경세포·뉴런
  계획서 3건을 넣는다. 잡힌 표지 집합이 기대한 것과 같은지, `field == "신경과학·뇌영상"`인지 본다.
- 기존 `test_fitness.py::test_demo_fields_differ_by_rule`도 그대로 통과한다(`plan_elife_neuro.md` → 신경과학·뇌영상).

### 3. 새 테스트가 버그를 실제로 잡는지 — 확인

수정 전 `fitness.py`(`git show HEAD:…`)를 스크래치 폴더의 패키지 사본에 넣고 새 테스트를 돌렸다.
pyproject의 `pythonpath`를 `-o`로 사본 쪽으로 바꿨다.

```
$ python -m pytest tests/e3/test_fitness_field.py tests/e3/test_fitness.py -q -o "pythonpath=<사본> ."
16 failed, 43 passed
```

- 수정 전 코드에서 실패한 것: 신경 연산자·분자 문서 3건, pde 물리 판정, 카탈로그 pde-operator, AI·일상 구절 9건 전부.
- 진짜 신경과학 3건 중 2건도 수정 전 코드에서 실패했다. 이유는 분야가 아니라 표지 집합이 달라서다(예전 어휘는
  `신경`·`인지`로 잡는다). 분야는 수정 전에도 신경과학이었다.
- 수정 전에도 통과한 것: `protein_binding.md`(원래 신경과학 표지가 0줄이라 보호용 검사)와 카탈로그의 나머지 도메인 검사.

### 4. 기존 테스트와 verify — 통과

```
$ NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e3/test_fitness.py -q        # 수정 전
33 passed in 0.28s
$ NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e3/test_fitness_field.py tests/e3/test_fitness.py -q   # 수정 후
59 passed in 0.39s
$ NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e3 -q
368 passed, 12 skipped in 8.46s
$ NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/verify.py
1092 passed, 45 skipped in 82.77s (0:01:22)
보안: 파일 372개
계약: 2개
테스트: 통과
verify 통과
```

## 결정

- 과제 설명의 영어 목록(`neuro\w*`, `neurons?`, `neuronal`, `neuroscien\w*`)은 `neuro\w*` 하나로 모두 덮이므로
  `neuro\w*`만 뒀다. 주석에 무엇을 포함하고 무엇을 빼는지 적었다. `brain`은 복수형도 잡도록 `brains?`로 했다.
- 한국어 `"인지"`를 그대로 두지 않고 인지 복합어(과제·기능·능력·부하·저하·장애·심리·과학)로 좁혔다. 한국어 어미
  `~인지`("~것인지", "~분할인지")가 모든 계획서에 흔해서 신경과학 오탐의 같은 원인이다. `"뇌"`에서는 `뇌우`를 뺐다.
  기후 분야가 제품 범위라서다.
- 한국어 표지를 정규식으로 받도록 `_line_hits`를 넓혔다. 제외 조건(`(?!망)`, `(?!우)`)은 부분 문자열로는 쓸 수 없어서다.
  바꾼 곳은 신경과학 분야뿐이고, 다른 분야·요소·장르 사전과 판정 로직, 반환 형태는 그대로다.
- 분야 동률은 여전히 먼저 등장한 분야가 이긴다. 이번 버그의 원인은 동률이 아니라 오탐이라서 동률 규칙은 건드리지 않았다.

## 못 한 것·남은 한계

- 영어 약어 바로 뒤에 한국어 조사가 붙으면(`EEG와`, `fMRI로`) `_en`의 `\b` 때문에 잡히지 않는다. 한글도 `\w`라서다.
  모든 `_en` 사전(요소·장르·분야)에 공통이고 수정 전과 같다. 테스트 문장은 `EEG 신호와`로 적었다. 고치려면 `_en` 경계를
  ASCII 전용(`(?<![A-Za-z0-9_])…(?![A-Za-z0-9_])`)으로 바꿔야 하는데, 요소 판정 줄 번호가 달라질 수 있어 이번 범위 밖으로 뒀다.
- `neuro\w*`는 여전히 `neuro-symbolic`, `neuromorphic`, 은닉층 설명의 `128 neurons` 같은 AI 용어를 잡을 수 있다.
  한 줄짜리 오탐이라 동률일 때만 분야가 바뀐다. 필요하면 부정 전방탐색으로 뺀다.

## 다음

- 위 `_en` 경계 문제(약어+조사)를 E3 소과제로 따로 고치고, 요소 판정 줄 번호 회귀를 함께 확인할 것을 제안한다.
- E4가 카탈로그에 새 도메인을 넣으면 `test_catalog_documents_field_matches_domain`이 허용 분야를 추가하라는 메시지와
  함께 실패한다. 규칙 분야 사전도 그 도메인에 맞게 늘려야 한다.
