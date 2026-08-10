# Asterion Prime RLM and Messaging Parity Design

> Parent: `docs/superpowers/plans/2026-08-10-asterion-prime-system-parity.md`, Task 5.
>
> Prime baseline: `0.7.1`, source commit
> `a18809e00ea30638584d87b3afea7285a9d7296c`, daemon protocol 7, schema 14.

## Goal

Deliver the nine mandatory `rlm.programmatic` features through the selected
`asterion.prime-gateway` provider while preserving Asterion-owned authority,
budget, durable recovery, private data, and provider pluggability:

- `rlm.environment`, `rlm.generated-program`, `rlm.child-model`,
  `rlm.recursion-depth`, `rlm.registry-lifecycle`, `rlm.messaging`,
  `rlm.cancellation-teardown`, `rlm.usage-cost`, and `rlm.recovery`.

Six provider-free scenarios (`environment`, `messaging`, `registry-lifecycle`,
`cancellation-teardown`, `recovery`, and `usage-cost`) must run against a real
pinned Prime daemon with zero credential reads and zero model-provider
operations. `generated-program`, `child-model`, and `recursion-depth` remain
`external-limited` until the operator supplies a finite model authorization;
the implementation must still reject invalid model, budget, and depth requests
before effect.

## Baseline facts

Prime's persistent IPython kernel exposes `rlm.run` through
`AgentSession._createKernelHostHandlers()`. The handler invokes
`runRlmChild()`. Child creation reaches the public `SubagentRuntimeHost` only
at `AgentSession._createRlmSubagentRuntime(options)`, immediately before the
native daemon creates a `RlmSubagentRuntime`. The exact public options carry
the child ID, session name, prompt, selected model, depth, maximum depth,
parent node, tools and an `onSessionPublished` callback.

Prime also exposes the public `AgentSessionMessageController` contract. The
daemon supplies both controllers internally from `DaemonMode`; its daemon wire
does not allow an external client to set either. Consequently an ordinary
Gateway client or Prime extension cannot safely replace these controllers.

## Decision

Use a version-locked **daemon host shim**, not a replacement RLM engine and not
a patch to Prime's private `rlm.run` implementation.

The shim changes only the daemon binding that installs its existing native
`SubagentRuntimeHost` and `AgentSessionMessageController`. It wraps those
instances with an Asterion bridge and calls the original native implementation
only after an explicit Asterion admission succeeds. It therefore retains
Prime's own persistent kernel, child `AgentSession` objects, child registry,
transcripts, scheduling, and family message delivery.

The shim is an exact source hunk registered in Asterion packaging metadata. At
setup and daemon preflight, Asterion verifies the pinned Prime source commit,
the expected source hashes, exports and structural anchors. A drift, omitted
shim, duplicate shim, malformed discovery file, inaccessible socket, or any
unexpected bridge reply fails closed before a session is created. The patch is
not a general monkey patch: it calls only documented `SubagentRuntimeHost` and
`AgentSessionMessageController` interfaces and preserves the native host as a
private delegate.

Alternatives rejected:

1. Letting native `rlm.run` execute unwrapped loses Asterion's pre-effect
   authority boundary.
2. Reimplementing RLM in Asterion duplicates Prime kernel/session semantics
   and breaks hosted/native provider equivalence.
3. Replacing private `AgentSession` methods is wider, version-fragile, and
   less auditable than one binding-time wrapper.

## Bridge boundary

Create the private, closed Unix-socket protocol `asterion.prime-rlm-host/v1`.
It is daemon-local transport, never a manifest or public runtime protocol.
Each frame is authenticated with a random 32-byte token stored only in a
mode-0600 discovery record below the private Asterion agent directory. Frames
have a request ID, Asterion session ID, exact parent/child identity, current
authority revision, and a canonical request digest. The daemon accepts no
environment-provided command, credential, model configuration, or path from a
frame.

The bridge has these operations:

| Operation | Effect boundary | Result |
| --- | --- | --- |
| `rlm.spawn.propose` | Before native child creation | `admitted`, `rejected`, or `uncertain`; an admitted response contains only the canonical child binding. |
| `rlm.child.started` | After native child session publication | Binds Prime active/transcript identities privately to the admitted Asterion child. |
| `rlm.child.terminal` | After native child completion/cancellation/failure | Commits monotonic safe usage and terminal status before host acknowledgment. |
| `rlm.message.propose` | Before native family delivery | Admits/rejects one directional parent/child/sibling message. |
| `rlm.message.delivered` | After native receipt | Commits only opaque endpoint IDs, direction, mode, and message digest. |
| `rlm.child.delete` | Before native delete/teardown | Fences delete, cancellation, and retention transitions. |

The existing `asterion.skill-control/v1` stays unchanged. This bridge is used
only by the shim; the existing Python `asterion_control` skill continues to
serve explicit program-originated application/child/checkpoint/goal effects.

## Lifecycle and authority

```text
Prime kernel rlm.run
  -> shim canonicalizes immutable options
  -> rlm.spawn.propose
  -> Gateway records action.proposed
  -> Asterion RlmChildService validates parent, depth, model policy, budget
  -> action admitted | rejected | uncertain
  -> admitted: native SubagentRuntimeHost.createRlmSubagentRuntime
  -> rlm.child.started binds native identity
  -> Prime runs child and emits native family events
  -> rlm.child.terminal commits usage/status
```

`RlmChildService` is a host-owned lifecycle service, not a runner. It owns an
immutable `RlmChildBinding` with Asterion child ID, parent session ID,
authority ID/revision, parent generation, proposal digest, depth, selected
model selector digest, and native identities stored privately. Its durable
states are `proposed`, `admitted`, `started`, `completed`, `failed`,
`cancelled`, and `uncertain`; no state may regress. A crash after admission
but before `started`, or after a native effect but before a durable terminal
receipt, is `uncertain` and fences reuse of the child ID.

The service rejects before native effect when the child is not a direct bound
descendant, the requested depth exceeds the authority maximum, the selected
model is not exactly allowed, the budget does not fit the remaining parent
budget, a request digest conflicts with the same idempotency key, or the parent
is terminal/recovery-required. It reserves the child budget before admission,
attributes child usage monotonically at terminal, and releases only unused
reservation. It never obtains credentials or chooses a model.

The adapter must preserve Prime's native `onSessionPublished`, completion,
release, deletion and daemon teardown callbacks. Parent close, cancellation,
or deletion invokes the native delegate exactly once after Asterion's durable
fence. If native cleanup cannot be proven, the public state is `uncertain` and
the daemon does not claim no orphan exists.

## Messaging and privacy

The message wrapper delegates roster/name resolution to Prime, then proposes a
message with a private body reference and public SHA-256 digest. It permits
only Prime's native family reachability: parent, direct child, or sibling under
the same parent. The resulting receipt records distinct opaque sender,
receiver, parent, and child identities plus `delivered` or `queued`; it exposes
neither text, transcript path, Prime active ID, model/provider payload nor
environment value. Native terminal notices use the same wrapper.

The public RLM observations expose only sorted child IDs, closed status, depth,
safe token/cost counters, model-selector digest and message direction/digest.
Child prompts, generated source, kernel variables, session paths, model names,
provider output and credentials remain private.

## Exact evidence matrix

| Feature | Boundary | Required proof |
| --- | --- | --- |
| `rlm.environment` | real Prime provider-free | Kernel persists a harmless variable across turns; no provider operation. |
| `rlm.messaging` | real Prime provider-free | Parent→child, child→parent and sibling delivery retain distinct directional identities and body redaction. |
| `rlm.registry-lifecycle` | real Prime provider-free | Create, list, retain and delete exact child bindings; reject ambiguous/stale selectors. |
| `rlm.cancellation-teardown` | real Prime provider-free | Cancel and parent teardown leave no retained native child/process; uncertain cleanup fails closed. |
| `rlm.recovery` | real Prime provider-free | Restart after admission/started/terminal preserves binding or fences uncertainty. |
| `rlm.usage-cost` | real Prime provider-free | Monotonic zero/faux usage cannot regress or exceed reserved budget. |
| `rlm.generated-program`, `rlm.child-model`, `rlm.recursion-depth` | bounded provider | Exact model, recursion and finite-budget behavior; no PASS without named authorized run evidence. |

Every primary scenario carries its declared assertion and fault IDs from the
parity ledger and produces exactly one matching evidence record. A fake daemon
may test diagnostics but never produces evidence. The domain checker may PASS
only the provider-free six; the three bounded features stay visible as
`external-limited` without finite operator authorization.

## Verification

The implementation must add a named provider-free command that runs the
Python service/protocol tests, Gateway bridge tests, shim compatibility tests,
and a real pinned Prime daemon harness in a closed HOME. It must prove zero
credential reads, zero model-provider operations, no child processes after
normal teardown, cancellation and restart, exact source/patch lock, and
sentinel redaction. `make test`, `make lint`, `make docs-check`, Pyright,
TypeScript tests, Rust checks, build and promotion check remain required.

The Task 5 exit command is:

```bash
uv run python tools/check_prime_parity.py --domain rlm.programmatic --provider asterion.prime-gateway
```
