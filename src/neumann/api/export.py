"""내보내기 패키지(ZIP 9파일). 계획서 §2 TRACE, §3 L2, §4 E4 L2.

    from neumann.api.export import build_package, router
    data = build_package(result, plan_text=None)   # ZIP 바이트
    app.include_router(router)                     # POST /premortem/package

파일 9개(이 순서로 ZIP에 들어간다): README.md, manifest.json, risk_cards.json, evidence_pack.json,
similar_works.csv, plan_annotated.md, neumann_report.md, ai_context.md, decision_log.json.

원칙
- 결정적: 같은 입력이면 manifest.json의 `created_at`(패키지 생성 시각)만 빼고 모든 파일이 바이트 단위로 같다.
  ZIP 항목 시각은 결과의 `generated_at`으로 고정한다. `created_at`을 넘기면 ZIP 전체가 같다.
- 정직: 카드별 `generator`(astra·rule·mock)와 강등 단계(degraded·error·skipped)를 README·리포트에 그대로 적는다.
  사람이 읽는 문서에는 표시 이름(`view.display_generator`: LLM (모델명)·비상 규칙·모의(mock))으로 적고,
  JSON 값(`generator: "astra"`)은 계약대로 둔다(DISP-1).
  규칙 카드를 LLM 결과라고 쓰지 않는다. 카드가 0장이면 결과에 적힌 사유를 옮기고, 없으면 "사유 없음"이라고 쓴다.
- 인용: `evidence`의 text를 가공 없이 옮긴다. 패키지는 원문을 다시 받지 않으므로 재대조 상태는 `not_reverified`다.
- 개인정보: 계획서 줄은 `PlanDocument` 규칙(NFC+LF, 이메일·ORCID 가림)을 거친 줄만 쓴다. 설정·환경변수는 읽지 않는다.
- 출처(E4-L2f F1): API로 받은 결과는 서버 서명(`result_sig`, `neumann.api.signing`)을 확인한다. 확인되면
  `result_origin: "server_signed"`, 아니면 `"client_submitted_unverified"`(README 첫 줄 경고, "제품 LLM이 만든"·
  "오프셋으로 자른" 같은 서버 보증 문구를 쓰지 않는다). 파이썬에서 직접 부르면 `"in_process"`(호출한 코드가 가진 결과).
- 서식 안전(F4): 마크다운 파일에 옮기는 결과 문자열의 `& < >`는 HTML 엔티티로 바꾸고(글자 그대로의 인용은
  `evidence_pack.json`), 코드 스팬 안 id의 백틱은 뺀다. CSV 문자열 칸이 `= + - @`·탭·CR로 시작하면 앞에 `'`를 붙인다.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import logging
import re
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from neumann.analyze.checklist import gate_checklist_items
from neumann.analyze.gate import EvidenceIndex, MALFORMED, NO_EVIDENCE_FAMILY, SECTIONS, review_evidence_problem
from neumann.api.view import display_generator, display_text
from neumann.api.plan_limits import check_embedded_plan, check_payload_plan
from neumann.api import export_revision  # E3-L2r: ZIP에 덧붙이는 수정 권고·통합본 파일(선택)
from neumann.models import (
    SCHEMA_VERSION,
    Excerpt,
    Generator,
    NeumannModel,
    PlanDocument,
    PremortemResult,
    RiskCard,
    StageStatus,
    redact_pii,
)

logger = logging.getLogger(__name__)

PACKAGE_FORMAT = "neumann-package/1"
MAX_PLAN_CHARS = 1_000_000
MAX_PACKAGE_CARDS = 100
MAX_PACKAGE_CARD_LINES = 200
MAX_PACKAGE_DECISIONS = 1_000
# B2: 요청 JSON 중첩 상한. 정상 결과·수정 권고는 10단 안팎이다. 더 깊으면 조립·렌더링 전에 422로 거절한다
# (깊은 중첩이 JSON 직렬화의 RecursionError → 500이 되지 않게).
MAX_PACKAGE_JSON_DEPTH = 64

# B2: 예상 심사평 audit 필드 형태. 알려진 필드만 형태를 확인해 싣는다. 형태가 틀리거나 모르는 필드는
# 값을 버리고 이름만 audit.dropped_keys에 남긴다(500·원문 유출 없이 내보내기는 계속한다).
AUDIT_MAX_COUNT = 1_000_000_000
AUDIT_MAX_TEXT_CHARS = 500
AUDIT_MAX_CODES = 64
AUDIT_MAX_CODE_CHARS = 64
AUDIT_MAX_DROPPED_KEYS = 32
_AUDIT_COUNT_KEYS = frozenset({"gen", "pass", "drop", "no_evidence", "generated", "passed"})
_AUDIT_TEXT_KEYS = frozenset({"gate", "note", "dropped_text"})
_AUDIT_CODE_MAPS = frozenset({"dropped_reasons", "reasons"})
_AUDIT_CODE_LISTS = frozenset({"no_evidence_reasons", "dropped_keys"})
_AUDIT_STRIPPED = frozenset({"dropped", "dropped_detail"})  # 뺀 문장 원문: 리포트에 싣지 않는다(사유 코드·개수만)
_AUDIT_CODE_RE = re.compile(r"[A-Za-z0-9_.:@-]{1,%d}" % AUDIT_MAX_CODE_CHARS)

FILE_NAMES: tuple[str, ...] = (
    "README.md",
    "manifest.json",
    "risk_cards.json",
    "evidence_pack.json",
    "similar_works.csv",
    "plan_annotated.md",
    "neumann_report.md",
    "ai_context.md",
    "decision_log.json",
)

FILE_ROLES: dict[str, str] = {
    "README.md": "이 안내문: 무엇이 들었나, 생성 방식, 강등 단계",
    "manifest.json": "파일별 sha256·크기, 생성 시각, 스키마 버전, 생성 방식별 카드 수",
    "risk_cards.json": "위험카드 원자료(계약 RiskCard 그대로)",
    "evidence_pack.json": "카드별 근거 인용·원문 URL·오프셋·해시",
    "similar_works.csv": "유사 연구 목록(UTF-8 BOM, 엑셀에서 바로 열림)",
    "plan_annotated.md": "계획서 줄 번호 옆에 연결된 카드 표시",
    "neumann_report.md": "사람이 읽는 리포트",
    "ai_context.md": "다른 AI에 넘길 요약: 카드·근거 id·한계",
    "decision_log.json": "카드·행동별 채택·보류·기각 기록(없으면 빈 목록)",
}

GENERATOR_LABELS: dict[Generator, str] = {
    Generator.astra: "제품 LLM(OpenAI, 모델은 manifest 참조)이 만든 카드",
    Generator.rule: "규칙(비상 경로: 키워드 태거·태그 빈도)으로 만든 카드. LLM 결과가 아니다",
    Generator.mock: "테스트용 가짜(mock). 실제 분석 결과가 아니다",
}
GENERATOR_SHORT: dict[Generator, str] = {g: display_generator(g.value) for g in Generator}  # 모델명 없는 표시 이름
# JSON 값에 대한 설명 한 줄(DISP-1). README·ai_context에만 싣는다. 사람용 문서에서 astra 글자는 이 줄과
# 리포트의 예상 심사평 JSON 코드 블록(결과 값 그대로)에만 나온다.
JSON_GENERATOR_NOTE = (
    "JSON 값 `generator: \"astra\"`는 계약 이름(제품 LLM)이고 모델명이 아니다. "
    "실제 모델은 `model`(카드·예상 심사평·체크리스트)에 있다."
)
# 서명 확인 안 된 결과(E4-L2f F1)에는 계약 이름 설명 대신 이 줄을 싣는다: 값이 무엇을 뜻하는지 서버가 보증하지 않는다.
JSON_GENERATOR_NOTE_UNVERIFIED = (
    "JSON 값 `generator`·`model`은 요청자가 보낸 결과에 적힌 표기다. 서버 서명이 없어 확인하지 못했다."
)

SOURCE_KIND_KO: dict[str, str] = {
    "review": "심사평",
    "author_response": "저자 답변",
    "decision": "결정",
    "post_status": "사후 상태",
}

NOT_OK_STATES = ("degraded", "error", "skipped")

# ── 결과 출처(서버 서명) ──────────────────────────────────────────────────

ResultOrigin = Literal["server_signed", "client_submitted_unverified", "in_process"]
RESULT_ORIGINS: tuple[str, ...] = ("server_signed", "client_submitted_unverified", "in_process")
ORIGIN_LABELS: dict[str, str] = {
    "server_signed": "이 서버가 분석해 서명한 결과(서명 확인됨)",
    "client_submitted_unverified": "요청자가 보낸 결과(서버 서명 확인 안 됨: 서명 없음·변조·서버 재기동)",
    "in_process": "서버 프로세스 안에서 직접 호출해 묶은 결과(API를 거치지 않음)",
}
UNVERIFIED_WARNING = (
    "**주의: 서버가 분석·서명한 결과가 아님.** 이 패키지의 결과 JSON은 요청자가 보낸 값이고 Neumann 서버의 서명을 "
    "확인하지 못했다(서명 없음·변조·서버 재기동). 위험카드의 생성 방식(generator)·인용문·점수는 보낸 값을 그대로 옮긴 것이며 "
    "서버가 검증하지 않았다."
)

# ── 결정 로그 ─────────────────────────────────────────────────────────────

DecisionChoice = Literal["adopt", "hold", "reject"]
DECISION_LABELS: dict[str, str] = {"adopt": "채택", "hold": "보류", "reject": "기각"}
_DECISION_ALIASES: dict[str, str] = {v: k for k, v in DECISION_LABELS.items()}


class DecisionEntry(NeumannModel):
    """카드(또는 체크리스트 행동) 하나에 대한 연구자의 결정(채택·보류·기각).

    `card_id`·`item_id` 중 하나 이상. `item_id`는 결과 `checklist` 항목의 id(목업은 행동 단위로 결정을 받는다).
    신원 필드는 둘 수 없다(NeumannModel이 막는다).
    """

    card_id: str | None = Field(default=None, min_length=1)
    item_id: str | None = Field(default=None, min_length=1, description="체크리스트 행동 id")
    decision: DecisionChoice
    note: str | None = Field(default=None, max_length=2000, description="메모. 이메일·ORCID는 가린다")
    decided_at: datetime | None = None

    @field_validator("decision", mode="before")
    @classmethod
    def _accept_korean(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return _DECISION_ALIASES.get(v, v.lower())
        return v

    @field_validator("note")
    @classmethod
    def _mask(cls, v: str | None) -> str | None:
        return None if v is None else redact_pii(v)

    @field_validator("decided_at")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("timezone-aware datetime만 허용한다")
        return v

    @model_validator(mode="after")
    def _target(self) -> DecisionEntry:
        if not (self.card_id or self.item_id):
            raise ValueError("card_id와 item_id 중 하나는 있어야 한다")
        return self

    @property
    def target(self) -> str:
        parts = []
        if self.card_id:
            parts.append(f"카드 `{_code(self.card_id)}`")
        if self.item_id:
            parts.append(f"행동 `{_code(self.item_id)}`")
        return " · ".join(parts)


CHECKLIST_ID_KEYS = ("id", "item_id", "action_id")


def _checklist_ids(checklist: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(item[k]) for item in checklist for k in CHECKLIST_ID_KEYS if item.get(k) is not None}


def _audit_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= AUDIT_MAX_COUNT


def _audit_code(value: Any) -> bool:
    return isinstance(value, str) and _AUDIT_CODE_RE.fullmatch(value) is not None


def _audit_value_ok(key: str, value: Any) -> bool:
    """알려진 audit 필드의 형태. 모르는 필드는 False(값을 싣지 않는다)."""
    if key in _AUDIT_COUNT_KEYS:
        return _audit_count(value)
    if key in _AUDIT_TEXT_KEYS:
        return isinstance(value, str) and len(value) <= AUDIT_MAX_TEXT_CHARS
    if key in _AUDIT_CODE_MAPS:
        return (isinstance(value, Mapping) and len(value) <= AUDIT_MAX_CODES
                and all(_audit_code(k) and _audit_count(n) for k, n in value.items()))
    if key in _AUDIT_CODE_LISTS:
        limit = AUDIT_MAX_DROPPED_KEYS if key == "dropped_keys" else AUDIT_MAX_CODES
        return isinstance(value, list) and len(value) <= limit and all(_audit_code(x) for x in value)
    if key == "linked_rate":
        return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)
                                 and 0 <= value <= 1)  # NaN·inf는 비교가 거짓이라 걸러진다
    return False


def _audit_key_name(key: Any) -> str:
    """버린 필드의 이름만(값 없음). 코드 모양이 아니면 개인정보 가림 뒤 코드 글자만 남긴다."""
    name = key if isinstance(key, str) else type(key).__name__
    if not _audit_code(name):
        name = re.sub(r"[^A-Za-z0-9_.:@-]+", "_", redact_pii(name))[:AUDIT_MAX_CODE_CHARS].strip("_") or "_"
    return name


def _sanitize_audit(raw_audit: Any) -> tuple[dict[str, Any], list[str]]:
    """B2: audit 필드마다 형태를 확인한다 → (실을 audit, 새로 버린 필드 이름).

    audit 자체가 객체가 아니면 ValueError(→ 422). 뺀 문장 원문(dropped·dropped_detail)은 싣지 않고,
    dropped의 [사유 코드, 문장] 쌍에서 사유 코드 개수만 센다. 그 밖의 형태 오류·모르는 필드는 이름만 남긴다.
    """
    if raw_audit is not None and not isinstance(raw_audit, Mapping):
        raise ValueError("expected_review.audit는 JSON 객체여야 합니다.")
    audit: dict[str, Any] = {}
    bad: set[str] = set()
    drops: list[str] = []
    for key, value in (raw_audit or {}).items():
        if key == "dropped":
            items = value if isinstance(value, list) else None
            if items is None and value is not None:
                bad.add("dropped")
            for d in items or ():
                if isinstance(d, (list, tuple)) and d and _audit_code(d[0]):
                    drops.append(d[0])
                elif d:  # 코드 모양이 아닌 항목은 세지 않는다(값은 싣지 않는다)
                    bad.add("dropped")
        elif key == "dropped_detail":
            continue  # 원문 기록: 형태와 관계없이 싣지 않는다
        elif isinstance(key, str) and _audit_value_ok(key, value):
            audit[key] = dict(value) if isinstance(value, Mapping) else (list(value) if isinstance(value, list) else value)
        else:
            bad.add(_audit_key_name(key))
    if drops or "drop" in audit:
        codes: Counter[str] = Counter(audit.get("dropped_reasons") or {})
        codes.update(drops)
        if len(codes) <= AUDIT_MAX_CODES and all(_audit_count(n) for n in codes.values()):
            audit["dropped_reasons"] = dict(codes)
        else:
            audit.pop("dropped_reasons", None)
            bad.add("dropped_reasons")
        audit["dropped_text"] = "제외한 문장 원문은 싣지 않음(분석 결과 아님) — 사유 코드·개수만"
    new = sorted(bad)
    if new:
        merged = sorted(set(audit.get("dropped_keys") or ()) | set(new))
        audit["dropped_keys"] = merged[:AUDIT_MAX_DROPPED_KEYS]
    return audit, new


def _review_for_report_with_drops(er: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    out = dict(er)
    audit, dropped_keys = _sanitize_audit(out.get("audit"))
    out["audit"] = audit
    return out, dropped_keys


def _review_for_report(er: Mapping[str, Any]) -> dict[str, Any]:
    """리포트에 싣는 예상 심사평(E3-L1e): 게이트가 뺀 문장 원문(audit.dropped·dropped_detail)은 빼고 사유 코드·개수만 남긴다.
    뺀 문장은 분석 결과가 아니므로 라벨 없이 문서에 나가지 않게 한다. 결과 JSON 원본은 바꾸지 않는다.
    B2: audit 필드는 형태를 확인한 것만 싣고, 틀린 형태·모르는 필드는 이름만 audit.dropped_keys에 남긴다."""
    return _review_for_report_with_drops(er)[0]


def _checklist_line(item: Mapping[str, Any]) -> str:
    """체크리스트 항목 한 줄. 키 이름은 E3 형식(text·risk_code·card_id·plan_lines)과 목업 형식(t·r·s·m)을 모두 읽는다."""
    text = item.get("text") or item.get("action") or item.get("t")
    if not text:
        return _one_line(json.dumps(item, ensure_ascii=False))
    item_id = next((item[k] for k in CHECKLIST_ID_KEYS if item.get(k) is not None), None)
    meta = []
    if item.get("risk_code") or item.get("r"):
        meta.append(str(item.get("risk_code") or item.get("r")))
    if item.get("card_id"):
        meta.append(f"카드 {item['card_id']}")
    if item.get("plan_lines"):
        meta.append("계획서 줄 " + ", ".join(str(n) for n in item["plan_lines"]))
    if item.get("generator"):
        meta.append(f"생성 {display_generator(item['generator'], item.get('model'))}")
    line = (f"[{_one_line(item_id)}] " if item_id is not None else "") + _one_line(text)
    if meta:
        line += f" ({_one_line(' · '.join(meta))})"
    status = item.get("decision") or item.get("s")
    if status:
        line += f" — 결정: {_one_line(status)}"
    memo = item.get("note") or item.get("m")
    if memo:
        line += f" — {_one_line(memo)}"
    return line


# ── 조립 문맥 ─────────────────────────────────────────────────────────────


@dataclass
class _Ctx:
    result: PremortemResult
    plan: PlanDocument | None
    plan_source: str
    refs: list[tuple[str, RiskCard]]
    ex_by_id: dict[str, Excerpt]
    gen_counts: dict[str, int]
    not_ok_stages: list[StageStatus]
    decisions: list[DecisionEntry]
    warnings: list[str] = field(default_factory=list)
    origin: str = "in_process"
    extra_files: list[str] = field(default_factory=list)  # E3-L2r: 덧붙인 파일 이름(revision.json·revised_plan.md)
    extra_summary: list[str] = field(default_factory=list)

    @property
    def n_cards(self) -> int:
        return len(self.refs)

    @property
    def verified(self) -> bool:
        """서버가 만든 결과라고 말할 수 있는지(서명 확인 또는 프로세스 안 직접 호출)."""
        return self.origin != "client_submitted_unverified"

    @property
    def plan_association(self) -> str:
        return _plan_association(self.plan, self.plan_source, self.origin)

    @property
    def plan_verified(self) -> bool:
        return self.plan_association in {"signed_result_plan", "hash_verified"}


def _resolve_plan(result: PremortemResult, plan_text: str | None) -> tuple[PlanDocument | None, str]:
    """External text may supply a missing body only when its canonical hash matches."""
    if result.plan is not None:
        return result.plan, "result.plan (plan_text는 쓰지 않음)" if plan_text else "result.plan"
    if plan_text is not None and plan_text.strip():
        plan = PlanDocument.from_text(plan_text, result.session_id)
        if plan.plan_id != result.plan_id:
            raise ValueError("계획서 본문 해시가 분석 결과의 plan_id와 맞지 않아 내보낼 수 없습니다.")
        return plan, "plan_text (이메일·ORCID 가림, 결과 plan_id와 해시 일치)"
    return None, "none"


def _plan_association(plan: PlanDocument | None, source: str, origin: str) -> str:
    if plan is None:
        return "missing"
    if origin != "server_signed":
        return "unverified"  # 직접 호출(in_process)도 서버 HMAC 검증을 주장하지 않는다.
    return "signed_result_plan" if source.startswith("result.plan") else "hash_verified"


def _plan_metadata(c: _Ctx) -> dict[str, Any]:
    return {"plan_association": c.plan_association, "plan_verified": c.plan_verified}


def _plan_authority_text(c: _Ctx) -> str:
    explanation = {
        "signed_result_plan": "결과 JSON 안의 계획서 본문이 서버 서명 범위에 포함된다.",
        "hash_verified": "보조 본문을 정규화·마스킹한 해시가 서버 서명된 결과의 plan_id와 일치한다.",
        "missing": "계획서 본문 없음. 계획서 본문을 서버 검증된 입력으로 보증하지 않는다.",
        "unverified": "계획서 본문을 서버 검증된 입력으로 보증하지 않는다. 결과의 plan_id와 일치는 서버 출처 보증이 아니다.",
    }[c.plan_association]
    return (f"계획서 연결 상태: `{c.plan_association}` — {explanation}\n"
            "결과 서명은 결과 JSON에만 적용되며 패키지 전체나 새 외부 입력을 서명한 것이 아니다.")


def _gate_export_result(result: PremortemResult) -> tuple[PremortemResult, list[str]]:
    """공용 조립 문맥 전에 저장 결과를 다시 검사한다. 원본 수정·규칙 대체 없이 사유 코드와 수만 남긴다."""
    index = EvidenceIndex(result)
    items, item_drops = gate_checklist_items(result.checklist, result, index=index, where="export")
    review, audit_dropped_keys = (_review_for_report_with_drops(result.expected_review) if result.expected_review
                                  else ({}, []))
    reasons: Counter[str] = Counter()
    shown = 0
    for section in SECTIONS:
        kept = []
        raw = review.get(section, [])
        if not isinstance(raw, list):
            reasons[MALFORMED] += 1
            raw = []
        for sentence in raw:
            reason = review_evidence_problem(sentence, index)[0] if isinstance(sentence, Mapping) else MALFORMED
            if reason is not None:
                reasons[reason] += 1
            else:
                kept.append(sentence)
        if review:
            review[section] = kept
        shown += len(kept)
    if review and reasons:
        audit = dict(review.get("audit") or {})
        prior = Counter(audit.get("dropped_reasons") or {})
        prior.update(reasons)
        n = sum(reasons.values())
        dropped_total = int(audit.get("drop") or 0) + n
        audit.update({"gen": shown + dropped_total, "pass": shown, "drop": dropped_total,
                      "no_evidence": int(audit.get("no_evidence") or 0) + sum(v for k, v in reasons.items() if k in NO_EVIDENCE_FAMILY),
                      "dropped_reasons": dict(sorted(prior.items())),
                      "dropped_text": "제외한 문장 원문은 싣지 않음(분석 결과 아님) — 사유 코드·개수만"})
        review["audit"] = audit
    warnings = []
    if reasons or item_drops:
        codes = Counter(d["reason"] for d in item_drops)
        codes.update(reasons)
        warnings.append(f"내보내기 근거 게이트: 심사평 {sum(reasons.values())}문장·체크리스트 {len(item_drops)}항목 제외 "
                        f"(분석 결과 아님). 사유 코드·개수: {json.dumps(dict(sorted(codes.items())), ensure_ascii=False)}")
    if audit_dropped_keys:
        warnings.append(f"예상 심사평 audit: 형식이 맞지 않거나 알 수 없는 필드 {len(audit_dropped_keys)}개를 값 없이 제외 "
                        "(이름만 audit.dropped_keys에 기록).")
    return result.model_copy(update={"expected_review": review, "checklist": items}), warnings


def _make_ctx(
    result: PremortemResult,
    plan_text: str | None,
    decisions: Sequence[DecisionEntry | Mapping[str, Any]] | None,
    origin: str = "in_process",
) -> _Ctx:
    if origin not in RESULT_ORIGINS:
        raise ValueError(f"result_origin은 {RESULT_ORIGINS} 중 하나다")
    original_item_ids = _checklist_ids(result.checklist)
    result, warnings = _gate_export_result(result)
    plan, plan_source = _resolve_plan(result, plan_text)

    refs = [(f"C{i}", card) for i, card in enumerate(result.risk_cards, start=1)]
    if plan is not None:
        n_lines = len(plan.lines)
        for ref, card in refs:
            bad = [n for n in card.why_applies.plan_lines if n > n_lines]
            if bad:
                warnings.append(f"{ref} `{_code(card.card_id)}`가 계획서에 없는 줄 {bad}을 가리킨다(계획서 {n_lines}줄).")

    gen_counts = {g.value: 0 for g in Generator}
    for card in result.risk_cards:
        gen_counts[card.generator.value] += 1

    card_ids = {card.card_id for card in result.risk_cards}
    item_ids = _checklist_ids(result.checklist)
    entries: list[DecisionEntry] = []
    for raw in decisions or ():
        entry = raw if isinstance(raw, DecisionEntry) else DecisionEntry.model_validate(raw)
        if entry.card_id is not None and entry.card_id not in card_ids:
            raise ValueError(f"결정 로그의 card_id {entry.card_id!r}가 결과의 카드에 없다")
        if entry.item_id is not None and entry.item_id not in original_item_ids:
            raise ValueError(f"결정 로그의 item_id {entry.item_id!r}가 결과의 체크리스트에 없다")
        if entry.item_id is not None and entry.item_id not in item_ids:
            warnings.append("내보내기 근거 게이트: 제외된 체크리스트 항목의 결정 기록 1개 제외(분석 결과 아님).")
            continue
        entries.append(entry)

    return _Ctx(
        result=result,
        plan=plan,
        plan_source=plan_source,
        refs=refs,
        ex_by_id={ex.excerpt_id: ex for ex in result.evidence},
        gen_counts=gen_counts,
        not_ok_stages=[s for s in result.stages if s.state in NOT_OK_STATES],
        decisions=entries,
        warnings=warnings,
        origin=origin,
    )


# ── 서식 헬퍼 ─────────────────────────────────────────────────────────────


def _utc_date(dt: datetime) -> datetime:
    try:
        return dt.astimezone(UTC)
    except (OverflowError, ValueError):
        raise ValueError("날짜를 UTC로 표현할 수 없어 내보낼 수 없습니다.") from None


def _zip_date(dt: datetime) -> tuple[int, int, int, int, int, int]:
    ts = _utc_date(dt)
    if not 1980 <= ts.year <= 2107:
        raise ValueError("ZIP 날짜는 UTC 기준 1980년부터 2107년까지 지원합니다.")
    return ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second


def _iso(dt: datetime) -> str:
    return _utc_date(dt).isoformat().replace("+00:00", "Z")


def _md_escape(text: str) -> str:
    """마크다운 파일에 옮기는 결과 문자열을 무력화한다(E4-L2f F4·R4). 렌더하면 같은 글자로 보인다.

    - HTML: ``& < >`` → 엔티티(태그·자동 링크 ``<http…>`` 불가).
    - 링크·이미지 문법: 백슬래시를 먼저 두 배로 하고, 대괄호 앞에 백슬래시를 붙인다(이미지·링크·참조 정의 문법 불가 →
      원격 이미지를 불러올 수 없다).
    """
    t = text.replace("\\", "\\\\")
    t = html.escape(t, quote=False)
    return t.replace("[", "\\[").replace("]", "\\]")


def _one_line(text: Any) -> str:
    """마크다운 한 줄용: 개인정보 가림 + 줄바꿈·연속 공백을 한 칸으로 + HTML 이스케이프."""
    return _md_escape(re.sub(r"\s+", " ", redact_pii(str(text))).strip())


def _code(text: Any) -> str:
    """코드 스팬(`…`) 안에 넣을 id: 백틱·줄바꿈을 빼서 스팬을 깨고 나오지 못하게 한다."""
    return re.sub(r"[`\r\n]+", "", str(text))


def _url(url: str) -> str:
    """자동 링크(<…>)로 쓸 수 있는 http(s) URL만 링크로, 아니면 이스케이프한 글자로."""
    return f"<{url}>" if re.fullmatch(r"https?://[^\s<>`]+", url) else _one_line(url)


def _csv(text: Any) -> str:
    """CSV 수식 주입 방지(F4): = + - @ 탭 CR로 시작하는 문자열 칸 앞에 ' 를 붙인다."""
    s = "" if text is None else str(text)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _json_md(obj: Any) -> str:
    """마크다운 안 JSON: < > & 를 \\u 이스케이프(디코드하면 같은 값, 렌더러가 HTML로 읽지 않는다)."""
    return (json.dumps(obj, ensure_ascii=False, indent=2)
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))


def _cell(text: Any) -> str:
    return _one_line(text).replace("|", "\\|")


def _json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _md_bytes(lines: list[str]) -> bytes:
    out: list[str] = []
    for ln in lines:
        if ln == "" and out and out[-1] == "":
            continue  # 빈 줄 연속은 하나로(코드 블록 안 계획서 줄은 번호가 붙어 비지 않는다)
        out.append(ln)
    return ("\n".join(out).rstrip("\n") + "\n").encode("utf-8")


def _risk_label(card: RiskCard) -> str:
    code = card.subcode or card.risk_code.value
    return f"{code} {card.risk_code.title_ko}"


def _result_model(r: PremortemResult) -> str | None:
    """결과 manifest의 LLM 모델(카드에 모델이 없을 때만 쓴다)."""
    m = r.manifest or {}
    return next((str(m[k]) for k in ("model_id", "model", "llm_model") if m.get(k)), None)


UNVERIFIED_GEN_NOTE = "결과에 적힌 표기, 미확인"


def _unverified_name(g: Generator) -> str:
    """서명 확인 안 된 결과의 생성 방식 이름: "LLM(결과에 적힌 표기, 미확인)"처럼 표기만 옮긴다(모델명 없음)."""
    base = display_generator(g.value)
    return f"{base[:-1]}, {UNVERIFIED_GEN_NOTE})" if base.endswith(")") else f"{base}({UNVERIFIED_GEN_NOTE})"


def _gen_name(c: _Ctx, g: Generator) -> str:
    """결과 전체의 생성 방식 이름(DISP-1). LLM이면 카드들의 모델(여럿이면 모두), 없으면 manifest 모델.

    LLM 카드가 0장이면 모델명을 붙이지 않는다("LLM 0장"). 쓰이지 않은 모델을 적지 않기 위해서다.
    """
    if g is not Generator.astra or not c.gen_counts[g.value]:
        return display_generator(g.value)
    models = list(dict.fromkeys(card.model for _ref, card in c.refs if card.generator is g and card.model))
    return display_generator(g.value, ", ".join(models) or _result_model(c.result))


def _gen_short(c: _Ctx, g: Generator) -> str:
    """결과 전체의 생성 방식 이름(마크다운용, 이스케이프됨). 서명 확인·직접 호출이면 DISP-1 이름, 미확인이면 표기만."""
    return _one_line(_gen_name(c, g) if c.verified else _unverified_name(g))


def _gen_desc(c: _Ctx, g: Generator) -> str:
    if c.verified:
        return GENERATOR_LABELS[g]
    return "결과에 적힌 생성 방식 표기일 뿐이다. 서버 서명이 없어 누가 어떻게 만들었는지 확인하지 못했다"


def _gen_label(c: _Ctx, card: RiskCard) -> str:
    """카드 생성 방식(마크다운용, 이스케이프됨). LLM 카드는 "LLM (모델명)", 규칙·mock은 모델을 붙이지 않는다.
    서명 확인 안 된 결과는 모델명 없이 "LLM(결과에 적힌 표기, 미확인)"."""
    if not c.verified:
        return _one_line(_unverified_name(card.generator))
    return _one_line(display_generator(card.generator.value, card.model or _result_model(c.result)))


def _gen_summary(c: _Ctx) -> str:
    return " · ".join(f"{_gen_short(c, g)} {c.gen_counts[g.value]}장" for g in Generator)


def _stage_line(s: StageStatus) -> str:
    text = f"{_one_line(s.stage)}: {s.state}"
    if s.detail:
        text += f" — {_one_line(display_text(s.detail))}"
    return text


def _zero_card_reasons(c: _Ctx) -> list[str]:
    """카드 0장 사유. 결과에 적힌 것만 옮긴다(지어내지 않는다)."""
    reasons: list[str] = []
    if c.result.status == "error":
        reasons.append("분석이 오류로 끝났다(status=error).")
    reasons.extend(f"단계 {_stage_line(s)}" for s in c.not_ok_stages)
    reasons.extend(_one_line(display_text(n)) for n in c.result.notices)
    if not reasons:
        reasons.append("파이프라인이 근거가 연결된 위험을 찾지 못했다. 결과에 따로 적힌 사유는 없다.")
    return reasons


def _status_suffix(c: _Ctx) -> str:
    if c.not_ok_stages:
        return f" — 정상이 아닌 단계 {len(c.not_ok_stages)}개(아래 '강등 단계')"
    if c.result.status != "ok":
        return " — 단계 기록 없이 상태만 강등됨"
    return " — 강등된 단계 없음"


def _plan_line_text(c: _Ctx, no: int) -> str | None:
    if c.plan is None or not (1 <= no <= len(c.plan.lines)):
        return None
    return _one_line(c.plan.line(no))


def _quote_block(text: str, indent: str = "") -> list[str]:
    return [f"{indent}> {_md_escape(ln)}" if ln else f"{indent}>" for ln in text.split("\n")]


def _excerpt_ref(ex: Excerpt) -> str:
    kind = SOURCE_KIND_KO.get(ex.source_kind, ex.source_kind)
    return f"{kind} `{_code(ex.source_id)}` [{ex.start}:{ex.end}] · {_url(ex.source_url)} · `{_code(ex.excerpt_id)}`"


def _limitations(c: _Ctx) -> list[str]:
    quote_line = (
        "- 인용문은 분석 시점에 원문을 오프셋으로 잘라 옮긴 것이다. 이 패키지는 원문을 다시 받아 대조하지 않았다"
        "(`evidence_pack.json`의 `reverification`)."
        if c.verified else
        "- 인용문은 요청자가 보낸 결과의 text 값이다. 원문에서 잘라 온 것인지 서버가 확인하지 않았다"
        "(`evidence_pack.json`의 `reverification`)."
    )
    lines = [
        f"- 결과 출처: `{c.origin}` — {ORIGIN_LABELS[c.origin]}.",
        quote_line,
        "- 위험카드는 비슷한 연구가 받은 심사 기록에서 찾은 **가능성**이다. 이 계획서의 결함이 확정됐다는 뜻이 아니다.",
        f"- 계획서 본문 출처: {c.plan_source}. 계획서 줄은 이메일·ORCID를 가린 뒤 담는다.",
        "- 설정·API 키·환경변수 값은 담지 않는다. 리뷰어 신원 정보는 없다.",
        "- PDF는 넣지 않는다. 화면에서 브라우저 인쇄로 만든다.",
    ]
    if c.gen_counts[Generator.rule.value]:
        lines.append("- rule 카드는 LLM이 아니라 규칙(비상 경로)으로 만든 것이다. 품질이 LLM 카드보다 낮을 수 있다.")
    if c.gen_counts[Generator.mock.value]:
        lines.append("- mock 카드는 테스트용 가짜다. 실제 분석 결과로 쓰면 안 된다.")
    return lines


# ── 파일별 조립 ───────────────────────────────────────────────────────────


def _readme(c: _Ctx) -> bytes:
    r = c.result
    L = [UNVERIFIED_WARNING, ""] if not c.verified else []
    L += [
        "# Neumann 내보내기 패키지",
        "",
        "연구계획서 사전 위험 점검 결과를 파일 9개로 묶었다. 파일별 sha256·크기는 `manifest.json`에 있다.",
        "",
        f"- 결과 출처: `{c.origin}` — {ORIGIN_LABELS[c.origin]}",
        f"- 결과 상태: **{r.status}**{_status_suffix(c)}",
        f"- 위험카드 {c.n_cards}장 · 근거 발췌 {len(r.evidence)}건 · 유사 연구 {len(r.similar_works)}편",
        f"- 생성 방식: {_gen_summary(c)}",
        f"- 계획서 id `{_code(r.plan_id)}` · 분석 시각 {_iso(r.generated_at)} · 파이프라인 `{_code(r.pipeline_version)}`",
        "",
        "## 들어 있는 파일",
        "",
        "| 파일 | 내용 |",
        "|---|---|",
    ]
    L += [f"| `{name}` | {FILE_ROLES[name]} |" for name in FILE_NAMES]
    L += [f"| `{name}` | {export_revision.FILE_ROLES[name]} |" for name in c.extra_files]  # E3-L2r(있을 때만)
    L += ["", JSON_GENERATOR_NOTE if c.verified else JSON_GENERATOR_NOTE_UNVERIFIED]
    if c.extra_summary:
        L += ["", "## 수정 권고(E3-L2r)", "", *c.extra_summary]
    L += ["", "## 생성 방식", ""]
    L += [f"- **{_gen_short(c, g)}** {c.gen_counts[g.value]}장: {_gen_desc(c, g)}" for g in Generator]
    if c.refs:
        L += ["", "카드별:", ""]
        L += [f"- {ref} `{_code(card.card_id)}` — {_gen_label(c, card)}" for ref, card in c.refs]
    L += ["", "## 강등 단계", ""]
    if c.not_ok_stages:
        L += ["| 단계 | 상태 | 구현 | 사유 |", "|---|---|---|---|"]
        L += [
            f"| {_cell(s.stage)} | {s.state} | {_cell(s.impl or '-')} | {_cell(display_text(s.detail or '-'))} |"
            for s in c.not_ok_stages
        ]
    elif r.stages:
        L.append(f"강등된 단계가 없다(단계 {len(r.stages)}개 모두 ok).")
    else:
        L.append("결과에 단계 기록이 없다.")
    if c.n_cards == 0:
        L += ["", "## 위험카드 0장", "", "이유:", ""]
        L += [f"- {x}" for x in _zero_card_reasons(c)]
    if r.notices:
        L += ["", "## 결과 알림", ""]
        L += [f"- {_one_line(display_text(n))}" for n in r.notices]
    if c.warnings:
        L += ["", "## 주의", ""]
        L += [f"- {w}" for w in c.warnings]
    L += ["", "## 한계", ""]
    L += _limitations(c)
    L += ["- `manifest.json`은 자기 자신의 해시는 담지 않는다. 나머지 8개 파일의 sha256으로 무결성을 확인한다."]
    return _md_bytes(L)


def _risk_cards_json(c: _Ctx) -> bytes:
    r = c.result
    return _json_bytes(
        {
            "format": PACKAGE_FORMAT,
            "schema_version": SCHEMA_VERSION,
            "plan_id": r.plan_id,
            "status": r.status,
            "risk_cards": [card.model_dump(mode="json") for card in r.risk_cards],
        }
    )


def _excerpt_json(ex: Excerpt) -> dict[str, Any]:
    return {
        "excerpt_id": ex.excerpt_id,
        "source_kind": ex.source_kind,
        "source_id": ex.source_id,
        "source_url": ex.source_url,
        "start": ex.start,
        "end": ex.end,
        "text": ex.text,
        "text_sha256": ex.text_sha256,
        "source_sha256": ex.source_sha256,
    }


def _evidence_pack_json(c: _Ctx) -> bytes:
    r = c.result
    cited: set[str] = set()
    cards = []
    for ref, card in c.refs:
        cited.update(card.evidence)
        cards.append(
            {
                "ref": ref,
                "card_id": card.card_id,
                "risk_code": card.risk_code.value,
                "subcode": card.subcode,
                "title": card.title,
                "generator": card.generator.value,
                "plan_lines": card.why_applies.plan_lines,
                "works": card.works,
                "evidence": [_excerpt_json(c.ex_by_id[x]) for x in card.evidence],
            }
        )
    return _json_bytes(
        {
            "format": PACKAGE_FORMAT,
            "schema_version": SCHEMA_VERSION,
            "plan_id": r.plan_id,
            "result_origin": c.origin,
            **_plan_metadata(c),
            "reverification": {
                "status": "not_reverified",
                "note": (
                    ("패키지는 원문을 다시 받지 않는다. text는 분석 시점에 원문[start:end]를 잘라 옮긴 값이다. "
                     if c.verified else
                     "서버 서명이 없는 결과다. text는 요청자가 보낸 값이며 원문[start:end]와 같은지 확인되지 않았다. ")
                    + "대조하려면 source_url의 원문(정규화 NFC+LF, 개인정보 가림 뒤)에서 [start:end]를 잘라 "
                    "text와 글자 단위로 비교하고 sha256을 text_sha256·source_sha256과 비교한다."
                ),
            },
            "cards": cards,
            "unlinked_evidence": [_excerpt_json(ex) for ex in r.evidence if ex.excerpt_id not in cited],
        }
    )


def _similar_works_csv(c: _Ctx) -> bytes:
    works = c.result.similar_works
    axes = sorted({k for w in works for k in w.axis_scores})
    cited_by: dict[str, list[str]] = {}
    for _ref, card in c.refs:
        for wid in card.works:
            cited_by.setdefault(wid, []).append(card.card_id)
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(
        ["rank", "work_id", "similarity", "title", "venue", "year", "url", "cited_by_cards", *(f"axis_{a}" for a in axes)]
    )
    for i, w in enumerate(works, start=1):
        writer.writerow(
            [
                i,
                _csv(w.work_id),
                f"{w.similarity:.4f}",
                _csv(w.title or ""),
                _csv(w.venue or ""),
                "" if w.year is None else w.year,
                _csv(w.url or ""),
                _csv(";".join(cited_by.get(w.work_id, []))),
                *("" if a not in w.axis_scores else f"{w.axis_scores[a]:.4f}" for a in axes),
            ]
        )
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _card_legend(c: _Ctx) -> list[str]:
    if not c.refs:
        return ["위험카드가 0장이라 연결된 줄이 없다."]
    L = ["| 표시 | 카드 id | 위험 유형 | 생성 | 제목 |", "|---|---|---|---|---|"]
    L += [
        f"| {ref} | `{_code(card.card_id)}` | {_cell(_risk_label(card))} | {_gen_label(c, card).replace('|', chr(92) + '|')} "
        f"| {_cell(card.title)} |"
        for ref, card in c.refs
    ]
    return L


def _plan_annotated(c: _Ctx) -> bytes:
    by_line: dict[int, list[str]] = {}
    for ref, card in c.refs:
        # 한 카드 안의 중복 줄만 제거한다. ref는 카드마다 고유하므로 누적 목록을 검색할 필요가 없다.
        for no in dict.fromkeys(card.why_applies.plan_lines):
            by_line.setdefault(no, []).append(ref)

    if c.plan is None:
        L = [
            "# 계획서 주석 (줄 번호만)",
            "",
            "계획서 본문이 결과에 없고 plan_text도 받지 않아서, 카드가 가리킨 줄 번호만 적는다.",
            "",
            "## 카드",
            "",
            *_card_legend(c),
            "",
            "## 줄 번호",
            "",
        ]
        if by_line:
            L += ["| 줄 | 연결된 카드 |", "|---:|---|"]
            L += [f"| {no} | {', '.join(by_line[no])} |" for no in sorted(by_line)]
        else:
            L.append("카드가 가리킨 계획서 줄이 없다.")
        return _md_bytes(L)

    lines = [(ln.no, redact_pii(ln.text)) for ln in c.plan.lines]
    longest_ticks = max((len(m) for _, t in lines for m in re.findall(r"`+", t)), default=0)
    fence = "`" * max(3, longest_ticks + 1)
    marks = {no: "[" + ",".join(refs) + "]" for no, refs in by_line.items()}
    width = max((len(m) for m in marks.values()), default=0)
    num_w = len(str(len(lines)))

    L = [
        "# 계획서 주석",
        "",
        f"계획서 {len(lines)}줄. 줄 번호 옆 `[C1]` 표시는 그 줄을 근거로 든 위험카드다. 본문 출처: {c.plan_source}.",
        "",
        "## 카드",
        "",
        *_card_legend(c),
        "",
        "## 본문",
        "",
        fence + "text",
    ]
    for no, text in lines:
        mark = marks.get(no, "")
        prefix = f"{no:>{num_w}} {mark:<{width}}" if width else f"{no:>{num_w}}"
        L.append(f"{prefix} | {text}".rstrip())
    L.append(fence)
    L += ["", "## 카드별 연결 줄", ""]
    if c.refs:
        for ref, card in c.refs:
            nos = card.why_applies.plan_lines
            L.append(f"- {ref} `{_code(card.card_id)}`: " + (", ".join(str(n) for n in nos) if nos else "연결된 줄 없음"))
    else:
        L.append("위험카드가 0장이다.")
    missing = sorted(n for n in by_line if n > len(lines))
    if missing:
        L += ["", f"주의: 계획서에 없는 줄 번호를 가리킨 카드가 있다: {missing}"]
    return _md_bytes(L)


def _report(c: _Ctx) -> bytes:
    r = c.result
    L = [UNVERIFIED_WARNING, ""] if not c.verified else []
    L += [
        "# Neumann 위험 점검 리포트",
        "",
        ("비슷한 연구가 실제로 받은 심사 기록(심사평·저자 답변·결정·사후 상태)에서 찾은 위험이다. "
         "인용문은 원문을 오프셋으로 잘라 그대로 옮긴 것이다."
         if c.verified else
         "요청자가 보낸 결과를 옮겼다. 위험카드·인용문·점수는 서버가 확인하지 않은 값이다."),
        "",
        "## 요약",
        "",
        f"- 결과 출처: `{c.origin}` — {ORIGIN_LABELS[c.origin]}",
        f"- 결과 상태: **{r.status}**{_status_suffix(c)}",
        f"- 위험카드 {c.n_cards}장 · 근거 발췌 {len(r.evidence)}건 · 유사 연구 {len(r.similar_works)}편",
        f"- 생성 방식: {_gen_summary(c)}",
        f"- 계획서 id `{_code(r.plan_id)}` · 세션 `{_code(r.session_id)}` · 분석 시각 {_iso(r.generated_at)} · "
        f"파이프라인 `{_code(r.pipeline_version)}`",
    ]
    if r.notices:
        L += ["", "알림:", ""]
        L += [f"- {_one_line(display_text(n))}" for n in r.notices]

    L += ["", "## 생성 방식과 단계", ""]
    L += [f"- **{_gen_short(c, g)}** {c.gen_counts[g.value]}장: {_gen_desc(c, g)}" for g in Generator]
    L.append("")
    if r.stages:
        L += ["| 단계 | 상태 | 구현 | 사유 | 소요(초) |", "|---|---|---|---|---:|"]
        L += [
            f"| {_cell(s.stage)} | {s.state} | {_cell(s.impl or '-')} | {_cell(display_text(s.detail or '-'))} | {s.elapsed_s:.2f} |"
            for s in r.stages
        ]
    else:
        L.append("결과에 단계 기록이 없다.")

    L += ["", f"## 위험카드 ({c.n_cards}장)", ""]
    if not c.refs:
        L += ["위험카드 0장. 이유:", ""]
        L += [f"- {x}" for x in _zero_card_reasons(c)]
    for i, (ref, card) in enumerate(c.refs, start=1):
        s = card.score
        L += [
            f"### {i}. [{_risk_label(card)}] {_one_line(card.title)}",
            "",
            f"- 카드 `{_code(card.card_id)}` ({ref}) · 생성: {_gen_label(c, card)}",
            f"- 점수 {s.total:.2f} (유사도 {s.similarity:.2f} · 빈도 {s.frequency:.2f} · "
            f"심각도 {s.severity:.2f} · 신뢰도 {s.confidence:.2f})",
            f"- 이 계획서에 해당하는 이유: {_one_line(card.why_applies.text)}",
        ]
        if card.why_applies.plan_lines:
            L.append("- 계획서 줄:")
            for no in card.why_applies.plan_lines:
                text = _plan_line_text(c, no)
                L.append(f"  - {no}: {text}" if text is not None else f"  - {no}")
        if card.works:
            L.append("- 근거 논문: " + ", ".join(f"`{_code(w)}`" for w in card.works))
        L += ["", f"근거 인용 {len(card.evidence)}건:", ""]
        for k, ex_id in enumerate(card.evidence, start=1):
            ex = c.ex_by_id[ex_id]
            L.append(f"{k}. {_excerpt_ref(ex)}")
            L.append("")
            L += _quote_block(ex.text, indent="   ")
            L.append("")

    L += ["", "## 유사 연구", ""]
    if r.similar_works:
        L += ["| # | 제목 | 유사도 | 학회·연도 | 링크 |", "|---:|---|---:|---|---|"]
        for i, w in enumerate(r.similar_works, start=1):
            venue = ", ".join(x for x in (w.venue or "", "" if w.year is None else str(w.year)) if x) or "-"
            L.append(
                f"| {i} | {_cell(w.title or w.work_id)} | {w.similarity:.2f} | {_cell(venue)} | "
                f"{_url(w.url) if w.url else '-'} |"
            )
    else:
        L.append("유사 연구가 없다.")

    if r.expected_review:
        L += ["", "## 예상 심사평 (결과의 expected_review를 옮김 · 제외한 문장은 사유 코드·개수만)", ""]
        er_gen = r.expected_review.get("generator")
        if er_gen:
            name = (display_generator(er_gen, r.expected_review.get("model")) if c.verified
                    else f"{display_generator(er_gen)}({UNVERIFIED_GEN_NOTE})")
            L += [f"생성: {_one_line(name)}", ""]
        L.append("```json")
        L += _json_md(_review_for_report(r.expected_review)).split("\n")
        L.append("```")
    if r.checklist:
        L += ["", "## 체크리스트 (결과의 checklist를 옮김)", ""]
        L += [f"- {_checklist_line(item)}" for item in r.checklist]
    if c.decisions:
        L += ["", "## 결정 로그", ""]
        L += [
            f"- {d.target}: {DECISION_LABELS[d.decision]}" + (f" — {_one_line(d.note)}" if d.note else "")
            for d in c.decisions
        ]
    if c.warnings:
        L += ["", "## 주의", ""]
        L += [f"- {w}" for w in c.warnings]
    L += ["", "## 한계", ""]
    L += _limitations(c)
    return _md_bytes(L)


def _ai_context(c: _Ctx) -> bytes:
    r = c.result
    L = [UNVERIFIED_WARNING, ""] if not c.verified else []
    L += [
        "# Neumann 결과 요약 (다른 AI에 넘기는 맥락)",
        "",
        "연구계획서 사전 위험 점검 결과다. 이 문서를 받은 AI는 다음을 지킨다.",
        "",
        ("- 따옴표 안 인용문은 실제 심사 기록 원문을 오프셋으로 잘라 옮긴 것이다. 고치거나 지어내지 않는다."
         if c.verified else
         "- 이 결과는 서버가 분석·서명한 것이 아니다. 인용문·생성 방식·점수는 보낸 값 그대로이고 확인되지 않았다. "
         "원문과 대조하기 전에는 인용으로 쓰지 않는다."),
        "- 근거는 발췌 id(`ex_…`)로 가리킨다. 근거 id가 없는 위험을 새로 덧붙이지 않는다.",
        "- generator=rule 카드는 규칙(비상 경로) 결과이고 LLM 판단이 아니다. generator=mock 카드는 테스트용 가짜다.",
        f"- {JSON_GENERATOR_NOTE if c.verified else JSON_GENERATOR_NOTE_UNVERIFIED}",
        "- 위험은 가능성이다. 계획서의 결함이 확정됐다고 말하지 않는다.",
        "",
        "## 상태",
        "",
        f"- result_origin: {c.origin}",
        f"- status: {r.status}{_status_suffix(c)}",
        f"- plan_id: {_one_line(r.plan_id)}",
        f"- 생성 방식: {_gen_summary(c)}",
    ]
    L += [f"- 정상이 아닌 단계: {_stage_line(s)}" for s in c.not_ok_stages]
    L += ["", f"## 위험카드 ({c.n_cards})", ""]
    if not c.refs:
        L += ["카드 0장. 이유:", ""]
        L += [f"- {x}" for x in _zero_card_reasons(c)]
    for ref, card in c.refs:
        L += [
            f"### {ref} {_one_line(card.card_id)}",
            "",
            f"- 위험 유형: {_risk_label(card)} ({card.risk_code.title_en})",
            f"- 제목: {_one_line(card.title)}",
            f"- 생성: {_gen_label(c, card)}",
            f"- 점수 total: {card.score.total:.2f}",
            f"- 해당 이유: {_one_line(card.why_applies.text)}",
        ]
        for no in card.why_applies.plan_lines:
            text = _plan_line_text(c, no)
            L.append(f"  - 계획서 {no}줄" + (f": {text}" if text is not None else ""))
        L.append("- 근거 id: " + ", ".join(_one_line(x) for x in card.evidence))
        L.append("- 근거 인용:")
        for ex_id in card.evidence:
            ex = c.ex_by_id[ex_id]
            quote = json.dumps(ex.text, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(
                ">", "\\u003e")  # 디코드하면 글자 그대로(줄바꿈 \n, < > &는 \\u 이스케이프)
            kind = SOURCE_KIND_KO.get(ex.source_kind, ex.source_kind)
            L.append(f"  - [{_one_line(ex_id)}] {quote} ({kind}, {_one_line(ex.source_url)})")
        L.append("")
    L += ["## 유사 연구", ""]
    if r.similar_works:
        L += [
            f"- {_one_line(w.work_id)} · {_one_line(w.title or '-')} · similarity {w.similarity:.2f}"
            for w in r.similar_works
        ]
    else:
        L.append("- 없음")
    if c.warnings:
        L += ["", "## 내보내기 주의", "", *[f"- {w}" for w in c.warnings]]
    L += ["", "## 한계", ""]
    L += _limitations(c)
    return _md_bytes(L)


def _decision_log_json(c: _Ctx) -> bytes:
    r = c.result
    return _json_bytes(
        {
            "format": PACKAGE_FORMAT,
            "schema_version": SCHEMA_VERSION,
            "plan_id": r.plan_id,
            "session_id": r.session_id,
            "choices": DECISION_LABELS,
            "cards": [
                {"card_id": card.card_id, "risk_code": card.risk_code.value, "title": card.title}
                for _ref, card in c.refs
            ],
            "checklist_item_ids": sorted(_checklist_ids(r.checklist)),
            "decisions": [d.model_dump(mode="json") for d in c.decisions],
            **_plan_metadata(c),
        }
    )


def _manifest_json(c: _Ctx, files: Mapping[str, bytes], created_at: datetime) -> bytes:
    r = c.result
    return _json_bytes(
        {
            "format": PACKAGE_FORMAT,
            "schema_version": SCHEMA_VERSION,
            "created_at": _iso(created_at),
            "result_origin": c.origin,
            **_plan_metadata(c),
            "result": {
                "session_id": r.session_id,
                "plan_id": r.plan_id,
                "generated_at": _iso(r.generated_at),
                "status": r.status,
                "pipeline_version": r.pipeline_version,
            },
            "counts": {
                "risk_cards": c.n_cards,
                "evidence": len(r.evidence),
                "similar_works": len(r.similar_works),
                "plan_lines": None if c.plan is None else len(c.plan.lines),
                "decisions": len(c.decisions),
            },
            "cards_by_generator": c.gen_counts,
            "not_ok_stages": [
                {"name": s.stage, "status": s.state, "reason": s.detail, "impl": s.impl} for s in c.not_ok_stages
            ],
            "plan_source": c.plan_source,
            "evidence_reverification": "not_reverified",
            "warnings": c.warnings,
            "files": [
                {"path": name, "sha256": _sha256(files[name]), "bytes": len(files[name]),
                 **({"result_origin": c.origin, **_plan_metadata(c)} if name in FILE_NAMES else {})}
                for name in (*FILE_NAMES, *c.extra_files)
                if name != "manifest.json"
            ],
            "extra_files": list(c.extra_files),  # E3-L2r: 9파일 밖에 덧붙인 것(없으면 빈 목록)
        }
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── 공개 함수 ─────────────────────────────────────────────────────────────


def _guard_export_plan(result: Any, plan_text: str | None) -> None:
    check_payload_plan({"result": result, "plan_text": plan_text})
    if isinstance(result, PremortemResult) and result.plan is not None:
        check_embedded_plan(result.plan.lines)


def build_package_files(
    result: PremortemResult | Mapping[str, Any],
    *,
    plan_text: str | None = None,
    decisions: Sequence[DecisionEntry | Mapping[str, Any]] | None = None,
    created_at: datetime | None = None,
    result_origin: ResultOrigin = "in_process",
    revision: Mapping[str, Any] | None = None,
    revision_decisions: Sequence[Mapping[str, Any]] | None = None,
    revised_plan: Mapping[str, Any] | None = None,
    revision_sig: str | None = None,
    result_sig: str | None = None,
) -> dict[str, bytes]:
    """9개 파일 {이름: 바이트}(FILE_NAMES 순서). 입력이 계약을 어기면 ValueError(ValidationError 포함).

    E3-L2r: `revision`(수정 권고)·`revised_plan`(통합본)이 오면 `revision.json`·`revised_plan.md`를 뒤에 덧붙인다(10·11번째).
    """
    _guard_export_plan(result, plan_text)
    if not isinstance(result, PremortemResult):
        result = PremortemResult.model_validate(result)
    c = _make_ctx(result, plan_text, decisions, result_origin)
    extras = export_revision.extra_files(result, revision, revision_decisions, revised_plan, revision_sig, result_sig)
    c.extra_files = list(extras)
    c.extra_summary = export_revision.summary_lines(revision, revision_decisions, revised_plan,
                                                  result=result, revision_sig=revision_sig, result_sig=result_sig)
    files: dict[str, bytes] = {
        "README.md": _readme(c),
        "risk_cards.json": _risk_cards_json(c),
        "evidence_pack.json": _evidence_pack_json(c),
        "similar_works.csv": _similar_works_csv(c),
        "plan_annotated.md": _plan_annotated(c),
        "neumann_report.md": _report(c),
        "ai_context.md": _ai_context(c),
        "decision_log.json": _decision_log_json(c),
    }
    # Preserve the first-line result warning/title. Every human-facing member states
    # the narrower plan authority; manifest entries also cover card-list and CSV members.
    for name in ("README.md", "plan_annotated.md", "neumann_report.md", "ai_context.md"):
        head, separator, tail = files[name].decode("utf-8").partition("\n")
        files[name] = (head + separator + "\n" + _plan_authority_text(c) + "\n" + tail).encode("utf-8")
    files.update(extras)
    when = created_at or datetime.now(UTC).replace(microsecond=0)
    files["manifest.json"] = _manifest_json(c, files, when)
    return {name: files[name] for name in (*FILE_NAMES, *c.extra_files)}


def build_package(
    result: PremortemResult | Mapping[str, Any],
    *,
    plan_text: str | None = None,
    decisions: Sequence[DecisionEntry | Mapping[str, Any]] | None = None,
    created_at: datetime | None = None,
    result_origin: ResultOrigin = "in_process",
    **extras: Any,
) -> bytes:
    """분석 결과 → ZIP 바이트(9파일 + E3-L2r 선택 파일: revision·revision_decisions·revised_plan·revision_sig).

    - plan_text: result.plan이 없을 때만 쓴다. 정규화·마스킹한 해시가 result.plan_id와 다르면 거절한다.
    - decisions: 카드별 채택·보류·기각 기록(선택). card_id가 결과에 없으면 ValueError.
    - created_at: 패키지 생성 시각(manifest). 없으면 지금. 넘기면 출력 전체가 결정적이다.
    - result_origin: 결과 출처(manifest·README). API는 서버 서명을 확인해 정한다. 직접 부르면 "in_process".
    """
    _guard_export_plan(result, plan_text)
    if not isinstance(result, PremortemResult):
        result = PremortemResult.model_validate(result)
    date_time = _zip_date(result.generated_at)  # reject unsupported dates before rendering; never substitute a date
    files = build_package_files(result, plan_text=plan_text, decisions=decisions, created_at=created_at,
                                result_origin=result_origin, **extras)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in files:  # FILE_NAMES 순서 + 덧붙인 파일
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, files[name])
    return buf.getvalue()


# ── API ──────────────────────────────────────────────────────────────────

router = APIRouter()


RESULT_REQUIRED_MESSAGE = "내보내기에는 분석 결과가 필요합니다. 먼저 분석을 실행한 뒤 결과 화면에서 내보내 주세요."


def json_depth_exceeds(obj: Any, limit: int = MAX_PACKAGE_JSON_DEPTH) -> bool:
    """B2: dict·list 중첩이 limit단을 넘는지(재귀 없이 센다. 깊은 입력으로 이 검사 자체가 넘치지 않게)."""
    stack: list[tuple[Any, int]] = [(obj, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, Mapping):
            children: Any = node.values()
        elif isinstance(node, (list, tuple)):
            children = node
        else:
            continue
        if depth > limit:
            return True
        stack.extend((child, depth + 1) for child in children if isinstance(child, (Mapping, list, tuple)))
    return False


def package_limit_refusal(
    payload: dict[str, Any], *, max_plan_lines: int = 5_000, max_plan_chars: int = 50_000,
) -> tuple[int, str, str] | None:
    """중첩 모델 검증·정규화·ZIP 조립 전에 원자료 개수만 검사한다(SEC-7).

    감싼 결과와 bare result 모두 검사한다. 잘못된 자료형은 기존 스키마 검증에 맡기고 입력은 되돌려 주지 않는다.
    """
    from neumann.api.serving import count_lines, user_message

    def plan_refusal(chars: int, lines: int) -> tuple[int, str, str] | None:
        if chars > max_plan_chars:
            return 413, "too_large", user_message("too_large", limit=max_plan_chars, chars=chars)
        if lines > max_plan_lines:
            return 422, "too_many_lines", user_message("too_many_lines", limit=max_plan_lines)
        return None

    text = payload.get("plan_text")
    if isinstance(text, str):
        refused = plan_refusal(len(text), count_lines(text))
        if refused:
            return refused
    decisions = payload.get("decisions")
    if isinstance(decisions, list) and len(decisions) > MAX_PACKAGE_DECISIONS:
        return 422, "package_limits", f"결정 기록이 너무 많습니다(최대 {MAX_PACKAGE_DECISIONS:,}건)."
    if json_depth_exceeds(payload, MAX_PACKAGE_JSON_DEPTH):
        return 422, "package_limits", f"요청 JSON 중첩이 너무 깊습니다(최대 {MAX_PACKAGE_JSON_DEPTH}단)."
    result = payload.get("result", payload)
    if not isinstance(result, dict):
        return None
    cards = result.get("risk_cards")
    if isinstance(cards, list):
        if len(cards) > MAX_PACKAGE_CARDS:
            return 422, "package_limits", f"위험카드가 너무 많습니다(최대 {MAX_PACKAGE_CARDS:,}장)."
        for card in cards:
            why = card.get("why_applies") if isinstance(card, dict) else None
            refs = why.get("plan_lines") if isinstance(why, dict) else None
            if isinstance(refs, list) and len(refs) > MAX_PACKAGE_CARD_LINES:
                return 422, "package_limits", f"카드별 연결 줄이 너무 많습니다(최대 {MAX_PACKAGE_CARD_LINES:,}줄)."
    plan = result.get("plan")
    lines = plan.get("lines") if isinstance(plan, dict) else None
    if isinstance(lines, list):
        if len(lines) > max_plan_lines:
            return plan_refusal(0, len(lines))
        chars, physical_lines = max(len(lines) - 1, 0), 0
        for line in lines:
            text = line.get("text") if isinstance(line, dict) else None
            if isinstance(text, str):
                chars += len(text)
                physical_lines += count_lines(text)
                refused = plan_refusal(chars, physical_lines)
                if refused:
                    return refused
    return None


class PackageRequest(BaseModel):
    """`POST /premortem/package` 본문. result(분석 결과 JSON)는 반드시 있어야 한다(plan_text만으로는 분석하지 않는다)."""

    model_config = ConfigDict(extra="forbid")

    result: dict[str, Any] | None = None
    result_sig: str | None = Field(default=None, max_length=200, description="화면 응답의 서버 서명(v1.<hex>)")
    plan_text: str | None = Field(default=None, max_length=MAX_PLAN_CHARS)
    decisions: list[dict[str, Any]] | None = None
    # E3-L2r(선택): 수정 권고·연구자 결정·통합본 → revision.json·revised_plan.md
    revision: dict[str, Any] | None = None
    revision_decisions: list[dict[str, Any]] | None = None
    revised_plan: dict[str, Any] | None = None
    revision_sig: str | None = Field(default=None, max_length=200)
    result_sig: str | None = Field(default=None, max_length=200)


def _errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors(include_input=False, include_url=False)
    ]


def _safe_filename_part(plan_id: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]", "", plan_id)[:12] or "plan"


@router.post(
    "/premortem/package",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}, "description": "ZIP 9파일"}},
)
def premortem_package(request: Request, payload: dict[str, Any] = Body(...)) -> Response:
    """분석 결과 JSON → 내보내기 ZIP.

    본문 형식: `{"result": {...}, "plan_text": "...", "decisions": [...]}`. result는 반드시 있어야 한다.
    분석 결과 JSON을 감싸지 않고 그대로 보내도 된다. plan_text는 result에 계획서 줄이 없을 때 줄 번호를 붙이는 데만 쓴다.
    plan_text만 오면 파이프라인을 돌리지 않고 422 + 사용자 문구로 거절한다(SEC-1 S-02, PM 결정 2026-09-30:
    내보내기는 결과만 받는다. 분석은 /premortem의 관문·속도 제한·예산을 거쳐야 한다).
    """
    srv = getattr(request.app.state, "serving", None)
    limits = {} if srv is None else {"max_plan_lines": srv.config.max_plan_lines,
                                    "max_plan_chars": srv.config.max_plan_chars}
    check_payload_plan(payload, max_lines=limits.get("max_plan_lines", 5_000))
    refusal = package_limit_refusal(payload, **limits)
    if refusal:
        status, code, message = refusal
        raise HTTPException(status_code=status, detail={"error_code": code, "message": message})
    if "result" not in payload and "plan_text" not in payload and {"session_id", "plan_id"} <= payload.keys():
        payload = {"result": payload}
    try:
        req = PackageRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_errors(exc)) from None
    has_text = bool(req.plan_text and req.plan_text.strip())
    if req.result is None:
        raise HTTPException(status_code=422, detail=RESULT_REQUIRED_MESSAGE)
    try:
        result = PremortemResult.model_validate(req.result)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_errors(exc)) from None

    from neumann.api.signing import verify_result

    origin: ResultOrigin = (
        "server_signed" if verify_result(req.result, req.result_sig) else "client_submitted_unverified"
    )
    try:
        plan, plan_source = _resolve_plan(result, req.plan_text if has_text else None)
        plan_association = _plan_association(plan, plan_source, origin)
        data = build_package(result, plan_text=req.plan_text if has_text else None, decisions=req.decisions,
                             result_origin=origin,
                             revision=req.revision, revision_decisions=req.revision_decisions,
                             revised_plan=req.revised_plan, revision_sig=req.revision_sig, result_sig=req.result_sig)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_errors(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    filename = f"neumann_package_{_safe_filename_part(result.plan_id)}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Neumann-Status": result.status,
            "X-Neumann-Cards": str(len(result.risk_cards)),
            "X-Neumann-Result-Origin": origin,
            "X-Neumann-Plan-Association": plan_association,
        },
    )


__all__ = [
    "DECISION_LABELS",
    "FILE_NAMES",
    "PACKAGE_FORMAT",
    "RESULT_ORIGINS",
    "DecisionEntry",
    "PackageRequest",
    "build_package",
    "build_package_files",
    "premortem_package",
    "router",
]
