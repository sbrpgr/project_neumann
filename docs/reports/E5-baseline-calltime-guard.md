# E5-baseline-calltime-guard

- Base HEAD: `33f1ca88f499c09a4ef9f640735cd132dd746112` (clean at start).
- Builder: `codex-gpt-6.1-sol`, reasoning HIGH. Single builder; no child agents.
- Authorized scope: `eval/baseline_llm.py`, directly related tests, this report.

## Change

`OpenAIBaseline` now applies the product model guard to injected clients at construction and again before each SDK request. `_get_client` checks current process permission even for injected/cached clients; `generate` rechecks immediately before `responses.create`, after client acquisition and model routing. Guard failures remain closed. A blocked call retains the existing `locked=True` result, stops evaluation retries, writes no cache, and reports `generator=none`.

The existing synthetic request-shape test explicitly grants both permissions so its original Astra request/actual-model assertions still test that authorized path. The related E0 baseline assertion now expects injected Astra to route to Sol without Astra permission. No product E3/config/model code, metrics, evaluation data, grades, prompts, schemas, or generator contract names changed. `MockBaseline` is unchanged.

## Measurements

All pytest runs used the six-slot helper, mock provider, live tests disabled, and the existing test Python `C:/Users/User/.venvs/neumann/Scripts/python.exe`. Permission grants exist only inside monkeypatched synthetic tests. No real OpenAI calls, credentials, `.env` reads, services, corpus runs, or data writes were used. New guard tests replace SDK construction and settings access with rejecting sentinels; all request counts below are synthetic `responses.create` calls.

Red, before implementation (17 initial cases):

```powershell
$testTemp = Join-Path C:/Users/User/Desktop/project_neumann/out/codex ('e5-baseline-red-' + [guid]::NewGuid().ToString('N'))
python C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py -- C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e5/test_baseline_calltime_guard.py -q --tb=no --basetemp $testTemp
```

Output: `12 failed, 5 passed in 0.17s`; exit 1. Unauthorized injection, post-success revocation, revocation during acquisition, injected Astra routing, current Astra revocation, guard failure, and blocked-cache behavior failed. Four authorized fake-SDK cases and ordinary mock passed.

Final green (three additional focused guard cases plus existing baseline and two related E0 tests):

```powershell
$testTemp = Join-Path C:/Users/User/Desktop/project_neumann/out/codex ('e5-baseline-final-' + [guid]::NewGuid().ToString('N'))
python C:/Users/User/Desktop/project_neumann/out/codex/run_target_tests.py -- C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e5/test_baseline_calltime_guard.py tests/e5/test_backtest_baseline_llm.py tests/e0/test_sec3_live_guard.py::test_baseline_replaces_astra tests/e0/test_sec3_live_guard.py::test_baseline_llm_locked_is_not_cached_and_not_astra -q --basetemp $testTemp
```

Output: `28 passed, 1 skipped in 0.27s`; exit 0. The skip is the existing real-API test.

| Criterion | Asserted measurement after fix |
|---|---|
| Missing/invalid process LIVE permission (5 values) | SDK calls 0; `locked=True`; direct `_get_client` raises `LiveCallLocked` |
| Authorized fake SDK (`1`, `true`, ` yes `, `ON`) | 1 successful SDK call per case; plan/instructions/store preserved |
| Permission revoked after authorized client acquisition | SDK calls 0 |
| Permission revoked after a successful request | Total calls remain 1; revoked request adds 0 |
| Permission revoked during client acquisition | SDK calls 0 |
| Settings-only approval, absent process permission | SDK calls 0; settings cannot authorize |
| LIVE guard exception | SDK calls 0; closed result |
| Injected Astra, including uppercase model name | Constructor and requested/actual synthetic model are `gpt-6.1-sol`; 1 call |
| Astra permission revoked after successful Astra request | 2 calls total: first Astra, second Sol |
| Model guard exception | 1 successful synthetic call routed to Sol |
| Locked evaluation/cache | 1 locked attempt, SDK calls 0, cache files 0, `generator=none`, `status=error` |
| Ordinary mock and existing baseline behavior | No LIVE permission needed; 3 risks; cache/retry/trim/shuffle/request-shape tests pass |

`git diff --check` passed before commit. Initial setup attempts found no pytest in default Python, then a denied default pytest temp directory; the successful red/green commands use the existing venv and fresh writable task-specific temp directories. Neither setup failure is counted as the defect result.

## Remaining / next

Independent `gpt-6-sol` verification remains for PM; this is builder measurement, not independent verification. Full verify, real API, load/corpus evaluation, main merge, push, and tags were not run per task scope. PM should independently remeasure these call counts and run the required integration checks before merging. Existing persisted cache semantics and evaluation data were left unchanged.
