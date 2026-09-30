"""TEST-1 부하 도구가 수집 실패·skip을 성공으로 숨기지 않는다."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._util import cpuload


@pytest.mark.parametrize("xml,code", [
    (None, 2), ("not xml", 2), ("<testsuites/>", 0),
    ('<testsuites><testcase classname="tests.x" name="ok"/></testsuites>', 2),
])
def test_incomplete_pytest_run_is_a_failure(monkeypatch, xml, code):
    def run(cmd, **kwargs):
        if xml is not None:
            path = next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--junitxml="))
            Path(path).write_text(xml, encoding="utf-8")
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(cpuload.subprocess, "run", run)
    out = cpuload._pytest_once(["tests/x.py"], [], {})
    assert out["pytest-run"][0] == "failed"


def test_watchdog_timeout_is_a_failure(monkeypatch):
    def run(cmd, **kwargs):
        raise cpuload.subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(cpuload.subprocess, "run", run)
    assert cpuload._pytest_once(["tests/x.py"], [], {})["pytest-run"] == (
        "failed", "pytest watchdog timeout (180s)",
    )


def test_skip_count_is_visible_and_not_a_pass(monkeypatch):
    monkeypatch.setattr(cpuload, "_pytest_once", lambda *args: {"tests/x.py::live": ("skipped", "")})
    out = cpuload.measure(["tests/x.py"], 2, ("none",), None, [])
    cell = out["none"]["tests/x.py::live"]
    assert cell["n"] == 0 and cell["skip"] == 2
    assert "0/0 (skip 2)" in cpuload.table(out, ("none",))


def test_cli_returns_nonzero_for_failed_measurement(monkeypatch):
    monkeypatch.setattr(cpuload, "measure", lambda *args: {
        "none": {"pytest-run": {"fail": 1, "n": 1, "skip": 0, "why": ["collection failed"]}},
    })
    assert cpuload.main(["--mode", "none", "--reps", "1", "tests/missing.py"]) == 1


def test_all_skips_do_not_make_cli_success(monkeypatch):
    monkeypatch.setattr(cpuload, "measure", lambda *args: {
        "none": {"live": {"fail": 0, "n": 0, "skip": 1, "why": []}},
    })
    assert cpuload.main(["--mode", "none", "--reps", "1", "tests/live.py"]) == 1


def test_load_duration_reaches_workers(monkeypatch):
    got = []

    class Load:
        def __init__(self, workers, max_s):
            got.append((workers, max_s))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(cpuload, "CpuLoad", Load)
    monkeypatch.setattr(cpuload, "_pytest_once", lambda *args: {"t": ("passed", "")})
    cpuload.measure(["t"], 1, ("load",), 2, [], max_s=10)
    assert got == [(2, 10)]
