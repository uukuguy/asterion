# Native Asterion Prime P1 Shared-Kernel Design

> Approved direction: implement the smallest reusable Asterion Prime kernel
> slice and prove it through a native `prime.ipython-coding@1.0.0` closed loop.

## Status and authority

This design follows the native reset established by
`2026-09-08-asterion-prime-native-p7-reset-design.md`. The wheel rooted at the
repository `pyproject.toml` remains authoritative. The historical
`prime-agent` P1 implementation is evidence and a behavioral reference only;
it is not an implementation dependency and cannot supply native acceptance.

The accepted product boundary is:

- `asterion.prime` is an Asterion-owned agent implementation;
- `AgentRuntimeClient` and `ControlPlaneClient` are orthogonal public surfaces
  over one product's private session semantics;
- Python owns orchestration, control, recovery, composition, and execution;
- Pi owns the provider-facing model/tool protocol;
- an injected operator service owns credentials, private content, worker
  creation, and finite live-run authority; and
- P1 is an application that consumes the kernel, not a second session engine.

## Goal

Deliver one installed native P1 application that performs two model-driven
IPython stages in the same persistent worker, executes one real context
compaction between them, cleanly reconstructs the controlling host attachment
and client from durable state inside the operator process, resumes without
replaying committed effects, satisfies the P1 oracle, emits only safe evidence,
and cleans up completely.

This delivery proves native P1 persistent coding, context compaction, and
control-side recovery. It does not prove Pi-process crash recovery, worker
crash recovery, P2 long-context quality, P4 full detach/attach semantics, child
agents, bounded autonomy, continual improvement, full Prime parity, or
production promotion.

## Rejected approaches

### P1-only runtime fork

Copying the P7 runtime binding and replacing its prompt would produce another
single-use application adapter. It would not establish reusable session,
context, or recovery semantics and would force later applications to repeat
the same work.

### Reuse the historical Prime Agent path

`src/asterion/applications/prime_agent/`, `prime.agent`, `prime.gateway`, the
Prime SDK, `3th-party/prime-agent`, its Docker gateway, and its development
receipts remain source-coupled legacy implementation. Importing, wrapping, or
relabeling them would violate the native reset and would not count as native
evidence.

### Full P4-grade recovery first

Recreating a lost Pi process or worker from transcript and checkpoint state
requires effect reconciliation and broader continuation semantics. That is a
separate P4 boundary. P1 recovery reconstructs the control host/client while
the provider-owned Prime session backend and restricted IPython worker remain
alive.

## Existing contracts retained unchanged

No closed v1 schema changes are required.

- `control.host.ControlPlaneClient` remains the asynchronous provider-neutral
  interface for command acceptance, cursor-based events, and close.
- `control.manager.ControlHost` remains the only control orchestrator. It owns
  persist-before-dispatch, reduction, authority, admitted actions, recovery,
  and public evidence projection.
- `control.session_context.SessionContextClient` remains the closed context
  operation extension. P1 uses only `session.describe`, `session.compact`, and
  `session.continuation.resume`.
- `control.session_context_manager.SessionContextManager` remains the owner of
  context-command identity, generation, revision, idempotence, budget
  reservation/settlement, cancellation, and uncertain fencing.
- `control.journal.FileCanonicalJournal` and
  `control.recovery.recover_control_host_state` remain the canonical host
  history and reducer.
- `runtime`, `assembly`, `packages`, `runner`, and `services` remain
  domain-neutral and must not import Prime applications.

The `control/providers/native/` implementation may be studied for durable
record and recovery patterns, but its controller, state, capsule, store types,
and exact `asterion.native` identity are not reused as Asterion Prime state.

## Architecture

```text
operator preset / host
  -> selected Asterion Prime control provider
  -> existing ControlHost + SessionContextManager
       -> canonical host journal and authority
       -> Asterion Prime ControlPlaneClient + SessionContextClient
                         |
                         v
             Asterion Prime persistent session backend
                         ^
                         |
installed native P1 application
  -> prime-applications provider and exact P1 assembly
  -> one asterion.prime runtime factory
  -> P1 runtime adapter consuming an injected narrow session service
  -> P1 oracle and safe receipt projector

persistent session backend
  -> reusable Pi RPC process/session
  -> injected restricted persistent IPython worker
  -> private transcript/summary/checkpoint store
```

The operator host owns `ControlHost`, the canonical journal, authority, and the
backend lifetime. The runtime never imports, constructs, or drives
`ControlHost`. The control adapter and runtime adapter are orthogonal clients
of one backend and never call each other.

The shared kernel is split into three narrowly owned parts. The backend extends
the existing implementation under `src/asterion/agents/prime/`; it does not
create a second session engine parallel to `AsterionPrimeSession`.

### Reusable Pi session lifecycle

`PiRpcSession` already exposes process-level `start`, `drive_prompt`, `send`,
`read_json_line`, `abort`, and `stop`, but its high-level `run` operation starts
and stops the process for one prompt. Add a reusable high-level lifecycle that:

- starts one exact preflighted Pi process once;
- drives multiple prompts sequentially against that same process;
- preserves monotonically validated native events and normalized usage per
  prompt;
- permits an explicit context-compaction request only through an already
  admitted backend operation and validates its terminal response;
- permits cancellation of the active request without making the session
  silently reusable after an uncertain terminal; and
- stops and reaps the process exactly once during final cleanup.

The reusable lifecycle is domain-neutral and lives under `runtimes/`. It knows
nothing about P1, ARC, Prime control commands, workers, or application oracles.
Existing one-shot `PiRpcSession.run()` behavior remains compatible for current
consumers.

### Asterion Prime persistent session backend

A new agent-private backend owns exactly one live Prime session generation.
It is separate from the public runtime adapter and survives closing and
reconstructing a control client. Its immutable identity binds:

- session ID and generation;
- selected provider, application, version, and runtime;
- exact Pi command and extension binding fingerprint;
- restricted worker identity;
- continuation ID;
- private-state root identity; and
- finite callback, tool, token, cost, and deadline ceilings.

The backend owns:

- the reusable Pi lifecycle;
- ordered private conversation entries;
- cumulative safe usage;
- one active command at a time;
- an idempotence table keyed by exact command identity and digest;
- durable public control events with contiguous sequence numbers;
- a compacted summary and its covered-prefix boundary;
- a checkpoint binding the public event cursor, private transcript digest,
  summary digest, worker identity, usage, and outstanding-effect status; and
- terminal cleanup.

Private prompt text, model responses, code, tool results, summary bodies,
credentials, provider payloads, paths, and environment values never enter the
canonical host journal or public events. Public values contain only canonical
identities, status codes, counts, media types, safe integer usage, and SHA-256
digests.

### Asterion Prime control adapter

Add a selected control provider whose ID is distinct from the historical
Prime Gateway provider. Its `ControlPlaneClient` delegates durable session
semantics to the persistent backend and implements `SessionContextClient` on
the same object, as required by `ControlHost`.

The client:

- binds one backend attachment generation; validates ordinary
  `ControlCommand` values against the session ID and authority revision; and
  validates generation on `SessionContextCommand`, `EventCursor`, and emitted
  `ControlEvent` values without adding fields to closed v1;
- persists acceptance in the backend before acknowledging it;
- treats an identical duplicate as idempotent and rejects a divergent
  duplicate;
- replays only the validated event suffix after an exact `EventCursor`;
- exposes `session.context-v1` in its control-plane manifest;
- executes `session.describe`, `session.compact`, and
  `session.continuation.resume` only after `SessionContextManager` admission;
- closes its attachment without closing the backend or worker; and
- has an explicit backend owner responsible for final teardown.

It does not authorize actions, choose applications or models, start arbitrary
services, retry provider calls, or persist canonical host authority.

## Context accounting and compaction

`PiRpcConfig.compact_events` is transport event redaction and is explicitly
not model context compaction.

The pinned Pi RPC `compact` response does not expose an immediate post-compact
context count, and its `get_session_stats.contextUsage` is null until another
assistant response. P1 therefore uses an exact provider-specific deterministic
rebuilt-context count; it does not claim a model-provider tokenizer count and
does not add a hidden model turn.

An application-owned Asterion Pi witness extension observes the public Pi
extension hooks. It imports Pi's public `buildSessionContext` operation to
rebuild the exact pre- and post-compaction message lists, then applies one
Asterion-owned deterministic counter to both lists. The counter covers text,
thinking, tool name plus canonical arguments, tool results, images, bash
execution, and compaction summaries under one closed versioned algorithm.
Python and TypeScript parity fixtures must produce the same counts. This count
is the provider-specific `session-context/v1` accounting unit; it is not
presented as a model tokenizer count.

Pi's `preparation.tokensBefore` uses a different usage-aware estimator. It is
validated and retained as a private native diagnostic only; it is never mixed
with the Asterion counter or projected as a receipt fact.

Pi owns the compaction summary request through its normal pinned provider
adapter and persists the resulting compaction entry. The witness extension is
observational: it never supplies a preset or custom summary and never invokes a
model. It reports the exact preparation and persisted-entry witnesses over a
preflighted private inherited-FD channel so Python can validate the admitted
operation without exposing summary content publicly.

The pinned Pi compact response does not expose the summary request's token or
cost usage. This delivery therefore charges the full admitted compact
reservation as a conservative accounting value. It does not claim that charge
is actual provider usage. Missing, malformed, duplicate, or uncertain compact
responses fence the context operation; no second provider adapter is created.

Before dispatch, preflight computes a worst-case bound for both Pi compaction
branches: the main summary and the optional split-turn prefix summary. Each
serialized summary input is capped at `4096` Asterion count units and each
summary output at `3276` tokens, so two requests fit below the `16000` token
reservation. The exact operator-resolved model price computes the worst-case
input/output cost, which must not exceed `125000` micro-units. Missing price
metadata, a larger input, or an excessive bound rejects compaction before Pi
mutation. Both possible requests also consume the global model-callback ceiling
and the same absolute `600000` millisecond run deadline.

| Receipt fact | Exact source and observation point |
|---|---|
| `covered_leaf_id` | SHA-256-bound `firstKeptEntryId` from the persisted `session_compact.compactionEntry` |
| `before_context_tokens` | Asterion counter over `buildSessionContext(pre_compact_branch).messages` at `session_before_compact` |
| `after_context_tokens` | Asterion counter over the Pi-rebuilt context represented by the pre-compact branch plus persisted compaction entry, observed after `session_compact` |
| `summary_sha256` | SHA-256 of the persisted `compactionEntry.summary`; the body remains private |
| `usage` | The fixed full compact reservation, charged once as conservative accounting rather than claimed actual provider usage |

Missing, malformed, mismatched, or cross-language-divergent counts fail the
operation; they are not replaced with zero or derived from raw summary length.
Automatic Pi compaction is disabled for this preset so all accepted compaction
flows through `SessionContextManager` admission. The admitted command causes
Pi to generate and persist a live summary for an exact covered prefix. The
backend stores the summary body privately and publishes only the existing
closed v1 receipt fields:

- `continuation_id`;
- `covered_leaf_id`;
- `before_context_tokens`;
- `after_context_tokens`;
- `summary_sha256`; and
- `usage`.

Successful compaction requires `after_context_tokens < before_context_tokens`,
an exact summary digest, usage within the admitted reservation, and a
persisted replacement boundary before the receipt is returned. The retained
suffix includes the P1 task contract and the references required to continue
using the same worker.

Compaction has three failure classes:

- rejection before Pi mutation leaves the previous continuation authoritative;
- a failure with positive proof that Pi did not mutate context also leaves the
  previous continuation authoritative; and
- any Pi mutation followed by missing, invalid, or unpersisted replacement
  evidence is `uncertain`, fences the attachment, emits
  `session.recovery-required`, and forbids continuation from the old
  checkpoint.

`session.describe` reports cumulative safe session usage, including the
conservative compact charge; `session.compact` reports the full reserved charge
for that operation. `SessionContextManager` settles it exactly once, and no
backend or projector settles it again. Evidence labels this value
`reservation-charged`, not observed provider usage.

## Control-side recovery boundary

P1 recovery is deliberately narrower than P4 and is named **clean control
attachment reconstruction**, not host-process crash recovery:

1. Stage one completes and its tool effect is committed.
2. The context operation completes and its replacement checkpoint is sealed.
3. The current `ControlHost` attachment and Asterion Prime client are closed
   cleanly inside the still-running operator process.
4. A new client attaches to the same live backend by exact identity.
5. A new `ControlHost` reconstructs its state from the existing canonical
   journal and requests events after the last committed cursor.
6. `session.continuation.resume` confirms the checkpoint transition.
7. Stage two runs without replaying stage one or the compact operation.

Recovery rejects identity, generation, worker, binding fingerprint, checkpoint
digest, journal prefix, or cursor mismatches before another model or tool
effect. A command that was started but cannot be proven committed is marked
uncertain and is never automatically replayed.

The live backend and worker survive the control attachment because their
lifetime is owned separately by the operator preset. No independent backend
daemon or cross-process IPC is introduced between the control attachment and
backend; the observational Pi-extension inherited-FD channel remains a private
operator service boundary. Operator-process exit, loss of the Pi process,
backend, or worker fails closed and is reported as outside this P1 recovery
boundary.

## Native P1 application

Migrate the exact public application index
`prime.ipython-coding__1.0.0` from the historical `prime_agent` provider to the
existing `prime-applications` provider. The native application has its own
exact assembly and capability package. The historical provider remains
selectable only through explicitly legacy surfaces; automatic selection by the
public application ID must neither load it nor become ambiguous. The assembly:

- selects runtime `asterion.prime`;
- requires the native P1 capability and `prime.tool.ipython`;
- declares only compatibility identities and host-service requirements;
- contains no prompt, command, path, credential, model, environment, mutable
  state, or provider configuration; and
- resolves exactly one executable implementation.

The P1 host integration is provider-owned and receives preflighted operator
services. It binds the persistent backend, Pi extension lease, restricted
worker, private stores, P1 task fixture, and oracle. The application runtime
uses the single `asterion.prime` factory binding. That factory dispatches by
exact application ID and version to separate P1 and P7 assembly functions and
projectors; registering two runtime bindings with the same runtime ID is
forbidden. P1 and P7 consume the same reusable Asterion Prime/Pi kernel.

### Fixed identities and limits

| Field | Exact value |
|---|---|
| Provider | `prime-applications` |
| Application | `prime.ipython-coding@1.0.0` |
| Capability package | `prime-ipython-coding-native@1.0.0` |
| Capability | `prime.ipython-coding@1.0.0` |
| Runtime | `asterion.prime` |
| Control plane | `asterion.prime-control@1.0.0` |
| Input preset | `fixed-small-verification` |
| Make target | `asterion-prime-p1-run` |
| Receipt media type | `application/vnd.asterion.prime.p1-native-receipt+json` |
| Deadline | `600000` milliseconds |
| Model callbacks | at most `8` |
| IPython tool callbacks | at most `4` |
| Aggregate tokens | at most `64000` |
| Cost | at most `500000` micro-units |
| Compact reservation | at most `16000` aggregate tokens and `125000` cost micro-units |
| Worker output | at most `65536` bytes per call |
| Pi automatic compaction | disabled |
| Pi compaction reserve | exactly `4096` tokens |
| Pi keep-recent window | exactly `256` tokens |
| Pre-compact prefix | pinned Pi `prepareCompaction` must expose non-empty `messagesToSummarize` or `turnPrefixMessages` |

The required host capabilities are exactly the sorted set
`prime.ipython`, `prime.p1-oracle`, `prime.pi-extension`,
`prime.private-trace`, and `prime.session-backend`. Provider/model identity is
resolved from existing operator configuration during preflight and is not a
manifest field or user-facing option.

The fixed small verification asks the model to perform two coding stages. Stage
one contains a setup turn and a verification turn. Provider preflight runs the
pinned Pi `prepareCompaction` algorithm with the exact settings and a
provider-free fixture proves that `messagesToSummarize` or
`turnPrefixMessages` is non-empty. The live `session_before_compact` witness
must prove the same condition. If the live prefix is still too short, the run
fails safely; it does not pad context, inject a summary, or skip compaction.

Stage one creates non-preseeded Python objects and a deterministic file inside
the persistent worker. After compaction and control reconstruction, stage two
inspects and uses those exact objects and bytes to produce the final result.
The operator oracle independently checks namespace identity, object identity
and behavior, working directory, file bytes, stage ordering, and absence of
seeded final code. It uses a narrow read-only worker snapshot/instrumentation
service after each committed stage; it neither injects a cell nor accepts the
model's self-report as evidence.

No manual cell injection, deterministic solution patch, fake broker, seeded
answer, seeded action sequence, or fixture PASS can satisfy acceptance.

## Result and evidence

The public runtime stream remains a valid `asterion.agent-runtime/v1` stream
with one run ID, contiguous sequences, matched tool calls/results, and one
terminal. Closed v1 has only `run.completed(status=completed|cancelled)` and
`run.failed(code,message)`. Budget exhaustion maps to `run.failed` with the
fixed safe code `p1_budget_limited`; uncertain recovery maps to `run.failed`
with `p1_recovery_required`. Neither introduces a new terminal or receipt
enum. The P1 projector may expose:

- `run.started`;
- bounded `usage.reported` events;
- one receipt artifact with a P1-native media type; and
- one completed, cancelled, or fixed-code failed terminal.

The receipt is digest-bound to the application, runtime, kernel generation,
worker, checkpoint, compact receipt, stage effects, oracle, and cleanup. It
contains no prompt, answer, source body, raw output, provider payload, worker
path, credential, or private store value.

The exact live command is one parameter-free operator preset. It accepts a
unique run ID for correlation but does not ask the user to select provider,
model, cost, token, or deadline values. Finite controls are internal. Missing
operator configuration or services fail during preflight without starting Pi
or the worker.

## Failure and cleanup rules

- All identity, assembly, service, authority, and lock mismatches fail before
  execution.
- Model/tool/context calls are sequential; no retry occurs inside the runtime,
  client, runner, or application.
- Cancellation stops the active request, records one terminal classification,
  and proceeds to cleanup.
- Storage tamper, event gaps, divergent duplicates, usage overflow, malformed
  compaction, or uncertain effects fail closed.
- Cleanup order is application resources, worker, Pi process, extension lease,
  private stores, then public terminal projection.
- Cleanup is idempotent and is attempted after success, failure, cancellation,
  and recovery rejection.
- Public errors use fixed categories and omit all sentinel private values.

## Verification contract

Implementation follows test-first red/green cycles. Tests stay proportional to
this research delivery and cover the essential boundaries rather than a full
release matrix.

### Provider-free tests

- reusable Pi lifecycle: two prompts share one process; usage and events remain
  ordered; cancellation and uncertain terminal prevent unsafe reuse;
- Prime backend: identity binding, idempotent acceptance, divergent duplicate
  rejection, exact cursor replay, single-writer ownership, and cleanup;
- context operations: exact pinned before/after accounting, counter parity,
  replacement digest, budget settlement once, pre-mutation failure preserving
  prior state, and post-mutation uncertainty fencing;
- recovery: reconstruct host/client from journal plus checkpoint; no command or
  tool replay; reject crossed identity, tampered checkpoint, event gap, and
  unresolved effect;
- native P1 metadata: metadata-only discovery, selected-only import, exact
  assembly/package/runtime binding, installed-wheel route, and absence of
  forbidden legacy imports; and
- redaction: sentinel prompt, answer, credential, provider payload, raw output,
  private path, environment value, and summary body absent from all public
  mappings, events, artifacts, exceptions, and representations.

### Bounded live acceptance

One authorized parameter-free preset must prove all of the following in a
single run:

1. installed `prime-applications` selects
   `prime.ipython-coding@1.0.0` and `asterion.prime`;
2. one real model-driven Pi session performs both stages;
3. one restricted IPython worker preserves namespace and file state;
4. one admitted real compact reduces the exact pinned rebuilt-context count and
   seals its summary replacement;
5. reconstructed control client/host resumes from the exact cursor and
   checkpoint without replay;
6. the independent P1 oracle passes;
7. safe usage remains within all finite limits and is settled exactly once;
8. one safe receipt artifact and one completed terminal are emitted; and
9. no Pi, worker, extension, socket, or temporary private-store residue remains.

Focused unit and installed-route commands run before the live preset. Full
`make check` and `make promotion-check` are required before declaring the
implementation integrated, but neither substitutes for the bounded live P1
acceptance. The live result remains development/unpromoted.

## Delivery sequence

1. Add reusable multi-prompt and compact operations to the common Pi lifecycle
   without changing existing one-shot behavior.
2. Implement the Asterion Prime persistent backend and provider-free recovery
   state.
3. Implement the Asterion Prime control/context client over the existing host
   contracts.
4. Add native P1 package, assembly, provider route, runtime projector, worker
   integration, oracle, and receipt.
5. Prove provider-free and installed-wheel boundaries.
6. Run the bounded native P1 preset under existing operator configuration.
7. Run integration gates, independently review the material contract/security
   changes, and record the exact evidence boundary.

## Compatibility impact

The four existing closed v1 contracts remain unchanged. Existing P7 and
one-shot Pi consumers retain their behavior. The native package and assembly
are additive, but the exact public application entry
`prime.ipython-coding__1.0.0` migrates from the historical provider to
`prime-applications`. Tests must prove metadata-only listing and automatic
selection do not import the historical provider. Historical `prime-agent` P1
may remain available only as explicitly legacy development evidence; it cannot
be selected by or imported into the native route.
