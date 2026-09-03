# P2 Task 2 Report: fixed long-context workload

## Scope

Implemented the sealed P2 workload and completion contract only. No Docker,
model, network, or benchmark command was run.

## RED evidence

Before the production module existed, ran:

```text
uv run python -m unittest -v tests.test_prime_programmatic_long_context_workload
```

It failed with `ModuleNotFoundError` for
`programmatic_long_context_workload`, proving the new tests exercised a
missing feature.

## Delivered

- Code-owned canonical P2 workload manifest and SHA-256 identity.
- Fixed P2 corpus, oracle, scenario, role, tool, and count facts; callers
  cannot provide alternate corpus or oracle identities.
- Redacted, frozen completion values with exact response/program binding and
  canonical public-safe completion bytes.
- Explicit P1 workload rejection.
- The bounded reducer now imports the P2 constants so its admission identity
  cannot drift from the canonical workload manifest.

## Commit

- `016f5ef feat(prime): define fixed long-context workload`

## Verification

Passed provider-free checks:

```text
uv run python -m unittest -v tests.test_prime_programmatic_long_context_workload tests.test_prime_programmatic_long_context_bounded_receipt tests.test_prime_programmatic_long_context_receipt
uv run ruff check src/asterion/applications/prime_agent/operator/programmatic_long_context_workload.py src/asterion/applications/prime_agent/programmatic_long_context_bounded_receipt.py tests/test_prime_programmatic_long_context_workload.py tests/test_prime_programmatic_long_context_bounded_receipt.py tests/test_prime_programmatic_long_context_receipt.py
uv run pyright src/asterion/applications/prime_agent/operator/programmatic_long_context_workload.py src/asterion/applications/prime_agent/programmatic_long_context_bounded_receipt.py tests/test_prime_programmatic_long_context_workload.py tests/test_prime_programmatic_long_context_bounded_receipt.py tests/test_prime_programmatic_long_context_receipt.py
git diff --check
```

All 13 focused tests passed; Ruff and Pyright reported no issues.
