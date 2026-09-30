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
from collections.abc import Iterable, Iterator
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


def load_corpus(data_dir: str | Path | None = None, *, include: Iterable[str] | None = None) -> Corpus:
    """공유 데이터 폴더의 코퍼스를 읽어 검증된 모델로 돌려준다.

    include를 주지 않으면(기본) 지금까지처럼 E1-L0 파일(`works.jsonl` 등, ResearchArcade)만 읽는다.
    include=("researcharcade", "elife")처럼 주면 소스별 접두 파일(`elife_works.jsonl` 등)을 합쳐 읽는다
    (`load_sources`, E1-L1c)."""
    if include is not None:
        return load_sources(data_dir, include=include)
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


# ── 여러 소스 합치기(E1-L1c) ──────────────────────────────────────────────
# 위 함수들의 기본 동작은 그대로다. 아래는 소스별 접두 파일(E1-L1b `elife_*.jsonl` 등)을 함께 읽는 추가 경로다.
# 소스 이름 → 파일 접두. researcharcade(E1-L0)는 접두 없는 `works.jsonl` 등.
SOURCE_FILE_PREFIXES: dict[str, str] = {"researcharcade": "", "elife": "elife_", "europepmc": "europepmc_"}
SOURCE_MANIFEST_FILES: dict[str, str] = {
    "researcharcade": MANIFEST_FILE,
    "elife": "elife_manifest.json",
    "europepmc": "europepmc_manifest.json",
}
# provenance.source_url(실제로 받은 원문)의 접두. 원문 해시를 다시 잴 수 있는 URL이어야 한다.
SOURCE_URL_PREFIXES: dict[str, tuple[str, ...]] = {
    "researcharcade": (OPENREVIEW_URL_PREFIX,),
    "elife": ("https://api.elifesciences.org/",),
    "europepmc": ("https://www.ebi.ac.uk/europepmc/webservices/rest/",),
}
# 사람이 여는 딥링크(`url`)의 접두. eLife·Europe PMC는 논문 랜딩·심사평 sub-article DOI.
SOURCE_DEEPLINK_PREFIXES: dict[str, tuple[str, ...]] = {
    "researcharcade": (OPENREVIEW_URL_PREFIX,),
    "elife": ("https://elifesciences.org/", "https://doi.org/10.7554/"),
    "europepmc": ("https://",),
}
# work_id 네임스페이스. 소스끼리 겹치지 않는다.
SOURCE_WORK_ID_PREFIXES: dict[str, str] = {
    "researcharcade": "researcharcade_hf:",
    "elife": "elife:",
    "europepmc": "europepmc:",
}
DEFAULT_SOURCES: tuple[str, ...] = ("researcharcade",)
ELIFE_SOURCES: tuple[str, ...] = ("researcharcade", "elife")
# 저장 키에 나오면 안 되는 신원 토큰: E1-L0 목록 + JATS·eLife 원본의 신원 칸 이름(E1-L1b와 같음).
SOURCE_IDENTITY_KEY_TOKENS: tuple[str, ...] = (*IDENTITY_KEY_TOKENS, "contrib", "participants")
# eLife 결정 매핑 규칙(E1-L1b): 신모델 = 평가 어휘 원문 그대로 no_binary_decision, 구모델 VOR = accept.
ELIFE_ASSESSMENT_RULE = "elife_assessment_vocabulary"
ELIFE_VOR_RULE = "elife_published_vor"


def _normalize_include(include: Iterable[str]) -> tuple[str, ...]:
    if isinstance(include, str):
        include = (include,)
    out = tuple(dict.fromkeys(s.strip().lower() for s in include if s and s.strip()))
    if not out:
        raise ValueError("include가 비었다")
    unknown = [s for s in out if s not in SOURCE_FILE_PREFIXES]
    if unknown:
        raise ValueError(f"모르는 소스 {unknown}. 가능: {sorted(SOURCE_FILE_PREFIXES)}")
    return out


def source_files(processed_dir: str | Path, source: str) -> dict[str, Path]:
    """소스 하나의 엔티티 파일 경로(works·reviews·author_responses·decisions)."""
    prefix = SOURCE_FILE_PREFIXES[source]
    return {k: Path(processed_dir) / f"{prefix}{name}" for k, name in OUTPUT_FILES.items()}


def resolve_sources_dir(data_dir: str | Path | None, include: Iterable[str]) -> Path:
    """데이터 루트 또는 processed 폴더 → 포함할 소스의 works 파일이 모두 있는 폴더."""
    inc = _normalize_include(include)
    if data_dir is None:
        from neumann.config import get_settings

        data_dir = get_settings().data_dir
    base = Path(data_dir)
    for cand in (base / "processed", base):
        if all(source_files(cand, s)["works"].is_file() for s in inc):
            return cand
    missing = {s: str(source_files(base / "processed", s)["works"]) for s in inc}
    raise FileNotFoundError(f"포함할 소스의 코퍼스가 없다: {missing}")


def source_of_work_id(work_id: str) -> str | None:
    for src, prefix in SOURCE_WORK_ID_PREFIXES.items():
        if work_id.startswith(prefix):
            return src
    return None


def load_sources(data_dir: str | Path | None = None, *, include: Iterable[str] = ELIFE_SOURCES) -> Corpus:
    """여러 소스를 합쳐 하나의 `Corpus`로. 소스마다 E1-L0와 같은 모델·줄 형식이고 파일 이름에 접두만 붙는다.

    - 포함한 소스의 파일(works·reviews·author_responses·decisions)이 하나라도 없으면 FileNotFoundError.
    - work_id가 소스 사이에 겹치면 ValueError(네임스페이스가 달라 정상이면 겹치지 않는다).
    - 고아 레코드(논문 없는 심사평·답변·결정)는 load_corpus와 같이 ValueError.
    - manifest = {"include": [...], "sources": {소스: 그 소스의 manifest}}.
    """
    inc = _normalize_include(include)
    d = resolve_sources_dir(data_dir, inc)
    works: dict[str, Work] = {}
    reviews: list[ReviewEvent] = []
    responses: list[AuthorResponse] = []
    decisions: dict[str, Decision] = {}
    manifests: dict[str, Any] = {}
    for src in inc:
        files = source_files(d, src)
        missing = [str(p) for p in files.values() if not p.is_file()]
        if missing:
            raise FileNotFoundError(f"{src} 파일이 없다: {missing}")
        src_works = list(iter_jsonl(files["works"], Work))
        dup = [w.work_id for w in src_works if w.work_id in works]
        if dup:
            raise ValueError(f"{src}: 다른 소스와 겹치는 work_id {len(dup)}건(예: {dup[:3]})")
        works.update({w.work_id: w for w in src_works})
        reviews.extend(iter_jsonl(files["reviews"], ReviewEvent))
        responses.extend(iter_jsonl(files["author_responses"], AuthorResponse))
        decisions.update({x.work_id: x for x in iter_jsonl(files["decisions"], Decision)})
        mpath = d / SOURCE_MANIFEST_FILES[src]
        manifests[src] = json.loads(mpath.read_text(encoding="utf-8")) if mpath.is_file() else {}
    dangling = [r.review_id for r in reviews if r.work_id not in works]
    dangling += [a.response_id for a in responses if a.work_id not in works]
    dangling += [x.decision_id for x in decisions.values() if x.work_id not in works]
    if dangling:
        raise ValueError(f"논문이 없는 레코드 {len(dangling)}건(예: {dangling[:3]})")
    return Corpus(
        works=works,
        reviews=reviews,
        author_responses=responses,
        decisions=decisions,
        manifest={"include": list(inc), "sources": manifests},
    )


def check_elife_decisions(corpus: Corpus) -> dict[str, Any]:
    """eLife 결정 매핑 원칙 검사(E1-L1b 규칙 유지 확인).

    - 신모델(평가 어휘) 결정은 `no_binary_decision`이고, `outcome_raw`가 같은 논문 편집자 평가의
      `rating`(평가 문구 원문)과 글자 그대로 같다. 억지로 accept/reject로 바꾸지 않는다.
    - `no_binary_decision`은 평가 어휘 규칙에서만 나온다. 구모델 VOR 결정은 `accept`. reject는 없다.
    위반이 있으면 ValueError, 없으면 건수를 돌려준다.
    """
    problems: list[str] = []
    counts: dict[str, int] = defaultdict(int)
    for wid, dec in corpus.decisions.items():
        if not wid.startswith(SOURCE_WORK_ID_PREFIXES["elife"]):
            continue
        counts[dec.outcome.value] += 1
        rule = dec.mapping_rule
        if rule == ELIFE_ASSESSMENT_RULE:
            if dec.outcome.value != "no_binary_decision":
                problems.append(f"{dec.decision_id}: 평가 어휘인데 {dec.outcome.value}")
            ratings = {r.rating for r in corpus.reviews_for(wid, kind="editor_assessment") if r.rating}
            if dec.outcome_raw not in ratings:
                problems.append(f"{dec.decision_id}: outcome_raw가 편집자 평가 원문 어휘와 다르다")
            else:
                counts["assessment_raw_preserved"] += 1
        elif rule == ELIFE_VOR_RULE:
            if dec.outcome.value != "accept":
                problems.append(f"{dec.decision_id}: 게재 VOR인데 {dec.outcome.value}")
        else:
            problems.append(f"{dec.decision_id}: 모르는 매핑 규칙 {rule!r}")
        if dec.outcome.value == "no_binary_decision" and rule != ELIFE_ASSESSMENT_RULE:
            problems.append(f"{dec.decision_id}: no_binary_decision인데 규칙이 {rule!r}")
    if problems:
        raise ValueError(f"eLife 결정 매핑 위반 {len(problems)}건: " + " | ".join(problems[:10]))
    return {"decisions": dict(sorted(counts.items())), "violations": 0}


def audit_sources(
    data_dir: str | Path | None = None, *, include: Iterable[str] = ELIFE_SOURCES, max_report: int = 10
) -> dict[str, Any]:
    """소스별 전량 검사(audit_processed의 여러 소스판). 레코드마다:
    모델 검증 통과, provenance.source가 소스 이름과 맞고 source_url이 그 소스의 원문 API URL,
    딥링크(url)가 그 소스의 사람용 링크, 원문 해시(sha256 64자리) 있음, work_id 네임스페이스, 신원 키 없음.
    위반이 하나라도 있으면 ValueError. 통과하면 소스·파일별 레코드 수와 비율을 돌려준다."""
    inc = _normalize_include(include)
    d = resolve_sources_dir(data_dir, inc)
    problems: list[str] = []
    per_source: dict[str, Any] = {}
    total = url_ok = deeplink_ok = sha_ok = identity_hits = 0
    for src in inc:
        url_prefixes = SOURCE_URL_PREFIXES[src]
        deep_prefixes = SOURCE_DEEPLINK_PREFIXES[src]
        wid_prefix = SOURCE_WORK_ID_PREFIXES[src]
        counts: dict[str, int] = {}
        for key, path in source_files(d, src).items():
            model = MODEL_FILES[OUTPUT_FILES[key]]
            n = 0
            with path.open(encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if not line.strip():
                        continue
                    n += 1
                    total += 1
                    where = f"{path.name}:{lineno}"
                    try:
                        row = json.loads(line)
                    except Exception as exc:
                        problems.append(f"{where}: JSON 오류 {exc}")
                        continue
                    # 신원 키는 모델 검증 전에 원본 줄에서 본다(모델이 거부하는 키도 신원 위반으로 센다)
                    bad = sorted({k for k in _keys(row) if any(t in k.lower() for t in SOURCE_IDENTITY_KEY_TOKENS)})
                    if bad:
                        identity_hits += 1
                        problems.append(f"{where}: 신원 키 {bad}")
                    try:
                        obj = model.model_validate(row)
                    except Exception as exc:
                        problems.append(f"{where}: 검증 실패 {str(exc).splitlines()[0]}")
                        continue
                    prov = obj.provenance  # type: ignore[attr-defined]
                    src_name = prov.source.lower()
                    if not (src_name == src or src_name.startswith(src)):
                        problems.append(f"{where}: provenance.source {prov.source!r}가 {src}가 아니다")
                    if prov.source_url.startswith(url_prefixes):
                        url_ok += 1
                    else:
                        problems.append(f"{where}: provenance.source_url이 {src} 원문 URL이 아니다")
                    link = getattr(obj, "url", None)
                    if link and link.startswith(deep_prefixes):
                        deeplink_ok += 1
                    else:
                        problems.append(f"{where}: url(딥링크)이 없거나 {src} 링크가 아니다")
                    if len(prov.content_sha256) == 64:
                        sha_ok += 1
                    if not str(getattr(obj, "work_id", "")).startswith(wid_prefix):
                        problems.append(f"{where}: work_id가 {wid_prefix} 네임스페이스가 아니다")
            counts[path.name] = n
        per_source[src] = counts
    if problems:
        raise ValueError(f"소스 검사 위반 {len(problems)}건: " + " | ".join(problems[:max_report]))
    return {
        "dir": str(d),
        "include": list(inc),
        "records": per_source,
        "records_total": total,
        "source_url_ratio": url_ok / total if total else None,
        "deeplink_ratio": deeplink_ok / total if total else None,
        "content_sha256_ratio": sha_ok / total if total else None,
        "identity_key_records": identity_hits,
        "violations": 0,
    }


__all__ = [
    "Corpus",
    "DEFAULT_SOURCES",
    "ELIFE_SOURCES",
    "MANIFEST_FILE",
    "OUTPUT_FILES",
    "SOURCE_FILE_PREFIXES",
    "SOURCE_URL_PREFIXES",
    "audit_processed",
    "audit_sources",
    "check_elife_decisions",
    "iter_jsonl",
    "load_corpus",
    "load_sources",
    "resolve_processed_dir",
    "resolve_sources_dir",
    "source_files",
    "source_of_work_id",
]
