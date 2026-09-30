"""라이브 E2E 요약 → neumann.metrics/1 변환 테스트(E5-L3b). 파일만 읽는다(서버·OpenAI 없음)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import scripts.metrics_from_e2e as mfe
from eval import report_card as rc

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "docs" / "reports" / "E5-L0e2e_live_summary.json"
SAMPLE = ROOT / "docs" / "reports" / "E5-L0e2e_sample_summary.json"
PRODUCT_SYS = "Neumann 제품 기본 모델(gpt-6.1-sol)"


def _plan(links=(10, 10), cards=(3, 3), drop=(1, 643), n_cards=5, failures=None, gens=None):
    rate = links[0] / links[1] if links[1] else None
    drop_txt = f"폐기율 {drop[0]}/{drop[1]} = {drop[0] / drop[1]:.3f} (verification)" if drop else "폐기율 없음"
    return {
        "source": "pipeline", "result_status": "ok", "n_cards": n_cards,
        "generators": gens if gens is not None else {"astra": n_cards}, "stages_not_ok": [],
        "linkage": {
            "summary": f"근거 연결률 {links[0]}/{links[1]} = {rate or 0:.3f} · 카드 통과 {cards[0]}/{cards[1]} = 1.000 · "
                       f"{drop_txt} · 실패 0건 · 판정 {'pass' if links[0] == links[1] else 'fail'}",
            "verdict": "pass" if links[0] == links[1] else "fail", "linkage_rate": rate,
            "links": f"{links[0]}/{links[1]}", "cards": f"{cards[0]}/{cards[1]}",
        },
        "failures": failures if failures is not None else [],
    }


def _summary(**plans):
    body = plans or {"a.md": _plan(), "b.md": _plan(links=(13, 13), cards=(4, 4), drop=(2, 701), n_cards=3)}
    body = {**body, "negative_recipe.md": {"source": "pipeline", "n_cards": 0, "failures": [],
                                           "zero_card_reasons": ["위험카드 0장: 연구계획서가 아니다"]}}
    return {"mode": "live", "base_url": "http://127.0.0.1:8010/", "started_at": "s", "finished_at": "f",
            "health": {"pipeline": {"state": "connected"}}, "plans": body}


def _by(out):
    return {(m["id"], m["system"]): m for m in out["metrics"]}


def test_live_summary_converts_to_counts_from_file():
    """커밋된 라이브 요약을 그대로 변환: 계획서별 개수의 합이 값·detail로 들어간다."""
    out = mfe.convert(json.loads(LIVE.read_text(encoding="utf-8")), model="gpt-6-astra", product_model="gpt-6.1-sol")
    assert out["schema"] == "neumann.metrics/1" and out["model"] == "gpt-6-astra"
    by = _by(out)
    lr = by[("linkage_rate", "neumann")]
    assert (lr["value"], lr["n"]) == (1.0, 43)
    assert lr["detail"].startswith("43/43; plan.md 10/10 · plan_elife_neuro.md 13/13 · plan_medimaging.md 20/20")
    assert "평가 모델 gpt-6-astra" in lr["conditions"]
    assert "generator는 요약에 기록되지 않았다" in lr["limits"]  # 연결 검사 실행은 화면 실행과 다르다
    cp = by[("card_pass_rate", "neumann")]
    assert (cp["value"], cp["n"], cp["detail"].split(";")[0]) == (1.0, 12, "12/12")
    dr = by[("drop_rate", "neumann")]
    assert (dr["value"], dr["n"], dr["detail"].split(";")[0]) == (0.0034, 2033, "7/2033")
    assert by[("e2e_cards", "neumann")]["value"] == 13
    de = by[("demo_e2e", "all")]
    assert (de["value"], de["detail"]) == (3, "3/3")
    assert "ZIP" in de["limits"] and "negative_recipe.md: 카드 0장" in de["conditions"]
    for mid in ("macro_f1", "linkage_rate", "drop_rate", "demo_e2e"):
        row = by[(mid, PRODUCT_SYS)]
        assert row["value"] is None and "측정 전" in row["conditions"]


def test_sample_summary_refused():
    with pytest.raises(mfe.InputError, match="라이브 요약만"):
        mfe.convert(json.loads(SAMPLE.read_text(encoding="utf-8")), model="gpt-6-astra")


@pytest.mark.parametrize(
    "patch, msg",
    [
        (lambda s: s["health"]["pipeline"].update(state="unavailable"), "파이프라인 연결된"),
        (lambda s: s["plans"]["a.md"].update(source="sample"), "파이프라인 결과가 아니다"),
        (lambda s: s["plans"]["a.md"]["linkage"].update(linkage_rate=0.9), "맞지 않는다"),
        (lambda s: s["plans"]["a.md"]["linkage"].update(links="9/10"), "맞지 않는다"),
        (lambda s: s["plans"]["a.md"]["linkage"].update(links="11/10", linkage_rate=1.1), "total보다 크다"),
        (lambda s: s["plans"]["a.md"]["linkage"].update(cards="2/3"), "카드 통과 개수"),
        (lambda s: s["plans"]["a.md"]["linkage"].update(summary="근거 연결률 10/10 · 카드 통과 3/3 · 폐기율 ?"),
         "폐기율을 읽을 수 없다"),
        (lambda s: s["plans"]["a.md"]["linkage"].update(links="열/열"), "형식이 아니다"),
    ],
)
def test_inconsistent_summary_refused(patch, msg):
    s = _summary()
    patch(s)
    with pytest.raises(mfe.InputError, match=msg):
        mfe.convert(s, model="gpt-6-astra")


def test_model_required():
    with pytest.raises(mfe.InputError, match="--model"):
        mfe.convert(_summary(), model=" ")


def test_failed_plan_not_counted_as_demo_and_linkage_shortfall_kept():
    """연결 실패가 있으면 그 개수 그대로(1.0으로 올리지 않음), 시연 수에서도 빠진다."""
    s = _summary(**{"a.md": _plan(links=(9, 10), failures=["근거 연결률 0.9"]), "b.md": _plan()})
    by = _by(mfe.convert(s, model="m"))
    assert by[("linkage_rate", "neumann")]["value"] == 0.95
    assert by[("linkage_rate", "neumann")]["detail"].startswith("19/20")
    assert by[("demo_e2e", "all")]["value"] == 1 and by[("demo_e2e", "all")]["detail"] == "1/2"


def test_ratio_never_rounds_to_perfect_or_zero():
    assert mfe.ratio(19_999, 20_000) == 0.9999
    assert mfe.ratio(1, 100_000) == 1e-05 and mfe.ratio(1, 100_000) > 0
    assert mfe.ratio(7, 2033) == 0.0034 and mfe.ratio(10, 10) == 1.0 and mfe.ratio(0, 5) == 0.0
    with pytest.raises(mfe.InputError):
        mfe.ratio(0, 0)


def test_missing_drop_and_unchecked_plan_are_marked():
    no_link = _plan()
    no_link["linkage"] = {"summary": "검사 안 함: 색인 없음"}
    s = _summary(**{"a.md": _plan(drop=None), "b.md": no_link})
    by = _by(mfe.convert(s, model="m"))
    assert by[("drop_rate", "neumann")]["value"] is None and by[("drop_rate", "neumann")]["detail"] == "폐기율 없음"
    assert "합계에서 빠졌다" in by[("linkage_rate", "neumann")]["limits"]
    assert by[("demo_e2e", "all")]["value"] == 1  # 연결 검사를 안 한 계획서는 통과로 세지 않는다


def test_output_feeds_report_card(tmp_path):
    """변환 결과를 eval.report_card에 넣으면 P2·P6가 채워지고, 제품 모델 행은 '측정 전'이다."""
    p = tmp_path / "e2e.json"
    assert mfe.main(["--summary", str(LIVE), "--model", "gpt-6-astra", "--product-model", "gpt-6.1-sol",
                     "--out", str(p)]) == 0
    md = rc.build([p], now="T", commit="c", command="cmd")
    assert "| P2 | 근거 연결률 (폐기율 병기) | 100% | 1.0 (43/43;" in md
    assert "**달성(폐기율 병기)**" in md
    assert "| P6 | 대표 계획 end-to-end 시연 | 3건 | 3 (3/3) |" in md
    assert f"| 지적 추출 Macro-F1 (리뷰 단위) | {PRODUCT_SYS} | 측정 전 |" in md
    assert "0.0034 (7/2033;" in md


def test_cli_error_exit_code(tmp_path):
    out = tmp_path / "x.json"
    assert mfe.main(["--summary", str(SAMPLE), "--model", "gpt-6-astra", "--out", str(out)]) == 2
    assert not out.exists()
    bad = tmp_path / "bad.json"
    bad.write_text("[1]", encoding="utf-8")
    assert mfe.main(["--summary", str(bad), "--model", "m", "--out", str(out)]) == 2
    s = copy.deepcopy(_summary())
    good = tmp_path / "ok.json"
    good.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    assert mfe.main(["--summary", str(good), "--model", "m", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["source"].startswith("scripts/metrics_from_e2e.py ← ok.json (sha256 ")
