"""structure 도구(FIN-TOOLS): 필수 절·순서·번호 체계·절/표/그림 참조를 NetworkX 그래프로 검사한다.

그래프: ``doc`` → 절(번호가 있으면 ``sec:3`` → ``sec:3.1`` 계층) · 표(``tbl:N``) · 그림(``fig:N``) 정의 노드,
참조는 "참조가 있는 줄을 담은 절 → 대상" 간선이다. 정의되지 않은 대상으로 가는 간선이 깨진 참조다.
번호 형제(1,2,4)의 빈 번호·중복 번호, 필수 절 누락, 정해진 순서에서 벗어난 절을 함께 본다.

args(FIN-ENGINE 계약 + 추가)
``{"lines": [줄…] 또는 "line_map": {"줄번호": 줄}, "required_sections": [키/한국어 이름…], "references"?: [{"line", "ref"}],
"order"?: [키…], "checks"?: ["sections", "order", "references", "numbering"]}``
references를 주지 않으면 줄에서 직접 찾는다. 제목이 하나도 없으면 unchecked(평문 계획서를 누락으로 판정하지 않는다).
"""

from __future__ import annotations

import importlib
import re
from typing import Any

VERSION = "fin-tools.structure@1"
MAX_LINES = 5000
MAX_LINE_CHARS = 2000
MAX_REPORT = 50
MAX_REFS = 500  # 참조는 앞에서부터 500개까지만 본다(적대적 입력의 시간 상한)

# (키, 한국어 이름, 제목에서 찾는 낱말). 순서가 기준 순서다(대표 지시: 배경·질문·가설·방법·데이터·평가·일정·위험·기대효과).
SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("background", "배경", ("배경", "필요성", "동기", "서론", "background", "motivation", "introduction")),
    ("question", "연구 질문", ("질문", "문제 정의", "문제정의", "목표", "목적", "research question", "question",
                            "objective", "aim", "problem statement")),
    ("hypothesis", "가설", ("가설", "hypothes")),
    ("method", "방법", ("방법", "접근", "설계", "method", "approach", "design")),
    ("data", "데이터", ("데이터", "자료", "data")),
    ("evaluation", "평가", ("평가", "검증 계획", "지표", "evaluation", "metric", "validation")),
    ("schedule", "일정", ("일정", "추진 계획", "추진계획", "타임라인", "마일스톤", "schedule", "timeline", "milestone",
                         "work plan")),
    ("risk", "위험", ("위험", "리스크", "한계", "risk", "limitation")),
    ("impact", "기대효과", ("기대효과", "기대 효과", "기대 성과", "기대성과", "파급", "활용", "impact", "outcome",
                         "deliverable")),
)
KEYS = tuple(k for k, _, _ in SECTIONS)
LABELS = {k: label for k, label, _ in SECTIONS}
_LABEL_TO_KEY = {label: k for k, label, _ in SECTIONS} | {"질문": "question", "기대 효과": "impact"}

_NUM = r"\d{1,2}(?:\.\d{1,2}){0,3}"
MD_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
NUM_HEADING = re.compile(rf"^\s{{0,3}}(?:§\s*)?(?:제\s*)?({_NUM})(?:\s*[장절])?[.)]?\s+(\S.*)$")
ROMAN_HEADING = re.compile(r"^\s{0,3}([IVX]{1,4}|[Ⅰ-Ⅻ])[.)]\s+(\S.*)$")
BOLD_HEADING = re.compile(r"^\s{0,3}\*\*([^*]{1,60})\*\*\s*:?\s*$")
BRACKET_HEADING = re.compile(r"^\s{0,3}[\[【]([^\]】]{1,40})[\]】]\s*$")
TITLE_NUMBER = re.compile(rf"^(?:§\s*)?(?:제\s*)?({_NUM})(?:\s*[장절])?[.)]?\s+")
_SENTENCE_END = re.compile(r"(?:다|요|함|음|임)\.?\s*$|[.?!]\s*$")

SEC_REF = re.compile(
    rf"§\s*({_NUM})|제\s*({_NUM})\s*[장절]|(?<![\d.])({_NUM})\s*[장절]\s*(?:참조|참고|에서|을\s*보|를\s*보)"
    rf"|(?:Section|Sec\.|섹션)\s*({_NUM})",
    re.I,
)
TF_REF = re.compile(r"(표|Table|그림|Figure|Fig\.)\s*(\d{1,3})(?![\d.]\d)", re.I)
# 캡션(정의): 줄 맨 앞 "표 1." "표 1:" "<표 1>" "[그림 2]" "**Table 3.**" — 번호 뒤 구두점이 있어야 한다("표 1 참조"는 참조다)
CAPTION = re.compile(r"^\s{0,3}[<\[*_!]*\s*(?:\[\s*)?(표|Table|그림|Figure|Fig\.)\s*(\d{1,3})(?!\d)\s*[.:>\])*]", re.I)
REF_ARG = re.compile(rf"^(?:§\s*({_NUM})|(표|그림)\s*(\d{{1,3}}))$")


def _kind(word: str) -> str:
    return "tbl" if word.lower() in ("표", "table") else "fig"


def canonical_keys(title: str) -> list[str]:
    t = title.lower()
    return [k for k, _, words in SECTIONS if any(w in t for w in words)]


def detect_headings(lines: dict[int, str]) -> list[dict[str, Any]]:
    """줄 번호(1부터) → 줄. 마크다운 제목이 2개 이상이면 마크다운 제목만, 아니면 번호·로마자·굵은 줄을 제목으로 본다."""
    md = []
    for no, text in lines.items():
        m = MD_HEADING.match(text[:MAX_LINE_CHARS])
        if m:
            md.append((no, len(m.group(1)), m.group(2).strip()))
    heads: list[tuple[int, int, str]] = list(md)
    if len(md) < 2:  # 마크다운 제목이 0~1개(문서 제목뿐)면 번호·로마자·굵은 줄 제목도 본다
        for no, text in lines.items():
            text = text[:MAX_LINE_CHARS]
            if MD_HEADING.match(text):
                continue
            m = NUM_HEADING.match(text)
            if m and len(m.group(2)) <= 40 and not _SENTENCE_END.search(m.group(2)):
                heads.append((no, m.group(1).count(".") + 2, text.strip()))
                continue
            m = ROMAN_HEADING.match(text) or BOLD_HEADING.match(text) or BRACKET_HEADING.match(text)
            if m and len(text.strip()) <= 50 and not _SENTENCE_END.search(text.strip().rstrip("*:]】")):
                heads.append((no, 2, text.strip().strip("*[]【】: ")))
    out = []
    for no, level, title in sorted(heads):
        num = TITLE_NUMBER.match(title.lstrip("#").strip())
        out.append({"line": no, "level": level, "title": title[:120], "number": num.group(1) if num else None,
                    "canonical": canonical_keys(title)})
    return out


def detect_references(lines: dict[int, str], heading_lines: set[int]) -> list[dict[str, Any]]:
    """절 참조(§3, 제3장, 3절 참조, Section 3)와 표·그림 참조(캡션 줄의 맨 앞 이름표는 정의이지 참조가 아니다)."""
    refs: list[dict[str, Any]] = []
    for no, text in sorted(lines.items()):
        if len(refs) >= MAX_REFS:
            break
        if no in heading_lines:
            continue
        text = text[:MAX_LINE_CHARS]
        for m in SEC_REF.finditer(text):
            num = next(g for g in m.groups() if g)
            refs.append({"line": no, "ref": f"§{num}", "start": m.start(), "end": m.end(), "text": m.group()})
        cap = CAPTION.match(text)
        for m in TF_REF.finditer(text):
            if cap and m.start() == cap.start(1):
                continue
            label = "표" if _kind(m.group(1)) == "tbl" else "그림"
            refs.append({"line": no, "ref": f"{label} {m.group(2)}", "start": m.start(), "end": m.end(), "text": m.group()})
    return refs


def detect_captions(lines: dict[int, str]) -> list[dict[str, Any]]:
    caps = []
    for no, text in sorted(lines.items()):
        m = CAPTION.match(text[:MAX_LINE_CHARS])
        if m:
            caps.append({"line": no, "kind": _kind(m.group(1)), "number": m.group(2)})
    return caps


def _line_map(args: dict[str, Any]) -> dict[int, str]:
    if "lines" in args:
        lines = args["lines"]
        if type(lines) is not list or len(lines) > MAX_LINES or not all(type(x) is str for x in lines):
            raise ValueError("invalid_lines")
        return {i: x for i, x in enumerate(lines, start=1)}
    raw = args.get("line_map")
    if type(raw) is not dict or len(raw) > MAX_LINES:
        raise ValueError("invalid_lines")
    out = {}
    for k, v in raw.items():
        if type(v) is not str or not re.fullmatch(r"\d{1,6}", str(k)):
            raise ValueError("invalid_lines")
        out[int(k)] = v
    return out


def _keys(values: Any, field: str) -> list[str]:
    if values is None:
        return []
    if type(values) is not list or len(values) > 20:
        raise ValueError(f"invalid_{field}")
    keys = []
    for v in values:
        if type(v) is not str:
            raise ValueError(f"invalid_{field}")
        key = v if v in KEYS else _LABEL_TO_KEY.get(v.strip())
        if key is None:
            raise ValueError(f"unknown_section_{field}")
        keys.append(key)
    return list(dict.fromkeys(keys))


def _order_violations(first: dict[str, int], order: list[str]) -> list[str]:
    """정해진 순서에 있는 절들의 첫 등장 줄로 최장 증가 부분열을 구하고, 거기서 빠진 절을 순서 위반으로 본다."""
    present = [k for k in order if k in first]
    seq = [first[k] for k in present]
    n = len(seq)
    best = [1] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if seq[j] <= seq[i] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    keep = set()
    i = max(range(n), key=lambda x: best[x]) if n else -1
    while i >= 0:
        keep.add(i)
        i = prev[i]
    return [present[i] for i in range(n) if i not in keep]


def run(args: dict[str, Any]) -> dict[str, Any]:
    if type(args) is not dict:
        return {"verdict": "unchecked", "reason": "invalid_args"}
    try:
        lines = _line_map(args)
        required = _keys(args.get("required_sections"), "required_sections")
        order = _keys(args.get("order"), "order") or [k for k in KEYS if k in required] or list(KEYS)
        checks = args.get("checks") or ["sections", "order", "references", "numbering"]
        if type(checks) is not list or not set(checks) <= {"sections", "order", "references", "numbering"}:
            raise ValueError("invalid_checks")
        refs_arg = args.get("references")
        if refs_arg is not None and (type(refs_arg) is not list or len(refs_arg) > 200):
            raise ValueError("invalid_references")
    except ValueError as exc:
        return {"verdict": "unchecked", "reason": str(exc)}
    nx = importlib.import_module("networkx")  # 없으면 ImportError → tool_unavailable
    heads = detect_headings(lines)
    if not heads:
        return {"verdict": "unchecked", "reason": "no_headings", "engine": "networkx"}
    heading_lines = {h["line"] for h in heads}
    if refs_arg is None:
        refs = detect_references(lines, heading_lines)
    else:
        refs = []
        for r in refs_arg:
            if type(r) is not dict or type(r.get("line")) is not int or type(r.get("ref")) is not str:
                return {"verdict": "unchecked", "reason": "invalid_references"}
            refs.append({"line": r["line"], "ref": r["ref"].strip()[:32]})

    g = nx.DiGraph()
    g.add_node("doc", kind="doc", defined=True)
    duplicates: list[str] = []
    missing_parent: list[str] = []
    owner: list[tuple[int, str]] = []  # (제목 줄, 노드) — 참조 줄이 속한 절을 찾는다
    for h in heads:
        node = f"sec:{h['number']}" if h["number"] else f"sec@{h['line']}"
        if node in g and g.nodes[node].get("defined"):
            duplicates.append(h["number"])
            node = f"{node}@{h['line']}"
        parent = "doc"
        if h["number"] and "." in h["number"]:
            parent = "sec:" + h["number"].rsplit(".", 1)[0]
            if parent not in g or not g.nodes[parent].get("defined"):
                missing_parent.append(h["number"])
                parent = "doc"
        g.add_node(node, kind="section", defined=True, line=h["line"], title=h["title"], number=h["number"])
        g.add_edge(parent, node, kind="contains")
        owner.append((h["line"], node))
    for cap in detect_captions(lines):
        node = f"{cap['kind']}:{cap['number']}"
        if node in g and g.nodes[node].get("defined"):
            duplicates.append(("표 " if cap["kind"] == "tbl" else "그림 ") + cap["number"])
            continue
        g.add_node(node, kind=cap["kind"], defined=True, line=cap["line"])
        g.add_edge("doc", node, kind="contains")
    broken: list[dict[str, Any]] = []
    unresolvable = 0
    has_numbered = any(h["number"] for h in heads)
    for r in refs:
        m = REF_ARG.match(r["ref"].replace("Table", "표").replace("Figure", "그림"))
        if not m:
            unresolvable += 1
            continue
        target = f"sec:{m.group(1)}" if m.group(1) else f"{_kind(m.group(2))}:{m.group(3)}"
        if target.startswith("sec:") and not has_numbered:
            unresolvable += 1  # 번호 없는 제목만 있으면 §N을 풀 수 없다(누락으로 단정하지 않는다)
            continue
        src = "doc"
        for line, node in owner:
            if line <= r["line"]:
                src = node
        if target not in g:
            g.add_node(target, kind=target.split(":")[0], defined=False)
        g.add_edge(src, target, kind="refers", line=r["line"])
        if not g.nodes[target].get("defined"):
            broken.append({"line": r["line"], "ref": r["ref"]})

    gaps: list[str] = []
    for node in list(g.nodes):
        prefix = (g.nodes[node].get("number") + ".") if g.nodes[node].get("number") else ""
        kids = [g.nodes[c].get("number") for c in g.successors(node)
                if g.edges[node, c].get("kind") == "contains" and g.nodes[c].get("number")]
        kids = [n[len(prefix):] for n in kids if n.startswith(prefix) and "." not in n[len(prefix):]]
        last = sorted({int(n) for n in kids})
        if last:
            gaps.extend(f"{prefix}{i}" for i in range(1, last[-1]) if i not in last)
    first: dict[str, int] = {}
    for h in heads:
        for k in h["canonical"]:
            first.setdefault(k, h["line"])
    missing = [k for k in required if k not in first]
    violations = _order_violations(first, order)
    unreferenced = sorted(n for n, d in g.nodes(data=True) if d.get("kind") in ("tbl", "fig") and d.get("defined")
                          and not any(g.edges[p, n].get("kind") == "refers" for p in g.predecessors(n)))

    problems = []
    if "sections" in checks and missing:
        problems.append("missing_sections")
    if "order" in checks and violations:
        problems.append("order_violation")
    if "references" in checks and broken:
        problems.append("broken_references")
    if "numbering" in checks and (duplicates or gaps or missing_parent):
        problems.append("numbering")
    out: dict[str, Any] = {
        "sections": [{k: h[k] for k in ("line", "title", "number", "canonical")} for h in heads[:MAX_REPORT]],
        "found": {k: first[k] for k in KEYS if k in first},
        "missing": missing if "sections" in checks else [],
        "missing_labels": [LABELS[k] for k in missing] if "sections" in checks else [],
        "order_ok": not violations, "order_violations": violations if "order" in checks else [],
        "references": len(refs), "broken_references": broken[:MAX_REPORT] if "references" in checks else [],
        "unresolvable_references": unresolvable,
        "duplicate_numbers": duplicates[:MAX_REPORT], "numbering_gaps": gaps[:MAX_REPORT],
        "missing_parent_sections": missing_parent[:MAX_REPORT], "unreferenced": unreferenced[:MAX_REPORT],
        "graph": {"nodes": g.number_of_nodes(), "edges": g.number_of_edges()},
        "checks": checks, "engine": "networkx", "verdict": "fail" if problems else "pass",
    }
    if problems:
        out["reason"] = ",".join(problems)
    elif "references" in checks and set(checks) == {"references"} and not refs:
        out.update(verdict="unchecked", reason="no_references")
    return out


ARGS_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {"type": "array", "maxItems": MAX_LINES, "items": {"type": "string"}},
        "line_map": {"type": "object", "maxProperties": MAX_LINES},
        "required_sections": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
        "order": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
        "references": {"type": "array", "maxItems": 200, "items": {"type": "object"}},
        "checks": {"type": "array", "items": {"enum": ["sections", "order", "references", "numbering"]}},
    },
    "additionalProperties": False,
}
