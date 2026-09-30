# E4-L2a 검증 보고서 (검증자: Claude Sonnet 5.5)

- 대상: 브랜치 `task/E4-L2a` (HEAD `ea53a8a`, 커밋 4개), worktree `.claude/worktrees/agent-a3f4faa9771cfe939`, 빌더 claude-opus-5.5
- 방법: 빌더 보고서를 믿지 않고 완료 기준을 직접 실행했다. ZIP은 fixture 결과로 `%TEMP%\e4l2a_verify_fixture.zip`에 만들어 원본 fixture(`reviews.jsonl`·`decisions.jsonl`)를 직접 잘라 대조했다. 조작 입력·변이 실험은 스크래치 폴더(`scratchpad\v`)의 복사본에서만 했고 worktree 코드와 git은 건드리지 않았다.
- 환경: Windows Python `neumann` venv, `PYTHONPATH="src;."`, `NEUMANN_RAW_DIR`·`NEUMANN_DATA_DIR` 설정.

## 결론

**PASS.** 병합을 막는 결함은 없다. 비차단 권고 5건은 맨 아래에 있다.

## 항목별 결과

| # | 확인 항목 | 실행한 명령 / 방법 | 실제 결과 | 판정 |
|---|---|---|---|---|
| 1a | 완료 기준 1: export 테스트 | `python -m pytest tests/e4 -q -k export` | **27 passed** in 0.74s (`-k export`가 파일 이름 `test_export.py`로 27건 전부 선택) | 통과 |
| 1b | 완료 기준 3: verify | `python scripts/verify.py` (브랜치 worktree) | 116 passed, 보안 77개 파일, 계약 2개, `verify 통과`. (빌더 보고서의 "114 passed, 2 skipped"와 skip 수가 다른 것은 내가 `NEUMANN_RAW_DIR` 등을 설정해 원본 필요 테스트가 돈 차이) | 통과 |
| 1c | 병합 상태 시뮬레이션 | 현재 main(`8d12572`, E4-L0 병합 포함)을 `git archive`로 스크래치에 풀고 export.py·test_export.py만 덮어 `pytest tests` | **185 passed**. `git merge-tree`도 충돌 없음(트리 객체만 생성, ref·작업 트리 변경 없음). `neumann.api.main.app`에 `app.include_router(router)`를 붙이면 경로 `['/health','/premortem','/premortem/package','/premortem/view']`, fixture로 POST → 200 `application/zip`, 카드 2, 9파일 | 통과 |
| 2a | ZIP 9파일 이름·순서 | fixture 결과로 `build_package(res, created_at=…)` → `%TEMP%`에 저장, `zipfile`로 열기 | `testzip()` None. 순서: README.md, manifest.json, risk_cards.json, evidence_pack.json, similar_works.csv, plan_annotated.md, neumann_report.md, ai_context.md, decision_log.json. 스펙 나열 순서와 같음. 항목 시각은 결과의 `generated_at`으로 고정, 권한 0o644 | 통과 |
| 2b | manifest sha256·크기 | ZIP에서 꺼낸 실제 바이트로 sha256·길이를 직접 계산해 manifest 항목과 비교 | manifest는 나머지 8파일(자기 자신 제외, README에 명시) 전부 sha256·bytes 일치. `cards_by_generator {'astra':0,'rule':0,'mock':2}`, `created_at`, `schema_version "1"` 있음 | 통과 |
| 2c | 인용문 = 원문 조각(글자 그대로) | `evidence_pack.json`의 8건을 fixture jsonl 원문에서 `[start:end]`로 직접 잘라 `text`·`text_sha256`·`source_sha256`과 비교 | **8건 전부 일치, 불일치 0**. 리포트의 `>` 블록 인용과 `ai_context.md`의 JSON 문자열 인용도 8건 전부 글자 그대로 | 통과 |
| 2d | 여러 줄 인용 | fixture 인용은 전부 한 줄이라, 줄바꿈·연속 빈 줄·앞뒤 공백이 든 발췌를 직접 만들어 넣음 | evidence_pack의 text·sha 그대로. 리포트의 `>` 블록을 되짜면 원문과 동일(`'First line…\n\n  Indented…  \nLast line.'`). ai_context의 JSON 문자열도 동일. 빈 줄 접기(`_md_bytes`)가 인용 블록을 망가뜨리지 않음 | 통과 |
| 2e | README 첫 20줄 | 실제 출력 확인 | 빌더 보고서에 붙인 것과 같음. 생성 방식 줄 "astra(LLM) 0장 · rule(규칙 비상 경로) 0장 · mock(테스트용 가짜) 2장" | 통과 |
| 3a | 강등 표기 | 단계 `extract`를 degraded(`fallback:rule_tagger`)로, 카드 1장 rule·1장 astra로 바꿔 생성 | README·리포트·ai_context 모두 `degraded`, 강등 단계 표(`extract \| degraded \| fallback:rule_tagger \| astra timeout -> rule tagger`), 카드별 "C1 … rule(규칙 비상 경로)", "C2 … astra(LLM), 모델 gpt-6-astra". manifest `not_ok_stages`·`cards_by_generator` 일치 | 통과 |
| 3b | rule을 LLM이라 쓰지 않는가 | 카드 2장 모두 rule로 만들어 세 문서에서 LLM·astra·gpt·규칙 문구 전수 확인 | rule은 항상 "규칙(비상 경로…). LLM 결과가 아니다"·"rule(규칙 비상 경로)"로 표기, astra 0장, `risk_cards.json`의 generator도 `rule`. rule 카드 줄에 astra·LLM 문구 없음. ai_context에도 "generator=rule 카드는 규칙 결과이고 LLM 판단이 아니다" 명시 | 통과 |
| 3c | 카드 0장 | (i) 사유 없음, (ii) status=error+단계 error+notices, (iii) status=degraded인데 단계 기록 없음 | 셋 다 죽지 않고 9파일 생성. (i)은 "결과에 따로 적힌 사유는 없다"(사유를 지어내지 않음), (ii)는 "분석이 오류로 끝났다(status=error)", 단계 사유, notices를 옮김. (iii)은 "단계 기록 없이 상태만 강등됨". risk_cards·evidence_pack 카드·CSV 데이터 행 모두 비어 있고 decision_log `decisions: []` | 통과 |
| 4a | 계획서 본문 마스킹(plan_text) | `result.plan=None`, `plan_text`에 이메일 2종(`kim.researcher@snu.ac.kr`, `PI+lab@Uni-Bonn.de`)·ORCID를 붙여 생성 | 9파일 전체에서 원문 노출 0건. `plan_annotated.md`에 `[EMAIL]`·`[ORCID]`. CRLF 입력은 LF로 정규화 | 통과 |
| 4b | 마스킹 안 된 `result.plan` | `PlanDocument.from_text(..., redact=False)`로 만든 계획서를 결과에 넣음 | 9파일 전체에서 노출 0건(출력 단계에서 `redact_pii`를 한 번 더 건다) | 통과 |
| 4c | 환경변수·비밀값 | `OPENAI_API_KEY`·솔트를 가짜 값으로 설정하고 생성(테스트 `test_package_contains_no_env_values`), 변이로 환경변수를 CSV에 덧붙여 봄 | 패키지에 값 없음. 변이는 테스트가 잡음. 코드·보고서·테스트에 실제 키 패턴 없음(테스트의 가짜 값만) | 통과 |
| 5 | 결정성 | `PYTHONHASHSEED` 0·1·4242·7로 4개 프로세스에서 fixture와 변형(체크리스트 id 섞임, axis_scores 순서 다름, 결정 로그 포함)을 `created_at` 고정으로 생성해 ZIP sha256 비교 | fixture ZIP sha256 `ff42077b…4a` 네 프로세스에서 동일, 변형 `aa31062f…f0`도 동일. 파일별 해시도 동일. 기본값(지금)으로 두 번 만들면 manifest 밖 8파일은 동일(테스트로 확인). 입력이 바뀌면 파일이 바뀜(`test_different_input_changes_output`) | 통과 |
| 6a | 파이프라인 없음 → 가짜 카드 없음 | `neumann.pipeline`이 실제로 없는 상태에서 `POST /premortem/package {"plan_text": …}` (그리고 `sys.modules`에 None을 넣은 경우) | 200, `X-Neumann-Status: error`, `X-Neumann-Cards: 0`. risk_cards `[]`·evidence 카드 `[]`·CSV 데이터 행 0, manifest 단계 `pipeline error — 분석 파이프라인 미연결(ModuleNotFoundError)`, `impl fallback:pipeline_unavailable`, 생성 방식 astra·rule·mock 전부 0장. README·리포트가 사유를 쓰고, 계획서 본문(마스킹)과 줄 번호는 담음. 입력의 이메일 노출 0 | 통과 |
| 6b | 파이프라인 예외 | `run_premortem`이 `RuntimeError("sk-SECRET-…")`를 던지게 함 | 200·status error·카드 0. README에는 예외 **클래스 이름**만(`분석 파이프라인 오류(RuntimeError)`), 메시지 본문(비밀 흉내 문자열) 미노출 | 통과 |
| 6c | 파이프라인 정상 | 가짜 `run_premortem`이 fixture 결과(객체 또는 dict)를 돌려줌 | 200, 카드 2. 결과에 `plan`이 있으면 `plan_text`는 쓰지 않는다고 manifest `plan_source`에 표기 | 통과 |
| 6d | 잘못된 입력 | `{}`·JSON 아님·리스트·공백 plan_text·1,000,001자 plan_text·존재하지 않는 근거 id·모르는 card_id 결정·신원 키(`reviewer_email`)가 든 결정 | 모두 422. 500 없음 | 통과 |
| 7 | 소유 경로 밖 변경 | `git diff main...task/E4-L2a --stat` / `--name-status` | 추가 3개뿐: `docs/reports/E4-L2a.md`, `src/neumann/api/export.py`, `tests/e4/test_export.py`(+1576줄, 삭제·수정 0). `contracts/`·`models.py`·`api/main.py`·fixtures·데이터·비밀 파일 변경 0. 브랜치의 `main` 병합 커밋(`43411f7`)은 지시문 추가분만 들여옴 | 통과 |
| 8 | 테스트가 항상 통과하는가 | 스크래치 복사본에 결함 15종을 하나씩 주입해 `pytest tests/e4 -k export` | 잡힘 13종: rule을 LLM으로 서술(긴 라벨·짧은 라벨 2종), manifest sha 오류·항목 누락, 인용문 가공(evidence·리포트·ai_context 3종), 비결정(README에 now), 카드 0장 사유 삭제, 강등 표 삭제, 파이프라인 없음에 status=ok(가짜 성공), 파일 순서 변경, 환경변수 누출. 살아남은 2종은 **동치 변이**: 마스킹은 `from_text(redact)`·`plan_annotated`·줄 인용 3겹이라 한 겹만 빼면 출력이 같음. 셋을 동시에 빼면 `test_plan_text_is_masked_when_result_has_no_plan`이 실패. 결함 없는 복사본은 27 passed | 통과 |
| 9 | worktree 청결 | `git status --short --ignored` | 내가 verify.py로 만든 `.pytest_cache/`를 지웠고 그 뒤 변경·무시 파일 0. ZIP은 `%TEMP%`에만 있음 | 통과 |

## 비차단 권고 (병합 뒤 또는 다음 과제에서)

1. **`expected_review`만 마스킹 없이 리포트에 덤프됨.** `neumann_report.md`의 "예상 심사평" 절은 `json.dumps(r.expected_review)`를 그대로 넣는다. 체크리스트·카드 제목·알림·결정 메모 등 다른 마크다운 면은 `_one_line`으로 이메일·ORCID를 가리는데 이 절만 빠졌다(조작 입력에서 이메일·ORCID가 리포트에 그대로 남는 것 확인). E3는 마스킹된 계획서에서 만들므로 실제 노출 가능성은 낮지만 `redact_pii`를 한 번 거는 편이 일관된다. 같은 이유로 `risk_cards.json`(계약 덤프 그대로)·`evidence_pack.json`의 카드 제목·CSV 제목·manifest 단계 사유는 upstream 값이 마스킹돼 있다고 가정한다. 스펙 범위("계획서 본문은 마스킹된 줄만")는 충족한다.
2. **파이프라인이 엉뚱한 값을 돌려주면 500.** `_run_pipeline`이 `run_premortem` 호출만 try로 감싸고 `PremortemResult.model_validate(out)`은 밖이라, 파이프라인이 `None`이나 계약 위반 dict를 돌려주면 `ValidationError`가 그대로 올라가 500이 된다(확인: None·`{"junk":1}` → 500). 다른 실패는 정직한 error 패키지가 되므로 검증도 같은 try에 넣으면 일관된다.
3. **plan_text만 보낸 경우(파이프라인 폴백)는 결정적이지 않다.** 결과 없이 만든 error 결과는 `session_id`(uuid)와 `generated_at`(지금)이 매번 달라 같은 계획서를 두 번 보내면 README·리포트가 다르다. 스펙의 결정성("같은 입력 → 같은 파일")은 결과를 넣은 경로에 적용되고 그쪽은 통과하므로 결함은 아니다. 다만 폴백 결과의 `README`가 "분석 시각"이라며 패키지 호출 시각을 적는다(분석은 일어나지 않았다). 폴백에서는 이 표기를 "생성 시각"으로 바꾸거나 생략하면 정직하다.
4. **검사 공백 2곳.** (a) fixture 인용이 전부 한 줄이라 여러 줄 인용 경로는 테스트가 없다(내가 수동으로 확인해 이상 없음). (b) 마스킹 안 된 `result.plan`(4b) 경로 테스트가 없다. 둘 다 코드는 맞게 동작한다.
5. **표기 사소한 점.** notices가 있고 카드가 0장이면 같은 문장이 README의 "이유"와 "결과 알림"에 두 번 나온다. `run_premortem(plan_text)`의 호출 형태(위치 인자 하나)는 아직 없는 E3 모듈에 대한 추측이므로 E3 병합 때 `neumann.pipeline` 실제 시그니처와 맞는지 통합 확인이 필요하다.

## 참고(결함 아님)

- 브랜치는 E5-L0·E4-L0 병합 전의 main에서 갈라졌다. 겹치는 파일이 없어 병합은 충돌 없고, 현재 main과 합친 스크래치에서 전체 185 passed였다. 병합 뒤 `python scripts/verify.py`는 한 번 더 돌린다.
- `main.py` 연결은 PM 몫이다. 빌더 보고서의 두 줄(`from neumann.api.export import router as export_router` / `app.include_router(export_router)`)로 실제 `neumann.api.main.app`에 붙여 200·ZIP 9파일이 나오는 것까지 스크래치에서 확인했다.
- `git merge-tree --write-tree`는 객체 저장소에 트리 객체 하나를 남긴다(ref·작업 트리 변경 없음).
