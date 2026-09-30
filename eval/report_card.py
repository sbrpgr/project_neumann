"""리포트 카드 생성기 (E5-L3a, 계획서 §4 E5 L3).

지표 JSON 여러 개를 받아 한 장짜리 Markdown 리포트 카드를 쓴다.

    python -m eval.report_card --inputs <지표 JSON ...> --out docs/reports/report_card.md

정직 표기(04_평가_명세 §7)를 코드로 강제한다.
- 참조선(사람 상한 0.725, 빈도 기준선)을 우리 숫자보다 먼저 싣는다.
- 신청서 약속 표는 목표 미달 → 측정 전 → 달성 순으로 적는다. 미달·측정 전 목록을 표 위에 한 번 더 적는다.
- 입력에 없는 지표는 "측정 전"으로 적는다. 추정하거나 채워 넣지 않는다.
- 값은 입력 JSON의 숫자를 그대로 옮긴다(다시 반올림하지 않는다). 여러 파일을 합칠 때만 계산하고 그렇다고 적는다.
- mock generator의 결과는 성능이 아니다. mock이 한 장이라도 섞이면 약속 칸을 채우지 않고 "mock" 행으로만 둔다.
- 비상 규칙(rule) 결과는 따로 표시한다. Macro-F1은 "Neumann 비상 규칙" 행, 근거 연결은 전부 규칙이면 그 행,
  astra와 섞였으면 Neumann 행에 두고 약속 표 판정 칸에 "비상 규칙 카드 k/N장 포함"을 병기한다.

받는 입력(파일마다 자동 판별):
1. `python -m eval.macro_f1` 결과 JSON (`metric`이 "review-level multilabel Tier-1 Macro-F1"로 시작)
   - 시스템은 `predictions.generator_counts`로 정한다: astra→Neumann, rule→Neumann 비상 규칙,
     baseline→빈도 기준선(예측 파일 이름에 freq가 있을 때) 또는 기준선, mock→mock, 여럿→혼합.
2. `python -m eval.linkage` 보고서 JSON (`report_schema == "neumann.linkage/1"`). `card_generators`로 시스템을 나누고,
   같은 시스템 보고서가 여러 개면 링크 수를 더한다. 비율이 개수(ok/total)와 다르면 오류로 멈춘다.
3. 일반 지표 JSON (`schema == "neumann.metrics/1"`) — 백테스트(E5-L2a) 등 나머지 지표용:

       {"schema": "neumann.metrics/1",
        "source": "무엇이 만든 파일인지(선택)",
        "metrics": [
          {"id": "bt_hit_at_3", "system": "neumann", "value": 0.4, "n": 30,
           "ci95": [0.23, 0.57], "conditions": "…", "limits": "…"}
        ]}

   `system`은 필수다(기본값 없음). `value`는 숫자 또는 null(null이면 측정 전).
   `ci95`는 [low, high] 또는 {"low", "high"} 또는 생략.
   `id`와 `system`은 아래 METRIC_LABELS·SYSTEM_LABELS를 쓴다. 모르는 id도 받아서 "기타"로 싣는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from eval.macro_f1 import REFERENCE_LINES

GENERIC_SCHEMA = "neumann.metrics/1"
LINKAGE_SCHEMA = "neumann.linkage/1"
MACRO_F1_PREFIX = "review-level multilabel Tier-1 Macro-F1"
NOT_MEASURED = "측정 전"

SYSTEM_LABELS: dict[str, str] = {
    "neumann": "Neumann (astra)",
    "neumann_rule": "Neumann 비상 규칙",
    "llm_baseline": "일반 LLM 기준선",
    "freq_baseline": "빈도 기준선(안 읽음)",
    "baseline": "기준선(종류 미상)",
    "mixed": "혼합 generator",
    "mixed_mock": "mock 섞임(성능 아님)",
    "unknown_generator": "generator 미상",
    "mock": "mock(테스트용, 성능 아님)",
    "human": "사람(대표 블라인드)",
    "all": "전체",
}

# id → (이름, 단위). 단위 "ratio"는 0~1 비율, "count"는 개수, "diff"는 차이.
METRIC_LABELS: dict[str, tuple[str, str]] = {
    "macro_f1": ("지적 추출 Macro-F1 (리뷰 단위)", "ratio"),
    "micro_f1": ("지적 추출 Micro-F1 (리뷰 단위)", "ratio"),
    "linkage_rate": ("근거 연결률 (링크 단위)", "ratio"),
    "card_pass_rate": ("카드 통과율 (모든 근거 연결된 카드)", "ratio"),
    "drop_rate": ("폐기율 (버린 지적 / 전체 지적)", "ratio"),
    "bt_precision_at_3": ("백테스트 적중률 precision@3 (A 비율)", "ratio"),
    "bt_hit_at_3": ("백테스트 Top-3 적중 hit@3", "ratio"),
    "bt_false_positive_rate": ("백테스트 오탐률 (C 비율)", "ratio"),
    "bt_specificity": ("백테스트 특이성 (진짜 − 셔플 적중률)", "diff"),
    "bt_evidence_rate": ("백테스트 근거율", "ratio"),
    "bt_diff_precision_at_3": ("적중률 차이 Neumann − 일반 LLM (짝지은 부트스트랩)", "diff"),
    "judge_human_agreement": ("판정 일치율 (대표 10편 vs AI 다수결, A/B/C)", "ratio"),
    "judge_human_kappa": ("판정 κ (대표 vs AI 다수결, A 여부 이진)", "diff"),
    "corpus_linked_papers": ("표본 연결 논문 수", "count"),
    "source_link_rate": ("원문 링크 유효율", "ratio"),
    "demo_e2e": ("대표 계획 end-to-end 시연", "count"),
    "e2e_cards": ("라이브 E2E 화면 위험카드 수 (데모 계획서 합)", "count"),
}


@dataclass(frozen=True)
class Promise:
    """신청서 약속 한 줄. 목표와 비교할 지표 (id, system)."""

    key: str
    label: str
    metric_id: str
    system: str
    op: str  # ">=" 또는 "=="
    target: float
    target_text: str


PROMISES: tuple[Promise, ...] = (
    Promise("P1", "지적 추출 Macro-F1", "macro_f1", "neumann", ">=", 0.70, "≥ 0.70"),
    Promise("P2", "근거 연결률 (폐기율 병기)", "linkage_rate", "neumann", "==", 1.0, "100%"),
    Promise("P3", "백테스트 Top-3 적중(hit@3)", "bt_hit_at_3", "neumann", ">=", 0.50, "≥ 0.50"),
    Promise("P4", "표본 연결", "corpus_linked_papers", "all", ">=", 300, "≥ 300편"),
    Promise("P5", "원문 링크", "source_link_rate", "all", "==", 1.0, "100%"),
    Promise("P6", "대표 계획 end-to-end 시연", "demo_e2e", "all", ">=", 3, "3건"),
)

# 입력이 없어도 표에 "측정 전"으로 남길 지표 (id, system). 약속 지표는 약속 표에서 따로 채운다.
EXPECTED_DETAIL: tuple[tuple[str, str], ...] = (
    ("macro_f1", "neumann"),
    ("micro_f1", "neumann"),
    ("macro_f1", "neumann_rule"),
    ("micro_f1", "neumann_rule"),
    ("linkage_rate", "neumann"),
    ("drop_rate", "neumann"),
    ("bt_precision_at_3", "neumann"),
    ("bt_precision_at_3", "llm_baseline"),
    ("bt_diff_precision_at_3", "neumann"),
    ("bt_hit_at_3", "neumann"),
    ("bt_hit_at_3", "llm_baseline"),
    ("bt_false_positive_rate", "neumann"),
    ("bt_false_positive_rate", "llm_baseline"),
    ("bt_specificity", "neumann"),
    ("bt_specificity", "llm_baseline"),
    ("bt_evidence_rate", "neumann"),
    ("bt_evidence_rate", "llm_baseline"),
    ("judge_human_agreement", "all"),
    ("judge_human_kappa", "all"),
)

# 백테스트 표본 한계(PM 결정 2026-09-30, E5-L3b 전달): 대표 결정으로 n=5, 사유는 비용.
BACKTEST_LIMIT = (
    "백테스트는 n=5(대표 결정, 비용 사유; real 대 기준선, 셔플 없음, sol)다. 표본이 작아 95% 구간이 매우 넓다. "
    "유의성을 주장하지 않고 점추정·구간·차이의 방향만 말한다. 셔플이 없어 특이성(진짜 − 셔플)은 재지 않는다."
)

FOOTNOTE_R7 = (
    "**[주1] R7 매핑 한계.** Macro-F1 골드의 R7(일반화·적용범위)은 DISAPERE `asp_motivation-impact`(동기·영향)를 "
    "옮긴 근사다(04_평가_명세 §3.1). 동기·영향 지적은 R7의 하위 유형 중 '영향·함의 불명확'에 가깝고, "
    "외적 타당성·적용범위·외삽 같은 일반화 지적은 골드에 덜 잡힌다. R7 점수는 이 한계와 같이 읽는다."
)
FOOTNOTE_GOLD = (
    "**[주2] 신청서 대비 골드 대체.** 신청서는 수동 라벨 100건(2인 교차)을 약속했다. 본선은 공개 사람 라벨 "
    "DISAPERE 합의 골드(과반 합의)로 대체했다(대표 승인 2026-09-29, 계획서 §1.5, 04_평가_명세 §5 결정 5). "
    "목표 0.70은 그대로 둔다."
)
FOOTNOTE_EXCLUDED = (
    "**[주3] 골드 없는 클래스 제외.** 골드 support가 0인 클래스는 Macro-F1 평균에서 자동 제외한다"
    "(04_평가_명세 §2.1 규칙 ①). 사후에 support가 적다고 빼지 않는다. 제외 클래스의 FP는 Micro-F1에 들어간다."
)


class InputError(ValueError):
    """지표 JSON 형식 오류."""


@dataclass
class Metric:
    id: str
    system: str
    value: float | int | None
    n: int | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    detail: str = ""  # 예: "107/107"
    conditions: str = ""
    limits: str = ""
    source: str = ""  # 입력 파일 이름
    computed: bool = False  # 여러 입력을 합쳐 이 생성기가 계산한 값
    promise_note: str = ""  # 약속 표 판정 칸에 같이 적을 말(예: 비상 규칙 카드 수)

    @property
    def label(self) -> str:
        return METRIC_LABELS.get(self.id, (self.id, "ratio"))[0]


@dataclass
class Collected:
    metrics: list[Metric] = field(default_factory=list)
    inputs: list[tuple[str, str, str]] = field(default_factory=list)  # (경로, 종류, sha256)
    excluded_classes: dict[str, list[str]] = field(default_factory=dict)  # 시스템 → 제외 클래스
    scored_classes: dict[str, list[str]] = field(default_factory=dict)
    gold: dict[str, Any] = field(default_factory=dict)  # n, sha256, file
    commands: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ── 입력 읽기 ──────────────────────────────────────────────────────────────


def _num(x: Any, where: str, *, allow_none: bool = True) -> float | int | None:
    if x is None and allow_none:
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise InputError(f"{where}: 숫자가 아니다({x!r})")
    return x


def _int_or_none(x: Any, where: str) -> int | None:
    if x is None:
        return None
    if isinstance(x, bool) or not isinstance(x, int) or x < 0:
        raise InputError(f"{where}: n은 0 이상 정수여야 한다({x!r})")
    return x


def _ci(raw: Any, where: str) -> tuple[float | None, float | None]:
    if raw is None:
        return None, None
    if isinstance(raw, dict):
        lo, hi = raw.get("low"), raw.get("high")
    elif isinstance(raw, (list, tuple)) and len(raw) == 2:
        lo, hi = raw
    else:
        raise InputError(f"{where}: ci95는 [low, high] 또는 {{low, high}}여야 한다")
    lo = _num(lo, f"{where}.ci95.low")
    hi = _num(hi, f"{where}.ci95.high")
    if (lo is None) != (hi is None):
        raise InputError(f"{where}: ci95 한쪽만 있다")
    if lo is not None and hi is not None and lo > hi:
        raise InputError(f"{where}: ci95 low > high")
    return lo, hi


def _macro_system(obj: dict) -> str:
    gens = (obj.get("predictions") or {}).get("generator_counts") or {}
    names = [g for g, c in gens.items() if c]
    if len(names) != 1:
        return "mixed" if names else "baseline"
    g = names[0]
    if g == "astra":
        return "neumann"
    if g == "rule":
        return "neumann_rule"
    if g == "mock":
        return "mock"
    if g == "baseline":
        return "freq_baseline" if "freq" in Path(str(obj.get("pred_file", ""))).name.lower() else "baseline"
    return "mixed"


def _read_macro_f1(obj: dict, name: str, col: Collected) -> None:
    where = name
    system = _macro_system(obj)
    n = _int_or_none(obj.get("n"), f"{where}.n")
    boot = obj.get("bootstrap") or {}
    gens = (obj.get("predictions") or {}).get("generator_counts") or {}
    pred = obj.get("predictions") or {}
    excluded = list(obj.get("excluded_classes") or [])
    scored = list(obj.get("scored_classes") or [])
    gold_sha = str(obj.get("gold_sha256") or "")
    gold_name = Path(str(obj.get("gold_file") or "골드")).name
    cond = (
        f"리뷰 단위 멀티라벨 Tier-1, 골드 {gold_name} n={n} (sha256 {gold_sha[:12] or '없음'}), "
        f"부트스트랩 {boot.get('n_resamples', '?')}회 시드 {boot.get('seed', '?')} percentile, "
        f"generator {gens}, 예측 없음 {pred.get('missing', '?')}건은 빈 예측으로 채점"
    )
    lim = f"골드 support 0 클래스 {excluded or '없음'} 제외[주3], R7 근사[주1], 골드 대체[주2]"
    if system == "freq_baseline":
        lim += ". " + _freq_note(obj)
    if system == "mock":
        lim = "mock 예측이다. 성능 수치가 아니다. " + lim
    for mid in ("macro_f1", "micro_f1"):
        if mid not in obj:
            raise InputError(f"{where}: {mid}가 없다")
        lo, hi = _ci(obj.get(f"{mid}_ci95"), f"{where}.{mid}")
        col.metrics.append(
            Metric(mid, system, _num(obj[mid], f"{where}.{mid}"), n, lo, hi, "", cond, lim, name)
        )
    col.excluded_classes[system] = excluded
    col.scored_classes[system] = scored
    if gold_sha:
        col.gold.setdefault(gold_sha, {"n": n, "file": gold_name})
    if obj.get("pred_file") and obj.get("gold_file"):
        col.commands.append(
            f"python -m eval.macro_f1 --pred {obj['pred_file']} --gold {obj['gold_file']} --out <{name}>"
        )


def _freq_note(obj: dict) -> str:
    """빈도 기준선 한계 문구. 이 입력의 클래스별 재현율과 Macro·Micro 값만 쓴다(다른 시스템과 비교하지 않는다)."""
    per = obj.get("per_class") or {}
    scored = [c for c in obj.get("scored_classes") or [] if isinstance(per.get(c), dict)]
    full = [c for c in scored if per[c].get("recall") == 1.0]
    zero = [c for c in scored if per[c].get("recall") == 0.0]
    base = "안 읽는 기준선이다(04_평가_명세 §6: 기준선 없는 단독 숫자 보고 금지)"
    if not (full or zero):
        return base
    return (
        f"{base}. 늘 내는 코드({'·'.join(full) or '없음'})는 재현율 1.0, 안 내는 코드({'·'.join(zero) or '없음'})는 "
        f"재현율 0이라 Micro-F1({fmt_value(obj.get('micro_f1'))})이 Macro-F1({fmt_value(obj.get('macro_f1'))})보다 높다"
    )


def _read_generic(obj: dict, name: str, col: Collected) -> None:
    rows = obj.get("metrics")
    if not isinstance(rows, list):
        raise InputError(f"{name}: metrics는 목록이어야 한다")
    src = obj.get("source")
    for i, m in enumerate(rows):
        where = f"{name}.metrics[{i}]"
        if not isinstance(m, dict):
            raise InputError(f"{where}: 객체가 아니다")
        mid, system = m.get("id"), m.get("system")
        if not isinstance(mid, str) or not mid:
            raise InputError(f"{where}: id가 없다")
        if system is None:
            raise InputError(f"{where}: system이 없다(neumann·llm_baseline·freq_baseline·all 등을 적는다. 기본값 없음)")
        if not isinstance(system, str) or not system:
            raise InputError(f"{where}: system이 문자열이 아니다")
        if "value" not in m:
            raise InputError(f"{where}: value가 없다(측정 전이면 null)")
        lo, hi = _ci(m.get("ci95"), where)
        cond = str(m.get("conditions") or "")
        if src and not cond:
            cond = f"출처 {src}"
        col.metrics.append(
            Metric(
                mid,
                system,
                _num(m["value"], f"{where}.value"),
                _int_or_none(m.get("n"), f"{where}.n"),
                lo,
                hi,
                str(m.get("detail") or ""),
                cond,
                str(m.get("limits") or ""),
                name,
            )
        )


def _linkage_system(obj: dict) -> str:
    """보고서 하나의 시스템. mock이 한 장이라도 있으면 약속 칸을 채우지 않는 시스템으로 보낸다."""
    gens = {str(g): int(c) for g, c in (obj.get("card_generators") or {}).items() if c}
    if gens.get("mock"):
        return "mock" if set(gens) == {"mock"} else "mixed_mock"
    if not gens:
        return "neumann" if obj.get("cards_total") == 0 else "unknown_generator"
    if set(gens) == {"rule"}:
        return "neumann_rule"
    if set(gens) <= {"astra", "rule"}:
        return "neumann"  # astra + 비상 규칙 혼합: Neumann 칸에 두되 규칙 카드 수를 약속 행에 병기
    return "mixed"


def _check_rate(rate: Any, ok: int, total: int, where: str) -> None:
    """보고서에 적힌 비율이 개수와 맞는지. 맞지 않으면 어느 쪽을 믿을지 정할 수 없어 멈춘다."""
    if rate is None:
        if total:
            raise InputError(f"{where}: 개수 {ok}/{total}가 있는데 비율이 null이다")
        return
    rate = _num(rate, where)
    if not total or not math.isclose(rate, ok / total, rel_tol=0, abs_tol=1e-9):
        raise InputError(f"{where}: 비율 {rate}가 개수 {ok}/{total}와 맞지 않는다")


def _read_linkage(reports: list[tuple[dict, str]], col: Collected) -> None:
    """근거 연결 보고서를 시스템(card_generators)별로 나눠 합친다.

    - 전부 astra(또는 astra + 비상 규칙) → Neumann. 규칙 카드가 있으면 약속 행에 수를 병기한다.
    - 전부 비상 규칙 → "Neumann 비상 규칙" 행. 약속 칸을 채우지 않는다.
    - mock이 한 장이라도 있으면 → mock / mock 섞임 행. 약속 칸을 채우지 않는다.
    한 시스템에 보고서가 한 개면 값을 그대로, 여러 개면 합계로 다시 계산하고 '계산'으로 표시한다.
    """
    groups: dict[str, list[tuple[dict, str]]] = {}
    for obj, name in reports:
        for k in ("links_ok", "links_total", "cards_ok", "cards_total"):
            if obj.get(k) is None:
                raise InputError(f"{name}: {k}가 없다")
            _int_or_none(obj.get(k), f"{name}.{k}")
        if obj["links_ok"] > obj["links_total"] or obj["cards_ok"] > obj["cards_total"]:
            raise InputError(f"{name}: ok가 total보다 크다")
        _check_rate(obj.get("linkage_rate"), obj["links_ok"], obj["links_total"], f"{name}.linkage_rate")
        _check_rate(obj.get("card_pass_rate"), obj["cards_ok"], obj["cards_total"], f"{name}.card_pass_rate")
        d = obj.get("drop") or {}
        if d.get("available"):
            dt = _int_or_none(d.get("findings_total"), f"{name}.drop.findings_total")
            dd = _int_or_none(d.get("findings_dropped"), f"{name}.drop.findings_dropped")
            if dt is None or dd is None or dd > dt:
                raise InputError(f"{name}: drop 개수가 없거나 dropped > total")
            _check_rate(d.get("rate"), dd, dt, f"{name}.drop.rate")
        groups.setdefault(_linkage_system(obj), []).append((obj, name))
    for system, reps in groups.items():
        _linkage_group(system, reps, col)


def _linkage_group(system: str, reports: list[tuple[dict, str]], col: Collected) -> None:
    gens: dict[str, int] = {}
    links_ok = links_total = cards_ok = cards_total = 0
    drop_total = drop_dropped = 0
    drop_missing = 0
    verdicts: dict[str, int] = {}
    for obj, _name in reports:
        links_ok += obj["links_ok"]
        links_total += obj["links_total"]
        cards_ok += obj["cards_ok"]
        cards_total += obj["cards_total"]
        for g, c in (obj.get("card_generators") or {}).items():
            gens[str(g)] = gens.get(str(g), 0) + int(c)
        v = str(obj.get("verdict"))
        verdicts[v] = verdicts.get(v, 0) + 1
        d = obj.get("drop") or {}
        if d.get("available"):
            drop_total += int(d["findings_total"])
            drop_dropped += int(d["findings_dropped"])
        else:
            drop_missing += 1
    names = ", ".join(n for _, n in reports)
    real = {g: c for g, c in gens.items() if c}
    n_gen = sum(real.values())
    single = len(reports) == 1
    one = reports[0][0]
    cond = f"결과 {len(reports)}건 전수(표본 아님), 원문 글자 단위 대조, 카드 generator {real or '없음'}, 판정 {verdicts}"
    lim = "전수 계산이라 구간 없음. 폐기율과 같이 읽는다(폐기율 없는 100%는 의미가 약하다, 04_평가_명세 §2.2)"
    note = ""
    if real.get("rule"):
        note = f"비상 규칙 카드 {real['rule']}/{n_gen}장 포함"
        cond += f", {note}"
        lim = "비상 규칙(비LLM) 카드가 들어 있다. astra 카드만의 값이 아니다. " + lim
    if system in ("mock", "mixed_mock"):
        lim = f"mock 카드 {real.get('mock', 0)}/{n_gen}장이 들어 있다. 성능 수치가 아니고 약속 판정에 쓰지 않는다. " + lim
    elif system in ("mixed", "unknown_generator"):
        lim = "카드 generator가 astra·규칙이 아니거나 비어 있다. 약속 판정에 쓰지 않는다. " + lim
    rate = one.get("linkage_rate") if single else (links_ok / links_total if links_total else None)
    col.metrics.append(
        Metric("linkage_rate", system, _num(rate, "linkage_rate"), links_total, None, None,
               f"{links_ok}/{links_total}", cond, lim, names, computed=not single, promise_note=note)
    )
    cpr = one.get("card_pass_rate") if single else (cards_ok / cards_total if cards_total else None)
    col.metrics.append(
        Metric("card_pass_rate", system, _num(cpr, "card_pass_rate"), cards_total, None, None,
               f"{cards_ok}/{cards_total}", cond, lim, names, computed=not single)
    )
    if drop_missing == len(reports):
        col.metrics.append(
            Metric("drop_rate", system, None, None, None, None, "폐기율 없음", cond,
                   "결과에 폐기 수가 없다. 연결률 100%의 의미가 약하다", names)
        )
    else:
        drate = (one.get("drop") or {}).get("rate") if single else (drop_dropped / drop_total if drop_total else None)
        dlim = "전수 계산" + (f". 결과 {drop_missing}건은 폐기율이 없어 합계에서 빠졌다" if drop_missing else "")
        col.metrics.append(
            Metric("drop_rate", system, _num(drate, "drop_rate"), drop_total, None, None,
                   f"{drop_dropped}/{drop_total}", cond, dlim, names, computed=not single)
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(paths: list[Path]) -> Collected:
    col = Collected()
    linkage: list[tuple[dict, str]] = []
    for p in paths:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InputError(f"{p}: JSON 파싱 실패 ({exc})") from exc
        if not isinstance(obj, dict):
            raise InputError(f"{p}: 최상위가 객체가 아니다")
        name = p.name
        if str(obj.get("metric", "")).startswith(MACRO_F1_PREFIX):
            kind = "macro_f1"
            _read_macro_f1(obj, name, col)
        elif obj.get("report_schema") == LINKAGE_SCHEMA:
            kind = "linkage"
            linkage.append((obj, name))
        elif obj.get("schema") == GENERIC_SCHEMA:
            kind = "metrics"
            _read_generic(obj, name, col)
        else:
            raise InputError(
                f"{p}: 모르는 형식이다(eval.macro_f1 결과, {LINKAGE_SCHEMA}, {GENERIC_SCHEMA} 중 하나여야 한다)"
            )
        col.inputs.append((str(p), kind, _sha256(p)))
    _read_linkage(linkage, col)
    keys = [(m.id, m.system) for m in col.metrics]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise InputError(f"같은 (지표, 시스템)이 두 번 이상 들어왔다: {dup}. 어느 값을 쓸지 정할 수 없다")
    return col


# ── 표기 ──────────────────────────────────────────────────────────────────


def fmt_value(x: float | int | None) -> str:
    """입력 숫자를 그대로 적는다(다시 반올림하지 않는다). 없으면 '측정 전'."""
    if x is None:
        return NOT_MEASURED
    return str(x)


def fmt_ci(m: Metric | None) -> str:
    if m is None or m.value is None:
        return "—"
    if m.ci_low is None:
        return "없음"
    return f"[{fmt_value(m.ci_low)}, {fmt_value(m.ci_high)}]"


def fmt_n(m: Metric | None) -> str:
    if m is None or m.value is None or m.n is None:
        return "—"
    return str(m.n)


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def _sys(system: str) -> str:
    return SYSTEM_LABELS.get(system, system)


def judge(p: Promise, m: Metric | None) -> str:
    if m is None or m.value is None:
        return NOT_MEASURED
    v = m.value
    ok = v >= p.target if p.op == ">=" else v == p.target
    if not ok:
        return "미달"
    if p.op == ">=" and m.ci_low is not None and m.ci_low < p.target:
        return "달성(구간 하한은 목표 아래)"
    if p.metric_id == "linkage_rate":
        return "달성(폐기율 병기)"
    return "달성"


def _order(verdict: str) -> int:
    if verdict == "미달":
        return 0
    if verdict == NOT_MEASURED:
        return 1
    return 2


def render(col: Collected, *, now: str, commit: str, command: str, eval_model: str | None = None) -> str:
    by = {(m.id, m.system): m for m in col.metrics}
    L: list[str] = []
    add = L.append

    add("# Project Neumann — 검증 리포트 카드")
    add("")
    add(f"- 생성: {now} · 코드 커밋: `{commit}` · 생성 명령: `{command}`")
    add("- 규칙(04_평가_명세 §7): 참조선 먼저 · 미달 먼저 · 모든 숫자에 n과 95% 구간 · 없는 지표는 \"측정 전\"(추정 금지)")
    add("- 값은 입력 JSON의 숫자를 그대로 옮겼다. 합쳐서 계산한 값은 '계산'으로 표시했다.")
    if eval_model:
        add(f"- Neumann 행의 평가 모델: `{eval_model}` (명령행 `--eval-model` 값. 입력 JSON에는 모델 기록이 없다)")
    add("")

    # 1. 참조선
    add("## 1. 참조선 — 우리 숫자보다 먼저 본다")
    add("")
    add("| 참조선 | 값 | 95% 구간 | n | 조건·출처 |")
    add("|---|---|---|---|---|")
    hu = REFERENCE_LINES["human_upper_bound_consensus_gold"]
    add(
        f"| 사람 간 일치 상한(합의 골드) Macro-F1 — 외부 실측, 우리 성능 아님 | {fmt_value(hu['macro_f1'])} "
        f"| [{fmt_value(hu['ci95'][0])}, {fmt_value(hu['ci95'][1])}] | 29리뷰(LOO) | {_cell(hu['note'])} |"
    )
    for mid in ("macro_f1", "micro_f1"):
        m = by.get((mid, "freq_baseline"))
        add(
            f"| 빈도 기준선(안 읽음, 최빈 3코드) {METRIC_LABELS[mid][0]} | {fmt_value(m.value if m else None)} "
            f"| {fmt_ci(m)} | {fmt_n(m)} | {_cell(m.conditions) if m else '입력 없음'} |"
        )
    m = by.get(("bt_precision_at_3", "freq_baseline"))
    add(
        f"| 빈도 기준선 백테스트 적중률 precision@3 (계산만, 발표 제외) | {fmt_value(m.value if m else None)} "
        f"| {fmt_ci(m)} | {fmt_n(m)} | {_cell(m.conditions) if m else '입력 없음'} |"
    )
    add("")

    # 2. 신청서 약속 대비 — 미달 먼저
    rows = []
    for p in PROMISES:
        m = by.get((p.metric_id, p.system))
        rows.append((p, m, judge(p, m)))
    rows.sort(key=lambda r: _order(r[2]))  # 안정 정렬: 같은 판정 안에서는 약속 번호 순
    miss = [f"{p.key} {p.label}" for p, _, v in rows if v == "미달"]
    todo = [f"{p.key} {p.label}" for p, _, v in rows if v == NOT_MEASURED]
    add("## 2. 신청서 약속 대비 — 미달을 먼저 적는다")
    add("")
    add(f"- **목표 미달 {len(miss)}건:** {', '.join(miss) if miss else '없음'}")
    add(f"- **측정 전 {len(todo)}건:** {', '.join(todo) if todo else '없음'}")
    add("")
    add("| # | 약속 (신청서) | 목표 | 측정값 | 95% 구간 | n | 판정 | 입력 |")
    add("|---|---|---|---|---|---|---|---|")
    for p, m, v in rows:
        val = fmt_value(m.value if m else None)
        if m and m.detail and m.value is not None:
            val += f" ({m.detail})"
        if eval_model and p.system == "neumann" and m and m.value is not None:
            val += f" ({eval_model})"
        verdict = f"**{v}**" + (f" · {m.promise_note}" if m and m.promise_note and m.value is not None else "")
        add(
            f"| {p.key} | {p.label} | {p.target_text} | {val} | {fmt_ci(m)} | {fmt_n(m)} | {verdict} "
            f"| {_cell(m.source) if m else '—'} |"
        )
    add("")
    add("판정은 점추정과 목표를 비교한다. 구간 하한이 목표 아래면 그렇게 적는다. "
        "Macro-F1 목표는 사람 간 상한(1절) 근처라는 점을 같이 읽는다[주2].")
    add("")

    # 3. 지표별 상세
    add("## 3. 지표별 값·n·95% 구간·조건·한계")
    add("")
    add("| 지표 | 시스템 | 값 | 95% 구간 | n | 조건 | 한계 | 입력 |")
    add("|---|---|---|---|---|---|---|---|")
    order_ids = list(METRIC_LABELS)
    seen = set()
    detail_keys = list(dict.fromkeys([*[(m.id, m.system) for m in col.metrics], *EXPECTED_DETAIL]))
    detail_keys.sort(key=lambda k: (order_ids.index(k[0]) if k[0] in order_ids else len(order_ids), k[0]))
    for key in detail_keys:
        if key in seen:
            continue
        seen.add(key)
        m = by.get(key)
        mid, system = key
        label = METRIC_LABELS.get(mid, (f"(기타) {mid}", ""))[0]
        if m is None:
            add(f"| {label} | {_sys(system)} | {NOT_MEASURED} | — | — | — | — | 입력 없음 |")
            continue
        val = fmt_value(m.value)
        if m.detail:
            val += f" ({m.detail})"
        if m.computed:
            val += " 계산"
        add(
            f"| {label} | {_sys(system)} | {val} | {fmt_ci(m)} | {fmt_n(m)} | {_cell(m.conditions) or '—'} "
            f"| {_cell(m.limits) or '—'} | {_cell(m.source)} |"
        )
    add("")

    # 4. 골드 없는 클래스
    add("## 4. 골드 없는 클래스 — Macro-F1에서 제외[주3]")
    add("")
    if col.excluded_classes:
        add("| 시스템 | 채점 클래스 | 제외 클래스(골드 support 0) |")
        add("|---|---|---|")
        for system, ex in col.excluded_classes.items():
            sc = col.scored_classes.get(system, [])
            add(f"| {_sys(system)} | {', '.join(sc) or '없음'} | {', '.join(ex) or '없음'} |")
    else:
        add(f"- {NOT_MEASURED}: Macro-F1 입력이 없어 제외 목록을 적을 수 없다.")
    if col.gold:
        add("")
        for sha, g in col.gold.items():
            add(f"- 골드: {g['file']} n={g['n']} sha256 `{sha}`")
    add("")

    # 5. 각주
    add("## 5. 각주")
    add("")
    add(FOOTNOTE_R7)
    add("")
    add(FOOTNOTE_GOLD)
    add("")
    add(FOOTNOTE_EXCLUDED)
    add("")

    # 6. 한계
    add("## 6. 한계 — 먼저 말한다")
    add("")
    lims = [
        "측정 전 지표는 비워 두지 않고 '측정 전'으로 적었다. 이 카드의 빈칸을 추정값으로 읽지 않는다.",
        "사람 간 상한 0.725는 DISAPERE 외부 실측이다. 우리 시스템 성능이 아니라 과제 난이도의 천장이다.",
        "빈도 기준선은 입력을 읽지 않는다. 기준선 없는 단독 숫자는 보고하지 않는다(04_평가_명세 §6).",
        BACKTEST_LIMIT,
        "백테스트 판정 조건(블라인드 여부·판정자 수와 구성·사람 재검토 여부)은 각 지표의 '조건' 칸을 본다. "
        "입력에 없으면 측정 전이다.",
    ]
    if any(m.system in ("mock", "mixed_mock") for m in col.metrics):
        lims.insert(0, "mock generator 입력이 있다. 그 행은 테스트용이고 성능이 아니다. 약속 판정에 쓰지 않았다.")
    for note in col.notes:
        lims.append(note)
    for i, s in enumerate(lims, 1):
        add(f"{i}. {s}")
    add("")

    # 7. 재현
    add("## 7. 재현")
    add("")
    add("| 입력 파일 | 종류 | sha256 |")
    add("|---|---|---|")
    if col.inputs:
        for path, kind, sha in col.inputs:
            add(f"| `{_cell(path)}` | {kind} | `{sha}` |")
    else:
        add("| (없음) | — | — |")
    add("")
    add("```")
    for c in col.commands:
        add(c)
    add(command)
    add("```")
    add("")
    return "\n".join(L)


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return out.stdout.strip() or "알 수 없음"
    except (OSError, subprocess.SubprocessError):
        return "알 수 없음"


def build(paths: list[Path], *, now: str | None = None, commit: str | None = None, command: str | None = None,
          eval_model: str | None = None) -> str:
    col = collect(paths)
    now = now or datetime.now().astimezone().isoformat(timespec="seconds")
    commit = commit or _git_commit()
    command = command or "python -m eval.report_card --inputs " + " ".join(str(p) for p in paths)
    return render(col, now=now, commit=commit, command=command, eval_model=eval_model)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m eval.report_card", description="리포트 카드 생성(E5-L3a)")
    ap.add_argument("--inputs", nargs="*", type=Path, default=[], help="지표 JSON 파일들(없으면 전부 측정 전)")
    ap.add_argument("--out", type=Path, required=True, help="리포트 카드 Markdown 경로")
    ap.add_argument("--eval-model", default=None,
                    help="Neumann 행을 잰 LLM 모델(입력 JSON에 기록이 없을 때). 약속 표 Neumann 행 측정값 옆과 머리에 적는다")
    args = ap.parse_args(argv)
    command = "python -m eval.report_card --inputs " + " ".join(p.as_posix() for p in args.inputs)
    command += f" --out {args.out.as_posix()}"
    if args.eval_model:
        command += f" --eval-model {args.eval_model}"
    try:
        text = build(args.inputs, command=command, eval_model=args.eval_model)
    except (InputError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    col_lines = [ln for ln in text.splitlines() if ln.startswith("- **목표 미달") or ln.startswith("- **측정 전")]
    for ln in col_lines:
        print(ln.replace("**", ""))
    print(f"리포트 카드: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
