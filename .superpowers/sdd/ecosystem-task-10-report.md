# Ecosystem Task 10 Report

## Status

COMPLETE.

Prime Gateway `ecosystem.capabilities` is closed at the exact domain boundary:
ten selected features, ten passed features, zero blocking features, zero
provider operations, and zero application operations.

H-034 is promoted exactly once after the clean repository and isolated
promotion gates passed. H-035 remains pending.

## RED evidence

Clean base: `04532ec`.

Command:

```bash
uv run python tools/check_prime_parity.py --domain ecosystem.capabilities --provider asterion.prime-gateway
```

Result: exit 1, `status: BLOCKED`, `blocking_feature_count: 10`,
`passed_feature_count: 0`, `reason_codes: ["result-missing"]`,
`provider_operations: 0`, `application_operations: 0`.

Blocking feature IDs:

- `ecosystem.collision-diagnostics`
- `ecosystem.context-files`
- `ecosystem.custom-providers-models`
- `ecosystem.extension-state-commands`
- `ecosystem.extensions-lifecycle`
- `ecosystem.mcp`
- `ecosystem.packages`
- `ecosystem.prompt-templates`
- `ecosystem.skills`
- `ecosystem.tools`

## Implementation

- Added `src/asterion/control/providers/prime/ecosystem_parity_testing.py`.
- Added `tests/test_prime_ecosystem_parity.py`.
- Promoted only the ten Prime Gateway ecosystem rows in
  `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`.
- Kept every native ecosystem row `missing`.
- Updated ledger/checker tests so `Verified-system-parity` remains `BLOCKED` on
  later domains.
- Made promotion bind a verified, detached clone of the pinned Prime source,
  rebuild its exact workspaces, and force all isolated commands to that clone.
- Completed direct sidecar fixtures for the closed `probeReady` descriptor
  contract and isolated nested promotion-test environments.
- Regenerated deterministic Climb state through H-034; H-035 remains pending.

The reducer consumes exactly four provider-free receipts:

- `test.prime-ecosystem-resources.provider-free`
- `test.prime-ecosystem-extensions.provider-free`
- `test.prime-ecosystem-packages.provider-free`
- `test.prime-ecosystem-mcp.provider-free`

It rejects wrong command/source/artifact/module/portfolio identities, wrong
canonical arrays, unexpected keys, nonzero provider/model/process counts,
wrong counts, and sentinel leakage.

## GREEN evidence

Focused Task10 tests in clean candidate:

```bash
uv run python -m unittest -v tests.test_prime_ecosystem_parity tests.test_prime_parity_ledger tests.test_check_prime_parity
```

Result: 32 tests OK.

Exact domain checker in clean candidate:

```bash
uv run python tools/check_prime_parity.py --domain ecosystem.capabilities --provider asterion.prime-gateway
```

Result: exit 0, `status: PASS`, `selected_feature_count: 10`,
`passed_feature_count: 10`, `blocking_feature_count: 0`,
`provider_operations: 0`, `application_operations: 0`.

Climb ecosystem gates in clean candidate:

- H-028: `npm --prefix packages/typescript/prime-gateway test -- test/ecosystem.test.mjs test/main.test.mjs` — 51/51 tests pass.
- H-029: `uv run python -m unittest -v tests.test_prime_ecosystem_real_process tests.test_setup_prime_agent` — 20 tests OK.
- H-030: `make test.prime-ecosystem-resources.provider-free` — 43 tests OK.
- H-031: `make test.prime-ecosystem-extensions.provider-free` — Python 3 tests OK and TypeScript ecosystem 22/22 OK.
- H-032: `make test.prime-ecosystem-packages.provider-free` — TypeScript build OK and Python 25 tests OK.
- H-033: `make test.prime-ecosystem-mcp.provider-free` — TypeScript build OK and Python 7 tests OK.

## Closure gates

Clean commit: `ef685f4`.

The exact H-034 cycle passed:

- `make check` — 1,954 Python tests plus TypeScript, Ruff, docs, Rust
  test/fmt/clippy, sdist, and wheel all passed.
- `make promotion-check` — `promotion full PASS commands=27
  provider_operations=0 full_dataset=no`.
- `git diff --check` — passed in the clean worktree.
- `runs.csv` contains cycle 34 exactly once with command
  `check.ecosystem-capabilities-closure`.
- Climb session state is H-034 passed with next action H-035; the generated
  research tree agrees.

The native RLM probe emitted its existing `External-limited` status during
repository tests. It was not promoted to PASS and performed zero provider
operations in this verification.

## Claims

- Claim: Prime Gateway `ecosystem.capabilities` exact domain is PASS at 10/10.
- Claim: the closure is provider-free and performs no provider/model operation.
- Claim: every native ecosystem result remains missing.
- Non-claim: `Verified-system-parity` is not PASS.
- Non-claim: `interfaces.operations` has no parity result yet; H-035 is only the
  pending closure inventory.
- Claim: H-034 passed exactly once after clean repository and promotion gates.
