# 보안 사고 기록 — 2026-10-01 03:4x KST, API 키가 테스트 출력에 찍힘

키 값은 이 문서와 저장소 어디에도 적지 않는다.

## 무엇이 일어났나

- PM 세션의 통합 빌더(INTEG-2)는 Codex CFG 커밋 `c0937f3`을 통합 브랜치 `integ/core2`에 병합한 뒤 그 범위의 대상 테스트를 돌렸다.
- `tests/e0/test_cfg1_proposal.py::test_auxiliary_cache_retains_only_allowed_tuner_keys`가 실패했다.
- pytest 실패 메시지(assert 비교 표시)에 **실제 `OPENAI_API_KEY` 값**이 출력됐다.

## 노출 범위

- 그 에이전트의 로컬 도구 출력(Claude Code 세션 기록, 이 PC의 사용자 폴더)뿐이다.
- 저장소 파일·커밋·push·보고서·scratch 파일에는 쓰이지 않았다. 빌더가 확인했고, 병합은 `git merge --abort`로 되돌렸다.
- 공개 저장소·외부 서비스로 나간 흔적은 없다.

## 원인

1. 테스트 fixture가 `OPENAI_API_KEY`를 환경에서 지우지 않은 채 `cfg.env_value("OPENAI_API_KEY") is None`을 단언했다. 실패하면 값이 그대로 출력된다.
2. `c0937f3`의 `env_value()`가 비밀값 키도 프로세스 환경변수에서 그대로 돌려준다(설계상 막았어야 함).
3. 에이전트 셸이 Windows 사용자 환경변수의 키를 물려받았다. 이 키는 실서버 기동용으로 대표가 설정했다.
4. 그 테스트 실행기가 자식 프로세스 환경에서 키를 제거하지 않았다. Codex 실행기 `run_job.ps1`은 제거한다.

## 조치

| 조치 | 상태 |
|---|---|
| 키 폐기·재발급 | **대표가 할 일**(AGENTS.md 규칙). 재발급 뒤 실서버(8020)는 새 사용자 환경변수를 받도록 새 프로세스로 다시 띄운다 |
| 기본 테스트에서 키·솔트를 환경변수에서 제거하고 저장소 .env를 읽지 않음 | main `f163183`(`tests/conftest.py`, `tests/e0/test_conftest_secrets.py`) |
| Claude 빌더·Codex 실행기가 자식 프로세스 환경에서 키·솔트·LIVE·ASTRA 플래그를 뺌 | 구축 세션이 지시했고, Codex `run_job.ps1`은 이미 적용 |
| `c0937f3`(CFG) 병합 금지 | 테스트 수정(키 제거, 참·거짓만 확인)과 `env_value()`의 비밀값 반환 차단 뒤 재검토 |
| 결정 기록 | `docs/decisions.md` 2026-10-01 03:4x |

## 재발 방지 규칙

- 테스트는 비밀값을 단언문에 직접 넣지 않고 참·거짓만 확인한다.
- 비밀값을 돌려줄 수 있는 헬퍼(`env_value` 등)는 비밀값 키를 거부한다.
- 모든 테스트 실행기는 자식 프로세스 환경에서 비밀값을 뺀다.
