# [FIX-AUTOFIX] 도구 계산값 연결과 코드 소유 확인 문구

판정: 오프라인 SEEDED 회귀에서 수정 적용 **0 → 4건**. 정확한 계산값 수정안 4건은 코드 도구 재검사도 **4/4 통과**했다. 최종 상태는 구조·의미 문제와 확인 필요 항목이 남아 `partial`이다. 라이브 재시험이나 모든 문제 해결을 주장하지 않는다.

## 원본과 재현 범위

읽기 전용 원본은 `out/codex/final-live/docs/reports/FINAL-LIVE-3C.md`와 `out/codex/final-live/data/final_test/final_live3c/finalize.json`이다. 확정 문안 1,666자, 도구 행 8개, 수정 제안 8개/적용 0개와 제외 사유 unsupported_number 4·placeholder_vocabulary 3·placeholder_malformed 1을 확인했다.

저장 finalize 응답은 거절된 replacement를 `[검사에서 제외된 수정안]`으로 지웠다. 별도의 assessment·correction 원응답 파일은 발견하지 못했다. 실제 모델 check 인자는 도구 evidence.input.check에서 회수했고, 서버가 붙인 quote는 모델 스키마 재생 전에 제거했다. 모델 issues는 저장 필드와 보고서의 C1/C2/C3 연결로 재구성했다. 수정문은 관측된 제외 사유 4/3/1을 재현하도록 **회귀검사용으로 재구성**했다. 따라서 원 correction 응답을 그대로 재생한 결과나, 지워진 각 제안의 정확한 실패 원인을 확인했다고 주장하지 않는다.

재구성 검사와 정확한 계산값 검사 모두 같은 저장 확정 문안과 실제 check 인자를 사용한다. 계산을 흉내 낸 값이 아니라 로컬 Z3·Pint를 다시 실행했다. HEAD의 기존 finalize.py는 `git show`로 읽어 메모리에서 실행해 전후를 비교했다. 원본 데이터는 수정하거나 커밋하지 않는다. 생성 방식: **Claude/Codex 오프라인**.

## 확정한 게이트 원인

- 접두사 불일치는 없었다. 기존 check_by_id에 selected + code_checks가 들어가고, rows_before에도 `code:…` 행이 들어간다. `tool:code:…`는 issue ID이며 check_ids의 `code:…`로 정확히 연결된다.
- 네 계산 실패 행 모두 details.computed가 있었다. 처리시간 27.7777777778, GPU시간 576, 일정 10개월, 예산 500000000원이다. 이 원본에서 expected/total/converted를 computed 대신 받아야 하는 필드 차이는 없었다. expected·stated는 기존 표기이며 계산 근거 숫자로 허용하지 않는다.
- 기존 _text_problem은 computed를 자리표시 안에서만 허용했다. 정확한 계산값을 본문에 쓰는 단위 수정안도 unsupported_number가 됐다.
- C-4의 코드 템플릿 치환은 placeholder_vocabulary/malformed 검사 뒤에 있었다. 앞에서 reason이 생기면 치환에 도달하지 못했다. 모델 issue가 check_ids를 비운 경우 같은 줄의 코드 계산값도 연결되지 않았다.

## 최소 수정

`src/neumann/analyze/finalize.py`에서 완료된 도구의 명시적 computed 스칼라만 공통 함수로 읽는다. 문자열 computed도 기존 FIN-TOOLS 조건 안에서 게이트와 템플릿이 동일하게 처리한다. params, expected, total, converted, 좌표, 실행 시간, 차이값, 비율 등 임의 숫자 잎은 계산 근거가 아니다(E-1).

본문 수치 허용은 해당 수정 줄에 출력 anchor가 정확히 일치하고, 검사 줄 전체가 issue 범위 안에 있는 **코드 선택 실패 검사**로 제한한다. Z3의 명시적 합계 등식과 Pint unit_derive만 대상이다. 분할 비율의 합계에는 수정할 출력 anchor가 없으므로 새 비율을 허용하지 않는다. 부등식 상한·unchecked 검사·다른 줄의 계산값도 허용하지 않는다. 모델이 check_id를 생략한 경우에도 이 엄격한 위치 조건으로 같은 도구 실패를 연결한다.

이 계산 실패에 연결된 제안이 unsupported_number 또는 placeholder_vocabulary/malformed로 거절되면 모델 수정문을 전부 버리고 원래 줄에 코드 소유 문구를 붙인다. 예: `[확인 필요: 계산 불일치 — 계산값 576GPU시간, 표기 500GPU시간]`. 숫자는 도구의 computed·stated/expected, 단위는 고정된 단위 표에서만 가져온다. 코드 생성과 연구자 확정 필요를 notices에 표시한다. 개인정보·마크업·새 기관·성과 주장·범위 밖 수정은 계속 거절한다. 일반 의미 문제의 기존 C-4 거절 조건은 유지한다.

## 전후 적용 수

| 검사 | 제안 | 적용 | 숫자를 실제로 고친 줄 | 코드 확인 문구 추가 | 해당 숫자 검사 재통과 |
|---|---:|---:|---|---|---:|
| 저장 라이브 FINAL-LIVE-3C | 8 | 0 | 없음 | 없음 | 0 |
| 기존 HEAD, 제외 사유 재구성 | 8 | 0 | 없음 | 없음 | 0 |
| 수정 후, 동일 재구성 | 8 | **4** | 14·15 | 36·44 | **2** |
| 수정 후, 정확한 도구 계산값 제안 | 4 | **4** | 14·15·36·44 | 없음 | **4** |

| 확정 문안 줄 | 기존 표기 | 정확한 계산값 검사에서 적용한 최종 문장 |
|---|---|---|
| 14 | 10시간 | 1억 개 샘플을 초당 1,000개 처리하면 27.7777777778시간이 걸린다. |
| 15 | 500 GPU시간 | GPU 8장 × 72시간 = 576 GPU시간을 쓴다. |
| 36 | 12개월 | - 총 연구 기간: 10개월 |
| 44 | 6억 원 | \| 합계 \| 500000000 원 \| |

재구성 검사에서는 일정 확인 문구 때문에 원 숫자 주장이 재추출되지 않아 unchecked, 예산 표는 기존 6억 원 주장을 유지하므로 failed다. 이 두 건은 **확인 문구 적용**이지 계산 오류 해결이 아니다. 정확한 계산값 제안 검사에서는 네 코드 검사가 모두 passed이고 관련 tool:code issues가 resolved다. 모델이 기존 500 등의 수치를 고정 인자로 잡았던 C1/C2/C3는 수정 후 unchecked로 남을 수 있으며, 이를 성공으로 바꾸지 않는다.

## 검증

모든 실행에서 지정 Python `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `PYTHONPATH=src;.`와 provider=mock을 사용했다. 테스트 전에 OPENAI_API_KEY·NEUMANN_PSEUDONYM_SALT·live 플래그를 프로세스 환경에서 제거했다. .env 로딩을 비활성화했으며 값 출력·환경변수 값 단언은 하지 않았다.

```powershell
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK,Env:NEUMANN_LIVE_TESTS -ErrorAction SilentlyContinue
$env:NEUMANN_LLM_PROVIDER='mock'
$env:PYTHONPATH='src;.'
& C:/Users/User/.venvs/neumann/Scripts/python.exe data/fix_autofix/replay.py
```

출력: before_reconstructed applied=0, 사유 4/3/1; after_reconstructed applied=4; after_exact_tool_values applied=4; socket_attempts=0; real_LLM_calls=0; regression=PASS. 로컬 replay.py와 측정 JSON은 무시된 data/fix_autofix에만 두었다.

```text
python -m pytest tests/e3/test_finalize_autofix.py tests/e3/test_finalize_gate.py tests/e3/test_finalize_code_checks.py tests/e3/test_finalize_combine.py tests/e3/test_finalize_vcomb.py -q
→ 최신 수정 포함 53 passed in 2.71s

python -m pytest tests/finalize tests/e3 tests/e4/test_export_finalization.py tests/e4/test_finalize_api.py tests/e4/test_finalize_c2.py tests/e4/test_finalize_ui.py tests/e4/test_finalize_vcomb_api.py tests/e4/test_finalize_browser.py -q -k 'not test_make_llm_selects_provider and not test_live_astra_expected_review_on_fixture'
→ 1203 passed, 17 skipped, 2 deselected in 146.82s
→ 이후 코드 생성 notice·anchor 경계 보강과 정상 placeholder 회귀 추가는 위 53개 검사로 다시 확인

NEUMANN_UI_TESTS=1 python -m pytest tests/e4/test_finalize_browser.py -q
→ 3 passed in 26.63s
```

본문 계산값·check_id 생략·문구 날조 폐기·잘못된 자리표시·임의 수치·PII/markup 차단·범위/unchecked 차단·분할 수치 임의 수정 금지·숫자 metadata 배제·저장 SEEDED 2가지 검사를 새 회귀에 포함했다. 기존 E-1·C-4 검사는 변경하지 않았다. 처음 새 검사가 예산 확인 문구의 상태를 unchecked로 예상해 실패했으며, 실제 failed가 유지됨을 확인해 테스트의 예상만 바로잡았다.

전체 e3 실행에서는 라이브 허용 플래그를 켜는 test_make_llm_selects_provider와 환경변수 값을 단언하는 test_live_astra_expected_review_on_fixture 두 검사를 사용자 금지에 따라 제외한다. 나머지 live/명시적 UI 검사는 기존 조건에 따라 skip이다. 별도의 브라우저 검사는 Playwright의 새 headless Chromium·8140–8169 중 빈 mock 포트만 사용했고, 생성한 시험 서버는 finally에서 종료됐다. 사용자 Chrome·탭·데스크톱 도구는 사용하지 않았다.

scripts/verify.py는 load_real_secrets가 .env를 읽으므로 실행하지 않았다. 전체 verify 통과나 병합 승인을 주장하지 않는다. 독립 검증자가 수행한 별도 작업 판정도 주장하지 않는다. 이 보고서는 빌더가 직접 수행한 검사 결과다.

`git diff --check` 통과. 세 변경 파일의 패턴 보안 검사는 verify.scan_text에 빈 secrets 목록을 직접 전달해 수행했다. load_real_secrets와 전체 verify는 호출하지 않았다. 실제 비밀값과 비교한 검사로 주장하지 않는다.

## 인계와 커밋

현재 브랜치 codex/fix-autofix. git 쓰기·stash·main 병합·push는 시도하지 않았다. 사용자 ACL 지시에 따라 **Claude가 커밋해야 한다**. 커밋 대상은 다음 세 파일이며 data 원본·측정 파일은 제외한다.

- src/neumann/analyze/finalize.py
- tests/e3/test_finalize_autofix.py
- docs/reports/FIX-AUTOFIX.md

권장 제목: `[FIX-AUTOFIX] 도구 계산값 수정 허용 및 코드 소유 불일치 문구 연결`. 본문 끝에 실제 검증 결과와 `builder: codex-gpt-6.1-sol`을 적는다. 원 correction 응답이 추가로 발견되면 같은 입력으로 정확한 원응답 재생이 다음 검증이다. 라이브 서버 재기동·최종 시험은 PM/대표 판단이며 이 작업에서 실행하지 않았다.

대시보드 메시지함에 사용자 지정 PowerShell POST로 한 줄 보고했고 `inbox_post_ok=true`를 확인했다. 첫 한글 본문 요청은 오류를 반환했으며, 동일 결과의 ASCII 본문으로 재시도해 성공했다. 첫 오류의 원인은 확정하지 않았다. 8099 연결은 이 명시적 보고에만 사용했다.

builder: codex-gpt-6.1-sol
