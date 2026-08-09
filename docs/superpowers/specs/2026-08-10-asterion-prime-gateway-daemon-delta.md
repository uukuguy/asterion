# Asterion Prime Gateway Daemon Boundary Design Delta

> Status: approved implementation refinement under the full-design authorization.
> Date: 2026-08-10.
> Prime baseline: `a18809e00ea30638584d87b3afea7285a9d7296c`.
> Package version: `@earendil-works/pi-coding-agent@0.7.1`.

## Why the baseline design needs this delta

The approved control-plane design preferred Prime's CLI RPC mode and reserved a
direct daemon binding for a demonstrated gap. Code inspection demonstrates that
gap. `src/modes/rpc/rpc-types.ts` exposes prompt, queue, state, compaction,
session editing, messaging, schedules and observation, but it exposes no
protocol greeting, schema revision, server capability set, resident-session
creation, detach/reattach lifecycle, resume cursor, command-result
acknowledgement, uncertain-mutation result or daemon restart checkpoint.

RPC mode is implemented on a client-owned daemon worker. EOF begins bounded
cleanup unless a schedule or heartbeat promotes the worker. It therefore cannot
be the authority for Asterion's required durable attach/recover semantics.

The pinned package root publicly exports `DaemonClient`,
`DaemonAgentConnection`, daemon command/event types, protocol constants and
`defaultDaemonSocketPath`. The source labels its JSONL socket the public local
protocol and provides the missing properties:

| Required property | Pinned Prime source |
|---|---|
| Exact negotiation | `DAEMON_PROTOCOL_VERSION = 7`, schema revision `14`, schema ID `protocol-7-schema-14-816309b1cd50` |
| Capability gate | `daemon_hello.serverCapabilities` plus per-command compatibility metadata |
| Durable lifecycle | `create` with `resident`, `attach`, `reattach`, `detach`, `kill` |
| Replay | generation-aware cursor and complete/partial/unavailable replay result |
| Idempotency | `clientId + commandId`, persisted mutation result and `ack_result` |
| Honest ambiguity | structured `command_result_uncertain` |
| Recovery | worker adoption/retry, `retry_worker`, snapshot resync and update-restart manifest |

The daemon architecture document still says protocol v4 while the pinned source
implements v7/schema 14. The gateway treats the pinned source constants and
runtime greeting as authoritative and records the documentation mismatch as a
compatibility risk; it never infers compatibility from prose or package version
alone.

## Decision

Phase 1 uses the daemon API exported from the Prime package root, isolated behind
the TypeScript Prime Gateway. It does not import Prime `src/` modules, read
worker descriptors, scan Prime storage, reproduce daemon logic in Python or
expose daemon DTOs in Asterion contracts.

Because the package is not registry-installable, the gateway implements only
the required JSONL envelope, correlation, acknowledgement and cursor rules from
that exported wire contract. Its locked DTO fixture is intentionally narrower
than Prime's full command union; unsupported commands cannot be sent.

Every Asterion root session receives a dedicated Prime daemon, agent directory
and socket below its private provider root. The gateway never attaches to the
operator's ordinary Prime daemon. This makes lifecycle, checkpoint and shutdown
operations session-scoped even though Prime's update-restart command is daemon
wide.

The package version is not published in the public npm registry: an exact
`npm view @earendil-works/pi-coding-agent@0.7.1` returns `E404`. Phase 1
therefore binds an operator-supplied source checkout rather than inventing a
registry dependency. Normal Asterion builds and tests do not import that
checkout. A separate setup/preflight path verifies the git commit when git
metadata is present, the locked `package-lock.json`, launcher, package metadata
and daemon protocol/client source digests, then uses `npm ci` and the source
launcher. It does not copy Prime into the Asterion wheel.

The gateway requires this exact handshake before session creation:

```text
protocol name       prime-agent.daemon
protocol version    7
schema revision     14
schema ID           protocol-7-schema-14-816309b1cd50
app version         0.7.1
capabilities        attach_snapshot, chunked_snapshot, event_sequence,
                    prompt_admission_cancellation, session_input_admission
```

It additionally verifies the locked source-artifact files and requires the
checkout to be clean when git metadata is present. A mismatch fails preflight
before Prime creates a worker or contacts a model.

## Gateway ownership boundary

```text
Python ControlHost
  <-> private Asterion gateway JSONL
      -> TypeScript Prime Gateway
          -> exported Prime DaemonClient
              -> dedicated Prime daemon v7
                  -> resident root worker and descendants
```

The Python/TypeScript sidecar transport is private adapter IPC. Public commands
and events remain exact `asterion.agent-control/v1` values; private goal/input
bodies may accompany a command only on this private pipe and are never copied
into the canonical journal, public errors or Pathlight.

Asterion session IDs, Asterion command IDs, gateway request IDs, Prime daemon
client IDs, Prime active-session IDs, Prime transcript session IDs, Prime event
generations and Asterion integer generations stay distinct. Only the private
gateway state store records their bindings.

## Controlled recursion delta

Prime's native `rlm.run` path checks its own depth and model availability but
has no public extension or daemon hook that can pause before child admission and
ask an external authority. Observing `rlm_child_update` occurs after admission
and can only support accounting or cancellation, not pre-execution authority.

Phase 1 therefore sets Prime's native RLM maximum depth to `0` and supplies the
Python-backed `asterion_control` skill. Its `spawn_child`, `message_child` and
`cancel_child` calls create ordinary Asterion action proposals over an
authenticated session-private socket. The Python host admits each action and a
host-owned child-session service launches a separately controlled Prime child
with a derived authority envelope. This preserves persistent programmatic
operation and recursive Prime work without allowing Prime to self-authorize
model spend.

Native Prime `rlm.run` remains a Phase 2 parity gap until either:

- Prime exposes a capability-negotiated pre-admission hook; or
- an isolated pinned patch is separately reviewed, versioned and differentially
  tested.

Phase 1 may claim controlled recursive Prime child work. It must not claim full
`rlm.programmatic` parity from that narrower path.

## Application bridge

The `asterion_control` skill requires caller-supplied idempotency keys for every
external effect. The gateway stores request bodies privately and emits only an
opaque `input_ref` in `action.proposed`. The host then:

1. journals and admits or rejects the proposal;
2. sends an `admitted` or `rejected` resolution;
3. runs an exact portfolio assembly only after admission;
4. journals the authoritative receipt and measured usage;
5. settles the reservation; and
6. sends one terminal `succeeded`, `failed`, `cancelled` or `uncertain`
   resolution.

The skill receives only safe receipt and artifact metadata. It never receives
host-service objects, credentials, private paths, raw provider payloads or
unapproved application output.

## Checkpoint and recovery

A session checkpoint waits for an input checkpoint and invokes Prime's
`prepare_update_restart` on the dedicated daemon. Prime atomically persists its
private restart manifest and stops the root worker tree. The gateway validates
the returned manifest, stores it only in the private capsule store, hashes the
canonical bytes, shuts down/relaunches the exact daemon build and reattaches to
the same active-session identity before emitting `checkpoint.created`.

The public checkpoint event contains only capsule/checkpoint IDs, exact engine
identity, digest, covered Asterion sequence and opaque storage reference. A
manifest body can contain configuration, prompts, paths and credentials and is
therefore never public evidence.

Recovery rules are:

- gateway restart reopens its durable Asterion event/command store and capsule;
- supervisor replacement reconnects with the same stable command envelope;
- worker recovery or Prime generation change emits `session.recovery-required`;
- complete Prime replay is reduced normally;
- unavailable replay requires a validated snapshot and starts a new Asterion
  generation after explicit recovery evidence;
- an accepted mutation without a durable result becomes `uncertain`; and
- no external action is retried without receipt reconciliation.

## Security and execution domain

Phase 1 supports `trusted-local` only unless an injected, separately verified
`execution.domain` service provides `restricted`. Prime's worker, IPython kernel
and model-generated code otherwise run with the OS user's permissions; neither
the process split nor the Rust controlled executor is described as a sandbox.

The gateway launches by direct argv with no shell, a scrubbed environment,
private `0700` roots and `0600` files. Socket and bridge tokens never appear in
argv, manifests, journal records, errors or public traces. The Prime child
receives bridge values only through its private launch environment.

## Cost and risk effect

This delta adds a narrow compatibility adapter and real-process tests, but
removes the much larger risk of inventing durable lifecycle semantics above an
invocation-local RPC stream. The residual high-risk areas are Prime API churn,
the stale daemon prose, checkpoint-wide worker stopping, same-user local socket
trust, and the temporary native-RLM parity gap.

The mitigation is exact artifact locking, a dedicated daemon per Asterion root,
capability negotiation, command/cursor persistence, source-backed compatibility
fixtures, sentinel redaction, and an explicit non-parity ledger entry for native
`rlm.run`.

## Acceptance conditions

This delta is implemented only when:

- gateway tests fail before any session work on every source digest,
  identity or capability drift;
- no Prime daemon type crosses the TypeScript gateway boundary;
- all daemon and bridge paths are private and absent from public projections;
- native `rlm.run` cannot start a child in Phase 1;
- an Asterion-managed Prime child is admitted before model execution;
- checkpoint/restart restores the exact root and child identities or fails
  closed;
- crash windows yield a receipt or honest `uncertain`; and
- the ledger distinguishes controlled recursive work from full RLM parity.
