"""E2-L3: 확대 코퍼스 색인을 새 폴더에(`scripts/build_index_l3.py`)와 전후 비교(`scripts/build_index_compare.py`).

기본 테스트는 가짜 코퍼스·가짜 임베더로 돈다. 공유 데이터 폴더에 실제 `index_l3`가 있으면 그 manifest도 잰다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from neumann.index import search as search_mod
from neumann.index import store as store_mod
from neumann.index.settings import get_index_settings
from neumann.index.store import IndexStore

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


GENERAL_ID = "fake:med-3"  # 가짜 코퍼스에서 이 논문을 "일반 ML"로 둔다


def _l3_corpus(corpus):
    works, reviews = corpus
    works = [w.model_copy(update={"fields": ["general_ml"]}) if w.work_id == GENERAL_ID else w for w in works]
    return works, reviews


def _write_processed(corpus, d: Path, *, manifest: str = "match") -> None:
    works, reviews = corpus
    d.mkdir(parents=True, exist_ok=True)
    (d / "works.jsonl").write_text("".join(w.model_dump_json() + "\n" for w in works), encoding="utf-8")
    (d / "reviews.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in reviews), encoding="utf-8")
    (d / "author_responses.jsonl").write_text("", encoding="utf-8")
    (d / "decisions.jsonl").write_text("", encoding="utf-8")
    if manifest == "none":
        return
    outputs = {n: {"records": 0, "sha256": _sha(d / n)} for n in ("works.jsonl", "reviews.jsonl")}
    if manifest == "mismatch":
        outputs["reviews.jsonl"]["sha256"] = "0" * 64
    cm = {"task": "E1-L3", "generated_at": "2026-09-30T10:00:00Z", "outputs": outputs,
          "selection": {"works": len(works), "by_group": {"ai4science": len(works) - 1, "general_ml": 1}}}
    (d / "corpus_manifest.json").write_text(json.dumps(cm), encoding="utf-8")


# ── 현재 색인을 덮지 않는다 ──

def test_check_out_dir_refuses_current_index(tmp_path):
    l3 = _load_script("build_index_l3")
    cur, src = tmp_path / "index", tmp_path / "processed_l3"
    assert "현재 색인" in l3.check_out_dir(cur, src, [cur])
    assert "현재 색인" in l3.check_out_dir(tmp_path / "x" / ".." / "index", src, [cur])  # 경로 표기가 달라도
    assert "입력" in l3.check_out_dir(src, src, [cur])
    assert l3.check_out_dir(tmp_path / "index_l3", src, [cur]) is None


def test_protected_dirs_include_configured_index(tmp_path, monkeypatch):
    l3 = _load_script("build_index_l3")
    monkeypatch.setenv("NEUMANN_INDEX_DIR", str(tmp_path / "served_index"))
    get_index_settings.cache_clear()
    try:
        dirs = [str(p) for p in l3.protected_dirs()]
    finally:
        monkeypatch.delenv("NEUMANN_INDEX_DIR")
        get_index_settings.cache_clear()
    assert str(tmp_path / "served_index") in dirs
    assert any(d.rstrip("/\\").endswith("index") for d in dirs)


def test_main_refuses_to_write_into_current_index(tmp_path, corpus, monkeypatch):
    l3 = _load_script("build_index_l3")
    src, cur = tmp_path / "processed_l3", tmp_path / "index"
    _write_processed(_l3_corpus(corpus), src)
    cur.mkdir()
    (cur / "manifest.json").write_text('{"keep": true}', encoding="utf-8")
    monkeypatch.setattr(l3, "protected_dirs", lambda: [cur])
    assert l3.main(["--processed", str(src), "--out", str(cur), "--no-embed"]) == 2
    assert (cur / "manifest.json").read_text(encoding="utf-8") == '{"keep": true}'  # 그대로
    assert sorted(p.name for p in cur.iterdir()) == ["manifest.json"]


# ── 빌드 ──

def test_build_l3_no_embed(tmp_path, corpus):
    l3 = _load_script("build_index_l3")
    src, out = tmp_path / "processed_l3", tmp_path / "index_l3"
    _write_processed(_l3_corpus(corpus), src)
    assert l3.main(["--processed", str(src), "--out", str(out), "--no-embed"]) == 0
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["counts"]["works"] == 4 and m["counts"]["reviews"] == 4
    assert m["offset_check"]["rate"] == 1.0 and m["offset_check_reloaded"]["passed"] == m["counts"]["excerpts"]
    assert m["corpus"]["task"] == "E1-L3" and m["corpus"]["sha256_match"] is True
    assert all(v["match"] for v in m["corpus"]["files"].values())
    assert m["groups"]["general_ml"]["works"] == 1 and m["groups"]["ai4science"]["works"] == 3
    assert m["groups"]["general_ml"]["reviews"] == 1  # fake:med-3 심사평 1건
    assert sum(g["excerpts"] for g in m["groups"].values()) == m["counts"]["excerpts"]
    assert m["l3"]["switch"] == f"NEUMANN_INDEX_DIR={out}"
    assert m["backend"]["degraded"] is True  # --no-embed 강등을 숨기지 않는다
    st = IndexStore.load(out)  # 덧붙인 manifest로도 읽힌다
    assert st.verify_offsets()["failed"] == 0 and st.manifest["groups"] == m["groups"]


def test_build_l3_fails_on_corpus_hash_mismatch(tmp_path, corpus):
    l3 = _load_script("build_index_l3")
    src, out = tmp_path / "processed_l3", tmp_path / "index_l3"
    _write_processed(_l3_corpus(corpus), src, manifest="mismatch")
    assert l3.main(["--processed", str(src), "--out", str(out), "--no-embed"]) == 1
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["corpus"]["sha256_match"] is False
    assert m["corpus"]["files"]["reviews.jsonl"]["match"] is False and m["corpus"]["files"]["works.jsonl"]["match"] is True


def test_build_l3_without_corpus_manifest_is_marked(tmp_path, corpus):
    l3 = _load_script("build_index_l3")
    src, out = tmp_path / "processed_l3", tmp_path / "index_l3"
    _write_processed(_l3_corpus(corpus), src, manifest="none")
    assert l3.main(["--processed", str(src), "--out", str(out), "--no-embed"]) == 0
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["corpus"]["sha256_match"] is None and "없음" in m["corpus"]["note"]


def test_oom_detection():
    l3 = _load_script("build_index_l3")
    assert l3._is_oom(RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB"))
    assert not l3._is_oom(RuntimeError("some other failure"))


# ── 전후 비교 ──

@pytest.fixture
def two_indexes(tmp_path, corpus, fake_embedder):
    works, reviews = _l3_corpus(corpus)
    old_w = [w for w in works if w.work_id != GENERAL_ID]
    old_r = [r for r in reviews if r.work_id != GENERAL_ID]
    old_dir, new_dir = tmp_path / "index", tmp_path / "index_l3"
    IndexStore.from_corpus(old_w, old_r, embedder=fake_embedder).save(old_dir)
    IndexStore.from_corpus(works, reviews, embedder=fake_embedder).save(new_dir)
    search_mod.set_query_embedder(fake_embedder)
    yield old_dir, new_dir
    search_mod.set_query_embedder(None)
    store_mod.set_store(None)


def test_compare_script_reports_new_general_ml_work(tmp_path, two_indexes):
    old_dir, new_dir = two_indexes
    plan = tmp_path / "plan_mri.md"
    plan.write_text("# 계획\n\nMRI 종양 분할(segmentation) 모델을 여러 병원 데이터로 평가한다.", encoding="utf-8")
    cmp_ = _load_script("build_index_compare")
    rc = cmp_.main(["--old", str(old_dir), "--new", str(new_dir), "--plan", str(plan), "-k", "3",
                    "--json", str(tmp_path / "c.json"), "--md", str(tmp_path / "c.md"), "--no-negative"])
    assert rc == 0
    rep = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    assert rep["indexes"]["old"]["works"] == 3 and rep["indexes"]["new"]["works"] == 4
    assert rep["indexes"]["new"]["offset_check"]["rate"] == 1.0
    assert rep["corpus_overlap"] == {"old_in_new": 3, "old_only": 0, "new_only": 1}
    c = rep["plans"][0]["compare"]
    top = c["new"][0]
    assert top["work_id"] == GENERAL_ID and top["group"] == "general_ml" and top["in_old_corpus"] is False
    assert top["old_rank"] is None
    assert c["entered_by_group"] == {"general_ml": 1} and c["entered"] == 1
    assert c["overlap"] == 2 and c["dropped"] == 1  # 새 논문 1편이 들어오고 옛 3등이 밀려난다
    assert c["overlap"] + c["entered"] == len(c["new"])
    assert c["same_work_dense_max_abs_diff"] is not None and c["same_work_dense_max_abs_diff"] < 1e-3
    md = (tmp_path / "c.md").read_text(encoding="utf-8")
    assert "새 논문" in md and "일반 ML" in md and "plan_mri" in md


def test_compare_hits_rank_bookkeeping(two_indexes, fake_embedder):
    old_dir, new_dir = two_indexes
    cmp_ = _load_script("build_index_compare")
    old, new = IndexStore.load(old_dir), IndexStore.load(new_dir)
    q = ["graph neural network ionic conductivity electrolyte"]
    ho, hn = search_mod.search(q, k=4, store=old), search_mod.search(q, k=4, store=new)
    c = cmp_.compare_hits(ho, hn, old, new)
    assert c["new"][0]["work_id"] == "fake:bat-1" and c["new"][0]["old_rank"] == 1
    assert c["rank_moves"]["fake:bat-1"] == [1, 1]
    assert [r["rank"] for r in c["new"]] == list(range(1, len(hn) + 1))
    assert c["overlap"] == 3 and c["entered"] == 1  # old에는 3편뿐
    assert c["new_by_group"] == {"ai4science": 3, "general_ml": 1}


# ── 실제 확대 색인(있을 때만) ──

def _real_index_l3() -> Path | None:
    from neumann.config import get_settings

    p = get_settings().data_dir / "index_l3" / "manifest.json"
    return p if p.is_file() else None


@pytest.mark.skipif(_real_index_l3() is None, reason="공유 데이터 폴더에 index_l3가 없다(빌드 전)")
def test_real_index_l3_manifest():
    mpath = _real_index_l3()
    assert mpath is not None
    m = json.loads(mpath.read_text(encoding="utf-8"))
    assert m["format"] == "neumann-index-v1"
    assert m["counts"]["works"] == m["corpus"]["selection"]["works"] >= 2000
    assert m["offset_check"]["failed"] == 0 and m["offset_check"]["rate"] == 1.0
    assert m["offset_check_reloaded"]["checked"] == m["counts"]["excerpts"] and m["offset_check_reloaded"]["failed"] == 0
    assert m["corpus"]["task"] == "E1-L3" and m["corpus"]["sha256_match"] is True
    assert m["groups"]["general_ml"]["works"] == m["corpus"]["selection"]["by_group"]["general_ml"]
    assert m["backend"]["degraded"] is False and m["dense_model"] == "bge-m3"
    assert Path(m["input"]["dir"]).name == "processed_l3"
    # 현재 색인(data/index)은 확대 코퍼스로 덮이지 않았다
    cur = mpath.parent.parent / "index" / "manifest.json"
    if cur.is_file():
        cm = json.loads(cur.read_text(encoding="utf-8"))
        assert Path(cm["input"]["dir"]).name != "processed_l3"
        assert cm["input"]["sha256"] != m["input"]["sha256"]
