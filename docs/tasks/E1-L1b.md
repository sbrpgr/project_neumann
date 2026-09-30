# E1-L1b — eLife·Europe PMC(PLOS) 공개 심사평 수집 (앞당김, 컷 1순위)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5
- 목표 시간: 60분
- 소유: `src/neumann/sources/elife.py`, `src/neumann/sources/europepmc.py`, `scripts/collect_elife*.py`, `scripts/collect_europepmc*.py`, `tests/e1/test_elife*.py`, `tests/e1/test_europepmc*.py`

## 읽을 것

- 계획서 §3 L1 "소스 추가", §4 E1 L1(데모 2·3번 fMRI·의료영상 분야 보강 목적)
- `03_데이터_수집_명세.md` §1(접근·제약·속도 제한·함정), §2
- `부록/데이터소스/elife.md`, `부록/데이터소스/europepmc_plos.md`
- `부록/설계/02_data_schema.md` §4.2·§4.3(필드 매핑), §3.3(eLife 답변의 심사평 재인용 함정)
- `src/neumann/models.py`, `src/neumann/sources/corpus.py`(E1-L0의 저장 형식에 맞춘다)
- 데모 계획서: `tests/fixtures/plans/plan_elife_neuro.md`, `plan_medimaging.md`

## 만들 것

1. eLife 공개 심사평(공개 API, 무인증): 신경과학·fMRI·의료영상 등 데모 2·3번 분야 중심으로 수백 편 규모. 공개 심사평(public review)·평가(assessment)·저자 답변. 속도 제한과 재시도, 중간 저장
2. Europe PMC / PLOS 심사평 sub-article: 같은 분야 중심으로 가능한 만큼
3. 공유 데이터 폴더 `data/processed/elife_*.jsonl`, `europepmc_*.jsonl`(E1-L0과 같은 엔티티별 JSONL 형식) + manifest(건수·분야·sha256·소요 시간)
4. `load_corpus`가 이 소스를 함께 읽을 수 있게 하는 방법을 보고서에 적는다(`corpus.py`는 E1-L0 몫이라 직접 고치지 말고 제안)
5. 불변식: 출처 URL 100%, 신원 필드 0, 정규화 순서, eLife 답변의 심사평 재인용 분리

## 완료 기준

1. 소스별 편수·심사평 수·분야 분포 보고. 실패한 소스는 버리고 이유를 적는다(컷라인)
2. 무작위 표본 3건 원문 대조
3. `python -m pytest tests/e1 -q -k "elife or europepmc"`(네트워크 없이 도는 테스트), `python scripts/verify.py` 통과. 데이터 커밋 금지
