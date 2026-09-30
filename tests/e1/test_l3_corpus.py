"""E1-L3 확대 코퍼스 조립: 가짜 papers + 샤드 0·1(키트) + 샤드 2(L3)로 선별·커버리지·출처·신원·결정성을 검사한다.

E1-L0 모듈(neumann.sources.researcharcade)이 필요하다. 없는 브랜치에서는 건너뛴다(병합 뒤에 돈다).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ra = pytest.importorskip("neumann.sources.researcharcade", reason="E1-L0(researcharcade)가 아직 병합되지 않았다")

from neumann.models import DecisionOutcome  # noqa: E402
from neumann.sources import corpus_l3 as l3  # noqa: E402
from neumann.sources.corpus import audit_processed, load_corpus  # noqa: E402

P24, P25 = "ICLR.cc/2024/Conference", "ICLR.cc/2025/Conference"
L3_AT = "2026-09-30T09:47:52Z"

PAPERS = [
    (P25, "Mol01", "Diffusion for molecule generation", "We generate 3D molecules with chemistry priors.", "ICLR 2025 Poster"),
    (P24, "Pde02", "Neural operator for PDEs", "Fourier neural operator for Navier-Stokes.", "Rejected_Submission"),
    (P25, "Gen03", "Better LLM prompting", "We improve chain-of-thought prompting.", "Rejected_Submission"),
    (P24, "Gen04", "Sparse attention transformers", "Linear-time attention.", "ICLR 2024 poster"),
    (P25, "Gen05", "Robust offline RL", "Conservative value estimates.", "ICLR 2025 Oral"),
    (P25, "Gen06", "Token pruning for ViTs", "Fewer tokens.", "Rejected_Submission"),  # 심사평 없음 → 후보 제외
    (P25, "Desk07", "Protein folding shortcut", "Protein structure.", "Desk_Rejected_Submission"),
    ("NeurIPS.cc/2024/Conference", "Nip08", "Protein design", "Protein design with diffusion.", "Accept"),
    (P24, "Gen09", "Data pruning at scale", "Pruning data.", "Rejected_Submission"),
]


def _note(nid, reply, writer, title, content, time="2024-11-04 01:05:41", venue=P25):
    return {
        "venue": venue,
        "review_openreview_id": nid,
        "replyto_openreview_id": reply,
        "writer": writer,
        "title": title,
        "content": json.dumps(content),
        "time": time,
    }


def _official(nid, pid, handle, summary, venue=P25, time="2024-11-04 01:05:41"):
    return _note(
        nid, pid, handle, f"Official Review by {handle}",
        {"Rating": "5: marginally below", "Confidence": "3", "Summary": summary, "Strengths": "Clear.", "Weaknesses": "Few baselines.", "Questions": "Seeds?"},
        venue=venue, time=time,
    )  # fmt: skip


SHARD0 = [
    _official("RevM1", "Mol01", "Reviewer_AbCd", "Molecules paper; mail me x@y.org"),
    _note("MetaM", "Mol01", "Area_Chair_XyZ1", "Meta Review of Submission1 by Area_Chair_XyZ1", {"Meta Review": "Accept."}, time="2024-12-01 00:00:00"),
    _note("DecM", "Mol01", "Program_Chairs", "Paper Decision", {"Decision": "Accept (Poster)", "Comment": ""}),
    _note("AnsM", "RevM1", "Authors", "Response by Authors", {"Title": "t", "Comment": "We added seeds."}),
    _official("RevG5", "Gen05", "Reviewer_Qq11", "RL paper."),
    _note("DecG5", "Gen05", "Program_Chairs", "Paper Decision", {"Decision": "Accept (Oral)", "Comment": "Great."}),
]
SHARD1 = [
    _official("RevG3", "Gen03", "Reviewer_Ww22", "Prompting paper; see ~Jane_Doe1."),
    _note("CmtG3", "RevG3", "Reviewer_Ww22", "Response by Reviewer", {"Title": "t", "Comment": "Thanks."}),
    _official("RevG9", "Gen09", "Reviewer_Ee33", "Data pruning.", venue=P24),
]
SHARD2 = [  # ICLR 2024 나머지(키트에 없는 샤드)
    _official("RevP2", "Pde02", "Reviewer_Rr44", "Operator paper.", venue=P24, time="2023-11-01 00:00:00"),
    _note("DecP2", "Pde02", "Program_Chairs", "Paper Decision", {"Decision": "Reject", "Comment": "Not enough."}, venue=P24),
    _note("AnsP2", "RevP2", "Authors", "Response by Authors", {"Title": "t", "Comment": "We disagree."}, venue=P24),
    _official("RevG4", "Gen04", "Reviewer_Tt55", "Attention paper.", venue=P24),
    _note("Old23", "OldPaper", "Reviewer_Zz", "Official Review by Reviewer_Zz", {"Summary": "2023."}, venue="ICLR.cc/2023/Conference"),
]
HANDLES = ("Reviewer_AbCd", "Area_Chair_XyZ1", "Program_Chairs", "Reviewer_Qq11", "Reviewer_Ww22", "Reviewer_Ee33",
           "Reviewer_Rr44", "Reviewer_Tt55", "~Jane_Doe1", "x@y.org")  # fmt: skip


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({k: [r[k] for r in rows] for k in rows[0]}), path)


def _entry(root: Path, rel: str, at: str) -> dict:
    data = (root / rel).read_bytes()
    return {"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "url": f"https://huggingface.co/x/{rel}", "retrieved_at_utc": at}


@pytest.fixture()
def dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    kit = tmp_path / "kit"
    cols = ["venue", "paper_openreview_id", "title", "abstract", "paper_decision"]
    papers = {c: [p[i] for p in PAPERS] for i, c in enumerate(cols)}
    papers["paper_pdf_link"] = ["/pdf/x.pdf"] * len(PAPERS)
    (kit / "data/researcharcade/papers").mkdir(parents=True)
    pq.write_table(pa.table(papers), kit / ra.PAPERS_FILE)
    for rel, rows in zip(ra.REVIEW_FILES, (SHARD0, SHARD1)):
        _write_parquet(kit / rel, rows)
    files = [_entry(kit, rel, "2026-09-28T10:25:28Z") for rel in (ra.PAPERS_FILE, *ra.REVIEW_FILES)]
    (kit / "manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    data = tmp_path / "data"
    raw_l3 = data / l3.RAW_SUBDIR
    _write_parquet(raw_l3 / l3.shard_rel_path(2), SHARD2)
    e = _entry(raw_l3, l3.shard_rel_path(2), L3_AT)
    (raw_l3 / l3.SHARD_MANIFEST).write_text(json.dumps({"files": [e]}), encoding="utf-8")
    return kit, raw_l3, data


def _collect(dirs, n: int = 3, out: str = l3.L3_SUBDIR) -> tuple[Path, dict]:
    kit, raw_l3, data = dirs
    manifest = l3.collect_l3(kit, raw_l3, data / out, shards=(0, 1, 2), general_ml_n=n, seed=11)
    return data / out, manifest


def test_coverage_before_after_and_pool(dirs) -> None:
    _, m = _collect(dirs)
    cov = m["coverage"]
    assert cov["before"]["shards"] == [0, 1] and cov["after"]["shards"] == [0, 1, 2]
    # 모집단 7편(데스크 리젝·NeurIPS 제외): 전 4편(Mol01·Gen03·Gen05·Gen09) → 후 6편(+Pde02·Gen04). Gen06은 끝까지 없음
    assert cov["before"]["population"] == {"papers": 7, "with_official_review": 4, "without": 3, "ratio": round(4 / 7, 4)}
    assert cov["after"]["population"] == {"papers": 7, "with_official_review": 6, "without": 1, "ratio": round(6 / 7, 4)}
    assert cov["before"]["ai4science"]["ratio"] == 0.5 and cov["after"]["ai4science"]["ratio"] == 1.0
    assert [c["population_with_official_review"] for c in cov["cumulative"]] == [2, 4, 6]
    shard2 = cov["per_shard"][2]
    assert shard2["origin"] == "l3" and shard2["iclr_2024_2025_notes"] == 4  # 2023 노트는 세지 않는다
    assert shard2["population_papers_with_official_review_in_shard"] == 2
    g = m["selection"]["general_ml_sampling"]
    assert g["pool"] == 4 and g["selected"] == 3 and g["pool_excluded"] == {"no_official_review": 1}


def test_selection_fields_and_groups(dirs) -> None:
    out, m = _collect(dirs)
    corpus = load_corpus(out)
    sel = m["selection"]
    assert sel["works"] == 5 and sel["by_group"] == {"ai4science": 2, "general_ml": 3}
    assert corpus.get_work("researcharcade_hf:Mol01").fields == ["materials_chemistry_molecules"]
    assert corpus.get_work("researcharcade_hf:Pde02").fields == ["physics_pde_climate"]
    general = [w for w in corpus.works.values() if not l3.is_ai4science(w)]
    assert len(general) == 3 and all(w.fields == ["general_ml"] for w in general)
    assert "researcharcade_hf:Gen06" not in corpus.works and "researcharcade_hf:Desk07" not in corpus.works
    for w in general:  # 일반 ML은 결정(수락·거절)과 공식 심사평이 있다
        assert corpus.decision_for(w.work_id).outcome in ra.ACCEPT_OUTCOMES | ra.REJECT_OUTCOMES
        assert corpus.reviews_for(w.work_id, kind="official_review")
    rows = [json.loads(x) for x in (out / "selection.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {(r["group"], r["ai4science"]) for r in rows} == {("ai4science", True), ("general_ml", False)}
    # 표본을 후보보다 크게 부르면 후보 전부(4편)
    _, m_all = _collect(dirs, n=100, out="x/" + l3.L3_SUBDIR)
    assert m_all["selection"]["by_group"]["general_ml"] == 4


def test_l3_shard_provenance_and_decision_note(dirs) -> None:
    out, _ = _collect(dirs)
    corpus = load_corpus(out)
    rev = corpus.get_review("researcharcade_hf:RevP2")  # 샤드 2에서만 온 심사평
    assert rev.provenance.accessed_at == datetime(2026, 9, 30, 9, 47, 52, tzinfo=UTC)
    assert rev.provenance.api_version == "hf-parquet:ulab-ai/ResearchArcade-openreview-reviews@train-00002-of-00006"
    assert rev.url == rev.provenance.source_url == "https://openreview.net/forum?id=Pde02&noteId=RevP2"
    assert corpus.responses_for("researcharcade_hf:Pde02")[0].review_id == "researcharcade_hf:RevP2"
    dec = corpus.decision_for("researcharcade_hf:Pde02")
    assert dec.outcome == DecisionOutcome.reject and dec.url.endswith("noteId=DecP2") and dec.text == "Not enough."
    assert dec.provenance.api_version.endswith("+hf-parquet:ulab-ai/ResearchArcade-openreview-reviews@train-00002-of-00006")
    old = corpus.get_review("researcharcade_hf:RevM1")  # 키트 샤드는 키트 받은 시각
    assert old.provenance.accessed_at == datetime(2026, 9, 28, 10, 25, 28, tzinfo=UTC)


def test_identity_and_audit(dirs, monkeypatch: pytest.MonkeyPatch) -> None:
    out, _ = _collect(dirs)
    blob = "".join((out / f).read_text(encoding="utf-8") for f in ra.OUTPUT_FILES.values())
    for h in HANDLES:
        assert h not in blob
    assert audit_processed(out)["violations"] == 0
    monkeypatch.setattr(l3, "MIN_TOTAL_WORKS", 5)
    rep = l3.audit_l3(out)
    assert rep["works"] == 5 and rep["by_group"] == {"ai4science": 2, "general_ml": 3} and rep["source_url_ratio"] == 1.0
    monkeypatch.setattr(l3, "MIN_TOTAL_WORKS", 6)  # 편수 기준을 실제로 잰다
    with pytest.raises(ValueError, match="편수"):
        l3.audit_l3(out)


@pytest.mark.parametrize("tamper", ["mixed_tags", "no_tags", "general_without_review", "identity_key"])
def test_audit_l3_detects(dirs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    out, _ = _collect(dirs)
    monkeypatch.setattr(l3, "MIN_TOTAL_WORKS", 1)
    works = [json.loads(x) for x in (out / "works.jsonl").read_text(encoding="utf-8").splitlines()]
    reviews = [json.loads(x) for x in (out / "reviews.jsonl").read_text(encoding="utf-8").splitlines()]
    gen = next(w for w in works if w["fields"] == ["general_ml"])
    if tamper == "mixed_tags":
        gen["fields"] = ["general_ml", "physics_pde_climate"]
    elif tamper == "no_tags":
        works[0]["fields"] = []
    elif tamper == "general_without_review":
        reviews = [r for r in reviews if r["work_id"] != gen["work_id"]]
    elif tamper == "identity_key":
        reviews[0]["writer"] = "Reviewer_AbCd"
    (out / "works.jsonl").write_text("".join(json.dumps(w) + "\n" for w in works), encoding="utf-8")
    (out / "reviews.jsonl").write_text("".join(json.dumps(r) + "\n" for r in reviews), encoding="utf-8")
    with pytest.raises(ValueError):
        l3.audit_l3(out)


def test_two_runs_same_bytes_and_output_guard(dirs) -> None:
    kit, raw_l3, data = dirs
    a = l3.collect_l3(kit, raw_l3, data / "a" / l3.L3_SUBDIR, shards=(0, 1, 2), general_ml_n=3, seed=11)
    b = l3.collect_l3(kit, raw_l3, data / "b" / l3.L3_SUBDIR, shards=(0, 1, 2), general_ml_n=3, seed=11)
    assert {k: v["sha256"] for k, v in a["outputs"].items()} == {k: v["sha256"] for k, v in b["outputs"].items()}
    with pytest.raises(ValueError, match="processed_l3"):  # 현재 코퍼스 폴더에는 쓰지 않는다
        l3.collect_l3(kit, raw_l3, data / "processed", shards=(0, 1, 2), general_ml_n=3)
    assert not (data / "processed").exists()
    with pytest.raises(FileNotFoundError):  # 출처(manifest) 없는 샤드는 쓰지 않는다
        l3.resolve_shards(kit, raw_l3, (0, 1, 2, 3))


def test_manifest_inputs_have_sha_and_urls(dirs) -> None:
    _, m = _collect(dirs)
    shards = [i for i in m["inputs"] if "shard" in i]
    assert [(i["shard"], i["origin"]) for i in shards] == [(0, "kit"), (1, "kit"), (2, "l3")]
    assert all(i["manifest_sha256_match"] is True and i["url"] and len(i["sha256"]) == 64 for i in m["inputs"])
    assert m["keywords"]["sha256"] == ra.keywords_sha256()


def test_compare_with_e1_l0_corpus_and_sample(dirs) -> None:
    kit, raw_l3, data = dirs
    ra.collect(kit, data / "processed")  # E1-L0 코퍼스(샤드 0·1)
    out, _ = _collect(dirs)
    cmp = l3.compare_with_processed(out, data / "processed")
    assert cmp["keywords_sha256_same"] and cmp["ai4s_work_ids_equal_processed"]
    assert cmp["works.jsonl"]["identical"] == cmp["works.jsonl"]["processed"] == 2
    assert cmp["reviews.jsonl"]["identical"] == cmp["reviews.jsonl"]["processed"]  # 현재 심사평은 글자 그대로 남는다
    assert cmp["reviews.jsonl"]["added_for_ai4s_works"] == 1  # RevP2(샤드 2)
    assert cmp["decisions.jsonl"]["changed"] == 1 and cmp["decisions.jsonl"]["changed_examples"] == ["researcharcade_hf:Pde02"]
    shards = l3.resolve_shards(kit, raw_l3, (0, 1, 2))
    res = l3.check_sample(out, shards, 4, seed=3)
    assert len(res) == 4 and any(r["shard"] == 2 for r in res)
    assert all(r["stored_equals_rebuilt_from_parquet"] and r["provenance_hash_matches_parquet"] for r in res)
