"""E3-L1s: 짧은 입력 보정 세트(직접 작성, 실제 계획서 아님).

단계 기대값(대표 방침 2026-09-30, 거절 기준은 같은 날 "300자 미만은 거절"로 바뀜):
- reject: 판정할 거리가 없다. 앞뒤 공백을 뺀 원문이 300자 미만(공백 포함, 한글 가중치 없음, 범위 밖 글 포함)이거나,
  지시어로 시작하는 한 문장·요소가 적은 한 문장·분야와 방법을 알 수 없는 글. LLM을 부르지 않고 거절, 무엇을 적을지 안내.
- warn: 300~600자이거나 요소 2개 이하이지만 분야·방법을 알 수 있다. 경고와 함께 끝까지 분석, 카드 0장 금지.
- offtopic: 범위 밖(요리·여행·광고 등). 300자 미만은 길이로, 그 이상은 지금처럼 적합성 판정이 거절한다.

백테스트 입력(data/eval/backtest_plans.jsonl)은 공개 초록에서 기여 문장을 지운 것이라 저장소에 싣지 않고,
같은 모양의 한국어 번역·의역(W19·W20·X02·V02·V03)을 대신 둔다. 원문 5편의 단계는 보고서 기준표에 적었다.
"""

from __future__ import annotations

# (id, 본문). 처음 보정 때 경고로 둔 짧은 AI4S 입력 21건: 모두 300자 미만이라 새 기준에서는 거절(too_short)
UNDER_300: list[tuple[str, str]] = [
    ("W01", "그래프 신경망(GNN)으로 리튬 배터리 전해액의 이온전도도를 예측한다. "
            "문헌에서 모은 조성-전도도 데이터로 학습하고 MAE로 평가한다."),
    ("W02", "물리정보 신경망(PINN)으로 2차원 비압축성 나비에-스토크스 방정식을 풀고, "
            "관측 데이터가 적을 때의 자료동화 성능을 유한요소 해와 비교한다."),
    ("W03", "단백질 구조 예측 모델로 숨은(cryptic) 결합 포켓을 찾는다. "
            "분자동역학(MD) 시뮬레이션 없이 정적 구조만으로 포켓을 예측하는 것이 목표다."),
    ("W04", "기후 모델 출력의 강수 편향을 확산 모델로 보정한다. ERA5 재분석 자료를 기준으로 삼는다."),
    ("W05", "머신러닝 원자간 퍼텐셜(MLIP)로 고체 전해질의 리튬 이온 확산 계수를 예측한다. "
            "DFT 분자동역학 궤적으로 학습하고 실험값과 비교해 검증한다."),
    ("W06", "단일세포 RNA-seq 데이터에서 세포 유형을 분류하는 트랜스포머 모델을 만든다. "
            "여러 조직의 공개 데이터셋으로 학습하고, 처음 보는 조직에서 정확도를 평가한다."),
    ("W07", "흉부 X선 영상으로 폐렴을 분류하는 CNN을 학습한다. 외부 병원 데이터로 일반화 성능을 검증한다."),
    ("W08", "소분자 약물 후보의 용해도를 그래프 신경망으로 예측한다. 스캐폴드 분할로 평가해 데이터 누출을 막는다."),
    ("W09", "Neural operator로 난류 유동의 장기 예측을 한다. 학습 구간 밖 레이놀즈 수에서의 오차를 측정한다."),
    ("W10", "We propose a diffusion model to generate stable crystal structures. "
            "We evaluate stability with DFT relaxation."),
    ("W11", "We train a graph neural network on QM9 to predict HOMO-LUMO gaps. "
            "Performance is measured by MAE against DFT labels."),
    ("W12", "Physics-informed neural networks often fail on stiff PDEs. "
            "We study how adaptive loss weighting changes convergence on reaction-diffusion benchmarks."),
    ("W13", "Machine learning weather models are fast but blur extremes. We fine-tune a transformer forecaster "
            "with a spectral loss and compare extreme-precipitation skill against ERA5."),
    ("W14", "목표: 단백질-리간드 결합 친화도 예측\n방법: 3D 등변 GNN\n데이터: PDBbind\n평가: 시간 분할 테스트셋 RMSE"),
    ("W15", "위성 영상으로 산불 확산을 예측하는 딥러닝 모델을 만든다. 과거 산불 기록으로 학습한다."),
    ("W16", "그래프 신경망으로 전해액 이온전도도를 예측해 보려는 아이디어를 구상 중이다.\n아직 세부 계획은 정하지 않았다."),
    ("W17", "QM9 데이터로 GNN을 학습해 분자 에너지를 예측하고, 무작위 분할과 스캐폴드 분할의 MAE를 비교해 평가한다."),
    ("W18", "Protein language models are used to predict mutation effects. "
            "We fine-tune ESM on deep mutational scanning data and report Spearman correlation on held-out proteins."),
    # 백테스트 입력과 같은 모양(연구 배경만 적은 초록)의 한국어 의역
    ("W19", "최근 물리정보 신경망(PINN)은 PDE 기반 시스템, 특히 자료동화를 푸는 방법으로 큰 관심을 받았다. "
            "그러나 이 방법은 아직 초기 단계이고, 제대로 이해되지 않은 단점과 실패가 많다."),
    ("W20", "단백질-리간드 결합 포켓을 정확히 예측하는 일은 단백질 기능 분석과 저분자 신약 설계의 핵심 과제다. "
            "단백질은 유연하고 동적이어서 숨은(cryptic) 포켓을 감춘다. "
            "현재 방법은 분자동역학(MD)에 의존해 확장성이 낮고 편향이 있다. "
            "최근의 ML 방법도 큰 MD 데이터셋이 있어야 모델을 학습할 수 있다."),
    ("W21", "Plug-and-play diffusion priors are a promising direction for solving inverse problems. "
            "Most studies focus on natural image restoration, so their performance on scientific inverse problems "
            "such as black hole imaging is unexplored."),
]

# 한국어 4~5문장 AI4S 계획(요소 2~4개): 원문이 177~236자라 300자 기준에서는 거절(too_short).
# 한국어는 같은 내용이 영어보다 짧다는 점을 보고서에 적으려고 남긴다.
KO_UNDER_300: list[tuple[str, str]] = [
    ("K01", "리튬 배터리 전해액의 이온전도도를 그래프 신경망(GNN)으로 예측하는 대리모델을 만들고자 한다. "
            "문헌에 보고된 전해액 조성과 온도별 전도도 값을 모아 학습 데이터로 쓴다. "
            "분자 그래프 인코더에 염 농도와 온도를 조건으로 넣어 서로 다른 측정 조건을 구분한다. "
            "기존 선형 회귀와 랜덤 포레스트를 기준선으로 두고 평균절대오차(MAE)로 비교한다. "
            "예측이 충분히 정확하면 아직 합성되지 않은 조성을 스크리닝하는 데 쓸 계획이다."),
    ("K02", "물리정보 신경망(PINN)은 지배 방정식인 편미분방정식을 손실 함수에 넣어 신경망을 학습하는 방법으로, "
            "관측이 적은 상황의 자료동화에서 특히 큰 관심을 받았다. 유체, 열전달, 고체역학의 순방향 문제와 역문제에 모두 쓰인다. "
            "그러나 이 방법은 아직 초기 단계이고, 강성 문제나 다중 스케일 문제에서 학습이 자주 실패한다. "
            "이런 실패가 왜 일어나는지는 아직 제대로 이해되지 않았다."),
    ("K03", "단백질-리간드 결합 포켓을 정확히 예측하는 일은 단백질 기능 분석과 저분자 신약 설계의 핵심 과제다. "
            "단백질은 유연하고 동적이어서 평소에는 보이지 않는 숨은(cryptic) 포켓을 감추고 있다. "
            "현재 방법은 대부분 분자동역학(MD) 시뮬레이션에 의존해 계산 비용이 크고 확장성이 낮으며 편향이 있다. "
            "최근의 기계학습 방법도 큰 MD 데이터셋을 후처리해 모델을 학습해야 한다는 한계가 있다."),
    ("K04", "전지구 기후 모델의 출력은 공간 해상도가 낮아 지역 강수 극값을 제대로 나타내지 못한다. "
            "확산 모델로 저해상도 강수장을 고해상도로 바꾸는 통계적 규모축소를 하려고 한다. "
            "ERA5 재분석 자료와 관측 격자 자료를 짝지어 학습 데이터로 쓴다. "
            "극한 강수 분위수와 공간 상관을 기존 보간법, CNN 기반 방법과 비교해 평가하고, 학습에 쓰지 않은 지역에서 따로 검증한다."),
    ("K05", "머신러닝 원자간 퍼텐셜(MLIP)을 이용해 황화물계 고체 전해질의 리튬 이온 확산 계수를 예측하려고 한다. "
            "DFT 분자동역학 궤적을 학습 데이터로 쓰고, 온도별 확산 계수를 긴 시뮬레이션으로 계산한다. "
            "학습 구조와 조성이 다른 전해질에서 오차가 얼마나 커지는지 확인한다. "
            "계산한 활성화 에너지를 문헌의 실험값과 비교해 검증할 계획이다."),
    ("K06", "위성 영상과 기상 자료를 함께 입력으로 받아 다음 날 산불 확산 범위를 예측하는 딥러닝 모델을 만든다. "
            "과거 10년의 산불 경계 기록과 풍속, 습도, 식생 지수를 학습 데이터로 쓴다. "
            "모델은 합성곱 신경망과 순환 신경망을 결합한 구조를 쓴다. "
            "연도 단위로 데이터를 나누어 평가하고, 지역별 성능 차이를 따로 분석한다."),
    ("K07", "소분자 약물 후보의 수용해도를 그래프 신경망으로 예측하려고 한다. "
            "공개 데이터셋 여러 개를 합쳐 학습 데이터를 만들되, 같은 분자가 여러 번 들어간 경우는 측정값을 평균한다. "
            "무작위 분할 대신 스캐폴드 분할로 평가해 구조가 비슷한 분자가 학습과 평가에 함께 들어가지 않게 한다. "
            "기존 기술자 기반 모델과 비교하고, 예측 불확실성도 함께 보고한다."),
    ("K08", "목표: 단백질-리간드 결합 친화도를 3차원 구조에서 예측한다.\n"
            "방법: 원자 좌표를 입력으로 받는 SE(3) 등변 그래프 신경망을 학습하고, 포켓 주변 원자만 잘라 입력한다.\n"
            "데이터: PDBbind 일반 세트로 학습하고 코어 세트는 평가에만 쓴다.\n"
            "평가: 공개 연도로 나눈 시간 분할 테스트셋에서 RMSE와 피어슨 상관을 보고하고, "
            "서열 유사도가 낮은 단백질만 따로 모아 성능을 다시 잰다."),
]

# 300~600자 AI4S 입력(분야·방법이 보임): 경고 후 끝까지 분석
WARN: list[tuple[str, str]] = [
    ("V01", "리튬 배터리 전해액의 이온전도도를 그래프 신경망(GNN)으로 예측하는 대리모델을 만들고자 한다. "
            "문헌에 보고된 전해액 조성과 온도별 전도도 값을 모아 학습 데이터로 쓴다. "
            "문헌마다 측정 온도와 염 농도가 달라서 이 조건을 입력 변수로 함께 넣는다. "
            "분자 그래프 인코더는 용매와 염을 따로 인코딩한 뒤 몰분율로 가중 평균한다. "
            "기존 선형 회귀와 랜덤 포레스트를 기준선으로 두고 평균절대오차(MAE)로 비교한다. "
            "같은 조성이 학습과 평가에 함께 들어가지 않도록 조성 단위로 데이터를 나눈다. "
            "예측이 충분히 정확하면 아직 합성되지 않은 조성을 스크리닝하는 데 쓸 계획이다."),
    ("V02", "물리정보 신경망(PINN)은 지배 방정식인 편미분방정식을 손실 함수에 넣어 신경망을 학습하는 방법이다. "
            "관측이 적은 상황에서도 물리 법칙을 제약으로 쓸 수 있어 자료동화에서 특히 큰 관심을 받았다. "
            "유체, 열전달, 고체역학의 순방향 문제와 역문제에 모두 쓰이고, 최근에는 기후와 해양 모델에도 적용되고 있다. "
            "그러나 이 방법은 아직 초기 단계이고, 강성 문제나 다중 스케일 문제에서 학습이 자주 실패한다. "
            "손실 항 사이의 균형, 배치점 선택, 신경망의 스펙트럼 편향이 원인으로 거론된다. "
            "하지만 이런 실패가 왜, 언제 일어나는지는 아직 체계적으로 이해되지 않았다."),
    ("V03", "단백질-리간드 결합 포켓을 정확히 예측하는 일은 단백질 기능 분석과 저분자 신약 설계의 핵심 과제다. "
            "단백질은 유연하고 동적이어서 평소 구조에서는 보이지 않는 숨은(cryptic) 포켓을 감추고 있다. "
            "이런 포켓은 기존에 표적으로 삼기 어려웠던 단백질에 새로운 약물 결합 자리를 열어 줄 수 있다. "
            "현재 방법은 대부분 분자동역학(MD) 시뮬레이션에 의존해 계산 비용이 크고 확장성이 낮으며 편향이 있다. "
            "최근의 기계학습 방법도 큰 MD 데이터셋을 후처리해 모델을 학습해야 한다는 한계가 있다. "
            "정적 구조만으로 숨은 포켓을 찾을 수 있는지는 아직 분명하지 않다."),
    ("V04", "전지구 기후 모델의 출력은 공간 해상도가 낮아 지역 강수 극값을 제대로 나타내지 못한다. "
            "확산 모델로 저해상도 강수장을 고해상도로 바꾸는 통계적 규모축소를 하려고 한다. "
            "ERA5 재분석 자료와 관측 격자 자료를 짝지어 학습 데이터로 쓰고, 지형 고도를 조건 입력으로 넣는다. "
            "학습은 과거 30년 가운데 앞의 25년으로 하고, 나머지 5년은 평가에만 쓴다. "
            "극한 강수 분위수와 공간 상관을 기존 보간법, CNN 기반 방법과 비교해 평가한다. "
            "학습에 쓰지 않은 지역에서도 따로 검증해 지역을 바꿔도 성능이 유지되는지 확인한다. "
            "생성한 여러 표본의 퍼짐으로 불확실성도 함께 제시한다."),
    ("V05", "머신러닝 원자간 퍼텐셜(MLIP)을 이용해 황화물계 고체 전해질의 리튬 이온 확산 계수를 예측하려고 한다. "
            "DFT 분자동역학 궤적을 학습 데이터로 쓰고, 온도별 확산 계수를 긴 시뮬레이션으로 계산한다. "
            "학습 데이터에는 여러 온도와 변형 구조를 넣어 고온에서의 원자 배치도 포함한다. "
            "학습 구조와 조성이 다른 전해질에서 오차가 얼마나 커지는지 따로 확인한다. "
            "계산한 활성화 에너지를 문헌의 실험값과 비교해 검증할 계획이다. "
            "퍼텐셜의 불확실성이 큰 구조는 DFT로 다시 계산해 학습 데이터에 더한다. "
            "마지막으로 새 조성 후보 몇 개의 전도도를 예측해 실험 팀에 넘길 계획이다."),
    ("V06", "위성 영상과 기상 자료를 함께 입력으로 받아 다음 날 산불 확산 범위를 예측하는 딥러닝 모델을 만든다. "
            "과거 10년의 산불 경계 기록과 풍속, 습도, 식생 지수를 학습 데이터로 쓴다. "
            "모델은 합성곱 신경망과 순환 신경망을 결합한 구조를 쓰고, 지형 경사를 추가 입력으로 넣는다. "
            "연도 단위로 데이터를 나누어 평가해 같은 산불이 학습과 평가에 함께 들어가지 않게 한다. "
            "지역별 성능 차이를 따로 분석하고, 큰 산불과 작은 산불에서의 오차를 나누어 본다. "
            "기존 물리 기반 확산 모델과도 같은 사례에서 비교한다. "
            "예측 지도는 소방 당국이 쓰는 격자 해상도에 맞춰 내보낸다."),
    ("V09", "Physics-informed neural networks (PINNs) embed the governing equations of a physical system into the "
            "training loss of a neural network. They have become popular for solving forward and inverse problems "
            "governed by partial differential equations, especially when observations are sparse. However, PINNs often "
            "fail to train on stiff, multi-scale, or chaotic dynamics, and the reasons for these failures are still "
            "poorly understood."),
    ("V10", "Generative models such as diffusion models can propose new crystal structures, but many generated "
            "candidates are thermodynamically unstable. We plan to condition a diffusion model on formation energy "
            "predicted by a graph neural network surrogate. Candidates will be relaxed with DFT to check stability."),
    ("V11", "Machine learning weather prediction models now match numerical weather prediction on average skill "
            "scores. However, they tend to smooth out extreme events such as heavy precipitation and tropical "
            "cyclones. We will fine-tune a transformer-based forecaster with a spectral loss and compare "
            "extreme-precipitation skill against ERA5 reanalysis."),
    ("V12", "Single-cell RNA sequencing produces millions of cell profiles across tissues and donors. Transformer "
            "foundation models pretrained on these profiles promise zero-shot cell type annotation. We will evaluate "
            "whether such models generalize to tissues that were absent from pretraining, using public atlases and "
            "accuracy on held-out tissues."),
    ("V13", "Protein language models can predict the effect of mutations without supervision. Deep mutational "
            "scanning experiments provide labelled fitness measurements for a few proteins. We propose to fine-tune "
            "ESM on these datasets and report Spearman correlation on proteins held out from training, comparing "
            "against unsupervised baselines."),
    ("V14", "Convolutional neural networks detect pneumonia in chest X-ray images with high accuracy on benchmark "
            "datasets. Their performance often drops when the images come from a different hospital or scanner. "
            "We plan to train on one public dataset and test on two external hospital datasets to measure this "
            "generalization gap."),
    ("V15", "Plug-and-play diffusion priors are a promising approach for solving inverse problems, where a pretrained "
            "diffusion model serves as the prior and a forward model encodes the measurements. Most studies evaluate "
            "them on natural image restoration such as deblurring and inpainting. Their performance on scientific "
            "inverse problems, such as black hole imaging or full waveform inversion, is largely unexplored."),
    ("V16", "Neural operators learn mappings between function spaces and can serve as fast surrogates for partial "
            "differential equation solvers. Fourier neural operators have been applied to turbulent flow, but long "
            "rollouts accumulate errors. We will study how training on multiple Reynolds numbers affects rollout "
            "stability and the error outside the training range."),
]

# 300자 이상인 한 문장(한 문장 규칙 재보정용)
LONG_SINGLE: list[tuple[str, str, str]] = [
    # 요소 3개 이상인 긴 한 문장: 경고(거절하지 않는다)
    ("S01", "warn", "We will train an equivariant graph neural network on the QM9 dataset of small organic molecules "
                    "to predict HOMO-LUMO gaps and dipole moments, evaluate it with mean absolute error against DFT "
                    "labels on a scaffold split, and compare it with SchNet and a fingerprint-based random forest "
                    "baseline trained on the same data."),
    # 연구 배경만 적은 긴 한 문장(요소 2개 이하): 한 문장 규칙으로 거절
    ("S02", "reject", "Physics-informed neural networks, which embed the governing partial differential equations "
                      "into the loss function of a neural network, have been widely adopted for forward and inverse "
                      "problems in fluid dynamics, heat transfer, and solid mechanics, yet their optimization is "
                      "notoriously unstable for stiff, chaotic, and multi-scale problems in practice."),
    # 지시어로 시작하는 긴 한 문장: 거절
    ("S03", "reject", "This is important not only for function approximation in high dimensions but also for the "
                      "solutions of partial differential equations with physics-informed neural networks, where the "
                      "choice of interpolation scheme and collocation points strongly affects accuracy, stability, and "
                      "the computational cost of training on large domains."),
]

REJECT: list[tuple[str, str]] = [
    # 지시어로 시작하는 한 문장(백테스트 ihHeqPLRDk와 같은 모양)
    ("X01", "This is important not only for function approximation but also for solving partial differential "
            "equations with physics-informed neural networks."),
    ("X02", "이는 함수 근사뿐 아니라 물리정보 신경망으로 편미분방정식을 푸는 데에도 중요하다."),
    ("X03", "AI로 신약 개발하기"),
    ("X04", "딥러닝 연구 계획"),
    ("X05", "이 연구는 매우 중요하며 앞으로 큰 발전이 기대된다. 좋은 결과를 얻을 것이다."),
    ("X06", "This is an important problem for the community. More work is clearly needed here."),
    ("X07", "PINN 연구"),
    ("X08", "기계학습을 이용한 소재 물성 예측에 관한 연구입니다."),
    ("X09", "Deep learning for materials discovery."),
    ("X10", "We use transformers for everything in science."),
    ("X11", "그래프 신경망으로 이온전도도를 예측한다."),
    ("X12", "This approach could change how we design new batteries in the coming decade."),
]

# 범위 밖. N01~N05는 300자 미만(길이로 거절), N06은 300자 이상(적합성 판정으로 거절)
OFFTOPIC: list[tuple[str, str]] = [
    ("N01", "김치찌개 만드는 법: 돼지고기를 볶다가 김치를 넣고 물을 부어 20분 끓인다. 두부와 대파를 넣고 간을 맞춘다."),
    ("N02", "제주도 2박 3일 여행 계획. 첫째 날은 성산일출봉과 우도를 둘러보고, 둘째 날은 한라산 영실 코스를 오른다. "
            "숙소는 서귀포 호텔로 예약했다."),
    ("N03", "Easy banana bread recipe\n"
            "Ingredients: 3 ripe bananas, 2 tablespoons butter, 1 teaspoon baking soda, 1 cup sugar.\n"
            "Preheat the oven to 175C. Mash the bananas, mix in the butter, and bake for 60 minutes.\n"
            "Makes 8 servings."),
    ("N04", "여름 맞이 특가 세일! 노트북 전 제품 30% 할인, 오늘 주문하면 내일 배송됩니다. 재고가 한정되어 있으니 서두르세요."),
    ("N05", "오늘은 아침에 늦잠을 자서 회사에 지각했다. 점심에는 동료들과 국수를 먹었고, 저녁에는 영화를 봤다. "
            "내일은 일찍 일어나야겠다고 일기에 적었다."),
    ("N06", "제주도 2박 3일 여행 일정을 정리했다. 첫째 날은 오전에 공항에 도착해 렌터카를 받고 성산일출봉과 우도를 둘러본다. "
            "점심은 해녀의 집에서 해산물을 먹고, 저녁에는 서귀포 올레시장에서 흑돼지와 귤을 산다. "
            "둘째 날은 한라산 영실 코스를 오르고 오후에는 중문 해변에서 쉰다. 저녁에는 호텔 근처 맛집에서 갈치조림을 먹는다. "
            "숙소는 서귀포 시내 호텔로 예약했고, 조식이 포함된 방으로 골랐다. "
            "셋째 날은 협재 해변과 한림공원, 근처 카페를 들른 뒤 저녁 비행기로 돌아온다. "
            "여행 경비는 1인당 40만 원으로 잡았고, 비가 오면 실내 관광지와 박물관으로 일정을 바꾼다."),
]

ALL: list[tuple[str, str, str]] = (
    [(i, "warn", t) for i, t in WARN]
    + [(i, exp, t) for i, exp, t in LONG_SINGLE]
    + [(i, "reject", t) for i, t in UNDER_300]
    + [(i, "reject", t) for i, t in KO_UNDER_300]
    + [(i, "reject", t) for i, t in REJECT]
    + [(i, "offtopic", t) for i, t in OFFTOPIC]
)
