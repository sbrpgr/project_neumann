"""변이 검사(표준 라이브러리만): 도구 소스의 한 곳을 바꾼 변이 모듈을 새로 실행해, 각 도구의 사례 표가 그 변이를 잡는지 본다.

변이가 살아남으면(사례 표가 전부 통과하면) 그 테스트는 기능을 실제로 검사하지 않는 것이다. 원본은 모든 사례 표를 통과해야 한다.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path
from typing import Any, Callable

import pytest

from neumann.finalize.tools import ToolRegistry
from neumann.finalize.tools import citation as real_citation
from neumann.finalize.tools import dimension as real_dimension
from tests.finalize import test_fin_tools_citation as tc
from tests.finalize import test_fin_tools_dimension as td
from tests.finalize import test_fin_tools_structure as ts
from tests.finalize import test_fin_tools_sums as tsum
from tests.finalize.fin_tools_backend import build_backend
from tests.finalize.fin_tools_plans import CLEAN, SEEDED


def load_mutant(modname: str, old: str, new: str) -> types.ModuleType:
    spec = importlib.util.find_spec(modname)
    assert spec and spec.origin
    src = Path(spec.origin).read_text(encoding="utf-8")
    assert src.count(old) == 1, f"변이 지점이 정확히 한 곳이 아니다: {modname}: {old!r}"
    mod = types.ModuleType(modname)
    mod.__file__ = spec.origin
    mod.__package__ = modname.rpartition(".")[0]
    exec(compile(src.replace(old, new), spec.origin, "exec"), mod.__dict__)  # noqa: S102 — 테스트 전용, 저장소 소스만
    return mod


def _table(run: Callable[[Any], dict], cases, bad=()) -> bool:
    """사례 표 전부 통과면 True(= 변이가 살아남음)."""
    for args, verdict, extra in cases:
        out = run(args)
        if out.get("verdict") != verdict or any(out.get(k) != v for k, v in extra.items()):
            return False
    for args in bad:
        if run(args).get("verdict") != "unchecked":
            return False
    return True


def survives(check: Callable[[types.ModuleType], bool], mod: types.ModuleType) -> bool:
    try:
        return check(mod)
    except Exception:  # noqa: BLE001 — 변이가 예외를 내면 잡힌 것이다
        return False


# ── 도구별 사례 표(각 테스트 모듈의 표를 그대로 쓴다) ─────────────────────


def sums_ok(mod):
    return _table(mod.run, tsum.CASES, tsum.BAD)


DIM_EXTRA = [
    ({"operation": "derive", "factors": [{"value": "1e8", "unit": "sample", "power": 1},
                                         {"value": 1000, "unit": "sample/s", "power": -1}],
      "expected": {"value": "28.0", "unit": "h"}}, "fail", {}),
]


def dimension_ok(mod):
    if "infobyte = 8 * infobit" in mod.DEFINITIONS:
        mod._UREG = real_dimension.registry()  # 정의가 같으면 느린 레지스트리를 다시 만들지 않는다
    return _table(mod.run, td.CASES + DIM_EXTRA)


def structure_ok(mod):
    return _table(mod.run, ts.CASES)


def extract_ok(mod):
    def labels(text):
        return {c.label: c for c in mod.extract_checks(text)}

    def verdicts(text):
        return {(r["check"]["label"], r["result"]["verdict"]) for r in mod.run_checks(mod.extract_checks(text), reg=ToolRegistry())}

    seeded = verdicts(SEEDED)
    want = {("references", "fail"), ("citation", "fail"), ("unit_add", "fail"), ("unit_derive", "fail"),
            ("split_sum", "fail"), ("schedule_sum", "fail"), ("table_sum", "fail"), ("sections", "fail")}
    if seeded != want:
        return False
    if {v for _, v in verdicts(CLEAN)} != {"pass"}:
        return False
    if "split_sum" in labels("We do not split the data 70/20/20 into train/test."):
        return False
    if "schedule_sum" in labels("## 일정\n- 1단계: 6개월(2단계와 병행)\n- 2단계: 6개월\n- 총 연구 기간: 6개월"):
        return False
    if "budget_sum" in labels("## 예산\n- 인건비 3억 원(연 1억 원)\n- 장비비 2억 원\n- 재료비 1억 원\n- 총 예산 6억 원"):
        return False
    frac = mod.run_checks([c for c in mod.extract_checks("Split 0.8/0.1/0.1 into train/validation/test.")],
                          reg=ToolRegistry())
    return [r["result"]["verdict"] for r in frac] == ["pass"]


QUANT_CASES = [("1억 5천만 원", 150_000_000, "KRW"), ("3개월간", 3, "month"), ("7B parameters", 7_000_000_000, "parameter"),
               ("256GB", 256, "gigainfobyte"), ("12,000건", 12000, "record"), ("3분기", 3, "quarter_year")]
QUANT_CASES += [("1조 원", 10**12, "KRW"), ("3조로", 3, None)]  # 조는 통화 앞에서만 배수(3조 = 세 모둠)
QUANT_EMPTY = ["2026년", "3D", "v2", "5x", "abc3"]  # 날짜·식별자 조각은 수치가 아니다(Codex 경계)


def quantities_ok(mod):
    for text, value, unit in QUANT_CASES:
        qs = mod.scan_line(text, 1)
        if len(qs) != 1 or qs[0].value != value or qs[0].unit != unit:
            return False
    for text in QUANT_EMPTY:
        if mod.scan_line(text, 1):
            return False
    rate = mod.scan_line("초당 1,000개", 1)
    return len(rate) == 1 and rate[0].rate_of == "second"


def citation_ok(mod):
    return _table(mod.run, tc.CASES)


P = "neumann.finalize.tools."
MUTANTS = [
    (P + "sums", sums_ok, "computed = sum(items, Fraction(0))", "computed = sum(items[1:], Fraction(0))"),
    (P + "sums", sums_ok, "return abs(computed - stated) <= tol", "return abs(computed - stated) < tol"),
    (P + "sums", sums_ok, "return computed <= stated + tol", "return computed < stated + tol"),
    (P + "sums", sums_ok, "value = Fraction(repr(raw))  #", "value = Fraction(raw)  #"),
    (P + "sums", sums_ok, "    if isinstance(raw, bool):\n        raise Unchecked(\"invalid_number\")",
     "    if False:\n        raise Unchecked(\"invalid_number\")"),
    (P + "sums", sums_ok, "    if abs(value) > MAX_ABS:\n        raise Unchecked(\"number_out_of_range\")",
     "    if False:\n        raise Unchecked(\"number_out_of_range\")"),
    (P + "dimension", dimension_ok, "compatible = left.dimensionality == right.dimensionality", "compatible = True"),
    (P + "dimension", dimension_ok, "close = math.isclose(a, b, rel_tol=tol, abs_tol=0.0)", "close = True"),
    (P + "dimension", dimension_ok, '"infobyte = 8 * infobit"', '"infobyte = 1 * infobit"'),
    (P + "dimension", dimension_ok, "holds = RELATIONS[relation](a, b)", "holds = not RELATIONS[relation](a, b)"),
    (P + "dimension", dimension_ok, "half = 0.5 * 10 ** (-decimals)", "half = 5 * 10 ** (-decimals)"),
    (P + "dimension", dimension_ok, "term = qty ** power", "term = qty"),
    (P + "structure", structure_ok, "missing = [k for k in required if k not in first]", "missing = []"),
    (P + "structure", structure_ok, '        if not g.nodes[target].get("defined"):\n            broken.append',
     '        if False:\n            broken.append'),
    (P + "structure", structure_ok, "if seq[j] <= seq[i] and", "if seq[j] >= seq[i] and"),
    (P + "structure", structure_ok, "for i in range(1, last[-1]) if i not in last", "for i in range(1, last[-1]) if i in last"),
    (P + "structure", structure_ok, "    if len(md) < 2:", "    if len(md) < 0:"),
    (P + "structure", structure_ok, '            duplicates.append(h["number"])', "            pass"),
    (P + "extract", extract_ok, "if qualified(line) or not SPLIT_WORDS.search(line):", "if not SPLIT_WORDS.search(line):"),
    (P + "extract", extract_ok, "total = Fraction(1) if all(v <= 1 for v in values)", "total = Fraction(100) if all(v <= 1 for v in values)"),
    (P + "extract", extract_ok, "!= 1 or parallel:", "!= 1:"),
    (P + "extract", extract_ok, "                ambiguous = True", "                ambiguous = False"),
    (P + "extract", extract_ok, 'rate.rate_of}"), power=-1)', 'rate.rate_of}"), power=1)'),
    (P + "extract", extract_ok, 'if re.fullmatch(r"\\s*\\+\\s*", gap) and', 'if re.fullmatch(r"\\s*-\\s*", gap) and'),
    (P + "quantities", quantities_ok, '_KO_BIG = {"만": 10**4, "억": 10**8', '_KO_BIG = {"만": 10**4, "억": 10**7'),
    (P + "quantities", quantities_ok, 'if u[2] == "year" and value >= 1900', 'if u[2] == "year" and value >= 99999'),
    (P + "quantities", quantities_ok, "            continue  # 3D·v2·5x", "            pass  # 3D·v2·5x"),
    (P + "quantities", quantities_ok, 'if line[j] == "조" and not re.match', 'if line[j] == "X" and not re.match'),
    (P + "citation", citation_ok, "out[\"retracted\"] = bool(set(kinds) & BAD_KINDS)", "out[\"retracted\"] = False"),
    (P + "citation", citation_ok, '    elif match and out["retracted"] is False:\n        out["verdict"] = "pass"',
     '    elif match and out["retracted"] is False:\n        out["verdict"] = "unchecked"'),
    (P + "citation", citation_ok, "            out[\"found\"] = match is not None", "            out[\"found\"] = True"),
]


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory):
    real_citation.set_backend(build_backend(Path(tmp_path_factory.mktemp("fin_tools_mut"))))
    yield
    real_citation.set_backend(None)


def test_original_modules_pass_every_case_table(evidence):
    import neumann.finalize.tools.extract as ex
    import neumann.finalize.tools.quantities as qn
    import neumann.finalize.tools.structure as st
    import neumann.finalize.tools.sums as su

    assert sums_ok(su) and dimension_ok(real_dimension) and structure_ok(st) and extract_ok(ex) and quantities_ok(qn)
    assert citation_ok(real_citation)


@pytest.mark.parametrize("modname,check,old,new", MUTANTS, ids=[f"{m.rsplit('.', 1)[1]}-{i}" for i, (m, *_rest) in enumerate(MUTANTS)])
def test_every_mutant_is_killed(evidence, modname, check, old, new):
    mutant = load_mutant(modname, old, new)
    if modname.endswith("citation"):
        mutant._BACKEND = real_citation.get_backend()
    assert not survives(check, mutant), f"살아남은 변이: {modname}: {old!r} → {new!r}"
