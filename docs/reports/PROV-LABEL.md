# PROV-LABEL — 검색어·의미검증 실제 출처 표기

- 작업 브랜치: `codex/prov-label`.
- 빌더: `codex-gpt-6.1-sol`. 하위 에이전트·실제 제품 LLM 호출 없음.
- 판정: LS-2·LS-3 수정 및 관련 mock 회귀·headless 화면 검사 통과. Git 스테이징·커밋은 실제 파일 권한 거부로 미완료. 독립 모델 검증과 main 병합은 PM에게 넘긴다.

## 변경

1. **LS-2**: `pipeline.run_premortem`의 검색어 출처는 목록의 존재가 아니라 `QueryPlan.generator`를 따른다. `astra → llm`, `mock → mock`, `rule → rule`; 검색어가 비어 검색 단계에서 규칙으로 채우면 `rule`이다. 실패 후 이미 채워진 규칙 검색어에도 규칙 대체 알림을 남긴다.
2. **LS-3**: `validate_cards`는 최종 카드·행동의 `judge`를 집계한다. 성공한 `astra`/`mock` 판정이 0이면 외피 `generator=rule`, `model=null`; 모든 판정이 같은 생성자면 그 생성자; 성공 판정과 규칙·미검증이 섞이면 `generator=mixed`. `generators`에 판정별 출처 수(`astra`, `mock`, `rule`, `none`)를 남긴다. 미검증은 여전히 `judge=none`이며 의미 판정을 규칙으로 만들지 않는다.
3. 의미검증의 규칙·혼합 출처를 기존 `notices`에 추가한다. UI는 `_status.notices`에서 이를 표시한다. `_status.search.queries_source`와 검색어 규칙 대체 표시도 기존 경로로 반영된다. `_status.generator_labels`는 카드의 실제 생성 방식만 집계하므로 실패한 검증의 요청 모델을 카드 생성자로 표시하지 않는다.

## 계약

계약 파일·`models.py` 변경 **0개**. `PremortemResult.verification`은 `dict[str, Any]`, JSON schema의 `verification`은 `additionalProperties: true`다. 의미검증 외피의 `mixed`와 판정 수 객체는 이 기존 확장 범위에서 기록한다. 카드의 `Generator` enum(`astra/rule/mock`)과 개별 판정의 `judge`는 유지했다. 수정 결과를 원래 분석 계약·UI 계약·Pydantic 모델로 다시 검사했다.

## 완료 기준별 검증

공통 실행 환경은 `PYTHONPATH=src;.`, `NEUMANN_LLM_PROVIDER=mock`. 실행 프로세스에서 `OPENAI_API_KEY`, `NEUMANN_PSEUDONYM_SALT`, 실제 호출·라이브 테스트 플래그를 제거했다. 설정 로더의 `.env` 읽기를 비활성화했다. 환경변수 값을 출력하거나 단언하는 테스트를 추가하지 않았다.

| 기준 | 명령·방법 | 실제 결과 |
|---|---|---|
| 공급자 없는 red → green | `C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest -q tests/e3/test_prov_label.py --tb=short` | 수정 전 **17 failed, 2 passed in 0.70s**; 수정 후 **19 passed in 0.88s** |
| LS-2 실제 출처 | 실패한 MockProvider 검색어 생성, 정상 mock, 호출 없는 LLM 메타데이터, 빈 검색어를 각각 실행 | `rule/mock/llm/rule`; 규칙 결과의 목록은 비어 있지 않아도 `rule`; UI 검색 표시와 분석 계약 통과 |
| LS-3 전부 실패 | 공급자 없는 콜백의 `None`, 예외, 잘못된 응답 모양, 빈 카드 응답을 astra/mock 메타데이터로 검사 | 규칙·미검증 개별 판정 유지, 외피 `rule`, 모델 `null`, `degraded` |
| LS-3 부분·전체 성공 | 2개 묶음 중 1개 실패, 전체 성공, 카드 규칙 상한+행동 성공, 콜백 없음·카드 0장 | 일부 성공은 `mixed`; 전체 성공은 실제 astra/mock; 카드·행동을 함께 집계; 0장도 LLM 생성 주장 없음 |
| 기존 기능 회귀 | 아래 관련 테스트 명령 | **276 passed, 4 skipped in 4.92s** |
| 화면 | `NEUMANN_PROV_LABEL_UI=1`로 `C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest -q tests/e3/test_prov_label_ui.py --tb=short` | **2 passed in 17.69s**; 1440·390px에서 규칙·혼합 4가지 렌더 확인, pageerror 0, 카드 배지와 `_status.generator_labels` 일치 |
| 서버 정리 | 사용 가능한 8180~8199 포트에서 자체 mock 서버 실행, finally 종료 및 소켓 닫힘 검사 | 통과. 예약 포트 8020·8099·8171에 시험 서버를 띄우지 않음 |
| diff | `git diff --check` | 출력 없음, exit 0 |

관련 테스트 명령:

```powershell
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest -q tests/e3/test_prov_label.py tests/e3/test_prov_label_ui.py tests/e3/test_validate_semantic.py tests/e3/test_pipeline.py tests/e3/test_pipeline_l1w.py tests/e3/test_pipeline_l1w_llm.py tests/e3/test_pipeline_l1w_cache.py tests/e3/test_short_input.py tests/e3/test_evidence_gate_l1e.py tests/e3/test_evidence_gate_view_l1e.py tests/e4/test_display_generator.py tests/e4/test_webui_gen_labels.py tests/e4/test_e4_view.py --tb=short
```

4개 skip은 opt-in 화면 검사 2개와 기존 선택적 검사 2개다. 이번 과제 화면 검사는 별도 opt-in 명령으로 실행해 2개 모두 통과했다. 화면 테스트는 실제 로그인 브라우저를 쓰지 않고 Playwright Chromium `headless=True`로만 실행했다. 제품 분석은 mock·fixture로 준비하고 HTTP 결과를 주입해 렌더했다. 화면 증거: `C:/Users/User/Desktop/project_neumann/data/final_test/prov_label/{rule,mixed}_{1440,390}.png` (비공개 data, 커밋 안 함).

초기 화면 검사는 렌더 후 서버 종료 직후의 소켓 확인에서 실패했다. Windows의 종료 지연을 고려해 최대 10초 동안 소켓 닫힘을 확인하도록 보완하고 위 2개 검사를 다시 통과했다. UI 소스·디자인 토큰은 수정하지 않았다. 디자인 규격 문서는 읽었으며 화면 확인 범위는 출처 알림·배지다.

## 못 한 것·다음

- 실제 OpenAI 호출·라이브 재시험·전체 `scripts/verify.py`는 지시대로 실행하지 않았다. 실제 서비스의 LS-1 키 설정 문제는 이 과제 범위 밖이다.
- 하위 에이전트 금지에 따라 독립 모델 검증은 수행하지 않았다. PM이 독립 검증 후 main에 병합해야 한다.
- 별도 폴백 기능을 만들거나 스펙에서 후퇴한 변경은 없다. 기존 폴백의 출처를 바로잡았다.
- Git 실행 제한: 지정한 5개 파일만 `git add -- src/neumann/pipeline.py src/neumann/analyze/validate.py tests/e3/test_prov_label.py tests/e3/test_prov_label_ui.py docs/reports/PROV-LABEL.md`로 스테이징하려 했으나 `fatal: Unable to create 'C:/Users/User/Desktop/project_neumann/.git/worktrees/prov-label/index.lock': Permission denied` (exit 128)로 실패했다. `.git` 쓰기 허용 안내와 실제 실행 권한이 일치하지 않는다. 따라서 스테이징·커밋·커밋 훅 검사는 실행 완료하지 못했다. 권한·훅 우회나 다른 worktree 수정은 하지 않았다.
- PM의 다음 작업: Git 쓰기 권한이 적용된 환경에서 위 5개 파일을 스테이징하고 `[PROV-LABEL]` 제목 및 실제 검증 결과·빌더 표기로 커밋한 뒤 독립 검증한다. 대시보드에는 검증 통과·커밋 권한 거부를 한 줄로 보고한다. main 병합·push는 하지 않았다.
