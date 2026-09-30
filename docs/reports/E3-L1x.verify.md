**판정: PASS** (병합 전 필수 수정 없음. 아래 "권고 후속"은 병합을 막지 않는 잔여 한계다.)

# E3-L1x 검증 보고서 — 규칙 분야 판정: 인공 신경망·신경 연산자를 신경과학으로 분류하지 않기

- 검증자: claude-sonnet-5.5 (빌더 claude-opus-5.5와 다른 모델) · 대상 브랜치 `task/E3-L1x` head `6c59721`
- 방법: 스크래치 폴더의 분리(detached) worktree에서 `6c59721`을 체크아웃해 재측정. 빌더 worktree는 열지도 고치지도 않았다. 검증 뒤 내 worktree 2개(브랜치용, main 대조용)는 `git worktree remove`로 지웠다.
- 모든 python 명령은 `NEUMANN_LLM_PROVIDER=mock`, `PYTHONPATH="src;."`, venv python. `.env`는 열지 않았고 OpenAI 호출은 없다.
- 측정 스크립트는 스크래치 폴더에만 있다(`l1x_measure.py`, `l1x_adv.py`, `l1x_adv2.py`, `l1x_diff.py`). 커밋하지 않는다.

## 1. 요약 표

| # | 완료 기준 | 결과 |
|---|---|---|
| 1 | 템플릿·예시·데모 계획서 분야 전후 재측정 | 통과. 빌더 표와 11건 모두 일치. 틀렸던 것은 `pde_operator.md` 하나 |
| 2 | 적대 구절(AI / 진짜 신경과학 / 한국어 오탐) | 통과(일부 한계 있음). 지시한 구절 중 `neuromorphic`만 신경과학으로 분류됨 |
| 3 | 판정(fit/unfit/uncertain) 로직 불변, 소유 경로 준수 | 통과 |
| 4 | `pytest tests/e3`, `scripts/verify.py` | 통과 |
| 5 | 새 테스트가 실제로 버그를 잡는가(항상 통과 금지) | 통과. main 코드에서 16건 실패, 변이 8종 모두 잡힘 |

## 2. 분야(field) 전후 재측정

명령: 두 트리(main, `6c59721`)에서 각각 `PlanDocument.from_text` → `rule_fitness(plan)`을 돌렸다. 신경과학 줄 수는 `_FIELDS`의 신경과학 항목으로 `_line_hits`가 잡은 줄 수다.

| 파일 | 전 field | 후 field | 신경과학 표지 줄(전→후) | verdict 전/후 | 요소 줄 번호 동일 |
|---|---|---|---|---|---|
| `templates/climate_emulator.md` | 기후·지구과학 | 기후·지구과학 | 1 → 0 | fit / fit | 예 |
| `templates/materials_gnn.md` | 재료·화학 | 재료·화학 | 0 → 0 | fit / fit | 예 |
| `templates/molecule_reaction.md` | 재료·화학 | 재료·화학 | 1 → 0 | fit / fit | 예 |
| `templates/pde_operator.md` | **신경과학·뇌영상** | **물리·공학** | 3 → 0 | fit / fit | 예 |
| `templates/protein_binding.md` | 생명과학·생물정보 | 생명과학·생물정보 | 0 → 0 | fit / fit | 예 |
| `templates/examples/neural_operator_weather.md` | 기후·지구과학 | 기후·지구과학 | 2 → 0 | fit / fit | 예 |
| `templates/examples/protein_ligand_affinity.md` | 생명과학·생물정보 | 생명과학·생물정보 | 1 → 0 | fit / fit | 예 |
| `tests/fixtures/plans/negative_recipe.md` | None | None | 0 → 0 | unfit / unfit | 예 |
| `tests/fixtures/plans/plan.md` | 재료·화학 | 재료·화학 | 1 → 0 | fit / fit | 예 |
| `tests/fixtures/plans/plan_elife_neuro.md` | 신경과학·뇌영상 | 신경과학·뇌영상 | 7 → 7 | fit / fit | 예 |
| `tests/fixtures/plans/plan_medimaging.md` | 의료·의료영상 | 의료·의료영상 | 2 → 0 | fit / fit | 예 |

- 실제로 분야가 뒤집힌 것은 `pde_operator.md` 하나다(신경과학 3줄·물리 3줄 동률에서 먼저 나온 분야가 이기는 `max` 동작). 과제 설명의 "`neural_operator_weather.md`도 신경과학"은 main에서도 재현되지 않는다(기후·지구과학). 빌더 보고서의 지적이 맞다.
- 수정 뒤 AI for Science 문서 전부(템플릿 5 + 예시 2 + 데모 3)에서 신경과학 표지가 0줄이다. 진짜 신경과학 데모 `plan_elife_neuro.md`는 7줄 그대로다.
- `catalog.json`·`catalog.schema.json`은 계획서가 아니라 뺐다.

## 3. 적대 구절 (전 = main, 후 = 브랜치)

"신경과학으로 분류"는 `_FIELDS`의 신경과학 항목에 표지가 한 줄이라도 잡히는지로 쟀다.

### 3-1. AI 구절 (신경과학이 아니어야 옳다)

| 구절 | 전 | 후 | 판단 |
|---|---|---|---|
| graph neural network | 신경과학 | 아님 | 옳음 |
| 신경망 / 심층 신경망 / 심층신경망 / 인공신경망 / 인공 신경망 | 신경과학 | 아님 | 옳음 |
| Fourier neural operator, 신경 연산자 | 신경과학 | 아님 | 옳음 |
| neural ODE | 신경과학 | 아님 | 옳음 |
| physics-informed neural network(s) | 신경과학 | 아님 | 옳음 |
| spiking / convolutional neural network, 신경회로망 | 신경과학 | 아님 | 옳음 |
| Neural Tangent Kernel, NeurIPS | 신경과학 | 아님 | 옳음 |
| **neuromorphic** (`neuromorphic hardware accelerator`) | 신경과학 | **신경과학 (`neuromorphic`)** | **틀림(빌더가 보고서에 한계로 적음)** |
| **neuro-symbolic reasoning** | 신경과학 | **신경과학 (`neuro`)** | 틀림(같은 한계) |
| **hidden layer with 128 neurons** | 신경과학 | **신경과학 (`neurons`)** | 틀림(같은 한계) |
| 뉴럴 네트워크, 뉴럴넷 (음역) | 아님 | 아님 | 옳음 |

### 3-2. 진짜 신경과학 구절 (신경과학이어야 옳다)

| 구절 | 전 | 후 | 판단 |
|---|---|---|---|
| fMRI BOLD signal | 신경과학 | 신경과학 (`fmri`) | 옳음 |
| EEG 신호 | 신경과학 | 신경과학 (`eeg`) | 옳음 |
| 뉴런 발화 | **아님** | 신경과학 (`뉴런`) | 옳음(전보다 좋아짐) |
| 신경세포 | 신경과학 | 신경과학 (`신경세포`) | 옳음 |
| cognitive load | 신경과학 | 신경과학 (`cognitive`) | 옳음 |
| brain connectivity, brains of mice | 신경과학 | 신경과학 | 옳음 |
| neurons / neuronal / neuroscience / neuroimaging | 신경과학 | 신경과학 | 옳음 |
| 뇌 영상, 뇌파, 대뇌 피질, 인지 과학, 인지 기능 저하 | 신경과학 | 신경과학 | 옳음 |
| 신경 영상, 신경계 질환, 신경 활동, 신경 신호 | 신경과학 | 신경과학 | 옳음 |

수정 뒤 놓치는 진짜 신경과학 구절(회귀, 전에는 잡던 것):

| 구절 | 전 | 후 |
|---|---|---|
| `신경전달물질 도파민`, `신경가소성`, `신경 발달`, `도파민 신경 손상`(맨 `신경`) | 신경과학 | **아님** |
| `neural recordings from primary visual cortex`, `neural responses`(맨 `neural`) | 신경과학 | **아님** |

전에도 못 잡던 것: `시냅스 가소성`, `해마 피질`, `cerebral cortex hippocampus`, `cortical activation`, `MEG and PET`(어휘에 없음). `fMRI를`·`EEG와`처럼 영어 약어 뒤에 조사가 붙으면 `\b` 때문에 못 잡는 것도 전과 같다(빌더가 보고서에 적음).

### 3-3. 한국어 오탐 (신경과학이 아니어야 옳다)

| 구절 | 전 | 후 | 판단 |
|---|---|---|---|
| 뇌우, 뇌우 예측 모델, 뇌우와 태풍 | 신경과학 | 아님 | 옳음 |
| 공정한 **것인지** 확인한다 | 신경과학 | 아님 | 옳음 |
| **인지하다**, 위험을 인지하고 | 신경과학 | 아님 | 옳음 |
| 신경 쓰지 않는다, 신경쓰다, 무신경 | 신경과학 | 아님 | 옳음 |
| **효과적인지 과제별로** 검증한다 | 신경과학 (`인지`) | **신경과학 (`인지 과제`)** | **틀림(잔여 오탐)** |
| 나은 **것인지 기능** 단위로 분해한다 | 신경과학 (`인지`) | **신경과학 (`인지 기능`)** | **틀림(잔여 오탐)** |
| 고뇌와 번뇌 | 신경과학 | 신경과학 (`뇌`) | 틀림(전과 같음, 드묾) |
| cognitive radio network | 신경과학 | 신경과학 | 틀림(전과 같음, 드묾) |

빌더 보고서는 "어미 `~인지`는 잡지 않는다"고 썼는데, 정확히는 `인지` 바로 뒤에 공백 없이 또는 한 칸 띄우고 `과제·기능·능력·부하·저하·장애·심리·과학`이 오는 경우(`~인지 과제`, `~인지 기능`)는 여전히 잡힌다. `인지` 앞에 한글 음절이 오는지 보는 조건이 없어서다. 문장이 `~인지,`나 `~인지.`로 끝나거나 다른 단어가 오면 안 잡힌다(빌더 테스트 통과).

## 4. 판정 로직 불변, 소유 경로

- 소유 경로: `git diff main...task/E3-L1x --name-status`가 3건뿐이다. `src/neumann/analyze/fitness.py`(M), `tests/e3/test_fitness_field.py`(A), `docs/reports/E3-L1x.md`(A). `contracts/`, `src/neumann/models.py`, 데이터·비밀값 파일 변경 없음.
- `fitness.py` 변경은 +14/−4줄(`git diff --numstat`): `_NEURO_KO`·`_NEURO_EN` 상수 추가, `_FIELDS`의 신경과학 항목만 교체, `_line_hits`가 정규식도 받게 확장. 다른 분야·요소·장르 사전, `rule_fitness` 본문, `assess_fitness`는 그대로다. `_FIELDS`·`_line_hits`를 다른 모듈이 쓰는 곳은 없다(grep).
- 차등 검사: `field`를 뺀 `rule_fitness` 반환 전체(verdict, precheck, reason, elements 줄 번호, n_elements, research_hits, offtopic_hits, offtopic_terms, n_chars)를 main과 브랜치에서 287건 입력(fixtures·템플릿 전 문서 + 적대 구절 조합 3종)에 돌려 JSON을 비교했다. 바이트 단위로 동일했다(`cmp` 통과).
- 튜플 `ko`의 `_line_hits` 경로(요소·장르·다른 분야)는 코드가 그대로라 동작이 같다. 정규식 경로는 신경과학 항목에만 쓰인다. 정규식 `finditer`는 한 줄에서 표지를 여러 번 돌려주지만(예: `고뇌와 번뇌` → `뇌`, `뇌`), 점수는 줄 단위 참·거짓이라 영향이 없다.

## 5. 테스트 실측

| 명령(브랜치 `6c59721` worktree) | 출력 |
|---|---|
| `python -m pytest tests/e3 -q -p no:cacheprovider` | `368 passed, 12 skipped in 6.84s` (빌더 보고와 일치) |
| `python scripts/verify.py` | `1092 passed, 45 skipped in 78.64s` / `보안: 파일 373개` / `계약: 2개` / `테스트: 통과` / `verify 통과` |
| 새 테스트 파일만 | `26 passed` |
| main worktree에 새 테스트 파일만 복사해 실행 | `16 failed, 43 passed`(`test_fitness_field.py` + `test_fitness.py`). 빌더 주장과 일치 |

verify 뒤 worktree의 `git status`는 깨끗했다(테스트가 남긴 파일 없음).

### 항상 통과하는 테스트인가 — 변이 검사

내 scratch worktree의 `fitness.py`를 한 곳씩 망가뜨리고 `tests/e3/test_fitness_field.py`(26건)를 돌렸다. 매번 원본으로 되돌리고 `cmp`로 확인했다.

| 변이 | 결과 |
|---|---|
| 영어 `neuro\w*` → `neur\w*` | 5건 실패 |
| `신경\s?회로(?!망)` 에서 `(?!망)` 제거 | 1건 실패 |
| `뇌(?!우)` 에서 `(?!우)` 제거 | 1건 실패 |
| `인지` 복합어를 맨 `인지`로 되돌림 | 2건 실패 |
| 맨 `신경` 추가 | 7건 실패 |
| `뉴런` 제거 | 1건 실패 |
| `신경세포` 제거 | 1건 실패 |
| `eeg` 제거 | 2건 실패 |

8종 모두 잡힌다. 다만 "진짜 신경과학" 테스트는 잡힌 표지 집합을 정확히 비교해서(`expected_terms`) 구현과 결합이 강하다. 어휘를 넓히면 이 테스트를 같이 고쳐야 한다(오류가 아니라 취약성).

## 6. 정직성·규칙 점검

- 커밋 메시지: 과제 ID, 검증 한 줄(`verify 통과 (1092 passed, 45 skipped)`), `builder: claude-opus-5.5` 있음. 빌더 보고서의 숫자는 내 재측정과 전부 일치한다(26건, 16 failed/43 passed, 368/12, 1092/45).
- 비밀값·`.env`·데이터 파일 추가 없음. 실제 API 호출 없음. 보안 검사(`verify.py`)에서 파일 373개 통과.
- 규칙 결과를 LLM 결과라고 표시하는 코드 변경은 없다(분야 사전만 손댐). `docs/decisions.md`에 남길 폴백 전환도 없다.
- 빌더 보고서 문장 하나가 조금 과장이다: "`~인지`는 잡지 않는다" → 위 3-3처럼 `~인지 과제·기능…`은 잡는다. 완료 기준(템플릿·예시 분야)에는 영향이 없다.

## 7. 권고 후속 (병합을 막지 않음, 필요하면 E3 소과제로)

1. 잔여 한국어 오탐: `_NEURO_KO`의 인지 복합어 앞에 한글 부정 후방탐색을 붙인다.
   `(?<![가-힣])인지\s?(?:과학|과제|기능|능력|부하|저하|장애|심리)`
   내가 정규식만 따로 돌려 본 결과 `효과적인지 과제별로`·`것인지 기능 단위`는 안 잡히고 `인지 과제 수행`·`인지과학`·`작업기억 인지 부하`·`실험 인지 기능 저하`는 잡힌다. 테스트에 `~인지 과제`, `~인지 기능` 문장을 추가한다.
2. AI 용어 잔여 오탐: 영어를 `neuro(?!morphic|-?symbolic)\w*`로 좁히면 `neuromorphic`·`neuro-symbolic`은 빠지고 `neuroscience`·`neuroimaging`·`neurons`·`neuronal`은 유지된다(정규식 단독 확인). `hidden layer with 128 neurons`는 남는다(문맥 없이는 구분 불가). `neuromorphic`을 신경과학으로 볼지는 제품 판단이다(뇌를 본뜬 하드웨어라 애매).
3. 진짜 신경과학 재현율 회귀: 맨 `신경`(신경전달물질·신경 발달·도파민 신경)과 맨 `neural`(neural responses in cortex)을 더 이상 잡지 않는다. 실제 신경과학 계획서는 대개 `뇌`·`뉴런`·`fMRI`·`EEG`도 함께 쓰므로 분야는 대부분 유지된다(`plan_elife_neuro.md` 7→7). `신경전달`·`신경\s?(?:발달|가소성|손상)`을 넣는 정도로 보완할 수 있다.
4. 빌더 제안도 유효하다: `_en`의 `\b` 때문에 `fMRI를`·`EEG와`처럼 영어 약어 뒤에 조사가 붙으면 못 잡는다. 모든 `_en` 사전 공통이고 요소 판정 줄 번호에 영향이 있으니 따로 다룬다.

## 최종 판정

**PASS.** `pde_operator.md`가 신경과학에서 물리·공학으로 바뀌었고, 템플릿·예시·데모 11건 전부에서 AI 방법 어휘가 신경과학 표지로 잡히지 않는다. 진짜 신경과학 데모는 그대로다. 판정 로직은 287건 차등 검사에서 field 외 전부 동일하고, 변경은 소유 경로(`fitness.py`, `tests/e3/`, 보고서) 안이며, `tests/e3` 368 통과·`verify.py` 통과다. 남는 한계(3-1의 `neuromorphic`류, 3-3의 `~인지 과제`, 3-2의 재현율 회귀)는 위 후속으로 다루면 된다.
