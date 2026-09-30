# SEC-1 — 보안·정직성 점검(공개 저장소·공개 서버 전)

- 점검자: Claude Sonnet 5.5 (코드를 고치지 않는다) · 목표 30분
- 산출: main 체크아웃 `docs/reports/SEC-1.md`
## 점검 범위(현재 main과 task/* 브랜치 전체)
1. 비밀값: 키 패턴·환경변수 값·`.env` 경로 문자열이 코드·테스트·보고서·스크린샷 파일명·커밋 메시지에 없는지(`git log -p` 표본, `scripts/verify.py --security`)
2. 공개 서버: 예외 메시지·스택 트레이스·내부 경로 노출, 로그에 계획서 본문·키, CORS·업로드 크기, 경로 이동(path traversal)·XSS(결과 렌더) 가능성
3. 데이터 라이선스: DISAPERE(CC BY-NC)·ResearchArcade(라이선스 없음)·RW 원본이나 대량 인용이 저장소에 들어갔는지
4. 정직성: 규칙·mock 결과를 LLM(astra) 결과로 표기하는 경로, 샘플을 실제처럼 보이는 경로
## 산출
발견마다 심각도·위치·재현·권고. 판정 PASS / 조건부 / FAIL
