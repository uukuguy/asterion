# Task 2 Fix Report: Expose mechanics prior through the P7 IPython bridge

## Scope

Completed the runtime bridge wiring for `_P7BrokerClient.mechanics_prior()`:

- `P7ClientFacade.mechanics_prior()` invokes the sealed client and accepts only
  a dictionary result, preserving body-free `P7ClientError` failures.
- The generated restricted `p7_client.py` source exposes the exact direct
  function contract, including zero-argument `mechanics_prior()`.
- `P7ClientServer` admits `mechanics_prior` with exactly zero arguments and
  applies the existing JSON serialization and 16 KiB response cap.
- The source validator admits the new method and validates its exact signature,
  while retaining existing method and helper validation.

## Verification

```text
uv run python -m unittest -v tests.test_prime_p7_live_command
Ran 45 tests ... OK

uv run python -m unittest -v tests.test_prime_p7_mechanics_prior tests.test_prime_p7_native_broker
Ran 50 tests ... OK

uv run python -m unittest -v tests.test_prime_p7_native_provider
Ran 19 tests ... OK

uv run ruff check src/asterion/applications/prime/p7/ipython_host.py src/asterion/applications/prime/p7/live.py tests/test_prime_p7_live_command.py
All checks passed!

git diff --check -- src/asterion/applications/prime/p7/ipython_host.py src/asterion/applications/prime/p7/live.py tests/test_prime_p7_live_command.py
PASS
```

Focused tests cover facade construction and result shape, generated-module
exposure, no-argument socket dispatch, malformed argument rejection, and safe
response contents.
