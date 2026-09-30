# E4-L2a 보고서: 내보내기 패키지(ZIP 9파일)

- 브랜치: `task/E4-L2a` · 빌더: claude-opus-5.5 · 검증 예정: Claude Sonnet 5.5
- 스펙: `docs/tasks/E4-L2a.md`. 참고: 계획서 §2 TRACE·§3 L2·§4 E4 L2, 기획 참고 문서(파일 목록과 역할만)

## 무엇을 했나

1. `src/neumann/api/export.py`
   - `build_package(result, *, plan_text=None, decisions=None, created_at=None) -> bytes`: ZIP 9파일(아래 순서 고정).
     `build_package_files(...) -> dict[str, bytes]`는 같은 내용을 파일별 바이트로 돌려준다(재사용·테스트용).
   - 9파일: `README.md`, `manifest.json`, `risk_cards.json`, `evidence_pack.json`, `similar_works.csv`,
     `plan_annotated.md`, `neumann_report.md`, `ai_context.md`, `decision_log.json`
   - `router = APIRouter()` + `POST /premortem/package` 핸들러. `main.py`는 건드리지 않았다(연결은 PM).
2. `tests/e4/test_export.py`: 27건. 9파일·순서, manifest sha256·크기 일치(변조 검출 포함), 인용 = evidence = fixture 원문[start:end],
   리포트·ai_context의 인용 글자 그대로, CSV, 계획서 주석(본문 있음·없음·plan_text 마스킹), 환경변수 값 미포함, 카드 0장(사유 있음·없음),
   강등+rule/astra 표기, status=error, 결정 로그(한국어 선택지·마스킹·잘못된 id·신원 필드 거부), 결정성, API 7건.

### 파일별 내용

| 파일 | 내용 |
|---|---|
| README.md | 결과 상태·카드/근거/유사 연구 수·생성 방식별 카드 수(첫 8줄), 9파일 표, 생성 방식(카드별), 강등 단계 표, 카드 0장이면 사유, 결과 알림, 주의, 한계 |
| manifest.json | `format`, `schema_version`, `created_at`(패키지 생성 시각), 결과 메타, 건수, `cards_by_generator`(astra·rule·mock 모두), `not_ok_stages`, `plan_source`, `evidence_reverification: "not_reverified"`, `warnings`, 나머지 8파일의 `sha256`·`bytes` |
| risk_cards.json | `RiskCard.model_dump(mode="json")` 그대로(계약으로 되읽힌다) |
| evidence_pack.json | 카드별 근거(excerpt_id·source_kind·source_id·source_url·start·end·text·text_sha256·source_sha256), 어느 카드도 인용하지 않은 발췌는 `unlinked_evidence`, 재대조 상태와 대조 방법 |
| similar_works.csv | rank·work_id·similarity·title·venue·year·url·cited_by_cards·axis_*(있을 때). UTF-8 BOM(엑셀 한글) |
| plan_annotated.md | 카드 범례(C1…) + 코드 블록 안에 `16 [C1] \| 본문`. 본문이 없으면 "줄 번호 \| 연결된 카드" 표만 |
| neumann_report.md | 요약, 생성 방식과 단계 표(소요 시간), 카드별 점수·해당 이유·계획서 줄·근거 인용(블록 인용, 원문 링크·오프셋·id), 유사 연구, 예상 심사평·체크리스트(있으면), 결정 로그, 한계 |
| ai_context.md | 다른 AI용 지시(인용 고치지 말 것, 근거 id로만, rule·mock 의미), 상태, 카드별 근거 id·인용(JSON 문자열로 글자 그대로), 유사 연구, 한계 |
| decision_log.json | `choices`(adopt 채택·hold 보류·reject 기각), 결정 대상 `cards`, `checklist_item_ids`, `decisions`(없으면 `[]`) |

## 완료 기준별 결과

### 1. `python -m pytest tests/e4 -q -k export` 통과

```
PS> $env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;."; $env:HF_HUB_OFFLINE="1"; $env:TRANSFORMERS_OFFLINE="1"
PS> python -m pytest tests/e4 -q -k export
...........................                                              [100%]
27 passed in 0.73s
```

검사기가 실제로 잡는지 한 번 확인했다(스크래치 스크립트로 모듈을 일부러 망가뜨림, 저장소에는 넣지 않음):

```
OK   rule을 LLM으로 표기: 실패를 잡았다
OK   manifest sha256 오류: 실패를 잡았다
OK   인용문 가공: 실패를 잡았다
OK   비결정 출력: 실패를 잡았다
OK   마스킹 누락: 실패를 잡았다
복구 뒤 통과
```

### 2. fixture 결과로 만든 ZIP의 파일 목록과 README 첫 20줄

`build_package(load_fixtures().premortem_result)`:

```
ZIP 12305 bytes
  2683  README.md
  1878  manifest.json
  2071  risk_cards.json
  5811  evidence_pack.json
   621  similar_works.csv
  1975  plan_annotated.md
  5390  neumann_report.md
  4486  ai_context.md
   604  decision_log.json
--- README.md 첫 20줄
# Neumann 내보내기 패키지

연구계획서 사전 위험 점검 결과를 파일 9개로 묶었다. 파일별 sha256·크기는 `manifest.json`에 있다.

- 결과 상태: **ok** — 강등된 단계 없음
- 위험카드 2장 · 근거 발췌 8건 · 유사 연구 3편
- 생성 방식: astra(LLM) 0장 · rule(규칙 비상 경로) 0장 · mock(테스트용 가짜) 2장
- 계획서 id `3d35460def76efc4a786dce769e614f0d54d110ee2837da6b8fc1dbcf88ef33c` · 분석 시각 2026-09-30T09:00:00Z · 파이프라인 `neumann-1`

## 들어 있는 파일

| 파일 | 내용 |
|---|---|
| `README.md` | 이 안내문: 무엇이 들었나, 생성 방식, 강등 단계 |
| `manifest.json` | 파일별 sha256·크기, 생성 시각, 스키마 버전, 생성 방식별 카드 수 |
| `risk_cards.json` | 위험카드 원자료(계약 RiskCard 그대로) |
| `evidence_pack.json` | 카드별 근거 인용·원문 URL·오프셋·해시 |
| `similar_works.csv` | 유사 연구 목록(UTF-8 BOM, 엑셀에서 바로 열림) |
| `plan_annotated.md` | 계획서 줄 번호 옆에 연결된 카드 표시 |
| `neumann_report.md` | 사람이 읽는 리포트 |
```

fixture 카드는 `generator=mock`이라 README가 "mock(테스트용 가짜) 2장"으로 적고, 한계 절에 "mock 카드는 테스트용 가짜다. 실제 분석 결과로 쓰면 안 된다"를 붙인다.

### 3. `python scripts/verify.py` 통과

```
PS> python scripts/verify.py
.....................................................s.................. [ 62%]
........................s...................                             [100%]
114 passed, 2 skipped in 1.57s
보안: 파일 76개
계약: 2개
테스트: 통과
verify 통과
```

(보고서 커밋 직전에 다시 돌려 같은 결과를 확인했다.)

## 바꾼 파일

- `src/neumann/api/export.py` (새 파일)
- `tests/e4/test_export.py` (새 파일)
- `docs/reports/E4-L2a.md` (이 보고서)
- `main` 병합 1회(`git merge main`, 과제 지시문 추가분만, 충돌 없음)

## 결정 (스펙이 모호해서 고른 것)

1. **결정성의 범위**: 패키지 생성 시각은 manifest의 `created_at` 한 곳에만 둔다. README·리포트는 결과의 `generated_at`(입력)만 쓴다. ZIP 항목 시각도 `generated_at`으로 고정. 그래서 `created_at`을 빼면 모든 파일이 바이트 단위로 같고, `created_at=`을 넘기면 ZIP 바이트 전체가 같다. `created_at`은 스펙 시그니처에 더한 선택 키워드 인자다.
2. **manifest는 자기 해시를 담지 않는다**(자기 참조 불가). 나머지 8파일의 sha256·크기를 담고, README에 그렇게 적었다.
3. **재대조 상태**: 패키지는 원문을 다시 받지 않으므로 `evidence_reverification: "not_reverified"`. 인용 text·오프셋·해시는 `Excerpt` 계약이 이미 자체 정합성(len·sha256)을 보장한다.
4. **카드 0장 사유**: 결과에 적힌 것만 옮긴다(status=error, 정상이 아닌 단계, notices). 아무것도 없으면 "결과에 따로 적힌 사유는 없다"라고 쓴다. 사유를 지어내지 않는다.
5. **`skipped` 단계**도 README "강등 단계" 표에 넣는다(정상이 아닌 단계로 취급). manifest 키 이름은 `not_ok_stages`.
6. **계획서 본문 출처**: `result.plan`이 있으면 그것을 쓰고 `plan_text`는 무시한다. 없고 `plan_text`가 있으면 `PlanDocument.from_text`(NFC+LF, 이메일·ORCID 가림)로 만든다. 그 해시가 결과 `plan_id`와 다르면 manifest·README `warnings`에 적는다. 출력하는 계획서 줄에는 `redact_pii`를 한 번 더 건다(멱등). 인용문은 가공하지 않는다(계약상 원문이 이미 가림 처리됨).
7. **decision_log 형식**: 최상위는 객체, 기록은 `decisions` 목록(없으면 `[]`). 스펙은 "카드별"이지만 목업 `checklist`는 행동 단위(`id`·`t`·`r`·`s`·`m`)로 결정을 받으므로 `DecisionEntry`가 `card_id`·`item_id` 중 하나 이상을 받게 했다. 결과에 없는 id, 선택지 밖 값, 알 수 없는 키(신원 필드 포함)는 거부한다(API 422). 선택지는 `adopt/hold/reject` 또는 `채택/보류/기각`. 메모는 이메일·ORCID를 가린다.
8. **API 입력**: `{"result": {...}, "plan_text": "...", "decisions": [...]}`. 결과 JSON을 감싸지 않고 그대로 보내도 받는다(최상위에 `session_id`·`plan_id`가 있으면). `plan_text`만 오면 E3의 `neumann.pipeline.run_premortem`을 **지연 import**해서 돌린다. 모듈이 없거나 예외가 나면 가짜 카드를 만들지 않고 **카드 0장·`status=error`** 패키지를 돌려준다(단계 `pipeline: error — 분석 파이프라인 미연결(ModuleNotFoundError)` 또는 `…오류(RuntimeError)`). 예외 메시지 본문은 쓰지 않고 예외 클래스 이름만 남긴다. 응답 헤더 `X-Neumann-Status`·`X-Neumann-Cards`로도 알린다.
9. **CSV**: UTF-8 BOM, 줄 끝 CRLF(RFC 4180 기본). 한국어 제목을 엑셀에서 바로 열기 위해서다.
10. 테스트 파일은 `tests/e4/test_export.py` 하나(`-k export`로 전부 선택됨). E4-L0 빌더와 이름이 겹치지 않는다.

## main.py 연결 (PM용)

```python
from neumann.api.export import router as export_router
app.include_router(export_router)          # POST /premortem/package
```

- 핸들러는 동기 함수(`def`)라 FastAPI 스레드풀에서 돈다. `plan_text`만 온 경우 파이프라인 시간만큼 걸린다.
- 응답: `application/zip`, `Content-Disposition: attachment; filename="neumann_package_<plan_id 앞 12자>.zip"`, `X-Neumann-Status`, `X-Neumann-Cards`.
- 화면(E4-L0)이 `/premortem/view` 응답에 원래 결과(`PremortemResult` JSON)를 함께 들고 있으면, 그대로 `{"result": ..., "decisions": [...]}`로 보내면 된다.

## 못 한 것

- PDF는 넣지 않았다(계획서 §4 E4 L2: PDF는 브라우저 인쇄).
- `main.py`에 라우터를 붙이지 않았다(스펙: PM 몫). 그래서 실제 서버(uvicorn)로 띄워 부른 적은 없고, 테스트는 `FastAPI()`에 라우터만 붙인 `TestClient`로 했다.
- 실제 E3 파이프라인 결과(astra 카드)로는 만들어 보지 않았다(아직 main에 없음). 파이프라인 연결은 가짜 모듈로 검사했다.

## 다음 과제에 넘길 것

- E4-L0/PM: 위 두 줄로 `main.py`에 연결. 화면의 "내보내기" 버튼은 이 라우트를 부르고, 목업의 클라이언트 JSZip 조립은 쓰지 않는다(기획 참고 문서: 서버 정본).
- E3-L1b(체크리스트): 항목에 `id`(또는 `item_id`/`action_id`), `text`, `card_id`, `plan_lines`, `generator`를 두면 리포트가 그대로 읽는다. 목업 키(`t`·`r`·`s`·`m`)도 읽는다.
- E3: 카드 0장일 때 사유를 `notices`나 단계 `reason`에 넣으면 README·리포트가 그대로 옮긴다.
- 제안(계약 변경 아님): `PremortemResult`에 결정 로그 칸이 생기면 `decisions` 인자 대신 그것을 읽게 바꾸면 된다.
