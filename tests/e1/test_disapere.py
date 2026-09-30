"""DISAPERE 로더 테스트. 기본은 합성 zip(직접 지은 문장)으로 돈다.
실제 원본 검사는 NEUMANN_RAW_DIR에 DISAPERE.zip이 있을 때만 돈다(원본은 저장소에 없다)."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from neumann.sources import disapere


def _doc(review_id, annotator, sents, forum="FORUM1", reviewer="AnonReviewer9"):
    return {
        "metadata": {
            "forum_id": forum,
            "review_id": review_id,
            "rebuttal_id": "REB",
            "title": "A synthetic paper",
            "reviewer": reviewer,
            "rating": 5,
            "conference": "ICLR2019",
            "permalink": f"https://openreview.net/forum?id={forum}&noteId=REB",
            "annotator": annotator,
        },
        "review_sentences": [
            {
                "review_id": review_id,
                "sentence_index": i,
                "text": text,
                "suffix": suffix,
                "review_action": "arg_evaluative",
                "fine_review_action": "none",
                "aspect": aspect,
                "polarity": polarity,
            }
            for i, (text, suffix, aspect, polarity) in enumerate(sents)
        ],
        "rebuttal_sentences": [],
    }


SENTS_A = [
    ("The method is interesting.", " ", "none", "pol_positive"),
    ("The experiments are too small.", "\n", "asp_substance", "pol_negative"),
]
SENTS_B = [("Missing a baseline comparison.", "", "asp_meaningful-comparison", "pol_negative")]


def make_zip(path: Path, docs: dict[str, dict]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("DISAPERE/", "")
        zf.writestr("DISAPERE/documentation/annotation_guidelines.pdf", b"%PDF-fake")
        for member, doc in docs.items():
            zf.writestr(member, json.dumps(doc))
    return path


@pytest.fixture
def fake_zip(tmp_path):
    return make_zip(
        tmp_path / "DISAPERE.zip",
        {
            "DISAPERE/final_dataset/train/RevA.json": _doc("RevA", "anno3", SENTS_A),
            "DISAPERE/extra_annotations/train/RevA.anno12.json": _doc("RevA", "anno12", SENTS_A),
            "DISAPERE/extra_annotations/train/RevA.anno2.json": _doc("RevA", "anno2", SENTS_A),
            "DISAPERE/final_dataset/test/RevB.json": _doc("RevB", "anno5", SENTS_B, forum="FORUM2"),
        },
    )


def test_groups_annotations_by_review(fake_zip):
    reviews = disapere.load_reviews(fake_zip)
    assert [r.review_id for r in reviews] == ["RevA", "RevB"]
    a, b = reviews
    assert a.n_annotators == 3 and b.n_annotators == 1
    # 주석자 순서: 숫자 기준(anno2, anno3, anno12)
    assert [x.annotator for x in a.annotations] == ["anno2", "anno3", "anno12"]
    assert a.split == "train" and b.split == "test"
    assert {x.subset for x in a.annotations} == {"final_dataset", "extra_annotations"}


def test_text_offsets_and_provenance(fake_zip):
    a = disapere.load_reviews(fake_zip)[0]
    assert a.sentences == ("The method is interesting.", "The experiments are too small.")
    assert a.text == "The method is interesting. The experiments are too small.\n"
    # 문장이 전체 본문에 그대로 들어 있다(오프셋으로 잘라 인용할 수 있어야 한다)
    start = a.text.index(a.sentences[1])
    assert a.text[start : start + len(a.sentences[1])] == a.sentences[1]
    assert len(a.text_sha256) == 64
    assert a.source_url == "https://openreview.net/forum?id=FORUM1&noteId=RevA"
    for ann in a.annotations:
        assert ann.member.startswith("DISAPERE/") and len(ann.member_sha256) == 64
    info = disapere.zip_info(fake_zip)
    assert info.url == disapere.DATASET_URL and info.license == "CC BY-NC 4.0"
    assert len(info.sha256) == 64 and info.retrieved_at[:2] == "20"
    assert disapere.count_members(fake_zip) == 4


def test_sentence_labels_kept(fake_zip):
    a = disapere.load_reviews(fake_zip)[0]
    labels = a.annotations[0].labels
    assert [(s.index, s.aspect, s.polarity) for s in labels] == [
        (0, "none", "pol_positive"),
        (1, "asp_substance", "pol_negative"),
    ]


def test_reviewer_identity_not_exposed(fake_zip):
    reviews = disapere.load_reviews(fake_zip)
    dumped = repr(reviews)
    assert "AnonReviewer9" not in dumped
    assert not hasattr(reviews[0], "reviewer")


def test_inconsistent_segmentation_is_error(tmp_path):
    other = [("The method is interesting.", " ", "none", "none")]
    z = make_zip(
        tmp_path / "bad.zip",
        {
            "DISAPERE/final_dataset/dev/RevC.json": _doc("RevC", "anno1", SENTS_A),
            "DISAPERE/extra_annotations/dev/RevC.anno2.json": _doc("RevC", "anno2", other),
        },
    )
    with pytest.raises(disapere.DisapereError, match="문장 분할"):
        disapere.load_reviews(z)


def test_duplicate_annotator_is_error(tmp_path):
    z = make_zip(
        tmp_path / "dup.zip",
        {
            "DISAPERE/final_dataset/dev/RevC.json": _doc("RevC", "anno1", SENTS_A),
            "DISAPERE/extra_annotations/dev/RevC.anno1.json": _doc("RevC", "anno1", SENTS_A),
        },
    )
    with pytest.raises(disapere.DisapereError, match="같은 주석자"):
        disapere.load_reviews(z)


def test_missing_zip_is_clear_error(tmp_path):
    with pytest.raises(disapere.DisapereError, match="없다"):
        disapere.load_reviews(tmp_path / "nope.zip")


def test_default_path_needs_env(monkeypatch):
    monkeypatch.delenv("NEUMANN_RAW_DIR", raising=False)
    with pytest.raises(disapere.DisapereError, match="NEUMANN_RAW_DIR"):
        disapere.default_zip_path()
    monkeypatch.setenv("NEUMANN_RAW_DIR", "/raw")
    assert disapere.default_zip_path() == Path("/raw") / "data" / "disapere" / "DISAPERE.zip"


def _real_zip() -> Path | None:
    raw = os.environ.get("NEUMANN_RAW_DIR")
    if not raw:
        return None
    p = Path(raw) / disapere.ZIP_RELPATH
    return p if p.is_file() else None


@pytest.mark.skipif(_real_zip() is None, reason="DISAPERE.zip 원본 없음(NEUMANN_RAW_DIR)")
def test_real_zip_counts():
    z = _real_zip()
    assert disapere.count_members(z) == 767
    reviews = disapere.load_reviews(z)
    assert len(reviews) == 506
    by_n = {}
    for r in reviews:
        by_n[r.n_annotators] = by_n.get(r.n_annotators, 0) + 1
    assert by_n == {1: 358, 2: 64, 3: 55, 4: 29}
    assert sum(v for k, v in by_n.items() if k >= 2) == 148
