# 인계 문서

PM이 병합할 때마다 갱신한다. Claude 한도가 다 되면 이 문서를 Codex에 주고 PM 역할을 넘긴다.

## ★ Codex 통합 후보 — 2026-10-01, 전체 검증 대기

- 이 절은 통합 브랜치 `codex/integration-20261001`의 준비 상태다. 기준 main `17c8058`; main 병합은 아직 하지 않았다. Git PM 실행은 통합 담당, 최종 병합 결정과 사용자 소통은 root PM이 맡는다.
- 후보 코드 `2fa72fe`: E3-L1s `47acaba`, E3-L1e `4c47892`, E4-L2f `5ac22b5`, E3-L2r `f8932e0`, TEST-1 `dc87885`와 그 선행 커밋을 전부 포함한다. TEST-1의 E4 direct_round 수정까지 포함하며 작업별 안정 HEAD만 썼다.
- 충돌은 view.py 1곳과 export.py 10곳이다. main 표시 문자열 정리, 입력 단계·검색 상태, 마지막 근거 게이트, 출처·서명, 선택 수정안 파일을 모두 보존했다. L2r 보고서 후행 공백 1줄만 정리했다. 최종 결합 mock 검사 364 통과·1 건너뜀, TEST-1 E3/CPU 285 통과, E4 156 통과. 전체 verify와 최종 독립 후보 판정은 아직 대기다.
- E3-L1e 독립 `gpt-6-sol/high`의 고정 `4c47892` 대상 186 통과·1 건너뜀, 브라우저 1 통과, 입력 형식 19 통과. E3-L2r 독립 `gpt-6-sol`의 고정 `f8932e0` 대상 119 통과, 실제 signing 모듈 주입 119 통과, 보안 454개 통과. 상세 보고서의 대상 HEAD와 조건부 범위를 그대로 따른다.
- 개발 주력 `gpt-6.1-sol`, 독립 검증 `gpt-6-sol`; 노력 수준은 과제별 실제 실행 설정을 따른다. 32개 편성의 실행·대기는 대시보드가 별도로 관리하므로 모두 실행 중이라고 해석하지 않는다. 이 후보의 통합 담당은 `codex-gpt-6.1-sol`이다.
- 전체 verify·부하는 통합 담당 단일 큐다. 개발·검증은 mock/offline, 실제 API 0. main 병합은 전체 verify와 최종 독립 판정 후 root 지시가 필요하다. 태그·공개·실서비스 재시작은 이번 준비에 포함하지 않는다.

## ★ Codex PM 작업 중 (2026-09-30 23:5x KST, 대표 즉시 착수 지시)

- 개발 주력 `gpt-6.1-sol/high`, 독립 검증 `gpt-6-sol/high`; PM은 배정·검증 큐·통합·보고를 맡는다. 제품은 `gpt-6.1-sol`, 개발·검증은 mock.
- 마감은 **10/01 02:40 KST**. 02:25부터 정리, 02:30까지 WIP 포함 커밋, 02:35부터 프로세스·인계 상태 점검. Claude 복귀 예약 문서는 02:45이므로 그전에 인계한다.
- E3-L2r: F1 `6bf5f3f`, F2 `01fb7d4`, F3 `884e02f`, F4 `43415a3`; 모두 아직 main 미병합. 최신 자체 대상 검사 101 통과, F5~F8 보강 중. 실제 signing 모듈 연결 후 독립 검증이 필요하다.
- E3-L1e: `53e30c2` 인수 정리 후 독립 검증에서 view·내보내기 우회 반례 발견. 같은 빌더가 최종 게이트를 보강 중. 보고서 `docs/reports/E3-L1e.codex.verify.md`.
- E3-L1s: 독립 대상 144 통과. 전체 verify는 시간 단언 1건 실패(1342 passed, 46 skipped), main view.py 병합 충돌 1곳. **병합 보류**, TEST-1 해결 필요. 보고서 `docs/reports/E3-L1s.codex.verify.md`.
- 대시보드 담당이 기존 Claude 이력을 보존하며 attention·usage·inbox·codex_progress를 관리한다. 현재 실제 실행 수만 표시하고 미검증을 PASS로 표시하지 않는다.
- 독립 CLI의 사용자 계정 ChatGPT 로그인 확인 완료. 병렬 실행 관리자가 기존 worktree별 작업과 고정 HEAD 검증을 배정한다. 전체 verify·부하 시험은 동시에 하나만.
- 8020·8099 유지, 공개 터널·실제 API는 기존 게이트와 승인 범위를 그대로 따른다. E1-L1b 보류 및 키트 데모 반입 판단은 대표 대기다.

## ★ PM 인수 완료 (2026-10-01 00:5x, 대표 지시 "인수인계 준비·작업 마무리") — 이 절이 최신

- **main HEAD는 `git log -1 main`** (이 커밋 직후, push됨). 되받을 때는 이 절 → 아래 "Codex 인수 시 첫 30분" → 대시보드 메시지함 "인수 종료" 요약 순서로 읽는다.
- **이번 창에서 병합한 것(20:00 이후):** E3-L1w(v1 파이프라인), E1-L1c(코드), E4-L1e, E4-L1f, E6-docs+README, E3-L1x, SEC-3(실제 호출 잠금+astra 금지), SEC-4(ReDoS), E4-L2e, SEC-5, E4-L2d(+E4-L2c, 패치 2개), E3-L1y, E5-L2c(판정 경로+블라인드 v3), DISP-1, E3-L1z, SEC-2r DO_NOT_SERVE 가드(cherry-pick+실효 경로 보강), E5-L3b(4354284), SEC-6, 테스트 안정화 2건, 리포트 카드 재생성.
- **결과:** 백테스트 n=5 판정 완료 — 주 결과 블라인드 v3 `docs/reports/E5-L2b_n5_results.md`(Neumann A 3/4·hit@3 0.2, 기준선 A 4/15·hit@3 0.6, 통계적 결론 없음).
- **검증 대기(PASS 나면 병합):** E3-L1s(47acaba 재검증)·E3-L1e(b64abeb 조건 반영) = v2 관문 → E4-L2f(서명, DISP-1 충돌 해결) → E4-L3m(8803fdd) → E4-L1g(샘플 갤러리) → E3-L2r·E4-L4r. 공개 전: PERF-pk, E4-L2g, OPS-tun, SEC-7. 그 밖: E4-L2h, E3-L1z2, TEST-1, E2-L5, E5-L3b 후속(5c84c88·bb3c129).
- **PM 과제 20개:** 인수 신호로 WIP 커밋 + 보고서 "남은 일" 5줄 뒤 정지. 목록·산출물은 QUEUE "PM 세션 과제 20개" 표. 브랜치는 `git log --all --oneline --grep '^\[<ID>\]'`. 모두 **검증 전**이며 병합하지 않았다.
- **막힌 것·대표 대기:** 라이브 묶음(v1 확인·원문 복원 7편·E2-L5 분야 6편)은 E3-L1s·E3-L1e 병합 뒤. E1-L1b는 병합 보류(대표 결정 대기). 대표 블라인드 판정(`data/eval/judge_n5v3/human`, JUDGE-H 양식은 검증 뒤). 터널은 공개 전 필수 묶음 뒤.
- **되받기:** 02:39 초기화 뒤 구축 세션이 되받는다(예약). PM 세션도 이 절과 메시지함부터 읽는다.

### PM 과제 20개 — 인수 시점 브랜치·상태(모두 WIP, 검증 전, 병합 안 함)

| ID | 브랜치 · 머리 | 상태 · 핵심 |
|---|---|---|
| LIC-1 | task/LIC-1 · 287a8b6 | LICENSES.md 초안. 위험: 심사평 인용 라이선스 미확인(OpenReview 약관), DISAPERE 비상업, **키트 데모 계획서 3편 반입**(decisions 00:5x) |
| DOC-1 | task/DOC-1 · ccfbedf | README·ARCHITECTURE·API 개정(RUNNING 미편집). main 기준 사실로 정정(관문 40자, HWPX 415, 화면 내보내기 준비 중) |
| PERF-2 | worktree-agent-acb6309df7b7878ad · 410109e | 지연 시뮬레이터(라이브 보정). 추정: EXTRACT_PARALLEL 32면 추출 1파, 동시 6명이면 상한 32 대기로 규칙 강등 위험 |
| OBS-1 | task/OBS-1 · 4c059ef | ops_report.py. **토큰 사용량이 manifest에 없음** → 비용 추정 불가(E3 manifest.llm_usage 제안) |
| REL-1 | worktree-agent-a41b74d979c55aa30 · 88bba3c | 동결 시트 작동(--skip-tests). 테스트·RELEASE.md 미완 |
| JUDGE-H | worktree-agent-a99b4bb99789be31d · 4234fb3 | 대표 판정 HTML 양식 완성(테스트 11). 생성: `python -m eval.human_form --judge-dir judge_n5v3` |
| E5-L1c | worktree-agent-aefb52ad3e6f89337 · a3bca7a | sol 재측정 준비(모델별 캐시, dry-run). gold만 약 $1.1~1.2, 명령은 보고서 |
| FUZZ-1 | worktree-agent-a6d1e116df0df0aa9 · ee086fc | 보고서만. 500 결함 4건(B1 /fonts Windows 금지 문자, B2~B4 package 입력) |
| CFG-1 | worktree-agent-a249a205b33b8b10d · 86e941f | .env 읽기 필드 17개·env_value(). **주의: main .env의 튜닝 키가 병합 뒤 적용됨** |
| SYSTEM-CARD | task/SYSTEM-CARD · 82939c7 | 초안. 발견: 분야 수준 카드 화면 라벨 미구현(E3-L1s), P3 측정값 있음 |
| PROMPT-AUDIT | worktree-agent-a1c0f2f573a9e1b93 · dd7f9fb | 호출별 표·우선 10·탐침 43 |
| E5-L3c | worktree-agent-a8e282159ab7af9ab · c5ec724 | generator 분리 코드. 새 테스트 미실행 |
| QA-1 | worktree-agent-acc37aea9a4ea9854 · 62138a4 | 결함 12(높음 3: 화면 내보내기 꺼짐→E4-L2f, HWPX 415→E4-L2h, 300자 없음→E3-L1s). **녹화 전 예열 필수(첫 분석 166초)**, mock에서 "OpenAI 전송" 안내 부정확 |
| PRIV-1 | task/PRIV-1 · 87f101c | **높음: 검색어 캐시가 계획서 요약을 만료 없이 디스크에**(끄는 설정 없음). 전화번호 가림 하이픈만. 맨 uvicorn이면 실제 IP 로그 → `serve.py --public` 필수 |
| E2E-2 | task/E2E-2 · 75d7a00 | 12개 중 9통과·1실패(연결 끊김 뒤 합류 미확인)·2건너뜀. 설계 공백: 300자 거절도 job 생성(202) |
| SEC-8 | worktree-agent-a7bc54b0191dce7c1 · 67b8117 | **판정 조건부.** 공개 전 필수 2: SEC8-01 줄 수 폭탄으로 LLM 프롬프트 ×592 증폭(지출 한도 없음) → 줄 상한, SEC8-05 `--public` 사전 점검이 LIVE_LLM_OK를 안 봐 공개 서버가 통째로 mock이 될 수 있음. 중간 3(캐시 적중 작업으로 저장소 채우기, 내보내기 CPU 증폭, zip 선언 크기) |
| MCP-demo | task/MCP-demo · f80d6a7 | 3개 도구 시연(mock·실색인), 테스트 8. premortem 도구는 없음(다음 단계) |
| DATA-CARD | worktree-agent-ab5683d4620ff6a54 · 5edd89d | 데이터 카드 완성(1,128편·리뷰 5,366·문장 133,769·거절 60.28%, 리뷰 없는 논문 60편) |
| UXC-1 · A11Y-1 | (TaskStop으로 정지됨) | **정지됨 — worktree에 미커밋 변경 있을 수 있음(git status 확인)** |

### 구축 세션 판정(인수 직전, 전체는 out/dashboard/handoff_agents.md E절)
- **E3-L2r FAIL(68385cd): 422 요청이 관문 자리를 반납하지 않아 한 IP 6건이면 전체 /premortem 504** 등 — 재탄생 병합 전 필수, **Codex 1순위**.
- PERF-pk PASS-조건부(보고서 docs/reports/PERF-pk.verify.md): 한글+결합 문자 NFC 제곱 → 정규화 전 길이 관문, 줄 상한 3,000~5,000.
- E4-L2g·OPS-tun PASS-조건부(수정 필요), E6-L3d ✅ 병합(이 커밋 직전). WIP: SEC-7 554d2b9, TEST-1 2bd6704, E3-L1z2 0f4e93e, E5-L3b 1a1da0e, E4-L1g a97a165, E5-L2f 0a720b4.
- 정적 판 교체 명령(E6-L3d): `precompute_demo.py --from-results <E5 worktree>/docs/reports/E5-L1e2e_live --run-commit a9f28e1 --allow-partial` → `build_static_site.py`(공유 data/precomputed·data/site를 바꾸므로 8010·8020 영향 확인 뒤).

## ★ Codex 인수 시 첫 30분 (00:4x 준비, 사용량 92%에 구축 세션이 인수 신호)

실행 방법·첫 메시지·체크리스트: `out/dashboard/codex_kickoff.md`(gitignore). 진행 중 작업 표: `out/dashboard/handoff_agents.md`. 대시보드 http://127.0.0.1:8099 메시지함을 먼저 읽는다. Codex는 개발용(gpt-6-astra 빌드 → gpt-6-sol 검증, 구독)이고 **제품 API는 gpt-6.1-sol만**(astra 금지, 코드가 막음).

1. **상태 파악(5분):** `git log --oneline -15 main`, `docs/tasks/QUEUE.md` 맨 위 "우선 병합" 줄과 "PM 세션 과제 20개" 표, `docs/decisions.md` 끝 20줄.
2. **병합 대기열(순서 고정):**
   - v2 관문: **E3-L1s(47acaba 재검증) → E3-L1e(b64abeb 조건 반영분)**. 둘이 병합되면 구축 세션(또는 대표)에 알리고 8020 재기동 → 라이브 묶음.
   - UI: E4-L2f → E4-L3m → E4-L1g → E3-L2r·E4-L4r(재탄생). 뒤에 병합하는 쪽이 main을 먼저 병합해 index.html 충돌을 푼다.
   - 공개 전 필수: PERF-pk(models 패치는 PM이 적용+decisions) → E4-L2g(캐시 키) → OPS-tun 재작업 → SEC-7 → SEC-8 보고서 반영 → 터널.
   - 그 밖: E4-L2h, E3-L1z2, TEST-1, E2-L5, E5-L3b 후속(5c84c88·bb3c129), PM 과제들.
   - 병합 조건: 다른 모델의 검증 PASS(또는 PASS-조건부의 조건 반영 확인) + `NEUMANN_LLM_PROVIDER=mock` verify.py 통과. 병합 뒤 push, HANDOFF·QUEUE 한 줄.
3. **라이브 묶음 실행 조건:** E3-L1s·E3-L1e 병합 뒤에만. v1 확인 1회, 원문 복원 7편, E2-L5 분야 6편(결합·도킹 override 포함). 모두 대표 승인 범위. 실행은 8020 경유 또는 `NEUMANN_LIVE_LLM_OK=1`이 명시된 명령만. 재실행은 대표 승인.
4. **금지:** `.env` 열기·출력, 환경변수 전체 출력, `git add -A`, `--no-verify`, `git stash`(worktree 공유), force push, astra 제품 호출(`NEUMANN_ALLOW_ASTRA`), 터널을 SEC-2r·SEC-7·PERF-pk 병합 전 공개, 키트 원문 반입, 리뷰어 실명, 사전 등록(백테스트 표본·판정) 변경, 07:00 동결 뒤 숫자 변경(REL-1 동결 시트 기준).
5. **되받기:** 02:39 초기화 뒤 Claude가 되받는다. Codex는 대시보드 메시지함에 **"인수 종료" 요약**(병합한 것, 진행 중, 막힌 것, 대표 대기)을 남긴다.

## ★ Codex 즉시 인수 (취소 — Claude 계속, 대표 21:3x) · 아래 표는 21:2x 상태 기록

**main `5ed9b45` (push됨)**: v0 태그 뒤 E2-L1·E4-L1a·E3-L1w(v1 파이프라인)·E1-L1c(코드)·E4-L1e·E4-L1f·E6-docs·E3-L1x·E4-L2e·SEC-3(실제 호출 잠금+astra 금지)·SEC-4(ReDoS) 병합.

**병합 순서(공개 전):** E4-L2d → SEC-5 → SEC-2 → 터널. 각 병합은 `codex_task.sh verify <ID>`(gpt-6-sol) PASS 뒤, verify.py(venv, `NEUMANN_LLM_PROVIDER=mock`) 통과 뒤.

| 브랜치 | 머리 | 상태 | 할 일 |
|---|---|---|---|
| task/E4-L2d | 40e283e | 재작업 3 끝, Sonnet 재검증이 교대로 중단됐을 수 있음 | 재검증(E4-L2c 포함, diff에 templates·index.html 혼입 없는지) → 병합 + `docs/reports/E4-L2c_main.patch` → `E4-L2d_main.patch` 순서 적용 → `.env.example` 새 키(TRUST_XFF·UPLOAD_*·JOB_*) → README 75행(동시 상한·대기열) |
| task/SEC-5 | a288b3b | 빌드 끝, Sonnet 검증 중단(`docs/reports/SEC-5.verify.md` 부분) | 재검증: 스레드 재사용 시 옛 검색 상태가 남는지(검색 시작 때 thread-local 초기화 권장) → 병합 |
| task/E1-L1b | 65fbc66 | 재작업 2(잔존 실명 0, 두 방법), 재검증 3 중단(`E1-L1b.verify.md` 부분) | 재검증 PASS → **squash 병합**(이력에 실명). 그 뒤 E1-L1c 명령으로 색인 재빌드, 해시 대조 rc 0. 그 전에는 `index_elife*` DO_NOT_SERVE |
| task/E3-L1y | 06d902a | 빌드 끝, 구축 세션 검증 중단 가능 | 재검증(병렬=순차 결과, manifest 실제 모델) → 병합 |
| task/E5-L1e2e | 5d60ac2 | WIP: 1단계 끝, 8020 라이브 1회 미실행/진행 여부 보고서 확인 | 라이브 1회(대표 승인) 통과 → 병합 → **태그 v1**(Macro-F1 0.4864는 astra 측정 구분 표기) |
| task/E4-L2f·E4-L3m·E5-L3b | 9550073·88f1b51·28a1472 | 구축 세션 WIP(보고서에 남은 일) | 보고서 보고 이어서 |
| task/E6-pres2 | daee70e | 발표 후속 4 | 07:00 체크리스트(보고서 맨 위) |
| task/E3-L1d | 3fa1349 | 중지(대표 지시) | 선택 |

**백테스트 n=5**(대표 승인, real만, gpt-6.1-sol 양쪽): 구축 세션이 python으로 실행 중. 결과 `data/eval/riskset_neumann.sol.first5.jsonl`·`riskset_baseline_llm.sol.first5.jsonl`. 판정(블라인드 3명 다수결, `eval.judge_envelope`·`eval.judge_run`)은 Codex(§5.7 비상 판정) 또는 21:40 뒤 Claude Sonnet. 대표 블라인드 판정도 이 5편. 표기 "n=5(대표 결정, 비용 사유; 30→15→5), 통계적 결론 제한". 표본 규칙은 decisions 21:0x.

**지키기:** 실제 OpenAI는 `NEUMANN_LIVE_LLM_OK=1`(프로세스 환경변수) 있을 때만, astra 금지(코드가 sol로 바꿈). 모든 명령에 `NEUMANN_LLM_PROVIDER=mock` 명시(옛 프로세스 환경 잔존). worktree에서 `git stash` 금지. 8020 실서버는 구축 세션 소유(재기동 명령은 아래 "지금 상태").

## ⚠ 최종 마감 (대표 지시): 발표자료 제출 10/01 09:00

| 시각 | 할 일 |
|---|---|
| ~07:00 | 발표 숫자 동결(v2 지표: 백테스트·Macro-F1·근거 연결률) |
| ~07:30 | 시연 영상 최종 녹화(E6-L3b, ffmpeg로 mp4), 프로토타입 주소(터널) 확정 |
| ~08:30 | 발표자료(키트 `발표자료/본선_발표자료.pptx`) 빈칸 10·11·12·13쪽 + 주소·영상 채우기 |
| 09:00 전 | PDF 저장과 제출 |

- **실제 OpenAI 호출 제한(대표 상시 규칙):** OpenAI API는 실제 서비스(사람이 쓰는 8010·공개 서버)와 태그급 성공 뒤 대표가 승인한 확인 테스트에서만 쓴다. `NEUMANN_LLM_PROVIDER=openai`와 `NEUMANN_LIVE_TESTS=1`은 PM이 대표 승인을 받은 과제에서만 켠다. 개발·빌드·검증·단위 테스트·측정은 mock이나 로컬로 한다. 설정 기본 provider는 mock이다. 구독(Claude·Codex) 에이전트가 만든 오프라인 결과를 제품 데이터에 쓰면 생성 방식을 "Claude/Codex 오프라인"으로 표기한다

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
- Codex PM 시작(대표): Codex 앱을 `C:\Users\User\Desktop\project_neumann`에서 열고, 모델 `gpt-6-astra`(추론 high)로 "`AGENTS.md`, `docs/HANDOFF.md`, `docs/tasks/QUEUE.md`, `out/dashboard/README.md`를 읽고 PM을 이어받아라". 대시보드 http://127.0.0.1:8099 (꺼져 있으면 `out/dashboard/start_dashboard.cmd`), usage.json·attention.json 갱신 규칙은 그 README.
- Codex 빌더·검증: `bash scripts/codex_task.sh build <과제ID>`(astra), `bash scripts/codex_task.sh verify <과제ID>`(sol, 빌더와 다른 모델). 백그라운드로 여러 개 띄워도 된다. 인계 뒤 병합 조건은 `python scripts/verify.py` 통과와 sol 검증 PASS.
- **평가 판정은 Codex로 하지 않는다**(계획서 §5.7). 21:40 뒤 Claude가 한다. Claude로 못 하게 되면 §5.7 비상 판정.

## 지금 상태 (2026-09-30 20:5x, PM "로컬 세팅")

- 과제 현황과 다음 할 일은 **`docs/tasks/QUEUE.md`**의 "★ 20:00 교대 스냅숏"이 기준이다
- main(push됨): v0 뒤 E2-L1 검색 보정, E4-L1a 업로드 API, **E3-L1w 파이프라인 v1(10단계)**, E1-L1c(코드만), E4-L1e AI4S 예시·템플릿, E4-L1f 화면 업로드(PDF·DOCX), E6-docs 문서·README, E3-L1x 규칙 분야 판정
- 점검 서버 **`http://127.0.0.1:8020`**(구축 세션, main 체크아웃, openai·gpt-6.1-sol 명시)
- **대표 지시: astra 금지.** 제품·평가 모두 `gpt-6.1-sol`. SEC-3(task/SEC-3, 검증 중)이 병합되면
  - 실제 OpenAI 호출은 프로세스 환경변수 `NEUMANN_LIVE_LLM_OK=1`이 있을 때만 된다(.env에서는 읽지 않음). 없으면 mock으로 강등
  - 모델명에 astra가 있으면 `NEUMANN_ALLOW_ASTRA=1` 없이는 sol로 바뀐다
  - 실서버 기동: `OPENBLAS_NUM_THREADS=1 NEUMANN_LIVE_LLM_OK=1 NEUMANN_LLM_PROVIDER=openai NEUMANN_LLM_MODEL=gpt-6.1-sol python -m uvicorn neumann.api.main:app --host 127.0.0.1 --port 8020`(공개는 `scripts/serve.py --public` 또는 `scripts\serve_public.cmd`) → `/health`의 `llm.effective=openai`, `llm.model=gpt-6.1-sol` 확인
- **이미 떠 있는 Claude·Codex 앱 프로세스는 옛 사용자 환경변수(provider=openai, model=gpt-6-astra)를 물려받았다.** 21:40 인수 때 앱을 재시작하면 사라진다. 그 전까지 모든 명령에 `NEUMANN_LLM_PROVIDER=mock`을 명시한다
- **터널 공개 금지**: E4-L2c(재작업 재검증 중) → E4-L2d(재작업 재검증 중) → SEC-2 → 공개. 공개 기동 때 `NEUMANN_MAX_CONCURRENT=6`(E4-L2e 부하 시험), 같은 와이파이 심사위원 대비(기본값이면 5명 중 2명 거절, 아래 값이면 10명 접수) `NEUMANN_JOB_PER_IP=10 NEUMANN_JOB_RATE_PER_MIN=30 NEUMANN_RATE_PER_MIN=30 NEUMANN_JOB_POLL_PER_MIN=1200`, `NEUMANN_DAILY_BUDGET=0`, `NEUMANN_REQUEST_TIMEOUT_S=90`
- 공개 전 필수: SEC-4(이메일 정규식 ReDoS 선형화, 검증 중), SEC-5(검색 상태 스레드별·OpenAI 동시 요청 상한, 빌드 중), E4-L2d(L2c 포함), SEC-2
- verify는 **venv 파이썬**으로: `NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/verify.py`
- worktree에서 `git stash` 금지(공유돼서 과제 변경이 섞인다)

## 대시보드 메시지함

- 대시보드(http://127.0.0.1:8099)에 메시지함(대표 ↔ Claude·Codex·PM, `inbox.jsonl`)과 확인 항목 체크가 있다. **Codex(또는 인계받은 에이전트)는 메시지함을 읽고 확인·처리·완료로 답한다.** 대시보드 서버는 감시 스크립트가 죽으면 다시 띄우고 로그인 때 자동 시작한다.

## 도구·경로

- Python venv: `C:/Users/User/.venvs/neumann/Scripts/python.exe`. pip이 없으니 설치는 `uv pip install --python <venv python> <패키지>`. mcp SDK 2.2.0 설치됨
- 공유 데이터: `C:/Users/User/Desktop/project_neumann/data/`(processed·index·eval·cache·raw·precomputed·site·video)
- cloudflared: `C:/Users/User/tools/cloudflared/cloudflared.exe`. quick tunnel은 `tunnel --url http://127.0.0.1:<포트>`이고 재시작마다 주소가 바뀐다
- ffmpeg: `C:/Users/User/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.2-full_build/bin/ffmpeg.exe`
- Codex CLI: `%LOCALAPPDATA%\OpenAI\Codex\bin\<해시>\codex.exe`(최신 것을 `scripts/codex_task.sh`가 찾는다)

## 대표 지시 요약(누적)

- 제품: Neumann의 에이전트는 불완전한 연구계획을, 불완전한 거절 기록들을 모아 설명해 주고, 완전한 기획으로 다시 재탄생시켜 주는 에이전트다(대표 정의). 제품 LLM은 gpt-6.1-sol(astra 금지), 규칙은 비상 경로. 오늘 목표는 "재탄생"까지(v2).
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
