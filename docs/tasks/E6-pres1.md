# E6-pres1 — 발표자료 작업본(숫자 외 전부) — 마감 10/01 09:00
- 빌더 Opus 5.5 · 검증 Sonnet 5.5 · 목표 60분 · 소유: 작업 파일 `C:/Users/User/Desktop/project_neumann/data/deck/`(저장소 밖, 커밋 안 함), 보고서
## 근거
키트 `발표자료/README.md`(빈칸 표), `발표자료/본선_발표자료.pptx`(원본은 수정 금지 — 복사해서 작업), 계획서 §4 E6(발표 숫자 원칙: 현장 측정값만, n·구간, 미달은 먼저), `docs/reports/*`(실측값), `docs/decisions.md`
## 만들 것
1. 원본을 `data/deck/본선_발표자료_작업본.pptx`로 복사해 **숫자가 필요 없는 빈칸**을 채운다: 구현 구성·데이터 규모(코퍼스 1,128편·심사평 5,366건·문장 133,769개·색인 GPU 76초 등 이미 확정된 실측), 11쪽 프로토타입 UI(스크린샷: `docs/reports/E4-L0_*.png` 등 최신), 12쪽 GitHub 주소 `github.com/sbrpgr/project_neumann`, 프로토타입 주소·시연 영상 자리(QR 자리 포함, 값은 07:30 확정)
2. 숫자 자리(백테스트·Macro-F1 astra 등)는 눈에 띄는 "측정 중" 표시로 비워 두고, 채울 칸 목록을 보고서에(쪽·칸·들어갈 지표·출처 파일)
3. 발표자 노트의 `[현장 작성]` 중 숫자 무관한 것 채우기. 옛 제품 숫자(κ 0.238, Macro-F1 0.469 등) 금지
4. 편집 방법: PowerPoint COM(이 PC에 설치됨) 또는 python-pptx(`uv pip install --python <venv python> python-pptx`). 한글 텍스트는 UTF-8 JSON에서 읽어 넣기
5. PDF로도 저장해 쪽마다 PNG로 확인(`data/deck/preview/`)
## 완료 기준
작업본·PDF·미리보기 PNG, 채운 칸/남은 칸 목록, 대표 실명 등 기존 결정 준수
