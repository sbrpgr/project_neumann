# E4-L1c — 근거 열람 패널·평가이력 지도(화면 L1)
- 빌더 Opus 5.5 · 검증 Sonnet 5.5 · 목표 50분 · 소유: `src/neumann/webui/index.html`의 **리포트·근거 패널 부분**, `src/neumann/api/view.py`, `tests/e4/test_view*.py` (입력 화면·고지 부분은 다른 빌더 — 병합 전 `git merge main`으로 충돌 확인)
## 근거
계획서 §3 L1 "화면"(계획서 행 → 실제 리뷰어 문장 → 결정 → 원문 링크), 목업 `Evidence.dc.html`·`web/index.html`, `05_디자인_규칙`
## 만들 것
근거 패널: 카드 근거마다 원문 인용(오프셋 그대로), 그 논문의 결정·평점, 원문 링크, 연결된 계획서 줄 강조. 평가이력 지도: 유사 연구별 결정 분포. 예상 심사평·체크리스트 표시 자리(결과에 있으면 렌더, 없으면 숨김). `build_ui_view`가 결과의 `expected_review`·`checklist`를 목업 형식으로
## 완료 기준
Playwright 1440×900 스크린샷(`docs/reports/E4-L1c_*.png`), 콘솔 오류 0·외부 요청 0, 테스트, `python scripts/verify.py` 통과. 서버는 8010 금지
