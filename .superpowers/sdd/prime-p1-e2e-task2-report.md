# Prime P1 real E2E — Task 2 report

## Delivered

- Expanded the domain-neutral `model.bounded-session` request contract with
  fixed input/output token ceilings and a fixed micro-unit cost ceiling, in
  addition to its existing request, byte, and deadline ceilings.
- Added a body-free terminal usage receipt and made revocation return it.
- Added Prime's selected host-service entry point. Its application-only factory
  resolves `PRIME_MODEL_API_KEY` and `PRIME_MODEL_ID` exclusively from the
  repository `.env`, retains them privately, and issues revocable opaque leases.
- The factory intentionally makes no provider client and no model network call.
  It ignores process/environment injection, so no credentials or provider
  configuration enter framework services or the worker-facing interface.

## Evidence

Passed:

```text
uv run python -m unittest -v tests.test_bounded_model_session tests.test_prime_model_session_host tests.test_prime_model_broker tests.test_prime_coding_fixture_receipt
# 21 tests, OK

uv run ruff check src/asterion/services/bounded_model_session.py src/asterion/services/__init__.py src/asterion/applications/prime_agent/operator/model_session_host.py tests/test_bounded_model_session.py tests/test_prime_model_session_host.py tests/test_prime_model_broker.py tests/test_prime_coding_fixture_receipt.py
# All checks passed

uv run python -m unittest -v tests.test_host_service_registry tests.test_setup_prime_agent tests.test_prime_programmatic_long_context_bounded_receipt
# 33 tests, OK
```

## Remaining boundary

The existing broker remains the framed-byte/cancellation mediator and has no
network provider in this task. A later task must bind real provider usage into
the terminal receipt and enforce its measured token/cost counters before a
provider-backed CLI result can be claimed.
