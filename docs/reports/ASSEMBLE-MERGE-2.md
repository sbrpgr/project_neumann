# ASSEMBLE-MERGE-2 — 채택 수정의 조용한 누락 제거

2026-10-01 KST. 시작 HEAD `39c7a01`(Claude가 `origin/main cda962f`, FIX-ASSEMBLE `f64f713`을 선행 병합). 병합·git 쓰기 명령은 실행하지 않았다. builder: codex-gpt-6.1-sol.

## 결과와 전후 측정

저장된 LIVE-SMOKE-3/4의 수정안 **24개를 전부 채택**하면 24개 모두 반영된다. 편집별 상태 24개, 변경 이력 24개, 미반영 0개다. 실제 제품 LLM 호출은 **0회**다.

| 입력·측정 | 전 | 후 |
|---|---:|---:|
| 원래 LIVE-SMOKE-4 gate-only 선정 22개(원 보고서) | 실제 반영 7개, 같은 줄 충돌 5건 | 이 작업의 직접 비교 기준과 입력 집합이 다름 |
| FIX-ASSEMBLE이 병합된 HEAD의 동일 라이브 24개 전체 채택 | 8개 반영 | **24개 반영** |
| 동일 24개의 직접 적용 / 구간 병합 / 별도 문장 보존 | 상태 계약 없음 | **13 / 0 / 11개** |
| 동일 24개의 같은 줄 충돌 | 5건 | **0건** |
| 동일 24개의 채택 미반영 / 건너뜀 | 충돌로 16개 미반영 / 0 | **0 / 0개** |
| 원문 / 수정본 줄 수 | 29 / 33 | 29 / **44** |
| 독립 구간 3개 합성 회귀 입력 | 같은 줄 전체 제외 | **3개 구간 병합**, 근거 3개 유지 |

선행 FIX-ASSEMBLE이 공유 추가 기록 재검사를 고쳤으므로 현재 24개는 각각 게이트를 통과한다. 옛 22개 선정값을 현재 코드의 재검사 통과 수로 인용하지 않는다. 위 전후 수치는 같은 입력과 결정으로 HEAD 소스를 메모리에서 실행한 결과와 작업본 결과를 비교했다.

## 구현

- `assemble.py`: 원문과 각 제안의 문자 차이를 구간으로 계산한다. 서로 겹치지 않는 구간은 원문 오프셋의 역순으로 적용하므로 앞선 삽입·삭제에 따른 위치 이동이 뒤 편집을 훼손하지 않는다.
- 겹치는 교체안은 삭제하지 않고 `insert_after` 방식으로 별도 줄에 보존한다. 순서는 원문 줄, revision의 카드·편집 순서다. 결정 POST의 나열 순서를 바꿔도 출력은 같다. 같은 위치 삽입과 교체 경계의 삽입은 보수적으로 겹침으로 취급한다.
- `edit_statuses[]`: `applied`, `merged`, `converted_insert`, `not_applied`와 사유·카드·원문 줄·수정본 범위·근거 id를 반환한다. 기각·미결정도 사유가 있는 `not_applied`이며 `stats.not_applied`에는 채택·직접 수정의 실패만 센다. 존재하지 않는 편집·줄, 낡은 원문, 빈 문안, 지원하지 않는 종류를 명시한다.
- 기존 화면이 표시하는 `notices`에 별도 문장 보존 안내와 채택 미반영 개별 사유를 넣었다. Markdown 이력과 DOCX에도 편집별 상태·사유 표를 넣었다. 화면 파일은 수정하지 않았다.
- B1 결합을 유지하기 위해 `changes.kind`, `old_text`, `new_text`, 카드·근거·rationale는 원래 편집의 정보를 유지한다. 실제 삽입 방식은 추가 필드 `effective_kind`, 전체 출력 줄은 `assembled_text`, 다듬기 전 개별 문안은 `applied_text`로 제공한다. 병합 줄의 `lines.edit_ids`에 모든 기여 편집을 담고 Markdown·DOCX 본문 각주에 전체 근거를 연결한다.
- 계약은 선택 필드만 추가했다. 옛 계약 예시·옛 응답도 계속 유효하다. models.py와 기존 서명·B1 검사 코드는 변경하지 않았다.
- polish는 기존처럼 요청했을 때만 실행하고 기존 숫자·자리표시·신규 사실·길이 관문을 통과해야 한다. 병합 줄에서는 내용 낱말을 삭제하는 다듬기도 거절하여 한 편집의 내용이 다듬기 과정에서 빠지지 않게 한다. mock polish 패키지도 검증했다.

## 검증 명령과 실제 출력

Python: `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `PYTHONPATH=src;.`. 실행기 `out/assemble_merge_check.py`는 커밋 제외 임시 파일이다. 실행 전에 OPENAI_API_KEY·NEUMANN_PSEUDONYM_SALT·라이브 플래그를 프로세스 환경에서 제거하고 provider=mock, Settings env_file=None으로 강제했다. 환경변수 값은 출력하거나 단언하지 않았다. 선택 검사 파일의 assert AST에서 환경변수 값 단언은 0개다.

| 명령·검사 | 실제 출력 |
|---|---|
| `python out/assemble_merge_check.py snapshot` | before: edits_total=24, applied=8, conflicts=5; after: applied=24, merged=0, converted_insert=11, not_applied=0; status_count=24 |
| `python out/assemble_merge_check.py -q tests/e3/test_assemble.py tests/e3/test_assemble_merge.py tests/e3/test_assemble_records.py tests/e3/test_revise.py tests/e3/test_finalize.py tests/e3/test_final_tools.py tests/e4/test_assemble_records_api.py tests/e4/test_assemble_merge_api.py tests/e4/test_revise_api.py tests/e4/test_export_pairing.py tests/e4/test_export.py tests/e4/test_finalize_api.py tests/e0/test_finalization_integration.py` | **273 passed in 6.48s**, exit 0 |
| `python out/assemble_merge_check.py security` | contracts **5개**, 보안 **파일 759개**, **verify 통과**, exit 0 |
| `git diff --check` | exit 0 |

회귀 fixture `tests/e3/assemble_live_smoke24.json`은 `data/final_test/live_smoke3/{plan.md,revision.json,analysis.result.json}`의 공개 출처·원문 오프셋·수정안 24개를 보존한 검사 입력이다. 실제 서버 서명과 리뷰어 신원 필드는 제거했고, 기록하기 전에 보안 패턴 검사를 통과했다. 원본 data와 다른 작업자의 worktree는 수정하지 않았다.

새 검사는 독립 구간의 길이 변화·각주 결합, 겹치는 구간·줄 전체 교체·같은 위치 삽입, 모든 미반영 사유, DOCX 사유 보존, 24개 전체 채택과 입력 불변성, 병합 기여 삭제 polish 거절을 실제로 검사한다. API 검사에서는 24개의 새 서명 조립본과 ZIP을 확인하고 상태 변조의 서명 실패, 정상 서명된 다른 세션·제안·rationale·결정·인용 결합의 HTTP 422, 구간 병합 정상 사슬의 HTTP 200을 확인했다.

## 한계와 인계

별도 문장 보존은 문안의 누락을 막는 결정적 적용 방법이며, 서로 모순되는 연구 설정을 의미적으로 해결했다는 판정은 아니다. 응답 알림에 문장 간 일관성의 최종 점검 필요를 표시한다. 실제 서비스 테스트와 실제 LLM polish는 수행하지 않았다. 브라우저·시험 서버·금지 포트·사용자 Chrome·데스크톱 도구를 사용하지 않았으며 새 화면 디자인도 없다. 전체 `verify.py`의 전체 pytest는 환경값 단언 테스트가 포함되므로 실행하지 않고, 지정 범위 mock 검사와 공식 verify의 보안·계약 검사를 실행했다.

하위 에이전트 위임 금지에 따라 별도 문맥 독립 검증은 하지 않았다. 빌더 자체 검사 결과이며, PM의 별도 작업 판정이 필요하다. 이를 독립 검증 완료로 기록하지 않는다.

git ACL 및 사용자 지시로 add·commit·merge·fetch·push·stash를 실행하지 않았다. **Claude가 현재 worktree의 아래 파일만 지정해서 커밋해야 한다.** 제목은 `[ASSEMBLE-MERGE-2] 채택 수정의 구간 병합·겹침 보존과 적용 상태`로 시작하고 실제 검사 결과와 `builder: codex-gpt-6.1-sol`을 넣는다.

1. `src/neumann/analyze/assemble.py`
2. `contracts/revised_plan.schema.json`
3. `tests/e3/test_assemble.py`
4. `tests/e3/test_assemble_merge.py`
5. `tests/e3/assemble_live_smoke24.json`
6. `tests/e4/test_revise_api.py`
7. `tests/e4/test_assemble_merge_api.py`
8. `docs/reports/ASSEMBLE-MERGE.md`
9. `docs/reports/ASSEMBLE-MERGE-2.md`

커밋·main 병합·라이브 최종 확인은 Claude/PM 인계 사항이다.

지정 PowerShell `Invoke-RestMethod -Method Post` / `ConvertTo-Json` 방식으로 Codex→Claude 메시지함 전달 **완료**: `kind=msg`, `id=m1790799637678`, `t=2026-10-01T05:20:37+0900`. 24개 반영·충돌 0·273개 mock 검사 통과·git 쓰기 없음·9개 파일 커밋 인계를 한 줄로 전달했다. 8099는 명시적으로 요청된 inbox POST에만 사용했다.
