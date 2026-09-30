"""B1-pairing: 개별로는 정상 서명된 result·revision·assembled를 **서로 섞어** 보내면 내보내기가 결합 검증으로 막는다.

Codex 감사(out/codex/results/ASTRA-provenance-coupling-audit-evidence.md)의 P0·A1~A6을 방어 기대값으로 뒤집은 것이다.
- P0(정상 결합)·A1(다른 목적 서명)·A2(카드 변조 + 옛 서명)는 기존 경계 그대로다.
- A3(다른 서명 결과 + 옛 수정 권고)·A4(다른 서명 수정 권고 + 옛 통합본)·A5(채택된 통합본 + 기각 결정)·A6(같은 발췌 id, 다른
  인용)는 각각 유효한 서명이라도 결합이 어긋나므로 422다. 확인할 자료가 없는 옛 통합본은 trusted가 아니라
  client_submitted_unverified로 표기한다.
- 변이 검사: 결합 검사 하나를 끄면 그 반례가 다시 통과한다(검사가 실제로 일한다는 증거).
실제 파이프라인·OpenAI 없음(mock provider, 가짜 기록 저장소). 서명 키는 이 프로세스의 무작위 키다.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.analyze import assemble as asm
from neumann.analyze import revise
from neumann.analyze.mock_responders import default_responders
from neumann.api import export, export_revision, signing
from neumann.api import revise as api
from neumann.llm import MockProvider
from neumann.models import Excerpt
from tests.e3.revise_fixtures import make_store
from tests.fixtures.loader import load_fixtures, plan_text

SIGNED = "server_signed"
UNVERIFIED = "client_submitted_unverified"


def signed_revision(result: dict[str, Any], card_ids: list[str] | None = None) -> dict[str, Any]:
    """서버가 실제로 발급하는 모양(origin 포함 본문에 revision 도메인 서명)."""
    rev = revise.revise_result(result, card_ids=card_ids, store=make_store(), llm=MockProvider(default_responders()))
    rev["origin"] = SIGNED
    rev["revision_sig"] = signing.sign_payload("revision", rev)
    return rev


def resign_revision(rev: dict[str, Any]) -> dict[str, Any]:
    """다른 정상 발급본을 흉내 낸다(같은 키로 다시 서명). 공격자가 서명을 위조한다는 뜻이 아니다."""
    body = {k: v for k, v in rev.items() if k != "revision_sig"}
    return {**body, "revision_sig": signing.sign_payload("revision", body)}


def first_edit(rev: dict[str, Any]) -> dict[str, Any]:
    return next(e for r in rev["revisions"] for e in r["edits"])


@dataclass
class Sent:
    status: int
    detail: str
    files: dict[str, bytes]
    headers: dict[str, str]

    @property
    def manifest(self) -> dict[str, Any]:
        return json.loads(self.files["manifest.json"])

    @property
    def readme(self) -> str:
        return self.files["README.md"].decode("utf-8")

    @property
    def revision_origin(self) -> str | None:
        return json.loads(self.files[export_revision.REVISION_FILE])["origin"] if export_revision.REVISION_FILE in self.files else None

    @property
    def assembly_trusted(self) -> bool:
        return f"통합본 출처: {SIGNED}" in self.readme


@dataclass
class Chain:
    result: dict[str, Any]
    result_sig: str
    revision: dict[str, Any]
    decisions: list[dict[str, Any]]
    revised_plan: dict[str, Any]
    client: TestClient

    def payload(self) -> dict[str, Any]:
        return copy.deepcopy({"result": self.result, "result_sig": self.result_sig, "revision": self.revision,
                              "revised_plan": self.revised_plan, "revision_decisions": self.decisions})

    def send(self, payload: dict[str, Any]) -> Sent:
        response = self.client.post("/premortem/package", json=payload)
        if response.status_code != 200:
            detail = response.json().get("detail")
            return Sent(response.status_code, detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False), {},
                        dict(response.headers))
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(files["manifest.json"])
        for entry in manifest["files"]:  # ZIP 자체 무결성은 늘 성립한다(새로 만든 바이트의 해시이므로 계보 증명이 아니다)
            assert hashlib.sha256(files[entry["path"]]).hexdigest() == entry["sha256"]
        return Sent(200, "", files, dict(response.headers))

    def assemble(self, decisions: list[dict[str, Any]], *, result: dict[str, Any] | None = None,
                 revision: dict[str, Any] | None = None, polish: bool = False) -> dict[str, Any]:
        res = result if result is not None else self.result
        return api.run_assembly(api.AssembleRequest(result=res, result_sig=signing.sign_result(res), plan_text=plan_text(),
                                                    revision=revision or self.revision, decisions=decisions, polish=polish),
                                provider="mock")


@pytest.fixture(scope="module")
def chain() -> Chain:
    result = load_fixtures().premortem_result.model_dump(mode="json")
    result_sig = signing.sign_result(result)
    revision = signed_revision(result)
    edit = first_edit(revision)
    decisions = [{"edit_id": edit["edit_id"], "decision": "adopt"}]
    assembled = api.run_assembly(api.AssembleRequest(result=result, result_sig=result_sig, plan_text=plan_text(),
                                                     revision=revision, decisions=decisions), provider="mock")
    assert assembled["stats"]["applied"] == 1 and assembled["origin"] == SIGNED and assembled["revised_plan_sig"]
    app = FastAPI()
    app.include_router(export.router)
    with TestClient(app) as client:
        yield Chain(result, result_sig, revision, decisions, assembled, client)


# ── 반례 조립(감사 A3~A6, 검사 하나에만 걸리는 최소 변형) ─────────────────


def a3_other_result(chain: Chain, variant: str) -> dict[str, Any]:
    """A3: 같은 계획서의 **다른** 정상 서명 결과 + 옛 서명 수정 권고·통합본."""
    p = chain.payload()
    changed_card = p["revised_plan"]["changes"][0]["card_id"]
    other_card = next(c["card_id"] for c in p["result"]["risk_cards"] if c["card_id"] != changed_card)
    if variant == "audit":  # 감사 원본: 통합본의 원천 카드가 없는 다른 세션의 결과
        p["result"]["risk_cards"] = [c for c in p["result"]["risk_cards"] if c["card_id"] != changed_card]
        p["result"]["session_id"] = "synthetic-other-analysis"
    elif variant == "session":  # 세션만 다르다(카드·근거는 같다)
        p["result"]["session_id"] = "synthetic-other-analysis"
    elif variant == "cards":  # 수정 권고가 다룬 카드 하나가 결과에 없다
        p["result"]["risk_cards"] = [c for c in p["result"]["risk_cards"] if c["card_id"] != other_card]
    elif variant == "evidence":  # 카드 id는 같지만 근거 목록이 다르다(다른 분석의 같은 이름 카드)
        card = next(c for c in p["result"]["risk_cards"] if c["card_id"] == other_card)
        card["evidence"] = card["evidence"][:-1]
    elif variant == "record_collision":  # 결과 evidence가 수정 권고의 새 기록 발췌와 같은 id를 쓴다
        rec = p["revision"]["records"][0]
        p["result"]["evidence"].append({k: rec[k] for k in Excerpt.model_fields if k in rec})
    else:
        raise AssertionError(variant)
    p["result_sig"] = signing.sign_result(p["result"])
    return p


def a4_other_revision(chain: Chain, variant: str = "audit") -> dict[str, Any]:
    """A4: 같은 결과의 **다른** 정상 서명 수정 권고 + 첫 서명 통합본(적용 수정안이 새 권고에 없다)."""
    p = chain.payload()
    changed_card = p["revised_plan"]["changes"][0]["card_id"]
    if variant == "audit":
        other_cards = [c["card_id"] for c in p["result"]["risk_cards"] if c["card_id"] != changed_card]
        p["revision"] = signed_revision(p["result"], card_ids=other_cards)
    elif variant == "same_ids_other_text":  # 같은 edit_id인데 제안 문안이 다른 재발급본
        rev = copy.deepcopy(p["revision"])
        first_edit(rev)["proposed_text"] = "재발급된 다른 제안 문안이다."
        p["revision"] = resign_revision(rev)
    elif variant == "extra_edit":  # 수정안이 하나 더 있는 재발급본(edits_total이 다르다)
        rev = copy.deepcopy(p["revision"])
        edit = first_edit(rev)
        rev["revisions"][0]["edits"].append({**edit, "edit_id": edit["edit_id"] + "x"})
        p["revision"] = resign_revision(rev)
    else:
        raise AssertionError(variant)
    p["revision_decisions"] = []
    return p


def a5_decision_conflict(chain: Chain, variant: str = "reject") -> dict[str, Any]:
    """A5: 채택된 서명 통합본은 그대로 두고 내보내기 결정만 바꾼다."""
    p = chain.payload()
    if variant == "reject":
        p["revision_decisions"][0]["decision"] = "reject"
    elif variant == "modify_other_text":
        p["revision_decisions"][0].update(decision="modify", revised_text="연구자가 나중에 다시 쓴 문장")
    elif variant == "adopt_undecided":  # 통합본이 미결정으로 기록한 수정안을 채택했다고 적는다
        p["revision_decisions"].append({"edit_id": p["revised_plan"]["undecided"][0], "decision": "adopt"})
    else:
        raise AssertionError(variant)
    return p


def a6_rebound_quote(chain: Chain) -> tuple[dict[str, Any], str, str]:
    """A6: 같은 출처 id·오프셋·발췌 id·세션이지만 원문 바이트가 바뀐(같은 길이) 다른 서명 결과 + 옛 서명 통합본."""
    p = chain.payload()
    used = set(p["revised_plan"]["changes"][0]["excerpt_ids"])
    ex = next(e for e in p["result"]["evidence"] if e["excerpt_id"] in used)
    prior_text = ex["text"]
    old_excerpt = Excerpt.model_validate(ex)
    old_source = load_fixtures().source_text(old_excerpt)
    assert old_excerpt.verify_against(old_source)
    marker = "SYNTHETIC ALTERNATE SOURCE QUOTE"
    assert len(marker) <= ex["end"] - ex["start"]
    new_source = old_source[: ex["start"]] + marker.ljust(ex["end"] - ex["start"], ".") + old_source[ex["end"]:]
    new_excerpt = Excerpt.from_source(new_source, ex["start"], ex["end"], source_kind=ex["source_kind"], source_id=ex["source_id"],
                                      source_url=ex["source_url"], excerpt_id=ex["excerpt_id"])
    assert new_excerpt.verify_against(new_source) and not new_excerpt.verify_against(old_source)
    assert new_excerpt.excerpt_id == old_excerpt.excerpt_id  # make_id는 원문 바이트에 안 걸린다(models.py)
    ex.update(new_excerpt.model_dump(mode="json"))
    p["result_sig"] = signing.sign_result(p["result"])
    body = {k: v for k, v in p["revised_plan"].items() if k != "revised_plan_sig"}
    assert signing.verify_payload("revised-plan", body, p["revised_plan"]["revised_plan_sig"])  # 옛 통합본 서명은 여전히 유효
    assert prior_text in p["revised_plan"]["markdown"]["footnoted"] and marker not in p["revised_plan"]["markdown"]["footnoted"]
    return p, prior_text, marker


# ── P0·A1·A2: 기존 경계 보존 ───────────────────────────────────────────────


def test_p0_correct_signed_chain_is_trusted_end_to_end(chain: Chain):
    r = chain.send(chain.payload())
    assert r.status == 200 and len(r.files) == 11
    assert r.headers["x-neumann-result-origin"] == SIGNED
    assert r.headers["x-neumann-revision-origin"] == SIGNED and r.headers["x-neumann-assembly-origin"] == SIGNED
    assert r.revision_origin == SIGNED and r.assembly_trusted
    comp = r.manifest["composition"]
    assert comp["revision_origin"] == SIGNED and comp["assembly_origin"] == SIGNED and comp["qualifiers"] == []
    assert set(comp["checks"]) == set(export_revision.PAIRING_CHECKS) and set(comp["checks"].values()) == {"ok"}
    by_path = {f["path"]: f for f in r.manifest["files"]}
    assert by_path[export_revision.REVISION_FILE]["origin"] == SIGNED
    assert by_path[export_revision.REVISED_PLAN_FILE]["origin"] == SIGNED
    md = r.files[export_revision.REVISED_PLAN_FILE].decode("utf-8")
    assert UNVERIFIED not in md and "mock" in md
    # 서명된 각주 판과 내보낸 각주 판이 글자 그대로 같다(라벨 포함).
    assert md.startswith(chain.revised_plan["markdown"]["footnoted"].rstrip("\n"))
    assert "결합 검증:" in r.readme


def test_a1_cross_purpose_signature_still_downgrades(chain: Chain):
    p = chain.payload()
    p["revision"]["revision_sig"] = p["revised_plan"]["revised_plan_sig"]
    r = chain.send(p)
    assert r.status == 200 and r.headers["x-neumann-result-origin"] == SIGNED
    assert r.revision_origin == UNVERIFIED and not r.assembly_trusted
    assert r.headers["x-neumann-revision-origin"] == UNVERIFIED and r.headers["x-neumann-assembly-origin"] == UNVERIFIED


def test_a2_changed_card_with_stale_result_signature_still_downgrades(chain: Chain):
    p = chain.payload()
    p["result"]["risk_cards"][0]["title"] += " altered"
    r = chain.send(p)
    assert r.status == 200 and r.headers["x-neumann-result-origin"] == UNVERIFIED
    assert r.revision_origin == UNVERIFIED and not r.assembly_trusted
    assert r.manifest["composition"]["checks"]["quotes"] == "skipped"  # 서명이 깨진 사슬에서는 인용 계보 비교 대상이 없다


# ── A3~A6: 반례는 422 ─────────────────────────────────────────────────────


@pytest.mark.parametrize("variant, needle", [
    ("audit", "session_id"), ("session", "session_id"), ("cards", "위험카드에 없다"),
    ("evidence", "근거 목록과 다르다"), ("record_collision", "같은 id"),
])
def test_a3_independently_signed_other_result_is_rejected(chain: Chain, variant: str, needle: str):
    r = chain.send(a3_other_result(chain, variant))
    assert r.status == 422, r.detail
    assert needle in r.detail and "synthetic" not in r.detail  # 입력 값을 되돌려 보내지 않는다
    assert "x-neumann-result-origin" not in r.headers


@pytest.mark.parametrize("variant, needle", [
    ("audit", "수정 권고에 없다"), ("same_ids_other_text", "제안 문안과 다르다"), ("extra_edit", "edits_total"),
])
def test_a4_independently_signed_other_revision_is_rejected(chain: Chain, variant: str, needle: str):
    p = a4_other_revision(chain, variant)
    assert signing.verify_payload("revision", {k: v for k, v in p["revision"].items() if k != "revision_sig"}, p["revision"]["revision_sig"])
    r = chain.send(p)
    assert r.status == 422, r.detail
    assert needle in r.detail


@pytest.mark.parametrize("variant, needle", [
    ("reject", "기각"), ("modify_other_text", "수정"), ("adopt_undecided", "미결정"),
])
def test_a5_decision_conflicting_with_signed_assembly_is_rejected(chain: Chain, variant: str, needle: str):
    r = chain.send(a5_decision_conflict(chain, variant))
    assert r.status == 422, r.detail
    assert needle in r.detail and "다시" in r.detail  # 통합본을 다시 만들라고 안내한다(조용히 재조립하지 않는다)


def test_a5_omitted_or_matching_or_recorded_reject_decisions_pass(chain: Chain):
    p = chain.payload()
    p["revision_decisions"] = []  # 결정 생략은 기각이 아니다
    r = chain.send(p)
    assert r.status == 200 and r.assembly_trusted and r.revision_origin == SIGNED
    r = chain.send(chain.payload())  # 같은 결정
    assert r.status == 200 and r.assembly_trusted
    # 통합본이 기각으로 기록한 수정안에 기각 결정 → 일치
    edits = [e for rv in chain.revision["revisions"] for e in rv["edits"]]
    decisions = [{"edit_id": edits[0]["edit_id"], "decision": "adopt"}, {"edit_id": edits[1]["edit_id"], "decision": "reject"}]
    assembled = chain.assemble(decisions)
    assert edits[1]["edit_id"] in assembled["rejected"] and assembled["revised_plan_sig"]
    p = chain.payload()
    p.update(revised_plan=assembled, revision_decisions=[*decisions, {"edit_id": edits[1]["edit_id"], "decision": "기각"}])
    r = chain.send(p)
    assert r.status == 200 and r.assembly_trusted
    p["revision_decisions"][-1]["decision"] = "채택"  # 마지막 결정이 기각과 어긋난다
    r = chain.send(p)
    assert r.status == 422 and "기각" in r.detail


def test_a5_modify_decision_matching_assembled_text_passes(chain: Chain):
    edit = first_edit(chain.revision)
    decisions = [{"edit_id": edit["edit_id"], "decision": "modify", "revised_text": "직접 쓴 문장 mail@example.org"}]
    assembled = chain.assemble(decisions)
    assert assembled["changes"][0]["decision"] == "modify" and assembled["revised_plan_sig"]
    p = chain.payload()
    p.update(revised_plan=assembled, revision_decisions=decisions)
    r = chain.send(p)
    assert r.status == 200 and r.assembly_trusted
    assert "mail@example.org" not in r.files[export_revision.REVISED_PLAN_FILE].decode("utf-8")


def test_a6_same_excerpt_id_with_different_quote_is_rejected(chain: Chain):
    p, prior_text, marker = a6_rebound_quote(chain)
    r = chain.send(p)
    assert r.status == 422, r.detail
    assert "인용" in r.detail and marker not in r.detail and prior_text not in r.detail
    # 같은 발췌 id → 같은 인용 해시. 결과만 따로 내보내면(수정 권고·통합본 없이) 결과 서명 기준으로 정상이다.
    alone = chain.send({"result": p["result"], "result_sig": p["result_sig"]})
    assert alone.status == 200 and alone.headers["x-neumann-result-origin"] == SIGNED and "composition" in alone.manifest
    assert alone.manifest["composition"] is None


# ── 확인 불가·비서명 결합·양성 변형 ──────────────────────────────────────


def test_signed_legacy_assembly_without_render_snapshot_is_qualified_not_trusted(chain: Chain):
    """각주 판 스냅숏이 없는 옛 통합본: 인용 계보를 확인할 수 없으므로 server_signed라고 적지 않는다(422도 아님)."""
    legacy = asm.assemble_revised_plan(plan_text(), chain.revision, chain.decisions, result=chain.result, regate=True)
    legacy["origin"] = SIGNED
    legacy["revised_plan_sig"] = signing.sign_payload("revised-plan", legacy)
    p = chain.payload()
    p["revised_plan"] = legacy
    r = chain.send(p)
    assert r.status == 200 and r.revision_origin == SIGNED and not r.assembly_trusted
    comp = r.manifest["composition"]
    assert comp["assembly_origin"] == UNVERIFIED and comp["checks"]["quotes"] == "unverified"
    assert any("인용 계보" in q for q in comp["qualifiers"])
    assert "결합 미확인" in r.readme and "인용 계보" in r.readme
    assert UNVERIFIED in r.files[export_revision.REVISED_PLAN_FILE].decode("utf-8")


def test_unsigned_mismatched_pair_is_rejected_regardless_of_signatures(chain: Chain):
    """서명이 없어도 결합이 어긋난 패키지는 만들지 않는다(어긋남은 서명과 무관한 사실)."""
    p = a3_other_result(chain, "cards")
    p["result_sig"] = None
    p["revision"]["revision_sig"] = None
    p["revised_plan"]["revised_plan_sig"] = None
    r = chain.send(p)
    assert r.status == 422 and "위험카드에 없다" in r.detail
    with pytest.raises(ValueError, match="위험카드에 없다"):
        export.build_package(p["result"], revision=p["revision"], revised_plan=p["revised_plan"])


def test_subset_revision_and_its_assembly_are_trusted(chain: Chain):
    """카드 일부만 요청한 수정 권고 + 그 통합본은 정상 결합이다(카드 부분집합은 어긋남이 아니다)."""
    other = [c["card_id"] for c in chain.result["risk_cards"] if c["card_id"] != chain.revised_plan["changes"][0]["card_id"]]
    rev = signed_revision(chain.result, card_ids=other)
    edit = first_edit(rev)
    decisions = [{"edit_id": edit["edit_id"], "decision": "adopt"}]
    assembled = chain.assemble(decisions, revision=rev)
    assert assembled["stats"]["applied"] == 1
    r = chain.send({"result": chain.result, "result_sig": chain.result_sig, "revision": rev, "revised_plan": assembled,
                    "revision_decisions": decisions})
    assert r.status == 200 and r.revision_origin == SIGNED and r.assembly_trusted


def test_polished_signed_assembly_keeps_signed_label_and_passes_quote_check(chain: Chain):
    assembled = chain.assemble(chain.decisions, polish=True)
    assert assembled["polish"]["applied"] is True and assembled["revised_plan_sig"]
    p = chain.payload()
    p["revised_plan"] = assembled
    r = chain.send(p)
    assert r.status == 200 and r.assembly_trusted
    md = r.files[export_revision.REVISED_PLAN_FILE].decode("utf-8")
    assert f"_{assembled['label']}_" in md and "다듬기 적용" in r.readme


def test_revision_only_and_assembly_only_extras_are_checked_where_possible(chain: Chain):
    p = a3_other_result(chain, "cards")
    p.pop("revised_plan")
    p["revision_decisions"] = []
    assert chain.send(p).status == 422  # 수정 권고만 보내도 결과와의 결합은 검사한다
    q = chain.payload()
    q.pop("revision")
    q["revision_decisions"] = []
    r = chain.send(q)  # 통합본만: 수정 권고가 없어 결합을 확인할 수 없다 → trusted 아님
    assert r.status == 200 and not r.assembly_trusted and r.manifest["composition"]["checks"]["edits"] == "skipped"


def test_assemble_api_does_not_mint_signature_for_mismatched_pair(tmp_path, monkeypatch, chain: Chain):
    """조립 API: 서명된 다른 결과 + 서명된 옛 수정 권고 → 서명하지 않는다(내보내기에서 422가 되는 결합을 서버가 인증하지 않는다)."""
    import asyncio

    from tests.e4.test_revise_api import client as async_client, make

    _srv, app = make(tmp_path, monkeypatch)
    other = a3_other_result(chain, "audit")

    async def go() -> None:
        async with async_client(app) as http:
            body = {"result": other["result"], "result_sig": other["result_sig"], "plan_text": plan_text(),
                    "revision": other["revision"], "decisions": []}
            response = await http.post("/premortem/revise/assemble", json=body)
            assert response.status_code == 200, response.text
            out = response.json()
            assert out["origin"] == UNVERIFIED and out["revised_plan_sig"] is None
            assert any("같은 분석" in n for n in out["notices"]) and "synthetic" not in json.dumps(out["notices"])
            good = await http.post("/premortem/revise/assemble", json={**body, "result": chain.result, "result_sig": chain.result_sig})
            assert good.status_code == 200 and good.json()["origin"] == SIGNED and good.json()["revised_plan_sig"]

    asyncio.run(go())


# ── 변이 검사: 검사 하나를 끄면 그 반례가 통과한다 ───────────────────────

COUNTEREXAMPLES = {
    "session": lambda c: a3_other_result(c, "session"),
    "cards": lambda c: a3_other_result(c, "cards"),
    "evidence": lambda c: a3_other_result(c, "evidence"),
    "edits": lambda c: a4_other_revision(c, "audit"),
    "decisions": lambda c: a5_decision_conflict(c, "reject"),
    "quotes": lambda c: a6_rebound_quote(c)[0],
}


def test_every_pairing_check_has_a_counterexample():
    assert set(COUNTEREXAMPLES) == set(export_revision.PAIRING_CHECKS)


@pytest.mark.parametrize("name", sorted(COUNTEREXAMPLES))
def test_mutation_disabling_one_check_lets_its_counterexample_through(chain: Chain, monkeypatch, name: str):
    payload = COUNTEREXAMPLES[name](chain)
    assert chain.send(payload).status == 422  # 검사가 켜져 있으면 막힌다
    monkeypatch.setitem(export_revision.PAIRING_CHECKS, name, lambda ctx: "ok")
    r = chain.send(payload)  # 그 검사 하나만 끄면 반례가 server_signed로 나간다 → 검사가 실제로 일한다
    assert r.status == 200, r.detail
    assert r.revision_origin == SIGNED and r.assembly_trusted
    monkeypatch.undo()
    assert chain.send(payload).status == 422
