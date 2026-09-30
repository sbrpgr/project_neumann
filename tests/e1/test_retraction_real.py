"""E1-L2 실데이터 대조: 원본 RW CSV와 공유 데이터 폴더의 processed 산출물이 있을 때만 돈다.

CSV를 이 테스트가 따로 읽어(csv 모듈) 건수·kind 분포·알려진 DOI 조회를 다시 잰다.
경로: NEUMANN_RAW_DIR(공개자료 루트), NEUMANN_DATA_DIR(공유 데이터 폴더).
"""

from __future__ import annotations

import csv
import json
import os
import random
from collections import Counter
from pathlib import Path

import pytest

from neumann.models import IDENTITY_TOKENS
from neumann.sources import retraction as rw

RAW_DIR = os.getenv("NEUMANN_RAW_DIR")
DATA_DIR = os.getenv("NEUMANN_DATA_DIR")
CSV_PATH = Path(RAW_DIR) / rw.RAW_RELPATH if RAW_DIR else None
PROCESSED = Path(DATA_DIR) / "processed" if DATA_DIR else None

pytestmark = pytest.mark.skipif(
    not (CSV_PATH and CSV_PATH.is_file() and PROCESSED and (PROCESSED / rw.OUT_JSONL).is_file()),
    reason="원본 RW CSV 또는 processed/retraction.jsonl이 없다(NEUMANN_RAW_DIR·NEUMANN_DATA_DIR)",
)

NATURE = {"Retraction": "retraction", "Expression of concern": "expression_of_concern",
          "Correction": "correction", "Reinstatement": "reinstatement"}
# 알려진 행(실측 문서 retraction.md §3 검증 쌍 34999 포함)
KNOWN_IDS = ["34999", "72853", "72867", "67291", "49720", "40040"]


@pytest.fixture(scope="module")
def csv_rows() -> list[dict[str, str]]:
    assert CSV_PATH is not None
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert PROCESSED is not None
    return json.loads((PROCESSED / rw.OUT_MANIFEST).read_text(encoding="utf-8"))


def _reasons(s: str) -> list[str]:
    out: list[str] = []
    for x in s.split(";"):
        x = x.strip()
        if x and x not in out:
            out.append(x)
    return out


def test_manifest_matches_this_csv(csv_rows: list[dict[str, str]], manifest: dict) -> None:
    assert CSV_PATH is not None
    assert manifest["input"]["sha256"] == rw.file_sha256(CSV_PATH), "processed가 현재 CSV로 만든 것이 아니다(재빌드)"
    assert manifest["rows_read"] == len(csv_rows)
    kinds = Counter(NATURE[r["RetractionNature"].strip()] for r in csv_rows if r["RetractionNature"].strip())
    assert manifest["kind_distribution_all_rows"] == dict(sorted(kinds.items()))
    assert manifest["records_written"] + sum(manifest["skipped"].values()) == len(csv_rows)
    lines = sum(1 for line in (PROCESSED / rw.OUT_JSONL).open(encoding="utf-8") if line.strip())  # type: ignore[operator]
    assert lines == manifest["records_written"] == manifest["outputs"][rw.OUT_JSONL]["lines"]


def _check_row(row: dict[str, str]) -> None:
    got = rw.get_post_status(row["OriginalPaperDOI"], data_dir=DATA_DIR)
    mine = [s for s in got if s.post_status_id == f"rw:{row['Record ID']}"]
    assert len(mine) == 1, row["Record ID"]
    s = mine[0]
    assert s.kind.value == NATURE[row["RetractionNature"]]
    assert s.target_doi == row["OriginalPaperDOI"].strip().lower().replace("%3c", "<").replace("%3e", ">")
    assert s.reason_codes == _reasons(row["Reason"])
    notice = row["RetractionDOI"].strip()
    if notice.lower().startswith("10."):
        assert s.notice_doi is not None and s.url is not None
        assert s.url.startswith("https://doi.org/10.")
    # 같은 DOI의 다른 표기(대문자, URL 접두)로도 같은 결과
    again = rw.get_post_status("https://doi.org/" + row["OriginalPaperDOI"].strip().upper(), data_dir=DATA_DIR)
    assert {x.post_status_id for x in again} == {x.post_status_id for x in got}


def test_known_rows_lookup(csv_rows: list[dict[str, str]]) -> None:
    by_id = {r["Record ID"]: r for r in csv_rows}
    for rid in KNOWN_IDS:
        _check_row(by_id[rid])


def test_random_rows_lookup(csv_rows: list[dict[str, str]]) -> None:
    pool = [r for r in csv_rows if r["OriginalPaperDOI"].strip().startswith("10.") and "%" not in r["OriginalPaperDOI"]]
    for row in random.Random(20260930).sample(pool, 25):
        _check_row(row)


def test_notice_and_missing_doi_are_empty(csv_rows: list[dict[str, str]]) -> None:
    originals = {r["OriginalPaperDOI"].strip().lower() for r in csv_rows}
    notice_only = next(
        r["RetractionDOI"] for r in csv_rows
        if r["RetractionDOI"].strip().lower().startswith("10.") and r["RetractionDOI"].strip().lower() not in originals
    )
    assert rw.get_post_status(notice_only, data_dir=DATA_DIR) == []
    assert rw.get_post_status("10.1000/neumann-does-not-exist", data_dir=DATA_DIR) == []


def test_no_identity_keys_in_real_output() -> None:
    assert PROCESSED is not None
    keys: set[str] = set()
    with (PROCESSED / rw.OUT_JSONL).open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            keys |= set(rec) | set(rec["provenance"])
    assert not {k for k in keys if any(t in k.lower() for t in IDENTITY_TOKENS)}


def test_real_field_prior_cs() -> None:
    p = rw.field_failure_prior(["Computer Science"], data_dir=DATA_DIR)
    assert p["status"] == "ok" and p["n_records"] > 1000
    risk = {r["risk_code"]: r["share"] for r in p["risk_codes"]}
    # 사전 실측(retraction.md §5-4): CS 심사 무결성 69.9% — R9.5로 다시 잰 값이 같은 수준이어야 한다
    assert 0.6 < risk["R9.5"] < 0.8
