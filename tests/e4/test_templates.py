"""E4-L1b 템플릿 카탈로그 검사: JSON 스키마, 골격 필수 칸, 예시 연결, 라우터, 입력 화면 정적 검사.

main.py는 건드리지 않는다. 라우터만 붙인 임시 FastAPI 앱으로 잰다.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft7Validator

from neumann.api import templates as T

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "src" / "neumann" / "api" / "templates"
PLANS = ROOT / "tests" / "fixtures" / "plans"
INDEX = ROOT / "src" / "neumann" / "webui" / "index.html"
SCOPE = "AI 활용 과학 연구 계획서 전용"
REQUIRED_TEMPLATES = {"materials-gnn", "protein-molecule", "physics-pde-climate", "neuro-fmri", "medical-imaging"}
DEMO_PLANS = {"plan.md", "plan_elife_neuro.md", "plan_medimaging.md"}


def raw_catalog() -> dict:
    return json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(T.router)
    return TestClient(app)


# ───────────── 카탈로그 JSON 스키마 ─────────────

def test_templates_schema_is_valid_draft7() -> None:
    schema = json.loads((DATA / "catalog.schema.json").read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)


def test_templates_catalog_matches_schema() -> None:
    schema = json.loads((DATA / "catalog.schema.json").read_text(encoding="utf-8"))
    errs = [e.message for e in Draft7Validator(schema).iter_errors(raw_catalog())]
    assert errs == []
    assert T.catalog_errors(raw_catalog()) == []


@pytest.mark.parametrize("mutate, needle", [
    (lambda c: c["templates"][0].pop("summary"), "summary"),
    (lambda c: c["templates"][0].update(id="Bad ID"), "does not match"),
    (lambda c: c["templates"][0].update(extra=1), "Additional properties"),
    (lambda c: c["examples"][0].update(path="../../.env"), "does not match"),
    (lambda c: c["templates"][1].update(id=c["templates"][0]["id"]), "id 중복"),
    (lambda c: c["templates"][0].update(file="nope.md"), "골격 파일 없음"),
    (lambda c: c["examples"][0].update(template_id="no-such"), "없는 템플릿"),
    (lambda c: c["examples"][0].update(path="tests/fixtures/plans/missing.md"), "예시 파일 없음"),
    (lambda c: c["templates"][0].update(domain="요리"), "범위 밖 분야"),
])
def test_templates_catalog_checker_rejects_broken(mutate, needle: str) -> None:
    c = copy.deepcopy(raw_catalog())
    mutate(c)
    errs = T.catalog_errors(c)
    assert errs, "망가진 카탈로그가 통과했다"
    assert any(needle in e for e in errs), errs


def test_templates_skeleton_missing_section_is_caught(tmp_path, monkeypatch) -> None:
    shutil.copytree(DATA, tmp_path, dirs_exist_ok=True)
    sk = tmp_path / "materials_gnn.md"
    sk.write_text(sk.read_text(encoding="utf-8").replace("## 5. 일정", "## 5. 기타"), encoding="utf-8")
    monkeypatch.setattr(T, "DATA_DIR", tmp_path)
    errs = T.catalog_errors(raw_catalog())
    assert any("materials-gnn" in e and "일정" in e for e in errs), errs


# ───────────── 내용: 분야·골격·예시 ─────────────

def test_templates_cover_required_domains() -> None:
    c = T.load_catalog()
    assert c["scope"]["label"] == SCOPE
    assert {t["id"] for t in c["templates"]} == REQUIRED_TEMPLATES
    assert {"소재·화학·분자", "단백질·생물·신약", "물리·PDE·기후", "신경과학", "의료영상"} <= set(c["scope"]["domains"])
    assert set(c["required_sections"]) == {"연구 목표", "방법", "데이터", "평가", "일정"}


def test_templates_skeletons_have_sections_in_order_and_korean() -> None:
    c = T.load_catalog()
    for t in c["templates"]:
        text = (DATA / t["file"]).read_text(encoding="utf-8")
        secs = T.sections(text)
        assert secs[:5] == c["required_sections"], (t["id"], secs)
        assert text.startswith("# "), t["id"]
        # 칸마다 채울 항목이 1줄 이상
        for block in re.split(r"^## ", text, flags=re.M)[1:]:
            assert re.search(r"^- \S", block, re.M), (t["id"], block[:20])
        assert re.search(r"[가-힣]", text)


def test_templates_examples_are_three_demo_plans() -> None:
    c = T.load_catalog()
    assert {Path(e["path"]).name for e in c["examples"]} == DEMO_PLANS
    assert "negative_recipe.md" not in {Path(e["path"]).name for e in c["examples"]}


# ───────────── 라우터 ─────────────

def test_templates_list_route(client: TestClient) -> None:
    r = client.get("/templates")
    assert r.status_code == 200
    j = r.json()
    assert j["scope"]["label"] == SCOPE
    assert [t["id"] for t in j["templates"]] == [t["id"] for t in raw_catalog()["templates"]]
    assert all(t["kind"] == "template" and t["sections"][:5] == j["required_sections"] for t in j["templates"])
    assert len(j["examples"]) == 3
    assert all(e["kind"] == "example" and e["title"] and e["filename"] in DEMO_PLANS for e in j["examples"])
    assert "text" not in j["templates"][0]  # 목록에는 본문을 싣지 않는다


@pytest.mark.parametrize("tid", sorted(REQUIRED_TEMPLATES))
def test_templates_item_route_returns_skeleton(client: TestClient, tid: str) -> None:
    r = client.get(f"/templates/{tid}")
    assert r.status_code == 200
    j = r.json()
    assert j["id"] == tid and j["kind"] == "template" and j["filename"] is None
    t = next(x for x in raw_catalog()["templates"] if x["id"] == tid)
    assert j["text"] == (DATA / t["file"]).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert j["chars"] == len(j["text"])
    for s in ("연구 목표", "방법", "데이터", "평가", "일정"):
        assert re.search(rf"^## \d+\. {s}$", j["text"], re.M), (tid, s)


def test_templates_item_route_returns_example_verbatim(client: TestClient) -> None:
    for e in raw_catalog()["examples"]:
        j = client.get(f"/templates/{e['id']}").json()
        want = (ROOT / e["path"]).read_text(encoding="utf-8").replace("\r\n", "\n")
        assert j["kind"] == "example" and j["text"] == want
        assert j["filename"] == Path(e["path"]).name
        assert j["template_id"] == e["template_id"]


def test_templates_unknown_and_bad_ids(client: TestClient) -> None:
    assert client.get("/templates/no-such-template").status_code == 404
    for bad in ("..%2F..%2F.env", "Materials-GNN", "a_b", "x" * 65):
        assert client.get(f"/templates/{bad}").status_code in (404, 422), bad


def test_templates_broken_catalog_returns_500_not_empty(client: TestClient, monkeypatch) -> None:
    def boom():
        raise T.CatalogError("테스트용 고장")
    monkeypatch.setattr(T, "load_catalog", boom)
    r = client.get("/templates")
    assert r.status_code == 500 and "테스트용 고장" in r.json()["reason"]
    assert client.get("/templates/materials-gnn").status_code == 500


# ───────────── 입력 화면(정적) ─────────────

def test_templates_input_screen_has_picker_scope_examples_and_fitness_slot() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert SCOPE in html  # API가 죽어도 범위 안내는 보인다
    assert "fetch('templates'" in html  # 상대 경로(루트 prefix 없이)
    for id_ in ('id="scope"', 'id="tplList"', 'id="exList"', 'id="fitBox"'):
        assert id_ in html, id_
    assert "showFitness" in html
    assert not re.search(r"(src|href)=[\"']https?://", html, re.I)
    assert "@import" not in html
