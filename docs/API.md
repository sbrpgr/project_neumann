# API

- 기준: 이 문서를 병합하기 직전의 `main`(작성 때 확인한 커밋 `47e45e5`).
- 아래 응답 예시는 `304e91e`의 서버를 `NEUMANN_LLM_PROVIDER=mock`, 임베딩 모델 없이(어휘 검색만) 포트 8125에서 띄워 실제로 요청해 받은 값을 줄인 것이다. **mock 응답이라 카드 내용은 분석 결과가 아니다.** 실제 서비스(provider를 `openai`로 켠 경우)에서는 `generator`가 `astra`이고 검색 강등이 없다(임베딩 모델이 있을 때). 예시 수치(근거 22건·카드 5장·점수)는 검색 보정(E2-L1, main `9a2471e`) 이전 값이라 지금 main에서는 조금 다르다.
- **있음** = main의 서버에 라우트가 있다. **예정** = main에 없다(지금 요청하면 404).
- 서버 실행은 [RUNNING.md §5](RUNNING.md#5-분석-실행). 기본 주소 `http://127.0.0.1:8000`.
- 전체 스키마: `GET /openapi.json`. `GET /docs`도 FastAPI 기본값으로 열리지만 Swagger UI 파일을 외부 CDN(jsdelivr)에서 받는다. 오프라인 확인에는 `/openapi.json`을 쓴다.

> **provider와 비용:** 기본 provider는 `mock`이다(비용 없음, 결과에 mock 표시). `NEUMANN_LLM_PROVIDER=openai`로 켜면 `POST /premortem`, `POST /premortem/view`, 그리고 `plan_text`만 보낸 `POST /premortem/package`가 요청마다 OpenAI API를 부르고 비용이 든다.

## 목록

| 메서드·경로 | 하는 일 | 상태 |
|---|---|---|
| `GET /` | 화면(`webui/index.html`) | 있음 |
| `GET /fonts/{경로}` | 로컬 폰트 파일 | 있음 |
| `GET /health` | 서버 상태, 파이프라인 연결, 단계별 모듈 import 가능 여부, 선택 라우터 상태 | 있음 |
| `POST /premortem` | 계획서 텍스트 → 분석 결과 JSON(`PremortemResult`) | 있음 |
| `POST /premortem/view` | 같은 입력 → 화면 데이터 JSON(`ui_view` 계약) + `_status` | 있음 |
| `POST /premortem/package` | 분석 결과(또는 계획서) → ZIP 9파일 | 있음 |
| `GET /premortem/precomputed`, `GET /premortem/precomputed/{plan_id}` | 데모 사전 계산본 목록·단건(오프라인 폴백, 변조 시 404) | 있음 |
| `GET /templates`, `GET /templates/{item_id}` | AI for Science 계획서 템플릿 목록·골격 | 있음 |
| `GET /api`, `GET /taxonomy`, `GET /config/weights` | 코퍼스·색인 실측 메타, 위험 유형 R0~R9, 위험점수 공식 | 있음 |
| MCP 서버(stdio) `python -m neumann.api.mcp_server` | 읽기 전용 도구 3종 | 있음 |
| `POST /upload/plan` | 계획서 파일(txt·md·pdf·docx, 10MB) → 텍스트. HWP 거부, 디스크에 저장하지 않음 | 있음 |

선택 라우터(`export`·`upload`·`precomputed`·`templates`·`meta`)는 `api/main.py`가 모듈이 있으면 붙인다. 붙었는지는 `/health`의 `routers`에서 확인한다(지금 main은 모두 `ok`).

## GET /health

```bash
curl http://127.0.0.1:8000/health
```

실측(줄임):

```json
{
  "status": "ok",
  "version": "0.0.1",
  "pipeline": {"state": "connected", "reason": "", "mode": "pipeline", "label": ""},
  "stages": {
    "pipeline": {"available": true, "modules": {"neumann.pipeline": "ok"}},
    "INPUT":    {"available": true, "modules": {"neumann.analyze.queries": "ok"}},
    "EVIDENCE": {"available": true, "modules": {"neumann.index.search": "ok", "neumann.index.store": "ok", "neumann.analyze.extract": "ok"}},
    "RISK":     {"available": true, "modules": {"neumann.analyze.cards": "ok"}},
    "REVIEW":   {"available": true, "modules": {"neumann.analyze.review": "ok", "neumann.analyze.gate": "ok"}},
    "ACTION":   {"available": true, "modules": {"neumann.analyze.checklist": "ok", "neumann.analyze.validate": "ok"}},
    "TRACE":    {"available": true, "modules": {"neumann.api.export": "ok"}},
    "llm":      {"available": true, "modules": {"neumann.llm": "ok"}},
    "models":   {"available": true, "modules": {"neumann.models": "ok"}},
    "config":   {"available": true, "modules": {"neumann.config": "ok"}}
  },
  "routers": {"neumann.api.export": "ok", "neumann.api.upload": "ok", "neumann.api.precomputed": "ok",
              "neumann.api.templates": "ok", "neumann.api.meta": "ok"}
}
```

- `pipeline.state`: `connected`(파이프라인 있음) · `unavailable`(모듈 없음 → 샘플) · `error`(import 실패)
- `stages`는 모듈을 import할 수 있는지만 본다. `REVIEW`·`ACTION`의 모듈은 있지만 파이프라인이 아직 부르지 않는다([ARCHITECTURE.md §1](ARCHITECTURE.md#1-지금-상태-한눈에)).

## POST /premortem

요청 본문(JSON):

| 키 | 타입 | 제약 |
|---|---|---|
| `plan_text` | 문자열 | 필수, 1~200,000자, 공백만이면 422 |
| `filename` | 문자열 | 선택, 255자 이하 |

```bash
curl -X POST http://127.0.0.1:8000/premortem \
  -H "Content-Type: application/json" --data-binary @req.json
# req.json: {"plan_text": "<tests/fixtures/plans/plan.md 내용>", "filename": "plan.md"}
```

Windows Git Bash에서는 한글을 `-d '…'`로 직접 넘기면 인코딩이 깨져 400이 날 수 있다. UTF-8 파일을 `--data-binary @파일`로 보낸다.

실측 응답(mock provider, 임베딩 없음, 200, 1.8초, 줄임):

```json
{
  "status": "degraded",
  "pipeline_version": "neumann-e3-l0",
  "plan_id": "3d35460def76efc4a786dce769e614f0d54d110ee2837da6b8fc1dbcf88ef33c",
  "stages": [
    {"name": "plan_normalize",   "phase": "INPUT",    "status": "ok",       "impl": "neumann.models:PlanDocument.from_text"},
    {"name": "query_axes",       "phase": "INPUT",    "status": "ok",       "impl": "mock:mock-deterministic-v1"},
    {"name": "search",           "phase": "EVIDENCE", "status": "degraded", "impl": "neumann.index.search:search",
     "reason": "상위 점수 0.245; 검색 강등(백엔드 lexical_only, 임베딩 없이 어휘 검색)"},
    {"name": "extract_issues",   "phase": "EVIDENCE", "status": "ok",       "impl": "mock:mock-deterministic-v1", "reason": "폐기율 0.0%"},
    {"name": "synthesize_cards", "phase": "RISK",     "status": "ok",       "impl": "mock:mock-deterministic-v1"},
    {"name": "verify_evidence",  "phase": "REVIEW",   "status": "ok",       "impl": "neumann.models:Excerpt.verify_against",
     "reason": "근거 22/22 원문 일치"}
  ],
  "notices": ["[search] degraded: 상위 점수 0.245; 검색 강등(백엔드 lexical_only, 임베딩 없이 어휘 검색)",
              "mock provider(테스트용) 결과 — 실제 astra 분석이 아니다"],
  "similar_works": ["… 10편 …"],
  "evidence": [{"excerpt_id": "ex_afb2cbc9e56b30d1", "source_kind": "review", "start": 889, "end": 1236,
                "source_url": "https://openreview.net/forum?id=ZkpDdCQUC4&noteId=PIYoBctiz2", "...": "text, text_sha256 …"},
               "… 모두 22건 …"],
  "risk_cards": [{"card_id": "card_9a76808af95c", "risk_code": "R2", "title": "mock: 실험 설계·평가 프로토콜",
                  "generator": "mock", "model": "mock-deterministic-v1",
                  "evidence": ["ex_afb2cbc9e56b30d1", "..."],
                  "score": {"similarity": 0.2291, "frequency": 1.0, "severity": 0.8, "confidence": 0.52, "total": 0.0953}},
                 "… 모두 5장 …"],
  "manifest": {"pipeline_version": "neumann-e3-l0", "llm_provider": "mock", "llm_model": "mock-deterministic-v1",
               "backend": "neumann.index.search:search",
               "prompt_versions": ["query_axes.v1", "extract_issues.v1", "synthesize_cards.v3"], "total_s": 1.741},
  "...": "plan, expected_review, checklist, risk_synthesis 등 contracts/premortem_response.schema.json의 키"
}
```

- `plan_id`는 계획서 본문의 sha256이다.
- 카드의 `evidence`는 발췌 id 목록이고, 인용문은 `evidence[]`의 `text`(원문 `[start:end]`)다. 모든 근거는 `verify_evidence` 단계에서 원문과 다시 대조된다.
- `score.total` = 유사도 × 빈도 × 심각도 × 신뢰도(곱, 가중치 없음).
- `generator`: `astra`(제품 LLM, OpenAI. 값 이름은 계약이고 실제 모델은 카드 `model`·`manifest.llm_model`, 기본 `gpt-6.1-sol`) · `rule`(비상 규칙) · `mock`(테스트용 가짜).
- 카드가 0장이면 사유가 `risk_synthesis.no_card_reason`과 `notices`에 들어간다. 실측(무관한 글 `tests/fixtures/plans/negative_recipe.md`, mock): 카드 0장, 사유 "입력이 연구계획서가 아니다(mock 판단: …); 유사 연구 검색 상위 점수 0.031".

오류:

| 코드 | 언제 |
|---|---|
| 422 | `plan_text`가 없거나 비었거나 200,000자를 넘는다 |
| 500 | 파이프라인 모듈 import·실행이 예외로 실패했다. 본문 `{"status": "error", "pipeline": …, "reason": "파이프라인 실행 실패: <예외 종류> @ <파일:줄>"}`(예외 메시지는 싣지 않는다). 단계 실패는 500이 아니라 강등(`degraded`)으로 돌아온다 |

파이프라인 모듈이 아예 없을 때만(지금 main에서는 일어나지 않는다) 공용 fixture 샘플을 `sample: true`, "분석 파이프라인 미연결(샘플 데이터)" 표시와 함께 돌려준다.

## POST /premortem/view

본문은 `/premortem`과 같다. 응답은 화면 데이터 계약(`contracts/ui_view.schema.json`)을 따르고, 서버가 응답마다 이 스키마로 검사한다.

최상위 키: `plan`, `pipeline`, `works`, `fams`, `corpus`, `ev`, `cards`, `others`, `review`, `checklist`, `plan_id`, `session_id`, `kpi`, `_status`.

`_status` 실측(mock provider, 임베딩 없음, 줄임):

```json
{"source": "pipeline", "label": "일부 단계 강등", "degraded": true, "generators": {"mock": 5},
 "contract_ok": true, "dropped": {}, "pipeline": "connected", "result_status": "degraded",
 "stages_not_ok": [{"name": "search", "phase": "EVIDENCE", "status": "degraded",
                    "reason": "상위 점수 0.245; 검색 강등(백엔드 lexical_only, 임베딩 없이 어휘 검색)"}]}
```

- `dropped`: 근거가 풀리지 않아 화면에서 뺀 카드·예상 심사평 문장 개수
- `degraded`: 샘플이거나, 결과 status가 degraded·error이거나, 강등 단계가 있거나, 생성 방식이 astra가 아닌 카드가 있으면 `true`
- `empty_reason`: 카드가 0장일 때 사유

## POST /premortem/package

분석 결과를 ZIP 9파일로 묶는다: `README.md`, `manifest.json`, `risk_cards.json`, `evidence_pack.json`, `similar_works.csv`, `plan_annotated.md`, `neumann_report.md`, `ai_context.md`, `decision_log.json`.

요청 본문(JSON, `result`나 `plan_text` 중 하나 이상):

| 키 | 뜻 |
|---|---|
| `result` | 분석 결과 JSON(`/premortem` 응답). `PremortemResult`로 검증한다(모르는 키는 거부) |
| `plan_text` | 계획서 원문(최대 1,000,000자). `result` 없이 오면 서버가 파이프라인을 돌린다(기본 mock, provider를 openai로 켰으면 OpenAI 호출) |
| `decisions` | 결정 로그. 항목 `{"card_id"` 또는 `"item_id", "decision": "adopt"·"hold"·"reject"(채택·보류·기각도 받음), "note"?, "decided_at"?}` |

`result`로 감싸지 않고 결과 JSON을 그대로 보내도 된다(`session_id`·`plan_id`가 있으면 결과로 본다).

```bash
curl -X POST http://127.0.0.1:8000/premortem/package \
  -H "Content-Type: application/json" --data-binary @pkg_req.json -o package.zip
# pkg_req.json: {"result": <POST /premortem 응답>,
#                "decisions": [{"card_id": "<카드 id>", "decision": "채택", "note": "분할을 저자 단위로 바꾼다"}]}
```

실측: `/premortem` 응답(mock)을 그대로 보내면 `200 application/zip`. `plan_text`만 보내면(mock) 파이프라인이 돌아 `200`, ZIP 9파일, `manifest.result.status: degraded`, `cards_by_generator: {"astra": 0, "rule": 0, "mock": 5}`. 응답 헤더 `Content-Disposition: attachment; filename="neumann_package_<plan_id 앞 12자>.zip"`.

ZIP의 `README.md` 첫 줄들은 결과 상태, 카드·근거·유사 연구 수, 생성 방식별 카드 수(astra·rule·mock)를 적는다.

오류:

| 코드 | 언제 |
|---|---|
| 422 | `result`와 `plan_text`가 모두 없다, `result`가 계약에 맞지 않는다, 결정 로그의 `card_id`·`item_id`가 결과에 없다 |

## GET /premortem/precomputed, GET /premortem/precomputed/{plan_id}

데모 계획서 3건의 사전 계산본(`scripts/precompute_demo.py`가 `<데이터 폴더>/precomputed/`에 만든 것)을 돌려준다. 디스크만 읽고 파이프라인·LLM을 부르지 않는다.

```bash
curl http://127.0.0.1:8000/premortem/precomputed
curl http://127.0.0.1:8000/premortem/precomputed/plan_elife_neuro     # plan_id(64hex) 또는 데모 이름
```

- 목록 응답 키: `label`("사전 계산본"), `available`, `reason`, `generated_at`, `source`(`pipeline`·`fixture`), `pipeline`, `llm`, `items`. 항목마다 `plan_id`, `demo`, `title`, `label`("사전 계산본(<생성 시각>)"), `source`, `status`, `cards_total`, `cards_by_generator`, `sha256`, 무결성 검사 결과.
- 단건 응답: `PremortemResult`에 표시를 더한 것. `notices` 맨 앞에 "사전 계산본(<생성 시각>) — 실시간 분석이 아니라 미리 계산해 둔 결과다"가 붙고, fixture로 대체된 사전 계산본이면 그것도 적는다. 응답 헤더 `x-neumann-precomputed: 1`, `x-neumann-precomputed-generated-at`, `x-neumann-precomputed-sha256`.
- 없는 id → `404 {"detail": {"code": "not_found", "message": "해당 계획서의 사전 계산본이 없다"}}`. 파일 sha256이 매니페스트와 다르면(변조) 404.
- 실측 메모: 확인 시점의 공유 데이터 폴더에 있던 사전 계산본 3건은 파이프라인 병합 전에 만든 fixture 대체본이었고, 응답에 `source: "fixture"`와 대체 사실이 그대로 표시됐다. 파이프라인으로 다시 만들면 `source: "pipeline"`이 된다(RUNNING §5-3).

## GET /templates, GET /templates/{item_id}

입력 화면의 템플릿 선택기와 "예시 불러오기"가 쓴다.

```bash
curl http://127.0.0.1:8000/templates
curl http://127.0.0.1:8000/templates/materials-gnn
```

- 목록 응답 키: `version`, `scope`(`label`: "AI 활용 과학 연구 계획서 전용", `domains` 5개), `required_sections`(연구 목표·방법·데이터·평가·일정), `templates`, `examples`.
- 실측 id: 템플릿 `materials-gnn`, `protein-molecule`, `physics-pde-climate`, `neuro-fmri`, `medical-imaging` · 예시 `example-battery`, `example-fmri`, `example-medimaging`.
- 단건 응답 키: `id`, `kind`(template·example), `name`, `domain`, `summary`, `sections`, `text`(계획서 골격 본문), `filename`, `source`, `chars`, `sha256`. 없는 id는 404.

## GET /api, GET /taxonomy, GET /config/weights

```bash
curl http://127.0.0.1:8000/api
curl http://127.0.0.1:8000/taxonomy
curl http://127.0.0.1:8000/config/weights
```

- `/api`: 데이터 폴더의 매니페스트에서 읽은 실측값만 돌려준다. 키: `service`, `version`, `schema_version`, `status`, `reasons`, `summary_ko`, `corpus`, `index`, `endpoints`. 매니페스트가 없으면 빈 값과 사유(`reasons`). 실측 `summary_ko`: "ICLR 2024 · ICLR 2025 · 논문 1,128편 · 심사평 5,366건 · 거절 60.3% · 색인 문장 133,769개"(심사평 5,366건은 공식 심사평 4,298 + 메타리뷰 1,068).
- `/taxonomy`: 택소노미 v1.0. 키: `version`, `source`, `tier1_count`(10), `tier2_count`(59), `severity_scale`(S1~S5), `classes`, `detect_paths`, `note`.
- `/config/weights`: 위험점수 공식. 실측(줄임):

```json
{"formula": "product", "formula_ko": "위험점수 = 유사도 × 빈도 × 심각도 × 신뢰도 (곱, 가중치 없음)",
 "weighted": false, "weights": null, "display": "곱 · 가중치 없음",
 "decision": {"source": "docs/decisions.md 2026-09-30 19:15 (PM)", "summary": "…"},
 "legacy_design_weights": {"status": "제품에서 쓰지 않는 옛 설계값", "used_in_product": false,
                           "values": {"similarity": 0.3, "frequency": 0.3, "severity": 0.3, "confidence": 0.1}},
 "pipeline": {"module": "neumann.analyze.cards", "state": "ok",
              "formula": "product_v1: similarity * frequency * severity * confidence", "matches": true}}
```

## MCP 서버 (stdio)

HTTP 서버와 별개 프로세스다. 외부 에이전트가 근거 데이터를 조회하는 창구이고, 쓰기·삭제·외부 네트워크 호출이 없다.

```bash
python -m neumann.api.mcp_server
```

| 도구 | 입력 | 출력 |
|---|---|---|
| `search_similar_works` | `query`(검색어, 300자 이하. 계획서 본문은 받지 않는다), `k` | 논문 id·제목·원문 URL·점수(0~1) |
| `get_review_records` | `work_id` | 심사평·저자 답변·결정 요약과 원문 URL(신원 정보 없음) |
| `get_post_status` | `doi` | 철회·정정·우려표명 등 사후 상태와 공지 링크 |

확인: `python -m pytest tests/e4 -q -k mcp` → `11 passed`(SDK 클라이언트로 서버를 띄워 도구 3개 목록·호출 형식·없는 id 처리를 검사).

## POST /upload/plan

계획서 파일에서 텍스트를 뽑는다. 분석은 하지 않는다(뽑은 텍스트를 `/premortem`·`/premortem/view`에 보낸다). 입력 화면의 파일 올리기를 이 엔드포인트에 연결하는 것은 예정(E4-L1f)이고, 지금 화면은 MD·TXT 파일을 브라우저에서 직접 읽는다.

```bash
curl -X POST http://127.0.0.1:8000/upload/plan -F "file=@tests/fixtures/plans/plan.md"
```

- 본문: `multipart/form-data`, 필드 `file` 하나.
- 형식: txt·md(인코딩 추정 UTF-8 → CP949), pdf, docx. 확장자와 매직바이트를 함께 본다.
- 상한(넘으면 413, 붐비면 503): 파일 10MB, 추출 글자 50,000자, PDF 200쪽, DOCX 압축 해제 20MB·항목 1,000개·압축비 100배, 처리 20초, 동시 2건. pdf·docx 추출은 별도 프로세스에서 돌리고 시간이 넘으면 강제 종료한다.
- 디스크에 쓰지 않는다. 로그에 본문·파일명을 남기지 않는다.
- 응답 키: `filename`, `kind`, `size_bytes`, `pages`, `encoding`, `text`, `lines`, `chars`, `warnings`.

실측(TestClient, main `d1dc0aa`):

```
plan.md → 200 {"filename": "plan.md", "kind": "md", "size_bytes": 1089, "pages": null, "encoding": "utf-8", "lines": 27, "chars": 644, "warnings": []}
plan.hwp(HWP 매직바이트) → 415 {"detail": "HWP는 PDF나 DOCX로 저장해 올려 주세요"}
빈 파일 → 422 {"detail": "빈 파일입니다"}
```

| 코드 | 언제 |
|---|---|
| 400 | multipart 형식 오류, 파일 여러 개 |
| 413 | 상한 초과 |
| 415 | HWP·HWPX, 그 밖의 미지원 형식 |
| 422 | `file` 필드 없음, 빈 파일, 손상·암호 PDF, 텍스트 없음 |
| 503 | 동시 처리 상한 초과 |
