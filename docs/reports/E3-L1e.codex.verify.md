# E3-L1e 독립 검증 — 현 HEAD 조건 미충족, 빌더 수정 대기

- 검증자: codex-gpt-6-sol. 대상 `task/E3-L1e` HEAD `53e30c2`, 비교 main `75072fc`.
- 실제 OpenAI 호출 0, 제품 코드 수정 0, Git 쓰기 0. Python은 venv·mock·offline 설정(`NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_TESTS=0`, `NEUMANN_LIVE_LLM_OK` 해제, `OPENBLAS_NUM_THREADS=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `PYTHONPATH='src;.'`)으로 실행했다.

## 확인된 기준

- `python -m pytest -q -p no:cacheprovider --basetemp=out/codex/pytest/E3-L1e/codex-sol-focused tests/e3/test_evidence_gate_l1e.py tests/e3/test_evidence_gate_view_l1e.py tests/e4/test_export.py` → **59 passed, 1 skipped**. 체크리스트 빈 id·없는 id·다른 카드 id·혼합 id 폐기, 2차 검증 재검사, 정상 항목 유지, 제외 수·문구 검사 통과.
- `NEUMANN_UI_TESTS=1 ... pytest ... tests/e3/test_evidence_gate_view_l1e.py::test_excluded_lists_render_in_browser` → **1 passed in 19.03s**. 테스트 소유 mock 8164 서버를 시작·정리했다. 기본 화면에서 체크리스트 폐기 문구는 0개, 심사평 폐기 문구는 접힌 감사 목록에 `제외됨` 라벨과 함께 있다. PM은 이 감사 열람을 기존 승인 기준으로 확인했다.
- `git diff main...HEAD -- contracts/ui_view.schema.json`에서 `checklist_audit` 및 `review.audit`의 선택 필드만 추가됨을 확인했다. `git diff --check main...HEAD` 출력 0, 읽기 전용 `git merge-tree <merge-base> main HEAD` 텍스트 충돌 0.

## 독립 반례 — 현 HEAD에서 실패

1. **심사평 view 마지막 방어선:** `tests.e3.test_evidence_gate_l1e._result()`에 `expected_review.weakness` 문장 하나를 넣고 `excerpt_ids=[r.evidence[0].excerpt_id, "ghost_ex"]`로 만든 뒤 `build_ui_view(r, records=None)` 실행. 출력은 `{'visible': True, 'citations': [1], 'view_dropped': 0}`. `src/neumann/api/view.py`의 `_build_review`는 없는 id만 버리고 문장을 남긴다. 체크리스트 view는 혼합 id를 문장째 제외하므로 공용 근거 게이트와 불일치한다. 정상 생성 경로의 앞 게이트는 이 입력을 막지만 저장 결과가 그 경로를 우회할 때 화면에서 재검사하지 못한다.
2. **내보내기 근거 방어선:** 계약 검증을 통과한 `PremortemResult`에 근거 `evidence=[]`인 체크리스트 행동을 넣어 `build_package_files` 실행하면 `neumann_report.md`에 그 행동 원문이 들어갔다(`report_contains_unsupported_action: True`). 근거가 `ghost_ex`뿐인 예상 심사평도 같은 리포트에 들어갔다(`report_contains_unsupported_sentence: True`). `src/neumann/api/export.py`의 `_report`는 생성 경로의 게이트를 다시 적용하지 않고 현재 항목을 옮긴다. 생성 단계에서 이미 폐기된 심사평의 감사 문구는 리포트에서 제거되는 것을 기존 테스트가 확인했다.

이 반례를 E3-L1e 빌더에게 입력·호출·위치와 함께 전달했다. 빌더가 수정 커밋을 만드는 중이다. **현 HEAD는 최종 PASS가 아니며 전체 verify는 PM 지시대로 수정 커밋 뒤에만 실행한다.** 다음 검증은 혼합 id 심사평·근거 없는 체크리스트/심사평의 view 및 ZIP 모든 파일 제외와 제외 수를 재측정해야 한다. 실제 라이브 확인은 하지 않았다.
