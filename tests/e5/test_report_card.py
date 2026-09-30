"""리포트 카드 생성기 테스트: 가짜 지표가 그대로 옮겨지는지, 없는 지표는 '측정 전'인지, 정직 표기 순서."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import report_card as rc

# 가짜 지표 값: 반올림하면 달라지는 자릿수를 일부러 쓴다(그대로 옮겨지는지 보려고).
FAKE_MACRO = 0.612345
FAKE_MACRO_CI = (0.551234, 0.667891)
FAKE_MICRO = 0.701234
FAKE_HIT = 0.4333
FAKE_HIT_CI = (0.2667, 0.6)
FAKE_P3 = 0.3111
FAKE_P3_CI = (0.2222, 0.4)


def _macro_json(generator: str = "astra", macro: float = FAKE_MACRO, ci=FAKE_MACRO_CI, pred_file="pred_astra.jsonl"):
    return {
        "metric": "review-level multilabel Tier-1 Macro-F1 (04_평가_명세 §2.1)",
        "created_at": "2026-09-30T20:00:00+09:00",
        "gold_file": "C:/x/data/eval/disapere_gold.jsonl",
        "gold_sha256": "a" * 64,
        "pred_file": f"C:/x/data/eval/{pred_file}",
        "pred_sha256": "b" * 64,
        "n": 148,
        "macro_f1": macro,
        "micro_f1": FAKE_MICRO,
        "scored_classes": ["R1", "R2", "R5", "R6", "R7"],
        "excluded_classes": ["R3", "R4", "R8", "R9"],
        "macro_f1_ci95": {"low": ci[0], "high": ci[1], "n_resamples": 2000, "n_defined": 2000, "seed": 20260930},
        "micro_f1_ci95": {"low": 0.65, "high": 0.75, "n_resamples": 2000, "n_defined": 2000, "seed": 20260930},
        "predictions": {"scored": 148, "missing": 0, "generator_counts": {generator: 148}},
        "bootstrap": {"n_resamples": 2000, "seed": 20260930},
    }


def _linkage_json(ok=37, total=40, drop=(5, 60), gens=None):
    d = (
        {"available": True, "findings_total": drop[1], "findings_dropped": drop[0], "rate": drop[0] / drop[1],
         "source": "verification", "note": ""}
        if drop
        else {"available": False, "note": "폐기율 없음"}
    )
    return {
        "report_schema": "neumann.linkage/1",
        "checked_at": "2026-09-30T20:00:00+09:00",
        "input_kind": "dict",
        "verdict": "pass" if ok == total else "fail",
        "links_total": total,
        "links_ok": ok,
        "linkage_rate": ok / total if total else None,
        "cards_total": 10,
        "cards_ok": 9,
        "card_pass_rate": 0.9,
        "card_generators": gens if gens is not None else {"astra": 10},
        "drop": d,
        "failures": [],
    }


def _generic_json(metrics):
    return {"schema": "neumann.metrics/1", "source": "가짜 백테스트", "metrics": metrics}


def _write(tmp_path: Path, name: str, obj) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _build(paths):
    return rc.build(paths, now="2026-09-30T20:00:00+09:00", commit="abc1234", command="python -m eval.report_card")


def _row(text: str, starts: str) -> str:
    rows = [ln for ln in text.splitlines() if ln.startswith(starts)]
    assert len(rows) == 1, f"{starts!r} 행이 {len(rows)}개"
    return rows[0]


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


@pytest.fixture
def fake_inputs(tmp_path):
    return [
        _write(tmp_path, "score_astra.json", _macro_json("astra")),
        _write(tmp_path, "linkage.json", _linkage_json()),
        _write(
            tmp_path,
            "backtest.json",
            _generic_json(
                [
                    {"id": "bt_hit_at_3", "system": "neumann", "value": FAKE_HIT, "n": 30, "ci95": list(FAKE_HIT_CI),
                     "conditions": "판정자 Claude 3명 블라인드 다수결", "limits": "n=30"},
                    {"id": "bt_precision_at_3", "system": "llm_baseline", "value": FAKE_P3, "n": 30,
                     "ci95": {"low": FAKE_P3_CI[0], "high": FAKE_P3_CI[1]}},
                    {"id": "corpus_linked_papers", "system": "all", "value": 1265, "n": None},
                ]
            ),
        ),
    ]


def test_values_copied_verbatim_into_promise_table(fake_inputs):
    text = _build(fake_inputs)
    p1 = _cells(_row(text, "| P1 |"))
    # | # | 약속 | 목표 | 측정값 | 95% 구간 | n | 판정 | 입력 |
    assert p1[3] == str(FAKE_MACRO)
    assert p1[4] == f"[{FAKE_MACRO_CI[0]}, {FAKE_MACRO_CI[1]}]"
    assert p1[5] == "148"
    assert p1[6] == "**미달**"
    assert p1[7] == "score_astra.json"
    p3 = _cells(_row(text, "| P3 |"))
    assert p3[3] == str(FAKE_HIT) and p3[4] == f"[{FAKE_HIT_CI[0]}, {FAKE_HIT_CI[1]}]" and p3[5] == "30"
    assert p3[6] == "**미달**"
    p2 = _cells(_row(text, "| P2 |"))
    assert p2[3] == f"{37 / 40} (37/40)" and p2[5] == "40" and p2[6] == "**미달**"
    p4 = _cells(_row(text, "| P4 |"))
    assert p4[3] == "1265" and p4[6] == "**달성**"


def test_values_copied_verbatim_into_detail_table(fake_inputs):
    text = _build(fake_inputs)
    row = _cells(_row(text, "| 백테스트 적중률 precision@3 (A 비율) | 일반 LLM 기준선 |"))
    assert row[2] == str(FAKE_P3)
    assert row[3] == f"[{FAKE_P3_CI[0]}, {FAKE_P3_CI[1]}]"
    assert row[4] == "30"
    micro = _cells(_row(text, "| 지적 추출 Micro-F1 (리뷰 단위) | Neumann (astra) |"))
    assert micro[2] == str(FAKE_MICRO) and micro[3] == "[0.65, 0.75]" and micro[4] == "148"
    hit = _cells(_row(text, "| 백테스트 Top-3 적중 hit@3 | Neumann (astra) |"))
    assert hit[5] == "판정자 Claude 3명 블라인드 다수결" and hit[6] == "n=30"
    drop = _cells(_row(text, "| 폐기율 (버린 지적 / 전체 지적) | Neumann (astra) |"))
    assert drop[2] == f"{5 / 60} (5/60)" and drop[4] == "60"


def test_missing_metrics_marked_not_measured(fake_inputs):
    text = _build(fake_inputs)
    for key in ("| P5 |", "| P6 |"):
        cells = _cells(_row(text, key))
        assert cells[3] == "측정 전" and cells[4] == "—" and cells[5] == "—" and cells[6] == "**측정 전**"
    for starts in (
        "| 백테스트 오탐률 (C 비율) | Neumann (astra) |",
        "| 백테스트 특이성 (진짜 − 셔플 적중률) | 일반 LLM 기준선 |",
        "| 지적 추출 Macro-F1 (리뷰 단위) | Neumann 비상 규칙 |",
        "| 판정 κ (대표 vs AI 다수결, A 여부 이진) | 전체 |",
    ):
        cells = _cells(_row(text, starts))
        assert cells[2] == "측정 전" and cells[7] == "입력 없음"
    assert "측정 전 2건:** P5 원문 링크, P6 대표 계획 end-to-end 시연" in text


def test_no_inputs_everything_not_measured():
    text = _build([])
    for p in rc.PROMISES:
        assert _cells(_row(text, f"| {p.key} |"))[6] == "**측정 전**"
    assert "목표 미달 0건:** 없음" in text
    assert "측정 전 6건" in text
    assert "Macro-F1 입력이 없어 제외 목록을 적을 수 없다" in text
    # 참조선의 사람 상한은 외부 실측이라 입력 없이도 싣는다. 빈도 기준선은 측정 전.
    assert "| 0.725 | [0.669, 0.772] |" in text
    ref = _cells(_row(text, "| 빈도 기준선(안 읽음, 최빈 3코드) 지적 추출 Macro-F1"))
    assert ref[1] == "측정 전" and ref[4] == "입력 없음"


def test_null_value_in_generic_input_is_not_measured(tmp_path):
    p = _write(tmp_path, "m.json", _generic_json([{"id": "bt_hit_at_3", "system": "neumann", "value": None, "n": 30}]))
    text = _build([p])
    cells = _cells(_row(text, "| P3 |"))
    assert cells[3] == "측정 전" and cells[5] == "—" and cells[6] == "**측정 전**"


def test_reference_lines_come_first_and_shortfalls_before_met(tmp_path):
    paths = [
        _write(tmp_path, "freq.json", _macro_json("baseline", 0.3308, (0.298, 0.3623), "pred_baseline_freq.jsonl")),
        _write(tmp_path, "astra.json", _macro_json("astra", 0.55, (0.5, 0.6))),
        _write(tmp_path, "g.json", _generic_json([
            {"id": "corpus_linked_papers", "system": "all", "value": 400},
            {"id": "demo_e2e", "system": "all", "value": 3},
        ])),
    ]
    text = _build(paths)
    i_ref = text.index("## 1. 참조선")
    i_promise = text.index("## 2. 신청서 약속 대비")
    assert i_ref < i_promise
    ref = text[i_ref:i_promise]
    assert "0.725" in ref and "0.3308" in ref and "[0.298, 0.3623]" in ref
    # 약속 표: 미달(P1) → 측정 전(P2, P3, P5) → 달성(P4, P6)
    order = [ln.split("|")[1].strip() for ln in text[i_promise:].splitlines() if ln.startswith("| P")]
    assert order == ["P1", "P2", "P3", "P5", "P4", "P6"]
    assert "목표 미달 1건:** P1 지적 추출 Macro-F1" in text
    # 미달 목록이 약속 표보다 먼저
    assert text.index("목표 미달 1건") < text.index("| P1 |")


def test_ci_below_target_is_flagged(tmp_path):
    p = _write(tmp_path, "a.json", _macro_json("astra", 0.71, (0.66, 0.76)))
    cells = _cells(_row(_build([p]), "| P1 |"))
    assert cells[6] == "**달성(구간 하한은 목표 아래)**"


def test_excluded_classes_and_footnotes(fake_inputs):
    text = _build(fake_inputs)
    sec = text[text.index("## 4. 골드 없는 클래스"):text.index("## 5. 각주")]
    assert "| Neumann (astra) | R1, R2, R5, R6, R7 | R3, R4, R8, R9 |" in sec
    assert "[주1] R7 매핑 한계" in text and "asp_motivation-impact" in text
    assert "[주2] 신청서 대비 골드 대체" in text and "수동 라벨 100건(2인 교차)" in text
    assert "[주3] 골드 없는 클래스 제외" in text


def test_mock_generator_never_fills_promise(tmp_path):
    paths = [
        _write(tmp_path, "mock.json", _macro_json("mock", 0.99, (0.98, 1.0))),
        _write(tmp_path, "link.json", _linkage_json(10, 10, gens={"mock": 10})),
    ]
    text = _build(paths)
    assert _cells(_row(text, "| P1 |"))[6] == "**측정 전**"
    assert _cells(_row(text, "| P2 |"))[6] == "**측정 전**"
    mock_row = _cells(_row(text, "| 지적 추출 Macro-F1 (리뷰 단위) | mock(테스트용, 성능 아님) |"))
    assert mock_row[2] == "0.99" and "성능 수치가 아니다" in mock_row[6]
    assert "mock generator 입력이 있다" in text


def test_linkage_without_drop_rate_is_marked(tmp_path):
    text = _build([_write(tmp_path, "l.json", _linkage_json(40, 40, drop=None))])
    assert _cells(_row(text, "| P2 |"))[6] == "**달성(폐기율 병기)**"
    drop = _cells(_row(text, "| 폐기율 (버린 지적 / 전체 지적) | Neumann (astra) |"))
    assert drop[2] == "측정 전 (폐기율 없음)"


def test_multiple_linkage_reports_are_summed_and_marked_computed(tmp_path):
    paths = [
        _write(tmp_path, "l1.json", _linkage_json(10, 10, drop=(1, 11))),
        _write(tmp_path, "l2.json", _linkage_json(5, 10, drop=(0, 10))),
    ]
    text = _build(paths)
    row = _cells(_row(text, "| 근거 연결률 (링크 단위) | Neumann (astra) |"))
    assert row[2] == f"{15 / 20} (15/20) 계산" and row[4] == "20"
    drop = _cells(_row(text, "| 폐기율 (버린 지적 / 전체 지적) | Neumann (astra) |"))
    assert drop[2] == f"{1 / 21} (1/21) 계산"


def test_rule_generator_goes_to_emergency_row(tmp_path):
    text = _build([_write(tmp_path, "r.json", _macro_json("rule", 0.4, (0.35, 0.45)))])
    assert _cells(_row(text, "| P1 |"))[6] == "**측정 전**"
    assert _cells(_row(text, "| 지적 추출 Macro-F1 (리뷰 단위) | Neumann 비상 규칙 |"))[2] == "0.4"


@pytest.mark.parametrize(
    "obj, msg",
    [
        ({"schema": "something/else"}, "모르는 형식"),
        (_generic_json([{"id": "bt_hit_at_3", "system": "neumann", "n": 3}]), "value가 없다"),
        (_generic_json([{"id": "bt_hit_at_3", "system": "neumann", "value": "0.5"}]), "숫자가 아니다"),
        (_generic_json([{"id": "bt_hit_at_3", "system": "neumann", "value": 0.5, "ci95": [0.6, 0.4]}]), "low > high"),
        (_generic_json([{"id": "bt_hit_at_3", "system": "neumann", "value": 0.5, "n": -1}]), "0 이상 정수"),
        (_generic_json([{"system": "neumann", "value": 0.5}]), "id가 없다"),
        ([1, 2], "최상위가 객체"),
    ],
)
def test_bad_inputs_rejected(tmp_path, obj, msg):
    p = _write(tmp_path, "bad.json", obj)
    with pytest.raises(rc.InputError, match=msg):
        _build([p])


def test_duplicate_metric_rejected(tmp_path):
    a = _write(tmp_path, "a.json", _macro_json("astra"))
    b = _write(tmp_path, "b.json", _macro_json("astra", 0.5))
    with pytest.raises(rc.InputError, match="두 번 이상"):
        _build([a, b])


def test_old_product_numbers_never_appear(fake_inputs):
    text = _build(fake_inputs) + _build([])
    for old in ("0.238", "0.2379", "0.469", "0.4689", "0.322", "0.3222", "0.840", "0.629", "0.430"):
        assert old not in text


def test_cli_writes_file_and_errors(tmp_path, fake_inputs, capsys):
    out = tmp_path / "sub" / "report_card.md"
    assert rc.main(["--inputs", *map(str, fake_inputs), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Project Neumann — 검증 리포트 카드")
    assert str(FAKE_MACRO) in text
    assert "목표 미달" in capsys.readouterr().out
    bad = _write(tmp_path, "bad.json", {"x": 1})
    assert rc.main(["--inputs", str(bad), "--out", str(tmp_path / "o.md")]) == 2
    assert not (tmp_path / "o.md").exists()
