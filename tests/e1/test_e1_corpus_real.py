"""E1-L0 실제 산출물 전량 검사(공유 데이터 폴더에 코퍼스가 있을 때만 돈다).

데이터 폴더: NEUMANN_DATA_DIR(없으면 설정 기본값). 없으면 건너뛴다(빌더·검증자 환경에서는 있다).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from neumann.models import DecisionOutcome, Excerpt
from neumann.sources import researcharcade as ra
from neumann.sources.corpus import audit_processed, load_corpus, resolve_processed_dir


def _processed() -> Path | None:
    cands = []
    if os.getenv("NEUMANN_DATA_DIR"):
        cands.append(Path(os.environ["NEUMANN_DATA_DIR"]))
    try:
        from neumann.config import get_settings

        cands.append(get_settings().data_dir)
    except Exception:
        pass
    for c in cands:
        try:
            return resolve_processed_dir(c)
        except FileNotFoundError:
            continue
    return None


PROCESSED = _processed()
pytestmark = pytest.mark.skipif(PROCESSED is None, reason="공유 데이터 폴더에 E1-L0 코퍼스가 없다")


@pytest.fixture(scope="module")
def corpus():
    return load_corpus(PROCESSED)


def test_audit_all_records() -> None:
    """레코드 100%: 모델 검증 오류 0, OpenReview 원문 URL, 신원 키 0."""
    report = audit_processed(PROCESSED)
    assert report["violations"] == 0
    assert report["records"]["works.jsonl"] >= 1000
    assert report["records"]["reviews.jsonl"] >= 4000


def test_manifest_matches_files(corpus) -> None:
    m = corpus.manifest
    assert m["keywords"]["sha256"] == ra.keywords_sha256()  # 코드의 키워드와 산출물이 같은 판
    for name, info in m["outputs"].items():
        data = (PROCESSED / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == info["sha256"], name
        assert data.count(b"\n") == info["records"]
    assert m["selection"]["works"] == len(corpus.works)
    assert m["linking"]["official_reviews"] == len([r for r in corpus.reviews if r.kind.value == "official_review"])


def test_selection_and_decisions(corpus) -> None:
    assert all(w.fields and set(w.fields) <= set(ra.FIELD_KEYWORDS) for w in corpus.works.values())
    assert {w.venue for w in corpus.works.values()} == {"ICLR 2024", "ICLR 2025"}
    # 논문마다 결정 1건, unknown 0(확장 매핑), 데스크 리젝은 모집단에서 뺐다
    assert set(corpus.decisions) == set(corpus.works)
    outcomes = {d.outcome for d in corpus.decisions.values()}
    assert DecisionOutcome.unknown not in outcomes and DecisionOutcome.desk_reject not in outcomes
    sel = {json.loads(x)["work_id"]: json.loads(x) for x in (PROCESSED / "selection.jsonl").read_text(encoding="utf-8").splitlines()}
    for wid, w in list(corpus.works.items())[:200]:
        assert ra.match_fields(w.title, w.abstract) == sel[wid]["keywords"]  # 저장된 제목·초록으로 재선별해도 같다


def test_reviews_are_cuttable(corpus) -> None:
    """심사평 텍스트는 Excerpt 오프셋 기준으로 쓸 수 있다(앞 200건, 첫 줄 구간)."""
    for r in corpus.reviews[:200]:
        end = r.text.find("\n") if "\n" in r.text else len(r.text)
        ex = Excerpt.from_source(r.text, 0, end, source_kind="review", source_id=r.review_id, source_url=r.url)
        assert ex.verify_against(r.text)
        assert r.work_id in corpus.works
