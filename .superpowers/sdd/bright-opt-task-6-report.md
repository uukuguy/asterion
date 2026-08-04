# Bright Optimization Task 6 Report

## Delivered boundary

`pathlight optimization execute` and `resume` now require the exact private
plan, the separately supplied exact authorization, and the prepared output
root.  Before any provider load, the coordinator re-reads the plan tree,
source lock, selected Bright rows, query-plan contracts and execution-config
digests, root device/inode, budget limits, and the complete receipt chain.
All remaining dataset/variant tasks then complete the existing
`BenchmarkCommandHost` metadata, lock, payload, application and draft-plan
phases before any task can load a provider.  Execution is foreground and
strictly ordered by the plan.

Each task gets a fresh private evidence root and one exclusive, mode-0600,
canonical receipt.  Fixed receipt names, no-extra-child validation, strict
field shapes, receipt digests and previous-receipt digests make the chain
append-only and reject replay, truncation, reordering, duplicate, symlink,
FIFO, ownership and mode attacks.  Receipts retain only digest-safe run and
evidence identities, terminal status, case count, usage, elapsed time,
failure category and cost evidence; they never project raw case/run/path,
prompt, output or provider data.

Model business failures are terminal without retries.  Authorization, network,
rate-limit, timeout and host-service failures consume the conservative task
budget and stop after two.  Cancellation returns 130 safely.  Unknown failures
fail closed without publishing a receipt.  Observation-invalid completion is
recorded as non-acceptable evidence state.  `status` uses the same chain
reader, and a fully terminal resume is provider-free/idempotent.

## Verification

Passed on 2026-08-04:

```text
uv run python -m unittest -v tests.test_dci_pathlight_optimization_cli
# 19 tests passed
uv run pyright src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py tests/test_dci_pathlight_optimization_cli.py
# 0 errors, 0 warnings
uv run ruff check src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py tests/test_dci_pathlight_optimization_cli.py
# All checks passed
git diff --check
# passed
```

The focused execution tests use a recording `BenchmarkCommandHost` shaped fake
only for provider/executor results; they assert all real host-boundary phases,
the full preflight barrier, fixed eight-task order, business/cancellation/
observation terminal semantics, actual and conservative costs, two-
infrastructure stop, partial and terminal resume, source/selection/prompt/
plan/root drift rejection, unknown-failure closure, and receipt-chain attack
matrix (truncation, extra, mode, symlink, FIFO, reorder and overspend).  No
provider was called while validating this change.

## Follow-up hardening

The coordinator now constructs a fresh `DciOperatorConfig` per task with an
exact `DciBenchmarkOperatorInputs.amount` derived from the remaining task and
global microdollar budget; `max_native_attempts` remains exactly one.  It reads
terminal receipt chains before loading operator configuration, binds each
execute/resume chain to the supplied authorization digest, uses the existing
`coverage-actual-microusd.*` / `coverage-upper-microusd.*` cost artifact
contract, and quarantines unknown-failure evidence so a later explicit resume
is not wedged.

Native workflow/recovery artifacts are not yet emitted by the benchmark result
contract for Bright optimization.  Consequently, the receipt's current
workflow/evaluation digest fields are not sufficient as a Task 7 re-read
contract; a subsequent native-evidence adapter must replace them with
`read_completed_dci_run` plus recovered Experiment/Evaluation bundle digests.
