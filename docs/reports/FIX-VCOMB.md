# FIX-VCOMB — E-1 / E-4 수정

2026-10-01 KST. 브랜치 `codex/fix-vcomb`, 기준 HEAD `cda962f`.
빌더: `codex-gpt-6.1-sol`. **빌더 자체 검증 PASS; 독립 검증 판정은 별도 작업자가 해야 한다.**

## 변경

- `src/neumann/analyze/finalize.py`: `_computed_numbers`는 완료된 도구 판정의 `details.computed`에 선언된 유한 숫자 scalar만 허용한다. params의 입력값, nodes/edges/elapsed_ms와 중첩 메타데이터는 계산 근거가 아니다. 현재 계약의 명시적 계산 결과 필드는 computed 하나다. 원문 수치의 허용은 기존 source scope 검사로 유지한다.
- 초기 검사와 수정 후 targeted recheck 모두 `neumann.finalize.tools.run_check → ToolRegistry.run`으로 실행한다. 동일한 `ToolSpec.timeout_s`, 등록 보존, 실패 처리 및 evidence 경계를 사용한다. 시간 초과는 `status=unchecked`, `error=timeout`, 빈 details, timeout message이며 registry의 실패 evidence를 그대로 남긴다. 잔여 쟁점도 unchecked/timeout으로 남는다.
- `tests/e3/test_finalize_vcomb.py`: V-COMBINED computed/timeout-flow 재현, 세 도구의 시간 제한, 재검사 시간 제한, 최종 수정 게이트, 비정상 computed 값 회귀 검사 17개.
- `tests/e4/test_finalize_vcomb_api.py`: 실제 ASGI HTTP finalize 경로의 도구 timeout, 실패 evidence, 잔여 쟁점, 동일 submission 재요청 캐시 검사 1개.
- `tests/e3/test_finalize.py`: 기존 orchestration 스텁을 항목별 registry 호출에 맞춘다. 초기 c1/c2 후 c1만 재검사하는 기존 완료 기준을 유지한다.

## 환경 및 완료 기준별 측정

모든 Python 실행은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `PYTHONPATH=src;.`, mock provider다. 실행 전 OPENAI_API_KEY·NEUMANN_PSEUDONYM_SALT·라이브 허용 플래그를 프로세스 환경에서 제거했다. pytest의 기존 conftest가 설정 로더의 env_file을 비활성화한다. 별도 측정에서도 두 설정 로더의 env_file을 None으로 설정했다. 환경변수 값을 출력하거나 단언하지 않았다.

| 완료 기준 | 결과 |
|---|---|
| E-1 computed만 허용 | metadata-only `details.nodes=99` → `[]`; computed=7 + nodes=99 및 입력 params → `['7']`; unchecked computed=7 → `[]` |
| E-1 최종 수정 게이트 | metadata 99를 제안한 placeholder는 unsupported_number로 거절, 실제 computed 7은 허용 |
| E-4 동일 시간 제한 경로 | 50ms 제한 + 300ms 지연: interface **71.063ms / timeout**, finalize **92.780ms / unchecked / timeout**, evidence와 잔여 쟁점 모두 unchecked |
| E-4 모든 도구·재검사 | constraint/z3, units/pint, dependency/networkx의 50ms 초과 및 targeted recheck 모두 unchecked/timeout 회귀 통과 |
| E-4 실제 HTTP 경로 | 200 응답 안의 도구 상태는 unchecked/timeout, finalization 상태 partial, 실패 evidence 유지. 같은 submission 재요청은 동일 결과이며 도구는 1회만 호출 |
| 요청된 finalize 관련 검사 | **340 passed, 1 skipped in 25.03s**, exit 0 |
| 보안 검사 | 보고서 포함 최종 실행: `보안: 파일 757개`, `verify 통과`, exit 0 |
| diff 공백 검사 | `git diff --check`, 출력 없음, exit 0 |

### RED → GREEN

HEAD의 원래 finalize 모듈을 `git show`로 읽고 두 함수만 별도 Python 프로세스 메모리에 복원했다. 제품 파일이나 git 상태를 되돌리지 않았다. 같은 완료 기준으로 computed 두 상태와 timeout-flow를 실행했다.

```python
import subprocess
from neumann.analyze import finalize
source = subprocess.check_output(['git', 'show', 'HEAD:src/neumann/analyze/finalize.py']).decode('utf-8')
baseline = {'__name__': 'vcomb_baseline'}
exec(compile(source, '<HEAD finalize baseline>', 'exec'), baseline)
for name in ('_computed_numbers', '_run_checks'):
    setattr(finalize, name, baseline[name])
import pytest
pytest.main(['-q', '-p', 'no:cacheprovider', '--tb=no',
             'tests/e3/test_finalize_vcomb.py',
             '-k', 'computed_allowlist or timeout_flow_interface'])
```

위 실행도 mock·비밀값 제거·env_file 비활성화 후 수행했다. **RED: 3 failed, 14 deselected in 0.47s, exit 1.** 수정 파일로 같은 선택을 실행하면 **GREEN: 3 passed, 14 deselected in 0.61s, exit 0.**

### 검증 명령

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:NEUMANN_LLM_PROVIDER='mock'
$env:NEUMANN_LIVE_TESTS='0'
$env:NEUMANN_UI_TESTS='0'
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK -ErrorAction SilentlyContinue
$finalTests = Get-ChildItem tests/e3,tests/e4 -Filter 'test_final*.py' | Select-Object -ExpandProperty FullName
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/finalize tests/e0/test_finalization_integration.py @finalTests
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/e3/test_finalize_vcomb.py -k 'computed_allowlist or timeout_flow_interface'
```

보안 검사 전 `.env` 파일 부재를 이름 존재 여부만으로 확인했다. OPENAI/Anthropic/GitHub/HF 키 이름을 프로세스 환경에서 제거한 뒤 `python scripts/verify.py --security`를 실행했다. `.env`를 읽지 않았다.

## 미실행 및 인계

- 사용자 지시대로 git 쓰기 명령을 시도하지 않았다. 커밋·main 병합·push는 미실행이다. Claude가 아래 다섯 파일을 현재 작업 브랜치에서 커밋해야 한다.
- 화면 `index.html`, 다른 worktree, 계약/models/config는 수정하지 않았다. F-9는 별도 화면 작업 범위다. 브라우저 옵트인 검사 1개는 NEUMANN_UI_TESTS=0으로 건너뛰었다. 브라우저·시험 서버·금지 포트는 사용하지 않았다. 8099는 지정된 종료 inbox POST에만 사용한다.
- 전체 `scripts/verify.py`와 독립 검증은 미실행이다. PM이 병합 전 전체 verify와 독립 재판정을 수행해야 한다.
- registry의 기존 thread timeout은 실행 중인 Python 스레드를 강제 종료하지 않고 늦은 결과를 버린다. 이번 변경도 그 경계를 사용한다. 회귀 테스트는 자체 지연 worker가 종료된 것을 확인한다.

커밋 대상:

```text
src/neumann/analyze/finalize.py
tests/e3/test_finalize.py
tests/e3/test_finalize_vcomb.py
tests/e4/test_finalize_vcomb_api.py
docs/reports/FIX-VCOMB.md
```

권장 제목: `[FIX-VCOMB] Restrict computed evidence and enforce registry timeouts in finalize`

검증 결과 줄: `validation: finalize suites 340 passed, 1 skipped; security verify passed; builder: codex-gpt-6.1-sol`

대시보드: 지정된 PowerShell inbox POST로 Claude에게 위 결과와 커밋 필요를 보고했다. 첫 한글 메시지는 `bad json`으로 거절되어 영문 한 줄로 재전송했고 성공했다.
