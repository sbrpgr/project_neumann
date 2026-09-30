# 아키텍처

Neumann은 연구계획서를 받아, 비슷한 연구가 실제로 받은 심사평·저자 답변·결정·정정/철회 기록에서 위험을 찾는다. 결과는 근거 문장과 원문 링크가 달린 위험카드다.

- 기준: `main` 커밋 `ed1d1a0` (2026-09-30 19:00 무렵). 이후 병합분은 반영하지 않았다.
- 표기: **있음** = main에 코드와 테스트가 있다. **예정** = 과제 브랜치에서 진행 중이거나 계획만 있다(main에 없다). 예정 항목에는 과제 ID를 붙였다.
- 실행 방법은 [RUNNING.md](RUNNING.md), 엔드포인트는 [API.md](API.md).

## 1. 지금 상태 한눈에

| 영역 | 상태 | 근거(main) |
|---|---|---|
| 데이터 계약(엔티티·불변식) | 있음 | `src/neumann/models.py`, `contracts/*.schema.json` |
| 설정 로더(환경변수 > `.env`) | 있음 | `src/neumann/config.py` |
| 코퍼스 수집: ResearchArcade → AI for Science 1,128편 | 있음 | `src/neumann/sources/researcharcade.py`, `corpus.py`, `scripts/collect_researcharcade.py` |
| DISAPERE 로더(평가 골드용) | 있음 | `src/neumann/sources/disapere.py` |
| API 서버와 화면 | 있음 | `src/neumann/api/main.py`, `view.py`, `webui/index.html` |
| 내보내기 패키지(ZIP 9파일) | 있음 | `src/neumann/api/export.py` |
| 평가: 근거 연결 검사, DISAPERE 골드, Macro-F1, 빈도 기준선 | 있음 | `eval/linkage.py`, `disapere_gold.py`, `macro_f1.py`, `baseline_freq.py` |
| 검증 러너·git 훅 | 있음 | `scripts/verify.py`, `.githooks/` |
| 검색 색인(문장 분할·BM25·bge-m3) | 예정 (E2-L0) | — |
| 분석 파이프라인·LLM provider(astra/mock) | 예정 (E3-L0) | — |
| 예상 심사평·근거 게이트 / 체크리스트·2차 검증 / 적합성·PII | 예정 (E3-L1a / E3-L1b / E3-L1c) | — |
| 정정·철회(Retraction Watch), eLife·Europe PMC | 예정 (E1-L2 / E1-L1b) | — |
| 업로드·템플릿·메타·사전 계산본 API, MCP 서버 | 예정 (E4-L1a·E4-L1b·E4-L1d·E6-L2a·E4-L2b) | — |

**중요:** main에는 아직 분석 파이프라인(`neumann.pipeline`)이 없다. 그래서 지금 서버는 입력한 계획서를 분석하지 않는다. 공용 fixture(가짜 데이터)로 만든 샘플을 돌려주고, 응답과 화면에 "분석 파이프라인 미연결(샘플 데이터)"을 표시한다(§3).

## 2. 6단계

| 단계 | 하는 일 | 산출 | 상태 |
|---|---|---|---|
| INPUT | 계획서 정규화(NFC·LF)와 줄 번호, 이메일·ORCID 가림. 방법·데이터·평가 축 추출, 입력 적합성 판정 | `PlanDocument`(줄 목록, `plan_id` = 본문 sha256) | 정규화·줄 번호·가림은 있음(`models.PlanDocument`, `normalize_text`, `redact_pii`). 축 추출·적합성 판정은 예정(E3-L0, E3-L1c) |
| EVIDENCE | 유사 연구 검색, 그 연구의 심사평·답변·결정·사후 상태 연결 | 유사 연구 목록, 근거 구간(`Excerpt`: 원문 오프셋·해시) | 코퍼스(1,128편, 심사평 4,298 + 메타리뷰 1,068, 저자 답변 12,660, 결정 1,128)는 있음. 검색 색인은 예정(E2-L0), 사후 상태는 예정(E1-L2) |
| RISK | 반복되는 지적을 위험 유형 R0~R9로 묶고 점수를 매긴다 | 위험 순위(`RiskCard.score`) | 계약(`RiskCard`, `RiskScore`, `RiskCode`)은 있음. 카드 생성은 예정(E3-L0) |
| REVIEW | 위험카드와 예상 심사평. 문장마다 근거 번호, 근거 없는 문장은 내보내지 않음 | 카드, 예상 심사평 | 화면 단의 근거 없는 카드·문장 제외는 있음(`api/view.py`). 생성은 예정(E3-L0, E3-L1a) |
| ACTION | 카드별 예방 행동, 연구자의 채택·보류·기각 기록 | 체크리스트, 결정 로그 | 결정 로그 형식(`DecisionEntry`)과 ZIP의 `decision_log.json`은 있음. 행동 문구 생성은 예정(E3-L1b) |
| TRACE | 단계별 실행 기록과 내보내기 패키지 | `stages`(`StageStatus`), ZIP 9파일 | ZIP은 있음(`api/export.py`). `/health`의 단계별 모듈 상태 보고는 있음. 파이프라인의 단계 기록은 예정(E3-L0) |

위험 유형 R0~R9의 이름은 `src/neumann/models.py`(`RiskCode`, `RISK_NAMES`)와 `src/neumann/api/view.py`(`TAXONOMY`)에 있다. R0(서술·표현)은 위험이 아니라 표시 전용이다.

## 3. 요청 흐름 (현재 main)

```
브라우저 GET /  ──> webui/index.html (폰트는 /fonts, CDN 없음)
     │
     └─ POST /premortem/view {"plan_text", "filename"?}
            │
            ▼
      api/main.py ── neumann.pipeline.run_premortem 지연 import
            │
            ├─ 모듈 없음(지금 main) ─> tests/fixtures/premortem_result.json(가짜)을 PremortemResult로 검증
            │                          + status="degraded", sample=true, notices[0]="분석 파이프라인 미연결(샘플 데이터): …"
            ├─ 모듈 있음, 실행 성공 ──> 결과 그대로
            └─ import·실행 실패 ─────> 500 + 오류 상태(샘플로 숨기지 않음, 예외 메시지는 싣지 않음)
            │
            ▼
      api/view.py build_ui_view ── 근거가 안 풀리는 카드·문장 제외, 생성 방식·강등 전달
            │                       contracts/ui_view.schema.json 검사(위반이면 빈 뷰 + 오류)
            ▼
      화면 데이터 JSON + _status(source, label, degraded, generators, dropped …)
```

- 동시 분석은 2건으로 제한한다(`MAX_CONCURRENT`). 입력은 1~200,000자, 공백만이면 422.
- 선택 라우터(`export`·`upload`·`precomputed`·`templates`·`meta`)는 모듈이 있으면 붙고, 없으면 건너뛴다. 상태는 `/health`의 `routers`에 `ok`·`missing`으로 나온다. 지금 main에서는 `export`만 `ok`다.
- 파이프라인이 main에 들어오면 코드 수정 없이 같은 경로가 "모듈 있음"으로 바뀐다(`/health`의 `pipeline.state`가 `connected`).

## 4. 모듈 지도

```
contracts/                     JSON Schema 2종(API 응답, 화면 데이터)                   있음
src/neumann/
├─ models.py                   엔티티·불변식(Provenance, Excerpt, RiskCard, PremortemResult …)  있음
├─ config.py                   설정 로더(SecretStr, 환경변수 > .env)                        있음
├─ sources/
│  ├─ researcharcade.py        ResearchArcade parquet → Work·ReviewEvent·AuthorResponse·Decision   있음
│  ├─ corpus.py                load_corpus(), audit_processed()(출처·신원 필드 전량 검사)      있음
│  ├─ disapere.py              DISAPERE.zip → 심사평 문장과 사람 라벨                        있음
│  └─ retraction.py · elife …  정정·철회, eLife·Europe PMC                                  예정 (E1-L2, E1-L1b)
├─ index/                      문장 분할·Excerpt·규칙 태그·BM25·bge-m3·검색                 예정 (E2-L0)
├─ analyze/                    검색어·지적 추출·카드·예상 심사평·체크리스트·검증              예정 (E3-*)
├─ llm.py                      provider 추상화(openai·mock)                                예정 (E3-L0)
├─ pipeline.py                 6단계 순서, 강등을 status에 기록                             예정 (E3-L0)
├─ api/
│  ├─ main.py                  라우트, 파이프라인 지연 연결, /health                        있음
│  ├─ view.py                  결과 → 화면 데이터 계약                                      있음
│  ├─ export.py                ZIP 9파일, POST /premortem/package                           있음
│  └─ upload · templates · meta · precomputed · mcp_server                                 예정 (E4-L1a·L1b·L1d, E6-L2a, E4-L2b)
└─ webui/                      index.html(목업 기반), fonts/(로컬 폰트 5종과 라이선스)       있음
scripts/
├─ verify.py                   보안 + 계약 + 전체 pytest                                   있음
├─ collect_researcharcade.py   코퍼스 조립 → <데이터 폴더>/processed/                       있음
├─ codex_task.sh               인계 뒤 Codex 과제 실행기                                   있음
└─ build_index.py · precompute_demo.py                                                     예정 (E2-L0, E6-L2a)
eval/                          linkage · disapere_gold · macro_f1 · baseline_freq          있음
                               backtest · report_card                                      예정 (E5-L2a, E5-L3a)
tests/                         fixtures/(공용 가짜 데이터) + e0·e1·e4·e5                   있음
```

폴더마다 주인 에픽이 하나다(`AGENTS.md` 표). 계약(`contracts/`, `models.py`)은 추가만 한다.

## 5. LLM 경로: astra 주력, 규칙은 비상 경로

설계(계획서 §1.2·§4 E3, 결정 기록 2026-09-30):

- 제품 LLM은 OpenAI Responses API의 `gpt-6-astra` 하나다. provider는 `openai`와 `mock` 둘뿐이다(로컬 LLM 없음).
- astra가 검색어·축 추출, 심사평 지적 추출, 카드 합성을 맡는다. 규칙은 API가 실패하거나 단계별 시간 상한(`NEUMANN_LLM_TIMEOUT_S`)을 넘을 때만 쓰는 비상 경로다.
- 비상 경로로 돌면 그 단계의 `stages[].status`를 `degraded`로 남기고, 결과 `status`가 자동으로 `degraded`가 된다(`PremortemResult` 검증기).
- 모든 호출은 "JSON 스키마 요청 → 로컬 재검증" 한 가지 방식이다.

main에 있는 것과 없는 것:

| 항목 | 상태 |
|---|---|
| 설정 키 `NEUMANN_LLM_PROVIDER`(openai·mock), `NEUMANN_LLM_MODEL`(기본 `gpt-6-astra`), `NEUMANN_LLM_TIMEOUT_S`(기본 60) | 있음(`config.py`) |
| 테스트는 기본으로 `mock` provider(`tests/conftest.py`), 실제 API 테스트는 `NEUMANN_LIVE_TESTS=1`일 때만 | 있음 |
| 카드의 생성 방식 필드 `generator`: `astra`·`rule`·`mock` | 있음(`models.Generator`) |
| 생성 방식·강등 단계를 화면(`_status.generators`, `_status.degraded`)과 ZIP(README·manifest의 `cards_by_generator`)에 그대로 표시 | 있음 |
| `llm.py`(OpenAI·mock provider), 지적 추출·카드 합성 호출, 비상 규칙 경로 | 예정(E3-L0) |

## 6. 근거 정직성 장치

| 장치 | 하는 일 | 상태 |
|---|---|---|
| 오프셋 구간 `Excerpt` | 원문 `source_text[start:end]`를 잘라 `text`를 채운다. 길이·`text_sha256`·공백 구간을 생성자에서 검사한다. `Excerpt.from_source()`로만 만든다 | 있음(`models.py`) |
| 근거 연결 검사기 | 카드가 인용한 발췌마다 `원문[start:end] == text`(글자 그대로, 정규화 없음), 해시, http(s) 링크를 다시 잰다. 오프셋 0은 정상값. 폐기율이 없으면 "폐기율 없음"을 명시 | 있음(`eval/linkage.py`) |
| 카드는 근거가 있어야 생성 | `RiskCard.evidence`는 발췌 id 최소 1개. 카드가 인용한 id는 `PremortemResult.evidence`에 있어야 한다 | 있음(`models.py`) |
| LLM은 인용문을 쓰지 않는다 | LLM은 발췌 id와 계획서 줄 번호만 돌려주고, 인용 문자열은 코드가 원문에서 잘라 붙인다 | 계약은 있음(카드는 id만 가짐). 추출 코드는 예정(E3-L0) |
| 화면 근거 게이트 | 근거가 풀리지 않는 카드와 예상 심사평 문장은 화면에 내보내지 않고 `_status.dropped`에 개수를 남긴다 | 있음(`api/view.py`) |
| 파이프라인 근거 게이트 | 근거 없는 문장은 그 문장만 뺀다. 카드와 행동은 따로 검증 | 예정(E3-L1a, E3-L1b) |
| 생성 방식 표기 | 규칙 결과를 LLM 결과라고 쓰지 않는다. `generator`를 화면·ZIP까지 전달, 샘플은 "샘플 데이터"로 표시 | 있음 |
| 실패를 숨기지 않음 | `/health`가 단계별 모듈을 실제로 import해 `ok·missing·error`로 보고. 파이프라인 오류는 500(샘플로 덮지 않음). 카드 0장이면 사유 표시 | 있음 |
| 출처 필수 | 영속 엔티티는 `provenance`(원문 URL·접근 시각·원문 sha256)가 필수. 코퍼스 전량 검사 `audit_processed()` 위반 0 | 있음 |
| 신원 필드 금지 | 필드 이름에 신원 토큰(`name`·`email`·`orcid`·`author`·`reviewer_id` 등)이 있으면 클래스 정의 시점에 TypeError. 모르는 키는 거부(`extra="forbid"`) | 있음(`models.NeumannModel`) |
| 개인정보 가림 | 이메일·ORCID를 `[EMAIL]`·`[ORCID]`로 가린다. 발췌를 만들기 전에 한다(오프셋 보존) | 있음(`models.redact_pii`) |
| 비밀값 차단 | 키 형태 문자열·`.env` 값 유출·금지 파일·5MB 초과 파일을 git 훅과 `verify`가 막는다. 찾은 값은 출력하지 않는다 | 있음(`scripts/verify.py`, `.githooks/`) |

## 7. 데이터 출처와 라이선스

데이터 원본과 가공본(코퍼스, 색인, 라벨, 캐시)은 저장소에 넣지 않는다(`.gitignore`의 `data/`, `*.parquet` 등). 원본은 저장소 밖 공개자료 폴더(`NEUMANN_RAW_DIR`)에서 읽기만 하고, 가공본은 데이터 폴더(`NEUMANN_DATA_DIR`)에 쓴다.

| 자료 | 받은 곳 | 라이선스 | 쓰는 곳 | 상태 |
|---|---|---|---|---|
| ResearchArcade (OpenReview 공개 심사 기록 미러) papers·reviews parquet | huggingface.co/datasets/ulab-ai/ResearchArcade-openreview-papers, `-reviews` | 선언 없음. 출처(ResearchArcade, OpenReview 원문 URL)를 표기하고 원본은 재배포하지 않는다 | 코퍼스(ICLR 2024·2025, AI for Science 3분야) | 있음 |
| DISAPERE | github.com/nnkennard/DISAPERE | CC BY-NC 4.0 (비상업) | 평가 골드(리뷰 단위 Tier-1 라벨 148건) | 있음 |
| Crossref–Retraction Watch | gitlab.com/crossref/retraction-watch-data | 라이선스 파일 없음(CC0 아님). 출처(Crossref, Retraction Watch) 표기 | 정정·철회 사후 상태 | 예정(E1-L2) |
| eLife·Europe PMC | 공개 API | 소스별로 확인 | 분야 보강 | 예정(E1-L1b) |
| 임베딩 모델 BAAI/bge-m3 | huggingface.co/BAAI/bge-m3 | MIT | 한국어·영어 검색 임베딩 | 예정(E2-L0) |
| 폰트 Pretendard·Jost·IBM Plex Mono·Instrument Serif·Mr Dafoe | Google Fonts 저장소, Pretendard 배포본 | SIL OFL 1.1 (각 폴더에 OFL.txt·LICENSE 동봉) | 화면(`src/neumann/webui/fonts/`) | 있음 |

- 코퍼스의 레코드는 전부 `https://openreview.net/forum?id=…` 원문 링크(심사평·답변·결정은 `&noteId=` 딥링크)를 가진다.
- 리뷰어 신원은 저장하지 않는다. 심사평 본문 안의 포럼 단위 익명 핸들("Reviewer hS7z" 형태)은 원문 오프셋을 지키려고 본문 그대로 두고, 필드로는 저장하지 않는다(결정 기록 2026-09-30 19:00).
- 발표·문서의 숫자는 현장 측정값만 쓴다. DISAPERE 인간 상한 Macro-F1 0.725는 공개 데이터에 대한 외부 참조선이고, 우리 성능이 아니다.

## 8. 계약

- `contracts/premortem_response.schema.json`: 분석 결과(`POST /premortem`) 모양. `PremortemResult.model_dump(mode="json")`이 통과한다.
- `contracts/ui_view.schema.json`: 화면 데이터(`POST /premortem/view`) 모양. 목업의 `DATA` 키(`plan`, `pipeline`, `works`, `fams`, `corpus`, `ev`, `cards`, `others`, `review`, `checklist`)에 `plan_id`, `session_id`, `kpi`를 더한다. 서버는 응답마다 이 스키마로 검사한다.
- `scripts/verify.py`가 두 스키마의 형식을 검사하고, 테스트가 실제 응답을 스키마로 검사한다.
