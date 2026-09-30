# DISP-1 — 생성 방식 표시 이름: "astra" → "LLM(실제 모델명)"

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5
- 목표 시간: 40분
- 소유: `src/neumann/api/view.py`, `src/neumann/webui/index.html`의 표시 문자열, `src/neumann/api/export.py`의 README·리포트 문구, `eval/report_card.py`의 표시 문구, 관련 테스트
- 실제 OpenAI 호출 금지(mock)
- **E4-L3d(디자인)·E4-L2f(내보내기)와 같은 파일을 만진다.** 구축 세션이 순서를 정한다(그 과제에 합쳐도 된다)

## 배경

- 계약(`models.Generator`)의 값 `astra`는 "제품 LLM"이라는 뜻의 **이름**이다. 실제 모델은 카드·manifest의 `model`에 있다(지금은 `gpt-6.1-sol`).
- 대표 지시는 "astra 모델을 쓰지 마라"이다. 그런데 화면·ZIP·리포트에 "astra"가 보이면 지시와 어긋나 보인다.
- 계약은 추가만 할 수 있으므로(AGENTS.md) **저장 값은 그대로 두고 사람이 보는 표시만 바꾼다.**

## 만들 것

1. 표시 매핑 하나를 한 곳에 둔다(예: `view.py`의 `generator_label(generator, model)`):
   - `astra` → "LLM (gpt-6.1-sol)"(모델명이 없으면 "LLM")
   - `rule` → "비상 규칙"
   - `mock` → "mock(시험용)"
2. 화면(카드 배지, 단계 표, 요약), 내보내기 README·`neumann_report.md`·`ai_context.md`, 리포트 카드의 표시 문자열을 이 매핑으로 바꾼다.
   - JSON 필드 값(`generator: "astra"`)은 바꾸지 않는다. JSON 문서 설명에 "astra는 계약 이름, 실제 모델은 model"을 한 줄 적는다.
3. 테스트
   - 화면 뷰와 내보내기 사람용 문서에 "astra" 글자가 없다(JSON 값 제외).
   - 규칙 카드를 LLM이라고 쓰지 않는다.
   - mock은 "mock"으로 드러난다.

## 완료 기준

1. `pytest tests/e4 tests/e5 -q` 통과
2. mock 서버 화면 스크린샷에 "LLM (…)" 배지가 보이고 "astra"가 없다
3. `python scripts/verify.py` 통과(venv 파이썬, `NEUMANN_LLM_PROVIDER=mock`)
