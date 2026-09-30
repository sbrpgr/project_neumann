# E6-docs — 저장소 README·아키텍처·실행 방법 (심사·점검용)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 40분
- 소유: `docs/ARCHITECTURE.md`, `docs/RUNNING.md`, `docs/API.md` (루트 `README.md`는 PM 소유 — 고칠 내용을 보고서에 초안으로)
## 읽을 것
계획서 §2·§4.0, 현재 main의 `src/`, `docs/tasks/`, 브랜치별 보고서(`docs/reports/`)
## 만들 것
1. `docs/ARCHITECTURE.md`: 6단계(INPUT→EVIDENCE→RISK→REVIEW→ACTION→TRACE), 모듈 지도, astra 주력·비상 규칙 경로, 근거 정직성 장치(오프셋 대조·근거 게이트·생성 방식 표기), 데이터 출처와 라이선스
2. `docs/RUNNING.md`: 설치(venv), 공개자료 경로, 색인 빌드, 서버 실행, 테스트, verify, 키는 환경변수(값을 문서에 쓰지 않음)
3. `docs/API.md`: 엔드포인트 목록과 예시(현재 main 기준, 없는 것은 "예정")
4. 루트 README 개정 초안(보고서에)
## 완료 기준
문서의 명령을 실제로 실행해 확인(실행 결과를 보고서에), 사실과 다른 기능을 쓰지 않음, `python scripts/verify.py` 통과
