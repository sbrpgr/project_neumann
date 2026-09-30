"""E1-L3: 코퍼스 규모 확대 준비 — 리뷰 샤드 2~5 받기 + AI for Science + 일반 ML 확대 코퍼스 조립.

E1-L0(`neumann.sources.researcharcade`, `neumann.sources.corpus`)의 선별 키워드·정규화·신원 제거·
레코드 형식을 그대로 쓴다. 이 파일은 그 위에 두 가지만 더한다.

1. **샤드 받기**(`fetch_shards`): HF `ulab-ai/ResearchArcade-openreview-reviews`의
   `data/train-0000{2..5}-of-00006.parquet`을 고정 리비전에서 받아 공유 폴더 `data/raw/researcharcade/`에
   둔다. HF가 알려 준 LFS sha256·크기와 대조해 맞을 때만 제자리에 놓고, 받은 URL·시각·크기·sha256을
   `manifest.json`에 적는다(키트 `공개자료/manifest.json`과 같은 칸).
2. **확대 코퍼스 조립**(`build_l3`, `collect_l3`): 샤드 6개 전부로 ICLR 2024·2025 논문을 연결하고
   AI for Science 선별(E1-L0 키워드 그대로) + 일반 ML 논문(결정과 공식 심사평이 있는 것, venue×결정 층화
   무작위, 시드 고정)을 합쳐 `data/processed_l3/`에 쓴다. 현재 `data/processed/`와 색인은 건드리지 않는다.

분야 태그: AI for Science 논문의 `Work.fields`는 E1-L0 분야 slug 그대로이고, 일반 ML 논문은
`["general_ml"]`이다. `is_ai4science(work)`로 구분한다. `selection.jsonl`에는 `group`·`ai4science`를 둔다.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:  # pragma: no cover
    import httpx

    from neumann.models import Work

# ── 1. 샤드 받기 ──────────────────────────────────────────────────────────

HF_REVIEWS_REPO = "ulab-ai/ResearchArcade-openreview-reviews"
HF_BASE = "https://huggingface.co"
# 2026-09-30 기준 main 리비전. 샤드 0·1의 LFS sha256이 키트(9/28 받음)와 같은 것을 확인했다.
HF_REVIEWS_REVISION = "179a53618432789fc26d235fa85cd69a889f5934"
N_SHARDS = 6
KIT_SHARDS = (0, 1)
L3_SHARDS = (2, 3, 4, 5)
RAW_SUBDIR = Path("raw") / "researcharcade"  # 공유 데이터 폴더 아래
SHARD_MANIFEST = "manifest.json"
USER_AGENT = "project-neumann-e1-l3/0.1 (+https://github.com/sbrpgr/project_neumann)"


def shard_name(i: int) -> str:
    return f"train-{i:05d}-of-{N_SHARDS:05d}.parquet"


def shard_repo_path(i: int) -> str:
    """HF 저장소 안 경로(data/train-…)."""
    return f"data/{shard_name(i)}"


def shard_rel_path(i: int) -> str:
    """`data/raw/researcharcade/` 아래 저장 경로. 키트의 `data/researcharcade/reviews/…`와 같은 모양."""
    return f"reviews/{shard_name(i)}"


def shard_url(i: int, revision: str = HF_REVIEWS_REVISION) -> str:
    return f"{HF_BASE}/datasets/{HF_REVIEWS_REPO}/resolve/{revision}/{shard_repo_path(i)}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def hf_lfs_index(client: "httpx.Client", repo: str = HF_REVIEWS_REPO, revision: str = HF_REVIEWS_REVISION) -> dict[str, dict[str, Any]]:
    """HF tree API → {저장소 경로: {"bytes", "sha256"}}. sha256은 LFS oid(파일 전체의 sha256)다."""
    url = f"{HF_BASE}/api/datasets/{repo}/tree/{revision}/data"
    resp = client.get(url)
    resp.raise_for_status()
    out: dict[str, dict[str, Any]] = {}
    for item in resp.json():
        lfs = item.get("lfs") or {}
        if item.get("type") == "file" and lfs.get("oid"):
            out[item["path"]] = {"bytes": int(lfs.get("size", item.get("size", 0))), "sha256": lfs["oid"]}
    return out


class ShardIntegrityError(RuntimeError):
    """받은 파일의 크기·sha256이 HF가 알려 준 값과 다르다(파일은 제자리에 놓지 않는다)."""


def download_file(client: "httpx.Client", url: str, dest: Path, *, expected_sha256: str, expected_bytes: int | None = None) -> dict[str, Any]:
    """스트리밍으로 `dest.part`에 받고 sha256·크기를 대조한 뒤에만 `dest`로 바꿔 끼운다."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    n = 0
    t0 = time.perf_counter()
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with part.open("wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
                h.update(chunk)
                n += len(chunk)
    digest = h.hexdigest()
    if digest != expected_sha256 or (expected_bytes is not None and n != expected_bytes):
        part.unlink(missing_ok=True)
        raise ShardIntegrityError(
            f"{dest.name}: sha256/크기 불일치(받은 {n}B {digest[:12]}…, 기대 {expected_bytes}B {expected_sha256[:12]}…)"
        )
    os.replace(part, dest)
    return {"bytes": n, "sha256": digest, "elapsed_s": round(time.perf_counter() - t0, 1)}


def load_shard_manifest(raw_l3_dir: Path) -> dict[str, Any]:
    path = Path(raw_l3_dir) / SHARD_MANIFEST
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _merge_files(files: list[dict[str, Any]], previous: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """이번 결과 + 이번에 다루지 않은 기존 항목."""
    done = {f["path"] for f in files}
    return [*files, *(v for k, v in previous.items() if k not in done)]


def _shard_manifest(revision: str, files: list[dict[str, Any]], kit: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_utc": _utc_now(),
        "task": "E1-L3",
        "dataset": HF_REVIEWS_REPO,
        "revision": revision,
        "license": "UNDECLARED",
        "note": "원본 재배포 금지(라이선스 미선언). 공유 데이터 폴더에만 두고 커밋하지 않는다.",
        "files": sorted(files, key=lambda f: f["path"]),
        "kit_consistency": kit,
    }


def fetch_shards(
    raw_l3_dir: Path,
    shards: Iterable[int] = L3_SHARDS,
    *,
    client: "httpx.Client | None" = None,
    revision: str = HF_REVIEWS_REVISION,
    kit_raw_dir: Path | None = None,
    log: Any = print,
) -> dict[str, Any]:
    """샤드를 받아 `raw_l3_dir/reviews/`에 두고 `raw_l3_dir/manifest.json`을 쓴다(이미 있고 sha256이 맞으면 건너뜀).

    manifest `files[]` 칸: path, bytes, sha256, url, retrieved_at_utc(키트 manifest와 같음) + hf_lfs_sha256, revision.
    kit_raw_dir을 주면 키트 샤드 0·1의 sha256이 같은 리비전의 HF LFS 값과 같은지도 적는다(kit_consistency).
    이번에 받지 않은 샤드의 기존 manifest 항목은 그대로 둔다.
    """
    import httpx

    raw_l3_dir = Path(raw_l3_dir)
    raw_l3_dir.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    if client is None:
        client = httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0), headers={"User-Agent": USER_AGENT})
    try:
        index = hf_lfs_index(client, HF_REVIEWS_REPO, revision)
        previous = {f["path"]: f for f in load_shard_manifest(raw_l3_dir).get("files", [])}
        files = []
        for i in sorted(set(shards)):
            rel = shard_rel_path(i)
            dest = raw_l3_dir / rel
            meta = index.get(shard_repo_path(i))
            if meta is None:
                raise ShardIntegrityError(f"HF 리비전 {revision}에 {shard_repo_path(i)}가 없다")
            url = shard_url(i, revision)
            prev = previous.get(rel)
            if dest.is_file() and prev and prev.get("sha256") == meta["sha256"] and sha256_file(dest) == meta["sha256"]:
                log(f"[건너뜀] {rel}: 이미 있고 sha256 일치")
                files.append(prev)
                continue
            log(f"[받는 중] {rel} ({meta['bytes']:,}B) ← {url}")
            info = download_file(client, url, dest, expected_sha256=meta["sha256"], expected_bytes=meta["bytes"])
            rec = {
                "path": rel,
                "bytes": info["bytes"],
                "sha256": info["sha256"],
                "url": url,
                "retrieved_at_utc": _utc_now(),
                "hf_lfs_sha256": meta["sha256"],
                "sha256_match": info["sha256"] == meta["sha256"],
                "revision": revision,
                "download_s": info["elapsed_s"],
            }
            log(f"[받음] {rel}: {info['bytes']:,}B sha256={info['sha256']} ({info['elapsed_s']}초)")
            files.append(rec)
            # 중간에 끊겨도 받은 것은 남도록 파일마다 manifest를 갱신한다
            _write_json(raw_l3_dir / SHARD_MANIFEST, _shard_manifest(revision, _merge_files(files, previous), []))
        kit = []
        if kit_raw_dir is not None:
            kit_dir = Path(kit_raw_dir)
            kit_manifest = {}
            km = kit_dir / "manifest.json"
            if km.is_file():
                kit_manifest = {f["path"]: f for f in json.loads(km.read_text(encoding="utf-8")).get("files", [])}
            for i in KIT_SHARDS:
                krel = f"data/researcharcade/reviews/{shard_name(i)}"
                entry = kit_manifest.get(krel, {})
                meta = index.get(shard_repo_path(i), {})
                kit.append(
                    {
                        "path": krel,
                        "kit_sha256": entry.get("sha256"),
                        "hf_lfs_sha256_at_revision": meta.get("sha256"),
                        "same": bool(entry.get("sha256")) and entry.get("sha256") == meta.get("sha256"),
                    }
                )
        manifest = _shard_manifest(revision, _merge_files(files, previous), kit)
        _write_json(raw_l3_dir / SHARD_MANIFEST, manifest)
        return manifest
    finally:
        if own_client:
            client.close()


# ── 2. 확대 코퍼스 조립 ───────────────────────────────────────────────────
# E1-L0 모듈(researcharcade·corpus)이 main에 들어오기 전 브랜치에서도 샤드 받기는 돌도록 따로 가져온다.

try:  # pragma: no cover - 병합 상태에 따라 갈린다
    from neumann.sources import researcharcade as ra
except ImportError:  # E1-L0 미병합
    ra = None  # type: ignore[assignment]

GENERAL_ML_FIELD = "general_ml"
GROUP_AI4S = "ai4science"
GROUP_GENERAL = "general_ml"
GROUPS = (GROUP_AI4S, GROUP_GENERAL)
DEFAULT_GENERAL_ML_N = 1000
DEFAULT_SEED = 20260930
MIN_TOTAL_WORKS = 2000
L3_SUBDIR = "processed_l3"
LIGHT_COLUMNS = ("venue", "review_openreview_id", "replyto_openreview_id", "writer", "title", "time")
KEPT_KINDS = ("official_review", "meta_review", "decision", "author_response")


def _require_ra():
    if ra is None:
        raise RuntimeError("neumann.sources.researcharcade(E1-L0)가 없다. task/E1-L0이 main에 병합된 뒤 조립한다")
    return ra


def is_ai4science(work: "Work") -> bool:
    """AI for Science 선별 논문인가(일반 ML 태그가 없으면 참)."""
    return GENERAL_ML_FIELD not in work.fields


def field_labels_ko() -> dict[str, str]:
    return {**_require_ra().FIELD_LABELS_KO, GENERAL_ML_FIELD: "일반 ML"}


@dataclass(frozen=True)
class ShardInput:
    """리뷰 샤드 하나: 절대 경로와 출처(받은 URL·시각·sha256)."""

    index: int
    path: Path
    url: str | None
    retrieved_at: datetime
    expected_sha256: str | None
    origin: str  # "kit"(공개자료) | "l3"(data/raw/researcharcade)

    @property
    def name(self) -> str:
        return shard_name(self.index)

    @property
    def api_version(self) -> str:
        """E1-L0와 같은 형식: hf-parquet:<repo>@<파일 stem>."""
        return f"hf-parquet:{HF_REVIEWS_REPO}@{Path(self.name).stem}"


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def resolve_shards(kit_raw_dir: Path, raw_l3_dir: Path, shards: Iterable[int] = range(N_SHARDS)) -> list[ShardInput]:
    """샤드 번호 → 위치와 출처. 키트(공개자료/manifest.json)에 있으면 키트, 없으면 L3 manifest에서 찾는다.
    파일이나 manifest 항목이 없으면 FileNotFoundError(출처 없는 입력은 쓰지 않는다)."""
    kit_raw_dir, raw_l3_dir = Path(kit_raw_dir), Path(raw_l3_dir)
    kit_manifest = _require_ra().load_input_manifest(kit_raw_dir)
    l3_manifest = {f["path"]: f for f in load_shard_manifest(raw_l3_dir).get("files", [])}
    out = []
    for i in sorted(set(shards)):
        kit_rel = f"data/researcharcade/reviews/{shard_name(i)}"
        l3_rel = shard_rel_path(i)
        if (kit_raw_dir / kit_rel).is_file() and kit_rel in kit_manifest:
            e, path, origin = kit_manifest[kit_rel], kit_raw_dir / kit_rel, "kit"
        elif (raw_l3_dir / l3_rel).is_file() and l3_rel in l3_manifest:
            e, path, origin = l3_manifest[l3_rel], raw_l3_dir / l3_rel, "l3"
        else:
            raise FileNotFoundError(
                f"샤드 {i}({shard_name(i)})가 없다: {kit_raw_dir / kit_rel} 또는 {raw_l3_dir / l3_rel}(+manifest). "
                "먼저 `python scripts/collect_l3_shards.py`"
            )
        out.append(ShardInput(i, path, e.get("url"), _parse_utc(e["retrieved_at_utc"]), e.get("sha256"), origin))
    return out


def _rank_key(seed: int, paper_id: str) -> str:
    return hashlib.sha256(f"{seed}:{paper_id}".encode("utf-8")).hexdigest()


def allocate(strata_sizes: dict[Any, int], n: int) -> dict[Any, int]:
    """비례 배분(최대 나머지 방식). 합은 정확히 min(n, 전체), 층 크기를 넘지 않는다. 나머지 동점은 층 키 순."""
    total = sum(strata_sizes.values())
    n = max(0, min(n, total))
    if n == 0:
        return {k: 0 for k in strata_sizes}
    quotas = {k: n * v / total for k, v in strata_sizes.items()}
    alloc = {k: min(strata_sizes[k], int(q)) for k, q in quotas.items()}
    order = sorted(strata_sizes, key=lambda k: (-(quotas[k] - int(quotas[k])), str(k)))
    rest = n - sum(alloc.values())
    while rest > 0:
        for k in order:
            if rest and alloc[k] < strata_sizes[k]:
                alloc[k] += 1
                rest -= 1
    return alloc


def sample_general_ml(pool: dict[str, tuple[str, str]], n: int, seed: int) -> tuple[list[str], dict[str, Any]]:
    """일반 ML 후보 {paper_id: (venue, outcome)} → venue×결정 층화 무작위 n편(시드 고정 해시 순위).
    같은 입력·시드면 같은 결과다. (고른 paper_id 정렬 목록, 층별 후보·배분)."""
    strata: dict[tuple[str, str], list[str]] = defaultdict(list)
    for pid, key in pool.items():
        strata[key].append(pid)
    sizes = {k: len(v) for k, v in strata.items()}
    alloc = allocate(sizes, n)
    chosen: list[str] = []
    for k in sorted(strata):
        ranked = sorted(strata[k], key=lambda pid: (_rank_key(seed, pid), pid))
        chosen.extend(ranked[: alloc[k]])
    spec = {
        "method": "stratified random by (venue, decision outcome); rank = sha256(f'{seed}:{paper_id}'); largest-remainder allocation",
        "seed": seed,
        "requested": n,
        "selected": len(chosen),
        "pool": len(pool),
        "strata": [{"venue": k[0], "outcome": k[1], "pool": sizes[k], "selected": alloc[k]} for k in sorted(strata)],
    }
    return sorted(chosen), spec


@dataclass
class _Note:
    kind: str
    time: str | None
    shard: int
    row: int


def _read_light(shard: ShardInput, venues: set[str]) -> tuple[dict[str, Any], list[tuple[str, Any, str, Any, int]]]:
    """샤드의 가벼운 칸만 읽는다(content 제외). (샤드 통계, 대상 venue 노트 [(id, replyto, kind, time, 행)])."""
    import pyarrow.parquet as pq

    mod = _require_ra()
    tab = pq.read_table(shard.path, columns=list(LIGHT_COLUMNS))
    cols = {c: tab.column(c).to_pylist() for c in LIGHT_COLUMNS}
    rows = []
    for i, nid in enumerate(cols["review_openreview_id"]):
        if cols["venue"][i] not in venues or not nid:
            continue
        kind = mod.note_kind(cols["title"][i], cols["writer"][i])  # writer는 분류에만 쓰고 저장하지 않는다
        rows.append((nid, cols["replyto_openreview_id"][i], kind, cols["time"][i], i))
    venue_counts = Counter(cols["venue"])
    stats = {
        "shard": shard.index,
        "file": shard.name,
        "origin": shard.origin,
        "rows": tab.num_rows,
        "venues": dict(sorted(venue_counts.items(), key=lambda kv: (-kv[1], kv[0] or ""))),
    }
    return stats, rows


@dataclass
class L3Build:
    works: list[Any] = field(default_factory=list)
    reviews: list[Any] = field(default_factory=list)
    author_responses: list[Any] = field(default_factory=list)
    decisions: list[Any] = field(default_factory=list)
    selection: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _coverage(papers: Iterable[str], reviewed: set[str]) -> dict[str, Any]:
    papers = list(papers)
    n = len(papers)
    k = sum(1 for p in papers if p in reviewed)
    return {"papers": n, "with_official_review": k, "without": n - k, "ratio": round(k / n, 4) if n else None}


def build_l3(
    kit_raw_dir: Path,
    shards: list[ShardInput],
    *,
    general_ml_n: int = DEFAULT_GENERAL_ML_N,
    seed: int = DEFAULT_SEED,
    before_shards: Iterable[int] = KIT_SHARDS,
) -> L3Build:
    """papers + 리뷰 샤드들 → 검증된 모델 객체(AI for Science 전부 + 일반 ML 표본). 파일은 쓰지 않는다.

    선별·연결·정규화·신원 제거는 E1-L0(`researcharcade`)의 함수를 그대로 쓴다. 다른 점은
    ① 노트를 샤드 여러 개에서 읽고(본문은 선별 논문 행만), ② 일반 ML 표본을 더하고, ③ 커버리지 전후를 잰다.
    """
    import pyarrow.parquet as pq

    from neumann.models import AuthorResponse, Decision, DecisionOutcome, Provenance, ReviewEvent, ReviewKind, Work, normalize_text

    mod = _require_ra()
    kit_raw_dir = Path(kit_raw_dir)
    before_shards = tuple(before_shards)
    in_manifest = mod.load_input_manifest(kit_raw_dir)
    out = L3Build()
    st: dict[str, Any] = {}
    redacted: Counter = Counter()

    def prov(url: str, at: datetime, content_hash: str, api: str) -> Provenance:
        return Provenance(source=mod.SOURCE, source_url=url, accessed_at=at, content_sha256=content_hash, license=mod.LICENSE, api_version=api)

    # 1) 논문 모집단(E1-L0와 같다: ICLR 2024·2025, 데스크 리젝 제외)
    papers_at = mod.file_retrieved_at(kit_raw_dir, mod.PAPERS_FILE, in_manifest)
    papers_api = f"hf-parquet:{mod.HF_DATASETS['papers']}@{Path(mod.PAPERS_FILE).stem}"
    papers = pq.read_table(kit_raw_dir / mod.PAPERS_FILE).to_pylist()
    iclr = [p for p in papers if p["venue"] in mod.VENUES]
    pop_by_id = {p["paper_openreview_id"]: p for p in iclr if p["paper_decision"] != mod.DESK_REJECT_RAW}
    paper_ids = {p["paper_openreview_id"] for p in iclr}
    venue_of = {pid: mod.VENUES[p["venue"]][0] for pid, p in pop_by_id.items()}
    venue_names = sorted(set(venue_of.values()))
    st["population"] = {
        "venues": sorted(mod.VENUES),
        "papers_total": len(iclr),
        "desk_rejected_excluded": len(iclr) - len(pop_by_id),
        "reviewed_population": len(pop_by_id),
        "by_venue": dict(sorted(Counter(venue_of.values()).items())),
    }
    ai4s: dict[str, dict[str, list[str]]] = {}
    for pid, p in pop_by_id.items():
        hits = mod.match_fields(p["title"] or "", p["abstract"])
        if hits:
            ai4s[pid] = hits

    # 2) 샤드들의 가벼운 칸 → 노트 그래프(같은 id가 또 나오면 처음 것만)
    parent: dict[str, Any] = {}
    notes: dict[str, _Note] = {}
    shard_stats = []
    dup = 0
    kind_counts: Counter = Counter()
    for sh in shards:
        s_stats, rows = _read_light(sh, set(mod.VENUES))
        s_kinds: Counter = Counter()
        for nid, reply, kind, t, i in rows:
            if nid in notes:
                dup += 1
                continue
            parent[nid] = reply
            notes[nid] = _Note(kind, t, sh.index, i)
            s_kinds[kind] += 1
        kind_counts.update(s_kinds)
        s_stats["iclr_2024_2025_notes"] = sum(s_kinds.values())
        s_stats["iclr_2024_2025_note_kinds"] = dict(sorted(s_kinds.items()))
        shard_stats.append(s_stats)

    root_cache: dict[str, str | None] = {}

    def root_paper(nid: str) -> str | None:
        path, cur, found = [nid], parent.get(nid), None
        while cur is not None and len(path) <= 64:
            if cur in paper_ids:
                found = cur
                break
            if cur in root_cache:
                found = root_cache[cur]
                break
            path.append(cur)
            cur = parent.get(cur)
        for x in path:
            root_cache[x] = found
        return found

    def first_review_ancestor(nid: str) -> str | None:
        cur, seen = parent.get(nid), 0
        while cur is not None and seen < 64:
            if cur in paper_ids:
                return None
            n = notes.get(cur)
            if n is not None and n.kind == "official_review":
                return cur
            cur = parent.get(cur)
            seen += 1
        return None

    by_paper: dict[str, list[str]] = defaultdict(list)
    reviewed_in_shard: dict[int, set[str]] = defaultdict(set)
    orphans = 0
    for nid, n in notes.items():
        pid = root_paper(nid)
        if pid is None:
            orphans += 1
            continue
        by_paper[pid].append(nid)
        if n.kind == "official_review" and pid in pop_by_id:
            reviewed_in_shard[n.shard].add(pid)

    # 3) 커버리지 전후(공식 심사평이 1건 이상 연결된 논문 비율)
    all_idx = tuple(sh.index for sh in shards)
    reviewed_before: set[str] = set().union(*(reviewed_in_shard[i] for i in before_shards if i in all_idx))
    reviewed_after: set[str] = set().union(*(reviewed_in_shard[i] for i in all_idx))
    general_pop = [pid for pid in pop_by_id if pid not in ai4s]

    def cov_block(reviewed: set[str]) -> dict[str, Any]:
        return {
            "population": _coverage(pop_by_id, reviewed),
            "population_by_venue": {v: _coverage([p for p in pop_by_id if venue_of[p] == v], reviewed) for v in venue_names},
            "ai4science": _coverage(ai4s, reviewed),
            "ai4science_by_venue": {v: _coverage([p for p in ai4s if venue_of[p] == v], reviewed) for v in venue_names},
            "general_ml_population": _coverage(general_pop, reviewed),
        }

    cumulative, acc = [], set()
    for sh in shards:
        acc |= reviewed_in_shard[sh.index]
        cumulative.append(
            {
                "through_shard": sh.index,
                "population_with_official_review": len(acc),
                "population_ratio": round(len(acc) / len(pop_by_id), 4) if pop_by_id else None,
                "ai4science_with_official_review": sum(1 for p in ai4s if p in acc),
            }
        )
    for s in shard_stats:
        s["population_papers_with_official_review_in_shard"] = len(reviewed_in_shard[s["shard"]])
        s["ai4science_papers_with_official_review_in_shard"] = sum(1 for p in ai4s if p in reviewed_in_shard[s["shard"]])
    st["coverage"] = {
        "definition": "공식 심사평(Official Review) 노트가 1건 이상 연결된 논문 비율. 모집단 = ICLR 2024·2025 심사 논문(데스크 리젝 제외)",
        "before": {"shards": [i for i in before_shards if i in all_idx], **cov_block(reviewed_before)},
        "after": {"shards": list(all_idx), **cov_block(reviewed_after)},
        "cumulative": cumulative,
        "per_shard": shard_stats,
    }

    # 4) 일반 ML 표본: 결정(수락·거절)과 공식 심사평이 있는 비AI4S 논문 중 층화 무작위
    pool: dict[str, tuple[str, str]] = {}
    pool_excluded: Counter = Counter()
    for pid in general_pop:
        outcome, _ = mod.map_decision(pop_by_id[pid]["paper_decision"] or "")
        if outcome not in mod.ACCEPT_OUTCOMES and outcome not in mod.REJECT_OUTCOMES:
            pool_excluded[f"decision_{outcome.value}"] += 1
        elif pid not in reviewed_after:
            pool_excluded["no_official_review"] += 1
        else:
            pool[pid] = (venue_of[pid], outcome.value)
    general_ids, sample_spec = sample_general_ml(pool, general_ml_n, seed)
    sample_spec["pool_excluded"] = dict(sorted(pool_excluded.items()))
    selected: dict[str, tuple[str, dict[str, list[str]]]] = {pid: (GROUP_AI4S, hits) for pid, hits in ai4s.items()}
    selected.update({pid: (GROUP_GENERAL, {}) for pid in general_ids})

    # 5) 선별 논문 노트의 본문만 샤드별로 꺼낸다(content 칸은 필요한 행만 take)
    need: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for pid in selected:
        for nid in by_paper.get(pid, []):
            n = notes[nid]
            if n.kind in KEPT_KINDS:
                need[n.shard].append((n.row, nid))
    raw_content: dict[str, str] = {}
    for sh in shards:
        items = sorted(need.get(sh.index, []))
        if items:
            col = pq.read_table(sh.path, columns=["content"]).column("content")
            for (_, nid), c in zip(items, col.take([r for r, _ in items]).to_pylist()):
                raw_content[nid] = c
            del col
    shard_by_idx = {sh.index: sh for sh in shards}

    skipped: Counter = Counter()
    decision_notes: dict[str, tuple[str, dict[str, Any]]] = {}
    for pid in sorted(selected):
        work_id = f"{mod.SOURCE}:{pid}"
        for nid in by_paper.get(pid, []):
            n = notes[nid]
            if n.kind not in KEPT_KINDS:
                skipped[n.kind] += 1
                continue
            raw = raw_content[nid]
            try:
                content = json.loads(raw)
            except (TypeError, ValueError):
                skipped["bad_json"] += 1
                continue
            sh = shard_by_idx[n.shard]
            p = prov(mod.note_url(pid, nid), sh.retrieved_at, mod.raw_hash(raw), sh.api_version)
            if n.kind == "decision":
                decision_notes[pid] = (nid, content)
                continue
            if n.kind == "author_response":
                text, k = mod.clean_text(mod.section_body(content.get("Comment")))
                if not text:
                    skipped["empty_author_response"] += 1
                    continue
                redacted["author_response"] += k
                rid = first_review_ancestor(nid)
                out.author_responses.append(
                    AuthorResponse(
                        provenance=p,
                        response_id=f"{mod.SOURCE}:{nid}",
                        work_id=work_id,
                        text=text,
                        review_id=f"{mod.SOURCE}:{rid}" if rid else None,
                        url=mod.note_url(pid, nid),
                    )
                )
                continue
            sections = mod.OFFICIAL_SECTIONS if n.kind == "official_review" else mod.META_SECTIONS
            text, k = mod.clean_text(mod.compose_sections(content, sections))
            if not text:
                skipped[f"empty_{n.kind}"] += 1
                continue
            redacted[n.kind] += k
            rating = content.get("Rating") if n.kind == "official_review" else None
            confidence = content.get("Confidence") if n.kind == "official_review" else None
            out.reviews.append(
                ReviewEvent(
                    provenance=p,
                    review_id=f"{mod.SOURCE}:{nid}",
                    work_id=work_id,
                    text=text,
                    kind=ReviewKind(n.kind),
                    url=mod.note_url(pid, nid),
                    created=mod.parse_time(n.time),
                    rating=None if rating is None else normalize_text(str(rating)),
                    confidence=None if confidence is None else normalize_text(str(confidence)),
                )
            )

    # 6) Work·Decision(E1-L0와 같은 규칙, 분야 태그만 그룹별)
    note_agree: Counter = Counter()
    for pid in sorted(selected):
        group, hits = selected[pid]
        row = pop_by_id[pid]
        venue, year = mod.VENUES[row["venue"]]
        title, k1 = mod.clean_text(normalize_text(row["title"] or "").strip())
        abstract, k2 = mod.clean_text(normalize_text(row["abstract"] or "").strip())
        redacted["work"] += k1 + k2
        work_id = f"{mod.SOURCE}:{pid}"
        fields = list(hits) if group == GROUP_AI4S else [GENERAL_ML_FIELD]
        out.works.append(
            Work(
                provenance=prov(mod.forum_url(pid), papers_at, mod.raw_hash(mod.canonical_json(row)), papers_api),
                work_id=work_id,
                native_id=pid,
                title=title,
                url=mod.forum_url(pid),
                abstract=abstract or None,
                venue=venue,
                year=year,
                fields=fields,
                work_type="conference_submission",
            )
        )
        out.selection.append({"work_id": work_id, "group": group, "ai4science": group == GROUP_AI4S, "fields": fields, "keywords": hits})
        raw_decision = row["paper_decision"] or ""
        outcome, rule = mod.map_decision(raw_decision) if raw_decision else (DecisionOutcome.unknown, "unmatched:")
        dn = decision_notes.get(pid)
        if dn:
            nid, content = dn
            note_outcome, _ = mod.map_decision(str(content.get("Decision") or ""))
            note_agree["agree" if note_outcome == outcome else "disagree"] += 1
            text, k = mod.clean_text(mod.section_body(content.get("Comment")))
            redacted["decision"] += k
            sh = shard_by_idx[notes[nid].shard]
            url, did = mod.note_url(pid, nid), f"{mod.SOURCE}:{nid}"
            api, at = f"{papers_api}+{sh.api_version}", max(papers_at, sh.retrieved_at)
            src = mod.canonical_json({"paper": row, "decision_note": content})
        else:
            note_agree["no_decision_note"] += 1
            text, url, did, api, at = "", mod.forum_url(pid), f"{mod.SOURCE}:{pid}:decision", papers_api, papers_at
            src = mod.canonical_json({"paper": row, "decision_note": None})
        out.decisions.append(
            Decision(
                provenance=prov(url, at, mod.raw_hash(src), api),
                decision_id=did,
                work_id=work_id,
                outcome=outcome,
                outcome_raw=raw_decision or "(empty)",
                text=text or None,
                url=url,
                mapping_rule=rule,
            )
        )

    # 결정적 순서(E1-L0와 같은 키)
    out.works.sort(key=lambda w: w.work_id)
    out.selection.sort(key=lambda s: s["work_id"])
    out.decisions.sort(key=lambda d: d.work_id)
    out.reviews.sort(key=lambda r: (r.work_id, r.created or datetime.min.replace(tzinfo=UTC), r.review_id))
    out.author_responses.sort(key=lambda a: (a.work_id, a.response_id))
    out.stats = {**st, **_summary(out, mod, sample_spec, shards, kind_counts, dup, orphans, note_agree, skipped, redacted)}
    return out


def _summary(out: L3Build, mod: Any, sample_spec: dict[str, Any], shards: list[ShardInput], kind_counts: Counter, dup: int,
             orphans: int, note_agree: Counter, skipped: Counter, redacted: Counter) -> dict[str, Any]:
    from neumann.models import DecisionOutcome, ReviewKind

    group_of = {s["work_id"]: s["group"] for s in out.selection}
    by_field = Counter(f for s in out.selection for f in s["fields"])
    field_order = (*mod.FIELD_KEYWORDS, GENERAL_ML_FIELD)
    labels = field_labels_ko()
    works_with_review = {r.work_id for r in out.reviews if r.kind == ReviewKind.official_review}
    rk_by_group: dict[str, Counter] = defaultdict(Counter)
    for r in out.reviews:
        rk_by_group[group_of[r.work_id]][r.kind.value] += 1
    resp_by_group = Counter(group_of[a.work_id] for a in out.author_responses)
    outcomes_by_group: dict[str, Counter] = defaultdict(Counter)
    for d in out.decisions:
        outcomes_by_group[group_of[d.work_id]][d.outcome.value] += 1
    all_outcomes: Counter = Counter()
    for c in outcomes_by_group.values():
        all_outcomes.update(c)

    def reject_ratio(c: Counter) -> float | None:
        n = sum(c.values())
        return round(sum(v for k, v in c.items() if DecisionOutcome(k) in mod.REJECT_OUTCOMES) / n, 4) if n else None

    n_group = Counter(group_of.values())
    no_review = [w for w in out.works if w.work_id not in works_with_review]
    rkinds = Counter(r.kind.value for r in out.reviews)
    return {
        "selection": {
            "works": len(out.works),
            "min_total_works": MIN_TOTAL_WORKS,
            "by_group": {g: n_group.get(g, 0) for g in GROUPS},
            "by_field": {f: by_field.get(f, 0) for f in field_order},
            "by_field_ko": {labels[f]: by_field.get(f, 0) for f in field_order},
            "by_venue": dict(sorted(Counter(w.venue for w in out.works).items())),
            "by_group_venue": {g: dict(sorted(Counter(w.venue for w in out.works if group_of[w.work_id] == g).items())) for g in GROUPS},
            "ai4science_multi_field_works": sum(1 for s in out.selection if s["ai4science"] and len(s["fields"]) > 1),
            "field_tag_rule": "AI for Science = E1-L0 분야 slug(들), 일반 ML = ['general_ml']",
            "general_ml_sampling": sample_spec,
        },
        "linking": {
            "review_shards": [sh.name for sh in shards],
            "iclr_notes_in_shards": sum(kind_counts.values()),
            "iclr_note_kinds_in_shards": dict(sorted(kind_counts.items())),
            "duplicate_note_ids_across_shards": dup,
            "orphan_notes_no_paper_in_shards": orphans,
            "official_reviews": rkinds.get("official_review", 0),
            "meta_reviews": rkinds.get("meta_review", 0),
            "reviews_by_group": {g: dict(sorted(rk_by_group[g].items())) for g in GROUPS},
            "author_responses": len(out.author_responses),
            "author_responses_by_group": {g: resp_by_group.get(g, 0) for g in GROUPS},
            "author_responses_linked_to_review": sum(1 for a in out.author_responses if a.review_id),
            "decisions": len(out.decisions),
            "decision_notes_found": len(out.decisions) - note_agree.get("no_decision_note", 0),
            "decision_note_vs_paper_decision": dict(sorted(note_agree.items())),
            "works_with_official_review": len(works_with_review),
            "works_without_review_in_shards": len(no_review),
            "works_without_review_by_group": dict(sorted(Counter(group_of[w.work_id] for w in no_review).items())),
            "works_without_review_ids": sorted(w.work_id for w in no_review),
            "skipped_notes": dict(sorted(skipped.items())),
            "identity_redactions": dict(sorted(redacted.items())),
        },
        "decisions": {
            "distribution": dict(sorted(all_outcomes.items())),
            "by_group": {g: dict(sorted(outcomes_by_group[g].items())) for g in GROUPS},
            "unknown": all_outcomes.get("unknown", 0),
            "reject_ratio": reject_ratio(all_outcomes),
            "reject_ratio_by_group": {g: reject_ratio(outcomes_by_group[g]) for g in GROUPS},
        },
    }


def write_l3(build: L3Build, out_dir: Path, kit_raw_dir: Path, shards: list[ShardInput], *, elapsed_s: float) -> dict[str, Any]:
    """엔티티별 JSONL + corpus_manifest.json(E1-L0와 같은 파일 이름·형식). manifest를 돌려준다."""
    mod = _require_ra()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    names = mod.OUTPUT_FILES
    outputs = {
        names[k]: mod.write_jsonl(out_dir / names[k], getattr(build, k))
        for k in ("works", "reviews", "author_responses", "decisions", "selection")
    }
    kit_raw_dir = Path(kit_raw_dir)
    in_manifest = mod.load_input_manifest(kit_raw_dir)
    pp = kit_raw_dir / mod.PAPERS_FILE
    p_digest = sha256_file(pp)
    p_entry = in_manifest.get(mod.PAPERS_FILE, {})
    inputs = [
        {
            "path": mod.PAPERS_FILE,
            "origin": "kit",
            "bytes": pp.stat().st_size,
            "sha256": p_digest,
            "manifest_sha256_match": (p_entry.get("sha256") == p_digest) if p_entry else None,
            "url": p_entry.get("url"),
            "retrieved_at_utc": mod.file_retrieved_at(kit_raw_dir, mod.PAPERS_FILE, in_manifest).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    ]
    for sh in shards:
        digest = sha256_file(sh.path)
        inputs.append(
            {
                "path": sh.name,
                "shard": sh.index,
                "origin": sh.origin,
                "bytes": sh.path.stat().st_size,
                "sha256": digest,
                "manifest_sha256_match": (sh.expected_sha256 == digest) if sh.expected_sha256 else None,
                "url": sh.url,
                "retrieved_at_utc": sh.retrieved_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    manifest = {
        "task": "E1-L3",
        "source": mod.SOURCE,
        "license": mod.LICENSE,
        "attribution": mod.ATTRIBUTION,
        "generator": "scripts/collect_l3_corpus.py (neumann.sources.corpus_l3 + neumann.sources.researcharcade)",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_s": round(elapsed_s, 2),
        "inputs": inputs,
        "keywords": {
            "sha256": mod.keywords_sha256(),
            "same_as": "E1-L0 neumann.sources.researcharcade.FIELD_KEYWORDS",
            "match_rule": "case-insensitive, word boundary start, trailing * = prefix, space/hyphen interchangeable",
            "text": "title + abstract",
            **mod.keyword_spec(),
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
    _write_json(out_dir / mod.MANIFEST_FILE, manifest)
    return manifest


def collect_l3(
    kit_raw_dir: Path,
    raw_l3_dir: Path,
    out_dir: Path,
    *,
    shards: Iterable[int] = range(N_SHARDS),
    general_ml_n: int = DEFAULT_GENERAL_ML_N,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """조립 한 번: 샤드 확인 → 선별(AI4S + 일반 ML) → 연결 → 검증 → `out_dir`에 쓰기. manifest를 돌려준다."""
    out_dir = Path(out_dir)
    if out_dir.name != L3_SUBDIR:
        # 현재 코퍼스(data/processed)를 덮어쓰지 않게 폴더 이름을 강제한다
        raise ValueError(f"확대 코퍼스 출력 폴더 이름은 {L3_SUBDIR}이어야 한다: {out_dir}")
    t0 = time.perf_counter()
    inputs = resolve_shards(kit_raw_dir, raw_l3_dir, shards)
    build = build_l3(kit_raw_dir, inputs, general_ml_n=general_ml_n, seed=seed)
    return write_l3(build, out_dir, kit_raw_dir, inputs, elapsed_s=time.perf_counter() - t0)


# ── 3. 읽기·검사 ─────────────────────────────────────────────────────────


def resolve_l3_dir(data_dir: str | Path | None = None) -> Path:
    """데이터 루트(`…/data`) 또는 `processed_l3` 폴더 → `processed_l3` 경로."""
    if data_dir is None:
        from neumann.config import get_settings

        data_dir = get_settings().data_dir
    base = Path(data_dir)
    cand = base if base.name == L3_SUBDIR else base / L3_SUBDIR
    if (cand / "works.jsonl").is_file():
        return cand
    raise FileNotFoundError(f"확대 코퍼스가 없다: {cand}. 먼저 `python scripts/collect_l3_corpus.py`")


def load_corpus_l3(data_dir: str | Path | None = None):
    """확대 코퍼스를 E1-L0 `load_corpus`로 읽는다(모든 레코드 모델 재검증). `Corpus`를 돌려준다."""
    from neumann.sources.corpus import load_corpus

    return load_corpus(resolve_l3_dir(data_dir))


def audit_l3(data_dir: str | Path | None = None) -> dict[str, Any]:
    """E1-L0 `audit_processed`(모델 재검증·OpenReview URL·원문 해시·신원 키 0) + 확대 코퍼스 조건:
    편수 ≥ 2,000, 모든 Work에 분야 태그(AI4S slug들 또는 general_ml 하나), 일반 ML은 결정(수락·거절)과
    공식 심사평이 있다. 위반이 하나라도 있으면 ValueError. 통과하면 수치를 돌려준다."""
    from neumann.sources.corpus import audit_processed

    mod = _require_ra()
    d = resolve_l3_dir(data_dir)
    report = audit_processed(d)
    corpus = load_corpus_l3(d)
    problems = []
    if len(corpus.works) < MIN_TOTAL_WORKS:
        problems.append(f"편수 {len(corpus.works)} < {MIN_TOTAL_WORKS}")
    ai4s_fields = set(mod.FIELD_KEYWORDS)
    groups: Counter = Counter()
    for w in corpus.works.values():
        general = w.fields == [GENERAL_ML_FIELD]
        if not general and not (w.fields and set(w.fields) <= ai4s_fields):
            problems.append(f"{w.work_id}: 분야 태그 {w.fields}")
            continue
        groups[GROUP_GENERAL if general else GROUP_AI4S] += 1
        if general:
            dec = corpus.decision_for(w.work_id)
            if dec is None or (dec.outcome not in mod.ACCEPT_OUTCOMES and dec.outcome not in mod.REJECT_OUTCOMES):
                problems.append(f"{w.work_id}: 일반 ML인데 결정(수락·거절)이 없다")
            if not corpus.reviews_for(w.work_id, kind="official_review"):
                problems.append(f"{w.work_id}: 일반 ML인데 공식 심사평이 없다")
    if problems:
        raise ValueError(f"확대 코퍼스 검사 위반 {len(problems)}건: " + " | ".join(problems[:10]))
    urls = sum(1 for w in corpus.works.values() if w.url and w.provenance.source_url)
    report["works_with_source_url"] = urls
    report["source_url_ratio"] = round(urls / len(corpus.works), 4) if corpus.works else None
    return {**report, "works": len(corpus.works), "by_group": dict(sorted(groups.items()))}


_ID_KEYS = {"works.jsonl": "work_id", "reviews.jsonl": "review_id", "author_responses.jsonl": "response_id", "decisions.jsonl": "work_id"}


def _lines_by_id(path: Path, key: str) -> dict[str, tuple[str, str]]:
    """{id: (work_id, 원래 줄)}. 줄 문자열 그대로 비교하려고 다시 직렬화하지 않는다."""
    out: dict[str, tuple[str, str]] = {}
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                out[row[key]] = (row["work_id"], line.rstrip("\n"))
    return out


def compare_with_processed(l3_dir: str | Path, processed_dir: str | Path) -> dict[str, Any]:
    """확대 코퍼스의 AI4S 부분이 현재 코퍼스(E1-L0 `data/processed`)를 담는지 본다(둘 다 읽기만).
    파일별: 현재 레코드 중 확대 코퍼스에 글자 그대로 있는 수, 바뀐 것, 빠진 것, AI4S 논문에 새로 붙은 것."""
    l3_dir, processed_dir = Path(l3_dir), Path(processed_dir)
    out: dict[str, Any] = {"l3_dir": str(l3_dir), "processed_dir": str(processed_dir)}
    mp = processed_dir / "corpus_manifest.json"
    ml = l3_dir / "corpus_manifest.json"
    if mp.is_file() and ml.is_file():
        kp = json.loads(mp.read_text(encoding="utf-8")).get("keywords", {}).get("sha256")
        kl = json.loads(ml.read_text(encoding="utf-8")).get("keywords", {}).get("sha256")
        out["keywords_sha256_same"] = bool(kp) and kp == kl
    base_works = set(_lines_by_id(processed_dir / "works.jsonl", "work_id"))
    for name, key in _ID_KEYS.items():
        old = _lines_by_id(processed_dir / name, key)
        new = _lines_by_id(l3_dir / name, key)
        same = [i for i, (_, line) in old.items() if i in new and new[i][1] == line]
        changed = sorted(i for i, (_, line) in old.items() if i in new and new[i][1] != line)
        missing = sorted(i for i in old if i not in new)
        added_ai4s = sorted(i for i, (wid, _) in new.items() if i not in old and wid in base_works)
        out[name] = {
            "processed": len(old),
            "l3_total": len(new),
            "identical": len(same),
            "changed": len(changed),
            "changed_examples": changed[:5],
            "missing_in_l3": len(missing),
            "missing_examples": missing[:5],
            "added_for_ai4s_works": len(added_ai4s),
        }
    l3_ai4s = {w for w, (_, line) in _lines_by_id(l3_dir / "works.jsonl", "work_id").items() if f'"{GENERAL_ML_FIELD}"' not in line}
    out["ai4s_work_ids_equal_processed"] = l3_ai4s == base_works
    return out


def check_sample(l3_dir: str | Path, shards: list[ShardInput], n: int, seed: int = DEFAULT_SEED) -> list[dict[str, Any]]:
    """무작위 n건(절반은 샤드 2~5에서 온 심사평): 저장된 텍스트를 parquet 원문에서 다시 만들어 대조한다.
    조립 코드와 따로 원문 칸이 저장 텍스트에 글자 그대로 있는지도 본다(신원 가림이 있으면 거짓일 수 있다)."""
    import random

    import pyarrow.parquet as pq

    from neumann.models import ReviewEvent, normalize_text
    from neumann.sources.corpus import iter_jsonl

    mod = _require_ra()
    reviews = sorted(iter_jsonl(resolve_l3_dir(l3_dir) / "reviews.jsonl", ReviewEvent), key=lambda r: r.review_id)
    by_stem = {Path(sh.name).stem: sh for sh in shards}
    new_idx = {sh.index for sh in shards if sh.index not in KIT_SHARDS}

    def shard_of(r: ReviewEvent) -> ShardInput:
        return by_stem[(r.provenance.api_version or "").rsplit("@", 1)[-1]]

    rng = random.Random(seed)
    fresh = [r for r in reviews if shard_of(r).index in new_idx]
    old = [r for r in reviews if shard_of(r).index not in new_idx]
    k_new = min(len(fresh), n // 2 if old else n)
    sample = rng.sample(fresh, k_new) + rng.sample(old, min(len(old), n - k_new))
    wanted: dict[int, dict[str, ReviewEvent]] = defaultdict(dict)
    for r in sample:
        wanted[shard_of(r).index][r.review_id.split(":", 1)[1]] = r
    results = []
    for idx, items in sorted(wanted.items()):
        sh = next(s for s in shards if s.index == idx)
        tab = pq.read_table(sh.path, columns=["review_openreview_id", "content"])
        ids = tab.column("review_openreview_id").to_pylist()
        rows = [i for i, nid in enumerate(ids) if nid in items]
        contents = tab.column("content").take(rows).to_pylist()
        for i, raw in zip(rows, contents):
            rev = items[ids[i]]
            content = json.loads(raw)
            names = mod.OFFICIAL_SECTIONS if rev.kind.value == "official_review" else mod.META_SECTIONS
            rebuilt, _ = mod.clean_text(mod.compose_sections(content, names))
            secs = [str(content[s]).strip() for s in names if content.get(s) is not None and str(content[s]).strip()]
            results.append(
                {
                    "review_id": rev.review_id,
                    "shard": idx,
                    "kind": rev.kind.value,
                    "url": rev.url,
                    "stored_chars": len(rev.text),
                    "stored_equals_rebuilt_from_parquet": rebuilt == rev.text,
                    "provenance_hash_matches_parquet": mod.raw_hash(raw) == rev.provenance.content_sha256,
                    "sections": len(secs),
                    "all_sections_verbatim": all(normalize_text(s) in rev.text for s in secs),
                }
            )
    return sorted(results, key=lambda r: r["review_id"])
