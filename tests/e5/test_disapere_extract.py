"""E5-L1b DISAPERE 지적 추출 예측기: 오프셋, 집계, 튜닝 가드(골드 거부), 재시도·강등 표기, 예측 형식.

기본은 mock provider·직접 지은 문장만 쓴다. 실제 API는 NEUMANN_LIVE_TESTS=1일 때만(맨 아래).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from eval import disapere_extract as dx
from eval.macro_f1 import load_predictions, score
from neumann.llm import LLMCall, LLMResult, MockProvider
from neumann.analyze.mock_responders import default_responders
from neumann.models import sha256_text

URL = "https://example.org/fixture/disapere"


def _row(rid: str, sentences: list[str], role: str = "dev", sep: str = " ", codes=None, n_ann: int = 1) -> dict:
    text = sep.join(sentences)
    return {
        "review_id": rid,
        "role": role,
        "n_annotators": n_ann,
        "risk_codes": codes or [],
        "sentences": sentences,
        "text": text,
        "text_sha256": sha256_text(text),
        "source": {"review_url": f"{URL}/{rid}"},
    }


REVIEWS = [
    _row("rvA", ["The paper proposes a method.", "Baselines are weak and no error bars are reported.",
                 "The code is not available, so results are not reproducible."], codes=["R2", "R5"]),
    _row("rvB", ["Novelty is limited and similar to prior work.", "The paper is well written."], sep="", codes=["R6"]),
    _row("rvC", ["Nice paper.", "Nice paper.", "The claims are not supported by the experiments."], sep="\n", codes=["R1"]),
]


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _docs(tmp_path: Path, rows=REVIEWS) -> list[dx.ReviewDoc]:
    return dx.load_docs(_write(tmp_path / "in.jsonl", rows))


# ── 입력·오프셋 ──────────────────────────────────────────────────────────


def test_excerpts_are_exact_source_slices_including_repeated_sentences(tmp_path):
    for doc in _docs(tmp_path):
        exs = dx.excerpts_for(doc)
        assert [e.text for e in exs] == doc.sentences
        for e in exs:
            assert doc.text[e.start : e.end] == e.text and e.verify_against(doc.text)
            assert e.source_id == doc.review_id
    rvc = dx.excerpts_for(_docs(tmp_path)[2])
    assert rvc[0].start == 0 and rvc[1].start == len("Nice paper.\n")  # 같은 문장이 두 번이면 두 번째 위치


def test_hash_mismatch_is_rejected(tmp_path):
    bad = dict(REVIEWS[0], text_sha256="0" * 64)
    with pytest.raises(ValueError, match="해시"):
        dx.excerpts_for(_docs(tmp_path, [bad])[0])


def test_load_docs_does_not_carry_labels(tmp_path):
    doc = _docs(tmp_path)[0]
    assert not hasattr(doc, "risk_codes") and not hasattr(doc, "sentence_labels")


def test_dev_labels_refuse_gold_rows(tmp_path):
    ok = _write(tmp_path / "dev.jsonl", REVIEWS)
    assert dx.load_dev_labels(ok)["rvA"] == frozenset({"R2", "R5"})
    gold = _write(tmp_path / "gold.jsonl", [REVIEWS[0], _row("g1", ["x."], role="gold", n_ann=2)])
    with pytest.raises(ValueError, match="골드는 튜닝에 쓰지 않는다"):
        dx.load_dev_labels(gold)
    multi = _write(tmp_path / "multi.jsonl", [_row("m1", ["x."], role="dev", n_ann=3)])
    with pytest.raises(ValueError):
        dx.load_dev_labels(multi)


# ── 집계·튜닝 ────────────────────────────────────────────────────────────


def _it(code, pol="negative", conf=0.9, s=0):
    return {"s": s, "start": 0, "end": 1, "code": code, "pol": pol, "conf": conf, "gen": "astra"}


def test_aggregate_filters_polarity_confidence_count_and_drops_r0_r9():
    issues = [_it("R2"), _it("R2", conf=0.4), _it("R5", pol="positive"), _it("R6", pol="neutral", conf=0.95),
              _it("R0"), _it("R9"), _it("R1", conf=0.55)]
    assert dx.aggregate(issues, dx.AggConfig(("negative",), 0.0, 1)) == ["R1", "R2"]
    assert dx.aggregate(issues, dx.AggConfig(("negative",), 0.6, 1)) == ["R2"]
    assert dx.aggregate(issues, dx.AggConfig(("negative",), 0.0, 2)) == ["R2"]
    assert dx.aggregate(issues, dx.AggConfig(("negative",), 0.5, 2)) == []
    assert dx.aggregate(issues, dx.AggConfig(("negative", "neutral"), 0.9, 1)) == ["R2", "R6"]
    assert dx.aggregate([], dx.AggConfig()) == []


def test_grid_is_fixed_and_ordered_simple_first():
    g = dx.grid()
    assert len(g) == 24 and g[0] == dx.AggConfig(("negative",), 0.0, 1)
    assert len(set(g)) == 24


def test_select_config_takes_max_and_breaks_ties_by_grid_order():
    res = [{"config": {"k": i}, "macro_f1": m} for i, m in enumerate([0.3, 0.5, 0.5 + 1e-12, 0.4, None])]
    assert dx.select_config(res)["config"] == {"k": 1}
    with pytest.raises(ValueError):
        dx.select_config([{"config": {}, "macro_f1": None}])


def test_tune_scores_against_dev_labels():
    raw = [
        {"review_id": "a", "issues": [_it("R2", conf=0.9), _it("R6", conf=0.3)]},
        {"review_id": "b", "issues": [_it("R6", conf=0.3)]},
    ]
    labels = {"a": frozenset({"R2"}), "b": frozenset()}
    out = dx.tune(raw, labels)
    assert out["n_configs"] == 24
    # R6은 두 리뷰 모두 FP(신뢰도 0.3) → 하한 0.5 이상이 R6 FP를 없애지만 C*={R2}라 Macro는 R2만 본다: 둘 다 1.0 → 격자 첫 것
    assert out["selected"]["config"] == {"polarities": ["negative"], "min_confidence": 0.0, "min_count": 1}
    assert out["selected"]["macro_f1"] == 1.0
    with pytest.raises(ValueError, match="raw에 없는"):
        dx.score_config(raw[:1], labels, dx.AggConfig())


# ── 추출(mock provider) ──────────────────────────────────────────────────


def _check_raw(rows, docs):
    by_id = {d.review_id: d for d in docs}
    for r in rows:
        exs = dx.excerpts_for(by_id[r["review_id"]])
        for it in r["issues"]:
            ex = exs[it["s"]]
            assert 0 <= it["start"] < it["end"] <= len(ex.text)
            assert it["code"] in {f"R{i}" for i in range(9)}


def test_extract_with_mock_provider_labels_mock_and_keeps_offsets(tmp_path):
    docs = _docs(tmp_path)
    rows, stats = dx.extract_astra(docs, MockProvider(default_responders()), cache_dir=None, parallel=2,
                                   sleep=lambda s: None)
    assert [r["review_id"] for r in rows] == ["rvA", "rvB", "rvC"]
    assert {r["generator"] for r in rows} == {"mock"} and {r["status"] for r in rows} == {"ok"}
    assert stats.llm_requests == 3 and stats.failed_requests == 0 and stats.retry_rounds_used == 0
    codes = {r["review_id"]: dx.aggregate(r["issues"], dx.AggConfig()) for r in rows}
    assert "R2" in codes["rvA"] and "R6" in codes["rvB"]
    _check_raw(rows, docs)


class FlakyProvider:
    """처음 n번은 속도 제한 실패, 그다음은 mock 응답."""

    name = "mock"
    model = "flaky"

    def __init__(self, fail_first: int):
        self.inner = MockProvider(default_responders())
        self.left = fail_first
        self.calls = 0

    def complete_json(self, call: LLMCall) -> LLMResult:
        self.calls += 1
        if self.left > 0:
            self.left -= 1
            return LLMResult(ok=False, data=None, provider="mock", model=self.model, task=call.task,
                             error="api_error", detail="RateLimitError HTTP 429")
        return self.inner.complete_json(call)


def test_failed_batches_are_retried_after_backoff(tmp_path):
    docs = _docs(tmp_path)
    slept: list[float] = []
    prov = FlakyProvider(fail_first=1)
    rows, stats = dx.extract_astra(docs, prov, cache_dir=None, parallel=1, sleep=slept.append)
    assert slept == [dx.RETRY_BACKOFF_S[0]]
    assert stats.retry_rounds_used == 1 and stats.failed_requests == 1
    assert stats.failures_by_reason == {"api_error": 1} and stats.reviews_fallback_final == 0
    assert {r["generator"] for r in rows} == {"mock"}
    assert prov.calls == 4  # 3 + 실패한 1건 재호출


def test_persistent_failure_is_marked_rule_and_degraded(tmp_path):
    docs = _docs(tmp_path)
    slept: list[float] = []
    prov = MockProvider(fail={"extract_issues": "api_error"})
    rows, stats = dx.extract_astra(docs, prov, cache_dir=None, parallel=2, retry_rounds=2, sleep=slept.append)
    assert len(slept) == 2 and stats.retry_rounds_used == 2
    assert all(r["generator"] == "rule" and r["status"] == "degraded" and r["fallback_reasons"] for r in rows)
    assert stats.reviews_fallback_final == 3 and stats.failed_requests == 9
    # 강등돼도 비상 규칙 태그는 남는다(rvA의 R2 등)
    assert any(it["gen"] == "rule" for r in rows for it in r["issues"])
    _check_raw(rows, docs)


def test_rule_extraction_uses_taxonomy_tagger(tmp_path):
    docs = _docs(tmp_path)
    rows, stats, impl = dx.extract_rule(docs)
    assert impl == "neumann.index.taxonomy:tag_excerpts"
    assert {r["generator"] for r in rows} == {"rule"}
    assert stats.sentences == 8
    assert "R2" in dx.aggregate(rows[0]["issues"], dx.AggConfig(("negative", "neutral"), 0.0, 1))
    _check_raw(rows, docs)


# ── 예측 형식·골드 가드 ─────────────────────────────────────────────────


def test_predictions_are_scorable_by_macro_f1(tmp_path):
    docs = _docs(tmp_path)
    rows, _ = dx.extract_astra(docs, MockProvider(default_responders()), cache_dir=None, sleep=lambda s: None)
    pred_path = tmp_path / "pred.jsonl"
    dx.write_jsonl(pred_path, dx.predictions(rows, dx.AggConfig()))
    preds = load_predictions(pred_path)
    assert set(preds) == {"rvA", "rvB", "rvC"} and {p.generator for p in preds.values()} == {"mock"}
    gold = {r["review_id"]: frozenset(r["risk_codes"]) for r in REVIEWS}
    res = score(gold, preds, n_boot=50)
    assert res["n"] == 3 and res["macro_f1"] is not None


def test_predict_refuses_gold_without_frozen_rule_and_with_adhoc_config(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUMANN_DATA_DIR", str(tmp_path))
    raw = tmp_path / "raw.jsonl"
    dx.write_jsonl(raw, [{"review_id": "x", "generator": "astra", "status": "ok", "issues": []}])
    monkeypatch.setitem(dx.FROZEN, "astra", None)
    with pytest.raises(SystemExit, match="FROZEN"):
        dx.main(["predict", "--split", "gold", "--generator", "astra", "--raw", str(raw)])
    cfg = json.dumps({"polarities": ["negative"], "min_confidence": 0.0, "min_count": 1})
    with pytest.raises(SystemExit, match="--config 금지"):
        dx.main(["predict", "--split", "gold", "--generator", "astra", "--raw", str(raw), "--config", cfg])
    out = tmp_path / "p.jsonl"
    assert dx.main(["predict", "--split", "dev", "--generator", "astra", "--raw", str(raw), "--config", cfg,
                    "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["risk_codes"] == []


def test_frozen_rules_are_from_the_pre_fixed_grid():
    grid = {c.as_dict().__repr__() for c in dx.grid()}
    for gen, cfg in dx.FROZEN.items():
        if cfg is not None:
            assert repr(dx.AggConfig.from_dict(cfg).as_dict()) in grid, gen


def test_extractor_fingerprint_changes_with_instructions(monkeypatch):
    from neumann.analyze import extract

    a = dx.extractor_fingerprint()
    monkeypatch.setattr(extract, "INSTRUCTIONS", extract.INSTRUCTIONS + " x")
    assert dx.extractor_fingerprint() != a


# ── 실제 API(NEUMANN_LIVE_TESTS=1일 때만) ───────────────────────────────


@pytest.mark.skipif(os.environ.get("NEUMANN_LIVE_TESTS") != "1", reason="실제 API 테스트는 NEUMANN_LIVE_TESTS=1일 때만")
def test_live_astra_two_reviews(tmp_path):
    from neumann.llm import make_llm

    docs = _docs(tmp_path)[:2]
    rows, stats = dx.extract_astra(docs, make_llm(provider="openai"), cache_dir=None, parallel=2)
    assert stats.llm_requests >= 2
    assert all(r["generator"] in ("astra", "rule") for r in rows)
    _check_raw(rows, docs)
