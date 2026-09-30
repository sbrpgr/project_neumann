"""통합 코퍼스 조회 인터페이스(다른 에픽용). E1-L0가 쓴 `data/processed/*.jsonl`을 모델로 읽는다.

    from neumann.sources.corpus import load_corpus
    corpus = load_corpus()                 # 설정의 NEUMANN_DATA_DIR
    corpus = load_corpus("C:/.../data")    # 데이터 루트 또는 processed 폴더
    for work in corpus.works.values():
        reviews = corpus.reviews_for(work.work_id)          # 공식 심사평 + 메타리뷰(작성 시각 순)
        official = corpus.reviews_for(work.work_id, kind="official_review")
        answers = corpus.responses_for(work.work_id)        # 저자 답변
        decision = corpus.decision_for(work.work_id)        # Decision | None
        fields = work.fields                                # 선별 분야 slug 목록

- 모든 레코드는 읽을 때 `models.py`로 다시 검증한다(검증 오류면 예외).
- `ReviewEvent.text`가 Excerpt 오프셋의 기준 문자열이다. 수정하지 말고 그대로 자른다.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from neumann.models import IDENTITY_TOKENS, AuthorResponse, Decision, ReviewEvent, Work

OUTPUT_FILES = {
    "works": "works.jsonl",
    "reviews": "reviews.jsonl",
    "author_responses": "author_responses.jsonl",
    "decisions": "decisions.jsonl",
}
MANIFEST_FILE = "corpus_manifest.json"

M = TypeVar("M", bound=BaseModel)


def iter_jsonl(path: Path, model: type[M]) -> Iterator[M]:
    """JSONL 한 줄씩 모델로 검증해 돌려준다. 오류 메시지에 파일과 줄 번호를 붙인다."""
    with Path(path).open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                yield model.model_validate_json(line)
            except Exception as exc:  # pydantic.ValidationError, JSON 오류
                raise ValueError(f"{Path(path).name}:{lineno}: {model.__name__} 검증 실패: {exc}") from exc


def resolve_processed_dir(data_dir: str | Path | None = None) -> Path:
    """데이터 루트(`.../data`) 또는 processed 폴더를 받아 JSONL이 있는 폴더를 돌려준다."""
    if data_dir is None:
        from neumann.config import get_settings

        data_dir = get_settings().data_dir
    base = Path(data_dir)
    for cand in (base / "processed", base):
        if (cand / OUTPUT_FILES["works"]).is_file():
            return cand
    raise FileNotFoundError(
        f"코퍼스가 없다: {base}(/processed)/{OUTPUT_FILES['works']}. 먼저 `python scripts/collect_researcharcade.py`"
    )


@dataclass
class Corpus:
    """읽어 들인 코퍼스. works는 work_id 순서의 dict, 나머지는 논문별 색인을 함께 갖는다."""

    works: dict[str, Work]
    reviews: list[ReviewEvent]
    author_responses: list[AuthorResponse]
    decisions: dict[str, Decision]
    manifest: dict[str, Any] = field(default_factory=dict)
    _reviews_by_work: dict[str, list[ReviewEvent]] = field(default_factory=dict, repr=False)
    _responses_by_work: dict[str, list[AuthorResponse]] = field(default_factory=dict, repr=False)
    _reviews_by_id: dict[str, ReviewEvent] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        by_work: dict[str, list[ReviewEvent]] = defaultdict(list)
        for r in self.reviews:
            by_work[r.work_id].append(r)
        resp: dict[str, list[AuthorResponse]] = defaultdict(list)
        for a in self.author_responses:
            resp[a.work_id].append(a)
        self._reviews_by_work = dict(by_work)
        self._responses_by_work = dict(resp)
        self._reviews_by_id = {r.review_id: r for r in self.reviews}

    def __len__(self) -> int:
        return len(self.works)

    def get_work(self, work_id: str) -> Work:
        return self.works[work_id]

    def reviews_for(self, work_id: str, kind: str | None = None) -> list[ReviewEvent]:
        """그 논문의 심사평(작성 시각 순). kind로 "official_review"/"meta_review"만 고를 수 있다."""
        items = self._reviews_by_work.get(work_id, [])
        return [r for r in items if kind is None or r.kind.value == kind]

    def responses_for(self, work_id: str, review_id: str | None = None) -> list[AuthorResponse]:
        """그 논문의 저자 답변. review_id를 주면 그 심사평에 달린 답변만."""
        items = self._responses_by_work.get(work_id, [])
        return [a for a in items if review_id is None or a.review_id == review_id]

    def decision_for(self, work_id: str) -> Decision | None:
        return self.decisions.get(work_id)

    def get_review(self, review_id: str) -> ReviewEvent:
        return self._reviews_by_id[review_id]

    def works_in_field(self, field_slug: str) -> list[Work]:
        return [w for w in self.works.values() if field_slug in w.fields]


MODEL_FILES: dict[str, type[BaseModel]] = {
    OUTPUT_FILES["works"]: Work,
    OUTPUT_FILES["reviews"]: ReviewEvent,
    OUTPUT_FILES["author_responses"]: AuthorResponse,
    OUTPUT_FILES["decisions"]: Decision,
}
# 저장 레코드의 키에 나오면 안 되는 신원 토큰(models.IDENTITY_TOKENS + OpenReview 원본의 신원 칸 이름).
# reviewer_pseudonym은 계약상 허용 필드지만 E1-L0는 쓰지 않으므로 이것도 걸린다.
IDENTITY_KEY_TOKENS: tuple[str, ...] = (*IDENTITY_TOKENS, "writer", "reviewer", "signatures", "readers")
OPENREVIEW_URL_PREFIX = "https://openreview.net/forum?id="


def _keys(obj: Any) -> Iterator[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def audit_processed(data_dir: str | Path | None = None, *, max_report: int = 10) -> dict[str, Any]:
    """전량 검사. 레코드마다: 모델 검증 통과, provenance·딥링크가 OpenReview 원문 URL, 원문 해시 있음,
    신원 키 없음. 위반이 하나라도 있으면 ValueError(앞의 몇 건을 보여 준다). 통과하면 레코드 수를 돌려준다."""
    d = resolve_processed_dir(data_dir)
    problems: list[str] = []
    counts: dict[str, int] = {}
    for name, model in MODEL_FILES.items():
        n = 0
        with (d / name).open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                n += 1
                where = f"{name}:{lineno}"
                try:
                    row = json.loads(line)
                    obj = model.model_validate(row)
                except Exception as exc:
                    problems.append(f"{where}: 검증 실패 {str(exc).splitlines()[0]}")
                    continue
                prov = obj.provenance  # type: ignore[attr-defined]
                if not prov.source_url.startswith(OPENREVIEW_URL_PREFIX):
                    problems.append(f"{where}: provenance.source_url이 OpenReview 원문 링크가 아니다")
                if not getattr(obj, "url", None) or not obj.url.startswith(OPENREVIEW_URL_PREFIX):  # type: ignore[attr-defined]
                    problems.append(f"{where}: url이 OpenReview 원문 링크가 아니다")
                bad = sorted({k for k in _keys(row) if any(t in k.lower() for t in IDENTITY_KEY_TOKENS)})
                if bad:
                    problems.append(f"{where}: 신원 키 {bad}")
        counts[name] = n
    if problems:
        raise ValueError(f"코퍼스 검사 위반 {len(problems)}건: " + " | ".join(problems[:max_report]))
    return {"records": counts, "violations": 0, "dir": str(d)}


def load_corpus(data_dir: str | Path | None = None) -> Corpus:
    """공유 데이터 폴더의 코퍼스를 읽어 검증된 모델로 돌려준다."""
    d = resolve_processed_dir(data_dir)
    works = {w.work_id: w for w in iter_jsonl(d / OUTPUT_FILES["works"], Work)}
    reviews = list(iter_jsonl(d / OUTPUT_FILES["reviews"], ReviewEvent))
    responses = list(iter_jsonl(d / OUTPUT_FILES["author_responses"], AuthorResponse))
    decisions = {x.work_id: x for x in iter_jsonl(d / OUTPUT_FILES["decisions"], Decision)}
    manifest_path = d / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    dangling = [r.review_id for r in reviews if r.work_id not in works]
    dangling += [a.response_id for a in responses if a.work_id not in works]
    dangling += [x.decision_id for x in decisions.values() if x.work_id not in works]
    if dangling:
        raise ValueError(f"논문이 없는 레코드 {len(dangling)}건(예: {dangling[:3]})")
    return Corpus(works=works, reviews=reviews, author_responses=responses, decisions=decisions, manifest=manifest)


__all__ = [
    "Corpus",
    "MANIFEST_FILE",
    "OUTPUT_FILES",
    "audit_processed",
    "iter_jsonl",
    "load_corpus",
    "resolve_processed_dir",
]
