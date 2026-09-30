"""VER-FIN C-1 회귀: Z3를 여러 스레드가 동시에 불러도 프로세스가 죽지 않는다(전역 컨텍스트 공유 금지).

Z3 전역 컨텍스트 경합은 파이썬 예외가 아니라 프로세스 강제 종료(0xC0000374·0xC0000005)로 나타나므로, 별도 프로세스에서
4스레드 × 20회를 돌리고 종료 코드 0과 결과 개수·판정을 확인한다. 실제 API 호출·환경 비밀값은 쓰지 않는다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = r"""
import threading
from neumann.analyze import final_tools as ft
try:  # FIN-TOOLS arithmetic_sum도 같은 Z3 잠금을 쓴다(있으면 함께 두드린다)
    from neumann.finalize.tools import sums
except ImportError:
    sums = None

def check(limit):
    plan = f"총 3\n항목 4\n최대 {limit}"
    sources = [{"line": i + 1, "quote": line} for i, line in enumerate(plan.splitlines())]
    return plan, {"check_id": "c", "kind": "constraint", "plan_lines": [1, 2, 3], "params": {
        "sources": sources, "operation": "sum", "terms": [{"source": 0, "value": 3}, {"source": 1, "value": 4}],
        "comparator": "le", "limit": {"source": 2, "value": limit}}}

results, errors = [], []

def worker(n):
    try:
        for i in range(20):
            limit = 10 if (n + i) % 2 else 6
            plan, c = check(limit)
            got = ft.run_tool_checks(plan, [c] * 16)
            want = "passed" if limit == 10 else "failed"
            results.append(all(r["status"] == want for r in got) and len(got) == 16)
            if sums is not None:
                s = sums.run({"items": [3, 4], "total": 7 if i % 2 else 8})
                results.append(s["verdict"] == ("pass" if i % 2 else "fail") and s["engine"] == "fraction+z3")
    except Exception as exc:
        errors.append(type(exc).__name__)

threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
for t in threads: t.start()
for t in threads: t.join()
expected = 160 if sums is not None else 80
print("OK" if not errors and len(results) == expected and all(results) else f"BAD {errors} {len(results)} {results.count(False)}")
"""


def _clean_env() -> dict[str, str]:
    keep = ("SYSTEMROOT", "SystemRoot", "PATH", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HOME")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env.update(PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]), PYTHONUTF8="1",
               NEUMANN_LLM_PROVIDER="mock", NEUMANN_LIVE_LLM_OK="0")
    return env


def test_concurrent_z3_checks_do_not_crash_the_process():
    for _ in range(2):
        proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=_clean_env(), capture_output=True,
                              text=True, encoding="utf-8", timeout=300)
        assert proc.returncode == 0, f"exit {proc.returncode:#x}"
        assert proc.stdout.strip().endswith("OK"), proc.stdout[-300:]
