"""라이브 E2E 요약 → 일반 지표 JSON(neumann.metrics/1) 변환 (E5-L3b).

    python scripts/metrics_from_e2e.py --summary docs/reports/E5-L0e2e_live_summary.json \\
        --model gpt-6-astra --product-model gpt-6.1-sol --out docs/reports/E5-L3b_metrics_e2e.json

`tests/e2e/test_live.py`가 남긴 요약(`E5-L0e2e_live_summary.json`)을 `python -m eval.report_card`가 읽는
일반 지표 형식으로 옮긴다. 파일만 읽는다(서버·OpenAI를 부르지 않는다).

만드는 지표(값은 요약의 개수로만 계산한다. 추정·보정 없음):
- `linkage_rate`/<연결 시스템>   근거 연결률 = 데모 계획서들의 링크 합 ok / 합 total (계획서별 개수는 detail)
- `card_pass_rate`/<연결 시스템> 모든 근거가 연결된 카드 / 검사 카드
- `drop_rate`/<연결 시스템>      폐기율 = 버린 지적 / 전체 지적 (연결 요약 문자열의 `폐기율 a/b`에서 읽는다)
- `e2e_cards`/neumann            화면에 나온 LLM(astra) 위험카드 수(데모 계획서 합). 규칙 카드는 `e2e_cards`/neumann_rule로 따로
- `demo_e2e`/all                 실패 0으로 끝까지 통과한 데모 계획서 수(신청서 약속 P6). 통과 조건에 근거 연결
                                 검사가 들어 있어, 연결 시스템이 미기록(참고)이면 이것도 참고 행으로 간다
- `--product-model`을 주면, 그 모델로는 재지 않은 헤드라인 지표를 값 null(= 측정 전) 행으로 적는다.

<연결 시스템>은 연결 검사 실행의 카드 generator(`plans[*].linkage.card_generators`)로 정한다. 키는 generator만
("astra") 또는 generator:model("astra:gpt-6.1-sol")이다. 모델이 붙어 있으면 `--model`과 다를 때 멈춘다.
계획서 단위 `card_generators`·`models.card_generators`는 읽지 않는다(약속 판정 입력은 `linkage` 한 곳).
`eval.report_card`의 연결 보고서 규칙과 같다.
- 한 계획서라도 기록이 없으면 → UNRECORDED_SYSTEM(참고 행, 약속 P2 판정에 안 씀. PM 결정 2026-09-30)
- 전부 astra(계약 이름 "제품 LLM") → neumann. astra+rule → RULE_MIXED_SYSTEM(LLM 카드와 분리, 약속 판정 제외. PM 결정)
- 전부 rule → neumann_rule. mock이 한 장이라도 있으면 거부. 그 밖의 generator → mixed

정직 규칙:
- 샘플 모드 요약(mode != live)이나 파이프라인 미연결 요약은 거부한다(성능 수치가 아니다).
- 요약에 적힌 비율이 개수와 다르거나, 요약 문자열의 개수와 필드의 개수가 다르면 멈춘다(어느 쪽을 믿을지 정할 수 없다).
- 비율은 소수 4자리로 적되, 1.0이 아닌 값을 1.0으로, 0이 아닌 값을 0으로 반올림하지 않는다. 정확한 개수는 detail에 둔다.
- 모델은 `--model`로 받아 조건 칸에 적는다(기본값 없음). 지표 행의 `model`(카드 '모델' 칸)은 요약에 기록된 모델만 쓴다:
  연결·폐기·카드 통과는 `models.llm_model`, 화면 카드 수는 `models.view_model_id`, 시연은 둘이 같을 때. 기록이 없으면 행에
  `model`을 두지 않는다(카드에 "(모델 기록 없음)"). 요약에 `plans[*].models.llm_model`(E5-L1e2e 이후)이 있으면
  대조해서 다르면 멈추고, 없으면 조건 칸에 "모델은 명령행 값(요약에 기록 없음)"이라고 적는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "neumann.metrics/1"
NEGATIVE_PLAN = "negative_recipe.md"  # tests/e2e/test_live.py의 범위 밖 입력
# 제품 기본 모델로 다시 재지 않은 헤드라인 지표(값 null 행). (id, system)
PRODUCT_UNMEASURED: tuple[tuple[str, str], ...] = (
    ("macro_f1", "neumann"),
    ("linkage_rate", "neumann"),
    ("drop_rate", "neumann"),
    ("demo_e2e", "all"),
)
DECISION_REF = "docs/decisions.md 2026-09-30 19:38(평가 모델·제품 모델 구분)·19:42(실제 호출 동결)"
# 연결 검사 실행의 카드 generator가 기록되지 않았을 때의 시스템. 약속 표는 system "neumann"만 보므로 P2는 측정 전으로 남는다.
UNRECORDED_SYSTEM = "Neumann 참고(검사 실행 generator 미기록, 약속 판정 제외)"
# LLM 카드와 규칙 카드(경고 단계 "분야 수준 참고 · 계획서와 대조 안 됨"·비상 경로)가 섞인 연결 검사. 요약에 generator별 링크 수가
# 없어 LLM 카드만의 값을 나눌 수 없으므로 Neumann(LLM) 행과 분리한다(PM 결정 2026-09-30: 성적표에서 LLM 카드와 분리).
RULE_MIXED_SYSTEM = "Neumann LLM+규칙 카드 혼합(LLM만 분리 불가, 약속 판정 제외)"

_FRAC = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
_SUM_LINK = re.compile(r"근거 연결률 (\d+)/(\d+)")
_SUM_CARD = re.compile(r"카드 통과 (\d+)/(\d+)")
_SUM_DROP = re.compile(r"폐기율 (\d+)/(\d+) = [0-9.]+ \(([^)]*)\)")


class InputError(ValueError):
    """요약 JSON 형식·일관성 오류."""


def ratio(ok: int, total: int) -> float:
    """ok/total을 소수 4자리로. 단 1.0이 아닌 값은 1.0으로, 0이 아닌 값은 0으로 만들지 않는다."""
    if total <= 0:
        raise InputError(f"비율 분모가 0 이하다({ok}/{total})")
    exact = ok / total
    r = round(exact, 4)
    if r == 1.0 and ok != total:
        return math.floor(exact * 10_000) / 10_000
    if r == 0.0 and ok != 0:
        return float(f"{exact:.2e}")
    return r


def _frac(s: Any, where: str) -> tuple[int, int]:
    m = _FRAC.match(str(s)) if isinstance(s, str) else None
    if not m:
        raise InputError(f"{where}: 'ok/total' 형식이 아니다({s!r})")
    ok, total = int(m.group(1)), int(m.group(2))
    if ok > total:
        raise InputError(f"{where}: ok가 total보다 크다({s})")
    return ok, total


def _plan_linkage(name: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    """계획서 하나의 연결 검사 개수. 검사하지 않았으면 None."""
    lk = entry.get("linkage") or {}
    if "links" not in lk:
        return None
    where = f"plans[{name}].linkage"
    links = _frac(lk.get("links"), f"{where}.links")
    cards = _frac(lk.get("cards"), f"{where}.cards")
    rate = lk.get("linkage_rate")
    if links[1] == 0:
        if rate is not None:
            raise InputError(f"{where}: 링크 0개인데 linkage_rate가 {rate}다")
    elif isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isclose(
        rate, links[0] / links[1], rel_tol=0, abs_tol=1e-9
    ):
        raise InputError(f"{where}: linkage_rate {rate!r}가 개수 {links[0]}/{links[1]}와 맞지 않는다")
    summary = str(lk.get("summary") or "")
    for pat, got, label in ((_SUM_LINK, links, "근거 연결률"), (_SUM_CARD, cards, "카드 통과")):
        m = pat.search(summary)
        if not m or (int(m.group(1)), int(m.group(2))) != got:
            raise InputError(f"{where}: summary의 {label} 개수가 필드({got[0]}/{got[1]})와 다르다: {summary!r}")
    drop = None
    m = _SUM_DROP.search(summary)
    if m:
        d_ok, d_total = int(m.group(1)), int(m.group(2))
        if d_ok > d_total:
            raise InputError(f"{where}: 폐기 수가 전체 지적보다 크다({d_ok}/{d_total})")
        drop = (d_ok, d_total, m.group(3))
    elif "폐기율" in summary and "폐기율 없음" not in summary:
        raise InputError(f"{where}: summary의 폐기율을 읽을 수 없다: {summary!r}")
    gens = lk.get("card_generators")
    if gens is not None:
        if not isinstance(gens, dict) or any(
            not isinstance(g, str) or isinstance(c, bool) or not isinstance(c, int) or c < 0 for g, c in gens.items()
        ):
            raise InputError(f"{where}.card_generators: {{generator: 0 이상 정수}}여야 한다({gens!r})")
    card_models: set[str] = set()
    if gens is not None:
        # 키는 generator만("astra") 또는 generator:model("astra:gpt-6.1-sol", tests/e2e card_generators() 형식) 둘 다 받는다.
        merged: dict[str, int] = {}
        for g, c in gens.items():
            if not c:
                continue
            gen, _, mdl = g.partition(":")
            merged[gen] = merged.get(gen, 0) + c
            if mdl and mdl != "-":
                card_models.add(mdl)
        gens = merged
        if not gens and cards[1]:
            gens = None  # 카드가 있는데 generator가 비어 있으면 기록 없음과 같다(eval.report_card의 unknown_generator)
    return {"links": links, "cards": cards, "drop": drop, "verdict": lk.get("verdict"), "gens": gens,
            "card_models": card_models}


def model_source(demo: dict[str, Any], model: str) -> str:
    """`--model`을 요약의 `plans[*].models.llm_model`(E5-L1e2e 이후 기록)과 대조한다. 다르면 멈춘다."""
    recorded = {
        n: (e.get("models") or {}).get("llm_model")
        for n, e in demo.items() if isinstance(e, dict) and isinstance(e.get("models"), dict)
        and (e.get("models") or {}).get("llm_model")
    }
    wrong = {n: m for n, m in recorded.items() if m != model}
    if wrong:
        raise InputError(f"--model {model!r}이 요약의 models.llm_model과 다르다: {wrong}")
    if not recorded:
        return "모델은 명령행 값(요약에 기록 없음)"
    if len(recorded) == len(demo):
        return f"요약 models.llm_model {len(recorded)}/{len(demo)}건과 일치"
    return f"요약 models.llm_model {len(recorded)}/{len(demo)}건과 일치, 나머지는 명령행 값(요약에 기록 없음)"


def recorded_model(demo: dict[str, Any], key: str, model: str) -> str | None:
    """데모 계획서 전부의 `models.<key>`가 기록돼 있고 모두 같을 때만 그 값. 카드 '모델' 칸은 이 기록만 쓴다
    (명령행 `--model`은 조건 칸에만). 기록이 `--model`과 다르면 멈춘다."""
    vals = [((e.get("models") or {}) if isinstance(e, dict) else {}).get(key) for e in demo.values()]
    got = {str(v) for v in vals if v}
    if got - {model}:
        raise InputError(f"--model {model!r}이 요약의 models.{key} {sorted(got)}와 다르다")
    return model if vals and all(vals) else None


def linkage_system(measured: dict[str, dict[str, Any]]) -> tuple[str, str, str]:
    """연결 검사 실행의 카드 generator로 (시스템, 약속 칸 병기 문구, 한계 문구 머리)를 정한다."""
    missing = [n for n, v in measured.items() if v["gens"] is None]
    if missing:
        return (
            UNRECORDED_SYSTEM,
            "검사 실행 카드 generator 미기록",
            f"연결 검사 실행의 카드 generator가 요약에 없다({', '.join(missing)}). 그래서 약속 P2 판정에 쓰지 않는 "
            "참고값이다(PM 결정 2026-09-30: generator를 기록한 라이브 결과로 채운다)",
        )
    gens: dict[str, int] = {}
    for v in measured.values():
        for g, c in v["gens"].items():
            gens[g] = gens.get(g, 0) + c
    if gens.get("mock"):
        raise InputError(f"연결 검사 카드에 mock generator가 있다({gens}): 성능 수치가 아니다")
    total = sum(gens.values())
    if gens and set(gens) == {"rule"}:
        return "neumann_rule", f"비상 규칙 카드 {total}/{total}장", "전부 비상 규칙(비LLM) 카드다"
    if set(gens) <= {"astra", "rule"}:
        if gens.get("rule"):
            return (RULE_MIXED_SYSTEM, f"규칙 카드 {gens['rule']}/{total}장 포함",
                    "규칙(비LLM) 카드가 섞여 있다. 요약에 generator별 링크 수가 없어 LLM 카드만의 값을 나눌 수 없으므로 "
                    "Neumann(LLM) 행과 분리한다(PM 결정 2026-09-30)")
        return "neumann", f"검사 실행 카드 generator {gens or '없음'}", ""
    return "mixed", f"검사 실행 카드 generator {gens}", "카드 generator가 astra·규칙이 아니다. 약속 판정에 쓰지 않는다"


def convert(summary: dict[str, Any], *, model: str, product_model: str | None = None,
            summary_name: str = "E5-L0e2e_live_summary.json", summary_sha256: str = "") -> dict[str, Any]:
    if not model or not model.strip():
        raise InputError("--model이 비었다(요약에 모델 이름이 없어서 받아야 한다)")
    if summary.get("mode") != "live":
        raise InputError(f"mode={summary.get('mode')!r}: 라이브 요약만 받는다(샘플 모드 결과는 성능이 아니다)")
    state = ((summary.get("health") or {}).get("pipeline") or {}).get("state")
    if state != "connected":
        raise InputError(f"health.pipeline.state={state!r}: 파이프라인 연결된 실행만 받는다")
    plans = summary.get("plans")
    if not isinstance(plans, dict) or not plans:
        raise InputError("plans가 비었다")

    demo = {n: e for n, e in plans.items() if n != NEGATIVE_PLAN}
    if not demo:
        raise InputError("데모 계획서 결과가 없다")
    run = (
        f"라이브 E2E {summary.get('base_url', '?')} {summary.get('started_at', '?')}~{summary.get('finished_at', '?')}, "
        f"1회 실행, 평가 모델 {model}({model_source(demo, model)})"
    )
    measured: dict[str, dict[str, Any]] = {}
    unmeasured: list[str] = []
    for name, entry in demo.items():
        if not isinstance(entry, dict):
            raise InputError(f"plans[{name}]: 객체가 아니다")
        if entry.get("source") != "pipeline":
            raise InputError(f"plans[{name}].source={entry.get('source')!r}: 파이프라인 결과가 아니다")
        got = _plan_linkage(name, entry)
        if got is None:
            unmeasured.append(name)
        else:
            other = got["card_models"] - {model}
            if other:
                raise InputError(f"plans[{name}].linkage.card_generators의 카드 모델 {sorted(other)}이 --model {model!r}과 다르다")
            measured[name] = got

    metrics: list[dict[str, Any]] = []
    rec_result = recorded_model(demo, "llm_model", model)  # /premortem 결과 manifest(연결 검사 실행)
    rec_view = recorded_model(demo, "view_model_id", model)  # 화면 실행
    rec_demo = rec_result if rec_result and rec_result == rec_view else None  # 시연은 두 실행 모두
    shown = {n: int(e.get("n_cards") or 0) for n, e in demo.items()}
    gens: dict[str, int] = {}
    for e in demo.values():
        for g, c in (e.get("generators") or {}).items():
            gens[str(g)] = gens.get(str(g), 0) + int(c)
    degraded = sum(len(e.get("stages_not_ok") or []) for e in demo.values())
    miss_note = f". 연결 검사를 하지 않은 데모 {len(unmeasured)}건({', '.join(unmeasured)})은 합계에서 빠졌다" if unmeasured else ""

    lsys: str | None = None
    if measured:
        lsys, lnote, lhead = linkage_system(measured)
        gen_note = (
            (f"{lhead}. " if lhead else "")
            + "연결 검사는 화면 실행과 별도인 같은 계획서의 /premortem 재실행 결과다"
            f"(화면 실행 카드 generator {gens or '없음'}, 강등 단계 {degraded}개)"
        )
        per = lambda key: " · ".join(f"{n} {v[key][0]}/{v[key][1]}" for n, v in measured.items())  # noqa: E731
        l_ok = sum(v["links"][0] for v in measured.values())
        l_tot = sum(v["links"][1] for v in measured.values())
        c_ok = sum(v["cards"][0] for v in measured.values())
        c_tot = sum(v["cards"][1] for v in measured.values())
        cond = (
            f"{run}. 데모 계획서 {len(measured)}건 /premortem 결과 전수, eval.linkage.check_result 원문 글자 단위 대조, "
            f"계획서별 개수 합산(계산)"
        )
        lim = f"{gen_note}. 전수라 구간 없음. 제품 기본 모델로는 재측정 안 함{miss_note}"
        metrics.append({
            "id": "linkage_rate", "system": lsys, "value": ratio(l_ok, l_tot) if l_tot else None,
            "n": l_tot, "detail": f"{l_ok}/{l_tot}; {per('links')}; {lnote}", "conditions": cond,
            "limits": lim + ". 폐기율과 같이 읽는다(04_평가_명세 §2.2)",
            **({"model": rec_result} if rec_result else {}),
        })
        metrics.append({
            "id": "card_pass_rate", "system": lsys, "value": ratio(c_ok, c_tot) if c_tot else None,
            "n": c_tot, "detail": f"{c_ok}/{c_tot}; {per('cards')}", "conditions": cond, "limits": lim,
            **({"model": rec_result} if rec_result else {}),
        })
        with_drop = {n: v["drop"] for n, v in measured.items() if v["drop"]}
        no_drop = [n for n, v in measured.items() if not v["drop"]]
        if with_drop:
            d_ok = sum(d[0] for d in with_drop.values())
            d_tot = sum(d[1] for d in with_drop.values())
            srcs = sorted({d[2] for d in with_drop.values()})
            metrics.append({
                "id": "drop_rate", "system": lsys, "value": ratio(d_ok, d_tot) if d_tot else None, "n": d_tot,
                "detail": f"{d_ok}/{d_tot}; " + " · ".join(f"{n} {d[0]}/{d[1]}" for n, d in with_drop.items()),
                "conditions": f"{cond}. 폐기 출처 {', '.join(srcs)}(검증 단계에서 버린 지적)",
                "limits": (f"{lhead}. " if lhead else "") + "전수 계산"
                + (f". 폐기율이 없는 {', '.join(no_drop)}은 합계에서 빠졌다" if no_drop else "") + miss_note,
                **({"model": rec_result} if rec_result else {}),
            })
        else:
            metrics.append({
                "id": "drop_rate", "system": lsys, "value": None, "detail": "폐기율 없음",
                "conditions": cond, "limits": "요약에 폐기 수가 없다. 연결률 100%의 의미가 약하다",
            })
    else:
        metrics.append({"id": "linkage_rate", "system": "neumann", "value": None,
                        "conditions": run, "limits": f"데모 {len(unmeasured)}건 모두 연결 검사를 하지 않았다"})

    # 화면 카드 수는 generator별로 나눈다: LLM(astra) 카드는 Neumann 행, 규칙 카드는 비상 규칙 행(PM 결정: LLM 카드와 분리).
    per_gen: dict[str, dict[str, int]] = {"astra": {}, "rule": {}}
    for n, e in demo.items():
        g = {str(k): int(v) for k, v in (e.get("generators") or {}).items() if v}
        bad = set(g) - {"astra", "rule"}
        if bad:
            raise InputError(f"plans[{n}].generators에 LLM·규칙이 아닌 generator {sorted(bad)}가 있다(mock 등은 성능이 아니다)")
        if sum(g.values()) != shown[n]:
            raise InputError(f"plans[{n}]: 화면 카드 {shown[n]}장인데 generator 기록 합이 {sum(g.values())}다(나눌 수 없다)")
        for k in per_gen:
            per_gen[k][n] = g.get(k, 0)
    metrics.append({
        "id": "e2e_cards", "system": "neumann", "value": sum(per_gen["astra"].values()), "n": len(demo),
        "detail": " · ".join(f"{n} {c}" for n, c in per_gen["astra"].items()),
        "conditions": f"{run}. 화면(/premortem/view)에 나온 LLM(astra) 위험카드 수, 데모 계획서 합. 화면 카드 generator {gens or '없음'}",
        "limits": "개수일 뿐 품질 지표가 아니다. 연결 검사 카드 수(card_pass_rate의 n)와 다른 실행이라 다를 수 있다. "
                  "규칙 카드는 세지 않는다(따로 적는다)",
        **({"model": rec_view} if rec_view else {}),
    })
    if sum(per_gen["rule"].values()):
        metrics.append({
            "id": "e2e_cards", "system": "neumann_rule", "value": sum(per_gen["rule"].values()), "n": len(demo),
            "detail": " · ".join(f"{n} {c}" for n, c in per_gen["rule"].items()),
            "conditions": f"{run}. 화면에 나온 규칙(비LLM) 위험카드 수, 데모 계획서 합",
            "limits": "규칙 카드(경고 단계 '분야 수준 참고 · 계획서와 대조 안 됨' 또는 비상 경로)다. LLM 카드 수와 분리해 적는다"
                      "(PM 결정 2026-09-30)",
        })

    passed = [
        n for n, e in demo.items()
        if e.get("failures") == [] and e.get("result_status") == "ok" and (n in measured)
        and measured[n]["links"][0] == measured[n]["links"][1] and measured[n]["verdict"] == "pass"
    ]
    neg = plans.get(NEGATIVE_PLAN)
    if isinstance(neg, dict):
        neg_txt = (
            f"범위 밖 입력 {NEGATIVE_PLAN}: 카드 {neg.get('n_cards')}장, 실패 {len(neg.get('failures') or [])}건"
            + (", 사유 표시" if neg.get("zero_card_reasons") or neg.get("empty_reason") else "")
        )
    else:
        neg_txt = "범위 밖 입력 검사 없음"
    # 시연 통과 조건에 근거 연결 검사가 들어 있으므로, 그 실행의 generator가 기록되지 않았으면 P2와 같이
    # 참고 행으로 둔다(PM 결정 2026-09-30). 약속 표는 system "all"만 보므로 P6는 측정 전으로 남는다.
    demo_ref = lsys == UNRECORDED_SYSTEM
    metrics.append({
        "id": "demo_e2e", "system": UNRECORDED_SYSTEM if demo_ref else "all", "value": len(passed), "n": len(demo),
        "detail": f"{len(passed)}/{len(demo)}" + ("; generator 미기록 실행" if demo_ref else ""),
        "conditions": (
            f"{run}. 데모 계획서가 실서버에서 붙여넣기→리포트 화면·파이프라인 연결·카드 인용·원문 링크·생성 방식 표시·"
            f"브라우저 오류 0·근거 연결 1.0 검사를 실패 0으로 통과한 수. {neg_txt}"
        ),
        "limits": (
            "generator 미기록 실행: 통과 조건인 근거 연결 검사 실행의 카드 generator가 요약에 없어 약속 P6 판정에 "
            "쓰지 않는 참고값이다(PM 결정 2026-09-30: generator·model을 기록한 라이브 결과로 채운다). "
            if demo_ref else ""
        ) + "리포트 화면까지. 결과 패키지(ZIP) 내보내기는 재지 않았다. 1회 실행",
        **({"model": rec_demo} if rec_demo else {}),
    })

    if product_model:
        for mid, system in PRODUCT_UNMEASURED:
            metrics.append({
                "id": mid, "system": f"Neumann 제품 기본 모델({product_model})", "value": None,
                "conditions": f"측정 전. 이 모델로 다시 재지 않았다. 이 카드의 Neumann 수치는 평가 모델 {model}로 잰 것",
                "limits": f"재측정 안 한 사유: 비용({DECISION_REF})",
            })

    return {
        "schema": SCHEMA,
        "source": f"scripts/metrics_from_e2e.py ← {summary_name}"
        + (f" (sha256 {summary_sha256})" if summary_sha256 else "") + f", 평가 모델 {model}",
        "model": model,
        "product_model": product_model,
        "metrics": metrics,
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python scripts/metrics_from_e2e.py", description="라이브 E2E 요약 → neumann.metrics/1")
    ap.add_argument("--summary", type=Path, required=True, help="E5-L0e2e_live_summary.json")
    ap.add_argument("--model", required=True, help="그 실행의 LLM 모델 이름(요약에 없음). 예: gpt-6-astra")
    ap.add_argument("--product-model", default=None, help="제품 기본 모델. 주면 재지 않은 헤드라인 지표를 '측정 전' 행으로 적는다")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        raw = args.summary.read_bytes()
        obj = json.loads(raw.decode("utf-8"))
        if not isinstance(obj, dict):
            raise InputError(f"{args.summary}: 최상위가 객체가 아니다")
        out = convert(obj, model=args.model, product_model=args.product_model,
                      summary_name=args.summary.name, summary_sha256=hashlib.sha256(raw).hexdigest())
    except (InputError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # 줄바꿈을 LF로 고정한다(.gitattributes eol=lf). CRLF로 쓰면 리포트 카드에 적힌 sha256이 체크아웃 파일과 달라진다.
    args.out.write_bytes((json.dumps(out, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    for m in out["metrics"]:
        print(f"{m['id']:<15} {m['system']:<40} {m['value']!s:<8} {m.get('detail', '')}")
    print(f"지표 {len(out['metrics'])}개 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
