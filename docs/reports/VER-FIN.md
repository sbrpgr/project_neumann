# VER-FIN 보안 조기 검토 (FIN-ENGINE · FIN-TOOLS · FIN-UI)

- 검토자: claude-sonnet-5-5 (빌더와 다른 모델, 읽기 전용). 2026-10-01 KST.
- 대상: Codex 최종화 기반 `b629789`(= `codex/finalization-20261001`, `task/FIN-ENGINE`·`task/FIN-TOOLS`의 현재 HEAD), 그 위에 올라온 FIN-ENGINE `a3b973b`(도구 인터페이스), FIN-UI 브랜치(`task/FIN-UI`=`62ce57b`=E4-L4r, 최종화 코드 없음).
- 방법: 스크래치 워크트리 2개(`wt_fin`=b629789, `wt_comb`=core-final `f54ef1d`+`b629789` 무커밋 병합; 소스 충돌 0, docs 2건만 충돌). mock provider, 네트워크·실제 API 0, `.env` 미열람. 적대 입력은 모두 그들의 함수/HTTP 앱(ASGI, 인메모리)에만 넣었고 임의 코드는 실행하지 않았다. 스크래치 워크트리는 끝에서 제거한다. 커밋·브랜치 변경 없음.
- 시점 주의: 이 검토 시점에 **`sandbox_exec`·`calc`·`arith_consistency`·`evidence_lookup` 구현은 어느 브랜치에도 없다**(`git grep sandbox_exec` = 결정 문서뿐). b629789에는 Z3(constraint)·Pint(units)·NetworkX(dependency) 3개 도구뿐이고 Codex 인계 문서가 "임의 생성 Python·범용 실행은 범위 밖"이라고 못박았다. FIN-ENGINE의 a3b973b는 인터페이스만 있고 `restricted_exec`는 "기본 꺼짐" 자리표시다. 따라서 §3은 구현이 아닌 **요구 설계**다.

## 전체 판정

**수정 필요(Z3 동시 실행 프로세스 크래시 · 단위 지수 사슬 연산 폭탄 · 이벤트 루프 동기 preflight와 이차 ReDoS · `[확인 필요]` 자유 문장 통로 — 모두 작은 수정, 그중 Z3는 FIN-TOOLS가 이미 반영). `sandbox_exec`·`calc`는 구현이 없으며, 만든다면 §4 조건을 모두 만족해야 한다.**

## b629789 병합 판정

**판정: 조건부(데모 병합 가능, 공개 노출·실 LLM 전에 C-1~C-4 수정 필수).**

- 조건 C-1 (Z3 동시 실행 = 프로세스 크래시): 병합 직후 `final_tools.py`의 Z3 사용을 잠금으로 직렬화하거나(검증함: 1줄 `threading.Lock`, 4스레드 80회 무오류, 1.0초) 데모를 `NEUMANN_MAX_CONCURRENT=1`로 기동한다. **→ FIN-TOOLS가 `Z3_LOCK`+호출마다 `z3.Context()`로 수정 중(미커밋 작업트리)이며, 재검증: 8스레드×40회×16검사 무오류.**
- 조건 C-2 (이벤트 루프 정지·2차 ReDoS): `api/finalize.py`의 `confirmed_text` 길이를 `srv.config.max_plan_chars`로 제한하고 preflight를 이벤트 루프가 아니라 스레드(또는 게이트 안)에서 돌리며, `AUTHOR_SIGNATURE_RE`·`_ENTITY_RE`를 고친다(검증함, 아래 표).
- 조건 C-3 (단위 지수 사슬 = 연산 폭탄, F-13): `final_tools._fact`의 단위 문법이 `m^3^3^3^3`처럼 `^` 사슬을 허용하고 Pint는 이를 Python 정수로 오른쪽 결합 거듭제곱한다. 계획서 문구 "1 m^3^3^3^3"와 공개 요청 `checks` 하나로 스레드가 끝나지 않는 정수 거듭제곱에 들어가 GIL·메모리를 점유한다(안전상 실제 폭탄은 실행하지 않았고 축소판으로 확인). 문법을 `^` 1회로 제한.
- 조건 C-4 (`[확인 필요: …]` 자유 문장 통로, F-12): 자리표시 안의 문장은 숫자·PII·기관 패턴 외에 검사가 없어 URL·정책 주장·지시문이 그대로 최종 초안에 들어간다(`http://evil.example/login` 통과 실측). 프롬프트 주입된 계획서로 LLM이 링크를 심을 수 있다. 자리표시 내용을 코드 템플릿으로 만들거나 `://`·`www.`·`](`·`@` 거절 + 범위 내 어휘만 허용.
- 이 넷은 터널이 닫힌 단일 발표자 데모에서는 악용 경로가 로컬 사용자뿐이고, mock에서는 UI가 `checks`를 보내지 않으며 mock 교정은 교정 0건(기본) 또는 고정 대본 문구뿐이므로 Z3·Pint·자리표시 경로에 닿지 않는다. 그래서 "병합 불가"가 아니다. 그러나 (공개 노출) 또는 (실 LLM 켬) 중 하나라도 하기 전에는 반드시 고쳐야 한다.

### (a) 위험 요소 점검 결과

| 항목 | 결과 |
|---|---|
| `eval`/`exec`/`subprocess`/`os.system`/`pickle`/네트워크/파일 쓰기 | **없음.** `git diff main...b629789 -- src scripts pyproject.toml`의 추가 줄에서 해당 호출 0건(정규식 상수와 `importlib.import_module("z3"/"pint"/"networkx")` 상수 이름 3곳뿐). `final_tools.py`는 모델 생성 코드를 해석하지 않는다. |
| 샌드박스 | b629789에는 없음(범위 밖). 공개 라우트로 도달 가능한 코드 실행 경로 0. |
| Z3 입력·시간 | 입력은 원문 줄에서 정확히 1회 나타난 유한 수(|값|≤1e9)·32항 이내·`solver.set(timeout=200ms)`. 상수만 들어가므로 시간은 문제 없다(31개 1e8 곱 1ms). **그러나 Z3 전역 컨텍스트가 스레드 안전하지 않다: C-1.** |
| Pint | 단위 문법을 `[A-Za-zµ°]+(?:[*/][A-Za-zµ°]+\|\^[1-3])*`(≤48자)로 제한해 ReDoS·지수 폭탄 없음. 오프셋 단위(degC/degF)는 `unchecked`. 매 호출 `UnitRegistry()` 재생성으로 130~170ms(첫 호출 640ms)×최대 16건 = 2.7~10초 CPU(F-7). |
| NetworkX | 노드·간선 각 ≤32, `is_directed_acyclic_graph`만 호출 — 그래프 크기 문제 없음. |
| 공개 라우트 | `POST /premortem/revise/finalize`만 추가(`main.py:410-412`에서 `install`). `srv.protect(..., "analysis")`로 강제 분석 관문, 관문 없는 앱은 503(테스트가 확인). |
| 슬롯·예약 반환 | 실측 OK: 잘못된 JSON/빈 본문/리스트/NUL/깊은 중첩 5000단/`checks` 비dict/결정 500개/`submission_id` 500자 8종이 모두 422, `gate.active=waiting=0`, 예산 소모 0(유일한 예산 1은 정상 revise 호출). `plan_text`가 상한 초과면 413. 중복 제출은 `_drop_reservation`으로 환불, 속도 제한에는 계산됨(rate_per_min=4에서 12회 중 3회 통과·나머지 429, 엔진 호출 1회). 타임아웃 뒤에도 스레드가 끝날 때까지 슬롯 유지(기존 `_Gate` 설계). **단 슬롯 반환 자체는 OK이나 ReDoS/Z3는 슬롯을 영구 점유할 수 있다(C-1·C-2, F-2).** |
| revise / assemble | 동일 `_Gate` 사용, 기존 테스트 통과. **assemble도 같은 ReDoS 정규식에 노출**(클라이언트가 보낸 `revision.proposed_text` 길이는 `validate_revision`이 제한하지 않음: 6000줄바꿈 3건 → assemble 9.1초, 이차 증가). core-final(E3-L2r)의 기존 결함이며 finalize가 이를 이벤트 루프에서 동기로 돌려 악화시킨다. |
| 테스트 | 결합 트리 집중 103건: 102 passed, 1 failed(`test_http_timeout_is_explicit_and_replay_does_not_repeat`). 단독 재실행 2/2 passed, 부하 때 1회 실패(0.05s 타임아웃을 전제한 시간 민감 테스트 — 안전 문제 아님, TEST-1 범위). |

### (b) 정직성 라벨

| 항목 | 결과 |
|---|---|
| mock 표기 | OK: `generator="mock"`, 안내문 "mock 테스트 결과이며 실제 LLM의 과학적 검토가 아닙니다", mock은 고정 `mock-semantic` 미검사 쟁점을 넣고 상태는 `partial`. 규칙 합성을 LLM 생성으로 쓰지 않는다. |
| 인용문 | OK: 모델은 줄 번호만 돌려주고(스키마에 `quote` 없음) 인용은 `_bind_sources`가 원문 줄에서 붙인다. 모델 교정안은 줄 앵커·숫자·기관·PII·마크업·새 어휘 게이트, 거절안은 고정 문구로 대체. |
| 수치 판정 | OK: 교정 줄의 숫자는 같은 줄 원문에 있는 것만 허용(`_text_problem`)하므로 초안이 도구가 내지 않은 계산값을 단정할 수 없다. 도구가 없거나 모호하면 `unchecked`. |
| 도달하는 결함 | (1) UI `originText`가 최종화 응답 **최상위**의 `generator`를 읽는데 그 필드는 `finalization.generator`에 있다 → mock 결과에도 "생성 방식 별도 확인"으로 표시되고 astra 모델명은 어디에도 안 나온다(`index.html:1504`, F-9). (2) `confirmed_text`(연구자 문안)로 돌려도 `origin="server_signed"`+서명이 붙는다(안내문 1줄만)(F-8). (3) 쟁점 `message`는 LLM 자유 문장이라 "인용처럼 보이는" 문구를 검증하지 않는다(F-10). |
| 서명 | `server_signed`는 입력 result/revision 서명이 모두 확인될 때만. **B1(A3~A6 결합 미해결)을 그대로 상속** — core-final+B1 병합 전에는 출처 주장을 제품 문서에 쓰지 않는다. |

## 1. 지적 사항 표

심각도: 치명(크래시·서버 정지) / 높음 / 중간 / 낮음. "브랜치@sha"는 재현한 대상이다. 줄 번호는 `b629789` 기준.

| ID | 심각도 | 브랜치@sha · 파일:줄 | 재현 | 수정 |
|---|---|---|---|---|
| F-1 | 치명 | b629789 `src/neumann/analyze/final_tools.py:86-95` (`_constraint`의 `z3.Solver()`·`RealVal`) | Z3 기본 전역 컨텍스트는 스레드 안전하지 않다. `run_tool_checks`를 2스레드로 동시에 돌리면 `0xC0000374`(힙 손상)/`0xC0000005`(접근 위반)로 프로세스 종료(3회 중 3회). HTTP로는 `max_concurrent=4`에서 제약 `checks` 16개짜리 finalize 6건을 동시에 보내면 서버 프로세스가 죽는다(`Z3_solver_check_assumptions`, 3/3). `checks`는 공개 요청 필드라 누구나 가능하고, 실 LLM이 제약 `checks`를 내면 정상 사용자 2명 동시 실행으로도 발생. 기본 동시 상한은 로컬 2·공개 4. | (a) 모듈 전역 `threading.Lock`으로 `_constraint` 전체 직렬화(검증: 4스레드×20회 무오류). (b) 또는 호출마다 `z3.Context()`와 `Solver(ctx=)`·`RealVal(s, ctx)` 사용(검증됨, 7.8초/80회로 더 느림). (c) 가장 좋은 것: 상수 합·곱 비교이므로 `fractions.Fraction`으로 정확 계산하고 Z3를 쓰지 않는다. 회귀 테스트: 8스레드 동시 호출. |
| F-2 | 높음 | b629789 `src/neumann/api/finalize.py:24-25,121-129`; `src/neumann/analyze/revise.py:166`(`AUTHOR_SIGNATURE_RE`)·`:169`(`_ENTITY_RE`) | (i) `confirmed_text`는 `max_plan_chars`(기본 5만)를 받지 않고 모델 상한 20만자까지 통과한다(140,000자 → 200, 엔진이 140,000자 수신; `plan_text`는 413). (ii) `finalization()`이 preflight(`assemble_revised_plan(..., regate=True)`, `contains_identity(confirmed_text)`)를 **`await` 없이 이벤트 루프에서 동기 실행**한다. (iii) `AUTHOR_SIGNATURE_RE=(?im)^\s*…`는 줄바꿈 연속에서 이차 시간: `"x"+"\n"*n` = n 5천 1.6초, 1만 5.1초, 2만 21초(n=14만이면 약 17분). `_ENTITY_RE`의 `{2,}`도 한글 연속에서 이차(2만자 26.5초). finalize 요청 1건(`revision.proposed_text`에 줄바꿈 3000개)이 **이벤트 루프를 1.2초 정지**시켰고 크기 비례로 이차 증가 → 요청 1건으로 서버 전체(헬스체크 포함)를 분 단위 정지 가능. assemble 경로에서는 스레드가 정규식에서 못 빠져나와 타임아웃(504) 뒤에도 슬롯을 계속 점유한다. | `AUTHOR_SIGNATURE_RE`를 `(?im)^[ \t]*(?:…)\b`로, `_ENTITY_RE`의 첫 분기를 `{2,40}`으로 제한(검증: 20만자에서 7ms/104ms, 일치 동작 유지). `confirmed_text`·`revision` 문자열 필드에 `srv.config.max_plan_chars`·`max_plan_lines`·`max_token_chars`를 적용하고 `validate_revision`에 `proposed_text ≤ MAX_PROPOSED_CHARS(600)` 추가. preflight는 `await asyncio.to_thread(...)`로 옮긴다(`gate.run` 안이 더 좋다). |
| F-3 | 높음 | b629789 `api/finalize.py:24,93-179` (`checks` 요청 필드) | 공개 요청이 `checks`(최대 16)를 직접 받아 도구를 임의 매개변수로 구동한다(통합 테스트가 이 경로를 씀). LLM 선택이 아니라 **호출자가 도구를 고른다** → 결정 문서의 "도구 선택은 코드가 정한다"와 어긋나고 F-1의 트리거가 된다. 호출자가 고른(선택적으로 통과하는) 검사 결과가 `server_signed` 서명 본문에 들어간다. | 공개 요청에서 `checks`를 없앤다(테스트 전용 내부 인자로). 도구 호출은 (점검 유형 → 도구)를 코드가 정하고 인자는 코드가 원문에서 뽑는다(a3b973b의 `TOOL_FOR_CHECK` 방향이 맞다). |
| F-4 | 중간 | b629789 `src/neumann/analyze/final_tools.py:154-189` (`run_tool_checks`) | 근거 줄 전체에 대한 `_QUALIFIED_NUMERIC.search`를 (검사 16) × (소스 32)번 반복한다. 20만자 한 줄 계획서에서 16검사 4.3초, 최악 문자열 18.5초(`re`는 GIL을 쥔 채 안 풀린다). 기본 상한(5만자)에서도 ~4.6초. 취소는 검사 사이에서만 확인되어 상한이 지나도 검사 1건(~1초) 더 돈다. | 줄 인덱스별로 한 번만 검사하는 캐시(dict)를 둔다(512회 → 최대 16회). 줄 길이가 크면(예: 4,000자 초과) `unchecked: line_too_long`. |
| F-5 | 중간 | b629789 `api/finalize.py:38-60,145-167` | 선두(leader) 취소(연결 끊김)는 `cache.finish(…503 "cancelled")`로 그 `submission_id`를 10분간 503으로 **고정**한다(같은 ID 재시도가 모두 503). 타임아웃·500도 10분 저장. 보안이 아니라 가용성·UX. 또 중복 대기자는 슬롯 없이 `limit`초까지 폴링(20ms) — 속도 제한은 받으나 동시 대기 수 상한은 없다. | 취소·500은 캐시에서 제거해 재시도를 허용하거나 짧은 TTL, 대기자 수 상한(예: 32). |
| F-6 | 중간 | b629789 `src/neumann/llm.py:330`(`max_attempts=2`), `analyze/finalize.py:170-175` | 비용: finalize 1회 = 논리 호출 최대 2(의미 검사 + 교정). 검사에서 쟁점이 0이어도 교정을 호출한다. OpenAI provider는 호출당 재시도 1회(`max_attempts=2`) → **실제 요청 최대 4**(각 60초 상한). 입력은 계획서 전체(×2, 교정 호출엔 쟁점·도구 결과 추가)이고 `confirmed_text`는 F-2로 5만자 상한을 우회 → 토큰 4배. `counters`는 논리 호출만 세고 시도·토큰은 응답에 없다. | 쟁점 0·도구 전부 pass이면 교정 호출 생략. `confirmed_text`에 같은 상한. `counters`에 `attempts`·`tokens` 추가(계약은 추가만). |
| F-7 | 낮음 | b629789 `final_tools.py:112` | 호출마다 `pint.UnitRegistry()` 생성(130~170ms, 첫 호출 640ms). | 모듈 수준 지연 싱글턴 1개(읽기 전용 사용) 또는 요청당 1개. |
| F-8 | 중간 | b629789 `api/finalize.py:80-88` | `confirmed_text`(연구자가 고친 임의 문안)도 `origin="server_signed"`+`finalization_sig`를 받는다. `confirmed_base_id`는 조립본의 id일 뿐 `confirmed_text`와 묶이지 않는다. 안내문 1줄("새 내용의 출처는 확인되지 않음")뿐이다. | 서명 본문에 `text_source: "assembled"\|"researcher_confirmed"`를 추가(계약 추가)하고 UI가 서명 문구를 "서버 처리 확인, 문안은 연구자 작성"으로 구분 표시. |
| F-9 | 중간 | b629789 `src/neumann/webui/index.html:1504` | `originText(raw)`가 `raw.generator`를 읽지만 최종화 응답 최상위에는 그 키가 없다(`finalization.generator`에 있음). mock도 astra도 "생성 방식 별도 확인". 모델명 미표시, MD 내려받기에 `notices`·생성자·모델 없음. AGENTS.md "폴백·mock은 화면에 표시" 위반 소지. | `originText`가 `raw.finalization.generator/model`을 읽고, 패널 머리와 MD 머리에 `생성: mock/astra(모델)`·`notices`를 넣는다. |
| F-10 | 낮음 | b629789 `analyze/finalize.py:195-201` | 쟁점 `message`는 LLM 자유 문장. PII·마크업·새 숫자만 검사하고, 따옴표로 원문을 "인용"한 것처럼 쓴 문구가 원문에 실제로 있는지는 보지 않는다("LLM은 인용문을 직접 쓰지 않는다"). 수치 판정 문장도 도구 결과와 묶이지 않음(상태가 `unchecked`라서 표시상 안전). | 메시지 안의 따옴표/「」 구간은 제거하거나 원문 부분 문자열인지 검증. 도구 없는 쟁점에 수치 비교 표현이 있으면 버림. |
| F-11 | 낮음 | b629789 `analyze/finalize.py:178` | 호출 실패(`response.ok=False`)여도 `generator/model`을 응답의 것(astra 등)으로 덮어쓴다. 상태는 `incomplete`라 거짓은 아니나 "astra가 생성"처럼 읽힐 수 있다. | 실패 시 `generator="rule"`·`model="none"` 유지, 시도 정보는 별도 필드. |
| F-12 | 높음 | b629789 `analyze/finalize.py:123-133`(`_text_problem`)·`analyze/assemble.py`(`_content_words`); 7011d78도 동일 | 교정안의 `[확인 필요: …]`(≤120자) 안은 숫자(도구 계산값 제외)·PII·기관/결과 패턴만 검사하고 낱말 게이트(`_content_words`)는 자리표시를 제외한다. 실측: `… [확인 필요: 세부는 http://evil.example/login 에서 확인]` → 문제 없음, `… [확인 필요: 이 예산은 정부 지침상 초과할 수 없다]` → 문제 없음. 프롬프트 주입된 계획서가 LLM을 시켜 최종 초안(내려받기·인쇄)에 링크·임의 주장을 "확인 필요" 표지로 심을 수 있다. | 자리표시 본문을 코드 템플릿(`[확인 필요: {issue kind} — {도구 사유 코드}]`)으로 만들거나, `://`·`www.`·`](`·`@`·`javascript:`·`data:` 거절 + 자리표시 안 낱말도 범위(`scope`) 어휘로 제한. |
| F-13 | 치명 | b629789 `final_tools.py:69-70,113-114`(`_fact`의 단위 정규식 `[A-Za-zµ°]+(?:[*/][A-Za-zµ°]+\|\^[1-3])*`) → Pint(`registry.Unit(...)`) | 문법이 `^[1-3]`을 여러 번 허용하므로 `m^3^3^3^3`(≤48자)이 통과한다. Pint는 `^`를 `**`로 바꿔 오른쪽 결합·Python 정수로 계산한다(확인: `2^3^2`=512, `10^3^3^2`는 19,683자리 정수를 계산). 3단 사슬 `m^3^3^3`은 지수 7.6e12를 "통과(passed)"로 돌려준다(338ms). 4단은 `3**(3**27)`이라 끝나지 않고 메모리를 소모한다(**안전상 4단 이상은 실행하지 않음**). 계획서에 "1 m^3^3^3^3"이 있고 공개 요청 `checks`(또는 모델이 제안한 검사)가 그 단위를 가리키면 스레드 1개가 GIL을 쥐고 영구 점유 → 서버 정지·메모리 고갈, 타임아웃(504)도 못 끊는다. | 단위 문법을 인수당 `^[1-3]` 최대 1회로 제한(`[A-Za-zµ°]+(?:\^[1-3])?`의 곱·나눔 조합만), 또는 호출 전에 `^` 개수 ≤ 단위 토큰 수로 검사. 숫자 앞 인자(`10^…`)는 금지. 같은 원칙을 FIN-TOOLS `dimension.normalize_unit`에도 적용(아래 F-17). |

## 2. FIN-ENGINE (`7011d78` 및 `a3b973b`) 검토

라우트 `POST /premortem/finalize`는 아직 없다(해당 브랜치의 `docs/API.md`만 수정 중). 현재 들어온 것은 도구 인터페이스(`neumann.finalize.tools`), 교정 게이트 확대, 시연용 scripted mock이다. UI(`FIN-UI` 목업)는 여전히 `premortem/revise/finalize`를 호출한다 → 결정 문서의 경로명과 불일치(통합 때 한쪽으로 통일).

| ID | 심각도 | 위치 | 내용 | 수정 |
|---|---|---|---|---|
| E-1 | 중간 | `7011d78` `analyze/finalize.py:150-182`(`_computed_numbers`) | "수치·합계 판정은 도구 결과로만" 위반 소지. 교정 자리표시에 들어갈 수 있는 "도구 계산 수치"를 **엔진이 `sum(terms)`·`math.prod(terms)`로 직접 계산**(값은 LLM이 준 `terms`, Z3는 sat/unsat만 반환하고 `details`에 합계가 없다). 시연 mock도 합계(4200)를 스스로 계산해 자리표시에 넣는다. 산술은 맞지만 출처가 도구가 아니다. | 도구(`arithmetic_sum`은 이미 `computed_exact`를 돌려준다)가 `details.computed`로 돌려준 값만 허용하고 엔진 내 산술 제거. 실패·미검사 행은 기여 0(현재 그렇게 돼 있음). |
| E-2 | 중간 | `7011d78` `llm.py:618`, `analyze/finalize_demo.py` | 시연 대본 mock이 **기본 mock provider**(`make_llm`의 mock 경로)에 들어갔다. `NEUMANN_LIVE_LLM_OK` 없이 provider=openai를 요청하면 mock으로 강등되므로(`llm.py:606`) 운영 모양의 서버에서도 계획서가 정규식 4개(예산 합계 문형·`mS`/`S/cm`·정제↔학습 순환·반비례/증가)에 맞으면 "오류를 찾은 것처럼" 결정적 issue·교정이 나온다. 라벨은 `generator=mock`이지만 F-9 때문에 UI 머리에는 나타나지 않는다. | 시연 대본 경로가 작동하면 `notices`에 "시연 대본(scripted mock): 실제 검토 아님"을 넣고 `generator`를 `mock`으로 유지, UI 머리에 `생성: 모의(mock)`를 표시(F-9). 시연 대본은 `NEUMANN_DEMO_SCRIPT=1`에서만 켠다. |
| E-3 | 중간 | `7011d78` `analyze/finalize.py:184-`(`_edit_scope`) | 교정 허용 범위를 "쟁점 줄 + 도구 근거 줄·발췌"로 넓혔다. 낱말은 그 범위 안 어휘만이라 새 사실은 못 넣지만, 한 줄의 어휘를 다른 줄로 옮겨 주장을 이동·합성할 수 있다(예: 목표 줄의 "이미 …"이 아닌 문형으로 방법 줄에 결론을 끼움). 또 F-12의 자리표시 자유 통로가 그대로다. | 범위 안 어휘 허용은 유지하되 줄마다 `issue.plan_lines`에 들어 있는 줄로 제한하고, 자리표시는 코드 템플릿화(F-12). |
| E-4 | 중간 | `a3b973b`/`7011d78` `finalize/tools/__init__.py` `ToolRegistry.run` (`spec.timeout_s`) | `ToolSpec.timeout_s`가 **어디에서도 강제되지 않는다**(`spec.run(...)`을 호출 스레드에서 그대로 실행, `except TimeoutError`는 도구 스스로 던질 때만). FIN-TOOLS는 스펙마다 2·5·10초를 적었지만 죽은 설정이다. 도구가 멈추면(F-13) 슬롯이 영구 점유된다. | 파이썬은 스레드를 못 죽이므로 (a) 모든 도구를 입력·계산량이 유계임을 테스트로 보증하고 (b) 무계 가능성이 있는 도구는 별도 프로세스(타임아웃 시 종료)로 실행. 최소한 죽은 `timeout_s`는 문서에 "미강제"로 표기. |
| E-5 | 낮음 | `ensure_adapters`·`register` | 확인 후 등록(`reg.get(name) is None` → `reg.register`) 사이에 경합: 두 스레드가 동시에 첫 호출하면 두 번째 `register`가 `ValueError("tool already registered")`를 던지고 `run_tool` 밖으로 전파되어 500·10분 캐시(F-5)가 된다. | 잠금 안에서 확인+등록, 또는 `replace=True`. |
| E-6 | 낮음 | `_schema_problem` | `jsonschema`가 없으면 검증을 건너뛴다(fail-open). 현재 `jsonschema`는 핵심 의존성이라 실제 위험은 낮으나 조용히 검증이 꺼진다. | 없으면 `invalid_args`(fail-closed). |
| E-7 | 낮음 | `_jsonable` | `int`는 그대로 통과 → 4300자리 초과 정수가 evidence/output에 들어가면 JSON 직렬화(`ValueError: Exceeds the limit (4300 digits)`)에서 500이 된다(확인). 계산기(`calc`)를 추가할 때 지수 상한이 없으면 재현된다. | 정수 자리수 ≤ 100(초과는 `str` 요약), 계산기 지수·자리수 상한(아래 §3). |
| E-8 | 정보 | `7011d78` `TOOL_FOR_CHECK` | 엔진이 `exec`·`calculator` 유형을 **삭제**하고 `constraint→z3`, `units→pint`, `dependency→networkx` 3개만 남겼다(보안상 좋은 방향). 반면 FIN-TOOLS는 `arithmetic_sum`·`unit_dimension`·`structure`·`citation_lookup`으로 등록하려 하고 `register`는 `TOOL_NAMES` 밖 이름에 `ValueError`를 던진다 → **두 브랜치를 합치면 FIN-TOOLS 등록이 전부 실패**(통합 차단, 보안 아님). | PM이 이름 체계를 하나로 정한다(도구 이름 ↔ 점검 유형 표를 한 곳에). |
| E-9 | 정보(설계 확인) | 도구 선택 | 도구 선택은 `kind→tool` 표가 코드에 고정돼 있어 LLM이 고르지 않는다(OK). 다만 `kind` 자체와 인자(`terms`·`unit`)는 LLM이 제안하고 코드가 원문 일치로 접지한다. FIN-TOOLS `extract_checks`(규칙 추출)를 주 경로로 쓰면 "유형·인자 모두 코드"가 된다. 각 도구 행에 `origin: rule\|llm`을 남기면 감사가 쉽다. | 추출기 우선 + LLM 제안은 보충, 행마다 출처 표기. |

## 3. FIN-TOOLS (작업트리, 미커밋) 검토

대상: `.claude/worktrees/s3-FIN-TOOLS`의 `final_tools.py` 수정분과 `neumann/finalize/tools/{sums,dimension,structure,citation,extract,quantities,fin_tools}.py`(읽기 전용 열람, 스크래치에 복사해 실행).

| ID | 심각도 | 내용 | 수정/상태 |
|---|---|---|---|
| T-0 | 해결됨 | 내가 보낸 C-1을 반영해 `Z3_LOCK`+호출마다 `z3.Context()`를 넣었다. `sums.py`도 같은 잠금을 쓴다. **재검증: `run_tool_checks` 8스레드×40회×16검사 무오류(0 non-passed), `sums.run` 8스레드×20회 무오류.** | 커밋 전 회귀 테스트(`test_final_tools_threads.py`)가 있는지 확인 필요(작업트리에 있음). |
| F-17 | 낮음(방어 심층) | `dimension.normalize_unit`의 `_EXP_RE`는 `^N`마다 ≤4만 보므로 `10^4^4^4`·`m^4^4^4^4`(각 지수 4)가 통과하고 `_quantity`가 숫자 포함 식을 `ureg.parse_expression`으로 평가한다 → F-13과 같은 정수 거듭제곱 폭탄. 현재는 단위 문자열이 추출기의 고정 표(`_KO_UNITS`·`_ASCII_UNITS`·`_WORD_UNITS`)에서만 오므로 계획서 본문이 직접 닿지 않지만, `ARGS_SCHEMA`의 `left/right`가 자유 객체라 API/LLM이 인자를 넘기게 되면 열린다. | `^`·`**`는 단위 전체에서 총 1회, 지수 ≤3, 숫자로 시작하는 단위 인자 거절. |
| F-18 | 낮음 | `citation._bounded`는 시간 초과 때 데몬 스레드를 남긴다(백엔드가 멈추면 누적). 읽기 전용·오프라인(환경변수·`.env` 미접근, 질의 ≤300자)이라 악용은 작다. | 동시 조회 수 상한(세마포어 4). |
| F-19 | 정보(긍정) | `citation.py` = evidence_lookup: 네트워크·파일 쓰기 없음, `review_records`는 "원문 앞부분 글자 그대로"(코드 절단), 백엔드 미설정이면 `unchecked`. `sums.py`는 `Fraction` 정확 산술+Z3 교차 확인, 불일치 시 `unchecked`, 자리 수 1e30·항목 64 상한. `extract.py` 적대 입력(4.8만자 공백·숫자 런·`1/` 4만번·`#` 4만번·표 5천행·예산 2500줄·월범위 3000줄·DOI·따옴표)에서 최대 154ms — 정규식 폭주 없음(`MAX_LINE_CHARS=2000`). `tolerance`는 코드가 원문 자릿수에서 유도(`stated_tolerance`) — LLM이 임의로 키워 통과시킬 수 없는 구조(단 API가 `args`를 그대로 받지 않는다는 전제). | 유지. `sums`/`dimension`의 `tolerance` 인자는 외부 입력으로 열지 말 것(요구사항). |
| F-20 | 낮음 | FIN-TOOLS `extract`가 만든 `args`는 코드가 원문에서 뽑은 값이라 계획서 문구에 접지돼 있다. 다만 `calculator`/`restricted_exec`는 FIN-TOOLS가 **만들지 않는다**고 명시(조정 사항). 따라서 결정 문서의 `calc`·`sandbox_exec`는 현재 어느 브랜치에도 구현이 없다. | 아래 §4 요구사항을 만족할 때만 추가. |

## 4. `calc` / `sandbox_exec` 요구 설계 (구현 전 — 안전 조건)

현재 구현이 없으므로 "만든다면 이 조건을 모두 만족해야 한다"는 목록이다. **07:00 이전에는 만들지 않는 것이 안전하다**(Codex 인계·FIN-TOOLS·엔진 `7011d78`이 모두 제외하는 방향이고 PM 지시와도 같다).

1. `sandbox_exec`는 임의 Python이 아니다. 닫힌 **템플릿 프로그램 목록**(예: `sum_check`, `unit_convert`)에 코드가 원문에서 뽑은 수치를 채워 넣는 것만 실행한다. 계획서·LLM 문장이 코드가 되는 경로 0(`restricted_exec`의 `args.code` 문자열 금지, `template_id`+수치 인자만).
2. 요청 본문 필드로는 켤 수 없다(서버 설정 플래그, 기본 꺼짐, 공개 API 경로에서 도달 불가). `CHECK_KINDS`·LLM 스키마 enum에 `exec` 미포함(엔진 `7011d78`이 이미 삭제 — 유지 요구).
3. 별도 프로세스: `subprocess`(`-I -S`, 환경변수 비상속, 임시 폴더 cwd), Windows Job Object로 메모리·CPU 시간·프로세스 수 제한, 타임아웃 시 프로세스 트리 종료. 네트워크 차단(방화벽 규칙/AppContainer — `socket` 몽키패치는 불충분), 임시 폴더 밖 쓰기 금지, 출력 크기 상한, 입력은 표준입력 JSON.
4. 동일 원칙을 `calc`에도 적용: `eval`/`exec`/`sympify` 금지, `ast` 허용 노드 화이트리스트(숫자·`+ - * / **`·괄호만, 이름·속성·호출 없음), `Fraction` 정확 산술, 식 길이 ≤200·깊이 ≤20, **지수 ≤ 64·결과 자리수 ≤ 200**(`9**9**9`·`10**10**6` 거절), 출력 자리수 제한(E-7).
5. 모든 수치 판정은 도구 출력(`details.computed`)에서만 가져오고 엔진이 산술하지 않는다(E-1).
6. 실행 이력(코드 해시·템플릿 id·입력 요약·종료 사유)을 `evidence`에 남기고 예외 원문은 남기지 않는다.

## 5. 공개 라우트·관문 요약 (수정 대상 경로 확인)

- 새 경로(`POST /premortem/finalize`)를 만들 때는 `revise._Gate`를 그대로 쓰고 `srv.protect(path,"analysis")`를 강제한다(E3-L2r F1 교훈). `_Gate.refusal_response()`의 경로 동일성 검사가 이름을 바꾸면 깨지므로 테스트(관문 없는 앱 503, 422·413·본문 오류 뒤 `gate.active=waiting=budget.used=0`)를 새 경로에 복제한다. 나의 적대 입력 8종과 동시성·ReDoS 재현은 세션 스크래치 `scratchpad/probe/test_http_probe.py`·`p1~p8.py`에 있고 새 경로에 그대로 재사용할 수 있다(요청하면 `tests/`로 옮긴다).
- 요청 본문 상한: `plan_text`·`confirmed_text`·`revision` 문자열 전부에 `max_plan_chars`·`max_plan_lines`·`max_token_chars` 적용(F-2).
- 클라이언트 제공 결과 불신: 서명이 없으면 `client_submitted_unverified`(현재 구현 OK). `checks`는 공개 입력에서 제거(F-3). `confirmed_text`는 별도 출처 라벨(F-8).
- 비용: 논리 호출 ≤2, 실제 요청 ≤4(재시도 포함)를 문서·`counters`에 표기하고 쟁점 0이면 교정 생략(F-6).

## 6. 검증 방법과 한계

- 실행한 것: 위 표의 재현은 모두 스크래치 워크트리(`b629789`, 결합 `f54ef1d+b629789`, FIN-TOOLS `b93561a`+작업트리 복사, FIN-ENGINE `7011d78`)에서 mock·로컬로만 돌렸다. 실제 API·네트워크·`.env` 0. Z3/Pint/정규식 적대 입력은 그들의 함수에 직접 넣었고 연산 폭탄(F-13·F-17)은 안전상 실행하지 않고 축소판으로만 확인했다.
- 못 한 것: `/premortem/finalize`(미구현)·`sandbox_exec`·`calc`(미구현)의 실제 코드 검토, FIN-UI의 실제 서버 모드 브라우저 검사, FIN-TOOLS 전체 pytest(작업 중). 결합 트리의 전체 `scripts/verify.py`는 돌리지 않았다(집중 103건만).
- 작업트리 상태는 계속 바뀐다(FIN-TOOLS는 검토 중에 내 C-1을 반영). 위 줄 번호는 `b629789` 기준이고 F-13·F-17은 재검증 시 다시 확인한다.
