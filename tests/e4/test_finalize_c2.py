"""C-2(VER-FIN) 회귀: 확정 문안의 서빙 상한, 이벤트 루프 밖 preflight, 정규식 선형 시간, 수정 권고 문자열 상한,
연구자 문안·결속되지 않은 서명 입력의 출처 표시. 실제 HTTP(ASGI)·실제 signing 모듈, mock LLM, 실제 API 없음."""

from __future__ import annotations

import copy
import threading
import time

from neumann.analyze.revise import contains_identity, unsupported_facts
from neumann.api import finalize, signing
from tests.e4.test_finalize_api import engine, setup
from tests.e4.test_revise_api import PLAN, _bundle, _decisions, client, result_json, run


def test_confirmed_text_gets_the_same_serving_caps_as_plan_text(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch, max_plan_chars=len(PLAN) + 5, max_token_chars=64)
    calls = []
    monkeypatch.setattr(finalize, "finalize_plan", engine(calls))
    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            base = {"plan_text": PLAN, "revision": bundle, "confirmed_base_id": "x"}
            big = await c.post(finalize.FINALIZE_PATH, json={**base, "submission_id": "cap_chars_1", "confirmed_text": "가 " * (len(PLAN) // 2 + 30)})
            assert big.status_code == 413 and big.json()["error_code"] == "too_large"
            token = await c.post(finalize.FINALIZE_PATH, json={**base, "submission_id": "cap_token_1", "confirmed_text": "a" * 100})
            assert token.status_code == 422 and token.json()["error_code"] == "long_token"
    run(go())
    assert calls == [] and srv.gate.active == srv.gate.waiting == 0
    assert srv.budget.used == 1  # only the bundle's own revise run spent budget; both refused requests were refunded


def test_preflight_runs_off_the_event_loop(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(finalize, "finalize_plan", engine([]))
    from neumann.analyze import assemble as asm
    seen = []
    real = asm.assemble_revised_plan
    def spy(*a, **kw):
        seen.append(threading.current_thread() is threading.main_thread())
        return real(*a, **kw)
    monkeypatch.setattr(asm, "assemble_revised_plan", spy)
    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            r = await c.post(finalize.FINALIZE_PATH, json={"plan_text": PLAN, "revision": bundle, "submission_id": "preflight_thread"})
            assert r.status_code == 200
    run(go())
    assert seen and seen[0] is False  # preflight ran in a worker thread, not on the loop thread


def test_identity_and_entity_regexes_are_linear_on_hostile_input():
    for text in ["\n" * 20_000 + "x", "a" * 20_000, "Ab\n" * 7_000, " " * 20_000 + "best regards"]:
        t0 = time.perf_counter()
        contains_identity(text)
        unsupported_facts(text, "")
        assert time.perf_counter() - t0 < 1.0, len(text)
    assert contains_identity("  best regards,\nthe team") and unsupported_facts("서울대학교와 협력", "")


def test_revision_strings_are_bounded(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(finalize, "finalize_plan", engine(calls))
    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            hostile = copy.deepcopy(bundle)
            hostile["revisions"][0]["edits"][0]["proposed_text"] = "\n" * 9_000
            t0 = time.perf_counter()
            r = await c.post(finalize.FINALIZE_PATH, json={"plan_text": PLAN, "revision": hostile, "submission_id": "bounded_rev_1"})
            assert r.status_code == 422 and r.json()["error_code"] == "invalid_request" and time.perf_counter() - t0 < 2.0
            d = await c.post(finalize.FINALIZE_PATH, json={"plan_text": PLAN, "revision": bundle, "submission_id": "bounded_dec_1",
                                                          "decisions": [{"edit_id": "e", "decision": "modify", "revised_text": "x" * 9_000}]})
            assert d.status_code == 422
    run(go())
    assert calls == []


def _signed_body(bundle, result):
    bundle = copy.deepcopy(bundle)
    bundle["revision_sig"] = signing.sign_payload("revision", {k: v for k, v in bundle.items() if k != "revision_sig"})
    return {"plan_text": PLAN, "revision": bundle, "result": result, "result_sig": signing.sign_result(result),
            "decisions": _decisions(bundle)}


def test_researcher_confirmed_text_is_labelled_user_input_and_never_server_signed(tmp_path, monkeypatch):
    srv, app = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(finalize, "finalize_plan", engine([]))
    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            body = _signed_body(bundle, result_json())
            good = await c.post(finalize.FINALIZE_PATH, json={**body, "submission_id": "coupled_signed_1"})
            assert good.status_code == 200
            out = good.json()
            assert out["origin"] == "server_signed" and out["text_source"] == "server_assembled"
            assert out["provenance"] == {"inputs_signed": True, "coupled": True, "coupling": "coupled", "researcher_text": False}
            base_id = out["assembled"]["revised_plan_id"]
            mine = await c.post(finalize.FINALIZE_PATH, json={**body, "submission_id": "researcher_text_1",
                                                             "confirmed_text": "연구자가 직접 고친 계획서 문안.", "confirmed_base_id": base_id})
            assert mine.status_code == 200
            out = mine.json()
            assert out["origin"] == "client_submitted_unverified" and out["finalization_sig"] is None
            assert out["text_source"] == "researcher_confirmed" and out["provenance"]["researcher_text"] is True
            assert any("서버 서명을 붙이지 않는다" in n for n in out["finalization"]["notices"])
    run(go())


def test_individually_signed_but_uncoupled_inputs_are_not_promoted(tmp_path, monkeypatch):
    """V-finalization H1: revision from result A + separately signed result B (same plan, different card title)."""
    srv, app = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(finalize, "finalize_plan", engine([]))
    async def go():
        async with client(app) as c:
            bundle = await _bundle(c)
            other = result_json()
            other["risk_cards"][0]["title"] = "A different card title for the same plan"
            r = await c.post(finalize.FINALIZE_PATH, json={**_signed_body(bundle, other), "submission_id": "uncoupled_h1"})
            assert r.status_code == 200
            out = r.json()
            assert out["origin"] == "client_submitted_unverified" and out["finalization_sig"] is None
            assert out["provenance"]["inputs_signed"] is True and out["provenance"]["coupled"] is False
            assert out["provenance"]["coupling"] == "card_mismatch"
            assert any("결속" in n for n in out["finalization"]["notices"])
            session = result_json()
            session["session_id"] = "sess_other_session"
            s = await c.post(finalize.FINALIZE_PATH, json={**_signed_body(bundle, session), "submission_id": "uncoupled_session"})
            assert s.json()["provenance"]["coupling"] == "session_or_plan_mismatch" and s.json()["origin"] == "client_submitted_unverified"
    run(go())


def test_coupled_provenance_unit_cases():
    ok, why = finalize.coupled_provenance(None, {})
    assert not ok and why == "result_missing"
    result = {"session_id": "s", "plan_id": "p", "risk_cards": [{"card_id": "c", "risk_code": "R3", "title": "t", "evidence": ["e1"]}],
              "evidence": [{"excerpt_id": "e1"}]}
    rev = {"session_id": "s", "plan_id": "p", "records": [{"excerpt_id": "r1"}], "revisions": [{
        "card_id": "c", "risk_code": "R3", "title": "t", "evidence_pool": ["e1", "r1"],
        "interpretation": [{"excerpt_ids": ["e1"]}], "edits": [{"rationale": {"excerpt_ids": ["r1"]}}]}]}
    assert finalize.coupled_provenance(result, rev) == (True, "coupled")
    stray = copy.deepcopy(rev)
    stray["revisions"][0]["edits"][0]["rationale"]["excerpt_ids"] = ["e_from_other_result"]
    assert finalize.coupled_provenance(result, stray) == (False, "evidence_mismatch")
    missing = copy.deepcopy(rev)
    missing["revisions"][0]["evidence_pool"] = ["r1"]
    assert finalize.coupled_provenance(result, missing) == (False, "evidence_mismatch")
