#!/usr/bin/env bash
# Codex 인계용 과제 실행기 (계획서 §5.6). Git Bash에서 실행한다.
#
#   bash scripts/codex_task.sh build  <과제ID>     빌더: main에서 worktree+브랜치 task/<과제ID>를 만들고 gpt-6-astra로 과제 수행
#   bash scripts/codex_task.sh verify <과제ID>     검증: 빌더 worktree에서 gpt-6-sol로 docs/tasks/_VERIFY.md 수행(코드 수정 금지)
#   bash scripts/codex_task.sh review <과제ID>     코드 리뷰만: codex exec review --base main (gpt-6-sol)
#
# 백그라운드로 여러 개 띄워도 된다(과제마다 worktree가 따로다). 로그: C:/Users/User/Desktop/pn_logs/codex_<모드>_<과제ID>.*
# 키는 환경변수(OPENAI는 제품용, Codex는 ChatGPT 로그인)로만 쓰고, 이 스크립트는 값을 읽거나 출력하지 않는다.
set -euo pipefail

MODE="${1:?모드: build | verify | review}"
TASK="${2:?과제ID}"
REPO="C:/Users/User/Desktop/project_neumann"
WT_ROOT="C:/Users/User/Desktop/pn_codex"
LOGS="C:/Users/User/Desktop/pn_logs"
EFFORT="${CODEX_EFFORT:-high}"
mkdir -p "$WT_ROOT" "$LOGS"

CODEX="$(powershell -NoProfile -Command "(Get-ChildItem \"\$env:LOCALAPPDATA\OpenAI\Codex\bin\" -Recurse -Filter codex.exe | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName" | tr -d '\r')"
[ -x "$CODEX" ] || { echo "codex.exe를 찾지 못했다"; exit 1; }
[ -f "$REPO/docs/tasks/$TASK.md" ] || [ "$MODE" != "build" ] || { echo "지시문 없음: docs/tasks/$TASK.md"; exit 1; }

WT="$WT_ROOT/$TASK"
case "$MODE" in
  build)
    if [ ! -d "$WT" ]; then
      git -C "$REPO" worktree add -q "$WT" -b "task/$TASK" main 2>/dev/null || git -C "$REPO" worktree add -q "$WT" "task/$TASK"
    fi
    PROMPT="당신은 Project Neumann의 빌더다(Codex gpt-6-astra, Claude 한도 소진으로 인계받음). 과제 ID: $TASK.
현재 폴더는 이 과제 전용 git worktree이고 브랜치는 task/$TASK 다. 순서대로 읽고 그대로 수행하라:
1) AGENTS.md  2) docs/tasks/_COMMON.md  3) docs/tasks/$TASK.md  4) docs/HANDOFF.md(현재 상태)
규칙: 이 브랜치에만 커밋, main 병합·push 금지, .env 열기·키 출력 금지, 하위 에이전트·자동 위임 금지, 소유 경로만 수정, 끝내기 전 python scripts/verify.py 통과(Python: C:/Users/User/.venvs/neumann/Scripts/python.exe), 보고서 docs/reports/$TASK.md 커밋(커밋 끝줄: builder: codex-gpt-6-astra), 작업 트리를 깨끗하게.
마지막 답: 브랜치, 커밋 목록, 완료 기준별 결과, 못 한 것."
    printf '%s\n' "$PROMPT" | "$CODEX" exec -m gpt-6-astra -c "model_reasoning_effort=\"$EFFORT\"" \
      -C "$WT" -s workspace-write --add-dir "$REPO/data" \
      -o "$LOGS/codex_build_$TASK.last.md" - > "$LOGS/codex_build_$TASK.log" 2>&1
    echo "끝: $TASK (브랜치 task/$TASK, 마지막 답 $LOGS/codex_build_$TASK.last.md)"
    ;;
  verify)
    [ -d "$WT" ] || WT="$(git -C "$REPO" worktree list --porcelain | awk -v b="refs/heads/task/$TASK" '/^worktree /{w=$2} $0=="branch "b{print w}')"
    [ -d "$WT" ] || { echo "빌더 worktree를 찾지 못했다: task/$TASK"; exit 1; }
    PROMPT="당신은 Project Neumann의 검증자다(Codex gpt-6-sol, 빌더와 다른 모델). 과제 ID: $TASK. 코드를 고치지 않는다.
$REPO/docs/tasks/_VERIFY.md 를 그대로 따르라. 지시문: docs/tasks/$TASK.md, 빌더 보고서: docs/reports/$TASK.md.
검증 보고서는 $REPO/docs/reports/$TASK.verify.md 에 쓴다(첫 줄에 '검증자: codex-gpt-6-sol'). git 쓰기 조작 금지, .env 금지, 이 worktree에 파일을 남기지 않는다.
마지막 답: 판정(PASS / FAIL / PASS-조건부)과 핵심 근거."
    printf '%s\n' "$PROMPT" | "$CODEX" exec -m gpt-6-sol -c "model_reasoning_effort=\"$EFFORT\"" \
      -C "$WT" -s workspace-write --add-dir "$REPO/docs/reports" \
      -o "$LOGS/codex_verify_$TASK.last.md" - > "$LOGS/codex_verify_$TASK.log" 2>&1
    echo "끝: $TASK 검증 (보고서 $REPO/docs/reports/$TASK.verify.md)"
    ;;
  review)
    [ -d "$WT" ] || { echo "worktree 없음: $WT"; exit 1; }
    "$CODEX" exec -C "$WT" review --base main -m gpt-6-sol -o "$LOGS/codex_review_$TASK.last.md" > "$LOGS/codex_review_$TASK.log" 2>&1
    echo "끝: $TASK 리뷰 ($LOGS/codex_review_$TASK.last.md)"
    ;;
  *) echo "모드: build | verify | review"; exit 2 ;;
esac
