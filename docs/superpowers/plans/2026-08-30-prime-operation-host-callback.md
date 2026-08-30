# Prime Operation Host Callback Implementation Plan

> **Execution mode:** Subagent-Driven Development with one implementation
> agent, one specification reviewer, and one code-quality reviewer per task.
> Every behavior change follows RED -> GREEN TDD and lands as a focused commit.

**Goal:** Make the selected Prime Gateway `operations-v1` production path
actually reachable through one identity-bound, operator-owned Python
`OperationManager`, then close Phase 2 and the Git/worktree graph only after the
real process path and every provider-free gate pass.

**Architecture:** Each root or child session owns one exact `OperationManager`.
The Prime factory validates and snapshots that dispatcher, constructs a
Prime-private Unix callback server, and wraps the ordinary lazy sidecar
transport so the callback starts before Node.  Node constructs one
`PrimeOperationHostClient -> PrimeOperationGateway` chain from the private
descriptor.  Neither adapter resolves private bodies, selects a service,
authorizes, retries, persists, or synthesizes receipts.

**Tech stack:** Python 3.10-3.12, `asyncio` Unix sockets, immutable operation
protocol dataclasses, TypeScript/Node 22 `net`, `unittest`, Node test runner,
repository-native Climb/project-state, Git bundle/worktree closure.

**Approved design:**
`docs/superpowers/specs/2026-08-30-prime-operation-host-callback-design.md`
through commit `8b7fb18`.

## Global constraints

- Preserve `CLI/host -> selected provider -> assembly -> exact
  implementations -> runner -> runtime/host services`.
- Python remains the sole authority and durable operation owner.
- TypeScript remains validation and Prime integration only.
- `operation-dispatcher` is session-bound managed injection, never a global
  entry point or request-selected registry.
- Do not change any public v1 schema or manifest authority semantics.
- Do not execute a provider, application, model, credential, network, package
  manager, restart, telemetry, or upload operation.
- Do not create H-037 until Tasks 1-6 are GREEN and independently approved.
- Preserve the two audited untracked artifact roots until final bundle-backed
  cleanup; no other dirty path is accepted.
- Do not mutate `origin/main`.

---

### Task 1: Add the generic identity-bound dispatcher contract

**Files**

- Modify: `src/asterion/operation/services.py`
- Modify: `src/asterion/operation/manager.py`
- Modify: `tests/test_operation_manager.py`

**Produces**

- `OperationDispatcher` with read-only `session_id`, `generation`,
  `authority_id`, `authority_revision`, plus `execute`, `cancel`, and
  `reconcile`.
- Public-safe identity projections on `OperationManager`; no service map or
  private resolver projection.

- [ ] **Step 1 — RED:** Add
  `TestOperationManager.test_dispatcher_projects_exact_immutable_identity` and
  a hostile-construction case.  Assert the four values come from the manager's
  selected authority/session and cannot be assigned.

  Run:

  ```bash
  uv run python -m unittest -v \
    tests.test_operation_manager.TestOperationManager.test_dispatcher_projects_exact_immutable_identity
  ```

  Expected: FAIL because the projections do not exist.

- [ ] **Step 2 — GREEN:** Add the structural protocol and four properties.
  Do not expose authority budgets, services, request store, journal, or
  resolver.

- [ ] **Step 3 — Verify:** Run:

  ```bash
  uv run python -m unittest -v tests.test_operation_manager tests.test_control_host
  git diff --check
  ```

  Expected: all PASS.

- [ ] **Step 4 — Commit:** `feat: project operation dispatcher identity`.

---

### Task 2: Implement the closed Python callback server

**Files**

- Add: `src/asterion/control/providers/prime/operation_host.py`
- Modify: `src/asterion/control/providers/prime/__init__.py`
- Add: `tests/test_prime_operation_host.py`

**Interfaces**

- `PRIME_OPERATION_HOST_PROTOCOL = "asterion.prime-operation-host/v1"`
- `PrimeOperationHostServer`
- fixed safe `PrimeOperationHostError`
- immutable descriptor `{socketPath, token}`

- [ ] **Step 1 — RED:** Add exact execute/reconcile/cancel tests using a
  recording identity-bound dispatcher.  Add a subtest matrix for wrong token,
  request ID, session, generation, authority, transaction identity, unknown
  keys, extra lines, oversized frame, timeout, hostile receipt, symlinked
  parent, pre-existing socket, and sentinel-bearing exceptions.

  Run:

  ```bash
  uv run python -m unittest -v tests.test_prime_operation_host
  ```

  Expected: FAIL on the missing module, not on fixture syntax.

- [ ] **Step 2 — GREEN:** Implement a one-line, size-capped Unix server.  Require
  request write-side EOF after the line so extra or delayed trailing data is
  rejected deterministically before dispatch.  Bind the four dispatcher
  identity values at construction, snapshot the three
  methods, create the socket under the resolved private root with mode `0600`,
  validate `OperationTransaction`/`OperationReceipt` canonically, and emit only
  the fixed error response.  Preserve `asyncio.CancelledError`; redact every
  other failure.

- [ ] **Step 3 — Lifecycle:** Make `start()` single-use and `close()`
  idempotent.  Track active handler tasks, cancel/drain them, then unlink only
  the exact non-symlink socket created by this server.

- [ ] **Step 4 — Verify:** Run:

  ```bash
  uv run python -m unittest -v \
    tests.test_prime_operation_host tests.test_operation_manager \
    tests.test_prime_operation_bridge
  git diff --check
  ```

  Expected: all PASS; sentinel token/path/body strings absent from exceptions
  and `repr`.

- [ ] **Step 5 — Commit:** `feat: serve Prime operation host callbacks`.

---

### Task 3: Implement the TypeScript callback client and production gateway assembly

**Files**

- Add: `packages/typescript/prime-gateway/src/operation-host.ts`
- Modify: `packages/typescript/prime-gateway/src/index.ts`
- Modify: `packages/typescript/prime-gateway/src/main.ts`
- Add: `packages/typescript/prime-gateway/test/operation-host.test.mjs`
- Modify: `packages/typescript/prime-gateway/test/main.test.mjs`
- Modify descriptor fixtures under `packages/typescript/prime-gateway/test/`
  only where the sole production descriptor validator now requires
  `operationHost`.

**Interfaces**

- `PrimeOperationHostClient implements PrimeOperationDispatcher`
- exact private descriptor `{socketPath, token}`
- one production chain `PrimeOperationHostClient -> PrimeOperationGateway`

- [ ] **Step 1 — RED client protocol:** Add a local Unix test server and assert
  exact execute/reconcile/cancel frames, one connection per call, exact bound
  identities, no transaction body field, exact receipt validation, and zero
  retries.  Reject malformed, mismatched, late, oversized, multi-line, trailing,
  error, and disconnected responses.

  Run:

  ```bash
  npm --prefix packages/typescript/prime-gateway run build
  npm --prefix packages/typescript/prime-gateway test -- \
    test/operation-host.test.mjs
  ```

  Expected: build or test FAIL because the client is absent.

- [ ] **Step 2 — GREEN client:** Implement the client with `node:net`; write one
  line with `socket.end(frame)` so the write side closes before awaiting the
  response.  Enforce the descriptor timeout, a fixed frame cap, exact key
  validation, canonical operation validators, and safe `PrimeOperationError`
  only.

- [ ] **Step 3 — RED production composition:** Add descriptor tests requiring
  exact `operationHost`, rejecting missing/extra/invalid path/token values, and
  proving the real `createSidecarFromDescriptor()` construction injects one
  operation gateway rather than a test-only dispatcher.

- [ ] **Step 4 — GREEN production composition:** Extend
  `PrimeSidecarDescriptor`, `validateDescriptor()`, and
  `createSidecarFromDescriptor()`.  The existing direct
  `PrimeGatewaySidecar` test constructor may still accept an injected fake, but
  the executable descriptor path must require the callback descriptor.

- [ ] **Step 5 — Update non-operation descriptor fixtures:** Add a valid
  unreachable test-local socket path and fixed test token where a real callback
  is not invoked.  Do not relax production validation to preserve old tests.

- [ ] **Step 6 — Verify:** Run:

  ```bash
  npm --prefix packages/typescript/prime-gateway run build
  npm --prefix packages/typescript/prime-gateway test -- \
    test/operation.test.mjs test/operation-host.test.mjs test/main.test.mjs
  npm --prefix packages/typescript/prime-gateway test
  git diff --check
  ```

  Expected: all TypeScript tests PASS.

- [ ] **Step 7 — Commit:** `feat: assemble Prime operation host client`.

---

### Task 4: Bind the Python factory to one managed callback lifecycle

**Files**

- Modify: `src/asterion/control/providers/prime/operation_host.py`
- Modify: `src/asterion/control/providers/prime/factory.py`
- Modify: `tests/test_prime_operation_host.py`
- Modify: `tests/test_prime_control_factory.py`

**Interfaces**

- `PrimeManagedOperationTransport`
- required host service key `operation-dispatcher`
- `_private_descriptor(..., operation_host=...)`

- [ ] **Step 1 — RED preflight:** Extend the factory test fixture with one
  valid identity-bound fake dispatcher.  Add subtests proving missing,
  malformed, property-exploding, and session/generation/authority mismatches
  fail before `process_factory`.  Assert errors and context/launch `repr` redact
  sentinel methods, tokens, private roots, and socket paths.

- [ ] **Step 2 — RED lifecycle:** Test a fake lazy process plus callback server:
  callback starts once before the first request/event, concurrent first calls
  do not double-start, no call creates no socket, close order is process then
  callback, and start failure never starts Node.  A first-start process failure
  must close the callback without masking the safe transport error.

- [ ] **Step 3 — GREEN managed transport:** Implement the wrapper with one
  async start lock and one close lock.  `events()` returns an async iterator that
  awaits callback startup before delegating.  Use only the wrapped process's
  public `request`, `events`, `close`, and production `pid` observation needed
  to distinguish startup failure.

- [ ] **Step 4 — GREEN factory:** Validate/snapshot the dispatcher, create the
  callback server at a fixed private-root child path with a fresh 256-bit token,
  add its descriptor, construct the ordinary process, wrap it, and bind the
  same wrapper to `PrimeControlPlaneClient` and `PrimeOperationClient`.

- [ ] **Step 5 — Verify:** Run:

  ```bash
  uv run python -m unittest -v \
    tests.test_prime_operation_host tests.test_prime_control_factory \
    tests.test_prime_operation_bridge tests.test_control_host
  git diff --check
  ```

  Expected: all PASS; process creation count remains zero for every failed
  preflight case.

- [ ] **Step 6 — Commit:** `feat: bind Prime operation callback lifecycle`.

---

### Task 5: Close root/child session composition and the real process round trip

**Files**

- Modify: `src/asterion/control/children.py`
- Modify: `tests/test_control_children.py`
- Modify: `tests/test_prime_verified_loop.py`
- Add: `tests/test_prime_operation_real_process.py`
- Modify other Python real-sidecar descriptor fixtures reported by the focused
  and full Prime test runs; do not alter evidence semantics.

**Interfaces**

- operator-owned synchronous child dispatcher deriver
- same per-session dispatcher in factory context and `ControlHost`
- real `PrimeControlPlaneClient.operation_client` production round trip

- [ ] **Step 1 — RED child isolation:** Add tests proving a Prime child cannot
  inherit the parent dispatcher, missing deriver fails before provider process
  creation, a wrong-identity child dispatcher fails, and one exact derived
  dispatcher is supplied to both the child factory and child `ControlHost`.
  Non-`operations-v1` providers remain unchanged.

- [ ] **Step 2 — GREEN child composition:** Add the optional deriver to
  `ChildSessionService`.  Invoke it only after the child journal and authority
  exist and before the provider-create fence.  Replace the session-bound
  `operation-dispatcher` entry exactly, propagate the deriver to nested child
  services, and pass the same validated manager to `ControlHost`.

- [ ] **Step 3 — RED real process:** Reuse the checked-in built Node sidecar and
  fake Prime daemon fixture.  Construct a real `OperationManager` with a fake
  operator-owned service, build the Prime client through
  `build_prime_control_plane_client()`, and call:

  ```python
  await client.operation_client.execute(transaction)
  ```

  Assert the complete Python -> Node -> Python path, exact one service call,
  exact receipt identity, callback socket cleanup, no private body in Node
  frames, and zero effect counters.  Add uncertain -> reconcile and uncertain
  -> cancel cases plus callback failure/no-retry.

- [ ] **Step 4 — GREEN real process:** Make only the assembly/lifecycle changes
  needed for the real test.  Do not add a fake production receipt, service map
  to Node, or alternate runner.

- [ ] **Step 5 — Update verified-loop composition:** Derive an exact child
  `OperationManager` from the test operator closure and add callback descriptor
  values to direct real-sidecar fixtures.  Preserve all existing scenario and
  evidence IDs.

- [ ] **Step 6 — Verify focused integration:** Run:

  ```bash
  npm --prefix packages/typescript/prime-gateway run build
  uv run python -m unittest -v \
    tests.test_control_children tests.test_prime_operation_real_process \
    tests.test_prime_verified_loop tests.test_prime_control_factory \
    tests.test_prime_operation_host
  npm --prefix packages/typescript/prime-gateway test
  git diff --check
  ```

  Expected: all PASS with zero provider/application/model/network operations.

- [ ] **Step 7 — Commit:** `feat: close Prime operation production path`.

---

### Task 6: Run the pre-promotion gate and independent review

**Files**

- Add: `.superpowers/sdd/prime-operation-host-callback-review.md`
- Modify implementation/tests only for reviewed findings
- Append only: `docs/status/JOURNAL.md`

- [ ] **Step 1 — Exact focused matrix:** Run:

  ```bash
  npm --prefix packages/typescript/prime-gateway run build
  npm --prefix packages/typescript/prime-gateway test
  uv run python -m unittest -v \
    tests.test_operation_manager tests.test_control_host \
    tests.test_control_children tests.test_prime_operation_bridge \
    tests.test_prime_operation_host tests.test_prime_operation_real_process \
    tests.test_prime_control_factory tests.test_prime_verified_loop
  uv run python -m unittest -v \
    tests.test_prime_parity_ledger tests.test_check_prime_parity \
    tests.test_prime_climb
  uv run python tools/check_prime_parity.py \
    --claim verified-system-parity --provider asterion.prime-gateway
  ```

  Expected: all tests PASS; checker remains exactly 61/0/2 and zero
  provider/application operations.

- [ ] **Step 2 — Repository and distribution matrix:** Run:

  ```bash
  make test
  make lint
  make docs-check
  make check
  make promotion-check
  uv build .
  git diff --check
  ```

  Expected: all PASS; promotion reports zero provider operations and no full
  dataset.

- [ ] **Step 3 — Independent review:** Review the design commit through HEAD
  for dependency direction, root/child identity, callback startup/close races,
  duplicate manager/runner paths, service selection, retries, uncertainty,
  protocol closure, symlink/path safety, redaction, evidence inflation, and
  Phase 3/4 nonclaims.

- [ ] **Step 4 — Fix loop:** Every finding receives RED reproduction, focused
  fix, focused rerun, and independent re-review.  Do not advance with an open
  HIGH/MEDIUM or an unclassified uncertainty.

- [ ] **Step 5 — Record:** Commit the approved review report and append-only
  Journal result as `docs: verify Prime operation callback`.

---

### Task 7: Execute H-037 once and close Phase 2 truthfully

**Files**

- Modify: `tools/climb/cycle.sh`
- Modify: `tools/climb/regen-tree.py`
- Modify: `tests/test_prime_climb.py`
- Modify: `docs/status/climb/hypotheses.yaml`
- Modify: `docs/status/climb/runs.csv`
- Modify: `docs/status/climb/session-state.json`
- Generated: `docs/status/climb/research-tree.md`
- Modify: `docs/status/PRIME-PARITY-LEDGER.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Append only: `docs/status/JOURNAL.md`
- Modify: `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`

- [x] **Step 1 — Dormant gate:** Add H-037 as pending with command identity
  `prime-system-parity-operation-host-callback`.  Its gate reruns Task 6's
  focused real-process test, complete system checker, repository checks, and
  promotion check.  The cleanliness guard permits exactly the two already
  audited artifact roots and rejects every other dirty path.

- [x] **Step 2 — RED canonical transition:** Add a test requiring exactly one
  cycle 37 PASS and `next_action=phase-3-native-kernel-design`; prove it fails
  before executing the gate.  Revert that assertion with an inverse patch so
  the dormant-gate commit is clean.

- [x] **Step 3 — Independently verify dormant gate:** Run all H-037 commands in
  a disposable detached copy.  Expected: exit 0, zero provider/application
  operations, no canonical state mutation.

- [x] **Step 4 — Execute once:** Run `tools/climb/cycle.sh H-037` exactly once,
  restore the closure assertion, regenerate the tree, and prove cycle 37
  appears once.  Commit `climb: close Prime system parity production path`.

- [x] **Step 5 — Truthful state:** Mark Phase 2
  `Verified-system-parity: PASS` with the named real process and repository
  gates.  Keep every native row missing and Phase 3/4 unchecked.  Set the next
  action to Phase 3 native-kernel design, while noting local-main promotion and
  Git closure remain Task 8.

- [x] **Step 6 — Verify and commit:** Run:

  ```bash
  make docs-check
  uv run python -m unittest -v \
    tests.test_prime_climb tests.test_prime_parity_ledger \
    tests.test_check_prime_parity tests.test_prime_operation_real_process
  uv run python tools/check_prime_parity.py \
    --claim verified-system-parity --provider asterion.prime-gateway
  git diff --check
  ```

  Commit `docs: close Prime system parity phase`.

---

### Task 8: Promote local main and close every branch/worktree

**Files and external recovery artifact**

- Add: `docs/status/GIT-RECOVERY-CLOSURE-20260830.md`
- Create: `.git/asterion-pre-phase3-recovery-20260830.bundle`
- Remove after verified recovery: obsolete local branches, registered
  non-primary worktrees, the literal `$(getconf DARWIN_USER_TEMP_DIR)/`, and
  `.task13-promotion-bin/`

- [x] **Step 1 — Audit:** Enumerate every worktree and branch with exact HEAD,
  status paths, reachability, duplicate patch/tree IDs, and sentinel scan.
  Preserve unique non-generated source state with temporary
  `refs/recovery/pre-phase3/*`; never preserve credentials, environments,
  `node_modules`, caches, build output, or private evidence.

- [x] **Step 2 — Provisional bundle:** Create and verify
  `.git/asterion-pre-phase3-recovery-20260830.bundle.tmp` containing the current
  integration head, old local main, archived ecosystem/H-024/H-035/H-036
  lines, every detached unique head, and all accepted recovery refs.

- [x] **Step 3 — Promote:** Move local `main` to the exact verified integration
  commit, switch the primary workspace to `main`, and verify old
  `main@262b2fd` remains reachable.  Do not push or update `origin/main`.

- [x] **Step 4 — Record steady state:** Update branch/recovery fields in
  `CURRENT-STATE.md`, `RESUME-NEXT-SESSION.md`, Journal, and the recovery report.
  Run docs, Climb, ledger, system checker, callback real-process, and
  `git diff --check` before committing `docs: record Git recovery closure`.

- [x] **Step 5 — Final bundle:** Create and verify
  `.git/asterion-pre-phase3-recovery-20260830.bundle` from final local `main`
  and all recovery refs.  Require every audited unique object to appear.  Only
  then remove the provisional bundle.

- [x] **Step 6 — Remove exact obsolete state:** Remove each audited non-primary
  worktree by absolute path, prune, delete obsolete normal branches and
  temporary recovery refs after bundle verification, then delete only the two
  audited artifact roots after rechecking their classified contents.

- [x] **Step 7 — Final verification:** Run:

  ```bash
  git status --short --branch
  git branch -vv
  git worktree list --porcelain
  git bundle verify .git/asterion-pre-phase3-recovery-20260830.bundle
  git rev-parse origin/main
  ```

  Expected: clean local `main`, one primary worktree, no obsolete development
  branch, valid recovery bundle, and unchanged `origin/main` at
  `f1316bb780cf01406b99b8b549461cd02df24138`.

## Terminal definition

This plan is not complete at implementation GREEN.  It completes only when the
real callback path and full gates pass, independent review approves, H-037 and
Phase 2 close exactly once, the verified result is on clean local `main`, all
obsolete worktrees/branches are removed behind a verified recovery bundle, and
Phase 3 native-kernel design is the sole remaining program action.
