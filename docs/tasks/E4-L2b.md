# E4-L2b — MCP 서버(도구 3종, 읽기 전용) (앞당김)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5
- 목표 시간: 45분
- 소유: `src/neumann/api/mcp_server.py`, `tests/e4/test_mcp*.py` (`api/main.py`·`view.py`·`export.py`는 다른 빌더 몫이라 건드리지 않는다)

## 읽을 것

- 계획서 §1.5 MCP 행, §3 L2 "MCP 서버(최소)", §4 E4 L2
- `src/neumann/index/`(E2-L0: `search`, `store.get_work`·`get_reviews`·`get_excerpts`) — main에 없으면 `git merge main`을 기다리지 말고 공유 색인(`data/index/`)과 E2 브랜치 인터페이스 설명(`docs/tasks/E2-L0.md`)대로 얇은 어댑터를 두고 개발
- `src/neumann/sources/retraction.py`(E1-L2: `get_post_status`) — 같은 방식

## 만들 것

1. 공식 Python SDK `mcp`를 venv에 설치한다: `C:/Users/User/.venvs/neumann/Scripts/python.exe -m pip install mcp` (설치 버전을 보고서에, `pyproject.toml` 추가는 PM에게 제안)
2. `src/neumann/api/mcp_server.py`: stdio MCP 서버 `python -m neumann.api.mcp_server`
   - `search_similar_works(query: str, k: int = 10)` → 논문 id·제목·원문 URL·점수
   - `get_review_records(work_id: str)` → 심사평·저자 답변·결정 요약과 원문 URL(신원 정보 없음)
   - `get_post_status(doi: str)` → 철회·정정 등 사후 상태와 공지 링크
   - 읽기 전용. 계획서 본문은 받지 않는다(검색어만). 결과마다 출처 URL
3. 테스트: SDK의 클라이언트로 서버를 띄워 도구 목록 3개, 각 도구 호출 결과 형식, 없는 id 처리

## 완료 기준

1. `python -m pytest tests/e4 -q -k mcp` 통과
2. 실제 색인으로 도구 3개 호출 결과 예시를 보고서에
3. `python scripts/verify.py` 통과
