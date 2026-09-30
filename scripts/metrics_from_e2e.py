"""라이브 E2E 요약 → 일반 지표 JSON(neumann.metrics/1) 변환 (E5-L3b).

    python scripts/metrics_from_e2e.py --summary docs/reports/E5-L0e2e_live_summary.json \\
        --model gpt-6-astra --product-model gpt-6.1-sol --out docs/reports/E5-L3b_metrics_e2e.json

`tests/e2e/test_live.py`가 남긴 요약(`E5-L0e2e_live_summary.json`)을 `python -m eval.report_card`가 읽는
일반 지표 형식으로 옮긴다. 파일만 읽는다(서버·OpenAI를 부르지 않는다).

만드는 지표(값은 요약의 개수로만 계산한다. 추정·보정 없음):
- `linkage_rate`/neumann   근거 연결률 = 데모 계획서들의 링크 합 ok / 합 total (계획서별 개수는 detail)
- `card_pass_rate`/neumann 모든 근거가 연결된 카드 / 검사 카드
- `drop_rate`/neumann      폐기율 = 버린 지적 / 전체 지적 (연결 요약 문자열의 `폐기율 a/b`에서 읽는다)
- `e2e_cards`/neumann      화면에 나온 위험카드 수(데모 계획서 합)
- `demo_e2e`/all           실패 0으로 끝까지 통과한 데모 계획서 수(신청서 약속 P6)
- `--product-model`을 주면, 그 모델로는 재지 않은 헤드라인 지표를 값 null(= 측정 전) 행으로 적는다.

정직 규칙:
- 샘플 모드 요약(mode != live)이나 파이프라인 미연결 요약은 거부한다(성능 수치가 아니다).
- 요약에 적힌 비율이 개수와 다르거나, 요약 문자열의 개수와 필드의 개수가 다르면 멈춘다(어느 쪽을 믿을지 정할 수 없다).
- 비율은 소수 4자리로 적되, 1.0이 아닌 값을 1.0으로, 0이 아닌 값을 0으로 반올림하지 않는다. 정확한 개수는 detail에 둔다.
- 요약에는 모델 이름이 없다. 모델은 `--model`로 받아 조건 칸에 적는다(기본값 없음).
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
    return {"links": links, "cards": cards, "drop": drop, "verdict": lk.get("verdict")}


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
        f"1회 실행, 평가 모델 {model}"
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
            measured[name] = got

    metrics: list[dict[str, Any]] = []
    shown = {n: int(e.get("n_cards") or 0) for n, e in demo.items()}
    gens: dict[str, int] = {}
    for e in demo.values():
        for g, c in (e.get("generators") or {}).items():
            gens[str(g)] = gens.get(str(g), 0) + int(c)
    degraded = sum(len(e.get("stages_not_ok") or []) for e in demo.values())
    gen_note = (
        f"연결 검사는 화면 실행과 별도인 같은 계획서의 /premortem 재실행 결과다. 그 실행의 카드 generator는 요약에 "
        f"기록되지 않았다(화면 실행 카드 generator {gens or '없음'}, 강등 단계 {degraded}개)"
    )
    miss_note = f". 연결 검사를 하지 않은 데모 {len(unmeasured)}건({', '.join(unmeasured)})은 합계에서 빠졌다" if unmeasured else ""

    if measured:
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
            "id": "linkage_rate", "system": "neumann", "value": ratio(l_ok, l_tot) if l_tot else None,
            "n": l_tot, "detail": f"{l_ok}/{l_tot}; {per('links')}; 검사 실행 카드 generator 미기록", "conditions": cond,
            "limits": lim + ". 폐기율과 같이 읽는다(04_평가_명세 §2.2)",
        })
        metrics.append({
            "id": "card_pass_rate", "system": "neumann", "value": ratio(c_ok, c_tot) if c_tot else None,
            "n": c_tot, "detail": f"{c_ok}/{c_tot}; {per('cards')}", "conditions": cond, "limits": lim,
        })
        with_drop = {n: v["drop"] for n, v in measured.items() if v["drop"]}
        no_drop = [n for n, v in measured.items() if not v["drop"]]
        if with_drop:
            d_ok = sum(d[0] for d in with_drop.values())
            d_tot = sum(d[1] for d in with_drop.values())
            srcs = sorted({d[2] for d in with_drop.values()})
            metrics.append({
                "id": "drop_rate", "system": "neumann", "value": ratio(d_ok, d_tot) if d_tot else None, "n": d_tot,
                "detail": f"{d_ok}/{d_tot}; " + " · ".join(f"{n} {d[0]}/{d[1]}" for n, d in with_drop.items()),
                "conditions": f"{cond}. 폐기 출처 {', '.join(srcs)}(검증 단계에서 버린 지적)",
                "limits": "전수 계산" + (f". 폐기율이 없는 {', '.join(no_drop)}은 합계에서 빠졌다" if no_drop else "")
                + miss_note,
            })
        else:
            metrics.append({
                "id": "drop_rate", "system": "neumann", "value": None, "detail": "폐기율 없음",
                "conditions": cond, "limits": "요약에 폐기 수가 없다. 연결률 100%의 의미가 약하다",
            })
    else:
        metrics.append({"id": "linkage_rate", "system": "neumann", "value": None,
                        "conditions": run, "limits": f"데모 {len(unmeasured)}건 모두 연결 검사를 하지 않았다"})

    metrics.append({
        "id": "e2e_cards", "system": "neumann", "value": sum(shown.values()), "n": len(demo),
        "detail": " · ".join(f"{n} {c}" for n, c in shown.items()),
        "conditions": f"{run}. 화면(/premortem/view)에 나온 위험카드 수, 데모 계획서 합. 화면 카드 generator {gens or '없음'}",
        "limits": "개수일 뿐 품질 지표가 아니다. 연결 검사 카드 수(card_pass_rate의 n)와 다른 실행이라 다를 수 있다",
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
    metrics.append({
        "id": "demo_e2e", "system": "all", "value": len(passed), "n": len(demo),
        "detail": f"{len(passed)}/{len(demo)}",
        "conditions": (
            f"{run}. 데모 계획서가 실서버에서 붙여넣기→리포트 화면·파이프라인 연결·카드 인용·원문 링크·생성 방식 표시·"
            f"브라우저 오류 0·근거 연결 1.0 검사를 실패 0으로 통과한 수. {neg_txt}"
        ),
        "limits": "리포트 화면까지. 결과 패키지(ZIP) 내보내기는 재지 않았다. 1회 실행",
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
