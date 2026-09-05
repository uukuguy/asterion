# Prime Authority Bundle and Linux Launch Implementation Plan

> **For agentic workers:** Use the existing delegated Terra implementation lane with independent Sol review. Preserve concurrent edits and exact source locks.

**Goal:** Deliver the trusted Linux execution boundary needed by Prime P1, then reuse it for the remaining six scenarios.

**Architecture:** The operator-owned manager launches distinct-identity supervisor, authority and application processes in one Linux guest. Authority code runs from an exact immutable CPython bundle; executable, code bundle and launch policy have separate identities. A parsed record never grants execution authority.

**Tech Stack:** Python orchestration and unittest; Linux Unix sockets, peer credentials and process/FD ownership; existing Prime runtime and Docker worker; current public Asterion contracts.

## Global constraints

- Preserve `asterion.agent-runtime/v1`, `asterion.capability/v1`, `asterion.capability-package/v1` and `asterion.application-assembly/v1`.
- Preserve exact legacy authority receipt/IPC parsing. A Python interpreter digest cannot populate the legacy standalone-authority-ELF catalog.
- No provider configuration, executable commands or launch paths enter portable capability/application manifests. Operator release inventories are private deployment inputs.
- Prime and Native remain parallel runtimes. P1-A qualification does not close P1-B multi-turn/compaction semantics.
- Deterministic backend tests prove process boundaries only. Real scenario closure needs finite model execution, trusted oracle, cancellation and cleanup evidence.
- No global harness activation, full ARC benchmark, publication or deployment into an unrelated service.

## Task 1: establish the actual Linux baseline

**Files:** `src/asterion/applications/prime_agent/operator/authority_docker_socket.py`, its exact entry in `resources/authority-artifact-lock.json`, `tests/test_prime_p1_authority_docker_socket.py`.

**Consumes:** existing `_new_daemon_client()` and trusted stdlib socket constants.
**Produces:** working Linux atomic close-on-exec/nonblocking Unix client creation without relaxing external-value validation.

- [x] Reproduce current Linux failure using the existing socket test.
- [x] Accept stdlib `SocketKind` integer constants while preserving zero/missing-flag rejection.
- [x] Add a regression using actual enum-valued constants and refresh only the changed source hash.
- [x] Run all 16 P1 modules on macOS and in an isolated installed Linux environment. Execute the Linux socket/SCM_RIGHTS/memfd tests rather than counting skips as evidence.

## Task 2: exact immutable bundle admission and launch contract

**Create:** `src/asterion/applications/prime_agent/operator/authority_bundle.py`, `tests/test_prime_authority_bundle.py`.

**Consumes:** an operator-selected root, one exact trusted release inventory and platform identity.
**Produces:** an opaque admitted bundle with separate interpreter, complete bundle and launch-profile digests; explicit close and pre-spawn revalidation. No self-registration or authority receipt issuance.

The release inventory enumerates every regular file as a sorted unique relative path, byte length, mode and SHA-256. Reject absolute/traversing/noncanonical paths, symlinks at every component, extra/missing files, duplicate identities, non-root ownership and group/world writes. Root is trusted; the application must be unable to write the bundle. The selected interpreter is a fixed code-owned relative entry and must match its exact Linux ELF target. Never infer compatibility from the current machine.

Canonical bundle hashing binds the exact inventory format/version, target and entries with domain-separated canonical bytes. The launch profile is code-owned and separately hashed; it defines isolated Python startup, cleared environment, fixed bootstrap entry and explicit inherited descriptor roles. The complete import closure includes stdlib, native extensions and dependencies, with explicitly declared system libraries in the operator TCB. No ambient cwd, user-site, editable install or PYTHONPATH import selection is permitted.

- [x] Freeze concrete types/signatures and wire migration: `docs/superpowers/specs/2026-09-05-prime-authority-bundle-contract.md`.
- [x] Implement the frozen module and descriptor-tree helper; Sol approved admission/revalidation after security regressions. Actual process consumer follows in Task 3.
- [x] Verify deterministic identity, mutation and inventory rejection, ownership/symlink checks, closed-state rejection and redaction with sentinel values. Tests cover source/mac and actual root-owned Linux boundaries.
- [ ] Produce a real installed bundle and prove its bootstrap loads only the selected import roots.

## Task 3: manager, supervisor and authority process path

**Create:** `src/asterion/applications/prime_agent/operator/authority_manager.py`, `src/asterion/applications/prime_agent/operator/authority_supervisor.py`, `tests/test_prime_authority_linux_launch.py`.
**Integrate:** `authority_process.py`, existing admission/configuration and exact runtime proxy.

**Consumes:** admitted bundle, exact operator identities, finite scenario profile, authority-only configuration and key descriptors.
**Produces:** one authenticated ready/execute/terminal path, final public-safe status rendered by the supervisor, and complete child reaping.

The manager launches authority before connection; authority binds/listens itself. Expected UID/PID values come from the manager, not the application. The supervisor validates reciprocal peer identity and one-run frame sequencing. Required descriptors survive their intended exec only, immediately regain CLOEXEC and never reach the application. The application runs provider → assembly → runner → Prime runtime with an exact proxy. It cannot supply signing keys, choose an executable or render the final trusted result.

- [ ] Run deterministic-backend success/failure/cancellation under actual distinct Linux UIDs, without persistent account changes.
- [ ] Exercise forged application output, wrong peer, FD leakage, replay, timeout and child crash; require one terminal and cleanup before return.
- [ ] Wire preflight to actual side-effect-free readiness and preserve acceptance as installed contract verification.
- [ ] Connect killable model transport and the existing worker/oracle chain only after the process boundary passes independent review.

## Task 4: semantic scenario qualification and reuse

**Integrate:** P1 workload/request/receipt profiles and existing P2/P3 launchers; P4–P7 missing host/launcher routes follow the canonical seven-scenario worklist.

- [ ] Prove P1-A finite real coding execution without calling it full P1 PASS.
- [ ] Deliver exact P1-B versioned multi-turn and compaction scenario; verify namespace/import/function/cwd/files persist in the same kernel and final oracle passes after model-caused edits.
- [ ] Reuse the same admitted host boundary for P2/P3, then P4/P5, P6 local/project scope and P7 finite public subset.
- [ ] Require installed public application paths, causal worker evidence, aggregate finite accounting, cancellation and cleanup for each of seven scenario completions.

## Verification and delivery

Use unittest success/failure/subTest matrices for each actual boundary. Before integrating packaged files or entry points, run full promotion with private complete failure logs; never infer current PASS from historical gates or residual temporary directories. Update the canonical worklist with exact named commands, platform and scope. Review and commit bounded source changes independently of pre-existing uncommitted documents.
