# E6-L3a — 프로토타입 주소용 정적 배포 빌드 (주최측 요구: 발표자료에 프로토타입 주소)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 50분
- 소유: `scripts/build_static_site*.py`, `tests/e6/test_static*.py` (화면 원본 `src/neumann/webui/`는 E4 몫 — 필요한 변경은 보고서에 제안)

## 배경
- 발표자료에 **프로토타입 주소**가 들어가야 한다(주최측 요구, 대표 지시 2026-09-30). 후보는 GitHub Pages 정적 판(`https://sbrpgr.github.io/project_neumann/`)이다
- **공개(Pages 켜기·배포)는 대표 승인 뒤 PM이 한다.** 이 과제는 배포할 수 있는 폴더를 만드는 데까지다

## 만들 것
1. `scripts/build_static_site.py`: `src/neumann/webui/index.html`·폰트를 복사하고, 데모 계획서 3건의 사전 계산본(`data/precomputed/`, E6-L2a — 없으면 공용 fixture 결과)을 JSON으로 넣어, 서버 없이 도는 정적 사이트를 공유 폴더 `data/site/`에 만든다
   - API 호출 대신 정적 JSON을 읽게 하는 방법: 빌드 때 `window.NEUMANN_STATIC = {...}` 주입 또는 정적 경로 fetch. 원본 index.html은 고치지 않고 빌드 산출물에서만 바꾼다
   - 화면에 **"사전 계산본(생성 시각·모델) — 라이브 분석 아님"** 표시. 입력칸은 데모 3건 선택으로 바꾸거나 비활성화
   - 외부 도메인 요청 0, 키·환경변수·내부 경로 문자열 0(빌드 뒤 자동 검사)
   - GitHub Pages 하위 경로(`/project_neumann/`)에서도 동작하도록 상대 경로
2. 테스트: 빌드 산출물에 비밀값 패턴·절대 로컬 경로 없음, 필수 파일 존재, 데모 3건 JSON 존재
3. Playwright로 `data/site/`를 로컬 정적 서버(`python -m http.server`)에 띄워 1440×900 스크린샷 3장(`docs/reports/E6-L3a_*.png`), 콘솔 오류 0·외부 요청 0
## 완료 기준
위 1~3, `python scripts/verify.py` 통과. `data/site/`는 커밋하지 않는다
