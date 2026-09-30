"""E4-L2f 화면 "IV 내보내기": 정적·서버 검사(항상) + Playwright 1440×900(``NEUMANN_UI_TESTS=1``일 때만).

원결과는 화면 응답(``build_ui_view`` → jobs 화면 결과·``/premortem/view``)의 ``result``·``result_sig``(서버 서명)로 온다.
내보내기 때 재분석하지 않는다. 서명 확인·변조·재기동은 ``test_export_ui_sign.py``가 본다.

    python -m pytest tests/e4/test_export_ui.py -q                              # 정적 검사
    NEUMANN_UI_TESTS=1 NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4/test_export_ui.py -q -s
    python tests/e4/test_export_ui.py [--port 8149] [--out docs/reports]         # 직접

Playwright 흐름(서버는 하위 프로세스 uvicorn, 기본 8149번, ``NEUMANN_LLM_PROVIDER=mock``·OpenAI 키 없이 띄우고 끝나면 종료.
8010·8020은 쓰지 않는다):
A. 첫 화면: 단계 IV 비활성·사유(분석 결과 없음) → 계획서 분석(mock, POST /premortem/jobs → GET 폴링) → 리포트에서 결정
   4건(뷰에 실린 결정·메모 1건 + 클릭 3건, 그중 하나는 한 바퀴 돌려 "보류"로 되돌림 → hold) → 단계 IV 누르면 내보내기
   섹션으로 → ZIP 내려받기(POST는 jobs·package 두 건, 재분석 0) → ZIP을 열어 9파일·decision_log.json·
   result_origin=server_signed 확인 → 스크린샷 ``docs/reports/E4-L2f_export.png`` 한 장 → 서버 오류(가로챈 422·429)의 문구가
   textContent로 보이는지(태그 안 만듦).
B. 샘플 결과: 버튼·단계 IV 비활성, 사유 "샘플".
C. 화면 응답에 원결과(result)가 없으면(옛 서버를 흉내 내 가로챔) 버튼 비활성·사유, 요청 없음.
콘솔 오류·페이지 오류·실패 요청·외부 도메인 요청이 있으면 실패(가로챈 4xx의 "Failed to load resource"만 뺀다).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

HTML = ROOT / "src" / "neumann" / "webui" / "index.html"
OUT = ROOT / "docs" / "reports"
PLAN = ROOT / "tests" / "fixtures" / "plans" / "plan.md"
SHOT = "E4-L2f_export.png"
DEFAULT_PORT = 8149
FORBIDDEN_PORTS = {8010, 8020}
VW, VH = 1440, 900
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
MEMO = "표본 크기 근거 보강 · 담당 a.kim@example.org"
XSS = '<img src=x onerror="window.__xss=1">서버 거절'
REPORT_READY = "document.body.dataset.view === 'report' && document.body.dataset.ready === '1'"


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


def _func(src: str, name: str) -> str:
    """index.html에서 함수 본문 하나(다음 최상위 함수 전까지)."""
    m = re.search(r"\n  function " + re.escape(name) + r"\(.*?(?=\n  function |\n  document\.addEventListener|\n  /\* -)", src, re.S)
    assert m, f"함수 {name} 없음"
    return m.group(0)


# ── 정적 검사(verify에서 돈다) ─────────────────────────────────────────────


def test_step_iv_not_placeholder():
    src = _src()
    assert "내보내기 · 준비 중" not in src
    assert "<span class=\"soon\">준비 중</span>" not in src
    steps = _func(src, "renderSteps")
    assert "expStepHtml(s)" in steps, "단계 IV가 내보내기 상태 함수로 그려져야 한다"
    step = _func(src, "expStepHtml")
    assert 'id="stpExport"' in step and "disabled" in step and "title=" in step


def test_disable_reasons_cover_no_result_and_sample():
    block = _func(_src(), "expBlock")
    assert "if (!D) return '분석 결과 없음'" in block
    assert "st.source === 'sample'" in block and "샘플" in block
    assert "result_status === 'error'" in block


def test_package_request_shape_matches_export_py():
    """화면이 보내는 결정 키·값이 export.py DecisionEntry·PackageRequest가 받는 형식인지."""
    from neumann.api.export import DECISION_LABELS, DecisionEntry, PackageRequest

    src = _src()
    do = _func(src, "doExport")
    assert "fetch('premortem/package'" in do
    body_keys = set(re.findall(r"JSON\.stringify\(\{ (result): raw, (result_sig): d\.result_sig \|\| null, (decisions): decisions \}\)", do)[0])
    assert body_keys <= set(PackageRequest.model_fields), body_keys

    dec = _func(src, "expDecisions")
    literal = re.search(r"var e = \{([^}]*)\}", dec).group(1)
    keys = set(re.findall(r"(\w+): ", literal)) | set(re.findall(r"e\.(\w+) = ", dec))
    assert keys == {"item_id", "decision", "note", "decided_at"}, keys
    assert keys <= set(DecisionEntry.model_fields)
    m = re.search(r"var EXP_DEC = (\{[^}]*\});", src)
    exp_dec = json.loads(m.group(1).replace("'", '"'))
    assert {DECISION_LABELS[v] for v in exp_dec.values()} == set(exp_dec) == {"채택", "보류", "기각"}
    # 결정 전(set === false) 항목은 싣지 않는다
    assert "it.set !== false" in _func(src, "expDecided")


def test_server_message_goes_through_text_content():
    src = _src()
    paint = _func(src, "expPaint")
    assert "m.textContent = e.msg" in paint and "innerHTML" not in paint
    msg = _func(src, "expServerMsg")
    assert "j.message" in msg and "j.detail" in msg
    html = _func(src, "expHtml")
    assert "esc(e.msg)" in html and "esc('내보낼 수 없음 · ' + why)" in html


def test_no_reanalysis_uses_view_result():
    src = _src()
    assert "fetch('premortem'," not in src, "내보내기는 재분석(POST /premortem)을 부르지 않는다"
    assert "var r = d && d.result;" in _func(src, "expInline")
    block = _func(src, "expBlock")
    assert "원결과가 없음" in block and "raw.plan_id !== D.plan_id" in block
    assert "var raw = expInline(d)" in _func(src, "doExport")


# ── 서버: 화면 응답에 실리는 원결과(view.py) ────────────────────────────────


def _fixture_result() -> dict:
    return json.loads((ROOT / "tests" / "fixtures" / "premortem_result.json").read_text(encoding="utf-8"))


def test_view_carries_contract_result_that_packages():
    from neumann.api.export import FILE_NAMES, build_package
    from neumann.api.view import build_ui_view, validate_ui_view
    from neumann.models import PremortemResult

    res = _fixture_result()
    view = build_ui_view(res, records=None)
    assert validate_ui_view(view) == [], "result를 붙여도 ui_view 계약을 지킨다"
    raw = view["result"]
    assert view["_status"]["export"] == {"result": True, "signed": True, "reason": None, "dropped_keys": []}
    assert isinstance(view["result_sig"], str) and view["result_sig"].startswith("v1.")
    assert raw == PremortemResult.model_validate(res).model_dump(mode="json")  # fixture는 뺄 키·가릴 진단 문구 없음
    assert raw["plan_id"] == view["plan_id"] and raw["session_id"] == view["session_id"]
    # 화면과 같은 값: 계획서 줄(빈 줄은 화면이 뺀다) 번호·문구가 뷰와 같다
    assert [(ln["no"], ln["text"]) for ln in raw["plan"]["lines"] if ln["text"].strip()] ==         [(ln["n"], ln["t"]) for ln in view["plan"]["lines"]]
    json.dumps(view, ensure_ascii=False, allow_nan=False)
    ids = [it["id"] for it in view["checklist"]]
    decisions = [{"item_id": ids[0], "decision": "adopt", "note": "메모 a@b.org"}] if ids else []
    with zipfile.ZipFile(io.BytesIO(build_package(raw, decisions=decisions))) as zf:
        assert zf.namelist() == list(FILE_NAMES)
        log = json.loads(zf.read("decision_log.json"))
    assert len(log["decisions"]) == len(decisions)
    if decisions:
        assert "a@b.org" not in log["decisions"][0]["note"]


def test_view_result_withheld_for_sample_error_and_bad_input():
    from neumann.api.view import build_ui_view

    res = _fixture_result()
    sample = build_ui_view(res, sample=True, pipeline_state="unavailable")
    assert sample["result"] is None and "샘플" in sample["_status"]["export"]["reason"]
    err = build_ui_view(None, pipeline_state="error", error="파이프라인 실행 실패: X")
    assert err["result"] is None and err["_status"]["export"]["reason"] == "분석 결과 없음"
    bad = dict(res, api_key="sk-should-not-pass")  # 계약 밖 필드(extra=forbid) → 싣지 않는다
    v = build_ui_view(bad, records=None)
    assert v["result"] is None and "PremortemResult" in v["_status"]["export"]["reason"]
    assert "sk-should-not-pass" not in json.dumps(v, ensure_ascii=False)


def test_service_ports_refused():
    assert DEFAULT_PORT == 8149 and DEFAULT_PORT not in FORBIDDEN_PORTS
    for port in sorted(FORBIDDEN_PORTS):
        with pytest.raises(SystemExit):
            start_server(port)


# ── Playwright ────────────────────────────────────────────────────────────


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def start_server(port: int) -> subprocess.Popen:
    import httpx

    if port in FORBIDDEN_PORTS:
        raise SystemExit(f"{port}은 쓰지 않는다(8010·8020 금지)")
    if not _port_free(port):
        raise SystemExit(f"포트 {port}가 이미 쓰이고 있다")
    env = {k: v for k, v in os.environ.items()
           if k not in {"OPENAI_API_KEY", "NEUMANN_LIVE_LLM_OK", "NEUMANN_LIVE_TESTS", "NEUMANN_ALLOW_ASTRA"}}
    env.update(PYTHONIOENCODING="utf-8", NEUMANN_LLM_PROVIDER="mock",
               PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]))
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "neumann.api.main:app", "--host", "127.0.0.1",
                             "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"서버가 바로 종료됨(exit {proc.returncode})")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    stop_server(proc)
    raise SystemExit("서버가 60초 안에 /health 200을 내지 않았다")


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


class Watch:
    """콘솔 오류·페이지 오류·실패 요청·외부 요청 수집."""

    def __init__(self, page, base: str) -> None:
        self.errors: list[str] = []
        self.posts: list[str] = []
        self.allow_4xx = False
        host = urlparse(base).hostname
        page.on("console", self._console)
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: self.errors.append(f"requestfailed: {r.url}"))
        page.on("request", lambda r: self.posts.append(urlparse(r.url).path) if r.method == "POST" else None)
        page.on("request", lambda r: None if (urlparse(r.url).hostname in LOCAL_HOSTS | {host}
                                               or r.url.startswith(("blob:", "data:")))
                else self.errors.append(f"external: {r.url}"))

    def _console(self, msg) -> None:
        if msg.type != "error":
            return
        if self.allow_4xx and "Failed to load resource" in msg.text:
            return
        self.errors.append(f"console: {msg.text}")


def _analyze(page, base: str, plan_text: str) -> None:
    page.goto(base + "/")
    page.wait_for_selector('body[data-view="input"][data-ready="1"]')
    page.fill("#ta", plan_text)
    page.click("#btnStart")
    page.wait_for_function(REPORT_READY, timeout=300_000)
    page.wait_for_selector("#s-export")


JOBS_GLOB = "**/premortem/jobs/**"   # GET /premortem/jobs/{id} 폴링(끝나면 result = 화면 뷰)
FETCH_TIMEOUT_MS = 180_000            # F7: 부하 중에도 가로챈 요청이 먼저 끊기지 않게


def _on_done_view(edit):
    """jobs 폴링 응답이 done이면 그 안의 화면 뷰(result)를 ``edit(view)``로 바꿔 돌려주는 route 처리기."""

    def handler(route, _req) -> None:
        resp = route.fetch(timeout=FETCH_TIMEOUT_MS)
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001 - JSON이 아니면 그대로
            route.fulfill(response=resp)
            return
        if isinstance(body, dict) and body.get("status") == "done" and isinstance(body.get("result"), dict):
            edit(body["result"])
            route.fulfill(response=resp, json=body)
        else:
            route.fulfill(response=resp)

    return handler


def _memo_on_first(view: dict) -> None:
    """뷰의 첫 체크리스트 항목에 결과에 실린 결정·메모가 있는 것처럼(E3 checklist decision·note) 바꾼다."""
    if view.get("checklist"):
        view["checklist"][0].update({"s": "채택", "set": True, "m": MEMO})


def run_ui(base: str, out: Path, tmp: Path) -> dict:
    from playwright.sync_api import sync_playwright

    from neumann.api.export import FILE_NAMES

    plan_text = PLAN.read_text(encoding="utf-8")
    info: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport={"width": VW, "height": VH}, accept_downloads=True)

            # ── A. 정상 흐름 ──
            page = ctx.new_page()
            w = Watch(page, base)
            page.goto(base + "/")
            page.wait_for_selector('body[data-view="input"][data-ready="1"]')
            stp = page.locator("#stpExport")
            assert stp.is_disabled(), "결과가 없을 때 단계 IV는 비활성이어야 한다"
            assert "분석 결과 없음" in (stp.get_attribute("title") or "")
            info["step_iv_before"] = stp.get_attribute("title")

            page.route(JOBS_GLOB, _on_done_view(_memo_on_first))
            _analyze(page, base, plan_text)
            page.unroute(JOBS_GLOB)
            view_plan_id = page.locator("#s-trace .mono").first.inner_text().split(" · ")[-1].strip()
            assert page.locator("#stpExport").is_enabled(), "리포트에서 단계 IV가 켜져야 한다"
            assert page.locator("#btnExport").is_enabled()
            n_items = page.locator("#s-check .dec").count()
            assert n_items >= 4, n_items

            page.click('#s-check .dec[data-i="1"]')          # 보류 → 기각
            page.click('#s-check .dec[data-i="2"]')          # 보류 → 기각
            page.click('#s-check .dec[data-i="2"]')          # 기각 → 채택
            for _ in range(3):                               # 보류 → 기각 → 채택 → 보류(명시적으로 되돌림 → hold, PM 결정 ③)
                page.click('#s-check .dec[data-i="3"]')
            # 클릭마다 집계는 다음 틱에 다시 그린다 — 중간 상태가 아니라 최종 값을 기다린다
            page.wait_for_function("document.getElementById('expDec').textContent.indexOf('결정 4건 · 채택 2 · 보류 1 · 기각 1') >= 0")
            info["exp_dec"] = page.locator("#expDec").inner_text()
            assert [page.locator(f'#s-check .dec[data-i="{i}"]').text_content() for i in range(4)] == ["채택", "기각", "채택", "보류"]
            assert f"결정 전 {n_items - 4}건은 싣지 않음" in info["exp_dec"], info["exp_dec"]

            page.evaluate("window.scrollTo(0, 0)")
            page.click("#stpExport")
            page.wait_for_timeout(300)
            top = page.evaluate("document.getElementById('s-export').getBoundingClientRect().top")
            assert 0 <= top < VH / 2, f"단계 IV를 누르면 내보내기 섹션으로 가야 한다(top={top})"

            with page.expect_download(timeout=120_000) as dl_info:
                page.click("#btnExport")
            dl = dl_info.value
            zpath = tmp / dl.suggested_filename
            dl.save_as(zpath)
            page.wait_for_function("document.getElementById('expMsg').textContent.indexOf('내려받음') >= 0")
            info["download"] = dl.suggested_filename
            info["posts"] = list(w.posts)
            assert w.posts == ["/premortem/jobs", "/premortem/package"], w.posts  # 재분석(POST /premortem) 없음
            info["exp_msg"] = page.locator("#expMsg").inner_text()
            assert "서버 서명 확인됨" in info["exp_msg"], info["exp_msg"]
            info["exp_src"] = page.locator("#expSrc").inner_text()
            assert re.fullmatch(r"neumann_package_[0-9A-Za-z_-]+\.zip", dl.suggested_filename), dl.suggested_filename

            page.locator("#s-export").scroll_into_view_if_needed()
            page.evaluate("document.getElementById('s-export').scrollIntoView({block: 'center'})")
            page.wait_for_timeout(200)
            out.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out / SHOT))
            info["screenshot"] = str((out / SHOT).relative_to(ROOT)).replace("\\", "/")

            with zipfile.ZipFile(zpath) as zf:
                names = zf.namelist()
                files = {n: zf.read(n) for n in names}
            assert names == list(FILE_NAMES), names
            log = json.loads(files["decision_log.json"])
            manifest = json.loads(files["manifest.json"])
            report = files["neumann_report.md"].decode("utf-8")
            info["zip_files"] = names
            info["decision_log"] = log["decisions"]
            assert log["plan_id"] == view_plan_id, (log["plan_id"], view_plan_id)
            by_id = {d["item_id"]: d for d in log["decisions"]}
            assert set(by_id) == {"C1", "C2", "C3", "C4"}, by_id
            assert by_id["C1"]["decision"] == "adopt" and by_id["C1"]["decided_at"] is None
            assert by_id["C1"]["note"].startswith("표본 크기 근거 보강") and "a.kim@example.org" not in by_id["C1"]["note"]
            assert "[EMAIL]" in by_id["C1"]["note"]
            assert by_id["C2"]["decision"] == "reject" and by_id["C2"]["decided_at"]
            assert by_id["C3"]["decision"] == "adopt" and by_id["C3"]["decided_at"]
            assert by_id["C4"]["decision"] == "hold" and by_id["C4"]["decided_at"]  # 되돌린 보류는 시각과 함께 기록
            assert all(d["card_id"] is None for d in log["decisions"])
            assert manifest["counts"]["decisions"] == 4
            assert manifest["result_origin"] == "server_signed", manifest["result_origin"]
            info["result_origin"] = manifest["result_origin"]
            assert not files["README.md"].decode("utf-8").startswith("**주의")
            assert "## 결정 로그" in report and "행동 `C2`: 기각" in report and "행동 `C3`: 채택" in report
            assert "a.kim@example.org" not in "".join(f.decode("utf-8", "replace") for f in files.values())
            assert not w.errors, w.errors

            # 서버 오류 문구: textContent로(태그를 만들지 않는다)
            w.allow_4xx = True
            page.route("**/premortem/package", lambda r, _q: r.fulfill(
                status=422, content_type="application/json", body=json.dumps({"detail": XSS}, ensure_ascii=False)))
            page.click("#btnExport")
            page.wait_for_function("document.getElementById('expMsg').textContent.indexOf('내보내기 실패') >= 0")
            msg = page.locator("#expMsg")
            assert msg.text_content() == "내보내기 실패 · " + XSS, msg.text_content()
            assert page.locator("#expMsg img").count() == 0 and page.evaluate("window.__xss") is None
            assert "err" in (msg.get_attribute("class") or "")
            page.unroute("**/premortem/package")
            page.route("**/premortem/package", lambda r, _q: r.fulfill(
                status=429, content_type="application/json",
                body=json.dumps({"message": "요청이 많습니다. 잠시 뒤 다시 시도하세요."}, ensure_ascii=False)))
            page.click("#btnExport")
            page.wait_for_function("document.getElementById('expMsg').textContent.indexOf('요청이 많습니다') >= 0")
            info["error_msgs"] = [msg.text_content()]
            assert page.locator("#btnExport").is_enabled(), "실패 뒤 다시 누를 수 있어야 한다"
            page.unroute("**/premortem/package")
            assert not w.errors, w.errors
            page.close()

            # ── B. 샘플 결과: 비활성·사유 ──
            page = ctx.new_page()
            w = Watch(page, base)

            def sample_view(view: dict) -> None:
                view["_status"].update({"source": "sample", "label": "분석 파이프라인 미연결(샘플 데이터)"})

            page.route(JOBS_GLOB, _on_done_view(sample_view))
            _analyze(page, base, plan_text)
            assert page.locator("#btnExport").is_disabled()
            assert "샘플" in page.locator("#expWhy").inner_text()
            assert page.locator("#stpExport").is_disabled()
            assert "샘플" in (page.locator("#stpExport").get_attribute("title") or "")
            info["sample_why"] = page.locator("#expWhy").inner_text()
            assert not w.errors, w.errors
            page.close()

            # ── C. 화면 응답에 원결과가 없으면(옛 서버) 비활성·사유, 요청 없음 ──
            page = ctx.new_page()
            w = Watch(page, base)

            def no_result_view(view: dict) -> None:
                view.pop("result", None)
                view.pop("result_sig", None)
                view["_status"].pop("export", None)

            page.route(JOBS_GLOB, _on_done_view(no_result_view))
            _analyze(page, base, plan_text)
            assert page.locator("#btnExport").is_disabled()
            info["no_result_why"] = page.locator("#expWhy").inner_text()
            assert "원결과가 없음" in info["no_result_why"], info["no_result_why"]
            assert "원결과" in (page.locator("#stpExport").get_attribute("title") or "")
            page.locator("#btnExport").click(force=True)
            page.wait_for_timeout(300)
            assert w.posts == ["/premortem/jobs"], w.posts
            assert not w.errors, w.errors
            page.close()
        finally:
            browser.close()
    return info


def run(port: int, out: Path) -> dict:
    proc = start_server(port)
    try:
        with tempfile.TemporaryDirectory() as td:
            return run_ui(f"http://127.0.0.1:{port}", out, Path(td))
    finally:
        stop_server(proc)


@pytest.mark.skipif(os.getenv("NEUMANN_UI_TESTS") != "1", reason="NEUMANN_UI_TESTS=1일 때만(브라우저·서버 필요)")
def test_export_ui_playwright():
    info = run(int(os.getenv("NEUMANN_UI_PORT", DEFAULT_PORT)), OUT)
    print(json.dumps(info, ensure_ascii=False, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    print(json.dumps(run(a.port, a.out), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
