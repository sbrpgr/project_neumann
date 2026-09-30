"""E4-L1f 화면 파일 업로드 Playwright 검사(1440×900, mock 서버).

    NEUMANN_UI_TESTS=1 python -m pytest tests/e4/test_webui_upload_ui.py -q -s
    python tests/e4/test_webui_upload_ui.py [--port 8131] [--out docs/reports]

- 기본 pytest(verify)에서는 건너뛴다(브라우저·서버 필요). ``NEUMANN_UI_TESTS=1``일 때만 돈다.
- 서버는 하위 프로세스로 ``neumann.api.main:app``을 띄운다. **``NEUMANN_LLM_PROVIDER=mock``을 강제**하고
  ``NEUMANN_LIVE_TESTS``는 지운다(사용자 환경 변수가 openai여도 실제 호출 없음). 업로드 경로는 LLM을 부르지 않는다.
  끝나면(실패해도) 종료한다. 8010(대표 점검)·8020(라이브 점검) 포트는 쓰지 않는다.
- 흐름: ① docx 업로드 → 본문 반영(스크린샷 ``E4-L1f_upload.png``) ② 빈 쪽 있는 pdf → 쪽수·경고
  ③ hwp → 서버 415 문구 그대로 ④ 파일명 ``<img onerror>`` → 글자로만 보임
  ⑤ 올리는 중 "읽는 중…"·두 번째 파일 무시(요청 1건) ⑥ 네트워크 실패 → "서버에 연결하지 못함"
  ⑦ 정적 판(404) → md는 브라우저 읽기, docx는 라이브 서버 안내.
- 콘솔 오류는 둘로 나눈다: 브라우저가 4xx·차단 응답마다 찍는 "Failed to load resource" 줄(의도한 415·404·차단)과
  그 밖의 오류(스크립트 오류 등). 뒤의 것과 페이지 오류·외부 요청이 하나라도 있으면 실패.
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
OUT = ROOT / "docs" / "reports"
PREFIX = "E4-L1f"
DEFAULT_PORT = 8131
FORBIDDEN_PORTS = {8010, 8020}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
NET_LOG = "Failed to load resource"

pytestmark = pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="NEUMANN_UI_TESTS=1일 때만(브라우저·서버 필요)")


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def start_server(port: int) -> subprocess.Popen:
    import httpx

    if port in FORBIDDEN_PORTS:
        raise SystemExit(f"{port}는 점검 서버 포트다. 다른 포트를 써라")
    if not _port_free(port):
        raise SystemExit(f"포트 {port}가 이미 쓰이고 있다")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]))
    env["NEUMANN_LLM_PROVIDER"] = "mock"  # 실제 OpenAI 호출 금지(대표 상시 규칙)
    env.pop("NEUMANN_LIVE_TESTS", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "neumann.api.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        cwd=ROOT, env=env)
    deadline = time.time() + 40
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"서버가 바로 종료됨(exit {proc.returncode})")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    stop_server(proc, port)
    raise SystemExit("서버가 40초 안에 /health 200을 내지 않았다")


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


def _samples() -> dict[str, dict]:
    from tests.e4.test_upload import HWP5_BYTES, make_pdf
    from tests.e4.test_webui_upload import PLAN_LINES, make_docx

    md = "# 연구계획서 — 정적 판 확인\n\n1. 목표: 브라우저에서 읽는다.\n".encode()
    return {
        "docx": {"name": "계획서_전해액.docx", "mimeType": DOCX_MIME, "buffer": make_docx()},
        "pdf": {"name": "계획서_전해액.pdf", "mimeType": "application/pdf", "buffer": make_pdf([PLAN_LINES, []])},
        "hwp": {"name": "계획서.hwp", "mimeType": "application/x-hwp", "buffer": HWP5_BYTES},
        "xss": {"name": "<img src=x onerror=window.__xss=1>.txt", "mimeType": "text/plain", "buffer": "본문 한 줄".encode()},
        "md": {"name": "계획서_정적.md", "mimeType": "text/markdown", "buffer": md},
    }


def _card(page) -> dict:
    return page.evaluate("""() => {
      const q = s => document.querySelector(s);
      return {
        fn: q('.file .fn') ? q('.file .fn').textContent : null,
        fm: q('.file .fm .mono') ? q('.file .fm .mono').textContent : null,
        lines_tag: q('.file .fm .tag') ? q('.file .fm .tag').textContent : null,
        prev: Array.from(document.querySelectorAll('.prev .bd .l')).slice(0, 5).map(e => e.textContent),
        warn: Array.from(document.querySelectorAll('#fileWarn li')).map(e => e.textContent),
        err: q('#inErr') ? q('#inErr').textContent : null,
        start_enabled: !q('#btnStart').disabled,
      };
    }""")


def _upload(page, sample: dict) -> None:
    page.set_input_files("#fileIn", files=[sample])


def _wait_name(page, name: str) -> None:
    page.wait_for_function("n => { const e = document.querySelector('.file .fn'); return e && e.textContent === n; }", arg=name)


def shoot(base: str, out: Path) -> dict:
    from playwright.sync_api import sync_playwright

    from neumann.api.upload import HWP_MESSAGE

    sm = _samples()
    console: list[dict] = []
    page_errors: list[str] = []
    requests: list[str] = []
    res: dict = {"phases": {}}

    def phase(name: str, fn) -> None:
        c0, e0 = len(console), len(page_errors)
        res["phases"][name] = fn()
        res["phases"][name]["_console"] = [m["text"] for m in console[c0:]]
        res["phases"][name]["_page_errors"] = page_errors[e0:]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="ko-KR")
        page = ctx.new_page()
        page.on("console", lambda m: console.append({"type": m.type, "text": m.text}) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))

        def open_file_tab() -> None:
            page.goto(base + "/", wait_until="networkidle")
            page.wait_for_selector('body[data-view="input"][data-ready="1"]')
            page.wait_for_function("document.getElementById('hdrState').textContent !== '서버 확인 중'")
            page.click('[data-mode="file"]')
            page.wait_for_selector("#drop")
            page.evaluate("document.fonts.ready.then(() => true)")

        def uploads() -> int:
            return sum(1 for u in requests if urlparse(u).path == "/upload/plan")

        open_file_tab()
        res["drop_hint"] = page.inner_text("#drop .sm")
        res["accept"] = page.get_attribute("#fileIn", "accept")

        # ① docx → 본문 반영
        def docx() -> dict:
            _upload(page, sm["docx"])
            _wait_name(page, sm["docx"]["name"])
            page.evaluate("document.getElementById('drop').scrollIntoView({block: 'start'})")
            page.screenshot(path=str(out / f"{PREFIX}_upload.png"))
            return _card(page)
        phase("docx", docx)

        # ② pdf(2쪽 중 1쪽 빈 쪽) → 쪽수·경고
        def pdf() -> dict:
            _upload(page, sm["pdf"])
            _wait_name(page, sm["pdf"]["name"])
            page.wait_for_selector("#fileWarn li")
            page.evaluate("document.getElementById('drop').scrollIntoView({block: 'start'})")
            page.screenshot(path=str(out / f"{PREFIX}_pdf_warn.png"))
            return _card(page)
        phase("pdf", pdf)

        # ③ hwp → 서버 415 문구 그대로
        def hwp() -> dict:
            _upload(page, sm["hwp"])
            page.wait_for_selector("#inErr")
            page.evaluate("document.getElementById('drop').scrollIntoView({block: 'start'})")
            page.screenshot(path=str(out / f"{PREFIX}_hwp.png"))
            return {**_card(page), "server_message": HWP_MESSAGE}
        phase("hwp", hwp)

        # ④ 파일명에 HTML → 글자로만
        def xss() -> dict:
            _upload(page, sm["xss"])
            _wait_name(page, sm["xss"]["name"])
            return {**_card(page), "xss_ran": page.evaluate("window.__xss === 1"),
                    "img_in_card": page.evaluate("!!document.querySelector('.file img, #drop img')")}
        phase("xss", xss)

        # ⑤ 올리는 중: "읽는 중…", 입력 비활성, 두 번째 파일(드롭) 무시 → 요청 1건
        def busy() -> dict:
            held: list = []
            page.route("**/upload/plan", lambda route: held.append(route))
            n0 = uploads()
            _upload(page, sm["docx"])
            page.wait_for_selector('#drop[aria-busy="true"]')
            page.evaluate("document.getElementById('drop').scrollIntoView({block: 'start'})")
            page.screenshot(path=str(out / f"{PREFIX}_busy.png"))
            got = {"drop_title": page.inner_text("#drop b"), "drop_sub": page.inner_text("#drop .sm"),
                   "input_disabled": page.is_disabled("#fileIn")}
            page.evaluate("""() => { const dt = new DataTransfer();
              dt.items.add(new File(['두 번째'], 'second.md', { type: 'text/markdown' }));
              document.getElementById('drop').dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); }""")
            page.wait_for_timeout(300)
            got["requests_while_busy"] = uploads() - n0
            got["held"] = len(held)
            held[0].continue_()
            _wait_name(page, sm["docx"]["name"])
            page.unroute("**/upload/plan")
            got["requests_total"] = uploads() - n0
            got["busy_after"] = page.get_attribute("#drop", "aria-busy")
            return {**got, **_card(page)}
        phase("busy", busy)

        # ⑥ 네트워크 실패(요청 차단) → md는 브라우저 읽기 + "서버에 연결하지 못함", pdf는 안내
        def offline() -> dict:
            page.route("**/upload/plan", lambda route: route.abort())
            _upload(page, sm["md"])
            _wait_name(page, sm["md"]["name"])
            md = _card(page)
            _upload(page, sm["pdf"])
            page.wait_for_selector("#inErr")
            pdf_err = page.inner_text("#inErr")
            page.unroute("**/upload/plan")
            return {"md": md, "pdf_err": pdf_err}
        phase("offline", offline)

        # ⑦ 정적 판(업로드 API 404) → docx 안내, md 브라우저 읽기, 이후 요청 안 함
        def static() -> dict:
            page.route("**/upload/plan", lambda route: route.fulfill(status=404, content_type="application/json",
                                                                     body='{"detail":"Not Found"}'))
            open_file_tab()
            n0 = uploads()
            _upload(page, sm["docx"])
            page.wait_for_selector("#inErr")
            docx_err = page.inner_text("#inErr")
            page.evaluate("document.getElementById('drop').scrollIntoView({block: 'start'})")
            page.screenshot(path=str(out / f"{PREFIX}_static.png"))
            _upload(page, sm["md"])
            _wait_name(page, sm["md"]["name"])
            page.unroute("**/upload/plan")
            return {"docx_err": docx_err, "md": _card(page), "requests": uploads() - n0}
        phase("static", static)
        browser.close()

    external = [u for u in requests if urlparse(u).scheme not in {"data", "blob", "about"}
                and urlparse(u).hostname not in LOCAL_HOSTS]
    all_console = [m["text"] for m in console]
    res.update({
        "console_errors_total": len(all_console),
        "console_network_log": [t for t in all_console if t.startswith(NET_LOG)],
        "console_other_errors": [t for t in all_console if not t.startswith(NET_LOG)],
        "page_errors": page_errors,
        "external_requests": external,
        "request_paths": sorted({urlparse(u).path for u in requests}),
    })
    return res


def check(res: dict) -> list[str]:
    from neumann.api.upload import HWP_MESSAGE

    from tests.e4.test_webui_upload import DROP_HINT, LIVE_ONLY, PLAN_LINES

    ph, problems = res["phases"], []

    def need(ok: bool, what: str) -> None:
        if not ok:
            problems.append(what)

    need(res["drop_hint"] == DROP_HINT, "드롭존 안내 문구")
    need(all(x in res["accept"].split(",") for x in (".pdf", ".docx", "application/pdf", DOCX_MIME)), "accept")
    d = ph["docx"]
    need(d["prev"][:3] == PLAN_LINES and d["fm"].startswith("DOCX · ") and d["start_enabled"] and not d["err"], "docx 본문 반영")
    p = ph["pdf"]
    need(p["prev"][:3] == PLAN_LINES and p["fm"].startswith("PDF · ") and "2쪽" in p["fm"], "pdf 본문·쪽수")
    need(any("텍스트가 없는 쪽" in w for w in p["warn"]), "pdf 경고 표시")
    need(ph["hwp"]["err"] == HWP_MESSAGE, "hwp 415 서버 문구")
    x = ph["xss"]
    need(x["fn"] == "<img src=x onerror=window.__xss=1>.txt" and not x["xss_ran"] and not x["img_in_card"], "파일명 이스케이프")
    b = ph["busy"]
    need(b["drop_title"] == "읽는 중…" and b["input_disabled"], "읽는 중 표시·입력 비활성")
    need(b["requests_while_busy"] == 1 and b["requests_total"] == 1 and b["held"] == 1, "중복 제출 차단")
    need(b["fn"] == "계획서_전해액.docx" and b["busy_after"] == "false", "올린 뒤 본문 반영·busy 해제")
    o = ph["offline"]
    need(any(w.startswith("서버에 연결하지 못함") for w in o["md"]["warn"]) and "브라우저 읽기" in o["md"]["fm"], "네트워크 실패 md 폴백 표시")
    need(o["pdf_err"] == "서버에 연결하지 못함 — " + LIVE_ONLY, "네트워크 실패 pdf 안내")
    s = ph["static"]
    need(s["docx_err"].endswith(LIVE_ONLY) and s["docx_err"].startswith("정적 판"), "정적 판 docx 안내")
    need(any(w.startswith("정적 판") for w in s["md"]["warn"]) and s["md"]["prev"][0] == "# 연구계획서 — 정적 판 확인", "정적 판 md 읽기")
    need(s["requests"] == 1, "정적 판 판단 뒤 추가 요청 없음")
    for k in ("console_other_errors", "page_errors", "external_requests"):
        need(not res[k], f"{k}: {res[k]}")
    main_flow = [t for n in ("docx", "pdf", "xss") for t in ph[n]["_console"]]
    need(not main_flow, f"본 흐름 콘솔 오류: {main_flow}")
    need(all("415" in t for t in ph["hwp"]["_console"]), "hwp 단계 콘솔은 415 응답 기록뿐이어야 한다")
    return problems


def run(port: int = DEFAULT_PORT, out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    proc = start_server(port)
    try:
        return shoot(f"http://127.0.0.1:{port}", out)
    finally:
        stop_server(proc, port)


def test_webui_upload_playwright() -> None:
    res = run()
    assert check(res) == [], json.dumps(res, ensure_ascii=False, indent=1)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    for p in (ROOT / "src", ROOT):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
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
