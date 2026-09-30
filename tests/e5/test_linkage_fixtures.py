"""E5-L0 근거 연결 검사기를 공용 fixture(`tests/fixtures`, E0b)로 돌린다.

fixture 결과(`premortem_result.json`)와 카드(`risk_cards.jsonl`)가 원문 심사평·결정문에 100% 연결되는지,
그리고 같은 fixture에 조작을 넣으면 실제로 떨어지는지 잰다.
fixture가 아직 없는 브랜치에서는 skip으로 보고된다(통과로 세지 않는다).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

loader = pytest.importorskip("tests.fixtures.loader", reason="공용 fixture(E0b)가 아직 이 브랜치에 없다")

from eval.linkage import check_result, main  # noqa: E402
from neumann.models import PremortemResult, sha256_text  # noqa: E402

FX_DIR: Path = loader.FIXTURES_DIR


@pytest.fixture(scope="module")
def fx():
    return loader.load_fixtures()


@pytest.fixture(scope="module")
def sources(fx) -> dict[str, str]:
    out = {r.review_id: r.text for r in fx.reviews}
    out.update({d.decision_id: d.text for d in fx.decisions if d.text is not None})
    return out


def test_fixture_result_is_fully_linked(fx, sources) -> None:
    res = fx.premortem_result
    rep = check_result(res, sources)
    assert rep.verdict == "pass", rep.failures
    assert rep.links_total == sum(len(c.evidence) for c in res.risk_cards) > 0
    assert rep.linkage_rate == 1.0 and rep.card_pass_rate == 1.0
    assert rep.cards_total == len(res.risk_cards) and rep.source_hash_unchecked == 0
    if rep.drop.available:
        assert rep.drop.rate is not None
    else:  # 폐기 수가 없으면 숨기지 않고 명시한다
        assert "폐기율" in rep.drop.note and rep.drop.rate is None


def test_fixture_offset_zero_excerpts_are_linked(fx, sources) -> None:
    res = fx.premortem_result
    cited = {eid for c in res.risk_cards for eid in c.evidence}
    zero = [e for e in res.evidence if e.start == 0 and e.excerpt_id in cited]
    assert zero, "fixture 카드가 오프셋 0 발췌를 인용해야 이 검사가 의미 있다"
    only_zero = res.model_copy(
        update={"risk_cards": [c.model_copy(update={"evidence": [zero[0].excerpt_id]}) for c in res.risk_cards[:1]]}
    )
    rep = check_result(only_zero, sources)
    assert rep.verdict == "pass" and rep.linkage_rate == 1.0, rep.failures


def test_fixture_risk_cards_jsonl_are_linked(fx, sources) -> None:
    res = PremortemResult(session_id="fx", plan_id="fx", evidence=fx.excerpts, risk_cards=fx.risk_cards)
    rep = check_result(res, sources)
    assert rep.verdict == "pass" and rep.linkage_rate == 1.0, rep.failures
    assert rep.cards_total == len(fx.risk_cards) >= 1


def _cited_nonzero(data: dict) -> dict:
    cited = {eid for c in data["risk_cards"] for eid in c["evidence"]}
    return next(e for e in data["evidence"] if e["excerpt_id"] in cited and e["start"] > 0)


def test_fixture_injected_quote_lowers_rate(fx, sources) -> None:
    data = fx.premortem_result.model_dump(mode="json")
    target = _cited_nonzero(data)
    forged = target["text"].swapcase()  # 같은 길이, 원문에 없는 글자
    assert forged != target["text"]
    target["text"], target["text_sha256"] = forged, sha256_text(forged)
    rep = check_result(data, sources)
    citing = [c["card_id"] for c in data["risk_cards"] if target["excerpt_id"] in c["evidence"]]
    assert rep.linkage_rate is not None and rep.linkage_rate < 1.0
    assert rep.links_ok == rep.links_total - len(citing)
    assert {(f.card_id, f.excerpt_id) for f in rep.failures} == {(cid, target["excerpt_id"]) for cid in citing}
    assert all(f.reasons == ["text_mismatch"] for f in rep.failures)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [("text_sha256", "0" * 64, "text_hash_mismatch"), ("source_url", "", "source_url_missing")],
)
def test_fixture_hash_only_or_empty_url_fails(fx, sources, field, value, reason) -> None:
    data = fx.premortem_result.model_dump(mode="json")
    _cited_nonzero(data)[field] = value
    rep = check_result(data, sources)
    assert rep.verdict == "fail" and rep.linkage_rate < 1.0
    assert set(rep.reason_counts) == {reason}


def test_fixture_cli(tmp_path: Path, capsys) -> None:
    out = tmp_path / "report.json"
    code = main(["--result", str(FX_DIR / "premortem_result.json"), "--sources", str(FX_DIR), "--out", str(out)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["passed"] is True and rep["linkage_rate"] == 1.0 and rep["failures"] == []
    assert "근거 연결률" in printed
