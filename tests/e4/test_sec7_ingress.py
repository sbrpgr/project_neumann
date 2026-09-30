"""Synthetic SEC7 pre-normalization ingress regressions; no product API calls."""
from __future__ import annotations

import asyncio
import json
import re
import time
from types import MappingProxyType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import jobs, main, serving, upload
from neumann.models import PlanDocument, normalize_text


def forbidden(*args, **kwargs):
    pytest.fail("rejected raw input reached normalization/hash/model/pipeline allocation")


@pytest.mark.parametrize("text,status", [
    ("가" * 800_001, 413),
    ("\u0301" * 400_000 + "\u0316" * 400_001, 413),
    ("x\u2028" * 5000 + "x", 422),
    ("x\n" * 5000 + "x", 422),
], ids=["hangul-800001", "combining-800001", "unicode-5001-lines", "lf-5001-lines"])
def test_upload_rejects_before_nfc(monkeypatch, text, status):
    calls = []

    def normalize(*args):
        calls.append(1)
        return forbidden()

    monkeypatch.setattr(upload, "normalize_text", normalize)
    started = time.monotonic()
    with pytest.raises(upload.UploadRejected) as exc:
        upload.extract_plan("synthetic.txt", text.encode("utf-8"))
    assert exc.value.status_code == status
    assert calls == []
    assert time.monotonic() - started < 5  # safety ceiling, not a CPU benchmark


@pytest.mark.parametrize("handler", [main.premortem, main.premortem_view])
def test_sync_direct_gate_before_input_info_or_pipeline(monkeypatch, handler):
    monkeypatch.setattr(main, "_load_pipeline", forbidden)
    monkeypatch.setattr(main, "_input_info", forbidden)
    response = asyncio.run(handler(main.PremortemRequest(plan_text="x\u2028" * 5000 + "x")))
    assert response.status_code == 422
    assert json.loads(response.body)["error_code"] == "too_many_lines"


def test_jobs_direct_gate_before_admission(monkeypatch):
    srv = serving.Serving(serving.ServingConfig())
    store = jobs.install(FastAPI(), srv=srv, load_pipeline=lambda: forbidden())
    monkeypatch.setattr(store, "_make_room", forbidden)
    monkeypatch.setattr(serving, "plan_key", forbidden)
    response = store.submit(jobs.JobRequest(plan_text="x\u2028" * 5000 + "x"), serving.RequestCtx(ticket="raw-test"))
    assert response.status_code == 422
    assert len(store) == 0


@pytest.mark.parametrize("path", ["/premortem", "/premortem/view", "/premortem/jobs"])
def test_analysis_middleware_gate_before_hash(monkeypatch, path):
    app = FastAPI()
    srv = serving.Serving(serving.ServingConfig())
    if path == "/premortem/jobs":
        srv.protect(path, "analysis", async_=True)  # jobs.install registers this route
    serving.install(app, srv)
    monkeypatch.setattr(serving, "plan_key", forbidden)

    @app.post(path)
    async def no_execution():
        return forbidden()

    response = TestClient(app).post(path, json={"plan_text": "x\u2028" * 5000 + "x"})
    assert response.status_code == 422
    assert response.json()["error_code"] == "too_many_lines"






@pytest.mark.parametrize("separator", ["\n", "\r\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_shared_line_boundary_without_split(separator):
    from neumann.api.plan_limits import PlanLimitError, check_plan_text

    class NoSplit(str):
        def split(self, *args, **kwargs):
            return forbidden()

        def splitlines(self, *args, **kwargs):
            return forbidden()

    text = NoSplit(separator.join(["x"] * 5000))
    assert check_plan_text(text) is text
    with pytest.raises(PlanLimitError) as exc:
        check_plan_text(text + separator + "x")
    assert exc.value.status_code == 422


def test_shared_char_and_aggregate_boundaries():
    from neumann.api.plan_limits import PlanLimitError, check_embedded_plan, check_payload_plan, check_plan_text

    text = "\U0001f600" * 200_000
    assert len(text.encode("utf-8")) == 800_000
    assert check_plan_text(text) is text
    with pytest.raises(PlanLimitError) as exc:
        check_plan_text(text + "x")
    assert exc.value.status_code == 413
    lines = [{"text": "x" * 99_999}, {"text": "x" * 100_000}]
    check_embedded_plan(lines)  # 200,000 including the joining LF
    lines[1]["text"] += "x"
    with pytest.raises(PlanLimitError) as exc:
        check_payload_plan(MappingProxyType({"result": MappingProxyType({"plan": {"lines": lines}})}))
    assert exc.value.status_code == 413
    check_embedded_plan([{"text": "x\u2028x"}, {"text": "x"}], max_lines=3)
    with pytest.raises(PlanLimitError) as exc:
        check_embedded_plan([{"text": "x\u2028x"}, {"text": "x"}], max_lines=2)
    assert exc.value.status_code == 422


def test_upload_raw_and_pre_nfc_boundaries(monkeypatch):
    from neumann.api.plan_limits import MAX_RAW_UPLOAD_CHARS, PlanLimitError, prepare_upload_text

    monkeypatch.setattr(upload, "normalize_text", forbidden)
    with pytest.raises(upload.UploadRejected) as exc:
        upload._clean("x" * (MAX_RAW_UPLOAD_CHARS + 1), collapse_blank=False)
    assert exc.value.status_code == 413
    assert prepare_upload_text("x" * 200_000, collapse_blank=False) == "x" * 200_000
    with pytest.raises(PlanLimitError) as exc:
        prepare_upload_text("x" * 200_001, collapse_blank=False)
    assert exc.value.status_code == 413
    with pytest.raises(PlanLimitError) as exc:
        prepare_upload_text("\u2028" * 100_000, collapse_blank=True)
    assert exc.value.status_code == 422
    assert prepare_upload_text("a\n" + "\n" * 99997 + "b", collapse_blank=True) == "a\n\nb"


@pytest.mark.parametrize("collapse", [False, True])
@pytest.mark.parametrize("text", [
    "\r\n한글 e\u0301\t끝  \r\n다음\n\n\n줄\r\n",
    "e\x00\u0301 \n\t본문\x1c\x85\u2028끝\u2029",
    "a\n \x00\n  \n  \nb\u00a0\n",
    "x" * 50_000,
    "\n".join(["x"] * 5000),
], ids=["nfd-crlf", "composition-controls", "control-blank-padding", "chars-50000", "lines-5000"])
def test_valid_upload_output_hash_and_offsets_unchanged(text, collapse):
    # Pre-change cleaner is the equivalence oracle, independent of the new guard.
    expected = normalize_text(text).translate(upload._CONTROL_TO_NEWLINE)
    expected = upload._CONTROL_RE.sub("", expected)
    expected = "\n".join(line.rstrip() for line in expected.split("\n"))
    if collapse:
        expected = re.sub(r"\n{3,}", "\n\n", expected)
    expected = expected.strip("\n")
    actual = upload._clean(text, collapse_blank=collapse)
    assert actual == expected
    before = PlanDocument.from_text(expected, "synthetic")
    after = PlanDocument.from_text(actual, "synthetic")
    assert after.plan_id == before.plan_id
    assert after.model_dump() == before.model_dump()
    for start in (0, len(actual) // 2):
        assert actual[start:start + 3] == expected[start:start + 3]


def test_upload_guard_mutation_is_detected(monkeypatch):
    # Re-enable the old NFC-first behavior in memory; the same sentinel must fail.
    monkeypatch.setattr(upload, "prepare_upload_text", lambda text, **kwargs: text)
    monkeypatch.setattr(upload, "normalize_text", forbidden)
    with pytest.raises(pytest.fail.Exception, match="rejected raw input"):
        upload.extract_plan("synthetic.txt", ("가" * 800_001).encode("utf-8"))


@pytest.mark.parametrize("padding", ["leading", "trailing", "collapsed"])
def test_permitted_blank_padding_does_not_consume_pre_nfc_budget(padding):
    from neumann.api.plan_limits import prepare_upload_text

    body = "한" * 50_000  # 150k pre-NFC -> 50k NFC; normalization is not timed here
    blanks = "\n" * 99_999
    text = blanks + body if padding == "leading" else body + blanks
    expected = body
    if padding == "collapsed":
        text += "b"
        expected += "\n\nb"
    assert prepare_upload_text(text, collapse_blank=padding == "collapsed") == expected
