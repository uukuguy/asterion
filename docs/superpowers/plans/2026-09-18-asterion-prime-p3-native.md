# Phase 7 — Asterion Prime P3 (recursive workflow) Native Rebuild

## Context

**Why now.** The 9-phase native detachment program is at Phase 7. Phases 1–6
are closed. P7, P1, P2, and P4 are native, witnessed, and republished in the
public selector. P3, P5, P6 remain unbuilt. The spec
(`docs/superpowers/specs/2026-09-18-asterion-prime-p3-native-design.md`)
defines P3 as one application-level demonstration of Asterion Prime's
recursive composition capability.

**What Phase 7 must produce.** A native `prime.recursive-workflow`
application that demonstrates depth / concurrency / budget / cancellation
limits on admitted child sessions without importing Prime RLM APIs. This
is the spec's P3 witness (L342–L344) verbatim:

> one root run starts an admitted child through `prime.child-runner`, the
> child result is joined into the root result, and exact depth /
> concurrency / budget limits reject further spawning without Prime RLM
> APIs.

**What Phase 7 must NOT do.** Touch the source-detachment gate, drive a
real Pi subprocess in the witness, write the P5 plan, or default to a
subprocess supervisor for child sessions (the in-process factory is the
default).

**Witness strategy** (confirmed): deterministic fake-worker, one Orb
invocation for the success path (`make asterion-prime-p3-run`), one Orb
invocation for the four refusal paths (`make asterion-prime-p3-run-limits`).
Mirror of P4's witness shape with **half the surface area** (no
cross-process supervisor needed — P3 has no recovery semantics).

**Provider gate** (confirmed): P3 stays unpublished in `create_provider()`
until `make asterion-prime-p3-run` AND `make asterion-prime-p3-run-limits`
both pass. A separate Task-15 commit then flips the witness-passed flag,
mirroring the P4 closure path exactly.

---

## Spec diff table (P3 vs P1 vs P2 vs P4)

| Row | P1 (closed) | P2 (closed) | P4 (closed) | P3 (Phase 7) |
|---|---|---|---|---|
| **Lifecycle** | One process opens a session, runs cells, seals one checkpoint, exits. | One process holds a session across one retrieval batch + one finalization. | Two processes (A seals, B attaches at generation+1). | **One process** opens root session, admits one child at depth=2, joins results, exits. |
| **Store / continuity** | `FilePrimeSessionStore` opens fresh; refuses to rebind. | Inherits P1. | Adds `open_continued(prior_root, next_identity)` for cross-process continuation. | **Inherits P1** — no new store classmethods. P3 has no recovery semantics. |
| **Identity** | `generation = 1` on first open. | Inherits P1. | `generation` monotonic across process boundaries; `open_continued` is the only widening path. | Root `generation = 1`; child `generation = root.generation + 1` admitted via `PrimeSessionBackend.attach(next_identity)`. |
| **Host services** | `prime.ipython`, `prime.p1-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend` | Adds `prime.p2-oracle`; reuses P1 substrate. | Adds `prime.continuity-store`; adds `prime.p4-oracle`. | **Adds `prime.child-runner`** (NEW host service); adds `prime.p3-oracle`; reuses P1 substrate minus `prime.ipython` (P3 is compose-only, not ipython-driven). |
| **Oracle** | Asserts checkpoint sealing + cleanup ordering. | Asserts retrieval bounded within context+cost caps. | Asserts generation monotonic + no committed effect replay. | Asserts child admitted + child joined + limits reject. |
| **Sealed receipt** | `PrimeCheckpointDigest` | Adds retrieval digest. | `P4NativeReceipt` with prior_checkpoint_sha256, new_generation. | `P3NativeReceipt` with `root_run_id`, `child_run_id`, `joined_result_sha256`, `depth_reached`, `refusal_reason`. |
| **Cross-process boundary** | None. | None. | **Load-bearing** (process A → process B). | None (single process; in-process child session factory). |
| **Limits enforced** | Budget via session backend. | Same. | Same. | **depth / concurrency / budget / cancellation** — application-level on top of session-backend budget gate. |

---

## Components (block order)

### Task 1 — Capability package JSON contracts
- **Files**:
  - `src/asterion/capabilities/prime_recursive_workflow_native/payload/capability-package.json`
  - `src/asterion/capabilities/prime_recursive_workflow_native/payload/capabilities/prime-recursive-workflow.json`
- **Convention**: `capability_id` in the capability JSON equals the
  application ID (`prime.recursive-workflow`); `package_id` in the
  package JSON equals `prime-recursive-workflow-native`.
- **Closed key sets**: validated by `validate_assembly_manifest`,
  `CapabilityPackageManifest`, `validate_capability_manifest`. All
  EDGE_FIELDS arrays sorted unique.
- **Tests**: `tests/test_asterion_prime_p3_capability_package.py`
  - `test_package_loads_and_lists_required_services` — set equality on
    `{prime.child-runner, prime.p3-oracle, prime.pi-extension,
    prime.private-trace, prime.session-backend}`.
  - `test_capability_id_matches_application_id`.

### Task 2 — Application assembly JSON
- **File**:
  `src/asterion/applications/prime/assemblies/prime-recursive-workflow.json`
- Mirrors P1/P2/P4 assembly shape exactly. `host_policies`,
  `host_events`, `host_artifacts` are `[]` (validator uses set equality,
  not `>=`).
- **Tests**: `tests/test_asterion_prime_p3_assembly.py`
  - `test_assembly_references_capability_package_and_services`.

### Task 3 — Host service `prime.child-runner`
- **File**: `src/asterion/applications/prime/services.py` (extend).
- **Pattern**: copy `_open_local_corpus_service` from
  `src/asterion/capabilities/dci/implementation/services.py:285`.
- **Public symbols**:
  - `ChildRunnerHostService` — async context manager exposing
    `public_identity`, `admit_child(*, parent_run_id, depth, signal)
    -> ChildAdmission | ChildAdmissionRefused`, `join_child_result(*,
    parent_run_id, child_receipt) -> str` (returns
    `joined_result_sha256`).
  - `create_child_runner_host_service(context: HostServiceFactoryContext)
    -> ChildRunnerHostService`.
- **Limits** (configurable per-context, defaults from spec):
  - `MAX_DEPTH = 2`, `MAX_CONCURRENT_CHILDREN = 1`,
    `MAX_CHILD_COST_USD = Decimal("0.10")`,
    `MAX_TOTAL_DURATION_MS = 60_000`.
- **Redaction**: `public_identity` MUST redact `private_root_identity`.
  Refusal reasons MUST be one of the closed enum:
  `{"depth-exceeded", "concurrency-exceeded", "budget-exceeded",
  "cancelled", "session-backend-rejected"}`.
- **Tests**: `tests/test_asterion_prime_p3_child_runner_service.py`
  - `test_service_exposes_public_identity_without_leaking_private_root`.
  - `test_service_admits_child_at_depth_two`.
  - `test_service_refuses_depth_three_with_depth_exceeded`.
  - `test_service_refuses_concurrent_two_with_concurrency_exceeded`.
  - `test_service_refuses_budget_exhausted_with_budget_exceeded`.
  - `test_join_child_result_is_digest_stable`.

### Task 4 — P3 host contract
- **File**: `src/asterion/applications/prime/p3/host.py` (new).
- **Pattern**: copy `P4RuntimeHost` Protocol shape
  (`src/asterion/applications/prime/p4/host.py`).
- **Public symbols**: `P3RuntimeHost` (Protocol) with
  `validate_runtime_services(...)`, `run_root(*, parent_run_id,
  child_request, signal) -> P3RootResult`,
  `report_admission_refused(...)`, `wait_finalization(...)`.
  Dataclasses: `P3RootCall`, `P3RootResult`, `P3ChildRequest`,
  `P3AdmissionRefused`, `P3Finalization`.
- **Tests**: `tests/test_asterion_prime_p3_host_protocol.py`
  - `test_protocol_shape_matches_p4_runtime_host`.

### Task 5 — P3 oracle
- **File**: `src/asterion/applications/prime/p3/oracle.py` (new).
- **Pattern**: copy `P4Oracle` shape.
- **Public symbols**: `P3Oracle.check(root_result, child_receipt,
  joined_sha256, refusal_reason) -> P3OracleReceipt`.
- **Tests**: `tests/test_asterion_prime_p3_oracle.py`
  - `test_oracle_passes_when_child_admitted_and_joined`.
  - `test_oracle_rejects_when_child_result_missing` → reason
    `child-not-joined`.
  - `test_oracle_rejects_when_depth_exceeded` → reason
    `limits-violated::depth-exceeded`.

### Task 6 — P3 sealed receipt
- **File**: `src/asterion/applications/prime/p3/receipt.py` (new).
- **Public symbols**: `P3NativeReceipt` (frozen; spec field set),
  `seal(root_run_id, root_generation, child_run_id, child_generation,
  child_result_sha256, joined_result_sha256, depth_reached,
  refusal_reason) -> P3NativeReceipt`, `build(...)` for tests.
- **Tests**: `tests/test_asterion_prime_p3_receipt.py`
  - `test_seal_receipt_is_digest_stable` — same inputs → same SHA;
    any field change → different SHA.
  - `test_seal_receipt_with_null_child_round_trips`.

### Task 7 — P3 runtime binding
- **File**: `src/asterion/applications/prime/p3/runtime_binding.py` (new).
- **Pattern**: copy `build_p4_runtime`.
- **Public symbols**: `P3_HOST_CAPABILITIES` (5-tuple),
  `build_p3_runtime(context: AsterionPrimeRuntimeContext) ->
  AsterionPrimeRuntimeClient`, internal `_P3RuntimeSession`.
- **Tests**: `tests/test_asterion_prime_p3_runtime_binding.py`
  - `test_build_p3_runtime_returns_client_with_p3_methods`.

### Task 8 — P3 operator
- **File**: `src/asterion/applications/prime/p3/operator.py` (new).
- **Pattern**: copy `src/asterion/applications/prime/p4/operator.py`
  structure (but **single mode**, no commit/recover split).
- **Public symbols**: `main()`, `run_success_path(env)`,
  `run_limits_path(env)`, `_preflight(env)`, `_build_resources(env)`,
  `_invoke_composed_root(resources)`.
- **Child identity construction** (load-bearing): the operator is the
  single authority on the child identity. Inside `_build_resources`,
  after `session_backend.attach(root_identity)` succeeds, the operator
  derives `child_identity = root_identity.bump_generation()` (a new
  helper on `PrimeBackendIdentity` that returns a copy with
  `generation += 1`, all other fields preserved, **including** the
  runtime-binding SHAs `pi_command_sha256` / `extension_binding_fingerprint`
  / `ceilings_sha256` per D-2026-09-18-01 inheritance rules). The
  derived identity is then passed to `child_runner.admit_child(...)`.
  This keeps `prime.child-runner` itself stateless about generation
  math; the operator owns "what child to admit", the runner owns "is
  it admissible".
- **Env**:
  - `ASTERION_PRIME_OPERATOR_ROOT` (required)
  - `ASTERION_PRIME_P3_PRIVATE_ROOT` (required)
  - `ASTERION_PRIME_P3_MODE` ∈ `{success, limits}` (required)
  - `ASTERION_PRIME_PI_ENTRY` (operator preflight only)
- **Order inside `_build_resources`**:
  1. `session_backend.attach(root_identity)` — root generation=1.
  2. `child_identity = root_identity.bump_generation()` (operator-owned).
  3. `child_runner` exposed via the host service, takes the derived
     `child_identity`.
  4. Build `p3_oracle`, `pi_extension` (fake), `private_trace` (fake).
- **Success-path stdout** (one JSON line):
  ```json
  {"status":"completed","root_run_id":"<id>","root_generation":1,"child_run_id":"<id>","child_generation":2,"child_result_sha256":"<sha>","joined_result_sha256":"<sha>","depth_reached":2,"refusal_reason":null,"receipt_sha256":"<sha>","private_root_redacted":true}
  ```
- **Limits-path stdout** (one JSON line per refusal scenario):
  ```json
  {"status":"refused","scenario":"depth","refusal_reason":"depth-exceeded","receipt_sha256":"<sha>","private_root_redacted":true}
  ```
  Four records emitted in order: `depth`, `concurrency`, `budget`,
  `cancellation`.
- **Deterministic fake-worker contract**: receives `(mode, depth,
  run_id)` and emits a payload whose SHA differs across tuples.
- **Tests**: `tests/test_asterion_prime_p3_operator.py`
  - `test_success_path_emits_completed_json_with_child_joined`.
  - `test_limits_path_emits_four_refusal_records`.
  - `test_operator_exits_nonzero_on_unknown_mode`.
  - `test_admission_refused_does_not_spawn_model`.

### Task 9 — Dispatcher branch
- **File**: `src/asterion/applications/prime/runtime_binding.py` (existing).
- **Edit**: at the `build_asterion_prime_runtime(context)` switch
  (around line 320), add a branch:
  - `("prime.recursive-workflow", "1.0.0") -> build_p3_runtime`.
- **Tests**: extend `tests/test_asterion_prime_p3_runtime_binding.py`
  - `test_dispatcher_routes_p3_application_id_to_build_p3_runtime`.

### Task 10 — Provider factory entry (P3 stays unpublished)
- **File**: `src/asterion/applications/prime/provider.py` (existing).
- **Edit**: add `prime_recursive_workflow_application()` and
  `create_prime_recursive_workflow_provider()` factories.
  **`create_provider()` does NOT include P3 yet** — the witness must
  pass first (Task 16).
- **Tests**: `tests/test_asterion_prime_p3_provider.py`
  - `test_provider_factory_exists_and_returns_p3_application`.
  - `test_create_provider_does_not_include_p3_until_witness_passes`.

### Task 11 — First-party package registration
- **File**: `src/asterion/applications/first_party_packages.py` (existing).
- **Edit**: register `PRIME_RECURSIVE_WORKFLOW_NATIVE_PACKAGE` in the
  registry dict.
- **Tests**: extend
  `tests/test_asterion_first_party_packages.py` to assert presence.

### Task 12 — `pyproject.toml` entry point
- **File**: `pyproject.toml` (around lines 41–43).
- **Edit**: add one line to
  `[project.entry-points."asterion.host_services"]`:
  ```
  prime.child-runner = "asterion.applications.prime.services:create_child_runner_host_service"
  ```
- **Tests**: `tests/test_asterion_prime_p3_entry_point.py`
  - `test_child_runner_entry_point_is_registered` —
    `importlib.metadata` lookup.

### Task 13 — Root fixture
- **File**: `tests/fixtures/prime_p3/small_root.json`
- **Content**: pre-baked `PrimeBackendIdentity` (gen=1) for operator
  tests (mirror of `tests/fixtures/prime_p4/small_state.json`).

### Task 14 — Makefile target `asterion-prime-p3-run` + `-limits`
- **File**: `Makefile`.
- **Default**: `ASTERION_PRIME_P3_PRIVATE_ROOT ?= $(CURDIR)/.asterion-private/prime-p3-witness`.
- **Logic**: runs the operator once via Orb mirror of P2's pattern
  (`uv run --no-cache --isolated --with <wheel> --with python-dotenv
  python -I -m asterion.applications.prime.p3.operator`). Capture the
  stdout JSON line. Assert with `jq -e`:
  1. `status == "completed"`, `child_run_id` non-null,
     `depth_reached == 2`.
  2. `child_generation == root_generation + 1`.
  3. `child_result_sha256 != root_result_sha256` (child did real work).
  4. `joined_result_sha256` non-null, `receipt_sha256` non-null,
     `refusal_reason == null`.
- **Add**: `asterion-prime-p3-run-limits` — re-invokes the operator with
  `ASTERION_PRIME_P3_MODE=limits`. Asserts four refusal records each
  with the right `refusal_reason` and a non-null `receipt_sha256`. Use
  `jq -s` slurp + `.[N]` index (not `jq -e --argjson ... --argjson ...`)
  to dodge the make-recipe `\$` quoting trap that bit P4 — see
  `serene-mixing-cat.md` §"Critical files" / Phase 6 commit `9d1a2bb7`.
  Each refusal record sits at a fixed index `.[0]`–`.[3]`; assert by
  scenario name field equality, not by line count.
- **Add**: `asterion-prime-p3-run-verbose` diagnostic sibling.

### Task 15 — Unit-test suite (one per component above)
- Files listed in each component above. **All targets must pass with
  ruff clean on changed files and the detachment gate still at 0.**

### Task 16 — Task-4 mirror: publish P3 in the public selector
- **File**: `src/asterion/applications/prime/provider.py`.
- **Edit**: only after `make asterion-prime-p3-run` AND
  `make asterion-prime-p3-run-limits` both pass, add P3 to
  `create_provider()` and to `pyproject.toml`
  `asterion.application_index`. **Revert the P1 regression test**
  (which counts 4 apps) to expect 5 apps (P7 + P1 + P2 + P4 + P3).
- **Tests**: combined with Task 10.

---

## Critical files to modify

Existing files (small, surgical edits):

- `src/asterion/applications/prime/runtime_binding.py` — add P3 dispatcher
  branch (Task 9).
- `src/asterion/applications/prime/provider.py` — add factories
  (Tasks 10, 16).
- `src/asterion/applications/prime/services.py` — extend with
  `ChildRunnerHostService` (Task 3).
- `src/asterion/applications/first_party_packages.py` — register package
  (Task 11).
- `pyproject.toml` — add host-service entry point (Task 12).
- `Makefile` — add `asterion-prime-p3-run` + `-limits` targets
  (Task 14).

New files (large blocks):

- `src/asterion/applications/prime/p3/{__init__.py, host.py, oracle.py,
  receipt.py, runtime_binding.py, operator.py}`
- `src/asterion/capabilities/prime_recursive_workflow_native/payload/{capability-package.json, capabilities/prime-recursive-workflow.json}`
- `src/asterion/applications/prime/assemblies/prime-recursive-workflow.json`
- `tests/test_asterion_prime_p3_{capability_package, assembly,
  child_runner_service, host_protocol, oracle, receipt,
  runtime_binding, operator, provider, entry_point}.py`
- `tests/fixtures/prime_p3/small_root.json`

## Reuse from existing substrate

- `asterion.prime` session factory (`src/asterion/agents/prime/session.py`)
  — extended through `PrimeSessionBackend.attach(next_identity)`; no
  duplicate session engine.
- `PrimeSessionBackend` (`src/asterion/agents/prime/backend.py:244`) —
  the budget / cancellation gate that `prime.child-runner` composes
  through.
- `PrimeBackendIdentity` / `PrimeCheckpoint` (`state.py:73, :160`) —
  reused unchanged.
- `_open_local_corpus_service` template
  (`capabilities/dci/implementation/services.py:285`) — copy for
  `create_child_runner_host_service`.
- `P4RuntimeHost` Protocol shape (`applications/prime/p4/host.py:111`) —
  copy for `P3RuntimeHost`.
- `build_p4_runtime` (`applications/prime/p4/runtime_binding.py`) —
  copy for `build_p3_runtime`.
- P4 operator structure (`applications/prime/p4/operator.py`) — copy
  for the P3 operator's CLI/preflight/resources/invoke pattern (minus
  the commit/recover split).
- P1/P2/P4 capability-package + assembly JSON shape — verbatim.

---

## Verification

End-to-end (`make asterion-prime-p3-run`):

1. Clean `ASTERION_PRIME_P3_PRIVATE_ROOT`.
2. Run operator once with `ASTERION_PRIME_P3_MODE=success`.
3. Parse stdout JSON. Expect `status="completed"`, `depth_reached=2`,
   non-null `child_run_id`, non-null `joined_result_sha256`,
   non-null `receipt_sha256`, `refusal_reason == null`.
4. The Makefile's `jq -e` assertions abort the target on any failure.

End-to-end (`make asterion-prime-p3-run-limits`):

1. Re-invoke operator with `ASTERION_PRIME_P3_MODE=limits`.
2. Parse four refusal records (one per scenario: `depth`,
   `concurrency`, `budget`, `cancellation`).
3. Assert each `refusal_reason` is the expected closed-enum value and
   each `receipt_sha256` is non-null.

Targeted regression (no full suite under research intensity):

- `uv run python -m unittest -v tests.test_asterion_prime_p3_capability_package tests.test_asterion_prime_p3_assembly tests.test_asterion_prime_p3_child_runner_service tests.test_asterion_prime_p3_host_protocol tests.test_asterion_prime_p3_oracle tests.test_asterion_prime_p3_receipt tests.test_asterion_prime_p3_runtime_binding tests.test_asterion_prime_p3_operator tests.test_asterion_prime_p3_provider tests.test_asterion_prime_p3_entry_point`
- Detachment gate: `uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"` → must print `0`.
- Ruff on changed files: clean.

Task-4 mirror (after both witness paths pass):

- `make asterion-prime-p1-run`, `make asterion-prime-p2-run`,
  `make asterion-prime-p4-run` still pass (no regression on the
  P1/P2/P4 witnesses).
- `tests/test_asterion_prime_p1_provider.py` updated to expect 5 apps.

---

## Out-of-scope (carried explicitly forward)

- No real-model invocation in the P3 witness. Real Pi subprocess use
  stays P1/P7 territory.
- No subprocess supervisor as the default child path (in-process is
  the default per spec §"Architectural principle").
- No source-detachment gate changes.
- No new host services beyond `prime.child-runner`.
  `prime.pi-extension`, `prime.private-trace`, `prime.session-backend`
  are reused from P1/P2/P4 without modification.
- No P5 work in this plan. P5 (Phase 8) gets its own plan after
  Phase 7 closes.

---

## Open risks (recorded, not blocking)

1. **`prime.child-runner` default path is in-process child sessions.**
   If a future P5 / P6 requirement forces cross-process child
   isolation, the subprocess fallback path is already designed
   (spec §"Newly introduced") but is **not** implemented in Phase 7.
   Recording now so we don't re-litigate in Phase 8.
2. **Limits enforced by the runner, not the framework alone.** The
   framework provides the gating primitives (`PrimeSessionBackend`
   budget, cancellation signal), but the **closed enum** of refusal
   reasons and the depth / concurrency ceilings are an application-
   level contract. If a future shared-substrate change moves these
   into the framework, the closed enum must be preserved verbatim
   (spec §"Redaction" / §"Failure behavior").
3. **Refusal-reason stability across versions.** The five-element
   closed enum (`depth-exceeded`, `concurrency-exceeded`,
   `budget-exceeded`, `cancelled`, `session-backend-rejected`) is the
   public contract. Any addition or rename is a breaking change
   for `make asterion-prime-p3-run-limits` and for downstream
   consumers (P5 / P6 will likely depend on these codes).
4. **Deterministic fake-worker for child results.** The fake-worker
   payload MUST include `(mode, depth, run_id)` so the no-replay and
   joined-result checks are meaningful. Same constraint as P4
   (`serene-mixing-cat.md` Risk 2).
