"""DISP-1: 리포트 카드의 생성 방식 표시 — 계약 값 astra는 "LLM"으로, 실제 모델명(gpt-6-astra 등)·파일 이름은 그대로."""

from __future__ import annotations

import json
from pathlib import Path

from eval import report_card as rc


def _write(tmp_path: Path, name: str, obj) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _linkage(gens: dict[str, int]) -> dict:
    return {
        "report_schema": "neumann.linkage/1", "checked_at": "2026-09-30T20:00:00+09:00", "input_kind": "dict",
        "verdict": "pass", "links_total": 10, "links_ok": 10, "linkage_rate": 1.0, "cards_total": 10, "cards_ok": 10,
        "card_pass_rate": 1.0, "card_generators": gens,
        "drop": {"available": True, "findings_total": 50, "findings_dropped": 5, "rate": 0.1, "source": "verification",
                 "note": ""},
        "failures": [],
    }


def _macro(gens: dict[str, int]) -> dict:
    return {
        "metric": "review-level multilabel Tier-1 Macro-F1 (04_평가_명세 §2.1)",
        "gold_file": "C:/x/gold.jsonl", "gold_sha256": "a" * 64, "pred_file": "C:/x/pred_llm.jsonl", "n": 148,
        "macro_f1": 0.5, "micro_f1": 0.6, "scored_classes": ["R1"], "excluded_classes": [],
        "macro_f1_ci95": {"low": 0.4, "high": 0.6}, "micro_f1_ci95": {"low": 0.5, "high": 0.7},
        "predictions": {"scored": 148, "missing": 0, "generator_counts": gens},
        "bootstrap": {"n_resamples": 2000, "seed": 1},
    }


def _build(paths: list[Path]) -> str:
    return rc.build(paths, now="2026-09-30T22:00:00+09:00", commit="abc1234", command="python -m eval.report_card")


def test_report_card_shows_llm_not_contract_name(tmp_path) -> None:
    text = _build([
        _write(tmp_path, "link.json", _linkage({"astra": 8, "rule": 2})),
        _write(tmp_path, "macro.json", _macro({"astra": 148})),
        _write(tmp_path, "m.json", {"schema": "neumann.metrics/1", "source": "가짜", "metrics": [
            {"id": "bt_hit_at_3", "system": "neumann", "value": 0.4, "n": 5,
             "conditions": "화면 카드 generator {'astra': 13}", "limits": "astra 카드만"}]}),
    ])
    assert "Neumann (LLM)" in text and "| Neumann (astra) |" not in text
    assert "카드 generator LLM 8 · 비상 규칙 2" in text and "generator LLM 148" in text
    assert "화면 카드 generator {'LLM': 13}" in text and "LLM 카드만" in text  # 입력 문구도 표시에서만 바꾼다
    assert "astra" not in text.lower(), [ln for ln in text.splitlines() if "astra" in ln.lower()]


def test_report_card_keeps_real_model_and_file_names(tmp_path) -> None:
    text = _build([
        _write(tmp_path, "score_astra.json", _macro({"astra": 148})),
        _write(tmp_path, "m.json", {"schema": "neumann.metrics/1", "metrics": [
            {"id": "bt_hit_at_3", "system": "neumann", "value": 0.4, "n": 5, "conditions": "평가 모델 gpt-6-astra"}]}),
    ])
    assert "평가 모델 gpt-6-astra" in text  # 실제 모델명은 그대로(astra 모델로 잰 값이면 그렇게 보여야 한다)
    assert "score_astra.json" in text  # 입력 파일 이름도 그대로
    assert "generator LLM 148" in text


def test_rule_and_mock_rows_are_not_called_llm(tmp_path) -> None:
    text = _build([_write(tmp_path, "rule.json", _linkage({"rule": 10}))])
    row = next(ln for ln in text.splitlines() if ln.startswith("| 근거 연결률 (링크 단위) | Neumann 비상 규칙 |"))
    assert "카드 generator 비상 규칙 10" in row and "LLM 10" not in row
    text = _build([_write(tmp_path, "mock.json", _linkage({"mock": 10}))])
    assert "카드 generator 모의(mock) 10" in text
