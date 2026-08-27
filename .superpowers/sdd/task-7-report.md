# Task 7 report: Prime ecosystem extensions

## Result

Implemented the provider-free Prime extension evidence package for the four
extension lifecycle scenarios:

- `ecosystem.extensions-lifecycle`
- `ecosystem.extension-state-commands`
- `ecosystem.tools`
- `ecosystem.custom-providers-models`

The fixture extension registers one command, one deterministic local tool and
one provider/model pair. The real Prime harness loads only the sealed extension
entrypoint, runs `start -> session -> shutdown -> teardown`, records one
command state append, invokes the tool locally, resolves the provider/model
registration without invoking it, pre-binds the durable ecosystem effect before
lifecycle execution, then commits an exact succeeded receipt through
`GatewayDurableStore.commitEcosystemEffectResult()`.

No provider, model, credential, network or retained process operation is
performed by this task.

## RED evidence

The focused test was first run before the extension scenario package existed:

```text
uv run python -m unittest -v tests.test_prime_ecosystem_extensions
RED: missing extension scenario support in real-prime-ecosystem.mjs
```

During fix verification, the normal extension path reproduced two real
regressions:

```text
uv run python -m unittest -v tests.test_prime_ecosystem_extensions
RED: command handler failed because Prime command context has no appendEntry()
```

```text
uv run python -m unittest -v tests.test_prime_ecosystem_extensions
RED: pre-bound ecosystem effect replayed through PrimeEcosystemAdapter became uncertain
```

The final implementation uses `pi.appendEntry()` for command-state recording
and commits the module-produced receipt directly through the pre-bound durable
store.

Independent review then exposed missing Task7 coverage. The regression RED was:

```text
uv run python -m unittest -v tests.test_prime_ecosystem_extensions
RED: success receipt missed command_state_digest, reopened_command_state_digest,
reopened_nonterminal_status, failure_matrix_count and failure_matrix_digest.
RED: provider-invocation-attempt variant returned code 0 instead of failing closed.
```

## GREEN evidence

```text
uv run python -m unittest -v tests.test_prime_ecosystem_extensions
PASS: 3 tests
```

The matrix covers exact lifecycle order, command state digest, deterministic
tool output digest, provider/model lookup without invocation, zero provider
operations, zero credential reads, zero retained processes, two-process
determinism, hostile tool output rejection and sentinel-bearing extension error
redaction.

The final Task7 fix additionally proves command state through the existing
`GatewayDurableStore` path: the harness binds the extension effect before the
Prime lifecycle, binds and commits a command-state ecosystem effect using the
command-state digest, reopens the same durable store root, verifies the digest
without lifecycle/module replay, and fences a reopened bound nonterminal effect
as `uncertain` with zero provider/model/process counts.

The complete failure matrix now covers duplicate registrations, teardown throw,
state append failure, reopened nonterminal effect, hostile tool output, provider
invocation attempt and sentinel-bearing extension errors. Public output is fixed
and redacted; only digest/count/status summaries are exposed.

## Gate status

```text
make test.prime-ecosystem-extensions.provider-free
PASS in a detached clean committed-equivalent Task7 worktree:
Python extension tests passed (3 tests).
TypeScript ecosystem tests passed (22 tests).
```

```text
make test.prime-ecosystem-extensions.provider-free
PASS in the same detached clean committed-equivalent Task7 worktree:
Python extension tests passed (3 tests).
TypeScript ecosystem tests passed (22 tests).
```

The shared worktree still contains unrelated artifact-lock/Task8/Task9 dirty
state, so the named gate was intentionally proven in an isolated detached
worktree containing HEAD plus only Task7 fix hunks, with symlinks to existing
offline `3th-party` and `node_modules` resources. No install/fetch/provider/model
call was performed.

## Files

- `tests/fixtures/prime_ecosystem/v1/extensions/exact-extension.ts`
- `tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs`
- `tests/test_prime_ecosystem_extensions.py`
- `.superpowers/sdd/task-7-report.md`

## Concerns

Current HEAD includes the earlier Task8 commit. This report and the new fix
commit should be treated as a Task7-only correction on top of that history.
