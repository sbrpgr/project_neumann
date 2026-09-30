# E4-L4r-UI-connect — 실제 로컬 HTTP UI 통합

남은 일 (PM 인계, 5줄):
1. 이 보고서를 포함한 안정 HEAD에 gpt-6-sol 독립 UI 검증을 배정한다.
2. 별도 core authority 수정 브랜치는 PM이 순서대로 통합하고 서명·출처 회귀를 다시 잰다.
3. PM 큐에서 전체 `scripts/verify.py`를 실행한다(빌더는 실행하지 않음).
4. 공개 원본 backend와 승인된 실사용 운영 환경은 PM이 별도로 검증한다(이번 검사는 fixture + mock).
5. 라이브 OpenAI·공개 배포·main 병합·push·tag는 이 작업에서 수행하지 않았다.

## 작업 상태와 권한

- 작업트리: `C:/Users/User/Desktop/project_neumann/out/codex/ui-integration`
- 브랜치: `codex/ui-integration-20261001`
- 시작 HEAD: `8aed6015e8e6793e421c9fc5753e73c43b9f5353`
- 위임받은 기존 MERGE_HEAD: `62ce57b4242c2ed39bc620177dd0ca76925fd972` (E4-L4r)
- 완료 커밋은 위 두 부모의 기존 no-commit 병합을 마무리한다. 추가 merge 명령은 실행하지 않았다. 최종 HEAD는 최종 응답과 `git rev-parse HEAD`로 확인한다.
- 실제 빌더 모델: `builder: codex-gpt-6.1-sol`; 이 보고서는 독립 verifier 결과가 아니다.
- OpenAI 실제 호출 **0**. 환경은 mock / NEUMANN_LIVE_TESTS=0 / LIVE_LLM_OK unset. 키를 복원하지 않았고 .env를 열지 않았다.
- API 변경은 PM이 명시 허용한 `main.py` samples router 등록 1줄뿐이다. models/contracts/config/export/signing/HANDOFF/QUEUE/decisions는 수정하지 않았다.
- 공개 원본·옛 neumann 폴더·실서비스 포트 8010/8020/8099에 접근하지 않았다. 모든 검사와 자체 서버는 shared two-slot wrapper를 통해 실행했다.

## 변경

- index.html 충돌은 L3m 근거 drawer의 Escape/Tab 포커스 처리를 보존하고 L4r `NeumannUI` 연결 훅을 함께 유지하여 해결했다. 기존 자동 staged L4r 보고서·그림·검사는 보존했다.
- `neumann.api.samples`를 동적 `templates/{id}`보다 앞에 등록했다. 공개 갤러리는 서버의 public_ok 필터·분야·license·관문 표시를 사용하며, fixture/mock 저장 결과를 실제 분석 배지로 내세우지 않는다.
- 기본 `REV.dev=false`. 합성 화면은 명시적인 `?mock=final`에서만 사용한다. 실제 revise 실패를 합성 성공으로 바꾸지 않는다.
- 실제 package 요청에 revision, revision_decisions, revised_plan, revision_sig를 추가했다. 명시 mock 모드 payload는 실제 export에 섞지 않는다.
- 출처 표시는 서버 HMAC 무결성과 생성 방식을 분리한다. 서명된 mock 수정 권고는 화면·MD·인쇄에 `생성: 모의(mock)`로 표시한다. 미검증 제출·브라우저 보존값의 경고를 유지했다.
- 새 `test_ui_connect.py`는 실제 production app, 실제 pipeline, 실제 서버 서명, 실제 HTTP와 브라우저 다운로드를 사용한다. browser route interception, 가짜 최종 API 응답, signing/pipeline monkeypatch는 없다.
- 증거 backend는 기존 지원 설정으로 켠 **명시적 fixture corpus**이고 LLM 생성은 **mock**이다. 실제 공개 논문 근거·실제 LLM 품질을 검증했다고 주장하지 않는다. 제품에 Codex 오프라인 생성 분석 결과를 저장하지 않았다.

## 완료 기준 측정

| 기준 | 실제 출력 / 확인 |
|---|---|
| public sample routing / flags | GET /templates/samples 200, public_count=5, 비공개 항목 404, fixture_badges=0; /templates 기존 경로 200; battery 필터 1건·전체 5건 |
| 실제 분석 → 서버 결과 | POST /premortem/jobs 202 → GET /premortem/jobs/<id> 200; source=pipeline, 카드 4장, generation=[mock], export.signed=true |
| 실제 수정 권고 | POST /premortem/revise 200, origin=server_signed, revision_sig 존재, generation=mock, edits=2 |
| 직접 편집 → assemble | POST /premortem/revise/assemble 200, origin=server_signed, revised_plan_sig 존재, revised_by=researcher, 직접 수정 문장 유지 |
| MD / DOCX | MD에 직접 수정 및 HMAC 출처 표시 유지; 실제 DOCX 38,002 bytes, ZIP/XML 유효, python-docx 본문에 직접 수정 문장 유지 |
| 실제 ZIP export | POST /premortem/package 200; 파일 11개, revision.json·revised_plan.md 존재, 수정 문장 유지, 헤더·manifest result_origin=server_signed |
| 위조 서명 | 실제 HTTP로 모양만 흉내낸 서명 제출 → 200, origin=client_submitted_unverified, revision_sig 없음; 인증 성공으로 표시되지 않음 |
| 합성 UI 상세 | 편집 충돌·원문 유지·확인칩·키보드·포커스·보존·미확인 출처·가짜 생성자 표시·인쇄·MD/DOCX 검사 통과. 이 검사는 route stub을 쓰며 실제 API 연결 근거와 구분함 |
| 반응형 | 실제 수정본 390/616/768/1440px 가로 넘침 없음; 별도 L3m drawer/touch/포커스/반응형 검사 통과 |
| 브라우저 안정성 | page_errors=[], console_errors=[], failed_requests=[], external_requests=0, route_interceptions=0 (실제 HTTP 검사) |

서명 문자열·키는 보고서/metrics에 기록하지 않고 존재 여부와 origin만 기록했다. HMAC origin은 현재 서버 판정이며 별도 core authority 수정의 독립 검증을 대신하지 않는다.

## 명령과 출력

아래 명령은 위 작업트리에서 실행했다. 모든 python은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`이며, wrapper는 `C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py`이다. 각 실행 전 process-local mock / NEUMANN_LIVE_TESTS=0 / NEUMANN_UI_TESTS=1 / PYTHONPATH=src;. / PYTHONUTF8=1을 주고 OPENAI_API_KEY와 NEUMANN_LIVE_LLM_OK를 제거했다. 테스트 임시 경로는 `out/codex/E4-L4r-UI-connect`이며 루트 TEMP는 쓰지 않았다.

```powershell
& C:/Users/User/.venvs/neumann/Scripts/python.exe C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py -- C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e4/test_ui_connect.py tests/e4/test_revise_ui.py tests/e4/test_revise_static.py tests/e4/test_samples.py tests/e4/test_templates.py tests/e4/test_export_ui.py -k 'not test_export_ui_playwright' -q --tb=short -p no:cacheprovider --basetemp C:/Users/User/Desktop/project_neumann/out/codex/E4-L4r-UI-connect/pytest-06
# Target test slot 1/2 acquired
# 87 passed, 3 skipped, 1 deselected in 38.68s

# NEUMANN_UI_PORT=8172; NEUMANN_UI_SHOTS_OUT=.../responsive-shots
& C:/Users/User/.venvs/neumann/Scripts/python.exe C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py -- C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e4/test_responsive.py -q --tb=short -p no:cacheprovider --basetemp C:/Users/User/Desktop/project_neumann/out/codex/E4-L4r-UI-connect/pytest-07
# Target test slot 1/2 acquired
# 1 passed in 40.68s

git diff --check
# 출력 없음 (exit 0)
```

3 skipped는 samples 문서 경로의 PDF/DOCX/HWPX symlink 탈출 검사로, Windows symlink 권한이 없어 기존 검사에서 건너뛰었다. 이 부분은 검증하지 못했다. 이전 route-intercept export UI 하나는 실제 package 다운로드 검사가 대체하여 deselect했다. 검사 약화나 항상 통과 검사로 바꾸지 않았다.

실패와 수정: 초기 대상 검사에서 embedded mock block의 최신 contract 불일치와 package payload 문자열 가정이 실패했다. mock block을 기존 생성기로 갱신하고 package schema 검사를 확장했다. 이어 합성 revise 검사는 가변 contract example의 근거 순서·편집 2개·자리표시 수를 고정 3-edit 시나리오로 간주하여 실패했다. 별도 고정 합성 fixture로 채택/수정/기각·확인칩·충돌 검사를 유지하고 실제 API의 현재 2-edit 계약은 새 실제 HTTP 검사로 검증했다. 마지막 전체 대상 실행은 위 결과로 통과했다.

## 증거와 인계

실제 HTTP metrics: `C:/Users/User/Desktop/project_neumann/out/codex/E4-L4r-UI-connect/evidence/UI-connect.metrics.json`.
실제 화면: 같은 디렉터리 `UI-connect-report.png`, `UI-connect-print.png` (육안 확인: 직접 수정·초안·HMAC 출처와 mock 표시).
합성 검사 화면: `.../E4-L4r-UI-connect/synthetic-shots`; L3m 반응형 화면: `.../responsive-shots`. CLI 실행 로그·runtime fixture·다운로드 캐시는 커밋하지 않았다.

통합 체크리스트: 현재 후보의 E4-L2f → E3-L2r → E4-L3m → L4r 순서를 유지한다. main을 병합하지 않는다. 별도 core authority 수정 후 실제 HTTP 정상/위조 서명·assemble·package를 동일 명령으로 다시 확인한다. server origin은 서버 응답에 따라 표시하며 UI가 HMAC을 자체 검증한다고 주장하지 않는다. gpt-6-sol 독립 UI 검증과 PM 전체 verify 후 PM이 병합/배포를 결정한다.

builder: codex-gpt-6.1-sol
