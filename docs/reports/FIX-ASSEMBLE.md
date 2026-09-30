# FIX-ASSEMBLE — 추가 기록 재사용으로 발생한 전체 채택 422 수정

2026-10-01 04:51 KST · 브랜치 `codex/fix-assemble` · builder: codex-gpt-6.1-sol

## 변경

`src/neumann/analyze/assemble.py::_regate_adoptions`에서 카드별 허용 집합을 **원래 카드 evidence ∪ (해당 카드 evidence_pool ∩ revision.records ID)**로 계산한다. `records`와 `evidence_pool`은 기존 revision 서명에 함께 포함되는 필드다. 추가 기록의 수치 대조는 제안별 인덱스 사본에서 수행하므로 앞선 제안이 공유 `index.excerpts`를 오염시키지 않는다. 다른 카드 인용·없는 기록·발췌 해시 불일치·근거 없는 수치 검사와 기존 서명 검증을 유지했다. API·계약·최종화 코드는 수정하지 않았다.

`codex/fin-combine` HEAD `ba9f440`의 assemble.py는 작업 시작 HEAD `96efc4d`와 동일했다(`git diff HEAD codex/fin-combine -- src/neumann/analyze/assemble.py` 출력 없음). 변경은 해당 검사 함수와 import에 한정했다. 다른 worktree는 수정하지 않았다.

## fixture와 재현

원본은 `C:/Users/User/Desktop/project_neumann/data/final_test/live_smoke3/`의 저장 JSON과 plan.md이며 읽기만 했다. `tests/e3/assemble_live_smoke3.json`은 카드 2개·수정안 2개·원래 발췌 2개·추가 기록 2개로 축소한 회귀 fixture다. 실패했던 `card_d3616b0df8c4/e1`, `/e3`의 문안과 줄 번호를 유지하고 두 rationale의 ID 목록을 공통 기록 `ex_2fc1f7e58d84a04a` 하나로 투영했다. 다른 카드의 별도 기록도 남겼다. 원래 라이브 서명은 포함하지 않았다.

발췌 4개는 공개 OpenReview 논문의 심사·저자 답변 기록이다. source_url과 실제 문장을 확인했고, 개인정보·리뷰어 신원 패턴 검사는 0건이었다. 저장 발췌의 text·start/end·SHA-256을 그대로 보존했으며 Excerpt 모델 검증을 통과했다. 공개 원문 전체와 다시 대조한 검증으로 주장하지 않는다. 전체 저장 응답·데이터 폴더·실행 로그는 커밋하지 않는다.

## 완료 기준별 측정

모든 실행에서 지정 Python `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `PYTHONPATH=src;.`, provider mock을 사용했다. 실행 전 OPENAI_API_KEY·NEUMANN_PSEUDONYM_SALT·라이브 플래그를 제거했다. 설정의 env_file을 비활성화했고 `.env`는 열지 않았다. 실행 대상 테스트의 환경변수 값 단언 AST 검사는 0건이었다.

| 기준 | 명령 / 실제 결과 |
|---|---|
| 수정 전 오류 재현(red) | `python -m pytest -q tests/e3/test_assemble_records.py` → **3 failed, 7 passed in 0.46s**, exit 1. 전체 채택·순서 검사·공유 인덱스 검사 모두 `proposed_text cites another card`로 실패 |
| 수정 후 회귀(green) | `python -m pytest -q tests/e3/test_assemble_records.py tests/e4/test_assemble_records_api.py` → **23 passed in 0.85s**, exit 0 |
| 전부 채택·순서 독립·인덱스 불변 | 축소 fixture는 적용 2개·충돌 0. 결정 순서와 revisions/edits/records 순서를 뒤집어도 생성 시각을 제외한 출력 전체 동일. 원본 입력·공유 EvidenceIndex.excerpts 불변 |
| 진짜 다른 카드 인용 차단 | 다른 카드 원래 발췌(풀에 억지 추가 포함)와 다른 카드 추가 기록은 정순·역순 모두 ValueError / HTTP **422 invalid_revision_proposal**. 대기열·예산 사용 0 |
| 발췌와 수치 검사 | 추가 기록의 0.25 수치는 정순·역순 모두 허용. 근거 없는 987654는 거절. 기록 해시 불일치도 거절 |
| HTTP 조립·내보내기 | 축소 fixture JSON·Markdown·DOCX가 정순·역순 모두 **HTTP 200**. 계약 테스트 서명으로 result/revision을 인증한 JSON 응답은 server_signed이며 revised_plan 서명 검증 통과. Markdown·DOCX의 추가 기록 인용 보존 |
| 저장 원본 24개 | `python C:/Users/User/Desktop/project_neumann/out/codex/fix_assemble_audit.py` → **24개 전체 regate PASS**, 단독 **24/24**, 원본 불변. 정순·역순 ASGI POST 모두 **HTTP 200**. 실제 네트워크·LLM 호출 0 |
| 관련 테스트 전체 | `python C:/Users/User/Desktop/project_neumann/out/codex/fix_assemble_verify.py` → **330 passed in 12.61s**, exit 0. revise·assemble·export·finalize·final_tools·jobs 포함 |
| 계약·보안 | 같은 검증 실행: **계약 5개 / 오류 0**, `python scripts/verify.py --security` → **보안: 파일 665개 / verify 통과**, exit 0 (이 보고서 추가 전). 최종 보고서 포함 재검사 결과는 아래 기록 |
| 패치 형식 | `git diff --check` → 출력 없음, exit 0 |

관련 테스트는 `tests/e3/test_revise.py`, `test_assemble.py`, `test_assemble_records.py`; `tests/e4/test_revise_api.py`, `test_assemble_records_api.py`, UI 이름을 제외한 `test_export*.py`; `tests/e0/test_finalization_integration.py`; `tests/e3/test_finalize.py`, `test_final_tools.py`; `tests/e4/test_finalize_api.py`, `test_jobs.py`다. 실행기는 `out/codex/` 아래의 커밋 제외 파일이다.

## 원본 전체 조립의 남은 충돌

저장 원본 전체 조립은 edits_total=24, applied=8, conflicts=5, skipped=0, undecided=0, placeholders=5다. 24개 모두 근거 검사를 통과했으나 같은 원문 줄을 교체하는 복수 제안은 기존 규칙대로 충돌 목록을 반환한다. 역순·짝홀순·edit_id 정렬의 3가지 순서에서도 통과 여부·stats·적용 ID 집합·충돌 내용은 동일했다.

원본에는 16행 뒤에 삽입하는 안이 2개 있다. 같은 줄의 insert_after는 기존 명세가 결정 순서를 유지하므로 전체 원본의 역순 조립 본문과 revised_plan_id는 달라질 수 있다. 이 의도된 순서 규칙은 수정하지 않았다. 순서에 따른 422 결함은 해소됐고, 축소 fixture의 출력 동일성은 별도로 검증했다.

## 못 한 것과 다음

실제 서비스 호출·실제 LLM 호출·라이브 최종화·브라우저 점검은 하지 않았다. HTTP 검사는 메모리 내 ASGI transport만 사용했고 서버나 포트 리스너를 기동하지 않았다. `scripts/verify.py` 전체 실행은 환경값을 단언하는 범위까지 실행하므로 이번 지시를 따라 실행하지 않고, 대상 330개 테스트·계약·보안 검사를 각각 수행했다.

이번 세션은 빌더 자체 검증이다. 하위 에이전트 금지 지시에 따라 별도 검증자를 띄우지 않았다. 독립 판정은 PM이 별도 작업에서 수행해야 한다(규칙의 기록 문구: “같은 모델(gpt-6.1-sol), 별도 작업 판정”). main 병합·push는 수행하지 않는다. PM은 이 커밋을 반영한 뒤 승인된 최종 라이브 테스트에서 전체 채택 이후 충돌 결정 → 최종화 흐름을 확인하면 된다.

최종 보고서 포함 `python scripts/verify.py --security`는 **보안: 파일 666개 / verify 통과**, exit 0이었다.

## 커밋 차단 — PM 인계 필요

지정 파일 5개를 대상으로 `git add -- src/neumann/analyze/assemble.py tests/e3/assemble_live_smoke3.json tests/e3/test_assemble_records.py tests/e4/test_assemble_records_api.py docs/reports/FIX-ASSEMBLE.md`를 실행했으나 **exit 128 / Permission denied**로 실패했다. 차단 경로는 `C:/Users/User/Desktop/project_neumann/.git/worktrees/fix-assemble/index.lock`이다. 남은 index.lock은 없었고, 해당 worktree 메타데이터 디렉터리·index의 Windows ACL에 Write Deny 항목이 존재함을 읽기만으로 확인했다. 세션 지시에는 .git 쓰기 허용이라고 되어 있지만 실제 Git 동작은 거절됐다. ACL·Git 메타데이터·훅을 우회하거나 수정하지 않았다.

후속 `scripts/verify.py --staged`의 “파일 0개 / verify 통과”는 스테이징된 변경이 없다는 의미이며 패치의 staged 검증 통과로 주장하지 않는다. **수정·회귀·보고서 작성은 완료, 스테이징·커밋은 미완료**다. 브랜치는 계속 `codex/fix-assemble`이며 위 5개 파일만 변경 상태다.

PM이 쓰기 가능한 세션에서 위 파일들을 지정해 add한 뒤 훅을 유지하며 커밋해야 한다. 준비된 메시지는 다음과 같다.

```text
[FIX-ASSEMBLE] Isolate card record gates during all-adopt assembly

validation: 330 passed; contracts 5, errors 0; security verify passed
builder: codex-gpt-6.1-sol
```

대시보드 인계는 지정 `Invoke-RestMethod` / `ConvertTo-Json` 명령으로 **완료**했다. 응답은 kind=msg, id=`m1790798018695`, 시각 `2026-10-01T04:53:38+0900`이었다. 수정 성공·330개 테스트 통과·기존 충돌 5건·커밋 Write Deny 차단·PM 커밋 필요를 한 줄로 전달했다.
