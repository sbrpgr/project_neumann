"""계획서 문장 속 수치·단위 인식(FIN-TOOLS). 표준 라이브러리만 쓴다(Pint는 `dimension`에서만 늦게 불러온다).

Codex FINAL-TOOLS 규칙을 그대로 잇는다.
- 숫자 경계: `neumann.analyze.final_tools._NUMBER`와 같은 규칙(영문 식별자·지수 조각·부호/소수점 조각은 숫자가 아니다,
  한글 조사는 숫자에 바로 붙을 수 있다: ``3이다``). 여기에 천 단위 쉼표(``12,000``)와 과학 표기(``1e8``)를 더했다.
- 한정·부정 줄: `neumann.analyze.final_tools._QUALIFIED_NUMERIC`(아님·않·약 N·가정·추정·if·not …)에 걸리는 줄의 수치는
  검사 대상에서 뺀다(원문이 확정한 수치만 검사한다).

단위는 짧은 표(한국어·SI·과학 ML 단위)로만 알아본다. 표에 없는 영문 낱말은 단위로 보지 않는다(``5 in accuracy``의 in 같은 오인 방지).
돌려주는 인용(`text`)은 언제나 원문 줄을 코드가 잘라 붙인 것이다(start·end 오프셋 포함).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from neumann.analyze.final_tools import _QUALIFIED_NUMERIC as QUALIFIED_NUMERIC  # Codex 규칙 재사용

MAX_LINE_CHARS = 2000
MAX_ABS = Fraction(10) ** 30

# Codex `_NUMBER`의 경계 규칙 + 천 단위 쉼표 + 과학 표기. 뒤 경계는 스캐너가 따로 본다(붙은 단위 허용).
NUMERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_.,+\-])[-+]?(?:\d+(?:\.\d+)?[eE][+-]?\d{1,3}|(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
)
_KO_SMALL = {"천": 1000, "백": 100, "십": 10}
_KO_BIG = {"만": 10**4, "억": 10**8, "조": 10**12}
_SUFFIX_MULT = {"K": 10**3, "k": 10**3, "M": 10**6, "B": 10**9, "G": 10**9, "T": 10**12}

# 단위 표면형 → (Pint 식, 분류). 분류는 추출기가 "같은 종류"를 가를 때 쓴다(time·currency·percent·count·…).
# 정보량은 Pint 기본 정의(bit·byte 무차원, Gb=gilbert)를 쓰지 않고 [information] 차원의 infobit·infobyte로 둔다.
_KO_UNITS: dict[str, tuple[str, str]] = {
    "개월": ("month", "time"), "달": ("month", "time"), "분기": ("quarter_year", "time"), "개년": ("year", "time"),
    "년": ("year", "time"), "주": ("week", "time"), "일": ("day", "time"), "시간": ("hour", "time"),
    "분": ("minute", "time"), "초": ("second", "time"),
    "억원": ("100000000 * KRW", "currency"), "만원": ("10000 * KRW", "currency"), "천원": ("1000 * KRW", "currency"),
    "원": ("KRW", "currency"), "달러": ("USD", "currency"),
    "퍼센트": ("percent", "percent"), "%": ("percent", "percent"),
    "샘플": ("sample", "sample"), "토큰": ("token", "token"), "에폭": ("epoch", "epoch"), "에포크": ("epoch", "epoch"),
    "스텝": ("step", "step"), "파라미터": ("parameter", "parameter"), "매개변수": ("parameter", "parameter"),
    "GPU시간": ("gpu * hour", "gpu_time"), "명": ("person", "person"), "건": ("record", "record"),
    "개": ("count", "count"), "장": ("count", "count"), "대": ("count", "count"),
}
# 한글 단위 뒤에 오면 단위가 아닌 낱말(``3분기``는 분기로 먼저 잡히므로 여기엔 없다)
_KO_BLOCK_AFTER = {
    "일": "부정반치단환괄련", "주": "요제체장", "장": "비점기애", "대": "학상비회규표안응", "초": "과기반",
    "분": "석야량포류", "년": "도대", "명": "확시칭", "개": "선발념요인별최", "건": "강설축",
}
_ASCII_UNITS: dict[str, tuple[str, str]] = {
    # 시간
    "s": ("second", "time"), "sec": ("second", "time"), "secs": ("second", "time"), "ms": ("millisecond", "time"),
    "us": ("microsecond", "time"), "µs": ("microsecond", "time"), "ns": ("nanosecond", "time"),
    "min": ("minute", "time"), "mins": ("minute", "time"), "h": ("hour", "time"), "hr": ("hour", "time"),
    "hrs": ("hour", "time"),
    # 길이·질량·온도·전기·화학(자주 쓰는 것만)
    "m": ("meter", "length"), "km": ("kilometer", "length"), "cm": ("centimeter", "length"),
    "mm": ("millimeter", "length"), "um": ("micrometer", "length"), "µm": ("micrometer", "length"),
    "nm": ("nanometer", "length"), "Å": ("angstrom", "length"),
    "g": ("gram", "mass"), "kg": ("kilogram", "mass"), "mg": ("milligram", "mass"), "µg": ("microgram", "mass"),
    "K": ("kelvin", "temperature"), "°C": ("degC", "temperature"), "℃": ("degC", "temperature"),
    "V": ("volt", "voltage"), "mV": ("millivolt", "voltage"), "mA": ("milliampere", "current"),
    "W": ("watt", "power"), "kW": ("kilowatt", "power"), "MW": ("megawatt", "power"),
    "J": ("joule", "energy"), "kJ": ("kilojoule", "energy"), "eV": ("electron_volt", "energy"),
    "keV": ("kiloelectron_volt", "energy"), "MeV": ("megaelectron_volt", "energy"), "kWh": ("kilowatt_hour", "energy"),
    "Hz": ("hertz", "frequency"), "kHz": ("kilohertz", "frequency"), "MHz": ("megahertz", "frequency"),
    "GHz": ("gigahertz", "frequency"), "Pa": ("pascal", "pressure"), "kPa": ("kilopascal", "pressure"),
    "MPa": ("megapascal", "pressure"), "bar": ("bar", "pressure"), "atm": ("atmosphere", "pressure"),
    "mol": ("mole", "amount"), "mmol": ("millimole", "amount"), "mM": ("millimolar", "concentration"),
    "L": ("liter", "volume"), "mL": ("milliliter", "volume"), "µL": ("microliter", "volume"),
    "S": ("siemens", "conductance"), "mS": ("millisiemens", "conductance"),
    "S/cm": ("siemens / centimeter", "conductivity"), "mS/cm": ("millisiemens / centimeter", "conductivity"),
    # 정보량
    "KB": ("kiloinfobyte", "information"), "kB": ("kiloinfobyte", "information"), "MB": ("megainfobyte", "information"),
    "GB": ("gigainfobyte", "information"), "TB": ("terainfobyte", "information"), "PB": ("petainfobyte", "information"),
    "KiB": ("kibiinfobyte", "information"), "MiB": ("mebiinfobyte", "information"),
    "GiB": ("gibiinfobyte", "information"), "TiB": ("tebiinfobyte", "information"),
    "Gb": ("gigainfobit", "information"), "Mb": ("megainfobit", "information"), "Tb": ("terainfobit", "information"),
    "Gbps": ("gigainfobit / second", "bandwidth"), "Mbps": ("megainfobit / second", "bandwidth"),
    # 연산량
    "FLOP": ("FLOP", "compute"), "FLOPs": ("FLOP", "compute"), "GFLOP": ("gigaFLOP", "compute"),
    "GFLOPs": ("gigaFLOP", "compute"), "TFLOP": ("teraFLOP", "compute"), "TFLOPs": ("teraFLOP", "compute"),
    "PFLOP": ("petaFLOP", "compute"), "PFLOPs": ("petaFLOP", "compute"), "EFLOP": ("exaFLOP", "compute"),
    "EFLOPs": ("exaFLOP", "compute"),
    "FLOPS": ("FLOPS", "compute_rate"), "GFLOPS": ("gigaFLOPS", "compute_rate"), "TFLOPS": ("teraFLOPS", "compute_rate"),
    "PFLOPS": ("petaFLOPS", "compute_rate"), "EFLOPS": ("exaFLOPS", "compute_rate"),
    "PF-day": ("petaflop_day", "compute"), "PF-days": ("petaflop_day", "compute"),
    "KRW": ("KRW", "currency"), "USD": ("USD", "currency"),
}
# 대소문자 무관 낱말 단위(영문)
_WORD_UNITS: dict[str, tuple[str, str]] = {
    "second": ("second", "time"), "seconds": ("second", "time"), "minute": ("minute", "time"),
    "minutes": ("minute", "time"), "hour": ("hour", "time"), "hours": ("hour", "time"), "day": ("day", "time"),
    "days": ("day", "time"), "week": ("week", "time"), "weeks": ("week", "time"), "month": ("month", "time"),
    "months": ("month", "time"), "year": ("year", "time"), "years": ("year", "time"),
    "sample": ("sample", "sample"), "samples": ("sample", "sample"), "example": ("sample", "sample"),
    "examples": ("sample", "sample"), "image": ("sample", "sample"), "images": ("sample", "sample"),
    "token": ("token", "token"), "tokens": ("token", "token"), "epoch": ("epoch", "epoch"), "epochs": ("epoch", "epoch"),
    "step": ("step", "step"), "steps": ("step", "step"), "iteration": ("step", "step"), "iterations": ("step", "step"),
    "param": ("parameter", "parameter"), "params": ("parameter", "parameter"), "parameter": ("parameter", "parameter"),
    "parameters": ("parameter", "parameter"), "gpu": ("gpu", "gpu"), "gpus": ("gpu", "gpu"),
    "gpu-hour": ("gpu * hour", "gpu_time"), "gpu-hours": ("gpu * hour", "gpu_time"), "gpu-h": ("gpu * hour", "gpu_time"),
    "percent": ("percent", "percent"),
}
# 수 바로 뒤에 붙는 배수 접미(K·M·B·T)는 뒤에 셀 수 있는 낱말이 올 때만 배수로 본다(7B parameters, 1M samples).
_COUNT_FAMILIES = {"sample", "token", "parameter", "step", "record", "person", "count", "epoch"}
_TIME_WORDS = {
    "초": "second", "s": "second", "sec": "second", "second": "second", "분": "minute", "min": "minute",
    "minute": "minute", "시간": "hour", "h": "hour", "hr": "hour", "hour": "hour", "일": "day", "day": "day",
}
_RATE_PREFIX = re.compile(r"(초|분|시간|일)당\s*$")
_GPU_BEFORE = re.compile(r"(?:GPU|TPU|[AHV]100|H200|B200)\s*(?:카드\s*)?$", re.I)
_ASCII_LETTER = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class Quantity:
    """원문 한 줄의 수치 1개. ``text``는 원문 ``line[start:end]`` 그대로다."""

    line: int  # 1부터
    start: int
    end: int
    text: str
    value: Fraction
    unit: str | None  # Pint 식(없으면 무단위 수)
    family: str | None  # time · currency · percent · sample · … (추출기의 같은 종류 판단용)
    rate_of: str | None = None  # "초당 1,000개"처럼 시간당 비율이면 분모 시간 단위(Pint 이름)
    number_text: str = ""

    @property
    def pint_unit(self) -> str | None:
        if self.unit is None and self.rate_of is None:
            return None
        base = self.unit or "count"
        return f"({base}) / {self.rate_of}" if self.rate_of else base

    def anchor(self) -> dict:
        return {"line": self.line, "start": self.start, "end": self.end, "text": self.text}


def parse_decimal(text: str) -> Fraction | None:
    """``12,000``·``3.5``·``1e8`` → 정확한 유리수. 형식이 아니거나 너무 크면 None."""
    s = text.replace(",", "").strip()
    if not s or len(s) > 40:
        return None
    try:
        value = Fraction(s)
    except (ValueError, ZeroDivisionError):
        return None
    return value if abs(value) <= MAX_ABS else None


def qualified(line: str) -> bool:
    """Codex 규칙: 부정·가정·근사·조건 표현이 있는 줄의 수치는 확정 주장이 아니다."""
    return bool(QUALIFIED_NUMERIC.search(line))


def _match_unit(line: str, pos: int) -> tuple[int, str, str, str] | None:
    """pos(수 바로 뒤, 공백 0~1칸 허용)에서 단위 표면형을 가장 길게 찾는다 → (끝, 표면형, Pint 식, 분류)."""
    rest = line[pos:pos + 40]
    skip = 1 if rest.startswith(" ") else 0
    body = rest[skip:]
    best = None
    for table in (_KO_UNITS, _ASCII_UNITS):
        for surface, (unit, family) in table.items():
            if body.startswith(surface) and (best is None or len(surface) > len(best[1])):
                best = (pos + skip + len(surface), surface, unit, family)
    m = re.match(r"[A-Za-z][A-Za-z\-]*", body)
    if m:
        word = m.group().lower()
        while word and word not in _WORD_UNITS and "-" in word:
            word = word.rsplit("-", 1)[0]
        if word in _WORD_UNITS and (best is None or len(word) > len(best[1])):
            unit, family = _WORD_UNITS[word]
            best = (pos + skip + len(word), body[: len(word)], unit, family)
    if best is None:
        return None
    end, surface, unit, family = best
    nxt = line[end:end + 1]
    if surface in _ASCII_UNITS or surface.lower() in _WORD_UNITS:
        if nxt and (nxt.isascii() and (nxt.isalnum() or nxt == "_")):
            return None
    elif nxt and nxt in _KO_BLOCK_AFTER.get(surface, ""):
        return None
    return best


def _korean_multiplier(line: str, pos: int) -> tuple[int, int] | None:
    """수 뒤의 천·백·십 / 만·억·조 배수(공백 0~1칸). → (끝 위치, 배수). 조는 통화 앞에서만 배수다(3조 = 세 모둠)."""
    j = pos + 1 if line[pos:pos + 1] == " " and line[pos + 1:pos + 2] in _KO_SMALL.keys() | _KO_BIG.keys() else pos
    mult, seen = 1, False
    if line[j:j + 1] and line[j] in _KO_SMALL:
        mult *= _KO_SMALL[line[j]]
        j += 1
        seen = True
    if line[j:j + 1] and line[j] in _KO_BIG:
        if line[j] == "조" and not re.match(r"\s?(?:원|달러|KRW|USD)", line[j + 1:j + 6]):
            return (j, mult) if seen else None
        mult *= _KO_BIG[line[j]]
        j += 1
        seen = True
    return (j, mult) if seen else None


def scan_line(line: str, line_no: int) -> list[Quantity]:
    """한 줄의 수치·단위를 왼쪽부터 찾는다. 한정·부정 여부는 부르는 쪽이 `qualified`로 본다."""
    if len(line) > MAX_LINE_CHARS:
        line = line[:MAX_LINE_CHARS]
    out: list[Quantity] = []
    pos = 0
    while True:
        m = NUMERAL_RE.search(line, pos)
        if not m:
            break
        start, end = m.start(), m.end()
        pos = end
        value = parse_decimal(m.group())
        if value is None:
            continue
        number_text = m.group()
        nxt = line[end:end + 1]
        # 뒤에 소수점·밑줄이 오면 조각이다(Codex 경계). 붙은 영문자는 단위표에 있을 때만 허용한다.
        if nxt in (".", "_") and not (nxt == "." and not line[end + 1:end + 2].isdigit()):
            continue
        # 한국어 복합 수(1억 5천만) — 큰 배수로 끝난 뒤 공백 하나 + 수가 오면 이어 붙인다
        k = _korean_multiplier(line, end)
        if k:
            end, group = k
            value *= group
            while True:  # 복합 수: 1억 5천만 · 1만 5천(뒤 묶음의 배수가 더 작아야 한다)
                j = end + 1 if line[end:end + 1] == " " else end
                m2 = NUMERAL_RE.match(line, j)
                k2 = _korean_multiplier(line, m2.end()) if m2 else None
                v2 = parse_decimal(m2.group()) if m2 else None
                if not m2 or not k2 or v2 is None or k2[1] >= group:
                    break
                value += v2 * k2[1]
                end, group = k2
            if abs(value) > MAX_ABS:
                continue
        suffix_mult = None
        if nxt in _SUFFIX_MULT and not k:
            after = line[end + 1:end + 2]
            if after == " " or after == "":
                unit_try = _match_unit(line, end + 1)
                if unit_try and unit_try[3] in _COUNT_FAMILIES:
                    suffix_mult = _SUFFIX_MULT[nxt]
        unit = family = None
        if suffix_mult:
            value *= suffix_mult
            end += 1
        u = _match_unit(line, end)
        if u:
            if u[2] == "year" and value >= 1900 and value.denominator == 1 and "," not in number_text:
                continue  # 2026년은 기간이 아니라 날짜다
            end, _surface, unit, family = u
        elif _ASCII_LETTER.match(line[end:end + 1] or " "):
            continue  # 3D·v2·5x 같은 식별자 조각(Codex 경계)
        rate_of = None
        tail = re.match(r"\s?/\s?(초|분|시간|일|sec|s|min|h|hr|hour|second|day)(?![A-Za-z가-힣])", line[end:end + 12])
        if tail and unit is not None:
            rate_of = _TIME_WORDS[tail.group(1)]
            end += tail.end()
        before = line[max(0, start - 12):start]
        rp = _RATE_PREFIX.search(before)
        if rp and rate_of is None:
            rate_of = _TIME_WORDS[rp.group(1)]
        if _GPU_BEFORE.search(before) and family in (None, "count"):
            unit, family = "gpu", "gpu"
        if rate_of is not None:
            family = f"{family or 'count'}_rate"
        out.append(Quantity(line_no, start, end, line[start:end], value, unit, family, rate_of, number_text))
        pos = max(pos, end)
    return out


def scan_text(text: str) -> tuple[list[str], list[Quantity]]:
    lines = text.splitlines()
    found: list[Quantity] = []
    for i, line in enumerate(lines, start=1):
        found.extend(scan_line(line, i))
    return lines, found


__all__ = ["NUMERAL_RE", "QUALIFIED_NUMERIC", "Quantity", "parse_decimal", "qualified", "scan_line", "scan_text"]
