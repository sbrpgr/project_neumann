"""내보내기 ZIP의 수정 권고 자리(E3-L2r) + 결합 검증(B1-pairing). export.py는 이 모듈을 몇 줄로만 부른다.

ZIP 9파일은 그대로 두고, 요청에 수정 권고가 있을 때만 파일을 **덧붙인다**:
- `revision.json`: 카드별 수정 권고(계약 revision.schema.json 그대로) + 연구자 결정(채택·수정·기각) + 출처(origin)
- `revised_plan.md`: 통합본(각주 판 + 수정 이력·근거 부록). 요청의 revised_plan(계약 revised_plan.schema.json)이 있을 때

출처(origin): 서버 서명(`revision_sig`, E4-L2f signing)이 확인되면 server_signed, 아니면 client_submitted_unverified.
결정의 edit_id는 수정 권고 안에 있어야 한다(없으면 ValueError → 422). 리뷰어 신원 필드는 없다(NeumannModel).
연구자 문안·메모는 이메일·ORCID를 가린다.

결합 검증(B1-pairing, Codex 감사 A3~A6): 서명은 객체 하나의 무결성만 보장하고 **객체 사이의 관계**는 보장하지 않는다. 각각
정상 서명된 result·revision·revised_plan을 다른 분석의 것과 섞어 보내면 누락 카드·다른 수정안·기각인데 채택된 통합본·같은
발췌 id에 다른 인용이 "server_signed"로 나갈 수 있었다. 그래서 내보내기(export 쪽)가 세 객체를 교차 검증한다:
- revision → result: `session`(같은 분석 세션), `cards`(권고한 카드가 결과에 있고 위험 유형이 같다), `evidence`(카드 근거
  풀 = 결과 카드의 근거 + 권고의 새 기록, 인용 id는 모두 그 안, 새 기록 id는 결과 evidence와 겹치지 않는다)
- revised_plan → revision: `edits`(적용된 수정안이 권고의 같은 수정안이다: 카드·종류·줄·원문·근거 id·이유·채택 문안,
  수정안 총수, 기각·미결정·충돌 목록의 id)
- decisions → revised_plan: `decisions`(내보내기 결정이 통합본에 기록된 결정과 어긋나지 않는다. 결정 생략은 기각이 아니다)
- quotes: 서명된 통합본의 각주 판(`markdown.footnoted`, 서명 범위 안)과 지금 결과로 다시 그린 각주가 발췌마다 같다.
  `Excerpt.make_id`는 원문 바이트에 걸리지 않아 같은 id에 다른 인용이 구조적으로 가능하다(A6).
구체적 모순은 `PairingConflict`(ValueError → API 422)이고, 확인할 자료가 없으면(각주 판 없는 옛 통합본 등)
`PairingUnverifiable` → trusted가 아니라 client_submitted_unverified + 사유. 어긋남은 서명과 무관한 사실이므로 구조 검사
(session·cards·evidence·edits·decisions)는 서명 여부와 관계없이 하고, quotes는 세 서명이 모두 확인된 사슬에서만 비교한다
(서명이 깨진 사슬은 이미 unverified다). 서명 페이로드에 상위 객체 해시를 넣는 방식은 쓰지 않았다(이유는
docs/reports/B1-pairing.md): 이미 발급된 객체는 어차피 교차 검증이 필요하고, 계약·서명 발급자(E3-L2r)·화면을 함께 바꿔야 하며,
키 재기동 뒤(서명 전부 무효)에도 어긋난 패키지를 막는 것은 교차 검증뿐이다. 이 검증은 모순을 잡지 실제 생성 실행의
부모를 증명하지는 않는다(감사 보고서의 한계 그대로).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from itertools import zip_longest
from typing import Any, Literal

from pydantic import Field, field_validator

from neumann.models import SCHEMA_VERSION, NeumannModel, PremortemResult, redact_pii

REVISION_FILE = "revision.json"
REVISED_PLAN_FILE = "revised_plan.md"
FILE_ROLES: dict[str, str] = {
    REVISION_FILE: "카드별 수정 권고(해석·채택 연구의 대응·수정안·질문·게이트 폐기 수·근거 발췌)와 연구자 결정(채택·수정·기각)",
    REVISED_PLAN_FILE: "통합된 수정 계획서: 각주 판(변경 문장 옆 근거)과 수정 이력·미해결 충돌·자리표시·근거 부록",
}
DECISION_LABELS: dict[str, str] = {"adopt": "채택", "modify": "수정", "reject": "기각"}
_ALIASES = {v: k for k, v in DECISION_LABELS.items()}
SERVER_SIGNED = "server_signed"
UNVERIFIED = "client_submitted_unverified"
CHECK_LABELS: dict[str, str] = {"session": "세션", "cards": "카드", "evidence": "근거", "edits": "수정안", "decisions": "결정",
                                "quotes": "인용"}
STATE_LABELS: dict[str, str] = {"ok": "일치", "skipped": "해당 없음", "unverified": "미확인"}


class RevisionDecision(NeumannModel):
    """수정안(edit) 하나에 대한 연구자 결정."""

    edit_id: str = Field(min_length=1)
    card_id: str | None = None
    decision: Literal["adopt", "modify", "reject"]
    revised_text: str | None = Field(default=None, max_length=2000, description="수정(modify) 때 연구자 문안. 이메일·ORCID는 가린다")
    note: str | None = Field(default=None, max_length=2000)
    decided_at: datetime | None = None

    @field_validator("decision", mode="before")
    @classmethod
    def _accept_korean(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return _ALIASES.get(v, v.lower())
        return v

    @field_validator("revised_text", "note")
    @classmethod
    def _mask(cls, v: str | None) -> str | None:
        return None if v is None else redact_pii(v)

    @field_validator("decided_at")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("timezone-aware datetime만 허용한다")
        return v


def edit_ids_of(revision: Mapping[str, Any]) -> dict[str, str]:
    """edit_id → card_id."""
    out: dict[str, str] = {}
    for rev in revision.get("revisions", []) or []:
        if isinstance(rev, Mapping):
            for e in rev.get("edits", []) or []:
                if isinstance(e, Mapping) and isinstance(e.get("edit_id"), str):
                    out[e["edit_id"]] = str(rev.get("card_id", ""))
    return out


def validate_decisions(revision: Mapping[str, Any], decisions: Sequence[Mapping[str, Any] | RevisionDecision] | None
                       ) -> list[RevisionDecision]:
    ids = edit_ids_of(revision)
    out: list[RevisionDecision] = []
    for raw in decisions or ():
        d = raw if isinstance(raw, RevisionDecision) else RevisionDecision.model_validate(raw)
        if d.edit_id not in ids:
            raise ValueError(f"수정 권고에 없는 edit_id {d.edit_id!r}")
        if d.card_id is None:
            d = d.model_copy(update={"card_id": ids[d.edit_id]})
        out.append(d)
    return out


def _origin(revision: Mapping[str, Any], sig: Any, result: Any = None, result_sig: Any = None) -> str:
    """서명만 본 출처(결합 검증 전). 결과 서명과 수정 권고 서명이 모두 확인돼야 server_signed."""
    try:
        from neumann.api.revise import revision_verified, verify_result
    except ImportError:
        return UNVERIFIED
    return SERVER_SIGNED if verify_result(result, result_sig) and revision_verified(revision, sig) else UNVERIFIED


def _assembly_signed(revised_plan: Mapping[str, Any]) -> bool:
    try:
        from neumann.api.revise import verify_payload
    except ImportError:
        return False
    body = {k: v for k, v in revised_plan.items() if k != "revised_plan_sig"}
    return verify_payload("revised-plan", body, revised_plan.get("revised_plan_sig"))


def _assembly_trusted(result: Any, revision: Mapping[str, Any] | None, revision_sig: Any,
                      revised_plan: Mapping[str, Any], result_sig: Any) -> bool:
    """서명만 본 통합본 신뢰(결합 검증 전)."""
    sig = revision_sig if revision_sig is not None else (revision or {}).get("revision_sig")
    return revision is not None and _origin(revision, sig, result, result_sig) == SERVER_SIGNED and _assembly_signed(revised_plan)


def _json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


# ── 결합 검증(B1-pairing) ─────────────────────────────────────────────────


class PairingConflict(ValueError):
    """각각 유효해도 결합이 어긋난다(구체적 모순). API는 422로 거절한다."""


class PairingUnverifiable(Exception):
    """결합을 확인할 자료가 없다(옛 통합본 등). trusted가 아니라 사유와 함께 client_submitted_unverified."""


@dataclass
class PairingContext:
    result: PremortemResult
    revision: Mapping[str, Any] | None
    revised_plan: Mapping[str, Any] | None
    decided: list[RevisionDecision]
    chain_signed: bool  # 결과·수정 권고·통합본 서명이 모두 확인됐나(각주 판 스냅숏이 인증된 자료인지)


CheckResult = Literal["ok", "skipped"] | None
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _safe_id(value: Any) -> str:
    """오류 문구에 싣는 식별자: 서버가 만든 id 모양만 남기고 잘라 입력 값을 되돌려 보내지 않는다."""
    return re.sub(r"[^0-9A-Za-z_./:-]", "", str(value))[:40] or "?"


def _norm_text(text: Any) -> str:
    return " ".join(_CONTROL_RE.sub("", redact_pii(str(text or ""))).split())


def _maps(items: Any) -> list[Mapping[str, Any]]:
    return [x for x in (items or []) if isinstance(x, Mapping)]


def _ids(items: Any) -> set[str]:
    return {str(x) for x in (items or []) if isinstance(x, str)}


def check_session(ctx: PairingContext) -> CheckResult:
    """수정 권고는 결과와 같은 분석 세션의 것이어야 한다."""
    if ctx.revision is None:
        return "skipped"
    if ctx.revision.get("session_id") != ctx.result.session_id:
        raise PairingConflict("수정 권고의 session_id가 결과의 session_id와 다르다(다른 분석의 수정 권고)")
    return "ok"


def check_cards(ctx: PairingContext) -> CheckResult:
    """수정 권고가 다룬 카드는 모두 결과의 위험카드이고 위험 유형이 같다(A3: 누락 카드)."""
    if ctx.revision is None:
        return "skipped"
    cards = {c.card_id: c for c in ctx.result.risk_cards}
    for rev in _maps(ctx.revision.get("revisions")):
        cid = rev.get("card_id")
        card = cards.get(cid) if isinstance(cid, str) else None
        if card is None:
            raise PairingConflict(f"수정 권고의 카드 {_safe_id(cid)}가 결과의 위험카드에 없다(다른 분석의 수정 권고)")
        if rev.get("risk_code") != card.risk_code.value:
            raise PairingConflict(f"수정 권고의 카드 {_safe_id(cid)}의 위험 유형이 결과의 카드와 다르다")
    return "ok"


def check_evidence(ctx: PairingContext) -> CheckResult:
    """카드 근거 풀·인용 id가 결과 evidence + 권고 records 안이고, 풀의 결과 쪽이 결과 카드의 근거 목록과 같다."""
    if ctx.revision is None:
        return "skipped"
    result_ids = {e.excerpt_id for e in ctx.result.evidence}
    record_ids = _ids(r.get("excerpt_id") for r in _maps(ctx.revision.get("records")))
    collide = record_ids & result_ids
    if collide:
        raise PairingConflict(f"수정 권고의 새 기록 발췌 {len(collide)}건이 결과 evidence와 같은 id를 쓴다(다른 결과의 수정 권고)")
    known = result_ids | record_ids
    cards = {c.card_id: c for c in ctx.result.risk_cards}
    for rev in _maps(ctx.revision.get("revisions")):
        cid = _safe_id(rev.get("card_id"))
        card = cards.get(str(rev.get("card_id")))
        pool = rev.get("evidence_pool")
        if isinstance(pool, list) and card is not None:
            pool_ids = _ids(pool)
            if pool_ids - known:
                raise PairingConflict(f"카드 {cid}의 근거 풀에 결과 evidence·권고 records에 없는 발췌 {len(pool_ids - known)}건이 있다")
            if pool_ids - record_ids != set(card.evidence):
                raise PairingConflict(f"카드 {cid}의 근거 풀이 결과 카드의 근거 목록과 다르다(다른 분석의 같은 이름 카드)")
        cited: set[str] = set()
        for s in _maps(rev.get("interpretation")):
            cited |= _ids(s.get("excerpt_ids"))
        prec = rev.get("precedents") if isinstance(rev.get("precedents"), Mapping) else {}
        for p in _maps(prec.get("items")):
            cited |= _ids(p.get("excerpt_ids"))
        for e in _maps(rev.get("edits")):
            rat = e.get("rationale") if isinstance(e.get("rationale"), Mapping) else {}
            cited |= _ids(rat.get("excerpt_ids"))
        if cited - known:
            raise PairingConflict(f"카드 {cid}가 인용한 발췌 {len(cited - known)}건이 결과 evidence·권고 records에 없다")
    return "ok"


def check_edits(ctx: PairingContext) -> CheckResult:
    """통합본에 적용·기록된 수정안이 이 수정 권고의 같은 수정안이다(A4: 다른 권고의 통합본)."""
    if ctx.revised_plan is None or ctx.revision is None:
        return "skipped"
    from neumann.analyze import assemble as asm

    edits = asm.collect_edits(ctx.revision)
    plan = ctx.revised_plan
    polished = bool((plan.get("polish") or {}).get("applied")) if isinstance(plan.get("polish"), Mapping) else False
    for ch in _maps(plan.get("changes")):  # 적용된 수정안부터(가장 직접적인 모순을 먼저 말한다)
        eid = ch.get("edit_id")
        e = edits.get(str(eid))
        sid = _safe_id(eid)
        if e is None:
            raise PairingConflict(f"통합본에 적용된 수정안 {sid}이 수정 권고에 없다(다른 수정 권고의 통합본)")
        old_range = ch.get("old_range") if isinstance(ch.get("old_range"), list) and ch.get("old_range") else [None]
        if ch.get("card_id") != e.card_id or ch.get("kind") != e.kind or old_range[0] != e.plan_line:
            raise PairingConflict(f"통합본의 수정안 {sid}의 카드·종류·줄 번호가 수정 권고와 다르다")
        if e.kind == "replace" and ch.get("old_text") != e.current_text:
            raise PairingConflict(f"통합본의 수정안 {sid}의 원문 줄이 수정 권고의 current_text와 다르다")
        if ch.get("decision") == "adopt":
            if list(ch.get("excerpt_ids") or []) != list(e.excerpt_ids) or str(ch.get("rationale") or "") != e.rationale:
                raise PairingConflict(f"통합본의 수정안 {sid}의 근거 id·이유가 수정 권고와 다르다")
            if not polished and ch.get("new_text") != " ".join(e.proposed_text.split()):
                raise PairingConflict(f"통합본에 채택된 수정안 {sid}의 문안이 수정 권고의 제안 문안과 다르다")
    stats = plan.get("stats") if isinstance(plan.get("stats"), Mapping) else {}
    if stats.get("edits_total") != len(edits):
        raise PairingConflict("통합본의 수정안 총수(stats.edits_total)가 수정 권고의 수정안 수와 다르다(다른 수정 권고의 통합본)")
    referenced = [*(plan.get("rejected") or []), *(plan.get("undecided") or []),
                  *(x for c in _maps(plan.get("conflicts")) for x in (c.get("edit_ids") or []))]
    for eid in referenced:
        if str(eid) not in edits:
            raise PairingConflict(f"통합본이 기록한 수정안 {_safe_id(eid)}이 수정 권고에 없다(다른 수정 권고의 통합본)")
    return "ok"


def check_decisions(ctx: PairingContext) -> CheckResult:
    """내보내기 결정이 통합본에 기록된 결정과 어긋나지 않는다(A5). 결정 생략은 기각이 아니다."""
    if ctx.revised_plan is None or not ctx.decided:
        return "skipped"
    plan = ctx.revised_plan
    if not isinstance(plan.get("rejected"), list) or not isinstance(plan.get("undecided"), list):
        raise PairingUnverifiable("통합본에 기각·미결정 목록이 없어 결정과의 일치를 확인할 수 없다")
    changes = {str(ch.get("edit_id")): ch for ch in _maps(plan.get("changes"))}
    rejected, undecided = _ids(plan["rejected"]), _ids(plan["undecided"])
    pending = {str(x) for c in _maps(plan.get("conflicts")) for x in (c.get("edit_ids") or [])}
    pending |= _ids(s.get("edit_id") for s in _maps(plan.get("skipped")))
    polished = bool((plan.get("polish") or {}).get("applied")) if isinstance(plan.get("polish"), Mapping) else False
    last: dict[str, RevisionDecision] = {}
    for d in ctx.decided:  # 마지막 결정이 유효하다(assemble.collect_decisions와 같은 규칙)
        last[d.edit_id] = d
    hint = " — 결정을 바꿨으면 통합본을 다시 만든 뒤 내보낸다"
    for eid, d in last.items():
        sid, mine = _safe_id(eid), DECISION_LABELS[d.decision]
        ch = changes.get(eid)
        if ch is not None:
            theirs = DECISION_LABELS.get(str(ch.get("decision")), str(ch.get("decision")))
            if d.decision != ch.get("decision"):
                raise PairingConflict(f"수정안 {sid}의 결정({mine})이 통합본에 적용된 결정({theirs})과 다르다{hint}")
            if d.decision == "modify" and not polished and _norm_text(d.revised_text) != _norm_text(ch.get("new_text")):
                raise PairingConflict(f"수정안 {sid}의 수정 문안이 통합본에 적용된 문안과 다르다{hint}")
        elif eid in rejected:
            if d.decision != "reject":
                raise PairingConflict(f"수정안 {sid}은 통합본에서 기각인데 결정은 {mine}이다{hint}")
        elif eid in undecided:
            raise PairingConflict(f"수정안 {sid}은 통합본에서 미결정인데 결정({mine})이 왔다{hint}")
        elif eid in pending:
            if d.decision == "reject":
                raise PairingConflict(f"수정안 {sid}은 통합본에서 충돌·건너뜀(채택·수정 결정)인데 결정은 기각이다{hint}")
        else:
            raise PairingConflict(f"수정안 {sid}이 통합본의 적용·기각·미결정·충돌 어디에도 없다(다른 통합본){hint}")
    return "ok"


def check_quotes(ctx: PairingContext) -> CheckResult:
    """서명된 통합본의 각주 판과 지금 결과로 다시 그린 각주가 발췌마다 같다(A6: 같은 발췌 id, 다른 인용)."""
    if ctx.revised_plan is None or ctx.revision is None or not ctx.chain_signed:
        return "skipped"
    from neumann.analyze import assemble as asm

    plan = ctx.revised_plan
    order = list(dict.fromkeys(str(x) for ch in _maps(plan.get("changes")) for x in (ch.get("excerpt_ids") or [])))
    if not order:
        return "ok"  # 인용한 발췌가 없으면 다시 그릴 인용도 없다(되묶일 인용이 없으므로 스냅숏 없이도 공허하게 성립)
    md = plan.get("markdown")
    snapshot = md.get("footnoted") if isinstance(md, Mapping) else None
    if not isinstance(snapshot, str):
        raise PairingUnverifiable("서명된 통합본에 각주 판(markdown.footnoted)이 없어 인용 계보를 확인할 수 없다")
    current = asm.render_markdown(plan, asm.evidence_lookup(ctx.result, ctx.revision))["footnoted"]
    n = len(plan.get("lines") or [])
    snap, now = snapshot.split("\n"), current.split("\n")
    # render_markdown: 본문 n줄, "", "---", "", "_라벨_", "", 각주… — 라벨 줄만 생성 시점 표기라 비교에서 뺀다.
    if len(snap) < n + 5 or len(now) < n + 5 or snap[n + 1] != "---" or now[n + 1] != "---" or snap[:n] != now[:n]:
        raise PairingUnverifiable("서명된 통합본의 각주 판 구조가 지금 렌더링과 달라 인용 계보를 확인할 수 없다")
    for i, (old, new) in enumerate(zip_longest(snap[n + 5:], now[n + 5:])):
        if old != new:
            if i < len(order):
                raise PairingConflict(f"발췌 {_safe_id(order[i])}의 인용문이 서명된 통합본의 각주와 다르다(같은 발췌 id에 다른 인용)")
            raise PairingConflict("통합본의 근거 각주가 서명된 각주 판과 다르다(같은 발췌 id에 다른 인용)")
    return "ok"


# 이름 → 검사. 순서대로 돌고, 변이 검사는 항목 하나를 바꿔 끈다(tests/e4/test_export_pairing.py).
PAIRING_CHECKS: dict[str, Callable[[PairingContext], CheckResult]] = {
    "session": check_session, "cards": check_cards, "evidence": check_evidence,
    "edits": check_edits, "decisions": check_decisions, "quotes": check_quotes,
}
RESULT_REVISION_CHECKS = ("session", "cards", "evidence")  # 미확인이면 수정 권고도 trusted 아님
ASSEMBLY_CHECKS = ("edits", "decisions", "quotes")  # 미확인이면 통합본이 trusted 아님


def revision_result_problem(result: Any, revision: Mapping[str, Any] | None) -> str | None:
    """수정 권고 → 결과 결합의 첫 모순 문구(없으면 None). 조립 API가 서명 전에 부른다(어긋난 결합에 서명하지 않는다)."""
    if result is None or not isinstance(revision, Mapping):
        return None
    try:
        res = result if isinstance(result, PremortemResult) else PremortemResult.model_validate(result)
    except Exception:  # noqa: BLE001 - 계약 위반은 서명 검증이 이미 False다
        return None
    ctx = PairingContext(res, revision, None, [], False)
    for name in RESULT_REVISION_CHECKS:
        try:
            PAIRING_CHECKS[name](ctx)
        except PairingConflict as exc:
            return str(exc)
        except PairingUnverifiable:
            continue
    return None


@dataclass
class Composition:
    """내보내기 한 번의 수정 권고·통합본 결합 판정. extra_files·summary_lines·manifest·헤더가 같은 판정을 쓴다."""

    revision: Mapping[str, Any] | None = None
    revised_plan: Mapping[str, Any] | None = None
    decided: list[RevisionDecision] = field(default_factory=list)
    revision_origin: str | None = None
    assembly_origin: str | None = None
    checks: dict[str, str] = field(default_factory=dict)
    qualifiers: list[str] = field(default_factory=list)
    label_model: str | None = None
    label_generator: str | None = UNVERIFIED

    @property
    def files(self) -> list[str]:
        return [name for name, present in ((REVISION_FILE, self.revision is not None), (REVISED_PLAN_FILE, self.revised_plan is not None))
                if present]

    def origin_of(self, name: str) -> str | None:
        return {REVISION_FILE: self.revision_origin, REVISED_PLAN_FILE: self.assembly_origin}.get(name)

    def metadata(self) -> dict[str, Any] | None:
        """manifest.json의 `composition`(덧붙인 파일이 없으면 null). 계약 밖 패키지 메타데이터다."""
        if self.revision is None and self.revised_plan is None:
            return None
        return {"revision_origin": self.revision_origin, "assembly_origin": self.assembly_origin,
                "checks": dict(self.checks), "qualifiers": list(self.qualifiers)}


def compose(
    result: PremortemResult | Mapping[str, Any] | None,
    revision: Mapping[str, Any] | None,
    decisions: Sequence[Mapping[str, Any] | RevisionDecision] | None,
    revised_plan: Mapping[str, Any] | None,
    revision_sig: Any = None,
    result_sig: Any = None,
) -> Composition:
    """계약·plan_id·edit_id 검사 → 서명 확인 → 결합 검증. 계약 위반·불일치·결합 모순은 ValueError(API 422)."""
    if revision is None and revised_plan is None:
        if decisions:
            raise ValueError("revision 없이 revision_decisions만 왔다")
        return Composition()
    if result is not None and not isinstance(result, PremortemResult):
        result = PremortemResult.model_validate(result)
    plan_id = result.plan_id if result is not None else None
    decided: list[RevisionDecision] = []
    if revision is not None:
        from neumann.analyze.revise import validate_revision

        errs = validate_revision(revision)
        if errs:
            raise ValueError("수정 권고가 계약(revision.schema.json)과 맞지 않는다: " + "; ".join(errs[:3]))
        if plan_id is not None and revision.get("plan_id") != plan_id:
            raise ValueError("수정 권고의 plan_id가 결과의 plan_id와 다르다")
        decided = validate_decisions(revision, decisions)
    elif decisions:
        raise ValueError("revision 없이 revision_decisions만 왔다")
    if revised_plan is not None:
        from neumann.analyze import assemble as asm

        errs = asm.validate_revised_plan(revised_plan)
        if errs:
            raise ValueError("통합본이 계약(revised_plan.schema.json)과 맞지 않는다: " + "; ".join(errs[:3]))
        if plan_id is not None and revised_plan.get("plan_id") != plan_id:
            raise ValueError("통합본의 plan_id가 결과의 plan_id와 다르다")

    sig = revision_sig if revision_sig is not None else (revision or {}).get("revision_sig")
    revision_signed = revision is not None and _origin(revision, sig, result, result_sig) == SERVER_SIGNED
    assembly_signed = revised_plan is not None and _assembly_signed(revised_plan)
    comp = Composition(revision=revision, revised_plan=revised_plan, decided=decided)
    unverified: set[str] = set()
    if result is not None:
        ctx = PairingContext(result, revision, revised_plan, decided, revision_signed and assembly_signed)
        for name, check in PAIRING_CHECKS.items():
            try:
                comp.checks[name] = check(ctx) or "ok"
            except PairingUnverifiable as exc:  # PairingConflict는 ValueError로 올라가 422가 된다
                comp.checks[name] = "unverified"
                comp.qualifiers.append(str(exc))
                unverified.add(name)
    else:  # 결과 없이 요약만 만드는 호출: 결합을 확인할 수 없다
        comp.checks = {name: "skipped" for name in PAIRING_CHECKS}
    if revision is not None:
        comp.revision_origin = SERVER_SIGNED if revision_signed and not (unverified & set(RESULT_REVISION_CHECKS)) else UNVERIFIED
    if revised_plan is not None:
        trusted = comp.revision_origin == SERVER_SIGNED and assembly_signed and not (unverified & set(ASSEMBLY_CHECKS))
        comp.assembly_origin = SERVER_SIGNED if trusted else UNVERIFIED
        if trusted:  # 서명된 다듬기 표기가 우선(api.revise.run_assembly의 라벨 규칙과 같다)
            pol = revised_plan.get("polish") if isinstance(revised_plan.get("polish"), Mapping) else {}
            model = (pol.get("model") if pol.get("applied") else None) or (revision or {}).get("model")
            gen = (pol.get("generator") if pol.get("applied") else None) or (revision or {}).get("generator")
            comp.label_model = model if isinstance(model, str) else None
            comp.label_generator = gen if isinstance(gen, str) else None
    return comp


# ── 파일·요약 ─────────────────────────────────────────────────────────────


def render_files(comp: Composition, result: PremortemResult) -> dict[str, bytes]:
    """덧붙일 파일 {이름: 바이트}. 판정(comp)은 compose()가 이미 끝냈다."""
    files: dict[str, bytes] = {}
    if comp.revision is not None:
        files[REVISION_FILE] = _json_bytes({
            "format": "neumann-package/1", "schema_version": SCHEMA_VERSION, "plan_id": result.plan_id,
            "origin": comp.revision_origin, "choices": DECISION_LABELS,
            "revision": {k: v for k, v in comp.revision.items() if k != "revision_sig"},
            "decisions": [d.model_dump(mode="json") for d in comp.decided],
        })
    if comp.revised_plan is not None:
        from neumann.analyze import assemble as asm

        rendered = asm.render_markdown(comp.revised_plan, asm.evidence_lookup(result, comp.revision),
                                      model=comp.label_model, generator=comp.label_generator)
        text = rendered["footnoted"].rstrip("\n") + "\n\n" + rendered["history"]
        files[REVISED_PLAN_FILE] = text.encode("utf-8")
    return files


def extra_files(
    result: PremortemResult,
    revision: Mapping[str, Any] | None,
    decisions: Sequence[Mapping[str, Any] | RevisionDecision] | None,
    revised_plan: Mapping[str, Any] | None,
    revision_sig: Any = None,
    result_sig: Any = None,
) -> dict[str, bytes]:
    """덧붙일 파일 {이름: 바이트}. 계약 위반·plan_id 불일치·없는 edit_id·결합 모순은 ValueError."""
    return render_files(compose(result, revision, decisions, revised_plan, revision_sig, result_sig), result)


def summary_of(comp: Composition) -> list[str]:
    """README의 '수정 권고(E3-L2r)' 절: 파일별 출처 + 결합 검증 결과(같은 판정)."""
    out: list[str] = []
    if comp.revision is not None:
        revision = comp.revision
        revs = _maps(revision.get("revisions"))
        n_edits = sum(len(r.get("edits", []) or []) for r in revs)
        n_prec = sum(1 for r in revs if (r.get("precedents") or {}).get("status") == "found")
        audit = revision.get("audit", {}) or {}
        if comp.revision_origin == SERVER_SIGNED:
            generation = f"생성 {revision.get('generator')}" + (f"({revision.get('model')})" if revision.get("model") else "")
        else:
            generation = "생성 표기 미확인(서버가 생성 방식·모델을 확인하지 않음)"
        out.append(f"- 수정 권고(`{REVISION_FILE}`): 카드 {len(revs)}장 · 수정안 {n_edits}건 · 채택 연구 대응 {n_prec}장 · "
                   f"근거 게이트 폐기 {audit.get('dropped', 0)}건 · {generation} · 결정 {len(comp.decided)}건"
                   f" · 수정 권고 출처: {comp.revision_origin}")
    if comp.revised_plan is not None:
        st = comp.revised_plan.get("stats", {}) or {}
        pol = comp.revised_plan.get("polish", {}) or {}
        out.append(f"- 통합본(`{REVISED_PLAN_FILE}`): 적용 {st.get('applied', 0)}건 · 충돌 {st.get('conflicts', 0)}건 · "
                   f"자리표시 {st.get('placeholders', 0)}곳 · 다듬기 {'적용' if pol.get('applied') else '미적용'}"
                   f" · 통합본 출처: {comp.assembly_origin}")
    if comp.checks:
        out.append("- 결합 검증: " + " · ".join(f"{CHECK_LABELS.get(k, k)} {STATE_LABELS.get(v, v)}" for k, v in comp.checks.items())
                   + " — 서명은 객체 하나의 무결성이고, 결과·수정 권고·통합본·결정이 같은 분석의 것인지는 이 검증이 본다")
    if comp.qualifiers:
        out.append("- 결합 미확인 사유(해당 파일은 server_signed로 적지 않는다): " + " / ".join(comp.qualifiers))
    return out


def summary_lines(revision: Mapping[str, Any] | None, decisions: Sequence[Any] | None,
                  revised_plan: Mapping[str, Any] | None, *, result: Any = None,
                  revision_sig: Any = None, result_sig: Any = None) -> list[str]:
    """README 요약(단독 호출용). export.py는 compose() 한 번의 판정을 summary_of()에 넘긴다."""
    return summary_of(compose(result, revision, decisions, revised_plan, revision_sig, result_sig))


__all__ = ["ASSEMBLY_CHECKS", "CHECK_LABELS", "Composition", "DECISION_LABELS", "FILE_ROLES", "PAIRING_CHECKS", "PairingConflict",
           "PairingContext", "PairingUnverifiable", "RESULT_REVISION_CHECKS", "REVISED_PLAN_FILE", "REVISION_FILE",
           "RevisionDecision", "SERVER_SIGNED", "UNVERIFIED", "compose", "edit_ids_of", "extra_files", "render_files",
           "revision_result_problem", "summary_lines", "summary_of", "validate_decisions"]
