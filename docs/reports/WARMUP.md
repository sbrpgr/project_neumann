# WARMUP — 검색 전용 백그라운드 예열

작업 브랜치: `codex/warmup`. 빌더: `codex-gpt-6.1-sol`.

## 구현

- `serving.install()`의 기동 훅이 백그라운드 태스크를 시작한다. 기본은 켜짐이며 `NEUMANN_WARMUP=0`으로 끈다. 기존 환경변수 이름을 재사용했고 `.env.example` 설명을 갱신했다.
- `api/warmup.py`는 실제 요청과 같은 `get_store()`·`get_embedder()` 캐시를 사용한다. BM25·dense 색인과 로컬 bge-m3를 읽고 더미 질의 `research methodology evaluation reproducibility`로 `search(k=1)`을 한 번 실행한다. 첫 encode, BM25 점수, dense 연산, 순위 융합까지 통과한다.
- 이전 예열의 데모 계획서 분석·LLM 실행·분석 결과 캐시 채우기를 제거했다. 호환 인자 `pipeline`과 `NEUMANN_WARMUP_PLANS`는 예열에서 실행하지 않는다. 예열은 분석 예산을 사용하지 않고 원본·색인을 수정하지 않는다.
- 일반·공개 `/health`에 `warmup`을 추가했다. `state`는 `pending/running/done/error`, `elapsed_s`는 진행 중 경과 초 또는 완료 소요 초다. 끈 경우에는 `state=done, enabled=false, elapsed_s=0`이다. 성공 시 검색 백엔드·논문 수, 실패 시 예외 종류만 추가한다. 경로·예외 메시지는 공개하지 않는다.
- 실제 파이프라인 실행 직전에 공용 예열 완료를 기다린다. 동기 분석과 잡 분석 모두 `Serving._job()`을 거친다. 기다린 시간은 `waited_s`에 포함하고 분석 `run_s`에는 포함하지 않는다. 요청 취소·시간 초과는 `shield`로 예열을 취소하지 않는다.
- 예열 대기 잡은 `status=running, stage=warmup`, `stage_label/message="모델 준비 중 · 첫 실행은 1~3분"`, `eta_s=null`, `warmup` 상세를 제공한다. 확인되지 않은 잔여 시간을 추정하지 않는다. 기존 화면이 단계 라벨을 표시하므로 화면 파일은 변경하지 않았다. 캐시 결과는 분석 실행이 필요 없어 바로 반환한다.
- 색인 없음·모델 없음·검색 강등은 예열 성공으로 처리하지 않고 `error`로 남긴다. 기다리던 분석은 예열 종료 뒤 기존 파이프라인으로 진행하고, 검색 실패·강등은 기존 결과 상태로 표시된다. 정상 종료 훅은 이 서버의 예열 태스크 완료를 기다린다.

## 검증 명령과 실제 출력

모든 실행은 지정 Python과 `PYTHONPATH=src;.`를 사용했다. 키·솔트·라이브 허용 플래그를 자식 프로세스 환경에서 제거했고 provider는 mock으로 고정했다. pytest 공통 설정과 측정 앱은 설정 로더의 `env_file=None`을 적용한다. `.env`를 읽거나 환경변수 값을 출력·단언하지 않았다.

```powershell
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK,Env:NEUMANN_LIVE_TESTS -ErrorAction SilentlyContinue
$env:NEUMANN_LLM_PROVIDER='mock'
$env:PYTHONPATH='src;.'
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e4/test_warmup.py tests/e4/test_serving.py tests/e4/test_jobs.py tests/e4/test_jobs_limits.py tests/e4/test_sec7.py tests/e4/test_e4_api.py -q --tb=short
```

최종 출력: `136 passed in 16.71s`.

새 검사는 실제 검색 로더·더미 질의 연결, 어휘 검색 강등 거절, 비활성화, 기동 전 pending, 중복 기동 방지, 공개/일반 health, 예열 중 잡 표시와 분석 미실행, 대기 취소 후 예열 지속, 성공/실패 종료 후 잡 완료, 예외 메시지 비노출을 검사한다. 스레드 이벤트로 순서를 제어하며 성능 시간 상한을 완료 기준으로 단언하지 않는다. 이전의 데모 캐시 예열 검사는 파이프라인 호출·결과 캐시 저장·예산 소비가 없는지 검사하도록 교체했다.

초기 새 테스트 4건은 설치된 FastAPI의 `APIRouter.startup()` 부재로 실패했다. 실제 `lifespan_context`를 사용하는 방식으로 고쳤고 최종 실행에서 전부 통과했다. 전체 `scripts/verify.py`와 전체 pytest는 실행하지 않았다. 커밋 훅의 스테이징 보안 검사는 우회하지 않는다.

## mock 기동 → 예열 → 첫 분석 전후 측정

```powershell
& C:/Users/User/.venvs/neumann/Scripts/python.exe tests/e4/warmup_probe.py --model C:/Users/User/Desktop/노이만_본선자료/공개자료/models/bge-m3 --index C:/Users/User/Desktop/project_neumann/data/index --out C:/Users/User/Desktop/project_neumann/out/codex/warmup_measurements_final.json
```

각 조건을 새 서버 프로세스에서 측정했으며 초기 1회와 측정 도구 보강 뒤 1회, 총 두 차례 비교했다. 아래는 마지막 실행이다. 81xx 빈 포트 자동 선택, 로컬 bge-m3, 기존 색인 1,128편, `tests/fixtures/plans/plan.md`, 제품 LLM mock, 분석 결과 캐시 꺼짐을 사용했다. 색인·모델 원본은 읽기만 했다. 새 질의 캐시 등 실행 산출물은 별도 `out/codex/probe_data`에 격리했다. 첫 분석 시간은 잡 POST부터 완료 폴링까지이며 0.2초 폴링 오차가 포함된다.

| 측정 | 예열 끔(전, 8190) | 예열 켬(후, 8191) |
|---|---:|---:|
| 기동 → 첫 health 응답 | 1.375초 | 1.485초 |
| 백그라운드 예열 소요 | 0초 | 13.000초 |
| 기동 → 예열 완료 확인 | 1.375초 | 14.157초 |
| 준비 뒤 첫 분석 요청 → 결과 | 13.579초 | 0.422초 |
| 실제 검색 단계(manifest) | 13.204초 | 0.066초 |
| 기동 → 첫 결과 전체 | 14.954초 | 14.579초 |
| 위험 카드 수 | 6 | 6 |
| 결과 상태 | degraded | degraded |

예열 켬 health 관찰 순서는 `running → done`이며 완료 데이터는 `enabled=true, elapsed_s=13.0, backend=hybrid, n_works=1128`이다. 실제 검색 단계는 두 조건 모두 `status=ok`였고 결과 `degraded`는 mock 분석의 실제 표시이며 LLM 성공으로 보고하지 않는다. 초기화 비용이 기동 직후로 옮겨져 예열 완료 후 첫 요청 대기가 줄었다. 기동 직후 들어오는 요청은 초기화 완료를 기다려야 한다.

초기 비교(8101/8100)에서는 첫 분석 `19.079초 → 0.422초`, 예열 `18.235초`, 검색 단계 `18.597초 → 0.057초`였다. 초기 JSON은 `out/codex/warmup_measurements.json`에 남겼다. 반복 간 초기화 시간 차이는 숨기지 않으며 단일 수치를 운영 보장으로 사용하지 않는다.

PM QA-2의 8020 첫 분석 157.7초는 별도 운영 실측이다. 이번 측정은 8020·실제 LLM을 사용하지 않았고 동일 부하·설정을 재현했다고 주장하지 않는다. OS 파일 캐시는 비우지 않았고 동시 작업 부하가 있어 숫자는 이 실행의 관찰값이다.

## headless 화면 확인

```powershell
& C:/Users/User/.venvs/neumann/Scripts/python.exe tests/e4/warmup_probe.py --ui --out C:/Users/User/Desktop/project_neumann/out/codex/warmup_ui
```

출력:

```json
[{"width":1440,"warmup_visible":true,"overflow_px":0},{"width":390,"warmup_visible":true,"overflow_px":0}]
```

81xx mock 서버에서 예열을 이벤트로 잠시 고정하고 실제 화면 입력 → 잡 POST → 폴링 → 모델 준비 문구를 확인했다. 두 폭의 PNG를 직접 확인했다. 서버의 새 단계 라벨을 기존 화면이 그대로 표시한다. UI 프로브 첫 실행은 분석 스테퍼 버튼을 실행 버튼으로 잘못 선택해 실패했으며 `#btnStart`로 수정했다. 측정 도구 수정 중 준비 확인 시간 초과도 발생했다. 로컬 HTTP 연결에 `trust_env=False`를 적용하고 Windows venv 실행기 PID와 인터프리터 PID가 다른 점을 확인해, 준비 확인에서 부모 PID도 검사하도록 수정했다. 최종 UI 실행은 위 출력으로 통과했다. 화면 CSS·폰트·색상 변경은 없다. 디자인 규격 문서를 읽었지만 이 브랜치의 기존 화면 자체에 남은 구 디자인을 새 규격 준수로 보고하지 않는다.

측정 JSON·PNG는 저장소 밖 `out/codex`에 두고 커밋하지 않는다. 모든 시험 자식 서버는 `finally`에서 종료했다. Windows 종료는 자신이 띄운 Popen PID의 프로세스 트리만 `taskkill /T`로 정리하며 다른 작업자 서버는 종료하지 않는다. 사용자 Chrome·데스크톱·탭 목록·실제 OpenAI API를 사용하지 않았다.

## 못 한 것과 다음

- 하위 에이전트 금지에 따라 독립 모델 검증은 하지 않았다. PM이 `gpt-6-sol` 독립 검증과 병합 판단을 진행해야 한다.
- 운영 8020·라이브 최종 검증은 PM 담당이며 이 작업에서는 접근하지 않았다. 실제 운영 색인·모델 설정으로 재기동한 뒤 `/health.warmup.state=done`과 첫 요청 대기 감소를 확인할 수 있다.
- 예열을 켠 개발 서버에는 로컬 모델·색인 설정이 필요하다. 없는 환경은 health에 `error`가 남으며 가짜 예열 성공으로 처리하지 않는다.
- 병합·push·stash·다른 작업자 worktree 수정은 하지 않았다. 현재 브랜치 커밋은 실제 파일 권한 차단으로 완료하지 못했다. 지정 대시보드 inbox에는 구현·검증 결과와 커밋 차단 사유를 한 줄 전달한다.

## 커밋 차단과 PM 인계

파일 10개를 명시한 `git add`와 `[WARMUP]` 제목의 `git commit`을 시도했으나 둘 다 다음 출력으로 거절됐다.

```text
fatal: Unable to create 'C:/Users/User/Desktop/project_neumann/.git/worktrees/warmup/index.lock': Permission denied
```

해당 worktree 메타데이터 폴더의 임시 파일 쓰기 점검도 거절됐다. `.env` 존재 확인은 false이며 내용을 읽지 않았다. 훅 우회나 ACL 변경, 다른 worktree 수정으로 우회하지 않았다. 스테이징 전에 거절되어 커밋 훅은 실행되지 않았으며 훅 통과를 주장하지 않는다.

변경과 보고서는 현재 worktree에 남아 있다. 전체 변경을 포함한 패치를 `C:/Users/User/Desktop/project_neumann/out/codex/WARMUP.patch`로 제공한다. PM은 Git 메타데이터 쓰기 권한을 복구한 뒤 이 브랜치에서 명시 파일을 스테이징하고 훅을 거쳐 커밋할 수 있다. 희망 커밋 메시지는 다음과 같다.

```text
[WARMUP] Add retrieval-only startup warmup and waiting job status

validation: 136 related tests passed; headless 1440/390 overflow 0; mock first analysis 13.579s -> 0.422s

builder: codex-gpt-6.1-sol
```
