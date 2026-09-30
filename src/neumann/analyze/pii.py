"""개인정보 마스킹 강화판 (E3-L1c).

`models.redact_pii`(이메일·ORCID)에 전화번호와 주민등록번호 형태를 더한다.

설계 (06_교훈_함정 ID-90·91: "알려진 표기 형식 열거"는 점검마다 새로 뚫렸다)
- **숫자열 기반 탐지:** 먼저 숫자 덩어리(run)를 찾고, 1~3글자 구분자(공백·하이픈류·점·괄호·가운뎃점)로
  이어진 덩어리들을 사슬로 묶는다. 사슬의 숫자 개수·첫 숫자·묶음 모양으로 전화번호인지 판단한다.
  구분자 조합을 열거하지 않으므로 `010 - 1234 - 5678`, `010.1234.5678`, `(02) 123-4567` 같은 변형이 한 규칙으로 잡힌다.
- **유니코드 숫자 매핑:** 전각(０-９)·아랍-인도(٠-٩) 등 10진 숫자를 ASCII로 1:1 바꾼 사본에서 탐지한다.
  글자 수가 그대로라 사본의 오프셋이 원문 오프셋과 같다.
- **경계 가드:** 앞뒤가 영문자·숫자·밑줄이면 버린다(`R2.3`, `v1.0`, `ex_0123…`). 한글 조사(`…5678로`)는 허용한다.
  천 단위 쉼표·소수점 가운데서 자르지 않는다. URL·DOI·arXiv 구간 안은 전화번호·주민번호로 보지 않는다.
- 오탐 방지: 점(.) 구분자는 모든 구분자가 점 하나이고 묶음이 3개 이상일 때만 인정한다(`0.95`, `0.12 0.34` 보존).
  `15xx-xxxx` 대표번호와 7~8자리 번호는 "전화·연락처·Tel" 같은 단서가 앞에 있을 때만 가린다(`1600-1700` 연도 범위 보존).

마스킹은 길이를 바꾸므로 Excerpt·PlanDocument를 만들기 **전에** 한다(models 모듈 설명과 같은 순서).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from neumann.models import EMAIL_RE, ORCID_RE, PlanDocument, normalize_text

TAGS: dict[str, str] = {"email": "[EMAIL]", "orcid": "[ORCID]", "rrn": "[RRN]", "phone": "[PHONE]"}
# 겹치면 앞쪽이 이긴다(ORCID 16자리가 전화번호로 먼저 잡히지 않게).
_PRIORITY: dict[str, int] = {"email": 0, "orcid": 1, "rrn": 2, "phone": 3}

_HYPHENS = "-‐‑‒–—―−﹘﹣－"
_DOTS = ".．"
_PARENS_OPEN = "(（"
_PARENS_CLOSE = ")）"
_MIDDOTS = "·・‧"
_PLUS = "+＋"
_LINE_BREAKS = "\n\r\v\f\x1c\x1d\x1e\x85  "
MAX_GAP = 3  # 숫자 덩어리 사이 구분자 최대 글자 수

_DIGIT_RUN = re.compile(r"[0-9]+")
_CUE_RE = re.compile(
    r"(?i)(?:\b(?:tel|phone|mobile|cell|fax|call|contact)\b|전화|연락|휴대|핸드폰|팩스|문의|☎|☏|✆|\U0001f4de)"
)
_PROTECTED_RES = (
    re.compile(r"(?i)\bhttps?://\S+|\bwww\.\S+"),
    re.compile(r"(?i)\b10\.[0-9]{4,9}/\S+"),  # DOI
    re.compile(r"(?i)\barxiv:\s*\S+"),
)
_RRN_HYPHENS = re.escape(_HYPHENS)
_RRN_RE = re.compile(
    r"(?<![0-9A-Za-z_])([0-9]{2})([0-9]{2})([0-9]{2})[ \t]?[" + _RRN_HYPHENS + r"]?[ \t]?"
    r"([1-8])([0-9]{6}|[*＊xX●○#]{6})(?![0-9A-Za-z_])"
)


@dataclass(frozen=True)
class PiiSpan:
    """원문 오프셋 구간. kind는 email·orcid·rrn·phone."""

    kind: str
    start: int
    end: int


# ── 보조 ──────────────────────────────────────────────────────────────────


def ascii_digits(text: str) -> str:
    """유니코드 10진 숫자(Nd)를 ASCII 숫자로 1:1 치환한다. 길이와 오프셋이 그대로다."""
    if text.isascii():
        return text
    out: list[str] = []
    for ch in text:
        if ch.isdecimal() and not ("0" <= ch <= "9"):
            out.append(str(unicodedata.decimal(ch)))
        else:
            out.append(ch)
    return "".join(out)


def _is_sep(ch: str) -> bool:
    if ch in _HYPHENS or ch in _DOTS or ch in _PARENS_OPEN or ch in _PARENS_CLOSE or ch in _MIDDOTS:
        return True
    return ch.isspace() and ch not in _LINE_BREAKS


def _is_word(ch: str) -> bool:
    """경계 가드: 영문자·숫자·밑줄이면 단어의 일부로 본다. 한글 조사는 단어로 보지 않는다."""
    return ch.isdecimal() or ch == "_" or (ch.isascii() and ch.isalpha())


def _has_dot(gap: str) -> bool:
    return any(c in _DOTS for c in gap)


def _looks_like_date_or_range(groups: list[str]) -> bool:
    """YYYY-MM-DD, DD.MM.YYYY, YYYY-YYYY(증가하는 연도 범위)."""
    nums = [int(g) for g in groups]
    lens = [len(g) for g in groups]
    if len(groups) == 3:
        if lens[0] == 4 and lens[1] <= 2 and lens[2] <= 2:
            y, m, d = nums
        elif lens[2] == 4 and lens[0] <= 2 and lens[1] <= 2:
            d, m, y = nums
            if m > 12:  # MM-DD-YYYY
                m, d = d, m
        else:
            return False
        return 1000 <= y <= 2199 and 1 <= m <= 12 and 1 <= d <= 31
    if len(groups) == 2 and lens == [4, 4]:
        return 1000 <= nums[0] < nums[1] <= 2199
    return False


def _has_cue(norm: str, pos: int) -> bool:
    line_start = norm.rfind("\n", 0, pos) + 1
    return bool(_CUE_RE.search(norm[max(line_start, pos - 24) : pos]))


def _phone_shape_ok(groups: list[str], gaps: list[str], *, plus: bool, cue: bool) -> bool:
    digits = "".join(groups)
    n_digits = len(digits)
    n_groups = len(groups)
    # 점 구분자: 모든 구분자가 점 하나이고 묶음이 3개 이상일 때만(소수·지표 수치 보호)
    if any(_has_dot(g) for g in gaps):
        if n_groups < 3 or not all(len(g) == 1 and g in _DOTS for g in gaps):
            return False
    if plus:  # 국제 표기 +82 …, E.164 최대 15자리
        return 8 <= n_digits <= 15
    if digits.startswith("00"):  # 국제 전화 접두 00(1) …
        return n_groups >= 2 and 10 <= n_digits <= 17
    if digits.startswith("0"):  # 국내: 02-123-4567, 010-1234-5678, 0505-123-4567, 01012345678
        if not 9 <= n_digits <= 11:
            return False
        lens = [len(g) for g in groups]
        if n_groups == 1:
            return True
        if n_groups == 2:
            return lens[0] >= 2 and lens[1] >= 4
        if n_groups == 3:
            return 2 <= lens[0] <= 4 and 3 <= lens[1] <= 4 and lens[2] == 4
        return False
    if groups[0] == "82" and n_groups >= 3 and 11 <= n_digits <= 12:  # + 없이 쓴 국가번호
        return True
    if not cue:
        return False
    # 단서(전화·Tel …)가 있을 때만: 대표번호 15xx/16xx/18xx-xxxx, 7~15자리 번호
    if n_groups == 2 and [len(g) for g in groups] == [4, 4] and digits[:2] in {"15", "16", "18"}:
        return True
    if _looks_like_date_or_range(groups):
        return False
    return 7 <= n_digits <= 15 and (n_groups >= 2 or n_digits >= 9)


def _chains(norm: str) -> list[list[tuple[int, int]]]:
    runs = [(m.start(), m.end()) for m in _DIGIT_RUN.finditer(norm)]
    chains: list[list[tuple[int, int]]] = []
    for run in runs:
        if chains:
            prev = chains[-1][-1]
            gap = norm[prev[1] : run[0]]
            if 1 <= len(gap) <= MAX_GAP and all(_is_sep(c) for c in gap):
                chains[-1].append(run)
                continue
        chains.append([run])
    return chains


def _phone_span(norm: str, chain: list[tuple[int, int]], i: int, j: int) -> PiiSpan | None:
    start, end = chain[i][0], chain[j][1]
    gaps = [norm[chain[k][1] : chain[k + 1][0]] for k in range(i, j)]
    # 소수점 한가운데서 자르지 않는다
    if i > 0 and _has_dot(norm[chain[i - 1][1] : start]):
        return None
    if j < len(chain) - 1 and _has_dot(norm[end : chain[j + 1][0]]):
        return None
    k = start
    plus = k > 0 and norm[k - 1] in _PLUS
    if plus:
        k -= 1
    if k > 0 and norm[k - 1] in _PARENS_OPEN and gaps and any(c in _PARENS_CLOSE for c in gaps[0]):
        k -= 1  # "(02) 123-4567"의 여는 괄호까지 가린다
    # 경계 가드: 앞뒤가 영문자·숫자·밑줄이면 버린다. 천 단위 쉼표·소수점 뒤/앞도 버린다
    if k > 0:
        before = norm[k - 1]
        if _is_word(before):
            return None
        if before in ",." + _DOTS and k > 1 and norm[k - 2].isdecimal():
            return None
    if end < len(norm):
        after = norm[end]
        if _is_word(after):
            return None
        if after in ",." + _DOTS and end + 1 < len(norm) and norm[end + 1].isdecimal():
            return None
    groups = [norm[a:b] for a, b in chain[i : j + 1]]
    if not _phone_shape_ok(groups, gaps, plus=plus, cue=_has_cue(norm, k)):
        return None
    return PiiSpan("phone", k, end)


def _protected(norm: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for rx in _PROTECTED_RES for m in rx.finditer(norm)]


def _inside(span: PiiSpan, zones: list[tuple[int, int]]) -> bool:
    return any(span.start < b and a < span.end for a, b in zones)


# ── 공개 함수 ─────────────────────────────────────────────────────────────


def find_phones(text: str) -> list[PiiSpan]:
    norm = ascii_digits(text)
    zones = _protected(norm)
    found: list[PiiSpan] = []
    for chain in _chains(norm):
        i = 0
        while i < len(chain):
            hit = None
            for j in range(len(chain) - 1, i - 1, -1):  # 가장 긴 사슬부터
                hit = _phone_span(norm, chain, i, j)
                if hit is not None:
                    break
            if hit is not None and not _inside(hit, zones):
                found.append(hit)
                i = j + 1
            else:
                i += 1
    return found


def find_rrns(text: str) -> list[PiiSpan]:
    """주민등록번호(외국인등록번호) 형태: YYMMDD-[1-8]NNNNNN, 뒷자리가 *로 가려진 형태 포함. 월·일이 유효해야 한다."""
    norm = ascii_digits(text)
    zones = _protected(norm)
    out: list[PiiSpan] = []
    for m in _RRN_RE.finditer(norm):
        month, day = int(m.group(2)), int(m.group(3))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        span = PiiSpan("rrn", m.start(), m.end())
        if not _inside(span, zones):
            out.append(span)
    return out


def find_pii(text: str) -> list[PiiSpan]:
    """이메일·ORCID(models 정규식 재사용)·주민번호·전화번호 구간. 겹치면 우선순위가 높은 쪽만 남긴다."""
    norm = ascii_digits(text)
    cands = [PiiSpan("email", m.start(), m.end()) for m in EMAIL_RE.finditer(norm)]
    cands += [PiiSpan("orcid", m.start(), m.end()) for m in ORCID_RE.finditer(norm)]
    cands += find_rrns(text)
    cands += find_phones(text)
    chosen: list[PiiSpan] = []
    for span in sorted(cands, key=lambda s: (_PRIORITY[s.kind], s.start)):
        if not any(span.start < c.end and c.start < span.end for c in chosen):
            chosen.append(span)
    return sorted(chosen, key=lambda s: s.start)


def mask_pii_counts(text: str) -> tuple[str, dict[str, int]]:
    """개인정보를 태그로 바꾼 문자열과 종류별 건수."""
    spans = find_pii(text)
    if not spans:
        return text, {}
    parts: list[str] = []
    pos = 0
    for s in spans:
        parts.append(text[pos : s.start])
        parts.append(TAGS[s.kind])
        pos = s.end
    parts.append(text[pos:])
    return "".join(parts), dict(Counter(s.kind for s in spans))


def mask_pii(text: str) -> str:
    """이메일·ORCID·주민번호·전화번호를 `[EMAIL]`·`[ORCID]`·`[RRN]`·`[PHONE]`으로 가린다. 두 번 불러도 같다."""
    return mask_pii_counts(text)[0]


def has_pii(text: str) -> bool:
    return bool(find_pii(text))


def mask_plan_text(text: str) -> tuple[str, dict[str, int]]:
    """계획서 원문 → 정규화(NFC+LF) → 마스킹. PlanDocument를 만들기 전에 부른다."""
    return mask_pii_counts(normalize_text(text))


def plan_document_from_text(text: str, session_id: str) -> tuple[PlanDocument, dict[str, int]]:
    """정규화 → 강화 마스킹 → 줄 번호. `PlanDocument.from_text` 대신 쓰면 전화번호·주민번호도 가려진다."""
    body, counts = mask_plan_text(text)
    return PlanDocument.from_text(body, session_id, redact=True), counts


__all__ = [
    "TAGS",
    "PiiSpan",
    "ascii_digits",
    "find_phones",
    "find_pii",
    "find_rrns",
    "has_pii",
    "mask_pii",
    "mask_pii_counts",
    "mask_plan_text",
    "plan_document_from_text",
]
