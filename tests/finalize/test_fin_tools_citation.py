"""citation_lookup·근거 조회: MCP 백엔드(코퍼스·Retraction Watch)를 fixture 데이터로. 정상·경계·적대·시간.

도구는 환경변수·.env를 읽지 않는다: 백엔드를 정하지 않으면 unchecked(backend_not_configured)다.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from neumann.finalize.tools import ToolCall, ToolRegistry
from neumann.finalize.tools import citation
from neumann.finalize.tools.fin_tools import register_all
from tests.finalize.fin_tools_backend import RETRACTED_DOI, build_backend

TITLE = "[FAKE] EquiMol: equivariant message passing for molecular property prediction"


@pytest.fixture(scope="module")
def backend(tmp_path_factory: pytest.TempPathFactory):
    be = build_backend(Path(tmp_path_factory.mktemp("fin_tools_cite")))
    citation.set_backend(be, timeout_s=10.0)
    yield be
    citation.set_backend(None)


# (args, verdict, 추가 기대)
CASES = [
    ({"doi": RETRACTED_DOI}, "fail", {"retracted": True, "reason": "retracted_or_concern"}),
    ({"doi": f"https://doi.org/{RETRACTED_DOI.upper()}"}, "fail", {"retracted": True}),   # 정규화
    ({"doi": "10.9999/not.retracted"}, "unchecked", {"retracted": False, "reason": "not_verifiable_in_corpus"}),
    ({"title": TITLE}, "pass", {"found": True}),
    ({"title": TITLE.lower().replace(":", "")}, "pass", {"found": True}),                  # 표기 차이
    ({"title": "A completely different study about volcano seismology"}, "unchecked", {"found": False}),
    ({"title": TITLE, "doi": "10.9999/not.retracted"}, "pass", {"found": True, "retracted": False}),
    ({"title": TITLE, "doi": RETRACTED_DOI}, "fail", {"retracted": True}),
    ({"doi": "not-a-doi"}, "unchecked", {"reason": "invalid_doi"}),
]


@pytest.mark.parametrize("args,verdict,extra", CASES)
def test_citation_lookup(backend, args, verdict, extra):
    out = citation.run(args)
    assert out["verdict"] == verdict, out
    for k, v in extra.items():
        assert out[k] == v, (k, out)


def test_retraction_record_carries_source_links(backend):
    out = citation.run({"doi": RETRACTED_DOI})
    rec = out["post_status"][0]
    assert rec["kind"] == "retraction" and rec["notice_url"].startswith("https://doi.org/")
    assert rec["source_url"].startswith("https://") and out["engine"] == "mcp_backend"


@pytest.mark.parametrize("args", [{}, {"doi": 3}, {"title": ""}, {"title": "x" * 301}, {"doi": "10.1/x", "year": 3},
                                  {"doi": "10.1/x", "sql": "drop"}, {"title": ["a"]}, [], "10.1/x"])
def test_invalid_args(backend, args):
    assert citation.run(args) == {"verdict": "unchecked", "reason": "invalid_args"}


def test_unconfigured_backend_is_unchecked_and_reads_no_environment(monkeypatch):
    citation.set_backend(None)
    monkeypatch.setenv("NEUMANN_DATA_DIR", "Z:/should/not/be/read")
    assert citation.run({"doi": RETRACTED_DOI}) == {"verdict": "unchecked", "reason": "backend_not_configured"}
    assert citation.search_prior_work("molecular property") == {"error": "backend_not_configured"}


def test_slow_backend_times_out_through_registry(backend):
    gate = threading.Event()
    slow = SimpleNamespace(normalize_doi=lambda d: gate.wait(5) and None, get_post_status=lambda d: [])
    citation.set_backend(slow, timeout_s=0.2)
    reg = ToolRegistry()
    register_all(reg)
    try:
        t0 = time.perf_counter()
        res = reg.run(ToolCall("citation_lookup", {"doi": RETRACTED_DOI}))
        assert time.perf_counter() - t0 < 5.0  # 0.2초 상한 + 부하 여유
        assert res.verdict == "unchecked" and res.error == "timeout"
    finally:
        gate.set()
        citation.set_backend(backend, timeout_s=10.0)


def test_backend_error_text_does_not_leak(backend):
    def boom(_):
        raise RuntimeError("secret path C:/private/key=abc")

    citation.set_backend(SimpleNamespace(normalize_doi=boom))
    reg = ToolRegistry()
    register_all(reg)
    try:
        res = reg.run(ToolCall("citation_lookup", {"doi": RETRACTED_DOI}))
        assert res.error == "tool_error" and "secret" not in str(res.as_dict())
    finally:
        citation.set_backend(backend, timeout_s=10.0)


def test_evidence_helpers(backend):
    hits = citation.search_prior_work("equivariant message passing molecular", 3)
    assert hits["hits"] and hits["hits"][0]["work_id"].startswith("fixture:") and hits["hits"][0]["url"]
    assert citation.search_prior_work("x" * 301) == {"error": "invalid_args"}
    rec = citation.review_records(hits["hits"][0]["work_id"])
    assert rec["work"]["work_id"] == hits["hits"][0]["work_id"] and "reviews" in rec
    assert citation.review_records("fixture:does-not-exist") == {"error": "not_found"}
