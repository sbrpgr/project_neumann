# TEST-1 시간 시험 안정화 — Codex 빌더 결과 (2026-10-01 00:20 KST)

빌더 범위 완료. 전체 verify와 독립 검증은 PM 큐에 남긴다.

- worktree: `C:/Users/User/Desktop/project_neumann/.claude/worktrees/s2-TEST-1`
- branch: `task/TEST-1`; 착수 HEAD: `2bd67041f70237c0d1183d2cedd45036b7ba1cbd`
- actual model: `gpt-6.1-sol` (PM이 확정한 실행 모델); `builder: codex-gpt-6.1-sol`
- 선행 커밋: `43ae75b` (부하 도구), `a7c287e` (파이프라인·CPU 예산). 최종 HEAD는 이 보고서와 E4 시험을 담은 커밋이다(`git log -1`).
- 실제 OpenAI 호출 **0**. `mock`, `NEUMANN_LIVE_TESTS=0`, 실행 시작 시 LIVE_LLM_OK 제거. pytest 공통 설정은 이를 0으로 닫는다. 키를 읽거나 복원하지 않았다.
- 제품 파일·contracts/models/config·공통 docs 변경 없음. 기존 WIP를 이어 시험·시험 도구·본인 보고서만 변경했다. main 병합/push/tag/하위 에이전트/서비스 접속 없음.
- `docs/tasks/TEST-1.md`와 `docs/reports/TEST-1.verify.md`는 현 worktree에 없다. 최신 PM 과제 지시, 기존 보고서, `_COMMON.md`, `_VERIFY.md`, AGENTS와 기준 계획서를 읽었다.

## 바꾼 검사와 보존한 의미

| 대상 | 최종 검사 |
|---|---|
| v1 겹침·의존 | 심사평/체크리스트 모듈 진입의 2자 배리어. 검증 진입 시 체크리스트 반환 이벤트와 실제 전달된 체크리스트가 일치해야 함. 단계 성공·작업 스레드도 확인 |
| sim WIP | 기존 순차/병렬 결과 동일·시간 비율·의존 하한 유지. 반복 비율도 혼잡에 흔들릴 수 있다는 설명으로 정정 |
| direct_round PM 실패 | 과제 이름 수 대신 호출당 실제 지연의 임계 경로: 앞 단계 합 + max(심사평, 체크리스트+검증). 지연 0인 호출은 하한 0. 소수 셋째 자리 통계의 반올림 오차 0.0005만 허용. 사용자 3명의 query_axes 진입 배리어로 동시 실행 증명 |
| DelayedMock·TimedLock WIP | 성공 응답 수·스레드 오류 검사 추가. 시계 시작 후 이벤트로 호출 해제. 가짜 시계의 wait/hold=0.15 정확값 유지, 실패 때도 해제·join |
| PII·SEC4·fitness | 원래 적대 입력(최대 20만 자, fitness 10만 자)과 1.0/0.2초 계산 예산 유지. 외부 프로세스 스케줄링은 제외하도록 process_time으로 측정 |
| 추출 상한 | 호출을 이벤트로 막고, 미완료인 동안 stage가 fallback으로 반환했는지 검사. finally에서 호출 정리 |
| 비동기 POST | 실제 분석을 Gated로 막은 동안 POST가 반환하고 search 진행 상태가 보임. 해제한 뒤 결과·본문·관문 슬롯·호출 1회 확인 |
| ZIP/작업자 | 폭탄에서 ZipFile.open 호출 0 확인. 시험이 만든 지연 작업자가 timeout 뒤 kill되고 poll로 종료 확인. 실제 PDF/DOCX 작업자 추출 시험은 유지 |
| jobs limits·업로드 응답 | 기존 CPU 계산 예산과 오류·응답 크기·pipeline 호출 0·관문 검사는 유지. 벽시계 polling 상한은 기능 기준이 아닌 교착 감시로 구분 |
| 부하 도구 | 수집 실패·XML 누락/손상·빈 결과·watchdog를 실패로 기록하고 CLI exit=1. skip 횟수 표시, 전부 skip도 exit=1. 대상 없는 실행 금지. --max-s 전달 버그 수정. mock·live=0·.env 비활성·외부 연결 차단으로 pytest 시작 |

새 skip/xfail, 성능 예산 확대, 제품 우회는 없다. serving의 대기 감시만 3~5초에서 20초로 통일했고, 슬롯 반환 조건은 그대로 검사한다. CPU 예산은 외부 혼잡과 분리한 계산 비용 경계이며 실제 서비스 벽시계 SLA 측정은 아니다.

## 실행한 명령과 측정값

Python: `C:/Users/User/.venvs/neumann/Scripts/python.exe`.
각 실행에서 mock/live=0를 명시하고 LIVE_LLM_OK를 제거했다. 아래 과제 전용 오프라인 runner는 `.env`를 비활성화하고 인증값을 읽지 않으며 HTTP 연결을 금지한다. Windows asyncio 내부 socketpair만 예외다. 외부 runner·진단·변이 파일은 `out/codex` 산출물로 커밋하지 않았다.

```powershell
& 'C:/Users/User/.venvs/neumann/Scripts/python.exe' 'C:/Users/User/Desktop/project_neumann/out/codex/TEST-1-targeted.py' -q -p no:cacheprovider --tb=short tests/_util/test_cpuload.py tests/e0/test_sec4_email_linear.py tests/e3/test_extract.py tests/e3/test_fitness_field.py tests/e3/test_pii.py tests/e3/test_pipeline_parallel.py tests/e3/test_pipeline_parallel_sim.py tests/e3/test_sec5_inflight.py tests/e4/test_jobs.py tests/e4/test_jobs_limits.py tests/e4/test_loadtest_multiuser.py tests/e4/test_upload.py tests/e4/test_serving.py tests/e4/test_serving_sec.py
```

출력: **441 passed in 35.67s**, 실패/오류/skip 0. 이후 TimedLock 정리 보강은 해당 시험 포함 3개 재검사: **3 passed in 4.75s**.

```powershell
& 'C:/Users/User/.venvs/neumann/Scripts/python.exe' -m tests._util.cpuload --mode both --workers 2 --max-s 30 --reps 1 --json 'C:/Users/User/Desktop/project_neumann/out/codex/TEST-1-light-load.json' tests/e3/test_pipeline_parallel_sim.py::test_simulated_parallel_is_faster_and_same tests/e3/test_pipeline_parallel.py::test_v1_stages_overlap_and_respect_dependency tests/e4/test_loadtest_multiuser.py::test_direct_round_runs_concurrently_and_matches_sequential_reference tests/e4/test_loadtest_multiuser.py::test_timed_lock_measures_wait_and_hold_per_thread tests/e4/test_loadtest_multiuser.py::test_delayed_mock_real_sleep_overlaps_across_threads tests/e4/test_loadtest_multiuser.py::test_delayed_mock_delays_are_in_flight_together tests/e3/test_extract.py::test_stage_deadline_falls_back tests/e3/test_pii.py::test_adversarial_inputs_are_fast
```

출력: 매개변수 확장 뒤 13개 항목 모두 **무부하 설정 0/1, 2 worker 부하 0/1** (실패/실행 수).
최종 스레드 정리 변경 뒤 2개 항목만 `--mode load --workers 2 --max-s 15 --reps 1`로 추가 확인: **각 0/1, 2.62초**.
다른 세션·프로세스를 중단하지 않았으므로 무부하 설정도 PC 전체가 유휴 상태라는 뜻은 아니다. 단발·소규모 결과이며 16/32 worker 반복의 안정성은 주장하지 않는다.

```powershell
& 'C:/Users/User/.venvs/neumann/Scripts/python.exe' 'C:/Users/User/Desktop/project_neumann/out/codex/TEST-1-metrics.py'
```

출력: PII 6개 입력의 최대 CPU **0.140625s < 1.0**, SEC4 5개 **0.062500s < 1.0**, fitness 270개(각 10만 자) **0.015625s < 0.2**.
direct_round: run_s **0.315/0.108/0.216**, 의존 관계에 따른 하한 **0.300/0.100/0.200**.
PM 보고의 `0.312 < 0.315`는 전달받은 실패값이며, 같은 호출 내역의 실패는 현재 worktree에서 재현하지 못했다. 과거의 과제 이름 수 하한 대신 위의 실제 지연·의존 관계를 검사한다.

## 변이 검사 (소스 수정 없이 독립 Python 프로세스 안에서만)

명령: `TEST-1-mutate.py <kind>`. 각 명령은 대상 pytest exit=1을 확인해 검출 성공을 반환한다.

| kind | 주입한 결함 | 실제 결과 |
|---|---|---|
| serial | v1 강제 순차 실행 | overlap 1 failed / 20.05s |
| serial-sim | 같은 결함 | sim 1 failed / 16.33s |
| no-dependency | semantic_validate 의존 제거 | graph 1 failed / 0.02s |
| lost-input | 검증 입력의 체크리스트 제거 | overlap/dependency 1 failed / 0.05s |
| no-delay | mock sleep 제거 | direct_round 1 failed / 3.06s |
| zero-lock | 스레드 계측을 0으로 고정 | TimedLock 1 failed / 0.02s |
| shared-lock | thread-local을 공유 상태로 변경 | TimedLock 1 failed / 0.02s |

**7/7 검출**. 항상 통과하는 검사가 아니다. 변이는 종료 시 해제되며 제품 파일에 차이가 없다.

## 실패·미실시 항목

- 첫 실행 **278 passed, 2 errors**: 공용 pytest 임시 폴더의 WinError 5. 과제 전용 out/codex 임시 폴더로 바꿔 해결.
- 다음 **290 passed, 15 failed**: 직접 추가한 연결 차단이 Windows asyncio 내부 socketpair도 거부. 내부 socketpair만 허용한 뒤 jobs/upload/limits/SEC5 **102 passed in 24.03s**, 최종 441개도 통과.
- 첫 git add/commit은 공용 `.git/worktrees/s2-TEST-1/index.lock` 권한 때문에 거부. 승인된 파일의 Git 메타데이터 쓰기만 권한 검토를 통과해 계속했다. 훅 우회 없음.
- `git diff --check` 성공. 커밋 훅의 `verify 통과`는 스테이징 파일 보안 검사만 뜻한다. **전체 scripts/verify.py는 실행하지 않았다** (최신 PM 지시). 독립 verifier를 만들거나 실행하지 않았다.
- 기준 계획서·공개 원본은 복사/변경하지 않았다. stop-request는 확인 시 존재하지 않았다.

## 남은 일·다음 (5줄)

1. PM이 독립 `gpt-6-sol` 검증을 실시하고 보고서의 주장을 재측정한다.
2. PM 큐에서만 전체 `python scripts/verify.py`를 실행하고 성공 뒤 통합한다.
3. PM 최신 제품 브랜치에서 direct_round 호출 내역·의존 하한을 확인한다(전달받은 실패값의 동일 재현은 미완).
4. 필요하면 별도 시간대에 성능을 재측정한다. 이번에는 무거운 16/32 worker 반복을 하지 않았다.
5. out/codex 진단·변이·임시 파일은 Git 밖에 보존하고 PM이 확인 뒤 자신의 방침에 따라 정리한다.

---

아래는 인계 전 이력이다. 현재 완료 기준·전체 verify 담당은 위의 최신 PM 지시를 우선한다.

# TEST-1 부하에 흔들리는 시험 안정화 (이전 WIP 인계)

상태: 일부만 끝났다. 제품 코드는 바꾸지 않았고(시험·시험 보조만), 모든 명령은 `NEUMANN_LLM_PROVIDER=mock`, OpenAI 호출 0이다.
worktree `.claude/worktrees/s2-TEST-1`, 브랜치 `task/TEST-1`(main 784fa73 병합 완료).

## 부하 재현 도구 (끝남)

- `tests/_util/cpuload.py`: 코어 수(기본 16)만큼 계산 프로세스를 돌리며 pytest를 반복 실행해 시험별 실패율 표를 만든다.
  `python -m tests._util.cpuload --reps 5 [--mode none|load|both] [--workers 32] [--only-failing] <시험 id...>`
- `tests/_util/timing.py`: 벽시계 대신 쓰는 판정(`assert_faster` 반복 최솟값 비율, `assert_scales_linearly` 길이 배수 대비 시간 비율).
- 주의: 이 PC는 다른 빌더·검증자의 pytest·verify가 동시에 돌아 "부하 없음"도 실제로는 중간 부하다. 전(前) 측정은 수정 전 스냅샷(`git archive HEAD`)에서 해야 수정 중인 파일과 섞이지 않는다.

## 전 측정 (수정 전 main d8f7c85, 대상 3개)

| 시험 | 부하 없음 5회 | 부하 16코어 5회 | 부하 32프로세스 8회 |
|---|---:|---:|---:|
| `test_pipeline_parallel_sim.py::test_simulated_parallel_is_faster_and_same` | 0/5 | 2/5 | 7/8 |
| `test_pipeline_parallel.py::test_v1_stages_overlap_and_respect_dependency` | 0/5 | 0/5 | 3/8 |
| `test_loadtest_multiuser.py::test_delayed_mock_real_sleep_overlaps_across_threads` | 0/5 | 0/5 | 6/8 |

실패 메시지: sim은 병렬 v1이 1.6~3.6초(기준 2.6단위=1.56초), 겹침 시험은 "예상 심사평과 체크리스트가 겹쳐 돌아야 한다"와 v1_wall 대비 serial 비율,
loadtest는 4개 동시 호출이 1.0~1.3초(기준 0.6초; 스레드 기동 지연이 초 단위로 튄다). 그 밖의 시험 전 측정(16코어×3)은 도중에 중단했다.

## 이번 커밋까지 고친 것과 변이 검사

- `tests/e4/test_loadtest_multiuser.py`
  - `test_delayed_mock_real_sleep_overlaps_across_threads`: 절대 0.6초 대신 같은 호출 4개의 동시/차례 시간 비율(<0.8, 반복 최솟값). 스레드는 배리어에 세웠다가 한꺼번에 푼다.
  - 신규 `test_delayed_mock_delays_are_in_flight_together`: 지연 자리에 4자 배리어를 넣어 겹침을 시간 없이 증명한다.
  - `test_timed_lock_measures_wait_and_hold_per_thread`: 진짜 sleep·시각 비교(`wait<0.05`, `>=0.08`) 대신 가짜 시계로 정확값 검사.
- 변이(제품 코드에 임시로 넣고 시험 후 원복, `git status`로 원복 확인): 지연을 락 안에서 실행 → 비율 시험 사멸(비율 1.00)·배리어 시험 사멸.
  GIL을 잡는 CPU 지연 → 비율 시험 사멸(0.99). TimedLock 대기·점유 0 고정, 스레드 공유 통계 → 사멸 3/3.
  (벽시계 마감 바쁜 대기는 스레드끼리 겹치므로 결함이 아니라서 잡히지 않는 것이 맞다.)
- `tests/e3/test_pipeline_parallel_sim.py::test_simulated_parallel_is_faster_and_same`: 반영됨, 부하 없는 1회 통과(부하 5회·변이 검사는 아직) (병렬/순차 v1 비율<0.8 최솟값, 순차≥3단위·병렬≥2단위 하한으로 의존 깨짐도 잡음, 총시간 비율<0.92).

## 남은 일

1. sim 시험을 부하 16코어×5·32×8로 재측정하고 변이(병렬 강제 끔: `_attach_v1`의 `if not parallel or errs:`를 항상 참으로, 의존 깨기: `V1_DEPENDS["semantic_validate"]=()`)로 사멸을 확인한다.
2. `test_pipeline_parallel.py::test_v1_stages_overlap_and_respect_dependency`를 이벤트로 교체한다: 예상 심사평 첫 호출이 체크리스트 진입을 기다려(5초) 겹침을 증명하고, 체크리스트 첫 호출이 2차 검증 진입을 잠깐(1초) 기다려 의존을 증명한다. `v1_wall_s < serial*0.85`는 지운다(겹침 증명+sim 비율이 대신함).
3. 나머지 벽시계 절대 상한을 같은 원칙으로 바꾼다: `test_pii.py`(1.0초 상한 8곳, 선형성 비율), `test_sec4_email_linear.py`, `test_fitness_field.py`(<0.2초), `test_extract.py`(<1.4→이벤트로 "호출이 안 끝났는데 돌아옴"), `test_upload.py`(<2/5/10초), `test_jobs.py`·`test_jobs_limits.py`(<1.0·<10초), `test_sec5_inflight.py`(wall·took<5.0), `test_serving*.py`(`wait_until` 3~5초 → 20초).
4. 수정 후 표(부하 16코어×5, 32×8)와 시험별 변이 결과를 이 보고서에 채운다(수정 전 스냅샷 대비).
5. `python scripts/verify.py` 통과 뒤 `[TEST-1]` 커밋으로 마무리하고 PM이 병합한다.
