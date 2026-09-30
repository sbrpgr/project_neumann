"""VER-FIN C-3 / F-17 회귀: 단위 거듭제곱 사슬(m^3^3^3^3)은 Pint에 닿기 전에 문법에서 거절된다.

Pint는 ``^`` 사슬을 오른쪽 결합 정수 거듭제곱으로 계산해 끝나지 않고 GIL까지 잡는다. 그래서 별도 프로세스에서 돌리고
프로세스 타임아웃을 걸며, 각 호출이 100 ms 안에 unchecked로 끝나는지 잰다(Pint import·레지스트리 준비는 시간에서 뺀다).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = r"""
import time
from neumann.analyze import final_tools as ft
from neumann.finalize.tools import dimension
dimension.warmup()
BAD = ["m^3^3^3^3", "m**3**3**3", "(m^3)^3^3", "m^(3^3)", "m^3^3", "m" * 10_000, "m^" + "3^" * 5000 + "3"]
worst = 0.0
bad = []
for unit in BAD:
    t = time.perf_counter()
    out = dimension.run({"left": {"value": 1, "unit": unit}, "right": {"value": 1, "unit": "m"}, "operation": "add"})
    worst = max(worst, time.perf_counter() - t)
    if out.get("verdict") != "unchecked":
        bad.append(("dimension", unit[:12]))
    plan = f"합산 4 {unit[:40]}\n5 m"
    check = {"check_id": "u", "kind": "units", "plan_lines": [1, 2], "params": {
        "sources": [{"line": 1, "quote": plan.splitlines()[0]}, {"line": 2, "quote": "5 m"}], "operation": "addition",
        "left": {"source": 0, "value": 4, "unit": unit}, "right": {"source": 1, "value": 5, "unit": "m"}}}
    t = time.perf_counter()
    row = ft.run_tool_checks(plan, [check])[0]
    worst = max(worst, time.perf_counter() - t)
    if row["status"] != "unchecked":
        bad.append(("final_tools", unit[:12]))
ok_dim = dimension.run({"left": {"value": 1, "unit": "m^3"}, "right": {"value": 1, "unit": "L"}, "operation": "add"})
print(f"WORST {worst:.4f} BAD {bad} OK {ok_dim['verdict']}")
"""


def test_exponent_chains_are_rejected_before_pint_within_100ms():
    env = {k: v for k, v in os.environ.items() if k in ("SYSTEMROOT", "SystemRoot", "PATH", "TEMP", "TMP", "USERPROFILE",
                                                         "LOCALAPPDATA", "APPDATA", "HOME")}
    env.update(PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]), PYTHONUTF8="1",
               NEUMANN_LLM_PROVIDER="mock", NEUMANN_LIVE_LLM_OK="0")
    proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=180)
    assert proc.returncode == 0, f"exit {proc.returncode:#x}"
    line = proc.stdout.strip().splitlines()[-1]
    worst = float(line.split()[1])
    assert "BAD []" in line and line.endswith("OK pass"), line
    assert worst < 0.1, line
