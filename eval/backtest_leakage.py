"""누출 제거(04_평가_명세 §0.1·§4.2, 옛 함정 B-10).

대상 논문과 그 심사평을 검색에서 빼는 `exclude_work_ids`를 만든다. 식별자 하나의 완전 일치로 걸면
표기 차이(`tj40W2HAKN` vs `researcharcade_hf:tj40W2HAKN`)로 한 번도 작동하지 않은 적이 있다. 그래서:

규칙(사전 고정, 2026-09-30) — 색인의 논문 w를 대상 t에 대해 제외하는 조건은 아래의 **합집합**:
1. id: 접두어·네임스페이스를 정규화한 id가 같다. 정규화 = OpenReview URL이면 `id=` 값, 아니면 마지막 `:` 뒤,
   앞뒤 공백 제거, casefold. 대상의 work_id·native_id·url에서 나온 키를 모두 쓴다.
2. title: 제목 정규화(NFKC, casefold, 영숫자 외 공백, 공백 압축)가 같다.
3. review: 색인 w의 심사평 본문 해시(NFC, 공백 압축, strip 후 sha256)가 대상의 공식 심사평 해시와 하나라도 같다.
- 결과 `exclude_work_ids`는 **색인이 실제로 쓰는 work_id 문자열**로 돌려준다(E2 `search`는 완전 일치로 거른다).
- 셔플 대조(계획서 j로 돌리고 논문 i의 심사평으로 판정)는 i와 j 둘 다 뺀다.
- 사후 자동 검사: 검색 결과에 대상이 0건(`self_hits`), 근거 인용문이 대상 심사평에 들어 있지 않음(`evidence_leaks`).

실행:
    python -m eval.backtest_leakage                    # 색인 data/index 기준 → data/eval/backtest_exclusions.json
    python -m eval.backtest_leakage --probe-search     # E2 search가 있으면 계획서로 검색해 자기 논문 0건을 실측
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval.backtest_common import (
    data_dir,
    eval_dir,
    load_corpus_view,
    read_json,
    read_jsonl,
    sha256_text,
    utf8_stdio,
    write_json,
)

FORMAT = "neumann-backtest-exclusions-v1"
_OPENREVIEW_ID = re.compile(r"[?&]id=([^&#\s]+)")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_WS = re.compile(r"\s+")


def normalize_work_id(raw: str | None) -> str:
    """접두어·네임스페이스를 떼고 casefold. `researcharcade_hf:AbC` == `AbC` == `https://openreview.net/forum?id=AbC`."""
    if not raw:
        return ""
    s = str(raw).strip()
    m = _OPENREVIEW_ID.search(s)
    if m:
        s = m.group(1)
    elif "://" not in s and ":" in s:
        s = s.rsplit(":", 1)[1]
    return s.strip().casefold()


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title).casefold()
    return _WS.sub(" ", _NON_ALNUM.sub(" ", t)).strip()


def review_hash(text: str | None) -> str:
    t = unicodedata.normalize("NFC", text or "")
    return sha256_text(_WS.sub(" ", t).strip())


@dataclass
class TargetKeys:
    work_id: str
    id_keys: set[str] = field(default_factory=set)
    title_key: str = ""
    review_hashes: set[str] = field(default_factory=set)

    def to_json(self) -> dict[str, Any]:
        return {
            "work_id": self.work_id,
            "id_keys": sorted(self.id_keys),
            "title_key": self.title_key,
            "review_hashes": sorted(self.review_hashes),
        }


def target_keys(work_id: str, *, title: str | None, native_id: str | None = None, url: str | None = None,
                review_texts: Iterable[str] = ()) -> TargetKeys:
    ids = {normalize_work_id(x) for x in (work_id, native_id, url) if x}
    ids.discard("")
    return TargetKeys(work_id, ids, normalize_title(title), {review_hash(t) for t in review_texts if t and t.strip()})


@dataclass
class IndexCatalog:
    """색인(또는 검색 대상 코퍼스)의 논문 목록. work_id는 색인 문자열 그대로."""

    works: dict[str, dict[str, Any]]  # work_id -> {"title", "native_id", "url"}
    review_hashes: dict[str, set[str]]  # work_id -> {review_hash}
    source: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_records(cls, works: Iterable[dict[str, Any]], reviews: Iterable[dict[str, Any]], source: str = "") -> IndexCatalog:
        w = {r["work_id"]: {"title": r.get("title"), "native_id": r.get("native_id"), "url": r.get("url")} for r in works}
        rh: dict[str, set[str]] = {}
        for r in reviews:
            rh.setdefault(r["work_id"], set()).add(review_hash(r.get("text")))
        return cls(w, rh, source)

    @classmethod
    def load(cls, index_dir: Path) -> IndexCatalog:
        index_dir = Path(index_dir)
        cat = cls.from_records(read_jsonl(index_dir / "works.jsonl"), read_jsonl(index_dir / "reviews.jsonl"), str(index_dir))
        mpath = index_dir / "manifest.json"
        cat.manifest = read_json(mpath) if mpath.is_file() else {}
        return cat

    def _id_index(self) -> dict[str, set[str]]:
        idx: dict[str, set[str]] = {}
        for wid, meta in self.works.items():
            for raw in (wid, meta.get("native_id"), meta.get("url")):
                k = normalize_work_id(raw)
                if k:
                    idx.setdefault(k, set()).add(wid)
        return idx

    def _title_index(self) -> dict[str, set[str]]:
        idx: dict[str, set[str]] = {}
        for wid, meta in self.works.items():
            k = normalize_title(meta.get("title"))
            if k:
                idx.setdefault(k, set()).add(wid)
        return idx

    def _hash_index(self) -> dict[str, set[str]]:
        idx: dict[str, set[str]] = {}
        for wid, hs in self.review_hashes.items():
            for h in hs:
                idx.setdefault(h, set()).add(wid)
        return idx


def resolve_exclusions(targets: list[TargetKeys], catalog: IndexCatalog) -> dict[str, dict[str, Any]]:
    """대상마다 {exclude_work_ids(색인 문자열), reasons{색인 wid: [id|title|review]}}."""
    by_id, by_title, by_hash = catalog._id_index(), catalog._title_index(), catalog._hash_index()
    out: dict[str, dict[str, Any]] = {}
    for t in targets:
        reasons: dict[str, set[str]] = {}
        for k in t.id_keys:
            for wid in by_id.get(k, ()):
                reasons.setdefault(wid, set()).add("id")
        if t.title_key:
            for wid in by_title.get(t.title_key, ()):
                reasons.setdefault(wid, set()).add("title")
        for h in t.review_hashes:
            for wid in by_hash.get(h, ()):
                reasons.setdefault(wid, set()).add("review")
        out[t.work_id] = {
            "exclude_work_ids": sorted(reasons),
            "reasons": {wid: sorted(r) for wid, r in sorted(reasons.items())},
        }
    return out


def is_target(work_id: str, t: TargetKeys, catalog: IndexCatalog | None = None) -> bool:
    """검색 결과 한 편이 대상 논문인가(id 정규화·제목·심사평 해시 중 하나라도)."""
    if normalize_work_id(work_id) in t.id_keys:
        return True
    if catalog is not None and work_id in catalog.works:
        if t.title_key and normalize_title(catalog.works[work_id].get("title")) == t.title_key:
            return True
        if t.review_hashes & catalog.review_hashes.get(work_id, set()):
            return True
    return False


def self_hits(hit_work_ids: Iterable[str], t: TargetKeys, catalog: IndexCatalog | None = None) -> list[str]:
    """검색 결과 중 대상 논문(누출). 제외가 작동하면 빈 목록이어야 한다."""
    return [w for w in hit_work_ids if is_target(w, t, catalog)]


def evidence_leaks(excerpt_texts: Iterable[str], target_review_texts: Iterable[str]) -> list[str]:
    """근거 인용문 중 대상 논문의 심사평에 글자 그대로(공백 정규화) 들어 있는 것. 0건이어야 한다."""
    hay = [_WS.sub(" ", unicodedata.normalize("NFC", t)).strip() for t in target_review_texts if t]
    leaks = []
    for ex in excerpt_texts:
        needle = _WS.sub(" ", unicodedata.normalize("NFC", ex or "")).strip()
        if len(needle) >= 20 and any(needle in h for h in hay):
            leaks.append(ex)
    return leaks


def keys_for_sample(sample: dict[str, Any], view: Any) -> dict[str, TargetKeys]:
    keys = {}
    for it in sample["items"]:
        w = view.works[it["work_id"]]
        keys[it["work_id"]] = target_keys(
            w.work_id, title=w.title, native_id=w.native_id, url=w.url,
            review_texts=[r.text for r in view.reviews_for(w.work_id)],
        )
    return keys


def build_exclusions(sample: dict[str, Any], view: Any, catalog: IndexCatalog) -> dict[str, Any]:
    keys = keys_for_sample(sample, view)
    resolved = resolve_exclusions(list(keys.values()), catalog)
    targets = []
    for it in sample["items"]:
        wid = it["work_id"]
        r = resolved[wid]
        targets.append({"work_id": wid, "pos": it["pos"], "keys": keys[wid].to_json(), **r,
                        "missing_in_index": not r["exclude_work_ids"]})
    shuffles = []
    for p in sample["shuffle_pairs"]:
        ex = sorted(set(resolved[p["work_id"]]["exclude_work_ids"]) | set(resolved[p["plan_work_id"]]["exclude_work_ids"]))
        shuffles.append({"work_id": p["work_id"], "plan_work_id": p["plan_work_id"], "exclude_work_ids": ex})
    reason_counts: dict[str, int] = {}
    for t in targets:
        for rs in t["reasons"].values():
            for x in rs:
                reason_counts[x] = reason_counts.get(x, 0) + 1
    m = catalog.manifest
    return {
        "format": FORMAT,
        "sample_list_sha256": sample["list_sha256"],
        "index": {
            "dir": catalog.source,
            "built_at": m.get("built_at"),
            "works": len(catalog.works),
            "input_sha256": (m.get("input") or {}).get("sha256"),
        },
        "rule": "exclude = id(normalized) ∪ title(normalized) ∪ review(sha256 of normalized text); shuffle = i ∪ j",
        "summary": {
            "targets": len(targets),
            "targets_found_in_index": sum(1 for t in targets if not t["missing_in_index"]),
            "excluded_index_works_total": sum(len(t["exclude_work_ids"]) for t in targets),
            "matches_by_reason": reason_counts,
            "targets_with_extra_matches": [t["work_id"] for t in targets if len(t["exclude_work_ids"]) > 1],
        },
        "targets": targets,
        "shuffle": shuffles,
    }


def stale_exclusions(excl: dict[str, Any], catalog: IndexCatalog) -> list[str]:
    """제외 목록 중 지금 색인에 없는 work_id. 색인이 다시 만들어져 id가 바뀌면 E2 완전 일치 필터가 조용히 무시하므로,
    생성 전에 이것이 비어 있어야 한다(아니면 `python -m eval.backtest_leakage`를 다시 돌린다)."""
    ids = {w for t in excl["targets"] for w in t["exclude_work_ids"]}
    ids |= {w for s in excl.get("shuffle", []) for w in s["exclude_work_ids"]}
    missing = sorted(ids - set(catalog.works))
    missing += [f"(대상 {t['work_id']} 제외 목록 비어 있음)" for t in excl["targets"] if not t["exclude_work_ids"]]
    return missing


def probe_search(sample: dict[str, Any], plans: dict[str, str], excl: dict[str, Any], catalog: IndexCatalog,
                 search_fn: Callable[..., list[Any]], k: int = 10) -> dict[str, Any]:
    """계획서로 실제 검색: 제외 없이 자기 논문이 몇 번 나오는지, 제외하면 0인지."""
    keys = {t["work_id"]: TargetKeys(t["work_id"], set(t["keys"]["id_keys"]), t["keys"]["title_key"],
                                     set(t["keys"]["review_hashes"])) for t in excl["targets"]}
    rows = []
    for t in excl["targets"]:
        wid = t["work_id"]
        q = [plans[wid]]
        before = [h.work_id for h in search_fn(q, k=k)]
        after = [h.work_id for h in search_fn(q, k=k, exclude_work_ids=set(t["exclude_work_ids"]))]
        # 옛 함정 재현: 접두어 없는 id 하나만 넣었을 때
        naive = [h.work_id for h in search_fn(q, k=k, exclude_work_ids={wid.rsplit(":", 1)[-1]})]
        rows.append({
            "work_id": wid,
            "self_in_topk_without_exclusion": len(self_hits(before, keys[wid], catalog)),
            "self_rank_without_exclusion": next((i for i, w in enumerate(before, 1) if is_target(w, keys[wid], catalog)), None),
            "self_in_topk_with_exclusion": len(self_hits(after, keys[wid], catalog)),
            "self_in_topk_naive_bare_id": len(self_hits(naive, keys[wid], catalog)),
        })
    return {
        "k": k,
        "n": len(rows),
        "self_hits_without_exclusion": sum(r["self_in_topk_without_exclusion"] for r in rows),
        "self_hits_with_exclusion": sum(r["self_in_topk_with_exclusion"] for r in rows),
        "self_hits_naive_bare_id": sum(r["self_in_topk_naive_bare_id"] for r in rows),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(description="백테스트 누출 제거 목록(exclude_work_ids)과 자기 논문 0건 실측")
    ap.add_argument("--sample", type=Path, default=None)
    ap.add_argument("--plans", type=Path, default=None)
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--index-dir", type=Path, default=None, help="기본 data/index")
    ap.add_argument("--out", type=Path, default=None, help="기본 data/eval/backtest_exclusions.json")
    ap.add_argument("--probe-search", action="store_true", help="neumann.index.search로 자기 논문 0건 실측")
    args = ap.parse_args(argv)

    base = args.data_dir or data_dir()
    sample = read_json(args.sample or eval_dir() / "backtest_sample.json")
    view = load_corpus_view(base)
    catalog = IndexCatalog.load(args.index_dir or base / "index")
    excl = build_exclusions(sample, view, catalog)
    out = args.out or eval_dir() / "backtest_exclusions.json"
    s = excl["summary"]
    print(f"색인 {excl['index']['works']}편({excl['index']['built_at']}) · 대상 {s['targets']}편 중 색인에 있음 {s['targets_found_in_index']}")
    print(f"제외 색인 논문 합계 {s['excluded_index_works_total']} · 사유별 {s['matches_by_reason']}")
    print(f"대상 외 추가 일치(동명·같은 심사평) {s['targets_with_extra_matches']}")

    if args.probe_search:
        try:
            from neumann.index.search import search
        except ImportError as exc:
            print(f"[건너뜀] neumann.index.search 없음(E2 미병합): {exc}")
        else:
            plans_path = args.plans or eval_dir() / "backtest_plans.jsonl"
            plans = {r["work_id"]: r["plan_text"] for r in read_jsonl(plans_path)}
            probe = probe_search(sample, plans, excl, catalog, search)
            from neumann.index.search import last_search_status

            probe["backend"] = last_search_status().get("backend")
            excl["probe_search"] = probe
            print(f"검색 실측(k={probe['k']}, 백엔드 {probe['backend']}, {probe['n']}편): 자기 논문 top-k "
                  f"제외 없음 {probe['self_hits_without_exclusion']} → 제외 {probe['self_hits_with_exclusion']} "
                  f"(접두어 없는 id 하나만: {probe['self_hits_naive_bare_id']})")
    sha = write_json(out, excl)
    print(f"sha256 {sha} → {out}")
    return 0 if not excl.get("probe_search") or excl["probe_search"]["self_hits_with_exclusion"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
