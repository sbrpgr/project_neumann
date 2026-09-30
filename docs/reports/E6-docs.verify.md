# E6-docs 검증 보고서 (Sonnet 5.5)

**PASS-조건부** — 병합 전에 아래 "병합 전 고칠 것"을 처리한다. 지금 상태로 병합하면 공개 저장소에 "main에는 분석 파이프라인이 없고 서버는 가짜 샘플만 돌려준다"는 **이미 사실이 아닌 서술**이 들어간다.

- 대상: `task/E6-docs` (마지막 커밋 202c6c7), 문서 3개(`docs/ARCHITECTURE.md`·`RUNNING.md`·`API.md`)와 빌더 보고서
- 소유 밖 변경 없음, 비밀·로컬 경로·기획서 01/06 내용 없음, `verify` 통과. 결함은 하나로 모인다: **문서 기준 커밋 `5e14b1c`가 낡았다**. 빌더는 기준 커밋과 "이후 병합분은 반영하지 않았다"를 문서 맨 위에 밝혔지만, 병합 시점의 main에서는 문서의 핵심 문장이 거짓이다.
- 검증 중 main이 5번 움직였다(`054b1e2` → `603c819` → `2b1aee3` → `5bc0b95` → `304e91e`). 서버·pytest 실측은 `054b1e2`·`603c819` 사본에서 했고, 이후 병합분(E6-L3a, E3-L1c, E5-L2a)은 커밋·파일 목록으로 확인했다.

## 1. 완료 기준별 결과

| # | 항목 | 실행한 것 / 실제 출력 | 판정 |
|---|---|---|---|
| 1 | 소유 밖 변경 | `git diff main...task/E6-docs --stat` → 4파일(`docs/API.md`, `ARCHITECTURE.md`, `RUNNING.md`, `reports/E6-docs.md`)만, +974. `--name-only`에서 소유 밖 0. `contracts/`·`models.py`·데이터·비밀 파일 변경 없음 | 통과 |
| 2 | `python scripts/verify.py` (빌더 worktree) | 보안 126파일·계약 2개·`185 passed`·`verify 통과`, exit 0. worktree 변경 0(추적·미추적 없음) | 통과 |
| 3 | 비밀·내부 정보 | 문서 3개+보고서를 `C:\Users`·`노이만_본선자료`·`sk-`·`sk_proj`·`ghp_`·`AKIA`·`BEGIN PRIVATE`·`@gmail`·`sprbxr`·`Desktop` 등으로 검색 → 0건. `OPENAI_API_KEY`·`NEUMANN_PSEUDONYM_SALT`는 이름만, 값 없음. 경로는 `<공개자료 폴더>`·`<데이터 폴더>`로 일반화 | 통과 |
| 4 | 기획서 01·06 내용 이전 여부 | 두 파일에서 백틱 토큰 429+29개, 20자 이상 줄 전부, 25자 조각을 뽑아 문서와 대조: 산문 겹침 0, 줄 겹침 0. 겹친 백틱 토큰 78개는 전부 main에 실제 있는 라우트·클래스·파일 이름(`/health`, `Excerpt`, ZIP 9파일 이름 등)이고 06에서는 `neumann/` 하나뿐. 보고서가 "열지 않았다"고 쓴 것과 어긋나는 증거는 없음 | 통과 |
| 5 | 문서가 그린 라이선스·출처 | `공개자료/MANIFEST.md`와 대조: ResearchArcade(선언 없음), DISAPERE CC BY-NC 4.0, Retraction Watch(라이선스 파일 없음·CC0 아님), bge-m3 MIT, Pretendard OFL — 일치. URL(huggingface·github nnkennard/DISAPERE·gitlab crossref) 일치. `src/neumann/webui/fonts/`에 폰트 5종 OFL.txt/LICENSE 실재 | 통과 |
| 6 | RUNNING 명령 표본(main `054b1e2` 사본, 산출은 스크래치) | 아래 §3 | 통과 |
| 7 | "있음" 표본 10개 이상 최신 main 확인 | 아래 §2 | 있음 표기는 통과, **문서 서술이 낡은 곳 다수** |
| 8 | "예정"이 "있음"이어야 하는 곳 | 아래 §4 (목록 12건) | **실패 → 조건** |
| 9 | "있음"이어야 할 곳이 "예정", 반대로 "예정"이어야 할 것이 "있음" | "예정→있음" 방향 과장 없음: 문서가 "있음"이라 쓴 것은 전부 main에 코드가 있었다. 아직 main에 없는 것(`/upload/plan`, `analyze/plan.py`, `index/hybrid.py`, `sources/elife.py`)은 "예정"이 맞다 | 통과 |

## 2. "있음" 표본 확인 (최신 main 사본, TestClient 또는 8133 서버, 끝나면 종료)

서버는 `NEUMANN_LLM_PROVIDER=mock`으로만 띄웠다(실제 OpenAI 호출 없음). 8010 미사용, 종료 뒤 `8133 free` 확인 2회.

| # | 문서의 "있음" | 실측 | 결과 |
|---|---|---|---|
| 1 | `GET /` 화면 | `200 text/html` | 맞음 |
| 2 | `GET /fonts/...` | `Pretendard-Regular.woff2` 200 | 맞음 |
| 3 | `POST /premortem` 422 조건 | 공백만 → 422, 200,001자 → 422 | 맞음 |
| 4 | `POST /premortem/package` ZIP 9파일 | 결과 JSON·fixture 결과 모두 200, ZIP 이름 목록이 문서와 같음(README·manifest·risk_cards·evidence_pack·similar_works.csv·plan_annotated·neumann_report·ai_context·decision_log) | 맞음 |
| 5 | package 오류 코드 | `{}` → 422, 없는 `card_id` → 422("결정 로그의 card_id … 결과의 카드에 없다"), 모르는 키 → 422, 결정 `채택` → 200 | 맞음 |
| 6 | `GET /templates`(5+3) | 템플릿 5(`materials-gnn` 등)·예시 3(`example-battery` 등), 단건 200, 없는 id 404 | 맞음 |
| 7 | `GET /taxonomy` | `v1.0`, tier1 10, tier2 59 | 맞음 |
| 8 | `GET /api` 요약 | "ICLR 2024 · ICLR 2025 · 논문 1,128편 · 심사평 5,366건 · 거절 60.3% · 색인 문장 133,769개" 정확히 일치 | 맞음 |
| 9 | MCP 도구 3종 | `TOOL_NAMES`가 문서 이름과 같고 `pytest tests/e4 -q -k mcp` → `11 passed` | 맞음 |
| 10 | `Excerpt.from_source`·`redact_pii`·`normalize_text`·`NeumannModel`·`RISK_NAMES`·`Generator` | `models.py`에 전부 있음. `DecisionEntry`는 `models.py`가 아니라 `api/export.py`에 있으나 문서는 위치를 models로 적지 않아 사실과 어긋나지 않음 | 맞음 |
| 11 | 설정 키 기본값(`LLM_MODEL=gpt-6-astra`, `TIMEOUT_S=60`, `API_PORT=8000`) | `config.py` 일치 | 맞음 |
| 12 | 코퍼스 수치(1,128편·4,298+1,068·12,660·1,128·거절 0.6028·위반 0) | 스크래치에서 다시 조립: 같은 값과 works sha256 `317e966f…` | 맞음 |
| 13 | `/health`의 `routers`·단계 모듈 예시(API.md 44~58행) | **최신 main과 다름** — §4 참고 | 낡음 |
| 14 | `GET /config/weights` 예시(API.md 195~201행) | **최신 main과 다름**(가중치 없는 곱) — §4 참고 | 낡음 |
| 15 | `POST /premortem`·`/view` 샘플 동작(API.md 15~16·28~34·82~128행) | **최신 main과 다름**(실제 파이프라인 연결) — §4 참고 | 낡음 |

## 3. RUNNING.md 명령 표본 실행 (산출은 스크래치, 공유 데이터 폴더 미사용)

| 명령 | 출력 핵심 | 결과 |
|---|---|---|
| `scripts/collect_researcharcade.py` | 1128편, 심사평 4298+1068, 답변 12660, 결정 1128, 거절 0.6028, 9.1초 | 통과 |
| `… --check-sample 5` | "대조: 전부 일치" | 통과 |
| `audit_processed()` | 4개 파일 건수 일치, 위반 `0` | 통과 |
| `python -m neumann.sources.retraction build / lookup / prior` | `rows_read 72684`, `records_written 66737`, `no_target_doi 5947`, 고유 DOI 63,690, `lookup` → `[]`, `prior` → `no_match` | 통과 |
| `eval.disapere_gold` → `baseline_freq` → `macro_f1` | 골드 148·dev 358, 고정 top-3 `R1,R2,R6`, 채점 클래스 R1·R2·R5·R6·R7, 예측 148건 정상 채점 | 통과 |
| `eval.linkage --result tests/fixtures/premortem_result.json --sources tests/fixtures` | `8/8 = 1.000 · 카드 통과 2/2 · 폐기율 없음 · 판정 pass` | 통과 |
| `scripts/build_index.py --source fixtures --out … --no-embed` | 문장 44, 오프셋 대조 메모리·디스크 44/44, `강등: --no-embed` | 통과 |
| `python -m pytest tests/e4 -q -k mcp` | `11 passed, 105 deselected` | 통과 |
| `scripts/build_index_check.py --help` | usage 출력(모델 로드 생략) | 통과 |
| `python -m pytest -q` (main `603c819`, mock provider) | **`639 passed, 9 skipped`** — 문서는 `456 passed, 6 skipped`(§4) | 명령은 통과, **수치 낡음** |
| `verify.py` | §1 #2 | 통과 |
| 실행하지 않음 | `git clone`, `playwright install`, `NEUMANN_LIVE_TESTS=1`, 실데이터 색인 빌드(bge-m3), `ui_shots.py`(서버+파이프라인+모델 로드), MCP stdio 단독 | 제외(지시) |

## 4. 병합 전 고칠 것 — 최신 main에 이미 병합됐는데 문서는 "예정/미연결"인 곳

증거는 main 사본 `054b1e2`·`603c819`의 실측과 커밋 목록이다.

| # | 문서 위치 | 문서의 서술 | 최신 main 사실 (증거) |
|---|---|---|---|
| 1 | ARCHITECTURE.md:27, 33, 44, 99~100, 144 / RUNNING.md:130~131, 142 / API.md:15~16, 28~34 | "분석 파이프라인·`llm.py`·`pipeline.py`·지적 추출·카드 합성 예정(E3-L0)", "main에는 아직 분석 파이프라인이 없다. 서버는 입력한 계획서를 분석하지 않고 샘플을 돌려준다" | **E3-L0 병합됨**(`09b5ed5`). `src/neumann/llm.py`, `pipeline.py`, `analyze/{cards,extract,queries,rules,backend,risk_brief,mock_responders}.py` 존재. `/health` → `pipeline.state: "connected"`, `mode: "pipeline"`. `POST /premortem`(mock provider) → `pipeline_version: "neumann-e3-l0"`, 입력 해시 기반 `plan_id`(`80d0b8a5…`, 문서 샘플 `3d35460d…`가 아님), 단계 6개(`plan_normalize`·`query_axes`·`search`·`extract_issues`·`synthesize_cards`·`verify_evidence`), 실제 색인 검색 유사 연구 10편, 무관 입력이라 카드 0장·사유 표시 |
| 2 | RUNNING.md:131 | "이 서버는 OpenAI를 부르지 않는다(파이프라인이 없으므로)" | **거짓**. 기본 provider가 `openai`이고 키가 있으면 `/premortem`이 gpt-6-astra를 부른다(비용 발생). 공개 문서에서 가장 위험한 문장 |
| 3 | API.md:140 | "`plan_text`만 오면 … 지금 main은 파이프라인이 없어서 카드 0장·`status: "error"` 패키지" | 실측: `plan_text`만 보내도 **200 ZIP, 실제 파이프라인 실행**(`plan_id` `80d0b8a5…`). 아직 SEC-1 S-02 수정 전이라 파이프라인(LLM)이 돈다는 뜻이다 |
| 4 | API.md:15~16, 21, 24, 226 / ARCHITECTURE.md:29, 72~73, 108, 115 | "`/premortem/precomputed`·`precompute_demo.py` 예정(E6-L2a), 지금 요청하면 404, `routers.precomputed`는 `missing`" | **E6-L2a 병합됨**(`d74b031`). `GET /premortem/precomputed` → 200(`"label":"사전 계산본"`, 3건, `integrity: ok`), 단건 200, 없는 id 404(`code: not_found`), `/health.routers.precomputed: "ok"`, `scripts/precompute_demo.py`·`api/precomputed.py` 존재 |
| 5 | ARCHITECTURE.md:31, 117 / RUNNING.md:170 | "리포트 카드 예정(E5-L3a)" | **E5-L3a 병합됨**(`ae78b3d`). `eval/report_card.py`, `python -m eval.report_card --help` 동작, `docs/reports/report_card.md` |
| 6 | ARCHITECTURE.md:31, 117 / RUNNING.md:170 | "백테스트 예정(E5-L2a)" | **E5-L2a 병합됨**(`ee66059`, main `304e91e` 시점). `eval/backtest_*.py`, `baseline_llm.py`, `judge_run.py` 존재 |
| 7 | ARCHITECTURE.md:28, 39, 98 | "입력 적합성·PII 예정(E3-L1c)" | **E3-L1c 병합됨**(`4010779`, `304e91e`). `analyze/fitness.py`, `pii.py` 존재. 단, `pipeline.py`가 아직 `assess_fitness`를 부르지 않으므로(적합성 판정은 E3-L0 `queries.py`가 함, 연결은 E3-L1w) "있음(모듈만)"이 맞다 |
| 8 | ARCHITECTURE.md:30 | "규모 확대 예정(E1-L3)" | **E1-L3 병합됨**(`87a345a`): `sources/corpus_l3.py`, `scripts/collect_l3_corpus.py`·`collect_l3_shards.py`(2,128편, `data/processed_l3`). 현재 색인·`/api`는 아직 1,128편이라 본문 수치는 그대로 두고 "확대 코퍼스는 별도 폴더, 색인 반영은 E2-L3"로 정정 |
| 9 | (문서에 없음) | E6-L3b 시연 녹화, E6-L3a 정적 배포 | **E6-L3b**(`ceddce2`): `scripts/record_demo.py` 병합됨. **E6-L3a**(`f68e20e`): `scripts/build_static_site.py`·`build_static_site_shots.py` 병합됨. RUNNING·ARCHITECTURE 어디에도 없다 — 심사자가 "저장소에 있는 스크립트"를 문서로 찾지 못한다. 모듈 지도·RUNNING에 한 줄씩 추가 |
| 10 | API.md:44~58 (`/health` 예시), 63 | `INPUT: neumann.analyze.plan missing`, `RISK: … cards missing`, `pipeline: unavailable`, `EVIDENCE`가 `index.hybrid`를 봄, `routers.precomputed: missing` | `3498feb`로 단계 모듈 이름이 실제 이름으로 바뀜. 실측(`603c819`): `pipeline: connected`, `INPUT: neumann.analyze.queries`, `EVIDENCE: index.search·index.store·analyze.extract`, `RISK: analyze.cards`, `REVIEW: review·gate`, `ACTION: checklist·validate`, `TRACE: api.export`, `llm: ok`, `routers.precomputed: ok`. 빌더 보고서 "넘길 것 7번"(EVIDENCE가 `false`)은 이미 해결됐다 |
| 11 | API.md:195~201, ARCHITECTURE.md §2 RISK 행은 맞음 | `/config/weights` 예시가 `weights 0.3/0.3/0.3/0.1`, `pipeline.state: "missing"`, "결정 기록과 다르다"는 주의 | `dc4ba2d`로 정정됨. 실측: `formula: "product"`, `weighted: false`, `weights: null`, `display: "곱 · 가중치 없음"`, `legacy_design_weights.used_in_product: false`, `pipeline.state: "ok"`. 주의 문단 삭제 |
| 12 | API.md:167 (알려진 제약: 샘플 응답을 package에 보내면 422), 빌더 보고서 "넘길 것 1번" | 샘플 응답 → 422 | 파이프라인 연결로 `/premortem`이 더는 샘플을 돌려주지 않는다(파이프라인 부재·오류일 때만). 이 문단은 "파이프라인이 없을 때의 동작"으로 내리거나 삭제 |

기타 낡은 수치·표현(같은 커밋에서 같이 고친다):

- 문서 머리 "기준: `main` `5e14b1c` … 이후 병합분은 반영하지 않았다"(ARCHITECTURE.md:5, RUNNING.md:3, API.md:3) → 다시 잰 커밋으로 갱신. 병합 순서가 계속 바뀌므로 "기준 커밋은 병합 직전 main"으로 적는다.
- RUNNING.md:142 테스트 수 `456 passed, 6 skipped`와 "`neumann.llm`이 아직 없어 건너뛴 1건" → 실측 `639 passed, 9 skipped`(main `603c819`)로. 건너뛴 9건은 실제 API 테스트(`NEUMANN_LIVE_TESTS`)·`NEUMANN_E2_MODEL_TESTS`·`NEUMANN_UI_TESTS`이고 `neumann.llm` 때문에 건너뛴 것은 없다.
- ARCHITECTURE.md:117 tests 목록에 `e6` 없음.
- RUNNING.md 환경변수 표에 최신 main이 읽는 `NEUMANN_SEARCH_ALPHA`, `NEUMANN_SEARCH_SCORE_FLOOR`, `NEUMANN_EMBED_MAX_SEQ`, `NEUMANN_LLM_EFFORT_*`, `NEUMANN_EXTRACT_STAGE_TIMEOUT_S`가 없다(선택 사항, 있으면 좋음). `NEUMANN_LLM_PROVIDER`는 설정 로더는 `openai|mock`만 받지만 `llm.py`는 `off`도 처리한다(문서의 "openai 또는 mock"은 설정 로더 기준으로 맞음).
- README 개정 초안(빌더 보고서 끝)의 "지금 상태" 표와 "아직 분석 파이프라인이 main에 없다" 문단도 같은 이유로 폐기하고, PM이 병합 뒤 다시 쓴다.

**"있음"이지만 진행 중이라 그대로 두어도 되는 것(확인)**: `review.py`·`gate.py`·`checklist.py`·`validate.py`는 `pipeline.py`가 아직 부르지 않아 "있음(모듈만)"이 여전히 정확하다(`pipeline.py`에 `attach_*`·`assess_fitness` 호출 0건, 연결은 E3-L1w 지시문). 업로드 파서(E4-L1a), 하이브리드 `index/hybrid.py`, `analyze/plan.py`, eLife(E1-L1b)는 main에 없어 "예정"이 맞다.

## 5. 정직성 점검 (문서 서술 자체)

- 문서가 실측이라고 쓴 수치는 재현됨(§2 #8·#12, §3). "예정" 표시가 붙은 항목이 아니라 **낡음**이 결함이다.
- 규칙 결과를 LLM 결과로 쓰거나 mock을 astra로 쓰는 서술은 없다. `generator`(`astra`·`rule`·`mock`)와 강등 표시, `unverified`(2차 검증 실패 시 규칙으로 흉내 내지 않음) 설명이 코드와 일치한다(`review.py`·`checklist.py`·`validate.py` 머리말 대조).
- `docs/API.md`가 공개 저장소 문서에서 "비용 폭주 방지(SEC-1)를 위해 `plan_text` 경로를 없앨 예정"이라고 열린 결함을 적는다(API.md:140). 결정 기록에 이미 같은 내용이 공개돼 있어 비밀은 아니지만, 터널 공개를 SEC-1 수정 뒤로 미룬 상태이므로 수정이 끝나기 전에는 "알려진 제약"에서 SEC-1 언급을 빼는 편이 낫다(권고, 병합 조건 아님).
- README 초안의 "처음부터 만들고 있다"는 기존 README와 같은 문장이지만, 화면은 목업 기반 재구성이다(결정 기록 19:25·19:22가 공개). ARCHITECTURE는 "목업 기반"이라고 적어 정직하다. README를 고칠 때 한 줄 덧붙이길 권한다(권고).

## 6. 병합 전 고칠 것 (조건)

1. **기준 커밋을 병합 직전 main으로 올리고 §4 #1~#12를 반영한다.** 최소한 다음이 반드시 필요하다: ① "파이프라인 없음·샘플" 문장 전부(ARCHITECTURE 27·33·44·54~64·99~100·144, RUNNING 130~131, API 15~16·28~34·44~58·82~128·167)를 실제 동작(`pipeline.state: connected`, `pipeline_version: neumann-e3-l0`, astra 주력·비상 규칙·mock 표시)으로, ② RUNNING.md:131 "OpenAI를 부르지 않는다"를 "기본 provider가 openai라 분석 요청마다 OpenAI(gpt-6-astra)를 호출한다. 시험은 `NEUMANN_LLM_PROVIDER=mock`"으로, ③ `/premortem/precomputed`·`precompute_demo.py`·`report_card.py`·`record_demo.py`·`build_static_site.py`·백테스트를 "있음"으로 옮기고 사용법 한 줄, ④ `/health`·`/config/weights` 예시 교체(§4 #10·#11), ⑤ API.md:140 `plan_text` 설명 교체.
2. API.md의 응답 예시(`/premortem`, `/premortem/view`)는 **실제 파이프라인 응답 모양**으로 다시 받아 쓴다. 지금 예시는 샘플 응답(`sample: true`, `impl: "fallback:sample"`)이라 실제와 다르다. 실제 astra 호출 없이 예시를 얻으려면 `NEUMANN_LLM_PROVIDER=mock`으로 받은 응답(`status: "degraded"`, `notices`에 "mock provider(테스트용) 결과 — 실제 astra 분석이 아니다")을 쓰되, mock임을 문서에 밝힌다.
3. 다시 쓴 뒤 문서의 "있음" 항목 표본을 새 main에서 재확인하고 보고서에 붙인다(특히 `precomputed`, `/health`, `/config/weights`, package `plan_text`).

이 조건은 문서 내용 갱신뿐이며 코드·계약·소유 경로는 건드리지 않는다. 조건 1~3이 해소되면 재검증 없이 PM이 diff의 "예정/미연결/샘플/OpenAI를 부르지 않는다" 검색 0건과 `python scripts/verify.py`만 확인하고 병합해도 된다.

## 7. 못 한 것

- `tests/e4/ui_shots.py`(서버+파이프라인+bge-m3 로드)와 화면 렌더는 실행하지 않았다. 문서의 "화면은 외부 요청을 하지 않는다"는 `webui/index.html`에 외부 URL이 없다는 정적 확인만 했다.
- 새 venv 실설치, `git clone`, 실제 OpenAI 호출, 실데이터 색인 빌드는 지시대로 제외.
- main이 검증 중에도 계속 병합돼 `304e91e` 이후 상태는 확인하지 못했다. E3-L1w(적합성·예상 심사평·체크리스트를 파이프라인에 연결)가 병합되면 "있음(모듈만)" 표기 4곳(ARCHITECTURE §1·§2·§4·§5, API.md `/health` 설명)이 다시 바뀐다.

## 재검증 (02f30a5)

**PASS-조건부** — 1차 "고칠 것" 6개(§6 ①~⑤와 조건 2)는 모두 해소됐고 README 초안의 숫자는 전부 출처와 글자 그대로 일치한다. 다만 검증 중에 main이 `c4679f9` → `497d3f8`(→ `8a26813`, 이후는 `.env.example`·QUEUE만 변경)로 움직였고, 그 사이 병합분(`a736efc` 기본 provider mock, `9a2471e` 검색 보정, `decisions.md` 19:46 정정) 때문에 **문서 3곳의 서술이 또 낡았다**. 문서 내용 갱신뿐이다(코드·계약·소유 경로 무관).

- 대상: `task/E6-docs` 마지막 커밋 `02f30a5`(기준 `c4679f9`). 비교 대상 main은 `497d3f8`(검증 시작 뒤 도착), 마지막 확인 `8a26813`.
- 실제 OpenAI 호출 없음: 서버·명령·verify 모두 `NEUMANN_LLM_PROVIDER=mock`, `OPENAI_API_KEY` 해제 상태. 서버는 8139에서만 두 번(`c4679f9`·`497d3f8` 사본) 띄워 끝냈고 종료 뒤 8139 리스너 없음. 8010은 건드리지 않음. 명령 산출은 전부 스크래치(공유 데이터 폴더는 서버가 읽기만 함, 내 서버 실행 시간대에 쓰인 파일 없음). 빌더 worktree 변경 0.

### 1. 1차 "고칠 것" 1~6 해소 여부

| # | 1차 조건 | 재검증 결과 | 판정 |
|---|---|---|---|
| 1 | ① "파이프라인 없음·샘플" 문장을 실제 동작으로 | 세 문서에서 "파이프라인이 없", "샘플만", "OpenAI를 부르지 않" 0건. 남은 "샘플·미연결"은 전부 "모듈이 없을 때만(지금 main에서는 일어나지 않는다)"(ARCH:71, API:59·127·145). 실서버(`497d3f8`, mock): `/health` `pipeline.state: connected`, `POST /premortem` `pipeline_version: neumann-e3-l0`, `plan_id` = 본문 sha256(실측 일치) | 해소 |
| 2 | ② RUNNING "OpenAI를 부르지 않는다" 삭제·비용 경고 | 문장 삭제, RUNNING·API 머리에 비용 주의 추가됨. **그러나 그 경고의 전제(기본 provider `openai`)가 `a736efc`(19:43)로 거짓이 됐다**(아래 조건 1) | 해소(새 결함 발생) |
| 3 | ③ precomputed·report_card·record_demo·build_static_site·백테스트를 "있음"으로 | 최신 main에 전부 존재: `GET /premortem/precomputed` 200(3건, `label` "사전 계산본", `source: fixture`), 단건 200+`x-neumann-precomputed: 1`, 없는 id 404 `not_found`; `eval/report_card.py`·`backtest_*.py`·`baseline_llm.py`·`judge_run.py`, `scripts/record_demo.py`·`build_static_site.py`·`precompute_demo.py`. `--help`·`--source fixture`·`build_static_site --precomputed …` "검사 통과" 재현 | 해소 |
| 4 | ④ `/health`·`/config/weights` 예시 교체 | `/health`: 단계 10개 모듈 이름·`routers`(`upload`만 `missing`)가 API.md 예시와 줄 단위로 같음. `/config/weights`: `formula: product`, `weighted: false`, `weights: null`, `display: "곱 · 가중치 없음"`, `legacy_design_weights.used_in_product: false`, `pipeline.state: ok` 같음 | 해소 |
| 5 | ⑤ API.md `plan_text` 설명 | "서버가 파이프라인을 돌린다(provider가 openai면 OpenAI 호출)"로 교체, SEC-1 언급 없음. 실측 `plan_text`만 → 200, ZIP 9파일, `cards_by_generator {astra 0, rule 0, mock 6}`(문서 예시 5는 `304e91e` 값) | 해소 |
| 6 | 조건 2: `/premortem`·`/view` 예시를 실제 파이프라인 응답(mock)으로, mock임을 밝힘 | 예시 머리와 `notices`에 "mock provider(테스트용) 결과 — 실제 astra 분석이 아니다"·강등 이유 명시. 응답 키·단계 6개·`manifest`·`notices`·`_status` 모양이 최신 main과 일치, `plan_id` `3d35460d…` 같음. 수치(근거 22, 카드 5, 점수 0.0953)는 `497d3f8`에서 근거 28·카드 6·0.0789로 달라졌으나(E2-L1 검색 보정) 예시가 "`304e91e`에서 받은 값"이라고 문서가 밝히고 있어 거짓은 아님(권고 R3) | 해소 |
| 조건 3 | 새 main 표본 재확인을 보고서에 붙임 | 빌더 보고서 "재측정" 절에 실측 붙음(`304e91e`/`588da63` 기준). 이번 재검증으로 `497d3f8`에서 다시 확인 | 해소 |

1차 §4 나머지도 확인: #7(적합성·PII "있음(모듈만)") 맞음, #8(확대 코퍼스, 기본 색인은 `/api` 그대로 1,128편) 맞음, #9(정적 배포·녹화 추가) 맞음, #12(샘플→package 422 제약) 삭제됨, 기타(테스트 수는 시점 표기, `tests/e6`·`e2e` 추가, 환경변수 표 보강, 기준 커밋 "병합 직전 main") 반영. §5 권고: SEC-1 언급 뺌, README에 "화면은 목업 기반" 한 줄 들어감.

### 2. "있음/있음(모듈만)/예정" 표본 — 최신 main(`497d3f8`) 대조 (40여 개)

- ARCHITECTURE §1 표 26행 전부: "있음" 21행의 경로가 전부 main에 존재(파일·폴더·`scripts/`·`eval/`·`tests/e2e`·`.githooks`), "예정" 2행(업로드 파서·eLife/Europe PMC)은 main에 없음(`src/neumann/api/upload.py`·`sources/elife*` 없음, `/upload/plan` 404, `/health.routers.upload: missing`).
- "있음(모듈만)" 3행(예상 심사평·게이트 / 체크리스트·2차검증 / 적합성·PII 강화판): `review.py`·`gate.py`·`checklist.py`·`validate.py`·`fitness.py`·`pii.py` 존재. `pipeline.py`·`view.py`·`main.py`(헬스의 모듈 이름 제외)가 부르는 곳 0건 → 표기 사실. E3-L1w 미병합.
- API 라우트 11개 + MCP: `/openapi.json` 경로 목록이 문서와 같음. 실측: `GET /`·폰트(`/fonts/Pretendard/Pretendard-Regular.woff2`)·422 두 조건(공백·200,001자)·`/premortem/package` ZIP 9파일 이름(문서와 같음)·오류(`{}` 422, 없는 `card_id` 422, 모르는 키 422, `채택` 200)·`/templates` 5+3·`/taxonomy` v1.0 10/59·`/api` `summary_ko`(1,128편·5,366건·60.3%·133,769개) 모두 문서와 같음. `pytest tests/e4 -q -k mcp` `11 passed`.
- 코퍼스·평가 명령(스크래치 산출): `collect_researcharcade.py` 1,128편·5,366건(4,298+1,068)·12,660·거절 0.6028·works sha256 `317e966f…`, `--check-sample 5` 전부 일치, `audit_processed` 위반 0, `eval.disapere_gold` 골드 148·dev 358, 빈도 기준선 **Macro-F1 0.3308 [95% 0.2980, 0.3623] · Micro 0.5379 [0.4871, 0.5861]**(README 수치를 그대로 재현), `eval.linkage` `8/8 = 1.000`, `build_index --source fixtures --no-embed` 44/44, `python -m neumann.pipeline … --provider mock` 정상, `precompute_demo --source fixture`·`build_static_site` 검사 통과.
- **틀린 표기 1건(과소 표기)**: 전화번호·주민번호 마스킹을 "모듈만"이라고 쓰지만(ARCH:46·168) `pipeline.py`의 `mask_extra_pii`(최소판)가 이미 INPUT 단계에서 전화·주민번호 형태를 가린다(권고 R1).

### 3. README 초안 숫자 대조 (출처와 글자 그대로)

| 초안의 값 | 출처 | 결과 |
|---|---|---|
| Macro-F1 0.4864 [0.4276, 0.5394], Micro 0.5644 | `docs/reports/E5-L1b.md` 표 12행 | 일치 |
| 빈도 기준선 0.3308 [0.2980, 0.3623], Micro 0.5379 | `E5-L1a.md` 84·91행, 위 재현 | 일치 |
| 사람 상한 0.725 | `E5-L1b.md` 11행, `eval/macro_f1.py` `REFERENCE_LINES` | 일치 |
| "Macro에서만 기준선 초과·Micro 구간 겹침·조정은 집계 규칙뿐·1회 채점·단일 실행", 목표 0.70 | `E5-L1b.md` 18·19·188행 | 일치 |
| 1,128편·5,366건(4,298+1,068)·133,769개·오프셋 100% | `E1-L0.md` 23~29·50행, `E2-L0.md` 55~65행, `/api` 실측 | 일치 |
| 라이브 E2E 5/5, 카드 5·3·5장·범위 밖 0장, 근거 10/10·13/13·20/20, 62~70초 | 커밋 `b671d0e` 메시지, `E5-L0e2e_live_summary.json`(`n_cards` 5·3·5, `links`, `ui_total_s` 69.6·62.0·65.1) | 일치(주의 R2) |
| 첫 커밋 18:06, 17:00 이전 커밋 0 | `git log --all` 첫 커밋 `d011edb` 18:06:26, 전 브랜치 최소 시각 18:06 | 일치 |
| v0 19:19 | 초안 본문에 시각은 없고 "태그 `v0`"만 있음. 태그 `v0` 시각 19:19:04(`git tag`) | 모순 없음 |
| 평가 모델 gpt-6-astra / 제품 기본 모델 gpt-6.1-sol 구분 | `decisions.md` 19:38 두 항목, `config.py` 기본값 `gpt-6.1-sol` | 일치(주의 조건 5) |

- 목표 미달을 먼저 적었는가: "지금 상태" 절 첫 문단이 "**목표 미달부터:** … 0.70에 못 미친다"이고 표보다 앞이다. 통과.
- 과장(검증 안 된 성능 주장): 없음. 성능 문장은 전부 실측·정정 각주가 붙었고 "약 62~70초"는 화면 전체 시간(서버 왕복 아님)이라고 메모에 밝힘. L1~L3을 "진행 중"으로 적어 달성 과장 없음.
- "개발 방식과 반입 자료" vs `decisions.md`: 17:00 이전 커밋 0·첫 커밋 18:06(19:25 ④), 목업 기반 재구성·약 55%(19:22), `contracts/`는 기획 원본(19:25 ②), 공개 자료 원본 그대로·가공물 현장 생성(19:25 ③), 사전 개발 점검(19:22)과 같은 사실이다. **결정 기록에 없는 사실 1건**: "사람 1명과 AI 코딩 에이전트"의 "사람 1명"(조건 4).

### 4. 비밀·내부 정보, 소유 경로, verify

- 비밀·내부: 세 문서·보고서·README 초안에서 키 형태(`sk-`·`sk_proj`·`ghp_`·`AKIA`·`BEGIN PRIVATE`)·이메일(`@gmail`·`sprbxr`)·로컬 경로(`C:\Users`·`Desktop`·`노이만_본선자료`·`.claude/worktrees`·`data` 절대경로) 0건. `OPENAI_API_KEY`·`NEUMANN_PSEUDONYM_SALT`는 이름만. 통과.
- 폐기된 기획 문서 이름(`구조_뼈대`·`교훈_함정`·`ID-9x`): 0건. 통과.
- `git diff main...task/E6-docs --stat`: `docs/API.md`, `ARCHITECTURE.md`, `RUNNING.md`, `reports/E6-docs.md`, `reports/E6-docs_README_draft.md`(PM 추가 배정) 5파일, +1,194. `contracts/`·`models.py`·데이터·비밀·소스 변경 없음. main에는 이 5파일 변경이 없어 병합 충돌 없음(파일 겹침 0).
- `python scripts/verify.py`(브랜치 worktree, mock, 키 해제): `897 passed, 41 skipped`, 보안 327파일, 계약 2개, `verify 통과`, exit 0. worktree 변경 0.

### 5. 병합 전 고칠 것 (조건, 문서 수정만)

1. **기본 provider가 바뀌었다(main `a736efc`, 19:43): `config.py`·`llm.py`·`.env.example` 기본값 `mock`.** 다음이 이제 사실이 아니다. ARCHITECTURE.md:66("기본 openai")·143("`openai`(기본)")·144("기본 설정(`NEUMANN_LLM_PROVIDER=openai`)에서는 분석 요청마다 OpenAI API를 부른다"), RUNNING.md:6(비용 주의)·37(표 기본값 `openai`)·62·126(주석 "실제 분석(openai…)"인데 환경변수 없이 이 명령을 돌리면 mock이 돈다), API.md:9·157, README 초안:59("기본 provider는 `openai`라 …"). → "기본은 mock. 실제 OpenAI 호출은 `NEUMANN_LLM_PROVIDER=openai`(+키)로 켤 때만이고 비용이 든다. 실서비스·대표 승인 확인만 켠다(`AGENTS.md` 상시 규칙)"로. 비용 경고는 "openai로 켜면"으로 조건을 바꾼다. `precompute_demo.py` 기본 실행도 이제 mock 결과를 만든다.
2. **README 초안 "공개 서버 방어선" 불릿이 결정 기록 19:46(대표 정정)과 어긋난다.** 초안은 "서버 쪽 일일 예산 상한·차단 스위치·동시 상한이 아직 main에 없고 그것이 켜진 것을 확인해야 터널을 연다"고 쓰지만, 19:46은 "일일 예산 상한은 걸지 않는다(`NEUMANN_DAILY_BUDGET=0`, 차단 스위치 안 켬), 동시 상한·대기열·속도 제한은 안정성 장치로 유지"라고 정정했다. 동시 상한(2건)은 이미 `main.py`에 있고 E4-L2c(대기열·속도 제한)는 아직 main에 없다. → "안정성 장치(동시 상한 있음, 대기열·속도 제한 E4-L2c 예정)와 SEC-1 수정·재점검 뒤에 터널을 연다. 일일 예산 상한은 걸지 않는다(결정 19:46)"로 다시 쓴다.
3. **RUNNING.md:47 검색 설정 기본값이 낡았다(main `9a2471e`).** `NEUMANN_SEARCH_SCORE_FLOOR` 기본 `0.0` → 비움(임베딩 모델별 보정값, bge-m3 0.45, 어휘만 검색이면 0). 같은 커밋에서 새 키 `NEUMANN_SEARCH_FUSION`(rrf)·`_RRF_K`(60)·`_PER_QUERY_MIN`(1)·`_AXIS_WEIGHTS`·`_ADAPTIVE_ALPHA`가 생겼다(추가는 선택). `index/queries.py`도 모듈 지도에 없다(선택).
4. **README 초안 "사람 1명과 AI 코딩 에이전트"**: "사람 1명"은 `decisions.md`·`HANDOFF.md` 어디에도 없다(항목은 "대표·PM"). 근거가 없으면 "사람(대표)과 AI 코딩 에이전트(빌더·검증자 분리)"로 줄이거나 뺀다.
5. **README 초안 "아래 평가 수치는 모두 `gpt-6-astra`로 잰 값이다"는 범위가 넓다.** 빈도 기준선 0.3308·사람 상한 0.725는 LLM 측정이 아니고 코퍼스·색인 수치도 아니다. 결정 19:38은 "Macro-F1 0.4864, 라이브 E2E, v0, 백테스트"로 한정했다. → "LLM으로 잰 수치(Macro-F1 0.4864, 라이브 E2E)는 `gpt-6-astra`로 잰 값이다"로.

1~5가 해소되면 재검증 없이 PM이 diff에서 `기본 openai`·`=openai`·`예산 상한`·`사람 1명` 검색과 `python scripts/verify.py`만 확인하고 병합해도 된다.

### 6. 권고 (병합 조건 아님)

- R1. ARCHITECTURE.md:46·168과 README "개인정보(이메일·ORCID)는 가린다"를 "이메일·ORCID + 전화번호·주민번호 형태(`pipeline.py` 최소판)"로. 강화판 `analyze/pii.py`만 모듈이다.
- R2. README 표의 "5/5 통과"는 검사 5개(파이프라인 연결 확인 1 + 데모 3 + 범위 밖 1)이고 본문은 4장면만 나열해 세면 어긋난다. 근거 연결 10/10·13/13·20/20은 API를 한 번 더 호출한 실행의 값이고 카드 수 5·3·5는 화면 실행 값이라 plan.md는 카드 5장(화면)·3장(API)로 다르다(`E5-L0e2e.md` 결정 1). "연결률은 API 재호출 실행 기준" 한 줄.
- R3. API.md 예시는 "검색 보정(E2-L1) 이전 값"임을 한 줄 더하면 최신 main과의 수치 차이(근거 22→28, 카드 5→6)가 설명된다. `/view` `_status`에 `records` 키가 새로 생겼다(예시는 "줄임"이라 무해).
- R4. API.md:169 "manifest `status: degraded`"는 실제로 `manifest.result.status`다.
- R5. README "의미 있는 줄 약 55%"는 19:22 측정값이고 `webui/index.html`은 그 뒤 바뀌었다 → "(19:22 측정)". 결정 19:22의 `backtest_plans.py` 정규식 3줄·F1 공식 5줄 공개와 19:25의 1,000줄 초과 병합 10개는 README에 없다. 점검 대비 절이므로 "결정 기록 19:22·19:25 참조" 한 줄 링크를 권한다.
- R6. 빌더 보고서 `E6-docs.md` 앞부분(23행 "서버가 OpenAI를 부르지 않는다" 등 첫 제출 기록)은 낡은 서술이 남아 있다. 맨 위에 "첫 제출 기록"이라고 밝혀 뒀으나 공개 저장소 독자는 놓칠 수 있다.

### 7. 못 한 것

- 실서버·실제 OpenAI 경로, bge-m3 임베딩 검색(문서의 "임베딩이 있을 때 검색 강등 없음")은 금지·제외로 실행하지 않았다. 실서버 응답 예시는 mock·어휘 검색 값만 확인했다.
- 화면 렌더(`ui_shots.py`)·`record_demo.py` 실행, `git clone`·새 venv 설치는 하지 않았다.
- `497d3f8` 위에 브랜치를 실제로 병합해 verify를 돌리지는 않았다(git 쓰기 금지). 파일 겹침 0으로 충돌 없음만 확인했다.

## 재검증 3 (608373b)

**PASS-조건부** — 재검증 (02f30a5)의 조건 5개는 전부 해소됐다. 남은 것은 두 가지다. (1) 검증 중 main에 **E3-L1w(파이프라인 v1 연결, `f204d0c`)가 병합**돼 문서의 "있음(모듈만)"·6단계 서술이 지금 main과 어긋난다(문서만 고치면 된다). (2) ARCHITECTURE.md:145가 "백테스트는 gpt-6-astra로 쟀다"고 써서 아직 재지 않은 것을 잰 것처럼 읽힌다.

- 대상: `task/E6-docs` `608373b`(재작업 2: `43d060d`·`608373b`). 코드는 main `9d2cf54`와 같다(`git diff 608373b main -- src scripts eval tests contracts` 비어 있음). 비교한 main은 검증 중 `9dc4e8f` → `9d2cf54` → `47e45e5` → **`f204d0c`**(E3-L1w 병합)로 움직였다. 서버 실측(아래 §2)은 `9d2cf54`와 `f204d0c` 두 시점에서 했다.
- 브랜치는 검증 중 `e600932`까지 더 나아갔다(`814c93e` 업로드 서술 정정, `e600932` 보고서). 이 절은 지시한 `608373b` 기준이고, `814c93e`가 아래 F1을 이미 고쳤다는 것만 확인했다(§3).
- **실제 OpenAI 호출 없음.** PM 긴급 지시(사용자 환경변수에 `NEUMANN_LLM_PROVIDER=openai`·`NEUMANN_LLM_MODEL=gpt-6-astra`가 남아 있음)에 대한 답: 이미 실행한 파이썬·pytest·verify 명령은 모두 `NEUMANN_LLM_PROVIDER=mock`을 명령줄에 붙였고(명령줄 값이 상속 환경변수를 이긴다), `OPENAI_API_KEY`는 `env -u`로 해제했다(설정 로더가 `has_key: False`를 출력해 확인). `NEUMANN_LIVE_TESTS`도 해제해 `tests/conftest.py:9-10`이 mock으로 고정했고, 서버 확인은 `NEUMANN_EMBED_MODEL`도 해제해 bge-m3를 로드하지 않았다. 결과의 `manifest.llm_provider`가 `mock`이고 `notices`에 "mock provider(테스트용) 결과"가 붙은 것으로 확인했다. **openai를 쓸 수 있었던 명령은 없다.** 정직하게 적어 둘 예외 둘: (a) 코드 기본값을 읽으려고 provider·모델 환경변수를 해제하고 `Settings()`만 만든 한 번(LLM 객체·파이프라인 없음, 키도 해제, 출력 `mock`·`gpt-6.1-sol`), (b) 정규식·파일 존재만 보는 스크립트 한 번은 `neumann`을 import하지 않는다. 상속된 `NEUMANN_LLM_MODEL=gpt-6-astra`는 provider가 mock이라 쓰이지 않았다(설정 로더 출력에서 처음 알았다). 서버는 띄우지 않았다(FastAPI TestClient로 프로세스 안에서만 요청, 포트 0개, 8020·8010 미접촉). 공유 데이터 폴더는 읽기만 했다(검색어 캐시는 astra 결과만 쓴다, mock은 쓰지 않는다: `analyze/queries.py`). 끝난 뒤 임시 worktree 2개와 스크래치 파일을 지웠고, 메인 체크아웃에서 바꾼 것은 이 파일뿐이다.

### 1. 재검증 (02f30a5) 조건 1~5 해소 여부 (608373b 기준 줄 번호)

| # | 조건 | 증거 | 판정 |
|---|---|---|---|
| 1 | 기본 provider `mock`(`a736efc`) 반영. 이전 위치 ARCH 66·143·144, RUNNING 6·37·62·126, API 9·157, README 59 | ARCH:67("기본 mock, 실제 호출은 openai로 켤 때만, 모델 기본값 gpt-6.1-sol")·:145-146. RUNNING:6(비용 주의: 기본 mock, openai로 켜면 호출·비용, 실서비스·승인 확인만)·:37(표 기본값 `mock`)·:68(셸 예시 주석 "기본값과 같다")·:131-132(기본 mock 명령과 openai 명령 분리)·:151(precompute "기본 mock"). API:9·:157. README 초안:59. `기본 openai`·`openai(기본)`·`기본값 openai` 검색 0건, `=openai`는 전부 "켜면" 조건문(ARCH:146, RUNNING:6·132, API:9, README:59). 코드: 환경변수를 모두 해제하고 `Settings()` → provider `mock`, model `gpt-6.1-sol`(`config.py:39-40`) | 해소 |
| 2 | README "공개 서버 방어선"을 결정 19:46대로 | README 초안:84·표:126. 결정 19:46(`decisions.md:35`: 일일 예산 상한 없음, 동시 상한·대기열·속도 제한 유지)·19:20(:19: 터널은 SEC-1 수정·재점검 뒤). `main.py:53` `MAX_CONCURRENT = 2`, `main.py`에 대기열·속도 제한 없음(`429\|rate\|queue` 0건), E4-L2c는 FAIL·재작업(QUEUE) → "동시 상한 있음, 대기열·속도 제한 예정, 터널은 수정 뒤"와 일치. 공개 주소를 켜진 것처럼 쓴 곳 0건(`trycloudflare\|cloudflare\|터널\|8010\|8020` 검색은 README:84·126 두 줄뿐이고 둘 다 계획·조건) | 해소 |
| 3 | RUNNING 검색 설정 기본값·새 키 | RUNNING:46-53이 `index/settings.py:44-56` Field 기본값과 일치: ALPHA 0.6, SCORE_FLOOR 비움(bge-m3 0.45·어휘만 0), FUSION rrf, RRF_K 60, PER_QUERY_MIN 1, AXIS_WEIGHTS `topic=1,method=1,data=1,evaluation=0.5`, ADAPTIVE_ALPHA true, EMBED_BATCH 16, MAX_SEQ 512. `NEUMANN_EXTRACT_STAGE_TIMEOUT_S` 호출 상한+60초(`extract.py:394` 주석)·LLM_TIMEOUT 60(`config.py:41`)·API 127.0.0.1:8000(`config.py:49-50`)도 일치. `index/queries.py`가 ARCH:19·:107에 있음 | 해소 |
| 4 | README "사람 1명" | README 초안:89 "사람(대표)과 AI 코딩 에이전트(빌더·검증자 분리)". `사람 1명` 검색 0건. `decisions.md`·HANDOFF의 "대표·PM"과 같은 사실 | 해소 |
| 5 | "평가 수치는 모두 gpt-6-astra" 범위 | README 초안:23 "LLM으로 잰 것(Macro-F1 0.4864, 라이브 E2E)은 `gpt-6-astra`… 빈도 기준선·사람 상한·코퍼스·색인 수치는 LLM 측정이 아니다"(결정 19:38 범위와 일치), :29·:37도 astra는 v0·라이브 E2E에만 붙음. ARCH:145도 좁혔으나 "백테스트"를 끼워 새 결함이 생겼다(아래 F2) | 해소(README) · 새 결함 F2 |

권고 R1~R5(02f30a5 §6)도 반영됨: R1 전화·주민번호 최소판(ARCH:47·:170, README:107), R2 "검사 5개·연결률은 API 재호출 실행"(README:118), R3 API:4 "예시 수치는 검색 보정 이전 값", R4 API:169 `manifest.result.status`, R5 README:91 "19:22 측정". R6(빌더 보고서 앞부분에 낡은 서술이 남음)은 그대로이고 맨 위 안내(E6-docs.md:7)가 있다.

### 2. "있음 / 있음(모듈만) / 예정"과 기본 provider·모델·업로드 서술의 사실 여부 (실측)

| 서술(608373b) | 실측·증거 | 결과 |
|---|---|---|
| 기본 provider `mock` | 위 §1 #1. 이 노트북은 사용자 환경변수가 `openai`로 덮으므로(PM 지시) 코드 기본값과 실행 결과가 다를 수 있다 → 권고 R1 | 맞음 |
| 제품 기본 모델 `gpt-6.1-sol`, 평가 수치는 `gpt-6-astra`로 측정 | `config.py:40` 기본값. 결정 19:38. LLM으로 잰 수치(Macro-F1 0.4864·라이브 E2E·v0)는 astra가 맞다. **다만 ARCH:145의 "백테스트는 astra로 쟀다"는 사실이 아니다**(F2) | 조건부 맞음 |
| `POST /upload/plan` 있음, 상한·오류 코드(API:244-272) | TestClient: `/openapi.json` 경로 12개에 포함. md 200 `{filename plan.md, kind md, size_bytes 1089, pages null, encoding utf-8, lines 27, chars 644, warnings []}`(문서 예시와 같음), HWP 매직바이트 415 "HWP는 PDF나 DOCX로 저장해 올려 주세요", 빈 파일 422 "빈 파일입니다", `.exe` 415, 10MB+1 413. 상한은 `upload.py:46-64` 그대로(10MB·50,000자·PDF 200쪽·압축 해제 20MB·항목 1,000·압축비 100·20초·동시 2), 오류 코드 표는 `upload.py:625-630`과 같음. `/health.routers` 5개 모두 `ok` | 맞음 |
| **입력 화면의 파일 올리기가 `/upload/plan`을 쓴다(API.md:246)** | `webui/index.html:491` "MD · TXT · 최대 10 MB · PDF · DOCX 준비 중", `accept`는 md·txt만, `readFile`(:596-600)은 md·txt만 브라우저에서 읽는다. `/upload` 참조 0건. E4-L1f(연결)는 QUEUE ⏳, main 미병합 | **거짓(F1)** — `814c93e`가 고침 |
| 공개 터널 주소를 켜진 것처럼 씀 | 4개 문서 어디에도 없음(§1 #2). QUEUE·HANDOFF: E4-L2c FAIL, 터널 공개 금지 | 문제 없음 |
| ARCH §1 표 "있음" 행의 경로 | 문서의 백틱 경로 98개를 저장소에 대조: 없는 것 0. "예정" 1행(eLife·Europe PMC)은 `sources/`에 `elife*` 파일이 없음 | 맞음 |
| API 라우트와 MCP | `/openapi.json` 경로 12개 = `/api`, `/config/weights`, `/health`, `/premortem`, `/premortem/package`, `/premortem/precomputed`, `/premortem/precomputed/{plan_id}`, `/premortem/view`, `/taxonomy`, `/templates`, `/templates/{item_id}`, `/upload/plan`(+ `GET /` 화면·폰트는 문서에 있음) | 맞음 |
| `/health`·`/config/weights`·`/api`·`/taxonomy`·`/templates`·`/premortem/precomputed` 응답 모양 | 실측 키·값이 API.md 예시와 같음(`pipeline.state connected`, 단계 10개 모듈 이름, `routers` 5개 ok, `formula product·weighted false·weights null·used_in_product false`, `summary_ko` "1,128편·5,366건·60.3%·133,769개", 택소노미 v1.0 10/59, 템플릿 5+예시 3, 사전 계산본 3건 `label 사전 계산본`·`source fixture`, 없는 id 404 `not_found`) | 맞음 |
| 422 조건(공백·200,001자), `/premortem/package` `{}` 422, `plan_text`만 200 ZIP 9파일 | 실측 그대로. `manifest.result.status degraded`, `cards_by_generator {astra 0, rule 0, mock 6}`(문서 예시 5는 API:4가 "검색 보정 이전 값"이라 밝힘) | 맞음 |
| **"있음(모듈만)": 예상 심사평·근거 게이트·체크리스트·2차 의미검증·입력 적합성·PII 강화** | `608373b`·main `9d2cf54` 시점에서는 `pipeline.py`가 이 모듈을 부르지 않아 맞았다. **`f204d0c`(E3-L1w 병합)에서는 거짓**: `pipeline.py:41-48` import, `PIPELINE_VERSION = "neumann-e3-l1w"`(:60), mock `POST /premortem` → 단계 10개(`plan_normalize, fitness, query_axes, search, extract_issues, synthesize_cards, verify_evidence, expected_review, checklist, semantic_validate`), `expected_review`·`checklist`(6건) 채워짐, `manifest.prompt_versions`에 `expected_review@v1`, `manifest`에 `timings_s`·`stage_limits_s`·`query_cache`. `fitness.py:26`이 `pii.mask_pii`를 부른다. 부적합 입력(조리법, mock)은 카드 0장, 사유 "입력이 연구계획서가 아니다(mock 판단: …); 검색 안 함", 나머지 8단계 `skipped` | **낡음(F3, 병합 조건 1)** |
| 예정: 업로드 화면 연결(E4-L1f), 대기열·속도 제한(E4-L2c), eLife·EPMC(E1-L1b) | main에 없음 | 맞음 |

### 3. 틀렸거나 낡은 문장 (전수)

| # | 위치(608373b) | 문장 | 사실 | 상태 |
|---|---|---|---|---|
| F1 | API.md:246 | "입력 화면의 파일 올리기가 쓴다" | 화면은 md·txt만 브라우저에서 읽고 PDF·DOCX는 "준비 중"이다(E4-L1f 미병합) | `814c93e`에서 해소(API:246 "화면 연결은 예정(E4-L1f)", ARCH:38 "있음(API만…)"). 병합은 이 커밋 이상으로 |
| F2 | ARCHITECTURE.md:145 | "이미 잰 평가 수치(DISAPERE Macro-F1, 라이브 E2E, v0)와 **백테스트**는 `gpt-6-astra`로 쟀다" | 백테스트는 측정한 적 없다. 기준선 30편 생성만 astra로 했고 Neumann 15편 생성·판정은 보류(결정 19:42, QUEUE E5-L2b, 대표 승인 뒤 `gpt-6.1-sol`). 결정 19:38의 문구를 그대로 옮겼으나 19:42가 바꿨다 | **미해소**(`e600932`에도 그대로) |
| F2b | RUNNING.md:38 | "제품 모델(평가 수치는 `gpt-6-astra`로 잰 것)" | 빈도 기준선·사람 상한은 LLM 측정이 아니다(README:23에서는 이미 좁힘) | 표현만(F2와 같이 고침) |
| F3 | ARCHITECTURE.md:6·15·24·25·26·43·47·50·51·66·114·115·116·147·151·162·164·170 | "있음(모듈만)"·"6단계 중 …검증까지"·"단계 기록 이름은 …verify_evidence(REVIEW)다"·"LLM 호출은 세 곳"·"파이프라인 연결 전" | main `f204d0c`에서 연결돼 있음. 단계 10개, LLM 호출 7곳(fitness·query_axes·extract_issues·synthesize_cards·expected_review·checklist·semantic_validate) | **미해소**(병합 조건 1) |
| F3b | API.md:60 | "`REVIEW`·`ACTION`의 모듈은 있지만 파이프라인이 아직 부르지 않는다" | 지금은 부른다 | 미해소 |
| F3c | API.md:81-110 | `/premortem` 예시가 `pipeline_version neumann-e3-l0`, 단계 6개, `prompt_versions` 3개, `manifest`에 `timings_s` 없음 | `neumann-e3-l1w`, 단계 10개, `prompt_versions`에 `expected_review@v1`(값은 mock으로 받은 것) | 미해소. API:4 머리말은 "수치가 조금 다르다"고만 했고 구조가 바뀐 것은 안 밝힘 |
| F3d | API.md:118 | 부적합 입력 예시 "카드 0장, 사유 '…; 유사 연구 검색 상위 점수 0.031'" | 지금은 검색 전에 멈춘다: "…; 검색 안 함", 이후 단계 `skipped` | 미해소 |
| F3e | README 초안:132 | "L1~L3 행의 '진행 중'은 … 파이프라인 연결 전이라는 뜻이다" | 예상 심사평·체크리스트는 연결됨(태그 `v1`은 대표 점검 뒤라 "진행 중" 자체는 맞음) | 메모만 갱신 |
| — | RUNNING.md:185 | "재측정(main `588da63`…): `908 passed, 22 skipped`" | 시점을 밝혀 거짓은 아니나 낡았다. `608373b` verify는 `994 passed, 42 skipped`(데이터 폴더 없음). 07:00 동결 때 다시 잰다 | 권고 R2 |

### 4. 비밀·경로·폐기 문서·소유 경로

- 5개 파일(`docs/API.md`·`ARCHITECTURE.md`·`RUNNING.md`·`reports/E6-docs.md`·`reports/E6-docs_README_draft.md`)에서 `sk-`·`sk_proj`·`ghp_`·`AKIA`·`BEGIN … PRIVATE`·`@gmail`·`sprbxr`·`C:\Users`·`C:/Users`·`Desktop`·`노이만_본선자료`·`.claude/worktrees`·드라이브 문자 경로·`Bearer`·`Authorization`·`cloudflared`·`.venvs` 검색 0건. `OPENAI_API_KEY`·`NEUMANN_PSEUDONYM_SALT`는 이름만, 값 대입 0건. `git clone` URL(`github.com/sbrpgr/project_neumann`)은 `origin`과 같다.
- 폐기된 기획 문서 이름(`구조_뼈대`·`교훈_함정`·`01_구조`·`06_교훈`·`ID-9`) 0건.
- `git diff main...task/E6-docs --stat`(608373b): 5파일, +1,262(위 5개). `src/`·`contracts/`·`models.py`·데이터·비밀 파일 변경 없음. main 쪽 변경(`docs/tasks/E4-L1f.md`, `QUEUE.md`, E3-L1w의 `src/`·`tests/`·`docs/reports/E3-L1w.md`)과 겹치는 파일 없음 → 병합 충돌 없음.

### 5. verify

`608373b` detached worktree에서 `env -u OPENAI_API_KEY -u NEUMANN_LIVE_TESTS PYTHONPATH="src;." NEUMANN_LLM_PROVIDER=mock PYTHONIOENCODING=utf-8 C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/verify.py` → `994 passed, 42 skipped in 72.02s`, 보안 356파일, 계약 2개, `verify 통과`, exit 0(공개자료·공유 데이터 폴더 환경변수 없이라 실데이터 테스트는 건너뜀). 실행 뒤 worktree 변경 0. 빌더 보고서 "최종 verify"(`897 passed, 41 skipped`, 파일 327개)는 `c4679f9` 시점 값이라 이 커밋과 다르다(권고 R2). `f204d0c`·`e600932`에서는 돌리지 않았다(병합·checkout은 git 쓰기라 하지 않음).

### 6. 병합 전 고칠 것 (문서만, 코드·계약·소유 경로 무관)

1. **E3-L1w 병합(`f204d0c`, `neumann-e3-l1w`)을 반영한다**(F3~F3e). ARCHITECTURE.md의 "있음(모듈만)"을 "있음"으로(:24·25·26·47·50·51·114·115·116·162·164·170), :15·:43·:66의 단계 목록을 10단계(`plan_normalize → fitness → query_axes → search → extract_issues → synthesize_cards → verify_evidence → expected_review → checklist → semantic_validate`, 적합성은 검색 전, 부적합이면 카드 0장·"검색 안 함")로, :147 "LLM 호출은 세 곳"을 7곳으로, :151 "모듈만 있는 LLM 호출(파이프라인 연결 전)"을 "연결됨(실패 시 규칙·`unverified`로 물러나는 동작은 그대로)"으로, :6의 "있음(모듈만)" 정의는 쓰는 곳이 없어지니 지우거나 "지금은 해당 없음". API.md:60 문장 삭제, :81-110 `/premortem` 예시와 :118 부적합 예시를 `NEUMANN_LLM_PROVIDER=mock`으로 다시 받은 응답으로 교체하고 머리말(:4)에 "단계·`pipeline_version`도 E3-L1w 이전과 다르다" 반영, README 초안:132 메모 갱신. 기준 커밋을 `f204d0c` 이상으로. 다시 받을 응답: `NEUMANN_LLM_PROVIDER=mock`으로 `POST /premortem`(단계 10개·`neumann-e3-l1w`)과 무관 입력(`tests/fixtures/plans/negative_recipe.md`).
2. **ARCHITECTURE.md:145의 "백테스트는 gpt-6-astra로 쟀다"를 고친다**(F2): "백테스트 기준선 30편 생성은 `gpt-6-astra`로 했고, 백테스트 측정은 보류(결정 19:42, 재개하면 `gpt-6.1-sol`)"로. RUNNING.md:38은 "LLM으로 잰 평가 수치(Macro-F1 0.4864, 라이브 E2E)는 `gpt-6-astra`"로(F2b).
3. (확인만) 병합 대상은 `608373b`가 아니라 F1을 고친 `814c93e` 이상(`e600932`)이어야 한다. 1·2를 그 위에 얹는다.

1~2가 해소되면 재검증 없이 PM이 diff에서 `모듈만`·`neumann-e3-l0`·`세 곳`·"백테스트는 `gpt-6-astra`로 쟀다"·"화면의 파일 올리기가 쓴다" 검색 0건과 `python scripts/verify.py`만 확인하고 병합해도 된다.

### 7. 권고 (병합 조건 아님)

- R1. RUNNING.md §2(또는 README 실행 절)에 "OS 사용자 환경변수도 환경변수라 코드 기본값 `mock`을 덮는다. 사용자 환경변수에 `NEUMANN_LLM_PROVIDER=openai`가 남아 있으면 개발·시험 명령도 실제 호출로 돈다. 명령줄에 `NEUMANN_LLM_PROVIDER=mock`을 붙이고, 확인은 참·거짓으로만(`bool(os.getenv(...))`)" 한 줄. 이번 검증에서 실제로 걸린 함정이다.
- R2. 테스트 수(RUNNING:185)와 빌더 보고서 "최종 verify"는 시점 값이다. 07:00 동결 때 main 실측 하나로 통일한다.
- R3. README 초안:84는 사실이지만 "SEC-1 지적 수정·재점검"만 적었다. 현재 공개 전제는 E4-L2c(FAIL, 재작업)·E4-L2d·SEC-2 통과다(HANDOFF). "E4-L2c는 검증 FAIL로 재작업 중이라 터널은 닫혀 있다"를 한 줄 덧붙이면 정확하다.
- R4. API.md 업로드 오류 표에 "multipart가 아닌 요청 → 415(`multipart/form-data 형식으로 file 필드에…`)"가 없다. 400·422 행은 코드와 맞다.
- R5. 결정 19:20("`plan_text`만 받아 파이프라인을 돌리는 경로는 없앤다")은 아직 코드에 반영되지 않았다(실측 `plan_text`만 → 200 ZIP). PM이 병합 전에 그 경로를 없애면 API.md:157·:169, RUNNING:6, API:9를 같이 고친다.

### 8. 못 한 것

- 실서버·실제 OpenAI 경로, bge-m3 임베딩 검색, 화면 렌더(`ui_shots.py`)·`record_demo.py`는 지시·규칙상 실행하지 않았다. 서버 응답은 mock·어휘 검색·TestClient 값이다.
- `e600932`(브랜치 끝)와 `f204d0c`(main 끝)에서 `verify`를 돌리지 못했다. `f204d0c` 위에 브랜치를 얹은 결과는 파일 겹침 0이라 충돌 없음만 확인했다.
