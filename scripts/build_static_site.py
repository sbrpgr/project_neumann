"""정적 배포 빌드 (E6-L3a): 서버 없이 도는 데모 사이트를 공유 폴더 ``data/site/``에 만든다.

    python scripts/build_static_site.py                       # <data>/site/
    python scripts/build_static_site.py --out DIR             # 다른 곳에
    python scripts/build_static_site.py --check DIR           # 이미 만든 폴더 검사만

- 화면 원본 ``src/neumann/webui/index.html``은 고치지 않는다. 산출물 ``index.html``에만 정적 모드를 주입한다.
  1) ``<head>``: 데모 목록 ``window.NEUMANN_STATIC`` + ``fetch`` 가로채기(``health`` → 정적 상태,
     ``premortem/view`` → ``demo/<id>.json``을 상대 경로로 읽음)
  2) 헤더 아래: "정적 판 · 사전 계산본 — 라이브 분석 아님" 띠
  3) ``</body>`` 앞: 입력 화면을 데모 3건 선택으로 바꾼다(본문 읽기 전용, 파일 업로드 숨김)
- 데모 3건(``tests/fixtures/plans``)마다 사전 계산본(``<data>/precomputed/``, E6-L2a)을 찾고,
  없거나 검증에 실패하면 공용 fixture 결과(가짜 데이터)로 채우되 화면·JSON에 그렇다고 적는다.
- 모든 경로는 상대 경로라 GitHub Pages 하위 경로(``/project_neumann/``)에서도 돈다.
- 빌드 뒤 ``check_site``가 자동 검사한다: 필수 파일, 비밀값 패턴·실제 비밀값, 환경변수 이름,
  로컬 절대 경로, 외부 도메인·루트 절대 경로 참조. 하나라도 걸리면 exit 1(찾은 값은 출력하지 않는다).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "src", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from neumann.models import PlanDocument, PremortemResult  # noqa: E402

WEBUI_DIR = ROOT / "src" / "neumann" / "webui"
FIXTURE_RESULT = ROOT / "tests" / "fixtures" / "premortem_result.json"
PLANS_DIR = ROOT / "tests" / "fixtures" / "plans"
DEMO_PLANS = ("plan.md", "plan_elife_neuro.md", "plan_medimaging.md")
FIXTURE_PLAN = "plan.md"  # 공용 fixture 결과가 기준으로 삼은 계획서
MANIFEST_NAMES = ("manifest.json", "index.json", "_manifest.json")
BUILD_MARK = "build.json"
KST = timezone(timedelta(hours=9), "KST")

LIVE_NOTE = "라이브 분석 아님"
SITE_TITLE_SUFFIX = " (정적 데모 · 사전 계산본)"
INPUT_NOTE = ("정적 판: 미리 계산해 둔 데모 3건 중 하나를 고르면 본문이 채워집니다. "
              "본문 수정·파일 업로드·라이브 분석은 서버 판에서만 됩니다.")

ViewBuilder = Callable[..., dict[str, Any]]
Validator = Callable[[dict[str, Any]], list[str]]


# ───────────────────────── 데모 결과 고르기 ─────────────────────────


@dataclass
class Demo:
    demo_id: str
    file: str
    title: str
    plan_text: str
    plan_id: str
    kind: str = "fixture"  # precomputed | fixture
    result: dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""
    model: str = ""
    origin: str = ""
    reason: str = ""
    manifest_sha_ok: bool | None = None
    notices: list[str] = field(default_factory=list)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _plan_title(text: str) -> str:
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    title = re.sub(r"^#+\s*", "", first).strip()
    return re.sub(r"^연구계획서\s*\(예시\)\s*[—\-:]\s*", "", title) or title


def load_demos(plans_dir: Path = PLANS_DIR, names: Iterable[str] = DEMO_PLANS) -> list[Demo]:
    demos = []
    for name in names:
        text = (plans_dir / name).read_text(encoding="utf-8")
        demos.append(Demo(demo_id=Path(name).stem, file=name, title=_plan_title(text), plan_text=text,
                          plan_id=PlanDocument.from_text(text, "static").plan_id))
    return demos


def _manifest_entries(pre_dir: Path) -> tuple[list[dict[str, Any]], str]:
    """사전 계산본 매니페스트를 항목 목록으로 편다. 모양(E6-L2a)이 정해지지 않아 흔한 모양을 모두 받는다."""
    for name in MANIFEST_NAMES:
        path = pre_dir / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [], f"{name} 파싱 실패"
        items: list[Any] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("entries", "items", "plans", "results", "demos", "files"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
                if isinstance(data.get(key), dict):
                    items = [{"_key": k, **v} for k, v in data[key].items() if isinstance(v, dict)]
                    break
            else:
                items = [{"_key": k, **v} for k, v in data.items() if isinstance(v, dict)]
        return [it for it in items if isinstance(it, dict)], name
    return [], ""


def _first(d: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def _entry_for(entries: list[dict[str, Any]], demo: Demo) -> dict[str, Any] | None:
    for e in entries:
        keys = {str(e.get(k, "")) for k in ("plan_id", "_key", "id", "demo_id", "plan", "file", "path", "filename",
                                             "plan_file", "name")}
        keys |= {Path(k).stem for k in list(keys) if k}
        if demo.plan_id in keys or demo.demo_id in keys or demo.file in keys:
            return e
    return None


def _fmt_time(value: Any) -> str:
    if not value:
        return ""
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:32]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")


def _model_of(result: Mapping[str, Any], entry: Mapping[str, Any] | None) -> str:
    man = result.get("manifest") or {}
    model = _first(man, "model_id", "model") or _first(entry or {}, "model_id", "model")
    provider = _first(man, "model_provider", "provider") or _first(entry or {}, "model_provider", "provider")
    if model:
        return f"{model}" + (f" ({provider})" if provider and str(provider) not in str(model) else "")
    gens = sorted({str(c.get("generator", "")) for c in result.get("risk_cards", []) if c.get("generator")})
    if gens == ["mock"]:
        return "mock provider"
    return "모델 미기록" + (f" · 생성 방식 {'/'.join(gens)}" if gens else "")


def _attach_plan(result: dict[str, Any], demo: Demo) -> None:
    """저장본에 계획서 본문이 빠져 있으면(dump_persisted) 공개 데모 계획서에서 다시 붙인다. plan_id가 같을 때만."""
    plan = result.get("plan")
    if isinstance(plan, dict) and plan.get("lines"):
        return
    if result.get("plan_id") == demo.plan_id:
        result["plan"] = PlanDocument.from_text(demo.plan_text, str(result.get("session_id") or "static")).model_dump(
            mode="json")


def find_precomputed(demo: Demo, pre_dir: Path | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    """(결과 dict, 매니페스트 항목, 못 쓴 사유). 결과는 PremortemResult 검증·plan_id 일치·매니페스트 sha256 일치를 통과한 것만."""
    if pre_dir is None or not pre_dir.is_dir():
        return None, None, "사전 계산본 폴더 없음"
    entries, man_name = _manifest_entries(pre_dir)
    entry = _entry_for(entries, demo)
    candidates: list[Path] = []
    if entry:
        f = _first(entry, "file", "path", "json", "filename", "result")
        if isinstance(f, str):
            candidates.append(pre_dir / Path(f).name)
    candidates += [pre_dir / f"{demo.plan_id}.json", pre_dir / f"{demo.demo_id}.json"]
    candidates += sorted(p for p in pre_dir.glob("*.json") if p.name not in MANIFEST_NAMES)
    seen: set[Path] = set()
    why = "데모 계획서와 plan_id가 맞는 사전 계산본 없음"
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        raw = path.read_bytes()
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("plan_id") != demo.plan_id:
            continue
        expected = _first(entry or {}, "sha256", "file_sha256", "json_sha256", "sha")
        if expected and str(expected).lower() != _sha256_bytes(raw):
            return None, entry, f"사전 계산본 sha256이 매니페스트({man_name})와 다름(변조 의심)"
        # 최상위 확장 키(sample·precomputed 등)는 계약 검증에서 빼고, 출처 판단에만 쓴다
        known = set(PremortemResult.model_fields)
        core = {k: v for k, v in data.items() if k in known}
        try:
            result = PremortemResult.model_validate(core).model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 - 계약을 어긴 저장본은 쓰지 않는다
            why = f"사전 계산본이 PremortemResult 계약을 통과하지 못함({type(exc).__name__})"
            continue
        for k in ("sample", "source", "mode", "origin"):
            if k in data and k not in result:
                result[k] = data[k]
        info = dict(entry or {})
        info["_manifest"] = man_name
        info["_sha_ok"] = bool(expected)
        return result, info, ""
    return None, entry, why


def _origin(result: Mapping[str, Any], entry: Mapping[str, Any] | None) -> str:
    """사전 계산본이 실제 파이프라인 결과인지 fixture 대체인지. 저장본·매니페스트가 밝힌 것만 믿는다."""
    for src in (entry or {}, result):
        for k in ("origin", "source", "mode", "method", "generated_by", "kind"):
            v = src.get(k)
            if isinstance(v, str) and v:
                return v
    if result.get("sample") is True:
        return "sample"
    if any("fixture" in str(n).lower() or "fake" in str(n).lower() for n in result.get("notices", [])):
        return "fixture"
    return "pipeline"


def resolve_demo(demo: Demo, pre_dir: Path | None, fixture_path: Path = FIXTURE_RESULT) -> Demo:
    result, entry, why = find_precomputed(demo, pre_dir)
    if result is not None:
        demo.kind = "precomputed"
        demo.origin = _origin(result, entry)
        demo.manifest_sha_ok = bool(entry and entry.get("_sha_ok")) or None
        _attach_plan(result, demo)
        demo.result = result
        demo.generated_at = str(result.get("generated_at") or _first(entry or {}, "generated_at", "created_at") or "")
        demo.model = _model_of(result, entry)
        if demo.manifest_sha_ok:
            demo.notices.append(f"사전 계산본 sha256이 매니페스트({entry.get('_manifest')})와 같다.")
        else:
            demo.notices.append("사전 계산본 매니페스트에 sha256이 없어 변조 여부를 확인하지 못했다.")
        if "fixture" in demo.origin.lower() or "sample" in demo.origin.lower() or "mock" in demo.origin.lower():
            demo.notices.append(f"이 사전 계산본은 실제 분석이 아니라 대체 결과다(생성 방식 표기: {demo.origin}).")
        return demo
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    demo.kind = "fixture"
    demo.origin = "fixture"
    demo.reason = why
    demo.result = PremortemResult.model_validate(data).model_dump(mode="json")
    demo.generated_at = str(demo.result.get("generated_at") or "")
    demo.model = _model_of(demo.result, None)
    demo.notices.append(f"사전 계산본을 쓰지 못함: {why}.")
    if demo.file != FIXTURE_PLAN:
        demo.notices.append(f"아래 화면은 이 계획서({demo.file})가 아니라 예시 계획서({FIXTURE_PLAN}) 기준의 공용 fixture(가짜 데이터)다.")
    return demo


def demo_label(demo: Demo) -> str:
    when = _fmt_time(demo.generated_at) or "생성 시각 미기록"
    if demo.kind == "precomputed":
        return f"사전 계산본(생성 {when} · 모델 {demo.model}) — {LIVE_NOTE}"
    return f"샘플(공용 fixture · 가짜 데이터 · 생성 {when} · 모델 {demo.model}) — 사전 계산본 없음 · {LIVE_NOTE}"


def demo_badge(demo: Demo) -> str:
    when = _fmt_time(demo.generated_at) or "시각 미기록"
    if demo.kind == "precomputed":
        return f"사전 계산본 · {when} · {demo.model}"
    return "샘플(가짜 데이터) · 사전 계산본 없음"


# ───────────────────────── 화면 데이터 ─────────────────────────


def _default_view_tools() -> tuple[ViewBuilder, Validator]:
    from neumann.api.view import build_ui_view, validate_ui_view  # E4 화면 데이터 계약 조립기

    return build_ui_view, validate_ui_view


def make_view(demo: Demo, build_view: ViewBuilder, validate: Validator | None, built_at: str) -> dict[str, Any]:
    sample = demo.kind == "fixture" or any(s in demo.origin.lower() for s in ("fixture", "sample", "mock"))
    input_info = {"chars": len(demo.plan_text), "lines": sum(1 for ln in demo.plan_text.splitlines() if ln.strip()),
                  "filename": demo.file}
    view = build_view(demo.result, filename=demo.file, sample=sample, pipeline_state="precomputed",
                      input_info=input_info, extra_notices=list(demo.notices))
    st = view.setdefault("_status", {})
    st["label"] = demo_label(demo)
    st["static"] = {
        "kind": demo.kind, "demo_id": demo.demo_id, "file": demo.file, "origin": demo.origin,
        "generated_at": demo.generated_at, "generated_kst": _fmt_time(demo.generated_at), "model": demo.model,
        "reason": demo.reason, "manifest_sha256_ok": demo.manifest_sha_ok, "built_at": built_at, "live": False,
    }
    if validate is not None:
        errors = validate(view)
        if errors:
            raise ValueError(f"{demo.demo_id}: 화면 데이터 계약 위반 {errors[:3]}")
    return view


# ───────────────────────── 주입 ─────────────────────────

STATIC_CSS = """
  /* ===== 정적 판(E6-L3a 빌드 주입) ===== */
  .sbanner { position: relative; z-index: 1; padding: 8px 36px; border-bottom: 1px solid var(--red-l); background: var(--bg); color: var(--red-d); font-size: 13px; text-align: center; line-height: 1.6; }
  .sbanner b { font-family: var(--head); font-weight: 600; letter-spacing: .04em; color: var(--red); margin-right: 8px; }
  .sdemos { flex: 1 1 100%; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
  .sdemo { text-align: left; padding: 10px 12px; border: 1px solid var(--line2); border-radius: 3px; background: var(--card); line-height: 1.45; }
  .sdemo:hover { border-color: var(--ink); }
  .sdemo .n { font-family: var(--mono); font-size: 11px; letter-spacing: .08em; color: var(--muted); }
  .sdemo .t { display: block; font-family: var(--head); font-weight: 600; font-size: 14px; color: var(--ink); margin: 2px 0 4px 0; }
  .sdemo .m { display: block; font-size: 12px; color: var(--green); }
  .sdemo .m.fx { color: var(--red); }
  .sdemo.on { border-color: var(--ink); box-shadow: inset 0 -3px 0 var(--red); }
  .snote { font-size: 12.5px; color: var(--text2); margin: 0 0 10px 0; }
  textarea.ta[readonly] { background: var(--soft); color: var(--text2); cursor: default; }
  @media (max-width: 860px) { .sdemos { grid-template-columns: 1fr; } .sbanner { padding: 8px 18px; } }
"""

# fetch 가로채기: 서버 API 대신 정적 JSON. 상대 경로만 쓴다(Pages 하위 경로).
STATIC_SHIM_JS = r"""
(function () {
  'use strict';
  var ST = window.NEUMANN_STATIC;
  if (!ST || typeof window.fetch !== 'function') return;
  var realFetch = window.fetch.bind(window);
  function norm(t) { return String(t == null ? '' : t).replace(/\r\n?/g, '\n').trim(); }
  function reply(body, status) { return Promise.resolve(new Response(JSON.stringify(body), { status: status || 200, headers: { 'Content-Type': 'application/json; charset=utf-8' } })); }
  function route(input) {
    var raw = typeof input === 'string' ? input : (input && input.url) || '';
    var u; try { u = new URL(raw, document.baseURI); } catch (e) { return null; }
    if (u.origin !== window.location.origin) return null;
    var base = new URL('.', document.baseURI).pathname;
    return (u.pathname.indexOf(base) === 0 ? u.pathname.slice(base.length) : u.pathname).replace(/^\/+/, '');
  }
  window.fetch = function (input, init) {
    var r = route(input);
    var method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    if (r === 'health') return reply(ST.health);
    if (r === 'premortem/view' && method === 'POST') {
      var text = '';
      try { text = JSON.parse((init && init.body) || '{}').plan_text; } catch (e) { text = ''; }
      var d = null;
      for (var i = 0; i < ST.demos.length; i++) { if (norm(ST.demos[i].plan_text) === norm(text)) { d = ST.demos[i]; break; } }
      if (!d) return reply(ST.not_found, 404);
      return realFetch(d.json, { cache: 'no-cache' });
    }
    if (r === 'premortem' || (r && r.indexOf('premortem/') === 0)) return reply(ST.not_found, 404);
    return realFetch(input, init);
  };
})();
"""

# 입력 화면: 직접 입력·파일 업로드 → 데모 3건 선택(본문 읽기 전용). 원본 화면이 다시 그릴 때마다 다시 붙인다.
STATIC_INPUT_JS = r"""
(function () {
  'use strict';
  var ST = window.NEUMANN_STATIC, app = document.getElementById('app');
  if (!ST || !ST.demos || !ST.demos.length || !app) return;
  var sel = 0;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]; }); }
  function fill() {
    var ta = document.getElementById('ta'); if (!ta) return;
    var d = ST.demos[sel];
    if (ta.value !== d.plan_text) { ta.value = d.plan_text; ta.dispatchEvent(new Event('input', { bubbles: true })); }
    Array.prototype.forEach.call(document.querySelectorAll('#demoPicker .sdemo'), function (b) {
      var on = Number(b.getAttribute('data-demo')) === sel; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }
  function decorate() {
    if (document.body.getAttribute('data-view') !== 'input') return;
    var ta = document.getElementById('ta');
    if (!ta) { var t = document.querySelector('#app [data-mode="text"]'); if (t) t.click(); return; }
    if (ta.getAttribute('data-static') === '1') return;
    ta.setAttribute('data-static', '1'); ta.readOnly = true; ta.placeholder = '데모 계획서를 고르세요';
    var picker = document.createElement('div');
    picker.className = 'sdemos'; picker.id = 'demoPicker'; picker.setAttribute('role', 'group'); picker.setAttribute('aria-label', '데모 계획서');
    picker.innerHTML = ST.demos.map(function (d, i) {
      return '<button type="button" class="sdemo" data-demo="' + i + '" aria-pressed="false"><span class="n">DEMO ' + (i + 1) + ' · ' + esc(d.file) + '</span><span class="t">' + esc(d.title) + '</span><span class="m' + (d.kind === 'precomputed' ? '' : ' fx') + '">' + esc(d.badge) + '</span></button>';
    }).join('');
    var seg = document.querySelector('#app .seg');
    if (seg && seg.parentNode) seg.parentNode.replaceChild(picker, seg); else ta.parentNode.insertBefore(picker, ta);
    var note = document.createElement('p'); note.className = 'snote'; note.id = 'staticNote'; note.textContent = ST.input_note;
    ta.parentNode.insertBefore(note, ta);
    picker.addEventListener('click', function (ev) { var b = ev.target.closest('[data-demo]'); if (!b) return; sel = Number(b.getAttribute('data-demo')); fill(); });
    fill();
  }
  new MutationObserver(decorate).observe(app, { childList: true });
  decorate();
})();
"""


def _script_json(obj: Any) -> str:
    """<script> 안에 안전하게 넣는 JSON(</script>·<!-- 차단)."""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace(
        "\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _replace_once(text: str, anchor: str, new: str) -> str:
    n = text.count(anchor)
    if n != 1:
        raise ValueError(f"화면 원본에서 주입 지점 {anchor!r}가 {n}번 나온다(1번이어야 한다). 원본 구조가 바뀌었는지 확인")
    return text.replace(anchor, new, 1)


def inject_static(index_html: str, static: Mapping[str, Any], banner_html: str) -> str:
    out = index_html
    m = re.search(r"<title>(.*?)</title>", out, flags=re.S)
    if m:
        out = out.replace(m.group(0), f"<title>{m.group(1)}{html.escape(SITE_TITLE_SUFFIX)}</title>", 1)
    head = (f'<style id="neumann-static-css">{STATIC_CSS}</style>\n'
            f'<script id="neumann-static-data">window.NEUMANN_STATIC = {_script_json(static)};</script>\n'
            f'<script id="neumann-static-shim">{STATIC_SHIM_JS}</script>\n</head>')
    out = _replace_once(out, "</head>", head)
    out = _replace_once(out, "</header>", "</header>\n" + banner_html)
    out = _replace_once(out, "</body>", f'<script id="neumann-static-input">{STATIC_INPUT_JS}</script>\n</body>')
    return out


def site_label(demos: list[Demo]) -> str:
    n_pre = sum(1 for d in demos if d.kind == "precomputed")
    if n_pre == len(demos):
        return f"정적 판 · 사전 계산본 — {LIVE_NOTE}"
    if n_pre == 0:
        return f"정적 판 · 샘플(가짜 데이터) — {LIVE_NOTE}"
    return f"정적 판 · 사전 계산본 {n_pre}/{len(demos)} · 나머지 샘플 — {LIVE_NOTE}"


def banner_html(demos: list[Demo]) -> str:
    parts = []
    for i, d in enumerate(demos, 1):
        parts.append(f"데모 {i}: " + (f"사전 계산본 {_fmt_time(d.generated_at) or '시각 미기록'} · {d.model}"
                                      if d.kind == "precomputed" else "샘플(가짜 데이터)"))
    text = (f"<b>정적 판</b>미리 계산해 둔 결과만 보여 줍니다 — {LIVE_NOTE}. "
            f"<span>{html.escape(' / '.join(parts))}</span>")
    return f'<div class="sbanner" id="staticBanner" role="note">{text}</div>'


# ───────────────────────── 빌드 ─────────────────────────


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def build_site(
    out_dir: Path,
    *,
    precomputed_dir: Path | None,
    webui_dir: Path = WEBUI_DIR,
    plans_dir: Path = PLANS_DIR,
    demo_names: Iterable[str] = DEMO_PLANS,
    fixture_path: Path = FIXTURE_RESULT,
    build_view: ViewBuilder | None = None,
    validate: Validator | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """정적 사이트를 out_dir에 만든다(임시 폴더에서 만든 뒤 바꿔 끼운다). 빌드 요약을 돌려준다."""
    src_index = webui_dir / "index.html"
    if not src_index.is_file():
        raise FileNotFoundError("화면 원본 index.html이 없다(E4 화면이 main에 병합됐는지 확인)")
    if build_view is None:
        build_view, default_validate = _default_view_tools()
        validate = validate or default_validate
    if out_dir.exists() and any(out_dir.iterdir()) and not (out_dir / BUILD_MARK).is_file() and not force:
        raise FileExistsError(f"{out_dir.name}/ 폴더가 비어 있지 않고 이 빌드가 만든 폴더가 아니다(--force로 덮어쓰기)")

    built_at = datetime.now(UTC).isoformat(timespec="seconds")
    src_bytes = src_index.read_bytes()
    demos = [resolve_demo(d, precomputed_dir, fixture_path) for d in load_demos(plans_dir, demo_names)]

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.build-", dir=out_dir.parent))
    try:
        shutil.copytree(webui_dir, tmp, dirs_exist_ok=True, ignore=shutil.ignore_patterns("index.html", "__pycache__"))
        (tmp / "demo").mkdir()
        entries = []
        for i, d in enumerate(demos, 1):
            view = make_view(d, build_view, validate, built_at)
            raw = json.dumps(view, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            rel = f"demo/{d.demo_id}.json"
            (tmp / rel).write_bytes(raw)
            entries.append({
                "n": i, "id": d.demo_id, "file": d.file, "title": d.title, "plan_text": d.plan_text,
                "plan_id": d.plan_id, "json": rel, "sha256": _sha256_bytes(raw), "kind": d.kind, "origin": d.origin,
                "generated_at": d.generated_at, "generated_kst": _fmt_time(d.generated_at), "model": d.model,
                "label": demo_label(d), "badge": demo_badge(d), "reason": d.reason,
                "cards": len(view.get("cards", [])), "works": len(view.get("works", [])),
            })
        label = site_label(demos)
        static = {
            "version": 1, "built_at": built_at, "live": False, "label": label, "input_note": INPUT_NOTE,
            "demos": entries,
            "health": {
                "status": "ok",
                "version": f"{_neumann_version()} · 정적 판",
                "pipeline": {"state": "unavailable", "reason": "정적 판 — 서버 없음, 사전 계산본만", "mode": "static",
                             "label": label},
                "stages": {},
            },
            "not_found": {"_status": {
                "source": "none", "label": f"정적 판: 데모 {len(entries)}건만 — {LIVE_NOTE}",
                "notices": [f"이 정적 판은 미리 계산한 데모 {len(entries)}건만 보여 준다. 입력한 계획서는 분석하지 않았다."],
            }},
        }
        page = inject_static(src_bytes.decode("utf-8"), static, banner_html(demos))
        (tmp / "index.html").write_text(page, encoding="utf-8", newline="\n")
        index_doc = {k: v for k, v in static.items() if k not in ("health", "not_found")}
        (tmp / "demo" / "index.json").write_text(json.dumps(index_doc, ensure_ascii=False, indent=1), encoding="utf-8")
        (tmp / ".nojekyll").write_text("", encoding="utf-8")  # GitHub Pages가 Jekyll로 가공하지 않게
        summary = {
            "built_at": built_at, "neumann_version": _neumann_version(), "git_commit": _git_commit(),
            "webui_index_sha256": _sha256_bytes(src_bytes), "label": label,
            "demos": [{k: e[k] for k in ("id", "file", "kind", "origin", "generated_at", "model", "sha256", "cards",
                                          "works", "reason")} for e in entries],
        }
        (tmp / BUILD_MARK).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        if src_index.read_bytes() != src_bytes:
            raise RuntimeError("빌드 중 화면 원본이 바뀌었다")
        if out_dir.exists():
            shutil.rmtree(out_dir)
        tmp.rename(out_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return summary


def _neumann_version() -> str:
    try:
        import neumann

        return str(neumann.__version__)
    except Exception:  # noqa: BLE001
        return "?"


# ───────────────────────── 산출물 검사 ─────────────────────────

TEXT_SUFFIXES = {".html", ".htm", ".json", ".js", ".css", ".txt", ".md", ".svg", ".xml", ""}
LOCAL_PATH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Windows 드라이브 경로", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\\\|\\|/)(?!/)")),
    ("UNC 경로", re.compile(r"(?<!\\)\\\\(?:\\\\)?[A-Za-z0-9_.$-]{2,}\\")),
    ("사용자 홈 경로", re.compile(r"(?i)(?:^|[\s\"'(=])/(?:Users|home|root)/[A-Za-z0-9_.-]+")),
    ("file:// 주소", re.compile(r"(?i)\bfile:/")),
    ("로컬 작업 폴더 이름", re.compile(r"(?i)AppData|\.venvs|worktrees|노이만_본선자료")),
]
# 리소스를 부르는 참조(링크 a[href]는 요청이 아니므로 뺀다)
RESOURCE_REF = re.compile(
    r"""<(?:script|img|iframe|source|video|audio|embed|track|input)\b[^>]*?\bsrc\s*=\s*["']?([^"'\s>]+)"""
    r"""|<link\b[^>]*?\bhref\s*=\s*["']?([^"'\s>]+)"""
    r"""|<object\b[^>]*?\bdata\s*=\s*["']?([^"'\s>]+)"""
    r"""|@import\s+(?:url\()?\s*["']?([^"')\s;]+)"""
    r"""|url\(\s*["']?([^"')\s]+)""",
    re.I,
)
JS_REQUEST = re.compile(
    r"""(?:fetch|XMLHttpRequest\(\)\.open|new\s+(?:WebSocket|EventSource|Worker)|sendBeacon|importScripts|import)\s*\(\s*(?:["'][A-Z]+["']\s*,\s*)?["'`]([^"'`]+)["'`]""",
    re.I,
)


def _load_verify():
    spec = importlib.util.spec_from_file_location("_neumann_verify", ROOT / "scripts" / "verify.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _env_names() -> set[str]:
    names = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "HF_TOKEN", "HF_HUB_OFFLINE",
             "TRANSFORMERS_OFFLINE", "PYTHONPATH"}
    try:
        from neumann.config import Settings

        for f in Settings.model_fields.values():
            alias = f.validation_alias
            if isinstance(alias, str):
                names.add(alias)
    except Exception:  # noqa: BLE001
        pass
    example = ROOT / ".env.example"
    if example.is_file():
        for line in example.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*#?\s*([A-Z][A-Z0-9_]{2,})\s*=", line)
            if m:
                names.add(m.group(1))
    return names


def _local_strings() -> list[str]:
    """이 기계의 절대 경로(저장소·데이터·홈). 슬래시 두 방향 모두."""
    vals: set[str] = set()
    for p in (ROOT, ROOT.parent, Path.home()):
        s = str(p)
        if len(s) > 3:
            vals |= {s, s.replace("\\", "/"), s.replace("\\", "\\\\")}
    for name in ("NEUMANN_DATA_DIR", "NEUMANN_RAW_DIR", "NEUMANN_EMBED_MODEL"):
        v = os.environ.get(name, "")
        if len(v) > 3:
            vals |= {v, v.replace("\\", "/"), v.replace("/", "\\")}
    return sorted(vals, key=len, reverse=True)


def _is_external(ref: str) -> bool:
    ref = ref.strip()
    return bool(re.match(r"(?i)^(?:[a-z][a-z0-9+.-]*:)?//", ref)) and not ref.lower().startswith("data:")


def check_site(site: Path, *, expect_demos: int = len(DEMO_PLANS)) -> tuple[list[str], dict[str, Any]]:
    """(문제 목록, 측정값). 문제에는 위치와 종류만 적고 찾은 값은 적지 않는다."""
    problems: list[str] = []
    stats: dict[str, Any] = {"files": 0, "text_files": 0, "bytes": 0, "resource_refs": 0, "demos": 0}
    if not site.is_dir():
        return [f"[필수] 사이트 폴더 없음: {site.name}"], stats

    # 1) 필수 파일
    index = site / "index.html"
    for rel in ("index.html", "demo/index.json", BUILD_MARK, ".nojekyll"):
        if not (site / rel).is_file():
            problems.append(f"[필수] {rel} 없음")
    page = index.read_text(encoding="utf-8") if index.is_file() else ""
    for marker, what in (("window.NEUMANN_STATIC", "정적 데이터 주입"), ('id="neumann-static-shim"', "fetch 가로채기"),
                         ('id="neumann-static-input"', "데모 선택 입력"), ('id="staticBanner"', "정적 판 띠"),
                         (LIVE_NOTE, "라이브 분석 아님 표시")):
        if marker not in page:
            problems.append(f"[필수] index.html에 {what} 없음")
    for font_ref in re.findall(r"""url\(\s*["']?(fonts/[^"')\s]+)""", page):
        if not (site / font_ref).is_file():
            problems.append(f"[필수] 폰트 파일 없음: {font_ref}")
    try:
        idx = json.loads((site / "demo" / "index.json").read_text(encoding="utf-8"))
        demos = idx.get("demos", [])
    except (OSError, ValueError):
        demos = []
        problems.append("[필수] demo/index.json을 읽지 못함")
    stats["demos"] = len(demos)
    if len(demos) != expect_demos:
        problems.append(f"[필수] 데모 {len(demos)}건(기대 {expect_demos}건)")
    for d in demos:
        rel = str(d.get("json", ""))
        path = site / rel
        if not rel.startswith("demo/") or not path.is_file():
            problems.append(f"[필수] 데모 JSON 없음: {rel or d.get('id')}")
            continue
        raw = path.read_bytes()
        if _sha256_bytes(raw) != d.get("sha256"):
            problems.append(f"[필수] {rel}: sha256이 demo/index.json과 다름")
        try:
            view = json.loads(raw.decode("utf-8"))
        except ValueError:
            problems.append(f"[필수] {rel}: JSON 파싱 실패")
            continue
        st = view.get("_status", {}) if isinstance(view, dict) else {}
        if LIVE_NOTE not in str(st.get("label", "")) or st.get("static", {}).get("kind") not in ("precomputed", "fixture"):
            problems.append(f"[필수] {rel}: '{LIVE_NOTE}' 표시 또는 static.kind 없음")
        if not isinstance(view.get("plan"), dict) or not isinstance(view.get("cards"), list):
            problems.append(f"[필수] {rel}: 화면 데이터(plan·cards) 없음")

    # 2) 비밀값·환경변수·로컬 경로 (텍스트 파일 전부)
    verify = _load_verify()
    secrets = verify.load_real_secrets()
    env_names = _env_names()
    env_re = re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(sorted(map(re.escape, env_names), key=len, reverse=True)) + r")(?![A-Za-z0-9_])")
    local = _local_strings()
    for path in sorted(p for p in site.rglob("*") if p.is_file()):
        rel = path.relative_to(site).as_posix()
        data = path.read_bytes()
        stats["files"] += 1
        stats["bytes"] += len(data)
        for name, value in secrets.items():
            if value.encode() in data:
                problems.append(f"[유출] {rel}: 실제 비밀값({name})")
        if path.suffix.lower() not in TEXT_SUFFIXES or b"\0" in data[:8192]:
            continue
        stats["text_files"] += 1
        text = data.decode("utf-8", "replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for kind, pat in verify.SECRET_PATTERNS:
                if pat.search(line):
                    problems.append(f"[비밀값] {rel}:{lineno}: {kind} 형태")
            if env_re.search(line):
                problems.append(f"[환경변수] {rel}:{lineno}: 환경변수 이름")
            for kind, pat in LOCAL_PATH_PATTERNS:
                if pat.search(line):
                    problems.append(f"[내부 경로] {rel}:{lineno}: {kind}")
            if any(s in line for s in local):
                problems.append(f"[내부 경로] {rel}:{lineno}: 이 기계의 절대 경로")

    # 3) 외부 도메인·루트 절대 경로 참조 (HTML·CSS·JS)
    for path in sorted(site.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".html", ".htm", ".css", ".js"}:
            continue
        rel = path.relative_to(site).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in RESOURCE_REF.finditer(text):
            ref = next(g for g in m.groups() if g)
            stats["resource_refs"] += 1
            if ref.lower().startswith(("data:", "#", "about:")):
                continue
            if _is_external(ref):
                problems.append(f"[외부 요청] {rel}: 외부 도메인 리소스 참조")
            elif ref.startswith("/"):
                problems.append(f"[경로] {rel}: 루트 절대 경로 참조(Pages 하위 경로에서 깨짐)")
        for m in JS_REQUEST.finditer(text):
            ref = m.group(1)
            if _is_external(ref) or re.match(r"(?i)^[a-z][a-z0-9+.-]*:", ref) and not ref.lower().startswith("data:"):
                problems.append(f"[외부 요청] {rel}: 스크립트가 외부 주소를 부름")
            elif ref.startswith("/"):
                problems.append(f"[경로] {rel}: 스크립트가 루트 절대 경로를 부름")
    return problems, stats


# ───────────────────────── CLI ─────────────────────────


def _default_data_dir() -> Path:
    try:
        from neumann.config import get_settings

        return Path(get_settings().data_dir)
    except Exception:  # noqa: BLE001
        return ROOT / "data"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=None, help="공유 데이터 폴더(기본: 설정 NEUMANN_DATA_DIR)")
    ap.add_argument("--out", type=Path, default=None, help="산출 폴더(기본: <data>/site)")
    ap.add_argument("--precomputed", type=Path, default=None, help="사전 계산본 폴더(기본: <data>/precomputed)")
    ap.add_argument("--webui", type=Path, default=WEBUI_DIR, help="화면 원본 폴더(기본: src/neumann/webui)")
    ap.add_argument("--force", action="store_true", help="이 빌드가 만들지 않은 산출 폴더도 덮어쓴다")
    ap.add_argument("--check", type=Path, default=None, metavar="SITE", help="빌드하지 않고 검사만")
    args = ap.parse_args(argv)

    if args.check is not None:
        problems, stats = check_site(args.check)
    else:
        data_dir = args.data_dir or _default_data_dir()
        out = args.out or data_dir / "site"
        pre = args.precomputed or data_dir / "precomputed"
        summary = build_site(out, precomputed_dir=pre, webui_dir=args.webui, force=args.force)
        print(f"빌드: {out.name}/ · {summary['label']}")
        for d in summary["demos"]:
            extra = f" · 사유: {d['reason']}" if d["reason"] else ""
            print(f"  - {d['id']}: {d['kind']}({d['origin']}) · 생성 {d['generated_at'] or '-'} · {d['model']} · "
                  f"카드 {d['cards']} · 유사 연구 {d['works']}{extra}")
        problems, stats = check_site(out)
    print(f"검사: 파일 {stats['files']}개({stats['bytes'] / 1024 / 1024:.1f}MB) · 텍스트 {stats['text_files']}개 · "
          f"리소스 참조 {stats['resource_refs']}개 · 데모 {stats['demos']}건")
    if problems:
        print(f"검사 실패 {len(problems)}건:")
        for p in problems:
            print(f"  {p}")
        return 1
    print("검사 통과: 필수 파일·데모 JSON, 비밀값 0, 환경변수 이름 0, 로컬 경로 0, 외부·루트 절대 참조 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
