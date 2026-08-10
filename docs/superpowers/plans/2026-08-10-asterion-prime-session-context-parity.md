# Asterion Prime Session/Context Parity Implementation Plan

> Status: Tasks 4.1-4.6 verified; Task 4.7 exact resume and bounded deletion is next.
>
> Program parent: `2026-08-10-asterion-prime-system-parity.md`, Task 4.
>
> Baseline: Prime Agent `0.7.1`, commit
> `a18809e00ea30638584d87b3afea7285a9d7296c`, daemon protocol 7,
> schema revision 14.

## Goal

Deliver the nine mandatory `session.context` features through the selected
`asterion.prime-gateway` provider without weakening Asterion's authority,
privacy, durability, or provider-pluggability boundaries:

- `session.persistence-naming`
- `session.resume-delete`
- `session.tree-navigation`
- `session.fork-clone`
- `session.compaction`
- `session.branch-summaries-labels`
- `session.delivery`
- `session.usage-status`
- `session.rich-attachments`

The implementation is complete only when the seven provider-free scenarios
pass against the exact pinned Prime implementation and the two bounded
scenarios have named bounded-provider evidence. Adapter unit tests, a fake
daemon, `implemented`, and `external-limited` are useful evidence but cannot
be promoted to a parity PASS.

## Baseline facts established from the pinned source

The plan relies only on the following exact Prime surfaces. Any source or
protocol drift blocks the scenario rather than selecting a nearby surface.

| Asterion behavior | Prime daemon 7 command(s) | Pinned implementation fact |
| --- | --- | --- |
| Create and persistent name | `create`, `set_session_name`, `get_session_header` | `SessionManager` persists the transcript and session info |
| Resume exact continuation | `switch_session` | The daemon requires a private `sessionPath` |
| Delete inactive continuation | `delete_saved_session` | The daemon rejects the active session file |
| Read branch tree | `get_session_tree` | Returns `flatNodes` and `leafId` |
| Navigate branch | `navigate_tree` with `summarize: false` | Mutates the selected leaf |
| Fork at entry | `fork` with exact `entryId` | May replace the transcript behind the resident active session |
| Clone active branch | `get_session_tree`, then `fork` with `position: "at"` | This is the pinned RPC implementation of `clone`; there is no daemon `clone` command |
| Compact | `compact`; cancellation uses `abort_compaction` | Calls `AgentSession.compact()` and may invoke a model |
| Summarize branch | `navigate_tree` with `summarize: true`; cancellation uses `abort_branch_summary` | May invoke a model and stores a summary entry |
| Set or clear label | `set_session_entry_label` | Calls `SessionManager.appendLabelChange()` |
| Input delivery | Existing `prompt` plus `streamingBehavior` | `direct`, `steer`, and `follow_up` already map to Prime admission semantics |
| Usage/status | `get_session_stats`, `get_state` | Raw responses require a closed safe projection |
| Image attachment | `prompt.content` / `prompt.images` | Prime accepts typed `ImageContent`; bodies remain private |

`rename_saved_session` and `delete_saved_session` accept paths, but no path is
accepted by an Asterion public contract. The Gateway resolves an Asterion
continuation ID through its own private, source-locked binding and validates
the resulting regular file beneath the configured session root immediately
before dispatch.

## Architecture decision

### Keep `agent-control/v1` closed

Do not add Prime session-management commands to
`asterion.agent-control/v1`. Its existing lifecycle and input commands remain
unchanged. `input.submit` continues to carry one opaque `content_ref`, and its
three delivery modes remain the canonical input-delivery contract.

Add a separate provider-neutral extension:

```text
operator / host API
  -> SessionContextManager (authority + canonical journal)
  -> selected provider's SessionContextClient
  -> Prime Gateway session-context IPC
  -> exact daemon 7 command(s)
  -> closed public receipt + private provider binding
```

The new wire identity is `asterion.session-context/v1`. It is a closed
Asterion protocol, implemented in Python and TypeScript and covered by valid
and invalid cross-language fixtures. A native provider can later implement
the same protocol without importing Prime code.

The selected `ControlPlaneClient` may also satisfy `SessionContextClient`.
This is enabled only when all three conditions hold:

1. the exact selected control-plane manifest declares capability
   `session.context-v1`;
2. the selected client structurally implements the closed extension;
3. the host explicitly injects that extension into `SessionContextManager`.

Do not scan providers, infer the extension from methods, or let the manager
load an entry point. Capability-without-implementation and
implementation-without-capability both fail preflight. The extension shares
the selected client's lifetime; it does not start a second daemon or runner.

### Identity model

Keep these identities distinct and fence every transition:

| Identity | Owner | Visibility | Stability rule |
| --- | --- | --- | --- |
| Asterion `session_id` | Asterion host | Public | Never changes for one control journal |
| Asterion `continuation_id` | Asterion host | Public | Identifies one resumable transcript artifact; fork/clone may create a new one |
| Asterion `branch_id` / `entry_id` | Gateway projection | Public opaque | Scoped to one continuation and rejected across scopes |
| Prime `activeSessionId` | Prime daemon | Private | May survive transcript replacement but is fenced by supervisor generation |
| Prime transcript/session ID | Prime | Private | May change after switch/fork/new-session |
| Prime session path | Prime | Private | Exact regular child of the configured session root; never rendered or journaled publicly |
| supervisor generation and daemon cursor | Prime/Gateway | Private | Must agree with the current durable binding before dispatch |

The Gateway stores provider identities and paths only in its private root.
Public receipts contain Asterion identities and digests, not provider IDs or
paths. A transcript-replacing daemon response is committed atomically with
the corresponding public-safe receipt before it can become the active private
binding.

### Authority model

Session/context requests do not become authority merely because Prime accepts
them. Every command carries the current `authority_revision` and an
`idempotency_key`; `SessionContextManager` verifies both before journaling.

The host authority envelope uses these exact operation IDs:

- `session.attachment.bind`
- `session.branch.summarize`
- `session.clone`
- `session.compact`
- `session.continuation.delete`
- `session.continuation.resume`
- `session.describe`
- `session.fork`
- `session.label.set`
- `session.name.set`
- `session.tree.navigate`
- `session.tree.read`

Read operations still require an allowed operation because status, usage and
topology are not ambient capabilities. Mutation commands require the session
to be non-terminal and the private Prime binding to be current. Delete also
requires the target continuation to be inactive.

`session.compact` and `session.branch.summarize` include an exact bounded
model budget and optional private instruction reference. Their budget is
reserved by the host before provider dispatch, usage is reconciled
monotonically from validated Prime events/stats, and unused reservation is
released only after a terminal receipt. Prime auto-compaction stays disabled
until a later admitted policy can express equivalent authority; no provider
setting silently enables it.

### Public protocol

Create closed schemas for command and receipt documents under
`schemas/session-context/v1/`.

Every command has exactly:

```json
{
  "protocol": "asterion.session-context/v1",
  "command_id": "context-command-1",
  "session_id": "session-1",
  "generation": 1,
  "authority_revision": 1,
  "idempotency_key": "context-operation-1",
  "operation": "session.tree.read",
  "payload": {
    "continuation_id": "continuation-1"
  }
}
```

Every receipt has exactly:

```json
{
  "protocol": "asterion.session-context/v1",
  "receipt_id": "context-receipt-1",
  "command_id": "context-command-1",
  "session_id": "session-1",
  "generation": 1,
  "operation": "session.tree.read",
  "status": "succeeded",
  "reason_code": "session-context-succeeded",
  "payload": {
    "evidence_ref": "evidence-1",
    "result": {
      "continuation_id": "continuation-1",
      "nodes": [],
      "leaf_id": null
    }
  }
}
```

Allowed receipt statuses are `succeeded`, `rejected`, `failed`, `cancelled`,
and `uncertain`. Only `succeeded` carries an operation result. `uncertain`
always places the control host into recovery-required state and cannot be
automatically retried with a different idempotency key.

Operation payloads are closed unions:

| Operation | Public request payload | Public success projection |
| --- | --- | --- |
| `session.describe` | `{}` | current `continuation_id`, status code, safe token/turn counts, optional name digest |
| `session.name.set` | `name_ref` | `name_sha256` and current `continuation_id` |
| `session.continuation.resume` | `continuation_id` | previous/current continuation IDs and transition digest |
| `session.continuation.delete` | `continuation_id` | deleted continuation ID and deletion receipt digest |
| `session.tree.read` | `continuation_id` | sorted closed nodes containing IDs, parent ID, kind, token count and optional label digest; active leaf ID |
| `session.tree.navigate` | `continuation_id`, `entry_id` | previous/current leaf IDs and transition digest |
| `session.fork` | `continuation_id`, `entry_id`, `position` | source and new continuation IDs, active leaf ID, transition digest |
| `session.clone` | `continuation_id` | source and new continuation IDs, active leaf ID, transition digest |
| `session.compact` | `continuation_id`, optional `instructions_ref`, exact budget | continuation ID, covered leaf ID, before/after token counts, summary digest, usage |
| `session.branch.summarize` | `continuation_id`, `entry_id`, optional `instructions_ref`, exact budget | previous/current leaf IDs, summary digest, usage |
| `session.label.set` | `continuation_id`, `entry_id`, nullable `label_ref` | entry ID and nullable label digest |
| `session.attachment.bind` | `input_id`, `attachment_id`, `body_ref`, `media_type`, `sha256`, `size` | same safe metadata plus causal input ID |

The tree node `kind` vocabulary is an Asterion-owned closed projection, not
Prime's raw entry type. Arrays are sorted and unique. Counts are nonnegative
safe integers. Digests are lowercase SHA-256. A response containing a raw
message, summary, label, name, provider payload, path, provider identity,
credential, socket, or environment value is rejected before persistence.

### Private input and attachment contract

Extend the host-owned private resolver with a narrow, separate protocol;
retain `PrivateContentResolver.resolve_text()` for existing callers:

```python
class PrivateAttachmentResolver(Protocol):
    def resolve_bytes(
        self,
        reference: str,
        *,
        expected_media_type: str,
        expected_sha256: str,
        expected_size: int,
        max_bytes: int,
    ) -> bytes: ...
```

The host resolves and verifies the body only after authority admission. The
Python client sends it over the existing private sidecar channel, never in a
public command or error. The Gateway stores the body under an unguessable
private reference and binds it to `(session_id, input_id, attachment_id)`.
`input.submit` reads only already-committed bindings for its exact `input_id`,
builds Prime `ImageContent`, and submits text plus attachments together.

For the pinned provider, initially admit only the exact image media types
supported by Prime's `ImageContent` decoder. Unsupported provider-neutral
media types fail with `attachment-media-unsupported`; they are not coerced or
written to disk. Duplicate attachment IDs are idempotent only when all safe
metadata and private digest agree.

### Durability and recovery protocol

Use the same stable `command_id` for the Asterion context command, sidecar
request and Prime daemon recovery-journal command. The Gateway sequence is:

```text
validate public command and current private identity
  -> append context.command.accepted and fsync
  -> send exact daemon command with stable ID (deferred response)
  -> validate and project response; never persist raw response publicly
  -> append one context.operation.committed record containing
       public receipt + complete next private binding
  -> fsync record and directory
  -> acknowledge daemon recovery-journal result
  -> return the public receipt
```

The committed record is the atomic boundary. It prevents a receipt from
becoming visible without the transcript/continuation binding required to
resume it. On restart:

- accepted without committed: resend the same daemon command ID;
- committed without daemon ack: replay the committed receipt, then ack;
- ack without committed: impossible by construction and covered by fault
  injection;
- daemon returns `command_result_uncertain`: persist an uncertain receipt,
  fence the session, and require operator recovery;
- identity/generation mismatch: dispatch nothing and emit a redacted failed
  receipt;
- digest conflict for a repeated command or idempotency key: fail closed.

Compaction and branch-summary cancellation use the matching Prime abort
command with the same causal operation identity. Cancellation after provider
ownership is terminal only after the provider is idle or a recovery-required
receipt is sealed. Deletion revalidates the inactive exact regular file after
admission and immediately before daemon dispatch, closing selector-swap and
symlink windows.

## Scenario contract

Replace the generic placeholder assertions/faults for these nine ledger
scenarios with the following exact matrices before registering a runner. This
is a ledger fixture change, not a relaxation of the original boundary.

| Scenario | Boundary | Required assertions | Required faults |
| --- | --- | --- | --- |
| `prime-parity.session.persistence-naming` | `real-prime-provider-free` | stable Asterion/active/transcript identity separation; name persists across detach/restart; public name digest only; duplicate rename idempotent | restart after daemon result before commit; conflicting rename replay |
| `prime-parity.session.resume-delete` | `real-prime-provider-free` | exact continuation resume; active continuation cannot be deleted; inactive exact artifact deletion only; public paths absent | restart after switch; selector swap; symlink replacement; delete after side effect before commit |
| `prime-parity.session.tree-navigation` | `real-prime-provider-free` | canonical topology projection; exact entry scope; deterministic active leaf; raw message/label absent | restart after navigation; stale continuation; foreign entry ID |
| `prime-parity.session.fork-clone` | `real-prime-provider-free` | fork uses requested entry; clone equals leaf fork-at; source remains resumable; new continuation binding committed atomically | restart in each fork/clone crash window; missing leaf; response/binding conflict |
| `prime-parity.session.compaction` | `bounded-provider` | budget admitted before model call; resumable compacted context; before/after usage monotonic; private summary; auto-compaction disabled | cancel during compaction; restart before/after daemon result; bounded-provider failure |
| `prime-parity.session.branch-summaries-labels` | `bounded-provider` | summary admitted/budgeted; label set/clear exact entry; branch identity retained; text private | cancel during summary; restart before/after result; stale entry; label replay conflict |
| `prime-parity.session.delivery` | `real-prime-provider-free` | direct rejects/owns according to idle state; steer targets current turn; follow-up queues next turn; input ID exactly once | restart after admission; cancel before ownership; replay all three modes |
| `prime-parity.session.usage-status` | `real-prime-provider-free` | safe status vocabulary; nonnegative monotonic counts; no provider/model/path/raw response; identity current | malformed/overflow stats; restart during read; stale generation |
| `prime-parity.session.rich-attachments` | `real-prime-provider-free` | typed digest/size projection; body private; attachment causal to exact input; Prime receives verified bytes once | digest/size/media mismatch; body swap; restart after bind and after prompt admission |

Provider-free unit tests use a deterministic fake daemon only to prove adapter
logic and crash windows. The parity runners for the seven
`real-prime-provider-free` scenarios must launch the source-locked Prime
daemon/code path in a temporary private root without reading a model
credential. When message/tree fixtures are needed, create them through a
pinned Prime test fixture builder or an admitted daemon command; do not edit a
session JSONL behind Prime's back.

The two bounded scenarios remain `external-limited` until a finite model
budget is explicitly authorized and recorded. Their provider-free tests prove
preflight, rejection, cancellation, recovery and redaction, but cannot produce
`bounded-pass`.

## Work breakdown

Each task is test-first and ends in a focused commit. Do not begin a later
mutation task while an earlier protocol/durability task is failing.

### Task 4.1: Add the closed session-context contract

**Status:** Complete. Python/JSON Schema/TypeScript agreement, safe-integer
bounds, wheel resources, full promotion and independent review pass.

**Create:**

- `schemas/session-context/v1/command.schema.json`
- `schemas/session-context/v1/receipt.schema.json`
- `src/asterion/control/session_context.py`
- `tests/fixtures/session_context/v1/valid-*.json`
- `tests/fixtures/session_context/v1/invalid-*.json`
- `tests/test_session_context_protocol.py`
- `pyproject.toml`
- `tools/check_promotion.py`
- `tests/test_distribution.py`
- `tests/test_check_promotion.py`

**Modify:**

- `src/asterion/control/__init__.py`
- `packages/typescript/asterion-runtime/src/types.ts`
- `packages/typescript/asterion-runtime/src/validation.ts`
- `packages/typescript/asterion-runtime/src/index.ts`
- `packages/typescript/asterion-runtime/test/runtime.test.mjs`
- `packages/typescript/asterion-runtime/test/type-contract.ts`

1. Write Python and TypeScript tests for every operation union, recursive
   immutability, canonical ordering, exact fields, IDs, budgets, safe tree
   nodes, attachment metadata, and all forbidden public values.
2. Prove invalid fixtures fail in both languages with sentinel-free errors.
3. Implement `SessionContextCommand`, `SessionContextReceipt`, validators and
   the `SessionContextClient` protocol. Keep provider details out.
4. Run:

```bash
uv run python -m unittest -v tests.test_session_context_protocol
npm --prefix packages/typescript/asterion-runtime test
uv run pyright src/asterion/control/session_context.py tests/test_session_context_protocol.py
uv run python -m unittest -v tests.test_distribution tests.test_check_promotion
make promotion-check
```

Expected: PASS, zero Pyright errors/warnings.

Commit: `feat: add closed session context protocol`.

### Task 4.2: Bind the extension to exactly one selected provider

**Status:** Complete. Exact capability/implementation agreement, explicit
selection, single-process lifetime, response correlation, promotion and
independent review pass.

**Modify:**

- `src/asterion/control/factory.py`
- `src/asterion/control/host.py`
- `src/asterion/control/providers/prime/client.py`
- `src/asterion/control/providers/prime/factory.py`
- `src/asterion/control/providers/prime/resources/control-plane.json`
- `tests/test_control_provider.py`
- `tests/test_prime_control_factory.py`

1. Add failing tests for the three-condition preflight, exact capability
   identity, no extension discovery, no second process and shared close.
2. Add a provider-neutral helper that returns an explicitly selected
   `SessionContextClient` only when manifest and implementation agree.
3. Add `session.context-v1` to the Prime manifest only after the client can
   satisfy the protocol; metadata-only `list` must not construct the client.
4. Prove a provider without the capability behaves exactly as before.

Run:

```bash
uv run python -m unittest -v tests.test_control_provider tests.test_prime_control_factory
```

Commit: `feat: bind selected session context provider`.

### Task 4.3: Add host authority, journal and recovery management

**Status:** Complete. The host persists commands and authority decisions before
dispatch, accounts for shared budgets, replays exact receipts, and fences
post-dispatch cancellation as uncertain until Task 4.4 adds routed IPC cancel.

**Create:**

- `src/asterion/control/session_context_manager.py`
- `tests/test_session_context_manager.py`

**Modify:**

- `src/asterion/control/authority.py`
- `src/asterion/control/journal.py`
- `src/asterion/control/manager.py`
- `src/asterion/control/recovery.py`
- `src/asterion/control/__init__.py`

1. Test persist-before-dispatch, exact authority revision/operation,
   idempotency conflicts, terminal-session rejection, model budget reservation,
   cancellation and uncertain recovery.
2. Add closed journal kinds for context command, decision and receipt; payloads
   contain only the public protocol documents and safe usage.
3. Implement `SessionContextManager.execute()` with an explicit injected
   client and cancellation signal. It never discovers, retries with a new ID,
   reads private data, or chooses a provider.
4. Recover accepted/decided/receipted context operations from the same
   canonical journal as lifecycle events.
5. Until Task 4.4 provides request-ID response routing, cancellation after
   dispatch records an uncertain receipt and fences the session. It must not
   send a cancel request through the blocked sequential sidecar channel.

Run:

```bash
uv run python -m unittest -v tests.test_session_context_manager tests.test_control_authority tests.test_control_host
```

Commit: `feat: manage authorized session context operations`.

### Task 4.4: Extend the private sidecar IPC and durable store

**Status:** Complete. Context IPC now uses exact request-ID routing, private
attachment/text preparation, atomic public command/receipt records, and strict
private attachment/continuation bindings with fault-recovery coverage.

**Modify:**

- `src/asterion/control/providers/prime/client.py`
- `src/asterion/control/providers/prime/process.py`
- `tests/test_prime_control_client.py`
- `tests/test_prime_control_factory.py`
- `packages/typescript/prime-gateway/src/main.ts`
- `packages/typescript/prime-gateway/src/durable-store.ts`
- `packages/typescript/prime-gateway/src/private-store.ts`
- `packages/typescript/prime-gateway/src/gateway.ts`
- `packages/typescript/prime-gateway/test/main.test.mjs`
- `packages/typescript/prime-gateway/test/durable-store.test.mjs`
- `packages/typescript/prime-gateway/test/private-store.test.mjs`

1. Add closed `session-context.execute` IPC request/receipt validation. Private
   fields are carried separately from the public command and cannot appear in
   logs, errors or durable public projections.
2. Add `context.command.accepted` and one atomic
   `context.operation.committed` record containing the safe receipt and next
   private identity/continuation binding.
3. Test every storage fault stage before/after write, rename and directory
   fsync. Reopen after each fault and assert exactly one current binding.
4. Add private attachment bytes and continuation locator bindings with strict
   roots, no-follow opens, caps and digest checks.
5. Replace the Python sidecar's lock-across-response request path for this
   surface with exact request-ID routing. Admit only the two context response
   types, route stale/out-of-order replies correctly, and prove an in-flight
   execute can be cancelled without consuming either response as the other.

Run:

```bash
npm --prefix packages/typescript/prime-gateway test -- \
  test/main.test.mjs test/durable-store.test.mjs test/private-store.test.mjs
uv run python -m unittest -v \
  tests.test_prime_control_client tests.test_prime_control_factory
```

Commit: `feat: persist prime session context operations`.

### Task 4.5: Admit the exact daemon session/context surface

**Status:** Complete. The pinned commands and image types are closed at the
wire, initial and reconnect build identity is exact, responses are bounded and
correlated, private daemon failures are redacted, and uncertain results retain
the deferred durability boundary.

**Modify:**

- `packages/typescript/prime-gateway/src/daemon-wire.ts`
- `packages/typescript/prime-gateway/src/daemon-client.ts`
- `packages/typescript/prime-gateway/src/index.ts`
- `packages/typescript/prime-gateway/src/main.ts`
- `packages/typescript/prime-gateway/test/daemon-wire.test.mjs`
- `packages/typescript/prime-gateway/test/daemon-client.test.mjs`
- `packages/typescript/prime-gateway/test/fixtures/fake-prime-daemon.mjs`

Add only these pinned daemon commands to the closed allowlist:

- `abort_branch_summary`
- `abort_compaction`
- `compact`
- `delete_saved_session`
- `fork`
- `get_session_stats`
- `get_session_tree`
- `get_state`
- `navigate_tree`
- `rename_saved_session`
- `set_session_entry_label`
- `set_session_name`
- `switch_session`

Add `prompt.content`/`prompt.images` only through a dedicated exact image
validator. Do not add `clone`: implement its pinned composite semantics in
`PrimeSession`.

Tests cover exact keys, protocol/schema/app/build lock, command compatibility,
closed nested content, response size/depth caps, raw-response rejection,
deferred ack/replay and redaction. Unknown or next-build fields fail closed.

Run:

```bash
npm --prefix packages/typescript/prime-gateway test -- \
  test/daemon-wire.test.mjs test/daemon-client.test.mjs
```

Commit: `feat: admit pinned prime session commands`.

### Task 4.6: Implement identity, naming, describe and usage projections

**Modify:**

- `packages/typescript/prime-gateway/src/prime-session.ts`
- `packages/typescript/prime-gateway/src/gateway.ts`
- `packages/typescript/prime-gateway/src/durable-store.ts`
- `packages/typescript/prime-gateway/src/main.ts`
- `src/asterion/control/providers/prime/process.py`
- `packages/typescript/prime-gateway/test/prime-session.test.mjs`
- `packages/typescript/prime-gateway/test/gateway.test.mjs`
- `tests/test_prime_control_factory.py`

1. Persist initial continuation and separate Prime active/transcript IDs after
   `create`; acquire the exact private session path through the pinned header.
2. Implement `session.name.set` and `session.describe`.
3. Project only closed status codes, monotonic nonnegative usage/turn counts,
   continuation ID and optional name digest.
4. Reject overflow, negative, floating, unknown and raw nested stats.
5. Exercise restart-after-result and repeated command replay.

**Status:** Complete. Creation now pins the Prime header, stores the private
continuation locator before acknowledging the daemon result, and rebinds it
across supervisor generations. Native naming and describe commands expose
only digests, closed status and monotonic safe counts; valid post-compaction
unknown context usage projects to zero while malformed statistics fail
closed. The sidecar launches with umask `0077`, so the pinned Prime transcript
satisfies the locator's owner-only file invariant. Thirty-eight focused
Gateway tests, all 152 Prime Gateway tests, the Python process-boundary suite,
`make check`, and independent review pass.

Run the two focused Gateway test files. Commit:
`feat: project prime session identity and status`.

### Task 4.7: Implement exact resume and bounded deletion

**Modify:** the same Prime session/Gateway/durable modules.

**Create:** `packages/typescript/prime-gateway/test/session-continuation.test.mjs`.

1. Resolve `continuation_id` only through the private binding store.
2. Revalidate a no-follow regular child beneath `sessionDir` immediately
   before `switch_session` or `delete_saved_session`.
3. Commit transcript/binding replacement atomically after resume.
4. Reject deletion of the active continuation before daemon dispatch.
5. Inject selector swap, symlink, crash-before-result, crash-after-result and
   delete-after-side-effect faults; assert no broad deletion and exact replay.

Commit: `feat: resume and delete exact prime continuations`.

### Task 4.8: Implement tree projection, navigation, fork and clone

**Create:**

- `packages/typescript/prime-gateway/src/session-tree.ts`
- `packages/typescript/prime-gateway/test/session-tree.test.mjs`

**Modify:** `prime-session.ts`, `gateway.ts`, `durable-store.ts` and their tests.

1. Validate `get_session_tree` into a closed internal form and project only
   scoped IDs, topology, kinds, counts and label digests.
2. Implement navigation with `summarize: false` and exact entry/continuation
   scoping.
3. Implement fork with the requested entry/position.
4. Implement clone exactly as pinned RPC: read current `leafId`, reject a
   missing leaf, then fork that leaf at `position: "at"`.
5. After fork/clone, reacquire and atomically commit the next transcript/path
   binding while preserving the Asterion session ID and source continuation.
6. Cover every crash window and conflicting replay.

Commit: `feat: add prime session tree fork and clone`.

### Task 4.9: Implement private rich attachments and delivery replay

**Modify:**

- `src/asterion/control/private_store.py`
- `src/asterion/control/providers/prime/client.py`
- `packages/typescript/prime-gateway/src/main.ts`
- `packages/typescript/prime-gateway/src/private-store.ts`
- `packages/typescript/prime-gateway/src/gateway.ts`
- `packages/typescript/prime-gateway/src/prime-session.ts`
- corresponding Python and Gateway tests

1. Add `PrivateAttachmentResolver` without weakening the existing text
   resolver.
2. Bind verified attachment bytes through `session.attachment.bind` and expose
   only attachment ID, input ID, media type, digest and size in the receipt.
3. Assemble committed attachments for the exact `input.submit.input_id` into
   Prime image content; reject missing, extra, reordered or conflicting binds.
4. Re-run direct/steer/follow-up admission and cancellation tests with stable
   input IDs and restart at each ownership boundary.
5. Assert sentinel body/name/label/path/provider values are absent from every
   public event, journal, report, exception and `repr`.

Commit: `feat: deliver private prime attachments exactly once`.

### Task 4.10: Implement labels and bounded model operations

**Modify:** Prime session/Gateway modules, authority reconciliation and tests.

1. Implement label set/clear as provider-free private-label operations.
2. Implement manual compaction with auto-compaction kept disabled.
3. Implement branch summary as `navigate_tree(summarize: true)` with private
   instructions and summary output.
4. Bind exact budgets before dispatch and reconcile controller/provider usage.
5. Test provider rejection, budget exhaustion, cancellation, restart and
   uncertain outcomes without a model credential.
6. Run the two real bounded scenarios only after explicit finite authorization;
   record the provider/build/budget/evidence command without raw model data.

Commit implementation separately from bounded evidence:

- `feat: add admitted prime compaction and summaries`
- `test: verify bounded prime session model operations`

If no budget is authorized, make only the first commit and retain
`external-limited` honestly.

### Task 4.11: Register exact scenarios and promote only exact evidence

**Modify:**

- `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`
- `src/asterion/control/parity_testing.py`
- `src/asterion/control/providers/prime/parity_testing.py`
- `tests/test_prime_parity_conformance.py`
- `tests/test_prime_verified_loop.py`
- `tools/check_prime_parity.py`

**Create:**

- `tests/test_prime_session_context_parity.py`
- any private test harness needed to launch the pinned real Prime daemon

1. Replace placeholder assertion/fault IDs with the exact scenario matrix in
   this plan.
2. Register all nine scenario runners. Fake-daemon reports remain diagnostic
   and have no ledger evidence ID.
3. Run the seven real Prime provider-free scenarios without reading a model
   credential. Evidence digests bind exact observations, source/artifact lock,
   scenario ID, provider ID and named verification command.
4. Run the two bounded scenarios only with explicit authority.
5. Update one provider result at a time. Never bulk-promote based on a domain
   test or implementation status.

Focused exit:

```bash
uv run python -m unittest -v \
  tests.test_session_context_protocol \
  tests.test_session_context_manager \
  tests.test_prime_session_context_parity \
  tests.test_prime_parity_conformance
npm --prefix packages/typescript/asterion-runtime test
npm --prefix packages/typescript/prime-gateway test
uv run python tools/check_prime_parity.py \
  --domain session.context \
  --provider asterion.prime-gateway
```

Expected only after bounded authorization: nine passed features and zero
`session.context` blockers. Missing features from other domains remain visible
in the full-system claim.

Commit: `test: verify prime session context parity`.

### Task 4.12: Full verification and independent review

Run from a clean worktree except durable status files and explicitly unrelated
user changes:

```bash
uv run python -m unittest -v tests.test_session_context_protocol
uv run python -m unittest -v tests.test_session_context_manager
uv run python -m unittest -v tests.test_prime_session_context_parity
npm --prefix packages/typescript/asterion-runtime test
npm --prefix packages/typescript/prime-gateway test
make test
make lint
make docs-check
make promotion-check
uv run pyright \
  src/asterion/control/session_context.py \
  src/asterion/control/session_context_manager.py \
  src/asterion/control/providers/prime/client.py \
  tests/test_session_context_protocol.py \
  tests/test_session_context_manager.py \
  tests/test_prime_session_context_parity.py
uv run python tools/check_prime_parity.py \
  --domain session.context \
  --provider asterion.prime-gateway
```

Request independent code review focused on authority bypass, path traversal,
private data projection, replay conflicts, fork/clone identity confusion,
compaction budget reconciliation and evidence inflation. Resolve every
Critical/Important finding and rerun the affected boundary plus the full
Python and Gateway suites.

## Cost and risk assessment

| Area | Estimated implementation cost | Risk | Required mitigation |
| --- | --- | --- | --- |
| New closed protocol in Python/TS/schemas | Medium | Cross-language drift | Shared fixtures and exact-field tests |
| Factory/host extension binding | Low-medium | Hidden provider coupling | Manifest plus structural plus explicit-injection gate |
| Canonical journal/recovery changes | High | Duplicate or unresumable mutation | Stable IDs, atomic committed record, exhaustive storage faults |
| Private continuation paths/delete | High | Path traversal or wrong artifact deletion | Private ID mapping, no-follow exact-root revalidation, inactive-only rule |
| Tree/fork/clone | High | Asterion/Prime identity confusion | Separate IDs, scoped entries, atomic binding transition |
| Attachments | Medium-high | Public data leak, body substitution | Private resolver, digest/size/media verification, causal input binding |
| Usage/status | Medium | Raw provider leakage or false budgets | Closed projection, monotonic reconciliation, overflow rejection |
| Compaction/summary | High | Unadmitted model spend, uncertain state | Explicit budgets, disabled auto-compaction, cancellation/recovery fence |
| Real Prime provider-free harness | Medium-high | Fake evidence or flaky environment | Exact source lock, real code path, deterministic private fixture builder |
| Bounded evidence | Low code / external cost | Unbounded spend or unverifiable result | Separate explicit authorization and finite budget |

The hosted route is still materially cheaper and safer than immediately
building the native kernel: it reuses Prime's mature session tree,
compaction, daemon recovery and input semantics. Its dominant risk is semantic
translation at transcript-replacing and file-mutating boundaries. This plan
therefore invests most effort in identities, private locators and replay
rather than duplicating Prime's agent loop. The resulting
`asterion.session-context/v1` contract and scenario suite become the executable
specification for the later native provider, reducing native-kernel design
risk instead of creating a permanent Prime dependency.

## Non-goals and stop conditions

- Do not expose Prime session files, raw messages, raw summaries, raw labels,
  raw names, provider/model identities or daemon payloads.
- Do not add source scanning, resume by arbitrary path, symlink traversal,
  registry/range lookup or manifest authority.
- Do not enable Prime auto-compaction, autonomous model calls or attachment
  media coercion.
- Do not implement a second composer, runner or daemon in TypeScript.
- Do not claim the two bounded features without an authorized bounded run.
- Stop and report `External-limited` if bounded credentials/budget are absent;
  keep the program goal active because later domains and the native provider
  remain incomplete.
- Any exact Prime artifact/protocol/schema/build mismatch blocks this phase and
  routes to the compatibility task; it is never normalized locally.
