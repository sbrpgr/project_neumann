"""Offline sample curation measurements. No providers, pipelines or network imports."""

from __future__ import annotations

from typing import Any

OFFLINE_LABEL = "Claude/Codex 오프라인"


def generation_of(result: dict[str, Any], *, source: str | None = None) -> str:
    """Use recorded provenance; never infer a live model from the contract name astra."""
    manifest = result.get("manifest", {})
    parts = [*result.get("risk_cards", []), *result.get("checklist", []), result.get("expected_review", {})]
    fit = result.get("plan_checks", {}).get("fitness", {})
    parts.append(fit)
    stages = result.get("stages", [])
    if (source == "fixture" or manifest.get("source") == "fixture"
            or manifest.get("llm_provider") == "mock"
            or any(p.get("generator") == "mock" for p in parts)
            or any("fixture" in str(s.get("impl", "")).lower() for s in stages)
            or any("[FAKE]" in n for n in result.get("notices", []))):
        return "mock"
    if manifest.get("generation") == OFFLINE_LABEL:
        return OFFLINE_LABEL
    provider, model = manifest.get("llm_provider"), manifest.get("llm_model")
    if provider == "openai" and isinstance(model, str) and model:
        return "라이브 " + model
    if provider in ("off", "rule") or any(p.get("generator") == "rule" for p in parts):
        return "rule"
    return "unknown"


def _linked(rows: list[dict[str, Any]], known: set[str], key: str) -> bool:
    return bool(rows) and all(isinstance(r.get(key), list) and bool(r[key]) and set(r[key]) <= known for r in rows)


def score_result(result: dict[str, Any], sample: dict[str, Any], field: dict[str, Any]) -> dict[str, Any]:
    """Score measurable completeness, not scientific accuracy or product performance."""
    cards = result.get("risk_cards", [])
    known = {e["excerpt_id"] for e in result.get("evidence", [])}
    card_evidence = {c["card_id"]: set(c.get("evidence", [])) for c in cards}
    review = result.get("expected_review", {})
    sentences = [s for section in ("strength", "weakness", "request") for s in review.get(section, [])]
    checklist = result.get("checklist", [])
    verification = result.get("verification", {})
    fitness = result.get("plan_checks", {}).get("fitness", {})
    input_quality = result.get("plan_checks", {}).get("input_quality", {})
    gate = (sample["expect_gate"] == "ok" and fitness.get("analyze") is True
            and fitness.get("verdict") not in ("unfit", "reject")
            and input_quality.get("analyze") is not False)
    generation = generation_of(result)
    good_stages = (result.get("status") == "ok" and bool(result.get("stages"))
                   and all(s.get("status") == "ok" for s in result["stages"]))
    no_rules = all(p.get("generator") != "rule" for p in [*cards, *checklist, review, fitness])
    links = _linked(cards, known, "evidence") and verification.get("linkage_rate") == 1
    review_links = _linked(sentences, known, "c") and all(
        bool(s.get("cards")) and set(s["cards"]) <= card_evidence.keys()
        and set(s["c"]) <= set().union(*(card_evidence[c] for c in s["cards"])) for s in sentences)
    checklist_links = bool(checklist) and all(
        isinstance(row.get("evidence"), list) and bool(row["evidence"])
        and row.get("card_id") in card_evidence
        and set(row["evidence"]) <= card_evidence[row["card_id"]] for row in checklist)
    # Missing verification is not evidence of zero dropped items.
    checklist_links = checklist_links and verification.get("checklist_evidence", {}).get("dropped") == 0
    domain_text = " ".join(str(result.get(k) or "") for k in ("domain",)) + " " + str(fitness.get("field") or "")
    domain_match = (result.get("domain") == sample["domain"] or
                    any(w.lower() in domain_text.lower() for w in field.get("keywords", [])))
    revisions = result.get("plan_checks", {}).get("revision_advice", {}).get("items", [])
    revision_links = _linked(revisions, known, "evidence") if revisions else None
    checks = {"gate": gate, "no_degradation": good_stages and no_rules,
              "card_count": 4 <= len(cards) <= 8, "evidence_linkage": links,
              "review_evidence": review_links, "checklist_evidence": checklist_links,
              "domain": domain_match}
    weights = {"gate": 20, "no_degradation": 15, "card_count": 15, "evidence_linkage": 15,
               "review_evidence": 10, "checklist_evidence": 10, "domain": 10}
    if revisions:
        checks["revision_evidence"] = revision_links
        weights["revision_evidence"] = 5
    breakdown = {k: weights[k] if ok else 0 for k, ok in checks.items()}
    score = round(sum(breakdown.values()) / sum(weights.values()) * 100, 2)
    eligible = all(checks.values()) and (generation.startswith("라이브 ") or generation == OFFLINE_LABEL)
    reasons = [k for k, ok in checks.items() if not ok]
    if generation in ("mock", "rule", "unknown"):
        reasons.append("generation=" + generation + ": 선별 불가")
    matches = []
    for weakness in sample["intended_weaknesses"]:
        matched = [c["card_id"] for c in cards if c.get("risk_code") == weakness["risk_code"]
                   and any(w.lower() in (c.get("title", "") + " " + c.get("why_applies", {}).get("text", "")).lower()
                           for w in weakness.get("keywords", []))]
        matches.append({"risk_code": weakness["risk_code"], "text": weakness["text"], "card_ids": matched})
    return {"score": score, "breakdown": breakdown, "checks": checks, "eligible": eligible,
            "generation": generation, "reason": "; ".join(reasons) or "측정 항목 통과 · 사람 확인 필요",
            "weakness_matches": matches,
            "cards": [{"id": c["card_id"], "title": c["title"], "evidence_count": len(c["evidence"])} for c in cards],
            "review_first_line": sentences[0].get("t", "") if review_links else ""}
