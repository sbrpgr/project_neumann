"""DISAPERE 골드 구성(§3.1)과 빈도 기준선 테스트. 합성 zip(직접 지은 문장)으로 돈다.
실제 원본 검사(골드 148건)는 NEUMANN_RAW_DIR에 DISAPERE.zip이 있을 때만 돈다."""

from __future__ import annotations

import json
import os
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from eval import baseline_freq, disapere_gold as dg
from eval import macro_f1 as mf
from neumann.sources import disapere


def _sent(i, aspect, polarity):
    return {
        "review_id": "X",
        "sentence_index": i,
        "text": f"Synthetic sentence {i}.",
        "suffix": " ",
        "review_action": "arg_evaluative",
        "fine_review_action": "none",
        "aspect": aspect,
        "polarity": polarity,
    }


def _doc(review_id, annotator, labels):
    sents = [_sent(i, a, p) for i, (a, p) in enumerate(labels)]
    for s in sents:
        s["review_id"] = review_id
    return {
        "metadata": {
            "forum_id": f"F_{review_id}",
            "review_id": review_id,
            "rebuttal_id": "R",
            "title": "t",
            "reviewer": "AnonReviewer1",
            "rating": 3,
            "conference": "ICLR2020",
            "permalink": "https://openreview.net/forum?id=x",
            "annotator": annotator,
        },
        "review_sentences": sents,
        "rebuttal_sentences": [],
    }


NEG, POS, NONE = "pol_negative", "pol_positive", "none"
N_SENT = 4


def _labels(**by_index):
    """문장 N_SENT개. 지정 안 한 문장은 (none, none)."""
    out = [("none", NONE)] * N_SENT
    for k, v in by_index.items():
        out[int(k[1:])] = v
    return out


def _ann(codes_by_sentence: dict[int, tuple[str, str]]):
    return _labels(**{f"s{i}": v for i, v in codes_by_sentence.items()})


def _make_zip(path: Path, reviews: dict[str, list[list[tuple[str, str]]]]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for rid, anns in reviews.items():
            for k, labels in enumerate(anns):
                subset = "final_dataset" if k == 0 else "extra_annotations"
                name = f"{rid}.json" if k == 0 else f"{rid}.anno{k + 10}.json"
                zf.writestr(f"DISAPERE/{subset}/test/{name}", json.dumps(_doc(rid, f"anno{k + 1}", labels)))
    return path


def _review(tmp_path, anns) -> disapere.Review:
    z = _make_zip(tmp_path / "d.zip", {"Rev": anns})
    (r,) = disapere.load_reviews(z)
    return r


def test_mapping_and_polarity_filter(tmp_path):
    r = _review(tmp_path, [_ann({
        0: ("asp_soundness-correctness", NEG),   # R1
        1: ("asp_substance", POS),               # 긍정 → 제외
        2: ("asp_clarity", NEG),                 # clarity → Tier-1 채점 제외
        3: ("asp_meaningful-comparison", NEG),   # R6
    })])
    assert dg.annotator_codes(r.annotations[0]) == {"R1", "R6"}


def test_originality_and_comparison_union_to_r6(tmp_path):
    r = _review(tmp_path, [_ann({0: ("asp_originality", NEG), 1: ("asp_meaningful-comparison", NEG),
                                 2: ("asp_replicability", NEG), 3: ("asp_motivation-impact", NEG)})])
    assert dg.annotator_codes(r.annotations[0]) == {"R5", "R6", "R7"}


def test_non_negative_polarity_never_counts(tmp_path):
    r = _review(tmp_path, [_ann({0: ("asp_substance", NONE), 1: ("arg_other", NEG), 2: ("none", NEG)})])
    assert dg.annotator_codes(r.annotations[0]) == frozenset()


def test_mapping_is_the_prefixed_table():
    assert dg.ASPECT_TO_TIER1 == {
        "asp_soundness-correctness": "R1",
        "asp_substance": "R2",
        "asp_replicability": "R5",
        "asp_originality": "R6",
        "asp_meaningful-comparison": "R6",
        "asp_motivation-impact": "R7",
    }
    assert "asp_clarity" not in dg.ASPECT_TO_TIER1
    assert set(dg.UNCOVERED) == {"R3", "R4", "R8", "R9"}


@pytest.mark.parametrize("n, k", [(1, 1), (2, 2), (3, 2), (4, 3), (5, 3)])
def test_majority_threshold(n, k):
    assert dg.majority_threshold(n) == k


def test_majority_gold_two_annotators_needs_both():
    m = dg.majority_gold([frozenset({"R1", "R2"}), frozenset({"R2"})])
    assert m["risk_codes"] == ["R2"] and m["threshold"] == 2
    assert m["disagreement_codes"] == ["R1"] and m["resolution"] == "majority_vote"


def test_majority_gold_three_and_four():
    three = dg.majority_gold([frozenset({"R1"}), frozenset({"R1", "R6"}), frozenset({"R6", "R2"})])
    assert three["risk_codes"] == ["R1", "R6"] and three["votes"] == {"R1": 2, "R2": 1, "R6": 2}
    four = dg.majority_gold([frozenset({"R1"}), frozenset({"R1"}), frozenset({"R1", "R2"}), frozenset({"R2"})])
    assert four["risk_codes"] == ["R1"] and four["threshold"] == 3  # R2는 2/4 → 과반 아님


def test_majority_gold_agreed_and_empty():
    same = dg.majority_gold([frozenset({"R5"}), frozenset({"R5"})])
    assert same["resolution"] == "agreed" and same["disagreement_codes"] == []
    empty = dg.majority_gold([frozenset(), frozenset({"R2"})])
    assert empty["risk_codes"] == []  # no_risk 골드도 남긴다


def test_build_splits_gold_and_dev_and_writes_manifest(tmp_path):
    z = _make_zip(tmp_path / "d.zip", {
        "G2": [_ann({0: ("asp_substance", NEG)}), _ann({0: ("asp_substance", NEG), 1: ("asp_originality", NEG)})],
        "G3": [_ann({0: ("asp_replicability", NEG)}), _ann({}), _ann({1: ("asp_replicability", NEG)})],
        "D1": [_ann({2: ("asp_soundness-correctness", NEG)})],
        "D2": [_ann({})],
    })
    info = disapere.zip_info(z)
    gold, dev = dg.build(disapere.load_reviews(z), info)
    assert [g["review_id"] for g in gold] == ["G2", "G3"]
    assert [d["review_id"] for d in dev] == ["D1", "D2"]
    g2, g3 = gold
    assert g2["risk_codes"] == ["R2"] and g2["annotator_codes"] == [["R2"], ["R2", "R6"]]
    assert g3["risk_codes"] == ["R5"] and g3["n_annotators"] == 3 and g3["threshold"] == 2
    assert dev[0]["risk_codes"] == ["R1"] and dev[1]["no_risk"] is True
    assert dev[0]["sentence_labels"][2] == {"aspect": "asp_soundness-correctness", "polarity": NEG, "tier1": "R1"}
    for rec in gold + dev:
        src = rec["source"]
        assert src["url"] == disapere.DATASET_URL and src["zip_sha256"] == info.sha256
        assert src["retrieved_at"] and src["review_url"].startswith("https://openreview.net/forum?id=")
        assert all(len(m["sha256"]) == 64 for m in src["members"])
        assert "reviewer" not in json.dumps(rec)
        assert "".join(s + " " for s in rec["sentences"]) == rec["text"]
    # 골드 파일에는 문장별 라벨을 두지 않는다(채점 전용)
    assert "sentence_labels" not in g2

    out = tmp_path / "out"
    man = dg.write_outputs(gold, dev, info, out, disapere.count_members(z))
    assert man["files"][dg.GOLD_FILE]["n"] == 2 and man["files"][dg.DEV_FILE]["n"] == 2
    for name, f in man["files"].items():
        data = (out / name).read_bytes()
        assert disapere.sha256_bytes(data) == f["sha256"]
    assert json.loads((out / dg.MANIFEST_FILE).read_text(encoding="utf-8"))["counts"]["gold"] == 2
    # 채점기가 골드 파일을 그대로 읽는다
    assert mf.load_gold(out / dg.GOLD_FILE) == {"G2": frozenset({"R2"}), "G3": frozenset({"R5"})}


def test_gold_jsonl_is_deterministic(tmp_path):
    z = _make_zip(tmp_path / "d.zip", {"G": [_ann({0: ("asp_substance", NEG)}), _ann({})]})
    info = disapere.zip_info(z)
    a = dg.write_outputs(*dg.build(disapere.load_reviews(z), info), info, tmp_path / "a", 2)
    b = dg.write_outputs(*dg.build(disapere.load_reviews(z), info), info, tmp_path / "b", 2)
    assert a["files"] == b["files"]


def test_frequency_baseline_uses_dev_only(tmp_path):
    dev = [
        {"review_id": "d1", "risk_codes": ["R2", "R1"]},
        {"review_id": "d2", "risk_codes": ["R2", "R6"]},
        {"review_id": "d3", "risk_codes": ["R2", "R5"]},
        {"review_id": "d4", "risk_codes": ["R1", "R6"]},
    ]
    freq = baseline_freq.code_frequency(dev)
    assert freq == Counter({"R2": 3, "R1": 2, "R6": 2, "R5": 1})
    assert baseline_freq.top_k(freq, 3) == ["R1", "R2", "R6"]
    # 동률은 코드 이름순
    assert baseline_freq.top_k(Counter({"R6": 2, "R1": 2, "R5": 2}), 2) == ["R1", "R5"]

    dev_path = tmp_path / "dev.jsonl"
    dev_path.write_text("".join(json.dumps(r) + "\n" for r in dev), encoding="utf-8")
    # 대상 파일에 라벨이 없어도 돈다(review_id만 읽는다)
    target = tmp_path / "target.jsonl"
    target.write_text("".join(json.dumps({"review_id": r}) + "\n" for r in ("g1", "g2")), encoding="utf-8")
    out = tmp_path / "pred.jsonl"
    assert baseline_freq.main(["--dev", str(dev_path), "--target", str(target), "--out", str(out)]) == 0
    preds = mf.load_predictions(out)
    assert set(preds) == {"g1", "g2"}
    assert all(p.codes == {"R1", "R2", "R6"} and p.generator == "baseline" for p in preds.values())


def _real_zip() -> Path | None:
    raw = os.environ.get("NEUMANN_RAW_DIR")
    if not raw:
        return None
    p = Path(raw) / disapere.ZIP_RELPATH
    return p if p.is_file() else None


@pytest.mark.skipif(_real_zip() is None, reason="DISAPERE.zip 원본 없음(NEUMANN_RAW_DIR)")
def test_real_gold_is_148_and_disjoint_from_dev():
    z = _real_zip()
    gold, dev = dg.build(disapere.load_reviews(z), disapere.zip_info(z))
    assert len(gold) == 148 and len(dev) == 358
    assert not {g["review_id"] for g in gold} & {d["review_id"] for d in dev}
    assert all(g["n_annotators"] >= 2 for g in gold)
    # DISAPERE에 대응 라벨이 없는 클래스는 골드 support 0
    assert not {c for g in gold for c in g["risk_codes"]} & set(dg.UNCOVERED)
