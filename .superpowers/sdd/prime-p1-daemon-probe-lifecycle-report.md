# Prime P1 daemon probe lifecycle report

## Scope

Completed the remaining fake-AF_UNIX-daemon lifecycle proof for the private Docker
`/version` projection probe. No real Docker daemon, readiness flow, process spawn,
or external network was used.

## TDD evidence

New lifecycle tests were added and initially run as a focused test selection. The
first run exposed an invalid test seam (an assignment to a slotted method), which
was corrected to patch the exact class method; it was not an implementation
failure. The corrected red/green lifecycle selection passed against the existing
implementation, so no production-source change was warranted.

## Covered behavior

- Fragmented `Transfer-Encoding: chunked` success and exact fixed request bytes.
- Path replacement before connect, after connect, and before successful return.
- Close during an active probe, a competing queued probe, and peer-observed client
  closure.
- Stalled daemon deadline and explicit cancellation, both with client cleanup.
- Aggregate child-failure redaction (including a sentinel), closed aggregate
  rejection, and absent cause/context.

## Verification

```text
uv run python -m unittest -v tests.test_prime_p1_authority_docker_socket tests.test_prime_p1_authority_resources
# Ran 40 tests: OK

uv run ruff check tests/test_prime_p1_authority_docker_socket.py tests/test_prime_p1_authority_resources.py
# All checks passed

git diff --check
# passed
```

## Remaining boundary

This is unit-level fake-daemon evidence only. Native Docker qualification and any
readiness wiring remain intentionally out of scope.
