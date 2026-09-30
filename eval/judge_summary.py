"""판정 결과 → 발표용 표(Markdown). `judge_run aggregate`가 결과 JSON과 함께 `<판정 폴더>_results.md`로 쓴다.

표에 들어가는 것(모두 결과 JSON에서 그대로 옮긴다. 여기서 새로 계산하는 값은 없다):
- 시스템별(진짜 조건): 논문 수, 낸 위험 수, 다수결 A·B·C 개수와 비율(낸 위험 기준), 빈 자리, precision@3·hit@3(95% 구간),
  오탐률, 근거율, 실행 상태(ok·degraded·error)와 위험 0개 논문 수.
- Neumann − 일반 LLM: 같은 논문 짝 차이와 구간, hit@3 불일치 쌍, status가 ok가 아닌 논문을 뺀 민감도.
- 다수결 구성(3명 일치·2:1·모두 다름)과 판정자 쌍 일치율. 대표 판정이 있으면 같은 표와 사람 대 AI 일치.
- 한계 문구: 셔플 대조 없음(특이성 측정 못 함), 작은 n. mock·합성 입력이나 가짜 판정이면 맨 위에 [예행]이라고 적는다.
"""

from __future__ import annotations

from typing import Any

NAMES = {"neumann": "Neumann", "baseline_llm": "일반 LLM(기준선)"}
ORDER = ("neumann", "baseline_llm")
REHEARSAL_MARKS = ("mock", "synthetic", "rehearsal")


def _num(v: float | None, digits: int = 3, signed: bool = False) -> str:
    if v is None:
        return "—"
    return f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"


def _metric(m: dict[str, Any] | None, signed: bool = False) -> str:
    if not m or m.get("value") is None:
        return "—"
    ci = m.get("ci95")
    s = _num(m["value"], signed=signed)
    return f"{s} [{_num(ci[0], signed=signed)}, {_num(ci[1], signed=signed)}]" if ci else s


def _share(rg: dict[str, Any], k: str) -> str:
    n = rg.get("n") or 0
    c = rg.get("counts", {}).get(k, 0)
    return f"{c}/{n} ({c / n:.0%})" if n else "—"


def _status(r: dict[str, Any]) -> str:
    sc = r.get("status_counts") or {}
    parts = [f"{k} {v}" for k, v in sorted(sc.items())]
    if r.get("failed_runs"):
        parts.append(f"위험 0개 {r['failed_runs']}편")
    return " · ".join(parts) or "—"


def _systems(metrics: dict[str, Any]) -> list[str]:
    have = list(metrics.get("systems", {}))
    return [s for s in ORDER if s in have] + sorted(s for s in have if s not in ORDER)


def system_table(metrics: dict[str, Any]) -> list[str]:
    lines = [
        "| 시스템 | 논문 | 낸 위험 | A 적중 | B 타당 | C 오탐 | 빈 자리 | precision@3 [95% 구간] | hit@3 [95% 구간] | 오탐률 | 근거율 | 실행 상태 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in _systems(metrics):
        r = metrics["systems"][s].get("real") or {}
        if not r.get("measured"):
            lines.append(f"| {NAMES.get(s, s)} | 0 | — | — | — | — | — | — | — | — | — | 판정된 논문 없음 |")
            continue
        rg = r.get("risk_grades") or {}
        lines.append(
            f"| {NAMES.get(s, s)} | {r['n']} | {r.get('n_risks', rg.get('n', '—'))} | {_share(rg, 'A')} | {_share(rg, 'B')} | "
            f"{_share(rg, 'C')} | {r.get('missing_slots', '—')} | {_metric(r.get('precision_at_3'))} | {_metric(r.get('hit_at_3'))} | "
            f"{_num((r.get('fp_rate') or {}).get('value'))} | {_num((r.get('evidence_rate') or {}).get('value'))} | {_status(r)} |"
        )
    return lines


def comparison_table(metrics: dict[str, Any]) -> list[str]:
    comp = metrics.get("comparison") or {}
    key = "_diff_neumann_minus_baseline_llm"
    if not any(k.endswith(key) for k in comp):
        return ["두 시스템이 모두 판정된 논문이 없어 비교하지 않았다."]
    lines = ["| 지표 | Neumann − 일반 LLM [95% 구간] | 짝 n |", "|---|---|---|"]
    for name, label in (("precision_at_3", "precision@3"), ("hit_at_3", "hit@3"), ("fp_rate", "오탐률")):
        m = comp.get(name + key)
        if m:
            lines.append(f"| {label} | {_metric(m, signed=True)} | {m.get('n')} |")
    d = comp.get("hit_at_3_discordant")
    if d:
        lines.append(f"| hit@3 불일치 쌍 | Neumann만 적중 {d['neumann_only']}편 · 일반 LLM만 적중 {d['baseline_only']}편 | {d['n']} |")
    sens = comp.get("sensitivity_status_ok_only")
    if sens:
        lines.append(f"| 민감도: 두 시스템 모두 status ok인 논문만 precision@3 | {_metric(sens.get('precision_at_3_diff'), signed=True)} "
                     f"| {sens['n']} (뺀 논문 {len(sens['excluded_work_ids'])}편) |")
    return lines


def vote_table(metrics: dict[str, Any]) -> list[str]:
    lines = ["| 시스템 | 3명 일치 | 2:1 | 모두 다름(→B) |", "|---|---|---|---|"]
    for s in _systems(metrics):
        vp = (metrics["systems"][s].get("real") or {}).get("vote_patterns") or {}
        lines.append(f"| {NAMES.get(s, s)} | {vp.get('unanimous', 0)} | {vp.get('split_2_1', 0)} | {vp.get('all_differ', 0)} |")
    return lines


def _is_rehearsal(out: dict[str, Any]) -> bool:
    vals: list[str] = [str(x) for x in out.get("judge_models") or []]
    for s in (out.get("metrics") or {}).get("systems", {}).values():
        r = s.get("real") or {}
        vals += [str(x) for x in (r.get("generator_counts") or {})] + [str(x) for x in r.get("models") or []]
    return any(m in v.lower() for v in vals for m in REHEARSAL_MARKS)


def render_results_md(out: dict[str, Any]) -> str:
    m = out["metrics"]
    run = out.get("run") or {}
    val = out.get("validation") or {}
    controls = m.get("controls") or {}
    n_works = len(run.get("work_ids") or m.get("work_ids_filter") or [])
    lines = ["# 백테스트 판정 결과", ""]
    if _is_rehearsal(out):
        lines += ["> **[예행]** mock·합성 입력 또는 가짜 판정으로 만든 값이다. 실제 결과가 아니다.", ""]
    spec = run.get("work_ids_spec")
    lines.append(f"- 논문 {n_works}편" + (f"(선택 `{spec}`, 사전 등록 표본 순서)" if spec else "") +
                 f" · 조건 {', '.join(controls.get('conditions') or run.get('conditions') or [])} · "
                 "판정: 독립 판정자 3명 블라인드, 위험별 다수결(3명 모두 다르면 B)")
    jm = out.get("judge_models")
    if jm:
        lines.append(f"- 판정 모델: {', '.join(map(str, jm))}")
    lines.append(f"- 판정 답 {val.get('valid', '—')}/{val.get('expected', '—')} 통과" +
                 ("" if val.get("complete") else f" · **미완**: 누락 {len(val.get('missing') or [])} · 집계 못 한 봉투 "
                  f"{len(out.get('incomplete_envelopes') or [])}(그 논문은 두 시스템 모두 지표에서 빠진다)"))
    if not controls.get("shuffle"):
        lines.append(f"- **{controls.get('note') or '셔플 대조 없음'}**")
    lines.append(f"- n이 작아 통계적 결론을 내리지 않는다. 구간은 논문 재표집 부트스트랩 {m.get('n_boot')}회 95% percentile이다.")
    if run.get("empty_works"):
        lines.append(f"- 모든 시스템이 위험 0개라 봉투 없이 적중 0으로 센 논문 {len(run['empty_works'])}편")
    if run.get("missing_risksets"):
        lines.append(f"- 위험 묶음이 없는 칸(실행 누락) {len(run['missing_risksets'])}개: {', '.join(run['missing_risksets'])}")
    models, astra = [], False
    for s in _systems(m):
        r = m["systems"][s].get("real") or {}
        if r.get("measured"):
            gens = ", ".join(f"{k} {v}" for k, v in sorted((r.get("generator_counts") or {}).items()))
            mods = ", ".join("없음" if x in ("None", "") else x for x in r.get("models") or [])
            astra = astra or "astra" in gens
            models.append(f"{NAMES.get(s, s)}: 생성 {gens} · 모델 {mods}")
    if models:
        lines.append("- " + " / ".join(models) + (" (generator `astra`는 계약 이름이고 모델이 아니다)" if astra else ""))
    lines += ["", "## 시스템별 (진짜 조건, AI 다수결)", "", *system_table(m), "",
              "A·B·C 비율은 낸 위험 기준, precision@3·오탐률은 논문마다 3칸 기준(빈 자리는 A·C가 아니다).", "",
              "## Neumann − 일반 LLM (같은 논문 짝)", "", *comparison_table(m), "",
              "## 다수결 구성 (위험 수)", "", *vote_table(m), ""]
    ja = out.get("judge_agreement") or {}
    if ja:
        pairs = " · ".join(f"{k} {_num(v)}" for k, v in ja.items() if "-" in k)
        lines += [f"판정자 쌍 일치율: {pairs} · 3명 모두 일치 {_num(ja.get('all_three_agree'))} (위험 {ja.get('n_risks')}개)", ""]
    if out.get("human_metrics"):
        ha = out.get("human_agreement") or {}
        lines += ["## 대표 블라인드 판정 (진짜 조건)", "", *system_table(out["human_metrics"]), "",
                  *comparison_table(out["human_metrics"]), "",
                  f"사람 대 AI 다수결: 위험 {ha.get('n')}개 · 3등급 일치 {_num(ha.get('exact_agreement_3class'))} · "
                  f"κ {_num(ha.get('kappa_3class'))} · A 여부 일치 {_num(ha.get('binary_A_agreement'))} · "
                  f"κ(A) {_num(ha.get('kappa_binary_A'))} (— = 분산이 없어 정의 안 됨)", ""]
        if out.get("human_incomplete_envelopes"):
            lines += [f"대표가 다 채우지 않은 봉투 {len(out['human_incomplete_envelopes'])}개는 사람 지표에서 뺐다.", ""]
    lines += ["## 정의", "",
              "- A 적중: 실제 심사평에 같은 사안(같은 대상·같은 원인)의 지적이 있다. B 타당: 심사평엔 없지만 계획서에 맞다. C 오탐.",
              "- precision@3 = 논문마다 A 개수/3의 평균. hit@3 = A가 하나라도 있는 논문 비율. 오탐률 = 논문마다 C 개수/3의 평균.",
              "- 근거율 = 원문 대조를 통과한 근거가 붙은 위험/낸 위험. 일반 LLM은 원문 근거가 없어 0이다.",
              "- 위험 0개(시스템 실패)·degraded(규칙 비상 경로) 논문도 빼지 않는다(적중 0·그대로 판정). 실행 상태 열에 적는다.",
              ""]
    return "\n".join(lines)


__all__ = ["render_results_md", "system_table", "comparison_table", "vote_table"]
