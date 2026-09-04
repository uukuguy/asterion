# Prime P1 E2E Task 3 report

## Delivered

- Replaced the image launcher’s built-in solution rewrite with a closed,
  canonical attach-stream protocol: host control, worker model request,
  host-mediated model response, then terminal completion.
- The launcher copies the locked starter, proves the initial oracle failure,
  accepts exactly one `ipython` model cell, requires that cell to mutate the
  workspace, then proves the final oracle success. Terminal facts record only
  the bounded causal metadata; prompt, cell, and output bodies remain private.
- Added the pinned Prime session identity (`prime-agent@0.7.1`) to control and
  model-request frames. The Docker attach adapter validates and relays only
  that exact request and an `ipython` response, and validates the causal
  terminal facts.
- Removed the direct `execution_receipt()` completion route, so a worker cannot
  obtain a successful terminal result without the future host model mediator.

## Test-first evidence

The new launcher protocol test was run before implementation and failed with
the expected missing duplex-frame and deterministic-path assertions.

Passed without Docker, network, credentials, or model execution:

```text
uv run python -m unittest -v tests.test_prime_docker_worker tests.test_prime_docker_cli tests.test_prime_ipython_launcher_protocol
# 47 tests, OK

uv run ruff check src/asterion/applications/prime_agent/operator/docker_worker.py src/asterion/applications/prime_agent/operator/docker_cli.py src/asterion/applications/prime_agent/operator/image/launcher.py tests/test_prime_docker_worker.py tests/test_prime_docker_cli.py tests/test_prime_ipython_launcher_protocol.py
# All checks passed
```

## Remaining boundary

This task deliberately does not start a container or model. The product
verifier in Task 4 must own the live broker-to-attach relay; until then the
direct worker execution route fails closed and cannot claim a bounded result.
