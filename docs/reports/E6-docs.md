# E6-docs 보고서: ARCHITECTURE·RUNNING·API 문서, README 개정 초안

- 브랜치: `task/E6-docs` · 빌더: claude-opus-5.5 · 2026-09-30
- 스펙: `docs/tasks/E6-docs.md`. 읽은 것: `AGENTS.md`, `docs/tasks/_COMMON.md`, 계획서 §0·§2·§4.0·§4(E0~E6), main의 `src/`·`eval/`·`scripts/`·`tests/`, `docs/tasks/`, `docs/reports/`, 진행 중 브랜치의 변경 파일 목록과 스크립트 머리말, 공개자료 `MANIFEST.md`(라이선스)
- 기획 키트의 폐기된 옛 구현 설명 문서 2종은 열지 않았고 옮기지 않았다. 옛 `neumann/` 폴더는 열지 않았다.

> 아래 "무엇을 했나"~"다음 과제에 넘길 것"은 첫 제출(문서 기준 `5e14b1c`) 기록이다. 그 뒤 main에 파이프라인이 연결돼 여러 서술이 바뀌었다. 현재 문서 상태와 재측정은 "재작업" 절을 본다.

## 무엇을 했나

| 파일 | 내용 |
|---|---|
| `docs/ARCHITECTURE.md` | 현재 상태 표(있음·예정), 6단계(INPUT→EVIDENCE→RISK→REVIEW→ACTION→TRACE)별 하는 일·산출·상태, 현재 요청 흐름(파이프라인 미연결 → 샘플 표시), 모듈 지도, astra 주력·비상 규칙 경로(설계와 main 구현 상태를 나눠 적음), 근거 정직성 장치 12종, 데이터 출처와 라이선스, 계약 |
| `docs/RUNNING.md` | 설치(uv venv), 환경변수(키는 이름만), 공개자료 폴더 구조, 코퍼스 조립, Retraction Watch 빌드·조회, 색인 빌드(예정), 서버 실행, 테스트·화면 스크린샷, 평가 명령 4종, verify·훅, 비밀값 규칙 |
| `docs/API.md` | 엔드포인트 표(있음 11 + MCP, 예정 3), 지금 main의 샘플 동작, `/health`·`/premortem`·`/premortem/view`·`/premortem/package`·`/templates`·`/api`·`/taxonomy`·`/config/weights`의 본문·제약·오류 코드·실측 응답, MCP 도구 3종, 알려진 제약, 예정 엔드포인트(과제 지시문 기준) |

문서의 기준 커밋은 **main `5e14b1c`**(커밋 시각 2026-09-30 19:08)다. 작업 중 main이 네 번 바뀌었다(`6067212` → `ed1d1a0` → `82146f9` → `5e14b1c`). `82146f9`에서 E1-L2·E3-L1b를, `5e14b1c`에서 E2-L0 색인·E3-L1a 예상 심사평·E4-L1b 템플릿·E4-L1d 메타 API·E4-L2b MCP를 "있음"으로 고치고 명령과 응답을 다시 확인했다. 아래 출력 중 기준 커밋을 따로 적지 않은 것은 `82146f9`에서, "5e14b1c 재확인" 절은 `5e14b1c`에서 잰 것이다.

## 확인 방법

- worktree(`task/E6-docs`)는 `481e11c`에서 갈라져 main보다 뒤처져 있다. 병합은 금지라, `git archive <main 커밋>`으로 main 사본을 스크래치 폴더에 풀어 그 사본에서 명령을 돌렸다. 저장소와 공유 데이터 폴더에는 아무것도 쓰지 않았다(코퍼스·Retraction 산출은 `--data-dir <스크래치>`로 돌림).
- 환경변수는 `_COMMON.md`와 같다(`PYTHONIOENCODING=utf-8 PYTHONPATH="src;." HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`, `NEUMANN_RAW_DIR`, `NEUMANN_DATA_DIR`). Python은 개발 venv(3.12.10).
- 서버는 8125번에서만 띄웠고 매번 끄고 포트가 비었는지 확인했다(`8125 free`). 무거운 모델 로드와 OpenAI 호출은 하지 않았다(main에는 파이프라인이 없어 서버가 OpenAI를 부르지 않는다).
- 경로 중 로컬 개인 경로는 문서에 쓰지 않고 `<공개자료 폴더>`·`<데이터 폴더>`로 적었다. 아래 출력의 스크래치 경로는 `<SP>`로 줄였다.

## 완료 기준별 결과

### 1. 문서의 명령을 실제로 실행해 확인: 통과(예외는 아래 "실행하지 않은 명령")

**설치(RUNNING §1)** — 기존 개발 venv에 같은 명령을 dry-run·offline으로:

```
$ uv pip install --dry-run --offline --python <개발 venv>/Scripts/python.exe -r pyproject.toml --extra dev
Using Python 3.12.10 environment at: <개발 venv>
Resolved 80 packages in 583ms
Checked 80 packages in 6ms
Would make no changes
$ uv venv --python 3.12 <SP>/venvcheck
Using CPython 3.12.10 interpreter at: …
Creating virtual environment at: <SP>/venvcheck
```

빈 venv에 offline으로는 `torch==2.14.0 needs to be downloaded from a registry`로 해석이 안 된다(네트워크 필요). 그래서 문서에 "새 venv 설치는 네트워크 필요, dry-run으로만 확인"이라고 적었다.

**키 확인(RUNNING §2)**

```
$ python -c "import os; print(bool(os.getenv('OPENAI_API_KEY')))"
True
```

**코퍼스 조립(RUNNING §4)**

```
$ python scripts/collect_researcharcade.py --data-dir <SP>/corpus_out
편수 1128 (사전 집계 1265), 분야별 {'소재·화학·분자': 439, '단백질·생물·신약': 550, '물리·PDE·기후': 387}
심사평 4298 + 메타리뷰 1068, 저자 답변 12660, 결정 1128
결정 분포 {'accept_oral': 32, 'accept_poster': 358, 'accept_spotlight': 58, 'reject': 680}, 거절 비율 0.6028 (사전 집계 0.61)
  works.jsonl: 1128건 sha256=317e966f38405215663b1161349df53320bcf84cd05fea2d5016ff8e6b89570a   (E1-L0 보고서 값과 같음)
  reviews.jsonl: 5366건 sha256=b0ba375f72b2d81d156e0cf75821d831c6cd26bec46e354f07ef30837f55f348  (같음)
소요 21.03초
$ python scripts/collect_researcharcade.py --data-dir <SP>/corpus_out --check-sample 5
… 대조: 전부 일치
$ python -c "from neumann.sources.corpus import audit_processed; r = audit_processed(); print(r['records'], r['violations'])"
{'works.jsonl': 1128, 'reviews.jsonl': 5366, 'author_responses.jsonl': 12660, 'decisions.jsonl': 1128} 0
```

**Retraction Watch(RUNNING §4-1)**

```
$ python -m neumann.sources.retraction build --data-dir <SP>/rw_out
  "rows_read": 72684, "records_written": 66737, "skipped": {"blank_rows": 0, "unknown_nature": 0, "no_target_doi": 5947},
  "unique_target_dois": 63690, "elapsed_s": 3.699
$ python -m neumann.sources.retraction lookup 10.1000/does-not-exist --data-dir <SP>/rw_out
[]
$ python -m neumann.sources.retraction join --data-dir <SP>/rw_out        (works.jsonl을 옆에 복사해 둠)
  "status": "ok", "n_works": 1128, "n_works_with_doi": 0, "n_matched_works": 0
$ python -m neumann.sources.retraction prior "machine learning" --data-dir <SP>/rw_out
  "status": "no_match", …
```

**서버와 API(RUNNING §6, API.md 전체)** — `python -m uvicorn neumann.api.main:app --host 127.0.0.1 --port 8125`(main `82146f9` 사본):

```
$ curl -s http://127.0.0.1:8125/health  (요약)
ok 0.0.1 {"state": "unavailable", "reason": "neumann.pipeline 모듈 없음", "mode": "sample", "label": "분석 파이프라인 미연결(샘플 데이터)"}
{'pipeline': False, 'INPUT': False, 'EVIDENCE': False, 'RISK': False, 'REVIEW': False, 'ACTION': True, 'TRACE': False, 'llm': False, 'models': True, 'config': True}
{'neumann.api.export': 'ok', 'neumann.api.upload': 'missing', 'neumann.api.precomputed': 'missing', 'neumann.api.templates': 'missing', 'neumann.api.meta': 'missing'}
GET / 200 text/html; charset=utf-8
GET /fonts/Pretendard/Pretendard-Regular.woff2 200
openapi paths: ['POST /premortem/package', 'GET /health', 'POST /premortem', 'POST /premortem/view']
$ POST /premortem --data-binary @req.json      # {"plan_text": "# 연구계획서\n랜덤 분할로 평가한다.", "filename": "plan.md"}
HTTP 200
{"status": "degraded", "sample": true, "plan_id": "3d35460def76efc4a786dce769e614f0d54d110ee2837da6b8fc1dbcf88ef33c"}
stages[0] {"name": "run_premortem", "phase": "PIPELINE", "status": "unavailable", "reason": "neumann.pipeline 모듈 없음 — 샘플 데이터", "impl": "fallback:sample", "degraded": true, "elapsed_s": 0.0, "counts": {}, "details": {}}
notices[0] 분석 파이프라인 미연결(샘플 데이터): 입력한 계획서는 분석되지 않았다. 아래 값은 공용 fixture(가짜 데이터)다.
cards 2 generators ['mock'] evidence 8
$ POST /premortem/view --data-binary @req.json
HTTP 200
['cards', 'checklist', 'corpus', 'ev', 'fams', 'kpi', 'others', 'pipeline', 'plan', 'plan_id', 'review', 'session_id', 'works']
{"source": "sample", "label": "분석 파이프라인 미연결(샘플 데이터)", "degraded": true, "generators": {"mock": 2}, "contract_ok": true, "dropped": {}, "input": {"chars": 20, "lines": 2, "filename": "plan.md"}, "pipeline": "unavailable"}
$ POST /premortem  {"plan_text": "   "}
HTTP 422
$ POST /premortem/package --data-binary @pkg_req3.json (fixture result + 결정 1건 "채택")
HTTP 200 application/zip
content-disposition: attachment; filename="neumann_package_3d35460def76.zip"
9 ['README.md', 'manifest.json', 'risk_cards.json', 'evidence_pack.json', 'similar_works.csv', 'plan_annotated.md', 'neumann_report.md', 'ai_context.md', 'decision_log.json']
[{"card_id": "card-fx-leak", "item_id": null, "decision": "adopt", "note": "분할을 저자 단위로 바꾼다", "decided_at": null}]
$ POST /premortem/package --data-binary @pkg_req2.json (plan_text만)
HTTP 200
error {'astra': 0, 'rule': 0, 'mock': 0} [{'name': 'pipeline', 'status': 'error', 'reason': '분석 파이프라인 미연결(ModuleNotFoundError)', 'impl': 'fallback:pipeline_unavailable'}]
$ POST /premortem/package {} / 없는 card_id / /premortem 샘플 그대로
{"detail":"result(분석 결과 JSON)나 plan_text(계획서 텍스트)가 필요하다"} HTTP 422
{"detail":"결정 로그의 card_id 'no-such-card'가 결과의 카드에 없다"} HTTP 422
HTTP 422
[['stages', 0, 'status'], ['stages', 0, 'degraded'], ['stages', 0, 'details'], ['sample']]
$ 예정 경로
GET /api 404 · GET /taxonomy 404 · GET /config/weights 404 · GET /templates 404 · GET /premortem/precomputed 404 · POST /upload/plan 404
```

추가 확인: `GET /docs`는 Swagger UI를 `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/…`에서 받는다(그래서 API.md에 "오프라인은 `/openapi.json`"이라고 적음). Git Bash에서 한글을 `-d '…'`로 직접 보내면 `{"detail":"There was an error parsing the body"}` 400이 났다(그래서 API.md 예시는 `--data-binary @파일`).

서버 종료 확인(4회 모두):

```
PS> Get-NetTCPConnection -LocalPort 8125 -State Listen …; Stop-Process …
8125 free
```

**테스트(RUNNING §7)**

```
$ python -m pytest -q -rs          (main 82146f9 사본, NEUMANN_DATA_DIR = 공유 데이터 폴더)
SKIPPED [1] tests\e3\test_checklist_live.py:73: 실제 API 테스트는 NEUMANN_LIVE_TESTS=1과 OPENAI_API_KEY가 있을 때만
SKIPPED [1] tests\e3\test_checklist_live.py:113: 실제 API 테스트는 NEUMANN_LIVE_TESTS=1과 OPENAI_API_KEY가 있을 때만
301 passed, 2 skipped in 11.76s
```

(`NEUMANN_DATA_DIR` 없이 돌리면 `tests/e1/test_e1_corpus_real.py`가 "공유 데이터 폴더에 E1-L0 코퍼스가 없다"로 건너뛴다 — 문서의 "공유 데이터 폴더가 없으면 건너뛴다"를 확인.)

화면 스크린샷 스크립트(main `6067212` 사본, 8125번):

```
$ python tests/e4/ui_shots.py --port 8125 --out <SP>/shots --prefix E6docs
exit=0
console_errors [] · page_errors [] · external_requests [] · server_stopped True · port_free_after True
dom.cards 2 | header 분석 파이프라인 미연결(샘플 데이터)
```

(스크린샷은 스크래치에만 두고 커밋하지 않았다. 샘플 화면이라 이 과제의 산출물이 아니다.)

**평가(RUNNING §8)** — 출력은 스크래치로:

```
$ python -m eval.disapere_gold --out-dir <SP>/evalout
골드 148건 (주석자 수별 {2: 64, 3: 55, 4: 29}, 해결 {'agreed': 22, 'majority_vote': 126}, no_risk 35)
튜닝(dev) 358건 (no_risk 44)
$ python -m eval.baseline_freq --dev <SP>/evalout/disapere_dev.jsonl --target <SP>/evalout/disapere_gold.jsonl --out <SP>/evalout/pred_baseline_freq.jsonl
고정 출력 top-3: ['R1', 'R2', 'R6'] → 148건
$ python -m eval.macro_f1 --pred <SP>/evalout/pred_baseline_freq.jsonl --gold <SP>/evalout/disapere_gold.jsonl --out <SP>/evalout/score.json
Macro-F1 0.3308 [95% 0.2980, 0.3623]  Micro-F1 0.5379 [95% 0.4871, 0.5861]  n=148
채점 클래스 ['R1', 'R2', 'R5', 'R6', 'R7']  제외(골드 support 0) ['R3', 'R4', 'R8', 'R9']
$ python -m eval.linkage --result tests/fixtures/premortem_result.json --sources tests/fixtures
근거 연결률 8/8 = 1.000 · 카드 통과 2/2 = 1.000 · 폐기율 없음 · 실패 0건 · 판정 pass
```

(`--sources tests/fixtures/reviews.jsonl`만 주면 `7/8 · 판정 fail`, 한 발췌의 원문이 다른 fixture 파일에 있어서다. 그래서 문서에는 폴더를 준다.)

**verify(RUNNING §9)** — 이 worktree에서(아래 "4" 참고).

**실행하지 않은 명령(문서에 그렇게 표시함)**

- `git clone …`: 네트워크 다운로드라 하지 않았다.
- `python -m playwright install chromium`: 다운로드라 하지 않았다(이미 설치된 환경에서 ui_shots.py는 실행 확인).
- `NEUMANN_LIVE_TESTS=1 python -m pytest`: 실제 OpenAI 호출이라 금지.
- 색인 빌드 `scripts/build_index.py`(E2-L0, main에 없음, bge-m3 로드): "예정, 이 문서에서 실행하지 않음"으로 표시.
- 서버의 기본 포트 8000 예시: 명령은 같고 포트만 8125로 바꿔 실행했다(8000·8010은 쓰지 않음).

**5e14b1c 재확인** — 새로 병합된 것과 테스트 수:

```
$ python -m pytest -q -rs          (main 5e14b1c 사본, NEUMANN_DATA_DIR = 공유 데이터 폴더)
SKIPPED [1] tests\e2\test_e2_build.py:131: 실제 bge-m3 검사는 NEUMANN_E2_MODEL_TESTS=1
SKIPPED [1] tests\e3\test_checklist_live.py:73: 실제 API 테스트는 NEUMANN_LIVE_TESTS=1과 OPENAI_API_KEY가 있을 때만
SKIPPED [1] tests\e3\test_checklist_live.py:113: 실제 API 테스트는 NEUMANN_LIVE_TESTS=1과 OPENAI_API_KEY가 있을 때만
SKIPPED [1] tests\e3\test_review.py:369: could not import 'neumann.llm': No module named 'neumann.llm'
SKIPPED [1] tests\e3\test_review_live.py:68: NEUMANN_LIVE_TESTS=1일 때만 실제 API를 부른다
SKIPPED [1] tests\e4\test_templates_ui.py:233: NEUMANN_UI_TESTS=1일 때만(브라우저·서버 필요)
456 passed, 6 skipped in 21.95s
$ python scripts/build_index.py --source fixtures --out <SP>/idx --no-embed
[build_index] 입력 fixtures: 논문 6편, 심사평 12건 (0.0s)
[build_index] 강등: --no-embed: 임베딩 없이 빌드
[build_index] 문장 44개 (0.0s), 태그 18개 (0.0s), BM25 0.0s, 임베딩 0.0s
[build_index] 오프셋 대조(메모리) 44/44, (디스크) 44/44
[build_index] 태그 종류 7: {'R1': 1, 'R2': 7, 'R3': 4, 'R4': 1, 'R5': 2, 'R6': 1, 'R7': 2}, 극성 {'negative': 18}
$ python scripts/build_index_check.py --help     (usage 출력 확인, 실행은 bge-m3 로드라 하지 않음)
$ python -m pytest tests/e4 -q -k mcp
11 passed, 105 deselected in 4.25s
$ python -m pytest tests/e2 -q
41 passed, 1 skipped in 3.10s
$ uvicorn … --port 8125  (5e14b1c)
unavailable {'pipeline': False, 'INPUT': False, 'EVIDENCE': False, 'RISK': False, 'REVIEW': True, 'ACTION': True, 'TRACE': False, 'llm': False, 'models': True, 'config': True}
{'neumann.api.export': 'ok', 'neumann.api.upload': 'missing', 'neumann.api.precomputed': 'missing', 'neumann.api.templates': 'ok', 'neumann.api.meta': 'ok'}
openapi paths: ['POST /premortem/package', 'GET /templates', 'GET /templates/{item_id}', 'GET /api', 'GET /taxonomy', 'GET /config/weights', 'GET /health', 'POST /premortem', 'POST /premortem/view']
GET /templates HTTP 200 → keys ['version', 'scope', 'required_sections', 'templates', 'examples']
  templates ['materials-gnn', 'protein-molecule', 'physics-pde-climate', 'neuro-fmri', 'medical-imaging']
  examples [('example-battery', 'example'), ('example-fmri', 'example'), ('example-medimaging', 'example')]
GET /templates/materials-gnn HTTP 200 → ['chars', 'domain', 'filename', 'id', 'kind', 'name', 'sections', 'sha256', 'source', 'summary', 'text']
GET /templates/nope 404
GET /api HTTP 200 → summary_ko "ICLR 2024 · ICLR 2025 · 논문 1,128편 · 심사평 5,366건 · 거절 60.3% · 색인 문장 133,769개"
GET /taxonomy HTTP 200 → version v1.0, tier1_count 10, tier2_count 59, severity ['S5', 'S4', 'S3', 'S2', 'S1'], classes 10
GET /config/weights HTTP 200 → {"weights":{"similarity":0.3,"frequency":0.3,"severity":0.3,"confidence":0.1}, … "source":"default","is_default":true,"label":"기본값", … "formula_ko":"위험점수 = 유사도 × 빈도 × 심각도 × 신뢰도", "pipeline":{"module":"neumann.analyze.cards","state":"missing", …}}
POST /premortem/package (plan_text만) HTTP 200 application/zip
8125 free
```

### 2. 사실과 다른 기능을 쓰지 않음: 통과(자체 점검)

- 문서마다 기준 커밋(`5e14b1c`)을 적고, main에 코드가 있는 것만 "있음"으로 썼다. 예정 항목은 과제 ID를 붙이고 "main에 없음/지금 요청하면 404"를 실측으로 확인했다.
- 파이프라인이 없어서 **서버는 계획서를 분석하지 않고 가짜 fixture 샘플을 돌려준다**는 사실을 세 문서 모두 앞쪽에 적었다.
- `/health`의 `ACTION: true`는 체크리스트 모듈이 import될 뿐 서버 응답에 쓰이지 않는다는 것을 API.md에 적었다.
- 숫자는 모두 이번에 다시 잰 값이다(1,128편·4,298·66,737·Macro-F1 0.3308·301 passed 등). DISAPERE 인간 상한 0.725는 외부 참조선이라고 적었다.
- 점검 명령:

```
$ grep -n "기준: `main` 커밋" docs/ARCHITECTURE.md docs/RUNNING.md docs/API.md   (앞 60자)
docs/ARCHITECTURE.md:5:- 기준: `main` 커밋 `5e14b1c` (20
docs/RUNNING.md:3:- 기준: `main` 커밋 `5e14b1c`. 이 문
docs/API.md:3:- 기준: `main` 커밋 `5e14b1c`. 아래 응ë
```

### 3. 루트 README 개정 초안: 재작업에서 `docs/reports/E6-docs_README_draft.md`로 대체(아래 "재작업")

### 4. `python scripts/verify.py` 통과

최종 커밋 직전 이 worktree에서 실행한 출력은 아래 "최종 verify"에 붙였다.

## 바꾼 파일

- `docs/ARCHITECTURE.md`(새로), `docs/RUNNING.md`(새로), `docs/API.md`(새로), `docs/reports/E6-docs.md`(이 보고서)
- 다른 파일은 고치지 않았다.

## 결정 (스펙이 모호해서 고른 것)

1. **"현재 main"을 무엇으로 볼지**: main이 작업 중 네 번 바뀌었다. 문서에 기준 커밋을 적고, 마지막으로 확인한 `5e14b1c`에 맞췄다. 그 뒤 병합분(E3-L0 파이프라인 등)은 PM이 "예정" 표시와 API 예시를 고치거나 후속 과제로 돌린다. "있음(모듈만)" 표기를 새로 두었다: 모듈은 main에 있지만 파이프라인이 없어 서버 응답에 쓰이지 않는 것(예상 심사평·게이트·체크리스트·2차 검증).
2. **명령 확인을 main 사본에서**: worktree는 `481e11c` 기준이고 merge 금지라, `git archive`로 main 사본을 스크래치에 풀어 실행했다. 산출은 스크래치로 보내 공유 데이터 폴더를 건드리지 않았다.
3. **설치 방법은 uv만 적음**: 개발 venv에 pip이 없고(uv로 만든 venv), `pyproject.toml`에 빌드 설정이 없어 `pip install -e .`는 확인할 수 없었다. 확인할 수 있는 `uv pip install -r pyproject.toml --extra dev`만 적었다.
4. **예정 엔드포인트의 모양**: 브랜치 코드는 병합 때 바뀔 수 있어, API.md에는 과제 지시문의 요약만 적고 "병합 뒤 `/openapi.json`과 보고서를 본다"고 했다. MCP 도구 이름은 E4-L2b 지시문과 브랜치 머리말이 같아 그대로 적었다.
5. **eLife·Europe PMC 라이선스**: main에 코드가 없어 "소스별로 확인"으로만 적었다(기획 조사값을 사실처럼 옮기지 않음).
6. **로컬 경로**: 사용자 폴더 경로를 문서에 쓰지 않고 `<공개자료 폴더>`·`<데이터 폴더>`로 적었다.

## 못 한 것

- 새 venv에 실제 설치(네트워크·다운로드 필요)와 `git clone`: dry-run으로만 확인.
- 실데이터 색인 빌드(`scripts/build_index.py` 기본)와 `build_index_check.py`: bge-m3 로드라 실행하지 않음(fixture `--no-embed`로만 확인, 문서에 표시).
- MCP 서버 단독 실행: stdio라 테스트(`-k mcp`)로만 확인.
- 파이프라인·업로드·사전 계산본: main에 없어 실행하지 않음(예정으로 표시).
- 루트 `README.md` 수정: PM 소유라 초안만 아래에 둠.
- **5e14b1c 이후 병합분 미반영**: 마감 시점 main은 `bbc688a`이고, 그사이 E6-L2a(사전 계산본 API `/premortem/precomputed`·`scripts/precompute_demo.py`), E5-L3a(리포트 카드 생성기), E6-L3b(시연 녹화 스크립트)가 병합됐다. 문서는 기준 커밋(`5e14b1c`)을 밝히고 이 셋을 "예정"으로 적고 있다. main이 계속 움직여 따라가기를 멈췄다. 병합 때 PM이 ARCHITECTURE §1·§4, API 목록·예정 절, RUNNING §8의 표시를 "있음"으로 바꾸거나 후속 과제로 돌린다.

## 다음 과제에 넘길 것

1. **`/premortem` 샘플 응답이 `/premortem/package`에서 422**(E4, PM 판단): 샘플에 붙는 `sample` 키와 `stages[0]`의 `status: "unavailable"`·`degraded`·`details`가 `PremortemResult` 계약(`extra="forbid"`, `StageState`는 ok·degraded·skipped·error)에 없다. 화면에서 샘플 결과로 "내보내기"를 누르면 실패할 수 있다. 파이프라인이 붙으면 사라지는 문제지만, 파이프라인 오류 시 샘플이 아니라 500이므로 영향은 "파이프라인 미연결" 상태에 한정된다. 고칠 곳 후보: `api/main.py`의 `_sample_result`가 `StageStatus` 모양(`status: "degraded"`, `impl: "fallback:sample"`)을 쓰고 `sample` 표시는 `notices`·`manifest`로 옮기거나, `export.py`가 알려진 샘플 키를 벗겨 받기.
2. `/docs`(Swagger UI)가 외부 CDN을 부른다. 오프라인 데모에서 누가 `/docs`를 열면 빈 화면이다. 필요하면 `FastAPI(docs_url=None)` 또는 로컬 자산으로.
3. 문서 갱신 시점: E3-L0 병합(v0) 때 ARCHITECTURE §1·§2·§3·§5, RUNNING §6, API "지금 main에서…" 절을 고쳐야 한다(샘플 → 실제 분석). `/health` 예시도 바뀐다.
4. `NEUMANN_API_HOST`·`NEUMANN_API_PORT` 설정 칸은 지금 서버 실행에 쓰이지 않는다(uvicorn 명령줄이 정함). 쓰지 않을 거면 `.env.example` 설명을 맞추고, 쓸 거면 실행 진입점을 둔다.
5. **`/config/weights`와 결정 기록 불일치**(E4-L1d/PM): 결정 기록 19:15는 "곱, 가중치 없음"을 보이게 한다고 했으나 `5e14b1c` 응답은 기본 가중치 0.3/0.3/0.3/0.1을 `weights`로 돌려준다(`formula_ko`는 곱). API.md에 주의로 적었다.
6. **`/premortem/package`의 `plan_text`만 받는 경로**: 결정 기록 19:20은 없앤다고 했으나 `5e14b1c`에서는 아직 200을 돌려준다. 고치면 API.md의 `plan_text` 행을 바꾼다.
7. **`/health`의 EVIDENCE 단계 모듈 이름**: `STAGE_MODULES["EVIDENCE"]`가 `neumann.index.hybrid`를 보는데 색인은 `neumann.index.search`로 들어왔다. 파이프라인이 붙어도 `neumann.index.hybrid`가 없으면 EVIDENCE가 계속 `false`로 보인다(PM 소유 `main.py`).

## README 개정 초안 (폐기)

첫 제출의 초안은 파이프라인 연결 전 상태를 적어 사실이 아니게 됐다. 재작업에서 PM 배정 범위로 새로 써서 `docs/reports/E6-docs_README_draft.md`에 두었다.

## 재작업 (검증 PASS-조건부 → 조건 해소)

검증 보고서 `docs/reports/E6-docs.verify.md`의 결함은 하나였다: 문서 기준 커밋(`5e14b1c`)이 낡아, 병합 시점 main(v0, 파이프라인 연결)에서 "파이프라인 없음·샘플만"·"OpenAI를 부르지 않는다" 같은 서술이 거짓이 됐다.

### 한 것

1. `git merge main` 두 번(`304e91e`, 그 뒤 `588da63`). 충돌 없음. 문서 기준은 "병합 직전 main"으로 적고 작성 때 확인한 커밋(`588da63`)을 밝혔다.
2. 검증 보고서 §4 #1~#12, §6 조건 1~3 반영:

| 검증 항목 | 고친 것 | 커밋 |
|---|---|---|
| §4 #1, §6 ① "파이프라인 없음·샘플" | 세 문서에서 삭제. 파이프라인 6단계 이름, `pipeline.state: connected`, `pipeline_version: neumann-e3-l0`, astra 주력·비상 규칙·mock 표시로 다시 씀. 샘플은 "모듈이 없을 때만(지금 main에서는 일어나지 않음)"으로 내림 | 857582b, 1325507, 156d2cb |
| §4 #2, §6 ② RUNNING "OpenAI를 부르지 않는다" | 삭제. RUNNING·API 머리에 비용 경고: 기본 provider `openai`라 분석 요청·파이프라인 명령·`plan_text` 패키지가 OpenAI를 부른다, 시험은 `NEUMANN_LLM_PROVIDER=mock` | 1325507, 156d2cb |
| §4 #3, §6 ⑤ API `plan_text` 설명 | "서버가 파이프라인을 돌린다(provider가 openai면 OpenAI 호출)"로 교체. SEC-1 언급은 뺐다(검증 권고) | 156d2cb |
| §4 #4 사전 계산본 | "있음"으로. API에 목록·단건·404·헤더·표시 문구, RUNNING §5-3 사용법 | 857582b, 1325507, 156d2cb |
| §4 #5·#6 리포트 카드·백테스트 | "있음"으로. RUNNING §8에 `backtest_sample`·`report_card` 사용법, 나머지 단계는 호출 비용 때문에 실행 안 함을 명시 | 857582b, 1325507 |
| §4 #7 적합성·PII | "있음(모듈만)"(파이프라인이 아직 부르지 않음, `pipeline.py`에 호출 0건 확인) | 857582b |
| §4 #8 규모 확대 | 확대 코퍼스·확대 색인(`index_l3`) "있음", 기본 색인은 1,128편이고 `NEUMANN_INDEX_DIR`로 전환 | 857582b, c1a1895 |
| §4 #9 정적 배포·녹화 | 모듈 지도와 RUNNING §5-4에 추가 | 857582b, 1325507 |
| §4 #10, §6 ④ `/health` 예시 | 실측으로 교체(단계 모듈 실제 이름, `llm: ok`, `routers.precomputed: ok`) | 156d2cb |
| §4 #11, §6 ④ `/config/weights` 예시 | 실측으로 교체(`formula: product`, `weights: null`, `display: "곱 · 가중치 없음"`, `pipeline.state: ok`). 주의 문단 삭제 | 156d2cb |
| §4 #12 샘플 → package 422 | 알려진 제약 삭제. 실측: `/premortem` 응답(mock)을 그대로 보내면 200 | 156d2cb |
| §6 조건 2 응답 예시 | `/premortem`·`/view`를 실제 파이프라인 응답(mock provider, 임베딩 없음)으로 다시 받아 쓰고 mock·어휘 검색 강등임을 문서 머리와 예시에 밝힘 | 156d2cb |
| 기타: 테스트 수, `tests/e6`·`e2e`, 환경변수 | `908 passed, 22 skipped`(588da63 병합 상태), 모듈 지도에 e6·e2e, 환경변수 표에 검색·임베딩·추론 강도·단계 시간 키 | 1325507, c1a1895 |

3. 병합 뒤 새로 들어온 것(E2-L3 확대 색인, E5-L0e2e 라이브 E2E, E5-L1b DISAPERE 추출 채점)도 반영했다(c1a1895). 마지막으로 `2c37557`을 병합해 E4-S06(입력 화면의 OpenAI 전송·본문 미저장 고지)을 ARCHITECTURE 표와 README 초안 보안 절에 한 줄씩 더하고 문서 기준 커밋을 `2c37557`로 올렸다(그 사이 변경은 `webui/index.html`과 테스트뿐이라 API 실측은 그대로 유효).
4. 기획 키트의 폐기된 문서 이름을 문서·보고서에서 모두 뺐다(이 보고서 머리 한 곳).
5. PM 추가 배정: 루트 README v0 개정 초안을 `docs/reports/E6-docs_README_draft.md`로 커밋(f65281d, 267a50c). 숫자는 저장소 보고서·결정 기록 값만 쓰고 파일별 출처 표를 붙였다. 목표 미달(Macro-F1 0.4864 < 0.70)을 먼저 적고, PM 정정대로 "Macro에서만 기준선 초과·Micro 구간 겹침·단일 실행"을 밝혔다.

### 재측정 (실제 OpenAI 호출 없음)

서버: 병합한 worktree(main `304e91e` 상태)에서 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_EMBED_MODEL` 없이(어휘 검색), `NEUMANN_DATA_DIR` = 공유 데이터 폴더, 포트 8125. 끝나고 `8125 free` 확인. `304e91e..588da63` 사이 `src/neumann/api`·`pipeline.py`·`llm.py`·`analyze`·`index` 변경은 주석 2줄(`fitness.py`·`pii.py`)뿐이라 응답은 그대로다.

```
$ GET /health
{"status": "ok", "version": "0.0.1", "pipeline": {"state": "connected", "reason": "", "mode": "pipeline", "label": ""}}
INPUT queries ok · EVIDENCE index.search·index.store·analyze.extract ok · RISK cards ok · REVIEW review·gate ok · ACTION checklist·validate ok · TRACE api.export ok · llm ok
routers {'neumann.api.export': 'ok', 'neumann.api.upload': 'missing', 'neumann.api.precomputed': 'ok', 'neumann.api.templates': 'ok', 'neumann.api.meta': 'ok'}
$ GET /openapi.json paths
['POST /premortem/package', 'GET /premortem/precomputed', 'GET /premortem/precomputed/{plan_id}', 'GET /templates', 'GET /templates/{item_id}', 'GET /api', 'GET /taxonomy', 'GET /config/weights', 'GET /health', 'POST /premortem', 'POST /premortem/view']
$ POST /premortem (tests/fixtures/plans/plan.md, mock)
HTTP 200 1.763648s
{"status": "degraded", "pipeline_version": "neumann-e3-l0", "plan_id": "3d35460def76…"}
manifest llm_provider mock · llm_model mock-deterministic-v1 · backend neumann.index.search:search · prompt_versions query_axes.v1, extract_issues.v1, synthesize_cards.v3 · total_s 1.741
stages plan_normalize ok · query_axes ok(mock) · search degraded(백엔드 lexical_only, 임베딩 없이 어휘 검색) · extract_issues ok(폐기율 0.0%) · synthesize_cards ok(mock) · verify_evidence ok(근거 22/22 원문 일치)
notices ["[search] degraded: …", "mock provider(테스트용) 결과 — 실제 astra 분석이 아니다"]
similar_works 10 evidence 22 cards 5 generators ['mock']
$ POST /premortem/view (plan.md, mock)
{"source": "pipeline", "label": "일부 단계 강등", "degraded": true, "generators": {"mock": 5}, "contract_ok": true, "dropped": {}, "pipeline": "connected", "result_status": "degraded", "stages_not_ok": [search degraded]}
$ POST /premortem (negative_recipe.md, mock)
degraded cards 0 no_card_reason "입력이 연구계획서가 아니다(mock 판단: mock: 연구 어휘 개수로 판정); 유사 연구 검색 상위 점수 0.031"
$ GET /premortem/precomputed
HTTP 200 · label "사전 계산본" · source "fixture" · items 3 · 항목 label "사전 계산본(2026-09-30 18:55 KST)"
$ GET /premortem/precomputed/plan_elife_neuro
HTTP 200 · x-neumann-precomputed: 1 · notices[0] "사전 계산본(2026-09-30 18:55 KST) — 실시간 분석이 아니라 미리 계산해 둔 결과다 · 분석 파이프라인 미연결로 fixture 결과로 대체된 사전 계산본"
$ GET /premortem/precomputed/nope
{"detail":{"code":"not_found","message":"해당 계획서의 사전 계산본이 없다"}} HTTP 404
$ GET /config/weights
{"formula": "product", "formula_ko": "위험점수 = 유사도 × 빈도 × 심각도 × 신뢰도 (곱, 가중치 없음)", "weighted": false, "weights": null, "display": "곱 · 가중치 없음", … "pipeline": {"module": "neumann.analyze.cards", "state": "ok", "formula": "product_v1: …", "matches": true}}
$ POST /premortem/package (plan_text만, mock)
HTTP 200 application/zip · 9파일 · status degraded · cards_by_generator {'astra': 0, 'rule': 0, 'mock': 5} · pipeline_version neumann-e3-l0
$ POST /premortem/package (/premortem 응답 그대로, mock)
HTTP 200 application/zip
```

공유 데이터 폴더의 사전 계산본 3건은 파이프라인 병합 전에 만든 fixture 대체본이라 응답에 그렇게 표시됐다(데이터 상태이지 코드 결함이 아니다). API.md에 그대로 적었다.

명령(RUNNING):

```
$ NEUMANN_LLM_PROVIDER=mock python scripts/precompute_demo.py --source pipeline --out <SP>/pre
분석: neumann.pipeline:run_premortem (연결됨)
  plan: pipeline · status degraded · 카드 5(mock 5) · 1.28s
  plan_elife_neuro: pipeline · status degraded · 카드 4(mock 4) · 0.13s
  plan_medimaging: pipeline · status degraded · 카드 4(mock 4) · 0.12s
재생 확인: 3/3
$ python scripts/build_static_site.py --precomputed <SP>/pre --out <SP>/site
검사: 파일 35개(6.1MB) · 텍스트 21개 · 리소스 참조 22개 · 데모 3건 · 템플릿·예시 8건
검사 통과: 필수 파일·데모 JSON, 비밀값 0, 환경변수 이름 0, 로컬 경로 0, 외부·루트 절대 참조 0
$ python -m neumann.pipeline tests/fixtures/plans/plan.md --provider mock
… "total_s": 1.371
$ python -m eval.backtest_sample --out <SP>/bt
… 30 reject researcharcade_hf:otXB6odSG8 physics_pde_climate   (30편 출력)
$ python -m eval.report_card --help · scripts/record_demo.py --help · scripts/build_static_site.py --help · python -m neumann.pipeline --help
usage 출력 확인
$ python -m pytest -q -rs     (588da63 병합 상태, NEUMANN_RAW_DIR·NEUMANN_DATA_DIR 지정, mock)
908 passed, 22 skipped in 67.48s
  건너뜀: 라이브 E2E 5(NEUMANN_LIVE_TESTS), 실제 API 테스트(checklist 2·fitness 4·live_astra 4·review 1·baseline_llm 1·disapere_extract 1), UI 1(NEUMANN_UI_TESTS), 실색인 회귀 1(NEUMANN_REAL_DATA_TESTS) 등
```

검색 점검(세 문서): "파이프라인이 없", "OpenAI를 부르지 않", "샘플만", 옛 기준 커밋(`5e14b1c`·`ed1d1a0`·`82146f9`)을 `grep`으로 찾아 0건(아래 "최종 verify" 앞 출력).

### 실행하지 않은 것 (이번에도)

- 실제 OpenAI 호출(서버 openai provider, `NEUMANN_LIVE_TESTS=1`, 라이브 E2E, `eval.baseline_llm`·`disapere_extract`·`backtest_run_neumann`), bge-m3 로드(실데이터 색인 빌드·`build_index_l3.py`·`build_index_check.py`), 녹화(`record_demo.py`), 다운로드(`git clone`, `collect_l3_shards.py`, `playwright install`).

### 남은 것 (PM)

- 이 문서를 병합한 뒤에도 main이 움직이면 기준 커밋을 확인한다. 특히 E3-L1w(적합성·예상 심사평·체크리스트를 파이프라인에 연결)가 들어오면 "있음(모듈만)" 표기(ARCHITECTURE §1·§2·§4·§5, API `/health` 설명)를 "있음"으로 바꾼다. E4-L1a(업로드)가 들어오면 API 목록·예정 절을 고친다.
- 첫 제출 "다음 과제에 넘길 것" 1(샘플 → package 422)·5(가중치)·7(EVIDENCE 모듈 이름)은 main에서 해결됐다. 6(`plan_text` 패키지 경로 제거, 결정 19:20)은 588da63에서도 아직 200이다. 2(`/docs` CDN)·4(`NEUMANN_API_HOST/PORT` 미사용)는 그대로다.

## 최종 verify

이 worktree(`task/E6-docs`, 보고서 스테이징 상태)에서 실행. worktree는 `481e11c` 기준이라 테스트 수가 main 사본보다 적다.

```
$ python scripts/verify.py
183 passed, 2 skipped in 1.73s
보안: 파일 126개
계약: 2개
테스트: 통과
verify 통과
```
