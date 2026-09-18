# Phase 9 — Asterion Prime P6 (continual-improvement) Native Rebuild

## Context

**Why now.** The 9-phase native detachment program is at Phase 9. Phases
1–8 are closed. P7, P1, P2, P3, P4, and P5 are native, witnessed, and
republished in the public selector. P6 remains unbuilt. Phase 8 closed at
commit `0a74bc1a` (Task 16 mirror commit for P5). The spec
(`docs/superpowers/specs/2026-09-19-asterion-prime-p6-native-design.md`)
defines P6 as one application-level demonstration of Asterion Prime's
**continual-improvement** capability. This is the spec's P6 witness
(L16–L19) verbatim:

> a candidate is evaluated against a fixed baseline, a non-improving
> candidate is rejected without promotion, and an improving candidate
> requires an explicit admitted promotion action before becoming
> current.

**What Phase 9 must produce.** A native `prime.continual-improvement`
application that demonstrates the admit → holdout → preserve-or-rollback
lifecycle with the closed 2-element public `terminal_outcome` enum
(`preserved` | `rolled-back`), the closed 3-element oracle verdict enum
(`preserved` | `rolled-back` | `global-rejected`), and explicit global-scope
authorization gating — all by composing the framework-owned
`HarnessCoordinator` (`src/asterion/control/harness.py`) under bounded
controls. **No new framework-level type is introduced**: P6 layers an
application-level wrapper on top of the existing
`HarnessCoordinator` / `HarnessScope` / `MemoryHarnessPrivateRevisionStore`.

**What Phase 9 must NOT do.** Touch the source-detachment gate, drive a
real Pi subprocess in the witness, write the P7 plan, introduce
`prime.continual-improvement-loop` (or any second host service) as a
separate surface — the **single `prime.candidate-store`** host service
is the only new host service in Phase 9 — reuse `prime.bounded-autonomy`
(P5 owns bounded-loop semantics), `prime.continuity-store` (P4 owns
checkpoint / recovery), or `prime.child-runner` (P3 owns recursive
composition), reimplement `HarnessCoordinator` / `HarnessScope` /
`MemoryHarnessPrivateRevisionStore`, inherit an SDK agent loop, or clean
the stale `src/asterion/applications/prime_agent/__pycache__/continual_improvement_*.pyc`
files (vestigial, harmless; spec L452+ explicitly out of scope).

**Witness strategy** (confirmed): deterministic fake-worker keyed on
`(mode, candidate_kind, run_id)`. Two Orb invocations:

- `make asterion-prime-p6-run` with `ASTERION_PRIME_P6_MODE=preserved`
  — the success path. One Orb invocation, one Orb record.
- `make asterion-prime-p6-run-limits` with
  `ASTERION_PRIME_P6_MODE=limits` — emits **two** records in a single
  `jq -s slurp + .[N]` array: `.[0]` = `rolled-back` (holdout
  regressed → exact inverse revision, `rollback_invocation_count=1`);
  `.[1]` = `global-rejected` (scope=global without
  `global_activation_approved=True` → pre-orchestration rejection →
  public receipt's `terminal_outcome="rolled-back"` +
  `global_activation_approved=False`).

Note the structural difference from P5: P5's `-limits` target emits
**three** refusal scenarios (`iteration-cap` / `duration-cap` /
`no-progress`). P6's `-limits` target emits **two** records
(`rolled-back` / `global-rejected`), because P6 has exactly two
non-success termination surfaces. Mirror of P4's single-`make` /
P3's split-shape; closer to P3 in record count, closer to P5 in
witness shape.

**Provider gate** (confirmed): P6 stays unpublished in
`create_provider()` until `make asterion-prime-p6-run` AND
`make asterion-prime-p6-run-limits` both pass. A separate Task-16
commit then flips the witness-passed flag and bumps the P1 regression
guard from 6 → 7 apps, mirroring the P3 / P4 / P5 closure path exactly.

---

## Spec diff table (P6 vs P1 vs P2 vs P3 vs P4 vs P5)

| Row | P1 (closed) | P2 (closed) | P3 (closed) | P4 (closed) | P5 (closed) | P6 (Phase 9) |
|---|---|---|---|---|---|---|
| **Lifecycle** | One process opens a session, runs cells, seals one checkpoint, exits. | One process holds a session across one retrieval batch + one finalization. | One process opens root session, admits one child at depth=2, joins results, exits. | Two processes (A seals, B attaches at generation+1). | One process opens one IPython session, runs bounded propose / verify / repair loop, seals one receipt, exits. | **One process** opens one `HarnessCoordinator`, admits one candidate, evaluates one holdout, preserves-or-rolls-back, seals one receipt, exits. |
| **Store / continuity** | `FilePrimeSessionStore` opens fresh; refuses to rebind. | Inherits P1. | Inherits P1 — no new store classmethods. | Adds `open_continued(prior_root, next_identity)` for cross-process continuation. | Inherits P1 — no new store classmethods. | **Inherits P1** — no new store classmethods. P6 has no recovery semantics, no continuity, no checkpoint. |
| **Identity** | `generation = 1` on first open. | Inherits P1. | Root `generation = 1`; child `generation = root.generation + 1`. | `generation` monotonic across process boundaries; `open_continued` is the only widening path. | `generation = 1` on first open. | **`generation = 1` on first open.** P6 has no generation monotonicity across admits (every admit is its own candidate within one run). |
| **Host services** | `prime.ipython`, `prime.p1-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend` | Adds `prime.p2-oracle`; reuses P1 substrate. | Adds `prime.child-runner`; adds `prime.p3-oracle`; reuses P1 substrate minus `prime.ipython`. | Adds `prime.continuity-store`; adds `prime.p4-oracle`. | Adds `prime.bounded-autonomy` (NEW host service, single loop controller); adds `prime.p5-oracle`. | **Adds `prime.candidate-store`** (NEW host service, **wraps** framework-owned `HarnessCoordinator` — composition, not duplication); adds `prime.p6-oracle`; reuses `prime.pi-extension`, `prime.private-trace`, `prime.session-backend`. |
| **Oracle** | Asserts checkpoint sealing + cleanup ordering. | Asserts retrieval bounded within context+cost caps. | Asserts child admitted + child joined + limits reject. | Asserts generation monotonic + no committed effect replay. | Asserts propose admitted + verify failed-then-repaired + bounded stop. | Asserts candidate admitted + holdout evaluated + explicit promotion OR exact rollback (closed **3-element** verdict enum: `preserved` / `rolled-back` / `global-rejected`). |
| **Sealed receipt** | `PrimeCheckpointDigest` | Adds retrieval digest. | `P3NativeReceipt` with `root_run_id`, `child_run_id`, `joined_result_sha256`, `depth_reached`, `refusal_reason`. | `P4NativeReceipt` with `prior_checkpoint_sha256`, `new_generation`. | `P5NativeReceipt` with `propose_step_count`, `verify_step_count`, `repair_step_count`, `failed_verify_count`, `terminal_reason` (closed 5-element), `joined_workspace_digest`. | **`P6NativeReceipt`** with `root_run_id`, `baseline_snapshot_digest`, `candidate_revision_digest`, `task_a_evidence_digest`, `task_b_result_digest`, `terminal_outcome` (closed **2-element**: `preserved` \| `rolled-back`), `global_activation_approved`, `rollback_invocation_count`, `receipt_sha256`. |
| **Cross-process boundary** | None. | None. | None (in-process child factory). | Load-bearing (process A → process B). | None. Single-process `asyncio` loop. | None. Single-process `HarnessCoordinator` wrapper (in-process default). |
| **Limits enforced** | Budget via session backend. | Same. | depth / concurrency / budget / cancellation. | Same. | iteration / repair-step duration / loop duration / workspace-digest dedup. | **One candidate revision / one holdout evaluation / one rollback maximum / finite action + usage + deadline + cost ceilings** — carried from `PrimeSessionBackend`'s budget gate. Defaults: `MAX_ACTIONS=1`, `MAX_USAGE_PROVIDER_OPS=4`, `MAX_DEADLINE_MS=60_000`, `MAX_COST_USD=0.05`. |
| **Stopping conditions (terminal_outcome)** | `recovery-required` on cancel mid-run; otherwise single terminal. | Same. | `recovery-required` on cancel-mid-child. | Same. | **Closed 5-element enum** (`success` / `iteration-cap-exceeded` / `duration-cap-exceeded` / `no-progress` / `cancelled`). | **Closed 2-element enum** (`preserved` \| `rolled-back`). The oracle's 3-element verdict enum (`preserved` / `rolled-back` / `global-rejected`) is **internal-only**; the public receipt's `terminal_outcome` stays at 2. Cancellation, candidate-admission errors, holdout-evaluation errors, and promotion-action errors **all fold to `rolled-back`** with diagnostic digests in the receipt. |

> **Load-bearing note.** P6's public `terminal_outcome` enum is
> **smaller** than P5's `terminal_reason` (2 vs 5 elements). The
> oracle's 3-element verdict enum is internal-only; the public
> receipt stays at 2. `global-rejected` folds to
> `terminal_outcome="rolled-back"` +
> `global_activation_approved=False`. The 4 error paths
> (cancellation, candidate admission, holdout evaluation,
> promotion action) all seal `rolled-back` with a 64-hex
> diagnostic digest in the receipt (spec L283–L292).

---

## Components (block order)

### Task 1 — Capability package JSON contracts

- **Files**:
  - `src/asterion/capabilities/prime_continual_improvement_native/payload/capability-package.json`
  - `src/asterion/capabilities/prime_continual_improvement_native/payload/capabilities/prime-continual-improvement.json`
- **Convention**: `capability_id` in the capability JSON equals the
  application ID (`prime.continual-improvement`); `package_id` in the
  package JSON equals `prime-continual-improvement-native`.
- **Closed key sets**: validated by `validate_assembly_manifest`,
  `CapabilityPackageManifest`, `validate_capability_manifest`. All
  `EDGE_FIELDS` arrays sorted unique.
- **Canonical-form detail (load-bearing, learned from Phase 7 Task 11):
  the JSON files MUST end with a trailing newline**
  (`\n`); `open_portable_payload` rejects non-canonical bytes.
- **Tests**: `tests/test_asterion_prime_p6_capability_package.py`
  - `test_package_loads_and_lists_required_services` — set equality on
    `{prime.candidate-store, prime.p6-oracle, prime.pi-extension,
    prime.private-trace, prime.session-backend, prime.ipython}`.
  - `test_capability_id_matches_application_id`.
  - `test_package_files_end_with_trailing_newline`.

### Task 2 — Application assembly JSON

- **File**:
  `src/asterion/applications/prime/assemblies/prime-continual-improvement.json`
- Mirrors P1/P2/P3/P4/P5 assembly shape exactly. `host_policies`,
  `host_events`, `host_artifacts` are `[]` (validator uses set equality,
  not `>=`).
- **Tests**: `tests/test_asterion_prime_p6_assembly.py`
  - `test_assembly_references_capability_package_and_services`.
  - `test_assembly_runtime_id_is_asterion_prime`.

### Task 3 — Host service `prime.candidate-store`

- **File**: `src/asterion/applications/prime/services.py` (extend).
- **Pattern**: copy `_open_local_corpus_service` from
  `src/asterion/capabilities/dci/implementation/services.py:285` for the
  factory; copy the `ChildRunnerHostService` / `BoundedAutonomyLoop`
  shape for the `public_identity` / async-context-manager contract.
- **Composition over duplication (load-bearing)**: `prime.candidate-store`
  **wraps** the framework-owned `HarnessCoordinator`
  (`src/asterion/control/harness.py:543`). It does **NOT** reimplement
  the append-only revision authority, the scope mapping, the
  inverse-rollback logic, or the snapshot projection. P6's wrapper
  owns the application-level lifecycle (admit → holdout → preserve /
  rollback) and the single-candidate / single-holdout / single-rollback
  limits; the coordinator remains framework-owned and domain-neutral.
- **Public symbols**:
  - `CandidateStoreLoop` — async context manager exposing
    `public_identity`, `admit_candidate(*, root_run_id, proposal,
    signal) -> CandidateAdmission | CandidateAdmissionRefused`,
    `evaluate_holdout(*, root_run_id, candidate, baseline, signal) ->
    HoldoutResult | HoldoutRefused`, `promote_or_rollback(*,
    root_run_id, candidate, holdout, signal) -> P6NativeReceipt`
    (single terminal result, one of the closed 2-element enum values),
    `last_evaluation_digest`, `rollback_invocation_count`.
  - `create_candidate_store_host_service(context:
    HostServiceFactoryContext) -> CandidateStoreLoop`.
- **Limits** (configurable per-context, defaults from spec):
  - `MAX_ACTIONS = 1` (admit),
    `MAX_USAGE_PROVIDER_OPS = 4` (one each: admit + evaluate +
    optional promote / rollback + one overhead),
    `MAX_DEADLINE_MS = 60_000`,
    `MAX_COST_USD = Decimal("0.05")`,
    `MAX_CANDIDATE_REVISIONS_PER_RUN = 1`,
    `MAX_HOLDOUT_EVALUATIONS_PER_RUN = 1`,
    `MAX_ROLLBACK_INVOCATIONS_PER_RUN = 1`.
- **Default scope**: `project` (matches the pre-detachment spec's
  fixed acceptance candidate — a project-scoped memory update).
  Acceptance adapter permitted at scope `session` or `project`; scope
  `global` requires `global_activation_approved=True` (the boundary
  rejection is a separate path that folds into
  `terminal_outcome="rolled-back"` with
  `global_activation_approved=False`).
- **Internal methods** (NOT separate host services):
  `_admit_proposal()` (wraps `HarnessCoordinator.apply(proposal)`),
  `_evaluate_on_holdout()` (composes `prime.p6-oracle` holdout
  verdict), `_apply_promotion()` (wraps
  `HarnessCoordinator.apply(promotion_action)`),
  `_apply_rollback()` (wraps `HarnessCoordinator.rollback(...)` with
  the exact inverse revision).
- **Redaction**: `public_identity` MUST redact `private_root_identity`.
  The public `terminal_outcome` MUST be one of the closed enum:
  `{"preserved", "rolled-back"}`. Internal oracle verdict enum
  (`{"preserved", "rolled-back", "global-rejected"}`) MUST NOT leak
  through `public_identity` — only the public `terminal_outcome` +
  `global_activation_approved` flag do.
- **State.py additions**: NONE expected — `prime.candidate-store`
  does not need new identity / checkpoint / store classmethods. The
  `HarnessCoordinator` carries all revision authority.
  **Confirmed-during-execution**: if Task 8 surfaces a need for a
  new helper on `PrimeBackendIdentity` (e.g., a `holdout_digest()`
  convenience method), add it minimally and report in the task's
  commit message; do not preemptively add anything in this plan.
  (P4 lesson carried forward: `PrimeBackendIdentity.bump_generation`
  stays in `state.py`; do not move it.)
- **Tests**: `tests/test_asterion_prime_p6_candidate_store_service.py`
  (14 tests, mirroring P5's 7 + 7 P6-specific additions):
  - `test_service_exposes_public_identity_without_leaking_private_root`.
  - `test_service_admits_candidate_and_returns_harness_revision`.
  - `test_service_refuses_second_admission_within_same_run`.
  - `test_service_evaluates_holdout_and_returns_non_regressing_result`.
  - `test_service_refuses_second_holdout_evaluation_within_same_run`.
  - `test_service_promotes_admitted_candidate_on_preserved_path`.
  - `test_service_rolls_back_on_rolled_back_path_with_exact_inverse_revision`.
  - `test_service_refuses_second_rollback_within_same_run`.
  - `test_service_emits_single_terminal_receipt_no_still_running_state`.
  - `test_global_rejected_path_short_circuits_pre_orchestration_with_no_revision`.
  - `test_cancellation_folds_to_rolled_back_with_cancellation_digest`.
  - `test_candidate_admission_error_folds_to_rolled_back_with_diagnostic_digest`.
  - `test_holdout_evaluation_error_folds_to_rolled_back_with_diagnostic_digest`.
  - `test_promotion_action_error_folds_to_rolled_back_with_diagnostic_digest`.

### Task 4 — `P6RuntimeHost` Protocol + frozen dataclasses

- **File**: `src/asterion/applications/prime/p6/host.py` (new).
- **Pattern**: copy `P3RuntimeHost` / `P4RuntimeHost` / `P5RuntimeHost`
  Protocol shape (`src/asterion/applications/prime/p3/host.py`,
  `p4/host.py`, `p5/host.py`).
- **Public symbols**:
  - `P6RuntimeHost` (Protocol) with
    `validate_runtime_services(...)`,
    `admit_candidate(*, root_run_id, proposal, signal) -> CandidateAdmission`,
    `evaluate_holdout(*, root_run_id, candidate, baseline, signal) -> HoldoutResult`,
    `promote_or_rollback(*, root_run_id, candidate, holdout, signal) -> P6NativeReceipt`,
    `wait_finalization(...)`.
  - Dataclasses: `P6AdmittedProposal` (frozen; `proposal_id`,
    `proposal_digest`, `revision_id`), `P6BaselineSnapshot` (frozen;
    `snapshot_id`, `entries` tuple), `P6CandidateRevision` (frozen;
    `revision_id`, `revision_digest`), `P6PromotionAction` (frozen;
    `promotion_id`, `promotion_digest`, `target_revision_id`),
    `P6HoldoutResult` (frozen; `task_b_result_sha256`,
    `non_regressing: bool`).
- **Frozen `terminal_outcome` enum**: as a `Literal[...]` type alias so
  the closed 2-element set (`preserved` | `rolled-back`) is enforced at
  the type level. Mirror of P5's `terminal_reason` literal but smaller
  (2 elements vs 5).
- **Frozen oracle verdict enum**: as a separate `Literal[...]` type
  alias for the 3-element verdict enum (`preserved` | `rolled-back` |
  `global-rejected`). The two enums are distinct types — the public
  enum (2-element) is the surface contract; the oracle verdict
  (3-element) is internal-only.
- **Tests**: `tests/test_asterion_prime_p6_host_protocol.py`
  - `test_protocol_shape_matches_p3_p4_p5_runtime_host`.
  - `test_terminal_outcome_is_closed_two_element_enum`.
  - `test_oracle_verdict_is_closed_three_element_enum`.
  - `test_public_enums_do_not_leak_oracle_verdict_set`.

### Task 5 — `prime.p6-oracle` oracle

- **File**: `src/asterion/applications/prime/p6/oracle.py` (new) +
  `tests/test_asterion_prime_p6_oracle.py`.
- **Pattern**: copy `P3Oracle` / `P4Oracle` / `P5Oracle` shape
  (frozen dataclass + `check(...) -> P6OracleReceipt`).
- **Closed 3-string verdict enum**:
  `{"preserved", "rolled-back", "global-rejected"}`.
- **Three invariants from spec L222–L247**:
  1. **candidate admitted**: `HarnessCoordinator.apply(proposal)`
     returned a non-empty `HarnessRevision` with a `revision_id`
     that differs from the baseline snapshot's `revision_id`
     (or equals `None` on iteration 1, when `sequence == 1`).
  2. **holdout evaluated**: `evaluate_holdout(candidate, baseline)`
     returned a `HoldoutResult` whose `task_b_result_sha256` and
     `non_regressing: bool` are both set; `task_b_result_sha256`
     is a 64-hex SHA-256 that differs from the baseline snapshot
     digest on the `preserved` path.
  3. **explicit promotion / exact rollback**:
     - `preserved` outcomes require an `apply(promotion_action)`
       call. Without it, oracle refuses reason
       `invariant-violation::missing-promotion-action`.
     - `rolled-back` outcomes require `rollback(...)` with the
       exact inverse revision produced in step 1. Without it,
       oracle refuses reason
       `invariant-violation::missing-rollback-call`.
     - `global-rejected` verdicts short-circuit
       pre-orchestration: no `HarnessRevision` is created, the
       baseline snapshot is unchanged, and the oracle returns
       reason `boundary-rejection::global-scope-not-authorized`.
- **Mid-task correction note** (mirroring P5 Task 5's empty-string
  lesson): `_validate_str` should be **type-only** so empty
  candidate revision digests reach the invariant verdict rather
  than being silently rejected (mirror P3's `Optional[str]`
  handling).
- **Public symbols**: `P6Oracle.check(admitted_proposal,
  baseline_snapshot, holdout_result, promotion_action, verdict) ->
  P6OracleReceipt`. Oracle verdict enum (closed 3 strings):
  `{"preserved", "rolled-back", "global-rejected"}`.
- **Tests**: `tests/test_asterion_prime_p6_oracle.py` (11 tests)
  - `test_oracle_passes_on_preserved_path_with_explicit_promotion_action`.
  - `test_oracle_rejects_preserved_without_promotion_action` → reason
    `invariant-violation::missing-promotion-action`.
  - `test_oracle_passes_on_rolled_back_path_with_exact_inverse_revision`.
  - `test_oracle_rejects_rolled_back_without_rollback_call` → reason
    `invariant-violation::missing-rollback-call`.
  - `test_oracle_passes_on_global_rejected_with_unauthorized_global_scope`
    → reason `boundary-rejection::global-scope-not-authorized`.
  - `test_oracle_rejects_when_candidate_admission_missing`.
  - `test_oracle_rejects_when_holdout_evaluation_missing`.
  - `test_oracle_rejects_when_task_b_result_digest_equals_baseline_digest`
    (proves the candidate produced different task B output, not a
    replay).
  - `test_oracle_rejects_when_revision_id_equals_baseline_revision_id_and_sequence_is_one`
    (proves the candidate differs from the empty baseline).
  - `test_oracle_verdict_is_closed_three_element_enum`.
  - `test_empty_candidate_revision_digest_reaches_invariant_verdict`.

### Task 6 — `P6NativeReceipt` + `seal()`

- **File**: `src/asterion/applications/prime/p6/receipt.py` (new) +
  `tests/test_asterion_prime_p6_receipt.py`.
- **Public symbols**: `P6NativeReceipt` (frozen dataclass; spec field
  set), `seal(root_run_id, baseline_snapshot_digest,
  candidate_revision_digest, task_a_evidence_digest,
  task_b_result_digest, terminal_outcome, global_activation_approved,
  rollback_invocation_count) -> P6NativeReceipt`,
  `build(...)` for tests.
- **Field set (9 fields, spec L257–L269)**:
  `root_run_id`, `baseline_snapshot_digest`,
  `candidate_revision_digest`, `task_a_evidence_digest`,
  `task_b_result_digest`, `terminal_outcome` (closed 2-element
  literal), `global_activation_approved`, `rollback_invocation_count`,
  `receipt_sha256`.
- **Canonical-form detail (load-bearing)**: the receipt SHA is
  computed over canonical JSON bytes (sorted keys, no whitespace,
  trailing newline) of the 8 non-self fields. Mirror P3 / P4 / P5's
  `seal` shape exactly.
- **Module move note** (mirror P5 Task 6 lesson): if Task 3 put the
  receipt in `services.py`, move it to `p6/receipt.py`; keep a
  wrapper shim that re-raises the receipt error as the host service
  error to preserve Task 3 tests' exception contract.
- **Diagnostic digests**: 4 optional 64-hex SHA-256 fields
  (`candidate_admission_error_digest` /
  `holdout_evaluation_error_digest` /
  `promotion_action_error_digest` / `cancellation_digest`), each
  present only when the corresponding path actually fired. The
  digest payload is the canonical-form of `{kind: str, message: str,
  frame_fingerprints: list[str]}` — no prompt bodies, no model prose,
  no source locations (spec L437–L438).
- **Tests**: `tests/test_asterion_prime_p6_receipt.py` (7 tests)
  - `test_seal_receipt_is_digest_stable` — same inputs → same SHA;
    any field change → different SHA.
  - `test_seal_receipt_with_zero_rollback_invocation_round_trips`.
  - `test_seal_receipt_with_one_rollback_invocation_round_trips`.
  - `test_terminal_outcome_is_closed_two_element_enum_in_receipt`.
  - `test_global_activation_approved_default_is_false_for_project_scope`.
  - `test_diagnostic_digest_field_is_absent_when_corresponding_path_did_not_fire`.
  - `test_diagnostic_digest_field_is_64_hex_sha256_when_present`.

### Task 7 — P6 runtime binding

- **File**: `src/asterion/applications/prime/p6/runtime_binding.py`
  (new) + `tests/test_asterion_prime_p6_runtime_binding.py`.
- **Pattern**: copy `build_p4_runtime` / `build_p5_runtime`.
- **Public symbols**: `P6_HOST_CAPABILITIES` (5-tuple, **set-equality
  fail-closed** per Phase 8 Task 7 lesson):
  `("prime.candidate-store", "prime.p6-oracle",
  "prime.pi-extension", "prime.private-trace",
  "prime.session-backend")` — must match the assembly's
  `required_services` set exactly. Mirror of P5's
  `P5_HOST_CAPABILITIES` 6-tuple but with `prime.candidate-store`
  instead of `prime.bounded-autonomy` and minus `prime.ipython` is
  permitted if P6 is not ipython-driven; the default is to keep
  `prime.ipython` since the candidate revision is admitted via
  IPython session. Final determination in Task 8.
- `build_p6_runtime(context: AsterionPrimeRuntimeContext) ->
  AsterionPrimeRuntimeClient`, internal `_P6RuntimeSession`.
- **Pyright latent-issues note** (mirror P5 Task 7 deferral): the
  `runtime_binding.py:294` `__init__` overload mismatch is a
  pre-existing project-level type issue; P6 will surface it again
  — record, don't fix in Task 7.
- **Tests**: `tests/test_asterion_prime_p6_runtime_binding.py` (10
  tests)
  - `test_p6_host_capabilities_is_closed_five_tuple_set`.
  - `test_build_p6_runtime_returns_client_with_p6_methods`.
  - `test_build_p6_runtime_does_not_register_child_runner_or_continuity_store_or_bounded_autonomy`.
  - `test_build_p6_runtime_composes_harness_coordinator`.
  - `test_build_p6_runtime_does_not_reimplement_harness_coordinator`.
  - `test_p6_runtime_session_default_scope_is_project`.
  - `test_p6_runtime_session_requires_global_activation_for_global_scope`.
  - `test_p6_runtime_session_emits_single_terminal_no_still_running`.
  - `test_dispatcher_routes_p6_application_id_to_build_p6_runtime`.
  - `test_dispatcher_does_not_route_p6_to_child_runner_or_continuity_or_bounded_autonomy`.

### Task 8 — P6 operator

- **File**: `src/asterion/applications/prime/p6/operator.py` (new) +
  `tests/test_asterion_prime_p6_operator.py`.
- **Pattern**: copy `src/asterion/applications/prime/p3/operator.py`
  and `p5/operator.py` structure (single `main()`, `_preflight(env)`,
  `_build_resources(env)`, `_invoke_loop(resources)`; **plus** a
  `_run_mode_preserved(resources)` vs `_run_mode_limits(resources)`
  split that dispatches on `ASTERION_PRIME_P6_MODE`).
- **Public symbols**: `main()`, `run_preserved_path(env)`,
  `run_limits_path(env)`, `_preflight(env)`,
  `_build_resources(env)`, `_invoke_loop(resources)`,
  `_run_scenario_rolled_back(resources)`,
  `_run_scenario_global_rejected(resources)`.
- **Mode dispatch**:
  - `ASTERION_PRIME_P6_MODE = "preserved"` → one operator run, one
    `P6NativeReceipt` to stdout (terminal_outcome = preserved,
    rollback_invocation_count = 0,
    global_activation_approved = false).
  - `ASTERION_PRIME_P6_MODE = "limits"` → **two** scenario runs,
    one `P6NativeReceipt` per scenario to stdout (one JSON object
    per line; the Makefile slurps with `jq -s`):
    - Scenario A (`rolled-back`): holdout regressed →
      exact inverse revision → terminal_outcome=`rolled-back`,
      rollback_invocation_count=1,
      global_activation_approved=false.
    - Scenario B (`global-rejected`): scope=global without
      `global_activation_approved=True` → pre-orchestration
      boundary rejection → terminal_outcome=`rolled-back`,
      global_activation_approved=false,
      candidate_revision_digest equals baseline_snapshot_digest.
- **Env**:
  - `ASTERION_PRIME_OPERATOR_ROOT` (required)
  - `ASTERION_PRIME_P6_PRIVATE_ROOT` (required)
  - `ASTERION_PRIME_P6_MODE` ∈ `{preserved, limits}` (required)
  - `ASTERION_PRIME_PI_ENTRY` (operator preflight only)
- **Order inside `_build_resources`**:
  1. `session_backend.attach(root_identity)` — root generation=1.
  2. `loop = candidate_store_host_service` — exposes the
     application-level admit → holdout → preserve-or-rollback
     lifecycle (composes `HarnessCoordinator` over
     `MemoryHarnessPrivateRevisionStore`, `prime.pi-extension`,
     `prime.p6-oracle`, and `prime.session-backend` for budget).
  3. Build `p6_oracle`, `pi_extension` (fake), `private_trace`
     (fake).
- **Stdout shape**: one JSON line per run. Preserved-path fields
  include `terminal_outcome="preserved"`,
  `global_activation_approved=false`,
  `rollback_invocation_count=0`, `task_b_result_digest` differing
  from `baseline_snapshot_digest`, and
  `candidate_revision_digest` differing from
  `baseline_snapshot_digest`. Limits-path emits **two records**
  (`rolled-back` then `global-rejected`), each as one JSON line:
  - `rolled-back`: `terminal_outcome="rolled-back"`,
    `rollback_invocation_count=1`, `candidate_revision_digest`
    non-null (admitted revision existed before rollback).
  - `global-rejected`: `terminal_outcome="rolled-back"`,
    `rollback_invocation_count=0` (pre-orchestration boundary
    rejection), `global_activation_approved=false`,
    `candidate_revision_digest == baseline_snapshot_digest`
    (no candidate was admitted).
  Note that scenario B's `terminal_outcome` is `rolled-back`
  (the public 2-element enum's only non-`preserved` value); the
  oracle's private `global-rejected` verdict does NOT appear in
  the public stdout — `global_activation_approved=false` plus
  the `candidate_revision_digest == baseline_snapshot_digest`
  equality are the public witnesses of the boundary rejection.
- **Deterministic fake-worker contract**: receives
  `(mode, candidate_kind, run_id)` and emits a payload whose
  SHA differs across tuples. The fake-worker payload for the
  `preserved` path MUST produce a `task_b_result_sha256` that
  differs from the `baseline_snapshot_digest` AND
  `non_regressing=True`. The fake-worker for the `rolled-back`
  scenario MUST produce `non_regressing=False`. The fake-worker
  for the `global-rejected` scenario is a no-op (scope=`global`
  triggers pre-orchestration rejection; no task B evaluation
  runs). Mirror of P3 / P4 / P5's deterministic contract.
- **State.py additions**: NONE expected — `prime.candidate-store`
  does not need new identity / checkpoint / store classmethods.
  **Confirmed-during-execution**: if Task 3 or Task 8 surfaces a
  need for a new helper on `PrimeBackendIdentity` (e.g., a
  `holdout_digest()` convenience method), add it minimally and
  report in the task's commit message; do not preemptively add
  anything in this plan.
- **Tests**: `tests/test_asterion_prime_p6_operator.py` (9 tests)
  - `test_preserved_path_emits_completed_json_with_terminal_outcome_preserved`.
  - `test_limits_path_emits_two_records_in_order_rolled_back_then_global_rejected`.
  - `test_rolled_back_scenario_emits_exactly_one_rollback_invocation`.
  - `test_global_rejected_scenario_emits_candidate_digest_equal_to_baseline`.
  - `test_operator_exits_nonzero_on_unknown_mode`.
  - `test_preserved_path_emits_rollback_invocation_count_zero`.
  - `test_preserved_path_emits_global_activation_approved_false`.
  - `test_preserved_path_emits_task_b_result_digest_differing_from_baseline`.
  - `test_limits_path_does_not_leak_oracle_verdict_in_public_stdout`.

### Task 9 — Dispatcher branch

- **File**: `src/asterion/applications/prime/runtime_binding.py`
  (existing). Around the `build_asterion_prime_runtime(context)`
  switch (around line 320, where P5's branch lives), add a branch:
  - `("prime.continual-improvement", "1.0.0") -> build_p6_runtime`.
- **Pyright latent-issues note**: this will surface the
  `runtime_binding.py:294` `__init__` overload mismatch again
  (pre-existing project-level type issue) — record, don't fix in
  Task 9. (Mirror of P5 Task 9.)
- **Tests**: extend `tests/test_asterion_prime_p6_runtime_binding.py`
  - `test_dispatcher_routes_p6_application_id_to_build_p6_runtime`.
  - `test_dispatcher_does_not_route_p6_to_child_runner_or_continuity_or_bounded_autonomy`.

### Task 10 — Provider factory entry (P6 stays unpublished)

- **File**: `src/asterion/applications/prime/provider.py` (existing).
- **Edit**: add `prime_continual_improvement_application()` and
  `create_prime_continual_improvement_provider()` factories.
  **`create_provider()` does NOT include P6 yet** — the witness must
  pass first (Task 16). P6 stays unpublished until
  `make asterion-prime-p6-run` AND `make asterion-prime-p6-run-limits`
  both pass. Mirror of P5's gated-publish pattern.
- **Task 10 subagent note**: it may need to import
  `asterion.capabilities.prime_continual_improvement_native`, which
  requires the capability-package Python module — same P5 lesson
  pattern; if Task 11 hasn't shipped the module yet, Task 10 should
  ship it (mirror Phase 7's Task 10 over-scope note).
- **Tests**: `tests/test_asterion_prime_p6_provider.py` (2 tests)
  - `test_provider_factory_exists_and_returns_p6_application`.
  - `test_create_provider_does_not_include_p6_until_witness_passes`.

### Task 11 — First-party package registration

- **File**: `src/asterion/applications/first_party_packages.py`
  (existing). **Phase 7 lesson (load-bearing, learned from the
  Task-11 subagent that discovered it from P4 mirror)**: "register
  in registry dict" is **not sufficient**. Phase 9 explicitly
  requires the three-part requirement:
  1. A capability-package Python module at
     `src/asterion/capabilities/prime_continual_improvement_native/{__init__.py,
     provider.py}` (mirror P3 / P5's
     `src/asterion/capabilities/prime_recursive_workflow_native/`
     and
     `prime_bounded_autonomy_native/`).
  2. The `provider.py` factory function must mirror P5's exact
     shape: `PACKAGE_REF`, `CAPABILITY_REF`, `P6_INPUT_PRESET`,
     `P6_ARTIFACT_ID`, `P6_RECEIPT_MEDIA_TYPE` constants plus a
     `create_provider()` factory.
  3. The capability-package JSON files (Task 1) require
     canonical-form with trailing `\n` for `open_portable_payload`
     (see Task 1).
- **Edit**:
  1. Create
     `src/asterion/capabilities/prime_continual_improvement_native/__init__.py`
     with `PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE` symbol
     re-export.
  2. Create
     `src/asterion/capabilities/prime_continual_improvement_native/provider.py`
     with the factory + closed-enum media type constants.
  3. Register `PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE` in
     `src/asterion/applications/first_party_packages.py` registry
     dict.
- **Tests**: extend
  `tests/test_asterion_first_party_packages.py` to assert presence
  and the exact factory shape (4 new tests at minimum per Phase 7
  lesson).

### Task 12 — `pyproject.toml` entry point

- **File**: `pyproject.toml` (around lines 41–43).
- **Edit**: add one line to
  `[project.entry-points."asterion.host_services"]`:
  ```
  prime.candidate-store = "asterion.applications.prime.services:create_candidate_store_host_service"
  ```
- **Tests**: `tests/test_asterion_prime_p6_entry_point.py`
  - `test_candidate_store_entry_point_is_registered` —
    `importlib.metadata` lookup.
  - `test_candidate_store_entry_point_resolves_to_factory`.

### Task 13 — Root fixture

- **File**: `tests/fixtures/prime_p6/small_root.json`.
- **Content**: pre-baked `PrimeBackendIdentity` (gen=1) for operator
  tests (mirror of `tests/fixtures/prime_p3/small_root.json` and
  `tests/fixtures/prime_p5/small_root.json`).
- **Producer's-construction-site note** (Phase 7 Task 13 lesson):
  use real 64-hex SHA-256 literals matching the P3 / P4 / P5
  fixture shape; do NOT use `"prime.pi-native"` placeholders.
  The 5 runtime-binding SHAs (`pi_command_sha256`,
  `extension_binding_fingerprint`, `ceilings_sha256`, plus the
  `HarnessCoordinator`-related SHAs) MUST match the production
  shape so the `P6_HOST_CAPABILITIES` set-equality check
  (Task 7) passes.
- **Tests**: `tests/test_asterion_prime_p6_root_fixture.py` (2 tests)
  - `test_fixture_loads_and_validates_against_p6_capability_package`.
  - `test_fixture_runtime_binding_shas_match_p6_host_capabilities`.

### Task 14 — Makefile target `asterion-prime-p6-run` + `-limits` + `-verbose`

- **File**: `Makefile`.
- **Default**:
  `ASTERION_PRIME_P6_PRIVATE_ROOT ?= $(CURDIR)/.asterion-private/prime-p6-witness`.
- **Logic**: runs the operator via Orb mirror of P5's pattern
  (`uv run --no-cache --isolated --with <wheel> --with python-dotenv
  python -I -m asterion.applications.prime.p6.operator`). Capture the
  stdout JSON line(s). Assert with `jq -e`:
  1. **Success path** (`-run` with `MODE=preserved`):
     `status == "completed"`,
     `terminal_outcome == "preserved"`,
     `global_activation_approved == false`,
     `rollback_invocation_count == 0`,
     `task_b_result_digest` non-null and differs from the
     `baseline_snapshot_digest`,
     `candidate_revision_digest` non-null and differs from the
     `baseline_snapshot_digest`,
     `receipt_sha256` non-null.
  2. **Limits path** (`-run-limits` with `MODE=limits`):
     re-invokes the operator. Uses `jq -s slurp` to fold the two
     JSON lines into an array. Asserts each refusal record by
     **fixed index** `.[0]`–`.[1]`, not by line count:
     - `.[0].scenario == "rolled-back"` and
       `.[0].terminal_outcome == "rolled-back"` and
       `.[0].rollback_invocation_count == 1` and
       `.[0].global_activation_approved == false` and
       `.[0].candidate_revision_digest` non-null (the admitted
       revision existed before rollback).
     - `.[1].scenario == "global-rejected"` and
       `.[1].terminal_outcome == "rolled-back"` and
       `.[1].rollback_invocation_count == 0` (no rollback was
       issued; the boundary rejection was pre-orchestration) and
       `.[1].global_activation_approved == false` and
       `.[1].candidate_revision_digest` equals
       `.[1].baseline_snapshot_digest` (no candidate was admitted).
  3. `jq -s` + `.[N]` index dodges the make-recipe `\$` quoting trap
     that bit P4 — see `serene-mixing-cat.md` §"Critical files" /
     Phase 6 commit `9d1a2bb7`.
  4. **CRITICAL — Phase 8 Task 14 fix-on-verify lesson**
     (commit `5c07d9ff`): use **single-line jq expressions**, NOT
     multi-line `\` continuation — bash 3.2.57 (macOS default)
     rejects multi-line `\` with `syntax error near unexpected
     token '('`. The `-q` flag MUST be on every `uv run` invocation
     (P4 commit `bb4b804` fix). The `-limits` target emits both
     `rolled-back` and `global-rejected` records via
     `jq -s slurp + .[N]` array indexing — mirror P5's 3-scenario
     limits target structure but with 2 records instead of 3.
- **Add**: `asterion-prime-p6-run-verbose` — diagnostic sibling that
  emits the per-step admission + holdout stream (no assertions, no
  public-safe contract).

### Task 15 — Unit-test suite sweep

- Files listed in each component above. **All targets must pass with
  ruff clean on changed files and the detachment gate still at 0.**
- Targeted regression (no full suite under research intensity):
  - `uv run python -m unittest -v tests.test_asterion_prime_p6_capability_package tests.test_asterion_prime_p6_assembly tests.test_asterion_prime_p6_candidate_store_service tests.test_asterion_prime_p6_host_protocol tests.test_asterion_prime_p6_oracle tests.test_asterion_prime_p6_receipt tests.test_asterion_prime_p6_runtime_binding tests.test_asterion_prime_p6_operator tests.test_asterion_prime_p6_provider tests.test_asterion_prime_p6_entry_point tests.test_asterion_prime_p6_root_fixture`
  - Detachment gate: `uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"` → must print `0`.
  - Ruff on changed files: clean.
  - P1 / P2 / P3 / P4 / P5 regression: each witness still passes
    (`make asterion-prime-p1-run` ... `make asterion-prime-p5-run`).

### Task 16 — Task-4 mirror: publish P6 in the public selector

- **File**: `src/asterion/applications/prime/provider.py`.
- **Edit**: only after `make asterion-prime-p6-run` AND
  `make asterion-prime-p6-run-limits` both pass, add P6 to
  `create_provider()` and to `pyproject.toml`
  `asterion.application_index`. **Revert the P1 regression test**
  (which counts 6 apps after Phase 8's Task 16) to expect 7 apps
  (P7 + P1 + P2 + P3 + P4 + P5 + P6).
- **Tests**:
  - `tests/test_asterion_prime_p1_provider.py` →
    `test_provider_publishes_all_seven_applications` (bumped from
    `...all_six_applications`).
  - `tests/test_asterion_prime_p6_provider.py` flip Task 10 guard
    (`assertNotIn` → `assertIn`).

---

## Critical files to modify

### Existing files (small, surgical edits)

- `src/asterion/applications/prime/runtime_binding.py` — add P6
  dispatcher branch (Task 9).
- `src/asterion/applications/prime/provider.py` — add factories
  (Tasks 10, 16).
- `src/asterion/applications/prime/services.py` — extend with
  `CandidateStoreLoop` and `create_candidate_store_host_service`
  (Task 3).
- `src/asterion/applications/first_party_packages.py` — register
  package (Task 11).
- `pyproject.toml` — add host-service entry point (Task 12),
  application_index row on publish (Task 16).
- `Makefile` — add `asterion-prime-p6-run` + `-limits` + `-verbose`
  targets (Task 14).
- `src/asterion/agents/prime/state.py` — **likely no additions**;
  confirm in Tasks 3 / 8 and report (no preemptive edits).

### New files (large blocks)

- `src/asterion/applications/prime/p6/{__init__.py, host.py,
  oracle.py, receipt.py, runtime_binding.py, operator.py}`
- `src/asterion/capabilities/prime_continual_improvement_native/__init__.py`
- `src/asterion/capabilities/prime_continual_improvement_native/provider.py`
- `src/asterion/capabilities/prime_continual_improvement_native/payload/{capability-package.json,
  capabilities/prime-continual-improvement.json}`
- `src/asterion/applications/prime/assemblies/prime-continual-improvement.json`
- `tests/test_asterion_prime_p6_{capability_package, assembly,
  candidate_store_service, host_protocol, oracle, receipt,
  runtime_binding, operator, provider, entry_point, root_fixture}.py`
- `tests/fixtures/prime_p6/small_root.json`

---

## Phase 7 / Phase 8 lessons captured per task

Captured inline at the relevant task: T1 (trailing `\n`),
T3 / T8 (no preemptive `state.py` additions), T6 (receipt module
move with wrapper shim), T7 (`P6_HOST_CAPABILITIES` set-equality
fail-closed), T11 (capability-package three-part requirement),
T13 (real 64-hex SHAs, not placeholders), T14 (single-line jq,
`-q` on every `uv run`). See each task for detail.

---

## Reuse from existing substrate

### Reused unchanged (cite file paths)

- `asterion.prime` session factory
  (`src/asterion/agents/prime/session.py`) — extended through
  `PrimeSessionBackend.attach(next_identity)` for the wrapper's
  session; no duplicate session engine.
- `PrimeSessionBackend` (`src/asterion/agents/prime/backend.py:244`) —
  the budget / cancellation / duration gate that
  `prime.candidate-store` composes through.
- `PrimeBackendIdentity` / `PrimeCheckpoint`
  (`state.py:73, :160`) — reused unchanged; P6 has no new
  identity / checkpoint / store classmethods.
- `prime.pi-extension`, `prime.private-trace`,
  `prime.session-backend` — reused from P1/P2/P3/P4/P5 unchanged.
- `_open_local_corpus_service` template
  (`capabilities/dci/implementation/services.py:285`) — copy for
  `create_candidate_store_host_service`.
- `P3RuntimeHost` / `P4RuntimeHost` / `P5RuntimeHost` Protocol shape
  (`applications/prime/p3/host.py:111`,
  `applications/prime/p4/host.py`,
  `applications/prime/p5/host.py`) — copy for `P6RuntimeHost`.
- `build_p3_runtime` / `build_p4_runtime` / `build_p5_runtime`
  (`applications/prime/p3/runtime_binding.py`,
  `p4/runtime_binding.py`, `p5/runtime_binding.py`) — copy for
  `build_p6_runtime`.
- P3 / P4 / P5 operator structure (`applications/prime/p3/operator.py`,
  `p4/operator.py`, `p5/operator.py`) — copy for the P6 operator's
  CLI/preflight/resources/invoke pattern (minus the commit/recover
  split, plus the `preserved` / `limits` mode dispatch).
- P1/P2/P3/P4/P5 capability-package + assembly JSON shape — verbatim.
- **Framework-owned `HarnessCoordinator`**
  (`src/asterion/control/harness.py:543`): append-only revision
  authority, scope-boundary record, inverse rollback, recovery,
  snapshot projection. **P6 wraps this engine**; P6 does NOT
  reimplement any of these primitives.
- **Framework-owned `HarnessScope`**
  (`src/asterion/control/harness.py:50`): the closed 3-element enum
  `{"session", "project", "global"}`. P6 uses this scope mapping
  unchanged.
- **Framework-owned `MemoryHarnessPrivateRevisionStore`** (same
  module, `L487`): the in-memory private proposal / snapshot store.
  P6 uses this as the default `private_store` injected into the
  wrapped coordinator.
- **Framework-owned canonical-form helper** `_mapping_digest(...)`
  and the shape of `_snapshot_id(...)` / `_revision_id(...)`:
  reused unchanged for P6's receipt SHA.

### Newly introduced

- `prime.candidate-store` host service — application-level wrapper
  around `HarnessCoordinator` that owns the admitted-candidate
  lifecycle + scope-boundary record + global-approval record. It
  does **not** reimplement the coordinator's append-only revision
  authority, the scope mapping, the inverse-rollback logic, or the
  snapshot projection; it composes them.
- Closed 2-element public `terminal_outcome` enum
  (`Literal["preserved", "rolled-back"]`).
- Closed 3-element internal oracle verdict enum
  (`Literal["preserved", "rolled-back", "global-rejected"]`).
- `P6NativeReceipt` dataclass (frozen, digest-stable, 9 fields per
  spec L257–L269).
- 4 optional diagnostic digest fields
  (`candidate_admission_error_digest` /
  `holdout_evaluation_error_digest` /
  `promotion_action_error_digest` / `cancellation_digest`), each
  64-hex SHA-256 and present only when the corresponding path
  actually fired.
- `P6HOST_CAPABILITIES` 5-tuple set-equality check.

---

## Verification

End-to-end (`make asterion-prime-p6-run` + `make asterion-prime-p6-run-limits`):
assertions listed inline at Task 14. The Makefile's `jq -e` aborts on
any failure.

Targeted regression (no full suite under research intensity):

- `uv run python -m unittest -v tests.test_asterion_prime_p6_capability_package tests.test_asterion_prime_p6_assembly tests.test_asterion_prime_p6_candidate_store_service tests.test_asterion_prime_p6_host_protocol tests.test_asterion_prime_p6_oracle tests.test_asterion_prime_p6_receipt tests.test_asterion_prime_p6_runtime_binding tests.test_asterion_prime_p6_operator tests.test_asterion_prime_p6_provider tests.test_asterion_prime_p6_entry_point tests.test_asterion_prime_p6_root_fixture`
- Detachment gate: `uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"` → must print `0`.
- Ruff on changed files: clean.

Task-4 mirror (after both witness paths pass):

- `make asterion-prime-p{1,2,3,4,5}-run` still pass (no regression).
- `tests/test_asterion_prime_p1_provider.py` updated to expect 7 apps.

---

## Pre-existing red tests carried forward

- `tests.test_pi_session` (1F+6E).
- `tests.test_prime_p7_native_installed`.
- `tests.test_core_only_install.py`.
- `test_builtin_capability_source` conformance-declaration-table
  gap now spans P2/P3/P4/P5/P6 (P6 will add one more entry in the
  same shape) — record for a future conformance-table pass.

---

## Out-of-scope (carried explicitly forward)

1. No real-model invocation in the P6 witness. Real Pi subprocess
   use stays P1/P7 territory.
2. No subprocess supervisor as the default wrapper path (in-process
   `HarnessCoordinator` wrapper is the default per the
   architectural principle above).
3. No source-detachment gate changes.
4. No new host services beyond `prime.candidate-store`.
   `prime.pi-extension`, `prime.private-trace`,
   `prime.session-backend` are reused from P1/P2/P3/P4/P5 without
   modification. `prime.ipython` MAY be reused from P1/P5 if the
   P6 operator needs IPython for candidate revision admission —
   Task 8 determines this.
5. No `prime.proposer` / `prime.verifier` / `prime.repairer`
   decomposition (P5's pattern). The single
   `prime.candidate-store` controller is the only new host service
   in Phase 9.
6. **No new framework-level harness types.** The boundary of
   `src/asterion/control/harness.py` stays framework-owned and
   domain-neutral. P6 wraps `HarnessCoordinator`; P6 does not
   duplicate it.
7. **No reuse of P5's `prime.bounded-autonomy`** (P5 owns
   bounded-loop semantics), **P4's `prime.continuity-store`** (P4
   owns checkpoint / recovery), or **P3's `prime.child-runner`**
   (P3 owns recursive composition). P6 has none of those surfaces.
8. **No inheritance of an SDK agent loop** (spec L257 hard
   constraint — the detached P1–P7 family does not inherit any
   SDK agent loop; P6 layers on the framework-owned
   `HarnessCoordinator` only).
9. **No cleanup of the stale
   `src/asterion/applications/prime_agent/__pycache__/continual_improvement_*.pyc`
   files.** They are vestigial, harmless, and the `.py` source has
   already been detached in Phase 1. A future hygiene pass owns
   this; Phase 9 leaves it alone to keep the diff focused on the
   P6 rebuild (spec L477–L482).
10. **No P7 plan in this document.** Phase 9 is the program
    closer; P7's plan was Phase 3.
11. **No promotion of any implemented-but-not-yet-witnessed P6
    component to PASS** in status documents. Promotion happens
    only after `make asterion-prime-p6-run` AND
    `make asterion-prime-p6-run-limits` both return exit 0.

---

## Open risks (recorded, not blocking)

1. **`HarnessCoordinator` shape drift.** Assumes the API at
   `src/asterion/control/harness.py:543` (`apply`, `rollback`,
   `snapshot`, `recover`) and the `HarnessScope` enum are
   stable. Task 3 must adapt the wrapper if shifted — but
   composition over duplication.
2. **State.py helper may surface during T3 / T8.** No addition
   expected (P6 has no monotonicity / recovery / continuity).
   Add minimally if discovered; report in commit message.
3. **The 2-element `terminal_outcome` enum is the public
   contract.** Any addition or rename is a breaking change.
   Closed enum is load-bearing — keeps public surface smaller
   than P5's 5-element `terminal_reason`.
4. **Deterministic fake-worker.** Payload MUST include
   `(mode, candidate_kind, run_id)` so digest checks are
   meaningful. `global-rejected` MUST emit
   `candidate_revision_digest == baseline_snapshot_digest`.
5. **Receipt module move risk.** If T3 puts the receipt in
   `services.py` and T6 moves it to `p6/receipt.py`, the
   wrapper shim must preserve T3 tests' exception contract.

---

## Migration order confirmation

Phase 9 is step **9** of the 9-phase program (rebuild P6 — the final
package). Phase 8 (P5) closed at `0a74bc1a`. P6 is the program
closer. The program order is fixed by the detachment spec
L267–L277 (removal → source-detachment gate → P7 anchor → P1 → P2
→ P4 → P3 → P5 → P6).
