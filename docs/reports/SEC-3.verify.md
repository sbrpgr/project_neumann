**판정: PASS-조건부** — 실제 OpenAI 호출 잠금 자체는 반증하지 못했다(실제 클라이언트 생성 경로 2곳 모두 플래그 없이 차단, 파이프라인 표기 정직, /health 키 노출 없음, verify 1061 통과). 다만 병합 전에 고칠 것 5건(아래 "고칠 것")이 있다. 3·4·5번은 표기 정직성 위반(잠긴 실행이 astra로 표기되거나 실패가 캐시에 남음)이라 병합 조건이고, 1·2번은 시험 위생·보강이다.

- 검증자: Claude Sonnet 5.5 (빌더: Opus, PM) · 대상: `task/SEC-3` `ab3270f` (기준 main `cd0a3ca`) · worktree `C:\Users\User\Desktop\pn_sec3`
- 검증 방법: 실제 키는 쓰지 않았다(가짜 키 `fake-test-key-not-real-000`만). 실제 클라이언트가 만들어지면 즉시 멈추도록 `openai.OpenAI`를 감시용 대체 클래스로 바꿔 놓고 돌렸다(네트워크 호출 없음). 변이 시험은 `git archive ab3270f`로 scratchpad에 푼 복사본에서만 했다. worktree는 수정하지 않았고 `git status` 깨끗(검증 전후 동일).
- 병합 충돌: `git merge-tree main task/SEC-3` 충돌 없음(main은 `848bd50`까지 왔지만 SEC-3이 건드린 파일은 안 바뀜). `contracts/`·`models.py` 변경 없음. PM이 E3(`llm.py`)·E5(`eval/baseline_llm.py`) 소유 파일을 고친 것은 `docs/decisions.md`에 기록돼 있다(긴급 보안 수정).

## 1. 실제 호출 경로 전수 조사

`src/`·`eval/`·`scripts/`에서 `OpenAI(`·`openai.`·`responses.create`·`httpx`·`urllib`·`requests`·`api.openai.com`·`base_url`·`codex`를 grep했다.

| 경로 | 위치 | 플래그 없음(미설정·빈값·`0`·`no`·`false`·`off`·`2`·`x`·공백) | 비고 |
|---|---|---|---|
| 실제 클라이언트 생성 1 | `src/neumann/llm.py:230` `OpenAIProvider.__init__` | 차단(`_config_error`="실제 호출 잠김", `_client is None`, `complete_json`은 `config_error` 실패) | 직접 생성도 막힘. 주입한 `client=`는 막지 않음(가짜 클라이언트 시험용, 의도) |
| 생성 진입점 | `llm.make_llm` (`pipeline`, `eval/disapere_extract`, `eval/backtest_run_neumann`, `scripts/precompute_demo`, API가 모두 경유) | provider=openai(설정·인자·환경변수, 대소문자 `OpenAI` 포함) → `mock`으로 강등 | `OpenAIProvider(`를 직접 부르는 곳은 `make_llm` 하나뿐 |
| 실제 클라이언트 생성 2 | `eval/baseline_llm.py:121` `OpenAIBaseline._get_client` | 차단(`RuntimeError`) | 결과 처리 문제는 아래 4번 |
| 플래그=1 | 위 두 곳 | 감시 클래스가 실제로 발동함 = 플래그가 유일한 차단막임을 확인 | |
| 네트워크 호출 | `sources/corpus_l3.py`(HF 다운로드), `record_demo.py`·`build_static_site_shots.py`(127.0.0.1) | OpenAI 아님 | 해당 없음 |
| `codex exec` | `eval/judge_run.py` `--execute` | 가드 밖(외부 CLI, ChatGPT 로그인 구독, 기본 dry-run) | 잔여 위험으로만 기록. 실제 API 키 인증을 쓰는지는 확인 못 함 |
| 라이브 시험 | `tests/e3/*_live.py`, `tests/e5`, `tests/e2e/test_live.py` | `NEUMANN_LIVE_TESTS=1`+키가 있을 때만 돎(skipif 확인) | 일부는 `OpenAI()`를 직접 만들어 플래그를 안 봄(허용 범위) |

플래그 값 매트릭스(provider=openai, 가짜 키, 프로세스 환경변수만 바꿈, `.env` 없음): 미설정·`""`·`0`·`no`·`false`·`off`는 `live_llm_allowed()=False`, `make_llm` → mock, 직접 생성 클라이언트 없음. `2`·`x`·`" "`는 `Settings`가 ValidationError로 실패하지만 결과는 False(닫힘). 플래그 `1`만 열림.

캐시: `make_llm`이 mock으로 강등되면 `extract._run_batch`(`llm.name=="openai"`일 때만 캐시)와 `queries`(astra만)는 캐시를 읽거나 쓰지 않는다. 옛 astra 캐시가 mock 실행에 섞이지 않는다.

## 2. 우선순위(환경변수 vs `.env`)와 닫힘 실패

scratchpad 복사본에 가짜 `.env`를 만들어 잰 결과(`live_llm_allowed()`):

| `.env` | 프로세스 환경변수 | 결과 |
|---|---|---|
| `NEUMANN_LIVE_LLM_OK=1` | `0` | False (환경변수 우선) |
| 같음 | `false` | False |
| 같음 | `""`(빈 값) | True (빈 값은 `.env`로 넘어감) |
| 같음 | 미설정 | True |
| 같음 | `1` | True |
| 같음 | `x` / `" "` | False (설정 오류 → 닫힘) |
| `=maybe`(잘못된 값) | 미설정 | False (ValidationError → 닫힘) |
| `=1` + `NEUMANN_LLM_PROVIDER=bogus`(설정 전체 오류) | 미설정 | False |
| 같음 | `1` | True (환경변수만으로 판정, 설정 오류와 무관) |
| 없음 | 미설정 | False (기본) |

파이프라인도 설정 오류(플래그 `x`, provider `bogus`)에서 죽지 않고 mock 또는 rule로 돌며 "설정 로드 실패(ValidationError)"를 notices에 남긴다. 통과.

## 3. 파이프라인 표기(가짜 코퍼스, 가짜 키, provider=openai 요청, 플래그 없음)

`run_premortem`을 `tests/e3/corpus.py` FixtureBackend로 돌렸다(인자로 `provider="openai"`, 설정으로 `NEUMANN_LLM_PROVIDER=openai`+`NEUMANN_LLM_MODEL=gpt-6-astra` 두 방식).

- 카드 generator `['mock']`, 모델 `mock-deterministic-v1`(환경변수의 `gpt-6-astra`가 아님)
- 단계 impl: `mock:mock-deterministic-v1`, `expected_review.generator=mock`, `manifest.llm_provider=mock`
- notices: `mock provider(테스트용) 결과 — 실제 astra 분석이 아니다`, `status=degraded`, 검색어 캐시 `enabled=False`
- 결과 JSON에 `"astra"`·`gpt-6-astra`·가짜 키 문자열 모두 0회
- 통과. 단 강등 사유(openai 요청이 잠겨서 mock이 됨)는 `log.warning`에만 있고 결과·notices에는 없다(아래 6번 권고).

## 4. `/health.llm` (TestClient, 가짜 키)

| 플래그 | `llm` 블록 |
|---|---|
| 미설정·`""`·`0` | `{"provider_requested":"openai","live_llm_ok":false,"effective":"mock","model":""}` |
| `1` | `{"provider_requested":"openai","live_llm_ok":true,"effective":"openai","model":"gpt-6-astra"}` |
| `x`(설정 오류) | `{"error":"ValidationError"}` |

본문 전체에서 가짜 키·`fake-test`·`sk-`·`api_key` 문자열 없음. 통과. (`effective`는 키 유무를 보지 않는다: 플래그=1인데 키가 없으면 `effective:"openai"`로 나오지만 실제 호출은 config_error 실패. 참·거짓 `key_present`를 더하면 정확해진다. 권고.)

## 5. 시험이 가드를 실제로 검사하는가 (scratchpad 복사본 변이)

`tests/e0/test_sec3_live_guard.py`+`tests/e3/test_llm.py`(정상 35개 통과)에 변이를 넣었다.

| 변이 | 결과 |
|---|---|
| M1 `make_llm` 강등 제거 | 실패 2건 |
| M2 `OpenAIProvider` 생성자 잠금 제거 | 실패 1건 |
| M3 `baseline_llm` 잠금 제거 | 실패 1건 |
| M4 `live_llm_allowed` 항상 True | 실패 6건 이상 |
| M5 conftest의 플래그 `0` 고정 제거(환경에 `1`이 있는 상황) | 실패 1건(`test_conftest_closes_flag_by_default`) |
| M7 빈 값을 True로 취급 | 실패 다수 |
| M9 `/health.effective`를 요청값 그대로 | 실패 1건 |
| M11 `/health.llm`에 키 값 노출 | 실패 1건(dict 동등 비교 때문. 아래 참고) |
| **M6 설정 오류 시 True(fail-open)** | **통과함(시험이 못 잡음)** |

시험 약점:
- M6이 살아남는다. "설정 오류는 닫힘"을 검사하는 시험이 없다(`config.py`의 `except`, `llm._live_llm_allowed`의 import 실패 분기 모두).
- `.env=1`+환경변수 `0` 우선순위 시험이 없다. 지금 코드는 위 2절 수동 측정으로 맞다. 그러나 `test_flag_values`의 `""` 케이스는 `live_llm_allowed()`가 아니라 `Settings(...)`를 직접 재서 `.env` fall-through를 검사하지 못한다.
- `test_health_reports_guard`의 `assert FAKE_KEY not in str(body)`는 그 시험이 `OPENAI_API_KEY`를 안 심어서 항상 참인 검사다. 키 노출은 앞줄의 dict 정확 비교가 대신 잡아 주므로 방어는 되지만, 그 줄은 죽은 검사다.

## 6. `python scripts/verify.py` (worktree, mock, 플래그·라이브 시험 변수 없음)

```
1061 passed, 26 skipped in 87.51s
보안: 파일 360개 / 계약: 2개 / 테스트: 통과 / verify 통과
```

## 고칠 것 (병합 전)

1. **`tests/e3/test_llm.py::test_make_llm_selects_provider`**: 플래그를 `1`로 켜는데, 주석("키가 없어 클라이언트를 만들지 않는다")과 달리 프로세스 환경에 `OPENAI_API_KEY`가 있으면(`_COMMON.md`상 에이전트 환경에 있음) `make_llm`이 환경변수 키를 집어 **실제 `openai.OpenAI` 클라이언트를 만든다**(가짜 키+감시 클래스로 재현: 키 있음 → 생성됨, 없음 → 안 됨). 네트워크 호출·비용은 없다. 그래도 "빌더·검증자는 플래그를 켜지 않는다"는 원칙에 어긋난다. 고침: 그 시험에 `monkeypatch.delenv("OPENAI_API_KEY", raising=False)`를 추가하거나 `openai.OpenAI`를 대체해 생성 여부를 단언.
2. **시험 보강(`tests/e0/test_sec3_live_guard.py`)**: (a) `get_settings`가 예외를 던질 때 `live_llm_allowed()`가 False(M6 변이가 실패하게), (b) 임시 `.env`(`NEUMANN_LIVE_LLM_OK=1`)에서 환경변수 `0`이면 False·빈 값이면 True, (c) `test_health_reports_guard`에서 `OPENAI_API_KEY`를 `FAKE_KEY`로 실제로 심고 본문에 없음을 단언(죽은 검사 제거).
3. **`eval/baseline_llm.py`**: 잠긴 상태로 돌면 `_get_client`의 `RuntimeError`가 `generate()`에서 `error="RuntimeError"`로만 남아 잠금 사유가 안 보이고, `generate_cached`가 **실패 항목을 영구 캐시에 쓴다**. 이후 대표 승인으로 플래그를 켜고 돌려도 `cache_hit=True, ok=False`로 실패를 그대로 재사용한다(재현: 잠금 실행 → 플래그 켠 실행이 캐시 적중, 클라이언트 생성 안 함). 잠금 실행이 만든 캐시는 손으로 지워야 한다. 고침: 잠금 오류에 전용 예외명·메시지(`LiveLocked`)를 남기고, 잠금·설정 오류 등 호출 자체를 못 한 실패는 캐시에 쓰지 않는다. 또 `riskset_from_entry`가 실패 행에도 `generator="astra"`·`model="gpt-6-astra"`를 붙이니(status는 error), 호출 못 한 행은 generator를 비우거나 `off`로 둔다.
4. **`eval/disapere_extract.py` `cmd_extract`**: `--generator astra`인데 잠겨서 mock으로 강등되면 조용히 계속해 `raw_astra_dev.jsonl`을 만들고 stats의 `"generator": "astra"`, `cache_dir`(astra 캐시 폴더)를 적는다. 행의 `generator`는 `mock`, `model`은 `mock-deterministic-v1`이라 파일 이름·메타와 내용이 어긋난다(재현: 가짜 `NEUMANN_DATA_DIR`에 리뷰 1건을 두고 실행). 이 파일을 `tune --generator astra`·`predict`가 읽으면 mock 결과가 astra 평가처럼 보인다. 고침: `args.generator=="astra"`인데 `llm.name!="openai"`면 `SystemExit("astra 요청이지만 실제 호출 잠김")`로 멈추거나(권장) 메타·파일 이름에 실제 generator를 쓴다.
5. **`scripts/precompute_demo.py` `llm_settings()`**: 매니페스트 `llm` 블록이 설정의 요청값(`{'provider':'openai','model':'gpt-6-astra'}`)을 그대로 적는다. 잠겨서 mock으로 돈 사전 계산본도 이렇게 나온다(항목별 `models`·`cards_by_generator`는 mock으로 정직해서 매니페스트 안에서 서로 모순). 고침: 결과의 `manifest.llm_provider`·`llm_model`(실제 사용 값) 또는 `live_llm_allowed()`를 반영한 유효값을 적는다.

## 권고 (병합을 막지는 않음)

6. 강등을 결과에도 남긴다: 잠금으로 openai가 mock이 되면 `run_premortem`이 notices에 "openai 요청이 NEUMANN_LIVE_LLM_OK 없어 mock으로 강등됨"을 더한다. 지금은 `log.warning`뿐이라, 실서비스가 플래그 없이 재기동되면 화면에는 "mock provider(테스트용) 결과"만 뜨고 이유가 없다(AGENTS "폴백은 결과와 화면에 표시").
7. 플래그 놓는 곳 문서가 어긋난다: `AGENTS.md`·`.env.example`은 "서버 기동 명령에만", `config.py`(필드 주석·모듈 docstring)는 "main 체크아웃 `.env`"도 허용한다. `.env`에 `1`을 두면 main 체크아웃에서 돌리는 모든 스크립트(검증자·PM 포함)가 열린다. 시험은 환경변수 `0` 고정이라 안전하지만 임의 스크립트는 아니다. 기동 명령에만 두도록 `config.py` 문구를 맞춘다.
8. 운영 주의: 8010 실서비스가 지금 `.env`로 provider=openai를 켜고 있다면, 이 커밋을 반영한 뒤 기동 명령에 `NEUMANN_LIVE_LLM_OK=1`이 없으면 조용히 mock이 된다. 재기동 전에 기동 명령에 플래그를 넣고 `/health.llm.effective`가 `openai`인지 확인한다.
9. `/health.llm`에 `key_present`(참·거짓)를 더하면 `effective:"openai"`인데 키가 없는 경우도 드러난다.

## 잔여 위험 (범위 밖, 기록만)

- `eval/judge_run.py --execute`의 `codex exec`와 `NEUMANN_LIVE_TESTS=1` 라이브 시험은 이 플래그와 무관하게 OpenAI에 닿을 수 있다. 전자는 기본 dry-run, 후자는 대표 승인 과제에서만 켠다는 규칙에 의존한다.
- 이미 떠 있는 프로세스가 옛 사용자 환경변수(provider=openai)를 물려받아도, 새 코드를 import하는 순간부터는 잠긴다. 코드를 다시 읽지 않는 장수 프로세스(재기동 안 한 서버)는 이 보호를 받지 못한다.
