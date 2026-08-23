# Asterion Prime Continual Harness Parity Design

> Parent: `docs/superpowers/plans/2026-08-10-asterion-prime-system-parity.md`, Task 7.
>
> Prime baseline: `0.7.1`, source commit
> `a18809e00ea30638584d87b3afea7285a9d7296c`, daemon protocol 7, schema 14.

## Goal

Deliver the eight mandatory `harness.continual` features through the selected
`asterion.prime-gateway` provider while preserving Asterion-owned authority,
durable recovery, private bodies, deterministic composition, and a future peer
native provider:

- `harness.prompt-entries`
- `harness.memory-entries`
- `harness.skill-descriptions`
- `harness.subagent-specifications`
- `harness.evidence-refinement`
- `harness.history-snapshots`
- `harness.rollback`
- `harness.scope-isolation`

Seven deterministic state scenarios run against the real pinned Prime boundary
with zero model credentials and zero provider operations. Only
`harness.evidence-refinement` requires a separately authorized finite model
operation because its claim includes a model-produced proposal grounded in
trajectory evidence.

## Baseline facts

Pinned Prime implements continual refinement in
`packages/coding-agent/src/core/refinement/refinement.ts`. It supports four
entry kinds (`prompt`, `memory`, `skill`, and `subagent`), create/update/delete
edits, local and global stores, append-only global refinement history, merged
local/global views, optimistic baseline conflict checks, and rollback through
inverse edits recorded as a new result with `rollbackOf`.

Prime's local store is session-owned. Its global store is agent-directory-owned.
Project-specific lessons are represented as explicitly project-qualified global
content rather than as a third native `HarnessScope` value. Asterion requires an
explicit project scope so unrelated projects cannot share state merely because
their bodies happen to contain different project names.

The repository currently has no `control.harness.*` implementation. Existing
Pi observation rollback is unrelated attempt-local telemetry and cannot satisfy
the continual-harness ledger.

## Decision

Build a provider-neutral, host-owned **revision kernel** and use the Prime
Gateway as an exact-version effect adapter. Prime remains the selected behavior
oracle and proposal engine; it does not become the authority or canonical
store.

The host owns:

- exact scope identity and approved roots;
- proposal admission and evidence requirements;
- immutable revision, snapshot, and activation identities;
- append-only journal records and recovery reduction;
- private entry bodies and provider-result bodies;
- public-safe receipts and parity evidence.

The Prime adapter owns only translation to the pinned refinement surface and
validation of the returned effect receipt. A Prime state file is a private
provider projection that can be rebuilt from the host journal; its existence,
contents, or timestamps never grant authority.

Alternatives rejected:

1. Directly treating Prime's harness files as canonical would let provider state
   grant authority, would not provide an isolated project scope, and would make
   crash recovery depend on mutable engine files.
2. A Gateway-only wrapper would duplicate admission and recovery policy in
   TypeScript and prevent the future native provider from sharing conformance.
3. A CLI-only shim would expose commands without durable revision, rollback,
   or persist-before-effect guarantees and therefore could not satisfy the
   ledger.

## Provider-neutral domain model

Add a focused `asterion.control.harness` module. It defines recursively
immutable values with exact closed fields:

- `HarnessScope(kind, scope_id)` where `kind` is exactly `session`, `project`,
  or `global`. Session and project require an opaque `scope_id`; global forbids
  one.
- `HarnessEntryKind` with exactly `prompt`, `memory`, `skill`, and `subagent`.
- `HarnessEntryDescriptor` with entry ID, kind, title digest, body reference,
  body digest, optional grouping-path digest, metadata digest, and version.
- `HarnessEdit` with action, entry identity, expected version, and optional
  replacement descriptor. Delete requires an existing exact version; create
  requires absence; update requires an exact prior version.
- `HarnessProposal` with proposal ID, authority ID/revision, scope, ordered
  edits, sorted unique evidence IDs, private rationale reference, rationale
  digest, and expected-outcome digest.
- `HarnessRevision` with revision ID, monotonic sequence, proposal digest,
  previous snapshot ID, resulting snapshot ID, activation status, and optional
  rollback target revision ID.
- `HarnessSnapshot` with scope, sequence, sorted entry descriptors, and the
  exact active revision ID.
- `HarnessReceipt` with proposal/revision/snapshot identities, terminal status,
  provider-effect digest, and safe operation/credential/usage counts.

Public values contain no prompt, memory, skill, subagent, rationale, expected
outcome, trajectory, path, credential, provider payload, or model output.
Bodies resolve only through an explicitly injected private content service.

## Scope semantics

Scopes have disjoint canonical journal namespaces and approved private roots:

| Asterion scope | Ownership | Prime projection |
| --- | --- | --- |
| `session:<id>` | One exact Asterion session generation | Prime local harness rooted below that session's private artifact root. |
| `project:<id>` | One explicitly selected project identity | A dedicated Prime local harness projection rooted below the project's approved private root; never the global agent directory. |
| `global` | Operator-owned cross-session state | Prime global harness below the selected provider root. |

A merged read view is ordered `global`, `project`, then `session`. Entry IDs are
never silently shadowed: collisions remain distinct by scope and rendering uses
the explicit scope identity. A proposal may mutate exactly one scope. Other
scopes are immutable context during proposal generation.

No scope is inferred from the current directory, environment, content body, or
Prime cache. The host supplies an exact approved scope binding before the
Gateway opens provider state.

## Proposal, admission, and activation flow

```text
caller selects one exact scope and private trajectory reference
  -> host resolves immutable snapshot and evidence identities
  -> provider proposes closed edits or caller supplies deterministic edits
  -> host validates kinds, versions, bodies, scope, authority and evidence
  -> host appends proposed revision before provider effect
  -> Gateway applies the exact admitted edit set to the pinned Prime projection
  -> Gateway returns a body-free effect digest and terminal status
  -> host verifies the projection against the admitted proposal
  -> host appends terminal revision and activates the resulting snapshot
```

Proposal generation and proposal activation are separate. A generated proposal
never applies merely because Prime emitted valid JSON. Admission requires the
current authority revision, an exact snapshot baseline, all referenced private
bodies, sorted unique evidence IDs, and a finite operation budget. Any conflict
rejects before provider effect.

The seven provider-free scenarios use deterministic host-supplied edits and
exercise the real Prime projection without model credentials. The bounded
`evidence-refinement` scenario supplies a private trajectory to Prime's pinned
proposal engine, permits at most one provider operation, and then runs the same
host admission and activation path.

## Revision, history, and rollback

Every accepted proposal creates one monotonically sequenced revision. History
is append-only and keyed by scope. A snapshot is a canonical immutable reduction
of all terminal successful revisions through its sequence; it is not a copied
authority document.

Rollback accepts one active or historical revision identity in the same scope.
The kernel derives inverse edits from the recorded before/after descriptor
identities, validates their current expected versions, and creates a new
proposal and revision with `rollback_revision_id` set. It never deletes or
rewrites the target revision. Cross-scope rollback, rollback of an unknown
revision, and rollback across intervening conflicts fail before provider effect.

History reads expose only revision identities, safe timestamps or sequences,
entry kinds, action counts, digests, statuses, and rollback links. Inspecting
bodies requires separate private-read authority.

## Journal and crash recovery

Reuse `CanonicalJournal` and its persist-before-effect discipline. Harness
records use a harness-owned closed record vocabulary rather than changing
`asterion.agent-control/v1`:

- proposal recorded;
- provider effect started;
- provider effect terminal;
- snapshot activated;
- provider effect uncertain.

The reducer requires contiguous sequence, one scope identity, exact proposal
and effect digests, and at most one terminal outcome per revision. A restart
before provider effect safely retries the same admitted revision. A transport
loss after effect start but before a verified terminal receipt marks the
revision `uncertain` and fences replay. Recovery may reconcile it only by
reading the exact pinned Prime projection and proving the admitted digest; it
must not resend an unproven edit.

Snapshot activation happens only after the terminal provider receipt is durable.
If activation persistence fails, recovery derives the same snapshot from the
already terminal revision without reapplying the provider effect.

## Prime Gateway boundary

Add one authenticated private IPC surface for continual-harness operations. It
is not a public schema, capability manifest, command registry, or alternate
runner. The closed operations are:

| Operation | Boundary | Safe result |
| --- | --- | --- |
| `harness.snapshot` | Read one exact scoped Prime projection. | Scope digest, snapshot digest, sequence, and sorted entry identity/version/digest tuples. |
| `harness.apply` | Apply one already admitted deterministic edit set. | Effect digest and `succeeded`, `failed`, or `uncertain`. |
| `harness.propose` | Invoke the pinned model proposal engine under finite authority. | Proposal digest, private result reference, safe usage, and terminal status. |

The Gateway verifies the pinned source/artifact lock and exact refinement
exports before opening the IPC bridge. It never chooses scope, evidence,
credentials, model, budget, or activation. The Python selected-provider adapter
preserves the host proposal/effect identity and rejects any receipt drift.

## Evidence and cost boundaries

| Feature | Minimum boundary | Required proof |
| --- | --- | --- |
| `harness.prompt-entries` | real Prime provider-free | Create/update/delete one prompt addendum while the base prompt remains immutable. |
| `harness.memory-entries` | real Prime provider-free | Revisioned memory create/update/delete with body-free public history. |
| `harness.skill-descriptions` | real Prime provider-free | Skill descriptor requires an exact Python reference and argument contract. |
| `harness.subagent-specifications` | real Prime provider-free | Revisioned delegation specification remains data, not execution authority. |
| `harness.history-snapshots` | real Prime provider-free | Append-only revisions reduce to exact immutable snapshots across restart. |
| `harness.rollback` | real Prime provider-free | Rollback creates a new monotonic revision and preserves the target history. |
| `harness.scope-isolation` | real Prime provider-free | Session, project, and global roots cannot read, mutate, or shadow each other. |
| `harness.evidence-refinement` | bounded provider | One finite model proposal cites admitted evidence and cannot activate without host admission. |

Provider-free evidence requires a real pinned Prime process, zero model
credential reads, zero provider operations, a deterministic fault matrix, and
sentinel redaction. Fake adapters remain diagnostic-only and receive no parity
evidence ID.

The bounded command requires explicit operator opt-in and a named model,
maximum one provider operation, positive aggregate-token cap, nonnegative
micro-cost cap, and hard deadline. Preflight only proves readiness. A failed or
external-limited run never promotes the bounded feature, and prior receipts or
configuration never authorize a new run.

## Security and privacy

- Provider roots and private body roots must be explicit, non-symlinked, and
  opened without traversal or source scanning.
- Public exceptions use fixed messages and never chain provider payloads.
- Entry bodies, titles, rationales, expected outcomes, trajectories, model
  output, paths, environment values, and credentials remain private.
- Public receipts carry only canonical IDs, digests, counts, kinds, statuses,
  and safe usage.
- Skill and subagent entries are declarative descriptions. Creating or
  activating them never imports Python, spawns a child, executes a command, or
  widens authority.
- Manifests contain compatibility identities only; no harness body, provider
  configuration, executable path, mutable revision, or private root enters a
  manifest.

## Testing and verification

Implementation follows TDD and separates four gates:

1. Provider-neutral Python tests cover closed values, immutability, scope
   isolation, optimistic conflicts, monotonic revisions, rollback, replay,
   uncertainty, cancellation, and sentinel redaction.
2. Prime Gateway TypeScript tests cover exact IPC shapes, locked refinement
   exports, provider projection, body-free receipts, and fail-closed drift.
3. A real pinned Prime provider-free harness proves all seven deterministic
   scenarios with restart injection, zero provider operations, zero credential
   reads, and no owned process after close.
4. A separately authorized bounded harness proves only
   `harness.evidence-refinement` with one finite provider operation.

Named targets must distinguish the boundaries:

```bash
make test.prime-continual-harness.provider-free
make test.prime-continual-harness.bounded
uv run python tools/check_prime_parity.py --domain harness.continual --provider asterion.prime-gateway
make check
make promotion-check
git diff --check
```

The domain may report PASS only after seven exact provider-free evidence records
and one exact bounded record are committed. `asterion.native` remains Missing,
and system parity remains blocked on later domains.

## Non-goals

- Implementing the Asterion-native provider.
- Changing Prime's base system prompt or treating refinement as hidden-reasoning
  equivalence.
- Executing activated skills or subagents as part of refinement.
- Inferring project identity from a working directory or scanning for harness
  resources.
- Adding registries, version ranges, implicit precedence, or mutable authority
  to manifests.
- Reusing the previous bounded long-running authorization for a new model run.

## Acceptance criteria

- Every one of the eight ledger features maps to exactly one named scenario and
  evidence boundary.
- Asterion, not Prime, owns authority, scope, canonical revision history,
  activation, recovery, and public evidence.
- Session, project, and global state are isolated by explicit identities and
  roots; collisions never silently shadow.
- All state transitions are deterministic, monotonic, immutable, and recoverable
  without duplicate provider effects.
- Rollback creates a new revision and preserves append-only history.
- Provider-free gates prove seven real-Prime scenarios with zero provider and
  credential operations.
- The bounded scenario cannot run without new explicit finite authority and can
  promote only `harness.evidence-refinement`.
- Public surfaces and failure paths pass sentinel-redaction assertions.
- Repository and promotion gates remain provider-free and pass before the domain
  is described as verified.
