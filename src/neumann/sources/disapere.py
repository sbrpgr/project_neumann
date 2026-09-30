"""DISAPERE 수집기: `DISAPERE.zip`을 읽어 심사평 단위 문장과 사람 라벨을 돌려준다.

- 원본(zip)은 읽기만 한다. 압축을 풀거나 고치지 않는다.
- DISAPERE는 CC BY-NC 4.0이다. 원본과 가공본(JSONL 등)은 저장소에 커밋하지 않고
  공유 데이터 폴더(`NEUMANN_DATA_DIR`)에만 둔다.
- 심사위원 신원 필드(`metadata.reviewer`, 예: AnonReviewer1)는 읽지 않고 내보내지 않는다.
  `annotator`(anno3 등)는 DISAPERE가 이미 익명화한 **라벨 작업자** id이며 합의 계산에만 쓴다.
- 모든 레코드에 출처(데이터셋 URL, 심사평 URL, 원본 해시, 접근 시각)를 붙인다.

zip 구조(실측): `DISAPERE/{final_dataset,extra_annotations}/{train,dev,test}/<review_id>[.annoN].json`
한 파일 = 한 주석자가 한 심사평에 붙인 문장 라벨. 같은 심사평을 여러 주석자가 라벨한 경우
파일이 여러 개다(final_dataset 1개 + extra_annotations 0~3개).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DATASET_NAME = "DISAPERE"
DATASET_URL = "https://raw.githubusercontent.com/nnkennard/DISAPERE/main/DISAPERE.zip"
LICENSE = "CC BY-NC 4.0"
# NEUMANN_RAW_DIR 아래 상대 경로
ZIP_RELPATH = Path("data") / "disapere" / "DISAPERE.zip"
SUBSETS = ("final_dataset", "extra_annotations")
SPLITS = ("train", "dev", "test")

_MEMBER_RE = re.compile(r"^DISAPERE/(final_dataset|extra_annotations)/(train|dev|test)/[^/]+\.json$")


class DisapereError(RuntimeError):
    """zip이 없거나 구조가 예상과 다르다."""


@dataclass(frozen=True)
class SentenceLabel:
    """한 주석자가 문장 하나에 붙인 라벨."""

    index: int
    aspect: str
    polarity: str
    review_action: str
    fine_review_action: str


@dataclass(frozen=True)
class Annotation:
    """한 주석자(익명 id)가 한 심사평 전체에 붙인 문장 라벨 묶음."""

    annotator: str
    subset: str
    split: str
    member: str
    member_sha256: str
    labels: tuple[SentenceLabel, ...]


@dataclass(frozen=True)
class Review:
    """심사평 1건 = 평가 단위 1개. 문장 분할은 모든 주석자에게 같다(로더가 검사한다)."""

    review_id: str
    forum_id: str
    conference: str
    title: str
    split: str
    sentences: tuple[str, ...]
    suffixes: tuple[str, ...]
    annotations: tuple[Annotation, ...]

    @property
    def text(self) -> str:
        return "".join(s + x for s, x in zip(self.sentences, self.suffixes))

    @property
    def text_sha256(self) -> str:
        return sha256_bytes(self.text.encode("utf-8"))

    @property
    def source_url(self) -> str:
        return f"https://openreview.net/forum?id={self.forum_id}&noteId={self.review_id}"

    @property
    def n_annotators(self) -> int:
        return len(self.annotations)


@dataclass(frozen=True)
class ZipInfo:
    """원본 zip의 출처 정보. `retrieved_at`은 zip 파일을 받은 시각(파일 수정 시각)이다."""

    path: str
    sha256: str
    size: int
    retrieved_at: str
    url: str = DATASET_URL
    license: str = LICENSE

    def as_dict(self) -> dict:
        return {
            "dataset": DATASET_NAME,
            "url": self.url,
            "license": self.license,
            "zip_sha256": self.sha256,
            "zip_size": self.size,
            "retrieved_at": self.retrieved_at,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def default_zip_path() -> Path:
    raw = os.environ.get("NEUMANN_RAW_DIR")
    if not raw:
        raise DisapereError("NEUMANN_RAW_DIR가 없다. --zip으로 DISAPERE.zip 경로를 주거나 환경변수를 설정한다")
    return Path(raw) / ZIP_RELPATH


def zip_info(zip_path: str | os.PathLike[str]) -> ZipInfo:
    path = Path(zip_path)
    if not path.is_file():
        raise DisapereError(f"DISAPERE.zip이 없다: {path}")
    data = path.read_bytes()
    mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    return ZipInfo(
        path=str(path),
        sha256=sha256_bytes(data),
        size=len(data),
        retrieved_at=mtime.isoformat(timespec="seconds"),
    )


def _annotation_from(member: str, raw: bytes, meta: dict, sentences: list[dict]) -> Annotation:
    subset, split = member.split("/")[1:3]
    labels = tuple(
        SentenceLabel(
            index=int(s["sentence_index"]),
            aspect=str(s["aspect"]),
            polarity=str(s["polarity"]),
            review_action=str(s["review_action"]),
            fine_review_action=str(s["fine_review_action"]),
        )
        for s in sentences
    )
    return Annotation(
        annotator=str(meta["annotator"]),
        subset=subset,
        split=split,
        member=member,
        member_sha256=sha256_bytes(raw),
        labels=labels,
    )


def _annotator_key(annotator: str) -> tuple[int, str]:
    digits = re.sub(r"\D", "", annotator)
    return (int(digits) if digits else 10**9, annotator)


def load_reviews(zip_path: str | os.PathLike[str] | None = None) -> list[Review]:
    """zip의 모든 주석 파일을 읽어 심사평 단위로 묶는다. review_id 순으로 돌려준다."""
    path = Path(zip_path) if zip_path is not None else default_zip_path()
    if not path.is_file():
        raise DisapereError(f"DISAPERE.zip이 없다: {path}")

    grouped: dict[str, dict] = {}
    with zipfile.ZipFile(path) as zf:
        members = sorted(n for n in zf.namelist() if _MEMBER_RE.match(n))
        if not members:
            raise DisapereError(f"주석 JSON이 없다(구조 확인 필요): {path}")
        for member in members:
            raw = zf.read(member)
            try:
                doc = json.loads(raw)
                meta = doc["metadata"]
                sents = doc["review_sentences"]
                review_id = str(meta["review_id"])
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise DisapereError(f"{member}: 형식 오류 ({exc.__class__.__name__}: {exc})") from exc
            order = [int(s["sentence_index"]) for s in sents]
            if order != list(range(len(sents))):
                raise DisapereError(f"{member}: 문장 번호가 0부터 연속이 아니다")
            if any(str(s.get("review_id", review_id)) != review_id for s in sents):
                raise DisapereError(f"{member}: 문장의 review_id가 metadata와 다르다")
            texts = tuple(str(s["text"]) for s in sents)
            suffixes = tuple(str(s.get("suffix", "")) for s in sents)
            ann = _annotation_from(member, raw, meta, sents)
            entry = grouped.get(review_id)
            if entry is None:
                grouped[review_id] = {
                    "forum_id": str(meta["forum_id"]),
                    "conference": str(meta.get("conference", "")),
                    "title": str(meta.get("title", "")),
                    "texts": texts,
                    "suffixes": suffixes,
                    "annotations": [ann],
                }
                continue
            if entry["texts"] != texts or entry["suffixes"] != suffixes:
                raise DisapereError(f"{review_id}: 주석자마다 문장 분할이 다르다({member})")
            if entry["forum_id"] != str(meta["forum_id"]):
                raise DisapereError(f"{review_id}: 주석자마다 forum_id가 다르다({member})")
            if any(a.annotator == ann.annotator for a in entry["annotations"]):
                raise DisapereError(f"{review_id}: 같은 주석자({ann.annotator}) 파일이 두 개다")
            entry["annotations"].append(ann)

    reviews: list[Review] = []
    for review_id in sorted(grouped):
        e = grouped[review_id]
        anns = tuple(sorted(e["annotations"], key=lambda a: _annotator_key(a.annotator)))
        splits = {a.split for a in anns}
        if len(splits) != 1:
            raise DisapereError(f"{review_id}: 주석 파일마다 split이 다르다({sorted(splits)})")
        reviews.append(
            Review(
                review_id=review_id,
                forum_id=e["forum_id"],
                conference=e["conference"],
                title=e["title"],
                split=splits.pop(),
                sentences=e["texts"],
                suffixes=e["suffixes"],
                annotations=anns,
            )
        )
    return reviews


def count_members(zip_path: str | os.PathLike[str]) -> int:
    with zipfile.ZipFile(zip_path) as zf:
        return sum(1 for n in zf.namelist() if _MEMBER_RE.match(n))
