"""E6-L3d: precompute_demo.py --from-results — 라이브 E2E 결과를 사전 계산본으로 가져오기.

실제 라이브 결과 파일은 쓰지 않는다. tests/e6/e6_support.fake_live_result로 가짜 결과를 tmp에 만든다.
새 분석·네트워크·LLM 호출이 없어야 한다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from neumann.api import precomputed as pc
from neumann.models import PremortemResult
from tests.e6.e6_support import (
    LIVE_WHEN,
    ROOT,
    block_external_network,
    fake_live_result,
    load_script,
    write_live_results,
)

pd = load_script()
PLANS = list(pd.DEMO_PLANS)
DEMOS = ["plan", "protein_ligand_affinity", "neural_operator_weather", "negative_recipe"]


def _quiet(_m: str) -> None:
    pass


def _entries(manifest: dict) -> dict[str, dict]:
    return {e["demo"]: e for e in manifest["entries"]}


def _results(tmp_path: Path, **kw) -> Path:
    return write_live_results(tmp_path / "E5-L1e2e_live", PLANS, **kw)


def test_import_keeps_model_time_and_marks_live_source(tmp_path, capsys):
    res = _results(tmp_path)
    out = tmp_path / "pre"
    with block_external_network() as attempts:
        code = pd.main(["--from-results", str(res), "--out", str(out), "--run-commit", "ABC1234def"])
    log = capsys.readouterr().out
    assert code == 0, log
    assert attempts == []
    assert "재생 확인: 4/4" in log and "라이브 서버(8020)" in log and "gpt-6.1-sol" in log

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "live_e2e" and manifest["kind"] == pc.MANIFEST_KIND
    live = manifest["live_run"]
    assert live["server_port"] == 8020 and live["server_label"] == "라이브 서버(8020)" and live["task"] == "E5-L1e2e"
    assert live["run_commit"] == "abc1234def" and live["run_commit_source"] == "인자(--run-commit)"
    assert live["import_commit"] is None or len(live["import_commit"]) == 40
    assert live["models"] == ["gpt-6.1-sol"] and live["providers"] == ["openai"] and live["partial"] is False
    assert live["results"] == "E5-L1e2e_live"  # 폴더 이름만(로컬 절대 경로를 남기지 않는다)
    assert str(tmp_path) not in json.dumps(manifest, ensure_ascii=False)
    assert manifest["pipeline"]["available"] is False and manifest["pipeline"]["impl"] == "import:live_e2e"

    entries = _entries(manifest)
    assert list(entries) == DEMOS
    for demo, rel in zip(DEMOS, PLANS):
        e = entries[demo]
        original = fake_live_result(rel)
        stored = json.loads((out / e["file"]).read_text(encoding="utf-8"))
        # 결과는 고치지 않는다: 모델·provider·생성 시각·카드 generator 그대로
        assert stored == PremortemResult.model_validate(original).model_dump(mode="json")
        assert stored["manifest"]["llm_provider"] == "openai" and stored["manifest"]["llm_model"] == "gpt-6.1-sol"
        assert e["generated_at"] == e["result_generated_at"] == LIVE_WHEN  # 항목 시각 = 라이브 생성 시각
        assert e["source"] == "live_e2e" and e["impl"] == "import:live_e2e"
        assert e["llm_actual"] == {"provider": "openai", "model": "gpt-6.1-sol"}
        assert e["generation"] == "openai:gpt-6.1-sol"
        assert e["live"]["server_port"] == 8020 and e["live"]["results_file"] == f"{Path(rel).stem}.result.json"
        assert len(e["live"]["results_file_sha256"]) == 64 and e["live"]["candidates"] == 1
        assert e["plan_text_included"] is True and e["role"] == ("out_of_scope" if demo == "negative_recipe" else "demo")
    assert entries["plan"]["cards_by_generator"] == {"astra": 2, "rule": 0, "mock": 0}
    assert entries["plan"]["models"] == ["gpt-6.1-sol", "openai:gpt-6.1-sol"]
    assert entries["negative_recipe"]["cards_total"] == 0  # 범위 밖 카드 0장은 실패가 아니다

    # 라우터(오프라인 폴백)는 라이브 생성 시각으로 표시한다
    items = pc.list_items(out)
    assert items["available"] is True and {it["integrity"] for it in items["items"]} == {"ok"}
    assert items["items"][0]["label"] == "사전 계산본(2026-09-30 21:20 KST)"
    assert items["llm"] == {"source": "results", "providers": ["openai"], "models": ["gpt-6.1-sol"]}


def test_mock_and_rule_results_stay_labelled(tmp_path):
    res = _results(tmp_path, provider="mock", model="mock-deterministic-v1", rule_cards=1)
    manifest, failures = pd.import_live(pd.demo_specs(), res, tmp_path / "pre", log=_quiet)
    assert failures == []
    e = _entries(manifest)["plan"]
    assert e["llm_actual"] == {"provider": "mock", "model": "mock-deterministic-v1"}
    assert e["cards_by_generator"] == {"astra": 1, "rule": 1, "mock": 0}
    assert e["generation"] == "mock:mock-deterministic-v1 · 규칙 대체 카드 1장(비상 경로) · mock(가짜 LLM)"
    stored = json.loads((tmp_path / "pre" / e["file"]).read_text(encoding="utf-8"))
    assert [c["generator"] for c in stored["risk_cards"]] == ["rule", "astra"]  # 규칙 카드를 LLM이라고 바꾸지 않는다
    assert manifest["live_run"]["providers"] == ["mock"]


@pytest.mark.parametrize(
    ("case", "mutate", "reason"),
    [
        ("astra 모델", lambda d: d["manifest"].update(llm_model="gpt-6-astra"), "astra 모델 표기"),
        ("astra 카드", lambda d: d["risk_cards"][0].update(model="gpt-6-astra"), "astra 모델 표기"),
        ("샘플 응답", lambda d: d.update(sample=True), "샘플 응답"),
        ("이메일", lambda d: d["evidence"][0].update(text="contact jane.doe@example.org now"), "가리지 않은 개인정보"),
        ("ORCID", lambda d: d["evidence"][1].update(text="orcid 0000-0002-1825-0097 x"), "가리지 않은 개인정보"),
        ("OpenReview 프로필", lambda d: d["notices"].append("by ~Jane_Doe1"), "가리지 않은 개인정보"),
        ("신원 키", lambda d: d["manifest"].update(reviewer_id="r1"), "가리지 않은 개인정보"),
        ("계약 위반", lambda d: d["risk_cards"][0].update(evidence=["ex_missing"]), "결과 계약 위반"),
        ("fixture 대체", lambda d: d["stages"].append({"name": "precompute_source", "status": "degraded",
                                                      "impl": "fallback:fixture"}), "fixture·파이프라인 미연결·오류"),
        ("fixture 단계", lambda d: d["stages"].append({"name": "retrieve", "impl": "fixture"}), "fixture·파이프라인"),
        ("fixture:mock 단계", lambda d: d["stages"].append({"name": "cards", "impl": "fixture:mock"}), "fixture·파이프라인"),
        ("파이프라인 미연결", lambda d: d["stages"].append({"name": "run_premortem", "status": "error",
                                                         "impl": "fallback:pipeline_unavailable"}), "fixture·파이프라인"),
        ("파이프라인 오류", lambda d: d["stages"].append({"name": "run_premortem", "status": "error",
                                                       "impl": "fallback:pipeline_error"}), "fixture·파이프라인"),
        ("status error", lambda d: d.update(status="error"), "오류 결과(status error)"),
        ("provider 없음", lambda d: d["manifest"].pop("llm_provider"), "manifest.llm_provider 없음"),
        ("astra model_name", lambda d: d["manifest"].update(model_name="gpt-6-astra"), "astra 모델 표기"),
        ("astra requested_model", lambda d: d["manifest"].update(requested_model="gpt-6-astra"), "astra 모델 표기"),
        ("프로필 id 점·아포스트로피", lambda d: d["notices"].append("~Geoffrey_E._Hinton1"), "가리지 않은 개인정보"),
        ("프로필 id 소문자", lambda d: d["notices"].append("see ~conor_o'brien2"), "가리지 않은 개인정보"),
        ("신원 키 조각", lambda d: d["manifest"].update(meta_reviewer_ids=["x"]), "가리지 않은 개인정보"),
        ("저자 키", lambda d: d["manifest"].update(paper_authors=["x"]), "가리지 않은 개인정보"),
    ],
)
def test_bad_candidates_are_rejected_and_nothing_is_written(tmp_path, capsys, case, mutate, reason):
    res = _results(tmp_path)
    path = res / "plan.result.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "pre"
    assert pd.main(["--from-results", str(res), "--out", str(out)]) == 1, case
    log = capsys.readouterr().out
    assert "실패 plan:" in log and reason in log, log
    assert "가져오기 중단" in log and not out.exists()  # 전부 아니면 쓰지 않는다
    for secret in ("jane.doe@example.org", "0000-0002-1825-0097", "~Jane_Doe1", "~Geoffrey_E._Hinton1", "brien2"):
        assert secret not in log  # 찾은 값은 출력하지 않는다(위치만)


def test_masked_pii_is_accepted_but_masked_quote_breaks_contract(tmp_path):
    res = _results(tmp_path)
    path = res / "plan.result.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["notices"].append("문의 [EMAIL] · [ORCID]")  # 가린 표기는 개인정보가 아니다
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert pd.privacy_problems(data) == []
    _, failures = pd.import_live(pd.demo_specs(), res, tmp_path / "pre", log=_quiet)
    assert failures == []

    # 인용(evidence.text)을 뒤에서 가리면 원문 대조(text_sha256)가 깨진다 — 그런 결과는 받지 않는다
    ev = data["evidence"][0]
    ev["text"] = ("[EMAIL] " + ev["text"])[: len(ev["text"])]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _, failures = pd.import_live(pd.demo_specs(), res, tmp_path / "pre2", log=_quiet)
    assert failures and failures[0]["demo"] == "plan" and "결과 계약 위반(ValidationError: evidence/0)" in failures[0]["error"]


def test_missing_plan_is_all_or_nothing_unless_partial(tmp_path, capsys):
    res = write_live_results(tmp_path / "r", PLANS[:3])  # 범위 밖 결과 없음(E5가 /premortem을 안 부른 경우)
    out = tmp_path / "pre"
    assert pd.main(["--from-results", str(res), "--out", str(out)]) == 1
    log = capsys.readouterr().out
    assert "실패 negative_recipe: 라이브 결과 없음(plan_id 일치 후보 0건)" in log and not out.exists()

    assert pd.main(["--from-results", str(res), "--out", str(out), "--allow-partial"]) == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert [e["demo"] for e in manifest["entries"]] == DEMOS[:3]
    assert manifest["live_run"]["partial"] is True
    assert manifest["failures"] == [{"demo": "negative_recipe", "error": "라이브 결과 없음(plan_id 일치 후보 0건)"}]


def test_wrapped_summary_latest_candidate_and_commit_from_results(tmp_path):
    """요약 JSON 안에 감싼 결과도 찾고, 같은 계획서가 여러 번이면 가장 늦은 것. 커밋은 감싼 JSON에서 읽는다."""
    res = tmp_path / "r"
    res.mkdir()
    early = fake_live_result(PLANS[0], when="2026-09-30T12:05:00Z", session_id="sess_a")
    late = fake_live_result(PLANS[0], when="2026-09-30T12:31:00Z", session_id="sess_b")
    wrapper = {"commit": "DEADBEEF12", "plans": {n: {"result": fake_live_result(p)} for n, p in zip(DEMOS[1:], PLANS[1:])}}
    wrapper["runs"] = [{"result": early}, {"result": late}]
    (res / "summary.json").write_text(json.dumps(wrapper, ensure_ascii=False), encoding="utf-8")
    (res / "notes.json").write_text("{not json", encoding="utf-8")  # 읽을 수 없는 파일은 건너뛰고 알린다
    logs: list[str] = []
    manifest, failures = pd.import_live(pd.demo_specs(), res, tmp_path / "pre", log=logs.append)
    assert failures == []
    e = _entries(manifest)["plan"]
    assert e["generated_at"] == "2026-09-30T12:31:00Z" and e["live"]["candidates"] == 2
    assert e["live"]["results_pointer"] == "/runs/1/result"
    assert "같은 계획서 결과 2건 중 라이브 우선·generated_at이 가장 늦은 것" in e["warnings"]
    assert manifest["live_run"]["run_commit"] == "deadbeef12" and manifest["live_run"]["run_commit_source"] == "결과 파일"
    assert any("notes.json: JSON 아님" in m for m in logs)


def test_old_demo_results_in_folder_are_ignored(tmp_path):
    """옛 fMRI·의료영상 결과가 폴더에 섞여 있어도 데모 계획서(plan_id)와 맞지 않아 쓰지 않는다."""
    res = _results(tmp_path)
    old = fake_live_result("tests/fixtures/plans/plan_medimaging.md")
    (res / "plan_medimaging.result.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    manifest, failures = pd.import_live(pd.demo_specs(), res, tmp_path / "pre", log=_quiet)
    assert failures == [] and [e["demo"] for e in manifest["entries"]] == DEMOS
    assert not (tmp_path / "pre" / f"{old['plan_id']}.json").exists()


def test_bad_run_commit_argument(tmp_path, capsys):
    assert pd.main(["--from-results", str(tmp_path), "--out", str(tmp_path / "o"), "--run-commit", "not-a-sha"]) == 2
    assert "16진수" in capsys.readouterr().out


def test_import_does_not_load_pipeline_llm_or_network():
    """가져오기는 새 분석이 아니다: 파이프라인·LLM·openai 모듈을 import하지 않는다(새 프로세스)."""
    code = (
        "import sys, importlib.util, json, tempfile, pathlib\n"
        "spec = importlib.util.spec_from_file_location('pdx', 'scripts/precompute_demo.py')\n"
        "m = importlib.util.module_from_spec(spec); sys.modules['pdx'] = m; spec.loader.exec_module(m)\n"
        "from tests.e6.e6_support import write_live_results\n"
        "d = pathlib.Path(tempfile.mkdtemp())\n"
        "r = write_live_results(d / 'r', list(m.DEMO_PLANS))\n"
        "man, fail = m.import_live(m.demo_specs(), r, d / 'o', log=lambda s: None)\n"
        "bad = [x for x in ('neumann.pipeline', 'neumann.llm', 'openai', 'torch', 'sentence_transformers') if x in sys.modules]\n"
        "print(json.dumps({'n': len(man['entries']), 'fail': fail, 'bad': bad}))\n"
    )
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]), PYTHONIOENCODING="utf-8",
               NEUMANN_LLM_PROVIDER="mock")
    env.pop("NEUMANN_LIVE_LLM_OK", None)
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, timeout=120)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert json.loads(proc.stdout.decode().strip().splitlines()[-1]) == {"n": 4, "fail": [], "bad": []}


def test_rehearsal_port_zero_is_not_called_live_server(tmp_path, capsys):
    """mock 결과로 절차만 확인할 때(--server-port 0): 라이브 서버 결과라고 적지 않는다."""
    res = _results(tmp_path, provider="mock", model="mock-deterministic-v1")
    out = tmp_path / "pre"
    assert pd.main(["--from-results", str(res), "--out", str(out), "--server-port", "0"]) == 0
    assert "로컬 리허설(라이브 서버 아님)" in capsys.readouterr().out
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["live_run"]["server_label"] == "로컬 리허설(라이브 서버 아님)"
    assert {e["live"]["server_label"] for e in manifest["entries"]} == {"로컬 리허설(라이브 서버 아님)"}
    assert "라이브 서버(" not in json.dumps(manifest, ensure_ascii=False)


def test_partial_fallbacks_inside_live_run_are_accepted(tmp_path):
    """라이브 안의 부분 대체(규칙 비상 경로)는 받는다: fallback: 전체를 막지 않는다."""
    res = _results(tmp_path, rule_cards=1)
    path = res / "plan.result.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["stages"] += [{"name": "synthesize_cards", "status": "degraded", "impl": "fallback:cards.rule_cards"},
                       {"name": "fitness", "status": "degraded", "impl": "fallback:rules.fitness"}]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    manifest, failures = pd.import_live(pd.demo_specs(), res, tmp_path / "pre", log=_quiet)
    assert failures == []
    e = _entries(manifest)["plan"]
    assert e["status"] == "degraded" and e["substitute"] is False and e["live"]["rehearsal"] is False
    assert "규칙 대체 카드 1장(비상 경로)" in e["generation"] and "status degraded" in e["generation"]


def test_zero_results_never_overwrite_existing_manifest(tmp_path, capsys):
    """--allow-partial이어도 가져올 결과가 0건이면 쓰지 않는다(경로 오타로 기존 매니페스트가 사라지지 않게)."""
    out = tmp_path / "pre"
    assert pd.main(["--from-results", str(_results(tmp_path)), "--out", str(out)]) == 0
    before = (out / "manifest.json").read_bytes()
    capsys.readouterr()
    for bad in (tmp_path / "오타_폴더", tmp_path / "empty"):
        (tmp_path / "empty").mkdir(exist_ok=True)
        assert pd.main(["--from-results", str(bad), "--out", str(out), "--allow-partial"]) == 1
        log = capsys.readouterr().out
        assert "가져올 결과 0건" in log and "기존 사전 계산본 그대로" in log
        assert (out / "manifest.json").read_bytes() == before
    manifest, failures = pd.import_live(pd.demo_specs(), tmp_path / "empty", out, allow_partial=True, log=_quiet)
    assert manifest == {} and failures[-1]["demo"] == "*"


def test_mock_results_are_substitute_and_rehearsal_whatever_the_port(tmp_path):
    res = _results(tmp_path, provider="mock", model="mock-deterministic-v1")
    manifest, failures = pd.import_live(pd.demo_specs(), res, tmp_path / "pre", server_port=8020, log=_quiet)
    assert failures == []
    for e in manifest["entries"]:
        assert e["substitute"] is True and e["substitute_reason"] == "mock provider 결과(가짜 LLM)"
        assert e["live"]["rehearsal"] is True and e["live"]["server_label"] == "로컬 리허설(라이브 서버 아님)"
    assert manifest["live_run"]["server_label"] == "로컬 리허설(라이브 서버 아님)"
    # provider는 openai여도 카드가 mock이면 대체
    res2 = _results(tmp_path / "b")
    path = res2 / "plan.result.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["risk_cards"][0]["generator"] = "mock"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    m2, _ = pd.import_live(pd.demo_specs(), res2, tmp_path / "pre2", log=_quiet)
    e = _entries(m2)["plan"]
    assert e["substitute"] is True and e["substitute_reason"] == "mock 카드 1장" and e["live"]["rehearsal"] is True
    assert _entries(m2)["protein_ligand_affinity"]["live"]["rehearsal"] is False
    assert m2["live_run"]["server_label"] == "라이브 서버(8020)" and m2["live_run"]["rehearsal_entries"] == ["plan"]


def test_live_result_preferred_over_later_mock(tmp_path):
    """같은 계획서에 라이브(openai)와 더 늦은 mock 결과가 있으면 라이브를 고른다."""
    res = _results(tmp_path)
    late_mock = fake_live_result(PLANS[0], provider="mock", model="mock-deterministic-v1", when="2026-09-30T14:00:00Z",
                                 session_id="sess_mock")
    (res / "plan_mock.result.json").write_text(json.dumps(late_mock, ensure_ascii=False), encoding="utf-8")
    manifest, failures = pd.import_live(pd.demo_specs(), res, tmp_path / "pre", log=_quiet)
    assert failures == []
    e = _entries(manifest)["plan"]
    assert e["llm_actual"]["provider"] == "openai" and e["generated_at"] == LIVE_WHEN and e["live"]["candidates"] == 2
    assert e["substitute"] is False
