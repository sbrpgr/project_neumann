**PASS**

# E4-L2e 검증 — 다중 사용자 부하 시험 스크립트·보고서

- 검증자: Claude Sonnet 5.5 (빌더 Claude Opus 5.5와 다른 모델) · 짧은 검증
- 대상: 브랜치 `task/E4-L2e` @ `1b0c5e6`, worktree `.claude/worktrees/s2-E4-L2e`. 검증 뒤 worktree `git status` 깨끗(파일 남기지 않음).
- 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `OPENAI_API_KEY` 없이(`env -u`) 실행. 실제 OpenAI 호출 0. GPU 재측정은 N=2 한 라운드만(서버 8148).

## 판정 표

| # | 확인 | 실행한 것 | 실제 결과 | 판정 |
|---|---|---|---|---|
| ① | 실제 OpenAI 차단 | 코드 읽기: `src/neumann/llm.py`에서 OpenAI를 부르는 곳은 `OpenAIProvider.complete_json`의 `responses.create` 한 곳뿐(`api.openai.com`·`chat.completions` 직접 호출 없음). 스크립트 3개가 시작 때 `require_mock_env()`(mock 미명시면 `SystemExit`) → `block_openai()`(그 메서드를 `RuntimeError`로 교체) → `os.environ.pop("OPENAI_API_KEY")`; 서버 자식 프로세스는 환경에서 키를 뺀다. 지연 mock은 `MockProvider` 상속 | 키 없는 환경에서: provider=`openai`로 실행 → "NEUMANN_LLM_PROVIDER=mock을 명시하고 다시 실행하라" 종료. provider 미설정도 같은 종료. `block_openai()` 뒤 가짜 키로 만든 `OpenAIProvider.complete_json(...)` → `RuntimeError: E4-L2e 부하 시험은 실제 OpenAI를 부르지 않는다`(네트워크로 안 나감). 단위 시험 `test_block_openai_refuses_real_calls`는 `client=object()`로 만들어 차단이 없으면 `AttributeError`라 실패한다(항상 통과하는 시험 아님). 8010·8020은 실행기·서버 양쪽에서 `FORBIDDEN_PORTS`로 거부 | 통과 |
| ② | N=2 표본 직접 실행 | `python scripts/loadtest_multiuser.py server --n 2 --port 8148 --out <scratch> --server-log <scratch>` (8148, 끝나면 종료) | 성공 2/2, 오류 0+단계 0, 지문 불일치 0, 검색상태 섞임 0. 건별 p50/최대 **52.53 / 57.11초**, 전체 57.34초, 처리량 **2.09건/분**, 임베딩 락 대기 0.0, 검색 단계 최대 0.107초, GPU 1,227MiB(Δ+8), RAM 작업 집합 3,136MB, 스레드 55, 세마포어 대기 최대 0.026초. 단계별 평균: fitness 4.5 / query_axes 2.8 / search 0.08 / extract 6.1 / synthesize 10.0 / expected_review 10.5 / checklist 10.4 / semantic 10.4초. 보고서 N=2 서버 행(p50 54.87·최대 57.09·처리량 2.09·GPU 1,229(+8)·스레드 55·단계별 값)과 형태(열·단계 표)와 수치 범위 일치. 종료 후 8148 LISTEN 없음(TIME_WAIT만), `nvidia-smi` 0MiB, 8020(타인 서버)은 건드리지 않음 | 통과 |
| ②′ | 보고서 표 ↔ 원자료 JSON | 두 JSON에서 라운드별 값을 다시 뽑음 | N=1~12(본 측정)·16·24·48 모두 성공=N, 오류 0, 지문 불일치 0, 섞임 0. p50/최대·처리량·GPU·`max_active_pipelines`(48에서 40, 대기 최대 54.4초)가 보고서 표와 일치. `server_stopped.port_closed=True` 두 번 | 통과 |
| ③ | 권장값 6의 근거·한계 서술 | 보고서 "결론"·"OpenAI 한계"·"한계"·"결정 6" 읽고 원자료와 산수 대조 | 정직하다: OpenAI 실제 지연·TPM·RPM·429를 **재지 않았다**고 세 곳(결론, OpenAI 한계, 못 한 것)에 명시. 6은 "본 측정 12의 절반"이라는 여유 규칙이고 TPM 실측이 아님을 밝히며, TPM 한도별 조정 공식(`floor(TPM÷12만)`, `RPM÷38`)과 "PM이 대시보드에서 확인"을 붙였다. 확인 전이면 공개 기본 4를 유지해도 된다고까지 적었다. 산수 재현: 입력 약 32.5만 자 ÷ 4 ≈ 8만 토큰 × 60/55 ≈ 9만/좌석·분, ×1.3 ≈ 12만, 6석 0.53M(0.7M), 50만 → 4 — 맞다. 건별 55초가 지시값 가정이라 실제가 더 길 수 있다는 것, mock 응답이 규칙 결과라 호출 수가 다를 수 있다는 것도 적었다. 사소한 흠은 아래 "고칠 것 1·2" | 통과(사소한 서술 보완 권고) |
| ④ | 단위 시험 | `pytest tests/e4 -q -k loadtest` | `13 passed, 199 deselected` (worktree). 현재 main(`42f8cc1`, SEC-3 등 반영) 파일을 스크래치에 풀고 빌더 파일만 덧씌워도 `13 passed`(훅 `main.MAX_CONCURRENT`·`_sem`·`pipeline.make_llm`·`OpenAIProvider` 그대로 유효). 시험 내용 확인: 겹침(전체 < 0.8×합)·timeout 상한·지문 변경·상태 섞임 검출 등 조작 입력으로 실패하는 단언이 있다 | 통과 |
| ④′ | verify.py | 빌더 브랜치에서 `python scripts/verify.py` | `1098 passed, 26 skipped in 106.01s` · 보안 파일 380개 · 계약 2개 · `verify 통과` (빌더 보고 1098/26과 같음) | 통과 |
| ⑤ | 소유·크기·비밀 | `git diff main...task/E4-L2e --stat`, `git ls-tree -l`, grep | 변경 9개 전부 소유 안: `scripts/loadtest_multiuser{,_app,_lib}.py`, `tests/e4/test_loadtest_multiuser.py`, `docs/reports/E4-L2e{.md,_results.json,_results_over12.json,_run.txt,_run_over12.txt}`. `contracts/`·`src/neumann/models.py`·`src/` 변경 0, 데이터·`.env` 추가 0. 최대 파일 201KB(5MB 초과 0). 원자료 JSON·run 출력에서 `sk-…`·`api_key`·`Bearer`·`secret`·`password`·`@gmail`·로컬 절대경로 0건(보고서 재현 명령의 `_COMMON.md` 공개 경로 두 줄과 "OPENAI_API_KEY를 뺀다" 서술뿐). `git merge-tree` 결과 main과 충돌 없음 | 통과 |

## 고칠 것(병합을 막지 않는 서술 보완, 빌더/PM 재량)

1. **호출 수·입력 크기 범위가 원자료보다 좁게 적혔다.** 보고서 "OpenAI 한계"는 "LLM 호출 32~36회, 입력 28만~41만 자(평균 32.5만)"인데, 원자료(서버 121건·직접 33건)는 호출 **29~43회(평균 35.5)**, 입력 **25.0만~41.0만 자(평균 32.6만)**이고 32~36에 든 것은 54%뿐이다. 9만 토큰/좌석 공식은 평균 기준이라, p95(43회·약 41만 자 ≈ 10만 토큰)에서는 좌석당 약 25% 더 든다. 범위를 원자료대로 고치고 "공식은 평균 기준, 꼬리는 +25%"를 한 줄 덧붙이면 정직성이 더 낫다.
2. **"OpenAI 속도 제한일 가능성이 크다"(결론 표·결정 6)는 근거가 없다.** 이 계정의 TPM 등급을 모르고 재지도 않았으므로 "가능성이 크다"보다 "미확인 — 확인 전까지 4~6 사이에서 보수적으로"가 맞다. 이미 뒤 문단이 조건부로 쓰여 있어 결론 표 문구만 조정하면 된다.
3. (참고, 병합 후 PM) 이 시험 서버는 `848bd50` 기준 main 앱이다. E4-L2c 서빙 층·작업 API가 main에 들어가면 `scripts/loadtest_multiuser_app.py`(`main.MAX_CONCURRENT`·`main._sem` 교체)가 그대로 맞는지 `pytest tests/e4 -k loadtest`와 N=2 서버 표본으로 한 번 확인할 것. 현재 main에는 아직 `serving.py`가 없고, 현재 main + 빌더 파일 조합의 단위 시험은 통과했다.

## 검증자 기록

- N=2 실행 산출물(JSON·서버 로그)은 검증자 스크래치 폴더에만 두었고 저장소에는 남기지 않았다.
- 병합 가능성 확인에 `git merge-tree --write-tree`를 한 번 썼다(ref·작업 트리는 안 바뀌고 로컬 객체 저장소에 tree 객체만 생긴다). 그 밖의 git 쓰기·`git stash`·`.env` 열기·키 값 출력·하위 에이전트는 없었다.
