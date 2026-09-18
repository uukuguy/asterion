# Phase 7 — Asterion Prime P3 (recursive-workflow) Native Design

> Date: 2026-09-18. Companion to the 9-phase native detachment program
> (`docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md`).
> Phase 6 (P4) closed at `bd638cb6`. This spec defines **what** Phase 7
> (P3 rebuild) must produce; the implementation plan defines the **how**.

## Ground truth — what P3 is

Per the detachment spec (L247–L251, L342–L344):

> Use an Asterion-owned session factory and controlled child runner. Preserve
> depth, concurrency, budget, and cancellation limits without importing Prime
> RLM or child-session APIs.
>
> **P3 witness**: one root run starts an admitted child through
> `prime.child-runner`, the child result is joined into the root result, and
> exact depth / concurrency / budget limits reject further spawning **without
> Prime RLM APIs**.

P3 application-level identity (`src/asterion/applications/prime/assemblies/prime-recursive-workflow.json`):

- `application_id`: `prime.recursive-workflow`
- `package_id`: `prime-recursive-workflow-native`
- Required injected host services: `prime.child-runner`, `prime.p3-oracle`,
  `prime.pi-extension`, `prime.private-trace`, `prime.session-backend`
- Make preset: `asterion-prime-p3-run`

## Architectural principle — application-level capability demonstration

P1–P7 are applications that demonstrate Asterion Prime's capabilities and
architecture. From this lens, P3 is not a new runtime or a parallel agent —
it is one application-shaped demonstration of the existing Asterion Prime
substrate's **recursive composition** capability:

- The Asterion Prime session factory (P1/P2/P4 substrate) already creates
  sessions; P3 layers **child sessions admitted by an application-level
  runner** on top of that same factory.
- Depth / concurrency / budget / cancellation limits are framework-owned
  invariants enforced by `asterion.control` / `asterion.session_backend`
  (substrate: spec L177–L178). P3's witness is an *application-level*
  proof that these limits hold under recursive composition.
- The new `prime.child-runner` host service is the **single new** host
  service that P3 introduces; it is an application integration that
  composes the existing session factory under bounded controls.

## Substrate reuse versus new components

### Reused unchanged from the native P1/P2/P4 substrate

- `asterion.prime` session factory (`src/asterion/agents/prime/session.py`)
  and reusable Pi session lifecycle (spec L173–L176).
- `PrimeSessionBackend` (`src/asterion/agents/prime/backend.py`) —
  admit / budget / cancellation gate that P3 composes through.
- `prime.pi-extension` — exact injected Pi command + resource identity.
- `prime.private-trace` — private trace + public redaction surface.
- `prime.session-backend` — admission / budgets / cancellation host service.
- `prime.p3-oracle` — pattern-copies `prime.p1-oracle` / `prime.p4-oracle`
  with P3-specific invariants; same sealed-receipt shape.
- Capability-package + assembly JSON shape — verbatim from P1/P2/P4
  (validated by `validate_assembly_manifest` /
  `CapabilityPackageManifest` / `validate_capability_manifest`).
- Make preset `asterion-prime-p3-run` — Orb pattern copied from
  `asterion-prime-p4-run`, **but with one Orb invocation** (no cross-process
  witness is needed because P3 has no checkpoint / recovery edge).
- Provider gate pattern — `create_prime_recursive_workflow_provider()`
  exists; `create_provider()` adds P3 only after the witness passes.

### Newly introduced in Phase 7 (single new host service)

- `prime.child-runner` — application-level child session factory that
  composes `asterion.prime` session factory under framework-enforced
  depth / concurrency / budget / cancellation limits.
  - **Default path: in-process child session factory.** The child shares
    the parent's process but is admitted through a new isolated
    `PrimeSessionBackend.attach(next_identity)` with `generation`
    bumped by one and a new `child_run_id`. No subprocess supervisor.
  - **Fallback path: subprocess supervisor**, taken only when the
    application explicitly opts in (e.g., to isolate a child that has
    consumed a large context, or to enforce a per-child cost ceiling).
    Default preset **does not** use this fallback.
  - **Limits enforced by `prime.child-runner` (not by the framework
    alone, but the framework provides the gating primitives):**
    - `MAX_DEPTH` (default 2 — root + one child level; witness runs at
      this depth).
    - `MAX_CONCURRENT_CHILDREN` (default 1).
    - `MAX_CHILD_COST_USD` (default 0.10; witness enforces via the
      session backend's budget gate).
    - `MAX_TOTAL_DURATION_MS` (default 60_000; one minute for the whole
      recursive run).
  - Exceeding any limit returns a structured `ChildAdmissionRefused`
      rejection; no implicit retry, no fallback to a child.

### Explicitly NOT introduced (out of scope)

- No new checkpoint seal — P3 has no recovery semantics (per spec L344:
  witness is about depth/concurrency/budget limits, not continuity).
- No new host service for a candidate store (that's P6 territory).
- No Prime RLM or Prime SDK import of any kind (spec L251 hard constraint).
- No source-detachment gate changes (Phase 1 already owns that surface).
- No real-model invocation in the witness (P1/P7 territory).

## P3 oracle — three invariants

The oracle enforces P3's witness invariants, mirroring the P1/P2/P4 oracle
shape (frozen dataclass + `check(...) -> P3OracleReceipt`):

1. **child admitted**: `child_identity.generation == root.generation + 1`,
   `child_run_id != root_run_id`, `child_identity.session_backend_attached`
   is truthy.
2. **child joined into root**: the root result carries a `child_result_sha256`
   field equal to the sealed child receipt's result digest. No truncation
   allowed.
3. **limits reject**: a depth-3 attempt is refused with
   `child-admission-refused::depth-exceeded`; a budget-exhausted attempt is
   refused with `child-admission-refused::budget-exceeded`; a concurrent-2
   attempt is refused with `child-admission-refused::concurrency-exceeded`;
   a cancelled-mid-child attempt produces a `recovery-required` terminal
   without automatic replay.

## P3 sealed receipt — `P3NativeReceipt`

Shape (frozen, digest-stable):

```python
@dataclass(frozen=True)
class P3NativeReceipt:
    root_run_id: str
    root_generation: int
    child_run_id: str | None            # None if root ran alone
    child_generation: int | None        # root.generation + 1 if a child ran
    child_result_sha256: str | None     # sealed child result digest
    joined_result_sha256: str           # root + child, joined deterministically
    depth_reached: int                  # 1 if no child, 2 if one admitted child
    refusal_reason: str | None          # None on success; admission-refused code on failure
    receipt_sha256: str                 # digest of the canonical form
```

The `joined_result_sha256` is the deterministic SHA-256 of
`(root_result_sha256 || child_result_sha256 || depth_reached)`, encoded as
canonical JSON bytes. This makes "child joined into root" directly
verifiable without parsing prose.

## Witness strategy

`make asterion-prime-p3-run` runs **one** Orb invocation (vs P4's two):

1. Preflight: read 5 env vars (`ASTERION_PRIME_OPERATOR_ROOT`,
   `ASTERION_PRIME_P3_PRIVATE_ROOT`, `DEEPSEEK_API_KEY` if real-model,
   `ASTERION_PRIME_PI_ENTRY`, and the wheel URI).
2. Run the operator once. The operator runs the root run, admits one child
   at depth 2, joins the child result, emits a one-line JSON record.
3. The Makefile `jq -e` asserts:
   - `status == "completed"`, `child_run_id` non-null,
     `depth_reached == 2`,
   - `child_generation == root_generation + 1`,
   - `child_result_sha256 != root_result_sha256` (child did real work),
   - `joined_result_sha256` non-null, `receipt_sha256` non-null,
     `refusal_reason == null`.
4. A second `make asterion-prime-p3-run-limits` target runs four
   refusal-path tests (depth / budget / concurrency / cancellation) against
   the same operator in-process; each refusal produces a separate JSON
   record and the target asserts the right `refusal_reason`.

Both targets are operator-authorized work (need `make` from a real shell).

## Determinism and the fake-worker contract

The witness uses a deterministic fake-worker (mirror of P4's contract):

- The fake-worker receives `(mode, depth, run_id)` and emits a payload whose
  SHA differs across `(mode, depth, run_id)` tuples — so the no-replay
  and joined-result checks are meaningful.
- Real-model invocation is out of scope; the witness proves recursive
  composition semantics, not model capability.

## Failure behavior (spec L283–L292)

- Child admission refused → structured refusal reason, no model spawn,
  terminal `recovery-required` if the refusal happened mid-composition.
- Cancellation → bounded cleanup of all admitted children; one terminal
  result with `refusal_reason = "cancelled"`.
- Budget exceeded → refuse the next admission; do not interrupt the
  running child.
- Oracle failure → application failure, not framework success.

## Public redaction (spec L293–L295)

`P3PublicResult` MUST NOT include: prompts, model prose, generated code,
worker output, credentials, provider bodies, private paths, source
locations, raw external logs. Only the fields named in
`P3NativeReceipt` plus `status`, `private_root_redacted=True` are public.

## What Phase 7 must NOT do

- Touch the source-detachment gate.
- Drive a real Pi subprocess in the witness.
- Write the P5 plan.
- Use subprocess supervisor as the default child path (the in-process
  factory is the default per the architectural principle above).
- Import Prime Agent, Prime RLM, Prime SDK, or Prime Gateway anywhere.

## Migration order confirmation

Phase 7 is step **7** of the 9-phase program (rebuild P3); P4 is step 6
(closed); P5 is step 8 (next after this). The program order is fixed by
the detachment spec L267–L277.
