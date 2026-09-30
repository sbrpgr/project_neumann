"""E5-L0e2e 판정 함수(순수 함수, 서버·브라우저 없이 돈다).

라이브 E2E(`test_live.py`)가 모은 재료를 받아 실패 사유 목록을 돌려준다. 빈 목록이면 통과.
기본 pytest(`test_e2e_checks.py`)가 이 함수들을 fixture로 직접 검사한다(항상 통과하는 검사 금지).

재료
- health: ``GET /health`` JSON
- view: ``POST /premortem/view`` 응답 JSON(ui_view 계약 + ``_status``) — 브라우저가 실제로 받은 것
- dom: 브라우저에서 ``DOM_PROBE_JS``로 읽은 화면 상태
- result: ``POST /premortem`` 응답 JSON(PremortemResult 모양) — 근거 연결 검사용

샘플 모드(파이프라인 미연결)는 어느 재료에서 드러나든 ``SAMPLE_FAIL``로 시작하는 사유로 보고한다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import urlparse

try:  # 화면 문구 원본. 없으면(API 모듈이 없는 브랜치) 같은 문자열을 쓴다.
    from neumann.api.view import SAMPLE_LABEL
except Exception:  # noqa: BLE001
    SAMPLE_LABEL = "분석 파이프라인 미연결(샘플 데이터)"

SAMPLE_FAIL = "파이프라인 미연결(샘플 모드)"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
# index.html의 GEN 표와 같은 문구. 규칙 카드가 LLM 카드처럼 보이면 안 된다.
GEN_LABEL = {
    "astra": "astra 합성",
    "rule": "규칙 합성 · 비상 경로",
    "mock": "mock provider",
    "sample": "샘플 · 분석 결과 아님",
}
DEFAULT_EMPTY_REASONS = {"", "사유 없음", "위험카드 0장 — 결과에 사유가 없다"}

# 브라우저에서 화면 상태를 읽는 스크립트(Playwright page.evaluate). 인용 원문은 길이만 보고 옮기지 않는다.
DOM_PROBE_JS = r"""
() => {
  const q = (s, r) => (r || document).querySelector(s);
  const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : null);
  const cards = Array.from(document.querySelectorAll('#s-cards .rc')).map((c) => {
    const g = q('.gen', c);
    return {
      rank: c.dataset.card || '',
      gen_class: g ? g.className : '',
      gen_text: txt(g) || '',
      ev: Array.from(c.querySelectorAll('.ev')).map((e) => {
        const a = q('a.src', e);
        const qq = q('.q', e);
        return {
          quote_len: qq ? qq.textContent.trim().length : 0,
          href: a ? (a.getAttribute('href') || '') : '',
          no_link_tag: !a,
        };
      }),
    };
  });
  const hdr = q('#hdrState');
  return {
    view: document.body.dataset.view || '',
    ready: document.body.dataset.ready || '',
    cards: cards,
    no_cards: txt(q('#noCards')),
    notice: txt(q('#statusNotice')),
    hdr_class: hdr ? hdr.className : '',
    hdr_text: txt(hdr) || '',
    trace: txt(q('#s-trace')) || '',
    job_state: txt(q('#jobState')),
    job_err: txt(q('#jobErr')),
  };
}
"""


def _st(view: Mapping[str, Any] | None) -> Mapping[str, Any]:
    st = (view or {}).get("_status")
    return st if isinstance(st, Mapping) else {}


# ───────────────────────── 파이프라인 연결 · 샘플 모드 ─────────────────────────


def check_health(health: Mapping[str, Any] | None) -> list[str]:
    """/health가 파이프라인 연결을 보고하는가. 샘플 모드면 SAMPLE_FAIL."""
    if not isinstance(health, Mapping):
        return ["서버 /health 응답 없음"]
    p = health.get("pipeline") or {}
    state, reason = p.get("state"), p.get("reason") or ""
    if state == "connected":
        return []
    if state == "unavailable" or p.get("mode") == "sample":
        return [f"{SAMPLE_FAIL}: /health pipeline.state={state} · {reason} · 화면 표시 '{p.get('label') or SAMPLE_LABEL}'"]
    return [f"파이프라인 오류: /health pipeline.state={state} · {reason}"]


def check_view_status(view: Mapping[str, Any] | None, http_status: int | None = None) -> list[str]:
    """/premortem/view 응답이 실제 파이프라인 결과인가(샘플·오류·계약 위반이면 실패)."""
    if not isinstance(view, Mapping):
        return [f"/premortem/view 응답 JSON 없음(HTTP {http_status})"]
    st = _st(view)
    out: list[str] = []
    if st.get("source") == "sample" or st.get("label") == SAMPLE_LABEL:
        out.append(f"{SAMPLE_FAIL}: /premortem/view _status.source={st.get('source')} · label='{st.get('label')}' "
                   "— 입력한 계획서는 분석되지 않았고 화면 값은 공용 fixture다")
    if st.get("pipeline") not in (None, "connected"):
        out.append(f"/premortem/view _status.pipeline={st.get('pipeline')}")
    if http_status is not None and http_status >= 400:
        out.append(f"/premortem/view HTTP {http_status}: {(st.get('notices') or [''])[0]}")
    if st.get("result_status") == "error":
        out.append(f"분석 결과 status=error: {(st.get('notices') or [''])[0]}")
    if st.get("contract_ok") is False:
        out.append(f"화면 데이터 계약 위반: {st.get('contract_errors')}")
    if st.get("section_errors"):
        out.append(f"화면 데이터 조립 중 깨진 섹션: {st.get('section_errors')}")
    return out


def check_result_json(result: Mapping[str, Any] | None, http_status: int | None = None) -> list[str]:
    """/premortem 결과가 샘플이 아닌 실제 결과인가."""
    if not isinstance(result, Mapping):
        return [f"/premortem 응답 JSON 없음(HTTP {http_status})"]
    out: list[str] = []
    impls = [str((s or {}).get("impl", "")) for s in result.get("stages") or [] if isinstance(s, Mapping)]
    if result.get("sample") is True or "fallback:sample" in impls:
        out.append(f"{SAMPLE_FAIL}: /premortem 결과 sample={result.get('sample')} · stages.impl={impls}")
    if http_status is not None and http_status >= 400:
        out.append(f"/premortem HTTP {http_status}: {result.get('reason') or result.get('detail')}")
    if result.get("status") == "error":
        out.append(f"/premortem status=error: {result.get('reason')}")
    return out


def check_header(dom: Mapping[str, Any]) -> list[str]:
    """헤더 알약이 파이프라인 연결을 표시하는가."""
    cls, text = str(dom.get("hdr_class", "")), str(dom.get("hdr_text", ""))
    if "st-ok" in cls and "파이프라인 연결" in text:
        return []
    if "st-sample" in cls or SAMPLE_LABEL in text:
        return [f"{SAMPLE_FAIL}: 헤더 표시 '{text}'"]
    return [f"헤더가 파이프라인 연결을 표시하지 않는다: class='{cls}' text='{text}'"]


# ───────────────────────── 카드 · 인용 · 원문 링크 ─────────────────────────


def _is_http(url: str) -> bool:
    p = urlparse(url or "")
    return p.scheme in {"http", "https"} and bool(p.netloc)


def check_cards(dom: Mapping[str, Any], view: Mapping[str, Any] | None = None) -> list[str]:
    """데모 계획서: 카드 1장 이상, 카드마다 인용(비어 있지 않음)과 http(s) 원문 링크가 1개 이상."""
    if dom.get("view") != "report":
        return [f"리포트 화면에 도달하지 못했다: view={dom.get('view')} · job={dom.get('job_state')} · {dom.get('job_err') or ''}"]
    cards = list(dom.get("cards") or [])
    out: list[str] = []
    if not cards:
        out.append(f"위험카드 0장: {dom.get('no_cards') or ''}")
    n_view = len((view or {}).get("cards") or []) if isinstance(view, Mapping) else None
    if n_view is not None and n_view != len(cards):
        out.append(f"화면 카드 수 {len(cards)} ≠ 응답 카드 수 {n_view}")
    for c in cards:
        ev = list(c.get("ev") or [])
        rank = c.get("rank")
        if not ev:
            out.append(f"카드 {rank}: 인용 0개")
            continue
        if not any(e.get("quote_len", 0) > 0 for e in ev):
            out.append(f"카드 {rank}: 인용문이 모두 비었다")
        bad = [e.get("href") for e in ev if not _is_http(str(e.get("href") or ""))]
        if bad:
            out.append(f"카드 {rank}: 원문 링크 없음·잘못됨 {len(bad)}/{len(ev)}개")
    return out


def check_generators(dom: Mapping[str, Any], view: Mapping[str, Any] | None) -> list[str]:
    """카드마다 생성 방식이 화면에 표시되고, 응답의 generator와 같다(규칙 카드를 astra로 보이지 않게)."""
    out: list[str] = []
    vcards = {str(c.get("rank")): c for c in (view or {}).get("cards") or [] if isinstance(c, Mapping)}
    for c in dom.get("cards") or []:
        rank = str(c.get("rank"))
        gen = (vcards.get(rank) or {}).get("gen")
        text = str(c.get("gen_text") or "")
        if not text:
            out.append(f"카드 {rank}: 생성 방식 표시 없음")
            continue
        if gen in GEN_LABEL and text != GEN_LABEL[gen]:
            out.append(f"카드 {rank}: generator={gen}인데 화면 표시 '{text}'")
    return out


def check_degradation(dom: Mapping[str, Any], view: Mapping[str, Any] | None) -> list[str]:
    """강등·오류 단계가 화면에 표시되는가.

    - ``_status.stages_not_ok``의 단계마다 상단 안내(#statusNotice)에 ``phase · name · status``가 있다(샘플 제외)
    - ``_status.degraded``면 안내 상자와 라벨이 있다
    - 추적(V) 섹션 Stages에 응답 ``pipeline``의 단계 이름이 모두 있다
    """
    if dom.get("view") != "report":
        return []  # 리포트가 없으면 check_cards가 이미 실패로 보고한다
    st = _st(view)
    notice = str(dom.get("notice") or "")
    out: list[str] = []
    if st.get("degraded") and st.get("label") and st.get("label") not in notice:
        out.append(f"강등 결과인데 상단 안내에 라벨 '{st.get('label')}'이 없다")
    if st.get("source") != "sample":
        for s in st.get("stages_not_ok") or []:
            key = f"{s.get('phase')} · {s.get('name')} · {s.get('status')}"
            if key not in notice:
                out.append(f"강등 단계가 화면에 없다: {key}")
    trace = str(dom.get("trace") or "")
    for p in (view or {}).get("pipeline") or []:
        if str(p.get("k")) not in trace:
            out.append(f"추적 섹션에 단계 {p.get('k')} 표시 없음")
    return out


# ───────────────────────── 범위 밖 입력 ─────────────────────────


def check_negative(dom: Mapping[str, Any], view: Mapping[str, Any] | None, http_status: int | None) -> list[str]:
    """범위 밖 입력: (a) 리포트에 카드 0장 + 기본값이 아닌 사유, 또는 (b) 4xx 부적합 판정 + 사유.

    500(파이프라인 실행 실패)은 부적합 판정이 아니다.
    """
    st = _st(view)
    if dom.get("view") == "report":
        cards = list(dom.get("cards") or [])
        if cards:
            return [f"범위 밖 입력인데 위험카드 {len(cards)}장이 나왔다"]
        reason = str(st.get("empty_reason") or "").strip()
        if reason in DEFAULT_EMPTY_REASONS:
            return [f"카드 0장이지만 사유가 없다(empty_reason='{reason}')"]
        if not dom.get("no_cards") or reason not in str(dom.get("no_cards")):
            return [f"카드 0장 사유가 화면(#noCards)에 없다: '{dom.get('no_cards')}'"]
        return []
    if http_status is not None and 400 <= http_status < 500:
        why = (st.get("notices") or [None])[0] or dom.get("job_err")
        return [] if why else [f"부적합 판정(HTTP {http_status})인데 사유가 없다"]
    return [f"범위 밖 입력 처리 실패: view={dom.get('view')} · HTTP {http_status} · {dom.get('job_err') or ''}"]


# ───────────────────────── 브라우저 위생 ─────────────────────────


def is_external(url: str, base_url: str) -> bool:
    """브라우저 요청이 외부로 나가는가. data:·blob:·about:은 내부, 로컬 호스트(서버 자신 포함)는 내부."""
    p = urlparse(url)
    if p.scheme in {"data", "blob", "about", "chrome", "chrome-extension"}:
        return False
    host = (p.hostname or "").lower()
    base_host = (urlparse(base_url).hostname or "").lower()
    return not (host == base_host or host in LOCAL_HOSTS)


def check_browser(console_errors: Iterable[str], page_errors: Iterable[str], external: Iterable[str],
                  failed: Iterable[str]) -> list[str]:
    out: list[str] = []
    for name, items in (("콘솔 오류", console_errors), ("페이지 오류", page_errors),
                        ("외부 요청", external), ("실패한 요청", failed)):
        items = list(items)
        if items:
            out.append(f"{name} {len(items)}건: {items[:5]}")
    return out


# ───────────────────────── 근거 연결 ─────────────────────────


def check_linkage(result: Mapping[str, Any], source_lookup: Callable[[str], Any] | Mapping[str, Any]
                  ) -> tuple[list[str], dict[str, Any]]:
    """eval.linkage.check_result로 근거 연결률 1.0을 확인한다. (실패 사유, 요약)"""
    from eval.linkage import check_result

    rep = check_result(result, source_lookup)
    info = {
        "summary": rep.summary(), "verdict": rep.verdict, "linkage_rate": rep.linkage_rate,
        "links": f"{rep.links_ok}/{rep.links_total}", "cards": f"{rep.cards_ok}/{rep.cards_total}",
        "reason_counts": dict(rep.reason_counts), "contract_valid": rep.contract_valid,
    }
    out: list[str] = []
    if rep.linkage_rate != 1.0 or rep.verdict != "pass":
        out.append(f"근거 연결률 {rep.linkage_rate} (verdict={rep.verdict}) · {dict(rep.reason_counts)} · "
                   f"첫 실패 {[f.model_dump() for f in rep.failures[:3]]}")
    return out, info


# ───────────────────────── 시간 ─────────────────────────


def stage_timings(view: Mapping[str, Any] | None, result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """화면 응답의 단계별(phase) ms와 결과 JSON의 단계별 elapsed_s를 모은다."""
    out: dict[str, Any] = {
        "view_phase_s": {str(p.get("k")): round((p.get("ms") or 0) / 1000, 3)
                         for p in (view or {}).get("pipeline") or [] if isinstance(p, Mapping)},
        "view_server_elapsed_s": _st(view).get("server_elapsed_s"),
        "view_pipeline_total_s": ((view or {}).get("kpi") or {}).get("elapsed_s") if isinstance(view, Mapping) else None,
    }
    if isinstance(result, Mapping):
        out["result_stage_s"] = {f"{s.get('phase')}/{s.get('name')}": s.get("elapsed_s")
                                 for s in result.get("stages") or [] if isinstance(s, Mapping)}
    return out
