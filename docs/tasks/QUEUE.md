# 과제 대기열 (PM이 병합·배정할 때마다 갱신)

인계 받는 쪽(Codex PM)은 이 표 위에서부터 진행한다. 실행은 `bash scripts/codex_task.sh build <과제ID>`, 검증은 `bash scripts/codex_task.sh verify <과제ID>`, 병합은 PM 규칙(`AGENTS.md`)대로. 상태: ✅ main 병합 · 🔍 검증 대기/중 · ⏳ 빌더 작업 중 · ⬜ 대기(착수 전) · ⛔ 막힘

마지막 갱신: 2026-09-30 19:08 (PM "로컬 세팅")

## ⚠ 최종 마감: 발표자료 제출 10/01 09:00 (HANDOFF 표). 발표 작업(E6)을 모든 L3 확장보다 앞에 둔다

## ★ 20:00 교대 스냅숏 (PM "로컬 세팅" 19:48) — 이것이 최신

**원칙:** 실제 OpenAI 호출은 실서비스·프로토타입 검증(시연·대표 점검·승인된 확인 테스트)만. 개발·빌드·검증은 mock(설정 기본값 mock). 제품 기본 모델 `gpt-6.1-sol`. 이미 잰 평가(E5-L1b Macro-F1 0.4864, 라이브 E2E, v0)는 `gpt-6-astra`로 쟀다고 구분 표기.

**main 상태:** v0 태그(19:19). **점검 서버는 8020**(구축 세션이 main 497d3f8로 기동, openai·gpt-6.1-sol, 로그 `pn_logs/server_8020.*.log`). 옛 8010(astra)은 19:50에 PM이 내림. 병합 30건 가까이(아래 표 + E2-L3·E5-L1b·E5-L0e2e·E4-S06·E4-L1c·E6-L3c). 8010 = main 체크아웃 실서버(19:10 기동, 당시 astra 기본값으로 떴음 → **재시작 시 sol**).

**열린 브랜치와 다음 행동**

| 과제 | 상태 | 다음 |
|---|---|---|
| E3-L1w v1 파이프라인 연결 | 🔍 빌드 끝(실제 호출 0), Sonnet 검증 중(mock) — task/E3-L1w 19b3fc1 | 끝나면 Sonnet/sol 검증 → 병합 → 실서버 재시작(sol) → 대표 점검 → 태그 `v1` |
| E2-L1 검색 보정 | ✅ 병합(33dd641), .env.example 키 추가됨 | 병합 시 `.env.example`에 새 키 5개(SCORE_FLOOR는 비움), similar_works 유사도 정렬·무관 사유 노출은 E3 후속 |
| E4-L1e 입력 예시·템플릿 AI4S 정렬(대표 지시) | ⏳ 구축 세션(API 금지) | 예시: 전해액 GNN 유지 + 단백질-리간드·신경 연산자 PDE 기후 새로. 템플릿 5종 AI4S. 병합 뒤 사전 계산본·정적 판·시연 녹화의 예시도 맞출 것 |
| E1-L1c eLife(+EPMC) 색인(우선순위 낮아짐: 예시에서 fMRI·의료영상 제외) | a3a4251, `index_elife`·`index_elife_epmc`에 DO_NOT_SERVE 표시(E1-L1b 실명 FAIL) | 데모 3건 모두 살리려면 `index_elife_epmc` 후보. E2-L1 병합 뒤 `NEUMANN_INDEX_DIR` 전환 결정·서버 재시작(첫 분석에 API 사용 = 허용) |
| E1-L1b eLife·EPMC 수집 | ❌ FAIL(리뷰어 실명 22+3건) → PM 세션 빌더 재작업(오프라인) | 잔존 서명 0 증명 후 재검증 → 병합. **그 전에는 eLife/EPMC 색인을 서비스에 쓰지 않는다** |
| E4-L2c 서빙 안정성 | 🔍 af008bb 공격적 검증 중(구축 세션) | 병합 + `docs/reports/E4-L2c_main.patch` 적용. 공개 모드 `NEUMANN_DAILY_BUDGET=0`(대표 정정), 동시 상한·대기열·속도 제한 유지 |
| E4-L2d 비동기 작업 API | ⏳ 구축 세션 | E4-L2c 뒤 병합 + `E4-L2d_main.patch`. **터널 공개 전제**(Cloudflare 100초 제한) |
| SEC-2 재점검 | 대기 | E4-L2c·L2d 병합 뒤 → 통과하면 cloudflared 터널 공개(주소는 발표자료로) |
| E4-L1a 업로드 | 🔍 S-03 수정(31f0b88) 재검증 필요 | 재검증 PASS → 병합(라우터 자동 연결) |
| E6-docs 문서·README | 🔍 재검증 중 | 병합 + 루트 README를 `docs/reports/E6-docs_README_draft.md`로 갱신(PM 소유) |
| E6-pres2 발표자료 숫자 | ⏳ 구축 세션 | `data/deck/` 작업본. 백테스트 칸은 "측정 중" |
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
| E4-L1a 업로드 파서 | ⏳ | PM | main.py 자동 연결(선택 라우터) |
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
