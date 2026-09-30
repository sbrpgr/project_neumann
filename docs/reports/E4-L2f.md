# E4-L2f 보고서 — 화면 "IV 내보내기" 켜기

빌더: claude-opus-5.5 · 브랜치 `task/E4-L2f` · 모든 실행 `NEUMANN_LLM_PROVIDER=mock`(OpenAI 호출 0), 서버 8149만 사용.

## 무엇을 했나

1. **화면(index.html, 내보내기 부분)**: 단계 IV "내보내기"와 리포트 섹션 VI "ZIP 내려받기" 버튼을 켰다.
   - 결과 없음·샘플·오류·원결과 없음이면 단계와 버튼을 끄고 사유를 보인다(단계는 `title`과 짧은 표시, 섹션은 `#expWhy`).
   - 단계 IV를 누르면 리포트의 내보내기 섹션으로 이동한다.
   - 버튼은 `{result, decisions}`를 `POST /premortem/package`로 보내고, 받은 ZIP을 내려받는다. 파일 이름은 서버의 `Content-Disposition`을 쓴다.
   - 결정은 연구자가 고른 항목만 보낸다: `{item_id, decision(adopt|hold|reject), note?, decided_at?}`로 `export.py` `DecisionEntry` 형식 그대로다.
     - 결과에 원래 실린 결정은 `set: true`로 온다. 화면에서 클릭한 결정은 클릭 시각을 `decided_at`으로 붙인다.
     - 결정 전 기본값 "보류"는 싣지 않는다. 몇 건인지 화면에 적는다.
   - 서버 오류 문구(`message` → `detail` → `reason` 순)는 `textContent`로 넣는다. 다시 그릴 때는 `esc()`를 거친다.
2. **서버(view.py)**: `build_ui_view`가 화면 응답에 원결과를 싣는다(코디네이터 정정 지시 2).
   - 싣는 것: `result`(`PremortemResult`로 검증한 계약 필드만의 JSON)와 `_status.export = {result, reason}`.
   - `/premortem/view`와 E4-L2d jobs 화면 결과가 같은 함수를 쓰므로 둘 다 이 필드를 갖는다. `jobs.py`·`main.py`는 고치지 않았다(충돌 0).
   - 샘플·오류·계약 밖 필드가 있는 결과는 `result: null`과 사유를 싣는다.
   - 가림은 화면과 같다: 계획서 줄·인용은 결과 값 그대로이고, 이메일·ORCID는 분석 입구(`PlanDocument`)에서 이미 가려져 있다.
   - 계약 밖 값(설정·경로·키)은 extra=forbid라 실리지 않는다. 계약 밖 필드가 섞인 결과는 통째로 싣지 않는다(테스트로 확인).
3. **재분석 없음**: 첫 판에 있던 "같은 계획서로 `POST /premortem`을 다시 불러 원결과 받기" 경로는 지웠다.
   - 내보내기 때 요청은 `/premortem/package` 한 건뿐이다(Playwright로 확인).
4. **Playwright 실패 원인**: 테스트의 경쟁 조건이었다(실제 버그 아님).
   - 디버그: 같은 `.dec`를 세 번 누르면 보류→기각→채택→보류로 매번 바뀌었다(mousedown·click 이벤트 3쌍).
   - 원인: 집계는 클릭 뒤 다음 틱에 다시 그린다. C3의 첫 클릭 뒤 중간 상태("결정 3건 · 채택 1 · 기각 2")에서 `'결정 3건'` 대기가 먼저 풀렸다.
   - 수정: 최종 값("채택 2 · 보류 0 · 기각 1")을 기다리고, 칸별 결정 문구도 확인한다.

## 완료 기준별 측정

| 기준 | 명령 | 결과 |
|---|---|---|
| 정적·서버 검사 | `NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4/test_export_ui.py -q` | `8 passed, 1 skipped` |
| Playwright 1440×900, 서버 8149, mock, 끝나면 종료 | `NEUMANN_UI_TESTS=1 NEUMANN_LLM_PROVIDER=mock python -m pytest tests/e4/test_export_ui.py -q` (main 병합 뒤) | `9 passed in 24.67s`, 이후 `netstat`에 8149 LISTEN 없음 |
| ZIP 9파일 | 같은 테스트(내려받은 ZIP을 `zipfile`로 엶) | `README.md, manifest.json, risk_cards.json, evidence_pack.json, similar_works.csv, plan_annotated.md, neumann_report.md, ai_context.md, decision_log.json` (`FILE_NAMES` 순서 그대로) |
| decision_log 내용 | 같은 테스트 | 아래 표. `manifest.counts.decisions == 3`, 리포트에 `## 결정 로그`·`행동 \`C2\`: 기각`, ZIP 어디에도 원 이메일 없음 |
| 재분석 없음 | 같은 테스트(POST 경로 기록) | `["/premortem/view", "/premortem/package"]` |
| 결과 없음·샘플·원결과 없음 비활성 | 같은 테스트 | 첫 화면 `내보내기 · 분석 결과 없음`, 샘플 `내보낼 수 없음 · 샘플 데이터(분석 결과 아님)`, 원결과 없는 뷰 `내보낼 수 없음 · 화면 응답에 원결과가 없음`(POST는 view 1건뿐) |
| 서버 문구 textContent | 같은 테스트(422 `detail`에 `<img onerror>`, 429 `message`) | 문구가 글자 그대로 보이고 `#expMsg img` 0개, `window.__xss` 없음. `내보내기 실패 · 요청이 많습니다. 잠시 뒤 다시 시도하세요.` |
| verify | `NEUMANN_LLM_PROVIDER=mock python scripts/verify.py` (main 병합 뒤) | `1216 passed, 28 skipped` · `verify 통과` |

decision_log.json의 `decisions`(Playwright, plan.md, mock):

| item_id | decision | note | decided_at |
|---|---|---|---|
| C1 | adopt | `표본 크기 근거 보강 · 담당 [EMAIL]` (뷰에 실린 결정·메모, 이메일은 `DecisionEntry`가 가림) | null |
| C2 | reject | null | 클릭 시각(UTC) |
| C3 | adopt | null | 클릭 시각(UTC) |

스크린샷: `docs/reports/E4-L2f_export.png`(1440×900, 내려받은 뒤 내보내기 섹션).

## 바꾼 파일

- `src/neumann/webui/index.html`: `renderSteps`의 단계 IV, `renderReport` 반환 줄(`expHtml()` 추가), E4-L2f 블록(`exp*` 함수·클릭 처리), CSS 한 묶음.
- `src/neumann/api/view.py`: `export_result`, `_attach_result`, `build_ui_view`에서 호출(정정 지시 2로 범위 넓힘).
- `tests/e4/test_export_ui.py`(새 파일), `docs/reports/E4-L2f.md`, `docs/reports/E4-L2f_export.png`.
- `export.py`·`main.py`·`jobs.py`·계약(`contracts/`, `models.py`)은 고치지 않았다.

## 결정

- 필드 이름은 `result`로 했다. ui_view 계약 루트가 추가 필드를 허용해서 계약 변경이 없다(`validate_ui_view` 통과를 테스트로 확인).
- 원결과는 `build_ui_view`에서 붙였다. 그래서 E4-L2d jobs(`_present`가 `build_ui_view` 호출)도 코드 변경 없이 같은 필드를 갖는다.
- 결정 전(기본값 보류) 항목은 결정 로그에 싣지 않는다. 연구자가 고르지 않은 것을 결정으로 기록하지 않으려는 것이다.
- 화면의 `result.plan_id`가 뷰의 `plan_id`와 다르면 내보내지 않는다.

## 못 한 것 · 제안

- 메모 편집 UI는 없다(체크리스트 부분은 이 과제 소유가 아니다). 결과에 실린 메모(`note`)만 보낸다. 제안: 체크리스트 "메모" 칸을 입력칸으로 바꾸면 `it.m`이 그대로 실린다.
- 화면 응답이 커진다. plan.md(mock) 기준 원결과 약 44KB가 뷰(약 28KB)에 붙는다. 제안: 커지면 서버 보관 결과 id로 바꿀 수 있다.

## 다음 과제에 넘길 것

- E4-L2d 병합 뒤 jobs 화면 결과(`format: "view"`)에도 `result`가 실리는지 한 번 확인하면 된다(같은 `build_ui_view` 경로).
  - 확인 명령: 이 테스트를 `NEUMANN_UI_TESTS=1`로 다시 돌린다.
  - POST 경로 기대값은 `/premortem/view` 대신 jobs 경로로 바뀔 수 있다. 바뀌면 테스트 기대값만 고친다.
