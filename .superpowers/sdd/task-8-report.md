# Task 8 report: Prime ecosystem packages

## Result

Closed the Task8 review gaps for the provider-free package source evidence
package for `ecosystem.packages`.

The test fixture exposes one portable package through an exact
local-directory candidate and a fake installed-distribution candidate. A
`CapabilitySourceLock` selects the local candidate by exact package ref, source
ID and payload digest; discovery is metadata-only and runs with provider imports
forbidden. The selected payload is materialized as an exact ecosystem package
resource and passed to the real Prime harness. The harness calls the pinned
Prime `resolvePackage()` module surface, which exercises the local
`DefaultPackageManager` resolution path through Task5 `resolvePackage()`, with
source fallback, network, and install paths forbidden. The returned private
selected identity plus payload/resource digests are compared exactly against the
Asterion-admitted package digest contract.

No provider, model, credential, network install, source fallback, package
install command or retained process operation is performed. The public receipt
contains only fixed status, public IDs, counts and digests.

Relocked package module resources:

```text
bundle_sha256: 4cf832dbc246daf6fbb90b791caed72f8513477541fad9516a333a03dfe3ca3a
module_lock_sha256: b02188c15e551cc41f3b93044417556db2e4c50cbf158cb768ac0f25962a3aab
artifact_lock_sha256: c64aeca1b4ffc38289ae5910e16f15901b4dd91f13456b2cae19b48a2b363e95
```

## RED evidence

Initial required command:

```text
uv run python -m unittest -v tests.test_prime_ecosystem_packages
RED: ModuleNotFoundError: No module named 'tests.test_prime_ecosystem_packages'
```

During implementation the TDD loop also caught invalid fixture assumptions:

```text
RED: portable payload missing required root children
RED: capability kind 'analysis' is outside the closed capability kind set
RED: package resource_id did not match the projected file name
RED: source-lock range rejection belongs to resolve_capability_source(), not lock construction
```

Review-fix regression RED evidence:

```text
uv run python -m unittest -v tests.test_prime_ecosystem_packages
RED: test_package_gate_builds_gateway_before_python_harness failed because
     Makefile did not build the TypeScript Gateway before the Python harness.
RED: test_real_prime_package_receipt_is_safe_exact_and_deterministic failed
     because the real harness did not accept or verify the admitted package
     source/payload/resource digest contract through the pinned Prime resolver.
```

## GREEN evidence

```text
uv run python -m unittest -v tests.test_prime_ecosystem_packages
PASS: 6 tests
```

Required gate, run twice:

```text
make test.prime-ecosystem-packages.provider-free
PASS: builds packages/typescript/prime-gateway, then 25 tests
```

```text
make test.prime-ecosystem-packages.provider-free
PASS: builds packages/typescript/prime-gateway, then 25 tests
```

Clean committed-equivalent Task8 state, run twice from
`/private/tmp/asterion-task8-verify-cEli4W/wt` with only offline local
dependencies symlinked:

```text
make test.prime-ecosystem-packages.provider-free
PASS: builds packages/typescript/prime-gateway, then 25 tests
```

```text
make test.prime-ecosystem-packages.provider-free
PASS: builds packages/typescript/prime-gateway, then 25 tests
```

The matrix covers exact local vs installed-distribution source selection,
metadata-only discovery, no provider import, no selected-source fallback,
ambiguous/missing/digest-drift/range rejection, remote locator rejection,
symlink rejection, undeclared payload rejection, real Prime package manager
surface observation, forbidden fallback/install/network, admitted digest
mismatch rejection, missing build-step regression, body-free canonical stdout,
and deterministic digests.

## Files

- `tests/fixtures/prime_ecosystem/v1/packages/`
- `tests/test_prime_ecosystem_packages.py`
- `packages/typescript/prime-gateway/resources/prime-ecosystem-module.mjs`
- `packages/typescript/prime-gateway/resources/prime-ecosystem-module-lock.json`
- `packages/typescript/prime-gateway/src/ecosystem.ts`
- `packages/typescript/prime-gateway/test/ecosystem.test.mjs`
- `packages/typescript/prime-gateway/test/main.test.mjs`
- `tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs`
- `Makefile` (Task8 provider-free target hunk only)

## Concerns

The shared worktree still contains unrelated long-running/RLM/resource drift
from other work. None of those hunks are part of the Task 8 commit.
