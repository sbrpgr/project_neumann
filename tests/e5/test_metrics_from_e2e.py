"""라이브 E2E 요약 → neumann.metrics/1 변환 테스트(E5-L3b). 파일만 읽는다(서버·OpenAI 없음)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import scripts.metrics_from_e2e as mfe
from eval import report_card as rc

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "docs" / "reports" / "E5-L0e2e_live_summary.json"
SAMPLE = ROOT / "docs" / "reports" / "E5-L0e2e_sample_summary.json"
PRODUCT_SYS = "Neumann 제품 기본 모델(gpt-6.1-sol)"
REF_SYS = mfe.UNRECORDED_SYSTEM
_RECORDED = object()  # 기본값: 연결 검사 카드 수만큼 astra로 기록


def _plan(links=(10, 10), cards=(3, 3), drop=(1, 643), n_cards=5, failures=None, gens=None, link_gens=_RECORDED):
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
            **({"card_generators": {"astra": cards[1]}} if link_gens is _RECORDED
               else {} if link_gens is None else {"card_generators": link_gens}),
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
    """커밋된 라이브 요약을 그대로 변환: 계획서별 개수의 합이 값·detail로 들어간다.
    연결 검사 실행의 generator가 기록되지 않아 연결 지표는 참고 행으로 간다(neumann 행 없음 → P2 측정 전)."""
    out = mfe.convert(json.loads(LIVE.read_text(encoding="utf-8")), model="gpt-6-astra", product_model="gpt-6.1-sol")
    assert out["schema"] == "neumann.metrics/1" and out["model"] == "gpt-6-astra"
    by = _by(out)
    for mid in ("linkage_rate", "card_pass_rate", "drop_rate"):
        assert (mid, "neumann") not in by
    lr = by[("linkage_rate", REF_SYS)]
    assert (lr["value"], lr["n"]) == (1.0, 43)
    assert lr["detail"].startswith("43/43; plan.md 10/10 · plan_elife_neuro.md 13/13 · plan_medimaging.md 20/20")
    assert "평가 모델 gpt-6-astra(모델은 명령행 값(요약에 기록 없음))" in lr["conditions"]
    assert "generator가 요약에 없다" in lr["limits"] and "약속 P2 판정에 쓰지 않는" in lr["limits"]
    assert lr["detail"].endswith("검사 실행 카드 generator 미기록")  # 약속 표(P2) 칸에도 보이게
    cp = by[("card_pass_rate", REF_SYS)]
    assert (cp["value"], cp["n"], cp["detail"].split(";")[0]) == (1.0, 12, "12/12")
    dr = by[("drop_rate", REF_SYS)]
    assert (dr["value"], dr["n"], dr["detail"].split(";")[0]) == (0.0034, 2033, "7/2033")
    assert dr["limits"].startswith("연결 검사 실행의 카드 generator가 요약에 없다")
    assert by[("e2e_cards", "neumann")]["value"] == 13
    assert ("demo_e2e", "all") not in by  # 시연도 같은 규칙(PM 결정): 약속 P6 칸을 채우지 않는다
    de = by[("demo_e2e", REF_SYS)]
    assert (de["value"], de["detail"]) == (3, "3/3; generator 미기록 실행")
    assert de["limits"].startswith("generator 미기록 실행:") and "약속 P6 판정에" in de["limits"]
    assert "ZIP" in de["limits"] and "negative_recipe.md: 카드 0장" in de["conditions"]
    for mid in ("macro_f1", "linkage_rate", "drop_rate", "demo_e2e"):
        row = by[(mid, PRODUCT_SYS)]
        assert row["value"] is None and "측정 전" in row["conditions"]
    assert not any("model" in m for m in out["metrics"])  # 요약에 모델 기록이 없다 → 카드 '모델' 칸은 "(모델 기록 없음)"


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


def test_model_checked_against_recorded_llm_model():
    """요약에 models.llm_model이 있으면(E5-L1e2e 이후) --model과 대조: 다르면 거부, 같으면 일치 표기."""
    s = _summary()
    for e in s["plans"].values():
        if "linkage" in e:
            e["models"] = {"llm_model": "gpt-6.1-sol"}
    with pytest.raises(mfe.InputError, match="models.llm_model과 다르다"):
        mfe.convert(s, model="gpt-6-astra")
    ok = _by(mfe.convert(s, model="gpt-6.1-sol"))
    assert "평가 모델 gpt-6.1-sol(요약 models.llm_model 2/2건과 일치)" in ok[("linkage_rate", "neumann")]["conditions"]
    del s["plans"]["b.md"]["models"]
    part = _by(mfe.convert(s, model="gpt-6.1-sol"))
    assert "1/2건과 일치, 나머지는 명령행 값" in part[("demo_e2e", "all")]["conditions"]


def test_summary_before_linkage_card_generators_stays_reference():
    """task/E5-L1e2e에 커밋된 라이브 요약(949d628 판) 모양: models.llm_model은 있지만 linkage.card_generators가 없다.
    그러면 모델은 대조되고 P2·P6는 참고 행으로 남는다. 2423834 이후 코드로 새 라이브 요약을 만들어야 채워진다."""
    s = _summary(**{"a.md": _plan(link_gens=None), "b.md": _plan(link_gens=None)})
    for e in s["plans"].values():
        if "linkage" in e:
            e["models"] = {"llm_model": "gpt-6.1-sol", "view_model_id": "gpt-6.1-sol"}
            e["card_generators"] = {"astra:gpt-6.1-sol": 3}  # 계획서 단위 "generator:model" 키는 읽지 않는다
    by = _by(mfe.convert(s, model="gpt-6.1-sol"))
    assert ("linkage_rate", "neumann") not in by and ("demo_e2e", "all") not in by
    assert by[("demo_e2e", REF_SYS)]["detail"].endswith("generator 미기록 실행")


def test_new_e5_l1e2e_summary_shape_fills_p2_p6_with_recorded_model(tmp_path):
    """2423834 이후 모양(linkage.card_generators 평문 키 "astra" + models.llm_model·view_model_id)이면
    P2·P6가 채워지고 카드 '모델' 칸에 요약에 기록된 모델이 들어간다."""
    s = _summary(**{n: _plan() for n in ("a.md", "b.md", "c.md")})
    for e in s["plans"].values():
        if "linkage" in e:
            e["models"] = {"llm_model": "gpt-6.1-sol", "view_model_id": "gpt-6.1-sol"}
    out = mfe.convert(s, model="gpt-6.1-sol")
    by = _by(out)
    for key in (("linkage_rate", "neumann"), ("drop_rate", "neumann"), ("demo_e2e", "all"), ("e2e_cards", "neumann")):
        assert by[key]["model"] == "gpt-6.1-sol"
    p = tmp_path / "m.json"
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    md = rc.build([p], now="T", commit="c", command="x")
    for key in ("| P2 |", "| P6 |"):
        cells = [c.strip() for c in next(ln for ln in md.splitlines() if ln.startswith(key)).strip().strip("|").split("|")]
        assert cells[6].startswith("**달성") and cells[8] == "gpt-6.1-sol"


def test_recorded_view_model_mismatch_refused():
    s = _summary()
    for e in s["plans"].values():
        if "linkage" in e:
            e["models"] = {"llm_model": "gpt-6.1-sol", "view_model_id": "gpt-6-astra"}
    with pytest.raises(mfe.InputError, match="view_model_id"):
        mfe.convert(s, model="gpt-6.1-sol")


def test_demo_model_needs_both_runs_recorded():
    """결과 manifest 모델만 있고 화면 실행 모델이 없으면: 연결 지표 행만 모델, 시연·화면 카드 수 행은 기록 없음."""
    s = _summary()
    for e in s["plans"].values():
        if "linkage" in e:
            e["models"] = {"llm_model": "gpt-6.1-sol"}
    by = _by(mfe.convert(s, model="gpt-6.1-sol"))
    assert by[("linkage_rate", "neumann")]["model"] == "gpt-6.1-sol"
    assert "model" not in by[("demo_e2e", "all")] and "model" not in by[("e2e_cards", "neumann")]


def test_partial_model_record_leaves_row_without_model():
    s = _summary()
    s["plans"]["a.md"]["models"] = {"llm_model": "gpt-6.1-sol", "view_model_id": "gpt-6.1-sol"}
    by = _by(mfe.convert(s, model="gpt-6.1-sol"))
    assert "model" not in by[("linkage_rate", "neumann")] and "model" not in by[("demo_e2e", "all")]


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


def test_plan_failing_other_checks_not_counted_as_demo():
    """근거 연결은 완전해도 다른 검사(브라우저·결과 상태)가 실패한 계획서는 시연 통과로 세지 않는다."""
    s = _summary(**{"a.md": _plan(failures=["콘솔 오류 1건"]), "b.md": _plan(), "c.md": _plan()})
    s["plans"]["c.md"]["result_status"] = "degraded"
    by = _by(mfe.convert(s, model="m"))
    assert (by[("demo_e2e", "all")]["value"], by[("demo_e2e", "all")]["detail"]) == (1, "1/3")
    assert by[("linkage_rate", "neumann")]["value"] == 1.0  # 연결률 자체는 개수 그대로


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
    """변환 결과를 eval.report_card에 넣으면: generator 미기록 실행의 연결 지표와 시연 수는 P2·P6를 채우지 않고
    (측정 전) 참고 행으로만 가고, 제품 모델 행은 '측정 전', e2e_cards는 이름표가 붙는다."""
    p = tmp_path / "e2e.json"
    assert mfe.main(["--summary", str(LIVE), "--model", "gpt-6-astra", "--product-model", "gpt-6.1-sol",
                     "--out", str(p)]) == 0
    md = rc.build([p], now="T", commit="c", command="cmd")
    assert "| P2 | 근거 연결률 (폐기율 병기) | 100% | 측정 전 | — | — | **측정 전** | — |" in md
    assert "달성(폐기율 병기)" not in md
    assert f"| 근거 연결률 (링크 단위) | {REF_SYS} | 1.0 (43/43;" in md
    assert "| 근거 연결률 (링크 단위) | Neumann (astra) | 측정 전 | — | — | — | — | 입력 없음 |" in md
    assert f"| 폐기율 (버린 지적 / 전체 지적) | {REF_SYS} | 0.0034 (7/2033;" in md
    assert "| P6 | 대표 계획 end-to-end 시연 | 3건 | 측정 전 | — | — | **측정 전** | — |" in md
    assert f"| 대표 계획 end-to-end 시연 | {REF_SYS} | 3 (3/3; generator 미기록 실행) |" in md
    assert "**달성" not in md
    assert f"| 지적 추출 Macro-F1 (리뷰 단위) | {PRODUCT_SYS} | 측정 전 |" in md
    assert "| 라이브 E2E 화면 위험카드 수 (데모 계획서 합) | Neumann (astra) | 13 (" in md
    assert "(기타)" not in md


@pytest.mark.parametrize(
    "link_gens, system, note, p2, p6",
    [
        ({"astra": 3}, "neumann", "검사 실행 카드 generator {'astra': 9}", "**달성(폐기율 병기)**", "**달성**"),
        ({"astra": 2, "rule": 1}, "neumann", "비상 규칙 카드 3/9장 포함", "**달성(폐기율 병기)**", "**달성**"),
        ({"rule": 3}, "neumann_rule", "비상 규칙 카드 9/9장", "**측정 전**", "**달성**"),
        ({"astra": 3, "other": 1}, "mixed", "검사 실행 카드 generator", "**측정 전**", "**달성**"),
        ({}, REF_SYS, "검사 실행 카드 generator 미기록", "**측정 전**", "**측정 전**"),
    ],
)
def test_recorded_card_generators_decide_linkage_system(link_gens, system, note, p2, p6, tmp_path):
    """generator가 기록된 라이브 결과(v1 이후)는 eval.report_card의 연결 보고서 규칙대로 시스템을 나눈다.
    시연(P6)은 generator가 기록됐으면 채우고, 미기록이면 P2와 같이 측정 전이다."""
    s = _summary(**{n: _plan(link_gens=link_gens) for n in ("a.md", "b.md", "c.md")})
    out = mfe.convert(s, model="gpt-6.1-sol")
    lr = _by(out)[("linkage_rate", system)]
    assert note in lr["detail"] and lr["value"] == 1.0
    p = tmp_path / "m.json"
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    md = rc.build([p], now="T", commit="c", command="x").splitlines()
    assert p2 in next(ln for ln in md if ln.startswith("| P2 |"))
    assert p6 in next(ln for ln in md if ln.startswith("| P6 |"))


def test_generator_model_keys_accepted_and_model_checked():
    """tests/e2e card_generators() 형식("generator:model")도 받는다. 모델이 --model과 다르면 멈춘다."""
    s = _summary(**{n: _plan(link_gens={"astra:gpt-6.1-sol": 2, "rule:-": 1}) for n in ("a.md", "b.md", "c.md")})
    by = _by(mfe.convert(s, model="gpt-6.1-sol"))
    assert "비상 규칙 카드 3/9장 포함" in by[("linkage_rate", "neumann")]["detail"]
    assert by[("demo_e2e", "all")]["value"] == 3
    with pytest.raises(mfe.InputError, match="카드 모델"):
        mfe.convert(s, model="gpt-6-astra")


def test_mock_or_malformed_card_generators_refused():
    for bad, msg in (({"astra": 2, "mock": 1}, "mock"), ({"astra:m": 2, "mock:-": 1}, "mock"),
                     ({"astra": -1}, "0 이상 정수"), (["astra"], "0 이상 정수")):
        s = _summary(**{"a.md": _plan(link_gens=bad)})
        with pytest.raises(mfe.InputError, match=msg):
            mfe.convert(s, model="m")


def test_one_plan_without_generators_makes_all_linkage_reference():
    """한 계획서라도 기록이 없으면 합계 전체를 참고 행으로 둔다(부분만 약속 칸에 넣지 않는다)."""
    s = _summary(**{"a.md": _plan(), "b.md": _plan(link_gens=None)})
    by = _by(mfe.convert(s, model="m"))
    assert ("linkage_rate", "neumann") not in by and "(b.md)" in by[("linkage_rate", REF_SYS)]["limits"]
    assert ("demo_e2e", "all") not in by and by[("demo_e2e", REF_SYS)]["value"] == 2


def _macro_with_pred(tmp_path, models):
    """예측 파일(행별 model)과 그 sha256을 가진 Macro-F1 결과 JSON."""
    pred = tmp_path / "pred_astra_gold.jsonl"
    pred.write_text("".join(json.dumps({"review_id": f"r{i}", "generator": "astra", "model": m}) + chr(10)
                            for i, m in enumerate(models)), encoding="utf-8")
    macro = {
        "metric": "review-level multilabel Tier-1 Macro-F1", "n": 148, "macro_f1": 0.4864, "micro_f1": 0.5644,
        "macro_f1_ci95": {"low": 0.4276, "high": 0.5394}, "micro_f1_ci95": {"low": 0.5125, "high": 0.612},
        "predictions": {"generator_counts": {"astra": 148}}, "scored_classes": [], "excluded_classes": [],
        "pred_file": str(pred), "pred_sha256": hashlib.sha256(pred.read_bytes()).hexdigest(),
    }
    f = tmp_path / "score_astra.json"
    f.write_text(json.dumps(macro), encoding="utf-8")
    return f, pred


def _cells_of(md, starts):
    row = next(ln for ln in md.splitlines() if ln.startswith(starts))
    return [c.strip() for c in row.strip().strip("|").split("|")]


def test_model_column_from_each_input_record(tmp_path):
    """모델 칸은 행마다 자기 입력의 기록: P1은 예측 파일의 model(gpt-6-astra), 백테스트 행은 행의 model(gpt-6.1-sol).
    기록 없는 행은 "(모델 기록 없음)", 측정 전 행은 비운다."""
    f, _ = _macro_with_pred(tmp_path, ["gpt-6-astra"] * 3)
    g = tmp_path / "bt.json"
    g.write_text(json.dumps({"schema": "neumann.metrics/1", "metrics": [
        {"id": "bt_hit_at_3", "system": "neumann", "value": 0.4, "n": 5, "model": "gpt-6.1-sol"},
        {"id": "bt_hit_at_3", "system": "llm_baseline", "value": 0.2, "n": 5},
        {"id": "bt_precision_at_3", "system": "neumann", "value": None, "model": "gpt-6.1-sol"},
    ]}), encoding="utf-8")
    md = rc.build([f, g], now="T", commit="c", command="x")
    assert _cells_of(md, "| P1 |")[3] == "0.4864" and _cells_of(md, "| P1 |")[8] == "gpt-6-astra"
    assert _cells_of(md, "| P3 |")[3] == "0.4" and _cells_of(md, "| P3 |")[8] == "gpt-6.1-sol"
    assert _cells_of(md, "| P4 |")[8] == "—"  # 측정 전
    assert _cells_of(md, "| 백테스트 Top-3 적중 hit@3 | 일반 LLM 기준선 |")[8] == "(모델 기록 없음)"
    assert _cells_of(md, "| 백테스트 적중률 precision@3 (A 비율) | Neumann (astra) |")[8] == "—"  # null 값
    assert _cells_of(md, "| 지적 추출 Macro-F1 (리뷰 단위) | Neumann (astra) |")[8] == "gpt-6-astra"
    assert "| 판정 일치율 (대표 10편 vs AI 다수결, A/B/C) | 전체 | 측정 전 | — | — | — | — | 입력 없음 | — |" in md
    assert "--eval-model" not in md


def test_model_column_partial_record_and_mismatch_stop(tmp_path):
    f, pred = _macro_with_pred(tmp_path, ["gpt-6-astra", None])
    md = rc.build([f], now="T", commit="c", command="x")
    assert _cells_of(md, "| P1 |")[8] == "gpt-6-astra (기록 없음 1/2행)"
    pred.write_text(pred.read_text(encoding="utf-8") + chr(10), encoding="utf-8")  # 채점 뒤 바뀐 예측 파일
    with pytest.raises(rc.InputError, match="채점 때와 다르다"):
        rc.build([f], now="T", commit="c", command="x")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "neumann.metrics/1", "metrics": [
        {"id": "bt_hit_at_3", "system": "neumann", "value": 0.4, "model": 7}]}), encoding="utf-8")
    with pytest.raises(rc.InputError, match="model"):
        rc.build([bad], now="T", commit="c", command="x")


def test_eval_model_option_removed(tmp_path):
    with pytest.raises(SystemExit):
        rc.main(["--inputs", "--out", str(tmp_path / "x.md"), "--eval-model", "gpt-6-astra"])


def test_report_card_backtest_limit_and_label():
    """PM 결정(E5-L3b 전달): 카드 한계 문구는 백테스트 n=5, e2e_cards 이름표."""
    md = rc.build([], now="T", commit="c", command="x")
    assert "백테스트는 n=5(대표 결정, 비용 사유; real 대 기준선, 셔플 없음, sol)" in md
    assert "n=30" not in md
    assert rc.METRIC_LABELS["e2e_cards"] == ("라이브 E2E 화면 위험카드 수 (데모 계획서 합)", "count")


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
    assert b"\r\n" not in out.read_bytes()  # LF 고정: 체크아웃 파일과 sha256이 같아야 한다


def test_committed_metrics_file_matches_converter():
    """커밋된 변환 결과(리포트 카드 입력)가 지금 변환기 출력과 바이트 단위로 같다."""
    committed = ROOT / "docs" / "reports" / "E5-L3b_metrics_e2e.json"
    raw = LIVE.read_bytes()
    out = mfe.convert(json.loads(raw.decode("utf-8")), model="gpt-6-astra", product_model="gpt-6.1-sol",
                      summary_name=LIVE.name, summary_sha256=hashlib.sha256(raw).hexdigest())
    assert committed.read_bytes() == (json.dumps(out, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
