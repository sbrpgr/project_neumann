# E1-L1c 보고서 — eLife(신경과학·의료영상) 코퍼스를 검색에 합치기

> **서비스 전환 금지 — E1-L1b 재작업 PASS 뒤 같은 명령으로 재빌드.**
> E1-L1b(eLife·Europe PMC 수집)가 검증에서 리뷰어 실명 잔존으로 FAIL했다(PM 재작업 중). `data/index_elife/`·`data/index_elife_epmc/`는 재작업 **전** 입력(`elife_reviews.jsonl` sha256 `6cc05a1e…`)으로 빌드됐으므로 실명이 남아 있을 수 있다. 두 폴더에 `DO_NOT_SERVE.txt`를 넣고 `manifest.json`에 `do_not_serve: {flag: true, reason, rebuild_command}`를 남겼다. `NEUMANN_INDEX_DIR`를 이 두 폴더로 두지 않는다.
>
> 재빌드 명령(저장소 루트, E1-L1b 재작업 PASS 뒤):
> ```
> python scripts/build_index_elife.py --batch 8 --include researcharcade,elife --out C:/Users/User/Desktop/project_neumann/data/index_elife
> python scripts/build_index_elife.py --batch 8 --include researcharcade,elife,europepmc --out C:/Users/User/Desktop/project_neumann/data/index_elife_epmc
> python scripts/build_index_elife_compare.py --new C:/Users/User/Desktop/project_neumann/data/index_elife        # 비교 다시
> ```
> 재빌드는 폴더를 새로 쓰므로 `DO_NOT_SERVE.txt`는 손으로 지운다(재작업 PASS 확인 뒤에만). 입력 해시 대조가 재작업 후 manifest와 맞아야 rc 0이다.
>
> **색인 문장 속 실명 패턴 건수**(재작업 전 입력, `index_elife_epmc` 문장 214,061개 전량, 이름 자체는 옮겨 적지 않음. `index_elife`는 같은 입력이라 eLife·OpenReview 행이 같다):
>
> | 패턴(그 패턴이 있는 문장 수) | eLife 33,655문장 | Europe PMC 46,637문장 | OpenReview 133,769문장 |
> |---|---|---|---|
> | **원본 캐시 명단의 리뷰어·편집자 전체 이름**(eLife `reviewers` 489명, JATS sub-article 기여자 409명) | **3** | **2** | - |
> | 원본 캐시 명단의 저자 전체 이름(6,248명, 리뷰어 신원은 아님) | 4 | 11 | - |
> | 이메일 · ORCID | 0 · 0 | 0 · 0 | 0 · 0 |
> | `Reviewer #N (이름 … signed)` · `reveal … identity: 이름` · `Dear 이름`(역할어·`[NAME]` 제외) | 0 · 0 · 0 | 0 · 0 · 0 | - |
> | 참고: `Dear …` 전체(역할어 포함, 대부분 "Dear Editor/Authors") · 맺음말 줄(`Sincerely,` 등) | 0 · 0 | 36 · 19 | 1 · 0 |
> | 참고: `reveal … identity` 문구(이름은 가려짐) · `Reviewer #N (… signed` 문구 | 177 · 0 | 0 · 6 | 0 · 0 |
> | 참고: 가림 표시 `[NAME]`가 있는 문장 | 497 | 56 | 0 |
>
> → 정규식 서명·인사·공개 문구는 모두 가려져 있지만, **원본 명단과 글자 그대로 맞는 리뷰어·편집자 이름이 eLife 3문장·Europe PMC 2문장에 남아 있다**(E1-L1b FAIL 사유와 맞는다). 잰 스크립트는 세션 임시 폴더에서 돌렸다(이름 명단은 원본 캐시 `data/cache/{elife,europepmc}`에서 읽고 출력하지 않음).

- 브랜치 `task/E1-L1c`(main b05de3c 기준) · 빌더 Claude Opus 5.5 · 검증 Sonnet 5.5 · 2026-09-30
- 입력: 공유 `data/processed/` 의 E1-L0 `works.jsonl` 등 + E1-L1b `elife_*.jsonl` · 출력: 공유 **`data/index_elife/`**(커밋 안 함)
- **`data/index/`·`data/index_l3/`는 건드리지 않았다**(빌드 전후 `manifest.json` sha256 `a0d1cf87…c38c62`·`22e5ec50…ec93` 같음, 두 폴더 파일 목록·크기·시각 같음).
- 스펙은 "316편"이라 했지만 E1-L1b 최종 산출물은 **500편**(E1-L1b 보고서: 316편 시점 뒤 500편으로 확장)이라 500편을 합쳤다.

## 무엇을 했나

| 파일 | 내용 |
|---|---|
| `src/neumann/sources/corpus.py` (추가만) | `load_corpus(data_dir, *, include=None)`: **include를 안 주면 지금과 똑같이** E1-L0 파일만 읽는다(기존 본문 그대로, 앞에 분기 한 줄). `include=("researcharcade","elife")`면 새 함수 `load_sources`가 소스별 접두 파일(`elife_works.jsonl` 등)을 합쳐 하나의 `Corpus`로 돌려준다(겹치는 work_id·고아 레코드·빠진 파일은 오류). `audit_sources`(소스별 전량 검사), `check_elife_decisions`(eLife 결정 매핑 원칙 검사), 소스 표(`SOURCE_FILE_PREFIXES`·`SOURCE_URL_PREFIXES`·딥링크·work_id 네임스페이스). `europepmc`도 같은 표로 읽을 수 있다(기본 포함은 아님). |
| `scripts/build_index_elife.py` (새 파일) | `scripts/build_index.py`(E2-L0)를 **고치지 않고** 불러, 입력 함수만 `load_corpus(include=...)`로 바꿔 끼운다. ① 출력이 `data/index`·`data/index_l3`·`NEUMANN_INDEX_DIR`·입력 폴더면 거부(rc 2) ② 빌드 전 `audit_sources` + `check_elife_decisions` 통과 필수(위반이면 rc 1, 색인 안 만듦) ③ 색인 입력 sha256을 소스 manifest(`corpus_manifest.json`·`elife_manifest.json`) `outputs`와 대조 ④ 소스별 논문·심사평·문장 수와 문장 오프셋 독립 재대조를 manifest `elife`에 덧붙임 ⑤ CUDA OOM이면 배치 반으로 재시도 ⑥ (검증 지적 반영) 입력 해시 불일치·오프셋 실패로 rc≠0이면 `--out` 폴더에 `DO_NOT_SERVE.txt`와 manifest `do_not_serve`를 **스크립트가 직접** 남기고, `전환: NEUMANN_INDEX_DIR=…` 안내는 성공일 때만 찍는다. 이미 있던 표시는 성공 재빌드에서도 지우지 않는다(manifest에 "이전 표시 유지") |
| `scripts/build_index_elife_compare.py` (새 파일) | 두 색인 문장 전량 오프셋 대조, 데모 3건 × (계획서 전문 · 짧은 영어) + 무관한 글, 상위 k 전후 비교(겹침·새로 든 논문의 소스·eLife 최고 순위·같은 논문 dense 차), `--json`·`--md` |
| `tests/e1/test_corpus_elife.py` | 20건: 기본 load_corpus 불변(eLife 파일이 옆에 있어도 무시), include 합치기, `("researcharcade",)` = 기본과 같은 레코드, 모르는·빈·빠진 소스, 겹치는 work_id, 고아 레코드, 검사기가 실제로 잡는지 6종(다른 호스트 URL·신원 키·딥링크 없음·소스 이름·네임스페이스·해시 형식), eLife 결정 매핑 위반 4종, 실제 eLife 산출물 검사 |
| `tests/e1/test_corpus_elife_index.py` | 11건: 보호 색인 거부(표기 달라도·`NEUMANN_INDEX_DIR`·`index_l3`), main 거부 rc 2, 가짜 두 소스 임베딩 없이 빌드(manifest `elife`·eLife Excerpt source_url=DOI), 입력 검사 위반이면 rc 1·색인 안 만듦, 해시 불일치 rc 1 + DO_NOT_SERVE·manifest 표시·전환 안내 없음, 오프셋 재대조 실패 표시, 성공이면 표시 없음·전환 안내, 이전 표시 유지, 비교 스크립트가 새로 든 eLife 논문을 잡는지, **실제 `index_elife` manifest 검사** |

`src/neumann/index/`(E2-L1 작업 중)·`scripts/build_index.py`·E2-L3 파일 이름(`build_index_l3.py`·`build_index_compare.py`)과 겹치지 않게 새 파일만 만들었다.

## 완료 기준별 결과

환경: `_COMMON.md`와 같다(`PYTHONPATH="src;."`, `NEUMANN_DATA_DIR=…/project_neumann/data`, `NEUMANN_EMBED_MODEL=…/bge-m3`).

### 1. 입력 검사 — 출처 URL 100%·원문 해시·신원 필드 0·eLife 결정 매핑

```
$ python -c "from neumann.sources.corpus import *; print(audit_sources(include=('researcharcade','elife','europepmc'))); c=load_corpus(include=('researcharcade','elife')); print(len(c.works),len(c.reviews),len(c.author_responses),len(c.decisions)); print(check_elife_decisions(c))"
{'records': {'researcharcade': {'works.jsonl': 1128, 'reviews.jsonl': 5366, 'author_responses.jsonl': 12660, 'decisions.jsonl': 1128},
             'elife': {'elife_works.jsonl': 500, 'elife_reviews.jsonl': 1224, 'elife_author_responses.jsonl': 499, 'elife_decisions.jsonl': 499},
             'europepmc': {...388, 845, 307, 388}},
 'records_total': 24932, 'source_url_ratio': 1.0, 'deeplink_ratio': 1.0, 'content_sha256_ratio': 1.0, 'identity_key_records': 0, 'violations': 0}   (4.6s)
1628 6590 13159 1627      (2.9s)
{'decisions': {'accept': 245, 'assessment_raw_preserved': 254, 'no_binary_decision': 254}, 'violations': 0}
```

| 검사 | 측정 | 결과 |
|---|---|---|
| 출처 URL | `provenance.source_url`이 그 소스 원문 API 접두(eLife `https://api.elifesciences.org/`, OpenReview `https://openreview.net/forum?id=`) | **1.0** (researcharcade+elife 23,004/23,004, europepmc 포함 24,932/24,932) |
| 딥링크 | `url`이 소스의 사람용 링크(eLife 논문 `elifesciences.org`, 심사평 `doi.org/10.7554/`) | 1.0 |
| 원문 해시 | `provenance.content_sha256` 64자리 hex(모델 검증 + 개수) | 1.0 |
| 신원 필드 | 원본 줄의 모든 키에 `models.IDENTITY_TOKENS` + writer·reviewer·signatures·readers·contrib·participants(모델 검증 **전에** 봄) | **0건** |
| 소스·네임스페이스 | `provenance.source` = 소스 이름, work_id 접두(`researcharcade_hf:`·`elife:`) | 위반 0, 소스 사이 work_id 겹침 0 |
| eLife 결정 매핑 | 신모델 254건 `no_binary_decision` + `outcome_raw` = 같은 논문 편집자 평가 `rating` 원문(예 `significance=valuable; strength=compelling`), 구모델 245건 `accept`(`elife_published_vor`), reject 0 | 위반 0, **원문 보존 254/254** |

색인 입력 해시 대조(빌드 manifest `elife.corpus_hash_check`): `works.jsonl`·`reviews.jsonl`(E1-L0 `corpus_manifest.json`), `elife_works.jsonl`·`elife_reviews.jsonl`(E1-L1b `elife_manifest.json`) **4/4 일치**.

### 2. 색인 빌드 `data/index_elife/`

```
$ nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader
3670 MiB, 2255 MiB                      # 다른 작업이 GPU를 쓰는 중 → 배치 8로(E2-L0 배치 16 최대 할당 1.35GB)
$ python scripts/build_index_elife.py --batch 8
[build_index_elife] 입력 검사 통과: 레코드 23004, 출처 URL 1.0, 원문 해시 1.0, 신원 키 0, eLife 결정 {'decisions': {'accept': 245, 'assessment_raw_preserved': 254, 'no_binary_decision': 254}, 'violations': 0}
[build_index_elife] ...\data\processed ['researcharcade', 'elife'] → ...\data\index_elife (배치 8)
[build_index] 입력 processed: 논문 1628편, 심사평 6590건 (3.9s)
[build_index] 임베딩 bge-m3 on cuda (로드 9.7s)
[build_index] 문장 167424개 (7.3s), 태그 12331개 (27.2s), BM25 0.2s, 임베딩 34.5s
[build_index] 오프셋 대조(메모리) 167424/167424, (디스크) 167424/167424
[build_index] 태그 종류 9: {'R0': 1464, 'R1': 492, 'R2': 2775, 'R3': 305, 'R4': 1368, 'R5': 896, 'R6': 2536, 'R7': 1338, 'R8': 1157}, 극성 {'negative': 9243, 'neutral': 1419, 'positive': 1669}
[build_index] 색인 ...\data\index_elife 128.10MB, 총 89.8s
[build_index_elife] 소스별 {'elife': {'excerpt_offsets_ok': 33655, 'excerpts': 33655, 'reviews': 1224, 'works': 500, 'works_with_reviews': 500},
                            'researcharcade': {'excerpt_offsets_ok': 133769, 'excerpts': 133769, 'reviews': 5366, 'works': 1128, 'works_with_reviews': 1068}}
[build_index_elife] 소스별 오프셋 재대조 167424/167424
[build_index_elife] 소스 manifest 해시 대조: True (대조 못 한 파일 [])
[build_index_elife] 전환: NEUMANN_INDEX_DIR=C:\Users\User\Desktop\project_neumann\data\index_elife
rc=0
$ nvidia-smi ...   → 1238 MiB, 4687 MiB   (빌드 프로세스 종료, 최대 할당 1.247GB·OOM 없음)
```

| 항목 | 현재 `data/index` | `data/index_elife` |
|---|---|---|
| 논문 | 1,128 (OpenReview) | **1,628** (OpenReview 1,128 + **eLife 500**) |
| 심사평 | 5,366 | 6,590 (+ eLife 1,224: 공개 심사평 545 · 편집자 평가 434 · 구모델 결정서 245) |
| 문장(Excerpt) | 133,769 | **167,424** (+ eLife **33,655**) |
| 규칙 태그 | 10,928 | 12,331 |
| 빌드 | 76.6s | 89.8s (배치 8) |
| 크기 | 102.1MB | 128.1MB |
| 로드 | 1.58s | 1.64s |

### 3. 오프셋 대조 100%

| 대조 | 결과 |
|---|---|
| 빌드 직후 메모리(`IndexStore.verify_offsets`: `원문[start:end] == text` + `Excerpt.verify_against` 해시) | 167,424 / 167,424 |
| 디스크 재로드 | 167,424 / 167,424 |
| 소스별 독립 재대조(`build_index_elife.py`가 따로 로드해 `review.text[start:end] == text`) | eLife 33,655/33,655 · OpenReview 133,769/133,769 |
| 비교 스크립트가 따로 로드해 다시 | 167,424 / 167,424 (현재 색인 133,769/133,769) |

**대조율 100%.** eLife 문장의 `source_url`은 심사평 sub-article DOI(예 `https://doi.org/10.7554/eLife.86740.3.sa0`)다.

### 4. 데모 상위 10편 전후 비교 (현재 `data/index` vs `data/index_elife`)

```
$ python scripts/build_index_elife_compare.py --json compare_elife.json --md compare_elife.md
[old] ...\data\index: 논문 1128편 {'researcharcade': 1128}, 문장 133769, 로드 1.58s, 오프셋 133769/133769
[new] ...\data\index_elife: 논문 1628편 {'elife': 500, 'researcharcade': 1128}, 문장 167424, 로드 1.64s, 오프셋 167424/167424
[plan/plan] 겹침 10/10, 새로 든 0 {}, eLife 최고 순위 None, 1등 0.37036 → 0.371837 (researcharcade)
[plan/en] 겹침 9/10, 새로 든 1 {'researcharcade': 1}, eLife 최고 순위 None, 1등 0.487116 → 0.499668 (researcharcade)
[plan_elife_neuro/plan] 겹침 0/10, 새로 든 10 {'elife': 10}, eLife 최고 순위 1, 1등 0.357768 → 0.395002 (elife)
[plan_elife_neuro/en] 겹침 0/10, 새로 든 10 {'elife': 10}, eLife 최고 순위 1, 1등 0.465887 → 0.604061 (elife)
[plan_medimaging/plan] 겹침 7/10, 새로 든 3 {'elife': 3}, eLife 최고 순위 2, 1등 0.36224 → 0.36224 (researcharcade)
[plan_medimaging/en] 겹침 8/10, 새로 든 2 {'elife': 2}, eLife 최고 순위 1, 1등 0.408281 → 0.422726 (elife)
[negative_recipe/unrelated] 겹침 10/10, 새로 든 0 {}, eLife 최고 순위 None, 1등 0.243076 → 0.243076 (researcharcade)
(18.2s, bge-m3 질의 임베딩 cuda, 끝나고 프로세스 종료)
```

질의: ① `plan` = 계획서 전문(`tests/fixtures/plans/*.md`, E2-L0·E2-L3와 같은 방식) ② `en` = 사람이 쓴 짧은 영어 한 줄(E2-L3 보조 질의와 같은 문장. LLM이 만든 검색어가 아니다. OpenAI 호출 없음). 점수 = 0.6·dense + 0.4·lexical(기본 설정).

| 데모 | 질의 | 겹침 | 새로 든 논문(그중 eLife) | eLife 최고 순위 | eLife 포함 상위 10 소스 | 1등 점수 현재→eLife 포함 | 1등 소스 | 같은 논문 dense 최대 차 |
|---|---|---|---|---|---|---|---|---|
| 1 전해액 | 계획서 | 10/10 | 0 (0) | - | OpenReview 10 | 0.3704 → 0.3718 | OpenReview | 0.00034 |
| 1 전해액 | 영어 | 9/10 | 1 (0) | - | OpenReview 10 | 0.4871 → 0.4997 | OpenReview | 0.00030 |
| **2 fMRI** | 계획서 | **0/10** | **10 (10)** | **1** | **eLife 10** | 0.3578 → **0.3950** | eLife | - |
| **2 fMRI** | 영어 | **0/10** | **10 (10)** | **1** | **eLife 10** | 0.4659 → **0.6041** | eLife | - |
| 3 의료영상 | 계획서 | 7/10 | 3 (3) | 2 | OpenReview 7 · eLife 3 | 0.3622 → 0.3622 | OpenReview | 0.00037 |
| 3 의료영상 | 영어 | 8/10 | 2 (2) | 1 | OpenReview 8 · eLife 2 | 0.4083 → 0.4227 | eLife | 0.00025 |
| 무관한 글 | 조리법 | 10/10 | 0 | - | OpenReview 10 | 0.2431 → 0.2431 | OpenReview | 0.00020 |

**데모 2 · fMRI 계획서 전문**

| # | 현재 색인 | 점수 | eLife 포함 색인 | 점수 | 소스 | 현재 순위 |
|---|---|---|---|---|---|---|
| 1 | In vivo cell-type and brain region classification via multimodal contra… | 0.358 | fMRI-based detection of alertness predicts behavioral response variabil… | 0.395 | eLife | 새 논문 |
| 2 | Spectral-Bias and Kernel-Task Alignment in Physically Informed Neural N… | 0.353 | Value signals guide abstraction during learning | 0.377 | eLife | 새 논문 |
| 3 | Informed Machine Learning with a Stochastic-Gradient-based Algorithm fo… | 0.353 | Multi-study fMRI outlooks on subcortical BOLD responses in the stop-sig… | 0.369 | eLife | 새 논문 |
| 4 | Equivariant Protein Multi-task Learning | 0.352 | Dynamic fMRI networks of human emotion | 0.368 | eLife | 새 논문 |
| 5 | BioBridge: Bridging Biomedical Foundation Models via Knowledge Graphs | 0.351 | Selective recruitment of the cerebellum evidenced by task-dependent gat… | 0.368 | eLife | 새 논문 |
| 6 | Improved Active Learning via Dependent Leverage Score Sampling | 0.351 | Neuroscout, a unified platform for generalizable and reproducible fMRI … | 0.368 | eLife | 새 논문 |
| 7 | PhysPDE: Rethinking PDE Discovery and a Physical Hypothesis Selection B… | 0.350 | Representational integration and differentiation in the human hippocamp… | 0.366 | eLife | 새 논문 |
| 8 | FIMP: Foundation Model-Informed Message Passing for Graph Neural Networ… | 0.350 | Modality-agnostic decoding of vision and language from fMRI | 0.363 | eLife | 새 논문 |
| 9 | Most discriminative stimuli for functional cell type clustering | 0.348 | Improving the accuracy of single-trial fMRI response estimates using GL… | 0.363 | eLife | 새 논문 |
| 10 | Learning from Integral Losses in Physics Informed Neural Networks | 0.347 | Prefrontal cortex state representations shape human credit assignment | 0.363 | eLife | 새 논문 |

**데모 2 · 영어 "classifying cognitive tasks from fMRI brain activation patterns with machine learning and independent component analysis"**

| # | 현재 색인 | 점수 | eLife 포함 색인 | 점수 | 소스 | 현재 순위 |
|---|---|---|---|---|---|---|
| 1 | In vivo cell-type and brain region classification via multimodal contra… | 0.466 | Dynamic fMRI networks of human emotion | 0.604 | eLife | 새 논문 |
| 2 | SimXRD-4M: Big Simulated X-ray Diffraction Data and Crystal Symmetry Cl… | 0.418 | Neural evidence of functional compensation for fluid intelligence in he… | 0.560 | eLife | 새 논문 |
| 3 | Brain-inspired $L_p$-Convolution benefits large kernels and aligns bett… | 0.410 | Relationship between cognitive abilities and mental health as represent… | 0.531 | eLife | 새 논문 |
| 4 | FIMP: Foundation Model-Informed Message Passing for Graph Neural Networ… | 0.408 | Predicting individual traits from models of brain dynamics accurately a… | 0.520 | eLife | 새 논문 |
| 5 | How Do Large Language Models Understand Graph Patterns? A Benchmark for… | 0.402 | Selective recruitment of the cerebellum evidenced by task-dependent gat… | 0.512 | eLife | 새 논문 |
| 6 | A path toward primitive machine intelligence: LMM not LLM is what you n… | 0.402 | Gaze patterns and brain activations in humans and marmosets in the Frit… | 0.512 | eLife | 새 논문 |
| 7 | Neuro-Causal Factor Analysis | 0.395 | Neural excursions from manifold structure explain patterns of learning … | 0.506 | eLife | 새 논문 |
| 8 | Modeling state-dependent communication between brain regions with switc… | 0.393 | Neuroscout, a unified platform for generalizable and reproducible fMRI … | 0.506 | eLife | 새 논문 |
| 9 | ZAPBench: A Benchmark for Whole-Brain Activity Prediction in Zebrafish | 0.392 | Physiological and motion signatures in static and time-varying function… | 0.505 | eLife | 새 논문 |
| 10 | Improved Active Learning via Dependent Leverage Score Sampling | 0.390 | Rapid encoding of task regularities in the human hippocampus guides sen… | 0.505 | eLife | 새 논문 |

**데모 3 · 의료영상 계획서 전문**

| # | 현재 색인 | 점수 | eLife 포함 색인 | 점수 | 소스 | 현재 순위 |
|---|---|---|---|---|---|---|
| 1 | GeSubNet: Gene Interaction Inference for Disease Subtype Network Genera… | 0.362 | GeSubNet: Gene Interaction Inference for Disease Subtype Network Genera… | 0.362 | OpenReview | 1 |
| 2 | Immunogenicity Prediction with Dual Attention Enables Vaccine Target Se… | 0.357 | A generalizable brain extraction net (BEN) for multimodal MRI data from… | 0.361 | eLife | 새 논문 |
| 3 | MeshMask: Physics-Based Simulations with Masked Graph Neural Networks | 0.357 | Immunogenicity Prediction with Dual Attention Enables Vaccine Target Se… | 0.358 | OpenReview | 2 |
| 4 | ViTally Consistent: Scaling Biological Representation Learning for Cell… | 0.357 | ViTally Consistent: Scaling Biological Representation Learning for Cell… | 0.357 | OpenReview | 4 |
| 5 | Predicting perturbation targets with causal differential networks | 0.353 | MeshMask: Physics-Based Simulations with Masked Graph Neural Networks | 0.357 | OpenReview | 3 |
| 6 | Equivariant Protein Multi-task Learning | 0.353 | Charting brain growth and aging at high spatial precision | 0.356 | eLife | 새 논문 |
| 7 | Efficient Biological Data Acquisition through Inference Set Design | 0.353 | Predicting perturbation targets with causal differential networks | 0.354 | OpenReview | 5 |
| 8 | EquiPocket: an E(3)-Equivariant Geometric Graph Neural Network for Liga… | 0.351 | Equivariant Protein Multi-task Learning | 0.353 | OpenReview | 6 |
| 9 | Does your model understand genes? A benchmark of gene properties for bi… | 0.350 | Efficient Biological Data Acquisition through Inference Set Design | 0.353 | OpenReview | 7 |
| 10 | Continuous Field Reconstruction from Sparse Observations with Implicit … | 0.348 | Introducing µGUIDE for quantitative imaging via generalized uncertainty… | 0.351 | eLife | 새 논문 |

**데모 3 · 영어 "convolutional neural network (ResNet, DenseNet) classifier for detecting pneumonia in chest X-ray images"**

| # | 현재 색인 | 점수 | eLife 포함 색인 | 점수 | 소스 | 현재 순위 |
|---|---|---|---|---|---|---|
| 1 | Modeling Divisive Normalization as Learned Local Competition in Visual … | 0.408 | Convolutional networks can model the functional modulation of the MEG r… | 0.423 | eLife | 새 논문 |
| 2 | Generalization of Scaled Deep ResNets in the Mean-Field Regime | 0.385 | Modeling Divisive Normalization as Learned Local Competition in Visual … | 0.408 | OpenReview | 1 |
| 3 | Joint Denoising of Cryo-EM Projection Images using Polar Transformers | 0.384 | Generalization of Scaled Deep ResNets in the Mean-Field Regime | 0.389 | OpenReview | 2 |
| 4 | BoneMet: An Open Large-Scale Multi-Modal Murine Dataset for Breast Canc… | 0.374 | Joint Denoising of Cryo-EM Projection Images using Polar Transformers | 0.383 | OpenReview | 3 |
| 5 | GRepsNet: A Simple Equivariant Network for Arbitrary Matrix Groups | 0.371 | EEG-based detection of the locus of auditory attention with convolution… | 0.374 | eLife | 새 논문 |
| 6 | Biological Sequence Analysis Using B ́ezier Curve | 0.367 | BoneMet: An Open Large-Scale Multi-Modal Murine Dataset for Breast Canc… | 0.371 | OpenReview | 4 |
| 7 | Brain-inspired $L_p$-Convolution benefits large kernels and aligns bett… | 0.362 | GRepsNet: A Simple Equivariant Network for Arbitrary Matrix Groups | 0.370 | OpenReview | 5 |
| 8 | Brain-inspired $L_p$-Convolution benefits large kernels and aligns bett… | 0.360 | Biological Sequence Analysis Using B ́ezier Curve | 0.365 | OpenReview | 6 |
| 9 | Derivative-Free Guidance in Continuous and Discrete Diffusion Models wi… | 0.359 | Brain-inspired $L_p$-Convolution benefits large kernels and aligns bett… | 0.362 | OpenReview | 7 |
| 10 | SimXRD-4M: Big Simulated X-ray Diffraction Data and Crystal Symmetry Cl… | 0.358 | Brain-inspired $L_p$-Convolution benefits large kernels and aligns bett… | 0.360 | OpenReview | 8 |

**데모 1 · 전해액 계획서 전문**: 상위 10편이 모두 같다(3·4위, 9·10위만 자리 바꿈, 점수 차 0.001 이하). 영어 질의는 9/10 겹침, 새로 든 1편(Energy-conserving equivariant GNN for elasticity, 10위)도 OpenReview 논문이다. eLife 논문은 상위 10편에 하나도 없다.

**판정(눈으로 본 것)**

1. **데모 2(fMRI)는 확실히 좋아진다.** 두 질의 모두 상위 10편이 **전부 eLife fMRI·신경영상 논문**으로 바뀐다(현재 색인은 fMRI 논문이 없어 세포 분류·PINN·GNN 논문이 나왔다). 1등 점수도 0.358 → 0.395(계획서), 0.466 → 0.604(영어)로 오른다. 과제 fMRI 연구뿐 아니라 Neuroscout(재현 가능한 fMRI 분석 플랫폼)·단일 시행 fMRI 반응 추정 같은 방법 논문도 이웃으로 온다(제목 기준). 그 심사평 문장이 근거 후보가 된다.
2. **데모 3(의료영상)은 조금 좋아진다.** eLife 2~3편(뇌 추출 네트워크 BEN·MRI 뇌 성장 차트·µGUIDE 정량 영상·MEG CNN·EEG CNN)이 들어오지만, **흉부 X선·폐렴 분류 논문은 eLife에 없다**(E1-L1b 보고: eLife는 의료영상+기계학습 논문이 드물다). 데모 3번의 주 보강원은 Europe PMC(PLOS Digital Health·PLOS ONE)다 → 아래 4b 참조.
3. **데모 1(전해액)은 그대로다.** eLife가 끼어들지 않고, 점수 변화는 BM25 idf·평균 길이 변화에서 오는 0.001~0.013이다. 같은 논문의 dense 점수 차는 최대 0.00037(fp16 저장 오차 수준).
4. **무관한 글**(조리법) 1등 0.243은 변하지 않았다(eLife 논문이 끼어들지 않음). 관련 질의(0.36 이상)와의 간격은 유지된다.

### 4b. Europe PMC 포함 색인 `data/index_elife_epmc/` (PM 추가 지시)

처음엔 세션 임시 폴더에서 참고 실험으로 돌렸고(19:42, 해시 대조 True, 뒤에 지움), PM 지시로 공유 폴더에 다시 빌드했다. `data/index`·`index_l3`·`index_elife`는 건드리지 않았다(빌드 전후 manifest sha256 `a0d1cf87…`·`22e5ec50…`·`084bbcae…` 같음. `index_elife`는 그 뒤 위의 DO_NOT_SERVE 표시만 더했다).

```
$ nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader
1229 MiB, 4696 MiB                      # 배치 8
$ python scripts/build_index_elife.py --batch 8 --include researcharcade,elife,europepmc --out C:/Users/User/Desktop/project_neumann/data/index_elife_epmc
[build_index_elife] 입력 검사 통과: 레코드 24932, 출처 URL 1.0, 원문 해시 1.0, 신원 키 0, eLife 결정 {'decisions': {'accept': 245, 'assessment_raw_preserved': 254, 'no_binary_decision': 254}, 'violations': 0}
[build_index] 입력 processed: 논문 2016편, 심사평 7435건 (4.8s)
[build_index] 임베딩 bge-m3 on cuda (로드 14.4s)
[build_index] 문장 214061개 (12.7s), 태그 15668개 (93.5s), BM25 1.2s, 임베딩 44.5s
[build_index] 오프셋 대조(메모리) 214061/214061, (디스크) 214061/214061
[build_index] 색인 ...\data\index_elife_epmc 161.37MB, 총 183.8s
[build_index_elife] 소스별 {'elife': {..., 'excerpts': 33655, 'excerpt_offsets_ok': 33655, 'reviews': 1224, 'works': 500},
                            'europepmc': {..., 'excerpts': 46637, 'excerpt_offsets_ok': 46637, 'reviews': 845, 'works': 388},
                            'researcharcade': {..., 'excerpts': 133769, 'excerpt_offsets_ok': 133769, 'reviews': 5366, 'works': 1128}}
[build_index_elife] 소스별 오프셋 재대조 214061/214061
[build_index_elife] 소스 manifest 해시 대조: False (대조 못 한 파일 [])
[build_index_elife] 실패: 색인 입력 해시가 소스 manifest와 다르다
rc=1
$ nvidia-smi ... → 1229 MiB, 4696 MiB   (프로세스 종료, 최대 할당 1.247GB, OOM 없음)
```

| 검사 | 결과 |
|---|---|
| 편수 · 심사평 · 문장 | **2,016편**(OpenReview 1,128 + eLife 500 + Europe PMC 388) · 7,435건 · **214,061개**(Europe PMC 46,637) |
| 오프셋 대조 | 메모리 214,061/214,061 · 디스크 214,061/214,061 · 소스별 재대조 214,061/214,061 · 비교 스크립트 재로드 214,061/214,061 → **100%** |
| 출처 URL · 딥링크 · 원문 해시 · 신원 키 | 24,932레코드 1.0 · 1.0 · 1.0 · **0건**, 위반 0 |
| eLife 결정 매핑 | no_binary_decision 254 = 원문 어휘 보존 254, accept 245, 위반 0 |
| **입력 해시 대조** | **불일치 → rc 1.** works 3종·OpenReview reviews는 일치, `elife_reviews.jsonl`(색인 `6cc05a1e…` vs 현재 manifest `b45045c3…`)·`europepmc_reviews.jsonl`(`cab0f50d…` vs `d11e4d67…`)이 다르다. 공유 `processed/`의 eLife·Europe PMC 파일이 **19:47에 다시 쓰였다**(E1-L1b 재작업). 색인은 그 전 파일을 읽었다(`index_elife`와 같은 eLife 입력). 검사기가 의도대로 잡은 것이고, 이 색인이 재작업 전 데이터라는 증거다 → DO_NOT_SERVE |
| 크기 · 빌드 | 161.4MB · 183.8s(태깅 93.5s: 다른 작업과 CPU 공유) |

```
$ python scripts/build_index_elife_compare.py --new C:/Users/User/Desktop/project_neumann/data/index_elife_epmc
[old] ...\data\index: 논문 1128편, 문장 133769, 오프셋 133769/133769
[new] ...\data\index_elife_epmc: 논문 2016편 {'elife': 500, 'europepmc': 388, 'researcharcade': 1128}, 문장 214061, 로드 2.87s, 오프셋 214061/214061
```

| 데모 | 질의 | 겹침 | 새로 든 논문(eLife / Europe PMC / OpenReview) | Europe PMC 포함 상위 10 소스 | 1등 점수 현재→Europe PMC 포함 | 1등 소스 |
|---|---|---|---|---|---|---|
| 1 전해액 | 계획서 | 10/10 | 0 | OpenReview 10 | 0.3704 → 0.3725 | OpenReview |
| 1 전해액 | 영어 | 9/10 | 1 (0 / 0 / 1) | OpenReview 10 | 0.4871 → 0.5072 | OpenReview |
| 2 fMRI | 계획서 | 0/10 | 10 (5 / 5 / 0) | eLife 5 · Europe PMC 5 | 0.3578 → 0.3944 | eLife |
| 2 fMRI | 영어 | 0/10 | 10 (3 / 7 / 0) | eLife 3 · Europe PMC 7 | 0.4659 → 0.6399 | Europe PMC |
| **3 의료영상** | 계획서 | **0/10** | **10 (0 / 10 / 0)** | **Europe PMC 10** | 0.3622 → **0.4103** | Europe PMC |
| **3 의료영상** | 영어 | **0/10** | **10 (0 / 10 / 0)** | **Europe PMC 10** | 0.4083 → **0.6422** | Europe PMC |
| 무관한 글 | 조리법 | 9/10 | 1 (0 / 1 / 0) | OpenReview 9 · Europe PMC 1(7위) | 0.2431 → 0.2431 | OpenReview |

- 데모 3(의료영상) 상위 10편이 **전부 Europe PMC의 흉부 X선·폐렴·의료영상 CNN 논문**으로 바뀐다. 계획서 전문 상위: Attention based automated radiology report generation using CNN and LSTM · A deep learning AI model for determining the relationship between X-Ray detectors and patient p… · Quantitative evaluation model of variable diagnosis for chest X-ray images using deep learning · CNNs trained with adult data are useful in pediatrics. A pneumonia classification example · Automated detection of COVID-19 through convolutional neural network using chest x-ray images.
- 데모 2(fMRI)는 eLife와 Europe PMC가 섞이고(Europe PMC: 3D CNN fMRI 설명가능성, fMRIPrep 잡음 제거 평가 등), 1등 점수가 eLife만 넣었을 때보다 더 오른다(영어 0.604 → 0.640).
- 데모 1은 그대로다(계획서 10/10). 무관한 글 1등 0.243은 그대로이고 Europe PMC 1편(흉부 CT 나이 추정)이 7위(0.232)에 들어온다.

### 5. 전환 방법 (설정으로만)

**지금은 전환하지 않는다**(맨 위 DO_NOT_SERVE). E1-L1b 재작업 PASS → 재빌드 → 해시 대조 rc 0 확인 뒤에 아래처럼 바꾼다.

코드 기본값은 그대로 `{NEUMANN_DATA_DIR}/index`다. eLife 포함 색인을 쓰려면 프로세스 환경변수(또는 main `.env`)에:

```
NEUMANN_INDEX_DIR=C:/Users/User/Desktop/project_neumann/data/index_elife
```

```
$ python -c "...get_index_settings().resolved_index_dir(); get_store(); get_excerpts('elife:86740')"
색인: C:\Users\User\Desktop\project_neumann\data\index
get_store 논문 1128 문장 133769
$ NEUMANN_INDEX_DIR=".../data/index_elife" python -c "..."
색인: C:\Users\User\Desktop\project_neumann\data\index_elife
get_store 논문 1628 문장 167424
get_excerpts elife:86740 39 'In uncertain conditions, decisions are not made in isolation' https://doi.org/10.7554/eLife.86740.3.sa0
```

- 서버(E4)는 재시작해야 한다(`get_store()`는 프로세스당 한 번 읽어 캐시). 8010 서버는 건드리지 않았다.
- 되돌리기: 변수를 지우면 `data/index`로 돌아간다. 두 색인 모두 bge-m3·`neumann-index-v1` 형식이라 질의 임베더는 그대로 쓴다.
- 결과에서 eLife 논문을 구분하려면 `work_id` 접두 `elife:`(또는 `neumann.sources.corpus.source_of_work_id`). 분야 태그 `neuro_fmri`·`medical_imaging`이 `Work.fields`에 있다.

### 6. 테스트·verify

```
$ python -m pytest tests/e1/test_corpus_elife.py tests/e1/test_corpus_elife_index.py -q
31 passed      (검증 지적 반영 뒤, NEUMANN_LLM_PROVIDER=mock: `pytest tests/e1 -q -k elife` → 31 passed, 125 deselected)
$ python scripts/verify.py        (NEUMANN_DATA_DIR=공유 data, 실제 index_elife·eLife 산출물 검사 포함)
910 passed, 21 skipped in 70.33s   (검증 지적 반영 뒤 NEUMANN_LLM_PROVIDER=mock 재실행: 913 passed, 21 skipped in 76.41s, 보안 파일 312개)
보안: 파일 311개
계약: 2개
테스트: 통과
verify 통과
```

## 바꾼 파일

- 추가: `src/neumann/sources/corpus.py`(기존 함수 본문·기본값 그대로, `load_corpus`에 키워드 전용 `include=None` 한 개와 분기 한 줄, 나머지는 새 함수·상수)
- 새로 만듦: `scripts/build_index_elife.py`, `scripts/build_index_elife_compare.py`, `tests/e1/test_corpus_elife.py`, `tests/e1/test_corpus_elife_index.py`, `docs/reports/E1-L1c.md`
- 고치지 않음: `src/neumann/index/`, `scripts/build_index.py`, 계약(`models.py`·`contracts/`), 다른 에픽 파일

## 결정 (스펙이 모호해서 고른 것)

1. **`load_corpus` 시그니처**: 스펙이 `load_corpus(..., include=(...))`를 요구하고 지시가 "기존 동작·시그니처 변경 금지, 기본값은 지금과 같게"라서, 위치 인자는 그대로 두고 **키워드 전용 `include=None`만 추가**했다. None이면 기존 본문이 그대로 돈다(테스트: eLife 파일이 옆에 있어도 무시, `manifest`도 기존 그대로). 합치는 일은 새 함수 `load_sources`가 한다.
2. **소스 이름** `researcharcade`(E1-L0 접두 없는 파일)·`elife`·`europepmc`. work_id 네임스페이스는 `researcharcade_hf:`·`elife:`·`europepmc:`.
3. **기본 포함은 researcharcade+elife**(스펙). Europe PMC는 `--include researcharcade,elife,europepmc`로 켤 수 있게만 했고 `data/index_elife`에는 넣지 않았다.
4. **빌드는 `build_index.py`를 고치지 않고 감쌌다**(E2-L3 방식). 입력 함수(`load_source`)만 이 스크립트 안에서 `load_corpus(include=...)`로 바꿔 끼운다. 색인 입력 해시는 색인이 읽는 파일(소스별 works·reviews)만.
5. **보호 폴더**: `data/index`, `data/index_l3`, `NEUMANN_INDEX_DIR`, 입력 폴더. 경로 비교는 `resolve` + 대소문자 무시.
6. **신원 키 검사는 모델 검증 전에** 원본 줄에서 본다. 모델이 모르는 키를 거부하는 경우에도 "신원 키"로 세기 위해서다.
7. **배치 8**: 빌드 직전 GPU 여유 2.2GB(다른 작업 사용 중). 최대 할당 1.25GB로 OOM 없이 끝났고, 끝나자 여유 4.7GB로 돌아왔다.
8. **비교 질의**는 계획서 전문 + 사람이 쓴 영어 한 줄(E2-L3와 같은 문장). astra 검색어는 OpenAI 호출 금지라 넣지 않았다.

## 못 한 것

- 실제 astra 검색어로의 전후 비교(OpenAI 호출 금지). 파이프라인이 붙은 뒤 `precompute_demo`를 두 색인으로 돌려 보면 된다.
- 점수 하한·alpha 재보정(E2-L1 범위). eLife 500편이 들어와도 무관한 글 1등 점수는 같았다.
- eLife 저자 답변(`AuthorResponse`)은 색인에 넣지 않았다. 현재 색인 형식(E2-L0)이 works·reviews만 담는다.

## 다음 과제에 넘길 것 / 제안

- **PM**: E1-L1b 재작업 PASS 뒤 맨 위 명령으로 두 색인을 재빌드하고 `DO_NOT_SERVE.txt`를 지운 다음에만 전환한다. 데모 2번(fMRI)은 `NEUMANN_INDEX_DIR=…/data/index_elife`, 데모 2·3번을 함께 살리려면 `…/data/index_elife_epmc` 한 줄 + 서버 재시작. 주 데모(1번)는 상위 10편이 같다. `.env.example`에 `NEUMANN_INDEX_DIR` 이름 추가 제안(비밀값 아님, E2-L0·E2-L3 제안과 같음).
- **데모 3번(흉부 X선)**: eLife만으로는 같은 주제 논문이 없고, Europe PMC 포함 색인(`data/index_elife_epmc`, 4b)에서 상위 10편이 모두 흉부 X선·폐렴 CNN 논문이 된다.
- **E1-L1b 재작업 검증**: 재빌드 뒤 이 보고서 맨 위 실명 패턴 표를 다시 재면 된다(원본 캐시 명단의 리뷰어·편집자 전체 이름이 문장에 0이어야 한다).
- **E2(L3 확대 색인과 합치기)**: `data/processed_l3`에 eLife 파일을 두면 같은 스크립트로 `--processed …/processed_l3 --out …/index_l3_elife`가 된다(단 `processed_l3`의 corpus_manifest 해시 대조가 함께 돈다).
- **E3·E5**: eLife 심사평 종류가 새로 들어온다(`public_review`·`editor_assessment`·`decision_letter`). 결정은 신모델 `no_binary_decision`(원문 어휘 보존)이라 채택률·백테스트에서 따로 다뤄야 한다.
