# E3-L1d — 코퍼스 심사평 전체 astra 지적 추출 사전 캐시
- 빌더 Opus 5.5 · 검증 Sonnet 5.5 · 목표 40분 · 소유: `scripts/precompute_extract*.py`, `tests/e3/test_precompute_extract*.py` (추출 로직은 main의 `neumann.analyze.extract`를 그대로 호출, 수정 금지)
## 만들 것
코퍼스(1,128편) 심사평 전체를 E3 추출기로 미리 돌려 파이프라인과 **같은 캐시 키·위치**(`data/cache/`)에 채운다 → 실제 분석의 추출 단계(30~40초)가 캐시 적중으로 줄어든다. 병렬·재시도·중간 재개, OpenAI 속도 제한 준수, 진행률·비용(토큰) 로그. 실패 묶음은 건너뛰고 기록
## 완료 기준
전체 실행(백그라운드 허용) 결과: 적중 가능 심사평 수·실패 수·소요·토큰, 캐시 적중 뒤 데모 plan.md 분석 시간 전후 비교, `python scripts/verify.py` 통과. 8010 서버 건드리지 않기
