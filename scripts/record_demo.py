"""시연 영상 녹화 (E6-L3b). 발표자료에 넣을 시연 영상을 Playwright로 녹화한다.

    python scripts/record_demo.py --base-url http://127.0.0.1:8010 \
        --demo example-battery --out data/video/          # 또는 example-binding · example-operator
    python scripts/record_demo.py --plan <계획서 경로> ...   # 예시 밖 계획서(붙여넣기)

순서: 입력 → 계획서 붙여넣기 → 분석 대기 → 리포트 → 위험카드 → 근거 열람 → (있으면) 내보내기.
사람 속도로 움직이고(가짜 커서·부드러운 스크롤), 단계마다 화면 아래에 짧은 주석(자막)을 띄운다.
(E6-L3d) 예시 선택은 AI4S 3건(`DEMO_EXAMPLES`, 화면 예시 목록 catalog.json examples와 같은 id)이다. `--demo <예시 id>`가
그 계획서 파일과 예시 버튼을 함께 고른다(기본 example-battery). 옛 fMRI·의료영상 예시는 뺐다(대표 지시).
(E6-L3c) 입력 화면에 범위 안내·"예시 불러오기"가 있고 `GET /templates`의 예시 중 파일 이름이 `--plan`과 같은 것이 있으면
붙여넣기 대신 그 예시 버튼을 누른다(`--example none`이면 늘 붙여넣기). 불러온 본문이 계획서 파일과 같은지 JSON에 남긴다.
분석 버튼 클릭·리포트 표시 시각(`observed.analysis_t_click`/`analysis_t_report`, 타임라인 기준)도 남겨 편집본이 대기 구간만 가속하게 한다.

- 샘플 판정: **헬스와 분석 응답 중 하나라도 샘플이면 샘플.** 녹화 전 `GET /health`가 `connected`가 아니면(미연결·오류)
  처음부터, 분석 응답 `_status`가 `source == "sample"` 또는 `sample: true`면 그 순간부터 화면 왼쪽 아래에
  "SAMPLE" 배지를 띄우고, 파일 이름·로그·JSON에 `sample`을 붙인다. 샘플 영상을 실제 시연처럼 쓰지 않게 하려는 것이다.
  단계마다 화면에 실제로 보인 배지 문구를 DOM에서 읽어 JSON `observed.badge_by_step`에 남긴다.
- 결과: `<out>/demo_<시각>_<sample|live>.webm`과 같은 이름의 `.json`(길이·해상도·단계별 타임스탬프).
  길이·해상도는 webm 헤더에서 읽는다(ffmpeg 없이).
- `--out`이 `data/`로 시작하는 상대 경로면 `NEUMANN_DATA_DIR`(공유 데이터 폴더) 아래로 푼다.
  worktree 안의 `data/`에 쌓이지 않게 하려는 것이다.
- 영상은 저장소에 커밋하지 않는다(공개 저장소, verify 5MB 상한). 업로드는 대표 승인 뒤.

종료 코드: 0 성공, 1 녹화 중 단계 실패(영상·JSON은 남긴다), 2 녹화 전 준비 실패(서버·계획서·Playwright).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import shutil
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "http://127.0.0.1:8010"
# 시연 예시(E6-L3d): 예시 id → 저장소 루트 기준 계획서. catalog.json examples와 같은 id·순서
DEMO_EXAMPLES: dict[str, str] = {
    "example-battery": "tests/fixtures/plans/plan.md",
    "example-binding": "src/neumann/api/templates/examples/protein_ligand_affinity.md",
    "example-operator": "src/neumann/api/templates/examples/neural_operator_weather.md",
}
DEMO_ALIASES = {"battery": "example-battery", "binding": "example-binding", "operator": "example-operator"}
DEFAULT_DEMO = "example-battery"
DEFAULT_PLAN = DEMO_EXAMPLES[DEFAULT_DEMO]
DEFAULT_OUT = "data/video/"
VIEWPORT = (1440, 900)

# 단계 id → 화면 주석. 샘플 데이터로 녹화해도 거짓이 되지 않게 "실제"라는 말을 쓰지 않는다.
STEPS: list[tuple[str, str]] = [
    ("input", "입력 화면 — 연구계획서를 넣는다"),
    ("paste", "계획서 붙여넣기"),
    ("analyze", "분석 실행 — 서버 응답 대기"),
    ("report", "리포트 — 요약·유사 연구·상위 위험"),
    ("risk_card", "위험카드 — 위험점수·근거·예방 행동"),
    ("evidence", "근거 열람 — 심사평 원문·출처·계획서 대응 줄"),
    ("export", "내보내기"),
]
STEP_LABEL = dict(STEPS)
SAMPLE_BADGE = "SAMPLE · 샘플 데이터 — 분석 결과 아님"

# ── 화면 주석·가짜 커서 (녹화 영상에는 OS 커서가 찍히지 않는다) ──────────────
OVERLAY_JS = r"""
(() => {
  if (window.__demo) return;
  const st = { caption: '', badge: '' };
  const css = `
    #__demo_cursor { position: fixed; left: 0; top: 0; width: 18px; height: 18px; margin: -9px 0 0 -9px;
      border-radius: 50%; background: rgba(220, 38, 38, .30); border: 2px solid rgba(185, 28, 28, .85);
      pointer-events: none; z-index: 2147483647; transition: width .12s, height .12s, margin .12s; }
    #__demo_cursor.down { width: 28px; height: 28px; margin: -14px 0 0 -14px; background: rgba(220, 38, 38, .45); }
    #__demo_caption { position: fixed; left: 50%; bottom: 30px; transform: translateX(-50%); max-width: 80vw;
      padding: 11px 20px; border-radius: 6px; background: rgba(17, 17, 17, .88); color: #fff;
      font: 600 17px/1.4 "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
      letter-spacing: .01em; pointer-events: none; z-index: 2147483646; transition: opacity .25s; }
    #__demo_caption:empty { opacity: 0; }
    #__demo_caption .n { color: #fca5a5; margin-right: 10px; font-variant-numeric: tabular-nums; }
    #__demo_badge { position: fixed; left: 16px; bottom: 16px; padding: 6px 12px; border-radius: 4px;
      background: #b45309; color: #fff; font: 700 13px/1.3 "Malgun Gothic", sans-serif; letter-spacing: .03em;
      pointer-events: none; z-index: 2147483646; }
    #__demo_badge:empty { display: none; }`;
  function ensure() {
    if (!document.body) return null;
    if (!document.getElementById('__demo_style')) {
      const s = document.createElement('style'); s.id = '__demo_style'; s.textContent = css;
      (document.head || document.documentElement).appendChild(s);
    }
    for (const id of ['__demo_cursor', '__demo_caption', '__demo_badge']) {
      if (!document.getElementById(id)) { const d = document.createElement('div'); d.id = id; document.body.appendChild(d); }
    }
    return true;
  }
  function paint() {
    if (!ensure()) return;
    const cap = document.getElementById('__demo_caption');
    cap.innerHTML = st.caption;
    document.getElementById('__demo_badge').textContent = st.badge;
  }
  window.__demo = {
    caption(html) { st.caption = html || ''; paint(); },
    badge(text) { st.badge = text || ''; paint(); },
  };
  document.addEventListener('mousemove', (e) => {
    if (!ensure()) return;
    document.getElementById('__demo_cursor').style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
  }, true);
  document.addEventListener('mousedown', () => { ensure() && document.getElementById('__demo_cursor').classList.add('down'); }, true);
  document.addEventListener('mouseup', () => { ensure() && document.getElementById('__demo_cursor').classList.remove('down'); }, true);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', paint); else paint();
})();
"""

SMOOTH_SCROLL_JS = r"""
async ([sel, offset, ms]) => {
  const el = sel ? document.querySelector(sel) : null;
  if (sel && !el) return false;
  const from = window.scrollY;
  const to = el ? Math.max(0, el.getBoundingClientRect().top + window.scrollY - offset) : Math.max(0, offset);
  const t0 = performance.now();
  await new Promise((done) => {
    function f(now) {
      const k = Math.min(1, (now - t0) / ms), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      window.scrollTo(0, from + (to - from) * e);
      if (k < 1) requestAnimationFrame(f); else done();
    }
    requestAnimationFrame(f);
  });
  return true;
}
"""


# 요소 가운데 점을 눌렀을 때 그 요소(또는 자식)가 맞는가. 가짜 커서·자막은 pointer-events:none이라 판정에 안 걸린다.
HIT_JS = r"""
(e) => {
  const r = e.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return false;
  const t = document.elementFromPoint(x, y);
  return !!t && (t === e || e.contains(t));
}
"""


# ── 결과 구조 ────────────────────────────────────────────────────────────────
@dataclass
class Step:
    id: str
    label: str
    t_start: float
    t_end: float | None = None
    status: str = "ok"  # ok | skipped | failed
    note: str = ""


@dataclass
class Timeline:
    """단계별 타임스탬프. t0 = 페이지 생성 시각(Playwright 녹화 시작과 거의 같다)."""

    clock: Callable[[], float] = time.monotonic
    t0: float = 0.0
    steps: list[Step] = field(default_factory=list)

    def start(self) -> None:
        self.t0 = self.clock()

    def now(self) -> float:
        return round(self.clock() - self.t0, 3)

    @contextmanager
    def step(self, step_id: str, label: str | None = None) -> Iterator[Step]:
        s = Step(step_id, label or STEP_LABEL.get(step_id, step_id), self.now())
        self.steps.append(s)
        try:
            yield s
        except Exception as exc:
            s.status, s.note = "failed", f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"
            raise
        finally:
            s.t_end = self.now()


@dataclass
class RecordResult:
    video: Path
    wall_s: float
    steps: list[Step]
    error: str = ""
    t0_lag_s: float = 0.0


# ── 준비: 경로·헬스·이름 ─────────────────────────────────────────────────────
def resolve_out_dir(arg: str | os.PathLike[str], env: dict[str, str] | None = None, cwd: Path | None = None) -> Path:
    """`data/…` 상대 경로는 공유 데이터 폴더(NEUMANN_DATA_DIR) 아래로, 그 밖의 상대 경로는 cwd 기준."""
    env = os.environ if env is None else env
    p = Path(arg)
    if p.is_absolute():
        return p
    data_dir = env.get("NEUMANN_DATA_DIR")
    if p.parts and p.parts[0] == "data" and data_dir:
        return Path(data_dir).joinpath(*p.parts[1:])
    return (cwd or Path.cwd()) / p


def select_demo(demo: str | None, plan: str | None, example: str) -> tuple[str, str]:
    """(계획서 경로, --example 값). `--demo`가 있으면 그 예시의 계획서와 예시 id를 함께 고른다.
    `--plan`만 있으면 그 파일(예시 버튼은 파일 이름으로 찾음). 둘 다 없으면 기본 예시."""
    if demo is not None:
        key = DEMO_ALIASES.get(demo, demo)
        if key not in DEMO_EXAMPLES:
            raise ValueError(f"예시 id '{demo}'는 없다. 가능한 값: {', '.join(DEMO_EXAMPLES)}")
        if plan is not None and Path(plan).name != Path(DEMO_EXAMPLES[key]).name:
            raise ValueError(f"--demo {key}와 --plan {Path(plan).name}이 다르다(둘 중 하나만 준다)")
        return DEMO_EXAMPLES[key], (key if example == "auto" else example)
    if plan is not None:
        return plan, example
    return DEMO_EXAMPLES[DEFAULT_DEMO], (DEFAULT_DEMO if example == "auto" else example)


def resolve_plan(arg: str) -> Path:
    p = Path(arg)
    if p.is_absolute() or p.is_file():
        return p
    return ROOT / p


def fetch_health(base_url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    url = base_url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (로컬 점검 서버)
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def find_example(base_url: str, plan_name: str, timeout: float = 5.0) -> dict[str, Any] | None:
    """`GET /templates`의 예시 중 `filename`이 계획서 파일 이름과 같은 것(없거나 실패하면 None)."""
    url = base_url.rstrip("/") + "/templates"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (로컬 점검 서버)
            cat = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    for ex in (cat or {}).get("examples") or []:
        if isinstance(ex, dict) and ex.get("filename") == plan_name and ex.get("id"):
            return ex
    return None


def _norm_text(t: str) -> str:
    return t.replace("\r\n", "\n").strip()


def classify_health(health: dict[str, Any] | None) -> tuple[str, str]:
    """(`live`|`sample`, 사유). 파이프라인이 `connected`일 때만 live. 나머지는 모두 샘플로 본다."""
    if not health:
        return "sample", "health 응답 없음"
    p = health.get("pipeline") or {}
    state = p.get("state")
    if state == "connected":
        return "live", "pipeline connected"
    return "sample", f"pipeline {state or '상태 없음'}" + (f" · mode {p['mode']}" if p.get("mode") else "")


def make_basename(mode: str, when: dt.datetime | None = None) -> str:
    when = when or dt.datetime.now()
    return f"demo_{when:%Y%m%d-%H%M%S}_{mode}"


# ── webm 헤더 읽기 (EBML, ffmpeg 없이 길이·해상도) ──────────────────────────
_MASTER = {0x18538067, 0x1549A966, 0x1654AE6B, 0xAE, 0xE0, 0x1F43B675, 0xA0}  # Segment Info Tracks TrackEntry Video Cluster BlockGroup
_ID_TIMECODE_SCALE, _ID_DURATION = 0x2AD7B1, 0x4489
_ID_PIXEL_W, _ID_PIXEL_H = 0xB0, 0xBA
_ID_CLUSTER, _ID_CLUSTER_TC, _ID_SIMPLE_BLOCK, _ID_BLOCK = 0x1F43B675, 0xE7, 0xA3, 0xA1


def _vint(buf: bytes, pos: int, keep_marker: bool) -> tuple[int, int, bool]:
    first = buf[pos]
    if first == 0:
        raise ValueError(f"잘못된 EBML 길이 바이트 @{pos}")
    length, mask = 1, 0x80
    while not first & mask:
        mask >>= 1
        length += 1
    value = first if keep_marker else first & (mask - 1)
    for b in buf[pos + 1 : pos + length]:
        value = (value << 8) | b
    unknown = not keep_marker and value == (1 << (7 * length)) - 1
    return value, length, unknown


def read_webm_info(path: str | os.PathLike[str]) -> dict[str, Any]:
    """webm의 길이(초)·해상도. Duration 요소가 없으면 마지막 블록 타임코드로 잰다."""
    data = Path(path).read_bytes()
    st: dict[str, Any] = {"scale": 1_000_000, "duration": None, "width": None, "height": None, "cluster": 0, "last": None, "blocks": 0}

    def uint(a: int, b: int) -> int:
        return int.from_bytes(data[a:b], "big")

    def walk(start: int, end: int) -> None:
        pos = start
        while pos < end and pos < len(data):
            eid, l1, _ = _vint(data, pos, True)
            size, l2, unknown = _vint(data, pos + l1, False)
            body = pos + l1 + l2
            stop = end if unknown else min(body + size, end, len(data))
            if eid in _MASTER:
                walk(body, stop)
            elif eid == _ID_TIMECODE_SCALE:
                st["scale"] = uint(body, stop)
            elif eid == _ID_DURATION:
                raw = data[body:stop]
                st["duration"] = struct.unpack(">f" if len(raw) == 4 else ">d", raw)[0]
            elif eid == _ID_PIXEL_W:
                st["width"] = uint(body, stop)
            elif eid == _ID_PIXEL_H:
                st["height"] = uint(body, stop)
            elif eid == _ID_CLUSTER_TC:
                st["cluster"] = uint(body, stop)
            elif eid in (_ID_SIMPLE_BLOCK, _ID_BLOCK) and stop - body >= 4:
                _, tl, _ = _vint(data, body, False)
                rel = struct.unpack(">h", data[body + tl : body + tl + 2])[0]
                t = st["cluster"] + rel
                st["last"] = t if st["last"] is None else max(st["last"], t)
                st["blocks"] += 1
            pos = stop

    if data[:4] != b"\x1a\x45\xdf\xa3":
        raise ValueError("webm(EBML) 파일이 아니다")
    walk(0, len(data))
    if st["duration"] is not None:
        duration, source = st["duration"] * st["scale"] / 1e9, "webm Duration"
    elif st["last"] is not None:
        duration, source = st["last"] * st["scale"] / 1e9, "webm 마지막 블록"
    else:
        duration, source = None, "없음"
    return {
        "duration_s": None if duration is None else round(duration, 3),
        "duration_source": source,
        "width": st["width"],
        "height": st["height"],
        "frames": st["blocks"],
    }


# ── 녹화 함수 (시나리오와 분리: 테스트는 가짜 페이지 시나리오로 부른다) ─────────
def record(
    out_dir: Path,
    basename: str,
    scenario: Callable[[Any, Timeline], None],
    *,
    viewport: tuple[int, int] = VIEWPORT,
    headless: bool = True,
    setup: Callable[[Any], None] | None = None,
) -> RecordResult:
    """브라우저를 띄워 `scenario(page, timeline)`을 녹화하고 `<out_dir>/<basename>.webm`에 둔다.

    시나리오가 실패해도 그때까지의 영상은 남기고 `error`에 사유를 적는다.
    `setup(context)`로 녹화 전에 라우팅(테스트의 가짜 서버) 등을 건다.
    """
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"{basename}.webm"
    tmp = Path(tempfile.mkdtemp(prefix=".rec-", dir=out_dir))
    tl = Timeline()
    error = ""
    wall = t0_lag = 0.0
    w, h = viewport
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless)
            try:
                context = browser.new_context(
                    viewport={"width": w, "height": h},
                    device_scale_factor=1,
                    locale="ko-KR",
                    record_video_dir=str(tmp),
                    record_video_size={"width": w, "height": h},  # 기본값은 800×800 안으로 줄인다
                )
                context.add_init_script(OVERLAY_JS)
                if setup:
                    setup(context)
                # 영상은 페이지가 만들어질 때 시작한다. 시계는 그 직전에 켜고, new_page에 걸린 시간을
                # 타임스탬프 오차(영상보다 최대 이만큼 늦을 수 있다)로 남긴다.
                tl.start()
                page = context.new_page()
                t0_lag = tl.now()
                try:
                    scenario(page, tl)
                except Exception as exc:  # 영상은 남기고 사유를 기록
                    error = f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"
                wall = tl.now()
                video = page.video
                context.close()  # 영상이 여기서 마무리된다
                if video is None:
                    raise RuntimeError("Playwright가 영상을 만들지 않았다")
                video.save_as(str(final))
                video.delete()
            finally:
                browser.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return RecordResult(video=final, wall_s=wall, steps=tl.steps, error=error, t0_lag_s=t0_lag)


# ── 시연 시나리오 ────────────────────────────────────────────────────────────
class Director:
    """사람 속도로 움직이는 도우미: 멈춤·가짜 커서 이동·부드러운 스크롤·주석."""

    def __init__(self, page: Any, *, pace: float = 1.0, captions: bool = True, total: int = len(STEPS)):
        self.page, self.pace, self.captions, self.total = page, pace, captions, total
        self.x, self.y = VIEWPORT[0] * 0.5, VIEWPORT[1] * 0.6
        self.n = 0

    def pause(self, seconds: float) -> None:
        self.page.wait_for_timeout(max(0, int(seconds * 1000 * self.pace)))

    def caption(self, text: str, numbered: bool = True) -> None:
        if not self.captions:
            return
        if numbered:
            self.n += 1
            html = f'<span class="n">{self.n}/{self.total}</span>' + _esc(text)
        else:
            html = _esc(text)
        self.page.evaluate("(h) => window.__demo && window.__demo.caption(h)", html)

    def badge(self, text: str) -> None:
        self.page.evaluate("(t) => window.__demo && window.__demo.badge(t)", text)

    def badge_text(self) -> str:
        """지금 화면에 보이는 배지 문구(없거나 숨겨져 있으면 빈 문자열). DOM에서 직접 읽는다."""
        return self.page.evaluate(
            "() => { const e = document.getElementById('__demo_badge');"
            " return e && getComputedStyle(e).display !== 'none' ? e.textContent : ''; }"
        )

    def move_to(self, locator: Any) -> None:
        locator.scroll_into_view_if_needed()
        if not locator.evaluate(HIT_JS):
            # (E6-L3c) 화면 안에 있어도 고정 머리글 밑에 가려 있으면 클릭이 머리글에 떨어진다 → 가운데로 올린다
            locator.evaluate("(e) => e.scrollIntoView({ block: 'center', behavior: 'smooth' })")
            prev = None
            for _ in range(40):  # 부드러운 스크롤이 멈추고 요소가 눌릴 자리에 올 때까지(최대 약 2초)
                self.page.wait_for_timeout(50)
                cur = locator.bounding_box()
                if cur == prev and locator.evaluate(HIT_JS):
                    break
                prev = cur
        box = locator.bounding_box()
        if not box:
            return
        tx, ty = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        dist = math.hypot(tx - self.x, ty - self.y)
        n = max(6, min(40, int(dist / 22)))
        for i in range(1, n + 1):
            k = i / n
            e = 1 - (1 - k) ** 3
            self.page.mouse.move(self.x + (tx - self.x) * e, self.y + (ty - self.y) * e)
            self.page.wait_for_timeout(max(1, int(16 * self.pace)))
        self.x, self.y = tx, ty

    def click(self, locator: Any) -> None:
        self.move_to(locator)
        self.pause(0.35)
        self.page.mouse.down()
        self.page.wait_for_timeout(max(1, int(90 * self.pace)))
        self.page.mouse.up()

    def scroll_to(self, selector: str | None, offset: int = 90, ms: int = 900) -> bool:
        return bool(self.page.evaluate(SMOOTH_SCROLL_JS, [selector, offset, max(1, int(ms * self.pace))]))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class DemoInfo:
    """시나리오가 채우는 관찰값(JSON에 들어간다)."""

    response_status: int | None = None
    response_source: str | None = None
    response_label: str | None = None
    response_sample: bool = False  # 응답 `_status`가 샘플이라고 했나
    analysis_s: float | None = None
    status_notice: str | None = None
    export: str = "unknown"
    scope: str | None = None  # 입력 화면 범위 안내 문구(#scope)
    plan_source: str = "paste"  # paste | example:<id>
    plan_loaded_chars: int | None = None  # 입력칸에 들어간 글자 수
    plan_matches_file: bool | None = None  # 입력칸 본문 == 계획서 파일(줄바꿈·앞뒤 공백 정규화)
    analysis_t_click: float | None = None  # 분석 버튼 클릭(타임라인 초)
    analysis_t_report: float | None = None  # 리포트 또는 오류가 뜬 시각(타임라인 초)
    badge: str = ""  # 녹화 끝에 화면에 있던 배지 문구(DOM에서 읽음)
    badge_from: str | None = None  # 배지가 처음 보인 단계
    badge_by_step: dict[str, str] = field(default_factory=dict)  # 단계 끝마다 화면의 배지 문구


def response_is_sample(status: dict[str, Any] | None) -> bool:
    """분석 응답의 `_status`가 샘플이면 참: `source == "sample"` 또는 `sample: true`."""
    status = status or {}
    return status.get("source") == "sample" or status.get("sample") is True


def demo_scenario(
    base_url: str,
    plan_text: str,
    plan_name: str,
    *,
    mode: str,
    info: DemoInfo,
    pace: float = 1.0,
    captions: bool = True,
    analysis_timeout_s: float = 180.0,
    stills_dir: Path | None = None,
    stills_prefix: str = "",
    example: dict[str, Any] | None = None,
) -> Callable[[Any, Timeline], None]:
    """입력 → 붙여넣기 → 분석 대기 → 리포트 → 위험카드 → 근거 → 내보내기. `record()`에 넘긴다."""
    url = base_url.rstrip("/") + "/"

    def run(page: Any, tl: Timeline) -> None:
        d = Director(page, pace=pace, captions=captions)
        page.set_default_timeout(15_000)

        def still(step_id: str) -> None:
            if stills_dir is not None:
                page.screenshot(path=str(stills_dir / f"{stills_prefix}{len(tl.steps):02d}_{step_id}.png"))

        @contextmanager
        def step(step_id: str) -> Iterator[Step]:
            """tl.step + 단계 끝에 화면의 배지 문구를 기록(샘플 표지가 실제로 보였는지 JSON·테스트가 확인)."""
            with tl.step(step_id) as s:
                yield s
                shown = d.badge_text()
                info.badge_by_step[step_id] = shown
                if shown and info.badge_from is None:
                    info.badge_from = step_id

        with step("input"):
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector('body[data-view="input"][data-ready="1"]')
            if mode == "sample":
                d.badge(SAMPLE_BADGE)
            d.caption(STEP_LABEL["input"])
            try:  # 헤더의 서버 상태 표시가 채워질 때까지(없어도 계속)
                page.wait_for_function("() => { const e = document.getElementById('hdrState'); return !e || e.textContent.trim() !== '서버 확인 중'; }", timeout=5_000)
            except Exception:
                pass
            if example is not None:  # 템플릿·예시 목록이 그려질 때까지(없어도 계속)
                try:
                    page.wait_for_selector("#exList [data-ex]", timeout=5_000)
                except Exception:
                    pass
            if page.locator("#scope").count():  # 범위 안내(AI 활용 과학 연구 계획서 전용)를 가리킨다
                info.scope = " ".join(page.locator("#scope").inner_text().split())
                d.move_to(page.locator("#scope"))
            d.pause(2.2)
            still("input")

        with step("paste") as s:
            ex_sel = f'#exList [data-ex="{example["id"]}"]' if example is not None else ""
            if ex_sel and page.locator(ex_sel).count():
                d.caption(f"예시 불러오기 — {example.get('name') or example['id']} ({plan_name})")
                d.click(page.locator(ex_sel).first)
                page.wait_for_function("() => { const t = document.getElementById('ta'); return t && t.value.trim().length > 0; }")
                info.plan_source = f"example:{example['id']}"
            else:
                if page.locator("#ta").count() == 0:
                    d.click(page.locator('[data-mode="text"]').first)
                    page.wait_for_selector("#ta")
                d.caption(f"{STEP_LABEL['paste']} — {plan_name} ({len(plan_text):,}자)")
                ta = page.locator("#ta")
                d.click(ta)
                d.pause(0.5)
                ta.fill(plan_text)  # 붙여넣기처럼 한 번에 넣는다(input 이벤트 발생)
                ta.evaluate("(e) => { e.setSelectionRange(0, 0); e.scrollTop = 0; }")  # 계획서 첫머리가 보이게
            loaded = page.locator("#ta").input_value()
            info.plan_loaded_chars = len(loaded)
            info.plan_matches_file = _norm_text(loaded) == _norm_text(plan_text)
            s.note = f"{info.plan_source} · {len(loaded)}자 · 파일과 {'같음' if info.plan_matches_file else '다름'}"
            page.wait_for_selector("#btnStart:not([disabled])")
            d.pause(2.0)
            still("paste")

        with step("analyze") as s:
            d.caption(STEP_LABEL["analyze"])
            btn = page.locator("#btnStart")
            d.move_to(btn)
            d.pause(0.5)
            t_click = time.monotonic()
            info.analysis_t_click = tl.now()
            with page.expect_response(lambda r: r.url.rstrip("/").endswith("premortem/view"), timeout=int(analysis_timeout_s * 1000)) as resp_info:
                page.mouse.down()
                page.mouse.up()
            resp = resp_info.value
            info.response_status = resp.status
            try:
                st = (resp.json() or {}).get("_status") or {}
                info.response_source, info.response_label = st.get("source"), st.get("label")
                info.response_sample = response_is_sample(st)
            except Exception:
                pass
            if info.response_sample:  # 헬스가 연결이라 했어도 응답이 샘플이면 여기서부터 화면에 표지
                d.badge(SAMPLE_BADGE)
            page.wait_for_selector('body[data-view="report"], #jobErr', timeout=int(analysis_timeout_s * 1000))
            info.analysis_s = round(time.monotonic() - t_click, 3)
            info.analysis_t_report = tl.now()
            if page.locator("#jobErr").count():
                s.note = page.locator("#jobErr").inner_text().strip()
                still("analyze_failed")
                raise RuntimeError(f"분석 실패: {s.note}")
            s.note = f"응답 {info.response_status} · source {info.response_source} · {info.analysis_s:.1f}s"

        with step("report"):
            page.wait_for_selector('body[data-view="report"][data-ready="1"]')
            d.caption(STEP_LABEL["report"])
            if page.locator("#statusNotice").count():
                info.status_notice = " ".join(page.locator("#statusNotice").inner_text().split())
            d.pause(3.0)
            still("report")
            if d.scroll_to("#s-map", ms=1100):
                d.pause(2.4)

        with step("risk_card") as s:
            card = page.locator("#s-cards .rc").first
            if page.locator("#s-cards .rc").count() == 0:
                s.status = "skipped"
                s.note = "위험카드 0장"
                d.caption("위험카드 0장")
                d.scroll_to("#s-cards", ms=900)
                d.pause(2.0)
            else:
                d.caption(STEP_LABEL["risk_card"])
                d.scroll_to("#s-cards .rc", ms=1100)
                d.pause(2.6)
                still("risk_card")
                box = card.bounding_box()
                if box and box["height"] > VIEWPORT[1] * 0.6:  # 긴 카드는 근거·예방 행동까지 천천히 내려 본다
                    page.evaluate("(dy) => window.scrollBy({ top: dy, behavior: 'smooth' })", int(min(box["height"] - 300, 420)))
                    d.pause(2.0)
                s.note = f"카드 {page.locator('#s-cards .rc').count()}장"

        with step("evidence") as s:
            cite = page.locator("#s-cards .rc .cite[data-ev]").first
            if page.locator("#s-cards .rc .cite[data-ev]").count() == 0:
                cite = page.locator(".cite[data-ev]").first
            if page.locator(".cite[data-ev]").count() == 0:
                s.status, s.note = "skipped", "근거 번호 없음"
                d.caption("근거 번호 없음")
                d.pause(1.5)
            else:
                d.caption(STEP_LABEL["evidence"])
                ev_id = cite.get_attribute("data-ev")
                d.click(cite)
                page.wait_for_selector("#pbody .pq")
                d.pause(3.2)
                still("evidence")
                lref = page.locator("#pbody .lref[data-line]").first
                if page.locator("#pbody .lref[data-line]").count():
                    d.click(lref)
                    d.pause(2.6)
                s.note = f"근거 #{ev_id}"

        with step("export") as s:
            d.scroll_to(None, offset=0, ms=700)
            exp = page.locator("#steps .stp", has_text="내보내기").first
            if page.locator("#steps .stp", has_text="내보내기").count() and exp.is_enabled():
                d.caption(STEP_LABEL["export"])
                d.click(exp)
                d.pause(3.0)
                still("export")
                info.export = "shown"
                s.note = "내보내기 단계 열림"
            else:
                d.caption(f"{STEP_LABEL['export']} — 이 빌드에서는 준비 중")
                if page.locator("#steps .stp", has_text="내보내기").count():
                    d.move_to(exp)
                d.pause(2.0)
                info.export = "unavailable"
                s.status, s.note = "skipped", "내보내기 단계 비활성(준비 중)"

        d.caption("끝 · 최종 판단은 연구자에게", numbered=False)
        d.pause(2.0)
        info.badge = d.badge_text()

    return run


# ── CLI ──────────────────────────────────────────────────────────────────────
def _log(mode: str, msg: str) -> None:
    print(f"[record_demo][{mode}] {msg}", flush=True)


def run_demo(
    base_url: str,
    plan_path: Path,
    out_dir: Path,
    *,
    pace: float = 1.0,
    captions: bool = True,
    headless: bool = True,
    analysis_timeout_s: float = 180.0,
    stills: bool = False,
    health_fetcher: Callable[[str], dict[str, Any] | None] = fetch_health,
    setup: Callable[[Any], None] | None = None,
    now: dt.datetime | None = None,
    example: str = "auto",
    example_finder: Callable[[str, str], dict[str, Any] | None] = find_example,
    task: str = "E6-L3b",
) -> tuple[int, dict[str, Any]]:
    """헬스 확인 → 녹화 → 이름 정하기 → JSON. (종료 코드, 메타데이터)."""
    health = health_fetcher(base_url)
    if health is None:
        _log("sample", f"서버 응답 없음: {base_url.rstrip('/')}/health — 녹화하지 않는다")
        return 2, {}
    mode, why = classify_health(health)
    _log(mode, f"health: {why}" + (" → 파일 이름·로그에 sample 표시" if mode == "sample" else ""))
    plan_text = plan_path.read_text(encoding="utf-8")
    when = now or dt.datetime.now()
    basename = make_basename(mode, when)
    stills_dir = out_dir if stills else None
    info = DemoInfo()
    ex = None if example == "none" else example_finder(base_url, plan_path.name)
    if example not in ("auto", "none") and ex is not None and ex.get("id") != example:
        ex = None  # 지정한 예시 id가 파일 이름으로 찾은 것과 다르면 붙여넣기로
    _log(mode, "예시 불러오기: " + (f"{ex['id']} ({plan_path.name})" if ex else "없음 → 붙여넣기"))
    scenario = demo_scenario(
        base_url, plan_text, plan_path.name, mode=mode, info=info, pace=pace, captions=captions,
        analysis_timeout_s=analysis_timeout_s, stills_dir=stills_dir, stills_prefix=basename + "_", example=ex,
    )
    _log(mode, f"녹화 시작: {base_url} · {plan_path.name} ({len(plan_text)}자) · {VIEWPORT[0]}×{VIEWPORT[1]}")
    result = record(out_dir, basename, scenario, viewport=VIEWPORT, headless=headless, setup=setup)

    # 헬스 또는 응답 중 하나라도 샘플이면 샘플이다(응답 쪽 화면 배지는 시나리오가 이미 켰다)
    reasons = (["health"] if mode == "sample" else []) + (["response"] if info.response_sample else [])
    if mode == "live" and info.response_sample:
        mode = "sample"
        new = make_basename(mode, when)
        new_video = result.video.with_name(f"{new}.webm")
        result.video.replace(new_video)
        if stills_dir is not None:
            for p in stills_dir.glob(f"{basename}_*.png"):
                p.replace(p.with_name(p.name.replace(basename, new, 1)))
        result.video, basename = new_video, new
        _log(mode, f"응답 _status가 샘플 → sample로 이름 바꿈 · 화면 배지는 {info.badge_from or '없음'} 단계부터")

    try:
        vinfo = read_webm_info(result.video)
    except Exception as exc:  # 헤더를 못 읽어도 영상은 남는다
        vinfo = {"duration_s": None, "duration_source": f"읽기 실패: {exc}", "width": None, "height": None, "frames": None}
    meta: dict[str, Any] = {
        "task": task,
        "video": result.video.name,
        "bytes": result.video.stat().st_size if result.video.exists() else 0,
        "mode": mode,
        "sample": mode == "sample",
        "sample_reason": reasons,
        "health": {k: (health.get("pipeline") or {}).get(k) for k in ("state", "mode", "label")} | {"version": health.get("version")},
        "recorded_at": when.astimezone().isoformat(timespec="seconds"),
        "base_url": base_url,
        "plan": plan_path.name,
        "plan_chars": len(plan_text),
        "viewport": {"width": VIEWPORT[0], "height": VIEWPORT[1]},
        "duration_s": vinfo["duration_s"],
        "duration_source": vinfo["duration_source"],
        "wall_s": result.wall_s,
        "resolution": {"width": vinfo["width"], "height": vinfo["height"]},
        "frames": vinfo["frames"],
        "t0": "new_page() 호출 직전. 영상 시작은 그 뒤 t0_lag_s 안쪽",
        "t0_lag_s": result.t0_lag_s,
        "steps": [asdict(s) for s in result.steps],
        "observed": asdict(info),
        "captions": captions,
        "pace": pace,
        "ok": not result.error,
        "error": result.error,
    }
    json_path = result.video.with_suffix(".json")
    json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for s in result.steps:
        _log(mode, f"  {s.t_start:7.2f}s → {s.t_end if s.t_end is not None else float('nan'):7.2f}s  {s.id:<10} {s.status:<8} {s.note}")
    _log(mode, f"영상: {result.video} · {meta['bytes'] / 1024 / 1024:.2f} MB · {vinfo['width']}×{vinfo['height']} · 길이 {vinfo['duration_s']}s ({vinfo['duration_source']}) · 벽시계 {result.wall_s:.1f}s")
    _log(mode, f"화면 배지: {info.badge_from or '없음'}" + (f" 단계부터 '{info.badge}'" if info.badge_from else "") + (f" · 샘플 사유 {'+'.join(reasons)}" if reasons else ""))
    _log(mode, f"JSON: {json_path}")
    if result.error:
        _log(mode, f"실패: {result.error}")
        return 1, meta
    return 0, meta


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--demo", default=None, help=f"시연 예시 id({' | '.join(DEMO_EXAMPLES)}, 기본 {DEFAULT_DEMO})")
    ap.add_argument("--plan", default=None, help="예시 밖 계획서 경로(--demo 대신)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="data/…는 NEUMANN_DATA_DIR 아래로 푼다")
    ap.add_argument("--pace", type=float, default=1.0, help="멈춤 배율(1=사람 속도, 작을수록 빠름)")
    ap.add_argument("--no-captions", action="store_true", help="화면 주석(자막) 끄기")
    ap.add_argument("--headed", action="store_true", help="브라우저 창을 띄워 녹화")
    ap.add_argument("--analysis-timeout", type=float, default=180.0, help="분석 응답 대기 상한(초)")
    ap.add_argument("--stills", action="store_true", help="단계마다 PNG도 out에 저장")
    ap.add_argument("--example", default="auto", help="auto(파일 이름이 같은 예시 버튼) | none(늘 붙여넣기) | 예시 id")
    ap.add_argument("--task", default="E6-L3b", help="JSON의 task 표기")
    args = ap.parse_args(argv)

    try:
        plan_arg, args.example = select_demo(args.demo, args.plan, args.example)
    except ValueError as exc:
        print(f"[record_demo] {exc}", file=sys.stderr)
        return 2
    plan = resolve_plan(plan_arg)
    if not plan.is_file():
        print(f"[record_demo] 계획서 없음: {plan}", file=sys.stderr)
        return 2
    out_dir = resolve_out_dir(args.out)
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("[record_demo] playwright가 없다: pip install playwright && playwright install chromium", file=sys.stderr)
        return 2
    code, _ = run_demo(
        args.base_url, plan, out_dir, pace=args.pace, captions=not args.no_captions, headless=not args.headed,
        analysis_timeout_s=args.analysis_timeout, stills=args.stills, example=args.example, task=args.task,
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
