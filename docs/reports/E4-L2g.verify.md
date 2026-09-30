# E4-L2g 검증 보고서 (검증자: Claude Sonnet 5.5)

대상: worktree `.claude/worktrees/s2-E4-L2g`, `task/E4-L2g` HEAD 303a8d8. 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK` 미설정(OpenAI 호출 0), `.env` 미열람, `NEUMANN_DATA_DIR`은 임시 폴더(공유 `data/cache`에 `results*` 생성 없음 확인). git 쓰기 없음. 인수 신호로 일부 확인을 중단했다(아래 "못 본 것").

**VERDICT: PASS-조건부**

| # | 확인 | 방법 | 결과 |
|---|---|---|---|
| 1 | 키 규칙 = make_llm·guard_model | 실제 `make_llm`(잠금 그대로) vs `current_namespace` 20조합, LIVE 가정은 `openai.OpenAI`를 더미로 바꾼 `make_llm` vs `namespace_for` 10조합(환경변수 미사용) | 20/20, 10/10 일치. astra 차단은 sol 실효 + `requested` 별도 칸 |
| 1b | 경로 주입 | 모델명 25종(`../`, `\`, `:`, NUL, 유니코드, 500자, `a/b` vs `a-b` 등) | 파일 이름 ASCII `[A-Za-z0-9._-]`만, 항상 results 폴더 안, 서로 다른 모델은 다른 파일(해시 구분) |
| 2 | mock 디스크 금지 | mock·잠긴 openai·rules·off·미상 provider·None·`" OpenAI "` 8종 | 디스크 0개. 실서비스 구분이어도 mock 흔적(카드 generator mock / 기록 mock)이면 디스크 0 |
| 2b | 심은 파일 | 이름은 sol인데 내용이 mock 등 11종 + 깨진 JSON + astra 이름으로 복사 | 모두 읽지 않음, 파일 바이트 불변 |
| 3 | 옛 `<plan_id>.json` | 조작 16종(mock 기록·기록 삭제·variant 다름·prompt/pipeline 버전 없음·degraded·sample·plan_id 다름·깨진 JSON 등) + 허용 목록 밖 + 새 이름 파일이 이미 있는 경우 | 대조군 1건만 이관, 나머지 무시, 옛 파일 불변, mock·env=mock 구분은 옛 파일을 아예 안 읽음 |
| 4 | 키 분리 | 빌더 테스트 22건 + HTTP 시나리오 C1~C6·D(env mock, env openai+LIVE 없음, 실서비스 가정, mock 예행 뒤 실서비스 파일 불변, 재기동 적중, astra 차단 별 파일, 입장 sol·실행 mock 저장 거절) | 전부 통과. 다른 구분은 합류·자리·진행 기록 안 섞임 |
| 5 | SYNC_QUEUE_MAX | `git diff`·grep | `NEUMANN_SYNC_QUEUE_MAX=8`은 `scripts/serve_loadtest.py`의 자식 프로세스 env에만. 서버 기본값(공개 4/비공개 0)·`.env.example` 불변 |
| 6 | 병합 충돌 | 스크래치 clone: origin/main(4152c58)+L2g, +L2f | main·L2f와 자동 병합 성공. **PERF-pk `PERF-pk_serving.patch`는 serving.py 2헝크 거절**(`ResultCache.put`→`entry_for/put_entry`, `Serving._job`의 `cache.put`), jobs.py·main.py 헝크는 적용됨. SEC-7은 main과 차이 없음(커밋·작업 트리 변경 0) |
| 7a | 새 테스트 | `pytest tests/e4/test_cache_namespace.py` | 22 passed |
| 7b | verify.py | 1회 실행 | 보안·계약 통과, pytest `1356 passed, 43 skipped, 1 failed`. 실패는 `tests/e3/test_pipeline_parallel_sim.py`(시간 상한, 부하 때 간헐. 단독 재실행 1 passed, main 9eda1c0이 이미 완화). skip이 빌더(26)보다 17 많은 것은 내 `NEUMANN_DATA_DIR`이 빈 임시 폴더라서(자료 의존 테스트) |
| 7c | 부하 시험 | `scripts/serve_loadtest.py` 포트 8196, 2회 | A(200×10)·B·C(503×2)·D(429×1)·E(디스크 0개)·F(재시작 뒤 다시 분석)·G 모두 기대대로. 그러나 스크립트 판정은 2회 모두 FAIL: "A 도착순번 최대 == 8" 조건이 6(동시 도착이 퍼짐, 당시 CPU 97%). 빌더 실행은 8로 PASS. L2g 결함인지 부하 탓인지 기준선 대조 못 함 |
| 7d | 변이 | 빌더 16개 주장 | 재현 안 함(내 24개 변이 스크립트는 준비만, 실행 전 중단) |

## 발견

- (낮음) 메모리 캐시는 mock 표지만으로는 거절하지 않는다: 결과 기록이 없거나 구분과 일치하면서 카드 generator만 mock이면 실서비스 구분 메모리에 들어간다(디스크는 막힘). 실제 파이프라인은 항상 manifest를 적어 도달 불가에 가깝고 빌더 테스트가 의도로 명시. 방어 강화하려면 disk_ok 구분에서 메모리도 거절.
- 내 실수: 첫 부하 시험을 포트 8161로 돌렸는데 다른 에이전트의 `neumann.api.main` 서버가 이미 점유. 그 서버로 합성 계획서 POST 약 10건이 갔다(제 서버는 바인딩 실패로 반복 종료). 프로세스는 건드리지 않았고 그 서버는 이후 종료됨. 두 번째부터 빈 포트 8196 사용.
- 정리 중 `%TEMP%\neumann_e4l2c_*`를 지웠는데 그중 하나(19:06, L2c 시절 부하 시험 잔여 로그)는 내 것이 아니었다. 로그뿐.

## 병합 전 필수 조치

1. PERF-pk 패치는 L2g 병합 뒤 손으로 다시 얹는다: `entry_for`가 `{"variant"…}` 옛 저장본을 만들면 새 `_valid`(format 2·ns_id·namespace)에 걸려 디스크 캐시가 전부 무효(닫힌 쪽이지만 캐시 기능 상실). `entry_for(plan_id, result, ns)`가 L2g의 `put`과 같은 저장본·`_record_mismatch` 검사·mock 흔적 검사를 하게 해야 한다.
2. `scripts/serve_loadtest.py`를 조용한 기계에서 한 번 다시 돌려 PASS 확인(도착순번 8 조건은 타이밍 민감).
3. 병합 뒤 전체 verify 1회 재실행(내 1회는 무관한 시간 테스트 1건 실패).
