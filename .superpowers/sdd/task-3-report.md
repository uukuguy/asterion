# Task 3 report: declared promotion npm cache contract

## Changes

- `Makefile` accepts the explicit operator resource
  `ASTERION_PROMOTION_NPM_CACHE` and passes it exactly once as `--npm-cache`.
  It also supplies `--node-executable` using the canonical Node 22 executable
  path rather than the npm package shim, which is a symlink and is rejected by
  the closed promotion boundary.
- CI restores the promotion cache at
  `${{ runner.temp }}/asterion-promotion-npm-cache`, keyed by the Asterion,
  Prime Gateway, and external Prime lockfiles. A cache miss fails before the
  promotion target; CI never populates it from the network.
- The README describes the cache as an operator-owned tool resource and says a
  cache miss fails without network access.
- Standalone contract tests cover the Make, README, and CI declarations.

## TDD evidence

RED:

```text
uv run python -m unittest -v tests.test_standalone_repository
FAILED (failures=2)
```

The failures were the absent `ASTERION_PROMOTION_NPM_CACHE` Make declaration
and absent CI cache declaration.

GREEN:

```text
uv run python -m unittest -v tests.test_standalone_repository tests.test_check_promotion
Ran 49 tests ... OK
uv run ruff check tools/check_promotion.py tests/test_check_promotion.py tests/test_standalone_repository.py
All checks passed!
git diff --check
```

## Populated-cache promotion check

Started:

```text
ASTERION_PROMOTION_NPM_CACHE="$(npm config get cache)" make promotion-check
```

The command was executing isolated external-Prime preparation when it was
stopped on parent direction to avoid an unbounded wait. Its actual Make result
was exit 130 (interrupted), so it is not a PASS result. No provider, Docker,
model, benchmark, or network fallback was invoked by this task.

## Remaining concern

The full populated-cache promotion gate remains not rerun to completion. CI
requires a pre-populated cache entry for the exact lock-key before promotion.

## Cache-key authority correction

The CI cache key now hashes the tracked
`packages/typescript/prime-gateway/resources/prime-artifact-lock.json`, which
records both the external Prime `package-lock.json` digest and its source
commit. It retains the tracked Asterion Runtime and Prime Gateway package lock
files and no longer names the ignored
`3th-party/prime-agent/package-lock.json` path. No cache fallback, network,
provider, Docker, or model behavior changed.

### TDD and verification evidence

RED:

```text
uv run python -m unittest -v tests.test_standalone_repository.StandaloneRepositoryTests.test_ci_runs_only_the_full_provider_free_promotion_gate
FAILED (failures=2)
```

The test failed because CI omitted the authority resource and still referenced
the ignored external lockfile.

GREEN:

```text
uv run python -m unittest -v tests.test_standalone_repository.StandaloneRepositoryTests.test_ci_runs_only_the_full_provider_free_promotion_gate
Ran 1 test ... OK
uv run ruff check tests/test_standalone_repository.py
All checks passed!
git diff --check
```
