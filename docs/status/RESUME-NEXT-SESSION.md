# Live Session Checkpoint

> Updated: 2026-07-29. Plan 4 implementation is complete on
> `feature/capability-protocol-foundation`.

## Outcome

DCI is implemented as `dci@1.0.0`, one capability package consumed by the
generic Asterion benchmark subsystem. It is not a generic framework dependency
or a parallel benchmark architecture.

The package owns seven capability manifests, three exact benchmark suites,
fifteen task bindings, its domain implementation, resources, and provider.
The `asterion-dci` entry point is only an application adapter over the generic
benchmark host.

DCI passed an external-first proof in a clean wheel environment using only the
public SDK. Its built-in, installed-distribution, and explicit local-directory
forms have equivalent payload identity, conformance, implementation bindings,
plans, and public results. Equal candidates remain ambiguous without an exact
source lock.

The obsolete `asterion.dci`, `asterion.capabilities.dci_research`, global
launchers, task shell scripts, and legacy tests are absent. Generic framework
packages do not import DCI.

## Plan 4 commits

- `9e5ca30` — migrate DCI manifest consumers to the portable payload.
- `d97cb60` — harden portable DCI payload boundaries.
- `bac48d3` — bind DCI benchmark tasks in package code.
- `0abb75a` — move DCI implementation into its package.
- `c720586` — make the DCI CLI an application adapter.
- `61a966e` — remove global DCI benchmark launchers.
- `dfddcb2` — prove DCI as an external capability package.
- `1a3b162` — materialize DCI as an equivalent built-in source.

## Boundaries

- Planning, acceptance, tests, checks, and promotion are provider-free.
- Execution requires a fresh embedding-host authorization, an exact source
  lock, injected implementations and services, cancellation, and private
  evidence storage.
- A monetary amount is optional private DCI operator configuration, not a
  generic requirement or execution authority.
- Full datasets and paper reproduction remain separately governed and were not
  run.
- Archive and registry source forms remain deferred pending a separate security
  and lifecycle design.

## Next action

Review and integrate this branch. No Plan 4 implementation task remains after
the final Task 8 gates and review pass.
