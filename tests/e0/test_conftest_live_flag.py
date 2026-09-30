"""루트 conftest: 라이브 테스트 요청에 허용 플래그가 없으면 조용히 건너뛰지 않고 실패한다(종료 코드 0 함정 방지)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("NEUMANN_LIVE_TESTS", "NEUMANN_LIVE_LLM_OK")}
    env.update({"NEUMANN_LLM_PROVIDER": "mock", "PYTHONIOENCODING": "utf-8", **env_extra})
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/e0/test_sec3_live_guard.py", "-k", "conftest_closes"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )


def test_live_tests_without_flag_is_usage_error():
    r = _run({"NEUMANN_LIVE_TESTS": "1"})
    assert r.returncode != 0
    assert "NEUMANN_LIVE_LLM_OK" in (r.stdout + r.stderr)


def test_normal_run_is_unaffected():
    r = _run({})
    assert r.returncode == 0, r.stdout + r.stderr
