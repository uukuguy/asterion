# P7 bridge repair report

## Implemented

- `_IpythonBridgeServer` now injects the live prediction client explicitly and dispatches only the allowlisted P7 methods with exact parameter shapes.
- Method replies use the existing five-field bridge parser contract. Successful values are canonical JSON in `output`; failures are redacted `status: "error"` replies.
- `P7ClientFacade` requires a callable `mechanics_prior` implementation.
- The TypeScript extension registers `p7_mechanics_prior` with an empty bounded schema and evidence-only description. The packaged extension resource was rebuilt from the TypeScript source.

## Verification

- `uv run python -m unittest -v tests.test_prime_p7_live_command.TestPrimeP7LiveCommand.test_ipython_bridge_dispatches_allowlisted_methods_with_canonical_results tests.test_prime_p7_live_command.TestPrimeP7LiveCommand.test_facade_exposes_mechanics_prior_with_safe_mapping_shape` — passed.
- `npm run typecheck` in `packages/typescript/asterion-prime-extension` — passed.
- Focused TypeScript registration tests — passed.
- `uv run ruff check src/asterion/applications/prime/p7/operator.py src/asterion/applications/prime/p7/ipython_host.py tests/test_prime_p7_live_command.py` — passed.
- `git diff --check` — passed.

The full extension test suite retains unrelated pre-existing context-witness harness failures; no live game was run.
