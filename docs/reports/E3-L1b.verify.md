# E3-L1b 검증 보고서 — 예방 체크리스트(astra) + 2차 의미검증

- 검증자: Claude Sonnet 5.5 (빌더 Claude Opus 5.5와 다른 모델) · 검증일 2026-09-30
- 대상: 브랜치 `task/E3-L1b` (커밋 `2fbd01e`, worktree `.claude/worktrees/agent-a002729386fd7d211`), 빌더 보고서 `docs/reports/E3-L1b.md`
- 코드 수정·git 쓰기 없음. 조작 실험은 worktree 밖 임시 폴더의 사본에서만 했다(worktree에 남긴 파일 없음, `git status` 깨끗, `.pytest_cache/`는 시작 전부터 있던 무시 대상).
- 환경변수는 `_COMMON.md` 그대로(`PYTHONPATH="src;."`). 키 값은 출력하지 않았고 `bool(OPENAI_API_KEY)`만 확인했다(True).

## 최종 판정: **PASS**

병합 전 고칠 것 없음. 아래 "참고(병합을 막지 않음)"는 파이프라인 연결(E3-L0)과 E4 화면 때 챙길 것이다.

## 완료 기준 재측정

| # | 항목 | 실행한 명령 | 실제 출력(핵심) | 결과 |
|---|---|---|---|---|
| 1 | `tests/e3` 전체 | `python -m pytest tests/e3 -q -p no:cacheprovider` | `27 passed, 2 skipped in 0.75s` (skip 2건은 `NEUMANN_LIVE_TESTS` 없을 때의 라이브 테스트) | 통과 |
| 2 | `verify.py` | `python scripts/verify.py` (task/E3-L1b worktree) | `253 passed, 2 skipped` · `보안: 파일 137개` · `계약: 2개` · `테스트: 통과` · `verify 통과` | 통과 |
| 3 | 가짜 llm_call: 없는 줄 번호 제거 | 자작 스크립트로 `plan_lines=[16, 99, 29, 0, -3, 2(빈 줄), "17", True, 16.0, None, 1e9, [16], {"a":1}]` 주입 (계획서 28줄) | 남은 줄 `[16]`, 나머지 12개는 `dropped.plan_lines`에 기록. 남의 excerpt id(`ex-not-mine`, `zzz`, 5, None)도 `dropped.evidence`로. 전부 무효(`[500,-1,"3"]`)면 카드 인용 줄 `[16,17]`/`[22]`로 잇고 `plan_lines_source="card"`. 카드 줄까지 무효면 `[]`, source `none`. 남은 모든 줄이 실재·비어있지 않음을 assert | 통과 |
| 4 | 가짜 llm_call: 카드 '틀림' → 삭제 없이 강등, 행동 유지 | `card-fx-leak`만 `mismatch`, 행동은 `match`로 응답 | 카드 2장·항목 4개 그대로(삭제 없음). `demoted_cards=['card-fx-leak']`, `demoted_actions=[]`, 항목 C1·C2는 `card_verdict=mismatch`인데 `validation.verdict=match, demoted=False`. `notices`에 강등 한 줄, 입력 결과 객체는 변형되지 않음(직렬화 비교). 반대 방향(카드 match·행동 전부 mismatch → `demoted_actions=[C1..C4]`, 항목 4개 유지)도 확인. 전부 mismatch여도 카드 2장·항목 4개 유지 | 통과 |
| 5 | 가짜 llm_call: 실패 시 `generator=rule` + degraded (체크리스트) | 응답 None / 예외(`TimeoutError`) / dict 아님 / `{"cards":"x"}` / `{"cards":[]}` / llm_call=None 6가지 | 6가지 모두 전 항목 `generator="rule"`, `model=None`, `fallback_reason`(`llm_failed`·`llm_exception:TimeoutError`·`llm_invalid_response`·`llm_missing_card`·`llm_unavailable`), 단계 `degraded`·impl `fallback:rule_actions`, 결과 `status="degraded"`. 카드 7장/3묶음에서 가운데 묶음만 실패시키면 그 3장만 rule(C4~C9), 나머지는 astra, 단계 `degraded`("카드 3/7장 규칙 문구로 대신함"). 순서·item_id(C1..C10)는 병렬에서도 결정적 | 통과 |
| 6 | 가짜 llm_call: 실패 시 검증 표기 | 응답 None / dict 아님 / `{"cards":5}` / 빈 cards / 예외(`RuntimeError("secret-boom")`) | 전부 카드·행동 `unverified`, `judge="none"`, 검증 `status=degraded`, 결과 `status ok→degraded`, `notices`에 사유. 예외 메시지 본문은 어디에도 안 남고 형(`llm_exception:RuntimeError`)만 남음. 규칙으로 '맞음'을 흉내 내는 경로 없음 | 통과 |
| 7 | 인용 줄이 없는/없는 줄뿐인 카드 | 카드 인용 줄 `[99, 2]`(범위 밖 + 빈 줄), LLM은 전부 `match` | 카드 판정 `weak`, `judge="rule"`, `cited_lines=[]`, `dropped_lines=[99,2]`. 모델이 '맞음'이라 해도 상한 약함 | 통과 |
| 8 | 엉뚱한 응답 무시 | 카드 verdict `"MISMATCH"`(enum 밖) + 없는 item_id `C999` | 카드 2장·행동 4개 모두 `unverified`(`judge=none`), 상태 degraded. 남의 카드 밑 item_id·enum 밖 판정은 채택되지 않음 | 통과 |
| 9 | 실제 astra (`NEUMANN_LIVE_TESTS=1`) | `NEUMANN_LIVE_TESTS=1 python -m pytest tests/e3/test_checklist_live.py -s -q` (키 존재 True, 값 미출력) | `2 passed in 33.95s`. 체크리스트 호출 15.8s(in 1404/out 752 tok) → 항목 4개 전부 `gen=astra`, 줄 전부 실재·`(llm)`, `dropped` 비어 있음, 단계 `ok`. 의미검증 호출 11.5s → 카드 2장 `match`, 행동 4개 `match`, 단계 `ok`. 음성 대조: 해당 이유를 다른 내용·인용 5~6행으로 바꾼 카드는 astra가 `mismatch`("16~17번 줄과 반대"), 그 카드의 타당한 행동은 `match`로 남고 `len(checklist)==1` | 통과 |
| 10 | 소유 경로 밖 변경 | `git diff main...task/E3-L1b --stat` | 6개 파일뿐: `docs/reports/E3-L1b.md`, `src/neumann/analyze/checklist.py`, `src/neumann/analyze/validate.py`, `tests/e3/test_checklist.py`, `tests/e3/test_checklist_live.py`, `tests/e3/test_validate_semantic.py` (+1743). `llm.py`·`pipeline.py`·`models.py`·`contracts/`·`.env`·`data/` 변경 없음(이 브랜치엔 main에 아직 없는 파일이라 애초에 존재하지 않음). `git diff main task/E3-L1b --stat`도 같은 6개. 테스트 파일명은 소유 패턴(`test_checklist*.py`, `test_validate*.py`)과 일치 | 통과 |
| 11 | 비밀값 | diff에서 `sk-…`, `OPENAI_API_KEY=`, `api_key=`, `Bearer` 검색 | 0건. 라이브 테스트는 SDK가 환경변수에서 키를 읽고 키·헤더를 출력하지 않음 | 통과 |
| 12 | 커밋 규칙 | `git log main..task/E3-L1b` | 메시지 `[E3-L1b] …`, 끝에 `verify 통과(…)`·`builder: claude-opus-5.5` | 통과 |

## 정직성 확인

| 항목 | 방법 | 결과 |
|---|---|---|
| 규칙 결과를 astra라고 표시하는 경로 | 코드 전수 확인 + 6가지 실패 주입 + 부분 실패 | `rule_actions()`는 `_new_item(..., generator="rule", model=None, ...)`로만 항목이 된다(실패·누락·전부 무효 카드 단위). LLM 경로 항목만 `gen`(주입 라벨)을 받는다. 검증의 규칙 판정은 `judge="rule"`(줄 없음 상한)뿐이고 의미 판정을 규칙이 대신하지 않는다(실패=`unverified`, `judge=none`). 경로 없음 |
| 인용 정직성 | 코드·스키마·payload 확인 | 스키마에 인용문 필드 없음(`action`·`verify`·`plan_lines`·`evidence_ids`, card_id·excerpt id는 enum). 모델에 보내는 `cited_lines` 텍스트는 코드가 `plan.line(n)`으로 잘라 붙인 것이고 원문과 같음(16행 비교 True). 이 과제는 새 인용 문자열을 만들지 않는다 |
| 강등이 status에 기록되는가 | 결과 `status`·단계·notices 확인 | 체크리스트 규칙 대체 → 단계 degraded + 결과 degraded. 검증 실패·미검증 → 단계 degraded + 결과 degraded + notices. 검증 '틀림' → `verification["semantic"].demoted_cards`, 항목 `card_verdict`·`validation`, notices 한 줄 |
| 항상 통과하는 테스트 | 사본에 변조(mutation) 10종을 넣고 `tests/e3` 재실행 | 아래 표: 9종은 실패로 잡히고, 1종(M6)은 동치 변형이라 잡히지 않는 것이 정상 |

변조 실험(worktree 밖 사본에서, 원본은 그대로):

| 변조 | 잡은 테스트 |
|---|---|
| M1 줄 번호 검증 제거 | `test_nonexistent_plan_lines_are_removed_and_recorded`, `test_card_citing_nonexistent_lines_is_capped_at_weak` |
| M2 규칙 대체 항목에 astra 표기 | `test_failure_falls_back_to_rule_and_marks_generator[...]` 등 |
| M3 규칙 대체해도 단계 ok | `test_attach_checklist_records_stage_and_keeps_contract` |
| M3b 강등 단계가 결과 status를 안 올림 | 위 + `test_failure_leaves_cards_unverified_and_degrades` |
| M4 '틀림' 카드의 항목 삭제 | `test_mismatch_card_is_demoted_but_not_deleted_and_its_actions_stay` |
| M5 줄 없는 카드의 weak 상한 제거 | `test_card_citing_nonexistent_lines_is_capped_at_weak` |
| M6 `elif fails` 분기 제거 | 안 잡힘 — 바로 아래 분기(`cards_unverified`)가 같은 degraded를 내므로 동치 변형, 사유 문구만 바뀜(문제 아님) |
| M7 검증 실패를 astra의 '맞음'으로 | `test_failure_leaves_cards_unverified_and_degrades` 외 2건 |
| M8 행동 판정을 카드 판정에 끌려가게 | `test_mismatch_card_is_demoted_...`, `test_mismatch_action_is_flagged_not_deleted_independent_of_card` |
| M9 근거 excerpt id 풀 검사 제거 | `test_foreign_evidence_unknown_card_and_missing_card` |
| M10 카드당 행동 3개 상한 제거 | `test_actions_capped_at_three_deduped_and_length_checked` |

## 참고(병합을 막지 않음)

1. `llm_label()`은 주입된 `llm_call`에 `generator` 속성이 없으면 기본 `astra`/`gpt-6-astra`로 표기한다. 파이프라인이 mock provider를 감쌀 때 어댑터가 `generator`(`mock`)·`model` 속성을 달지 않으면 mock 결과가 astra로 찍힌다. 빌더 보고서의 어댑터 예시는 속성을 다는 형태이므로 E3-L0 연결 때 그대로 지켜야 한다(PM 확인 항목).
2. LLM 경로에서 행동의 줄 번호가 전부 무효이고 카드 인용 줄까지 무효이면 `plan_lines=[]`, `plan_lines_source="none"`인 astra 행동이 남는다(과제 문구 "각 행동은 계획서 줄 번호에 연결"의 예외). 표시는 되지만 E4가 '줄 없음'을 보여 주거나 걸러야 한다. 실제 카드는 `why_applies.plan_lines`가 보통 있어 드문 경우다.
3. 라이브 테스트는 openai SDK를 직접 부르는 임시 llm_call이다(과제가 허락한 형태). E3-L0 `llm.py`는 main에 아직 없어 그 어댑터 경로(`complete_json`)와 mock 응답 함수는 검증하지 못했다. 빌더도 "못 한 것"에 적었다. mock provider로 돌리면 응답 함수 부재로 규칙 대체(degraded)·`unverified`가 되는 것은 정직한 표기다.
4. 행동 `action`, 판정 `reason`은 LLM이 쓴 한국어 문장이다(인용이 아님). 코드는 길이·중복만 검사하고 내용이 원문과 맞는지는 2차 검증(카드·행동 판정)이 본다. 이 층은 의도된 설계다.
5. 빌더 보고서의 verify 수치(210 passed)는 main 병합 전 시점이다. 현재 브랜치 head는 253 passed, 2 skipped로 통과한다.
