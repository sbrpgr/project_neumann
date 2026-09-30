# 연구계획서 (예시) — 전해액 이온전도도 예측 대리모델

## 1. 연구 목표

리튬이온 배터리 전해액의 이온전도도를 예측하는 Graph Neural Network 대리모델을 개발하여,
실험 합성 없이 후보 조성을 사전 선별하는 것을 목표로 한다.

## 2. 방법

분자 그래프 인코더와 조성 임베딩을 결합한 GNN 을 학습한다.
제안 모델을 기존에 발표된 baseline 2종과 비교한다.

## 3. 데이터

문헌에 보고된 약 12,000건의 전해액 조성-전도도 데이터를 수집해 사용한다.
We randomly split the dataset into 80/10/10 train/validation/test sets.
조성이 거의 동일한 중복 항목에 대한 별도 제거 절차는 두지 않는다.

## 4. 평가

holdout test set 에서 R2 와 MAE 를 보고한다.
We do not report error bars, and no ablation study is planned.
Code and data will not be released due to an industrial collaboration agreement.

## 5. 기대 성과

제안 모델이 기존 baseline 대비 더 높은 예측 정확도를 달성할 것으로 기대한다.
