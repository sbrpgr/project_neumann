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
  규칙 카드를 LLM 결과라고 쓰지 않는다. 카드가 0장이면 결과에 적힌 사유를 옮기고, 없으면 "사유 없음"이라고 쓴다.
- 인용: `evidence`의 text를 가공 없이 옮긴다. 패키지는 원문을 다시 받지 않으므로 재대조 상태는 `not_reverified`다.
- 개인정보: 계획서 줄은 `PlanDocument` 규칙(NFC+LF, 이메일·ORCID 가림)을 거친 줄만 쓴다. 설정·환경변수는 읽지 않는다.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

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
GENERATOR_SHORT: dict[Generator, str] = {
    Generator.astra: "astra(LLM)",
    Generator.rule: "rule(규칙 비상 경로)",
    Generator.mock: "mock(테스트용 가짜)",
}

SOURCE_KIND_KO: dict[str, str] = {
    "review": "심사평",
    "author_response": "저자 답변",
    "decision": "결정",
    "post_status": "사후 상태",
}

NOT_OK_STATES = ("degraded", "error", "skipped")

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
            parts.append(f"카드 `{self.card_id}`")
        if self.item_id:
            parts.append(f"행동 `{self.item_id}`")
        return " · ".join(parts)


CHECKLIST_ID_KEYS = ("id", "item_id", "action_id")


def _checklist_ids(checklist: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(item[k]) for item in checklist for k in CHECKLIST_ID_KEYS if item.get(k) is not None}


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
        meta.append(f"생성 {item['generator']}")
    line = (f"[{item_id}] " if item_id is not None else "") + _one_line(text)
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

    @property
    def n_cards(self) -> int:
        return len(self.refs)


def _make_ctx(
    result: PremortemResult,
    plan_text: str | None,
    decisions: Sequence[DecisionEntry | Mapping[str, Any]] | None,
) -> _Ctx:
    warnings: list[str] = []
    plan: PlanDocument | None
    if result.plan is not None:
        plan, plan_source = result.plan, "result.plan"
        if plan_text:
            plan_source = "result.plan (plan_text는 쓰지 않음)"
    elif plan_text is not None and plan_text.strip():
        plan = PlanDocument.from_text(plan_text, result.session_id)  # NFC+LF, 이메일·ORCID 가림
        plan_source = "plan_text (이메일·ORCID 가림)"
        if plan.plan_id != result.plan_id:
            warnings.append("plan_text의 해시가 결과의 plan_id와 다르다. 분석한 계획서와 다른 본문일 수 있다.")
    else:
        plan, plan_source = None, "none"

    refs = [(f"C{i}", card) for i, card in enumerate(result.risk_cards, start=1)]
    if plan is not None:
        n_lines = len(plan.lines)
        for ref, card in refs:
            bad = [n for n in card.why_applies.plan_lines if n > n_lines]
            if bad:
                warnings.append(f"{ref} `{card.card_id}`가 계획서에 없는 줄 {bad}을 가리킨다(계획서 {n_lines}줄).")

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
        if entry.item_id is not None and entry.item_id not in item_ids:
            raise ValueError(f"결정 로그의 item_id {entry.item_id!r}가 결과의 체크리스트에 없다")
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
    )


# ── 서식 헬퍼 ─────────────────────────────────────────────────────────────


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _one_line(text: Any) -> str:
    """마크다운 한 줄용: 개인정보 가림 + 줄바꿈·연속 공백을 한 칸으로."""
    return re.sub(r"\s+", " ", redact_pii(str(text))).strip()


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


def _gen_label(card: RiskCard) -> str:
    label = GENERATOR_SHORT[card.generator]
    if card.generator is Generator.astra and card.model:
        label += f", 모델 {card.model}"
    return label


def _gen_summary(c: _Ctx) -> str:
    return " · ".join(f"{GENERATOR_SHORT[g]} {c.gen_counts[g.value]}장" for g in Generator)


def _stage_line(s: StageStatus) -> str:
    text = f"{s.stage}: {s.state}"
    if s.detail:
        text += f" — {_one_line(s.detail)}"
    return text


def _zero_card_reasons(c: _Ctx) -> list[str]:
    """카드 0장 사유. 결과에 적힌 것만 옮긴다(지어내지 않는다)."""
    reasons: list[str] = []
    if c.result.status == "error":
        reasons.append("분석이 오류로 끝났다(status=error).")
    reasons.extend(f"단계 {_stage_line(s)}" for s in c.not_ok_stages)
    reasons.extend(_one_line(n) for n in c.result.notices)
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
    return [f"{indent}> {ln}" if ln else f"{indent}>" for ln in text.split("\n")]


def _excerpt_ref(ex: Excerpt) -> str:
    kind = SOURCE_KIND_KO.get(ex.source_kind, ex.source_kind)
    return f"{kind} `{ex.source_id}` [{ex.start}:{ex.end}] · <{ex.source_url}> · `{ex.excerpt_id}`"


def _limitations(c: _Ctx) -> list[str]:
    lines = [
        "- 인용문은 분석 시점에 원문을 오프셋으로 잘라 옮긴 것이다. 이 패키지는 원문을 다시 받아 대조하지 않았다"
        "(`evidence_pack.json`의 `reverification`).",
        "- 위험카드는 비슷한 연구가 받은 심사 기록에서 찾은 **가능성**이다. 이 계획서의 결함이 확정됐다는 뜻이 아니다.",
        f"- 계획서 본문 출처: {c.plan_source}. 계획서 줄은 이메일·ORCID를 가린 뒤 담는다.",
        "- 설정·API 키·환경변수 값은 담지 않는다. 리뷰어 신원 정보는 없다.",
        "- PDF는 넣지 않는다. 화면에서 브라우저 인쇄로 만든다.",
    ]
    if c.gen_counts[Generator.rule.value]:
        lines.append("- rule 카드는 LLM이 아니라 규칙(비상 경로)으로 만든 것이다. 품질이 astra 카드보다 낮을 수 있다.")
    if c.gen_counts[Generator.mock.value]:
        lines.append("- mock 카드는 테스트용 가짜다. 실제 분석 결과로 쓰면 안 된다.")
    return lines


# ── 파일별 조립 ───────────────────────────────────────────────────────────


def _readme(c: _Ctx) -> bytes:
    r = c.result
    L = [
        "# Neumann 내보내기 패키지",
        "",
        "연구계획서 사전 위험 점검 결과를 파일 9개로 묶었다. 파일별 sha256·크기는 `manifest.json`에 있다.",
        "",
        f"- 결과 상태: **{r.status}**{_status_suffix(c)}",
        f"- 위험카드 {c.n_cards}장 · 근거 발췌 {len(r.evidence)}건 · 유사 연구 {len(r.similar_works)}편",
        f"- 생성 방식: {_gen_summary(c)}",
        f"- 계획서 id `{r.plan_id}` · 분석 시각 {_iso(r.generated_at)} · 파이프라인 `{r.pipeline_version}`",
        "",
        "## 들어 있는 파일",
        "",
        "| 파일 | 내용 |",
        "|---|---|",
    ]
    L += [f"| `{name}` | {FILE_ROLES[name]} |" for name in FILE_NAMES]
    L += ["", "## 생성 방식", ""]
    L += [f"- **{g.value}** {c.gen_counts[g.value]}장: {GENERATOR_LABELS[g]}" for g in Generator]
    if c.refs:
        L += ["", "카드별:", ""]
        L += [f"- {ref} `{card.card_id}` — {_gen_label(card)}" for ref, card in c.refs]
    L += ["", "## 강등 단계", ""]
    if c.not_ok_stages:
        L += ["| 단계 | 상태 | 구현 | 사유 |", "|---|---|---|---|"]
        L += [
            f"| {_cell(s.stage)} | {s.state} | {_cell(s.impl or '-')} | {_cell(s.detail or '-')} |"
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
        L += [f"- {_one_line(n)}" for n in r.notices]
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
            "reverification": {
                "status": "not_reverified",
                "note": (
                    "패키지는 원문을 다시 받지 않는다. text는 분석 시점에 원문[start:end]를 잘라 옮긴 값이다. "
                    "대조하려면 source_url의 원문(정규화 NFC+LF, 개인정보 가림 뒤)에서 [start:end]를 잘라 "
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
                w.work_id,
                f"{w.similarity:.4f}",
                w.title or "",
                w.venue or "",
                "" if w.year is None else w.year,
                w.url or "",
                ";".join(cited_by.get(w.work_id, [])),
                *("" if a not in w.axis_scores else f"{w.axis_scores[a]:.4f}" for a in axes),
            ]
        )
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _card_legend(c: _Ctx) -> list[str]:
    if not c.refs:
        return ["위험카드가 0장이라 연결된 줄이 없다."]
    L = ["| 표시 | 카드 id | 위험 유형 | 생성 | 제목 |", "|---|---|---|---|---|"]
    L += [
        f"| {ref} | `{card.card_id}` | {_cell(_risk_label(card))} | {_cell(_gen_label(card))} | {_cell(card.title)} |"
        for ref, card in c.refs
    ]
    return L


def _plan_annotated(c: _Ctx) -> bytes:
    by_line: dict[int, list[str]] = {}
    for ref, card in c.refs:
        for no in card.why_applies.plan_lines:
            refs = by_line.setdefault(no, [])
            if ref not in refs:
                refs.append(ref)

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
            L.append(f"- {ref} `{card.card_id}`: " + (", ".join(str(n) for n in nos) if nos else "연결된 줄 없음"))
    else:
        L.append("위험카드가 0장이다.")
    missing = sorted(n for n in by_line if n > len(lines))
    if missing:
        L += ["", f"주의: 계획서에 없는 줄 번호를 가리킨 카드가 있다: {missing}"]
    return _md_bytes(L)


def _report(c: _Ctx) -> bytes:
    r = c.result
    L = [
        "# Neumann 위험 점검 리포트",
        "",
        "비슷한 연구가 실제로 받은 심사 기록(심사평·저자 답변·결정·사후 상태)에서 찾은 위험이다. "
        "인용문은 원문을 오프셋으로 잘라 그대로 옮긴 것이다.",
        "",
        "## 요약",
        "",
        f"- 결과 상태: **{r.status}**{_status_suffix(c)}",
        f"- 위험카드 {c.n_cards}장 · 근거 발췌 {len(r.evidence)}건 · 유사 연구 {len(r.similar_works)}편",
        f"- 생성 방식: {_gen_summary(c)}",
        f"- 계획서 id `{r.plan_id}` · 세션 `{r.session_id}` · 분석 시각 {_iso(r.generated_at)} · 파이프라인 `{r.pipeline_version}`",
    ]
    if r.notices:
        L += ["", "알림:", ""]
        L += [f"- {_one_line(n)}" for n in r.notices]

    L += ["", "## 생성 방식과 단계", ""]
    L += [f"- **{g.value}** {c.gen_counts[g.value]}장: {GENERATOR_LABELS[g]}" for g in Generator]
    L.append("")
    if r.stages:
        L += ["| 단계 | 상태 | 구현 | 사유 | 소요(초) |", "|---|---|---|---|---:|"]
        L += [
            f"| {_cell(s.stage)} | {s.state} | {_cell(s.impl or '-')} | {_cell(s.detail or '-')} | {s.elapsed_s:.2f} |"
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
            f"- 카드 `{card.card_id}` ({ref}) · 생성: {_gen_label(card)}",
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
            L.append("- 근거 논문: " + ", ".join(f"`{w}`" for w in card.works))
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
                f"{'<' + w.url + '>' if w.url else '-'} |"
            )
    else:
        L.append("유사 연구가 없다.")

    if r.expected_review:
        L += ["", "## 예상 심사평 (결과의 expected_review를 그대로 옮김)", "", "```json"]
        L += json.dumps(r.expected_review, ensure_ascii=False, indent=2).split("\n")
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
    L = [
        "# Neumann 결과 요약 (다른 AI에 넘기는 맥락)",
        "",
        "연구계획서 사전 위험 점검 결과다. 이 문서를 받은 AI는 다음을 지킨다.",
        "",
        "- 따옴표 안 인용문은 실제 심사 기록 원문을 오프셋으로 잘라 옮긴 것이다. 고치거나 지어내지 않는다.",
        "- 근거는 발췌 id(`ex_…`)로 가리킨다. 근거 id가 없는 위험을 새로 덧붙이지 않는다.",
        "- generator=rule 카드는 규칙(비상 경로) 결과이고 LLM 판단이 아니다. generator=mock 카드는 테스트용 가짜다.",
        "- 위험은 가능성이다. 계획서의 결함이 확정됐다고 말하지 않는다.",
        "",
        "## 상태",
        "",
        f"- status: {r.status}{_status_suffix(c)}",
        f"- plan_id: {r.plan_id}",
        f"- 생성 방식: {_gen_summary(c)}",
    ]
    L += [f"- 정상이 아닌 단계: {_stage_line(s)}" for s in c.not_ok_stages]
    L += ["", f"## 위험카드 ({c.n_cards})", ""]
    if not c.refs:
        L += ["카드 0장. 이유:", ""]
        L += [f"- {x}" for x in _zero_card_reasons(c)]
    for ref, card in c.refs:
        L += [
            f"### {ref} {card.card_id}",
            "",
            f"- 위험 유형: {_risk_label(card)} ({card.risk_code.title_en})",
            f"- 제목: {_one_line(card.title)}",
            f"- generator: {card.generator.value}" + (f" (model {card.model})" if card.model else ""),
            f"- 점수 total: {card.score.total:.2f}",
            f"- 해당 이유: {_one_line(card.why_applies.text)}",
        ]
        for no in card.why_applies.plan_lines:
            text = _plan_line_text(c, no)
            L.append(f"  - 계획서 {no}줄" + (f": {text}" if text is not None else ""))
        L.append("- 근거 id: " + ", ".join(card.evidence))
        L.append("- 근거 인용:")
        for ex_id in card.evidence:
            ex = c.ex_by_id[ex_id]
            quote = json.dumps(ex.text, ensure_ascii=False)  # 글자 그대로(줄바꿈은 \n으로 이스케이프)
            kind = SOURCE_KIND_KO.get(ex.source_kind, ex.source_kind)
            L.append(f"  - [{ex_id}] {quote} ({kind}, {ex.source_url})")
        L.append("")
    L += ["## 유사 연구", ""]
    if r.similar_works:
        L += [
            f"- {w.work_id} · {_one_line(w.title or '-')} · similarity {w.similarity:.2f}" for w in r.similar_works
        ]
    else:
        L.append("- 없음")
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
        }
    )


def _manifest_json(c: _Ctx, files: Mapping[str, bytes], created_at: datetime) -> bytes:
    r = c.result
    return _json_bytes(
        {
            "format": PACKAGE_FORMAT,
            "schema_version": SCHEMA_VERSION,
            "created_at": _iso(created_at),
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
                {"path": name, "sha256": _sha256(files[name]), "bytes": len(files[name])}
                for name in FILE_NAMES
                if name != "manifest.json"
            ],
        }
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── 공개 함수 ─────────────────────────────────────────────────────────────


def build_package_files(
    result: PremortemResult | Mapping[str, Any],
    *,
    plan_text: str | None = None,
    decisions: Sequence[DecisionEntry | Mapping[str, Any]] | None = None,
    created_at: datetime | None = None,
) -> dict[str, bytes]:
    """9개 파일 {이름: 바이트}(FILE_NAMES 순서). 입력이 계약을 어기면 ValueError(ValidationError 포함)."""
    if not isinstance(result, PremortemResult):
        result = PremortemResult.model_validate(result)
    c = _make_ctx(result, plan_text, decisions)
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
    when = created_at or datetime.now(UTC).replace(microsecond=0)
    files["manifest.json"] = _manifest_json(c, files, when)
    return {name: files[name] for name in FILE_NAMES}


def build_package(
    result: PremortemResult | Mapping[str, Any],
    *,
    plan_text: str | None = None,
    decisions: Sequence[DecisionEntry | Mapping[str, Any]] | None = None,
    created_at: datetime | None = None,
) -> bytes:
    """분석 결과 → ZIP 바이트(9파일).

    - plan_text: result.plan이 없을 때만 쓴다. PlanDocument 규칙대로 정규화·마스킹한 줄만 담는다.
    - decisions: 카드별 채택·보류·기각 기록(선택). card_id가 결과에 없으면 ValueError.
    - created_at: 패키지 생성 시각(manifest). 없으면 지금. 넘기면 출력 전체가 결정적이다.
    """
    if not isinstance(result, PremortemResult):
        result = PremortemResult.model_validate(result)
    files = build_package_files(result, plan_text=plan_text, decisions=decisions, created_at=created_at)
    ts = result.generated_at.astimezone(UTC)
    date_time = max((ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second), (1980, 1, 1, 0, 0, 0))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in FILE_NAMES:
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, files[name])
    return buf.getvalue()


# ── API ──────────────────────────────────────────────────────────────────

router = APIRouter()


RESULT_REQUIRED_MESSAGE = "내보내기에는 분석 결과가 필요합니다. 먼저 분석을 실행한 뒤 결과 화면에서 내보내 주세요."


class PackageRequest(BaseModel):
    """`POST /premortem/package` 본문. result(분석 결과 JSON)는 반드시 있어야 한다(plan_text만으로는 분석하지 않는다)."""

    model_config = ConfigDict(extra="forbid")

    result: dict[str, Any] | None = None
    plan_text: str | None = Field(default=None, max_length=MAX_PLAN_CHARS)
    decisions: list[dict[str, Any]] | None = None


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
def premortem_package(payload: dict[str, Any] = Body(...)) -> Response:
    """분석 결과 JSON → 내보내기 ZIP.

    본문 형식: `{"result": {...}, "plan_text": "...", "decisions": [...]}`. result는 반드시 있어야 한다.
    분석 결과 JSON을 감싸지 않고 그대로 보내도 된다. plan_text는 result에 계획서 줄이 없을 때 줄 번호를 붙이는 데만 쓴다.
    plan_text만 오면 파이프라인을 돌리지 않고 422 + 사용자 문구로 거절한다(SEC-1 S-02, PM 결정 2026-09-30:
    내보내기는 결과만 받는다. 분석은 /premortem의 관문·속도 제한·예산을 거쳐야 한다).
    """
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

    try:
        data = build_package(result, plan_text=req.plan_text if has_text else None, decisions=req.decisions)
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
        },
    )


__all__ = [
    "DECISION_LABELS",
    "FILE_NAMES",
    "PACKAGE_FORMAT",
    "DecisionEntry",
    "PackageRequest",
    "build_package",
    "build_package_files",
    "premortem_package",
    "router",
]
