# E4-L4r 보고서 — "계획서 수정 권고" UI/UX 확장(V 단계 · 수정본 뷰어 모달 · 편집 · 목업 모드)

## Codex 인수 결과 (2026-10-01)

- 역할: E4-L4r builder, `builder: codex-gpt-6.1-sol` (운영자가 지정한 실제 모델). 독립 `gpt-6-sol` 검증은 수행하지 않았으며 PM 배정 대상이다.
- 작업tree: `C:/Users/User/Desktop/project_neumann/.claude/worktrees/s2-E4-L4r`; branch: `task/E4-L4r`; 시작 HEAD: `e4131a0cfd3d754ccefa15cb729896ccaf89ae3b`; 제품코드/테스트 커밋: `408c1cc`.
- `AGENTS.md`, `_COMMON.md`, `_VERIFY.md`, 기존 과제 보고서, HANDOFF/QUEUE, 기준 기획서 `00_구현_계획서.md`를 읽었다. 이 tree에 `docs/tasks/E4-L4r.md`와 `docs/reports/E4-L4r.verify.md`는 없다. 최신 직접 지시를 완료 기준으로 삼았다.
- 모든 실행은 mock, `NEUMANN_LIVE_TESTS=0`, `NEUMANN_LIVE_LLM_OK`/`OPENAI_API_KEY` unset. **실제 OpenAI API 호출 0회**. 키를 복원하지 않는다. 기획서/공개자료는 읽기 전용, 외부 웹검색/다운로드 0, 실서비스 8010/8020/8099 호출·조작 0, 하위 에이전트/새 CLI 0.
- 다른 branch/main 병합·push·tag 0. 계약/models/config/공통 PM 문서 수정 0. 전체 `python scripts/verify.py`는 최신 지시대로 **PM 큐에 남김**. 커밋 훅의 `verify.py --staged`는 정상 실행했다.

## 남은 일 (인수용 5줄, 최신)

1. **된 것:** 합성 fixture로 수정 권고/뷰어 UI 검사, 보존 카드 재진입·목업 초기화·인쇄 빈 페이지·미결 충돌의 원문 유지·출처/생성자 표시 수정; targeted **42 passed**, 19장 screenshot과 metrics는 `out/codex/E4-L4r/shots/`.
2. **안 된 것:** 의존 branch/main 통합과 실제 E3 mock API/HMAC 연결, 실제 서버 DOCX 생성·ZIP revision 포함, 독립 다른 모델 검증, 전체 verify. 이번 DOCX는 python-docx 합성 스텁이며 실제 API 생성 결과로 주장하지 않는다.
3. **설정:** `REV.dev=true`를 유지했다. 의존 API 병합 전 false로 바꾸지 않는다. `?mock=final`은 별도 보존 키를 쓰며 제품 API/외부 요청 0; 자신의 8171 검사 서버는 모두 종료했다.
4. **다음:** PM이 **E4-L2f → E3-L2r → E4-L3m → L4r** 순서로 통합하고 아래 체크리스트 수행; `out/codex/E4-L4r/integration/export-connect.patch`, `dev-disable.patch`는 적용하지 않은 제안이다.
5. **한계/제안:** 여러 카드 응답을 합치면 권고 서명은 null, 원문 문단 직접 편집은 .md/로그만 반영되고 서버 .docx/ZIP에는 빠진다는 안내 유지. PM은 결정 문서에 이 한계와 DOCX 출처 헤더 추가 제안을 기록한다.

## 이번에 바꾼 동작

- `renderRevise`가 카드를 DOM에 붙인 다음 본문을 그린다. 이전에는 저장된 권고가 복원돼도 단계 V로 재진입하면 카드 본문이 비었다.
- “보존값 지우고 다시”를 현재 목업 계획서 저장값 삭제와 재로드에 연결했다. 관계없는 localStorage 값은 유지하며 목업 키 `neumann.revise.mock.<plan_id>`와 일반 키를 분리했다.
- 인쇄 규칙이 뷰어의 조상 `#app`을 숨기던 문제를 고쳤다. 실제 print media에서 원고가 표시되고 컨트롤은 숨겨진다. 미결·충돌·확인 필요 수와 출처 안내는 인쇄 원고에 남긴다.
- 미해결 같은 줄 충돌은 화면 조립도 원문을 유지한다. 선택 뒤에만 해당 문안을 적용하며 제외된 안은 서버 결정 `기각`으로 보낸다.
- `result_sig`를 revise/assemble 요청에 선택 전달한다. 단일 권고의 `revision_sig`는 assemble에도 전달하고, 여러 카드 권고를 합친 경우 기존 방식대로 서명을 비운다. 합성 서명은 전달 검사값이며 HMAC 인증을 의미하지 않는다.
- `origin=client_submitted_unverified`를 카드·안내·뷰어·.md/인쇄에 표시한다. 가짜 서명 모양/가짜 생성자 라벨이 있어도 생성자·모델을 미확인으로 표시한다. localStorage에서 origin을 `server_signed`로 변조한 경우도 보존값을 새 서버 인증처럼 표시하지 않는다. 브라우저는 HMAC를 자체 검증하지 않으며 서버의 origin 판정에 의존한다.
- 다른 계획서의 plan_id와 다른 카드 id 응답을 거절한다. 같은 card_rank를 넣어도 다른 카드 id를 대신 허용하지 않는다.
- DOCX 다운로드는 기존 원문 직접 편집 제외 안내에 응답 출처 확인 정보 부재를 함께 표시한다. 현재 E3 DOCX 응답 헤더에는 인증 origin이 없으므로 JSON 결과의 인증을 DOCX 인증으로 주장하지 않는다.
- UI 검사 스텁을 `PK...TESTDOCX`에서 실제 python-docx ZIP/XML 문서로 바꾸고 본문·확인칩 값·직접 원문 편집 제외를 확인한다. 검사 서버 실행 코드가 제거한 API 키를 복원하던 동작도 없앴다.

## 완료 기준별 직접 실행과 측정

Python: `C:/Users/User/.venvs/neumann/Scripts/python.exe`. 실행 환경: `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_TESTS=0`, `NEUMANN_UI_TESTS=1`, `NEUMANN_UI_SHOTS_PORT=8171`, `PYTHONPATH=src;.`, `PYTHONUTF8=1`, `PYTHONDONTWRITEBYTECODE=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`; live/key unset. `TEMP`/`TMP`는 허용된 `out/codex/E4-L4r/temp`에 한정했다.

```text
python -m pytest tests/e4/test_revise_static.py tests/e4/test_revise_ui.py tests/e4/test_notice.py tests/e4/test_webui_upload.py tests/e4/test_view_panel.py -q -p no:cacheprovider --basetemp C:/Users/User/Desktop/project_neumann/out/codex/E4-L4r/pytest-reviewed
42 passed in 28.93s

git diff --check
(출력 없음, exit 0)

git apply --check C:/Users/User/Desktop/project_neumann/out/codex/E4-L4r/integration/dev-disable.patch
(출력 없음, exit 0; 검사만, 적용하지 않음)

커밋 기본 pre-commit 훅:
보안(스테이징): 파일 2개
verify 통과
```

| 완료 기준 | 실제 측정/단언 결과 |
|---|---|
| 진입·근거·결정·편집·Ctrl+Z·취소·재시도·뷰어 보기 3종 | `test_revise_ui` 전체 흐름 PASS; 원문 근거 문자열 일치; 취소 후 재시도 버튼 존재 |
| 검사 중 오류/외부 접근 | 예기치 않은 console/page/request 오류 각각 **0**, 외부 요청 **0**. 의도한 jobs/assemble 404와 revise 500은 별도 목록으로 남김 |
| `?mock=final` | 제품 API 요청 **0**, 외부 요청 **0**; 재로드 편집·충돌 선택 보존; reset 후 편집 제거·초기 충돌 복귀·관계없는 저장값 유지 |
| 가짜 서명/미확인 출처 | 합성 응답 4회: 타 카드 거절, 타 계획서 거절, API 없음 오류(브라우저에서만 dev=false), 미확인 생성자·통합본 안내. 위조된 보존 origin도 재검증 안 됨 표시 |
| 서명 전달 | revise에 result_sig 포함; assemble 단일 권고 서명 전달; 다중 권고 서명 null. 실제 HMAC 검증은 미측정 |
| 미결 충돌 | 목업 초기화 뒤 모든 미결 충돌 문단 `p.t === p.orig`; 서버 스텁 충돌 선택 뒤 충돌 **0**, 제외 후보 결정 `기각` |
| 확인칩/.md | 입력한 `착수 후 4주 차`가 화면·서버용 revised_text·.md에 반영; 원문 직접 편집은 .md에 반영 |
| .docx 스텁 | 유효 ZIP + `word/document.xml`; python-docx로 재열기 성공; 채운 값 포함, 원문 직접 편집 미포함; UI의 제외 안내 있음 |
| 실제 print media | `paper_visible=true`, `app_display=block`, `controls_display=none`, `draft_visible=true`, `source_visible=true` |
| 390/1440 | 수정 권고/뷰어 scrollWidth **390/390**; 뷰어 내부 **390/390**; 시트 **390×844**; 1440 수정 권고 **1440/1440** |
| 검사 서버 종료 | 마지막 검사 뒤 socket 확인: `8171 listening: False`; 자신이 만든 서버만 종료 |

검사 결과 JSON: `C:/Users/User/Desktop/project_neumann/out/codex/E4-L4r/shots/E4-L4r.metrics.json`. 스크린샷 19장(새 print 포함)은 같은 폴더에 있다. 현재 저장소의 기존 PNG들은 이전 Claude 스텁 측정물이며 이번 측정물로 덮어쓰지 않았다. CLI 실행 로그/metrics/통합 패치는 커밋하지 않는다.

### 실패도 남김

- 첫 pytest는 기본 Temp/기존 pytest cache 접근 권한 때문에 UI setup에 실패(`3 passed, 1 error`). 허용된 out basetemp/TEMP와 `-p no:cacheprovider`로 해결했다.
- 새 복원 검사는 저장 권고 카드 본문이 비는 문제를 드러냈다. DOM 부착 뒤 본문 렌더링으로 수정했다.
- 출처 검사에서 `서버 통합본 조립 중`을 완료로 먼저 읽는 테스트 경쟁 조건(`1 failed, 41 passed`)이 있었다. `state().asm.source === 'server'`와 `조립 중` 부재를 기다리도록 강화한 뒤 최종 42건 통과했다.
- 기본 sandbox에서 git add가 외부 공유 Git 메타데이터 `index.lock` 쓰기 권한에 막혔다. 사용자 지시 커밋의 파일 두 개만 대상으로 자동 승인된 escalation에서 staging/commit을 수행했다. 훅 우회 0, 자동 승인 거절 없음.
- 제안 패치 첫 dry-run은 Windows CRLF로 실패했다. 패치 파일만 LF로 저장한 뒤 `dev-disable.patch`의 `git apply --check`가 통과했다. export 패치는 의존 UI 통합 뒤 PM이 check해야 한다.

## PM 통합 체크리스트 (직접 병합하지 않음)

참조 HEAD(읽기 전용 조회 당시): E4-L2f `5ac22b5`, E3-L2r `f8932e0`, E4-L3m `d08640a`, main `17c8058`. 움직일 수 있으므로 PM은 적용 시 현재 HEAD를 다시 기록한다.

1. **순서 유지:** E4-L2f → E3-L2r → E4-L3m → L4r. E4-L3m의 패널 닫기/열기 이벤트와 L4r의 `window.NeumannUI` 훅을 모두 유지한다. CSS 별도 `rvStyle`, embedded `rvMockFinal`, 수정 권고 스크립트가 각각 하나인지 확인한다.
2. **원결과와 API:** 실제 mock `/premortem/view` 및 jobs 완료 뷰에 `result`/`result_sig`가 있어야 한다. 설치된 `/premortem/revise`의 선택 `result_sig`, assemble의 `result_sig`/`revision_sig` 허용을 확인한다. 실제 signing.py로 정상 결과·변조 결과·가짜/누락 서명·재기동을 검증한다.
3. **ZIP 연결:** `export-connect.patch`는 읽은 E4-L2f HEAD 기준이다. 통합 tree에서 `git apply --check <patch>` 후 적용하고, `doExport()`가 `Object.assign({result, result_sig, decisions}, revisionPayload)`를 보내는지 확인한다. `!window.NeumannRevise.mock`을 유지한다. revision/revised_plan/decisions 추가 시 export extra=forbid와 request 4MB 상한을 확인한다.
4. **mock 실API 검사:** 가로채기 없이 자신의 검사 서버에서 단일/여러 카드 revise → 결정 → assemble JSON → 실제 DOCX/ZIP을 검사한다. 여러 카드 서명 null은 `client_submitted_unverified`이어야 한다. 미확인 출처 UI/MD/문서 표시, 원문 문단 편집 제외 안내, 연구자 문안의 근거/각주 표기도 확인한다. 이번 테스트는 서버 실통합을 대신하지 않는다.
5. **dev 끄기:** 2~4 통과 뒤에만 `dev-disable.patch`를 `git apply --check`하고 적용한다. 일반 화면 API 404/405/501이면 모의 권고를 만들지 않고 오류·재시도를 표시해야 하며, `?mock=final`은 그대로 유지돼야 한다. 테스트에서는 이 설정을 브라우저 메모리에서만 시뮬레이션했다.
6. **통합 화면:** 390/601/616/768/1440에서 권고·뷰어·근거 서랍을 검사한다. E4-L3m 포커스 처리와 L4r 모달 Tab/Esc 복귀가 충돌하지 않아야 한다. 실제 인쇄/PDF, 깨끗한 원고/각주 판, 확인칩·충돌·편집·취소·보존을 재검사한다.
7. **병합 조건:** PM 큐의 전체 `python scripts/verify.py` 및 독립 `gpt-6-sol` 검증. 원문 편집을 서버 DOCX에 싣는 계약 확장·DOCX origin 응답 헤더는 별도 승인 제안이며 이 과제에서 계약/API를 변경하지 않았다.

제안 패치 경로는 위 out 폴더에 있고 **적용하지 않았다**. 분실에 대비한 핵심 변경은 `REV.dev: true → false` 및 `doExport`의 요청 본문에 `window.NeumannRevise.exportPayload()`를 펼치는 두 항목이다. PM 공통 HANDOFF/QUEUE/decisions는 고치지 않았다.

---

## 이전 Claude 보고서 (역사 기록, 아래 남은 일은 위 최신 내용으로 대체)

1. **된 것:** 리포트 카드 "수정안 보기"·상단 "채택한 위험으로 수정안 받기"·단계 **V 수정 권고** → 카드별 (a) 거절 사유 해석(근거 번호→기존 근거 패널) (b) 채택 연구의 대응(없으면 "대응 사례 없음") (c) 줄 단위 전후 비교 수정안(제안(근거 아님) 표시) (d) 확인 질문 (e) 채택·직접 수정·기각 → 순차 진행·취소·재시도 → **수정본 뷰어 모달**(깨끗한 원고·변경 표시·각주 판, 충돌 선택, `[확인 필요: …]` 칩 입력, 문단 편집·Ctrl+Z, 저장·취소·원래대로, 상태 줄·완성본 배지, .md·.docx(서버)·인쇄, Esc·포커스 가두기·복귀, 390 전체 화면 시트) → 브라우저 보존(localStorage) → **목업 모드 `?mock=final`**. E3-L2r 계약(`POST /premortem/revise`, `POST /premortem/revise/assemble` json·docx, 결정 채택|수정|기각+revised_text)에 맞춘 어댑터. Playwright 전체 흐름 `problems []`(콘솔·페이지 오류 0, 외부 요청 0, 목업 서버 API 요청 0), 정적 검사 3건 통과.
2. **안 된 것:** 전체 `python scripts/verify.py`는 이 세션에서 돌리지 못했다(pre-commit `verify --staged` 보안 통과, `pytest tests/e4/test_revise_static.py` 3 passed, UI 검사 통과). 실제 E3-L2r 서버와 붙여 본 적 없음(응답은 계약 모양 스텁). `git merge main`(DISP-1·SEC-6 병합된 main) 미실행 — `merge-tree`로는 main·E4-L2f·E3-L1e·E3-L2r 충돌 0, **E4-L3m 1곳 충돌**(index.html 주 스크립트 끝 `renderSteps(); render(); …` 바로 위 훅 한 줄 근처 — 양쪽 다 유지하면 됨). 뷰어에서 **원문 문단**을 직접 편집한 것은 계약상 assemble이 수정안 결정만 받아 서버 .docx에는 못 싣는다(.md·결정 로그에는 반영, 화면에 그렇게 표시). E4-L2f 내보내기 연결은 `window.NeumannRevise.exportPayload()`를 package 본문에 펼치는 한 줄이 남아 있다(E4-L2f 병합 뒤).
3. **목업 여는 방법:** `cd <worktree>` 뒤 `NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." PYTHONUTF8=1 C:/Users/User/.venvs/neumann/Scripts/python.exe -m uvicorn neumann.api.main:app --host 127.0.0.1 --port 8171` → 브라우저에서 **`http://127.0.0.1:8171/?mock=final`** (서버 없이 `src/neumann/webui/index.html?mock=final`을 파일로 열어도 같은 화면, 헤더만 "서버 응답 없음"). 화면 맨 위 노란 띠 "디자인 점검용 목업 · 가짜 데이터". 리포트 카드 "수정안 보기" → V 화면 → "수정본 보기" 뷰어(충돌 1·확인 필요 1이 남아 있어 선택·입력·편집·보기 전환을 바로 시험할 수 있다). "보존값 지우고 다시"는 아직 버튼만 있고 동작은 `window.NeumannRevise.forget()` + 새로고침.
4. **다음 단계:** ① `git merge main` → `python scripts/verify.py` → 병합 순서 제안 **E4-L2f → E3-L2r → E4-L3m → E4-L4r**(E4-L2f가 화면 응답에 `result`를 실어야 실제 revise 호출이 가능, E3-L2r이 서버, E4-L3m 반응형 CSS는 이 화면의 scoped 규칙과 같은 값). ② 병합 뒤 `REV.dev = false`(개발용 모의 어댑터 끔) 한 줄. ③ 실제 mock 서버(E3-L2r 병합)에서 `NEUMANN_UI_TESTS=1 python -m pytest tests/e4/test_revise_ui.py`와 수동 흐름 확인, 스크린샷 `docs/reports/E4-L4r_*.png` 갱신(현재 것은 스텁 응답 기준). ④ E3 제안: assemble이 `researcher_edits[{line, text}]`를 받으면 뷰어 원문 편집도 .docx에 실린다.
5. **주의:** index.html 변경은 (i) `</style>` 뒤 별도 `<style id="rvStyle">` 블록 (ii) 주 스크립트 끝 훅 한 줄 `window.NeumannUI = {…}` (iii) `</body>` 앞 `<script id="rvMockFinal">`(생성기 산출물, 손으로 고치지 말 것 — `python tests/e4/revise_mock_data.py`) + 수정 권고 `<script>` 블록. 기존 함수는 한 줄도 바꾸지 않았다(진입 버튼은 MutationObserver로 붙임). 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, 실제 OpenAI 호출 0, 8010·8020·8099 안 씀(검사 서버 8161·8162, 끝나면 종료 확인).

---

- 빌더: Claude Fable 5.1 · 브랜치 `task/E4-L4r`(worktree `.claude/worktrees/s2-E4-L4r`, main `03503d6`에서 시작) · 2026-09-30
- 대표 지시: "거절 사유 해석과 근거를 기반으로 계획서 수정 권고를 동반 … UI/UX 확장", "수정된 연구계획서는 뷰어 모달로 매우 깔끔하게", "완전한 유기체 = 근거 기반으로 고쳐진 연구계획서", "편집 기능 + 최종 완성 상태 목업".
- 서버 쪽은 E3-L2r(`task/E3-L2r` 68385cd): 계약 `contracts/revision.schema.json`·`contracts/revised_plan.schema.json`, 예시 `contracts/examples/revision.mock.json`·`revised_plan.mock.json`, 보고서 `docs/reports/E3-L2r.md` §0.

## 화면 흐름

```
리포트(III) ─ 카드마다 [수정안 보기] · 상단 [채택한 위험으로 수정안 받기] · 단계 표시 [V 수정 권고]
   │
   ▼  V 수정 권고 화면(body[data-view=revise])
   카드 고르기(체크·순서대로 진행·취소) ─ 카드 1장당 10~30초: 대기 블록(단계 이름 4개 · 경과 · 서버 단계 보고 없으면 그렇다고) · 실패 → 사유 + [다시 시도] · 취소됨 → [다시 시도]
   카드 01 ─ (a) 거절 사유 해석: 문장마다 #근거 번호(누르면 오른쪽 근거 패널: 발췌·논문·결정·원문 링크; 서버가 새로 조회한 저자 답변·결정 발췌는 번호를 이어 등록)
          ─ (b) 채택 연구의 대응: 저자 답변 근거 + 논문·결정 라벨 / 없으면 "대응 사례 없음 — 사유"
          ─ (c) 계획서 수정안: 왼쪽 원문(해당 줄 강조, 삭제 표시) · 오른쪽 제안(추가 표시, "제안(근거 아님)" 태그, 원문 불일치 경고) · 문맥 ±1줄 · 제안 이유 + #근거
          ─ (e) [채택] [직접 수정 → 편집 칸] [기각] · 제안 n · 채택 · 직접 수정 · 기각 · 미결
          ─ (d) 확인 질문
   생성 주체·근거 없는 문장 제외 수(서버 게이트·화면 게이트)·개발용 어댑터·샘플 표시 · 쓸 수 있던 기록(coverage)
   수정본 요약(채택·미결·충돌·확인 필요) ─ [수정본 보기(뷰어)] [원고 내려받기(.md)]
   │
   ▼  수정본 뷰어 모달(role=dialog, aria-modal, 포커스 가두기, Esc, 배경 딤, 390 전체 화면 시트)
   상단 바: 제목 · "변경 n곳 · 채택 m / 제안 n · 충돌 k · 확인 필요 j · 직접 수정 e" · [완성본] · 조립 출처(서버 통합본/화면 조립) · 보기 3종(깨끗한 원고 · 변경 표시 · 각주 판) · 문장 다듬기 토글(기본 끔, 게이트 거부 표시) · [.md] [.docx] [인쇄/PDF] [닫기]
   본문(종이, 70ch): 변경 문단 옅은 배경 + 여백 표식, 삭제·추가 표시, 툴팁(원문·근거 요약), 각주 판은 문장 옆 번호 → 발췌·원문 링크
   미해결 충돌 배너 "선택 필요 k건" → 문단 아래 두 안 나란히 [이 안 선택] · [확인 필요: …] 칩 → 바로 입력 · 문단 클릭 → 편집(저장 Ctrl+Enter · 취소 Esc · 원래대로) · Ctrl+Z
```

## 서버 계약 어댑터(E3-L2r)

| 호출 | 본문(정확히 이 키만, 계약 extra=forbid) | 응답 처리 |
|---|---|---|
| `POST /premortem/revise` | `{result: 화면 응답의 result(E4-L2f), plan_text: S.text, card_ids: [카드 id]}` 카드마다 1회(순차) | `revisions[]`에서 카드 찾기 → 해석·대응·수정안·질문·audit 정규화, `records[]`·`works[]`를 근거 패널에 등록, `cards_skipped` → "권고 없음 · 사유", 202+job_id면 폴링 |
| `POST /premortem/revise/assemble` | `{plan_text, revision: 카드별 응답 합침(1개면 서명 유지), decisions: [{edit_id, card_id, decision: 채택|수정|기각, revised_text?, note?, decided_at}], result?, polish, format: json|docx, title}` | `lines/changes/conflicts/placeholders/stats/polish/markdown/label` → 뷰어 모델. 404·405·501이면 화면 조립으로. 충돌에서 고르지 않은 안은 `기각`+메모, 자리표시를 채운 채택안은 `수정`+revised_text |
| 원결과 없음(샘플·E4-L2f 병합 전) / API 404 | 개발용 어댑터(`REV.dev`)가 모의(mock) 권고를 계약 모양으로 만들고 화면에 "개발용 어댑터 · 사유 · 모의 권고" | 병합 뒤 `REV.dev = false` 한 줄 |

정직성: 생성 주체는 DISP-1 방식(`_status.generator_labels` > "LLM (모델명)" · "비상 규칙" · "모의(mock)"), 근거 번호로 풀리지 않는 문장은 화면 게이트가 빼고 수를 표시(서버 게이트 수와 따로), 샘플·mock·개발용 어댑터·서버 조립/화면 조립 표시, 제안 문안 "제안(근거 아님)", 다듬기 게이트 거부 그대로 표시.

## 완료 기준별 명령과 출력

공통: `NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." PYTHONUTF8=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`, `NEUMANN_LIVE_LLM_OK` 없음, 파이썬 `C:/Users/User/.venvs/neumann/Scripts/python.exe`.

```
$ python -m pytest tests/e4/test_revise_static.py -q
3 passed in 0.42s
$ python tests/e4/revise_mock_data.py --check
mock block fresh
$ python tests/e4/test_revise_ui.py --port 8161 --out <scratch>/shots        # 서버 8161 하위 프로세스, 끝나면 종료
problems []
  console_errors [] · page_errors [] · failed_requests [] · external_requests []
  revise 요청 키 ['card_ids','plan_text','result'] · assemble 요청 format json/docx
  뷰어: role=dialog · 제목 포커스 · 변경 2곳 · 칩 1 · 인쇄 규칙 있음 · 본문 폭 646px ≤ 760
  편집: 저장 → 직접 수정 2 · 결정 로그 rev-edit modify · .md 반영 · 보존값 반영 → Ctrl+Z → 직접 수정 1
  충돌: 서버 통합본 배너 "선택 필요 1건" → 선택 → 충돌 0 · 고르지 않은 안 기각 전송 · .docx 내려받음(PK, 변경 3)
  다듬기: "다듬기 미적용 — 게이트 거부: placeholders_changed at 17"
  목업(?mock=final, 새 문맥): 서버 API 요청 0 · 외부 요청 0 · 새로고침 뒤 편집·충돌 선택 보존
  390: revise 390/390 · viewer 390/390(시트 390×844) · 1440/1440
```

스크린샷(`docs/reports/E4-L4r_*.png`, 스텁 응답 기준): report_entry · revise_card · evidence · decisions · viewer_marks · viewer_clean · viewer_notes · viewer_editing · retry · viewer_conflict · waiting · 390_revise · 390_viewer · mock_1440_report · mock_1440_revise · mock_1440_viewer · mock_390_viewer · mock_390_revise.

## 바꾼 파일

- `src/neumann/webui/index.html`: `<style id="rvStyle">`(198줄), 훅 1줄, `<script id="rvMockFinal">`(생성기), 수정 권고 `<script>` 블록(약 870줄).
- `tests/e4/test_revise_ui.py`(Playwright, NEUMANN_UI_TESTS=1), `tests/e4/test_revise_static.py`(verify), `tests/e4/revise_mock_data.py`(목업 블록 생성기).
- 계약·`models.py`·다른 소유 파일은 건드리지 않았다.

## 결정(모호해서 고른 것)

1. 카드마다 revise를 따로 부른다(진행·취소·재시도 단위, 90초 동기 상한 안). assemble에는 응답을 합쳐 보낸다(둘 이상이면 `revision_sig`를 비움 → 내보내기는 client_submitted_unverified).
2. 새 발췌(records)는 기존 `D.ev`에 번호를 이어 등록해 기존 근거 패널·지도가 그대로 쓴다(리포트 KPI "근거 문장 n건"이 그만큼 는다).
3. "채택한 위험" = 체크리스트에서 채택한 항목의 카드, 없으면 모든 카드.
4. 원문 문단 편집은 화면·.md·결정 로그(`rev-edit:<줄>` modify)에만(계약 한계, 화면에 표시). 제안 문단 편집은 그 수정안의 결정 "수정".
5. 반응형 상단바 규칙은 E4-L3m 값을 `body[data-view="revise"]`에만 복제(병합 뒤 같은 값이 겹침).

## 다른 브랜치와 겹칠 수 있는 줄

`git merge-tree --write-tree`(HEAD 기준): main(19a41f5)·E4-L2f·E3-L1e·E3-L2r **충돌 0**, **E4-L3m 1곳**(index.html 주 스크립트 끝, 훅 한 줄 `window.NeumannUI = {…}`과 E4-L3m의 클릭 처리 두 줄이 이웃 — 둘 다 유지). CSS는 `</style>` 뒤 별도 블록이라 E4-L2f·E4-L3m의 `</style>` 앞 CSS와 겹치지 않는다. DISP-1(이미 main)의 `genl`은 `_status.generator_labels`로 읽어 쓴다.
