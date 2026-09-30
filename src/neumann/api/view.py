"""분석 결과(PremortemResult 모양) → 화면 데이터 계약(`contracts/ui_view.schema.json`).

공개 함수는 둘이다.

- ``build_ui_view(result, ...)``: 예외를 던지지 않는다. 빠진 부분은 빈 값으로 채우고 사정은 ``_status``에 적는다.
- ``validate_ui_view(view)``: 계약 위반 목록(빈 목록이면 통과). jsonschema Draft-07.

입력 형식은 ``docs/reports/E4-L0.md`` "build_ui_view 입력 형식"에 적었다. 요약:
``plan_stats.lines``(줄 번호), ``similar_works``, ``evidence``(발췌 id·원문에서 잘라낸 ``text``·``source_url``),
``risk_cards``(``evidence``는 발췌 id 목록, ``generator``는 astra|rule|mock), ``expected_review``, ``checklist``,
``stages``(StageReport), ``status``, ``notices``, ``manifest``. pydantic 모델도 받는다(``model_dump``).

정직성 규칙(AGENTS.md):
- 근거가 하나도 연결되지 않는 카드와 예상 심사평 문장은 화면에 내보내지 않고 ``_status``에 개수를 남긴다.
- 인용문은 결과의 ``text``를 그대로 쓴다. 이 모듈은 문장을 만들지 않는다.
- 생성 방식(``generator``)과 강등 단계는 그대로 화면까지 전달한다.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
import sys
import uuid
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "ui_view.schema.json"

SAMPLE_LABEL = "분석 파이프라인 미연결(샘플 데이터)"
ERROR_LABEL = "분석 실패"

# 택소노미 v1 최상위 유형(부록/설계/03_risk_taxonomy.md). (이름, 지도 열 이름)
TAXONOMY: dict[str, tuple[str, str]] = {
    "R0": ("서술 · 표현", "서술"),
    "R1": ("주장-증거 정합성", "주장"),
    "R2": ("실험 설계 · 평가 프로토콜", "평가"),
    "R3": ("데이터 누출 · 분할 오염", "누출"),
    "R4": ("데이터 품질 · 대표성", "데이터"),
    "R5": ("재현성 · 연구산출물", "재현"),
    "R6": ("신규성 · 선행연구 위치", "신규성"),
    "R7": ("일반화 · 적용범위", "일반화"),
    "R8": ("도메인 실증 · 물리적 타당성", "도메인"),
    "R9": ("연구윤리 · 사후 위험", "윤리"),
}

GENERATORS = {"astra", "rule", "mock", "sample"}
# 생성 방식 표시 이름(DISP-1, decisions 2026-09-30 21:5x). 계약 값 ``astra``는 "제품 LLM"이라는 이름일 뿐 모델이 아니다.
# 저장 값(``generator: "astra"``)은 그대로 두고, 사람이 보는 화면·ZIP 문서·리포트 카드만 이 함수를 거친다
# (``neumann.api.export``·``eval.report_card``도 여기서 가져다 쓴다).
# astra는 여기 없다: 모델명을 붙여 display_generator가 "LLM (모델명)"으로 만든다.
GENERATOR_DISPLAY = {"rule": "비상 규칙", "mock": "모의(mock)", "sample": "샘플 · 분석 결과 아님"}
UNKNOWN_GENERATOR_LABEL = "생성 방식 미표기"
# 계약 이름으로 쓴 astra만 잡는다. 모델명 안의 astra(gpt-6-astra 등)는 실제 모델 이름이라 건드리지 않는다.
# 바로 뒤에 붙은 조사도 잡아 받침에 맞게 바꾼다(astra가 → LLM이, astra는 → LLM은).
_CONTRACT_ASTRA = re.compile(r"(?<![A-Za-z0-9_.\-])astra(?![A-Za-z0-9_\-])([가는를와로라나랑])?", re.IGNORECASE)
_JOSA_AFTER_LLM = {"가": "이", "는": "은", "를": "을", "와": "과", "로": "으로", "라": "이라", "나": "이나", "랑": "이랑"}


def display_generator(generator: Any, model: Any = None) -> str:
    """생성 방식(계약 값) → 사람이 보는 이름. ``astra`` → "LLM (모델명)"(모델명이 없으면 "LLM").

    ``rule`` → "비상 규칙", ``mock`` → "모의(mock)". 규칙·mock에는 모델명을 붙이지 않는다(LLM 결과로 보이지 않게).
    모르는 값은 추정하지 않고 그 값을 보인다. 모델명은 고치지 않는다(실제 모델이 astra 계열이면 그 이름이 보인다).
    """
    g = _text(generator).strip()
    key = g.lower()
    if key == "astra":
        m = _text(model).strip()
        return f"LLM ({m})" if m else "LLM"
    if key in GENERATOR_DISPLAY:
        return GENERATOR_DISPLAY[key]
    if not key or key == "unknown":
        return UNKNOWN_GENERATOR_LABEL
    return display_text(g)


def display_text(text: Any) -> str:
    """사람이 보는 자유 문구(알림·단계 사유)에서 계약 이름 ``astra``만 "LLM"으로 바꾼다. 인용·계획서 줄에는 쓰지 않는다."""
    return _CONTRACT_ASTRA.sub(lambda m: "LLM" + _JOSA_AFTER_LLM.get(m.group(1) or "", ""), _text(text))


# DecisionOutcome(models.py) → 화면 라벨. 원문 문자열(outcome_raw)보다 먼저 본다.
OUTCOME_LABEL = {
    "accept_oral": "Oral", "accept_spotlight": "Spotlight", "accept_poster": "Poster", "accept": "채택",
    "major_revision": "대폭 수정", "minor_revision": "소폭 수정",
    "reject_resubmit": "거절", "reject": "거절", "desk_reject": "거절",
    "withdrawn": "철회", "no_binary_decision": "미정", "unknown": "미정",
}
ACCEPT_LABELS = {"채택", "Oral", "Spotlight", "Poster"}
REVISION_LABELS = {"대폭 수정", "소폭 수정"}
RATING_NUM = re.compile(r"^\s*(\d+(?:\.\d+)?)")
STAGE_STATUS_KO = {
    "ok": "정상", "degraded": "강등", "empty": "결과 없음", "unavailable": "미연결",
    "error": "오류", "skipped": "건너뜀",
}
SOURCE_KIND_KO = {
    "review": "심사평", "author_response": "저자 답변", "decision": "결정문", "post_status": "사후 기록",
}
REJECT_LABEL = "거절"
NEUTRAL_DECISIONS = {"미정", "철회"}
PSEUDONYM = re.compile(r"^rvw_[0-9a-f]{16}$")


# ───────────────────────── 작은 도구 ─────────────────────────


def _as_dict(obj: Any) -> dict[str, Any]:
    """pydantic 모델·dataclass·Mapping → dict. 그 밖은 빈 dict."""
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            out = dump(mode="json")
            return dict(out) if isinstance(out, Mapping) else {}
        except Exception:  # noqa: BLE001 - 모양이 이상한 모델도 빈 값으로
            return {}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        try:
            return dataclasses.asdict(obj)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _list(obj: Any) -> list[Any]:
    if obj is None or isinstance(obj, (str, bytes, Mapping)):
        return []
    if isinstance(obj, Iterable):
        return list(obj)
    return []


def _get(d: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return default


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return str(v)
    return ""


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and math.isfinite(v) and v == int(v):
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    return None


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        return float(v)
    if isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


def _code(v: Any) -> str:
    """'R3', 'R3.1', 'r2' → 'R3', 'R3', 'R2'. 모르는 값은 ''."""
    m = re.match(r"^\s*[Rr](\d)", _text(v))
    return f"R{m.group(1)}" if m else ""


def decision_label(raw: Any) -> str:
    """결정 문자열 → 화면 라벨. 거절 · Oral · Spotlight · Poster · 채택 · 철회 · 미정."""
    s = _text(raw).strip()
    low = s.lower()
    if not s or low in {"unknown", "none", "null", "n/a", "pending"}:
        return "미정"
    if s in {REJECT_LABEL, "채택", "미정", "철회"}:
        return s
    if low in OUTCOME_LABEL:
        return OUTCOME_LABEL[low]
    if "withdraw" in low:
        return "철회"
    if "reject" in low or "desk" in low:
        return REJECT_LABEL
    if "revision" in low:
        return "소폭 수정" if "minor" in low else "대폭 수정"
    for key, label in (("oral", "Oral"), ("spotlight", "Spotlight"), ("poster", "Poster")):
        if key in low:
            return label
    if "accept" in low:
        return "채택"
    return s[:24]


def _short_title(title: str) -> str:
    if ":" in title:
        head = title.split(":", 1)[0].strip()
        if 3 <= len(head) <= 40:
            return head
    return title if len(title) <= 48 else title[:47].rstrip() + "…"


def _rating(v: Any) -> str:
    f = _num(v)
    if f is None:
        return _text(v)[:8]
    return f"{f:.2f}" if f != int(f) else f"{int(f)}"


def _size_label(n_bytes: int) -> str:
    return f"{n_bytes / 1024:.1f} KB" if n_bytes >= 1024 else f"{n_bytes} B"


def rating_value(v: Any) -> float | None:
    """평점 원문('6: marginally above …', '5', 6.0) → 앞의 숫자. 숫자가 없으면 None."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) if math.isfinite(float(v)) else None
    m = RATING_NUM.match(_text(v))
    return float(m.group(1)) if m else None


# ───────────────────────── 코퍼스 기록 조회(결정·평점) ─────────────────────────


@dataclasses.dataclass
class RecordLookup:
    """분석 결과에 없는 논문 결정·심사평 평점을 코퍼스 기록(Work·ReviewEvent·Decision)에서 찾는다.

    ``PremortemResult.similar_works``·``Excerpt``에는 결정·평점·논문 id가 없다(계약). 화면은 이것을 지어내지 않고
    기록에서 **원문 그대로** 가져온다. 결과에 값이 있으면 결과가 이긴다. 못 찾으면 비워 둔다("미정", "–").
    """

    decisions: dict[str, tuple[str, str]] = dataclasses.field(default_factory=dict)  # work_id → (라벨, 원문)
    ratings: dict[str, list[float]] = dataclasses.field(default_factory=dict)  # work_id → 공식 심사평 평점
    reviews: dict[str, tuple[str, str]] = dataclasses.field(default_factory=dict)  # review_id → (work_id, 평점 원문)
    decision_work: dict[str, str] = dataclasses.field(default_factory=dict)  # decision_id → work_id
    works: dict[str, dict[str, str]] = dataclasses.field(default_factory=dict)  # work_id → title·url·venue
    source: str = "records"

    @classmethod
    def from_records(cls, works: Iterable[Any] = (), reviews: Iterable[Any] = (), decisions: Iterable[Any] = (),
                     *, source: str = "records") -> RecordLookup:
        """Work·ReviewEvent·Decision(모델 또는 dict) 목록으로 만든다."""
        lk = cls(source=source)
        for raw in works:
            w = _as_dict(raw)
            wid = _text(w.get("work_id"))
            if wid:
                lk.works[wid] = {"title": _text(w.get("title")), "url": _text(w.get("url")),
                                 "venue": _text(w.get("venue"))}
        for raw in reviews:
            lk.add_review(_as_dict(raw))
        for raw in decisions:
            lk.add_decision(_as_dict(raw))
        return lk

    def add_review(self, r: Mapping[str, Any]) -> None:
        rid, wid = _text(r.get("review_id")), _text(r.get("work_id"))
        if not rid or not wid:
            return
        kind = _text(r.get("kind")) or "official_review"
        raw = _text(r.get("rating"))
        self.reviews[rid] = (wid, raw)
        v = rating_value(raw)
        if kind == "official_review" and v is not None:
            self.ratings.setdefault(wid, []).append(v)

    def add_decision(self, d: Mapping[str, Any]) -> None:
        wid = _text(d.get("work_id"))
        if not wid:
            return
        outcome, raw = _text(d.get("outcome")).lower(), _text(d.get("outcome_raw"))
        label = OUTCOME_LABEL.get(outcome) or decision_label(raw)
        self.decisions[wid] = (label, raw)
        did = _text(d.get("decision_id"))
        if did:
            self.decision_work[did] = wid

    def __bool__(self) -> bool:
        return bool(self.decisions or self.reviews or self.works)

    def work_of_source(self, source_id: str) -> str:
        if source_id in self.reviews:
            return self.reviews[source_id][0]
        return self.decision_work.get(source_id, "")

    def review_rating(self, source_id: str) -> str:
        return self.reviews.get(source_id, ("", ""))[1]


AUTO: Any = object()  # build_ui_view(records=AUTO): 공유 데이터 폴더의 기록을 쓴다(샘플이면 쓰지 않는다)
_RECORD_FILES = ("processed/decisions.jsonl", "processed/elife_decisions.jsonl", "processed_l3/decisions.jsonl")


def _iter_json_lines(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield row


def _data_dir() -> Path | None:
    try:
        from neumann.config import get_settings

        return Path(get_settings().data_dir)
    except Exception:  # noqa: BLE001 - 설정을 못 읽으면 조회 없이 간다
        return None


@lru_cache(maxsize=2)
def _load_records(data_dir: str, stamp: tuple[float, ...]) -> RecordLookup | None:  # noqa: ARG001 - stamp는 캐시 키
    """공유 데이터 폴더 → RecordLookup. 이미 메모리에 올라온 색인(neumann.index.store)이 있으면 그것을 쓴다."""
    base = Path(data_dir)
    lk = RecordLookup(source="corpus_records")
    store = getattr(sys.modules.get("neumann.index.store"), "_STORE", None)
    if store is not None and getattr(store, "works", None):
        for wid, w in store.works.items():
            lk.works[wid] = {"title": _text(getattr(w, "title", "")), "url": _text(getattr(w, "url", "")),
                             "venue": _text(getattr(w, "venue", ""))}
        for revs in store.reviews.values():
            for r in revs:
                lk.add_review(_as_dict(r))
    else:
        for name in ("works.jsonl", "reviews.jsonl"):
            p = base / "index" / name
            if not p.is_file():
                continue
            for row in _iter_json_lines(p):
                if name == "works.jsonl":
                    wid = _text(row.get("work_id"))
                    if wid:
                        lk.works[wid] = {"title": _text(row.get("title")), "url": _text(row.get("url")),
                                         "venue": _text(row.get("venue"))}
                else:
                    lk.add_review(row)
    for rel in _RECORD_FILES:
        p = base / rel
        if p.is_file():
            for row in _iter_json_lines(p):
                lk.add_decision(row)
    return lk or None


def default_records() -> RecordLookup | None:
    """공유 데이터 폴더의 결정·평점 기록. 폴더·파일이 없으면 None(화면은 '미정'·'–'로 둔다)."""
    base = _data_dir()
    if base is None or not base.is_dir():
        return None
    paths = [base / "index" / "works.jsonl", base / "index" / "reviews.jsonl", *(base / r for r in _RECORD_FILES)]
    stamp = tuple(p.stat().st_mtime if p.is_file() else 0.0 for p in paths)
    if not any(stamp):
        return None
    try:
        return _load_records(str(base), stamp)
    except Exception:  # noqa: BLE001 - 조회 실패는 화면을 막지 않는다
        return None


# ───────────────────────── 섹션별 조립 ─────────────────────────


class _Ctx:
    """섹션 사이에 공유하는 조회표와 기록."""

    def __init__(self, records: RecordLookup | None = None) -> None:
        self.records = records
        self.enriched: dict[str, int] = {}  # 기록에서 채운 값의 개수(추적용)
        self.ev_lines: dict[str, list[int]] = {}  # 발췌 id → 그 발췌를 인용한 카드들의 계획서 줄(순서 유지)
        self.ev_cards: dict[str, list[int]] = {}  # 발췌 id → 인용한 카드 순위
        self.card_rank: dict[str, int] = {}  # card_id → 화면 순위
        self.works_by_id: dict[str, dict[str, Any]] = {}
        self.work_n: dict[str, int] = {}
        self.evidence: dict[str, dict[str, Any]] = {}
        self.ev_num: dict[str, int] = {}
        self.fams: list[dict[str, str]] = []
        self.fam_index: dict[tuple[str, str], int] = {}
        self.plan_line_ns: set[int] = set()
        self.ev_work: dict[str, str] = {}  # 발췌 id → 논문 id(명시 필드 > URL 대조 > 카드의 유일한 논문)
        self.ev_line: dict[str, int] = {}  # 발췌 id → 계획서 줄(명시 필드가 없으면 인용한 카드의 첫 줄)
        self.section_errors: dict[str, str] = {}
        self.dropped: dict[str, int] = {}

    def drop(self, what: str, n: int = 1) -> None:
        self.dropped[what] = self.dropped.get(what, 0) + n

    def enrich(self, what: str) -> None:
        self.enriched[what] = self.enriched.get(what, 0) + 1

    def fam_for(self, code: str, sub: str = "", title: str = "") -> int:
        code = code or _code(sub) or "R?"
        k = sub or code
        name = title or TAXONOMY.get(code, (k, k))[0]
        key = (k, name)
        if key not in self.fam_index:
            col = TAXONOMY.get(code, (k, k))[1]
            self.fam_index[key] = len(self.fams)
            self.fams.append({"k": k, "n": name, "col": col})
        return self.fam_index[key]

    def fam_for_code(self, code: str) -> int:
        for i, f in enumerate(self.fams):
            if _code(f["k"]) == code:
                return i
        return self.fam_for(code)


MD_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+\S")


def _build_plan(res: Mapping[str, Any], filename: str | None, ctx: _Ctx) -> dict[str, Any]:
    """계획서 줄. 줄 번호는 결과의 번호를 그대로 쓴다(카드가 그 번호를 가리킨다). 빈 줄은 화면에서 뺀다."""
    ps = _as_dict(res.get("plan_stats"))
    plan = _as_dict(res.get("plan"))
    raw_lines = _list(ps.get("lines")) or _list(plan.get("lines")) or _list(res.get("lines"))
    lines: list[dict[str, Any]] = []
    seen: set[int] = set()
    has_title = False
    for i, raw in enumerate(raw_lines, 1):
        if isinstance(raw, str):
            n, t, h = i, raw, None
        else:
            d = _as_dict(raw)
            if not d:
                ctx.drop("plan_lines")
                continue
            n = _int(_get(d, "n", "no", "line_no", "line", "number"))
            n = i if n is None else n
            t = _text(_get(d, "t", "text", "content", default=""))
            h = _get(d, "h", "kind", "heading")
        if n < 1 or n in seen:
            ctx.drop("plan_lines")
            continue
        seen.add(n)
        if not t.strip():
            continue  # 빈 줄: 번호는 유지하되 화면 목록에는 싣지 않는다
        item: dict[str, Any] = {"n": n, "t": t}
        hv = _text(h).lower() if not isinstance(h, bool) else ("h" if h else "")
        md = MD_HEADING.match(t)
        if hv == "title" or (not hv and md and len(md.group(1)) == 1 and not has_title):
            item["h"] = "title"
            has_title = True
        elif hv in {"h", "heading", "h1", "h2", "h3", "h4", "h5", "h6", "section"} or (not hv and md):
            item["h"] = "h"
        lines.append(item)
    ctx.plan_line_ns = {line["n"] for line in lines}
    body = "\n".join(line["t"] for line in lines)
    n_bytes = _int(_get(ps, "size_bytes", "bytes")) or len(body.encode("utf-8"))
    title = _text(_get(ps, "title"))
    if not title:
        first = next((line["t"] for line in lines if line.get("h") == "title"), "") or (lines[0]["t"] if lines else "")
        title = first.strip().lstrip("#").strip()
    file = filename or _text(_get(ps, "file", "filename")) or ("직접 입력" if lines else "")
    meta = f"정규화 {len(lines)}줄" if lines else "계획서 줄 없음"
    return {"file": file, "size": _size_label(n_bytes), "meta": meta, "title": title, "lines": lines}


def _build_works(res: Mapping[str, Any], ctx: _Ctx) -> list[dict[str, Any]]:
    works: list[dict[str, Any]] = []
    for raw in _list(_get(res, "similar_works", "works")):
        w = _as_dict(raw)
        wid = _text(_get(w, "work_id", "id", "forum_id", "paper_id"))
        title = _text(_get(w, "title", "t"))
        if not wid or wid in ctx.work_n:
            ctx.drop("works")
            continue
        n = len(works) + 1
        rec = ctx.records
        known = (rec.works.get(wid) if rec else None) or {}
        title = title or known.get("title", "") or wid
        prov = _as_dict(w.get("provenance"))
        url = _text(_get(w, "url", "forum_url", "source_url")) or _text(prov.get("source_url")) or known.get("url", "")
        raw_dec = _get(w, "decision", "decision_label", "d")
        dec, d_raw, d_src = decision_label(raw_dec), _text(raw_dec), "result" if raw_dec is not None else ""
        if raw_dec is None and rec and wid in rec.decisions:
            dec, d_raw = rec.decisions[wid]
            d_src = rec.source
            ctx.enrich("works_decision")
        raw_rt = _get(w, "rating", "avg_rating", "mean_rating", "r")
        rs = [round(v, 2) for v in (rec.ratings.get(wid, []) if rec else [])]
        if raw_rt is None and rs:
            raw_rt = sum(rs) / len(rs)
            ctx.enrich("works_rating")
        item = {
            "n": n,
            "t": title,
            "s": _text(_get(w, "short_title", "s")) or _short_title(title),
            "d": dec,
            "r": _rating(raw_rt) or "–",
            "id": wid,
            "f": [],
            "u": url,
            "venue": _text(_get(w, "venue")) or known.get("venue", ""),
        }
        if d_raw:
            item["draw"] = d_raw[:80]  # 결정 원문 문자열(라벨을 만든 근거)
        if d_src:
            item["dsrc"] = d_src
        if rs:
            item["rs"] = rs  # 공식 심사평 평점 하나하나(평가 분포)
        sim = _num(_get(w, "similarity", "score"))
        if sim is not None:
            item["sim"] = round(sim, 4)
        works.append(item)
        ctx.works_by_id[wid] = item
        ctx.work_n[wid] = n
    return works


def _collect_evidence(res: Mapping[str, Any], ctx: _Ctx) -> None:
    for raw in _list(_get(res, "evidence", "excerpts")):
        e = _as_dict(raw)
        eid = _text(_get(e, "excerpt_id", "id", "eid"))
        if eid and _text(_get(e, "text", "quote", "q")):
            ctx.evidence.setdefault(eid, e)
        else:
            ctx.drop("evidence")


def _ev_refs(refs: Any, ctx: _Ctx) -> list[str]:
    """카드·문장이 가리키는 발췌 id 목록. dict로 들어온 발췌는 조회표에 등록한다."""
    out: list[str] = []
    for r in _list(refs):
        if isinstance(r, str):
            eid = r
        else:
            d = _as_dict(r)
            eid = _text(_get(d, "excerpt_id", "id", "eid"))
            if eid and _text(_get(d, "text", "quote", "q")):
                ctx.evidence.setdefault(eid, d)
        if eid and eid not in out:
            out.append(eid)
    return out


def _same_page(url: str, work_url: str) -> bool:
    """근거 URL(심사평 딥링크)이 논문 랜딩 페이지를 가리키는지. 같은 host·path에 같은 id 파라미터, 또는 접두어."""
    if not url or not work_url:
        return False
    if url == work_url or url.startswith(work_url.rstrip("/") + "/") or url.startswith(work_url + "&") \
            or url.startswith(work_url + "#"):
        return True
    a, b = urlparse(url), urlparse(work_url)
    if (a.netloc, a.path) != (b.netloc, b.path):
        return False
    ida, idb = parse_qs(a.query).get("id"), parse_qs(b.query).get("id")
    return bool(ida and ida == idb)


def _resolve_work(e: Mapping[str, Any], ctx: _Ctx) -> str:
    """발췌 → 논문 id. 명시 필드(work_id)가 없으면 원문 URL로 유사 연구 목록과 맞춘다. 못 찾으면 ''."""
    wid = _text(_get(e, "work_id", "paper_id", "forum_id"))
    if wid:
        return wid
    if ctx.records:  # 발췌의 원문(source_id = review_id·decision_id) → 그 기록의 논문
        wid = ctx.records.work_of_source(_text(e.get("source_id")))
        if wid:
            return wid
    url = _text(_get(e, "source_url", "url"))
    for w in ctx.works_by_id.values():
        if _same_page(url, w.get("u", "")):
            return w["id"]
    return ""


def _number_ev(eid: str, ctx: _Ctx) -> int | None:
    if eid not in ctx.evidence:
        return None
    if eid not in ctx.ev_num:
        ctx.ev_num[eid] = len(ctx.ev_num) + 1
    return ctx.ev_num[eid]


def _card_plan_lines(c: Mapping[str, Any], ctx: _Ctx) -> tuple[list[int], str]:
    why = c.get("why_applies")
    lines_raw: Any = _get(c, "plan_lines", "lines")
    text = _text(_get(c, "description", "desc", "why", "summary", "rationale"))
    if isinstance(why, str):
        text = text or why
    elif why is not None:
        wd = _as_dict(why) if not isinstance(why, list) else {"plan_lines": why}
        lines_raw = lines_raw if lines_raw is not None else _get(wd, "plan_lines", "lines", "line_numbers")
        text = text or _text(_get(wd, "text", "reason", "summary"))
    lines: list[int] = []
    for v in _list(lines_raw):
        n = _int(v)
        if n is not None and n in ctx.plan_line_ns and n not in lines:
            lines.append(n)
        else:
            ctx.drop("card_plan_lines")
    return lines, text


def _severity(c: Mapping[str, Any], score: Mapping[str, Any]) -> int:
    raw = _get(c, "severity", "sev")
    if isinstance(raw, str):
        m = re.search(r"\d", raw)
        raw = int(m.group(0)) if m else None
    v = _num(raw)
    if v is None:
        v = _num(score.get("severity"))
        if v is not None and v <= 1:
            v = v * 5
    if v is None:
        return 3
    if 0 < v <= 1 and not float(v).is_integer():
        v = v * 5
    return int(min(5, max(1, round(v))))


def _build_cards(res: Mapping[str, Any], works: list[dict[str, Any]], ctx: _Ctx) -> list[dict[str, Any]]:
    raw_cards = [_as_dict(c) for c in _list(_get(res, "risk_cards", "cards"))]
    raw_cards = [c for c in raw_cards if c]
    if any(_int(c.get("rank")) is not None for c in raw_cards):
        raw_cards.sort(key=lambda c: (_int(c.get("rank")) is None, _int(c.get("rank")) or 0))
    n_similar = len(works)
    reject_ids = {w["id"] for w in works if w["d"] == REJECT_LABEL}
    decisions_known = any(w["d"] not in NEUTRAL_DECISIONS for w in works)
    cards: list[dict[str, Any]] = []
    for c in raw_cards:
        eids = [e for e in _ev_refs(_get(c, "evidence", "evidence_ids", "excerpt_ids", "ev"), ctx) if e in ctx.evidence]
        if not eids:
            ctx.drop("cards_without_evidence")
            continue
        code = _code(_get(c, "risk_code", "code", "subcode", "fam"))
        fam = ctx.fam_for(code, _text(_get(c, "subcode")), _text(_get(c, "title", "name")))
        score = _as_dict(c.get("score")) if not isinstance(c.get("score"), (int, float, str)) else {"total": c.get("score")}
        total = _num(_get(score, "total", "value"))
        comp = [[label, round(v, 4)] for label, key in
                (("유사도", "similarity"), ("빈도", "frequency"), ("심각도", "severity"), ("신뢰도", "confidence"))
                if (v := _num(score.get(key))) is not None]
        lines, desc = _card_plan_lines(c, ctx)
        ev_nums = [n for e in eids if (n := _number_ev(e, ctx)) is not None]
        listed_works = [w for w in dict.fromkeys(_text(w) for w in _list(_get(c, "works", "work_ids",
                                                                                "supporting_work_ids"))) if w]
        for e in eids:
            if e not in ctx.ev_work:
                wid = _resolve_work(ctx.evidence[e], ctx) or (listed_works[0] if len(listed_works) == 1 else "")
                if not wid:  # 카드의 논문 id와 원문 URL의 id 파라미터가 같으면 그 논문(제목은 모른다)
                    ids = parse_qs(urlparse(_text(ctx.evidence[e].get("source_url"))).query).get("id") or []
                    wid = next((w for w in listed_works for i in ids
                                if w == i or w.endswith(":" + i) or w.endswith("/" + i)), "")
                ctx.ev_work[e] = wid
            if lines and e not in ctx.ev_line:
                ctx.ev_line[e] = lines[0]
            ev_ls = ctx.ev_lines.setdefault(e, [])
            ev_ls.extend(n for n in lines if n not in ev_ls)
            ctx.ev_cards.setdefault(e, []).append(len(cards) + 1)
        card_works = set(listed_works) | {ctx.ev_work[e] for e in eids}
        card_works.discard("")
        in_similar = card_works & set(ctx.work_n)
        freq_d = _as_dict(c.get("frequency")) if isinstance(c.get("frequency"), Mapping) else {}
        k = _int(_get(freq_d, "n_works", "works")) if freq_d else None
        k = len(in_similar) if k is None else k
        r = _int(_get(freq_d, "n_reject", "rejected")) if freq_d else None
        r = len(in_similar & reject_ids) if r is None else r
        if n_similar and decisions_known:
            freq = f"유사 {n_similar}편 중 {k}편 지적 · 그중 {r}편 거절"
        elif n_similar:
            freq = f"유사 {n_similar}편 중 {k}편 지적 · 결정 정보 없음"
        else:
            freq = f"근거 논문 {len(card_works)}편"
        gen = _text(_get(c, "generator", "derivation", "gen")).lower()
        gen = gen if gen in GENERATORS else ("unknown" if not gen else gen[:16])
        acts = []
        for a in _list(_get(c, "actions", "acts", "prevention_actions")):
            t = _text(a) or _text(_get(_as_dict(a), "text", "action", "t"))
            if t:
                acts.append(t)
        cid = _text(_get(c, "card_id", "id"))
        if cid:
            ctx.card_rank.setdefault(cid, len(cards) + 1)
        cards.append({
            "rank": len(cards) + 1,
            "fam": fam,
            "sev": _severity(c, score),
            "score": f"{total:.2f}" if total is not None else "–",
            "comp": comp,
            "src": f"근거 {len(ev_nums)}건 · 논문 {len(card_works)}편",
            "desc": desc,
            "lines": lines,
            "freq": freq,
            "ev": ev_nums,
            "acts": acts,
            "gen": gen,
            "genl": display_generator(gen, _get(c, "model")),
            "id": _text(_get(c, "card_id", "id")),
            "_works": sorted(card_works),
        })
    return cards


def _build_ev(ctx: _Ctx, card_fam_of: dict[str, int]) -> dict[str, dict[str, Any]]:
    ev: dict[str, dict[str, Any]] = {}
    for eid, n in sorted(ctx.ev_num.items(), key=lambda kv: kv[1]):
        e = ctx.evidence[eid]
        wid = ctx.ev_work.get(eid) or _resolve_work(e, ctx)
        w = ctx.works_by_id.get(wid)
        code = _code(_get(e, "risk_code", "code"))
        fam = card_fam_of.get(eid)
        if fam is None:
            fam = ctx.fam_for_code(code or "R?")
        rec = ctx.records
        known = (rec.works.get(wid) if rec and wid else None) or {}
        venue = _text(_get(e, "venue")) or (w or {}).get("venue", "") or known.get("venue", "")
        kind = SOURCE_KIND_KO.get(_text(_get(e, "source_kind", "kind")).lower(), "심사평")
        section = _text(_get(e, "section"))
        v = " · ".join(x for x in (venue, kind, section) if x)
        rv = _text(_get(e, "reviewer_pseudonym"))
        raw_dec = _get(e, "work_decision", "decision")
        dec = (w or {}).get("d") or decision_label(raw_dec)
        if w is None and raw_dec is None and rec and wid in rec.decisions:
            dec = rec.decisions[wid][0]  # 유사 연구 목록 밖 논문(확장 검색)도 기록에 결정이 있으면 쓴다
            ctx.enrich("evidence_decision")
        raw_rt = _get(e, "rating", "rt")
        if raw_rt is None and rec:
            raw_rt = rec.review_rating(_text(e.get("source_id"))) or None
            if raw_rt is not None:
                ctx.enrich("evidence_rating")
        rt_num = rating_value(raw_rt)
        item: dict[str, Any] = {
            "fam": fam,
            "q": _text(_get(e, "text", "quote", "q")),
            "p": (w or {}).get("t") or _text(_get(e, "work_title", "paper_title", "p")) or known.get("title", "") or wid,
            "v": v,
            "d": dec,
            "rt": _rating(rt_num) if rt_num is not None else _rating(raw_rt),
            "rv": rv if PSEUDONYM.match(rv) else "",
            "id": wid,
            "ln": _int(_get(e, "plan_line", "ln")) or ctx.ev_line.get(eid),
            "u": _text(_get(e, "source_url", "url")) or (w or {}).get("u", "") or known.get("url", ""),
            "eid": eid,
        }
        if raw_rt is not None and _text(raw_rt) != item["rt"]:
            item["rtraw"] = _text(raw_rt)[:80]  # 평점 원문('6: marginally above …')
        lns = [n for n in ctx.ev_lines.get(eid, []) if n in ctx.plan_line_ns]
        if item["ln"] is not None and item["ln"] in ctx.plan_line_ns and item["ln"] not in lns:
            lns.insert(0, item["ln"])
        item["lns"] = lns
        item["cards"] = list(dict.fromkeys(ctx.ev_cards.get(eid, [])))
        sk = _text(_get(e, "source_kind", "kind")).lower()
        if sk:
            item["kind"] = sk
        if not item["p"]:
            item["p"] = "논문 미상"
        if item["ln"] is not None and item["ln"] not in ctx.plan_line_ns:
            item["ln"] = None
        if w is not None:
            item["map"] = w["n"]
        else:
            item["x"] = True
        start, end = _int(e.get("start")), _int(e.get("end"))
        if start is not None and end is not None:
            item["off"] = [start, end]
        sha = _text(_get(e, "text_sha256", "sha256"))
        if sha:
            item["sha"] = sha[:16]
        ev[str(n)] = item
    return ev


def _build_review(res: Mapping[str, Any], ctx: _Ctx, has_works: bool) -> dict[str, Any]:
    """예상 심사평. 화면에서 근거 번호로 풀리지 않는 문장은 내보내지 않는다.

    ``"map"`` 인용(평가이력 지도 참조)은 유사 연구 목록이 있을 때만 근거로 인정한다.
    """
    er = _as_dict(_get(res, "expected_review", "review"))
    out: dict[str, Any] = {}
    kept = dropped_n = 0
    dropped: list[list[str]] = []
    for key, aliases in (("strength", ("strength", "strengths")), ("weakness", ("weakness", "weaknesses")),
                         ("request", ("request", "requests"))):
        sents = []
        for raw in _list(_get(er, *aliases)):
            s = _as_dict(raw) if not isinstance(raw, str) else {"text": raw}
            t = _text(_get(s, "text", "t", "sentence"))
            cites: list[int | str] = []
            for ref in _list(_get(s, "evidence", "excerpt_ids", "c", "citations", "cites")):
                if ref == "map":
                    if has_works and "map" not in cites:
                        cites.append("map")
                    continue
                eid = _text(ref) if not isinstance(ref, Mapping) else _text(_get(ref, "excerpt_id", "id"))
                n = _number_ev(eid, ctx) if eid else None
                if n is not None and n not in cites:
                    cites.append(n)
            if not t or not cites:
                dropped_n += 1
                dropped.append(["no_evidence_in_view", t[:200]])
                continue
            kept += 1
            sent: dict[str, Any] = {"t": t, "c": cites}
            lns = [n for v in _list(_get(s, "plan_lines", "lines", "ln")) if (n := _int(v)) in ctx.plan_line_ns]
            if lns:
                sent["ln"] = list(dict.fromkeys(lns))
            ranks = [ctx.card_rank[cid] for cid in (_text(x) for x in _list(s.get("cards"))) if cid in ctx.card_rank]
            if ranks:
                sent["cards"] = list(dict.fromkeys(ranks))
            sents.append(sent)
        out[key] = sents
    audit = _as_dict(er.get("audit"))
    gate_dropped: list[list[str]] = []
    for d in _list(_get(audit, "dropped")):
        if isinstance(d, (list, tuple)) and len(d) == 2:
            gate_dropped.append([_text(d[0]), _text(d[1])])
        elif dd := _as_dict(d):
            gate_dropped.append([_text(_get(dd, "reason", "code")), _text(_get(dd, "text", "sentence"))])
    dropped = gate_dropped + dropped
    gen = _int(_get(audit, "generated", "gen"))
    gen = kept + dropped_n if gen is None else max(gen, kept)
    if dropped_n:
        ctx.drop("review_sentences_without_evidence", dropped_n)
    # pass = 화면에 실제로 나가는 문장 수. 게이트가 뺀 것과 화면이 뺀 것이 모두 drop에 들어간다.
    out["audit"] = {"gen": gen, "pass": kept, "drop": max(0, gen - kept), "dropped": dropped}
    gate = _text(audit.get("gate"))
    if gate:
        out["audit"]["gate"] = gate
    # 생성 방식·상태를 그대로 싣는다(규칙 합성을 LLM 생성으로 보이게 하지 않는다). 결과에 없으면 싣지 않는다.
    gen_raw = _text(_get(er, "generator", "gen")).lower()
    if gen_raw:
        out["gen"] = gen_raw if gen_raw in GENERATORS else gen_raw[:16]
    for key, aliases in (("st", ("status",)), ("why", ("reason",)), ("model", ("model",))):
        v = _text(_get(er, *aliases))
        if v:
            out[key] = v[:300]
    if out.get("gen"):
        out["genl"] = display_generator(out["gen"], out.get("model"))
    if out.get("why"):
        out["why"] = display_text(out["why"])
    return out


def _build_checklist(res: Mapping[str, Any], ctx: _Ctx | None = None) -> list[dict[str, Any]]:
    """체크리스트(E3-L1b 항목) → 목업 ``{id, t, r, s, m}`` + 화면용 추가 키.

    추가 키: ``ln``(계획서 줄), ``ev``(화면 근거 번호), ``card``(카드 순위), ``v``(확인 조건), ``gen``(생성 방식),
    ``why``(규칙 대체 사유), ``cv``(카드 2차 검증 판정), ``set``(연구자가 결정을 골랐는지 — 아니면 ``s``는 기본값 보류).
    """
    table = {"채택": "채택", "보류": "보류", "기각": "기각", "adopt": "채택", "accept": "채택", "adopted": "채택",
             "defer": "보류", "hold": "보류", "pending": "보류", "reject": "기각", "rejected": "기각"}
    out = []
    for i, raw in enumerate(_list(_get(res, "checklist")), 1):
        it = _as_dict(raw)
        t = _text(_get(it, "action", "t", "text", "title"))
        if not t:
            continue
        chosen = table.get(_text(_get(it, "decision", "s", "choice")).strip().lower())
        item: dict[str, Any] = {"id": _text(_get(it, "id", "item_id")) or f"C{i}", "t": t,
                                "r": _text(_get(it, "risk_code", "r", "risk")), "s": chosen or "보류",
                                "m": _text(_get(it, "note", "m", "memo")), "set": chosen is not None}
        if ctx is not None:
            lns = [n for v in _list(_get(it, "plan_lines", "lines")) if (n := _int(v)) in ctx.plan_line_ns]
            item["ln"] = list(dict.fromkeys(lns))
            evs = [ctx.ev_num[e] for e in (_text(x) for x in _list(_get(it, "evidence", "evidence_ids")))
                   if e in ctx.ev_num]
            item["ev"] = list(dict.fromkeys(evs))
            rank = ctx.card_rank.get(_text(it.get("card_id")))
            if rank is not None:
                item["card"] = rank
        for key, aliases in (("v", ("verify",)), ("gen", ("generator",)), ("why", ("fallback_reason",)),
                             ("cv", ("card_verdict",))):
            v = _text(_get(it, *aliases))
            if v:
                item[key] = v[:300]
        if item.get("gen"):
            item["genl"] = display_generator(item["gen"], _get(it, "model"))
        out.append(item)
    return out


def _build_pipeline(res: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float | None]:
    groups: dict[str, dict[str, Any]] = {}
    not_ok: list[dict[str, Any]] = []
    total = 0.0
    seen_time = False
    for raw in _list(_get(res, "stages", "statuses")):
        st = _as_dict(raw)
        name = _text(_get(st, "name", "stage")) or "stage"
        phase = (_text(_get(st, "phase")) or name).upper()
        status = _text(_get(st, "status", "state")).lower() or "ok"
        reason = display_text(_get(st, "reason", "detail"))
        impl = _text(_get(st, "impl"))
        el = _num(st.get("elapsed_s"))
        if el is not None and el >= 0:
            total += el
            seen_time = True
        g = groups.setdefault(phase, {"k": phase, "ms": 0, "log": [], "_st": []})
        g["ms"] += int(round((el or 0) * 1000))
        kind = "ok" if status == "ok" else ("k" if status in {"skipped", "empty"} else "w")
        msg = f"{name} — {STAGE_STATUS_KO.get(status, status)}"
        if reason:
            msg += f" · {reason}"
        if impl:
            msg += f" · {impl}"
        g["log"].append([kind, msg[:300]])
        g["_st"].append(status)
        if status != "ok" or st.get("degraded") is True:
            not_ok.append({"name": name, "phase": phase, "status": status, "reason": reason[:300]})
    pipeline = []
    for g in groups.values():
        sts = g.pop("_st")
        counts = {s: sts.count(s) for s in dict.fromkeys(sts)}
        g["m"] = " · ".join(f"{STAGE_STATUS_KO.get(s, s)} {n}" for s, n in counts.items())
        pipeline.append(g)
    return pipeline, not_ok, (round(total, 3) if seen_time else None)


def _fill_work_flags(works: list[dict[str, Any]], cards: list[dict[str, Any]], ctx: _Ctx) -> None:
    fam_works: list[set[str]] = [set() for _ in ctx.fams]
    for cd in cards:
        fam_works[cd["fam"]].update(cd["_works"])
    for w in works:
        w["f"] = [1 if w["id"] in fw else 0 for fw in fam_works]


def _generator_labels(view: dict[str, Any], gens: Mapping[str, int]) -> dict[str, str]:
    """생성 방식별 표시 이름(DISP-1). 모델명이 없는 LLM 카드·심사평·체크리스트는 결과 manifest의 모델로 채운다.

    계약 값(``gen``)은 그대로 두고 ``genl``만 채운다. 규칙·mock에는 모델을 붙이지 않는다.
    """
    model = (view.get("kpi") or {}).get("model_id")
    for d in [*view.get("cards", []), view.get("review", {}), *view.get("checklist", [])]:
        if d.get("gen") == "astra" and d.get("genl") == "LLM" and model:
            d["genl"] = display_generator("astra", model)
    labels: dict[str, str] = {}
    for g in gens:
        names = list(dict.fromkeys(cd["genl"] for cd in view.get("cards", []) if cd.get("gen") == g and cd.get("genl")))
        labels[g] = " · ".join(names) if names else display_generator(g, model if g == "astra" else None)
    return labels


# ───────────────────────── 공개 함수 ─────────────────────────


def empty_view() -> dict[str, Any]:
    return {
        "plan_id": "", "session_id": "",
        "plan": {"file": "", "size": "0 B", "meta": "계획서 줄 없음", "title": "", "lines": []},
        "pipeline": [], "works": [], "fams": [], "corpus": [], "ev": {}, "cards": [], "others": [],
        "review": {"strength": [], "weakness": [], "request": [], "audit": {"gen": 0, "pass": 0, "drop": 0, "dropped": []}},
        "checklist": [],
        "kpi": {"n_works": 0, "n_reject": 0, "n_accept": 0, "n_evidence": 0, "n_cards_total": 0, "review_count": 0,
                "model_id": None, "model_provider": None, "elapsed_s": None},
    }


def build_ui_view(
    result: Any,
    *,
    filename: str | None = None,
    sample: bool = False,
    pipeline_state: str = "connected",
    error: str | None = None,
    input_info: Mapping[str, Any] | None = None,
    extra_notices: Iterable[str] = (),
    records: Any = AUTO,
) -> dict[str, Any]:
    """분석 결과 → ui_view dict. 절대 예외를 던지지 않는다.

    - ``sample``: 파이프라인이 없어 샘플을 쓴 경우. 화면이 ``_status.label``을 띄운다.
    - ``records``: 결정·평점 조회(``RecordLookup``). 기본 ``AUTO``는 공유 데이터 폴더의 기록을 쓰되 샘플이면 쓰지 않는다
      (가짜 fixture에 실제 기록을 섞지 않는다). ``None``이면 조회하지 않는다.
    - ``pipeline_state``: connected | unavailable | error
    - ``error``: 파이프라인이 실패한 사유(사람이 읽는 한 줄, 비밀값 금지).
    """
    try:
        if records is AUTO:
            records = None if sample else default_records()
        return _build(result, filename=filename, sample=sample, pipeline_state=pipeline_state, error=error,
                      input_info=input_info, extra_notices=list(extra_notices),
                      records=records if isinstance(records, RecordLookup) else None)
    except Exception as exc:  # noqa: BLE001 - 마지막 방어선: 빈 뷰 + 오류 상태
        view = empty_view()
        view["_status"] = _status_block(
            sample=sample, pipeline_state=pipeline_state, result_status="error",
            error=error or f"화면 데이터 조립 실패: {type(exc).__name__}", notices=list(extra_notices),
            input_info=input_info)
        return view


def _status_block(*, sample: bool, pipeline_state: str, result_status: str | None, error: str | None,
                  notices: list[str], input_info: Mapping[str, Any] | None) -> dict[str, Any]:
    if sample:
        label = SAMPLE_LABEL
    elif error or result_status == "error":
        label = ERROR_LABEL
    elif result_status == "degraded":
        label = "일부 단계 강등"
    else:
        label = ""
    if error and error not in notices:
        notices = [error, *notices]
    return {
        "source": "sample" if sample else ("none" if result_status == "error" and pipeline_state != "connected" else "pipeline"),
        "pipeline": pipeline_state,
        "label": label,
        "result_status": result_status,
        "degraded": bool(sample or result_status in {"degraded", "error"}),
        "notices": notices,
        "input": dict(input_info or {}),
        "stages_not_ok": [], "generators": {}, "empty_reason": None,
        "dropped": {}, "section_errors": {}, "contract_ok": True, "contract_errors": [],
        "generated_at": None, "pipeline_version": None,
    }


# 입력 분량 단계(E3-L1s, 결과 plan_checks.input_quality) → 화면 문구. 문구는 E3가 만든 message를 그대로 쓴다.
INPUT_LEVEL_LABEL = {"reject": "입력이 짧아 분석하지 않음", "warn": "입력이 짧아 결과 신뢰도 낮음"}


def _input_quality(res: Mapping[str, Any]) -> dict[str, Any] | None:
    """결과의 입력 분량 단계 → `_status.input_quality`(level·label·message·missing·followups). 없으면 None."""
    iq = _as_dict(_as_dict(res.get("plan_checks")).get("input_quality"))
    level = _text(iq.get("level")).lower()
    if level not in ("reject", "warn", "ok"):
        return None
    return {
        "level": level,
        "status": _text(iq.get("status")) or None,
        "label": INPUT_LEVEL_LABEL.get(level, ""),
        "message": _text(iq.get("message")) or None,
        "missing": [_text(m) for m in _list(iq.get("missing")) if _text(m)],
        "followups": [_text(_as_dict(q).get("question")) for q in _list(iq.get("followup_questions"))
                      if _text(_as_dict(q).get("question"))],
        "metrics": {k: v for k, v in _as_dict(iq.get("metrics")).items()
                    if k in ("length", "n_chars", "n_sentences", "n_elements", "n_elements_llm")},
    }


def _build(result: Any, *, filename: str | None, sample: bool, pipeline_state: str, error: str | None,
           input_info: Mapping[str, Any] | None, extra_notices: list[str],
           records: RecordLookup | None = None) -> dict[str, Any]:
    res = _as_dict(result)
    ctx = _Ctx(records)
    view = empty_view()

    def section(name: str, fn, default):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 한 섹션이 깨져도 나머지는 그린다
            ctx.section_errors[name] = type(exc).__name__
            return default

    view["plan"] = section("plan", lambda: _build_plan(res, filename, ctx), view["plan"])
    works = section("works", lambda: _build_works(res, ctx), [])
    section("evidence", lambda: _collect_evidence(res, ctx), None)
    cards = section("cards", lambda: _build_cards(res, works, ctx), [])
    card_fam_of: dict[str, int] = {}
    inv = {n: e for e, n in ctx.ev_num.items()}
    for cd in cards:
        for n in cd["ev"]:
            card_fam_of.setdefault(inv[n], cd["fam"])
    review = section("review", lambda: _build_review(res, ctx, bool(works)), view["review"])
    ev = section("ev", lambda: _build_ev(ctx, card_fam_of), {})
    section("works_flags", lambda: _fill_work_flags(works, cards, ctx), None)
    pipeline, not_ok, elapsed = section("pipeline", lambda: _build_pipeline(res), ([], [], None))
    checklist = section("checklist", lambda: _build_checklist(res, ctx), [])

    flagged = {n for cd in cards for n in cd["lines"]}
    for line in view["plan"]["lines"]:
        if line["n"] in flagged:
            line["f"] = True
    for cd in cards:
        cd.pop("_works", None)

    view.update({
        "pipeline": pipeline, "works": works, "fams": ctx.fams, "corpus": [None] * len(ctx.fams),
        "ev": ev, "cards": cards, "others": [], "review": review, "checklist": checklist,
    })
    plan_text_for_id = "\n".join(line["t"] for line in view["plan"]["lines"])
    view["plan_id"] = _text(res.get("plan_id")) or (
        "sha256:" + hashlib.sha256(plan_text_for_id.encode("utf-8")).hexdigest()[:16] if plan_text_for_id else "")
    view["session_id"] = _text(res.get("session_id")) or ("sess_" + uuid.uuid4().hex[:12])

    manifest = _as_dict(res.get("manifest"))
    n_reject = sum(1 for w in works if w["d"] == REJECT_LABEL)
    n_accept = sum(1 for w in works if w["d"] in ACCEPT_LABELS)
    review_count = sum(len(review.get(k, [])) for k in ("strength", "weakness", "request"))
    view["kpi"] = {
        "n_works": len(works), "n_reject": n_reject, "n_accept": n_accept, "n_evidence": len(ev),
        "n_cards_total": len(cards), "review_count": review_count,
        "model_id": _text(_get(manifest, "model_id", "model", "llm_model")) or _text(res.get("model_id")) or None,
        "model_provider": _text(_get(manifest, "model_provider", "provider", "llm_provider")) or _text(res.get("model_provider")) or None,
        "elapsed_s": elapsed,
    }

    result_status = _text(res.get("status")).lower() or (None if not res else "ok")
    if error:
        result_status = "error"
    notices = [display_text(n) for n in _list(res.get("notices")) if _text(n)] + [display_text(n) for n in extra_notices if n]
    status = _status_block(sample=sample, pipeline_state=pipeline_state, result_status=result_status,
                           error=error, notices=notices, input_info=input_info)
    gens: dict[str, int] = {}
    for cd in cards:
        gens[cd["gen"]] = gens.get(cd["gen"], 0) + 1
    status["generators"] = gens
    status["generator_labels"] = _generator_labels(view, gens)
    status["stages_not_ok"] = not_ok
    status["degraded"] = bool(status["degraded"] or not_ok or any(g != "astra" for g in gens))
    if not cards:
        reason = _text(_get(res, "empty_reason", "no_cards_reason"))
        if not reason:
            card_stage = next((s for s in not_ok if "card" in s["name"].lower() or s["phase"] == "RISK"), None)
            reason = (card_stage or {}).get("reason", "")
        if not reason and ctx.dropped.get("cards_without_evidence"):
            reason = f"근거가 연결되지 않은 카드 {ctx.dropped['cards_without_evidence']}장을 뺐다"
        status["empty_reason"] = display_text(reason or error or "위험카드 0장 — 결과에 사유가 없다")
    # 입력 분량 단계(E3-L1s): 거절·경고면 안내 문구를 notices 맨 앞에, 라벨에 표시(화면 공지 상자가 라벨이 있을 때 뜬다).
    iqv = None if sample else _input_quality(res)
    status["input_quality"] = iqv
    if iqv and iqv["level"] in ("reject", "warn"):
        msg = iqv["message"]
        if msg:
            status["notices"] = [msg, *[n for n in status["notices"] if n != msg]]
        if not error and result_status != "error":
            status["label"] = iqv["label"] + (f" · {status['label']}" if status["label"] else "")
    # 검색어 규칙 대체·낮은 유사도·적합성 보류 진행(E3-L1s): 결과 plan_checks에서 옮겨 표시한다(정직 표기).
    pcs = _as_dict(res.get("plan_checks"))
    srch, gate = _as_dict(pcs.get("search")), _as_dict(pcs.get("research_gate"))
    marks = []
    if _text(srch.get("queries_source")) == "rule":
        marks.append("검색어 규칙 대체")
    if srch.get("low_similarity") is True:
        marks.append("낮은 유사도")
    if gate.get("passed") is True:
        marks.append(_text(gate.get("note")) or "적합성 보류였으나 유사 연구 근거로 진행")
    status["search"] = {
        "queries_source": _text(srch.get("queries_source")) or None,
        "low_similarity": srch.get("low_similarity") is True,
        "research_gate": _text(gate.get("status")) or None,
        "marks": marks,
    } if (srch or gate) else None
    if marks and not sample and not error and result_status != "error":
        extra = " · ".join(m for m in marks if m not in status["label"])
        status["label"] = f"{status['label']} · {extra}" if status["label"] and extra else (status["label"] or extra)
    status["dropped"] = ctx.dropped
    status["section_errors"] = ctx.section_errors
    status["generated_at"] = _text(res.get("generated_at")) or None
    status["pipeline_version"] = _text(res.get("pipeline_version")) or None
    # 결정·평점을 결과가 아니라 코퍼스 기록에서 채웠으면 그 사실과 개수를 남긴다(추적 섹션이 표시).
    status["records"] = {"source": records.source, "filled": dict(ctx.enriched)} if records else None
    ver = _as_dict(res.get("verification"))
    vstage = next((s for s in _list(res.get("stages")) if _text(_as_dict(s).get("name")) == "verify_evidence"), None)
    total, ok = _int(ver.get("quotes_total")), _int(ver.get("quotes_verified"))
    status["verification"] = {
        "total": total, "verified": ok,
        "stage": _text(_as_dict(vstage).get("status")) or None if vstage is not None else None,
    } if (total is not None or vstage is not None) else None
    view["_status"] = status

    errors = validate_ui_view(view)
    if errors:
        # 계약을 어긴 뷰는 내보내지 않는다. 빈 뷰 + 오류 상태로 바꾼다.
        fallback = empty_view()
        status = dict(status)
        status.update({"contract_ok": False, "contract_errors": errors[:10], "label": ERROR_LABEL,
                       "result_status": "error", "degraded": True})
        fallback["_status"] = status
        return fallback
    return view


@lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft7Validator

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft7Validator(schema)


def validate_ui_view(view: Any) -> list[str]:
    """계약 위반 메시지 목록. 빈 목록이면 통과."""
    try:
        validator = _validator()
    except Exception as exc:  # noqa: BLE001
        return [f"계약 스키마를 읽지 못함: {type(exc).__name__}"]
    errs = sorted(validator.iter_errors(view), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message[:200]}" for e in errs]
