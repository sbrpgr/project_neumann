"""부하 재현 도구(TEST-1): 테스트를 도는 동안 CPU를 코어 수만큼 바쁘게 하고, 실패율 표를 만든다.

과부하 때만 흔들리는 시간 의존 테스트를 개발 기기에서 재현하려는 도구다. 제품 코드·pytest 설정을 건드리지 않는다.

    # 부하 없이 5회 · 부하 아래 5회, 테스트별 실패율 표(마크다운)
    python -m tests._util.cpuload --reps 5 tests/e3/test_pipeline_parallel_sim.py::test_simulated_parallel_is_faster_and_same

    # 부하만(코어 수의 2배 프로세스), 결과 JSON도 저장
    python -m tests._util.cpuload --mode load --workers 32 --json out.json tests/e4/test_loadtest_multiuser.py

    # 아무 명령이나 부하 아래에서 실행
    python -m tests._util.cpuload --run -- python -m pytest tests/e3 -q

부하 프로세스는 표준 라이브러리만 쓰는 별도 인터프리터(순수 파이썬 계산 루프)이고, 시험과 같은 우선순위로 돈다.
부모가 죽어도 `--max-s`(기본 900초) 뒤에는 스스로 끝난다. 실제 OpenAI 호출·네트워크는 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from types import TracebackType

_BURN = (
    "import sys, time\n"
    "end = time.monotonic() + float(sys.argv[1])\n"
    "x = 1.0\n"
    "while time.monotonic() < end:\n"
    "    for _ in range(20000):\n"
    "        x = x * 1.0000001 + 1e-9\n"
)

# 설정 로더보다 먼저 실제 호출을 닫는다. .env/인증값을 읽지 않고 pytest만 실행한다.
_PYTEST_BOOTSTRAP = (
    "import os,sys,socket\n"
    "os.environ['NEUMANN_LLM_PROVIDER']='mock'\n"
    "os.environ['NEUMANN_LIVE_TESTS']='0'\n"
    "os.environ.pop('NEUMANN_LIVE_LLM_OK',None)\n"
    "os.environ.pop('OPENAI_API_KEY',None)\n"
    "sys.path[:0]=['src','.']\n"
    "def audit(event,args):\n"
    "    if event=='socket.connect':\n"
    "        if sys._getframe(1).f_code is socket.socketpair.__code__ and args[1][0] in {'127.0.0.1','::1'}: return\n"
    "        raise RuntimeError('CPU load test forbids network connections')\n"
    "sys.addaudithook(audit)\n"
    "from neumann.config import Settings\n"
    "Settings.model_config['env_file']=None\n"
    "import pytest\n"
    "raise SystemExit(pytest.main(sys.argv[1:]))\n"
)


class CpuLoad:
    """with 블록 동안 `workers`개(기본: 코어 수)의 계산 프로세스를 돌린다."""

    def __init__(self, workers: int | None = None, max_s: float = 900.0) -> None:
        self.workers = workers if workers is not None else (os.cpu_count() or 4)
        self.max_s = max_s
        self._procs: list[subprocess.Popen[bytes]] = []

    def __enter__(self) -> CpuLoad:
        self._procs = [
            subprocess.Popen([sys.executable, "-c", _BURN, str(self.max_s)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            for _ in range(self.workers)
        ]
        time.sleep(0.5)  # 모두 실제로 돌기 시작할 때까지(인터프리터 기동)
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        for p in self._procs:
            p.terminate()
        for p in self._procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        self._procs = []


def _pytest_once(nodeids: list[str], extra: list[str], env: dict[str, str]) -> dict[str, tuple[str, str]]:
    """pytest를 한 번 돌려 {시험 id: (결과, 실패 요약)}를 돌려준다. 결과: passed·failed·skipped."""
    with tempfile.TemporaryDirectory() as td:
        xml = Path(td) / "r.xml"
        cmd = [sys.executable, "-c", _PYTEST_BOOTSTRAP, "-p", "no:cacheprovider", "-q", "--tb=line",
               f"--junitxml={xml}", f"--basetemp={Path(td) / 'pytest'}", *extra, *nodeids]
        try:
            proc = subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  stdin=subprocess.DEVNULL, timeout=180)
        except subprocess.TimeoutExpired:
            return {"pytest-run": ("failed", "pytest watchdog timeout (180s)")}
        out: dict[str, tuple[str, str]] = {}
        if not xml.exists():
            return {"pytest-run": ("failed", f"pytest exit {proc.returncode}: JUnit XML missing")}
        try:
            cases = list(ET.parse(xml).getroot().iter("testcase"))
        except ET.ParseError:
            return {"pytest-run": ("failed", f"pytest exit {proc.returncode}: invalid JUnit XML")}
        for tc in cases:
            name = f"{tc.get('classname', '').replace('.', '/')}.py::{tc.get('name')}"
            bad = tc.find("failure")
            if bad is None:
                bad = tc.find("error")
            if bad is not None:
                out[name] = ("failed", (bad.get("message") or "").strip().splitlines()[0][:160] if (bad.get("message") or "").strip() else "")
            elif tc.find("skipped") is not None:
                out[name] = ("skipped", "")
            else:
                out[name] = ("passed", "")
        if not out or (proc.returncode and not any(state == "failed" for state, _ in out.values())):
            out["pytest-run"] = ("failed", f"pytest exit {proc.returncode}: no reported test failure")
        return out


def measure(nodeids: list[str], reps: int, modes: tuple[str, ...], workers: int | None, extra: list[str],
            max_s: float = 900.0) -> dict:
    """모드(none·load)마다 reps회씩 돌려 시험별 {실패, 횟수, 사유}를 모은다."""
    env = {**os.environ, "NEUMANN_LLM_PROVIDER": "mock", "NEUMANN_LIVE_TESTS": "0", "PYTHONUTF8": "1"}
    env.pop("NEUMANN_LIVE_LLM_OK", None)
    env.pop("OPENAI_API_KEY", None)
    result: dict[str, dict[str, dict]] = {m: defaultdict(lambda: {"fail": 0, "n": 0, "skip": 0, "why": []}) for m in modes}
    for mode in modes:
        for rep in range(reps):
            if mode == "load":
                with CpuLoad(workers, max_s):
                    got = _pytest_once(nodeids, extra, env)
            else:
                got = _pytest_once(nodeids, extra, env)
            for tid, (state, why) in got.items():
                cell = result[mode][tid]
                if state == "skipped":
                    cell["skip"] += 1
                    continue
                cell["n"] += 1
                if state == "failed":
                    cell["fail"] += 1
                    cell["why"].append(why)
            print(f"[{mode} {rep + 1}/{reps}] " + " ".join({"failed": "F", "skipped": "S", "passed": "."}[s] for s, _ in got.values()),
                  file=sys.stderr, flush=True)
    return {m: dict(v) for m, v in result.items()}


def table(res: dict, modes: tuple[str, ...], only_failing: bool = False) -> str:
    ids = sorted({tid for m in modes for tid in res[m]})
    if only_failing:
        ids = [t for t in ids if any(res[m].get(t, {}).get("fail") for m in modes)]
    head = "| 시험 | " + " | ".join({"none": "부하 없음", "load": "부하 아래"}[m] for m in modes) + " |"
    rows = [head, "|---|" + "---:|" * len(modes)]
    for tid in ids:
        cells = []
        for m in modes:
            c = res[m].get(tid)
            cells.append("-" if not c else f"{c['fail']}/{c['n']}" + (f" (skip {c['skip']})" if c.get("skip") else ""))
        rows.append(f"| `{tid}` | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=5, help="모드마다 반복 횟수(기본 5)")
    ap.add_argument("--mode", choices=("both", "none", "load"), default="both")
    ap.add_argument("--workers", type=int, default=None, help="부하 프로세스 수(기본: 코어 수)")
    ap.add_argument("--max-s", type=float, default=900.0, help="부하 프로세스 자동 종료 시간")
    ap.add_argument("--json", type=Path, default=None, help="결과를 JSON으로 저장")
    ap.add_argument("--only-failing", action="store_true", help="한 번이라도 실패한 시험만 표에 싣는다")
    ap.add_argument("--run", action="store_true", help="`--` 뒤 명령을 부하 아래에서 한 번 실행하고 종료 코드를 돌려준다")
    ap.add_argument("rest", nargs="*", help="pytest 시험 id(--run이면 실행할 명령)")
    args = ap.parse_args(argv)
    if args.reps < 1 or (args.workers is not None and args.workers < 1) or args.max_s <= 0:
        ap.error("reps/workers/max-s must be positive")
    if not args.rest:
        ap.error("targeted test ids (or --run command) are required")
    if args.run:
        with CpuLoad(args.workers, args.max_s):
            return subprocess.run(args.rest).returncode
    modes = ("none", "load") if args.mode == "both" else (args.mode,)
    res = measure(args.rest, args.reps, modes, args.workers, [], args.max_s)
    print(table(res, modes, args.only_failing))
    for m in modes:
        for tid, c in sorted(res[m].items()):
            for why in sorted(set(c["why"])):
                print(f"- [{m}] {tid}: {why}")
    if args.json:
        args.json.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(any(c["fail"] for rows in res.values() for c in rows.values())
               or not any(c["n"] for rows in res.values() for c in rows.values()))


if __name__ == "__main__":
    raise SystemExit(main())
