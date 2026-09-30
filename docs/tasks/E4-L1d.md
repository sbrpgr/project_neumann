# E4-L1d — 메타 API: /api(코퍼스 실측 메타)·/taxonomy·/config/weights

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 35분
- 소유: `src/neumann/api/meta.py`, `tests/e4/test_meta*.py` (router만 제공, `main.py` 연결은 PM)
## 읽을 것
계획서 §4 E4 L1, 목업 `web/index.html`의 corpus·가중치 모달, `data/processed/corpus_manifest.json`, `data/index/manifest.json`, `부록/설계/03_risk_taxonomy.md`
## 만들 것
`GET /api`: 코퍼스 편수·분야별 수·심사평 수·거절 비율·색인 문장 수·빌드 시각(매니페스트에서, 실측만), `GET /taxonomy`: R0~R9 이름·설명·심각도(택소노미 문서 기준), `GET /config/weights`: 위험점수 가중치(설정 값, 없으면 기본값과 "기본값" 표시). 매니페스트가 없으면 빈 값과 사유
## 완료 기준
테스트(매니페스트 있음·없음), `python scripts/verify.py` 통과
