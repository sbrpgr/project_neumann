# E3-L1e 독립 재검증 — 고정 HEAD `4c47892`

- 검증자: `codex-gpt-6-sol/high`; 검증 대상: `task/E3-L1e`의 `4c47892f227293202195a06aadf29cb78075e3ad` (2026-10-01 KST).
- 시작과 보고서 작성 전 `git rev-parse HEAD`는 위 값, 보고서 작성 전 `git status --short` 출력은 없음. 제품 코드·테스트·계약은 수정하지 않았다. 이전 실패 기록은 저장소 루트의 `docs/reports/E3-L1e.codex.verify.md`에서 읽었다.
- 실제 OpenAI 호출 **0**. 지정한 이름의 프로세스 환경만 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_TESTS=0`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `PYTHONDONTWRITEBYTECODE=1`, `OPENBLAS_NUM_THREADS=1`, `PYTHONPATH='src;.'`, `PYTHONUTF8=1`로 설정하고 `NEUMANN_LIVE_LLM_OK`와 `OPENAI_API_KEY`를 제거했다. 시작 확인 출력: `provider_mock True live_ok_absent True api_key_absent True`. 실제 서비스와 8010·8020·8099는 건드리지 않았다. 브라우저 시험 서버는 검사 전 빈 포트 8165·8166에서 해당 검사만 시작하고 자기 프로세스만 정리했다.

## 완료 기준 판정

| 기준 | 판정 | 독립 확인 |
|---|---|---|
| 고정 HEAD·기존 작업 보존 | **PASS** | 시작·보고서 작성 전 HEAD 일치, 작업 트리 깨끗함. `git diff --check` 출력 없음. |
| 계약 인용과 원문 문자 오프셋 | **PASS-conditional** | fixture 원문에 대해 패키지의 9개 발췌 전부 `source[start:end] == text`, `text_sha256` 및 `source_sha256` 일치. 패키지는 원문을 다시 받지 않아 실제 외부 코퍼스 재대조 상태를 `not_reverified`로 표기하므로 그 범위의 실원문 검증은 이 판정에 포함되지 않는다. |
| 고아 발췌가 달린 심사평 문장 | **PASS** | 유효한 발췌를 결과 `evidence`에 추가하되 어느 카드에도 연결하지 않고 그 발췌만 인용한 문장을 주입했다. view 활성 문장에서 통째로 제외됐고 ZIP 9파일에서도 원문이 없었다. |
| 정상+무효 근거 혼합 심사평·체크리스트 | **PASS** | 정상 ID와 없는 ID를 한 문장·행동에 같이 넣었다. 정상 ID만 남겨 문장을 표시하지 않았으며, view는 심사평 2문장·체크리스트 1항목을 제외했다. 정상 심사평 1문장과 정상 체크리스트 4항목은 유지했다. |
| 심사평·체크리스트·결정 메모의 9파일 누출 방지 | **PASS** | 저장 모델을 계약 재검증해 생성 게이트 우회 입력으로 만들었다. 고아 문장, 혼합 문장, 혼합 행동, 그 행동의 결정 메모는 `README.md`, `manifest.json`, `risk_cards.json`, `evidence_pack.json`, `similar_works.csv`, `plan_annotated.md`, `neumann_report.md`, `ai_context.md`, `decision_log.json`의 모든 바이트에서 부재. 정상 문장·행동·결정 메모는 리포트/로그에 남았다. 원본 입력 모델은 불변이었다. |
| Markdown·AI 맥락·근거팩·manifest·ZIP 일관성 | **PASS** | 리포트와 AI 맥락에 제외 경고가 표시되고, `decision_log.json`은 제외 항목 ID/결정을 제거했다. manifest는 나머지 8파일의 크기·SHA-256 모두 일치, 결정 수 1과 발췌 수 9를 기록했다. ZIP의 정확한 9개 이름·순서·바이트가 `build_package_files`와 일치했다. |
| HTML 화면과 접힌 감사 목록 | **PASS** | 독립 반례의 `validate_ui_view == []`, 활성 심사평에는 정상 문장만, 체크리스트에는 근거 있는 행동만 있었다. 브라우저 회귀는 제외 안내, 기본 접힘, `제외됨` 라벨, 근거 번호, 콘솔 오류 0을 실제 DOM에서 확인했다. 감사 목록의 제외 문장은 분석 결과와 구별된다. |
| PDF 인쇄 | **PASS-conditional** | mock HTML 화면에서 브라우저 `page.pdf()`로 만든 6쪽 PDF의 추출 텍스트에 제외 안내 1개·2개가 각각 있고 폐기 행동·문장 원문은 없었다. PDF 페이지 시각 배치까지 검수한 것은 아니다. 제품의 PDF는 HTML의 `window.print()` 경로다. |
| MD·PDF·DOCX 입력 형식 | **PASS-conditional** | 같은 합성 계획서를 `/upload/plan`의 세 형식으로 보냈을 때 본문 문자열과 `PlanDocument.plan_id`가 일치했다. DOCX는 입력 형식이며 ZIP에 DOCX 파일은 없다. 이 확인은 세 형식의 입력 정규화에 한정한다. |
| 전체 병합 게이트 | **PASS-conditional** | 표적 회귀와 반례는 통과했다. PM 큐가 소유한 전체 `scripts/verify.py`는 지시대로 실행하지 않았으므로 병합 판정은 PM의 전체 결과가 필요하다. |

## 명령과 측정 출력

Python: `C:/Users/User/.venvs/neumann/Scripts/python.exe`. 모든 명령은 위 mock/offline 환경에서 실행했고 pytest에는 `-p no:cacheprovider` 및 `C:/Users/User/Desktop/project_neumann/out/codex/pytest/E3-L1e/` 아래의 전용 `--basetemp`를 줬다. 처음 표적 실행은 부모 임시 디렉터리가 없어 `185 passed, 1 skipped, 1 error` (`FileNotFoundError` at setup)였다. 해당 부모 디렉터리만 만든 뒤 재실행했다. 이 오류는 제품 assertion 실패가 아니다.

```text
python -m pytest tests/e3/test_evidence_gate_l1e.py tests/e3/test_evidence_gate_view_l1e.py tests/e3/test_gate.py tests/e3/test_checklist.py tests/e3/test_review.py tests/e3/test_validate_semantic.py tests/e4/test_e4_view.py tests/e4/test_view_panel.py tests/e4/test_export.py -q -p no:cacheprovider --basetemp=C:/Users/User/Desktop/project_neumann/out/codex/pytest/E3-L1e/reverify-targeted-2
186 passed, 1 skipped in 1.24s

NEUMANN_UI_TESTS=1 NEUMANN_UI_TESTS_PORT=8165 NEUMANN_UI_SHOTS_OUT=C:/Users/User/Desktop/project_neumann/out/codex/pytest/E3-L1e python -m pytest tests/e3/test_evidence_gate_view_l1e.py -k browser -q -p no:cacheprovider --basetemp=C:/Users/User/Desktop/project_neumann/out/codex/pytest/E3-L1e/reverify-browser
1 passed, 21 deselected in 16.97s

python -m pytest tests/e4/test_webui_upload.py -q -p no:cacheprovider --basetemp=C:/Users/User/Desktop/project_neumann/out/codex/pytest/E3-L1e/reverify-input-formats
19 passed in 2.00s
```

추가 반례는 PowerShell here-string을 `python -`에 전달해 실행했다. `load_fixtures().premortem_result`에 (1) 카드에 없는 fixture 발췌 1개, (2) 정상·고아·혼합 ID 심사평 3개, (3) 정상 행동 4개와 정상+`ghost_ex` 혼합 행동 1개, (4) 정상 행동과 제외 행동 각각의 결정 메모를 넣은 뒤 `PremortemResult.model_validate`로 저장 결과를 재구성했다. `build_ui_view(..., records=None)`, `build_package_files(..., created_at=2025-01-02 UTC)`, `build_package`를 직접 호출해 모든 활성 문장·행동, 9파일 원문 부재, 정상 항목 유지, 원문 오프셋·해시, manifest·ZIP 바이트, 원본 불변을 assertion으로 확인했다. 실행 출력:

```text
view {'active_review': ['INDEPENDENT_SUPPORTED_SENTENCE'], 'checklist_shown': 4, 'review_excluded': 2, 'checklist_view_excluded': 1}
package {'members': 9, 'manifest_entries': 8, 'source_offset_matches': 9, 'excluded_decisions': 1, 'input_unchanged': True, 'zip_bytes_match': True}
```

별도 `TestClient` 합성 형식 비교의 출력은 `format_equivalence {'formats': ['md', 'pdf', 'docx'], 'same_plan_text': True, 'same_plan_id': True, 'api_calls': 0}`이다. 여기서 `api_calls`는 실제 OpenAI 호출 수이고, 로컬 `/upload/plan` 요청은 3회다. PDF 인쇄는 Playwright mock 작업 응답으로 화면을 완성한 뒤 메모리의 `page.pdf()`를 `pypdf.PdfReader`로 추출해 검사했다. 출력: `pages: 6`, `bytes: 185397`, 제외 안내 2개 포함, 폐기 행동·문장 3개 원문 부재. `fitz`가 설치되지 않아 첫 시도는 import 오류였고, `pypdf`로 재실행했다. PDF 제목 문자열 하나는 추출 텍스트의 줄 나눔 때문에 연속 검색이 실패해 제목을 판정 기준에서 빼고 제외 안내·폐기 문구를 개별 검색했다.

## 남은 일

1. **보고서 커밋 차단:** `git add -- docs/reports/E3-L1e.codex.reverify.md` → `fatal: Unable to create 'C:/Users/User/Desktop/project_neumann/.git/worktrees/s2-E3-L1e/index.lock': Permission denied`. 샌드박스 밖 공용 Git 메타데이터 쓰기가 거부됐다. 우회·권한 상승·훅 비활성화 없이 중단했으며, 보고서 파일은 작업 트리에만 남고 스테이징·커밋되지 않았다. PM이 권한 있는 세션에서 지정 파일만 스테이징하고 훅을 켠 채 커밋해야 한다.
2. PM 직렬 큐에서 고정 코드에 대한 전체 `scripts/verify.py` 실행·결과 확인.
3. 실제 공개 코퍼스 원문 오프셋 대조가 필요하면 별도 원본 접근 승인·검증 절차로 수행. 이번 검증은 fixture 원문을 글자 단위로 대조했다.
4. PDF 인쇄의 페이지 배치 시각 검수는 별도다. 현재 확인은 PDF 추출 텍스트와 HTML DOM의 근거 무누출이다.

제품 수정 0, main 병합·push·tag 0, 실제 OpenAI 호출 0. 최종 판정은 **표적 기준 PASS, 전체 병합은 PM verify 대기(PASS-conditional)**다.
