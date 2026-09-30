"""PROV-LABEL opt-in headless 화면 검사: 81xx mock 서버, 자체 프로세스만 종료."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest

from neumann.analyze import validate
from neumann.analyze.mock_responders import default_responders
from neumann.api.view import build_ui_view
from neumann.llm import MockProvider
from neumann.pipeline import run_premortem
from tests.e3.corpus import PLAN_BATTERY, build_backend
from tests.e3.test_prov_label import LEAK, SEED, MODEL, _base, _callback, _judge

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(os.getenv("NEUMANN_PROV_LABEL_UI") != "1", reason="opt-in headless mock 화면 검사")


def _free_port():
    for port in range(8180, 8200):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    pytest.fail("사용 가능한 81xx 시험 포트가 없음")


@pytest.mark.parametrize("width", [1440, 390])
def test_provenance_notices_and_labels_render_headlessly(width, tmp_path):
    from playwright.sync_api import sync_playwright

    responders = default_responders()
    rule = run_premortem(PLAN_BATTERY, provider="mock", backend=build_backend(), cache_dir=None,
                         llm=MockProvider(responders, fail={task: "timeout" for task in responders}))
    assert rule.plan_checks["search"]["queries_source"] == "rule"
    assert rule.verification["semantic"]["generator"] == "rule"
    assert {c.generator.value for c in rule.risk_cards} == {"rule"}
    result, plan = _base()
    judge = _judge({LEAK: "match", SEED: "match"})

    def partial(payload):
        response = judge(payload)
        response["cards"] = [c for c in response["cards"] if c["card_id"] == LEAK]
        return response

    report = validate.validate_cards(result, plan, _callback(partial), generator="astra", model=MODEL)
    mixed = validate.apply_validation(result, report)
    assert report["generator"] == "mixed"
    port = _free_port()
    env = dict(os.environ)
    for key in ("OPENAI_API_KEY", "NEUMANN_PSEUDONYM_SALT", "NEUMANN_LIVE_LLM_OK", "NEUMANN_LIVE_TESTS"):
        env.pop(key, None)
    env.update(NEUMANN_LLM_PROVIDER="mock", PYTHONPATH="src;.", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    # 설정 로더의 .env 읽기까지 닫은 뒤 시험 서버를 연다.
    boot = (
        "import neumann.config as c; c.Settings.model_config['env_file']=None; "
        "import neumann.index.settings as i; i.IndexSettings.model_config['env_file']=None; "
        f"import uvicorn; uvicorn.run('neumann.api.main:app',host='127.0.0.1',port={port},log_level='warning')"
    )
    proc = subprocess.Popen([sys.executable, "-c", boot], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = Path(os.getenv("NEUMANN_PROV_LABEL_UI_OUT") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail("시험 서버 조기 종료")
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            pytest.fail("시험 서버 준비 시간 초과")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for origin, source, expected in (("rule", rule, "비상 규칙"), ("mixed", mixed, "혼합")):
                    page = browser.new_page(viewport={"width": width, "height": 900}, locale="ko-KR")
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    view = build_ui_view(source, records=None)
                    page.route("**/premortem/jobs", lambda route: route.fulfill(status=404, body="{}"))
                    page.route("**/premortem/view", lambda route: route.fulfill(
                        status=200, content_type="application/json", body=json.dumps(view, ensure_ascii=False)))
                    page.goto(base, wait_until="networkidle")
                    page.wait_for_selector('body[data-view="input"][data-ready="1"]')
                    page.fill("#ta", PLAN_BATTERY)
                    page.click("#btnStart")
                    page.wait_for_selector('body[data-view="report"][data-ready="1"]', timeout=30000)
                    notice = page.inner_text("#statusNotice")
                    assert f"2차 의미검증 출처: {expected}" in notice
                    if origin == "rule":
                        assert "검색어 규칙 대체" in notice
                    badges = page.locator("#s-cards .rc .gen").all_inner_texts()
                    assert badges
                    assert set(badges) == set(view["_status"]["generator_labels"].values())
                    assert "LLM" not in " · ".join(badges)
                    page.screenshot(path=str(out / f"{origin}_{width}.png"), full_page=True)
                    assert not errors
                    page.close()
            finally:
                browser.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        # Windows에서는 프로세스 종료 직후 소켓이 잠깐 남는다. 닫힘까지 확인한다.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) != 0:
                    break
            time.sleep(0.2)
        else:
            pytest.fail("자체 시험 서버 종료 후 포트가 닫히지 않음")
