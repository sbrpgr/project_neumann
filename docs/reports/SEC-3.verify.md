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

## 재검증 (9a20726, eb25703)

**최종 판정: PASS-조건부** — 9a20726: 이전 지적 5건 중 4건 해소, 1건(1번)은 지정한 시험은 고쳤으나 같은 결함이 다른 시험에 남아 있다(한 줄 순서 교환). 설계 변경(`live_llm_allowed()`는 프로세스 환경변수만 본다)에서 열림으로 새는 경로는 못 찾았다. eb25703(astra 금지): 제품 코드에서 플래그 없이 astra 모델이 실제 호출에 쓰일 경로는 못 찾았고, manifest·카드 모델은 교체된 실제 값이며, 주입 대역은 이름을 유지한다. verify 통과(1063). 병합 전에 아래 "남은 고칠 것" 1번(한 줄) 하나만 처리하면 된다.

- 검증자: Claude Sonnet 5.5 · 대상: `task/SEC-3` `9a20726`(수정 커밋, 기준 `ab3270f`)과 `eb25703`(astra 금지, `git diff 9a20726 eb25703`) · worktree `C:\Users\User\Desktop\pn_sec3`
- 방법: 실제 키 없음(가짜 키만). `openai.OpenAI`를 감시용 대체 클래스로 바꿔 생성 여부만 세었다(네트워크 호출 없음). 변이·`.env` 시험은 `git archive 9a20726`을 scratchpad에 푼 복사본에서만 했다. 가짜 `.env`는 복사본에만 뒀다. worktree는 수정·커밋하지 않았고 `.env`는 열지 않았다.
- 참고(동시 작업): 20:26:55부터 worktree에 커밋 안 된 수정이 생겼고(내가 한 것이 아님) 이것이 곧 `eb25703`으로 커밋됐다. 아래 1~5절 측정(감시 시험 20:24, verify 20:24·20:26, 동작 시험)은 그 전이라 `9a20726` 그대로였고(중간 `git status` 깨끗 확인), 복사본 시험은 커밋에서 뽑은 것이다. `eb25703` 측정은 6절.

### 1. 이전 "고칠 것" 5건

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| 1 | 시험이 플래그를 켠 채 실제 클라이언트를 만듦 | **부분 해결** | `tests/e3/test_llm.py:201` `delenv("OPENAI_API_KEY")` 추가: 감시 시험(환경에 가짜 키)에서 이 시험은 더 이상 생성하지 않음. 그러나 **`tests/e0/test_sec3_live_guard.py:84-88` `test_flag_opens_openai`가 같은 결함**: `make_llm(...)`(줄 85)이 `delenv`(줄 87)보다 먼저라 환경에 `OPENAI_API_KEY`가 있으면 `openai.OpenAI`가 만들어진다. 감시 결과 `OpenAI 생성 1건: test_sec3_live_guard.py:86 test_flag_opens_openai <- llm.py:472 make_llm <- llm.py:230 __init__`(45개 시험 통과, 생성은 이 1건뿐). 네트워크 호출·비용은 없다 |
| 2 | 시험 보강 | **해결** | (a) 설정 오류 시 닫힘: 이제 함수가 설정을 읽지 않아 그 경로 자체가 없음(구조로 해소, 아래 2절). (b) `.env`=1 무시: `test_sec3_live_guard.py:57` `test_dotenv_flag_is_ignored`, 변이 MA2(`.env` 대체 읽기 복원) 시험 2건 실패로 잡힘. (c) `:151` `test_health_reports_guard_without_key_material`이 `OPENAI_API_KEY`에 FAKE_KEY를 실제로 심고 `FAKE_KEY not in json.dumps(body)` 단언(죽은 검사 제거), 변이 MG 잡힘. 값 매트릭스 `:47`·미설정 `:52` 추가(MB 잡힘) |
| 3 | baseline 잠금 실패 캐시·표기 | **해결** | `eval/baseline_llm.py:100` `LiveCallLocked`, `:145` 잠금은 `{"ok":False,"locked":True,"error":"locked: ..."}` 반환, `:235` 잠금이면 재시도 없이 중단, `:265-268` 캐시에 쓰지 않음, `:292` `generator="none"`+notes. 동작 확인: 잠금 실행 후 캐시 폴더 비어 있음, `entry.locked=True·ok=False·cache_hit=False`, riskset `generator=none·status=error`. 변이 MC(캐시 씀)·MD(astra 표기)·MJ(잠금 제거) 모두 잡힘 |
| 4 | extract `--generator astra` 조용한 강등 | **해결** | `eval/disapere_extract.py:451-453` `llm.name != "openai"`이면 `SystemExit`. 동작 확인: 가짜 데이터 폴더에서 `astra`+잠금 → SystemExit, `raw_astra_dev.jsonl` 안 만들어짐. `mock` 생성기는 정상(`raw_mock_dev.jsonl`) |
| 5 | precompute 매니페스트가 요청값을 사용값처럼 기록 | **해결** | `scripts/precompute_demo.py:183-190` `llm_settings()`가 `provider_requested·model_requested·live_llm_ok`로 이름을 바꿔 기록, `:194` `llm_actual(result)`(결과 manifest의 실제 값), `:304` 항목별 `llm_actual`. 실제 `run_premortem`(FixtureBackend, provider=openai 요청, 플래그 없음)으로 확인: `llm_settings()`={`provider_requested`:openai, `live_llm_ok`:False}, `llm_actual()`={`provider`:mock, `model`:mock-deterministic-v1}. 옛 키(`provider`·`model`)를 읽는 곳 없음(webui·tests·scripts grep, `api/precomputed.py:264`는 그대로 전달만) |

### 2. 설계 변경: `live_llm_allowed()`가 환경변수만 보는가, 열림으로 새는 경로가 있는가

`src/neumann/config.py:72-76`: `return os.environ.get(LIVE_LLM_FLAG, "").strip().lower() in _TRUE`. 예외를 던질 일이 없고 설정·`.env`를 읽지 않으며 `Settings.live_llm_ok` 필드는 삭제됨(`hasattr`=False). 참 값은 `1·true·yes·on`(대소문자·공백 무시)뿐이다.

가짜 `.env`(`NEUMANN_LIVE_LLM_OK=1`, `NEUMANN_LLM_PROVIDER=openai`, 가짜 키)를 둔 복사본에서 잰 결과(감시 클래스로 생성 수 셈):

| 조건 | 결과 |
|---|---|
| `.env`=1, 프로세스 환경변수 미설정, provider는 `.env`에서 openai로 읽힘 | `live_llm_allowed()`=False, `make_llm`→mock, OpenAI 생성 0 (`.env` 플래그가 실제로 무시됨) |
| 환경변수 `""`·`" "`·`0`·`no`·`false`·`off`·`2`·`x`·`-1`·`None`·전각/비ASCII 숫자(`١`) | 모두 False |
| `TRUE`·`1`·`yes`·`on`·`"true "` | True (의도) |
| 설정 오류(`NEUMANN_LLM_PROVIDER=bogus`, ValidationError) | False |
| `get_settings`가 예외를 던지는 상태 | False (설정을 안 읽음) |
| `llm._live_llm_allowed()` (import 분기 포함) | False |

`.env`를 프로세스 환경으로 내보내는 코드도 없다(`load_dotenv`·`os.environ` 대입 grep: 플래그를 쓰는 곳은 `tests/conftest.py`의 `"0"` 고정뿐, pydantic-settings는 환경으로 내보내지 않음). 잠금 호출부 4곳(`make_llm`, `OpenAIProvider.__init__`, `baseline_llm._get_client`, `_live_llm_allowed`)은 모두 이 함수 하나를 본다. **fail-open 경로 없음.** 열림이 되는 유일한 길은 프로세스 환경변수가 실제로 1이 되는 것(사용자·시스템 환경변수에 영구 등록: AGENTS가 금지)이며 이는 코드가 아니라 운영 문제다.

문서 정합(이전 권고 7): `config.py` docstring·`.env.example`(`.env에서는 읽지 않는다`)·`AGENTS.md`가 "기동 명령의 환경변수로만"으로 일치. 해소.

### 3. 새로 생긴 문제

- **(고칠 것) 위 1번 잔여**: `test_flag_opens_openai` 순서. 고침: `monkeypatch.delenv("OPENAI_API_KEY", raising=False)`를 `make_llm` 호출 앞으로 옮기거나(줄 87→85 앞) 옛처럼 `_openai_settings()`(가짜 키)를 넘긴다. 고친 뒤 확인: `OPENAI_API_KEY`에 가짜 값을 두고 `openai.OpenAI` 감시 플러그인으로 `tests/e0/test_sec3_live_guard.py tests/e3/test_llm.py`를 돌려 생성 0건.
- (경미, 병합 조건 아님) `eval/baseline_llm.py`: `_get_client()`가 `generate()`의 `try` 밖으로 나가서(`:141-146`), 플래그=1인데 키가 없으면 `RuntimeError("OPENAI_API_KEY가 없다")`가 그대로 전파된다(재현 확인). 옛 동작은 `{"ok":False,"error":"RuntimeError"}` 반환이었고 클래스 docstring(`:104`)은 "실패는 예외 대신 반환"이라 적혀 있다. 승인된 실행에서만 닿는 경로고 크게 실패하는 쪽이라 위험은 낮다. 의도라면 docstring을 맞추고, 아니면 `LiveCallLocked` 외에는 예전처럼 잡는다.
- (경미) 잠금 행의 `model`이 여전히 요청 모델명(`gpt-6-astra`)이다. `generator=none`·`status=error`·notes로 미생성이 드러나므로 표기 거짓은 아니다.
- (경미, 시험 강도) 변이 결과: MA2·MB·MC·MD·MF·MG·MH·MI·MJ는 잡힘(각 1~4건 실패). **ME(extract의 `raise`를 `pass`로)는 통과**: `test_disapere_extract_refuses_astra_when_locked`(`:127`)는 소스에 조건 문자열이 있는지만 본다. `cmd_extract`를 `argparse.Namespace(split="dev", generator="astra", ...)`로 실제 호출해 `SystemExit`를 단언하도록 바꾸면 된다(내가 쓴 동작 확인 스크립트가 그 형태). MK·ML(`llm._live_llm_allowed`·`baseline_llm`의 import 실패 분기를 True로)도 통과하나, 실제로 닿을 수 없는 방어 분기라 권고만 한다.
- (경미) `/health.llm.key_present`(참·거짓만)와 `effective:"openai_no_key"`는 `api/main.py:246-253`에서 정상 동작, 값 노출 없음(FAKE_KEY 본문 검색 0건). 이전 권고 9 해소.

### 4. `python scripts/verify.py` (worktree `9a20726`, `NEUMANN_LLM_PROVIDER=mock`, `PYTHONPATH="src;."`, venv python)

```
OPENAI_API_KEY 미설정: 1054 passed, 43 skipped in 77.69s
보안: 파일 361개 / 계약: 2개 / 테스트: 통과 / verify 통과 (exit 0)
```

- 참고 1: `OPENAI_API_KEY`에 가짜 키(시험 파일의 FAKE_KEY와 같은 값)으로 돌리면 테스트는 1054 통과지만 보안 스캔이 그 문자열이 든 파일 4곳을 [유출]로 표시해 verify가 실패한다. 스캔이 환경변수 값과 같은 문자열을 저장소에서 찾기 때문에 생긴 측정 방식의 산물이다(저장소 결함 아님). 다른 값의 가짜 키(또는 미설정)로는 통과.
- 참고 2: 이전 측정(1061 통과·26 건너뜀)보다 건너뜀이 늘었다(43). 건너뜀 사유는 `공유 데이터 폴더·원본 CSV 없음`, `NEUMANN_LIVE_TESTS`/키 필요 등 데이터·환경 조건뿐이고 SEC-3 시험은 건너뛰지 않았다. 이번 환경에서는 데이터 경로 변수가 없어 그런 것으로 보이며 원인을 더 파지는 않았다(전체 시험 수는 1087 → 1097로 +10).

### 5. 이전 권고 처리 현황

| 이전 권고 | 상태 |
|---|---|
| 6 강등 사유를 결과 notices에도 | 미반영(`log.warning`만). 실서비스가 플래그 없이 뜨면 화면에는 "mock provider(테스트용)"만 보이고 이유는 안 보임. 남은 권고 |
| 7 문서 어긋남 | 해소 |
| 8 8010 재기동 주의 | 더 엄격해짐: `.env`에 플래그를 둬도 **효과 없음**. HANDOFF·`_COMMON.md`에 서버 기동 명령(`NEUMANN_LIVE_LLM_OK=1` 포함)은 아직 없다. 재기동 전에 기동 명령에 넣고 `/health.llm.effective=="openai"`를 확인하도록 HANDOFF에 한 줄 남기기를 권한다 |
| 9 `key_present` | 해소 |

### 6. eb25703 (astra 금지, `git diff 9a20726 eb25703`)

변경: `config.py`에 `astra_allowed()`(프로세스 환경변수 `NEUMANN_ALLOW_ASTRA`만 봄)·`guard_model()`(모델명에 astra가 대소문자 무관으로 들어 있으면 `gpt-6.1-sol`로 교체), `llm.py`의 `_guard_model`·`make_llm`·`OpenAIProvider` 실제 클라이언트 분기, `eval/baseline_llm.py` 생성자, `/health.llm.model`(교체된 값)·`astra_allowed`, `tests/conftest.py`(라이브 시험은 `NEUMANN_LIVE_LLM_OK`도 있어야 돌고 환경의 astra 모델은 sol로 교체), 시험 추가, `AGENTS.md`·`.env.example`(이름만, 값 비움)·`docs/decisions.md` 한 줄.

측정 방법: 복사본(`git archive eb25703`)에서 옛 사용자 환경 재현(요청 모델 astra, provider=openai, 가짜 키, 허용 플래그는 이 스크래치 프로세스 안에서만 켬). `openai.OpenAI`를 대체 클래스로 바꾸고 `OPENAI_BASE_URL`을 닫힌 로컬 포트로 돌려, 실제 클래스가 만들어져도 네트워크에 닿지 않게 했다. 대체 클래스의 `responses.create`는 mock 응답기(`default_responders`)로 답한다.

**(1) 허용 플래그 없이 astra 모델이 실제 호출에 쓰일 경로가 남았는가: 제품 코드에는 없다.**

| 실제 호출 지점 | 가드 | 확인 |
|---|---|---|
| `src/neumann/llm.py:231,262` `OpenAIProvider` | `make_llm`(`:477`)에서 교체, 직접 생성해도 실제 클라이언트를 만드는 분기(`:227`)에서 교체 | 직접 생성(키+허용 플래그): 모델 `gpt-6.1-sol`. 변이 N2·N3 시험이 잡음 |
| `eval/baseline_llm.py:146,156` `OpenAIBaseline` | 클라이언트를 주입하지 않은 생성 시점에 교체(`:111-117`), 캐시 키도 교체된 모델로 잡힘 | 환경의 astra·명시 astra 모두 sol. 변이 N4 잡음 |
| `/health.llm.model` | `guard_model(...)`(`api/main.py:254`) | 변이 N6 잡음 |
| 그 밖 | `src/`·`eval/`·`scripts/`의 `.py`에 astra 모델 이름 리터럴 없음. API에 요청이 모델을 지정하는 경로 없음. 분석 캐시 키(`queries.py:109`, `extract.py:295`)가 모델을 포함해 옛 astra 캐시가 sol 실행에 재사용되지 않음. `eval/judge_run.py`의 `codex exec`는 `gpt-6-sol`(외부 CLI, 범위 밖) | grep |

우회하는 곳(시험만): `tests/e3/test_checklist_live.py:32`·`test_fitness_live.py:33`·`test_review_live.py:41`은 `OpenAI`를 직접 만들고 모델을 `os.getenv("NEUMANN_LLM_MODEL") or "gpt-6.1-sol"`로 정해 `guard_model`을 거치지 않는다. 이를 막는 것은 `tests/conftest.py`뿐이다. 시험 없이 conftest 로직만 실행해 확인했다(시험은 돌리지 않음): 라이브 시험 변수만 있고 허용 플래그가 없으면 라이브 시험 변수가 0으로 바뀌어 건너뜀 / 둘 다 있고 환경 모델이 astra(대소문자 무관)면 sol로 교체 / `NEUMANN_ALLOW_ASTRA=1`이면 유지. 다만 conftest 로직 자체를 검사하는 시험은 없다(변경해도 시험이 못 잡음). `tests/e3/test_fitness_live.py:60`에 "gpt-6-astra 호출" 주석이 남아 있다(주석만).

fail-open 여부: 교체 조건은 환경변수 하나(`.env` 안 읽음)이고, `llm._guard_model`·`baseline_llm`의 import 실패 분기는 astra를 sol로 바꾸는 닫힌 쪽이다. 그 두 분기를 뒤집는 변이(N8·N9)는 시험이 못 잡지만 닿을 수 없는 방어 분기다.

**(2) manifest·카드 `model`이 교체된 실제 값인가: 그렇다.** 요청 모델 astra, 허용 플래그 켠 스크래치 프로세스에서 `run_premortem` 끝까지(가짜 코퍼스):

```
manifest llm_provider/llm_model: openai gpt-6.1-sol
create에 넘긴 model 집합: ['gpt-6.1-sol'] | 호출 수: 14
카드 (generator, model): [(astra, gpt-6.1-sol)] | 카드 수: 4 | status: ok
결과 JSON 안 'gpt-6-astra' 문자열 0회, 'gpt-6.1-sol' 35회
```

`LLMResult.model`이 `self.model`(교체된 값)에서 나오고(`llm.py:236` `base`), 카드는 그 값을 받는다(`cards.py:242`, `pipeline.py:519`). `NEUMANN_ALLOW_ASTRA=1`이면 astra가 유지된다(확인). 참고: 카드 `generator` 값은 계약 이름 `astra` 그대로다(`docs/decisions.md`에 기록된 의도). 화면에 이 값이 "astra"로 보이면 모델이 아니라 생성 방식 이름이라는 뜻이다.

**(3) 주입한 가짜 클라이언트 경로가 이름을 유지하는가: 그렇다.** `OpenAIProvider(api_key=None, model="gpt-6-astra", client=<대역>)`: `name="openai"`, `model="gpt-6-astra"`, `config_error=None`. `OpenAIBaseline(model="gpt-6-astra", client=<대역>)`도 유지. `tests/e0/test_sec3_live_guard.py`의 `test_injected_client_keeps_model_name`·`test_baseline_replaces_astra`(셋째 단언)가 검사하고, 주입 경로에도 가드를 넣는 변이 N7은 시험 2건이 실패로 잡는다. `tests/e5/test_backtest_baseline_llm.py:92`처럼 주입 대역에 astra 이름을 쓰는 기존 시험은 verify에서 통과. 참고로 `tests/e3/test_llm.py`의 `test_make_llm_selects_provider`는 모델을 sol로 바꿨다(`make_llm`이 이제 교체하므로 의도된 변경).

변이 결과(복사본, 시험 54개 기준 통과): N1 가드 무력화 7건 실패, N2 `make_llm` 가드 제거 4건, N3 실제 클라이언트 분기 가드 제거 1건, N4 baseline 가드 제거 1건, N5 `astra_allowed` 항상 참 8건, N6 `/health` 가드 제거 1건, N7 주입 경로도 교체 2건 모두 **잡힘**. N8·N9(방어 분기)만 통과.

감시 시험 재실행(`eb25703` 복사본, 환경에 가짜 키): 시험 54개 통과, `openai.OpenAI` 생성 2건. ① `test_flag_opens_openai`(줄 86, **이전 1번 잔여, 아직 안 고쳐짐**: 환경 키를 집어 만듦) ② `test_direct_provider_real_client_path_replaces_astra`(줄 212): 시험이 넘긴 FAKE_KEY로 클라이언트만 만들고 호출은 없다(의도).

**verify on eb25703** (worktree, `OPENAI_API_KEY` 미설정, `NEUMANN_LLM_PROVIDER=mock`, `PYTHONPATH="src;."`, venv python; 전후 `git status` 깨끗):

```
1063 passed, 43 skipped in 65.18s
보안: 파일 361개 / 계약: 2개 / 테스트: 통과 / verify 통과 (exit 0)
```

새로 생긴 경미한 점: `guard_model`이 교체할 때마다 경고 로그를 남기므로(`config.py`) astra가 설정된 서버는 `/health`가 불릴 때마다 같은 경고가 쌓인다(권고: 한 번만 남기기).

### 남은 고칠 것

1. **(병합 조건)** `tests/e0/test_sec3_live_guard.py:84-88` `test_flag_opens_openai`: `delenv("OPENAI_API_KEY")`를 `make_llm` 앞으로(또는 가짜 키를 넣은 설정 객체 사용). 고친 뒤 확인: `OPENAI_API_KEY`에 가짜 키를 두고 `openai.OpenAI` 감시 플러그인으로 `tests/e0/test_sec3_live_guard.py tests/e3/test_llm.py`를 돌려, 생성이 `test_direct_provider_real_client_path_replaces_astra` 1건(시험이 넘긴 FAKE_KEY)뿐인지 본다.
2. (선택) extract 강등 시험을 소스 문자열 검사에서 `cmd_extract` 실제 호출로. baseline `generate()`의 키 없음 예외 처리 방침 결정. conftest의 라이브 시험 게이트에 시험 추가(현재 변경해도 못 잡음). 강등 사유를 notices에 남기는 권고 6, HANDOFF에 기동 명령 한 줄(권고 8).
