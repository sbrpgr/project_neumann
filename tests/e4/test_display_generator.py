"""DISP-1: 생성 방식 표시 이름 — 계약 값 astra는 그대로, 사람이 보는 화면·ZIP 문서에는 "LLM (실제 모델명)".

- 표시 함수는 한 곳(``neumann.api.view.display_generator``·``display_text``)이다. export·report_card가 가져다 쓴다.
- 화면 뷰(``build_ui_view``)와 ZIP 사람용 문서(README·리포트·계획서 주석·ai_context)에 "astra" 글자가 없다.
  예외: JSON 값(``generator: "astra"``)과 그것을 설명하는 한 줄(``JSON_GENERATOR_NOTE``), 실제 모델명이 astra 계열일 때.
- 규칙 카드를 LLM이라고 쓰지 않는다. mock은 "mock"으로 드러난다.
- 저장 JSON의 generator 값은 그대로다.

화면 스크린샷(Playwright, mock 서버)은 ``NEUMANN_UI_SHOTS=1``일 때만 돈다(브라우저·서버 필요).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from neumann.api.export import JSON_GENERATOR_NOTE, build_package
from neumann.api.view import build_ui_view, display_generator, display_text, validate_ui_view
from neumann.models import PremortemResult
from tests.fixtures.loader import load_fixtures

ROOT = Path(__file__).resolve().parents[2]
SOL = "gpt-6.1-sol"
HUMAN_DOCS = ("README.md", "neumann_report.md", "plan_annotated.md", "ai_context.md", "similar_works.csv")
NOTE_DOCS = ("README.md", "ai_context.md")  # JSON 설명 한 줄(JSON_GENERATOR_NOTE)을 싣는 문서는 이 둘뿐


def openai_result(model: str | None = SOL, *, card_model: str | None = SOL) -> dict[str, Any]:
    """fixture 결과를 '실제 서비스(openai provider)가 만든 결과' 모양으로 바꾼 가짜(호출 없음).

    카드·예상 심사평·체크리스트의 generator는 계약 값 astra, 알림·단계 사유에는 파이프라인이 쓰는 'astra' 문구를 넣는다.
    """
    data = load_fixtures().premortem_result.model_dump(mode="json")
    cards = data["risk_cards"]
    for c in cards:
        c["generator"] = "astra"
        c["model"] = card_model
    ev0 = cards[0]["evidence"][0]
    data["expected_review"] = {
        "generator": "astra", "model": model, "status": "ok",
        "weakness": [{"text": "분할 기준이 적혀 있지 않다", "evidence": [ev0]}],
    }
    data["checklist"] = [
        {"item_id": "A1", "action": "scaffold 기반 분할 추가", "risk_code": "R3", "card_id": cards[0]["card_id"],
         "plan_lines": cards[0]["why_applies"]["plan_lines"], "evidence": [ev0], "generator": "astra", "model": model},
    ]
    data["notices"] = ["검색어 캐시 적중: 이 계획서에 astra가 앞서 만든 검색어를 다시 썼다"]
    data["stages"][1].update(status="degraded", reason="astra ① 호출 시간 초과 → 규칙 태거", impl=f"openai:{model}")
    data["manifest"] = {"llm_provider": "openai", "llm_model": model}
    return data


def _strings(obj: Any, skip_keys: frozenset[str] = frozenset({"gen", "result"})):
    """뷰 안의 사람이 보는 문자열 값. 계약 값(gen)·원결과 JSON(result, E4-L2f)·dict 키는 뺀다."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in skip_keys:
                yield from _strings(v, skip_keys)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, skip_keys)
    elif isinstance(obj, str):
        yield obj


def _human_text(doc: str, name: str) -> str:
    """사람용 문서에서 JSON 값(```json 블록)과, README·ai_context면 JSON 설명 한 줄을 뺀 나머지."""
    doc = re.sub(r"```json\n.*?```", "", doc, flags=re.S)
    if name not in NOTE_DOCS:
        return doc
    return "\n".join(ln for ln in doc.splitlines() if JSON_GENERATOR_NOTE not in ln)


# ── 표시 함수 ─────────────────────────────────────────────────────────────


def test_display_generator_mapping() -> None:
    assert display_generator("astra", SOL) == f"LLM ({SOL})"
    assert display_generator("astra") == "LLM"
    assert display_generator("ASTRA", "  ") == "LLM"
    assert display_generator("rule", SOL) == "비상 규칙"  # 규칙에는 모델을 붙이지 않는다
    assert "LLM" not in display_generator("rule")
    assert "mock" in display_generator("mock", SOL) and "LLM" not in display_generator("mock", SOL)
    assert display_generator("sample") == "샘플 · 분석 결과 아님"
    assert display_generator(None) == display_generator("unknown") == "생성 방식 미표기"
    assert display_generator("baseline") == "baseline"  # 모르는 값은 추정하지 않고 그대로
    # 실제 모델이 astra 계열이면(NEUMANN_ALLOW_ASTRA) 모델명은 그대로 보인다(유일한 예외)
    assert display_generator("astra", "gpt-6-astra") == "LLM (gpt-6-astra)"


@pytest.mark.parametrize(("raw", "shown"), [
    ("astra ① 호출 시간 초과", "LLM ① 호출 시간 초과"),
    ("입력이 연구계획서가 아니다(astra 판단: 요리 메모)", "입력이 연구계획서가 아니다(LLM 판단: 요리 메모)"),
    ("실제 astra 분석이 아니다", "실제 LLM 분석이 아니다"),
    ("이 계획서에 astra가 앞서 만든 검색어", "이 계획서에 LLM이 앞서 만든 검색어"),  # 조사도 받침에 맞게
    ("astra는 · astra를 · astra와 · astra로 · astra라는", "LLM은 · LLM을 · LLM과 · LLM으로 · LLM이라는"),
    ("화면 카드 generator {'astra': 13}", "화면 카드 generator {'LLM': 13}"),
    ("평가 모델 gpt-6-astra", "평가 모델 gpt-6-astra"),            # 모델명은 그대로
    ("score_astra.json · pred_astra_gold.jsonl", "score_astra.json · pred_astra_gold.jsonl"),  # 파일 이름도
    ("openai:gpt-6.1-sol", "openai:gpt-6.1-sol"),
])
def test_display_text_only_rewrites_contract_name(raw: str, shown: str) -> None:
    assert display_text(raw) == shown


# ── 화면 뷰 ──────────────────────────────────────────────────────────────


def test_view_shows_llm_model_and_no_astra_for_openai_result() -> None:
    raw = openai_result()
    before = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    view = build_ui_view(raw, records=None, pipeline_state="connected")
    assert validate_ui_view(view) == []
    assert view["cards"] and all(cd["gen"] == "astra" for cd in view["cards"])  # 계약 값은 그대로
    assert {cd["genl"] for cd in view["cards"]} == {f"LLM ({SOL})"}
    assert view["review"]["gen"] == "astra" and view["review"]["genl"] == f"LLM ({SOL})"
    assert view["checklist"][0]["genl"] == f"LLM ({SOL})"
    st = view["_status"]
    assert st["generators"] == {"astra": len(view["cards"])}
    assert st["generator_labels"] == {"astra": f"LLM ({SOL})"}
    assert any("LLM ① 호출 시간 초과" in s["reason"] for s in st["stages_not_ok"])
    assert any("LLM이 앞서 만든 검색어" in n for n in st["notices"])
    leaked = [s for s in _strings(view) if "astra" in s.lower()]
    assert leaked == [], leaked
    # 입력(저장 JSON)은 바뀌지 않는다
    assert json.dumps(raw, ensure_ascii=False, sort_keys=True) == before
    assert PremortemResult.model_validate(raw).risk_cards[0].generator.value == "astra"


def test_view_uses_manifest_model_when_card_has_none() -> None:
    view = build_ui_view(openai_result(card_model=None), records=None, pipeline_state="connected")
    assert {cd["genl"] for cd in view["cards"]} == {f"LLM ({SOL})"}
    no_model = openai_result(model=None, card_model=None)
    view = build_ui_view(no_model, records=None, pipeline_state="connected")
    assert {cd["genl"] for cd in view["cards"]} == {"LLM"}  # 모델을 모르면 지어내지 않는다


def test_rule_cards_are_not_called_llm_and_mock_says_mock() -> None:
    raw = openai_result()
    raw["risk_cards"][0].update(generator="rule", model=None)
    raw["risk_cards"][1].update(generator="mock", model=SOL)  # mock에 모델이 적혀 있어도 LLM으로 쓰지 않는다
    view = build_ui_view(raw, records=None, pipeline_state="connected")
    rule, mock = view["cards"][0], view["cards"][1]
    assert rule["gen"] == "rule" and rule["genl"] == "비상 규칙" and "LLM" not in rule["genl"]
    assert mock["gen"] == "mock" and "mock" in mock["genl"] and "LLM" not in mock["genl"]
    labels = view["_status"]["generator_labels"]
    assert labels == {"rule": "비상 규칙", "mock": "모의(mock)"}
    assert view["_status"]["degraded"] is True  # 규칙·mock 카드는 강등으로 표시(기존 규칙 그대로)


def test_real_astra_model_is_the_only_exception() -> None:
    view = build_ui_view(openai_result(model="gpt-6-astra", card_model="gpt-6-astra"), records=None,
                         pipeline_state="connected")
    assert {cd["genl"] for cd in view["cards"]} == {"LLM (gpt-6-astra)"}
    leaked = {s for s in _strings(view) if "astra" in s.lower()}
    assert leaked and all("gpt-6-astra" in s for s in leaked), leaked


# ── ZIP 내보내기 ─────────────────────────────────────────────────────────


def _package(raw: dict[str, Any]) -> dict[str, str]:
    import io
    import zipfile

    data = build_package(PremortemResult.model_validate(raw))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {i.filename: zf.read(i).decode("utf-8-sig") for i in zf.infolist()}


def test_export_human_docs_have_no_astra_but_json_keeps_contract_value() -> None:
    files = _package(openai_result())
    for name in HUMAN_DOCS:
        rest = _human_text(files[name], name)
        assert "astra" not in rest.lower(), (name, [ln for ln in rest.splitlines() if "astra" in ln.lower()])
        assert (JSON_GENERATOR_NOTE in files[name]) == (name in NOTE_DOCS), name  # 설명 줄은 README·ai_context만
    readme, report = files["README.md"], files["neumann_report.md"]
    assert f"- 생성: LLM ({SOL})" in files["ai_context.md"]
    assert f"**LLM ({SOL})** 2장" in readme and f"LLM ({SOL}) 2장 · 비상 규칙 0장 · 모의(mock) 0장" in report
    assert f"생성: LLM ({SOL})" in report  # 예상 심사평 머리
    assert "LLM ① 호출 시간 초과" in readme and "LLM이 앞서 만든 검색어" in report
    assert f"생성 LLM ({SOL})" in report  # 체크리스트 줄
    # JSON 값은 계약 그대로
    cards = json.loads(files["risk_cards.json"])["risk_cards"]
    assert {c["generator"] for c in cards} == {"astra"} and {c["model"] for c in cards} == {SOL}
    assert json.loads(files["manifest.json"])["cards_by_generator"]["astra"] == 2
    assert {c["generator"] for c in json.loads(files["evidence_pack.json"])["cards"]} == {"astra"}


def test_export_rule_and_mock_labels() -> None:
    raw = openai_result()
    raw["risk_cards"][0].update(generator="rule", model=None)
    raw["risk_cards"][1].update(generator="mock", model=None)
    files = _package(raw)
    readme = files["README.md"]
    rule_line = next(ln for ln in readme.splitlines() if ln.startswith("- C1 "))
    mock_line = next(ln for ln in readme.splitlines() if ln.startswith("- C2 "))
    assert rule_line.endswith("— 비상 규칙") and "LLM" not in rule_line
    assert mock_line.endswith("— 모의(mock)")
    for name in HUMAN_DOCS:
        assert "astra" not in _human_text(files[name], name).lower(), name


def test_export_zero_llm_cards_does_not_name_a_model() -> None:
    """LLM 카드가 0장이면 요약에 모델명을 붙이지 않는다(manifest에 모델이 있어도 \"LLM 0장\")."""
    raw = openai_result()
    for c in raw["risk_cards"]:
        c.update(generator="mock", model=None)
    files = _package(raw)
    for name in ("README.md", "neumann_report.md", "ai_context.md"):
        doc = files[name]
        assert "LLM 0장 · 비상 규칙 0장 · 모의(mock) 2장" in doc, name
        assert f"LLM ({SOL}) 0장" not in doc and f"**LLM ({SOL})**" not in doc, name
    assert "- **LLM** 0장:" in files["README.md"]


# ── 화면 스크린샷(mock 서버, 선택) ───────────────────────────────────────


@pytest.mark.skipif(os.environ.get("NEUMANN_UI_SHOTS") != "1", reason="NEUMANN_UI_SHOTS=1일 때만(브라우저·서버 필요)")
def test_screenshot_llm_badge_without_astra(tmp_path) -> None:
    """mock 서버 화면에 openai 모양 결과 뷰를 넣어 그린다: 'LLM (모델명)' 배지, 화면 글자에 astra 없음."""
    sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
    from playwright.sync_api import sync_playwright

    from tests.e4.ui_shots import start_server, stop_server
    from tests.fixtures.loader import plan_text

    out = Path(os.environ.get("NEUMANN_UI_SHOTS_OUT") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("NEUMANN_UI_SHOTS_PORT", "8137"))
    assert port not in (8010, 8020, 8099)
    view = build_ui_view(openai_result(), records=None, pipeline_state="connected")
    body = json.dumps(view, ensure_ascii=False)
    saved = dict(os.environ)
    for k in ("OPENAI_API_KEY", "NEUMANN_LIVE_LLM_OK", "NEUMANN_LIVE_TESTS", "NEUMANN_ALLOW_ASTRA"):
        os.environ.pop(k, None)
    os.environ.update({"NEUMANN_LLM_PROVIDER": "mock", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    try:
        proc = start_server(port)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR").new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            page.wait_for_selector('body[data-view="input"][data-ready="1"]')
            page.route("**/premortem/view", lambda route, _req: route.fulfill(
                status=200, content_type="application/json", body=body))
            page.fill("#ta", plan_text())
            page.click("#btnStart")
            page.wait_for_function("document.body.dataset.view === 'report' && document.body.dataset.ready === '1' "
                                   "&& !!document.querySelector('#s-cards .rc')", timeout=120_000)
            page.evaluate("document.fonts.ready.then(() => true)")
            badges = page.eval_on_selector_all("#s-cards .rc .gen", "els => els.map(e => e.innerText)")
            page.evaluate("document.getElementById('s-cards').scrollIntoView({block: 'start'})")
            page.wait_for_timeout(250)
            page.screenshot(path=str(out / "DISP-1_cards.png"))
            page.evaluate("document.getElementById('s-trace').scrollIntoView({block: 'start'})")
            page.wait_for_timeout(250)
            page.screenshot(path=str(out / "DISP-1_trace.png"))
            shown = page.evaluate("document.body.innerText")
            trace = page.inner_text("#s-trace")
            rev = page.inner_text("#revGen")
            browser.close()
    finally:
        stop_server(proc, port)
    assert not errors, errors
    assert badges and all(b == f"LLM ({SOL})" for b in badges), badges
    assert f"LLM ({SOL}) {len(badges)}장" in trace and rev.startswith(f"LLM ({SOL})")
    assert "astra" not in shown.lower(), [ln for ln in shown.splitlines() if "astra" in ln.lower()]
