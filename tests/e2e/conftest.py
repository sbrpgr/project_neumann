"""E5-L0e2e 라이브 E2E 옵션과 실행 기록.

    NEUMANN_LIVE_TESTS=1 python -m pytest tests/e2e/test_live.py -v --e2e-base-url http://127.0.0.1:8010

옵션(또는 환경변수)
- ``--e2e-base-url`` / ``NEUMANN_E2E_BASE_URL``: 대상 서버(기본 http://127.0.0.1:8010)
- ``--e2e-timeout`` / ``NEUMANN_E2E_TIMEOUT``: 계획서 1건 분석 대기 상한(초, 기본 300)
- ``--e2e-out`` / ``NEUMANN_E2E_OUT``: 스크린샷·요약 JSON 폴더(기본 docs/reports)

기본 pytest(``NEUMANN_LIVE_TESTS``가 1이 아님)에서는 라이브 테스트가 건너뛰어진다.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "http://127.0.0.1:8010"
DEFAULT_TIMEOUT_S = 300.0
PREFIX = "E5-L0e2e"

# 한 번의 실행에서 계획서별 측정값을 모은다(세션 끝에 요약 JSON과 터미널 요약으로 낸다).
RUN_LOG: dict[str, Any] = {"plans": {}}


def pytest_addoption(parser: pytest.Parser) -> None:
    g = parser.getgroup("neumann-e2e")
    g.addoption("--e2e-base-url", action="store", default=None, help="E2E 대상 서버 base URL")
    g.addoption("--e2e-timeout", action="store", default=None, help="계획서 1건 분석 대기 상한(초)")
    g.addoption("--e2e-out", action="store", default=None, help="스크린샷·요약 JSON 폴더")


def _opt(config: pytest.Config, name: str, env: str, default: Any) -> Any:
    try:
        v = config.getoption(name, default=None)
    except ValueError:  # 옵션이 등록되지 않은 실행(전체 pytest 등)
        v = None
    return v or os.getenv(env) or default


@pytest.fixture(scope="session")
def e2e_base_url(pytestconfig: pytest.Config) -> str:
    return str(_opt(pytestconfig, "--e2e-base-url", "NEUMANN_E2E_BASE_URL", DEFAULT_BASE_URL)).rstrip("/") + "/"


@pytest.fixture(scope="session")
def e2e_timeout_s(pytestconfig: pytest.Config) -> float:
    return float(_opt(pytestconfig, "--e2e-timeout", "NEUMANN_E2E_TIMEOUT", DEFAULT_TIMEOUT_S))


@pytest.fixture(scope="session")
def e2e_out(pytestconfig: pytest.Config) -> Path:
    out = Path(_opt(pytestconfig, "--e2e-out", "NEUMANN_E2E_OUT", ROOT / "docs" / "reports"))
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.fixture(scope="session")
def run_log(e2e_base_url: str, e2e_timeout_s: float, e2e_out: Path):
    RUN_LOG.update({"base_url": e2e_base_url, "timeout_s": e2e_timeout_s,
                    "started_at": datetime.now(UTC).isoformat(timespec="seconds")})
    yield RUN_LOG
    RUN_LOG["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    mode = RUN_LOG.get("mode", "unknown")
    path = e2e_out / f"{PREFIX}_{mode}_summary.json"
    path.write_text(json.dumps(RUN_LOG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    RUN_LOG["summary_path"] = str(path)


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:  # noqa: ANN001
    plans = RUN_LOG.get("plans") or {}
    if not plans:
        return
    tr = terminalreporter
    tr.section("E5-L0e2e 라이브 E2E 요약")
    tr.write_line(f"대상 {RUN_LOG.get('base_url')} · 모드 {RUN_LOG.get('mode')} · 상한 {RUN_LOG.get('timeout_s')}s")
    for name, p in plans.items():
        t = p.get("timings") or {}
        tr.write_line(
            f"- {name}: {'PASS' if not p.get('failures') else 'FAIL'} · 카드 {p.get('n_cards')} · "
            f"화면 전체 {t.get('ui_total_s')}s(응답 {t.get('ui_response_s')}s) · 서버 {t.get('view_server_elapsed_s')}s · "
            f"단계 {t.get('view_phase_s')} · /premortem {t.get('api_premortem_s', '-')}s · 연결 {(p.get('linkage') or {}).get('summary', '-')}")
        for f in p.get("failures") or []:
            tr.write_line(f"    ✗ {f}")
    if RUN_LOG.get("summary_path"):
        tr.write_line(f"요약 JSON: {RUN_LOG['summary_path']}")
