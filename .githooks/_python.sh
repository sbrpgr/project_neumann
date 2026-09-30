# 훅이 쓸 파이썬. 프로젝트 venv가 있으면 그것을, 없으면 시스템 파이썬을 쓴다.
PY="$HOME/.venvs/neumann/Scripts/python.exe"
[ -x "$PY" ] || PY="$(command -v python3 || command -v python)"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
