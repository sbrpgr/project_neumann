# E4-L1d 보고서 — 메타 API: /api · /taxonomy · /config/weights

- 브랜치: `task/E4-L1d` · 빌더: claude-opus-5.5 · 검증: Sonnet 5.5(예정)
- 소유 경로만 고쳤다: `src/neumann/api/meta.py`, `tests/e4/test_meta.py`, 이 보고서. `main.py`·`contracts/`·`models.py`·`config.py`는 건드리지 않았다.

## 무엇을 했나

`neumann.api.meta.router`(FastAPI `APIRouter`)에 라우트 3개를 만들었다. main 연결은 PM이 한다.

| 라우트 | 내용 | 없을 때 |
|---|---|---|
| `GET /api` | 공유 데이터 폴더의 `processed/corpus_manifest.json`·`index/manifest.json` 값을 그대로 옮긴다. 코퍼스 편수(`selection.works`), 분야별 수(`selection.by_field`·`by_field_ko`), 학회별 수, 심사평 수(`outputs["reviews.jsonl"].records`, 공식 심사평·메타리뷰 내역), 결정 수·거절 비율(`decisions.reject_ratio`), 색인 문장(발췌) 수(`counts.excerpts`), 태그 수, 오프셋 검사, 빌드 시각(`built_at`)·코퍼스 생성 시각(`generated_at`), 출처·라이선스, `summary_ko` 한 줄 요약, 색인 입력 해시와 코퍼스 출력 해시 대조(`matches_corpus`) | 값은 `null`, 사유는 섹션 `reason`과 최상위 `reasons`. `status`: `ok` / `partial`(한쪽 없음·필드 누락·해시 불일치) / `unavailable`(둘 다 없음). 항상 200 |
| `GET /taxonomy` | R0~R9: 코드, slug, 한·영 이름(`models.RISK_NAMES`), 설명(03_risk_taxonomy §3 "정의"), 심각도 기본값 S1~S5와 등급 이름, 탐지 경로, 위험카드 생성 여부, Macro-F1 측정 대상 여부, 소분류 id. 심각도 표(§2.3), 버전 v1.0, Tier-1 10 / Tier-2 59 | 정적 데이터라 항상 있다 |
| `GET /config/weights` | **(후속 변경으로 대체됨: 아래 "후속 변경" 절 참고. 지금은 곱·가중치 없음)** 첫 구현: 위험점수 가중치. 설정(`Settings.risk_weights`)에 값이 있으면 `source="config"`, `label="설정값"`. 없거나 형식이 틀리면 기본값 0.30/0.30/0.30/0.10, `source="default"`, `label="기본값"`, `reason`(형식 오류면 `config_error`도). 순서·한국어 라벨·표시 문자열(`display`)·공식. 파이프라인 점수 모듈(`neumann.analyze.cards`)이 있으면 그 모듈의 `SCORE_FORMULA`·`SCORE_WEIGHTS`를 `pipeline`에 보여주고 일치 여부(`matches`)를 적는다 | 현재 config.py에 키가 없어 **기본값** 표시 |

정직성
- 숫자는 매니페스트 값만 쓴다. 없는 값을 다른 값으로 계산해 채우지 않는다(예: `reject_ratio`가 없으면 accept·reject가 있어도 `null`, 테스트로 고정).
- 형식이 틀린 필드(숫자 자리에 문자열 등)도 `null`과 "형식 오류" 사유로 돌린다.
- 로컬 절대 경로(색인 `input.dir`), GPU 이름 같은 환경 정보는 응답에 넣지 않는다(화이트리스트로만 꺼냄, 테스트로 고정). 매니페스트 경로는 상대 경로로만 적는다.
- 매니페스트가 깨져도 예외를 올리지 않고 사유(예외 종류만)를 돌려준다.

## 완료 기준별 측정

### 1. 테스트(매니페스트 있음·없음) — 통과

```
$ export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 NEUMANN_DATA_DIR="C:/Users/User/Desktop/project_neumann/data"
$ python -m pytest tests/e4/test_meta.py -v
tests/e4/test_meta.py::test_api_with_manifests_passes_values_through PASSED
tests/e4/test_meta.py::test_api_does_not_leak_local_environment PASSED
tests/e4/test_meta.py::test_api_without_manifests_returns_empty_values_and_reasons PASSED
tests/e4/test_meta.py::test_api_partial_when_index_missing PASSED
tests/e4/test_meta.py::test_api_broken_manifest_is_reported_not_raised PASSED
tests/e4/test_meta.py::test_api_missing_or_mistyped_field_is_null_with_reason PASSED
tests/e4/test_meta.py::test_api_flags_index_built_from_other_corpus PASSED
tests/e4/test_meta.py::test_api_real_manifests_match_raw_values PASSED
tests/e4/test_meta.py::test_taxonomy_r0_to_r9 PASSED
tests/e4/test_meta.py::test_weights_default_when_not_configured PASSED
tests/e4/test_meta.py::test_weights_real_settings_dependency_defaults PASSED
tests/e4/test_meta.py::test_weights_from_config[raw0] PASSED
tests/e4/test_meta.py::test_weights_from_config[0.4/0.2/0.3/0.1] PASSED
tests/e4/test_meta.py::test_weights_from_config[similarity=0.4, frequency=0.2, severity=0.3, confidence=0.1] PASSED
tests/e4/test_meta.py::test_weights_invalid_config_falls_back_with_reason[0.3/0.3/0.3-4개] PASSED
tests/e4/test_meta.py::test_weights_invalid_config_falls_back_with_reason[0.3/0.3/0.3/1.5-0~1] PASSED
tests/e4/test_meta.py::test_weights_invalid_config_falls_back_with_reason[raw2-키 불일치] PASSED
tests/e4/test_meta.py::test_weights_invalid_config_falls_back_with_reason[similarity=abc,...-숫자] PASSED
tests/e4/test_meta.py::test_weights_invalid_config_falls_back_with_reason[42-지원하지 않는 형식] PASSED
tests/e4/test_meta.py::test_pipeline_scoring_reports_module_weights PASSED
tests/e4/test_meta.py::test_pipeline_scoring_import_error_is_state PASSED
tests/e4/test_meta.py::test_router_routes_and_openapi PASSED
============================= 22 passed in 0.95s ==============================
```

- 테스트는 router를 임시 `FastAPI()` 앱에 붙이고 `dependency_overrides`로 데이터 폴더(tmp_path)·가중치 설정·파이프라인 모듈 상태를 바꾼다.
- 합성 매니페스트 숫자는 테스트 전용 값이다(실제 코퍼스 값 아님). 실제 값 대조는 `test_api_real_manifests_match_raw_values`가 한다: 공유 데이터 폴더의 매니페스트를 직접 읽어 응답과 같은지 비교한다. `NEUMANN_DATA_DIR`이 없고 설정 기본 경로에도 매니페스트가 없으면 skip(`NEUMANN_DATA_DIR` 없이 돌리면 `21 passed, 1 skipped`).

실데이터·빈 폴더 응답(서버 없이 TestClient, router만 붙인 앱):

```
[실데이터] GET /api ok []
 summary_ko: ICLR 2024 · ICLR 2025 · 논문 1,128편 · 심사평 5,366건 · 거절 60.3% · 색인 문장 133,769개
 corpus works 1128 by_field {'materials_chemistry_molecules': 439, 'protein_biology_drug': 550, 'physics_pde_climate': 387} reviews 5366 (official 4298 + meta 1068) reject_ratio 0.6028 generated_at 2026-09-30T09:40:55Z
 index excerpts 133769 built_at 2026-09-30T09:47:25+00:00 matches_corpus True
[빈 폴더] GET /api 200 unavailable ['매니페스트 없음: processed/corpus_manifest.json', '매니페스트 없음: index/manifest.json'] works None excerpts None
GET /config/weights {'similarity': 0.3, 'frequency': 0.3, 'severity': 0.3, 'confidence': 0.1} default 기본값 | 설정에 위험점수 가중치(risk_weights)가 없다 → 기본값 사용 | pipeline missing
GET /taxonomy v1.0 10 59 R0:서술·표현:S1 R1:주장-증거 정합성:S4 R2:실험 설계·평가 프로토콜:S4 R3:데이터 누출·분할 오염:S5 R4:데이터 품질·대표성:S3 R5:재현성·연구산출물:S3 R6:신규성·선행연구 위치:S4 R7:일반화·적용범위:S4 R8:도메인 실증·물리적 타당성:S4 R9:연구윤리·사후 위험:S5
```

(분야별 수의 합 1,376 > 편수 1,128인 것은 한 논문이 여러 분야에 걸리기 때문이다. 매니페스트 `selection.multi_field_works`=241을 같이 돌려준다.)

### 2. `python scripts/verify.py` — 통과

```
$ python scripts/verify.py        (위와 같은 환경변수, 작업 폴더에서)
...
207 passed in 4.21s
보안: 파일 124개
계약: 2개
테스트: 통과
verify 통과
```

## 바꾼 파일

- `src/neumann/api/meta.py` (새 파일): router, `build_api_meta`, `build_taxonomy`, `build_weights`, `parse_weights`, `pipeline_scoring`, 의존성 `get_data_dir`·`get_weights_setting`·`get_pipeline_scoring`
- `tests/e4/test_meta.py` (새 파일): 22개
- `docs/reports/E4-L1d.md` (이 보고서)

## PM이 main.py에 붙일 줄

main(6067212)의 `OPTIONAL_ROUTERS`에 이미 `"neumann.api.meta"`가 들어 있어서, 이 브랜치를 병합하면 따로 할 일 없이 연결된다. 확인도 했다. main의 `main.py` 소스(`git show main:src/neumann/api/main.py`, 읽기만 함)를 이 브랜치 패키지로 실행하니 다음과 같았다.

```
routers: {'neumann.api.export': 'ok', 'neumann.api.upload': 'missing', 'neumann.api.precomputed': 'missing', 'neumann.api.templates': 'missing', 'neumann.api.meta': 'ok'}
/api 200 /taxonomy 200 /config/weights 200
```

직접 붙인다면:

```python
from neumann.api.meta import router as meta_router
app.include_router(meta_router)   # GET /api · GET /taxonomy · GET /config/weights
```

기존 라우트(`/`, `/health`, `/premortem`, `/premortem/view`, `/premortem/package`)와 경로가 겹치지 않는다. 다른 E4·E6 브랜치(`E4-L1a/b`, `E4-L2b/c`, `E6-L2a`)의 `src`에도 `/api`·`/taxonomy`·`/config/weights`는 없다(`git grep`으로 확인).

## 결정(스펙이 모호해서 고른 것)

1. **심사평 수**는 코퍼스 `outputs["reviews.jsonl"].records`(5,366 = 공식 심사평 4,298 + 메타리뷰 1,068)를 쓰고, 내역(`official_reviews`, `meta_reviews`)을 함께 준다. 색인 쪽 `counts.reviews`도 `index.reviews`로 따로 준다.
2. **거절 비율**은 `decisions.reject_ratio`(전체 1,128편 기준 0.6028)를 쓴다. 심사평이 있는 논문 기준 값(`reject_ratio_among_reviewed_works` 0.6011)은 넣지 않았다.
3. **색인 문장 수** 키 이름은 매니페스트·모델과 같게 `index.excerpts`로 했다(화면 요약 문구는 "색인 문장").
4. **빌드 시각**은 색인 `built_at`과 코퍼스 `generated_at`을 둘 다 준다.
5. 매니페스트가 없어도 **200**을 돌려준다(메타 정보라 화면이 깨지지 않게). 상태는 `status`·`reasons`로 드러낸다.
6. **(후속 변경으로 폐기)** **가중치 기본값** 0.30/0.30/0.30/0.10은 기획서 `04_architecture.md` §3.8 `aggregate_risk` 입력 예시와 목업 가중치 모달의 값이다. config.py에는 가중치 키가 없어서 `getattr(get_settings(), "risk_weights", None)`로 읽는다. 지금은 항상 `None` → 기본값.
7. **(후속 변경으로 판정 기준이 바뀜: 곱·가중치 1.0이면 일치)** **파이프라인 대조**: 표시용 가중치와 실제 카드 점수 계산이 다를 수 있어서, 점수 모듈이 있으면 그 모듈의 공식·가중치를 같이 보여준다. `task/E3-L0` 브랜치의 `neumann/analyze/cards.py`는 `SCORE_FORMULA="product_v1: similarity * frequency * severity * confidence"`, `SCORE_WEIGHTS` 전부 1.0이다. 이 브랜치가 병합되면 `/config/weights`의 `pipeline.matches=false`와 "카드 점수는 모듈 값으로 계산된다"는 안내가 뜬다. 숨기지 않으려고 이렇게 했다.
8. **택소노미 설명**은 03_risk_taxonomy §3 각 카드의 "정의"를 옮겼다. R1·R2·R4·R5·R6은 원문 그대로다. 나머지는 화면용으로 줄였다. R0은 첫 두 문장만 남겼다. R3에서는 "Kapoor & Narayanan 8유형 채택" 문장과 "R2와의 차이:" 머리를 뺐고, R7에서는 "R1과의 경계:" 머리를, R8에서는 "Neumann의 고유 축" 구절을, R9에서는 "브리프 9절 가드레일에 따라"를 뺐다. 심각도·탐지 경로·카드 생성 여부·Macro-F1 여부·소분류 수는 문서 값 그대로다. R9의 "위험카드 생성"은 문서 값("예")을 따랐다. E3-L0 카드 조립은 R9를 카드로 만들지 않는다. 둘이 다르다는 것을 적어 둔다.

## 제안(PM 승인 필요, 이 과제에서는 고치지 않음)

- **(후속 변경으로 철회: 제품은 가중치를 쓰지 않는다)** `src/neumann/config.py`에 `risk_weights: str | None = Field(default=None, validation_alias="NEUMANN_RISK_WEIGHTS")`, `.env.example`에 `NEUMANN_RISK_WEIGHTS=` 추가. 형식은 `0.3/0.3/0.3/0.1` 또는 `similarity=0.3,frequency=0.3,severity=0.3,confidence=0.1`이다(`parse_weights`가 둘 다 받고, 틀리면 기본값과 사유를 돌려준다). 추가하면 meta.py를 고치지 않아도 `source="config"`가 된다.
- 가중치 합성 공식을 E3와 맞춰야 한다. 목업·04_architecture는 가중치 0.3/0.3/0.3/0.1을 보여주고, E3-L0은 가중치 없는 곱이다. 어느 쪽이 제품 공식인지 PM이 정해 `docs/decisions.md`에 남기는 것이 좋다.

## 못 한 것

- 가중치 **변경** API(POST)는 만들지 않았다(스펙은 GET만). 목업 모달의 "적용"은 아직 점수를 다시 계산하지 않는다.
- 화면(webui) 연결은 이 과제 범위 밖이다(소유 경로 아님). 추적 섹션의 "ICLR 2025 공식 심사평 25,170건 · 6,209편"은 목업 예시 값이다. `/api`의 `summary_ko`나 `corpus`·`index` 값으로 바꾸면 된다.
- Retraction Watch 매니페스트(`processed/retraction_manifest.json`)는 스펙 항목이 아니어서 `/api`에 넣지 않았다.
- 서버는 띄우지 않았다(TestClient로 충분했다. 8124·8010 모두 쓰지 않음).

## 다음 과제에 넘길 것

- E4 화면: 상단 가중치 pill 텍스트는 `/config/weights`의 `display`("곱 · 가중치 없음")로 바꾸고, 가중치 슬라이더 모달은 없애거나 공식 안내(`formula_ko`, `decision.source`)로 바꾼다. 코퍼스 문구는 `/api`의 `summary_ko`, 위험 이름·심각도는 `/taxonomy`로 바꾼다.
- E3 병합 뒤 `/config/weights`의 `pipeline.state`가 `ok`인지(import 오류면 `error: …`) 확인한다.

## 후속 변경 (PM 결정 반영: 위험점수 = 곱, 가중치 없음)

PM 결정 `docs/decisions.md` 2026-09-30 19:15(main)에 따라 `/config/weights`를 고쳤다. 먼저 `git merge main`으로 main을 받았다(충돌 없음, 병합 커밋 `4a010a1`).

바뀐 것
- 응답 본문은 결정 그대로다. `formula="product"`, `formula_expr="similarity * frequency * severity * confidence"`, `formula_ko="위험점수 = 유사도 × 빈도 × 심각도 × 신뢰도 (곱, 가중치 없음)"`, `weighted=false`, `weights=null`, `display="곱 · 가중치 없음"`이다. `decision.source="docs/decisions.md 2026-09-30 19:15 (PM)"`와 결정 요약도 함께 준다.
- 0.3/0.3/0.3/0.1은 `legacy_design_weights`에만 남겼다. `status="제품에서 쓰지 않는 옛 설계값"`, `used_in_product=false`로 표시한다. 현재 값 자리(`weights`·`display`·`formula*`)에는 0.3도 "기본값"도 나오지 않는다(테스트로 고정).
- 설정 가중치 경로를 없앴다. `get_weights_setting`, `parse_weights`, `source`·`is_default`·`label`·`config_error`가 빠졌다. 제품이 가중치를 쓰지 않으니 설정으로 바꿀 값이 없다. 앞의 `risk_weights` 설정 키 제안도 철회한다.
- E3 점수 모듈 대조는 유지했다(`pipeline_matches`). 모듈이 있고 `SCORE_FORMULA`에 "product"가 들어 있으며, `SCORE_WEIGHTS`가 없거나 네 요소 모두 1.0이면 `matches=true`다. 공식이 곱이 아니거나, 1.0이 아닌 가중치가 있거나, 항목이 다르면 `matches=false`와 사유를 준다. 모듈이 없거나 import에 실패하면 `null`이다. `task/E3-L0`의 `cards.py`(`product_v1: …`, 가중치 전부 1.0)와 같은 모양의 가짜 모듈로 `matches=true`를 확인했다. 실제 `neumann.analyze.cards`는 아직 main에 없어서 `test_real_pipeline_module_if_present`는 skip이다. 병합되면 자동으로 일치를 잰다.

바뀐 응답(서버 없이 router만 붙인 앱)

```
{"formula": "product", "formula_expr": "similarity * frequency * severity * confidence", "formula_ko": "위험점수 = 유사도 × 빈도 × 심각도 × 신뢰도 (곱, 가중치 없음)", "weighted": false, "weights": null, "display": "곱 · 가중치 없음", "components": ["similarity", "frequency", "severity", "confidence"], "labels_ko": {"similarity": "유사도", "frequency": "빈도", "severity": "심각도", "confidence": "신뢰도"}, "decision": {"source": "docs/decisions.md 2026-09-30 19:15 (PM)", "summary": "위험점수는 계획서 §2 정의대로 유사도 × 빈도 × 심각도 × 신뢰도의 곱(가중치 없음). 설계·목업의 가중합(0.3/0.3/0.3/0.1)은 쓰지 않는다."}, "legacy_design_weights": {"status": "제품에서 쓰지 않는 옛 설계값", "used_in_product": false, "values": {"similarity": 0.3, "frequency": 0.3, "severity": 0.3, "confidence": 0.1}, "source": "기획서 부록/설계/04_architecture.md §3.8 aggregate_risk 입력 예시 · 목업 가중치 모달"}, "pipeline": {"module": "neumann.analyze.cards", "state": "missing", "formula": null, "weights": null, "matches": null, "note": "파이프라인 점수 모듈이 없거나 불러오지 못해 대조하지 못함."}}
```

테스트(가중치 부분을 새로 썼다. /api·/taxonomy 테스트는 그대로다)

```
$ python -m pytest tests/e4/test_meta.py -v      (NEUMANN_DATA_DIR=공유 데이터 폴더)
tests/e4/test_meta.py::test_api_with_manifests_passes_values_through PASSED
tests/e4/test_meta.py::test_api_does_not_leak_local_environment PASSED
tests/e4/test_meta.py::test_api_without_manifests_returns_empty_values_and_reasons PASSED
tests/e4/test_meta.py::test_api_partial_when_index_missing PASSED
tests/e4/test_meta.py::test_api_broken_manifest_is_reported_not_raised PASSED
tests/e4/test_meta.py::test_api_missing_or_mistyped_field_is_null_with_reason PASSED
tests/e4/test_meta.py::test_api_flags_index_built_from_other_corpus PASSED
tests/e4/test_meta.py::test_api_real_manifests_match_raw_values PASSED
tests/e4/test_meta.py::test_taxonomy_r0_to_r9 PASSED
tests/e4/test_meta.py::test_weights_shows_product_without_weights PASSED
tests/e4/test_meta.py::test_weights_response_is_not_mutated_between_calls PASSED
tests/e4/test_meta.py::test_pipeline_e3_product_module_matches PASSED
tests/e4/test_meta.py::test_pipeline_mismatch_is_reported[가중치 0.3… → "1.0이 아닌"] PASSED
tests/e4/test_meta.py::test_pipeline_mismatch_is_reported[weighted_sum_v1 → "곱(product)이 아니다"] PASSED
tests/e4/test_meta.py::test_pipeline_mismatch_is_reported[항목 2개 → "항목"] PASSED
tests/e4/test_meta.py::test_pipeline_without_formula_or_weights_is_unknown PASSED
tests/e4/test_meta.py::test_pipeline_scoring_import_error_is_state PASSED
tests/e4/test_meta.py::test_real_pipeline_module_if_present SKIPPED   (neumann.analyze.cards 미병합)
tests/e4/test_meta.py::test_router_routes_and_openapi PASSED
======================== 18 passed, 1 skipped in 1.02s ========================
```

verify(main 병합 뒤, 작업 폴더):

```
$ python scripts/verify.py
...
396 passed, 5 skipped in 18.92s
보안: 파일 183개
계약: 2개
테스트: 통과
verify 통과
```
