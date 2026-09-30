"""E4-L1b 입력 화면 Playwright 검사(1440×900): 범위 안내 · 템플릿 선택기 · 예시 불러오기 · 적합성 판정 자리.

    NEUMANN_UI_TESTS=1 python -m pytest tests/e4/test_templates_ui.py -q -s
    python tests/e4/test_templates_ui.py [--port 8121] [--out docs/reports]

- 기본 pytest(verify)에서는 건너뛴다(브라우저·서버가 필요). ``NEUMANN_UI_TESTS=1``일 때만 돈다.
- main.py는 건드리지 않는다. 하위 프로세스에서 ``main.app``에 이 과제의 ``router``를 붙여 띄우고(이미 붙어 있으면 그대로),
  끝나면(실패해도) 종료한다. 포트 8010(대표 점검 서버)은 쓰지 않는다.
- 렌더 완료 DOM 조건(``data-ready``, 템플릿 버튼 수, 입력칸 값)을 기다린 뒤 찍는다.
- 콘솔 오류·페이지 오류·실패 요청·외부 도메인 요청을 센다. 본 흐름에서 하나라도 있으면 실패.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "src" / "neumann" / "api" / "templates"
PLANS = ROOT / "tests" / "fixtures" / "plans"
OUT = ROOT / "docs" / "reports"
PREFIX = "E4-L1b"
DEFAULT_PORT = 8121
FORBIDDEN_PORT = 8010
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SCOPE = "AI 활용 과학 연구 계획서 전용"

SERVER_CODE = """
import sys, uvicorn
from neumann.api.main import app
from neumann.api.templates import router
if not any(getattr(r, 'path', '') == '/templates' for r in app.routes):
    app.include_router(router)
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
"""

pytestmark = pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="NEUMANN_UI_TESTS=1일 때만(브라우저·서버 필요)")


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def start_server(port: int) -> subprocess.Popen:
    import httpx

    if port == FORBIDDEN_PORT:
        raise SystemExit("8010은 대표 점검 서버 포트다. 다른 포트를 써라")
    if not _port_free(port):
        raise SystemExit(f"포트 {port}가 이미 쓰이고 있다")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]))
    proc = subprocess.Popen([sys.executable, "-c", SERVER_CODE, str(port)], cwd=ROOT, env=env)
    deadline = time.time() + 40
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"서버가 바로 종료됨(exit {proc.returncode})")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/templates", timeout=2).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    stop_server(proc, port)
    raise SystemExit("서버가 40초 안에 /templates 200을 내지 않았다")


def stop_server(proc: subprocess.Popen, port: int) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    deadline = time.time() + 10
    while time.time() < deadline and not _port_free(port):
        time.sleep(0.2)


def _norm(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def shoot(base: str, out: Path) -> dict:
    from playwright.sync_api import sync_playwright

    catalog = json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed: list[str] = []
    requests: list[str] = []
    res: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="ko-KR")
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}"))

        # 1 첫 화면: 범위 안내 + 선택기 + 예시
        page.goto(base + "/", wait_until="networkidle")
        page.wait_for_selector('body[data-view="input"][data-ready="1"]')
        page.wait_for_function(f"document.querySelectorAll('#tplList .tp').length === {len(catalog['templates'])}")
        page.wait_for_function("document.getElementById('hdrState').textContent !== '서버 확인 중'")
        page.evaluate("document.fonts.ready.then(() => true)")
        res["scope_text"] = page.inner_text("#scope")
        res["scope_visible"] = page.is_visible("#scope")
        res["templates_shown"] = page.eval_on_selector_all("#tplList .tp", "els => els.map(e => e.innerText.replace(/\\s+/g, ' ').trim())")
        res["examples_shown"] = page.eval_on_selector_all("#exList .exl", "els => els.map(e => e.innerText.replace(/\\s+/g, ' ').trim())")
        res["fitbox_hidden_initially"] = page.eval_on_selector("#fitBox", "e => e.hidden")
        page.screenshot(path=str(out / f"{PREFIX}_input.png"))

        # 2 템플릿 선택 → 입력칸에 골격
        first = catalog["templates"][0]
        page.fill("#ta", "사용자가 먼저 쓴 메모")
        page.click(f'#tplList .tp[data-tpl="{first["id"]}"]')
        want = _norm(DATA / first["file"])
        page.wait_for_function("t => document.getElementById('ta') && document.getElementById('ta').value === t", arg=want)
        res["template_fills_textarea"] = page.input_value("#ta") == want
        res["template_selected"] = page.get_attribute(f'#tplList .tp[data-tpl="{first["id"]}"]', "aria-pressed")
        res["template_meta"] = page.inner_text("#tplMeta")
        res["start_enabled_after_template"] = page.is_enabled("#btnStart")
        page.screenshot(path=str(out / f"{PREFIX}_template.png"))
        page.click("#tplMeta .undo")
        page.wait_for_function("document.getElementById('ta').value === '사용자가 먼저 쓴 메모'")
        res["undo_restores_user_text"] = True

        # 모든 템플릿이 각자 골격을 채우는지
        filled = {}
        for t in catalog["templates"]:
            page.click(f'#tplList .tp[data-tpl="{t["id"]}"]')
            w = _norm(DATA / t["file"])
            page.wait_for_function("t => document.getElementById('ta').value === t", arg=w)
            filled[t["id"]] = True
        res["all_templates_fill"] = filled

        # 3 예시 불러오기 → 데모 계획서 원문
        ex_ok = {}
        for e in catalog["examples"]:
            page.click(f'#exList .exl[data-ex="{e["id"]}"]')
            w = _norm(ROOT / e["path"])
            page.wait_for_function("t => document.getElementById('ta').value === t", arg=w)
            ex_ok[e["id"]] = page.get_attribute(f'#tplList .tp[data-tpl="{e["template_id"]}"]', "aria-pressed") == "true"
        res["examples_fill_and_select_template"] = ex_ok
        page.click(f'#exList .exl[data-ex="{catalog["examples"][1]["id"]}"]')
        page.wait_for_function("t => document.getElementById('ta').value === t", arg=_norm(ROOT / catalog["examples"][1]["path"]))
        res["example_meta"] = page.inner_text("#tplMeta")
        page.screenshot(path=str(out / f"{PREFIX}_example.png"))

        # 4 적합성 판정 자리: mock 판정 주입(연결 전 자리 확인용, 화면에 'mock provider'로 표기)
        page.fill("#ta", _norm(PLANS / "negative_recipe.md"))
        page.evaluate("""() => window.NeumannInput.showFitness({fit: false, generator: 'mock', field: '해당 없음', language: 'ko',
            reasons: ['[mock] 연구 질문·방법·데이터·평가 요소가 없다', '[mock] 조리법 문서로 보인다']})""")
        page.wait_for_selector("#fitBox:not([hidden])")
        page.evaluate("document.getElementById('fitBox').scrollIntoView({block: 'center'})")
        res["fitbox_text"] = page.inner_text("#fitBox")
        page.screenshot(path=str(out / f"{PREFIX}_fitness.png"))
        page.evaluate("window.NeumannInput.clearFitness()")
        res["fitbox_hidden_after_clear"] = page.eval_on_selector("#fitBox", "e => e.hidden")
        main_console_errors = list(console_errors)

        # 5 라우터가 안 붙은 서버(404): 목록을 숨기지 않고 사유 표시, 범위 안내는 그대로
        page.route("**/templates", lambda route: route.fulfill(status=404, content_type="application/json",
                                                               body='{"detail":"Not Found"}'))
        page.goto(base + "/", wait_until="networkidle")
        page.wait_for_selector("#tplErr")
        res["no_router_error_text"] = page.inner_text("#tplErr")
        res["no_router_scope_text"] = page.inner_text("#scope")
        page.screenshot(path=str(out / f"{PREFIX}_no_router.png"))
        page.unroute("**/templates")
        browser.close()

    external = [u for u in requests if urlparse(u).scheme not in {"data", "blob", "about"}
                and urlparse(u).hostname not in LOCAL_HOSTS]
    res.update({
        "console_errors": main_console_errors,
        "console_errors_in_404_scenario": console_errors[len(main_console_errors):],
        "page_errors": page_errors,
        "failed_requests": failed,
        "requests_total": len(requests),
        "request_paths": sorted({urlparse(u).path for u in requests}),
        "external_requests": external,
    })
    return res


def check(res: dict) -> list[str]:
    catalog = json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))
    problems = []
    if SCOPE not in res["scope_text"] or not res["scope_visible"]:
        problems.append("범위 안내가 안 보인다")
    if len(res["templates_shown"]) != len(catalog["templates"]):
        problems.append("템플릿 버튼 수가 다르다")
    if len(res["examples_shown"]) != 3:
        problems.append("예시 버튼이 3개가 아니다")
    if not res["template_fills_textarea"] or res["template_selected"] != "true":
        problems.append("템플릿 선택이 입력칸을 채우지 않는다")
    if not all(res["examples_fill_and_select_template"].values()):
        problems.append("예시가 연결 템플릿을 선택하지 않는다")
    if "부적합" not in res["fitbox_text"] or "mock" not in res["fitbox_text"]:
        problems.append("적합성 판정 자리가 부적합 사유를 보이지 않는다")
    if not res["fitbox_hidden_initially"] or not res["fitbox_hidden_after_clear"]:
        problems.append("적합성 판정 자리가 비었는데 보인다")
    if "404" not in res["no_router_error_text"] or SCOPE not in res["no_router_scope_text"]:
        problems.append("라우터 없을 때 사유 표시가 없다")
    for k in ("console_errors", "page_errors", "failed_requests", "external_requests"):
        if res[k]:
            problems.append(f"{k}: {res[k]}")
    return problems


def run(port: int = DEFAULT_PORT, out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    proc = start_server(port)
    try:
        return shoot(f"http://127.0.0.1:{port}", out)
    finally:
        stop_server(proc, port)


def test_templates_ui_playwright() -> None:
    res = run()
    assert check(res) == [], json.dumps(res, ensure_ascii=False, indent=1)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    res = run(a.port, a.out)
    problems = check(res)
    print(json.dumps({**res, "problems": problems}, ensure_ascii=False, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
