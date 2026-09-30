# E6-docs 보고서: ARCHITECTURE·RUNNING·API 문서, README 개정 초안

- 브랜치: `task/E6-docs` · 빌더: claude-opus-5.5 · 2026-09-30
- 스펙: `docs/tasks/E6-docs.md`. 읽은 것: `AGENTS.md`, `docs/tasks/_COMMON.md`, 계획서 §0·§2·§4.0·§4(E0~E6), main의 `src/`·`eval/`·`scripts/`·`tests/`, `docs/tasks/`, `docs/reports/`, 진행 중 브랜치의 변경 파일 목록과 스크립트 머리말, 공개자료 `MANIFEST.md`(라이선스)
- 기획서의 `01_구조_뼈대`·`06_교훈_함정`은 열지 않았고 옮기지 않았다. 옛 `neumann/` 폴더는 열지 않았다.

## 무엇을 했나

| 파일 | 내용 |
|---|---|
| `docs/ARCHITECTURE.md` | 현재 상태 표(있음·예정), 6단계(INPUT→EVIDENCE→RISK→REVIEW→ACTION→TRACE)별 하는 일·산출·상태, 현재 요청 흐름(파이프라인 미연결 → 샘플 표시), 모듈 지도, astra 주력·비상 규칙 경로(설계와 main 구현 상태를 나눠 적음), 근거 정직성 장치 12종, 데이터 출처와 라이선스, 계약 |
| `docs/RUNNING.md` | 설치(uv venv), 환경변수(키는 이름만), 공개자료 폴더 구조, 코퍼스 조립, Retraction Watch 빌드·조회, 색인 빌드(예정), 서버 실행, 테스트·화면 스크린샷, 평가 명령 4종, verify·훅, 비밀값 규칙 |
| `docs/API.md` | 엔드포인트 표(있음 6 + 예정 6), 지금 main의 샘플 동작, `/health`·`/premortem`·`/premortem/view`·`/premortem/package`의 본문·제약·오류 코드·실측 응답, 알려진 제약, 예정 엔드포인트(과제 지시문 기준) |

문서의 기준 커밋은 **main `82146f9`**(2026-09-30 19:02)다. 작업을 `ed1d1a0` 기준으로 시작했는데 도중에 E1-L2(Retraction Watch)와 E3-L1b(체크리스트·2차 의미검증)가 병합돼, 그 둘을 "있음"으로 고치고 명령과 응답을 `82146f9`에서 다시 확인했다.

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

서버 종료 확인(3회 모두):

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

### 2. 사실과 다른 기능을 쓰지 않음: 통과(자체 점검)

- 문서마다 기준 커밋(`82146f9`)을 적고, main에 코드가 있는 것만 "있음"으로 썼다. 예정 항목은 과제 ID를 붙이고 "main에 없음/지금 요청하면 404"를 실측으로 확인했다.
- 파이프라인이 없어서 **서버는 계획서를 분석하지 않고 가짜 fixture 샘플을 돌려준다**는 사실을 세 문서 모두 앞쪽에 적었다.
- `/health`의 `ACTION: true`는 체크리스트 모듈이 import될 뿐 서버 응답에 쓰이지 않는다는 것을 API.md에 적었다.
- 숫자는 모두 이번에 다시 잰 값이다(1,128편·4,298·66,737·Macro-F1 0.3308·301 passed 등). DISAPERE 인간 상한 0.725는 외부 참조선이라고 적었다.
- 점검 명령:

```
$ grep -n "ed1d1a0" docs/ARCHITECTURE.md docs/RUNNING.md docs/API.md     (옛 기준 잔존 없음)
(출력 없음)
```

### 3. 루트 README 개정 초안: 아래 "README 개정 초안"

### 4. `python scripts/verify.py` 통과

최종 커밋 직전 이 worktree에서 실행한 출력은 아래 "최종 verify"에 붙였다.

## 바꾼 파일

- `docs/ARCHITECTURE.md`(새로), `docs/RUNNING.md`(새로), `docs/API.md`(새로), `docs/reports/E6-docs.md`(이 보고서)
- 다른 파일은 고치지 않았다.

## 결정 (스펙이 모호해서 고른 것)

1. **"현재 main"을 무엇으로 볼지**: main이 작업 중 세 번 바뀌었다(`6067212` → `ed1d1a0` → `82146f9`). 문서에 기준 커밋을 적고, 마지막으로 확인한 `82146f9`에 맞췄다. 이후 병합분(E2-L0 색인, E3-L0 파이프라인 등)이 들어오면 "예정" 표시와 API 예시를 PM이 고치거나 후속 과제로 돌린다.
2. **명령 확인을 main 사본에서**: worktree는 `481e11c` 기준이고 merge 금지라, `git archive`로 main 사본을 스크래치에 풀어 실행했다. 산출은 스크래치로 보내 공유 데이터 폴더를 건드리지 않았다.
3. **설치 방법은 uv만 적음**: 개발 venv에 pip이 없고(uv로 만든 venv), `pyproject.toml`에 빌드 설정이 없어 `pip install -e .`는 확인할 수 없었다. 확인할 수 있는 `uv pip install -r pyproject.toml --extra dev`만 적었다.
4. **예정 엔드포인트의 모양**: 브랜치 코드는 병합 때 바뀔 수 있어, API.md에는 과제 지시문의 요약만 적고 "병합 뒤 `/openapi.json`과 보고서를 본다"고 했다. MCP 도구 이름은 E4-L2b 지시문과 브랜치 머리말이 같아 그대로 적었다.
5. **eLife·Europe PMC 라이선스**: main에 코드가 없어 "소스별로 확인"으로만 적었다(기획 조사값을 사실처럼 옮기지 않음).
6. **로컬 경로**: 사용자 폴더 경로를 문서에 쓰지 않고 `<공개자료 폴더>`·`<데이터 폴더>`로 적었다.

## 못 한 것

- 새 venv에 실제 설치(네트워크·다운로드 필요)와 `git clone`: dry-run으로만 확인.
- 색인 빌드·파이프라인·예정 엔드포인트의 명령: main에 없어 실행하지 않음(예정으로 표시).
- 루트 `README.md` 수정: PM 소유라 초안만 아래에 둠.

## 다음 과제에 넘길 것

1. **`/premortem` 샘플 응답이 `/premortem/package`에서 422**(E4, PM 판단): 샘플에 붙는 `sample` 키와 `stages[0]`의 `status: "unavailable"`·`degraded`·`details`가 `PremortemResult` 계약(`extra="forbid"`, `StageState`는 ok·degraded·skipped·error)에 없다. 화면에서 샘플 결과로 "내보내기"를 누르면 실패할 수 있다. 파이프라인이 붙으면 사라지는 문제지만, 파이프라인 오류 시 샘플이 아니라 500이므로 영향은 "파이프라인 미연결" 상태에 한정된다. 고칠 곳 후보: `api/main.py`의 `_sample_result`가 `StageStatus` 모양(`status: "degraded"`, `impl: "fallback:sample"`)을 쓰고 `sample` 표시는 `notices`·`manifest`로 옮기거나, `export.py`가 알려진 샘플 키를 벗겨 받기.
2. `/docs`(Swagger UI)가 외부 CDN을 부른다. 오프라인 데모에서 누가 `/docs`를 열면 빈 화면이다. 필요하면 `FastAPI(docs_url=None)` 또는 로컬 자산으로.
3. 문서 갱신 시점: E2-L0·E3-L0 병합(v0) 때 ARCHITECTURE §1·§2·§5, RUNNING §5·§6, API "지금 main에서…" 절을 고쳐야 한다(샘플 → 실제 분석).
4. `NEUMANN_API_HOST`·`NEUMANN_API_PORT` 설정 칸은 지금 서버 실행에 쓰이지 않는다(uvicorn 명령줄이 정함). 쓰지 않을 거면 `.env.example` 설명을 맞추고, 쓸 거면 실행 진입점을 둔다.

## README 개정 초안

루트 `README.md`를 아래로 바꾸자고 제안한다(PM 소유라 고치지 않았다). 기준은 main `82146f9`이고, v0 병합 때 "상태" 표와 첫 문단의 "샘플" 문장을 고친다.

````markdown
# Neumann

연구계획서를 넣으면, 비슷한 연구가 실제로 받은 **심사평·저자 답변·결정·정정/철회 기록**에서 위험을 찾아 근거가 연결된 위험카드로 돌려주는 서비스다.

- 분석 대상은 논문 본문이 아니라 평가 과정 기록이다.
- 개입 시점은 투고 직전이 아니라 연구 착수 전이다.
- 카드마다 실제 심사평 문장을 원문 오프셋 그대로 인용하고 원문 링크를 단다. 근거 없는 문장은 내보내지 않는다.
- 생성 방식(LLM `gpt-6-astra` / 비상 규칙 / 테스트용 mock)과 강등 여부를 결과와 화면에 그대로 표시한다.

2026 NAIS AI 해커톤 본선(2026-09-30 17:00 ~ 10-01 12:00)에서 처음부터 만들고 있다. 커밋 이력이 곧 현장 개발 기록이다.

## 지금 상태

| 영역 | 상태 |
|---|---|
| 데이터 계약·설정·검증 러너 | 있음 |
| 코퍼스: OpenReview 공개 심사 기록(ResearchArcade 경유) AI for Science 1,128편, 심사평 4,298건 | 있음 |
| 정정·철회 사후 상태(Retraction Watch) | 있음(소스) |
| API 서버·화면·내보내기 ZIP | 있음 |
| 평가: 근거 연결 검사, DISAPERE 골드 148건 Macro-F1(빈도 기준선 0.3308) | 있음 |
| 예방 체크리스트·2차 의미검증 | 있음(모듈, 파이프라인 연결 전) |
| 검색 색인, astra 분석 파이프라인, 예상 심사평 | 진행 중 |

아직 분석 파이프라인이 main에 없다. 지금 서버는 입력한 계획서를 분석하지 않고 가짜 샘플을 "분석 파이프라인 미연결(샘플 데이터)" 표시와 함께 돌려준다.

| 단계 | 내용 | 태그 |
|---|---|---|
| L0 | 계획서 입력 → 유사 연구 + 위험카드(실제 심사평 인용) | `v0` |
| L1 | 위험점수, 예상 심사평, 근거 열람 패널 | `v1` |
| L2 | 체크리스트·결정 로그, 백테스트, 내보내기 | `v2` |
| L3 | 디자인, 규모 확대, 리포트 카드 | `v3` |

## 시작하기

Python 3.12와 [uv](https://docs.astral.sh/uv/). 자세한 것은 [docs/RUNNING.md](docs/RUNNING.md).

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -r pyproject.toml --extra dev
git config core.hooksPath .githooks       # 비밀값 검사 훅(클론마다 한 번)
cp .env.example .env                      # 값을 채운다. .env는 커밋되지 않는다. 키는 환경변수 OPENAI_API_KEY로
python scripts/verify.py                  # 보안 + 계약 + 테스트
python -m uvicorn neumann.api.main:app --host 127.0.0.1 --port 8000   # http://127.0.0.1:8000/
```

## 문서

| 문서 | 내용 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 6단계, 모듈 지도, astra 주력·비상 규칙 경로, 근거 정직성 장치, 데이터 출처와 라이선스 |
| [docs/RUNNING.md](docs/RUNNING.md) | 설치, 환경변수, 공개자료 경로, 코퍼스·색인, 서버, 테스트, 평가, verify |
| [docs/API.md](docs/API.md) | 엔드포인트와 예시 |
| `docs/decisions.md` | 결정 기록 |
| `docs/HANDOFF.md` | 작업 인계 문서 |
| `docs/tasks/`, `docs/reports/` | 과제 지시문과 과제별 보고서(측정값·검증) |

## 보안

공개 저장소다. 비밀값은 환경변수(또는 커밋되지 않는 `.env`)에만 두고 코드는 환경변수로만 읽는다.

- `.gitignore`가 `.env`, 데이터, 모델 가중치, 색인, 캐시, 로그를 막는다.
- `scripts/verify.py`가 키 형태 문자열, `.env`·환경변수에 든 실제 키 값, 금지 파일, 5MB 넘는 파일을 찾는다. 찾은 값은 출력하지 않는다.
- git 훅: `pre-commit`(스테이징 내용), `commit-msg`(메시지), `pre-push`(추적 파일 전체와 커밋 메시지).
- GitHub 시크릿 스캐닝과 푸시 보호가 켜져 있다.

## 구조

| 경로 | 내용 |
|---|---|
| `AGENTS.md` | 에이전트 규칙 원본(Claude·Codex 공통). `CLAUDE.md`가 가져온다 |
| `contracts/` | 데이터 계약 JSON Schema(API 응답, 화면 데이터) |
| `src/neumann/` | 제품 코드: `models.py`(계약), `config.py`, `sources/`(수집), `index/`(색인), `analyze/`(분석), `api/`(서버·내보내기), `webui/`(화면) |
| `eval/` | 평가: 근거 연결 검사, DISAPERE 골드, Macro-F1, 기준선 |
| `scripts/` | 검증 러너, 수집·색인 스크립트 |
| `tests/` | 테스트와 공용 가짜 데이터(`tests/fixtures/`) |

## 데이터 출처와 라이선스

데이터 원본과 가공본은 저장소에 넣지 않는다.

| 자료 | 라이선스 |
|---|---|
| OpenReview 공개 심사 기록(공개 미러 ResearchArcade 경유) | 선언 없음. 출처를 표기하고 원본은 재배포하지 않는다 |
| DISAPERE(사람이 붙인 심사평 라벨) | CC BY-NC 4.0 |
| Crossref–Retraction Watch(정정·철회) | 라이선스 파일 없음(CC0 아님). 출처 표기 |
| 임베딩 모델 BAAI/bge-m3 | MIT |
| 화면 폰트(Pretendard, Jost, IBM Plex Mono, Instrument Serif, Mr Dafoe) | SIL OFL 1.1 |
````

## 최종 verify

(아래에 붙임)
