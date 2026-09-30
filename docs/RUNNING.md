# 실행 방법

- 기준: `main` 커밋 `ed1d1a0`. 이 문서의 명령은 그 커밋의 사본에서 Windows 11 + Git Bash + Python 3.12.10으로 실행해 확인했다(결과는 `docs/reports/E6-docs.md`).
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
- `torch`·`sentence-transformers`는 색인 빌드(예정)에만 쓴다. 지금 main의 서버·테스트·평가 코드는 이것을 import하지 않는다.
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
| `NEUMANN_EMBED_MODEL` | bge-m3 로컬 폴더(색인 빌드용, 예정) | 없음 |
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
├─ data/retraction_watch/retraction_watch.csv          (예정 E1-L2에서 사용)
└─ models/bge-m3/                                      (예정 E2-L0에서 사용)
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

## 5. 색인 빌드 (예정, E2-L0)

main에는 아직 색인 코드가 없다. E2-L0 브랜치의 스크립트 이름은 `scripts/build_index.py`이고 입력은 §4의 코퍼스, 출력은 `<NEUMANN_DATA_DIR>/index/`다. bge-m3를 불러오므로 `NEUMANN_EMBED_MODEL`이 필요하다. 병합 뒤 `docs/reports/E2-L0.md`의 명령을 따른다. 이 문서에서는 실행하지 않았다.

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

- 확인한 결과: `226 passed`(main `ed1d1a0`).
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
