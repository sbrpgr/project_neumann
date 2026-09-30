# E5-L1e2e 검증 보고서

- 검증자: Claude Sonnet 5.5 (읽기 전용) · 대상: `task/E5-L1e2e` 커밋 82e5e67~**641dcbe**(worktree `.claude/worktrees/s2-E5-L1e2e`) · 2026-09-30
- 규칙 준수: 라이브 재실행 없음, 모든 명령 `NEUMANN_LLM_PROVIDER=mock`·`OPENAI_API_KEY` 해제·`NEUMANN_LIVE_TESTS`/`NEUMANN_LIVE_LLM_OK` 미설정, `.env` 미열람, 8020·8099 접속 없음(서버는 띄우지 않았고 브라우저 시험은 route 가로채기), stash·commit·merge·push 없음. 조작 시험 스크립트와 `git archive` 사본은 scratchpad에만 남겼다.
- 판정 대상 결과: 커밋된 8020 실행(21:13~21:24, gpt-6.1-sol, 3 passed · 2 failed). 검증 중 PM 쪽 재실행(`test_live.py --plans ai4s`, PID 27320)이 worktree의 `docs/reports/E5-L1e2e_live_*.png`를 덮어쓰기 시작했다(미커밋 변경). 덮어쓰기 전 커밋본으로 대조했고, 이 보고서의 판정은 커밋 641dcbe 기준이다.

## 판정: PASS-조건부

판정기와 커밋된 결과의 숫자는 맞고, 2 FAIL 판정은 정당하다. 병합 전 고칠 것은 하나다: main의 새 루트 conftest(cdaca5a)와 합치면 이 브랜치의 단위 검사 1건이 실패한다.

## 완료 기준·확인 항목

| # | 확인 | 실행 / 실제 출력 | 결과 |
|---|---|---|---|
| 1a | 요약 JSON ↔ 보고서 표 | 요약 JSON을 다시 계산: 카드 5/7/7(API 5/7/8), 근거 연결 19/19·28/28·27/27, 카드 통과 5/5·7/7·8/8, 폐기율 4/636=0.006·9/623=0.014·9/753=0.012, 심사평 8문장, 화면 시간 85.0/140.8/154.7/4.3s(합 384.8), API 83.1/95.9/97.1s(합 276.1), 세션 671.092s, v1 단계 58.2/63.8/61.1s, 단계별 시간표 24칸 | 전부 일치 |
| 1b | 스크린샷 ↔ 요약 | 18장 중 11장(체크리스트 3·심사평 3·카드 3·범위 밖 리포트·계획서별 표본) 직접 확인. 나머지 7장(input 4·report 3)은 요약 JSON과 대조만. 카드 수 5/7/7, 심사평 근거 번호를 손으로 셈(plan 23=11+12, protein 21=10+11, neural 19=10+9), 문장 8, 게이트 표시 8/8/0/8, 체크리스트 행 12/19/18 + 푸터 "보류 12/19/18", 범위 밖 화면에 사유·모델 gpt-6.1-sol 표시 | 일치 |
| 1c | 2 FAIL 정당성 | protein C3(`10행 23행 카드 01 astra 합성`)·neural C6(`17행 18행 22행 카드 03`)에 근거 번호 버튼이 없음을 스크린샷으로 확인. 나머지 항목은 모두 번호가 있다(18/19, 17/18) | 정당. 제품 프롬프트는 `evidence_ids 0~3개`라 0개도 허용해서, 판정기 기준(항목마다 근거)이 제품 스키마보다 엄격하다. PM이 E3-L1e(근거 게이트)로 이미 큐에 넣은 사안과 같다 |
| 2 | 판정기 조작 시험 | 아래 "조작 시험"(잡은 것·놓친 것 목록) | 핵심 조작은 모두 잡음, 놓친 3건은 기록만/설계상 |
| 3 | 모델 기록 | manifest·카드 모델·심사평 모델·체크리스트 모델·화면 KPI·`/health.llm`이 모두 `gpt-6.1-sol`(요약 JSON `models`). 카드 `generator=astra`는 계약 이름이고 화면에는 "astra 합성 + gpt-6.1-sol"로 나온다. 캐시 키(`queries.cache_key`·`extract.cache_key`)에 모델이 들어 있어 캐시 재사용분도 sol로 표기된다. 모델명을 바꿔 시험: manifest·카드·심사평(대문자)·체크리스트 항목·KPI·`/health` 모델이 astra면 모두 "astra 모델이 쓰였다(금지)" 실패 | astra 검사는 동작. 단 아래 발견 3 |
| 4 | 결과 JSON 저장 코드 | `_save_result` 시험(scratchpad tmp): 이메일 2·ORCID 2를 `[EMAIL]`·`[ORCID]`로 가리고 바꾼 경로 3개를 기록. `reviewer_email`·`reviewer_name` 키와 `rvw_<16hex>` 아닌 가명은 실패로 보고. 계획서 이름 `../../evil/../pwn.md`·`..\..\pwn2.md`·`C:/Windows/pwn4.md`·`..`은 모두 `Path.stem`으로 `<out>/E5-L1e2e_live/` 안 파일명이 되어 밖으로 못 나간다(접두어·mode는 상수·고정 매핑, 계획서 경로는 `PLAN_SETS` 상수) | 이메일·ORCID·경로는 통과. 아래 발견 4 |
| 5 | conftest 함정 | 아래 "conftest 의견" | 조건부(병합 전 수정 1건) |
| 6a | 기본 e2e 시험 | `pytest tests/e2e -q` → 641dcbe: `34 passed, 8 skipped`(949d628: 33 passed). `NEUMANN_UI_TESTS=1 pytest tests/e2e/test_probe_ui.py` → `2 passed`(실제 index.html, 서버·LLM 없음) | 통과 |
| 6b | verify | `python scripts/verify.py` 641dcbe: `1183 passed, 29 skipped in 183.52s` · 보안 413개 · 계약 2개 · `verify 통과`. 이전 실행(커밋 도중 작업 트리)도 `1182 passed, 29 skipped`, 통과 | 통과 |
| 7 | generator 기록 | 아래 "generator 키 대조" | 2423834로 해결(커밋된 요약 JSON은 예외, 발견 1) |
| — | 계약·소유 경로 | `git diff main...task/E5-L1e2e --name-only`: `tests/e2e/{conftest,e2e_checks,test_live,test_probe_ui,test_v1_checks}.py`와 `docs/reports/E5-L1e2e*`뿐. `contracts/`·`src/neumann/models.py`·다른 에픽·비밀값 없음(diff에서 키 값 검색 0건) | 통과 |
| — | 커밋 규칙 | 10개 커밋, 전부 `verify 통과`·`builder:` 줄 있음. 데이터·스크린샷 커밋(`e28e787`) 제외 최대 543줄(`fdd1674`, 테스트 2파일)로 "수백 줄 이내" 경계 | 통과 |

## 조작 시험(scratchpad, mock 결과)

기준 입력은 `tests/fixtures/premortem_result.json` + 빌더의 `v1_result`·`build_ui_view`. 실제 `index.html`에 가짜 view를 먹이는 시험도 했다(DOM 탐침 포함).

잡은 것: 근거 번호가 있지만 근거 목록에 없는 id(심사평 #99, 체크리스트 #77: 화면·응답이 같아도 실패, 실제 index.html에서도) · 결과 JSON의 없는 excerpt id(심사평·체크리스트) · 화면 심사평에서 근거 번호가 빠지거나 문장끼리 뒤바뀜 · 빈 문장 · 강등 단계가 상단 안내에서 빠짐 · 규칙 체크리스트 항목이 astra로 표시됨 · astra 모델명(위 3번, 6곳).

놓친 것(기록만 하거나 설계 밖):

- 체크리스트 근거가 근거 목록에는 있으나 **그 카드의 근거가 아님**: `evidence_within_card`로 기록만 하고 실패로 안 친다(결과 JSON 쪽도 같다). 커밋된 실행은 근거가 있는 항목 전부 카드 안(12/12, 18/18, 17/17).
- 서버가 `gen`을 astra로 거짓 표시하는 응답(화면과 응답이 같은 거짓)은 화면-응답 비교로는 못 잡는다. 이 판정기의 범위 밖이다.
- 규칙 항목(`gen=rule`)이 있는데 `stages_not_ok`가 비어 있는 경우: 행에 "규칙 합성" 라벨이 뜨므로 정직성은 지켜지지만 단계 강등 알림은 요구하지 않는다.

## generator 키 대조(항목 7)

- E5-L3b 변환기(`scripts/metrics_from_e2e.py`)는 `plans[*].linkage.card_generators`를 읽고, 키는 `astra`·`rule`이어야 한다(`{astra, rule}`이 아니면 `mixed`).
- **949d628의 코드**는 `plans[*].card_generators`(`astra:gpt-6.1-sol` 형식, 계획서 항목 바로 아래)와 `plans[*].models.card_generators`에만 썼다. 위치도 형식도 변환기와 안 맞았다(형식 그대로 옮기면 `mixed`). 실제로 변환기에 커밋된 요약을 넣으면 P2·P6이 "generator 미기록 참고"로 나온다.
- **2423834·641dcbe**: `linkage.card_generators = dict(rep.card_generators)`(예 `{"astra": 5}`)를 추가하고, 화면 쪽 `view_card_generators`·`dom_card_labels`, `write_summary` 분리, 계획서 흐름 시험(`test_summary_json_has_card_generators_per_plan`)을 넣었다. 확인: (a) 키를 빼면 `test_linkage_info_has_drop_rate`·이 시험이 실패(변이 검사), (b) 실제 `test_demo_plan` 흐름으로 만든 요약 JSON을 변환기에 넣으면 시스템 `neumann`, `linkage_rate` 1.0, `demo_e2e` all 3 → P2·P6이 채워짐(재현: scratchpad `summary_flow.py`), (c) `astra`·`rule`·`mock` 조합이 `{astra:1, rule:1}`·`{mock:1, astra:1}`로 원본 그대로 세어진다.
- **커밋된 요약 JSON(`E5-L1e2e_live_summary.json`)은 이 키들이 없다**(라이브가 코드보다 먼저 돌았음). 그 파일만으로는 P2·P6이 참고 행이다. 새 요약을 채우려면 PM이 승인한 재실행이 필요하고, 지금 PM 쪽 재실행이 돌고 있으니 그 결과가 커밋될 때 확인하면 된다. 커밋된 요약의 화면 실행 `generators`(`{"astra": 5|7|7}`)는 화면 실행 것이지 연결 검사(`/premortem`) 실행 것이 아니라 변환기가 쓰지 않는다.

## conftest 의견(항목 5)

- 브랜치 자체(기존 루트 conftest)에서 `NEUMANN_LIVE_TESTS=1`만 주고 `pytest tests/e2e/test_live.py`를 돌리면 `5 skipped`, 종료 코드 0(함정 재현). 스크립트(`python tests/e2e/test_live.py …`)는 새 가드로 pytest 시작 전에 이유를 알리고 종료 코드 1로 실패한다(확인).
- PM의 main 수정(cdaca5a): 같은 조건에서 `UsageError`, 종료 코드 4(사본에서 확인). 이 방향이 맞다. `ImportError while loading conftest` 안에 감싸여 나오지만 사유 문장이 보이고 종료 코드가 0이 아니라서 함정은 없어진다. 루트 conftest는 더 고칠 필요가 없다.
- **문제**: 이 브랜치를 cdaca5a와 합치면 `tests/e2e/test_v1_checks.py::test_script_plans_argument_collects_ai4s`가 실패한다(사본에서 `git archive task/E5-L1e2e` + main의 `tests/conftest.py`로 재현: `1 failed, 35 passed`, 종료 코드 4). 스크립트가 `--collect-only`에서도 `NEUMANN_LIVE_TESTS=1`을 환경에 넣고 pytest를 부르므로 새 conftest가 `UsageError`로 막는다. 수집만은 플래그가 필요 없다.
- 스크립트 가드는 남겨도 된다(pytest 시작 전에 멈춤). 대신 가드 메시지·`test_live.py` 머리말·`tests/e2e/conftest.py` 머리말·보고서 결정 2의 "conftest가 NEUMANN_LIVE_TESTS를 0으로 되돌려 skip"은 병합 뒤 낡은 설명이 된다.

## 발견

1. **(필수) main 병합 시 단위 검사 1건 실패** — 위 "conftest 의견". 조치: `test_live.py` `__main__`에서 `--collect-only`이면 `NEUMANN_LIVE_TESTS`를 환경에 넣지 않는다(예: `if not collect_only: os.environ["NEUMANN_LIVE_TESTS"] = "1"`). 낡은 설명 문구 정리.
2. **커밋된 요약 JSON에 `linkage.card_generators`가 없다** — 코드는 고쳐졌고 시험됐다. 재실행 결과를 커밋할 때 요약에 키가 들어 있는지 확인하면 된다. 보고서의 "요약 JSON에 `card_generators`(예: `astra:gpt-6.1-sol`)가 남는다"는 계획서 항목의 `card_generators`를 가리키므로 맞지만, 변환기가 읽는 것은 `linkage.card_generators`(`astra` 형식)다. 보고서에 한 줄 정정을 권한다.
3. **라이브인데 mock이어도 통과한다(권고)** — 판정기가 `check_models`로 막는 것은 astra와 모델명 부재뿐이다. `manifest.llm_provider=mock`, `health.llm.effective=mock`, `astra_allowed=true`, 단계 impl의 `…astra`, sol이 아닌 모델명, 카드 `generator=mock`은 모두 실패가 아니다(`models_line`에 "sol 아님"으로 적힐 뿐. 빌더의 새 시험은 mock 카드가 실패 0으로 통과함을 그대로 단언한다). 빌더의 mock 서버 드라이런이 "실패 0"이었던 이유다. 이번 커밋된 실행은 요약에 openai·sol이 명시돼 있어 결과는 정직하다. 다음 라이브부터 `health.llm.effective!='openai'`·mock 카드는 실패로 두면 8020 대신 mock 서버를 잘못 가리킨 실행이 통과로 나가지 않는다.
4. **결과 JSON 저장(소소)** — (a) 신원 키·가명 위반은 실패로 보고하면서 파일은 그대로 써 둔다(이메일·ORCID만 가려서 씀). 공개 저장소에 들어갈 파일이므로 위반이면 파일을 안 쓰거나 별도 이름으로 격리하는 편이 안전하다. (b) 키 토큰이 `models.IDENTITY_TOKENS`보다 좁다: `author`·`name`을 뺐다. 픽스처 결과에서 걸리는 것은 단계 `name` 하나뿐이라 `author`는 넣어도 오탐이 없다(`author`·`authors`·`name` 키를 넣은 결과가 신원 키로 안 잡힘을 확인). (c) 전화번호·주민번호 형태는 건수만 기록한다(`other_pii_like`, 시험에서 각 1건 가려지지 않음). 이 정도는 설계(오탐 가능)로 보고서에도 적혀 있다.
5. **화면 인용문 표본**: neural 카드 02의 인용 #4 발췌에 인용된 논문의 저자 이름 목록(References 줄)이 들어 있다. 리뷰어 신원은 아니지만 공개 예시(E6-L3d)로 쓸 때 눈으로 볼 것. 값 검사는 이름을 못 잡는다.
6. **라이브 실행 중 worktree 변경**: 검증 중 PM 쪽 재실행이 커밋된 스크린샷을 덮어쓰기 시작했다. 병합 전에 커밋되는 요약·스크린샷이 어느 실행(2 FAIL 실행 vs 재실행)인지 PM이 정리해야 한다. 이 검증의 숫자 대조는 2 FAIL 실행(커밋본) 기준이다.

## 병합 전 필수 조치

1. 발견 1: `--collect-only`에서 `NEUMANN_LIVE_TESTS`를 넣지 않게 하고(또는 시험을 main conftest와 맞게), main과 합친 상태에서 `tests/e2e`가 통과하는지 확인. 낡은 conftest 설명 문구 정리.
2. 재실행 결과를 커밋한다면 새 `E5-L1e2e_live_summary.json`에 계획서마다 `linkage.card_generators`가 들어 있는지 확인하고, 보고서의 결과 절(2 PASS·2 FAIL)을 그 실행에 맞게 고친다. 안 커밋하면 지금 요약으로는 E5-L3b P2·P6이 참고 행에 남는다는 것을 PM이 안다.
3. 권고(병합을 막지 않음): 발견 3·4 — 다음 라이브 전에 반영.
