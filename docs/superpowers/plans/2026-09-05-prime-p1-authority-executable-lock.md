# Prime P1 Authority Executable Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or inline TDD execution task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an authority-owned, target-specific executable lock so a future P1 receipt can derive `authority_executable_sha256` from the executable actually selected by the service manager.

**Architecture:** This is separate from the existing Python source artifact lock. A pure code-owned catalog is empty in production until an independently promoted Linux ELF is recorded; a test-only injected catalog proves parsing and target selection without host inspection. Later launch work will prove manager lock-to-exec FD identity; this task neither adds a Python console script nor changes receipt/execute behavior.

**Tech Stack:** Python 3.10+, `unittest`, canonical JSON, SHA-256, existing image target validation conventions.

## Global Constraints

- The universal wheel stays platform-neutral; runtime Linux/ELF admission is deferred to the launch task.
- Descriptor targets are explicit OCI-like `linux/<architecture>/none`, sorted and unique; no hard-coded host architecture or default amd64.
- Production catalog is empty and fails closed. Fixtures must not populate it with invented production artifact identity.
- No path, command, environment configuration, Docker, network, subprocess, model, source build, socket, receipt, ready, or execute behavior is introduced.

---

### Task 1: Pure promoted executable-lock catalog and aggregate identity

**Files:**

- Create: `src/asterion/applications/prime_agent/operator/authority_executable_lock.py`
- Create: `src/asterion/applications/prime_agent/operator/resources/authority-executable-lock.json`
- Modify: `src/asterion/applications/prime_agent/operator/authority_resources.py`
- Modify: `src/asterion/applications/prime_agent/operator/resources/authority-artifact-lock.json`
- Create: `tests/test_prime_p1_authority_executable_lock.py`
- Modify: `tests/test_prime_p1_authority_resources.py`
- Modify: `tests/test_prime_p1_resource_set_identity.py`

**Interfaces:**

- `AuthorityExecutableLock(target: ImagePlatformDescriptor, format: str, size: int, sha256: str)` is an immutable syntax-only record.
- `resolve_promoted_authority_executable_lock(target: object) -> AuthorityExecutableLock` selects exactly one code-owned record or raises the public-safe authority resource error.
- `AdmittedPrimeP1AuthorityExecutable` is an opaque aggregate child whose contribution includes only the selected lock’s canonical SHA-256 identity; it is not an executable FD and cannot produce a receipt digest yet.

- [ ] **Step 1: RED tests.** Add `test_empty_production_catalog_fails_closed`, a test-only injected catalog proving exact `linux/arm64/none` selection and canonical target ordering, and one subtest matrix for malformed target/ELF format/noncanonical digest/duplicate target rejection. Assert the existing aggregate refuses to construct without the exact new child.

- [ ] **Step 2: Run RED.**

Run: `uv run python -m unittest -v tests.test_prime_p1_authority_executable_lock tests.test_prime_p1_authority_resources tests.test_prime_p1_resource_set_identity`

Expected: FAIL because the executable-lock module and aggregate child do not exist.

- [ ] **Step 3: GREEN implementation.** Parse exact canonical JSON keys `protocol`, `authority_version`, `executables`; validate lowercase SHA-256, positive bounded size, `format == "elf"`, Linux target with `variant == None`, and target sort/uniqueness. Keep `PRIME_P1_PROMOTED_AUTHORITY_EXECUTABLE_CATALOG = ()`; expose only private aggregate admission, with a test injection seam parallel to current promoted catalogs. Extend production resources only after artifact/application/static/evidence/Docker/socket admission and include a stable `authority-executable` contribution. Update the Python source lock after bytes stabilize.

- [ ] **Step 4: GREEN verification and commit.**

Run: `uv run python -m unittest -v tests.test_prime_p1_authority_executable_lock tests.test_prime_p1_authority_resources tests.test_prime_p1_resource_set_identity && uv run ruff check src/asterion/applications/prime_agent/operator/authority_executable_lock.py src/asterion/applications/prime_agent/operator/authority_resources.py tests/test_prime_p1_authority_executable_lock.py && uv run pyright src/asterion/applications/prime_agent/operator/authority_executable_lock.py src/asterion/applications/prime_agent/operator/authority_resources.py tests/test_prime_p1_authority_executable_lock.py && git diff --check`

Expected: PASS without Docker, provider, model, subprocess, or real ELF execution.

Commit: `feat: lock promoted Prime P1 authority executable`

### Task 2: Exact-FD launch proof and receipt provenance

**Files:**

- Modify: `src/asterion/applications/prime_agent/operator/authority_process.py`
- Modify: `src/asterion/applications/prime_agent/operator/authority_protocol.py`
- Modify: `docs/superpowers/specs/2026-09-05-prime-p1-production-authority-redesign.md`
- Modify: `tests/test_prime_p1_authority_process.py`
- Modify: `tests/test_prime_p1_authority_protocol.py`

**Interfaces:** `AuthorityLaunchContract` gains a unique retained executable FD. The manager validates and executes that exact FD; authority compares it to the executed Linux object before exposing a receipt-bound digest.

- [ ] **Step 1: RED tests.** Test mismatched checked/executed FDs, a Python-shim `/proc/self/exe` mismatch, changed live FD identity, and terminal receipt digest mismatch; each must fail closed/redacted.
- [ ] **Step 2: Implement only after a real ELF promotion path exists.** Use bounded, revalidated FD hashing plus Linux `/proc/self/exe` identity; service-manager check-and-exec must use the same open-file description. Do not enable this task against an empty production catalog.

## Self-review

- No component treats a Python module/wheel/image/host architecture as executable evidence.
- Task 1 is a pure no-execution contract; Task 2 cannot turn P1 `basic` into PASS without a genuine promoted authority artifact and separately promoted image/seccomp inputs.
