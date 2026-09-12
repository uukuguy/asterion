# Prime P1 Application Receipt Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or inline TDD execution task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retain the exact, already admitted P1 application identities needed by a future authority-owned receipt without making them public or granting execution authority.

**Architecture:** `authority_application_resources.py` remains the sole verifier for the fixed P1 resource descriptor.  After every resource is verified, it creates an opaque immutable private identity containing the descriptor identity plus the assembly, package-manifest, workload, starter, and oracle digests selected from fixed paths.  A private method supplies a copy-free internal projection only while the owner is live; receipt issuance and all static/image/source/executable material remain deliberately out of scope.

**Tech Stack:** Python 3.10+, `unittest`, existing no-follow resource verifier and redacted authority errors.

## Global Constraints

- Do not perform Docker, network, subprocess, model, service-manager, image-build, source-root, seccomp, ready, execute, or receipt-signing work.
- No public API may disclose fixed paths, bytes, credentials, model configuration, or an authority capability.
- Preserve the existing resource-set contribution exactly, so this internal retention cannot silently change resource-set semantics.
- Use only representative development-boundary tests: golden admitted projection, tamper rejection before projection, and close-state rejection.

---

### Task 1: Retain exact application receipt identities

**Files:**

- Modify: `src/asterion/applications/prime_agent/operator/authority_application_resources.py`
- Modify: `tests/test_prime_p1_authority_application_resources.py`
- Modify: `src/asterion/applications/prime_agent/operator/resources/authority-artifact-lock.json`

**Interfaces:**

- Produces private immutable `_ApplicationReceiptProjection(assembly_sha256, package_manifest_sha256, workload_sha256, starter_sha256, oracle_sha256)`.
- `AdmittedPrimeP1ApplicationResources._receipt_projection() -> _ApplicationReceiptProjection` returns the exact retained projection only before `close()`; failure is converted to the existing public-safe resource error by its caller.

- [ ] **Step 1: Write the failing tests.** Add a test that admits the packaged set and asserts its five private digest fields exactly equal the descriptor entries.  Add a test that closes it then observes `ValueError` from `_receipt_projection()`.  Extend the existing descriptor digest mutation loop to mutate the starter entry and show admission fails before a projection can exist.

- [ ] **Step 2: Run RED.**

Run: `uv run python -m unittest -v tests.test_prime_p1_authority_application_resources`

Expected: FAIL because `_receipt_projection` does not exist.

- [ ] **Step 3: Implement the minimal private retention.** Add a frozen private projection type, map only the five fixed descriptor paths to their verified SHA-256 strings, validate exact lowercase digests, store it beside the existing descriptor identity, and make `_receipt_projection()` reject closed or malformed state.  Keep `_resource_set_contribution()` based solely on its existing descriptor SHA-256.

- [ ] **Step 4: Update the authority source lock.** Recompute only the `authority_application_resources.py` entry in `resources/authority-artifact-lock.json` after its contents stabilize.

- [ ] **Step 5: Run GREEN and commit.**

Run: `uv run python -m unittest -v tests.test_prime_p1_authority_application_resources tests.test_prime_p1_resource_set_identity tests.test_prime_p1_authority_resources && uv run ruff check src/asterion/applications/prime_agent/operator/authority_application_resources.py tests/test_prime_p1_authority_application_resources.py && uv run pyright src/asterion/applications/prime_agent/operator/authority_application_resources.py tests/test_prime_p1_authority_application_resources.py && git diff --check`

Expected: PASS with no Docker, provider, model, or external process invocation.

Commit: `feat: retain Prime P1 application receipt identity`

## Self-review

- The task preserves P1’s closed application lock and adds only the currently missing internal receipt inputs.
- It intentionally does not claim an authority executable, Prime source, materialized image input, seccomp promotion, or P1 `basic` execution.
- The new method has no path argument and cannot select a resource; all five digests come from already fixed descriptor paths.
