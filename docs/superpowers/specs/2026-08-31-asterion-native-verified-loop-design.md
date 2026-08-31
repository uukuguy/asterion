# Asterion Native Verified-loop Design

## Purpose

This phase advances the Asterion-native reproduction program from the durable
single-session controller core to the first closed, evidence-backed Native
`Verified-loop` slice.  It targets exactly these eleven mandatory Prime rows
at pinned Prime commit `a18809e00ea30638584d87b3afea7285a9d7296c`:

- `session.persistence-naming`, `session.resume-delete`, `session.delivery`,
  and `session.usage-status`;
- `rlm.environment`, `rlm.generated-program`, `rlm.usage-cost`, and
  `rlm.recovery`; and
- `operation.goals`, `operation.detach-attach-replay`, and
  `operation.autonomous-quality`.

The phase must produce a Native implementation and a truthful reducer.  It
does not redefine Prime Gateway evidence as Native evidence, and it does not
claim full Prime reproduction.  The remaining mandatory Native rows stay
Missing after this slice.

## Evidence partition

Nine rows are `real-prime-provider-free` in the canonical feature index:

| Native scenario | Feature | Required proof |
|---|---|---|
| named-session lifecycle | `session.persistence-naming` | stable identity/name across restart and idempotent rename |
| exact resume/deletion | `session.resume-delete` | selector correctness, active-delete rejection, bounded cleanup |
| input delivery | `session.delivery` | direct, steer, and follow-up ordering/cancellation semantics |
| public usage status | `session.usage-status` | monotonic, body-free context/token/usage projection |
| persistent RLM environment | `rlm.environment` | isolated environment identity and turn-to-turn state |
| RLM usage attribution | `rlm.usage-cost` | monotonic child attribution with no private provider payload |
| RLM snapshot recovery | `rlm.recovery` | exact snapshot restoration and fail-closed uncertainty |
| operation goals | `operation.goals` | persistent active and terminal state transitions |
| detach/attach/replay | `operation.detach-attach-replay` | one contiguous history, cursor replay, no duplicate terminal |

`rlm.generated-program` and `operation.autonomous-quality` are explicitly
`bounded-provider`.  Their real-provider receipt is necessary for Native
`Verified-loop`; provider-free doubles may test rejection, causal accounting,
and redaction but cannot promote either row.

## Architecture

### Native feature services

Add narrowly scoped Native services above the existing controller and stores:

- a session registry and delivery queue, whose durable records are reduced by
  the controller's existing contiguous journal rules;
- an isolated program-environment service with snapshot descriptors and
  monotonic usage attribution; and
- an operation service that owns goals, detach/attach cursors, and finite
  autonomous continuation state.

These services receive resolved identifiers, the immutable controller state,
and injected host services.  They do not discover providers, read environment
variables, choose models, or retain raw content.  Their public projections are
closed, body-free protocol values with stable IDs and sorted unique arrays.

### Turn-adapter boundary

`NativeTurnAdapter` remains the sole controller boundary for turn execution.
The deterministic adapter remains the provider-free test implementation.  A
separate production-facing bounded adapter may be supplied only by the host
after exact preflight.  It accepts an immutable Native turn request and emits
only a validated Native turn result plus safe accounting facts; it cannot
expose prompts, provider payloads, credentials, paths, or raw output to the
controller, tests, receipts, exceptions, or manifests.

The adapter is not a generic model client.  Model/provider selection,
credential resolution, process ownership, deadline, output cap, cancellation,
and finite budget remain operator-owned injected capabilities.  No manifest,
catalog, or package gains executable paths, mutable configuration, or a secret
reference.

### Bounded authority and reconciliation

Implement the 3.2b path completely, but make model execution unreachable
unless a separately approved finite reservation is supplied at invocation.
The reservation fixes the provider/model identity, maximum turns, token/cost
cap, deadline, one owned process tree, and one terminal outcome.  Invalid or
missing private configuration is `External-limited` before process start and
renders no secret.

The private receipt contains only digests, terminal state, bounded usage, and
boolean causal assertions.  Its public reduction verifies one reservation,
one terminal result, exact identities, no duplicate actions, no unexplained
gaps, and redaction sentinels.  Any missing, conflicting, or uncertain fact is
non-promotable and must not retry under that reservation.

## Differential evidence and promotion

Each Native scenario has an explicit mapping to its existing
`prime-parity.*` oracle scenario.  The differential harness validates the
pinned source, artifact, and module locks before comparison and compares only
canonical public projections.  It records provider, model, credential,
network, application, and upload counters separately.

The phase verifier emits an exact public JSON receipt containing selected,
provider-free-passed, bounded-passed, uncertain, and promoted feature IDs,
the common/differential/recovery scenario counts, and all external counters.
Promotion requires all eleven exact rows, source identity locks, zero public
redaction violations, and a complete bounded receipt for the two bounded rows.
Until then the ledger remains Native `Verified-loop: Missing` and all unproved
rows remain Missing.

## Verification boundaries

Provider-free commands are mandatory and must remain safe in `make check`,
`make promotion-check`, `list`, `describe`, and acceptance:

1. focused Native session/RLM/operation unit and conformance suites;
2. Native-versus-Prime provider-free differential scenarios for the nine
   provider-free rows;
3. failure, restart, cancellation, immutability, identity, ordering, and
   sentinel-redaction matrices; and
4. the exact Native 3.2 public receipt/reducer.

The bounded command is a separately invoked operator action, never a Makefile
or promotion side effect.  Immediately before it can execute a model turn, the
operator must provide a new explicit finite-budget authorization.  Its result
may close only the two bounded rows; it cannot grant authority for subsequent
runs or later phases.

Native `Verified-loop` is promoted only after both the provider-free and the
authorized bounded receipts pass on the same candidate.  `make check`,
`make promotion-check`, `git diff --check`, and the exact Native parity checker
then provide the final phase closure evidence.

## Non-goals

- No real provider/model call during design, implementation, ordinary tests,
  or provider-free verification.
- No reuse of Prime Gateway execution as evidence of Native behavior.
- No generic framework dependency on DCI, Prime source, test fixtures, or an
  adjacent repository.
- No claim that the eleven rows, Native `Verified-loop`, or full 61-row Native
  parity has passed until the stated evidence requirements are met.
