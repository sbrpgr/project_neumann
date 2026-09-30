"""Crossref–Retraction Watch 사후상태 소스 (E1-L2).

원본: Retraction Watch Database(Crossref 배포) CSV 한 개. 라이선스 선언이 없고 Crossref가 인용을 요청한다.
"CC0"라고 쓰지 않는다. 출력마다 `CITATION`과 스냅샷 날짜를 붙인다. 원본 CSV는 저장소에 넣지 않는다.

하는 일
1. `build()`: CSV → `PostStatus` JSONL(`data/processed/retraction.jsonl`)
   + 분야 prior용 패싯(`retraction_facets.json`) + 영수증(`retraction_manifest.json`).
2. `get_post_status(doi)`: **원논문 DOI**로 사후상태 목록을 돌려준다(공지 DOI로는 찾지 않는다 — 방향 주의).
3. `field_failure_prior(subject_keywords)`: RW `Subject`가 키워드와 맞는 레코드들의 사유(`Reason`) 빈도.
4. `join_corpus()`: 공유 데이터 폴더의 코퍼스 Work(JSONL)와 DOI로 조인한 결과.

신원 정보: `Author`·`Institution`·`Country` 열은 읽자마자 버린다. `Title`·`URLS`·`Notes`도 저장하지 않는다
(`Notes`에는 사람 이름·외부 링크가 섞인다). 행 해시(provenance.content_sha256)는 원본 행 전체의 해시라
원문 대조는 되지만 내용은 드러나지 않는다.

DOI 정규화 규칙(`normalize_doi`, 조회·저장·조인 모두 같은 함수):
  앞뒤 공백 제거 → `https://doi.org/`·`http://dx.doi.org/`·`doi:` 접두 제거 → `%XX` 퍼센트 인코딩 해제
  → 소문자 → `^10\\.\\d{4,9}/\\S+$`가 아니면 None(`unavailable`·빈 값·`xx10.…` 같은 오기 포함).
  (`models.Work.doi` 검증기와 같은 방향: URL 접두 제거 + 소문자. 퍼센트 해제는 RW의 SICI DOI `%3C`·`%3E` 때문에 더했다.)

실행:
  python -m neumann.sources.retraction build [--csv PATH] [--data-dir PATH]
  python -m neumann.sources.retraction join [--data-dir PATH]
  python -m neumann.sources.retraction lookup DOI [--data-dir PATH]
  python -m neumann.sources.retraction prior KEYWORD [KEYWORD ...] [--data-dir PATH]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from neumann.models import SCHEMA_VERSION, PostStatus, PostStatusKind, Provenance

# ── 출처 ─────────────────────────────────────────────────────────────────

SOURCE_ID = "retraction_watch"
DATASET_HOME = "https://gitlab.com/crossref/retraction-watch-data"
DATASET_URL = "https://gitlab.com/crossref/retraction-watch-data/-/raw/main/retraction_watch.csv"
CITATION = "Retraction Watch Database, Crossref. https://gitlab.com/crossref/retraction-watch-data"
LICENSE_NOTE = "undeclared: LICENSE 없음, Crossref가 인용을 요청(출처 표기 필수, CC0 아님)"
RAW_RELPATH = Path("data") / "retraction_watch" / "retraction_watch.csv"

OUT_JSONL = "retraction.jsonl"
OUT_FACETS = "retraction_facets.json"
OUT_MANIFEST = "retraction_manifest.json"

# ── CSV 열 ───────────────────────────────────────────────────────────────

COL_ID = "Record ID"
COL_SUBJECT = "Subject"
COL_NATURE = "RetractionNature"
COL_REASON = "Reason"
COL_NOTICE_DOI = "RetractionDOI"
COL_TARGET_DOI = "OriginalPaperDOI"
REQUIRED_COLUMNS = (COL_ID, COL_SUBJECT, COL_NATURE, COL_REASON, COL_NOTICE_DOI, COL_TARGET_DOI)
# 읽자마자 버리는 열(신원·자유서술). 레코드·패싯·영수증 어디에도 값이 들어가지 않는다.
DROPPED_COLUMNS = ("Author", "Institution", "Country", "Title", "URLS", "Notes")

NATURE_TO_KIND: dict[str, PostStatusKind] = {
    "retraction": PostStatusKind.retraction,
    "expression of concern": PostStatusKind.expression_of_concern,
    "correction": PostStatusKind.correction,
    "reinstatement": PostStatusKind.reinstatement,
}
# 분야 prior 기본 대상: 사유가 위험 근거가 되는 철회·우려표명(정정은 사유 커버리지가 낮고 재게재는 반대 신호).
DEFAULT_PRIOR_KINDS: tuple[str, ...] = (PostStatusKind.retraction.value, PostStatusKind.expression_of_concern.value)

# ── 사유 코드 → 위험 하위코드 (기획 키트 03_risk_taxonomy §7 표 그대로) ──────────

RW_REASON_TO_RISK: dict[str, str] = {
    "Author Unresponsive": "R9.9",
    "Compromised Peer Review": "R9.5",
    "Computer-Aided Content or Computer-Generated Content": "R9.8",
    "Concerns/Issues about Data": "R9.1",
    "Concerns/Issues about Image": "R9.2",
    "Concerns/Issues about Peer Review": "R9.5",
    "Concerns/Issues about Results and/or Conclusions": "R9.1",
    "Conflict of Interest": "R9.7",
    "Duplication of Data": "R9.2",
    "Duplication of/in Article": "R9.4",
    "Duplication of/in Image": "R9.2",
    "Error in Analyses": "R9.3",
    "Error in Data": "R9.3",
    "Error in Image": "R9.3",
    "Error in Methods": "R9.3",
    "Error in Results and/or Conclusions": "R9.3",
    "Euphemisms for Duplication": "R9.4",
    "Euphemisms for Plagiarism": "R9.4",
    "Falsification/Fabrication of Data": "R9.2",
    "Informed/Patient Consent - None/Withdrawn": "R9.6",
    "Lack of IRB/IACUC Approval and/or Compliance": "R9.6",
    "Manipulation of Images": "R9.2",
    "Original Data and/or Images not Provided and/or not Available": "R9.9",
    "Paper Mill": "R9.5",
    "Plagiarism of Text": "R9.4",
    "Plagiarism of/in Article": "R9.4",
    "Results Not Reproducible": "R9.1",
    "Rogue Editor": "R9.5",
    "Unreliable Data": "R9.1",
    "Unreliable Image": "R9.2",
    "Unreliable Results and/or Conclusions": "R9.1",
}

# 사유가 아니라 절차 상태인 코드(03_risk_taxonomy §7). 빈도 prior에서 기본으로 뺀다.
RW_PROCEDURAL_CODES: frozenset[str] = frozenset(
    {
        "Date of Article and/or Notice Unknown",
        "Investigation by Company/Institution",
        "Investigation by Journal/Publisher",
        "Investigation by ORI",
        "Investigation by Third Party",
        "Misconduct - Official Investigation(s) and/or Finding(s)",
        "Notice - Lack of",
        "Notice - Limited or No Information",
        "Notice - Unable to Access via current resources",
        "Objections by Author(s)",
        "Objections by Third Party",
        "Removed",
        "Retract and Replace",
        "Temporary Removal",
        "Transfer of Article",
        "Updated to Correction",
        "Updated to Expression of Concern",
        "Updated to Retraction",
        "Upgrade/Update of Prior Notice(s)",
        "Withdrawal",
    }
)

# ── DOI ──────────────────────────────────────────────────────────────────

_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_PCT_RE = re.compile(r"%[0-9A-Fa-f]{2}")

DOI_NORMALIZATION_RULE = (
    "strip → 접두(https://doi.org/, http://dx.doi.org/, doi:) 제거 → %XX 퍼센트 해제 → 소문자 "
    "→ ^10\\.\\d{4,9}/\\S+$ 불일치면 None(unavailable·빈값·오기)"
)


def normalize_doi(value: str | None) -> str | None:
    """DOI 문자열을 비교용 정규형으로. DOI가 아니면 None."""
    if value is None:
        return None
    s = _DOI_PREFIX_RE.sub("", str(value).strip()).strip()
    if _PCT_RE.search(s):
        s = unquote(s)
    s = s.lower()
    if not _DOI_RE.match(s):
        return None
    return s


def doi_url(doi: str) -> str:
    """정규화된 DOI → 근거 링크. `<`·`>`·`#`·`%` 같은 문자는 퍼센트 인코딩한다."""
    return "https://doi.org/" + quote(doi, safe="/:;()[]+,=@!$&'*~")


# ── CSV 읽기 ─────────────────────────────────────────────────────────────


def split_multi(value: str | None) -> list[str]:
    """RW 다중값(`;` 구분, 끝에 `;`가 붙는다) → 순서 유지, 중복·빈 칸 제거. 값은 원문 그대로(앞뒤 공백만 뗌)."""
    out: list[str] = []
    for part in (value or "").split(";"):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def row_sha256(fields: Sequence[str]) -> str:
    """원본 행 해시: 헤더 순서의 원문 필드 목록을 JSON(ensure_ascii=False, 구분자 ',' ':')으로 만든 UTF-8의 sha256."""
    payload = json.dumps(list(fields), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_snapshot_date(csv_path: Path) -> str | None:
    """CSV 옆 README의 'generated on YYYY-MM-DD'(배포판 생성일)."""
    readme = csv_path.with_name("README.md")
    if not readme.is_file():
        return None
    m = re.search(r"generated on (\d{4}-\d{2}-\d{2})", readme.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def iter_csv_rows(csv_path: Path) -> Iterator[tuple[list[str], dict[str, str]]]:
    """(원본 필드 목록, 필요한 열만 남긴 dict)를 차례로. 버리는 열은 dict에 넣지 않는다."""
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"RW CSV에 필요한 열이 없다: {missing}")
        keep = {i: h for i, h in enumerate(header) if h and h not in DROPPED_COLUMNS}
        for fields in reader:
            yield fields, {h: (fields[i] if i < len(fields) else "") for i, h in keep.items()}


def resolve_csv_path(csv_path: str | os.PathLike[str] | None = None) -> Path:
    if csv_path is not None:
        return Path(csv_path)
    raw_dir = os.getenv("NEUMANN_RAW_DIR")
    if not raw_dir:
        from neumann.config import get_settings

        raw = get_settings().raw_dir
        raw_dir = str(raw) if raw else None
    if not raw_dir:
        raise FileNotFoundError("RW CSV 경로가 없다: --csv 또는 NEUMANN_RAW_DIR")
    return Path(raw_dir) / RAW_RELPATH


def resolve_data_dir(data_dir: str | os.PathLike[str] | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    env = os.getenv("NEUMANN_DATA_DIR")
    if env:
        return Path(env)
    from neumann.config import get_settings

    return Path(get_settings().data_dir)


# ── 변환 ─────────────────────────────────────────────────────────────────


def row_to_post_status(
    raw_fields: Sequence[str],
    row: dict[str, str],
    *,
    accessed_at: datetime,
    api_version: str,
) -> PostStatus | None:
    """행 하나 → PostStatus. 대상 원논문 DOI가 없거나 성격(RetractionNature)을 모르면 None."""
    kind = NATURE_TO_KIND.get(row.get(COL_NATURE, "").strip().lower())
    target = normalize_doi(row.get(COL_TARGET_DOI))
    record_id = row.get(COL_ID, "").strip()
    if kind is None or target is None or not record_id:
        return None
    notice = normalize_doi(row.get(COL_NOTICE_DOI))
    return PostStatus(
        post_status_id=f"rw:{record_id}",
        kind=kind,
        target_doi=target,
        notice_doi=notice,
        reason_codes=split_multi(row.get(COL_REASON)),
        url=doi_url(notice) if notice else None,
        provenance=Provenance(
            source=SOURCE_ID,
            source_url=DATASET_URL,
            accessed_at=accessed_at,
            content_sha256=row_sha256(raw_fields),
            license=LICENSE_NOTE,
            api_version=api_version,
        ),
    )


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _file_info(path: Path, lines: int | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {"bytes": path.stat().st_size, "sha256": file_sha256(path)}
    if lines is not None:
        info["lines"] = lines
    return info


def build(
    csv_path: str | os.PathLike[str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
    *,
    accessed_at: datetime | None = None,
) -> dict[str, Any]:
    """CSV를 읽어 processed 산출물 3개를 쓰고 영수증(manifest dict)을 돌려준다.

    accessed_at 기본값은 로컬 CSV 파일의 수정 시각(반입 시각)이다. 같은 입력이면 출력 sha256이 같다.
    """
    t0 = time.perf_counter()
    src = resolve_csv_path(csv_path)
    if not src.is_file():
        raise FileNotFoundError(f"RW CSV가 없다: {src}")
    out_dir = resolve_data_dir(data_dir) / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    if accessed_at is None:
        accessed_at = datetime.fromtimestamp(src.stat().st_mtime, UTC).replace(microsecond=0)
    snapshot = read_snapshot_date(src)
    api_version = f"rw-csv:{snapshot or 'unknown'}"

    lines: list[str] = []
    subjects: dict[str, int] = {}
    reasons: dict[str, int] = {}
    kinds = [k.value for k in PostStatusKind]
    facet_records: list[list[Any]] = []
    rows_read = blank = unknown_nature = no_target = no_notice = 0
    nature_unknown_values: Counter[str] = Counter()
    kind_all: Counter[str] = Counter()
    kind_written: Counter[str] = Counter()
    targets: set[str] = set()

    for raw_fields, row in iter_csv_rows(src):
        rows_read += 1
        if not any(f.strip() for f in raw_fields):
            blank += 1
            continue
        nature = row.get(COL_NATURE, "").strip()
        kind = NATURE_TO_KIND.get(nature.lower())
        if kind is None:
            unknown_nature += 1
            nature_unknown_values[nature] += 1
            continue
        kind_all[kind.value] += 1
        record_id = row.get(COL_ID, "").strip()
        subj_idx = [subjects.setdefault(s, len(subjects)) for s in split_multi(row.get(COL_SUBJECT))]
        reason_idx = [reasons.setdefault(r, len(reasons)) for r in split_multi(row.get(COL_REASON))]
        facet_records.append([f"rw:{record_id}", kinds.index(kind.value), subj_idx, reason_idx])

        status = row_to_post_status(raw_fields, row, accessed_at=accessed_at, api_version=api_version)
        if status is None:
            no_target += 1
            continue
        if status.notice_doi is None:
            no_notice += 1
        kind_written[status.kind.value] += 1
        targets.add(status.target_doi or "")
        lines.append(status.model_dump_json())

    jsonl_path = out_dir / OUT_JSONL
    _write_atomic(jsonl_path, "".join(line + "\n" for line in lines))
    facets = {
        "schema": "neumann.retraction_facets/1",
        "citation": CITATION,
        "snapshot": snapshot,
        "kinds": kinds,
        "subjects": list(subjects),
        "reasons": list(reasons),
        "records": facet_records,  # [post_status_id, kind 번호, [subject 번호], [reason 번호]]
    }
    facets_path = out_dir / OUT_FACETS
    _write_atomic(facets_path, json.dumps(facets, ensure_ascii=False, separators=(",", ":")) + "\n")

    reason_set = set(reasons)
    manifest: dict[str, Any] = {
        "source": SOURCE_ID,
        "citation": CITATION,
        "dataset_home": DATASET_HOME,
        "dataset_url": DATASET_URL,
        "license": LICENSE_NOTE,
        "snapshot_generated": snapshot,
        "accessed_at": accessed_at.isoformat(),
        "accessed_at_rule": "로컬 CSV 파일 수정 시각(반입 시각), UTC",
        "schema_version": SCHEMA_VERSION,
        "input": {"file": src.name, **_file_info(src)},
        "rows_read": rows_read,
        "records_written": len(lines),
        "facet_records": len(facet_records),
        "skipped": {
            "blank_rows": blank,
            "unknown_nature": unknown_nature,
            "no_target_doi": no_target,
        },
        "unknown_nature_values": dict(nature_unknown_values),
        "kind_distribution_all_rows": dict(sorted(kind_all.items())),
        "kind_distribution_written": dict(sorted(kind_written.items())),
        "unique_target_dois": len(targets),
        "written_without_notice_doi": no_notice,
        "reason_labels": len(reasons),
        "subject_labels": len(subjects),
        "reason_mapping": {
            "mapped_to_risk": len(reason_set & set(RW_REASON_TO_RISK)),
            "procedural": len(reason_set & RW_PROCEDURAL_CODES),
            "other": len(reason_set - set(RW_REASON_TO_RISK) - RW_PROCEDURAL_CODES),
            "table": "03_risk_taxonomy §7",
        },
        "doi_normalization": DOI_NORMALIZATION_RULE,
        "row_hash_rule": "sha256(json.dumps(원본 행 필드 목록, ensure_ascii=False, separators=(',', ':')))",
        "dropped_columns": list(DROPPED_COLUMNS),
        "outputs": {
            OUT_JSONL: _file_info(jsonl_path, len(lines)),
            OUT_FACETS: _file_info(facets_path),
        },
        "built_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    clear_cache()
    manifest["corpus_join"] = join_corpus(out_dir.parent)
    manifest["elapsed_s"] = round(time.perf_counter() - t0, 3)
    _write_atomic(out_dir / OUT_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


# ── 조회 ─────────────────────────────────────────────────────────────────


class RetractionIndex:
    """processed 산출물을 메모리에 올린 조회기. PostStatus는 돌려줄 때만 검증해 만든다(적재가 빠르다)."""

    def __init__(self, records: Iterable[dict[str, Any]], facets: dict[str, Any] | None = None) -> None:
        self._by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.n_records = 0
        for rec in records:
            self.n_records += 1
            doi = normalize_doi(rec.get("target_doi"))
            if doi:
                self._by_target[doi].append(rec)
        self.facets = facets

    @classmethod
    def load(cls, data_dir: str | os.PathLike[str] | None = None) -> RetractionIndex:
        processed = resolve_data_dir(data_dir) / "processed"
        jsonl = processed / OUT_JSONL
        if not jsonl.is_file():
            raise FileNotFoundError(f"{jsonl}가 없다. 먼저 `python -m neumann.sources.retraction build`")
        with jsonl.open(encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
        facets_path = processed / OUT_FACETS
        facets = json.loads(facets_path.read_text(encoding="utf-8")) if facets_path.is_file() else None
        return cls(records, facets)

    def __contains__(self, doi: object) -> bool:
        return isinstance(doi, str) and normalize_doi(doi) in self._by_target

    def target_dois(self) -> set[str]:
        return set(self._by_target)

    def get(self, doi: str) -> list[PostStatus]:
        key = normalize_doi(doi)
        if key is None:
            return []
        return [PostStatus.model_validate(rec) for rec in self._by_target.get(key, [])]

    def field_failure_prior(
        self,
        subject_keywords: Sequence[str],
        *,
        kinds: Sequence[str] = DEFAULT_PRIOR_KINDS,
        top_k: int = 10,
        include_procedural: bool = False,
    ) -> dict[str, Any]:
        if not self.facets:
            raise FileNotFoundError(f"{OUT_FACETS}가 없어 분야 prior를 계산할 수 없다")
        return compute_field_prior(
            self.facets, subject_keywords, kinds=kinds, top_k=top_k, include_procedural=include_procedural
        )


def _keyword_patterns(subject_keywords: Sequence[str]) -> list[re.Pattern[str]]:
    pats = []
    for kw in subject_keywords:
        kw = (kw or "").strip().lower()
        if kw:
            pats.append(re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"))
    return pats


def compute_field_prior(
    facets: dict[str, Any],
    subject_keywords: Sequence[str],
    *,
    kinds: Sequence[str] = DEFAULT_PRIOR_KINDS,
    top_k: int = 10,
    include_procedural: bool = False,
) -> dict[str, Any]:
    """RW `Subject`가 키워드(대소문자 무시, 단어 경계)와 맞는 레코드의 사유 빈도.

    단위: share = 해당 분야 레코드 중 그 사유를 1번 이상 가진 비율. baseline_share는 같은 kind 전체 레코드 기준.
    한 레코드가 여러 분야에 걸려도 한 번만 센다. 절차 코드(RW_PROCEDURAL_CODES)는 기본으로 뺀다.
    """
    subjects: list[str] = facets["subjects"]
    reasons: list[str] = facets["reasons"]
    kind_names: list[str] = facets["kinds"]
    wanted_kinds = {kind_names.index(k) for k in kinds if k in kind_names}
    pats = _keyword_patterns(subject_keywords)
    matched_subj = {i for i, s in enumerate(subjects) if any(p.search(s.lower()) for p in pats)}

    reason_risk = [RW_REASON_TO_RISK.get(r) for r in reasons]
    base_n = n = 0
    base_counts: Counter[int] = Counter()
    counts: Counter[int] = Counter()
    base_risk: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    subj_counts: Counter[int] = Counter()
    for _rid, kind_i, subj_idx, reason_idx in facets["records"]:
        if kind_i not in wanted_kinds:
            continue
        risk_codes = {reason_risk[r] for r in reason_idx if reason_risk[r]}
        base_n += 1
        base_counts.update(reason_idx)
        base_risk.update(risk_codes)
        hit = [s for s in subj_idx if s in matched_subj]
        if hit:
            n += 1
            counts.update(reason_idx)
            risk_counts.update(risk_codes)
            subj_counts.update(hit)

    def _share(c: int, d: int) -> float:
        return round(c / d, 4) if d else 0.0

    reason_rows = []
    for ri, c in counts.items():
        code = reasons[ri]
        procedural = code in RW_PROCEDURAL_CODES
        if procedural and not include_procedural:
            continue
        share, base = _share(c, n), _share(base_counts[ri], base_n)
        reason_rows.append(
            {
                "reason": code,
                "records": c,
                "share": share,
                "baseline_share": base,
                "lift": round(share / base, 3) if base else None,
                "risk_code": RW_REASON_TO_RISK.get(code),
                "procedural": procedural,
            }
        )
    reason_rows.sort(key=lambda r: (-r["records"], r["reason"]))

    # 위험 하위코드 단위: 레코드가 그 코드로 매핑되는 사유를 1개 이상 가진 비율
    risk_rows = [
        {
            "risk_code": code,
            "records": c,
            "share": _share(c, n),
            "baseline_share": _share(base_risk[code], base_n),
        }
        for code, c in sorted(risk_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    return {
        "status": "ok" if n else "no_match",
        "subject_keywords": [k for k in subject_keywords if (k or "").strip()],
        "kinds": [k for k in kinds if k in kind_names],
        "matched_subjects": [
            {"subject": subjects[i], "records": subj_counts[i]}
            for i in sorted(matched_subj, key=lambda i: (-subj_counts[i], subjects[i]))
        ],
        "n_records": n,
        "n_baseline": base_n,
        "reasons": reason_rows[: max(0, top_k)],
        "risk_codes": risk_rows,
        "unit": "share = 해당 분야 레코드 중 그 사유를 1번 이상 가진 비율(레코드 단위, 중복 분야는 1번)",
        "procedural_excluded": not include_procedural,
        "source": {"citation": CITATION, "snapshot": facets.get("snapshot"), "url": DATASET_HOME},
    }


_INDEX_CACHE: dict[str, RetractionIndex] = {}


def load_index(data_dir: str | os.PathLike[str] | None = None) -> RetractionIndex:
    """processed 산출물을 한 번 읽어 캐시한다(데이터 폴더별). 다시 만들었으면 `clear_cache()`."""
    key = str(resolve_data_dir(data_dir).resolve())
    idx = _INDEX_CACHE.get(key)
    if idx is None:
        idx = RetractionIndex.load(key)
        _INDEX_CACHE[key] = idx
    return idx


def clear_cache() -> None:
    _INDEX_CACHE.clear()


def get_post_status(doi: str, *, data_dir: str | os.PathLike[str] | None = None) -> list[PostStatus]:
    """원논문 DOI(정규화 전 문자열도 됨) → 사후상태 목록. 없으면 빈 목록. 공지 DOI로는 찾지 않는다."""
    return load_index(data_dir).get(doi)


def field_failure_prior(
    subject_keywords: list[str],
    *,
    data_dir: str | os.PathLike[str] | None = None,
    kinds: Sequence[str] = DEFAULT_PRIOR_KINDS,
    top_k: int = 10,
    include_procedural: bool = False,
) -> dict[str, Any]:
    """분야 키워드(RW Subject와 단어 경계 매칭) → 그 분야 철회·우려표명 사유 빈도. 카드의 '이 분야에서 흔한 사후 문제' 근거."""
    return load_index(data_dir).field_failure_prior(
        subject_keywords, kinds=kinds, top_k=top_k, include_procedural=include_procedural
    )


# ── 코퍼스 조인 ──────────────────────────────────────────────────────────


def _is_work_file(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    keys = set(json.loads(line))
                    return {"work_id", "title", "url"} <= keys and not keys & {"review_id", "response_id", "decision_id"}
    except (OSError, ValueError):
        return False
    return False


def join_corpus(data_dir: str | os.PathLike[str] | None = None, *, max_matches: int = 50) -> dict[str, Any]:
    """공유 데이터 폴더 processed/*.jsonl 중 Work 모양 파일을 찾아 DOI로 조인한다. 코퍼스가 없으면 그렇다고 적는다."""
    processed = resolve_data_dir(data_dir) / "processed"
    files = sorted(
        p for p in processed.glob("*.jsonl") if not p.name.startswith("retraction") and _is_work_file(p)
    )
    if not files:
        return {"status": "corpus_missing", "works_files": [], "note": "코퍼스(Work JSONL)가 아직 없다. 조인은 다음에"}
    idx = load_index(processed.parent)
    n_works = n_doi = 0
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in files:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                wid = rec.get("work_id")
                if wid in seen:
                    continue
                seen.add(wid)
                n_works += 1
                doi = normalize_doi(rec.get("doi"))
                if not doi:
                    continue
                n_doi += 1
                statuses = idx.get(doi)
                if statuses:
                    matched.append(
                        {
                            "work_id": wid,
                            "doi": doi,
                            "post_status_ids": [s.post_status_id for s in statuses],
                            "kinds": sorted({s.kind.value for s in statuses}),
                        }
                    )
    return {
        "status": "ok",
        "works_files": [p.name for p in files],
        "n_works": n_works,
        "n_works_with_doi": n_doi,
        "n_matched_works": len(matched),
        "n_matched_post_status": sum(len(m["post_status_ids"]) for m in matched),
        "matches": matched[:max_matches],
    }


# ── CLI ──────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m neumann.sources.retraction", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="CSV → processed/retraction.jsonl + facets + manifest")
    b.add_argument("--csv")
    b.add_argument("--data-dir")
    j = sub.add_parser("join", help="코퍼스 Work와 DOI 조인, manifest의 corpus_join 갱신")
    j.add_argument("--data-dir")
    lk = sub.add_parser("lookup", help="원논문 DOI 조회")
    lk.add_argument("doi")
    lk.add_argument("--data-dir")
    pr = sub.add_parser("prior", help="분야 키워드 → 사유 빈도")
    pr.add_argument("keywords", nargs="+")
    pr.add_argument("--data-dir")
    pr.add_argument("--top-k", type=int, default=10)
    args = ap.parse_args(argv)

    if args.cmd == "build":
        m = build(args.csv, args.data_dir)
        summary = {k: m[k] for k in ("rows_read", "records_written", "skipped", "kind_distribution_all_rows",
                                     "kind_distribution_written", "unique_target_dois", "elapsed_s")}
        summary["corpus_join"] = {k: v for k, v in m["corpus_join"].items() if k != "matches"}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.cmd == "join":
        result = join_corpus(args.data_dir)
        mpath = resolve_data_dir(args.data_dir) / "processed" / OUT_MANIFEST
        if mpath.is_file():
            m = json.loads(mpath.read_text(encoding="utf-8"))
            m["corpus_join"] = result
            m["corpus_join_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
            _write_atomic(mpath, json.dumps(m, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "lookup":
        out = [s.model_dump(mode="json") for s in get_post_status(args.doi, data_dir=args.data_dir)]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.cmd == "prior":
        print(json.dumps(field_failure_prior(args.keywords, data_dir=args.data_dir, top_k=args.top_k),
                         ensure_ascii=False, indent=2))
    return 0


__all__ = [
    "CITATION",
    "DEFAULT_PRIOR_KINDS",
    "DROPPED_COLUMNS",
    "NATURE_TO_KIND",
    "RW_PROCEDURAL_CODES",
    "RW_REASON_TO_RISK",
    "RetractionIndex",
    "build",
    "clear_cache",
    "compute_field_prior",
    "doi_url",
    "field_failure_prior",
    "get_post_status",
    "join_corpus",
    "load_index",
    "normalize_doi",
    "row_to_post_status",
]


if __name__ == "__main__":
    sys.exit(main())
