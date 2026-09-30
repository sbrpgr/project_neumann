# PKG-FINAL — 최종 점검 결과를 포함한 선택적 ZIP 내보내기

## 무엇을 했나

- 작업 브랜치: `codex/pkg-final`. 시작 기준 `origin/main` = `5093383`.
- `origin/main`의 `contracts/finalization.schema.json`과 `codex/fin-combine`(`ba9f440`)의 동일 계약·서명 발급 방식을 읽었다. fin-combine은 전체 응답에서 `finalization_sig`만 제외한 본문에 `finalization` 도메인으로 서명하고, 연구자 확정 문안에는 서명을 붙이지 않는다(F-8).
- `src/neumann/api/export.py`에 선택적 `finalization`, `finalization_sig`, `final_text` 입력을 추가했다. finalization이 없으면 기존 9파일/수정 권고 내보내기를 유지한다.
- 새 `export_finalization.py`가 계약·서명·결합 검사를 담당한다. 기존 B1 검사로 결과↔권고↔결정↔조립본의 세션·카드·근거·수정안·결정·서명된 각주를 검사한다. 최종 응답의 조립본과 별도 조립본이 같아야 하고, 서버 조립 문안은 점검 입력 문안·해시와 같아야 한다. 입력/출력 sha256, 최종 문안 중복 필드, 실제 적용된 자동 수정의 줄·원문·출력 재현도 확인한다.
- 구체적 결합 모순은 서명 유무와 관계없이 422다. 서명 누락·변조·다른 도메인·부모 서명 미확인은 `client_submitted_unverified`로 표시한다. 연구자 확정 문안은 유효한 서명이 잘못 붙었더라도 미검증으로 표시한다.
- ZIP에 `final_draft.md`, `finalization.json`을 추가한다. README에는 자동 수정 목록, 수정 전/재검사 도구별 상태, 미해결 쟁점과 마지막 검사에서 실패/미검사인 도구, 생성 방식·한계·공지·출처를 기록한다. manifest에 파일 크기·sha256·출처와 최종 점검 상태를 기록하고 응답에 `X-Neumann-Finalization-Origin`을 추가한다.
- Markdown의 HTML을 이스케이프하고 이메일·ORCID를 마스킹한다. 새 최종 점검 JSON에서는 신원 필드와 내보낸 서명 값을 제외한다. mock/비상 규칙은 사람이 읽는 생성 방식으로 표시하고 미검증 생성 표기를 보증하지 않는다.
- serving의 기존 요청 본문 **4 MiB** 상한은 바꾸지 않았다. 새 최종 점검 자료가 상한에 포함되어 ZIP 조립 전에 413으로 거절되는 회귀를 추가했다.
- 변경 범위는 export 구현, 전용 회귀 테스트, 이 보고서다. 계약·finalize 엔진/API·웹 UI는 수정하지 않았다.

## 호출자 연결 형식

`finalization`에는 **finalize 응답 전체**를 넣는다. 내부 inspection만 제출하는 경우는 서명된 전체 응답을 재구성할 수 없어 미검증으로 처리한다. 별도 서명과 최종 문안은 생략 가능하며, 제출하면 응답 내 값과 일치해야 한다.

```javascript
// finalResponse = 수정 확정·검증 API의 전체 응답
Object.assign(existingPackagePayload, {
  revised_plan: finalResponse.assembled,
  finalization: finalResponse,
  finalization_sig: finalResponse.finalization_sig,
  final_text: finalResponse.final_text
});
```

`existingPackagePayload`에는 동일 분석의 result/result_sig, revision/revision_sig, revision_decisions를 유지한다. 별도 revised_plan을 생략하면 finalResponse.assembled를 B1 검증에 사용한다. 오래된 통합본을 함께 보내면 422가 되므로 최종 응답의 조립본을 선택해야 한다.

## 완료 기준별 측정값

환경: 지정 Python `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `PYTHONPATH=src;.`, provider=mock. 테스트 실행 전 프로세스 환경에서 OpenAI 키·가명 솔트·live 호출/테스트 플래그를 제거했다. 환경변수 값 출력·단언 테스트와 실제 제품 API 호출은 없다. 테스트는 ASGI TestClient를 사용하며 서버 포트를 열지 않았다.

실행 명령:

```powershell
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e4/test_export_finalization.py tests/e4/test_export.py tests/e4/test_export_revision.py tests/e4/test_export_pairing.py tests/e4/test_export_plan_authority.py tests/e4/test_export_revision_dates.py tests/e4/test_export_raw_audit.py tests/e4/test_export_audit_shape_fuzz.py tests/e4/test_payload_signing.py tests/e4/test_finalize_api.py -q --tb=short
git diff --check
```

실제 출력: **176 passed in 6.21s**, `git diff --check` 출력 없음(종료 0). 최종 코드 변경 후 전용 회귀 재실행: **27 passed in 0.88s**.

| 완료 기준 | 측정 |
|---|---|
| 최종 ZIP·README·manifest·응답 출처 | 서명된 fixture에서 최종 2파일, 본문, 상태·자동 수정·도구 결과·미해결 요약, sha256·크기·출처 확인 |
| 실제 서명 발급 방식 호환 | mock `finalize.run_finalization`의 응답을 실제 package 라우트에 보내 `server_signed` 확인 |
| 결합 모순 422 | 최종 문안 별도 필드, 해시, 수정 원문/누락, 점검 입력, 서로 다른 조립본, 결정, 세션, 별도 서명, 잘못된 도구 형태 등 11개 반례 |
| 미검증 정직 표시 | 서명 누락·변조·다른 도메인·결과 서명 없음·조립본 서명 없음 5경로를 파일·manifest·헤더에서 확인 |
| F-8 | 연구자 문안이 조립 문안과 같은 경우/다른 경우 모두 유효 서명이 있어도 미검증 |
| 4 MiB | finalization에 상한 초과 자료를 넣으면 413, build_package 호출 0회 |
| 기존 내보내기 회귀 | 기존 9파일, 수정 권고, B1 반례, 계획서 권위, 날짜, audit 형태, 서명, finalize API 검사 통과 |
| 안전·결정성 | 고정 생성 시각의 ZIP 바이트 동일, HTML 이스케이프, 이메일 마스킹, 신원 필드 제외 |

## 못 한 것과 다음

- 사용자 지시대로 전체 `scripts/verify.py`와 라이브 테스트는 실행하지 않았다. 별도 작업·문맥의 독립 검증은 PM이 배정해야 한다.
- **커밋 차단:** 파일을 지정한 `git add`와 `[PKG-FINAL]` 제목의 `git commit`을 시도했으나 `fatal: Unable to create 'C:/Users/User/Desktop/project_neumann/.git/worktrees/pkg-final/index.lock': Permission denied`로 실패했다. 잠금 파일은 존재하지 않는다. 허용된 `.git` 폴더를 작업 디렉터리로 한 `git -C ... add`도 동일하게 실패했다. 따라서 커밋·staged 훅 검사는 실행되지 않았고, 네 파일은 현재 worktree의 변경 사항으로 남아 있다. 권한 변경·훅 우회·stash는 하지 않았다. PM이 실제 Windows/sandbox 쓰기 권한을 복구한 뒤 파일을 지정하여 커밋해야 한다.
- **UI 연결은 fin-combine/화면 담당 후속**이다. 읽은 main과 fin-combine의 `NeumannRevise.exportPayload()`는 아직 finalization을 보내지 않는다. 위 호출 형식으로 `state().finalization` 전체 응답과 그 `assembled`를 넘겨야 완성 화면 ZIP에 최종 2파일이 들어간다. export 범위 제한에 따라 화면을 수정하지 않았다.
- 서버 서명·B1 검사는 객체 무결성과 구체적 결합 모순을 확인한다. 실행 부모 계보 자체를 암호학적으로 증명하지 않으며, 점검 completed도 모든 과학적 오류의 부재를 보장하지 않는다. README·최종 초안에 제한과 미완료 상태를 표시한다.
- PM은 이 커밋을 선택 반영하고 UI 연결 후 별도 독립 검증·전체 통합 검증을 수행한다. main 병합·push는 하지 않았다.

builder: codex-gpt-6.1-sol
