"""공용 fixture 생성기. 모든 내용은 분명히 가짜다([FAKE], example.org).

다시 만들 때:  python tests/fixtures/make_fixtures.py
Excerpt는 손으로 오프셋을 적지 않고, 원문에서 문장을 찾아 `Excerpt.from_source()`로 잘라 만든다.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from neumann.models import (  # noqa: E402
    Decision,
    Excerpt,
    Generator,
    PlanDocument,
    PremortemResult,
    Provenance,
    ReviewEvent,
    RiskCard,
    RiskScore,
    RiskTag,
    SimilarWork,
    StageStatus,
    WhyApplies,
    Work,
    sha256_text,
)

ACCESSED = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
BASE = "https://example.org/fake-venue"


def prov(url: str, text: str) -> Provenance:
    return Provenance(
        source="fixture",
        source_url=url,
        accessed_at=ACCESSED,
        content_sha256=sha256_text(text),
        license="fixture-fake-data",
        api_version="fixture-v1",
    )


WORKS = [
    ("gnn-001", "[FAKE] EquiMol: equivariant message passing for molecular property prediction",
     ["molecular property prediction", "graph neural network"]),
    ("gnn-002", "[FAKE] Scaffold-aware contrastive pretraining for small-molecule GNNs",
     ["molecular property prediction", "self-supervised learning"]),
    ("gnn-003", "[FAKE] Uncertainty-calibrated GNN ensembles for aqueous solubility prediction",
     ["molecular property prediction", "uncertainty"]),
    ("seg-001", "[FAKE] UNet-Lite: lightweight 3D segmentation of liver tumors in CT",
     ["medical image segmentation", "computed tomography"]),
    ("seg-002", "[FAKE] Cross-site domain adaptation for brain MRI lesion segmentation",
     ["medical image segmentation", "domain adaptation"]),
    ("seg-003", "[FAKE] Semi-supervised polyp segmentation with consistency regularization",
     ["medical image segmentation", "semi-supervised learning"]),
]

REVIEWS = {
    "gnn-001": [
        "The paper reports a random 80/10/10 split of the molecules. Random splits are known to leak "
        "near-duplicate scaffolds between train and test, so the reported MAE is likely optimistic. "
        "Please add a scaffold split or a time split. The comparison also omits recent equivariant "
        "baselines that the related work section itself lists.",
        "All numbers come from a single training run with one random seed. Without error bars across "
        "seeds it is impossible to tell whether the 3% improvement is real. The ablation on "
        "message-passing depth is missing. Code is promised but not provided with the submission.",
    ],
    "gnn-002": [
        "The pretraining corpus overlaps with the downstream test molecules. The authors should "
        "deduplicate by canonical SMILES and InChIKey before pretraining. Otherwise the downstream gains "
        "may reflect memorization rather than transfer.",
        "The method is only evaluated on two small benchmark tasks. It is unclear whether the gains "
        "generalize to larger or noisier assay data. The baselines are not tuned with the same budget as "
        "the proposed model, which makes the comparison unfair. I recommend a fair hyperparameter search "
        "for all methods.",
    ],
    "gnn-003": [
        "The claimed calibration improvement is not supported by the reported experiments. Expected "
        "calibration error is shown for one dataset only, and no reliability diagrams are given. The claim "
        "in the abstract should be toned down or backed by more evidence.",
        "Solubility labels are merged from several public sources with different measurement protocols. "
        "Duplicate compounds with conflicting labels are kept, which adds label noise. The paper should "
        "describe how conflicts were resolved and report results on a cleaned subset. A single seed is "
        "used for every ensemble size.",
    ],
    "seg-001": [
        "Slices from the same patient appear in both the training and the test sets. This patient-level "
        "leakage inflates the Dice score substantially. Please re-split the data at the patient level and "
        "report the new results.",
        "The model is evaluated on a single public dataset from one hospital. No external validation on a "
        "different scanner or site is provided. Claims about clinical readiness are therefore premature. "
        "The comparison with nnU-Net, the standard baseline, is missing.",
    ],
    "seg-002": [
        "The target-site images are used to select the checkpoint. This means the test distribution "
        "influences model selection, which is a form of leakage. A separate validation split from the "
        "target site is needed. The reported gains may shrink once this is fixed.",
        "Results are reported from one run with a fixed seed. Given the small number of target-site scans, "
        "variance across seeds could be large. Please report mean and standard deviation over at least "
        "three seeds. Code and preprocessing scripts are not released, which limits reproducibility.",
    ],
    "seg-003": [
        "The novelty over existing consistency-regularization methods is limited. The loss is essentially "
        "the same as in prior mean-teacher work with a different augmentation. The paper should position "
        "itself more clearly against these methods.",
        "Only Dice is reported, without boundary metrics such as HD95. The test set is small, and "
        "confidence intervals are not given. Several frames come from the same video, so frame-level "
        "random splitting may leak near-identical images across splits. Please split by video.",
    ],
}

DECISIONS = {
    "gnn-001": ("reject", "Reject",
                "The reviewers agree that the random split likely overstates performance and that the "
                "single-seed results are not convincing."),
    "gnn-002": ("accept_poster", "FakeConf 2099 poster", None),
    "gnn-003": ("major_revision", "Major Revision", None),
    "seg-001": ("reject", "Reject",
                "Patient-level leakage between training and test sets undermines the main result."),
    "seg-002": ("minor_revision", "Minor Revision", None),
    "seg-003": ("accept", "Accept", None),
}

# (source_kind, source_id, 원문에서 찾을 문장, 위험 코드)
EXCERPT_SPECS = [
    ("review", "rev-gnn-001-a", "The paper reports a random 80/10/10 split of the molecules.", "R3"),  # 오프셋 0
    ("review", "rev-gnn-001-a", "Random splits are known to leak near-duplicate scaffolds between train and "
     "test, so the reported MAE is likely optimistic.", "R3"),
    ("review", "rev-gnn-002-a", "The pretraining corpus overlaps with the downstream test molecules.", "R3"),
    ("decision", "dec-gnn-001", "the random split likely overstates performance", "R3"),
    ("review", "rev-seg-001-a", "Slices from the same patient appear in both the training and the test sets.", "R3"),
    ("review", "rev-seg-002-a", "The target-site images are used to select the checkpoint.", "R3"),
    ("review", "rev-seg-003-b", "Several frames come from the same video, so frame-level random splitting may "
     "leak near-identical images across splits.", "R3"),
    ("review", "rev-gnn-001-b", "All numbers come from a single training run with one random seed.", "R2"),
    ("review", "rev-gnn-001-b", "Without error bars across seeds it is impossible to tell whether the 3% "
     "improvement is real.", "R2"),
    ("review", "rev-gnn-003-b", "A single seed is used for every ensemble size.", "R2"),
    ("review", "rev-seg-002-b", "Results are reported from one run with a fixed seed.", "R2"),
    ("review", "rev-seg-001-b", "No external validation on a different scanner or site is provided.", "R7"),
]


def build() -> dict[str, list]:
    works, reviews, decisions = [], [], []
    for wid, title, fields in WORKS:
        url = f"{BASE}/forum?id={wid}"
        works.append(Work(
            work_id=f"fixture:{wid}", native_id=wid, title=title, url=url, venue="FakeConf 2099",
            year=2099, fields=fields, work_type="submission", provenance=prov(url, title),
        ))
        for suffix, text in zip("ab", REVIEWS[wid], strict=True):
            rid = f"rev-{wid}-{suffix}"
            rurl = f"{BASE}/forum?id={wid}&noteId={rid}"
            reviews.append(ReviewEvent(
                review_id=rid, work_id=f"fixture:{wid}", text=text, url=rurl, round=1,
                provenance=prov(rurl, text),
            ))
        outcome, raw, dtext = DECISIONS[wid]
        durl = f"{BASE}/forum?id={wid}&noteId=dec-{wid}"
        decisions.append(Decision(
            decision_id=f"dec-{wid}", work_id=f"fixture:{wid}", outcome=outcome, outcome_raw=raw, text=dtext,
            url=durl, mapping_rule="fixture", provenance=prov(durl, dtext or raw),
        ))

    by_id = {("review", r.review_id): r for r in reviews} | {("decision", d.decision_id): d for d in decisions}
    excerpts, tags = [], []
    for kind, sid, sentence, code in EXCERPT_SPECS:
        src = by_id[(kind, sid)]
        start = src.text.index(sentence)
        ex = Excerpt.from_source(src.text, start, start + len(sentence), source_kind=kind, source_id=sid,
                                 source_url=src.url)
        excerpts.append(ex)
        tags.append(RiskTag(excerpt_id=ex.excerpt_id, risk_code=code, confidence=0.9, generator=Generator.mock))
    assert excerpts[0].start == 0

    def eid(sid: str, prefix: str) -> str:
        (hit,) = [e.excerpt_id for e in excerpts if e.source_id == sid and e.text.startswith(prefix)]
        return hit

    cards = [
        RiskCard(
            card_id="card-fx-leak",
            risk_code="R3",
            title="Random splitting can leak near-duplicates into the test set",
            why_applies=WhyApplies(
                text="The plan splits the data randomly (80/10/10) and has no step to remove near-duplicate "
                     "compositions.",
                plan_lines=[16, 17],
            ),
            evidence=[
                eid("rev-gnn-001-a", "The paper reports a random"),
                eid("rev-gnn-001-a", "Random splits are known"),
                eid("rev-gnn-002-a", "The pretraining corpus"),
                eid("dec-gnn-001", "the random split likely"),
            ],
            works=["fixture:gnn-001", "fixture:gnn-002"],
            score=RiskScore(similarity=0.82, frequency=0.5, severity=1.0, confidence=0.9, total=0.78,
                            weights={"similarity": 0.25, "frequency": 0.25, "severity": 0.25, "confidence": 0.25}),
            generator=Generator.mock,
        ),
        RiskCard(
            card_id="card-fx-seed",
            risk_code="R2",
            title="Single-seed results without error bars",
            why_applies=WhyApplies(text="The plan states that no error bars and no ablation will be reported.",
                                   plan_lines=[22]),
            evidence=[
                eid("rev-gnn-001-b", "All numbers come from"),
                eid("rev-gnn-001-b", "Without error bars"),
                eid("rev-gnn-003-b", "A single seed is used"),
                eid("rev-seg-002-b", "Results are reported from"),
            ],
            works=["fixture:gnn-001", "fixture:gnn-003", "fixture:seg-002"],
            score=RiskScore(similarity=0.7, frequency=0.5, severity=0.6, confidence=0.85, total=0.65,
                            weights={"similarity": 0.25, "frequency": 0.25, "severity": 0.25, "confidence": 0.25}),
            generator=Generator.mock,
        ),
    ]

    plan_text = (HERE / "plans" / "plan.md").read_text(encoding="utf-8")
    plan = PlanDocument.from_text(plan_text, session_id="fixture-session")
    used = {x for c in cards for x in c.evidence}
    result = PremortemResult(
        session_id="fixture-session",
        plan_id=plan.plan_id,
        generated_at=ACCESSED,
        plan=plan,
        similar_works=[
            SimilarWork(work_id=w.work_id, similarity=s, title=w.title, url=w.url, venue=w.venue, year=w.year)
            for w, s in zip(works[:3], (0.82, 0.74, 0.61), strict=True)
        ],
        evidence=[e for e in excerpts if e.excerpt_id in used],
        risk_cards=cards,
        stages=[
            StageStatus(stage="retrieve", phase="search", impl="fixture"),
            StageStatus(stage="extract", phase="analyze", impl="fixture:mock"),
            StageStatus(stage="cards", phase="analyze", impl="fixture:mock"),
        ],
        notices=["[FAKE] fixture result for UI/API development"],
    )
    return {
        "works": works, "reviews": reviews, "decisions": decisions, "excerpts": excerpts,
        "risk_tags": tags, "risk_cards": cards, "premortem_result": [result],
    }


def write(data: dict[str, list]) -> None:
    for name, items in data.items():
        if name == "premortem_result":
            (HERE / "premortem_result.json").write_text(
                json.dumps(items[0].model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            continue
        lines = [json.dumps(x.model_dump(mode="json"), ensure_ascii=False) for x in items]
        (HERE / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    d = build()
    write(d)
    print({k: len(v) for k, v in d.items()})
