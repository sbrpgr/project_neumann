"""위험 유형 R0~R9 요약(지시문용)과 심각도 기본값.

출처: 기획 키트 `부록/설계/03_risk_taxonomy.md` §2.3·§3·§6-1을 지시문 크기로 줄여 새로 쓴 것이다.
"""

from __future__ import annotations

from neumann.models import RiskCode

# 택소노미 §3의 심각도 기본값(S1~S5)과 0~1 환산값.
SEVERITY_LEVEL: dict[RiskCode, str] = {
    RiskCode.R0: "S1",
    RiskCode.R1: "S4",
    RiskCode.R2: "S4",
    RiskCode.R3: "S5",
    RiskCode.R4: "S3",
    RiskCode.R5: "S3",
    RiskCode.R6: "S4",
    RiskCode.R7: "S4",
    RiskCode.R8: "S4",
    RiskCode.R9: "S5",
}
SEVERITY_UNIT: dict[str, float] = {"S5": 1.0, "S4": 0.8, "S3": 0.6, "S2": 0.4, "S1": 0.2}

# 카드로 만들 수 있는 유형. R0(서술·표현)은 비위험 싱크, R9는 심사평 본문에서 추론 금지(택소노미 B9).
CARD_CODES: tuple[RiskCode, ...] = tuple(c for c in RiskCode if c not in (RiskCode.R0, RiskCode.R9))

TAXONOMY_BRIEF = """\
Risk codes (Neumann taxonomy v1, Tier-1):
- R0 presentation_clarity: readability, organisation, notation, typos, figure labels, "hard to follow". Not a research-design risk.
- R1 claim_evidence: the presented experiments/proofs do not support the stated conclusion within its own scope; overclaiming; unjustified assumptions; flawed proof.
- R2 evaluation_protocol: the procedure that produces the numbers is inadequate: missing/weak/outdated baselines, missing ablations, single seed / no error bars / no variance or significance, unfair tuning budget, inappropriate metrics, requests for more experiments on the same task.
- R3 data_leakage: information leaks between training and evaluation (random split with near-duplicates, same entity in train and test, preprocessing/feature selection on the full data, test contamination, split by molecule vs scaffold, subject overlap).
- R4 data_quality: the data itself: provenance, collection protocol, exclusion criteria, missing values, label noise, heterogeneous measurement conditions, small or unrepresentative samples, class imbalance.
- R5 reproducibility: missing code, data, hyperparameters, implementation or training details, compute/environment information needed for a third party to reproduce.
- R6 novelty_positioning: limited novelty, overlap with prior work, missing related work or comparisons that are about citing/discussing literature.
- R7 generalization_scope: claims beyond the tested conditions; need for other datasets/populations/chemistries/sites; out-of-distribution or external validation; limitations not stated.
- R8 domain_validation: predictions not validated by domain experiments (synthesis, measurement, clinical study) or physical/chemical/biological plausibility constraints; lack of expert/clinical validation.
- R9 integrity_post_pub: documented retraction/correction records ONLY. Never assign R9 from review text.

Boundary rules:
- Needs more experiments -> R2; only needs citing/discussing literature -> R6.
- Reported numbers contaminated, split must be redone -> R3; numbers honest but hard to interpret -> R2.
- Info moving between train and test -> R3; data defective even with a perfect split -> R4.
- Same conditions, evidence falls short -> R1; asks for other conditions/datasets -> R7.
- Lab/physical/clinical validation -> R8; computational test on other data -> R7.
- Missing info needed to re-implement -> R5; wording/readability -> R0.
"""
