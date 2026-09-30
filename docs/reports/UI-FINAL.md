# UI-FINAL-3 최종 화면

2026-10-01 KST. builder: codex-gpt-6.1-sol. Claude가 시작한 origin/main(96efc4d) 병합 충돌을 파일 편집으로 해소했습니다. git 쓰기·stash·main 병합·push는 하지 않았습니다. MERGE_HEAD와 인덱스 충돌은 Claude가 지정 파일 add·commit으로 완료해야 합니다.

## main 기능 보존 확인표

| 기능 | 확인 |
|---|---|
| DISP-1 | genLabel/genText의 서버 genl 우선 처리 보존. 새 채택 카드도 genl 표시. 관련 정적 검사 통과. |
| E3-L1e | 기존 ckExcluded/revExcluded 보존. 새 채택 단계 보조 영역도 review/checklist audit 제외 수·사유 표시. |
| E4-L3m | body 직속 서랍·초점 복귀·Tab 제한 보존. 1152px 클릭 검사 통과. 새 토글·근거 칩·번호·작은 버튼44px. |
| E4-L2f | result_sig 보존. 완료 내보내기에 기존 exportPayload 사용. 실제 HTTP 검사 통과. |
| FINAL-API-UI | 직접 편집→서버 재조립→새 confirmed_base_id와 확정 본문→최종 점검. 실제 HTTP 직접 편집 회귀 통과. |
| L4r-UI-connect | requestRevision/assembleBody/fromServer/exportPayload 재사용. 기존 수정 UI headless 회귀 통과. |

## 디자인 검토 반영표

| ID | 변경 |
|---|---|
| DR-01 | 팝오버 근거 단일 열, 메타 별도 행. |
| DR-02 | body 직속 fixed, 높이 제한·내부 스크롤·하단 행동바 회피. |
| DR-03 | 정보 텍스트 ink-2, 팝오버 메타 우선순위도 수정. |
| DR-04 | 시연 문안·이유 정리, Claude/Codex 오프라인 출처 표시. 미확인 출처는 한국어로 정직하게 표시. |
| DR-05 | 분석 영어 단계·내부 구현 설명 제거, 한국어 단계·초 표시·시험 모드 칩. |
| DR-06 | revise_mock_data.py·fin_mock_data.py로 두 JSON 재생성. |
| DR-07 | 입력 경계 ink-3, 제외 카드 opacity 제거. |
| DR-08 | mark·placeholder UA 색을 토큰으로 명시. |
| DR-09 | 시연 위험 제목 한국어, 실제 결과는 서버 설명·표시 이름. |
| DR-10 | 한 문장 요약, 인용은 근거 펼침에 제공. |
| DR-11 | 샘플을 감싸는 입력 외곽 카드 면·테두리 제거. |
| DR-12 | 모바일 논문 칩 pill·2×10·gap8, 최소44px 터치. |
| DR-13 | 문서 제목20/1.4/600, 화면 제목28. |
| DR-14 | 문서 대칭48, 모바일 대칭24, 문단 수평패딩0. |
| DR-15 | 완료 행동 영역을 문서 뒤 하단에 배치. |
| DR-16 | 시험 docx 버튼 준비 중·비활성, 실제 ZIP 다운로드 통과. |
| DR-17 | 데스크톱 하단 행동바 수평패딩0으로 오른쪽 정렬. |
| DR-18 | 모바일 스테퍼56px. |
| DR-19 | 카드20, 입력 중첩 외곽 면 제거. |
| DR-20 | 허용 간격으로 정리. 안전 여백80px·고지 펼침160px은 고정바 회피 예외. 카드20·칩2×10 명세 예외. |
| DR-21 | 버튼·문단·파일·대기 모서리8. |
| DR-22 | 샘플 선택·토스트 그림자 제거, 팝오버만 유지. |
| DR-23 | 거절 논문 상태 ink-2. |
| DR-24 | 검사·스테퍼16px SVG, 대기 펼침1.5px SVG. |

입력·분석·채택·수정 계획서·최종 점검·완성 이름을 통일했습니다. 원문자 번호·sandbox 제한 실행 줄을 제거했습니다. 분석 진행 화면은 주 버튼0개 예외를 유지합니다.

## 검사

모든 검사는 지정 Python, PYTHONPATH=src;., provider=mock으로 수행했습니다. OpenAI 키·salt·live 플래그 제거, 환경 값 출력·단언 없음. 브라우저는 Playwright headless만 사용했습니다.

| 명령 | 결과 |
|---|---|
| pytest test_fin_static.py test_ui_final_design.py test_finalize_ui.py | 8 passed |
| pytest test_export_ui.py test_export_ui_sign.py test_webui_gen_labels.py test_display_generator.py test_finalize_api.py test_revise_api.py test_export_revision.py | 113 passed, 2 skipped |
| pytest test_ui_final3.py test_revise_ui.py (NEUMANN_UI_TESTS=1) | 3 passed. 새 실제 HTTP 전체 흐름 및 기존 수정 UI. |
| pytest test_ui_final3.py (직접 편집 강화 후) | 2 passed. 변경 문단 직접 수정→확정 요청→최종 본문→package 전송 보존. |
| python tests/e4/test_fin_ui.py --port 8174 --out docs/reports/UI-FINAL_shots | problems[];14 PNG. 390 전6단계·375·768 가로 넘침0. 콘솔/페이지 오류0, 목업 API/외부 요청0. 서랍1152 hit-test 통과. |
| 8172 DOM 추가 측정 | 1440·390 전6단계 넘침0, 글자14/16/20/28만, Pretendard1종, 스테퍼56px. 팝오버1440 top433/bottom775≤900, 390 top334/bottom760≤844;body직속·단일열. |
| pytest test_e4_api.py test_notice.py test_revise_static.py test_fin_static.py test_ui_final_design.py test_finalize_ui.py test_static_site.py (최종) | 68 passed. 전체 검사에서 발견된 화면 관련5개 실패 원인 모두 해결. |
| scripts/verify.py 최초 | 2416 passed,57 skipped,7 failed. 화면 관련5개 원인 수정. E5 두 실패는 임시 경로 project_neumann 문자열로 발생해 중립 tmp로 전체 재검사. |

PNG·DOM 측정은 [UI-FINAL_shots](UI-FINAL_shots/)에 있습니다. 시험8174·8176·8178 종료. 8172는 이 worktree의 숨김 mock 서버로 유지합니다. Get-NetTCPConnection 접근 거부로 netstat의 정확한127.0.0.1:8172 LISTENING PID36288만 종료했고 새 PID34024를 기동했습니다. HTTP 응답에서 UI-FINAL-3 코드 포함을 확인했습니다.

최종 포트 확인에서 실제8172 리스너는 자식PID16792이며 다른 시험 포트8174·8176·8178 리스너0입니다. 12화면 DOM 측정에서 비활성 버튼을 제외한 정보 텍스트의 ink-3 사용0입니다. CSS 색 리터럴은 :root 밖0, 글자 크기4단계 밖0으로 정적 검사 통과. git diff --check 통과.

전체 재검사 중 중립 Temp 경로는 샌드박스 PermissionError로1908 passed·54 skipped·518 setup errors였습니다. 쓰기 가능한 기본 임시 경로로 다시 실행하고 있으며 이 중간 실패를 성공으로 처리하지 않습니다.

최종 scripts/verify.py: **2421 passed,57 skipped,2 failed in142.66s**. 보안718파일·계약5개 통과. 실패는 tests/e5/test_judge_n5.py::test_briefs_for_n5_one_per_judge 및 test_judge_run.py::test_claude_briefs_isolated이며 임시 절대 경로의 project_neumann 문자열을 금지어 검사로 잡습니다. E5 소유 범위이므로 수정하지 않았습니다. 전체 verify는 통과하지 않았으며 PM 병합 전에 이2건 해결 또는 쓰기 가능한 중립 경로 재검증이 필요합니다.

## 제한·다음

새 /premortem/finalize를 먼저 호출하고404/405/501에만 /premortem/revise/finalize로 재시도합니다. 실제 로컬 서버는 레거시 경로를 지원합니다. package에는 finalization·final_text·finalization_sig를 함께 전송합니다. 구형 서버가 이 선택 필드만 extra_forbidden으로 거절하면 기존 ZIP으로 재시도하며 최종 초안은 .md로 받도록 안내합니다. codex/pkg-final 병합 뒤 ZIP에 최종 초안이 포함되는지 PM이 확인해야 합니다.

실제 제품 LLM 호출0. 독립 검증·main 병합·커밋은 수행하지 않았습니다. Claude가 지정 파일을 add·commit하고 PM이 최종 병합해야 합니다. 권장 제목: [UI-FINAL-3] 6단계 최종 화면과 main 기능 통합. builder: codex-gpt-6.1-sol.
