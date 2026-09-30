"""E3-L1s: 짧은 입력 보정 세트(직접 작성, 실제 계획서 아님).

단계 기대값(대표 방침 2026-09-30):
- reject: 판정할 거리가 없다(너무 짧음·지시어로 시작하는 한 문장·요소가 적은 한 문장·분야와 방법을 알 수 없는 글).
  LLM을 부르지 않고 거절, 무엇을 더 적을지 안내.
- warn: 짧지만 분야·방법을 알 수 있다. 경고와 함께 끝까지 분석, 카드 0장 금지.
- offtopic: 범위 밖(요리·여행·광고 등). 지금처럼 거절(거절 단계 또는 적합성 판정).

백테스트 입력(data/eval/backtest_plans.jsonl)은 공개 초록에서 기여 문장을 지운 것이라 저장소에 싣지 않고,
같은 모양의 한국어 번역·의역(W19·W20·X2)을 대신 둔다. 원문 5편의 단계는 보고서 기준표에 적었다.
"""

from __future__ import annotations

# (id, 기대 단계, 본문)
WARN: list[tuple[str, str]] = [
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
]

ALL: list[tuple[str, str, str]] = (
    [(i, "warn", t) for i, t in WARN] + [(i, "reject", t) for i, t in REJECT] + [(i, "offtopic", t) for i, t in OFFTOPIC]
)
