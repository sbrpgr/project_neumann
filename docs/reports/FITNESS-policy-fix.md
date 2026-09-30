# FITNESS-policy-fix — 빌더 완료, 통합 PM verify 대기

- 작업 트리: `C:/Users/User/Desktop/project_neumann/out/codex/fix-fitness-policy`
- 브랜치: `codex/fitness-policy-regression`; 고정 시작 소스: `da5aba7e267e2e1297d9cec5ddae21eaaa1a0a4d`.
- 빌더 실제 모델: `codex-gpt-6.1-sol` / medium. 기존 E3-L1z2 완료 과제와 작업 트리는 수정하지 않았다.
- 실제 OpenAI API 호출 0. mock / `NEUMANN_LIVE_TESTS=0`, live 허용 플래그 해제. 지정 실행 관리자는 자식 테스트의 API 키와 live 허용값도 제거한다. `.env`·auth·키·전체 환경 조회 없음.

## 수정

`tests/e3/test_fitness_diff.py`만 수정하고 이 보고서를 추가했다. 제품 코드·fixture·계약·공통 PM 문서는 수정하지 않았다.

1. 기존 분야 비교 기준 `BASE_REV=4cbf0f0`을 유지했다. 문서 분야 동일성, 무작위 입력의 분야 변화, 진짜 신경과학 회귀 검사는 그대로다.
2. 전체 반환값 정책 기준은 독립 소스 `POLICY_REV=47acaba`로 읽는다. 이 기준의 `_FIELDS`만 고정 통합 소스 `FIELD_REV=da5aba7`에서 적용한다. L1s의 `no_topic` 분기와 `input_quality.metrics.field`는 분야 탐지에 의존하므로, 필드를 지우지 않고 승인된 분야 탐지기를 실행하는 비교다. **현재 런타임 코드를 기준으로 복사하지 않는다.**
3. `rule`, fallback, 고정 모델 판정 3종의 모든 결정적 반환값을 251입력 × 5경로로 비교한다. `field`·중첩 `rule.field`·`input_quality`·notice·reason·분류·status 등을 삭제하지 않는다. 비결정적 실행 시간 `elapsed_s`만 비교에서 제외한다. 기준 소스 읽기 실패는 skip 대신 실패한다.
4. 251건 모두에서 규칙 판정과 모델/강등의 `verdict`, `analyze`, `is_research_plan`도 정책 기준과 별도로 비교한다. 사례 제외·분량별 비교 제외 없음.
5. 승인된 299/300/301/599/600/601자 기대를 독립 상수로 명시했다. 각각 앞뒤 공백 유무를 검사하며 내부 공백 포함·한글 무가중 길이, 4요소 유지, reject/warn/ok, 사유·안내문·thresholds, fallback 상태, 실제 mock 호출 0/1회를 확인한다.

## 완료 기준 / 명령과 출력

모든 테스트는 지정 관리자를 거쳐 실행했다. Python은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`; `PYTHONPATH=src;.`, `PYTHONIOENCODING=utf-8`.

```powershell
python C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py -- C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e3/test_fitness_diff.py tests/e3/test_short_input.py tests/e3/test_fitness.py -q -p no:cacheprovider
# Target test slot 1/2 acquired
# 200 passed in 5.86s
```

| 기준 | 결과 |
|---|---|
| 승인 정책을 포함한 전체 결정적 반환값 | 251건 × 5경로 동일, 차등 검사 통과 |
| 정책 기준과 분류 불변 | 251건 전체 규칙/모델/강등 분류 비교 통과 |
| 기존 분야 기준 보존 | `4cbf0f0` 대상 기존 분야 검사 통과 |
| 300/600 정책 | 6경계 × 공백 2종 = 12건 통과; 299 거절/호출 0, 300~599 경고, 600 이상 ok |
| 기존 short_input/fitness 호환 | 세 파일 통합 targeted 검사 200 passed, 실패/skip 0 |
| 변이 | 아래 9종 모두 검사에 잡힘; 변이 검사는 원래 검사의 AssertionError를 요구하므로 변이가 살아남으면 실패 |
| 전체 verify | 실행 안 함. 통합 PM 큐 전용 |

## 반례 / 의미 있는 변이

- 규칙 `fit ↔ unfit` 분류 변이, 모델 경로의 유효 분류 `fit ↔ unfit` 변이: 전체 비교가 둘 다 실패한다. 독립 정책 기준은 변이와 함께 바뀌지 않는다.
- status, notice, 중첩 `input_quality.metrics.field` 변이: 전체 비교가 각각 실패한다. 정책·안내문·분야 필드 삭제로 문제를 숨기지 않는다.
- 상수는 정상인 채 경계 결과만 299→warn, 300→reject, 599→ok, 600→warn으로 바꾸는 4변이: 명시 경계 검사가 각각 실패한다. 단순 threshold 상수 확인만으로 통과하지 않는다.
- 구체 반례: 연구 요소 4개인 **299자** 입력도 승인 정책상 `unfit`, `precheck=too_short`, `decided_by=precheck`, `status=ok`, mock 호출 0이다. 동일 구조 **300자**는 `fit`, input_quality warn, mock 호출 1이다. 옛 40자 정책과 비교해 이 변화를 회귀로 취급하던 실패를 정책 소스 분리로 해결했다.

## 못 한 것 / 다음

제품 변경 없음. 전체 verify·서비스·데이터·부하 측정·하위 에이전트·CLI 추가 실행·main 병합·push·tag는 하지 않았다. 기존 작업 보존, named git add, 보안 훅 유지. 보고서와 테스트만 과제 브랜치에 커밋한다.

1. 통합 PM이 이 커밋을 고정 소스 `da5aba7`에 적용한다.
2. 통합 PM 큐에서 fullverify를 재실행한다.
3. 독립 `codex-gpt-6-sol` 검증자가 기준 분리·변이·경계를 재확인한다.
4. 승인된 추가 정책 변경이 있으면 새 독립 정책 소스를 지정한다; 기대 필드 삭제로 우회하지 않는다.
5. 이 과제의 제품 수정 잔여는 없다. 최종 커밋/깨끗한 상태를 보고하고 종료한다.
