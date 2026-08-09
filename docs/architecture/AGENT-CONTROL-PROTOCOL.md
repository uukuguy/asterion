# Asterion Agent Control Protocol

## Purpose and current boundary

Asterion's long-running control layer coordinates durable agent sessions above
exact application assemblies. It has three closed versioned contracts:

- `asterion.agent-system/v1` resolves one control provider, one immutable
  application portfolio, declarative policies and required host capabilities;
- `asterion.control-plane/v1` declares an exact provider's commands, events,
  capabilities, checkpoint format and compatibility IDs; and
- `asterion.agent-control/v1` carries immutable host commands and provider
  events for one session generation.

Phase 0 establishes this provider-neutral foundation with an in-memory fake. It
does not start Prime, contact a model, invoke an application runtime, implement
opaque capsule storage, or establish `Verified-loop` or Prime parity.

## Placement and dependency direction

```text
operator / CLI
  -> resolved agent-system plan
     -> exact control-plane provider
     -> immutable authority envelope
  -> Python ControlHost
     -> canonical journal
     -> state reduction, admission and budgets
     <-> asterion.agent-control/v1
  -> admitted application action (post-Phase 0)
     -> exact application assembly -> runner -> runtime / host services
```

The control layer orchestrates applications but does not replace their
catalogs, composers, runners or runtimes. Framework control modules remain
domain-neutral and do not import DCI or Prime implementations.

## Ownership

| Concern | Owner | Provider may do | Provider must not do |
|---|---|---|---|
| Static composition | Asterion host | consume its resolved plan | discover packages, choose undeclared runtimes or expand the portfolio |
| Authority and policy | operator and Asterion host | bind proposals to the current revision | self-authorize or infer authority from configuration, cache or prior state |
| Portable session state | Asterion host | emit validated ordered facts | mutate canonical state directly |
| Engine continuation | selected provider | store an opaque compatible capsule | publish capsule bodies, paths or credentials |
| Application execution | Asterion host | propose one exact action | invoke an assembly before admission |
| Public evidence | Pathlight projection | emit fixed safe facts | publish prompts, answers, raw output, provider payloads or private references |

Python owns resolution, journal, state and admission. TypeScript validates the
same shared contracts and will own the Prime Node gateway. Rust remains the
controlled command-execution boundary; it is not an OS sandbox or the owner of
agent orchestration.

## Static resolution

System resolution is complete before provider construction. IDs and versions
are exact; portfolios and capability lists are sorted and unique. Missing
providers, applications, runtimes, capabilities or host services fail closed.
The immutable plan is compatibility input, not mutable execution authority.

Control-provider factories are selected by exact
`control_plane_id@version`. Their private root, credentials and configuration
are injected by the host and never appear in a manifest, plan representation or
public error.

## Commands and events

Every command carries one `command_id`, `session_id`, positive
`authority_revision`, closed type and type-specific payload. Phase 0 command
types are:

- `session.create`, `session.attach`, `session.pause`, `session.resume` and
  `session.cancel`;
- `input.submit` with exactly `direct`, `steer` or `follow_up` delivery;
- `checkpoint.request`; and
- `action.resolve`.

Every event carries one `event_id`, `session_id`, positive generation,
contiguous positive sequence, UTC timestamp, closed type and validated payload.
Phase 0 event types are:

- `session.created`, `session.running`, `session.paused`,
  `session.recovery-required`, `session.completed`, `session.failed`,
  `session.cancelled` and `session.budget-limited`;
- `goal.updated` and `action.proposed`;
- `checkpoint.created`, `budget.reported` and `fault.raised`.

A complete generation has one session identity, one generation, unique event
IDs, sequences `1..N`, and exactly one terminal event in final position.

## Authority, actions and budgets

An operator-owned `AuthorityEnvelope` fixes the allowed portfolio and
operations, execution domain, host-service grants, expiry, cancellation state,
recursion and child limits, action deadline, and controller/application/child/
aggregate token and cost limits. Replacements require a strictly newer,
compatible revision.

An `action.proposed` event includes an authority revision, idempotency key,
exact target, input reference, expected artifact types, causal parents and a
finite budget request. The host evaluates it without mutation, journals one
decision, reserves admitted budget once, updates canonical state and sends one
`action.resolve`. Rejection never contacts the application executor.

Phase 0 deliberately stops at admission: its injected `ActionExecutor` is not
called. Application execution and receipt settlement enter the Prime
verified-loop phase behind the same host-owned boundary.

## Canonical state and recovery

Session transitions are explicit:

```text
created -> running <-> paused
running -> recovery_required -> running | failed | cancelled
running | paused -> completed | failed | cancelled | budget_limited
```

Completion requires a completed goal and no active action. Failure and
budget-limited termination also require no active action. Cancellation closes
all non-terminal actions. A budget-limited state can reopen only as a new
generation under a strictly newer authority revision.

Action transitions are explicit:

```text
proposed -> admitted -> running -> succeeded | failed | cancelled | uncertain
proposed -> rejected
uncertain -> succeeded | failed | cancelled  (only with reconciliation receipt)
```

`uncertain` means an external effect may have occurred without an authoritative
receipt. It is never a retry instruction. Reconciliation must supply evidence,
or an operator must authorize a distinct compensating or replacement action.

## Journal ordering and idempotency

The canonical journal begins with exact system and authority bindings. The host
then persists a command before provider send and persists an event before state
reduction. Append uses compare-and-append positions. Replaying the same record
ID and digest returns its original entry; replaying the same ID with different
content fails closed.

Command/event IDs, provider generation/sequence and journal positions are
different identities. A transport failure after persistence is reported as
uncertain delivery; the host neither hides the accepted record nor invents a
provider event. Event gaps remain journal evidence and cannot synthesize state.

## Checkpoints and engine capsules

`checkpoint.created` exposes only opaque IDs, exact provider/checkpoint
versions, capsule digest, covered event sequence and an opaque storage
reference. The provider owns capsule format and contents; Asterion owns the
portable journal and compatibility checks. Phase 0 validates this public shape
but does not yet seal or restore real engine capsules.

## Public Pathlight evidence

The control host can project a public-safe causal graph rooted at `system` and
`session`, with fixed `goal`, `action`, `admission`, `checkpoint` and `fault`
facts. Published fields are fixed statuses, counts, generation/sequence/journal
positions, and SHA-256 digests of opaque identities, reasons and canonical
events. Payload bodies, goal references, private roots and provider error bodies
never enter the trace.

Pathlight is observational. Recorder or recorder-metadata failures cannot alter
the control result and instead add the fixed host snapshot gap
`control-pathlight-recording`. A required evidence gap prevents a later parity
claim.

## Phase 0 conformance and claims

The reusable fake-provider suite covers these stable scenario IDs:

```text
attach-replay
budget-limited
cancel
checkpoint
command-idempotency
complete
fault-recovery
input-delivery
pause-resume
proposal-admission
```

The suite is provider-free and deterministic. Prime Gateway and the native
kernel must later implement the same public client contract and pass the common
scenarios; provider-specific tests may add constraints but cannot waive them.

Use the current evidence ledger for exact command results and claim level:
[Prime Parity Ledger](../status/PRIME-PARITY-LEDGER.md). Phase 0 can prove only
`control-plane-foundation`; it cannot prove `Verified-loop`,
`Verified-system-parity`, `Verified-native-parity` or full Prime equivalence.
