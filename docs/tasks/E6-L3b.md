# E6-L3b — 시연 영상 녹화 스크립트 (주최측 요구: 발표자료에 시연 영상)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 40분
- 소유: `scripts/record_demo*.py`, `tests/e6/test_record*.py`

## 배경
- 발표자료에 **시연 영상**이 들어가야 한다(주최측 요구, 대표 지시 2026-09-30). 지금은 녹화 스크립트를 만들고, v2 이후 최종 화면으로 다시 녹화한다
- PATH에 ffmpeg는 없고 Playwright의 녹화 기능(`record_video_dir`, webm)은 쓸 수 있다
- **영상은 저장소에 커밋하지 않는다**(공개 저장소, verify 5MB 상한). 공유 폴더 `data/video/`에만. 업로드는 대표 승인 뒤

## 만들 것
1. `scripts/record_demo.py --base-url http://127.0.0.1:8010 --plan tests/fixtures/plans/plan.md --out data/video/`: Playwright(1440×900)로 입력 → 계획서 붙여넣기 → 분석 대기 → 리포트 → 위험카드 → 근거 열람 → (있으면) 내보내기 순서를 사람 속도로 녹화. 단계마다 자막처럼 보일 짧은 화면 주석(선택)
2. 녹화 전에 `/health`로 파이프라인 연결 상태를 확인하고, 미연결(샘플)이면 파일 이름과 로그에 "sample"을 붙인다(샘플을 실제 시연처럼 쓰지 않게)
3. 결과: webm 파일, 길이·해상도·단계별 타임스탬프 JSON
4. 테스트: 짧은 가짜 페이지로 녹화 함수가 파일을 만드는지(네트워크 없이)
## 완료 기준
지금 떠 있는 점검 서버(127.0.0.1:8010, 샘플 데이터)로 1회 녹화한 결과(길이·단계 타임스탬프)를 보고서에. `python scripts/verify.py` 통과. 영상 커밋 금지
