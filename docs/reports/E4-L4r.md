# E4-L4r 보고서 — "계획서 수정 권고" UI/UX 확장(V 단계 · 수정본 뷰어 모달 · 편집 · 목업 모드)

## 남은 일(인수용 5줄)

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
