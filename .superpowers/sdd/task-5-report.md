# P2 Task 5 — sealed acceptance orchestration

Added the provider-free P2 acceptance coordinator and a fake full-chain test.
The only success order is attestation, broker admission, release, canonical
result, broker revocation, worker destruction, cleanup receipt, worker boundary
gate, then bounded reducer. The coordinator checks the code-owned P2 role,
workload, profile limits, response/program digest binding, broker identity and
quiescence, and the existing exact boundary/receipt reducers. It rejects
missing services and identity substitutions without exposing private values.

Compatibility reports and their provider-free observations remain unable to
issue bounded evidence; the acceptance test also proves lifecycle objects are
required.

Provider-free verification passed:

```text
uv run python -m unittest -v tests.test_prime_programmatic_long_context_acceptance tests.test_prime_programmatic_long_context_bounded_receipt tests.test_prime_programmatic_long_context_receipt tests.test_prime_programmatic_long_context_worker tests.test_prime_programmatic_long_context_launcher_protocol tests.test_prime_programmatic_long_context_docker_cli tests.test_prime_model_broker tests.test_prime_worker_gate tests.test_prime_restricted_worker
uv run python -m unittest -v tests.test_prime_ipython_launcher_protocol tests.test_prime_docker_worker tests.test_prime_docker_cli tests.test_prime_coding_fixture_receipt tests.test_prime_worker_gate tests.test_prime_model_broker
uv run ruff check src/asterion/applications/prime_agent/programmatic_long_context_acceptance.py tests/test_prime_programmatic_long_context_acceptance.py
uv run pyright src/asterion/applications/prime_agent/programmatic_long_context_acceptance.py tests/test_prime_programmatic_long_context_acceptance.py
git diff --check
```

The first command passed 50 tests; the P1 cross-role command passed 63. No
Docker daemon, model provider, or network execution occurred.
