# E0b — 데이터 모델·설정 로더·공용 fixture·데모 입력

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5
- **목표 시간: `models.py`·`config.py`와 그 테스트를 25분 안에 먼저 커밋한다**(E1·E2·E3·E5 빌더가 기다린다). 전체 50분.
- 소유(PM이 이 과제에 위임): `src/neumann/models.py`, `src/neumann/config.py`, `tests/fixtures/`, `tests/e0/`

## 읽을 것

- 계획서 §2(무엇을 만드나, 윤리 가드레일), §3 L0, §4.0(골격), §4 E0·E3의 "불변식"
- `부록/설계/02_data_schema.md` §1(불변식 3개), §3(엔티티 정의 전부), §5(Provenance), §6(Excerpt·정규화 순서), §7(윤리 가드레일)
- `부록/설계/03_risk_taxonomy.md`: 최상위 위험 유형 R0~R9와 이름(하위 코드 R1.1 등은 문자열로 허용)
- `contracts/premortem_response.schema.json`, `contracts/ui_view.schema.json`
- `docs/HANDOFF.md` "설정 로더 요구사항"

## 만들 것

1. `src/neumann/models.py` (pydantic v2). **이 파일이 모든 에픽의 계약이다.** 단순하고 확실하게.
   - `Provenance`(source, source_url 문자열 그대로 보존·검증만, accessed_at tz-aware, content_sha256)
   - `Work`, `ReviewEvent`, `AuthorResponse`, `Decision`, `PostStatus`: 02_data_schema §3의 핵심 필드. 모든 영속 엔티티에 `provenance` 필수
   - **신원 필드 금지:** 기반 클래스가 클래스 생성 시 필드 이름에 `name`·`email`·`reviewer_id`·`author`·`orcid` 같은 신원 토큰이 있으면 `TypeError`. (`reviewer_pseudonym`은 `^rvw_[0-9a-f]{16}$`만 허용하는 예외 필드로 둘지 판단해 보고서에 적는다)
   - `Excerpt`: `excerpt_id`, `source_kind`(review/author_response/decision/post_status), `source_id`, `start`·`end`(원문 문자 오프셋), `text`, `text_sha256`, `source_url`. 생성 헬퍼 `Excerpt.from_source(source_text, start, end, ...)`는 **원문을 잘라서** `text`를 만든다. `verify_against(source_text) -> bool` 제공
   - `RiskCode`(R0~R9 Enum, 이름 포함), `RiskTag`(excerpt_id, risk_code, 하위 코드 문자열 선택, polarity, confidence, `generator`)
   - `Generator` Enum: `astra` · `rule` · `mock` (생성 방식 정직 표기)
   - `RiskCard`: card_id, risk_code, title, why_applies(계획서 줄 번호 목록 포함), evidence(Excerpt id 목록, **최소 1개 — 비면 생성 거부**), works(논문 id 목록), score 구성요소(similarity·frequency·severity·confidence·total), `generator`
   - `StageStatus`(stage, state: ok/degraded/skipped/error, detail) — 강등 기록용
   - `PlanDocument`(plan_id=sha256, lines: 줄 번호가 붙은 목록, session_id; 본문을 영속 저장하지 않는 dump 메서드)
   - `PremortemResult`: plan, similar_works, cards, statuses, (선택) expected_review·checklist 자리. `contracts/premortem_response.schema.json`과 모순되지 않게
   - 계약은 추가만 할 수 있게 설계한다(필수 필드를 최소로)
2. `src/neumann/config.py`: pydantic-settings `Settings`. 우선순위 **환경변수 > `.env`**(기본값). `.env` 위치는 저장소 루트(없으면 무시). `load_dotenv(override=True)` 금지. `openai_api_key`와 `pseudonym_salt`는 `SecretStr`. 키: `NEUMANN_LLM_PROVIDER`(openai|mock), `NEUMANN_LLM_MODEL`(기본 gpt-6-astra), `NEUMANN_LLM_TIMEOUT_S`, `NEUMANN_EMBED_MODEL`, `NEUMANN_RAW_DIR`, `NEUMANN_DATA_DIR`, API host/port. `get_settings()` 캐시 함수. 새 키를 넣으면 `.env.example`에 이름만 추가해야 하지만 `.env.example`은 PM 소유다 → 필요한 키 목록을 보고서에 적는다
3. 테스트 `tests/e0/`: 신원 필드 금지(TypeError), Excerpt 오프셋 대조(오프셋 0 포함, 조작된 text 거부), 증거 없는 RiskCard 거부, provenance 없는 Work 거부, **`.env`에 빈 `OPENAI_API_KEY=`가 있어도 환경변수 값이 이긴다**(임시 폴더의 가짜 .env와 가짜 키 문자열로 — 실제 키 금지), SecretStr repr에 값이 안 나옴
4. `tests/fixtures/`: 계약을 통과하는 작은 가짜 데이터(JSON/JSONL, 영어, 분명히 가짜인 내용)와 로더 `tests/fixtures/loader.py`
   - 두 분야(예: 분자 특성 예측 GNN, 의료영상 분할)에 걸친 Work 6편, ReviewEvent 12건(각 3~6문장, 실제 심사평 같은 지적: 베이스라인 부족, 누출, 단일 시드 등), Decision, 그에서 잘라 낸 Excerpt(오프셋 정확), RiskCard 2장
   - `tests/fixtures/plans/`: 키트 `부록/데모입력/`의 계획서 3건을 원본 그대로 복사(plan.md, plan_elife_neuro.md, plan_medimaging.md) + 음성 대조 입력 `negative_recipe.md`(연구와 무관한 조리법 글, 직접 작성)
   - 로더 테스트: 모든 fixture가 models로 읽히고 Excerpt가 원문 대조를 통과

## 완료 기준

1. `python -m pytest tests/e0 -q` 통과(출력 붙이기)
2. `models.py`·`config.py`만으로 첫 커밋(25분 안), 그다음 fixture 커밋
3. `python scripts/verify.py` 통과
4. 보고서에 모델 목록과 각 불변식을 어느 테스트가 검사하는지 표로
