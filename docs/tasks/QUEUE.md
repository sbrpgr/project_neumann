# 과제 대기열 (PM이 병합·배정할 때마다 갱신)

인계 받는 쪽(Codex PM)은 이 표 위에서부터 진행한다. 실행은 `bash scripts/codex_task.sh build <과제ID>`, 검증은 `bash scripts/codex_task.sh verify <과제ID>`, 병합은 PM 규칙(`AGENTS.md`)대로. 상태: ✅ main 병합 · 🔍 검증 대기/중 · ⏳ 빌더 작업 중 · ⬜ 대기(착수 전) · ⛔ 막힘

마지막 갱신: 2026-10-01 00:5x (PM "로컬 세팅") — PM 인수 완료. HANDOFF 맨 위 "PM 인수 완료" 절이 최신

## ⚠ 최종 마감: 발표자료 제출 10/01 09:00 (HANDOFF 표). 발표 작업(E6)을 모든 L3 확장보다 앞에 둔다

## ★ 20:00 교대 스냅숏 (PM "로컬 세팅" 19:48) — 이것이 최신

**원칙:** 실제 OpenAI 호출은 실서비스·프로토타입 검증(시연·대표 점검·승인된 확인 테스트)만. 개발·빌드·검증은 mock(설정 기본값 mock). 제품 기본 모델 `gpt-6.1-sol`. 이미 잰 평가(E5-L1b Macro-F1 0.4864, 라이브 E2E, v0)는 `gpt-6-astra`로 쟀다고 구분 표기.

**main 상태:** v0 태그(19:19). **점검 서버는 8020**(구축 세션이 main 497d3f8로 기동, openai·gpt-6.1-sol, 로그 `pn_logs/server_8020.*.log`). 옛 8010(astra)은 19:50에 PM이 내림. 병합 30건 가까이(아래 표 + E2-L3·E5-L1b·E5-L0e2e·E4-S06·E4-L1c·E6-L3c). 8010 = main 체크아웃 실서버(19:10 기동, 당시 astra 기본값으로 떴음 → **재시작 시 sol**).

**열린 브랜치와 다음 행동**

| 과제 | 상태 | 다음 |
|---|---|---|
| E3-L1w v1 파이프라인 연결 | ✅ 병합(f204d0c) | **v1 태그 조건**: v1 기능 main(E3-L1w·E4-L1c·E4-L1e·E4-L1f·E2-L1·E5-L1b) + E5-L1e2e(구축 세션, --plans ai4s) 검증·병합 + 8020 sol 라이브 1회 통과 → PM이 `v1` 태그. Macro-F1 0.4864는 gpt-6-astra 측정이라 구분 표기 |
| **SEC-3 실제 호출 잠금 + astra 금지** | ✅ 병합(548d928) | 실서버 기동: `NEUMANN_LIVE_LLM_OK=1 NEUMANN_LLM_PROVIDER=openai NEUMANN_LLM_MODEL=gpt-6.1-sol` → `/health.llm` 확인 |
| E2-L1 검색 보정 | ✅ 병합(33dd641), .env.example 키 추가됨 | 병합 시 `.env.example`에 새 키 5개(SCORE_FLOOR는 비움), similar_works 유사도 정렬·무관 사유 노출은 E3 후속 |
| E4-L1e 입력 예시·템플릿 AI4S 정렬(대표 지시) | ✅ 병합(0504255, Sonnet PASS) | 새 예시 사전 계산본·정적 판 DEMO_PLANS 교체는 API 사용 → 대표 승인 대기 |
| E1-L1c eLife(+EPMC) 색인 | ✅ 코드만 병합(43d116f). 색인 `index_elife*`는 DO_NOT_SERVE 유지 | E1-L1b PASS 뒤 재빌드(입력 해시 rc 0). 권고: 색인 로더가 DO_NOT_SERVE를 거부(E2, 선택) |
| E1-L1b eLife·EPMC 수집 | 🔍 재검증 3 PASS-조건부(실명 잔존 0, 부분 가림 3건 `’`·`–`) → 재작업 3 중(PM 세션) | 재검증 → **squash 병합** → 색인 재빌드(해시 rc 0) |
| E4-L2c 서빙 안정성 | 🔍 재검증 PASS-조건부(83754ff): 인코딩 우회 fail-closed, 혼입 0. 남은 것(E4-L1f 테스트 request_id, serve.py UTF-8)은 E4-L2d에서 고침. **공개 금지** | **E4-L2d 하나로 병합**(L2d가 L2c 포함), 패치 L2c → L2d 순서. SEC-4 먼저 |
| E4-L2d 비동기 작업 API(L2c 포함) | ✅ 병합(2bd2b58, 패치·키 03503d6) | 8020 재기동(구축 세션). 공개는 SEC-2r 필수 조치 뒤 |
| SEC-4 이메일 정규식 ReDoS | 🔍 task/SEC-4 386621a(PM), Sonnet 검증 중 | `models.contains_pii`·`redact_pii` 선형화(`email_spans`), 결과 동일. 공개 전 필수 |
| E3-L1x rule_fitness "neural" 오분류 | ✅ 병합(Sonnet PASS) | 남은 한계: `~인지 과제` 오탐, neuromorphic(후속 소과제, 선택) |
| E4-L1f 화면 업로드 | ✅ 병합(cf43101, Sonnet PASS) | 8020 재기동 시 반영. 발표 9쪽 "PDF·DOCX 포함" |
| E5-L1e2e 라이브 E2E AI4S 세트 | ❌ 라이브 1회(8020 sol): plan.md·범위 밖 PASS, 단백질·신경 연산자 FAIL(체크리스트 1항목씩 근거 번호 없음). 결과 JSON 미저장 | E3-L1e(체크리스트 근거 게이트)·E3-L1s(분량 두 단계) 병합 → 라이브 1회(v1 확인+결과 JSON, 약 $2)+백테스트 사후 재실행(약 $2)을 한 번에 대표 승인 → v1 태그 |
| E3-L1y 카드 뒤 단계 병렬·진행 보고 | 🔍 795ec31 검증 중(구축 세션): 54.1→42.0초(mock), 결과 순차와 동일 | PM 결정: 순서 단언은 체크리스트→2차 검증만+병렬=순차 결과 동일 고정, EXTRACT_PARALLEL 24 유지, 캐시 임시 파일명 고유화. jobs.py 단계 표시는 E4-L2d 쪽 |
| SEC-5 다중 사용자 동시성 | ⏳ PM 세션 빌더(mock) | E4-L2e 부하 시험 지적: 검색 상태 스레드별(index/search.py), OpenAI 동시 요청 프로세스 상한 `NEUMANN_LLM_MAX_INFLIGHT`(llm.py). 공개 전 필수 |
| E4-L2e 부하 시험 | ✅ 병합(Sonnet PASS), 보고서 문구 정정 | 공개 기동 `NEUMANN_MAX_CONCURRENT=6` |
| SEC-4 이메일 ReDoS | ✅ 병합(5ed9b45) | — |
| E5-L2c 판정 경로 n=5 real만 | ⏳ PM 세션 빌더(mock 예행) | 결과 파일 오면 PM이 build → briefs → Sonnet 3명 → validate → aggregate |
| E6-L3d v1 라이브 결과로 사전 계산본·정적 판 | ⬜ 구축 세션이 띄움 | 추가 API 없음. E5-L1e2e 결과 JSON 필요 |
| E3-L1z 규칙 판정 조사·인지 오탐 | ⬜ 구축 세션이 띄움 | 선택 |
| 참고: 세부 설정 키(`NEUMANN_LLM_MAX_INFLIGHT`, `NEUMANN_EXTRACT_PARALLEL` 등) | — | `.env`에서 안 읽힘(config 필드 없음). 기동 명령 환경변수로 준다 |
| E2-L5 세부 분야 사다리·분야별 3건 실분석(추가 실험) | ⏳ 구축 세션 | 선정 규칙·충분 기준 사전 커밋, 모든 단계 보고. 실분석은 E3-L1s·E3-L1e 병합 뒤 v1 라이브·백테스트 사후 재실행과 묶음 |
| **우선 병합(00:2x)** | — | **v2 관문: E3-L1s·E3-L1e** → E4-L2f → E4-L3m → E4-L1g(샘플 갤러리, v2 필수) → E3-L2r·E4-L4r(재탄생). 공개 전 필수: PERF-pk·E4-L2g·OPS-tun·SEC-7. 그 밖: E4-L2h·E3-L1z2·TEST-1·E2-L5·E5-L3b 후속 + PM 과제 20개(SEC-8·DOC-1·A11Y-1·E2E-2·MCP-demo·E5-L1c·PERF-2·QA-1·REL-1·E5-L3c·LIC-1·JUDGE-H·CFG-1·OBS-1·PRIV-1·DATA-CARD·SYSTEM-CARD·PROMPT-AUDIT·FUZZ-1·UXC-1) |
| E3-L2r·E4-L4r 수정 권고(서버·화면) | ⏳ 구축 세션(Fable, mock) | 대표 지시 시제품 추가. 큐 맨 뒤 |
| E5-L2f 원문 복원 백테스트(추가 실험) | ⬜ 사전 기록(decisions 23:5x), arXiv 다운로드는 대표 승인 뒤 | 표본 순서·arXiv 공개판 필수·v1 우선, A/B/C 판정 재사용 |
| E5-L2e 쌍비교(RFP) | ⏸ 보류(RFP 취소) | — |
| SEC-2 재점검 | 대기 | E4-L2c·L2d 병합 뒤 → 통과하면 cloudflared 터널 공개(주소는 발표자료로) |
| E4-L1a 업로드 | ✅ 병합(2e38839, 긴 경계 400 수정 80e024c 포함) | 공개 전 `/upload/plan` 속도 제한(E4-L2c 보호 경로), 화면 문구 "정리 뒤 50,000자 상한" |
| E6-docs 문서·README | ✅ 병합(7049da9), 루트 README 교체(38b01e4) | 07:00 동결 때 숫자·상태 한 번 더 맞춤. SEC-3 병합 뒤 RUNNING에 LIVE_LLM_OK 두 줄 |
| E4-L1f 화면 업로드 → `/upload/plan` | ✅ 병합(cf43101) | 선택 개선: 업로드 AbortController 40초 |
| E6-pres2 발표자료 숫자 | 🔍 PASS-조건부(숫자 불일치 0) → 12·11쪽 문구, GPU "약 77초" 수정 중(구축 세션) | 설계 쪽 "설계"+"예정", 결과 쪽 실측만. 07:00 체크리스트: 테스트 수 동결 main 실측 1개, 백테스트 못 돌리면 "미측정"(15편 삭제), 터널 없으면 주소 칸 "로컬 시연·영상", 작업 메모·형광 제거 |
| E3-L1d 사전 추출 스크립트 | 중지·선택 병합 | 재개는 대표 승인 뒤, 데모 상위 논문만 `--work-ids` |
| **E5-L2b 백테스트 n=5** | ✅ 실행(real, sol)·판정(Sonnet 3명, 재판정 뒤 일치 0.947). Neumann 낸 위험 4/4 A·근거율 1.0, 0장 3편 → hit@3 0.4 대 기준선 0.8 | 결과 `data/eval/judge_n5_results.md`. 대표 블라인드 판정 꾸러미 `judge_n5/human`. E5-L2c 검증 중 → 병합 |

**발표 마감 10/01 09:00**(HANDOFF 맨 위 일정표)


## PM 세션 과제 20개 (00:3x 가동, 브랜치는 `git log --all --oneline --grep '^\[<ID>\]'`로 찾는다)

| ID | 내용 | 산출 | 상태 |
|---|---|---|---|
| SEC-8 | 공개 직전 보안 재감사(Fable, 읽기 전용) | docs/reports/SEC-8.md | ⏸ 인수 신호로 WIP 정지(검증 전) |
| DOC-1 | 심사위원용 README·ARCHITECTURE·API·RUNNING | 문서 4개 | ⏸ 인수 신호로 WIP 정지(검증 전) |
| LIC-1 | 라이선스·출처 점검, 고지 문구 | docs/LICENSES.md | ⏸ 인수 신호로 WIP 정지(검증 전) |
| A11Y-1 | 화면 접근성 감사(보고서만) | docs/reports/A11Y-1.md | ⏸ 인수 신호로 WIP 정지(검증 전) |
| E2E-2 | jobs 경로 다중 사용자 E2E(mock) | tests/e2e/test_jobs_multiuser* | ⏸ 인수 신호로 WIP 정지(검증 전) |
| MCP-demo | 외부 에이전트 MCP 연결 시연 | scripts/mcp_demo.py, docs/MCP_DEMO.md | ⏸ 인수 신호로 WIP 정지(검증 전) |
| E5-L1c | P1 Macro-F1 sol 재측정 준비(실행 안 함) | docs/reports/E5-L1c_plan.md | ⏸ 인수 신호로 WIP 정지(검증 전) |
| PERF-2 | 분석 지연 단축 연구(모의) | scripts/perf_sim_pipeline.py | ⏸ 인수 신호로 WIP 정지(검증 전) |
| QA-1 | 시연 흐름 QA(보고서만) | docs/reports/QA-1.md | ⏸ 인수 신호로 WIP 정지(검증 전) |
| REL-1 | 07:00 동결 시트·태그 절차 | scripts/release_check.py, docs/RELEASE.md | ⏸ 인수 신호로 WIP 정지(검증 전) |
| E5-L3c | 지표 generator 분리(rule ≠ LLM 적중) | eval/, tests/e5 | ⏸ 인수 신호로 WIP 정지(검증 전) |
| JUDGE-H | 대표 블라인드 판정 HTML 양식 | eval/human_form.py | ⏸ 인수 신호로 WIP 정지(검증 전) |
| CFG-1 | .env 읽기 일관화(SEC-3 플래그 제외) | config.py | ⏸ 인수 신호로 WIP 정지(검증 전) |
| OBS-1 | 운영 사용량·비용 보고 | scripts/ops_report.py | ⏸ 인수 신호로 WIP 정지(검증 전) |
| PRIV-1 | 개인정보·보존 감사(보고서만) | docs/reports/PRIV-1.md | ⏸ 인수 신호로 WIP 정지(검증 전) |
| DATA-CARD | 코퍼스·색인 데이터 카드 | docs/DATA_CARD.md | ⏸ 인수 신호로 WIP 정지(검증 전) |
| SYSTEM-CARD | 시스템 카드(모델·한계) | docs/SYSTEM_CARD.md | ⏸ 인수 신호로 WIP 정지(검증 전) |
| PROMPT-AUDIT | 제품 프롬프트 감사(보고서만) | docs/reports/PROMPT-AUDIT.md | ⏸ 인수 신호로 WIP 정지(검증 전) |
| FUZZ-1 | 공개 API 퍼징 테스트 | tests/e4/test_fuzz_api.py | ⏸ 인수 신호로 WIP 정지(검증 전) |
| UXC-1 | 화면 문구 정직성·용어(보고서만) | docs/reports/UXC-1.md | ⏸ 인수 신호로 WIP 정지(검증 전) |

모든 과제는 빌드 뒤 다른 모델(Sonnet) 검증이 병합 조건. 보고서만 쓰는 과제는 내용 검토 뒤 docs 병합.

## v0 크리티컬 패스

| 과제 | 상태 | 브랜치 | 다음 할 일 |
|---|---|---|---|
| E0·E0b 골격·데이터 모델 | ✅ | — | — |
| E1-L0 코퍼스(1,128편) | 🔍 Sonnet 검증 중 | task/E1-L0 | PASS면 병합 → `python scripts/build_index.py`로 색인 재빌드(load_corpus 경로) |
| E2-L0 검색 색인 | 🔍 Sonnet 검증 중 | task/E2-L0 | PASS면 병합 |
| E3-L0 astra 분석 파이프라인 | ⏳ | task/E3-L0 | 끝나면 검증 → 병합. **v0 통합**: 서버 재시작 → 데모 3건 실제 astra 실행 → 근거 연결 검사 → 스크린샷 → 태그 `v0` → push |
| E4-L0 API·화면 | ✅ | — | — |
| E5-L0 근거 연결 검사기 | ✅ | — | verify.py에서 부르는 연결은 v0 통합 때 |

## 앞당긴 L1~L3 (병렬)

| 과제 | 상태 | 담당 세션 | 비고 |
|---|---|---|---|
| E5-L1a DISAPERE 골드·Macro-F1 | ✅ | PM | 빈도 기준선 0.3308 |
| E4-L2a 내보내기 ZIP | ✅ | PM | main.py 연결됨 |
| E1-L2 Retraction Watch | 🔍 검증 중 | PM | |
| E5-L2a 백테스트 데이터셋·기준선·판정 실행기 | ⏳ | PM | |
| E4-L2b MCP 서버 | ⏳ | PM | |
| E1-L1b eLife·Europe PMC | ⏳ | PM | 컷 1순위 |
| E3-L1a 예상 심사평·근거 게이트 | ⏳ | PM | llm_call 주입 방식, E3-L0 뒤 연결 |
| E3-L1b 체크리스트·2차 검증 | ⏳ | PM | 〃 |
| E3-L1c 적합성·PII | ⏳ | PM | 〃 |
| E4-L1a 업로드 파서 | ✅ | PM | main.py 자동 연결(선택 라우터) |
| E1-L3 규모 확대(샤드 6개, 2,000편+) | ⏳ | PM | data/processed_l3/ |
| E6-L2a 사전 계산본·오프라인 폴백 | ⏳ | PM | main.py 자동 연결 |
| E6-L3a 정적 배포 빌드(폴백) | ⏳ | PM | 주력은 라이브 서버(대표 지시) |
| E6-L3b 시연 녹화 스크립트 | ⏳ | PM | 최종 녹화는 v2 뒤 |
| E4-L1b AI4S 템플릿·범위 안내 | ⏳ | 구축 세션 | 대표 지시 |
| E4-L2c 공개 서버 안정성 | ⏳ | 구축 세션 | 대표 지시(터널 공개, 토큰 없이) |
| E5-L0e2e 라이브 E2E | ⏳ | 구축 세션 | v0 뒤 실제 실행 |
| E4-L1d 메타 API | ⏳ | 구축 세션 | |
| E5-L3a 리포트 카드 생성기 | ⏳ | 구축 세션 | |
| E6-docs 문서 | ⏳ | 구축 세션 | |
| SEC-1 보안 점검 | ⏳ | 구축 세션 | |

## 착수 전 (선행 과제가 병합되면 바로)

| 과제 | 선행 | 내용 |
|---|---|---|
| E2-L1 검색 보정 | E2-L0 | 축별 가중치, 점수 하한 실측(무관 질의 0.23 vs 관련 0.36~0.49 → 하한 약 0.30), 한국어 질의 번역 결합 |
| E3-L1d 코퍼스 전체 astra 지적 추출 | E3-L0 | 심사평 5,366건 사전 추출 캐시(백그라운드, 병렬, 속도 제한 확인) |
| E5-L1b DISAPERE astra Macro-F1 | E3-L0, E5-L1a | 골드 148건에 astra 추출 → 채점(astra·비상 규칙 나눠 보고). 튜닝은 dev만 |
| E3-L1 연결 | E3-L0, E3-L1a·b·c | pipeline에 예상 심사평·체크리스트·2차 검증·적합성 연결 → 태그 `v1` |
| E5-L2b 백테스트 실행 | E5-L2a, v1 | 30편 × (Neumann·일반 LLM) × (진짜·셔플) 생성 → 판정(Claude Sonnet 3명, 판정 몫 한도 남김, 비상 시 Codex gpt-6-sol §5.7) → 지표 → 태그 `v2` |
| 터널 공개 | v0, E4-L2c, 대표의 cloudflared 승인 | quick tunnel 주소를 발표자료에(재시작하면 주소가 바뀜) |
