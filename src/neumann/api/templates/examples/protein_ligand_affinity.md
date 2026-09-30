# 연구계획서 (예시) — 단백질-리간드 결합 친화도 예측 등변 GNN

## 1. 연구 목표

단백질-리간드 복합체의 3차원 구조로부터 결합 친화도(pKd)를 예측하는 E(3)-equivariant Graph Neural Network를 개발하여,
신약 후보 물질의 가상 스크리닝(virtual screening) 단계에서 도킹 점수 함수를 대체하는 것을 목표로 한다.

## 2. 방법

결합 포켓 원자와 리간드 원자를 하나의 그래프로 구성하고, 등변 메시지 전달 층으로 원자 간 거리·방향 정보를 학습한다.
제안 모델을 AutoDock Vina 점수 함수 1종과 비교한다.

## 3. 데이터

PDBbind v2020 general set 약 19,000개 복합체로 학습하고, CASF-2016 core set 285개를 테스트셋으로 사용한다.
두 세트 사이에 겹치는 복합체와 서열이 유사한 단백질에 대한 별도 제거 절차는 두지 않는다.
We randomly split the training complexes into 90/10 train/validation sets, without scaffold or protein-family grouping.
결정 구조가 없는 ChEMBL 활성 화합물 약 30,000건은 AutoDock Vina 도킹 포즈를 입력으로 쓰고, 도킹 점수를 결합 친화도 라벨로 사용한다.

## 4. 평가

CASF-2016 core set에서 Pearson 상관계수와 RMSE 를 보고한다.
We train a single model with one random seed, do not report error bars, and no ablation study is planned.

## 5. 기대 성과

제안 모델이 기존 도킹 점수 함수 대비 더 높은 상관계수를 달성하여, 신약 후보 선별 비용을 줄일 것으로 기대한다.
