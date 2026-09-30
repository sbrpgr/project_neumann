"""E5-L0 근거 연결 검사기 자체 검사.

검사기가 실제로 조작을 잡는지 확인한다(항상 통과하는 검사 금지):
조작 인용 주입 → 연결률 < 1.0, 오프셋 0 발췌 통과, 해시만 틀림 → 실패, URL 빔 → 실패,
폐기율 없는 결과 → "폐기율 없음" 명시, 카드 0장 → 1.0이 아니라 "정의 안 됨".
공용 fixture가 없어도 돌도록 models로 작은 결과를 직접 만든다.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval.linkage import NO_DROP_NOTE, REASONS, check_result, load_sources, main
from neumann.models import (
    Excerpt,
    Generator,
    PremortemResult,
    RiskCard,
    RiskScore,
    StageStatus,
    WhyApplies,
    sha256_text,
)

ROOT = Path(__file__).resolve().parents[2]

SOURCES = {
    "rev_a": "The baselines are weak. Only a single seed is reported, so the gains may be noise.",
    "rev_b": "Test molecules overlap with training scaffolds. This is a clear data leakage risk.",
}
URLS = {
    "rev_a": "https://openreview.net/forum?id=FAKE01&noteId=revA",
    "rev_b": "https://openreview.net/forum?id=FAKE02&noteId=revB",
}


def ex(source_id: str, start: int, end: int) -> Excerpt:
    return Excerpt.from_source(
        SOURCES[source_id], start, end, source_kind="review", source_id=source_id, source_url=URLS[source_id]
    )


def card(card_id: str, evidence: list[Excerpt], code: str = "R2") -> RiskCard:
    return RiskCard(
        card_id=card_id,
        risk_code=code,
        title=f"fake card {card_id}",
        why_applies=WhyApplies(text="plan reports a single run", plan_lines=[2]),
        evidence=[e.excerpt_id for e in evidence],
        score=RiskScore(similarity=0.7, frequency=0.5, severity=0.6, confidence=0.9, total=0.5),
        generator=Generator.mock,
    )


E_ZERO = ex("rev_a", 0, 23)  # "The baselines are weak." — 오프셋 0
E_TAIL = ex("rev_a", 24, len(SOURCES["rev_a"]))  # 원문 끝까지
E_LEAK = ex("rev_b", 0, 47)


def make_result(*, with_drop: bool = True, cards: list[RiskCard] | None = None, evidence=None) -> PremortemResult:
    return PremortemResult(
        session_id="sess_fake",
        plan_id="plan_fake",
        evidence=[E_ZERO, E_TAIL, E_LEAK] if evidence is None else evidence,
        risk_cards=[card("card_1", [E_ZERO, E_TAIL]), card("card_2", [E_LEAK, E_ZERO], "R3")]
        if cards is None
        else cards,
        verification={"findings_total": 20, "findings_dropped": 3} if with_drop else {},
    )


def as_dict(result: PremortemResult) -> dict:
    return result.model_dump(mode="json")


def evidence_entry(data: dict, excerpt_id: str) -> dict:
    return next(e for e in data["evidence"] if e["excerpt_id"] == excerpt_id)


# ── 정상 결과 ─────────────────────────────────────────────────────────────


def test_fixture_texts_are_what_the_tests_assume() -> None:
    assert E_ZERO.start == 0 and E_ZERO.text == "The baselines are weak."
    assert E_TAIL.end == len(SOURCES["rev_a"])
    assert E_LEAK.text == "Test molecules overlap with training scaffolds."


def test_clean_result_passes_with_drop_rate() -> None:
    rep = check_result(make_result(), SOURCES)
    assert rep.verdict == "pass" and rep.passed
    assert (rep.links_ok, rep.links_total, rep.linkage_rate) == (4, 4, 1.0)
    assert (rep.cards_ok, rep.cards_total, rep.card_pass_rate) == (2, 2, 1.0)
    assert (rep.excerpts_ok, rep.excerpts_total) == (3, 3)
    assert rep.failures == [] and rep.reason_counts == {}
    assert rep.drop.available and rep.drop.rate == pytest.approx(0.15) and rep.drop.source == "verification"
    assert rep.source_hash_unchecked == 0 and rep.card_generators == {"mock": 2}
    assert "폐기율 3/20 = 0.150" in rep.summary()


def test_offset_zero_excerpt_passes_not_falsy() -> None:
    """start=0은 정상값이다. `if not start`로 검사하면 이 카드가 실패로 잘못 집계된다."""
    res = make_result(cards=[card("only_zero", [E_ZERO])], evidence=[E_ZERO])
    for inp in (res, as_dict(res)):
        rep = check_result(inp, SOURCES)
        assert rep.verdict == "pass", rep.failures
        assert rep.linkage_rate == 1.0
    assert as_dict(res)["evidence"][0]["start"] == 0


def test_dict_and_model_inputs_agree() -> None:
    res = make_result()
    a, b = check_result(res, SOURCES), check_result(as_dict(res), SOURCES)
    assert a.input_kind == "model" and b.input_kind == "dict"
    assert b.contract_valid is True
    keys = ("verdict", "links_total", "links_ok", "cards_ok", "excerpts_ok", "failures", "drop")
    assert {k: getattr(a, k) for k in keys} == {k: getattr(b, k) for k in keys}


def test_lookup_forms_mapping_callable_object() -> None:
    res = make_result()
    assert check_result(res, lambda sid: SOURCES[sid]).passed  # KeyError 안 나는 경로
    assert check_result(res, lambda sid: SimpleNamespace(text=SOURCES[sid])).passed  # ReviewEvent처럼 .text
    assert check_result(res, {k: {"text": v} for k, v in SOURCES.items()}).passed


# ── 조작 주입: 연결률이 1.0 아래로 떨어져야 한다 ─────────────────────────


def test_injected_fabricated_quote_lowers_rate_below_one() -> None:
    """인용문을 바꿔치고 해시까지 맞춘 경우: 모델 생성자는 통과하지만 원문 대조에서 잡힌다."""
    fake = "The baselines are good."  # 같은 길이(23자), 원문에 없는 문장
    assert len(fake) == E_ZERO.end - E_ZERO.start and fake not in SOURCES["rev_a"]
    forged = Excerpt(  # 계약 검증을 통과하는 거짓 발췌
        excerpt_id=E_ZERO.excerpt_id,
        source_kind="review",
        source_id="rev_a",
        start=0,
        end=len(fake),
        text=fake,
        text_sha256=sha256_text(fake),
        source_url=URLS["rev_a"],
        source_sha256=sha256_text(SOURCES["rev_a"]),
    )
    res = make_result(evidence=[forged, E_TAIL, E_LEAK])
    rep = check_result(res, SOURCES)
    assert rep.linkage_rate is not None and rep.linkage_rate < 1.0
    assert (rep.links_ok, rep.links_total) == (2, 4)  # E_ZERO를 인용한 링크 2개가 모두 실패
    assert rep.verdict == "fail" and not rep.passed
    assert rep.cards_ok == 0 and rep.card_pass_rate == 0.0
    assert {(f.card_id, f.excerpt_id) for f in rep.failures} == {
        ("card_1", E_ZERO.excerpt_id),
        ("card_2", E_ZERO.excerpt_id),
    }
    assert all(f.reasons == ["text_mismatch"] for f in rep.failures)
    assert rep.reason_counts == {"text_mismatch": 2}


def test_injected_quote_in_json_single_link() -> None:
    """JSON에서 인용 1건만 조작(해시 재계산) → 그 링크만 실패, 연결률 3/4."""
    data = as_dict(make_result())
    e = evidence_entry(data, E_LEAK.excerpt_id)
    e["text"] = "Test molecules overlap with training compounds."  # 같은 길이, 원문에 없는 말
    assert len(e["text"]) == e["end"] - e["start"]
    e["text_sha256"] = sha256_text(e["text"])
    rep = check_result(data, SOURCES)
    assert (rep.links_ok, rep.links_total, rep.linkage_rate) == (3, 4, 0.75)
    assert [(f.card_id, f.excerpt_id, f.reasons) for f in rep.failures] == [
        ("card_2", E_LEAK.excerpt_id, ["text_mismatch"])
    ]
    assert (rep.cards_ok, rep.card_pass_rate) == (1, 0.5)


def test_shifted_offsets_fail() -> None:
    data = as_dict(make_result())
    e = evidence_entry(data, E_TAIL.excerpt_id)
    e["start"] -= 1
    e["end"] -= 1
    rep = check_result(data, SOURCES)
    assert rep.linkage_rate == 0.75
    assert rep.failures[0].reasons == ["text_mismatch"]
    assert rep.contract_valid is True  # 계약은 통과하는 조작 — 원문 대조만 잡는다


def test_text_hash_only_wrong_fails_dict_and_model() -> None:
    data = as_dict(make_result())
    evidence_entry(data, E_TAIL.excerpt_id)["text_sha256"] = "0" * 64
    rep = check_result(data, SOURCES)
    assert rep.verdict == "fail" and rep.linkage_rate == 0.75
    assert rep.failures[0].reasons == ["text_hash_mismatch"]
    assert rep.contract_valid is False and any("계약" in n for n in rep.notes)

    bad = Excerpt.model_construct(**{**E_TAIL.model_dump(), "text_sha256": "f" * 64})  # 생성자 검증 우회
    res = PremortemResult.model_construct(
        session_id="s", plan_id="p", evidence=[E_ZERO, bad, E_LEAK], risk_cards=make_result().risk_cards
    )
    rep2 = check_result(res, SOURCES)
    assert rep2.input_kind == "model" and rep2.failures[0].reasons == ["text_hash_mismatch"]
    assert rep2.linkage_rate == 0.75


def test_source_hash_only_wrong_fails() -> None:
    data = as_dict(make_result())
    evidence_entry(data, E_LEAK.excerpt_id)["source_sha256"] = "a" * 64
    rep = check_result(data, SOURCES)
    assert rep.failures[0].reasons == ["source_hash_mismatch"] and rep.linkage_rate == 0.75


def test_changed_source_text_fails() -> None:
    """원문이 저장 뒤 바뀌었으면(같은 구간 글자는 같아도) 원문 해시로 잡는다."""
    changed = dict(SOURCES, rev_b=SOURCES["rev_b"] + " Extra sentence.")
    rep = check_result(make_result(), changed)
    assert rep.failures[0].reasons == ["source_hash_mismatch"]
    assert rep.linkage_rate == 0.75


@pytest.mark.parametrize("url", ["", "   ", None])
def test_empty_url_fails(url) -> None:
    data = as_dict(make_result())
    evidence_entry(data, E_ZERO.excerpt_id)["source_url"] = url
    rep = check_result(data, SOURCES)
    assert rep.verdict == "fail" and rep.linkage_rate == 0.5  # E_ZERO를 인용한 링크 2개
    assert all(f.reasons == ["source_url_missing"] for f in rep.failures)


def test_non_http_url_fails() -> None:
    data = as_dict(make_result())
    evidence_entry(data, E_LEAK.excerpt_id)["source_url"] = "file:///C:/secret.txt"
    rep = check_result(data, SOURCES)
    assert rep.failures[0].reasons == ["source_url_invalid"]


def test_missing_sources_fail_not_pass() -> None:
    res = make_result()
    for lookup in ({}, None, lambda sid: None, lambda sid: {}[sid]):
        rep = check_result(res, lookup)
        assert rep.linkage_rate == 0.0 and rep.verdict == "fail"
        assert set(rep.reason_counts) == {"source_not_found"}

    def boom(sid: str) -> str:
        raise RuntimeError("store down")

    rep = check_result(res, boom)
    assert rep.reason_counts == {"source_lookup_error": 4}


def test_out_of_range_and_bad_offsets() -> None:
    data = as_dict(make_result())
    e = evidence_entry(data, E_TAIL.excerpt_id)
    def tail_reasons(rep) -> list[str]:
        return next(f for f in rep.failures if f.excerpt_id == E_TAIL.excerpt_id).reasons

    short = dict(SOURCES, rev_a=SOURCES["rev_a"][:40])
    assert "offset_out_of_range" in tail_reasons(check_result(data, short))

    e["start"] = None
    assert "offset_missing" in tail_reasons(check_result(data, SOURCES))
    e["start"], e["end"] = 10, 5
    assert "offset_invalid" in tail_reasons(check_result(data, SOURCES))
    e["start"], e["end"] = 24.0, float(len(SOURCES["rev_a"]))  # 정수가 아닌 오프셋
    assert "offset_invalid" in tail_reasons(check_result(data, SOURCES))


def test_dangling_and_duplicate_excerpt_ids_and_empty_card() -> None:
    data = as_dict(make_result())
    data["evidence"] = [e for e in data["evidence"] if e["excerpt_id"] != E_LEAK.excerpt_id]
    rep = check_result(data, SOURCES)
    assert rep.failures[0].reasons == ["excerpt_missing"] and rep.linkage_rate == 0.75

    data = as_dict(make_result())
    dup = copy.deepcopy(evidence_entry(data, E_TAIL.excerpt_id))
    dup["text"] = dup["text"].upper()
    dup["text_sha256"] = sha256_text(dup["text"])
    data["evidence"].append(dup)
    rep = check_result(data, SOURCES)
    assert rep.failures[0].reasons == ["duplicate_excerpt_id"]

    data = as_dict(make_result())
    data["risk_cards"][0]["evidence"] = []
    rep = check_result(data, SOURCES)
    assert rep.verdict == "fail" and rep.cards_ok == 1
    assert [(f.card_id, f.excerpt_id, f.reasons) for f in rep.failures] == [("card_1", None, ["no_evidence"])]


def test_every_reason_key_is_documented() -> None:
    for key in (
        "no_evidence",
        "excerpt_missing",
        "duplicate_excerpt_id",
        "source_url_missing",
        "source_url_invalid",
        "source_not_found",
        "source_lookup_error",
        "offset_missing",
        "offset_invalid",
        "offset_out_of_range",
        "text_mismatch",
        "text_hash_mismatch",
        "source_hash_mismatch",
    ):
        assert key in REASONS


# ── 폐기율 ────────────────────────────────────────────────────────────────


def test_no_drop_counts_says_so_explicitly() -> None:
    rep = check_result(make_result(with_drop=False), SOURCES)
    assert rep.passed  # 연결은 다 됐지만
    assert not rep.drop.available and rep.drop.rate is None
    assert "폐기율 없음" in rep.drop.note and NO_DROP_NOTE in rep.notes
    assert "폐기율 없음" in rep.summary()
    assert rep.model_dump(mode="json")["drop"]["rate"] is None


def test_drop_rate_from_stage_counts() -> None:
    stages = [
        StageStatus(stage="extract_paper_1", counts={"findings_kept": 8, "findings_dropped": 2}),
        StageStatus(stage="extract_paper_2", counts={"findings_total": 10, "findings_dropped": 0}),
        StageStatus(stage="synthesize", counts={"cards": 2}),
    ]
    res = make_result(with_drop=False).model_copy(update={"stages": stages})
    for inp in (res, as_dict(res)):
        rep = check_result(inp, SOURCES)
        assert (rep.drop.findings_dropped, rep.drop.findings_total) == (2, 20)
        assert rep.drop.rate == pytest.approx(0.1)
        assert rep.drop.source == "stages:extract_paper_1,extract_paper_2"


@pytest.mark.parametrize(
    "counts",
    [
        {"findings_total": 3, "findings_dropped": 5},
        {"findings_total": "20", "findings_dropped": 3},
        {"findings_dropped": 3},
        {"findings_total": 0, "findings_dropped": 0},
    ],
)
def test_bad_drop_counts_are_not_reported_as_rate(counts) -> None:
    rep = check_result(make_result(with_drop=False).model_copy(update={"verification": counts}), SOURCES)
    assert not rep.drop.available and rep.drop.rate is None
    assert "폐기율" in rep.drop.note


# ── 카드 0장 ──────────────────────────────────────────────────────────────


def test_no_cards_is_not_a_vacuous_pass() -> None:
    res = PremortemResult(session_id="s", plan_id="p", notices=["no related work"])
    rep = check_result(res, SOURCES)
    assert rep.verdict == "no_cards" and not rep.passed
    assert rep.linkage_rate is None and rep.card_pass_rate is None
    assert "정의 안 됨" in rep.summary()


def test_degraded_status_is_noted() -> None:
    res = make_result().model_copy(update={"status": "degraded"})
    rep = check_result(res, SOURCES)
    assert rep.passed and rep.result_status == "degraded"
    assert any("status=degraded" in n for n in rep.notes)


def test_bad_input_type_raises() -> None:
    with pytest.raises(TypeError):
        check_result([], SOURCES)  # type: ignore[arg-type]


# ── 원문 읽기 ─────────────────────────────────────────────────────────────


def write_sources_jsonl(path: Path, sources: dict[str, str]) -> None:
    lines = [json.dumps({"review_id": k, "work_id": "w", "text": v}, ensure_ascii=False) for k, v in sources.items()]
    # 발췌 레코드는 원문이 아니므로 건너뛰어야 한다
    lines.append(json.dumps(E_ZERO.model_dump(mode="json")))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_sources_formats(tmp_path: Path) -> None:
    jl = tmp_path / "reviews.jsonl"
    write_sources_jsonl(jl, SOURCES)
    assert load_sources([jl]) == SOURCES

    mp = tmp_path / "more.json"
    mp.write_text(json.dumps({"dec_1": "Reject."}), encoding="utf-8")
    assert load_sources([tmp_path]) == {**SOURCES, "dec_1": "Reject."}

    text_with_ls = "line one\u2028still the same record"  # splitlines()였다면 잘렸을 문자
    ls = tmp_path / "ls.jsonl"
    ls.write_text(json.dumps({"response_id": "resp_1", "text": text_with_ls}, ensure_ascii=False), encoding="utf-8")
    assert load_sources([ls]) == {"resp_1": text_with_ls}

    clash = tmp_path / "clash.json"
    clash.write_text(json.dumps({"rev_a": "different text"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_sources([jl, clash])


# ── CLI ───────────────────────────────────────────────────────────────────


def write_inputs(tmp_path: Path, data: dict) -> tuple[Path, Path]:
    result = tmp_path / "result.json"
    result.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    src = tmp_path / "reviews.jsonl"
    write_sources_jsonl(src, SOURCES)
    return result, src


def test_cli_pass_and_fail(tmp_path: Path, capsys) -> None:
    result, src = write_inputs(tmp_path, as_dict(make_result()))
    out = tmp_path / "out" / "report.json"
    assert main(["--result", str(result), "--sources", str(src), "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["passed"] is True and rep["linkage_rate"] == 1.0 and rep["drop"]["rate"] == 0.15
    assert "근거 연결률 4/4" in capsys.readouterr().out

    data = as_dict(make_result(with_drop=False))
    evidence_entry(data, E_ZERO.excerpt_id)["source_url"] = ""
    result, src = write_inputs(tmp_path, data)
    assert main(["--result", str(result), "--sources", str(src), "--out", str(out)]) == 1
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["passed"] is False and rep["linkage_rate"] == 0.5
    assert rep["drop"]["available"] is False and "폐기율 없음" in rep["drop"]["note"]
    assert {f["card_id"] for f in rep["failures"]} == {"card_1", "card_2"}


def test_cli_without_sources_fails_and_empty_result(tmp_path: Path) -> None:
    result, _ = write_inputs(tmp_path, as_dict(make_result()))
    assert main(["--result", str(result)]) == 1

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps(PremortemResult(session_id="s", plan_id="p").model_dump(mode="json")), "utf-8")
    assert main(["--result", str(empty)]) == 1
    assert main(["--result", str(empty), "--allow-empty"]) == 0

    assert main(["--result", str(tmp_path / "nope.json")]) == 2


def test_cli_module_entry_point(tmp_path: Path) -> None:
    """`python -m eval.linkage`로 실제 실행한다."""
    data = as_dict(make_result())
    evidence_entry(data, E_LEAK.excerpt_id)["text_sha256"] = "0" * 64
    result, src = write_inputs(tmp_path, data)
    out = tmp_path / "report.json"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)]), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, "-m", "eval.linkage", "--result", str(result), "--sources", str(src), "--out", str(out)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 1, proc.stderr
    assert "근거 연결률 3/4 = 0.750" in proc.stdout
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["reason_counts"] == {"text_hash_mismatch": 1}
