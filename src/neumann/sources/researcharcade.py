"""ResearchArcade(HF의 OpenReview 미러) 원본 parquet → AI for Science 코퍼스 (E1-L0).

입력(공개자료, 읽기만):
    data/researcharcade/papers/train-00000-of-00001.parquet
    data/researcharcade/reviews/train-0000{0,1}-of-00006.parquet   (나머지 샤드는 L3)

순서:
    1. 선별: ICLR 2024·2025 심사 논문(데스크 리젝 제외) 중 제목+초록 키워드로 3개 분야를 고른다.
    2. 연결: 리뷰 노트를 replyto 사슬로 논문에 붙인다.
       공식 심사평·메타리뷰 → ReviewEvent, 저자 답변 → AuthorResponse, 결정 → Decision.
    3. 변환: models.py 계약으로 검증해 엔티티별 JSONL로 쓴다(결정적 순서, 같은 입력 → 같은 바이트).

불변식:
    - 레코드마다 provenance(OpenReview forum/note URL, 원본 파일 접근 시각, 원문 해시). URL이 없으면 만들지 않는다.
    - 리뷰어 신원(writer, 제목 속 핸들, 서명)은 저장하지 않는다.
    - 본문 정규화 순서: NFC·줄바꿈 → 보일러플레이트(빈 칸·점수 칸) 제거 → 신원 제거 → 저장.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import pyarrow.parquet as pq

from neumann.models import (
    AuthorResponse,
    Decision,
    DecisionOutcome,
    Provenance,
    ReviewEvent,
    ReviewKind,
    Work,
    normalize_text,
    redact_pii,
    sha256_text,
)

SOURCE = "researcharcade_hf"
LICENSE = "UNDECLARED"
ATTRIBUTION = (
    "ResearchArcade (ulab-ai, Hugging Face) mirror of OpenReview. "
    "Original records at https://openreview.net. License undeclared: raw data is not redistributed."
)
OPENREVIEW_BASE = "https://openreview.net"

PAPERS_FILE = "data/researcharcade/papers/train-00000-of-00001.parquet"
REVIEW_FILES = (
    "data/researcharcade/reviews/train-00000-of-00006.parquet",
    "data/researcharcade/reviews/train-00001-of-00006.parquet",
)
HF_DATASETS = {
    "papers": "ulab-ai/ResearchArcade-openreview-papers",
    "reviews": "ulab-ai/ResearchArcade-openreview-reviews",
}

# 원본 venue 문자열 → (표시용 venue, 연도)
VENUES: dict[str, tuple[str, int]] = {
    "ICLR.cc/2024/Conference": ("ICLR 2024", 2024),
    "ICLR.cc/2025/Conference": ("ICLR 2025", 2025),
}
DESK_REJECT_RAW = "Desk_Rejected_Submission"

# 사전 집계(04_평가_명세 §0.1, 2026-09-29). 비교 보고용일 뿐 선별에 쓰지 않는다.
PRECOUNT = {
    "reviewed_population": 13433,
    "works": 1265,
    "by_field": {
        "materials_chemistry_molecules": 555,
        "protein_biology_drug": 671,
        "physics_pde_climate": 285,
    },
    "reviews": 5000,
    "reject_ratio": 0.61,
}

# ── 1. 선별 키워드 ───────────────────────────────────────────────────────
# 규칙: 대소문자 무시, 단어 경계에서 시작. 끝이 `*`면 앞부분 일치(molecul* → molecule, molecular).
# 공백은 공백·하이픈 어느 쪽과도, 하이픈은 공백·하이픈·붙여쓰기와 맞는다.
# 뜻이 여럿인 단어(material → supplementary material, catalyst → "a catalyst for", physics → "Physics of
# Language Models", weather → "weather conditions")는 과학 쓰임새의 구로만 넣었다(보고서 "결정" 참고).

FIELD_LABELS_KO: dict[str, str] = {
    "materials_chemistry_molecules": "소재·화학·분자",
    "protein_biology_drug": "단백질·생물·신약",
    "physics_pde_climate": "물리·PDE·기후",
}

FIELD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "materials_chemistry_molecules": (
        "molecul*", "chemi*", "materials science", "material science", "materials discovery",
        "material discovery", "materials design", "material design", "inorganic material*", "metamaterial*",
        "crystals", "crystalline", "crystallograph*", "crystal structure*", "crystal material*",
        "crystal generation", "crystal propert*", "catalysis", "catalyt*", "open catalyst", "electrocatal*",
        "polymer*", "retrosynthe*", "reaction prediction", "reaction condition*", "smiles", "force field*",
        "interatomic", "atomistic", "atomic structure*", "density functional", "electrolyte*",
        "battery degradation", "battery material*", "lithium", "alloy*", "metal-organic", "zeolite*",
        "ab initio", "potential energy surface*", "conformation*", "spectroscop*", "quantum chemistry",
        "quantum monte carlo", "solid-state", "periodic table",
    ),
    "protein_biology_drug": (
        "protein*", "peptide*", "antibod*", "enzym*", "amino acid*", "gene", "genes", "genomic*", "genomes",
        "genome sequenc*", "genome-wide", "genome-scale", "gene expression", "transcriptom*", "single-cell",
        "rna", "dna", "cell type*", "cell line*", "computational biology", "structural biology",
        "synthetic biology", "systems biology", "molecular biology", "cell biology", "biological sequence*",
        "biological data*", "bioinformatic*", "biomolecul*", "drug*", "ligand*", "docking",
        "binding affinit*", "virtual screening", "pharmacolog*", "pharmacokinetic*", "pharmacophore*",
        "pharmaceutical*", "microb*", "bacteri*", "virolog*", "omics", "multi-omics", "proteom*",
        "metabolom*", "tcr", "cryo-em", "phylogen*", "mutation effect*", "variant effect*",
    ),
    "physics_pde_climate": (
        "pde", "pdes", "partial differential equation*", "physics-informed", "physics-constrained",
        "physics-guided", "pinn", "pinns", "neural operator*", "navier-stokes", "fluid dynamic*",
        "fluid simulation*", "fluid flow*", "fluid mechanic*", "fluids", "turbulen*", "climate",
        "weather forecast*", "weather prediction*", "numerical weather", "weather model*", "atmospher*",
        "oceanic", "oceanograph*", "ocean model*", "earth system*", "geophysic*", "seismic wave*",
        "seismolog*", "earthquake*", "subsurface", "physical simulation*", "physics simulation*",
        "particle physics", "high-energy physics", "astrophysic*", "astronom*", "cosmolog*", "tokamak*",
        "nuclear fusion", "plasma physics", "laser-plasma", "many-body", "quantum system*",
        "quantum mechanic*", "physical law*", "laws of physics", "computational physics", "physical sciences",
        "computational fluid dynamics", "wave equation", "heat equation", "burgers", "darcy",
        "solid mechanics", "hamiltonian system*",
    ),
}


def keyword_regex(keyword: str) -> re.Pattern[str]:
    """키워드 → 정규식. `*`는 끝에만 온다(앞부분 일치)."""
    prefix = keyword.endswith("*")
    body = keyword.rstrip("*").lower()
    parts = []
    for ch in body:
        if ch == " ":
            parts.append(r"[\s\-]+")
        elif ch == "-":
            parts.append(r"[\s\-]?")
        else:
            parts.append(re.escape(ch))
    return re.compile(r"\b" + "".join(parts) + (r"\w*" if prefix else r"\b"), re.IGNORECASE)


def _literal_head(keyword: str) -> str:
    """정규식 전에 부분 문자열로 거르는 첫 낱말(소문자). 속도용일 뿐 결과는 정규식이 정한다."""
    return re.split(r"[\s\-]", keyword.rstrip("*").lower(), maxsplit=1)[0]


_COMPILED: dict[str, list[tuple[str, str, re.Pattern[str]]]] = {
    f: [(k, _literal_head(k), keyword_regex(k)) for k in kws] for f, kws in FIELD_KEYWORDS.items()
}


# 과학 분야가 아닌데 키워드를 품은 일반 ML 벤치마크 이름. 매칭 전에 지운다(ogbn-proteins는 그래프 ML 표준 벤치마크).
MASK_PHRASES: tuple[re.Pattern[str], ...] = (re.compile(r"\bogbn[\s\-_]?proteins\b", re.IGNORECASE),)


def match_fields(title: str, abstract: str | None) -> dict[str, list[str]]:
    """제목+초록에서 분야별로 맞은 키워드. 맞은 분야만 돌려준다(분야 순서 고정)."""
    text = f"{title}\n{abstract or ''}"
    for mask in MASK_PHRASES:
        text = mask.sub(" ", text)
    low = text.lower()
    out: dict[str, list[str]] = {}
    for f, pats in _COMPILED.items():
        hit = [k for k, head, p in pats if head in low and p.search(text)]
        if hit:
            out[f] = hit
    return out


def keyword_spec() -> dict[str, Any]:
    """선별 규칙 전체(키워드 + 지우는 구). 해시와 manifest에 같은 것을 쓴다."""
    return {"fields": {f: list(k) for f, k in FIELD_KEYWORDS.items()}, "mask_phrases": [m.pattern for m in MASK_PHRASES]}


def keywords_sha256() -> str:
    """선별 규칙(분야·키워드·순서·지우는 구)의 sha256. 목록이 바뀌면 값이 바뀐다."""
    return sha256_text(json.dumps(keyword_spec(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


# ── 2. 결정 문자열 확장 매핑 ─────────────────────────────────────────────
# 표준 규칙(02_data_schema §4.6)은 소문자 "ICLR 2024 poster"만 가정해 HF 미러의 "Rejected_Submission",
# "ICLR 2025 Poster", "Desk_Rejected_Submission"을 전부 unknown으로 만든다. 밑줄을 공백으로 바꾸고
# 대소문자를 무시한 뒤 순서대로 본다(철회·데스크리젝 먼저).

DECISION_RULES: tuple[tuple[str, re.Pattern[str], DecisionOutcome], ...] = (
    ("withdrawn", re.compile(r"\bwithdrawn?\b"), DecisionOutcome.withdrawn),
    ("desk_reject", re.compile(r"\bdesk[ \-]?reject"), DecisionOutcome.desk_reject),
    ("reject", re.compile(r"\breject"), DecisionOutcome.reject),
    ("submitted_to", re.compile(r"\bsubmitted to\b"), DecisionOutcome.reject),
    ("oral", re.compile(r"\boral\b"), DecisionOutcome.accept_oral),
    ("spotlight", re.compile(r"\bspotlight\b"), DecisionOutcome.accept_spotlight),
    ("poster", re.compile(r"\bposter\b"), DecisionOutcome.accept_poster),
    ("accept", re.compile(r"\baccept"), DecisionOutcome.accept),
)
ACCEPT_OUTCOMES = frozenset(
    {DecisionOutcome.accept_oral, DecisionOutcome.accept_spotlight, DecisionOutcome.accept_poster, DecisionOutcome.accept}
)
REJECT_OUTCOMES = frozenset({DecisionOutcome.reject, DecisionOutcome.desk_reject})


def map_decision(raw: str) -> tuple[DecisionOutcome, str]:
    """결정 원문 → (outcome, mapping_rule). 못 맞추면 unknown + "unmatched:<원문>"."""
    key = raw.replace("_", " ").strip().lower()
    for name, pat, outcome in DECISION_RULES:
        if pat.search(key):
            return outcome, f"researcharcade_ext:{name}"
    return DecisionOutcome.unknown, f"unmatched:{raw}"


# ── 본문 정규화·신원 제거 ─────────────────────────────────────────────────

OFFICIAL_SECTIONS = ("Summary", "Strengths", "Weaknesses", "Questions")
OFFICIAL_SCORE_KEYS = ("Rating", "Confidence", "Soundness", "Presentation", "Contribution")
META_SECTIONS = ("Meta Review", "Additional Comments On Reviewer Discussion")
# OpenReview 프로필 id(실명 기반, 예 "~Jane_Doe1"). 공개 댓글 작성자 등이 본문에 남기면 가린다.
PROFILE_ID_RE = re.compile(r"~[A-Za-z][A-Za-z.\-']*(?:_[A-Za-z][A-Za-z.\-']*)+\d+")


def redact_identity(text: str) -> tuple[str, int]:
    """신원 제거: 이메일·ORCID(models.redact_pii) + OpenReview 프로필 id. (결과, 가린 개수)."""
    n = len(PROFILE_ID_RE.findall(text))
    out = redact_pii(PROFILE_ID_RE.sub("[PROFILE]", text))
    n += out.count("[EMAIL]") - text.count("[EMAIL]") + out.count("[ORCID]") - text.count("[ORCID]")
    return out, n


def section_body(value: Any) -> str:
    """칸 하나: ① NFC·LF 정규화 → 앞뒤 공백 제거. 빈 칸은 ""(② 보일러플레이트로 버린다)."""
    if value is None:
        return ""
    return normalize_text(str(value)).strip()


def compose_sections(content: dict[str, Any], names: Iterable[str]) -> str:
    """정해진 순서로 서술 칸만 이어 붙인다. 빈 칸·점수 칸은 버린다. 결과는 아직 신원 제거 전."""
    parts = []
    for name in names:
        body = section_body(content.get(name))
        if body:
            parts.append(f"{name}:\n{body}")
    return "\n\n".join(parts)


def clean_text(raw: str) -> tuple[str, int]:
    """저장 문자열 만들기(정규화 순서 ①→②→③). 이 결과가 Excerpt 오프셋의 기준이다."""
    return redact_identity(raw)


# ── provenance ────────────────────────────────────────────────────────────


def forum_url(paper_id: str) -> str:
    return f"{OPENREVIEW_BASE}/forum?id={paper_id}"


def note_url(paper_id: str, note_id: str) -> str:
    return f"{OPENREVIEW_BASE}/forum?id={paper_id}&noteId={note_id}"


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def raw_hash(raw: str) -> str:
    """원문 해시: 받은 원문을 NFC·LF 정규화한 뒤의 sha256(models.Provenance.content_sha256 정의)."""
    return sha256_text(normalize_text(raw))


def load_input_manifest(raw_dir: Path) -> dict[str, dict[str, Any]]:
    """공개자료 manifest.json(파일별 url·sha256·retrieved_at_utc). 없으면 빈 dict."""
    path = raw_dir / "manifest.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {f["path"]: f for f in data.get("files", [])}


def file_retrieved_at(raw_dir: Path, rel: str, manifest: dict[str, dict[str, Any]]) -> datetime:
    """원본 파일의 접근(내려받은) 시각. manifest 우선, 없으면 파일 수정 시각(UTC)."""
    entry = manifest.get(rel)
    if entry and entry.get("retrieved_at_utc"):
        return datetime.strptime(entry["retrieved_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return datetime.fromtimestamp((raw_dir / rel).stat().st_mtime, tz=UTC).replace(microsecond=0)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_time(value: str | None) -> datetime | None:
    """ResearchArcade `time`("2024-11-04 01:05:41", 시간대 표기 없음)을 UTC로 읽는다."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


# ── 조립 ──────────────────────────────────────────────────────────────────


def note_kind(title: str | None, writer: str | None) -> str:
    """리뷰 노트 종류. 신원(writer)은 분류에만 쓰고 저장하지 않는다."""
    t = title or ""
    if t.startswith("Official Review"):
        return "official_review"
    if t.startswith("Meta Review"):
        return "meta_review"
    if t == "Paper Decision":
        return "decision"
    if (writer or "") == "Authors":
        return "author_response"
    if (writer or "").startswith("~"):
        return "public_comment"
    return "other_comment"  # 리뷰어·AC·PC의 토론 댓글(L0 범위 밖)


@dataclass
class CorpusBuild:
    works: list[Work] = field(default_factory=list)
    reviews: list[ReviewEvent] = field(default_factory=list)
    author_responses: list[AuthorResponse] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    selection: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _provenance(source_url: str, accessed_at: datetime, content_hash: str, api_version: str) -> Provenance:
    return Provenance(
        source=SOURCE,
        source_url=source_url,
        accessed_at=accessed_at,
        content_sha256=content_hash,
        license=LICENSE,
        api_version=api_version,
    )


def _api_version(kind: str, rel: str) -> str:
    return f"hf-parquet:{HF_DATASETS[kind]}@{Path(rel).stem}"


def build_corpus(raw_dir: Path, review_files: Iterable[str] = REVIEW_FILES) -> CorpusBuild:
    """원본 parquet → 검증된 모델 객체. 파일은 쓰지 않는다(write_outputs가 쓴다)."""
    raw_dir = Path(raw_dir)
    review_files = tuple(review_files)
    in_manifest = load_input_manifest(raw_dir)
    out = CorpusBuild()
    st: dict[str, Any] = {}
    redacted = Counter()

    # 1) 논문 선별
    papers_at = file_retrieved_at(raw_dir, PAPERS_FILE, in_manifest)
    papers_api = _api_version("papers", PAPERS_FILE)
    papers = pq.read_table(raw_dir / PAPERS_FILE).to_pylist()
    iclr = [p for p in papers if p["venue"] in VENUES]
    population = [p for p in iclr if p["paper_decision"] != DESK_REJECT_RAW]
    st["population"] = {
        "venues": sorted(VENUES),
        "papers_total": len(iclr),
        "desk_rejected_excluded": len(iclr) - len(population),
        "reviewed_population": len(population),
        "by_venue": dict(sorted(Counter(VENUES[p["venue"]][0] for p in population).items())),
    }
    selected: dict[str, dict[str, Any]] = {}
    for p in population:
        hits = match_fields(p["title"] or "", p["abstract"])
        if hits:
            selected[p["paper_openreview_id"]] = {"row": p, "hits": hits}

    # 2) 리뷰 노트 읽기(신원 칸 writer는 분류에만 쓴다)
    parent: dict[str, str] = {}
    notes: dict[str, dict[str, Any]] = {}
    paper_ids = {p["paper_openreview_id"] for p in iclr}
    kind_counts = Counter()
    for rel in review_files:
        at = file_retrieved_at(raw_dir, rel, in_manifest)
        api = _api_version("reviews", rel)
        tab = pq.read_table(raw_dir / rel)
        cols = {name: tab.column(name).to_pylist() for name in ("venue", "review_openreview_id", "replyto_openreview_id", "writer", "title", "time")}
        content_col = tab.column("content")
        for i, nid in enumerate(cols["review_openreview_id"]):
            if cols["venue"][i] not in VENUES or not nid:
                continue
            parent[nid] = cols["replyto_openreview_id"][i]
            kind = note_kind(cols["title"][i], cols["writer"][i])
            kind_counts[kind] += 1
            notes[nid] = {"kind": kind, "time": cols["time"][i], "idx": i, "content_col": content_col, "at": at, "api": api}

    def root_paper(nid: str) -> str | None:
        seen = 0
        cur = parent.get(nid)
        while cur is not None and seen < 64:
            if cur in paper_ids:
                return cur
            cur = parent.get(cur)
            seen += 1
        return None

    def first_review_ancestor(nid: str) -> str | None:
        cur = parent.get(nid)
        seen = 0
        while cur is not None and seen < 64:
            if cur in paper_ids:
                return None
            n = notes.get(cur)
            if n is not None and n["kind"] == "official_review":
                return cur
            cur = parent.get(cur)
            seen += 1
        return None

    by_paper: dict[str, list[str]] = defaultdict(list)
    orphans = 0
    for nid in notes:
        pid = root_paper(nid)
        if pid is None:
            orphans += 1
            continue
        if pid in selected:
            by_paper[pid].append(nid)

    skipped = Counter()
    decision_notes: dict[str, tuple[str, dict[str, Any]]] = {}
    for pid in sorted(selected):
        for nid in by_paper.get(pid, []):
            n = notes[nid]
            kind = n["kind"]
            if kind not in ("official_review", "meta_review", "decision", "author_response"):
                skipped[kind] += 1
                continue
            raw_content = n["content_col"][n["idx"]].as_py()
            try:
                content = json.loads(raw_content)
            except (TypeError, ValueError):
                skipped["bad_json"] += 1
                continue
            prov = _provenance(note_url(pid, nid), n["at"], raw_hash(raw_content), n["api"])
            work_id = f"{SOURCE}:{pid}"
            created = parse_time(n["time"])
            if kind == "decision":
                decision_notes[pid] = (nid, content)
                continue
            if kind == "author_response":
                text, k = clean_text(section_body(content.get("Comment")))
                if not text:
                    skipped["empty_author_response"] += 1
                    continue
                redacted["author_response"] += k
                rid = first_review_ancestor(nid)
                out.author_responses.append(
                    AuthorResponse(
                        provenance=prov,
                        response_id=f"{SOURCE}:{nid}",
                        work_id=work_id,
                        text=text,
                        review_id=f"{SOURCE}:{rid}" if rid else None,
                        url=note_url(pid, nid),
                    )
                )
                continue
            sections = OFFICIAL_SECTIONS if kind == "official_review" else META_SECTIONS
            text, k = clean_text(compose_sections(content, sections))
            if not text:
                skipped[f"empty_{kind}"] += 1
                continue
            redacted[kind] += k
            rating = content.get("Rating") if kind == "official_review" else None
            confidence = content.get("Confidence") if kind == "official_review" else None
            out.reviews.append(
                ReviewEvent(
                    provenance=prov,
                    review_id=f"{SOURCE}:{nid}",
                    work_id=work_id,
                    text=text,
                    kind=ReviewKind(kind),
                    url=note_url(pid, nid),
                    created=created,
                    rating=None if rating is None else normalize_text(str(rating)),
                    confidence=None if confidence is None else normalize_text(str(confidence)),
                )
            )

    # 3) Work·Decision
    note_agree = Counter()
    for pid in sorted(selected):
        row = selected[pid]["row"]
        hits = selected[pid]["hits"]
        venue, year = VENUES[row["venue"]]
        title, k1 = clean_text(normalize_text(row["title"] or "").strip())
        abstract, k2 = clean_text(normalize_text(row["abstract"] or "").strip())
        redacted["work"] += k1 + k2
        work_id = f"{SOURCE}:{pid}"
        raw_row = canonical_json(row)
        out.works.append(
            Work(
                provenance=_provenance(forum_url(pid), papers_at, raw_hash(raw_row), papers_api),
                work_id=work_id,
                native_id=pid,
                title=title,
                url=forum_url(pid),
                abstract=abstract or None,
                venue=venue,
                year=year,
                fields=list(hits),
                work_type="conference_submission",
            )
        )
        out.selection.append({"work_id": work_id, "fields": list(hits), "keywords": hits})

        raw_decision = row["paper_decision"] or ""
        outcome, rule = map_decision(raw_decision) if raw_decision else (DecisionOutcome.unknown, "unmatched:")
        dn = decision_notes.get(pid)
        if dn:
            nid, content = dn
            note_outcome, _ = map_decision(str(content.get("Decision") or ""))
            note_agree["agree" if note_outcome == outcome else "disagree"] += 1
            text, k = clean_text(section_body(content.get("Comment")))
            redacted["decision"] += k
            url = note_url(pid, nid)
            did = f"{SOURCE}:{nid}"
            api = f"{papers_api}+{notes[nid]['api']}"
            at = max(papers_at, notes[nid]["at"])
            src = canonical_json({"paper": row, "decision_note": content})
        else:
            note_agree["no_decision_note"] += 1
            text, url, did, api, at = "", forum_url(pid), f"{SOURCE}:{pid}:decision", papers_api, papers_at
            src = canonical_json({"paper": row, "decision_note": None})
        out.decisions.append(
            Decision(
                provenance=_provenance(url, at, raw_hash(src), api),
                decision_id=did,
                work_id=work_id,
                outcome=outcome,
                outcome_raw=raw_decision or "(empty)",
                text=text or None,
                url=url,
                mapping_rule=rule,
            )
        )

    # 결정적 순서
    out.works.sort(key=lambda w: w.work_id)
    out.selection.sort(key=lambda s: s["work_id"])
    out.decisions.sort(key=lambda d: d.work_id)
    out.reviews.sort(key=lambda r: (r.work_id, r.created or datetime.min.replace(tzinfo=UTC), r.review_id))
    out.author_responses.sort(key=lambda a: (a.work_id, a.response_id))

    # 통계
    by_field = Counter(f for s in out.selection for f in s["fields"])
    combos = Counter("+".join(s["fields"]) for s in out.selection)
    works_with_review = {r.work_id for r in out.reviews if r.kind == ReviewKind.official_review}
    no_review = [w for w in out.works if w.work_id not in works_with_review]
    outcomes = Counter(d.outcome.value for d in out.decisions)
    n_dec = len(out.decisions)
    n_rej = sum(v for k, v in outcomes.items() if DecisionOutcome(k) in REJECT_OUTCOMES)
    n_acc = sum(v for k, v in outcomes.items() if DecisionOutcome(k) in ACCEPT_OUTCOMES)
    st["selection"] = {
        "works": len(out.works),
        "by_field": {f: by_field.get(f, 0) for f in FIELD_KEYWORDS},
        "by_field_ko": {FIELD_LABELS_KO[f]: by_field.get(f, 0) for f in FIELD_KEYWORDS},
        "field_combinations": dict(sorted(combos.items())),
        "multi_field_works": sum(1 for s in out.selection if len(s["fields"]) > 1),
        "by_venue": dict(sorted(Counter(w.venue for w in out.works).items())),
        "precount": PRECOUNT,
    }
    rkinds = Counter(r.kind.value for r in out.reviews)
    st["linking"] = {
        "review_shards": [Path(r).name for r in review_files],
        "iclr_notes_in_shards": sum(kind_counts.values()),
        "iclr_note_kinds_in_shards": dict(sorted(kind_counts.items())),
        "orphan_notes_no_paper_in_shards": orphans,
        "official_reviews": rkinds.get("official_review", 0),
        "meta_reviews": rkinds.get("meta_review", 0),
        "author_responses": len(out.author_responses),
        "author_responses_linked_to_review": sum(1 for a in out.author_responses if a.review_id),
        "decisions": n_dec,
        "decision_notes_found": n_dec - note_agree.get("no_decision_note", 0),
        "decision_note_vs_paper_decision": dict(sorted(note_agree.items())),
        "works_with_official_review": len(works_with_review),
        "works_without_review_in_shards": len(no_review),
        "works_without_review_by_venue": dict(sorted(Counter(w.venue for w in no_review).items())),
        "skipped_notes": dict(sorted(skipped.items())),
        "identity_redactions": dict(sorted(redacted.items())),
    }
    st["decisions"] = {
        "distribution": dict(sorted(outcomes.items())),
        "raw_distribution": dict(sorted(Counter(d.outcome_raw for d in out.decisions).items())),
        "unknown": outcomes.get("unknown", 0),
        "accept": n_acc,
        "reject": n_rej,
        "reject_ratio": round(n_rej / n_dec, 4) if n_dec else None,
        "reject_ratio_among_reviewed_works": (
            round(
                sum(1 for d in out.decisions if d.outcome in REJECT_OUTCOMES and d.work_id in works_with_review)
                / len(works_with_review),
                4,
            )
            if works_with_review
            else None
        ),
        "precount_reject_ratio": PRECOUNT["reject_ratio"],
    }
    out.stats = st
    return out


# ── 쓰기 ──────────────────────────────────────────────────────────────────

OUTPUT_FILES = {
    "works": "works.jsonl",
    "reviews": "reviews.jsonl",
    "author_responses": "author_responses.jsonl",
    "decisions": "decisions.jsonl",
    "selection": "selection.jsonl",
}
MANIFEST_FILE = "corpus_manifest.json"


def _dump_line(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json", exclude_none=True)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def write_jsonl(path: Path, records: Iterable[Any]) -> dict[str, Any]:
    """한 줄에 한 레코드, UTF-8, LF. 임시 파일에 쓰고 바꿔 끼운다. (레코드 수, 바이트, sha256)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    n = 0
    h = hashlib.sha256()
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            line = _dump_line(rec) + "\n"
            fh.write(line)
            h.update(line.encode("utf-8"))
            n += 1
    tmp.replace(path)
    return {"records": n, "bytes": path.stat().st_size, "sha256": h.hexdigest()}


def write_outputs(build: CorpusBuild, out_dir: Path, raw_dir: Path, *, elapsed_s: float, review_files: Iterable[str] = REVIEW_FILES) -> dict[str, Any]:
    """엔티티별 JSONL과 corpus_manifest.json을 쓴다. manifest를 돌려준다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        OUTPUT_FILES["works"]: write_jsonl(out_dir / OUTPUT_FILES["works"], build.works),
        OUTPUT_FILES["reviews"]: write_jsonl(out_dir / OUTPUT_FILES["reviews"], build.reviews),
        OUTPUT_FILES["author_responses"]: write_jsonl(out_dir / OUTPUT_FILES["author_responses"], build.author_responses),
        OUTPUT_FILES["decisions"]: write_jsonl(out_dir / OUTPUT_FILES["decisions"], build.decisions),
        OUTPUT_FILES["selection"]: write_jsonl(out_dir / OUTPUT_FILES["selection"], build.selection),
    }
    raw_dir = Path(raw_dir)
    in_manifest = load_input_manifest(raw_dir)
    inputs = []
    for rel in (PAPERS_FILE, *review_files):
        p = raw_dir / rel
        entry = in_manifest.get(rel, {})
        digest = sha256_file(p)
        inputs.append(
            {
                "path": rel,
                "bytes": p.stat().st_size,
                "sha256": digest,
                "manifest_sha256_match": (entry.get("sha256") == digest) if entry else None,
                "url": entry.get("url"),
                "retrieved_at_utc": file_retrieved_at(raw_dir, rel, in_manifest).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    manifest = {
        "task": "E1-L0",
        "source": SOURCE,
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "generator": "scripts/collect_researcharcade.py (neumann.sources.researcharcade)",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_s": round(elapsed_s, 2),
        "inputs": inputs,
        "keywords": {
            "sha256": keywords_sha256(),
            "match_rule": "case-insensitive, word boundary start, trailing * = prefix, space/hyphen interchangeable",
            "text": "title + abstract",
            **keyword_spec(),
        },
        **build.stats,
        "normalization": [
            "1 NFC + LF (models.normalize_text), section strip",
            "2 boilerplate: empty sections dropped; score fields (Rating/Confidence kept as fields; Soundness/Presentation/Contribution dropped)",
            "3 identity: emails/ORCID (models.redact_pii) + OpenReview profile ids -> [PROFILE]; writer/title handles never stored",
            "4 store (Excerpt offsets are relative to the stored text)",
        ],
        "outputs": outputs,
    }
    tmp = out_dir / (MANIFEST_FILE + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(out_dir / MANIFEST_FILE)
    return manifest


def collect(raw_dir: Path, out_dir: Path, review_files: Iterable[str] = REVIEW_FILES) -> dict[str, Any]:
    """조립 한 번: 읽기 → 선별 → 연결 → 검증 → 쓰기. manifest를 돌려준다."""
    t0 = time.perf_counter()
    review_files = tuple(review_files)
    build = build_corpus(raw_dir, review_files)
    return write_outputs(build, out_dir, raw_dir, elapsed_s=time.perf_counter() - t0, review_files=review_files)


__all__ = [
    "ATTRIBUTION",
    "DECISION_RULES",
    "FIELD_KEYWORDS",
    "FIELD_LABELS_KO",
    "LICENSE",
    "MANIFEST_FILE",
    "OUTPUT_FILES",
    "PAPERS_FILE",
    "REVIEW_FILES",
    "SOURCE",
    "CorpusBuild",
    "build_corpus",
    "clean_text",
    "collect",
    "compose_sections",
    "forum_url",
    "keyword_regex",
    "keywords_sha256",
    "map_decision",
    "match_fields",
    "note_kind",
    "note_url",
    "redact_identity",
    "write_outputs",
]
