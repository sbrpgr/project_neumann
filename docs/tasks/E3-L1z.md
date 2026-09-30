# E3-L1z — 규칙 판정(비상 경로) 한국어 조사·"~인지" 오탐 정리

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5
- 목표 시간: 30분
- 소유: `src/neumann/analyze/fitness.py`, `tests/e3/test_fitness*.py`, 보고서
- 실제 OpenAI 호출 금지(mock)

## 배경 (E3-L1x 검증에서 남긴 한계)

1. **`~인지 과제`·`~인지 기능` 오탐.** 예를 들어 "효과적인지 과제별로"가 신경과학으로 잡힌다. `_NEURO_KO`의 인지 복합어 앞에 `(?<![가-힣])`를 붙이면 된다.
2. **영어 약어 뒤 조사.** `EEG와`·`fMRI로`·`GNN을`처럼 한글 조사가 붙으면 `\b`가 한글을 단어 문자로 봐서 못 잡는다. 파일 전체의 영어 패턴에 해당한다. 경계를 `(?<![A-Za-z0-9])…(?![A-Za-z0-9])`로 바꾸는 것을 검토한다.
3. **AI 용어.** `neuromorphic`·`neuro-symbolic`은 AI 쪽 용어다. `neuro(?!morphic|-?symbolic)\w*`로 좁힌다.

## 만들 것

- 위 세 가지를 고치고 회귀 테스트를 추가한다.
- 판정 로직(fit·unfit·uncertain)은 분야를 뺀 반환값이 main과 같아야 한다. 템플릿·예시·데모 계획서와 무작위 입력 200건 이상으로 대조한다.
- 모든 템플릿과 예시의 분야를 수정 전후 표로 보고서에 적는다.

## 완료 기준

1. `pytest tests/e3 -q` 통과
2. `python scripts/verify.py` 통과(venv 파이썬, `NEUMANN_LLM_PROVIDER=mock`)
