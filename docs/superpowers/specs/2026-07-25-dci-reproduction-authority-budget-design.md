# DCI Reproduction Authority and Budget Design

> Approved direction: explicit execution with enforceable multi-scope budgets,
> disabled by default.

## Context

The existing `paper reproduce` path can issue an in-process
`FullExecutionAuthorization`, print that authorization was issued, and exit
without consuming it. The authorization binds a profile, paper scopes,
selected-ID digests, and one private output-root inode, but its USD budget is
metadata only. The benchmark runner has no operation-count or cost ledger.

Task 8 closes that gap without changing provider-free defaults.

## User-facing modes

`paper reproduce` has two modes:

1. **Plan mode (default).** Without `--execute`, the command resolves the
   selected profile and scopes, prints only body-free counts and identities,
   performs zero Agent/Judge operations, creates no authority, and requires no
   budget configuration.
2. **Execution mode (explicit).** `--execute` is the sole invocation-level
   execution authorization. Only this mode requires:
   - positive Agent operation cap;
   - positive Judge operation cap;
   - positive finite total USD cap;
   - positive finite Agent per-operation USD upper bound;
   - positive finite Judge per-operation USD upper bound.

Budget values never imply execution authority. Configuration, environment,
prior evidence, and caches cannot replace the explicit `--execute` flag.

Scope selection is repeatable and exact. If no scope is selected in plan mode,
the plan may describe the profile's paper scopes. Execution mode requires an
explicit non-empty scope selection so a broad profile cannot accidentally
authorize every scope.

## Considered approaches

### Selected: registry ledger plus descriptor-bound scope roots

Keep the unforgeable in-process authorization object and extend its private
registry record with:

- exact selected scopes and selected-ID digests;
- Agent and Judge operation caps;
- total USD cap;
- per-operation USD upper bounds;
- reserved, completed, and actual-cost counters;
- cancellation and finalization state;
- one deterministic child output-root identity per scope.

This supports multiple scopes while preserving fail-closed identity and
budget checks at every external operation.

### Rejected: single-scope execution only

This fits the current single batch-root model but postpones the approved
multi-scope interface and would require another authorization migration.

### Rejected: actual-cost accounting without reservations

Actual costs are available only after an Agent or Judge operation. Accounting
afterward can stop later operations but cannot enforce the total cap before
the current operation. It must not be described as an enforced budget.

## Authority model

`authorize_full_execution(...)` validates:

- exact resolved profile identity;
- exact selected paper scopes and selected-ID identities;
- a fresh private parent output root;
- positive integer operation caps;
- positive finite total and per-operation USD limits;
- `invocation_authorized is True`.

It creates and descriptor-checks deterministic per-scope child directories
under the parent root. Scope IDs are mapped to safe opaque child names rather
than used as paths. The immutable public authorization value exposes only
body-free identities and limits; the issuance token is private and never
printed or serialized. Paths are excluded from `repr`.

The registry is the mutable source of truth. Under one lock it stores each
scope's output identity, consumed state, operation reservations, reconciled
actual costs, cancellation state, and finalization state.

## Budget lifecycle

Before an external Agent or Judge operation, the benchmark executor calls a
reservation function with the authority, scope, operation kind, and that
kind's configured upper bound. Reservation fails before provider work if:

- the authority/profile/scope/output identity changed;
- the scope was not consumed exactly once;
- authorization was cancelled or finalized;
- the operation cap would be exceeded;
- accumulated actual cost plus all active reservations plus the new
  reservation would exceed the total USD cap.

After the operation, the executor reconciles the reservation with
descriptor-bound actual-cost evidence. The actual cost must be finite,
non-negative, and no greater than the reserved upper bound. A missing,
invalid, or excessive actual cost fails closed and cancels all later
operations.

Cache reuse performs no reservation because it performs no external
operation. A Judge evaluation operation may internally retry transport, so
its per-operation upper bound covers the entire evaluation call, not one HTTP
attempt.

Cancellation marks the registry record before draining in-flight work.
Waiting rows fail their next reservation and cannot start another external
operation.

## Execution flow

The CLI performs one same-process chain:

```python
authority = authorize_full_execution(
    profile=profile,
    scope_ids=scope_ids,
    output_root=output_root,
    max_agent_operations=max_agent_operations,
    max_judge_operations=max_judge_operations,
    max_cost_usd=max_cost_usd,
    max_agent_cost_per_operation_usd=max_agent_cost_per_operation_usd,
    max_judge_cost_per_operation_usd=max_judge_cost_per_operation_usd,
    invocation_authorized=True,
)
return execute_authorized_reproduction(
    authority,
    profile=profile,
    scope_ids=scope_ids,
    output_root=output_root,
)
```

`execute_authorized_reproduction` verifies the exact arguments against the
authorization snapshot, consumes each scope once, and sends each benchmark
request only to its pre-bound child root. It never discovers scopes,
runtimes, credentials, or output locations.

The duplicate issue-and-exit reproduction helper is removed or delegated to
the same plan/execute implementation. No command may issue a live authority
and return without consuming or cancelling it.

## Errors and privacy

All public failures use stable classes and generic messages. They never
include:

- issuance tokens;
- credentials or environment values;
- profile payloads;
- prompts, answers, corpus text, provider responses, or raw output;
- private parent or child paths.

Mismatch, inode replacement, replay, invalid cost evidence, and cancellation
all fail closed before any later operation.

## Verification

Provider-free tests cover:

- default plan mode requires no budget flags and performs zero operations;
- `--execute` requires every positive finite limit;
- absent, forged, replayed, mismatched, cancelled, and inode-replaced
  authorities are rejected;
- multiple scopes use distinct pre-bound child roots;
- Agent and Judge caps stop before excess operations;
- reservations stop before exceeding total USD;
- actual cost reconciles reservations and excessive actual cost cancels later
  work;
- cache hits do not consume operation budget;
- cancellation prevents waiting rows from starting;
- sentinel credentials and private paths never appear in errors or output;
- the CLI authorizes and consumes in one process and never serializes the
  token.

All tests use local fixtures and perform zero provider operations.
