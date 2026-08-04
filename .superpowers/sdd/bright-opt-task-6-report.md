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

Receipts now project and bind actual native evidence.  For each successful
task the coordinator re-reads the one private native output tree with
`read_completed_dci_run`, converts it with `recovered_run_to_experiment` and
`recovered_run_to_evaluation_bundle`, and reads every canonical
`workflow-evidence.json` using the existing safe workflow reader.  The closed
receipt contains only recomputable digests (`recovered_run_sha256`, experiment,
evaluation and sorted workflow-bundle-set digests) plus input/output/total
tokens.  Resume and terminal receipt-chain validation recompute that same
projection, so tampering or removal of native artifacts rejects before any
provider load.

Completed output that cannot close this projection is explicitly
`observation-invalid`, with all native digest/token fields null.  Failed,
cancelled, and infrastructure receipts are `native_evidence_state=unavailable`
and likewise retain null native fields: zeroes and synthetic hashes cannot
stand in for unavailable evidence.  Failed DCI runs obtain their category from
the persisted generic evidence-store progress record rather than treating all
failures as model business failures.

Additional focused verification passed on 2026-08-04:

```text
uv run python -m unittest -v tests.test_dci_pathlight_optimization_cli tests.test_dci_benchmark_host tests.test_dci_benchmark_real_executor tests.test_dci_pathlight_recovery tests.test_workflow_evidence_storage
# 90 tests passed
uv run pyright src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py tests/test_dci_pathlight_optimization_cli.py
# 0 errors, 0 warnings
uv run ruff check src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py tests/test_dci_pathlight_optimization_cli.py
# All checks passed
git diff --check
# passed
```

The native-host test uses an actual `DciBenchmarkHost` with a controlled
`BenchmarkTaskExecutor`, exercising discover/source-lock/payload/resolve/draft/
authorize/provider-loading/generic runner/evidence-store/result-type phases for
all eight Bright tasks.  It proves per-task `Decimal("1")` authority,
case-limit 10, zero Judge operations, single native attempt, actual and upper
coverage artifacts, and the complete preflight barrier before provider load.

## Receipt re-review closure

Native failure evidence is now fail-closed: only explicit persisted
`model-refusal`, `evaluation`, `parsing`, or `tool-protocol` classes project to
model-business.  A persisted `unknown` class quarantines the task evidence,
publishes no receipt, and leaves a later explicit resume able to start a fresh
task root.

Cost reconciliation requires exactly one
`coverage-authorized-microusd.<task-limit>` artifact.  It then accepts exactly
one canonical actual amount with no upper artifact, or one exact upper artifact
with no actual amount.  Missing, duplicated, contradictory, malformed, or
wrong-limit cost artifacts reject rather than silently becoming conservative.

For each successful 10-case Bright task, native projection now requires exactly
10 unique completed workflow records, unique bundle/run/input/source identities,
and workflow input-plus-output tokens equal to the recovered cases' aggregate
agent tokens.  The workflow projection and recovered case contracts have no
shared public case key (`run/input/source` hashes versus recovered dataset/case
source hashes), so this release does not claim a fabricated per-case mapping;
it closes the boundary through exact count, identity uniqueness, token equality,
and exclusive task evidence-root ownership.  Missing, duplicate, extra, or
token-mismatched workflow evidence invalidates the projection and receipt replay
recomputes these same constraints.
