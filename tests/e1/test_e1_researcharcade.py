"""E1-L0 ResearchArcade 수집기: 작은 가짜 parquet로 선별·연결·정규화·결정성·신원 제거를 검사한다."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from neumann.models import (
    Decision,
    DecisionOutcome,
    Excerpt,
)
from neumann.sources import researcharcade as ra
from neumann.sources.corpus import audit_processed, load_corpus

# ── 키워드 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("keyword", "text", "expected"),
    [
        ("molecul*", "Molecular property prediction", True),
        ("molecul*", "biomolecular", False),  # 단어 경계에서 시작
        ("single-cell", "single cell RNA-seq", True),
        ("single-cell", "single-cell atlas", True),
        ("rna", "internal representation", False),
        ("rna", "RNA secondary structure", True),
        ("materials science", "materials-science workflows", True),
        ("catalysis", "a catalyst for progress", False),
        ("pde", "PDE-constrained learning", True),
        ("weather forecast*", "medium-range weather forecasting", True),
        ("weather forecast*", "robust to weather conditions", False),
    ],
)
def test_keyword_regex(keyword: str, text: str, expected: bool) -> None:
    assert bool(ra.keyword_regex(keyword).search(text)) is expected


def test_match_fields_selects_science_and_rejects_general_ml() -> None:
    hits = ra.match_fields("Equivariant GNNs for protein-ligand docking", "We predict binding affinity.")
    assert list(hits) == ["protein_biology_drug"]
    assert {"protein*", "ligand*", "docking", "binding affinit*"} <= set(hits["protein_biology_drug"])
    multi = ra.match_fields("Neural operators for molecular dynamics", "We solve PDEs for chemistry.")
    assert list(multi) == ["materials_chemistry_molecules", "physics_pde_climate"]  # 분야 순서 고정
    assert ra.match_fields("Scaling laws for LLM pretraining", "Supplementary material has code.") == {}
    # 일반 그래프 ML 벤치마크 이름은 지운다
    assert ra.match_fields("Deep GNN distillation", "Results on ogbn-proteins and ogbn-arxiv.") == {}


def test_keyword_hash_is_stable_and_sensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    h1 = ra.keywords_sha256()
    assert h1 == ra.keywords_sha256()
    changed = {**ra.FIELD_KEYWORDS, "physics_pde_climate": ra.FIELD_KEYWORDS["physics_pde_climate"] + ("x",)}
    monkeypatch.setattr(ra, "FIELD_KEYWORDS", changed)
    assert ra.keywords_sha256() != h1


# ── 결정 확장 매핑 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "outcome"),
    [
        ("Rejected_Submission", DecisionOutcome.reject),
        ("Desk_Rejected_Submission", DecisionOutcome.desk_reject),
        ("Withdrawn_Submission", DecisionOutcome.withdrawn),
        ("ICLR 2025 Poster", DecisionOutcome.accept_poster),
        ("ICLR 2025 Spotlight", DecisionOutcome.accept_spotlight),
        ("ICLR 2025 Oral", DecisionOutcome.accept_oral),
        ("ICLR 2024 poster", DecisionOutcome.accept_poster),
        ("ICLR 2024 spotlight", DecisionOutcome.accept_spotlight),
        ("ICLR 2024 oral", DecisionOutcome.accept_oral),
        ("Accept (poster)", DecisionOutcome.accept_poster),
        ("Accept (Oral)", DecisionOutcome.accept_oral),
        ("Reject", DecisionOutcome.reject),
    ],
)
def test_map_decision_extended(raw: str, outcome: DecisionOutcome) -> None:
    got, rule = ra.map_decision(raw)
    assert got == outcome
    assert rule.startswith("researcharcade_ext:")


def test_map_decision_unmatched_keeps_raw() -> None:
    got, rule = ra.map_decision("Invite to Workshop Track")
    assert got == DecisionOutcome.unknown
    assert rule == "unmatched:Invite to Workshop Track"
    Decision.model_validate(  # unknown도 원문과 규칙을 남기면 저장 가능
        {
            "provenance": _prov(),
            "decision_id": "d1",
            "work_id": "w1",
            "outcome": got,
            "outcome_raw": "Invite to Workshop Track",
            "mapping_rule": rule,
        }
    )


# ── 신원 제거·정규화 ─────────────────────────────────────────────────────


def test_redact_identity() -> None:
    text = "Contact jane.doe@uni.edu, ORCID 0000-0002-1825-0097, see ~Jane_Doe1. vIoU@0.3 is a metric."
    out, n = ra.redact_identity(text)
    assert "jane.doe@uni.edu" not in out and "0000-0002-1825-0097" not in out and "~Jane_Doe1" not in out
    assert "[EMAIL]" in out and "[ORCID]" in out and "[PROFILE]" in out
    assert "vIoU@0.3" in out  # 지표 표기는 건드리지 않는다
    assert n == 3


def test_compose_sections_order_and_boilerplate() -> None:
    content = {
        "Rating": "6: marginally above",
        "Weaknesses": "  W1\r\nW2  ",
        "Summary": "Café study",  # NFD
        "Strengths": "",
        "Questions": None,
        "Soundness": "3 good",
    }
    out = ra.compose_sections(content, ra.OFFICIAL_SECTIONS)
    assert out == "Summary:\nCafé study\n\nWeaknesses:\nW1\nW2"
    assert unicodedata.is_normalized("NFC", out)
    assert "Rating" not in out and "Soundness" not in out and "Strengths" not in out


# ── 가짜 원본으로 전체 조립 ───────────────────────────────────────────────

P24, P25 = "ICLR.cc/2024/Conference", "ICLR.cc/2025/Conference"

PAPERS = [
    # (venue, id, title, abstract, decision)
    (P25, "PaperMol01", "Diffusion for molecule generation", "We generate 3D molecules with chemistry priors.", "ICLR 2025 Poster"),
    (P24, "PaperPde02", "Neural operator for PDEs", "Fourier neural operator for Navier-Stokes. Contact a@b.com", "Rejected_Submission"),
    (P25, "PaperGen03", "Better LLM prompting", "We improve chain-of-thought prompting.", "Rejected_Submission"),
    (P25, "PaperDesk04", "Protein folding shortcut", "Protein structure prediction.", "Desk_Rejected_Submission"),
    ("NeurIPS.cc/2024/Conference", "PaperNip05", "Protein design", "Protein design with diffusion.", "Accept"),
    (P24, "PaperBio06", "Single-cell foundation model", "Gene expression atlas.", "ICLR 2024 spotlight"),
]


def _review(nid, reply, writer, title, content, time="2024-11-04 01:05:41", venue=P25):
    return {
        "venue": venue,
        "review_openreview_id": nid,
        "replyto_openreview_id": reply,
        "writer": writer,
        "title": title,
        "content": json.dumps(content),
        "time": time,
    }


REVIEWS = [
    _review(
        "RevA",
        "PaperMol01",
        "Reviewer_AbCd",
        "Official Review by Reviewer_AbCd",
        {
            "Rating": 6,
            "Confidence": 4,
            "Soundness": 3,
            "Summary": "The paper proposes a diffusion model.\r\nIt is Café-grade.",
            "Strengths": "Clear writing.",
            "Weaknesses": "Only one seed. Email me at rev@mail.org.",
            "Questions": "",
        },
    ),
    _review(
        "RevB",
        "PaperMol01",
        "Reviewer_EfGh",
        "Official Review by Reviewer_EfGh",
        {"Rating": 5, "Confidence": 3, "Summary": "Baselines are missing.", "Strengths": "-", "Weaknesses": "No ablation.", "Questions": "Why?"},
        time="2024-11-02 10:00:00",
    ),
    _review(
        "MetaC",
        "PaperMol01",
        "Area_Chair_XyZ1",
        "Meta Review of Submission12 by Area_Chair_XyZ1",
        {"Meta Review": "Accept.", "Additional Comments On Reviewer Discussion": ""},
        time="2024-12-01 00:00:00",
    ),
    _review("DecD", "PaperMol01", "Program_Chairs", "Paper Decision", {"Decision": "Accept (Poster)", "Comment": ""}),
    _review("AnsE", "RevA", "Authors", "Response by Authors", {"Title": "Rebuttal by Authors", "Comment": "We added three seeds."}),
    _review("AnsF", "AnsE", "Authors", "Response by Authors", {"Title": "Follow-up", "Comment": "More results.\r\nThanks."}),
    _review("AnsG", "PaperMol01", "Authors", "Response by Authors", {"Title": "General response", "Comment": "Summary of changes."}),
    _review("AnsEmpty", "RevB", "Authors", "Response by Authors", {"Title": "t", "Comment": "   "}),
    _review("CmtH", "RevA", "Reviewer_AbCd", "Response by Reviewer", {"Title": "t", "Comment": "Thanks, raising score."}),
    _review("PubI", "PaperMol01", "~Jane_Doe1", "Response by ~Jane_Doe1", {"Title": "t", "Comment": "Public note."}),
    _review("RevJ", "PaperGen03", "Reviewer_Klmn", "Official Review by Reviewer_Klmn", {"Rating": 3, "Summary": "Not science.", "Weaknesses": "x"}),
    _review("OrphK", "MissingParent", "Authors", "Response by Authors", {"Title": "t", "Comment": "orphan"}),
    _review(
        "RevL",
        "PaperBio06",
        "Reviewer_Opqr",
        "Official Review by Reviewer_Opqr",
        {"Rating": "8: accept, good paper", "Confidence": "4: confident", "Summary": "Useful atlas; see ~John_Smith2.", "Weaknesses": "Leakage."},
        venue=P24,
    ),
    _review("DecM", "PaperBio06", "Program_Chairs", "Paper Decision", {"Decision": "Accept (spotlight)", "Comment": "Nice work."}, venue=P24),
]


@pytest.fixture()
def raw_dir(tmp_path: Path) -> Path:
    root = tmp_path / "raw"
    (root / "data/researcharcade/papers").mkdir(parents=True)
    (root / "data/researcharcade/reviews").mkdir(parents=True)
    cols = ["venue", "paper_openreview_id", "title", "abstract", "paper_decision"]
    papers = {c: [p[i] for p in PAPERS] for i, c in enumerate(cols)}
    papers["paper_pdf_link"] = ["/pdf/x.pdf"] * len(PAPERS)
    pq.write_table(pa.table(papers), root / ra.PAPERS_FILE)
    half = len(REVIEWS) // 2
    for rel, rows in zip(ra.REVIEW_FILES, (REVIEWS[:half], REVIEWS[half:])):
        pq.write_table(pa.table({k: [r[k] for r in rows] for k in rows[0]}), root / rel)
    files = []
    for rel in (ra.PAPERS_FILE, *ra.REVIEW_FILES):
        data = (root / rel).read_bytes()
        files.append(
            {
                "path": rel,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "url": f"https://huggingface.co/datasets/x/{rel}",
                "retrieved_at_utc": "2026-09-28T10:25:28Z",
            }
        )
    (root / "manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    return root


@pytest.fixture()
def built(raw_dir: Path, tmp_path: Path) -> tuple[Path, dict]:
    out = tmp_path / "data" / "processed"
    manifest = ra.collect(raw_dir, out)
    return out, manifest


def _prov() -> dict:
    return {
        "source": ra.SOURCE,
        "source_url": "https://openreview.net/forum?id=x",
        "accessed_at": "2026-09-28T10:25:28Z",
        "content_sha256": "0" * 64,
    }


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_selection_population_and_counts(built: tuple[Path, dict]) -> None:
    out, manifest = built
    pop = manifest["population"]
    assert pop["papers_total"] == 5  # NeurIPS 제외
    assert pop["desk_rejected_excluded"] == 1
    assert pop["reviewed_population"] == 4
    sel = manifest["selection"]
    assert sel["works"] == 3  # 분자·PDE·단일세포, 일반 LLM 논문 제외
    assert sel["by_field"] == {"materials_chemistry_molecules": 1, "protein_biology_drug": 1, "physics_pde_climate": 1}
    link = manifest["linking"]
    assert link["official_reviews"] == 3 and link["meta_reviews"] == 1
    assert link["author_responses"] == 3  # 빈 답변 1건은 버림
    assert link["skipped_notes"] == {"empty_author_response": 1, "other_comment": 1, "public_comment": 1}
    assert link["works_without_review_in_shards"] == 1  # PDE 논문
    assert link["orphan_notes_no_paper_in_shards"] == 1
    assert manifest["decisions"]["unknown"] == 0
    assert manifest["decisions"]["reject_ratio"] == pytest.approx(1 / 3, abs=1e-4)
    for name, info in manifest["outputs"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == info["sha256"]


def test_two_runs_same_bytes(raw_dir: Path, tmp_path: Path) -> None:
    a = ra.collect(raw_dir, tmp_path / "a")
    b = ra.collect(raw_dir, tmp_path / "b")
    assert {k: v["sha256"] for k, v in a["outputs"].items()} == {k: v["sha256"] for k, v in b["outputs"].items()}


def test_linking_and_text(built: tuple[Path, dict]) -> None:
    out, _ = built
    corpus = load_corpus(out.parent)  # 데이터 루트를 줘도 processed를 찾는다
    wid = f"{ra.SOURCE}:PaperMol01"
    assert corpus.get_work(wid).fields == ["materials_chemistry_molecules"]
    reviews = corpus.reviews_for(wid)
    assert [r.review_id.split(":")[1] for r in reviews] == ["RevB", "RevA", "MetaC"]  # 작성 시각 순
    rev_a = corpus.get_review(f"{ra.SOURCE}:RevA")
    assert rev_a.text == (
        "Summary:\nThe paper proposes a diffusion model.\nIt is Café-grade.\n\n"
        "Strengths:\nClear writing.\n\nWeaknesses:\nOnly one seed. Email me at [EMAIL]."
    )
    assert rev_a.rating == "6" and rev_a.confidence == "4"
    assert rev_a.url == "https://openreview.net/forum?id=PaperMol01&noteId=RevA"
    by_id = {a.response_id.split(":")[1]: a for a in corpus.responses_for(wid)}
    assert by_id["AnsE"].review_id == f"{ra.SOURCE}:RevA"
    assert by_id["AnsF"].review_id == f"{ra.SOURCE}:RevA"  # 답변의 답변도 원 심사평에 붙는다
    assert by_id["AnsG"].review_id is None  # 전체 답변
    assert by_id["AnsF"].text == "More results.\nThanks."
    dec = corpus.decision_for(wid)
    assert dec.outcome == DecisionOutcome.accept_poster and dec.outcome_raw == "ICLR 2025 Poster"
    assert dec.url.endswith("noteId=DecD")
    pde = corpus.decision_for(f"{ra.SOURCE}:PaperPde02")
    assert pde.outcome == DecisionOutcome.reject and pde.url == "https://openreview.net/forum?id=PaperPde02"
    assert "a@b.com" not in corpus.get_work(f"{ra.SOURCE}:PaperPde02").abstract
    bio = corpus.get_review(f"{ra.SOURCE}:RevL")
    assert "~John_Smith2" not in bio.text and "[PROFILE]" in bio.text
    assert bio.rating == "8: accept, good paper"
    # 저장된 텍스트에서 자른 Excerpt가 원문 대조를 통과한다(오프셋 기준 = 저장 문자열)
    start = rev_a.text.index("Only one seed.")
    ex = Excerpt.from_source(rev_a.text, start, start + len("Only one seed."), source_kind="review", source_id=rev_a.review_id, source_url=rev_a.url)
    assert ex.verify_against(rev_a.text)


def test_provenance_and_identity_invariants(built: tuple[Path, dict]) -> None:
    out, _ = built
    report = audit_processed(out)
    assert report["violations"] == 0
    assert report["records"] == {"works.jsonl": 3, "reviews.jsonl": 4, "author_responses.jsonl": 3, "decisions.jsonl": 3}
    blob = "".join((out / f).read_text(encoding="utf-8") for f in ra.OUTPUT_FILES.values())
    for handle in ("Reviewer_AbCd", "Reviewer_EfGh", "Area_Chair_XyZ1", "~Jane_Doe1", "Program_Chairs", "Public note."):
        assert handle not in blob
    for row in _lines(out / "reviews.jsonl") + _lines(out / "author_responses.jsonl"):
        assert set(row) <= {"provenance", "schema_version", "review_id", "response_id", "work_id", "text", "kind", "url", "created", "rating", "confidence", "review_id"}


def _copy_outputs(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for f in ra.OUTPUT_FILES.values():
        (dst / f).write_bytes((src / f).read_bytes())


def _rewrite(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.mark.parametrize("tamper", ["identity_key", "bad_url", "non_openreview_url", "missing_provenance", "pseudonym"])
def test_audit_detects_violations(built: tuple[Path, dict], tmp_path: Path, tamper: str) -> None:
    """검사기가 실제로 잡는지: 조작한 레코드 하나로 실패해야 한다."""
    out, _ = built
    bad = tmp_path / "bad"
    _copy_outputs(out, bad)
    rows = _lines(bad / "reviews.jsonl")
    if tamper == "identity_key":
        rows[0]["writer"] = "Reviewer_AbCd"
    elif tamper == "bad_url":
        rows[0]["provenance"]["source_url"] = "not a url"
    elif tamper == "non_openreview_url":
        rows[0]["provenance"]["source_url"] = "https://example.com/x"
    elif tamper == "missing_provenance":
        del rows[0]["provenance"]
    elif tamper == "pseudonym":
        rows[0]["reviewer_pseudonym"] = "rvw_0123456789abcdef"
    _rewrite(bad / "reviews.jsonl", rows)
    with pytest.raises(ValueError):
        audit_processed(bad)
