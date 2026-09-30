"""규칙 기반 점검 추출기(FIN-TOOLS): 계획서 문장에서 검사할 주장을 뽑아 코드가 정한 도구 호출(ToolCall)로 만든다.

LLM이 검사를 제안하지 않아도(mock 포함) 원문에 적힌 수치·단위·합계·일정·절 참조·인용이 있으면 검사가 생긴다.
도구 선택은 `fin_tools.FIN_TOOL_FOR_KIND` 표가 정하고(엔진 이름 z3·pint·networkx 별칭), 인자는 원문에서 코드가 뽑는다. 각 검사에는 근거 위치
(`anchors`: 줄·시작·끝·원문 글자 그대로)가 붙는다. 인용 문자열은 코드가 원문에서 잘라 붙인다.

뽑는 것(라벨 → 점검 유형 → 도구)
- split_sum      · 학습/검증/테스트 분할 비율(80/10/10, 70%·15%·15%)·건수 분할 합   → sum → arithmetic_sum
- schedule_sum   · 일정 단계 기간(N개월) 합 = 총 기간 / schedule_span · M1–M9 범위 ≤ 총 기간 → sum
- budget_sum     · 예산 항목(원·만원·억원) 합 = 총액                                  → sum
- table_sum      · 표의 행 합계 열·합계 행                                           → sum
- expr_sum       · 원문 산식 ``a + b = c``(같은 단위)                                 → sum
- arith_expr     · 원문 산식 ``a × b = c``(단위 없는 수)                              → arithmetic → calculator
- unit_derive    · 단위가 붙은 산식(a / b = c)·"초당 R개로 A개를 처리하면 T" 규모 검사   → unit → unit_dimension(derive)
- unit_add       · 단위가 붙은 두 수의 덧셈(``10 mS + 1 S/cm``)                        → unit → unit_dimension(add)
- unit_compare   · 단위가 붙은 두 수의 부등식(``120 GB ≤ 80 GB``)                      → unit → unit_dimension(compare)
- sections       · 필수 절(배경·질문·가설·방법·데이터·평가·일정·위험·기대효과) 존재·순서·번호 → structure
- references     · §N·제N장·N절 참조·표 N·그림 N 참조                                  → reference → structure
- citation       · DOI·따옴표 제목(연도)                                              → citation → citation_lookup

정직성: Codex 규칙(`final_tools._QUALIFIED_NUMERIC`)에 걸리는 줄(부정·가정·근사·조건)의 수치는 뽑지 않는다. 뜻이 둘로 읽히는
경우(항목 줄에 금액이 둘, 병행 일정, 단위가 섞인 합)는 뽑지 않는다(오탐보다 누락). 뽑히지 않은 것은 "검사 안 함"이지 통과가 아니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from neumann.finalize.tools import ToolCall
from neumann.finalize.tools.fin_tools import FIN_TOOL_FOR_KIND
from neumann.finalize.tools.quantities import Quantity, parse_decimal, qualified, scan_line
from neumann.finalize.tools.structure import (
    LABELS, detect_captions, detect_headings, detect_references,
)

MAX_TEXT = 200_000
MAX_LINES = 5000
MAX_CHECKS = 32
MAX_PER_LABEL = 8
REQUIRED_SECTIONS = [LABELS[k] for k in LABELS]

SPLIT_WORDS = re.compile(r"train|valid|\bval\b|\bdev\b|test|학습|훈련|검증|테스트|시험|분할|split|나누|나눈", re.I)
SPLIT_GROUPS = (re.compile(r"train|학습|훈련", re.I), re.compile(r"valid|\bval\b|\bdev\b|검증", re.I),
                re.compile(r"test|테스트|시험", re.I))
SLASH_GROUP = re.compile(r"(?<![\d.,/:])(\d{1,3}(?:\.\d+)?)((?:\s*/\s*\d{1,3}(?:\.\d+)?){1,4})(?![\d/.]\d|/)")
TOTAL_HINT = re.compile(r"총|전체|합계|합산|total|overall|(?:^|[|\s])계(?:\s*[|:]|\s*$)", re.I)
PERIOD_HINT = re.compile(r"(?:연구|과제|사업|전체|총)\s*기간|period|duration", re.I)
SCHEDULE_ITEM = re.compile(r"단계|phase|stage|\bWP\s*\d|work\s*package|과제|차년도|\bM\d|마일스톤|milestone|\d\s*차(?![가-힣])", re.I)
PARALLEL = re.compile(r"병행|동시|병렬|중첩|겹|parallel|overlap|concurrent", re.I)
BUDGET_HEAD = re.compile(r"예산|연구비|사업비|소요\s*비용|budget|cost", re.I)
BUDGET_ITEM = re.compile(r"인건비|장비|재료|여비|간접비|활동비|위탁|전산|클라우드|운영비|수당|budget|cost|비용", re.I)
MONTH_RANGE = re.compile(r"M\s?(\d{1,2})\s*[~–—-]\s*M?\s?(\d{1,2})(?!\d)|(?<![\d.])(\d{1,2})\s*[~–—-]\s*(\d{1,2})\s*(?:개월|월차|months?)")
DERIVE_VERB = re.compile(r"걸리|걸린|소요|필요|완료|처리|학습|수집|생성|takes?|requires?|needs?|process", re.I)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>)\]　,;]+")
TITLE_RE = re.compile(r"[“\"]([^”\"]{15,200})[”\"]")
YEAR_RE = re.compile(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)")
_OPS = {"+": "+", "-": "-", "−": "-", "×": "*", "x": "*", "X": "*", "*": "*", "/": "/", "÷": "/"}
_TO_MONTHS = {"month": Fraction(1), "year": Fraction(12), "quarter_year": Fraction(3)}
_COUNT_UNITS = {"count", "sample", "record", "token", "person", "step", "parameter", "epoch"}


@dataclass(frozen=True)
class ExtractedCheck:
    """추출된 검사 1건. ``call``은 FIN-ENGINE 레지스트리에 그대로 넣는 도구 호출이다."""

    check_id: str
    kind: str
    label: str
    plan_lines: tuple[int, ...]
    anchors: tuple[dict[str, Any], ...]
    call: ToolCall
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def tool(self) -> str:
        return self.call.name

    def as_dict(self) -> dict[str, Any]:
        return {"check_id": self.check_id, "kind": self.kind, "label": self.label, "tool": self.tool,
                "plan_lines": list(self.plan_lines), "anchors": [dict(a) for a in self.anchors],
                "call": self.call.as_dict(), "notes": list(self.notes)}


def _num_arg(value: Fraction) -> int | str:
    """정확한 수를 JSON으로: 정수는 int, 나머지는 십진 문자열(부동소수 오차 없이 도구가 다시 읽는다)."""
    if value.denominator == 1:
        return value.numerator
    d = value.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    if d == 1:
        digits = 0
        while (value * 10**digits).denominator != 1:
            digits += 1
        scaled = abs(value * 10**digits).numerator
        whole, frac = divmod(scaled, 10**digits)
        return f"{'-' if value < 0 else ''}{whole}.{str(frac).rjust(digits, '0')}"
    return f"{float(value):.15g}"


def _anchor(line_no: int, line: str, start: int, end: int) -> dict[str, Any]:
    return {"line": line_no, "start": start, "end": end, "text": line[start:end]}


class _Builder:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.out: list[ExtractedCheck] = []
        self.counts: dict[str, int] = {}
        self.used_lines: set[int] = set()

    def add(self, label: str, kind: str, anchors: list[dict[str, Any]], args: dict[str, Any],
            notes: tuple[str, ...] = ()) -> None:
        if self.counts.get(label, 0) >= MAX_PER_LABEL or kind not in FIN_TOOL_FOR_KIND:
            return
        self.counts[label] = self.counts.get(label, 0) + 1
        plan_lines = tuple(sorted({a["line"] for a in anchors}))
        check_id = f"{label}-{plan_lines[0] if plan_lines else 0}-{self.counts[label]}"
        self.out.append(ExtractedCheck(check_id, kind, label, plan_lines, tuple(anchors),
                                       ToolCall(FIN_TOOL_FOR_KIND[kind], args, check_id=check_id), notes))


# ── 섹션 정보 ─────────────────────────────────────────────────────────────


def _section_index(lines: list[str]) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    line_map = {i: t for i, t in enumerate(lines, start=1)}
    heads = detect_headings(line_map)
    owner: dict[int, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    idx = 0
    for no in range(1, len(lines) + 1):
        while idx < len(heads) and heads[idx]["line"] <= no:
            current = heads[idx]
            idx += 1
        if current is not None:
            owner[no] = current
    return heads, owner


def _in_section(owner: dict[int, dict[str, Any]], no: int, key: str | None = None, pattern: re.Pattern[str] | None = None) -> bool:
    head = owner.get(no)
    if not head or head["line"] == no:
        return False
    if key is not None and key in head["canonical"]:
        return True
    return bool(pattern and pattern.search(head["title"]))


# ── 합계: 분할 비율 ─────────────────────────────────────────────────────


def _split_sums(b: _Builder, quants: dict[int, list[Quantity]]) -> None:
    for no, line in enumerate(b.lines, start=1):
        if qualified(line) or not SPLIT_WORDS.search(line):
            continue
        groups = sum(1 for g in SPLIT_GROUPS if g.search(line))
        if groups < 2 and not re.search(r"분할|split|나누|나눈", line, re.I):
            continue
        m = SLASH_GROUP.search(line)
        if m:
            parts = [m.group(1)] + re.findall(r"\d{1,3}(?:\.\d+)?", m.group(2))
            values = [parse_decimal(p) for p in parts]
            if None in values or len(values) < 2:
                continue
            total = Fraction(1) if all(v <= 1 for v in values) and sum(values) <= Fraction(3, 2) else Fraction(100)
            b.add("split_sum", "sum", [_anchor(no, line, m.start(), m.end())],
                  {"items": [_num_arg(v) for v in values], "total": _num_arg(total), "unit": "percent" if total == 100 else "fraction"})
            b.used_lines.add(no)
            continue
        pct = [q for q in quants.get(no, []) if q.family == "percent"]
        if len(pct) >= 2:
            b.add("split_sum", "sum", [q.anchor() for q in pct],
                  {"items": [_num_arg(q.value) for q in pct], "total": 100, "unit": "percent"})
            b.used_lines.add(no)
            continue
        counts = [q for q in quants.get(no, []) if q.unit in _COUNT_UNITS and q.rate_of is None]
        if len(counts) >= 3 and len({q.unit for q in counts}) == 1:
            first = counts[0]
            after, before = line[first.end:first.end + 4], line[max(0, first.start - 6):first.start]
            if re.search(r"중|of", after) or re.search(r"총|전체|total", before, re.I):
                b.add("split_sum", "sum", [q.anchor() for q in counts],
                      {"items": [_num_arg(q.value) for q in counts[1:]], "total": _num_arg(first.value), "unit": first.unit})
                b.used_lines.add(no)


# ── 합계: 표 ─────────────────────────────────────────────────────────────


def _cells(line: str) -> list[tuple[int, int, str]]:
    """``| a | b |`` → [(시작, 끝, 칸 글자)] (앞뒤 공백 제외 오프셋)."""
    out = []
    pos = line.index("|") + 1 if "|" in line else 0
    while True:
        nxt = line.find("|", pos)
        if nxt < 0:
            break
        raw = line[pos:nxt]
        lead = len(raw) - len(raw.lstrip())
        text = raw.strip()
        out.append((pos + lead, pos + lead + len(text), text))
        pos = nxt + 1
    return out


def _cell_value(line: str, no: int, start: int, end: int) -> Quantity | None:
    qs = [q for q in scan_line(line[:end], no) if q.start >= start]
    if len(qs) != 1 or qs[0].rate_of:
        return None
    rest = line[qs[0].end:end].strip()
    return qs[0] if not rest else None


def _table_sums(b: _Builder) -> None:
    i, n = 0, len(b.lines)
    while i < n:
        if not b.lines[i].lstrip().startswith("|"):
            i += 1
            continue
        j = i
        while j < n and b.lines[j].lstrip().startswith("|"):
            j += 1
        block = list(range(i + 1, j + 1))  # 줄 번호(1부터)
        i = j
        if len(block) < 4:
            continue
        header = _cells(b.lines[block[0] - 1])
        body = [no for no in block[1:] if not re.fullmatch(r"[\s|:\-]*", b.lines[no - 1])]
        if not header or len(body) < 2:
            continue
        rows = {no: _cells(b.lines[no - 1]) for no in body}
        if any(len(c) != len(header) for c in rows.values()):
            continue
        # 합계 열: 마지막 머리칸이 합계·계·total
        if TOTAL_HINT.search(header[-1][2]):
            for no, cells in rows.items():
                line = b.lines[no - 1]
                if qualified(line) or TOTAL_HINT.search(cells[0][2]):
                    continue
                vals = [_cell_value(line, no, s, e) for s, e, _ in cells[1:]]
                if any(v is None for v in vals) or len(vals) < 3 or len({v.unit for v in vals}) != 1:
                    continue
                b.add("table_sum", "sum", [v.anchor() for v in vals],
                      {"items": [_num_arg(v.value) for v in vals[:-1]], "total": _num_arg(vals[-1].value),
                       "unit": vals[-1].unit or "", "labels": [cells[0][2][:80]] * (len(vals) - 1)})
                b.used_lines.add(no)
        # 합계 행: 첫 칸이 합계·계·total인 행 → 열마다 위 행들의 합
        totals = [no for no, cells in rows.items() if TOTAL_HINT.search(cells[0][2])]
        if len(totals) != 1:
            continue
        tno = totals[0]
        others = [no for no in body if no != tno]
        if qualified(b.lines[tno - 1]) or any(qualified(b.lines[no - 1]) for no in others) or len(others) < 2:
            continue
        for col in range(1, len(header)):
            tline = b.lines[tno - 1]
            s, e, _ = rows[tno][col]
            tv = _cell_value(tline, tno, s, e)
            vals = [_cell_value(b.lines[no - 1], no, *rows[no][col][:2]) for no in others]
            if tv is None or any(v is None for v in vals) or len({v.unit for v in vals} | {tv.unit}) != 1:
                continue
            b.add("table_sum", "sum", [v.anchor() for v in vals] + [tv.anchor()],
                  {"items": [_num_arg(v.value) for v in vals], "total": _num_arg(tv.value), "unit": tv.unit or "",
                   "labels": [rows[no][0][2][:80] for no in others]})
            b.used_lines.update(others + [tno])


# ── 합계: 일정·예산 ─────────────────────────────────────────────────────


def _durations(quants: list[Quantity], line: str) -> list[Quantity]:
    ranges = [(m.start(), m.end()) for m in MONTH_RANGE.finditer(line)]
    return [q for q in quants if q.unit in _TO_MONTHS or q.unit == "week"
            if q.rate_of is None and not any(s <= q.start < e for s, e in ranges)]


def _cluster(item_lines: list[int], anchor: int, max_gap: int = 2) -> set[int]:
    """총계 줄에서 시작해 줄 간격 max_gap 이하로 이어지는 항목 줄만 남긴다(멀리 떨어진 같은 종류의 수를 섞지 않는다)."""
    keep: set[int] = set()
    lines = sorted(set(item_lines))
    for direction in (-1, 1):
        edge = anchor
        for no in (reversed([n for n in lines if n < anchor]) if direction < 0 else [n for n in lines if n > anchor]):
            if abs(no - edge) > max_gap + 1:
                break
            keep.add(no)
            edge = no
    return keep


def _schedule_sums(b: _Builder, quants: dict[int, list[Quantity]], owner: dict[int, dict[str, Any]]) -> None:
    items: list[tuple[int, Quantity]] = []
    spans: list[tuple[int, re.Match[str]]] = []
    totals: list[tuple[int, Quantity]] = []
    parallel = False
    for no, line in enumerate(b.lines, start=1):
        if no in b.used_lines or qualified(line):
            continue
        in_sched = _in_section(owner, no, "schedule")
        durs = _durations(quants.get(no, []), line)
        hinted = TOTAL_HINT.search(line) or PERIOD_HINT.search(line)
        if hinted and len(durs) == 1 and (in_sched or PERIOD_HINT.search(line)):
            totals.append((no, durs[0]))
            continue
        if not (in_sched or SCHEDULE_ITEM.search(line)):
            continue
        if PARALLEL.search(line):
            parallel = True
        if len(durs) == 1 and SCHEDULE_ITEM.search(line) or (len(durs) == 1 and in_sched and not hinted):
            items.append((no, durs[0]))
        for m in MONTH_RANGE.finditer(line):
            if SCHEDULE_ITEM.search(line) or in_sched:
                spans.append((no, m))
    if len({t.value * _TO_MONTHS.get(t.unit, 1) for _, t in totals}) != 1 or parallel:
        return  # 총 기간이 없거나 둘 이상이면(또는 병행 일정) 판정하지 않는다
    tno, total = totals[0]
    t_months = total.value * _TO_MONTHS[total.unit] if total.unit in _TO_MONTHS else None
    has_section = any(_in_section(owner, no, "schedule") for no, _ in items + spans)
    if has_section:  # 일정 절이 있으면 그 절 안의 항목만
        items = [(no, q) for no, q in items if _in_section(owner, no, "schedule")]
        spans = [(no, m) for no, m in spans if _in_section(owner, no, "schedule")]
    else:  # 없으면 총계 줄 주변에 이어진 항목만
        near = _cluster([no for no, _ in items] + [no for no, _ in spans], tno)
        items = [(no, q) for no, q in items if no in near]
        spans = [(no, m) for no, m in spans if no in near]
    if len(items) >= 2:
        units = {q.unit for _, q in items} | {total.unit}
        if units <= set(_TO_MONTHS):
            values = [q.value * _TO_MONTHS[q.unit] for _, q in items]
            total_v, unit = t_months, "month"
        elif units == {"week"}:
            values, total_v, unit = [q.value for _, q in items], total.value, "week"
        else:
            values = []
        if values and total_v is not None:
            b.add("schedule_sum", "sum", [q.anchor() for _, q in items] + [total.anchor()],
                  {"items": [_num_arg(v) for v in values], "total": _num_arg(total_v), "unit": unit,
                   "labels": [b.lines[no - 1].strip()[:80] for no, _ in items]})
            b.used_lines.update([no for no, _ in items] + [tno])
            return
    if len(spans) >= 2 and t_months is not None:
        ends = [int(m.group(2) or m.group(4)) for _, m in spans]
        starts = [int(m.group(1) or m.group(3)) for _, m in spans]
        if all(s <= e for s, e in zip(starts, ends)):
            line_of = {no: b.lines[no - 1] for no, _ in spans}
            b.add("schedule_span", "sum",
                  [_anchor(no, line_of[no], m.start(), m.end()) for no, m in spans] + [total.anchor()],
                  {"items": [max(ends)], "total": _num_arg(t_months), "relation": "le", "unit": "month",
                   "labels": ["마지막 월차"]}, notes=("범위 일정: 마지막 월차가 총 기간을 넘지 않는지만 본다",))
            b.used_lines.update([no for no, _ in spans] + [tno])


def _budget_sums(b: _Builder, quants: dict[int, list[Quantity]], owner: dict[int, dict[str, Any]]) -> None:
    items: list[tuple[int, Quantity]] = []
    totals: list[tuple[int, Quantity]] = []
    ambiguous = False
    for no, line in enumerate(b.lines, start=1):
        if no in b.used_lines or qualified(line):
            continue
        money = [q for q in quants.get(no, []) if q.family == "currency" and q.rate_of is None]
        if not money:
            continue
        in_budget = _in_section(owner, no, pattern=BUDGET_HEAD)
        if not (in_budget or BUDGET_ITEM.search(line) or TOTAL_HINT.search(line)):
            continue
        hint = TOTAL_HINT.search(line)
        if len(money) >= 3 and hint:  # 한 줄 안: "인건비 3억 원, 장비비 2억 원, 총 5억 원"
            tot = [q for q in money if TOTAL_HINT.search(line[max(0, q.start - 8):q.start])]
            if len(tot) == 1:
                rest = [q for q in money if q is not tot[0]]
                b.add("budget_sum", "sum", [q.anchor() for q in money],
                      {"items": [_num_arg(q.value) for q in rest], "total": _num_arg(tot[0].value), "unit": tot[0].unit})
                b.used_lines.add(no)
            continue
        if len(money) != 1:
            if in_budget or BUDGET_ITEM.search(line):
                ambiguous = True  # 항목 줄에 금액이 둘 이상(연차별·괄호 설명) — 뜻이 둘로 읽힌다
            continue
        if hint:
            totals.append((no, money[0]))
        elif in_budget or BUDGET_ITEM.search(line):
            items.append((no, money[0]))
    # 총액 줄: 예산 절 안이거나, 예산을 말하거나, 항목 줄 바로 곁(3줄 이내)
    item_lines = [no for no, _ in items]
    totals = [(no, q) for no, q in totals if _in_section(owner, no, pattern=BUDGET_HEAD)
              or re.search(r"예산|연구비|사업비|budget", b.lines[no - 1], re.I)
              or any(abs(no - i) <= 3 for i in item_lines)]
    if ambiguous or len(totals) != 1:
        return
    tno, total = totals[0]
    if any(_in_section(owner, no, pattern=BUDGET_HEAD) for no, _ in items + totals):
        items = [(no, q) for no, q in items if _in_section(owner, no, pattern=BUDGET_HEAD)]
    else:
        near = _cluster([no for no, _ in items], tno)
        items = [(no, q) for no, q in items if no in near]
    if len(items) < 2 or len({q.unit for _, q in items} | {total.unit}) != 1:
        return
    b.add("budget_sum", "sum", [q.anchor() for _, q in items] + [total.anchor()],
          {"items": [_num_arg(q.value) for _, q in items], "total": _num_arg(total.value), "unit": total.unit,
           "labels": [b.lines[no - 1].strip()[:80] for no, _ in items]})
    b.used_lines.update([no for no, _ in items] + [tno])


# ── 산식·단위 ────────────────────────────────────────────────────────────


def _op_between(line: str, a: Quantity, c: Quantity) -> str | None:
    gap = line[a.end:c.start]
    m = re.fullmatch(r"\s*([+\-−×xX*/÷])\s*", gap)
    if not m:
        return None
    op = m.group(1)
    if op == "-" and not (gap.startswith(" ") and gap.endswith(" ")):
        return None  # 1-3은 범위다
    if op in "xX" and not (gap.startswith(" ") and gap.endswith(" ")):
        return None
    return _OPS[op]


def _quantity_arg(q: Quantity, unit: str | None = None) -> dict[str, Any]:
    return {"value": _num_arg(q.value), "unit": unit or q.pint_unit or "count"}


def _expressions(b: _Builder, quants: dict[int, list[Quantity]]) -> None:
    for no, line in enumerate(b.lines, start=1):
        qs = quants.get(no, [])
        if len(qs) < 2 or qualified(line):
            continue
        eq = [m.start() for m in re.finditer(r"=|＝", line)]
        handled: set[int] = set()
        for pos in eq:
            after = [q for q in qs if q.start > pos]
            if not after or line[pos + 1:after[0].start].strip():
                continue
            result = after[0]
            before = [q for q in qs if q.end <= pos]
            if not before or line[before[-1].end:pos].strip():
                continue
            chain, ops = [before[-1]], []
            k = len(before) - 1
            while k > 0:
                op = _op_between(line, before[k - 1], before[k])
                if op is None:
                    break
                chain.insert(0, before[k - 1])
                ops.insert(0, op)
                k -= 1
            if not ops or len(chain) > 8:
                continue
            anchors = [q.anchor() for q in chain + [result]]
            units = [q.pint_unit for q in chain + [result]]
            handled.update(id(q) for q in chain + [result])
            if set(ops) == {"+"} and len(set(units)) == 1:
                b.add("expr_sum", "sum", anchors, {"items": [_num_arg(q.value) for q in chain],
                                                   "total": _num_arg(result.value), "unit": units[0] or ""})
            elif set(ops) <= {"*", "/"} and all(units):
                factors = [dict(_quantity_arg(chain[0]), power=1)]
                factors += [dict(_quantity_arg(q), power=1 if op == "*" else -1) for q, op in zip(chain[1:], ops)]
                b.add("unit_derive", "unit", anchors, {"operation": "derive", "factors": factors,
                                                        "expected": _quantity_arg(result)})
            elif not any(units):
                expr = _num_arg(chain[0].value)
                for q, op in zip(chain[1:], ops):
                    expr = f"{expr}{op}{_num_arg(q.value)}"
                b.add("arith_expr", "arithmetic", anchors,
                      {"expression": str(expr), "expected": _num_arg(result.value),
                       "tolerance": _half_unit(result.number_text)})
        # 등호 밖의 단위 덧셈·부등식
        for a, c in zip(qs, qs[1:]):
            if id(a) in handled or not (a.pint_unit and c.pint_unit):
                continue
            gap = line[a.end:c.start]
            if re.fullmatch(r"\s*\+\s*", gap) and (a.unit != c.unit or a.family != c.family):
                b.add("unit_add", "unit", [a.anchor(), c.anchor()],
                      {"operation": "add", "left": _quantity_arg(a), "right": _quantity_arg(c)})
            rel = re.fullmatch(r"\s*(≤|<=|<|≥|>=|>)\s*", gap)
            if rel:
                relation = {"≤": "le", "<=": "le", "<": "lt", "≥": "ge", ">=": "ge", ">": "gt"}[rel.group(1)]
                b.add("unit_compare", "unit", [a.anchor(), c.anchor()],
                      {"operation": "compare", "relation": relation, "left": _quantity_arg(a),
                       "right": _quantity_arg(c)})


def _half_unit(number_text: str) -> float:
    text = number_text.replace(",", "")
    if "e" in text.lower():
        return 0.0
    decimals = len(text.split(".", 1)[1]) if "." in text else 0
    return 0.5 * 10 ** (-decimals) if decimals else 0.0


def _rate_derivations(b: _Builder, quants: dict[int, list[Quantity]]) -> None:
    """"초당 1,000개로 1억 개를 처리하면 10시간" → 1억 개 ÷ (1,000개/초) ≈ 10시간(Pint 규모 검사)."""
    for no, line in enumerate(b.lines, start=1):
        qs = [q for q in quants.get(no, [])]
        if len(qs) < 3 or qualified(line) or "=" in line or not DERIVE_VERB.search(line):
            continue
        rates = [q for q in qs if q.rate_of is not None]
        times = [q for q in qs if q.family == "time" and q.rate_of is None]
        if len(rates) != 1 or len(times) != 1:
            continue
        rate = rates[0]
        base = rate.unit or "count"
        amounts = [q for q in qs if q.rate_of is None and q.unit and q is not times[0]
                   and (q.unit == base or (q.unit in _COUNT_UNITS and base in _COUNT_UNITS))]
        if len(amounts) != 1:
            continue
        amount = amounts[0]
        unit = amount.unit if amount.unit != "count" else base  # 일반 개수(개·장)는 구체 단위(샘플·건)에 맞춘다
        b.add("unit_derive", "unit", [amount.anchor(), rate.anchor(), times[0].anchor()],
              {"operation": "derive",
               "factors": [dict(_quantity_arg(amount, unit), power=1),
                           dict(_quantity_arg(rate, f"({unit}) / {rate.rate_of}"), power=-1)],
               "expected": _quantity_arg(times[0])})


# ── 구조·참조·인용 ───────────────────────────────────────────────────────


def _structure(b: _Builder, heads: list[dict[str, Any]]) -> None:
    if len(heads) < 2:
        return
    line_map = {i: t for i, t in enumerate(b.lines, start=1)}
    caps = detect_captions(line_map)
    keep = {h["line"] for h in heads} | {c["line"] for c in caps}
    sparse = {str(no): b.lines[no - 1] for no in sorted(keep)}
    anchors = [_anchor(h["line"], b.lines[h["line"] - 1], 0, len(b.lines[h["line"] - 1])) for h in heads[:40]]
    b.add("sections", "structure", anchors, {"line_map": sparse, "required_sections": list(REQUIRED_SECTIONS),
                                             "checks": ["sections", "order", "numbering"]})
    refs = detect_references(line_map, {h["line"] for h in heads})
    if refs:
        b.add("references", "reference", [_anchor(r["line"], b.lines[r["line"] - 1], r["start"], r["end"]) for r in refs[:40]],
              {"line_map": sparse, "references": [{"line": r["line"], "ref": r["ref"]} for r in refs[:200]],
               "required_sections": [], "checks": ["references"]})


def _citations(b: _Builder) -> None:
    for no, line in enumerate(b.lines, start=1):
        for m in DOI_RE.finditer(line):
            doi = m.group().rstrip(".,;:")
            b.add("citation", "citation", [_anchor(no, line, m.start(), m.start() + len(doi))], {"doi": doi})
        for m in TITLE_RE.finditer(line):
            year = YEAR_RE.search(line[m.end():m.end() + 20]) or YEAR_RE.search(line[max(0, m.start() - 20):m.start()])
            if not year and not re.search(r"et al|등\s*\(|\bDOI\b|arXiv|journal|학회|학술지", line, re.I):
                continue
            args: dict[str, Any] = {"title": m.group(1).strip()}
            if year:
                args["year"] = int(year.group(1))
            b.add("citation", "citation", [_anchor(no, line, m.start(1), m.end(1))], args)


# ── 공개 함수 ────────────────────────────────────────────────────────────


def extract_checks(plan_text: str, *, max_checks: int = MAX_CHECKS) -> list[ExtractedCheck]:
    """계획서 원문 → 검사 목록(줄 순). 입력은 20만 자·5,000줄까지 본다. 예외를 던지지 않는다(뽑지 못하면 빈 목록)."""
    if type(plan_text) is not str or not plan_text.strip():
        return []
    lines = plan_text[:MAX_TEXT].splitlines()[:MAX_LINES]
    b = _Builder(lines)
    try:
        heads, owner = _section_index(lines)
        quants = {no: scan_line(line, no) for no, line in enumerate(lines, start=1)}
        _table_sums(b)
        _split_sums(b, quants)
        _schedule_sums(b, quants, owner)
        _budget_sums(b, quants, owner)
        _expressions(b, quants)
        _rate_derivations(b, quants)
        _structure(b, heads)
        _citations(b)
    except Exception:  # noqa: BLE001 — 추출 실패는 "검사 없음"이지 통과가 아니다(엔진이 표시)
        return sorted(b.out, key=lambda c: (c.plan_lines[:1], c.check_id))[:max_checks]
    return sorted(b.out, key=lambda c: (c.plan_lines[:1] or (0,), c.check_id))[:max_checks]


def run_checks(checks: list[ExtractedCheck], *, reg: Any = None, cancel_event: Any = None) -> list[dict[str, Any]]:
    """추출한 검사를 돌린다: 엔진 이름(z3·pint·networkx)은 FIN-ENGINE 레지스트리(FIN-TOOLS 구현 등록)로,
    citation_lookup은 FIN-TOOLS 안에서(같은 ToolResult 모양). → [{check, result}]"""
    from neumann.finalize.tools.fin_tools import run_call

    out = []
    for check in checks:
        result = run_call(check.call, reg=reg, cancel_event=cancel_event)
        out.append({"check": check.as_dict(), "result": result.as_dict()})
    return out


__all__ = ["ExtractedCheck", "REQUIRED_SECTIONS", "extract_checks", "run_checks"]
