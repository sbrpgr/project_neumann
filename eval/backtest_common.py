"""백테스트 공용: 사전 고정 상수, 경로, JSON 입출력, 코퍼스 얇은 어댑터(04_평가_명세 §0).

사전 고정(2026-09-30, 결과를 보기 전에 코드와 커밋으로 고정한다):
- 시드 20260930. 표본·셔플 짝·사람 판정 표본·봉투 순서·부트스트랩이 각자 이름 붙은 시드를 쓴다(아래 SEEDS).
- 표본 30편, 축소 표본 = 목록 앞 15편.
- 부트스트랩 2,000회, 95% percentile 구간.

코퍼스 어댑터: `neumann.sources.corpus.load_corpus`(E1)가 있으면 그것을, 없으면 같은 JSONL을 계약 모델로 직접 읽는다.
어느 쪽이든 공식 심사평(official_review)만 논문별로 모은다.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SEED = 20260930
SEEDS = {
    "sample": SEED,  # random.Random(20260930): 층별 추출
    "shuffle": SEED + 1,  # 셔플 대조 짝
    "human": SEED + 2,  # 대표 블라인드 판정 10편
    "envelope": SEED + 3,  # 봉투 안 위험 순서, 봉투 id
    "bootstrap": SEED,  # 부트스트랩(macro_f1과 같은 시드)
}
N_SAMPLE = 30
N_REDUCED = 15
N_HUMAN = 10
N_BOOT = 2000
ALPHA = 0.05

DEFAULT_DATA_DIR = Path("C:/Users/User/Desktop/project_neumann/data")


def data_dir() -> Path:
    """공유 데이터 폴더. NEUMANN_DATA_DIR > 설정 > 기본값(main 체크아웃의 data/)."""
    env = os.environ.get("NEUMANN_DATA_DIR")
    if env:
        return Path(env)
    try:
        from neumann.config import get_settings

        return Path(get_settings().data_dir)
    except Exception:  # noqa: BLE001 — 설정을 못 읽어도 기본 경로로 간다
        return DEFAULT_DATA_DIR


def eval_dir() -> Path:
    return data_dir() / "eval"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(obj: Any) -> str:
    """해시용 정규 JSON(키 정렬, 공백 없음, 유니코드 그대로)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> str:
    """JSON을 쓰고 파일 sha256을 돌려준다. 줄바꿈은 LF(해시가 OS와 무관하게 같게)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(data)
    return sha256_bytes(data)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")
    path.write_bytes(data)
    return sha256_bytes(data)


def utf8_stdio() -> None:
    import sys

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


# ── 코퍼스 얇은 어댑터 ─────────────────────────────────────────────────────


@dataclass
class CorpusView:
    """백테스트가 쓰는 만큼만: 논문, 공식 심사평(작성 순), 결정, 매니페스트."""

    works: dict[str, Any]  # work_id -> models.Work
    official_reviews: dict[str, list[Any]]  # work_id -> [models.ReviewEvent]
    decisions: dict[str, Any]  # work_id -> models.Decision
    manifest: dict[str, Any] = field(default_factory=dict)
    source: str = "jsonl"
    processed_dir: str = ""
    selection: dict[str, dict[str, Any]] = field(default_factory=dict)  # work_id -> selection.jsonl 행(분야별 걸린 키워드)

    def reviews_for(self, work_id: str) -> list[Any]:
        return self.official_reviews.get(work_id, [])


def _iter_models(path: Path, model: Any) -> Iterator[Any]:
    with Path(path).open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if line.strip():
                try:
                    yield model.model_validate_json(line)
                except Exception as exc:
                    raise ValueError(f"{Path(path).name}:{lineno}: {model.__name__} 검증 실패") from exc


def _review_key(r: Any) -> tuple[str, str]:
    created = r.created.isoformat() if getattr(r, "created", None) else ""
    return (created, r.review_id)


def load_corpus_view(base: Path | None = None, *, prefer_e1: bool = True) -> CorpusView:
    """공유 데이터 폴더(`.../data` 또는 `.../data/processed`)의 코퍼스를 읽는다."""
    base = Path(base) if base is not None else data_dir()
    processed = base / "processed" if (base / "processed" / "works.jsonl").is_file() else base
    if not (processed / "works.jsonl").is_file():
        raise FileNotFoundError(f"코퍼스가 없다: {processed}/works.jsonl")
    manifest_path = processed / "corpus_manifest.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    sel_path = processed / "selection.jsonl"
    selection = {r["work_id"]: r for r in read_jsonl(sel_path)} if sel_path.is_file() else {}

    if prefer_e1:
        try:
            from neumann.sources.corpus import load_corpus  # E1-L0 (main에 들어오면 이 경로)
        except ImportError:
            load_corpus = None  # type: ignore[assignment]
        if load_corpus is not None:
            c = load_corpus(processed)
            official: dict[str, list[Any]] = {}
            for wid in c.works:
                revs = [r for r in c.reviews_for(wid) if r.kind.value == "official_review"]
                if revs:
                    official[wid] = sorted(revs, key=_review_key)
            return CorpusView(dict(c.works), official, dict(c.decisions), c.manifest or manifest, "e1.load_corpus",
                              str(processed), selection)

    from neumann.models import Decision, ReviewEvent, Work

    works = {w.work_id: w for w in _iter_models(processed / "works.jsonl", Work)}
    official = {}
    for r in _iter_models(processed / "reviews.jsonl", ReviewEvent):
        if r.kind.value == "official_review":
            official.setdefault(r.work_id, []).append(r)
    for wid in official:
        official[wid].sort(key=_review_key)
    decisions = {d.work_id: d for d in _iter_models(processed / "decisions.jsonl", Decision)}
    return CorpusView(works, official, decisions, manifest, "jsonl", str(processed), selection)


__all__ = [
    "ALPHA",
    "CorpusView",
    "N_BOOT",
    "N_HUMAN",
    "N_REDUCED",
    "N_SAMPLE",
    "SEED",
    "SEEDS",
    "canonical_json",
    "canonical_sha256",
    "data_dir",
    "eval_dir",
    "file_sha256",
    "load_corpus_view",
    "read_json",
    "read_jsonl",
    "sha256_text",
    "utf8_stdio",
    "write_json",
    "write_jsonl",
]
