# README-FINAL — 제출용 한국어 README

- 작업 브랜치: `codex/readme-final`; 시작 HEAD: `5093383`.
- 빌더: `codex-gpt-6.1-sol`. 하위 에이전트 위임 없이 직접 작성·검사했다. 이 보고서는 빌더 검증이며 별도 모델의 독립 검증을 주장하지 않는다.
- 변경: `README.md`, 이 보고서만. 제품 코드·계약·설정·다른 worktree는 수정하지 않았다. main 병합·push·stash는 하지 않았다.
- 실제 제품 OpenAI 호출 없음. 시험 환경에서 `OPENAI_API_KEY`, `NEUMANN_PSEUDONYM_SALT`, `NEUMANN_LIVE_LLM_OK`, `NEUMANN_LIVE_TESTS`를 제거하고 provider를 mock으로 지정했다. 환경변수 값 출력·단언, `.env` 읽기 없음.

## 무엇을 했나

초기 v0 중심 README를 제출용 한국어 문서로 재작성했다. 한 줄 소개와 대표 에이전트 정의를 유지하고, 연구 착수 전 공백과 입력 → 분석 → 재탄생 → 연구자 수정 확정 → 도구 점검·수정·재검사 → 최종 초안의 Mermaid 흐름을 설명했다.

구성에는 AI4S OpenReview 기본 코퍼스, bge-m3+BM25, 원문 오프셋 기반 근거 관문, Z3/Pint/NetworkX, HMAC-SHA256을 포함했다. 도구 통과와 과학적 타당성, 개별 서명과 산출물 결합을 구분했다. mock 기본 실행과 승인된 라이브 설정, 개인정보·보안 원칙, 한계·로드맵을 정리했다.

## 완료 기준별 측정

모든 Python 명령의 실행 파일은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `PYTHONPATH=src;.`였다. 테스트는 비밀값을 제거한 환경에서 실행했다. 전체 `scripts/verify.py`는 과제 지시에 따라 실행하지 않았다.

| 완료 기준 | 방법·명령 | 실제 결과 |
|---|---|---|
| 소개·원문 정의·필요성 | 기존 README의 대표 정의와 재작성 문안 대조 | 정의 문장 그대로 유지; 착수 전 계획 점검 공백 설명 |
| 여섯 단계 흐름 | Mermaid와 단계별 설명 대조 | 입력·분석·재탄생·수정 확정·최종 점검·최종 초안 연결 |
| 구성과 정직한 한계 | `config.py`, `final_tools.py`, `finalize.py`, `signing.py`와 대조 | 검색 강등, mock, 원문 근거, 제한된 검사, 임시 HMAC 키의 재기동 한계 명시 |
| 의존성 명령 | `uv pip install --python $python -r pyproject.toml --extra dev --extra finalization --cache-dir data/readme-final/uv-cache --dry-run --offline` | `Resolved 94 packages`, `Checked 94 packages`, `Would make no changes`; 설치 변경 없음 |
| fixture 색인 | `& $python scripts/build_index.py --source fixtures --out $env:NEUMANN_INDEX_DIR --no-embed` | 가짜 논문 6편·심사평 12건, 문장 44개; 메모리·디스크 오프셋 각각 `44/44`; 임베딩 없는 강등 표시 |
| CLI mock 분석 | `& $python -m neumann.pipeline tests/fixtures/plans/plan.md --provider mock --backend index` | 종료 코드 0; `status=degraded`, mock 카드 2장, 원문 인용 `10/10` 일치, search 단계 `lexical_only` |
| 서버 실행·상태 | `& $python -m uvicorn neumann.api.main:app --host 127.0.0.1 --port 8136`; `(Invoke-RestMethod -Uri http://127.0.0.1:8136/health).pipeline.state` | 서버 기동; `connected` |
| 관련 mock 회귀 | `& $python -m pytest tests/e0/test_finalization_integration.py tests/e3/test_final_tools.py tests/e3/test_finalize.py tests/e4/test_finalize_api.py tests/e4/test_payload_signing.py -q` | `95 passed in 4.85s`, 종료 코드 0 |
| headless 전체 흐름 | Playwright Chromium `launch(headless=True)`; 8136 mock 서버, fixture 계획서 입력 → 위험카드 → 수정안 → 직접 수정 → 통합본 → 수정 확정·검증 → Markdown 다운로드 | 위험카드 2장; revise·assemble·finalize HTTP 모두 200; `generator=mock`, `status=partial`, `origin=server_signed`, 서명 존재; 최종 화면/API/다운로드 문안 일치; 최종 확정 POST 1회 |
| 시험 서버 종료 | 직접 기동한 PID 39028만 `Stop-Process -Id 39028`; 해당 포트 연결 조회 | `8136 test server stopped`; 다른 프로세스 종료 없음 |
| 평가 수치 참조 | README 평가 절 검사, 별도 numbers-audit worktree 파일 읽기 | 평가 수치 직접 기재 없음; `docs/reports/numbers_frozen.json` 단일 참조; 미확정·모델·표본 한계 명시 |
| 문서 정적 점검 | Python으로 정의 원문·Mermaid 연결·필수 구성·코드펜스·평가 숫자 리터럴·로컬 링크 검사; `git diff --check` | 모두 PASS; 빠진 링크는 별도 작업의 `numbers_frozen.json` 하나뿐; 공백 오류 없음 |

브라우저 점검은 외부 페이지·사용자 Chrome·데스크톱·탭 목록 도구 없이 로컬 mock 서버와 새 headless Chromium 컨텍스트만 사용했다. POST 응답과 DOM의 최종 텍스트를 비교하고, 내려받은 Markdown에 최종 텍스트·변경 목록·잔여 쟁점이 있는지 확인했다. 스크린샷은 git에서 제외되는 `data/readme-final/final-flow.png`에 남겼다. 화면 구현을 변경하지 않았다.

## 실패와 수정한 검증 절차

- 첫 의존성 점검은 기본 uv 캐시 경로의 접근 제한으로 실패했다. 쓰기 가능한 로컬 `data/readme-final/uv-cache`를 명시하고 재실행해 통과했다. README에 통과한 명령을 반영했다.
- 첫 브라우저 검사 스크립트는 다운로드 단언에서 실패했다. PowerShell stdin의 UTF-8 인코딩을 명시하고, 불필요한 외국어 문자열 부재 단언을 제거한 뒤 다시 검사했다. 최종 텍스트 포함·한국어 감사 절 존재·화면/API 동일성 검사 모두 통과했다. 제품 코드는 고치지 않았다.
- 초기 패치 도구 호출은 같은 파일을 한 패치에서 삭제·추가하려다 거부됐다. 파일 삭제·추가를 순차 적용했다. 제출물의 내용과 최종 diff를 확인했다.
- 첫 평가 숫자 스캔은 `AI4S`·`e2e` 같은 식별자 안의 숫자까지 수치로 오인했다. 숫자 리터럴만 검사하도록 범위를 바로잡아 통과했다. 평가 수치를 직접 적지 않는 기준은 유지했다.

## 못 한 것과 다음

- 현재 worktree에는 `docs/reports/numbers_frozen.json`이 없다. `C:/Users/User/Desktop/project_neumann/out/codex/numbers-audit/docs/reports/numbers_frozen.json`을 읽기만 하여 평가 설명을 대조했다. 이 파일도 동결 전 초안이며 `merged`는 미확정, `live_full_flow`는 미측정이었다. 수치를 복사하거나 파일을 새로 만들어 확정하지 않았다. **PM이 숫자 작업 산출물을 병합한 뒤 참조를 완성해야 한다.**
- 라이브 기동 예시는 문서에만 적었고 실행하지 않았다. 실데이터 재수집·bge-m3 재빌드·새 가상환경 실제 설치도 하지 않았다. 준비된 환경의 오프라인 의존성 확인, fixture 색인, mock 흐름을 검증했다.
- mock 최종 결과는 `partial`이다. 라이브 전체 흐름 성공·과학적 검증 완료·예측 우위를 주장하지 않는다.
- 독립 검증과 main 병합·전체 verify·라이브 최종 확인은 PM의 후속 절차다.

## 커밋 차단과 인계

`git add -- README.md docs/reports/README-FINAL.md`와 `[README-FINAL]` 제목의 `git commit`을 현재 브랜치에서 시도했으나, 두 명령 모두 `.git/worktrees/readme-final/index.lock: Permission denied`로 실패했다. 사용자 지시의 .git 쓰기 허용 안내와 달리 실행 환경이 해당 경로 쓰기를 거부했다. 커밋·스테이징은 이루어지지 않았다. 권한 변경·훅 우회·다른 worktree 수정은 시도하지 않았다.

검토 가능한 두 문서와 변경 패치를 로컬에 남긴다. 패치 경로는 `data/readme-final/README-FINAL.patch`이며 README 변경과 새 보고서를 포함한다. PM은 쓰기 가능한 작업 환경에서 이 두 문서를 적용하고 `[README-FINAL]` 제목·실제 검증 결과·`builder: codex-gpt-6.1-sol`을 포함해 커밋할 수 있다. 대시보드에는 검증 완료와 커밋 권한 차단을 함께 보고한다.
