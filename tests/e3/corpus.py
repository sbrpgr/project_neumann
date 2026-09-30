"""E3 테스트용 가짜 코퍼스(분명히 가짜: 제목 [FIXTURE], URL example.org). 실제 심사평이 아니다.

두 분야: (A) 소재·화학 GNN 물성 예측 4편, (B) 의료영상 딥러닝 4편. 논문마다 심사평 2건.
E2 실색인이 없을 때 파이프라인을 끝까지 돌려 보는 데 쓴다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from neumann.analyze.backend import FixtureBackend
from neumann.models import Provenance, ReviewEvent, Work, sha256_text

ACCESSED = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)

WORKS: list[dict] = [
    {
        "id": "A1",
        "title": "[FIXTURE] Graph neural network surrogate for ionic conductivity of liquid electrolytes",
        "abstract": "We train a graph neural network on literature data of lithium battery electrolyte formulations "
        "to predict ionic conductivity and screen candidate compositions.",
        "fields": ["materials", "battery", "electrolyte", "graph neural network", "property prediction"],
        "reviews": [
            "The paper proposes a GNN surrogate for electrolyte conductivity. "
            "The random split of the dataset likely places near-duplicate formulations in both the training and test sets, "
            "which inflates the reported accuracy. "
            "The baselines are weak: only a linear model and a random forest are compared. "
            "No error bars or results over multiple random seeds are reported. "
            "The code and the curated dataset are not released, so the results cannot be reproduced.",
            "This is an interesting application. "
            "An ablation study is missing, so it is unclear which component of the architecture drives the gains. "
            "The model is never validated experimentally by synthesizing and measuring any predicted electrolyte. "
            "The literature data mixes measurements taken at different temperatures and salt concentrations, "
            "which raises concerns about label noise.",
        ],
    },
    {
        "id": "A2",
        "title": "[FIXTURE] Message passing networks for molecular property prediction of battery solvents",
        "abstract": "A message passing neural network predicts viscosity and conductivity of battery solvents from molecular "
        "graphs trained on public datasets.",
        "fields": ["chemistry", "molecular property prediction", "graph neural network", "battery"],
        "reviews": [
            "The evaluation relies on a random split instead of a scaffold split, so structurally similar molecules leak "
            "between training and test data. "
            "The comparison to more recent baselines such as equivariant networks is missing. "
            "Standard deviations across runs should be reported to show the improvement is statistically significant.",
            "The claimed generalization to unseen chemistries is not supported by any out-of-distribution test. "
            "Hyperparameters and training details are not described, which hurts reproducibility. "
            "The paper is well written and easy to follow.",
        ],
    },
    {
        "id": "A3",
        "title": "[FIXTURE] Crystal graph networks for solid electrolyte discovery",
        "abstract": "Crystal graph convolutional networks screen solid-state electrolyte candidates for lithium conductivity.",
        "fields": ["materials", "solid electrolyte", "crystal graph", "screening"],
        "reviews": [
            "The screening results are not validated by DFT calculations or experiments, so their physical plausibility "
            "is unclear. "
            "The training set contains duplicate structures that also appear in the test set. "
            "The authors do not compare against simple baselines like composition-only models.",
            "Novelty is limited because crystal graph networks for this task were already proposed in prior work. "
            "No uncertainty estimates or confidence intervals accompany the predictions.",
        ],
    },
    {
        "id": "A4",
        "title": "[FIXTURE] Transfer learning for polymer electrolyte property prediction",
        "abstract": "We pretrain a graph model on large molecular datasets and fine-tune it to predict polymer electrolyte "
        "conductivity.",
        "fields": ["polymer", "electrolyte", "transfer learning", "graph neural network"],
        "reviews": [
            "Results are reported from a single run, and variance across seeds should be analyzed. "
            "The claims of state-of-the-art performance are overstated given the small margins. "
            "It is unclear whether the pretraining data overlaps with the test polymers, which could be data leakage.",
            "The dataset is small and not representative of commercially relevant polymer electrolytes. "
            "Please release the code so that others can reproduce the fine-tuning results.",
        ],
    },
    {
        "id": "B1",
        "title": "[FIXTURE] Deep convolutional networks for pneumonia detection in chest radiographs",
        "abstract": "A convolutional neural network detects pneumonia in chest X-ray images and is compared with radiologists.",
        "fields": ["medical imaging", "chest x-ray", "convolutional neural network", "classification"],
        "reviews": [
            "Images from the same patient appear in both training and test sets because the split is done per image, "
            "which is a clear case of data leakage. "
            "There is no external validation on data from a different hospital, so generalization is unclear. "
            "The comparison with radiologists lacks a proper clinical baseline.",
            "Confidence intervals for the AUC should be reported. "
            "The labels were mined from reports with natural language processing and are known to be noisy.",
        ],
    },
    {
        "id": "B2",
        "title": "[FIXTURE] Robust lesion segmentation in dermoscopy images with attention U-Net",
        "abstract": "An attention U-Net segments skin lesions in dermoscopy images across several public datasets.",
        "fields": ["medical imaging", "segmentation", "dermatology", "u-net"],
        "reviews": [
            "The method is evaluated only on public benchmarks and never on an external clinical cohort. "
            "Ablation experiments for the attention module are missing. "
            "Results over multiple random seeds are not reported.",
            "The improvement over the baseline U-Net is marginal and within the noise. "
            "Implementation details such as augmentation settings are missing, which harms reproducibility.",
        ],
    },
    {
        "id": "B3",
        "title": "[FIXTURE] Self-supervised pretraining for chest CT classification",
        "abstract": "Self-supervised pretraining on unlabeled chest CT volumes improves downstream classification.",
        "fields": ["medical imaging", "ct", "self-supervised learning", "classification"],
        "reviews": [
            "The pretraining corpus may contain scans of patients from the test set, leading to contamination. "
            "Baselines with ImageNet pretraining are missing. "
            "The clinical relevance of the task is not validated with radiologists.",
            "The dataset is highly imbalanced and the paper does not discuss how this affects the metrics. "
            "Code will not be released, which limits reproducibility.",
        ],
    },
    {
        "id": "B4",
        "title": "[FIXTURE] Uncertainty-aware diagnosis of diabetic retinopathy from fundus photographs",
        "abstract": "A Bayesian convolutional network grades diabetic retinopathy from fundus images with uncertainty estimates.",
        "fields": ["medical imaging", "ophthalmology", "uncertainty", "convolutional neural network"],
        "reviews": [
            "The model is tested on a single site and its generalization to other hospitals and camera types is unknown. "
            "No statistical test supports the claimed improvement over prior methods.",
            "Label quality is a concern because grades from a single annotator were used. "
            "The contribution is incremental compared to existing Bayesian deep learning work.",
        ],
    },
]


def _prov(url: str, text: str) -> Provenance:
    return Provenance(source="fixture", source_url=url, accessed_at=ACCESSED, content_sha256=sha256_text(text))


def build() -> tuple[list[Work], list[ReviewEvent]]:
    works: list[Work] = []
    reviews: list[ReviewEvent] = []
    for w in WORKS:
        wid = f"fixture:{w['id']}"
        url = f"https://example.org/fixture/{w['id']}"
        works.append(
            Work(work_id=wid, title=w["title"], url=url, abstract=w["abstract"], fields=w["fields"], venue="FIXTURE",
                 year=2025, provenance=_prov(url, w["title"] + w["abstract"]))
        )
        for j, text in enumerate(w["reviews"], 1):
            rurl = f"{url}#review{j}"
            reviews.append(
                ReviewEvent(review_id=f"{wid}:r{j}", work_id=wid, text=text, url=rurl, provenance=_prov(rurl, text))
            )
    return works, reviews


def build_backend() -> FixtureBackend:
    works, reviews = build()
    return FixtureBackend(works, reviews)


def dump_json(path: str | Path) -> Path:
    works, reviews = build()
    data = {"works": [w.model_dump(mode="json") for w in works], "reviews": [r.model_dump(mode="json") for r in reviews]}
    p = Path(path)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


# 테스트에 쓰는 짧은 계획서(데모 계획서와 같은 분야·구조, 직접 작성)
PLAN_BATTERY = """\
# 연구계획서 — 전해액 이온전도도 예측 GNN

## 1. 목표
리튬 배터리 전해액의 이온전도도를 예측하는 Graph Neural Network 대리모델을 개발한다.

## 2. 방법
분자 그래프 인코더를 학습하고 기존 baseline 2종과 비교한다.

## 3. 데이터
문헌에 보고된 전해액 조성-전도도 데이터를 수집한다.
We randomly split the dataset into 80/10/10 train/validation/test sets.

## 4. 평가
holdout test set 에서 MAE 를 보고한다.
We do not report error bars, and no ablation study is planned.
Code and data will not be released.
"""

PLAN_IMAGING = """\
# 연구계획서 — 흉부 X선 폐렴 검출 CNN

## 1. 목표
흉부 X선 영상에서 폐렴을 검출하는 Convolutional Neural Network 분류기를 개발한다.

## 2. 방법
ResNet 기반 medical imaging classification 모델을 학습하고 clinical baseline 과 비교한다.

## 3. 데이터
공개 chest x-ray 데이터셋 영상을 사용한다.
We randomly split the images into train/validation/test sets.

## 4. 평가
검증 데이터셋에서 AUC 를 보고한다. external validation 은 계획하지 않는다.
"""

# 범위 밖 대조(조리법). E3-L1s: 300자 미만은 길이로 거절(호출 0)되므로, 적합성 판정 경로("연구계획서가 아니다")를
# 계속 시험하려고 300자 이상으로 늘렸다. 300자 미만 조리법은 tests/e3/short_inputs.py(N01)가 맡는다.
RECIPE = """\
# 김치찌개 끓이는 법

1. 냄비에 돼지고기와 잘 익은 김치를 넣고 볶는다.
2. 물을 붓고 두부와 대파를 넣는다.
3. 고춧가루와 다진 마늘로 간을 맞춘 뒤 10분 더 끓인다.
4. 김치가 너무 시면 설탕을 반 큰술 넣어 신맛을 줄인다.
5. 돼지고기 대신 참치 통조림을 넣으면 참치김치찌개가 된다.
6. 멸치와 다시마로 육수를 내면 더 깊은 맛이 난다.
7. 불을 끄기 직전에 청양고추를 넣으면 칼칼해진다.
맛있게 먹는다.
남은 찌개는 식혀서 냉장고에 두고 다음 날 다시 끓여 먹는다. 라면 사리를 넣어도 잘 어울린다.
밥과 김, 계란말이를 곁들이면 한 끼 식사로 충분하다.
"""
