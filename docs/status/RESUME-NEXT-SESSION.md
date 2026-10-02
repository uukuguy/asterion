# Live Session Checkpoint

> Updated: 2026-10-02 08:14 Asia/Shanghai. Session remains active; this is not a final handoff.

## TL;DR

- P7 persistence, probe eligibility, and replay diagnostics are now fail-closed and independently reviewed.
- ACTION4 still has an unrepresentable moving edge-marker residual; no certificate or model-search authority exists for it.
- A fresh SP80 L1 witness was cancelled by external RPC after 5 current actions; it is not solve evidence.

## Verified changes

- `compile_effect_hypothesis()` rejects `unsupported-residual` candidates.
- `ExperienceInducer.probe_plan()` only reports candidates that compile; rejected candidates remain diagnostic.
- Prefix diagnostics distinguish `prior_prefix_actions` from actual `replayed_prefix_actions`, including partial replay and excluding later live actions.
- Persistence failures retain WorldMap/transition learning while preserving bounded unavailable diagnostics.
- 229 focused Python tests, 32 TypeScript tests (26 pass, 6 external Pi skips), lint, docs-check, and resource parity pass.
- Independent review of the current code reports P0/P1/P2/P3 = 0.

## Live evidence boundary

- Run `p7-live-20261001235840-4c37429319e405352e45c96d` ended with `cleanup=true`, `sealed_trace=false`, `replay_verified=false`, `primitive_action_count=5`, and `external_cancel`; do not count it as a solve.
- Historical L1 prefixes are context or replay evidence, not fresh P7 solving.
- ACTION4 recordings show a stable 20×4 block translation plus 14→0 edge markers whose positions and counts vary. Current DSL cannot safely express that residual.
- Full `make promotion-check` remains unresolved: prior gate was red and a later run was stopped after prolonged no output. Do not claim PASS.

## Next actions

1. Keep unsupported residuals diagnostic-only unless a bounded, context-sensitive rule is backed by multiple fresh transitions and exact replay validation.
2. Diagnose the external RPC cancellation before another live witness; use a bounded fresh run only after the runtime path is responsive.
3. If a new live run succeeds, report current-level actions separately from prior prefix context and replay actions.

## Commands

```bash
uv run python -m unittest -q \
  tests.test_prime_p7_global_experience \
  tests.test_prime_p7_game_mechanics \
  tests.test_prime_p7_experience_induction \
  tests.test_prime_p7_experience_simulator \
  tests.test_prime_p7_experience_e2e \
  tests.test_prime_p7_native_broker \
  tests.test_prime_p7_live_command
npm --prefix packages/typescript/asterion-prime-extension test
make lint
make docs-check
```
