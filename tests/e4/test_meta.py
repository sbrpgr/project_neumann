"""E4-L1d 메타 API: GET /api · GET /taxonomy · GET /config/weights.

router를 임시 FastAPI 앱에 붙여서 잰다(main.py 연결은 PM). 데이터 폴더는 tmp_path로 바꾼다.
매니페스트 있음·없음·일부 없음·깨짐·필드 누락, 가중치 설정 있음·없음·오류, 파이프라인 모듈 대조를 본다.
공유 데이터 폴더에 실제 매니페스트가 있으면 응답 숫자가 매니페스트 원값과 같은지도 잰다(없으면 skip).
"""

from __future__ import annotations

import copy
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import meta
from neumann.models import RISK_NAMES, RiskCode

# 모양은 실제 매니페스트를 따르고, 숫자는 테스트용으로 따로 정한 값(실제 코퍼스 값 아님).
CORPUS: dict[str, Any] = {
    "source": "researcharcade_hf",
    "license": "UNDECLARED",
    "attribution": "test attribution",
    "generated_at": "2026-09-30T00:00:00Z",
    "population": {"venues": ["ICLR.cc/2024/Conference", "ICLR.cc/2025/Conference"]},
    "selection": {
        "works": 11,
        "by_field": {"materials_chemistry_molecules": 5, "protein_biology_drug": 4, "physics_pde_climate": 3},
        "by_field_ko": {"소재·화학·분자": 5, "단백질·생물·신약": 4, "물리·PDE·기후": 3},
        "multi_field_works": 1,
        "by_venue": {"ICLR 2024": 4, "ICLR 2025": 7},
    },
    "linking": {"official_reviews": 30, "meta_reviews": 9, "works_with_official_review": 9},
    "decisions": {
        "accept": 4, "reject": 7, "unknown": 0, "reject_ratio": 0.6364,
        "distribution": {"accept_poster": 4, "reject": 7},
    },
    "outputs": {
        "works.jsonl": {"records": 11, "sha256": "a" * 64},
        "reviews.jsonl": {"records": 39, "sha256": "b" * 64},
        "author_responses.jsonl": {"records": 50, "sha256": "c" * 64},
    },
}
INDEX: dict[str, Any] = {
    "format": "neumann-index-v1",
    "dense_model": "bge-m3",
    "built_at": "2026-09-30T01:00:00+00:00",
    "input": {"dir": "C:\\secret\\local\\path", "files": {"works.jsonl": "a" * 64, "reviews.jsonl": "b" * 64}},
    "counts": {"works": 11, "reviews": 39, "excerpts": 777, "tags": 55, "tag_counts": {"R1": 20, "R2": 35}},
    "offset_check": {"checked": 777, "passed": 777, "failed": 0, "rate": 1.0},
    "backend": {"lexical": "bm25", "degraded": False, "degraded_reason": None, "gpu_name": "SECRET-GPU"},
}


def write(data_dir: Path, rel: str, obj: Any) -> None:
    path = data_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")


def make_client(data_dir: Path, weights: Any = None, pipeline: dict[str, Any] | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(meta.router)
    app.dependency_overrides[meta.get_data_dir] = lambda: data_dir
    app.dependency_overrides[meta.get_weights_setting] = lambda: weights
    pipe = pipeline if pipeline is not None else meta.pipeline_scoring("neumann_test_absent_module_xyz")
    app.dependency_overrides[meta.get_pipeline_scoring] = lambda: pipe
    return TestClient(app)


@pytest.fixture
def full_dir(tmp_path: Path) -> Path:
    write(tmp_path, meta.CORPUS_MANIFEST, CORPUS)
    write(tmp_path, meta.INDEX_MANIFEST, INDEX)
    return tmp_path


# ───────────────────────── GET /api ─────────────────────────


def test_api_with_manifests_passes_values_through(full_dir: Path) -> None:
    r = make_client(full_dir).get("/api")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok" and d["reasons"] == []
    c, i = d["corpus"], d["index"]
    assert c["available"] is True and c["reason"] == ""
    assert c["works"] == 11
    assert c["by_field"] == CORPUS["selection"]["by_field"]
    assert c["by_field_ko"] == CORPUS["selection"]["by_field_ko"]
    assert c["by_venue"] == {"ICLR 2024": 4, "ICLR 2025": 7}
    assert c["reviews"] == 39 and c["official_reviews"] == 30 and c["meta_reviews"] == 9
    assert c["author_responses"] == 50
    assert c["decisions"]["reject_ratio"] == 0.6364
    assert c["decisions"]["accept"] == 4 and c["decisions"]["reject"] == 7
    assert c["generated_at"] == "2026-09-30T00:00:00Z"
    assert c["venues"] == CORPUS["population"]["venues"]
    assert i["available"] is True and i["reason"] == ""
    assert i["excerpts"] == 777 and i["works"] == 11 and i["reviews"] == 39 and i["tags"] == 55
    assert i["built_at"] == "2026-09-30T01:00:00+00:00"
    assert i["tag_counts"] == {"R1": 20, "R2": 35}
    assert i["offset_check"] == {"checked": 777, "passed": 777, "failed": 0, "rate": 1.0}
    assert i["degraded"] is False and i["degraded_reason"] is None
    assert i["matches_corpus"] is True
    assert d["summary_ko"] == "ICLR 2024 · ICLR 2025 · 논문 11편 · 심사평 39건 · 거절 63.6% · 색인 문장 777개"


def test_api_does_not_leak_local_environment(full_dir: Path) -> None:
    body = make_client(full_dir).get("/api").text
    assert "secret" not in body.lower()  # 색인 입력 절대 경로, GPU 이름
    assert str(full_dir) not in body and full_dir.as_posix() not in body
    assert "SECRET-GPU" not in body


def test_api_without_manifests_returns_empty_values_and_reasons(tmp_path: Path) -> None:
    r = make_client(tmp_path).get("/api")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "unavailable"
    assert any("매니페스트 없음: processed/corpus_manifest.json" in x for x in d["reasons"])
    assert any("매니페스트 없음: index/manifest.json" in x for x in d["reasons"])
    c, i = d["corpus"], d["index"]
    assert c["available"] is False and i["available"] is False
    assert c["reason"] and i["reason"]
    for key in ("works", "by_field", "reviews", "official_reviews", "generated_at", "source"):
        assert c[key] is None, key
    assert all(v is None for v in c["decisions"].values())
    for key in ("excerpts", "built_at", "works", "reviews", "tag_counts", "degraded"):
        assert i[key] is None, key
    assert i["matches_corpus"] is None
    assert d["summary_ko"] == ""


def test_api_partial_when_index_missing(tmp_path: Path) -> None:
    write(tmp_path, meta.CORPUS_MANIFEST, CORPUS)
    d = make_client(tmp_path).get("/api").json()
    assert d["status"] == "partial"
    assert d["corpus"]["works"] == 11
    assert d["index"]["excerpts"] is None and d["index"]["reason"] == "매니페스트 없음: index/manifest.json"
    assert "색인 문장" not in d["summary_ko"] and "논문 11편" in d["summary_ko"]


def test_api_broken_manifest_is_reported_not_raised(tmp_path: Path) -> None:
    write(tmp_path, meta.CORPUS_MANIFEST, "{not json")
    write(tmp_path, meta.INDEX_MANIFEST, "[1, 2]")
    r = make_client(tmp_path).get("/api")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "unavailable"
    assert "읽기 실패" in d["corpus"]["reason"] and "JSONDecodeError" in d["corpus"]["reason"]
    assert "형식 오류" in d["index"]["reason"]
    assert d["corpus"]["works"] is None and d["index"]["excerpts"] is None


def test_api_missing_or_mistyped_field_is_null_with_reason(tmp_path: Path) -> None:
    corpus = copy.deepcopy(CORPUS)
    del corpus["decisions"]["reject_ratio"]
    corpus["selection"]["works"] = "11"  # 문자열: 형식 오류로 본다
    index = copy.deepcopy(INDEX)
    del index["counts"]["excerpts"]
    write(tmp_path, meta.CORPUS_MANIFEST, corpus)
    write(tmp_path, meta.INDEX_MANIFEST, index)
    d = make_client(tmp_path).get("/api").json()
    assert d["status"] == "partial"
    assert d["corpus"]["decisions"]["reject_ratio"] is None
    assert d["corpus"]["works"] is None
    assert "decisions/reject_ratio" in d["corpus"]["reason"]
    assert "selection/works (형식 오류)" in d["corpus"]["reason"]
    assert d["index"]["excerpts"] is None and "counts/excerpts" in d["index"]["reason"]
    # 없는 값은 계산해서 채우지 않는다: accept/reject가 있어도 reject_ratio는 null
    assert d["corpus"]["decisions"]["accept"] == 4
    assert "거절" not in d["summary_ko"]


def test_api_flags_index_built_from_other_corpus(tmp_path: Path) -> None:
    index = copy.deepcopy(INDEX)
    index["input"]["files"]["reviews.jsonl"] = "f" * 64
    write(tmp_path, meta.CORPUS_MANIFEST, CORPUS)
    write(tmp_path, meta.INDEX_MANIFEST, index)
    d = make_client(tmp_path).get("/api").json()
    assert d["index"]["matches_corpus"] is False
    assert d["status"] == "partial"
    assert any("reviews.jsonl" in x and "재빌드" in x for x in d["reasons"])


def _real_data_dir() -> Path:
    env = os.environ.get("NEUMANN_DATA_DIR")
    return Path(env) if env else meta.get_data_dir()


def test_api_real_manifests_match_raw_values() -> None:
    """공유 데이터 폴더의 실제 매니페스트: 응답 숫자 == 매니페스트 원값(지어낸 숫자 없음)."""
    data_dir = _real_data_dir()
    cpath, ipath = data_dir / meta.CORPUS_MANIFEST, data_dir / meta.INDEX_MANIFEST
    if not (cpath.is_file() and ipath.is_file()):
        pytest.skip("공유 데이터 폴더에 매니페스트가 없다")
    craw = json.loads(cpath.read_text(encoding="utf-8"))
    iraw = json.loads(ipath.read_text(encoding="utf-8"))
    d = make_client(data_dir).get("/api").json()
    c, i = d["corpus"], d["index"]
    assert c["works"] == craw["selection"]["works"]
    assert c["by_field"] == craw["selection"]["by_field"]
    assert c["reviews"] == craw["outputs"]["reviews.jsonl"]["records"]
    assert c["decisions"]["reject_ratio"] == craw["decisions"]["reject_ratio"]
    assert i["excerpts"] == iraw["counts"]["excerpts"]
    assert i["built_at"] == iraw["built_at"]
    assert c["generated_at"] == craw["generated_at"]
    assert d["status"] in ("ok", "partial")


# ───────────────────────── GET /taxonomy ─────────────────────────

# 03_risk_taxonomy.md §3 Tier-1 카드의 "심각도 기본값"
DOC_SEVERITY = {"R0": "S1", "R1": "S4", "R2": "S4", "R3": "S5", "R4": "S3",
                "R5": "S3", "R6": "S4", "R7": "S4", "R8": "S4", "R9": "S5"}
DOC_SUBCODES = {"R0": 0, "R1": 5, "R2": 7, "R3": 8, "R4": 7, "R5": 5, "R6": 5, "R7": 6, "R8": 7, "R9": 9}


def test_taxonomy_r0_to_r9(tmp_path: Path) -> None:
    r = make_client(tmp_path).get("/taxonomy")
    assert r.status_code == 200
    d = r.json()
    assert d["version"] == "v1.0"
    codes = [c["code"] for c in d["classes"]]
    assert codes == [f"R{n}" for n in range(10)]
    assert d["tier1_count"] == 10 and d["tier2_count"] == 59
    for c in d["classes"]:
        slug, ko, en = RISK_NAMES[RiskCode(c["code"])]
        assert (c["slug"], c["name_ko"], c["name_en"]) == (slug, ko, en)
        assert c["description"].strip()
        assert c["severity"] == DOC_SEVERITY[c["code"]], c["code"]
        assert c["severity_rank"] == int(c["severity"][1:])
        assert len(c["subcodes"]) == DOC_SUBCODES[c["code"]]
        assert all(s.startswith(c["code"] + ".") for s in c["subcodes"])
        assert set(c["detect_from"]) <= set(d["detect_paths"])
    by = {c["code"]: c for c in d["classes"]}
    assert by["R0"]["creates_card"] is False and by["R0"]["severity_name_ko"] == "경미"
    assert by["R9"]["macro_f1_target"] is False and by["R9"]["detect_from"] == ["post_pub_record"]
    assert by["R3"]["severity_name_ko"] == "치명적"
    assert [s["level"] for s in d["severity_scale"]] == ["S5", "S4", "S3", "S2", "S1"]


# ───────────────────────── GET /config/weights ─────────────────────────


def test_weights_default_when_not_configured(tmp_path: Path) -> None:
    r = make_client(tmp_path, weights=None).get("/config/weights")
    assert r.status_code == 200
    d = r.json()
    assert d["weights"] == {"similarity": 0.3, "frequency": 0.3, "severity": 0.3, "confidence": 0.1}
    assert d["source"] == "default" and d["is_default"] is True and d["label"] == "기본값"
    assert "기본값" in d["reason"] and d["config_error"] is None
    assert d["display"] == "0.3 / 0.3 / 0.3 / 0.1"
    assert d["order"] == ["similarity", "frequency", "severity", "confidence"]
    assert d["labels_ko"]["similarity"] == "유사도"
    assert d["pipeline"]["state"] == "missing" and d["pipeline"]["matches"] is None


def test_weights_real_settings_dependency_defaults() -> None:
    """config.py에 risk_weights 키가 없으면(현재) 실제 의존성도 None → 기본값."""
    from neumann.config import get_settings

    if getattr(get_settings(), "risk_weights", None) is not None:
        pytest.skip("설정에 risk_weights가 들어왔다")
    assert meta.get_weights_setting() is None
    assert meta.build_weights(meta.get_weights_setting())["is_default"] is True


@pytest.mark.parametrize(
    "raw",
    [
        {"similarity": 0.4, "frequency": 0.2, "severity": 0.3, "confidence": 0.1},
        "0.4/0.2/0.3/0.1",
        "similarity=0.4, frequency=0.2, severity=0.3, confidence=0.1",
    ],
)
def test_weights_from_config(tmp_path: Path, raw: Any) -> None:
    d = make_client(tmp_path, weights=raw).get("/config/weights").json()
    assert d["weights"] == {"similarity": 0.4, "frequency": 0.2, "severity": 0.3, "confidence": 0.1}
    assert d["source"] == "config" and d["is_default"] is False and d["label"] == "설정값"
    assert d["reason"] == "" and d["display"] == "0.4 / 0.2 / 0.3 / 0.1"


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("0.3/0.3/0.3", "4개"),
        ("0.3/0.3/0.3/1.5", "0~1"),
        ({"similarity": 0.3, "frequency": 0.3, "severity": 0.3}, "키 불일치"),
        ("similarity=abc,frequency=0.3,severity=0.3,confidence=0.1", "숫자"),
        (42, "지원하지 않는 형식"),
    ],
)
def test_weights_invalid_config_falls_back_with_reason(tmp_path: Path, raw: Any, fragment: str) -> None:
    d = make_client(tmp_path, weights=raw).get("/config/weights").json()
    assert d["weights"] == meta.DEFAULT_WEIGHTS
    assert d["is_default"] is True and d["label"] == "기본값"
    assert d["config_error"] and fragment in d["config_error"]
    assert "형식 오류" in d["reason"]


def test_pipeline_scoring_reports_module_weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("neumann_test_fake_cards")
    fake.SCORE_FORMULA = "product_v1: similarity * frequency * severity * confidence"
    fake.SCORE_WEIGHTS = {"similarity": 1.0, "frequency": 1.0, "severity": 1.0, "confidence": 1.0}
    monkeypatch.setitem(sys.modules, "neumann_test_fake_cards", fake)
    info = meta.pipeline_scoring("neumann_test_fake_cards")
    assert info["state"] == "ok" and info["formula"].startswith("product_v1")
    d = make_client(tmp_path, pipeline=info).get("/config/weights").json()
    assert d["pipeline"]["matches"] is False and d["pipeline"]["note"]
    assert d["pipeline"]["weights"] == fake.SCORE_WEIGHTS

    same = dict(info, weights=dict(meta.DEFAULT_WEIGHTS))
    d2 = make_client(tmp_path, pipeline=same).get("/config/weights").json()
    assert d2["pipeline"]["matches"] is True


def test_pipeline_scoring_import_error_is_state(monkeypatch: pytest.MonkeyPatch) -> None:
    assert meta.pipeline_scoring("neumann_test_absent_module_xyz")["state"] == "missing"
    monkeypatch.setitem(sys.modules, "neumann_test_blocked_mod", None)  # import 차단
    assert meta.pipeline_scoring("neumann_test_blocked_mod")["state"] == "missing"


# ───────────────────────── router ─────────────────────────


def test_router_routes_and_openapi(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api", "/taxonomy", "/config/weights"):
        assert "get" in paths[p], p
    assert {r.path for r in meta.router.routes} == {"/api", "/taxonomy", "/config/weights"}
