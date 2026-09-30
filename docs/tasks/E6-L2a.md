# E6-L2a — 데모 사전 계산본·오프라인 폴백 (앞당김)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 50분
- 소유: `scripts/precompute_demo*.py`, `src/neumann/api/precomputed.py`, `tests/e6/`

## 읽을 것
- 계획서 §3 L2 "데모", §4 E4 L2(`GET /premortem/precomputed`, `GET /premortem/precomputed/{plan_id}`: 오프라인 폴백, 변조 시 404), §4 E6
- `src/neumann/models.py`(PremortemResult), 데모 계획서 `tests/fixtures/plans/`

## 만들 것
1. `scripts/precompute_demo.py`: 데모 계획서 3건을 `neumann.pipeline.run_premortem(plan_text) -> PremortemResult`(E3-L0이 만드는 중. 없으면 fixture 결과로 대체하고 표시)로 돌려 공유 폴더 `data/precomputed/<plan_id>.json` + 매니페스트(sha256, 생성 시각, 생성 방식별 카드 수, 소요 시간)
2. `api/precomputed.py`: FastAPI `router` — 목록·단건 조회, 매니페스트 sha256과 다르면 404(변조 감지), 응답에 "사전 계산본(생성 시각)" 표시. `main.py` 연결은 PM
3. 네트워크 없이 도는지 테스트(외부 호출 0)
## 완료 기준
1. fixture 기반 테스트: 목록·단건·변조 404·표시
2. `python scripts/verify.py` 통과
