# P7 retry no-effect guard

Date: 2026-09-26. Scope: the already authorized OFFLINE, same-game failed-level retry path.

## Evidence and objective

G50T's sealed 78-action failure and an operator-interrupted 30-action retry both remained at Level 1. The retry repeated an `ACTION2` test whose settled frame did not change, while state digests changed. A checked multi-action plan later matched local position predictions without proving that the level objective advanced. The interrupted run is diagnostic only: it has no seal or replay-verified result.

The objective is to stop spending multiple actions on an observed no-effect plan and require a falsifiable new probe after repeated no-effect attempts. The guard cannot determine a game's objective or guarantee a solve. It uses only the stable post-action grid and level count, never game IDs, colors, coordinates, source code, or unverified prior runs.

## Options and choice

1. Stronger prompt only: cheap, but the two G50T runs already show that prose alone does not reliably retire a contradicted hypothesis.
2. Ban an action name after a no-effect result: mechanical, but the same action can work in another position.
3. **Chosen:** keep actions available, but stop a checked batch on a no-effect settled frame and, after repeated no-effect instances of the same action in one level, require future attempts of that action to be single-step checked probes. This preserves exploration while making each repeated test falsifiable.

## Contract

- Only the explicit OFFLINE `same-game-failed-attempt` retry mode enables the guard. Normal local solves, official play, and historical prefix replay keep existing behavior.
- A no-effect action has unchanged *settled grid* and unchanged `levels_completed`. Observation/state hashes alone cannot classify it. `RESET` and a level advance clear current-level counts.
- `act_checked` stops its remaining queued items after the first no-effect action and reports `observation-no-change`, distinct from `prediction-mismatch` and success. The executed action remains in the trace and budget.
- After three no-effect occurrences of one action name in a level, a raw `act` of that name returns a public-safe `REPLAN_REQUIRED` with zero dispatched actions. A single-item `act_checked` with an explicit distinguishing expectation may test it again. Other available actions are unaffected. Prior no-effect counts come only from the selected, validated same-game retry advice; the current interrupted G50T run is excluded.
- The prompt distinguishes a matched local mechanic from progress toward the goal. After a no-effect result, it must withdraw or revise the tested hypothesis; after `REPLAN_REQUIRED`, it must use a one-item checked probe or another evidence-based action.
- Counters and blocked calls are private diagnostics; public receipts expose no scene details.

## Verification

Focused zero-model tests cover stable-grid no-effect despite changing state hash, batch stop, raw-call guard threshold, a checked single probe, reset/level scope, normal/offical mode unchanged, and no action/trace entry for blocked calls. Run only those tests and Ruff before one live G50T retry. Compare its actions, objective progression, use of the guard, seal, replay, cleanup, time, and tokens against the two earlier observations. Do not infer broad solve improvement from one run.
