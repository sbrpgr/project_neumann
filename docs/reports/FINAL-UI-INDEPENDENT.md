# FINAL UI independent verification

- Verifier: codex-gpt-6-sol; product builder: codex-gpt-6.1-sol.
- Checkout HEAD observed after test: `401e75e` (shared checkout advanced from `343d473` during verification).
- Command: `NEUMANN_UI_TESTS=1 C:\Users\User\.venvs\neumann\Scripts\python.exe C:\Users\User\Desktop\project_neumann\out\codex\run_target_tests.py --browser -- C:\Users\User\.venvs\neumann\Scripts\python.exe -m pytest -q -s tests/e4/test_finalize_browser.py`
- Result: **1 passed in 9.41s**. The local HTTP server used the production app, explicit fixture evidence backend, and mock LLM provider. No browser route interception or actual OpenAI call was used.

The browser loaded a public sample, ran analysis through `/premortem/jobs`, obtained an actual revision through `/premortem/revise`, submitted a researcher edit to `/premortem/revise/assemble`, and clicked **수정 확정·검증** once. Exactly one `/premortem/revise/finalize` request was observed for that click; it returned HTTP 200, `server_signed` origin, and a finalization signature. The final panel displayed the response `final_text` exactly. The downloaded `neumann_final_plan.md` contained that same text and the change/issues sections. The mock-provider result was `partial`, 613 final characters, zero corrections, and one remaining issue; this verifies honest partial status rather than a fabricated complete state.

Changing the polish option cleared the displayed finalization and removed the final panel. With the browser taken offline, another finalize click produced a visible failure message and no finalization result. Source inspection also confirmed that decision and direct-edit handlers call `invalidateFinalization()` and that the final panel and Markdown use `final_text`.

Limit: This test covers one sample and one revision choice. It does not establish semantic quality for other plans or exercise the live OpenAI provider. The Word download still describes the assembled manuscript, whereas the finalized text is offered as Markdown; its button and title state that distinction.
