# Prime Operation Host Callback Design

## Objective

Close the remaining Prime Gateway `Verified-system-parity` production gap
without changing Asterion's ownership boundaries.  The selected Prime factory
currently advertises `operations-v1` and binds a Python `PrimeOperationClient`,
while the production TypeScript descriptor path never constructs the
`PrimeOperationGateway` needed to handle `operation.execute`,
`operation.cancel`, or `operation.reconcile`.

The approved correction is one private, operator-owned callback path:

```text
Python PrimeOperationClient
  -> selected Node Prime sidecar
  -> fixed private Unix callback
  -> injected Python OperationManager
  -> exact preselected OperationService
  -> validated public-safe OperationReceipt
```

This design closes the selected-provider production assembly path.  It does
not add a second operation runner, move authority into Node, implement
Asterion-native parity, or broaden any public protocol.

## Approved Decision

Use option **1A**: the operator injects one already-selected generic operation
dispatcher per session, while the Prime provider owns only the callback
transport adapter and ties its lifecycle to that session's selected sidecar
process.

The dispatcher is the same host-owned `OperationManager` that already owns:

- authority evaluation and budget reservation;
- private request resolution and typed request storage;
- exact `feature_id` to `OperationService` binding;
- append-only operation journal records;
- idempotency, uncertain-state handling, cancellation, and reconciliation.

The Prime provider does not construct an `OperationManager`, discover an
operation service, inspect private request bodies, or choose behavior from a
request.  It validates an explicitly injected dispatcher before process
creation and constructs only a private transport server bound to the current
session identity.

## Rejected Alternatives

### Host-prestarted endpoint

Requiring the outer host to start a Prime-specific Unix server before calling
the synchronous provider factory would make root construction possible, but
would leave child-session identity and lifecycle binding underspecified.  A
single prestarted endpoint could be reused with the wrong session or authority;
a per-child endpoint would require asynchronous work inside a synchronous
factory boundary.

### Node-local operation implementation

Constructing feature-specific services or synthetic receipts in Node would
duplicate Python orchestration and authority, permit request-selected service
behavior, and violate the repository dependency direction.

### Withdrawing `operations-v1`

Removing the capability would make the production claim truthful but would
reopen the six mandatory operation parity rows.  It is a fallback only if the
approved callback cannot satisfy the closed architecture and verification
gates.

## Ownership and Dependency Direction

The dependency direction remains:

```text
operator host
  -> OperationManager + exact OperationService map
  -> selected Prime factory
  -> Prime callback transport + Node adapter
  -> validated receipt returned to the operator host
```

The generic operation interfaces stay under `src/asterion/operation/`.  The
Unix protocol, server, Node client, and sidecar lifecycle wrapper are
Prime-provider adapters under the existing Prime provider packages.  Generic
framework modules do not import DCI or Prime implementation details.

The injected service identity is `operation-dispatcher`.  It is a session-bound
managed host service, not a globally discoverable application service and not
a new `pyproject.toml` entry point.  A Prime system must declare and supply the
exact root-session instance through its operator-owned `host_services`; the
Prime factory independently fails closed when it is absent or malformed.

## Generic Dispatcher Contract

Add a narrow structural protocol for the already-authoritative dispatcher:

```python
class OperationDispatcher(Protocol):
    @property
    def session_id(self) -> str: ...

    @property
    def generation(self) -> int: ...

    @property
    def authority_id(self) -> str: ...

    @property
    def authority_revision(self) -> int: ...

    async def execute(
        self, transaction: OperationTransaction
    ) -> OperationReceipt: ...

    async def cancel(
        self, operation_id: str, *, authority_revision: int
    ) -> OperationReceipt: ...

    async def reconcile(
        self, transaction: OperationTransaction
    ) -> OperationReceipt: ...
```

`OperationManager` already implements the three behaviors and gains only these
four public-safe, read-only identity projections.  It remains the canonical
implementation.  The factory requires those projections to equal the selected
context and snapshots the three bound methods after validation so later
attribute mutation cannot change the selected service.  The adapter never
receives a map of services and therefore cannot select one.

## Root and Child Session Assembly

There is exactly one authoritative dispatcher for each session, not one global
dispatcher for the entire process tree.

For a root session, the operator constructs the `OperationManager` after the
authority and canonical journal exist but before constructing the selected
control provider.  The same instance is then supplied in both places:

```text
ControlPlaneFactoryContext.host_services["operation-dispatcher"]
ControlHost(operation_manager=the_same_instance)
```

This removes any Python -> Node -> different Python manager split.  Direct host
operations and Prime callback operations reach the same durable state machine.

For a child session, reusing the parent's `operation-dispatcher` is forbidden.
`ChildSessionService` therefore accepts one optional operator-owned synchronous
dispatcher deriver.  The deriver receives only the already-derived child
authority, opened child journal, child session ID, and generation; it captures
the operator-selected resolver, store, and exact service map outside the child
framework.  It returns one identity-bound `OperationDispatcher`.

Child construction order is fixed:

1. derive and persist the child binding and authority;
2. open or recover the child canonical journal;
3. derive and validate the child dispatcher;
4. replace, never merge ambiguously, the parent session's
   `operation-dispatcher` in the child factory context;
5. construct the selected Prime provider and callback transport;
6. pass the same child dispatcher to the child `ControlHost`.

If the selected provider advertises `operations-v1` and no child dispatcher
deriver is available, or the returned identity differs, child provider
creation fails before a sidecar process or operation effect.  A child cannot
fall back to its parent dispatcher, a global registry, or a request-selected
service.

## Private Callback Protocol

The transport uses the closed private protocol
`asterion.prime-operation-host/v1`.  It is not a public manifest or one of the
four closed shared composition contracts.

The descriptor passed to Node through the existing inherited private file
descriptor adds exactly:

```json
{
  "operationHost": {
    "socketPath": "<private-root>/prime-operation.sock",
    "token": "<64 lowercase hex characters>"
  }
}
```

The top-level descriptor already contains `sessionId`, `generation`,
`authorityId`, `authorityRevision`, and `timeoutMs`.  The Node callback client
binds those values at construction and includes them in every request.  Request
data cannot replace the socket, token, or identity.

Execute and reconcile requests contain exactly:

```text
protocol, id, type, token, session_id, generation,
authority_id, authority_revision, transaction
```

Cancel requests contain exactly:

```text
protocol, id, type, token, session_id, generation,
authority_id, authority_revision, operation_id
```

Successful responses contain exactly:

```text
protocol, id, type="operation.receipt", receipt
```

Safe failures contain only:

```text
protocol, id, type="error", code="operation-host-failed"
```

Frames are one JSON line, body-free, size-capped, deadline-bound, and accepted
only over the generated Unix socket.  The requester must half-close its write
side immediately after that line, while retaining the read side for the one
response; EOF is the deterministic frame terminator that lets the server reject
extra lines and delayed trailing data before dispatch.  Unknown keys, duplicate
or malformed identities, invalid tokens, oversized frames, extra lines,
trailing data, invalid receipts, and timeouts fail closed.  There is no retry.

## Python Callback Server

Add a Prime-specific callback server that:

1. receives the snapshotted `OperationDispatcher` and exact
   session/generation/authority identity;
2. generates or receives a 256-bit opaque token;
3. creates one socket below the already-resolved private root, rejecting
   symlinked parents and pre-existing paths;
4. sets the socket mode to `0600`;
5. validates the complete frame before invoking the dispatcher;
6. constructs `OperationTransaction` through the canonical Python validator;
7. validates the returned `OperationReceipt` and its complete transaction
   identity before serialization;
8. returns only the fixed safe error shape for all non-cancellation failures;
9. removes the socket and drains active handlers during idempotent close.

The server performs no service lookup.  `OperationManager` remains the only
component allowed to resolve `feature_id` against its preselected exact service
map and to read the private request through its injected resolver.

## Sidecar Lifecycle Adapter

The synchronous Prime factory constructs four values without starting async
work:

1. the validated/snapshotted dispatcher;
2. the callback server and immutable descriptor;
3. the ordinary `PrimeSidecarProcess` from the supplied `process_factory`;
4. a managed transport wrapper shared by `PrimeControlPlaneClient` and
   `PrimeOperationClient`.

On the first request or event iteration, the managed wrapper acquires one
start lock, starts the callback server, and only then permits the ordinary
sidecar process to start.  This removes the connection race while keeping the
factory synchronous.  Concurrent first requests observe one start.

Close order is sidecar first, callback server second.  The callback remains
available until Node can no longer issue requests.  Close is idempotent, makes
a best effort to release both resources, and reports only the existing safe
Prime transport error.  If no request ever starts the sidecar, close leaves no
socket or process behind.

If callback startup fails, the Node process is never created.  If Node startup
fails after callback startup, the wrapper closes and unlinks the callback
before returning a safe error.

## TypeScript Production Assembly

Add a `PrimeOperationHostClient` implementing the existing
`PrimeOperationDispatcher` interface.  It connects to the one descriptor-bound
socket per call, writes one exact frame, half-closes the write side, enforces the
descriptor timeout and frame cap, validates one exact response on the retained
read side, and closes the connection.  It never retries and never reads a
request body.

`validateDescriptor()` accepts `operationHost` only through the same recursive
optional-field technique used for `daemonLifecycle`, with exact keys and the
existing token/path safety constraints.

`createSidecarFromDescriptor()` must require `operationHost` for the production
Prime descriptor, construct:

```text
PrimeOperationHostClient -> PrimeOperationGateway
```

and inject that gateway into the sole `PrimeGatewaySidecar`.  Tests that build
`PrimeGatewaySidecar` directly may continue to inject a fake gateway, but no
production descriptor path may advertise `operations-v1` without the callback
descriptor.

The existing `PrimeOperationGateway` retains transaction validation,
same-operation serialization, replay fences, cancellation rules, and receipt
identity checks.  It does not gain service-selection logic.

## Identity, Recovery, and Failure Semantics

Every callback request is bound simultaneously to:

- callback token;
- request ID;
- session ID;
- generation;
- authority ID and revision;
- operation ID;
- complete transaction identity for execute/reconcile.

The Python server rejects a transaction whose embedded identity differs from
the server binding before dispatcher invocation.  Node validates the same
identity again against the transaction it sent.

Transport loss after dispatch is `uncertain`; neither side retries.  Recovery
uses the existing exact transaction replay: execute the same transaction to
recover the manager's durable receipt, then reconcile or cancel only when that
receipt is uncertain.  Conflicting transaction bytes remain a hard failure.

The callback transport owns no durable state.  Restart truth remains in the
Python operation journal and `OperationManager`; Node's in-memory gateway is a
serialization and validation fence, not the authority source.

## Security and Privacy

- The token and socket path appear only in the inherited private descriptor and
  redacted internal values.
- Public exceptions, `repr`, logs, parity reports, and receipts contain no
  token, socket path, private root, request body, credentials, prompts, provider
  payloads, or raw service output.
- The callback protocol carries only the already-public-safe transaction
  descriptor and receipt; private request bytes never cross into Node.
- Socket creation rejects symlink traversal and pre-existing endpoints.
- Missing dispatcher or identity mismatch fails before provider work.
- The transport cannot authorize commands, start services, choose runtimes,
  persist state, retry, schedule, or select an operation implementation.

## Verification Strategy

Implementation follows RED -> GREEN TDD.

### Python unit boundaries

- missing, malformed, exploding, or identity-incompatible dispatcher is
  rejected before `process_factory` is called;
- callback server accepts exact execute/cancel/reconcile frames and invokes the
  snapshotted dispatcher once;
- hostile keys, token, identity, transaction, receipt, frame size, timeout,
  disconnect, socket path, and symlink cases fail closed;
- lifecycle wrapper starts callback before process, starts once under
  concurrency, closes both resources, and leaves no endpoint after failures;
- root and child composition inject the same per-session manager into both the
  callback and `ControlHost`, while parent-dispatcher reuse fails before child
  process creation;
- sentinel secrets and paths are absent from all public errors and `repr`.

### TypeScript unit boundaries

- descriptor validation accepts only exact `operationHost` values;
- the host client emits exact body-free frames and validates exact responses;
- malformed, mismatched, late, oversized, multi-line, error, or disconnected
  responses reject without retry;
- the production descriptor path constructs and injects exactly one
  `PrimeOperationGateway`.

### Real-process provider-free integration

Start an actual built Node sidecar with its normal production descriptor and a
fake Prime daemon, plus one real Python callback server backed by a real
`OperationManager` and fake operator-owned `OperationService`.

Drive the public selected-provider object:

```text
PrimeControlPlaneClient.operation_client.execute(transaction)
```

and prove the complete Python -> Node -> Python round trip, exact one service
execution, exact receipt identity, zero request-body exposure, and zero
provider/application/network/model operations.  Add uncertain -> reconcile and
uncertain -> cancel cases, plus missing callback and callback failure cases.

This named real-process test is the new system-integration evidence.  Existing
provider-free operation harness receipts remain valid feature evidence, but
their `61/0/2` ledger count alone no longer closes Phase 2.

### Repository gates

After focused tests pass, rerun TypeScript build/tests, the Task 3/4 Python
sets, the system checker, `make test`, `make lint`, `make docs-check`,
`make check`, `make promotion-check`, distribution assumptions, and
`git diff --check`.  Every provider/application/model/network operation count
must remain zero.

## Climb and Project-State Transition

Do not append or execute H-037 during design or RED planning.  H-037 may be
recorded exactly once only after:

1. the real production callback round trip passes;
2. the full provider-free repository gates pass;
3. an independent architecture/code reviewer confirms the operation path is
   production-reachable and preserves authority boundaries.

Only then may the generated research tree advance from H-036, the Phase 2
status become `Verified-system-parity: PASS`, and the live resume baton move to
Phase 3 native parity.  A checker report of `61/0/2` before those conditions is
necessary but insufficient.

Git branch/worktree cleanup remains the final Phase 2 task: first promote the
reviewed integration to local `main`, verify the recovery bundle, switch the
primary workspace to clean `main`, then remove obsolete branches and detached
worktrees.  Do not stop on an integration branch or partially cleaned worktree
graph.

## Non-Goals

- No new public operation feature or schema version.
- No DCI-specific behavior in framework or provider modules.
- No Node-owned authority, private request resolver, operation journal, or
  implementation registry.
- No synthetic production receipt or request-selected dispatcher.
- No provider/model/network operation and no paid rerun.
- No Asterion-native-kernel implementation or native-parity claim.
- No remote push or mutation of `origin/main` without separate authorization.

## Completion Definition

The callback correction is complete only when all of the following are true:

- a selected Prime factory cannot advertise a usable `operations-v1` path
  without one exact injected `operation-dispatcher`;
- root and child sessions each bind one identity-exact manager, and a child can
  neither inherit nor route operations through its parent's manager;
- the sole production Node descriptor path constructs the callback client and
  `PrimeOperationGateway`;
- the real process round trip reaches the injected `OperationManager` exactly
  once and returns an exact safe receipt;
- execute, cancel, reconcile, replay, uncertainty, identity, lifecycle, and
  redaction gates pass;
- the system checker remains exactly 61 PASS, zero blocking, two exclusions,
  and zero provider/application operations;
- full repository, promotion, distribution, and independent-review gates pass;
- H-037 and Phase 2 are closed truthfully exactly once;
- local `main` contains the verified result and the primary worktree is the
  only active worktree, with unique historical states preserved in a verified
  recovery bundle.

The overall Asterion program remains open after this point: Phase 3 and Phase 4
must still deliver and verify the interchangeable Asterion-native provider
against the same closed Prime parity ledger.
