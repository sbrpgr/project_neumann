"""E6-L3a 정적 배포 빌드 테스트.

- 합성 화면(작은 index.html + 폰트 1개)과 가짜 화면 데이터 조립기로 빌드 절차를 잰다. 화면 원본(E4)이 없어도 돈다.
- 화면 원본(src/neumann/webui)과 E4 조립기(neumann.api.view)가 있으면 실제 빌드도 잰다(없으면 사유를 남기고 건너뜀).
- 검사기(check_site)가 심어 둔 비밀값·로컬 경로·외부 참조·환경변수 이름·빠진 파일을 실제로 잡는지 잰다.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from neumann.models import PlanDocument

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("build_static_site", ROOT / "scripts" / "build_static_site.py")
assert _spec and _spec.loader
bss = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bss
_spec.loader.exec_module(bss)

PLANS = ROOT / "tests" / "fixtures" / "plans"
FIXTURE = ROOT / "tests" / "fixtures" / "premortem_result.json"
DEMO_IDS = ("plan", "protein_ligand_affinity", "neural_operator_weather")  # 범위 밖 예시는 사전 계산본이 있을 때만

FAKE_INDEX = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>Neumann</title>
<style>@font-face { font-family: "X"; src: url("fonts/X/x.woff2") format("woff2"); }</style>
</head>
<body data-view="boot"><header class="top"><span id="hdrState">서버 확인 중</span></header>
<div id="app"></div>
<script>fetch('health').then(function (r) { return r.json(); });</script>
</body></html>
"""


def fake_view(result: dict[str, Any], *, filename: str | None, sample: bool, pipeline_state: str,
              input_info: dict[str, Any], extra_notices: list[str]) -> dict[str, Any]:
    plan = result.get("plan") or {}
    return {
        "plan": {"file": filename, "lines": [{"n": ln["no"], "t": ln["text"]} for ln in plan.get("lines", [])]},
        "cards": [{"id": c["card_id"]} for c in result.get("risk_cards", [])],
        "works": [{"n": i} for i, _ in enumerate(result.get("similar_works", []), 1)],
        "_status": {"source": "sample" if sample else "pipeline", "pipeline": pipeline_state, "label": "",
                    "notices": list(extra_notices), "input": dict(input_info)},
    }


@pytest.fixture()
def webui(tmp_path: Path) -> Path:
    d = tmp_path / "webui"
    (d / "fonts" / "X").mkdir(parents=True)
    (d / "index.html").write_text(FAKE_INDEX, encoding="utf-8")
    (d / "fonts" / "X" / "x.woff2").write_bytes(b"wOF2" + b"\0" * 64)
    (d / "fonts" / "X" / "OFL.txt").write_text("SIL Open Font License 1.1\n", encoding="utf-8")
    return d


def build(tmp_path: Path, webui: Path, pre: Path | None = None, **kw: Any) -> tuple[Path, dict[str, Any]]:
    out = tmp_path / "data" / "site"
    summary = bss.build_site(out, precomputed_dir=pre, webui_dir=webui, build_view=fake_view,
                             validate=lambda v: [], **kw)
    return out, summary


def static_blob(site: Path) -> dict[str, Any]:
    page = (site / "index.html").read_text(encoding="utf-8")
    m = re.search(r"window\.NEUMANN_STATIC = (\{.*?\});</script>", page, flags=re.S)
    assert m, "NEUMANN_STATIC 주입 없음"
    return json.loads(m.group(1))


def plan_id(name: str) -> str:
    return PlanDocument.from_text((PLANS / name).read_text(encoding="utf-8"), "t").plan_id


def write_precomputed(pre: Path, *, name: str = "plan.md", strip_plan: bool = False, sha: str | None = "auto",
                      model: str = "gpt-6-astra", when: str = "2026-09-30T10:12:00Z") -> Path:
    pre.mkdir(parents=True, exist_ok=True)
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pid = plan_id(name)
    assert data["plan_id"] == pid, "공용 fixture는 plan.md 기준이어야 한다"
    data.update({"generated_at": when, "notices": [], "manifest": {"model_id": model, "model_provider": "openai"}})
    if strip_plan:
        data["plan"] = None
    path = pre / f"{pid}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    entry: dict[str, Any] = {"plan_id": pid, "file": path.name, "generated_at": when}
    if sha == "auto":
        entry["sha256"] = bss._sha256_bytes(path.read_bytes())
    elif sha:
        entry["sha256"] = sha
    (pre / "manifest.json").write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    return path


# ───────────────────────── 빌드 절차 ─────────────────────────


def test_fixture_fallback_builds_complete_site(tmp_path: Path, webui: Path) -> None:
    before = (webui / "index.html").read_bytes()
    site, summary = build(tmp_path, webui, pre=tmp_path / "없는폴더")

    assert (webui / "index.html").read_bytes() == before, "화면 원본을 고치면 안 된다"
    for rel in ("index.html", "demo/index.json", "build.json", ".nojekyll", "fonts/X/x.woff2", "fonts/X/OFL.txt",
                *(f"demo/{d}.json" for d in DEMO_IDS)):
        assert (site / rel).is_file(), rel
    assert [d["kind"] for d in summary["demos"]] == ["fixture"] * 3
    assert summary["label"] == "정적 판 · 샘플(가짜 데이터) — 라이브 분석 아님"
    # 범위 밖 예시(요리 메모)에 남의 fixture 카드를 붙여 보여 주지 않는다
    assert [d["id"] for d in summary["dropped_demos"]] == ["negative_recipe"]
    assert not (site / "demo" / "negative_recipe.json").exists()

    for d in DEMO_IDS:
        view = json.loads((site / "demo" / f"{d}.json").read_text(encoding="utf-8"))
        st = view["_status"]
        assert st["static"]["kind"] == "fixture" and st["static"]["live"] is False
        assert "라이브 분석 아님" in st["label"] and "사전 계산본 없음" in st["label"]
        assert st["source"] == "sample"
        assert any("사전 계산본을 쓰지 못함" in n for n in st["notices"])
        # plan.md가 아닌 데모는 남의 계획서 결과임을 밝힌다
        assert any("예시 계획서(plan.md)" in n for n in st["notices"]) == (d != "plan")

    problems, stats = bss.check_site(site)
    assert problems == [], problems
    assert stats["demos"] == 3


def test_static_injection_is_relative_and_complete(tmp_path: Path, webui: Path) -> None:
    site, _ = build(tmp_path, webui)
    page = (site / "index.html").read_text(encoding="utf-8")
    blob = static_blob(site)

    assert page.count('id="neumann-static-shim"') == 1 and page.count('id="neumann-static-input"') == 1
    assert page.index('id="neumann-static-shim"') < page.index("fetch('health')"), "가로채기는 화면 스크립트보다 먼저"
    assert 'id="staticBanner"' in page and "라이브 분석 아님" in page
    assert "fetch('health')" in page, "원본 화면 스크립트는 그대로 들어간다"
    assert [d["id"] for d in blob["demos"]] == list(DEMO_IDS)
    for d in blob["demos"]:
        assert d["json"] == f"demo/{d['id']}.json", "상대 경로(Pages 하위 경로)"
        assert d["plan_text"] == (ROOT / d["path"]).read_text(encoding="utf-8") and d["role"] == "demo"
        assert d["sha256"] == bss._sha256_bytes((site / d["json"]).read_bytes())
    assert blob["health"]["pipeline"]["state"] == "unavailable"
    assert "라이브 분석 아님" in blob["health"]["pipeline"]["label"]
    assert blob["not_found"]["_status"]["label"].startswith("정적 판")
    # 루트 절대 경로('/…')나 외부 주소를 부르는 리소스가 없다
    assert not re.search(r"""(?:src|href)\s*=\s*["']/(?!/)""", page)
    assert not re.search(r"""(?:src|href)\s*=\s*["'](?:https?:)?//""", page)


FAKE_TEMPLATES = {
    "index": {"version": 1, "scope": {"label": "t", "domains": ["d"]}, "required_sections": [],
              "templates": [{"id": "tpl-a", "kind": "template", "name": "A"}],
              "examples": [{"id": "ex-plan", "kind": "example", "name": "P", "filename": "plan.md"}]},
    "items": {"tpl-a": {"id": "tpl-a", "kind": "template", "text": "# 골격\n## 1. 연구 목표\n"},
              "ex-plan": {"id": "ex-plan", "kind": "example", "text": (PLANS / "plan.md").read_text(encoding="utf-8")}},
}


def test_templates_are_served_as_static_json(tmp_path: Path, webui: Path) -> None:
    """E4-L1b 템플릿 선택기(GET templates, templates/{id})를 정적 JSON으로 돌려준다."""
    (webui / "index.html").write_text(FAKE_INDEX.replace("fetch('health')", "fetch('templates')"), encoding="utf-8")
    site, summary = build(tmp_path, webui, templates_source=lambda: FAKE_TEMPLATES)
    assert summary["templates"] == 2
    assert json.loads((site / "templates.json").read_text(encoding="utf-8")) == FAKE_TEMPLATES["index"]
    for item_id, item in FAKE_TEMPLATES["items"].items():
        assert json.loads((site / "templates" / f"{item_id}.json").read_text(encoding="utf-8")) == item
    blob = static_blob(site)
    assert blob["templates"] == {"index": "templates.json", "dir": "templates/", "ids": ["tpl-a", "ex-plan"]}
    page = (site / "index.html").read_text(encoding="utf-8")
    assert "r === 'templates'" in page and "ST.templates.dir + id + '.json'" in page
    assert blob["not_demo_note"].startswith("정적 판")
    problems, stats = bss.check_site(site)
    assert problems == [] and stats["templates"] == 2

    (site / "templates" / "tpl-a.json").unlink()
    assert any(p.startswith("[필수] templates/tpl-a.json") for p in bss.check_site(site)[0])


def test_page_calling_templates_needs_catalog(tmp_path: Path, webui: Path) -> None:
    (webui / "index.html").write_text(FAKE_INDEX.replace("fetch('health')", "fetch('templates')"), encoding="utf-8")
    with pytest.raises(RuntimeError, match="templates"):
        build(tmp_path, webui, templates_source=lambda: None)
    bad = {"index": FAKE_TEMPLATES["index"], "items": {"../x": {"id": "../x", "text": ""}}}
    with pytest.raises(ValueError, match="id"):
        build(tmp_path, webui, templates_source=lambda: bad)
    assert not (tmp_path / "data" / "site").exists()


def test_real_template_catalog_matches_api() -> None:
    try:
        from neumann.api.templates import get_template, list_templates
    except ImportError:
        pytest.skip("neumann.api.templates 없음(E4-L1b 병합 전)")
    got = bss._default_templates()
    assert got is not None and got["index"] == list_templates()
    ids = [t["id"] for t in got["index"]["templates"]] + [e["id"] for e in got["index"]["examples"]]
    assert list(got["items"]) == ids and all(got["items"][i] == get_template(i) for i in ids)
    assert all(bss.TEMPLATE_ID.match(i) for i in ids)


def test_script_json_cannot_close_script_tag() -> None:
    s = bss._script_json({"t": "</script><script>alert(1)</script> <!-- &  "})
    assert "</" not in s and "<!--" not in s and " " not in s
    assert json.loads(s)["t"].startswith("</script>")


def test_precomputed_is_used_and_labelled(tmp_path: Path, webui: Path) -> None:
    write_precomputed(tmp_path / "pre")
    site, summary = build(tmp_path, webui, pre=tmp_path / "pre")

    kinds = {d["id"]: d["kind"] for d in summary["demos"]}
    assert kinds == {"plan": "precomputed", "protein_ligand_affinity": "fixture", "neural_operator_weather": "fixture"}
    assert summary["label"] == "정적 판 · 사전 계산본 1/3 · 나머지 가짜 데이터 — 라이브 분석 아님"
    view = json.loads((site / "demo" / "plan.json").read_text(encoding="utf-8"))
    st = view["_status"]
    assert st["label"] == "사전 계산본(생성 2026-09-30 19:12 KST · 모델 gpt-6-astra (openai)) — 라이브 분석 아님"
    assert st["source"] == "pipeline" and st["static"]["manifest_sha256_ok"] is True
    assert st["static"]["origin"] == "pipeline"
    assert any("sha256이 매니페스트" in n for n in st["notices"])
    assert bss.check_site(site)[0] == []


def test_precomputed_fixture_substitute_is_not_called_real(tmp_path: Path, webui: Path) -> None:
    """E6-L2a 매니페스트 모양(entries[].demo·source·impl·models) — 저장본이 fixture 대체라고 밝히면 그렇게 표시한다."""
    pre = tmp_path / "pre"
    path = write_precomputed(pre)
    entry = {"plan_id": plan_id("plan.md"), "demo": "plan", "file": path.name,
             "sha256": bss._sha256_bytes(path.read_bytes()), "source": "fixture", "impl": "fallback:fixture",
             "models": []}
    (pre / "manifest.json").write_text(json.dumps({"kind": "neumann.precomputed", "source": "fixture",
                                                   "entries": [entry]}), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["manifest"] = {}
    path.write_text(json.dumps(data), encoding="utf-8")
    entry["sha256"] = bss._sha256_bytes(path.read_bytes())
    (pre / "manifest.json").write_text(json.dumps({"entries": [entry]}), encoding="utf-8")

    site, summary = build(tmp_path, webui, pre=pre)
    plan = next(d for d in summary["demos"] if d["id"] == "plan")
    assert plan["kind"] == "precomputed" and plan["substitute"] is True and plan["origin"] == "fixture"
    st = json.loads((site / "demo" / "plan.json").read_text(encoding="utf-8"))["_status"]
    assert st["label"].startswith("사전 계산본(fixture 대체 · 가짜 데이터 · 생성 ") and "라이브 분석 아님" in st["label"]
    assert st["source"] == "sample" and st["static"]["substitute"] is True
    assert any("실제 분석이 아니라 대체 결과" in n for n in st["notices"])
    assert summary["label"] == "정적 판 · 샘플(가짜 데이터) — 라이브 분석 아님"
    blob = static_blob(site)
    assert blob["demos"][0]["substitute"] is True and "fixture 대체" in blob["demos"][0]["badge"]


def test_precomputed_without_plan_body_gets_public_demo_plan(tmp_path: Path, webui: Path) -> None:
    write_precomputed(tmp_path / "pre", strip_plan=True)
    site, _ = build(tmp_path, webui, pre=tmp_path / "pre")
    view = json.loads((site / "demo" / "plan.json").read_text(encoding="utf-8"))
    text = (PLANS / "plan.md").read_text(encoding="utf-8")
    assert view["_status"]["static"]["kind"] == "precomputed"
    assert [ln["t"] for ln in view["plan"]["lines"]] == text.split("\n")


def test_tampered_or_mismatched_precomputed_falls_back(tmp_path: Path, webui: Path) -> None:
    path = write_precomputed(tmp_path / "pre")
    path.write_text(path.read_text(encoding="utf-8").replace("gpt-6-astra", "gpt-6-astrX"), encoding="utf-8")
    site, summary = build(tmp_path, webui, pre=tmp_path / "pre")
    plan = next(d for d in summary["demos"] if d["id"] == "plan")
    assert plan["kind"] == "fixture" and "변조" in plan["reason"]
    view = json.loads((site / "demo" / "plan.json").read_text(encoding="utf-8"))
    assert "사전 계산본 없음" in view["_status"]["label"]

    # plan_id가 다른 저장본은 이름이 같아도 그 데모에 쓰지 않는다
    other = tmp_path / "pre2"
    other.mkdir()
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    (other / "neural_operator_weather.json").write_text(json.dumps(data), encoding="utf-8")
    _, summary2 = build(tmp_path, webui, pre=other)
    kinds = {d["id"]: d["kind"] for d in summary2["demos"]}
    assert kinds["neural_operator_weather"] == "fixture"
    assert kinds["plan"] == "precomputed", "plan_id가 맞으면 파일 이름과 무관하게 찾는다"


def test_refuses_to_overwrite_foreign_folder(tmp_path: Path, webui: Path) -> None:
    out = tmp_path / "data" / "site"
    out.mkdir(parents=True)
    (out / "keep.txt").write_text("남의 파일", encoding="utf-8")
    with pytest.raises(FileExistsError):
        build(tmp_path, webui)
    assert (out / "keep.txt").is_file()
    build(tmp_path, webui, force=True)
    assert not (out / "keep.txt").exists() and (out / "build.json").is_file()
    build(tmp_path, webui)  # 이 빌드가 만든 폴더는 다시 덮어쓴다


def test_injection_needs_exactly_one_anchor(tmp_path: Path, webui: Path) -> None:
    (webui / "index.html").write_text(FAKE_INDEX.replace("</header>", ""), encoding="utf-8")
    with pytest.raises(ValueError, match="</header>"):
        build(tmp_path, webui)
    assert not (tmp_path / "data" / "site").exists(), "실패한 빌드는 산출 폴더를 남기지 않는다"


def test_missing_webui_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        bss.build_site(tmp_path / "site", precomputed_dir=None, webui_dir=tmp_path / "없음", build_view=fake_view)


# ───────────────────────── 검사기 ─────────────────────────


def _append(site: Path, rel: str, text: str) -> None:
    p = site / rel
    p.write_text(p.read_text(encoding="utf-8") + text, encoding="utf-8")


PLANTS = {
    "비밀값 패턴": (lambda s: _append(s, "demo/plan.json", " " + "s" + "k-proj-" + "A1b2" * 8), "[비밀값]"),
    "Windows 경로": (lambda s: _append(s, "index.html", "<!-- " + "C:" + "\\Users\\someone\\x -->"), "[내부 경로]"),
    "JSON 속 Windows 경로": (lambda s: _append(s, "demo/index.json", " " + json.dumps("D:" + "/work/x")), "[내부 경로]"),
    "사용자 홈 경로": (lambda s: _append(s, "build.json", ' "/' + 'home/someone/x"'), "[내부 경로]"),
    "이 기계 절대 경로": (lambda s: _append(s, "demo/plan.json", " " + json.dumps(str(ROOT))), "[내부 경로]"),
    "외부 스크립트": (lambda s: _append(s, "index.html", '<script src="https://cdn.example.com/x.js"></script>'), "[외부 요청]"),
    "외부 CSS url": (lambda s: _append(s, "index.html", '<style>a{background:url(//img.example.com/a.png)}</style>'), "[외부 요청]"),
    "외부 fetch": (lambda s: _append(s, "index.html", "<script>fetch('https://api.example.com/x')</script>"), "[외부 요청]"),
    "루트 절대 경로": (lambda s: _append(s, "index.html", '<link rel="stylesheet" href="/fonts/a.css">'), "[경로]"),
    "환경변수 이름": (lambda s: _append(s, "demo/plan.json", " NEUMANN_" + "DATA_DIR"), "[환경변수]"),
    "데모 JSON 빠짐": (lambda s: (s / "demo" / "neural_operator_weather.json").unlink(), "[필수]"),
    "데모 JSON 변조": (lambda s: _append(s, "demo/plan.json", " "), "[필수]"),
    "폰트 빠짐": (lambda s: (s / "fonts" / "X" / "x.woff2").unlink(), "[필수]"),
}


@pytest.mark.parametrize("name", list(PLANTS))
def test_check_site_catches_planted_problem(tmp_path: Path, webui: Path, name: str) -> None:
    site, _ = build(tmp_path, webui)
    assert bss.check_site(site)[0] == []
    plant, tag = PLANTS[name]
    plant(site)
    problems, _ = bss.check_site(site)
    assert any(p.startswith(tag) for p in problems), (name, problems)


def test_check_site_catches_real_secret_value(tmp_path: Path, webui: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = "zz-static-site-leak-probe-0042"  # 비밀값 패턴에 걸리지 않는 가짜 값
    monkeypatch.setenv("OPENAI_API_KEY", fake)
    site, _ = build(tmp_path, webui)
    assert bss.check_site(site)[0] == []
    _append(site, "demo/plan.json", " " + fake)
    problems, _ = bss.check_site(site)
    assert any(p.startswith("[유출]") for p in problems)
    assert not any(fake in p for p in problems), "찾은 값은 출력하지 않는다"


def test_https_links_in_data_are_not_requests(tmp_path: Path, webui: Path) -> None:
    """근거의 원문 링크(a[href])는 요청이 아니므로 외부 요청으로 세지 않는다."""
    site, _ = build(tmp_path, webui)
    _append(site, "index.html", '<a href="https://openreview.net/forum?id=abc" target="_blank">원문</a>')
    assert bss.check_site(site)[0] == []


# ───────────────────────── 실제 화면 원본 ─────────────────────────


def _real_tools():
    if not (bss.WEBUI_DIR / "index.html").is_file():
        pytest.skip("화면 원본 src/neumann/webui/index.html 없음(E4 병합 전)")
    try:
        from neumann.api.view import build_ui_view, validate_ui_view
    except ImportError:
        pytest.skip("neumann.api.view 없음(E4 병합 전)")
    return build_ui_view, validate_ui_view


def test_real_webui_build_passes_contract_and_checks(tmp_path: Path) -> None:
    build_ui_view, validate_ui_view = _real_tools()
    write_precomputed(tmp_path / "pre")
    out = tmp_path / "site"
    summary = bss.build_site(out, precomputed_dir=tmp_path / "pre")
    assert [d["kind"] for d in summary["demos"]] == ["precomputed", "fixture", "fixture"]
    for d in DEMO_IDS:
        view = json.loads((out / "demo" / f"{d}.json").read_text(encoding="utf-8"))
        assert validate_ui_view(view) == [], d
        assert "라이브 분석 아님" in view["_status"]["label"]
        assert view["cards"], "fixture·사전 계산본 모두 카드가 있다"
    src = (bss.WEBUI_DIR / "index.html").read_text(encoding="utf-8")
    page = (out / "index.html").read_text(encoding="utf-8")
    app_script = src[src.rindex("<script>"):src.rindex("</script>")]
    assert app_script in page, "원본 화면 스크립트는 한 글자도 바꾸지 않는다"
    for ref in re.findall(r"""url\(\s*["']?(fonts/[^"')\s]+)""", src):
        assert (out / ref).is_file(), ref
    problems, stats = bss.check_site(out)
    assert problems == [], problems
    assert stats["demos"] == 3
    if bss.PAGE_CALLS_TEMPLATES.search(src):  # E4-L1b 템플릿 선택기
        assert summary["templates"] > 0 and stats["templates"] == summary["templates"]


# ───────────────────────── E6-L3d: 라이브 결과 사전 계산본 ─────────────────────────

LIVE_BADGE = "사전 계산본(라이브 서버, gpt-6.1-sol, 2026-09-30 21:20 KST)"


def live_store(tmp_path: Path, **kw: Any) -> Path:
    """precompute_demo.py --from-results로 가짜 라이브 결과(E5-L1e2e 모양)를 가져온 사전 계산본 폴더."""
    from tests.e6.e6_support import load_script, write_live_results

    pd = load_script()
    res = write_live_results(tmp_path / "E5-L1e2e_live", list(pd.DEMO_PLANS), **kw)
    manifest, failures = pd.import_live(pd.demo_specs(), res, tmp_path / "pre", log=lambda _m: None)
    assert failures == [] and manifest["source"] == "live_e2e"
    return tmp_path / "pre"


def test_demo_plans_match_precompute_and_drop_old_examples() -> None:
    from tests.e6.e6_support import load_script

    assert bss.DEMO_PLANS == load_script().DEMO_PLANS
    joined = " ".join(bss.DEMO_PLANS).lower()
    assert "elife" not in joined and "medimaging" not in joined and "fmri" not in joined
    assert [d.demo_id for d in bss.load_demos()] == [*DEMO_IDS, "negative_recipe"]
    assert [d.role for d in bss.load_demos()] == ["demo", "demo", "demo", "out_of_scope"]


def test_live_precomputed_shows_live_badge(tmp_path: Path, webui: Path) -> None:
    site, summary = build(tmp_path, webui, pre=live_store(tmp_path))
    assert [d["id"] for d in summary["demos"]] == [*DEMO_IDS, "negative_recipe"] and summary["dropped_demos"] == []
    assert all(d["kind"] == "precomputed" and d["origin"] == "live_e2e" and d["live_source"] for d in summary["demos"])
    assert all(d["badge"] == LIVE_BADGE and d["substitute"] is False for d in summary["demos"])
    assert summary["label"] == f"정적 판 · {LIVE_BADGE} — 라이브 분석 아님"

    page = (site / "index.html").read_text(encoding="utf-8")
    banner = re.search(r'<div class="sbanner" id="staticBanner".*?</div>', page, flags=re.S).group(0)
    assert "라이브 서버, gpt-6.1-sol, 2026-09-30 21:20 KST" in banner and "라이브 분석 아님" in banner
    blob = static_blob(site)
    assert [d["badge"] for d in blob["demos"]] == [LIVE_BADGE] * 4
    assert blob["demos"][3]["role"] == "out_of_scope" and "범위 밖 입력" in page
    for d in (*DEMO_IDS, "negative_recipe"):
        st = json.loads((site / "demo" / f"{d}.json").read_text(encoding="utf-8"))["_status"]
        assert st["label"] == f"{LIVE_BADGE} — 라이브 분석 아님"
        assert st["source"] == "pipeline" and st["static"]["live_source"] is True and st["static"]["provider"] == "openai"
        assert any("라이브 서버(8020)에서 gpt-6.1-sol로 분석한 결과" in n for n in st["notices"])
    problems, stats = bss.check_site(site)
    assert problems == [] and stats["demos"] == 4


def test_live_mock_or_rule_results_are_not_called_real(tmp_path: Path, webui: Path) -> None:
    """라이브 서버가 mock으로 돌았거나 규칙 대체 카드가 있으면 배지에 그대로 적는다."""
    pre = live_store(tmp_path, provider="mock", model="mock-deterministic-v1", rule_cards=1)
    site, summary = build(tmp_path, webui, pre=pre)
    plan = summary["demos"][0]
    assert plan["substitute"] is True and plan["provider"] == "mock"
    assert plan["badge"] == ("사전 계산본(라이브 서버, mock-deterministic-v1, 2026-09-30 21:20 KST) · "
                             "mock 결과 · 가짜 데이터 · 규칙 대체 1장")
    assert summary["label"].endswith("mock 결과 · 가짜 데이터) — 라이브 분석 아님")
    st = json.loads((site / "demo" / "plan.json").read_text(encoding="utf-8"))["_status"]
    assert st["source"] == "sample" and any("규칙 합성(비상 경로)" in n for n in st["notices"])
    assert bss.check_site(site)[0] == []


def test_check_site_requires_all_ai4s_demos(tmp_path: Path, webui: Path) -> None:
    site, _ = build(tmp_path, webui, pre=live_store(tmp_path))
    idx_path = site / "demo" / "index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    idx["demos"] = [d for d in idx["demos"] if d["id"] != "protein_ligand_affinity"]
    idx_path.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    problems, _ = bss.check_site(site)
    assert any("빠진 AI4S 예시 ['protein_ligand_affinity']" in p for p in problems), problems


def test_real_webui_build_with_live_results(tmp_path: Path) -> None:
    _, validate_ui_view = _real_tools()
    out = tmp_path / "site"
    summary = bss.build_site(out, precomputed_dir=live_store(tmp_path))
    assert [d["badge"] for d in summary["demos"]] == [LIVE_BADGE] * 4
    for d in (*DEMO_IDS, "negative_recipe"):
        view = json.loads((out / "demo" / f"{d}.json").read_text(encoding="utf-8"))
        assert validate_ui_view(view) == [], d
        assert view["_status"]["label"] == f"{LIVE_BADGE} — 라이브 분석 아님"
        assert bool(view["cards"]) == (d != "negative_recipe")
    problems, stats = bss.check_site(out)
    assert problems == [] and stats["demos"] == 4
