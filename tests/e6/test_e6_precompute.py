"""E6-L2a: scripts/precompute_demo.py — 사전 계산본과 매니페스트.

실제 파이프라인·API를 부르지 않는다. 파이프라인은 없음(fixture 대체)과 가짜 run_premortem 두 경우로 잰다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from neumann.config import get_settings
from neumann.models import PlanDocument, PremortemResult
from tests.e6.e6_support import ROOT, SCRIPT, block_external_network, fake_pipeline_result, load_script
from tests.fixtures.loader import DEMO_PLANS, plan_text

pd = load_script()
MISSING = (lambda: (None, "neumann.pipeline 모듈 없음"))  # noqa: E731
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _quiet(_msg: str) -> None:
    pass


def _fake_loader(calls: list[tuple[str, str]], fail_on: str | None = None):
    def run_premortem(text: str, *, session_id: str | None = None) -> PremortemResult:
        assert session_id is not None
        calls.append((session_id, text))
        if fail_on and session_id.endswith(fail_on):
            raise RuntimeError("provider blew up: LEAKMARKER-7781")
        return PremortemResult.model_validate(fake_pipeline_result(text, session_id))

    return lambda: (run_premortem, pd.PIPELINE_IMPL)


def _read(out: Path, entry: dict) -> tuple[bytes, dict]:
    data = (out / entry["file"]).read_bytes()
    return data, json.loads(data.decode("utf-8"))


def test_demo_plans_are_the_fixture_demo_plans():
    assert pd.DEMO_PLANS == DEMO_PLANS
    assert [s.demo for s in pd.demo_specs()] == ["plan", "plan_elife_neuro", "plan_medimaging"]
    assert all(s.path.is_file() and s.public_fixture for s in pd.demo_specs())


def test_fixture_mode_writes_results_and_manifest_offline(tmp_path):
    out = tmp_path / "precomputed"
    with block_external_network() as attempts:
        manifest, failures = pd.build(pd.demo_specs(), out, source="fixture", log=_quiet)
    assert attempts == []
    assert failures == []
    assert manifest["kind"] == "neumann.precomputed" and manifest["source"] == "fixture"
    assert manifest["pipeline"]["available"] is False
    assert ISO_Z.match(manifest["generated_at"])
    on_disk = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest

    entries = {e["demo"]: e for e in manifest["entries"]}
    assert list(entries) == ["plan", "plan_elife_neuro", "plan_medimaging"]
    for demo, entry in entries.items():
        data, raw = _read(out, entry)
        # 매니페스트 sha256·바이트가 실제 파일과 같다
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["bytes"] == len(data)
        assert entry["file"] == f"{entry['plan_id']}.json"
        # plan_id는 계획서 본문의 sha256(PlanDocument 규칙)
        assert entry["plan_id"] == PlanDocument.from_text(plan_text(f"{demo}.md"), "x").plan_id
        assert ISO_Z.match(entry["generated_at"]) and entry["elapsed_s"] >= 0
        assert set(entry["cards_by_generator"]) == {"astra", "rule", "mock"}
        assert sum(entry["cards_by_generator"].values()) == entry["cards_total"]
        # 대체 사실이 결과 안에 정직하게 남는다
        result = PremortemResult.model_validate(raw)
        assert result.status == "degraded" and entry["status"] == "degraded"
        assert entry["source"] == "fixture" and entry["impl"] == "fallback:fixture"
        assert "precompute_source" in entry["degraded_stages"]
        assert any(s.impl == "fallback:fixture" and s.state == "degraded" for s in result.stages)
        assert result.notices[0].startswith("[대체] 분석 파이프라인 미연결")
        assert entry["plan_text_included"] is True and result.plan is not None

    # plan.md는 fixture 카드 2장(mock) — mock을 astra라고 세지 않는다
    assert entries["plan"]["cards_total"] == 2
    assert entries["plan"]["cards_by_generator"] == {"astra": 0, "rule": 0, "mock": 2}
    assert manifest["llm"] is None and all(e["models"] == [] for e in entries.values())  # 대체본에 모델을 지어 붙이지 않는다
    # fixture가 없는 계획서는 카드를 지어내지 않고 사유를 남긴다
    for demo in ("plan_elife_neuro", "plan_medimaging"):
        _, raw = _read(out, entries[demo])
        assert entries[demo]["cards_total"] == 0 and raw["risk_cards"] == []
        assert "fixture 결과가 없어" in raw["risk_synthesis"]["no_card_reason"]


def test_auto_falls_back_to_fixture_when_pipeline_missing(tmp_path):
    manifest, failures = pd.build(pd.demo_specs(), tmp_path, source="auto", pipeline_loader=MISSING, log=_quiet)
    assert failures == []
    assert manifest["source"] == "fixture"
    assert manifest["pipeline"] == {"available": False, "impl": "fallback:fixture", "note": "neumann.pipeline 모듈 없음"}
    raw = _read(tmp_path, manifest["entries"][0])[1]
    assert "neumann.pipeline 모듈 없음" in raw["notices"][0]


def test_pipeline_required_but_missing_fails_without_writing(tmp_path, monkeypatch, capsys):
    manifest, failures = pd.build(pd.demo_specs(), tmp_path / "a", source="pipeline", pipeline_loader=MISSING, log=_quiet)
    assert manifest == {} and "파이프라인 필수" in failures[0]["error"]
    assert not (tmp_path / "a").exists()

    monkeypatch.setattr(pd, "load_pipeline", MISSING)
    assert pd.main(["--source", "pipeline", "--out", str(tmp_path / "b")]) == 1
    assert not (tmp_path / "b" / "manifest.json").exists()
    assert "파이프라인 필수" in capsys.readouterr().out


def test_pipeline_mode_calls_run_premortem_and_counts_by_generator(tmp_path):
    calls: list[tuple[str, str]] = []
    with block_external_network() as attempts:
        manifest, failures = pd.build(pd.demo_specs(), tmp_path, source="auto", pipeline_loader=_fake_loader(calls), log=_quiet)
    assert attempts == [] and failures == []
    assert [sid for sid, _ in calls] == ["precomputed-plan", "precomputed-plan_elife_neuro", "precomputed-plan_medimaging"]
    assert [text for _, text in calls] == [plan_text(n) for n in DEMO_PLANS]  # 원문 그대로 넘긴다
    assert manifest["source"] == "pipeline" and manifest["pipeline"]["available"] is True
    entries = {e["demo"]: e for e in manifest["entries"]}
    assert entries["plan"]["impl"] == "neumann.pipeline:run_premortem"
    assert entries["plan"]["cards_by_generator"] == {"astra": 1, "rule": 1, "mock": 0}
    assert entries["plan"]["models"] == ["gpt-6-astra"]  # astra 카드의 model
    assert entries["plan_medimaging"]["cards_total"] == 0 and entries["plan_medimaging"]["models"] == []
    s = get_settings()
    assert manifest["llm"] == {"provider": s.llm_provider, "model": s.llm_model}  # 이름만(비밀값 없음)
    raw = _read(tmp_path, entries["plan"])[1]
    assert not any(n.startswith("[대체]") for n in raw["notices"])  # 실제 경로엔 대체 표시가 없다
    assert raw["session_id"] == "precomputed-plan"
    # 카드 0장·건너뛴 단계는 status가 ok여도 경고로 드러낸다
    assert entries["plan"]["warnings"] == []
    assert entries["plan_medimaging"]["warnings"] == ["카드 0장: 가짜 파이프라인: 카드 없음", "건너뛴 단계: search"]


def test_empty_pipeline_result_fails_unless_allowed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pd, "load_pipeline", _fake_loader([]))
    assert pd.main(["--source", "pipeline", "--out", str(tmp_path / "a")]) == 1
    out = capsys.readouterr().out
    assert "카드 0장: plan_elife_neuro, plan_medimaging" in out and "경고 plan_medimaging" in out
    assert pd.main(["--source", "pipeline", "--out", str(tmp_path / "b"), "--allow-empty"]) == 0


def test_pipeline_failure_is_recorded_without_exception_text(tmp_path, monkeypatch, capsys):
    calls: list[tuple[str, str]] = []
    manifest, failures = pd.build(
        pd.demo_specs(), tmp_path, source="pipeline", pipeline_loader=_fake_loader(calls, fail_on="plan_elife_neuro"), log=_quiet
    )
    assert [e["demo"] for e in manifest["entries"]] == ["plan", "plan_medimaging"]  # 나머지는 계속 만든다
    assert failures == [{"demo": "plan_elife_neuro", "error": "분석 실패(RuntimeError)"}]
    assert manifest["failures"] == failures
    assert b"LEAKMARKER" not in (tmp_path / "manifest.json").read_bytes()  # 예외 메시지(비밀값 우려)를 남기지 않는다

    monkeypatch.setattr(pd, "load_pipeline", _fake_loader([], fail_on="plan_elife_neuro"))
    assert pd.main(["--source", "pipeline", "--out", str(tmp_path / "m")]) == 1  # 실패를 숨기지 않는다
    assert "실패 plan_elife_neuro" in capsys.readouterr().out


def test_non_demo_plan_is_stored_without_plan_body(tmp_path):
    copy = tmp_path / "user_plan.md"
    copy.write_text(plan_text("plan.md"), encoding="utf-8")
    manifest, failures = pd.build([pd.PlanSpec("user_plan", copy)], tmp_path / "out", source="fixture", log=_quiet)
    assert failures == []
    entry = manifest["entries"][0]
    data, raw = _read(tmp_path / "out", entry)
    assert entry["plan_text_included"] is False and entry["title"] is None
    assert raw["plan"] is None
    assert "리튬이온 배터리 전해액".encode() not in data
    PremortemResult.model_validate(raw)


def test_main_replays_what_it_wrote(tmp_path, capsys):
    with block_external_network() as attempts:
        code = pd.main(["--source", "fixture", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert attempts == []
    assert "재생 확인: 3/3" in out


def test_script_runs_as_command_without_pythonpath(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(PYTHONIOENCODING="utf-8", NEUMANN_LLM_PROVIDER="mock", NEUMANN_DATA_DIR=str(tmp_path / "data"))
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", "fixture"], cwd=tmp_path, env=env, capture_output=True, timeout=120
    )
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 0, out
    # 기본 출력 폴더는 <NEUMANN_DATA_DIR>/precomputed
    manifest = json.loads((tmp_path / "data" / "precomputed" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == 3
    assert "재생 확인: 3/3" in out


def test_network_guard_actually_blocks():
    """차단기 자체 검사: 외부 연결은 막고 기록한다(항상 통과하는 검사가 아님을 확인)."""
    with block_external_network() as attempts:
        with pytest.raises(OSError):
            socket.create_connection(("example.org", 80), timeout=1)
    assert attempts and attempts[0] == ("getaddrinfo", "example.org")
    assert ROOT.joinpath("scripts", "precompute_demo.py").is_file()
