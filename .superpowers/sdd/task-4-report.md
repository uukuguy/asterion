# P2 Task 4 — sealed worker facade

Implemented separate P2-only Docker and broker-relay facades.  They admit
only the code-owned long-context role, exact workload digest, and exact image;
the Docker command path has no inherited host environment and fixes the P2
entrypoint and seccomp identity.  P1 role/workload values are rejected.

The worker receipt hashes only opaque canonical completion bytes supplied by
the sealed launcher path.  Context exit forcefully waits for engine cleanup
before permitting a cleanup receipt.  The relay is one-at-a-time, revokes on
close or cancellation, rejects subsequent requests, and exposes no provider
surface.

Provider-free verification passed:

```text
uv run python -m unittest -v tests.test_prime_programmatic_long_context_worker tests.test_prime_programmatic_long_context_docker_cli tests.test_prime_programmatic_long_context_launcher_protocol
uv run ruff check src/asterion/applications/prime_agent/operator/programmatic_long_context_worker.py src/asterion/applications/prime_agent/operator/programmatic_long_context_docker_cli.py tests/test_prime_programmatic_long_context_worker.py tests/test_prime_programmatic_long_context_docker_cli.py
uv run pyright src/asterion/applications/prime_agent/operator/programmatic_long_context_worker.py src/asterion/applications/prime_agent/operator/programmatic_long_context_docker_cli.py tests/test_prime_programmatic_long_context_worker.py tests/test_prime_programmatic_long_context_docker_cli.py
git diff --check
```

No Docker daemon, model provider, network, or benchmark execution occurred.

## Review correction

The facade now parses the fixed P2 completion schema and requires canonical
re-encoding byte equality before deriving its result digest.  It retains an
execution-only, one-shot cleanup tombstone; rejects execution after confirmed
destruction; removes any returned lease rejected after launch; and makes the
broker relay consumed after its first request.  Engine removal runs in a
separate task behind a repeated shield loop, so outer cancellation is
re-raised only after removal has completed and destruction state is recorded.

New provider-free regressions cover arbitrary completion bytes, lifecycle
ordering and one-shot cleanup, mismatched returned lease cleanup, sequential
relay reuse, and cancellation during cleanup.  The focused command above now
passes 14 tests.
