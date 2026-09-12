# Prime Source Lock Canonical Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the existing exact Prime source lock a canonical, domain-separated SHA-256 identity usable by the future P1 authority without reading a Git checkout.

**Architecture:** `source_lock.py` already validates the immutable `PrimeSourceLock` triple. Add a pure canonical serialization of that validated triple and a SHA-256 helper over `asterion.prime-source-lock/v1\0` plus those bytes. This is metadata identity only—not source verification, image building, Docker, model work, or an execution grant.

**Tech Stack:** Python 3.12 stdlib, `unittest`.

## Global Constraints

- Accept only exact `PrimeSourceLock`, reuse `_validate_lock`, and expose no filesystem, Git, network, package-manager, Docker, or subprocess path.
- Canonical form is UTF-8 JSON with `ensure_ascii=False`, `allow_nan=False`, sorted keys, and compact separators; identity is `sha256(domain + canonical_bytes)`.
- Stable values give the same digest; one lock field mutation changes it; invalid locks fail through `PrimeSourceLockError` without exposing input.
- Development tests cover determinism, field-change sensitivity, and invalid type only; do not enumerate malformed strings already covered by source-lock validation tests.

### Task 1: Canonical source-lock bytes and digest

**Files:**

- Modify: `src/asterion/applications/prime_agent/source_lock.py`
- Modify: `tests/test_prime_source_lock.py`

**Interfaces:**

- Produces: `canonical_prime_source_lock_bytes(lock: object) -> bytes` and `prime_source_lock_sha256(lock: object) -> str`.

- [ ] **Step 1: Write RED tests.**

  Add a valid `PrimeSourceLock` test which asserts canonical bytes equal the exact sorted compact JSON mapping (`commit`, `package_lock_sha256`, `tree_sha256`), identical locks have equal 64-character digest, and changing only `tree_sha256` changes it. Assert an `object()` input raises `PrimeSourceLockError`.

- [ ] **Step 2: Run RED.**

  Run: `uv run python -m unittest -v tests.test_prime_source_lock`

  Expected: FAIL because canonical identity functions do not exist.

- [ ] **Step 3: Add pure implementation.**

  Validate through `_validate_lock`, render only the three lock fields in canonical JSON, and hash exact domain bytes plus canonical result. Normalize all validation/encoding errors as `PrimeSourceLockError("Prime source lock is invalid")` without a cause.

- [ ] **Step 4: Run GREEN and commit.**

  Run: `uv run python -m unittest -v tests.test_prime_source_lock && uv run ruff check src/asterion/applications/prime_agent/source_lock.py tests/test_prime_source_lock.py && uv run pyright src/asterion/applications/prime_agent/source_lock.py tests/test_prime_source_lock.py && git diff --check`

  Expected: PASS. Commit: `feat: identify canonical Prime source locks`.

## Self-review

- The function is pure and does not weaken `verify_prime_source_lock`.
- Digest is not plain JSON SHA-256; the fixed domain prefix prevents cross-contract reuse.
