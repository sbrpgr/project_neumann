# FIN-UI 보고서 — 최종 형태 화면 + 시연 목업(`?mock=final` ①~⑦)

## 목업 여는 명령 (맨 위)

```
cd C:/Users/User/Desktop/project_neumann/.claude/worktrees/s3-FIN-UI
NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." PYTHONUTF8=1 C:/Users/User/.venvs/neumann/Scripts/python.exe -m uvicorn neumann.api.main:app --host 127.0.0.1 --port 8172
```
브라우저(크롬)에서 **`http://127.0.0.1:8172/?mock=final`** → 첫 화면은 ① 연구계획 입력. 단계 바로가기: `?mock=final&at=input|job|report|revise|final`
(각 단계는 그 앞 단계가 끝난 상태로 열린다. `at=final`은 ④ 확정을 자동으로 눌러 ⑤→⑥→⑦까지 보여 준다). 화면 맨 위 앰버 띠 "디자인 점검용 목업 · 가짜 데이터"에 같은 바로가기 버튼과 "보존값 지우고 다시"가 있다.
서버 없이 `src/neumann/webui/index.html?mock=final`을 파일로 열어도 같은 화면(헤더만 "서버 응답 없음"). 실제 OpenAI 호출 0, `OPENAI_API_KEY`는 모든 명령·서버 기동에서 뺐다(`env -u OPENAI_API_KEY`).

## 남은 일 (인수용 5줄)

1. **된 것:** `?mock=final`이 대표 정의의 최종 형태 한 줄 이야기로 이어진다 — ① 입력(샘플 갤러리·붙여넣기·PDF/DOCX/HWPX 업로드·300자 안내) → ② 가짜 분석 진행(WAIT-UX 연결 자리) → 위험카드 → ③ 재탄생(V, 편집·채택·수정·기각) → ④ **"수정 확정·검증" 한 번** → ⑤ 최종 점검 진행 화면(논리→물리→구조→근거→교정→재검사, 도구 호출 19건이 이름·입력·결과·상태·줄과 함께 실시간 로그) → ⑥ 최종 초안(교정 6줄 적용·1줄 게이트 제외, 원문→수정·이유·도구 근거 배지, 해결 1·미해결 1·확인 필요 5·미검사 1, .md 내려받기·인쇄) → ⑦ 전후 비교(위험 해소 2/2 · 수정 2줄 · 오류 수정 6/7 · 쟁점 해결 1/8 · 도구 호출 19). Playwright 흐름 검사 `problems []`(콘솔·페이지 오류 0, 서버 API·외부 요청 0, 390·768·1440 가로 넘침 0), 정적 검사 7건, 기존 E4-L4r 검사 `problems []` 유지.
2. **안 된 것:** 실제 서버 `POST /premortem/revise/finalize`(Codex `codex/finalization-20261001`의 `src/neumann/api/finalize.py`)와 붙여 본 적 없음 — 이 브랜치에는 그 API가 없고 화면 어댑터만 같은 경로·본문으로 부른다. FIN-ENGINE의 시연 fixture는 아직 커밋되지 않아 **같은 모양의 가짜 fixture**(`tests/e4/fin_mock_data.py`)로 진행했다(도구 실행 기록도 가짜 — 실제 Z3·Pint·NetworkX 실행 아님, 화면에 그렇게 표시). `.docx`는 서버가 만들어야 하므로 목업에서는 안내만. 인쇄는 브라우저 인쇄 CSS까지(실제 PDF 저장은 수동 확인). 전체 `python scripts/verify.py`는 PM 큐.
3. **설정·주의:** 목업 데이터 블록 두 개는 생성기 산출물이다 — `python tests/e4/revise_mock_data.py`(`rvMockFinal`: 계획서 6~8절 의도적 오류 포함) · `python tests/e4/fin_mock_data.py`(`finMockFinal`). 손으로 고치면 정적 검사가 STALE로 막는다. 8172는 대표가 보는 목업 서버(종료하지 말 것, 로그 `C:/Users/User/Desktop/pn_logs/mockup_8172.*.log`).
4. **다음:** ① FIN-ENGINE fixture가 오면 `fin_mock_data.py`가 그 파일을 읽도록 바꾸고(`trace`·`corrections[].before` 앵커 규칙은 아래 §어댑터), 화면 어댑터 `normFinal`은 그대로. ② 실제 서버와 붙일 때 `assembleBody('json') + submission_id + confirmed_text + confirmed_base_id` 본문이 `FinalizeRequest`에 맞는지 확인(Codex `tests/e4/test_finalize_ui.py`가 기대하는 문자열과 함수 이름은 다르다 — 이 화면은 `requestFinalization/finalizationPanel` 대신 `NeumannFinal.start/renderFinal`). ③ WAIT-UX 모듈(`window.NeumannWait.update(info)`)이 오면 `waitHook` 호출만으로 연결된다. ④ 통합 시 `finStyle`의 전역 반응형 규칙은 E4-L3m(d08640a)과 같은 값이므로 하나만 남긴다.
5. **한계/정직성:** 교정 문안은 근거가 아니며 최종 판단은 연구자에게(화면·.md에 표시). 도구는 명시된 수치·단위·선행관계만 검사하고 연구 전체 타당성을 보증하지 않는다(안내문). 서명 없는 결과는 "목업 fixture · 서명 없음"으로 표시. 실제 LLM의 의미 검토 품질은 이 목업으로 입증되지 않는다.

## 화면 흐름(최종 형태, 한 줄로 이어지는 이야기)

```
① 입력(body[data-view=input])  샘플 갤러리(목업 3종: fixture 1 + 자리 2) · 붙여넣기(300자 기준 실시간 안내) · 파일 업로드(PDF·DOCX·HWPX·TXT·MD) → [Pre-mortem 실행 →]
② 분석(job)  목업은 서버 호출 없이 6단계 타임라인(정리→질의→검색·거절 기록 조회→지적 추출→위험카드 합성→원문 대조)을 재생 · WAIT-UX 자리: window.NeumannWait.update({mock,state,stage,label,index,total,elapsed})
   → 리포트(report)  유사 연구 거절 기록 → 위험카드 2장(근거 번호 → 근거 패널) · 카드마다 [수정안 보기]
③ 재탄생(revise, V)  거절 사유 해석 → 채택 연구의 대응 → 계획서 수정안(줄 단위 전후 비교, 편집 가능) → 채택·직접 수정·기각 → 수정본 뷰어(충돌 선택·[확인 필요] 입력·문단 편집)
④ [수정 확정·검증 →]  수정본 요약(#rvFinalize)과 뷰어 바(#rvFinalize2) 두 곳 · 채택 0이면 비활성 · 미결·충돌·확인 필요는 "최종 점검에서 확인 필요로 남음" 안내
⑤ 최종 점검 진행(final, VI)  단계 타임라인(논리·물리·구조·근거·교정·재검사, 단계별 도구 n·불일치 m) + 진행 막대 + 도구 호출 기록(role=log, aria-live=polite):
   시각 · 단계 · 도구 이름[상태 배지] · check_id · 종류 · n행 · ms / 입력 / 결과 / 메시지 — 계산기 · 합계·제약(Z3) · 단위·차원(Pint) · 구조·선행관계(NetworkX) · 구조(절 번호) · 인용·철회 조회 · 제한 실행 · 근거 대조 · 교정 제안(mock LLM)
⑥ 최종 초안  요약 6칸(해결·미해결·확인 필요·미검사·교정 적용/제외·도구 호출) → [교정 표시 | 깨끗한 원고] → 종이(74ch): 교정 문단(앰버, "교정 n" 태그, Tab·Enter로 기록 점프) 아래 상자 "원문 → 수정 · 이유 · 도구 근거 배지(누르면 ⑤ 기록의 해당 줄로 펼쳐·강조·초점)",
   ③ 채택/직접 수정 문단(파랑), [확인 필요: …] 칩 → 교정 목록(제외된 제안은 사유만) → 쟁점 목록(종류·줄·도구 배지·상태) · [최종 초안 내려받기(.md)] [.docx(서버)] [인쇄/PDF] [다시 확정·검증]
⑦ 전후 비교  타일 5개(위험 해소 n/N · 수정 n줄 · 오류 수정 n/N · 쟁점 해결 n/N · 도구 호출 n) + 표(위험카드 · 오류 · 줄 수 · [확인 필요] · 근거 · 생성 주체: 처음 계획서 ↔ 최종 초안)
무효화: ③에서 결정·편집·충돌 선택·자리표시가 바뀌면(persist) 이전 ⑤⑥⑦ 결과는 사라지고 VI 단계는 "다시 확정" 상태로
```

## 서버 계약 어댑터(FIN-UI 스크립트 블록 → FIN-ENGINE)

| 호출 | 본문 | 응답 처리 |
|---|---|---|
| `POST premortem/revise/finalize` (Codex codex/final-ui-20261001 2ac62f8 · `contracts/finalization.schema.json`) | `assembleBody('json')` + `polish:false` + `submission_id` + (서버 통합본이 있을 때) `confirmed_text`(확정 문안 전체) · `confirmed_base_id`(revised_plan_id) | `finalization@v1` → `normFinal`: `tool_checks_before/after` → 도구 로그(단계 tools/recheck), `corrections[]`는 `before` 줄 문자열로 **현재 확정 문안에 앵커**(안 맞으면 `anchor_mismatch` "적용 못 함 · 원문이 달라짐"), `issues[]` 상태 resolved/unresolved/unchecked → 화면 상태 해결/미해결/확인 필요(교정이 `[확인 필요]`를 남겼거나 재검사가 unchecked)/미검사 |
| 404·405·501 | — | "서버 최종 점검 API 없음 — FIN-ENGINE 연결 전" 실패 표시 + [다시 시도] |
| 목업(`?mock=final`) | 서버 호출 없음 | `<script id="finMockFinal">`의 `trace[]`를 `t`초 타이머로 재생(실시간 로그), 끝나면 같은 fixture의 `finalization`을 `normFinal`에 통과 |

화면용 확장(엔진이 채택하면 좋은 것): `trace[] = {t, stage, tool, name, check_id, kind, plan_lines, input, result, status, message, ms}`, `stages[] = {id, name, desc}`, `corrections[].proposed`(제외된 제안의 원문 — `after`는 `[검사에서 제외된 수정안]`). 없으면 `tool_checks_*`만으로 로그를 만든다.

## 목업 fixture(가짜)

- 계획서: 공용 fixture `plan.md`(1~5절, 위험카드 16·17·22행 불변) + 6~8절(`revise_mock_data.EXTRA_PLAN`) — **의도적 오류**: 2·3단계 선행관계 순환(구조), 예산 항목 합 1억 1,000만원 ≠ 총액 1억 2,000만원(논리·합계), 250 mL × 40회 = 10 L ≠ 8 L(논리·계산기), 상온 25 K(물리·단위), 전도도+점도 합산(물리·차원), 참고문헌 [3] 철회 기록(근거·인용 조회), [1] 거절 논문 인용(미해결 예시).
- 최종 점검: 도구 호출 19건(통과 8 · 불일치 7 · 미검사 4), 교정 7건(적용 6 · `unsupported_content`로 제외 1 — "논문으로 발표한다" 새 내용), 쟁점 8건(해결 1 · 미해결 1 · 확인 필요 5 · 미검사 1), 상태 `partial`, `generator: mock`, 서명 없음.

## 완료 기준별 명령과 출력

공통: `env -u OPENAI_API_KEY -u NEUMANN_LIVE_LLM_OK NEUMANN_LLM_PROVIDER=mock NEUMANN_LIVE_TESTS=0 PYTHONPATH="src;." PYTHONUTF8=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`, 파이썬 `C:/Users/User/.venvs/neumann/Scripts/python.exe`.

```
$ python -m pytest tests/e4/test_fin_static.py tests/e4/test_revise_static.py -q -p no:cacheprovider
7 passed
$ python tests/e4/fin_mock_data.py --check ; python tests/e4/revise_mock_data.py --check
fin mock block fresh / mock block fresh
$ NEUMANN_UI_TESTS=1 python tests/e4/test_fin_ui.py --port 8174 --out docs/reports        # 서버 8174 하위 프로세스, 끝나면 종료(8174 free)
problems []
  input: view=input · 띠 "디자인 점검용 목업 · 가짜 데이터" · 샘플 3 · 안내 "입력 1320자 · 300자 기준 충족 · 파일 업로드: PDF · DOCX · HWPX …" · 바로가기 5
  job: state=running · 타임라인 7칸 · "목업 분석 중 · 계획서 정리 · 서버 호출 없음"
  report: 카드 2 · "완료 · 제안 3건 · 채택 1 · 직접 수정 1 · 기각 1 · 미결 0" · 단계 I~VI · 계획서 31줄
  revise: 카드 2 · 요약 "4채택 / 2미결 / 1충돌 / 2확인 필요 … 수정 확정·검증 →" · 확정 버튼 활성 · VI 활성
  run_mid: 로그 6줄 · running · 실행 중 1 · 완료 1 · role=log aria-live=polite · 첫 줄 "0.3s 논리 점검 제한 실행 (계산만 …) 통과 split-sizes 15행 16행 41 ms 입력 n = 12000; … 결과 [9600, 1200, 1200] · 합 12000"
  done: 로그 19줄 · 해결 1 · 미해결 1 · 확인 필요 5 · 미검사 1 · 교정 적용 6 · 제외 1 · 도구 호출 19(불일치 7 · 통과 8) · 교정 문단 6 · 배지 6 · 쟁점 8 · 칩 14 · 초점 finDraftTitle · status partial
      · final_text에 "[확인 필요: 항목 합" · input_text에 원문 "총 예산은 1억 2,000만원이다" · 도구 {calc,z3,pint,networkx,records,sandbox,outline,grounding,llm}
  compare: 타일 5(위험 해소 2/2 · 수정 2줄 · 오류 수정 6/7 · 쟁점 해결 1/8 · 도구 호출 19회) · 표 6행
  jump: 배지 → 기록 강조 1 · 펼침 · 초점 기록 안 · aria-expanded=true / kbd: 교정 문단 Tab(tabindex 0)+Enter → "1.2s 논리 점검 합계·제약 (Z3) 불일치 budget-sum 37행 … unsat · 좌변 11000"
  md: plan_final.md 97줄 · 교정 반영 · 점검 요약 · 교정 목록 · 도구 호출 기록 · 제외 제안 본문 미반영
  invalidate: 결정 변경 뒤 status=idle · VI 버튼 활성(다시 확정)
  narrow: final 390/390 · 768/768, input·report·revise 390·768 전부 sw=iw
  console_errors [] · page_errors [] · api [] · external [] · requests 70 · 8174 free
$ NEUMANN_UI_TESTS=1 python tests/e4/test_revise_ui.py --port 8175 --out <scratch>        # 기존 E4-L4r 검사(목업 구간은 &at=report)
problems []   · 8175 free
```

| 완료 기준 | 측정 |
|---|---|
| ①~⑦ 클릭으로 이어짐 | 입력(샘플 3·안내·업로드) → 진행 → 리포트 2장 → V → 확정 버튼 2곳 → 진행 로그 → 최종 초안 → 전후 비교 → 배지 점프 → .md → 무효화 → 다시 확정: 전부 PASS |
| 콘솔 오류 · 페이지 오류 | 0 · 0 |
| 서버 호출 · 외부 요청 | `/premortem/`·`/upload` 0 · 외부 도메인 0 |
| 반응형 390·768·1440 | 입력·진행·리포트·수정 권고·최종 초안 전부 scrollWidth = clientWidth(768 상단바 넘침은 E4-L3m 값으로 해결) |
| 접근성 | ⑤ 진입 시 제목 초점, `role=log aria-live=polite`, 교정 문단 `tabindex=0`+Enter → 기록 점프·초점, 배지 `aria-label`, 보기 전환 `aria-pressed`, 기록 접기 `aria-expanded/controls`, 서버·fixture 문자열 textContent만(innerHTML 대입은 상수 SVG 한 곳) |
| 정직성 | 목업 띠 상시 · "도구 실행 기록도 가짜" · 생성 주체 mock · "서명 없음" · 교정은 근거 아님 · 제한된 검사 안내 |

스크린샷(`docs/reports/FIN-UI_*.png`, 목업 fixture 기준): 1440_1_input · 1440_2_job · 1440_2_report · 1440_3_revise · 1440_3_viewer · 1440_5_running · 1440_6_final_top · 1440_6_draft · 1440_7_compare · 1440_final_full · 390_5_run · 390_6_draft · 768_6_draft · 390_1_input.

## 바꾼 파일

- `src/neumann/webui/index.html`: `<style id="finStyle">`(final 화면 + E4-L3m 전역 반응형 값 복제), 수정 권고 블록 6곳(④ 버튼 2, `persist→invalidate`, `confirmed()`·`assembleBody`·`mockData` export, 목업 띠 바로가기·`mockJump`, `?at=`), `<script id="finMockFinal">`(생성기), FIN-UI 스크립트 블록(`window.NeumannFinal`, VI 단계 버튼 `#stpFinal`, 목업 ①② 보조: 샘플 갤러리·300자 안내·가짜 분석·`waitHook`).
- `tests/e4/revise_mock_data.py`(계획서 6~8절 확장) · `tests/e4/fin_mock_data.py`(새) · `tests/e4/test_fin_static.py`(새) · `tests/e4/test_fin_ui.py`(새) · `tests/e4/test_revise_ui.py`(목업 구간 `&at=report` 1줄).
- 계약·`models.py`·API·다른 소유 파일은 건드리지 않았다. Codex final-ui 코드는 가져오지 않고 **id·경로·본문 키만 같게** 맞췄다(출처 표기).

## 결정(모호해서 고른 것)

1. 목업 첫 화면은 ① 입력(대표 지시). 기존 E4-L4r 검사는 `&at=report`로 리포트부터 본다.
2. ⑤⑥⑦은 한 단계(VI 최종 초안, `body[data-view=final]`) 안의 세 절로 두고 목차로 오간다 — 진행이 끝나면 ⑥으로 부드럽게 스크롤·제목 초점, ⑤ 기록은 접힘(배지로 다시 펼침). 모달이 아니라 문서 편집기처럼 한 페이지.
3. 교정은 줄 번호가 아니라 **원문 문자열 앵커**로 적용한다(연구자가 ③에서 문안을 바꿔도 안전, 엔진의 `anchor_mismatch`와 같은 뜻).
4. ③의 미결·충돌·확인 필요가 남아도 확정을 막지 않는다(자리표시는 "확인 필요"로 ⑥에 남고 ⑦에 센다). 채택 0이면 비활성.
5. 목업 ①의 샘플 갤러리는 fixture 1종만 실제로 불러오고 나머지 2종은 "목업에는 fixture 없음"으로 정직하게 표시(실제 서비스는 `/templates`).
6. 768 상단바 넘침은 이 브랜치의 기존 문제(E4-L3m 미포함)였지만 최종 형태 검수 기준(390·768·1440)이므로 같은 값을 `finStyle`에 전역으로 넣었다.

---

- 빌더: Claude Fable 5.1 · 브랜치 `task/FIN-UI`(worktree `.claude/worktrees/s3-FIN-UI`, `task/E4-L4r` 62ce57b에서 시작) · 2026-10-01
- 대표 지시: "수정 권고 데모도 우리 기획의 최종 형태 기준 … 불완전한 기획서를 넣는다 → 불완전한 유기체들이 완성도를 높여 준다 → 연구자가 확정 → 최종적으로 논리·물리·구조 오류를 점검·수정해 완성도를 높인 연구계획서 초안 … 에이전트가 도구를 활용해 검증까지", "첫 화면은 연구계획 입력창".
- 참조: E4-L4r(62ce57b) 목업·보고서, Codex `codex/final-ui-20261001`(2ac62f8: rvFinalize·finalize 경로), `codex/finalization-20261001`(b629789: `contracts/finalization.schema.json`, `analyze/finalize.py`, `final_tools.py`), `codex/ui-ux-followup`(c18d38d: a11y — 이번엔 가져오지 않음), E4-L3m(d08640a 반응형 값).
