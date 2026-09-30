# E4-L2f-authority-fix

Builder: `codex-gpt-6.1-sol` (PM 지정 실제 모델, medium). Worktree: `C:/Users/User/Desktop/project_neumann/out/codex/fix-export-authority`. Branch: `codex/export-plan-authority`. 시작 HEAD: `da5aba7e267e2e1297d9cec5ddae21eaaa1a0a4d`, 시작 작업 트리 깨끗함. 독립 FAIL 근거: `2b53611:docs/reports/E4-L2f.codex.verify.md`.

## 변경과 출처 범위

- 독립 원래 반례(`plan=None`, 유효한 결과 HMAC, `plan_text="different plan"`)를 먼저 재현했다. 이제 정규화·개인정보 마스킹 뒤 본문 해시가 결과의 `plan_id`와 다르면 API 422 / 직접 builder ValueError로 거절한다. 검증 불가능한 legacy id도 외부 본문을 승인하지 않는다. 오류는 입력 본문을 되돌려 보내지 않는다.
- `result_origin`과 `X-Neumann-Result-Origin`은 기존 결과 HMAC 판정 그대로다. 계획서가 없다고 진짜 결과 서명을 거짓으로 미확인 처리하지 않는다. 대신 `X-Neumann-Plan-Association`, export metadata의 `plan_association`·`plan_verified`로 입력 계획서 검증 범위를 구분한다.
- `signed_result_plan`: 결과 안 본문이 결과 HMAC 범위에 있음. `hash_verified`: 보조 본문의 정규화·마스킹 해시가 HMAC으로 확인한 결과의 plan_id와 일치. `missing`: 본문 없음, 검증된 입력 보증 없음. `unverified`: 결과 서명이 없거나 직접 프로세스 호출이며, 본문/id 일치로 서버 HMAC 보증을 대신하지 않음. verified는 앞 두 상태만 true다.
- 원래 `result.plan`이 있으면 기존처럼 그것을 쓰고 별도 `plan_text`를 무시한다. 서명 변조된 본문·결과는 계획서 검증 상태도 미확인이다.
- 4개 Markdown(README·주석·리포트·AI 맥락)에 계획서 연결 상태와 “결과 서명은 결과 JSON에만 적용”을 앞쪽에 적는다. 기존 결과 미확인 경고/제목의 첫 줄은 보존했다. evidence_pack·decision_log·manifest에도 동일한 계획서 상태를 담는다. risk_cards의 배열·CSV 형식은 유지하고 manifest의 각 기본 파일 항목이 동일한 출처/계획서 상태와 파일 SHA256을 기록하므로 기본 9파일 전체를 설명한다.
- E3-L2r의 추가 2파일은 별도 revision/revised-plan 서명을 계속 검사한다. 기본 입력 계획서의 검증 필드를 추가 파일에 덮어씌우지 않는다. 실제 결과 HMAC·revision HMAC·revised-plan HMAC을 사용한 mock 연결 검사에서 수정 권고→조립→11파일 ZIP을 확인했다.
- 수정 파일은 `src/neumann/api/export.py`, `tests/e4/test_export.py`, `tests/e4/test_export_plan_authority.py`, 이 보고서뿐이다. models/config/contracts/index.html/공통 docs는 수정하지 않았다. 기존 PII 검사에 사용할 보조 본문은 이제 그 본문의 실제 마스킹 해시에 맞는 fixture id로 설정한다. 마스킹 검사와 줄 번호 기대는 유지했다.

## 명령과 실제 출력

Python은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`. 모든 시험은 아래 helper를 거쳤다. helper가 두 슬롯 중 하나를 잡고 자식 프로세스의 OpenAI 키/live 허용 플래그를 제거하며 provider mock·live tests 0을 지정한다. 실제 OpenAI API 호출 0. `.env`/인증값/전체 환경변수 미열람. 서버·실서비스·다운로드·제품 데이터 생성 없음.

```text
<python> C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py -- <python> -m pytest <targets> -q -p no:cacheprovider --basetemp <전용 out/codex 경로> --tb=short
```

| 기준 | 실제 대상/실행 | 출력 |
|---|---|---|
| Red: 원래 반례와 출처 분리 | `tests/e4/test_export_plan_authority.py`, 수정 전, basetemp `authority-red-temp` | `10 failed in 0.77s`. 원래 different plan·변조 본문은 실제 200이어서 422 기대에 실패. 나머지는 새 상태/헤더 누락을 잡음 |
| Green: 대상 회귀 | `tests/e4/test_export_plan_authority.py tests/e4/test_export.py tests/e4/test_export_ui_sign.py tests/e4/test_export_revision.py tests/e4/test_revise_api.py`, basetemp `authority-green3-temp` | `116 passed in 3.62s`, exit 0, skip 0 |
| 원래 case/해시 불일치/변조/검증 불가 hash | 위 새 검사(11건)에 포함 | 외부 mismatch 2건·legacy id는 422. 원래 본문을 바꿔 계약 해시까지 갱신해도 옛 HMAC은 미확인 |
| 본문 없음/원래 signed body/외부 hash 일치/unsigned body | 새 검사 `test_result_signature_and_plan_authority_are_distinct_across_package` | 헤더·manifest·2개 JSON·4개 Markdown·모든 기본 파일 manifest 항목의 상태 일치. missing/unsigned는 plan_verified false. 정상 signed/서명된 id 해시 일치는 true |
| 원래 본문 우선/정규화·마스킹 | 새 검사 | 외부 unrelated plan은 원래 본문이 있을 때 무시. CRLF·이메일 포함 보조 본문도 정규화·마스킹된 해시로 연결하고 원 이메일은 ZIP 9파일에서 0건 |
| 실제 signed revise/assemble/export | 새 검사 `test_signed_hash_matched_export_revise_assemble_connection` | plan 없는 signed 결과+정상 보조 본문 → revise 200/server_signed/revision_sig → assemble 200/server_signed/revised_plan_sig 실제 검증 true → export 200/hash_verified, 11파일, revision origin server_signed·통합 Markdown 미확인 폴백 없음 |
| 의미 있는 변이 | helper로 별도 `python -c`에서 export._resolve_plan만 해시 검사 없는 함수로 교체한 뒤 `pytest.main(["tests/e4/test_export_plan_authority.py", "-k", "original_fail", "-q", "-p", "no:cacheprovider", "--tb=short"])` | `2 failed, 9 deselected, 1 warning in 0.15s`; `HASH_GUARD_REMOVAL_DETECTED=True`. 다시 200을 내는 변이를 두 422 검사가 잡음. 디스크 코드 변이 없음. 경고는 이미 import된 anyio assertion rewrite |
| 변경 형식 | `git diff --check` | exit 0, 출력 없음 |

중간 실패도 기록한다. 첫 Green은 테스트 편집이 비슷한 이전 줄에 적용되어 undefined body 1건과 PII fixture 해시 불일치 1건으로 `2 failed, 113 passed`였다. 정확한 두 테스트 위치를 고쳤다. 다음 연결 검사는 기존 revised_plan.md가 machine origin 문자열을 쓰는 것으로 잘못 기대해 `1 failed, 115 passed`였다. 실제 revised-plan 서명을 확인한 상태에서 Markdown의 기존 mock 생성 표시와 미확인 폴백 부재를 검사하도록 바로잡았고 최종 Green은 위 116건 전부 통과했다. 제품 출처 검사나 해시 거절 조건은 약화하지 않았다.

## 못 한 것·다음 (PM 인계 5줄)

1. 전체 `scripts/verify.py`는 PM 큐 전용이므로 실행하지 않았다. 커밋 훅은 유지한다.
2. 독립 `gpt-6-sol`은 안정 커밋에서 원래 반례·헤더·9파일·E3 연결을 재검증한다.
3. 별도 UI 소유자는 새 계획서 연결 헤더를 필요할 때 표시한다. index.html은 이 과제에서 수정하지 않았다.
4. 계약 파일 변경은 없다. PM이 원하면 새 export 메타데이터/헤더를 공식 문서·추가 스키마로 기록한다(제안).
5. main 병합/push/tag·HANDOFF/QUEUE/decisions는 PM 담당이며 실제 API·실서비스 시험은 수행하지 않았다.
