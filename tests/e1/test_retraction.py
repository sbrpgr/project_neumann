"""E1-L2 Retraction Watch 소스: 작은 CSV로 도는 기본 테스트(원본 CSV 불필요).

픽스처 행 7개는 실제 RW CSV(스냅샷 2026-09-25)에서 뽑은 행이다. 신원·자유서술 열(Title·Institution·Country·
Author·URLS·Notes)만 가짜 자리표시 값으로 바꿨다 — 그 값이 출력 어디에도 없어야 한다.
마지막 두 행(999000001·999000002)은 빈 행·미지 성격 처리를 보려는 합성 행이다.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from neumann.models import IDENTITY_TOKENS, PostStatus, PostStatusKind, Provenance, Work
from neumann.sources import retraction as rw

HEADER = (
    "Record ID,Title,Subject,Institution,Journal,Publisher,Country,Author,URLS,ArticleType,RetractionDate,"
    "RetractionDOI,RetractionPubMedID,OriginalPaperDate,OriginalPaperDOI,OriginalPaperPubMedID,RetractionNature,"
    "Reason,Paywalled,Notes,"
)
FAKE = {
    "Title": "Placeholder Title Zeta",
    "Institution": "Placeholder Univ Qux; Placeholder Lab Quux",
    "Country": "Placeland",
    "Author": "Pat Placeholder;Sam Standin",
    "URLS": "https://example.org/rw-post-placeholder",
    "Notes": "See also: https://example.org/pubpeer-placeholder",
}
# (Record ID, Subject, Journal, Publisher, ArticleType, RetractionDate, RetractionDOI, RetractionPubMedID,
#  OriginalPaperDate, OriginalPaperDOI, OriginalPaperPubMedID, RetractionNature, Reason, Paywalled)
REAL_ROWS = [
    ("72867", "(B/T) Computer Science;(PHY) Engineering - Electrical;", "Microprocessors and Microsystems", "Elsevier",
     "Research Article;", "6/25/2021 0:00", "10.1016/j.micpro.2021.104304", "0", "2/27/2020 0:00",
     "10.1016/j.micpro.2020.103053", "0", "Expression of concern",
     "Compromised Peer Review;Concerns/Issues about Article;Error by Journal/Publisher;Investigation by Journal/Publisher;"
     "Investigation by Third Party;Objections by Author(s);Rogue Editor;Updated to Retraction;", "No"),
    ("72853", "(B/T) Computer Science;(PHY) Engineering - Electrical;", "Microprocessors and Microsystems", "Elsevier",
     "Research Article;", "2/14/2024 0:00", "10.1016/j.micpro.2024.105024", "0", "2/27/2020 0:00",
     "10.1016/j.micpro.2020.103053", "0", "Retraction",
     "Author Unresponsive;Compromised Peer Review;Error by Journal/Publisher;Investigation by Journal/Publisher;"
     "Investigation by Third Party;Objections by Author(s);Rogue Editor;Upgrade/Update of Prior Notice(s);", "No"),
    ("70548", "(B/T) Computer Science;(PHY) Engineering - General;",
     "EG-ICE 2020 Workshop on Intelligent Computing in Engineering", "Technische Universitat Berlin",
     "Conference Abstract/Paper;", "10/18/2023 0:00", "unavailable", "0", "6/30/2020 0:00", "unavailable", "0",
     "Retraction", "Legal Reasons and/or Threats;", "No"),
    ("67291", "(BLS) Biochemistry;(BLS) Biology - Cancer;(BLS) Biology - Cellular;(HSC) Medicine - Drug Design;"
     "(PHY) Nanotechnology;", "International Journal of Nanomedicine", "Taylor and Francis - Dove Press",
     "Research Article;", "8/4/2022 0:00", "10.2147/IJN.S384663", "35959284", "2/26/2016 0:00", "10.2147/IJN.S97476",
     "27013874", "Correction",
     "Concerns/Issues about Data;Concerns/Issues about Referencing/Attributions;Error in Text;"
     "Investigation by Company/Institution;", "No"),
    ("49720", "(HSC) Biostatistics/Epidemiology;(HSC) Medicine - Cardiovascular;(HSC) Medicine - Surgery;",
     "Circulation: Cardiovascular Quality and Outcomes", "American Heart Association", "Research Article;",
     "11/21/2023 0:00", "10.1161/HCQ.0000000000000125", "37988442", "4/30/2021 0:00",
     "10.1161/CIRCOUTCOMES.120.007778", "33926210", "Reinstatement",
     "Error in Analyses;Error in Results and/or Conclusions;Retract and Replace;", "No"),
    ("40040", "(HSC) Medicine - Obstetrics/Gynecology;(HSC) Medicine - Oncology;(HSC) Medicine - Surgery;"
     "(HSC) Radiology/Imaging;", "Journal of Surgical Oncology", "Wiley", "Research Article;", "8/10/2000 0:00",
     "10.1002/1096-9098(200007)74:3%3C201::AID-JSO8%3E3.0.CO;2-5", "0", "7/1/2000 0:00",
     "10.1002/1096-9098(200007)74:3%3C201::AID-JSO8%3E3.0.CO;2-5", "10951417", "Retraction",
     "Date of Article and/or Notice Unknown;Plagiarism of/in Article;", "No"),
    ("34999", "(BLS) Biology - Cancer;(BLS) Biology - Cellular;(BLS) Genetics;",
     "Therapeutic Advances in Medical Oncology", "SAGE Publications", "Research Article;", "12/15/2021 0:00",
     "10.1177/17588359211061903", "35035532", "9/14/2019 0:00", "10.1177/1758835919874651", "31579114",
     "Retraction", "Concerns/Issues about Data;Concerns/Issues about Results and/or Conclusions;", "No"),
]
SYNTHETIC_UNKNOWN = ("999000002", "(B/T) Computer Science;", "Synthetic Journal", "Synthetic Publisher",
                     "Research Article;", "1/1/2020 0:00", "10.9999/synthetic.notice", "0", "1/1/2019 0:00",
                     "10.9999/synthetic.target", "0", "Mystery Notice", "Paper Mill;", "No")


def _full_row(t: tuple[str, ...]) -> list[str]:
    (rid, subject, journal, publisher, atype, rdate, rdoi, rpmid, odate, odoi, opmid, nature, reason, paywalled) = t
    return [rid, FAKE["Title"], subject, FAKE["Institution"], journal, publisher, FAKE["Country"], FAKE["Author"],
            FAKE["URLS"], atype, rdate, rdoi, rpmid, odate, odoi, opmid, nature, reason, paywalled, FAKE["Notes"], ""]


def _fixture_rows() -> list[list[str]]:
    return [_full_row(t) for t in REAL_ROWS] + [[""] * 21, _full_row(SYNTHETIC_UNKNOWN)]


def _write_fixture(path: Path) -> Path:
    buf = io.StringIO()
    buf.write(HEADER + "\n")
    w = csv.writer(buf, lineterminator="\n")
    for row in _fixture_rows():
        w.writerow(row)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


ACCESSED = datetime(2026, 9, 28, 10, 26, 14, tzinfo=UTC)


@pytest.fixture()
def built(tmp_path: Path) -> tuple[Path, dict]:
    (tmp_path / "raw").mkdir()
    src = _write_fixture(tmp_path / "raw" / "retraction_watch.csv")
    manifest = rw.build(src, tmp_path / "data", accessed_at=ACCESSED)
    return tmp_path / "data", manifest


def _lines(data_dir: Path) -> list[dict]:
    text = (data_dir / "processed" / rw.OUT_JSONL).read_text(encoding="utf-8")
    return [json.loads(x) for x in text.splitlines() if x.strip()]


# ── DOI 정규화 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.1177/1758835919874651", "10.1177/1758835919874651"),
        ("  10.2147/IJN.S97476 ", "10.2147/ijn.s97476"),
        ("https://doi.org/10.2147/IJN.S97476", "10.2147/ijn.s97476"),
        ("http://dx.doi.org/10.2147/IJN.S97476", "10.2147/ijn.s97476"),
        ("doi:10.2147/IJN.S97476", "10.2147/ijn.s97476"),
        ("DOI: 10.2147/IJN.S97476", "10.2147/ijn.s97476"),
        ("10.1002/1096-9098(200007)74:3%3C201::AID-JSO8%3E3.0.CO;2-5",
         "10.1002/1096-9098(200007)74:3<201::aid-jso8>3.0.co;2-5"),
        ("10.1002/1096-9098(200007)74:3%3c201::aid-jso8%3e3.0.co;2-5",
         "10.1002/1096-9098(200007)74:3<201::aid-jso8>3.0.co;2-5"),
        ("unavailable", None),
        ("Unavailable", None),
        ("", None),
        (None, None),
        ("xx10.1007/978-3-030-00524-5_9", None),
        ("not a doi", None),
    ],
)
def test_normalize_doi(raw: str | None, expected: str | None) -> None:
    assert rw.normalize_doi(raw) == expected


def test_normalize_doi_agrees_with_work_contract() -> None:
    raw = "https://doi.org/10.2147/IJN.S97476"
    w = Work(
        work_id="x:1", title="t", url="https://example.org/w",
        doi=raw,
        provenance=Provenance(source="test", source_url="https://example.org/w", accessed_at=ACCESSED,
                              content_sha256="0" * 64),
    )
    assert rw.normalize_doi(raw) == w.doi


def test_doi_url_encodes_unsafe_chars() -> None:
    url = rw.doi_url("10.1002/1096-9098(200007)74:3<201::aid-jso8>3.0.co;2-5")
    assert url == "https://doi.org/10.1002/1096-9098(200007)74:3%3C201::aid-jso8%3E3.0.co;2-5"
    assert rw.doi_url("10.1177/17588359211061903") == "https://doi.org/10.1177/17588359211061903"


# ── 빌드 영수증 ───────────────────────────────────────────────────────────


def test_build_counts(built: tuple[Path, dict]) -> None:
    _, m = built
    assert m["rows_read"] == 9
    assert m["records_written"] == 6
    assert m["facet_records"] == 7  # 대상 DOI가 없는 70548도 분야 prior에는 들어간다
    assert m["skipped"] == {"blank_rows": 1, "unknown_nature": 1, "no_target_doi": 1}
    assert m["unknown_nature_values"] == {"Mystery Notice": 1}
    assert m["kind_distribution_all_rows"] == {
        "correction": 1, "expression_of_concern": 1, "reinstatement": 1, "retraction": 4,
    }
    assert m["kind_distribution_written"] == {
        "correction": 1, "expression_of_concern": 1, "reinstatement": 1, "retraction": 3,
    }
    assert m["unique_target_dois"] == 5
    assert m["snapshot_generated"] is None  # 픽스처 옆에 README가 없다
    assert m["corpus_join"]["status"] == "corpus_missing"
    out = m["outputs"][rw.OUT_JSONL]
    data = (built[0] / "processed" / rw.OUT_JSONL).read_bytes()
    assert out["lines"] == 6 and out["sha256"] == hashlib.sha256(data).hexdigest()
    saved = json.loads((built[0] / "processed" / rw.OUT_MANIFEST).read_text(encoding="utf-8"))
    assert saved["records_written"] == 6


def test_build_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    src = _write_fixture(tmp_path / "raw" / "retraction_watch.csv")
    a = rw.build(src, tmp_path / "a", accessed_at=ACCESSED)
    b = rw.build(src, tmp_path / "b", accessed_at=ACCESSED)
    assert a["outputs"] == b["outputs"]


def test_every_line_is_valid_post_status_with_provenance(built: tuple[Path, dict]) -> None:
    data_dir, _ = built
    by_id = {r[0]: r for r in _fixture_rows()}
    for rec in _lines(data_dir):
        ps = PostStatus.model_validate(rec)
        prov = ps.provenance
        assert prov.source == "retraction_watch"
        assert prov.source_url == rw.DATASET_URL
        assert prov.accessed_at == ACCESSED
        rid = ps.post_status_id.removeprefix("rw:")
        # 원본 행 해시를 테스트가 따로 다시 계산해 대조한다
        raw = json.dumps(by_id[rid], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        assert prov.content_sha256 == hashlib.sha256(raw).hexdigest()
        assert ps.target_doi and ps.work_id is None
        if ps.notice_doi:
            assert ps.url == rw.doi_url(ps.notice_doi)


# ── 조회 ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "10.1177/1758835919874651",
        "10.1177/1758835919874651 ",
        "https://doi.org/10.1177/1758835919874651",
        "DOI:10.1177/1758835919874651",
    ],
)
def test_known_doi_lookup(built: tuple[Path, dict], query: str) -> None:
    data_dir, _ = built
    got = rw.get_post_status(query, data_dir=data_dir)
    assert [s.post_status_id for s in got] == ["rw:34999"]
    s = got[0]
    assert s.kind is PostStatusKind.retraction
    assert s.target_doi == "10.1177/1758835919874651"
    assert s.notice_doi == "10.1177/17588359211061903"
    assert s.url == "https://doi.org/10.1177/17588359211061903"
    assert s.reason_codes == ["Concerns/Issues about Data", "Concerns/Issues about Results and/or Conclusions"]


def test_one_paper_with_two_notices(built: tuple[Path, dict]) -> None:
    got = rw.get_post_status("10.1016/J.MICPRO.2020.103053", data_dir=built[0])
    assert {(s.post_status_id, s.kind.value) for s in got} == {
        ("rw:72867", "expression_of_concern"),
        ("rw:72853", "retraction"),
    }
    eoc = next(s for s in got if s.post_status_id == "rw:72867")
    # 원문 그대로: 순서·철자 유지, 끝 ';'만 떨어진다
    assert eoc.reason_codes == [
        "Compromised Peer Review", "Concerns/Issues about Article", "Error by Journal/Publisher",
        "Investigation by Journal/Publisher", "Investigation by Third Party", "Objections by Author(s)",
        "Rogue Editor", "Updated to Retraction",
    ]


@pytest.mark.parametrize(
    ("doi", "rid", "kind"),
    [
        ("10.2147/IJN.S97476", "rw:67291", PostStatusKind.correction),
        ("10.1161/CIRCOUTCOMES.120.007778", "rw:49720", PostStatusKind.reinstatement),
        ("10.1002/1096-9098(200007)74:3<201::AID-JSO8>3.0.CO;2-5", "rw:40040", PostStatusKind.retraction),
    ],
)
def test_kind_mapping_and_case_insensitive(built: tuple[Path, dict], doi: str, rid: str, kind: PostStatusKind) -> None:
    got = rw.get_post_status(doi, data_dir=built[0])
    assert [(s.post_status_id, s.kind) for s in got] == [(rid, kind)]


def test_sici_notice_url_is_encoded(built: tuple[Path, dict]) -> None:
    (s,) = rw.get_post_status("10.1002/1096-9098(200007)74:3%3C201::AID-JSO8%3E3.0.CO;2-5", data_dir=built[0])
    assert s.url == "https://doi.org/10.1002/1096-9098(200007)74:3%3C201::aid-jso8%3E3.0.co;2-5"


@pytest.mark.parametrize(
    "doi",
    [
        "10.1177/17588359211061903",  # 공지 DOI: 원논문 기준 조회라 걸리면 안 된다(방향 함정)
        "10.1016/j.micpro.2024.105024",  # 공지 DOI
        "10.1000/does-not-exist",
        "10.9999/synthetic.target",  # 성격을 모르는 행은 저장하지 않았다
        "unavailable",
        "",
    ],
)
def test_unknown_or_notice_doi_returns_empty(built: tuple[Path, dict], doi: str) -> None:
    assert rw.get_post_status(doi, data_dir=built[0]) == []


def test_lookup_returns_fresh_objects(built: tuple[Path, dict]) -> None:
    a = rw.get_post_status("10.1177/1758835919874651", data_dir=built[0])
    a[0].reason_codes.append("tampered")
    b = rw.get_post_status("10.1177/1758835919874651", data_dir=built[0])
    assert "tampered" not in b[0].reason_codes


# ── 신원 정보 ─────────────────────────────────────────────────────────────


def _all_keys(obj: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(k)
            keys |= _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            keys |= _all_keys(v)
    return keys


def test_no_identity_fields_or_values(built: tuple[Path, dict]) -> None:
    data_dir, _ = built
    keys: set[str] = set()
    for rec in _lines(data_dir):
        keys |= _all_keys(rec)
    bad = {k for k in keys if any(tok in k.lower() for tok in IDENTITY_TOKENS)}
    assert bad == set()
    for name in (rw.OUT_JSONL, rw.OUT_FACETS, rw.OUT_MANIFEST):
        text = (data_dir / "processed" / name).read_text(encoding="utf-8")
        for col, value in FAKE.items():
            for piece in value.split(";"):
                assert piece.strip() not in text, f"{name}에 {col} 값이 남았다"
    facets = json.loads((data_dir / "processed" / rw.OUT_FACETS).read_text(encoding="utf-8"))
    assert set(facets) == {"schema", "citation", "snapshot", "kinds", "subjects", "reasons", "records"}


# ── 분야 prior ─────────────────────────────────────────────────────────────


def test_field_prior_computer_science(built: tuple[Path, dict]) -> None:
    p = rw.field_failure_prior(["computer science"], data_dir=built[0])
    assert p["status"] == "ok"
    assert [m["subject"] for m in p["matched_subjects"]] == ["(B/T) Computer Science"]
    # 철회·우려표명 중 CS: 72867(EoC), 72853, 70548(DOI 없음도 포함)
    assert p["n_records"] == 3
    assert p["n_baseline"] == 5  # 72867, 72853, 70548, 40040, 34999
    rows = {r["reason"]: r for r in p["reasons"]}
    assert rows["Compromised Peer Review"]["records"] == 2
    assert rows["Compromised Peer Review"]["share"] == round(2 / 3, 4)
    assert rows["Compromised Peer Review"]["baseline_share"] == round(2 / 5, 4)
    assert rows["Compromised Peer Review"]["risk_code"] == "R9.5"
    assert rows["Legal Reasons and/or Threats"]["records"] == 1
    assert "Investigation by Journal/Publisher" not in rows  # 절차 코드는 기본 제외
    assert all(not r["procedural"] for r in p["reasons"])
    risk = {r["risk_code"]: r for r in p["risk_codes"]}
    assert risk["R9.5"]["records"] == 2 and risk["R9.9"]["records"] == 1
    assert p["source"]["citation"] == rw.CITATION


def test_field_prior_procedural_and_kinds(built: tuple[Path, dict]) -> None:
    p = rw.field_failure_prior(["Computer Science"], data_dir=built[0], include_procedural=True, top_k=50)
    rows = {r["reason"]: r for r in p["reasons"]}
    assert rows["Investigation by Journal/Publisher"]["procedural"] is True
    q = rw.field_failure_prior(["Nanotechnology"], data_dir=built[0], kinds=["correction"])
    assert q["n_records"] == 1 and q["n_baseline"] == 1
    assert {r["reason"] for r in q["reasons"]} == {
        "Concerns/Issues about Data", "Concerns/Issues about Referencing/Attributions", "Error in Text",
    }


def test_field_prior_word_boundary_and_no_match(built: tuple[Path, dict]) -> None:
    p = rw.field_failure_prior(["chemistry"], data_dir=built[0])  # Biochemistry에 걸리면 안 된다
    assert p["status"] == "no_match" and p["n_records"] == 0 and p["reasons"] == []
    assert rw.field_failure_prior([], data_dir=built[0])["status"] == "no_match"
    multi = rw.field_failure_prior(["oncology", "cancer"], data_dir=built[0])
    # 40040(Oncology), 34999(Cancer): 레코드 단위로 한 번씩
    assert multi["n_records"] == 2


# ── 코퍼스 조인 ───────────────────────────────────────────────────────────


def _work(work_id: str, doi: str | None) -> str:
    w = Work(
        work_id=work_id, title="t", url=f"https://openreview.net/forum?id={work_id}", doi=doi,
        provenance=Provenance(source="test", source_url=f"https://openreview.net/forum?id={work_id}",
                              accessed_at=ACCESSED, content_sha256="0" * 64),
    )
    return w.model_dump_json(exclude_none=True)


def test_join_corpus(built: tuple[Path, dict]) -> None:
    data_dir, _ = built
    works = [_work("t:a", "https://doi.org/10.1177/1758835919874651"), _work("t:b", None),
             _work("t:c", "10.1000/not-in-rw")]
    (data_dir / "processed" / "works.jsonl").write_text("\n".join(works) + "\n", encoding="utf-8")
    j = rw.join_corpus(data_dir)
    assert j["status"] == "ok" and j["works_files"] == ["works.jsonl"]
    assert (j["n_works"], j["n_works_with_doi"], j["n_matched_works"]) == (3, 2, 1)
    assert j["matches"] == [{"work_id": "t:a", "doi": "10.1177/1758835919874651",
                             "post_status_ids": ["rw:34999"], "kinds": ["retraction"]}]


def test_join_corpus_missing(tmp_path: Path) -> None:
    (tmp_path / "processed").mkdir()
    assert rw.join_corpus(tmp_path)["status"] == "corpus_missing"


def test_missing_processed_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        rw.get_post_status("10.1177/1758835919874651", data_dir=tmp_path / "nowhere")
