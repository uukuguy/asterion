# Task 1 Report: Canonical Prime Source-Lock Identity

## Scope

Implemented the canonical source-lock bytes and domain-separated SHA-256 identity helpers in `source_lock.py`, with focused coverage in `test_prime_source_lock.py`.

## TDD evidence

RED was run before implementation:

```text
uv run python -m unittest -v tests.test_prime_source_lock
```

It failed during test import because `canonical_prime_source_lock_bytes` and `prime_source_lock_sha256` did not yet exist.

GREEN and verification passed:

```text
uv run python -m unittest -v tests.test_prime_source_lock
uv run ruff check src/asterion/applications/prime_agent/source_lock.py tests/test_prime_source_lock.py
uv run pyright src/asterion/applications/prime_agent/source_lock.py tests/test_prime_source_lock.py
git diff --check
```

The Prime source-lock suite ran 10 tests successfully; Ruff reported no issues, Pyright reported 0 errors/warnings/information, and `git diff --check` passed.

## Implementation

- Validates through the existing exact `_validate_lock` contract.
- Serializes only `commit`, `package_lock_sha256`, and `tree_sha256` as sorted, compact UTF-8 JSON with `ensure_ascii=False` and `allow_nan=False`.
- Hashes `asterion.prime-source-lock/v1\0` followed by those canonical bytes.
- Normalizes validation and encoding failures to `PrimeSourceLockError("Prime source lock is invalid")` without a chained cause.
- Leaves `verify_prime_source_lock` behavior unchanged and performs no filesystem, Git, network, subprocess, or package-manager work.

## Concerns

None. Pyright emitted only its informational notice that a newer version is available; the check itself passed.
