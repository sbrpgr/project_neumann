# 과제 공통 규칙 (모든 빌더·검증자)

먼저 읽는다: `AGENTS.md`(규칙) → 이 파일 → 자기 과제 파일. 기준 문서는 `C:/Users/User/Desktop/노이만_본선자료/기획서/00_구현_계획서.md`다. 과제 파일이 계획서와 다르면 과제 파일을 따르고 보고서에 적는다.

## 경로

| 무엇 | 경로 |
|---|---|
| Python | `C:/Users/User/.venvs/neumann/Scripts/python.exe` (필요한 패키지는 설치돼 있다. `mcp` SDK만 없다. 새 패키지가 필요하면 보고서에 적는다) |
| 기획 키트(읽기만) | `C:/Users/User/Desktop/노이만_본선자료/기획서` |
| 공개자료 원본(읽기만) | `C:/Users/User/Desktop/노이만_본선자료/공개자료` |
| **공유 데이터 폴더** | `C:/Users/User/Desktop/project_neumann/data` — 모든 worktree가 같이 쓴다. worktree 안의 `data/`가 아니다. gitignore 대상 |
| 목업(최신) | `C:/Users/User/Desktop/노이만_본선자료/기획서/부록/목업/web/index.html` |

실행할 때 환경변수:

```bash
export PYTHONIOENCODING=utf-8 PYTHONPATH="src:." HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export NEUMANN_RAW_DIR="C:/Users/User/Desktop/노이만_본선자료/공개자료"
export NEUMANN_DATA_DIR="C:/Users/User/Desktop/project_neumann/data"
export NEUMANN_EMBED_MODEL="C:/Users/User/Desktop/노이만_본선자료/공개자료/models/bge-m3"
```

- `.env`는 main 체크아웃에만 있고 worktree에는 없다. 열지 않는다.
- `OPENAI_API_KEY`는 이미 환경변수로 들어와 있다. 있는지 확인할 때는 참·거짓만 본다. 값을 출력·기록하지 않는다.
- 제품 LLM은 OpenAI Responses API `gpt-6-astra`다(9/30 호출 확인: `client.responses.create(model="gpt-6-astra", input=..., reasoning={"effort": "low"})`, 짧은 요청 약 3초).

## 작업 방식

- 자기 worktree에서만 작업한다. 시작하면 `git switch -c task/<과제ID>`(이미 있으면 그대로). 커밋은 그 브랜치에만 한다. main 병합과 push는 PM이 한다.
- 자기 소유 경로만 고친다(`AGENTS.md` 표와 과제 파일의 "소유"). 예외: 자기 보고서 `docs/reports/<과제ID>.md`와 스크린샷 `docs/reports/<과제ID>_*.png`는 써도 된다.
- 계약(`contracts/`, `src/neumann/models.py`)은 바꾸지 않는다. 필요한 필드가 없으면 보고서 "제안"에 적고, 자기 모듈 안에서 우회한다.
- 테스트는 `tests/<에픽 소문자>/`(예: `tests/e1/`)에 둔다. 기본 테스트는 mock·fixture로 돈다. 실제 API를 부르는 테스트는 `NEUMANN_LIVE_TESTS=1`일 때만 돈다.
- 큰 데이터 산출물은 공유 데이터 폴더에 둔다. 저장소에는 코드·테스트·작은 fixture만.
- 끝내기 전에 `python scripts/verify.py`가 통과해야 한다(보안 + 계약 + 전체 pytest). 완료 기준의 명령을 **직접 실행**하고 출력을 보고서에 붙인다. 실행하지 않고 "됐다"고 쓰지 않는다.
- 커밋: 작게, 메시지 `[과제ID] 무엇을`, 끝줄에 `verify 통과`와 `builder: claude-opus-5.5`. `git add`는 파일을 지정해서 한다.
- 보고서 `docs/reports/<과제ID>.md`: 무엇을 했나, 완료 기준별 명령·출력, 바꾼 파일, 결정한 것(스펙이 모호해서 고른 것), 못 한 것, 다음 과제에 넘길 것. 커밋에 포함한다.
- 하위 에이전트를 띄우지 않는다. 막히면 합리적인 쪽을 골라 계속하고 보고서 "결정"에 적는다. 멈춰서 기다리지 않는다.
- 목표 시간을 넘길 것 같으면 핵심 완료 기준부터 채우고, 나머지는 보고서 "못 한 것"에 적고 끝낸다. 끝낼 때 작업 트리에 커밋 안 된 변경이 없어야 한다.

## 근거 정직성 (모든 과제)

- 출처(원문 URL·접근 시각·원문 해시) 없는 레코드는 만들지 않는다. 리뷰어 신원 필드는 없다.
- 인용은 원문에서 오프셋으로 잘라 붙인 것만 쓴다. LLM이 쓴 문자열을 인용으로 쓰지 않는다.
- 규칙으로 만든 결과를 LLM 결과라고 표시하지 않는다. 비상 경로로 돌면 `status`에 남긴다.
