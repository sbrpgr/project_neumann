# E4-L2a — 내보내기 패키지(ZIP 9파일) (앞당김)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5
- 목표 시간: 45분
- 소유: `src/neumann/api/export.py`, `tests/e4/test_export*.py` (**`api/main.py`는 E4-L0 빌더가 작업 중이라 건드리지 않는다**)

## 읽을 것

- 계획서 §2 TRACE, §3 L2 "내보내기 패키지", §4 E4 L2(9파일 목록)
- `01_구조_뼈대.md` §1·§5의 내보내기 설명(파일 목록과 각 파일의 역할만 참고. 코드 없음)
- `src/neumann/models.py`(PremortemResult, RiskCard, Excerpt, SimilarWork, StageStatus)
- `tests/fixtures/`(premortem_result.json 등)

## 만들 것

1. `src/neumann/api/export.py`
   - `build_package(result: PremortemResult, *, plan_text: str | None = None) -> bytes`: ZIP 바이트. 9파일:
     `README.md`(무엇이 들었나, 생성 방식 표기, 강등 단계), `manifest.json`(파일별 sha256·크기, 생성 시각, 스키마 버전, 생성 방식별 카드 수), `risk_cards.json`, `evidence_pack.json`(카드별 근거 인용·원문 URL·오프셋·해시), `similar_works.csv`, `plan_annotated.md`(계획서 줄 번호 옆에 연결된 카드 표시. `plan_text`가 없으면 줄 번호 목록만), `neumann_report.md`(사람이 읽는 리포트), `ai_context.md`(다른 AI에 넘길 요약: 카드·근거 id·한계), `decision_log.json`(카드별 채택·보류·기각 기록 자리, 비어 있으면 빈 목록)
   - 카드 0장이어도 죽지 않고 이유를 README·리포트에 쓴다
   - 강등(`StageStatus` degraded·error)과 카드별 `generator`를 README·리포트에 정직하게 표기. 규칙 카드를 LLM 결과라고 쓰지 않는다
   - 개인정보: 계획서 본문은 `PlanDocument` 규칙대로(마스킹된 줄만). 키·환경변수 값 금지
   - FastAPI `router = APIRouter()`와 `POST /premortem/package`(입력: 결과 JSON 또는 계획서 텍스트 → 결과는 나중에 파이프라인이 채움) 핸들러를 이 파일에 둔다. `main.py`에 한 줄로 붙이는 것은 PM이 한다
2. 테스트: fixture 결과로 ZIP 생성 → 9파일 존재, manifest sha256 일치, 인용 텍스트가 evidence와 같음, 카드 0장·강등 결과 처리, 결정적 출력(같은 입력 → 같은 파일 내용, 생성 시각 제외)

## 완료 기준

1. `python -m pytest tests/e4 -q -k export` 통과
2. fixture 결과로 만든 ZIP의 파일 목록과 README 첫 20줄을 보고서에
3. `python scripts/verify.py` 통과
