# E5-L0e2e — 라이브 E2E 검사(실데이터·실제 astra, 로컬 서버)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 45분
- 소유: `tests/e2e/`(새 폴더), `docs/reports/E5-L0e2e*`

## 만들 것
1. `tests/e2e/test_live.py`(`NEUMANN_LIVE_TESTS=1`일 때만 실행): 로컬 서버(인자로 base URL, 기본 http://127.0.0.1:8010)에 Playwright로
   - 데모 계획서 3건(`tests/fixtures/plans/`): 입력 → 분석 완료 대기(시간 상한 설정) → 카드 1장 이상, 카드마다 인용·원문 링크, 파이프라인 연결 표시(샘플 모드면 실패로 보고), 단계별 강등 표시 확인
   - 범위 밖 입력 1건(`negative_recipe.md`): 카드 0장과 사유(또는 부적합 판정)
   - 결과 JSON을 받아 `eval.linkage.check_result`(+ `neumann.index.store.get_source_text`)로 근거 연결률 1.0 확인
   - 단계별 소요 시간·전체 시간 기록, 스크린샷(`docs/reports/E5-L0e2e_*.png`), 콘솔 오류 0, 외부 요청 0(OpenAI 호출은 서버 쪽이라 브라우저 요청에는 없어야 함)
2. 분석 파이프라인이 아직 main에 없으면 테스트 코드를 먼저 만들고, 샘플 모드에서 "파이프라인 미연결"을 정확히 실패로 보고하는지만 확인한다. v0 통합 뒤 PM이 실제로 돌린다
## 완료 기준
테스트 코드 커밋, 샘플 모드에서의 실행 결과(기대대로 실패 보고), `python scripts/verify.py` 통과(e2e는 기본 건너뜀)
