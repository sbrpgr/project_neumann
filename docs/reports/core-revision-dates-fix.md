# core-revision-dates-fix

Builder actual model: `codex-gpt-6.1-sol`, HIGH (PM 배정). Worktree `C:/Users/User/Desktop/project_neumann/out/codex/fix-revision-readme`, branch `codex/revision-readme-authority`. 시작 HEAD `894e15cefdbc308a286de631f332041c556d63ef`, 시작 작업 트리 깨끗함. 수정 범위: export.py·export_revision.py·새 E4 검사·이 보고서.

## 수정과 기준

- 최신 `core-candidate-894-review-evidence.md`와 `core-candidate-review/revision_probe.py`를 먼저 확인하고 같은 894에서 실행했다. signed 결과와 unsigned revision을 함께 보내면 revision.json은 미확인인데 README에는 모델 sentinel이 출처 한정 없이 실리는 원래 반례를 재현했다.
- README의 각 수정 권고 요약 줄에 **그 수정 권고의** 출처를 표시한다. 결과 HMAC과 revision HMAC이 함께 맞을 때만 기존 generator/model 요약을 유지한다. 미확인 권고에는 생성 표기 미확인 문구를 쓰고 self-asserted model/generator를 확인된 값처럼 전시하지 않는다. 원 revision JSON 값은 그대로 보존한다. `result_origin`은 바꾸지 않는다.
- 통합본 요약도 별도로 결과·revision·revised-plan의 서명을 검사해 출처를 붙인다. 추가 Markdown renderer와 요약이 같은 `_assembly_trusted` 함수를 사용한다. 서명된 정상 생성·조립 내용은 유지한다.
- `2200-01-01Z`, `9999-12-31T23:59:59-10:00`, `0001-01-01T00:00:00+10:00`을 최신 894에서 직접 재현했다. ZIP은 UTC 기준 1980~2107년만 수용하고 범위 밖/UTC 변환 overflow는 ValueError→API 422로 거절한다. 1980으로 클램프하던 옛 동작도 제거했다. 현재 날짜 대체·입력 날짜 변경·HMAC 출처 변경은 없다. 역사 결과에 TTL을 붙이지 않는다.
- `_iso`의 UTC overflow도 동일하게 ValueError로 닫으므로 직접 파일 builder의 created_at overflow도 보호한다. 유효한 날짜는 기존 ISO 값과 ZIP 항목 시각을 그대로 쓴다.
- 과거 FUZZ 보고서와 direct_export.py는 반례 출처로만 사용하고 최신 894에서 다시 측정했다. checklist.plan_lines=5는 이미 `NO_EXCEPTION`이므로 그 정책이나 게이트를 수정하지 않았다.
- SEC7 raw helper는 이 base에 없고 처음 확인 때 미커밋이었다. 작업 중 `eb7a331`로 커밋됐으나 이 고정 worktree에 dependency가 아직 없어서 helper를 복제하거나 main/jobs/upload를 바꾸지 않았다. 아래 export 전용 연결 패치를 남긴다. **현재 커밋에 raw cap이 적용됐다고 주장하지 않는다.**

## 실행과 출력

Python `C:/Users/User/.venvs/neumann/Scripts/python.exe`. 모든 표적 시험·probe는 `C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py -- <python> ...`의 6-slot helper로 실행했다. helper가 자식의 provider=mock, live tests=0, OpenAI 키/live 허용 플래그 제거를 적용한다. 실제 API 호출 **0**. 브라우저/서버/실서비스/공개 원본/전체 verify/부하 측정 없음. 시각 비교는 성능 기준으로 쓰지 않았다.

| 완료 기준 | 명령·대상 | 실제 출력 |
|---|---|---|
| 최신 README 반례 Red | helper → `python -c`에서 sys.path에 `src`, `.`를 넣고 지정 revision_probe.py를 runpy 실행 | `revision.json origin: client_submitted_unverified`, README sentinel `True`, explicit qualifier `False` |
| 최신 날짜 직접 재현 | helper → 동일 방식으로 지정 FUZZ direct_export.py 실행 | `B2 error`, `B3-upper OverflowError`, `B3-lower OverflowError`, `B4 NO_EXCEPTION` |
| 새 반례 Red | `-m pytest tests/e4/test_export_revision_dates.py -q -p no:cacheprovider --basetemp .../core-revision-dates-red --tb=short` | `9 failed, 4 passed in 0.92s`: revision 로컬 출처 4건·날짜 3건·클램프/created_at 2건 실패, 정상 ZIP 경계/이력 4건 통과 |
| 최종 Green | `-m pytest tests/e4/test_export_revision_dates.py tests/e4/test_export.py tests/e4/test_export_ui_sign.py tests/e4/test_export_plan_authority.py tests/e4/test_export_revision.py -q -p no:cacheprovider --basetemp .../core-revision-dates-final --tb=short` | **`100 passed in 1.52s`**, skip/xfail 없음 |
| 결과/수정 권고/통합본 출처·원내용 | 위 Green | unsigned·signed·변조 model·누락 결과 HMAC 4건에서 revision JSON의 입력 값 완전 동일, 로컬 summary 출처 일치. 실제 서명된 결과/수정/조립 연결과 9/10/11파일 구성 통과. 통합본 서명 또는 revision 서명 변조는 local summary와 renderer 둘 다 미확인 |
| 날짜 500 제거·정상 보존 | 위 새 검사 | 세 bad date × signed/unsigned 6건 모두 422, 직접 build_package ValueError. 1980/2107 경계·2020 윤일 이력·현지 2108이지만 UTC 2107인 정상 입력의 ZIP 날짜와 manifest ISO 값 정확히 보존. 1979 거절, created_at UTC overflow ValueError |
| 원 probe Green | Red와 같은 revision_probe.py·direct_export.py 재실행 | README sentinel `False`, qualifier `True`, revision.json origin 그대로 미확인. 날짜 세 건 모두 `ValueError`, B4 그대로 `NO_EXCEPTION` |
| 의미 변이: 요약에서만 trust 우회 | helper → 별도 python에서 summary_lines 실행 중에만 `_origin`을 server_signed로 바꾼 뒤 unsigned summary 검사 | `1 failed, 12 deselected in 0.54s`, `SUMMARY_TRUST_BYPASS_DETECTED=True`. revision.json 판정은 그대로인데 README 오인 표기를 검사기가 잡음 |
| 의미 변이: ZIP 날짜 임의 치환 | helper → 별도 python에서 `_zip_date`를 합성 상수 날짜로 바꾼 뒤 latest_three/zip_date_boundaries/no_clamping 선택 검사 | 최종 검사 기준 `7 failed, 4 passed, 8 deselected, 1 warning in 0.37s`, `DATE_SUBSTITUTION_DETECTED=True`. 범위 밖 수용과 정상 이력 날짜 변경을 모두 잡음 |
| 형식 | `git diff --check` | exit 0, 출력 없음 |

변이는 별도 프로세스 메모리에서만 실행해 저장소 코드를 바꾸지 않았다. anyio assertion-rewrite 경고는 변이 probe가 pytest 전에 앱 모듈을 import한 영향이다. 첫 날짜 변이 실행은 합성 ZIP 응답을 실패 메시지로 출력해 노이즈가 컸다. 테스트의 실패 메시지만 status/content-type으로 줄인 뒤 최종 변이를 재실행했다. 기대 상태나 날짜·출처 검사는 낮추지 않았다.

## SEC7 dependency 뒤 적용할 export 전용 작은 패치

아래 diff는 이 보고서 작성 시점의 export.py를 기준으로 생성했다. `eb7a331`의 shared `neumann.api.plan_limits`가 **먼저** 포함돼야 한다. 새 cap/helper 구현은 복제하지 않는다. API에서는 nested Pydantic/NFC 이전, 직접 builder에서는 model 검증/게이트 이전에 호출한다. 기존 normalize_text·해시·근거·서명 판정은 건드리지 않는다. dependency와 이 패치를 합친 뒤 oversize raw text/embedded lines를 넣고 model/NFC 호출 0 및 정상 본문/id 동일성을 표적 검증해야 한다. 이 통합 경로는 현재 worktree에서 적용·실행하지 않았다. 보고서 diff를 final LF를 포함해 `out/codex/core-revision-dates-export-cap.patch`로 추출한 뒤 `git apply --check`는 exit 0이다. 첫 scratch 추출은 마지막 LF를 빠뜨려 corrupt patch였으며 추출만 고쳤다(제품 파일 적용 없음).

## 남은 일 5줄

1. PM이 SEC7 `eb7a331` dependency와 아래 export 전용 raw-cap 패치를 통합하고 early guard 표적 검사를 실행한다.
2. 독립 `gpt-6-sol`은 이 안정 HEAD에서 unsigned summary·날짜 3종·signed 정상값을 재측정한다.
3. 전체 `scripts/verify.py`는 PM 전용 큐에서 수행한다. 커밋 훅은 유지한다.
4. main/fonts/jobs/upload/models/config/contracts/index/UI·공통 docs는 수정하지 않았다. 다른 worktree·프로세스도 수정/종료하지 않았다.
5. main 병합/push/tag·공통 인계 문서 갱신과 최종 release 판정은 PM 담당이다.

```diff
--- a/src/neumann/api/export.py
+++ b/src/neumann/api/export.py
@@ -45,6 +45,7 @@
 from neumann.analyze.checklist import gate_checklist_items
 from neumann.analyze.gate import EvidenceIndex, MALFORMED, NO_EVIDENCE_FAMILY, SECTIONS, review_evidence_problem
 from neumann.api.view import display_generator, display_text
+from neumann.api.plan_limits import check_embedded_plan, check_payload_plan
 from neumann.api import export_revision  # E3-L2r: ZIP에 덧붙이는 수정 권고·통합본 파일(선택)
 from neumann.models import (
     SCHEMA_VERSION,
@@ -1068,6 +1069,12 @@
 # ── 공개 함수 ─────────────────────────────────────────────────────────────
 
 
+def _guard_export_plan(result: Any, plan_text: str | None) -> None:
+    check_payload_plan({"result": result, "plan_text": plan_text})
+    if isinstance(result, PremortemResult) and result.plan is not None:
+        check_embedded_plan(result.plan.lines)
+
+
 def build_package_files(
     result: PremortemResult | Mapping[str, Any],
     *,
@@ -1085,6 +1092,7 @@
 
     E3-L2r: `revision`(수정 권고)·`revised_plan`(통합본)이 오면 `revision.json`·`revised_plan.md`를 뒤에 덧붙인다(10·11번째).
     """
+    _guard_export_plan(result, plan_text)
     if not isinstance(result, PremortemResult):
         result = PremortemResult.model_validate(result)
     c = _make_ctx(result, plan_text, decisions, result_origin)
@@ -1129,6 +1137,7 @@
     - created_at: 패키지 생성 시각(manifest). 없으면 지금. 넘기면 출력 전체가 결정적이다.
     - result_origin: 결과 출처(manifest·README). API는 서버 서명을 확인해 정한다. 직접 부르면 "in_process".
     """
+    _guard_export_plan(result, plan_text)
     if not isinstance(result, PremortemResult):
         result = PremortemResult.model_validate(result)
     date_time = _zip_date(result.generated_at)  # reject unsupported dates before rendering; never substitute a date
@@ -1193,6 +1202,7 @@
     plan_text만 오면 파이프라인을 돌리지 않고 422 + 사용자 문구로 거절한다(SEC-1 S-02, PM 결정 2026-09-30:
     내보내기는 결과만 받는다. 분석은 /premortem의 관문·속도 제한·예산을 거쳐야 한다).
     """
+    check_payload_plan(payload)  # raw guard before nested model validation/NFC
     if "result" not in payload and "plan_text" not in payload and {"session_id", "plan_id"} <= payload.keys():
         payload = {"result": payload}
     try:
```
