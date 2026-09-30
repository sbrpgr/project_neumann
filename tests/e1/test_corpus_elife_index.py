"""E1-L1c: eLife 포함 색인 빌드 스크립트(`scripts/build_index_elife.py`)와 전후 비교 스크립트.

가짜 소스(test_corpus_elife의 작은 코퍼스)로 임베딩 없이 빌드한다. 맨 아래 한 건만 실제 `data/index_elife`를 잰다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from neumann.index.settings import get_index_settings
from tests.e1.test_corpus_elife import _elife_rows, _ra_rows, _read, _write

ROOT = Path(__file__).resolve().parents[2]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bie():
    return _script("build_index_elife")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture()
def processed(tmp_path: Path) -> Path:
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    for name, rows in {**_ra_rows(), **_elife_rows()}.items():
        _write(proc / name, rows)
    # 소스 manifest의 outputs sha256(E1-L0·E1-L1b 형식)
    ra = {n: {"sha256": _sha(proc / n)} for n in ("works.jsonl", "reviews.jsonl")}
    el = {n: {"sha256": _sha(proc / n)} for n in ("elife_works.jsonl", "elife_reviews.jsonl")}
    (proc / "corpus_manifest.json").write_text(json.dumps({"task": "E1-L0", "outputs": ra}), encoding="utf-8")
    (proc / "elife_manifest.json").write_text(json.dumps({"task": "E1-L1b", "outputs": el}), encoding="utf-8")
    return proc


def test_check_out_dir_refuses_protected(bie, tmp_path: Path) -> None:
    data = tmp_path / "data"
    protect = [data / "index", data / "index_l3"]
    proc = data / "processed"
    assert bie.check_out_dir(data / "index", proc, protect)
    assert bie.check_out_dir(Path(str(data / "INDEX_L3") + "/"), proc, protect)  # 표기가 달라도
    assert bie.check_out_dir(proc, proc, protect)
    assert bie.check_out_dir(data / "index_elife", proc, protect) is None


def test_protected_dirs_include_index_l3_and_setting(bie, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEUMANN_INDEX_DIR", str(tmp_path / "custom_idx"))
    get_index_settings.cache_clear()
    try:
        names = [p.name for p in bie.protected_dirs()]
    finally:
        get_index_settings.cache_clear()
    assert names[:2] == ["index", "index_l3"] and "custom_idx" in names


def test_main_refuses_current_index(bie, processed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEUMANN_DATA_DIR", str(processed.parent))
    monkeypatch.delenv("NEUMANN_INDEX_DIR", raising=False)
    from neumann.config import get_settings

    get_settings.cache_clear()
    get_index_settings.cache_clear()
    try:
        for name in ("index", "index_l3"):
            rc = bie.main(["--processed", str(processed), "--out", str(processed.parent / name), "--no-embed"])
            assert rc == 2
            assert not (processed.parent / name).exists()
    finally:
        get_settings.cache_clear()
        get_index_settings.cache_clear()


def test_build_no_embed_merges_sources(bie, processed: Path) -> None:
    out = processed.parent / "index_elife"
    rc = bie.main(["--processed", str(processed), "--out", str(out), "--no-embed"])
    assert rc == 0
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["counts"]["works"] == 4 and m["counts"]["reviews"] == 5
    assert m["offset_check_reloaded"]["rate"] == 1.0
    e = m["elife"]
    assert e["include"] == ["researcharcade", "elife"]
    assert set(e["sources"]) == {"researcharcade", "elife"}
    assert e["sources"]["elife"]["works"] == 2 and e["sources"]["elife"]["reviews"] == 3
    assert e["sources"]["elife"]["excerpts"] == e["sources"]["elife"]["excerpt_offsets_ok"] > 0
    assert e["offset_recheck"]["rate"] == 1.0
    assert e["corpus_hash_check"]["sha256_match"] is True
    assert e["input_audit"]["violations"] == 0 and e["input_audit"]["source_url_ratio"] == 1.0
    assert e["elife_decisions"]["decisions"]["no_binary_decision"] == 1
    assert e["switch"].startswith("NEUMANN_INDEX_DIR=")
    assert set(m["input"]["files"]) == {"works.jsonl", "reviews.jsonl", "elife_works.jsonl", "elife_reviews.jsonl"}
    # eLife 문장 Excerpt의 source_url은 심사평 딥링크(DOI)
    rows = [r for r in _read(out / "excerpts.jsonl") if r["source_id"].startswith("elife:")]
    assert rows and all(r["source_url"].startswith("https://doi.org/10.7554/") for r in rows)


def test_build_fails_on_audit_violation(bie, processed: Path) -> None:
    p = processed / "elife_reviews.jsonl"
    rows = _read(p)
    rows[0]["provenance"]["source_url"] = "https://example.org/x"
    _write(p, rows)
    out = processed.parent / "index_elife"
    assert bie.main(["--processed", str(processed), "--out", str(out), "--no-embed"]) == 1
    assert not out.exists()


def test_build_fails_on_manifest_hash_mismatch(bie, processed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mp = processed / "elife_manifest.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["outputs"]["elife_reviews.jsonl"]["sha256"] = "0" * 64
    mp.write_text(json.dumps(m), encoding="utf-8")
    out = processed.parent / "index_elife"
    assert bie.main(["--processed", str(processed), "--out", str(out), "--no-embed"]) == 1
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    got = manifest["elife"]["corpus_hash_check"]
    assert got["sha256_match"] is False and got["files"]["elife_reviews.jsonl"]["match"] is False
    # 실패한 색인에는 스크립트가 직접 서비스 금지 표시를 남기고, 전환 안내는 찍지 않는다
    marker = out / "DO_NOT_SERVE.txt"
    assert marker.is_file()
    text = marker.read_text(encoding="utf-8")
    assert "elife_reviews.jsonl" in text and "--include researcharcade,elife" in text
    dns = manifest["do_not_serve"]
    assert dns["flag"] is True and "해시" in dns["reason"] and "elife_reviews.jsonl" in dns["reason"]
    assert dns["rebuild_command"].startswith("python scripts/build_index_elife.py")
    printed = capsys.readouterr().out
    assert "전환: NEUMANN_INDEX_DIR" not in printed and "서비스 전환 금지" in printed


def test_build_success_has_no_marker_and_prints_switch(bie, processed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = processed.parent / "index_elife"
    assert bie.main(["--processed", str(processed), "--out", str(out), "--no-embed"]) == 0
    assert not (out / "DO_NOT_SERVE.txt").exists()
    assert "do_not_serve" not in json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert "전환: NEUMANN_INDEX_DIR=" in capsys.readouterr().out


def test_build_marks_on_offset_recheck_failure(bie, processed: Path, monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    real = bie.source_counts

    def broken(index_dir):  # 소스별 재대조에서 한 문장이 원문과 안 맞은 것처럼
        got = real(index_dir)
        got["elife"]["excerpt_offsets_ok"] -= 1
        return got

    monkeypatch.setattr(bie, "source_counts", broken)
    out = processed.parent / "index_elife"
    assert bie.main(["--processed", str(processed), "--out", str(out), "--no-embed"]) == 1
    assert (out / "DO_NOT_SERVE.txt").is_file()
    dns = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["do_not_serve"]
    assert dns["flag"] is True and "오프셋" in dns["reason"]
    assert "전환: NEUMANN_INDEX_DIR" not in capsys.readouterr().out


def test_prior_marker_is_kept_on_successful_rebuild(bie, processed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = processed.parent / "index_elife"
    out.mkdir()
    (out / "DO_NOT_SERVE.txt").write_text("E1-L1b 실명 잔존 FAIL", encoding="utf-8")
    assert bie.main(["--processed", str(processed), "--out", str(out), "--no-embed"]) == 0
    assert (out / "DO_NOT_SERVE.txt").is_file()  # 사람이 원인을 확인한 뒤 손으로 지운다
    dns = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["do_not_serve"]
    assert dns["flag"] is True and "이전" in dns["reason"]
    printed = capsys.readouterr().out
    assert "전환: NEUMANN_INDEX_DIR" not in printed and "손으로 지워야" in printed


def test_compare_marks_elife_hits(processed: Path) -> None:
    """비교 스크립트: eLife 포함 색인에 새로 든 eLife 논문을 '새 논문·eLife'로 잡는지(가짜 두 색인, 어휘 검색)."""
    bie = _script("build_index_elife")
    cmp_mod = _script("build_index_elife_compare")
    old, new = processed.parent / "old", processed.parent / "new"
    assert bie.main(["--processed", str(processed), "--out", str(old), "--no-embed", "--include", "researcharcade"]) == 0
    assert bie.main(["--processed", str(processed), "--out", str(new), "--no-embed"]) == 0
    q = [{"demo": "neuro", "kind": "en", "title": "fmri", "text": "fMRI head motion connectivity analysis"},
         {"demo": "gnn", "kind": "en", "title": "gnn", "text": "GNN paper ablation"}]
    rep = cmp_mod.run(old, new, q, k=3)
    assert rep["old"]["works_by_source"] == {"researcharcade": 2}
    assert rep["new"]["works_by_source"] == {"elife": 2, "researcharcade": 2}
    assert rep["new"]["offset_check"]["rate"] == 1.0
    neuro, gnn = rep["results"]
    assert neuro["new"][0]["source"] == "elife" and neuro["new"][0]["old_rank"] is None
    assert neuro["summary"]["elife_best_rank"] == 1 and neuro["summary"]["entered_by_source"].get("elife", 0) >= 1
    assert neuro["summary"]["top1_new_source"] == "elife"
    assert gnn["new"][0]["source"] == "researcharcade" and gnn["new"][0]["old_rank"] == 1
    assert neuro["backend"]["new"]["backend"] == "lexical_only"  # 임베딩 없는 색인은 강등으로 표시
    md = cmp_mod.to_markdown(rep)
    assert "새 논문" in md and "eLife" in md


# ── 실제 색인(공유 데이터 폴더에 index_elife가 있을 때만) ──

def _real_manifest() -> dict | None:
    d = os.getenv("NEUMANN_DATA_DIR")
    if not d:
        return None
    mp = Path(d) / "index_elife" / "manifest.json"
    return json.loads(mp.read_text(encoding="utf-8")) if mp.is_file() else None


REAL = _real_manifest()


@pytest.mark.skipif(REAL is None, reason="공유 데이터 폴더에 index_elife가 없다")
def test_real_index_elife_manifest() -> None:
    assert REAL is not None
    assert REAL["offset_check"]["rate"] == 1.0 and REAL["offset_check_reloaded"]["rate"] == 1.0
    assert REAL["offset_check_reloaded"]["checked"] == REAL["counts"]["excerpts"]
    e = REAL["elife"]
    assert e["include"] == ["researcharcade", "elife"]
    assert e["offset_recheck"]["rate"] == 1.0
    assert e["sources"]["elife"]["works"] >= 300 and e["sources"]["researcharcade"]["works"] >= 1000
    assert e["corpus_hash_check"]["sha256_match"] is True
    assert e["input_audit"]["violations"] == 0 and e["input_audit"]["identity_key_records"] == 0
    assert e["input_audit"]["source_url_ratio"] == 1.0 and e["input_audit"]["content_sha256_ratio"] == 1.0
    d = e["elife_decisions"]["decisions"]
    assert d["no_binary_decision"] == d["assessment_raw_preserved"]
    assert REAL["backend"]["degraded"] is False and REAL["backend"]["dense"] == "bge-m3"
