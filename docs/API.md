# API

- 기준: `main` 커밋 `ed1d1a0`. 아래 응답 예시는 그 커밋의 서버(`127.0.0.1:8125`)에 실제로 요청해 받은 값을 줄인 것이다.
- **있음** = main의 서버에 라우트가 있다. **예정** = 과제 브랜치에서 진행 중이다. 지금 요청하면 404다.
- 서버 실행은 [RUNNING.md §6](RUNNING.md#6-서버-실행-있음). 기본 주소 `http://127.0.0.1:8000`.
- 전체 스키마: `GET /openapi.json`(서버가 만든 OpenAPI). `GET /docs`도 FastAPI 기본값으로 열리지만 Swagger UI 파일을 외부 CDN(jsdelivr)에서 받는다. 오프라인 확인에는 `/openapi.json`을 쓴다.

## 목록

| 메서드·경로 | 하는 일 | 상태 |
|---|---|---|
| `GET /` | 화면(`webui/index.html`) | 있음 |
| `GET /fonts/{경로}` | 로컬 폰트 파일 | 있음 |
| `GET /health` | 서버 상태, 단계별 모듈 import 가능 여부, 선택 라우터 상태 | 있음 |
| `POST /premortem` | 계획서 텍스트 → 분석 결과 JSON(`PremortemResult` 모양) | 있음 (파이프라인 미연결: 샘플) |
| `POST /premortem/view` | 같은 입력 → 화면 데이터 JSON(`ui_view` 계약) + `_status` | 있음 (파이프라인 미연결: 샘플) |
| `POST /premortem/package` | 분석 결과(또는 계획서) → ZIP 9파일 | 있음 |
| `POST /upload/plan` | 파일(txt·md·pdf·docx, 10MB) → 텍스트. HWP 거부 | 예정 (E4-L1a) |
| `GET /templates`, `GET /templates/{id}` | AI for Science 계획서 템플릿 목록·골격 | 예정 (E4-L1b) |
| `GET /api`, `GET /taxonomy`, `GET /config/weights` | 코퍼스 실측 메타, 위험 유형 R0~R9, 위험점수 가중치 | 예정 (E4-L1d) |
| `GET /premortem/precomputed`, `GET /premortem/precomputed/{plan_id}` | 데모 사전 계산본(오프라인 폴백, 변조 시 404) | 예정 (E6-L2a) |
| MCP 서버(stdio) `python -m neumann.api.mcp_server` | 읽기 전용 도구 3종: `search_similar_works`, `get_review_records`, `get_post_status` | 예정 (E4-L2b) |

예정 라우터 중 `upload`·`templates`·`meta`·`precomputed`는 모듈이 main에 들어오면 `api/main.py`가 자동으로 붙인다. 붙었는지는 `/health`의 `routers`에서 `ok`로 확인한다.

## 지금 main에서 분석이 어떻게 도는가

`neumann.pipeline`(E3-L0)이 main에 없다. 그래서 `/premortem`과 `/premortem/view`는 입력한 계획서를 분석하지 않고, 공용 fixture `tests/fixtures/premortem_result.json`(가짜 데이터)을 돌려준다. 응답에는 다음 표시가 붙는다.

- `/premortem`: `status: "degraded"`, `sample: true`, `notices[0]`에 "분석 파이프라인 미연결(샘플 데이터): …", `stages[0].impl: "fallback:sample"`
- `/premortem/view`: `_status.source: "sample"`, `_status.label: "분석 파이프라인 미연결(샘플 데이터)"`, 화면 상단에도 같은 문구
- 샘플의 `plan_id`는 입력 계획서가 아니라 fixture 계획서의 id다.

파이프라인 모듈이 들어오면 같은 라우트가 실제 분석 결과를 돌려준다. 모듈이 있는데 import나 실행이 실패하면 샘플로 덮지 않고 500과 오류 상태를 돌려준다(예외 메시지는 싣지 않는다).

## GET /health

```bash
curl http://127.0.0.1:8000/health
```

```json
{
  "status": "ok",
  "version": "0.0.1",
  "pipeline": {"state": "unavailable", "reason": "neumann.pipeline 모듈 없음", "mode": "sample",
               "label": "분석 파이프라인 미연결(샘플 데이터)"},
  "stages": {
    "pipeline": {"available": false, "modules": {"neumann.pipeline": "missing: 모듈 없음"}},
    "INPUT":    {"available": false, "modules": {"neumann.analyze.plan": "missing: 모듈 없음"}},
    "RISK":     {"available": false, "modules": {"neumann.analyze.cards": "missing: 모듈 없음"}},
    "models":   {"available": true,  "modules": {"neumann.models": "ok"}},
    "...": "EVIDENCE, REVIEW, ACTION, TRACE, llm, config 도 같은 모양"
  },
  "routers": {"neumann.api.export": "ok", "neumann.api.upload": "missing", "neumann.api.precomputed": "missing",
              "neumann.api.templates": "missing", "neumann.api.meta": "missing"}
}
```

- `pipeline.state`: `connected`(모듈 있음) · `unavailable`(모듈 없음 → 샘플) · `error`(import 실패)
- 모듈 상태: `ok` · `missing: …` · `error: …`

## POST /premortem

요청 본문(JSON):

| 키 | 타입 | 제약 |
|---|---|---|
| `plan_text` | 문자열 | 필수, 1~200,000자, 공백만이면 422 |
| `filename` | 문자열 | 선택, 255자 이하 |

```bash
curl -X POST http://127.0.0.1:8000/premortem \
  -H "Content-Type: application/json" --data-binary @req.json
# req.json: {"plan_text": "# 연구계획서\n랜덤 분할로 평가한다.", "filename": "plan.md"}
```

Windows Git Bash에서는 한글을 `-d '…'`로 직접 넘기면 인코딩이 깨져 400이 날 수 있다. UTF-8 파일을 `--data-binary @파일`로 보낸다.

응답(200, 줄임):

```json
{
  "status": "degraded", "sample": true,
  "plan_id": "3d35460def76efc4a786dce769e614f0d54d110ee2837da6b8fc1dbcf88ef33c",
  "session_id": "sess_271464b2eef5",
  "stages": [{"name": "run_premortem", "phase": "PIPELINE", "status": "unavailable",
              "reason": "neumann.pipeline 모듈 없음 — 샘플 데이터", "impl": "fallback:sample", "degraded": true,
              "elapsed_s": 0.0, "counts": {}, "details": {}}],
  "notices": ["분석 파이프라인 미연결(샘플 데이터): 입력한 계획서는 분석되지 않았다. 아래 값은 공용 fixture(가짜 데이터)다.", "..."],
  "risk_cards": [{"card_id": "card-fx-leak", "risk_code": "R3", "generator": "mock",
                  "evidence": ["ex_c5986bb2facc61b2", "ex_110f92f3599151f1", "ex_845f5eb5621099f5", "ex_ca5fa760fdb45841"], "...": "..."}],
  "evidence": [{"excerpt_id": "ex_c5986bb2facc61b2", "source_kind": "review", "start": 0, "end": 59,
                "source_url": "https://example.org/fake-venue/forum?id=gnn-001&noteId=rev-gnn-001-a", "...": "text, text_sha256 …"}],
  "...": "similar_works, plan, expected_review, checklist, manifest 등 contracts/premortem_response.schema.json의 키"
}
```

- 카드의 `evidence`는 발췌 id 목록이고, 인용문은 `evidence[]`의 `text`(원문 `[start:end]`)다.
- `generator`: `astra`(LLM) · `rule`(비상 규칙) · `mock`(테스트용 가짜). 지금 샘플은 전부 `mock`이다.

오류:

| 코드 | 언제 |
|---|---|
| 422 | `plan_text`가 없거나 비었거나 너무 길다 |
| 500 | 파이프라인 모듈이 있는데 import·실행이 실패했다. 본문 `{"status": "error", "pipeline": …, "reason": "파이프라인 실행 실패: <예외 종류> @ <파일:줄>"}` |

## POST /premortem/view

본문은 `/premortem`과 같다. 응답은 화면 데이터 계약(`contracts/ui_view.schema.json`)을 따르고, 서버가 응답마다 이 스키마로 검사한다.

최상위 키: `plan`, `pipeline`, `works`, `fams`, `corpus`, `ev`, `cards`, `others`, `review`, `checklist`, `plan_id`, `session_id`, `kpi`, `_status`.

`_status` 예시(실측, 줄임):

```json
{"source": "sample", "label": "분석 파이프라인 미연결(샘플 데이터)", "degraded": true,
 "generators": {"mock": 2}, "contract_ok": true, "dropped": {},
 "input": {"chars": 20, "lines": 2, "filename": "plan.md"}, "pipeline": "unavailable",
 "...": "notices, stages_not_ok, empty_reason, section_errors, contract_errors, server_elapsed_s …"}
```

- `dropped`: 근거가 풀리지 않아 화면에서 뺀 카드·예상 심사평 문장 개수
- `degraded`: 샘플이거나, 결과 status가 degraded·error이거나, 강등 단계가 있거나, 생성 방식이 astra가 아닌 카드가 있으면 `true`
- `empty_reason`: 카드가 0장일 때 사유

## POST /premortem/package

분석 결과를 ZIP 9파일로 묶는다: `README.md`, `manifest.json`, `risk_cards.json`, `evidence_pack.json`, `similar_works.csv`, `plan_annotated.md`, `neumann_report.md`, `ai_context.md`, `decision_log.json`.

요청 본문(JSON, `result`나 `plan_text` 중 하나 이상):

| 키 | 뜻 |
|---|---|
| `result` | 분석 결과 JSON. `PremortemResult`로 검증한다(모르는 키는 거부) |
| `plan_text` | 계획서 원문(최대 1,000,000자). `result` 없이 오면 파이프라인을 돌린다. 지금 main은 파이프라인이 없어서 카드 0장·`status: "error"` 패키지를 만든다(가짜 카드를 만들지 않는다) |
| `decisions` | 결정 로그. 항목 `{"card_id"` 또는 `"item_id", "decision": "adopt"·"hold"·"reject"(채택·보류·기각도 받음), "note"?, "decided_at"?}` |

`result`로 감싸지 않고 결과 JSON을 그대로 보내도 된다(`session_id`·`plan_id`가 있으면 결과로 본다).

```bash
curl -X POST http://127.0.0.1:8000/premortem/package \
  -H "Content-Type: application/json" --data-binary @pkg_req.json -o package.zip
# pkg_req.json: {"result": <tests/fixtures/premortem_result.json 내용>,
#                "decisions": [{"card_id": "card-fx-leak", "decision": "채택", "note": "분할을 저자 단위로 바꾼다"}]}
```

응답: `200 application/zip`, `Content-Disposition: attachment; filename="neumann_package_3d35460def76.zip"`. 실측한 `README.md` 첫 줄들:

```
# Neumann 내보내기 패키지
- 결과 상태: **ok** — 강등된 단계 없음
- 위험카드 2장 · 근거 발췌 8건 · 유사 연구 3편
- 생성 방식: astra(LLM) 0장 · rule(규칙 비상 경로) 0장 · mock(테스트용 가짜) 2장
```

오류:

| 코드 | 언제 |
|---|---|
| 422 | `result`와 `plan_text`가 모두 없다, `result`가 계약에 맞지 않는다, 결정 로그의 `card_id`·`item_id`가 결과에 없다 |

알려진 제약(main `ed1d1a0`): 지금 `/premortem`의 **샘플 응답**을 그대로 `/premortem/package`에 보내면 422다. 샘플에 붙는 표시 키(`sample`, `stages[0]`의 `status: "unavailable"`·`degraded`·`details`)가 `PremortemResult` 계약에 없기 때문이다. 실제 파이프라인 결과나 `tests/fixtures/premortem_result.json`은 통과한다.

## 예정 엔드포인트 (main에 없음)

아래는 과제 지시문(`docs/tasks/`) 기준 설계다. 모양은 병합 때 바뀔 수 있으므로 병합 뒤 `/openapi.json`과 과제 보고서를 본다.

| 경로 | 과제 | 지시문 요약 |
|---|---|---|
| `POST /upload/plan` | E4-L1a | txt·md·pdf·docx에서 텍스트 추출, 10MB 초과 거부, HWP·HWPX는 415와 "PDF나 DOCX로 저장" 안내, 디스크에 저장하지 않음. 텍스트·줄 수·추출 경고 반환 |
| `GET /templates`, `GET /templates/{id}` | E4-L1b | 분야별 계획서 골격(한국어)과 설명, 데모 계획서 3건 연결 |
| `GET /api` | E4-L1d | 코퍼스 편수·분야별 수·심사평 수·거절 비율·색인 문장 수·빌드 시각(매니페스트 실측값만, 없으면 빈 값과 사유) |
| `GET /taxonomy` | E4-L1d | R0~R9 이름·설명·심각도 |
| `GET /config/weights` | E4-L1d | 위험점수 가중치(설정 값, 없으면 기본값과 "기본값" 표시) |
| `GET /premortem/precomputed`, `GET /premortem/precomputed/{plan_id}` | E6-L2a | 데모 3건 사전 계산본 목록·단건, 매니페스트 sha256과 다르면 404, 응답에 "사전 계산본(생성 시각)" 표시 |
| MCP stdio 서버 | E4-L2b | 읽기 전용, 계획서 본문은 받지 않음(검색어만), 결과마다 출처 URL, 신원 정보 없음 |
