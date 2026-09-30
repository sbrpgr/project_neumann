# FINAL-ENGINE builder report

Builder: codex-gpt-6.1-sol. Additive final draft engine; no existing model/contracts changed.

Implemented `finalize_plan(plan_text, *, result=None, provider=None, checks=None, cancel_event=None, llm_call=None)`.
Structured assessment extracts logical/physical/structural issues and at most 16 grounded tool checks.
One structured correction request permits at most eight exact-anchor line edits, at most one applied batch,
and at most one targeted local recheck. No retrieval or iterative semantic calls occur. Cancelled or failed
assessment/correction stops subsequent work and returns incomplete with the accepted source retained.
Rejected edits retain the original line and report reason. New line-local numbers, existing unsupported-fact
patterns, identity, PII, unsafe markup and control characters are rejected. Source quotations are attached
from source lines by code; the assessment model emits source IDs only. `result` is accepted for API
compatibility but is not treated as authority for new scientific or numeric commitments.

The return carries finalization@v1, PlanDocument-compatible input/output hashes, source/final text,
issues and residual statuses, before/after tool audits, correction audits, counters and generator/model.
Completed means the bounded run finished with no reported residual; its notice explicitly disclaims
universal error absence. Unverified semantic issues remain unchecked, including after a safe edit.
Mock has deterministic empty edits plus an explicit unverified scientific-scope issue; off is incomplete.

Targeted measurement (process-scoped mock, LIVE_TESTS=0, LIVE_LLM_OK=0, PYTHONUTF8=1):

`C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e3/test_finalize.py -q`

Output: `10 passed in 0.22s`.

Checks cover strict schemas, mock honesty, safe anchored correction and hashes, numeric/entity/PII/markup
rejection, wrong anchors, timeout/API/schema failures, cancellation before/after assessment, exactly one
targeted recheck and preserved unmodified checks, maximum checks, unavailable tools, bounded completed
notice and sanitized provider exceptions. Targeted adapter orchestration test uses an explicitly labelled
stub; actual tool-module integration and independent-model validation remain PM integration tasks.

Limits: existing unsupported_facts patterns cannot prove scientific truth or recognize every entity. The
draft is not certified as scientifically correct. Recheck retains original check anchors; changing the
source assertion makes that check unchecked rather than silently claiming the previous fact is proved.
No full verify or live API call was made. Next: integrate FINAL-TOOLS and run independent validation.
