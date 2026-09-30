# 결정 기록

한 줄씩 추가한다. 형식: `날짜 시각 | 결정 | 이유 | 누가`

- 2026-09-30 16:42 | 공개 저장소 `sbrpgr/project_neumann`을 본선 전에 빈 상태로 만듦(커밋 0) | 주최측 요청 | 대표
- 2026-09-30 18:00 | 첫 커밋들은 제품 코드 0줄: 규칙, 보안 설정, 검증 러너, 계약 스키마, 문서 | 계획서 §6 | PM
- 2026-09-30 18:00 | 비밀값은 `.env`에만 두고 코드는 환경변수로만 읽는다. `.env.example`의 비밀값 칸은 비운다 | 공개 저장소 | 대표·PM
- 2026-09-30 18:00 | 비밀값 검사는 세 겹: git 훅(pre-commit·commit-msg·pre-push) + `scripts/verify.py` + GitHub 푸시 보호 | 한 겹이 빠져도 막히게 | PM
- 2026-09-30 18:00 | `contracts/` 스키마 2종은 기획 키트(`부록/설계/contracts/`) 원본을 그대로 가져옴 | 계획서 §4.0·§6 | PM
- 2026-09-30 18:00 | 제품 LLM은 OpenAI API `gpt-6-astra` 하나. provider는 `openai`·`mock`만 둔다(로컬 LLM 없음) | 대표 확정 | 대표
- 2026-09-30 18:13 | 제품 LLM `gpt-6-astra`를 Responses API로 1회 호출해 확인(짧은 요청 약 3초, reasoning effort low) | 계획서 §5.5 T+0 | PM
- 2026-09-30 18:15 | PM 세션("로컬 세팅")이 구축 세션에서 인수, 한 대화에서 빌더를 subagent(worktree 격리, Opus 5.5)로 병렬 운영 | 대표 지시 "끝까지 진행" | 대표·PM
- 2026-09-30 18:15 | 공유 데이터 폴더를 main 체크아웃의 `data/`로 고정(모든 worktree가 절대경로로 씀) | worktree마다 data/가 따로 생기는 문제 | PM
- 2026-09-30 18:21 | Codex 인계 준비 시험 통과: `codex exec -m gpt-6-astra -s workspace-write`가 임시 worktree에 파일 쓰기·venv python 실행 성공, 다른 변경 없음 | 계획서 §5.6 | PM
