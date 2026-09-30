"""E1-L1c: load_corpus(include=...)로 eLife 코퍼스 합치기, 소스별 전량 검사, eLife 결정 매핑 검사.

가짜 레코드(작은 tmp 폴더)로 돈다. 맨 아래 한 건만 공유 데이터 폴더의 실제 eLife 산출물을 잰다(없으면 건너뜀).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from neumann.sources.corpus import (
    audit_sources,
    check_elife_decisions,
    load_corpus,
    load_sources,
    resolve_sources_dir,
    source_of_work_id,
)

SHA = "a" * 64
OR = "https://openreview.net/forum?id="
API = "https://api.elifesciences.org/articles/"


def _prov(source: str, url: str) -> dict:
    return {"source": source, "source_url": url, "accessed_at": "2026-09-30T10:00:00Z", "content_sha256": SHA}


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _ra_rows() -> dict[str, list[dict]]:
    works, reviews, responses, decisions = [], [], [], []
    for nid in ("abc1", "abc2"):
        url = OR + nid
        wid = f"researcharcade_hf:{nid}"
        works.append({"provenance": _prov("researcharcade_hf", url), "work_id": wid, "title": f"GNN paper {nid}",
                      "url": url, "fields": ["molecule"]})
        reviews.append({"provenance": _prov("researcharcade_hf", url), "review_id": f"{wid}:r1", "work_id": wid,
                        "text": "The method is novel. The ablation is missing.", "kind": "official_review", "url": url})
        responses.append({"provenance": _prov("researcharcade_hf", url), "response_id": f"{wid}:a1", "work_id": wid,
                          "text": "We added the ablation.", "url": url})
        decisions.append({"provenance": _prov("researcharcade_hf", url), "decision_id": f"{wid}:d", "work_id": wid,
                          "outcome": "accept", "outcome_raw": "Accept (poster)", "url": url})
    return {"works.jsonl": works, "reviews.jsonl": reviews, "author_responses.jsonl": responses,
            "decisions.jsonl": decisions}


def _elife_rows() -> dict[str, list[dict]]:
    works, reviews, responses, decisions = [], [], [], []
    # 신모델: 평가 어휘 → no_binary_decision(원문 그대로)
    wid, api = "elife:86740", API + "86740"
    works.append({"provenance": _prov("elife", api), "work_id": wid, "title": "History biases in perceptual decisions",
                  "url": "https://elifesciences.org/articles/86740", "doi": "10.7554/elife.86740", "venue": "eLife",
                  "fields": ["neuro_fmri", "subject:neuroscience"]})
    reviews.append({"provenance": _prov("elife", api), "review_id": f"{wid}:sa0", "work_id": wid,
                    "text": "This work provides valuable insights. The evidence is compelling.",
                    "kind": "editor_assessment", "url": "https://doi.org/10.7554/eLife.86740.3.sa0",
                    "rating": "significance=valuable; strength=compelling"})
    reviews.append({"provenance": _prov("elife", api), "review_id": f"{wid}:sa1", "work_id": wid,
                    "text": "The fMRI analysis is careful. Head motion is not controlled.", "kind": "public_review",
                    "url": "https://doi.org/10.7554/eLife.86740.3.sa1"})
    responses.append({"provenance": _prov("elife", api), "response_id": f"{wid}:sa4", "work_id": wid,
                      "text": "We now regress out motion.", "url": "https://doi.org/10.7554/eLife.86740.3.sa4"})
    decisions.append({"provenance": _prov("elife", api), "decision_id": f"{wid}:decision", "work_id": wid,
                      "outcome": "no_binary_decision", "outcome_raw": "significance=valuable; strength=compelling",
                      "url": "https://doi.org/10.7554/eLife.86740.3.sa0", "mapping_rule": "elife_assessment_vocabulary"})
    # 구모델: 게재 VOR → accept
    wid, api = "elife:55081", API + "55081"
    works.append({"provenance": _prov("elife", api), "work_id": wid, "title": "Brain functional networks in voles",
                  "url": "https://elifesciences.org/articles/55081", "venue": "eLife",
                  "fields": ["neuro_fmri", "medical_imaging"]})
    reviews.append({"provenance": _prov("elife", api), "review_id": f"{wid}:sa1", "work_id": wid,
                    "text": "Acceptance summary:\n\nThe connectivity analysis is sound.", "kind": "decision_letter",
                    "url": "https://doi.org/10.7554/eLife.55081.sa1"})
    responses.append({"provenance": _prov("elife", api), "response_id": f"{wid}:sa2", "work_id": wid,
                      "text": "We thank the reviewers.", "url": "https://doi.org/10.7554/eLife.55081.sa2"})
    decisions.append({"provenance": _prov("elife", api), "decision_id": f"{wid}:decision", "work_id": wid,
                      "outcome": "accept", "outcome_raw": "status=vor; decision letter (pre-2023 model)",
                      "url": "https://doi.org/10.7554/eLife.55081.sa1", "mapping_rule": "elife_published_vor"})
    return {"elife_works.jsonl": works, "elife_reviews.jsonl": reviews, "elife_author_responses.jsonl": responses,
            "elife_decisions.jsonl": decisions}


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    for name, rows in {**_ra_rows(), **_elife_rows()}.items():
        _write(proc / name, rows)
    (proc / "corpus_manifest.json").write_text(json.dumps({"task": "E1-L0"}), encoding="utf-8")
    (proc / "elife_manifest.json").write_text(json.dumps({"task": "E1-L1b", "status": "complete"}), encoding="utf-8")
    return tmp_path / "data"


# ── load_corpus 기본값은 그대로, include로 합치기 ──

def test_default_load_corpus_is_unchanged(data_root: Path) -> None:
    """eLife 파일이 같은 폴더에 있어도 기본 load_corpus는 E1-L0 파일만 읽는다."""
    c = load_corpus(data_root)
    assert sorted(c.works) == ["researcharcade_hf:abc1", "researcharcade_hf:abc2"]
    assert len(c.reviews) == 2 and len(c.decisions) == 2
    assert c.manifest == {"task": "E1-L0"}


def test_include_merges_elife(data_root: Path) -> None:
    c = load_corpus(data_root, include=("researcharcade", "elife"))
    assert len(c) == 4
    assert {source_of_work_id(w) for w in c.works} == {"researcharcade", "elife"}
    assert len(c.reviews) == 5 and len(c.author_responses) == 4 and len(c.decisions) == 4
    assert [r.kind.value for r in c.reviews_for("elife:86740")] == ["editor_assessment", "public_review"]
    assert c.reviews_for("elife:86740", kind="public_review")[0].url.startswith("https://doi.org/10.7554/")
    assert c.decision_for("elife:86740").outcome.value == "no_binary_decision"
    assert c.manifest["include"] == ["researcharcade", "elife"]
    assert c.manifest["sources"]["elife"]["task"] == "E1-L1b"
    assert c.works_in_field("neuro_fmri") and all(w.work_id.startswith("elife:") for w in c.works_in_field("neuro_fmri"))


def test_include_researcharcade_only_equals_default(data_root: Path) -> None:
    a, b = load_corpus(data_root), load_corpus(data_root, include=["researcharcade"])
    assert a.works == b.works and a.reviews == b.reviews and a.decisions == b.decisions
    assert a.author_responses == b.author_responses


def test_elife_only_and_processed_dir(data_root: Path) -> None:
    c = load_sources(data_root / "processed", include=("elife",))
    assert sorted(c.works) == ["elife:55081", "elife:86740"]
    assert resolve_sources_dir(data_root, ("elife",)) == data_root / "processed"


def test_unknown_and_missing_sources(data_root: Path) -> None:
    with pytest.raises(ValueError, match="모르는 소스"):
        load_corpus(data_root, include=("researcharcade", "arxiv"))
    with pytest.raises(ValueError, match="비었다"):
        load_corpus(data_root, include=())
    with pytest.raises(FileNotFoundError):
        load_corpus(data_root, include=("researcharcade", "europepmc"))
    (data_root / "processed" / "elife_decisions.jsonl").unlink()
    with pytest.raises(FileNotFoundError, match="elife"):
        load_corpus(data_root, include=("researcharcade", "elife"))


def test_duplicate_work_id_across_sources(data_root: Path) -> None:
    p = data_root / "processed" / "elife_works.jsonl"
    rows = _read(p)
    rows[0]["work_id"] = "researcharcade_hf:abc1"
    _write(p, rows)
    with pytest.raises(ValueError, match="겹치는 work_id"):
        load_corpus(data_root, include=("researcharcade", "elife"))


def test_orphan_elife_review(data_root: Path) -> None:
    p = data_root / "processed" / "elife_reviews.jsonl"
    rows = _read(p)
    rows[0]["work_id"] = "elife:99999"
    _write(p, rows)
    with pytest.raises(ValueError, match="논문이 없는 레코드"):
        load_corpus(data_root, include=("researcharcade", "elife"))


# ── 전량 검사: 출처 URL 100%·원문 해시·신원 필드 0 ──

def test_audit_sources_passes(data_root: Path) -> None:
    a = audit_sources(data_root, include=("researcharcade", "elife"))
    assert a["violations"] == 0 and a["identity_key_records"] == 0
    assert a["source_url_ratio"] == a["deeplink_ratio"] == a["content_sha256_ratio"] == 1.0
    assert a["records"]["elife"] == {"elife_works.jsonl": 2, "elife_reviews.jsonl": 3,
                                      "elife_author_responses.jsonl": 2, "elife_decisions.jsonl": 2}
    assert a["records_total"] == 8 + 9


@pytest.mark.parametrize(
    ("tamper", "match"),
    [
        ("other_host", "원문 URL이 아니다"),
        ("identity_key", "신원 키"),
        ("no_deeplink", "딥링크"),
        ("wrong_source", "provenance.source"),
        ("wrong_namespace", "네임스페이스"),
        ("bad_hash", "검증 실패"),
    ],
)
def test_audit_sources_detects_violations(data_root: Path, tamper: str, match: str) -> None:
    p = data_root / "processed" / "elife_reviews.jsonl"
    rows = _read(p)
    r = rows[1]
    if tamper == "other_host":
        r["provenance"]["source_url"] = "https://example.org/articles/86740"
    elif tamper == "identity_key":
        r["reviewer_name"] = "[NAME]"
    elif tamper == "no_deeplink":
        r.pop("url")
    elif tamper == "wrong_source":
        r["provenance"]["source"] = "europepmc"
    elif tamper == "wrong_namespace":
        r["work_id"] = "europepmc:86740"
    elif tamper == "bad_hash":
        r["provenance"]["content_sha256"] = "not-a-hash"
    _write(p, rows)
    with pytest.raises(ValueError, match=match):
        audit_sources(data_root, include=("researcharcade", "elife"))


# ── eLife 결정 매핑: no_binary_decision(평가 문구 원문 보존) ──

def test_elife_decision_mapping_kept(data_root: Path) -> None:
    c = load_corpus(data_root, include=("researcharcade", "elife"))
    got = check_elife_decisions(c)
    assert got["decisions"] == {"accept": 1, "assessment_raw_preserved": 1, "no_binary_decision": 1}


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("outcome", "accept", "평가 어휘인데 accept"),
        ("outcome_raw", "significance=important; strength=compelling", "원문 어휘와 다르다"),
        ("mapping_rule", "guess", "모르는 매핑 규칙"),
    ],
)
def test_elife_decision_mapping_violations(data_root: Path, field: str, value: str, match: str) -> None:
    p = data_root / "processed" / "elife_decisions.jsonl"
    rows = _read(p)
    rows[0][field] = value
    _write(p, rows)
    c = load_corpus(data_root, include=("researcharcade", "elife"))
    with pytest.raises(ValueError, match=match):
        check_elife_decisions(c)


def test_vor_rejected_is_violation(data_root: Path) -> None:
    p = data_root / "processed" / "elife_decisions.jsonl"
    rows = _read(p)
    rows[1]["outcome"] = "reject"
    _write(p, rows)
    with pytest.raises(ValueError, match="게재 VOR인데 reject"):
        check_elife_decisions(load_corpus(data_root, include=("researcharcade", "elife")))


# ── 실제 산출물(공유 데이터 폴더에 eLife가 있을 때만) ──

def _real_root() -> Path | None:
    cand = os.getenv("NEUMANN_DATA_DIR")
    if not cand:
        return None
    try:
        return resolve_sources_dir(cand, ("researcharcade", "elife"))
    except FileNotFoundError:
        return None


REAL = _real_root()


@pytest.mark.skipif(REAL is None, reason="공유 데이터 폴더에 eLife 산출물이 없다")
def test_real_elife_audit_and_mapping(tmp_path: Path) -> None:
    assert REAL is not None
    # eLife 파일만 복사해 잰다(ResearchArcade 전량 검사는 test_e1_corpus_real이 한다)
    for name in ("elife_works.jsonl", "elife_reviews.jsonl", "elife_author_responses.jsonl", "elife_decisions.jsonl"):
        shutil.copyfile(REAL / name, tmp_path / name)
    a = audit_sources(tmp_path, include=("elife",))
    assert a["violations"] == 0 and a["identity_key_records"] == 0
    assert a["source_url_ratio"] == 1.0 and a["content_sha256_ratio"] == 1.0
    assert a["records"]["elife"]["elife_works.jsonl"] >= 300
    c = load_sources(tmp_path, include=("elife",))
    got = check_elife_decisions(c)
    assert got["decisions"]["no_binary_decision"] == got["decisions"]["assessment_raw_preserved"] > 0
