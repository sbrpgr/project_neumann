# E6-L3c — 실서버 시연 영상 1차 녹화 + mp4 변환
- 빌더 Opus 5.5 · 검증 Sonnet 5.5 · 목표 30분 · 소유: `data/video/`(커밋 안 함), `scripts/record_demo*.py`의 작은 보완, 보고서
## 만들 것
main의 `scripts/record_demo.py`로 **실서버 8010(v0, 실제 astra)**에서 데모 plan.md 시연을 녹화(샘플 아님이 확인돼야 함 — `_live` 파일), ffmpeg(`C:/Users/User/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.2-full_build/bin/ffmpeg.exe`)로 mp4(H.264, 발표자료 삽입용)와 3분 이내 편집본(분석 대기 구간 가속). 서버를 끄거나 재시작하지 않는다(대표 점검 중일 수 있음 — 녹화 1회만)
## 완료 기준
webm·mp4 경로, 길이, 단계 타임스탬프, 샘플 표시 없음 확인. 최종 녹화는 v2 뒤 다시 한다
