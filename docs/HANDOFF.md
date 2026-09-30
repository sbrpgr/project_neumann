# 인계 문서

PM이 병합할 때마다 갱신한다. Claude 한도가 다 되면 이 문서를 Codex에 주고 PM 역할을 넘긴다.

## ⚠ 최종 마감 (대표 지시): 발표자료 제출 10/01 09:00

| 시각 | 할 일 |
|---|---|
| ~07:00 | 발표 숫자 동결(v2 지표: 백테스트·Macro-F1·근거 연결률) |
| ~07:30 | 시연 영상 최종 녹화(E6-L3b, ffmpeg로 mp4), 프로토타입 주소(터널) 확정 |
| ~08:30 | 발표자료(키트 `발표자료/본선_발표자료.pptx`) 빈칸 10·11·12·13쪽 + 주소·영상 채우기 |
| 09:00 전 | PDF 저장과 제출 |

## Codex PM이 20:00에 이어받으면 할 일 (순서대로)

1. `docs/tasks/QUEUE.md` 최신 현황 요약을 읽는다. 검증 보고서(`docs/reports/<ID>.verify.md`)가 PASS인데 main에 없는 브랜치를 병합한다(`git merge --no-ff task/<ID>`, 검증 보고서도 커밋). PASS-조건부는 조건이 해소된 커밋이 있을 때만
2. **E3-L0**(v0 핵심): SEC-1 S-04·S-05 수정 커밋이 있고 검증 PASS면 병합. 검증이 없으면 `bash scripts/codex_task.sh verify E3-L0`(sol)
3. **v0 통합**: main에서 ① 파이프라인에 적합성(E3-L1c `assess_fitness`, 부적합이면 카드 0장·사유)·예상 심사평(E3-L1a `attach_expected_review(result, provider_llm_call(...))`)·체크리스트·2차 검증(E3-L1b `attach_checklist`·`attach_validation`) 연결(E3 소유 `pipeline.py`) ② `python scripts/verify.py` ③ 8010 서버를 main 체크아웃에서 재시작(지금은 `C:/Users/User/Desktop/pn_integ` 통합 worktree에서 떠 있음) ④ 데모 3건 실제 실행 + `eval.linkage.check_result` ⑤ 태그 `v0`(연결분까지 되면 `v1`) + push
4. 사전 계산본을 실제 파이프라인으로 재생성: `python scripts/precompute_demo.py --source pipeline` → 정적 폴백 재빌드(`scripts/build_static_site.py`)
5. Claude 빌더가 끊겨 미완인 브랜치는 `bash scripts/codex_task.sh build <ID>`로 이어서(기존 worktree를 자동으로 찾는다), 끝나면 `verify <ID>`(sol)
6. **하지 않는 것**: 평가 판정(21:40 뒤 Claude), 터널 공개(E4-L2c 비용 방어선 병합·확인 전 금지), 키트 원본 수정

## 21:40 이후: Claude·Codex 두 레인 동시 (대표 결정)

- 병합은 PM 한 명(21:40 뒤 Claude PM). 검증은 빌더와 다른 모델(Codex 빌드 → Claude Sonnet 검증 가능)
- 레인 나누기(소유 경로가 겹치지 않게): **Claude 레인** = E3 파이프라인·예상 심사평 연결, E4 화면, 백테스트 판정(Claude 전용), 발표자료. **Codex 레인** = E1-L1c(eLife 코퍼스 합치기 제안 반영), E2-L1·E2-L3(색인), 사전 계산본·정적 판·시연 영상(E6), 문서(E6-docs)

## 교대 일정 (대표 지시 2026-09-30)

- **20:00 Claude → Codex 교대.** Codex PM(`gpt-6-astra`)이 21:40까지 진행한다. **21:40 Claude 5시간 창 초기화 뒤 Claude가 되받는다.** 되받을 때도 이 문서와 `docs/tasks/QUEUE.md`로 한다.
- Codex PM 시작(대표): Codex 앱을 `C:\Users\User\Desktop\project_neumann`에서 열고, 모델 `gpt-6-astra`(추론 high)로 "`AGENTS.md`, `docs/HANDOFF.md`, `docs/tasks/QUEUE.md`를 읽고 PM을 이어받아라".
- Codex 빌더·검증: `bash scripts/codex_task.sh build <과제ID>`(astra), `bash scripts/codex_task.sh verify <과제ID>`(sol, 빌더와 다른 모델). 백그라운드로 여러 개 띄워도 된다. 인계 뒤 병합 조건은 `python scripts/verify.py` 통과와 sol 검증 PASS.
- **평가 판정은 Codex로 하지 않는다**(계획서 §5.7). 21:40 뒤 Claude가 한다. Claude로 못 하게 되면 §5.7 비상 판정.

## 지금 상태 (2026-09-30 18:58)

- 과제 현황과 다음 할 일은 **`docs/tasks/QUEUE.md`**가 기준이다
- main에 병합: E0·E0b·E5-L0·E5-L1a·E4-L0·E4-L2a. 모두 push됨
- `main.py`에 선택 라우터(export·upload·precomputed·templates·meta) 자동 연결. 모듈이 main에 들어오면 서버 재시작만 하면 붙는다. 상태는 `/health`의 `routers`
- 점검 서버 `http://127.0.0.1:8010`: E4-L0 빌더 worktree에서 띄운 **샘플 모드** 서버. v0 통합 뒤 main 체크아웃에서 다시 띄운다(`.claude/launch.json` 또는 E4-L2c의 `scripts/serve.py`)
- 사용량(18:52): Claude 5시간 창 17%, 주간 5%. 대표 방침: 20:00 전에 풀로 쓴다

## 도구·경로

- Python venv: `C:/Users/User/.venvs/neumann/Scripts/python.exe`. pip이 없으니 설치는 `uv pip install --python <venv python> <패키지>`. mcp SDK 2.2.0 설치됨
- 공유 데이터: `C:/Users/User/Desktop/project_neumann/data/`(processed·index·eval·cache·raw·precomputed·site·video)
- cloudflared: `C:/Users/User/tools/cloudflared/cloudflared.exe`. quick tunnel은 `tunnel --url http://127.0.0.1:<포트>`이고 재시작마다 주소가 바뀐다
- ffmpeg: `C:/Users/User/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.2-full_build/bin/ffmpeg.exe`
- Codex CLI: `%LOCALAPPDATA%\OpenAI\Codex\bin\<해시>\codex.exe`(최신 것을 `scripts/codex_task.sh`가 찾는다)

## 대표 지시 요약(누적)

- 제품: 연구 사전기획 단계용 에이전트 서비스. astra 주력, 규칙은 비상 경로
- 프로토타입 주소 = 로컬 라이브 서버를 터널로 공개(토큰 없이, 안정성 장치로 버틴다). 정적 판은 폴백
- 입력 화면에 AI for Science 템플릿 선택기와 "AI 활용 과학 연구 계획서 전용" 안내. 범위 밖 입력은 적합성 판정으로 막는다
- 발표자료에 프로토타입 주소와 시연 영상(주최측 요구)
- git push는 주요 에픽마다

## 기록 (2026-09-30 18:30, PM 세션 "로컬 세팅"이 이어받음)

- PM이 `AGENTS.md`를 개정 계획서에 맞춤(push는 주요 에픽마다, HANDOFF 병합마다 갱신, 인계 뒤 astra→sol 검증, astra 주력), 패키지 골격(`src/neumann/{sources,index,analyze,api}/__init__.py`, `eval/__init__.py`)과 pytest `pythonpath` 추가
- 과제 지시문: `docs/tasks/_COMMON.md`(공통) + W1 1차 `E0b`(모델·설정·fixture) · `E1-L0`(코퍼스) · `E4-L0`(API·화면) · `E5-L1a`(DISAPERE 골드·Macro-F1)
- 18:26 `models.py`·`config.py`(E0b 커밋 73a264b)를 main에 선병합(def820d). verify 통과(tests/e0 39개)
- 18:45 **E0 완료**: E0b 전체 병합(fixture·로더·데모 계획서, Sonnet 검증 PASS), `tests/conftest.py`(기본 mock), verify 훅 경고 수정 → **첫 push**
- 18:50 **E5-L1a 병합**(Sonnet PASS): DISAPERE 골드 148건(dev 358건), `eval/macro_f1.py`, 빈도 기준선 Macro-F1 0.3308 [0.2980, 0.3623]. 예측 JSONL 형식은 `docs/reports/E5-L1a.md`
- 나중에 챙길 것(리포트 카드 E5-L3): 사람 상한 0.725 설명 문구("29리뷰 leave-one-out")의 출처 확인·정리, R7 매핑 한계 각주
- 진행 중 빌더 7명(Claude Opus 5.5, worktree `.claude/worktrees/agent-*`, 브랜치 `task/<과제ID>`): E0b(fixture 계속), E1-L0, E4-L0, E5-L1a, E2-L0, E3-L0, E5-L0
- 대기: E1-L2 Retraction Watch(자리 나면). 빌더가 끝나면 Sonnet 검증(`docs/tasks/_VERIFY.md`) → 병합 → 에픽이면 push
- Codex 인계 시험 통과(18:21). 인계 명령은 계획서 §5.6
- 공유 데이터 폴더: `C:/Users/User/Desktop/project_neumann/data`(모든 worktree 공용, gitignore)

## 이전 상태 (2026-09-30 18:35 구축 세션 기록)

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
