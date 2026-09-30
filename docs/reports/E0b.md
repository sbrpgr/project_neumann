# E0b 보고서 — 데이터 모델·설정 로더·공용 fixture·데모 입력

- 빌더: claude-opus-5.5 · 브랜치 `task/E0b` · 시작 18:18(브랜치 생성) · 첫 계약 커밋 18:24(6분)

## 무엇을 했나

| 커밋 | 내용 |
|---|---|
| `73a264b` 18:24 | `src/neumann/models.py`, `src/neumann/config.py`, `tests/e0/test_e0_models.py`, `tests/e0/test_e0_config.py` (계약 먼저) |
| `aab4226` 18:26 | `tests/fixtures/`(JSONL·로더·생성기·계획서 4건), `tests/e0/test_e0_fixtures.py` |
| (이 커밋) | fixture 생성기를 LF 고정으로 수정, 이 보고서 |

## 완료 기준별 측정

### 1. `python -m pytest tests/e0 -q`

```
$ C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e0 -q
.............................................                            [100%]
45 passed in 0.30s
```

### 2. 첫 커밋은 models·config(+그 테스트)만, 그다음 fixture

```
$ git log --format='%h %ad %s' --date=format:'%H:%M:%S' -3
aab4226 18:26:53 [E0b] 공용 fixture(가짜 Work 6·심사평 12·결정 6·발췌 12·카드 2·결과 1)와 로더, 데모 계획서
73a264b 18:24:22 [E0b] 데이터 계약 models.py·설정 로더 config.py와 불변식 테스트
17a4e13 18:18:23 [E0] PM 인수: ...
$ git show --stat --format= 73a264b
 src/neumann/config.py      |  65 +++++
 src/neumann/models.py      | 696 +++++++++++++++++++++++++++++++++++++++++++++
 tests/e0/test_e0_config.py | 106 +++++++
 tests/e0/test_e0_models.py | 301 ++++++++++++++++++++
 4 files changed, 1168 insertions(+)
```

### 3. `python scripts/verify.py`

```
$ C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/verify.py
.............................................                            [100%]
45 passed in 0.32s
보안: 파일 46개
주의: git 훅이 꺼져 있다. 켜려면  git config core.hooksPath .githooks
계약: 2개
테스트: 통과
verify 통과
```

(훅 경고는 worktree에서 verify가 설정을 읽는 방식 탓으로 보인다. 실제 커밋 때 pre-commit 훅이 돌아 `보안(스테이징) … verify 통과`를 찍었다. git 설정은 바꾸지 않았다.)

### 4. 모델 목록과 불변식 ↔ 테스트

| 모델 | 필수 필드 | 불변식(생성자에서 거부) | 검사하는 테스트 (`tests/e0/`) |
|---|---|---|---|
| `NeumannModel`(기반) | — | 필드 이름·별칭에 신원 토큰(`name email e_mail orcid author reviewer_id affiliation institution signature handle profile phone`) → 클래스 정의 시 **TypeError**. 예외는 `__identity_exempt_fields__`로만. 모르는 키 거부(`extra="forbid"`) | `test_identity_field_raises_typeerror_at_class_definition`(7종), `test_identity_alias_also_blocked`, `test_identity_exemption_is_explicit_only`, `test_extra_identity_key_rejected_at_runtime` |
| `Provenance` | source, source_url, accessed_at, content_sha256 | URL은 http(s)만·글자 그대로 보존, accessed_at tz-aware·미래 거부, sha256 64hex, `reviewcritique` 소스 거부 | `test_provenance_rules` |
| `SourcedRecord`(기반) | provenance | provenance 기본값 없음 | `test_work_without_provenance_rejected`, `test_other_sourced_records_require_provenance`(3종) |
| `Work` | work_id, title, url, provenance | DOI 정규화·형식 검사 | 위 + fixture 로드 |
| `ReviewEvent` | review_id, work_id, text, provenance | 본문 이메일·ORCID 거부, `reviewer_pseudonym`은 `^rvw_[0-9a-f]{16}$`만, created tz-aware | `test_reviewer_pseudonym_pattern_only`, `test_review_text_with_pii_rejected_and_redact_helper` |
| `AuthorResponse` | response_id, work_id, text, provenance | 본문 PII 거부 | (같은 기반 검증) |
| `Decision` | decision_id, work_id, outcome, outcome_raw, provenance | outcome Enum | `test_other_sourced_records_require_provenance[Decision]` |
| `PostStatus` | post_status_id, kind, provenance, (work_id 또는 target_doi) | 대상 하나는 필수 | `test_post_status_needs_target` |
| `Excerpt` | excerpt_id, source_kind, source_id, start, end, text, text_sha256, source_url | `end>start≥0`, `len(text)==end-start`, 공백뿐 거부, sha 일치. `from_source()`는 원문을 잘라 만든다. `verify_against(src)`는 글자·해시·원문 해시 대조 | `test_excerpt_from_source_slices_original_including_offset_zero`, `test_excerpt_middle_and_end_offsets`, `test_excerpt_tampered_text_rejected`, `test_excerpt_constructor_invariants`, `test_excerpt_detects_changed_source`, fixture `test_every_excerpt_matches_source_text` |
| `RiskCode` | — | R0~R9, `.slug`·`.title_ko`·`.title_en` | `test_risk_code_names_and_generator` |
| `Generator` | — | astra·rule·mock 셋만 | `test_risk_code_names_and_generator` |
| `RiskTag` | excerpt_id, risk_code, generator | 하위 코드가 risk_code 소속 | `test_subcode_must_belong_to_code` |
| `WhyApplies` | text | 계획서 줄 번호 ≥1 | fixture `test_premortem_result_fixture_matches_contract_and_plan_lines` |
| `RiskScore` | similarity, frequency, severity, confidence, total | 모두 0~1 | `test_score_bounds` |
| `RiskCard` | card_id, risk_code, title, why_applies, evidence(≥1), score, generator | **근거 없으면 생성 거부**, 빈 id 거부, 하위 코드 소속 | `test_riskcard_without_evidence_rejected`, `test_subcode_must_belong_to_code` |
| `StageStatus` | stage | state ∈ ok/degraded/skipped/error. JSON 키는 계약대로 name/status/reason | `test_premortem_result_dump_matches_contract_schema` |
| `PlanLine`·`PlanDocument` | plan_id, session_id, lines | 줄 번호 1부터 연속, plan_id == sha256(본문). `from_text()`가 NFC+LF·PII 가림. `dump_persisted()`는 본문 없음 | `test_plan_document_lines_and_no_body_in_persisted_dump` |
| `SimilarWork` | work_id, similarity | similarity −1~1 | fixture 결과 |
| `PremortemResult` | session_id, plan_id | `model_dump(mode="json")`이 `contracts/premortem_response.schema.json` 통과, 카드 근거 id가 모두 `evidence`에 있음, degraded/error 단계가 있으면 status 자동 "degraded", plan.plan_id 일치, `dump_persisted()`는 계획서 본문 없음 | `test_premortem_result_dump_matches_contract_schema`, `test_premortem_result_minimal_is_valid`, `test_premortem_result_rejects_dangling_card_evidence` |
| `config.Settings` | — | 환경변수 > `.env` > 기본값, 빈 값 무시, 비밀값 SecretStr | `test_env_var_beats_empty_dotenv_value`(빈 `OPENAI_API_KEY=` + 환경변수 가짜 키), `test_env_var_beats_nonempty_dotenv_value`, `test_dotenv_used_when_env_missing_and_empty_means_none`, `test_missing_dotenv_is_ignored_and_defaults`, `test_invalid_provider_rejected`, `test_secretstr_repr_hides_values`, `test_paths_from_env`, `test_get_settings_is_cached` |
| fixtures | — | 전부 models로 읽힘, Excerpt 전부 원문 대조 통과(오프셋 0 포함), 카드 근거·논문이 실재, 결과가 계약 스키마 통과, 데모 계획서 3건이 키트 원본과 sha256 동일 | `test_e0_fixtures.py` 6건 |

## 다른 빌더에게 (계약 요약)

- 가져오기: `from neumann.models import Work, ReviewEvent, Excerpt, RiskCard, ...`, `from neumann.config import get_settings`
- 수집기(E1) 순서: `normalize_text()` → `redact_pii()` → 엔티티의 `text`로 저장 → 그 문자열에서 `Excerpt.from_source(text, start, end, source_kind=..., source_id=..., source_url=...)`. 모델은 텍스트를 자동 변환하지 않는다(오프셋이 밀리지 않게).
- 리뷰어 핸들은 `make_reviewer_pseudonym(raw, scope=<포럼/논문 id>, salt=settings.pseudonym_salt.get_secret_value())`로만 저장.
- 새 필드 이름에 `name`·`author`·`handle`·`profile` 등이 들어가면 import 때 TypeError가 난다. `title`·`label`·`*_id`를 쓴다.
- E3: 카드는 `evidence`(excerpt id ≥1)와 `generator`가 필수. 규칙 경로면 `Generator.rule`, 결과 `stages`에 `StageStatus(stage=..., state="degraded", detail=...)`. `PremortemResult.evidence`에 카드가 인용한 Excerpt를 모두 넣어야 생성된다.
- E4: `PremortemResult.model_dump(mode="json")`이 그대로 응답 계약이다. 저장할 때는 `dump_persisted()`(계획서 본문 제외). 개발용 결과는 `tests/fixtures/premortem_result.json`.
- 테스트 fixture: `from tests.fixtures.loader import load_fixtures, plan_text` (pytest `pythonpath`에 `.`이 있어 동작).

## 결정 (스펙이 모호해서 고른 것)

1. **`reviewer_pseudonym`은 예외 필드로 두지 않았다.** 토큰(`reviewer_id` 등)에 걸리지 않는 이름이라 면제가 필요 없고, 대신 `^rvw_[0-9a-f]{16}$` 패턴만 허용한다. 면제 장치(`__identity_exempt_fields__`)는 `StageStatus.stage`(JSON 키 `name` = 단계 이름) 한 곳에만 쓴다.
2. **결과 필드 이름은 계약 스키마를 따랐다.** 스펙의 cards·statuses는 `risk_cards`·`stages`로 두었다(스키마와 모순 없게, `model_dump`가 그대로 스키마 통과). `StageStatus`는 파이썬 이름 stage/state/detail(스펙), JSON 키 name/status/reason(스키마) — 별칭, 양쪽 이름 모두로 생성 가능.
3. **PremortemResult에 스키마의 나머지 자유 칸(axes, claims, plan_checks, verification, manifest 등)을 기본값 있는 선택 필드로 모두 넣었다.** `extra="forbid"`라서 없으면 E3가 못 채운다.
4. **`extra="forbid"`를 전 모델에 적용.** 추가 키로 신원 정보가 새는 것을 막는다. 필드가 더 필요하면 PM에게 추가 요청.
5. `Excerpt`에 선택 필드 `source_sha256`(원문 전체 해시)을 더했다. `from_source`가 채우고, `verify_against`가 원문이 바뀌었는지도 잡는다.
6. `RiskCard.evidence`는 스펙대로 **Excerpt id 목록**이다(설계서 02의 Excerpt 객체 목록이 아님). 객체는 `PremortemResult.evidence`에 한 번만 싣는다.
7. `PlanDocument.from_text()`는 기본으로 이메일·ORCID를 가린다(거부 대신 마스킹 — 업로드 흐름을 끊지 않게).
8. 텍스트 PII 가드: `ReviewEvent`·`AuthorResponse`·`Decision`·`PostStatus`의 `text`에 이메일·ORCID가 있으면 거부. 이메일 정규식은 TLD를 알파벳으로 제한(`vIoU@0.3` 오탐 방지, 테스트 있음).
9. 설계서 02의 무거운 부분(라이선스 규칙, RiskScore 재계산, RiskFrequency, ExpectedReview, ChecklistItem, PlanDocument 24h 만료)은 넣지 않았다. "필수 최소" 지시에 따름. 필요해지면 선택 필드로 추가.
10. 테스트 파일 이름을 `test_e0_*.py`로 했다. `__init__.py` 없는 테스트 폴더끼리 같은 파일 이름(`test_models.py`)이면 pytest가 충돌한다.
11. `llm_provider` 기본값은 `.env.example`과 같은 `openai`. 테스트는 mock을 명시해야 한다.

## .env.example에 추가가 필요한 키 (PM 소유라 고치지 않음)

- `NEUMANN_LIVE_TESTS=` (실제 API 테스트 스위치, 기본 거짓). 나머지 키(`OPENAI_API_KEY`, `NEUMANN_PSEUDONYM_SALT`, `NEUMANN_LLM_PROVIDER`, `NEUMANN_LLM_MODEL`, `NEUMANN_LLM_TIMEOUT_S`, `NEUMANN_EMBED_MODEL`, `NEUMANN_RAW_DIR`, `NEUMANN_DATA_DIR`, `NEUMANN_API_HOST`, `NEUMANN_API_PORT`)는 이미 있다.

## 바꾼 파일

- `src/neumann/models.py`, `src/neumann/config.py`
- `tests/e0/test_e0_models.py`, `tests/e0/test_e0_config.py`, `tests/e0/test_e0_fixtures.py`
- `tests/fixtures/loader.py`, `tests/fixtures/make_fixtures.py`, `tests/fixtures/{works,reviews,decisions,excerpts,risk_tags,risk_cards}.jsonl`, `tests/fixtures/premortem_result.json`
- `tests/fixtures/plans/{plan.md, plan_elife_neuro.md, plan_medimaging.md}`(키트 원본 그대로), `tests/fixtures/plans/negative_recipe.md`(직접 작성)
- `docs/reports/E0b.md`

## 못 한 것

- 설계서 02 §3의 세부 규칙 다수(위 결정 9). 새 패키지는 필요 없었다.
- `Decision.outcome=unknown`일 때 `mapping_rule="unmatched:<원문>"` 강제는 넣지 않았다(계약을 이미 커밋한 뒤라 조이지 않음). E1이 지키면 좋다.

## 다음 (제안)

- PM: 루트 `tests/conftest.py`에서 `NEUMANN_LLM_PROVIDER=mock`을 기본으로 걸고 `get_settings.cache_clear()` — 테스트가 실수로 실제 API를 부르지 않게.
- PM: `.env.example`에 `NEUMANN_LIVE_TESTS=` 추가.
- E3: 카드 조립 불변식(카드당 근거 3건·논문 2편 이상, 최대 8장, R0 카드 금지)은 조립 단계에서 강제. 모델은 근거 ≥1만 강제한다.
- E5-L0: 근거 연결 검사기는 `Excerpt.verify_against()`와 `PremortemResult` 불변식을 그대로 쓰면 된다.
