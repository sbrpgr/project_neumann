# E5-L1a — DISAPERE 골드와 Macro-F1 채점기 (앞당김, E1-L1 DISAPERE 수집 포함)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5
- 목표 시간: 60분
- 소유: `src/neumann/sources/disapere.py`, `eval/`(패키지), `tests/e5/`, `tests/e1/test_disapere.py`

## 읽을 것

- `04_평가_명세.md` §0.6, §1.2(참조선: 사람 간 상한 0.725), §2.1(Macro-F1 정의·분모 규칙), §3.1(DISAPERE 골드 148건 매핑·합의 규칙), §6(함정)
- `부록/설계/03_risk_taxonomy.md`: R0~R9와 DISAPERE 라벨 매핑 근거
- `부록/평가/05_eval_protocol.md`, `부록/평가/label_schema.json`, `부록/평가/labeling_guide.md`
- `공개자료/data/disapere/README.md`, `LICENSE.md`(CC BY-NC 4.0: 원본과 가공본을 커밋하지 않는다)

## 만들 것

1. `src/neumann/sources/disapere.py`: `DISAPERE.zip`을 읽어 리뷰 단위 문장과 사람 라벨을 돌려준다. 원본은 수정하지 않는다
2. 골드 구성(§3.1 규칙 그대로): 과반 합의 골드 **148건** → 공유 데이터 폴더 `data/eval/disapere_gold.jsonl`, 골드가 아닌 튜닝용(약 358건) → `data/eval/disapere_dev.jsonl`. 파일별 건수·sha256을 `data/eval/disapere_manifest.json`에
3. `eval/macro_f1.py`
   - 입력: 예측 JSONL(`review_id`, 예측 risk_code 집합, `generator`: rule/astra/mock), 골드 JSONL
   - 출력: 클래스별 P/R/F1, Macro-F1, Micro-F1, n, 부트스트랩 95% 구간(2,000회, 시드 고정), 골드에 없는 클래스(R3·R4·R8·R9 등)는 규칙대로 제외하고 제외 목록을 출력에 명시
   - CLI: `python -m eval.macro_f1 --pred <파일> --gold <파일> --out <json>`
4. 빈도 기준선 예측을 만들어 채점한다(참조선)
5. E3가 나중에 astra 추출 결과를 이 채점기에 넣는다. 예측 JSONL 형식을 보고서에 명확히 적는다

## 완료 기준

1. 골드 건수 148(아니면 이유와 실제 건수)
2. 채점기 단위 테스트: 손으로 계산한 작은 예제와 일치, 완벽 예측 1.0, 전부 오답 0.0, 빈 예측 처리
3. 빈도 기준선 Macro-F1과 구간 산출(보고서에 수치)
4. `python -m pytest tests/e5 tests/e1/test_disapere.py -q`, `python scripts/verify.py` 통과. DISAPERE 원본·가공본은 커밋하지 않는다
