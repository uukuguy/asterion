# Asterion Prime Client Interfaces Design

> Approved direction: add one provider-neutral client-session projection above
> `ControlHost`. Every SDK, transport, interactive view, and export surface
> consumes the same validated public event stream and the same authority-scoped
> private-value service.

## Context

Prime system parity is closed through `ecosystem.capabilities`. The next exact
domain contains fifteen missing features. H-035 covers only these nine client
interfaces:

- `interface.sdk`
- `interface.cli-interactive`
- `interface.rpc`
- `interface.acp`
- `interface.json-stream`
- `interface.headless-print`
- `interface.tui-commands`
- `interface.tui-extension-ui`
- `interface.export-share`

The remaining six `operation.*` features belong to a later operational package.
No client-interface evidence may promote them, `Verified-system-parity`, or any
Asterion-native result.

Asterion already has the provider-neutral `ControlHost`, a replayable
`ControlPlaneClient`, closed control and runtime contracts, cross-language
validators, host-owned private stores, public-safe evidence projections, and a
generic one-shot application CLI. It does not have a shared session-client
contract or functional RPC, ACP, interactive, TUI, or sharing adapters above
the control host.

Prime source evidence is pinned to commit
`a18809e00ea30638584d87b3afea7285a9d7296c` and the exact files already named in
the parity ledger: `core/sdk.ts`, `cli-main.ts`, `modes/rpc/`, `modes/acp/`,
`modes/print-mode.ts`, `core/slash-commands.ts`, and `core/export-html/`.

## Goals

- Make all nine client features functionally reachable through Asterion.
- Preserve Python ownership of orchestration, authority, admission, canonical
  state, application execution, and client-session projection.
- Give every client the same ordered, replayable, validated public event stream.
- Keep message bodies, prompts, answers, tool arguments/results, provider
  payloads, credentials, and private paths behind an explicit private-value
  capability.
- Keep SDK, RPC, ACP, JSONL, CLI, headless, TUI, extension UI, export, and share
  as adapters and views rather than alternate runners or composers.
- Produce four exact provider-free evidence packages that reduce mechanically
  to the nine parity rows.

## Non-goals

- No change to the closed `asterion.agent-control/v1` or
  `asterion.agent-runtime/v1` contracts.
- No second control provider, runner, composer, catalog, or implementation
  resolver.
- No pixel-identical TUI comparison.
- No auth, model selection, settings/keybindings, telemetry/usage, doctor, or
  update/restart implementation.
- No provider/model operation, credential read, external share upload, or full
  dataset run in this package.
- No Asterion-native parity claim.

## Considered approaches

### Selected: one client-session projection above `ControlHost`

Introduce a new closed `asterion.agent-client/v1` contract. Python projects
canonical host state, journaled control events, and application result
identities into one body-free stream. A host-owned private-value service
resolves referenced content only for an explicitly authorized client session.
All client surfaces are codecs or views over this pair.

This preserves dependency direction, makes replay and redaction uniform, and
allows the same conformance scenarios to run through Prime Gateway and the
future native provider.

### Rejected: expose control and runtime streams separately

This would add less code initially, but every client would need to correlate
two independently sequenced streams, recover partial delivery, reconcile
terminal states, and independently decide which runtime values are private.
Those duplicated decisions would make clients disagree and weaken redaction.

### Rejected: wrap Prime's native SDK and modes directly

This is the shortest route to a visual demo, but it gives each Prime mode a
path around Asterion authority, journal identity, private projection, and exact
application execution. It also cannot serve as a common oracle for the future
native provider.

## Architecture

```text
SDK / JSONL / RPC / ACP / CLI / headless / TUI / export-share
                         |
                 client adapter/view
                         |
            Asterion client-session endpoint
             |                           |
 validated public event stream   private-value service
             |                           |
       host projector               host authority
             |                           |
          ControlHost + canonical journal/state
                         |
                  selected provider
                         |
       exact applications -> runner -> runtime/services
```

The client endpoint is host-owned. It accepts client intents, performs
pre-execution validation and authority checks, and delegates accepted session
operations to the existing `ControlHost`. Provider adapters never construct
client responses directly.

## New client contract

`asterion.agent-client/v1` is separate from the closed control and runtime v1
contracts. Its canonical schema, Python types/validator, TypeScript
types/validator, and valid/invalid fixtures must agree exactly.

The contract has three immutable values:

- `ClientIntent`: a client-generated idempotent request with exact session,
  client, authority-revision, and intent identity.
- `ClientEvent`: one body-free event in a single session generation with a
  contiguous sequence and unique event ID.
- `ClientCursor`: the exact session generation and last accepted sequence used
  for replay.

The event vocabulary must be the minimum functional projection needed by the
nine interfaces. It includes session state, message availability, tool
lifecycle, usage, artifact availability, command-registry revision, extension
UI requests, export/share receipts, recoverable faults, and one terminal event.
Private bodies appear only as opaque references plus safe media type, size, and
digest metadata where required. They never appear in the public event payload.

Client intents cover session input, session lifecycle, functional command
invocation, extension UI response, export request, and share request. An intent
describes requested behavior; it does not grant authority. The host either
journals one accepted resolution or rejects it before provider/application
work.

## Shared stream invariants

- One session ID and generation per stream.
- Contiguous sequences, unique event IDs, and deterministic replay after an
  exact cursor.
- One terminal event and no post-terminal events.
- Tool calls and results remain matched even when their bodies are private.
- Message, tool, artifact, and UI references are session-scoped and immutable.
- Duplicate intent IDs are idempotent; conflicting reuse fails closed.
- Unknown event/intent fields, identities, media types, cursors, and protocol
  versions fail before any external effect.
- A slow client receives bounded backpressure or an explicit replay-required
  fault; the host never silently drops or reorders events.
- Adapters validate the stream at their boundary and do not reinterpret
  provider-native events.

## Private-value service

The private-value service is a narrow host protocol, not a manifest authority.
It resolves one exact immutable reference for one admitted client session and
purpose. Supported purposes are interactive rendering, headless final output,
extension UI response, and explicitly authorized private export.

Every resolution binds:

- client and session identities;
- authority revision;
- reference kind, digest, media type, and maximum size;
- one declared purpose;
- cancellation and deadline.

The service returns bytes or text only to the authenticated in-process or local
transport endpoint. Public logs, errors, evidence, receipts, and export/share
defaults contain references and digests, never bodies or private paths.
Reference absence, replacement, digest drift, excessive size, wrong purpose,
or stale authority fails closed.

## Client surfaces

### SDK and JSON stream

The SDK is the only programmatic client core. It submits validated intents,
iterates validated client events, replays from a cursor, and resolves private
values through an injected capability. It cannot construct a provider or run
an application itself.

JSONL is a bounded LF-only framing codec over SDK intents and events. It has
maximum line and nesting limits, rejects partial terminal lines and unknown
fields, writes no diagnostics to its data stream, and closes on framing or
validation failure.

### RPC and ACP

RPC maps request IDs to SDK intent IDs and emits the same client events without
provider-native payloads. Responses acknowledge admission or rejection; long
running results remain events and private references.

ACP is a semantic codec over the same SDK. Session, message, tool, usage,
artifact, cancellation, and terminal transitions map from validated client
events. Unsupported ACP requests fail explicitly. ACP stdout remains
machine-owned and cannot contain logs or private values outside the protocol.

### Interactive CLI, headless, TUI, and extension UI

Interactive CLI and TUI are views over one SDK session. Functional commands
come from one host-projected command registry with a monotonic revision. The
TUI may choose layout locally, but command availability, accessible text,
state transitions, cancellation, and failures are shared and testable.

Headless mode consumes the same stream until its terminal event. Text mode may
resolve only the final admitted message reference; JSON mode emits the public
event stream and leaves private bodies referenced unless an explicit private
output option and authority are supplied.

Extension UI requests are host-projected, typed requests with a deadline and
opaque request reference. The client validates the supported method, gathers a
response, stores any body privately, and submits a reference. Detach,
cancellation, timeout, or unsupported methods produce one deterministic
cancelled/rejected response.

### Export and share

Public export serializes a complete validated public stream plus safe artifact
metadata. It is the default and requires no access to private bodies.

Private export requires a one-use authority bound to session generation,
covered sequence, selected references, destination identity, media type, byte
limit, and expiry. The host export service writes the artifact and returns only
an artifact ID, digest, media type, and opaque storage reference.

Share is a separate injected host service. Without an explicitly configured
service and one-use authority, it can only return a local export reference. It
never infers upload permission from settings, credentials, caches, or prior
exports.

## Evidence packages

H-035 fixes the following four evidence package boundaries for the detailed
implementation plan:

| Evidence command ID | Features | Required proof |
|---|---|---|
| `test.prime-client-core.provider-free` | `interface.sdk`, `interface.json-stream` | Shared intent/event validation, replay, framing limits, private reference enforcement |
| `test.prime-client-protocols.provider-free` | `interface.rpc`, `interface.acp` | Exact codec mappings, stdout purity, cancellation, unsupported-request rejection |
| `test.prime-client-interactive.provider-free` | `interface.cli-interactive`, `interface.headless-print`, `interface.tui-commands`, `interface.tui-extension-ui` | One command registry, functional state transitions, accessible content, UI timeout/cancellation |
| `test.prime-client-export-share.provider-free` | `interface.export-share` | Public-safe default, explicit private authority, immutable artifact/share receipt |

Each package emits one canonical receipt for the pinned Prime identity. The
receipt records its exact feature and scenario IDs, client protocol identity,
stream digest, private-service contract digest, artifact/module locks, process
counts, provider-operation counts, credential-read counts, retained-process
counts, and redaction result. It contains no source path, command, credential,
body, raw output, or private destination.

The domain reducer accepts exactly these four receipts, rejects unexpected keys
or identities, and promotes only the nine Prime Gateway rows when every receipt
passes. All nine native rows remain `missing`.

## Failure and cancellation

The endpoint rejects before provider/application work on invalid protocol,
identity, cursor, authority revision, command revision, private reference,
destination, media type, line size, nesting depth, or unsupported operation.

After admission:

- transport disconnect detaches the view but does not implicitly cancel the
  session;
- explicit cancellation flows through `ControlHost` and produces one terminal
  event;
- uncertain external effects use the existing journal reconciliation path;
- private-value or export failures do not expose bodies in errors;
- extension UI timeout submits one deterministic cancellation response;
- adapter shutdown releases listeners and owned local resources without
  terminating operator-owned services.

## Verification strategy

Implementation uses test-driven development and provider-free fakes before the
pinned real Prime process. Shared fixtures are consumed by Python and
TypeScript validators. Tests cover:

- valid and invalid closed-contract fixtures;
- immutability, exact identities, deterministic replay, duplicate intent
  handling, cursor gaps, terminal ordering, and backpressure;
- matched tool lifecycle and reference scoping;
- framing caps, partial lines, stdout contamination, and disconnects;
- command-registry revisions and functional TUI state transitions;
- extension UI validation, timeout, detach, and cancellation;
- public export redaction and private export/share authority;
- sentinel secrets across events, errors, receipts, artifacts, and logs;
- zero provider/model operations and zero credential reads;
- exact reduction from four receipts to nine passing Prime Gateway results,
  with native results and later operational features unchanged.

The detailed plan must include the exact focused commands plus `make test`,
`make lint`, `make docs-check`, `make check`, and `make promotion-check` before
the H-035 closure cycle advances.

## Compatibility and rollout

The client protocol starts at v1 and is additive to existing distribution
surfaces. Existing generic `asterion run` behavior remains unchanged. New CLI
commands must require explicit client/control selection and must not change
`list`, `describe`, `verify`, or one-shot application execution.

Prime-specific transport details stay private to Prime Gateway. The future
native provider must pass the same client scenarios without changing client
adapters. Pinned/next-build compatibility remains a separate later gate with
exact artifact locks and reviewed difference records.

## Approved implementation boundary

This design authorizes writing the detailed client-interface implementation
plan after specification review. It does not itself authorize implementation,
provider/model operations, external share uploads, operational-feature work,
or any broader parity claim.
