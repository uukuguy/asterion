# Next-Session Handoff

> Updated: 2026-10-01. Final handoff for this session; the long-running P7 goal remains paused.

## TL;DR

- The global experience foundation is implemented and integrated: immutable observations, persistent game-wide mechanisms, and bounded counterfactual simulation.
- The implementation is verified by focused tests, but real SP80 L1→L2→L3 capability is still unproven. The last pure run stopped at the 10-minute limit in L2.
- Resume with static gates and a short tool-surface check before another live run. Keep offline route injection disabled.

## Where things stand

- Branch: `main`; working tree was clean at handoff.
- Model used in the last live run: `gpt-6.1-sol`.
- Last SP80 run: L1 used a replay-verified 6-step prefix; L2 executed 22 current-level actions and did not complete within 10 minutes; `confirmed_model=false`, `simulator=absent`, no transport or permission errors.
- Focused verification after the integration: 164 P7/Broker/tool/new-module tests passed; official Operator tests: 12 passed; `py_compile` and `git diff --check` passed.
- No P7 process is running.

## What this session delivered

- `d85b03b8`, `f7c51d1b`: immutable `ObservationState` and reserved-field validation.
- `00b4544e`, `b03b6368`: bounded atomic `GameMechanicsStore` with exact-game identity, scope, evidence, conflict, and advisory-only projection.
- `63492b13`, `74f26d89`, `eb43b2ed`, `5a2f8d95`: counterfactual hypothesis branches, divergence diagnostics, final-level WIN boundary, and ARC action-data compatibility.
- `b1a114a3`: Broker, Operator, worker bridge, live RPC, prompt, and integration tests for the new experience path.
- `b6fcc865`, `eab0db3a`: pause checkpoint and status journal.
- `CURRENT-STATE.md`: refreshed structural architecture and evidence boundary.

## Next steps

1. Run `make lint`, `make docs-check`, and the focused P7 suite on the handoff tree.
2. Verify the three new worker tools (`observation_state`, `game_mechanics`, `counterfactual_search`) through the actual bridge without dispatching actions.
3. Resume pure P7 SP80 with `offline_optimization_enabled=false`; track current-level actions, candidate lifecycle, confirmed model, simulator status, prediction matches/conflicts, and whether persistent memory changes the next decision.
4. Compare a cold-start run with a warm-start run before claiming that the agent becomes more skilled through repetition.

## Do not repeat these paths

- Do not treat a replayed L1 prefix or an offline route as a fresh P7 solve.
- Do not inject optimizer routes into capability runs.
- Do not treat a persisted hypothesis, transition ledger, or counterfactual path as an executable certificate.
- Stop after three consecutive failed levels or when a reproducible generic mechanism defect appears; repair first.

## Ready-to-paste commands

```bash
make lint
make docs-check
uv run python -m unittest -q \
  tests.test_prime_p7_global_experience \
  tests.test_prime_p7_game_mechanics \
  tests.test_prime_p7_observation_state \
  tests.test_prime_p7_hypothesis_simulator \
  tests.test_prime_p7_native_broker \
  tests.test_prime_p7_live_command
make asterion-prime-p7-level-witness GAME=sp80 LEVEL=3
```
