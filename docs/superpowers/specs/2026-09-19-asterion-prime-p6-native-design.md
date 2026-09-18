# Phase 9 — Asterion Prime P6 (continual-improvement) Native Design

> Date: 2026-09-19. Companion to the 9-phase native detachment program
> (`docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md`).
> Phase 8 (P5) closed at `0a74bc1a`. This spec defines **what** Phase 9
> (P6 rebuild) must produce; the implementation plan defines the **how**.

## Ground truth — what P6 is

Per the detachment spec (L259–L264, L351–L353, L116):

> Compose the preceding native capabilities into bounded evaluation, candidate
> change, and explicit promotion. Prior evidence or cached configuration never
> grants execution or promotion authority.
>
> **P6 witness**: a candidate is evaluated against a fixed baseline, a
> non-improving candidate is rejected without promotion, and an improving
> candidate requires an explicit admitted promotion action before becoming
> current.

| Phase | Application ID | Capability package ID | Assembly path | Required injected host services | Formal Make preset |
|---|---|---|---|---|---|
| P6 | `prime.continual-improvement` | `prime-continual-improvement-native` | `src/asterion/applications/prime/assemblies/prime-continual-improvement.json` | `prime.candidate-store`, `prime.p6-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend` | `asterion-prime-p6-run` |

Per the pre-detachment P6 spec
(`docs/superpowers/specs/2026-09-04-prime-p6-continual-improvement-design.md`):

- **Closed workload (verbatim, spec L26–L36):** one closed workload admits
  evidence from task A, creates one small candidate revision, evaluates a
  separate holdout task B, and either preserves the revision on deterministic
  non-regression or applies the coordinator's exact inverse rollback. The
  test surface is IPython-only; Harness effects remain host-owned, not model
  tools. The workload owns distinct SHA-256 identities for task A evidence,
  candidate policy, task B oracle, model, schema, and fixed harness fixture;
  one candidate revision, one holdout evaluation, one rollback maximum, and
  finite action, usage, deadline, and cost ceilings.
- **Trace and acceptance (spec L42–L62):** a private immutable trace binds
  the exact workload identities, baseline and candidate snapshot digests,
  candidate revision digest, task-A evidence digest, task-B result digest,
  terminal state, cleanup, and the declared outcome: `preserved` or
  `rolled-back`. A preserved trace requires task B to be non-regressing and
  the candidate snapshot to remain active; a rollback trace requires task B
  to fail non-regression, exactly one inverse revision, and restoration of
  the baseline entry projection. The acceptance adapter receives an
  already-created `HarnessCoordinator`, an injected holdout gate, and
  redacted identities. It validates the fixed trace, requires an admitted
  candidate revision, performs exactly one holdout operation, and accepts
  only the declared preserve or exact rollback outcome. It never chooses
  scope, model, provider, retry policy, or gate command.
- **Scope and global authority (spec L64–L73):** session and project effects
  use the existing isolated projections. A global effect is rejected unless
  a separate exact operator authorization carries the matching scope digest
  and `global_activation_approved is True`. This approval does not
  authorize a model, Docker, network, or benchmark run. The fixed P6
  end-to-end fixture is project-scoped, so local tests prove global
  approval rejection/acceptance as a boundary condition without mutating
  global operator state.

The user has confirmed the **architectural principle**:
`prime.candidate-store` is a new host service that **WRAPS** the
framework-owned `HarnessCoordinator` (does not reimplement it) — composition,
not duplication. The pre-detachment spec's explicit clause L8–L9 ("It does
not reimplement Harness coordination, revision storage, scope mapping, or
rollback") and the framework substrate at `src/asterion/control/harness.py`
support this: `HarnessCoordinator` already owns the append-only revision
authority, scope-boundary record, and inverse-rollback logic. P6 layers an
application-level lifecycle on top.

## Architectural principle — application-level capability demonstration

P1–P7 are applications that demonstrate Asterion Prime's capabilities and
architecture. From this lens, P6 is not a new runtime or a parallel agent —
it is one application-shaped demonstration of Asterion Prime's
**continual-improvement** capability:

- The framework-owned `HarnessCoordinator` (`src/asterion/control/harness.py`)
  already exposes append-only revision authority (`apply(proposal) ->
  HarnessRevision`), scope-boundary record (`HarnessScope`), inverse rollback
  (`rollback(...)`), recovery (`recover()`), and snapshot projection
  (`snapshot()`). P6 layers an **admitted-candidate lifecycle** on top of
  that engine: admit candidate → evaluate on holdout → preserve or
  rollback.
- Bounded action / usage / deadline / cost ceilings are framework-owned
  limits enforced through `PrimeSessionBackend` (substrate: spec L177–L178);
  P6 reads duration elapsed and checks cancellation through the session
  backend. P6's witness is an *application-level* proof that the continual
  improvement capability stops exactly on the closed outcome enum
  (`preserved` | `rolled-back`).
- The new `prime.candidate-store` host service is the **single new** host
  service that P6 introduces. It composes `prime.pi-extension` (admit
  candidate revision through IPython session) and `prime.p6-oracle` (holdout
  evaluation + verdict) under the framework-owned `HarnessCoordinator`'s
  append-only revision authority.

P5 and P6 both compose the native substrate; P5's loop is one-shot
(propose / verify / repair) and P6's is two-stage (admit candidate →
evaluate on holdout → preserve or rollback). Both wrap framework-owned
engines under bounded controls; neither introduces a new framework-level
type.

## Substrate reuse versus new components

### Reused unchanged from the native P1/P2/P3/P4/P5 substrate

- `asterion.prime` session factory (`src/asterion/agents/prime/session.py`)
  and reusable Pi session lifecycle (spec L173–L176).
- `PrimeSessionBackend` (`src/asterion/agents/prime/backend.py`) —
  admit / budget / cancellation gate that P6 composes through for the
  duration cap and for cancellation propagation.
- `PrimeBackendIdentity` / `PrimeCheckpoint` (`state.py:73, :160`) —
  reused unchanged. P6 has no checkpoint / recovery semantics (P4 owns
  that surface), so `open_continued()` is **not** introduced here.
- `prime.pi-extension` — exact injected Pi command + resource identity.
- `prime.private-trace` — private trace + public redaction surface.
- `prime.session-backend` — admission / budgets / cancellation host
  service (P6 reads duration elapsed and the cancellation signal from
  the session backend).
- `prime.p6-oracle` — pattern-copies `prime.p1-oracle` / `prime.p3-oracle`
  / `prime.p4-oracle` / `prime.p5-oracle` with P6-specific invariants;
  same sealed-receipt shape.
- **Framework-owned `HarnessCoordinator`** (`src/asterion/control/harness.py`):
  append-only revision authority, scope-boundary record, inverse rollback,
  recovery, and snapshot projection. P6 wraps this engine; P6 does **not**
  reimplement any of these primitives.
- **Framework-owned `HarnessScope`** (`src/asterion/control/harness.py:50`):
  the closed 3-element enum `{"session", "project", "global"}`. P6 uses
  this scope mapping unchanged.
- **Framework-owned `MemoryHarnessPrivateRevisionStore`** (same module,
  `L487`): the in-memory private proposal / snapshot store. P6 uses this
  as the default `private_store` injected into the wrapped coordinator.
- **Framework-owned canonical-form helper** `_mapping_digest(...)` and the
  shape of `_snapshot_id(...)` / `_revision_id(...)`: reused unchanged for
  P6's receipt SHA.
- Capability-package + assembly JSON shape — verbatim from P1/P2/P3/P4/P5
  (validated by `validate_assembly_manifest` /
  `CapabilityPackageManifest` / `validate_capability_manifest`).
- Make preset `asterion-prime-p6-run` — Orb pattern copied from
  `asterion-prime-p5-run`, with one Orb invocation per mode (`preserved` /
  `rolled-back` / `global-rejected`), no cross-process supervisor (P6 has
  no checkpoint / recovery edge).
- Provider gate pattern — `create_prime_continual_improvement_provider()`
  exists; `create_provider()` adds P6 only after the witness passes.

### Newly introduced in Phase 9 (single new host service)

- `prime.candidate-store` — application-level wrapper around
  `HarnessCoordinator` that owns the admitted-candidate lifecycle +
  scope-boundary record + global-approval record. It does **not**
  reimplement the coordinator's append-only revision authority, the
  scope mapping, the inverse-rollback logic, or the snapshot projection;
  it composes them.
  - **Default scope: `project`** (matches the pre-detachment spec's
    fixed acceptance candidate — a project-scoped memory update — and
    the witness's local-testability requirement). The acceptance
    adapter is permitted to construct a coordinator at scope
    `session` or `project`; scope `global` requires a separate exact
    operator authorization carrying `global_activation_approved is
    True` (rejection of `global_activation_approved = False` is a
    boundary surface, NOT a separate terminal outcome).
  - **Single candidate revision per run** — the pre-detachment spec's
    "one candidate revision" clause is enforced at the wrapper boundary,
    not inside the coordinator. The wrapper refuses a second
    `apply(proposal)` call after the first one has produced a
    `HarnessRevision`.
  - **Single holdout evaluation per run** — the pre-detachment spec's
    "one holdout evaluation" clause. The wrapper refuses a second
    `evaluate_holdout(...)` call after the first one has produced a
    `HoldoutResult`.
  - **One rollback maximum** — the pre-detachment spec's "one rollback
    maximum" clause. The wrapper refuses a second `rollback(...)` call
    after the first one has produced an inverse `HarnessRevision`.
  - **Finite action / usage / deadline / cost ceilings** — carried from
    `PrimeSessionBackend`'s budget gate. Defaults: `MAX_ACTIONS = 1`
    (admit), `MAX_USAGE_PROVIDER_OPS = 4` (one each: admit + evaluate
    + optional promote / rollback + one overhead), `MAX_DEADLINE_MS =
    60_000` (one minute for the whole evaluate-and-decide cycle),
    `MAX_COST_USD = 0.05` (mirrors P5's per-loop cost ceiling).
  - **Stopping conditions (closed 3-element enum, exhaustive, the
    oracle's verdict set):**
    - `preserved` — holdout non-regressing, candidate snapshot active.
    - `rolled-back` — holdout regressing, exactly one inverse
      revision, baseline entry projection restored.
    - `global-rejected` — scope=`global` without
      `global_activation_approved=True`. Boundary rejection
      pre-orchestration (does not enter the harness journal). NOT a
      terminal outcome of the run itself; the receipt's
      `terminal_outcome` folds this case into `"rolled-back"` with
      `global_activation_approved = False` so the closed 2-element
      `terminal_outcome` enum stays closed.
  - **No implicit retry, no autonomous continuation.** A run that
    hits any non-`preserved` terminal returns a sealed
    `P6NativeReceipt` exactly once; there is no background retry, no
    deferred continuation, no "still running" state in the public
    output. Prior evidence or cached configuration never grants
    promotion authority (detachment spec L262–L263).

### Explicitly NOT introduced (out of scope)

- No new checkpoint seal — P6 has no recovery semantics
  (`prime.continuity-store` is P4's surface; P6 does not introduce
  it).
- No new `HarnessCoordinator` / `HarnessScope` /
  `MemoryHarnessPrivateRevisionStore` — the framework substrate is
  reused unchanged. P6 layers an application-level wrapper on top.
- No `prime.bounded-autonomy` reuse (P5 owns bounded-loop semantics).
- No `prime.continuity-store` reuse (P4 owns checkpoint / recovery).
- No `prime.child-runner` reuse (P3 owns recursive composition).
- No new framework-level harness types. The boundary of
  `src/asterion/control/harness.py` stays framework-owned and
  domain-neutral.
- No subprocess supervisor (P6 single-process; in-process wrapper is
  the default path, mirror of P5's `asyncio` loop default).
- No real-model invocation in the witness (P1/P7 territory).
- No source-detachment gate changes (Phase 1 already owns that
  surface).

## P6 oracle — three invariants

The oracle enforces P6's witness invariants, mirroring the P1/P3/P4/P5
oracle shape (frozen dataclass + `check(...) -> P6OracleReceipt`):

1. **candidate admitted**: `HarnessCoordinator.apply(proposal)` returned a
   non-empty `HarnessRevision` with a `revision_id` that differs from the
   baseline snapshot's `revision_id` (or equals `None` on iteration 1, when
   `sequence == 1`).
2. **holdout evaluated**: `evaluate_holdout(candidate, baseline)` returned a
   `HoldoutResult` whose `task_b_result_sha256` and `non_regressing: bool`
   are both set. `task_b_result_sha256` is a 64-hex SHA-256 that differs
   from the baseline snapshot digest on the `preserved` path (proves the
   candidate produced different task B output, not a replay).
3. **explicit promotion / exact rollback**:
   - `preserved` outcomes require an `apply(promotion_action)` call —
       i.e. an explicit promotion action — before the receipt seals.
       Without that promotion action, the oracle refuses to seal as
       `preserved` and returns reason
       `invariant-violation::missing-promotion-action`.
   - `rolled-back` outcomes require `rollback(...)` with the exact
       inverse revision produced in step 1. Without that rollback call,
       the oracle refuses to seal as `rolled-back` and returns reason
       `invariant-violation::missing-rollback-call`.
   - `global-rejected` verdicts short-circuit pre-orchestration: no
       `HarnessRevision` is created, the baseline snapshot is unchanged,
       and the receipt seals with `terminal_outcome = "rolled-back"` and
       `global_activation_approved = False`. The `global-rejected`
       verdict is a boundary surface of the wrapper, not a separate
       terminal class of the run; this keeps the closed 2-element
       `terminal_outcome` enum (`preserved` | `rolled-back`) closed.

The oracle is a **closed 3-string verdict enum**:
`{"preserved", "rolled-back", "global-rejected"}`. The
`global-rejected` verdict is the wrapper's pre-orchestration boundary
rejection; the oracle returns it directly.

## P6 sealed receipt — `P6NativeReceipt`

Shape (frozen, digest-stable, canonical-form):

```python
@dataclass(frozen=True)
class P6NativeReceipt:
    root_run_id: str                          # operator's stable run identifier
    baseline_snapshot_digest: str             # 64-hex SHA-256 of canonical-form baseline entry projection
    candidate_revision_digest: str            # 64-hex SHA-256 of canonical-form HarnessRevision
    task_a_evidence_digest: str               # 64-hex SHA-256 of canonical-form task A evidence
    task_b_result_digest: str                 # 64-hex SHA-256 of canonical-form task B holdout result
    terminal_outcome: str                     # closed 2-element enum: "preserved" | "rolled-back"
    global_activation_approved: bool          # False for project-scope; True ONLY for global-scope with operator authorization
    rollback_invocation_count: int            # 0 if preserved; 1 if rolled-back (single inverse revision per design L52)
    receipt_sha256: str                       # 64-hex SHA-256 of the canonical form
```

Notes on the closed enum:

- The oracle has a **closed 3-element verdict enum** (`preserved` /
  `rolled-back` / `global-rejected`) — the verdict the wrapper produces.
- The receipt has a **closed 2-element `terminal_outcome` enum**
  (`preserved` / `rolled-back`) — the public-safe declaration of what
  happened. The `global-rejected` verdict folds into `rolled-back` with
  `global_activation_approved = False` so the public enum stays at 2.
- Cancellation, candidate-admission errors, holdout-evaluation errors,
  and promotion-action errors all fold into `terminal_outcome =
  "rolled-back"` with a diagnostic digest in the receipt (see
  `Failure behavior` below). They are NOT additional terminal outcomes.
- This keeps every public enum closed: 3 oracle verdicts, 2 receipt
  terminal outcomes, 4 diagnostic digest fields
  (`candidate_admission_error_digest` /
  `holdout_evaluation_error_digest` / `promotion_action_error_digest`
  / `cancellation_digest`, each 64-hex SHA-256 and only present when
  the corresponding path actually fired).

## Witness strategy

`make asterion-prime-p6-run` runs **three** Orb invocations (one per
mode: `preserved` / `rolled-back` / `global-rejected`). Each invocation
runs the operator once against the same `prime.candidate-store` host
service. `make asterion-prime-p6-run-verbose` is the diagnostic
sibling that emits the per-step admission + holdout stream (no
assertions).

**Preserved Orb invocation** (proves the witness's third clause: "an
improving candidate requires an explicit admitted promotion action
before becoming current"):

1. Preflight: read 5 env vars (`ASTERION_PRIME_OPERATOR_ROOT`,
   `ASTERION_PRIME_P6_PRIVATE_ROOT`, `ASTERION_PRIME_PI_ENTRY`,
   `DEEPSEEK_API_KEY` if real-model, and the wheel URI).
2. Run the operator once with `ASTERION_PRIME_P6_MODE=preserved`.
   The wrapper:
   - admits candidate via `HarnessCoordinator.apply(proposal)` →
     receives `HarnessRevision(revision_id=...)` differing from the
     baseline's `revision_id=None`;
   - evaluates on task B holdout (`evaluate_holdout(candidate,
     baseline)`) → `HoldoutResult(task_b_result_sha256=<digest>,
     non_regressing=True)`;
   - applies the **explicit promotion action** via
     `apply(promotion_action)` (the pre-detachment spec's "explicit
     admitted promotion action");
   - seals `P6NativeReceipt` with
     `terminal_outcome="preserved"`,
     `global_activation_approved=False`,
     `rollback_invocation_count=0`.
3. The Makefile `jq -e` asserts:
   - `status == "completed"`,
     `terminal_outcome == "preserved"`,
     `global_activation_approved == false`,
     `rollback_invocation_count == 0`,
     `task_b_result_digest` non-null and differs from the baseline
     snapshot digest,
     `candidate_revision_digest` non-null and differs from the
     baseline snapshot digest,
     `receipt_sha256` non-null.

**Rolled-back Orb invocation** (proves the witness's second clause:
"a non-improving candidate is rejected without promotion"):

1. Re-invoke operator with `ASTERION_PRIME_P6_MODE=rolled-back`.
2. The wrapper:
   - admits candidate via `HarnessCoordinator.apply(proposal)` →
     receives `HarnessRevision(revision_id=...)`;
   - evaluates on task B holdout →
     `HoldoutResult(task_b_result_sha256=<digest>, non_regressing=False)`;
   - applies `rollback(...)` with the **exact inverse revision** from
     the admit step (single inverse revision per pre-detachment spec
     L52);
   - seals `P6NativeReceipt` with
     `terminal_outcome="rolled-back"`,
     `rollback_invocation_count=1`.
3. The Makefile `jq -e` asserts:
   - `terminal_outcome == "rolled-back"`,
     `rollback_invocation_count == 1`,
     `candidate_revision_digest` non-null (the admitted revision
     existed before rollback),
     the `rollback_invocation_count` field equals exactly 1 (one
     inverse revision, no second rollback),
     baseline snapshot's `revision_id` returned to `None` after the
     inverse revision activated
     (`HarnessSnapshot.revision_id is None` post-rollback).

**Global-rejected Orb invocation** (proves the global-scope boundary
per pre-detachment spec L64–L73):

1. Re-invoke operator with `ASTERION_PRIME_P6_MODE=global-rejected`.
2. The wrapper constructs the coordinator at scope `global` with
   `global_activation_approved=False`. The boundary check fires
   pre-orchestration: no `HarnessRevision` is created, no holdout
   evaluation runs, baseline snapshot unchanged. The wrapper seals
   `P6NativeReceipt` with
   `terminal_outcome="rolled-back"` and
   `global_activation_approved=False`. The oracle's verdict is
   `"global-rejected"` (private to the oracle); the public receipt's
   `terminal_outcome` is `"rolled-back"` because the boundary
   rejection means no admission happened, equivalent to a
   rollback-without-effect from the public contract's perspective.
3. The Makefile `jq -e` asserts:
   - `terminal_outcome == "rolled-back"`,
     `global_activation_approved == false`,
     `rollback_invocation_count == 0` (no rollback was issued; the
     boundary rejection was pre-orchestration),
     `candidate_revision_digest` equals the baseline snapshot
     digest (no candidate was admitted).

All three records emitted via `jq -s slurp + .[N]` index — mirror P5's
fix-on-verify (`5c07d9ff`) that bash 3.2.57 (macOS default) requires
single-line jq expressions.

## Determinism and the fake-worker contract

The witness uses a deterministic fake-worker (mirror of P3/P4/P5's
contract):

- The fake-worker receives `(mode, candidate_kind, run_id)` and
  emits a payload whose SHA differs across tuples — so the
  `task_b_result_digest`, `candidate_revision_digest`, and
  `receipt_sha256` checks are meaningful.
- For `preserved` mode: task B result must differ from the baseline
  snapshot digest AND `non_regressing=True`.
- For `rolled-back` mode: `non_regressing=False`.
- For `global-rejected` mode: scope=`global` triggers
  pre-orchestration rejection; no task B evaluation runs.
- Real-model invocation is out of scope; the witness proves continual
  improvement semantics (bounded evaluation against a fixed
  baseline + explicit promotion), not model capability.

## Failure behavior (spec L283–L292)

- **Cancellation** → bounded cleanup of any in-flight holdout
  evaluation; one terminal result with
  `terminal_outcome="rolled-back"`, the cancellation-digest set, no
  further provider work. `recovery-required` is the framework-level
  marker for "stop without automatic replay"; it folds into the
  `rolled-back` terminal outcome so the public enum stays at 2.
- **Oracle fail** → application failure, not framework success. The
  operator emits `recovery-required` via the runner's terminal-event
  shape; the receipt does not seal (the receipt boundary fails
  closed).
- **Candidate admission fail** (`HarnessCoordinator.apply(proposal)`
  raises `HarnessError` — scope mismatch, baseline conflict, replay
  conflict) → terminal `rolled-back` with
  `rollback_invocation_count=0` and a
  `candidate_admission_error_digest` in the receipt. NOT a 3rd
  terminal outcome — folds into `rolled-back`.
- **Holdout evaluation fail** (oracle cannot produce a
  `HoldoutResult`; raised exception) → terminal `rolled-back` with a
  `holdout_evaluation_error_digest` in the receipt. Folds into
  `rolled-back`.
- **Promotion action fail** (post-holdout `apply(promotion_action)`
  raises `HarnessError` because the candidate snapshot was not the
  current snapshot, or because scope=global without
  `global_activation_approved=True`) → terminal `rolled-back` with a
  `promotion_action_error_digest` in the receipt. Folds into
  `rolled-back`.

All four error paths seal the receipt with `terminal_outcome =
"rolled-back"`; the public enum stays at 2. Each error path's
diagnostic digest is a 64-hex SHA-256 of the canonical-form
exception payload (kind + message + frame fingerprints only — no
prompt bodies, no model prose, no source locations).

## Public redaction (spec L293–L295)

`P6PublicResult` MUST NOT include: prompts, model prose, generated
code, worker output, credentials, provider bodies, private paths,
source locations, raw external logs, the per-step holdout verdict
stream, or the wrapper's internal `global-rejected` verdict (that
verdict is private to the oracle; the public surface expresses it
through `terminal_outcome="rolled-back"` +
`global_activation_approved=False`). Only the fields named in
`P6NativeReceipt` plus `status` and `private_root_redacted=True` are
public. The verbose-mode stdout is operator-only and never enters the
witness record.

## What Phase 9 must NOT do

- Touch the source-detachment gate.
- Drive a real Pi subprocess in the witness.
- Write the P1/P2/P3/P4/P5 regression plans (those are already
  closed; Phase 9 only mirrors the Task-16 publisher-edit step on
  top of the existing 6-app public selector).
- Introduce `prime.continual-improvement-loop` (or
  `prime.continual-improvement-store` with a different name) as a
  separate host service — the single `prime.candidate-store` is the
  only new host service in Phase 9.
- Reuse `prime.bounded-autonomy` (P5 owns bounded-loop semantics),
  `prime.continuity-store` (P4 owns checkpoint / recovery), or
  `prime.child-runner` (P3 owns recursive composition). P6 has none
  of those surfaces.
- **Reimplement** `HarnessCoordinator` / `HarnessScope` /
  `MemoryHarnessPrivateRevisionStore` — the framework substrate is
  reused unchanged. P6 wraps the engine; P6 does not duplicate it.
- Use a subprocess supervisor as the default wrapper path (the
  in-process wrapper is the default per the architectural principle
  above; a future cross-process isolation requirement would be a
  separate phase).
- Inherit an SDK agent loop (spec L257 hard constraint — the
  detached P1–P7 family does not inherit any SDK agent loop; P6
  layers on the framework-owned `HarnessCoordinator` only).
- Clean the stale
  `src/asterion/applications/prime_agent/__pycache__/continual_improvement_*.pyc`
  files. They are vestigial, harmless, and the `.py` source has
  already been detached in Phase 1. A future hygiene pass owns
  this; Phase 9 leaves it alone to keep the diff focused on the P6
  rebuild.
- Promote any implemented-but-not-yet-witnessed P6 component to PASS
  in status documents. Promotion happens only after
  `make asterion-prime-p6-run` (all three Orb invocations) returns
  exit 0.

## Migration order confirmation

Phase 9 is step **9** of the 9-phase program (rebuild P6 — the final
package). Phase 8 (P5) closed at `0a74bc1a`. P6 is the program
closer. The program order is fixed by the detachment spec L267–L277
(removal → source-detachment gate → P7 anchor → P1 → P2 → P4 → P3 →
P5 → P6).
