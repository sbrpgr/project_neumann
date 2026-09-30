# E4-L1e 검증 보고서 — 입력 화면 예시·템플릿을 AI for Science에 맞게 교체

**PASS**

- 검증자: Claude Sonnet 5.5(빌더 Opus 5.5와 다른 모델) · 대상 `task/E4-L1e` 66c0b82(기준 8a26813) · worktree `s2-E4-L1e`
- 지시문 파일 없음(PM 메시지가 스펙). 빌더 보고서는 믿지 않고 직접 실행해 반증을 시도했다.
- 모든 python·pytest·서버 명령에 `NEUMANN_LLM_PROVIDER=mock`(과 `NEUMANN_LIVE_TESTS=0`)을 걸었다. 실제 OpenAI 호출 0건. `.env` 열지 않음, 키 출력 없음.
- 빌더 worktree에 남긴 파일 없음(`git status` 빈 출력, 임시 산출은 `AppData/Local/Temp/vl1e`에만 두고 삭제).

## 판정 표

| # | 항목 | 실행한 것 | 실제 결과 | 판정 |
|---|---|---|---|---|
| 1a | 새 예시 2건이 AI for Science인가 | 두 파일 전문 읽기 | 단백질-리간드 결합 친화도 등변 GNN(신약) / FNO 기반 Navier-Stokes·ERA5 대리모델(PDE·기후). 둘 다 방법·데이터·평가·기대 성과 5칸, plan.md와 같은 형식 | 통과 |
| 1b | 약점이 자연스럽게 들어 있나 | 문장 단위로 확인 | 신약 5개(무작위 분할·스캐폴드·계열 무시 / PDBbind–CASF 겹침 미제거 / 도킹 점수를 라벨로 / 기준선 1종 / 단일 시드·오차 막대·절제 없음), PDE·기후 5개(시점 무작위 분할·같은 격자·기간 / 한 단계만 평가하며 10일 롤아웃 주장 / 보존 법칙 미반영 / 계산 시간 미측정 / 단일 시드). 각각 계획서 본문의 자연스러운 서술이고 심사평에서 실제로 나오는 지적이다 | 통과 |
| 1c | 사실 어긋남 | 데이터셋 이름·규모·버전 대조 | 아래 "사실 확인" 참조. 어긋난 서술 없음 | 통과 |
| 1d | 표절·복사 흔적, 현장 작성 | 14자 조각 겹침(기획서·발표자료·시각자료·repo docs·tests·src 전체), 6-gram 단어 겹침(코퍼스 논문 49,418편 초록), 커밋 시각 | 겹치는 곳은 plan.md의 **틀 문장**뿐(제목 줄, "…를 목표로 한다.", "We randomly split … train/validation sets", "do not report error bars, and no ablation study is planned", "…것으로 기대한다"). 키트 문서의 본문 문장과 겹침 없음. 코퍼스 초록과 6-gram 겹침 0편. 커밋 4건 모두 2026-09-30 19:56~20:03(KST, 본선 당일) | 통과(틀 문장은 의도된 형식 맞춤) |
| 2 | 검색 확인 재현 | 빌더 스크립트가 아니라 **내 스크립트**로 `neumann.index.search.search([전문], k=10)`, main 색인 1,128편, `NEUMANN_EMBED_BATCH=2`, 한 프로세스 1회 로드 뒤 캐시 해제 | 결합 친화도: 순서·score·dense가 보고서 표와 10편 모두 같음(1위 EquiPocket 0.669/0.711 … 10위 0.597/0.636). PDE: 10편 모두 같음(1위 Residual Factorized FNO 0.618/0.661 … 10위 0.559/0.600). 파일 해시 앞 12자도 같음(`0d75d00c63ab`, `11a5f2e74984`). 판정 `related`, backend `hybrid`, 강등 없음. 소요 17.7초. GPU 사용량 실행 전후 1,219 MiB(해제 확인) | 통과 |
| 2b | 자기 분야 논문인가 | 상위 10편의 제목·초록 앞부분을 직접 읽음 | 결합 친화도: 분야 태그 9/10(`protein_biology_drug`; 4위 REBIND는 소재만), 결합 부위·도킹·단백질-리간드 결합 주제 5편(1·3·5·7·8위) + 같은 계열 5편. PDE: 분야 태그 10/10, FNO·난류·날씨 백본 등 같은 주제 7편(1·2·3·4·6·9·10위) + 같은 계열 3편(PAC-FNO 영상 인식, 혼합 정밀도 연산자, Tensor-GaLore). 빌더의 ○/△ 표시와 내 판독이 일치 | 통과 |
| 3a | 신경과학·의료영상 잔존 | 저장소 전체 grep(신경과학·의료영상·fMRI·neuro·X선·폐렴·medimaging 등), 카탈로그·골격 5종·`index.html`·`tests/e4/test_templates*.py`, `GET /templates` JSON, 렌더된 화면 텍스트·HTML | 소유 영역(카탈로그·골격·화면·템플릿 테스트) 안에는 "없음을 검사하는 문구"만 남음. 화면 텍스트·HTML에 0건. 저장소 다른 곳의 잔존은 이 과제 소유 밖(아래 "남은 것") | 통과 |
| 3b | Playwright 1440×900, 서버 8142, mock | 내 스크립트(빌더 테스트와 별개), uvicorn `main.app`을 8142에 띄움 → 검사 → 종료(PID 종료, 8142 free 확인) | 범위 안내 `AI 활용 과학 연구 계획서 전용 / 소재·화학·분자 / 단백질·생물·신약 / 물리·PDE·기후`. 템플릿 버튼 5개(i 소재·배터리 GNN 대리모델 / ii 분자·화학 반응 예측 / iii 단백질 구조·결합 예측(신약) / iv PDE 신경 연산자·물리 시뮬레이션 / v 기후·지구과학 에뮬레이터)를 눌러 모두 입력칸이 채워짐(680·772·844·832·863자). 예시 3건을 눌러 원문 길이 645·926·901자(원본 파일과 같음)로 채워지고 연결 템플릿 i·iii·iv가 선택됨. **콘솔 오류·경고 0, 페이지 오류 0, 실패 요청 0, 외부 요청 0, 4xx·5xx 0**. 스크린샷을 눈으로 확인(범위 안내·템플릿·예시 밑줄 링크 정상). 8010·8020 사용 안 함 | 통과 |
| 4a | `pytest tests/e4 -q -k templates` | mock | `32 passed, 1 skipped, 108 deselected in 1.65s`(skip 1건은 `NEUMANN_UI_TESTS=1` 전용 Playwright) | 통과 |
| 4b | `python scripts/verify.py` | mock, `NEUMANN_LIVE_TESTS=0`, 빌더 브랜치 | `960 passed, 25 skipped in 86.05s` · 보안 파일 351개 · 계약 2개 · `verify 통과`. 실행 뒤 worktree 깨끗 | 통과 |
| 4c | 소유 밖 변경·섞임 | `git diff main...task/E4-L1e --stat`, 커밋별 파일 목록, 이름 목록 대조 | 19개 파일, 전부 소유 안: `templates.py`, `templates/`(카탈로그·스키마·골격 5종·예시 2건·옛 골격 삭제), `index.html`(SCOPE 상수 1줄), `tests/e4/test_templates.py`·`test_templates_ui.py`, `docs/reports/E4-L1e*`. **`serving.py` 없음**(브랜치·main 둘 다 저장소에 그 파일이 없다). `contracts/`·`models.py`·`main.py`·`tests/fixtures` 변경 0. 커밋 4건 모두 위 범위만 건드림(stash 사고 흔적 없음) | 통과 |
| 4d | `tests/fixtures/plans/` 불변 | `git diff --stat main...task/E4-L1e -- tests/fixtures`, 기준~HEAD 대조 | 변경 0(4개 파일 그대로). 예시 ①은 복사가 아니라 이 파일을 가리킴 | 통과 |
| 4e | main과 충돌 | 기준 이후 main이 바뀐 31개 파일과 빌더 19개 파일의 교집합, main의 옛 id 참조 | 교집합 없음. main에서 옛 id·신경과학·의료영상을 쓰는 곳은 이 과제가 바꾸는 `catalog.json`뿐(fitness.py 분류표·calibrate 스크립트 문자열은 별개) | 통과 |
| 5 | 테스트가 항상 통과하지 않는가 | temp 복사본에서 조작 4종(코드는 안 고침) | `index.html` SCOPE에 '신경과학' 추가 → 화면 검사 실패 / 예시에서 "별도 제거 절차" 문장 삭제 → 약점 검사 실패 / 골격에 fMRI 삽입 → 신경·의료 잔존 검사 실패 / 카탈로그 분야에 '의료영상' 추가 → 2건 실패. 조작 전 32건 통과 | 통과 |
| 6 | 정직성 | 색인·검색 상태 표시, 인용, 규칙/LLM 표기 | 이 과제는 예시·템플릿·안내 문구만 바꾸며 인용·판정 경로를 건드리지 않음. 검색 확인은 로컬 bge-m3 + BM25이고 보고서가 "API 호출 0건"이라고 쓴 것과 내 확인이 같음 | 해당 없음/통과 |

## 사실 확인(예시 2건)

- 결합 친화도: PDBbind v2020 general set 약 19,000개(실제 19,443개), CASF-2016 core set 285개(57 클러스터 x 5), 평가 Pearson·RMSE(CASF scoring power 지표), AutoDock Vina, pKd, ChEMBL 모두 사실과 일치. "PDBbind general set에 CASF-2016 core set과 겹치는 복합체가 있다"는 약점은 실제 문헌에서 지적되는 누출이며 사실이다. 결정 구조 없는 화합물의 도킹 점수를 라벨로 쓰는 것은 허구가 아닌 실제 나쁜 관행이라 약점으로 자연스럽다.
- 신경 연산자: Navier-Stokes 점성 1e-3, 64x64, 궤적 1,000개, FNO 층 4개는 FNO 원논문 설정과 일치. ERA5 1979–2018, 5.625°(32x64)는 WeatherBench 표준 설정과 일치. 6시간 간격 x 40단계 = 10일 롤아웃, IFS(ECMWF)도 정확하다. "수천 배 빠르다"는 계획서의 기대 서술이라 사실 오류가 아니다(FourCastNet 등은 그 이상을 주장). 예시 어디에도 존재하지 않는 데이터셋 이름·버전은 없다.

## 남은 것(병합을 막지 않음, 다른 과제 몫 — PM 참고)

1. **정적 사이트·사전 계산 데모는 아직 옛 구성**: `scripts/build_static_site.py`의 `DEMO_PLANS`와 `tests/e6/*`, `data/precomputed`에 fMRI·의료영상 데모(`plan_elife_neuro`, `plan_medimaging`)가 남아 있다(빌더도 보고서에 적음). 새 예시 2건에는 사전 계산 결과가 없어서 정적 사이트에서는 눌러도 결과가 없고, 실서버(8010)에서는 실제 파이프라인을 돌려야 한다. E6에서 새 예시 2건 사전 계산(대표 승인 필요)과 `DEMO_PLANS` 교체를 해야 "화면 어디에도 안 남음"이 정적 사이트까지 이어진다.
2. **규칙 판정의 분야 이름표 오분류(E3-L1c 소유, 이 과제 아님)**: `analyze/fitness.py`의 `rule_fitness`는 정규식 `neur\w*`가 "Neural"에 걸려서 `pde_operator.md` 골격을 분야 "신경과학·뇌영상"으로 표시한다(내가 8개 파일에 돌려 확인. 새 예시 `neural_operator_weather.md`는 "기후·지구과학"으로 나옴). 규칙 비상 경로에서만 쓰이고 판정 자체는 `fit`이지만, 신경망 계획서에 "신경과학"이 붙을 수 있다. 분류표의 신경과학·의료 항목 정리를 E3-L1c 후속으로 넘길 것.
3. 빌더 보고서의 stash 사고: `s2-E4-L2c` worktree를 읽기 전용으로 확인했더니 지금은 작업 트리가 깨끗하고(커밋 83754ff 보고서에 "git stash 사고와 정리"가 있음) 이 과제 파일이 섞여 있지 않다. 이 브랜치 쪽은 커밋 4건 모두 소유 범위 안이라 병합에 영향 없음. `_COMMON.md`에 "worktree에서 git stash 금지" 한 줄을 넣자는 빌더 제안은 PM 판단.
4. 재현하지 않은 것: 옛 fMRI·의료영상 두 계획서의 검색 표(비교용이며 이 과제 결과물이 아님), ① plan.md의 검색 표(지시 범위가 새 예시 2건이었고 plan.md는 불변 fixture). 두 표는 빌더 보고서 값을 그대로 믿지 않고 "미확인"으로 둔다.

## 재현 명령

```bash
export NEUMANN_LLM_PROVIDER=mock NEUMANN_LIVE_TESTS=0 PYTHONIOENCODING=utf-8 PYTHONPATH="src;." HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export NEUMANN_RAW_DIR=".../공개자료" NEUMANN_DATA_DIR=".../project_neumann/data" NEUMANN_EMBED_MODEL=".../공개자료/models/bge-m3" NEUMANN_EMBED_BATCH=2
cd .claude/worktrees/s2-E4-L1e
python -m pytest tests/e4 -q -k templates          # 32 passed, 1 skipped
python scripts/verify.py                           # 960 passed, 25 skipped, verify 통과
git diff main...task/E4-L1e --stat                 # 19 files, 소유 안
```
