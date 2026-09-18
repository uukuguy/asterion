# Phase 8 — Asterion Prime P5 (bounded-autonomy) Native Rebuild

## Context

**Why now.** The 9-phase native detachment program is at Phase 8. Phases
1–7 are closed. P7, P1, P2, P3, and P4 are native, witnessed, and
republished in the public selector. P5 and P6 remain unbuilt. The spec
(`docs/superpowers/specs/2026-09-19-asterion-prime-p5-native-design.md`)
defines P5 as one application-level demonstration of Asterion Prime's
bounded-autonomy capability.

**What Phase 8 must produce.** A native `prime.bounded-autonomy`
application that demonstrates a finite propose / verify / repair loop
with exact stopping conditions, a closed 4-element stopping-condition
enum, workspace-digest deduplication, and `MAX_ITERATIONS = 3`, all
without inheriting an SDK agent loop. This is the spec's P5 witness
(L348–L350) verbatim:

> a finite propose/verify/repair run performs at least one failed
> verification and one bounded repair, then stops on success or the
> exact iteration cap with no autonomous continuation afterward.

**What Phase 8 must NOT do.** Touch the source-detachment gate, drive
a real Pi subprocess in the witness, write the P6 plan, introduce
separate `prime.proposer` / `prime.verifier` / `prime.repairer` host
services (the single `prime.bounded-autonomy` controller is the only
new host service in this phase), or reuse P4's `prime.continuity-store`
/ P3's `prime.child-runner`.

**Witness strategy** (confirmed): deterministic fake-worker, one Orb
invocation for the success path (`make asterion-prime-p5-run` with
`ASTERION_PRIME_P5_MODE=success`), one Orb invocation for the three
refusal paths (`make asterion-prime-p5-run-limits` with
`ASTERION_PRIME_P5_MODE=limits`). The success-path witness shows
verify-fail → repair → verify-pass; the limits-path witness shows the
three closed stopping-condition enum values
(`iteration-cap-exceeded`, `duration-cap-exceeded`, `no-progress`) in
a single `jq -s slurp + .[N]` array — mirror of P4's `9d1a2bb7` fix
and Phase 7's `-limits` target.

**Provider gate** (confirmed): P5 stays unpublished in
`create_provider()` until `make asterion-prime-p5-run` AND
`make asterion-prime-p5-run-limits` both pass. A separate Task-16
commit then flips the witness-passed flag, mirroring the P3 / P4
closure path exactly.

---

## Spec diff table (P5 vs P1 vs P2 vs P3 vs P4)

| Row | P1 (closed) | P2 (closed) | P3 (closed) | P4 (closed) | P5 (Phase 8) |
|---|---|---|---|---|---|
| **Lifecycle** | One process opens a session, runs cells, seals one checkpoint, exits. | One process holds a session across one retrieval batch + one finalization. | One process opens root session, admits one child at depth=2, joins results, exits. | Two processes (A seals, B attaches at generation+1). | **One process** opens one IPython session, runs propose → verify → (repair → verify)\* iterations inside a bounded loop, seals one receipt, exits. |
| **Store / continuity** | `FilePrimeSessionStore` opens fresh; refuses to rebind. | Inherits P1. | Inherits P1 — no new store classmethods. | Adds `open_continued(prior_root, next_identity)` for cross-process continuation. | **Inherits P1** — no new store classmethods. P5 has no recovery semantics, no continuity, no checkpoint. |
| **Identity** | `generation = 1` on first open. | Inherits P1. | Root `generation = 1`; child `generation = root.generation + 1` admitted via `PrimeSessionBackend.attach(next_identity)`. | `generation` monotonic across process boundaries; `open_continued` is the only widening path. | `generation = 1` on first open. P5 has no generation monotonicity across loops (every loop is its own root_run_id). |
| **Host services** | `prime.ipython`, `prime.p1-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend` | Adds `prime.p2-oracle`; reuses P1 substrate. | **Adds `prime.child-runner`**; adds `prime.p3-oracle`; reuses P1 substrate minus `prime.ipython`. | Adds `prime.continuity-store`; adds `prime.p4-oracle`. | **Adds `prime.bounded-autonomy`** (NEW host service, single loop controller); adds `prime.p5-oracle`; reuses P1 substrate as-is (P5 IS ipython-driven). |
| **Oracle** | Asserts checkpoint sealing + cleanup ordering. | Asserts retrieval bounded within context+cost caps. | Asserts child admitted + child joined + limits reject. | Asserts generation monotonic + no committed effect replay. | Asserts propose admitted + verify failed-then-repaired + bounded stop (closed 5-element terminal_reason enum). |
| **Sealed receipt** | `PrimeCheckpointDigest` | Adds retrieval digest. | `P3NativeReceipt` with `root_run_id`, `child_run_id`, `joined_result_sha256`, `depth_reached`, `refusal_reason`. | `P4NativeReceipt` with `prior_checkpoint_sha256`, `new_generation`. | `P5NativeReceipt` with `root_run_id`, `propose_step_count`, `verify_step_count`, `repair_step_count`, `failed_verify_count`, `terminal_reason` (closed enum), `joined_workspace_digest`. |
| **Cross-process boundary** | None. | None. | None (in-process child factory). | **Load-bearing** (process A → process B). | None. Single-process `asyncio` loop. |
| **Limits enforced** | Budget via session backend. | Same. | depth / concurrency / budget / cancellation (application-level on top of session-backend budget gate). | Same. | **iteration (MAX_ITERATIONS=3) / repair-step duration (30_000ms) / loop duration (120_000ms) / workspace-digest dedup** — application-level on top of session-backend duration gate. |
| **Stopping conditions** | `recovery-required` on cancel mid-run; otherwise single terminal. | Same. | `recovery-required` on cancel-mid-child. | Same. | **Closed 5-element enum**: `success`, `iteration-cap-exceeded`, `duration-cap-exceeded`, `no-progress`, `cancelled`. No `still-running` ever public. |

---

## Components (block order)

### Task 1 — Capability package JSON contracts

- **Files**:
  - `src/asterion/capabilities/prime_bounded_autonomy_native/payload/capability-package.json`
  - `src/asterion/capabilities/prime_bounded_autonomy_native/payload/capabilities/prime-bounded-autonomy.json`
- **Convention**: `capability_id` in the capability JSON equals the
  application ID (`prime.bounded-autonomy`); `package_id` in the
  package JSON equals `prime-bounded-autonomy-native`.
- **Closed key sets**: validated by `validate_assembly_manifest`,
  `CapabilityPackageManifest`, `validate_capability_manifest`. All
  `EDGE_FIELDS` arrays sorted unique.
- **Canonical-form detail (load-bearing, learned from Phase 7 Task 11):
  the JSON files MUST end with a trailing newline**
  (`\n`); `open_portable_payload` rejects non-canonical bytes.
- **Tests**: `tests/test_asterion_prime_p5_capability_package.py`
  - `test_package_loads_and_lists_required_services` — set equality on
    `{prime.bounded-autonomy, prime.p5-oracle, prime.pi-extension,
    prime.private-trace, prime.session-backend, prime.ipython}`.
  - `test_capability_id_matches_application_id`.
  - `test_package_files_end_with_trailing_newline`.

### Task 2 — Application assembly JSON

- **File**:
  `src/asterion/applications/prime/assemblies/prime-bounded-autonomy.json`
- Mirrors P1/P2/P3/P4 assembly shape exactly. `host_policies`,
  `host_events`, `host_artifacts` are `[]` (validator uses set equality,
  not `>=`).
- **Tests**: `tests/test_asterion_prime_p5_assembly.py`
  - `test_assembly_references_capability_package_and_services`.
  - `test_assembly_runtime_id_is_asterion_prime`.

### Task 3 — Host service `prime.bounded-autonomy`

- **File**: `src/asterion/applications/prime/services.py` (extend).
- **Pattern**: copy `_open_local_corpus_service` from
  `src/asterion/capabilities/dci/implementation/services.py:285` for the
  factory; copy the `ChildRunnerHostService` shape from
  `src/asterion/applications/prime/services.py` (P3 Phase 7) for the
  `public_identity` / async-context-manager contract.
- **Public symbols**:
  - `BoundedAutonomyLoop` — async context manager exposing
    `public_identity`, `run_loop(*, root_run_id, signal) ->
    P5NativeReceipt | P5StoppedReceipt` (single terminal result,
    one of the closed 5-element enum values), `last_step_timed_out`.
  - `create_bounded_autonomy_host_service(context:
    HostServiceFactoryContext) -> BoundedAutonomyLoop`.
- **Limits** (configurable per-context, defaults from spec):
  - `MAX_ITERATIONS = 3`, `MAX_REPAIR_DURATION_MS = 30_000`,
    `MAX_TOTAL_DURATION_MS = 120_000`,
    `WORKSPACE_DIGEST_DEDUP = True`.
- **Internal methods** (NOT separate host services):
  `_propose_step()`, `_verify_step()`, `_repair_step()` — each is a
  thin wrapper that calls `prime.ipython` (propose / repair) or
  `prime.p5-oracle` (verify) under the corresponding limit.
- **Workspace-digest dedup adapter**: `_compute_workspace_digest()` —
  canonical JSON SHA-256 of the most recent propose / repair
  artifact; compared against the prior digest; equal-digest runs
  terminate with `terminal_reason = "no-progress"` before the next
  verify step.
- **Redaction**: `public_identity` MUST redact `private_root_identity`.
  `terminal_reason` MUST be one of the closed enum:
  `{"success", "iteration-cap-exceeded", "duration-cap-exceeded",
  "no-progress", "cancelled"}`.
- **Tests**: `tests/test_asterion_prime_p5_loop_service.py`
  - `test_service_exposes_public_identity_without_leaking_private_root`.
  - `test_service_runs_propose_verify_repair_loop_to_success`.
  - `test_service_stops_with_iteration_cap_exceeded_after_three_fails`.
  - `test_service_stops_with_duration_cap_exceeded_on_slow_propose`.
  - `test_service_stops_with_no_progress_on_unchanged_workspace_digest`.
  - `test_service_emits_single_terminal_receipt_no_still_running_state`.
  - `test_workspace_digest_dedup_rejects_second_gate_with_same_digest`.

### Task 4 — P5 host contract

- **File**: `src/asterion/applications/prime/p5/host.py` (new).
- **Pattern**: copy `P3RuntimeHost` / `P4RuntimeHost` Protocol shape
  (`src/asterion/applications/prime/p3/host.py`,
  `src/asterion/applications/prime/p4/host.py`).
- **Public symbols**: `P5RuntimeHost` (Protocol) with
  `validate_runtime_services(...)`, `run_loop(*, root_run_id, signal) ->
  P5NativeReceipt`, `report_loop_stopped(...)`, `wait_finalization(...)`.
  Dataclasses: `P5LoopCall`, `P5LoopResult`, `P5StoppedResult`,
  `P5Finalization`.
- **Frozen `terminal_reason` enum**: as a `Literal[...]` type alias so
  the closed set is enforced at the type level (mirror of P3's refusal
  enum).
- **Tests**: `tests/test_asterion_prime_p5_host_protocol.py`
  - `test_protocol_shape_matches_p3_p4_runtime_host`.
  - `test_terminal_reason_is_closed_five_element_enum`.

### Task 5 — P5 oracle

- **File**: `src/asterion/applications/prime/p5/oracle.py` (new).
- **Pattern**: copy `P3Oracle` / `P4Oracle` shape.
- **Public symbols**: `P5Oracle.check(propose_step_count,
  verify_step_count, repair_step_count, failed_verify_count,
  terminal_reason, joined_workspace_digest, refusal_reason) ->
  P5OracleReceipt`. Oracle verdict enum (closed 4 strings):
  `{"pass", "fail", "no-progress", "cancelled"}`.
- **Tests**: `tests/test_asterion_prime_p5_oracle.py`
  - `test_oracle_passes_when_propose_admitted_verify_repaired_and_stopped`.
  - `test_oracle_rejects_when_failed_verify_count_zero` → reason
    `propose-not-verified`.
  - `test_oracle_rejects_when_terminal_reason_is_still_running` →
    reason `unbounded-stop`.
  - `test_oracle_rejects_when_no_progress_but_digest_changed` →
    reason `invariant-violation::no-progress-digest-mismatch`.

### Task 6 — P5 sealed receipt

- **File**: `src/asterion/applications/prime/p5/receipt.py` (new).
- **Public symbols**: `P5NativeReceipt` (frozen; spec field set),
  `P5StoppedReceipt` (frozen; carries the same field set with
  `terminal_reason` always non-`success`),
  `seal(root_run_id, root_generation, propose_step_count,
  verify_step_count, repair_step_count, failed_verify_count,
  terminal_reason, joined_workspace_digest) -> P5NativeReceipt`,
  `build(...)` for tests.
- **Canonical-form detail (load-bearing)**: the receipt SHA is
  computed over canonical JSON bytes (sorted keys, no whitespace,
  trailing newline). Mirror P3 / P4's `seal` shape exactly.
- **Tests**: `tests/test_asterion_prime_p5_receipt.py`
  - `test_seal_receipt_is_digest_stable` — same inputs → same SHA;
    any field change → different SHA.
  - `test_seal_receipt_with_zero_repair_steps_round_trips`.

### Task 7 — P5 runtime binding

- **File**: `src/asterion/applications/prime/p5/runtime_binding.py`
  (new).
- **Pattern**: copy `build_p4_runtime`.
- **Public symbols**: `P5_HOST_CAPABILITIES` (6-tuple),
  `build_p5_runtime(context: AsterionPrimeRuntimeContext) ->
  AsterionPrimeRuntimeClient`, internal `_P5RuntimeSession`.
- **Tests**: `tests/test_asterion_prime_p5_runtime_binding.py`
  - `test_build_p5_runtime_returns_client_with_p5_methods`.
  - `test_build_p5_runtime_does_not_register_child_runner_or_continuity_store`.

### Task 8 — P5 operator

- **File**: `src/asterion/applications/prime/p5/operator.py` (new).
- **Pattern**: copy `src/asterion/applications/prime/p3/operator.py`
  structure (single `main()`, `_preflight(env)`, `_build_resources(env)`,
  `_invoke_loop(resources)`; **plus** a `_run_mode_success(resources)`
  vs `_run_mode_limits(resources)` split that dispatches on
  `ASTERION_PRIME_P5_MODE`).
- **Public symbols**: `main()`, `run_success_path(env)`,
  `run_limits_path(env)`, `_preflight(env)`, `_build_resources(env)`,
  `_invoke_loop(resources)`, `_run_scenario_iteration_cap(resources)`,
  `_run_scenario_duration_cap(resources)`,
  `_run_scenario_no_progress(resources)`.
- **Mode dispatch**:
  - `ASTERION_PRIME_P5_MODE = "success"` → one loop run, one
    `P5NativeReceipt` to stdout (terminal_reason = success).
  - `ASTERION_PRIME_P5_MODE = "limits"` → three scenario runs, one
    `P5StoppedReceipt` per scenario to stdout (one JSON object per
    line; the Makefile slurps with `jq -s`).
- **Env**:
  - `ASTERION_PRIME_OPERATOR_ROOT` (required)
  - `ASTERION_PRIME_P5_PRIVATE_ROOT` (required)
  - `ASTERION_PRIME_P5_MODE` ∈ `{success, limits}` (required)
  - `ASTERION_PRIME_PI_ENTRY` (operator preflight only)
- **Order inside `_build_resources`**:
  1. `session_backend.attach(root_identity)` — root generation=1.
  2. `loop = bounded_autonomy_host_service` — exposes the single
     loop controller (uses `prime.ipython` for propose / repair and
     `prime.p5-oracle` for verify, all injected via
     `HostServiceFactoryContext`).
  3. Build `p5_oracle`, `pi_extension` (fake), `private_trace` (fake).
- **Success-path stdout** (one JSON line):
  ```json
  {"status":"completed","root_run_id":"<id>","root_generation":1,"propose_step_count":1,"verify_step_count":2,"repair_step_count":1,"failed_verify_count":1,"terminal_reason":"success","joined_workspace_digest":"<sha>","receipt_sha256":"<sha>","private_root_redacted":true}
  ```
- **Limits-path stdout** (one JSON line per refusal scenario, three
  records total):
  ```json
  {"status":"stopped","scenario":"iteration-cap","terminal_reason":"iteration-cap-exceeded","verify_step_count":3,"repair_step_count":0,"failed_verify_count":3,"joined_workspace_digest":"<sha>","receipt_sha256":"<sha>","private_root_redacted":true}
  {"status":"stopped","scenario":"duration-cap","terminal_reason":"duration-cap-exceeded","verify_step_count":0,"last_step_timed_out":true,"joined_workspace_digest":"<sha>","receipt_sha256":"<sha>","private_root_redacted":true}
  {"status":"stopped","scenario":"no-progress","terminal_reason":"no-progress","verify_step_count":0,"joined_workspace_digest":"<sha>","receipt_sha256":"<sha>","private_root_redacted":true}
  ```
- **Deterministic fake-worker contract**: receives
  `(mode, iteration, scenario, run_id)` and emits a payload whose
  SHA differs across tuples. The fake-worker `repair_step` payload
  MUST produce a workspace digest that differs from the prior
  step's digest, **except** in scenario C (`no-progress`), where the
  repair is a no-op and the digest is forced to equal the iter-1
  digest.
- **State.py additions**: NONE expected — `prime.bounded-autonomy`
  does not need new identity / checkpoint / store classmethods.
  **Confirmed-during-execution**: if Task 3 surfaces a need for a new
  helper on `PrimeBackendIdentity` (e.g., `workspace_digest()`), add
  it minimally and report in the task's commit message; do not
  preemptively add anything in this plan.
- **Tests**: `tests/test_asterion_prime_p5_operator.py`
  - `test_success_path_emits_completed_json_with_terminal_reason_success`.
  - `test_limits_path_emits_three_refusal_records_in_order`.
  - `test_operator_exits_nonzero_on_unknown_mode`.
  - `test_no_progress_scenario_forces_unchanged_workspace_digest`.
  - `test_iteration_cap_scenario_emits_three_failed_verifies`.

### Task 9 — Dispatcher branch

- **File**: `src/asterion/applications/prime/runtime_binding.py`
  (existing). Around the `build_asterion_prime_runtime(context)` switch
  (around line 320), add a branch:
  - `("prime.bounded-autonomy", "1.0.0") -> build_p5_runtime`.
- **Tests**: extend `tests/test_asterion_prime_p5_runtime_binding.py`
  - `test_dispatcher_routes_p5_application_id_to_build_p5_runtime`.
  - `test_dispatcher_does_not_route_p5_to_child_runner_or_continuity`.

### Task 10 — Provider factory entry (P5 stays unpublished)

- **File**: `src/asterion/applications/prime/provider.py` (existing).
- **Edit**: add `prime_bounded_autonomy_application()` and
  `create_prime_bounded_autonomy_provider()` factories.
  **`create_provider()` does NOT include P5 yet** — the witness must
  pass first (Task 16).
- **Tests**: `tests/test_asterion_prime_p5_provider.py`
  - `test_provider_factory_exists_and_returns_p5_application`.
  - `test_create_provider_does_not_include_p5_until_witness_passes`.

### Task 11 — First-party package registration

- **File**: `src/asterion/applications/first_party_packages.py`
  (existing). **Phase 7 lesson (load-bearing, learned from the
  Task-11 subagent that discovered it from P4 mirror):** "register in
  registry dict" is **not sufficient**. Phase 8 explicitly requires:
  - A capability-package Python module at
    `src/asterion/capabilities/prime_bounded_autonomy_native/{__init__.py,
    provider.py}` (mirror P3's
    `src/asterion/capabilities/prime_recursive_workflow_native/`).
  - The `provider.py` factory function must mirror P3's exact shape:
    `PACKAGE_REF`, `CAPABILITY_REF`, `P5_INPUT_PRESET`,
    `P5_ARTIFACT_ID`, `P5_RECEIPT_MEDIA_TYPE` constants plus a
    `create_provider()` factory.
  - The capability-package JSON files (Task 1) require canonical-form
    with trailing `\n` for `open_portable_payload` (see Task 1).
- **Edit**:
  1. Create `src/asterion/capabilities/prime_bounded_autonomy_native/__init__.py`
     with `PRIME_BOUNDED_AUTONOMY_NATIVE_PACKAGE` symbol re-export.
  2. Create `src/asterion/capabilities/prime_bounded_autonomy_native/provider.py`
     with the factory + closed-enum media type constants.
  3. Register `PRIME_BOUNDED_AUTONOMY_NATIVE_PACKAGE` in
     `src/asterion/applications/first_party_packages.py` registry dict.
- **Tests**: extend
  `tests/test_asterion_first_party_packages.py` to assert presence
  and the exact factory shape.

### Task 12 — `pyproject.toml` entry point

- **File**: `pyproject.toml` (around lines 41–43).
- **Edit**: add one line to
  `[project.entry-points."asterion.host_services"]`:
  ```
  prime.bounded-autonomy = "asterion.applications.prime.services:create_bounded_autonomy_host_service"
  ```
- **Tests**: `tests/test_asterion_prime_p5_entry_point.py`
  - `test_bounded_autonomy_entry_point_is_registered` —
    `importlib.metadata` lookup.

### Task 13 — Root fixture

- **File**: `tests/fixtures/prime_p5/small_root.json`
- **Content**: pre-baked `PrimeBackendIdentity` (gen=1) for operator
  tests (mirror of `tests/fixtures/prime_p3/small_root.json`).

### Task 14 — Makefile target `asterion-prime-p5-run` + `-limits` + `-verbose`

- **File**: `Makefile`.
- **Default**: `ASTERION_PRIME_P5_PRIVATE_ROOT ?= $(CURDIR)/.asterion-private/prime-p5-witness`.
- **Logic**: runs the operator via Orb mirror of P3's pattern
  (`uv run --no-cache --isolated --with <wheel> --with python-dotenv
  python -I -m asterion.applications.prime.p5.operator`). Capture the
  stdout JSON line(s). Assert with `jq -e`:
  1. **Success path** (`-run` with `MODE=success`):
     `status == "completed"`, `terminal_reason == "success"`,
     `propose_step_count == 1`, `verify_step_count == 2`,
     `repair_step_count == 1`, `failed_verify_count == 1`,
     `joined_workspace_digest` non-null and differs from the
     fake-worker's iter-1 digest, `receipt_sha256` non-null.
  2. **Limits path** (`-run-limits` with `MODE=limits`):
     re-invokes the operator. Uses `jq -s slurp` to fold the three
     JSON lines into an array. Asserts each refusal record by
     **fixed index** `.[0]`–`.[2]`, not by line count:
     - `.[0].scenario == "iteration-cap"` and
       `.[0].terminal_reason == "iteration-cap-exceeded"` and
       `.[0].verify_step_count == 3` and
       `.[0].failed_verify_count == 3`.
     - `.[1].scenario == "duration-cap"` and
       `.[1].terminal_reason == "duration-cap-exceeded"` and
       `.[1].last_step_timed_out == true`.
     - `.[2].scenario == "no-progress"` and
       `.[2].terminal_reason == "no-progress"` and
       `.[2].joined_workspace_digest` equals the iter-1 digest.
  3. `jq -s` + `.[N]` index dodges the make-recipe `\$` quoting trap
     that bit P4 — see `serene-mixing-cat.md` §"Critical files" /
     Phase 6 commit `9d1a2bb7`.
- **Add**: `asterion-prime-p5-run-verbose` — diagnostic sibling that
  emits the per-step oracle verdict stream (no assertions, no
  public-safe contract).

### Task 15 — Unit-test suite sweep

- Files listed in each component above. **All targets must pass with
  ruff clean on changed files and the detachment gate still at 0.**

### Task 16 — Task-4 mirror: publish P5 in the public selector

- **File**: `src/asterion/applications/prime/provider.py`.
- **Edit**: only after `make asterion-prime-p5-run` AND
  `make asterion-prime-p5-run-limits` both pass, add P5 to
  `create_provider()` and to `pyproject.toml`
  `asterion.application_index`. **Revert the P1 regression test**
  (which counts 5 apps) to expect 6 apps (P7 + P1 + P2 + P3 + P4 +
  P5).
- **Tests**: combined with Task 10.

---

## Critical files to modify

### Existing files (small, surgical edits)

- `src/asterion/applications/prime/runtime_binding.py` — add P5
  dispatcher branch (Task 9).
- `src/asterion/applications/prime/provider.py` — add factories
  (Tasks 10, 16).
- `src/asterion/applications/prime/services.py` — extend with
  `BoundedAutonomyLoop` and `create_bounded_autonomy_host_service`
  (Task 3).
- `src/asterion/applications/first_party_packages.py` — register
  package (Task 11).
- `pyproject.toml` — add host-service entry point (Task 12),
  application_index row on publish (Task 16).
- `Makefile` — add `asterion-prime-p5-run` + `-limits` + `-verbose`
  targets (Task 14).
- `src/asterion/agents/prime/state.py` — **likely no additions**;
  confirm in Task 8 and report (no preemptive edits).

### New files (large blocks)

- `src/asterion/applications/prime/p5/{__init__.py, host.py,
  oracle.py, receipt.py, runtime_binding.py, operator.py}`
- `src/asterion/capabilities/prime_bounded_autonomy_native/__init__.py`
- `src/asterion/capabilities/prime_bounded_autonomy_native/provider.py`
- `src/asterion/capabilities/prime_bounded_autonomy_native/payload/{capability-package.json,
  capabilities/prime-bounded-autonomy.json}`
- `src/asterion/applications/prime/assemblies/prime-bounded-autonomy.json`
- `tests/test_asterion_prime_p5_{capability_package, assembly,
  loop_service, host_protocol, oracle, receipt, runtime_binding,
  operator, provider, entry_point}.py`
- `tests/fixtures/prime_p5/small_root.json`

---

## Reuse from existing substrate

### Reused unchanged (cite file paths)

- `asterion.prime` session factory
  (`src/asterion/agents/prime/session.py`) — extended through
  `PrimeSessionBackend.attach(next_identity)` for the loop's session;
  no duplicate session engine.
- `PrimeSessionBackend` (`src/asterion/agents/prime/backend.py:244`) —
  the budget / cancellation / duration gate that
  `prime.bounded-autonomy` composes through.
- `PrimeBackendIdentity` / `PrimeCheckpoint`
  (`state.py:73, :160`) — reused unchanged; P5 has no new
  identity / checkpoint / store classmethods.
- Workspace-digest helper (`src/asterion/capabilities/prime_*/payload/...`)
  — if a canonical-form SHA-256 helper already exists in the
  P3 / P4 capability payloads, copy it verbatim into the P5
  capability-payload and into the dedup adapter. **If it does not
  exist, add a minimal `canonical_json_sha256(obj)` helper under
  `agents/prime/util.py`** and reuse it across all three payloads.
- `prime.ipython` (`src/asterion/applications/prime/services.py`) —
  reused as-is for the propose step and the repair step. P5 does
  not introduce a new worker protocol.
- `prime.pi-extension`, `prime.private-trace`,
  `prime.session-backend` — reused from P1/P2/P3/P4 unchanged.
- `_open_local_corpus_service` template
  (`capabilities/dci/implementation/services.py:285`) — copy for
  `create_bounded_autonomy_host_service`.
- `P3RuntimeHost` / `P4RuntimeHost` Protocol shape
  (`applications/prime/p3/host.py:111`,
  `applications/prime/p4/host.py`) — copy for `P5RuntimeHost`.
- `build_p3_runtime` / `build_p4_runtime`
  (`applications/prime/p3/runtime_binding.py`,
  `applications/prime/p4/runtime_binding.py`) — copy for
  `build_p5_runtime`.
- P3 / P4 operator structure (`applications/prime/p3/operator.py`,
  `applications/prime/p4/operator.py`) — copy for the P5 operator's
  CLI/preflight/resources/invoke pattern (minus the commit/recover
  split, plus the success/limits mode dispatch).
- P1/P2/P3/P4 capability-package + assembly JSON shape — verbatim.

### Newly introduced

- `prime.bounded-autonomy` host service — single loop controller,
  not three separate services (per architectural principle).
- Closed 5-element `terminal_reason` enum
  (`Literal["success", "iteration-cap-exceeded",
  "duration-cap-exceeded", "no-progress", "cancelled"]`).
- Workspace-digest dedup adapter — `_compute_workspace_digest()`
  inside `BoundedAutonomyLoop`.
- Closed 4-element oracle verdict enum
  (`Literal["pass", "fail", "no-progress", "cancelled"]`).
- `P5NativeReceipt` / `P5StoppedReceipt` dataclasses (frozen,
  digest-stable).
- `canonical_json_sha256(obj)` helper (only if it does not already
  exist in the substrate — verify in Task 1).

---

## Verification

End-to-end (`make asterion-prime-p5-run`):

1. Clean `ASTERION_PRIME_P5_PRIVATE_ROOT`.
2. Run operator once with `ASTERION_PRIME_P5_MODE=success`.
3. Parse stdout JSON. Expect `status="completed"`,
   `terminal_reason="success"`, `propose_step_count=1`,
   `verify_step_count=2`, `repair_step_count=1`,
   `failed_verify_count=1`, non-null
   `joined_workspace_digest` (different from iter-1 digest), non-null
   `receipt_sha256`.
4. The Makefile's `jq -e` assertions abort the target on any failure.

End-to-end (`make asterion-prime-p5-run-limits`):

1. Re-invoke operator with `ASTERION_PRIME_P5_MODE=limits`.
2. Parse three refusal records (one per scenario:
   `iteration-cap`, `duration-cap`, `no-progress`) via
   `jq -s slurp`.
3. Assert each scenario by fixed index `.[0]`–`.[2]`:
   - `.[0]`: scenario=`iteration-cap`,
     `terminal_reason=iteration-cap-exceeded`,
     `verify_step_count=3`, `failed_verify_count=3`.
   - `.[1]`: scenario=`duration-cap`,
     `terminal_reason=duration-cap-exceeded`,
     `last_step_timed_out=true`.
   - `.[2]`: scenario=`no-progress`,
     `terminal_reason=no-progress`,
     `joined_workspace_digest` equals iter-1 digest.

Targeted regression (no full suite under research intensity):

- `uv run python -m unittest -v tests.test_asterion_prime_p5_capability_package tests.test_asterion_prime_p5_assembly tests.test_asterion_prime_p5_loop_service tests.test_asterion_prime_p5_host_protocol tests.test_asterion_prime_p5_oracle tests.test_asterion_prime_p5_receipt tests.test_asterion_prime_p5_runtime_binding tests.test_asterion_prime_p5_operator tests.test_asterion_prime_p5_provider tests.test_asterion_prime_p5_entry_point`
- Detachment gate: `uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"` → must print `0`.
- Ruff on changed files: clean.

Task-4 mirror (after both witness paths pass):

- `make asterion-prime-p1-run`, `make asterion-prime-p2-run`,
  `make asterion-prime-p3-run`, `make asterion-prime-p4-run`
  still pass (no regression on the P1/P2/P3/P4 witnesses).
- `tests/test_asterion_prime_p1_provider.py` updated to expect
  6 apps.

---

## Out-of-scope (carried explicitly forward)

1. No real-model invocation in the P5 witness. Real Pi subprocess
   use stays P1/P7 territory.
2. No subprocess supervisor as the default loop path (in-process
   `asyncio` is the default per spec §"Newly introduced").
3. No source-detachment gate changes.
4. No new host services beyond `prime.bounded-autonomy`.
   `prime.ipython`, `prime.pi-extension`, `prime.private-trace`,
   `prime.session-backend` are reused from P1/P2/P3/P4 without
   modification.
5. No `prime.proposer` / `prime.verifier` / `prime.repairer`
   decomposition. The single loop controller is the only new host
   service in Phase 8.
6. No P6 work in this plan. P6 (Phase 9) gets its own plan after
   Phase 8 closes.

---

## Open risks (recorded, not blocking)

1. **`canonical_json_sha256` may not exist as a shared helper.** If
   neither the P3 nor P4 capability-payloads export a canonical-form
   SHA-256 helper, Task 1 must add a minimal one under
   `agents/prime/util.py` and reuse it across P3 / P4 / P5
   capability-payloads. Recording now so we don't reinvent the
   helper three times.
2. **State.py may surface a need for a new identity helper during
   Task 8.** Pre-flight reading suggests no addition is needed (P5
   has no generation monotonicity and no recovery semantics), but
   if `BoundedAutonomyLoop` discovers a need for a new
   `PrimeBackendIdentity` helper (e.g., a `workspace_digest()`
   convenience method), add it minimally and report in the task's
   commit message. Do not preemptively add anything.
3. **The 5-element `terminal_reason` enum is the public contract.**
   Any addition or rename is a breaking change for
   `make asterion-prime-p5-run-limits` and for downstream consumers
   (P6 will likely depend on these codes). Mirror of P3's
   5-element refusal-reason enum contract.
4. **Deterministic fake-worker for propose / repair digests.** The
   fake-worker payload MUST include `(mode, iteration, scenario,
   run_id)` so the `joined_workspace_digest`, `failed_verify_count`,
   and `receipt_sha256` checks are meaningful. Same constraint as
   P3 / P4 (`serene-mixing-cat.md` Risk 2).
