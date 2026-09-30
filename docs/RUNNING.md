# 실행 방법

- 기준: `main` 커밋 `5e14b1c`. 이 문서의 명령은 main 사본(`82146f9`·`5e14b1c`)에서 Windows 11 + Git Bash + Python 3.12.10으로 실행해 확인했다(결과는 `docs/reports/E6-docs.md`).
- **예정**이라고 적은 명령은 main에 아직 없는 스크립트다. 과제가 병합되면 그 과제 보고서(`docs/reports/<과제ID>.md`)를 본다.
- 구조와 상태는 [ARCHITECTURE.md](ARCHITECTURE.md), 엔드포인트는 [API.md](API.md).

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
- 새 venv에 설치할 때는 네트워크가 필요하다. `torch`는 크고, GPU용 빌드가 필요하면 PyTorch 안내대로 인덱스를 따로 지정한다. 이 문서를 쓸 때는 이미 갖춰진 개발 venv에 같은 명령을 `--dry-run --offline`으로 돌려 의존성 80개가 모두 충족됨(`Would make no changes`)만 확인했다.
- `torch`·`sentence-transformers`는 색인 빌드와 임베딩 검색(bge-m3)에 쓴다. 기본 테스트는 실제 모델을 불러오지 않는다(`NEUMANN_E2_MODEL_TESTS=1`일 때만).
- 화면 스크린샷 스크립트(§7)를 쓸 때만 Playwright 브라우저가 필요하다: `python -m playwright install chromium`.

## 2. 환경변수

설정 로더(`src/neumann/config.py`)는 **환경변수 > 저장소 루트 `.env` > 기본값** 순서로 읽는다. 빈 값은 없는 것으로 본다. 견본은 `.env.example`이다(키 이름만 있고 비밀값 칸은 비어 있다).

```bash
cp .env.example .env      # .env는 .gitignore로 막혀 있다. 절대 커밋하지 않는다
```

| 이름 | 뜻 | 기본값 |
|---|---|---|
| `OPENAI_API_KEY` | 제품 LLM 키. **환경변수로만 넣는다.** 값을 파일·문서·로그에 쓰지 않는다 | 없음 |
| `NEUMANN_PSEUDONYM_SALT` | 리뷰어 가명 해시 솔트. 비어 있으면 가명 생성을 거부한다 | 없음 |
| `NEUMANN_LLM_PROVIDER` | `openai` 또는 `mock` | `openai` |
| `NEUMANN_LLM_MODEL` | 제품 모델 | `gpt-6-astra` |
| `NEUMANN_LLM_TIMEOUT_S` | 호출 단계별 시간 상한(초). 넘으면 그 단계만 비상 규칙 경로 | `60` |
| `NEUMANN_LIVE_TESTS` | `1`이면 실제 API를 부르는 테스트도 돈다 | 꺼짐 |
| `NEUMANN_RAW_DIR` | 공개자료 원본 폴더(§3) | 없음 |
| `NEUMANN_DATA_DIR` | 가공 데이터 폴더(코퍼스·색인·평가 산출) | `<저장소>/data` |
| `NEUMANN_EMBED_MODEL` | bge-m3 로컬 폴더(색인 빌드·검색용) | 없음 |
| `NEUMANN_INDEX_DIR`, `NEUMANN_EMBED_DEVICE`, `NEUMANN_EMBED_BATCH` | 색인 폴더·임베딩 장치·배치(선택, `src/neumann/index/settings.py`) | `<데이터 폴더>/index` 등 |
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

받은 곳과 라이선스는 [ARCHITECTURE.md §7](ARCHITECTURE.md#7-데이터-출처와-라이선스).

## 4. 코퍼스 조립 (있음)

ResearchArcade parquet에서 AI for Science 코퍼스를 만든다. 결과는 `<NEUMANN_DATA_DIR>/processed/`의 JSONL과 `corpus_manifest.json`이다. 두 번 돌려도 JSONL의 sha256은 같다.

```bash
python scripts/collect_researcharcade.py                      # 조립(약 11~21초)
python scripts/collect_researcharcade.py --data-dir <다른 폴더>  # 다른 곳에 쓰기
python scripts/collect_researcharcade.py --check-sample 5       # 저장된 심사평과 parquet 원문 대조
python -c "from neumann.sources.corpus import audit_processed; r = audit_processed(); print(r['records'], r['violations'])"
```

확인한 출력(요약): `편수 1128`, `심사평 4298 + 메타리뷰 1068, 저자 답변 12660, 결정 1128`, 거절 비율 `0.6028`, 전량 검사 위반 `0`.

## 4-1. 정정·철회 사후 상태 (있음)

Retraction Watch CSV를 `PostStatus` JSONL로 바꾸고, 원논문 DOI로 조회한다. 결과는 `<NEUMANN_DATA_DIR>/processed/retraction*.json(l)`이다.

```bash
python -m neumann.sources.retraction build            # CSV → retraction.jsonl + facets + manifest (약 4초)
python -m neumann.sources.retraction lookup <DOI>     # 원논문 DOI의 사후 상태 목록(없으면 [])
python -m neumann.sources.retraction join             # 코퍼스 Work와 DOI 조인
python -m neumann.sources.retraction prior <키워드>…   # 분야 키워드별 철회 사유 빈도
```

확인한 출력(요약): `rows_read 72684`, `records_written 66737`(원논문 DOI 없는 5,947행 제외), 고유 원논문 DOI 63,690.

## 5. 색인 빌드 (있음)

§4의 코퍼스를 문장 Excerpt·규칙 태그·BM25·bge-m3 임베딩으로 만들어 `<NEUMANN_DATA_DIR>/index/`에 쓴다. 색인 파일은 커밋하지 않는다.

```bash
python scripts/build_index.py                                            # 공유 코퍼스 → 색인(bge-m3 로드, NEUMANN_EMBED_MODEL 필요)
python scripts/build_index.py --source fixtures --out <다른 폴더> --no-embed   # 공용 fixture로, 임베딩 없이(강등 표시)
python scripts/build_index_check.py                                      # 색인 점검: 전량 오프셋 대조, 기본 질의 3건 상위 10편
```

- 확인한 것: `--source fixtures --no-embed`는 이 문서를 쓸 때 실행했다(`오프셋 대조(메모리) 44/44, (디스크) 44/44`, `강등: --no-embed`). 실데이터 전체 빌드와 `build_index_check.py`는 bge-m3를 불러오므로 이 문서에서 실행하지 않았다. E2-L0 보고서의 실측: 문장 133,769개 전량 오프셋 대조 100%, 빌드 76.6초(CUDA).
- 임베딩 모델을 못 읽으면 검색은 어휘(BM25)만 쓰고 강등을 기록한다.

## 5-1. MCP 서버 (있음)

```bash
python -m neumann.api.mcp_server        # stdio. 읽기 전용 도구 3종: search_similar_works, get_review_records, get_post_status
python -m pytest tests/e4 -q -k mcp     # SDK 클라이언트로 서버를 띄워 도구 목록·호출 형식을 검사
```

`mcp` 패키지(`pyproject.toml`의 `mcp>=2.2,<3`)가 필요하다. 확인한 것: `11 passed`. 서버 단독 실행은 MCP 클라이언트가 붙어야 의미가 있어 테스트로만 확인했다.

## 6. 서버 실행 (있음)

```bash
python -m uvicorn neumann.api.main:app --host 127.0.0.1 --port 8000
```

- 화면: `http://127.0.0.1:8000/`. 상태: `curl http://127.0.0.1:8000/health`.
- 지금 main에는 분석 파이프라인이 없어서 `/health`의 `pipeline.state`가 `unavailable`이고, 분석 요청에는 공용 fixture(가짜 데이터) 샘플이 "분석 파이프라인 미연결(샘플 데이터)" 표시와 함께 돌아온다. 입력한 계획서는 분석되지 않는다.
- 이 서버는 OpenAI를 부르지 않는다(파이프라인이 없으므로). 폰트는 로컬에서 서빙하고 화면은 외부 요청을 하지 않는다.
- 다른 포트에서 띄워도 된다(`--port 8125` 등). 끝나면 Ctrl+C로 끈다.

## 7. 테스트 (있음)

```bash
python -m pytest -q                        # 전체. 기본은 mock provider(tests/conftest.py)
python -m pytest tests/e4 -q               # 에픽별
NEUMANN_LIVE_TESTS=1 python -m pytest -q   # 실제 API 테스트까지(키 필요, 돈이 든다)
```

- 확인한 결과: `456 passed, 6 skipped`(main `5e14b1c`). 건너뛴 것: 실제 API 테스트 3건(`NEUMANN_LIVE_TESTS=1`), 실제 bge-m3 1건(`NEUMANN_E2_MODEL_TESTS=1`), 브라우저 화면 1건(`NEUMANN_UI_TESTS=1`), `neumann.llm`이 아직 없어 건너뛴 1건.
- 공유 데이터 폴더가 없으면 실데이터 테스트(`tests/e1/test_e1_corpus_real.py` 등)는 건너뛴다.

화면 스크린샷(Playwright, 1440×900). 스크립트가 uvicorn을 하위 프로세스로 띄우고 끝나면 끈다:

```bash
python tests/e4/ui_shots.py --port 8125 --out <출력 폴더> --prefix demo
```

출력 JSON에 `console_errors`, `external_requests`, `server_stopped`, `port_free_after`가 나온다.

## 8. 평가 명령 (있음)

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
```

확인한 출력: 빈도 기준선 `Macro-F1 0.3308 [95% 0.2980, 0.3623]  Micro-F1 0.5379 … n=148`, 근거 연결 `8/8 = 1.000 · 카드 통과 2/2 · 폐기율 없음 · 판정 pass`(fixture라 폐기율이 없다).

백테스트·리포트 카드는 예정(E5-L2a, E5-L3a).

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
