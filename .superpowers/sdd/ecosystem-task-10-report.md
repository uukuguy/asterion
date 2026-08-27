# Ecosystem Task 10 Report

## Status

DONE_WITH_CONCERNS.

Prime Gateway `ecosystem.capabilities` is closed at the exact domain boundary:
ten selected features, ten passed features, zero blocking features, zero
provider operations, and zero application operations.

H-034 is not promoted because repository/promotion gates did not produce a
clean PASS in the committed-equivalent candidate.

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
- Regenerated deterministic Climb state through H-033; H-034 remains pending.

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

## Gate concerns

`make check` is not PASS.

Clean candidate evidence: repository test discovery ran 1,948 tests and failed
with two failures and two errors outside the Task10 ecosystem closure. A pure
`04532ec` reproduction hit the same non-ecosystem failure class before Task10
changes:

- `tests.test_prime_rlm_messaging_parity...test_real_daemon_exposes_asterion_rlm_spawn_admission`
- `tests.test_prime_verified_loop...test_all_provider_free_prime_loop_scenarios_pass`
- `tests.test_prime_climb...test_h001_cycle_records_safe_provider_free_outcome`
- `tests.test_prime_session_context_parity...test_real_prime_provider_free_scenarios_match_committed_evidence`

`make promotion-check` is not PASS.

Observed failure: promotion creates an isolated copy that excludes `3th-party/`;
`tests.test_prime_ecosystem_packages` requires the external pinned Prime
ecosystem source and fails closed with `external pinned Prime ecosystem source
is required`.

`git diff --check` passes on the final Task10 candidate patch.

## Claims

- Claim: Prime Gateway `ecosystem.capabilities` exact domain is PASS at 10/10.
- Claim: the closure is provider-free and performs no provider/model operation.
- Claim: every native ecosystem result remains missing.
- Non-claim: `Verified-system-parity` is not PASS.
- Non-claim: `interfaces.operations` is not started.
- Non-claim: H-034 is not passed until repository and promotion gates are clean.
