# Ecosystem Task 9 report: provider-free MCP integration

## Result

Implemented and review-fixed the host-owned provider-free MCP fixture path for
Prime ecosystem parity. The Python service launches one operator-injected local
server by direct argv with `shell=False`, an empty environment, private
mode-0600 discovery, fixed deadline/output caps, nonblocking stdout/stderr
multiplexing, one lease/challenge-bound credential refresh, redacted terminal
receipts, replay-safe terminal receipts, and kill/reap cleanup on cancellation,
partial-line stalls, stderr flood, or failure.

The real Prime ecosystem harness now supports `--scenario-package mcp`, passes
an operator-owned local channel into the locked `runMcpFixture(frame, channel)`
surface, instantiates Prime `McpManager`, resolves `mcp.config`, performs the
exact local initialize/list exchange, invokes exactly one host refresh through
Prime's `mcp.refresh` OAuth host handler, shuts down the manager-side channel
and local server, replays the terminal receipt without a second refresh, then
binds/commits the exact gateway effect and emits one body-free deterministic
observation.

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

The independent review then found that the real harness counted only surface
availability and that stdout/stderr handling could block. I added RED coverage
for both before changing implementation:

```text
uv run python -m unittest -v \
  tests.test_control_ecosystem_mcp.TestOwnedMcpFixtureService.test_partial_stdout_line_fails_fast_redacted_and_reaped \
  tests.test_control_ecosystem_mcp.TestOwnedMcpFixtureService.test_stderr_flood_fails_before_deadline_redacted_and_reaped \
  tests.test_prime_ecosystem_mcp.TestPrimeEcosystemMcp.test_real_prime_mcp_receipt_is_safe_exact_and_deterministic
RED: 3 failures
```

The GREEN implementation exposes an owned service channel, drains stdout/stderr
nonblockingly under the shared cap/deadline, and makes the locked Prime module
consume that channel through `McpManager`/OAuth host handlers. The private MCP
observation digest asserts one challenge, one credential refresh, two
initialize messages, one list, one shutdown, zero replay refreshes, and zero
provider operations.

## Verification

```text
make test.prime-ecosystem-mcp.provider-free
PASS: 7 tests
```

```text
make test.prime-ecosystem-mcp.provider-free
PASS: 7 tests
```

The provider-free gate was run twice after the lease-binding fix. Both runs
reported one host credential refresh, one challenge, zero replay refreshes,
zero provider operations, zero model credential reads, and zero owned processes
after close through the asserted receipts/private digest.

```text
npm --prefix packages/typescript/prime-gateway test -- test/ecosystem.test.mjs test/main.test.mjs
PASS: 51 tests
```

```text
temporary detached worktree at 629f44a + Task9 fix patch
make test.prime-ecosystem-mcp.provider-free
PASS: 7 tests

make test.prime-ecosystem-mcp.provider-free
PASS: 7 tests

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
- `packages/typescript/prime-gateway/resources/prime-ecosystem-module.mjs`
- `packages/typescript/prime-gateway/resources/prime-ecosystem-module-lock.json`
- `packages/typescript/prime-gateway/src/ecosystem.ts`
- `packages/typescript/prime-gateway/test/ecosystem.test.mjs`
- `packages/typescript/prime-gateway/test/main.test.mjs`
- `tests/test_control_ecosystem_mcp.py`
- `tests/test_prime_ecosystem_mcp.py`
- `tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs`
- `Makefile` (Task9 MCP target only)
- `.superpowers/sdd/ecosystem-task-9-report.md`

## Concerns

- The working tree contains unrelated pre-existing RLM, long-running, climb,
  and legacy `.superpowers/sdd/task-9-report.md` edits. They are intentionally
  not part of this Task9 commit.
- The main working tree also contains an unrelated dirty
  `prime-artifact-lock.json`; affected TypeScript lock tests were therefore
  verified in a clean committed-equivalent worktree with the committed artifact
  lock preserved.
