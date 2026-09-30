"""수정 권고(E3-L2r)가 쓰는 기록 조회: 결정(채택·거절)·저자 답변·메타리뷰 → 문장 발췌(원문 오프셋).

**코드가 검색·조회**하고 LLM은 번호만 고른다(AGENTS.md: LLM은 인용문을 쓰지 않는다).

- `RecordStore`(Protocol): `get_decision(work_id)`, `get_responses(work_id)`, `get_meta_reviews(work_id)`, `get_work(work_id)`.
- `FileRecordStore`: 공유 데이터 폴더의 `processed/decisions.jsonl`·`author_responses.jsonl`(eLife·Europe PMC 파일도
  있으면 합친다)과 색인(`neumann.index.store`, 없으면 `index/reviews.jsonl`)의 메타리뷰를 읽는다. 처음 쓸 때 한 번 읽어
  논문별로 묶어 둔다(원시 행 보관, 돌려줄 때 모델로 검증).
- `MemoryRecordStore`: 테스트·fixture용(목록 주입).
- `collect_card_records(card, result, store)`: 카드 근거 논문(`card.works`) 우선, 채택 사례가 없으면 결과의 유사 연구까지
  넓혀서, 논문마다 결정 1건(원문 문자열 또는 결정 본문)·메타리뷰 문장·저자 답변 문장을 고른다. 문장 고르기는 규칙이다:
  카드 유형 키워드(`rules.keyword_tags`)와 카드 근거 문장과의 낱말 겹침으로 점수를 매겨 상위 N개만 남긴다.
  발췌는 모두 `Excerpt.from_source`(원문[start:end])로 만든다.

리뷰어 신원 필드는 없다(모델이 막는다). 저자 답변 본문은 수집 때 이메일·ORCID를 가린 문자열이다.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from neumann.analyze import rules
from neumann.models import AuthorResponse, Decision, Excerpt, PremortemResult, ReviewEvent, ReviewKind, RiskCard, RiskCode, Work, contains_pii

log = logging.getLogger(__name__)

ACCEPT_OUTCOMES = frozenset({"accept", "accept_oral", "accept_spotlight", "accept_poster"})
REJECT_OUTCOMES = frozenset({"reject", "reject_resubmit", "desk_reject"})
OUTCOME_LABEL = {
    "accept_oral": "Oral", "accept_spotlight": "Spotlight", "accept_poster": "Poster", "accept": "채택",
    "major_revision": "대폭 수정", "minor_revision": "소폭 수정", "reject_resubmit": "거절", "reject": "거절",
    "desk_reject": "거절", "withdrawn": "철회", "no_binary_decision": "미정", "unknown": "미정",
}

MIN_SENTENCE_CHARS = 40
MAX_SENTENCE_CHARS = 600
MAX_META_PER_WORK = 3
MAX_RESPONSE_PER_WORK = 4
MAX_META_TOTAL = 6
MAX_RESPONSE_TOTAL = 12
MAX_WORKS = 10

_TOKEN = re.compile(r"[a-z][a-z0-9\-]{2,}")
_STOP = frozenset(
    "the and for with from that this are was were into using based our not but they their which have has been "
    "also more than can will would should could may might paper authors reviewer reviewers results result method "
    "methods model models data set sets use used show shown section table figure proposed propose approach work".split()
)


def is_accepted(outcome: str | None) -> bool:
    return outcome in ACCEPT_OUTCOMES


def is_rejected(outcome: str | None) -> bool:
    return outcome in REJECT_OUTCOMES


def outcome_label(outcome: str | None) -> str:
    return OUTCOME_LABEL.get(outcome or "unknown", "미정")


# ── 저장소 ────────────────────────────────────────────────────────────────


class RecordStore(Protocol):
    source: str

    def get_decision(self, work_id: str) -> Decision | None: ...

    def get_responses(self, work_id: str) -> list[AuthorResponse]: ...

    def get_meta_reviews(self, work_id: str) -> list[ReviewEvent]: ...

    def get_work(self, work_id: str) -> Work | None: ...


class MemoryRecordStore:
    """테스트·fixture용. 목록을 그대로 들고 있다."""

    def __init__(
        self,
        *,
        decisions: Iterable[Decision] = (),
        responses: Iterable[AuthorResponse] = (),
        reviews: Iterable[ReviewEvent] = (),
        works: Iterable[Work] = (),
        source: str = "memory",
    ) -> None:
        self.source = source
        self._decisions = {d.work_id: d for d in decisions}
        self._responses: dict[str, list[AuthorResponse]] = {}
        for r in responses:
            self._responses.setdefault(r.work_id, []).append(r)
        self._meta: dict[str, list[ReviewEvent]] = {}
        for r in reviews:
            if r.kind == ReviewKind.meta_review:
                self._meta.setdefault(r.work_id, []).append(r)
        self._works = {w.work_id: w for w in works}

    def get_decision(self, work_id: str) -> Decision | None:
        return self._decisions.get(work_id)

    def get_responses(self, work_id: str) -> list[AuthorResponse]:
        return list(self._responses.get(work_id, []))

    def get_meta_reviews(self, work_id: str) -> list[ReviewEvent]:
        return list(self._meta.get(work_id, []))

    def get_work(self, work_id: str) -> Work | None:
        return self._works.get(work_id)


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


class _Grouped:
    """JSONL 여러 개를 처음 쓸 때 한 번 읽어 work_id별 원시 행으로 묶는다."""

    def __init__(self, paths: list[Path], model: type[BaseModel]) -> None:
        self.paths = [p for p in paths if p.is_file()]
        self.model = model
        self._rows: dict[str, list[dict[str, Any]]] | None = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.paths)

    def load(self) -> int:
        if self._rows is None:
            with self._lock:
                if self._rows is None:
                    rows: dict[str, list[dict[str, Any]]] = {}
                    for p in self.paths:
                        for row in _iter_json_lines(p):
                            wid = row.get("work_id")
                            if isinstance(wid, str) and wid:
                                rows.setdefault(wid, []).append(row)
                    self._rows = rows
        return sum(len(v) for v in self._rows.values())

    def get(self, work_id: str) -> list[Any]:
        self.load()
        assert self._rows is not None
        out = []
        for row in self._rows.get(work_id, []):
            try:
                out.append(self.model.model_validate(row))
            except Exception as exc:  # noqa: BLE001 — 깨진 행은 건너뛴다(신원 필드가 섞인 행도 모델이 거부한다)
                log.warning("기록 행 검증 실패 work_id=%s kind=%s", work_id[:24], type(exc).__name__)
        return out


DECISION_FILES = ("decisions.jsonl", "elife_decisions.jsonl", "europepmc_decisions.jsonl")
RESPONSE_FILES = ("author_responses.jsonl", "elife_author_responses.jsonl", "europepmc_author_responses.jsonl")


class FileRecordStore:
    """공유 데이터 폴더의 기록. 메타리뷰·논문은 색인 저장소(있으면)에서, 없으면 index/*.jsonl에서 읽는다."""

    def __init__(self, data_dir: str | Path | None = None, index_dir: str | Path | None = None) -> None:
        if data_dir is None:
            from neumann.config import get_settings

            data_dir = get_settings().data_dir
        self.data_dir = Path(data_dir)
        processed = self.data_dir / "processed"
        self.index_dir = Path(index_dir) if index_dir is not None else self.data_dir / "index"
        self._decisions = _Grouped([processed / n for n in DECISION_FILES], Decision)
        self._responses = _Grouped([processed / n for n in RESPONSE_FILES], AuthorResponse)
        self._reviews: _Grouped | None = None
        self._works: dict[str, Work] | None = None
        self._lock = threading.Lock()
        parts = ["processed/decisions.jsonl" if self._decisions.available else "decisions:없음",
                 "processed/author_responses.jsonl" if self._responses.available else "author_responses:없음"]
        self.source = " + ".join(parts) + " + index reviews"

    def _store(self) -> Any | None:
        try:
            from neumann.index import store as e2_store

            return e2_store.get_store()
        except Exception:  # noqa: BLE001 — 색인이 없으면 파일로
            return None

    def get_decision(self, work_id: str) -> Decision | None:
        got = self._decisions.get(work_id)
        return got[0] if got else None

    def get_responses(self, work_id: str) -> list[AuthorResponse]:
        return self._responses.get(work_id)

    def get_meta_reviews(self, work_id: str) -> list[ReviewEvent]:
        st = self._store()
        if st is not None:
            revs = st.get_reviews(work_id)
        else:
            if self._reviews is None:
                with self._lock:
                    if self._reviews is None:
                        self._reviews = _Grouped([self.index_dir / "reviews.jsonl"], ReviewEvent)
            revs = self._reviews.get(work_id)
        return [r for r in revs if r.kind == ReviewKind.meta_review]

    def get_work(self, work_id: str) -> Work | None:
        st = self._store()
        if st is not None:
            try:
                return st.get_work(work_id)
            except KeyError:
                return None
        if self._works is None:
            with self._lock:
                if self._works is None:
                    works: dict[str, Work] = {}
                    p = self.index_dir / "works.jsonl"
                    if p.is_file():
                        for row in _iter_json_lines(p):
                            try:
                                w = Work.model_validate(row)
                            except Exception:  # noqa: BLE001
                                continue
                            works[w.work_id] = w
                    self._works = works
        return self._works.get(work_id)


_DEFAULT: FileRecordStore | None = None
_DEFAULT_LOCK = threading.Lock()


def default_record_store() -> FileRecordStore:
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = FileRecordStore()
    return _DEFAULT


def reset_default_record_store() -> None:
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = None


# ── 문장 고르기(규칙) ─────────────────────────────────────────────────────


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP}


def _split(text: str) -> list[tuple[int, int]]:
    try:
        from neumann.index.sentences import split_sentences

        return split_sentences(text)
    except Exception:  # noqa: BLE001 — 색인 모듈이 없으면 단순 분할
        from neumann.analyze.backend import split_sentences as simple

        return simple(text)


def score_sentence(text: str, code: RiskCode, topic: set[str]) -> float:
    """카드 유형 키워드 적중(2점) + 카드 근거와 겹치는 낱말 비율(0~1)."""
    tags = dict(rules.keyword_tags(text))
    hit = 2.0 if code in tags else 0.0
    toks = _tokens(text)
    overlap = len(toks & topic) / (len(toks) or 1)
    return hit + overlap


@dataclass
class RecordExcerpt:
    """새 발췌 + 논문·종류·결정."""

    excerpt: Excerpt
    work_id: str
    record_kind: str  # meta_review | author_response | decision
    outcome: str | None
    score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {**self.excerpt.model_dump(mode="json"), "work_id": self.work_id, "record_kind": self.record_kind,
                "outcome": self.outcome}


@dataclass
class WorkRecords:
    work_id: str
    outcome: str | None
    outcome_raw: str | None
    title: str | None
    url: str | None
    n_responses: int = 0
    n_meta_reviews: int = 0
    decision_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"work_id": self.work_id, "title": self.title, "url": self.url, "outcome": self.outcome or "unknown",
                "outcome_raw": self.outcome_raw, "outcome_label": outcome_label(self.outcome),
                "n_responses": self.n_responses, "n_meta_reviews": self.n_meta_reviews}


@dataclass
class CardRecords:
    """카드 하나가 인용할 수 있는 새 기록."""

    card_id: str
    works: list[WorkRecords] = field(default_factory=list)
    excerpts: list[RecordExcerpt] = field(default_factory=list)
    widened: bool = False  # 카드 근거 논문에 채택 사례가 없어 유사 연구 전체로 넓혔나

    def by_id(self) -> dict[str, RecordExcerpt]:
        return {r.excerpt.excerpt_id: r for r in self.excerpts}

    def coverage(self) -> dict[str, int]:
        return {
            "works_considered": len(self.works),
            "works_with_decision": sum(1 for w in self.works if w.outcome and w.outcome != "unknown"),
            "works_accepted": sum(1 for w in self.works if is_accepted(w.outcome)),
            "works_rejected": sum(1 for w in self.works if is_rejected(w.outcome)),
            "works_with_responses": sum(1 for w in self.works if w.n_responses),
            "works_with_meta_review": sum(1 for w in self.works if w.n_meta_reviews),
        }


def _record_url(rec: Any) -> str:
    return getattr(rec, "url", None) or rec.provenance.source_url


def _sentence_excerpts(text: str, *, source_kind: str, source_id: str, source_url: str, code: RiskCode,
                       topic: set[str], limit: int) -> list[tuple[float, Excerpt]]:
    out: list[tuple[float, Excerpt]] = []
    from neumann.analyze.revise import contains_identity

    for s, e in _split(text):
        piece = text[s:e]
        if not (MIN_SENTENCE_CHARS <= len(piece) <= MAX_SENTENCE_CHARS) or not piece.strip():
            continue
        if contains_identity(piece) or contains_pii(piece):
            continue
        try:
            ex = Excerpt.from_source(text, s, e, source_kind=source_kind, source_id=source_id, source_url=source_url)  # type: ignore[arg-type]
        except ValueError:
            continue
        out.append((score_sentence(piece, code, topic), ex))
    out.sort(key=lambda t: (-t[0], t[1].start))
    return out[:limit]


def _decision_excerpt(dec: Decision) -> Excerpt | None:
    """결정 본문이 있으면 그 전체, 없으면 결정 원문 문자열(outcome_raw)을 글자 그대로 자른다."""
    text = dec.text if dec.text and dec.text.strip() else dec.outcome_raw
    if not text or not text.strip():
        return None
    from neumann.analyze.revise import contains_identity

    if contains_identity(text) or contains_pii(text):
        return None
    try:
        return Excerpt.from_source(text, 0, len(text), source_kind="decision", source_id=dec.decision_id,
                                   source_url=_record_url(dec))
    except ValueError:
        return None


def collect_card_records(
    card: RiskCard,
    result: PremortemResult,
    store: RecordStore,
    *,
    known_ids: set[str] | None = None,
) -> CardRecords:
    """카드 근거 논문 → (없으면 유사 연구 전체) 기록을 모아 발췌로 만든다. 예외로 죽지 않는다(논문 단위로 건너뜀)."""
    ev = {e.excerpt_id: e for e in result.evidence}
    topic = _tokens(" ".join([card.title, card.why_applies.text, *(ev[x].text for x in card.evidence if x in ev)]))
    code = RiskCode(card.risk_code)
    known = set(known_ids or ())
    out = CardRecords(card_id=card.card_id)

    def gather(work_ids: list[str]) -> None:
        for wid in work_ids:
            if any(w.work_id == wid for w in out.works) or len(out.works) >= MAX_WORKS:
                continue
            try:
                dec = store.get_decision(wid)
                responses = store.get_responses(wid)
                metas = store.get_meta_reviews(wid)
                work = store.get_work(wid)
            except Exception as exc:  # noqa: BLE001 — 한 논문의 기록 오류로 전체를 멈추지 않는다
                log.warning("기록 조회 실패 work_id=%s kind=%s", wid[:24], type(exc).__name__)
                continue
            # 저장소가 다른 논문 기록을 돌려줘도 요청한 논문의 기록으로 재표기하지 않는다.
            dec = dec if dec is None or dec.work_id == wid else None
            responses = [a for a in responses if a.work_id == wid]
            metas = [r for r in metas if r.work_id == wid]
            work = work if work is None or work.work_id == wid else None
            sim = next((w for w in result.similar_works if w.work_id == wid), None)
            outcome = dec.outcome.value if dec is not None else None
            wr = WorkRecords(
                work_id=wid, outcome=outcome, outcome_raw=dec.outcome_raw if dec else None,
                title=(work.title if work else None) or (sim.title if sim else None),
                url=(work.url if work else None) or (sim.url if sim else None),
                n_responses=len(responses), n_meta_reviews=len(metas),
                decision_url=_record_url(dec) if dec else None,
            )
            out.works.append(wr)
            if dec is not None:
                dx = _decision_excerpt(dec)
                if dx is not None and dx.excerpt_id not in known:
                    out.excerpts.append(RecordExcerpt(dx, wid, "decision", outcome, 0.0))
            for r in metas:
                for sc, ex in _sentence_excerpts(r.text, source_kind="review", source_id=r.review_id,
                                                 source_url=_record_url(r), code=code, topic=topic,
                                                 limit=MAX_META_PER_WORK):
                    if ex.excerpt_id not in known:
                        out.excerpts.append(RecordExcerpt(ex, wid, "meta_review", outcome, sc))
            per_work: list[tuple[float, Excerpt, str]] = []
            for a in responses:
                for sc, ex in _sentence_excerpts(a.text, source_kind="author_response", source_id=a.response_id,
                                                 source_url=_record_url(a), code=code, topic=topic,
                                                 limit=MAX_RESPONSE_PER_WORK):
                    per_work.append((sc, ex, a.response_id))
            per_work.sort(key=lambda t: (-t[0], t[2], t[1].start))
            for sc, ex, _rid in per_work[:MAX_RESPONSE_PER_WORK]:
                if ex.excerpt_id not in known:
                    out.excerpts.append(RecordExcerpt(ex, wid, "author_response", outcome, sc))

    gather(list(dict.fromkeys(card.works)))
    has_case = any(r.record_kind == "author_response" and is_accepted(r.outcome) for r in out.excerpts)
    if not has_case:
        others = [w.work_id for w in result.similar_works if w.work_id not in card.works]
        if others:
            out.widened = True
            gather(others)
    # 전체 상한: 메타리뷰·저자 답변은 점수 순으로 자르고, 결정은 모두 둔다
    metas = sorted((r for r in out.excerpts if r.record_kind == "meta_review"), key=lambda r: -r.score)[:MAX_META_TOTAL]
    resps = sorted((r for r in out.excerpts if r.record_kind == "author_response"), key=lambda r: -r.score)[:MAX_RESPONSE_TOTAL]
    decs = [r for r in out.excerpts if r.record_kind == "decision"]
    keep = {id(r) for r in (*metas, *resps, *decs)}
    out.excerpts = [r for r in out.excerpts if id(r) in keep]
    return out


__all__ = [
    "ACCEPT_OUTCOMES",
    "CardRecords",
    "FileRecordStore",
    "MemoryRecordStore",
    "RecordExcerpt",
    "RecordStore",
    "WorkRecords",
    "collect_card_records",
    "default_record_store",
    "is_accepted",
    "is_rejected",
    "outcome_label",
    "reset_default_record_store",
    "score_sentence",
]
