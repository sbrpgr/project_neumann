# VER-B — B1(결합 검증)·B2B3(audit 형태·기준선 재시도/캐시 키) 독립 검증

- 검증자: Claude Sonnet 5.5(빌더 B1 `claude-fable-5.1`, B2B3 `claude-opus-5.5`와 다른 모델). 2026-10-01 03:3x~03:5x KST.
- 대상: `task/B1-pairing` @ `0c53f08`, `task/B2B3` @ `b1bd7fa`(둘 다 기준 `f54ef1d`). main = `39055d1`(core-final + finalization 병합, `origin/main`은 아직 `4af816e`라 미push).
- 환경: 모든 python 명령 `NEUMANN_LLM_PROVIDER=mock`·`OPENBLAS_NUM_THREADS=1`·`NEUMANN_LIVE_TESTS=0`, `env -u OPENAI_API_KEY -u NEUMANN_PSEUDONYM_SALT -u NEUMANN_LIVE_LLM_OK`. `.env` 열람 0, 환경변수 값 출력 0, `NEUMANN_LIVE_LLM_OK` 설정 0(B3 탐침은 환경변수 대신 가드 함수만 가로챔), 실제 OpenAI 호출 0, 서버 포트 0(TestClient). 커밋·stash 없음. 전체 pytest 로그에서 키 모양 문자열 0건(개수만 검사).

## 판정

| 브랜치 | 판정 |
|---|---|
| B1 `task/B1-pairing` | **PASS-조건부(polish 적용 통합본은 제안 문안 일치 검사를 건너뜀 — 빌더가 §7에 적은 한계이며 재현됨. 병합은 가능, 후속으로 문안 해시 또는 발급자 측 상위 해시 권장)** |
| B2B3 `task/B2B3` | **PASS** |
| 병합 충돌 | **없음**(B1→main, B2B3→main, B1↔B2B3, 세 가지 모두) |

## 1. 병합 가능성

| 명령 | 결과 |
|---|---|
| `git merge-tree --write-tree --name-only main task/B1-pairing` | rc 0, 충돌 없음 |
| `… main task/B2B3` | rc 0, 충돌 없음 |
| `… task/B1-pairing task/B2B3` | rc 0, 충돌 없음 |
| 스크래치 worktree `main`(39055d1) + `git merge --no-edit task/B1-pairing` + `task/B2B3` | 두 병합 모두 자동 성공(ort). 둘 다 `src/neumann/api/export.py`를 고치지만 겹치는 줄이 없다 |

- 의미 충돌 점검: main이 f54ef1d 이후 더한 것은 `finalize`·`samples`·UI이고 `export*.py`·`revise.py`·`eval/`은 건드리지 않았다. 병합 결과에서 새 테스트 48건(pairing 30 + fuzz 8 + 기준선 10 포함) 모두 통과.
- 두 브랜치 diff에 비밀값·`.env`·`data/`·가중치·`git diff --check` 문제 0건.
- 병합 결과에 `codex/e5-baseline-calltime-guard`(58b56fb)는 따로 넣지 않았다. B2B3가 cherry-pick(`fa60f0e`)으로 포함하므로 별도 병합하면 충돌한다(B2B3 보고서 지시 그대로).

## 2. 대상 테스트(병합 트리, mock)

`tests/e4/test_export_pairing.py test_export_audit_shape_fuzz.py test_export.py test_export_plan_authority.py test_export_raw_audit.py test_export_revision.py test_export_revision_dates.py test_export_ui.py test_export_ui_sign.py test_payload_signing.py test_revise_api.py test_finalize_api.py`, `tests/e3/test_assemble.py test_revise.py`, `tests/e5/test_baseline_calltime_guard.py test_baseline_retry_cache_identity.py test_backtest_baseline_llm.py`, `tests/e0/test_sec3_live_guard.py`.

| 실행 | 결과 |
|---|---|
| 1회(`-x`, 다른 에이전트 부하 중) | 223 통과 후 **1 실패**: `tests/e4/test_finalize_api.py::test_http_timeout_is_explicit_and_replay_does_not_repeat` — `/premortem/revise`가 504(전체 88초, 부하) |
| 2회(같은 묶음, `-x` 없이) | **372 passed, 3 skipped, 10.9초** |
| 위 실패 1건 단독 3회 | 3회 모두 `1 passed`(0.9~1.4초) |

실패 1건은 main의 finalization 테스트이고 B1·B2B3가 건드리지 않은 코드 경로다(시간 제한 단언, 부하 의존 — 알려진 종류). 단독 재실행 통과.

## 3. B1 독립 반례(`scratchpad/probe_b12.py`, 빌더 테스트와 다른 변형 포함)

서명 키는 프로세스 무작위, `/premortem/package`에 result·revision·revised_plan·decisions를 섞어 보냄. "미서명"은 422이거나 200이어도 통합본이 `server_signed`가 아님.

| 사례 | 결과 |
|---|---|
| P0 정상 결합 | 200 · revision·통합본 `server_signed` |
| C1 세션만 바꾼 결과(재서명) + 옛 권고·통합본(A3식) | **422** `수정 권고의 session_id가 결과의 session_id와 다르다` |
| C1b 위험카드 id 전부 바뀐 결과(재서명)(A3식) | **422** `카드 card-fx-leak가 결과의 위험카드에 없다` |
| C2 같은 결과의 다른 카드 부분집합 권고(서명) + 옛 통합본(A4식) | **422** `수정 권고에 없는 edit_id` |
| C3a 결정 `[채택, 기각]`(마지막 기각) vs 채택 통합본(A5식) | **422** `결정(기각)이 통합본에 적용된 결정(채택)과 다르다` |
| C3b 결정 `[기각, 채택]`(마지막 채택) | 200 · `server_signed`(정상, 마지막 결정 기준) |
| C3c 기각 결정 vs 채택 통합본(A5) | **422** |
| C8 다른 수정안을 채택한 통합본(자기 서명 유효) + 첫 채택 결정 | **422** `통합본에서 미결정인데 결정(채택)이 왔다` |
| C8b 그 통합본 + 일치 결정 | 200 · `server_signed` |
| C9 같은 발췌 id·같은 길이·다른 글자(text·sha 재계산, 재서명 결과) + 옛 통합본(A6식) | **422** `발췌 ex_c5986bb2facc61b2의 인용문이 서명된 통합본의 각주와 다르다` |
| C5a 권고 없이 통합본·결정만 | 422 `revision 없이 revision_decisions만 왔다` |
| C5b 권고만 | 200 · revision `server_signed`, 통합본 없음 |
| 조립 `run_assembly`: 서명된 다른 세션 결과 + 서명된 옛 권고 | `origin=client_submitted_unverified`, **`revised_plan_sig=null`**(서명 발급 안 함) |
| **C4** polish 적용(`polish.applied=true`) 통합본 + 같은 edit_id·**다른 제안 문안**으로 재발급한 권고(서명) | **200 · 통합본 `server_signed`**(검출 못 함). 같은 조합을 `polish=False` 통합본으로 만들면 **422** `문안이 수정 권고의 제안 문안과 다르다` |

- 조립 HTTP 경로(`POST /premortem/revise/assemble`)는 입력 관문 티켓(main의 core-final E3-L1s)이 없어 503이라 탐침에서 직접 못 불렀다. 같은 서명 발급 함수 `run_assembly`로 대신 확인했고, 저장소의 `tests/e4/test_revise_api.py`·`test_export_pairing.py`(조립 API 서명 안 함)는 통과.
- 화면 흐름 거짓 양성 점검: 화면(`index.html`)이 보내는 모양(한글 `채택/기각/수정`, `decided_at`·`note`·`revised_text`, 일부만 결정, 결정 없음, 자리표시 입력 수정)을 그대로 서버 조립 + 내보내기에 태운 6가지 모두 **200 · 통합본 `server_signed`**(거짓 422 없음). 같은 줄에 수정안 둘이 있는 충돌 사례는 fixture에 없어 재지 못했다.
- 빌더 자체 변이 검사(검사 6개 각각 끄면 반례 통과, 전체 무력화 시 21건 실패)는 빌더 보고값을 신뢰하되 테스트 6/6 통과를 병합 트리에서 확인.

### B1 조건(PASS-조건부 사유)
1. **polish 적용 통합본**: `polish.applied`가 참이면 채택 문안·수정 문안 문자열 일치 검사를 건너뛴다(`export_revision.py` 267·303행 부근). `polish` 값은 서명된 통합본 본문 안이라 위조는 서명을 깨뜨리지만, 같은 계획서·같은 edit_id로 정상 서명된 권고가 둘 있을 때(재생성) 다듬은 통합본과 다른 권고가 `server_signed`로 함께 나간다. 이 경우 카드·줄·원문·근거 id·이유·인용은 여전히 검사된다. 빌더 보고서 §7에 "한계"로 적혀 있고 A3~A6 감사 반례 자체는 모두 막혔으므로 병합 차단은 아니다. 후속: 권고 제안 문안의 해시를 통합본 서명 범위에 넣거나(계약 추가, PM 승인) 다듬기 적용본은 `quotes`처럼 "미확인" 사유를 README에 남기는 것.
2. 한계(빌더 §7, 재확인 불필요): 교차 검증은 모순 탐지이며 정확한 부모 증명이 아님 — 카드 제목만 바꾼 재서명 결과처럼 id·유형·근거가 같은 경우는 구분하지 않는다(이번에 별도 탐침하지 않음).

## 4. B2 독립 탐침(`expected_review.audit`은 `result` 안에 있음 — 요청 최상위 `expected_review`는 422 extra_forbidden)

서명·미서명 두 경로 모두, `raise_server_exceptions=False`로 500을 그대로 보이게 함.

| 입력 | 결과 |
|---|---|
| `dropped_reasons` = `1`, `[1]`, `1.5`, `None`, `{a:{b:1}}`, `{a:"9"*400}` | 전부 **200**(500 없음), 값 버리고 이름만 `dropped_keys` |
| `dropped` = `5`, `[[1]]`, `[None,[]]`, `[{}]` | 200 |
| `drop` = `"x"`, `[1]`, `1e30`, `-1`, `true`; `gen`/`pass` = None | 200 |
| `no_evidence_reasons` = `5`, `[[1]]`; `linked_rate` = `"nan"`, `[1]` | 200 |
| 모르는 필드(`zzz:{a:1}`, 이름 "없는필드" + 10만 자 값) | 200 · 리포트에 `zzz`·`dropped_keys`(이름만) 기록 확인 |
| 중첩: `audit.zzz` 깊이 30 | 200 |
| 중첩: 깊이 63·64·65·200·1200(요청 전체 기준이라 래퍼 3~4단 더함) | **422** `package_limits` "요청 JSON 중첩이 너무 깊습니다(최대 64…" |
| 원문 바이트 폭탄: audit 안 2,000단 / 100,000단 | **422 / 400**(500 아님) |
| 원문 `{"result": [[[…]]]}` 2,000단 / 100,000단 | 422 / 400 |
| `result` 안 깊이 70 + 잘못된 서명 | 422 |

500은 0건. 정상 audit 값 보존·재통과 동일 모양·퍼징 300건·깊이 63/65 경계는 빌더 테스트(`test_export_audit_shape_fuzz.py` 8건)가 병합 트리에서 통과.

## 5. B3 독립 탐침(`scratchpad/probe_b3.py`, 합성 SDK·환경변수 미설정, `_require_live_call`·`_guard_model`만 가로챔)

| 사례 | 결과 |
|---|---|
| 1a 요청 모델 astra, 가드 sol | 실제 SDK 호출 모델 `gpt-6.1-sol` |
| 1b 캐시 파일명 | `sha256(openai\|gpt-6.1-sol\|effort\|prompt_version\|plan_id)` 와 일치(sol 키) |
| 1c 같은 설정 재실행 | 캐시 적중, SDK 1회 |
| 1d astra 허용으로 바뀌면 | astra 키로 별도 호출·별도 파일 |
| 1e astra 재철회 | sol 키 적중, 추가 호출 없음 |
| 2a effort 다르면 | 키 다름(식과 일치) |
| 2b mock provider | 키 ≠ openai 키(식과 일치) |
| 2c 요청 모델 이름만 다른 두 공급자(astra/sol, 권한 없음) | 같은 실효 키·SDK 1회·파일 1개 |
| 3a~c 첫 응답 "쓸 수 있으나 3문장" → 재시도 전 승인 철회 | `ok=False`·`output=None`·`locked=True`·캐시 파일 0·SDK 1회, 행 `status=error`·위험 0 |
| 3d 승인 복구 후 재실행 | 잠긴 결과를 재사용하지 않고 새로 호출, 성공·캐시 기록 |
| 4 첫 시도부터 잠김 | SDK 0회·`ok=False`·캐시 0 |
| 5a sol 키 파일 안에 `model_actual=astra` 기록 | 재사용 안 함·재호출 |
| 5b 깨진 JSON 캐시 파일 | 예외 없이 재호출 |
| 5c `locked=True` 옛 기록 | 재사용 안 함·재호출 |

16개 모두 기대대로. `eval/` 안에서 `cache_key(provider…)`를 쓰는 곳은 `baseline_llm.py` 내부뿐(`identity_cache_key`로 통일)이라 호출부 불일치 없음.

## 6. 전체 pytest(병합 트리 1회)

`python -m pytest -p no:cacheprovider -q tests` → **2414 passed, 56 skipped, 0 failed, 149.2초**(rc 0). 이번 실행에서는 시간 단언 실패가 한 건도 없었다(부하 낮음). 앞선 대상 테스트 1회차의 실패 1건(`test_finalize_api` 504)만 부하 탓으로 기록했고 단독 3회 통과. (B2B3 보고서가 적은 시간·동시성 실패 4건, B1 보고서의 5건은 이 조건에서 재현되지 않음.)

## 7. 정리·남은 것

- 스크래치 worktree(`scratchpad/wt_b`) 제거, 탐침 스크립트는 scratchpad에만 있고 저장소 파일 변경 없음(이 보고서 제외, 미커밋).
- 못 한 것: 브라우저 실행 화면 확인(이번 범위 밖), 실서비스·실 OpenAI(금지), 조립 HTTP 경로 직접 호출(관문 티켓 필요), 충돌(같은 줄 2수정안) 화면 흐름.
- 다음(PM): ① B1·B2B3 병합 순서 자유(충돌 없음), 병합 뒤 `scripts/verify.py` 1회. ② B1의 polish 조건을 후속 과제로 기록(`docs/decisions.md` 한 줄 권장). ③ B2B3 병합 시 `codex/e5-baseline-calltime-guard`는 목록에서 뺀다.
