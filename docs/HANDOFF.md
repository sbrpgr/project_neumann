# 인계 문서

PM이 병합할 때마다 갱신한다. Claude 한도가 다 되면 이 문서를 Codex에 주고 PM 역할을 넘긴다.

## 지금 상태 (2026-09-30 18:35)

- 단계: E0(골격) 일부 완료. 제품 코드 0줄. 태그 없음. **push 안 함**(E0 첫 push는 대표 확인 뒤).
- 이 문서까지 구축 세션이 썼다. 이후는 PM 세션("로컬 세팅")이 이어받는다.

### 끝낸 것 (main)

| 항목 | 파일 |
|---|---|
| 비밀값·데이터 차단 | `.gitignore`, `.gitattributes`, `.env.example`(비밀값 칸 비움) |
| 검증 러너 | `scripts/verify.py`: 키 형태 문자열, `.env`·환경변수에 든 실제 키 값의 원문 유출, 금지 파일, 5MB 초과, `.env.example` 빈 값, 계약 스키마, pytest(테스트 없으면 건너뜀) |
| git 훅 | `.githooks/` pre-commit(스테이징)·commit-msg·pre-push(추적 파일+커밋 메시지). `git config core.hooksPath .githooks` 설정됨 |
| 에이전트 규칙 | `AGENTS.md`(원본), `CLAUDE.md`(`@AGENTS.md`), `.claude/settings.json`(.env 읽기·편집 거부, 강제 add·훅 우회·force push 거부, 키트 폴더 읽기 허용) |
| 계약 | `contracts/premortem_response.schema.json`, `contracts/ui_view.schema.json`(키트 원본 그대로) |
| 문서 | `README.md`, `pyproject.toml`(의존성만, 빌드 설정 없음), `docs/decisions.md` |

- 확인: 심은 유출 6종(키 패턴, .env 값 복사, .env 강제 add, 6MB, safetensors, 메시지 토큰)을 모두 차단했다. 가짜 키를 넣은 실제 커밋은 훅이 거부했다.
- GitHub 원격: 시크릿 스캐닝·푸시 보호 켜져 있음(읽기로 확인). 기본 브랜치는 빈 저장소라 `master`로 표시됨. 첫 push 때 `main`을 올리면 바뀐다.

### 키·.env 상태

- `OPENAI_API_KEY`는 **Windows 사용자 환경변수**에 있다(참·거짓으로만 확인). `.env`에는 그 줄을 주석 처리해 빈 값이 키를 가리지 않게 했다.
- 로컬 `.env`(커밋 안 됨)에는 `NEUMANN_PSEUDONYM_SALT`(생성해 넣음), `NEUMANN_EMBED_MODEL`·`NEUMANN_RAW_DIR`(키트 `공개자료/` 경로)가 있다.
- `verify`는 환경변수의 실제 키 값도 읽어 저장소 파일·커밋 메시지에 원문이 있는지 찾는다(값은 출력하지 않음).

### 못 끝낸 것 (계획서 §4 E0 기준)

1. `src/neumann/models.py`·`config.py`와 패키지 골격
2. `tests/fixtures/` 공용 가짜 데이터(Work·ReviewEvent·Excerpt·RiskCard, 계약 통과)
3. 데모 계획서 3건(키트 `부록/데모입력/`) + 음성 대조 입력(무관한 글) 1건
4. `docs/tasks/` W1 지시문 7건
5. Codex 인계 준비 시험 실행(§5.6)
6. E0 첫 push(대표 확인 필요)

## PM에게 넘기는 메모

- **설정 로더 요구사항:** 환경변수 > `.env` 순서. pydantic-settings 기본 우선순위가 이렇다. `load_dotenv(override=True)`는 쓰지 않는다. 키 필드는 `SecretStr`로 받아 repr·로그에 값이 안 나오게 한다. 테스트로 "`.env`에 빈 `OPENAI_API_KEY=`가 있어도 환경변수 값이 이긴다"를 확인한다.
- **AGENTS.md와 개정 계획서 §10의 차이(고치지 않았다, PM 판단):** push는 에픽 과제 종료·태그 때, PM은 병합마다 `docs/HANDOFF.md` 갱신, 인계 뒤 검증은 astra 빌드 → sol 검증, 제품 분석은 astra 주력(비상 경로면 status·화면 표시), 커밋 끝줄 빌더 라벨은 `builder: claude-opus-5.5` 형식. 지금까지 커밋은 `builder: claude-opus (PM)`로 적었다.
- **병렬 충돌 방지 제안:** 빌더를 띄우기 전에 `src/neumann/{sources,index,analyze,api}/__init__.py`와 에픽별 테스트 폴더를 E0에서 먼저 만들어 두면 같은 `__init__.py`를 여러 브랜치가 만드는 충돌이 없다. `eval/`을 패키지로 쓰면 `pyproject.toml`의 pytest `pythonpath`에 `"."`를 더한다.
- **계약 메모:** `premortem_response.schema.json`은 느슨하다(`risk_cards` 등이 자유 객체). 실제 불변식은 `models.py`로 강제해야 한다(`부록/설계/02_data_schema.md` §1·§3·§6). `ui_view.schema.json`은 화면 계약이라 엄격하다.
- **verify 확장 자리:** E5-L0 근거 연결 검사기가 생기면 `scripts/verify.py`에서 부른다(계획서 §4 E0 "근거 연결 검사").
- **옛 `neumann/` 폴더:** 홈 아래 5단계 안에서 찾지 못했다. 그래서 `.claude/settings.json`에는 흔한 위치 세 곳(바탕화면, 홈, 문서)만 막아 두었다. 실제 위치를 알면 그 경로를 추가한다.
- **Codex 설정 파일(`~/.codex/config.toml`)은 대표 개인 설정이라 고치지 않는다.** 모델은 명령마다 `-m`으로 지정한다.

## 인계 받는 쪽이 지킬 것

- 규칙은 `AGENTS.md`. 병합 전 `python scripts/verify.py` 통과가 게이트다.
- 기준 문서: `C:\Users\User\Desktop\노이만_본선자료\기획서\00_구현_계획서.md`
- `.env`와 환경변수 값은 열거나 출력하지 않는다. 키가 있는지는 참·거짓으로만 확인한다.
