from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from neumann.index.store import IndexStore

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _write_corpus(corpus, d: Path) -> None:
    works, reviews = corpus
    d.mkdir(parents=True, exist_ok=True)
    (d / "works.jsonl").write_text("".join(w.model_dump_json() + "\n" for w in works), encoding="utf-8")
    (d / "reviews.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in reviews), encoding="utf-8")


def test_build_script_jsonl_no_embed(tmp_path, corpus):
    src, out = tmp_path / "processed", tmp_path / "index"
    _write_corpus(corpus, src)
    build = _load_script("build_index")
    rc = build.main(["--source", "jsonl", "--processed", str(src), "--out", str(out), "--no-embed"])
    assert rc == 0
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["format"] == "neumann-index-v1"
    assert m["counts"]["works"] == 4 and m["counts"]["reviews"] == 4
    assert m["counts"]["excerpts"] > 10
    assert m["offset_check"]["failed"] == 0 and m["offset_check"]["rate"] == 1.0
    assert m["offset_check_reloaded"]["passed"] == m["counts"]["excerpts"]
    assert m["counts"]["tag_kinds"] >= 2
    assert m["backend"]["degraded"] is True and m["backend"]["dense"] is None  # 강등을 숨기지 않는다
    assert len(m["input"]["sha256"]) == 64 and set(m["input"]["files"]) == {"works.jsonl", "reviews.jsonl"}
    assert m["build_seconds"] >= 0 and "sentences_s" in m["stages"]
    assert m["index_bytes"] > 0
    assert not (out / "embeddings.npy").exists()
    st = IndexStore.load(out)
    assert st.n_excerpts() == m["counts"]["excerpts"]


def test_build_script_default_processed_source(tmp_path, corpus):
    """기본 입력(load_corpus). E1 코드가 없으면 jsonl 직접 읽기로 대신하고 manifest에 그 사실을 남긴다."""
    src, out = tmp_path / "processed", tmp_path / "index"
    _write_corpus(corpus, src)
    (src / "author_responses.jsonl").write_text("", encoding="utf-8")
    (src / "decisions.jsonl").write_text("", encoding="utf-8")
    build = _load_script("build_index")
    assert build.main(["--processed", str(src), "--out", str(out), "--no-embed"]) == 0
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    if importlib.util.find_spec("neumann.sources.corpus") is None:
        assert m["input"]["source"] == "jsonl" and "load_corpus" in m["input"]["fallback"]
    else:
        assert m["input"]["source"] == "processed" and "fallback" not in m["input"]
    assert m["counts"]["works"] == 4 and m["offset_check"]["failed"] == 0


def test_corpus_adapter_accepts_e1_shape(corpus):
    from dataclasses import dataclass

    works, reviews = corpus

    @dataclass
    class FakeCorpus:  # E1 Corpus 모양: works는 dict, reviews는 list
        works: dict
        reviews: list

    build = _load_script("build_index")
    w, r = build._parts(FakeCorpus({x.work_id: x for x in works}, reviews))
    assert w == works and r == reviews
    with pytest.raises(TypeError):
        build._parts(FakeCorpus({"a": "not a work"}, reviews))


def test_build_is_deterministic(tmp_path, corpus):
    src = tmp_path / "processed"
    _write_corpus(corpus, src)
    build = _load_script("build_index")
    for name in ("a", "b"):
        assert build.main(["--source", "jsonl", "--processed", str(src), "--out", str(tmp_path / name), "--no-embed"]) == 0
    for fname in ("excerpts.jsonl", "tags.jsonl", "bm25.json", "works.jsonl", "reviews.jsonl"):
        assert (tmp_path / "a" / fname).read_bytes() == (tmp_path / "b" / fname).read_bytes(), fname


def test_check_script_runs(tmp_path, corpus, fake_embedder, capsys):
    from neumann.index import search as search_mod
    from neumann.index import store as store_mod

    st = IndexStore.from_corpus(*corpus, embedder=fake_embedder)
    st.save(tmp_path)
    search_mod.set_query_embedder(fake_embedder)
    try:
        check = _load_script("build_index_check")
        rc = check.main(["--index", str(tmp_path), "-q", "ionic conductivity electrolyte", "-k", "2", "--json", str(tmp_path / "r.json")])
    finally:
        search_mod.set_query_embedder(None)
        store_mod.set_store(None)
    assert rc == 0
    rep = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert rep["offset_check"]["failed"] == 0
    assert rep["queries"][0]["hits"][0]["work_id"] == "fake:bat-1"


FIXTURE_LOADER = ROOT / "tests" / "fixtures" / "loader.py"


@pytest.mark.skipif(not FIXTURE_LOADER.is_file(), reason="공용 fixture(E0b)가 아직 없다")
def test_shared_fixtures_index():
    from tests.fixtures.loader import load_fixtures

    fx = load_fixtures()
    st = IndexStore.from_corpus(fx.works, fx.reviews)
    res = st.verify_offsets()
    assert res["checked"] > 0 and res["failed"] == 0
    kinds = {row["risk_code"] for _w, row in st.iter_tag_rows()}
    assert len(kinds) >= 2
    for w in fx.works:
        assert st.get_work(w.work_id) == w


@pytest.mark.skipif(os.getenv("NEUMANN_E2_MODEL_TESTS") != "1", reason="실제 bge-m3 검사는 NEUMANN_E2_MODEL_TESTS=1")
def test_bge_m3_cross_lingual():
    from neumann.index.embed import get_embedder

    emb = get_embedder()
    docs = [
        "A graph neural network predicts the ionic conductivity of lithium battery electrolytes.",
        "A U-Net segments brain tumors in MRI scans.",
        "Cooking recipe for kimchi stew with pork and tofu.",
    ]
    q = emb.encode(["리튬 배터리 전해액의 이온전도도를 예측하는 그래프 신경망"])
    d = emb.encode(docs)
    sims = (q @ d.T)[0]
    assert emb.dim == 1024
    assert int(sims.argmax()) == 0 and sims[0] > sims[1] + 0.1
