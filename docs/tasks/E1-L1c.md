# E1-L1c — eLife(신경과학·의료영상) 코퍼스를 검색에 합치기
- 빌더 Opus 5.5 · 검증 Sonnet 5.5 · 목표 45분 · 소유: `src/neumann/sources/corpus.py`(추가만), `scripts/build_index*`(E2와 겹치지 않게 새 옵션만), `tests/e1/test_corpus_elife*.py`
## 근거
E1-L1b 산출 `data/processed/elife_*.jsonl`(316편)과 보고서 `docs/reports/E1-L1b.md`(합치는 방법 제안), 데모 2·3번(fMRI·의료영상) 분야 보강 목적(계획서 §4 E1 L1)
## 만들 것
`load_corpus(..., include=("researcharcade","elife"))` 같은 추가 옵션, eLife 포함 색인을 **`data/index_elife/`**에 빌드(현재 `data/index/` 덮기 금지), 데모 2·3번 상위 10편 전후 비교(eLife 논문이 들어오는지)
## 완료 기준
오프셋 100%, 비교 표, 출처 URL·신원 필드 검사, `python scripts/verify.py` 통과. 전환은 설정(`NEUMANN_INDEX_DIR`)으로만
