# 과제 대기열 (PM이 병합·배정할 때마다 갱신)

인계 받는 쪽(Codex PM)은 이 표 위에서부터 진행한다. 실행은 `bash scripts/codex_task.sh build <과제ID>`, 검증은 `bash scripts/codex_task.sh verify <과제ID>`, 병합은 PM 규칙(`AGENTS.md`)대로. 상태: ✅ main 병합 · 🔍 검증 대기/중 · ⏳ 빌더 작업 중 · ⬜ 대기(착수 전) · ⛔ 막힘

마지막 갱신: 2026-09-30 20:0x (PM "로컬 세팅")

## ⚠ 최종 마감: 발표자료 제출 10/01 09:00 (HANDOFF 표). 발표 작업(E6)을 모든 L3 확장보다 앞에 둔다

## ★ 20:00 교대 스냅숏 (PM "로컬 세팅" 19:48) — 이것이 최신

**원칙:** 실제 OpenAI 호출은 실서비스·프로토타입 검증(시연·대표 점검·승인된 확인 테스트)만. 개발·빌드·검증은 mock(설정 기본값 mock). 제품 기본 모델 `gpt-6.1-sol`. 이미 잰 평가(E5-L1b Macro-F1 0.4864, 라이브 E2E, v0)는 `gpt-6-astra`로 쟀다고 구분 표기.

**main 상태:** v0 태그(19:19). **점검 서버는 8020**(구축 세션이 main 497d3f8로 기동, openai·gpt-6.1-sol, 로그 `pn_logs/server_8020.*.log`). 옛 8010(astra)은 19:50에 PM이 내림. 병합 30건 가까이(아래 표 + E2-L3·E5-L1b·E5-L0e2e·E4-S06·E4-L1c·E6-L3c). 8010 = main 체크아웃 실서버(19:10 기동, 당시 astra 기본값으로 떴음 → **재시작 시 sol**).

**열린 브랜치와 다음 행동**

| 과제 | 상태 | 다음 |
|---|---|---|
| E3-L1w v1 파이프라인 연결 | ✅ 병합(f204d0c, Sonnet PASS·mock), 단계별 설정 키 .env.example(cd0a3ca) | 8020을 main 최신으로 재기동(sol 명시) → 대표 점검 → 승인 확인 실행 1회 → 태그 `v1` |
| **SEC-3 실제 호출 잠금** | 🔍 task/SEC-3 ab3270f, Sonnet 검증 중 | 사용자 환경변수 provider=openai 사고 대응(변수는 대표 승인으로 삭제됨). 병합 뒤 실서버는 `NEUMANN_LIVE_LLM_OK=1 NEUMANN_LLM_PROVIDER=openai NEUMANN_LLM_MODEL=gpt-6.1-sol`로 기동, `/health.llm` 확인 |
| E2-L1 검색 보정 | ✅ 병합(33dd641), .env.example 키 추가됨 | 병합 시 `.env.example`에 새 키 5개(SCORE_FLOOR는 비움), similar_works 유사도 정렬·무관 사유 노출은 E3 후속 |
| E4-L1e 입력 예시·템플릿 AI4S 정렬(대표 지시) | 🔍 task/E4-L1e 66c0b82 검증 중(구축 세션, API 0) | 병합 → E4-L1f를 그 위에. 새 예시 사전 계산본·정적 판 DEMO_PLANS 교체는 API 사용 → 대표 승인 |
| E1-L1c eLife(+EPMC) 색인(우선순위 낮아짐: 예시에서 fMRI·의료영상 제외) | a3a4251, `index_elife`·`index_elife_epmc`에 DO_NOT_SERVE 표시(E1-L1b 실명 FAIL) | 데모 3건 모두 살리려면 `index_elife_epmc` 후보. E2-L1 병합 뒤 `NEUMANN_INDEX_DIR` 전환 결정·서버 재시작(첫 분석에 API 사용 = 허용) |
| E1-L1b eLife·EPMC 수집 | ❌ FAIL(리뷰어 실명 22+3건) → PM 세션 빌더 재작업(오프라인) | 잔존 서명 0 증명 후 재검증 → 병합. **그 전에는 eLife/EPMC 색인을 서비스에 쓰지 않는다** |
| E4-L2c 서빙 안정성 | ❌ FAIL(BOM·UTF-16 본문으로 입장 검사 우회, IPv6 /64 우회) → 재작업 중(구축 세션). **공개 금지**. ⚠ stash 사고로 E4-L1e 변경이 섞였음 → 병합 전 diff에 templates·index.html 없는지 PM 확인 | 병합 + `docs/reports/E4-L2c_main.patch` 적용. 공개 모드 `NEUMANN_DAILY_BUDGET=0`(대표 정정), 동시 상한·대기열·속도 제한 유지 |
| E4-L2d 비동기 작업 API | 🔍 999f3f9 빌드 끝(동시 5건 응답 최장 0.08초). E4-L2c 재작업 병합 뒤 재검증 | E4-L2c 뒤 병합 + `E4-L2d_main.patch`. **터널 공개 전제**(Cloudflare 100초 제한) |
| SEC-2 재점검 | 대기 | E4-L2c·L2d 병합 뒤 → 통과하면 cloudflared 터널 공개(주소는 발표자료로) |
| E4-L1a 업로드 | ✅ 병합(2e38839, 긴 경계 400 수정 80e024c 포함) | 공개 전 `/upload/plan` 속도 제한(E4-L2c 보호 경로), 화면 문구 "정리 뒤 50,000자 상한" |
| E6-docs 문서·README | 🔍 재작업 2(608373b) 재검증 3 중(Sonnet, PM 세션) | PASS → 병합 + 루트 README를 `docs/reports/E6-docs_README_draft.md`로 갱신(PM 소유). 07:00 동결 때 숫자·상태 한 번 더 맞춤 |
| E4-L1f 화면 업로드 → `/upload/plan` | ⏳ PM 세션 빌더(mock) | index.html은 readFile·드롭존·파일 카드만. **E4-L1e 먼저 병합, 그 위에 올림**. 발표 9쪽 표기가 이 병합 여부를 따름 |
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
