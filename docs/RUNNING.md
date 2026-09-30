# 실행 방법

- 기준: 이 문서를 병합하기 직전의 `main`(작성 때 확인한 커밋 `848bd50`). 이 문서의 명령은 `304e91e`·`588da63`에서 Windows 11 + Git Bash + Python 3.12.10으로 실행해 확인했다(결과는 `docs/reports/E6-docs.md`). 실행하지 않은 명령은 그렇다고 적었다.
- 구조와 상태는 [ARCHITECTURE.md](ARCHITECTURE.md), 엔드포인트는 [API.md](API.md).

> **LLM provider와 비용:** 기본 provider는 `mock`이다(결정적 가짜 응답, 비용 없음). mock 결과는 분석이 아니며 결과에 그렇게 표시된다. `NEUMANN_LLM_PROVIDER=openai`로 켜면 서버의 분석 요청(`/premortem`, `/premortem/view`, `plan_text`만 보낸 `/premortem/package`)과 파이프라인 명령이 요청마다 OpenAI API(기본 모델 `gpt-6.1-sol`)를 부르고 비용이 든다. 실서비스·대표 승인 확인에서만 켠다(`AGENTS.md`).

## 1. 설치

필요한 것: Python 3.12, git, [uv](https://docs.astral.sh/uv/). 의존성 목록은 `pyproject.toml`에 있다(빌드 설정 없이 의존성만 적었다).

```bash
git clone https://github.com/sbrpgr/project_neumann.git
cd project_neumann
uv venv --python 3.12 .venv
uv pip install --python .venv -r pyproject.toml --extra dev
git config core.hooksPath .githooks        # 비밀값 검사 훅 켜기(클론마다 한 번)
```

- 이후 `python`은 이 venv의 파이썬이다(Windows: `.venv/Scripts/python.exe`, 그 밖: `.venv/bin/python`).
- 새 venv에 설치할 때는 네트워크가 필요하다. `torch`는 크고, GPU용 빌드가 필요하면 PyTorch 안내대로 인덱스를 따로 지정한다. 이 문서를 쓸 때는 이미 갖춰진 개발 venv에 같은 명령을 `--dry-run --offline`으로 돌려 의존성이 모두 충족됨(`Would make no changes`)만 확인했다(`git clone`도 하지 않았다).
- `torch`·`sentence-transformers`는 색인 빌드와 임베딩 검색(bge-m3)에 쓴다.
- 화면 스크린샷·녹화 스크립트를 쓸 때만 Playwright 브라우저가 필요하다: `python -m playwright install chromium`(실행하지 않음).

## 2. 환경변수

설정 로더(`src/neumann/config.py`)는 **환경변수 > 저장소 루트 `.env` > 기본값** 순서로 읽는다. 빈 값은 없는 것으로 본다. 견본은 `.env.example`이다(키 이름만 있고 비밀값 칸은 비어 있다).

```bash
cp .env.example .env      # .env는 .gitignore로 막혀 있다. 절대 커밋하지 않는다
```

| 이름 | 뜻 | 기본값 |
|---|---|---|
| `OPENAI_API_KEY` | 제품 LLM 키. **환경변수로만 넣는다.** 값을 파일·문서·로그에 쓰지 않는다 | 없음 |
| `NEUMANN_PSEUDONYM_SALT` | 리뷰어 가명 해시 솔트. 비어 있으면 가명 생성을 거부한다 | 없음 |
| `NEUMANN_LLM_PROVIDER` | `mock`(시험용 결정적 응답) 또는 `openai`(실제 호출, 키 필요, 비용) | `mock` |
| `NEUMANN_LLM_MODEL` | 제품 모델. LLM으로 잰 평가 수치(Macro-F1 0.4864, 라이브 E2E)는 `gpt-6-astra`로 잰 것 | `gpt-6.1-sol` |
| `NEUMANN_LLM_TIMEOUT_S` | 호출 시간 상한(초). 넘으면 그 단계만 비상 규칙 경로. 호출별로는 `NEUMANN_LLM_TIMEOUT_<TASK>_S` | `60` |
| `NEUMANN_LLM_EFFORT_<TASK>` | 호출별 추론 강도 덮어쓰기(예: `NEUMANN_LLM_EFFORT_SYNTHESIZE_CARDS`) | 호출별 기본값(`llm.py`) |
| `NEUMANN_EXTRACT_STAGE_TIMEOUT_S` | 지적 추출 단계 전체 시간 상한 | 호출 상한 + 60초 |
| `NEUMANN_LIVE_TESTS` | `1`이면 실제 API를 부르는 테스트도 돈다 | 꺼짐 |
| `NEUMANN_RAW_DIR` | 공개자료 원본 폴더(§3) | 없음 |
| `NEUMANN_DATA_DIR` | 가공 데이터 폴더(코퍼스·색인·평가 산출·사전 계산본) | `<저장소>/data` |
| `NEUMANN_EMBED_MODEL` | bge-m3 로컬 폴더(색인 빌드·검색). 없으면 검색은 어휘(BM25)만 쓰고 강등을 기록한다 | 없음 |
| `NEUMANN_INDEX_DIR`, `NEUMANN_EMBED_DEVICE`, `NEUMANN_EMBED_BATCH`, `NEUMANN_EMBED_MAX_SEQ` | 색인 폴더·임베딩 장치·배치·최대 토큰(`src/neumann/index/settings.py`) | `<데이터 폴더>/index`, `auto`(cuda 있으면 cuda), `16`, `512` |
| `NEUMANN_SEARCH_ALPHA` | 검색 결합 점수의 임베딩 비중(나머지는 BM25) | `0.6` |
| `NEUMANN_SEARCH_SCORE_FLOOR` | 점수 하한. 비우면 임베딩 모델별 실측 보정값(bge-m3 0.45), 보정값 없는 모델·어휘만 검색이면 0 | 비움 |
| `NEUMANN_SEARCH_FUSION` | 여러 질의 결합: `rrf`(질의별 순위 융합) 또는 `max` | `rrf` |
| `NEUMANN_SEARCH_RRF_K` | 순위 융합 상수 k | `60` |
| `NEUMANN_SEARCH_PER_QUERY_MIN` | 질의마다 하한을 넘은 상위 n편을 결과에 먼저 넣는다(0이면 끔) | `1` |
| `NEUMANN_SEARCH_AXIS_WEIGHTS` | 축별 가중치 | `topic=1,method=1,data=1,evaluation=0.5` |
| `NEUMANN_SEARCH_ADAPTIVE_ALPHA` | 질의 낱말 중 색인 어휘에 있는 비율만큼만 BM25에 비중(한국어 질의는 임베딩만) | `true` |
| `NEUMANN_API_HOST`, `NEUMANN_API_PORT` | 서버 주소 설정 칸. 지금 서버는 uvicorn 명령줄의 `--host`·`--port`로 정한다 | `127.0.0.1`, `8000` |

키가 들어 있는지는 참·거짓으로만 확인한다. 값을 출력하지 않는다.

```bash
python -c "import os; print(bool(os.getenv('OPENAI_API_KEY')))"
```

셸마다 한 번(Windows Python은 `PYTHONPATH` 구분자가 `;`다. Git Bash에서도 그렇다. macOS·Linux는 `src:.`):

```bash
export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export NEUMANN_RAW_DIR="<공개자료 폴더>"
export NEUMANN_DATA_DIR="<데이터 폴더>"
export NEUMANN_LLM_PROVIDER=mock        # 기본값과 같다. 실제 분석은 openai(키 필요, 비용, 승인 뒤)
```

## 3. 공개자료 원본

원본은 저장소 밖 한 폴더(`NEUMANN_RAW_DIR`)에 받아 두고 읽기만 한다. 코드는 이 폴더 아래 상대 경로를 쓴다.

```
<NEUMANN_RAW_DIR>/
├─ data/researcharcade/papers/train-00000-of-00001.parquet
├─ data/researcharcade/reviews/train-00000-of-00006.parquet, train-00001-of-00006.parquet
├─ data/disapere/DISAPERE.zip
├─ data/retraction_watch/retraction_watch.csv
└─ models/bge-m3/
```

리뷰 샤드 2~5(확대 코퍼스용)는 `scripts/collect_l3_shards.py`가 `<데이터 폴더>/raw/researcharcade/`에 받는다(다운로드라 이 문서에서 실행하지 않음). 받은 곳과 라이선스는 [ARCHITECTURE.md §7](ARCHITECTURE.md#7-데이터-출처와-라이선스).

## 4. 데이터 준비

### 4-1. 코퍼스 조립

ResearchArcade parquet에서 AI for Science 코퍼스를 만든다. 결과는 `<NEUMANN_DATA_DIR>/processed/`의 JSONL과 `corpus_manifest.json`이다. 두 번 돌려도 JSONL의 sha256은 같다.

```bash
python scripts/collect_researcharcade.py                      # 조립(약 10~20초)
python scripts/collect_researcharcade.py --data-dir <다른 폴더>  # 다른 곳에 쓰기
python scripts/collect_researcharcade.py --check-sample 5       # 저장된 심사평과 parquet 원문 대조
python -c "from neumann.sources.corpus import audit_processed; r = audit_processed(); print(r['records'], r['violations'])"
```

확인한 출력(요약): `편수 1128`, `심사평 4298 + 메타리뷰 1068, 저자 답변 12660, 결정 1128`, 거절 비율 `0.6028`, 원문 대조 `전부 일치`, 전량 검사 위반 `0`.

확대 코퍼스(샤드 6개 + 일반 ML)는 `python scripts/collect_l3_corpus.py`가 `<데이터 폴더>/processed_l3/`에 따로 만들고, `python scripts/build_index_l3.py`가 확대 색인 `<데이터 폴더>/index_l3/`를 만든다(현재 색인은 덮지 않는다). 서버·파이프라인은 기본으로 `<데이터 폴더>/index`(1,128편)를 쓰고, 확대 색인으로 바꾸려면 `NEUMANN_INDEX_DIR=<데이터 폴더>/index_l3`로 설정한다. 이 문서에서는 실행하지 않았다(샤드 2~5·bge-m3 필요). E2-L3 보고서의 실측: 2,128편·문장 257,244개·오프셋 100%.

### 4-2. 정정·철회 사후 상태

```bash
python -m neumann.sources.retraction build            # CSV → retraction.jsonl + facets + manifest (약 4초)
python -m neumann.sources.retraction lookup <DOI>     # 원논문 DOI의 사후 상태 목록(없으면 [])
python -m neumann.sources.retraction join             # 코퍼스 Work와 DOI 조인
python -m neumann.sources.retraction prior <키워드>…   # 분야 키워드별 철회 사유 빈도
```

확인한 출력(요약): `rows_read 72684`, `records_written 66737`(원논문 DOI 없는 5,947행 제외), 고유 원논문 DOI 63,690. `join`은 지금 코퍼스에 DOI가 없어 `n_matched_works 0`.

### 4-3. 색인 빌드

§4-1의 코퍼스를 문장 Excerpt·규칙 태그·BM25·bge-m3 임베딩으로 만들어 `<NEUMANN_DATA_DIR>/index/`에 쓴다.

```bash
python scripts/build_index.py                                            # 공유 코퍼스 → 색인(bge-m3 로드, NEUMANN_EMBED_MODEL 필요)
python scripts/build_index.py --source fixtures --out <다른 폴더> --no-embed   # 공용 fixture로, 임베딩 없이(강등 표시)
python scripts/build_index_check.py                                      # 색인 점검: 전량 오프셋 대조, 기본 질의 3건 상위 10편
```

확인한 것: `--source fixtures --no-embed`만 실행했다(`오프셋 대조(메모리) 44/44, (디스크) 44/44`, `강등: --no-embed`). 실데이터 빌드와 `build_index_check.py`는 bge-m3를 불러오므로 실행하지 않았다. E2-L0 보고서의 실측: 문장 133,769개 전량 오프셋 대조 100%, 빌드 76.6초(CUDA).

## 5. 분석 실행

### 5-1. 서버

```bash
python -m uvicorn neumann.api.main:app --host 127.0.0.1 --port 8000                             # 기본 mock(비용 없음)
NEUMANN_LLM_PROVIDER=openai python -m uvicorn neumann.api.main:app --host 127.0.0.1 --port 8000 # 실제 분석(키 필요, 비용, 승인 뒤)
```

- 화면: `http://127.0.0.1:8000/`. 상태: `curl http://127.0.0.1:8000/health` → `pipeline.state: "connected"`.
- 폰트는 로컬에서 서빙하고, 화면 원본(`webui/index.html`)에는 외부 URL이 없다.
- `NEUMANN_EMBED_MODEL`이 없으면 검색이 어휘만으로 돌고 결과에 `search` 단계 강등이 표시된다.
- 확인한 것: 포트 8125에서 mock provider·임베딩 없이 띄워 `/health`, `/premortem`, `/premortem/view`, `/premortem/precomputed`, `/config/weights`, `/premortem/package`를 요청했다(응답은 [API.md](API.md)). 데모 계획서 1건 분석 1.8초(mock, 어휘 검색). 실제 astra 경로는 이 문서에서 부르지 않았다.

### 5-2. 명령줄 한 건

```bash
python -m neumann.pipeline tests/fixtures/plans/plan.md --provider mock     # 결과 JSON 요약 출력
```

`--provider openai|mock|off`, `--backend index|fixture`. 확인한 것: `--provider mock`으로 실행(총 1.4초).

### 5-3. 데모 사전 계산본(오프라인 폴백)

```bash
python scripts/precompute_demo.py                       # 데모 3건 → <데이터 폴더>/precomputed/ (파이프라인 사용, provider는 설정대로: 기본 mock)
python scripts/precompute_demo.py --source fixture      # 네트워크·API 없이 fixture로
python scripts/precompute_demo.py --out <다른 폴더>
```

확인한 것: `NEUMANN_LLM_PROVIDER=mock … --source pipeline --out <스크래치>` → 3건, 카드 5·4·4(전부 mock), `재생 확인: 3/3`. 서버의 `GET /premortem/precomputed`가 이 폴더를 읽는다. 사전 계산본에는 생성 방식(pipeline/fixture)과 provider가 그대로 남는다.

### 5-4. 정적 데모 사이트·시연 녹화

```bash
python scripts/build_static_site.py --out <다른 폴더>      # 서버 없이 도는 데모 사이트(사전 계산본을 읽음)
python scripts/build_static_site.py --check <폴더>         # 만든 폴더 검사만
python scripts/record_demo.py --base-url http://127.0.0.1:8000 --plan tests/fixtures/plans/plan.md --out <폴더>   # Playwright 녹화
```

확인한 것: `build_static_site.py --precomputed <5-3 산출> --out <스크래치>` → `검사 통과: 필수 파일·데모 JSON, 비밀값 0, 환경변수 이름 0, 로컬 경로 0, 외부·루트 절대 참조 0`. 정적 판 화면에는 "정적 판 · 사전 계산본 — 라이브 분석 아님" 띠가 붙는다. `record_demo.py`는 서버와 브라우저가 필요해 `--help`만 확인했다(서버가 샘플 상태면 영상에 "SAMPLE" 배지를 붙인다).

## 6. MCP 서버

```bash
python -m neumann.api.mcp_server        # stdio. 읽기 전용 도구 3종: search_similar_works, get_review_records, get_post_status
python -m pytest tests/e4 -q -k mcp     # SDK 클라이언트로 서버를 띄워 도구 목록·호출 형식을 검사
```

`mcp` 패키지(`pyproject.toml`)가 필요하다. 확인한 것: 테스트 `11 passed`. 서버 단독 실행은 MCP 클라이언트가 붙어야 의미가 있어 테스트로만 확인했다.

## 7. 테스트

```bash
python -m pytest -q                        # 전체. tests/conftest.py가 mock provider로 고정
python -m pytest tests/e4 -q               # 에픽별
NEUMANN_LIVE_TESTS=1 python -m pytest -q   # 실제 API 테스트까지(키 필요, 비용)
```

- 재측정(main `b01df0a` 병합 상태, `NEUMANN_LLM_PROVIDER=mock` 명시, `NEUMANN_RAW_DIR`·`NEUMANN_DATA_DIR` 지정): `1047 passed, 26 skipped`. 건너뛰는 것은 실제 API 테스트(`NEUMANN_LIVE_TESTS=1`), 실제 bge-m3(`NEUMANN_E2_MODEL_TESTS=1`), 브라우저 화면(`NEUMANN_UI_TESTS=1`), 실색인 회귀(`NEUMANN_REAL_DATA_TESTS=1`)다.
- 라이브 E2E(`tests/e2e/test_live.py`)는 실서버와 실제 OpenAI 호출을 쓰므로 `NEUMANN_LIVE_TESTS=1`일 때만 돈다(`--e2e-base-url`로 서버 지정, 비용). 판정 함수는 기본 pytest(`tests/e2e/test_e2e_checks.py`)가 검사한다. 이 문서에서는 라이브로 돌리지 않았다.
- 공개자료 폴더(`NEUMANN_RAW_DIR`)나 공유 데이터 폴더가 없으면 원본·실데이터 테스트(`tests/e1/test_e1_corpus_real.py`, `test_retraction_real.py` 등)도 건너뛴다. 위 재측정은 두 폴더를 모두 준 상태다.

화면 스크린샷(Playwright, 1440×900). 스크립트가 uvicorn을 하위 프로세스로 띄우고 끝나면 끈다(시험은 mock으로):

```bash
NEUMANN_LLM_PROVIDER=mock python tests/e4/ui_shots.py --port 8125 --out <출력 폴더> --prefix demo
```

## 8. 평가 명령

```bash
# DISAPERE 골드(148건)와 튜닝셋(358건)
python -m eval.disapere_gold --out-dir <데이터 폴더>/eval
# 빈도 기준선(심사평을 읽지 않고 dev 최빈 3코드)
python -m eval.baseline_freq --dev <데이터 폴더>/eval/disapere_dev.jsonl \
    --target <데이터 폴더>/eval/disapere_gold.jsonl --out <데이터 폴더>/eval/pred_baseline_freq.jsonl
# 리뷰 단위 Tier-1 Macro-F1 (부트스트랩 95% 구간)
python -m eval.macro_f1 --pred <데이터 폴더>/eval/pred_baseline_freq.jsonl \
    --gold <데이터 폴더>/eval/disapere_gold.jsonl --out <데이터 폴더>/eval/score_baseline_freq.json
# 근거 연결 검사(원문 오프셋 대조)
python -m eval.linkage --result tests/fixtures/premortem_result.json --sources tests/fixtures
# 백테스트 표본 30편(층화·시드 고정)
python -m eval.backtest_sample --out <폴더>
# 리포트 카드(지표 JSON → Markdown 한 장)
python -m eval.report_card --inputs <지표 JSON …> --out <파일.md>
```

확인한 출력: 빈도 기준선 `Macro-F1 0.3308 [95% 0.2980, 0.3623]  Micro-F1 0.5379 … n=148`, 근거 연결 `8/8 = 1.000 · 카드 통과 2/2 · 폐기율 없음 · 판정 pass`(fixture라 폐기율이 없다), 백테스트 표본 30편 출력, `report_card --help`.

DISAPERE 골드에 제품 지적 추출기를 돌리는 `python -m eval.disapere_extract extract|tune|predict`(OpenAI 호출)와 백테스트의 나머지 단계(`eval.backtest_run_neumann`, `eval.baseline_llm`, `eval.judge_run`)는 파이프라인·일반 LLM 호출·판정자 실행이 들어가 이 문서에서 실행하지 않았다. 사용법은 각 모듈 머리말에 있다.

## 9. verify (병합·push 전 필수)

```bash
python scripts/verify.py              # 보안 + 계약 + 전체 pytest
python scripts/verify.py --security   # 보안만(추적·미추적 파일 + 커밋 메시지). pre-push 훅
python scripts/verify.py --staged     # 스테이징 내용만. pre-commit 훅
```

- 보안 검사는 키 형태 문자열, `.env`·환경변수에 든 실제 키 값의 원문, 금지 파일(`.env`, parquet, 모델 가중치 등), 5MB 초과 파일을 찾는다. 찾은 값은 출력하지 않고 위치와 종류만 알린다.
- 훅: `pre-commit`(스테이징), `commit-msg`(메시지), `pre-push`(추적 파일 전체와 커밋 메시지). 훅을 우회하지 않는다.

## 10. 비밀값 규칙 요약

- 키는 환경변수 `OPENAI_API_KEY`로만 준다. 코드에 기본값으로 넣지 않는다.
- `.env`를 열거나 출력하지 않는다. 환경변수 전체를 출력하지 않는다.
- `git add`는 파일을 지정해서 한다. 데이터·가중치·색인·캐시·로그는 올리지 않는다.
- 전체 규칙은 `AGENTS.md`.
