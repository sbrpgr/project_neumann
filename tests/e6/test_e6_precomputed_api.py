"""E6-L2a: src/neumann/api/precomputed.py — 목록·단건·변조 404·표시·오프라인.

사전 계산본은 scripts/precompute_demo.py의 fixture 모드로 tmp 폴더에 만들고, 라우터 폴더 의존성을 바꿔 끼운다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import precomputed as pc
from neumann.models import PremortemResult
from tests.e6.e6_support import ROOT, block_external_network, load_script
from tests.fixtures.loader import plan_text

pd = load_script()
LABEL_RE = re.compile(r"^사전 계산본\(\d{4}-\d{2}-\d{2} \d{2}:\d{2} KST\)$")
BASE = "/premortem/precomputed"


@pytest.fixture
def store(tmp_path) -> tuple[Path, dict]:
    out = tmp_path / "precomputed"
    manifest, failures = pd.build(pd.demo_specs(), out, source="fixture", log=lambda _m: None)
    assert failures == [] and len(manifest["entries"]) == 3
    return out, manifest


def _client(directory: Path) -> TestClient:
    app = FastAPI()
    app.include_router(pc.router)
    app.dependency_overrides[pc.precomputed_dir] = lambda: directory
    return TestClient(app)


@pytest.fixture
def client(store) -> TestClient:
    return _client(store[0])


def _entry(manifest: dict, demo: str) -> dict:
    return next(e for e in manifest["entries"] if e["demo"] == demo)


def _write_manifest(directory: Path, manifest: dict) -> None:
    (directory / "manifest.json").write_bytes(pc.encode_json(manifest))


def test_router_paths():
    assert {r.path for r in pc.router.routes} == {BASE, BASE + "/{plan_id}"}


def test_list_returns_items_with_label_and_integrity(client, store):
    res = client.get(BASE)
    assert res.status_code == 200
    assert res.headers[pc.HEADER_FLAG] == "1"
    body = res.json()
    assert body["available"] is True and body["label"] == "사전 계산본"
    assert body["source"] == "fixture" and body["generated_at"] == store[1]["generated_at"]
    assert [it["demo"] for it in body["items"]] == ["plan", "plan_elife_neuro", "plan_medimaging"]
    for it in body["items"]:
        entry = _entry(store[1], it["demo"])
        assert LABEL_RE.match(it["label"]), it["label"]
        assert it["label"] == pc.precomputed_label(entry["generated_at"])
        assert it["integrity"] == "ok" and it["available"] is True
        assert it["sha256"] == entry["sha256"] and it["cards_total"] == entry["cards_total"]
        assert it["cards_by_generator"] == entry["cards_by_generator"]
        assert it["elapsed_s"] == entry["elapsed_s"] and it["source"] == "fixture"
        assert it["warnings"] == entry["warnings"]
        assert it["url"] == f"{BASE}/{entry['plan_id']}"
    assert body["items"][0]["title"].startswith("연구계획서 (예시)")


def test_get_by_plan_id_is_marked_precomputed_and_keeps_contract(client, store):
    entry = _entry(store[1], "plan")
    res = client.get(f"{BASE}/{entry['plan_id']}")
    assert res.status_code == 200
    assert res.headers[pc.HEADER_FLAG] == "1"
    assert res.headers[pc.HEADER_GENERATED_AT] == entry["generated_at"]
    assert res.headers[pc.HEADER_SHA256] == entry["sha256"]
    body = res.json()
    # 표시: notices 맨 앞 + manifest.precomputed
    label = pc.precomputed_label(entry["generated_at"])
    assert body["notices"][0].startswith(label + " — 실시간 분석이 아니라 미리 계산해 둔 결과다")
    assert "fixture 결과로 대체" in body["notices"][0]  # 대체본이면 그것도 적는다
    meta = body["manifest"]["precomputed"]
    assert meta["label"] == label and meta["generated_at"] == entry["generated_at"]
    assert meta["sha256"] == entry["sha256"] and meta["integrity"] == "ok" and meta["source"] == "fixture"
    # 표시를 붙여도 결과 계약(모델·JSON 스키마)을 그대로 통과한다
    result = PremortemResult.model_validate(body)
    assert result.plan_id == entry["plan_id"] and len(result.risk_cards) == 2
    schema = json.loads((ROOT / "contracts" / "premortem_response.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(body, schema)
    # 저장본의 원래 notices는 뒤에 그대로 있다
    stored = json.loads((store[0] / entry["file"]).read_text(encoding="utf-8"))
    assert body["notices"][1:] == stored["notices"]


def test_get_by_demo_name(client, store):
    entry = _entry(store[1], "plan_elife_neuro")
    res = client.get(f"{BASE}/plan_elife_neuro")
    assert res.status_code == 200
    assert res.json()["plan_id"] == entry["plan_id"]
    assert res.json()["risk_cards"] == []


def test_label_is_kst_and_honest_when_time_unknown():
    assert pc.precomputed_label("2026-09-30T12:03:00Z") == "사전 계산본(2026-09-30 21:03 KST)"
    assert pc.precomputed_label("2026-09-30T12:03:00+00:00") == "사전 계산본(2026-09-30 21:03 KST)"
    assert pc.precomputed_label(None) == "사전 계산본(생성 시각 미상)"
    assert pc.precomputed_label("어제") == "사전 계산본(생성 시각 미상)"


def test_tampered_file_returns_404_and_list_flags_it(client, store):
    directory, manifest = store
    entry = _entry(manifest, "plan")
    url = f"{BASE}/{entry['plan_id']}"
    assert client.get(url).status_code == 200  # 변조 전에는 200(짝 검사)

    path = directory / entry["file"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["risk_cards"][0]["title"] = "Tampered title"  # 여전히 유효한 JSON·계약이지만 바이트가 다르다
    path.write_bytes(pc.encode_json(raw))

    res = client.get(url)
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "tampered"
    assert "변조" in res.json()["detail"]["message"]
    items = {it["demo"]: it for it in client.get(BASE).json()["items"]}
    assert items["plan"]["integrity"] == "mismatch" and items["plan"]["available"] is False
    assert items["plan_medimaging"]["integrity"] == "ok"  # 다른 항목은 그대로 쓸 수 있다
    assert client.get(f"{BASE}/plan_medimaging").status_code == 200


def test_single_byte_change_is_detected(client, store):
    directory, manifest = store
    entry = _entry(manifest, "plan_medimaging")
    path = directory / entry["file"]
    data = path.read_bytes()
    path.write_bytes(data[:-1] + b" ")  # 끝 줄바꿈 한 바이트만 바꾼다
    assert client.get(f"{BASE}/{entry['plan_id']}").status_code == 404


def test_manifest_sha_edit_returns_404(client, store):
    directory, manifest = store
    entry = _entry(manifest, "plan")
    entry["sha256"] = "0" * 64
    _write_manifest(directory, manifest)
    res = client.get(f"{BASE}/{entry['plan_id']}")
    assert res.status_code == 404 and res.json()["detail"]["code"] == "tampered"


def test_swapped_file_with_matching_sha_is_caught_by_plan_id(client, store):
    """파일을 다른 계획서 결과로 바꾸고 sha까지 맞춰도, 결과 안의 plan_id가 달라 404."""
    directory, manifest = store
    target, other = _entry(manifest, "plan"), _entry(manifest, "plan_medimaging")
    data = (directory / other["file"]).read_bytes()
    (directory / target["file"]).write_bytes(data)
    target["sha256"] = pc.sha256_bytes(data)
    _write_manifest(directory, manifest)
    res = client.get(f"{BASE}/{target['plan_id']}")
    assert res.status_code == 404 and res.json()["detail"]["code"] == "tampered"


def test_unknown_and_traversal_ids_return_404(client, store):
    for key in ("deadbeef", "manifest", "manifest.json", "..%2Fmanifest.json", "..%5C..%5Cmanifest"):
        res = client.get(f"{BASE}/{key}")
        assert res.status_code == 404, key


def test_manifest_file_name_outside_folder_is_refused(client, store, tmp_path):
    directory, manifest = store
    outside = tmp_path / "outside.json"
    data = (directory / _entry(manifest, "plan")["file"]).read_bytes()
    outside.write_bytes(data)
    entry = _entry(manifest, "plan")
    for bad in ("../outside.json", "..\\outside.json", "manifest.json", "sub/x.json"):
        entry["file"] = bad
        entry["sha256"] = pc.sha256_bytes(data)
        _write_manifest(directory, manifest)
        res = client.get(f"{BASE}/{entry['plan_id']}")
        assert res.status_code == 404 and res.json()["detail"]["code"] == "bad_name", bad


def test_missing_manifest_and_missing_file(tmp_path, store):
    empty = tmp_path / "empty"
    empty.mkdir()
    c = _client(empty)
    body = c.get(BASE).json()
    assert body["available"] is False and body["items"] == [] and "precompute_demo" in body["reason"]
    res = c.get(f"{BASE}/plan")
    assert res.status_code == 404 and res.json()["detail"]["code"] == "no_manifest"

    directory, manifest = store
    entry = _entry(manifest, "plan_elife_neuro")
    (directory / entry["file"]).unlink()
    c2 = _client(directory)
    assert c2.get(f"{BASE}/{entry['plan_id']}").json()["detail"]["code"] == "missing_file"
    items = {it["demo"]: it for it in c2.get(BASE).json()["items"]}
    assert items["plan_elife_neuro"]["integrity"] == "missing"


def test_broken_manifest_is_reported_not_raised(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "manifest.json").write_text("{not json", encoding="utf-8")
    c = _client(d)
    body = c.get(BASE).json()
    assert body["available"] is False and body["code"] == "bad_manifest"
    assert c.get(f"{BASE}/plan").status_code == 404


def test_lookup_by_text_for_main_fallback(store):
    directory, manifest = store
    hit = pc.lookup_by_text(plan_text("plan_medimaging.md"), directory)
    assert hit is not None and hit.result.plan_id == _entry(manifest, "plan_medimaging")["plan_id"]
    assert LABEL_RE.match(hit.label)
    marked = pc.mark_result(hit)
    assert marked["notices"][0].startswith(hit.label)
    PremortemResult.model_validate(marked)
    assert pc.lookup_by_text(plan_text("negative_recipe.md"), directory) is None
    assert pc.lookup_by_text(plan_text("plan.md"), directory / "nope") is None


def test_marked_result_renders_through_e4_view_with_label(store):
    """main.py가 폴백으로 붙일 때: mark_result → build_ui_view(E4) 화면 데이터에도 표시가 남는다."""
    view_mod = pytest.importorskip("neumann.api.view", reason="E4 view.py가 이 브랜치에 없다")
    directory, manifest = store
    hit = pc.load_precomputed("plan", directory)
    view = view_mod.build_ui_view(pc.mark_result(hit), pipeline_state="connected")
    notices = view["_status"]["notices"]
    assert notices[0].startswith(hit.label), notices
    assert len(view["cards"]) == 2  # 카드도 그대로 그려진다


def test_default_folder_follows_data_dir_setting(monkeypatch, tmp_path):
    from neumann.config import get_settings

    monkeypatch.setenv("NEUMANN_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        assert pc.precomputed_dir() == tmp_path / "precomputed"
    finally:
        get_settings.cache_clear()


def test_requests_make_no_external_network_calls(client, store):
    entry = _entry(store[1], "plan")
    with block_external_network() as attempts:
        assert client.get(BASE).status_code == 200
        assert client.get(f"{BASE}/{entry['plan_id']}").status_code == 200
        assert client.get(f"{BASE}/plan_medimaging").status_code == 200
        assert client.get(f"{BASE}/unknown").status_code == 404
    assert attempts == []


def test_router_module_imports_no_pipeline_llm_or_model_code():
    """오프라인 폴백이 파이프라인·LLM·임베딩을 끌고 오지 않는다(새 프로세스에서 import만 한다)."""
    code = (
        "import sys, neumann.api.precomputed\n"
        "bad = [m for m in ('neumann.pipeline','neumann.llm','openai','torch','sentence_transformers','httpx') "
        "if m in sys.modules]\n"
        "print(','.join(bad))\n"
    )
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]), PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, timeout=120)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout.decode().strip() == ""
