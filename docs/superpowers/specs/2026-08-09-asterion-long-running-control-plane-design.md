# Asterion Long-Running Control Plane Design

> Status: approved design baseline for implementation planning.
> Date: 2026-08-09.
> Prime parity baseline: vendored `3th-party/prime-agent` commit
> `a18809e00ea30638584d87b3afea7285a9d7296c`.

## Objective

Asterion will grow from deterministic capability-package application execution
into a framework for strongly controlled, long-running agents. It will support
two interchangeable control-plane providers:

1. a Prime Agent-managed provider delivered first; and
2. an Asterion-native kernel delivered afterward.

The first delivery target is a **verifiable long-running closure**: a durable
goal can autonomously plan and invoke authorized Asterion applications, use
recursive child agents, detach and reattach, checkpoint, recover from crashes,
respect budgets and cancellation, and expose an evidence-complete causal trace.

The final target is functional parity with the pinned Prime baseline. The
first target is an implementation milestone, not a reduction of final scope.

## Decisions

- Asterion owns a neutral, versioned long-running control-plane contract.
- Prime Gateway and the future native kernel implement that same contract.
- Prime is the first provider, not the definition of the public contract.
- The long-running control plane sits above existing application assemblies.
- A session receives an immutable portfolio of exact application assemblies.
- The control plane may autonomously orchestrate within the portfolio. It may
  only propose additions or changes outside it; the host must authorize them.
- Asterion owns portable semantic state. Each engine owns its opaque execution
  continuation state.
- Same-engine resume may restore the exact execution site. Cross-engine takeover
  resumes from an Asterion checkpoint and does not pretend to migrate Python
  memory, provider-internal state, or token-by-token dialogue.
- The Prime provider uses Prime's public RPC mode. Asterion does not bind to the
  private daemon protocol unless a separately reviewed, capability-gated gap
  makes that unavoidable.
- Full parity is measured against the pinned baseline. Upstream changes enter a
  parity-difference ledger and do not silently move the completion target.

## Alternatives Considered

### ACP-only integration

ACP is stable and portable, but its native surface is one session per
connection with prompt, stream and cancellation. Prime-only long-running
features are relegated to `_meta`, and heartbeat, schedules, messaging and
daemon lifecycle are not fully controllable. ACP remains an eventual client
interface, not the Prime provider boundary.

### Direct Prime daemon binding

The daemon exposes the whole Prime lifecycle, but direct coupling would make
Asterion depend on Prime command enumeration, schema revisions, socket layout,
worker ownership and restart behavior. This path is reserved for a proven RPC
gap and must remain isolated inside Prime Gateway.

### Neutral control plane with Prime Gateway

This is the selected approach. The additional protocol work is material, but it
is the only path that delivers Prime first without making the later native
kernel a second, incompatible architecture.

## Architecture

```text
CLI / operator host
  -> exact agent-system assembly
     -> control-plane provider selection
     -> immutable application portfolio
     -> policy and authority envelope
  -> Asterion Control Host
     -> canonical journal / admission / budget / checkpoint / Pathlight
     <-> asterion.agent-control/v1
         -> Prime Gateway -> public Prime RPC -> Prime daemon/workers/kernel
         OR
         -> Asterion Native Kernel
  -> admitted ActionProposal
     -> exact application assembly
     -> existing runner -> runtime -> capability implementations
```

The static plane defines what a session may do. The dynamic plane records what
it is doing. The execution plane performs one exact admitted action.

The control provider never directly grants itself authority. It produces an
action proposal. The Asterion host validates the proposal against the resolved
system plan, portfolio, policy, authority revision and remaining budgets before
invoking an application or another host operation.

## New Static Contracts

### `asterion.agent-system/v1`

An agent-system assembly is the static root for a long-running agent. Its closed
manifest contains:

- `system_id` and exact semantic `version`;
- one exact `control_plane_id@version`;
- a sorted, unique portfolio of exact application assembly references;
- exact declarative policy references;
- required host-service capability identifiers; and
- allowed control capabilities required from the selected provider.

It contains no prompt text, credentials, provider payloads, executable paths,
environment values, session state, mutable budgets or private storage roots.

### `asterion.control-plane/v1`

A control-plane manifest declares:

- exact provider identity and version;
- supported commands and emitted event families;
- supported long-running features;
- continuation-capsule media type;
- checkpoint format version; and
- compatibility identifiers required for exact resume.

Manifests describe compatibility. The host owns provider construction,
configuration, authority and storage.

### `asterion.agent-control/v1`

This is a closed bidirectional command/event contract. Every command has a
globally unique `command_id`, one `session_id`, and an expected authority
revision. Every event has one session ID, one generation, a contiguous sequence,
an event ID, a timestamp supplied by the host clock boundary, a type and a
validated payload.

The protocol is represented by canonical JSON Schemas, Python validation/types,
TypeScript validation/types, and sorted valid/invalid fixtures.

## Dynamic Entities

### System plan

The host resolves the agent-system assembly, application providers, capability
sources, control provider and host-service declarations before any engine work.
The resulting immutable plan is the only static authority source for a session.

### Authority envelope

The operator creates an authority envelope at session start. It contains:

- an opaque authority ID and monotonic revision;
- allowed portfolio members and operations;
- controller, application, child-agent and aggregate token/cost limits;
- wall-clock and action deadlines;
- maximum recursion depth and concurrent children;
- permitted execution-domain profile;
- host-service grants; and
- expiry and cancellation state.

Increasing or changing authority creates a new revision and a journal event.
Prior repository state, cache, configuration or engine state never grants
authority.

### Goal

A goal contains the operator-provided objective, optional completion contract,
budget binding and status. Its statuses are `active`, `paused`,
`needs_input`, `budget_limited`, `completed`, `failed` and `cancelled`.

Only an explicit engine completion proposal admitted by the host, or an explicit
operator action, may mark a goal completed. A stopped continuation, passed
partial gate, context compaction or exhausted budget is not completion.

### Task graph

The engine may create a dynamic task graph. A task references an exact portfolio
assembly and its declared input projection, dependencies, intended artifacts,
budget slice and completion expectation. The host assigns task identity and
records every state transition.

Task graph structure is portable semantic state. Engine-private scratch
reasoning and implementation objects are not.

### Action proposal

Every externally meaningful operation is represented as an action proposal.
Initial action kinds are:

- `application.invoke`;
- `child.spawn`, `child.message` and `child.cancel`;
- `checkpoint.create`;
- `goal.complete` and `goal.fail`;
- `input.request`; and
- `session.pause`.

Later parity phases add schedule, heartbeat, harness refinement, package and
integration actions without weakening the admission model.

Each proposal contains an action ID, idempotency key, exact target, declared
input projection, expected outputs, budget request and causal parent IDs. It
contains no credential or private provider payload.

## Commands and Events

Initial host-to-provider commands are:

- `session.create`;
- `session.attach` with an event cursor;
- `input.submit` with `direct`, `steer` or `follow_up` delivery;
- `session.pause`, `session.resume` and `session.cancel`;
- `checkpoint.request`; and
- `action.resolve` with `admitted`, `rejected`, `succeeded`, `failed`,
  `cancelled` or `uncertain` resolution.

Initial provider-to-host event families are:

- `session.*` and `goal.*`;
- safe `assistant.*` and `context.*` projections;
- `child.*` and `message.*`;
- `action.proposed`;
- `checkpoint.created`;
- `budget.*`; and
- `fault.*`.

RPC transport details, Prime daemon details and native in-process callbacks are
adapter-private and never appear in these DTOs.

## State Machines

### Session

```text
created -> running <-> paused
running -> checkpointing -> running
running -> recovery_required -> running | failed | cancelled
running | paused -> completed | failed | cancelled | budget_limited
```

`budget_limited` is resumable only under a new authority revision. A terminal
session emits exactly one terminal event. `recovery_required` is explicit and
must not be projected as ordinary running state.

### Action

```text
proposed -> admitted -> running -> succeeded | failed | cancelled | uncertain
proposed -> rejected
```

One proposal receives exactly one admission decision. One admitted action
receives exactly one execution terminal state. `uncertain` means an external
side effect might have occurred but no authoritative receipt proves its result.
An uncertain action is never retried automatically; reconciliation must prove a
terminal result or an operator must authorize a compensating/new action.

### Command idempotency

The host and provider persist command IDs before acknowledgement. Replaying an
accepted command returns or replays its original result. It never executes the
command twice. Prompt admission that cannot be classified as cancelled or
accepted becomes an explicit unknown/uncertain admission fault.

## Canonical Journal and Engine Capsules

Asterion's append-only canonical journal stores:

- system-plan and authority identities;
- goal and task transitions;
- commands, events and cursors;
- action proposals, admission decisions and receipts;
- budgets and usage projections;
- checkpoint records;
- artifact and Pathlight evidence references; and
- public safe fault projections.

The journal never stores raw prompts unless an explicit private storage policy
allows a separately protected transcript, provider payloads, credentials,
private model configuration, raw tool output or engine-local paths.

The selected provider stores an opaque continuation capsule. For Prime this may
include the JSONL session, kernel snapshot, child tree, harness state and Prime
session artifacts. Asterion records only:

- opaque capsule ID;
- control provider identity and exact implementation digest;
- capsule format version and digest;
- private storage service reference; and
- the canonical journal sequence the capsule covers.

Checkpoint creation first seals the canonical journal prefix, then records the
capsule binding. A checkpoint whose digest, engine identity or covered journal
sequence does not match is rejected before resume.

## Prime Gateway

Prime Gateway is a TypeScript sidecar implementing the Asterion control-plane
transport. It owns all Prime-specific translation.

### Process boundary

The gateway launches an exact, digest-verified Prime distribution in public RPC
mode. Prime RPC already uses daemon-backed coordination and exposes session
state, messages, schedules, heartbeats, observation and agent messaging. Prime
continues to own daemon and worker compatibility.

The gateway:

- sanitizes the environment and binds a private Prime agent/session root;
- verifies Prime version/digest and required RPC features before session work;
- maps RPC commands/events to `asterion.agent-control/v1`;
- tracks RPC request IDs, daemon active-session IDs and Asterion IDs separately;
- persists cursor and admission metadata needed for reconnect;
- converts Prime replay gaps into explicit resync evidence;
- redacts public projections; and
- never exposes Prime file paths or auth values through public events.

It may use a private daemon binding only for a documented RPC gap. Such use
requires exact Prime protocol capability negotiation, isolated adapter code and
old/new compatibility tests.

### Asterion Prime package

A versioned Asterion Prime package supplies a Python kernel skill named
`asterion_control`. It communicates with the gateway over an authenticated,
session-private local channel. Its model-facing operations include:

- inspect the authorized portfolio without secrets;
- propose an application invocation;
- inspect action status and safe results;
- request a checkpoint;
- inspect remaining budget; and
- propose goal completion.

The skill cannot authorize its own proposal. Gateway channel credentials and
socket paths are injected privately and excluded from public state.

Prime's persistent IPython, RLM children, goal, autonomous continuation,
compaction and messaging remain intact. Their external effects are confined by
the selected execution domain and Asterion admission boundary.

## Execution Domains

Prime and native kernels execute model-generated code. A process boundary is
not an OS security sandbox. The architecture therefore introduces an explicit
host-owned `execution.domain` service distinct from `executor.controlled`.

Two profiles are recognized:

- `trusted-local`: explicit operator authorization allows engine processes to
  use a bounded workspace with user-level OS permissions. Results must state
  that they are not sandbox-verified.
- `restricted`: the host launches controller, kernel and child processes in a
  separately enforced filesystem/network/process domain with scrubbed
  environment and resource limits.

`executor.controlled` remains direct command-policy enforcement and must not be
misrepresented as the restricted domain. Verified untrusted execution requires
the restricted profile; initial provider-free conformance may use temporary
trusted-local workspaces while stating that boundary.

## Asterion Native Kernel

The native provider is a separate implementation of the same control contract,
not a fork of application runners or capability composers. It owns:

- persistent controller session and context;
- programmatic Python control environment;
- provider/model turn execution;
- recursive child sessions and registry;
- queue, steer and follow-up delivery;
- compaction and context-tree navigation;
- goal and autonomous continuation policy;
- usage attribution;
- engine-local capsules and restart recovery; and
- later schedule, heartbeat, harness, integration and extension parity.

It uses existing Asterion runtimes and host services where their public
contracts fit. If long-running controller turns require a richer runtime
contract, that change is introduced explicitly; it is not hidden inside a
capability implementation.

Prime remains a differential behavior oracle throughout native development.
The native provider does not need matching internal data structures or
byte-identical transcripts, but must pass the same externally observable
conformance scenarios and invariants.

## Relationship to Existing Applications and Capabilities

Existing application assemblies remain exact, deterministic execution units.
They do not become mutable actors. A long-running task invokes one resolved
assembly under one action identity.

The control plane may:

- choose an existing portfolio assembly;
- provide its admitted input;
- consume its safe artifacts/events;
- decide what task follows; and
- run independent admitted tasks concurrently when the system policy permits.

It may not discover packages, install sources, select undeclared runtime
implementations, inject host services or expand authority. These are host
operations triggered only by explicit operator-approved plan revisions.

This preserves the value of capability packages while adding a strong,
long-horizon loop above them.

## Pathlight and Evidence

Pathlight extends from application-run tracing to the complete causal chain:

```text
system -> session -> goal -> task -> action proposal -> admission
       -> application run -> runtime/model/tool -> artifact/evaluation
       -> checkpoint/continuation/terminal decision
```

Every node carries safe identities and causal parent references. Private
controller prompts, provider requests, raw tool output and capsules stay in the
private evidence channel. Public traces expose verified shapes, counts, digests,
statuses and gap declarations.

Provider disconnects, event gaps, snapshot resync, rejected proposals,
budget-limited states, uncertain actions and recovery attempts are first-class
evidence. Observability failure must not change execution results, but missing
required evidence prevents a parity or verified-loop claim.

## Error and Recovery Semantics

| Failure | Required result | Forbidden result |
|---|---|---|
| Invalid system/portfolio/provider combination | preflight rejection before engine start | implicit fallback |
| Prime version or required RPC feature absent | gateway capability mismatch | sending unsupported commands |
| Provider authentication stale | `needs_input` / safe auth fault | retry loop or credential exposure |
| Engine disconnect with complete cursor replay | reconnect and replay | duplicate accepted command |
| Event gap | snapshot resync plus explicit gap evidence | invented contiguous history |
| Crash around external side effect | reconcile or `uncertain` | blind retry |
| Budget exhaustion | `budget_limited` | completed |
| Capsule corruption or mismatch | reject resume, preserve canonical checkpoint | partial restore and continuation |
| Root cancellation | cascade to active actions and descendants, one terminal state each | orphan child work |
| Public redaction failure | fail closed before publication | partial secret-bearing output |

Provider retry policy is limited to transport operations proven idempotent.
Application, tool and external side-effect retries require explicit policy and
idempotency evidence.

## Functional Parity Inventory

Functional parity is divided into domains. Pixel-identical TUI rendering and
identical hidden reasoning are not required; equivalent functionality must be
reachable through an Asterion-supported CLI, SDK or interactive client.

### Session and context

- persistent sessions and naming;
- resume and delete;
- conversation tree navigation;
- fork and clone;
- manual and automatic compaction;
- branch summaries and labels;
- queue, steer and follow-up delivery;
- context, token and usage status; and
- image and rich output attachments.

### Programmatic RLM

- persistent IPython-compatible control environment;
- model-generated program execution;
- exact child model selection;
- recursive child agents and depth limits;
- child registry, retention and deletion;
- direct parent/child/sibling messaging;
- child cancellation and parent teardown;
- child usage/cost attribution; and
- recoverable child state.

### Long-running operation

- daemon or equivalent resident workers;
- detach, attach and replay;
- persistent goals and explicit completion;
- bounded autonomous continuations and quality gates;
- user heartbeat;
- multiple agent-created heartbeats;
- one-time and cron schedules;
- restart/update recovery;
- worker residency/eviction; and
- orphan process cleanup.

### Continual harness

- local and global prompt entries;
- memory entries;
- reusable skill descriptions;
- subagent specifications;
- evidence-backed refinement;
- refinement history and snapshots;
- rollback; and
- isolation between local, global and project state.

### Capability ecosystem

- context-file loading;
- prompt templates;
- Markdown and Python skills;
- extensions and lifecycle events;
- registered/custom/overridden tools;
- extension state and commands;
- Prime/Asterion package install and resource selection;
- MCP integrations and credential refresh;
- custom providers and models; and
- deterministic collision diagnostics.

### Interfaces and operations

- SDK;
- CLI interactive mode;
- RPC, ACP and JSON event-stream clients;
- headless/print operation;
- interactive/TUI functional commands and extension UI requests;
- export and share;
- auth, model, thinking, service-tier and transport selection;
- settings and keybindings;
- telemetry/tracing and usage/cost reporting;
- diagnostics/doctor; and
- controlled update/restart.

## Completion Levels

### Implemented

The protocol, provider code and public entry point exist. This label makes no
behavioral claim.

### Verified-loop

The Prime provider proves the initial long-running closure through named
provider-free and bounded provider-backed commands. The evidence covers goal,
autonomous continuation, portfolio invocation, RLM child operation,
detach/attach, checkpoint, crash recovery, cancellation, budget enforcement,
redaction and Pathlight causality.

### Verified-system-parity

Every item in the pinned functional inventory is usable under the Asterion
control host through the Prime provider and has conformance evidence. A Prime
feature delegated to Prime still must obey Asterion identity, authority,
evidence and recovery boundaries.

### Verified-native-parity

The native provider passes every mandatory scenario and differential invariant
used for system parity. Missing domains remain explicit gaps; partial parity is
not promoted to this label.

External-limited, not-rerun, documentation mapping and narrow unit tests never
establish any verified level by themselves.

## Verification Strategy

### Schema and protocol

- valid/invalid fixtures for every closed contract;
- Python and TypeScript fixture agreement;
- canonical ordering and exact identity tests;
- command idempotency, sequence and one-terminal-event tests;
- immutable plan, authority and result tests; and
- public/private projection and sentinel-redaction tests.

### State-machine model tests

Generate command, fault and recovery sequences. Assert legal transitions,
single resolutions, budget monotonicity, cancellation propagation, no task
execution before admission and no automatic retry from uncertain state.

### Provider conformance

Prime Gateway and Native Kernel run the same provider-independent scenario
suite. Provider-specific adapters may add tests but cannot waive common cases.

### Differential tests

For each parity feature, run equivalent deterministic/fake-provider scenarios
against Prime and Native. Compare externally visible states, causal events,
artifacts, usage invariants and failures, not raw text or hidden reasoning.

### Fault injection

Kill or disconnect host, gateway, supervisor, worker, controller kernel and child
kernel at command admission, proposal admission, application start, side-effect
completion, receipt persistence, checkpoint sealing and event replay. Verify
recovery or honest uncertain state without duplicate effects.

### Long-running tests

- accelerated virtual-clock tests covering at least 24 hours of heartbeats,
  schedules, eviction and retries;
- provider-free real-process soak with detach/attach and repeated restarts;
- bounded provider-backed long run with a finite authority envelope; and
- resource cap and orphan-process audits after cancellation and shutdown.

### Upgrade compatibility

Test the pinned Prime build and at least the next accepted build with old/new
gateway combinations. An upstream build enters support only after RPC capability,
resume and event-mapping conformance passes.

## Delivery Phases

### Phase 0 — Control-plane foundation

Deliver the three new closed protocols, validators and fixtures; immutable
system resolution; authority envelopes; canonical journal; control-provider
registry; state-machine model; provider conformance harness; and safe evidence
projection.

Exit: a fake provider completes, pauses, resumes, faults and recovers a complete
session without runtime or provider access.

### Phase 1 — Prime verifiable long-running closure

Deliver Prime Gateway over public RPC, exact distribution binding, the Asterion
Prime package/skill, portfolio invocation bridge, Prime goal/autonomous/RLM
mapping, checkpoint/capsule storage, reconnect/replay/reconciliation,
Pathlight projection and bounded end-to-end verification.

Exit: `Verified-loop` evidence passes, including process fault injection. This
phase does not claim full Prime parity.

### Phase 2 — Prime system parity

Complete every pinned feature domain through Prime Gateway: full session tree,
compaction, message coordination, heartbeat/schedules, continual harness,
skills/extensions/packages/MCP, settings/model operations, interfaces,
diagnostics and update/restart.

Exit: the parity ledger contains no missing mandatory item and
`Verified-system-parity` passes.

### Phase 3 — Native long-running kernel

Implement the native controller, persistent program environment, recursive
agents, context/session tree, autonomous policy, recovery and core ecosystem
behind the same protocol. Use Prime differential conformance continuously.

Exit: the native provider satisfies `Verified-loop` and all foundational parity
domains.

### Phase 4 — Native full parity

Complete the remaining scheduling, continual harness, ecosystem, client and
operational domains.

Exit: `Verified-native-parity` passes against the pinned baseline. Only this
exit satisfies the full project objective.

## Cost and Risk

These are planning magnitudes, not delivery commitments. They assume an
experienced contributor familiar with the repository, reuse of Prime as a
differential oracle, no pixel-level UI rewrite, and no external sandbox product
implementation.

| Scope | One experienced engineer | Two-to-three-person team | Dominant uncertainty |
|---|---:|---:|---|
| Phase 0 | 4–7 weeks | 3–5 weeks | protocol and recovery abstraction |
| Phase 1 | 8–14 weeks | 5–9 weeks | RPC extension points and crash windows |
| Phase 2 | 3–6 months | 2–4 months | ecosystem and interface breadth |
| Phase 3 | 5–9 months | 3–6 months | kernel, recursion and consistency |
| Phase 4 | 3–7 months | 2–5 months | refinement governance and long-tail parity |

The schedule risk is high. Prime first reduces product risk and creates a live
oracle; it does not make the native implementation small.

Primary risks and mitigations:

- **Wrong neutral abstraction:** deliver a fake-provider model and Prime spike
  before freezing v1; use closed fixtures and explicit revisions afterward.
- **Prime upstream churn:** bind exact artifacts, prefer public RPC, maintain a
  parity-difference ledger and compatibility matrix.
- **Duplicate external effects:** persist command/action identities, use receipts,
  fail to uncertain and reconcile before retry.
- **Secret/private-state leakage:** separate public/private channels, use opaque
  references, sentinel tests and fail-closed publication.
- **Unbounded autonomy/cost:** immutable authority envelope, monotonic accounting,
  host-enforced deadlines and explicit budget-limited states.
- **Self-modifying harness drift:** append-only refinement history, proposal and
  approval policy, scoped stores, rollback and evaluation gates.
- **False parity:** fixed baseline inventory, named evidence and identical common
  provider scenarios.
- **OS permission exposure:** explicit execution-domain profiles and no sandbox
  claims for trusted-local runs.

## Compatibility

Existing capability, package, application assembly and agent-runtime v1
contracts remain valid. Long-running control adds new protocols above them.
Applications that do not select an agent-system assembly continue to execute as
before.

Python remains the owner of Asterion orchestration, system resolution and
canonical state. TypeScript validates shared control contracts and owns the
Prime Node integration. Rust continues to own controlled command execution;
any restricted execution-domain implementation is a separately declared host
service and must not be conflated with the current Rust executor.

## Design Acceptance Criteria

The design is ready for implementation planning when:

- control-plane ownership and provider interchangeability are explicit;
- the existing application/capability relationship is preserved and extended;
- authority, portable state and engine-private state have one owner each;
- session, action, uncertain-side-effect and checkpoint semantics are complete;
- the Prime public RPC boundary and package bridge are defined;
- native scope and differential behavior requirements are defined;
- full parity has a pinned, exhaustive functional inventory;
- failure, privacy, cost and long-running evidence requirements are testable;
- delivery phases do not redefine Phase 1 as final completion; and
- no placeholder or unresolved architecture choice remains.
