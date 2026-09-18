# Phase 8 — Asterion Prime P5 (bounded-autonomy) Native Design

> Date: 2026-09-19. Companion to the 9-phase native detachment program
> (`docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md`).
> Phase 7 (P3) closed at `fec56274`. This spec defines **what** Phase 8
> (P5 rebuild) must produce; the implementation plan defines the **how**.

## Ground truth — what P5 is

Per the detachment spec (L253–L257, L348–L350, L116):

> Compose native tool execution, child work, verification, and recovery into a
> finite propose/verify/repair loop. It must have exact stopping conditions and
> must not inherit an SDK agent loop.
>
> **P5 witness**: a finite propose/verify/repair run performs at least one
> failed verification and one bounded repair, then stops on success or the exact
> iteration cap with no autonomous continuation afterward.
>
> Required injected host services: `prime.ipython`, `prime.p5-oracle`,
> `prime.pi-extension`, `prime.private-trace`, `prime.session-backend`.
> Make preset: `asterion-prime-p5-run`.

Per the pre-detachment P5 blueprint
(`docs/superpowers/plans/2026-09-04-prime-p5-bounded-autonomy.md`):

- **Fixed IPython-only repair loop** (not multi-application): the loop's
  propose / repair steps both run through `prime.ipython`.
- **Workspace-digest deduplication**: an unchanged workspace digest within the
  same run rejects a second gate (no infinite repair loops).
- **Provider-free acceptance cannot issue bounded evidence** — only an
  admitted worker boundary plus operator authorization may issue a live
  receipt.
- **Deterministic gate feedback**: each loop step has oracle-verifiable
  feedback so the verify step is reproducible from the trace.

The user has confirmed **single loop host service** `prime.bounded-autonomy`
(not three separate `proposer` / `verifier` / `repairer` services, not a
child-runner reuse). The loop controller is one new host service that
internally calls `prime.ipython` for propose / repair steps and a new
`prime.p5-oracle` for verify steps.

## Architectural principle — application-level capability demonstration

P1–P7 are applications that demonstrate Asterion Prime's capabilities and
architecture. From this lens, P5 is not a new runtime or a parallel agent —
it is one application-shaped demonstration of Asterion Prime's **bounded
autonomy** capability:

- The Asterion Prime session factory (P1/P2/P4 substrate) already exposes
  IPython sessions; P5 layers a **finite propose/verify/repair loop** on
  top of that same factory and the framework-owned `PrimeSessionBackend`
  budget / cancellation gate.
- Iteration / duration / no-progress caps are framework-owned limits
  enforced through `PrimeSessionBackend` (substrate: spec L177–L178) plus
  application-level counters. P5's witness is an *application-level*
  proof that bounded autonomy stops exactly when the cap fires.
- The new `prime.bounded-autonomy` host service is the **single new** host
  service that P5 introduces; it composes `prime.ipython` (propose / repair)
  and `prime.p5-oracle` (verify) under bounded controls.

## Substrate reuse versus new components

### Reused unchanged from the native P1/P2/P3/P4 substrate

- `asterion.prime` session factory (`src/asterion/agents/prime/session.py`)
  and reusable Pi session lifecycle (spec L173–L176).
- `PrimeSessionBackend` (`src/asterion/agents/prime/backend.py`) —
  admit / budget / cancellation gate that P5 composes through for the
  duration cap and for cancellation propagation.
- `PrimeBackendIdentity` / `PrimeCheckpoint` (`state.py:73, :160`) —
  reused unchanged. P5 has no checkpoint / recovery semantics (P4 owns
  that surface), so `open_continued()` is **not** introduced here.
- `prime.ipython` — exact injected IPython host service reused for the
  propose step **and** the repair step. P5 does not introduce a new
  worker protocol.
- `prime.pi-extension` — exact injected Pi command + resource identity.
- `prime.private-trace` — private trace + public redaction surface.
- `prime.session-backend` — admission / budgets / cancellation host
  service (P5 reads duration elapsed from the session backend).
- `prime.p5-oracle` — pattern-copies `prime.p1-oracle` / `prime.p3-oracle`
  / `prime.p4-oracle` with P5-specific invariants; same sealed-receipt
  shape.
- Capability-package + assembly JSON shape — verbatim from P1/P2/P3/P4
  (validated by `validate_assembly_manifest` /
  `CapabilityPackageManifest` / `validate_capability_manifest`).
- Make preset `asterion-prime-p5-run` — Orb pattern copied from
  `asterion-prime-p4-run`, with one Orb invocation per mode (success /
  limits), no cross-process supervisor (P5 has no checkpoint / recovery
  edge).
- Provider gate pattern — `create_prime_bounded_autonomy_provider()`
  exists; `create_provider()` adds P5 only after the witness passes.

### Newly introduced in Phase 8 (single new host service)

- `prime.bounded-autonomy` — application-level loop controller that
  composes `prime.ipython` and `prime.p5-oracle` under framework-enforced
  duration / iteration / progress limits.
  - **Default path: in-process loop** (no subprocess supervisor,
    mirror D-2026-09-18-02). The loop runs in the same process as the
    operator; cancellation is a single `asyncio.Event` that the loop
    checks between iterations.
  - **Limits enforced (closed set, framework-owned primitives + closed
    application-level counters):**
    - `MAX_ITERATIONS` (default 3 — one propose, one failed verify,
      one repair, then stop; the success-path witness hits
      `terminal_reason == "success"` at iteration 2; the limits-path
      witness hits `terminal_reason == "iteration-cap-exceeded"` after
      3 failed verify steps).
    - `MAX_REPAIR_DURATION_MS` (default 30_000 per repair step; the
      repair step aborts and the loop records
      `last_step_kind = "repair"`, `last_step_timed_out = True`).
    - `MAX_TOTAL_DURATION_MS` (default 120_000 for the whole loop;
      wall-clock from the first propose step; the loop records
      `terminal_reason = "duration-cap-exceeded"` and the iteration
      counter at the moment of the cap).
    - `WORKSPACE_DIGEST_DEDUP` — unchanged workspace digest within the
      same run rejects a second gate: the loop computes the workspace
      digest at the end of each propose / repair step; if the new
      digest equals the digest recorded at the previous gate, the loop
      refuses the verify step and records
      `terminal_reason = "no-progress"`.
  - **Stopping conditions (closed enum, exhaustive):**
    - `success` — oracle passes → terminate with reason `success`.
    - `iteration-cap-exceeded` — `MAX_ITERATIONS` reached without a
      passing verify → terminate.
    - `duration-cap-exceeded` — `MAX_TOTAL_DURATION_MS` elapsed
      → terminate.
    - `no-progress` — workspace digest unchanged between two adjacent
      steps → terminate.
    - `cancelled` — cancellation signal observed → bounded cleanup,
      one terminal result (spec L291).
  - **No implicit retry, no autonomous continuation.** A run that
    hits any non-`success` terminal returns a sealed
    `P5NativeReceipt` exactly once; there is no background retry, no
    deferred continuation, no "still running" state in the public
    output. This is the spec's "no autonomous continuation afterward"
    clause (L349) enforced at the receipt boundary.

### Explicitly NOT introduced (out of scope)

- No new checkpoint seal — P5 has no recovery semantics
  (`prime.continuity-store` is P4's surface; P5 does not introduce
  it).
- No new `prime.proposer` / `prime.verifier` / `prime.repairer` host
  services. The single `prime.bounded-autonomy` controller is the
  one new host service; the propose / verify / repair verbs are
  internal methods on it, not separate injection points.
- No source-detachment gate changes (Phase 1 already owns that
  surface).
- No real-model invocation in the witness (P1/P7 territory).
- No SDK agent-loop inheritance — the loop controller is
  application-level, not framework-level. A future shared-substrate
  change that wants a generic bounded-loop primitive would have to
  prove it does not absorb P5's closed refusal enum, otherwise the
  loop controller stays in P5.

## P5 oracle — three invariants

The oracle enforces P5's witness invariants, mirroring the P1/P3/P4 oracle
shape (frozen dataclass + `check(...) -> P5OracleReceipt`):

1. **propose admitted**: `propose_step` produced a non-empty candidate
   artifact; the candidate has a `workspace_digest_sha256` field that
   differs from the prior digest (or equals `None` on iteration 1).
2. **verify failed then repaired**: the run includes
   `verify_step_count >= 1` with at least one
   `oracle_verdict == "fail"`, followed by
   `repair_step_count >= 1` whose post-repair
   `workspace_digest_sha256` differs from the prior digest. (The
   success-path witness shows verify-fail → repair → verify-pass;
   the limits-path witness shows 3 verify-fail without a
   workspace-progressing repair.)
3. **bounded stop**: the run terminates with one of
   `{success, iteration-cap-exceeded, duration-cap-exceeded,
   no-progress, cancelled}` — NOT a `still-running` state, an
   empty `terminal_reason`, or an iteration count higher than
   `MAX_ITERATIONS`.

The oracle is a **closed 4-string verdict enum**:
`{"pass", "fail", "no-progress", "cancelled"}`. The "no-progress"
verdict is recorded when the oracle itself observes an unchanged
workspace digest; the loop controller then records
`terminal_reason = "no-progress"` and stops.

## P5 sealed receipt — `P5NativeReceipt`

Shape (frozen, digest-stable):

```python
@dataclass(frozen=True)
class P5NativeReceipt:
    root_run_id: str                       # loop's stable run identifier
    root_generation: int                   # always 1; P5 has no continuity
    propose_step_count: int                # >= 1
    verify_step_count: int                 # >= 1
    repair_step_count: int                 # >= 0 (success path: 1; limits path: 0)
    failed_verify_count: int                # >= 1 per the spec witness
    terminal_reason: str                   # closed enum; never "still-running"
    joined_workspace_digest: str          # final workspace digest, hex SHA-256
    receipt_sha256: str                    # digest of the canonical form
```

The `joined_workspace_digest` is the final SHA-256 of the canonical-form
JSON encoding of the last accepted workspace snapshot (after the last
propose / repair step that produced progress). The oracle's
`no-progress` verdict short-circuits the digest to the prior value, so
the receipt's `joined_workspace_digest` matches the digest recorded at
the prior gate — that is itself part of the public-safe evidence that
the loop did not advance.

## Witness strategy

`make asterion-prime-p5-run` runs **two** Orb invocations (success-path
and limits-path; both in the same `make` recipe to keep the operator
contract single-mode, mirror of P3's two-target split). Each invocation
runs the operator once against the same `prime.bounded-autonomy` host
service.

**Success-path Orb invocation** (proves the witness's first clause):

1. Preflight: read 5 env vars (`ASTERION_PRIME_OPERATOR_ROOT`,
   `ASTERION_PRIME_P5_PRIVATE_ROOT`, `ASTERION_PRIME_PI_ENTRY`,
   `DEEPSEEK_API_KEY` if real-model, and the wheel URI).
2. Run the operator once with `ASTERION_PRIME_P5_MODE=success`.
   The loop:
   - iter 1: propose (oracle: fail), record `failed_verify_count=1`.
   - iter 2: repair (workspace digest changes), verify (oracle: pass),
     record `terminal_reason = "success"`.
3. The Makefile `jq -e` asserts:
   - `status == "completed"`, `terminal_reason == "success"`,
     `propose_step_count == 1`, `verify_step_count == 2`,
     `repair_step_count == 1`, `failed_verify_count == 1`,
     `joined_workspace_digest` non-null and differs from the iter-1
     digest, `receipt_sha256` non-null.

**Limits-path Orb invocation** (proves the witness's "bounded stop"
clause and the closed enum of stopping conditions):

1. Re-invoke operator with `ASTERION_PRIME_P5_MODE=limits`.
2. The operator runs three refusal scenarios (one Orb invocation,
   three records emitted via `jq -s slurp + .[N]` index — mirror of
   P4's `9d1a2bb7` fix and Phase 7's `-limits` target):
   - scenario A (`iteration-cap`): three failed verifies →
     `terminal_reason = "iteration-cap-exceeded"`,
     `verify_step_count = 3`, `repair_step_count = 0`,
     `failed_verify_count = 3`.
   - scenario B (`duration-cap`): one slow propose step →
     `terminal_reason = "duration-cap-exceeded"`,
     `verify_step_count = 0`, `last_step_timed_out = true`.
   - scenario C (`no-progress`): propose with unchanged digest →
     `terminal_reason = "no-progress"`, `verify_step_count = 0`,
     `joined_workspace_digest` equals the iter-1 digest.
3. The Makefile `jq -e` asserts each scenario by index in the slurped
   array, not by line count.

`make asterion-prime-p5-run-verbose` is the diagnostic sibling that
emits the per-step oracle verdict stream (no assertions).

## Determinism and the fake-worker contract

The witness uses a deterministic fake-worker (mirror of P3's / P4's
contract):

- The fake-worker receives `(mode, iteration, scenario, run_id)` and
  emits a payload whose SHA differs across tuples — so the
  `failed_verify_count`, `joined_workspace_digest`, and
  `receipt_sha256` checks are meaningful.
- The fake-worker `repair_step` payload MUST produce a workspace
  digest that differs from the prior step's digest, **except** in
  scenario C (`no-progress`), where the repair is a no-op and the
  digest is forced to equal the iter-1 digest.
- Real-model invocation is out of scope; the witness proves bounded
  autonomy semantics, not model capability.

## Failure behavior (spec L283–L292)

- Oracle fail → record `failed_verify_count += 1`, schedule a repair
  step on the next iteration; do not interrupt the loop until either
  the iteration cap, the duration cap, or the oracle's "pass" verdict
  fires.
- Iteration cap reached → terminate with `iteration-cap-exceeded`,
  no model spawn, no implicit retry.
- Duration cap reached → terminate with `duration-cap-exceeded`,
  record `last_step_timed_out = true`.
- No-progress digest → terminate with `no-progress`, do not run the
  next verify step (the verify step is refused by the loop's
  dedup-adapter, not by the oracle).
- Cancellation → bounded cleanup of in-flight propose / repair /
  verify; one terminal result with `terminal_reason = "cancelled"`.
- Oracle failure → application failure, not framework success.

## Public redaction (spec L293–L295)

`P5PublicResult` MUST NOT include: prompts, model prose, generated
code, worker output, credentials, provider bodies, private paths,
source locations, raw external logs, or the per-step oracle verdict
stream. Only the fields named in `P5NativeReceipt` plus `status` and
`private_root_redacted=True` are public. The verbose-mode stdout is
operator-only and never enters the witness record.

## What Phase 8 must NOT do

- Touch the source-detachment gate.
- Drive a real Pi subprocess in the witness.
- Write the P6 plan (Phase 9).
- Use a subprocess supervisor as the default loop path (the
  in-process `asyncio` loop is the default per the architectural
  principle above; a future cross-process isolation requirement
  would be a separate phase).
- Introduce `prime.proposer` / `prime.verifier` / `prime.repairer` as
  separate host services (the single `prime.bounded-autonomy`
  controller is the only new host service in Phase 8).
- Inherit an SDK agent loop (spec L257 hard constraint).
- Reuse P4's `prime.continuity-store` or P3's `prime.child-runner` —
  P5 has neither continuity nor child composition.

## Migration order confirmation

Phase 8 is step **8** of the 9-phase program (rebuild P5); P3 is step
7 (closed at `fec56274`); P6 is step 9 (next after this). The program
order is fixed by the detachment spec L267–L277.
