# core-final 독립 검증 (f54ef1d) — Claude Sonnet 5.5

**판정: main 병합 가능(데모용, 터널 닫힌 상태) — 공개(터널 열기) 전에는 아래 "공개 전 필수 수정" 7건이 풀려야 하고, 병합할 때 docs 충돌 2곳(HANDOFF·decisions)은 양쪽 유지로 풀어야 한다.**

- 대상: `codex/core-final-20261001` = `f54ef1d`(스크래치 워크트리 `pn_corefinal`, 읽기 전용). 비교 main은 검증 끝 시점의 `c8c6b32`.
- 조건: 전부 `NEUMANN_LLM_PROVIDER=mock`, `OPENBLAS_NUM_THREADS=1`. `NEUMANN_LIVE_LLM_OK`는 한 번도 켜지 않았다(실제 API 호출 0). `.env`는 열지 않았다. 서버는 띄우지 않았다(Starlette TestClient, 프로세스 안). 그래서 8010·8020·8099·8171을 건드리지 않았고 8150~8199 포트도 쓰지 않았다(점검 중 보인 8163·8172는 다른 에이전트 것). 워크트리는 끝까지 `git status` 깨끗, 커밋·stash 없음.
- 데이터: main `data/index`(98MB)만 스크래치로 복사해 `NEUMANN_DATA_DIR`로 썼다(캐시·예산·로그가 공유 `data/`에 쓰이지 않게). bge-m3는 공개자료 로컬 폴더, 오프라인.
- 한계: mock 응답 기준이다. 실제 LLM의 적합성 판정·카드 품질은 재지 않았다. 브라우저 화면은 직접 조작하지 않았다(QA-2 `docs/reports/QA-2.md`가 같은 후보의 화면 흐름을 다뤘다). 시간 상자(30분)는 넘겼다(전체 pytest 2회 포함).
- 셸 환경에 `NEUMANN_LLM_PROVIDER=openai`와 API 키가 있었다. 모든 점검 스크립트에서 provider를 mock으로 덮어썼고, 키 값은 출력하지 않았다. 내 출력 파일 전부를 "키 값이 들어 있는지"로 대조했고(값 출력 없음) 0건이었다.

## 점검 결과 표

| # | 항목 | 방법 | 결과 | 판정 |
|---|---|---|---|---|
| 1a | 입력 관문: 300자 미만 거절(동기) | `/premortem`·`/premortem/view`에 250·299자 | 200, `status=degraded`, `input_quality.level=reject`·`rejected_thin_input`, 위험카드 0, **LLM 호출 0**, 화면 문구 "입력이 300자 미만이라 연구계획서로 분석하지 않습니다…" | 통과 |
| 1b | 300자 미만 거절(작업 경로) | `/premortem/jobs` 250·299자 | **202로 잡(job)을 만들고** 같은 거절 결과로 끝남, LLM 호출 0. 입구에서 막지 않는다 → E2E-2 설계 공백 **확인됨**(관문 자리·속도 제한 1칸·예산 1단위·잡 저장소 1칸을 쓰고, 끝난 잡은 TTL 15분 보관) | 동작 정상 / 설계 공백 있음(공개 전 수정) |
| 1c | 경고 구간 | 300자·450자·559자(요소 2/4)·357자 | 모두 `warn_short_input`, 경고 문구 + 전체 분석(300자 26회, 450자 32회 mock 호출, 카드 5장). 559자·2요소는 분야 수준 **규칙 카드 3장**(generator=rule, 화면 "비상 규칙", 알림 "규칙으로 만들었다(LLM 생성 아님)", ZIP README·리포트에도 "분야 수준"·"비상 규칙") | 통과 (라벨 문구는 결정문과 다름 → 표 5 참고) |
| 1d | 정상 분량·범위 밖 | 1089자 계획서 / 요리법 980자 | 계획서 `ok`, 카드 6장. 요리법은 **fitness 1회 호출 뒤 카드 0, 검색 안 함**(거절). 다만 머리 문구가 "입력이 짧아 결과 신뢰도 낮음"(QA-2 Q2-4와 같은 현상) | 통과(표시 결함 경미) |
| 2a | 근거 게이트: 심사평 | 생성 뒤 결과에 문장을 끼워 넣어 `build_ui_view`·`build_package_files`로 측정. 근거 id에 유령 id 섞음·빈 배열·유령만·다른 카드 근거·없는 카드 id·카드 비움·`c` 키 없음·문자열·dict(섹션 3종 × 7모양 = 21건) | **화면 본문 목록에 0건**(감사 목록에만 "제외됨"으로, 제외 수 "근거 없는 항목 1개 제외"). ZIP 9파일 어디에도 문장 원문 0건. 중복된 **유효** id만 통과(정상) | 통과 — 알려진 반례(혼합 id 화면 방어선·내보내기 `_report`) **닫힘** |
| 2b | 근거 게이트: 체크리스트 | 근거 빈 항목·유령 id·혼합 id 끼워 넣기 | 화면 체크리스트·ZIP 모두 0건, `checklist_audit.note`="근거 없는 항목 1개 제외" | 통과 |
| 2c | 2차 검증 | 기존 테스트 `test_second_validation_catches_items_that_bypassed_the_checklist_gate`·`test_apply_validation_regates_checklist_it_is_given`(전체 pytest에 포함) | 통과 | 통과 |
| 3a | 수정 권고 F1(422가 자리를 놓아줌) | 공개 설정(동시 4·대기 30·IP당 분당 6)에서 한 IP가 422 6종(본문 오류·result 계약 위반·plan_mismatch·카드 id 9개·빈 계획서·assemble 본문 오류) + 7건 더 | 매 건 뒤 `gate.active=0 waiting=0`, 예산 사용량 불변(환불). 같은 IP는 7건째부터 429(자기 한도), **다른 IP의 `/premortem`은 200(1.3초)** — 504 없음. 작업 경로 빈 본문도 자리 0 | 통과(F1 닫힘) |
| 3b | F2(저자 답변 없이 "대응 있음") | 코드(`revise.py`의 `PRECEDENT_NOT_ACCEPTED`: 같은 채택 논문의 저자 답변 인용 필수) + 기존 테스트 `test_precedent_requires_same_accepted_author_response`(전체 pytest 포함). mock 권고는 `precedents.status=none` | 통과 (실제 LLM 출력으로는 못 봄) | 통과(코드·테스트) |
| 3c | F3(카드 상한) | 카드 20장 결과로 `card_ids` 없이 → 422 `too_many_cards`, **LLM 호출 0**, 자리·예산 반납. 카드 8개 지정 → 200(호출 8). 9개 → 422 | 통과 | 통과(F3 닫힘) |
| 3d | F4(위조 result·revision) | 결과를 고치고 옛 서명을 붙이면 `origin=client_submitted_unverified`, `revision_sig=null`. 위조 revision(generator=astra, 지어낸 수치 / 지어낸 기관명)을 assemble → **422** `invalid_revision_proposal`. result 없이 위조 revision도 422. 정상 서명 사슬은 200·`server_signed`·라벨 "mock (mock-deterministic-v1)" | 통과 (단, 미서명·정상 문안의 "위조 generator" 표기 경로는 위 422 때문에 라벨까지 못 봄) | 통과(F4 닫힘) — 단 표 5의 A3~A6은 별개 |
| 4a | SEC-3 실제 호출 잠금·astra 금지 | 환경 provider=openai, 플래그 없음 | `make_llm` → mock, 직접 만든 `OpenAIProvider`는 client=None·`config_error="실제 호출 잠김"`, `complete_json` → `ok=False`. `guard_model("gpt-6-astra")`·`GPT-6-Astra-x` → `gpt-6.1-sol`. `/view` 결과 generators `{'mock': 6}` | 통과 |
| 4b | DO_NOT_SERVE 사전 점검 | `scripts/serve.py`의 `preflight_public`을 가짜 설정(값 없는 자리 문자열)으로 | DO_NOT_SERVE.txt가 있는 색인 → 거부(폴더 이름만 출력), 깨끗한 색인 → 통과, provider=mock → 거부. **이 점검은 `serve.py --public`에서만 돈다**(`src/`에는 없음) | 통과(적용 범위 제한 → 공개 전 수정) |
| 4c | `/health` | 기본·공개 모드 | 기본: status·version·commit·started_at·pipeline·stages·routers·`llm`(키 "있음" 불린만). 공개: status·version·commit·pipeline·llm(effective·model·live_llm_ok)·accepting뿐. 환경의 비밀값 문자열·경로 포함 0 | 통과 |
| 4d | 내보내기 서명 라벨 | 화면 결과+서명 → `/premortem/package` | 정상: 200, `server_signed`, `signed_result_plan`, 9파일. 결과 변조+옛 서명: `client_submitted_unverified`. 서명 없음: `client_submitted_unverified`. (mock 결과는 README·리포트·ai_context·plan_annotated 4개 마크다운 모두 "mock"·"모의" 표기) | 통과 |
| 5 | 알려진 차단 5종 | 아래 표 5 | 데모 흐름에서 닿는 것 **0** | 아래 참고 |
| 6 | `git merge-tree` | main `c8c6b32` ← f54ef1d | **소스 충돌 0**. 텍스트 충돌 2곳: `docs/HANDOFF.md`(main은 "07:00 완성 기준" 절을, 후보는 "Codex 핵심 후보" 절을 같은 자리에 추가), `docs/decisions.md`(양쪽이 끝에 덧붙임). 양쪽 유지로 풀면 된다. 계약(`contracts/`)은 추가만(삭제 1줄은 쉼표), `models.py`·`config.py`·`AGENTS.md` 변경 0. main의 테스트 env 정리(f163183)와도 충돌 없음 | 통과(문서 충돌 해소 필요) |
| 7 | 전체 pytest(mock) | 워크트리에서 | 1회차(`-x`): 100%까지 실패 0. 2회차(내 부하 큰 점검과 동시에): **2172 passed, 49 skipped, 10 failed** — 10건 전부 업로드·PDF 작업자 시험(`test_sec7` 4·`test_upload` 4·`test_webui_upload` 2), 메시지는 "파일 처리 시간이 상한(10초)". 같은 3파일을 **부하 없이 다시: 140 passed**. PM 측정(2182 passed·49 skipped·0 failed)과 모순 없음 | 통과(부하 민감) |

### 표 5 — 알려진 차단의 재현과 데모 흐름 도달 여부

| 차단 | f54ef1d 실측 | 데모 흐름에서 닿나 | 심각도(데모 / 공개) |
|---|---|---|---|
| A3~A6 산출물 상호 결합 | **A3·A5 재현**: 서버 서명된 result·revision·revised_plan을 `/premortem/package`에 섞어 보내면 200, `server_signed`, README "통합본 출처: server_signed", 11파일. A3은 통합본의 원천 카드가 없는 다른 서명 결과를 붙여도 통과, A5는 결정 "기각"을 붙여도 통합본에는 "채택"이 남는다 | **아니오.** 화면 내보내기(`index.html:979`)는 `result`·`result_sig`·`decisions`만 보낸다. 이 후보엔 수정 권고 화면이 없고(QA-2 Q2-1) `/premortem/revise*`는 API 전용. 서명된 산출물 여러 개를 직접 조합해야 한다 | 낮음 / 중간(출처 표기 신뢰 훼손, 권한·비용 상승은 없음) |
| `audit.dropped_reasons` int/list → 500 | **재현**: 미서명 결과의 `expected_review.audit.dropped_reasons`가 정수·리스트면 HTTP 500(`TypeError`, 응답엔 사용자 문구뿐), 문자열은 422, dict·null은 200 | **아니오.** 서버가 만든 audit는 `reasons`만 갖고 `dropped_reasons`는 없다(실측 키 목록 확인). 직접 만든 JSON만 닿는다 | 낮음 / 낮음~중간(500 잡음·로그) |
| UI 마크다운 mock 표기 | 이 후보에서는 **정상**: ZIP 마크다운 4종이 모두 mock임을 적고, 화면 배지 "모의(mock)". 알려진 FAIL은 이 후보에 없는 UI 브랜치(c18d38d) 기준. 남은 것은 QA-2 Q2-7(mock인데 헤더 "분석 파이프라인 연결"·"OpenAI API로 전송" 고지) | 닿지만 표기 자체는 충분. 헤더·고지만 부정확 | 낮음 / 낮음 |
| JUDGE unknown-ID | `a27facd`가 **후보에 없음**. 오프라인 평가 도구(`eval/judge_*`)라 서버 경로와 무관. 실행하지 않았다 | 아니오 | 없음 / 지표 보고 전 수정 |
| baseline 재시도 상태·캐시 키 | `58b56fb`가 **후보에 없음**. 오프라인 평가(`eval/baseline_llm.py`). 코드만 읽었다(`cache_key`가 요청 모델 대신 provider.model을 씀). 실행하지 않았다 | 아니오 | 없음 / 지표 보고 전 수정 |

## 후보에 없는 Codex 안정 커밋 (병합해도 이 수정들은 들어오지 않는다)

`git merge-base --is-ancestor`로 확인: `89f922c`(서빙 예약 수명), `d99075c`(수집기 전화번호 가림), `f59e95b`(E3 의미 게이트), `c6e1564`(E3 공급자 오류 안전), `618e466`(E3 호출 시점 잠금), `dd8491c`(PII·질의 캐시), `58b56fb`, `a27facd`, `c18d38d`, `2db1a25`, `4680299` 등은 f54ef1d의 조상이 **아니다**. 포함된 것은 `26e5339`(내보내기 원문 상한+audit 모양)까지다. main 기준으로는 순개선이지만, 공개 안전 주장의 근거로 쓰면 안 된다.

- 큐 취소 실측(예약 수명 대용): 동시 1 설정에서 대기 중인 요청을 클라이언트가 끊어도 자리·대기는 모두 비워진다(`active=0 waiting=0`). 다만 끊긴 요청의 분석은 **끝까지 돌고 예산 1단위를 쓴다**(환불 없음). 실제 API라면 비용이다.

## 공개(터널 열기) 전 필수 수정

1. **A3~A6 결합 검사** — `/premortem/package`가 revision·revised_plan을 받을 때 result 세션·카드, 통합본의 edit/card/종류·원문·근거 id, 결정 충돌, 렌더 스냅샷을 검사하거나, 못 하면 "결합 미검증"으로 표기. (A3·A5 재현됨, 보고서 `core-hmac-pairing-stop.md`의 5줄 계획 그대로)
2. **`audit.dropped_reasons` 모양 검사** — `export.py` 209·340행의 `dict(audit.get("dropped_reasons") or {})`가 정수·리스트에서 500. 타입 검사 뒤 422 또는 무시.
3. **300자 미만을 입구에서 거절** — `/premortem/jobs`·`/premortem`·`/premortem/view`가 관문·속도 제한·예산·잡 저장소를 쓰기 전에(공백 포함 300자 기준, 본문 파싱 전 값싼 검사) 422로 돌려준다. 지금은 LLM 0회지만 자리·속도 제한·예산·잡 칸을 쓴다.
4. **서빙 예약 수명 수정 병합(`89f922c`) 뒤 재검증** — 끊긴 요청의 분석·예산 환불, 전날 예산 환불이 새 날에 섞이는 문제(일일 예산 기본 꺼짐이라 켤 때 영향).
5. **DO_NOT_SERVE 검사를 서버 본체로** — 지금은 `scripts/serve.py --public`에서만 본다. `uvicorn`을 직접 띄우거나 `NEUMANN_INDEX_DIR`를 금지 색인으로 바꾸면 그대로 서비스된다. 색인 열기(`make_backend`) 시점에 거부해야 한다.
6. **후보에 없는 안정 커밋 판단** — `618e466`(호출 시점 잠금), `c6e1564`(공급자 오류에 키·헤더가 안 남는지), `dd8491c`(질의 캐시·PII), `f59e95b`, `d99075c`는 독립 검증이 끝나지 않았거나(`c6e1564`·`f59e95b` "independent unfinished") 이 후보에 없다. 공개하려면 병합과 재검증이 필요하다.
7. **업로드 작업자 10초 상한의 부하 민감성** — 부하가 있으면 정상 PDF·DOCX가 "처리 시간 상한" 413으로 떨어진다(이번 2회차 10건). 공개·다중 사용자에서는 오탐 거절이 된다. 상한·작업자 기동 방식 재검토.

## 그 밖의 메모 (차단 아님)

- 분야 수준 규칙 카드의 라벨: 결정(23:0x)은 "분야 수준 참고 · 계획서와 대조 안 됨"을 못박았는데, 코드·화면에는 그 문구가 없다(`generator=rule`·"비상 규칙" 배지, 알림 "분야 수준 카드 3장을 규칙으로 만들었다(LLM 생성 아님)", ZIP에 "분야 수준"). 정직성 요건(LLM 아님 표시)은 충족. 문구를 맞출지는 PM 판단.
- 범위 밖 글의 머리 문구가 "입력이 짧아 결과 신뢰도 낮음"(QA-2 Q2-4)이고, 거절 화면이 리포트 틀 그대로다(Q2-11).
- 이 후보에는 수정 권고·재탄생 화면이 없다(QA-2 Q2-1). 07:00 기준의 2·3단계는 FIN-UI·E4-L4r 병합 뒤에야 화면으로 보인다. 서랍 scrim 버그(Q2-2)는 그대로다.
- 점검 방법 메모: Starlette `TestClient`를 `with` 없이 쓰면 요청마다 이벤트 루프가 닫혀 백그라운드 작업(jobs)이 취소되어 모든 작업이 `internal` 오류로 끝난다. 처음에 이걸 제품 결함으로 오인할 뻔했다. `with TestClient(app)`으로 써야 한다(제품 문제가 아님).
- 재현 스크립트는 스크래치패드 `v/`(`gate.py`·`ev_probe.py`·`ev_probe2.py`·`f1.py`·`f34.py`·`sec.py`·`blockers.py`·`pairing.py`·`leak.py`)에 있다. 저장소에 넣지 않았다.
