# Asterion Native Durable Controller Core Design

**Date:** 2026-08-30  
**Status:** Section design approved; pending final written-spec review  
**Program position:** Phase 3.1 of the Prime-equivalence program

## Objective

Build the first Asterion-native control-provider substrate: one durable,
single-session controller that implements the existing `ControlPlaneClient`
boundary, accepts host-owned authority and remaining-budget snapshots, drives a
deterministic provider-free turn, emits exactly replayable public control
events, checkpoints private continuation state, and recovers after process
crashes without duplicating commands, turns, actions, or terminal events.

This is not a journal-only repair and it is not a reduced project objective.
It is the Phase 3.1 foundation for reproducing the complete mandatory Prime
feature inventory through `asterion.native`. The final objective remains all 61
mandatory features passing at pinned Prime commit
`a18809e00ea30638584d87b3afea7285a9d7296c`, with zero blocking features and
only the two already reviewed exclusions.

## Existing Boundaries

The design preserves the repository dependency direction:

```text
CLI/host -> selected provider -> assembly -> catalog/composer
         -> exact implementations -> runner -> runtime/host services
```

The host continues to own:

- exact system and portfolio resolution;
- the canonical control journal and `ControlState`;
- authority, admission, reservation, settlement, and cancellation;
- application execution through existing runners;
- injected operation and host services; and
- public evidence and redaction.

The native provider owns only:

- its private controller session state;
- idempotent command acceptance;
- controller-turn lifecycle and policy state;
- its contiguous provider event stream;
- private continuation capsules; and
- provider-local restart recovery.

The native provider must not become another composer, runner, application
executor, authority ledger, scheduler, package catalog, or host-service
locator. It implements the same closed `asterion.agent-control/v1` and
`asterion.control-plane/v1` contracts already used by the Prime provider.

## Chosen Approach

Use a provider-private, event-sourced durable controller behind the existing
`ControlPlaneClient`. The controller keeps an append-only hash-chained session
journal separate from the host canonical journal, reduces that journal into an
immutable controller state, and exposes only already committed `ControlEvent`
objects.

This was selected over two alternatives:

1. **Snapshot-first controller storage.** Snapshots make current-state reads
   simple but obscure crash boundaries, command idempotency, and the difference
   between a completed turn and an acknowledged turn. They remain an optional
   cache, never the source of truth.
2. **Writing native state into the host canonical journal.** That would give
   the provider write access to host-authoritative facts, mix private engine
   state with public-safe records, and create competing ownership of one
   cursor. The journals must remain separate.

The private journal does not grant authority. It records what the provider has
accepted and produced; the host canonical journal remains the authoritative
record of what Asterion admitted, executed, settled, and published.

## Scope

Phase 3.1 includes:

- one exact native provider binding and manifest;
- one client bound to one root session and one generation;
- durable command idempotency;
- deterministic controller state reduction and replay;
- create, attach, detach, pause, resume, cancel, input, action resolution, and
  checkpoint commands from the existing closed protocol;
- deterministic provider-free turn execution;
- action proposal and host resolution closure;
- monotonic usage and host-supplied remaining-budget enforcement;
- private continuation capsules;
- exact event-cursor replay;
- process-crash recovery at named commit boundaries; and
- provider-free conformance, differential, redaction, and resource tests.

Phase 3.1 explicitly excludes:

- a real model/provider turn;
- model-generated Python or IPython execution;
- recursive children or child messaging;
- session/context trees, fork, clone, compaction, or rich attachments;
- steer/follow-up queues beyond durably accepting the existing delivery value;
- heartbeat, schedules, resident workers, or autonomous background loops;
- continual harness behavior;
- ecosystem installation, discovery, MCP, extensions, or custom providers;
- provider-specific SDK, CLI, TUI, auth, update, or telemetry implementations;
  and
- any `Verified-loop`, Phase 3 completion, or `Verified-native-parity` claim.

## Architecture

```text
ControlHost (authoritative)
  |- CanonicalJournal / ControlState
  |- AuthorityLedger / admission / budget validation
  |- existing runner and injected host services
  `- NativeControlPlaneClient
       `- NativeController
            |- NativeSessionStore
            |- NativeStateReducer
            |- NativeTurnAdapter
            `- NativeCapsuleStore
```

Dependencies within the provider remain one-way:

```text
factory
  -> client
      -> controller
          -> store
          -> reducer
          -> turn adapter
          -> capsule store
```

Neither the store nor reducer imports the host manager, runner, Prime
implementation, tests, or adjacent source trees. Prime is a differential
behavior oracle, not a native runtime dependency.

## Components

### Exact factory binding

The factory validates the exact native control-plane identity and version,
resolved system identity, authority envelope, private root, session identity,
and all closed string options before opening provider state. It selects one
explicit implementation; it does not scan directories or fall back to Prime.

The native manifest initially declares only behavior actually implemented by
this subproject. It uses the existing command and event vocabulary and a
native-specific continuation compatibility identity and checkpoint version.
Executable paths, prompts, provider configuration, credentials, environment
values, and mutable state never enter the manifest.

### `NativeControlPlaneClient`

The client is the protocol edge. It implements:

- `manifest`;
- `send(ControlCommand)`;
- `events(EventCursor | None)`; and
- `close()`.

It also implements the already supported optional host extension
`sync_authority_snapshot(RemainingBudget)`. The client serializes state
transitions, translates internal failures into provider transport failures,
and ensures `close()` releases resources without changing canonical session
state. It contains no action-execution or control-policy implementation.

### `NativeController`

The controller validates commands against the reduced provider state,
allocates stable turn and event identities, assigns contiguous event sequence
numbers, drives ready provider-free work to quiescence, and converts a closed
turn result into existing `ControlEvent` values.

It proposes actions but never admits or executes them. Only a host-delivered
`action.resolve` may advance an action after proposal. Only a terminal action
resolution may make the corresponding result available to a following turn.

### `NativeSessionStore`

The store provides compare-and-append, exact record-ID idempotency, position
and digest conflict detection, immutable replay, and exclusive single-writer
ownership. Its production implementation is a descriptor-relative segmented
append log under the provider private root.

```text
session-root/
  lock
  records/
    00000001-<digest>.record
    00000002-<digest>.record
    ...
  capsules/
```

Each record is written to an exclusively created private temporary file,
flushed, atomically renamed to its final position/digest name, and followed by
a directory durability barrier. Temporary files are not committed records.
Recovery requires exact contiguous positions, canonical encoding, a valid
previous-record digest, and a matching content digest. Missing positions,
duplicate positions, forks, noncanonical encodings, symlinks, replacements,
or interior corruption fail closed.

### `NativeStateReducer`

The reducer is a pure function from one completely validated journal prefix to
an immutable provider state. That state contains:

- provider, system, session, and generation identity;
- lifecycle and goal status;
- current authority revision and latest host remaining-budget snapshot;
- accepted command digests;
- pending, committed, and recovery-required turns;
- proposed and resolved action identities;
- monotonic provider usage;
- committed public events and the next sequence;
- latest checkpoint metadata; and
- the unique terminal identity, if present.

An in-memory snapshot may cache this result but never outranks replay. Replaying
the same valid prefix must return an equal frozen state without mutating input
records.

### `NativeTurnAdapter`

The first adapter is deterministic and provider-free. It accepts an immutable
controller snapshot, stable turn key, input references/digests, and an explicit
turn budget. It returns a closed `NativeTurnResult` containing only validated
directives, reference identities, public-safe projections, and usage.

The same stable turn key must produce the same canonical result and digest. The
adapter cannot access a runner, network, credential, package catalog, mutable
global state, or real model provider. Test scripts and fault injection are
injected through this interface; the production client exposes no `emit_*`
test methods.

A later real-provider adapter will use the same controller boundary but cannot
inherit deterministic retry semantics. Started-but-uncommitted real turns
require explicit reconciliation or honest uncertainty in a separate design.

### `NativeCapsuleStore`

The capsule store writes private, versioned continuation values before their
checkpoint event is committed. Journal and public records contain only capsule
identity, SHA-256 digest, provider/checkpoint versions, covered sequence,
covered journal position, and an opaque storage reference.

Capsules may contain private controller context, but prompts, user bodies,
provider payloads, credentials, raw application output, and absolute private
paths must never enter public events, host journals, exceptions, reprs, or
evidence projections.

## Private Journal Model

Every record has a stable record ID, kind, canonical closed payload, position,
previous digest, and digest. The initial record set is deliberately small.

### `session.bound`

Binds exact provider, system, session, generation, checkpoint version, and
initial authority identity. It is written once and cannot be revised.

### `authority.synced`

Records the latest host-authoritative `RemainingBudget`. Equal retries are
idempotent. The snapshot is only a provider throttle; it does not authorize an
action or replace the host `AuthorityLedger`.

### `command.committed`

Contains one complete validated public command and any immediate deterministic
events produced by accepting that command. Equal command-ID retries return the
existing record. A different command with the same ID conflicts without
changing state.

### `turn.started`

Contains a stable turn ID and idempotency key, authority revision, causal
command IDs, private input references and digests, adapter identity, and the
maximum turn budget. It contains no referenced private body.

### `turn.committed`

Atomically contains the canonical turn-result projection, exact usage, result
digest, and the complete ordered public event batch produced by the turn. No
event from the turn is visible before this record commits.

### `turn.recovery-required`

Fences a started turn whose result cannot be proven safe to reproduce. The
controller neither invents a result nor retries an effect. The deterministic
fake adapter normally resolves by recomputing the stable result and verifying
the same digest; future non-deterministic adapters require reconciliation.

### `checkpoint.committed`

Contains validated capsule metadata and the corresponding complete
`checkpoint.created` event. The capsule must already be durable and digest
verified. The journal remains the Phase 3.1 source of truth; the capsule is a
validated acceleration and migration boundary.

## Normal Data Flow

### Construction and recovery

1. The factory validates exact identities and opens only the journal derived
   from the configured session identity.
2. An empty store awaits the first `session.create`; a nonempty store is fully
   replayed and reduced.
3. Provider, system, session, generation, version, authority, and event cursor
   identities must agree.
4. Any invalid committed prefix makes provider construction unavailable. The
   provider never skips a committed record to manufacture a later state.

### Session creation

1. Validate the host command and its system/session/authority identities.
2. Commit `session.bound` if the store is empty.
3. Commit the command and its `session.created`, active `goal.updated`, and
   `session.running` events as one `command.committed` record.
4. Return from `send()` only after the durability barrier completes.

### Authority and budget synchronization

The host calls `sync_authority_snapshot()` before or after relevant command
and event processing. The native provider durably records a changed snapshot
and uses it to constrain future turns. Usage remains monotonic. If no admissible
turn budget remains, the controller does not invoke the adapter and commits the
current legal usage projection followed by the unique
`session.budget-limited` terminal event.

The provider may stop early based on the host snapshot. It may not infer that a
remaining budget grants portfolio access, operation access, host services, or
execution authority.

### Input and provider-free turn

1. `input.submit` is durably accepted without dereferencing or storing its
   private body.
2. `events(cursor)` drives ready work. It commits `turn.started` before calling
   the adapter.
3. The deterministic adapter returns one closed result.
4. The controller validates result identity, directives, usage, and budget.
5. Result, usage, and public events commit together in `turn.committed`.
6. `events()` yields only committed events, then returns when the controller is
   temporarily quiescent.

The iterator does not hold a filesystem lock across adapter awaits or event
yields. This permits `ControlHost` to process an `action.proposed` event and
reentrantly send its `action.resolve` command without deadlock.

### Action closure

```text
native turn -> action.proposed
            -> host AuthorityLedger admission
            -> action.resolve(admitted | rejected)
            -> existing host runner for admitted work
            -> action.resolve(terminal)
            -> next native turn
```

Each proposal, admission resolution, and terminal resolution is unique and
digest-bound. A conflict fails closed. The native provider never imports or
calls an application runner directly.

### Lifecycle commands

- `session.attach` validates the exact generation/cursor and enables suffix
  replay without creating replacement history.
- `session.detach` ends the current consumption relationship without deleting
  state or manufacturing a terminal event.
- `session.pause` commits `session.paused` and prevents new turns.
- `session.resume` resumes only a paused or recovery-required session and
  commits `session.running`.
- `session.cancel` prevents new turns and commits the unique
  `session.cancelled` terminal event.
- `close()` releases locks and descriptors without implicitly cancelling the
  session or mutating either journal.

### Checkpoint

1. Build a deterministic capsule from a committed provider position.
2. Write and durably sync the private capsule.
3. Reopen or otherwise verify its identity and digest.
4. Commit `checkpoint.committed` with the exact `checkpoint.created` event.
5. Expose the event only after the commit barrier.

Capsule corruption rejects that checkpoint. A complete journal remains
recoverable and is never overwritten by a corrupt capsule.

## Failure and Recovery Semantics

| Failure | Required result | Forbidden result |
|---|---|---|
| Same command ID, equal command | Exact idempotent acceptance | A second turn or event batch |
| Same command ID, different command | Reject with unchanged state | Last-writer-wins |
| Cursor ahead or generation mismatch | Reject replay | Empty or invented suffix |
| Temporary record at crash | Treat as uncommitted and retain for audit | Promote it to state |
| Missing/interior/corrupt committed record | Provider construction fails closed | Skip or truncate through corruption |
| Crash after command commit but before acknowledgement | Host retry observes the equal committed command | Duplicate command effects |
| Crash after `turn.started` but before fake result commit | Recompute under the same turn key and validate its digest | Allocate another turn |
| Invalid or over-budget fake result | Commit safe fault/recovery-required projection, not the result | Publish invalid usage or directives |
| Crash after turn commit but before event yield | Replay the committed event suffix | Re-run the turn |
| Capsule corrupt, journal complete | Reject capsule and recover from journal | Partial capsule restore |
| Terminal already committed | Preserve the one terminal event and allow replay only | State-changing commands or second terminal |
| Close transport failure | Report transport uncertainty | Manufacture session failure/cancellation |

A public redaction failure fails before publication. A provider observation or
capsule failure never converts an unproven action into success.

## Concurrency, Determinism, and Resource Limits

- One client binds one root session and one generation.
- A single-writer lock serializes durable provider transitions.
- No filesystem lock spans an adapter await or public event yield.
- Clocks, IDs, fake results, and fake usage are injectable and deterministic.
- Phase 3.1 has no background infinite loop; `events()` advances ready work to
  a bounded quiescent point.
- Each advance has explicit turn, event, record-size, capsule-size, and total
  private-storage limits.
- The private root and record/capsule files use restrictive operator-owned
  permissions and descriptor-relative, no-follow access.
- `close()` leaves no owned worker process. Phase 3.1 starts no provider,
  application, or model process.

## Verification Strategy

### Store and security matrices

Test append, equal retry, conflicting retry, reopen at every commit boundary,
temporary files, missing positions, reorder, fork, digest corruption,
noncanonical encoding, two-writer races, symlinks, root/file replacement,
permissions, resource caps, and durability barriers.

Sentinel prompts, credentials, provider payloads, private bodies, application
output, and absolute paths must be absent from public events, host journal
records, exceptions, reprs, and public evidence.

### Reducer model tests

Use `unittest` and `subTest` matrices for legal and illegal prefixes covering
create/running, input/turn/action resolution, pause/resume, detach/attach,
checkpoint, cancellation, completion, failure, budget limiting, authority
revision, usage monotonicity, and one-terminal invariants. Every valid prefix
must recover repeatedly to the same immutable state.

### Common provider conformance

Run the existing ten provider-independent behaviors against the production
native controller with injected deterministic test adapters:

- attach-replay;
- budget-limited;
- cancel;
- checkpoint;
- command-idempotency;
- complete;
- fault-recovery;
- input-delivery;
- pause-resume; and
- proposal-admission.

### Host integration

Use the real `ControlHost` and `AuthorityLedger` with a provider-free fake action
executor. Prove no execution before admission, exactly one admitted execution,
durable receipt-before-terminal ordering, zero executor calls for rejected,
cancelled, or budget-limited work, idempotent authority-snapshot delivery, and
no native path around the host runner.

### Real-process crash matrix

Run the native controller in an independent Python process and terminate it at
named boundaries around command commit/ack, turn start/adapter/result commit,
event yield, capsule write/checkpoint commit, and terminal commit/host receipt.
After every restart assert no duplicate turn, action, event, terminal, or owned
process and no promotion of uncommitted state.

### Prime differential subset

Compare only externally visible foundational behavior: lifecycle state order,
proposal/admission/terminal causality, replay, budget monotonicity, checkpoint
identity, and crash recovery. Do not compare hidden reasoning, raw text,
private journals, or byte-identical transcripts.

All Phase 3.1 verification is provider-free. Evidence must state zero provider,
model, credential, network, application, and upload operations.

## Phase 3.1 Completion and Claim Boundary

The subproject may record `native-controller-core: PASS` only when:

- the exact native binding, journal, reducer, client, fake turn, capsule, and
  recovery paths exist;
- all ten common scenarios pass;
- all named real-process crash windows pass;
- host authority, budget, admission, and exactly-once tests pass;
- redaction, permission, symlink, and resource-cap tests pass;
- `make test`, `make lint`, `make docs-check`, `make check`,
  `make promotion-check`, and `git diff --check` pass;
- promotion evidence reports zero provider and application operations; and
- the work is integrated on clean `main` with no leftover feature worktree or
  branch.

This PASS must not promote Native `Verified-loop`, Phase 3 completion, or
`Verified-native-parity`. No compound parity feature is promoted merely because
one prerequisite is present.

## Complete Prime-Equivalence Traceability

The authoritative scope source is
`tests/fixtures/prime-parity/v1/feature-index.json`. It contains 61 mandatory
feature IDs and two reviewed exclusions. Native tracking must consume that
exact set rather than maintain an independent hand-curated scope.

### Session and context — 9 mandatory features

- `session.persistence-naming`
- `session.resume-delete`
- `session.tree-navigation`
- `session.fork-clone`
- `session.compaction`
- `session.branch-summaries-labels`
- `session.delivery`
- `session.usage-status`
- `session.rich-attachments`

These are owned by future native context-tree, delivery-queue, attachment, and
compaction components built on this durable session/capsule substrate.

### Programmatic RLM — 9 mandatory features

- `rlm.environment`
- `rlm.generated-program`
- `rlm.child-model`
- `rlm.recursion-depth`
- `rlm.registry-lifecycle`
- `rlm.messaging`
- `rlm.cancellation-teardown`
- `rlm.usage-cost`
- `rlm.recovery`

These are owned by future controlled program-environment, real-turn adapter,
child registry, message bus, cancellation, usage, and recovery components. They
reuse existing host runners and controlled execution; they do not create a
second application runner.

### Long-running and operational behavior — 16 mandatory features

- `operation.goals`
- `operation.autonomous-quality`
- `operation.detach-attach-replay`
- `operation.heartbeat-user`
- `operation.heartbeat-agent`
- `operation.schedule-once-cron`
- `operation.resident-workers`
- `operation.worker-residency-eviction`
- `operation.restart-update-recovery`
- `operation.orphan-cleanup`
- `operation.auth`
- `operation.model-selection`
- `operation.settings-keybindings`
- `operation.telemetry-usage`
- `operation.doctor`
- `operation.controlled-update-restart`

Goals, replay, autonomous policy, residency, and recovery extend the native
controller. Heartbeat and schedules use host-injected clock and scheduler
services. Auth, settings, model selection, telemetry, diagnostics, and updates
remain explicit host operations; the native controller never reads credentials
or mutates installation state directly.

### Continual harness — 8 mandatory features

- `harness.prompt-entries`
- `harness.memory-entries`
- `harness.skill-descriptions`
- `harness.subagent-specifications`
- `harness.evidence-refinement`
- `harness.history-snapshots`
- `harness.rollback`
- `harness.scope-isolation`

These are owned by a future scoped, revisioned harness service with explicit
history, snapshot, rollback, and isolation semantics. Controller state may
reference harness revisions but cannot silently rewrite them.

### Ecosystem — 10 mandatory features

- `ecosystem.context-files`
- `ecosystem.prompt-templates`
- `ecosystem.skills`
- `ecosystem.extensions-lifecycle`
- `ecosystem.tools`
- `ecosystem.extension-state-commands`
- `ecosystem.packages`
- `ecosystem.mcp`
- `ecosystem.custom-providers-models`
- `ecosystem.collision-diagnostics`

Native parity reuses Asterion's exact catalog, package, materialization,
host-service, and credential-refresh boundaries. It must not add source
scanning, version ranges, hidden precedence, registries, or symlink traversal.

### Interfaces — 9 mandatory features

- `interface.sdk`
- `interface.cli-interactive`
- `interface.rpc`
- `interface.acp`
- `interface.json-stream`
- `interface.headless-print`
- `interface.tui-commands`
- `interface.tui-extension-ui`
- `interface.export-share`

These interfaces stay provider-neutral. Selecting `asterion.native` must make
the same functionality reachable without a parallel native-only SDK, CLI, RPC,
or TUI implementation.

The only exclusions are hidden-reasoning identity and pixel-identical TUI
rendering. Functional TUI commands and extension UI requests remain mandatory.

## Delivery Tranches to Full Native Parity

### Phase 3.1 — Durable controller core

Deliver this design. It supplies shared prerequisites but promotes no compound
parity row by itself.

### Phase 3.2 — Native `Verified-loop`

Target the first 11 foundational rows:

- session: persistence/naming, resume/delete, delivery, usage/status;
- RLM: environment, generated program, usage/cost, recovery; and
- operation: goals, detach/attach/replay, autonomous quality.

Add the real provider-turn adapter, bounded real-provider authority, and
uncertain reconciliation. Promote only rows with their own complete evidence.

### Phase 3.3 — Foundational native parity

Target the next 14 rows:

- remaining session tree/fork/compaction/summary/attachment rows;
- remaining child-model/recursion/registry/messaging/cancellation RLM rows; and
- resident workers, eviction, restart recovery, and orphan cleanup.

Phase 3 exits only after Native `Verified-loop` and these foundational domains
have their named evidence. Phase 3.1 completion alone is not a Phase 3 exit.

### Phase 4 — Remaining 36 rows

Generate the Phase 4 work from the exact remaining set:

- two heartbeat and one schedule row;
- six operational auth/model/settings/telemetry/doctor/update rows;
- eight continual-harness rows;
- ten ecosystem rows; and
- nine interface rows.

The generated tracking matrix records for every mandatory feature its owning
component, dependency tranche, provider-free scenario, any required bounded
provider scenario, crash/security/redaction requirements, evidence receipt,
and current state. Exact-set validation fails on a missing, extra, or renamed
mandatory ID. Partial behavior never promotes a complete row.

## Final Project Gate

The full project objective is complete only when the exact checker can report:

```text
provider = asterion.native
mandatory = 61
passed = 61
blocking = 0
excluded = 2
```

That result must also have common-provider conformance, Prime differential
evidence, real-process recovery, finite provider-backed evidence where
provider semantics are required, security/redaction review, `make check`, and
`make promotion-check`. Until then, status must continue to say that Prime
Gateway system parity is complete and Asterion-native full reproduction is not.

## Compatibility and Future Protocol Changes

Phase 3.1 does not change any closed public schema. If a later native domain
cannot be expressed through an existing contract, that change requires a
separate protocol design updating the canonical schema, Python types and
validator, TypeScript types and validator, and both valid and invalid fixtures.
Native implementation details must never silently widen a closed mapping.

The initial private journal and checkpoint versions are exact. Future private
format evolution requires explicit compatibility or migration handling; it
must never reinterpret an old capsule under a new provider/checkpoint identity.
