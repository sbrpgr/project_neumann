# FINAL-TOOLS

Builder: codex-gpt-6.1-sol. Scope: source-grounded, bounded finalization checks.

Implemented `run_tool_checks(plan_text, checks, cancel_event=None)` in `src/neumann/analyze/final_tools.py`. Each result returns `check_id`, `kind`, `tool`, `status`, `plan_lines`, `message`, and `details`. Status is `passed`, `failed`, or `unchecked`; missing optional libraries, invalid anchors, ambiguous facts, cancellation, solver unknown, and tool errors never count as passes. Errors use fixed reason codes and omit exception payloads.

## Parameters

Common `params.sources`: one to 32 `{line, quote}` objects; one-based line numbers must belong to `plan_lines`, and quotes must be exact substrings of the original source line. Fact `source` is a zero-based index into this list. Unknown parameter keys are rejected.

- `constraint`: `operation` (`sum` or `product`), `terms` (one to 32 `{source, value}`), `comparator` (`le`, `ge`, `eq`), `limit` (`{source, value}`). Finite numbers must appear exactly once as numeric literals in the corresponding quote. Operation and comparator markers must be anchored. Z3 evaluates the supplied concrete relation with a 200 ms solver timeout.
- `units`: `operation` (`addition` or `equality`), `left` and `right` (`{source, value, unit}`). Numbers must be contiguous with their unit in the source quote. Unit grammar is restricted to short alphabetic identifiers and bounded products, divisions, or powers 1–3. Pint checks dimensional compatibility and executes conversion/addition where appropriate. Numerical equality is outside this check's scope.
- `dependency`: `nodes` (`{id, source, phrase}`), `edges` (`{from, to, source, phrase}`). Phrases must be exact source substrings. Edges require an explicit directional prerequisite marker: FROM followed by `후`, `before`, `선행`, or `prerequisite for`, then TO; or TO `requires` FROM. Networkx detects cycles in hard prerequisites. Feedback, optionality, iteration, or negation makes the check unchecked; cropping a quote cannot erase these qualifiers from its source line.

Maximum 16 checks, 32 facts/nodes/edges/sources per check, 256-character quotes, 200,000-character plan text. Oversized check lists return at most 16 unchecked results. No eval, exec, subprocess, file access, network access, or model-generated code execution.

## Validation

Command (process-only mock provider; live flags zero):

```powershell
$env:NEUMANN_LLM_PROVIDER='mock'
$env:NEUMANN_LIVE_TESTS='0'
$env:NEUMANN_LIVE_LLM_OK='0'
$env:PYTHONUTF8='1'
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e3/test_final_tools.py -q
```

Result: `29 passed in 0.78s`. Coverage includes actual Z3 positive/negative sum and product checks; actual Pint compatible/incompatible/unknown units; actual networkx DAG/cycle checks; unavailable libraries; source mismatch; wrong direction; feedback and cropped qualifiers; fabricated/nonfinite/bool/code numbers; extra code params; numeric ambiguity; unit grammar; check/fact limits; cancellation; and simulated Z3 unknown with its timeout setting asserted.

## Limits and next steps

This verifies supplied anchored claims only, not universal research-plan correctness or the completeness of model-proposed checks. It deliberately leaves unsupported language and ambiguous extraction unchecked. No live API calls or full repository verification were run. Independent gpt-6-sol verification and integration are PM responsibilities; dependency packaging is owned by PM.
