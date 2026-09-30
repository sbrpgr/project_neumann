# E4-L2f 독립 검증 — 고정 HEAD

**VERDICT: FAIL.** 핵심 서명·내보내기 경로는 통과했으나, 서명된 결과에 `plan`이 없을 때 다른 `plan_text`를 ZIP에 넣어도 패키지 출처가 `server_signed`로 남는다. 계획서 불일치가 포함된 패키지를 미확인으로 처리해야 한다는 이번 완료 기준을 충족하지 못했다. 이 경로는 통상 화면의 `result.plan`이 있는 경우와 다르며, ZIP 내부에는 해시 불일치 경고가 있다는 범위를 함께 기록한다.

- 작업 트리 `C:\Users\User\Desktop\project_neumann\.claude\worktrees\s2-E4-L2f`, 브랜치 `task/E4-L2f`. 검증 대상 HEAD `5ac22b5144cdd12c37f361a4a3555fe06ad70c6a`(`git rev-parse HEAD`). 시작 시 작업 트리 깨끗함. 대상 빌더 기록 `gpt-6.1-sol`, 검증자 PM 지정 모델 `codex-gpt-6-sol`.
- `AGENTS.md`, `docs/reports/E4-L2f.md`, 기존 `E4-L2f.verify.md`, `docs/tasks/QUEUE.md`, 읽기 전용 계획서 `00_구현_계획서.md`를 확인했다. E3-L2r 지정 HEAD `f8932e0`의 `revise.py`·`export_revision.py`·계약 경로를 Git 객체에서 읽기만 했다. E3와 E4 고정 HEAD는 미통합이다(`git merge-base --is-ancestor f8932e0 HEAD` → 아님).
- 제품 코드·테스트·기존 보고서 수정 없음. 별도 합성 검사 스크립트와 UI 사진은 저장소 밖 `C:\Users\User\Desktop\project_neumann\out\codex\`에만 있다. `.env`·인증값·키 값은 열거나 출력하지 않았다. 테스트 슬롯 도우미가 자식 프로세스의 provider를 mock, live tests를 0으로 지정하고 OpenAI 키·live 허용 플래그를 제거했다. 합성 HMAC 시험 값만 별도 프로세스에 줬다. 실제 OpenAI 호출 0건.

## 완료 기준별 명령과 출력

Python `C:\Users\User\.venvs\neumann\Scripts\python.exe`. 모든 표적 검사 명령은 `C:\Users\User\Desktop\project_neumann\out\codex\run_target_tests.py -- <command>`를 거쳤다. 전체 `scripts/verify.py`는 PM 전용 지시로 실행하지 않았다.

| 항목 | 실행·실측 | 판정 |
|---|---|---|
| 표적 회귀 | `<helper> -- <python> -m pytest tests/e4/test_payload_signing.py tests/e4/test_export_ui_sign.py tests/e4/test_export_ui.py -q -rs -p no:cacheprovider --basetemp <out/codex/e4l2f-verify-pytest-5ac22b5>` → **72 passed, 1 skipped in 1.03s**. Skip은 opt-in 브라우저 검사이며 아래에서 직접 수행 | PASS |
| generic bridge | 별도 Playwright `JSON.stringify`·Python `json.loads` 왕복: 작은 숫자/한글 정상 확인 `True`; 다른 purpose, payload 변조, 비ASCII 서명, 중첩 비문자 키, NaN, 1,200단계 중첩 확인은 모두 `False`(예외·500 없음). 정상 서명은 `v1.<64 소문자 hex>`이며 `neumann-revision-v1` 도메인과 result 도메인이 분리됨(위 표적 회귀). 임의의 의미상 잘못된 `{plan_id:"wrong"}`도 서명/검증은 `True`: 이 함수는 스키마·출처 관문이 아니므로 호출자가 먼저 검증해야 함 | 형식/무결성 PASS; 의미 검증은 호출자 책임 |
| 숫자 경계 | 실제 Chromium `JSON.stringify({amount:1e20})` → `{"amount":100000000000000000000}`. Python float 원본으로 서명한 뒤 이 브라우저 값을 재검증하면 `False`. 일반 작은 숫자 왕복은 `True`; 큰 숫자는 오인 인증 없이 미확인으로 닫히나 모든 JSON 숫자의 roundtrip 보장은 아님 | 제한 |
| R1·R2 | 표적 회귀의 비ASCII·전각·대문자·공백·길이 7종은 모두 200/unverified, 짧은 설정 키는 무작위 키로 교체되고 재시작 때 이전 서명 무효. 별도 nonASCII 패키지 요청도 `200 client_submitted_unverified`. 별도 프로세스에서 키 교체 후 기존 서명은 `200 client_submitted_unverified`, README·리포트·AI 문서 첫 줄에 미확인 경고 | PASS |
| R3·R4·M10 | 표적 회귀 72건에 자유형 dict 화이트리스트, 실제 결과 손실, 마크다운 링크·이미지 무력화, 정수/실수 정규화 검사 포함. 별도 `manifest`·`expected_review`에 합성 표식을 넣고 `build_ui_view`→ZIP: 원결과·ZIP 9파일 모두 표식 0건. 정상 ZIP 파일 9개 순서 `FILE_NAMES`와 동일 | PASS (현재 시험 입력) |
| 결과 출처 | 서명 정상 `200 server_signed`; `session_id` 변조 `200 client_submitted_unverified`, manifest도 같은 출처. 원결과 계약 검증 후 서명 확인하는 `/premortem/package` 코드 순서 확인 | PASS |
| 실제 UI | `<helper> -- <python> tests/e4/test_export_ui.py --port 8179 --out <out/codex/e4l2f-ui-verifier>` (프로세스 TEMP/TMP와 읽기 전용 `NEUMANN_DATA_DIR` 지정) → exit 0. POST `[/premortem/jobs,/premortem/package]`, ZIP 9파일, 결정 4건(채택 2·보류 1·기각 1), 정상 화면 `서버 서명 확인됨`, 비ASCII 서명 재내보내기 `확인 안 됨`, 샘플·원결과 없음 버튼 비활성. 스크린샷에서 내보내기 버튼·9파일 목록·출처 문구 육안 확인 | PASS |

첫 UI 시도는 작업 트리에 색인이 없어 `IndexNotBuilt`, 이어 체크리스트 0건으로 `AssertionError: 0`(exit 1)이었다. 저장소 공유 `data/index/manifest.json` 존재만 확인한 뒤 그 경로를 읽기 전용 데이터 설정으로 준 재실행은 exit 0이다. 재실행 로그는 임베딩 모델 미설정으로 **어휘 검색 강등**을 표시했다. 화면·ZIP 흐름 검증에만 썼고 분석 품질 검증으로 계산하지 않는다. 시험 서버 8179는 검사기가 자신이 띄운 프로세스만 종료했고 끝난 뒤 LISTEN이 없었다. 8010·8020·8099는 건드리지 않았다.

## 고정 HEAD 반례 — 계획서 출처

저장소 밖 합성 검사 `e4l2f_independent_probe.py`에서 계약에 맞는 fixture 결과의 `plan`을 `None`으로 바꾸고 `sign_result`로 서명했다. `/premortem/package`에 그 결과·서명과 해시가 다른 `plan_text="different plan"`을 보냈다. 출력:

```
fallback_plan_mismatch_status_origin 200 server_signed
fallback_plan_source plan_text (이메일·ORCID 가림)
fallback_plan_text_used True
fallback_mismatch_notice True
```

`export.py`는 `result.plan`이 없으면 요청자가 보낸 `plan_text`를 사용하고 해시 불일치를 ZIP 경고에 적는다. 그러나 `verify_result`는 서명된 `result`만 확인해 `X-Neumann-Result-Origin: server_signed`와 manifest의 `result_origin: server_signed`를 유지한다. README 첫 줄의 미확인 경고도 붙지 않는다. 결과 JSON 자체의 서명 판정은 맞지만 **ZIP에 쓰인 계획서 본문은 그 서명 범위 밖**이다. 사용자에게 패키지 전체가 서버 확인된 것으로 읽힐 여지가 있어 위 FAIL의 근거다. `result.plan`이 있을 때 다른 `plan_text`를 보내면 그 본문은 사용되지 않으며, 이 반례와 구별했다.

## E3-L2r 연결 범위

읽기 전용 지정 HEAD `f8932e0`의 `revise.py`는 E4 signing이 있을 때 `sign_payload("revision", out)`·`verify_payload("revision", body, sig)`를 호출한다. 수정 요청은 `PremortemResult` 계약·`plan_text`의 plan_id를 확인해 불일치면 422, 조립 요청은 revision 계약·plan_id와 근거 관문을 먼저 검사한다. `run_revision`은 입력 결과 서명이 확인된 경우만 수정 결과를 서명하고, `run_assembly`는 결과와 수정 권고 서명이 모두 확인된 경우만 통합본을 서명한다. `export_revision.py`도 수정 권고·통합본 계약과 plan_id를 먼저 확인한다. 이는 코드 경계의 정적 확인이며 **통합 실행 결과는 아니다**. E3 단독 HEAD에는 E4 `signing.py`가 없어서 래퍼는 서명을 `None`/검증 `False`로 처리한다. 두 브랜치 병합 뒤 E3 API·추가 ZIP 파일의 end-to-end 판정이 필요하다.

## 못 한 것·다음 (PM 인계)

1. E3-L2r+E4-L2f 통합본의 revision 생성·조립·추가 ZIP 경로는 이 고정 HEAD에서 실행하지 못했다. PM 통합 뒤 별도 검증한다.
2. PM은 불일치 보조 계획서를 422로 거절하거나 계획서 출처를 미확인으로 별도 표기·패키지 상위 문구에 반영하도록 결정하고, 위 반례를 회귀 시험에 넣어야 한다.
3. 일반 브라우저 숫자 왕복은 통과했지만 `1e20` 같은 큰 숫자는 미확인으로 닫힌다. E3 계약에서 이런 숫자를 허용하는지 통합 때 확인한다.
4. 전체 `scripts/verify.py`, 실제 OpenAI, 실서비스, 과부하 시험은 하지 않았다. PM의 병합 관문에 남긴다.
5. main 병합·push·tag와 공통 HANDOFF/QUEUE/decisions 수정은 PM 담당이다. 이 보고서 한 파일만 커밋한다.
