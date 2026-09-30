# 연구계획서 (예시) — 신경 연산자 기반 대기 유체 대리모델

## 1. 연구 목표

Fourier Neural Operator(FNO)로 2차원 비압축성 Navier-Stokes 방정식과 전지구 대기 순환의 시간 전개를 학습하는 대리모델을 개발하여,
격자 해상도에 무관하게 수치 기상 모델보다 빠르게 10일 예측장을 만드는 것을 목표로 한다.

## 2. 방법

FNO 층 4개로 현재 시점의 속도장·지위고도·온도장에서 6시간 뒤 상태를 예측하고, 이를 반복 적용해 10일까지 롤아웃한다.
손실 함수는 격자점별 MSE 만 사용하며, 질량·에너지 보존이나 비발산 조건은 반영하지 않는다.
제안 모델을 U-Net 과 ResNet 기준선과 비교한다.

## 3. 데이터

Navier-Stokes 는 점성 계수 1e-3, 64×64 격자로 시뮬레이션한 궤적 1,000개를, 대기 자료는 ERA5 재분석 1979–2018년 5.625° 격자(32×64)를 사용한다.
We randomly split all time snapshots into 80/10/10 train/validation/test sets.
학습과 평가는 같은 격자 해상도, 같은 기간 안에서 이루어진다.

## 4. 평가

테스트 시점에서 6시간 뒤 한 단계 예측의 상대 L2 오차와 RMSE 를 보고한다.
All results come from a single training run with one random seed; we do not report error bars.
수치 해법(pseudo-spectral solver, IFS) 대비 계산 시간은 따로 측정하지 않는다.

## 5. 기대 성과

제안 모델이 수치 모델보다 수천 배 빠르면서 비슷한 정확도로 기상장을 예측하여, 기후 시나리오 분석의 계산 부담을 줄일 것으로 기대한다.
