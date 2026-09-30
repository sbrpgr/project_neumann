"""E4-L0 API 검사: /health, /premortem, /premortem/view, 화면·폰트 서빙.

파이프라인 연결 상태는 sys.modules로 조작한다. E3가 neumann.pipeline을 병합한 뒤에도 이 검사는
"미연결" 경로와 "연결" 경로를 각각 결정적으로 잰다(실제 파이프라인·API를 부르지 않는다).
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft7Validator

from neumann.api import main
from neumann.api.view import SAMPLE_LABEL

ROOT = Path(__file__).resolve().parents[2]
UI_SCHEMA = json.loads((ROOT / "contracts" / "ui_view.schema.json").read_text(encoding="utf-8"))
RESULT_SCHEMA = json.loads((ROOT / "contracts" / "premortem_response.schema.json").read_text(encoding="utf-8"))
WEBUI = ROOT / "src" / "neumann" / "webui"

PLAN = """# 연구계획서 — 전해액 이온전도도 예측 대리모델
## 2. 방법
분자 그래프 인코더와 조성 임베딩을 결합한 GNN 을 학습한다.
We randomly split the dataset into 80/10/10 train/validation/test sets.
We do not report error bars, and no ablation study is planned.
"""


def ui_errors(view: dict) -> list[str]:
    return [f"{list(e.absolute_path)}: {e.message}" for e in Draft7Validator(UI_SCHEMA).iter_errors(view)]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture()
def no_pipeline(monkeypatch):
    """neumann.pipeline 이 없는 상태(import 시 ModuleNotFoundError)."""
    monkeypatch.setitem(sys.modules, "neumann.pipeline", None)


def fake_pipeline(monkeypatch, fn) -> None:
    mod = types.ModuleType("neumann.pipeline")
    mod.run_premortem = fn
    monkeypatch.setitem(sys.modules, "neumann.pipeline", mod)


def astra_result(plan_text: str) -> dict:
    """샘플을 '연결된 파이프라인이 astra로 만든 결과'처럼 바꾼 가짜 반환값."""
    data = json.loads(main.SAMPLE_PATH.read_text(encoding="utf-8"))
    data["status"] = "ok"
    data["plan_id"] = "sha256:test"
    data["session_id"] = "sess_test"
    for c in data["risk_cards"]:
        c["generator"] = "astra"
    data["stages"] = [
        {"name": "plan_normalize", "phase": "INPUT", "status": "ok", "elapsed_s": 0.01},
        {"name": "build_risk_cards", "phase": "RISK", "status": "ok", "impl": "neumann.analyze.cards:build",
         "elapsed_s": 2.5},
    ]
    data["manifest"] = {"model_id": "gpt-6-astra", "model_provider": "openai"}
    data["echo_chars"] = len(plan_text)
    return data


# ───────────────────────── /health ─────────────────────────


def test_health_ok_and_reports_stages(client, no_pipeline):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["pipeline"]["state"] == "unavailable"
    assert body["pipeline"]["mode"] == "sample"
    assert body["pipeline"]["label"] == SAMPLE_LABEL
    for stage in ("pipeline", "INPUT", "EVIDENCE", "RISK", "REVIEW", "ACTION", "TRACE"):
        assert stage in body["stages"], stage
        assert isinstance(body["stages"][stage]["available"], bool)
    assert body["stages"]["pipeline"]["available"] is False
    assert body["stages"]["pipeline"]["modules"]["neumann.pipeline"].startswith("missing")


def test_health_reports_connected_pipeline(client, monkeypatch):
    fake_pipeline(monkeypatch, astra_result)
    body = client.get("/health").json()
    assert body["pipeline"]["state"] == "connected"
    assert body["stages"]["pipeline"]["available"] is True


def test_health_reports_broken_pipeline_as_error(client, monkeypatch):
    mod = types.ModuleType("neumann.pipeline")  # run_premortem 없음
    monkeypatch.setitem(sys.modules, "neumann.pipeline", mod)
    body = client.get("/health").json()
    assert body["pipeline"]["state"] == "unavailable"
    assert "run_premortem" in body["pipeline"]["reason"]


# ───────────────────────── 파이프라인 미연결: 샘플 + 상태 표시 ─────────────────────────


def test_view_without_pipeline_is_contract_valid_and_labelled(client, no_pipeline):
    r = client.post("/premortem/view", json={"plan_text": PLAN})
    assert r.status_code == 200
    view = r.json()
    assert ui_errors(view) == []
    st = view["_status"]
    assert st["source"] == "sample"
    assert st["pipeline"] == "unavailable"
    assert st["label"] == SAMPLE_LABEL
    assert st["degraded"] is True
    assert any(SAMPLE_LABEL in n for n in st["notices"])
    assert st["input"]["chars"] == len(PLAN)
    assert st["contract_ok"] is True
    # 샘플이라도 카드마다 근거 인용과 원문 링크가 있다
    assert view["cards"], "샘플 카드가 비었다"
    for card in view["cards"]:
        assert card["gen"] == "mock"  # 공용 fixture 카드는 mock 생성
        assert card["ev"]
        for n in card["ev"]:
            ev = view["ev"][str(n)]
            assert ev["q"].strip()
            assert ev["u"].startswith("https://")


def test_premortem_without_pipeline_returns_labelled_sample(client, no_pipeline):
    r = client.post("/premortem", json={"plan_text": PLAN})
    assert r.status_code == 200
    body = r.json()
    assert list(Draft7Validator(RESULT_SCHEMA).iter_errors(body)) == []
    assert body["sample"] is True
    assert body["status"] == "degraded"
    assert any(SAMPLE_LABEL in n for n in body["notices"])
    assert body["stages"][0]["status"] == "unavailable"
    assert body["stages"][0]["impl"] == "fallback:sample"


# ───────────────────────── 파이프라인 연결 ─────────────────────────


def test_view_with_connected_pipeline(client, monkeypatch):
    seen = {}

    def run_premortem(plan_text):
        seen["text"] = plan_text
        return astra_result(plan_text)

    fake_pipeline(monkeypatch, run_premortem)
    r = client.post("/premortem/view", json={"plan_text": PLAN, "filename": "plan.md"})
    assert r.status_code == 200
    view = r.json()
    assert seen["text"] == PLAN, "파이프라인에 원문이 그대로 전달되지 않았다"
    assert ui_errors(view) == []
    st = view["_status"]
    assert st["source"] == "pipeline"
    assert st["pipeline"] == "connected"
    assert st["label"] == ""
    assert st["generators"] == {"astra": len(view["cards"])}
    assert view["plan"]["file"] == "plan.md"
    assert view["plan_id"] == "sha256:test"
    assert view["kpi"]["model_id"] == "gpt-6-astra"
    assert [p["k"] for p in view["pipeline"]] == ["INPUT", "RISK"]


def test_premortem_with_connected_pipeline_passes_result_through(client, monkeypatch):
    fake_pipeline(monkeypatch, astra_result)
    r = client.post("/premortem", json={"plan_text": PLAN})
    assert r.status_code == 200
    body = r.json()
    assert body["echo_chars"] == len(PLAN)
    assert "sample" not in body


def test_async_pipeline_and_filename_kwarg(client, monkeypatch):
    async def run_premortem(plan_text, filename=None):
        data = astra_result(plan_text)
        data["plan_stats"]["file"] = f"from-pipeline:{filename}"
        return data

    fake_pipeline(monkeypatch, run_premortem)
    view = client.post("/premortem/view", json={"plan_text": PLAN, "filename": "x.md"}).json()
    assert view["_status"]["source"] == "pipeline"
    assert view["plan"]["file"] == "x.md"  # 요청의 파일 이름이 우선


def test_pipeline_exception_is_not_hidden(client, monkeypatch):
    def boom(plan_text):
        raise RuntimeError("secret-looking message that must not leak")

    fake_pipeline(monkeypatch, boom)
    r = client.post("/premortem/view", json={"plan_text": PLAN})
    assert r.status_code == 500
    view = r.json()
    assert ui_errors(view) == []
    st = view["_status"]
    assert st["result_status"] == "error"
    assert st["source"] == "pipeline"
    assert st["label"] == "분석 실패"
    assert view["cards"] == [] and view["works"] == []
    assert "RuntimeError" in st["notices"][0]
    assert "secret-looking" not in r.text
    r2 = client.post("/premortem", json={"plan_text": PLAN})
    assert r2.status_code == 500
    assert r2.json()["status"] == "error"
    assert "secret-looking" not in r2.text


def test_broken_pipeline_import_is_error_not_sample(client, monkeypatch):
    def broken_import(module):
        return ("error", "import 실패: ModuleNotFoundError(sentence_transformers)") if module == "neumann.pipeline" \
            else ("ok", "")

    monkeypatch.setattr(main, "_import_state", broken_import)
    r = client.post("/premortem/view", json={"plan_text": PLAN})
    assert r.status_code == 500
    st = r.json()["_status"]
    assert st["source"] == "none"
    assert st["pipeline"] == "error"
    assert st["label"] == "분석 실패"


def test_blank_plan_is_rejected(client, no_pipeline):
    assert client.post("/premortem/view", json={"plan_text": "   \n "}).status_code == 422
    assert client.post("/premortem", json={}).status_code == 422


# ───────────────────────── 화면 · 폰트 ─────────────────────────


def test_index_is_served_without_external_resources(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    html = r.text
    # 외부에서 불러오는 리소스(스크립트·스타일·폰트·@import)가 없어야 한다
    assert not re.search(r"<(script|link|img|iframe)[^>]*(src|href)=[\"']https?://", html, re.I)
    assert not re.search(r"url\([\"']?https?://", html, re.I)
    assert "@import" not in html
    assert "fonts.googleapis" not in html and "jsdelivr" not in html and "cdnjs" not in html
    # 하드코딩된 목업 DATA 대신 API를 부른다
    assert 'id="DATA"' not in html
    assert "premortem/view" in html
    assert "김대운" in html  # 헤더 실명 배지 유지(대표 결정)


def test_every_font_face_is_served_locally(client):
    html = client.get("/").text
    urls = re.findall(r"url\(\"(fonts/[^\"]+)\"\)", html)
    assert len(urls) >= 5
    families = {u.split("/")[1] for u in urls}
    assert families == {"Pretendard", "Jost", "IBMPlexMono", "InstrumentSerif", "MrDafoe"}
    for u in urls:
        r = client.get("/" + u)
        assert r.status_code == 200, u
        assert len(r.content) > 10_000, u
    for fam in families:
        lic = list((WEBUI / "fonts" / fam).glob("OFL.txt")) + list((WEBUI / "fonts" / fam).glob("LICENSE"))
        assert lic, f"{fam} 라이선스 파일 없음"
