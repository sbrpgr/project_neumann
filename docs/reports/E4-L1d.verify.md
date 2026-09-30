# E4-L1d 검증 보고서 — 메타 API(/api · /taxonomy · /config/weights)

- 검증자: Claude Sonnet 5.5 (빌더 claude-opus-5.5와 다른 모델) · 대상: `task/E4-L1d` @ `381330d` (worktree `.claude/worktrees/s2-E4-L1d`)
- 코드·git 쓰기·`.env` 열기·서버 기동·OpenAI 호출 모두 하지 않았다(TestClient만 사용, 8010·8127 미사용).

## 최종 판정: **PASS**

병합 전에 고칠 것은 없다. 완료 기준(테스트 있음·없음, verify)이 직접 실행으로 통과했고, 실데이터 숫자가 매니페스트 원값과 전부 같으며, 택소노미 구조 필드가 기획 문서와 일치하고, 소유 경로 밖 변경·비밀값·로컬 경로 노출이 없다. 아래 "병합 후 권고"는 품질 개선이며 병합을 막지 않는다.

## 1. 완료 기준 직접 실행

| # | 항목 | 실행한 명령(환경변수는 `_COMMON.md`) | 실제 출력 | 결과 |
|---|---|---|---|---|
| 1-1 | 테스트, 매니페스트 있음 | `pytest tests/e4 -q -k meta` (`NEUMANN_DATA_DIR`=공유 데이터 폴더) | `22 passed, 57 deselected` | 통과 |
| 1-2 | 테스트, 매니페스트 없음 | 같은 명령, `NEUMANN_DATA_DIR`=빈 임시 폴더 | `21 passed, 1 skipped`(skip은 실데이터 대조 1건, 의도된 동작) | 통과 |
| 1-3 | verify | `python scripts/verify.py` (worktree) | `207 passed` · `보안: 파일 125개` · `계약: 2개` · `테스트: 통과` · `verify 통과` | 통과 |
| 1-4 | 병합 모의(main a6eab0c + 이 브랜치 3파일, 스크래치 복사본) | 전체 `pytest` | `323 passed, 2 skipped`. 브랜치 기반은 481e11c인데 main은 a6eab0c까지 나아갔다. main에 `meta.py`·`test_meta*`·`E4-L1d.md`가 없어 충돌 없음 | 통과 |
| 1-5 | main.py 연결 | 위 복사본에서 `neumann.api.main:app`을 TestClient로 | `/health.routers['neumann.api.meta']='ok'`, `/api`·`/taxonomy`·`/config/weights` 모두 200 `application/json`. POST·PUT·DELETE·HEAD는 405. `/api?data_dir=C:/Windows` 쿼리는 무시(works 1128 그대로). 기존 5개 라우트와 경로 충돌 없음 | 통과 |

## 2. 조작 입력에 테스트가 실패하는가(변이 검사)

스크래치 복사본의 `meta.py`를 한 곳씩 망가뜨리고 `tests/e4/test_meta.py`를 다시 돌렸다(워크트리는 건드리지 않음).

| 변이 | 결과 |
|---|---|
| 편수를 실제값 1128로 고정 / 합성값 11로 고정 | 둘 다 실패(합성 테스트 / 매니페스트 없음 테스트가 잡음) |
| `reject_ratio`·`excerpts`·`built_at`을 가짜 값으로 | 실패 |
| 심사평 수를 공식 심사평 수(4,298)로 바꿈 | 실패 |
| `by_field`를 `by_venue`로 바꿈 | 실패 |
| 색인 `input.dir`·`gpu_name` 누출 | 실패(누출 테스트) |
| 매니페스트가 없을 때 0으로 채움 / 상태를 항상 `ok`로 | 실패 |
| 색인·코퍼스 해시 불일치를 못 잡게 함 | 실패 |
| 깨진 JSON에서 예외가 올라가게 함 | 실패 |
| 기본값을 "설정값"으로 표시 / 기본 가중치 값 변경 / 설정값 무시 | 실패 |
| R3 심각도 S5→S3, R9 Macro-F1 플래그 반전 | 실패 |
| 파이프라인 `matches`를 항상 True로 / 요약의 거절 % 자릿수 변경 / 필드 누락 사유 제거 | 실패 |
| **생존 3건**: 파이프라인 모듈 `error:` 상태 두 분기를 `ok`로 바꿈, R3 설명문을 "WRONG TEXT"로 교체 | 테스트가 못 잡음(아래 권고 1·2) |

24개 변이 중 21개를 테스트가 잡았다. 항상 통과하는 핵심 테스트는 없다.

## 3. 실데이터 대조(공유 데이터 폴더, TestClient)

원본은 `data/processed/corpus_manifest.json`·`data/index/manifest.json`을 직접 읽었다. 응답은 `/api`.

| 항목 | 매니페스트 원값 | `/api` 응답 | 일치 |
|---|---|---|---|
| 논문 편수 | `selection.works` 1128 | `corpus.works` 1128 | O |
| 분야별 수 | 439 / 550 / 387 | 같은 dict(`by_field`·`by_field_ko` 모두) | O |
| 학회별 수 | ICLR 2024 410 · ICLR 2025 718 | 같음 | O |
| 심사평 수 | `outputs.reviews.jsonl.records` 5366 (= 공식 4298 + 메타 1068) | 5366 / 4298 / 1068 | O |
| 거절 비율 | `decisions.reject_ratio` 0.6028 (680/1128) | 0.6028, 요약 문구 "거절 60.3%" | O |
| 결정 수 | accept 448 · reject 680 | 같음 | O |
| 코퍼스 생성 시각 | `2026-09-30T09:40:55Z` | 같음 | O |
| 색인 문장 수 | `counts.excerpts` 133769 | `index.excerpts` 133769 | O |
| 색인 작품·심사평·태그 | 1128 / 5366 / 10928 | 같음(`tag_counts`도 같음) | O |
| 색인 빌드 시각 | `2026-09-30T09:47:25+00:00` | 같음 | O |
| 오프셋 검사 | checked 133769 · passed 133769 · failed 0 · rate 1.0 | 같음 | O |
| 색인↔코퍼스 해시 | works·reviews sha256 앞 12자 `317e966f3840`·`b0ba375f72b2` 양쪽 동일 | `matches_corpus: true` | O |

- 17개 필드 전부 일치(`ALL EQUAL: True`), `status: ok`, `reasons: []`. 지어낸 숫자 없음.
- 매니페스트가 없으면 값 `null`+사유, 필드 누락·형식 오류·깨진 JSON도 사유와 함께 200으로 돌려준다(테스트와 변이 검사로 확인). 분야별 합 1,376 > 편수 1,128은 `multi_field_works` 241과 함께 노출된다(원값 241 확인).

## 4. 택소노미·가중치 정직성

| 항목 | 방법 | 결과 |
|---|---|---|
| R0~R9 이름·slug | `03_risk_taxonomy.md` 카드 헤더 10개를 파싱해 응답과 비교 | 전부 일치(R0 영문명 불일치로 보인 것은 내 파서가 중첩 괄호를 못 읽은 탓이며, 문서 헤더와 `models.RISK_NAMES` 값은 같음) |
| 심각도 기본값 | 문서 "심각도 기본값" 행 | R0 S1 · R1 S4 · R2 S4 · R3 S5 · R4 S3 · R5 S3 · R6 S4 · R7 S4 · R8 S4 · R9 S5 전부 일치, 등급 이름(치명적·중대·상당·경미)도 일치 |
| 탐지 경로·위험카드 생성·Macro-F1 측정·소분류 | 같은 방식 | 10개 모두 일치(R0 카드 생성 아니오, R9 Macro-F1 아니오). 소분류 5+7+8+7+5+5+6+7+9=59, Tier-1 10 |
| 설명문 | 문서 "정의"와 문장 단위 비교 | R1·R2·R3~R7·R9·R0는 문서 문장 그대로(R3·R7은 "R2와의 차이:" 같은 머리말만 뺌), R8은 마지막 구절("Neumann의 고유 축")만 뺌. 보고서 결정 8번의 설명과 같음. 의미 왜곡 없음 |
| 가중치 기본값 | `04_architecture.md` §3.8 `aggregate_risk` 입력 예시 | 0.30/0.30/0.30/0.10, 공식 "유사도×빈도×심각도×신뢰도"가 문서와 같음 |
| 기본값 표시 | `/config/weights` 실응답 | `source:"default"`, `is_default:true`, `label:"기본값"`, `reason:"설정에 위험점수 가중치(risk_weights)가 없다 → 기본값 사용"`. config.py에 키가 없어 설정값으로 위장하지 않음. 형식이 틀린 설정도 기본값+`config_error`로 표시 |
| 파이프라인 대조 | 응답 `pipeline` | main에는 `neumann.analyze.cards`가 없어 `state:"missing"`, `matches:null`. `task/E3-L0`의 `cards.py`는 `SCORE_FORMULA="product_v1…"`, `SCORE_WEIGHTS` 전부 1.0임을 직접 확인(빌더 보고서 결정 7과 같음) |

## 5. 계약·범위·노출

| 항목 | 확인 | 결과 |
|---|---|---|
| `git diff main...task/E4-L1d --stat` | 3파일 추가(+998): `docs/reports/E4-L1d.md`, `src/neumann/api/meta.py`, `tests/e4/test_meta.py`. 전부 소유 경로 | 범위 준수 |
| `main.py`·`contracts/`·`models.py`·`config.py`·`.env.example` 변경 | 해당 경로 diff 0바이트 | 없음 |
| 데이터·비밀값 파일 | 브랜치 트리에 `.env`·`data/`·parquet·npy 없음. diff에서 키 패턴(`sk-…`, `api_key=`, Bearer)·비밀번호 없음 | 없음 |
| 응답 내 로컬 경로·내부 정보 | 실응답 전문에서 `C:\`·`Users`·`Desktop`·`노이만`·`project_neumann`·`.venvs`·`gpu`·`cuda`·`OPENAI`·`sk-` 검색. 유일한 `X:/` 꼴 일치는 `https://openreview.net`(attribution 문구). 색인 `input.dir`·GPU 이름·VRAM·device는 화이트리스트로 걸러져 나오지 않음. 매니페스트 경로·사유는 상대 경로와 예외 종류만 | 노출 없음 |
| 다른 브랜치와의 경로 충돌 | `task/*` 25개 브랜치 `src`에서 `"/api"`·`"/taxonomy"`·`/config/weights` 검색 | 겹치는 곳 없음 |
| 워크트리 정리 | `verify.py`가 만든 `.pytest_cache/`(gitignore 대상) 삭제, 추적 파일 변경 없음 | 정리함 |

## 병합 후 권고(병합을 막지 않음)

1. 테스트 공백: `pipeline_scoring`의 `error: …` 두 분기(의존 모듈 없음·기타 import 예외)는 테스트가 없다. `test_pipeline_scoring_import_error_is_state`는 이름과 달리 `missing`만 확인한다(변이 생존).
2. 택소노미 설명문은 "비어 있지 않음"만 검사한다. R3 설명을 통째로 바꿔도 통과한다(변이 생존). 심각도·경로·소분류는 문서 값으로 고정돼 있어 이 공백은 설명문에만 해당한다. 수동 대조 결과는 위 4번 표.
3. 색인이 `degraded=true`여도 `status`는 `ok`로 남고(`index.degraded`·`degraded_reason` 필드로만 드러난다), 색인 매니페스트의 `input.fallback`(jsonl 직접 읽기 대체 사실)은 응답에 나오지 않는다. 현재 실데이터는 `degraded:false`라 문제 없다. 화면이 `/api`를 쓸 때 `degraded`를 표시하면 된다.
4. E3-L0 병합 뒤 `/config/weights`는 최상위 `weights`(0.3/0.3/0.3/0.1, "기본값")와 `pipeline.matches=false`를 함께 준다. 화면은 `pipeline.note`를 반드시 보여야 하고, 가중합/곱 중 어느 쪽이 제품 공식인지 PM이 `docs/decisions.md`에 정해야 한다(빌더 보고서 "제안"과 같은 사항).
