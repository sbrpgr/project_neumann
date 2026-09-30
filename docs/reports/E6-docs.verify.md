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
