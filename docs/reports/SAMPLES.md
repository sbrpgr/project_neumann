# SAMPLES 첫 화면 샘플 보고서

2026-10-01 KST · 작업 브랜치 `codex/samples` · 빌더 `codex-gpt-6.1-sol`

세 분야의 팀 작성 연구계획서 3편을 선정하고 PDF·DOCX·HWPX 9개를 만들었다. 첫 화면에서 세 편을 펼쳐 보여 주며, 소개에는 연구 목적만 적었다. 원문 입력과 문서 다운로드를 현재 서버 라우트로 확인했다. 이번 작업의 제품 LLM 호출은 0회다.

다만 과거 라이브 실행 전체의 오류 0건 조건을 세 편 모두 충족했다고 보고할 수는 없다. 전해액은 전체 검사 실패 0건이고, 단백질·대기 유체는 카드와 인용 검사가 좋지만 과거 체크리스트·화면 검사 실패가 있었다. 아래에 그대로 기록한다. 현재 첫 화면·문서 경로의 오류 0건과 과거 분석 전체 오류를 구분한다.

## 선정 근거

읽은 자료는 현재 프로젝트의 `data/eval/*.jsonl`, `data/eval/neumann_runs/real__*.json`, `data/precomputed/manifest.json`, `docs/reports/E5-L1e2e.verify.md`와 `.claude/worktrees/s2-E5-L1e2e/docs/reports/E5-L1e2e_live_summary.json`, 같은 폴더의 `E5-L1e2e_live/*.result.json`이다. 다른 worktree는 읽기만 했다. 옛 프로젝트와 기획서 원문은 사용하지 않았다.

`data/precomputed` 3건은 `source=fixture`, degraded, 카드 2/0/0장이라 좋은 실제 실행의 증거로 쓰지 않았다. 백테스트에는 카드 4~5장과 높은 인용 연결률의 사례도 있으나, 현재 레지스트리에서 본문 공개가 승인되지 않은 타인 논문 복원본이고 일부는 짧은 초록이다. 첫 화면에는 공개 가능한 팀 작성 계획서를 선택했다. 이는 시연용 선별이며 성능 추정 표본이 아니다.

| 분야 | 선정 계획서 / ID | 결과 시각 KST | 카드 | 기록된 인용 검증 | 카드 의미 검증 | 오류 기록과 선정 판단 |
|---|---|---|---:|---|---|---|
| 소재·화학·분자 | 전해액 이온전도도 예측 GNN / `example-battery` | 09-30 21:58:17 | 5 | 17/17, 연결률 1.0 | 맞음 5, 약함 0, 불일치 0 | 결과 ok, 단계 10/10 ok, 과거 e2e 실패 0. 세 편 중 가장 확실한 시연 입력 |
| 단백질·생물·신약 | 단백질-리간드 결합 친화도 예측 / `example-binding` | 09-30 22:01:05 | 7 | 27/27, 연결률 1.0 | 맞음 5, 약함 2, 불일치 0 | 결과 ok, 단계 10/10 ok. 과거 e2e 실패 2: 화면 체크리스트 C3 근거 번호 없음, 404 콘솔 오류 1건. 분야 다양성을 위한 조건부 선정 |
| 물리·PDE·기후 | 신경 연산자 기반 대기 유체 대리모델 / `example-operator` | 09-30 22:03:53 | 7 | 25/25, 연결률 1.0 | 맞음 7, 약함 0, 불일치 0 | 결과 ok, 단계 10/10 ok. 과거 e2e 실패 3: 화면 C6 근거 번호 없음, 404 콘솔 오류 1건, API 체크리스트 C7 evidence 없음. 카드 결과가 좋은 조건부 선정 |

인용 검증은 저장된 `verification.quotes_verified/quotes_total`이고 의미 검증은 저장된 `verification.semantic.counts`이다. 원문 저장소와 과학적 정확도를 새로 독립 판정한 값이 아니다. 요약의 화면 실행과 저장된 `/premortem` 실행은 별도 요청일 수 있으므로 저장된 결과 파일의 수를 표의 기준으로 삼았다.

본문은 이전 라이브 결과의 `plan.lines`와 일치함을 확인했고 변경하지 않았다. 세 파일의 원문 해시, 결과 해시, 의미 검증 수치, 과거 실패 목록은 `src/neumann/api/templates/samples/selection.json`에 남겼다. 결과 원본 전체를 공개 저장소로 옮기지 않았고, 레지스트리의 선정 정보는 공개 API에서 제외된다. 사람이 독립 확인했다고 주장하지 않기 위해 `checked_by_human=false`, 전체 점수 `score=null`을 유지했다.

## 배치와 첫 화면

- 본문: `src/neumann/api/templates/samples/{electrolyte_gnn,protein_ligand_affinity,neural_operator_weather}.md`.
- 문서: 같은 경로의 `docs/` 아래 세 본문의 PDF·DOCX·HWPX, 총 9개.
- 기존 `samples.json` 형식과 ID를 유지하며 서버 문서 허용 디렉터리를 `templates/samples/docs`로 변경했다. 경로·심볼릭 링크 이탈 방어는 유지했다.
- 분량 미달·범위 밖 거절용 2편은 `retired`로 바꿔 첫 화면에서 제외했다. 타인 논문 후보 12편은 기존 비공개 상태를 유지했다.
- 갤러리를 기본으로 펼치고 실제 샘플이 있는 세부 분야 3개만 선택기에 보인다. 분야·연구 목적 한 줄과 선택·다운로드 조작만 표시한다. 약점 목록, 라이선스 내부 설명, 저장 결과가 없다는 개발 문구는 첫 화면 카드에서 제거했다.
- 기존 sticky 전송 고지가 늘어난 샘플 영역을 덮는 문제를 렌더링에서 확인했다. 최신 `out/dashboard/ui_design_spec.md`에 따라 실행 버튼 아래의 일반 흐름으로 옮겨 제목을 가리지 않도록 했다. 전송 고지의 사실 문구는 유지했다.
- 결과를 새로 생성하거나 mock을 좋은 라이브 결과로 포장하지 않았다. mock·fixture 사전 계산본에 즉시 결과 배지를 주지 않는 기존 게이트도 유지된다.

## 원문 복원 측정

명령은 모두 `C:/Users/User/.venvs/neumann/Scripts/python.exe`로 실행했다. 테스트 전에 키·솔트·라이브 허용 플래그를 프로세스 환경에서 제거하고 provider를 mock으로 정했다. 설정의 env_file은 None으로 닫았다. 값 출력·값 단언, 실제 서비스 접속은 없었다.

```powershell
$env:NEUMANN_LLM_PROVIDER='mock'
$env:PYTHONPATH='src;.'
& C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/check_sample_documents.py --extractor-root C:/Users/User/Desktop/project_neumann --output out/sample-build/main-extraction.json
```

main 추출기 확인 시점의 HEAD: `ac9723ae60438b9f5df5350c956a320be66a2079`. `src/neumann/api/upload.py` SHA-256: `f682c06992cfd0eac472c569eb32c9613a3bd1c22e4af0e55694ff4568f1b7d5`. main 파일은 수정하지 않았다. HTTP 상태 표기의 200은 직접 추출 성공을 나타내며, 별도 관련 테스트에서 실제 업로드 HTTP 경로도 검사했다.

| 계획서 | PDF | DOCX | HWPX |
|---|---|---|---|
| 전해액 | 1쪽, 정리 후 원문 정확 일치, 경고 0 | 정리 후 원문 정확 일치, 경고 0 | main 추출기 415 |
| 단백질 결합 | 1쪽, 비공백 원문 문자 100% 일치, 경고 0 | 정리 후 원문 정확 일치, 경고 0 | main 추출기 415 |
| 대기 유체 | 1쪽, 비공백 원문 문자 100% 일치, 경고 0 | 정리 후 원문 정확 일치, 경고 0 | main 추출기 415 |

PDF의 단백질·대기 유체는 조판으로 추가된 줄바꿈 4자씩이 있어 원문의 줄 번호·plan_id까지 같다고 주장하지 않는다. 문자 복원 비교는 NFC 후 공백류를 제거해 했고, 단어·숫자·문장부호 손실은 0이다. DOCX는 main의 정리 규칙까지 적용한 문자열이 정확히 같다. HWPX는 ZIP/XML 본문과 Preview 원문을 검증했지만 main에서 지원되지 않는다. HWPX-UPLOAD가 추출기 지원을 담당하며, 한컴 앱 렌더링은 하지 않았다.

PDF 3쪽은 번들 Poppler로 PNG 렌더링 후 모두 직접 확인했다. 잘림·겹침·누락 글리프 없음. DOCX는 python-docx 재읽기와 업로드 복원을 확인했지만, 아래 렌더러 실패로 Word/LibreOffice의 실제 페이지 시각 검증은 미완료다.

```text
render_docx.py electrolyte_gnn.docx --output_dir out/sample-build/docx-render --emit_pdf
FileNotFoundError: LibreOffice soffice.exe was not found on PATH
```

documents 스킬의 “Run render_docx.py to produce page-<N>.png images” 검증 단계가 이 환경에서 막혔다. PDF가 동일 원문과 유사 조판을 사용해도 DOCX 실제 렌더링을 대신한 검증이라고 주장하지 않는다.

## 관련 테스트

전체 `scripts/verify.py`는 실행하지 않았다.

```text
pytest tests/e4/test_samples.py tests/e4/test_curate_samples.py tests/e4/test_selected_sample_documents.py tests/e4/test_templates.py tests/e4/test_notice.py tests/e4/test_webui_upload.py -q
165 passed, 3 skipped in 7.50s

pytest tests/e4/test_selected_sample_documents.py -q
20 passed in 5.29s

NEUMANN_UI_TESTS=1 NEUMANN_UI_PORT=8162 pytest tests/e4/test_selected_sample_ui.py tests/e4/test_notice.py tests/e4/test_notice_ui.py -q
10 passed in 17.94s
```

최종 165건에는 실제 HTTP 업로드 회귀 9건이 포함된다. 문서 테스트 20건 실행에도 그 9건이 포함된다. 모든 파일의 내용 복원, 원문·선정 해시, 레지스트리 비공개 필드, 다운로드 본문, 경로 이탈 방어, 네트워크 금지, 세 분야, 정답 노출 금지, 거절 샘플 제외를 검사했다. skipped 3건은 Windows 심볼릭 링크 권한이 없어 실행되지 않은 기존 테스트다.

Playwright는 자체 headless Chromium과 81xx mock 서버만 사용했고 서버를 종료했다. 1440×960·390×960에서 세 편 선택, 분야 필터, 다운로드 링크 9개, 실행 가능 상태를 확인했다. 콘솔 오류·페이지 오류·외부 요청·실패 요청·분석 요청·가로 넘침 모두 0. 스크린샷은 `out/sample-build/ui/`에만 두었다. 과거 테스트가 생성한 기존 E4-S06 스크린샷 2개는 HEAD 원본으로 되돌려 이 과제에 넣지 않았다.

샘플 변경에 추가한 색 리터럴·새 글꼴·4단계 밖 글자 크기는 0이다. 이 브랜치의 기존 전체 화면에는 장식 서체, 로마 숫자 등 최신 규격 이전 요소가 남아 있어 전체 디자인 적합성을 주장하지 않는다. 최종 화면 재구성 작업과 병합 시 샘플 API·본문·다운로드를 다시 연결해야 한다. 입력 이외 분석~완성 단계는 이 과제에서 새로 실행하거나 검증하지 않았다.

## 못 한 것과 다음

1. 독립 검증은 하지 않았다. 하위 에이전트 위임 금지에 따라 PM이 별도 검증 세션을 배정해야 한다.
2. DOCX 실제 페이지 렌더링과 한컴 HWPX 앱 열기는 미검증이다. DOCX는 renderer가 있는 환경에서 시각 검증이 필요하다. HWPX의 main 415는 HWPX-UPLOAD에 전달한다.
3. 단백질·대기 유체의 과거 체크리스트·화면 오류를 이 작업에서 라이브 재실행으로 해결하지 않았다. 공개 시연 전 PM 승인 확인 테스트에서 수정 확정~최종 초안까지 전체 흐름을 확인해야 한다.
4. 커밋 시도에서 `fatal: Unable to create 'C:/Users/User/Desktop/project_neumann/.git/worktrees/samples/index.lock': Permission denied`가 발생했다. git add부터 실패했고 커밋·stash·main 병합·push는 없었다. 완료 변경과 이 보고서는 현재 worktree에 남아 있다. 권한이 적용된 PM 프로세스에서 이 브랜치 파일만 지정해 커밋해야 한다.

커밋 제목: `[SAMPLES] Curate three field examples and add upload documents`.
검증 결과와 `builder: codex-gpt-6.1-sol`을 커밋 본문에 남긴다. 전체 verify는 PM 병합 시 수행한다.
