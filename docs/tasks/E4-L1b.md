# E4-L1b — AI for Science 템플릿 선택기·범위 안내 (대표 지시 2026-09-30)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 45분
- 소유: `src/neumann/api/templates.py`, `src/neumann/api/templates/`(템플릿 데이터), `src/neumann/webui/index.html`의 **입력 화면 부분**, `tests/e4/test_templates*.py`. `main.py` 연결은 PM(라우터만 제공)

## 배경
- 대표 지시: 입력 화면에 AI for Science 템플릿을 고르는 기능이 보여야 한다. 안 보이면 아무 연구나 넣을 수 있기 때문이다. 화면에 범위 안내 "AI 활용 과학 연구 계획서 전용"을 보인다
- 코퍼스 분야: 소재·화학·분자 / 단백질·생물·신약 / 물리·PDE·기후 (+ 데모 2·3번 신경과학 fMRI·의료영상)

## 만들 것
1. 템플릿 카탈로그(JSON): 재료·배터리 GNN 대리모델, 단백질·분자, 물리·PDE·기후, 신경과학 fMRI, 의료영상. 템플릿마다 계획서 골격(연구 목표·방법·데이터·평가·일정 칸, 한국어)과 설명. 데모 계획서 3건(`tests/fixtures/plans/`)은 "예시 불러오기"로 연결
2. `api/templates.py`: `router`에 `GET /templates`(목록), `GET /templates/{id}`(골격 본문)
3. 입력 화면(`webui/index.html`): 템플릿 선택기(선택하면 입력칸에 골격 채움), 예시 3건 불러오기, 상단 범위 안내 "AI 활용 과학 연구 계획서 전용". 디자인 규칙(`05_디자인_규칙`) 준수, CDN 금지
4. 범위 밖 입력은 적합성 판정(E3-L1c `assess_fitness`)이 막는다 — 화면에서 판정 결과(부적합 사유)를 보여 줄 자리를 마련(연결은 PM)
## 완료 기준
1. `pytest tests/e4 -q -k templates`, 템플릿 JSON 스키마 테스트
2. Playwright(1440×900) 스크린샷: 선택기·범위 안내·예시 불러오기(`docs/reports/E4-L1b_*.png`), 콘솔 오류 0, 외부 요청 0. 서버는 8010이 아닌 빈 포트로 띄우고 끝나면 종료
3. `python scripts/verify.py` 통과
