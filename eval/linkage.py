"""근거 연결 검사기 (E5-L0).

위험카드가 인용한 근거(Excerpt)가 원문과 글자 단위로 연결되는지 잰다.

    python -m eval.linkage --result result.json --sources reviews.jsonl --out report.json

함수 하나로 부를 수 있다(PM이 `scripts/verify.py`에서 쓴다):

    from eval.linkage import check_result
    report = check_result(result, source_lookup)  # result: PremortemResult 또는 그 JSON dict
    report.passed, report.linkage_rate, report.card_pass_rate, report.drop.rate, report.failures

근거 링크 = 카드 1장 × 그 카드가 인용한 excerpt id 1개. 링크마다 다음을 모두 만족해야 "연결됨"이다.

- 카드가 인용한 excerpt id가 `result.evidence`에 있다(서로 다른 내용으로 중복되지 않는다)
- `source_url`이 비어 있지 않은 http(s) URL이다
- `source_lookup(source_id)`가 원문을 돌려준다
- `원문[start:end] == text` — 글자 그대로 비교한다(strip·정규화 없음)
- `sha256(text) == text_sha256`, 그리고 `source_sha256`이 있으면 `sha256(원문) == source_sha256`

오프셋 0은 정상값이다. 빠진 값은 `is None`으로만 본다(falsy 검사 금지).
모델 생성자 검사를 믿지 않는다. dict 입력은 검증 없이 필드를 직접 읽고, 모델 입력도 필드를 다시 잰다.
그래서 조작된 JSON(해시만 틀림, URL 빔, 인용 바꿔치기)도 예외 없이 실패로 집계된다.

폐기율은 결과에 있을 때만 보고한다(아래 `DROP_*` 키). 없으면 "폐기율 없음"을 명시한다.
폐기율 없는 연결률 100%는 의미가 약하다(04_평가_명세 §2.2).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, computed_field

from neumann.models import PremortemResult, sha256_text

REPORT_SCHEMA = "neumann.linkage/1"

# 폐기율을 읽는 키. `verification`에 먼저 찾고, 없으면 `stages[].counts`를 더한다.
DROP_TOTAL = "findings_total"  # 파이프라인이 받은 전체 지적 수
DROP_DROPPED = "findings_dropped"  # 그중 버린 지적 수(범위 밖·빈 구간·enum 밖 등)
DROP_KEPT = "findings_kept"  # total이 없으면 kept + dropped를 전체로 쓴다

# models._check_http_url과 같은 식. 비공개 함수에 기대지 않으려고 따로 둔다.
_HTTP_URL = re.compile(r"^https?://[^\s/$.?#][^\s]*$")

REASONS: dict[str, str] = {
    "no_evidence": "카드에 근거 excerpt id가 없다",
    "excerpt_missing": "카드가 인용한 excerpt id가 result.evidence에 없다",
    "duplicate_excerpt_id": "같은 excerpt id가 evidence에 서로 다른 내용으로 두 번 이상 있다",
    "source_url_missing": "source_url이 비었다",
    "source_url_invalid": "source_url이 http(s) URL이 아니다",
    "source_id_missing": "source_id가 비었다",
    "source_not_found": "source_lookup이 원문을 찾지 못했다",
    "source_lookup_error": "source_lookup이 예외를 냈다",
    "offset_missing": "start 또는 end가 없다",
    "offset_invalid": "start/end가 정수가 아니거나 start<0 또는 end<=start",
    "offset_out_of_range": "end가 원문 길이를 넘는다",
    "text_missing": "인용 text가 없다",
    "text_mismatch": "원문[start:end]가 인용 text와 글자 단위로 다르다",
    "text_hash_missing": "text_sha256이 없다",
    "text_hash_mismatch": "sha256(text)가 text_sha256과 다르다",
    "source_hash_mismatch": "sha256(원문)이 source_sha256과 다르다",
}

NO_DROP_NOTE = (
    "폐기율 없음: 결과에 verification 또는 stages[].counts의 "
    f"{DROP_DROPPED}·{DROP_TOTAL}(또는 {DROP_KEPT})가 없다. 폐기율 없는 연결률은 의미가 약하다"
)

# source_lookup: source_id → 원문. 원문은 str 또는 `.text`/["text"]가 str인 객체. 없으면 None 또는 KeyError.
SourceLookup = Callable[[str], Any] | Mapping[str, Any]


# ── 보고 모델 ─────────────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LinkFailure(_Strict):
    """실패한 근거 링크 하나(또는 근거 없는 카드). reasons는 REASONS의 키."""

    card_id: str | None
    excerpt_id: str | None
    reasons: list[str]
    detail: str


class DropRate(_Strict):
    """폐기율 = findings_dropped / findings_total. 결과에 없으면 available=False, rate=None."""

    available: bool
    findings_total: int | None = None
    findings_dropped: int | None = None
    rate: float | None = None
    source: str | None = None  # 어디서 읽었나: "verification" 또는 "stages:<이름,...>"
    note: str


class LinkageReport(_Strict):
    report_schema: str = REPORT_SCHEMA
    checked_at: datetime
    session_id: str | None = None
    plan_id: str | None = None
    result_status: str | None = None
    input_kind: Literal["model", "dict"]
    contract_valid: bool | None = None  # dict 입력이 PremortemResult 검증을 통과했나(모델 입력은 None)
    verdict: Literal["pass", "fail", "no_cards"]
    links_total: int
    links_ok: int
    linkage_rate: float | None  # links_ok / links_total. 링크 0개면 None(1.0으로 세지 않는다)
    cards_total: int
    cards_ok: int  # 근거가 1개 이상이고 모든 근거 링크가 연결된 카드
    card_pass_rate: float | None
    excerpts_total: int  # 카드가 인용한 서로 다른 excerpt id 수
    excerpts_ok: int
    source_hash_unchecked: int  # source_sha256이 없어 원문 전체 해시는 못 잰 excerpt 수
    evidence_unreferenced: int  # evidence에 있지만 어느 카드도 인용하지 않은 excerpt 수
    card_generators: dict[str, int]
    drop: DropRate
    reason_counts: dict[str, int]
    failures: list[LinkFailure]
    notes: list[str]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return self.verdict == "pass"

    def summary(self) -> str:
        """한 줄 요약(CLI 출력·로그용). 인용 원문은 넣지 않는다."""
        d = self.drop
        drop = (
            f"폐기율 {d.findings_dropped}/{d.findings_total} = {_fmt(d.rate)} ({d.source})"
            if d.available
            else "폐기율 없음"
        )
        return (
            f"근거 연결률 {self.links_ok}/{self.links_total} = {_fmt(self.linkage_rate)} · "
            f"카드 통과 {self.cards_ok}/{self.cards_total} = {_fmt(self.card_pass_rate)} · "
            f"{drop} · 실패 {len(self.failures)}건 · 판정 {self.verdict}"
        )


def _fmt(x: float | None) -> str:
    return "정의 안 됨" if x is None else f"{x:.3f}"


# ── 검사 ──────────────────────────────────────────────────────────────────


def _get(obj: Any, key: str) -> Any:
    """dict와 모델(model_construct로 필드가 빠진 것 포함) 양쪽에서 값을 읽는다."""
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _short(s: Any, n: int = 60) -> str:
    r = repr(s)
    return r if len(r) <= n else r[: n - 3] + "..."


_EXCERPT_FIELDS = (
    "source_kind",
    "source_id",
    "start",
    "end",
    "text",
    "text_sha256",
    "source_url",
    "source_sha256",
)


def _signature(ex: Any) -> str:
    # repr로 묶는다: 조작된 입력에 해시 불가능한 값(list 등)이 들어 있어도 죽지 않게
    return repr(tuple(_get(ex, f) for f in _EXCERPT_FIELDS))


class _Sources:
    """source_lookup 호출을 source_id별로 한 번만 한다."""

    def __init__(self, lookup: SourceLookup | None) -> None:
        self._lookup = lookup
        self._cache: dict[str, tuple[str | None, str | None, str]] = {}

    def get(self, source_id: str) -> tuple[str | None, str | None, str]:
        """(원문, 실패 사유 키, 설명)."""
        if source_id not in self._cache:
            self._cache[source_id] = self._resolve(source_id)
        return self._cache[source_id]

    def _resolve(self, source_id: str) -> tuple[str | None, str | None, str]:
        lookup = self._lookup
        if lookup is None:
            return None, "source_not_found", "source_lookup이 주어지지 않았다"
        try:
            value = lookup.get(source_id) if isinstance(lookup, Mapping) else lookup(source_id)
        except KeyError:
            value = None
        except Exception as exc:  # 조회 실패도 실패로 센다(검사기가 죽지 않게)
            return None, "source_lookup_error", f"{type(exc).__name__}"
        if value is None:
            return None, "source_not_found", f"source_id={source_id!r}"
        if isinstance(value, str):
            return value, None, ""
        text = _get(value, "text")
        if isinstance(text, str):
            return text, None, ""
        return None, "source_not_found", f"source_id={source_id!r}: 원문 text가 문자열이 아니다"


def _check_excerpt(ex: Any, sources: _Sources) -> tuple[list[str], list[str], bool]:
    """excerpt 하나를 잰다. (실패 사유 키 목록, 설명 목록, 원문 해시 미대조 여부)."""
    reasons: list[str] = []
    details: list[str] = []

    url = _get(ex, "source_url")
    if url is None or not isinstance(url, str) or not url.strip():
        reasons.append("source_url_missing")
    elif not _HTTP_URL.match(url):
        reasons.append("source_url_invalid")
        details.append(f"source_url={_short(url)}")

    text = _get(ex, "text")
    text_ok = isinstance(text, str)
    if not text_ok:
        reasons.append("text_missing")

    text_sha = _get(ex, "text_sha256")
    if text_sha is None or text_sha == "":
        reasons.append("text_hash_missing")
    elif text_ok and sha256_text(text) != text_sha:
        reasons.append("text_hash_mismatch")

    start, end = _get(ex, "start"), _get(ex, "end")
    offsets_ok = False
    if start is None or end is None:  # 0은 정상값이다. falsy로 보지 않는다
        reasons.append("offset_missing")
    elif not (_is_int(start) and _is_int(end)) or start < 0 or end <= start:
        reasons.append("offset_invalid")
        details.append(f"start={start!r}, end={end!r}")
    else:
        offsets_ok = True

    source_id = _get(ex, "source_id")
    source_text: str | None = None
    if not isinstance(source_id, str) or not source_id:
        reasons.append("source_id_missing")
    else:
        source_text, why, detail = sources.get(source_id)
        if why is not None:
            reasons.append(why)
            if detail:
                details.append(detail)

    hash_unchecked = False
    if source_text is not None:
        if offsets_ok and text_ok:
            if end > len(source_text):
                reasons.append("offset_out_of_range")
                details.append(f"end={end} > len(원문)={len(source_text)}")
            elif source_text[start:end] != text:
                reasons.append("text_mismatch")
                details.append(f"원문[{start}:{end}]={_short(source_text[start:end])} != text={_short(text)}")
        src_sha = _get(ex, "source_sha256")
        if src_sha is None:
            hash_unchecked = True
        elif sha256_text(source_text) != src_sha:
            reasons.append("source_hash_mismatch")
    return reasons, details, hash_unchecked


def _drop_from_counts(counts: Any) -> tuple[int, int] | str | None:
    """(total, dropped), 오류 설명 문자열, 또는 키가 없으면 None."""
    if not isinstance(counts, Mapping) or DROP_DROPPED not in counts:
        return None
    dropped = counts.get(DROP_DROPPED)
    total = counts.get(DROP_TOTAL)
    kept = counts.get(DROP_KEPT)
    if total is None and kept is not None:
        if not (_is_int(kept) and _is_int(dropped)):
            return f"{DROP_KEPT}={kept!r}, {DROP_DROPPED}={dropped!r}: 정수가 아니다"
        total = kept + dropped
    if not (_is_int(total) and _is_int(dropped)):
        return f"{DROP_TOTAL}={total!r}, {DROP_DROPPED}={dropped!r}: 정수가 아니다"
    if dropped < 0 or total < 0 or dropped > total:
        return f"{DROP_DROPPED}={dropped} / {DROP_TOTAL}={total}: 범위가 맞지 않는다"
    return total, dropped


def _drop_rate(verification: Any, stages: list[Any]) -> DropRate:
    found: list[tuple[str, tuple[int, int] | str]] = []
    got = _drop_from_counts(verification)
    if got is not None:
        found.append(("verification", got))
    else:
        for i, st in enumerate(stages):
            got = _drop_from_counts(_get(st, "counts"))
            if got is not None:
                label = _get(st, "stage") or _get(st, "name") or f"#{i}"
                found.append((str(label), got))
    if not found:
        return DropRate(available=False, note=NO_DROP_NOTE)
    errors = [f"{src}: {g}" for src, g in found if isinstance(g, str)]
    if errors:
        return DropRate(available=False, note="폐기율 계산 불가: " + "; ".join(errors))
    total = sum(g[0] for _, g in found)  # type: ignore[index]
    dropped = sum(g[1] for _, g in found)  # type: ignore[index]
    source = "verification" if found[0][0] == "verification" else "stages:" + ",".join(s for s, _ in found)
    if total == 0:
        return DropRate(
            available=False,
            findings_total=0,
            findings_dropped=0,
            source=source,
            note="폐기율 정의 안 됨: 전체 지적 0건",
        )
    rate = dropped / total
    return DropRate(
        available=True,
        findings_total=total,
        findings_dropped=dropped,
        rate=rate,
        source=source,
        note=f"폐기율 {dropped}/{total} = {rate:.3f}",
    )


def check_result(
    result: PremortemResult | Mapping[str, Any],
    source_lookup: SourceLookup | None,
    *,
    now: datetime | None = None,
) -> LinkageReport:
    """결과의 모든 카드 근거를 원문과 대조한다. 예외 없이 보고서를 돌려준다(입력 타입 오류만 TypeError).

    - result: `PremortemResult` 또는 그 `model_dump(mode="json")` dict(조작돼 계약 검증을 못 넘는 것도 된다)
    - source_lookup: `source_id -> 원문`. 함수 또는 dict. 원문이 없으면 None을 돌려주거나 KeyError
    """
    if isinstance(result, BaseModel):
        input_kind: Literal["model", "dict"] = "model"
        contract_valid: bool | None = None
        contract_note = None
    elif isinstance(result, Mapping):
        input_kind = "dict"
        try:
            PremortemResult.model_validate(dict(result))
            contract_valid, contract_note = True, None
        except ValidationError as exc:
            errs = exc.errors(include_url=False, include_input=False)
            first = errs[0] if errs else {}
            loc = ".".join(str(p) for p in first.get("loc", ()))
            contract_valid = False
            contract_note = f"결과가 계약(PremortemResult) 검증을 통과하지 못했다: {len(errs)}건, 첫 오류 {loc}: {str(first.get('msg', ''))[:200]}"
    else:
        raise TypeError(f"result는 PremortemResult 또는 dict여야 한다: {type(result).__name__}")

    cards = list(_get(result, "risk_cards") or [])
    evidence = list(_get(result, "evidence") or [])
    stages = list(_get(result, "stages") or [])
    sources = _Sources(source_lookup)

    by_id: dict[str, list[Any]] = {}
    for ex in evidence:
        eid = _get(ex, "excerpt_id")
        if isinstance(eid, str) and eid:
            by_id.setdefault(eid, []).append(ex)

    ex_cache: dict[str, tuple[list[str], list[str], bool]] = {}

    def check_id(eid: str) -> tuple[list[str], list[str], bool]:
        if eid not in ex_cache:
            entries = by_id.get(eid)
            if not entries:
                ex_cache[eid] = (["excerpt_missing"], [], False)
            elif len({_signature(e) for e in entries}) > 1:
                ex_cache[eid] = (["duplicate_excerpt_id"], [f"{len(entries)}개 항목"], False)
            else:
                ex_cache[eid] = _check_excerpt(entries[0], sources)
        return ex_cache[eid]

    failures: list[LinkFailure] = []
    reason_counts: Counter[str] = Counter()
    generators: Counter[str] = Counter()
    links_total = links_ok = cards_ok = 0
    referenced: set[str] = set()

    for idx, card in enumerate(cards):
        card_id = _get(card, "card_id")
        card_id = card_id if isinstance(card_id, str) and card_id else f"#{idx}"
        gen = _get(card, "generator")
        generators[str(getattr(gen, "value", gen))] += 1
        ids = _get(card, "evidence")
        if not isinstance(ids, (list, tuple)) or not ids:
            failures.append(LinkFailure(card_id=card_id, excerpt_id=None, reasons=["no_evidence"], detail=""))
            reason_counts["no_evidence"] += 1
            continue
        card_good = True
        for eid in ids:
            links_total += 1
            if not isinstance(eid, str) or not eid.strip():
                reasons, details = ["excerpt_missing"], [f"excerpt id={eid!r}"]
                eid_out = None if eid is None else str(eid)
            else:
                referenced.add(eid)
                reasons, details, _ = check_id(eid)
                eid_out = eid
            if reasons:
                card_good = False
                failures.append(
                    LinkFailure(card_id=card_id, excerpt_id=eid_out, reasons=list(reasons), detail="; ".join(details))
                )
                reason_counts.update(reasons)
            else:
                links_ok += 1
        cards_ok += card_good

    excerpts_ok = sum(1 for eid in referenced if not ex_cache[eid][0])
    hash_unchecked = sum(1 for eid in referenced if ex_cache[eid][2])
    drop = _drop_rate(_get(result, "verification"), stages)

    cards_total = len(cards)
    if cards_total == 0:
        verdict: Literal["pass", "fail", "no_cards"] = "no_cards"
    elif links_total > 0 and links_ok == links_total and cards_ok == cards_total:
        verdict = "pass"
    else:
        verdict = "fail"

    notes: list[str] = []
    if verdict == "no_cards":
        notes.append("카드 0장: 연결률은 정의 안 됨(1.0으로 세지 않는다)")
    if not drop.available:
        notes.append(drop.note)
    if hash_unchecked:
        notes.append(f"source_sha256 없는 excerpt {hash_unchecked}개: 구간 대조는 했지만 원문 전체 해시는 못 쟀다")
    status = _get(result, "status")
    status = None if status is None else str(status)
    if status not in (None, "ok"):
        notes.append(f"결과 status={status}: 강등·오류 경로가 섞인 결과다")
    if contract_note:
        notes.append(contract_note)

    session_id = _get(result, "session_id")
    plan_id = _get(result, "plan_id")
    return LinkageReport(
        checked_at=now or datetime.now(UTC),
        session_id=session_id if isinstance(session_id, str) else None,
        plan_id=plan_id if isinstance(plan_id, str) else None,
        result_status=status,
        input_kind=input_kind,
        contract_valid=contract_valid,
        verdict=verdict,
        links_total=links_total,
        links_ok=links_ok,
        linkage_rate=(links_ok / links_total) if links_total else None,
        cards_total=cards_total,
        cards_ok=cards_ok,
        card_pass_rate=(cards_ok / cards_total) if cards_total else None,
        excerpts_total=len(referenced),
        excerpts_ok=excerpts_ok,
        source_hash_unchecked=hash_unchecked,
        evidence_unreferenced=len(set(by_id) - referenced),
        card_generators=dict(generators),
        drop=drop,
        reason_counts=dict(reason_counts),
        failures=failures,
        notes=notes,
    )


# ── 원문 읽기(CLI) ────────────────────────────────────────────────────────

_SOURCE_ID_KEYS = ("review_id", "response_id", "decision_id", "post_status_id", "source_id", "id")


def _read_json_any(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".jsonl":
        # splitlines()는 U+2028 등에서도 자르므로 쓰지 않는다
        return [json.loads(line) for line in raw.split("\n") if line.strip()]
    return json.loads(raw)


def load_sources(paths: Iterable[str | Path]) -> dict[str, str]:
    """원문 파일(들)을 읽어 `source_id -> 원문` dict를 만든다.

    - `.json`: `{source_id: 원문}` dict 또는 레코드 목록
    - `.jsonl`: 한 줄에 레코드 하나(ReviewEvent·AuthorResponse·Decision·PostStatus의 JSON 등)
    - 폴더: 안의 `*.json`·`*.jsonl`(하위 폴더 제외)
    레코드 id는 review_id → response_id → decision_id → post_status_id → source_id → id 순으로 읽는다.
    `excerpt_id`가 있는 레코드(발췌)는 원문이 아니므로 건너뛴다. 같은 id에 다른 원문이면 ValueError.
    """
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in (".json", ".jsonl") and f.is_file()))
        else:
            files.append(p)
    out: dict[str, str] = {}

    def put(sid: Any, text: Any, where: Path) -> None:
        if not (isinstance(sid, str) and sid and isinstance(text, str)):
            return
        if sid in out and out[sid] != text:
            raise ValueError(f"{where}: source_id {sid!r}의 원문이 앞선 파일과 다르다")
        out[sid] = text

    for f in files:
        data = _read_json_any(f)
        if isinstance(data, Mapping) and all(isinstance(v, str) for v in data.values()):
            for sid, text in data.items():
                put(sid, text, f)
            continue
        if not isinstance(data, list):
            raise ValueError(f"{f}: 원문 파일 형식이 아니다(dict[str,str] 또는 레코드 목록)")
        for rec in data:
            if not isinstance(rec, Mapping) or "excerpt_id" in rec:
                continue
            sid = next((rec[k] for k in _SOURCE_ID_KEYS if isinstance(rec.get(k), str) and rec.get(k)), None)
            put(sid, rec.get("text"), f)
    return out


# ── CLI ───────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """종료 코드: 0 통과(또는 --allow-empty에서 카드 0장), 1 실패·카드 0장, 2 입력 오류."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="python -m eval.linkage", description="근거 연결 검사기(E5-L0)")
    ap.add_argument("--result", required=True, help="PremortemResult JSON 파일")
    ap.add_argument(
        "--sources",
        action="append",
        default=[],
        help="원문 파일·폴더(.json/.jsonl, 여러 번 가능). 없으면 모든 근거가 source_not_found로 실패한다",
    )
    ap.add_argument("--out", help="보고서 JSON을 쓸 경로(없으면 요약만 출력)")
    ap.add_argument("--allow-empty", action="store_true", help="카드 0장(음성 대조 입력)을 통과로 친다")
    args = ap.parse_args(argv)

    try:
        data = _read_json_any(Path(args.result))
        if not isinstance(data, Mapping):
            raise ValueError("결과 JSON의 최상위가 객체가 아니다")
        sources = load_sources(args.sources)
    except (OSError, ValueError) as exc:  # json.JSONDecodeError는 ValueError
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2
    if not args.sources:
        print("주의: --sources가 없다. 원문 대조를 할 수 없어 모든 근거가 실패로 집계된다", file=sys.stderr)

    report = check_result(data, sources)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report.summary())
    for fail in report.failures[:20]:
        print(f"  실패 card={fail.card_id} excerpt={fail.excerpt_id}: {', '.join(fail.reasons)}")
    if len(report.failures) > 20:
        print(f"  … 외 {len(report.failures) - 20}건(보고서 JSON 참고)")
    if report.verdict == "pass" or (report.verdict == "no_cards" and args.allow_empty):
        return 0
    return 1


__all__ = [
    "DROP_DROPPED",
    "DROP_KEPT",
    "DROP_TOTAL",
    "REASONS",
    "REPORT_SCHEMA",
    "DropRate",
    "LinkFailure",
    "LinkageReport",
    "SourceLookup",
    "check_result",
    "load_sources",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
