# TEST-1 부하에 흔들리는 시험 안정화 (미완, WIP 인계)

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
