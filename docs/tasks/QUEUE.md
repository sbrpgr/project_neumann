# 과제 대기열 (PM이 병합·배정할 때마다 갱신)

인계 받는 쪽(Codex PM)은 이 표 위에서부터 진행한다. 실행은 `bash scripts/codex_task.sh build <과제ID>`, 검증은 `bash scripts/codex_task.sh verify <과제ID>`, 병합은 PM 규칙(`AGENTS.md`)대로. 상태: ✅ main 병합 · 🔍 검증 대기/중 · ⏳ 빌더 작업 중 · ⬜ 대기(착수 전) · ⛔ 막힘

마지막 갱신: 2026-09-30 20:5x (PM "로컬 세팅")

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
| E1-L1b eLife·EPMC 수집 | ❌ 재검증 FAIL(이전 25건 해소, 새 형식 3건: 대문자 성 서명·`&amp;` 공동 서명·답변 감사문) → PM 세션 빌더 재작업 2(오프라인) | 잔존 0(두 방법) 증명 후 재검증 → **squash 병합**. 그 전에는 eLife/EPMC 색인을 서비스에 쓰지 않는다 |
| E4-L2c 서빙 안정성 | 🔍 재검증 PASS-조건부(83754ff): 인코딩 우회 fail-closed, 혼입 0. 남은 것(E4-L1f 테스트 request_id, serve.py UTF-8)은 E4-L2d에서 고침. **공개 금지** | **E4-L2d 하나로 병합**(L2d가 L2c 포함), 패치 L2c → L2d 순서. SEC-4 먼저 |
| E4-L2d 비동기 작업 API | 🔍 PASS-조건부 → 재작업 중(구축 세션): E4-L2c 재병합·create_job 글자 상한, 작업 저장소 고갈 DoS(IP별 보관 상한·합류/캐시 POST 속도 제한) | E4-L2c 뒤 병합 + `E4-L2d_main.patch`. **터널 공개 전제**. 병합 뒤 README "동시 상한 2건, 대기열·속도 제한 예정"(75행) 갱신: 공개 기본값 동시 4·대기 30 |
| SEC-4 이메일 정규식 ReDoS | 🔍 task/SEC-4 386621a(PM), Sonnet 검증 중 | `models.contains_pii`·`redact_pii` 선형화(`email_spans`), 결과 동일. 공개 전 필수 |
| E3-L1x rule_fitness "neural" 오분류 | ✅ 병합(Sonnet PASS) | 남은 한계: `~인지 과제` 오탐, neuromorphic(후속 소과제, 선택) |
| E4-L1f 화면 업로드 | ✅ 병합(cf43101, Sonnet PASS) | 8020 재기동 시 반영. 발표 9쪽 "PDF·DOCX 포함" |
| E5-L1e2e 라이브 E2E AI4S 세트 | ⏳ 구축 세션(개발 mock, 8020 sol 라이브 정확히 1회, 재실행은 PM 승인) | v1 확인 실행 |
| E3-L1y 카드 뒤 단계 병렬·진행 보고 | ⏳ 구축 세션(pipeline.py만) | 검증에 manifest 실제 모델·단계 impl 확인 포함 |
| SEC-5 다중 사용자 동시성 | ⏳ PM 세션 빌더(mock) | E4-L2e 부하 시험 지적: 검색 상태 스레드별(index/search.py), OpenAI 동시 요청 프로세스 상한 `NEUMANN_LLM_MAX_INFLIGHT`(llm.py). 공개 전 필수 |
| E4-L2e 부하 시험 | 🔍 1b0c5e6(구축 세션), 검증 요청 | 동시 24건 오류 0, 권장 `NEUMANN_MAX_CONCURRENT=6` |
| SEC-2 재점검 | 대기 | E4-L2c·L2d 병합 뒤 → 통과하면 cloudflared 터널 공개(주소는 발표자료로) |
| E4-L1a 업로드 | ✅ 병합(2e38839, 긴 경계 400 수정 80e024c 포함) | 공개 전 `/upload/plan` 속도 제한(E4-L2c 보호 경로), 화면 문구 "정리 뒤 50,000자 상한" |
| E6-docs 문서·README | ✅ 병합(7049da9), 루트 README 교체(38b01e4) | 07:00 동결 때 숫자·상태 한 번 더 맞춤. SEC-3 병합 뒤 RUNNING에 LIVE_LLM_OK 두 줄 |
| E4-L1f 화면 업로드 → `/upload/plan` | ✅ 병합(cf43101) | 선택 개선: 업로드 AbortController 40초 |
| E6-pres2 발표자료 숫자 | 🔍 PASS-조건부(숫자 불일치 0) → 12·11쪽 문구, GPU "약 77초" 수정 중(구축 세션) | 설계 쪽 "설계"+"예정", 결과 쪽 실측만. 07:00 체크리스트: 테스트 수 동결 main 실측 1개, 백테스트 못 돌리면 "미측정"(15편 삭제), 터널 없으면 주소 칸 "로컬 시연·영상", 작업 메모·형광 제거 |
| E3-L1d 사전 추출 스크립트 | 중지·선택 병합 | 재개는 대표 승인 뒤, 데모 상위 논문만 `--work-ids` |
| **E5-L2b 백테스트** | ⏸ 보류(19:36 중지) | **대표 승인 뒤** `gpt-6.1-sol`로 Neumann·기준선 둘 다 15편(`--limit 15`), 새 검색(E2-L1) 병합 뒤 조건으로. 이어서 판정 Claude Sonnet 3명(§5.7) → 지표 → 태그 `v2` |

**발표 마감 10/01 09:00**(HANDOFF 맨 위 일정표)

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
