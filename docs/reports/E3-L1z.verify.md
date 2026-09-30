# E3-L1z 검증 보고서 (Claude Sonnet 5.5)

VERDICT: PASS-조건부

- 대상: `task/E3-L1z` HEAD `58d0069`(main `c8ba766` 병합 포함). 기준 비교는 `c8ba766`(main 병합 시점, `fitness.py`는 `4cbf0f0`·현재 main `f37100a`와 동일 파일).
- 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK`·`NEUMANN_LIVE_TESTS` 해제(OpenAI 호출 0). `.env` 열지 않음, 키 출력 없음. stash·commit·merge·push 없음. 빌더 worktree에 남은 파일 없음(검증 뒤 `git status`: 변경 없음, 무시 대상 `.pytest_cache`는 내가 시작하기 전부터 있던 것). 변이 실험은 스크래치 사본에서 하고 폐기했다.
- 소유 경로: `git diff c8ba766..HEAD --stat` = `fitness.py`, `tests/e3/test_fitness_diff.py`, `tests/e3/test_fitness_field.py`, `tests/e3/test_pipeline_parallel_status.py`(PM 추가), 보고서. `contracts/`·`models.py`·데이터·비밀값 변경 없음.

## 판정 요약

| # | 항목 | 결과 |
|---|---|---|
| 1 | 오탐 수정·새 탐지 재현 + 적대 사례 | 통과(오탐 수정·새 탐지 전부 재현, 진짜 신경과학 50건 이상 유지). **진짜 신경과학 5건 신규 누락(보고서 미공개), 잔여 오탐 4건(신규 아님)** |
| 2 | 지시문과 다른 결정 3가지 | 3가지 모두 타당. 단 결정 2에 미공개 회귀 1종 |
| 3 | main 대비 차등 | 재현(1,255건 동일). 내 코퍼스 5,185건에서도 분야 밖 반환값 차이 0 |
| 4 | ReDoS | 통과(최악 53 ms, 10만 자 935회) |
| 5 | PM 추가 테스트 | 통과(status 합치기 삭제를 9/10으로 잡음) |
| 6 | 중단 사고 | 통과(HEAD `fitness.py`는 의도한 수정본, 깨뜨린 흔적 없음) |
| 7 | pytest·verify | 통과(`verify.py`: 1335 passed, 27 skipped, 종료 코드 0). `tests/e3` 1회 시간 경합 실패(아래) |

## 1. 오탐 수정·새 탐지·적대 사례

직접 입력은 `rule_fitness(PlanDocument.from_text(...))["field"]`로 기준 모듈(`git show c8ba766:...`)과 HEAD를 나란히 실행했다.

오탐 수정(기준 → HEAD):

| 입력 | 기준 | HEAD |
|---|---|---|
| 효과적인지 과제별로 검증한다. | 신경과학 | 없음 |
| 나은 것인지 기능 단위로 분해한다. | 신경과학 | 없음 |
| 타당한 설계인지 부하 시험으로 확인한다. | 신경과학 | 없음 |
| neuromorphic hardware accelerator에 올린다. / Neuromorphic chips | 신경과학 | 없음 |
| neuro-symbolic reasoning으로… / Neurosymbolic / NeuroSymbolic AI / neuro symbolic 모델 | 신경과학 | 없음 |
| Neuromorphic과 neuro-symbolic를 비교 | 신경과학 | 없음 |

새 탐지(기준 없음 → HEAD): `EEG와 fMRI로…`·`EEG를`·`fMRI로`·`brain을`·`EEG_data를` → 신경과학; `DNA와 RNA를`·`RNA로`·`proteins를` → 생명과학; `LLM으로…NLP를`·`LLMs를` → 자연어처리; `x-ray로`·`X-Ray가`·`xray를` → 의료영상; `plasma를`·`quantum으로` → 물리·공학; `climate를`·`weather로` → 기후; `batteries를` → 재료·화학; `vision으로` → 컴퓨터비전. 로마자 낱말 한가운데(`brainstorming과 rebranding을`, `EEG2`, `3EEG`, `cellular`, `nlpx`, `xdna`, `dna2`, `Prox-ray`)는 잡지 않는다(32건 중 어긋남 0).

진짜 신경과학 유지(적대 사례 55건 이상, 기준과 HEAD 모두 신경과학): 경도인지장애 / 경도 인지장애 / 경도 인지 장애(MCI) / 인지 과제 수행 / 인지과제 / 사회인지기능 / 고령자의 인지 기능 저하 / 인지 능력 / 인지 부하 / 시각인지과제 / 인지 심리학 / 인지과학 / 인지 과학 / `(인지 과제)` / `"인지 과제"` / 줄 첫머리 `인지 과제` / `2인지 과제` / 전각 공백·nbsp 사이 / 전두엽의 인지 기능 / 알츠하이머 환자의 인지기능 / 뇌파 / 신경세포·신경 세포 / 신경망이 아닌 신경세포의 발화율 / 신경계 / 신경 영상 / 신경활동 / 신경 회로 / 뉴런 / `(EEG)` / `EEG/MEG` / neuroimaging을 / neuroscience / neurons and neuronal / `Neuro-Symbolic Neuroscience`(neuroscience 쪽은 유지) / neuromorphology / cognitive load task / cognitive와 / brain connectivity / brains of mice 등. 인공 신경망(`신경망으로`, `neural network를`, `neural operator`)과 `뇌우`는 계속 신경과학이 아니다.

### 발견 A — 진짜 신경과학 5건이 기준에서는 잡히고 HEAD에서는 놓친다 (보고서 미공개)

접두어가 붙은 "…인지" 뒤에 명사를 띄어 쓴 형태다. 낱말 첫머리가 아니라서 `(?<![가-힣])`에 걸리고, 붙여 쓴 갈래(`인지장애` 등)는 공백이 있어 안 잡는다.

| 입력 | 기준 | HEAD |
|---|---|---|
| 사회인지 기능을 평가한다. | 신경과학 | 없음 |
| 경도인지 장애 환자를 모집한다. | 신경과학 | 없음 |
| 신경인지 기능 검사를 시행한다. | 신경과학 | 없음 |
| 사회인지 과제를 수행한다. | 신경과학 | 없음 |
| 시각인지 능력을 본다. | 신경과학 | 없음 |

`사회인지 기능`(조현병·발달 연구), `신경인지 기능`, `경도인지 장애`(MCI의 흔한 띄어쓰기 변형)는 실제 표기다. 지시문 방식(앞에 `(?<![가-힣])`만)도 똑같이 놓치므로 빌더가 지시를 어긴 것은 아니고, 지시보다는 낫다(붙여 쓴 복합어를 살림). 그러나 보고서 §9 "남은 분야 누락"에 이 한계가 없다. 영향은 분야 표지(화면 문구)뿐이고 판정·요소 줄 번호에는 없다.

### 발견 B — 잔여 오탐(신규 아님, 기준에서도 오탐, 경미)

`neuro–symbolic`(en dash), `neuro-morphic`(하이픈으로 끊음), `표본이 30인지 과제별로`·`AUC가 0.9인지 기능별로`(숫자·로마자 바로 뒤의 "인지"는 한글이 아니라 뒤보기가 통과)는 여전히 신경과학으로 잡힌다. 지시문 정규식과 같은 한계다.

## 2. 지시문과 다르게 한 결정 3가지

1. **조사 경계는 분야 패턴에만.** 타당. 지시문은 "검토한다"와 "판정 로직은 분야를 뺀 반환값이 main과 같아야 한다"를 함께 요구한다. `_en`(요소·무관 사전)까지 `(?<![a-z0-9])…(?![a-z0-9])`로 바꾼 변이를 내가 직접 만들어(메모리 모듈, 파일 안 고침) 빌더 코퍼스 251건에 돌리니 분야 밖 반환값이 **184건**, 판정이 바뀐 것이 **42건**으로 보고서(§4 M4)와 정확히 같다. 남는 한계(`GNN을`·`CNN으로`가 방법 요소로 안 잡힘)는 §9에 적혀 있다.
2. **붙은 "인지" 복합어 유지.** 타당하고 지시문보다 낫다. 지시문 그대로(`(?<![가-힣])인지\s?…`) 하면 `경도인지장애`·`사회인지기능`이 빠진다. 스크래치 사본에서 그 변이를 넣어 `test_fitness_field.py`가 2건 실패하는 것을 확인했다(빌더는 차등 검사 포함 10건). 다만 발견 A(접두어+띄어쓴 명사)는 남는다.
3. **`neuro symbolic` 띄어쓰기 제외.** 타당. 지시문의 `-?symbolic`의 상위 집합이고, 진짜 신경과학 어휘 중 `neuro`+`symbolic`으로 시작하는 낱말은 없다(`neuromorphology`·`neuron`은 계속 잡힘, 확인함). 유니코드 대시·하이픈 끊김은 제외하지 못하는 것이 한계(발견 B).

## 3. main 대비 차등 (직접 재구성)

- 빌더 테스트 코퍼스(문서 11 + 무작위 240): 분야 밖 반환값 5종(`rule`·`fallback`·고정 LLM 3종) 모두 동일, 분야 변경 **42건**(보고서와 일치). 이 검사는 `pytest tests/e3/test_fitness_diff.py`로도 통과.
- **내 코퍼스**(빌더 것과 다른 어휘·시드 777·13, 각 1,500건 + 저장소 `docs/**/*.md` 8줄 창 1,897건 + `tests/fixtures/*.jsonl` 텍스트 + 빌더 코퍼스 251건 = **5,185건**): 분야 밖 반환값 차이 **0건**. 분야가 바뀐 입력 745건.
- 분야 변경의 설명: 입력을 줄 단위로 나눠 기준·HEAD의 분야 표지 일치(시작 위치)를 비교하고, 사라진 표지와 새로 잡힌 표지를 각각 원인으로 분류했다.
  - 사라진 표지 1,163건 = 인지 어미(앞이 한글인 띄어 쓴 `인지 과제` 등) 784 + `neuromorphic`/`neuro(-|공백)symbolic` 379.
  - 새로 잡힌 표지 2,297건 = 모두 앞뒤에 한글·밑줄 등 비ASCII 문자가 붙은 영어 표지(조사·밑줄).
  - **세 수정으로 설명되지 않는 표지 변화는 0건.**
  - 빌더 코퍼스만 보면 분야 변경 42건이 모두 이 셋으로 설명된다. 표본 15건을 눈으로 확인했고(예: `neuromorphic/… → 자연어처리`, `사회인지 과제…→ 컴퓨터비전`은 붙은 접두어 사례로 발견 A와 같은 종류) 이상 없음.

## 4. ReDoS

- 바뀐 정규식(`_NEURO_KO`, `_NEURO_EN`, 나머지 분야 영어 패턴 7개 = 서로 다른 객체 9개)을 빌더 것과 **다른** 반복 단위 65종(`인지 과제인지 `, `neuro--`, `neuro` + 공백 50개 + `symbolic`, `neuro‑`(비분리 하이픈), 1000자 알파벳+공백 등) + 임의 조합 20종으로 만든 10만 자 입력에 `finditer`: 935회 실행, **최악 53.4 ms**(`의료·의료영상` 영어 패턴, 임의 입력), 전부 0.2초 미만.
- 선형 확인: `_NEURO_KO`·`_NEURO_EN`을 10만 → 40만 → 160만 자(각 3회 최솟값)로 늘렸을 때 4~4.7배씩 늘어난다(제곱 아님). `인지 ` 반복 `_NEURO_KO`: 4 → 20 → 80 ms.
- 분야 표지 전체를 10만 자 단일 줄에 돌린 `rule_fitness`: 기준 대비 최대 40 ms 정도 더 느림(예: `인지 ` 121 → 151 ms, `뇌` 62 → 102 ms), 시간 폭발 없음.

## 5. PM 추가 테스트 `test_pipeline_parallel_status.py`

스크래치 사본에서 `_merge_v1`의 status 합치기 두 줄(`if _STATUS_RANK.get(out.status, 2) > …: status = out.status`)을 삭제:

| 변이 | 새 status 테스트 | 기존 `test_pipeline_parallel.py` |
|---|---|---|
| 원본 | 42(둘 합침) passed | 통과 |
| 두 줄 삭제 | **9 failed, 1 passed**(통과 1건은 실패 없는 대조군) — 실패 사유 `assert par.status == seq.status` / `'ok' == 'degraded'` | 32 passed(못 잡음: E3-L1y 검증과 같음) |
| 비교 방향 뒤집기(`>` → `<`) | 9 failed, 1 passed | — |
| 조건을 항상 참으로(마지막 단계 status로 덮어쓰기) | 2 failed, 8 passed | — |

status 합치기가 사라지거나 반대로 되면 새 테스트가 잡는다. 사본은 폐기했고 worktree의 `pipeline.py`는 건드리지 않았다.

## 6. 중단 사고: `fitness.py`

- `fitness.py`를 바꾼 커밋은 `39ebca9` 하나뿐이다(`git log -- src/neumann/analyze/fitness.py`: `39ebca9`가 이번 브랜치 유일). 이후 `34295f0`·`61d66b0`·`aa10d38`·`58d0069` 모두 `fitness.py`의 blob 해시가 `61b533c…`로 **동일**하다.
- `git diff c8ba766 HEAD -- src/neumann/analyze/fitness.py`를 전부 읽었다: 의도한 수정(`_en_ascii` 추가, `_NEURO_KO` 인지 두 갈래, `_NEURO_EN` neuro 부정 전방탐색, `_FIELDS` 영어 패턴을 `_en_ascii`로)뿐이다. `_en_ascii`의 경계는 `(?<![a-z0-9])…(?![a-z0-9])`, `_en`은 `\b` 그대로(변이 M2·M4의 흔적 없음).
- HEAD blob에 백스페이스(`\x08`)·널 바이트 0개(빌더가 겪은 `\b`→백스페이스 사고 흔적 없음). 커밋 로그·reflog에 이상 없음, 작업 트리 == HEAD.

## 7. 전체 pytest · verify

| 명령 | 결과 |
|---|---|
| `python -m pytest tests/e3 -q -p no:cacheprovider` | 1회차 `1 failed, 494 passed, 12 skipped`(아래), 2회차 **495 passed, 12 skipped**(빌더와 같은 수) |
| `python -m pytest tests/e3/test_fitness_field.py tests/e3/test_fitness_diff.py tests/e3/test_pipeline_parallel_status.py` | 110 passed |
| `python scripts/verify.py`(venv, mock) | **1335 passed, 27 skipped in 168.59s**, 보안 파일 415개, 계약 2개, 테스트 통과, `verify 통과`, 종료 코드 0 |

1회차 실패 `tests/e3/test_pipeline_parallel_sim.py::test_simulated_parallel_is_faster_and_same`는 E3-L1y의 **벽시계 시간** 단언(`par v1_wall_s < 2.6 × 0.24 s`) 테스트다. 이 과제가 건드린 파일이 아니고, 그 시각 이 컴퓨터에서 파이썬 프로세스 46개가 동시에 돌아 CPU 경합이 있었다. 같은 테스트를 단독으로 3회 돌리면 모두 통과하고, 이어진 2회차·`verify.py`도 통과했다. 이 과제와 무관한 시간 의존 테스트 취약성이다(발견 C).

## 발견 정리

- **A (조치 필요, 미공개 회귀)**: 접두어 + 띄어 쓴 `인지 …`(`사회인지 기능`, `경도인지 장애`, `신경인지 기능`, `사회인지 과제`, `시각인지 능력`)가 기준에서는 신경과학인데 HEAD에서는 놓친다. 보고서 §9에 없다.
- **B (경미, 신규 아님)**: `neuro–symbolic`(en dash)·`neuro-morphic`, 숫자·로마자 뒤 `…30인지 과제별로`가 여전히 신경과학으로 잡힌다.
- **C (참고, 이 과제 밖)**: E3-L1y `test_pipeline_parallel_sim.py`의 시간 단언이 CPU 경합에서 실패할 수 있다.
- 나머지 주장(1,255건 동일, 42건 원인, 최악 12.4 ms 계열 ReDoS, 변이 5종, PM 추가 검사, verify 1335)은 모두 재현됐다. 보고서 §2 표(11건 분야 전후 동일)도 `test_document_fields_equal_base`가 통과한다.

## 병합 전 필수 조치

1. `docs/reports/E3-L1z.md` §9에 발견 A(접두어+띄어 쓴 `인지 기능·과제·능력·장애`가 기준 대비 신규 누락, 지시문 방식과 같은 한계)를 한 줄 추가한다. 코드 변경은 필수가 아니다. 원하면 `_NEURO_KO`에 접두어 허용 목록(예: `사회|경도|신경|시각|청각|정서|언어|메타`)을 더해 고칠 수 있으나 그러면 새 테스트와 재차등 검사가 필요하다.
2. (권고, 선택) 발견 B의 잔여 오탐(en dash·끊긴 `neuro-morphic`, 숫자·로마자 뒤 `인지`)은 `_NEURO_KO` 뒤보기를 `(?<![가-힣A-Za-z0-9])`로 넓히면 줄일 수 있다. 다음 과제로 넘겨도 된다.

그 밖에 병합을 막는 문제는 없다(판정 로직 불변, 검사 통과).
