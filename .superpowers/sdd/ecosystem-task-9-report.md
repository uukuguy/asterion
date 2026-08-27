# Ecosystem Task 9 report: provider-free MCP integration

## Result

Implemented the host-owned provider-free MCP fixture path for Prime ecosystem
parity. The Python service launches one operator-injected local server by
direct argv with `shell=False`, an empty environment, private mode-0600
discovery, fixed deadline/output caps, one lease/challenge-bound credential
refresh, redacted terminal receipts, replay-safe terminal receipts, and
kill/reap cleanup on cancellation or failure.

The real Prime ecosystem harness now supports `--scenario-package mcp`, calls
the locked `runMcpFixture()` surface, verifies MCP manager and OAuth surface
availability without provider invocation, then binds/commits the exact gateway
effect and emits one body-free deterministic observation.

No provider/model operation, network fetch, install, manifest executable path,
or model credential read was used.

## TDD evidence

The inherited draft had green focused tests, but missed unbound refresh
rejection. I added a focused RED test before changing production code:

```text
uv run python -m unittest -v tests.test_control_ecosystem_mcp.TestOwnedMcpFixtureService.test_refresh_requires_bound_lease_and_rejects_replay
RED: exit 1; EcosystemMcpError not raised for unbound refresh
```

Then `OwnedMcpFixtureService` was tightened so `start()` registers a one-shot
lease/challenge binding only after the server challenge is validated, and
`refresh()` consumes only that pending binding.

```text
uv run python -m unittest -v tests.test_control_ecosystem_mcp.TestOwnedMcpFixtureService.test_refresh_requires_bound_lease_and_rejects_replay
GREEN: 1 test, PASS
```

## Verification

```text
make test.prime-ecosystem-mcp.provider-free
PASS: 5 tests
```

```text
make test.prime-ecosystem-mcp.provider-free
PASS: 5 tests
```

The provider-free gate was run twice after the lease-binding fix. Both runs
reported one host credential refresh, zero provider operations, zero model
credential reads, and zero owned processes after close through the asserted
receipts.

```text
temporary detached worktree at 1518b99 + staged Task9 patch
make test.prime-ecosystem-mcp.provider-free
PASS: 5 tests

make test.prime-ecosystem-mcp.provider-free
PASS: 5 tests

git diff --check
PASS
```

The temporary verification used copied local ignored build artifacts
(`prime-gateway`/`asterion-runtime` dist and node_modules) and a copied pinned
Prime source checkout, matching the provider-free local prerequisites already
used by the main worktree gate.

## Files

- `src/asterion/control/ecosystem_mcp.py`
- `tests/fixtures/prime_ecosystem/v1/mcp/local-server.mjs`
- `tests/test_control_ecosystem_mcp.py`
- `tests/test_prime_ecosystem_mcp.py`
- `tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs`
- `Makefile` (Task9 MCP target only)
- `.superpowers/sdd/ecosystem-task-9-report.md`

## Concerns

- The working tree contains unrelated pre-existing RLM, long-running, climb,
  and legacy `.superpowers/sdd/task-9-report.md` edits. They are intentionally
  not part of this Task9 commit.
