# E4-L2f 보고서 (WIP, 대표 지시로 Codex 교대 — 중간 종료)

- 된 것: `index.html` 단계 IV "내보내기"·섹션 VI "ZIP 내려받기" 켬(커밋 1e7d6e2). 결과 없음·샘플·오류면 비활성+사유, 서버 message/detail은 textContent. 결정은 연구자가 고른 항목만 `{item_id, decision(adopt|hold|reject), note, decided_at}`로 `/premortem/package`에 보냄. 결정: 화면 데이터(ui_view)에 원본 결과가 없어, `D.result`가 없으면 같은 계획서로 `POST /premortem`을 다시 받고 계획서 id·카드 id·체크리스트 id·문구가 화면과 같을 때만 묶음(다르면 거절). 제안: `/premortem/view`(또는 jobs)가 원본 result를 함께 실어 재분석을 없앨 것(실제 LLM이면 재분석 비용·불일치).
- 테스트 상태: `tests/e4/test_export_ui.py` 정적 6건 통과(`pytest -q` → 6 passed, 1 skipped). Playwright(8149, mock, `NEUMANN_UI_TESTS=1`)는 단계 IV 비활성 사유·분석·결정 집계까지 진행했으나 실패: 같은 `.dec`를 연달아 두 번 클릭한 두 번째가 반영 안 됨(기대 채택2·기각1, 실제 채택1·기각2) — 클릭 사이 대기나 한 번 클릭 기대값으로 고칠 것.
- 남은 것: 위 Playwright 수정 후 ZIP 9파일·decision_log 검증·스크린샷 `E4-L2f_export.png` 생성, `python scripts/verify.py`, `git merge main`(index.html 충돌 시 내보내기 부분만 해결).
