"""E6-L3b 시연 녹화 스크립트 테스트. 네트워크 없이 돈다.

- 순수 함수: 헬스 분류(샘플 표시), 파일 이름, 출력 경로, webm 헤더 읽기(손으로 만든 EBML)
- 녹화 함수: 짧은 가짜 페이지(`set_content`)를 녹화해 webm이 생기는지
- 시연 시나리오 전체: 가짜 앱을 `context.route`로 띄워(외부 요청은 모두 abort) 단계·샘플 표시를 확인
Chromium을 띄울 수 없는 환경이면 브라우저 테스트만 건너뛴다.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("record_demo", ROOT / "scripts" / "record_demo.py")
rd = importlib.util.module_from_spec(_spec)
sys.modules["record_demo"] = rd
_spec.loader.exec_module(rd)

PLAN = ROOT / "tests" / "fixtures" / "plans" / "plan.md"


# ── 순수 함수 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("health", "mode"),
    [
        ({"pipeline": {"state": "connected"}}, "live"),
        ({"pipeline": {"state": "unavailable", "mode": "sample"}}, "sample"),
        ({"pipeline": {"state": "error", "reason": "x"}}, "sample"),
        ({"status": "ok"}, "sample"),
        (None, "sample"),
    ],
)
def test_classify_health_only_connected_is_live(health, mode):
    got, why = rd.classify_health(health)
    assert got == mode
    assert why


@pytest.mark.parametrize(
    ("status", "sample"),
    [
        ({"source": "sample"}, True),
        ({"source": "pipeline", "sample": True}, True),
        ({"source": "pipeline"}, False),
        ({"source": "pipeline", "sample": False}, False),
        ({}, False),
        (None, False),
    ],
)
def test_response_is_sample(status, sample):
    assert rd.response_is_sample(status) is sample


def test_basename_carries_mode():
    when = dt.datetime(2026, 9, 30, 18, 5, 7)
    assert rd.make_basename("sample", when) == "demo_20260930-180507_sample"
    assert rd.make_basename("live", when).endswith("_live")


def test_out_dir_data_prefix_goes_to_shared_data_dir(tmp_path):
    shared = tmp_path / "shared_data"
    env = {"NEUMANN_DATA_DIR": str(shared)}
    assert rd.resolve_out_dir("data/video/", env=env, cwd=tmp_path / "wt") == shared / "video"
    assert rd.resolve_out_dir("out/v", env=env, cwd=tmp_path / "wt") == tmp_path / "wt" / "out" / "v"
    assert rd.resolve_out_dir("data/video", env={}, cwd=tmp_path / "wt") == tmp_path / "wt" / "data" / "video"
    assert rd.resolve_out_dir(tmp_path / "abs", env=env) == tmp_path / "abs"


def _el(eid: int, payload: bytes) -> bytes:
    """EBML 요소 하나: id(표지 비트 포함 그대로) + 8바이트 길이 + 내용."""
    idb = eid.to_bytes((eid.bit_length() + 7) // 8, "big")
    return idb + bytes([0x01]) + len(payload).to_bytes(7, "big") + payload


def _webm(duration_ms: float | None, w: int, h: int, blocks: list[tuple[int, int]]) -> bytes:
    info = _el(0x2AD7B1, (1_000_000).to_bytes(3, "big"))
    if duration_ms is not None:
        info += _el(0x4489, struct.pack(">d", duration_ms))
    video = _el(0xE0, _el(0xB0, w.to_bytes(2, "big")) + _el(0xBA, h.to_bytes(2, "big")))
    tracks = _el(0x1654AE6B, _el(0xAE, _el(0xD7, b"\x01") + video))
    clusters = b""
    for cluster_tc, rel in blocks:
        block = bytes([0x81]) + struct.pack(">h", rel) + b"\x80" + b"frame"
        clusters += _el(0x1F43B675, _el(0xE7, cluster_tc.to_bytes(2, "big")) + _el(0xA3, block))
    segment = _el(0x18538067, _el(0x1549A966, info) + tracks + clusters)
    return _el(0x1A45DFA3, _el(0x4282, b"webm")) + segment


def test_read_webm_info_duration_element(tmp_path):
    p = tmp_path / "a.webm"
    p.write_bytes(_webm(12_345.0, 1440, 900, [(0, 0), (0, 40)]))
    info = rd.read_webm_info(p)
    assert info["duration_s"] == pytest.approx(12.345)
    assert info["duration_source"] == "webm Duration"
    assert (info["width"], info["height"]) == (1440, 900)
    assert info["frames"] == 2


def test_read_webm_info_falls_back_to_last_block(tmp_path):
    p = tmp_path / "b.webm"
    p.write_bytes(_webm(None, 320, 240, [(0, 0), (1000, 0), (2000, 480)]))
    info = rd.read_webm_info(p)
    assert info["duration_s"] == pytest.approx(2.48)
    assert info["duration_source"] == "webm 마지막 블록"
    assert info["frames"] == 3


def test_read_webm_info_rejects_non_webm(tmp_path):
    p = tmp_path / "c.webm"
    p.write_bytes(b"not a video")
    with pytest.raises(ValueError):
        rd.read_webm_info(p)


# ── 브라우저 테스트 ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def chromium_ok():
    pw_mod = pytest.importorskip("playwright.sync_api")
    try:
        with pw_mod.sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
    except Exception as exc:  # 브라우저 미설치 등
        pytest.skip(f"Chromium 실행 불가: {exc}")
    return True


def test_record_short_fake_page_makes_webm(tmp_path, chromium_ok):
    def scenario(page, tl):
        with tl.step("one", "첫 화면"):
            page.set_content("<html><body style='background:#fff'><h1 id='h'>녹화 테스트</h1></body></html>")
            page.wait_for_timeout(400)
        with tl.step("two", "두 번째 화면"):
            page.evaluate("document.getElementById('h').textContent = '둘째'")
            page.wait_for_timeout(400)

    res = rd.record(tmp_path, "unit", scenario, viewport=(320, 240))
    assert res.error == ""
    assert res.video == tmp_path / "unit.webm"
    assert res.video.is_file() and res.video.stat().st_size > 1000
    info = rd.read_webm_info(res.video)
    assert (info["width"], info["height"]) == (320, 240)
    assert info["duration_s"] and info["duration_s"] > 0.5
    assert [s.id for s in res.steps] == ["one", "two"]
    assert all(s.status == "ok" and s.t_end >= s.t_start for s in res.steps)
    assert res.steps[1].t_start >= res.steps[0].t_end
    assert not list(tmp_path.glob(".rec-*")), "임시 녹화 폴더가 남았다"


def test_record_keeps_video_when_scenario_fails(tmp_path, chromium_ok):
    def scenario(page, tl):
        with tl.step("boom"):
            page.set_content("<p>x</p>")
            page.wait_for_timeout(200)
            raise RuntimeError("일부러 실패")

    res = rd.record(tmp_path, "fail", scenario, viewport=(320, 240))
    assert "일부러 실패" in res.error
    assert res.video.is_file()
    assert res.steps[0].status == "failed"


# 가짜 앱: 실제 화면(src/neumann/webui)이 쓰는 선택자만 흉내 낸다.
FAKE_APP = """<!doctype html><html><head><meta charset="utf-8"><title>fake</title></head>
<body data-view="boot"><header style="position:fixed;top:0;left:0;right:0;height:56px;background:#fff">
<div id="steps"></div><span id="hdrState">서버 확인 중</span></header><div id="app" style="padding-top:70px"></div>
<script>
var EXPORT_ON = __EXPORT__, D = null, $ = function (i) { return document.getElementById(i); };
function steps() { $('steps').innerHTML = ['계획서','분석','리포트','내보내기'].map(function (s, i) {
  var off = (i === 3 && !EXPORT_ON); return '<button class="stp" data-step="' + i + '"' + (off ? ' disabled' : '') + '>' + s + '</button>'; }).join(''); }
function view(v, html) { document.body.dataset.ready = '0'; document.body.dataset.view = v; $('app').innerHTML = html; document.body.dataset.ready = '1'; }
function input() { view('input', '<button data-mode="text">직접 입력</button><textarea id="ta" rows="8" cols="80"></textarea><button id="btnStart" disabled>실행</button>');
  $('ta').addEventListener('input', function () { $('btnStart').disabled = !$('ta').value.trim(); });
  $('btnStart').addEventListener('click', start); }
function start() { view('job', '<h1>분석 실행</h1>');
  fetch('premortem/view', { method: 'POST', body: JSON.stringify({ plan_text: $('ta') ? '' : '' }) }).then(function (r) { return r.json(); })
    .then(function (b) { D = b; setTimeout(report, 200); }); }
function report() { var tall = '<div style="height:700px">근거·예방 행동</div>';
  view('report', '<section id="s-summary"><div id="statusNotice">' + D._status.label + '</div></section>' +
    '<section id="s-map" style="height:600px">지도</section><section id="s-cards">' +
    '<div class="rc" data-card="1"><h3>카드 1</h3><button class="cite" data-ev="1">#1</button>' + tall + '</div></section>' +
    '<aside><div id="pbody"></div></aside>'); }
document.addEventListener('click', function (e) { var t;
  if ((t = e.target.closest('[data-ev]'))) { $('pbody').innerHTML = '<div class="pq">인용</div><span class="lref" data-line="16">16행</span>'; return; }
  if ((t = e.target.closest('[data-line]'))) { $('pbody').innerHTML = '<div class="pq">계획서 16행</div>'; return; }
  if ((t = e.target.closest('[data-step]')) && !t.disabled && t.dataset.step === '3') { view('export', '<h1>내보내기</h1>'); } });
fetch('health').then(function (r) { return r.json(); }).then(function (h) { $('hdrState').textContent = h.pipeline.state; });
steps(); input();
</script></body></html>"""


BADGE_WATCH_JS = """
(() => {  // 테스트 쪽 감시: 배지 요소의 글자가 바뀔 때마다 파이썬으로 알린다(스크립트의 배지 읽기와 독립)
  let last = null;
  const report = () => {
    const e = document.getElementById('__demo_badge');
    const t = e && getComputedStyle(e).display !== 'none' ? e.textContent : '';
    if (t !== last) { last = t; window.__testBadge(t); }
  };
  new MutationObserver(report).observe(document, { subtree: true, childList: true, characterData: true });
})();
"""


def _fake_server(status: dict, export_on: bool, seen: list[str], badges: list[str]):
    def setup(context):
        def block(route):
            seen.append("BLOCKED " + route.request.url)
            route.abort()

        def handle(route):
            url = route.request.url
            seen.append(url)
            if url.endswith("/health"):
                route.fulfill(json={"pipeline": {"state": "unavailable"}})
            elif url.endswith("/premortem/view"):
                route.fulfill(json={"cards": [{}], "plan": {}, "_status": {"label": "라벨", **status}})
            else:
                route.fulfill(body=FAKE_APP.replace("__EXPORT__", "true" if export_on else "false"), content_type="text/html; charset=utf-8")

        context.route("**/*", block)  # 가짜 앱 밖으로는 나가지 않는다
        context.route("http://demo.test/**", handle)
        context.expose_function("__testBadge", lambda text: badges.append(text))
        context.add_init_script(BADGE_WATCH_JS)

    return setup


STEP_IDS = ["input", "paste", "analyze", "report", "risk_card", "evidence", "export"]


@pytest.mark.parametrize(
    ("health_state", "status", "export_on", "mode", "badge_from"),
    [
        # 점검 서버(미연결)와 같은 경우: 처음부터 배지
        ("unavailable", {"source": "sample"}, False, "sample", "input"),
        # 헬스는 연결인데 응답이 샘플: 응답을 받은 analyze 단계부터 배지 + 파일 이름 sample
        ("connected", {"source": "sample"}, False, "sample", "analyze"),
        # 응답이 source는 pipeline이라도 sample 플래그가 참이면 샘플
        ("connected", {"source": "pipeline", "sample": True}, False, "sample", "analyze"),
        # 둘 다 실제: 배지 없음
        ("connected", {"source": "pipeline"}, True, "live", None),
    ],
)
def test_demo_flow_offline(tmp_path, chromium_ok, capsys, health_state, status, export_on, mode, badge_from):
    seen: list[str] = []
    badges: list[str] = []
    code, meta = rd.run_demo(
        "http://demo.test",
        PLAN,
        tmp_path,
        pace=0.05,
        health_fetcher=lambda _url: {"version": "t", "pipeline": {"state": health_state, "mode": "sample" if health_state != "connected" else None}},
        setup=_fake_server(status, export_on, seen, badges),
        now=dt.datetime(2026, 9, 30, 12, 0, 0),
    )
    assert code == 0, meta.get("error")
    assert not [u for u in seen if u.startswith("BLOCKED")], "외부로 나간 요청이 있다"

    base = f"demo_20260930-120000_{mode}"
    video, sidecar = tmp_path / f"{base}.webm", tmp_path / f"{base}.json"
    assert video.is_file() and video.stat().st_size > 1000
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([video.name, sidecar.name])  # 다른 이름(live 등)이 남지 않는다
    saved = json.loads(sidecar.read_text(encoding="utf-8"))
    assert saved == meta
    assert saved["mode"] == mode and saved["sample"] is (mode == "sample")
    assert (saved["resolution"]["width"], saved["resolution"]["height"]) == (1440, 900)
    assert saved["duration_s"] and saved["duration_s"] > 1

    steps = saved["steps"]
    assert [s["id"] for s in steps] == STEP_IDS
    assert all(s["status"] == "ok" for s in steps[:-1])
    assert steps[-1]["status"] == ("ok" if export_on else "skipped")
    starts = [s["t_start"] for s in steps]
    assert starts == sorted(starts) and all(s["t_end"] >= s["t_start"] for s in steps)
    obs = saved["observed"]
    assert obs["response_source"] == status["source"]
    assert obs["response_sample"] is (status.get("source") == "sample" or status.get("sample") is True)
    assert obs["export"] == ("shown" if export_on else "unavailable")

    # 화면 배지: 샘플이면 반드시 보이고, 실제면 절대 없다
    by_step = obs["badge_by_step"]
    assert list(by_step) == STEP_IDS
    if mode == "sample":
        on_from = STEP_IDS.index(badge_from)
        assert all(by_step[s] == "" for s in STEP_IDS[:on_from]), by_step
        assert all("SAMPLE" in by_step[s] for s in STEP_IDS[on_from:]), by_step
        assert obs["badge_from"] == badge_from and "SAMPLE" in obs["badge"]
        assert any("SAMPLE" in b for b in badges), f"테스트 감시가 화면에서 SAMPLE 배지를 보지 못했다: {badges}"
        assert saved["sample_reason"] == (["health"] if health_state != "connected" else []) + (["response"] if obs["response_sample"] else [])
    else:
        assert all(v == "" for v in by_step.values()), by_step
        assert obs["badge_from"] is None and obs["badge"] == ""
        assert not any(badges), f"실제 녹화인데 배지가 떴다: {badges}"
        assert saved["sample_reason"] == []

    out = capsys.readouterr().out
    if mode == "sample":
        assert "[sample]" in out and "_sample.webm" in out


def test_demo_aborts_when_server_down(tmp_path):
    code, meta = rd.run_demo("http://demo.test", PLAN, tmp_path, health_fetcher=lambda _u: None)
    assert code == 2 and meta == {}
    assert not list(tmp_path.iterdir())
