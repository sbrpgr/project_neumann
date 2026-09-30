# E4-L1e 보고서 — 입력 화면 예시·템플릿을 AI for Science에 맞게 교체(대표 지시)

- 빌더: Claude Opus 5.5 · 브랜치 `task/E4-L1e` · 기준 커밋 `8a26813` · 지시문: PM 메시지(docs/tasks에 파일 없음)
- 결과: 예시 3건(새로 2건), 템플릿 5종 재정렬, 범위 안내 3분야, 로컬 검색 확인, 테스트·스크린샷·verify 모두 직접 실행해 통과
- 실제 OpenAI 호출 0건(검색은 로컬 bge-m3 + BM25, 화면 서버는 `NEUMANN_LLM_PROVIDER=mock`)

## 무엇을 했나

### 1. 예시 3건 (`src/neumann/api/templates/examples/`, 새 폴더)

| id | 이름 | 분야 | 연결 템플릿 | 파일 |
|---|---|---|---|---|
| `example-battery` | 전해액 이온전도도 GNN | 소재·화학·분자 | `materials-gnn` | `tests/fixtures/plans/plan.md`(그대로 가리킴) |
| `example-binding` | 단백질-리간드 결합 친화도 예측 | 단백질·생물·신약 | `protein-binding` | `examples/protein_ligand_affinity.md`(새로) |
| `example-operator` | 신경 연산자 대기 유체 대리모델 | 물리·PDE·기후 | `pde-operator` | `examples/neural_operator_weather.md`(새로) |

새 두 건은 plan.md와 같은 형식이다: 제목 1줄, 5칸(연구 목표·방법·데이터·평가·기대 성과), 한국어 본문에 영어 기술어·영어 문장 섞음, 길이 926·901자(plan.md 645자). 테스트가 형식·길이 범위(0.7~1.8배)를 잰다.

**② 단백질-리간드 결합 친화도 예측 등변 GNN** — 복합체 3차원 구조로 pKd를 예측하는 E(3)-equivariant GNN으로 가상 스크리닝의 도킹 점수 함수를 대체한다. 결합 포켓 원자 + 리간드 원자 그래프, 등변 메시지 전달. PDBbind v2020 general set 약 19,000개로 학습, CASF-2016 core set 285개로 테스트, ChEMBL 활성 화합물 약 30,000건은 Vina 도킹 포즈를 입력으로 쓴다. 평가는 Pearson·RMSE. 기대 성과: 도킹 점수보다 높은 상관, 후보 선별 비용 절감.

넣은 약점(신약 분야 심사평에서 자주 나오는 것 5개):
1. 무작위 분할, 스캐폴드·단백질 계열 묶음 없음 → 스캐폴드·표적 누출 (`We randomly split … without scaffold or protein-family grouping.`)
2. PDBbind general set과 CASF-2016 core set의 겹치는 복합체·유사 서열 제거 없음 (벤치마크 버전 간 중복)
3. 결정 구조 없는 ChEMBL 화합물은 도킹 포즈를 입력으로, **도킹 점수를 결합 친화도 라벨로** 사용 (라벨 신뢰성)
4. 기준선이 AutoDock Vina 점수 함수 1종뿐 (최근 딥러닝 모델과 비교 없음)
5. 단일 시드, 오차 막대 없음, 절제 실험 없음

**③ 신경 연산자 기반 대기 유체 대리모델** — FNO로 2차원 비압축성 Navier-Stokes와 전지구 대기 순환(ERA5)의 시간 전개를 학습, "격자 해상도에 무관하게" 수치 기상 모델보다 빠르게 10일 예측장을 만든다. FNO 층 4개로 6시간 뒤 상태 예측 → 반복 적용해 10일 롤아웃. Navier-Stokes 64×64 궤적 1,000개, ERA5 1979–2018 5.625°(32×64). 기준선 U-Net·ResNet. 기대 성과: 수천 배 빠르고 비슷한 정확도.

넣은 약점(PDE·기후 분야 5개):
1. 학습·평가 기간/해상도 중첩: 모든 시점을 무작위 80/10/10 분할, "같은 격자 해상도, 같은 기간"에서 학습·평가 (인접 시점 누출, 해상도 무관 주장 미검증)
2. 장기 롤아웃 안정성 미평가: 10일 롤아웃을 목표로 하면서 6시간 한 단계 예측만 평가
3. 물리 보존 법칙 미검증: 손실은 MSE뿐, 질량·에너지 보존·비발산 조건 반영·검사 없음
4. 수치 해법 대비 계산비용 비교 없음: "수천 배 빠르다"고 기대하면서 pseudo-spectral solver·IFS 대비 계산 시간 미측정
5. 단일 시드, 오차 막대 없음

① plan.md는 그대로다(무작위 분할·중복 미제거, 기준선 2종, 오차 막대·절제 없음, 코드·데이터 비공개).

### 2. 템플릿 5종 재정렬 (`src/neumann/api/templates/`)

| # | id | 이름 | 분야 | 골격 파일 |
|---|---|---|---|---|
| i | `materials-gnn` | 소재·배터리 GNN 대리모델 | 소재·화학·분자 | `materials_gnn.md`(그대로) |
| ii | `molecule-reaction` | 분자·화학 반응 예측 | 소재·화학·분자 | `molecule_reaction.md`(새로) |
| iii | `protein-binding` | 단백질 구조·결합 예측(신약) | 단백질·생물·신약 | `protein_binding.md`(`protein_molecule.md`에서 이름 바꾸고 결합·구조 중심으로 고침) |
| iv | `pde-operator` | PDE 신경 연산자·물리 시뮬레이션 | 물리·PDE·기후 | `pde_operator.md`(`physics_pde_climate.md`에서 이름 바꾸고 PDE 중심으로 고침) |
| v | `climate-emulator` | 기후·지구과학 에뮬레이터 | 물리·PDE·기후 | `climate_emulator.md`(새로) |

- 삭제: `neuro_fmri.md`(신경과학 fMRI), `medical_imaging.md`(의료영상)
- 골격 형식은 그대로: `# 연구계획서 — (연구 제목: 예) …)` + `## 1. 연구 목표`~`## 5. 일정`, 칸마다 채울 항목 `- …:`. 각 분야 심사에서 자주 지적되는 항목을 칸에 넣었다(신약: 서열·스캐폴드·표적 분할과 벤치마크 버전 간 중복 제거, 도킹·예측 구조 입력 시 성능 저하 / PDE: 보존량 오차, 장기 롤아웃, 같은 정확도에서 계산 비용 / 기후: 연도 단위 분할·기간 겹침 점검, 기후 통계 재현, 학습 기간 밖 조건)
- `catalog.json` `version` 1 → 2

### 3. 범위 안내

- `catalog.json` `scope.domains` = `["소재·화학·분자", "단백질·생물·신약", "물리·PDE·기후"]`(코퍼스 `fields` 3종과 같다)
- `index.html` 입력 화면의 고정 상수 `SCOPE`(API 실패 때 보이는 목록)도 같은 3분야로. "AI 활용 과학 연구 계획서 전용" 문구 유지. 입력 화면 외 부분(전송 고지·리포트·근거 패널)은 건드리지 않았다(`index.html` diff 1줄)

### 4. 로더·스키마 (`src/neumann/api/templates.py`, `catalog.schema.json`)

- 예시 경로 허용 폴더 두 곳: `src/neumann/api/templates/examples/`, `tests/fixtures/plans/`(스키마 패턴 + 로더의 `EXAMPLE_DIRS` 검사). 그 밖 경로·없는 파일은 거부(테스트 추가)

### 5. 테스트

- `tests/e4/test_templates.py`(기본 pytest): 새 카탈로그 스키마 통과, 망가진 카탈로그 11종 거부(새 예시 폴더의 없는 파일·허용 밖 경로 2종 추가), 템플릿 5종 id, 범위 = 코퍼스 3분야, 예시 3건 id↔경로·분야마다 1건·예시 분야 = 연결 템플릿 분야, examples/ 폴더 파일 = 새 예시 2건, 새 예시 형식(5칸·한영 섞임·길이), 새 예시의 약점 문구 존재, 카탈로그·골격에 신경과학·의료영상·fMRI·X선·폐렴 없음, 화면 `SCOPE` 상수 = 3분야, 라우트가 예시 원문을 글자 단위로 돌려줌
- `tests/e4/test_templates_ui.py`(Playwright, `NEUMANN_UI_TESTS=1`): 기본 포트 8140, 8010·8020 거부, 서버 하위 프로세스에 `NEUMANN_LLM_PROVIDER=mock` 강제, 화면에 범위 밖 분야가 남으면 실패, `--prefix`·`--shots`로 저장 장면 선택, pytest 실행은 tmp에 찍어 `docs/reports`의 E4-L1b 스크린샷을 덮지 않음

## 완료 기준별 측정

환경변수는 `_COMMON.md`대로, Python은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`.

### 1·2·3. 예시·템플릿·범위 — `pytest tests/e4 -q -k templates`

```
$ NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4 -q -k templates
................................s                                        [100%]
32 passed, 1 skipped, 108 deselected in 1.61s
```

### 4. 로컬 검색 확인 (API 없음)

명령: `PYTHONPATH=<main>/src NEUMANN_EMBED_BATCH=2 NEUMANN_LLM_PROVIDER=mock python docs/reports/E4-L1e_search_check.py <worktree> <main> out.json`
- main 체크아웃(`f93569c`)의 `neumann.index.search`, 색인 `data/index`(1,128편, `dense_model=bge-m3`), 하한 0.45(`calibrated:bge-m3`, E2-L1). 백엔드 `hybrid`, 강등 없음
- 질의 = 계획서 전문 1개(`search([전문], k=10)`), bge-m3는 한 프로세스에서 한 번만 로드, 배치 2, 끝나고 캐시 해제·`torch.cuda.empty_cache()`(실행 뒤 GPU 사용량 1,219MiB = 실행 전과 같음). 18초
- 검색한 파일: `protein_ligand_affinity.md` 926자 sha256 `0d75d00c63ab…`, `neural_operator_weather.md` 901자 `11a5f2e74984…`, `plan.md` 645자 `3d35460def76…`(커밋된 파일과 같다. 검색 뒤 문구 조정 없음)
- 판정 열: **색인 판정**은 `last_search_status()["relevance"]["verdict"]`(하한 기준). **주제**는 빌더가 제목·초록으로 매긴 것: ○ 같은 연구 주제 · △ 같은 분야·방법 계열, 과제 다름 · × 무관. **분야**는 논문의 코퍼스 `fields`(M 소재·화학·분자, P 단백질·생물·신약, F 물리·PDE·기후)

요약:

| 예시 | 색인 판정 | 1위 관련도 | 하한 넘은 편수 | 자기 분야 태그(상위 10) | 주제 ○/△/× |
|---|---|---|---|---|---|
| ① 전해액 이온전도도 GNN | related | 0.601 | 1,004 | 8/10 (M) | 0 / 6 / 4 |
| ② 단백질-리간드 결합 친화도 (새) | related | **0.711** | 1,100 | **9/10** (P) | **5 / 5 / 0** |
| ③ 신경 연산자 대기 유체 (새) | related | **0.661** | 843 | **10/10** (F) | **7 / 3 / 0** |
| 옛 fMRI 인지과제 분류 | related | 0.595 | 922 | 해당 분야 없음 | 0 / 3 / 7 |
| 옛 흉부 X선 폐렴 검출 | related | 0.596 | 1,001 | 해당 분야 없음 | 0 / 1 / 9 |

- 새 예시 2건은 자기 분야 논문을 상위에 찾는다(1위가 각각 등변 GNN 결합 부위 예측, 난류용 FNO). 조정 불필요
- 전문 질의는 5건 모두 하한을 넘는다(1,128편 중 843~1,100편). 긴 학술체 글에서 색인 판정 `related`는 변별력이 없다(E2-L1 기술 문서의 적용 범위와 같다). 차이는 1위 관련도와 상위 결과의 주제에서 난다
- 옛 두 예시는 주제 일치 0편. 코퍼스에 fMRI 2편, X-ray·radiograph 5편, pneumonia 0편뿐이다(제목+초록 정규식)
- ① plan.md도 주제 일치 0편(분자 GNN 일반만). 코퍼스에 electrolyte·ionic conductivity 1편, battery 2편뿐이다. 지시대로 plan.md는 고치지 않았다(데모 fixture). 참고: binding affinity 19편, PDBbind 7편, neural operator·FNO 54편, ERA5·weather 38편

상위 10편:

**① 전해액 이온전도도 GNN** (`plan.md`)

| # | 제목 | score | dense | 분야 | 주제 |
|---|---|---|---|---|---|
| 1 | GraphGPT: Graph Learning with Generative Pre-trained Transformers | 0.567 | 0.601 | M,P | △ |
| 2 | Interpreting Equivariant Representations | 0.565 | 0.599 | M | △ |
| 3 | GraphDeepONet: Learning to simulate time-dependent PDEs using graph neural network and deep operator network | 0.565 | 0.599 | F | × |
| 4 | Graph Neural Preconditioners for Iterative Solutions of Sparse Linear Systems | 0.560 | 0.595 | F | × |
| 5 | Learning Ante-hoc Explanations for Molecular Graphs | 0.559 | 0.593 | M | △ |
| 6 | Graph Neural Networks for Interferometer Simulations | 0.555 | 0.589 | M,F | × |
| 7 | Hybrid Directional Graph Neural Network for Molecules | 0.555 | 0.588 | M | △ |
| 8 | A Theoretically-Principled Sparse, Connected, and Rigid Graph Representation of Molecules | 0.554 | 0.588 | M | △ |
| 9 | Equivariant Denoisers Cannot Copy Graphs: Align Your Graph Diffusion Models | 0.554 | 0.587 | M | △ |
| 10 | Graph Transformers Dream of Electric Flow | 0.553 | 0.587 | M | × |

**② 단백질-리간드 결합 친화도 예측** (`protein_ligand_affinity.md`, 새)

| # | 제목 | score | dense | 분야 | 주제 |
|---|---|---|---|---|---|
| 1 | EquiPocket: an E(3)-Equivariant Geometric Graph Neural Network for Ligand Binding Site Prediction | 0.669 | 0.711 | M,P | ○ |
| 2 | Enhancing PPB Affinity Prediction through Data Integration and Feature Alignment | 0.625 | 0.665 | P | △ (단백질-단백질 결합) |
| 3 | VN-EGNN: E(3)- and SE(3)-Equivariant Graph Neural Networks with Virtual Nodes Enhance Protein Binding Site Identification | 0.625 | 0.665 | P | ○ |
| 4 | REBIND: Enhancing Ground-state Molecular Conformation Prediction via Force-Based Graph Rewiring | 0.615 | 0.655 | M | △ |
| 5 | GNNAS-Dock: Budget Aware Algorithm Selection with Graph Neural Networks for Molecular Docking | 0.610 | 0.648 | M,P | ○ |
| 6 | Rigid Protein-Protein Docking via Equivariant Elliptic-Paraboloid Interface Prediction | 0.600 | 0.639 | P | △ |
| 7 | Protein-Ligand Interaction Prior for Binding-aware 3D Molecule Diffusion Models | 0.599 | 0.637 | M,P | ○ |
| 8 | Protein-ligand binding representation learning from fine-grained interactions | 0.599 | 0.637 | P | ○ |
| 9 | Equivariant Protein Multi-task Learning | 0.598 | 0.636 | P | △ |
| 10 | Streamlining Generative Models for Structure-Based Drug Design | 0.597 | 0.636 | M,P | △ |

**③ 신경 연산자 대기 유체 대리모델** (`neural_operator_weather.md`, 새)

| # | 제목 | score | dense | 분야 | 주제 |
|---|---|---|---|---|---|
| 1 | Residual Factorized Fourier Neural Operator for simulation of three-dimensional turbulence | 0.618 | 0.661 | F | ○ |
| 2 | Spectral-Refiner: Accurate Fine-Tuning of Spatiotemporal Fourier Neural Operator for Turbulent Flows | 0.587 | 0.628 | F | ○ |
| 3 | Enhancing Solutions for Complex PDEs: Introducing Translational Equivariant Attention in Fourier Neural Operators | 0.580 | 0.621 | F | ○ |
| 4 | Comparing and Contrasting Deep Learning Weather Prediction Backbones on Navier-Stokes and Atmospheric Dynamics | 0.579 | 0.620 | F | ○ |
| 5 | PAC-FNO: Parallel-Structured All-Component Fourier Neural Operators for Recognizing Low-Quality Images | 0.576 | 0.617 | F | △ (영상 인식) |
| 6 | Physics-enhanced Neural Operator: An Application in Simulating Turbulent Transport | 0.569 | 0.611 | F | ○ |
| 7 | Guaranteed Approximation Bounds for Mixed-Precision Neural Operators | 0.568 | 0.608 | F | △ |
| 8 | Tensor-GaLore: Memory-Efficient Training via Gradient Tensor Decomposition | 0.565 | 0.605 | F | △ |
| 9 | Sensitivity-Constrained Fourier Neural Operators for Forward and Inverse Problems in Parametric Differential Equations | 0.559 | 0.599 | F | ○ |
| 10 | Space and time continuous physics simulation from partial observations | 0.559 | 0.600 | F | ○ |

**옛 fMRI 인지과제 분류** (`plan_elife_neuro.md`, 비교)

| # | 제목 | score | dense | 분야 | 주제 |
|---|---|---|---|---|---|
| 1 | In vivo cell-type and brain region classification via multimodal contrastive learning | 0.573 | 0.595 | M,P | △ (신경 전기생리) |
| 2 | Spectral-Bias and Kernel-Task Alignment in Physically Informed Neural Networks | 0.564 | 0.586 | F | × |
| 3 | Informed Machine Learning with a Stochastic-Gradient-based Algorithm for Training with Hard Constraints | 0.564 | 0.586 | F | × |
| 4 | PhysPDE: Rethinking PDE Discovery and a Physical Hypothesis Selection Benchmark | 0.561 | 0.583 | F | × |
| 5 | BioBridge: Bridging Biomedical Foundation Models via Knowledge Graphs | 0.561 | 0.583 | M,P | × |
| 6 | Improved Active Learning via Dependent Leverage Score Sampling | 0.560 | 0.581 | F | × |
| 7 | Equivariant Protein Multi-task Learning | 0.557 | 0.578 | P | × |
| 8 | FIMP: Foundation Model-Informed Message Passing for Graph Neural Networks | 0.556 | 0.578 | P | △ (fMRI 실험 포함) |
| 9 | Most discriminative stimuli for functional cell type clustering | 0.556 | 0.577 | P | △ (신경과학) |
| 10 | Learning from Integral Losses in Physics Informed Neural Networks | 0.554 | 0.575 | F | × |

**옛 흉부 X선 폐렴 검출** (`plan_medimaging.md`, 비교)

| # | 제목 | score | dense | 분야 | 주제 |
|---|---|---|---|---|---|
| 1 | GeSubNet: Gene Interaction Inference for Disease Subtype Network Generation | 0.567 | 0.596 | P | × |
| 2 | Immunogenicity Prediction with Dual Attention Enables Vaccine Target Selection | 0.561 | 0.590 | P | × |
| 3 | ViTally Consistent: Scaling Biological Representation Learning for Cell Microscopy | 0.561 | 0.589 | M,P | △ (세포 영상) |
| 4 | Predicting perturbation targets with causal differential networks | 0.555 | 0.583 | P | × |
| 5 | Efficient Biological Data Acquisition through Inference Set Design | 0.554 | 0.582 | M,P | × |
| 6 | MeshMask: Physics-Based Simulations with Masked Graph Neural Networks | 0.551 | 0.578 | F | × |
| 7 | Equivariant Protein Multi-task Learning | 0.550 | 0.579 | P | × |
| 8 | Continuous Field Reconstruction from Sparse Observations with Implicit Neural Networks | 0.547 | 0.575 | F | × |
| 9 | EquiPocket: an E(3)-Equivariant Geometric Graph Neural Network for Ligand Binding Site Prediction | 0.546 | 0.573 | M,P | × |
| 10 | Does your model understand genes? A benchmark of gene properties for biological and text models | 0.545 | 0.573 | P | × |

### 5. Playwright 스크린샷(1440×900, 입력 화면) — 통과

```
$ NEUMANN_LLM_PROVIDER=mock python tests/e4/test_templates_ui.py --port 8140 --out docs/reports --prefix E4-L1e --shots input   # exit 0
 "scope_text": "AI 활용 과학 연구 계획서 전용\n소재·화학·분자\n단백질·생물·신약\n물리·PDE·기후",
 "templates_shown": ["i 소재·배터리 GNN 대리모델", "ii 분자·화학 반응 예측", "iii 단백질 구조·결합 예측(신약)",
                     "iv PDE 신경 연산자·물리 시뮬레이션", "v 기후·지구과학 에뮬레이터"],
 "examples_shown": ["전해액 이온전도도 GNN소재·화학·분자", "단백질-리간드 결합 친화도 예측단백질·생물·신약",
                    "신경 연산자 대기 유체 대리모델물리·PDE·기후"],
 "all_templates_fill": {"materials-gnn": true, "molecule-reaction": true, "protein-binding": true, "pde-operator": true, "climate-emulator": true},
 "examples_fill_and_select_template": {"example-battery": true, "example-binding": true, "example-operator": true},
 "example_meta": "예시 단백질-리간드 결합 친화도 예측\nprotein_ligand_affinity.md\n템플릿 단백질 구조·결합 예측(신약)\n이전 입력 되돌리기",
 "no_router_scope_text": "AI 활용 과학 연구 계획서 전용\n소재·화학·분자\n단백질·생물·신약\n물리·PDE·기후",
 "console_errors": [], "page_errors": [], "failed_requests": [], "external_requests": [],
 "screenshots": ["E4-L1e_input.png"], "problems": []
$ python -c "…connect_ex(('127.0.0.1',8140))…"
8140 free (server stopped)

$ NEUMANN_UI_TESTS=1 python -m pytest tests/e4/test_templates_ui.py -q
1 passed in 9.06s
```

- `docs/reports/E4-L1e_input.png`: 첫 화면(범위 안내 3분야 · 템플릿 i~v · 예시 3건). 콘솔 오류 0, 페이지 오류 0, 외부 요청 0
- 404 장면의 콘솔 오류 1건은 E4-L1b와 같이 `page.route`로 일부러 만든 것이라 따로 센다(본 흐름 0)
- 8010·8020은 쓰지 않았다(8020은 실행 때 사용 중이었다)

### 6. `python scripts/verify.py` — 통과

```
$ NEUMANN_LLM_PROVIDER=mock NEUMANN_LIVE_TESTS=0 python scripts/verify.py
960 passed, 25 skipped in 67.41s (0:01:07)
보안: 파일 351개
계약: 2개
테스트: 통과
verify 통과
```

### 실제 OpenAI 호출 여부 — 0건

- PM 긴급 공지(이 PC 사용자 환경변수에 `NEUMANN_LLM_PROVIDER=openai`)를 받고 이 세션의 명령을 다시 확인했다. python·pytest·Playwright 서버·검색 명령은 모두 `export NEUMANN_LLM_PROVIDER=mock` 뒤에 돌렸다(Playwright 서버 하위 프로세스는 코드에서도 mock 강제)
- `git commit`만 export 없이 돌았다. pre-commit 훅은 `scripts/verify.py --staged`(스테이징 보안 검사만, pytest·LLM 없음)라서 API를 부르지 않는다
- 검색 확인은 로컬 bge-m3 + BM25뿐이다(LLM 호출 경로 없음)

## 바꾼 파일

- 새로: `src/neumann/api/templates/examples/{protein_ligand_affinity.md, neural_operator_weather.md}`, `src/neumann/api/templates/{molecule_reaction.md, climate_emulator.md}`, `docs/reports/E4-L1e.md`, `docs/reports/E4-L1e_input.png`, `docs/reports/E4-L1e_search_check.py`(검색 확인 스크립트, 재현용)
- 이름 바꾸고 고침: `protein_molecule.md` → `protein_binding.md`, `physics_pde_climate.md` → `pde_operator.md`
- 삭제: `neuro_fmri.md`, `medical_imaging.md`
- 수정: `catalog.json`, `catalog.schema.json`(예시 경로 패턴), `src/neumann/api/templates.py`(예시 폴더 2곳 허용, 문서), `src/neumann/webui/index.html`(입력 화면 `SCOPE` 상수 1줄), `tests/e4/test_templates.py`, `tests/e4/test_templates_ui.py`
- 안 고침: `tests/fixtures/plans/*`, `contracts/`, `models.py`, `main.py`, 전송 고지·리포트·근거 패널

## 결정

- **① 전해액 예시는 fixture를 가리킨다(복사하지 않음)**: `tests/fixtures/plans/plan.md`는 데모 사전 계산 결과·`scripts/record_demo.py`(예시 `filename == "plan.md"`로 찾음)·정적 사이트 데모와 같은 원문이어야 한다. 복사하면 두 벌이 갈라질 수 있고 파일 이름이 바뀌면 녹화 스크립트가 예시 버튼을 못 찾는다. 그래서 예시 경로 허용 폴더를 `templates/examples/`와 `tests/fixtures/plans/` 두 곳으로 했다
- 템플릿 id를 내용에 맞게 바꿨다(`protein-molecule` → `protein-binding`, `physics-pde-climate` → `pde-operator`, 새 `molecule-reaction`·`climate-emulator`). 저장소에서 옛 id를 쓰는 곳은 이 과제 파일뿐이었다(grep). `example-battery` id는 `record_demo` 테스트가 쓰므로 그대로
- 템플릿 i 이름을 "재료·배터리" → "소재·배터리"로(지시문 표기, 범위 분야 "소재·화학·분자"와 맞춤). id·골격은 그대로
- ③ 예시의 연결 템플릿은 `pde-operator`(방법이 FNO라서). 기후 에뮬레이터 템플릿은 예시 없이 골격만
- 새 예시 약점은 분야마다 5개로 했다(지시 4~5개). 신약은 "기준선 1종"이 PDE에서는 "기준선 2종(U-Net·ResNet)"으로 약점 목록에서 뺐다(수치 해법 비교 부재는 4번 계산비용으로 다룸)
- 검색 확인은 제품 파이프라인의 축별 질의(`neumann.index.queries`)가 아니라 지시대로 **계획서 전문 1개 질의**로 했다
- Playwright는 한 장만 `docs/reports`에 저장했다(`--shots input`). 나머지 장면(템플릿·예시·판정 자리·404)도 같은 실행에서 검사는 모두 했다

## 사고 — git stash가 다른 worktree와 섞임 (PM 확인 필요)

- 커밋을 기능 단위로 나누려고 이 worktree에서 `git stash push --keep-index --include-untracked`를 썼다(19:56:04, 커밋 `544fb16`). stash는 모든 worktree가 같은 `refs/stash`를 쓴다. 그 사이 **`s2-E4-L2c` worktree의 에이전트가 `git stash pop`을 해 내 stash(`544fb16`)를 자기 작업 트리에 적용·삭제했고**, 내 `git stash pop`은 그쪽 stash(`69c9414`, 19:55:49, "WIP on task/E4-L2c: af008bb")를 받아 `src/neumann/api/serving.py` 충돌로 멈췄다(충돌이라 그 stash는 목록에 남았고, 이후 목록에서 사라졌다)
- 내 쪽 처리: 충돌로 생긴 `serving.py`(내 브랜치에 없는 파일)를 `git rm -f`로 지우고, 떠 있는 커밋 `544fb16`을 `git stash apply 544fb16`으로 되살렸다. 이후 stash를 쓰지 않았다
- **`s2-E4-L2c` 작업 트리에 이 과제의 커밋 안 된 변경(templates 카탈로그·골격·예시·`index.html` SCOPE·`test_templates.py`)이 들어가 있다**(읽기만 해서 확인: `git -C …/s2-E4-L2c status`). 그쪽 파일은 내 소유가 아니라 건드리지 않았다. E4-L2c 에이전트가 이 파일들을 커밋하지 않고 버리도록(`git checkout -- src/neumann/api/templates* src/neumann/webui/index.html tests/e4/test_templates.py` 등, 그쪽 판단) PM이 알려야 한다. 그쪽 stash `69c9414`는 떠 있는 커밋으로 남아 있어 `git stash apply 69c9414`로 되살릴 수 있다(E4-L2c가 필요하면)
- 제안(PM): `_COMMON.md`에 "worktree에서 `git stash` 금지(모든 worktree가 공유)" 한 줄

## 못 한 것

- 없음(지시 범위). 단, 아래는 이 과제 소유가 아니라 남겼다

## 다음 과제에 넘길 것

- E6(정적 사이트): `scripts/build_static_site.py`의 `DEMO_PLANS`와 `tests/e6/test_static_site.py`의 `DEMO_IDS`에 옛 fMRI·의료영상 데모(`plan_elife_neuro`, `plan_medimaging`)가 남아 있다. 대표 지시 취지(AI for Science)를 정적 데모에도 맞추려면 새 예시 2건으로 사전 계산을 다시 만들어야 한다(사전 계산은 대표 승인 없이 OpenAI로 돌리지 않는다)
- 템플릿 카탈로그는 `GET /templates`로 읽으므로 정적 사이트를 다시 빌드하면 새 템플릿·예시가 자동으로 들어간다
- ① 예시(plan.md)는 코퍼스에 전해액 논문이 1편뿐이라 상위 결과가 분자 GNN 일반이다. 데모 대표 예시로 결합 친화도·신경 연산자 쪽이 근거가 더 두텁다
- 화면 머리의 실명 배지는 E6-L3a 검증에서 이미 PM 결정 사항으로 올라가 있다(스크린샷에 보임, 이 과제는 건드리지 않음)
