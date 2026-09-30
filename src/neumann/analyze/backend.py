"""근거 저장소 어댑터. 분석 파이프라인은 이 인터페이스만 본다.

- `IndexBackend`: E2 실색인(`neumann.index.search.search`, `neumann.index.store.get_excerpts/get_work/get_reviews`)
- `FixtureBackend`: 테스트·개발용 작은 가짜 코퍼스(메모리). 제품 경로에서 조용히 이것으로 바뀌지 않는다.
  명시적으로 고를 때만 쓰고, 쓰면 search 단계 impl에 `fixture:`로 남는다.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from neumann.models import Excerpt, ReviewEvent, Work


@dataclass(frozen=True)
class Hit:
    work_id: str
    score: float
    dense: float | None = None
    lexical: float | None = None
    matched_query: str | None = None


class EvidenceBackend(Protocol):
    name: str

    def search(self, queries: list[str], k: int = 10, exclude_work_ids: set[str] | None = None) -> list[Hit]: ...

    def get_excerpts(self, work_id: str) -> list[Excerpt]: ...

    def get_work(self, work_id: str) -> Work | None: ...

    def get_reviews(self, work_id: str) -> list[ReviewEvent]: ...


# ── E2 실색인 ─────────────────────────────────────────────────────────────


class IndexBackend:
    """E2 색인 인터페이스를 그대로 부른다(계획서 E2-L0 '만들 것' 1~3)."""

    name = "index"

    def __init__(self) -> None:
        from neumann.index import search as _search  # noqa: F401 — 없으면 ImportError
        from neumann.index import store as _store  # noqa: F401

        self._search = _search
        self._store = _store
        self.impl = "neumann.index.search:search"

    def search(self, queries: list[str], k: int = 10, exclude_work_ids: set[str] | None = None) -> list[Hit]:
        raw = self._search.search(queries, k=k, exclude_work_ids=exclude_work_ids)
        return [
            Hit(
                work_id=h.work_id,
                score=float(h.score),
                dense=_opt_float(getattr(h, "dense", None)),
                lexical=_opt_float(getattr(h, "lexical", None)),
                matched_query=getattr(h, "matched_query", None),
            )
            for h in raw
        ]

    def status(self) -> dict[str, Any]:
        """E2 마지막 검색의 상태(백엔드, 강등 여부). 없으면 빈 dict."""
        fn = getattr(self._search, "last_search_status", None)
        try:
            return dict(fn()) if callable(fn) else {}
        except Exception:  # noqa: BLE001
            return {}

    def get_excerpts(self, work_id: str) -> list[Excerpt]:
        return list(self._store.get_excerpts(work_id))

    def get_work(self, work_id: str) -> Work | None:
        try:
            return self._store.get_work(work_id)
        except (KeyError, LookupError):
            return None

    def get_reviews(self, work_id: str) -> list[ReviewEvent]:
        return list(self._store.get_reviews(work_id))


def _opt_float(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# ── fixture ───────────────────────────────────────────────────────────────

_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9-])|\n+")
_TOKEN = re.compile(r"[a-z][a-z0-9\-]+")
_STOP = {"the", "and", "for", "with", "from", "that", "this", "are", "was", "were", "into", "using", "based", "our", "not"}


def split_sentences(text: str) -> list[tuple[int, int]]:
    """아주 단순한 문장 경계(fixture 전용). (start, end) 오프셋, 앞뒤 공백 제외."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _SENT_END.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    out: list[tuple[int, int]] = []
    for s, e in spans:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            out.append((s, e))
    return out


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class FixtureBackend:
    """메모리 코퍼스. 검색은 토큰 코사인(영어만). 테스트와 E2 이전 개발용."""

    name = "fixture"
    impl = "fixture:FixtureBackend"

    def __init__(self, works: Iterable[Work], reviews: Iterable[ReviewEvent]) -> None:
        self.works = {w.work_id: w for w in works}
        self.reviews: dict[str, list[ReviewEvent]] = {}
        for r in reviews:
            self.reviews.setdefault(r.work_id, []).append(r)
        self._vecs = {wid: Counter(_tokens(" ".join([w.title, w.abstract or "", " ".join(w.fields)]))) for wid, w in self.works.items()}
        self._excerpts: dict[str, list[Excerpt]] = {}

    @classmethod
    def from_json(cls, path: str | Path) -> FixtureBackend:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([Work(**w) for w in data["works"]], [ReviewEvent(**r) for r in data["reviews"]])

    def search(self, queries: list[str], k: int = 10, exclude_work_ids: set[str] | None = None) -> list[Hit]:
        exclude = exclude_work_ids or set()
        best: dict[str, Hit] = {}
        for q in queries:
            qv = Counter(_tokens(q))
            if not qv:
                continue
            qn = math.sqrt(sum(v * v for v in qv.values()))
            for wid, dv in self._vecs.items():
                if wid in exclude or not dv:
                    continue
                dot = sum(qv[t] * dv.get(t, 0) for t in qv)
                if not dot:
                    continue
                score = dot / (qn * math.sqrt(sum(v * v for v in dv.values())))
                if wid not in best or score > best[wid].score:
                    best[wid] = Hit(work_id=wid, score=round(score, 4), lexical=round(score, 4), matched_query=q)
        return sorted(best.values(), key=lambda h: (-h.score, h.work_id))[:k]

    def get_excerpts(self, work_id: str) -> list[Excerpt]:
        if work_id not in self._excerpts:
            out: list[Excerpt] = []
            for r in self.reviews.get(work_id, []):
                url = r.url or r.provenance.source_url
                for s, e in split_sentences(r.text):
                    out.append(Excerpt.from_source(r.text, s, e, source_kind="review", source_id=r.review_id, source_url=url))
            self._excerpts[work_id] = out
        return list(self._excerpts[work_id])

    def get_work(self, work_id: str) -> Work | None:
        return self.works.get(work_id)

    def get_reviews(self, work_id: str) -> list[ReviewEvent]:
        return list(self.reviews.get(work_id, []))


def make_backend(name: str | None = None, *, fixture_corpus: str | Path | None = None) -> EvidenceBackend:
    """backend 선택. 기본은 E2 실색인. fixture는 경로를 명시했을 때만."""
    import os

    name = (name or os.environ.get("NEUMANN_EVIDENCE_BACKEND") or "index").lower()
    if name == "fixture":
        path = fixture_corpus or os.environ.get("NEUMANN_FIXTURE_CORPUS")
        if not path:
            raise ValueError("fixture backend에는 코퍼스 경로가 필요하다(NEUMANN_FIXTURE_CORPUS)")
        return FixtureBackend.from_json(path)
    return IndexBackend()
