# 아키텍처

Neumann은 연구계획서를 받아, 비슷한 연구가 실제로 받은 심사평·저자 답변·결정·정정/철회 기록에서 위험을 찾는다. 결과는 근거 문장과 원문 링크가 달린 위험카드다.

- 기준: 이 문서를 병합하기 직전의 `main`(작성 때 확인한 커밋 `2c37557`, 태그 `v0` 이후).
- 표기: **있음** = main에 코드와 테스트가 있고 제품 경로에서 쓰인다. **있음(모듈만)** = 모듈과 테스트는 있지만 분석 파이프라인이 아직 부르지 않아 서버 응답에는 쓰이지 않는다. **예정** = main에 없다(과제 ID를 붙였다).
- 실행 방법은 [RUNNING.md](RUNNING.md), 엔드포인트는 [API.md](API.md).

## 1. 지금 상태 한눈에

| 영역 | 상태 | 근거(main) |
|---|---|---|
| 데이터 계약(엔티티·불변식) | 있음 | `src/neumann/models.py`, `contracts/*.schema.json` |
| 설정 로더(환경변수 > `.env`) | 있음 | `src/neumann/config.py` |
| 분석 파이프라인(6단계 중 INPUT→EVIDENCE→RISK→검증까지) | 있음 | `src/neumann/pipeline.py` |
| LLM 호출 층(provider `openai`·`mock`·`off`) | 있음 | `src/neumann/llm.py` |
| 검색어·축 추출, 지적 추출, 카드 합성, 비상 규칙 | 있음 | `src/neumann/analyze/queries.py`, `extract.py`, `cards.py`, `rules.py`, `backend.py` |
| 코퍼스: ResearchArcade → AI for Science 1,128편 | 있음 | `src/neumann/sources/researcharcade.py`, `corpus.py`, `scripts/collect_researcharcade.py` |
| 확대 코퍼스·확대 색인(샤드 6개 + 일반 ML, 별도 폴더 `processed_l3`·`index_l3`) | 있음(기본 색인은 1,128편, `NEUMANN_INDEX_DIR`로 전환) | `src/neumann/sources/corpus_l3.py`, `scripts/collect_l3_*.py`, `scripts/build_index_l3.py` |
| 정정·철회 사후 상태(Retraction Watch) | 있음 | `src/neumann/sources/retraction.py` |
| DISAPERE 로더(평가 골드용) | 있음 | `src/neumann/sources/disapere.py` |
| 검색 색인: 문장 Excerpt·비상용 규칙 태그·BM25·bge-m3·하이브리드 검색 | 있음 | `src/neumann/index/`, `scripts/build_index.py` |
| 예상 심사평·근거 게이트 | 있음(모듈만) | `src/neumann/analyze/review.py`, `gate.py` |
| 예방 체크리스트·2차 의미검증 | 있음(모듈만) | `src/neumann/analyze/checklist.py`, `validate.py` |
| 입력 적합성 판정·개인정보 마스킹 강화 | 있음(모듈만) | `src/neumann/analyze/fitness.py`, `pii.py` |
| API 서버와 화면(템플릿 선택기·범위 안내, 입력 화면의 OpenAI 전송·본문 미저장 고지 포함) | 있음 | `src/neumann/api/main.py`, `view.py`, `templates.py`, `webui/index.html` |
| 메타 API(`/api`·`/taxonomy`·`/config/weights`) | 있음 | `src/neumann/api/meta.py` |
| 내보내기 패키지(ZIP 9파일) | 있음 | `src/neumann/api/export.py` |
| 사전 계산본(오프라인 폴백) | 있음 | `src/neumann/api/precomputed.py`, `scripts/precompute_demo.py` |
| MCP 서버(stdio, 읽기 전용 도구 3종) | 있음 | `src/neumann/api/mcp_server.py` |
| 정적 배포 빌드, 시연 녹화 스크립트 | 있음 | `scripts/build_static_site.py`, `scripts/record_demo.py` |
| 평가: 근거 연결 검사, DISAPERE 골드·Macro-F1, 빈도 기준선 | 있음 | `eval/linkage.py`, `disapere_gold.py`, `macro_f1.py`, `baseline_freq.py` |
| 평가: DISAPERE 골드에 제품 지적 추출기(astra·비상 규칙) 채점 | 있음 | `eval/disapere_extract.py` |
| 평가: 백테스트(표본·일반 LLM 기준선·판정 실행기·지표), 리포트 카드 | 있음 | `eval/backtest_*.py`, `baseline_llm.py`, `judge_run.py`, `report_card.py` |
| 라이브 E2E(실서버·Playwright, `NEUMANN_LIVE_TESTS=1`일 때만) | 있음 | `tests/e2e/` |
| 검증 러너·git 훅 | 있음 | `scripts/verify.py`, `.githooks/` |
| 업로드 파서(txt·md·pdf·docx) | 예정 (E4-L1a) | — |
| eLife·Europe PMC | 예정 (E1-L1b) | — |

## 2. 6단계

파이프라인(`run_premortem`)의 단계 기록 이름은 `plan_normalize`·`query_axes`(INPUT) → `search`·`extract_issues`(EVIDENCE) → `synthesize_cards`(RISK) → `verify_evidence`(REVIEW)다.

| 단계 | 하는 일 | 산출 | 상태 |
|---|---|---|---|
| INPUT | 계획서 정규화(NFC·LF)와 줄 번호, 이메일·ORCID 가림. astra가 검색어·방법·데이터·평가 축을 뽑고 연구계획서인지 본다 | `PlanDocument`(줄 목록, `plan_id` = 본문 sha256), 검색어 | 있음(`models.PlanDocument`, `analyze/queries.py`). 적합성 판정 강화판(`fitness.py`)·전화번호 등 마스킹(`pii.py`)은 있음(모듈만) |
| EVIDENCE | 색인에서 유사 연구를 찾고, 그 연구의 심사평에서 astra가 지적을 뽑는다 | 유사 연구 목록, 근거 구간(`Excerpt`: 원문 오프셋·해시) | 있음(`index/search.py`, `analyze/extract.py`). 코퍼스 1,128편·색인 문장 133,769개(`/api` 실측). 사후 상태 소스는 있으나 지금 코퍼스(ICLR)에는 DOI가 없어 이어진 논문은 0편 |
| RISK | 반복되는 지적을 위험 유형 R0~R9로 묶고 점수를 매긴다. 점수 = 유사도 × 빈도 × 심각도 × 신뢰도(곱, 가중치 없음) | 위험카드(`RiskCard`) | 있음(`analyze/cards.py`). 카드 0장이면 사유를 `risk_synthesis.no_card_reason`과 `notices`에 담는다 |
| REVIEW | 카드 근거를 원문과 다시 대조. 예상 심사평(문장마다 근거 번호, 근거 없는 문장은 내보내지 않음) | 검증된 카드, 예상 심사평 | 원문 대조(`verify_evidence`)는 있음. 예상 심사평·근거 게이트는 있음(모듈만) |
| ACTION | 카드별 예방 행동, 연구자의 채택·보류·기각 기록 | 체크리스트, 결정 로그 | 행동 생성·2차 의미검증은 있음(모듈만). 결정 로그(`DecisionEntry`, ZIP의 `decision_log.json`)는 있음 |
| TRACE | 단계별 실행 기록, 사용한 provider·모델·프롬프트 버전·소요 시간, 내보내기 | `stages`, `manifest`, ZIP 9파일 | 있음(`pipeline.py`, `api/export.py`) |

위험 유형 R0~R9의 이름은 `models.py`(`RiskCode`, `RISK_NAMES`)에 있고, 이름·설명·심각도는 `GET /taxonomy`로 볼 수 있다. R0(서술·표현)은 위험이 아니라 표시 전용이다.

## 3. 요청 흐름

```
브라우저 GET /  ──> webui/index.html (폰트는 /fonts, CDN 없음)
     │               입력 화면: 범위 안내 + 템플릿 선택기(GET /templates, /templates/{item_id})
     │
     └─ POST /premortem/view {"plan_text", "filename"?}
            │
            ▼
      api/main.py ── neumann.pipeline.run_premortem (동시 2건)
            │         plan_normalize → query_axes → search → extract_issues → synthesize_cards → verify_evidence
            │         LLM 호출은 설정된 provider(기본 openai = gpt-6-astra, 시험은 mock)
            │         단계가 실패하면 그 단계만 비상 규칙으로 대신하거나 건너뛰고 stages에 남긴다
            │
            ├─ 성공 ─────────────> 결과(PremortemResult)
            ├─ 모듈 import 실패 ─> 500 + 오류 상태(예외 메시지는 싣지 않음)
            └─ 모듈 없음 ────────> 공용 fixture 샘플 + "분석 파이프라인 미연결(샘플 데이터)" 표시(지금 main에서는 일어나지 않는다)
            │
            ▼
      api/view.py build_ui_view ── 근거가 안 풀리는 카드·문장 제외, 생성 방식·강등 전달
            │                       contracts/ui_view.schema.json 검사(위반이면 빈 뷰 + 오류)
            ▼
      화면 데이터 JSON + _status(source, label, degraded, generators, stages_not_ok …)
```

- 입력은 1~200,000자, 공백만이면 422.
- 선택 라우터(`export`·`upload`·`precomputed`·`templates`·`meta`)는 모듈이 있으면 붙는다. 상태는 `/health`의 `routers`에 나온다. 지금 main에서는 `upload`만 `missing`이다.
- 사전 계산본(`/premortem/precomputed`)은 디스크만 읽는다(파이프라인·LLM·임베딩을 import하지 않음). 응답에 "사전 계산본(생성 시각)"을 표시하고, 파일이 매니페스트 sha256과 다르면 404다.
- MCP 서버는 HTTP 서버와 별개의 stdio 프로세스다(`python -m neumann.api.mcp_server`). 색인과 사후 상태를 읽기만 한다.

## 4. 모듈 지도

```
contracts/                     JSON Schema 2종(API 응답, 화면 데이터)                           있음
src/neumann/
├─ models.py                   엔티티·불변식(Provenance, Excerpt, RiskCard, PremortemResult …)  있음
├─ config.py                   설정 로더(SecretStr, 환경변수 > .env)                            있음
├─ llm.py                      LLM 호출 층: JSON 스키마 요청 → 로컬 재검증, openai·mock·off     있음
├─ pipeline.py                 run_premortem: 6단계 순서, 강등을 stages·status에 기록           있음
├─ sources/
│  ├─ researcharcade.py · corpus.py   ResearchArcade → 코퍼스, load_corpus·audit_processed      있음
│  ├─ corpus_l3.py             확대 코퍼스(샤드 6개 + 일반 ML)                                  있음
│  ├─ retraction.py            Retraction Watch CSV → PostStatus, get_post_status(doi)          있음
│  ├─ disapere.py              DISAPERE.zip → 심사평 문장과 사람 라벨                           있음
│  └─ elife …                  eLife·Europe PMC                                                예정 (E1-L1b)
├─ index/
│  ├─ sentences.py             문장 분할 → Excerpt(원문 오프셋)                                 있음
│  ├─ taxonomy.py              비상 경로용 최소 규칙 태거(R0~R8, generator="rule")               있음
│  ├─ bm25.py · embed.py       BM25(영어 어휘) · bge-m3 임베딩(다국어)                           있음
│  ├─ search.py                하이브리드 검색(임베딩 못 읽으면 어휘만, 강등 기록)               있음
│  └─ store.py · settings.py   색인 저장소 · 경로·검색 설정                                      있음
├─ analyze/
│  ├─ queries.py               검색어·축 추출(astra ①), 연구계획서 여부                         있음
│  ├─ extract.py               심사평 지적 추출(astra ②, 발췌 id·줄 번호만 받음)                  있음
│  ├─ cards.py · risk_brief.py 카드 합성(astra ③), 점수는 코드가 곱으로 계산                     있음
│  ├─ rules.py · backend.py    비상 규칙 경로 · 근거 백엔드(색인/fixture)                         있음
│  ├─ mock_responders.py       mock provider용 결정적 응답                                      있음
│  ├─ review.py · gate.py      예상 심사평 · 근거 게이트                                         있음(모듈만)
│  ├─ checklist.py · validate.py  예방 체크리스트 · 2차 의미검증                                있음(모듈만)
│  └─ fitness.py · pii.py      입력 적합성 판정 · 개인정보 마스킹 강화                           있음(모듈만)
├─ api/
│  ├─ main.py                  라우트, 파이프라인 연결, 선택 라우터, /health                     있음
│  ├─ view.py                  결과 → 화면 데이터 계약                                          있음
│  ├─ export.py                ZIP 9파일, POST /premortem/package                               있음
│  ├─ precomputed.py           사전 계산본 목록·단건(변조 시 404)                               있음
│  ├─ templates.py · templates/  AI for Science 계획서 골격 5종 + 예시 3건                     있음
│  ├─ meta.py                  /api · /taxonomy · /config/weights                               있음
│  ├─ mcp_server.py            MCP stdio 서버, 읽기 전용 도구 3종                               있음
│  └─ upload                   계획서 파일 업로드 파서                                          예정 (E4-L1a)
└─ webui/                      index.html(목업 기반), fonts/(로컬 폰트 5종과 라이선스)          있음
scripts/
├─ verify.py                   보안 + 계약 + 전체 pytest                                       있음
├─ collect_researcharcade.py · collect_l3_corpus.py · collect_l3_shards.py   코퍼스 조립·확대    있음
├─ build_index.py · build_index_check.py   색인 빌드 · 점검                                     있음
├─ build_index_l3.py · build_index_compare.py   확대 색인(index_l3) 빌드 · 전후 비교              있음
├─ precompute_demo.py          데모 3건 사전 계산본                                             있음
├─ build_static_site.py · build_static_site_shots.py   서버 없이 도는 정적 데모 사이트          있음
├─ record_demo.py              시연 영상 녹화(Playwright)                                       있음
└─ codex_task.sh               인계 뒤 Codex 과제 실행기                                       있음
eval/                          linkage · disapere_gold · disapere_extract · macro_f1 · baseline_freq   있음
                               backtest_* · baseline_llm · judge_run · judge_envelope · report_card   있음
tests/                         fixtures/(공용 가짜 데이터) + e0·e1·e2·e3·e4·e5·e6·e2e          있음
```

폴더마다 주인 에픽이 하나다(`AGENTS.md` 표). 계약(`contracts/`, `models.py`)은 추가만 한다.

## 5. LLM 경로: astra 주력, 규칙은 비상 경로

- 제품 LLM은 OpenAI Responses API의 `gpt-6-astra` 하나다. 설정 로더가 받는 provider는 `openai`(기본)와 `mock`이다. `llm.py`는 비상 경로 확인용 `off`도 처리한다(파이프라인 명령줄 `--provider off`). 로컬 LLM은 없다.
- **기본 설정(`NEUMANN_LLM_PROVIDER=openai`)에서는 분석 요청마다 OpenAI API를 부른다(비용이 든다).** 시험·데모 준비는 `NEUMANN_LLM_PROVIDER=mock`으로 한다. 테스트는 `tests/conftest.py`가 mock으로 고정한다.
- astra 호출은 세 곳이다: 검색어·축 추출(`query_axes`), 지적 추출(`extract_issues`), 카드 합성(`synthesize_cards`). 추론 강도와 시간 상한은 호출마다 정하고 설정 키로 덮어쓴다(`NEUMANN_LLM_EFFORT_<TASK>`, `NEUMANN_LLM_TIMEOUT_S` 등).
- 모든 호출은 "JSON 스키마 요청 → 로컬 재검증" 한 가지 방식이다. 실패·시간 초과·스키마 위반이면 그 단계만 비상 규칙 경로로 돌리고, 단계 `status`를 `degraded`로 남긴다. 강등이 하나라도 있으면 결과 `status`가 `degraded`가 된다(`PremortemResult` 검증기).
- LLM은 인용문을 쓰지 않는다. 발췌 id·카드 id·계획서 줄 번호만 돌려주고, 인용 문자열은 코드가 원문에서 잘라 붙인다.
- 생성 방식은 카드마다 `generator`(`astra`·`rule`·`mock`)와 `model`로 남고, 결과 `manifest`에 `llm_provider`·`llm_model`·프롬프트 버전이 남는다. mock으로 돌면 `notices`에 "mock provider(테스트용) 결과 — 실제 astra 분석이 아니다"가 붙는다.
- 모듈만 있는 LLM 호출(파이프라인 연결 전): 예상 심사평(`review.py`, 실패하면 카드 제목과 근거 원문 축자 인용으로 규칙 합성하고 `generator="rule"`), 체크리스트(`checklist.py`, 실패한 카드만 규칙 문구), 2차 의미검증(`validate.py`, 실패하면 규칙으로 흉내 내지 않고 `unverified`), 적합성 판정(`fitness.py`, 실패하면 규칙 판정과 `generator="rule"`). 모두 호출 함수 `llm_call`을 주입받는다.

## 6. 근거 정직성 장치

| 장치 | 하는 일 | 상태 |
|---|---|---|
| 오프셋 구간 `Excerpt` | 원문 `source_text[start:end]`를 잘라 `text`를 채운다. 길이·`text_sha256`·공백 구간을 생성자에서 검사한다 | 있음(`models.py`) |
| 파이프라인 원문 대조 | 카드 근거를 원문과 글자 단위로 다시 대조해 통과한 것만 남긴다(`verify_evidence` 단계, 예: "근거 22/22 원문 일치") | 있음(`pipeline.py`) |
| 색인 빌드 때 전량 대조 | 문장 Excerpt를 메모리·디스크 양쪽에서 원문과 대조한다(E2-L0 보고서: 133,769개 100%) | 있음(`scripts/build_index.py`) |
| 근거 연결 검사기 | 카드가 인용한 발췌마다 `원문[start:end] == text`(정규화 없음), 해시, http(s) 링크를 다시 잰다. 오프셋 0은 정상값. 폐기율이 없으면 "폐기율 없음"을 명시 | 있음(`eval/linkage.py`) |
| 카드는 근거가 있어야 생성 | `RiskCard.evidence`는 발췌 id 최소 1개. 카드가 인용한 id는 `PremortemResult.evidence`에 있어야 한다 | 있음(`models.py`) |
| 근거 게이트 | 예상 심사평 문장마다 인용 발췌·카드·줄 번호의 실재, 따옴표 인용의 글자 일치, 숫자의 출처, 개인정보를 검사하고 실패한 문장만 버린다(규칙 검사) | 있음(모듈만, `analyze/gate.py`) |
| 화면 근거 게이트 | 근거가 풀리지 않는 카드와 예상 심사평 문장은 화면에 내보내지 않고 `_status.dropped`에 개수를 남긴다 | 있음(`api/view.py`) |
| 2차 의미검증 | 카드와 행동을 따로 판정. 틀림은 지우지 않고 강등 표시 | 있음(모듈만, `analyze/validate.py`) |
| 생성 방식 표기 | 규칙·mock 결과를 LLM 결과라고 쓰지 않는다. `generator`를 화면·ZIP까지 전달 | 있음 |
| 실패를 숨기지 않음 | 강등 단계는 `stages`·`notices`·화면 `_status.stages_not_ok`에 드러난다. 임베딩을 못 읽으면 어휘 검색만 하고 강등 기록. 카드 0장이면 사유 표시. `/health`는 단계별 모듈을 실제로 import해 보고 | 있음 |
| 사전 계산본 표시 | 사전 계산본은 "실시간 분석이 아니라 미리 계산해 둔 결과"로 표시하고, fixture로 대체된 것이면 그것도 적는다. sha256이 다르면 404 | 있음(`api/precomputed.py`) |
| 출처 필수 | 영속 엔티티는 `provenance`(원문 URL·접근 시각·원문 sha256)가 필수. 코퍼스 전량 검사 `audit_processed()` 위반 0 | 있음 |
| 신원 필드 금지 | 필드 이름에 신원 토큰(`name`·`email`·`orcid`·`author`·`reviewer_id` 등)이 있으면 클래스 정의 시점에 TypeError. 모르는 키는 거부(`extra="forbid"`) | 있음(`models.NeumannModel`) |
| 개인정보 가림 | 이메일·ORCID를 `[EMAIL]`·`[ORCID]`로 가린다(발췌를 만들기 전). 전화번호·주민번호 형태까지 가리는 강화판은 모듈만 | 있음(`models.redact_pii`), 있음(모듈만, `analyze/pii.py`) |
| 비밀값 차단 | 키 형태 문자열·`.env` 값 유출·금지 파일·5MB 초과 파일을 git 훅과 `verify`가 막는다. 찾은 값은 출력하지 않는다 | 있음(`scripts/verify.py`, `.githooks/`) |

## 7. 데이터 출처와 라이선스

데이터 원본과 가공본(코퍼스, 색인, 라벨, 캐시, 사전 계산본)은 저장소에 넣지 않는다(`.gitignore`의 `data/`, `*.parquet`, `*.npy` 등). 원본은 저장소 밖 공개자료 폴더(`NEUMANN_RAW_DIR`)에서 읽기만 하고, 가공본은 데이터 폴더(`NEUMANN_DATA_DIR`)에 쓴다.

| 자료 | 받은 곳 | 라이선스 | 쓰는 곳 | 상태 |
|---|---|---|---|---|
| ResearchArcade (OpenReview 공개 심사 기록 미러) papers·reviews parquet | huggingface.co/datasets/ulab-ai/ResearchArcade-openreview-papers, `-reviews` | 선언 없음. 출처(ResearchArcade, OpenReview 원문 URL)를 표기하고 원본은 재배포하지 않는다 | 코퍼스(ICLR 2024·2025, AI for Science 3분야) | 있음 |
| DISAPERE | github.com/nnkennard/DISAPERE | CC BY-NC 4.0 (비상업) | 평가 골드(리뷰 단위 Tier-1 라벨 148건) | 있음 |
| Crossref–Retraction Watch | gitlab.com/crossref/retraction-watch-data | 라이선스 파일 없음(CC0 아님). 출처(Crossref, Retraction Watch) 표기. 저자·기관·국가 열은 읽자마자 버린다 | 정정·철회 사후 상태 | 있음 |
| 임베딩 모델 BAAI/bge-m3 | huggingface.co/BAAI/bge-m3 | MIT | 한국어·영어 검색 임베딩 | 있음 |
| eLife·Europe PMC | 공개 API | 소스별로 확인 | 분야 보강 | 예정(E1-L1b) |
| 폰트 Pretendard·Jost·IBM Plex Mono·Instrument Serif·Mr Dafoe | Google Fonts 저장소, Pretendard 배포본 | SIL OFL 1.1 (각 폴더에 OFL.txt·LICENSE 동봉) | 화면(`src/neumann/webui/fonts/`) | 있음 |

- 코퍼스의 레코드는 전부 `https://openreview.net/forum?id=…` 원문 링크(심사평·답변·결정은 `&noteId=` 딥링크)를 가진다.
- 리뷰어 신원은 저장하지 않는다. 심사평 본문 안의 포럼 단위 익명 핸들("Reviewer hS7z" 형태)은 원문 오프셋을 지키려고 본문 그대로 두고, 필드로는 저장하지 않는다(결정 기록 2026-09-30 19:00).
- 발표·문서의 숫자는 현장 측정값만 쓴다. DISAPERE 인간 상한 Macro-F1 0.725는 공개 데이터에 대한 외부 참조선이고, 우리 성능이 아니다.

## 8. 계약

- `contracts/premortem_response.schema.json`: 분석 결과(`POST /premortem`) 모양. `PremortemResult.model_dump(mode="json")`이 통과한다.
- `contracts/ui_view.schema.json`: 화면 데이터(`POST /premortem/view`) 모양. 목업의 `DATA` 키(`plan`, `pipeline`, `works`, `fams`, `corpus`, `ev`, `cards`, `others`, `review`, `checklist`)에 `plan_id`, `session_id`, `kpi`를 더한다. 서버는 응답마다 이 스키마로 검사한다.
- `scripts/verify.py`가 두 스키마의 형식을 검사하고, 테스트가 실제 응답을 스키마로 검사한다.
