# 연구계획서 (예시) — 의료영상 분류 심층신경망

## 1. 연구 목표

흉부 X선 영상에서 폐렴 징후를 자동으로 검출하는 Convolutional Neural Network 분류기를 개발하여,
의료진의 진단 보조 도구로 활용하는 것을 목표로 한다.

## 2. 방법

기존 의료영상 데이터셋을 활용하여 ResNet 및 DenseNet 기반의 이미지 분류 모델을 학습한다.
제안 모델을 임상 기준선(clinical baseline)과 비교하여 성능을 평가한다.

## 3. 데이터

공개된 의료영상 벤치마크 데이터셋(예: ChexPert, NIH Chest X-ray)의 약 50,000건 영상을 수집한다.
We randomly split the dataset into 80/10/10 train/validation/test sets.
각 영상의 메타데이터(촬영 기관, 환자 정보)는 익명화 절차를 거친다.

## 4. 평가

검증 데이터셋에 대해 ROC-AUC, 민감도, 특이도를 보고한다.
We do not report error bars, and no ablation study is planned.
학습된 가중치는 저장소 라이센스 정책에 따라 공개 여부를 결정한다.

## 5. 기대 성과

제안 모델이 기존 임상 기준선과 동등 이상의 분류 성능을 달성하여,
임상 환경의 대규모 스크리닝 자동화에 기여할 것으로 기대한다.
