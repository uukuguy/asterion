# Prime P6 Continual Improvement Design

## Decision

`prime.continual-improvement/v1` is a fixed harness-refinement acceptance
product built on Asterion's existing provider-neutral `HarnessCoordinator` and
selected-Prime harness adapter. It does not reimplement Harness coordination,
revision storage, scope mapping, or rollback.

One closed workload admits evidence from task A, creates one small candidate
revision, evaluates a separate holdout task B, and either preserves the
revision on deterministic non-regression or applies the coordinator's exact
inverse rollback. The test surface is IPython-only; Harness effects remain
host-owned, not model tools.

## Alternatives considered

1. Treat the existing eight-row Harness parity matrix as P6. Rejected: it
   proves generic gateway behavior but not the required A-to-B causal product.
2. Create a new P6 revision engine. Rejected: it duplicates already verified
   append-only and inverse-rollback authority.
3. Add a narrow fixed product layer over the existing engine. Selected: it
   proves the required end-to-end causal chain without widening authority.

## Closed workload

The workload owns:

- scenario and worker role identities;
- distinct SHA-256 identities for task A evidence, candidate policy, task B
  oracle, model, schema, and fixed harness fixture;
- only `("ipython",)` as the model action surface;
- one candidate revision, one holdout evaluation, one rollback maximum, and
  finite action, usage, deadline, and cost ceilings;
- a bounded CRUD/type coverage matrix for `prompt`, `memory`, `skill`, and
  `subagent` across session and project scopes.

The fixed acceptance candidate is a project-scoped memory update. The coverage
matrix remains provider-free contract evidence, rather than a collection of
unbounded live edits. It excludes the immutable base prompt.

## Trace and acceptance

A private immutable trace binds the exact workload identities, baseline and
candidate snapshot digests, candidate revision digest, task-A evidence digest,
task-B result digest, terminal state, cleanup, and the declared outcome:
`preserved` or `rolled-back`.

- A preserved trace requires task B to be non-regressing and the candidate
  snapshot to remain active.
- A rollback trace requires task B to fail non-regression, exactly one inverse
  revision, and restoration of the baseline entry projection.
- No trace may contain prompt bodies, task text, rationale, filesystem paths,
  provider payloads, or credentials.
- A provider-free fake may validate causality and issue only provider-free
  evidence. It cannot yield bounded evidence.

The acceptance adapter receives an already-created `HarnessCoordinator`, an
injected holdout gate, and redacted identities. It validates the fixed trace,
requires an admitted candidate revision, performs exactly one holdout operation,
and accepts only the declared preserve or exact rollback outcome. It never
chooses scope, model, provider, retry policy, or gate command.

## Scope and global authority

Session and project effects use the existing isolated projections. A global
effect is rejected unless a separate exact operator authorization carries the
matching scope digest and `global_activation_approved is True`. This approval
does not authorize a model, Docker, network, or benchmark run.

The fixed P6 end-to-end fixture is project-scoped, so local tests prove global
approval rejection/acceptance as a boundary condition without mutating global
operator state.

## Evidence and live boundary

The live reducer requires a private admitted P6 trace, exact platform lock,
matching admitted restricted-worker boundary, task-B oracle attestation,
quiescent broker, destroyed worker, and—only for global scope—the exact global
approval. It revalidates these facts immediately before issuing bounded
evidence. Local tests exercise this reducer with fake data only; real
Prime/IPython worker evidence remains External-limited until separately
authorized.

## Verification

Provider-free tests cover canonical workload identity, every trace branch,
identity and ceiling mismatches, unchanged/mismatched snapshots, holdout replay,
rollback exactness, base-prompt rejection, global-approval gating, redaction,
and fake-chain evidence level. They run without Docker, a model, network, or
`.env` access. Scoped unittest, Ruff, Pyright, and `git diff --check` are the
local verification boundary.
