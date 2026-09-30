# 규칙 (모든 에이전트: Claude, Codex)

이 파일이 규칙 원본이다. Codex는 이 파일을, Claude Code는 `CLAUDE.md`(이 파일을 가져옴)를 읽는다.

## 출처와 범위

- 이 저장소의 코드와 데이터는 본선 현장에서 새로 만든다. 옛 프로젝트 폴더(`neumann/`)나 옛 코드를 열거나 복사하지 않는다.
- 참고 자료는 로컬 기획서 폴더(`C:\Users\User\Desktop\노이만_본선자료\기획서\`)뿐이다. 읽기만 하고 저장소로 복사하지 않는다. 기준 문서는 `00_구현_계획서.md`다.
- 공개 데이터·모델 원본은 `C:\Users\User\Desktop\노이만_본선자료\공개자료\`에 있다. 경로는 `.env`로 받고, 원본은 수정하지 않는다.
- 폴더를 통째로 복사해 버전을 만들지 않는다. 브랜치를 쓴다.

## 비밀값 (공개 저장소다)

- API 키·토큰·`.env` 내용을 파일, 커밋, 커밋 메시지, 로그, 보고서, 테스트 fixture 어디에도 쓰지 않는다.
- `.env`를 열거나 출력하지 않는다(`cat`·`type`·`Get-Content`·Read 도구 모두). 환경변수 전체를 출력하지 않는다(`env`, `printenv`, `set`, `Get-ChildItem env:`).
- 키가 있는지 확인할 때는 참·거짓만 본다.
  `python -c "import os; print(bool(os.getenv('OPENAI_API_KEY')))"`
- 코드는 비밀값을 환경변수(`.env`는 설정 로더가 읽음)로만 받는다. 코드에 기본값으로 넣지 않는다. 예외 메시지·로그에 요청 헤더나 설정 객체 전체를 찍지 않는다.
- 테스트는 `mock` provider로 돈다. 실제 API 호출은 과제 지시문이 허락한 경우만 한다.
- `.env.example`에는 키 이름만 두고 값은 비운다. 새 설정 키를 만들면 여기에 이름을 추가한다.
- `git add`는 파일을 지정해서 한다(`git add -A`·`git add .` 금지). `git add -f`로 무시 파일을 넣지 않는다.
- 훅을 우회하지 않는다(`--no-verify` 금지). 훅이 막으면 원인을 고친다.
- 비밀값이 커밋·push·로그에 들어갔으면 즉시 작업을 멈추고 PM(대표)에게 알린다. 키는 폐기하고 새로 발급하는 것이 먼저다. 이력만 지우는 것으로는 안 된다.

- **실제 OpenAI 호출 제한(대표 상시 규칙):** OpenAI API는 실제 서비스(사람이 쓰는 8010·공개 서버)와 태그급 성공 뒤 대표가 승인한 확인 테스트에서만 쓴다. `NEUMANN_LLM_PROVIDER=openai`와 `NEUMANN_LIVE_TESTS=1`은 PM이 대표 승인을 받은 과제에서만 켠다. 개발·빌드·검증·단위 테스트·측정은 mock이나 로컬로 한다. 설정 기본 provider는 mock이다. 실제 호출은 `NEUMANN_LIVE_LLM_OK=1`이 있는 프로세스에서만 열린다(SEC-3). 이 플래그는 실서비스 서버 기동 명령과 대표 승인 확인 테스트에만 준다. 사용자·시스템 환경변수에 provider·모델·플래그를 영구로 넣지 않는다. 구독(Claude·Codex) 에이전트가 만든 오프라인 결과를 제품 데이터에 쓰면 생성 방식을 "Claude/Codex 오프라인"으로 표기한다

## 올리지 않는 것

- `.env`, `data/`, 모델 가중치, 색인, 캐시, parquet, 에이전트·Codex 실행 로그. `.gitignore`와 `scripts/verify.py`가 막는다.
- 기획 키트 원문(기획서·부록)은 저장소에 올리지 않는다.

## git

- 커밋은 작게 한다. 메시지 앞에 과제 ID(`[E3-L1] …`), 끝에 실제 검증 결과 한 줄과 실제 빌더 모델을 적는다(인계 주력 `builder: codex-gpt-6.1-sol`, 난제에 Astra를 썼으면 그 모델을 적는다).
- main 병합과 push는 PM만 한다. push는 **주요 에픽마다**: 에픽 과제가 검증을 통과해 main에 병합됐을 때와 태그(`v0`~`v3`, `v3.x`, `final`)를 찍을 때. push 전에 `python scripts/verify.py`가 통과해야 한다.
- PM은 병합할 때마다 `docs/HANDOFF.md`를 갱신한다. Claude 한도가 다 되면 Codex가 이 문서로 이어받는다.
- 계약(`contracts/`, `src/neumann/models.py`)은 추가만 한다. 바꾸려면 PM 승인을 받고 `docs/decisions.md`에 한 줄 남긴다.
- 자기 소유가 아닌 폴더는 고치지 않는다(아래 표). 다른 에이전트의 프로세스를 종료하지 않는다.

| 경로 | 주인 |
|---|---|
| 루트 파일, `contracts/`, `docs/`, `scripts/verify.py`, `.githooks/`, `.claude/` | PM (E0) |
| `src/neumann/models.py`, `src/neumann/config.py`, `tests/fixtures/` | PM (E0) |
| `src/neumann/sources/`, `scripts/collect*` | E1 |
| `src/neumann/index/`, `scripts/build_index*` | E2 |
| `src/neumann/analyze/`, `src/neumann/llm.py`, `src/neumann/pipeline.py` | E3 |
| `src/neumann/api/`, `src/neumann/webui/` | E4 |
| `eval/` | E5 |
| `scripts/precompute_demo*` | E6 |
| `tests/` (fixtures 제외) | 각 에픽 |

## 품질과 정직성

- 검증은 빌더와 다른 모델이 한다(Opus 빌드 → Sonnet 검증). 검증자는 빌더 코드를 쓰지 않고 완료 기준을 다시 잰다. 대표의 2026-09-30 Codex 인수 지시로 개발 주력은 `gpt-6.1-sol`, 독립 검증은 `gpt-6-sol`이다. 어려운 개발 과제에만 구독 Astra를 배정할 수 있다. 제품 Astra 금지는 그대로이며, `verify` 통과가 병합 조건이다.
- 제품 분석은 LLM(`gpt-6.1-sol`)이 주력이다(결과의 generator 값 `astra`는 계약 이름일 뿐 모델이 아니다). **astra 모델은 쓰지 않는다(대표 지시)**: 모델명에 astra가 있으면 `NEUMANN_ALLOW_ASTRA=1`이 없는 한 코드가 sol로 바꾼다. 규칙은 API 실패·시간 초과 때만 쓰는 비상 경로다(예외 하나: 입력 분량 경고 단계에서 LLM이 0장이면 "분야 수준 참고" 규칙 카드, decisions 23:0x). 비상 경로로 돌면 결과의 `status`와 화면에 표시한다.
- 테스트 없는 기능은 완료가 아니다. 검사기는 기능을 실제로 검사해야 한다(항상 통과하는 검사 금지).
- 실패를 숨기지 않는다. 폴백으로 돌면 결과와 화면에 표시한다.
- 근거 없는 문장을 출력하지 않는다. 인용은 원문 오프셋과 글자 단위로 같아야 한다.
- LLM은 인용문을 직접 쓰지 않는다. 발췌 id와 줄 번호만 돌려받고, 인용 문자열은 코드가 원문에서 잘라 붙인다.
- 규칙으로 합성한 결과를 LLM 생성이라고 쓰지 않는다.
- 리뷰어 신원 필드는 두지 않는다. 개인정보는 마스킹한다.
- 스펙대로 못 만들고 폴백으로 물러나면, 그 세션 안에 `docs/decisions.md`에 한 줄 남긴다.

## 빌더

- 개별 빌더·검증자는 하위 에이전트를 띄우지 않는다. 대표가 명시한 병렬 개발을 위해 PM과 실행 관리자는 독립 작업을 배정할 수 있다. 빌더는 자기 과제를 끝까지 직접 쓰고, 세션을 끝내기 전에 커밋한다.
- 보고서: 무엇을 했나, 완료 기준별 측정값(명령과 출력), 못 한 것, 다음.
